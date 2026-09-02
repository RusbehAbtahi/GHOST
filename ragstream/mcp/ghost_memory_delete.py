"""Expose deterministic episode and whole-Collection deletion through MCP.

This module accepts only exact owner-scoped identifiers. Individual episodes
use Recall Key or Record ID; whole Collections use exact Collection ID and the
backend's volatile two-step confirmation state. Instructions live in JSON.

Main classes:
    GhostMemoryDeleteTool:
        Routes exact deletion to Collection or ordinary memory persistence.

Main methods and functions:
    call_sanitized():
        Validates and executes individual or whole-Collection deletion.
    tool_metadata():
        Builds the destructive OAuth-protected MCP tool descriptor.
"""

from __future__ import annotations

import json

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
    COLLECTION_MEMORY_TYPE,
    McpMemoryCollectionStore,
)
from ragstream.memory.mcp_memory_store import McpMemoryStore


TOOL_NAME = "ghost_memory_delete"
TOOL_TITLE = "GHOST Memory Delete"

DELETE_MODE_EPISODE = "episode"
DELETE_MODE_COLLECTION = "collection"

_INSTRUCTIONS = load_memory_tool_instructions(
    "custom_memory_delete.json"
)
TOOL_DESCRIPTION = _INSTRUCTIONS.tool_description
SERVER_INSTRUCTIONS = _INSTRUCTIONS.server_instruction

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "recall_key": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions[
                "recall_key"
            ],
        },
        "record_id": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions[
                "record_id"
            ],
        },
        "collection_id": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions[
                "collection_id"
            ],
        },
        "delete_all_matches": {
            "type": "boolean",
            "default": False,
            "description": _INSTRUCTIONS.field_descriptions[
                "delete_all_matches"
            ],
        },
    },
    "oneOf": [
        {
            "required": ["recall_key"],
            "not": {
                "anyOf": [
                    {"required": ["record_id"]},
                    {"required": ["collection_id"]},
                ]
            },
        },
        {
            "required": ["record_id"],
            "not": {
                "anyOf": [
                    {"required": ["recall_key"]},
                    {"required": ["collection_id"]},
                ]
            },
        },
        {
            "required": ["collection_id"],
            "not": {
                "anyOf": [
                    {"required": ["recall_key"]},
                    {"required": ["record_id"]},
                    {"required": ["delete_all_matches"]},
                ]
            },
        },
    ],
    "additionalProperties": False,
}

_MATCH_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "memory_type": {
            "type": "string",
        },
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
        },
        "collection_id": {
            "type": "string",
        },
        "episode_number": {
            "type": "integer",
            "minimum": 1,
        },
    },
    "required": [
        "recall_key",
        "record_id",
    ],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "deletion_mode": {
            "type": "string",
            "enum": [
                DELETE_MODE_EPISODE,
                DELETE_MODE_COLLECTION,
            ],
        },
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
            "items": _MATCH_ITEM_SCHEMA,
        },
        "confirmation_required": {
            "type": "boolean",
        },
        "delete_pending": {
            "type": "boolean",
        },
        "collection_id": {
            "type": "string",
            "minLength": 1,
        },
        "collection_name": {
            "type": "string",
            "minLength": 1,
        },
        "record_count": {
            "type": "integer",
            "minimum": 0,
        },
        "deleted_episode_count": {
            "type": "integer",
            "minimum": 0,
        },
        "reason": {
            "type": "string",
        },
    },
    "required": [
        "deletion_mode",
        "deleted",
        "deleted_count",
        "requires_selection",
        "matches",
        "confirmation_required",
        "delete_pending",
    ],
    "additionalProperties": False,
}


