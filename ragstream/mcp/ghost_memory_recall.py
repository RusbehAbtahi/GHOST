"""Expose the MCP contract for recalling one GHOST memory pair.

Main classes:
    GhostMemoryRecallTool:
        Validates one recall request and passes it to the MCP memory store.

Main methods and functions:
    call_sanitized():
        Returns the authenticated user's stored input/output pair.
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


TOOL_NAME = "ghost_memory_recall"
TOOL_TITLE = "GHOST Memory Recall"
TOOL_DESCRIPTION = (
    "Recalls the stored user/assistant pair for an exact recall key and returns "
    "its record ID, original input, and original output."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "recall_key": {
            "type": "string",
            "minLength": 1,
        },
    },
    "required": ["recall_key"],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
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
        "input_text": {
            "type": "string",
        },
        "output_text": {
            "type": "string",
        },
    },
    "required": ["recall_key", "record_id", "input_text", "output_text"],
    "additionalProperties": False,
}


class GhostMemoryRecallTool:
    """Thin MCP adapter for recalling one authenticated memory pair."""

    def __init__(self, memory_store: McpMemoryStore) -> None:
        self._memory_store = memory_store

    def call_sanitized(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        """Validate the request, recall the pair, and sanitize failures."""
        if not isinstance(owner_sub, str) or not owner_sub:
            return GhostToolResult(
                content=[{"type": "text", "text": "authenticated user is required"}],
                structuredContent={},
                isError=True,
            )

        if not isinstance(arguments, Mapping):
            return GhostToolResult(
                content=[{"type": "text", "text": "memory recall input is required"}],
                structuredContent={},
                isError=True,
            )

        if set(arguments).difference({"recall_key"}):
            return GhostToolResult(
                content=[{"type": "text", "text": "unsupported input property"}],
                structuredContent={},
                isError=True,
            )

        recall_key = arguments.get("recall_key")
        if not isinstance(recall_key, str) or not recall_key.strip():
            return GhostToolResult(
                content=[
                    {
                        "type": "text",
                        "text": (
                            "recall_key is required and must be a non-empty string"
                        ),
                    }
                ],
                structuredContent={},
                isError=True,
            )

        clean_recall_key = recall_key.strip()

        try:
            memory = self._memory_store.recall_memory(
                owner_sub=owner_sub,
                recall_key=clean_recall_key,
            )

            if memory is None:
                return GhostToolResult(
                    content=[
                        {
                            "type": "text",
                            "text": (
                                "No memory found for recall key "
                                f'"{clean_recall_key}".'
                            ),
                        }
                    ],
                    structuredContent={},
                    isError=True,
                )

            record_id = memory["record_id"]
            input_text = memory["input_text"]
            output_text = memory["output_text"]
        except Exception:  # noqa: BLE001
            return GhostToolResult(
                content=[{"type": "text", "text": "GHOST memory recall failed"}],
                structuredContent={},
                isError=True,
            )

        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": f"Input:\n{input_text}\n\nOutput:\n{output_text}",
                }
            ],
            structuredContent={
                "recall_key": clean_recall_key,
                "record_id": record_id,
                "input_text": input_text,
                "output_text": output_text,
            },
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