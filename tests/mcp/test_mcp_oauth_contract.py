"""OAuth and security metadata checks for the current GHOST MCP tools."""

from __future__ import annotations

from typing import Any

from mcp.server.transport_security import TransportSecuritySettings
from starlette.testclient import TestClient

from ragstream.mcp.auth import AuthConfig, Principal
from ragstream.mcp.ghost_mcp_app import GhostMcpApplication
from ragstream.mcp.ghost_prompt_builder import STATUS_COMPLETE
from ragstream.mcp.ghost_prompt_run import TOOL_NAME as RUN_TOOL_NAME
from ragstream.mcp.ghost_prompt_settings import (
    GhostPromptSettings,
    TOOL_NAME as SETTINGS_TOOL_NAME,
)
from ragstream.mcp.ghost_prompt_show import (
    TOOL_NAME as SHOW_TOOL_NAME,
    tool_metadata as show_tool_metadata,
)
from ragstream.mcp.server import (
    MCP_PATH,
    OAUTH_METADATA_PATH,
    GhostMcpRuntime,
)


ISSUER = "https://cognito-idp.eu-central-1.amazonaws.com/pool"
APP_CLIENT_ID = "client"
RESOURCE = "https://ghost.example/mcp"
REQUIRED_SCOPE = "https://ghost.example/mcp/invoke"

AUTH_CONFIG = AuthConfig(
    issuer=ISSUER,
    app_client_id=APP_CLIENT_ID,
    resource=RESOURCE,
    required_scope=REQUIRED_SCOPE,
)


class AllowingVerifier:
    def verify_bearer_token(self, token: str) -> Principal:
        assert token == "valid-token"
        return Principal(
            subject="owner",
            issuer=ISSUER,
            client_id=APP_CLIENT_ID,
            resource=RESOURCE,
            scopes=(REQUIRED_SCOPE,),
            expires_at=2_000_000_000,
        )


class Builder:
    def build(self, **arguments: Any) -> dict[str, Any]:
        return {
            "status": STATUS_COMPLETE,
            "prompt": f"BUILT: {arguments['prompt_text']}",
            "clarification_question": "",
            "general_skill_candidates": [],
            "receipt": {"status": STATUS_COMPLETE},
        }


def build_runtime(tmp_path) -> GhostMcpRuntime:
    application = GhostMcpApplication(
        prompt_builder=Builder(),  # type: ignore[arg-type]
        prompt_settings=GhostPromptSettings(tmp_path),
        required_scope=REQUIRED_SCOPE,
    )
    return GhostMcpRuntime(
        ghost_application=application,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
        token_verifier=AllowingVerifier(),  # type: ignore[arg-type]
        auth_config=AUTH_CONFIG,
    )


def test_metadata_route_is_public_and_complete(tmp_path) -> None:
    runtime = build_runtime(tmp_path)

    with TestClient(runtime.starlette_app) as client:
        response = client.get(OAUTH_METADATA_PATH)

    assert response.status_code == 200
    assert response.json() == {
        "resource": RESOURCE,
        "authorization_servers": [ISSUER],
        "scopes_supported": [REQUIRED_SCOPE],
    }


def test_missing_token_is_rejected(tmp_path) -> None:
    runtime = build_runtime(tmp_path)

    with TestClient(runtime.starlette_app) as client:
        response = client.get(MCP_PATH)

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_prompt_tool_metadata_declares_required_scope() -> None:
    metadata = show_tool_metadata(REQUIRED_SCOPE)
    expected = [{"type": "oauth2", "scopes": [REQUIRED_SCOPE]}]

    assert metadata["securitySchemes"] == expected
    assert metadata["_meta"]["securitySchemes"] == expected


def test_all_three_prompt_tools_are_oauth_protected(tmp_path) -> None:
    application = build_runtime(tmp_path).ghost_application
    tools = {
        tool.name: tool
        for tool in application.list_tools()
        if tool.name in {
            SHOW_TOOL_NAME,
            RUN_TOOL_NAME,
            SETTINGS_TOOL_NAME,
        }
    }

    assert set(tools) == {
        SHOW_TOOL_NAME,
        RUN_TOOL_NAME,
        SETTINGS_TOOL_NAME,
    }
    for tool in tools.values():
        assert tool.securitySchemes is not None
        assert tool.securitySchemes[0]["scopes"] == [REQUIRED_SCOPE]
