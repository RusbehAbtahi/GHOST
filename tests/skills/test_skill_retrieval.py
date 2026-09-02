from pathlib import Path
from typing import Any

import pytest

from ragstream.skills.skill_retrieval import SkillRetrieval


class FakeMemoryStore:
    def __init__(
        self,
        *,
        candidates: list[dict[str, Any]] | None = None,
        skills: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.candidates = list(candidates or [])
        self.skills = dict(skills or {})

    def search_skills(
        self,
        *,
        owner_sub: str,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        assert owner_sub == "owner-1"
        assert query
        return self.candidates[:limit]

    def get_skill(
        self,
        *,
        owner_sub: str,
        skill_id: str,
        active_only: bool,
    ) -> dict[str, Any] | None:
        assert owner_sub == "owner-1"

        item = self.skills.get(skill_id)
        if item is None:
            return None
        if (
            active_only
            and item.get("skill_status") != "ACTIVE"
        ):
            return None

        return item


def test_search_applies_status_threshold_and_limit(
    tmp_path: Path,
) -> None:
    store = FakeMemoryStore(
        candidates=[
            {
                "skill_id": "skill-a",
                "skill_title": "Relevant Skill",
                "skill_description": "Relevant",
                "skill_status": "ACTIVE",
                "cosine_similarity": 0.8,
            },
            {
                "skill_id": "skill-b",
                "skill_title": "Excluded Skill",
                "skill_description": "Excluded",
                "skill_status": "EXCLUDED",
                "cosine_similarity": 0.9,
            },
            {
                "skill_id": "skill-c",
                "skill_title": "Weak Skill",
                "skill_description": "Weak",
                "skill_status": "ACTIVE",
                "cosine_similarity": 0.1,
            },
        ]
    )
    retrieval = SkillRetrieval(
        owner_sub="owner-1",
        memory_store=store,
        skills_root=tmp_path,
    )

    assert retrieval.search("find folders") == [
        {
            "skill_id": "skill-a",
            "skill_title": "Relevant Skill",
            "skill_description": "Relevant",
            "skill_tags": ["STANDARD"],
            "cosine_similarity": 0.8,
        }
    ]


def test_load_skills_reads_only_valid_owner_skill_path(
    tmp_path: Path,
) -> None:
    skill_path = (
        tmp_path
        / "owner-1"
        / "skill-a"
        / "SKILL.md"
    )
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        "instructions",
        encoding="utf-8",
    )

    store = FakeMemoryStore(
        skills={
            "skill-a": {
                "skill_status": "ACTIVE",
                "skill_md_path": str(skill_path),
            }
        }
    )
    retrieval = SkillRetrieval(
        owner_sub="owner-1",
        memory_store=store,
        skills_root=tmp_path,
    )

    assert retrieval.load_skills(
        ["skill-a", "skill-a"]
    ) == ["instructions"]


def test_load_skills_rejects_unknown_id(
    tmp_path: Path,
) -> None:
    retrieval = SkillRetrieval(
        owner_sub="owner-1",
        memory_store=FakeMemoryStore(),
        skills_root=tmp_path,
    )

    with pytest.raises(
        ValueError,
        match="Active Skill was not found",
    ):
        retrieval.load_skills(["missing"])