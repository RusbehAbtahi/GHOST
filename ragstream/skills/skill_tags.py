"""Persist and validate dynamic GHOST Skill tags.

The owner-scoped JSON catalog is the runtime source of truth for allowed Skill
categories. SQLite remains only a derivative retrieval index.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import sqlite3
import tempfile

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, TextIO


STANDARD_SKILL_TAG = "STANDARD"
DEFAULT_SKILL_TAG_SETTINGS_ROOT = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "mcp"
    / "skill_tag_settings"
)
DEFAULT_SKILL_TAG_CATALOG_PATH = Path(__file__).with_name(
    "default_skill_tag_catalog.json"
)
_SAFE_SKILL_TAG = re.compile(r"[A-Z][A-Z0-9_-]*")
_SAFE_OWNER_SUB = re.compile(r"[A-Za-z0-9._-]+")


class SkillTagCatalogError(ValueError):
    """Raised when Skill tag settings or persisted catalog state is invalid."""


class SkillTagCatalog:
    """Read and atomically update one owner's Skill tag catalog."""

    def __init__(
        self,
        settings_root: str | Path = DEFAULT_SKILL_TAG_SETTINGS_ROOT,
        default_catalog_path: str | Path = DEFAULT_SKILL_TAG_CATALOG_PATH,
    ) -> None:
        self.settings_root = Path(settings_root)
        self.default_catalog_path = Path(default_catalog_path)

    def show(self, owner_sub: str) -> dict[str, list[str]]:
        """Return the current catalog, creating approved defaults if absent."""
        owner = self._validate_owner_sub(owner_sub)
        with self._owner_lock(owner):
            return {"skill_tags": list(self._read_or_create_unlocked(owner))}

    def tags(self, owner_sub: str) -> list[str]:
        """Return the current allowed Skill tags for one owner."""
        return self.show(owner_sub)["skill_tags"]

    def add(self, owner_sub: str, tag: str) -> tuple[list[str], bool]:
        """Add one normalized tag if absent and return the resulting catalog."""
        owner = self._validate_owner_sub(owner_sub)
        clean_tag = _normalize_tag(tag, "tag")
        with self._owner_lock(owner):
            tags = self._read_or_create_unlocked(owner)
            if clean_tag in tags:
                return list(tags), False
            tags.append(clean_tag)
            self._write_unlocked(owner, tags)
            return list(tags), True

    def remove(self, owner_sub: str, tag: str) -> tuple[list[str], bool]:
        """Remove one non-default tag after callers have checked Skill usage."""
        owner = self._validate_owner_sub(owner_sub)
        clean_tag = _normalize_tag(tag, "tag")
        if clean_tag == STANDARD_SKILL_TAG:
            raise SkillTagCatalogError(
                "STANDARD is the required default Skill tag and cannot be removed"
            )
        with self._owner_lock(owner):
            tags = self._read_or_create_unlocked(owner)
            if clean_tag not in tags:
                raise SkillTagCatalogError(
                    f"Skill tag is not defined: {clean_tag}"
                )
            tags.remove(clean_tag)
            self._write_unlocked(owner, tags)
            return list(tags), True

    def settings_path(self, owner_sub: str) -> Path:
        """Return the deterministic owner-scoped JSON catalog path."""
        owner = self._validate_owner_sub(owner_sub)
        return self.settings_root / owner / "skill_tags.json"

    @staticmethod
    def _validate_owner_sub(owner_sub: str) -> str:
        owner = str(owner_sub or "").strip()
        if (
            owner in {"", ".", ".."}
            or _SAFE_OWNER_SUB.fullmatch(owner) is None
        ):
            raise SkillTagCatalogError(
                "owner_sub must contain only letters, numbers, '.', '_' or '-'"
            )
        return owner

    @contextmanager
    def _owner_lock(self, owner: str) -> Iterator[None]:
        owner_root = self.settings_root / owner
        owner_root.mkdir(parents=True, exist_ok=True)
        lock_path = owner_root / ".skill_tags.lock"
        lock_file: TextIO = lock_path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()

    def _read_or_create_unlocked(self, owner: str) -> list[str]:
        path = self.settings_root / owner / "skill_tags.json"
        if not path.exists():
            tags = self._read_catalog_file(self.default_catalog_path, "default")
            self._write_unlocked(owner, tags)
            return tags
        return self._read_catalog_file(path, "persisted")

    @staticmethod
    def _read_catalog_file(path: Path, source: str) -> list[str]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SkillTagCatalogError(
                f"{source} Skill tag catalog JSON is unreadable"
            ) from error
        if not isinstance(raw, Mapping) or set(raw) != {"skill_tags"}:
            raise SkillTagCatalogError(
                f"{source} Skill tag catalog must contain only skill_tags"
            )
        tags = normalize_skill_tags(
            raw["skill_tags"],
            default_to_standard=False,
        )
        if not tags:
            raise SkillTagCatalogError("Skill tag catalog must not be empty")
        if STANDARD_SKILL_TAG not in tags:
            raise SkillTagCatalogError(
                "Skill tag catalog must contain the required default tag STANDARD"
            )
        return tags

    def _write_unlocked(self, owner: str, tags: list[str]) -> None:
        clean_tags = normalize_skill_tags(tags, default_to_standard=False)
        if not clean_tags or STANDARD_SKILL_TAG not in clean_tags:
            raise SkillTagCatalogError(
                "Skill tag catalog must contain the required default tag STANDARD"
            )
        owner_root = self.settings_root / owner
        owner_root.mkdir(parents=True, exist_ok=True)
        target = owner_root / "skill_tags.json"
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=owner_root,
                prefix=".skill_tags.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                json.dump(
                    {"skill_tags": clean_tags},
                    temp_file,
                    ensure_ascii=False,
                    indent=2,
                )
                temp_file.write("\n")
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, target)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()


def _normalize_tag(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must contain only non-empty strings")
    tag = value.strip().upper()
    if _SAFE_SKILL_TAG.fullmatch(tag) is None:
        raise ValueError(f"{field_name} contains an invalid tag")
    return tag


def normalize_skill_tags(
    value: Any,
    *,
    default_to_standard: bool,
    field_name: str = "skill_tags",
    allowed_tags: list[str] | set[str] | frozenset[str] | None = None,
) -> list[str]:
    """Normalize tags and optionally validate against a runtime catalog."""
    if value is None or value == []:
        return [STANDARD_SKILL_TAG] if default_to_standard else []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")

    allowed: set[str] | None = None
    if allowed_tags is not None:
        allowed = {
            _normalize_tag(item, "allowed_tags")
            for item in allowed_tags
        }

    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        tag = _normalize_tag(item, field_name)
        if allowed is not None and tag not in allowed:
            raise ValueError(
                f"{field_name} contains undefined tag {tag}; "
                "read the current Skill tag catalog first"
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
    *,
    allowed_tags: list[str] | set[str] | frozenset[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Return valid filters and reject the same tag on both sides."""
    included = normalize_skill_tags(
        include_tags,
        default_to_standard=False,
        field_name="include_tags",
        allowed_tags=allowed_tags,
    )
    excluded = normalize_skill_tags(
        exclude_tags,
        default_to_standard=False,
        field_name="exclude_tags",
        allowed_tags=allowed_tags,
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
