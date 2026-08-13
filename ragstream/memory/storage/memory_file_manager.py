# ragstream/memory/storage/memory_file_manager.py
# -*- coding: utf-8 -*-
"""Manage the files and SQLite identity of complete GHOST memory histories.

Main classes:
    MemoryFileManager:
        Creates, loads, renames, lists, and deletes whole memory histories.

Important notes:
    file_id is stable identity; filenames and titles remain mutable metadata.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ragstream.memory.memory_manager import MemoryManager
from ragstream.textforge.RagLog import LogALL as logger
from ragstream.textforge.RagLog import LogDeveloper as _logger_dev


DEV_LOG_ENABLED = False


def logger_dev(*args, **kwargs):
    if DEV_LOG_ENABLED:
        return _logger_dev(*args, **kwargs)
    return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_title(title: str) -> str:
    value = (title or "").strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-._")
    return value or "Memory"


class MemoryFileManager:
    """
    Server-side manager for memory history files.

    Owns file-level operations:
    - list histories
    - create history
    - load history
    - rename history
    - delete history

    Identity rule:
    - file_id is stable identity.
    - filename_ragmem / filename_meta are mutable path/display fields.
    """

    def __init__(
        self,
        memory_manager: MemoryManager,
        memory_vector_store: Any | None = None,
    ) -> None:
        self.memory_manager = memory_manager
        self.memory_vector_store = memory_vector_store

    def list_histories(self) -> list[dict[str, Any]]:
        """Return all memory histories from SQLite."""
        return self.memory_manager.list_histories()

    def create_history(
        self,
        title: str,
        *,
        memory_type: str = "",
        memory_description: str = "",
        actors: list[Any] | None = None,
        owner_sub: str = "",
        expires_at_utc: str | None = None,
        storage_folder: str = "",
    ) -> dict[str, Any]:
        """
        Create a new empty memory history and make it active.

        Creates:
        - empty .ragmem file
        - .ragmeta.json file
        - SQLite memory_files row
        """
        clean_title = str(title or "").strip()
        if not clean_title:
            raise ValueError("title must not be empty.")

        self.memory_manager.start_new_history(
            clean_title,
            memory_type=memory_type,
            memory_description=memory_description,
            actors=actors,
            owner_sub=owner_sub,
            expires_at_utc=expires_at_utc,
            storage_folder=storage_folder,
        )

        now = self.memory_manager.created_at_utc or _utc_now()

        self.memory_manager.ragmem_path.parent.mkdir(parents=True, exist_ok=True)
        self.memory_manager.meta_path.parent.mkdir(parents=True, exist_ok=True)
        self.memory_manager.ragmem_path.touch(exist_ok=False)

        metainfo = {
            "file_id": self.memory_manager.file_id,
            "title": self.memory_manager.title,
            "memory_type": self.memory_manager.memory_type,
            "memory_description": self.memory_manager.memory_description,
            "actors": list(self.memory_manager.actors),
            "filename_ragmem": self.memory_manager.filename_ragmem,
            "filename_meta": self.memory_manager.filename_meta,
            "created_at_utc": now,
            "updated_at_utc": now,
            "record_count": 0,
            "record_ids": [],
            "parent_ids": [],
            "tag_summary": {},
            "auto_keywords": [],
            "user_keywords": [],
            "records": [],
            "owner_sub": self.memory_manager.owner_sub,
            "expires_at_utc": self.memory_manager.expires_at_utc,
        }

        self.memory_manager.metainfo = metainfo
        self.memory_manager.b_file_created = True

        with self.memory_manager.meta_path.open("w", encoding="utf-8") as f:
            json.dump(metainfo, f, ensure_ascii=False, indent=2)

        self._insert_empty_file_row(
            file_id=self.memory_manager.file_id,
            title=self.memory_manager.title,
            filename_ragmem=self.memory_manager.filename_ragmem,
            filename_meta=self.memory_manager.filename_meta,
            created_at_utc=now,
            updated_at_utc=now,
            memory_type=self.memory_manager.memory_type,
            memory_description=self.memory_manager.memory_description,
            actors=self.memory_manager.actors,
            owner_sub=self.memory_manager.owner_sub,
            expires_at_utc=self.memory_manager.expires_at_utc,
        )

        logger_dev(
            (
                "MemoryFileManager.create_history\n"
                f"file_id={self.memory_manager.file_id}\n"
                f"title={self.memory_manager.title}\n"
                f"filename_ragmem={self.memory_manager.filename_ragmem}\n"
                f"filename_meta={self.memory_manager.filename_meta}"
            ),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return {
            "success": True,
            "file_id": self.memory_manager.file_id,
            "title": self.memory_manager.title,
            "memory_type": self.memory_manager.memory_type,
            "memory_description": self.memory_manager.memory_description,
            "actors": list(self.memory_manager.actors),
            "filename_ragmem": self.memory_manager.filename_ragmem,
            "filename_meta": self.memory_manager.filename_meta,
            "record_count": 0,
        }

    def load_history(self, file_id: str) -> dict[str, Any]:
        """Load one memory history into the active MemoryManager."""
        clean_file_id = self._clean_file_id(file_id)
        self.memory_manager.load_history(clean_file_id)

        return {
            "success": True,
            "file_id": self.memory_manager.file_id,
            "title": self.memory_manager.title,
            "memory_type": self.memory_manager.memory_type,
            "memory_description": self.memory_manager.memory_description,
            "actors": list(self.memory_manager.actors),
            "filename_ragmem": self.memory_manager.filename_ragmem,
            "filename_meta": self.memory_manager.filename_meta,
            "record_count": len(self.memory_manager.records),
        }

    def rename_history(
        self,
        file_id: str,
        new_title: str,
    ) -> dict[str, Any]:
        """
        Rename one memory history.

        Updates:
        - physical .ragmem filename
        - physical .ragmeta.json filename
        - SQLite memory_files row
        - file-level fields inside .ragmeta.json
        """
        clean_file_id = self._clean_file_id(file_id)
        clean_title = (new_title or "").strip()

        if not clean_title:
            raise ValueError("new_title must not be empty.")

        row = self._lookup_file(clean_file_id)
        if not row:
            raise ValueError(f"Memory history not found: {clean_file_id}")

        old_ragmem = self.memory_manager.files_root / row["filename_ragmem"]
        old_meta = self.memory_manager.files_root / row["filename_meta"]

        old_relative_ragmem = Path(str(row["filename_ragmem"]))
        relative_parent = old_relative_ragmem.parent
        timestamp_prefix = self._extract_timestamp_prefix(row["filename_ragmem"])
        stem = f"{timestamp_prefix}-{_safe_title(clean_title)}"

        new_ragmem_name = str(relative_parent / f"{stem}.ragmem")
        new_meta_name = str(relative_parent / f"{stem}.ragmeta.json")

        new_ragmem = self.memory_manager.files_root / new_ragmem_name
        new_meta = self.memory_manager.files_root / new_meta_name

        if new_ragmem.exists() or new_meta.exists():
            stem = f"{stem}-{clean_file_id[:8]}"
            new_ragmem_name = str(relative_parent / f"{stem}.ragmem")
            new_meta_name = str(relative_parent / f"{stem}.ragmeta.json")
            new_ragmem = self.memory_manager.files_root / new_ragmem_name
            new_meta = self.memory_manager.files_root / new_meta_name

        if old_ragmem.exists():
            old_ragmem.rename(new_ragmem)

        if old_meta.exists():
            old_meta.rename(new_meta)

        now = _utc_now()

        self._update_sqlite_file_row(
            file_id=clean_file_id,
            title=clean_title,
            filename_ragmem=new_ragmem_name,
            filename_meta=new_meta_name,
            updated_at_utc=now,
        )

        if self.memory_manager.file_id == clean_file_id:
            self.memory_manager.title = clean_title
            self.memory_manager.filename_ragmem = new_ragmem_name
            self.memory_manager.filename_meta = new_meta_name
            self.memory_manager.save_metainfo()
            self.memory_manager.refresh_sqlite_index()
        else:
            self._update_meta_json_file_fields(
                meta_path=new_meta,
                title=clean_title,
                filename_ragmem=new_ragmem_name,
                filename_meta=new_meta_name,
                updated_at_utc=now,
            )

        logger_dev(
            (
                "MemoryFileManager.rename_history\n"
                f"file_id={clean_file_id}\n"
                f"old_ragmem={row['filename_ragmem']}\n"
                f"new_ragmem={new_ragmem_name}\n"
                f"old_meta={row['filename_meta']}\n"
                f"new_meta={new_meta_name}"
            ),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return {
            "success": True,
            "file_id": clean_file_id,
            "title": clean_title,
            "filename_ragmem": new_ragmem_name,
            "filename_meta": new_meta_name,
        }

    def delete_history(self, file_id: str) -> dict[str, Any]:
        """
        Delete one memory history.

        Deletes:
        - physical .ragmem
        - physical .ragmeta.json
        - SQLite memory_files row
        - SQLite memory_records rows
        - memory vectors by file_id
        """
        clean_file_id = self._clean_file_id(file_id)
        row = self._lookup_file(clean_file_id)

        if not row:
            raise ValueError(f"Memory history not found: {clean_file_id}")

        ragmem_path = self.memory_manager.files_root / row["filename_ragmem"]
        meta_path = self.memory_manager.files_root / row["filename_meta"]

        vectors_deleted = 0
        if self.memory_vector_store is not None and hasattr(self.memory_vector_store, "delete_file"):
            vector_result = self.memory_vector_store.delete_file(clean_file_id)
            vectors_deleted = int(vector_result.get("deleted_vectors", 0) or 0)

        self._delete_sqlite_rows(clean_file_id)

        if ragmem_path.exists():
            ragmem_path.unlink()

        if meta_path.exists():
            meta_path.unlink()

        if self.memory_manager.file_id == clean_file_id:
            self._reset_active_memory_manager()

        logger_dev(
            (
                "MemoryFileManager.delete_history\n"
                f"file_id={clean_file_id}\n"
                f"filename_ragmem={row['filename_ragmem']}\n"
                f"filename_meta={row['filename_meta']}\n"
                f"vectors_deleted={vectors_deleted}"
            ),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return {
            "success": True,
            "file_id": clean_file_id,
            "title": row["title"],
            "filename_ragmem": row["filename_ragmem"],
            "filename_meta": row["filename_meta"],
            "vectors_deleted": vectors_deleted,
        }

    def _lookup_file(self, file_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.memory_manager.sqlite_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT file_id, title, memory_type, memory_description,
                       actors_json, filename_ragmem, filename_meta,
                       created_at_utc, updated_at_utc, record_count,
                       owner_sub, expires_at_utc
                FROM memory_files
                WHERE file_id = ?
                """,
                (file_id,),
            ).fetchone()

        return dict(row) if row else None

    def _insert_empty_file_row(
        self,
        *,
        file_id: str,
        title: str,
        filename_ragmem: str,
        filename_meta: str,
        created_at_utc: str,
        updated_at_utc: str,
        memory_type: str,
        memory_description: str,
        actors: list[Any],
        owner_sub: str,
        expires_at_utc: str | None,
    ) -> None:
        with sqlite3.connect(self.memory_manager.sqlite_path) as conn:
            conn.execute(
                """
                INSERT INTO memory_files (
                    file_id, title, memory_type, memory_description,
                    actors_json, filename_ragmem, filename_meta,
                    created_at_utc, updated_at_utc, record_count,
                    owner_sub, expires_at_utc
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                ON CONFLICT(file_id) DO UPDATE SET
                    title = excluded.title,
                    memory_type = excluded.memory_type,
                    memory_description = excluded.memory_description,
                    actors_json = excluded.actors_json,
                    filename_ragmem = excluded.filename_ragmem,
                    filename_meta = excluded.filename_meta,
                    created_at_utc = excluded.created_at_utc,
                    updated_at_utc = excluded.updated_at_utc,
                    record_count = excluded.record_count,
                    owner_sub = excluded.owner_sub,
                    expires_at_utc = excluded.expires_at_utc
                """,
                (
                    file_id,
                    title,
                    memory_type,
                    memory_description,
                    json.dumps(actors, ensure_ascii=False),
                    filename_ragmem,
                    filename_meta,
                    created_at_utc,
                    updated_at_utc,
                    owner_sub,
                    expires_at_utc,
                ),
            )
            conn.commit()

    def _update_sqlite_file_row(
        self,
        *,
        file_id: str,
        title: str,
        filename_ragmem: str,
        filename_meta: str,
        updated_at_utc: str,
    ) -> None:
        with sqlite3.connect(self.memory_manager.sqlite_path) as conn:
            conn.execute(
                """
                UPDATE memory_files
                SET title = ?,
                    filename_ragmem = ?,
                    filename_meta = ?,
                    updated_at_utc = ?
                WHERE file_id = ?
                """,
                (
                    title,
                    filename_ragmem,
                    filename_meta,
                    updated_at_utc,
                    file_id,
                ),
            )
            conn.commit()

    def _delete_sqlite_rows(self, file_id: str) -> None:
        with sqlite3.connect(self.memory_manager.sqlite_path) as conn:
            conn.execute(
                "DELETE FROM memory_records WHERE file_id = ?",
                (file_id,),
            )
            conn.execute(
                "DELETE FROM memory_files WHERE file_id = ?",
                (file_id,),
            )
            conn.commit()

    @staticmethod
    def _update_meta_json_file_fields(
        *,
        meta_path: Path,
        title: str,
        filename_ragmem: str,
        filename_meta: str,
        updated_at_utc: str,
    ) -> None:
        if not meta_path.exists():
            return

        try:
            with meta_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

        if not isinstance(data, dict):
            data = {}

        data["title"] = title
        data["filename_ragmem"] = filename_ragmem
        data["filename_meta"] = filename_meta
        data["updated_at_utc"] = updated_at_utc

        with meta_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _reset_active_memory_manager(self) -> None:
        self.memory_manager.file_id = uuid.uuid4().hex
        self.memory_manager.title = ""
        self.memory_manager.memory_type = ""
        self.memory_manager.memory_description = ""
        self.memory_manager.actors = []
        self.memory_manager.owner_sub = ""
        self.memory_manager.expires_at_utc = None
        self.memory_manager.created_at_utc = ""
        self.memory_manager.updated_at_utc = ""
        self.memory_manager.filename_ragmem = ""
        self.memory_manager.filename_meta = ""
        self.memory_manager.records = []
        self.memory_manager.metainfo = {}
        self.memory_manager.b_file_created = False

    @staticmethod
    def _extract_timestamp_prefix(filename_ragmem: str) -> str:
        text = Path(str(filename_ragmem or "").strip()).name
        match = re.match(r"^(\d{4}-\d{2}-\d{2}-\d{2}-\d{2})-", text)
        if match:
            return match.group(1)

        return datetime.now().strftime("%Y-%m-%d-%H-%M")

    @staticmethod
    def _clean_file_id(file_id: str) -> str:
        clean_file_id = str(file_id or "").strip()
        if not clean_file_id:
            raise ValueError("file_id must not be empty.")
        return clean_file_id