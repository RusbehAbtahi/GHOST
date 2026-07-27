"""GHOST MCP server using Streamable HTTP.

The server exposes the existing GHOST prompt-engineering tool. OAuth provider
configuration is intentionally not invented here and must be added through the
deployment-specific authentication layer.

Requires mcp>=1.27,<2.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import anyio
import mcp.types as types
import uvicorn
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import McpError
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from ragstream.mcp.ghost_engineer_prompt import (
    GhostEngineerPromptTool,
    GhostToolResult,
    TOOL_NAME,
    tool_metadata,
)
from ragstream.mcp.prompt_engineering_runner import PromptEngineeringRunner
from ragstream.textforge.RagLog import LogNoGUI


SERVER_NAME = "GHOST"
SERVER_VERSION = "0.1.0"

SERVER_INSTRUCTIONS = (
    "GHOST exposes one prompt-engineering tool. The tool runs PreProcessing "
    "and A2 PromptShaper, returns the engineered prompt, and does not answer "
    "the original user request."
)

MCP_PATH = "/mcp"
MCP_HTTP_METHODS = ("GET", "POST", "DELETE")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_UVICORN_LOG_LEVEL = "info"

ALLOWED_UVICORN_LOG_LEVELS = {
    "critical",
    "error",
    "warning",
    "info",
    "debug",
    "trace",
}

DEFAULT_ALLOWED_HOSTS = (
    "ragstream.rusbehabtahi.com",
    "ragstream.rusbehabtahi.com:*",
    "127.0.0.1",
    "127.0.0.1:*",
    "localhost",
    "localhost:*",
)

DEFAULT_ALLOWED_ORIGINS = (
    "https://ragstream.rusbehabtahi.com",
    "http://127.0.0.1:*",
    "http://localhost:*",
)


class GhostMcpApplication:
    """Own the GHOST tool and convert its result to the MCP contract."""

    def __init__(
        self,
        tool: GhostEngineerPromptTool | None = None,
    ) -> None:
        """Create the production tool or accept an injected tool for tests."""
        if tool is None:
            prompt_runner = PromptEngineeringRunner()
            tool = GhostEngineerPromptTool(prompt_runner)

        self.tool = tool

    def list_tools(self) -> list[types.Tool]:
        """Return the single tool definition advertised to MCP clients."""
        definition = tool_metadata()

        # A2 communicates with the external OpenAI service.
        definition["annotations"]["openWorldHint"] = True

        return [
            types.Tool.model_validate(definition)
        ]

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None,
    ) -> types.CallToolResult:
        """Execute the requested tool and return a complete MCP result."""
        if name != TOOL_NAME:
            raise McpError(
                types.ErrorData(
                    code=types.INVALID_PARAMS,
                    message=f"Unknown tool: {name}",
                )
            )

        internal_result = self.tool.call_sanitized(
            arguments
        )

        return self._to_mcp_result(
            internal_result
        )

    @classmethod
    def _to_mcp_result(
        cls,
        result: GhostToolResult,
    ) -> types.CallToolResult:
        """Validate and convert one internal GHOST result to MCP."""
        text = cls._single_text(
            result.content
        )

        if result.isError:
            return cls._error_result(
                text or "GHOST prompt engineering failed"
            )

        structured_content = result.structuredContent

        engineered_prompt = structured_content.get(
            "engineered_prompt"
        )

        valid_result = (
            text is not None
            and isinstance(engineered_prompt, str)
            and bool(engineered_prompt.strip())
            and text == engineered_prompt
            and structured_content.get("stage") == "a2"
            and set(structured_content)
            == {
                "engineered_prompt",
                "stage",
            }
        )

        if not valid_result:
            LogNoGUI(
                "GHOST MCP rejected an invalid internal tool result.",
                "ERROR",
                "INTERNAL",
            )

            return cls._error_result(
                "GHOST returned an invalid tool result"
            )

        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=engineered_prompt,
                )
            ],
            structuredContent={
                "engineered_prompt": engineered_prompt,
                "stage": "a2",
            },
            isError=False,
        )

    @staticmethod
    def _single_text(
        content: object,
    ) -> str | None:
        """Return text only when content contains one exact text item."""
        if not isinstance(content, list):
            return None

        if len(content) != 1:
            return None

        item = content[0]

        if not isinstance(item, Mapping):
            return None

        text = item.get("text")

        valid_item = (
            set(item)
            == {
                "type",
                "text",
            }
            and item.get("type") == "text"
            and isinstance(text, str)
        )

        return text if valid_item else None

    @staticmethod
    def _error_result(
        message: str,
    ) -> types.CallToolResult:
        """Create one sanitized MCP tool-error response."""
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=message,
                )
            ],
            isError=True,
        )


class GhostMcpRuntime:
    """Connect GHOST to MCP, Streamable HTTP, and Starlette.

    One runtime object contains:

    - mcp_server:
      Interprets MCP methods such as tools/list and tools/call.

    - session_manager:
      Carries MCP messages through Streamable HTTP.

    - starlette_app:
      Exposes /mcp and manages the transport lifetime.
    """

    def __init__(
        self,
        ghost_application: GhostMcpApplication,
        transport_security: TransportSecuritySettings,
    ) -> None:
        """Create and connect the three runtime infrastructure objects."""
        # Application object reached when MCP dispatches a tool call.
        self.ghost_application = ghost_application

        # MCP protocol server that interprets MCP requests.
        self.mcp_server = Server(
            name=SERVER_NAME,
            version=SERVER_VERSION,
            instructions=SERVER_INSTRUCTIONS,
        )

        register_list_tools = (
            self.mcp_server.list_tools()
        )

        register_list_tools(
            self.handle_list_tools
        )

        # Registered directly because the SDK call_tool decorator converts
        # exceptions into isError tool results. Direct registration allows an
        # McpError for an unknown tool to remain a JSON-RPC protocol error.
        self.mcp_server.request_handlers[
            types.CallToolRequest
        ] = self.handle_call_tool_request

        # Each request receives a fresh transport.
        # No session state or event-resume storage is required.
        self.session_manager = (
            StreamableHTTPSessionManager(
                app=self.mcp_server,
                event_store=None,
                json_response=True,
                stateless=True,
                security_settings=transport_security,
            )
        )

        # This route maps the exact /mcp address to this runtime object.
        mcp_route = Route(
            MCP_PATH,
            endpoint=self,
            methods=MCP_HTTP_METHODS,
        )

        # Starlette performs HTTP routing and controls transport lifetime.
        self.starlette_app = Starlette(
            debug=False,
            routes=[
                mcp_route,
            ],
            lifespan=self.lifespan,
        )

    async def handle_list_tools(
        self,
    ) -> list[types.Tool]:
        """Return the tool definitions requested through tools/list."""
        return self.ghost_application.list_tools()

    async def handle_call_tool_request(
        self,
        request: types.CallToolRequest,
    ) -> types.ServerResult:
        """Execute tools/call and preserve protocol-level MCP errors."""
        # The GHOST workflow is synchronous.
        # A worker thread keeps the asynchronous HTTP server responsive.
        result = await anyio.to_thread.run_sync(
            self.ghost_application.call_tool,
            request.params.name,
            request.params.arguments,
        )

        return types.ServerResult(
            result
        )

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """Forward one Starlette /mcp request to the MCP HTTP transport."""
        await self.session_manager.handle_request(
            scope,
            receive,
            send,
        )

    @asynccontextmanager
    async def lifespan(
        self,
        _application: Starlette,
    ) -> AsyncIterator[None]:
        """Keep the session manager active for Starlette's full lifetime."""
        async with self.session_manager.run():
            LogNoGUI(
                "GHOST MCP session manager started.",
                "INFO",
                "INTERNAL",
            )

            try:
                yield
            finally:
                LogNoGUI(
                    "GHOST MCP session manager stopped.",
                    "INFO",
                    "INTERNAL",
                )


