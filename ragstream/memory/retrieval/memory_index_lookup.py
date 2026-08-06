# ragstream/memory/memory_index_lookup.py
# -*- coding: utf-8 -*-
"""
MemoryIndexLookup
=================
Deterministic lookup layer for Memory Retrieval.

This class reads memory_index.sqlite3 and, when needed, reconstructs Q/A body
text from the corresponding .ragmem file.

It does not perform vector search.
It does not score semantic hits.
It does not modify memory truth.
"""

from __future__ import annotations

import json
import re
import sqlite3

from pathlib import Path
from typing import Any

from ragstream.memory.memory_record import RECORD_END, RECORD_START
from ragstream.textforge.RagLog import LogALL as logger
from ragstream.textforge.RagLog import LogDeveloper as _logger_dev
DEV_LOG_ENABLED = False

def logger_dev(*args, **kwargs):
    if DEV_LOG_ENABLED:
        return _logger_dev(*args, **kwargs)
    return None

class MemoryIndexLookup:
    """
    SQLite-backed deterministic lookup helper.

    The SQLite table mirrors .ragmeta.json metadata.
    Full Q/A body is loaded from .ragmem only when needed for candidates.
    """

    def __init__(
        self,
        sqlite_path: str | Path,
        memory_root: str | Path | None = None,
    ) -> None:
        self.sqlite_path: Path = Path(sqlite_path)
        self.memory_root: Path | None = Path(memory_root) if memory_root is not None else None

    def get_working_memory(
        self,
        file_id: str,
        cfg: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Return latest non-Black records from the active memory file.

        This is the current-log working memory.
        """
        clean_file_id = str(file_id or "").strip()
        if not clean_file_id:
            return []

        working_cfg = cfg.get("working_memory", {}) if isinstance(cfg, dict) else {}
        if working_cfg.get("enabled", True) is False:
            return []

        max_pairs = int(working_cfg.get("max_pairs", 2))
        exclude_tags = self._as_list(working_cfg.get("exclude_tags", ["Black"]))

        query = """
            SELECT *
            FROM memory_records
            WHERE file_id = ?
        """
        params: list[Any] = [clean_file_id]

        if exclude_tags:
            placeholders = ",".join("?" for _ in exclude_tags)
            query += f" AND tag NOT IN ({placeholders})"
            params.extend(exclude_tags)

        query += " ORDER BY created_at_utc DESC LIMIT ?"
        params.append(max_pairs)

        rows = self._fetch_rows(query, params)
        candidates = [self._row_to_candidate(row) for row in rows]
        candidates = self._attach_file_rows(candidates)
        candidates = self._attach_ragmem_bodies(candidates)

        logger(
            f"Memory working lookup: file={clean_file_id[:8]} | candidates={len(candidates)}",
            "INFO",
            "INTERNAL",
        )

        logger_dev(
            "Memory working lookup result\n"
            + json.dumps(candidates, ensure_ascii=False, indent=2, default=str),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return candidates

    def get_latest_gold(
        self,
        file_id: str,
        cfg: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Return latest Gold candidates from the active memory file.

        Gold is still bounded by config; it is not unlimited context.
        """
        clean_file_id = str(file_id or "").strip()
        if not clean_file_id:
            return []

        episodic_cfg = cfg.get("episodic_memory", {}) if isinstance(cfg, dict) else {}
        if episodic_cfg.get("enabled", True) is False:
            return []

        max_gold_records = int(episodic_cfg.get("max_gold_records", 1))

        rows = self._fetch_rows(
            """
            SELECT *
            FROM memory_records
            WHERE file_id = ?
              AND tag = 'Gold'
            ORDER BY created_at_utc DESC
            LIMIT ?
            """,
            [clean_file_id, max_gold_records],
        )

        candidates = [self._row_to_candidate(row) for row in rows]
        candidates = self._attach_file_rows(candidates)
        candidates = self._attach_ragmem_bodies(candidates)

        logger(
            f"Memory Gold lookup: file={clean_file_id[:8]} | candidates={len(candidates)}",
            "INFO",
            "INTERNAL",
        )

        logger_dev(
            "Memory Gold lookup result\n"
            + json.dumps(candidates, ensure_ascii=False, indent=2, default=str),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return candidates

    def get_direct_recall(
        self,
        direct_recall_key: str,
        cfg: dict[str, Any],
        owner_sub: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Lookup a Direct Recall candidate across all memory histories.

        Automatic retrieval stays current-file only, but Direct Recall is allowed
        to cross histories through exact key lookup.

        When owner_sub is supplied, matching is restricted to memory files owned
        by that authenticated subject. Omitting it preserves normal GHOST lookup.
        """
        key = str(direct_recall_key or "").strip()
        if not key:
            return None

        direct_cfg = cfg.get("direct_recall", {}) if isinstance(cfg, dict) else {}
        if direct_cfg.get("enabled", True) is False:
            return None

        exclude_tags = self._as_list(direct_cfg.get("exclude_tags", ["Black"]))

        query = """
            SELECT mr.*
            FROM memory_records AS mr
        """
        params: list[Any] = []

        if owner_sub is None:
            query += " WHERE mr.direct_recall_key = ?"
        else:
            clean_owner_sub = str(owner_sub).strip()
            if not clean_owner_sub:
                return None

            query += """
                JOIN memory_files AS mf ON mf.file_id = mr.file_id
                WHERE mf.owner_sub = ?
                  AND mr.direct_recall_key = ?
            """
            params.append(clean_owner_sub)

        params.append(key)

        if exclude_tags:
            placeholders = ",".join("?" for _ in exclude_tags)
            query += f" AND mr.tag NOT IN ({placeholders})"
            params.extend(exclude_tags)

        query += """
            ORDER BY
              CASE mr.tag WHEN 'Gold' THEN 0 WHEN 'Green' THEN 1 ELSE 2 END,
              mr.created_at_utc DESC
            LIMIT 1
        """

        rows = self._fetch_rows(query, params)
        if not rows:
            logger(f"Direct Recall lookup found no match: key={key}", "INFO", "INTERNAL")
            return None

        candidates = [self._row_to_candidate(rows[0])]
        candidates = self._attach_file_rows(candidates)
        candidates = self._attach_ragmem_bodies(candidates)

        candidate = candidates[0] if candidates else None

        logger(
            f"Direct Recall lookup matched: key={key} | record={candidate.get('record_id', '')[:8] if candidate else ''}",
            "INFO",
            "INTERNAL",
        )

        logger_dev(
            "Direct Recall lookup result\n"
            + json.dumps(candidate, ensure_ascii=False, indent=2, default=str),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return candidate

    def get_records_by_ids(
        self,
        file_id: str,
        record_ids: list[str],
    ) -> list[dict[str, Any]]:
        """
        Load metadata rows for selected parent MemoryRecord ids.
        """
        clean_file_id = str(file_id or "").strip()
        clean_ids = [str(record_id).strip() for record_id in record_ids if str(record_id).strip()]

        if not clean_file_id or not clean_ids:
            return []

        placeholders = ",".join("?" for _ in clean_ids)

        rows = self._fetch_rows(
            f"""
            SELECT *
            FROM memory_records
            WHERE file_id = ?
              AND record_id IN ({placeholders})
            """,
            [clean_file_id, *clean_ids],
        )

        candidates = [self._row_to_candidate(row) for row in rows]
        candidates = self._attach_file_rows(candidates)
        candidates = self._attach_ragmem_bodies(candidates)

        return candidates

    def get_file_row(
        self,
        file_id: str,
    ) -> dict[str, Any] | None:
        """Return one row from memory_files."""
        clean_file_id = str(file_id or "").strip()
        if not clean_file_id:
            return None

        rows = self._fetch_rows(
            """
            SELECT *
            FROM memory_files
            WHERE file_id = ?
            """,
            [clean_file_id],
            table_name="memory_files",
        )

        return dict(rows[0]) if rows else None

    def _fetch_rows(
        self,
        query: str,
        params: list[Any],
        *,
        table_name: str = "memory_records",
    ) -> list[sqlite3.Row]:
        if not self.sqlite_path.exists():
            logger(f"Memory SQLite not found: {self.sqlite_path}", "WARN", "PUBLIC")
            return []

        with sqlite3.connect(self.sqlite_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()

        logger_dev(
            (
                "MemoryIndexLookup SQL result\n"
                f"table={table_name}\n"
                f"query={query.strip()}\n"
                f"params={params}\n"
                f"rows={len(rows)}"
            ),
            "TRACE",
            "CONFIDENTIAL",
        )

        return rows

    def _row_to_candidate(self, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        data = dict(row)

        candidate: dict[str, Any] = {
            "file_id": data.get("file_id", ""),
            "record_id": data.get("record_id", ""),
            "parent_id": data.get("parent_id", ""),
            "created_at_utc": data.get("created_at_utc", ""),
            "source": data.get("source", ""),
            "tag": data.get("tag", ""),
            "retrieval_source_mode": data.get("retrieval_source_mode", "QA"),
            "direct_recall_key": data.get("direct_recall_key", ""),
            "auto_keywords": self._json_list(data.get("auto_keywords_json")),
            "user_keywords": self._json_list(data.get("user_keywords_json")),
            "active_project_name": data.get("active_project_name", ""),
            "embedded_files_snapshot": self._json_list(data.get("embedded_files_snapshot_json")),
            "input_hash": data.get("input_hash", ""),
            "output_hash": data.get("output_hash", ""),
            "sqlite_metadata": data,
        }

        return candidate

    def _attach_file_rows(
        self,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        file_cache: dict[str, dict[str, Any]] = {}

        for candidate in candidates:
            file_id = str(candidate.get("file_id", "")).strip()
            if not file_id:
                continue

            if file_id not in file_cache:
                file_cache[file_id] = self.get_file_row(file_id) or {}

            file_row = file_cache[file_id]
            candidate["file_row"] = file_row
            candidate["title"] = file_row.get("title", "")
            candidate["filename_ragmem"] = file_row.get("filename_ragmem", "")
            candidate["filename_meta"] = file_row.get("filename_meta", "")

        return candidates

    def _attach_ragmem_bodies(
        self,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Attach stable Q/A body from .ragmem.

        SQLite intentionally stores metadata only, so Q/A body comes from
        the durable .ragmem file.
        """
        if self.memory_root is None:
            return candidates

        body_cache: dict[tuple[str, str], dict[str, Any]] = {}

        for candidate in candidates:
            file_id = str(candidate.get("file_id", "")).strip()
            record_id = str(candidate.get("record_id", "")).strip()

            if not file_id or not record_id:
                continue

            cache_key = (file_id, record_id)
            if cache_key not in body_cache:
                body_cache[cache_key] = self._load_ragmem_body(candidate)

            body = body_cache[cache_key]
            candidate["input_text"] = body.get("input_text", "")
            candidate["output_text"] = body.get("output_text", "")
            candidate["ragmem_body"] = body

        return candidates

    def _load_ragmem_body(
        self,
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        if self.memory_root is None:
            return {}

        filename_ragmem = str(candidate.get("filename_ragmem", "")).strip()
        record_id = str(candidate.get("record_id", "")).strip()

        if not filename_ragmem or not record_id:
            return {}

        ragmem_path = self.memory_root / "files" / filename_ragmem
        if not ragmem_path.exists():
            return {}

        text = ragmem_path.read_text(encoding="utf-8")
        pattern = re.compile(
            rf"{re.escape(RECORD_START)}\n(.*?)\n{re.escape(RECORD_END)}",
            re.DOTALL,
        )

        for match in pattern.finditer(text):
            raw_block = match.group(1)
            try:
                data = json.loads(raw_block)
            except Exception:
                continue

            if isinstance(data, dict) and str(data.get("record_id", "")) == record_id:
                return data

        return {}

    @staticmethod
    def _json_list(value: Any) -> list[Any]:
        if isinstance(value, list):
            return value

        if value is None:
            return []

        try:
            parsed = json.loads(str(value))
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []

    @staticmethod
    def _as_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]

        if value is None:
            return []

        text = str(value).strip()
        return [text] if text else []