"""Persist one continuing MCP chat as one normal GHOST memory history.

The store owns only Persistent Chat policy: initialization, append with a
client-produced cumulative ActiveBrief, and deterministic owner-scoped resume.
MemoryRecord, MemoryManager, MemoryFileManager, .ragmem, .ragmeta.json, and the
shared SQLite schema remain the underlying GHOST persistence infrastructure.

Main classes:
    McpPersistentChatStore:
        Applies Persistent Chat policy to the common GHOST memory backend.
    PersistentChatPartialSaveError:
        Reports that durable episode data was written before a later failure.

Main methods:
    initialize_chat():
        Creates one empty, non-daily persistent chat history.
    append_episode():
        Appends visible Q/A and the updated cumulative ActiveBrief.
    resume_from_record():
        Resolves a history by owner and episode ID and returns its latest state.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading

from pathlib import Path
from typing import Any

from ragstream.memory.memory_manager import MemoryManager
from ragstream.memory.memory_record import MemoryRecord, RECORD_END, RECORD_START
from ragstream.memory.storage.memory_file_manager import MemoryFileManager


PERSISTENT_CHAT_MEMORY_TYPE = "persistent_chat"
PERSISTENT_CHAT_SOURCE = "mcp_persistent_chat"
DEFAULT_MEMORY_ROOT = Path("data/mcp/memory")

_OWNER_SUB_PATTERN = re.compile(r"[A-Za-z0-9._-]+")
_RECORD_PATTERN = re.compile(
    rf"{re.escape(RECORD_START)}\n(.*?)\n{re.escape(RECORD_END)}",
    re.DOTALL,
)
_RECORD_START_LINE_PATTERN = re.compile(
    rf"^{re.escape(RECORD_START)}$",
    re.MULTILINE,
)
_RECORD_END_LINE_PATTERN = re.compile(
    rf"^{re.escape(RECORD_END)}$",
    re.MULTILINE,
)


class PersistentChatPartialSaveError(RuntimeError):
    """Indicate that .ragmem was written but the save was not coherent."""

    def __init__(self, record_id: str) -> None:
        super().__init__(
            "durable episode data was written, but metadata/index update failed"
        )
        self.record_id = record_id


class McpPersistentChatStore:
    """Own Persistent Chat persistence on the common GHOST memory backend."""

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

        # MemoryManager owns the common schema and its backward-compatible
        # migrations. Creating an inactive manager performs only that setup.
        self._new_memory_manager()

    def initialize_chat(
        self,
        owner_sub: str,
        title: str,
        memory_description: str = "",
    ) -> dict[str, Any]:
        """Create one owner-scoped persistent history without a daily split."""
        owner = self._validate_owner_sub(owner_sub)
        clean_title = self._require_text(title, "title", trim=True)
        if not isinstance(memory_description, str):
            raise ValueError("memory_description must be a string.")

        with self._lock:
            manager = self._new_memory_manager()
            result = MemoryFileManager(manager).create_history(
                clean_title,
                memory_type=PERSISTENT_CHAT_MEMORY_TYPE,
                memory_description=memory_description.strip(),
                actors=[],
                owner_sub=owner,
                storage_folder=f"{owner}/active_blackboard",
            )

        return {
            "file_id": str(result["file_id"]),
            "title": str(result["title"]),
            "memory_type": str(result["memory_type"]),
            "memory_description": str(result["memory_description"]),
            "record_count": int(result["record_count"]),
        }

    def append_episode(
        self,
        owner_sub: str,
        file_id: str,
        input_text: str,
        output_text: str,
        active_retrieval_brief: str,
    ) -> dict[str, Any]:
        """Append one visible Q/A and its client-produced cumulative brief."""
        owner = self._validate_owner_sub(owner_sub)
        clean_file_id = self._require_text(file_id, "file_id", trim=True)
        exact_input = self._require_text(input_text, "input_text")
        exact_output = self._require_text(output_text, "output_text")
        clean_brief = self._require_text(
            active_retrieval_brief,
            "active_retrieval_brief",
            trim=True,
        )

        with self._lock:
            file_row = self._lookup_owner_chat(owner, clean_file_id)
            if file_row is None:
                raise ValueError(
                    "persistent chat memory was not found for the authenticated user"
                )

            self._validate_history_coherence(file_row)
            manager = self._load_manager(file_row)
            latest = self._latest_record(manager.records)
            next_sequence_number = max(
                len(manager.records),
                max(
                    (record.sequence_number for record in manager.records),
                    default=0,
                ),
            ) + 1

            record = MemoryRecord(
                input_text=exact_input,
                output_text=exact_output,
                source=PERSISTENT_CHAT_SOURCE,
                parent_id=latest.record_id if latest is not None else None,
                tag="Green",
                user_keywords=[],
                active_project_name=None,
                embedded_files_snapshot=[],
                retrieval_source_mode="QA",
                direct_recall_key="",
                episode_title="",
                active_retrieval_brief_title="",
                active_retrieval_brief=clean_brief,
                active_retrieval_brief_contributor_ids=[],
                sequence_number=next_sequence_number,
                actor_id="",
                chat_stream_id=manager.file_id,
                episode_description="",
            )

            with manager.ragmem_path.open("a", encoding="utf-8") as file:
                file.write(record.to_ragmem_block())
                file.write("\n")

            manager.records.append(record)
            try:
                manager.save_metainfo()
                manager.refresh_sqlite_index()
            except Exception as error:
                raise PersistentChatPartialSaveError(record.record_id) from error

        return {
            "file_id": manager.file_id,
            "record_id": record.record_id,
            "sequence_number": record.sequence_number,
            "created_at_utc": record.created_at_utc,
        }

    def resume_from_record(
        self,
        owner_sub: str,
        record_id: str,
    ) -> dict[str, Any] | None:
        """Resolve an existing history and return its latest coherent state."""
        owner = self._validate_owner_sub(owner_sub)
        resume_record_id = self._require_text(
            record_id,
            "record_id",
            trim=True,
        )

        with self._lock:
            file_rows = self._lookup_chats_by_record(owner, resume_record_id)
            if not file_rows:
                return None
            if len(file_rows) != 1:
                raise ValueError(
                    "persistent chat memory could not be resolved safely"
                )

            file_row = file_rows[0]
            self._validate_history_coherence(file_row)
            manager = self._load_manager(file_row)

            if resume_record_id not in {
                record.record_id for record in manager.records
            }:
                raise ValueError(
                    "persistent chat memory could not be resolved safely"
                )

            latest = self._latest_record(manager.records)
            if latest is None:
                raise ValueError(
                    "persistent chat memory has no resumable episode"
                )

        return {
            "resume_record_id": resume_record_id,
            "file_id": manager.file_id,
            "title": manager.title,
            "memory_type": manager.memory_type,
            "memory_description": manager.memory_description,
            "record_count": len(manager.records),
            "latest_record_id": latest.record_id,
            "latest_sequence_number": latest.sequence_number,
            "latest_created_at_utc": latest.created_at_utc,
            "active_retrieval_brief_title": (
                latest.active_retrieval_brief_title
            ),
            "active_retrieval_brief": latest.active_retrieval_brief,
        }

    def _new_memory_manager(self) -> MemoryManager:
        return MemoryManager(
            memory_root=self.memory_root,
            sqlite_path=self.sqlite_path,
        )

    def _load_manager(self, file_row: dict[str, Any]) -> MemoryManager:
        manager = self._new_memory_manager()
        manager.load_history(str(file_row["file_id"]))

        valid_identity = (
            manager.owner_sub == str(file_row["owner_sub"])
            and manager.memory_type == PERSISTENT_CHAT_MEMORY_TYPE
        )
        if not valid_identity:
            raise ValueError("persistent chat identity does not match")
        return manager

    def _lookup_owner_chat(
        self,
        owner_sub: str,
        file_id: str,
    ) -> dict[str, Any] | None:
        with sqlite3.connect(self.sqlite_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT file_id, title, memory_type, memory_description,
                       filename_ragmem, filename_meta, created_at_utc,
                       updated_at_utc, record_count, owner_sub
                FROM memory_files
                WHERE file_id = ?
                  AND owner_sub = ?
                  AND memory_type = ?
                """,
                [file_id, owner_sub, PERSISTENT_CHAT_MEMORY_TYPE],
            ).fetchone()
        return dict(row) if row is not None else None

    def _lookup_chats_by_record(
        self,
        owner_sub: str,
        record_id: str,
    ) -> list[dict[str, Any]]:
        with sqlite3.connect(self.sqlite_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT mf.file_id, mf.title, mf.memory_type,
                       mf.memory_description, mf.filename_ragmem,
                       mf.filename_meta, mf.created_at_utc,
                       mf.updated_at_utc, mf.record_count, mf.owner_sub
                FROM memory_records AS mr
                JOIN memory_files AS mf ON mf.file_id = mr.file_id
                WHERE mr.record_id = ?
                  AND mf.owner_sub = ?
                  AND mf.memory_type = ?
                ORDER BY mf.file_id
                """,
                [record_id, owner_sub, PERSISTENT_CHAT_MEMORY_TYPE],
            ).fetchall()
        return [dict(row) for row in rows]

    def _validate_history_coherence(
        self,
        file_row: dict[str, Any],
    ) -> None:
        ragmem_path = self.memory_root / "files" / str(
            file_row["filename_ragmem"]
        )
        meta_path = self.memory_root / "files" / str(
            file_row["filename_meta"]
        )
        if not ragmem_path.is_file() or not meta_path.is_file():
            raise ValueError("persistent chat memory file pair is incomplete")

        try:
            metainfo = json.loads(meta_path.read_text(encoding="utf-8"))
            ragmem_text = ragmem_path.read_text(encoding="utf-8")
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("persistent chat memory files are invalid") from error
        if not isinstance(metainfo, dict):
            raise ValueError("persistent chat memory metadata is invalid")

        valid_metadata_identity = (
            str(metainfo.get("file_id", "")) == str(file_row["file_id"])
            and str(metainfo.get("owner_sub", "")) == str(file_row["owner_sub"])
            and str(metainfo.get("memory_type", ""))
            == PERSISTENT_CHAT_MEMORY_TYPE
            and str(metainfo.get("filename_ragmem", ""))
            == str(file_row["filename_ragmem"])
            and str(metainfo.get("filename_meta", ""))
            == str(file_row["filename_meta"])
        )
        if not valid_metadata_identity:
            raise ValueError("persistent chat identity does not match")

        records: list[MemoryRecord] = []
        for match in _RECORD_PATTERN.finditer(ragmem_text):
            try:
                data = json.loads(match.group(1))
            except json.JSONDecodeError as error:
                raise ValueError("persistent chat memory body is invalid") from error
            if not isinstance(data, dict):
                raise ValueError("persistent chat memory body is invalid")
            records.append(MemoryRecord.from_dict(data))

        marker_count_is_valid = (
            len(_RECORD_START_LINE_PATTERN.findall(ragmem_text))
            == len(records)
            and len(_RECORD_END_LINE_PATTERN.findall(ragmem_text))
            == len(records)
        )
        if not marker_count_is_valid:
            raise ValueError("persistent chat memory body is incomplete")

        metadata_records = metainfo.get("records", [])
        if not isinstance(metadata_records, list):
            raise ValueError("persistent chat memory metadata is invalid")
        metadata_ids = [
            str(item.get("record_id", ""))
            for item in metadata_records
            if isinstance(item, dict) and str(item.get("record_id", ""))
        ]
        body_ids = [record.record_id for record in records]

        with sqlite3.connect(self.sqlite_path) as connection:
            sqlite_ids = [
                str(row[0])
                for row in connection.execute(
                    """
                    SELECT record_id
                    FROM memory_records
                    WHERE file_id = ?
                    ORDER BY sequence_number, created_at_utc, record_id
                    """,
                    [str(file_row["file_id"])],
                ).fetchall()
            ]

        coherent_ids = (
            len(body_ids) == len(set(body_ids))
            and set(body_ids) == set(metadata_ids) == set(sqlite_ids)
            and len(body_ids) == len(metadata_ids) == len(sqlite_ids)
        )
        coherent_counts = (
            int(file_row["record_count"]) == len(body_ids)
            and int(metainfo.get("record_count", -1)) == len(body_ids)
        )
        if not coherent_ids or not coherent_counts:
            raise ValueError(
                "persistent chat memory body, metadata, and index are not coherent"
            )

    @staticmethod
    def _latest_record(records: list[MemoryRecord]) -> MemoryRecord | None:
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
    def _validate_owner_sub(owner_sub: str) -> str:
        if not isinstance(owner_sub, str):
            raise ValueError("owner_sub is not a safe path component.")
        if (
            owner_sub in {"", ".", ".."}
            or _OWNER_SUB_PATTERN.fullmatch(owner_sub) is None
        ):
            raise ValueError("owner_sub is not a safe path component.")
        return owner_sub

    @staticmethod
    def _require_text(
        value: str,
        field_name: str,
        *,
        trim: bool = False,
    ) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must not be empty.")
        return value.strip() if trim else value