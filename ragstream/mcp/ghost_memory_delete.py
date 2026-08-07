"""Expose the MCP contract for deleting authenticated GHOST memories.

Main classes:
    GhostMemoryDeleteTool:
        Validates one delete request and reports the owner-scoped result.

Main methods and functions:
    call_sanitized():
        Deletes by exact record ID or safely handles an exact recall key.
    tool_metadata():
        Builds the destructive OAuth-protected MCP tool descriptor.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from ragstream.mcp.ghost_engineer_prompt import (
    DEFAULT_REQUIRED_SCOPE,
    GhostToolResult,
)
from ragstream.memory.mcp_memory_store import McpMemoryStore


TOOL_NAME = "ghost_memory_delete"
TOOL_TITLE = "GHOST Memory Delete"
TOOL_DESCRIPTION = (
    "Deletes memory episodes belonging to the authenticated user. Supply "
    "exactly one recall_key or record_id. A unique recall key deletes its one "
    "matching episode. If a recall key has several matches, nothing is deleted "
    "unless delete_all_matches is explicitly true; otherwise the tool returns "
    "their creation dates and record IDs so the user can select one."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "recall_key": {
            "type": "string",
            "minLength": 1,
        },
        "record_id": {
            "type": "string",
            "minLength": 1,
        },
        "delete_all_matches": {
            "type": "boolean",
            "default": False,
        },
    },
    "oneOf": [
        {
            "required": ["recall_key"],
            "not": {"required": ["record_id"]},
        },
        {
            "required": ["record_id"],
            "not": {"required": ["recall_key"]},
        },
    ],
    "additionalProperties": False,
}

MATCH_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "recall_key": {
            "type": "string",
            "minLength": 1,
        },
        "record_id": {
            "type": "string",
            "minLength": 1,
        },
        "created_at_utc": {
            "type": "string",
            "minLength": 1,
        },
    },
    "required": ["recall_key", "record_id", "created_at_utc"],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "deleted": {
            "type": "boolean",
        },
        "deleted_count": {
            "type": "integer",
            "minimum": 0,
        },
        "requires_selection": {
            "type": "boolean",
        },
        "matches": {
            "type": "array",
            "items": MATCH_ITEM_SCHEMA,
        },
    },
    "required": [
        "deleted",
        "deleted_count",
        "requires_selection",
        "matches",
    ],
    "additionalProperties": False,
}


class GhostMemoryDeleteTool:
    """Thin MCP adapter for deleting one authenticated user's memories."""

    def __init__(self, memory_store: McpMemoryStore) -> None:
        self._memory_store = memory_store

    def call_sanitized(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        """Validate the selector, perform deletion, and sanitize failures."""
        if not isinstance(owner_sub, str) or not owner_sub.strip():
            return self._failure("authenticated user is required")
        if not isinstance(arguments, Mapping):
            return self._failure("memory delete input is required")
        if set(arguments).difference(
            {"recall_key", "record_id", "delete_all_matches"}
        ):
            return self._failure("unsupported input property")

        recall_key = arguments.get("recall_key")
        record_id = arguments.get("record_id")
        delete_all_matches = arguments.get("delete_all_matches", False)
        if recall_key is not None and (
            not isinstance(recall_key, str) or not recall_key.strip()
        ):
            return self._failure("recall_key must be a non-empty string")
        if record_id is not None and (
            not isinstance(record_id, str) or not record_id.strip()
        ):
            return self._failure("record_id must be a non-empty string")
        if (recall_key is None) == (record_id is None):
            return self._failure(
                "exactly one of recall_key or record_id is required"
            )
        if not isinstance(delete_all_matches, bool):
            return self._failure("delete_all_matches must be a boolean")
        if record_id is not None and delete_all_matches:
            return self._failure(
                "delete_all_matches is allowed only with recall_key"
            )

        clean_recall_key = recall_key.strip() if recall_key is not None else None
        clean_record_id = record_id.strip() if record_id is not None else None
        try:
            result = self._memory_store.delete_memory(
                owner_sub=owner_sub,
                recall_key=clean_recall_key,
                record_id=clean_record_id,
                delete_all_matches=delete_all_matches,
            )
        except Exception:  # noqa: BLE001
            return self._failure("GHOST memory deletion failed")

        if result["deleted"]:
            text = (
                f"Deleted {result['deleted_count']} GHOST memory episode(s).\n"
                f"{self._format_matches(result['matches'])}"
            )
        elif result["requires_selection"]:
            text = (
                "No memory was deleted because the recall key has multiple "
                "matches. Delete one by record ID or explicitly request all "
                "matches.\n"
                f"{self._format_matches(result['matches'])}"
            )
        else:
            text = "No matching GHOST memory was found. Nothing was deleted."

        return GhostToolResult(
            content=[{"type": "text", "text": text}],
            structuredContent=result,
        )

    @staticmethod
    def _format_matches(matches: list[dict[str, str]]) -> str:
        lines: list[str] = []
        for memory in matches:
            recall_key = json.dumps(memory["recall_key"], ensure_ascii=False)
            lines.append(
                f"- Recall key: {recall_key}\n"
                f"  Created UTC: {memory['created_at_utc']}\n"
                f"  Record ID: {memory['record_id']}"
            )
        return "\n".join(lines)

    @staticmethod
    def _failure(reason: str) -> GhostToolResult:
        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": f"Memory deletion failed. Reason: {reason}.",
                }
            ],
            structuredContent={},
            isError=True,
        )


def tool_metadata(required_scope: str | None = None) -> dict[str, Any]:
    """Build the OAuth-protected MCP tool descriptor."""
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
        "_meta": {
            "securitySchemes": security_schemes.copy(),
        },
        "annotations": {
            "destructiveHint": True,
            "readOnlyHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    }