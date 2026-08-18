"""Persist short-lived owner-scoped MCP Clipboard Memory.

Clipboard Memory is a deterministic temporary slot mechanism. Slots M1 through
M100 are append-only: saving another value to an occupied slot creates a new
episode, while recall returns only the newest exact match. Clipboard histories
use one shared GHOST ``.ragmem``/``.ragmeta.json`` pair per owner and UTC day.

This module deliberately contains no semantic retrieval, Episode Description,
ActiveBrief, list, or manual-delete behavior. It exposes only save, exact latest
recall, and physical expiration cleanup. The MCP interface and asynchronous
startup scheduling are added in Part 2.

Main classes:
    McpClipboardStore:
        Owns Clipboard append, newest-slot recall, and expired-file cleanup.
    ClipboardPartialWriteError:
        Reports a durable append followed by an index/metadata failure.

Main functions:
    is_clipboard_slot():
        Identifies reserved M1-M100 slot names without accepting lookalikes.
    normalize_clipboard_slot():
        Validates and canonicalizes a slot to uppercase form.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ragstream.memory.memory_manager import MemoryManager
from ragstream.memory.memory_record import MemoryRecord
from ragstream.memory.storage.memory_file_manager import MemoryFileManager


CLIPBOARD_MEMORY_TYPE = "clipboard"
CLIPBOARD_SOURCE = "mcp_clipboard"
CLIPBOARD_RETENTION_DAYS = 10
DEFAULT_MEMORY_ROOT = Path("data/mcp/memory")

_OWNER_SUB_PATTERN = re.compile(r"[A-Za-z0-9._-]+")
_CLIPBOARD_SLOT_PATTERN = re.compile(
    r"M(?:[1-9]|[1-9][0-9]|100)",
    re.IGNORECASE,
)


def is_clipboard_slot(value: object) -> bool:
    """Return whether value is one exact reserved Clipboard slot name."""
    return (
        isinstance(value, str)
        and _CLIPBOARD_SLOT_PATTERN.fullmatch(value.strip()) is not None
    )


def normalize_clipboard_slot(value: str) -> str:
    """Validate M1-M100 and return its canonical uppercase representation."""
    if not is_clipboard_slot(value):
        raise ValueError("clipboard_slot must be one of M1 through M100.")
    return value.strip().upper()


class ClipboardPartialWriteError(RuntimeError):
    """Indicate that durable Clipboard content changed before later failure."""

    def __init__(self, record_id: str) -> None:
        super().__init__(
            "Clipboard append changed durable data before metadata/index "
            "synchronization failed"
        )
        self.record_id = record_id


class McpClipboardStore:
    """Own append-only Clipboard storage and exact newest-slot retrieval."""

    def __init__(
        self,
        memory_root: str | Path = DEFAULT_MEMORY_ROOT,
        sqlite_path: str | Path | None = None,
        *,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.memory_root = Path(memory_root)
        self.sqlite_path = (
            Path(sqlite_path)
            if sqlite_path is not None
            else self.memory_root / "memory_index.sqlite3"
        )
        self._now_provider = now_provider or (
            lambda: datetime.now(timezone.utc)
        )
        self._lock = threading.Lock()

        # MemoryManager establishes and migrates the common GHOST SQLite schema.
        self._new_memory_manager()

    def save(
        self,
        owner_sub: str,
        clipboard_slot: str,
        input_text: str,
        output_text: str,
    ) -> dict[str, Any]:
        """Append one visible Q/A pair to an exact Clipboard slot."""
        owner = self._validate_owner_sub(owner_sub)
        slot = normalize_clipboard_slot(clipboard_slot)
        exact_input = self._require_visible_text(input_text, "input_text")
        exact_output = self._require_visible_text(output_text, "output_text")
        now = self._utc_now()
        utc_date = now.date().isoformat()

        with self._lock:
            manager = self._load_or_create_daily_history(
                owner_sub=owner,
                utc_date=utc_date,
                now=now,
            )
            sequence_number = max(
                len(manager.records),
                max(
                    (
                        record.sequence_number
                        for record in manager.records
                    ),
                    default=0,
                ),
            ) + 1

            record = MemoryRecord(
                input_text=exact_input,
                output_text=exact_output,
                source=CLIPBOARD_SOURCE,
                parent_id=None,
                tag="Green",
                user_keywords=[],
                active_project_name=None,
                embedded_files_snapshot=[],
                retrieval_source_mode="QA",
                direct_recall_key=slot,
                episode_title="",
                active_retrieval_brief_title="",
                active_retrieval_brief="",
                active_retrieval_brief_contributor_ids=[],
                sequence_number=sequence_number,
                actor_id="",
                chat_stream_id=manager.file_id,
                episode_description="",
                expires_at_utc=manager.expires_at_utc,
                created_at_utc=self._format_utc(now),
            )

            with manager.ragmem_path.open("a", encoding="utf-8") as file:
                file.write(record.to_ragmem_block())
                file.write("\n")

            manager.records.append(record)
            try:
                manager.save_metainfo()
                manager.refresh_sqlite_index()
            except Exception as error:
                raise ClipboardPartialWriteError(
                    record.record_id
                ) from error

        return {
            "saved": True,
            "memory_type": CLIPBOARD_MEMORY_TYPE,
            "clipboard_slot": slot,
            "recall_key": slot,
            "record_id": record.record_id,
            "sequence_number": record.sequence_number,
            "file_id": manager.file_id,
            "created_at_utc": record.created_at_utc,
            "expires_at_utc": manager.expires_at_utc,
        }

    def recall_latest(
        self,
        owner_sub: str,
        clipboard_slot: str,
    ) -> dict[str, Any] | None:
        """Return the newest non-expired exact match for one Clipboard slot."""
        owner = self._validate_owner_sub(owner_sub)
        slot = normalize_clipboard_slot(clipboard_slot)
        now_utc = self._format_utc(self._utc_now())

        with self._lock:
            row = self._lookup_latest_record(
                owner_sub=owner,
                clipboard_slot=slot,
                now_utc=now_utc,
            )
            if row is None:
                return None

            manager = self._new_memory_manager()
            manager.load_history(str(row["file_id"]))
            valid_history = (
                manager.owner_sub == owner
                and manager.memory_type == CLIPBOARD_MEMORY_TYPE
            )
            if not valid_history:
                raise ValueError(
                    "Clipboard history identity does not match."
                )

            record_id = str(row["record_id"])
            record = next(
                (
                    item
                    for item in manager.records
                    if item.record_id == record_id
                ),
                None,
            )
            if record is None:
                raise ValueError(
                    "Clipboard body, metadata, and index do not match."
                )
            if normalize_clipboard_slot(record.direct_recall_key) != slot:
                raise ValueError(
                    "Clipboard slot identity does not match."
                )

        return {
            "memory_type": CLIPBOARD_MEMORY_TYPE,
            "clipboard_slot": slot,
            "recall_key": slot,
            "record_id": record.record_id,
            "sequence_number": record.sequence_number,
            "file_id": manager.file_id,
            "created_at_utc": record.created_at_utc,
            "expires_at_utc": manager.expires_at_utc,
            "input_text": record.input_text,
            "output_text": record.output_text,
        }

    def cleanup_expired(self) -> dict[str, Any]:
        """Physically delete all expired Clipboard histories and index rows."""
        now_utc = self._format_utc(self._utc_now())

        with self._lock:
            expired_rows = self._expired_history_rows(now_utc)
            deleted_file_ids: list[str] = []
            failed_file_ids: list[str] = []
            deleted_record_count = 0

            for row in expired_rows:
                file_id = str(row["file_id"])
                try:
                    manager = self._new_memory_manager()
                    MemoryFileManager(manager).delete_history(file_id)
                except Exception:
                    failed_file_ids.append(file_id)
                    continue

                deleted_file_ids.append(file_id)
                deleted_record_count += int(row["record_count"])

        return {
            "memory_type": CLIPBOARD_MEMORY_TYPE,
            "checked_at_utc": now_utc,
            "expired_file_count": len(expired_rows),
            "deleted_file_count": len(deleted_file_ids),
            "deleted_record_count": deleted_record_count,
            "deleted_file_ids": deleted_file_ids,
            "failed_file_ids": failed_file_ids,
        }

    def _load_or_create_daily_history(
        self,
        *,
        owner_sub: str,
        utc_date: str,
        now: datetime,
    ) -> MemoryManager:
        title = self._daily_title(utc_date)
        rows = self._daily_history_rows(owner_sub, title)
        if len(rows) > 1:
            raise ValueError(
                "More than one Clipboard history exists for the UTC day."
            )

        if rows:
            manager = self._new_memory_manager()
            manager.load_history(str(rows[0]["file_id"]))
            valid_history = (
                manager.owner_sub == owner_sub
                and manager.memory_type == CLIPBOARD_MEMORY_TYPE
                and manager.title == title
            )
            if not valid_history:
                raise ValueError(
                    "Clipboard daily history identity does not match."
                )

            if manager.expires_at_utc is None:
                manager.expires_at_utc = self._format_utc(
                    now + timedelta(days=CLIPBOARD_RETENTION_DAYS)
                )
                for record in manager.records:
                    record.expires_at_utc = manager.expires_at_utc

                manager.save_metainfo()
                manager.refresh_sqlite_index()

            return manager

        manager = self._new_memory_manager()
        expires_at_utc = self._format_utc(
            now + timedelta(days=CLIPBOARD_RETENTION_DAYS)
        )
        MemoryFileManager(manager).create_history(
            title,
            memory_type=CLIPBOARD_MEMORY_TYPE,
            memory_description="",
            actors=[],
            owner_sub=owner_sub,
            expires_at_utc=expires_at_utc,
            storage_folder=f"{owner_sub}/clipboard",
        )
        return manager

    def _daily_history_rows(
        self,
        owner_sub: str,
        title: str,
    ) -> list[sqlite3.Row]:
        with sqlite3.connect(self.sqlite_path) as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute(
                """
                SELECT file_id, title, owner_sub, memory_type,
                       expires_at_utc
                FROM memory_files
                WHERE owner_sub = ?
                  AND memory_type = ?
                  AND title = ?
                ORDER BY file_id
                """,
                [owner_sub, CLIPBOARD_MEMORY_TYPE, title],
            ).fetchall()

    def _lookup_latest_record(
        self,
        *,
        owner_sub: str,
        clipboard_slot: str,
        now_utc: str,
    ) -> sqlite3.Row | None:
        with sqlite3.connect(self.sqlite_path) as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute(
                """
                SELECT mf.file_id,
                       mr.record_id,
                       mr.sequence_number,
                       mr.created_at_utc
                FROM memory_records AS mr
                JOIN memory_files AS mf ON mf.file_id = mr.file_id
                WHERE mf.owner_sub = ?
                  AND mf.memory_type = ?
                  AND mr.direct_recall_key = ?
                  AND mf.expires_at_utc IS NOT NULL
                  AND mf.expires_at_utc > ?
                ORDER BY mr.created_at_utc DESC,
                         mr.sequence_number DESC,
                         mr.record_id DESC
                LIMIT 1
                """,
                [
                    owner_sub,
                    CLIPBOARD_MEMORY_TYPE,
                    clipboard_slot,
                    now_utc,
                ],
            ).fetchone()

    def _expired_history_rows(
        self,
        now_utc: str,
    ) -> list[sqlite3.Row]:
        with sqlite3.connect(self.sqlite_path) as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute(
                """
                SELECT file_id, record_count
                FROM memory_files
                WHERE memory_type = ?
                  AND expires_at_utc IS NOT NULL
                  AND expires_at_utc <= ?
                ORDER BY expires_at_utc, file_id
                """,
                [CLIPBOARD_MEMORY_TYPE, now_utc],
            ).fetchall()

    def _new_memory_manager(self) -> MemoryManager:
        return MemoryManager(
            memory_root=self.memory_root,
            sqlite_path=self.sqlite_path,
        )

    def _utc_now(self) -> datetime:
        value = self._now_provider()
        if not isinstance(value, datetime):
            raise ValueError(
                "now_provider must return a datetime."
            )
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)

        return (
            value.astimezone(timezone.utc)
            .replace(microsecond=0)
        )

    @staticmethod
    def _format_utc(value: datetime) -> str:
        return (
            value.astimezone(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    @staticmethod
    def _daily_title(utc_date: str) -> str:
        return f"MCP_CLIPBOARD_{utc_date}"

    @staticmethod
    def _validate_owner_sub(owner_sub: str) -> str:
        if not isinstance(owner_sub, str) or not owner_sub.strip():
            raise ValueError(
                "owner_sub must not be empty."
            )

        owner = owner_sub.strip()
        if _OWNER_SUB_PATTERN.fullmatch(owner) is None:
            raise ValueError(
                "owner_sub contains unsupported characters."
            )
        return owner

    @staticmethod
    def _require_visible_text(
        value: str,
        field_name: str,
    ) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"{field_name} must not be empty."
            )
        return value