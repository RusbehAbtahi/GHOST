# ragstream/memory/memory_manager.py
# -*- coding: utf-8 -*-
"""
MemoryManager
=============
Owns one active memory history file, its MemoryRecords, MetaInfo,
.ragmem persistence, .ragmeta.json persistence, and SQLite indexing.

Authority split:
- .ragmem is append-only and stores stable memory body fields only.
- .ragmeta.json stores current editable/readable metadata.
- SQLite mirrors .ragmeta.json for fast lookup/indexing.

ActiveBrief pending-topic buffer:
- RAM-only.
- Not written to .ragmem, .ragmeta.json, or SQLite.
- Used only to detect whether consecutive skipped Q/A pairs form a new topic.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ragstream.memory.memory_record import (
    MemoryRecord,
    RECORD_END,
    RECORD_START,
)
from ragstream.textforge.RagLog import LogDeveloper as _logger_dev


DEV_LOG_ENABLED = False


def logger_dev(*args, **kwargs):
    if DEV_LOG_ENABLED:
        return _logger_dev(*args, **kwargs)
    return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _filename_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H-%M")


def _safe_title(title: str) -> str:
    value = (title or "").strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-._")
    return value or "Untitled"


def _clean_storage_folder(storage_folder: str) -> str:
    value = str(storage_folder or "").strip().replace("\\", "/")
    if not value:
        return ""

    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("storage_folder must be a safe relative path.")

    return "/".join(path.parts)


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        item = str(value).strip()
        if not item:
            continue

        key = item.lower()
        if key in seen:
            continue

        result.append(item)
        seen.add(key)

    return result


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    return text if text else None


def _list_or_empty(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _actors_from_json(value: Any) -> list[Any]:
    if not isinstance(value, str) or not value.strip():
        return []

    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []

    return _list_or_empty(decoded)


def _clean_retrieval_source_mode(value: str | None) -> str | None:
    if value is None:
        return None

    mode = str(value or "").strip().upper()
    if mode in {"QA", "Q", "A"}:
        return mode

    return "QA"


def _clean_direct_recall_key(value: str | None) -> str | None:
    if value is None:
        return None

    return str(value or "").strip()


class MemoryManager:
    def __init__(
        self,
        memory_root: Path,
        sqlite_path: Path,
        title: str = "",
        *,
        memory_type: str = "",
        memory_description: str = "",
        actors: list[Any] | None = None,
        owner_sub: str = "",
        expires_at_utc: str | None = None,
    ) -> None:
        self.file_id: str = uuid.uuid4().hex
        self.title: str = ""
        self.memory_type: str = str(memory_type or "").strip()
        self.memory_description: str = str(memory_description or "").strip()
        self.actors: list[Any] = _list_or_empty(actors)
        self.owner_sub: str = str(owner_sub or "").strip()
        self.expires_at_utc: str | None = _optional_str(expires_at_utc)
        self.created_at_utc: str = ""
        self.updated_at_utc: str = ""
        self.filename_ragmem: str = ""
        self.filename_meta: str = ""

        self.memory_root: Path = Path(memory_root)
        self.sqlite_path: Path = Path(sqlite_path)

        self.records: list[MemoryRecord] = []
        self.metainfo: dict[str, Any] = {}

        # RAM-only buffer for topic-shift detection.
        # If Q/A is skipped as unrelated to the current ActiveBrief,
        # its reduced text and vectors are kept here.
        # The next skipped Q/A is compared to this buffer.
        self.pending_activebrief_topic_buffer: dict[str, Any] = {}

        self.tag_catalog: list[str] = ["Gold", "Green", "Black"]
        self.b_file_created: bool = False

        self.memory_root.mkdir(parents=True, exist_ok=True)
        self.files_root.mkdir(parents=True, exist_ok=True)
        self._init_sqlite()

        if title.strip():
            self.start_new_history(
                title,
                memory_type=self.memory_type,
                memory_description=self.memory_description,
                actors=self.actors,
                owner_sub=self.owner_sub,
                expires_at_utc=self.expires_at_utc,
            )

    @property
    def files_root(self) -> Path:
        return self.memory_root / "files"

    @property
    def ragmem_path(self) -> Path:
        return self.files_root / self.filename_ragmem

    @property
    def meta_path(self) -> Path:
        return self.files_root / self.filename_meta

    def start_new_history(
        self,
        title: str,
        *,
        memory_type: str = "",
        memory_description: str = "",
        actors: list[Any] | None = None,
        owner_sub: str = "",
        expires_at_utc: str | None = None,
        storage_folder: str = "",
    ) -> None:
        clean_title = (title or "").strip()
        if not clean_title:
            raise ValueError("Memory title must not be empty.")

        self.file_id = uuid.uuid4().hex
        self.title = clean_title
        self.memory_type = str(memory_type or "").strip()
        self.memory_description = str(memory_description or "").strip()
        self.actors = _list_or_empty(actors)
        self.owner_sub = str(owner_sub or "").strip()
        self.expires_at_utc = _optional_str(expires_at_utc)
        self.created_at_utc = _utc_now()
        self.updated_at_utc = self.created_at_utc
        self.records = []
        self.metainfo = {}
        self.pending_activebrief_topic_buffer = {}
        self.b_file_created = False

        relative_folder = _clean_storage_folder(storage_folder)
        stem = f"{_filename_timestamp()}-{_safe_title(clean_title)}"
        filename_ragmem = f"{stem}.ragmem"
        filename_meta = f"{stem}.ragmeta.json"

        if relative_folder:
            filename_ragmem = f"{relative_folder}/{filename_ragmem}"
            filename_meta = f"{relative_folder}/{filename_meta}"

        if (self.files_root / filename_ragmem).exists():
            stem = f"{stem}-{self.file_id[:8]}"
            filename_ragmem = f"{stem}.ragmem"
            filename_meta = f"{stem}.ragmeta.json"
            if relative_folder:
                filename_ragmem = f"{relative_folder}/{filename_ragmem}"
                filename_meta = f"{relative_folder}/{filename_meta}"

        self.filename_ragmem = filename_ragmem
        self.filename_meta = filename_meta

    def load_history(self, file_id: str) -> None:
        file_row = self._lookup_file(file_id)
        if not file_row:
            raise ValueError(f"Memory history not found: {file_id}")

        self.file_id = file_row["file_id"]
        self.title = file_row["title"]
        self.memory_type = str(file_row.get("memory_type", "") or "").strip()
        self.memory_description = str(
            file_row.get("memory_description", "") or ""
        ).strip()
        self.actors = _actors_from_json(file_row.get("actors_json", "[]"))
        self.owner_sub = str(file_row.get("owner_sub", "") or "").strip()
        self.expires_at_utc = _optional_str(file_row.get("expires_at_utc"))
        self.created_at_utc = str(file_row.get("created_at_utc", "") or "")
        self.updated_at_utc = str(file_row.get("updated_at_utc", "") or "")
        self.filename_ragmem = file_row["filename_ragmem"]
        self.filename_meta = file_row["filename_meta"]

        self.records = self._read_ragmem_records(self.ragmem_path)
        self.pending_activebrief_topic_buffer = {}
        self.b_file_created = self.ragmem_path.exists()

        if self.meta_path.exists():
            with self.meta_path.open("r", encoding="utf-8") as f:
                loaded_meta = json.load(f)
            self.metainfo = loaded_meta if isinstance(loaded_meta, dict) else {}
            self._apply_file_metainfo()
            self._apply_metainfo_overlay_to_records()
        else:
            self.save_metainfo()

        self.refresh_sqlite_index()

    def list_histories(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT file_id, title, memory_type, memory_description,
                       actors_json, filename_ragmem, filename_meta,
                       created_at_utc, updated_at_utc, record_count,
                       owner_sub, expires_at_utc
                FROM memory_files
                ORDER BY updated_at_utc DESC
                """
            ).fetchall()

        histories: list[dict[str, Any]] = []
        for row in rows:
            history = dict(row)
            history["actors"] = _actors_from_json(history.pop("actors_json", "[]"))
            histories.append(history)

        return histories

    def capture_pair(
        self,
        input_text: str,
        output_text: str,
        source: str,
        parent_id: str | None = None,
        user_keywords: list[str] | None = None,
        active_project_name: str | None = None,
        embedded_files_snapshot: list[str] | None = None,
    ) -> MemoryRecord:
        next_sequence_number = max(
            len(self.records),
            max((record.sequence_number for record in self.records), default=0),
        ) + 1
        record = MemoryRecord(
            input_text=input_text,
            output_text=output_text,
            source=source,
            parent_id=parent_id,
            tag="Green",
            user_keywords=user_keywords,
            active_project_name=active_project_name,
            embedded_files_snapshot=embedded_files_snapshot,
            retrieval_source_mode="QA",
            direct_recall_key="",
            sequence_number=next_sequence_number,
        )

        if not self.title.strip():
            auto_title = self._build_auto_history_title(
                record=record,
                active_project_name=active_project_name,
            )
            self.start_new_history(
                auto_title,
                memory_type=self.memory_type,
                memory_description=self.memory_description,
                actors=self.actors,
                owner_sub=self.owner_sub,
                expires_at_utc=self.expires_at_utc,
            )

        self._update_active_retrieval_brief(record)

        self.records.append(record)
        self._append_record_to_ragmem(record)
        self.save_metainfo()
        self.refresh_sqlite_index()

        return record

    def sync_gui_edits(
        self,
        gui_records_state: list[dict[str, Any]],
    ) -> None:
        if not gui_records_state:
            return

        records_by_id = {record.record_id: record for record in self.records}
        changed = False

        for item in gui_records_state:
            record_id = str(item.get("record_id", "")).strip()
            if not record_id or record_id not in records_by_id:
                continue

            record = records_by_id[record_id]

            tag = item.get("tag")
            if tag is not None:
                tag = str(tag).strip()
                if tag not in self.tag_catalog:
                    tag = None

            user_keywords = item.get("user_keywords")
            if user_keywords is not None and not isinstance(user_keywords, list):
                user_keywords = []

            retrieval_source_mode = _clean_retrieval_source_mode(item.get("retrieval_source_mode"))
            direct_recall_key = _clean_direct_recall_key(item.get("direct_recall_key"))

            before = record.to_index_dict()
            record.update_editable_metadata(
                tag=tag,
                user_keywords=user_keywords,
                retrieval_source_mode=retrieval_source_mode,
                direct_recall_key=direct_recall_key,
            )
            after = record.to_index_dict()

            if before != after:
                changed = True

        if changed:
            self.save_metainfo()
            self.refresh_sqlite_index()

    def save_metainfo(self) -> None:
        self.metainfo = self._build_metainfo()

        if not self.filename_meta:
            return

        self.meta_path.parent.mkdir(parents=True, exist_ok=True)
        with self.meta_path.open("w", encoding="utf-8") as f:
            json.dump(self.metainfo, f, ensure_ascii=False, indent=2)

    def refresh_sqlite_index(self) -> None:
        self._init_sqlite()

        if not self.file_id or not self.filename_ragmem:
            return

        metainfo = self._build_metainfo()
        now = _utc_now()

        created_at_utc = metainfo.get("created_at_utc") or now
        updated_at_utc = metainfo.get("updated_at_utc") or now
        record_count = int(metainfo.get("record_count", 0))

        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute(
                """
                INSERT INTO memory_files (
                    file_id, title, memory_type, memory_description,
                    actors_json, filename_ragmem, filename_meta,
                    created_at_utc, updated_at_utc, record_count,
                    owner_sub, expires_at_utc
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
                    self.file_id,
                    self.title,
                    self.memory_type,
                    self.memory_description,
                    json.dumps(self.actors, ensure_ascii=False),
                    self.filename_ragmem,
                    self.filename_meta,
                    created_at_utc,
                    updated_at_utc,
                    record_count,
                    self.owner_sub,
                    self.expires_at_utc,
                ),
            )

            for record in self.records:
                index_data = record.to_index_dict()

                conn.execute(
                    """
                    INSERT INTO memory_records (
                        file_id, record_id, parent_id, sequence_number,
                        created_at_utc, actor_id, chat_stream_id, source, tag,
                        retrieval_source_mode, direct_recall_key, episode_title,
                        episode_description, auto_keywords_json,
                        user_keywords_json, active_project_name,
                        embedded_files_snapshot_json, expires_at_utc,
                        input_hash, output_hash
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        embedded_files_snapshot_json = excluded.embedded_files_snapshot_json,
                        expires_at_utc = excluded.expires_at_utc,
                        input_hash = excluded.input_hash,
                        output_hash = excluded.output_hash
                    """,
                    (
                        self.file_id,
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
                        json.dumps(index_data["auto_keywords"], ensure_ascii=False),
                        json.dumps(index_data["user_keywords"], ensure_ascii=False),
                        index_data["active_project_name"],
                        json.dumps(index_data["embedded_files_snapshot"], ensure_ascii=False),
                        index_data["expires_at_utc"],
                        index_data["input_hash"],
                        index_data["output_hash"],
                    ),
                )

            self._delete_sqlite_rows_not_in_memory(conn)
            conn.commit()

    def _build_metainfo(self) -> dict[str, Any]:
        record_ids = [record.record_id for record in self.records]
        parent_ids = _unique([record.parent_id for record in self.records if record.parent_id])

        tag_summary: dict[str, int] = {}
        auto_keywords: list[str] = []
        user_keywords: list[str] = []

        for record in self.records:
            tag_summary[record.tag] = tag_summary.get(record.tag, 0) + 1
            auto_keywords.extend(record.auto_keywords)
            user_keywords.extend(record.user_keywords)

        if not self.created_at_utc:
            self.created_at_utc = (
                self.records[0].created_at_utc if self.records else _utc_now()
            )
        self.updated_at_utc = _utc_now()

        metainfo = dict(self.metainfo)
        metainfo.update(
            {
                "file_id": self.file_id,
                "title": self.title,
                "memory_type": self.memory_type,
                "memory_description": self.memory_description,
                "actors": list(self.actors),
                "filename_ragmem": self.filename_ragmem,
                "filename_meta": self.filename_meta,
                "created_at_utc": self.created_at_utc,
                "updated_at_utc": self.updated_at_utc,
                "record_count": len(self.records),
                "record_ids": record_ids,
                "parent_ids": parent_ids,
                "tag_summary": tag_summary,
                "auto_keywords": _unique(auto_keywords),
                "user_keywords": _unique(user_keywords),
                "records": [record.to_index_dict() for record in self.records],
                "owner_sub": self.owner_sub,
                "expires_at_utc": self.expires_at_utc,
            }
        )
        return metainfo

    def close(self) -> None:
        self.save_metainfo()
        self.refresh_sqlite_index()

    def _update_active_retrieval_brief(self, record: MemoryRecord) -> None:
        """
        Build the ActiveRetrievalBrief for the new MemoryRecord.

        This happens before the record is first written to .ragmem so that
        active_retrieval_brief remains part of the stable body block.

        The pending-topic buffer is updated here too, because it belongs to
        the active memory history, not to Streamlit and not to the builder.
        """
        try:
            from ragstream.memory.compression.memory_active_retrieval_brief import (
                MemoryActiveRetrievalBriefBuilder,
            )

            builder = MemoryActiveRetrievalBriefBuilder()
            result = builder.build_for_record(
                record=record,
                previous_records=list(self.records),
                pending_topic_buffer=dict(self.pending_activebrief_topic_buffer or {}),
            )

            active_brief_title = str(
                result.get("active_retrieval_brief_title", "") or ""
            ).strip()
            active_brief = str(
                result.get("active_retrieval_brief", "") or ""
            ).strip()
            contributor_ids = list(
                result.get("active_retrieval_brief_contributor_ids") or []
            )

            record.update_active_retrieval_brief(
                active_retrieval_brief=active_brief,
                contributor_ids=contributor_ids,
                active_retrieval_brief_title=active_brief_title,
            )

            new_buffer = result.get("pending_activebrief_topic_buffer", {})
            self.pending_activebrief_topic_buffer = (
                new_buffer if isinstance(new_buffer, dict) else {}
            )

            logger_dev(
                "MemoryManager ActiveBrief update result\n"
                + json.dumps(
                    {
                        "record_id": record.record_id,
                        "activebrief_llm_skipped": bool(
                            result.get("activebrief_llm_skipped", False)
                        ),
                        "activebrief_gate_route": str(
                            result.get("activebrief_gate_route", "") or ""
                        ),
                        "active_retrieval_brief_title": active_brief_title,
                        "active_retrieval_brief": active_brief,
                        "active_retrieval_brief_contributor_ids": contributor_ids,
                        "pending_activebrief_topic_buffer": self._pending_buffer_log_view(
                            self.pending_activebrief_topic_buffer
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                "DEBUG",
                "CONFIDENTIAL",
            )

        except Exception as e:
            logger_dev(
                "ActiveRetrievalBrief generation failed\n"
                + json.dumps(
                    {
                        "record_id": record.record_id,
                        "error": str(e),
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                "ERROR",
                "CONFIDENTIAL",
            )

    def _append_record_to_ragmem(self, record: MemoryRecord) -> None:
        if not self.filename_ragmem:
            raise ValueError("Memory filename is not initialized.")

        self.ragmem_path.parent.mkdir(parents=True, exist_ok=True)

        with self.ragmem_path.open("a", encoding="utf-8") as f:
            f.write(record.to_ragmem_block())
            f.write("\n")

        self.b_file_created = True

    def _read_ragmem_records(self, path: Path) -> list[MemoryRecord]:
        if not path.exists():
            return []

        text = path.read_text(encoding="utf-8")
        pattern = re.compile(
            rf"{re.escape(RECORD_START)}\n(.*?)\n{re.escape(RECORD_END)}",
            re.DOTALL,
        )

        records: list[MemoryRecord] = []

        for match in pattern.finditer(text):
            raw_block = match.group(1)
            try:
                data = json.loads(raw_block)
                if isinstance(data, dict):
                    records.append(MemoryRecord.from_dict(data))
            except Exception:
                continue

        return records

    def _apply_file_metainfo(self) -> None:
        """Apply optional file-level metadata without requiring new fields."""
        if "memory_type" in self.metainfo:
            self.memory_type = str(self.metainfo.get("memory_type") or "").strip()

        if "memory_description" in self.metainfo:
            self.memory_description = str(
                self.metainfo.get("memory_description") or ""
            ).strip()

        if "actors" in self.metainfo:
            self.actors = _list_or_empty(self.metainfo.get("actors"))

        if "owner_sub" in self.metainfo:
            self.owner_sub = str(self.metainfo.get("owner_sub") or "").strip()

        if "expires_at_utc" in self.metainfo:
            self.expires_at_utc = _optional_str(
                self.metainfo.get("expires_at_utc")
            )

        if self.metainfo.get("created_at_utc"):
            self.created_at_utc = str(self.metainfo["created_at_utc"])

        if self.metainfo.get("updated_at_utc"):
            self.updated_at_utc = str(self.metainfo["updated_at_utc"])

    def _apply_metainfo_overlay_to_records(self) -> None:
        """
        Overlay current .ragmeta.json metadata onto records loaded from .ragmem.

        .ragmem supplies the stable body.
        .ragmeta.json supplies current metadata.
        """
        meta_records = self.metainfo.get("records", [])
        if not isinstance(meta_records, list):
            return

        metadata_by_record_id: dict[str, dict[str, Any]] = {}

        for item in meta_records:
            if not isinstance(item, dict):
                continue

            record_id = str(item.get("record_id", "")).strip()
            if not record_id:
                continue

            metadata_by_record_id[record_id] = item

        for record in self.records:
            metadata = metadata_by_record_id.get(record.record_id)
            if metadata is None:
                continue

            record.update_metadata_overlay(metadata)

    def _delete_sqlite_rows_not_in_memory(self, conn: sqlite3.Connection) -> None:
        """
        Keep SQLite as a mirror of the active MemoryManager.records list.
        SQLite is not allowed to keep extra current rows for this file_id.
        """
        if not self.records:
            conn.execute(
                "DELETE FROM memory_records WHERE file_id = ?",
                (self.file_id,),
            )
            return

        record_ids = [record.record_id for record in self.records]
        placeholders = ",".join("?" for _ in record_ids)

        conn.execute(
            f"""
            DELETE FROM memory_records
            WHERE file_id = ?
              AND record_id NOT IN ({placeholders})
            """,
            [self.file_id, *record_ids],
        )

    def _lookup_file(self, file_id: str) -> dict[str, Any] | None:
        self._init_sqlite()

        with sqlite3.connect(self.sqlite_path) as conn:
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

    def _build_auto_history_title(
        self,
        record: MemoryRecord,
        active_project_name: str | None = None,
    ) -> str:
        """
        Build the first memory history title automatically.

        The file name must stay generic and deterministic:
        YYYY-MM-DD-HH-mm-memory-record.ragmem
        """
        return "memory-record"

    @staticmethod
    def _pending_buffer_log_view(buffer: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(buffer, dict) or not buffer:
            return {}

        return {
            "record_id": str(buffer.get("record_id", "") or ""),
            "created_at_utc": str(buffer.get("created_at_utc", "") or ""),
            "question_vector_count": len(buffer.get("question_vectors", []) or []),
            "answer_vector_count": len(buffer.get("answer_vectors", []) or []),
            "vector_count": int(buffer.get("vector_count", 0) or 0),
            "has_center_vector": bool(buffer.get("center_vector", [])),
            "reduced_question_preview": str(buffer.get("reduced_question", "") or "")[:500],
            "reduced_answer_preview": str(buffer.get("reduced_answer", "") or "")[:500],
        }

    def _init_sqlite(self) -> None:
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute(
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
                )
                """
            )

            conn.execute(
                """
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
                )
                """
            )

            self._ensure_memory_files_columns(conn)
            self._ensure_memory_records_columns(conn)

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_files_owner_sub
                ON memory_files(owner_sub)
                """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_files_memory_type
                ON memory_files(memory_type)
                """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_records_tag
                ON memory_records(tag)
                """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_records_project
                ON memory_records(active_project_name)
                """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_records_direct_recall_key
                ON memory_records(direct_recall_key)
                """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_records_record_id
                ON memory_records(record_id)
                """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_records_file_sequence
                ON memory_records(file_id, sequence_number)
                """
            )

            conn.commit()

    @staticmethod
    def _ensure_memory_files_columns(conn: sqlite3.Connection) -> None:
        existing_columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(memory_files)").fetchall()
        }
        additions = {
            "memory_type": "TEXT NOT NULL DEFAULT ''",
            "memory_description": "TEXT NOT NULL DEFAULT ''",
            "actors_json": "TEXT NOT NULL DEFAULT '[]'",
            "owner_sub": "TEXT NOT NULL DEFAULT ''",
            "expires_at_utc": "TEXT",
        }

        for column_name, declaration in additions.items():
            if column_name not in existing_columns:
                conn.execute(
                    f"ALTER TABLE memory_files ADD COLUMN {column_name} {declaration}"
                )

    @staticmethod
    def _ensure_memory_records_columns(conn: sqlite3.Connection) -> None:
        existing_columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(memory_records)").fetchall()
        }
        additions = {
            "sequence_number": "INTEGER NOT NULL DEFAULT 0",
            "actor_id": "TEXT NOT NULL DEFAULT ''",
            "chat_stream_id": "TEXT NOT NULL DEFAULT ''",
            "retrieval_source_mode": "TEXT NOT NULL DEFAULT 'QA'",
            "direct_recall_key": "TEXT NOT NULL DEFAULT ''",
            "episode_title": "TEXT NOT NULL DEFAULT ''",
            "episode_description": "TEXT NOT NULL DEFAULT ''",
            "expires_at_utc": "TEXT",
        }

        for column_name, declaration in additions.items():
            if column_name not in existing_columns:
                conn.execute(
                    f"ALTER TABLE memory_records ADD COLUMN {column_name} {declaration}"
                )