"""Retrieve owner-scoped Skill candidates and load selected SKILL.md files."""

from __future__ import annotations

import re

from pathlib import Path
from typing import Any


DEFAULT_SKILLS_ROOT = Path("data/skills/MCP_CLI")
_SAFE_OWNER_SUB = re.compile(r"[A-Za-z0-9._-]+")


class SkillRetrieval:
    """Coordinate description search and deterministic Skill loading."""

    def __init__(
        self,
        *,
        owner_sub: str,
        memory_store: Any,
        skills_root: str | Path = DEFAULT_SKILLS_ROOT,
        max_candidates: int = 10,
        similarity_threshold: float = 0.2,
    ) -> None:
        if not isinstance(max_candidates, int) or max_candidates < 1:
            raise ValueError("max_candidates must be a positive integer.")
        if not 0.0 <= float(similarity_threshold) <= 1.0:
            raise ValueError(
                "similarity_threshold must be between 0 and 1."
            )

        self.max_candidates = max_candidates
        self.similarity_threshold = float(similarity_threshold)
        self._owner_sub = self._validate_owner_sub(owner_sub)
        self._memory_store = memory_store
        self._owner_skills_root = Path(skills_root) / self._owner_sub

    def search(
        self,
        query: str,
        *,
        include_tags: list[str] | None = None,
        exclude_tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return up to ten ACTIVE description candidates above threshold."""
        clean_query = self._require_text(query, "query")
        search_arguments = {
            "owner_sub": self._owner_sub,
            "query": clean_query,
            "limit": self.max_candidates,
        }
        if include_tags or exclude_tags:
            search_arguments["include_tags"] = include_tags or []
            search_arguments["exclude_tags"] = exclude_tags or []
        raw_candidates = self._memory_store.search_skills(
            **search_arguments
        )

        candidates: list[dict[str, Any]] = []
        for item in raw_candidates:
            if str(item.get("skill_status", "")).upper() != "ACTIVE":
                continue

            score = item.get("cosine_similarity")
            if score is None or float(score) < self.similarity_threshold:
                continue

            candidates.append(
                {
                    "skill_id": str(item["skill_id"]),
                    "skill_title": str(item["skill_title"]),
                    "skill_description": str(
                        item["skill_description"]
                    ),
                    "skill_tags": list(
                        item.get("skill_tags") or ["STANDARD"]
                    ),
                    "cosine_similarity": float(score),
                }
            )

        return candidates[: self.max_candidates]

    def load_skills(self, skill_ids: list[str]) -> list[str]:
        """Validate selected IDs and return their active SKILL.md contents."""
        clean_ids = self._clean_skill_ids(skill_ids)
        loaded_skills: list[str] = []

        for skill_id in clean_ids:
            data = self._memory_store.get_skill(
                owner_sub=self._owner_sub,
                skill_id=skill_id,
                active_only=True,
            )
            if data is None:
                raise ValueError(
                    f"Active Skill was not found for skill_id: {skill_id}"
                )

            skill_md_path = self._validated_skill_path(
                str(data.get("skill_md_path", ""))
            )
            loaded_skills.append(
                skill_md_path.read_text(encoding="utf-8")
            )

        return loaded_skills

    def _validated_skill_path(self, value: str) -> Path:
        skill_path = Path(self._require_text(value, "skill_md_path"))
        resolved_root = self._owner_skills_root.resolve()
        resolved_path = skill_path.resolve()

        try:
            resolved_path.relative_to(resolved_root)
        except ValueError as error:
            raise ValueError(
                "Skill path is outside the authenticated owner folder."
            ) from error

        if resolved_path.name != "SKILL.md" or not resolved_path.is_file():
            raise ValueError("Selected SKILL.md file was not found.")

        return resolved_path

    @staticmethod
    def _clean_skill_ids(skill_ids: list[str]) -> list[str]:
        if not isinstance(skill_ids, list):
            raise ValueError("skill_ids must be a list.")

        cleaned: list[str] = []
        seen: set[str] = set()

        for skill_id in skill_ids:
            value = str(skill_id or "").strip()
            if not value:
                raise ValueError(
                    "skill_ids must not contain empty values."
                )

            if value not in seen:
                cleaned.append(value)
                seen.add(value)

        return cleaned

    @staticmethod
    def _require_text(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must not be empty.")
        return value.strip()

    @staticmethod
    def _validate_owner_sub(owner_sub: str) -> str:
        owner = SkillRetrieval._require_text(owner_sub, "owner_sub")
        if (
            owner in {".", ".."}
            or _SAFE_OWNER_SUB.fullmatch(owner) is None
        ):
            raise ValueError("owner_sub contains unsafe characters.")
        return owner