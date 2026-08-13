"""Expose the three MCP contracts for GHOST Persistent Chat Memory.

The module validates authenticated MCP inputs and delegates persistence to
McpPersistentChatStore. It does not render ChatGPT answers or perform LLM work.

Main classes:
    GhostPersistentChatTool:
        Provides sanitized initialize, append, and resume operations.

Main methods and functions:
    init_sanitized():
        Initializes one non-daily persistent chat memory.
    append_sanitized():
        Persists one visible Q/A with ChatGPT's updated cumulative ActiveBrief.
    resume_sanitized():
        Resolves an existing memory from an exact owner-scoped episode ID.
    init_tool_metadata(), append_tool_metadata(), resume_tool_metadata():
        Build the three OAuth-protected MCP tool descriptors.
"""

from __future__ import annotations

from typing import Any, Mapping

from ragstream.mcp.ghost_engineer_prompt import (
    DEFAULT_REQUIRED_SCOPE,
    GhostToolResult,
)
from ragstream.memory.mcp_persistent_chat_store import (
    McpPersistentChatStore,
    PersistentChatPartialSaveError,
)


INIT_TOOL_NAME = "ghost_persistent_chat_init"
APPEND_TOOL_NAME = "ghost_persistent_chat_append"
RESUME_TOOL_NAME = "ghost_persistent_chat_resume"

PERSISTENT_CHAT_SERVER_INSTRUCTIONS = (
    "Persistent Chat Memory begins only after an explicit successful "
    "ghost_persistent_chat_init or ghost_persistent_chat_resume call. ChatGPT "
    "remains the presentation authority: compose the normal complete answer, "
    "including its normal Markdown and code formatting, and never use GHOST as "
    "an answer renderer. For each subsequent normal user/assistant exchange "
    "while persistence is active, update the cumulative ActiveBrief from the "
    "previous ActiveBrief plus the current visible Q/A, then call "
    "ghost_persistent_chat_append with the complete visible user message, the "
    "same substantive assistant answer, and that updated ActiveBrief. For the "
    "first episode, create the ActiveBrief from the first Q/A. Do not persist "
    "hidden reasoning, internal tool traffic, tool results, or the persistence "
    "receipt as conversation content. After a successful append, show the "
    "normal answer followed by the exact short receipt returned by GHOST. "
    "Never claim a save when saved is false. To recover, call "
    "ghost_persistent_chat_resume with an exact previously returned record ID; "
    "the ID locates the memory, while GHOST returns that memory's latest "
    "healthy ActiveBrief. Resume never creates a memory."
)

INIT_TOOL_DESCRIPTION = (
    "Explicitly activates one Persistent Chat Memory for the authenticated "
    "user. Supply the user-provided title and, optionally, a general "
    "description. This creates one stable, non-daily GHOST history; it does "
    "not save a conversation episode. After success, use "
    "ghost_persistent_chat_append for each subsequent normal Q/A."
)

APPEND_TOOL_DESCRIPTION = (
    "Appends one normal visible user/assistant exchange to an already "
    "initialized Persistent Chat Memory. First compose the complete normal "
    "assistant answer with its normal formatting. Pass the complete visible "
    "user message as input_text, that same substantive answer as output_text, "
    "and ChatGPT's cumulative updated ActiveBrief as "
    "active_retrieval_brief. GHOST persists but does not render or rewrite the "
    "answer. On success, show the returned receipt exactly after the normal "
    "answer. This operation never creates a missing persistent memory."
)

RESUME_TOOL_DESCRIPTION = (
    "Resumes an existing Persistent Chat Memory using an exact episode "
    "record_id previously returned in a successful save receipt. Resolution "
    "is scoped to the authenticated owner. The supplied episode locates the "
    "memory; continuation uses that memory's latest coherent episode and "
    "ActiveBrief, even when they are newer. This operation is read-only and "
    "never creates a memory when resolution fails."
)

INIT_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "minLength": 1,
            "description": "The user-provided persistent chat title.",
        },
        "memory_description": {
            "type": "string",
            "default": "",
            "description": (
                "Optional general description supplied by the user. Leave "
                "empty rather than inventing project facts."
            ),
        },
    },
    "required": ["title"],
    "additionalProperties": False,
}

