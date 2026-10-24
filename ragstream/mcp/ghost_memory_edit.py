"""Expose exact Collection episode maintenance editing through MCP.

The tool selects one existing Collection episode only by exact Record ID and may
replace its answer, local title, or local description. Stable identity, question,
ActiveBrief, Recall Key, and episode number remain unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ragstream.mcp.mcp_tool_contracts import (
    DEFAULT_REQUIRED_SCOPE,
    GhostToolResult,
)
from ragstream.mcp.memory_tool_instructions import load_memory_tool_instructions
from ragstream.memory.mcp_memory_collection_store import (
    COLLECTION_MEMORY_TYPE,
    McpMemoryCollectionStore,
)


TOOL_NAME = "ghost_memory_edit_episode"
TOOL_TITLE = "GHOST Memory Edit Episode"

_INSTRUCTIONS = load_memory_tool_instructions("custom_memory_edit.json")
TOOL_DESCRIPTION = _INSTRUCTIONS.tool_description
SERVER_INSTRUCTIONS = _INSTRUCTIONS.server_instruction

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "record_id": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions["record_id"],
        },
        "new_output_text": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions["new_output_text"],
        },
        "new_episode_title": {
            "type": "string",
            "minLength": 1,
            "maxLength": 120,
            "description": _INSTRUCTIONS.field_descriptions["new_episode_title"],
        },
        "new_episode_description": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions[
                "new_episode_description"
            ],
        },
    },
    "required": ["record_id"],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "edited": {"type": "boolean"},
        "memory_type": {"type": "string"},
        "collection_id": {"type": "string"},
        "record_id": {"type": "string"},
        "episode_number": {"type": "integer", "minimum": 1},
        "recall_key": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["edited", "memory_type"],
    "additionalProperties": False,
}


class GhostMemoryEditEpisodeTool:
    """Edit selected mutable fields of one exact Collection episode."""

    def __init__(self, collection_store: McpMemoryCollectionStore) -> None:
        self._collection_store = collection_store

    def call_sanitized(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        if not isinstance(owner_sub, str) or not owner_sub.strip():
            return self._failure("authenticated user is required")
        if not isinstance(arguments, Mapping):
            return self._failure("memory edit input is required")

        allowed_properties = {
            "record_id",
            "new_output_text",
            "new_episode_title",
            "new_episode_description",
        }
        if set(arguments).difference(allowed_properties):
            return self._failure("unsupported input property")

        record_id = arguments.get("record_id")
        if not isinstance(record_id, str) or not record_id.strip():
            return self._failure("record_id must be a non-empty string")

        replacements: dict[str, str] = {}
        for field_name in (
            "new_output_text",
            "new_episode_title",
            "new_episode_description",
        ):
            if field_name not in arguments:
                continue

            value = arguments.get(field_name)
            if not isinstance(value, str) or not value.strip():
                return self._failure(
                    f"{field_name} must be a non-empty string"
                )
            replacements[field_name] = value

        if not replacements:
            return self._failure(
                "at least one editable Collection episode field is required"
            )

        try:
            result = self._collection_store.edit_episode_output(
                owner_sub=owner_sub,
                record_id=record_id.strip(),
                new_output_text=replacements.get("new_output_text"),
                new_episode_title=replacements.get("new_episode_title"),
                new_episode_description=replacements.get(
                    "new_episode_description"
                ),
            )
        except ValueError as error:
            return self._failure(str(error))
        except Exception:  # noqa: BLE001
            return self._failure("GHOST Collection episode edit failed")

        if not result["edited"]:
            return self._failure(
                "no Collection episode matched the exact Record ID"
            )

        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": (
                        "Collection episode edited successfully.\n"
                        f"Collection ID: {result['collection_id']}\n"
                        f"Episode number: {result['episode_number']}\n"
                        f"Record ID: {result['record_id']}"
                    ),
                }
            ],
            structuredContent=result,
        )

    @staticmethod
    def _failure(reason: str) -> GhostToolResult:
        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": f"Memory episode edit failed. Reason: {reason}.",
                }
            ],
            structuredContent={
                "edited": False,
                "memory_type": COLLECTION_MEMORY_TYPE,
                "reason": reason,
            },
            isError=True,
        )


def tool_metadata(
    required_scope: str | None = None,
) -> dict[str, Any]:
    """Build the OAuth-protected Collection episode edit descriptor."""
    scope = (
        required_scope
        if required_scope is not None
        else DEFAULT_REQUIRED_SCOPE
    ).strip()
    if not scope:
        raise ValueError("required_scope must not be empty")

    security_schemes = [
        {
            "type": "oauth2",
            "scopes": [scope],
        }
    ]

    return {
        "name": TOOL_NAME,
        "title": TOOL_TITLE,
        "description": TOOL_DESCRIPTION,
        "inputSchema": INPUT_SCHEMA,
        "outputSchema": OUTPUT_SCHEMA,
        "securitySchemes": security_schemes,
        "_meta": {
            "securitySchemes": security_schemes.copy(),
        },
        "annotations": {
            "destructiveHint": False,
            "readOnlyHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    }
