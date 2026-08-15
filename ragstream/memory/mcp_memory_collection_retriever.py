"""List and deterministically recall MCP Collection Memory episodes.

The module owns read-only Collection navigation: owner-scoped Collection
listing, episode metadata listing, numbered selection, and token-safe payload
construction. Collection writes and deletion remain in the companion store.

Main classes:
    CollectionRecallSelection:
        Represents one validated numbered Collection selection request.
    McpMemoryCollectionRetriever:
        Resolves Collections and returns metadata or full numbered episodes.

Main methods:
    list_collections():
        Lists the authenticated owner's Collection containers.
    list_episodes():
        Lists one Collection's episode metadata and permanent number gaps.
    recall_episodes():
        Returns a token-safe deterministic prefix of a numbered selection.
"""

from __future__ import annotations

import json
import re
import sqlite3

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ragstream.memory.mcp_memory_collection_store import (
    COLLECTION_MEMORY_TYPE,
    DEFAULT_MEMORY_ROOT,
    ensure_collection_schema,
)
from ragstream.memory.memory_manager import MemoryManager
from ragstream.memory.memory_record import MemoryRecord


DEFAULT_COLLECTION_RECALL_TOKEN_LIMIT = 12_000
MAX_REQUESTED_EPISODE_NUMBERS = 1_000

SELECTION_EPISODE_NUMBER = "episode_number"
SELECTION_EPISODE_NUMBERS = "episode_numbers"
SELECTION_RANGE = "range"
SELECTION_FIRST = "first"
SELECTION_LAST = "last"
SELECTION_ALL = "all"

_SELECTION_MODES = {
    SELECTION_EPISODE_NUMBER,
    SELECTION_EPISODE_NUMBERS,
    SELECTION_RANGE,
    SELECTION_FIRST,
    SELECTION_LAST,
    SELECTION_ALL,
}
_OWNER_SUB_PATTERN = re.compile(r"[A-Za-z0-9._-]+")


@dataclass(frozen=True)
class CollectionRecallSelection:
    """Describe one exact numbered selection inside a Collection."""

    mode: str
    episode_number: int | None = None
    episode_numbers: tuple[int, ...] = ()
    range_start: int | None = None
    range_end: int | None = None
    count: int | None = None


