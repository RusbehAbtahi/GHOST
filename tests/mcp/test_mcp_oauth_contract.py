"""Test the complete GHOST MCP OAuth discovery and tool contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mcp.server.transport_security import TransportSecuritySettings
from starlette.testclient import TestClient

from ragstream.mcp.auth import (
    AuthConfig,
    AuthenticationError,
    AuthenticationServiceError,
    AuthorizationError,
)
from ragstream.mcp.ghost_engineer_prompt import (
    GhostToolResult,
    TOOL_NAME,
    tool_metadata,
)
from ragstream.mcp.server import (
    MCP_PATH,
    OAUTH_METADATA_PATH,
    GhostMcpApplication,
    GhostMcpRuntime,
)


ISSUER = (
    "https://cognito-idp.eu-central-1.amazonaws.com/"
    "eu-central-1_O2GBcKsnT"
)

APP_CLIENT_ID = "62293lip90j4hmpqucp4gd05ma"

RESOURCE = "https://ragstream.rusbehabtahi.com/mcp"

REQUIRED_SCOPE = (
    "https://ragstream.rusbehabtahi.com/mcp/invoke"
)

RESOURCE_METADATA_URL = (
    "https://ragstream.rusbehabtahi.com"
    "/.well-known/oauth-protected-resource/mcp"
)

AUTH_CONFIG = AuthConfig(
    issuer=ISSUER,
    app_client_id=APP_CLIENT_ID,
    resource=RESOURCE,
    required_scope=REQUIRED_SCOPE,
)

MCP_HEADERS = {
    "Authorization": "Bearer valid-token",
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2025-06-18",
}


class AllowingVerifier:
    """Accept the fixed token used by authenticated tests."""

    def verify_bearer_token(
        self,
        token: str,
    ) -> object:
        assert token == "valid-token"
        return object()


class InvalidTokenVerifier:
    """Reject the supplied token as invalid."""

    def verify_bearer_token(
        self,
        _token: str,
    ) -> object:
        raise AuthenticationError(
            "invalid token"
        )


class ScopeRejectingVerifier:
    """Reject the supplied token for missing authorization scope."""

    def verify_bearer_token(
        self,
        _token: str,
    ) -> object:
        raise AuthorizationError(
            "required scope missing"
        )


class ServiceFailingVerifier:
    """Simulate unavailable Cognito signing keys."""

    def verify_bearer_token(
        self,
        _token: str,
    ) -> object:
        raise AuthenticationServiceError(
            "JWKS unavailable"
        )


class StubTool:
    """Return one deterministic valid GHOST tool result."""

    def call_sanitized(
        self,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        prompt_text = str(
            (arguments or {}).get(
                "prompt_text",
                "",
            )
        )

        engineered_prompt = (
            f"ENGINEERED: {prompt_text}"
        )

        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": engineered_prompt,
                }
            ],
            structuredContent={
                "engineered_prompt": engineered_prompt,
                "stage": "a2",
            },
            isError=False,
        )


def _build_runtime(
    token_verifier: Any,
) -> GhostMcpRuntime:
    """Create one isolated authenticated MCP runtime."""
    ghost_application = GhostMcpApplication(
        tool=StubTool(),
        required_scope=REQUIRED_SCOPE,
    )

    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    )

    return GhostMcpRuntime(
        ghost_application=ghost_application,
        transport_security=transport_security,
        token_verifier=token_verifier,
        auth_config=AUTH_CONFIG,
    )


def test_metadata_route_is_public_and_complete() -> None:
    runtime = _build_runtime(
        AllowingVerifier()
    )

    with TestClient(runtime.starlette_app) as client:
        response = client.get(
            OAUTH_METADATA_PATH
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"

    assert response.json() == {
        "resource": RESOURCE,
        "authorization_servers": [
            ISSUER,
        ],
        "scopes_supported": [
            REQUIRED_SCOPE,
        ],
    }


def test_missing_token_returns_oauth_discovery_challenge() -> None:
    runtime = _build_runtime(
        AllowingVerifier()
    )

    with TestClient(runtime.starlette_app) as client:
        response = client.get(
            MCP_PATH
        )

    assert response.status_code == 401
    assert response.json() == {
        "error": "unauthorized",
    }

    challenge = response.headers[
        "www-authenticate"
    ]

    assert challenge.startswith("Bearer ")
    assert (
        f'resource_metadata="{RESOURCE_METADATA_URL}"'
        in challenge
    )
    assert (
        f'scope="{REQUIRED_SCOPE}"'
        in challenge
    )


def test_invalid_token_returns_invalid_token_challenge() -> None:
    runtime = _build_runtime(
        InvalidTokenVerifier()
    )

    with TestClient(runtime.starlette_app) as client:
        response = client.get(
            MCP_PATH,
            headers={
                "Authorization": "Bearer invalid-token",
            },
        )

    assert response.status_code == 401

    challenge = response.headers[
        "www-authenticate"
    ]

    assert (
        f'resource_metadata="{RESOURCE_METADATA_URL}"'
        in challenge
    )
    assert 'error="invalid_token"' in challenge


def test_insufficient_scope_returns_403_challenge() -> None:
    runtime = _build_runtime(
        ScopeRejectingVerifier()
    )

    with TestClient(runtime.starlette_app) as client:
        response = client.get(
            MCP_PATH,
            headers={
                "Authorization": "Bearer valid-token",
            },
        )

    assert response.status_code == 403
    assert response.json() == {
        "error": "forbidden",
    }

    challenge = response.headers[
        "www-authenticate"
    ]

    assert (
        f'resource_metadata="{RESOURCE_METADATA_URL}"'
        in challenge
    )
    assert (
        f'scope="{REQUIRED_SCOPE}"'
        in challenge
    )
    assert (
        'error="insufficient_scope"'
        in challenge
    )


def test_authentication_service_failure_returns_503() -> None:
    runtime = _build_runtime(
        ServiceFailingVerifier()
    )

    with TestClient(runtime.starlette_app) as client:
        response = client.get(
            MCP_PATH,
            headers={
                "Authorization": "Bearer valid-token",
            },
        )

    assert response.status_code == 503
    assert response.json() == {
        "error": "authentication_service_unavailable",
    }
    assert "www-authenticate" not in response.headers


def test_tool_metadata_declares_oauth_security() -> None:
    metadata = tool_metadata(
        REQUIRED_SCOPE
    )

    expected_security_schemes = [
        {
            "type": "oauth2",
            "scopes": [
                REQUIRED_SCOPE,
            ],
        }
    ]

    assert (
        metadata["securitySchemes"]
        == expected_security_schemes
    )

    assert (
        metadata["_meta"]["securitySchemes"]
        == expected_security_schemes
    )


def test_authenticated_initialize_succeeds() -> None:
    runtime = _build_runtime(
        AllowingVerifier()
    )

    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {
                "name": "oauth-contract-test",
                "version": "1.0",
            },
        },
    }

    with TestClient(runtime.starlette_app) as client:
        response = client.post(
            MCP_PATH,
            headers=MCP_HEADERS,
            json=request,
        )

    assert response.status_code == 200

    result = response.json()["result"]

    assert result["protocolVersion"] == "2025-06-18"
    assert result["serverInfo"] == {
        "name": "GHOST",
        "version": "0.1.0",
    }


def test_tools_list_exposes_one_oauth_protected_tool() -> None:
    runtime = _build_runtime(
        AllowingVerifier()
    )

    request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {},
    }

    with TestClient(runtime.starlette_app) as client:
        response = client.post(
            MCP_PATH,
            headers=MCP_HEADERS,
            json=request,
        )

    assert response.status_code == 200

    tools = response.json()["result"]["tools"]

    assert len(tools) == 1
    assert tools[0]["name"] == TOOL_NAME

    expected_security_schemes = [
        {
            "type": "oauth2",
            "scopes": [
                REQUIRED_SCOPE,
            ],
        }
    ]

    assert (
        tools[0]["securitySchemes"]
        == expected_security_schemes
    )

    assert (
        tools[0]["_meta"]["securitySchemes"]
        == expected_security_schemes
    )


def test_authenticated_tool_call_succeeds() -> None:
    runtime = _build_runtime(
        AllowingVerifier()
    )

    request = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": TOOL_NAME,
            "arguments": {
                "prompt_text": "Explain OAuth.",
            },
        },
    }

    with TestClient(runtime.starlette_app) as client:
        response = client.post(
            MCP_PATH,
            headers=MCP_HEADERS,
            json=request,
        )

    assert response.status_code == 200

    result = response.json()["result"]

    assert result["isError"] is False

    assert result["structuredContent"] == {
        "engineered_prompt": "ENGINEERED: Explain OAuth.",
        "stage": "a2",
    }

    assert result["content"] == [
        {
            "type": "text",
            "text": "ENGINEERED: Explain OAuth.",
        }
    ]