"""Expose Clipboard, exact, semantic Episodic, and Collection Recall.

This module validates one authenticated Recall request and deterministically
routes it to newest-slot Clipboard retrieval, shared exact retrieval, semantic
Episodic candidate search, or numbered Collection retrieval. Client
instructions live in JSON.

Main classes:
    GhostMemoryRecallTool:
        Adapts one shared MCP Recall call to the selected backend path.

Main methods and functions:
    call_sanitized():
        Validates and executes one Clipboard, exact, semantic, or Collection
        retrieval stage.
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
from ragstream.mcp.memory_recall_contract import (
    COLLECTION_ARGUMENTS as _COLLECTION_ARGUMENTS,
    COLLECTION_SELECTION_MODES as _COLLECTION_SELECTION_MODES,
    EPISODIC_MEMORY_TYPE,
    MEMORY_TYPES as _MEMORY_TYPES,
    RESULT_MODES as _RESULT_MODES,
    RESULT_MODE_DESCRIPTION,
    RESULT_MODE_EPISODE,
    RETRIEVAL_CLIPBOARD,
    RETRIEVAL_COLLECTION,
    RETRIEVAL_EXACT,
    RETRIEVAL_SEMANTIC,
    WORKFLOW_COMPLETE,
    WORKFLOW_SELECTION_REQUIRED,
    build_recall_schemas,
)
from ragstream.mcp.memory_tool_instructions import (
    load_memory_tool_instructions,
)
from ragstream.memory.mcp_clipboard_store import (
    CLIPBOARD_MEMORY_TYPE,
    McpClipboardStore,
    is_clipboard_slot,
)
from ragstream.memory.mcp_memory_collection_retriever import (
    CollectionRecallSelection,
    McpMemoryCollectionRetriever,
)
from ragstream.memory.mcp_memory_collection_store import (
    COLLECTION_MEMORY_TYPE,
)
from ragstream.memory.mcp_memory_store import McpMemoryStore


TOOL_NAME = "ghost_memory_recall"
TOOL_TITLE = "GHOST Memory Recall"

_INSTRUCTIONS = load_memory_tool_instructions(
    "custom_memory_recall.json"
)
TOOL_DESCRIPTION = _INSTRUCTIONS.tool_description
SERVER_INSTRUCTIONS = _INSTRUCTIONS.server_instruction

INPUT_SCHEMA, OUTPUT_SCHEMA = build_recall_schemas(
    _INSTRUCTIONS.field_descriptions
)


class GhostMemoryRecallTool:
    """Route authenticated Recall calls to one deterministic backend path."""

    def __init__(
        self,
        memory_store: McpMemoryStore,
        collection_retriever: McpMemoryCollectionRetriever | None = None,
        clipboard_store: McpClipboardStore | None = None,
    ) -> None:
        """Create Recall over the shared owner-scoped memory stores."""
        self._memory_store = memory_store
        self._collection_retriever = (
            collection_retriever
            or McpMemoryCollectionRetriever(
                memory_root=memory_store.memory_root,
                sqlite_path=memory_store.sqlite_path,
            )
        )
        self._clipboard_store = (
            clipboard_store
            or McpClipboardStore(
                memory_root=memory_store.memory_root,
                sqlite_path=memory_store.sqlite_path,
            )
        )

    def call_sanitized(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        """Validate and execute one deterministic Recall path."""
        if not isinstance(owner_sub, str) or not owner_sub.strip():
            return self._failure(
                "authenticated user is required",
                RETRIEVAL_EXACT,
                RESULT_MODE_EPISODE,
            )

        if not isinstance(arguments, Mapping):
            return self._failure(
                "memory recall input is required",
                RETRIEVAL_EXACT,
                RESULT_MODE_EPISODE,
            )

        allowed_properties = {
            "memory_type",
            "recall_key",
            "record_id",
            "query_description",
            "date_from",
            "date_to",
            "result_mode",
            *_COLLECTION_ARGUMENTS,
        }
        if set(arguments).difference(allowed_properties):
            return self._failure(
                "unsupported input property",
                RETRIEVAL_EXACT,
                RESULT_MODE_EPISODE,
            )

        result_mode = arguments.get(
            "result_mode",
            RESULT_MODE_EPISODE,
        )
        if result_mode not in _RESULT_MODES:
            return self._failure(
                "result_mode must be episode or description",
                RETRIEVAL_EXACT,
                RESULT_MODE_EPISODE,
            )

        explicit_memory_type = "memory_type" in arguments
        memory_type = arguments.get("memory_type")

        if (
            explicit_memory_type
            and memory_type not in _MEMORY_TYPES
        ):
            return self._failure(
                "memory_type must be episodic, collection, or clipboard",
                RETRIEVAL_EXACT,
                result_mode,
            )

        text_values = {
            name: self._read_optional_text(arguments, name)
            for name in (
                "recall_key",
                "record_id",
                "query_description",
                "date_from",
                "date_to",
                "collection_id",
                "collection_name",
                "selection_mode",
            )
        }

        invalid_fields = [
            name
            for name, value in text_values.items()
            if value is False
        ]
        if invalid_fields:
            return self._failure(
                f"{invalid_fields[0]} must be a non-empty string",
                RETRIEVAL_EXACT,
                result_mode,
            )

        recall_key = text_values["recall_key"]
        record_id = text_values["record_id"]

        exact_identifiers = [
            value
            for value in (recall_key, record_id)
            if isinstance(value, str)
        ]
        if len(exact_identifiers) > 1:
            return self._failure(
                "supply exactly one of recall_key or record_id",
                RETRIEVAL_EXACT,
                result_mode,
            )

        clipboard_key = (
            recall_key
            if isinstance(recall_key, str)
            and is_clipboard_slot(recall_key)
            else None
        )

        if (
            memory_type == CLIPBOARD_MEMORY_TYPE
            or clipboard_key is not None
        ):
            return self._recall_clipboard(
                owner_sub=owner_sub,
                arguments=arguments,
                recall_key=(
                    clipboard_key
                    if clipboard_key is not None
                    else self._optional_string(recall_key)
                ),
                result_mode=result_mode,
            )

        if exact_identifiers:
            disallowed = {
                "query_description",
                "date_from",
                "date_to",
                *_COLLECTION_ARGUMENTS,
            }.intersection(arguments)

            if disallowed:
                return self._failure(
                    "exact recall cannot include semantic or numbered "
                    "Collection selectors",
                    RETRIEVAL_EXACT,
                    result_mode,
                )

            return self._recall_exact(
                owner_sub=owner_sub,
                recall_key=(
                    recall_key
                    if isinstance(recall_key, str)
                    else None
                ),
                record_id=(
                    record_id
                    if isinstance(record_id, str)
                    else None
                ),
                result_mode=result_mode,
                expected_memory_type=(
                    memory_type
                    if explicit_memory_type
                    else None
                ),
            )

        if memory_type == COLLECTION_MEMORY_TYPE:
            return self._recall_collection(
                owner_sub,
                arguments,
                text_values,
                result_mode,
            )

        if _COLLECTION_ARGUMENTS.intersection(arguments):
            return self._failure(
                "numbered Collection selectors require memory_type "
                "collection",
                RETRIEVAL_COLLECTION,
                result_mode,
            )

        query_description = text_values["query_description"]
        if not isinstance(query_description, str):
            return self._failure(
                "query_description is required when no exact identifier "
                "is known",
                RETRIEVAL_SEMANTIC,
                result_mode,
            )

        return self._search_candidates(
            owner_sub=owner_sub,
            query_description=query_description,
            date_from=self._optional_string(
                text_values["date_from"]
            ),
            date_to=self._optional_string(
                text_values["date_to"]
            ),
            result_mode=result_mode,
        )

    def _recall_clipboard(
        self,
        *,
        owner_sub: str,
        arguments: Mapping[str, Any],
        recall_key: str | None,
        result_mode: str,
    ) -> GhostToolResult:
        """Return only the newest non-expired pair in one M1-M100 slot."""
        if (
            not isinstance(recall_key, str)
            or not is_clipboard_slot(recall_key)
        ):
            return self._failure(
                "Clipboard Memory requires recall_key M1 through M100",
                RETRIEVAL_CLIPBOARD,
                RESULT_MODE_EPISODE,
            )

        if result_mode != RESULT_MODE_EPISODE:
            return self._failure(
                "Clipboard Memory supports only result_mode episode",
                RETRIEVAL_CLIPBOARD,
                RESULT_MODE_EPISODE,
            )

        allowed = {
            "memory_type",
            "recall_key",
            "result_mode",
        }
        if set(arguments).difference(allowed):
            return self._failure(
                "Clipboard recall accepts only recall_key and result_mode",
                RETRIEVAL_CLIPBOARD,
                RESULT_MODE_EPISODE,
            )

        try:
            memory = self._clipboard_store.recall_latest(
                owner_sub=owner_sub,
                clipboard_slot=recall_key,
            )
        except ValueError as error:
            return self._failure(
                str(error),
                RETRIEVAL_CLIPBOARD,
                RESULT_MODE_EPISODE,
            )
        except Exception:  # noqa: BLE001
            return self._failure(
                "GHOST Clipboard Memory recall failed",
                RETRIEVAL_CLIPBOARD,
                RESULT_MODE_EPISODE,
            )

        if memory is None:
            return self._failure(
                f'no active Clipboard Memory found for '
                f'"{recall_key.upper()}"',
                RETRIEVAL_CLIPBOARD,
                RESULT_MODE_EPISODE,
            )

        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": self._format_clipboard_memory(memory),
                }
            ],
            structuredContent={
                "workflow_state": WORKFLOW_COMPLETE,
                "retrieval_path": RETRIEVAL_CLIPBOARD,
                "result_mode": RESULT_MODE_EPISODE,
                "memory_type": CLIPBOARD_MEMORY_TYPE,
                "file_id": memory["file_id"],
                "recall_key": memory["recall_key"],
                "record_id": memory["record_id"],
                "sequence_number": memory["sequence_number"],
                "created_at_utc": memory["created_at_utc"],
                "expires_at_utc": memory["expires_at_utc"],
                "input_text": memory["input_text"],
                "output_text": memory["output_text"],
            },
        )

    def _recall_exact(
        self,
        *,
        owner_sub: str,
        recall_key: str | None,
        record_id: str | None,
        result_mode: str,
        expected_memory_type: str | None,
    ) -> GhostToolResult:
        """Recall one non-Clipboard episode using an exact identifier."""
        try:
            memory = self._memory_store.recall_memory(
                owner_sub=owner_sub,
                recall_key=recall_key,
                record_id=record_id,
            )
        except ValueError as error:
            return self._failure(
                str(error),
                RETRIEVAL_EXACT,
                result_mode,
            )
        except Exception:  # noqa: BLE001
            return self._failure(
                "GHOST memory recall failed",
                RETRIEVAL_EXACT,
                result_mode,
            )

        if memory is None:
            selector = (
                recall_key
                if recall_key is not None
                else record_id
            )
            return self._failure(
                f'no memory found for exact identifier "{selector}"',
                RETRIEVAL_EXACT,
                result_mode,
            )

        if (
            expected_memory_type is not None
            and memory["memory_type"] != expected_memory_type
        ):
            return self._failure(
                "exact identifier does not belong to the requested "
                "memory_type",
                RETRIEVAL_EXACT,
                result_mode,
            )

        structured_content: dict[str, Any] = {
            "workflow_state": WORKFLOW_COMPLETE,
            "retrieval_path": RETRIEVAL_EXACT,
            "result_mode": result_mode,
            "file_id": memory["file_id"],
            "memory_type": memory["memory_type"],
            "recall_key": memory["recall_key"],
            "record_id": memory["record_id"],
            "sequence_number": memory["sequence_number"],
            "episode_title": memory["episode_title"],
            "episode_description": memory["episode_description"],
            "created_at_utc": memory["created_at_utc"],
        }

        if result_mode == RESULT_MODE_DESCRIPTION:
            text = memory["episode_description"]
        else:
            structured_content.update(
                {
                    "input_text": memory["input_text"],
                    "output_text": memory["output_text"],
                    "active_retrieval_brief_title": memory[
                        "active_retrieval_brief_title"
                    ],
                    "active_retrieval_brief": memory[
                        "active_retrieval_brief"
                    ],
                    "active_retrieval_brief_contributor_ids": memory[
                        "active_retrieval_brief_contributor_ids"
                    ],
                }
            )
            text = self._format_exact_memory(memory)

        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": text,
                }
            ],
            structuredContent=structured_content,
        )

    def _recall_collection(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any],
        text_values: dict[str, str | bool | None],
        result_mode: str,
    ) -> GhostToolResult:
        """Recall deterministic numbered episodes from one Collection."""
        if (
            "query_description" in arguments
            or {"date_from", "date_to"}.intersection(arguments)
        ):
            return self._failure(
                "semantic query and date fields are not Collection "
                "selectors",
                RETRIEVAL_COLLECTION,
                result_mode,
            )

        collection_id = self._optional_string(
            text_values["collection_id"]
        )
        collection_name = self._optional_string(
            text_values["collection_name"]
        )

        if (collection_id is None) == (collection_name is None):
            return self._failure(
                "exactly one of collection_id or collection_name is "
                "required",
                RETRIEVAL_COLLECTION,
                result_mode,
            )

        selection_mode = text_values["selection_mode"]
        if not isinstance(selection_mode, str):
            return self._failure(
                "selection_mode is required for Collection recall",
                RETRIEVAL_COLLECTION,
                result_mode,
            )

        if selection_mode not in _COLLECTION_SELECTION_MODES:
            return self._failure(
                "unsupported Collection selection_mode",
                RETRIEVAL_COLLECTION,
                result_mode,
            )

        selection = self._build_collection_selection(
            selection_mode,
            arguments,
        )
        if isinstance(selection, str):
            return self._failure(
                selection,
                RETRIEVAL_COLLECTION,
                result_mode,
            )

        try:
            recalled = self._collection_retriever.recall_episodes(
                owner_sub=owner_sub,
                selection=selection,
                collection_id=collection_id,
                collection_name=collection_name,
            )
        except ValueError as error:
            return self._failure(
                str(error),
                RETRIEVAL_COLLECTION,
                result_mode,
            )
        except Exception:  # noqa: BLE001
            return self._failure(
                "GHOST Collection Memory recall failed",
                RETRIEVAL_COLLECTION,
                result_mode,
            )

        episodes = recalled["episodes"]
        if result_mode == RESULT_MODE_DESCRIPTION:
            episodes = [
                self._description_projection(episode)
                for episode in episodes
            ]

        structured_content = {
            "workflow_state": WORKFLOW_COMPLETE,
            "retrieval_path": RETRIEVAL_COLLECTION,
            "result_mode": result_mode,
            "memory_type": COLLECTION_MEMORY_TYPE,
            **recalled,
            "episodes": episodes,
        }

        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": self._format_collection_result(
                        structured_content
                    ),
                }
            ],
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
        """Return semantic Episodic candidates for model-side selection."""
        try:
            candidates = (
                self._memory_store.search_episodic_memories(
                    owner_sub=owner_sub,
                    query_description=query_description,
                    date_from=date_from,
                    date_to=date_to,
                )
            )
        except ValueError as error:
            return self._failure(
                str(error),
                RETRIEVAL_SEMANTIC,
                result_mode,
            )
        except Exception:  # noqa: BLE001
            return self._failure(
                "GHOST intelligent memory recall failed",
                RETRIEVAL_SEMANTIC,
                result_mode,
            )

        if not candidates:
            return self._failure(
                "no Episodic Memory candidates matched the request",
                RETRIEVAL_SEMANTIC,
                result_mode,
            )

        lines = [
            "Candidate selection is required before the final episode fetch."
        ]
        for position, candidate in enumerate(
            candidates,
            start=1,
        ):
            lines.extend(
                [
                    "",
                    f"Candidate {position}",
                    f"Record ID: {candidate['record_id']}",
                    f"Title: {candidate['episode_title']}",
                    (
                        "Description: "
                        f"{candidate['episode_description']}"
                    ),
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
                "memory_type": EPISODIC_MEMORY_TYPE,
                "candidate_count": len(candidates),
                "candidates": candidates,
            },
        )

    @staticmethod
    def _build_collection_selection(
        selection_mode: str,
        arguments: Mapping[str, Any],
    ) -> CollectionRecallSelection | str:
        """Build one typed Collection episode selection."""
        raw_numbers = arguments.get("episode_numbers", [])

        if not isinstance(raw_numbers, list):
            return (
                "episode_numbers must be an array of positive integers"
            )

        if any(
            not isinstance(number, int)
            or isinstance(number, bool)
            or number < 1
            for number in raw_numbers
        ):
            return (
                "episode_numbers must contain positive integers"
            )

        return CollectionRecallSelection(
            mode=selection_mode,
            episode_number=arguments.get("episode_number"),
            episode_numbers=tuple(raw_numbers),
            range_start=arguments.get("range_start"),
            range_end=arguments.get("range_end"),
            count=arguments.get("count"),
        )

    @staticmethod
    def _format_exact_memory(
        memory: Mapping[str, Any],
    ) -> str:
        """Format one complete exact Episodic or Collection episode."""
        lines = [
            f"Episode title: {memory['episode_title']}",
            (
                "Episode description: "
                f"{memory['episode_description']}"
            ),
        ]

        if memory["memory_type"] == COLLECTION_MEMORY_TYPE:
            lines.extend(
                [
                    f"Collection ID: {memory['file_id']}",
                    (
                        "Episode number: "
                        f"{memory['sequence_number']}"
                    ),
                    "",
                    "Collection ActiveBrief:",
                    memory["active_retrieval_brief"],
                ]
            )

        lines.extend(
            [
                "",
                "Input:",
                memory["input_text"],
                "",
                "Output:",
                memory["output_text"],
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _format_clipboard_memory(
        memory: Mapping[str, Any],
    ) -> str:
        """Format the newest exact Clipboard pair."""
        return "\n".join(
            [
                f"Clipboard slot: {memory['recall_key']}",
                "",
                "Input:",
                memory["input_text"],
                "",
                "Output:",
                memory["output_text"],
            ]
        )

    @staticmethod
    def _format_collection_result(
        result: Mapping[str, Any],
    ) -> str:
        """Format one deterministic numbered Collection response."""
        lines = [
            f"Collection: {result['collection_name']}",
            f"Collection ID: {result['collection_id']}",
            (
                "Returned episode numbers: "
                f"{result['returned_episode_numbers']}"
            ),
        ]

        if result["unavailable_episode_numbers"]:
            lines.append(
                "Unavailable or deleted episode numbers: "
                f"{result['unavailable_episode_numbers']}"
            )

        if result["omitted_episode_numbers"]:
            lines.append(
                "Omitted because of the token limit: "
                f"{result['omitted_episode_numbers']}"
            )

        for episode in result["episodes"]:
            lines.extend(
                [
                    "",
                    (
                        f"Episode {episode['episode_number']}: "
                        f"{episode['episode_title']}"
                    ),
                    f"Recall key: {episode['recall_key']}",
                    (
                        "Description: "
                        f"{episode['episode_description']}"
                    ),
                ]
            )

            if result["result_mode"] == RESULT_MODE_EPISODE:
                lines.extend(
                    [
                        "Collection ActiveBrief:",
                        episode["active_retrieval_brief"],
                        "Input:",
                        episode["input_text"],
                        "Output:",
                        episode["output_text"],
                    ]
                )

        return "\n".join(lines)

    @staticmethod
    def _description_projection(
        episode: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Return Collection episode metadata without full Q/A content."""
        return {
            field_name: episode[field_name]
            for field_name in (
                "episode_number",
                "record_id",
                "recall_key",
                "episode_title",
                "episode_description",
                "created_at_utc",
            )
        }

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
    def _optional_string(
        value: str | bool | None,
    ) -> str | None:
        """Return a string value or None."""
        return value if isinstance(value, str) else None

    @staticmethod
    def _failure(
        reason: str,
        retrieval_path: str,
        result_mode: str,
    ) -> GhostToolResult:
        """Return one sanitized deterministic Recall failure."""
        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": reason,
                }
            ],
            structuredContent={
                "workflow_state": WORKFLOW_COMPLETE,
                "retrieval_path": retrieval_path,
                "result_mode": result_mode,
                "reason": reason,
            },
            isError=True,
        )


def tool_metadata(
    required_scope: str | None = None,
) -> dict[str, Any]:
    """Build the OAuth-protected shared Recall tool descriptor."""
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