class McpMemoryCollectionRetriever:
    """Own deterministic Collection listing and token-safe episode reads."""

    def __init__(
        self,
        memory_root: str | Path = DEFAULT_MEMORY_ROOT,
        sqlite_path: str | Path | None = None,
        *,
        max_recall_tokens: int = (
            DEFAULT_COLLECTION_RECALL_TOKEN_LIMIT
        ),
    ) -> None:
        if (
            not isinstance(max_recall_tokens, int)
            or isinstance(max_recall_tokens, bool)
            or max_recall_tokens < 1
        ):
            raise ValueError(
                "max_recall_tokens must be a positive integer"
            )

        self.memory_root = Path(memory_root)
        self.sqlite_path = (
            Path(sqlite_path)
            if sqlite_path is not None
            else self.memory_root / "memory_index.sqlite3"
        )
        self.max_recall_tokens = max_recall_tokens
        self._encoding = self._load_token_encoding()

        # Establish common tables before adding the Collection extension.
        self._new_memory_manager()
        ensure_collection_schema(self.sqlite_path)

    def list_collections(
        self,
        owner_sub: str,
    ) -> list[dict[str, Any]]:
        """Return deterministic Collection identities and current counts."""
        owner = self._validate_owner_sub(owner_sub)

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
                       next_sequence_number
                FROM memory_files
                WHERE owner_sub = ?
                  AND memory_type = ?
                ORDER BY created_at_utc, file_id
                """,
                [owner, COLLECTION_MEMORY_TYPE],
            ).fetchall()

        return [
            {
                **dict(row),
                "highest_assigned_episode_number": (
                    int(row["next_sequence_number"]) - 1
                ),
            }
            for row in rows
        ]

    def list_episodes(
        self,
        owner_sub: str,
        *,
        collection_id: str | None = None,
        collection_name: str | None = None,
    ) -> dict[str, Any]:
        """List one Collection's metadata without returning complete Q/A."""
        owner = self._validate_owner_sub(owner_sub)
        collection = self._resolve_collection(
            owner,
            collection_id=collection_id,
            collection_name=collection_name,
        )
        rows = self._episode_metadata_rows(
            str(collection["file_id"])
        )
        available_numbers = {
            int(row["episode_number"])
            for row in rows
        }
        highest_assigned = (
            int(collection["next_sequence_number"]) - 1
        )
        unavailable_numbers = [
            number
            for number in range(1, highest_assigned + 1)
            if number not in available_numbers
        ]

        return {
            "collection_id": str(collection["file_id"]),
            "collection_name": str(collection["title"]),
            "collection_description": str(
                collection["memory_description"]
            ),
            "created_at_utc": str(
                collection["created_at_utc"]
            ),
            "record_count": int(collection["record_count"]),
            "highest_assigned_episode_number": highest_assigned,
            "next_sequence_number": int(
                collection["next_sequence_number"]
            ),
            "episodes": [
                dict(row)
                for row in rows
            ],
            "unavailable_episode_numbers": unavailable_numbers,
        }

    def recall_episodes(
        self,
        owner_sub: str,
        selection: CollectionRecallSelection,
        *,
        collection_id: str | None = None,
        collection_name: str | None = None,
    ) -> dict[str, Any]:
        """Return available full episodes until the token limit is reached."""
        owner = self._validate_owner_sub(owner_sub)

        if not isinstance(selection, CollectionRecallSelection):
            raise ValueError(
                "selection must be a CollectionRecallSelection"
            )

        collection = self._resolve_collection(
            owner,
            collection_id=collection_id,
            collection_name=collection_name,
        )
        manager = self._load_collection_manager(collection)
        records_by_number = {
            record.sequence_number: record
            for record in manager.records
        }
        requested_numbers = self._resolve_requested_numbers(
            selection,
            records_by_number,
            int(collection["next_sequence_number"]),
        )

        episodes: list[dict[str, Any]] = []
        returned_numbers: list[int] = []
        unavailable_numbers: list[int] = []
        omitted_numbers: list[int] = []
        estimated_tokens = 0

        for position, episode_number in enumerate(requested_numbers):
            record = records_by_number.get(episode_number)
            if record is None:
                unavailable_numbers.append(episode_number)
                continue

            payload = self._episode_payload(record)
            payload_tokens = self._count_tokens(payload)

            if (
                estimated_tokens + payload_tokens
                > self.max_recall_tokens
            ):
                omitted_numbers = requested_numbers[position:]
                break

            episodes.append(payload)
            returned_numbers.append(episode_number)
            estimated_tokens += payload_tokens

        return {
            "collection_id": str(collection["file_id"]),
            "collection_name": str(collection["title"]),
            "collection_description": str(
                collection["memory_description"]
            ),
            "selection_mode": selection.mode,
            "requested_episode_numbers": requested_numbers,
            "returned_episode_numbers": returned_numbers,
            "unavailable_episode_numbers": unavailable_numbers,
            "omitted_episode_numbers": omitted_numbers,
            "episodes": episodes,
            "truncated": bool(omitted_numbers),
            "token_limit": self.max_recall_tokens,
            "estimated_tokens": estimated_tokens,
        }

    def _resolve_collection(
        self,
        owner_sub: str,
        *,
        collection_id: str | None,
        collection_name: str | None,
    ) -> dict[str, Any]:
        clean_id = self._optional_text(
            collection_id,
            "collection_id",
        )
        clean_name = self._optional_text(
            collection_name,
            "collection_name",
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
                SELECT file_id, title, memory_description,
                       filename_ragmem, filename_meta,
                       created_at_utc, updated_at_utc,
                       record_count, owner_sub,
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
            raise ValueError(
                "Collection could not be resolved safely"
            )

        return dict(rows[0])

    def _load_collection_manager(
        self,
        collection: dict[str, Any],
    ) -> MemoryManager:
        manager = self._new_memory_manager()
        manager.load_history(str(collection["file_id"]))

        valid_identity = (
            manager.owner_sub == str(collection["owner_sub"])
            and manager.memory_type == COLLECTION_MEMORY_TYPE
        )
        if not valid_identity:
            raise ValueError(
                "Collection identity does not match"
            )

        highest_sequence = max(
            (
                record.sequence_number
                for record in manager.records
            ),
            default=0,
        )
        sqlite_next = int(collection["next_sequence_number"])

        try:
            meta_next = int(
                manager.metainfo["next_sequence_number"]
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                "Collection next_sequence_number metadata is invalid"
            ) from error

        if (
            sqlite_next < 1
            or sqlite_next != meta_next
            or sqlite_next <= highest_sequence
        ):
            raise ValueError(
                "Collection sequence counter is not coherent"
            )

        return manager

    def _episode_metadata_rows(
        self,
        collection_id: str,
    ) -> list[sqlite3.Row]:
        with sqlite3.connect(self.sqlite_path) as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute(
                """
                SELECT sequence_number AS episode_number,
                       record_id,
                       direct_recall_key AS recall_key,
                       episode_title,
                       episode_description,
                       created_at_utc
                FROM memory_records
                WHERE file_id = ?
                ORDER BY sequence_number,
                         created_at_utc,
                         record_id
                """,
                [collection_id],
            ).fetchall()

    def _resolve_requested_numbers(
        self,
        selection: CollectionRecallSelection,
        records_by_number: dict[int, MemoryRecord],
        next_sequence_number: int,
    ) -> list[int]:
        mode = str(selection.mode or "").strip()
        if mode not in _SELECTION_MODES:
            raise ValueError(
                "unsupported Collection selection mode"
            )

        available_numbers = sorted(records_by_number)
        highest_assigned = max(
            0,
            next_sequence_number - 1,
        )

        if mode == SELECTION_EPISODE_NUMBER:
            numbers = [
                self._positive_int(
                    selection.episode_number,
                    "episode_number",
                )
            ]

        elif mode == SELECTION_EPISODE_NUMBERS:
            if not selection.episode_numbers:
                raise ValueError(
                    "episode_numbers must not be empty"
                )
            numbers = self._unique_positive_numbers(
                selection.episode_numbers
            )

        elif mode == SELECTION_RANGE:
            start = self._positive_int(
                selection.range_start,
                "range_start",
            )
            end = self._positive_int(
                selection.range_end,
                "range_end",
            )
            if start > end:
                raise ValueError(
                    "range_start must not exceed range_end"
                )
            if (
                end - start + 1
                > MAX_REQUESTED_EPISODE_NUMBERS
            ):
                raise ValueError(
                    "requested Collection range is too large"
                )
            numbers = list(range(start, end + 1))

        elif mode == SELECTION_FIRST:
            count = self._positive_int(
                selection.count,
                "count",
            )
            self._validate_selection_size(count)
            numbers = available_numbers[:count]

        elif mode == SELECTION_LAST:
            count = self._positive_int(
                selection.count,
                "count",
            )
            self._validate_selection_size(count)
            numbers = available_numbers[-count:]

        else:
            if (
                highest_assigned
                > MAX_REQUESTED_EPISODE_NUMBERS
            ):
                raise ValueError(
                    "Collection is too large for one "
                    "all-episode request"
                )
            numbers = list(
                range(1, highest_assigned + 1)
            )

        self._validate_unused_selection_fields(
            selection,
            mode,
        )
        return numbers

    @staticmethod
    def _validate_unused_selection_fields(
        selection: CollectionRecallSelection,
        mode: str,
    ) -> None:
        populated = {
            "episode_number": (
                selection.episode_number is not None
            ),
            "episode_numbers": bool(
                selection.episode_numbers
            ),
            "range_start": (
                selection.range_start is not None
            ),
            "range_end": (
                selection.range_end is not None
            ),
            "count": selection.count is not None,
        }
        allowed = {
            SELECTION_EPISODE_NUMBER: {
                "episode_number",
            },
            SELECTION_EPISODE_NUMBERS: {
                "episode_numbers",
            },
            SELECTION_RANGE: {
                "range_start",
                "range_end",
            },
            SELECTION_FIRST: {
                "count",
            },
            SELECTION_LAST: {
                "count",
            },
            SELECTION_ALL: set(),
        }[mode]

        unsupported = {
            field_name
            for field_name, is_populated in populated.items()
            if is_populated and field_name not in allowed
        }
        if unsupported:
            raise ValueError(
                "selection contains fields that do not "
                "belong to its mode"
            )

    @staticmethod
    def _episode_payload(
        record: MemoryRecord,
    ) -> dict[str, Any]:
        return {
            "episode_number": record.sequence_number,
            "record_id": record.record_id,
            "recall_key": record.direct_recall_key,
            "episode_title": record.episode_title,
            "episode_description": record.episode_description,
            "created_at_utc": record.created_at_utc,
            "input_text": record.input_text,
            "output_text": record.output_text,
            "active_retrieval_brief_title": (
                record.active_retrieval_brief_title
            ),
            "active_retrieval_brief": (
                record.active_retrieval_brief
            ),
            "active_retrieval_brief_contributor_ids": list(
                record.active_retrieval_brief_contributor_ids
            ),
        }

    def _count_tokens(
        self,
        payload: dict[str, Any],
    ) -> int:
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )

        if self._encoding is None:
            # Deterministic conservative fallback when tiktoken is absent.
            return max(
                1,
                (len(serialized) + 3) // 4,
            )

        return len(
            self._encoding.encode(serialized)
        )

    @staticmethod
    def _load_token_encoding() -> Any | None:
        try:
            import tiktoken

            return tiktoken.get_encoding("cl100k_base")
        except Exception:
            return None

    def _new_memory_manager(self) -> MemoryManager:
        return MemoryManager(
            memory_root=self.memory_root,
            sqlite_path=self.sqlite_path,
        )

    @staticmethod
    def _unique_positive_numbers(
        values: tuple[int, ...],
    ) -> list[int]:
        if len(values) > MAX_REQUESTED_EPISODE_NUMBERS:
            raise ValueError(
                "too many episode numbers were requested"
            )

        numbers: list[int] = []
        seen: set[int] = set()

        for value in values:
            number = (
                McpMemoryCollectionRetriever._positive_int(
                    value,
                    "episode_numbers",
                )
            )
            if number not in seen:
                numbers.append(number)
                seen.add(number)

        return numbers

    @staticmethod
    def _validate_selection_size(size: int) -> None:
        if size > MAX_REQUESTED_EPISODE_NUMBERS:
            raise ValueError(
                "too many Collection episodes were requested"
            )

    @staticmethod
    def _positive_int(
        value: int | None,
        field_name: str,
    ) -> int:
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 1
        ):
            raise ValueError(
                f"{field_name} must be a positive integer"
            )

        return value

    @staticmethod
    def _optional_text(
        value: str | None,
        field_name: str,
    ) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"{field_name} must be a non-empty string"
            )

        return value.strip()

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