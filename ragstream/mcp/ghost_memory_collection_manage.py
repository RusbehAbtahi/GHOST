"""Expose Collection move, archive, and restore through MCP.

This module validates one exact owner-scoped Collection management request and
delegates durable location changes to McpMemoryCollectionManager.

Main classes:
    GhostMemoryCollectionManageTool:
        Adapts move, archive, and restore requests to the Collection backend.

Main methods and functions:
    call_sanitized():
        Executes one validated Collection management action.
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
from ragstream.mcp.memory_tool_instructions import load_memory_tool_instructions
from ragstream.memory.mcp_memory_collection_manager import (
    McpMemoryCollectionManager,
)


TOOL_NAME = "ghost_memory_collection_manage"
TOOL_TITLE = "GHOST Collection Memory Manage"
WORKFLOW_COMPLETE = "complete"
ACTION_MOVE = "move"
ACTION_ARCHIVE = "archive"
ACTION_RESTORE = "restore"
_ACTIONS = {ACTION_MOVE, ACTION_ARCHIVE, ACTION_RESTORE}

_INSTRUCTIONS = load_memory_tool_instructions("custom_memory_collection_manage.json")
TOOL_DESCRIPTION = _INSTRUCTIONS.tool_description
SERVER_INSTRUCTIONS = _INSTRUCTIONS.server_instruction

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": sorted(_ACTIONS),
            "description": _INSTRUCTIONS.field_descriptions["action"],
        },
        "collection_id": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions["collection_id"],
        },
        "destination_folder": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions["destination_folder"],
        },
    },
    "required": ["action", "collection_id"],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "success": {"type": "boolean"},
        "workflow_state": {"type": "string", "enum": [WORKFLOW_COMPLETE]},
        "action": {"type": "string", "enum": sorted(_ACTIONS)},
        "collection_id": {"type": "string", "minLength": 1},
        "collection_name": {"type": "string"},
        "folder": {"type": "string", "minLength": 1},
        "reason": {"type": "string"},
    },
    "required": ["success", "workflow_state"],
    "additionalProperties": False,
}


class GhostMemoryCollectionManageTool:
    """Validate and execute exact Collection location-management requests."""

    def __init__(self, manager: McpMemoryCollectionManager) -> None:
        self._manager = manager

    def call_sanitized(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        """Execute one move, archive, or restore action."""
        if not isinstance(owner_sub, str) or not owner_sub.strip():
            return self._failure("authenticated user is required")
        if not isinstance(arguments, Mapping):
            return self._failure("Collection management input is required")
        if set(arguments).difference(
            {"action", "collection_id", "destination_folder"}
        ):
            return self._failure("unsupported input property")

        action = arguments.get("action")
        collection_id = arguments.get("collection_id")
        destination = arguments.get("destination_folder")
        if action not in _ACTIONS:
            return self._failure("unsupported Collection management action")
        if not isinstance(collection_id, str) or not collection_id.strip():
            return self._failure("collection_id must be a non-empty string")
        if destination is not None and (
            not isinstance(destination, str) or not destination.strip()
        ):
            return self._failure("destination_folder must be a non-empty string")

        try:
            if action == ACTION_MOVE:
                if not isinstance(destination, str):
                    return self._failure("move requires destination_folder")
                result = self._manager.move_collection(
                    owner_sub,
                    collection_id.strip(),
                    destination.strip(),
                )
            elif action == ACTION_ARCHIVE:
                if destination is not None:
                    return self._failure("archive does not use destination_folder")
                result = self._manager.archive_collection(
                    owner_sub,
                    collection_id.strip(),
                )
            else:
                result = self._manager.restore_collection(
                    owner_sub,
                    collection_id.strip(),
                    destination.strip() if isinstance(destination, str) else None,
                )
        except ValueError as error:
            return self._failure(str(error))
        except Exception:  # noqa: BLE001
            return self._failure("GHOST Collection management failed")

        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": (
                        f"Collection {result['action']} completed. "
                        f"Collection: {result['collection_name']} | "
                        f"Folder: {result['folder']}"
                    ),
                }
            ],
            structuredContent={
                "success": True,
                "workflow_state": WORKFLOW_COMPLETE,
                **result,
            },
        )

    @staticmethod
    def _failure(reason: str) -> GhostToolResult:
        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": f"Collection management failed. Reason: {reason}.",
                }
            ],
            structuredContent={
                "success": False,
                "workflow_state": WORKFLOW_COMPLETE,
                "reason": reason,
            },
            isError=True,
        )


def tool_metadata(required_scope: str | None = None) -> dict[str, Any]:
    """Build the OAuth-protected Collection management descriptor."""
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
            "destructiveHint": True,
            "readOnlyHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    }