def _read_host() -> str:
    """Read and validate the network address used by Uvicorn."""
    host = os.getenv(
        "GHOST_MCP_HOST",
        DEFAULT_HOST,
    ).strip()

    if not host:
        raise ValueError(
            "GHOST_MCP_HOST must not be empty"
        )

    return host


def _read_port() -> int:
    """Read and validate the TCP port opened by Uvicorn."""
    raw_port = os.getenv(
        "GHOST_MCP_PORT",
        str(DEFAULT_PORT),
    )

    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError(
            "GHOST_MCP_PORT must be an integer"
        ) from exc

    if not 1 <= port <= 65535:
        raise ValueError(
            "GHOST_MCP_PORT must be between 1 and 65535"
        )

    return port


def _read_uvicorn_log_level() -> str:
    """Read and validate Uvicorn's own server log level."""
    log_level = os.getenv(
        "GHOST_MCP_LOG_LEVEL",
        DEFAULT_UVICORN_LOG_LEVEL,
    ).strip().lower()

    if log_level not in ALLOWED_UVICORN_LOG_LEVELS:
        raise ValueError(
            "GHOST_MCP_LOG_LEVEL has an unsupported value"
        )

    return log_level


def _read_csv_values(
    name: str,
    defaults: tuple[str, ...],
) -> list[str]:
    """Read one comma-separated environment variable as clean values."""
    raw_value = os.getenv(name)

    if raw_value is None:
        return list(defaults)

    return [
        value.strip()
        for value in raw_value.split(",")
        if value.strip()
    ]


def _create_transport_security() -> TransportSecuritySettings:
    """Create Host and Origin validation for the public MCP endpoint."""
    allowed_hosts = _read_csv_values(
        "GHOST_MCP_ALLOWED_HOSTS",
        DEFAULT_ALLOWED_HOSTS,
    )

    if not allowed_hosts:
        raise ValueError(
            "GHOST_MCP_ALLOWED_HOSTS must not be empty"
        )

    allowed_origins = _read_csv_values(
        "GHOST_MCP_ALLOWED_ORIGINS",
        DEFAULT_ALLOWED_ORIGINS,
    )

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


def main() -> None:
    """Create the GHOST MCP object graph and start the web server."""
    host = _read_host()
    port = _read_port()
    uvicorn_log_level = _read_uvicorn_log_level()
    transport_security = _create_transport_security()

    # Owns the GHOST prompt-engineering tool and MCP result contract.
    ghost_application = GhostMcpApplication()

    # Contains mcp_server, session_manager, and starlette_app.
    mcp_runtime = GhostMcpRuntime(
        ghost_application,
        transport_security,
    )

    # Starlette is the web application Uvicorn executes.
    starlette_application = (
        mcp_runtime.starlette_app
    )

    # Stores the network settings and Starlette application.
    uvicorn_config = uvicorn.Config(
        app=starlette_application,
        host=host,
        port=port,
        log_level=uvicorn_log_level,
    )

    # Opens the TCP port and runs the asynchronous web server.
    uvicorn_server = uvicorn.Server(
        uvicorn_config
    )

    uvicorn_server.run()


if __name__ == "__main__":  # pragma: no cover
    main()