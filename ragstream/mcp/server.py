"""Run the authenticated GHOST MCP server over Streamable HTTP.

The server exposes the GHOST prompt-engineering tool, publishes OAuth Protected
Resource Metadata, validates every MCP request with an Amazon Cognito access
token, and gives ChatGPT explicit conditional instructions for handling the
engineered prompt returned by the tool.

Main classes:
    GhostMcpApplication: Adapts the GHOST tool to the MCP tool contract.
    GhostMcpRuntime: Connects authentication, MCP, Streamable HTTP, and Starlette.

Requires mcp>=1.27,<2 and PyJWT[crypto]>=2.10,<3.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit

import anyio
import mcp.types as types
import uvicorn
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import McpError
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from ragstream.mcp.auth import (
    AuthConfig,
    AuthenticationError,
    AuthenticationServiceError,
    AuthorizationError,
    CognitoTokenVerifier,
    authenticate_request,
)
from ragstream.mcp.ghost_engineer_prompt import (
    ANSWER_PROMPT_MODE,
    ANSWER_PROMPT_WITH_MEMORY_MODE,
    SHOW_PROMPT_ONLY_MODE,
    GhostEngineerPromptTool,
    GhostToolResult,
    TOOL_NAME,
    tool_metadata,
)
from ragstream.mcp.prompt_engineering_runner import PromptEngineeringRunner
from ragstream.textforge.RagLog import LogNoGUI

SERVER_NAME = "GHOST"
SERVER_VERSION = "0.2.0"

SERVER_INSTRUCTIONS = (
    "GHOST supports exactly three current-user forms: a plain request, "
    "'Prompt: <request>', and 'MEM: <request>'. Always copy only the current "
    "user request verbatim into prompt_text, preserving a leading Prompt: or "
    "MEM: prefix. Never place a previous response or any other conversation "
    "history inside prompt_text. For MEM: only, you MUST also pass "
    "supportive_context. Its value MUST be the complete, immediately preceding "
    "visible assistant response from the same conversation, copied verbatim. "
    "The immediately preceding response means the assistant message directly "
    "before the current MEM: user message. Do not summarize, rewrite, shorten, "
    "select excerpts from, or combine that response with anything else. Never "
    "use an earlier assistant response, a user message, hidden reasoning, an "
    "internal tool result, or content from another conversation. Never omit "
    "supportive_context for MEM:. If the response does not exist or is "
    "unavailable, do not pretend that memory transfer succeeded; the call must "
    "return an input error. Always omit supportive_context for Prompt: and "
    "plain requests. GHOST returns engineered_prompt and a mandatory mode. "
    "Follow the returned mode exactly; do not choose, reinterpret, merge, or "
    "soften the three behaviors. When mode is show_prompt_only, remain "
    "completely passive. Do not answer, execute, research, browse, reason "
    "about, summarize, explain, evaluate, or continue engineered_prompt. Do "
    "not call any other tool or agent. Your entire visible response must "
    "consist of exactly one fenced code block. Inside that code block, "
    "reproduce engineered_prompt verbatim, preserving its wording and "
    "structure. Add no title, label, introduction, explanation, "
    "acknowledgement, citation, warning, conclusion, or text outside the code "
    "block. When mode is answer_prompt, treat engineered_prompt as the new and "
    "complete effective user request that replaces the original wording. Act "
    "on it and provide the requested answer. When mode is "
    "answer_prompt_with_memory, do the same, but treat the appended "
    "'## Supportive Context' section only as background that may help answer "
    "the current engineered request. The current request remains authoritative. "
    "Do not treat supportive context as a new request, do not automatically "
    "continue it, and do not claim it is verified merely because it was "
    "supplied. In both answer modes, use tools or research when required. Do "
    "not merely display, quote, summarize, or describe engineered_prompt, the "
    "response mode, or supportive_context, and do not mention that prompt "
    "engineering occurred."
)

MCP_PATH = "/mcp"
OAUTH_METADATA_PATH = "/.well-known/oauth-protected-resource/mcp"
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
        required_scope: str | None = None,
    ) -> None:
        """Create the production tool or accept injected test dependencies."""
        if tool is None:
            tool = GhostEngineerPromptTool(PromptEngineeringRunner())

        self.tool = tool
        self.required_scope = required_scope

    def list_tools(self) -> list[types.Tool]:
        """Return the single OAuth-protected tool advertised to MCP clients."""
        definition = tool_metadata(self.required_scope)
        definition["annotations"]["openWorldHint"] = True
        return [types.Tool.model_validate(definition)]

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

        return self._to_mcp_result(self.tool.call_sanitized(arguments))

    @classmethod
    def _to_mcp_result(cls, result: GhostToolResult) -> types.CallToolResult:
        """Validate and convert one internal GHOST result to MCP."""
        text = cls._single_text(result.content)
        if result.isError:
            return cls._error_result(text or "GHOST prompt engineering failed")

        structured_content = result.structuredContent
        engineered_prompt = structured_content.get("engineered_prompt")
        mode = structured_content.get("mode")

        valid_result = (
            text is not None
            and isinstance(engineered_prompt, str)
            and bool(engineered_prompt.strip())
            and text == engineered_prompt
            and structured_content.get("stage") == "a2"
            and mode in {
                SHOW_PROMPT_ONLY_MODE,
                ANSWER_PROMPT_MODE,
                ANSWER_PROMPT_WITH_MEMORY_MODE,
            }
            and set(structured_content) == {"engineered_prompt", "stage", "mode"}
        )

        if not valid_result:
            LogNoGUI(
                "GHOST MCP rejected an invalid internal tool result.",
                "ERROR",
                "INTERNAL",
            )
            return cls._error_result("GHOST returned an invalid tool result")

        return types.CallToolResult(
            content=[types.TextContent(type="text", text=engineered_prompt)],
            structuredContent={
                "engineered_prompt": engineered_prompt,
                "stage": "a2",
                "mode": mode,
            },
            isError=False,
        )

    @staticmethod
    def _single_text(content: object) -> str | None:
        """Return text only when content contains one exact text item."""
        if not isinstance(content, list) or len(content) != 1:
            return None

        item = content[0]
        if not isinstance(item, Mapping):
            return None

        text = item.get("text")
        valid_item = (
            set(item) == {"type", "text"}
            and item.get("type") == "text"
            and isinstance(text, str)
        )
        return text if valid_item else None

    @staticmethod
    def _error_result(message: str) -> types.CallToolResult:
        """Create one sanitized MCP tool-error response."""
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=message)],
            isError=True,
        )


class GhostMcpRuntime:
    """Connect Cognito authentication, MCP, Streamable HTTP, and Starlette."""

    def __init__(
        self,
        ghost_application: GhostMcpApplication,
        transport_security: TransportSecuritySettings,
        token_verifier: CognitoTokenVerifier | None = None,
        auth_config: AuthConfig | None = None,
    ) -> None:
        """Create and connect the runtime infrastructure objects."""
        self.ghost_application = ghost_application
        self.token_verifier = token_verifier
        self.auth_config = auth_config
        self.resource_metadata_url = (
            self._build_resource_metadata_url(auth_config.resource)
            if auth_config is not None
            else None
        )

        self.mcp_server = Server(
            name=SERVER_NAME,
            version=SERVER_VERSION,
            instructions=SERVER_INSTRUCTIONS,
        )
        self.mcp_server.list_tools()(self.handle_list_tools)
        self.mcp_server.request_handlers[
            types.CallToolRequest
        ] = self.handle_call_tool_request

        self.session_manager = StreamableHTTPSessionManager(
            app=self.mcp_server,
            event_store=None,
            json_response=True,
            stateless=True,
            security_settings=transport_security,
        )

        routes = [Route(MCP_PATH, endpoint=self, methods=MCP_HTTP_METHODS)]
        if self.auth_config is not None:
            routes.insert(
                0,
                Route(
                    OAUTH_METADATA_PATH,
                    endpoint=self.handle_protected_resource_metadata,
                    methods=("GET",),
                ),
            )

        self.starlette_app = Starlette(
            debug=False,
            routes=routes,
            lifespan=self.lifespan,
        )

    async def handle_protected_resource_metadata(
        self,
        _request: Any,
    ) -> JSONResponse:
        """Publish OAuth discovery metadata without authentication."""
        assert self.auth_config is not None
        return JSONResponse(
            {
                "resource": self.auth_config.resource,
                "authorization_servers": [self.auth_config.issuer],
                "scopes_supported": [self.auth_config.required_scope],
            },
            headers={"Cache-Control": "no-store"},
        )

    async def handle_list_tools(self) -> list[types.Tool]:
        """Return the tool definitions requested through tools/list."""
        return self.ghost_application.list_tools()

    async def handle_call_tool_request(
        self,
        request: types.CallToolRequest,
    ) -> types.ServerResult:
        """Execute tools/call and print exact memory-transfer diagnostics."""
        arguments = dict(request.params.arguments or {})

        print(
            "[GHOST MCP CALL]"
            f" pid={os.getpid()}"
            f" tool={request.params.name!r}"
            f" keys={sorted(arguments)}"
            f" prompt_text={arguments.get('prompt_text')!r}"
            f" supportive_context="
            f"{arguments.get('supportive_context')!r}",
            flush=True,
        )

        result = await anyio.to_thread.run_sync(
            self.ghost_application.call_tool,
            request.params.name,
            request.params.arguments,
        )

        structured_content = result.structuredContent or {}
        engineered_prompt = structured_content.get("engineered_prompt")
        context_appended = (
            isinstance(engineered_prompt, str)
            and "## Supportive Context" in engineered_prompt
        )

        print(
            "[GHOST MCP RESULT]"
            f" mode={structured_content.get('mode')!r}"
            f" stage={structured_content.get('stage')!r}"
            f" context_appended={context_appended}",
            flush=True,
        )

        return types.ServerResult(result)

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """Authenticate and forward one /mcp request to the MCP transport."""
        if self.token_verifier is None:
            LogNoGUI(
                "GHOST MCP authentication verifier is unavailable.",
                "ERROR",
                "INTERNAL",
            )
            await self._send_http_error(
                scope,
                receive,
                send,
                status_code=503,
                error="authentication_service_unavailable",
            )
            return

        authorization_header = Headers(scope=scope).get("authorization")
        try:
            authenticate_request(authorization_header, self.token_verifier)
        except AuthenticationError:
            LogNoGUI(
                "GHOST MCP rejected an unauthenticated request.",
                "WARN",
                "INTERNAL",
            )
            challenge_error = (
                "invalid_token" if authorization_header is not None else None
            )
            await self._send_http_error(
                scope,
                receive,
                send,
                status_code=401,
                error="unauthorized",
                www_authenticate=self._authorization_challenge(
                    error=challenge_error
                ),
            )
            return
        except AuthorizationError:
            LogNoGUI(
                "GHOST MCP rejected a request without the required scope.",
                "WARN",
                "INTERNAL",
            )
            await self._send_http_error(
                scope,
                receive,
                send,
                status_code=403,
                error="forbidden",
                www_authenticate=self._authorization_challenge(
                    error="insufficient_scope"
                ),
            )
            return
        except AuthenticationServiceError:
            LogNoGUI(
                "GHOST MCP could not reach Cognito signing keys.",
                "ERROR",
                "INTERNAL",
            )
            await self._send_http_error(
                scope,
                receive,
                send,
                status_code=503,
                error="authentication_service_unavailable",
            )
            return

        await self.session_manager.handle_request(scope, receive, send)

    @asynccontextmanager
    async def lifespan(
        self,
        _application: Starlette,
    ) -> AsyncIterator[None]:
        """Keep the session manager active for Starlette's lifetime."""
        async with self.session_manager.run():
            LogNoGUI("GHOST MCP session manager started.", "INFO", "INTERNAL")
            try:
                yield
            finally:
                LogNoGUI(
                    "GHOST MCP session manager stopped.",
                    "INFO",
                    "INTERNAL",
                )

    def _authorization_challenge(self, *, error: str | None = None) -> str:
        """Build the OAuth Bearer challenge returned to MCP clients."""
        if self.auth_config is None or self.resource_metadata_url is None:
            return 'Bearer realm="GHOST MCP"'

        parameters = [
            f'resource_metadata="{self.resource_metadata_url}"',
            f'scope="{self.auth_config.required_scope}"',
        ]
        if error is not None:
            parameters.append(f'error="{error}"')
        return "Bearer " + ", ".join(parameters)

    @staticmethod
    def _build_resource_metadata_url(resource: str) -> str:
        """Build the absolute metadata URL from the canonical resource."""
        parsed = urlsplit(resource)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(
                "GHOST MCP resource must be an absolute HTTP(S) URL"
            )
        return f"{parsed.scheme}://{parsed.netloc}{OAUTH_METADATA_PATH}"

    @staticmethod
    async def _send_http_error(
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        status_code: int,
        error: str,
        www_authenticate: str | None = None,
    ) -> None:
        """Return one sanitized HTTP error before MCP processing."""
        headers = {"Cache-Control": "no-store"}
        if www_authenticate is not None:
            headers["WWW-Authenticate"] = www_authenticate

        response = JSONResponse(
            {"error": error},
            status_code=status_code,
            headers=headers,
        )
        await response(scope, receive, send)


