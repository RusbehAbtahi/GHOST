# ragstream/memory/memory_record.py
# -*- coding: utf-8 -*-
"""Represent one accepted input/output memory episode and its metadata.

MemoryRecord keeps stable episode body fields separate from current metadata.
Only stable body fields are serialized into .ragmem; current metadata is exposed
through to_index_dict() for .ragmeta.json and compatible SQLite mirrors.

Main classes:
    MemoryRecord:
        Owns one memory episode, serialization, and metadata projection.

Main methods:
    update_editable_metadata():
        Applies user-editable metadata changes.
    update_metadata_overlay():
        Applies current metadata loaded from .ragmeta.json.
    to_ragmem_block():
        Serializes the stable append-only episode body.
    to_index_dict():
        Projects current metadata for .ragmeta.json and SQLite.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from datetime import datetime, timezone
from typing import Any


RECORD_START = "----- MEMORY RECORD START -----"
RECORD_END = "----- MEMORY RECORD END -----"


RETRIEVAL_SOURCE_MODES = {"QA", "Q", "A"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _clean_list(values: list[str] | None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()

    for value in values or []:
        item = str(value).strip()
        if not item:
            continue

        key = item.lower()
        if key in seen:
            continue

        cleaned.append(item)
        seen.add(key)

    return cleaned


def _clean_retrieval_source_mode(value: str | None) -> str:
    mode = str(value or "QA").strip().upper()
    return mode if mode in RETRIEVAL_SOURCE_MODES else "QA"


def _clean_direct_recall_key(value: str | None) -> str:
    return str(value or "").strip()


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    return text if text else None


class MemoryRecord:
    def __init__(
        self,
        input_text: str,
        output_text: str,
        source: str,
        parent_id: str | None = None,
        tag: str = "Green",
        user_keywords: list[str] | None = None,
        active_project_name: str | None = None,
        embedded_files_snapshot: list[str] | None = None,
        retrieval_source_mode: str = "QA",
        direct_recall_key: str = "",
        episode_title: str = "",
        active_retrieval_brief_title: str = "",
        active_retrieval_brief: str = "",
        active_retrieval_brief_contributor_ids: list[str] | None = None,
        *,
        record_id: str | None = None,
        created_at_utc: str | None = None,
        auto_keywords: list[str] | None = None,
        input_hash: str | None = None,
        output_hash: str | None = None,
    ) -> None:
        self.record_id: str = record_id or uuid.uuid4().hex
        self.parent_id: str | None = parent_id
        self.created_at_utc: str = created_at_utc or _utc_now()

        self.input_text: str = input_text or ""
        self.output_text: str = output_text or ""
        self.source: str = source or ""

        self.tag: str = tag or "Green"
        self.user_keywords: list[str] = _clean_list(user_keywords)
        self.retrieval_source_mode: str = _clean_retrieval_source_mode(retrieval_source_mode)
        self.direct_recall_key: str = _clean_direct_recall_key(direct_recall_key)
        self.episode_title: str = str(episode_title or "").strip()

        self.active_project_name: str | None = active_project_name
        self.embedded_files_snapshot: list[str] = list(embedded_files_snapshot or [])

        self.active_retrieval_brief_title: str = str(active_retrieval_brief_title or "").strip()
        self.active_retrieval_brief: str = str(active_retrieval_brief or "").strip()
        self.active_retrieval_brief_contributor_ids: list[str] = _clean_list(
            active_retrieval_brief_contributor_ids
        )

        self.input_hash: str = input_hash or _sha256(self.input_text)
        self.output_hash: str = output_hash or _sha256(self.output_text)

        if auto_keywords is None:
            self.auto_keywords: list[str] = self.generate_auto_keywords()
        else:
            self.auto_keywords = _clean_list(auto_keywords)

    def generate_auto_keywords(self) -> list[str]:
        text = f"{self.input_text}\n\n{self.output_text}".strip()
        if not text:
            return []

        try:
            import yake
        except Exception:
            return []

        try:
            extractor = yake.KeywordExtractor(
                lan="en",
                n=3,
                dedupLim=0.9,
                top=5,
                features=None,
            )
            keywords = extractor.extract_keywords(text)
            return _clean_list([kw for kw, _score in keywords])
        except Exception:
            return []

    def update_editable_metadata(
        self,
        tag: str | None = None,
        user_keywords: list[str] | None = None,
        retrieval_source_mode: str | None = None,
        direct_recall_key: str | None = None,
    ) -> None:
        if tag is not None:
            clean_tag = str(tag).strip()
            if clean_tag:
                self.tag = clean_tag

        if user_keywords is not None:
            self.user_keywords = _clean_list(user_keywords)

        if retrieval_source_mode is not None:
            self.retrieval_source_mode = _clean_retrieval_source_mode(retrieval_source_mode)

        if direct_recall_key is not None:
            self.direct_recall_key = _clean_direct_recall_key(direct_recall_key)

    def update_active_retrieval_brief(
        self,
        active_retrieval_brief: str,
        contributor_ids: list[str] | None = None,
        active_retrieval_brief_title: str = "",
    ) -> None:
        self.active_retrieval_brief_title = str(active_retrieval_brief_title or "").strip()
        self.active_retrieval_brief = str(active_retrieval_brief or "").strip()
        self.active_retrieval_brief_contributor_ids = _clean_list(contributor_ids)

    def update_metadata_overlay(
        self,
        metadata: dict[str, Any],
    ) -> None:
        """
        Apply current metadata loaded from .ragmeta.json.

        This method deliberately does not modify stable .ragmem body fields:
        - record_id
        - parent_id
        - created_at_utc
        - input_text
        - output_text
        - source
        - input_hash
        - output_hash
        - active_retrieval_brief_title
        - active_retrieval_brief
        - active_retrieval_brief_contributor_ids
        """
        if not isinstance(metadata, dict):
            return

        self.update_editable_metadata(
            tag=metadata.get("tag"),
            user_keywords=list(metadata.get("user_keywords") or []),
            retrieval_source_mode=metadata.get("retrieval_source_mode"),
            direct_recall_key=metadata.get("direct_recall_key"),
        )

        if "episode_title" in metadata:
            self.episode_title = str(metadata.get("episode_title") or "").strip()

        if "auto_keywords" in metadata:
            self.auto_keywords = _clean_list(list(metadata.get("auto_keywords") or []))

        if "active_project_name" in metadata:
            self.active_project_name = _optional_str(metadata.get("active_project_name"))

        if "embedded_files_snapshot" in metadata:
            self.embedded_files_snapshot = list(metadata.get("embedded_files_snapshot") or [])

    def to_ragmem_dict(self) -> dict[str, Any]:
        """
        Stable append-only .ragmem body.

        Editable GUI metadata is intentionally excluded from this dictionary.
        """
        return {
            "record_id": self.record_id,
            "parent_id": self.parent_id,
            "created_at_utc": self.created_at_utc,
            "input_text": self.input_text,
            "output_text": self.output_text,
            "source": self.source,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "active_retrieval_brief_title": self.active_retrieval_brief_title,
            "active_retrieval_brief": self.active_retrieval_brief,
            "active_retrieval_brief_contributor_ids": self.active_retrieval_brief_contributor_ids,
        }

    def to_ragmem_block(self) -> str:
        body = json.dumps(self.to_ragmem_dict(), ensure_ascii=False, indent=2)
        return f"{RECORD_START}\n{body}\n{RECORD_END}\n"

    def to_index_dict(self) -> dict[str, Any]:
        """
        Current metadata/index view.

        This dictionary is used for:
        - .ragmeta.json per-record metadata
        - SQLite mirror rows

        It does not duplicate full input_text, output_text, or full ActiveBrief text.
        """
        return {
            "record_id": self.record_id,
            "parent_id": self.parent_id,
            "created_at_utc": self.created_at_utc,
            "source": self.source,
            "tag": self.tag,
            "retrieval_source_mode": self.retrieval_source_mode,
            "direct_recall_key": self.direct_recall_key,
            "episode_title": self.episode_title,
            "auto_keywords": self.auto_keywords,
            "user_keywords": self.user_keywords,
            "active_project_name": self.active_project_name,
            "embedded_files_snapshot": self.embedded_files_snapshot,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
        }

    def to_full_dict(self) -> dict[str, Any]:
        """
        Full in-RAM diagnostic/export view.

        This is not used for .ragmem serialization.
        """
        data = self.to_ragmem_dict()
        data.update(
            {
                "tag": self.tag,
                "retrieval_source_mode": self.retrieval_source_mode,
                "direct_recall_key": self.direct_recall_key,
                "episode_title": self.episode_title,
                "auto_keywords": self.auto_keywords,
                "user_keywords": self.user_keywords,
                "active_project_name": self.active_project_name,
                "embedded_files_snapshot": self.embedded_files_snapshot,
            }
        )
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryRecord":
        """
        Load one MemoryRecord from a .ragmem block.

        Supports both:
        - new body-only .ragmem blocks
        - older full .ragmem blocks that still contain metadata

        Current metadata from .ragmeta.json is applied later by MemoryManager.
        """
        auto_keywords_raw = data.get("auto_keywords")

        return cls(
            input_text=str(data.get("input_text", "")),
            output_text=str(data.get("output_text", "")),
            source=str(data.get("source", "")),
            parent_id=_optional_str(data.get("parent_id")),
            tag=str(data.get("tag", "Green")),
            user_keywords=list(data.get("user_keywords") or []),
            active_project_name=_optional_str(data.get("active_project_name")),
            embedded_files_snapshot=list(data.get("embedded_files_snapshot") or []),
            retrieval_source_mode=str(data.get("retrieval_source_mode", "QA")),
            direct_recall_key=str(data.get("direct_recall_key", "")),
            episode_title=str(data.get("episode_title", "") or ""),
            active_retrieval_brief_title=str(data.get("active_retrieval_brief_title", "") or ""),
            active_retrieval_brief=str(data.get("active_retrieval_brief", "") or ""),
            active_retrieval_brief_contributor_ids=list(
                data.get("active_retrieval_brief_contributor_ids") or []
            ),
            record_id=str(data.get("record_id") or uuid.uuid4().hex),
            created_at_utc=str(data.get("created_at_utc") or _utc_now()),
            auto_keywords=(
                list(auto_keywords_raw)
                if isinstance(auto_keywords_raw, list)
                else None
            ),
            input_hash=data.get("input_hash"),
            output_hash=data.get("output_hash"),
        )