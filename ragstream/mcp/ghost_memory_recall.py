"""Expose exact and intelligent Episodic Recall through one MCP tool.

This module validates Recall requests and selects the backend's exact or
semantic path. It returns a deterministic workflow state so the client knows
whether to select a candidate or publish the final result. Model-facing
instructions are loaded from custom_memory_recall.json.

Main classes:
    GhostMemoryRecallTool:
        Adapts one MCP Recall call to exact fetch or semantic candidate search.

Main methods and functions:
    call_sanitized():
        Validates the request and executes the appropriate retrieval stage.
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
from ragstream.memory.mcp_memory_store import McpMemoryStore


TOOL_NAME = "ghost_memory_recall"
TOOL_TITLE = "GHOST Memory Recall"

WORKFLOW_SELECTION_REQUIRED = "selection_required"
WORKFLOW_COMPLETE = "complete"
RETRIEVAL_EXACT = "exact"
RETRIEVAL_SEMANTIC = "semantic"
RESULT_MODE_EPISODE = "episode"
RESULT_MODE_DESCRIPTION = "description"

_INSTRUCTIONS = load_memory_tool_instructions("custom_memory_recall.json")
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
        "record_id": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions["record_id"],
        },
        "query_description": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions[
                "query_description"
            ],
        },
        "date_from": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions["date_from"],
        },
        "date_to": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions["date_to"],
        },
        "result_mode": {
            "type": "string",
            "enum": [RESULT_MODE_EPISODE, RESULT_MODE_DESCRIPTION],
            "default": RESULT_MODE_EPISODE,
            "description": _INSTRUCTIONS.field_descriptions["result_mode"],
        },
    },
    "oneOf": [
        {
            "required": ["recall_key"],
            "not": {
                "anyOf": [
                    {"required": ["record_id"]},
                    {"required": ["query_description"]},
                ]
            },
        },
        {
            "required": ["record_id"],
            "not": {
                "anyOf": [
                    {"required": ["recall_key"]},
                    {"required": ["query_description"]},
                ]
            },
        },
        {
            "required": ["query_description"],
            "not": {
                "anyOf": [
                    {"required": ["recall_key"]},
                    {"required": ["record_id"]},
                ]
            },
        },
    ],
    "additionalProperties": False,
}

_CANDIDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "record_id": {"type": "string", "minLength": 1},
        "recall_key": {"type": "string", "minLength": 1},
        "episode_title": {"type": "string"},
        "episode_description": {"type": "string", "minLength": 1},
        "created_at_utc": {"type": "string", "minLength": 1},
        "cosine_similarity": {"type": ["number", "null"]},
    },
    "required": [
        "record_id",
        "recall_key",
        "episode_title",
        "episode_description",
        "created_at_utc",
        "cosine_similarity",
    ],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "workflow_state": {
            "type": "string",
            "enum": [WORKFLOW_SELECTION_REQUIRED, WORKFLOW_COMPLETE],
        },
        "retrieval_path": {
            "type": "string",
            "enum": [RETRIEVAL_EXACT, RETRIEVAL_SEMANTIC],
        },
        "result_mode": {
            "type": "string",
            "enum": [RESULT_MODE_EPISODE, RESULT_MODE_DESCRIPTION],
        },
        "recall_key": {"type": "string", "minLength": 1},
        "record_id": {"type": "string", "minLength": 1},
        "episode_title": {"type": "string"},
        "episode_description": {"type": "string"},
        "created_at_utc": {"type": "string"},
        "input_text": {"type": "string"},
        "output_text": {"type": "string"},
        "candidate_count": {"type": "integer", "minimum": 0},
        "candidates": {
            "type": "array",
            "maxItems": 10,
            "items": _CANDIDATE_SCHEMA,
        },
        "reason": {"type": "string"},
    },
    "required": [
        "workflow_state",
        "retrieval_path",
        "result_mode",
    ],
    "additionalProperties": False,
}


class GhostMemoryRecallTool:
    """Adapt authenticated exact and intelligent Episodic Recall calls."""

    def __init__(self, memory_store: McpMemoryStore) -> None:
        self._memory_store = memory_store

    def call_sanitized(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        """Validate and execute one exact or semantic Recall stage."""
        if not isinstance(owner_sub, str) or not owner_sub.strip():
            return self._failure(
                "authenticated user is required",
                retrieval_path=RETRIEVAL_EXACT,
                result_mode=RESULT_MODE_EPISODE,
            )
        if not isinstance(arguments, Mapping):
            return self._failure(
                "memory recall input is required",
                retrieval_path=RETRIEVAL_EXACT,
                result_mode=RESULT_MODE_EPISODE,
            )

        allowed_properties = {
            "recall_key",
            "record_id",
            "query_description",
            "date_from",
            "date_to",
            "result_mode",
        }
        if set(arguments).difference(allowed_properties):
            return self._failure(
                "unsupported input property",
                retrieval_path=RETRIEVAL_EXACT,
                result_mode=RESULT_MODE_EPISODE,
            )

        result_mode = arguments.get(
            "result_mode",
            RESULT_MODE_EPISODE,
        )
        if (
            not isinstance(result_mode, str)
            or result_mode not in {
                RESULT_MODE_EPISODE,
                RESULT_MODE_DESCRIPTION,
            }
        ):
            return self._failure(
                "result_mode must be episode or description",
                retrieval_path=RETRIEVAL_EXACT,
                result_mode=RESULT_MODE_EPISODE,
            )

        recall_key = self._read_optional_text(arguments, "recall_key")
        record_id = self._read_optional_text(arguments, "record_id")
        query_description = self._read_optional_text(
            arguments,
            "query_description",
        )
        date_from = self._read_optional_text(arguments, "date_from")
        date_to = self._read_optional_text(arguments, "date_to")

        invalid_fields = [
            field_name
            for field_name, value in (
                ("recall_key", recall_key),
                ("record_id", record_id),
                ("query_description", query_description),
                ("date_from", date_from),
                ("date_to", date_to),
            )
            if value is False
        ]
        if invalid_fields:
            return self._failure(
                f"{invalid_fields[0]} must be a non-empty string",
                retrieval_path=RETRIEVAL_EXACT,
                result_mode=result_mode,
            )

        exact_identifiers = [
            value
            for value in (recall_key, record_id)
            if isinstance(value, str)
        ]
        if len(exact_identifiers) > 1:
            return self._failure(
                "supply exactly one of recall_key or record_id",
                retrieval_path=RETRIEVAL_EXACT,
                result_mode=result_mode,
            )

        if exact_identifiers:
            if isinstance(query_description, str):
                return self._failure(
                    "query_description cannot accompany an exact identifier",
                    retrieval_path=RETRIEVAL_EXACT,
                    result_mode=result_mode,
                )
            if isinstance(date_from, str) or isinstance(date_to, str):
                return self._failure(
                    "date filters are available only for intelligent recall",
                    retrieval_path=RETRIEVAL_EXACT,
                    result_mode=result_mode,
                )
            return self._recall_exact(
                owner_sub=owner_sub,
                recall_key=recall_key if isinstance(recall_key, str) else None,
                record_id=record_id if isinstance(record_id, str) else None,
                result_mode=result_mode,
            )

        if not isinstance(query_description, str):
            return self._failure(
                "query_description is required when no exact identifier is known",
                retrieval_path=RETRIEVAL_SEMANTIC,
                result_mode=result_mode,
            )

        return self._search_candidates(
            owner_sub=owner_sub,
            query_description=query_description,
            date_from=date_from if isinstance(date_from, str) else None,
            date_to=date_to if isinstance(date_to, str) else None,
            result_mode=result_mode,
        )

    def _recall_exact(
        self,
        *,
        owner_sub: str,
        recall_key: str | None,
        record_id: str | None,
        result_mode: str,
    ) -> GhostToolResult:
        try:
            memory = self._memory_store.recall_memory(
                owner_sub=owner_sub,
                recall_key=recall_key,
                record_id=record_id,
            )
        except ValueError as error:
            return self._failure(
                str(error),
                retrieval_path=RETRIEVAL_EXACT,
                result_mode=result_mode,
            )
        except Exception:  # noqa: BLE001
            return self._failure(
                "GHOST memory recall failed",
                retrieval_path=RETRIEVAL_EXACT,
                result_mode=result_mode,
            )

        if memory is None:
            selector = recall_key if recall_key is not None else record_id
            return self._failure(
                f'no memory found for exact identifier "{selector}"',
                retrieval_path=RETRIEVAL_EXACT,
                result_mode=result_mode,
            )

        structured_content: dict[str, Any] = {
            "workflow_state": WORKFLOW_COMPLETE,
            "retrieval_path": RETRIEVAL_EXACT,
            "result_mode": result_mode,
            "recall_key": memory["recall_key"],
            "record_id": memory["record_id"],
            "episode_title": memory["episode_title"],
            "episode_description": memory["episode_description"],
            "created_at_utc": memory["created_at_utc"],
        }

        if result_mode == RESULT_MODE_DESCRIPTION:
            text = memory["episode_description"]
        else:
            structured_content["input_text"] = memory["input_text"]
            structured_content["output_text"] = memory["output_text"]
            text = (
                f"Episode title: {memory['episode_title']}\n"
                f"Episode description: {memory['episode_description']}\n\n"
                f"Input:\n{memory['input_text']}\n\n"
                f"Output:\n{memory['output_text']}"
            )

        return GhostToolResult(
            content=[{"type": "text", "text": text}],
            structuredContent=structured_content,
        )

    def _search_candidates(
        self,
        *,
        owner_sub: str,
        query_description: str,
        date_from: str | None,
        date_to: str | None,
        result_mode: str,
    ) -> GhostToolResult:
        try:
            candidates = self._memory_store.search_episodic_memories(
                owner_sub=owner_sub,
                query_description=query_description,
                date_from=date_from,
                date_to=date_to,
            )
        except ValueError as error:
            return self._failure(
                str(error),
                retrieval_path=RETRIEVAL_SEMANTIC,
                result_mode=result_mode,
            )
        except Exception:  # noqa: BLE001
            return self._failure(
                "GHOST intelligent memory recall failed",
                retrieval_path=RETRIEVAL_SEMANTIC,
                result_mode=result_mode,
            )

        if not candidates:
            return self._failure(
                "no Episodic Memory candidates matched the request",
                retrieval_path=RETRIEVAL_SEMANTIC,
                result_mode=result_mode,
            )

        lines = [
            "Candidate selection is required before the final episode fetch."
        ]
        for position, candidate in enumerate(candidates, start=1):
            lines.extend(
                [
                    "",
                    f"Candidate {position}",
                    f"Record ID: {candidate['record_id']}",
                    f"Title: {candidate['episode_title']}",
                    f"Description: {candidate['episode_description']}",
                    f"Created: {candidate['created_at_utc']}",
                ]
            )

        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": "\n".join(lines),
                }
            ],
            structuredContent={
                "workflow_state": WORKFLOW_SELECTION_REQUIRED,
                "retrieval_path": RETRIEVAL_SEMANTIC,
                "result_mode": result_mode,
                "candidate_count": len(candidates),
                "candidates": candidates,
            },
        )

    @staticmethod
    def _read_optional_text(
        arguments: Mapping[str, Any],
        field_name: str,
    ) -> str | bool | None:
        if field_name not in arguments:
            return None

        value = arguments.get(field_name)
        if not isinstance(value, str) or not value.strip():
            return False
        return value.strip()

    @staticmethod
    def _failure(
        reason: str,
        *,
        retrieval_path: str,
        result_mode: str,
    ) -> GhostToolResult:
        return GhostToolResult(
            content=[{"type": "text", "text": reason}],
            structuredContent={
                "workflow_state": WORKFLOW_COMPLETE,
                "retrieval_path": retrieval_path,
                "result_mode": result_mode,
                "reason": reason,
            },
            isError=True,
        )


def tool_metadata(required_scope: str | None = None) -> dict[str, Any]:
    """Build the OAuth-protected MCP Recall tool descriptor."""
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
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    }