"""Persist and retrieve owner-scoped MCP Episodic Memory.

This module owns the durable MCP memory workflow: unique Recall Keys, daily
.ragmem/.ragmeta.json histories, the shared SQLite mirror, listing, and episode
deletion. Description indexing and read-only retrieval are delegated to focused
backend modules.

Main classes:
    McpMemoryStore:
        Coordinates durable Episodic Memory and its derivative vector index.
    EpisodicMemoryPartialSaveError:
        Reports a rare save failure after durable data could not be rolled back.

Main methods:
    save_episodic_memory():
        Saves one visible Q/A with Title, Description, and a unique Recall Key.
    recall_memory():
        Fetches one full episode by exact Recall Key or exact Record ID.
    search_episodic_memories():
        Returns up to ten description-ranked candidates after optional dates.
    list_memories():
        Lists the authenticated owner's episodes from newest to oldest.
    delete_memory():
        Deletes one selected episode or all exact-key matches for one owner.

Important notes:
    MemoryRecord owns episode serialization. SQLite remains a metadata mirror;
    the Chroma description index is derivative and never replaces durable truth.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ragstream.memory.mcp_episodic_description_vector_store import (
    McpEpisodicDescriptionVectorStore,
)
from ragstream.memory.mcp_episodic_retriever import (
    EPISODIC_MEMORY_TYPE,
    MAX_SEMANTIC_CANDIDATES,
    McpEpisodicRetriever,
)
from ragstream.memory.memory_record import MemoryRecord, RECORD_END, RECORD_START
from ragstream.textforge.RagLog import LogNoGUI


DEFAULT_MEMORY_ROOT = Path("data/mcp/memory")
MAX_EPISODE_TITLE_LENGTH = 120

_OWNER_SUB_PATTERN = re.compile(r"[A-Za-z0-9._-]+")
_CLIPBOARD_KEY_PATTERN = re.compile(
    r"M(?:[1-9]|[1-9][0-9]|100)",
    re.IGNORECASE,
)
_RECORD_PATTERN = re.compile(
    rf"{re.escape(RECORD_START)}\n(.*?)\n{re.escape(RECORD_END)}",
    re.DOTALL,
)


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        item = str(value).strip()
        if not item or item.lower() in seen:
            continue
        result.append(item)
        seen.add(item.lower())

    return result


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    return text if text else None


def _list_or_empty(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


class EpisodicMemoryPartialSaveError(RuntimeError):
    """Indicate that a failed semantic save may still have durable data."""

    def __init__(self, record_id: str, recall_key: str) -> None:
        super().__init__(
            "episodic memory indexing failed and durable rollback was incomplete"
        )
        self.record_id = record_id
        self.recall_key = recall_key


class McpMemoryStore:
    """Coordinate durable MCP Episodic Memory and description retrieval."""

    def __init__(
        self,
        memory_root: str | Path = DEFAULT_MEMORY_ROOT,
        sqlite_path: str | Path | None = None,
        description_vector_store: (
            McpEpisodicDescriptionVectorStore | None
        ) = None,
    ) -> None:
        self.memory_root = Path(memory_root)
        self.files_root = self.memory_root / "files"
        self.vector_root = self.memory_root / "vector_db"
        self.sqlite_path = (
            Path(sqlite_path)
            if sqlite_path is not None
            else self.memory_root / "memory_index.sqlite3"
        )
        self._lock = threading.Lock()

        self.files_root.mkdir(parents=True, exist_ok=True)
        self.vector_root.mkdir(parents=True, exist_ok=True)
        self._init_sqlite()
        self._description_vectors = (
            description_vector_store
            if description_vector_store is not None
            else McpEpisodicDescriptionVectorStore(self.vector_root)
        )
        self._episodic_retriever = McpEpisodicRetriever(
            sqlite_path=self.sqlite_path,
            memory_root=self.memory_root,
            description_vector_store=self._description_vectors,
        )

    def save_episodic_memory(
        self,
        owner_sub: str,
        recall_key: str,
        episode_title: str,
        episode_description: str,
        input_text: str,
        output_text: str,
    ) -> MemoryRecord:
        """Save one Episodic episode and index its Description for recall."""
        owner = self._validate_owner_sub(owner_sub)
        base_key = self._require_text(recall_key, "recall_key", trim=True)
        if _CLIPBOARD_KEY_PATTERN.fullmatch(base_key) is not None:
            raise ValueError(
                "recall_key M1 through M100 is reserved for Clipboard Memory."
            )

        title = self._require_text(episode_title, "episode_title", trim=True)
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

        with self._lock:
            effective_key = self._allocate_unique_recall_key(owner, base_key)
            record = MemoryRecord(
                input_text=exact_input,
                output_text=exact_output,
                source="mcp",
                parent_id=None,
                tag="Green",
                user_keywords=[],
                active_project_name=None,
                embedded_files_snapshot=[],
                retrieval_source_mode="QA",
                direct_recall_key=effective_key,
                episode_title=title,
                episode_description=description,
                active_retrieval_brief_title="",
                active_retrieval_brief="",
                active_retrieval_brief_contributor_ids=[],
            )

            utc_date = record.created_at_utc[:10]
            ragmem_path, meta_path, filename_ragmem, filename_meta = (
                self._resolve_daily_history(owner, utc_date)
            )
            file_id, records, existing_metainfo = self._load_daily_history(
                owner,
                ragmem_path,
                meta_path,
            )
            record.sequence_number = max(
                len(records),
                max((item.sequence_number for item in records), default=0),
            ) + 1
            records.append(record)

            with ragmem_path.open("a", encoding="utf-8") as file:
                file.write(record.to_ragmem_block())
                file.write("\n")

            metainfo = self._build_metainfo(
                owner_sub=owner,
                file_id=file_id,
                title=f"MCP_MEM_{utc_date}",
                filename_ragmem=filename_ragmem,
                filename_meta=filename_meta,
                records=records,
                existing_metainfo=existing_metainfo,
            )
            with meta_path.open("w", encoding="utf-8") as file:
                json.dump(metainfo, file, ensure_ascii=False, indent=2)

            self._refresh_sqlite_index(metainfo, records)
            try:
                self._description_vectors.upsert_description(
                    owner_sub=owner,
                    file_id=file_id,
                    record_id=record.record_id,
                    episode_description=record.episode_description,
                    created_at_utc=record.created_at_utc,
                )
            except Exception as error:
                self._rollback_failed_vector_save(
                    owner_sub=owner,
                    file_id=file_id,
                    utc_date=utc_date,
                    record=record,
                    original_error=error,
                )
            return record

    def recall_memory(
        self,
        owner_sub: str,
        *,
        recall_key: str | None = None,
        record_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return one full episode selected by exactly one exact identifier."""
        owner = self._validate_owner_sub(owner_sub)
        with self._lock:
            return self._episodic_retriever.recall_exact(
                owner,
                recall_key=recall_key,
                record_id=record_id,
            )

    def search_episodic_memories(
        self,
        owner_sub: str,
        query_description: str,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = MAX_SEMANTIC_CANDIDATES,
    ) -> list[dict[str, Any]]:
        """Return compact Episode Description candidates ranked by cosine."""
        owner = self._validate_owner_sub(owner_sub)
        with self._lock:
            return self._episodic_retriever.search(
                owner,
                query_description,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
            )

    def list_memories(
        self,
        owner_sub: str,
    ) -> list[dict[str, str]]:
        """List one owner's episodes in deterministic newest-first order."""
        owner = self._validate_owner_sub(owner_sub)

        with self._lock, sqlite3.connect(self.sqlite_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT mr.direct_recall_key AS recall_key,
                       mr.episode_title,
                       mr.record_id,
                       mr.created_at_utc
                FROM memory_records AS mr
                JOIN memory_files AS mf ON mf.file_id = mr.file_id
                WHERE mf.owner_sub = ?
                  AND mr.direct_recall_key <> ''
                ORDER BY mr.created_at_utc DESC, mr.record_id DESC
                """,
                [owner],
            ).fetchall()

        return [dict(row) for row in rows]

    def delete_memory(
        self,
        owner_sub: str,
        *,
        recall_key: str | None = None,
        record_id: str | None = None,
        delete_all_matches: bool = False,
    ) -> dict[str, Any]:
        """Delete an episode while keeping files and SQLite synchronized."""
        owner = self._validate_owner_sub(owner_sub)
        key = (
            self._require_text(recall_key, "recall_key", trim=True)
            if recall_key is not None
            else None
        )
        identifier = (
            self._require_text(record_id, "record_id", trim=True)
            if record_id is not None
            else None
        )
        if (key is None) == (identifier is None):
            raise ValueError(
                "exactly one of recall_key or record_id is required."
            )
        if not isinstance(delete_all_matches, bool):
            raise ValueError("delete_all_matches must be a boolean.")
        if identifier is not None and delete_all_matches:
            raise ValueError(
                "delete_all_matches is allowed only with recall_key."
            )

        with self._lock:
            selector = (
                "mr.direct_recall_key = ?"
                if key is not None
                else "mr.record_id = ?"
            )
            selector_value = key if key is not None else identifier

            with sqlite3.connect(self.sqlite_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    f"""
                    SELECT mr.file_id,
                           mr.record_id,
                           mr.direct_recall_key AS recall_key,
                           mr.created_at_utc
                    FROM memory_records AS mr
                    JOIN memory_files AS mf ON mf.file_id = mr.file_id
                    WHERE mf.owner_sub = ?
                      AND {selector}
                    ORDER BY mr.created_at_utc DESC, mr.record_id DESC
                    """,
                    [owner, selector_value],
                ).fetchall()

            matches = [
                {
                    "recall_key": str(row["recall_key"]),
                    "record_id": str(row["record_id"]),
                    "created_at_utc": str(row["created_at_utc"]),
                }
                for row in rows
            ]
            result: dict[str, Any] = {
                "deleted": False,
                "deleted_count": 0,
                "requires_selection": False,
                "matches": matches,
            }
            if not rows:
                return result
            if key is not None and len(rows) > 1 and not delete_all_matches:
                result["requires_selection"] = True
                return result
            if identifier is not None and len(rows) > 1:
                raise ValueError(
                    "MCP memory index contains a duplicate record_id."
                )

            selected_rows = rows if delete_all_matches else rows[:1]
            rows_by_file: dict[str, list[sqlite3.Row]] = {}
            for row in selected_rows:
                rows_by_file.setdefault(str(row["file_id"]), []).append(row)

            for file_id, file_rows in rows_by_file.items():
                utc_date = str(file_rows[0]["created_at_utc"])[:10]
                target_ids = {
                    str(row["record_id"])
                    for row in file_rows
                }
                self._delete_from_daily_history(
                    owner,
                    file_id,
                    utc_date,
                    target_ids,
                )

            selected_ids = {
                str(row["record_id"])
                for row in selected_rows
            }
            result["deleted"] = True
            result["matches"] = [
                match
                for match in matches
                if match["record_id"] in selected_ids
            ]
            result["deleted_count"] = len(result["matches"])
            self._delete_description_vectors(selected_ids)
            return result

    def _allocate_unique_recall_key(
        self,
        owner_sub: str,
        base_key: str,
    ) -> str:
        with sqlite3.connect(self.sqlite_path) as conn:
            rows = conn.execute(
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

    def _rollback_failed_vector_save(
        self,
        *,
        owner_sub: str,
        file_id: str,
        utc_date: str,
        record: MemoryRecord,
        original_error: Exception,
    ) -> None:
        try:
            self._delete_from_daily_history(
                owner_sub,
                file_id,
                utc_date,
                {record.record_id},
            )
        except Exception as rollback_error:
            raise EpisodicMemoryPartialSaveError(
                record.record_id,
                record.direct_recall_key,
            ) from rollback_error

        try:
            self._description_vectors.delete_records([record.record_id])
        except Exception:
            LogNoGUI(
                "GHOST MCP left an unreferenced description vector after "
                "rolling back a failed Episodic save.",
                "WARN",
                "INTERNAL",
            )

        raise RuntimeError(
            "episodic description indexing failed; durable save was rolled back"
        ) from original_error

    def _delete_description_vectors(self, record_ids: set[str]) -> None:
        try:
            self._description_vectors.delete_records(record_ids)
        except Exception:
            LogNoGUI(
                "GHOST MCP deleted durable memory but description-vector "
                "cleanup failed.",
                "WARN",
                "INTERNAL",
            )

    def _delete_from_daily_history(
        self,
        owner_sub: str,
        file_id: str,
        utc_date: str,
        target_ids: set[str],
    ) -> None:
        ragmem_path, meta_path, filename_ragmem, filename_meta = (
            self._resolve_indexed_history(owner_sub, file_id)
        )
        loaded_file_id, records, existing_metainfo = (
            self._load_daily_history(
                owner_sub,
                ragmem_path,
                meta_path,
            )
        )
        if loaded_file_id != file_id:
            raise ValueError(
                "MCP memory index and metadata do not match."
            )
        if not target_ids.issubset(
            {record.record_id for record in records}
        ):
            raise ValueError(
                "MCP memory index and file contents do not match."
            )

        remaining = [
            record
            for record in records
            if record.record_id not in target_ids
        ]
        if not remaining:
            ragmem_path.unlink()
            meta_path.unlink()
            with sqlite3.connect(self.sqlite_path) as conn:
                conn.execute(
                    "DELETE FROM memory_records WHERE file_id = ?",
                    [file_id],
                )
                conn.execute(
                    "DELETE FROM memory_files WHERE file_id = ?",
                    [file_id],
                )
                conn.commit()
            return

        ragmem_path.write_text(
            "".join(
                f"{record.to_ragmem_block()}\n"
                for record in remaining
            ),
            encoding="utf-8",
        )
        metainfo = self._build_metainfo(
            owner_sub=owner_sub,
            file_id=file_id,
            title=f"MCP_MEM_{utc_date}",
            filename_ragmem=filename_ragmem,
            filename_meta=filename_meta,
            records=remaining,
            existing_metainfo=existing_metainfo,
        )
        meta_path.write_text(
            json.dumps(
                metainfo,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self._refresh_sqlite_index(metainfo, remaining)

    def _resolve_daily_history(
        self,
        owner_sub: str,
        utc_date: str,
    ) -> tuple[Path, Path, str, str]:
        owner_root = self.files_root / owner_sub / "direct_recall"
        owner_root.mkdir(parents=True, exist_ok=True)

        stem = f"MCP_MEM_{utc_date}"
        filename_ragmem = (
            f"{owner_sub}/direct_recall/{stem}.ragmem"
        )
        filename_meta = (
            f"{owner_sub}/direct_recall/{stem}.ragmeta.json"
        )
        return (
            self.files_root / filename_ragmem,
            self.files_root / filename_meta,
            filename_ragmem,
            filename_meta,
        )

    def _resolve_indexed_history(
        self,
        owner_sub: str,
        file_id: str,
    ) -> tuple[Path, Path, str, str]:
        with sqlite3.connect(self.sqlite_path) as conn:
            row = conn.execute(
                """
                SELECT filename_ragmem, filename_meta
                FROM memory_files
                WHERE file_id = ?
                  AND owner_sub = ?
                """,
                [file_id, owner_sub],
            ).fetchone()

        if row is None:
            raise ValueError(
                "MCP memory index entry was not found."
            )

        filename_ragmem = str(row[0])
        filename_meta = str(row[1])
        return (
            self.files_root / filename_ragmem,
            self.files_root / filename_meta,
            filename_ragmem,
            filename_meta,
        )

    def _load_daily_history(
        self,
        owner_sub: str,
        ragmem_path: Path,
        meta_path: Path,
    ) -> tuple[str, list[MemoryRecord], dict[str, Any]]:
        if not ragmem_path.exists() and not meta_path.exists():
            return uuid.uuid4().hex, [], {}

        if not ragmem_path.exists() or not meta_path.exists():
            raise ValueError(
                "MCP memory file pair is incomplete."
            )

        try:
            metainfo = json.loads(
                meta_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(
                "MCP memory metadata is invalid."
            ) from error

        if not isinstance(metainfo, dict):
            raise ValueError("MCP memory metadata is invalid.")
        if metainfo.get("owner_sub") != owner_sub:
            raise ValueError("MCP memory owner does not match.")

        file_id = str(metainfo.get("file_id", "")).strip()
        if not file_id:
            raise ValueError(
                "MCP memory metadata has no file_id."
            )

        meta_records = metainfo.get("records", [])
        if not isinstance(meta_records, list):
            raise ValueError("MCP memory metadata is invalid.")

        metadata_by_id = {
            str(item.get("record_id", "")): item
            for item in meta_records
            if isinstance(item, dict)
            and str(item.get("record_id", "")).strip()
        }
        records: list[MemoryRecord] = []

        try:
            ragmem_text = ragmem_path.read_text(encoding="utf-8")
        except OSError as error:
            raise ValueError(
                "MCP memory file cannot be read."
            ) from error

        for match in _RECORD_PATTERN.finditer(ragmem_text):
            try:
                data = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue

            loaded_record = MemoryRecord.from_dict(data)
            metadata = metadata_by_id.get(loaded_record.record_id)
            if metadata is not None:
                loaded_record.update_metadata_overlay(metadata)
            records.append(loaded_record)

        return file_id, records, metainfo

    def _build_metainfo(
        self,
        owner_sub: str,
        file_id: str,
        title: str,
        filename_ragmem: str,
        filename_meta: str,
        records: list[MemoryRecord],
        existing_metainfo: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tag_summary: dict[str, int] = {}
        auto_keywords: list[str] = []
        user_keywords: list[str] = []

        for record in records:
            tag_summary[record.tag] = (
                tag_summary.get(record.tag, 0) + 1
            )
            auto_keywords.extend(record.auto_keywords)
            user_keywords.extend(record.user_keywords)

        metainfo = dict(existing_metainfo or {})
        metainfo.update(
            {
                "file_id": file_id,
                "title": title,
                "memory_type": EPISODIC_MEMORY_TYPE,
                "memory_description": str(
                    metainfo.get("memory_description", "") or ""
                ).strip(),
                "actors": _list_or_empty(
                    metainfo.get("actors")
                ),
                "filename_ragmem": filename_ragmem,
                "filename_meta": filename_meta,
                "created_at_utc": (
                    str(metainfo.get("created_at_utc") or "")
                    or (
                        records[0].created_at_utc
                        if records
                        else ""
                    )
                ),
                "updated_at_utc": (
                    _utc_now()
                    if records
                    else ""
                ),
                "record_count": len(records),
                "record_ids": [
                    record.record_id
                    for record in records
                ],
                "parent_ids": _unique(
                    [
                        record.parent_id
                        for record in records
                        if record.parent_id
                    ]
                ),
                "tag_summary": tag_summary,
                "auto_keywords": _unique(auto_keywords),
                "user_keywords": _unique(user_keywords),
                "records": [
                    record.to_index_dict()
                    for record in records
                ],
                "owner_sub": owner_sub,
                "expires_at_utc": _optional_str(
                    metainfo.get("expires_at_utc")
                ),
            }
        )
        return metainfo

    def _refresh_sqlite_index(
        self,
        metainfo: dict[str, Any],
        records: list[MemoryRecord],
    ) -> None:
        file_id = str(metainfo["file_id"])

        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute(
                """
                INSERT INTO memory_files (
                    file_id,
                    title,
                    memory_type,
                    memory_description,
                    actors_json,
                    filename_ragmem,
                    filename_meta,
                    created_at_utc,
                    updated_at_utc,
                    record_count,
                    owner_sub,
                    expires_at_utc
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    metainfo["title"],
                    metainfo["memory_type"],
                    metainfo["memory_description"],
                    json.dumps(
                        metainfo["actors"],
                        ensure_ascii=False,
                    ),
                    metainfo["filename_ragmem"],
                    metainfo["filename_meta"],
                    metainfo["created_at_utc"],
                    metainfo["updated_at_utc"],
                    metainfo["record_count"],
                    metainfo["owner_sub"],
                    metainfo["expires_at_utc"],
                ),
            )

            for record in records:
                index_data = record.to_index_dict()
                conn.execute(
                    """
                    INSERT INTO memory_records (
                        file_id,
                        record_id,
                        parent_id,
                        sequence_number,
                        created_at_utc,
                        actor_id,
                        chat_stream_id,
                        source,
                        tag,
                        retrieval_source_mode,
                        direct_recall_key,
                        episode_title,
                        episode_description,
                        auto_keywords_json,
                        user_keywords_json,
                        active_project_name,
                        embedded_files_snapshot_json,
                        expires_at_utc,
                        input_hash,
                        output_hash
                    )
                    VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    ON CONFLICT(file_id, record_id) DO UPDATE SET
                        parent_id = excluded.parent_id,
                        sequence_number = excluded.sequence_number,
                        created_at_utc = excluded.created_at_utc,
                        actor_id = excluded.actor_id,
                        chat_stream_id = excluded.chat_stream_id,
                        source = excluded.source,
                        tag = excluded.tag,
                        retrieval_source_mode = excluded.retrieval_source_mode,
                        direct_recall_key = excluded.direct_recall_key,
                        episode_title = excluded.episode_title,
                        episode_description = excluded.episode_description,
                        auto_keywords_json = excluded.auto_keywords_json,
                        user_keywords_json = excluded.user_keywords_json,
                        active_project_name = excluded.active_project_name,
                        embedded_files_snapshot_json =
                            excluded.embedded_files_snapshot_json,
                        expires_at_utc = excluded.expires_at_utc,
                        input_hash = excluded.input_hash,
                        output_hash = excluded.output_hash
                    """,
                    (
                        file_id,
                        index_data["record_id"],
                        index_data["parent_id"],
                        index_data["sequence_number"],
                        index_data["created_at_utc"],
                        index_data["actor_id"],
                        index_data["chat_stream_id"],
                        index_data["source"],
                        index_data["tag"],
                        index_data["retrieval_source_mode"],
                        index_data["direct_recall_key"],
                        index_data["episode_title"],
                        index_data["episode_description"],
                        json.dumps(
                            index_data["auto_keywords"],
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            index_data["user_keywords"],
                            ensure_ascii=False,
                        ),
                        index_data["active_project_name"],
                        json.dumps(
                            index_data["embedded_files_snapshot"],
                            ensure_ascii=False,
                        ),
                        index_data["expires_at_utc"],
                        index_data["input_hash"],
                        index_data["output_hash"],
                    ),
                )

            record_ids = [
                record.record_id
                for record in records
            ]
            placeholders = ",".join(
                "?"
                for _ in record_ids
            )
            conn.execute(
                f"""
                DELETE FROM memory_records
                WHERE file_id = ?
                  AND record_id NOT IN ({placeholders})
                """,
                [file_id, *record_ids],
            )
            conn.commit()

    def _init_sqlite(self) -> None:
        self.sqlite_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with sqlite3.connect(self.sqlite_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_files (
                    file_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    memory_type TEXT NOT NULL DEFAULT '',
                    memory_description TEXT NOT NULL DEFAULT '',
                    actors_json TEXT NOT NULL DEFAULT '[]',
                    filename_ragmem TEXT NOT NULL,
                    filename_meta TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    record_count INTEGER NOT NULL,
                    owner_sub TEXT NOT NULL DEFAULT '',
                    expires_at_utc TEXT
                );

                CREATE TABLE IF NOT EXISTS memory_records (
                    file_id TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    parent_id TEXT,
                    sequence_number INTEGER NOT NULL DEFAULT 0,
                    created_at_utc TEXT NOT NULL,
                    actor_id TEXT NOT NULL DEFAULT '',
                    chat_stream_id TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    retrieval_source_mode TEXT NOT NULL DEFAULT 'QA',
                    direct_recall_key TEXT NOT NULL DEFAULT '',
                    episode_title TEXT NOT NULL DEFAULT '',
                    episode_description TEXT NOT NULL DEFAULT '',
                    auto_keywords_json TEXT NOT NULL,
                    user_keywords_json TEXT NOT NULL,
                    active_project_name TEXT,
                    embedded_files_snapshot_json TEXT NOT NULL,
                    expires_at_utc TEXT,
                    input_hash TEXT NOT NULL,
                    output_hash TEXT NOT NULL,
                    PRIMARY KEY (file_id, record_id)
                );
                """
            )

            file_columns = {
                str(row[1])
                for row in conn.execute(
                    "PRAGMA table_info(memory_files)"
                ).fetchall()
            }
            file_additions = {
                "memory_type": "TEXT NOT NULL DEFAULT ''",
                "memory_description": "TEXT NOT NULL DEFAULT ''",
                "actors_json": "TEXT NOT NULL DEFAULT '[]'",
                "owner_sub": "TEXT NOT NULL DEFAULT ''",
                "expires_at_utc": "TEXT",
            }
            for column_name, declaration in file_additions.items():
                if column_name not in file_columns:
                    conn.execute(
                        f"ALTER TABLE memory_files "
                        f"ADD COLUMN {column_name} {declaration}"
                    )

            record_columns = {
                str(row[1])
                for row in conn.execute(
                    "PRAGMA table_info(memory_records)"
                ).fetchall()
            }
            record_additions = {
                "sequence_number": "INTEGER NOT NULL DEFAULT 0",
                "actor_id": "TEXT NOT NULL DEFAULT ''",
                "chat_stream_id": "TEXT NOT NULL DEFAULT ''",
                "retrieval_source_mode": "TEXT NOT NULL DEFAULT 'QA'",
                "direct_recall_key": "TEXT NOT NULL DEFAULT ''",
                "episode_title": "TEXT NOT NULL DEFAULT ''",
                "episode_description": "TEXT NOT NULL DEFAULT ''",
                "expires_at_utc": "TEXT",
            }
            for column_name, declaration in record_additions.items():
                if column_name not in record_columns:
                    conn.execute(
                        f"ALTER TABLE memory_records "
                        f"ADD COLUMN {column_name} {declaration}"
                    )

            conn.executescript(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_memory_files_owner_sub
                ON memory_files(owner_sub);

                CREATE INDEX IF NOT EXISTS
                    idx_memory_files_memory_type
                ON memory_files(memory_type);

                CREATE INDEX IF NOT EXISTS
                    idx_memory_records_tag
                ON memory_records(tag);

                CREATE INDEX IF NOT EXISTS
                    idx_memory_records_project
                ON memory_records(active_project_name);

                CREATE INDEX IF NOT EXISTS
                    idx_memory_records_direct_recall_key
                ON memory_records(direct_recall_key);

                CREATE INDEX IF NOT EXISTS
                    idx_memory_records_record_id
                ON memory_records(record_id);

                CREATE INDEX IF NOT EXISTS
                    idx_memory_records_file_sequence
                ON memory_records(file_id, sequence_number);
                """
            )
            conn.commit()

    @staticmethod
    def _validate_owner_sub(owner_sub: str) -> str:
        if not isinstance(owner_sub, str):
            raise ValueError(
                "owner_sub is not a safe path component."
            )

        value = owner_sub
        if (
            value in {"", ".", ".."}
            or _OWNER_SUB_PATTERN.fullmatch(value) is None
        ):
            raise ValueError(
                "owner_sub is not a safe path component."
            )
        return value

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