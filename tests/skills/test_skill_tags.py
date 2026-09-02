"""Tests for controlled Skill tags and deterministic SQLite filtering."""

from __future__ import annotations

from pathlib import Path

import pytest

from ragstream.skills.skill_tags import (
    SkillTagIndex,
    normalize_skill_tag_filters,
    normalize_skill_tags,
)


def _tag_index(tmp_path: Path, domain: str = "CLI") -> SkillTagIndex:
    index = SkillTagIndex(
        sqlite_path=tmp_path / "skill_tags.sqlite3",
        skill_domain=domain,
    )
    index.replace_owner_records(
        owner_sub="owner-1",
        record_tags={
            "standard-only": ["STANDARD"],
            "ghost-only": ["GHOST"],
            "both": ["STANDARD", "GHOST"],
        },
    )
    return index


def _filter(
    index: SkillTagIndex,
    *,
    include_tags: list[str] | None = None,
    exclude_tags: list[str] | None = None,
    owner_sub: str = "owner-1",
) -> list[str]:
    return index.filter_record_ids(
        owner_sub=owner_sub,
        candidate_record_ids=[
            "both",
            "standard-only",
            "ghost-only",
        ],
        include_tags=list(include_tags or []),
        exclude_tags=list(exclude_tags or []),
    )


def test_missing_skill_tags_default_to_standard() -> None:
    assert normalize_skill_tags(
        None,
        default_to_standard=True,
    ) == ["STANDARD"]
    assert normalize_skill_tags(
        [],
        default_to_standard=True,
    ) == ["STANDARD"]


def test_skill_tags_are_controlled_normalized_and_unique() -> None:
    assert normalize_skill_tags(
        [" ghost ", "STANDARD", "ghost"],
        default_to_standard=True,
    ) == ["GHOST", "STANDARD"]

    with pytest.raises(ValueError, match="undefined tag CUSTOM"):
        normalize_skill_tags(
            ["CUSTOM"],
            default_to_standard=True,
        )


def test_filter_rejects_include_exclude_overlap() -> None:
    with pytest.raises(
        ValueError,
        match="same Skill tag cannot be included and excluded",
    ):
        normalize_skill_tag_filters(["GHOST"], ["ghost"])


@pytest.mark.parametrize(
    ("include_tags", "exclude_tags", "expected"),
    [
        (
            [],
            [],
            ["both", "standard-only", "ghost-only"],
        ),
        (
            ["GHOST"],
            [],
            ["both", "ghost-only"],
        ),
        (
            ["STANDARD"],
            [],
            ["both", "standard-only"],
        ),
        (
            ["GHOST", "STANDARD"],
            [],
            ["both", "standard-only", "ghost-only"],
        ),
        (
            [],
            ["GHOST"],
            ["standard-only"],
        ),
        (
            ["GHOST", "STANDARD"],
            ["GHOST"],
            ["standard-only"],
        ),
    ],
)
def test_sqlite_filters_before_semantic_candidates(
    tmp_path: Path,
    include_tags: list[str],
    exclude_tags: list[str],
    expected: list[str],
) -> None:
    index = _tag_index(tmp_path)

    if set(include_tags).intersection(exclude_tags):
        with pytest.raises(ValueError):
            _filter(
                index,
                include_tags=include_tags,
                exclude_tags=exclude_tags,
            )
