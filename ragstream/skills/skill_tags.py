"""Validate controlled Skill tags and filter Skill records through SQLite.

Skill tags are categorical retrieval controls, separate from ordinary Memory tags.
The durable values live in Skill RagMeta metadata; SkillTagIndex maintains the
owner- and domain-scoped SQLite projection used before vector retrieval.

Main classes:
    SkillTagIndex:
        Rebuilds and queries the deterministic SQLite Skill-tag projection.

Main functions:
    normalize_skill_tags():
        Normalizes and validates tags against the fixed vocabulary.
    normalize_skill_tag_filters():
        Validates include/exclude filters and rejects contradictions.
"""

from __future__ import annotations

import re
import sqlite3

from pathlib import Path
from typing import Any


STANDARD_SKILL_TAG = "STANDARD"
GHOST_SKILL_TAG = "GHOST"
ALLOWED_SKILL_TAGS = frozenset(
    {STANDARD_SKILL_TAG, GHOST_SKILL_TAG}
)
_SAFE_SKILL_TAG = re.compile(r"[A-Z][A-Z0-9_-]*")


def normalize_skill_tags(
    value: Any,
    *,
    default_to_standard: bool,
    field_name: str = "skill_tags",
) -> list[str]:
    """Return unique controlled tags in stable order."""
    if value is None or value == []:
        return [STANDARD_SKILL_TAG] if default_to_standard else []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")

    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(
                f"{field_name} must contain only non-empty strings"
            )

        tag = item.strip().upper()
        if _SAFE_SKILL_TAG.fullmatch(tag) is None:
            raise ValueError(f"{field_name} contains an invalid tag")
        if tag not in ALLOWED_SKILL_TAGS:
            allowed = ", ".join(sorted(ALLOWED_SKILL_TAGS))
            raise ValueError(
                f"{field_name} contains undefined tag {tag}; "
                f"allowed tags: {allowed}"
            )
        if tag not in seen:
            normalized.append(tag)
            seen.add(tag)

    if not normalized and default_to_standard:
        return [STANDARD_SKILL_TAG]
    return normalized


def normalize_skill_tag_filters(
    include_tags: Any,
    exclude_tags: Any,
) -> tuple[list[str], list[str]]:
    """Return valid filters and reject the same tag on both sides."""
    included = normalize_skill_tags(
        include_tags,
        default_to_standard=False,
        field_name="include_tags",
    )
    excluded = normalize_skill_tags(
        exclude_tags,
        default_to_standard=False,
        field_name="exclude_tags",
    )
    overlap = sorted(set(included).intersection(excluded))
    if overlap:
        raise ValueError(
            "the same Skill tag cannot be included and excluded: "
            + ", ".join(overlap)
        )
    return included, excluded


class SkillTagIndex:
    """Maintain the deterministic SQLite projection of Skill tags."""

    def __init__(
        self,
        *,
        sqlite_path: str | Path,
        skill_domain: str,
    ) -> None:
        self._sqlite_path = Path(sqlite_path)
        self._skill_domain = str(skill_domain).strip()
        if not self._skill_domain:
            raise ValueError("skill_domain must not be empty")
        self._initialize()

    def replace_owner_records(
        self,
        *,
        owner_sub: str,
        record_tags: dict[str, list[str]],
    ) -> None:
        """Replace one owner's domain rows from current RagMeta truth."""
        owner = str(owner_sub).strip()
        if not owner:
            raise ValueError("owner_sub must not be empty")

        rows: list[tuple[str, str, str, str]] = []
        for record_id, tags in record_tags.items():
            clean_record_id = str(record_id).strip()
            if not clean_record_id:
                raise ValueError("record_id must not be empty")
            for tag in normalize_skill_tags(
                tags,
                default_to_standard=True,
            ):
                rows.append(
                    (
                        self._skill_domain,
                        owner,
                        clean_record_id,
                        tag,
                    )
                )

        with sqlite3.connect(self._sqlite_path) as connection:
            connection.execute(
                """
                DELETE FROM mcp_skill_tags
                WHERE skill_domain = ? AND owner_sub = ?
                """,
                (self._skill_domain, owner),
            )
            connection.executemany(
                """
                INSERT INTO mcp_skill_tags (
                    skill_domain,
                    owner_sub,
                    record_id,
                    tag_name
                ) VALUES (?, ?, ?, ?)
                """,
                rows,
            )

    def filter_record_ids(
        self,
        *,
        owner_sub: str,
        candidate_record_ids: list[str],
        include_tags: list[str],
        exclude_tags: list[str],
    ) -> list[str]:
        """Apply deterministic tag filters and preserve candidate order."""
        if not candidate_record_ids:
            return []

        included, excluded = normalize_skill_tag_filters(
            include_tags,
            exclude_tags,
        )
        placeholders = ", ".join("?" for _ in candidate_record_ids)
        parameters: list[str] = [
            self._skill_domain,
            owner_sub,
            *candidate_record_ids,
        ]
        sql = (
            "SELECT DISTINCT base.record_id "
            "FROM mcp_skill_tags AS base "
            "WHERE base.skill_domain = ? "
            "AND base.owner_sub = ? "
            f"AND base.record_id IN ({placeholders}) "
        )

        if included:
            tag_placeholders = ", ".join("?" for _ in included)
            sql += (
                "AND EXISTS ("
                "SELECT 1 FROM mcp_skill_tags AS wanted "
                "WHERE wanted.skill_domain = base.skill_domain "
                "AND wanted.owner_sub = base.owner_sub "
                "AND wanted.record_id = base.record_id "
                f"AND wanted.tag_name IN ({tag_placeholders})"
                ") "
            )
            parameters.extend(included)

        if excluded:
            tag_placeholders = ", ".join("?" for _ in excluded)
            sql += (
                "AND NOT EXISTS ("
                "SELECT 1 FROM mcp_skill_tags AS blocked "
                "WHERE blocked.skill_domain = base.skill_domain "
                "AND blocked.owner_sub = base.owner_sub "
                "AND blocked.record_id = base.record_id "
                f"AND blocked.tag_name IN ({tag_placeholders})"
                ") "
            )
            parameters.extend(excluded)

        with sqlite3.connect(self._sqlite_path) as connection:
            rows = connection.execute(sql, parameters).fetchall()

        allowed = {str(row[0]) for row in rows}
        return [
            record_id
            for record_id in candidate_record_ids
            if record_id in allowed
        ]

    def _initialize(self) -> None:
        self._sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._sqlite_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS mcp_skill_tags (
                    skill_domain TEXT NOT NULL,
                    owner_sub TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    tag_name TEXT NOT NULL,
                    PRIMARY KEY (
                        skill_domain,
                        owner_sub,
                        record_id,
                        tag_name
                    )
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_mcp_skill_tags_lookup
                ON mcp_skill_tags (
                    skill_domain,
                    owner_sub,
                    tag_name,
                    record_id
                )
                """
            )
