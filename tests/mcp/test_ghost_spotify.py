"""Tests for the five minimal Spotify MCP tools and application registration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ragstream.mcp.ghost_mcp_app import GhostMcpApplication
from ragstream.mcp.ghost_prompt_settings import GhostPromptSettings
from ragstream.mcp.ghost_spotify import (
    ADD_QUEUE_TOOL_NAME,
    DEVICE_CHECK_TOOL_NAME,
    PAUSE_TOOL_NAME,
    SERVER_INSTRUCTIONS as SPOTIFY_SERVER_INSTRUCTIONS,
    START_TOOL_NAME,
    STOP_TOOL_NAME,
    GhostSpotifyTool,
)


class FakeController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def device_ready(self) -> dict[str, Any]:
        self.calls.append(("device_ready", ()))
        return {
            "ready": True,
            "device": {
                "name": "Phone",
                "type": "Smartphone",
                "is_active": True,
            },
        }

    def playlist_tracks(self, parent_uri: str | None = None) -> dict[str, Any]:
        self.calls.append(("playlist_tracks", (parent_uri,)))
        if parent_uri is None:
            return {
                "ready": True,
                "device": {
                    "name": "Phone",
                    "type": "Smartphone",
                    "is_active": True,
                },
            }
        return {
            "ready": True,
            "device": {
                "name": "Phone",
                "type": "Smartphone",
                "is_active": True,
            },
            "parent_uri": parent_uri,
            "track_count": 1,
            "tracks": [
                {
                    "position": 1,
                    "title": "Movement I",
                    "artists": ["Quartet"],
                    "uri": "spotify:track:one",
                    "type": "track",
                    "available": True,
                }
            ],
        }

    def start(
        self,
        parent_uri: str,
        starter_track_uri: str,
    ) -> dict[str, Any]:
        self.calls.append(("start", (parent_uri, starter_track_uri)))
        return {
            "action": "started",
            "parent_uri": parent_uri,
            "starter_track_uri": starter_track_uri,
        }

    def add_queue(self, track_uris: list[str]) -> dict[str, Any]:
        self.calls.append(("add_queue", (tuple(track_uris),)))
        return {
            "action": "queued",
            "track_count": len(track_uris),
            "track_uris": track_uris,
        }

    def pause(self) -> dict[str, Any]:
        self.calls.append(("pause", ()))
        return {"action": "paused", "keepalive": True}

    def stop(self) -> dict[str, Any]:
        self.calls.append(("stop", ()))
        return {"action": "stopped", "keepalive": False}


class NoopBuilder:
    def build(self, **arguments: Any) -> dict[str, Any]:
        return {
            "status": "complete",
            "prompt": arguments.get("prompt_text", ""),
            "clarification_question": "",
            "general_skill_candidates": [],
            "receipt": {"status": "complete"},
        }


def test_adapter_exposes_five_focused_operations() -> None:
    controller = FakeController()
    tool = GhostSpotifyTool(controller=controller)  # type: ignore[arg-type]

    ready = tool.device_check_sanitized({})
    started = tool.start_sanitized(
        {
            "parent_uri": "spotify:playlist:parent",
            "starter_track_uri": "spotify:track:one",
        }
    )
    queued = tool.add_queue_sanitized(
        {"track_uris": ["spotify:track:one", "spotify:track:two"]}
    )
    paused = tool.pause_sanitized({})
    stopped = tool.stop_sanitized({})

    assert ready.isError is False
    assert ready.structuredContent["ready"] is True
    assert started.structuredContent["action"] == "started"
    assert queued.structuredContent["track_count"] == 2
    assert paused.structuredContent["keepalive"] is True
    assert stopped.structuredContent["keepalive"] is False
    assert controller.calls == [
        ("device_ready", ()),
        (
            "start",
            ("spotify:playlist:parent", "spotify:track:one"),
        ),
        ("add_queue", (("spotify:track:one", "spotify:track:two"),)),
        ("pause", ()),
        ("stop", ()),
    ]



def test_start_forwards_episode_uri_unchanged() -> None:
    controller = FakeController()
    tool = GhostSpotifyTool(controller=controller)  # type: ignore[arg-type]

    started = tool.start_sanitized(
        {
            "parent_uri": "spotify:playlist:parent",
            "starter_track_uri": "spotify:episode:lecture",
        }
    )

    assert started.isError is False
    assert started.structuredContent["starter_track_uri"] == "spotify:episode:lecture"
    assert controller.calls == [
        ("start", ("spotify:playlist:parent", "spotify:episode:lecture"))
    ]


def test_start_rejects_extra_or_missing_properties() -> None:
    tool = GhostSpotifyTool(controller=FakeController())  # type: ignore[arg-type]

    missing = tool.start_sanitized(
        {"parent_uri": "spotify:playlist:parent"}
    )
    extra = tool.start_sanitized(
        {
            "parent_uri": "spotify:playlist:parent",
            "starter_track_uri": "spotify:track:one",
            "mode": "loop",
        }
    )

    assert missing.isError is True
    assert extra.isError is True



def test_add_queue_requires_only_non_empty_track_uri_array() -> None:
    tool = GhostSpotifyTool(controller=FakeController())  # type: ignore[arg-type]

    missing = tool.add_queue_sanitized({})
    empty = tool.add_queue_sanitized({"track_uris": []})
    extra = tool.add_queue_sanitized(
        {"track_uris": ["spotify:track:one"], "position": 1}
    )

    assert missing.isError is True
    assert empty.isError is True
    assert extra.isError is True


def test_pause_and_stop_accept_no_properties() -> None:
    tool = GhostSpotifyTool(controller=FakeController())  # type: ignore[arg-type]

    assert tool.pause_sanitized({"device_name": "Phone"}).isError is True
    assert tool.stop_sanitized({"action": "anything"}).isError is True



def test_application_registers_exactly_five_spotify_tools(tmp_path: Path) -> None:
    spotify_tool = GhostSpotifyTool(
        controller=FakeController(),  # type: ignore[arg-type]
     )
    application = GhostMcpApplication(
        prompt_builder=NoopBuilder(),  # type: ignore[arg-type],
        prompt_settings=GhostPromptSettings(tmp_path / "settings"),
        spotify_tool=spotify_tool,
    )

    names = {tool.name for tool in application.list_tools()}
    spotify_names = {name for name in names if name.startswith("ghost_spotify_")}

    assert spotify_names == {
        DEVICE_CHECK_TOOL_NAME,
        START_TOOL_NAME,
        ADD_QUEUE_TOOL_NAME,
        PAUSE_TOOL_NAME,
        STOP_TOOL_NAME,
    }

    result = application.call_tool(
        START_TOOL_NAME,
        {
            "parent_uri": "spotify:playlist:parent",
            "starter_track_uri": "spotify:track:one",
        },
        "owner",
    )
    assert result.isError is False
    assert result.structuredContent["action"] == "started"

    queued = application.call_tool(
        ADD_QUEUE_TOOL_NAME,
        {"track_uris": ["spotify:track:one", "spotify:track:two"]},
        "owner",
    )
    assert queued.isError is False
    assert queued.structuredContent["track_count"] == 2

def test_spotify_server_instructions_enforce_collection_routing() -> None:
    instructions = SPOTIFY_SERVER_INSTRUCTIONS

    assert "d839053d0f1c456197de0c2246f01d30" in instructions
    assert "Spotify_Collection" in instructions
    assert "REUSE FIRST" in instructions
    assert "{parent_uri, track_uri}" in instructions
    assert "list_mode collection_episodes" in instructions
    assert "select only the Episode or Episodes relevant" in instructions
    assert "exact record_id" in instructions
    assert "ghost_spotify_start" in instructions
    assert "spotify:episode" in instructions
    assert "ghost_spotify_add_queue" in instructions
    assert "ghost_spotify_device_check" not in instructions
    assert "device-readiness" not in instructions
    assert "device readiness" not in instructions
    assert "Spotify web search" in instructions
    assert "not found in the Collection" in instructions


def test_spotify_server_instructions_preserve_literal_queue_order() -> None:
    instructions = SPOTIFY_SERVER_INSTRUCTIONS

    assert "ordered {parent_uri, track_uri} pairs" in instructions
    assert "Preserve the user's requested order and musical movement order exactly" in instructions
    assert "Project those pairs to the ordered track_uri list" in instructions
    assert "ghost_spotify_add_queue exactly once" in instructions
    assert "Do not deduplicate, reorder, skip, or infer continuation" in instructions


def test_spotify_server_instructions_reuse_resolved_data() -> None:
    instructions = SPOTIFY_SERVER_INSTRUCTIONS

    assert "if the exact requested music" in instructions
    assert "reuse those exact values immediately" in instructions
    assert "Do not list, recall, search, verify, or resolve them again" in instructions
    assert "Keep both values even when the current action ultimately needs only track_uri" in instructions


def test_spotify_server_instructions_forbid_autonomous_recovery() -> None:
    instructions = SPOTIFY_SERVER_INSTRUCTIONS

    assert "Do not use another Collection" in instructions
    assert "generic RAG/vector retrieval" in instructions
    assert "CLI search" in instructions
    assert "public web search" in instructions
    assert "Spotify web search" in instructions
    assert "invented Spotify URIs" in instructions
    assert "If materially different recordings remain plausible, ask one concise clarification" in instructions
    assert "If the exact requested item cannot be resolved from Spotify_Collection, stop" in instructions
    assert "Report only the actual result returned by the Spotify action tool" in instructions
