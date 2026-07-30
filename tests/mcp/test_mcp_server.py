"""Tests for the GHOST low-level MCP server runtime.

These tests intentionally do not start Uvicorn and do not require AWS.
The protocol tests connect an MCP ClientSession directly to the low-level
MCP Server through the official SDK's in-memory transport.

Covered requirement areas:
- GHOST-MCP-PROTOCOL-INITIALIZATION
- GHOST-MCP-TOOLS-LIST
- GHOST-MCP-TOOLS-CALL
- GHOST-MCP-MALFORMED-REQUEST-ERROR
- GHOST-MCP-INPUT-VALIDATION-ERROR
- GHOST-MCP-PROTOCOL-ACCEPTANCE
- GHOST-MCP-TOOL-INVENTORY-ACCEPTANCE
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

import mcp.types as types
import pytest
from mcp.client.session import ClientSession
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session
from starlette.routing import Route

from ragstream.mcp.ghost_engineer_prompt import (
    GhostEngineerPromptTool,
    GhostToolResult,
    INPUT_SCHEMA,
    OUTPUT_SCHEMA,
    TOOL_DESCRIPTION,
    TOOL_NAME,
    TOOL_TITLE,
)
from ragstream.mcp import server as server_module
from ragstream.mcp.server import GhostMcpApplication, GhostMcpRuntime


ENGINEERED_PROMPT = "## TASK\nExplain the GHOST MCP server architecture."
RAW_PROMPT = "Explain the GHOST MCP server architecture."


@dataclass
class RecordingRunner:
    """Small deterministic runner used instead of PreProcessing, A2, and OpenAI."""

    result: str = ENGINEERED_PROMPT
    error: Exception | None = None
    calls: list[str] = field(default_factory=list)

    def run(self, prompt_text: str) -> str:
        self.calls.append(prompt_text)

        if self.error is not None:
            raise self.error

        return self.result


@pytest.fixture
def anyio_backend() -> str:
    """Run AnyIO tests only with asyncio, matching Uvicorn's normal backend."""

    return "asyncio"


@pytest.fixture
def runner() -> RecordingRunner:
    return RecordingRunner()


@pytest.fixture
def ghost_application(runner: RecordingRunner) -> GhostMcpApplication:
    tool = GhostEngineerPromptTool(runner)  # type: ignore[arg-type]
    return GhostMcpApplication(tool=tool)


@pytest.fixture
def runtime(ghost_application: GhostMcpApplication) -> GhostMcpRuntime:
    # No HTTP headers are involved in the in-memory protocol tests.
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    )

    return GhostMcpRuntime(
        ghost_application=ghost_application,
        transport_security=security,
    )


@pytest.fixture
async def client_session(
    runtime: GhostMcpRuntime,
) -> AsyncGenerator[ClientSession, None]:
    """Create an initialized MCP client connected directly to the server.

    The SDK helper starts the low-level server, performs initialize, receives
    the initialization result, and sends notifications/initialized before it
    yields the ClientSession.
    """

    async with create_connected_server_and_client_session(
        runtime.mcp_server,
        raise_exceptions=False,
    ) as session:
        yield session


def _single_text(result: types.CallToolResult) -> str:
    assert len(result.content) == 1

    content = result.content[0]
    assert isinstance(content, types.TextContent)

    return content.text


@pytest.mark.anyio
async def test_protocol_initialization_advertises_only_tools(
    client_session: ClientSession,
) -> None:
    """Initialization must advertise tools and no unsupported capability."""

    capabilities = client_session.get_server_capabilities()

    assert capabilities is not None
    assert capabilities.tools is not None
    assert capabilities.prompts is None
    assert capabilities.resources is None
    assert capabilities.logging is None
    assert capabilities.completions is None
    assert capabilities.tasks is None
    assert capabilities.experimental == {}


@pytest.mark.anyio
async def test_protocol_lists_exactly_one_ghost_tool(
    client_session: ClientSession,
) -> None:
    """tools/list must expose only the approved Version-1 GHOST tool."""

    result = await client_session.list_tools()

    assert [tool.name for tool in result.tools] == [TOOL_NAME]

    tool = result.tools[0]
    assert tool.title == TOOL_TITLE
    assert tool.description == TOOL_DESCRIPTION
    assert tool.inputSchema == INPUT_SCHEMA
    assert tool.outputSchema == OUTPUT_SCHEMA

    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.idempotentHint is False
    assert tool.annotations.openWorldHint is True


