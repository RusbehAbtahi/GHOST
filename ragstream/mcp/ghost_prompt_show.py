"""Expose the shared GHOST prompt builder as a build-and-show MCP tool."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ragstream.mcp.ghost_prompt_builder import (
    GhostPromptBuilder,
    PromptBuildError,
    STATUS_CLARIFICATION_REQUIRED,
    STATUS_COMPLETE,
    STATUS_SELECTION_REQUIRED,
)
from ragstream.mcp.mcp_tool_contracts import (
    DEFAULT_REQUIRED_SCOPE,
    GhostToolResult,
)
from ragstream.mcp.memory_tool_instructions import (
    load_memory_tool_instructions,
)


TOOL_NAME = "ghost_prompt_show"
TOOL_TITLE = "GHOST Prompt Show"
MODE_SHOW = "show_prompt"
DISPLAY_POLICY_VERBATIM = "VERBATIM_REQUIRED"
DISPLAY_POLICY_EXECUTE_ONCE = "EXECUTE_EXACTLY_ONCE"
DISPLAY_POLICY_NOT_APPLICABLE = "NOT_APPLICABLE"

_INSTRUCTIONS = load_memory_tool_instructions("custom_prompt_show.json")
TOOL_DESCRIPTION = _INSTRUCTIONS.tool_description
SERVER_INSTRUCTIONS = _INSTRUCTIONS.server_instruction

_SETTING_OVERRIDES_SCHEMA = {
    "type": "object",
    "properties": {
        "input_cleanup": {"type": "boolean"},
        "prompt_shaping": {"type": "boolean"},
        "document_retrieval": {"type": "boolean"},
        "memory_retrieval": {"type": "boolean"},
        "knowledge_retrieval": {"type": "boolean"},
        "general_skill_retrieval": {"type": "boolean"},
        "memory_recency_enabled": {"type": "boolean"},
        "default_project_name": {"type": ["string", "null"]},
        "default_ragmem_path": {"type": ["string", "null"]},
    },
    "additionalProperties": False,
}

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "prompt_text": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions["prompt_text"],
        },
        "prompt": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions["prompt"],
        },
        "build_id": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions["build_id"],
        },
        "setting_overrides": {
            **_SETTING_OVERRIDES_SCHEMA,
            "description": _INSTRUCTIONS.field_descriptions[
                "setting_overrides"
            ],
        },
        "project_name": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions["project_name"],
        },
        "document_project_name": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions[
                "document_project_name"
            ],
        },
        "ragmem_path": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions["ragmem_path"],
        },
        "document_context_tokens": {
            "type": "integer",
            "minimum": 1,
            "description": _INSTRUCTIONS.field_descriptions[
                "document_context_tokens"
            ],
        },
        "document_max_output_tokens": {
            "type": "integer",
            "minimum": 1,
            "description": _INSTRUCTIONS.field_descriptions[
                "document_max_output_tokens"
            ],
        },
        "memory_context_tokens": {
            "type": "integer",
            "minimum": 1,
            "description": _INSTRUCTIONS.field_descriptions[
                "memory_context_tokens"
            ],
        },
        "memory_max_output_tokens": {
            "type": "integer",
            "minimum": 1,
            "description": _INSTRUCTIONS.field_descriptions[
                "memory_max_output_tokens"
            ],
        },
        "general_skill_ids": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1},
            "description": _INSTRUCTIONS.field_descriptions[
                "general_skill_ids"
            ],
        },
        "general_skill_query": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions[
                "general_skill_query"
            ],
        },
    },
    "anyOf": [
        {"required": ["prompt_text"]},
        {"required": ["prompt"]},
        {"required": ["build_id"]},
    ],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": [
                STATUS_COMPLETE,
                STATUS_CLARIFICATION_REQUIRED,
                STATUS_SELECTION_REQUIRED,
            ],
        },
        "mode": {"type": "string"},
        "display_policy": {
            "type": "string",
            "enum": [
                DISPLAY_POLICY_VERBATIM,
                DISPLAY_POLICY_EXECUTE_ONCE,
                DISPLAY_POLICY_NOT_APPLICABLE,
            ],
        },
        "prompt": {"type": "string"},
        "clarification_question": {"type": "string"},
        "general_skill_candidates": {
            "type": "array",
            "items": {"type": "object"},
        },
        "receipt": {"type": "object"},
        "reason": {"type": "string"},
    },
    "required": [
        "status",
        "mode",
        "display_policy",
        "prompt",
        "clarification_question",
        "general_skill_candidates",
        "receipt",
    ],
    "additionalProperties": False,
}

_ALLOWED_ARGUMENTS = frozenset(INPUT_SCHEMA["properties"])


class GhostPromptToolAdapter:
    """Shared thin adapter for prompt Show and Run behavior."""

    def __init__(
        self,
        builder: GhostPromptBuilder,
        *,
        mode: str,
        failure_label: str,
    ) -> None:
        self._builder = builder
        self._mode = mode
        self._failure_label = failure_label

    def call_sanitized(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        """Validate one request, build once, and return a sanitized result."""
        try:
            clean_arguments = _validate_arguments(arguments)
            built = self._builder.build(
                owner_sub=owner_sub,
                **clean_arguments,
            )
            built = self._continue_single_skill(owner_sub, built)
            structured = {
                "status": built["status"],
                "mode": self._mode,
                "display_policy": self._display_policy(built["status"]),
                "prompt": built["prompt"],
                "clarification_question": built[
                    "clarification_question"
                ],
                "general_skill_candidates": built[
                    "general_skill_candidates"
                ],
                "receipt": built["receipt"],
            }
            return GhostToolResult(
                content=[
                    {
                        "type": "text",
                        "text": _result_text(structured),
                    }
                ],
                structuredContent=structured,
            )
        except (PromptBuildError, ValueError) as error:
            return self._failure(str(error))
        except Exception:
            return self._failure("GHOST prompt building failed")

    def _continue_single_skill(
        self,
        owner_sub: str,
        built: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Automatically continue an unambiguous one-candidate Skill build."""
        if built.get("status") != STATUS_SELECTION_REQUIRED:
            return built

        candidates = list(built.get("general_skill_candidates", []) or [])
        if len(candidates) != 1 or not isinstance(candidates[0], Mapping):
            return built

        skill_id = str(candidates[0].get("skill_id", "") or "").strip()
        receipt = built.get("receipt")
        if not skill_id or not isinstance(receipt, Mapping):
            return built
        build_id = str(receipt.get("build_id", "") or "").strip()
        if not build_id:
            return built

        return self._builder.build(
            owner_sub=owner_sub,
            build_id=build_id,
            general_skill_ids=[skill_id],
        )

    def _display_policy(self, status: str) -> str:
        if status != STATUS_COMPLETE:
            return DISPLAY_POLICY_NOT_APPLICABLE
        if self._mode == MODE_SHOW:
            return DISPLAY_POLICY_VERBATIM
        return DISPLAY_POLICY_EXECUTE_ONCE

    def _failure(self, reason: str) -> GhostToolResult:
        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": f"{self._failure_label} Reason: {reason}.",
                }
            ],
            structuredContent={},
            isError=True,
        )


