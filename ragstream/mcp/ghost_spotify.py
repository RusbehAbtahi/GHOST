"""Expose focused Spotify operations as GHOST MCP tools.

Main class:
    GhostSpotifyTool:
        Validates MCP input and delegates directly to SpotifyController.

Main methods:
    device_check_sanitized():
        Check live Spotify Connect readiness.
    start_sanitized():
        Start one exact track or episode inside one exact parent context.
    add_queue_sanitized():
        Add exact ordered track URIs to Spotify's live queue.
    pause_sanitized():
        Pause Spotify and start the silent keepalive.
    stop_sanitized():
        Stop the GHOST Spotify session and cancel keepalive.
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
from ragstream.tools.spotify.spotify_controller import (
    SpotifyController,
    SpotifyQueuePartialFailure,
)


DEVICE_CHECK_TOOL_NAME = "ghost_spotify_device_check"
START_TOOL_NAME = "ghost_spotify_start"
ADD_QUEUE_TOOL_NAME = "ghost_spotify_add_queue"
PAUSE_TOOL_NAME = "ghost_spotify_pause"
STOP_TOOL_NAME = "ghost_spotify_stop"

_INSTRUCTIONS = load_memory_tool_instructions("custom_spotify.json")
TOOL_DESCRIPTION = _INSTRUCTIONS.tool_description
SERVER_INSTRUCTIONS = _INSTRUCTIONS.server_instruction


def _oauth_metadata(
    name: str,
    title: str,
    description: str,
    input_schema: dict[str, Any],
    *,
    read_only: bool,
    required_scope: str | None,
) -> dict[str, Any]:
    scope = (required_scope or DEFAULT_REQUIRED_SCOPE).strip()
    if not scope:
        raise ValueError("required_scope must not be empty")

    security_schemes = [{"type": "oauth2", "scopes": [scope]}]
    return {
        "name": name,
        "title": title,
        "description": description,
        "inputSchema": input_schema,
        "securitySchemes": security_schemes,
        "_meta": {"securitySchemes": security_schemes.copy()},
        "annotations": {
            "destructiveHint": False,
            "readOnlyHint": read_only,
            "idempotentHint": read_only,
            "openWorldHint": True,
        },
    }


def device_check_tool_metadata(required_scope=None) -> dict[str, Any]:
    return _oauth_metadata(
        DEVICE_CHECK_TOOL_NAME,
        "GHOST Spotify Device Check",
        _INSTRUCTIONS.field_descriptions["device_check_tool"],
        {"type": "object", "properties": {}, "additionalProperties": False},
        read_only=True,
        required_scope=required_scope,
    )

def start_tool_metadata(
    required_scope: str | None = None,
) -> dict[str, Any]:
    return _oauth_metadata(
        START_TOOL_NAME,
        "GHOST Spotify Start",
        _INSTRUCTIONS.field_descriptions["start_tool"],
        {
            "type": "object",
            "properties": {
                "parent_uri": {
                    "type": "string",
                    "minLength": 1,
                    "description": _INSTRUCTIONS.field_descriptions[
                        "parent_uri"
                    ],
                },
                "starter_track_uri": {
                    "type": "string",
                    "minLength": 1,
                    "description": _INSTRUCTIONS.field_descriptions[
                        "starter_track_uri"
                    ],
                },
            },
            "required": ["parent_uri", "starter_track_uri"],
            "additionalProperties": False,
        },
        read_only=False,
        required_scope=required_scope,
    )


def add_queue_tool_metadata(
    required_scope: str | None = None,
) -> dict[str, Any]:
    return _oauth_metadata(
        ADD_QUEUE_TOOL_NAME,
        "GHOST Spotify Add Queue",
        _INSTRUCTIONS.field_descriptions["add_queue_tool"],
        {
            "type": "object",
            "properties": {
                "track_uris": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "string",
                        "minLength": 1,
                    },
                    "description": _INSTRUCTIONS.field_descriptions[
                        "track_uris"
                    ],
                }
            },
            "required": ["track_uris"],
            "additionalProperties": False,
        },
        read_only=False,
        required_scope=required_scope,
    )


def pause_tool_metadata(
    required_scope: str | None = None,
) -> dict[str, Any]:
    return _oauth_metadata(
        PAUSE_TOOL_NAME,
        "GHOST Spotify Pause",
        _INSTRUCTIONS.field_descriptions["pause_tool"],
        {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        read_only=False,
        required_scope=required_scope,
    )


def stop_tool_metadata(
    required_scope: str | None = None,
) -> dict[str, Any]:
    return _oauth_metadata(
        STOP_TOOL_NAME,
        "GHOST Spotify Stop",
        _INSTRUCTIONS.field_descriptions["stop_tool"],
        {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        read_only=False,
        required_scope=required_scope,
    )


def _result(
    message: str,
    structured: dict[str, Any] | None = None,
    error: Exception | None = None,
) -> GhostToolResult:
    if error is None:
        return GhostToolResult(
            content=[{"type": "text", "text": message}],
            structuredContent=structured or {},
        )

    return GhostToolResult(
        content=[
            {
                "type": "text",
                "text": f"{message}. Reason: {error}.",
            }
        ],
        structuredContent=structured or {},
        isError=True,
    )


def _require_empty_input(
    arguments: Mapping[str, Any] | None,
    operation: str,
) -> None:
    if arguments is None:
        return
    if not isinstance(arguments, Mapping) or arguments:
        raise ValueError(f"Spotify {operation} accepts no input properties")


class GhostSpotifyTool:
    """Adapt the focused Spotify operations to stable MCP results."""

    def __init__(
        self,
        controller: SpotifyController | None = None,
    ) -> None:
        self._controller_instance = controller

    def device_check_sanitized(self, arguments=None) -> GhostToolResult:
        """Check live Spotify Connect readiness."""
        try:
            _require_empty_input(arguments, "device check")
            return _result(
                "Spotify device is ready.",
                self._controller().device_ready(),
            )
        except Exception as error:
            return _result(
                "Spotify device check failed",
                {"ready": False, "reason": str(error)},
                error=error,
            )

    def start_sanitized(
        self,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        """Start one exact starter track or episode inside one exact parent context."""
        try:
            if not isinstance(arguments, Mapping):
                raise ValueError("Spotify start input is required")
            if set(arguments) != {"parent_uri", "starter_track_uri"}:
                raise ValueError(
                    "Spotify start requires only parent_uri and starter_track_uri"
                )

            parent_uri = arguments.get("parent_uri")
            starter_track_uri = arguments.get("starter_track_uri")
            if not isinstance(parent_uri, str) or not parent_uri.strip():
                raise ValueError("parent_uri must be a non-empty string")
            if (
                not isinstance(starter_track_uri, str)
                or not starter_track_uri.strip()
            ):
                raise ValueError(
                    "starter_track_uri must be a non-empty string"
                )

            result = self._controller().start(
                parent_uri.strip(),
                starter_track_uri.strip(),
            )
            return _result("Spotify playback started.", result)
        except Exception as error:
            return _result("Spotify start failed", error=error)

    def add_queue_sanitized(
        self,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        """Add exact ordered track URIs to Spotify's current live queue."""
        try:
            if not isinstance(arguments, Mapping):
                raise ValueError("Spotify add_queue input is required")
            if set(arguments) != {"track_uris"}:
                raise ValueError("Spotify add_queue requires only track_uris")

            track_uris = arguments.get("track_uris")
            if not isinstance(track_uris, list) or not track_uris:
                raise ValueError("track_uris must be a non-empty array")
            if any(
                not isinstance(value, str) or not value.strip()
                for value in track_uris
            ):
                raise ValueError("every track_uris item must be a non-empty string")

            result = self._controller().add_queue(
                [value.strip() for value in track_uris]
            )
            return _result("Spotify queue updated.", result)
        except SpotifyQueuePartialFailure as error:
            structured = {
                "action": "queue_partial_failure",
                "queued_count": len(error.queued_track_uris),
                "queued_track_uris": error.queued_track_uris,
                "failed_index": len(error.queued_track_uris) + 1,
                "failed_track_uri": error.failed_track_uri,
                "remaining_track_uris": error.remaining_track_uris,
                "delivery_uncertain": error.delivery_uncertain,
            }
            return _result(
                "Spotify add queue stopped before completion",
                structured,
                error=error,
            )
        except Exception as error:
            return _result(
                "Spotify add queue failed",
                {"action": "queue_failed", "reason": str(error)},
                error=error,
            )

    def pause_sanitized(
        self,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        """Pause playback and start the silent two-hour keepalive."""
        try:
            _require_empty_input(arguments, "pause")
            return _result("Spotify paused.", self._controller().pause())
        except Exception as error:
            return _result("Spotify pause failed", error=error)

    def stop_sanitized(
        self,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        """Stop playback and terminate any GHOST keepalive."""
        try:
            _require_empty_input(arguments, "stop")
            return _result("Spotify stopped.", self._controller().stop())
        except Exception as error:
            return _result("Spotify stop failed", error=error)

    def _controller(self) -> SpotifyController:
        if self._controller_instance is None:
            self._controller_instance = SpotifyController()
        return self._controller_instance
