from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import mimetypes
import os
import sqlite3
from typing import BinaryIO, Any
import uuid


DISK_SCHEMA_VERSION = 1
CHUNK_SIZE = 1024 * 1024
MAX_FILE_SIZE = 1024 * 1024 * 1024  # 1 ГБ на один файл в первой версии


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
                CREATE UNIQUE INDEX IF NOT EXISTS ux_disk_folder_parent_name
                ON disk_folders(COALESCE(parent_id, ''), name_key)
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
            db.execute(
                """
                INSERT INTO disk_meta(key, value) VALUES('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(DISK_SCHEMA_VERSION),),
            )

    def _require_folder(self, db: sqlite3.Connection, folder_id: str | None) -> None:
        if folder_id is None:
            return
        row = db.execute("SELECT id FROM disk_folders WHERE id = ?", (folder_id,)).fetchone()
        if row is None:
            raise FileNotFoundError("Папка не найдена.")

    def create_folder(self, name: str, parent_id: str | None = None) -> dict[str, Any]:
        clean = self._validate_name(name, kind="папки")
        folder_id = uuid.uuid4().hex
        created_at = self._now()
        try:
            with self._session() as db:
                self._require_folder(db, parent_id)
                db.execute(
                    "INSERT INTO disk_folders(id, parent_id, name, name_key, created_at) VALUES(?, ?, ?, ?, ?)",
                    (folder_id, parent_id, clean, clean.casefold(), created_at),
                )
        except sqlite3.IntegrityError as exc:
            raise FileExistsError("Папка с таким именем уже существует.") from exc
        return {"id": folder_id, "parent_id": parent_id, "name": clean, "created_at": created_at}

    def list_entries(self, folder_id: str | None = None, query: str = "") -> dict[str, Any]:
        search = query.strip().casefold()
        with self._session() as db:
            self._require_folder(db, folder_id)
            folders = [
                dict(row)
                for row in db.execute(
                    "SELECT id, parent_id, name, created_at FROM disk_folders WHERE parent_id IS ? ORDER BY name COLLATE NOCASE",
                    (folder_id,),
                ).fetchall()
            ]
            files = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT id, folder_id, name, content_type, size_bytes, sha256, created_at
                    FROM disk_files
                    WHERE folder_id IS ?
                    ORDER BY created_at DESC
                    """,
                    (folder_id,),
                ).fetchall()
            ]
            if search:
                folders = [item for item in folders if search in item["name"].casefold()]
                files = [item for item in files if search in item["name"].casefold()]

            breadcrumb: list[dict[str, str | None]] = []
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
                breadcrumb.append({"id": row["id"], "name": row["name"]})
                current = row["parent_id"]
            breadcrumb.reverse()

            stats = db.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM disk_files) AS files,
                    (SELECT COUNT(*) FROM disk_folders) AS folders,
                    (SELECT COALESCE(SUM(size_bytes), 0) FROM disk_files) AS bytes
                """
            ).fetchone()

        return {
            "folder_id": folder_id,
            "breadcrumb": breadcrumb,
            "folders": folders,
            "files": files,
            "stats": {
                "files": int(stats["files"]),
                "folders": int(stats["folders"]),
                "bytes": int(stats["bytes"]),
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
            created_at = self._now()
            detected_type = content_type or mimetypes.guess_type(clean)[0] or "application/octet-stream"

            try:
                with self._session() as db:
                    db.execute(
                        """
                        INSERT INTO disk_files(
                            id, folder_id, name, stored_name, content_type,
                            size_bytes, sha256, created_at
                        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            file_id,
                            folder_id,
                            clean,
                            stored_name,
                            detected_type,
                            size_bytes,
                            digest.hexdigest(),
                            created_at,
                        ),
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
            "sha256": digest.hexdigest(),
            "created_at": created_at,
        }

    def get_file(self, file_id: str) -> dict[str, Any]:
        with self._session() as db:
            row = db.execute(
                """
                SELECT id, folder_id, name, stored_name, content_type, size_bytes, sha256, created_at
                FROM disk_files WHERE id = ?
                """,
                (file_id,),
            ).fetchone()
        if row is None:
            raise FileNotFoundError("Файл не найден.")
        item = dict(row)
        path = (self.objects_dir / item.pop("stored_name")).resolve()
        if path.parent != self.objects_dir.resolve() or not path.is_file():
            raise FileNotFoundError("Физический файл отсутствует в хранилище.")
        item["path"] = path
        return item

    def delete_file(self, file_id: str) -> dict[str, str]:
        item = self.get_file(file_id)
        with self._session() as db:
            db.execute("DELETE FROM disk_files WHERE id = ?", (file_id,))
        item["path"].unlink(missing_ok=True)
        return {"status": "удалено", "id": file_id}

    def delete_folder(self, folder_id: str) -> dict[str, str]:
        with self._session() as db:
            self._require_folder(db, folder_id)
            child_folder = db.execute(
                "SELECT 1 FROM disk_folders WHERE parent_id = ? LIMIT 1",
                (folder_id,),
            ).fetchone()
            child_file = db.execute(
                "SELECT 1 FROM disk_files WHERE folder_id = ? LIMIT 1",
                (folder_id,),
            ).fetchone()
            if child_folder or child_file:
                raise OSError("Папку можно удалить только после очистки.")
            db.execute("DELETE FROM disk_folders WHERE id = ?", (folder_id,))
        return {"status": "удалено", "id": folder_id}


    def health(self) -> dict[str, Any]:
        listing = self.list_entries()
        return {
            "status": "готово",
            "status_code": "ready",
            "schema_version": DISK_SCHEMA_VERSION,
            "files": listing["stats"]["files"],
            "folders": listing["stats"]["folders"],
            "bytes": listing["stats"]["bytes"],
            "max_file_size": MAX_FILE_SIZE,
            "storage_path": str(self.storage_root),
        }
