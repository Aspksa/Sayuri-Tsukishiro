from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import mimetypes
import os
import re
import sqlite3
import zipfile
import xml.etree.ElementTree as ET
from typing import BinaryIO, Any, Iterable
import uuid

from .dna import DNA_ANALYZER_VERSION, DocumentDNAAnalyzer
from .dna_advanced import ADVANCED_DNA_VERSION, AdvancedDNAEngine
from .dna_evolution import EVOLUTION_ENGINE_VERSION, DNAEvolutionEngine
from .dna_spatial import SPATIAL_ENGINE_VERSION, SpatialDNAEngine


DISK_SCHEMA_VERSION = 7
CHUNK_SIZE = 1024 * 1024
MAX_FILE_SIZE = 1024 * 1024 * 1024  # 1 ГБ
MAX_PREVIEW_XML_BYTES = 16 * 1024 * 1024
DEFAULT_RECENT_LIMIT = 30
REANALYZE_COOLDOWN_SECONDS = 10


class DiskService:
    def __init__(self, database_path: Path, storage_root: Path):
        self.database_path = database_path
        self.storage_root = storage_root
        self.objects_dir = storage_root / "objects"
        self.temp_dir = storage_root / "temp"
        self.dna_analyzer = DocumentDNAAnalyzer()
        self.advanced_dna = AdvancedDNAEngine()
        self.evolution_dna = DNAEvolutionEngine()
        project_root = database_path.parent.parent
        self.spatial_dna = SpatialDNAEngine(
            tessdata_path=project_root / ".runtime" / "tessdata",
        )

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
                CREATE TABLE IF NOT EXISTS disk_dna (
                    file_id TEXT PRIMARY KEY REFERENCES disk_files(id) ON DELETE CASCADE,
                    sha256 TEXT NOT NULL,
                    source_updated_at TEXT NOT NULL,
                    analyzer_version TEXT NOT NULL,
                    analyzed_at TEXT NOT NULL,
                    dna_json TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS disk_dna_spatial (
                    file_id TEXT PRIMARY KEY REFERENCES disk_files(id) ON DELETE CASCADE,
                    sha256 TEXT NOT NULL,
                    engine_version TEXT NOT NULL,
                    analyzed_at TEXT NOT NULL,
                    spatial_json TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_disk_dna_spatial_sha
                ON disk_dna_spatial(sha256, engine_version)
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS disk_dna_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id TEXT NOT NULL REFERENCES disk_files(id) ON DELETE CASCADE,
                    version_no INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    source_updated_at TEXT NOT NULL,
                    analyzer_version TEXT NOT NULL,
                    analyzed_at TEXT NOT NULL,
                    dna_json TEXT NOT NULL,
                    UNIQUE(file_id, version_no)
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_disk_dna_history_file
                ON disk_dna_history(file_id, version_no DESC)
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS disk_dna_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id TEXT NOT NULL REFERENCES disk_files(id) ON DELETE CASCADE,
                    fact_id TEXT,
                    action TEXT NOT NULL,
                    corrected_value_json TEXT,
                    note TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_disk_dna_feedback_file
                ON disk_dna_feedback(file_id, id)
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS disk_dna_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id TEXT NOT NULL REFERENCES disk_files(id) ON DELETE CASCADE,
                    sequence_no INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    previous_chain_hash TEXT,
                    chain_hash TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(file_id, sequence_no)
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_disk_dna_ledger_file
                ON disk_dna_ledger(file_id, sequence_no)
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS disk_dna_correction_rules (
                    fact_type TEXT NOT NULL,
                    original_canonical TEXT NOT NULL,
                    corrected_json TEXT NOT NULL,
                    supporting_files_json TEXT NOT NULL DEFAULT '[]',
                    support_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(fact_type, original_canonical, corrected_json)
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS disk_dna_entities (
                    entity_id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    canonical_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    document_count INTEGER NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL DEFAULT 0.0,
                    attributes_json TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(category, canonical_id)
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS disk_dna_entity_mentions (
                    file_id TEXT NOT NULL REFERENCES disk_files(id) ON DELETE CASCADE,
                    entity_id TEXT NOT NULL REFERENCES disk_dna_entities(entity_id) ON DELETE CASCADE,
                    fact_ids_json TEXT NOT NULL DEFAULT '[]',
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    confidence REAL NOT NULL DEFAULT 0.0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(file_id, entity_id)
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_disk_dna_entity_mentions_entity
                ON disk_dna_entity_mentions(entity_id, file_id)
                """
            )
            db.execute(
                """
                INSERT INTO disk_dna_history(
                    file_id, version_no, sha256, source_updated_at,
                    analyzer_version, analyzed_at, dna_json
                )
                SELECT
                    d.file_id, 1, d.sha256, d.source_updated_at,
                    d.analyzer_version, d.analyzed_at, d.dna_json
                FROM disk_dna d
                WHERE NOT EXISTS (
                    SELECT 1 FROM disk_dna_history h WHERE h.file_id = d.file_id
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

    def _folder_stats(self, db: sqlite3.Connection, folder_id: str) -> dict[str, int]:
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
            SELECT
                COUNT(*) AS file_count,
                COALESCE(SUM(size_bytes), 0) AS total
            FROM disk_files
            WHERE trashed_at IS NULL
              AND folder_id IN (SELECT id FROM descendants)
            """,
            (folder_id,),
        ).fetchone()
        return {
            "file_count": int(row["file_count"] if row else 0),
            "size_bytes": int(row["total"] if row else 0),
        }

    def _folder_size(self, db: sqlite3.Connection, folder_id: str) -> int:
        return self._folder_stats(db, folder_id)["size_bytes"]

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
        stats = self._folder_stats(db, item["id"])
        item["size_bytes"] = stats["size_bytes"]
        item["file_count"] = stats["file_count"]
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
            "file_count": 0,
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
        moves: list[dict[str, Any]] = []

        try:
            with self._session() as db:
                destination_row = self._require_folder(db, destination_id)
                destination_name = destination_row["name"] if destination_row else "Диск Sayuri"

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
                        source_id = row["folder_id"]
                        if source_id == destination_id:
                            continue
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
                        source_id = row["parent_id"]
                        if source_id == destination_id:
                            continue
                        if destination_id == object_id:
                            raise ValueError("Нельзя переместить папку саму в себя.")
                        if destination_id and self._is_descendant(db, object_id, destination_id):
                            raise ValueError("Нельзя переместить папку внутрь её дочерней папки.")
                        db.execute(
                            "UPDATE disk_folders SET parent_id = ?, updated_at = ? WHERE id = ?",
                            (destination_id, now, object_id),
                        )
                        name = row["name"]

                    move_info = {
                        "kind": kind,
                        "id": object_id,
                        "name": name,
                        "from_id": source_id,
                        "to_id": destination_id,
                    }
                    moves.append(move_info)
                    self._record_action(
                        db,
                        "moved",
                        kind,
                        object_id,
                        name,
                        {"from_id": source_id, "destination_id": destination_id},
                    )
        except sqlite3.IntegrityError as exc:
            raise FileExistsError("В папке назначения уже есть папка с таким именем.") from exc

        return {
            "status": "перемещено",
            "count": len(moves),
            "destination_id": destination_id,
            "destination_name": destination_name,
            "moves": moves,
        }

    def undo_move(self, moves: Iterable[dict[str, Any]]) -> dict[str, Any]:
        normalized = list(moves)
        if not normalized:
            raise ValueError("Нет перемещения для отмены.")
        now = self._now()
        restored = 0

        try:
            with self._session() as db:
                for move in normalized:
                    kind = move.get("kind")
                    object_id = move.get("id")
                    destination_id = move.get("from_id")
                    if kind not in {"file", "folder"} or not object_id:
                        raise ValueError("Некорректные данные отмены перемещения.")

                    self._require_folder(db, destination_id)

                    if kind == "file":
                        row = db.execute(
                            "SELECT name, name_key FROM disk_files WHERE id = ? AND trashed_at IS NULL",
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
                            raise FileExistsError("Нельзя отменить перемещение: исходное имя уже занято.")
                        db.execute(
                            "UPDATE disk_files SET folder_id = ?, updated_at = ? WHERE id = ?",
                            (destination_id, now, object_id),
                        )
                    else:
                        row = db.execute(
                            "SELECT name FROM disk_folders WHERE id = ? AND trashed_at IS NULL",
                            (object_id,),
                        ).fetchone()
                        if row is None:
                            raise FileNotFoundError("Папка не найдена.")
                        if destination_id == object_id:
                            raise ValueError("Нельзя переместить папку саму в себя.")
                        if destination_id and self._is_descendant(db, object_id, destination_id):
                            raise ValueError("Нельзя вернуть папку внутрь её дочерней папки.")
                        db.execute(
                            "UPDATE disk_folders SET parent_id = ?, updated_at = ? WHERE id = ?",
                            (destination_id, now, object_id),
                        )

                    self._record_action(
                        db,
                        "move_undone",
                        kind,
                        object_id,
                        row["name"],
                        {"destination_id": destination_id},
                    )
                    restored += 1
        except sqlite3.IntegrityError as exc:
            raise FileExistsError("Нельзя отменить перемещение: имя папки уже занято.") from exc

        return {"status": "перемещение отменено", "count": restored}

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

    @staticmethod
    def _decode_text(data: bytes) -> str:
        for encoding in ("utf-8-sig", "utf-16", "cp1251", "latin-1"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")

    @staticmethod
    def _zip_xml_text(path: Path, member_names: list[str], text_tags: set[str]) -> str:
        chunks: list[str] = []
        expanded = 0
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            for member in member_names:
                if member not in names:
                    continue
                info = archive.getinfo(member)
                expanded += int(info.file_size)
                if expanded > MAX_PREVIEW_XML_BYTES:
                    raise ValueError("Office-документ слишком большой для безопасного локального предпросмотра.")
                root = ET.fromstring(archive.read(member))
                current: list[str] = []
                for element in root.iter():
                    tag = element.tag.rsplit("}", 1)[-1]
                    if tag in text_tags and element.text:
                        current.append(element.text)
                    if tag in {"p", "tr"} and current:
                        chunks.append(" ".join(current).strip())
                        current = []
                if current:
                    chunks.append(" ".join(current).strip())
        return "\n".join(line for line in chunks if line)

    def preview(self, file_id: str) -> dict[str, Any]:
        item = self.get_file(file_id)
        path: Path = item["path"]
        suffix = path.suffix.lower() if path.suffix else Path(item["name"]).suffix.lower()
        content_type = item["content_type"]

        base = {
            "id": item["id"],
            "name": item["name"],
            "content_type": content_type,
            "size_bytes": item["size_bytes"],
            "sha256": item["sha256"],
            "category": item["category"],
        }

        if content_type == "application/pdf" or suffix == ".pdf":
            return {**base, "mode": "pdf", "url": f"/api/disk/files/{file_id}/view"}
        if content_type.startswith("image/"):
            return {**base, "mode": "image", "url": f"/api/disk/files/{file_id}/view"}
        if content_type.startswith("video/"):
            return {**base, "mode": "video", "url": f"/api/disk/files/{file_id}/view"}
        if content_type.startswith("audio/"):
            return {**base, "mode": "audio", "url": f"/api/disk/files/{file_id}/view"}

        if suffix in {".txt", ".md", ".json", ".xml", ".csv", ".log", ".ini", ".cfg", ".yaml", ".yml"}:
            limit = 4 * 1024 * 1024
            data = path.read_bytes()
            truncated = len(data) > limit
            text = self._decode_text(data[:limit])
            return {**base, "mode": "text", "text": text, "truncated": truncated}

        if suffix == ".docx":
            text = self._zip_xml_text(path, ["word/document.xml"], {"t"})
            return {**base, "mode": "document", "text": text or "Документ не содержит извлекаемого текста."}

        if suffix == ".pptx":
            with zipfile.ZipFile(path) as archive:
                slides = sorted(
                    name for name in archive.namelist()
                    if name.startswith("ppt/slides/slide") and name.endswith(".xml")
                )
            text = self._zip_xml_text(path, slides, {"t"})
            return {**base, "mode": "presentation", "text": text or "Презентация не содержит извлекаемого текста."}

        if suffix == ".xlsx":
            rows: list[list[str]] = []
            sheet_name = "Лист"
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
                shared: list[str] = []
                if "xl/sharedStrings.xml" in names:
                    info = archive.getinfo("xl/sharedStrings.xml")
                    if info.file_size > MAX_PREVIEW_XML_BYTES:
                        raise ValueError("Таблица слишком большая для безопасного локального предпросмотра.")
                    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                    for si in root:
                        parts = [
                            node.text or ""
                            for node in si.iter()
                            if node.tag.rsplit("}", 1)[-1] == "t"
                        ]
                        shared.append("".join(parts))
                sheets = sorted(
                    name for name in names
                    if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
                )
                if sheets:
                    info = archive.getinfo(sheets[0])
                    if info.file_size > MAX_PREVIEW_XML_BYTES:
                        raise ValueError("Таблица слишком большая для безопасного локального предпросмотра.")
                    root = ET.fromstring(archive.read(sheets[0]))
                    for row in root.iter():
                        if row.tag.rsplit("}", 1)[-1] != "row":
                            continue
                        values: list[str] = []
                        for cell in row:
                            if cell.tag.rsplit("}", 1)[-1] != "c":
                                continue
                            cell_type = cell.attrib.get("t")
                            value_node = next(
                                (node for node in cell if node.tag.rsplit("}", 1)[-1] == "v"),
                                None,
                            )
                            raw = value_node.text if value_node is not None and value_node.text else ""
                            if cell_type == "s" and raw.isdigit():
                                index = int(raw)
                                raw = shared[index] if index < len(shared) else raw
                            values.append(raw)
                        if values:
                            rows.append(values[:50])
                        if len(rows) >= 200:
                            break
            return {**base, "mode": "table", "sheet": sheet_name, "rows": rows, "truncated": len(rows) >= 200}

        if suffix in {".odt", ".ods", ".odp"}:
            text = self._zip_xml_text(path, ["content.xml"], {"p", "h"})
            mode = {".odt": "document", ".ods": "table-text", ".odp": "presentation"}[suffix]
            return {**base, "mode": mode, "text": text or "Файл не содержит извлекаемого текста."}

        return {
            **base,
            "mode": "unsupported",
            "message": "Для этого формата встроенный предпросмотр пока недоступен. Файл можно скачать или открыть внешним приложением.",
        }

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while True:
                chunk = source.read(CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def _spatial_snapshot(
        self,
        item: dict[str, Any],
        *,
        force: bool = False,
        force_ocr: bool = False,
    ) -> dict[str, Any]:
        file_id = str(item["id"])
        with self._session() as db:
            row = db.execute(
                """
                SELECT sha256, engine_version, analyzed_at, spatial_json
                FROM disk_dna_spatial
                WHERE file_id = ?
                """,
                (file_id,),
            ).fetchone()
            if (
                row is not None
                and row["sha256"] == item["sha256"]
                and row["engine_version"] == SPATIAL_ENGINE_VERSION
                and not force
            ):
                cached = json.loads(row["spatial_json"])
                if not force_ocr or bool(cached.get("force_ocr")):
                    cached["cached"] = True
                    cached["analyzed_at"] = row["analyzed_at"]
                    return cached

        path = Path(item["path"])
        suffix = path.suffix.lower() if path.suffix else Path(item["name"]).suffix.lower()
        spatial = self.spatial_dna.extract(
            path,
            content_type=str(item["content_type"]),
            suffix=suffix,
            force_ocr=force_ocr,
        )
        analyzed_at = self._now()
        spatial["analyzed_at"] = analyzed_at
        spatial["cached"] = False
        with self._session() as db:
            db.execute(
                """
                INSERT INTO disk_dna_spatial(
                    file_id, sha256, engine_version, analyzed_at, spatial_json
                ) VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(file_id) DO UPDATE SET
                    sha256 = excluded.sha256,
                    engine_version = excluded.engine_version,
                    analyzed_at = excluded.analyzed_at,
                    spatial_json = excluded.spatial_json
                """,
                (
                    file_id,
                    item["sha256"],
                    SPATIAL_ENGINE_VERSION,
                    analyzed_at,
                    json.dumps(spatial, ensure_ascii=False),
                ),
            )
        return spatial

    def spatial_document(
        self,
        file_id: str,
        *,
        force: bool = False,
        force_ocr: bool = False,
    ) -> dict[str, Any]:
        item = self.get_file(file_id)
        return self._spatial_snapshot(
            item,
            force=force,
            force_ocr=force_ocr,
        )

    def spatial_status(self) -> dict[str, Any]:
        capabilities = self.spatial_dna.capabilities()
        with self._session() as db:
            rows = db.execute(
                """
                SELECT spatial_json
                FROM disk_dna_spatial
                """
            ).fetchall()

        ready = 0
        pages = 0
        ocr_pages = 0
        ocr_failures = 0
        table_count = 0
        for row in rows:
            try:
                spatial = json.loads(row["spatial_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            if spatial.get("status") == "ready":
                ready += 1
            pages += int(spatial.get("page_count") or 0)
            ocr = spatial.get("ocr") or {}
            ocr_pages += int(ocr.get("used_pages") or 0)
            ocr_failures += len(ocr.get("failures") or [])
            table_count += int((spatial.get("tables") or {}).get("count") or 0)

        return {
            "status": "готово" if capabilities.get("pymupdf_available") else "ограничено",
            "engine_version": SPATIAL_ENGINE_VERSION,
            "capabilities": capabilities,
            "cached_documents": len(rows),
            "ready_documents": ready,
            "pages": pages,
            "ocr_pages": ocr_pages,
            "ocr_failures": ocr_failures,
            "tables": table_count,
            "policy": "Координаты берутся только из движка документа; отсутствие OCR не маскируется.",
        }

    def _feedback_calibration(self, db: sqlite3.Connection) -> dict[str, Any]:
        rows = db.execute(
            """
            SELECT f.fact_id, f.action, d.dna_json
            FROM disk_dna_feedback f
            JOIN disk_dna d ON d.file_id = f.file_id
            ORDER BY f.id
            """
        ).fetchall()
        stats: dict[str, dict[str, int]] = {}
        for row in rows:
            try:
                dna = json.loads(row["dna_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            fact = next(
                (
                    item for item in dna.get("molecules", {}).get("facts", [])
                    if item.get("id") == row["fact_id"]
                ),
                None,
            )
            if fact is None:
                continue
            fact_type = str(fact.get("type") or "unknown")
            bucket = stats.setdefault(
                fact_type,
                {"samples": 0, "positive": 0, "negative": 0},
            )
            bucket["samples"] += 1
            if row["action"] in {"confirm", "correct"}:
                bucket["positive"] += 1
            elif row["action"] == "reject":
                bucket["negative"] += 1

        result: dict[str, Any] = {}
        for fact_type, bucket in stats.items():
            samples = bucket["samples"]
            reliability = (bucket["positive"] + 1) / (samples + 2)
            result[fact_type] = {
                **bucket,
                "reliability": round(reliability, 4),
            }
        return result

    @staticmethod
    def _learned_correction_rules(db: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = db.execute(
            """
            SELECT fact_type, original_canonical, corrected_json, support_count
            FROM disk_dna_correction_rules
            WHERE support_count >= 3
            ORDER BY support_count DESC, fact_type, original_canonical
            """
        ).fetchall()
        result = []
        for row in rows:
            try:
                corrected = json.loads(row["corrected_json"])
            except json.JSONDecodeError:
                continue
            result.append(
                {
                    "fact_type": row["fact_type"],
                    "original_canonical": row["original_canonical"],
                    "corrected": corrected,
                    "support_count": row["support_count"],
                }
            )
        return result

    def _register_correction_rule(
        self,
        db: sqlite3.Connection,
        *,
        file_id: str,
        fact: dict[str, Any],
        corrected_value: str,
    ) -> None:
        fact_type = str(fact.get("type") or "")
        original = str((fact.get("normalized") or {}).get("canonical") or fact.get("value") or "")
        if not fact_type or not original:
            return
        corrected = self.dna_analyzer._normalize_fact(fact_type, corrected_value)
        corrected_json = json.dumps(corrected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        row = db.execute(
            """
            SELECT supporting_files_json
            FROM disk_dna_correction_rules
            WHERE fact_type = ? AND original_canonical = ? AND corrected_json = ?
            """,
            (fact_type, original, corrected_json),
        ).fetchone()
        files: list[str] = []
        if row is not None:
            try:
                files = [str(value) for value in json.loads(row["supporting_files_json"])]
            except (TypeError, json.JSONDecodeError):
                files = []
        if file_id not in files:
            files.append(file_id)
        files = sorted(set(files))
        db.execute(
            """
            INSERT INTO disk_dna_correction_rules(
                fact_type, original_canonical, corrected_json,
                supporting_files_json, support_count, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(fact_type, original_canonical, corrected_json) DO UPDATE SET
                supporting_files_json = excluded.supporting_files_json,
                support_count = excluded.support_count,
                updated_at = excluded.updated_at
            """,
            (
                fact_type,
                original,
                corrected_json,
                json.dumps(files, ensure_ascii=False),
                len(files),
                self._now(),
            ),
        )

    def _append_dna_ledger(
        self,
        db: sqlite3.Connection,
        *,
        file_id: str,
        event_type: str,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        previous = db.execute(
            """
            SELECT sequence_no, chain_hash
            FROM disk_dna_ledger
            WHERE file_id = ?
            ORDER BY sequence_no DESC
            LIMIT 1
            """,
            (file_id,),
        ).fetchone()
        sequence_no = int(previous["sequence_no"] if previous else 0) + 1
        previous_hash = previous["chain_hash"] if previous else None
        created_at = self._now()
        details_json = json.dumps(
            details,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        payload_sha256 = hashlib.sha256(details_json.encode("utf-8")).hexdigest()
        chain_material = "|".join(
            [
                file_id,
                str(sequence_no),
                event_type,
                created_at,
                payload_sha256,
                str(previous_hash or ""),
            ]
        )
        chain_hash = hashlib.sha256(chain_material.encode("utf-8")).hexdigest()
        db.execute(
            """
            INSERT INTO disk_dna_ledger(
                file_id, sequence_no, event_type, created_at,
                payload_sha256, previous_chain_hash, chain_hash, details_json
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_id,
                sequence_no,
                event_type,
                created_at,
                payload_sha256,
                previous_hash,
                chain_hash,
                details_json,
            ),
        )
        return {
            "sequence_no": sequence_no,
            "event_type": event_type,
            "created_at": created_at,
            "payload_sha256": payload_sha256,
            "previous_chain_hash": previous_hash,
            "chain_hash": chain_hash,
        }

    def dna_ledger(self, file_id: str, limit: int = 100) -> dict[str, Any]:
        self.get_file(file_id, allow_trashed=True)
        safe_limit = min(max(int(limit), 1), 500)
        with self._session() as db:
            rows = db.execute(
                """
                SELECT sequence_no, event_type, created_at, payload_sha256,
                       previous_chain_hash, chain_hash, details_json
                FROM disk_dna_ledger
                WHERE file_id = ?
                ORDER BY sequence_no
                """,
                (file_id,),
            ).fetchall()

        valid = True
        previous_hash = None
        entries = []
        for row in rows:
            details_json = row["details_json"]
            payload_sha256 = hashlib.sha256(details_json.encode("utf-8")).hexdigest()
            chain_material = "|".join(
                [
                    file_id,
                    str(row["sequence_no"]),
                    row["event_type"],
                    row["created_at"],
                    payload_sha256,
                    str(previous_hash or ""),
                ]
            )
            expected_chain = hashlib.sha256(chain_material.encode("utf-8")).hexdigest()
            entry_valid = (
                payload_sha256 == row["payload_sha256"]
                and row["previous_chain_hash"] == previous_hash
                and expected_chain == row["chain_hash"]
            )
            valid = valid and entry_valid
            if len(entries) < safe_limit:
                entries.append(
                    {
                        "sequence_no": row["sequence_no"],
                        "event_type": row["event_type"],
                        "created_at": row["created_at"],
                        "payload_sha256": row["payload_sha256"],
                        "previous_chain_hash": row["previous_chain_hash"],
                        "chain_hash": row["chain_hash"],
                        "valid": entry_valid,
                        "details": json.loads(details_json),
                    }
                )
            previous_hash = row["chain_hash"]
        return {
            "file_id": file_id,
            "valid": valid,
            "entries": entries,
            "total": len(rows),
            "chain_head": previous_hash,
        }

    @staticmethod
    def _median(values: list[float]) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return float(ordered[middle])
        return float((ordered[middle - 1] + ordered[middle]) / 2)

    def _enrich_corpus_intelligence(
        self,
        db: sqlite3.Connection,
        file_id: str,
        dna: dict[str, Any],
    ) -> None:
        rows = db.execute(
            """
            SELECT d.file_id, d.dna_json, f.name, f.size_bytes
            FROM disk_dna d
            JOIN disk_files f ON f.id = d.file_id
            WHERE d.file_id <> ? AND f.trashed_at IS NULL
            """,
            (file_id,),
        ).fetchall()
        corpus: list[dict[str, Any]] = []
        for row in rows:
            try:
                other = json.loads(row["dna_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            corpus.append(
                {
                    "file_id": row["file_id"],
                    "name": row["name"],
                    "size_bytes": int(row["size_bytes"]),
                    "dna": other,
                }
            )

        dependencies = dna.setdefault("dependencies", {"items": [], "count": 0, "unresolved_count": 0})
        graph = dna.setdefault("graph_ready", {"nodes": [], "edges": [], "ready_for_merge": True})
        document_node = f"document:{file_id}"
        comparison_rows = []

        for dependency in dependencies.get("items", []):
            number = str(dependency.get("document_number") or "")
            expected_type = dependency.get("expected_type")
            matches = []
            for candidate in corpus:
                other = candidate["dna"]
                other_type = other.get("classification", {}).get("document_type")
                if expected_type and other_type != expected_type:
                    continue
                other_numbers = self._dna_fact_values(other, "document_number")
                if number and number in other_numbers:
                    matches.append(candidate)

            dependency["resolved_file_ids"] = [item["file_id"] for item in matches]
            dependency["status"] = "resolved" if matches else "missing"
            for match in matches:
                edge = {
                    "from": document_node,
                    "to": f"document:{match['file_id']}",
                    "type": "depends_on",
                    "dependency_id": dependency.get("id"),
                    "evidence_fact_ids": [dependency.get("source_fact_id")],
                    "inferred": False,
                }
                if edge not in graph.setdefault("edges", []):
                    graph["edges"].append(edge)

                current_amounts = self._dna_fact_values(dna, "amount", role="total_amount")
                other_amounts = self._dna_fact_values(match["dna"], "amount", role="total_amount")
                if current_amounts and other_amounts:
                    comparison_rows.append(
                        {
                            "other_file_id": match["file_id"],
                            "other_name": match["name"],
                            "dependency_id": dependency.get("id"),
                            "current_total": sorted(current_amounts),
                            "other_total": sorted(other_amounts),
                            "matches": current_amounts == other_amounts,
                            "note": "Сравнение сумм связанных документов; различие само по себе не считается ошибкой.",
                        }
                    )
        dependencies["unresolved_count"] = sum(
            1 for item in dependencies.get("items", []) if item.get("status") != "resolved"
        )
        dna["cross_document_arithmetic"] = comparison_rows[:60]

        current_type = dna.get("classification", {}).get("document_type")
        current_numbers = self._dna_fact_values(dna, "document_number")
        family_members = []
        for candidate in corpus:
            other = candidate["dna"]
            if other.get("classification", {}).get("document_type") != current_type:
                continue
            other_numbers = self._dna_fact_values(other, "document_number")
            if current_numbers and other_numbers and current_numbers & other_numbers:
                family_members.append(candidate)

        family_material = "|".join(
            [str(current_type or "document"), ",".join(sorted(current_numbers)) or file_id]
        )
        family_id = "family-" + hashlib.sha1(family_material.encode("utf-8")).hexdigest()[:16]
        dna["document_family"] = {
            "id": family_id,
            "document_type": current_type,
            "identity_numbers": sorted(current_numbers),
            "members": [
                {
                    "file_id": item["file_id"],
                    "name": item["name"],
                    "sha256": item["dna"].get("identity", {}).get("sha256"),
                    "analyzed_at": item["dna"].get("analyzed_at"),
                }
                for item in family_members[:40]
            ],
            "member_count": len(family_members) + 1,
        }

        template_sha = dna.get("template_fingerprint", {}).get("sha256")
        template_matches = [
            {
                "file_id": item["file_id"],
                "name": item["name"],
            }
            for item in corpus
            if template_sha
            and item["dna"].get("template_fingerprint", {}).get("sha256") == template_sha
        ]
        dna["template_fingerprint"]["matching_documents"] = template_matches[:40]
        dna["template_fingerprint"]["matching_count"] = len(template_matches)

        same_type = [
            item for item in corpus
            if item["dna"].get("classification", {}).get("document_type") == current_type
        ]
        anomalies = []
        if len(same_type) >= 3:
            size_values = [float(item["size_bytes"]) for item in same_type if item["size_bytes"] >= 0]
            word_values = [
                float(item["dna"].get("anatomy", {}).get("words") or 0)
                for item in same_type
            ]
            profile_values = [
                float(item["dna"].get("profile", {}).get("completeness_percent") or 0)
                for item in same_type
            ]
            metrics = {
                "size_bytes": (
                    float(dna.get("identity", {}).get("size_bytes") or 0),
                    self._median(size_values),
                ),
                "words": (
                    float(dna.get("anatomy", {}).get("words") or 0),
                    self._median(word_values),
                ),
                "profile_completeness": (
                    float(dna.get("profile", {}).get("completeness_percent") or 0),
                    self._median(profile_values),
                ),
            }
            for metric, (current, median) in metrics.items():
                if median is None or median <= 0:
                    continue
                ratio = current / median
                if ratio < 0.25 or ratio > 4.0:
                    anomalies.append(
                        {
                            "metric": metric,
                            "current": current,
                            "median": median,
                            "ratio": round(ratio, 3),
                            "level": "attention",
                            "message": "Значение сильно отличается от медианы документов того же типа.",
                        }
                    )
                elif metric == "profile_completeness" and current + 35 < median:
                    anomalies.append(
                        {
                            "metric": metric,
                            "current": current,
                            "median": median,
                            "ratio": round(ratio, 3),
                            "level": "attention",
                            "message": "Полнота профиля заметно ниже обычной для этого типа документов.",
                        }
                    )
        dna["anomalies"] = {
            "items": anomalies,
            "count": len(anomalies),
            "corpus_size": len(same_type),
            "method": "robust_median_baseline",
        }

    def package_dna(
        self,
        folder_id: str | None = None,
        *,
        analyze_missing: bool = False,
    ) -> dict[str, Any]:
        with self._session() as db:
            self._require_folder(db, folder_id)
            if folder_id is None:
                rows = db.execute(
                    """
                    SELECT id, name FROM disk_files
                    WHERE trashed_at IS NULL
                    ORDER BY name_key, id
                    """
                ).fetchall()
                folder_name = "Диск Sayuri"
            else:
                rows = db.execute(
                    """
                    WITH RECURSIVE descendants(id) AS (
                        SELECT ?
                        UNION ALL
                        SELECT f.id
                        FROM disk_folders f
                        JOIN descendants d ON f.parent_id = d.id
                        WHERE f.trashed_at IS NULL
                    )
                    SELECT id, name FROM disk_files
                    WHERE trashed_at IS NULL
                      AND folder_id IN (SELECT id FROM descendants)
                    ORDER BY name_key, id
                    """,
                    (folder_id,),
                ).fetchall()
                folder_name = self._require_folder(db, folder_id)["name"]
            file_refs = [dict(row) for row in rows]

        documents = []
        pending = []
        for item in file_refs:
            if analyze_missing:
                try:
                    dna = self.document_dna(item["id"])
                    documents.append(dna)
                    continue
                except (FileNotFoundError, ValueError, zipfile.BadZipFile, ET.ParseError):
                    pending.append({"file_id": item["id"], "name": item["name"], "status": "analysis_failed"})
                    continue
            with self._session() as db:
                row = db.execute(
                    "SELECT dna_json FROM disk_dna WHERE file_id = ?",
                    (item["id"],),
                ).fetchone()
            if row is None:
                pending.append({"file_id": item["id"], "name": item["name"], "status": "not_analyzed"})
                continue
            try:
                documents.append(json.loads(row["dna_json"]))
            except json.JSONDecodeError:
                pending.append({"file_id": item["id"], "name": item["name"], "status": "invalid_dna"})

        type_counts = Counter(
            str(dna.get("classification", {}).get("document_type") or "Документ")
            for dna in documents
        )
        entity_counts = Counter(
            str(entity.get("canonical_key"))
            for dna in documents
            for entity in dna.get("entities", [])
            if entity.get("canonical_key")
        )
        shared_entities = [
            {"canonical_key": key, "documents": count}
            for key, count in entity_counts.most_common(100)
            if count >= 2
        ]
        contradiction_count = sum(
            len(dna.get("contradictions", {}).get("internal") or [])
            + len(dna.get("contradictions", {}).get("cross_document") or [])
            + len(dna.get("contradictions", {}).get("temporal") or [])
            for dna in documents
        )
        obligation_count = sum(
            int(dna.get("obligations", {}).get("count") or 0)
            for dna in documents
        )
        memory_ready = sum(
            1 for dna in documents
            if dna.get("quality_gate", {}).get("memory_ready")
        )
        package_material = json.dumps(
            {
                "folder_id": folder_id,
                "file_ids": sorted(
                    str(dna.get("identity", {}).get("file_id"))
                    for dna in documents
                    if dna.get("identity", {}).get("file_id")
                ),
                "sha256": sorted(
                    str(dna.get("identity", {}).get("sha256"))
                    for dna in documents
                    if dna.get("identity", {}).get("sha256")
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return {
            "schema_version": 1,
            "package_id": "package-" + hashlib.sha256(package_material.encode("utf-8")).hexdigest()[:20],
            "folder_id": folder_id,
            "folder_name": folder_name,
            "files_total": len(file_refs),
            "analyzed": len(documents),
            "pending": pending,
            "document_types": dict(type_counts),
            "shared_entities": shared_entities,
            "obligations": obligation_count,
            "contradictions": contradiction_count,
            "memory_ready_documents": memory_ready,
            "documents": [
                {
                    "file_id": dna.get("identity", {}).get("file_id"),
                    "name": dna.get("identity", {}).get("name"),
                    "document_type": dna.get("classification", {}).get("document_type"),
                    "coverage_percent": dna.get("coverage_percent"),
                    "family_id": dna.get("document_family", {}).get("id"),
                    "memory_ready": dna.get("quality_gate", {}).get("memory_ready"),
                }
                for dna in documents
            ],
        }

    @staticmethod
    def _all_correction_rules(db: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = db.execute(
            """
            SELECT fact_type, original_canonical, corrected_json, support_count
            FROM disk_dna_correction_rules
            ORDER BY fact_type, original_canonical, support_count DESC
            """
        ).fetchall()
        result = []
        for row in rows:
            try:
                corrected = json.loads(row["corrected_json"])
            except json.JSONDecodeError:
                continue
            result.append(
                {
                    "fact_type": row["fact_type"],
                    "original_canonical": row["original_canonical"],
                    "corrected": corrected,
                    "support_count": int(row["support_count"]),
                }
            )
        return result

    @staticmethod
    def _load_dna_corpus(
        db: sqlite3.Connection,
        *,
        exclude_file_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if exclude_file_id:
            rows = db.execute(
                """
                SELECT d.dna_json
                FROM disk_dna d
                JOIN disk_files f ON f.id = d.file_id
                WHERE f.trashed_at IS NULL AND d.file_id <> ?
                """,
                (exclude_file_id,),
            ).fetchall()
        else:
            rows = db.execute(
                """
                SELECT d.dna_json
                FROM disk_dna d
                JOIN disk_files f ON f.id = d.file_id
                WHERE f.trashed_at IS NULL
                """
            ).fetchall()
        corpus = []
        for row in rows:
            try:
                corpus.append(json.loads(row["dna_json"]))
            except (TypeError, json.JSONDecodeError):
                continue
        return corpus

    @staticmethod
    def _previous_history_dna(
        db: sqlite3.Connection,
        file_id: str,
    ) -> dict[str, Any] | None:
        row = db.execute(
            """
            SELECT dna_json
            FROM disk_dna_history
            WHERE file_id = ?
            ORDER BY version_no DESC
            LIMIT 1 OFFSET 1
            """,
            (file_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["dna_json"])
        except json.JSONDecodeError:
            return None

    def _sync_global_entities(
        self,
        db: sqlite3.Connection,
        file_id: str,
        dna: dict[str, Any],
    ) -> None:
        old_rows = db.execute(
            "SELECT entity_id FROM disk_dna_entity_mentions WHERE file_id = ?",
            (file_id,),
        ).fetchall()
        affected = {row["entity_id"] for row in old_rows}
        db.execute(
            "DELETE FROM disk_dna_entity_mentions WHERE file_id = ?",
            (file_id,),
        )

        facts = {
            str(fact.get("id")): fact
            for fact in dna.get("molecules", {}).get("facts", [])
            if fact.get("id")
        }
        global_refs = []
        now = self._now()

        for cluster in dna.get("entity_resolution", {}).get("clusters", []):
            category = str(cluster.get("category") or "Факт")
            canonical_id = str(cluster.get("canonical_id") or "").strip()
            if not canonical_id:
                continue
            entity_id = "global-" + hashlib.sha1(
                f"{category}|{canonical_id}".encode("utf-8")
            ).hexdigest()[:20]
            affected.add(entity_id)
            values = [str(value) for value in (cluster.get("values") or []) if value]
            display_name = values[0] if values else canonical_id
            fact_ids = [
                str(value)
                for value in (cluster.get("evidence_fact_ids") or [])
                if value
            ]
            evidence = [
                facts[fact_id].get("source")
                for fact_id in fact_ids
                if fact_id in facts
            ]
            confidences = [
                float(facts[fact_id].get("calibrated_confidence", facts[fact_id].get("confidence") or 0))
                for fact_id in fact_ids
                if fact_id in facts
            ]
            confidence = max(confidences, default=0.0)
            attributes = {
                "values": sorted(set(values)),
                "resolution": cluster.get("resolution"),
            }

            db.execute(
                """
                INSERT INTO disk_dna_entities(
                    entity_id, category, canonical_id, display_name,
                    first_seen_at, last_seen_at, document_count,
                    confidence, attributes_json
                ) VALUES(?, ?, ?, ?, ?, ?, 0, ?, ?)
                ON CONFLICT(entity_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    last_seen_at = excluded.last_seen_at,
                    confidence = MAX(disk_dna_entities.confidence, excluded.confidence),
                    attributes_json = excluded.attributes_json
                """,
                (
                    entity_id,
                    category,
                    canonical_id,
                    display_name,
                    now,
                    now,
                    confidence,
                    json.dumps(attributes, ensure_ascii=False),
                ),
            )
            db.execute(
                """
                INSERT INTO disk_dna_entity_mentions(
                    file_id, entity_id, fact_ids_json, evidence_json,
                    confidence, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_id, entity_id) DO UPDATE SET
                    fact_ids_json = excluded.fact_ids_json,
                    evidence_json = excluded.evidence_json,
                    confidence = excluded.confidence,
                    updated_at = excluded.updated_at
                """,
                (
                    file_id,
                    entity_id,
                    json.dumps(fact_ids, ensure_ascii=False),
                    json.dumps(evidence, ensure_ascii=False),
                    confidence,
                    now,
                ),
            )
            cluster["global_entity_id"] = entity_id
            global_refs.append(
                {
                    "entity_id": entity_id,
                    "category": category,
                    "canonical_id": canonical_id,
                    "display_name": display_name,
                    "confidence": round(confidence, 3),
                }
            )

        for entity_id in affected:
            row = db.execute(
                """
                SELECT COUNT(*) AS document_count, MAX(updated_at) AS last_seen_at
                FROM disk_dna_entity_mentions
                WHERE entity_id = ?
                """,
                (entity_id,),
            ).fetchone()
            count = int(row["document_count"] if row else 0)
            if count <= 0:
                db.execute(
                    "DELETE FROM disk_dna_entities WHERE entity_id = ?",
                    (entity_id,),
                )
            else:
                db.execute(
                    """
                    UPDATE disk_dna_entities
                    SET document_count = ?, last_seen_at = COALESCE(?, last_seen_at)
                    WHERE entity_id = ?
                    """,
                    (count, row["last_seen_at"], entity_id),
                )

        dna["global_entities"] = {
            "items": global_refs,
            "count": len(global_refs),
            "registry": "disk_dna_entities",
        }

    def _enrich_evolution(
        self,
        db: sqlite3.Connection,
        file_id: str,
        dna: dict[str, Any],
        *,
        previous: dict[str, Any] | None,
    ) -> None:
        corpus = self._load_dna_corpus(db, exclude_file_id=file_id)
        feedback_metrics = self._feedback_calibration(db)
        correction_rules = self._all_correction_rules(db)
        self.evolution_dna.enrich(
            dna,
            previous=previous,
            corpus=corpus,
            correction_rules=correction_rules,
            feedback_metrics=feedback_metrics,
        )
        self._sync_global_entities(db, file_id, dna)

    def evolution_status(self) -> dict[str, Any]:
        with self._session() as db:
            corpus = self._load_dna_corpus(db)
            correction_rules = self._all_correction_rules(db)
            feedback = self._feedback_calibration(db)
            entity_count = int(
                db.execute("SELECT COUNT(*) AS n FROM disk_dna_entities").fetchone()["n"]
            )
            mention_count = int(
                db.execute("SELECT COUNT(*) AS n FROM disk_dna_entity_mentions").fetchone()["n"]
            )
            feedback_count = int(
                db.execute("SELECT COUNT(*) AS n FROM disk_dna_feedback").fetchone()["n"]
            )

        current = 0
        self_review_failed = 0
        regression_blocked = 0
        maturity = []
        for dna in corpus:
            evolution = dna.get("evolution") or {}
            if evolution.get("engine_version") == EVOLUTION_ENGINE_VERSION:
                current += 1
            if evolution.get("self_review", {}).get("passed") is False:
                self_review_failed += 1
            if evolution.get("regression_guard", {}).get("status") == "blocked":
                regression_blocked += 1
            score = evolution.get("experience", {}).get("maturity_score")
            if isinstance(score, (int, float)):
                maturity.append(float(score))

        lifecycle = self.evolution_dna._rule_lifecycle(correction_rules)
        return {
            "status": "готово",
            "engine_version": EVOLUTION_ENGINE_VERSION,
            "documents": len(corpus),
            "documents_current": current,
            "self_review_failed": self_review_failed,
            "regression_blocked": regression_blocked,
            "global_entities": entity_count,
            "entity_mentions": mention_count,
            "feedback_events": feedback_count,
            "feedback_types": feedback,
            "rule_lifecycle": lifecycle.get("counts", {}),
            "average_maturity_score": round(sum(maturity) / len(maturity), 2) if maturity else 0.0,
            "principle": "Эволюция допускается только через проверяемый опыт и не превращает гипотезы в факты.",
        }

    def reanalysis_plan(self, limit: int = 100) -> dict[str, Any]:
        safe_limit = min(max(int(limit), 1), 500)
        with self._session() as db:
            rows = db.execute(
                """
                SELECT d.file_id, d.analyzer_version, d.dna_json, f.name
                FROM disk_dna d
                JOIN disk_files f ON f.id = d.file_id
                WHERE f.trashed_at IS NULL
                ORDER BY d.analyzed_at ASC
                """
            ).fetchall()

        items = []
        for row in rows:
            try:
                dna = json.loads(row["dna_json"])
            except json.JSONDecodeError:
                items.append({
                    "file_id": row["file_id"],
                    "name": row["name"],
                    "priority": 100,
                    "reasons": ["invalid_dna_json"],
                })
                continue

            reasons = []
            priority = 0
            if row["analyzer_version"] != DNA_ANALYZER_VERSION:
                reasons.append("analyzer_version")
                priority += 60
            if dna.get("advanced_engine_version") != ADVANCED_DNA_VERSION:
                reasons.append("advanced_engine_version")
                priority += 40
            if dna.get("evolution", {}).get("engine_version") != EVOLUTION_ENGINE_VERSION:
                reasons.append("evolution_engine_version")
                priority += 35
            if dna.get("spatial", {}).get("engine_version") != SPATIAL_ENGINE_VERSION:
                reasons.append("spatial_engine_version")
                priority += 55
            if dna.get("evolution", {}).get("self_review", {}).get("passed") is False:
                reasons.append("self_review_failed")
                priority += 70
            if dna.get("evolution", {}).get("regression_guard", {}).get("status") == "blocked":
                reasons.append("regression_blocked")
                priority += 90
            if not dna.get("integrity", {}).get("matches", True):
                reasons.append("integrity_failed")
                priority += 100

            if reasons:
                items.append({
                    "file_id": row["file_id"],
                    "name": row["name"],
                    "priority": priority,
                    "reasons": reasons,
                })

        items.sort(key=lambda item: (-item["priority"], item["name"].casefold()))
        return {
            "engine_version": EVOLUTION_ENGINE_VERSION,
            "count": len(items),
            "items": items[:safe_limit],
            "policy": "План только рекомендует переанализ; сам массовый переанализ автоматически не запускается.",
        }

    @staticmethod
    def _dna_fact_values(
        dna: dict[str, Any],
        fact_type: str,
        *,
        role: str | None = None,
    ) -> set[str]:
        values: set[str] = set()
        for fact in dna.get("molecules", {}).get("facts", []):
            if fact.get("type") != fact_type:
                continue
            if role is not None and fact.get("role") != role:
                continue
            if fact.get("quality_gate") == "rejected":
                continue
            normalized = fact.get("normalized") or {}
            value = normalized.get("canonical") or fact.get("value")
            if value is not None:
                values.add(str(value))
        return values

    @staticmethod
    def _dna_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
        left_tokens = set(left.get("fingerprint", {}).get("token_hashes") or [])
        right_tokens = set(right.get("fingerprint", {}).get("token_hashes") or [])
        if not left_tokens or not right_tokens:
            return 0.0
        union = left_tokens | right_tokens
        if not union:
            return 0.0
        return len(left_tokens & right_tokens) / len(union)

    @staticmethod
    def _dna_delta(
        previous: dict[str, Any] | None,
        current: dict[str, Any],
        *,
        reason: str,
    ) -> dict[str, Any]:
        if not previous:
            return {
                "reason": "initial",
                "added_facts": current.get("molecules", {}).get("total", 0),
                "removed_facts": 0,
                "changed_types": [],
                "classification_changed": False,
                "profile_completeness_delta": current.get("profile", {}).get("completeness_percent", 0),
                "value_changes": [],
                "semantic_changes": {
                    "template_changed": False,
                    "obligation_delta": int(current.get("obligations", {}).get("count") or 0),
                    "risk_delta": len(current.get("risks") or []),
                },
                "spatial_changes": {
                    "spatial_changed": bool(current.get("spatial", {}).get("spatial_sha256")),
                    "page_delta": int(current.get("spatial", {}).get("page_count") or 0),
                    "table_delta": int(current.get("spatial", {}).get("tables", {}).get("count") or 0),
                    "ocr_page_delta": int(current.get("spatial", {}).get("ocr", {}).get("used_pages") or 0),
                    "quality_delta": int(current.get("spatial", {}).get("quality", {}).get("score") or 0),
                },
            }

        def keyed(dna: dict[str, Any]) -> set[tuple[str, str, str]]:
            result: set[tuple[str, str, str]] = set()
            for fact in dna.get("molecules", {}).get("facts", []):
                normalized = fact.get("normalized") or {}
                canonical = normalized.get("canonical") or fact.get("value")
                if canonical is not None:
                    result.add(
                        (
                            str(fact.get("type")),
                            str(fact.get("role") or ""),
                            str(canonical),
                        )
                    )
            return result

        def grouped(dna: dict[str, Any]) -> dict[tuple[str, str], set[str]]:
            result: dict[tuple[str, str], set[str]] = {}
            for fact_type, role, canonical in keyed(dna):
                result.setdefault((fact_type, role), set()).add(canonical)
            return result

        before = keyed(previous)
        after = keyed(current)
        added = after - before
        removed = before - after
        added_types = {item[0] for item in added}
        removed_types = {item[0] for item in removed}
        before_grouped = grouped(previous)
        after_grouped = grouped(current)

        value_changes = []
        for key in sorted(set(before_grouped) | set(after_grouped)):
            old_values = before_grouped.get(key, set())
            new_values = after_grouped.get(key, set())
            if old_values == new_values:
                continue
            fact_type, role = key
            change: dict[str, Any] = {
                "type": fact_type,
                "role": role,
                "before": sorted(old_values),
                "after": sorted(new_values),
            }
            if fact_type == "amount" and len(old_values) == 1 and len(new_values) == 1:
                def parse_money(value: str) -> float | None:
                    match = re.search(r"-?\d+(?:\.\d+)?", value.replace(" ", ""))
                    if not match:
                        return None
                    try:
                        return float(match.group(0))
                    except ValueError:
                        return None

                old_number = parse_money(next(iter(old_values)))
                new_number = parse_money(next(iter(new_values)))
                if old_number is not None and new_number is not None:
                    change["numeric_delta"] = round(new_number - old_number, 2)
                    if old_number:
                        change["percent_delta"] = round(
                            ((new_number - old_number) / old_number) * 100,
                            2,
                        )
            value_changes.append(change)

        before_template = previous.get("template_fingerprint", {}).get("sha256")
        after_template = current.get("template_fingerprint", {}).get("sha256")
        before_spatial = previous.get("spatial", {})
        after_spatial = current.get("spatial", {})
        return {
            "reason": reason,
            "added_facts": len(added),
            "removed_facts": len(removed),
            "changed_types": sorted(added_types & removed_types),
            "classification_changed": (
                previous.get("classification", {}).get("document_type")
                != current.get("classification", {}).get("document_type")
            ),
            "profile_completeness_delta": (
                int(current.get("profile", {}).get("completeness_percent", 0))
                - int(previous.get("profile", {}).get("completeness_percent", 0))
            ),
            "value_changes": value_changes[:120],
            "semantic_changes": {
                "template_changed": bool(
                    before_template and after_template and before_template != after_template
                ),
                "obligation_delta": (
                    int(current.get("obligations", {}).get("count") or 0)
                    - int(previous.get("obligations", {}).get("count") or 0)
                ),
                "risk_delta": len(current.get("risks") or []) - len(previous.get("risks") or []),
            },
            "spatial_changes": {
                "spatial_changed": (
                    before_spatial.get("spatial_sha256")
                    != after_spatial.get("spatial_sha256")
                ),
                "page_delta": (
                    int(after_spatial.get("page_count") or 0)
                    - int(before_spatial.get("page_count") or 0)
                ),
                "table_delta": (
                    int(after_spatial.get("tables", {}).get("count") or 0)
                    - int(before_spatial.get("tables", {}).get("count") or 0)
                ),
                "ocr_page_delta": (
                    int(after_spatial.get("ocr", {}).get("used_pages") or 0)
                    - int(before_spatial.get("ocr", {}).get("used_pages") or 0)
                ),
                "quality_delta": (
                    int(after_spatial.get("quality", {}).get("score") or 0)
                    - int(before_spatial.get("quality", {}).get("score") or 0)
                ),
            },
        }

    def _refresh_dna_metadata(
        self,
        dna: dict[str, Any],
        item: dict[str, Any],
        properties: dict[str, Any],
    ) -> None:
        identity = dna.setdefault("identity", {})
        identity.update(
            {
                "file_id": item["id"],
                "name": item["name"],
                "format": Path(item["name"]).suffix.lower().lstrip(".") or "без расширения",
                "content_type": item["content_type"],
                "size_bytes": item["size_bytes"],
                "sha256": item["sha256"],
                "category": item.get("category", self._file_category(item["name"], item["content_type"])),
                "path": properties.get("path", []),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
            }
        )

    def _enrich_cross_document(
        self,
        db: sqlite3.Connection,
        file_id: str,
        dna: dict[str, Any],
    ) -> None:
        gate = dna.setdefault("quality_gate", {})
        gate["reasons"] = [
            reason for reason in (gate.get("reasons") or [])
            if reason != "cross_document_contradiction"
        ]
        dna["risks"] = [
            risk for risk in (dna.get("risks") or [])
            if risk.get("code") != "cross-document"
        ]
        dna.setdefault("contradictions", {})["cross_document"] = []
        graph = dna.setdefault("graph_ready", {"nodes": [], "edges": [], "ready_for_merge": True})
        graph["edges"] = [
            edge for edge in (graph.get("edges") or [])
            if edge.get("type") not in {"exact_duplicate", "near_duplicate", "related"}
        ]

        rows = db.execute(
            """
            SELECT d.file_id, d.sha256, d.dna_json, f.name
            FROM disk_dna d
            JOIN disk_files f ON f.id = d.file_id
            WHERE d.file_id <> ? AND f.trashed_at IS NULL
            """,
            (file_id,),
        ).fetchall()

        current_entities = {
            str(entity.get("canonical_key"))
            for entity in dna.get("entities", [])
            if entity.get("canonical_key")
        }
        current_type = dna.get("classification", {}).get("document_type")
        current_numbers = self._dna_fact_values(dna, "document_number")
        related: list[dict[str, Any]] = []
        contradictions: list[dict[str, Any]] = []

        for row in rows:
            try:
                other = json.loads(row["dna_json"])
            except (TypeError, json.JSONDecodeError):
                continue

            similarity = self._dna_similarity(dna, other)
            other_entities = {
                str(entity.get("canonical_key"))
                for entity in other.get("entities", [])
                if entity.get("canonical_key")
            }
            shared_entities = sorted(current_entities & other_entities)
            exact_duplicate = row["sha256"] == dna.get("identity", {}).get("sha256")
            near_duplicate = not exact_duplicate and similarity >= 0.82

            if exact_duplicate or near_duplicate or similarity >= 0.22 or shared_entities:
                relation_type = (
                    "exact_duplicate"
                    if exact_duplicate
                    else "near_duplicate"
                    if near_duplicate
                    else "related"
                )
                related.append(
                    {
                        "file_id": row["file_id"],
                        "name": row["name"],
                        "relation": relation_type,
                        "similarity": round(similarity, 4),
                        "shared_entities": shared_entities[:24],
                    }
                )

            other_type = other.get("classification", {}).get("document_type")
            other_numbers = self._dna_fact_values(other, "document_number")
            same_identity = bool(current_numbers and other_numbers and current_numbers & other_numbers)
            if current_type == other_type and same_identity:
                for fact_type, role in (
                    ("amount", "total_amount"),
                    ("date", "document_date"),
                    ("inn", None),
                    ("vin", None),
                    ("vehicle_plate", None),
                ):
                    left = self._dna_fact_values(dna, fact_type, role=role) or self._dna_fact_values(dna, fact_type)
                    right = self._dna_fact_values(other, fact_type, role=role) or self._dna_fact_values(other, fact_type)
                    if left and right and left != right:
                        contradictions.append(
                            {
                                "other_file_id": row["file_id"],
                                "other_name": row["name"],
                                "field": fact_type,
                                "current_values": sorted(left),
                                "other_values": sorted(right),
                                "level": "attention",
                                "message": "Документы с одинаковым номером содержат разные значения.",
                            }
                        )

        related.sort(key=lambda item: (item["relation"] != "exact_duplicate", -item["similarity"], item["name"].casefold()))
        dna["cross_document"] = {
            "related": related[:20],
            "contradictions": contradictions[:40],
            "exact_duplicates": sum(1 for item in related if item["relation"] == "exact_duplicate"),
            "near_duplicates": sum(1 for item in related if item["relation"] == "near_duplicate"),
        }
        dna.setdefault("contradictions", {})["cross_document"] = contradictions[:40]

        if contradictions:
            gate = dna.setdefault("quality_gate", {})
            gate["memory_ready"] = False
            reasons = list(gate.get("reasons") or [])
            if "cross_document_contradiction" not in reasons:
                reasons.append("cross_document_contradiction")
            gate["reasons"] = reasons
            risks = dna.setdefault("risks", [])
            if not any(risk.get("code") == "cross-document" for risk in risks):
                risks.append(
                    {
                        "code": "cross-document",
                        "severity": "attention",
                        "title": "Междокументные расхождения",
                        "reason": f"Найдено расхождений с другими версиями/документами: {len(contradictions)}.",
                    }
                )

        if not contradictions:
            gate["memory_ready"] = (
                bool(dna.get("integrity", {}).get("matches"))
                and not gate.get("reasons")
                and int(gate.get("accepted") or 0) > 0
            )

        document_node = f"document:{file_id}"
        existing_edge_keys = {
            (edge.get("from"), edge.get("to"), edge.get("type"))
            for edge in graph.get("edges", [])
        }
        for relation in related[:20]:
            target = f"document:{relation['file_id']}"
            key = (document_node, target, relation["relation"])
            if key in existing_edge_keys:
                continue
            graph.setdefault("edges", []).append(
                {
                    "from": document_node,
                    "to": target,
                    "type": relation["relation"],
                    "similarity": relation["similarity"],
                    "inferred": False,
                    "evidence": "fingerprint/entity match",
                }
            )

    @staticmethod
    def _recompute_feedback_gate(dna: dict[str, Any]) -> None:
        counts = {"accepted": 0, "review": 0, "rejected": 0}
        for fact in dna.get("molecules", {}).get("facts", []):
            gate = fact.get("quality_gate", "review")
            counts[gate if gate in counts else "review"] += 1
        gate = dna.setdefault("quality_gate", {})
        gate.update(counts)
        reasons = list(gate.get("reasons") or [])
        if counts["accepted"] == 0 and "no_accepted_facts" not in reasons:
            reasons.append("no_accepted_facts")
        elif counts["accepted"] > 0:
            reasons = [reason for reason in reasons if reason != "no_accepted_facts"]
        gate["reasons"] = reasons
        gate["memory_ready"] = (
            bool(dna.get("integrity", {}).get("matches"))
            and not reasons
            and counts["accepted"] > 0
        )

    def _apply_dna_feedback(
        self,
        db: sqlite3.Connection,
        file_id: str,
        dna: dict[str, Any],
    ) -> None:
        rows = db.execute(
            """
            SELECT fact_id, action, corrected_value_json, note, created_at
            FROM disk_dna_feedback
            WHERE file_id = ?
            ORDER BY id
            """,
            (file_id,),
        ).fetchall()
        if not rows:
            return

        facts = {
            fact.get("id"): fact
            for fact in dna.get("molecules", {}).get("facts", [])
            if fact.get("id")
        }
        applied = 0
        for row in rows:
            fact = facts.get(row["fact_id"])
            if fact is None:
                continue
            action = row["action"]
            if action == "confirm":
                fact["quality_gate"] = "accepted"
                fact["confidence"] = max(float(fact.get("confidence") or 0), 0.995)
            elif action == "reject":
                fact["quality_gate"] = "rejected"
                fact["status"] = "rejected_by_user"
            elif action == "correct":
                corrected = json.loads(row["corrected_value_json"] or "{}")
                new_value = str(corrected.get("value") or "").strip()
                if new_value:
                    fact["original_value"] = fact.get("value")
                    fact["value"] = new_value
                    fact["normalized"] = self.dna_analyzer._normalize_fact(str(fact.get("type")), new_value)
                    fact["quality_gate"] = "accepted"
                    fact["status"] = "corrected_by_user"
                    fact["confidence"] = 1.0
            fact["feedback"] = {
                "action": action,
                "note": row["note"],
                "created_at": row["created_at"],
            }
            applied += 1

        if applied:
            dna["feedback"] = {"applied": applied}
            self._recompute_feedback_gate(dna)
            dna["knowledge_promotion"] = self.advanced_dna._knowledge_promotion(dna)
            security = dna.get("security") or {
                "trust_domain": "document_content",
                "prompt_injection": {"detected": False},
            }
            sensitive = dna.get("sensitive_data") or {"findings": []}
            obligations = dna.get("obligations") or {"items": []}
            dna["ai_context"] = self.advanced_dna._selective_ai_context(
                dna,
                security=security,
                sensitive=sensitive,
                obligations=obligations,
            )

    def dna_history(self, file_id: str, limit: int = 20) -> list[dict[str, Any]]:
        self.get_file(file_id, allow_trashed=True)
        safe_limit = min(max(int(limit), 1), 100)
        with self._session() as db:
            rows = db.execute(
                """
                SELECT version_no, sha256, analyzer_version, analyzed_at, dna_json
                FROM disk_dna_history
                WHERE file_id = ?
                ORDER BY version_no DESC
                LIMIT ?
                """,
                (file_id, safe_limit),
            ).fetchall()
        result = []
        for row in rows:
            try:
                dna = json.loads(row["dna_json"])
            except json.JSONDecodeError:
                dna = {}
            result.append(
                {
                    "version": row["version_no"],
                    "sha256": row["sha256"],
                    "analyzer_version": row["analyzer_version"],
                    "analyzed_at": row["analyzed_at"],
                    "document_type": dna.get("classification", {}).get("document_type"),
                    "coverage_percent": dna.get("coverage_percent"),
                    "delta": dna.get("version_delta"),
                }
            )
        return result

    def record_dna_feedback(
        self,
        file_id: str,
        *,
        fact_id: str,
        action: str,
        corrected_value: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        if action not in {"confirm", "reject", "correct"}:
            raise ValueError("Неизвестное действие обратной связи ДНК.")
        dna = self.document_dna(file_id)
        facts = {
            fact.get("id"): fact
            for fact in dna.get("molecules", {}).get("facts", [])
            if fact.get("id")
        }
        fact = facts.get(fact_id)
        if fact is None:
            raise FileNotFoundError("Факт ДНК не найден.")
        corrected_clean = str(corrected_value or "").strip()
        if action == "correct" and not corrected_clean:
            raise ValueError("Для исправления нужно новое значение.")

        created_at = self._now()
        with self._session() as db:
            db.execute(
                """
                INSERT INTO disk_dna_feedback(
                    file_id, fact_id, action, corrected_value_json, note, created_at
                ) VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    fact_id,
                    action,
                    json.dumps({"value": corrected_clean}, ensure_ascii=False) if action == "correct" else None,
                    str(note or "").strip() or None,
                    created_at,
                ),
            )
            if action == "correct":
                self._register_correction_rule(
                    db,
                    file_id=file_id,
                    fact=fact,
                    corrected_value=corrected_clean,
                )
            ledger = self._append_dna_ledger(
                db,
                file_id=file_id,
                event_type=f"feedback:{action}",
                details={
                    "fact_id": fact_id,
                    "fact_type": fact.get("type"),
                    "original_canonical": (fact.get("normalized") or {}).get("canonical"),
                    "corrected_value": corrected_clean if action == "correct" else None,
                    "note": str(note or "").strip() or None,
                    "created_at": created_at,
                },
            )
            self._record_action(
                db,
                "dna_feedback",
                "file",
                file_id,
                dna.get("identity", {}).get("name", file_id),
                {
                    "fact_id": fact_id,
                    "action": action,
                    "ledger_sequence": ledger["sequence_no"],
                },
            )
        return {
            "status": "сохранено",
            "fact_id": fact_id,
            "action": action,
            "ledger_sequence": ledger["sequence_no"],
        }

    def document_dna(
        self,
        file_id: str,
        *,
        force: bool = False,
        bypass_cooldown: bool = False,
        force_ocr: bool = False,
    ) -> dict[str, Any]:
        item = self.get_file(file_id)
        properties = self.properties("file", file_id)
        source_updated_at = item.get("updated_at") or item.get("created_at") or ""

        with self._session() as db:
            current_row = db.execute(
                """
                SELECT sha256, source_updated_at, analyzer_version, analyzed_at, dna_json
                FROM disk_dna
                WHERE file_id = ?
                """,
                (file_id,),
            ).fetchone()

            same_analysis = (
                current_row is not None
                and current_row["sha256"] == item["sha256"]
                and current_row["analyzer_version"] == DNA_ANALYZER_VERSION
            )
            cooldown_hit = False
            if force and same_analysis and not bypass_cooldown and not force_ocr:
                try:
                    last_analyzed = datetime.fromisoformat(current_row["analyzed_at"])
                    now = datetime.now(timezone.utc)
                    if last_analyzed.tzinfo is None:
                        last_analyzed = last_analyzed.replace(tzinfo=timezone.utc)
                    cooldown_hit = (
                        0 <= (now - last_analyzed).total_seconds()
                        < REANALYZE_COOLDOWN_SECONDS
                    )
                except (TypeError, ValueError):
                    cooldown_hit = False

            if same_analysis and (not force or cooldown_hit):
                cached = json.loads(current_row["dna_json"])
                self._refresh_dna_metadata(cached, item, properties)
                self._apply_dna_feedback(db, file_id, cached)
                self._enrich_cross_document(db, file_id, cached)
                self._enrich_corpus_intelligence(db, file_id, cached)
                previous_history = self._previous_history_dna(db, file_id)
                self._enrich_evolution(
                    db,
                    file_id,
                    cached,
                    previous=previous_history,
                )
                cached["analyzed_at"] = current_row["analyzed_at"]
                cached["cached"] = True
                cached["content_reused"] = current_row["source_updated_at"] != source_updated_at
                cached["reanalysis_deduplicated"] = bool(cooldown_hit)
                cached["reanalysis_cooldown_seconds"] = REANALYZE_COOLDOWN_SECONDS
                ledger_row = db.execute(
                    """
                    SELECT sequence_no, chain_hash
                    FROM disk_dna_ledger
                    WHERE file_id = ?
                    ORDER BY sequence_no DESC
                    LIMIT 1
                    """,
                    (file_id,),
                ).fetchone()
                cached["evidence_ledger"] = {
                    "sequence_no": int(ledger_row["sequence_no"]) if ledger_row else 0,
                    "chain_head": ledger_row["chain_hash"] if ledger_row else None,
                }
                db.execute(
                    """
                    UPDATE disk_dna
                    SET source_updated_at = ?, dna_json = ?
                    WHERE file_id = ?
                    """,
                    (
                        source_updated_at,
                        json.dumps(cached, ensure_ascii=False),
                        file_id,
                    ),
                )
                return cached

            calibration = self._feedback_calibration(db)
            learned_rules = self._learned_correction_rules(db)

        previous_dna: dict[str, Any] | None = None
        if current_row is not None:
            try:
                previous_dna = json.loads(current_row["dna_json"])
            except json.JSONDecodeError:
                previous_dna = None

        actual_sha256 = self._hash_file(item["path"])
        integrity = {
            "expected_sha256": item["sha256"],
            "actual_sha256": actual_sha256,
            "matches": actual_sha256 == item["sha256"],
        }
        preview = self.preview(file_id)
        spatial = self._spatial_snapshot(
            item,
            force=bypass_cooldown or force_ocr,
            force_ocr=force_ocr,
        )
        analysis_preview = self.spatial_dna.analysis_preview(preview, spatial)
        dna = self.dna_analyzer.analyze(
            item={**item, "duplicate_count": properties.get("duplicate_count", 0)},
            properties=properties,
            preview=analysis_preview,
            integrity=integrity,
        )
        dna["spatial"] = self.spatial_dna.compact_summary(spatial)
        analyzed_at = self._now()
        dna["analyzed_at"] = analyzed_at
        dna["cached"] = False
        dna["content_reused"] = False
        dna["reanalysis_deduplicated"] = False
        dna["reanalysis_cooldown_seconds"] = REANALYZE_COOLDOWN_SECONDS

        ocr_failures = list((spatial.get("ocr") or {}).get("failures") or [])
        if ocr_failures:
            dna.setdefault("risks", []).append(
                {
                    "code": "ocr-partial",
                    "severity": "attention",
                    "title": "OCR выполнен не полностью",
                    "reason": f"Страниц с ошибкой OCR: {len(ocr_failures)}.",
                }
            )

        if current_row is None:
            reason = "initial"
        elif current_row["sha256"] != item["sha256"]:
            reason = "content_changed"
        elif current_row["analyzer_version"] != DNA_ANALYZER_VERSION:
            reason = "analyzer_upgrade"
        elif force_ocr:
            reason = "forced_ocr"
        elif bypass_cooldown:
            reason = "deep_reanalysis"
        else:
            reason = "reanalyzed"

        with self._session() as db:
            self._apply_dna_feedback(db, file_id, dna)
            self.advanced_dna.enrich(
                dna,
                preview=analysis_preview,
                calibration=calibration,
                learned_rules=learned_rules,
            )
            self.spatial_dna.attach_fact_locations(dna, spatial)
            self._enrich_cross_document(db, file_id, dna)
            self._enrich_corpus_intelligence(db, file_id, dna)
            self._enrich_evolution(
                db,
                file_id,
                dna,
                previous=previous_dna,
            )

            version_row = db.execute(
                "SELECT COALESCE(MAX(version_no), 0) AS version_no FROM disk_dna_history WHERE file_id = ?",
                (file_id,),
            ).fetchone()
            next_version = int(version_row["version_no"] if version_row else 0) + 1
            dna["history"] = {
                "version": next_version,
                "previous_version": next_version - 1 if next_version > 1 else None,
            }
            dna["version_delta"] = self._dna_delta(previous_dna, dna, reason=reason)

            ledger = self._append_dna_ledger(
                db,
                file_id=file_id,
                event_type="analysis",
                details={
                    "version": next_version,
                    "reason": reason,
                    "sha256": item["sha256"],
                    "analyzer_version": DNA_ANALYZER_VERSION,
                    "advanced_engine_version": ADVANCED_DNA_VERSION,
                    "evolution_engine_version": EVOLUTION_ENGINE_VERSION,
                    "spatial_engine_version": SPATIAL_ENGINE_VERSION,
                    "spatial_sha256": dna.get("spatial", {}).get("spatial_sha256"),
                    "ocr_pages": dna.get("spatial", {}).get("ocr", {}).get("used_pages", 0),
                    "semantic_sha256": dna.get("fingerprint", {}).get("semantic_sha256"),
                    "facts": dna.get("molecules", {}).get("total", 0),
                    "memory_ready": dna.get("quality_gate", {}).get("memory_ready", False),
                    "self_review_score": dna.get("evolution", {}).get("self_review", {}).get("score"),
                    "regression_guard": dna.get("evolution", {}).get("regression_guard", {}).get("status"),
                },
            )
            dna["evidence_ledger"] = {
                "sequence_no": ledger["sequence_no"],
                "chain_head": ledger["chain_hash"],
            }

            dna_json = json.dumps(dna, ensure_ascii=False)
            db.execute(
                """
                INSERT INTO disk_dna(
                    file_id, sha256, source_updated_at, analyzer_version, analyzed_at, dna_json
                ) VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_id) DO UPDATE SET
                    sha256 = excluded.sha256,
                    source_updated_at = excluded.source_updated_at,
                    analyzer_version = excluded.analyzer_version,
                    analyzed_at = excluded.analyzed_at,
                    dna_json = excluded.dna_json
                """,
                (
                    file_id,
                    item["sha256"],
                    source_updated_at,
                    DNA_ANALYZER_VERSION,
                    analyzed_at,
                    dna_json,
                ),
            )
            db.execute(
                """
                INSERT INTO disk_dna_history(
                    file_id, version_no, sha256, source_updated_at,
                    analyzer_version, analyzed_at, dna_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    next_version,
                    item["sha256"],
                    source_updated_at,
                    DNA_ANALYZER_VERSION,
                    analyzed_at,
                    dna_json,
                ),
            )
            self._record_action(
                db,
                "dna_analyzed",
                "file",
                file_id,
                item["name"],
                {
                    "coverage_percent": dna["coverage_percent"],
                    "facts": dna["molecules"]["total"],
                    "document_type": dna["classification"]["document_type"],
                    "version": next_version,
                    "reason": reason,
                    "memory_ready": dna.get("quality_gate", {}).get("memory_ready", False),
                    "ledger_sequence": ledger["sequence_no"],
                    "evolution_engine_version": EVOLUTION_ENGINE_VERSION,
                    "spatial_engine_version": SPATIAL_ENGINE_VERSION,
                    "ocr_pages": dna.get("spatial", {}).get("ocr", {}).get("used_pages", 0),
                },
            )
        return dna

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
            "dna_analyzer_version": DNA_ANALYZER_VERSION,
            "dna_advanced_version": ADVANCED_DNA_VERSION,
            "dna_evolution_version": EVOLUTION_ENGINE_VERSION,
            "dna_spatial_version": SPATIAL_ENGINE_VERSION,
            "spatial": self.spatial_status(),
            "files": listing["stats"]["files"],
            "folders": listing["stats"]["folders"],
            "bytes": listing["stats"]["bytes"],
            "trash_items": listing["stats"]["trash_items"],
            "favorites": listing["stats"]["favorites"],
            "max_file_size": MAX_FILE_SIZE,
            "storage_path": str(self.storage_root),
        }
