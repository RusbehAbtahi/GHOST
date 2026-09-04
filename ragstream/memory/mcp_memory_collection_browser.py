"""Browse physical locations of owner-scoped GHOST Collections.

This module owns folder discovery and location-scoped Collection listing.
Numbered episode metadata and recall remain in McpMemoryCollectionRetriever.

Main classes:
    McpMemoryCollectionBrowser:
        Lists Main, ordinary folders, Archive, and Collections in one location.

Main methods:
    list_collections():
        Lists Collections directly in one selected location.
    list_collection_folders():
        Lists Main, ordinary immediate subfolders, and Archive.
"""

from __future__ import annotations

import json
import re
import sqlite3

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


class McpMemoryCollectionBrowser:
    """Own deterministic folder discovery and one-location Collection listing."""

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
        MemoryManager(self.memory_root, self.sqlite_path)
        ensure_collection_schema(self.sqlite_path)

    def list_collections(
        self,
        owner_sub: str,
        folder: str | None = None,
    ) -> list[dict[str, Any]]:
        """List Collections directly in Main, one ordinary folder, or Archive."""
        owner = self._validate_owner_sub(owner_sub)
        clean_folder = normalize_collection_folder(folder)
        if clean_folder == COLLECTION_ARCHIVE_FOLDER:
            return self._list_archived_collections(owner)

        expected_parent = collection_storage_folder(owner, clean_folder)
        with sqlite3.connect(self.sqlite_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT file_id AS collection_id,
                       title AS collection_name,
                       memory_description AS collection_description,
                       created_at_utc,
                       updated_at_utc,
                       record_count,
                       next_sequence_number,
                       filename_ragmem
                FROM memory_files
                WHERE owner_sub = ? AND memory_type = ?
                ORDER BY created_at_utc, file_id
                """,
                [owner, COLLECTION_MEMORY_TYPE],
            ).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            relative_parent = Path(str(row["filename_ragmem"])).parent.as_posix()
            if relative_parent != expected_parent:
                continue
            item = dict(row)
            item.pop("filename_ragmem", None)
            item["folder"] = clean_folder
            item["highest_assigned_episode_number"] = (
                int(item["next_sequence_number"]) - 1
            )
            result.append(item)
        return result

    def list_collection_folders(self, owner_sub: str) -> list[str]:
        """List Main, ordinary immediate subfolders, and the reserved Archive."""
        owner = self._validate_owner_sub(owner_sub)
        root = self.memory_root / "files" / owner / "collections"
        ordinary: list[str] = []
        if root.is_dir():
            ordinary = sorted(
                path.name
                for path in root.iterdir()
                if path.is_dir()
                and path.name.casefold()
                not in {
                    COLLECTION_MAIN_FOLDER.casefold(),
                    COLLECTION_ARCHIVE_FOLDER.casefold(),
                }
            )
        return [COLLECTION_MAIN_FOLDER, *ordinary, COLLECTION_ARCHIVE_FOLDER]

    def _list_archived_collections(
        self,
        owner_sub: str,
    ) -> list[dict[str, Any]]:
        archive_root = (
            self.memory_root
            / "files"
            / collection_storage_folder(owner_sub, COLLECTION_ARCHIVE_FOLDER)
        )
        if not archive_root.is_dir():
            return []

        result: list[dict[str, Any]] = []
        for path in sorted(archive_root.glob("*.ragmeta.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if (
                not isinstance(data, dict)
                or str(data.get("owner_sub", "") or "") != owner_sub
                or str(data.get("memory_type", "") or "")
                != COLLECTION_MEMORY_TYPE
            ):
                continue
            try:
                next_number = int(data.get("next_sequence_number", 1))
                record_count = int(data.get("record_count", 0))
            except (TypeError, ValueError):
                continue
            result.append(
                {
                    "collection_id": str(data.get("file_id", "") or ""),
                    "collection_name": str(data.get("title", "") or ""),
                    "collection_description": str(
                        data.get("memory_description", "") or ""
                    ),
                    "created_at_utc": str(data.get("created_at_utc", "") or ""),
                    "updated_at_utc": str(data.get("updated_at_utc", "") or ""),
                    "record_count": record_count,
                    "next_sequence_number": next_number,
                    "highest_assigned_episode_number": next_number - 1,
                    "folder": COLLECTION_ARCHIVE_FOLDER,
                }
            )
        return result

    @staticmethod
    def _validate_owner_sub(owner_sub: str) -> str:
        if (
            not isinstance(owner_sub, str)
            or owner_sub in {"", ".", ".."}
            or _OWNER_SUB_PATTERN.fullmatch(owner_sub) is None
        ):
            raise ValueError("owner_sub is not a safe path component")
        return owner_sub
