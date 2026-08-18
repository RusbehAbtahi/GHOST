"""Unit tests for the GHOST runtime-control MCP Lambda boundary.

All AWS and Cognito interactions are replaced by deterministic test doubles.
"""

from __future__ import annotations

import json
import sys

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_CONTROL_SOURCE = REPOSITORY_ROOT / "lambda" / "runtime_control"
sys.path.insert(0, str(REPOSITORY_ROOT))
sys.path.insert(0, str(RUNTIME_CONTROL_SOURCE))

from ragstream.mcp.auth import (  # noqa: E402
    AuthConfig,
    AuthenticationError,
)
from ghost_runtime_control import mcp_server as mcp_module  # noqa: E402
from ghost_runtime_control.lambda_handler import (  # noqa: E402
    MCP_PATH,
    OAUTH_METADATA_PATH,
    RuntimeControlApplication,
)
from ghost_runtime_control.mcp_server import (  # noqa: E402
    FORBIDDEN,
    INVALID_REQUEST,
    UNAUTHENTICATED,
    McpResponse,
    RuntimeControlMcpServer,
)


OWNER_SUBJECT = "owner-subject-123"
AUTHORIZATION = "Bearer valid-test-token"


class FakeController:
    """Record runtime operations without calling AWS."""

    def __init__(self) -> None:
        self.start_calls: list[tuple[int | None, int | None]] = []
        self.status_calls = 0
        self.stop_calls = 0
        self.watchdog_calls = 0

    def start(
        self,
        runtime_profile: int | None = None,
        idle_timeout_minutes: int | None = None,
    ) -> dict[str, Any]:
        self.start_calls.append((runtime_profile, idle_timeout_minutes))
        return {
            "ec2_state": "running",
            "runtime_profile": runtime_profile or 1,
            "ghost_ready": True,
            "effective_idle_timeout_minutes": idle_timeout_minutes or 20,
        }

    def status(self) -> dict[str, Any]:
        self.status_calls += 1
        return {
            "ec2_state": "running",
            "runtime_profile": 1,
            "ghost_ready": True,
        }

    def stop(self) -> dict[str, Any]:
        self.stop_calls += 1
        return {"ec2_state": "stopping", "changed": True}

    def stop_if_idle(self) -> dict[str, Any]:
        self.watchdog_calls += 1
        return {"stopped": False, "reason": "runtime is active"}


class FakeMcpServer:
    """Record requests forwarded by the Lambda application."""

    def __init__(self, response: McpResponse) -> None:
        self.response = response
        self.calls: list[tuple[Any, str | None]] = []

    def handle(
        self,
        request_body: Any,
        authorization_header: str | None,
    ) -> McpResponse:
        self.calls.append((request_body, authorization_header))
        return self.response


@pytest.fixture
def controller() -> FakeController:
    return FakeController()


@pytest.fixture
def mcp_server(
    monkeypatch: pytest.MonkeyPatch,
    controller: FakeController,
) -> RuntimeControlMcpServer:
    monkeypatch.setattr(
        mcp_module,
        "authenticate_request",
        lambda _header, _verifier: SimpleNamespace(
            subject=OWNER_SUBJECT
        ),
    )
    return RuntimeControlMcpServer(
        controller=controller,  # type: ignore[arg-type]
        token_verifier=object(),  # type: ignore[arg-type]
        allowed_subject=OWNER_SUBJECT,
    )


def _request(
    method: str,
    params: Mapping[str, Any] | None = None,
    request_id: int = 1,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
    }
    if params is not None:
        message["params"] = dict(params)
    return message


def _http_event(
    method: str,
    path: str,
    *,
    body: str = "",
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "version": "2.0",
        "rawPath": path,
        "headers": dict(headers or {}),
        "requestContext": {
            "http": {"method": method, "path": path}
        },
        "body": body,
        "isBase64Encoded": False,
    }


def _auth_config() -> AuthConfig:
    return AuthConfig(
        issuer=(
            "https://cognito-idp.eu-central-1.amazonaws.com/"
            "eu-central-1_example"
        ),
        app_client_id="client-123",
        resource="https://runtime.ghost.example/mcp",
        required_scope="ghost/runtime.control",
    )


