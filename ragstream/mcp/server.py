"""MCP server bootstrap and tool registration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

from ragstream.mcp.auth import Principal, TokenVerifier
from ragstream.mcp.ghost_engineer_prompt import (
    GhostEngineerPromptTool,
    TOOL_DESCRIPTION,
    TOOL_NAME,
    TOOL_TITLE,
    INPUT_SCHEMA,
    OUTPUT_SCHEMA,
    tool_metadata,
)
from ragstream.mcp.prompt_engineering_runner import PromptEngineeringRunner
from ragstream.mcp.rate_limiter import InMemoryRateLimiter, RateLimitDecision


@dataclass(frozen=True)
class BoundaryResult:
    allowed: bool
    status_code: int = 200
    message: str = ""
    retry_after_seconds: float = 0.0
    principal: Principal | None = None


class McpInvocationBoundary:
    """Runs auth and rate-limit checks before GHOST processing."""

    def __init__(self, *, verifier: TokenVerifier | None = None, rate_limiter: InMemoryRateLimiter | None = None) -> None:
        self._verifier = verifier
        self._rate_limiter = rate_limiter

    def check(self, *, authorization_header: str | None = None, caller_key: str | None = None) -> BoundaryResult:
        principal: Principal | None = None
        if self._verifier is not None:
            from ragstream.mcp.auth import AuthenticationError, AuthorizationError, authenticate_request

            try:
                principal = authenticate_request(authorization_header, self._verifier)
            except AuthenticationError:
                return BoundaryResult(False, status_code=401, message="authentication required")
            except AuthorizationError:
                return BoundaryResult(False, status_code=403, message="not authorized")

        if self._rate_limiter is not None:
            key = caller_key or (principal.subject if principal else "anonymous")
            decision: RateLimitDecision = self._rate_limiter.check(key)
            if not decision.allowed:
                return BoundaryResult(
                    False,
                    status_code=429,
                    message="rate limit exceeded",
                    retry_after_seconds=decision.retry_after_seconds,
                    principal=principal,
                )
        return BoundaryResult(True, principal=principal)


class GhostMcpApplication:
    """Owns the single exported GHOST MCP tool."""

    def __init__(self, *, tool: GhostEngineerPromptTool | None = None, boundary: McpInvocationBoundary | None = None) -> None:
        self._tool = tool or GhostEngineerPromptTool(PromptEngineeringRunner())
        self._boundary = boundary or McpInvocationBoundary()

    def list_tools(self) -> list[dict[str, Any]]:
        return [tool_metadata()]

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None,
        *,
        authorization_header: str | None = None,
        caller_key: str | None = None,
    ) -> Any:
        if name != TOOL_NAME:
            return {"isError": True, "content": [{"type": "text", "text": "unknown tool"}]}
        boundary = self._boundary.check(authorization_header=authorization_header, caller_key=caller_key)
        if not boundary.allowed:
            return {"isError": True, "content": [{"type": "text", "text": boundary.message}], "status_code": boundary.status_code}
        return self._tool.call_sanitized(arguments)


def create_fastmcp_server(app: GhostMcpApplication | None = None):
    """Create the official Python MCP SDK server with one registered tool."""
    try:
        from mcp.server.fastmcp import FastMCP  # type: ignore[import]
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("The official Python MCP SDK package 'mcp' is required to run the server") from exc

    ghost_app = app or GhostMcpApplication()
    mcp = FastMCP("GHOST")

    @mcp.tool(name=TOOL_NAME, title=TOOL_TITLE, description=TOOL_DESCRIPTION)
    def ghost_engineer_prompt(prompt_text: str) -> str:
        result = ghost_app.call_tool(TOOL_NAME, {"prompt_text": prompt_text})
        if getattr(result, "isError", False):
            raise RuntimeError(result.content[0]["text"])
        return result.structuredContent["engineered_prompt"]

    return mcp


def main() -> None:
    server = create_fastmcp_server()
    transport = os.getenv("GHOST_MCP_TRANSPORT", "streamable-http")
    server.run(transport=transport)


if __name__ == "__main__":  # pragma: no cover
    main()
