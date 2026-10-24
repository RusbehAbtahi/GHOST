"""Run the GHOST MCP runtime over Streamable HTTP.

The runtime supports two deployment modes:
- cognito: authenticated AWS/public deployment
- local: unauthenticated loopback-only deployment for OpenAI Secure MCP Tunnel

MCP transport and protocol negotiation are provided by mcp>=2,<3, including
both legacy initialize handshakes and MCP 2026-07-28 server/discover.
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
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.transport_security import TransportSecuritySettings
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
SERVER_VERSION = "0.5.0"

MCP_PATH = "/mcp"
OAUTH_METADATA_PATH = "/.well-known/oauth-protected-resource/mcp"
AUTHENTICATED_SUBJECT_SCOPE_KEY = "ghost.authenticated_subject"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_UVICORN_LOG_LEVEL = "info"
DEFAULT_AUTH_MODE = "cognito"

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

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
    "[::1]",
    "[::1]:*",
)

DEFAULT_ALLOWED_ORIGINS = (
    "https://ghost.rusbehabtahi.com",
    "http://127.0.0.1:*",
    "http://localhost:*",
    "http://[::1]:*",
)

_AUTHENTICATED_SUBJECT: ContextVar[str | None] = ContextVar(
    "ghost_mcp_authenticated_subject",
    default=None,
)


class GhostMcpRuntime:
    """Connect GHOST tools, MCP v2 transport, and optional Cognito auth."""

    def __init__(
        self,
        ghost_application: GhostMcpApplication,
        transport_security: TransportSecuritySettings,
        token_verifier: CognitoTokenVerifier | None = None,
        auth_config: AuthConfig | None = None,
        rate_limiter: InMemoryRateLimiter | None = None,
    ) -> None:
        self.ghost_application = ghost_application
        self.token_verifier = token_verifier
        self.auth_config = auth_config
        self.rate_limiter = rate_limiter

        resource_metadata_override = os.getenv(
            "GHOST_MCP_RESOURCE_METADATA_URL",
            "",
        ).strip()
        self.resource_metadata_url = (
            resource_metadata_override
            or (
                self._build_resource_metadata_url(auth_config.resource)
                if auth_config is not None
                else None
            )
        )

        self.mcp_server = Server(
            name=SERVER_NAME,
            version=SERVER_VERSION,
            instructions=SERVER_INSTRUCTIONS,
            lifespan=self.lifespan,
            on_list_tools=self.handle_list_tools,
            on_call_tool=self.handle_call_tool_request,
        )

        custom_routes: list[Route] = []
        if self.auth_config is not None:
            custom_routes.append(
                Route(
                    OAUTH_METADATA_PATH,
                    endpoint=self.handle_protected_resource_metadata,
                    methods=["GET"],
                )
            )

        self._mcp_http_app = self.mcp_server.streamable_http_app(
            streamable_http_path=MCP_PATH,
            json_response=False,
            stateless_http=False,
            transport_security=transport_security,
            custom_starlette_routes=custom_routes,
        )

        # Uvicorn runs this wrapper. Lifespan traffic is forwarded unchanged to
        # the MCP SDK Starlette app, so its session manager starts normally.
        self.starlette_app = self

    async def handle_protected_resource_metadata(
        self,
        _request: Any,
    ) -> JSONResponse:
        """Publish OAuth Protected Resource metadata in Cognito mode."""
        assert self.auth_config is not None
        return JSONResponse(
            {
                "resource": self.auth_config.resource,
                "authorization_servers": [
    os.getenv(
        "GHOST_MCP_AUTHORIZATION_SERVER_URL",
        self.auth_config.issuer,
    ).strip()
],
                "scopes_supported": [self.auth_config.required_scope],
            },
            headers={"Cache-Control": "no-store"},
        )

    async def handle_list_tools(
        self,
        _context: ServerRequestContext[Any],
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        """Return all GHOST tool definitions."""
        return types.ListToolsResult(
            tools=self.ghost_application.list_tools()
        )

    async def handle_call_tool_request(
        self,
        context: ServerRequestContext[Any],
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        """Rate-limit authenticated callers and execute one tool call."""
        arguments = dict(params.arguments or {})
        subject = _AUTHENTICATED_SUBJECT.get()

        request = context.request
        if request is not None:
            try:
                subject = request.scope.get(
                    AUTHENTICATED_SUBJECT_SCOPE_KEY,
                    subject,
                )
            except AttributeError:
                pass

        print(
            "[GHOST MCP CALL]"
            f" pid={os.getpid()}"
            f" tool={params.name!r}"
            f" keys={sorted(arguments)}"
            f" subject={subject!r}",
            flush=True,
        )

        rate_limit_applies = (
            self.rate_limiter is not None
            and subject is not None
            and params.name in GHOST_TOOL_NAMES
        )
        if rate_limit_applies:
            decision = self.rate_limiter.check(subject)
            if not decision.allowed:
                retry_after = max(
                    1,
                    ceil(decision.retry_after_seconds),
                )
                return types.CallToolResult(
                    content=[
                        types.TextContent(
                            type="text",
                            text=(
                                "Rate limit exceeded; retry after "
                                f"{retry_after} seconds"
                            ),
                        )
                    ],
                    is_error=True,
                )

        result = await anyio.to_thread.run_sync(
            self.ghost_application.call_tool,
            params.name,
            arguments,
            subject,
        )

        structured_content = result.structured_content or {}
        print(
            "[GHOST MCP RESULT]"
            f" tool={params.name!r}"
            f" status={structured_content.get('status')!r}"
            f" mode={structured_content.get('mode')!r}"
            f" is_error={bool(result.is_error)}",
            flush=True,
        )
        return result

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """Apply Cognito only to /mcp, then forward to the MCP SDK app."""
        if scope.get("type") != "http" or scope.get("path") != MCP_PATH:
            await self._mcp_http_app(scope, receive, send)
            return

        if self.token_verifier is None and self.auth_config is None:
            await self._mcp_http_app(scope, receive, send)
            return

        if self.token_verifier is None or self.auth_config is None:
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
            await self._mcp_http_app(scope, receive, send)
        finally:
            scope.pop(AUTHENTICATED_SUBJECT_SCOPE_KEY, None)
            _AUTHENTICATED_SUBJECT.reset(subject_token)

    @asynccontextmanager
    async def lifespan(
        self,
        _server: Server[Any],
    ) -> AsyncIterator[dict[str, Any]]:
        """Run GHOST startup cleanup inside the MCP server lifespan."""
        await self._cleanup_expired_clipboard()
        LogNoGUI(
            "GHOST MCP runtime started.",
            "INFO",
            "INTERNAL",
        )
        try:
            yield {}
        finally:
            LogNoGUI(
                "GHOST MCP runtime stopped.",
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
    host = os.getenv("GHOST_MCP_HOST", DEFAULT_HOST).strip()
    if not host:
        raise ValueError("GHOST_MCP_HOST must not be empty")
    return host


def _read_port() -> int:
    raw_port = os.getenv("GHOST_MCP_PORT", str(DEFAULT_PORT))
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("GHOST_MCP_PORT must be an integer") from exc

    if not 1 <= port <= 65535:
        raise ValueError("GHOST_MCP_PORT must be between 1 and 65535")
    return port


def _read_uvicorn_log_level() -> str:
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
    raw_value = os.getenv(name)
    if raw_value is None:
        return list(defaults)
    return [
        value.strip()
        for value in raw_value.split(",")
        if value.strip()
    ]


def _create_rate_limiter() -> InMemoryRateLimiter:
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


def _read_auth_mode(host: str) -> str:
    auth_mode = os.getenv(
        "GHOST_MCP_AUTH_MODE",
        DEFAULT_AUTH_MODE,
    ).strip().lower()

    if auth_mode not in {"cognito", "local"}:
        raise ValueError(
            "GHOST_MCP_AUTH_MODE must be either 'cognito' or 'local'"
        )
    if auth_mode == "local" and host not in LOOPBACK_HOSTS:
        raise ValueError(
            "GHOST MCP local auth mode may only bind to a loopback host"
        )
    return auth_mode


def main() -> None:
    """Create the configured GHOST MCP server and start Uvicorn."""
    host = _read_host()
    auth_mode = _read_auth_mode(host)

    if auth_mode == "cognito":
        auth_config = AuthConfig.from_environment()
        token_verifier = CognitoTokenVerifier(auth_config)
        rate_limiter = _create_rate_limiter()
        required_scope: str | None = auth_config.required_scope
    else:
        auth_config = None
        token_verifier = None
        rate_limiter = None
        required_scope = None

    print(
        "[GHOST MCP START]"
        f" pid={os.getpid()}"
        f" server_file={os.path.realpath(__file__)}"
        f" version={SERVER_VERSION}"
        f" auth_mode={auth_mode!r}"
        f" tools={sorted(GHOST_TOOL_NAMES)}",
        flush=True,
    )

    ghost_application = GhostMcpApplication(
        required_scope=required_scope
    )
    mcp_runtime = GhostMcpRuntime(
        ghost_application=ghost_application,
        transport_security=_create_transport_security(),
        token_verifier=token_verifier,
        auth_config=auth_config,
        rate_limiter=rate_limiter,
    )

    uvicorn_config = uvicorn.Config(
        app=mcp_runtime.starlette_app,
        host=host,
        port=_read_port(),
        log_level=_read_uvicorn_log_level(),
    )
    uvicorn.Server(uvicorn_config).run()


if __name__ == "__main__":  # pragma: no cover
    main()
