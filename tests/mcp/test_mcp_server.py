"""Focused tests for the current GHOST MCP application boundary."""

from __future__ import annotations

from typing import Any

import mcp.types as types
import pytest
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import McpError
from starlette.routing import Route

from ragstream.mcp import server as server_module
from ragstream.mcp.ghost_mcp_app import GhostMcpApplication
from ragstream.mcp.ghost_prompt_builder import STATUS_COMPLETE
from ragstream.mcp.ghost_prompt_run import TOOL_NAME as RUN_TOOL_NAME
from ragstream.mcp.ghost_prompt_settings import (
    GhostPromptSettings,
    TOOL_NAME as SETTINGS_TOOL_NAME,
)
from ragstream.mcp.ghost_prompt_show import TOOL_NAME as SHOW_TOOL_NAME
from ragstream.mcp.server import GhostMcpRuntime


class RecordingBuilder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def build(self, **arguments: Any) -> dict[str, Any]:
        self.calls.append(arguments)
        return {
            "status": STATUS_COMPLETE,
            "prompt": f"BUILT: {arguments['prompt_text']}",
            "clarification_question": "",
            "general_skill_candidates": [],
            "receipt": {"status": STATUS_COMPLETE},
        }


@pytest.fixture
def builder() -> RecordingBuilder:
    return RecordingBuilder()


@pytest.fixture
def ghost_application(
    tmp_path,
    builder: RecordingBuilder,
) -> GhostMcpApplication:
    return GhostMcpApplication(
        prompt_builder=builder,  # type: ignore[arg-type]
        prompt_settings=GhostPromptSettings(tmp_path),
    )


def test_application_lists_three_separate_prompt_tools(
    ghost_application: GhostMcpApplication,
) -> None:
    names = [tool.name for tool in ghost_application.list_tools()]

    assert names[:3] == [
        SHOW_TOOL_NAME,
        RUN_TOOL_NAME,
        SETTINGS_TOOL_NAME,
    ]
    assert "ghost_engineer_prompt" not in names


@pytest.mark.parametrize(
    ("tool_name", "expected_mode"),
    [
        (SHOW_TOOL_NAME, "show_prompt"),
        (RUN_TOOL_NAME, "run_prompt"),
    ],
)
def test_application_dispatches_show_and_run_through_same_builder(
    ghost_application: GhostMcpApplication,
    builder: RecordingBuilder,
    tool_name: str,
    expected_mode: str,
) -> None:
    result = ghost_application.call_tool(
        tool_name,
        {"prompt_text": "task"},
        "owner",
    )

    assert result.isError is False
    assert result.structuredContent is not None
    assert result.structuredContent["prompt"] == "BUILT: task"
    assert result.structuredContent["mode"] == expected_mode
    assert builder.calls[-1]["owner_sub"] == "owner"


def test_application_dispatches_owner_scoped_settings(
    ghost_application: GhostMcpApplication,
) -> None:
    result = ghost_application.call_tool(
        SETTINGS_TOOL_NAME,
        {
            "action": "set",
            "updates": {"memory_recency_enabled": False},
        },
        "owner",
    )

    assert result.isError is False
    assert result.structuredContent is not None
    assert result.structuredContent["settings"][
        "memory_recency_enabled"
    ] is False


def test_unknown_tool_remains_an_mcp_error(
    ghost_application: GhostMcpApplication,
) -> None:
    with pytest.raises(McpError) as error:
        ghost_application.call_tool("unknown", {}, "owner")

    assert error.value.error.code == types.INVALID_PARAMS


def test_runtime_exposes_the_mcp_route(
    ghost_application: GhostMcpApplication,
) -> None:
    runtime = GhostMcpRuntime(
        ghost_application=ghost_application,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
    )

    assert len(runtime.starlette_app.routes) == 1
    route = runtime.starlette_app.routes[0]
    assert isinstance(route, Route)
    assert route.path == server_module.MCP_PATH
    assert route.endpoint is runtime


def test_environment_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GHOST_MCP_HOST", raising=False)
    monkeypatch.delenv("GHOST_MCP_PORT", raising=False)
    monkeypatch.delenv("GHOST_MCP_LOG_LEVEL", raising=False)

    assert server_module._read_host() == server_module.DEFAULT_HOST
    assert server_module._read_port() == server_module.DEFAULT_PORT
    assert (
        server_module._read_uvicorn_log_level()
        == server_module.DEFAULT_UVICORN_LOG_LEVEL
    )
