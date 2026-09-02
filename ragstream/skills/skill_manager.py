"""Coordinate Skill artifacts, Memory persistence, lifecycle, and retrieval."""

from __future__ import annotations

import re
import shutil
import uuid

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ragstream.skills.skill import EXCLUDED_SKILL_STATUS, Skill
from ragstream.skills.skill_creator import SkillCreator
from ragstream.skills.skill_retrieval import SkillRetrieval


DEFAULT_SKILLS_ROOT = Path("data/skills/MCP_CLI")
_SAFE_PATH_PART = re.compile(r"[A-Za-z0-9._-]+")


class SkillManager:
    """Coordinate deterministic operations with request-scoped state."""

    def __init__(
        self,
        *,
        owner_sub: str,
        current_skill: Skill | None = None,
        affected_skill_ids: list[str] | None = None,
        skills_root: str | Path = DEFAULT_SKILLS_ROOT,
        memory_store: Any | None = None,
    ) -> None:
        self.skills: dict[str, Skill] = {}
        self.selected_skill_ids: list[str] = []
        self.current_skill: Skill | None = current_skill
        self.affected_skill_ids: list[str] = list(
            affected_skill_ids or []
        )

        self._owner_sub = self._validate_path_part(
            owner_sub,
            "owner_sub",
        )
        self._skills_root = Path(skills_root)
        self._owner_skills_root = self._skills_root / self._owner_sub
        self._creator = SkillCreator()

        if memory_store is None:
            from ragstream.memory.mcp_skill_memory_store import (
                McpSkillMemoryStore,
            )

            memory_store = McpSkillMemoryStore()

        self._memory_store = memory_store
        self._retrieval = SkillRetrieval(
            owner_sub=self._owner_sub,
            memory_store=self._memory_store,
            skills_root=self._skills_root,
        )

    def create_skill_artifact(
        self,
        skill: Skill,
    ) -> tuple[Skill, bool]:
        """Assign GHOST identity/path and delegate SKILL.md creation."""
        if not isinstance(skill, Skill):
            raise TypeError("skill must be a Skill instance.")

        input_errors = skill.validate_creation_input()
        if input_errors:
            raise ValueError(
                "Invalid Skill creation input: "
                + " ".join(input_errors)
            )

        if not skill.skill_id.strip():
            skill.skill_id = uuid.uuid4().hex

        self._validate_path_part(skill.skill_id, "skill_id")
        folder_name = self._validate_path_part(
            skill.skill_name,
            "skill_name",
        )

        if skill.folder_path:
            folder_path = self._validated_owner_path(
                skill.folder_path
            )
        else:
            created_at = datetime.now(timezone.utc).strftime(
                "%Y_%m_%d_%H_%M_%S_%f"
            )
            folder_path = (
                self._owner_skills_root
                / f"{created_at}_{folder_name}"
            )

        skill.folder_path = str(folder_path)
        self.current_skill = skill

        created_skill, success = self._creator.create_skill(skill)
        if success:
            self.skills[created_skill.skill_id] = created_skill
        else:
            self.current_skill = None

        return created_skill, success

    def persist_skill_memory(
        self,
        skill: Skill,
        replacing_skill_ids: list[str] | None = None,
    ) -> Skill:
        """Persist one created Skill through the Memory architecture."""
        if not isinstance(skill, Skill):
            raise TypeError("skill must be a Skill instance.")

        if not Path(skill.skill_md_path).is_file():
            raise ValueError(
                "The Skill artifact must exist before Memory persistence."
            )

        skill.ragmem_title = (
            skill.ragmem_title.strip()
            or skill.skill_title.strip()
        )
        skill.ragmem_description = (
            skill.ragmem_description.strip()
            or skill.skill_description.strip()
        )
        skill.ragmem_recall_key = (
            skill.ragmem_recall_key.strip()
            or skill.skill_id
        )

        clean_replacing_ids = self._clean_skill_ids(
            replacing_skill_ids or []
        )
        try:
            result = self._memory_store.save_skill(
                owner_sub=self._owner_sub,
                skill_data=self._skill_memory_data(skill),
                replacing_skill_ids=clean_replacing_ids,
            )
        except Exception:
            self.discard_skill_artifact(skill)
            raise

        skill.ragmem_record_id = str(result["record_id"])
        skill.ragmem_recall_key = str(result["recall_key"])

        errors = skill.validate()
        if errors:
            raise ValueError(
                "Invalid persisted Skill: " + " ".join(errors)
            )

        self.skills[skill.skill_id] = skill
        self.current_skill = None
        return skill

    def rollback_persisted_skill(self, skill: Skill) -> None:
        """Remove a failed replacement from Memory and the filesystem."""
        if not isinstance(skill, Skill):
            raise TypeError("skill must be a Skill instance.")

        self._memory_store.delete_skill(
            owner_sub=self._owner_sub,
            skill_id=skill.skill_id,
        )
        self.discard_skill_artifact(skill)

    def discard_skill_artifact(self, skill: Skill) -> None:
        """Remove one exact request-owned artifact during rollback."""
        if not isinstance(skill, Skill):
            raise TypeError("skill must be a Skill instance.")

        tracked_skill = self.skills.get(skill.skill_id)
        if tracked_skill is not skill and self.current_skill is not skill:
            raise ValueError(
                "Only an artifact tracked by this manager may be discarded."
            )

        folder_path = self._validated_owner_path(skill.folder_path)
        skill_md_path = Path(skill.skill_md_path)
        if (
            skill_md_path.name != "SKILL.md"
            or skill_md_path.parent.resolve() != folder_path.resolve()
        ):
            raise ValueError("Skill artifact paths are inconsistent.")

        if folder_path.exists():
            if not folder_path.is_dir():
                raise ValueError("Skill artifact folder is not a directory.")
            shutil.rmtree(folder_path)

        self.skills.pop(skill.skill_id, None)
        if self.current_skill is skill:
            self.current_skill = None

    def archive_replaced_skills(
        self,
        affected_skill_ids: list[str],
        replacement_skill_id: str = "",
    ) -> None:
        """Archive artifacts and mark Memory episodes EXCLUDED."""
        clean_ids = self._clean_skill_ids(affected_skill_ids)
        if not clean_ids:
            self.affected_skill_ids = []
            return

        clean_replacement_id = ""
        if replacement_skill_id:
            clean_replacement_id = self._validate_path_part(
                replacement_skill_id,
                "replacement_skill_id",
            )

        archive_date = datetime.now(timezone.utc).date().isoformat()
        archive_root = self._owner_skills_root / "Archive"
        planned: list[dict[str, Any]] = []

        for skill_id in clean_ids:
            stored = self._memory_store.get_skill(
                owner_sub=self._owner_sub,
                skill_id=skill_id,
                active_only=True,
            )
            if stored is None:
                raise ValueError(
                    f"Active Skill was not found for skill_id: {skill_id}"
                )

            source = self._validated_owner_path(
                str(stored.get("folder_path", ""))
            )
            if not source.is_dir():
                raise ValueError(
                    f"Skill folder was not found for skill_id: {skill_id}"
                )

            destination = (
                archive_root / f"{source.name}_{archive_date}"
            )
            if destination.exists():
                raise FileExistsError(
                    f"Skill archive already exists: {destination}"
                )

            notes = list(stored.get("notes", []))
            notes.append(
                {
                    "type": "replacement",
                    "archived_at_utc": archive_date,
                    "archived_path": str(destination),
                }
            )
            planned.append(
                {
                    "skill_id": skill_id,
                    "source": source,
                    "destination": destination,
                    "folder_path": str(destination),
                    "skill_md_path": str(
                        destination / "SKILL.md"
                    ),
                    "notes": notes,
                }
            )

        moved: list[dict[str, Any]] = []
        try:
            archive_root.mkdir(parents=True, exist_ok=True)

            for item in planned:
                shutil.move(
                    str(item["source"]),
                    str(item["destination"]),
                )
                moved.append(item)

            if clean_replacement_id:
                self._memory_store.finalize_replacement(
                    owner_sub=self._owner_sub,
                    replacement_skill_id=clean_replacement_id,
                    archived_skills=planned,
                )
            else:
                self._memory_store.exclude_skills(
                    owner_sub=self._owner_sub,
                    archived_skills=planned,
                )
        except Exception:
            for item in reversed(moved):
                if Path(item["destination"]).exists():
                    shutil.move(
                        str(item["destination"]),
                        str(item["source"]),
                    )
            raise

        for item in planned:
            skill = self.skills.get(str(item["skill_id"]))
            if skill is None:
                continue

            skill.folder_path = str(item["folder_path"])
            skill.skill_md_path = str(item["skill_md_path"])
            skill.skill_status = EXCLUDED_SKILL_STATUS
            skill.notes = list(item["notes"])

        self.affected_skill_ids = clean_ids

    def retrieve_candidates(
        self,
        query: str,
        *,
        include_tags: list[str] | None = None,
        exclude_tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return owner-scoped Skill description candidates."""
        return self._retrieval.search(
            query,
            include_tags=include_tags,
            exclude_tags=exclude_tags,
        )

    def load_selected_skills(
        self,
        skill_ids: list[str],
    ) -> list[str]:
        """Load validated active SKILL.md instructions for selected IDs."""
        clean_ids = self._clean_skill_ids(skill_ids)
        loaded = self._retrieval.load_skills(clean_ids)
        self.selected_skill_ids = clean_ids
        return loaded

    def _skill_memory_data(
        self,
        skill: Skill,
    ) -> dict[str, Any]:
        return {
            "skill_id": skill.skill_id,
            "skill_name": skill.skill_name,
            "skill_title": skill.skill_title,
            "skill_description": skill.skill_description,
            "skill_tags": list(skill.skill_tags),
            "folder_path": skill.folder_path,
            "skill_md_path": skill.skill_md_path,
            "ragmem_recall_key": skill.ragmem_recall_key,
            "ragmem_title": skill.ragmem_title,
            "ragmem_description": skill.ragmem_description,
            "ragmem_q": skill.ragmem_q,
            "ragmem_a": skill.ragmem_a,
            "skill_status": skill.skill_status,
            "notes": list(skill.notes),
        }

    def _validated_owner_path(self, value: str) -> Path:
        path = Path(value)
        resolved_root = self._owner_skills_root.resolve()
        resolved_path = path.resolve()

        try:
            resolved_path.relative_to(resolved_root)
        except ValueError as error:
            raise ValueError(
                "Skill path is outside the authenticated owner folder."
            ) from error

        return path

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

            SkillManager._validate_path_part(value, "skill_id")
            if value not in seen:
                cleaned.append(value)
                seen.add(value)

        return cleaned

    @staticmethod
    def _validate_path_part(value: str, field_name: str) -> str:
        clean_value = str(value or "").strip()
        if (
            clean_value in {".", ".."}
            or _SAFE_PATH_PART.fullmatch(clean_value) is None
        ):
            raise ValueError(
                f"{field_name} must contain only letters, numbers, '.', "
                "'_' or '-'."
            )

        return clean_value