def _application(
    controller: FakeController,
    response: McpResponse,
) -> tuple[RuntimeControlApplication, FakeMcpServer]:
    fake_server = FakeMcpServer(response)
    application = RuntimeControlApplication(
        controller=controller,  # type: ignore[arg-type]
        mcp_server=fake_server,  # type: ignore[arg-type]
        auth_config=_auth_config(),
    )
    return application, fake_server


def test_initialize_negotiates_supported_protocol(
    mcp_server: RuntimeControlMcpServer,
) -> None:
    response = mcp_server.handle(
        _request(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "1.0"},
            },
        ),
        AUTHORIZATION,
    )

    assert response.status_code == 200
    assert response.body is not None
    result = response.body["result"]
    assert result["protocolVersion"] == "2025-11-25"
    assert result["serverInfo"]["name"] == "ghost-runtime-control"
    assert result["capabilities"] == {"tools": {"listChanged": False}}


def test_tools_list_contains_exactly_three_approved_tools(
    mcp_server: RuntimeControlMcpServer,
) -> None:
    response = mcp_server.handle(
        _request("tools/list"),
        AUTHORIZATION,
    )

    assert response.body is not None
    tools = response.body["result"]["tools"]
    assert [tool["name"] for tool in tools] == [
        "ghost_ec2_start",
        "ghost_ec2_status",
        "ghost_ec2_stop",
    ]
    assert all(
        "instance_id" not in tool["inputSchema"].get("properties", {})
        for tool in tools
    )


def test_tools_call_delegates_start_status_and_stop(
    mcp_server: RuntimeControlMcpServer,
    controller: FakeController,
) -> None:
    start_response = mcp_server.handle(
        _request(
            "tools/call",
            {
                "name": "ghost_ec2_start",
                "arguments": {
                    "runtime_profile": 2,
                    "idle_timeout_minutes": 45,
                },
            },
        ),
        AUTHORIZATION,
    )
    status_response = mcp_server.handle(
        _request(
            "tools/call",
            {"name": "ghost_ec2_status", "arguments": {}},
            request_id=2,
        ),
        AUTHORIZATION,
    )
    stop_response = mcp_server.handle(
        _request(
            "tools/call",
            {"name": "ghost_ec2_stop", "arguments": {}},
            request_id=3,
        ),
        AUTHORIZATION,
    )

    assert controller.start_calls == [(2, 45)]
    assert controller.status_calls == 1
    assert controller.stop_calls == 1
    assert start_response.body is not None
    assert start_response.body["result"]["structuredContent"] == {
        "ec2_state": "running",
        "runtime_profile": 2,
        "ghost_ready": True,
        "effective_idle_timeout_minutes": 45,
    }
    assert status_response.body is not None
    assert status_response.body["result"]["isError"] is False
    assert stop_response.body is not None
    assert stop_response.body["result"]["isError"] is False


@pytest.mark.parametrize(
    ("arguments", "expected_message"),
    [
        (
            {"runtime_profile": True},
            "runtime_profile must be integer 1 or 2.",
        ),
        ({"runtime_profile": 3}, "runtime_profile must be 1 or 2."),
        (
            {"idle_timeout_minutes": "20"},
            "idle_timeout_minutes must be an integer.",
        ),
        (
            {"instance_id": "i-forbidden"},
            "Unsupported start argument(s): instance_id",
        ),
    ],
)
def test_start_rejects_invalid_or_unapproved_arguments(
    mcp_server: RuntimeControlMcpServer,
    controller: FakeController,
    arguments: Mapping[str, Any],
    expected_message: str,
) -> None:
    response = mcp_server.handle(
        _request(
            "tools/call",
            {"name": "ghost_ec2_start", "arguments": arguments},
        ),
        AUTHORIZATION,
    )

    assert response.status_code == 200
    assert response.body is not None
    result = response.body["result"]
    assert result["isError"] is True
    assert result["content"][0]["text"] == expected_message
    assert controller.start_calls == []