class GhostPromptShowTool(GhostPromptToolAdapter):
    """Build one final prompt and return it for code-frame display only."""

    def __init__(self, builder: GhostPromptBuilder) -> None:
        super().__init__(
            builder,
            mode=MODE_SHOW,
            failure_label="GHOST Prompt Show failed.",
        )


def _validate_arguments(
    arguments: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(arguments, Mapping):
        raise ValueError("prompt input is required")

    arguments = _normalize_argument_aliases(arguments)
    unsupported = set(arguments).difference(_ALLOWED_ARGUMENTS)
    if unsupported:
        raise ValueError("unsupported input property")

    build_id = arguments.get("build_id")
    prompt_text = arguments.get("prompt_text")
    has_build_id = isinstance(build_id, str) and bool(build_id.strip())
    has_prompt = isinstance(prompt_text, str) and bool(prompt_text.strip())
    has_skill_ids = arguments.get("general_skill_ids") is not None

    if not has_build_id and not has_prompt:
        raise ValueError("prompt_text is required for a new build")
    if build_id is not None and not has_build_id:
        raise ValueError("build_id must be a non-empty string")
    if has_build_id:
        forbidden = {
            "setting_overrides",
            "project_name",
            "ragmem_path",
            "document_context_tokens",
            "document_max_output_tokens",
            "memory_context_tokens",
            "memory_max_output_tokens",
            "general_skill_query",
        }.intersection(arguments)
        if forbidden:
            raise ValueError(
                "continuation cannot replace saved settings or sources"
            )
        if has_prompt == has_skill_ids:
            raise ValueError(
                "continuation requires exactly one of prompt_text or "
                "general_skill_ids"
            )

    clean: dict[str, Any] = {}
    if has_build_id:
        clean["build_id"] = build_id.strip()
    if has_prompt:
        clean["prompt_text"] = prompt_text

    overrides = arguments.get("setting_overrides")
    if overrides is not None:
        if not isinstance(overrides, Mapping):
            raise ValueError("setting_overrides must be an object")
        clean["setting_overrides"] = dict(overrides)

    for key in ("project_name", "ragmem_path", "general_skill_query"):
        value = arguments.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a non-empty string")
        clean[key] = value.strip()

    for key in (
        "document_context_tokens",
        "document_max_output_tokens",
        "memory_context_tokens",
        "memory_max_output_tokens",
    ):
        value = arguments.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{key} must be a positive integer")
        clean[key] = value

    skill_ids = arguments.get("general_skill_ids")
    if skill_ids is not None:
        clean["general_skill_ids"] = _clean_skill_ids(skill_ids)

    return clean


def _normalize_argument_aliases(
    arguments: Mapping[str, Any],
) -> dict[str, Any]:
    """Map common legacy/obvious prompt arguments to canonical MCP names."""
    normalized = dict(arguments)
    aliases = {
        "prompt": "prompt_text",
        "document_project_name": "project_name",
    }
    for alias, canonical in aliases.items():
        if alias not in normalized:
            continue
        alias_value = normalized.pop(alias)
        if canonical in normalized and normalized[canonical] != alias_value:
            raise ValueError(
                f"conflicting input properties: {alias} and {canonical}"
            )
        normalized.setdefault(canonical, alias_value)
    return normalized


def _clean_skill_ids(raw_skill_ids: Any) -> Sequence[str]:
    if not isinstance(raw_skill_ids, list) or not raw_skill_ids:
        raise ValueError("general_skill_ids must be a non-empty list")

    cleaned: list[str] = []
    seen: set[str] = set()
    for raw_skill_id in raw_skill_ids:
        if not isinstance(raw_skill_id, str) or not raw_skill_id.strip():
            raise ValueError(
                "general_skill_ids must contain non-empty strings"
            )
        skill_id = raw_skill_id.strip()
        if skill_id in seen:
            raise ValueError("general_skill_ids must be unique")
        seen.add(skill_id)
        cleaned.append(skill_id)
    return cleaned


def _result_text(result: Mapping[str, Any]) -> str:
    status = result["status"]
    if status == STATUS_COMPLETE:
        return str(result["prompt"])
    if status == STATUS_CLARIFICATION_REQUIRED:
        return str(result["clarification_question"])
    if status == STATUS_SELECTION_REQUIRED:
        return (
            "GHOST found General Skill candidates. Select exact "
            "general_skill_ids and call the same prompt tool again."
        )
    raise ValueError("prompt builder returned an unsupported status")


def tool_metadata(
    required_scope: str | None = None,
) -> dict[str, Any]:
    """Build the OAuth-protected Prompt Show descriptor."""
    return _tool_metadata(
        name=TOOL_NAME,
        title=TOOL_TITLE,
        description=TOOL_DESCRIPTION,
        required_scope=required_scope,
    )


def _tool_metadata(
    *,
    name: str,
    title: str,
    description: str,
    required_scope: str | None,
) -> dict[str, Any]:
    scope = (
        required_scope
        if required_scope is not None
        else DEFAULT_REQUIRED_SCOPE
    ).strip()
    if not scope:
        raise ValueError("required_scope must not be empty")

    security_schemes = [{"type": "oauth2", "scopes": [scope]}]
    return {
        "name": name,
        "title": title,
        "description": description,
        "inputSchema": INPUT_SCHEMA,
        "outputSchema": OUTPUT_SCHEMA,
        "securitySchemes": security_schemes,
        "_meta": {"securitySchemes": security_schemes.copy()},
        "annotations": {
            "destructiveHint": False,
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    }
