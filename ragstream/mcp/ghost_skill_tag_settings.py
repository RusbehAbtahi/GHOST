"""Expose owner-scoped dynamic Skill tag catalog settings through GHOST MCP."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ragstream.mcp.mcp_tool_contracts import (
    DEFAULT_REQUIRED_SCOPE,
    GhostToolResult,
)
from ragstream.mcp.memory_tool_instructions import (
    load_memory_tool_instructions,
)
from ragstream.memory.mcp_skill_memory_store import (
    CLI_SKILL_CONFIG,
    GENERAL_SKILL_CONFIG,
    McpSkillMemoryStore,
)
from ragstream.skills.skill_tags import (
    SkillTagCatalog,
    SkillTagCatalogError,
)


TOOL_NAME = "ghost_skill_tag_settings"
TOOL_TITLE = "GHOST Skill Tag Settings"

_INSTRUCTIONS = load_memory_tool_instructions(
    "custom_skill_tag_settings.json"
)
TOOL_DESCRIPTION = _INSTRUCTIONS.tool_description
SERVER_INSTRUCTIONS = _INSTRUCTIONS.server_instruction

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["show", "add", "remove"],
            "description": _INSTRUCTIONS.field_descriptions["action"],
        },
        "tag": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions["tag"],
        },
    },
    "required": ["action"],
    "additionalProperties": False,
}

_USAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "skill_domain": {"type": "string", "enum": ["CLI", "GENERAL"]},
        "skill_id": {"type": "string", "minLength": 1},
        "skill_name": {"type": "string", "minLength": 1},
        "skill_status": {"type": "string", "minLength": 1},
    },
    "required": ["skill_domain", "skill_id", "skill_name", "skill_status"],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["show", "add", "remove"]},
        "tag": {"type": "string", "minLength": 1},
        "skill_tags": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1},
        },
        "changed": {"type": "boolean"},
        "usage": {"type": "array", "items": _USAGE_SCHEMA},
        "reason": {"type": "string"},
    },
    "required": ["action", "skill_tags", "changed"],
    "additionalProperties": False,
}

UsageChecker = Callable[[str, str], list[dict[str, str]]]


class GhostSkillTagSettingsTool:
    """Thin MCP adapter over the persisted Skill tag catalog."""

    def __init__(
        self,
        catalog: SkillTagCatalog,
        usage_checker: UsageChecker | None = None,
    ) -> None:
        self._catalog = catalog
        self._usage_checker = usage_checker or self._find_usage

    def call_sanitized(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        try:
            action, tag = self._validate_arguments(arguments)
            if action == "show":
                tags = self._catalog.tags(owner_sub)
                return self._success(action, tags, changed=False)

            assert tag is not None
            if action == "add":
                tags, changed = self._catalog.add(owner_sub, tag)
                return self._success(
                    action,
                    tags,
                    changed=changed,
                    tag=tag.strip().upper(),
                )

            clean_tag = tag.strip().upper()
            usage = self._usage_checker(owner_sub, clean_tag)
            if usage:
                return self._success(
                    action,
                    self._catalog.tags(owner_sub),
                    changed=False,
                    tag=clean_tag,
                    usage=usage,
                    reason="Skill tag is still used by persisted Skills",
                )

            tags, changed = self._catalog.remove(owner_sub, clean_tag)
            return self._success(
                action,
                tags,
                changed=changed,
                tag=clean_tag,
                usage=[],
            )
        except (SkillTagCatalogError, ValueError) as error:
            return GhostToolResult(
                content=[
                    {
                        "type": "text",
                        "text": (
                            "GHOST Skill Tag Settings failed. "
                            f"Reason: {error}."
                        ),
                    }
                ],
                structuredContent={},
                isError=True,
            )
        except Exception:
            return GhostToolResult(
                content=[
                    {
                        "type": "text",
                        "text": "GHOST Skill Tag Settings failed.",
                    }
                ],
                structuredContent={},
                isError=True,
            )

    def _find_usage(self, owner_sub: str, tag: str) -> list[dict[str, str]]:
        usage: list[dict[str, str]] = []
        for domain_config in (CLI_SKILL_CONFIG, GENERAL_SKILL_CONFIG):
            store = McpSkillMemoryStore(
                domain_config=domain_config,
                skill_tag_catalog=self._catalog,
            )
            usage.extend(
                store.find_skills_by_tag(
                    owner_sub=owner_sub,
                    tag=tag,
                )
            )
        return usage

    @staticmethod
    def _validate_arguments(
        arguments: Mapping[str, Any] | None,
    ) -> tuple[str, str | None]:
        if not isinstance(arguments, Mapping):
            raise ValueError("Skill tag settings input is required")
        if set(arguments).difference({"action", "tag"}):
            raise ValueError("unsupported input property")

        action = arguments.get("action")
        if action not in {"show", "add", "remove"}:
            raise ValueError("unsupported Skill tag settings action")

        tag = arguments.get("tag")
        if action == "show":
            if "tag" in arguments:
                raise ValueError("tag is allowed only for add or remove")
            return action, None

        if not isinstance(tag, str) or not tag.strip():
            raise ValueError(f"action {action} requires a non-empty tag")
        return action, tag

    @staticmethod
    def _success(
        action: str,
        tags: list[str],
        *,
        changed: bool,
        tag: str = "",
        usage: list[dict[str, str]] | None = None,
        reason: str = "",
    ) -> GhostToolResult:
        structured: dict[str, Any] = {
            "action": action,
            "skill_tags": list(tags),
            "changed": changed,
        }
        if tag:
            structured["tag"] = tag
        if usage is not None:
            structured["usage"] = list(usage)
        if reason:
            structured["reason"] = reason

        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": f"GHOST Skill tag settings action '{action}' completed.",
                }
            ],
            structuredContent=structured,
        )


def tool_metadata(
    required_scope: str | None = None,
) -> dict[str, Any]:
    """Build the OAuth-protected Skill Tag Settings descriptor."""
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
