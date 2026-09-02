"""Expose Collection Memory initialization through MCP.

This module validates one authenticated initialization request and delegates
durable Collection creation to McpMemoryCollectionStore. Collection append,
recall, listing, and deletion remain in the shared memory tools.

Main classes:
    GhostMemoryCollectionInitTool:
        Adapts one MCP initialization request to the Collection backend.

Main methods and functions:
    call_sanitized():
        Creates an empty owner-scoped Collection and returns its stable ID.
    tool_metadata():
        Builds the OAuth-protected MCP tool descriptor.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ragstream.mcp.mcp_tool_contracts import (
    DEFAULT_REQUIRED_SCOPE,
    GhostToolResult,
)
from ragstream.mcp.memory_tool_instructions import (
    load_memory_tool_instructions,
)
from ragstream.memory.mcp_memory_collection_store import (
    McpMemoryCollectionStore,
)


TOOL_NAME = "ghost_memory_collection_init"
TOOL_TITLE = "GHOST Collection Memory Initialize"
WORKFLOW_COMPLETE = "complete"

_INSTRUCTIONS = load_memory_tool_instructions(
    "custom_memory_collection_init.json"
)
TOOL_DESCRIPTION = _INSTRUCTIONS.tool_description
SERVER_INSTRUCTIONS = _INSTRUCTIONS.server_instruction

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "collection_name": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions[
                "collection_name"
            ],
        },
        "collection_description": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions[
                "collection_description"
            ],
        },
    },
    "required": ["collection_name", "collection_description"],
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
        "collection_id": {"type": "string", "minLength": 1},
        "collection_name": {"type": "string", "minLength": 1},
        "collection_description": {
            "type": "string",
            "minLength": 1,
        },
        "created_at_utc": {"type": "string", "minLength": 1},
        "record_count": {"type": "integer", "minimum": 0},
        "next_sequence_number": {"type": "integer", "minimum": 1},
        "reason": {"type": "string"},
    },
    "required": ["created", "workflow_state"],
    "additionalProperties": False,
}


class GhostMemoryCollectionInitTool:
    """Adapt authenticated Collection initialization to persistence."""

    def __init__(self, collection_store: McpMemoryCollectionStore) -> None:
        self._collection_store = collection_store

    def call_sanitized(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        """Validate and create one empty owner-scoped Collection."""
        if not isinstance(owner_sub, str) or not owner_sub.strip():
            return self._failure("authenticated user is required")
        if not isinstance(arguments, Mapping):
            return self._failure(
                "Collection initialization input is required"
            )
        if set(arguments).difference(
            {"collection_name", "collection_description"}
        ):
            return self._failure("unsupported input property")

        collection_name = arguments.get("collection_name")
        collection_description = arguments.get(
            "collection_description"
        )

        if (
            not isinstance(collection_name, str)
            or not collection_name.strip()
        ):
            return self._failure(
                "collection_name is required and must be a "
                "non-empty string"
            )
        if (
            not isinstance(collection_description, str)
            or not collection_description.strip()
        ):
            return self._failure(
                "collection_description is required and must be a "
                "non-empty string"
            )

        try:
            collection = self._collection_store.initialize_collection(
                owner_sub=owner_sub,
                collection_name=collection_name.strip(),
                collection_description=collection_description.strip(),
            )
        except ValueError as error:
            return self._failure(str(error))
        except Exception:  # noqa: BLE001
            return self._failure(
                "GHOST Collection initialization failed"
            )

        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": (
                        "Collection Memory initialized successfully.\n"
                        f"Collection name: "
                        f"{collection['collection_name']}\n"
                        f"Collection ID: "
                        f"{collection['collection_id']}\n"
                        f"Created UTC: "
                        f"{collection['created_at_utc']}"
                    ),
                }
            ],
            structuredContent={
                "created": True,
                "workflow_state": WORKFLOW_COMPLETE,
                **collection,
            },
        )

    @staticmethod
    def _failure(reason: str) -> GhostToolResult:
        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": (
                        "Collection Memory was NOT initialized. "
                        f"Reason: {reason}."
                    ),
                }
            ],
            structuredContent={
                "created": False,
                "workflow_state": WORKFLOW_COMPLETE,
                "reason": reason,
            },
            isError=True,
        )


def tool_metadata(
    required_scope: str | None = None,
) -> dict[str, Any]:
    """Build the OAuth-protected Collection initialization descriptor."""
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
            "idempotentHint": False,
            "openWorldHint": False,
        },
    }