@pytest.mark.anyio
async def test_protocol_calls_tool_and_returns_exact_success_contract(
    client_session: ClientSession,
    runner: RecordingRunner,
) -> None:
    """tools/call must preserve text, structured content, and a2 stage."""

    result = await client_session.call_tool(
        TOOL_NAME,
        arguments={"prompt_text": RAW_PROMPT},
    )

    assert result.isError is False
    assert _single_text(result) == ENGINEERED_PROMPT
    assert result.structuredContent == {
        "engineered_prompt": ENGINEERED_PROMPT,
        "stage": "a2",
    }
    assert runner.calls == [RAW_PROMPT]


@pytest.mark.anyio
async def test_unknown_tool_is_protocol_error_and_does_not_execute_ghost(
    client_session: ClientSession,
    runner: RecordingRunner,
) -> None:
    """An undeclared tool name must remain a JSON-RPC/MCP error."""

    with pytest.raises(McpError) as exc_info:
        await client_session.call_tool(
            "unknown_tool",
            arguments={"prompt_text": RAW_PROMPT},
        )

    assert exc_info.value.error.code == types.INVALID_PARAMS
    assert exc_info.value.error.message == "Unknown tool: unknown_tool"
    assert runner.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("arguments", "expected_message"),
    [
        (None, "prompt_text is required and must be a non-empty string"),
        ({}, "prompt_text is required and must be a non-empty string"),
        ({"prompt_text": 42}, "prompt_text must be a non-empty string"),
        ({"prompt_text": "   \n\t"}, "prompt_text must be a non-empty string"),
        (
            {"prompt_text": RAW_PROMPT, "unsupported": True},
            "unsupported input property",
        ),
    ],
)
async def test_invalid_tool_arguments_return_sanitized_tool_error(
    client_session: ClientSession,
    runner: RecordingRunner,
    arguments: dict[str, Any] | None,
    expected_message: str,
) -> None:
    """Valid tools/call envelopes with bad arguments must use isError=true."""

    result = await client_session.call_tool(
        TOOL_NAME,
        arguments=arguments,
    )

    assert result.isError is True
    assert result.structuredContent is None
    assert _single_text(result) == expected_message
    assert runner.calls == []


@pytest.mark.anyio
async def test_unexpected_runner_failure_is_sanitized(
    runtime: GhostMcpRuntime,
) -> None:
    """Internal exception details must not cross the MCP tool boundary."""

    secret_error = RuntimeError(
        "/tmp/private OPENAI_API_KEY=secret raw-model-output Traceback"
    )
    failing_runner = RecordingRunner(error=secret_error)
    tool = GhostEngineerPromptTool(failing_runner)  # type: ignore[arg-type]
    runtime.ghost_application = GhostMcpApplication(tool=tool)

    # The low-level MCP handlers reference runtime.ghost_application at call time,
    # therefore replacing it here keeps the same registered server object.
    async with create_connected_server_and_client_session(
        runtime.mcp_server,
        raise_exceptions=False,
    ) as session:
        result = await session.call_tool(
            TOOL_NAME,
            arguments={"prompt_text": RAW_PROMPT},
        )

    message = _single_text(result)

    assert result.isError is True
    assert message == "GHOST prompt engineering failed"
    assert "/tmp/private" not in message
    assert "OPENAI_API_KEY" not in message
    assert "raw-model-output" not in message
    assert "Traceback" not in message
    assert failing_runner.calls == [RAW_PROMPT]


@pytest.mark.parametrize(
    "internal_result",
    [
        GhostToolResult(
            content=[],
            structuredContent={
                "engineered_prompt": ENGINEERED_PROMPT,
                "stage": "a2",
            },
        ),
        GhostToolResult(
            content=[{"type": "text", "text": "different text"}],
            structuredContent={
                "engineered_prompt": ENGINEERED_PROMPT,
                "stage": "a2",
            },
        ),
        GhostToolResult(
            content=[{"type": "text", "text": ENGINEERED_PROMPT}],
            structuredContent={
                "engineered_prompt": ENGINEERED_PROMPT,
                "stage": "preprocessed",
            },
        ),
        GhostToolResult(
            content=[{"type": "text", "text": ENGINEERED_PROMPT}],
            structuredContent={
                "engineered_prompt": ENGINEERED_PROMPT,
                "stage": "a2",
                "unexpected": "value",
            },
        ),
        GhostToolResult(
            content=[{"type": "text", "text": ENGINEERED_PROMPT}],
            structuredContent={
                "engineered_prompt": "   ",
                "stage": "a2",
            },
        ),
    ],
)
def test_application_rejects_invalid_internal_success_result(
    internal_result: GhostToolResult,
) -> None:
    """The adapter must never publish an inconsistent success result."""

    result = GhostMcpApplication._to_mcp_result(internal_result)

    assert result.isError is True
    assert result.structuredContent is None
    assert _single_text(result) == "GHOST returned an invalid tool result"


