"""Expose the shared MCP Save contract for all supported memory modes.

This module validates one authenticated Save request and deterministically
routes it to Episodic persistence, Collection append, or Clipboard append.
Model-facing instructions are loaded from custom_memory_save.json.

Main classes:
    GhostMemoryTagTool:
        Adapts one MCP Save call to the selected owner-scoped backend.

Main methods and functions:
    call_sanitized():
        Validates, routes, saves, and returns the effective Recall Key.
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
from ragstream.memory.mcp_clipboard_store import (
    CLIPBOARD_MEMORY_TYPE,
    McpClipboardStore,
    is_clipboard_slot,
)
from ragstream.memory.mcp_memory_collection_store import (
    COLLECTION_MEMORY_TYPE,
    McpMemoryCollectionStore,
)
from ragstream.memory.mcp_memory_store import (
    MAX_EPISODE_TITLE_LENGTH,
    McpMemoryStore,
)


TOOL_NAME = "ghost_memory_tag"
TOOL_TITLE = "GHOST Memory Save"
WORKFLOW_COMPLETE = "complete"
EPISODIC_MEMORY_TYPE = "episodic"

_SUPPORTED_MEMORY_TYPES = {
    CLIPBOARD_MEMORY_TYPE,
    EPISODIC_MEMORY_TYPE,
    COLLECTION_MEMORY_TYPE,
}

_CLIPBOARD_SLOT_PATTERN = "^[Mm](?:[1-9]|[1-9][0-9]|100)$"

_INSTRUCTIONS = load_memory_tool_instructions("custom_memory_save.json")
TOOL_DESCRIPTION = _INSTRUCTIONS.tool_description
SERVER_INSTRUCTIONS = _INSTRUCTIONS.server_instruction

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "memory_type": {
            "type": "string",
            "enum": sorted(_SUPPORTED_MEMORY_TYPES),
            "default": EPISODIC_MEMORY_TYPE,
            "description": _INSTRUCTIONS.field_descriptions[
                "memory_type"
            ],
        },
        "recall_key": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions["recall_key"],
        },
        "collection_id": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions[
                "collection_id"
            ],
        },
        "collection_name": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions[
                "collection_name"
            ],
        },
        "episode_title": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_EPISODE_TITLE_LENGTH,
            "description": _INSTRUCTIONS.field_descriptions[
                "episode_title"
            ],
        },
        "episode_description": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions[
                "episode_description"
            ],
        },
        "input_text": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions["input_text"],
        },
        "output_text": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions["output_text"],
        },
        "active_retrieval_brief": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions[
                "active_retrieval_brief"
            ],
        },
    },
    "required": ["input_text", "output_text"],
    "oneOf": [
        {
            "properties": {
                "memory_type": {"const": COLLECTION_MEMORY_TYPE},
            },
            "required": [
                "memory_type",
                "episode_title",
                "episode_description",
                "active_retrieval_brief",
            ],
            "oneOf": [
                {
                    "required": ["collection_id"],
                    "not": {"required": ["collection_name"]},
                },
                {
                    "required": ["collection_name"],
                    "not": {"required": ["collection_id"]},
                },
            ],
        },
        {
            "properties": {
                "memory_type": {"const": CLIPBOARD_MEMORY_TYPE},
                "recall_key": {"pattern": _CLIPBOARD_SLOT_PATTERN},
            },
            "required": ["recall_key"],
            "not": {
                "anyOf": [
                    {"required": ["collection_id"]},
                    {"required": ["collection_name"]},
                    {"required": ["episode_title"]},
                    {"required": ["episode_description"]},
                    {"required": ["active_retrieval_brief"]},
                ]
            },
        },
        {
            "properties": {
                "memory_type": {"const": EPISODIC_MEMORY_TYPE},
                "recall_key": {
                    "not": {"pattern": _CLIPBOARD_SLOT_PATTERN}
                },
            },
            "required": [
                "recall_key",
                "episode_title",
                "episode_description",
            ],
        },
    ],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "saved": {"type": "boolean"},
        "workflow_state": {
            "type": "string",
            "enum": [WORKFLOW_COMPLETE],
        },
        "memory_type": {
            "type": "string",
            "enum": sorted(_SUPPORTED_MEMORY_TYPES),
        },
        "requested_recall_key": {
            "type": ["string", "null"],
        },
        "recall_key": {"type": "string", "minLength": 1},
        "episode_title": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_EPISODE_TITLE_LENGTH,
        },
        "episode_description": {"type": "string", "minLength": 1},
        "record_id": {"type": "string", "minLength": 1},
        "file_id": {"type": "string", "minLength": 1},
        "sequence_number": {"type": "integer", "minimum": 1},
        "expires_at_utc": {"type": "string", "minLength": 1},
        "collection_id": {"type": "string", "minLength": 1},
        "collection_name": {"type": "string", "minLength": 1},
        "episode_number": {"type": "integer", "minimum": 1},
        "created_at_utc": {"type": "string", "minLength": 1},
        "next_sequence_number": {"type": "integer", "minimum": 1},
        "reason": {"type": "string"},
    },
    "required": ["saved", "workflow_state"],
    "additionalProperties": False,
}


class GhostMemoryTagTool:
    """Route authenticated Save calls to the selected memory backend."""

    def __init__(
        self,
        memory_store: McpMemoryStore,
        collection_store: McpMemoryCollectionStore | None = None,
        clipboard_store: McpClipboardStore | None = None,
    ) -> None:
        """Create the Save interface over the shared memory stores."""
        self._memory_store = memory_store
        self._collection_store = collection_store or McpMemoryCollectionStore(
            memory_root=memory_store.memory_root,
            sqlite_path=memory_store.sqlite_path,
        )
        self._clipboard_store = clipboard_store or McpClipboardStore(
            memory_root=memory_store.memory_root,
            sqlite_path=memory_store.sqlite_path,
        )

    def call_sanitized(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        """Validate and execute one deterministic Save path."""
        if not isinstance(owner_sub, str) or not owner_sub.strip():
            return self._failure("authenticated user is required")
        if not isinstance(arguments, Mapping):
            return self._failure("memory save input is required")

        allowed_properties = {
            "memory_type",
            "recall_key",
            "collection_id",
            "collection_name",
            "episode_title",
            "episode_description",
            "input_text",
            "output_text",
            "active_retrieval_brief",
        }
        if set(arguments).difference(allowed_properties):
            return self._failure("unsupported input property")

        requested_memory_type = arguments.get(
            "memory_type",
            EPISODIC_MEMORY_TYPE,
        )
        if requested_memory_type not in _SUPPORTED_MEMORY_TYPES:
            return self._failure(
                "memory_type must be episodic, collection, or clipboard"
            )

        recall_key = self._read_optional_text(arguments, "recall_key")
        if recall_key is False:
            return self._failure(
                "recall_key must be a non-empty string"
            )

        clipboard_key = (
            recall_key
            if isinstance(recall_key, str)
            and is_clipboard_slot(recall_key)
            else None
        )
        memory_type = (
            CLIPBOARD_MEMORY_TYPE
            if clipboard_key is not None
            else requested_memory_type
        )

        if memory_type == CLIPBOARD_MEMORY_TYPE:
            return self._save_clipboard(
                owner_sub=owner_sub,
                arguments=arguments,
                recall_key=recall_key,
            )

        common_values = self._read_common_values(arguments)
        if isinstance(common_values, str):
            return self._failure(
                common_values,
                memory_type=memory_type,
            )

        if memory_type == COLLECTION_MEMORY_TYPE:
            return self._save_collection(
                owner_sub,
                arguments,
                common_values,
            )

        return self._save_episodic(
            owner_sub,
            arguments,
            common_values,
        )

    def _save_clipboard(
        self,
        *,
        owner_sub: str,
        arguments: Mapping[str, Any],
        recall_key: str | bool | None,
    ) -> GhostToolResult:
        """Append one exact visible Q/A pair to a reserved M1-M100 slot."""
        if (
            not isinstance(recall_key, str)
            or not is_clipboard_slot(recall_key)
        ):
            return self._failure(
                "Clipboard Memory requires recall_key M1 through M100",
                memory_type=CLIPBOARD_MEMORY_TYPE,
            )

        forbidden = {
            "collection_id",
            "collection_name",
            "episode_title",
            "episode_description",
            "active_retrieval_brief",
        }.intersection(arguments)
        if forbidden:
            return self._failure(
                "Clipboard Memory accepts only recall_key, input_text, and "
                "output_text",
                memory_type=CLIPBOARD_MEMORY_TYPE,
                requested_recall_key=recall_key,
            )

        pair = self._read_visible_pair(arguments)
        if isinstance(pair, str):
            return self._failure(
                pair,
                memory_type=CLIPBOARD_MEMORY_TYPE,
                requested_recall_key=recall_key,
            )

        try:
            saved = self._clipboard_store.save(
                owner_sub=owner_sub,
                clipboard_slot=recall_key,
                input_text=pair["input_text"],
                output_text=pair["output_text"],
            )
        except ValueError as error:
            return self._failure(
                str(error),
                memory_type=CLIPBOARD_MEMORY_TYPE,
                requested_recall_key=recall_key,
            )
        except Exception:  # noqa: BLE001
            return self._failure(
                "GHOST Clipboard Memory storage failed",
                memory_type=CLIPBOARD_MEMORY_TYPE,
                requested_recall_key=recall_key,
            )

        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": (
                        "Clipboard Memory saved successfully.\n"
                        f"Recall key: {saved['recall_key']}\n"
                        f"Record ID: {saved['record_id']}\n"
                        f"Expires: {saved['expires_at_utc']}"
                    ),
                }
            ],
            structuredContent={
                "saved": True,
                "workflow_state": WORKFLOW_COMPLETE,
                "memory_type": CLIPBOARD_MEMORY_TYPE,
                "requested_recall_key": recall_key,
                "recall_key": saved["recall_key"],
                "record_id": saved["record_id"],
                "file_id": saved["file_id"],
                "sequence_number": saved["sequence_number"],
                "created_at_utc": saved["created_at_utc"],
                "expires_at_utc": saved["expires_at_utc"],
            },
        )

    def _save_episodic(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any],
        common_values: dict[str, str],
    ) -> GhostToolResult:
        """Persist one ordinary Episodic Memory episode."""
        collection_fields = {
            "collection_id",
            "collection_name",
            "active_retrieval_brief",
        }
        if collection_fields.intersection(arguments):
            return self._failure(
                "Collection fields require memory_type collection",
                memory_type=EPISODIC_MEMORY_TYPE,
            )

        recall_key = self._read_optional_text(arguments, "recall_key")
        if recall_key is False or recall_key is None:
            return self._failure(
                "recall_key is required for Episodic Memory",
                memory_type=EPISODIC_MEMORY_TYPE,
            )

        try:
            record = self._memory_store.save_episodic_memory(
                owner_sub=owner_sub,
                recall_key=recall_key,
                episode_title=common_values["episode_title"],
                episode_description=common_values[
                    "episode_description"
                ],
                input_text=common_values["input_text"],
                output_text=common_values["output_text"],
            )
        except ValueError as error:
            return self._failure(
                str(error),
                memory_type=EPISODIC_MEMORY_TYPE,
                requested_recall_key=recall_key,
            )
        except Exception:  # noqa: BLE001
            return self._failure(
                "GHOST Episodic Memory storage failed",
                memory_type=EPISODIC_MEMORY_TYPE,
                requested_recall_key=recall_key,
            )

        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": (
                        "Episodic Memory saved successfully.\n"
                        f"Episode title: {record.episode_title}\n"
                        f"Recall key: {record.direct_recall_key}\n"
                        f"Record ID: {record.record_id}"
                    ),
                }
            ],
            structuredContent={
                "saved": True,
                "workflow_state": WORKFLOW_COMPLETE,
                "memory_type": EPISODIC_MEMORY_TYPE,
                "requested_recall_key": recall_key,
                "recall_key": record.direct_recall_key,
                "episode_title": record.episode_title,
                "episode_description": record.episode_description,
                "record_id": record.record_id,
                "created_at_utc": record.created_at_utc,
            },
        )

    def _save_collection(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any],
        common_values: dict[str, str],
    ) -> GhostToolResult:
        """Append one numbered episode to an existing Collection."""
        collection_id = self._read_optional_text(
            arguments,
            "collection_id",
        )
        collection_name = self._read_optional_text(
            arguments,
            "collection_name",
        )
        recall_key = self._read_optional_text(
            arguments,
            "recall_key",
        )
        active_brief = self._read_optional_text(
            arguments,
            "active_retrieval_brief",
        )

        invalid_fields = [
            field_name
            for field_name, value in (
                ("collection_id", collection_id),
                ("collection_name", collection_name),
                ("recall_key", recall_key),
                ("active_retrieval_brief", active_brief),
            )
            if value is False
        ]
        if invalid_fields:
            return self._failure(
                f"{invalid_fields[0]} must be a non-empty string",
                memory_type=COLLECTION_MEMORY_TYPE,
            )

        if (collection_id is None) == (collection_name is None):
            return self._failure(
                "exactly one of collection_id or collection_name is required",
                memory_type=COLLECTION_MEMORY_TYPE,
            )

        if not isinstance(active_brief, str):
            return self._failure(
                "active_retrieval_brief is required for Collection Memory",
                memory_type=COLLECTION_MEMORY_TYPE,
            )

        try:
            saved = self._collection_store.append_episode(
                owner_sub=owner_sub,
                collection_id=(
                    collection_id
                    if isinstance(collection_id, str)
                    else None
                ),
                collection_name=(
                    collection_name
                    if isinstance(collection_name, str)
                    else None
                ),
                recall_key=(
                    recall_key
                    if isinstance(recall_key, str)
                    else None
                ),
                episode_title=common_values["episode_title"],
                episode_description=common_values[
                    "episode_description"
                ],
                input_text=common_values["input_text"],
                output_text=common_values["output_text"],
                active_retrieval_brief=active_brief,
            )
        except ValueError as error:
            return self._failure(
                str(error),
                memory_type=COLLECTION_MEMORY_TYPE,
                requested_recall_key=(
                    recall_key
                    if isinstance(recall_key, str)
                    else None
                ),
            )
        except Exception:  # noqa: BLE001
            return self._failure(
                "GHOST Collection Memory storage failed",
                memory_type=COLLECTION_MEMORY_TYPE,
                requested_recall_key=(
                    recall_key
                    if isinstance(recall_key, str)
                    else None
                ),
            )

        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": (
                        "Collection episode saved successfully.\n"
                        f"Collection: {saved['collection_name']}\n"
                        f"Episode number: {saved['episode_number']}\n"
                        f"Episode title: {saved['episode_title']}\n"
                        f"Recall key: {saved['recall_key']}\n"
                        f"Record ID: {saved['record_id']}"
                    ),
                }
            ],
            structuredContent={
                "saved": True,
                "workflow_state": WORKFLOW_COMPLETE,
                "memory_type": COLLECTION_MEMORY_TYPE,
                **saved,
            },
        )

    @staticmethod
    def _read_common_values(
        arguments: Mapping[str, Any],
    ) -> dict[str, str] | str:
        """Read fields shared by Episodic and Collection Memory."""
        values: dict[str, str] = {}

        for field_name in (
            "episode_title",
            "episode_description",
            "input_text",
            "output_text",
        ):
            value = arguments.get(field_name)
            if not isinstance(value, str) or not value.strip():
                return (
                    f"{field_name} is required and must be "
                    "a non-empty string"
                )

            values[field_name] = (
                value.strip()
                if field_name
                in {"episode_title", "episode_description"}
                else value
            )

        if len(values["episode_title"]) > MAX_EPISODE_TITLE_LENGTH:
            return (
                f"episode_title must be at most "
                f"{MAX_EPISODE_TITLE_LENGTH} characters"
            )

        return values

    @staticmethod
    def _read_visible_pair(
        arguments: Mapping[str, Any],
    ) -> dict[str, str] | str:
        """Read the exact visible user/assistant pair without rewriting it."""
        values: dict[str, str] = {}

        for field_name in ("input_text", "output_text"):
            value = arguments.get(field_name)
            if not isinstance(value, str) or not value.strip():
                return (
                    f"{field_name} is required and must be "
                    "a non-empty string"
                )
            values[field_name] = value

        return values

    @staticmethod
    def _read_optional_text(
        arguments: Mapping[str, Any],
        field_name: str,
    ) -> str | bool | None:
        """Read an optional non-empty string."""
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
        memory_type: str | None = None,
        requested_recall_key: str | None = None,
    ) -> GhostToolResult:
        """Return one sanitized deterministic Save failure."""
        structured_content: dict[str, Any] = {
            "saved": False,
            "workflow_state": WORKFLOW_COMPLETE,
            "reason": reason,
        }

        if memory_type is not None:
            structured_content["memory_type"] = memory_type

        if requested_recall_key is not None:
            structured_content["requested_recall_key"] = (
                requested_recall_key
            )

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


def tool_metadata(
    required_scope: str | None = None,
) -> dict[str, Any]:
    """Build the OAuth-protected shared Save tool descriptor."""
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