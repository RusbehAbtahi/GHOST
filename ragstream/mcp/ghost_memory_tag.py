"""Expose the MCP contract for saving one GHOST memory pair.

Main classes:
    GhostMemoryTagTool:
        Validates one tag request and passes it to the MCP memory store.

Main methods and functions:
    call_sanitized():
        Saves the authenticated user's selected visible input/output pair.
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


TOOL_NAME = "ghost_memory_tag"
TOOL_TITLE = "GHOST Memory Tag"
TOOL_DESCRIPTION = (
    "Saves one visible user/assistant pair from the current conversation under "
    "an exact recall key. By default, use the immediately preceding pair. If the "
    "user identifies an older pair by its text or position, use that pair instead. "
    "Copy the selected user message into input_text and its complete assistant "
    "response into output_text, both verbatim. One call saves one pair; call the "
    "tool separately for each pair when the user requests several. Do not use a "
    "summary, hidden reasoning, or an internal tool result."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "recall_key": {
            "type": "string",
            "minLength": 1,
        },
        "input_text": {
            "type": "string",
            "minLength": 1,
        },
        "output_text": {
            "type": "string",
            "minLength": 1,
        },
    },
    "required": ["recall_key", "input_text", "output_text"],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "saved": {
            "type": "boolean",
        },
        "recall_key": {
            "type": "string",
            "minLength": 1,
        },
        "record_id": {
            "type": "string",
            "minLength": 1,
        },
    },
    "required": ["saved"],
    "additionalProperties": False,
}


class GhostMemoryTagTool:
    """Thin MCP adapter for saving one authenticated memory pair."""

    def __init__(self, memory_store: McpMemoryStore) -> None:
        self._memory_store = memory_store

    def call_sanitized(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        """Validate the request, save the pair, and return a clear receipt."""
        if not isinstance(owner_sub, str) or not owner_sub.strip():
            return self._failure("authenticated user is required")

        if not isinstance(arguments, Mapping):
            return self._failure("memory tag input is required")

        if set(arguments).difference(
            {"recall_key", "input_text", "output_text"}
        ):
            return self._failure("unsupported input property")

        recall_key = arguments.get("recall_key")
        input_text = arguments.get("input_text")
        output_text = arguments.get("output_text")

        if not isinstance(recall_key, str) or not recall_key.strip():
            return self._failure(
                "recall_key is required and must be a non-empty string"
            )

        if not isinstance(input_text, str) or not input_text.strip():
            return self._failure(
                "input_text is required and must be a non-empty string"
            )

        if not isinstance(output_text, str) or not output_text.strip():
            return self._failure(
                "output_text is required and must be a non-empty string"
            )

        clean_recall_key = recall_key.strip()

        try:
            record = self._memory_store.tag_memory(
                owner_sub=owner_sub,
                recall_key=clean_recall_key,
                input_text=input_text,
                output_text=output_text,
            )
        except Exception:  # noqa: BLE001
            return self._failure(
                "GHOST memory storage failed",
                recall_key=clean_recall_key,
            )

        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": (
                        "Memory saved successfully.\n"
                        f"Recall key: {clean_recall_key}\n"
                        f"Record ID: {record.record_id}"
                    ),
                }
            ],
            structuredContent={
                "saved": True,
                "recall_key": clean_recall_key,
                "record_id": record.record_id,
            },
        )

    @staticmethod
    def _failure(
        reason: str,
        recall_key: str | None = None,
    ) -> GhostToolResult:
        structured_content: dict[str, Any] = {"saved": False}
        if recall_key is not None:
            structured_content["recall_key"] = recall_key

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
            "readOnlyHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    }