INIT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "initialized": {"type": "boolean"},
        "file_id": {"type": "string", "minLength": 1},
        "title": {"type": "string", "minLength": 1},
        "memory_type": {"type": "string", "minLength": 1},
        "record_count": {"type": "integer", "minimum": 0},
    },
    "required": ["initialized"],
    "additionalProperties": False,
}

APPEND_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "file_id": {
            "type": "string",
            "minLength": 1,
            "description": "Stable file_id returned by initialization or resume.",
        },
        "input_text": {
            "type": "string",
            "minLength": 1,
            "description": "Complete visible user message for this episode.",
        },
        "output_text": {
            "type": "string",
            "minLength": 1,
            "description": (
                "Complete substantive assistant answer composed for the user, "
                "preserving normal Markdown and code content."
            ),
        },
        "active_retrieval_brief": {
            "type": "string",
            "minLength": 1,
            "description": (
                "Updated cumulative ActiveBrief produced from the previous "
                "ActiveBrief plus this episode's visible Q/A."
            ),
        },
    },
    "required": [
        "file_id",
        "input_text",
        "output_text",
        "active_retrieval_brief",
    ],
    "additionalProperties": False,
}

APPEND_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "saved": {"type": "boolean"},
        "file_id": {"type": "string", "minLength": 1},
        "record_id": {"type": "string", "minLength": 1},
        "sequence_number": {"type": "integer", "minimum": 1},
        "created_at_utc": {"type": "string", "minLength": 1},
        "receipt": {"type": "string", "minLength": 1},
        "durable_memory_written": {"type": "boolean"},
    },
    "required": ["saved"],
    "additionalProperties": False,
}

RESUME_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "record_id": {
            "type": "string",
            "minLength": 1,
            "description": (
                "Exact episode record_id from any successful save receipt in "
                "the persistent chat memory."
            ),
        },
    },
    "required": ["record_id"],
    "additionalProperties": False,
}

RESUME_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "resumed": {"type": "boolean"},
        "resume_record_id": {"type": "string", "minLength": 1},
        "file_id": {"type": "string", "minLength": 1},
        "title": {"type": "string", "minLength": 1},
        "memory_description": {"type": "string"},
        "record_count": {"type": "integer", "minimum": 1},
        "latest_record_id": {"type": "string", "minLength": 1},
        "latest_sequence_number": {"type": "integer", "minimum": 1},
        "latest_created_at_utc": {"type": "string", "minLength": 1},
        "active_retrieval_brief_title": {"type": "string"},
        "active_retrieval_brief": {"type": "string", "minLength": 1},
    },
    "required": ["resumed"],
    "additionalProperties": False,
}


