"""Move, archive, and restore owner-scoped GHOST Collections.

This module owns physical Collection location changes and the SQLite lifecycle
needed by Archive. Collection episode creation/deletion and numbered recall
remain in the existing store and retriever.

Main classes:
    McpMemoryCollectionManager:
        Coordinates active moves, Archive removal, and durable restore.

Main methods:
    move_collection():
        Moves one active Collection to Main or one ordinary subfolder.
    archive_collection():
        Moves one active Collection to Archive and removes its live index rows.
    restore_collection():
        Restores one archived Collection and rebuilds its live SQLite rows.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading

from pathlib import Path
from typing import Any

from ragstream.memory.mcp_memory_collection_paths import (
    COLLECTION_ARCHIVE_FOLDER,
    COLLECTION_MAIN_FOLDER,
    collection_storage_folder,
    normalize_collection_folder,
)
from ragstream.memory.mcp_memory_collection_store import (
    COLLECTION_MEMORY_TYPE,
    DEFAULT_MEMORY_ROOT,
    ensure_collection_schema,
)
from ragstream.memory.memory_manager import MemoryManager


_OWNER_SUB_PATTERN = re.compile(r"[A-Za-z0-9._-]+")


class McpMemoryCollectionManager:
    """Own safe Collection location changes without changing Collection identity."""

    def __init__(
        self,
        memory_root: str | Path = DEFAULT_MEMORY_ROOT,
        sqlite_path: str | Path | None = None,
    ) -> None:
        self.memory_root = Path(memory_root)
        self.sqlite_path = (
            Path(sqlite_path)
            if sqlite_path is not None
            else self.memory_root / "memory_index.sqlite3"
        )
        self._lock = threading.Lock()
        MemoryManager(self.memory_root, self.sqlite_path)
        ensure_collection_schema(self.sqlite_path)

    @property
    def files_root(self) -> Path:
        return self.memory_root / "files"

    def move_collection(
        self,
        owner_sub: str,
        collection_id: str,
        destination_folder: str,
    ) -> dict[str, Any]:
        """Move one active Collection while keeping its SQLite records live."""
        owner = self._validate_owner_sub(owner_sub)
        identifier = self._require_text(collection_id, "collection_id")
        folder = normalize_collection_folder(destination_folder)
        if folder == COLLECTION_ARCHIVE_FOLDER:
            raise ValueError("use archive action to move a Collection to Archive")

        with self._lock:
            row = self._active_collection(owner, identifier)
            return self._move_active(row, owner, folder, archive=False)

    def archive_collection(
        self,
        owner_sub: str,
        collection_id: str,
    ) -> dict[str, Any]:
        """Move one active Collection to Archive and remove its live index rows."""
        owner = self._validate_owner_sub(owner_sub)
        identifier = self._require_text(collection_id, "collection_id")

        with self._lock:
            row = self._active_collection(owner, identifier)
            return self._move_active(
                row,
                owner,
                COLLECTION_ARCHIVE_FOLDER,
                archive=True,
            )

    def restore_collection(
        self,
        owner_sub: str,
        collection_id: str,
        destination_folder: str | None = None,
    ) -> dict[str, Any]:
        """Restore one archived Collection and rebuild its SQLite representation."""
        owner = self._validate_owner_sub(owner_sub)
        identifier = self._require_text(collection_id, "collection_id")
        folder = normalize_collection_folder(destination_folder)
        if folder == COLLECTION_ARCHIVE_FOLDER:
            raise ValueError("restore destination cannot be Archive")

        with self._lock:
            meta_path, metainfo = self._archived_collection(owner, identifier)
            self._validate_restore_collisions(owner, metainfo)

            ragmem_name = (
                meta_path.name.removesuffix(".ragmeta.json") + ".ragmem"
            )
            archive_ragmem = meta_path.with_name(ragmem_name)
            if not archive_ragmem.is_file() or not meta_path.is_file():
                raise ValueError("archived Collection files are incomplete")

            destination_root = self.files_root / collection_storage_folder(owner, folder)
            destination_root.mkdir(parents=True, exist_ok=True)
            new_ragmem = destination_root / archive_ragmem.name
            new_meta = destination_root / meta_path.name
            if new_ragmem.exists() or new_meta.exists():
                raise ValueError("restore destination already contains Collection files")

            original_meta = meta_path.read_bytes()
            archive_ragmem.rename(new_ragmem)
            try:
                meta_path.rename(new_meta)
            except Exception:
                new_ragmem.rename(archive_ragmem)
                raise

            try:
                self._write_meta_paths(
                    new_meta,
                    new_ragmem.relative_to(self.files_root).as_posix(),
                    new_meta.relative_to(self.files_root).as_posix(),
                )
                self._rebuild_sqlite(new_ragmem, new_meta)
            except Exception:
                self._delete_index_rows(identifier)
                if new_ragmem.exists():
                    new_ragmem.rename(archive_ragmem)
                if new_meta.exists():
                    new_meta.rename(meta_path)
                meta_path.write_bytes(original_meta)
                raise

            return {
                "success": True,
                "action": "restore",
                "collection_id": identifier,
                "collection_name": str(metainfo.get("title", "")),
                "folder": folder,
            }

    def _move_active(
        self,
        row: dict[str, Any],
        owner: str,
        folder: str,
        *,
        archive: bool,
    ) -> dict[str, Any]:
        old_ragmem = self.files_root / str(row["filename_ragmem"])
        old_meta = self.files_root / str(row["filename_meta"])
        if not old_ragmem.is_file() or not old_meta.is_file():
            raise ValueError("Collection files are incomplete")

        destination_root = self.files_root / collection_storage_folder(owner, folder)
        destination_root.mkdir(parents=True, exist_ok=True)
        new_ragmem = destination_root / old_ragmem.name
        new_meta = destination_root / old_meta.name

        if new_ragmem == old_ragmem and new_meta == old_meta:
            return {
                "success": True,
                "action": "move",
                "collection_id": str(row["file_id"]),
                "collection_name": str(row["title"]),
                "folder": folder,
            }
        if new_ragmem.exists() or new_meta.exists():
            raise ValueError("destination already contains Collection files")

        original_meta = old_meta.read_bytes()
        old_ragmem.rename(new_ragmem)
        try:
            old_meta.rename(new_meta)
        except Exception:
            new_ragmem.rename(old_ragmem)
            raise

        new_ragmem_name = new_ragmem.relative_to(self.files_root).as_posix()
        new_meta_name = new_meta.relative_to(self.files_root).as_posix()
        try:
            self._write_meta_paths(new_meta, new_ragmem_name, new_meta_name)
            if archive:
                self._delete_index_rows(
                    str(row["file_id"]),
                    require_file_row=True,
                )
            else:
                self._update_index_paths(
                    str(row["file_id"]),
                    new_ragmem_name,
                    new_meta_name,
                )
        except Exception:
            if new_ragmem.exists():
                new_ragmem.rename(old_ragmem)
            if new_meta.exists():
                new_meta.rename(old_meta)
            old_meta.write_bytes(original_meta)
            raise

        return {
            "success": True,
            "action": "archive" if archive else "move",
            "collection_id": str(row["file_id"]),
            "collection_name": str(row["title"]),
            "folder": folder,
        }

    def _active_collection(self, owner: str, collection_id: str) -> dict[str, Any]:
        with sqlite3.connect(self.sqlite_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT file_id, title, filename_ragmem, filename_meta
                FROM memory_files
                WHERE owner_sub = ? AND memory_type = ? AND file_id = ?
                """,
                [owner, COLLECTION_MEMORY_TYPE, collection_id],
            ).fetchone()
        if row is None:
            raise ValueError("active Collection was not found for the authenticated user")
        return dict(row)

    def _archived_collection(
        self,
        owner: str,
        collection_id: str,
    ) -> tuple[Path, dict[str, Any]]:
        archive_root = self.files_root / collection_storage_folder(
            owner,
            COLLECTION_ARCHIVE_FOLDER,
        )
        matches: list[tuple[Path, dict[str, Any]]] = []
        if archive_root.is_dir():
            for path in archive_root.glob("*.ragmeta.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if (
                    isinstance(data, dict)
                    and str(data.get("file_id", "") or "") == collection_id
                    and str(data.get("owner_sub", "") or "") == owner
                    and str(data.get("memory_type", "") or "")
                    == COLLECTION_MEMORY_TYPE
                ):
                    matches.append((path, data))
        if len(matches) != 1:
            raise ValueError("archived Collection could not be resolved safely")
        return matches[0]

    def _validate_restore_collisions(
        self,
        owner: str,
        metainfo: dict[str, Any],
    ) -> None:
        collection_id = str(metainfo.get("file_id", "") or "").strip()
        title = str(metainfo.get("title", "") or "").strip()
        if not collection_id or not title:
            raise ValueError("archived Collection metadata is incomplete")

        with sqlite3.connect(self.sqlite_path) as connection:
            active = connection.execute(
                """
                SELECT 1 FROM memory_files
                WHERE owner_sub = ? AND memory_type = ?
                  AND (file_id = ? OR title = ?)
                LIMIT 1
                """,
                [owner, COLLECTION_MEMORY_TYPE, collection_id, title],
            ).fetchone()
            if active is not None:
                raise ValueError("an active Collection already uses this identity or name")

            keys = [
                str(item.get("direct_recall_key", "") or "").strip()
                for item in metainfo.get("records", [])
                if isinstance(item, dict)
                and str(item.get("direct_recall_key", "") or "").strip()
            ]
            if keys:
                placeholders = ",".join("?" for _ in keys)
                collision = connection.execute(
                    f"""
                    SELECT 1
                    FROM memory_records AS mr
                    JOIN memory_files AS mf ON mf.file_id = mr.file_id
                    WHERE mf.owner_sub = ?
                      AND mr.direct_recall_key IN ({placeholders})
                    LIMIT 1
                    """,
                    [owner, *keys],
                ).fetchone()
                if collision is not None:
                    raise ValueError("an active memory already uses an archived Recall Key")

    def _rebuild_sqlite(self, ragmem_path: Path, meta_path: Path) -> None:
        metainfo = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(metainfo, dict):
            raise ValueError("archived Collection metadata is invalid")

        manager = MemoryManager(self.memory_root, self.sqlite_path)
        manager.file_id = self._require_text(metainfo.get("file_id"), "file_id")
        manager.title = self._require_text(metainfo.get("title"), "title")
        manager.memory_type = self._require_text(
            metainfo.get("memory_type"),
            "memory_type",
        )
        if manager.memory_type != COLLECTION_MEMORY_TYPE:
            raise ValueError("archived memory is not a Collection")
        manager.memory_description = str(metainfo.get("memory_description", "") or "")
        manager.actors = list(metainfo.get("actors", []) or [])
        manager.owner_sub = self._require_text(metainfo.get("owner_sub"), "owner_sub")
        manager.expires_at_utc = metainfo.get("expires_at_utc")
        manager.created_at_utc = str(metainfo.get("created_at_utc", "") or "")
        manager.updated_at_utc = str(metainfo.get("updated_at_utc", "") or "")
        manager.filename_ragmem = ragmem_path.relative_to(self.files_root).as_posix()
        manager.filename_meta = meta_path.relative_to(self.files_root).as_posix()
        manager.metainfo = metainfo
        manager.records = manager._read_ragmem_records(ragmem_path)
        manager._apply_metainfo_overlay_to_records()

        highest = max((record.sequence_number for record in manager.records), default=0)
        try:
            next_number = int(metainfo["next_sequence_number"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("archived next_sequence_number is invalid") from error
        if next_number <= highest:
            raise ValueError("archived next_sequence_number is not coherent")

        manager.metainfo["next_sequence_number"] = next_number
        manager.save_metainfo()
        manager.refresh_sqlite_index()
        with sqlite3.connect(self.sqlite_path) as connection:
            connection.execute(
                "UPDATE memory_files SET next_sequence_number = ? WHERE file_id = ?",
                [next_number, manager.file_id],
            )
            connection.commit()

    @staticmethod
    def _write_meta_paths(
        meta_path: Path,
        filename_ragmem: str,
        filename_meta: str,
    ) -> None:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Collection metadata is invalid")
        data["filename_ragmem"] = filename_ragmem
        data["filename_meta"] = filename_meta
        meta_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _update_index_paths(
        self,
        collection_id: str,
        filename_ragmem: str,
        filename_meta: str,
    ) -> None:
        with sqlite3.connect(self.sqlite_path) as connection:
            cursor = connection.execute(
                """
                UPDATE memory_files
                SET filename_ragmem = ?, filename_meta = ?
                WHERE file_id = ? AND memory_type = ?
                """,
                [filename_ragmem, filename_meta, collection_id, COLLECTION_MEMORY_TYPE],
            )
            if cursor.rowcount != 1:
                raise ValueError("Collection SQLite path update failed")
            connection.commit()

    def _delete_index_rows(
        self,
        collection_id: str,
        *,
        require_file_row: bool = False,
    ) -> None:
        with sqlite3.connect(self.sqlite_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM memory_records WHERE file_id = ?",
                [collection_id],
            )
            cursor = connection.execute(
                "DELETE FROM memory_files WHERE file_id = ? AND memory_type = ?",
                [collection_id, COLLECTION_MEMORY_TYPE],
            )
            if cursor.rowcount not in {0, 1}:
                raise ValueError("Collection SQLite removal failed")
            if require_file_row and cursor.rowcount != 1:
                raise ValueError("active Collection SQLite row was not removed")
            connection.commit()

    @staticmethod
    def _validate_owner_sub(owner_sub: str) -> str:
        if (
            not isinstance(owner_sub, str)
            or owner_sub in {"", ".", ".."}
            or _OWNER_SUB_PATTERN.fullmatch(owner_sub) is None
        ):
            raise ValueError("owner_sub is not a safe path component")
        return owner_sub

    @staticmethod
    def _require_text(value: Any, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string")
        return value.strip()