def test_missing_token_returns_unauthenticated_error(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: RuntimeControlMcpServer,
) -> None:
    def reject_token(_header: Any, _verifier: Any) -> None:
        raise AuthenticationError("missing bearer token")

    monkeypatch.setattr(mcp_module, "authenticate_request", reject_token)
    response = mcp_server.handle(_request("tools/list"), None)

    assert response.status_code == 401
    assert response.body is not None
    assert response.body["error"] == {
        "code": UNAUTHENTICATED,
        "message": "missing bearer token",
    }
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_authenticated_non_owner_is_forbidden(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: RuntimeControlMcpServer,
) -> None:
    monkeypatch.setattr(
        mcp_module,
        "authenticate_request",
        lambda _header, _verifier: SimpleNamespace(
            subject="another-cognito-subject"
        ),
    )
    response = mcp_server.handle(
        _request("tools/list"),
        AUTHORIZATION,
    )

    assert response.status_code == 403
    assert response.body is not None
    assert response.body["error"]["code"] == FORBIDDEN


def test_invalid_json_and_tool_notification_are_rejected(
    mcp_server: RuntimeControlMcpServer,
) -> None:
    parse_response = mcp_server.handle("{not-json", AUTHORIZATION)
    notification_response = mcp_server.handle(
        {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "ghost_ec2_status",
                "arguments": {},
            },
        },
        AUTHORIZATION,
    )

    assert parse_response.status_code == 400
    assert parse_response.body is not None
    assert parse_response.body["error"]["code"] == -32700
    assert notification_response.status_code == 400
    assert notification_response.body is not None
    assert notification_response.body["error"]["code"] == INVALID_REQUEST


def test_http_post_forwards_body_and_authorization_header(
    controller: FakeController,
) -> None:
    application, fake_server = _application(
        controller,
        McpResponse(
            status_code=200,
            body={"jsonrpc": "2.0", "id": 1, "result": {}},
            headers={"Content-Type": "application/json"},
        ),
    )
    body = json.dumps(_request("ping"))

    response = application.handle(
        _http_event(
            "POST",
            MCP_PATH,
            body=body,
            headers={"Authorization": AUTHORIZATION},
        )
    )

    assert response["statusCode"] == 200
    assert json.loads(response["body"])["result"] == {}
    assert fake_server.calls == [(body, AUTHORIZATION)]


def test_oauth_metadata_publishes_cognito_and_scope(
    controller: FakeController,
) -> None:
    application, fake_server = _application(
        controller,
        McpResponse(200, {}, {}),
    )

    response = application.handle(
        _http_event("GET", OAUTH_METADATA_PATH)
    )
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert body["resource"] == "https://runtime.ghost.example/mcp"
    assert body["authorization_servers"] == [
        (
            "https://cognito-idp.eu-central-1.amazonaws.com/"
            "eu-central-1_example"
        )
    ]
    assert body["scopes_supported"] == ["ghost/runtime.control"]
    assert fake_server.calls == []


def test_http_401_gets_complete_oauth_challenge(
    controller: FakeController,
) -> None:
    application, _fake_server = _application(
        controller,
        McpResponse(
            status_code=401,
            body={
                "jsonrpc": "2.0",
                "id": 1,
                "error": {
                    "code": UNAUTHENTICATED,
                    "message": "expired bearer token",
                },
            },
            headers={"Content-Type": "application/json"},
        ),
    )

    response = application.handle(
        _http_event(
            "POST",
            MCP_PATH,
            body=json.dumps(_request("tools/list")),
            headers={"Authorization": "Bearer expired"},
        )
    )
    challenge = response["headers"]["WWW-Authenticate"]

    assert response["statusCode"] == 401
    assert (
        'resource_metadata="https://runtime.ghost.example/'
        '.well-known/oauth-protected-resource/mcp"'
    ) in challenge
    assert 'scope="ghost/runtime.control"' in challenge
    assert 'error="invalid_token"' in challenge


def test_scheduled_event_runs_idle_watchdog(
    controller: FakeController,
) -> None:
    application, fake_server = _application(
        controller,
        McpResponse(200, {}, {}),
    )

    response = application.handle(
        {
            "source": "aws.scheduler",
            "detail-type": "Scheduled Event",
        }
    )

    assert response == {"watchdog_checked": True}
    assert controller.watchdog_calls == 1
    assert fake_server.calls == []