def test_application_preserves_sanitized_internal_tool_error() -> None:
    internal_result = GhostToolResult(
        content=[
            {
                "type": "text",
                "text": "prompt_text must be a non-empty string",
            }
        ],
        structuredContent={},
        isError=True,
    )

    result = GhostMcpApplication._to_mcp_result(internal_result)

    assert result.isError is True
    assert result.structuredContent is None
    assert _single_text(result) == "prompt_text must be a non-empty string"


def test_runtime_exposes_exact_mcp_route_and_stateless_transport(
    runtime: GhostMcpRuntime,
) -> None:
    """The Starlette application must expose one exact /mcp route."""

    assert len(runtime.starlette_app.routes) == 1

    route = runtime.starlette_app.routes[0]
    assert isinstance(route, Route)
    assert route.path == server_module.MCP_PATH
    assert set(server_module.MCP_HTTP_METHODS).issubset(route.methods or set())
    assert route.endpoint is runtime

    assert runtime.session_manager.app is runtime.mcp_server
    assert runtime.session_manager.stateless is True
    assert runtime.session_manager.json_response is True
    assert runtime.session_manager.event_store is None


def test_environment_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GHOST_MCP_HOST", raising=False)
    monkeypatch.delenv("GHOST_MCP_PORT", raising=False)
    monkeypatch.delenv("GHOST_MCP_LOG_LEVEL", raising=False)
    monkeypatch.delenv("GHOST_MCP_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("GHOST_MCP_ALLOWED_ORIGINS", raising=False)

    assert server_module._read_host() == server_module.DEFAULT_HOST
    assert server_module._read_port() == server_module.DEFAULT_PORT
    assert (
        server_module._read_uvicorn_log_level()
        == server_module.DEFAULT_UVICORN_LOG_LEVEL
    )

    security = server_module._create_transport_security()
    assert security.enable_dns_rebinding_protection is True
    assert security.allowed_hosts == list(server_module.DEFAULT_ALLOWED_HOSTS)
    assert security.allowed_origins == list(server_module.DEFAULT_ALLOWED_ORIGINS)


def test_custom_environment_is_trimmed_and_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GHOST_MCP_HOST", " 0.0.0.0 ")
    monkeypatch.setenv("GHOST_MCP_PORT", "9000")
    monkeypatch.setenv("GHOST_MCP_LOG_LEVEL", " DEBUG ")
    monkeypatch.setenv(
        "GHOST_MCP_ALLOWED_HOSTS",
        " mcp.example.com, mcp.example.com:*, ,localhost ",
    )
    monkeypatch.setenv(
        "GHOST_MCP_ALLOWED_ORIGINS",
        " https://mcp.example.com, http://localhost:* ",
    )

    assert server_module._read_host() == "0.0.0.0"
    assert server_module._read_port() == 9000
    assert server_module._read_uvicorn_log_level() == "debug"

    security = server_module._create_transport_security()
    assert security.allowed_hosts == [
        "mcp.example.com",
        "mcp.example.com:*",
        "localhost",
    ]
    assert security.allowed_origins == [
        "https://mcp.example.com",
        "http://localhost:*",
    ]


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_host_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("GHOST_MCP_HOST", value)

    with pytest.raises(ValueError, match="GHOST_MCP_HOST must not be empty"):
        server_module._read_host()


@pytest.mark.parametrize("value", ["not-a-number", "1.5"])
def test_non_integer_port_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("GHOST_MCP_PORT", value)

    with pytest.raises(ValueError, match="GHOST_MCP_PORT must be an integer"):
        server_module._read_port()


@pytest.mark.parametrize("value", ["0", "-1", "65536"])
def test_out_of_range_port_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("GHOST_MCP_PORT", value)

    with pytest.raises(
        ValueError,
        match="GHOST_MCP_PORT must be between 1 and 65535",
    ):
        server_module._read_port()


def test_unsupported_uvicorn_log_level_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GHOST_MCP_LOG_LEVEL", "verbose")

    with pytest.raises(
        ValueError,
        match="GHOST_MCP_LOG_LEVEL has an unsupported value",
    ):
        server_module._read_uvicorn_log_level()


def test_empty_allowed_hosts_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GHOST_MCP_ALLOWED_HOSTS", " , , ")

    with pytest.raises(
        ValueError,
        match="GHOST_MCP_ALLOWED_HOSTS must not be empty",
    ):
        server_module._create_transport_security()