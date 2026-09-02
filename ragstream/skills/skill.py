"""Represent one MCP CLI Skill and validate its internal coherence."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ragstream.skills.skill_tags import (
    STANDARD_SKILL_TAG,
    normalize_skill_tags,
)


ACTIVE_SKILL_STATUS = "ACTIVE"
EXCLUDED_SKILL_STATUS = "EXCLUDED"
MAX_INSTRUCTION_TOKENS = 10_000
VALID_SKILL_STATUSES = {
    ACTIVE_SKILL_STATUS,
    EXCLUDED_SKILL_STATUS,
}


@dataclass(slots=True)
class Skill:
    """Hold the artifact, Memory identity, and lifecycle data of one Skill."""

    skill_id: str = ""
    skill_name: str = ""
    skill_title: str = ""
    skill_description: str = ""
    skill_tags: list[str] = field(
        default_factory=lambda: [STANDARD_SKILL_TAG]
    )

    folder_path: str = ""
    skill_md_path: str = ""

    yaml_metadata: dict[str, Any] = field(default_factory=dict)
    instruction_text: str = ""

    ragmem_record_id: str = ""
    ragmem_recall_key: str = ""
    ragmem_title: str = ""
    ragmem_description: str = ""
    ragmem_q: str = ""
    ragmem_a: str = ""

    skill_status: str = ""
    notes: list[Any] = field(default_factory=list)

    def validate_creation_input(self) -> list[str]:
        """Return errors for fields required before artifact creation."""
        errors: list[str] = []
        required_text = {
            "skill_name": self.skill_name,
            "skill_title": self.skill_title,
            "skill_description": self.skill_description,
            "instruction_text": self.instruction_text,
        }
        for field_name, value in required_text.items():
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{field_name} must not be empty.")

        if not isinstance(self.yaml_metadata, dict):
            errors.append("yaml_metadata must be a dictionary.")
        if not isinstance(self.notes, list):
            errors.append("notes must be a list.")
        try:
            normalized_tags = normalize_skill_tags(
                self.skill_tags,
                default_to_standard=True,
            )
            if self.skill_tags != normalized_tags:
                errors.append("skill_tags must be normalized.")
        except ValueError as error:
            errors.append(str(error) + ".")

        if (
            self.instruction_text
            and _instruction_token_count(self.instruction_text)
            > MAX_INSTRUCTION_TOKENS
        ):
            errors.append(
                "instruction_text must not exceed 10000 tokens."
            )

        return errors

    def validate(self) -> list[str]:
        """Return validation errors without modifying the Skill."""
        errors = self.validate_creation_input()

        required_text = {
            "skill_id": self.skill_id,
            "folder_path": self.folder_path,
            "skill_md_path": self.skill_md_path,
            "ragmem_record_id": self.ragmem_record_id,
            "ragmem_recall_key": self.ragmem_recall_key,
            "ragmem_title": self.ragmem_title,
            "ragmem_description": self.ragmem_description,
            "ragmem_q": self.ragmem_q,
            "ragmem_a": self.ragmem_a,
            "skill_status": self.skill_status,
        }
        for field_name, value in required_text.items():
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{field_name} must not be empty.")

        status = str(self.skill_status or "").strip().upper()
        if status and status not in VALID_SKILL_STATUSES:
            errors.append("skill_status must be ACTIVE or EXCLUDED.")

        if self.skill_md_path:
            skill_path = Path(self.skill_md_path)
            if skill_path.name != "SKILL.md":
                errors.append("skill_md_path must point to SKILL.md.")
            if (
                self.folder_path
                and skill_path.parent != Path(self.folder_path)
            ):
                errors.append("skill_md_path must be inside folder_path.")

        return errors


def _instruction_token_count(text: str) -> int:
    """Count tokens with the installed tokenizer and keep a safe fallback."""
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception:
        # The runtime dependency normally provides tiktoken. This fallback
        # keeps validation available in minimal test environments.
        return max(1, (len(text) + 3) // 4)