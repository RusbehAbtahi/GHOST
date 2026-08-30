"""Test the Part 2 CLI MCP contracts and application integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from ragstream.cli.command_service import (
    CommandOutcome,
    CommandServiceError,
)
from ragstream.mcp.ghost_cli import (
    ASYNC_INPUT_SCHEMA,
    ASYNC_RESULT_ACTION,
    ASYNC_START_ACTION,
    ASYNC_TOOL_NAME,
    CLI_OUTPUT_SCHEMA,
    RUN_INPUT_SCHEMA,
    RUN_TOOL_NAME,
    GhostCliTool,
    async_tool_metadata,
    run_tool_metadata,
)
from ragstream.mcp.ghost_mcp_app import (
    GHOST_TOOL_NAMES,
    GhostMcpApplication,
)


@dataclass
class RecordingCommandService:
    """Return controlled Part 1 outcomes and record adapter calls."""

    sync_outcome: CommandOutcome = field(
        default_factory=lambda: CommandOutcome(
            status="succeeded",
            exit_code=0,
            stdout="sync output",
            job_id="sync-job",
        )
    )
    async_outcome: CommandOutcome = field(
        default_factory=lambda: CommandOutcome(
            status="in_progress",
            job_id="async-job",
        )
    )
    result_outcome: CommandOutcome = field(
        default_factory=lambda: CommandOutcome(
            status="succeeded",
            exit_code=0,
            stdout="async output",
            job_id="async-job",
        )
    )
    calls: list[tuple[Any, ...]] = field(default_factory=list)

    def run_sync(
        self,
        owner_sub: str,
        command: str | None = None,
        confirmation_id: str | None = None,
        confirmation_token: str | None = None,
    ) -> CommandOutcome:
        self.calls.append(
            (
                "run_sync",
                owner_sub,
                command,
                confirmation_id,
                confirmation_token,
            )
        )
        return self.sync_outcome

    def start_async(
        self,
        owner_sub: str,
        command: str | None = None,
        confirmation_id: str | None = None,
        confirmation_token: str | None = None,
    ) -> CommandOutcome:
        self.calls.append(
            (
                "start_async",
                owner_sub,
                command,
                confirmation_id,
                confirmation_token,
            )
        )
        return self.async_outcome

    def get_async_result(
        self,
        owner_sub: str,
        job_id: str,
    ) -> CommandOutcome:
        self.calls.append(
            (
                "get_async_result",
                owner_sub,
                job_id,
            )
        )
        return self.result_outcome


class FailingCommandService(RecordingCommandService):
    """Raise a private detail that must not cross the MCP boundary."""

    def run_sync(
        self,
        owner_sub: str,
        command: str | None = None,
        confirmation_id: str | None = None,
        confirmation_token: str | None = None,
    ) -> CommandOutcome:
        del owner_sub, command, confirmation_id, confirmation_token
        raise CommandServiceError(
            "/private/path AWS_SECRET_ACCESS_KEY=secret"
        )


def _tool(
    service: RecordingCommandService | None = None,
) -> tuple[GhostCliTool, RecordingCommandService]:
    command_service = service or RecordingCommandService()
    return (
        GhostCliTool(command_service),  # type: ignore[arg-type]
        command_service,
    )


def test_cli_metadata_declares_two_protected_stateful_tools() -> None:
    run = run_tool_metadata("ghost.invoke")
    asynchronous = async_tool_metadata("ghost.invoke")

    assert run["name"] == RUN_TOOL_NAME
    assert asynchronous["name"] == ASYNC_TOOL_NAME
    assert run["inputSchema"] == RUN_INPUT_SCHEMA
    assert asynchronous["inputSchema"] == ASYNC_INPUT_SCHEMA
    assert run["outputSchema"] == CLI_OUTPUT_SCHEMA
    assert asynchronous["outputSchema"] == CLI_OUTPUT_SCHEMA

    for metadata in (run, asynchronous):
        assert metadata["securitySchemes"] == [
            {
                "type": "oauth2",
                "scopes": ["ghost.invoke"],
            }
        ]
        assert metadata["annotations"] == {
            "destructiveHint": True,
            "readOnlyHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        }


def test_run_delegates_exact_values_and_returns_complete_result() -> None:
    tool, service = _tool()

    result = tool.run_sanitized(
        "owner-1",
        {
            "command": "  docker ps  ",
        },
    )

    assert result.isError is False
    assert service.calls == [
        (
            "run_sync",
            "owner-1",
            "docker ps",
            None,
            None,
        )
    ]
    assert result.structuredContent == {
        "status": "succeeded",
        "exit_code": 0,
        "stdout": "sync output",
        "job_id": "sync-job",
    }
    assert result.content[0]["text"] == (
        "Status: succeeded\n"
        "Job ID: sync-job\n"
        "Exit code: 0\n\n"
        "STDOUT:\n"
        "sync output"
    )


def test_confirmation_result_states_that_command_did_not_execute() -> None:
    service = RecordingCommandService(
        sync_outcome=CommandOutcome(
            status="confirmation_required",
            confirmation_required=True,
            confirmation_id="pending-command",
            confirmation_token="confirm-once",
            message="'rm' is not classified as read-only",
        )
    )
    tool, _ = _tool(service)

    result = tool.run_sanitized(
        "owner-1",
        {"command": "rm old.log"},
    )

    assert result.isError is False
    assert result.structuredContent == {
        "status": "confirmation_required",
        "confirmation_required": True,
        "confirmation_id": "pending-command",
        "confirmation_token": "confirm-once",
        "message": "'rm' is not classified as read-only",
    }
    assert "The command was NOT executed." in result.content[0]["text"]
    assert "omit command" in result.content[0]["text"]


def test_run_confirms_server_side_command_without_resending_it() -> None:
    tool, service = _tool()

    result = tool.run_sanitized(
        "owner-1",
        {
            "confirmation_id": "  pending-command  ",
            "confirmation_token": "  approved-token  ",
        },
    )

    assert result.isError is False
    assert service.calls == [
        (
            "run_sync",
            "owner-1",
            None,
            "pending-command",
            "approved-token",
        )
    ]


def test_async_start_and_result_use_one_tool_without_restarting() -> None:
    tool, service = _tool()

    started = tool.async_sanitized(
        "owner-1",
        {
            "action": ASYNC_START_ACTION,
            "command": "sleep 30",
        },
    )
    completed = tool.async_sanitized(
        "owner-1",
        {
            "action": ASYNC_RESULT_ACTION,
            "job_id": "async-job",
        },
    )

    assert started.structuredContent == {
        "status": "in_progress",
        "job_id": "async-job",
    }
    assert completed.structuredContent == {
        "status": "succeeded",
        "exit_code": 0,
        "stdout": "async output",
        "job_id": "async-job",
    }
    assert service.calls == [
        (
            "start_async",
            "owner-1",
            "sleep 30",
            None,
            None,
        ),
        (
            "get_async_result",
            "owner-1",
            "async-job",
        ),
    ]


@pytest.mark.parametrize(
    ("arguments", "expected_reason"),
    [
        (
            {"action": "unknown"},
            "action must be either 'start' or 'result'",
        ),
        (
            {
                "action": ASYNC_START_ACTION,
                "job_id": "existing",
                "command": "df -h",
            },
            "job_id is not allowed when action is 'start'",
        ),
        (
            {"action": ASYNC_START_ACTION},
            "provide command, or provide both confirmation_id and confirmation_token",
        ),
        (
            {
                "action": ASYNC_RESULT_ACTION,
                "job_id": "existing",
                "command": "df -h",
            },
            "command is not allowed when action is 'result'",
        ),
        (
            {
                "action": ASYNC_RESULT_ACTION,
                "job_id": "existing",
                "confirmation_token": "token",
            },
            "confirmation_token is not allowed when action is 'result'",
        ),
        (
            {"action": ASYNC_RESULT_ACTION},
            "job_id is required when action is 'result'",
        ),
    ],
)
def test_async_rejects_invalid_action_field_combinations(
    arguments: dict[str, str],
    expected_reason: str,
) -> None:
    tool, service = _tool()

    result = tool.async_sanitized("owner-1", arguments)

    assert result.isError is True
    assert result.structuredContent == {
        "status": "request_error",
        "message": expected_reason,
    }
    assert service.calls == []


@pytest.mark.parametrize(
    ("owner_sub", "arguments", "expected_reason"),
    [
        (
            "",
            {"command": "df -h"},
            "authenticated user is required",
        ),
        (
            "owner-1",
            None,
            "CLI run input is required",
        ),
        (
            "owner-1",
            {"command": ""},
            "command must be a non-empty string",
        ),
        (
            "owner-1",
            {
                "command": "df -h",
                "unexpected": True,
            },
            "unsupported input property",
        ),
        (
            "owner-1",
            {
                "command": "df -h",
                "confirmation_token": 7,
            },
            "confirmation_token must be a non-empty string",
        ),
    ],
)
def test_run_rejects_invalid_input_without_calling_service(
    owner_sub: str,
    arguments: dict[str, Any] | None,
    expected_reason: str,
) -> None:
    tool, service = _tool()

    result = tool.run_sanitized(owner_sub, arguments)

    assert result.isError is True
    assert result.structuredContent == {
        "status": "request_error",
        "message": expected_reason,
    }
    assert service.calls == []


def test_backend_failure_is_sanitized() -> None:
    tool, _ = _tool(FailingCommandService())

    result = tool.run_sanitized(
        "owner-1",
        {"command": "df -h"},
    )

    message = result.content[0]["text"]
    assert result.isError is True
    assert result.structuredContent == {
        "status": "request_error",
        "message": "GHOST CLI backend could not execute the command",
    }
    assert "/private/path" not in message
    assert "AWS_SECRET_ACCESS_KEY" not in message
    assert "secret" not in message


def test_application_inventory_and_dispatch_include_both_cli_tools() -> None:
    service = RecordingCommandService()
    application = GhostMcpApplication.__new__(
        GhostMcpApplication
    )
    application.required_scope = "ghost.invoke"
    application.cli_tool = GhostCliTool(  # type: ignore[arg-type]
        service
    )

    tool_names = [
        tool.name
        for tool in application.list_tools()
    ]

    assert RUN_TOOL_NAME in GHOST_TOOL_NAMES
    assert ASYNC_TOOL_NAME in GHOST_TOOL_NAMES
    assert RUN_TOOL_NAME in tool_names
    assert ASYNC_TOOL_NAME in tool_names

    run_result = application.call_tool(
        RUN_TOOL_NAME,
        {"command": "df -h"},
        owner_sub="owner-1",
    )
    async_result = application.call_tool(
        ASYNC_TOOL_NAME,
        {
            "action": ASYNC_RESULT_ACTION,
            "job_id": "async-job",
        },
        owner_sub="owner-1",
    )

    assert run_result.isError is False
    assert run_result.structuredContent == {
        "status": "succeeded",
        "exit_code": 0,
        "stdout": "sync output",
        "job_id": "sync-job",
    }
    assert async_result.isError is False
    assert async_result.structuredContent == {
        "status": "succeeded",
        "exit_code": 0,
        "stdout": "async output",
        "job_id": "async-job",
    }
