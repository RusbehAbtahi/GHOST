"""Expose immutable Skill creation and replacement through GHOST MCP.

This module validates model-prepared Skill data, creates one fresh SkillManager
per call, and coordinates artifact creation, Memory persistence, and archival.
It also owns Linux non-waiting locks for normalized names and replaced IDs.

Main classes:
    McpSkillMakerTool:
        Adapts one authenticated MCP request to the Part 1 Skill workflow.

Main methods and functions:
    call_sanitized():
        Creates a new Skill or an immutable replacement Skill.
    tool_metadata():
        Builds the OAuth-protected MCP tool descriptor.

Important notes:
    Lock files remain on disk. Linux stores the active lock state internally
    and releases it when this process unlocks or closes the file descriptor.
"""

from __future__ import annotations

import errno
import fcntl
import re

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TextIO

from ragstream.mcp.ghost_engineer_prompt import (
    DEFAULT_REQUIRED_SCOPE,
    GhostToolResult,
)
from ragstream.mcp.memory_tool_instructions import (
    load_memory_tool_instructions,
)
from ragstream.memory.mcp_skill_memory_store import (
    SkillNameAlreadyExistsError,
    SkillRegistryIntegrityError,
)
from ragstream.skills.skill import Skill
from ragstream.skills.skill_manager import (
    DEFAULT_SKILLS_ROOT,
    SkillManager,
)


TOOL_NAME = "ghost_skill_make"
TOOL_TITLE = "GHOST Skill Maker"
WORKFLOW_COMPLETE = "complete"

CREATE_NEW_SKILL = "CREATE_NEW_SKILL"
UPDATE_EXISTING_SKILL = "UPDATE_EXISTING_SKILL"
SKILL_UPDATE_BUSY = "SKILL_UPDATE_BUSY"
SKILL_NAME_ALREADY_EXISTS = "SKILL_NAME_ALREADY_EXISTS"
SKILL_REGISTRY_CORRUPT = "SKILL_REGISTRY_CORRUPT"
SKILL_ROLLBACK_FAILED = "SKILL_ROLLBACK_FAILED"
SKILL_MAKE_FAILED = "SKILL_MAKE_FAILED"

_SAFE_PATH_PART = re.compile(r"[A-Za-z0-9._-]+")

_INSTRUCTIONS = load_memory_tool_instructions(
    "custom_skill_make.json"
)
TOOL_DESCRIPTION = _INSTRUCTIONS.tool_description
SERVER_INSTRUCTIONS = _INSTRUCTIONS.server_instruction

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": [CREATE_NEW_SKILL, UPDATE_EXISTING_SKILL],
            "description": _INSTRUCTIONS.field_descriptions["decision"],
        },
        "skill_name": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions[
                "skill_name"
            ],
        },
        "skill_title": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions[
                "skill_title"
            ],
        },
        "skill_description": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions[
                "skill_description"
            ],
        },
        "skill_text": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions[
                "skill_text"
            ],
        },
        "yaml_metadata": {
            "type": "object",
            "description": _INSTRUCTIONS.field_descriptions[
                "yaml_metadata"
            ],
        },
        "ragmem_title": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions[
                "ragmem_title"
            ],
        },
        "ragmem_description": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions[
                "ragmem_description"
            ],
        },
        "affected_skill_ids": {
            "type": "array",
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1},
            "description": _INSTRUCTIONS.field_descriptions[
                "affected_skill_ids"
            ],
        },
        "notes": {
            "type": "array",
            "description": _INSTRUCTIONS.field_descriptions["notes"],
        },
    },
    "required": [
        "decision",
        "skill_name",
        "skill_title",
        "skill_description",
        "skill_text",
        "ragmem_title",
        "ragmem_description",
        "affected_skill_ids",
    ],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "created": {"type": "boolean"},
        "workflow_state": {
            "type": "string",
            "enum": [WORKFLOW_COMPLETE],
        },
        "decision": {
            "type": "string",
            "enum": [CREATE_NEW_SKILL, UPDATE_EXISTING_SKILL],
        },
        "skill_id": {"type": "string", "minLength": 1},
        "skill_name": {"type": "string", "minLength": 1},
        "skill_title": {"type": "string", "minLength": 1},
        "skill_description": {"type": "string", "minLength": 1},
        "folder_path": {"type": "string", "minLength": 1},
        "skill_md_path": {"type": "string", "minLength": 1},
        "ragmem_record_id": {"type": "string", "minLength": 1},
        "ragmem_recall_key": {"type": "string", "minLength": 1},
        "skill_status": {"type": "string", "minLength": 1},
        "affected_skill_ids": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
        "error_code": {
            "type": "string",
            "enum": [
                SKILL_UPDATE_BUSY,
                SKILL_NAME_ALREADY_EXISTS,
                SKILL_REGISTRY_CORRUPT,
                SKILL_ROLLBACK_FAILED,
                SKILL_MAKE_FAILED,
            ],
        },
        "existing_skill_id": {"type": "string", "minLength": 1},
        "reason": {"type": "string"},
    },
    "required": ["created", "workflow_state"],
    "additionalProperties": False,
}

