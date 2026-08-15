"""Resolve exact and intelligent MCP Episodic Recall requests.

This module owns read-only Episodic retrieval over SQLite, .ragmem bodies, and
the Episode Description vector index. It does not create, modify, or delete
durable memory; McpMemoryStore remains the persistence authority.

Main classes:
    McpEpisodicRetriever:
        Coordinates deterministic exact fetches and semantic candidate search.

Main methods:
    recall_exact():
        Loads one owner-scoped full episode by Recall Key or Record ID.
    search():
        Applies optional UTC dates and returns cosine-ranked descriptions.

Important notes:
    SQLite selects the allowed owner/date record set before vector ranking.
    Full Q/A text is read only for the final exact episode.
"""

from __future__ import annotations

import json
import re
import sqlite3

from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

from ragstream.memory.mcp_episodic_description_vector_store import (
    McpEpisodicDescriptionVectorStore,
)
from ragstream.memory.memory_record import RECORD_END, RECORD_START


MAX_SEMANTIC_CANDIDATES = 10
EPISODIC_MEMORY_TYPE = "episodic"

_RECORD_PATTERN = re.compile(
    rf"{re.escape(RECORD_START)}\n(.*?)\n{re.escape(RECORD_END)}",
    re.DOTALL,
)


class McpEpisodicRetriever:
    """Own exact and description-ranked reads for MCP Episodic Memory."""

    def __init__(
        self,
        *,
        sqlite_path: str | Path,
        memory_root: str | Path,
        description_vector_store: McpEpisodicDescriptionVectorStore,
    ) -> None:
        self.sqlite_path = Path(sqlite_path)
        self.files_root = Path(memory_root) / "files"
        self._description_vectors = description_vector_store

    def recall_exact(
        self,
        owner_sub: str,
        *,
        recall_key: str | None = None,
        record_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return one full episode selected by one exact identifier."""
        owner = self._require_text(owner_sub, "owner_sub")
        key = (
            self._require_text(recall_key, "recall_key")
            if recall_key is not None
            else None
        )
        identifier = (
            self._require_text(record_id, "record_id")
            if record_id is not None
            else None
        )
        if (key is None) == (identifier is None):
            raise ValueError(
                "exactly one of recall_key or record_id is required."
            )

        row = self._lookup_exact_record(
            owner_sub=owner,
            recall_key=key,
            record_id=identifier,
        )
        if row is None:
            return None

        body = self._load_record_body(
            filename_ragmem=str(row["filename_ragmem"]),
            record_id=str(row["record_id"]),
        )
        return {
            "recall_key": str(row["recall_key"]),
            "record_id": str(row["record_id"]),
            "episode_title": str(row["episode_title"]),
            "episode_description": str(row["episode_description"]),
            "created_at_utc": str(row["created_at_utc"]),
            "input_text": str(body.get("input_text", "")),
            "output_text": str(body.get("output_text", "")),
        }

    def search(
        self,
        owner_sub: str,
        query_description: str,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = MAX_SEMANTIC_CANDIDATES,
    ) -> list[dict[str, Any]]:
        """Return compact Episode Description candidates ranked by cosine."""
        owner = self._require_text(owner_sub, "owner_sub")
        query = self._require_text(
            query_description,
            "query_description",
        )
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit < 1
            or limit > MAX_SEMANTIC_CANDIDATES
        ):
            raise ValueError(
                f"limit must be between 1 and {MAX_SEMANTIC_CANDIDATES}."
            )

        start_utc = self._normalize_date_bound(
            date_from,
            field_name="date_from",
            end_of_day=False,
        )
        end_utc = self._normalize_date_bound(
            date_to,
            field_name="date_to",
            end_of_day=True,
        )
        if start_utc is not None and end_utc is not None:
            if start_utc > end_utc:
                raise ValueError("date_from must not be later than date_to.")

        rows = self._list_semantic_candidates(
            owner_sub=owner,
            date_from_utc=start_utc,
            date_to_utc=end_utc,
        )
        if not rows:
            return []

        rows_by_id = {str(row["record_id"]): row for row in rows}
        vector_hits = self._description_vectors.search_descriptions(
            owner_sub=owner,
            query_description=query,
            candidate_record_ids=list(rows_by_id),
            limit=limit,
        )

        candidates: list[dict[str, Any]] = []
        for hit in vector_hits:
            record_id_value = str(hit.get("record_id", ""))
            row = rows_by_id.get(record_id_value)
            if row is None:
                continue
            candidates.append(
                {
                    "record_id": record_id_value,
                    "recall_key": str(row["recall_key"]),
                    "episode_title": str(row["episode_title"]),
                    "episode_description": str(
                        row["episode_description"]
                    ),
                    "created_at_utc": str(row["created_at_utc"]),
                    "cosine_similarity": hit.get("cosine_similarity"),
                }
            )
        return candidates

    def _lookup_exact_record(
        self,
        *,
        owner_sub: str,
        recall_key: str | None,
        record_id: str | None,
    ) -> sqlite3.Row | None:
        selector = (
            "mr.direct_recall_key = ?"
            if recall_key is not None
            else "mr.record_id = ?"
        )
        selector_value = recall_key if recall_key is not None else record_id

        with sqlite3.connect(self.sqlite_path) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(
                f"""
                SELECT mr.record_id,
                       mr.direct_recall_key AS recall_key,
                       mr.episode_title,
                       mr.episode_description,
                       mr.created_at_utc,
                       mf.filename_ragmem
                FROM memory_records AS mr
                JOIN memory_files AS mf ON mf.file_id = mr.file_id
                WHERE mf.owner_sub = ?
                  AND {selector}
                ORDER BY mr.created_at_utc DESC, mr.record_id DESC
                LIMIT 1
                """,
                [owner_sub, selector_value],
            ).fetchone()

    def _list_semantic_candidates(
        self,
        *,
        owner_sub: str,
        date_from_utc: str | None,
        date_to_utc: str | None,
    ) -> list[sqlite3.Row]:
        query = """
            SELECT mr.record_id,
                   mr.direct_recall_key AS recall_key,
                   mr.episode_title,
                   mr.episode_description,
                   mr.created_at_utc
            FROM memory_records AS mr
            JOIN memory_files AS mf ON mf.file_id = mr.file_id
            WHERE mf.owner_sub = ?
              AND mf.memory_type = ?
              AND mr.episode_description <> ''
        """
        parameters: list[Any] = [owner_sub, EPISODIC_MEMORY_TYPE]
        if date_from_utc is not None:
            query += " AND mr.created_at_utc >= ?"
            parameters.append(date_from_utc)
        if date_to_utc is not None:
            query += " AND mr.created_at_utc <= ?"
            parameters.append(date_to_utc)
        query += " ORDER BY mr.created_at_utc DESC, mr.record_id DESC"

        with sqlite3.connect(self.sqlite_path) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(query, parameters).fetchall()

    def _load_record_body(
        self,
        *,
        filename_ragmem: str,
        record_id: str,
    ) -> dict[str, Any]:
        relative_path = Path(filename_ragmem)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("MCP memory index contains an unsafe filename.")

        ragmem_path = self.files_root / relative_path
        if not ragmem_path.is_file():
            raise ValueError("MCP memory body file was not found.")

        try:
            text = ragmem_path.read_text(encoding="utf-8")
        except OSError as error:
            raise ValueError("MCP memory body file cannot be read.") from error

        for match in _RECORD_PATTERN.finditer(text):
            try:
                data = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            if (
                isinstance(data, dict)
                and str(data.get("record_id", "")) == record_id
            ):
                return data

        raise ValueError("MCP memory body and index do not match.")

    @staticmethod
    def _normalize_date_bound(
        value: str | None,
        *,
        field_name: str,
        end_of_day: bool,
    ) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty ISO date.")

        text = value.strip()
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                parsed_date = date.fromisoformat(text)
                boundary_time = time(23, 59, 59) if end_of_day else time.min
                parsed = datetime.combine(
                    parsed_date,
                    boundary_time,
                    tzinfo=timezone.utc,
                )
            else:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                parsed = parsed.astimezone(timezone.utc)
        except ValueError as error:
            raise ValueError(
                f"{field_name} must be an ISO date or datetime."
            ) from error

        return (
            parsed.replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    @staticmethod
    def _require_text(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must not be empty.")
        return value.strip()