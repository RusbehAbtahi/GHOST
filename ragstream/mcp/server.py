"""Run the authenticated GHOST MCP runtime over Streamable HTTP.

The server owns the MCP/HTTP runtime boundary: OAuth Protected Resource
Metadata, Amazon Cognito authentication, authenticated request context, rate
limiting, Streamable HTTP, Starlette routing, and Uvicorn startup. Tool creation,
metadata, dispatch, and tool-result conversion live in ghost_mcp_app.py.

Main classes:
    GhostMcpRuntime:
        Connects authentication, MCP, Streamable HTTP, and Starlette.

Main functions:
    main():
        Builds the authenticated runtime and starts Uvicorn.

Important notes:
    All advertised GHOST tools are rate-limited by authenticated Cognito subject.
    Multi-call Recall progression is communicated by structured workflow state.
    Requires mcp>=1.27,<2 and PyJWT[crypto]>=2.10,<3.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from math import ceil
from typing import Any
from urllib.parse import urlsplit

import anyio
import mcp.types as types
import uvicorn
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
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
from ragstream.mcp.ghost_mcp_app import (
    GHOST_TOOL_NAMES,
    SERVER_INSTRUCTIONS,
    GhostMcpApplication,
)
from ragstream.mcp.rate_limiter import InMemoryRateLimiter
from ragstream.textforge.RagLog import LogNoGUI


SERVER_NAME = "GHOST"
SERVER_VERSION = "0.4.0"

MCP_PATH = "/mcp"
OAUTH_METADATA_PATH = "/.well-known/oauth-protected-resource/mcp"
MCP_HTTP_METHODS = ("GET", "POST", "DELETE")
AUTHENTICATED_SUBJECT_SCOPE_KEY = "ghost.authenticated_subject"

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
    "ghost.rusbehabtahi.com",
    "ghost.rusbehabtahi.com:*",
    "127.0.0.1",
    "127.0.0.1:*",
    "localhost",
    "localhost:*",
)

DEFAULT_ALLOWED_ORIGINS = (
    "https://ghost.rusbehabtahi.com",
    "http://127.0.0.1:*",
    "http://localhost:*",
)

_AUTHENTICATED_SUBJECT: ContextVar[str | None] = ContextVar(
    "ghost_mcp_authenticated_subject",
    default=None,
)


class GhostMcpRuntime:
    """Connect Cognito authentication, MCP, Streamable HTTP, and Starlette."""

    def __init__(
        self,
        ghost_application: GhostMcpApplication,
        transport_security: TransportSecuritySettings,
        token_verifier: CognitoTokenVerifier | None = None,
        auth_config: AuthConfig | None = None,
        rate_limiter: InMemoryRateLimiter | None = None,
    ) -> None:
        """Create and connect the runtime infrastructure objects."""
        self.ghost_application = ghost_application
        self.token_verifier = token_verifier
        self.auth_config = auth_config
        self.rate_limiter = rate_limiter
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
        self.mcp_server.request_handlers[types.CallToolRequest] = (
            self.handle_call_tool_request
        )

        self.session_manager = StreamableHTTPSessionManager(
            app=self.mcp_server,
            event_store=None,
            json_response=False,
            stateless=False,
            security_settings=transport_security,
        )

        routes = [Route(MCP_PATH, endpoint=self, methods=MCP_HTTP_METHODS)]
        if self.auth_config is not None:
            routes.insert(
                0,
                Route(
                    OAUTH_METADATA_PATH,
                    self.handle_protected_resource_metadata,
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
        """Rate-limit and execute one authenticated tools/call request."""
        arguments = dict(request.params.arguments or {})
        subject = _AUTHENTICATED_SUBJECT.get()

        try:
            request_context = self.mcp_server.request_context
        except LookupError:
            request_context = None

        if request_context is not None:
            try:
                subject = request_context.request.scope.get(
                    AUTHENTICATED_SUBJECT_SCOPE_KEY,
                    subject,
                )
            except AttributeError:
                pass

        print(
            "[GHOST MCP CALL]"
            f" pid={os.getpid()}"
            f" tool={request.params.name!r}"
            f" keys={sorted(arguments)}"
            f" subject={subject!r}",
            flush=True,
        )

        rate_limit_applies = (
            self.rate_limiter is not None
            and subject is not None
            and request.params.name in GHOST_TOOL_NAMES
        )
        if rate_limit_applies:
            decision = self.rate_limiter.check(subject)
            if not decision.allowed:
                retry_after = max(
                    1,
                    ceil(decision.retry_after_seconds),
                )
                print(
                    "[GHOST MCP RATE LIMIT]"
                    f" subject={subject!r}"
                    f" retry_after_seconds={retry_after}",
                    flush=True,
                )
                result = types.CallToolResult(
                    content=[
                        types.TextContent(
                            type="text",
                            text=(
                                "Rate limit exceeded; retry after "
                                f"{retry_after} seconds"
                            ),
                        )
                    ],
                    isError=True,
                )
                return types.ServerResult(result)

        result = await anyio.to_thread.run_sync(
            self.ghost_application.call_tool,
            request.params.name,
            arguments,
            subject,
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
            principal = authenticate_request(
                authorization_header,
                self.token_verifier,
            )
        except AuthenticationError:
            LogNoGUI(
                "GHOST MCP rejected an unauthenticated request.",
                "WARN",
                "INTERNAL",
            )
            challenge_error = (
                "invalid_token"
                if authorization_header is not None
                else None
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

        subject_token = _AUTHENTICATED_SUBJECT.set(principal.subject)
        scope[AUTHENTICATED_SUBJECT_SCOPE_KEY] = principal.subject

        try:
            await self.session_manager.handle_request(
                scope,
                receive,
                send,
            )
        finally:
            scope.pop(AUTHENTICATED_SUBJECT_SCOPE_KEY, None)
            _AUTHENTICATED_SUBJECT.reset(subject_token)

    @asynccontextmanager
    async def lifespan(
        self,
        _application: Starlette,
    ) -> AsyncIterator[None]:
        """Start transport and schedule Clipboard expiration cleanup."""
        async with self.session_manager.run():
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(
                    self._cleanup_expired_clipboard
                )

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

    async def _cleanup_expired_clipboard(self) -> None:
        """Run physical Clipboard cleanup outside the event loop."""
        try:
            result = await anyio.to_thread.run_sync(
                self.ghost_application.cleanup_expired_clipboard
            )
        except Exception:  # noqa: BLE001
            LogNoGUI(
                "GHOST Clipboard startup cleanup failed.",
                "WARN",
                "INTERNAL",
            )
            return

        LogNoGUI(
            "GHOST Clipboard startup cleanup completed: "
            f"deleted_files={result['deleted_file_count']}, "
            f"deleted_records={result['deleted_record_count']}, "
            f"failed_files={len(result['failed_file_ids'])}.",
            "INFO",
            "INTERNAL",
        )

    def _authorization_challenge(
        self,
        *,
        error: str | None = None,
    ) -> str:
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
    def _build_resource_metadata_url(
        resource: str,
    ) -> str:
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
        raise ValueError(
            "GHOST_MCP_LOG_LEVEL has an unsupported value"
        )

    return log_level


def _read_csv_values(
    name: str,
    defaults: tuple[str, ...],
) -> list[str]:
    """Read one comma-separated environment variable."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return list(defaults)

    return [
        value.strip()
        for value in raw_value.split(",")
        if value.strip()
    ]


def _create_rate_limiter() -> InMemoryRateLimiter:
    """Create the authenticated tool-call limiter from deployment settings."""
    try:
        limit = int(os.environ["GHOST_MCP_RATE_LIMIT"])
        window_seconds = float(
            os.environ["GHOST_MCP_RATE_LIMIT_WINDOW_SECONDS"]
        )
    except KeyError as exc:
        raise ValueError(
            f"missing rate-limit setting: {exc.args[0]}"
        ) from exc
    except ValueError as exc:
        raise ValueError(
            "GHOST MCP rate-limit settings must be numeric"
        ) from exc

    return InMemoryRateLimiter(
        limit=limit,
        window_seconds=window_seconds,
    )


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

    print(
        "[GHOST MCP START]"
        f" pid={os.getpid()}"
        f" server_file={os.path.realpath(__file__)}"
        f" version={SERVER_VERSION}"
        f" tools={sorted(GHOST_TOOL_NAMES)}",
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
        rate_limiter=_create_rate_limiter(),
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