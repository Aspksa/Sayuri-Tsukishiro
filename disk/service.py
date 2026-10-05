from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import mimetypes
import os
import sqlite3
from typing import BinaryIO, Any, Iterable
import uuid


DISK_SCHEMA_VERSION = 2
CHUNK_SIZE = 1024 * 1024
MAX_FILE_SIZE = 1024 * 1024 * 1024  # 1 ГБ
DEFAULT_RECENT_LIMIT = 30


class DiskService:
    def __init__(self, database_path: Path, storage_root: Path):
        self.database_path = database_path
        self.storage_root = storage_root
        self.objects_dir = storage_root / "objects"
        self.temp_dir = storage_root / "temp"

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database_path, timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA journal_mode = WAL")
        db.execute("PRAGMA synchronous = NORMAL")
        db.execute("PRAGMA busy_timeout = 5000")
        return db

    @contextmanager
    def _session(self):
        db = self._connect()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _validate_name(name: str, *, kind: str) -> str:
        clean = str(name).strip()
        if not clean:
            raise ValueError(f"Имя {kind} не может быть пустым.")
        if clean in {".", ".."} or "/" in clean or "\\" in clean:
            raise ValueError(f"Недопустимое имя {kind}.")
        if any(ord(character) < 32 for character in clean):
            raise ValueError(f"Имя {kind} содержит управляющие символы.")
        if len(clean) > 255:
            raise ValueError(f"Имя {kind} слишком длинное.")
        return clean

    @staticmethod
    def _columns(db: sqlite3.Connection, table: str) -> set[str]:
        return {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}

    @classmethod
    def _ensure_column(cls, db: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        if column not in cls._columns(db, table):
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def initialize(self) -> None:
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        with self._session() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS disk_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS disk_folders (
                    id TEXT PRIMARY KEY,
                    parent_id TEXT NULL REFERENCES disk_folders(id) ON DELETE RESTRICT,
                    name TEXT NOT NULL,
                    name_key TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS disk_files (
                    id TEXT PRIMARY KEY,
                    folder_id TEXT NULL REFERENCES disk_folders(id) ON DELETE RESTRICT,
                    name TEXT NOT NULL,
                    stored_name TEXT NOT NULL UNIQUE,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

            self._ensure_column(db, "disk_folders", "updated_at", "TEXT")
            self._ensure_column(db, "disk_folders", "favorite", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(db, "disk_folders", "trashed_at", "TEXT")
            self._ensure_column(db, "disk_folders", "original_parent_id", "TEXT")
            self._ensure_column(db, "disk_files", "name_key", "TEXT")
            self._ensure_column(db, "disk_files", "updated_at", "TEXT")
            self._ensure_column(db, "disk_files", "favorite", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(db, "disk_files", "trashed_at", "TEXT")
            self._ensure_column(db, "disk_files", "original_folder_id", "TEXT")

            now = self._now()
            db.execute("UPDATE disk_folders SET updated_at = created_at WHERE updated_at IS NULL")
            db.execute("UPDATE disk_files SET updated_at = created_at WHERE updated_at IS NULL")
            for row in db.execute("SELECT id, name FROM disk_files WHERE name_key IS NULL OR name_key = ''").fetchall():
                db.execute("UPDATE disk_files SET name_key = ? WHERE id = ?", (row["name"].casefold(), row["id"]))

            db.execute("DROP INDEX IF EXISTS ux_disk_folder_parent_name")
            db.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS ux_disk_folder_parent_name_active
                ON disk_folders(COALESCE(parent_id, ''), name_key)
                WHERE trashed_at IS NULL
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_disk_file_folder_name_active
                ON disk_files(folder_id, name_key, trashed_at)
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_disk_files_folder_active
                ON disk_files(folder_id, trashed_at)
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_disk_files_sha256
                ON disk_files(sha256)
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS disk_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    action TEXT NOT NULL,
                    object_kind TEXT NOT NULL,
                    object_id TEXT,
                    object_name TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            db.execute(
                """
                INSERT INTO disk_meta(key, value) VALUES('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(DISK_SCHEMA_VERSION),),
            )

    def _require_folder(
        self,
        db: sqlite3.Connection,
        folder_id: str | None,
        *,
        allow_trashed: bool = False,
    ) -> sqlite3.Row | None:
        if folder_id is None:
            return None
        query = "SELECT * FROM disk_folders WHERE id = ?"
        params: tuple[Any, ...] = (folder_id,)
        if not allow_trashed:
            query += " AND trashed_at IS NULL"
        row = db.execute(query, params).fetchone()
        if row is None:
            raise FileNotFoundError("Папка не найдена.")
        return row

    @staticmethod
    def _record_action(
        db: sqlite3.Connection,
        action: str,
        kind: str,
        object_id: str | None,
        name: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        db.execute(
            """
            INSERT INTO disk_actions(created_at, action, object_kind, object_id, object_name, details_json)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                action,
                kind,
                object_id,
                name,
                json.dumps(details or {}, ensure_ascii=False),
            ),
        )

    @staticmethod
    def _file_category(name: str, content_type: str) -> str:
        suffix = Path(name).suffix.lower()
        if content_type.startswith("image/"):
            return "images"
        if content_type.startswith("video/"):
            return "video"
        if content_type.startswith("audio/"):
            return "audio"
        if suffix == ".pdf":
            return "pdf"
        if suffix in {".doc", ".docx", ".odt", ".rtf", ".txt", ".md"}:
            return "documents"
        if suffix in {".xls", ".xlsx", ".ods", ".csv"}:
            return "tables"
        if suffix in {".ppt", ".pptx", ".odp"}:
            return "presentations"
        if suffix in {".zip", ".rar", ".7z", ".tar", ".gz"}:
            return "archives"
        return "other"

    def _folder_size(self, db: sqlite3.Connection, folder_id: str) -> int:
        row = db.execute(
            """
            WITH RECURSIVE descendants(id) AS (
                SELECT id FROM disk_folders WHERE id = ?
                UNION ALL
                SELECT f.id
                FROM disk_folders f
                JOIN descendants d ON f.parent_id = d.id
                WHERE f.trashed_at IS NULL
            )
            SELECT COALESCE(SUM(size_bytes), 0) AS total
            FROM disk_files
            WHERE trashed_at IS NULL
              AND folder_id IN (SELECT id FROM descendants)
            """,
            (folder_id,),
        ).fetchone()
        return int(row["total"] if row else 0)

    def _folder_path(self, db: sqlite3.Connection, folder_id: str | None) -> list[dict[str, str]]:
        path: list[dict[str, str]] = []
        current = folder_id
        seen: set[str] = set()
        while current:
            if current in seen:
                break
            seen.add(current)
            row = db.execute(
                "SELECT id, parent_id, name FROM disk_folders WHERE id = ?",
                (current,),
            ).fetchone()
            if row is None:
                break
            path.append({"id": row["id"], "name": row["name"]})
            current = row["parent_id"]
        path.reverse()
        return path

    def _decorate_folder(self, db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["favorite"] = bool(item.get("favorite"))
        item["size_bytes"] = self._folder_size(db, item["id"])
        item["kind"] = "folder"
        return item

    def _decorate_file(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["favorite"] = bool(item.get("favorite"))
        item["kind"] = "file"
        item["category"] = self._file_category(item["name"], item["content_type"])
        return item

    def create_folder(self, name: str, parent_id: str | None = None) -> dict[str, Any]:
        clean = self._validate_name(name, kind="папки")
        folder_id = uuid.uuid4().hex
        now = self._now()
        try:
            with self._session() as db:
                self._require_folder(db, parent_id)
                db.execute(
                    """
                    INSERT INTO disk_folders(
                        id, parent_id, name, name_key, created_at, updated_at, favorite, trashed_at, original_parent_id
                    ) VALUES(?, ?, ?, ?, ?, ?, 0, NULL, NULL)
                    """,
                    (folder_id, parent_id, clean, clean.casefold(), now, now),
                )
                self._record_action(db, "created", "folder", folder_id, clean, {"parent_id": parent_id})
        except sqlite3.IntegrityError as exc:
            raise FileExistsError("Папка с таким именем уже существует.") from exc
        return {
            "id": folder_id,
            "parent_id": parent_id,
            "name": clean,
            "created_at": now,
            "updated_at": now,
            "favorite": False,
            "size_bytes": 0,
            "kind": "folder",
        }

    def list_entries(
        self,
        folder_id: str | None = None,
        query: str = "",
        *,
        scope: str = "all",
        sort: str = "name",
        direction: str = "asc",
        category: str = "all",
    ) -> dict[str, Any]:
        if scope not in {"all", "favorites", "recent", "trash"}:
            raise ValueError("Неизвестный раздел Диска.")
        if sort not in {"name", "date", "size", "type"}:
            raise ValueError("Неизвестная сортировка.")
        if direction not in {"asc", "desc"}:
            raise ValueError("Неизвестное направление сортировки.")

        search = query.strip().casefold()

        with self._session() as db:
            if scope == "all":
                self._require_folder(db, folder_id)
                folder_rows = db.execute(
                    """
                    SELECT id, parent_id, name, created_at, updated_at, favorite, trashed_at
                    FROM disk_folders
                    WHERE parent_id IS ? AND trashed_at IS NULL
                    """,
                    (folder_id,),
                ).fetchall()
                file_rows = db.execute(
                    """
                    SELECT id, folder_id, name, content_type, size_bytes, sha256,
                           created_at, updated_at, favorite, trashed_at
                    FROM disk_files
                    WHERE folder_id IS ? AND trashed_at IS NULL
                    """,
                    (folder_id,),
                ).fetchall()
            elif scope == "favorites":
                folder_rows = db.execute(
                    """
                    SELECT id, parent_id, name, created_at, updated_at, favorite, trashed_at
                    FROM disk_folders
                    WHERE favorite = 1 AND trashed_at IS NULL
                    """
                ).fetchall()
                file_rows = db.execute(
                    """
                    SELECT id, folder_id, name, content_type, size_bytes, sha256,
                           created_at, updated_at, favorite, trashed_at
                    FROM disk_files
                    WHERE favorite = 1 AND trashed_at IS NULL
                    """
                ).fetchall()
            elif scope == "recent":
                folder_rows = db.execute(
                    """
                    SELECT id, parent_id, name, created_at, updated_at, favorite, trashed_at
                    FROM disk_folders
                    WHERE trashed_at IS NULL
                    ORDER BY updated_at DESC LIMIT ?
                    """,
                    (DEFAULT_RECENT_LIMIT,),
                ).fetchall()
                file_rows = db.execute(
                    """
                    SELECT id, folder_id, name, content_type, size_bytes, sha256,
                           created_at, updated_at, favorite, trashed_at
                    FROM disk_files
                    WHERE trashed_at IS NULL
                    ORDER BY updated_at DESC LIMIT ?
                    """,
                    (DEFAULT_RECENT_LIMIT,),
                ).fetchall()
            else:
                folder_rows = db.execute(
                    """
                    SELECT id, parent_id, name, created_at, updated_at, favorite, trashed_at
                    FROM disk_folders
                    WHERE trashed_at IS NOT NULL
                      AND (
                          parent_id IS NULL
                          OR parent_id NOT IN (
                              SELECT id FROM disk_folders WHERE trashed_at IS NOT NULL
                          )
                      )
                    """
                ).fetchall()
                file_rows = db.execute(
                    """
                    SELECT id, folder_id, name, content_type, size_bytes, sha256,
                           created_at, updated_at, favorite, trashed_at
                    FROM disk_files
                    WHERE trashed_at IS NOT NULL
                      AND (
                          folder_id IS NULL
                          OR folder_id NOT IN (
                              SELECT id FROM disk_folders WHERE trashed_at IS NOT NULL
                          )
                      )
                    """
                ).fetchall()

            folders = [self._decorate_folder(db, row) for row in folder_rows]
            files = [self._decorate_file(row) for row in file_rows]

            if search:
                folders = [item for item in folders if search in item["name"].casefold()]
                files = [item for item in files if search in item["name"].casefold()]

            if category != "all":
                if category == "folders":
                    files = []
                else:
                    folders = []
                    files = [item for item in files if item["category"] == category]

            reverse = direction == "desc"

            def sort_key(item: dict[str, Any]):
                if sort == "date":
                    return item.get("updated_at") or item.get("created_at") or ""
                if sort == "size":
                    return int(item.get("size_bytes") or 0)
                if sort == "type":
                    return (item.get("category") or "folder", item["name"].casefold())
                return item["name"].casefold()

            folders.sort(key=sort_key, reverse=reverse)
            files.sort(key=sort_key, reverse=reverse)

            stats = db.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM disk_files WHERE trashed_at IS NULL) AS files,
                    (SELECT COUNT(*) FROM disk_folders WHERE trashed_at IS NULL) AS folders,
                    (SELECT COALESCE(SUM(size_bytes), 0) FROM disk_files WHERE trashed_at IS NULL) AS bytes,
                    (SELECT COUNT(*) FROM disk_files WHERE trashed_at IS NOT NULL) +
                    (SELECT COUNT(*) FROM disk_folders WHERE trashed_at IS NOT NULL) AS trash_items,
                    (SELECT COUNT(*) FROM disk_files WHERE favorite = 1 AND trashed_at IS NULL) +
                    (SELECT COUNT(*) FROM disk_folders WHERE favorite = 1 AND trashed_at IS NULL) AS favorites
                """
            ).fetchone()

            breadcrumb = self._folder_path(db, folder_id) if scope == "all" else []

        return {
            "folder_id": folder_id,
            "scope": scope,
            "breadcrumb": breadcrumb,
            "folders": folders,
            "files": files,
            "stats": {
                "files": int(stats["files"]),
                "folders": int(stats["folders"]),
                "bytes": int(stats["bytes"]),
                "trash_items": int(stats["trash_items"]),
                "favorites": int(stats["favorites"]),
                "max_file_size": MAX_FILE_SIZE,
            },
        }

    def store_stream(
        self,
        *,
        name: str,
        content_type: str | None,
        size_bytes: int,
        stream: BinaryIO,
        folder_id: str | None = None,
    ) -> dict[str, Any]:
        clean = self._validate_name(name, kind="файла")
        if size_bytes < 0:
            raise ValueError("Некорректный размер файла.")
        if size_bytes > MAX_FILE_SIZE:
            raise ValueError("Файл превышает лимит 1 ГБ.")

        with self._session() as db:
            self._require_folder(db, folder_id)

        file_id = uuid.uuid4().hex
        stored_name = file_id
        temp_path = self.temp_dir / f"{file_id}.part"
        final_path = self.objects_dir / stored_name
        digest = hashlib.sha256()
        remaining = size_bytes
        written = 0

        try:
            with temp_path.open("wb") as target:
                while remaining > 0:
                    chunk = stream.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        raise ValueError("Передача файла завершилась раньше заявленного размера.")
                    target.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
                    remaining -= len(chunk)
                target.flush()
                os.fsync(target.fileno())

            if written != size_bytes:
                raise ValueError("Размер сохранённого файла не совпал с ожидаемым.")

            temp_path.replace(final_path)
            now = self._now()
            detected_type = content_type or mimetypes.guess_type(clean)[0] or "application/octet-stream"
            sha256 = digest.hexdigest()

            try:
                with self._session() as db:
                    duplicate = db.execute(
                        """
                        SELECT id, name FROM disk_files
                        WHERE sha256 = ? AND trashed_at IS NULL
                        ORDER BY created_at ASC LIMIT 1
                        """,
                        (sha256,),
                    ).fetchone()
                    conflict = db.execute(
                        """
                        SELECT id FROM disk_files
                        WHERE folder_id IS ? AND name_key = ? AND trashed_at IS NULL
                        LIMIT 1
                        """,
                        (folder_id, clean.casefold()),
                    ).fetchone()
                    if conflict:
                        raise FileExistsError("Файл с таким именем уже существует в этой папке.")
                    db.execute(
                        """
                        INSERT INTO disk_files(
                            id, folder_id, name, name_key, stored_name, content_type,
                            size_bytes, sha256, created_at, updated_at,
                            favorite, trashed_at, original_folder_id
                        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL)
                        """,
                        (
                            file_id,
                            folder_id,
                            clean,
                            clean.casefold(),
                            stored_name,
                            detected_type,
                            size_bytes,
                            sha256,
                            now,
                            now,
                        ),
                    )
                    self._record_action(
                        db,
                        "uploaded",
                        "file",
                        file_id,
                        clean,
                        {
                            "folder_id": folder_id,
                            "size_bytes": size_bytes,
                            "sha256": sha256,
                            "duplicate_of": duplicate["id"] if duplicate else None,
                        },
                    )
            except Exception:
                final_path.unlink(missing_ok=True)
                raise
        finally:
            temp_path.unlink(missing_ok=True)

        return {
            "id": file_id,
            "folder_id": folder_id,
            "name": clean,
            "content_type": detected_type,
            "size_bytes": size_bytes,
            "sha256": sha256,
            "created_at": now,
            "updated_at": now,
            "favorite": False,
            "duplicate_of": duplicate["id"] if duplicate else None,
        }

    def get_file(self, file_id: str, *, allow_trashed: bool = False) -> dict[str, Any]:
        with self._session() as db:
            query = """
                SELECT id, folder_id, name, stored_name, content_type, size_bytes, sha256,
                       created_at, updated_at, favorite, trashed_at, original_folder_id
                FROM disk_files WHERE id = ?
            """
            if not allow_trashed:
                query += " AND trashed_at IS NULL"
            row = db.execute(query, (file_id,)).fetchone()
        if row is None:
            raise FileNotFoundError("Файл не найден.")
        item = dict(row)
        path = (self.objects_dir / item.pop("stored_name")).resolve()
        if path.parent != self.objects_dir.resolve() or not path.is_file():
            raise FileNotFoundError("Физический файл отсутствует в хранилище.")
        item["favorite"] = bool(item["favorite"])
        item["path"] = path
        item["category"] = self._file_category(item["name"], item["content_type"])
        return item

    def properties(self, kind: str, object_id: str) -> dict[str, Any]:
        if kind not in {"file", "folder"}:
            raise ValueError("Неизвестный тип объекта.")

        with self._session() as db:
            if kind == "file":
                row = db.execute(
                    """
                    SELECT id, folder_id, name, content_type, size_bytes, sha256,
                           created_at, updated_at, favorite, trashed_at, original_folder_id
                    FROM disk_files WHERE id = ?
                    """,
                    (object_id,),
                ).fetchone()
                if row is None:
                    raise FileNotFoundError("Файл не найден.")
                item = self._decorate_file(row)
                parent_id = item["folder_id"]
                duplicate_count = db.execute(
                    "SELECT COUNT(*) AS count FROM disk_files WHERE sha256 = ? AND id <> ?",
                    (item["sha256"], object_id),
                ).fetchone()["count"]
                item["duplicate_count"] = int(duplicate_count)
            else:
                row = db.execute(
                    """
                    SELECT id, parent_id, name, created_at, updated_at, favorite, trashed_at, original_parent_id
                    FROM disk_folders WHERE id = ?
                    """,
                    (object_id,),
                ).fetchone()
                if row is None:
                    raise FileNotFoundError("Папка не найдена.")
                item = self._decorate_folder(db, row)
                parent_id = item["parent_id"]
                counts = db.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM disk_files WHERE folder_id = ? AND trashed_at IS NULL) AS files,
                        (SELECT COUNT(*) FROM disk_folders WHERE parent_id = ? AND trashed_at IS NULL) AS folders
                    """,
                    (object_id, object_id),
                ).fetchone()
                item["direct_files"] = int(counts["files"])
                item["direct_folders"] = int(counts["folders"])

            item["path"] = self._folder_path(db, parent_id)
        return item

    def rename(self, kind: str, object_id: str, name: str) -> dict[str, Any]:
        clean = self._validate_name(name, kind="объекта")
        now = self._now()
        try:
            with self._session() as db:
                if kind == "file":
                    row = db.execute(
                        "SELECT name, folder_id FROM disk_files WHERE id = ? AND trashed_at IS NULL",
                        (object_id,),
                    ).fetchone()
                    if row is None:
                        raise FileNotFoundError("Файл не найден.")
                    conflict = db.execute(
                        """
                        SELECT id FROM disk_files
                        WHERE folder_id IS ? AND name_key = ? AND id <> ? AND trashed_at IS NULL
                        LIMIT 1
                        """,
                        (row["folder_id"], clean.casefold(), object_id),
                    ).fetchone()
                    if conflict:
                        raise FileExistsError("Файл с таким именем уже существует в этой папке.")
                    old_name = row["name"]
                    db.execute(
                        "UPDATE disk_files SET name = ?, name_key = ?, updated_at = ? WHERE id = ?",
                        (clean, clean.casefold(), now, object_id),
                    )
                elif kind == "folder":
                    row = db.execute(
                        "SELECT name FROM disk_folders WHERE id = ? AND trashed_at IS NULL",
                        (object_id,),
                    ).fetchone()
                    if row is None:
                        raise FileNotFoundError("Папка не найдена.")
                    old_name = row["name"]
                    db.execute(
                        "UPDATE disk_folders SET name = ?, name_key = ?, updated_at = ? WHERE id = ?",
                        (clean, clean.casefold(), now, object_id),
                    )
                else:
                    raise ValueError("Неизвестный тип объекта.")
                self._record_action(
                    db,
                    "renamed",
                    kind,
                    object_id,
                    clean,
                    {"old_name": old_name, "new_name": clean},
                )
        except sqlite3.IntegrityError as exc:
            raise FileExistsError("Объект с таким именем уже существует.") from exc
        return {"status": "переименовано", "id": object_id, "name": clean}

    def _is_descendant(self, db: sqlite3.Connection, folder_id: str, possible_descendant: str) -> bool:
        row = db.execute(
            """
            WITH RECURSIVE descendants(id) AS (
                SELECT id FROM disk_folders WHERE parent_id = ? AND trashed_at IS NULL
                UNION ALL
                SELECT f.id FROM disk_folders f
                JOIN descendants d ON f.parent_id = d.id
                WHERE f.trashed_at IS NULL
            )
            SELECT 1 FROM descendants WHERE id = ? LIMIT 1
            """,
            (folder_id, possible_descendant),
        ).fetchone()
        return row is not None

    def move(self, items: Iterable[dict[str, str]], destination_id: str | None) -> dict[str, Any]:
        normalized = list(items)
        if not normalized:
            raise ValueError("Не выбраны объекты для перемещения.")
        now = self._now()

        try:
            with self._session() as db:
                self._require_folder(db, destination_id)
                moved = 0
                for item in normalized:
                    kind = item.get("kind")
                    object_id = item.get("id")
                    if not object_id or kind not in {"file", "folder"}:
                        raise ValueError("Некорректный объект перемещения.")

                    if kind == "file":
                        row = db.execute(
                            "SELECT name, name_key, folder_id FROM disk_files WHERE id = ? AND trashed_at IS NULL",
                            (object_id,),
                        ).fetchone()
                        if row is None:
                            raise FileNotFoundError("Файл не найден.")
                        conflict = db.execute(
                            """
                            SELECT id FROM disk_files
                            WHERE folder_id IS ? AND name_key = ? AND id <> ? AND trashed_at IS NULL
                            LIMIT 1
                            """,
                            (destination_id, row["name_key"], object_id),
                        ).fetchone()
                        if conflict:
                            raise FileExistsError("В папке назначения уже есть файл с таким именем.")
                        db.execute(
                            "UPDATE disk_files SET folder_id = ?, updated_at = ? WHERE id = ?",
                            (destination_id, now, object_id),
                        )
                        name = row["name"]
                    else:
                        row = db.execute(
                            "SELECT name, parent_id FROM disk_folders WHERE id = ? AND trashed_at IS NULL",
                            (object_id,),
                        ).fetchone()
                        if row is None:
                            raise FileNotFoundError("Папка не найдена.")
                        if destination_id == object_id:
                            raise ValueError("Нельзя переместить папку саму в себя.")
                        if destination_id and self._is_descendant(db, object_id, destination_id):
                            raise ValueError("Нельзя переместить папку внутрь её дочерней папки.")
                        db.execute(
                            "UPDATE disk_folders SET parent_id = ?, updated_at = ? WHERE id = ?",
                            (destination_id, now, object_id),
                        )
                        name = row["name"]

                    self._record_action(
                        db,
                        "moved",
                        kind,
                        object_id,
                        name,
                        {"destination_id": destination_id},
                    )
                    moved += 1
        except sqlite3.IntegrityError as exc:
            raise FileExistsError("В папке назначения уже есть папка с таким именем.") from exc
        return {"status": "перемещено", "count": moved}

    def set_favorite(self, items: Iterable[dict[str, str]], favorite: bool) -> dict[str, Any]:
        normalized = list(items)
        if not normalized:
            raise ValueError("Не выбраны объекты.")
        now = self._now()
        updated = 0
        with self._session() as db:
            for item in normalized:
                kind = item.get("kind")
                object_id = item.get("id")
                if kind == "file":
                    row = db.execute(
                        "SELECT name FROM disk_files WHERE id = ? AND trashed_at IS NULL",
                        (object_id,),
                    ).fetchone()
                    if row is None:
                        raise FileNotFoundError("Файл не найден.")
                    db.execute(
                        "UPDATE disk_files SET favorite = ?, updated_at = ? WHERE id = ?",
                        (int(favorite), now, object_id),
                    )
                elif kind == "folder":
                    row = db.execute(
                        "SELECT name FROM disk_folders WHERE id = ? AND trashed_at IS NULL",
                        (object_id,),
                    ).fetchone()
                    if row is None:
                        raise FileNotFoundError("Папка не найдена.")
                    db.execute(
                        "UPDATE disk_folders SET favorite = ?, updated_at = ? WHERE id = ?",
                        (int(favorite), now, object_id),
                    )
                else:
                    raise ValueError("Неизвестный тип объекта.")
                self._record_action(
                    db,
                    "favorite_on" if favorite else "favorite_off",
                    kind,
                    object_id,
                    row["name"],
                )
                updated += 1
        return {"status": "обновлено", "count": updated, "favorite": favorite}

    def trash(self, items: Iterable[dict[str, str]]) -> dict[str, Any]:
        normalized = list(items)
        if not normalized:
            raise ValueError("Не выбраны объекты.")
        now = self._now()
        count = 0
        with self._session() as db:
            for item in normalized:
                kind = item.get("kind")
                object_id = item.get("id")
                if kind == "file":
                    row = db.execute(
                        "SELECT name, folder_id FROM disk_files WHERE id = ? AND trashed_at IS NULL",
                        (object_id,),
                    ).fetchone()
                    if row is None:
                        raise FileNotFoundError("Файл не найден.")
                    db.execute(
                        """
                        UPDATE disk_files
                        SET original_folder_id = folder_id, trashed_at = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (now, now, object_id),
                    )
                elif kind == "folder":
                    row = db.execute(
                        "SELECT name, parent_id FROM disk_folders WHERE id = ? AND trashed_at IS NULL",
                        (object_id,),
                    ).fetchone()
                    if row is None:
                        raise FileNotFoundError("Папка не найдена.")
                    descendants = [
                        child["id"]
                        for child in db.execute(
                            """
                            WITH RECURSIVE tree(id) AS (
                                SELECT id FROM disk_folders WHERE id = ?
                                UNION ALL
                                SELECT f.id FROM disk_folders f
                                JOIN tree t ON f.parent_id = t.id
                                WHERE f.trashed_at IS NULL
                            )
                            SELECT id FROM tree
                            """,
                            (object_id,),
                        ).fetchall()
                    ]
                    placeholders = ",".join("?" for _ in descendants)
                    db.execute(
                        """
                        UPDATE disk_folders
                        SET original_parent_id = CASE WHEN id = ? THEN parent_id ELSE original_parent_id END,
                            trashed_at = ?, updated_at = ?
                        WHERE id IN (""" + placeholders + ")",
                        (object_id, now, now, *descendants),
                    )
                    db.execute(
                        """
                        UPDATE disk_files
                        SET original_folder_id = folder_id, trashed_at = ?, updated_at = ?
                        WHERE trashed_at IS NULL AND folder_id IN (""" + placeholders + ")",
                        (now, now, *descendants),
                    )
                else:
                    raise ValueError("Неизвестный тип объекта.")
                self._record_action(db, "trashed", kind, object_id, row["name"])
                count += 1
        return {"status": "в корзине", "count": count}

    def restore(self, items: Iterable[dict[str, str]]) -> dict[str, Any]:
        normalized = list(items)
        if not normalized:
            raise ValueError("Не выбраны объекты.")
        now = self._now()
        restored = 0
        try:
            with self._session() as db:
                for item in normalized:
                    kind = item.get("kind")
                    object_id = item.get("id")
                    if kind == "file":
                        row = db.execute(
                            "SELECT name, original_folder_id FROM disk_files WHERE id = ? AND trashed_at IS NOT NULL",
                            (object_id,),
                        ).fetchone()
                        if row is None:
                            raise FileNotFoundError("Файл в корзине не найден.")
                        destination = row["original_folder_id"]
                        if destination:
                            try:
                                self._require_folder(db, destination)
                            except FileNotFoundError:
                                destination = None
                        db.execute(
                            """
                            UPDATE disk_files
                            SET folder_id = ?, original_folder_id = NULL, trashed_at = NULL, updated_at = ?
                            WHERE id = ?
                            """,
                            (destination, now, object_id),
                        )
                    elif kind == "folder":
                        row = db.execute(
                            "SELECT name, original_parent_id FROM disk_folders WHERE id = ? AND trashed_at IS NOT NULL",
                            (object_id,),
                        ).fetchone()
                        if row is None:
                            raise FileNotFoundError("Папка в корзине не найдена.")
                        destination = row["original_parent_id"]
                        if destination:
                            try:
                                self._require_folder(db, destination)
                            except FileNotFoundError:
                                destination = None
                        descendants = [
                            child["id"]
                            for child in db.execute(
                                """
                                WITH RECURSIVE tree(id) AS (
                                    SELECT id FROM disk_folders WHERE id = ?
                                    UNION ALL
                                    SELECT f.id FROM disk_folders f JOIN tree t ON f.parent_id = t.id
                                )
                                SELECT id FROM tree
                                """,
                                (object_id,),
                            ).fetchall()
                        ]
                        placeholders = ",".join("?" for _ in descendants)
                        db.execute(
                            "UPDATE disk_folders SET parent_id = ? WHERE id = ?",
                            (destination, object_id),
                        )
                        db.execute(
                            "UPDATE disk_folders SET trashed_at = NULL, updated_at = ?, original_parent_id = NULL WHERE id IN (" + placeholders + ")",
                            (now, *descendants),
                        )
                        db.execute(
                            "UPDATE disk_files SET trashed_at = NULL, updated_at = ?, original_folder_id = NULL WHERE folder_id IN (" + placeholders + ")",
                            (now, *descendants),
                        )
                    else:
                        raise ValueError("Неизвестный тип объекта.")
                    self._record_action(db, "restored", kind, object_id, row["name"])
                    restored += 1
        except sqlite3.IntegrityError as exc:
            raise FileExistsError("Не удалось восстановить: в исходной папке уже есть объект с таким именем.") from exc
        return {"status": "восстановлено", "count": restored}

    def delete_permanently(self, items: Iterable[dict[str, str]]) -> dict[str, Any]:
        normalized = list(items)
        if not normalized:
            raise ValueError("Не выбраны объекты.")
        files_to_delete: list[Path] = []
        count = 0

        with self._session() as db:
            for item in normalized:
                kind = item.get("kind")
                object_id = item.get("id")
                if kind == "file":
                    row = db.execute(
                        "SELECT name, stored_name FROM disk_files WHERE id = ? AND trashed_at IS NOT NULL",
                        (object_id,),
                    ).fetchone()
                    if row is None:
                        raise FileNotFoundError("Файл в корзине не найден.")
                    files_to_delete.append(self.objects_dir / row["stored_name"])
                    db.execute("DELETE FROM disk_files WHERE id = ?", (object_id,))
                elif kind == "folder":
                    row = db.execute(
                        "SELECT name FROM disk_folders WHERE id = ? AND trashed_at IS NOT NULL",
                        (object_id,),
                    ).fetchone()
                    if row is None:
                        raise FileNotFoundError("Папка в корзине не найдена.")
                    descendants = [
                        child["id"]
                        for child in db.execute(
                            """
                            WITH RECURSIVE tree(id) AS (
                                SELECT id FROM disk_folders WHERE id = ?
                                UNION ALL
                                SELECT f.id FROM disk_folders f JOIN tree t ON f.parent_id = t.id
                            )
                            SELECT id FROM tree
                            """,
                            (object_id,),
                        ).fetchall()
                    ]
                    placeholders = ",".join("?" for _ in descendants)
                    file_rows = db.execute(
                        "SELECT stored_name FROM disk_files WHERE folder_id IN (" + placeholders + ")",
                        tuple(descendants),
                    ).fetchall()
                    files_to_delete.extend(self.objects_dir / file_row["stored_name"] for file_row in file_rows)
                    db.execute("DELETE FROM disk_files WHERE folder_id IN (" + placeholders + ")", tuple(descendants))
                    for folder_to_delete in reversed(descendants):
                        db.execute("DELETE FROM disk_folders WHERE id = ?", (folder_to_delete,))
                else:
                    raise ValueError("Неизвестный тип объекта.")
                self._record_action(db, "deleted", kind, object_id, row["name"])
                count += 1

        for path in files_to_delete:
            path.unlink(missing_ok=True)
        return {"status": "удалено навсегда", "count": count}

    def folder_tree(self) -> list[dict[str, Any]]:
        with self._session() as db:
            rows = db.execute(
                """
                SELECT id, parent_id, name
                FROM disk_folders
                WHERE trashed_at IS NULL
                ORDER BY name_key
                """
            ).fetchall()
            by_id = {row["id"]: dict(row) for row in rows}

        def build_path(folder_id: str) -> tuple[list[str], int]:
            names: list[str] = []
            current = by_id.get(folder_id)
            seen: set[str] = set()
            while current and current["id"] not in seen:
                seen.add(current["id"])
                names.append(current["name"])
                current = by_id.get(current["parent_id"])
            names.reverse()
            return names, max(0, len(names) - 1)

        result = []
        for row in by_id.values():
            names, depth = build_path(row["id"])
            result.append(
                {
                    "id": row["id"],
                    "parent_id": row["parent_id"],
                    "name": row["name"],
                    "path": " / ".join(names),
                    "depth": depth,
                }
            )
        result.sort(key=lambda item: item["path"].casefold())
        return result

    def recent_actions(self, limit: int = 30) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 100)
        with self._session() as db:
            rows = db.execute(
                """
                SELECT id, created_at, action, object_kind, object_id, object_name, details_json
                FROM disk_actions
                ORDER BY id DESC LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        actions = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item.pop("details_json"))
            actions.append(item)
        return actions

    def health(self) -> dict[str, Any]:
        listing = self.list_entries()
        return {
            "status": "готово",
            "status_code": "ready",
            "schema_version": DISK_SCHEMA_VERSION,
            "files": listing["stats"]["files"],
            "folders": listing["stats"]["folders"],
            "bytes": listing["stats"]["bytes"],
            "trash_items": listing["stats"]["trash_items"],
            "favorites": listing["stats"]["favorites"],
            "max_file_size": MAX_FILE_SIZE,
            "storage_path": str(self.storage_root),
        }
