"""Expose the MCP contract for saving one GHOST Episodic Memory.

This module validates the authenticated Save request and delegates durable
storage and description indexing to McpMemoryStore. Model-facing instructions
are loaded from custom_memory_save.json rather than embedded in Python.

Main classes:
    GhostMemoryTagTool:
        Adapts one MCP Save call to the owner-scoped Episodic backend.

Main methods and functions:
    call_sanitized():
        Validates, saves, and returns the actual stored Recall Key and Record ID.
    tool_metadata():
        Builds the OAuth-protected MCP tool descriptor.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ragstream.mcp.ghost_engineer_prompt import (
    DEFAULT_REQUIRED_SCOPE,
    GhostToolResult,
)
from ragstream.mcp.memory_tool_instructions import (
    load_memory_tool_instructions,
)
from ragstream.memory.mcp_memory_store import (
    MAX_EPISODE_TITLE_LENGTH,
    McpMemoryStore,
)


TOOL_NAME = "ghost_memory_tag"
TOOL_TITLE = "GHOST Memory Save"
WORKFLOW_COMPLETE = "complete"

_INSTRUCTIONS = load_memory_tool_instructions("custom_memory_save.json")
TOOL_DESCRIPTION = _INSTRUCTIONS.tool_description
SERVER_INSTRUCTIONS = _INSTRUCTIONS.server_instruction

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "recall_key": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions["recall_key"],
        },
        "episode_title": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_EPISODE_TITLE_LENGTH,
            "description": _INSTRUCTIONS.field_descriptions[
                "episode_title"
            ],
        },
        "episode_description": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions[
                "episode_description"
            ],
        },
        "input_text": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions["input_text"],
        },
        "output_text": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions["output_text"],
        },
    },
    "required": [
        "recall_key",
        "episode_title",
        "episode_description",
        "input_text",
        "output_text",
    ],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "saved": {"type": "boolean"},
        "workflow_state": {
            "type": "string",
            "enum": [WORKFLOW_COMPLETE],
        },
        "requested_recall_key": {
            "type": "string",
            "minLength": 1,
        },
        "recall_key": {
            "type": "string",
            "minLength": 1,
        },
        "episode_title": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_EPISODE_TITLE_LENGTH,
        },
        "episode_description": {
            "type": "string",
            "minLength": 1,
        },
        "record_id": {
            "type": "string",
            "minLength": 1,
        },
        "reason": {"type": "string"},
    },
    "required": ["saved", "workflow_state"],
    "additionalProperties": False,
}


class GhostMemoryTagTool:
    """Adapt one authenticated MCP Save call to Episodic persistence."""

    def __init__(self, memory_store: McpMemoryStore) -> None:
        self._memory_store = memory_store

    def call_sanitized(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        """Validate the request, save the episode, and return its receipt."""
        if not isinstance(owner_sub, str) or not owner_sub.strip():
            return self._failure("authenticated user is required")
        if not isinstance(arguments, Mapping):
            return self._failure("memory save input is required")

        allowed_properties = {
            "recall_key",
            "episode_title",
            "episode_description",
            "input_text",
            "output_text",
        }
        if set(arguments).difference(allowed_properties):
            return self._failure("unsupported input property")

        recall_key = arguments.get("recall_key")
        episode_title = arguments.get("episode_title")
        episode_description = arguments.get("episode_description")
        input_text = arguments.get("input_text")
        output_text = arguments.get("output_text")

        text_fields = {
            "recall_key": recall_key,
            "episode_title": episode_title,
            "episode_description": episode_description,
            "input_text": input_text,
            "output_text": output_text,
        }
        for field_name, value in text_fields.items():
            if not isinstance(value, str) or not value.strip():
                return self._failure(
                    f"{field_name} is required and must be a non-empty string"
                )

        clean_recall_key = recall_key.strip()
        clean_episode_title = episode_title.strip()
        clean_description = episode_description.strip()

        if len(clean_episode_title) > MAX_EPISODE_TITLE_LENGTH:
            return self._failure(
                f"episode_title must be at most "
                f"{MAX_EPISODE_TITLE_LENGTH} characters",
                requested_recall_key=clean_recall_key,
            )

        try:
            record = self._memory_store.save_episodic_memory(
                owner_sub=owner_sub,
                recall_key=clean_recall_key,
                episode_title=clean_episode_title,
                episode_description=clean_description,
                input_text=input_text,
                output_text=output_text,
            )
        except ValueError as error:
            return self._failure(
                str(error),
                requested_recall_key=clean_recall_key,
            )
        except Exception:  # noqa: BLE001
            return self._failure(
                "GHOST memory storage failed",
                requested_recall_key=clean_recall_key,
            )

        effective_key = record.direct_recall_key
        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": (
                        "Memory saved successfully.\n"
                        f"Episode title: {record.episode_title}\n"
                        f"Recall key: {effective_key}\n"
                        f"Record ID: {record.record_id}"
                    ),
                }
            ],
            structuredContent={
                "saved": True,
                "workflow_state": WORKFLOW_COMPLETE,
                "requested_recall_key": clean_recall_key,
                "recall_key": effective_key,
                "episode_title": record.episode_title,
                "episode_description": record.episode_description,
                "record_id": record.record_id,
            },
        )

    @staticmethod
    def _failure(
        reason: str,
        requested_recall_key: str | None = None,
    ) -> GhostToolResult:
        structured_content: dict[str, Any] = {
            "saved": False,
            "workflow_state": WORKFLOW_COMPLETE,
            "reason": reason,
        }
        if requested_recall_key is not None:
            structured_content["requested_recall_key"] = (
                requested_recall_key
            )

        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": f"Memory was NOT saved. Reason: {reason}.",
                }
            ],
            structuredContent=structured_content,
            isError=True,
        )


def tool_metadata(required_scope: str | None = None) -> dict[str, Any]:
    """Build the OAuth-protected MCP Save tool descriptor."""
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