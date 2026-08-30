"""Create the physical folder and SKILL.md artifact for one Skill."""

from __future__ import annotations

import json
import shutil

from pathlib import Path

from ragstream.skills.skill import ACTIVE_SKILL_STATUS, Skill


class SkillCreator:
    """Create one standard Skill artifact without holding mutable state."""

    def create_skill(self, skill: Skill) -> tuple[Skill, bool]:
        """Create the Skill folder and write YAML plus Markdown to SKILL.md."""
        if not self._has_required_input(skill):
            return skill, False

        folder_path = Path(skill.folder_path)
        skill_md_path = folder_path / "SKILL.md"
        metadata = dict(skill.yaml_metadata)
        metadata.setdefault("name", skill.skill_name.strip())
        metadata.setdefault(
            "description",
            skill.skill_description.strip(),
        )

        folder_created = False
        try:
            folder_path.mkdir(parents=True, exist_ok=False)
            folder_created = True
            skill_md_path.write_text(
                self._build_skill_md(
                    metadata=metadata,
                    title=skill.skill_title,
                    instructions=skill.instruction_text,
                ),
                encoding="utf-8",
            )
        except OSError:
            if folder_created and folder_path.exists():
                shutil.rmtree(folder_path)
            return skill, False

        skill.folder_path = str(folder_path)
        skill.skill_md_path = str(skill_md_path)
        skill.yaml_metadata = metadata
        skill.ragmem_q = str(skill_md_path)
        skill.ragmem_a = json.dumps(
            {
                "skill_id": skill.skill_id,
                "skill_name": skill.skill_name,
            },
            ensure_ascii=False,
        )
        skill.skill_status = ACTIVE_SKILL_STATUS
        return skill, True

    @staticmethod
    def _has_required_input(skill: Skill) -> bool:
        if not isinstance(skill, Skill):
            return False

        required_values = (
            skill.skill_id,
            skill.skill_name,
            skill.skill_title,
            skill.skill_description,
            skill.folder_path,
            skill.instruction_text,
        )
        return all(
            isinstance(value, str) and bool(value.strip())
            for value in required_values
        ) and isinstance(skill.yaml_metadata, dict)

    @staticmethod
    def _build_skill_md(
        *,
        metadata: dict[str, object],
        title: str,
        instructions: str,
    ) -> str:
        # JSON scalar/object syntax is valid YAML. Rendering it directly keeps
        # this module deterministic and avoids adding another dependency.
        yaml_lines = [
            f"{json.dumps(str(key), ensure_ascii=False)}: "
            f"{json.dumps(value, ensure_ascii=False)}"
            for key, value in metadata.items()
        ]
        yaml_block = "\n".join(yaml_lines)

        return (
            f"---\n{yaml_block}\n---\n\n"
            f"# {title.strip()}\n\n"
            f"{instructions.strip()}\n"
        )