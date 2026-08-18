"""Expose GHOST EC2 runtime control through MCP JSON-RPC.

It authenticates each message, publishes exactly three approved tools,
validates their inputs, and delegates AWS work to Ec2Controller.

API Gateway event parsing belongs to lambda_handler.py. EC2 and SSM operations
belong to ec2_controller.py and runtime_state.py.
"""

from __future__ import annotations

import copy
import hmac
import json
import logging
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Mapping, Sequence

from ragstream.mcp.auth import (
    AuthenticationError,
    AuthenticationServiceError,
    AuthorizationError,
    CognitoTokenVerifier,
    authenticate_request,
)

from .ec2_controller import Ec2ControlError, Ec2Controller


LOGGER = logging.getLogger(__name__)

SERVER_NAME = "ghost-runtime-control"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_PROTOCOL_VERSIONS = frozenset(
    {"2025-03-26", "2025-06-18", "2025-11-25"}
)

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
UNAUTHENTICATED = -32001
FORBIDDEN = -32003
AUTH_SERVICE_UNAVAILABLE = -32004


# The instance ID is deliberately absent: callers can control only the fixed
# EC2 target configured through the Lambda environment.
TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "ghost_ec2_start",
        "title": "Start GHOST EC2",
        "description": (
            "Start the configured GHOST EC2 instance with an approved runtime "
            "profile and idle timeout, then wait for GHOST readiness."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "runtime_profile": {
                    "type": "integer",
                    "enum": [1, 2],
                    "default": 1,
                    "description": (
                        "Profile 1 uses t3.medium; profile 2 uses "
                        "m7i-flex.xlarge."
                    ),
                },
                "idle_timeout_minutes": {
                    "type": "integer",
                    "default": 20,
                    "description": (
                        "Idle shutdown timeout. Values are constrained to "
                        "10 through 120 minutes."
                    ),
                },
            },
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    },
    {
        "name": "ghost_ec2_status",
        "title": "Inspect GHOST EC2 Status",
        "description": (
            "Report EC2 state, runtime profile, readiness, idle timeout, and "
            "inactivity without refreshing the inactivity timer."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    },
    {
        "name": "ghost_ec2_stop",
        "title": "Stop GHOST EC2",
        "description": (
            "Normally stop the configured EC2 instance without terminating it "
            "or changing its runtime profile."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    },
)


@dataclass(frozen=True)
class McpResponse:
    """HTTP status, JSON-RPC body, and headers for lambda_handler.py."""

    status_code: int
    body: dict[str, Any] | None
    headers: Mapping[str, str]


class McpProtocolError(Exception):
    """A request violated JSON-RPC or the supported MCP method contract."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RuntimeControlMcpServer:
    """Authenticate requests and expose the three runtime-control tools.

    controller owns EC2 behavior. token_verifier is the existing shared
    Cognito verifier. allowed_subject is the only Cognito user permitted to
    control the configured instance.
    """

    def __init__(
        self,
        controller: Ec2Controller,
        token_verifier: CognitoTokenVerifier,
        allowed_subject: str,
    ) -> None:
        owner_subject = allowed_subject.strip()
        if not owner_subject:
            raise ValueError("allowed Cognito subject cannot be empty")

        self._controller = controller
        self._token_verifier = token_verifier
        self._allowed_subject = owner_subject

    def handle(
        self,
        request_body: str | bytes | Mapping[str, Any],
        authorization_header: str | None,
    ) -> McpResponse:
        """Process one MCP JSON-RPC message and return an HTTP-ready result."""

        try:
            message = self._parse_message(request_body)
        except McpProtocolError as exc:
            return self._error(None, exc.code, exc.message, 400)

        request_id = message.get("id")
        authentication_error = self._authenticate(
            authorization_header,
            request_id,
        )
        if authentication_error is not None:
            return authentication_error

        if "id" not in message:
            return self._handle_notification(message)

        try:
            result = self._dispatch(message)
        except McpProtocolError as exc:
            return self._error(request_id, exc.code, exc.message)
        except Exception:
            LOGGER.exception("Unhandled runtime-control MCP request failure")
            return self._error(
                request_id,
                INTERNAL_ERROR,
                "Internal runtime-control error.",
                500,
            )

        return McpResponse(
            status_code=200,
            body={
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result,
            },
            headers={"Content-Type": "application/json"},
        )

    def _parse_message(
        self,
        request_body: str | bytes | Mapping[str, Any],
    ) -> dict[str, Any]:
        """Decode and validate the common JSON-RPC message fields."""

        if isinstance(request_body, Mapping):
            message: Any = dict(request_body)
        else:
            try:
                message = json.loads(request_body)
            except (
                json.JSONDecodeError,
                TypeError,
                UnicodeDecodeError,
            ) as exc:
                raise McpProtocolError(
                    PARSE_ERROR,
                    "Request body is not valid JSON.",
                ) from exc

        if not isinstance(message, dict):
            raise McpProtocolError(
                INVALID_REQUEST,
                "Message must be an object.",
            )

        if message.get("jsonrpc") != "2.0":
            raise McpProtocolError(
                INVALID_REQUEST,
                "jsonrpc must be '2.0'.",
            )

        if (
            not isinstance(message.get("method"), str)
            or not message["method"]
        ):
            raise McpProtocolError(
                INVALID_REQUEST,
                "method must be a non-empty string.",
            )

        if (
            "id" in message
            and not self._is_request_id(message["id"])
        ):
            raise McpProtocolError(
                INVALID_REQUEST,
                "id must be a string or integer.",
            )

        if (
            message.get("params") is not None
            and not isinstance(message.get("params", {}), Mapping)
        ):
            raise McpProtocolError(
                INVALID_PARAMS,
                "params must be an object.",
            )

        return message

    def _authenticate(
        self,
        authorization_header: str | None,
        request_id: Any,
    ) -> McpResponse | None:
        """Validate the token and restrict runtime control to the owner."""

        try:
            principal = authenticate_request(
                authorization_header,
                self._token_verifier,
            )

            if not hmac.compare_digest(
                principal.subject,
                self._allowed_subject,
            ):
                raise AuthorizationError(
                    "Identity is not authorized for runtime control."
                )

        except AuthenticationError as exc:
            return self._error(
                request_id,
                UNAUTHENTICATED,
                str(exc),
                401,
                {"WWW-Authenticate": "Bearer"},
            )

        except AuthorizationError as exc:
            return self._error(
                request_id,
                FORBIDDEN,
                str(exc),
                403,
            )

        except AuthenticationServiceError as exc:
            return self._error(
                request_id,
                AUTH_SERVICE_UNAVAILABLE,
                str(exc),
                503,
            )

        return None

    def _handle_notification(
        self,
        message: Mapping[str, Any],
    ) -> McpResponse:
        if message["method"] == "tools/call":
            return self._error(
                None,
                INVALID_REQUEST,
                "tools/call requires a JSON-RPC id.",
                400,
            )

        return McpResponse(
            status_code=202,
            body=None,
            headers={},
        )

    def _dispatch(
        self,
        message: Mapping[str, Any],
    ) -> dict[str, Any]:
        method = str(message["method"])
        params = self._params(message)

        if method == "initialize":
            requested = params.get("protocolVersion")
            negotiated = (
                requested
                if requested in SUPPORTED_PROTOCOL_VERSIONS
                else PROTOCOL_VERSION
            )

            return {
                "protocolVersion": negotiated,
                "capabilities": {
                    "tools": {
                        "listChanged": False,
                    }
                },
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                },
                "instructions": (
                    "Use these tools only to start, inspect, or stop the fixed "
                    "GHOST EC2 runtime."
                ),
            }

        if method == "ping":
            return {}

        if method == "tools/list":
            return {
                "tools": copy.deepcopy(list(TOOLS)),
            }

        if method == "tools/call":
            return self._call_tool(params)

        raise McpProtocolError(
            METHOD_NOT_FOUND,
            f"Unsupported MCP method: {method}",
        )

    def _call_tool(
        self,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments", {})

        if not isinstance(name, str) or not name:
            raise McpProtocolError(
                INVALID_PARAMS,
                "tools/call requires a tool name.",
            )

        if not isinstance(arguments, Mapping):
            raise McpProtocolError(
                INVALID_PARAMS,
                "Tool arguments must be an object.",
            )

        if name == "ghost_ec2_start":
            return self._call_start(arguments)

        if name == "ghost_ec2_status":
            return self._call_empty(
                arguments,
                self._controller.status,
            )

        if name == "ghost_ec2_stop":
            return self._call_empty(
                arguments,
                self._controller.stop,
            )

        raise McpProtocolError(
            INVALID_PARAMS,
            f"Unknown runtime-control tool: {name}",
        )

    def _call_start(
        self,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        unknown = set(arguments) - {
            "runtime_profile",
            "idle_timeout_minutes",
        }

        if unknown:
            return self._tool_error(
                "Unsupported start argument(s): "
                + ", ".join(sorted(unknown))
            )

        profile = arguments.get("runtime_profile")
        timeout = arguments.get("idle_timeout_minutes")

        if (
            profile is not None
            and not self._is_integer(profile)
        ):
            return self._tool_error(
                "runtime_profile must be integer 1 or 2."
            )

        if profile not in (None, 1, 2):
            return self._tool_error(
                "runtime_profile must be 1 or 2."
            )

        if (
            timeout is not None
            and not self._is_integer(timeout)
        ):
            return self._tool_error(
                "idle_timeout_minutes must be an integer."
            )

        try:
            result = self._controller.start(
                runtime_profile=profile,
                idle_timeout_minutes=timeout,
            )
        except (
            Ec2ControlError,
            TypeError,
            ValueError,
        ) as exc:
            return self._tool_error(str(exc))

        return self._tool_success(result)

    def _call_empty(
        self,
        arguments: Mapping[str, Any],
        operation: Any,
    ) -> dict[str, Any]:
        if arguments:
            return self._tool_error(
                "This tool does not accept arguments."
            )

        try:
            return self._tool_success(operation())
        except (
            Ec2ControlError,
            TypeError,
            ValueError,
        ) as exc:
            return self._tool_error(str(exc))

    def _tool_success(
        self,
        result: Any,
    ) -> dict[str, Any]:
        structured = self._json_value(result)

        if not isinstance(structured, dict):
            structured = {
                "result": structured,
            }

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        structured,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                }
            ],
            "structuredContent": structured,
            "isError": False,
        }

    @staticmethod
    def _tool_error(
        message: str,
    ) -> dict[str, Any]:
        """Return a recoverable MCP tool-execution error."""

        return {
            "content": [
                {
                    "type": "text",
                    "text": (
                        message.strip()
                        or "Runtime-control operation failed."
                    ),
                }
            ],
            "isError": True,
        }

    @classmethod
    def _json_value(
        cls,
        value: Any,
    ) -> Any:
        """Convert controller data classes and timestamps to JSON values."""

        if is_dataclass(value) and not isinstance(value, type):
            return cls._json_value(asdict(value))

        if isinstance(value, Enum):
            return cls._json_value(value.value)

        if isinstance(value, (datetime, date)):
            return value.isoformat()

        if isinstance(value, Mapping):
            return {
                str(key): cls._json_value(item)
                for key, item in value.items()
            }

        if isinstance(value, Sequence) and not isinstance(
            value,
            (str, bytes, bytearray),
        ):
            return [
                cls._json_value(item)
                for item in value
            ]

        if value is None or isinstance(
            value,
            (str, int, float, bool),
        ):
            return value

        return str(value)

    @staticmethod
    def _params(
        message: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Return already-validated request parameters."""

        params = message.get("params")
        return {} if params is None else params

    @staticmethod
    def _is_request_id(
        value: Any,
    ) -> bool:
        """Accept JSON-RPC string and integer IDs, excluding booleans."""

        return isinstance(value, str) or (
            isinstance(value, int)
            and not isinstance(value, bool)
        )

    @staticmethod
    def _is_integer(
        value: Any,
    ) -> bool:
        """Accept integer tool inputs without treating booleans as integers."""

        return (
            isinstance(value, int)
            and not isinstance(value, bool)
        )

    @staticmethod
    def _error(
        request_id: Any,
        code: int,
        message: str,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> McpResponse:
        """Build a JSON-RPC error with its corresponding HTTP status."""

        response_headers = {
            "Content-Type": "application/json",
        }

        if headers:
            response_headers.update(headers)

        return McpResponse(
            status_code=status_code,
            body={
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": code,
                    "message": message,
                },
            },
            headers=response_headers,
        )