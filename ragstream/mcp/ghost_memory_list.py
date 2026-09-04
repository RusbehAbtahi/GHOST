"""Expose shared metadata listing for GHOST memories and Collections.

This module validates one authenticated list request and routes it to the
general memory index, the Collection container index, or one Collection's
numbered episode metadata. It never returns complete stored Q/A bodies.

Main classes:
    GhostMemoryListTool:
        Adapts one MCP metadata-list request to the selected backend path.

Main methods and functions:
    call_sanitized():
        Lists general memories, Collections, or Collection episode metadata.
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
from ragstream.memory.mcp_memory_collection_browser import (
    McpMemoryCollectionBrowser,
)
from ragstream.memory.mcp_memory_collection_retriever import (
    McpMemoryCollectionRetriever,
)
from ragstream.memory.mcp_memory_store import McpMemoryStore


TOOL_NAME = "ghost_memory_list"
TOOL_TITLE = "GHOST Memory List"

LIST_MODE_MEMORIES = "memories"
LIST_MODE_COLLECTIONS = "collections"
LIST_MODE_COLLECTION_FOLDERS = "collection_folders"
LIST_MODE_COLLECTION_EPISODES = "collection_episodes"

_LIST_MODES = {
    LIST_MODE_MEMORIES,
    LIST_MODE_COLLECTIONS,
    LIST_MODE_COLLECTION_FOLDERS,
    LIST_MODE_COLLECTION_EPISODES,
}

_INSTRUCTIONS = load_memory_tool_instructions(
    "custom_memory_list.json"
)
TOOL_DESCRIPTION = _INSTRUCTIONS.tool_description
SERVER_INSTRUCTIONS = _INSTRUCTIONS.server_instruction

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "list_mode": {
            "type": "string",
            "enum": sorted(_LIST_MODES),
            "default": LIST_MODE_MEMORIES,
            "description": _INSTRUCTIONS.field_descriptions[
                "list_mode"
            ],
        },
        "collection_id": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions[
                "collection_id"
            ],
        },
        "folder": {
            "type": "string",
            "minLength": 1,
            "description": _INSTRUCTIONS.field_descriptions["folder"],
        },
    },
    "additionalProperties": False,
}

_MEMORY_ITEM_SCHEMA = {
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

_COLLECTION_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "collection_id": {
            "type": "string",
            "minLength": 1,
        },
        "collection_name": {
            "type": "string",
            "minLength": 1,
        },
        "collection_description": {
            "type": "string",
        },
        "created_at_utc": {
            "type": "string",
            "minLength": 1,
        },
        "updated_at_utc": {
            "type": "string",
            "minLength": 1,
        },
        "record_count": {
            "type": "integer",
            "minimum": 0,
        },
        "next_sequence_number": {
            "type": "integer",
            "minimum": 1,
        },
        "highest_assigned_episode_number": {
            "type": "integer",
            "minimum": 0,
        },
        "folder": {"type": "string", "minLength": 1},
    },
    "required": [
        "collection_id",
        "collection_name",
        "collection_description",
        "created_at_utc",
        "updated_at_utc",
        "record_count",
        "next_sequence_number",
        "highest_assigned_episode_number",
        "folder",
    ],
    "additionalProperties": False,
}

_EPISODE_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "episode_number": {
            "type": "integer",
            "minimum": 1,
        },
        "record_id": {
            "type": "string",
            "minLength": 1,
        },
        "recall_key": {
            "type": "string",
            "minLength": 1,
        },
        "episode_title": {
            "type": "string",
        },
        "episode_description": {
            "type": "string",
        },
        "created_at_utc": {
            "type": "string",
            "minLength": 1,
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

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "list_mode": {
            "type": "string",
            "enum": sorted(_LIST_MODES),
        },
        "memories": {
            "type": "array",
            "items": _MEMORY_ITEM_SCHEMA,
        },
        "collections": {
            "type": "array",
            "items": _COLLECTION_ITEM_SCHEMA,
        },
        "folders": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
        "folder": {"type": "string", "minLength": 1},
        "collection_id": {
            "type": "string",
            "minLength": 1,
        },
        "collection_name": {
            "type": "string",
            "minLength": 1,
        },
        "collection_description": {
            "type": "string",
        },
        "created_at_utc": {
            "type": "string",
            "minLength": 1,
        },
        "record_count": {
            "type": "integer",
            "minimum": 0,
        },
        "highest_assigned_episode_number": {
            "type": "integer",
            "minimum": 0,
        },
        "next_sequence_number": {
            "type": "integer",
            "minimum": 1,
        },
        "episodes": {
            "type": "array",
            "items": _EPISODE_ITEM_SCHEMA,
        },
        "unavailable_episode_numbers": {
            "type": "array",
            "items": {
                "type": "integer",
                "minimum": 1,
            },
        },
        "total_count": {
            "type": "integer",
            "minimum": 0,
        },
        "reason": {
            "type": "string",
        },
    },
    "required": [
        "list_mode",
        "total_count",
    ],
    "additionalProperties": False,
}


class GhostMemoryListTool:
    """Route authenticated metadata lists without returning full bodies."""

    def __init__(
        self,
        memory_store: McpMemoryStore,
        collection_retriever: McpMemoryCollectionRetriever,
        collection_browser: McpMemoryCollectionBrowser | None = None,
    ) -> None:
        self._memory_store = memory_store
        self._collection_retriever = collection_retriever
        self._collection_browser = collection_browser or McpMemoryCollectionBrowser(
            memory_root=collection_retriever.memory_root,
            sqlite_path=collection_retriever.sqlite_path,
        )

    def call_sanitized(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        """Validate and execute one metadata-list path."""
        if not isinstance(owner_sub, str) or not owner_sub.strip():
            return self._failure(
                "authenticated user is required",
                LIST_MODE_MEMORIES,
            )
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, Mapping):
            return self._failure(
                "memory list input is required",
                LIST_MODE_MEMORIES,
            )
        if set(arguments).difference(
            {"list_mode", "collection_id", "folder"}
        ):
            return self._failure(
                "unsupported input property",
                LIST_MODE_MEMORIES,
            )

        list_mode = arguments.get(
            "list_mode",
            LIST_MODE_MEMORIES,
        )
        if list_mode not in _LIST_MODES:
            return self._failure(
                "unsupported list_mode",
                LIST_MODE_MEMORIES,
            )

        collection_id = arguments.get("collection_id")
        folder = arguments.get("folder")
        if collection_id is not None and (
            not isinstance(collection_id, str)
            or not collection_id.strip()
        ):
            return self._failure(
                "collection_id must be a non-empty string",
                list_mode,
            )

        if folder is not None and (
            not isinstance(folder, str) or not folder.strip()
        ):
            return self._failure("folder must be a non-empty string", list_mode)

        if list_mode == LIST_MODE_MEMORIES:
            if collection_id is not None or folder is not None:
                return self._failure(
                    "Collection fields are not used with memories",
                    list_mode,
                )
            return self._list_memories(owner_sub)

        if list_mode == LIST_MODE_COLLECTION_FOLDERS:
            if collection_id is not None or folder is not None:
                return self._failure(
                    "collection_folders does not use collection_id or folder",
                    list_mode,
                )
            return self._list_collection_folders(owner_sub)

        if list_mode == LIST_MODE_COLLECTIONS:
            if collection_id is not None:
                return self._failure(
                    "collection_id is not used when listing Collections",
                    list_mode,
                )
            return self._list_collections(
                owner_sub,
                folder.strip() if isinstance(folder, str) else None,
            )

        if folder is not None:
            return self._failure(
                "folder is not used when listing Collection episodes",
                list_mode,
            )
        if not isinstance(collection_id, str):
            return self._failure(
                "exact collection_id is required for "
                "Collection episodes",
                list_mode,
            )

        return self._list_collection_episodes(
            owner_sub,
            collection_id.strip(),
        )

    def _list_memories(
        self,
        owner_sub: str,
    ) -> GhostToolResult:
        try:
            memories = self._memory_store.list_memories(
                owner_sub=owner_sub
            )
        except Exception:  # noqa: BLE001
            return self._failure(
                "GHOST memory listing failed",
                LIST_MODE_MEMORIES,
            )

        if memories:
            lines = [
                "Saved GHOST memories, newest first:",
                "",
                (
                    "| Episode title | Recall key | "
                    "Created UTC | Record ID |"
                ),
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
            content=[
                {
                    "type": "text",
                    "text": text,
                }
            ],
            structuredContent={
                "list_mode": LIST_MODE_MEMORIES,
                "memories": memories,
                "total_count": len(memories),
            },
        )

    def _list_collections(
        self,
        owner_sub: str,
        folder: str | None,
    ) -> GhostToolResult:
        try:
            collections = self._collection_browser.list_collections(
                owner_sub,
                folder=folder,
            )
        except Exception:  # noqa: BLE001
            return self._failure(
                "GHOST Collection listing failed",
                LIST_MODE_COLLECTIONS,
            )

        if collections:
            lines = [
                f"GHOST Collection Memories in {collections[0]['folder']}:",
                "",
                (
                    "| Collection | Description | Episodes | "
                    "Collection ID |"
                ),
                "| --- | --- | ---: | --- |",
            ]

            for collection in collections:
                lines.append(
                    "| "
                    f"{self._markdown_cell(
                        collection['collection_name']
                    )} | "
                    f"{self._markdown_cell(
                        collection['collection_description']
                    )} | "
                    f"{collection['record_count']} | "
                    f"{self._markdown_cell(
                        collection['collection_id']
                    )} |"
                )

            text = "\n".join(lines)
        else:
            text = "No Collection Memories were found."

        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": text,
                }
            ],
            structuredContent={
                "list_mode": LIST_MODE_COLLECTIONS,
                "folder": (
                    collections[0]["folder"]
                    if collections
                    else (folder or "Main")
                ),
                "collections": collections,
                "total_count": len(collections),
            },
        )

    def _list_collection_folders(self, owner_sub: str) -> GhostToolResult:
        try:
            folders = self._collection_browser.list_collection_folders(owner_sub)
        except Exception:  # noqa: BLE001
            return self._failure(
                "GHOST Collection folder listing failed",
                LIST_MODE_COLLECTION_FOLDERS,
            )

        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": "Collection folders: " + ", ".join(folders),
                }
            ],
            structuredContent={
                "list_mode": LIST_MODE_COLLECTION_FOLDERS,
                "folders": folders,
                "total_count": len(folders),
            },
        )

    def _list_collection_episodes(
        self,
        owner_sub: str,
        collection_id: str,
    ) -> GhostToolResult:
        try:
            result = self._collection_retriever.list_episodes(
                owner_sub=owner_sub,
                collection_id=collection_id,
            )
        except ValueError as error:
            return self._failure(
                str(error),
                LIST_MODE_COLLECTION_EPISODES,
            )
        except Exception:  # noqa: BLE001
            return self._failure(
                "GHOST Collection episode listing failed",
                LIST_MODE_COLLECTION_EPISODES,
            )

        lines = [
            f"Collection: {result['collection_name']}",
            f"Collection ID: {result['collection_id']}",
            f"Available episodes: {result['record_count']}",
        ]

        if result["unavailable_episode_numbers"]:
            lines.append(
                "Unavailable or deleted episode numbers: "
                f"{result['unavailable_episode_numbers']}"
            )

        if result["episodes"]:
            lines.extend(
                [
                    "",
                    (
                        "| No. | Title | Recall key | "
                        "Description | Record ID |"
                    ),
                    "| ---: | --- | --- | --- | --- |",
                ]
            )

            for episode in result["episodes"]:
                lines.append(
                    "| "
                    f"{episode['episode_number']} | "
                    f"{self._markdown_cell(
                        episode['episode_title']
                    )} | "
                    f"{self._markdown_cell(
                        episode['recall_key']
                    )} | "
                    f"{self._markdown_cell(
                        episode['episode_description']
                    )} | "
                    f"{self._markdown_cell(
                        episode['record_id']
                    )} |"
                )

        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": "\n".join(lines),
                }
            ],
            structuredContent={
                "list_mode": LIST_MODE_COLLECTION_EPISODES,
                **result,
                "total_count": len(result["episodes"]),
            },
        )

    @staticmethod
    def _markdown_cell(value: str) -> str:
        return (
            str(value)
            .replace("\\", "\\\\")
            .replace("|", "\\|")
            .replace("\r", " ")
            .replace("\n", " ")
        )

    @staticmethod
    def _failure(
        reason: str,
        list_mode: str,
    ) -> GhostToolResult:
        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": (
                        f"Memory list failed. Reason: {reason}."
                    ),
                }
            ],
            structuredContent={
                "list_mode": list_mode,
                "total_count": 0,
                "reason": reason,
            },
            isError=True,
        )


def tool_metadata(
    required_scope: str | None = None,
) -> dict[str, Any]:
    """Build the OAuth-protected shared List tool descriptor."""
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
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    }