ManagerFactory = Callable[[str], SkillManager]


class McpSkillMakerTool:
    """Coordinate one authenticated, request-scoped Skill write workflow."""

    def __init__(
        self,
        manager_factory: ManagerFactory | None = None,
        skills_root: str | Path = DEFAULT_SKILLS_ROOT,
    ) -> None:
        self._skills_root = Path(skills_root)
        self._manager_factory = (
            manager_factory or self._create_manager
        )

    def call_sanitized(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        """Create a new Skill or replace exact owner-scoped Skill IDs."""
        validation_error = self._validate_request(
            owner_sub,
            arguments,
        )
        if validation_error is not None:
            return self._failure(validation_error)
        assert arguments is not None

        try:
            decision = str(arguments["decision"])
            affected_skill_ids = self._clean_affected_skill_ids(
                arguments["affected_skill_ids"]
            )
            self._validate_decision(decision, affected_skill_ids)
            skill = self._build_skill(arguments)
        except ValueError as error:
            return self._failure(str(error))

        lock_files = self._acquire_locks(
            owner_sub,
            skill.skill_name,
            affected_skill_ids,
        )
        if lock_files is None:
            return self._failure(
                "another CLI task is changing this Skill name or version",
                error_code=SKILL_UPDATE_BUSY,
            )

        try:
            manager = self._manager_factory(owner_sub)

            # Validate every replacement ID before creating a new artifact.
            # This prevents an invented or stale ID from producing a new Skill.
            if affected_skill_ids:
                manager.load_selected_skills(affected_skill_ids)

            created_skill, created = manager.create_skill_artifact(skill)
            if not created:
                return self._failure(
                    "the SKILL.md artifact could not be created"
                )

            persisted_skill = manager.persist_skill_memory(
                created_skill,
                replacing_skill_ids=affected_skill_ids,
            )
            if affected_skill_ids:
                try:
                    manager.archive_replaced_skills(
                        affected_skill_ids,
                        replacement_skill_id=(
                            persisted_skill.skill_id
                        ),
                    )
                except Exception:
                    try:
                        manager.rollback_persisted_skill(
                            persisted_skill
                        )
                    except Exception:
                        return self._failure(
                            "replacement failed and rollback did not "
                            "complete",
                            error_code=SKILL_ROLLBACK_FAILED,
                        )
                    raise

            return self._success(
                decision,
                persisted_skill,
                affected_skill_ids,
            )
        except SkillNameAlreadyExistsError as error:
            return self._failure(
                str(error),
                error_code=SKILL_NAME_ALREADY_EXISTS,
                existing_skill_id=error.existing_skill_id,
            )
        except SkillRegistryIntegrityError as error:
            return self._failure(
                str(error),
                error_code=SKILL_REGISTRY_CORRUPT,
            )
        except ValueError as error:
            return self._failure(str(error))
        except Exception:
            return self._failure("GHOST Skill creation failed")
        finally:
            self._release_locks(lock_files)

    def _acquire_locks(
        self,
        owner_sub: str,
        skill_name: str,
        skill_ids: list[str],
    ) -> list[TextIO] | None:
        owner = self._validate_safe_path_part(owner_sub, "owner_sub")
        normalized_name = self._validate_safe_path_part(
            skill_name,
            "skill_name",
        ).casefold()

        lock_root = self._skills_root / ".locks" / owner
        lock_root.mkdir(parents=True, exist_ok=True)
        acquired: list[TextIO] = []

        lock_names = {f"name_{normalized_name}.lock"}
        lock_names.update(
            f"id_{skill_id}.lock"
            for skill_id in skill_ids
        )

        # Sorted acquisition gives every writer the same lock order.
        for lock_name in sorted(lock_names):
            lock_path = lock_root / lock_name
            lock_file = lock_path.open("a+", encoding="utf-8")
            try:
                fcntl.flock(
                    lock_file.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
            except OSError as error:
                lock_file.close()
                self._release_locks(acquired)
                if error.errno in {errno.EACCES, errno.EAGAIN}:
                    return None
                raise

            acquired.append(lock_file)

        return acquired

    @staticmethod
    def _release_locks(lock_files: list[TextIO]) -> None:
        # The stable .lock file remains. Unlocking and closing only releases
        # Linux's in-kernel lock state so a later update may acquire it.
        for lock_file in reversed(lock_files):
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            finally:
                lock_file.close()

    @staticmethod
    def _validate_request(
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
    ) -> str | None:
        if not isinstance(owner_sub, str) or not owner_sub.strip():
            return "authenticated user is required"
        if not isinstance(arguments, Mapping):
            return "Skill maker input is required"

        allowed_fields = {
            "decision",
            "skill_name",
            "skill_title",
            "skill_description",
            "skill_text",
            "yaml_metadata",
            "ragmem_title",
            "ragmem_description",
            "affected_skill_ids",
            "notes",
        }
        if set(arguments).difference(allowed_fields):
            return "unsupported input property"

        required_fields = {
            "decision",
            "skill_name",
            "skill_title",
            "skill_description",
            "skill_text",
            "ragmem_title",
            "ragmem_description",
            "affected_skill_ids",
        }
        missing_fields = required_fields.difference(arguments)
        if missing_fields:
            return "missing required input: " + ", ".join(
                sorted(missing_fields)
            )

        return None

    @classmethod
    def _build_skill(
        cls,
        arguments: Mapping[str, Any],
    ) -> Skill:
        text_fields = (
            "skill_name",
            "skill_title",
            "skill_description",
            "skill_text",
            "ragmem_title",
            "ragmem_description",
        )
        clean_text: dict[str, str] = {}
        for field_name in text_fields:
            value = arguments[field_name]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"{field_name} must be a non-empty string"
                )
            clean_text[field_name] = value.strip()

        cls._validate_safe_path_part(
            clean_text["skill_name"],
            "skill_name",
        )

        yaml_metadata = arguments.get("yaml_metadata", {})
        if not isinstance(yaml_metadata, dict):
            raise ValueError("yaml_metadata must be an object")

        notes = arguments.get("notes", [])
        if not isinstance(notes, list):
            raise ValueError("notes must be a list")

        return Skill(
            skill_name=clean_text["skill_name"],
            skill_title=clean_text["skill_title"],
            skill_description=clean_text["skill_description"],
            yaml_metadata=dict(yaml_metadata),
            instruction_text=clean_text["skill_text"],
            ragmem_title=clean_text["ragmem_title"],
            ragmem_description=clean_text["ragmem_description"],
            notes=list(notes),
        )

    @classmethod
    def _clean_affected_skill_ids(
        cls,
        raw_skill_ids: Any,
    ) -> list[str]:
        if not isinstance(raw_skill_ids, list):
            raise ValueError("affected_skill_ids must be a list")

        cleaned: list[str] = []
        seen: set[str] = set()
        for skill_id in raw_skill_ids:
            if not isinstance(skill_id, str) or not skill_id.strip():
                raise ValueError(
                    "affected_skill_ids must contain only non-empty strings"
                )

            clean_id = cls._validate_safe_path_part(
                skill_id,
                "skill_id",
            )
            if clean_id not in seen:
                cleaned.append(clean_id)
                seen.add(clean_id)

        return cleaned

    @staticmethod
    def _validate_decision(
        decision: str,
        affected_skill_ids: list[str],
    ) -> None:
        if decision not in {CREATE_NEW_SKILL, UPDATE_EXISTING_SKILL}:
            raise ValueError(
                "decision must be CREATE_NEW_SKILL or "
                "UPDATE_EXISTING_SKILL"
            )
        if decision == CREATE_NEW_SKILL and affected_skill_ids:
            raise ValueError(
                "CREATE_NEW_SKILL requires empty affected_skill_ids"
            )
        if decision == UPDATE_EXISTING_SKILL and not affected_skill_ids:
            raise ValueError(
                "UPDATE_EXISTING_SKILL requires affected_skill_ids"
            )

    @staticmethod
    def _validate_safe_path_part(
        value: str,
        field_name: str,
    ) -> str:
        clean_value = str(value or "").strip()
        if (
            clean_value in {".", ".."}
            or _SAFE_PATH_PART.fullmatch(clean_value) is None
        ):
            raise ValueError(
                f"{field_name} must contain only letters, numbers, '.', "
                "'_' or '-'"
            )

        return clean_value

    def _create_manager(self, owner_sub: str) -> SkillManager:
        return SkillManager(
            owner_sub=owner_sub,
            skills_root=self._skills_root,
        )

    @staticmethod
    def _success(
        decision: str,
        skill: Skill,
        affected_skill_ids: list[str],
    ) -> GhostToolResult:
        structured_content = {
            "created": True,
            "workflow_state": WORKFLOW_COMPLETE,
            "decision": decision,
            "skill_id": skill.skill_id,
            "skill_name": skill.skill_name,
            "skill_title": skill.skill_title,
            "skill_description": skill.skill_description,
            "folder_path": skill.folder_path,
            "skill_md_path": skill.skill_md_path,
            "ragmem_record_id": skill.ragmem_record_id,
            "ragmem_recall_key": skill.ragmem_recall_key,
            "skill_status": skill.skill_status,
            "affected_skill_ids": affected_skill_ids,
        }
        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": (
                        "GHOST Skill created successfully.\n"
                        f"Skill ID: {skill.skill_id}\n"
                        f"SKILL.md: {skill.skill_md_path}"
                    ),
                }
            ],
            structuredContent=structured_content,
        )

    @staticmethod
    def _failure(
        reason: str,
        error_code: str = SKILL_MAKE_FAILED,
        existing_skill_id: str = "",
    ) -> GhostToolResult:
        structured_content = {
            "created": False,
            "workflow_state": WORKFLOW_COMPLETE,
            "error_code": error_code,
            "reason": reason,
        }
        if existing_skill_id:
            structured_content["existing_skill_id"] = (
                existing_skill_id
            )

        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": (
                        "GHOST Skill was NOT created. "
                        f"Reason: {reason}."
                    ),
                }
            ],
            structuredContent=structured_content,
            isError=True,
        )


def tool_metadata(
    required_scope: str | None = None,
) -> dict[str, Any]:
    """Build the OAuth-protected Skill maker descriptor."""
    scope = (
        required_scope
        if required_scope is not None
        else DEFAULT_REQUIRED_SCOPE
    ).strip()
    if not scope:
        raise ValueError("required_scope must not be empty")

    security_schemes = [{"type": "oauth2", "scopes": [scope]}]
    return {
        "name": TOOL_NAME,
        "title": TOOL_TITLE,
        "description": TOOL_DESCRIPTION,
        "inputSchema": INPUT_SCHEMA,
        "outputSchema": OUTPUT_SCHEMA,
        "securitySchemes": security_schemes,
        "_meta": {"securitySchemes": security_schemes.copy()},
        "annotations": {
            "destructiveHint": False,
            "readOnlyHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    }