class GhostMemoryDeleteTool:
    """Route exact episode and whole-Collection deletion safely."""

    def __init__(
        self,
        memory_store: McpMemoryStore,
        collection_store: McpMemoryCollectionStore,
    ) -> None:
        self._memory_store = memory_store
        self._collection_store = collection_store

    def call_sanitized(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        """Validate one exact selector and execute its deletion path."""
        if not isinstance(owner_sub, str) or not owner_sub.strip():
            return self._failure(
                "authenticated user is required"
            )
        if not isinstance(arguments, Mapping):
            return self._failure(
                "memory delete input is required"
            )
        if set(arguments).difference(
            {
                "recall_key",
                "record_id",
                "collection_id",
                "delete_all_matches",
            }
        ):
            return self._failure(
                "unsupported input property"
            )

        selectors: dict[str, str] = {}

        for field_name in (
            "recall_key",
            "record_id",
            "collection_id",
        ):
            if field_name not in arguments:
                continue

            value = arguments.get(field_name)
            if (
                not isinstance(value, str)
                or not value.strip()
            ):
                return self._failure(
                    f"{field_name} must be a non-empty string"
                )

            selectors[field_name] = value.strip()

        if len(selectors) != 1:
            return self._failure(
                "exactly one recall_key, record_id, or "
                "collection_id is required"
            )

        delete_all_matches = arguments.get(
            "delete_all_matches",
            False,
        )
        if not isinstance(delete_all_matches, bool):
            return self._failure(
                "delete_all_matches must be a boolean"
            )

        if (
            "recall_key" not in selectors
            and delete_all_matches
        ):
            return self._failure(
                "delete_all_matches is allowed only with recall_key"
            )

        if "collection_id" in selectors:
            if "delete_all_matches" in arguments:
                return self._failure(
                    "delete_all_matches is not valid for "
                    "Collection deletion"
                )

            return self._delete_collection(
                owner_sub,
                selectors["collection_id"],
            )

        return self._delete_episode(
            owner_sub=owner_sub,
            recall_key=selectors.get("recall_key"),
            record_id=selectors.get("record_id"),
            delete_all_matches=delete_all_matches,
        )

    def _delete_episode(
        self,
        *,
        owner_sub: str,
        recall_key: str | None,
        record_id: str | None,
        delete_all_matches: bool,
    ) -> GhostToolResult:
        if not delete_all_matches:
            try:
                collection_result = (
                    self._collection_store.delete_episode(
                        owner_sub=owner_sub,
                        recall_key=recall_key,
                        record_id=record_id,
                    )
                )
            except ValueError as error:
                return self._failure(str(error))
            except Exception:  # noqa: BLE001
                return self._failure(
                    "GHOST Collection episode deletion failed"
                )

            if collection_result["deleted"]:
                match = {
                    "memory_type": COLLECTION_MEMORY_TYPE,
                    "recall_key": collection_result["recall_key"],
                    "record_id": collection_result["record_id"],
                    "collection_id": collection_result[
                        "collection_id"
                    ],
                    "episode_number": collection_result[
                        "episode_number"
                    ],
                }

                result = self._base_result(
                    DELETE_MODE_EPISODE
                )
                result.update(
                    {
                        "deleted": True,
                        "deleted_count": 1,
                        "matches": [match],
                    }
                )

                return GhostToolResult(
                    content=[
                        {
                            "type": "text",
                            "text": (
                                "Deleted Collection episode "
                                f"{match['episode_number']} "
                                "with Record ID "
                                f"{match['record_id']}."
                            ),
                        }
                    ],
                    structuredContent=result,
                )

        try:
            ordinary_result = self._memory_store.delete_memory(
                owner_sub=owner_sub,
                recall_key=recall_key,
                record_id=record_id,
                delete_all_matches=delete_all_matches,
            )
        except ValueError as error:
            return self._failure(str(error))
        except Exception:  # noqa: BLE001
            return self._failure(
                "GHOST memory deletion failed"
            )

        result = self._base_result(
            DELETE_MODE_EPISODE
        )
        result.update(ordinary_result)

        if ordinary_result["deleted"]:
            text = (
                f"Deleted {ordinary_result['deleted_count']} "
                "GHOST memory episode(s).\n"
                f"{self._format_matches(
                    ordinary_result['matches']
                )}"
            )
        elif ordinary_result["requires_selection"]:
            text = (
                "No memory was deleted because the exact Recall "
                "Key has multiple matches. Delete one by Record "
                "ID or explicitly request all exact matches.\n"
                f"{self._format_matches(
                    ordinary_result['matches']
                )}"
            )
        else:
            text = (
                "No matching GHOST memory was found. "
                "Nothing was deleted."
            )

        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": text,
                }
            ],
            structuredContent=result,
        )

    def _delete_collection(
        self,
        owner_sub: str,
        collection_id: str,
    ) -> GhostToolResult:
        try:
            backend_result = (
                self._collection_store.delete_collection(
                    owner_sub=owner_sub,
                    collection_id=collection_id,
                )
            )
        except ValueError as error:
            return self._failure(
                str(error),
                deletion_mode=DELETE_MODE_COLLECTION,
            )
        except Exception:  # noqa: BLE001
            return self._failure(
                "GHOST whole-Collection deletion failed",
                deletion_mode=DELETE_MODE_COLLECTION,
            )

        result = self._base_result(
            DELETE_MODE_COLLECTION
        )
        result.update(backend_result)
        result["deleted_count"] = int(
            backend_result.get(
                "deleted_episode_count",
                0,
            )
        )

        if backend_result["deleted"]:
            text = (
                "Collection Memory deleted successfully.\n"
                f"Collection: "
                f"{backend_result['collection_name']}\n"
                f"Collection ID: "
                f"{backend_result['collection_id']}\n"
                "Deleted episodes: "
                f"{backend_result['deleted_episode_count']}"
            )
        else:
            text = (
                "Collection deletion refused for safety. "
                "Nothing was deleted. Repeat the same exact "
                "Collection deletion request to confirm.\n"
                f"Collection: "
                f"{backend_result['collection_name']}\n"
                f"Collection ID: "
                f"{backend_result['collection_id']}"
            )

        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": text,
                }
            ],
            structuredContent=result,
        )

    @staticmethod
    def _base_result(
        deletion_mode: str,
    ) -> dict[str, Any]:
        return {
            "deletion_mode": deletion_mode,
            "deleted": False,
            "deleted_count": 0,
            "requires_selection": False,
            "matches": [],
            "confirmation_required": False,
            "delete_pending": False,
        }

    @staticmethod
    def _format_matches(
        matches: list[dict[str, str]],
    ) -> str:
        lines: list[str] = []

        for memory in matches:
            recall_key = json.dumps(
                memory["recall_key"],
                ensure_ascii=False,
            )
            lines.append(
                f"- Recall key: {recall_key}\n"
                f"  Created UTC: "
                f"{memory['created_at_utc']}\n"
                f"  Record ID: {memory['record_id']}"
            )

        return "\n".join(lines)

    @classmethod
    def _failure(
        cls,
        reason: str,
        *,
        deletion_mode: str = DELETE_MODE_EPISODE,
    ) -> GhostToolResult:
        result = cls._base_result(deletion_mode)
        result["reason"] = reason

        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": (
                        f"Memory deletion failed. Reason: {reason}."
                    ),
                }
            ],
            structuredContent=result,
            isError=True,
        )


def tool_metadata(
    required_scope: str | None = None,
) -> dict[str, Any]:
    """Build the OAuth-protected shared Delete tool descriptor."""
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
            "destructiveHint": True,
            "readOnlyHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    }