class GhostPersistentChatTool:
    """Thin MCP adapter for authenticated Persistent Chat operations."""

    def __init__(self, store: McpPersistentChatStore) -> None:
        self._store = store

    def init_sanitized(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        """Validate and initialize one persistent chat memory."""
        error = self._validate_request(
            owner_sub,
            arguments,
            {"title", "memory_description"},
            "persistent chat initialization input is required",
        )
        if error is not None:
            return self._failure("initialization", error, "initialized")
        assert arguments is not None

        title = arguments.get("title")
        memory_description = arguments.get("memory_description", "")
        if not isinstance(title, str) or not title.strip():
            return self._failure(
                "initialization",
                "title is required and must be a non-empty string",
                "initialized",
            )
        if not isinstance(memory_description, str):
            return self._failure(
                "initialization",
                "memory_description must be a string",
                "initialized",
            )

        try:
            state = self._store.initialize_chat(
                owner_sub=owner_sub,
                title=title,
                memory_description=memory_description,
            )
        except ValueError as error:
            return self._failure(
                "initialization",
                str(error),
                "initialized",
            )
        except Exception:  # noqa: BLE001 - sanitize the MCP boundary
            return self._failure(
                "initialization",
                "GHOST persistent chat storage failed",
                "initialized",
            )

        file_id = str(state["file_id"])
        clean_title = str(state["title"])
        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": (
                        "Persistent Chat Memory initialized.\n"
                        f"Title: {clean_title}\n"
                        f"File ID: {file_id}\n"
                        "No episode has been saved yet. For the first normal "
                        "Q/A, create the initial cumulative ActiveBrief and "
                        "use ghost_persistent_chat_append."
                    ),
                }
            ],
            structuredContent={
                "initialized": True,
                "file_id": file_id,
                "title": clean_title,
                "memory_type": str(state["memory_type"]),
                "record_count": int(state["record_count"]),
            },
        )

    def append_sanitized(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        """Validate and append one persistent Q/A episode."""
        required_fields = (
            "file_id",
            "input_text",
            "output_text",
            "active_retrieval_brief",
        )
        error = self._validate_request(
            owner_sub,
            arguments,
            set(required_fields),
            "persistent chat append input is required",
        )
        if error is not None:
            return self._failure("append", error, "saved")
        assert arguments is not None

        values: dict[str, str] = {}
        for field_name in required_fields:
            value = arguments.get(field_name)
            if not isinstance(value, str) or not value.strip():
                return self._failure(
                    "append",
                    f"{field_name} is required and must be a non-empty string",
                    "saved",
                )
            values[field_name] = value

        try:
            result = self._store.append_episode(
                owner_sub=owner_sub,
                file_id=values["file_id"],
                input_text=values["input_text"],
                output_text=values["output_text"],
                active_retrieval_brief=values["active_retrieval_brief"],
            )
        except PersistentChatPartialSaveError as error:
            return GhostToolResult(
                content=[
                    {
                        "type": "text",
                        "text": (
                            "Persistent Chat episode was NOT confirmed saved. "
                            "The durable memory body contains Record ID "
                            f"{error.record_id}, but metadata/index update failed."
                        ),
                    }
                ],
                structuredContent={
                    "saved": False,
                    "record_id": error.record_id,
                    "durable_memory_written": True,
                },
                isError=True,
            )
        except ValueError as error:
            return self._failure("append", str(error), "saved")
        except Exception:  # noqa: BLE001 - sanitize the MCP boundary
            return self._failure(
                "append",
                "GHOST persistent chat storage failed",
                "saved",
            )

        record_id = str(result["record_id"])
        receipt = f"GHOST saved — Record ID: {record_id}"
        return GhostToolResult(
            content=[{"type": "text", "text": receipt}],
            structuredContent={
                "saved": True,
                "file_id": str(result["file_id"]),
                "record_id": record_id,
                "sequence_number": int(result["sequence_number"]),
                "created_at_utc": str(result["created_at_utc"]),
                "receipt": receipt,
            },
        )

    def resume_sanitized(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        """Validate an episode handle and return the latest resumable state."""
        error = self._validate_request(
            owner_sub,
            arguments,
            {"record_id"},
            "persistent chat resume input is required",
        )
        if error is not None:
            return self._failure("resume", error, "resumed")
        assert arguments is not None

        record_id = arguments.get("record_id")
        if not isinstance(record_id, str) or not record_id.strip():
            return self._failure(
                "resume",
                "record_id is required and must be a non-empty string",
                "resumed",
            )
        clean_record_id = record_id.strip()

        try:
            state = self._store.resume_from_record(
                owner_sub=owner_sub,
                record_id=clean_record_id,
            )
        except ValueError as error:
            return self._failure("resume", str(error), "resumed")
        except Exception:  # noqa: BLE001 - sanitize the MCP boundary
            return self._failure(
                "resume",
                "GHOST persistent chat recovery failed",
                "resumed",
            )

        if state is None:
            return self._failure(
                "resume",
                (
                    "record_id did not resolve to an existing Persistent Chat "
                    "Memory for the authenticated user; no memory was created"
                ),
                "resumed",
            )

        latest_record_id = str(state["latest_record_id"])
        active_brief = str(state["active_retrieval_brief"])
        text = (
            "Persistent Chat Memory resumed.\n"
            f"File ID: {state['file_id']}\n"
            f"Resume handle: {clean_record_id}\n"
            f"Latest Record ID: {latest_record_id}\n"
            "Continue from the latest state below and use "
            "ghost_persistent_chat_append for subsequent normal Q/A.\n\n"
            "Latest ActiveBrief:\n"
            f"{active_brief}"
        )
        return GhostToolResult(
            content=[{"type": "text", "text": text}],
            structuredContent={
                "resumed": True,
                "resume_record_id": clean_record_id,
                "file_id": str(state["file_id"]),
                "title": str(state["title"]),
                "memory_description": str(state["memory_description"]),
                "record_count": int(state["record_count"]),
                "latest_record_id": latest_record_id,
                "latest_sequence_number": int(
                    state["latest_sequence_number"]
                ),
                "latest_created_at_utc": str(
                    state["latest_created_at_utc"]
                ),
                "active_retrieval_brief_title": str(
                    state["active_retrieval_brief_title"]
                ),
                "active_retrieval_brief": active_brief,
            },
        )

    @staticmethod
    def _validate_request(
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
        allowed_properties: set[str],
        missing_input_message: str,
    ) -> str | None:
        if not isinstance(owner_sub, str) or not owner_sub.strip():
            return "authenticated user is required"
        if not isinstance(arguments, Mapping):
            return missing_input_message
        if set(arguments).difference(allowed_properties):
            return "unsupported input property"
        return None

    @staticmethod
    def _failure(
        operation: str,
        reason: str,
        status_field: str,
    ) -> GhostToolResult:
        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": (
                        f"Persistent Chat {operation} failed. Reason: {reason}."
                    ),
                }
            ],
            structuredContent={status_field: False},
            isError=True,
        )