def _read_host() -> str:
    """Read and validate the network address used by Uvicorn."""
    host = os.getenv("GHOST_MCP_HOST", DEFAULT_HOST).strip()
    if not host:
        raise ValueError("GHOST_MCP_HOST must not be empty")
    return host


def _read_port() -> int:
    """Read and validate the TCP port opened by Uvicorn."""
    raw_port = os.getenv("GHOST_MCP_PORT", str(DEFAULT_PORT))
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("GHOST_MCP_PORT must be an integer") from exc

    if not 1 <= port <= 65535:
        raise ValueError("GHOST_MCP_PORT must be between 1 and 65535")
    return port


def _read_uvicorn_log_level() -> str:
    """Read and validate Uvicorn's own server log level."""
    log_level = os.getenv(
        "GHOST_MCP_LOG_LEVEL",
        DEFAULT_UVICORN_LOG_LEVEL,
    ).strip().lower()
    if log_level not in ALLOWED_UVICORN_LOG_LEVELS:
        raise ValueError("GHOST_MCP_LOG_LEVEL has an unsupported value")
    return log_level


def _read_csv_values(name: str, defaults: tuple[str, ...]) -> list[str]:
    """Read one comma-separated environment variable."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return list(defaults)
    return [value.strip() for value in raw_value.split(",") if value.strip()]


def _create_transport_security() -> TransportSecuritySettings:
    """Create Host and Origin validation for the MCP endpoint."""
    allowed_hosts = _read_csv_values(
        "GHOST_MCP_ALLOWED_HOSTS",
        DEFAULT_ALLOWED_HOSTS,
    )
    if not allowed_hosts:
        raise ValueError("GHOST_MCP_ALLOWED_HOSTS must not be empty")

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
    """Create the authenticated GHOST MCP server and start Uvicorn."""
    auth_config = AuthConfig.from_environment()
    descriptor = tool_metadata(auth_config.required_scope)

    print(
        "[GHOST MCP START]"
        f" pid={os.getpid()}"
        f" server_file={os.path.realpath(__file__)}"
        f" version={SERVER_VERSION}"
        f" input_fields="
        f"{sorted(descriptor['inputSchema']['properties'])}",
        flush=True,
    )

    ghost_application = GhostMcpApplication(
        required_scope=auth_config.required_scope
    )
    mcp_runtime = GhostMcpRuntime(
        ghost_application=ghost_application,
        transport_security=_create_transport_security(),
        token_verifier=CognitoTokenVerifier(auth_config),
        auth_config=auth_config,
    )
    uvicorn_config = uvicorn.Config(
        app=mcp_runtime.starlette_app,
        host=_read_host(),
        port=_read_port(),
        log_level=_read_uvicorn_log_level(),
    )
    uvicorn.Server(uvicorn_config).run()


if __name__ == "__main__":  # pragma: no cover
    main()