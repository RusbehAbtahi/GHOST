"""Persist owner-scoped MCP Collection Memory histories and episodes.

The module owns Collection lifecycle writes: initialization, explicit episode
append, individual episode deletion, and two-step whole-Collection deletion.
Common .ragmem, .ragmeta.json, SQLite, and MemoryRecord behavior remains owned
by MemoryManager and MemoryFileManager.

Main classes:
    McpMemoryCollectionStore:
        Applies Collection write and deletion policy to common GHOST storage.
    CollectionPartialWriteError:
        Reports a durable file write followed by an incoherent later failure.

Main methods:
    initialize_collection():
        Creates one empty Collection with a stable Collection ID.
    append_episode():
        Appends one numbered episode and advances its permanent counter.
    delete_episode():
        Removes one exact Collection episode without renumbering survivors.
    delete_collection():
        Requires two identical owner/Collection-ID requests before deletion.

Main functions:
    ensure_collection_schema():
        Adds the Collection counter and deterministic lookup index.
"""

from __future__ import annotations

import re
import sqlite3
import threading

from pathlib import Path
from typing import Any

from ragstream.memory.mcp_memory_store import MAX_EPISODE_TITLE_LENGTH
from ragstream.memory.memory_manager import MemoryManager
from ragstream.memory.memory_record import MemoryRecord
from ragstream.memory.storage.memory_file_manager import MemoryFileManager


COLLECTION_MEMORY_TYPE = "collection"
COLLECTION_SOURCE = "mcp_collection"
DEFAULT_MEMORY_ROOT = Path("data/mcp/memory")

_OWNER_SUB_PATTERN = re.compile(r"[A-Za-z0-9._-]+")
_CLIPBOARD_KEY_PATTERN = re.compile(
    r"M(?:[1-9]|[1-9][0-9]|100)",
    re.IGNORECASE,
)