def init_tool_metadata(required_scope: str | None = None) -> dict[str, Any]:
    """Build the initialization tool descriptor."""
    return _tool_metadata(
        required_scope=required_scope,
        name=INIT_TOOL_NAME,
        title="GHOST Persistent Chat Initialize",
        description=INIT_TOOL_DESCRIPTION,
        input_schema=INIT_INPUT_SCHEMA,
        output_schema=INIT_OUTPUT_SCHEMA,
        read_only=False,
        idempotent=False,
    )


def append_tool_metadata(required_scope: str | None = None) -> dict[str, Any]:
    """Build the episode-append tool descriptor."""
    return _tool_metadata(
        required_scope=required_scope,
        name=APPEND_TOOL_NAME,
        title="GHOST Persistent Chat Append",
        description=APPEND_TOOL_DESCRIPTION,
        input_schema=APPEND_INPUT_SCHEMA,
        output_schema=APPEND_OUTPUT_SCHEMA,
        read_only=False,
        idempotent=False,
    )


def resume_tool_metadata(required_scope: str | None = None) -> dict[str, Any]:
    """Build the deterministic resume tool descriptor."""
    return _tool_metadata(
        required_scope=required_scope,
        name=RESUME_TOOL_NAME,
        title="GHOST Persistent Chat Resume",
        description=RESUME_TOOL_DESCRIPTION,
        input_schema=RESUME_INPUT_SCHEMA,
        output_schema=RESUME_OUTPUT_SCHEMA,
        read_only=True,
        idempotent=True,
    )


def _tool_metadata(
    *,
    required_scope: str | None,
    name: str,
    title: str,
    description: str,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
    read_only: bool,
    idempotent: bool,
) -> dict[str, Any]:
    scope = (
        required_scope
        if required_scope is not None
        else DEFAULT_REQUIRED_SCOPE
    ).strip()
    if not scope:
        raise ValueError("required_scope must not be empty")

    security_schemes = [{"type": "oauth2", "scopes": [scope]}]
    return {
        "name": name,
        "title": title,
        "description": description,
        "inputSchema": input_schema,
        "outputSchema": output_schema,
        "securitySchemes": security_schemes,
        "_meta": {"securitySchemes": security_schemes.copy()},
        "annotations": {
            "destructiveHint": False,
            "readOnlyHint": read_only,
            "idempotentHint": idempotent,
            "openWorldHint": False,
        },
    }