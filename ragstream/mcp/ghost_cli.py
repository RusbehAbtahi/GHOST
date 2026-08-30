"""Expose synchronous and asynchronous CLI execution through GHOST MCP.

The module is a thin authenticated adapter around the Part 1 command service.
It validates public MCP arguments, delegates execution and result retrieval,
formats stable tool results, and advertises the two OAuth-protected tools. It
does not classify commands, persist confirmations, run subprocesses, or call
AWS Systems Manager directly; those responsibilities remain in ragstream.cli.

Main classes:
    GhostCliTool:
        Provides sanitized synchronous run, asynchronous start, and result
        retrieval operations.

Main methods and functions:
    run_sanitized():
        Executes one command through the synchronous service path.
    async_sanitized():
        Starts a command or retrieves one existing durable command job.
    run_tool_metadata(), async_tool_metadata():
        Build the two OAuth-protected MCP tool descriptors.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ragstream.cli.command_service import (
    CommandOutcome,
    CommandService,
    CommandServiceError,
)
from ragstream.mcp.ghost_engineer_prompt import (
    DEFAULT_REQUIRED_SCOPE,
    GhostToolResult,
)
from ragstream.mcp.memory_tool_instructions import (
    load_memory_tool_instructions,
)


RUN_TOOL_NAME = "ghost_cli_run"
RUN_TOOL_TITLE = "GHOST CLI Run"
ASYNC_TOOL_NAME = "ghost_cli_async"
ASYNC_TOOL_TITLE = "GHOST CLI Async"

ASYNC_START_ACTION = "start"
ASYNC_RESULT_ACTION = "result"

_RUN_INSTRUCTIONS = load_memory_tool_instructions(
    "custom_cli_run.json"
)
_ASYNC_INSTRUCTIONS = load_memory_tool_instructions(
    "custom_cli_async.json"
)

RUN_TOOL_DESCRIPTION = _RUN_INSTRUCTIONS.tool_description
ASYNC_TOOL_DESCRIPTION = _ASYNC_INSTRUCTIONS.tool_description
CLI_SERVER_INSTRUCTIONS = (
    _RUN_INSTRUCTIONS.server_instruction
    + " "
    + _ASYNC_INSTRUCTIONS.server_instruction
)

RUN_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "minLength": 1,
            "description": _RUN_INSTRUCTIONS.field_descriptions[
                "command"
            ],
        },
        "confirmation_token": {
            "type": "string",
            "minLength": 1,
            "description": _RUN_INSTRUCTIONS.field_descriptions[
                "confirmation_token"
            ],
        },
        "confirmation_id": {
            "type": "string",
            "minLength": 1,
            "description": _RUN_INSTRUCTIONS.field_descriptions[
                "confirmation_id"
            ],
        },
    },
    "oneOf": [
        {"required": ["command"]},
        {"required": ["confirmation_id", "confirmation_token"]},
    ],
    "additionalProperties": False,
}

ASYNC_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                ASYNC_START_ACTION,
                ASYNC_RESULT_ACTION,
            ],
            "description": _ASYNC_INSTRUCTIONS.field_descriptions[
                "action"
            ],
        },
        "command": {
            "type": "string",
            "minLength": 1,
            "description": _ASYNC_INSTRUCTIONS.field_descriptions[
                "command"
            ],
        },
        "job_id": {
            "type": "string",
            "minLength": 1,
            "description": _ASYNC_INSTRUCTIONS.field_descriptions[
                "job_id"
            ],
        },
        "confirmation_token": {
            "type": "string",
            "minLength": 1,
            "description": _ASYNC_INSTRUCTIONS.field_descriptions[
                "confirmation_token"
            ],
        },
        "confirmation_id": {
            "type": "string",
            "minLength": 1,
            "description": _ASYNC_INSTRUCTIONS.field_descriptions[
                "confirmation_id"
            ],
        },
    },
    "required": ["action"],
    "additionalProperties": False,
}

_OUTPUT_STATUSES = [
    "confirmation_required",
    "in_progress",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
    "not_found",
    "request_error",
]

CLI_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": _OUTPUT_STATUSES,
        },
        "exit_code": {"type": "integer"},
        "stdout": {"type": "string"},
        "stderr": {"type": "string"},
        "truncated": {"type": "boolean"},
        "job_id": {"type": "string", "minLength": 1},
        "confirmation_required": {"type": "boolean"},
        "confirmation_id": {
            "type": "string",
            "minLength": 1,
        },
        "confirmation_token": {
            "type": "string",
            "minLength": 1,
        },
        "message": {"type": "string"},
    },
    "required": ["status"],
    "additionalProperties": False,
}


class GhostCliTool:
    """Adapt authenticated MCP calls to the owner-scoped command service."""

    def __init__(self, service: CommandService) -> None:
        """Store the Part 1 service without creating another backend."""
        self._service = service

    def run_sanitized(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        """Validate and execute one synchronous command request."""
        error = self._validate_base_request(
            owner_sub,
            arguments,
            {"command", "confirmation_id", "confirmation_token"},
            "CLI run input is required",
        )
        if error is not None:
            return self._failure(error)
        assert arguments is not None

        command, confirmation_id, confirmation_token, request_error = (
            self._command_request(arguments)
        )
        if request_error is not None:
            return self._failure(request_error)

        try:
            outcome = self._service.run_sync(
                owner_sub=owner_sub,
                command=command,
                confirmation_id=confirmation_id,
                confirmation_token=confirmation_token,
            )
        except ValueError as error:
            return self._failure(str(error))
        except CommandServiceError:
            return self._failure(
                "GHOST CLI backend could not execute the command"
            )
        except Exception:  # noqa: BLE001 - sanitize the MCP boundary
            return self._failure(
                "GHOST CLI execution failed"
            )

        return self._outcome_result(
            outcome,
            retry_tool_name=RUN_TOOL_NAME,
        )

    def async_sanitized(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        """Validate an asynchronous start or result-retrieval request."""
        error = self._validate_base_request(
            owner_sub,
            arguments,
            {
                "action",
                "command",
                "job_id",
                "confirmation_id",
                "confirmation_token",
            },
            "CLI async input is required",
        )
        if error is not None:
            return self._failure(error)
        assert arguments is not None

        action = arguments.get("action")
        if action not in {
            ASYNC_START_ACTION,
            ASYNC_RESULT_ACTION,
        }:
            return self._failure(
                "action must be either 'start' or 'result'"
            )

        if action == ASYNC_START_ACTION:
            return self._start_async(owner_sub, arguments)
        return self._get_async_result(owner_sub, arguments)

    def _start_async(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any],
    ) -> GhostToolResult:
        if "job_id" in arguments:
            return self._failure(
                "job_id is not allowed when action is 'start'"
            )

        command, confirmation_id, confirmation_token, request_error = (
            self._command_request(arguments)
        )
        if request_error is not None:
            return self._failure(request_error)

        try:
            outcome = self._service.start_async(
                owner_sub=owner_sub,
                command=command,
                confirmation_id=confirmation_id,
                confirmation_token=confirmation_token,
            )
        except ValueError as error:
            return self._failure(str(error))
        except CommandServiceError:
            return self._failure(
                "GHOST CLI backend could not start the command"
            )
        except Exception:  # noqa: BLE001 - sanitize the MCP boundary
            return self._failure(
                "GHOST CLI asynchronous execution failed"
            )

        return self._outcome_result(
            outcome,
            retry_tool_name=ASYNC_TOOL_NAME,
        )

    def _get_async_result(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any],
    ) -> GhostToolResult:
        if "command" in arguments:
            return self._failure(
                "command is not allowed when action is 'result'"
            )
        if "confirmation_token" in arguments:
            return self._failure(
                "confirmation_token is not allowed when action is 'result'"
            )
        if "confirmation_id" in arguments:
            return self._failure(
                "confirmation_id is not allowed when action is 'result'"
            )

        job_id = self._non_empty_string(arguments.get("job_id"))
        if job_id is None:
            return self._failure(
                "job_id is required when action is 'result'"
            )

        try:
            outcome = self._service.get_async_result(
                owner_sub=owner_sub,
                job_id=job_id,
            )
        except ValueError as error:
            return self._failure(str(error))
        except CommandServiceError:
            return self._failure(
                "GHOST CLI backend could not retrieve the command result"
            )
        except Exception:  # noqa: BLE001 - sanitize the MCP boundary
            return self._failure(
                "GHOST CLI result retrieval failed"
            )

        return self._outcome_result(
            outcome,
            retry_tool_name=ASYNC_TOOL_NAME,
        )

    @staticmethod
    def _validate_base_request(
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
        allowed_properties: set[str],
        missing_message: str,
    ) -> str | None:
        if not isinstance(owner_sub, str) or not owner_sub.strip():
            return "authenticated user is required"
        if not isinstance(arguments, Mapping):
            return missing_message
        if set(arguments).difference(allowed_properties):
            return "unsupported input property"
        return None

    @classmethod
    def _command_request(
        cls,
        arguments: Mapping[str, Any],
    ) -> tuple[str | None, str | None, str | None, str | None]:
        command = cls._non_empty_string(arguments.get("command"))
        confirmation_id = cls._non_empty_string(
            arguments.get("confirmation_id")
        )
        confirmation_token = cls._non_empty_string(
            arguments.get("confirmation_token")
        )
        if "command" in arguments and command is None:
            return None, None, None, "command must be a non-empty string"
        if "confirmation_id" in arguments and confirmation_id is None:
            return (
                None,
                None,
                None,
                "confirmation_id must be a non-empty string",
            )
        if "confirmation_token" in arguments and confirmation_token is None:
            return (
                None,
                None,
                None,
                "confirmation_token must be a non-empty string",
            )
        if command is not None and (
            confirmation_id is not None or confirmation_token is not None
        ):
            return (
                None,
                None,
                None,
                "command cannot be combined with confirmation_id or "
                "confirmation_token",
            )
        if command is None and (
            confirmation_id is None or confirmation_token is None
        ):
            return (
                None,
                None,
                None,
                "provide command, or provide both confirmation_id and "
                "confirmation_token",
            )
        return command, confirmation_id, confirmation_token, None

    @staticmethod
    def _non_empty_string(value: Any) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        return value.strip()

    @classmethod
    def _outcome_result(
        cls,
        outcome: CommandOutcome,
        retry_tool_name: str,
    ) -> GhostToolResult:
        structured_content = cls._structured_outcome(outcome)
        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": cls._format_outcome(
                        outcome,
                        retry_tool_name,
                    ),
                }
            ],
            structuredContent=structured_content,
            isError=outcome.status == "not_found",
        )

    @staticmethod
    def _structured_outcome(
        outcome: CommandOutcome,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"status": outcome.status}

        if outcome.exit_code is not None:
            result["exit_code"] = outcome.exit_code
        if outcome.stdout:
            result["stdout"] = outcome.stdout
        if outcome.stderr:
            result["stderr"] = outcome.stderr
        if outcome.truncated:
            result["truncated"] = True
        if outcome.job_id:
            result["job_id"] = outcome.job_id
        if outcome.confirmation_required:
            result["confirmation_required"] = True
        if outcome.confirmation_id:
            result["confirmation_id"] = outcome.confirmation_id
        if outcome.confirmation_token:
            result["confirmation_token"] = (
                outcome.confirmation_token
            )
        if outcome.message:
            result["message"] = outcome.message

        return result

    @staticmethod
    def _format_outcome(
        outcome: CommandOutcome,
        retry_tool_name: str,
    ) -> str:
        if outcome.confirmation_required:
            return (
                "Confirmation required. The command was NOT executed.\n"
                f"Reason: {outcome.message}\n"
                f"Confirmation ID: {outcome.confirmation_id}\n"
                f"Confirmation token: {outcome.confirmation_token}\n"
                f"After explicit user approval, retry {retry_tool_name} "
                "with this confirmation ID and token; omit command."
            )

        if outcome.status == "in_progress":
            return (
                "Command is still running.\n"
                f"Job ID: {outcome.job_id}\n"
                "Retrieve the same job with ghost_cli_async action "
                "'result'. Do not start it again."
            )

        if outcome.status == "not_found":
            return (
                "Command job was not found for the authenticated user.\n"
                f"Job ID: {outcome.job_id}"
            )

        lines = [f"Status: {outcome.status}"]
        if outcome.job_id:
            lines.append(f"Job ID: {outcome.job_id}")
        if outcome.exit_code is not None:
            lines.append(f"Exit code: {outcome.exit_code}")
        if outcome.message:
            lines.append(f"Message: {outcome.message}")
        if outcome.truncated:
            lines.append("Output truncated: true")
        if outcome.stdout:
            lines.extend(["", "STDOUT:", outcome.stdout])
        if outcome.stderr:
            lines.extend(["", "STDERR:", outcome.stderr])
        return "\n".join(lines)

    @staticmethod
    def _failure(reason: str) -> GhostToolResult:
        return GhostToolResult(
            content=[
                {
                    "type": "text",
                    "text": (
                        "GHOST CLI request failed. "
                        f"Reason: {reason}."
                    ),
                }
            ],
            structuredContent={
                "status": "request_error",
                "message": reason,
            },
            isError=True,
        )


def run_tool_metadata(
    required_scope: str | None = None,
) -> dict[str, Any]:
    """Build the OAuth-protected synchronous CLI descriptor."""
    return _tool_metadata(
        name=RUN_TOOL_NAME,
        title=RUN_TOOL_TITLE,
        description=RUN_TOOL_DESCRIPTION,
        input_schema=RUN_INPUT_SCHEMA,
        required_scope=required_scope,
    )


def async_tool_metadata(
    required_scope: str | None = None,
) -> dict[str, Any]:
    """Build the OAuth-protected asynchronous CLI descriptor."""
    return _tool_metadata(
        name=ASYNC_TOOL_NAME,
        title=ASYNC_TOOL_TITLE,
        description=ASYNC_TOOL_DESCRIPTION,
        input_schema=ASYNC_INPUT_SCHEMA,
        required_scope=required_scope,
    )


def _tool_metadata(
    name: str,
    title: str,
    description: str,
    input_schema: dict[str, Any],
    required_scope: str | None,
) -> dict[str, Any]:
    scope = (
        required_scope
        if required_scope is not None
        else DEFAULT_REQUIRED_SCOPE
    ).strip()
    if not scope:
        raise ValueError("required_scope must not be empty")

    security_schemes = [
        {
            "type": "oauth2",
            "scopes": [scope],
        }
    ]
    return {
        "name": name,
        "title": title,
        "description": description,
        "inputSchema": input_schema,
        "outputSchema": CLI_OUTPUT_SCHEMA,
        "securitySchemes": security_schemes,
        "_meta": {
            "securitySchemes": security_schemes.copy(),
        },
        "annotations": {
            "destructiveHint": True,
            "readOnlyHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    }