def ensure_collection_schema(sqlite_path: str | Path) -> None:
    """Add the shared Collection counter and lookup index when absent."""
    with sqlite3.connect(Path(sqlite_path)) as connection:
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(memory_files)"
            ).fetchall()
        }
        if "next_sequence_number" not in columns:
            connection.execute(
                "ALTER TABLE memory_files ADD COLUMN "
                "next_sequence_number INTEGER NOT NULL DEFAULT 1"
            )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_memory_files_owner_type_title
            ON memory_files(owner_sub, memory_type, title)
            """
        )
        connection.commit()


class CollectionPartialWriteError(RuntimeError):
    """Indicate that Collection files changed before a later failure."""

    def __init__(self, operation: str, record_id: str = "") -> None:
        super().__init__(
            f"Collection {operation} changed durable data before failing"
        )
        self.operation = operation
        self.record_id = record_id


class McpMemoryCollectionStore:
    """Own Collection creation, append, and deterministic deletion policy."""

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
        self._pending_collection_deletes: set[tuple[str, str]] = set()

        # MemoryManager establishes the shared schema. This store adds only the
        # Collection-level monotonic counter required for stable episode gaps.
        self._new_memory_manager()
        ensure_collection_schema(self.sqlite_path)

    def initialize_collection(
        self,
        owner_sub: str,
        collection_name: str,
        collection_description: str,
    ) -> dict[str, Any]:
        """Create one persistent Collection and its permanent number counter."""
        owner = self._validate_owner_sub(owner_sub)
        name = self._require_text(
            collection_name,
            "collection_name",
            trim=True,
        )
        description = self._require_text(
            collection_description,
            "collection_description",
            trim=True,
        )

        with self._lock:
            if self._collection_name_exists(owner, name):
                raise ValueError(
                    "collection_name already exists for the authenticated user"
                )

            manager = self._new_memory_manager()
            result = MemoryFileManager(manager).create_history(
                name,
                memory_type=COLLECTION_MEMORY_TYPE,
                memory_description=description,
                actors=[],
                owner_sub=owner,
                storage_folder=f"{owner}/collections",
            )
            manager.metainfo["next_sequence_number"] = 1

            try:
                manager.save_metainfo()
                self._write_next_sequence_number(manager.file_id, 1)
            except Exception:
                try:
                    self._rollback_failed_initialization(manager.file_id)
                except Exception as rollback_error:
                    raise CollectionPartialWriteError(
                        "initialization rollback"
                    ) from rollback_error
                raise

        return {
            "collection_id": str(result["file_id"]),
            "collection_name": str(result["title"]),
            "collection_description": str(result["memory_description"]),
            "created_at_utc": manager.created_at_utc,
            "record_count": 0,
            "next_sequence_number": 1,
        }

    def append_episode(
        self,
        owner_sub: str,
        *,
        collection_id: str | None = None,
        collection_name: str | None = None,
        recall_key: str | None = None,
        episode_title: str,
        episode_description: str,
        input_text: str,
        output_text: str,
        active_retrieval_brief: str,
    ) -> dict[str, Any]:
        """Append one explicit episode and return its stable number and key."""
        owner = self._validate_owner_sub(owner_sub)
        title = self._require_text(
            episode_title,
            "episode_title",
            trim=True,
        )
        if len(title) > MAX_EPISODE_TITLE_LENGTH:
            raise ValueError(
                f"episode_title must be at most "
                f"{MAX_EPISODE_TITLE_LENGTH} characters."
            )

        description = self._require_text(
            episode_description,
            "episode_description",
            trim=True,
        )
        exact_input = self._require_text(input_text, "input_text")
        exact_output = self._require_text(output_text, "output_text")
        active_brief = self._require_text(
            active_retrieval_brief,
            "active_retrieval_brief",
            trim=True,
        )

        with self._lock:
            collection = self._resolve_collection(
                owner,
                collection_id=collection_id,
                collection_name=collection_name,
            )
            manager, sequence_number = self._load_collection_manager(
                collection
            )

            requested_key = self._clean_optional_recall_key(recall_key)
            base_key = requested_key or self._generate_recall_key(
                manager.title,
                sequence_number,
                title,
            )
            effective_key = self._allocate_unique_recall_key(owner, base_key)
            latest = self._latest_record(manager.records)

            record = MemoryRecord(
                input_text=exact_input,
                output_text=exact_output,
                source=COLLECTION_SOURCE,
                parent_id=latest.record_id if latest is not None else None,
                tag="Green",
                user_keywords=[],
                active_project_name=None,
                embedded_files_snapshot=[],
                retrieval_source_mode="QA",
                direct_recall_key=effective_key,
                episode_title=title,
                active_retrieval_brief_title=manager.title,
                active_retrieval_brief=active_brief,
                active_retrieval_brief_contributor_ids=[],
                sequence_number=sequence_number,
                actor_id="",
                chat_stream_id=manager.file_id,
                episode_description=description,
            )

            contributor_ids = [
                previous.record_id for previous in manager.records
            ]
            contributor_ids.append(record.record_id)
            record.update_active_retrieval_brief(
                active_retrieval_brief=active_brief,
                contributor_ids=contributor_ids,
                active_retrieval_brief_title=manager.title,
            )

            with manager.ragmem_path.open("a", encoding="utf-8") as file:
                file.write(record.to_ragmem_block())
                file.write("\n")

            next_sequence_number = sequence_number + 1
            manager.records.append(record)
            manager.metainfo["next_sequence_number"] = (
                next_sequence_number
            )

            try:
                manager.save_metainfo()
                manager.refresh_sqlite_index()
                self._write_next_sequence_number(
                    manager.file_id,
                    next_sequence_number,
                )
            except Exception as error:
                raise CollectionPartialWriteError(
                    "append",
                    record.record_id,
                ) from error

        return {
            "collection_id": manager.file_id,
            "collection_name": manager.title,
            "record_id": record.record_id,
            "episode_number": record.sequence_number,
            "requested_recall_key": requested_key,
            "recall_key": record.direct_recall_key,
            "episode_title": record.episode_title,
            "episode_description": record.episode_description,
            "created_at_utc": record.created_at_utc,
            "next_sequence_number": next_sequence_number,
        }

    def delete_episode(
        self,
        owner_sub: str,
        *,
        recall_key: str | None = None,
        record_id: str | None = None,
    ) -> dict[str, Any]:
        """Delete one exact Collection episode while preserving all numbers."""
        owner = self._validate_owner_sub(owner_sub)
        clean_key = (
            self._require_text(recall_key, "recall_key", trim=True)
            if recall_key is not None
            else None
        )
        clean_record_id = (
            self._require_text(record_id, "record_id", trim=True)
            if record_id is not None
            else None
        )

        if (clean_key is None) == (clean_record_id is None):
            raise ValueError(
                "exactly one of recall_key or record_id is required."
            )

        with self._lock:
            match = self._lookup_collection_episode(
                owner,
                recall_key=clean_key,
                record_id=clean_record_id,
            )
            if match is None:
                return {
                    "deleted": False,
                    "deleted_count": 0,
                    "memory_type": COLLECTION_MEMORY_TYPE,
                }

            manager, next_sequence_number = (
                self._load_collection_manager(match)
            )
            target_record_id = str(match["record_id"])
            target = next(
                (
                    record
                    for record in manager.records
                    if record.record_id == target_record_id
                ),
                None,
            )
            if target is None:
                raise ValueError(
                    "Collection body, metadata, and index do not match"
                )

            manager.records = [
                record
                for record in manager.records
                if record.record_id != target_record_id
            ]
            manager.ragmem_path.write_text(
                "".join(
                    f"{record.to_ragmem_block()}\n"
                    for record in manager.records
                ),
                encoding="utf-8",
            )
            manager.metainfo["next_sequence_number"] = (
                next_sequence_number
            )

            try:
                manager.save_metainfo()
                manager.refresh_sqlite_index()
                self._write_next_sequence_number(
                    manager.file_id,
                    next_sequence_number,
                )
            except Exception as error:
                raise CollectionPartialWriteError(
                    "episode deletion",
                    target_record_id,
                ) from error

        return {
            "deleted": True,
            "deleted_count": 1,
            "memory_type": COLLECTION_MEMORY_TYPE,
            "collection_id": manager.file_id,
            "record_id": target.record_id,
            "episode_number": target.sequence_number,
            "recall_key": target.direct_recall_key,
            "next_sequence_number": next_sequence_number,
        }

    def delete_collection(
        self,
        owner_sub: str,
        collection_id: str,
    ) -> dict[str, Any]:
        """Refuse once, then delete the same exact Collection on repetition."""
        owner = self._validate_owner_sub(owner_sub)
        clean_collection_id = self._require_text(
            collection_id,
            "collection_id",
            trim=True,
        )

        with self._lock:
            collection = self._resolve_collection(
                owner,
                collection_id=clean_collection_id,
                collection_name=None,
            )
            pending_key = (owner, clean_collection_id)

            if pending_key not in self._pending_collection_deletes:
                self._pending_collection_deletes.add(pending_key)
                return {
                    "deleted": False,
                    "confirmation_required": True,
                    "delete_pending": True,
                    "collection_id": clean_collection_id,
                    "collection_name": str(collection["title"]),
                    "record_count": int(collection["record_count"]),
                }

            manager = self._new_memory_manager()
            result = MemoryFileManager(manager).delete_history(
                clean_collection_id
            )
            self._pending_collection_deletes.discard(pending_key)

        return {
            "deleted": True,
            "confirmation_required": False,
            "delete_pending": False,
            "collection_id": clean_collection_id,
            "collection_name": str(result["title"]),
            "deleted_episode_count": int(collection["record_count"]),
        }

    def _new_memory_manager(self) -> MemoryManager:
        return MemoryManager(
            memory_root=self.memory_root,
            sqlite_path=self.sqlite_path,
        )

    def _resolve_collection(
        self,
        owner_sub: str,
        *,
        collection_id: str | None,
        collection_name: str | None,
    ) -> dict[str, Any]:
        clean_id = (
            self._require_text(
                collection_id,
                "collection_id",
                trim=True,
            )
            if collection_id is not None
            else None
        )
        clean_name = (
            self._require_text(
                collection_name,
                "collection_name",
                trim=True,
            )
            if collection_name is not None
            else None
        )

        if (clean_id is None) == (clean_name is None):
            raise ValueError(
                "exactly one of collection_id or collection_name is required."
            )

        selector = "file_id = ?" if clean_id is not None else "title = ?"
        selector_value = clean_id if clean_id is not None else clean_name

        with sqlite3.connect(self.sqlite_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                f"""
                SELECT file_id, title, memory_type, memory_description,
                       filename_ragmem, filename_meta, created_at_utc,
                       updated_at_utc, record_count, owner_sub,
                       next_sequence_number
                FROM memory_files
                WHERE owner_sub = ?
                  AND memory_type = ?
                  AND {selector}
                ORDER BY file_id
                """,
                [
                    owner_sub,
                    COLLECTION_MEMORY_TYPE,
                    selector_value,
                ],
            ).fetchall()

        if not rows:
            raise ValueError(
                "Collection was not found for the authenticated user"
            )
        if len(rows) != 1:
            raise ValueError("Collection could not be resolved safely")

        return dict(rows[0])

    def _load_collection_manager(
        self,
        collection: dict[str, Any],
    ) -> tuple[MemoryManager, int]:
        manager = self._new_memory_manager()
        manager.load_history(str(collection["file_id"]))

        valid_identity = (
            manager.owner_sub == str(collection["owner_sub"])
            and manager.memory_type == COLLECTION_MEMORY_TYPE
        )
        if not valid_identity:
            raise ValueError("Collection identity does not match")

        highest_sequence_number = max(
            (
                record.sequence_number
                for record in manager.records
            ),
            default=0,
        )
        sqlite_next = int(collection["next_sequence_number"])
        meta_next_raw = manager.metainfo.get("next_sequence_number")

        if meta_next_raw is None:
            # Repair Collections created before the permanent counter existed.
            repaired_next = max(
                sqlite_next,
                highest_sequence_number + 1,
            )
            manager.metainfo["next_sequence_number"] = repaired_next
            manager.save_metainfo()
            self._write_next_sequence_number(
                manager.file_id,
                repaired_next,
            )
            return manager, repaired_next

        try:
            meta_next = int(meta_next_raw)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "Collection next_sequence_number metadata is invalid"
            ) from error

        if (
            sqlite_next < 1
            or meta_next != sqlite_next
            or sqlite_next <= highest_sequence_number
        ):
            raise ValueError(
                "Collection sequence counter is not coherent"
            )

        return manager, sqlite_next

    def _lookup_collection_episode(
        self,
        owner_sub: str,
        *,
        recall_key: str | None,
        record_id: str | None,
    ) -> dict[str, Any] | None:
        selector = (
            "mr.direct_recall_key = ?"
            if recall_key is not None
            else "mr.record_id = ?"
        )
        selector_value = (
            recall_key if recall_key is not None else record_id
        )

        with sqlite3.connect(self.sqlite_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                f"""
                SELECT mr.record_id, mr.sequence_number,
                       mr.direct_recall_key, mf.file_id, mf.title,
                       mf.owner_sub, mf.memory_type, mf.filename_ragmem,
                       mf.filename_meta, mf.record_count,
                       mf.next_sequence_number
                FROM memory_records AS mr
                JOIN memory_files AS mf ON mf.file_id = mr.file_id
                WHERE mf.owner_sub = ?
                  AND mf.memory_type = ?
                  AND {selector}
                ORDER BY mr.created_at_utc DESC, mr.record_id DESC
                """,
                [
                    owner_sub,
                    COLLECTION_MEMORY_TYPE,
                    selector_value,
                ],
            ).fetchall()

        if not rows:
            return None
        if len(rows) != 1:
            raise ValueError(
                "Collection episode could not be resolved safely"
            )

        return dict(rows[0])

    def _allocate_unique_recall_key(
        self,
        owner_sub: str,
        base_key: str,
    ) -> str:
        with sqlite3.connect(self.sqlite_path) as connection:
            rows = connection.execute(
                """
                SELECT mr.direct_recall_key
                FROM memory_records AS mr
                JOIN memory_files AS mf ON mf.file_id = mr.file_id
                WHERE mf.owner_sub = ?
                  AND mr.direct_recall_key <> ''
                """,
                [owner_sub],
            ).fetchall()

        used_keys = {str(row[0]) for row in rows}
        if base_key not in used_keys:
            return base_key

        suffix = 1
        while f"{base_key}_{suffix}" in used_keys:
            suffix += 1

        return f"{base_key}_{suffix}"

    def _write_next_sequence_number(
        self,
        collection_id: str,
        next_sequence_number: int,
    ) -> None:
        with sqlite3.connect(self.sqlite_path) as connection:
            cursor = connection.execute(
                """
                UPDATE memory_files
                SET next_sequence_number = ?
                WHERE file_id = ?
                  AND memory_type = ?
                """,
                [
                    next_sequence_number,
                    collection_id,
                    COLLECTION_MEMORY_TYPE,
                ],
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    "Collection sequence counter was not stored"
                )
            connection.commit()

    def _collection_name_exists(
        self,
        owner_sub: str,
        collection_name: str,
    ) -> bool:
        with sqlite3.connect(self.sqlite_path) as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM memory_files
                WHERE owner_sub = ?
                  AND memory_type = ?
                  AND title = ?
                LIMIT 1
                """,
                [
                    owner_sub,
                    COLLECTION_MEMORY_TYPE,
                    collection_name,
                ],
            ).fetchone()

        return row is not None

    def _rollback_failed_initialization(
        self,
        collection_id: str,
    ) -> None:
        manager = self._new_memory_manager()
        MemoryFileManager(manager).delete_history(collection_id)

    @staticmethod
    def _latest_record(
        records: list[MemoryRecord],
    ) -> MemoryRecord | None:
        if not records:
            return None

        return max(
            records,
            key=lambda record: (
                record.sequence_number,
                record.created_at_utc,
                record.record_id,
            ),
        )

    @staticmethod
    def _generate_recall_key(
        collection_name: str,
        episode_number: int,
        episode_title: str,
    ) -> str:
        collection_part = McpMemoryCollectionStore._safe_key_component(
            collection_name
        )
        title_part = McpMemoryCollectionStore._safe_key_component(
            episode_title
        )
        return (
            f"{collection_part}-{episode_number:04d}-{title_part}"
        )

    @staticmethod
    def _safe_key_component(value: str) -> str:
        component = re.sub(
            r"[^\w.-]+",
            "-",
            value.strip(),
            flags=re.UNICODE,
        )
        component = re.sub(
            r"-{2,}",
            "-",
            component,
        ).strip("-._")
        return component or "memory"

    @staticmethod
    def _clean_optional_recall_key(
        value: str | None,
    ) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                "recall_key must be a non-empty string"
            )

        clean_key = value.strip()
        if _CLIPBOARD_KEY_PATTERN.fullmatch(clean_key) is not None:
            raise ValueError(
                "recall_key M1 through M100 is reserved for "
                "Clipboard Memory."
            )

        return clean_key

    @staticmethod
    def _validate_owner_sub(owner_sub: str) -> str:
        if not isinstance(owner_sub, str):
            raise ValueError(
                "owner_sub is not a safe path component."
            )
        if (
            owner_sub in {"", ".", ".."}
            or _OWNER_SUB_PATTERN.fullmatch(owner_sub) is None
        ):
            raise ValueError(
                "owner_sub is not a safe path component."
            )

        return owner_sub

    @staticmethod
    def _require_text(
        value: str,
        field_name: str,
        *,
        trim: bool = False,
    ) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"{field_name} must not be empty."
            )
        return value.strip() if trim else value