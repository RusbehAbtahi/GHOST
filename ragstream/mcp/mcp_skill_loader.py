"""Expose owner-scoped Skill discovery and deterministic loading through MCP.

This module is the MCP boundary for the Part 1 Skill retrieval workflow. It
validates public arguments, creates one fresh SkillManager for every call, and
returns either description candidates or complete selected SKILL.md content.

Main classes:
    McpSkillLoaderTool:
        Adapts one authenticated MCP request to SkillManager retrieval.

Main methods and functions:
    call_sanitized():
        Searches Skill descriptions or loads exact selected Skill IDs.
    tool_metadata():
        Builds the OAuth-protected MCP tool descriptor.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from ragstream.mcp.mcp_tool_contracts import (
    DEFAULT_REQUIRED_SCOPE,
    GhostToolResult,
)
from ragstream.mcp.memory_tool_instructions import (
    load_memory_tool_instructions,
)
from ragstream.memory.mcp_skill_memory_store import (
    CLI_SKILL_DOMAIN,
    DEFAULT_SKILLS_BASE_ROOT,
    GENERAL_SKILL_DOMAIN,
    McpSkillMemoryStore,
    SkillDomainConfig,
    resolve_skill_domain,
)
from ragstream.skills.skill_manager import SkillManager
from ragstream.skills.skill_tags import SkillTagCatalog, normalize_skill_tag_filters


TOOL_NAME = "ghost_skill_loader"
TOOL_TITLE = "GHOST Skill Loader"
WORKFLOW_SELECTION_REQUIRED = "selection_required"
WORKFLOW_COMPLETE = "complete"

_INSTRUCTIONS = load_memory_tool_instructions(
    "custom_skill_loader.json"
)
TOOL_DESCRIPTION = _INSTRUCTIONS.tool_description
SERVER_INSTRUCTIONS = _INSTRUCTIONS.server_instruction

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "skill_domain": {
            "type": "string",
            "enum": [CLI_SKILL_DOMAIN, GENERAL_SKILL_DOMAIN],
            "description": _INSTRUCTIONS.field_descriptions[
                "skill_domain"
            ],
        },
        "query": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions["query"],
        },
        "include_tags": {
            "type": "array",
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1},
            "description": _INSTRUCTIONS.field_descriptions["include_tags"],
        },
        "exclude_tags": {
            "type": "array",
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1},
            "description": _INSTRUCTIONS.field_descriptions["exclude_tags"],
        },
        "skill_ids": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1},
            "description": _INSTRUCTIONS.field_descriptions[
                "skill_ids"
            ],
        },
    },
    "required": ["skill_domain"],
    "oneOf": [
        {
            "required": ["query"],
            "not": {"required": ["skill_ids"]},
        },
        {
            "required": ["skill_ids"],
            "not": {"required": ["query"]},
        },
    ],
    "additionalProperties": False,
}

_CANDIDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "skill_id": {"type": "string", "minLength": 1},
        "skill_title": {"type": "string", "minLength": 1},
        "skill_description": {"type": "string", "minLength": 1},
        "skill_tags": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1},
        },
        "cosine_similarity": {"type": "number"},
    },
    "required": [
        "skill_id",
        "skill_title",
        "skill_description",
        "skill_tags",
        "cosine_similarity",
    ],
    "additionalProperties": False,
}

_LOADED_SKILL_SCHEMA = {
    "type": "object",
    "properties": {
        "skill_id": {"type": "string", "minLength": 1},
        "skill_text": {"type": "string", "minLength": 1},
    },
    "required": ["skill_id", "skill_text"],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "skill_domain": {
            "type": "string",
            "enum": [CLI_SKILL_DOMAIN, GENERAL_SKILL_DOMAIN],
        },
        "workflow_state": {
            "type": "string",
            "enum": [
                WORKFLOW_SELECTION_REQUIRED,
                WORKFLOW_COMPLETE,
            ],
        },
        "query": {"type": "string", "minLength": 1},
        "candidate_count": {"type": "integer", "minimum": 0},
        "include_tags": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
        "exclude_tags": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
        "candidates": {
            "type": "array",
            "items": _CANDIDATE_SCHEMA,
        },
        "loaded_count": {"type": "integer", "minimum": 0},
        "skills": {
            "type": "array",
            "items": _LOADED_SKILL_SCHEMA,
        },
        "reason": {"type": "string"},
    },
    "required": ["workflow_state"],
    "additionalProperties": False,
}

ManagerFactory = Callable[[str, SkillDomainConfig], SkillManager]


class McpSkillLoaderTool:
    """Adapt authenticated MCP calls to request-scoped Skill retrieval."""

    def __init__(
        self,
        manager_factory: ManagerFactory | None = None,
        skills_base_root: str | Path = DEFAULT_SKILLS_BASE_ROOT,
        skill_tag_catalog: SkillTagCatalog | None = None,
    ) -> None:
        self._skills_base_root = Path(skills_base_root)
        self._skill_tag_catalog = skill_tag_catalog or SkillTagCatalog()
        self._manager_factory = (
            manager_factory or self._create_manager
        )

    def call_sanitized(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        """Search descriptions or load exact active Skills for one owner."""
        error = self._validate_request(owner_sub, arguments)
        if error is not None:
            return self._failure(error)
        assert arguments is not None

        try:
            domain_config = resolve_skill_domain(
                arguments["skill_domain"]
            )
            manager = self._manager_factory(
                owner_sub,
                domain_config,
            )
            if "query" in arguments:
                return self._search(
                    manager,
                    arguments["query"],
                    domain_config.skill_domain,
                    self._skill_tag_catalog.tags(owner_sub),
                    arguments.get("include_tags"),
                    arguments.get("exclude_tags"),
                )

            skill_ids = self._clean_skill_ids(arguments["skill_ids"])
            return self._load(
                manager,
                skill_ids,
                domain_config.skill_domain,
            )
        except ValueError as error:
            return self._failure(str(error))
        except Exception:
            return self._failure("GHOST Skill loading failed")

    @staticmethod
    def _search(
        manager: SkillManager,
        raw_query: Any,
        skill_domain: str,
        allowed_tags: list[str],
        raw_include_tags: Any,
        raw_exclude_tags: Any,
    ) -> GhostToolResult:
        if not isinstance(raw_query, str) or not raw_query.strip():
            raise ValueError(
                "query is required and must be a non-empty string"
            )

        query = raw_query.strip()
        include_tags, exclude_tags = normalize_skill_tag_filters(
            raw_include_tags,
            raw_exclude_tags,
            allowed_tags=allowed_tags,
        )
        if include_tags or exclude_tags:
            candidates = manager.retrieve_candidates(
                query,
                include_tags=include_tags,
                exclude_tags=exclude_tags,
            )
        else:
            candidates = manager.retrieve_candidates(query)
        workflow_state = (
            WORKFLOW_SELECTION_REQUIRED
            if candidates
            else WORKFLOW_COMPLETE
        )
        message = (
            f"GHOST found {len(candidates)} active Skill candidate(s)."
        )
        if candidates:
            message += " Select exact skill_ids and call this tool again."

        return GhostToolResult(
            content=[{"type": "text", "text": message}],
            structuredContent={
                "skill_domain": skill_domain,
                "workflow_state": workflow_state,
                "query": query,
                "candidate_count": len(candidates),
                "include_tags": include_tags,
                "exclude_tags": exclude_tags,
                "candidates": candidates,
            },
        )

    @staticmethod
    def _load(
        manager: SkillManager,
        skill_ids: list[str],
        skill_domain: str,
    ) -> GhostToolResult:
        skill_texts = manager.load_selected_skills(skill_ids)
        loaded_skills = [
            {
                "skill_id": skill_id,
                "skill_text": skill_text,
            }
            for skill_id, skill_text in zip(
                skill_ids,
                skill_texts,
                strict=True,
            )
        ]

        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": (
                        f"GHOST loaded {len(loaded_skills)} active "
                        "Skill(s)."
                    ),
                }
            ],
            structuredContent={
                "skill_domain": skill_domain,
                "workflow_state": WORKFLOW_COMPLETE,
                "loaded_count": len(loaded_skills),
                "skills": loaded_skills,
            },
        )

    @staticmethod
    def _validate_request(
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
    ) -> str | None:
        if not isinstance(owner_sub, str) or not owner_sub.strip():
            return "authenticated user is required"
        if not isinstance(arguments, Mapping):
            return "Skill loader input is required"
        if set(arguments).difference(
            {
                "skill_domain",
                "query",
                "skill_ids",
                "include_tags",
                "exclude_tags",
            }
        ):
            return "unsupported input property"
        if "skill_domain" not in arguments:
            return "missing required input: skill_domain"

        has_query = "query" in arguments
        has_skill_ids = "skill_ids" in arguments
        if has_query == has_skill_ids:
            return "provide exactly one of query or skill_ids"

        if has_skill_ids and (
            "include_tags" in arguments or "exclude_tags" in arguments
        ):
            return "tag filters are allowed only with query"
        return None

    @staticmethod
    def _clean_skill_ids(raw_skill_ids: Any) -> list[str]:
        if not isinstance(raw_skill_ids, list) or not raw_skill_ids:
            raise ValueError("skill_ids must be a non-empty list")

        cleaned: list[str] = []
        seen: set[str] = set()
        for skill_id in raw_skill_ids:
            if not isinstance(skill_id, str) or not skill_id.strip():
                raise ValueError(
                    "skill_ids must contain only non-empty strings"
                )

            clean_id = skill_id.strip()
            if clean_id not in seen:
                cleaned.append(clean_id)
                seen.add(clean_id)

        return cleaned

    def _create_manager(
        self,
        owner_sub: str,
        domain_config: SkillDomainConfig,
    ) -> SkillManager:
        return SkillManager(
            owner_sub=owner_sub,
            skills_root=domain_config.skills_root(
                self._skills_base_root
            ),
            memory_store=McpSkillMemoryStore(
                domain_config=domain_config,
                skill_tag_catalog=self._skill_tag_catalog,
            ),
        )

    @staticmethod
    def _failure(reason: str) -> GhostToolResult:
        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": f"GHOST Skill loading failed. Reason: {reason}.",
                }
            ],
            structuredContent={
                "workflow_state": WORKFLOW_COMPLETE,
                "reason": reason,
            },
            isError=True,
        )


def tool_metadata(
    required_scope: str | None = None,
) -> dict[str, Any]:
    """Build the OAuth-protected Skill loader descriptor."""
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
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    }
