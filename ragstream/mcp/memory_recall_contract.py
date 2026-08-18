"""Build the shared MCP Recall JSON schemas and routing constants.

Keeping the declarative MCP contract here prevents the Recall dispatcher from
growing beyond its routing responsibility. Model-facing prose still comes
from ``custom_memory_recall.json``; this module only builds deterministic JSON
Schema from that prose and the backend's supported constants.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ragstream.memory.mcp_clipboard_store import CLIPBOARD_MEMORY_TYPE
from ragstream.memory.mcp_memory_collection_retriever import (
    MAX_REQUESTED_EPISODE_NUMBERS,
    SELECTION_ALL,
    SELECTION_EPISODE_NUMBER,
    SELECTION_EPISODE_NUMBERS,
    SELECTION_FIRST,
    SELECTION_LAST,
    SELECTION_RANGE,
)
from ragstream.memory.mcp_memory_collection_store import (
    COLLECTION_MEMORY_TYPE,
)


WORKFLOW_SELECTION_REQUIRED = "selection_required"
WORKFLOW_COMPLETE = "complete"

RETRIEVAL_EXACT = "exact"
RETRIEVAL_SEMANTIC = "semantic"
RETRIEVAL_COLLECTION = "collection"
RETRIEVAL_CLIPBOARD = "clipboard"

EPISODIC_MEMORY_TYPE = "episodic"
RESULT_MODE_EPISODE = "episode"
RESULT_MODE_DESCRIPTION = "description"

MEMORY_TYPES = {
    CLIPBOARD_MEMORY_TYPE,
    EPISODIC_MEMORY_TYPE,
    COLLECTION_MEMORY_TYPE,
}
RESULT_MODES = {RESULT_MODE_EPISODE, RESULT_MODE_DESCRIPTION}
COLLECTION_SELECTION_MODES = {
    SELECTION_EPISODE_NUMBER,
    SELECTION_EPISODE_NUMBERS,
    SELECTION_RANGE,
    SELECTION_FIRST,
    SELECTION_LAST,
    SELECTION_ALL,
}
COLLECTION_ARGUMENTS = {
    "collection_id",
    "collection_name",
    "selection_mode",
    "episode_number",
    "episode_numbers",
    "range_start",
    "range_end",
    "count",
}


def build_recall_schemas(
    descriptions: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the complete shared Recall input and output schemas."""
    input_schema = {
        "type": "object",
        "properties": {
            "memory_type": _text_field(
                descriptions["memory_type"],
                enum=sorted(MEMORY_TYPES),
            ),
            "recall_key": _text_field(descriptions["recall_key"]),
            "record_id": _text_field(descriptions["record_id"]),
            "query_description": _text_field(
                descriptions["query_description"]
            ),
            "date_from": _text_field(descriptions["date_from"]),
            "date_to": _text_field(descriptions["date_to"]),
            "collection_id": _text_field(descriptions["collection_id"]),
            "collection_name": _text_field(
                descriptions["collection_name"]
            ),
            "selection_mode": _text_field(
                descriptions["selection_mode"],
                enum=sorted(COLLECTION_SELECTION_MODES),
            ),
            "episode_number": _positive_integer_field(
                descriptions["episode_number"]
            ),
            "episode_numbers": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_REQUESTED_EPISODE_NUMBERS,
                "items": {"type": "integer", "minimum": 1},
                "description": descriptions["episode_numbers"],
            },
            "range_start": _positive_integer_field(
                descriptions["range_start"]
            ),
            "range_end": _positive_integer_field(
                descriptions["range_end"]
            ),
            "count": {
                **_positive_integer_field(descriptions["count"]),
                "maximum": MAX_REQUESTED_EPISODE_NUMBERS,
            },
            "result_mode": {
                **_text_field(
                    descriptions["result_mode"],
                    enum=sorted(RESULT_MODES),
                ),
                "default": RESULT_MODE_EPISODE,
            },
        },
        "anyOf": [
            {"required": ["recall_key"]},
            {"required": ["record_id"]},
            {"required": ["query_description"]},
            {
                "required": ["memory_type", "selection_mode"],
                "properties": {
                    "memory_type": {"const": COLLECTION_MEMORY_TYPE}
                },
            },
        ],
        "additionalProperties": False,
    }

    candidate_schema = {
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

    collection_episode_schema = {
        "type": "object",
        "properties": {
            "episode_number": {"type": "integer", "minimum": 1},
            "record_id": {"type": "string", "minLength": 1},
            "recall_key": {"type": "string", "minLength": 1},
            "episode_title": {"type": "string"},
            "episode_description": {"type": "string"},
            "created_at_utc": {"type": "string"},
            "input_text": {"type": "string"},
            "output_text": {"type": "string"},
            "active_retrieval_brief_title": {"type": "string"},
            "active_retrieval_brief": {"type": "string"},
            "active_retrieval_brief_contributor_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "episode_number",
            "record_id",
            "recall_key",
            "episode_title",
            "episode_description",
            "created_at_utc",
        ],
        "additionalProperties": False,
    }

    output_schema = {
        "type": "object",
        "properties": {
            "workflow_state": {
                "type": "string",
                "enum": [WORKFLOW_SELECTION_REQUIRED, WORKFLOW_COMPLETE],
            },
            "retrieval_path": {
                "type": "string",
                "enum": [
                    RETRIEVAL_EXACT,
                    RETRIEVAL_SEMANTIC,
                    RETRIEVAL_COLLECTION,
                    RETRIEVAL_CLIPBOARD,
                ],
            },
            "result_mode": {
                "type": "string",
                "enum": sorted(RESULT_MODES),
            },
            "memory_type": {"type": "string"},
            "file_id": {"type": "string"},
            "recall_key": {"type": "string", "minLength": 1},
            "record_id": {"type": "string", "minLength": 1},
            "sequence_number": {"type": "integer", "minimum": 0},
            "episode_title": {"type": "string"},
            "episode_description": {"type": "string"},
            "created_at_utc": {"type": "string"},
            "expires_at_utc": {"type": "string"},
            "input_text": {"type": "string"},
            "output_text": {"type": "string"},
            "active_retrieval_brief_title": {"type": "string"},
            "active_retrieval_brief": {"type": "string"},
            "active_retrieval_brief_contributor_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
            "candidate_count": {"type": "integer", "minimum": 0},
            "candidates": {
                "type": "array",
                "maxItems": 10,
                "items": candidate_schema,
            },
            "collection_id": {"type": "string", "minLength": 1},
            "collection_name": {"type": "string", "minLength": 1},
            "collection_description": {"type": "string"},
            "selection_mode": {
                "type": "string",
                "enum": sorted(COLLECTION_SELECTION_MODES),
            },
            "requested_episode_numbers": _positive_integer_array(),
            "returned_episode_numbers": _positive_integer_array(),
            "unavailable_episode_numbers": _positive_integer_array(),
            "omitted_episode_numbers": _positive_integer_array(),
            "episodes": {
                "type": "array",
                "items": collection_episode_schema,
            },
            "truncated": {"type": "boolean"},
            "token_limit": {"type": "integer", "minimum": 1},
            "estimated_tokens": {"type": "integer", "minimum": 0},
            "reason": {"type": "string"},
        },
        "required": ["workflow_state", "retrieval_path", "result_mode"],
        "additionalProperties": False,
    }
    return input_schema, output_schema


def _text_field(
    description: str,
    *,
    enum: list[str] | None = None,
) -> dict[str, Any]:
    """Build one non-empty string field."""
    field: dict[str, Any] = {
        "type": "string",
        "minLength": 1,
        "description": description,
    }
    if enum is not None:
        field["enum"] = enum
    return field


def _positive_integer_field(description: str) -> dict[str, Any]:
    """Build one positive integer field."""
    return {
        "type": "integer",
        "minimum": 1,
        "description": description,
    }


def _positive_integer_array() -> dict[str, Any]:
    """Build an array containing positive integers."""
    return {
        "type": "array",
        "items": {"type": "integer", "minimum": 1},
    }