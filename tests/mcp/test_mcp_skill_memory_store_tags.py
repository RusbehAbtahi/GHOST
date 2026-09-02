"""Integration tests for SQLite filtering before Skill vector search."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ragstream.memory.mcp_skill_memory_store import McpSkillMemoryStore
from ragstream.memory.memory_record import MemoryRecord


class RecordingVectors:
    """Return deterministic hits and retain each allowed Record-ID scope."""

    def __init__(self) -> None:
        self.candidate_scopes: list[list[str]] = []

    def upsert_description(self, **_kwargs: Any) -> None:
        return None

    def search_descriptions(
        self,
        *,
        owner_sub: str,
        query_description: str,
        candidate_record_ids: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        assert owner_sub == "owner-1"
        assert query_description
        self.candidate_scopes.append(list(candidate_record_ids))
        return [
            {
                "record_id": record_id,
                "cosine_similarity": 0.9,
            }
            for record_id in candidate_record_ids[:limit]
        ]

    def delete_records(self, _record_ids: list[str]) -> None:
        return None


class FakeManager:
    """Provide the MemoryManager surface used by Skill persistence."""

    def __init__(self, tmp_path: Path) -> None:
        self.file_id = "file-1"
        self.owner_sub = "owner-1"
        self.records: list[MemoryRecord] = []
        self.ragmem_path = tmp_path / "CLI_SKILL.ragmem"
        self.ragmem_path.touch()

    def save_metainfo(self) -> None:
        return None

    def refresh_sqlite_index(self) -> None:
        return None


def _skill_data(
    skill_id: str,
    *,
    skill_tags: list[str] | None = None,
) -> dict[str, Any]:
    folder = f"/skills/owner-1/{skill_id}"
    data: dict[str, Any] = {
        "skill_id": skill_id,
        "skill_name": skill_id,
        "skill_title": skill_id,
        "skill_description": f"Description for {skill_id}.",
        "folder_path": folder,
        "skill_md_path": f"{folder}/SKILL.md",
        "ragmem_recall_key": skill_id,
        "ragmem_title": skill_id,
        "ragmem_description": f"Description for {skill_id}.",
        "ragmem_q": f"{folder}/SKILL.md",
        "ragmem_a": f'{{"skill_id": "{skill_id}"}}',
        "skill_status": "ACTIVE",
        "notes": [],
    }
    if skill_tags is not None:
        data["skill_tags"] = skill_tags
    return data


def _store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[McpSkillMemoryStore, RecordingVectors]:
    vectors = RecordingVectors()
    store = McpSkillMemoryStore(
        memory_root=tmp_path,
        sqlite_path=tmp_path / "memory_index.sqlite3",
        description_vector_store=vectors,  # type: ignore[arg-type]
    )
    manager = FakeManager(tmp_path)
    monkeypatch.setattr(
        store,
        "_load_or_create_manager",
        lambda _owner: manager,
    )
    monkeypatch.setattr(
        store,
        "_load_manager",
        lambda _owner: manager,
    )
    store.save_skill(
        owner_sub="owner-1",
        skill_data=_skill_data("standard"),
    )
    store.save_skill(
        owner_sub="owner-1",
        skill_data=_skill_data("ghost", skill_tags=["GHOST"]),
    )
    return store, vectors


def test_no_filter_defaults_legacy_skill_to_standard_and_searches_all(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, vectors = _store(tmp_path, monkeypatch)

    candidates = store.search_skills(
        owner_sub="owner-1",
        query="skill",
        limit=10,
    )

    assert [item["skill_tags"] for item in candidates] == [
        ["STANDARD"],
        ["GHOST"],
    ]
    assert len(vectors.candidate_scopes[-1]) == 2


def test_sqlite_tag_filter_restricts_scope_before_vector_search(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, vectors = _store(tmp_path, monkeypatch)

    ghost_candidates = store.search_skills(
        owner_sub="owner-1",
        query="skill",
        limit=10,
        include_tags=["GHOST"],
        exclude_tags=[],
    )
    assert [item["skill_id"] for item in ghost_candidates] == ["ghost"]
    assert len(vectors.candidate_scopes[-1]) == 1

    standard_candidates = store.search_skills(
        owner_sub="owner-1",
        query="skill",
        limit=10,
        include_tags=[],
        exclude_tags=["GHOST"],
    )
    assert [item["skill_id"] for item in standard_candidates] == [
        "standard"
    ]
    assert len(vectors.candidate_scopes[-1]) == 1
