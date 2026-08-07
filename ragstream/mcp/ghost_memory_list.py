"""Expose the MCP contract for listing one user's saved GHOST memories.

Main classes:
    GhostMemoryListTool:
        Validates one list request and returns owner-scoped memory identifiers.

Main methods and functions:
    call_sanitized():
        Lists episode titles, recall keys, record IDs, and creation dates.
    tool_metadata():
        Builds the OAuth-protected MCP tool descriptor.
"""

from __future__ import annotations

from typing import Any, Mapping

from ragstream.mcp.ghost_engineer_prompt import (
    DEFAULT_REQUIRED_SCOPE,
    GhostToolResult,
)
from ragstream.memory.mcp_memory_store import McpMemoryStore


TOOL_NAME = "ghost_memory_list"
TOOL_TITLE = "GHOST Memory List"
TOOL_DESCRIPTION = (
    "Lists all memory episodes saved by the authenticated user, newest first. "
    "Use this tool when the user wants to see or rediscover saved recall keys. "
    "Each entry contains the episode title, exact recall key, creation date, "
    "and record ID; stored input and output text are not returned."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

MEMORY_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "recall_key": {
            "type": "string",
            "minLength": 1,
        },
        "episode_title": {
            "type": "string",
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
    "required": [
        "recall_key",
        "episode_title",
        "record_id",
        "created_at_utc",
    ],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "memories": {
            "type": "array",
            "items": MEMORY_ITEM_SCHEMA,
        },
        "total_count": {
            "type": "integer",
            "minimum": 0,
        },
    },
    "required": ["memories", "total_count"],
    "additionalProperties": False,
}


class GhostMemoryListTool:
    """Thin MCP adapter for listing one authenticated user's memories."""

    def __init__(self, memory_store: McpMemoryStore) -> None:
        self._memory_store = memory_store

    def call_sanitized(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        """Validate the request, list memories, and sanitize failures."""
        if not isinstance(owner_sub, str) or not owner_sub.strip():
            return self._failure("authenticated user is required")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, Mapping):
            return self._failure("memory list input is required")
        if arguments:
            return self._failure("unsupported input property")

        try:
            memories = self._memory_store.list_memories(owner_sub=owner_sub)
        except Exception:  # noqa: BLE001
            return self._failure("GHOST memory listing failed")

        if memories:
            lines = [
                "Saved GHOST memories, newest first:",
                "",
                "| Episode title | Recall key | Created UTC | Record ID |",
                "| --- | --- | --- | --- |",
            ]
            for memory in memories:
                lines.append(
                    "| "
                    f"{self._markdown_cell(memory['episode_title'])} | "
                    f"{self._markdown_cell(memory['recall_key'])} | "
                    f"{self._markdown_cell(memory['created_at_utc'])} | "
                    f"{self._markdown_cell(memory['record_id'])} |"
                )
            text = "\n".join(lines)
        else:
            text = "No saved GHOST memories were found."

        return GhostToolResult(
            content=[{"type": "text", "text": text}],
            structuredContent={
                "memories": memories,
                "total_count": len(memories),
            },
        )

    @staticmethod
    def _markdown_cell(value: str) -> str:
        """Escape one metadata value for safe display inside a Markdown table."""
        return (
            str(value)
            .replace("\\", "\\\\")
            .replace("|", "\\|")
            .replace("\r", " ")
            .replace("\n", " ")
        )

    @staticmethod
    def _failure(reason: str) -> GhostToolResult:
        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": f"Memory list failed. Reason: {reason}.",
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
            "destructiveHint": False,
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    }