"""Connect API Gateway and the scheduled watchdog to runtime-control logic.

This module is the AWS Lambda entry point. It creates the application once per
warm Lambda environment, converts API Gateway events into MCP requests, exposes
OAuth Protected Resource Metadata, and invokes the idle watchdog for scheduled
events.

Main class:
    RuntimeControlApplication: Routes HTTP and scheduled Lambda invocations.

Main function:
    lambda_handler(): Function configured as the Lambda Handler in SAM.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from functools import lru_cache
from typing import Any, Mapping
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urlsplit
from urllib.request import Request, urlopen

from ragstream.mcp.auth import AuthConfig, CognitoTokenVerifier

from .config import RuntimeControlConfig
from .ec2_controller import Ec2Controller
from .mcp_server import McpResponse, RuntimeControlMcpServer
from .runtime_state import RuntimeStateStore


LOGGER = logging.getLogger(__name__)

MCP_PATH = "/mcp"
OAUTH_METADATA_PATH = "/.well-known/oauth-protected-resource/mcp"
OAUTH_SERVER_METADATA_PATH = "/.well-known/oauth-authorization-server"
OAUTH_AUTHORIZE_PATH = "/oauth/authorize"
OAUTH_TOKEN_PATH = "/oauth/token"
OIDC_METADATA_PATH = "/.well-known/openid-configuration"
OIDC_FETCH_TIMEOUT_SECONDS = 5.0


class RuntimeControlApplication:
    """Route API Gateway and watchdog events to the correct service.

    controller:
        Executes the scheduled idle check and all EC2 lifecycle operations.
    mcp_server:
        Authenticates and executes MCP JSON-RPC requests.
    auth_config:
        Provides the OAuth resource, issuer, and scope published to clients.
    """

    def __init__(
        self,
        controller: Ec2Controller,
        mcp_server: RuntimeControlMcpServer,
        auth_config: AuthConfig,
    ) -> None:
        self._controller = controller
        self._mcp_server = mcp_server
        self._auth_config = auth_config
        self._resource_metadata_url = self._build_metadata_url(
            auth_config.resource
        )
        self._authorization_server = self._build_authorization_server(
            auth_config.resource
        )

    def handle(
        self,
        event: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Handle one API Gateway request or scheduled watchdog invocation."""

        if _is_api_gateway_event(event):
            return self._handle_http(event)

        return self._handle_watchdog()

    def _handle_http(
        self,
        event: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Route one API Gateway request without exposing AWS event details."""

        method = self._http_method(event)
        path = self._request_path(event)

        if (
            method == "GET"
            and path.endswith(OAUTH_METADATA_PATH)
        ):
            return self._oauth_metadata_response()

        if (
            method == "GET"
            and path.endswith(OAUTH_SERVER_METADATA_PATH)
        ):
            return self._oauth_server_metadata_response()

        if (
            method == "GET"
            and path.endswith(OAUTH_AUTHORIZE_PATH)
        ):
            return self._oauth_authorization_redirect(event)

        if (
            method == "POST"
            and path.endswith(OAUTH_TOKEN_PATH)
        ):
            return self._oauth_token_response(event)

        if (
            method == "GET"
            and path.endswith(OIDC_METADATA_PATH)
        ):
            return self._oidc_metadata_response()

        if not path.endswith(MCP_PATH):
            return self._http_response(
                404,
                {"error": "not_found"},
            )

        # This Lambda returns JSON responses rather than a server-sent event
        # stream. MCP permits GET to return 405 when SSE is not provided.
        if method != "POST":
            return self._http_response(
                405,
                {"error": "method_not_allowed"},
                {"Allow": "POST"},
            )

        try:
            request_body = self._request_body(event)
        except ValueError:
            return self._http_response(
                400,
                {"error": "invalid_request_body"},
            )

        request_headers = self._request_headers(event)
        authorization_header = request_headers.get(
            "authorization"
        )

        mcp_response = self._mcp_server.handle(
            request_body,
            authorization_header,
        )

        return self._mcp_http_response(
            mcp_response,
            authorization_header,
        )

    def _handle_watchdog(
        self,
    ) -> dict[str, Any]:
        """Run one scheduled idle check without starting a stopped instance."""

        result = self._controller.stop_if_idle()

        LOGGER.info(
            "GHOST runtime-control watchdog completed: %s",
            result,
        )

        # EventBridge Scheduler ignores the Lambda result. Keep it small and
        # JSON-safe while CloudWatch receives the detailed result in the log.
        return {
            "watchdog_checked": True,
        }

    def _oauth_metadata_response(
        self,
    ) -> dict[str, Any]:
        """Publish discovery metadata for the existing Cognito environment."""

        return self._http_response(
            200,
            {
                "resource": self._auth_config.resource,
                "authorization_servers": [
                    self._authorization_server
                ],
                "scopes_supported": [
                    self._auth_config.required_scope
                ],
            },
        )

    def _oidc_metadata_response(
        self,
    ) -> dict[str, Any]:
        """Publish Cognito metadata with missing MCP declarations."""

        try:
            metadata = _load_cognito_oidc_metadata(
                self._auth_config.issuer,
                self._auth_config.required_scope,
            )
        except (OSError, ValueError):
            LOGGER.exception(
                "Unable to load Cognito OIDC discovery metadata"
            )
            return self._http_response(
                502,
                {"error": "authorization_server_metadata_unavailable"},
            )

        return self._http_response(200, metadata)

    def _oauth_server_metadata_response(
        self,
    ) -> dict[str, Any]:
        """Publish a ChatGPT-compatible OAuth facade for Cognito."""

        try:
            metadata = dict(
                _load_cognito_oidc_metadata(
                    self._auth_config.issuer,
                    self._auth_config.required_scope,
                )
            )
        except (OSError, ValueError, json.JSONDecodeError):
            LOGGER.exception(
                "Unable to load Cognito authorization-server metadata"
            )
            return self._http_response(
                502,
                {"error": "authorization_server_metadata_unavailable"},
            )

        metadata.update(
            {
                "issuer": self._authorization_server,
                "authorization_endpoint": (
                    f"{self._authorization_server}{OAUTH_AUTHORIZE_PATH}"
                ),
                "token_endpoint": (
                    f"{self._authorization_server}{OAUTH_TOKEN_PATH}"
                ),
                "response_types_supported": ["code"],
                "grant_types_supported": [
                    "authorization_code",
                    "refresh_token",
                ],
                "token_endpoint_auth_methods_supported": ["none"],
                "code_challenge_methods_supported": ["S256"],
                "scopes_supported": [
                    self._auth_config.required_scope
                ],
            }
        )
        metadata.pop(
            "authorization_response_iss_parameter_supported",
            None,
        )

        return self._http_response(200, metadata)

    def _oauth_authorization_redirect(
        self,
        event: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Validate the resource and redirect the request to Cognito."""

        from urllib.parse import parse_qsl, urlencode

        parameters = parse_qsl(
            self._encoded_query_string(event),
            keep_blank_values=True,
        )

        requested_resources = [
            value
            for name, value in parameters
            if name == "resource"
        ]
        if any(
            resource != self._auth_config.resource
            for resource in requested_resources
        ):
            return self._http_response(
                400,
                {"error": "invalid_target"},
            )

        # Cognito rejects resource-binding because its custom scope uses a
        # different resource-server identifier. The facade validates resource,
        # then removes it before forwarding the request.
        cognito_parameters = [
            (name, value)
            for name, value in parameters
            if name != "resource"
        ]

        try:
            metadata = _load_cognito_oidc_metadata(
                self._auth_config.issuer,
                self._auth_config.required_scope,
            )
            endpoint = _required_https_metadata_url(
                metadata,
                "authorization_endpoint",
            )
        except (OSError, ValueError, json.JSONDecodeError):
            LOGGER.exception("Unable to prepare Cognito authorization redirect")
            return self._http_response(
                502,
                {"error": "authorization_server_unavailable"},
            )

        query_string = urlencode(cognito_parameters)
        location = endpoint
        if query_string:
            location = f"{endpoint}?{query_string}"

        return {
            "statusCode": 302,
            "headers": {
                "Location": location,
                "Cache-Control": "no-store",
            },
            "body": "",
            "isBase64Encoded": False,
        }

    def _oauth_token_response(
        self,
        event: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Forward the unchanged public-client token request to Cognito."""

        try:
            request_body = self._cognito_token_request_body(event)
            metadata = _load_cognito_oidc_metadata(
                self._auth_config.issuer,
                self._auth_config.required_scope,
            )
            endpoint = _required_https_metadata_url(
                metadata,
                "token_endpoint",
            )
            request = Request(
                endpoint,
                data=request_body.encode("utf-8"),
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                method="POST",
            )

            try:
                with urlopen(
                    request,
                    timeout=OIDC_FETCH_TIMEOUT_SECONDS,
                ) as response:
                    status_code = response.status
                    payload = json.load(response)
            except HTTPError as error:
                status_code = error.code
                payload = json.loads(
                    error.read().decode("utf-8")
                )

            if not isinstance(payload, dict):
                raise ValueError("Cognito token response must be an object")

        except (OSError, ValueError, json.JSONDecodeError):
            LOGGER.exception("Unable to exchange OAuth code with Cognito")
            return self._http_response(
                502,
                {"error": "token_endpoint_unavailable"},
            )

        return self._http_response(status_code, payload)

    def _cognito_token_request_body(
        self,
        event: Mapping[str, Any],
    ) -> str:
        """Remove MCP-only parameters before forwarding to Cognito."""

        request_body = self._request_body(event)

        if not isinstance(request_body, str):
            raise ValueError("OAuth token body must be form-encoded text")

        return urlencode(
            [
                (name, value)
                for name, value in parse_qsl(
                    request_body,
                    keep_blank_values=True,
                )
                if name != "resource"
            ]
        )

    @staticmethod
    def _encoded_query_string(
        event: Mapping[str, Any],
    ) -> str:
        """Preserve OAuth query parameters across API Gateway versions."""

        raw_query = event.get("rawQueryString")
        if isinstance(raw_query, str) and raw_query:
            return raw_query

        multi_value = event.get("multiValueQueryStringParameters")
        if isinstance(multi_value, Mapping):
            return urlencode(
                {
                    str(key): value
                    for key, value in multi_value.items()
                    if value is not None
                },
                doseq=True,
            )

        single_value = event.get("queryStringParameters")
        if isinstance(single_value, Mapping):
            return urlencode(
                {
                    str(key): str(value)
                    for key, value in single_value.items()
                    if value is not None
                }
            )

        return ""

    def _mcp_http_response(
        self,
        response: McpResponse,
        authorization_header: str | None,
    ) -> dict[str, Any]:
        """Convert McpResponse and add the complete OAuth challenge."""

        headers = dict(response.headers)

        if response.status_code == 401:
            error = (
                "invalid_token"
                if authorization_header
                else None
            )
            headers["WWW-Authenticate"] = (
                self._authorization_challenge(error)
            )

        elif response.status_code == 403:
            headers["WWW-Authenticate"] = (
                self._authorization_challenge(
                    "insufficient_scope"
                )
            )

        return self._http_response(
            response.status_code,
            response.body,
            headers,
        )

    def _authorization_challenge(
        self,
        error: str | None,
    ) -> str:
        """Build the Bearer challenge used by MCP OAuth clients."""

        parameters = [
            (
                'resource_metadata="'
                f'{self._resource_metadata_url}"'
            ),
            f'scope="{self._auth_config.required_scope}"',
        ]

        if error:
            parameters.append(
                f'error="{error}"'
            )

        return "Bearer " + ", ".join(parameters)

    @staticmethod
    def _request_headers(
        event: Mapping[str, Any],
    ) -> dict[str, str]:
        """Normalize API Gateway headers for case-insensitive lookup."""

        raw_headers = event.get("headers")

        if not isinstance(raw_headers, Mapping):
            return {}

        return {
            str(name).lower(): str(value)
            for name, value in raw_headers.items()
            if value is not None
        }

    @staticmethod
    def _http_method(
        event: Mapping[str, Any],
    ) -> str:
        """Read the HTTP method from REST API or HTTP API event formats."""

        method = event.get("httpMethod")

        if isinstance(method, str):
            return method.upper()

        request_context = event.get("requestContext")

        if isinstance(request_context, Mapping):
            http_context = request_context.get("http")

            if isinstance(http_context, Mapping):
                nested_method = http_context.get("method")

                if isinstance(nested_method, str):
                    return nested_method.upper()

        return ""

    @staticmethod
    def _request_path(
        event: Mapping[str, Any],
    ) -> str:
        """Read the public path from REST API or HTTP API events."""

        for field_name in ("rawPath", "path"):
            path = event.get(field_name)

            if isinstance(path, str):
                return path

        request_context = event.get("requestContext")

        if isinstance(request_context, Mapping):
            http_context = request_context.get("http")

            if isinstance(http_context, Mapping):
                path = http_context.get("path")

                if isinstance(path, str):
                    return path

        return ""

    @staticmethod
    def _request_body(
        event: Mapping[str, Any],
    ) -> str | bytes | Mapping[str, Any]:
        """Decode an API Gateway request body, including base64 events."""

        body = event.get("body", "")

        if isinstance(body, Mapping):
            return body

        if not isinstance(body, str):
            raise ValueError(
                "API Gateway body must be text"
            )

        if not event.get("isBase64Encoded", False):
            return body

        try:
            return base64.b64decode(
                body,
                validate=True,
            ).decode("utf-8")

        except (
            binascii.Error,
            UnicodeDecodeError,
        ) as exc:
            raise ValueError(
                "invalid base64 request body"
            ) from exc

    @staticmethod
    def _http_response(
        status_code: int,
        body: Mapping[str, Any] | None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create the proxy response expected by API Gateway."""

        response_headers = {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
        }

        if headers:
            response_headers.update(headers)

        response_body = (
            ""
            if body is None
            else json.dumps(
                body,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )

        return {
            "statusCode": status_code,
            "headers": response_headers,
            "body": response_body,
            "isBase64Encoded": False,
        }

    @staticmethod
    def _build_authorization_server(
        resource: str,
    ) -> str:
        """Return the public origin that hosts the OAuth facade."""

        parsed = urlsplit(resource)

        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError(
                "GHOST MCP resource must be an absolute HTTPS URL"
            )

        return f"{parsed.scheme}://{parsed.netloc}"

    @staticmethod
    def _build_metadata_url(
        resource: str,
    ) -> str:
        """Build the RFC 9728 metadata URL for the MCP resource."""

        parsed = urlsplit(resource)

        if (
            parsed.scheme != "https"
            or not parsed.netloc
        ):
            raise ValueError(
                "GHOST MCP resource must be an absolute HTTPS URL"
            )

        return (
            f"{parsed.scheme}://{parsed.netloc}"
            f"{OAUTH_METADATA_PATH}"
        )


@lru_cache(maxsize=1)
def _build_application() -> RuntimeControlApplication:
    """Create and cache services reused by warm Lambda invocations."""

    runtime_config = (
        RuntimeControlConfig.from_environment()
    )
    auth_config = AuthConfig.from_environment()

    state_store = RuntimeStateStore(
        runtime_config
    )

    controller = Ec2Controller(
        runtime_config,
        state_store,
    )

    token_verifier = CognitoTokenVerifier(
        auth_config
    )

    mcp_server = RuntimeControlMcpServer(
        controller=controller,
        token_verifier=token_verifier,
        allowed_subject=(
            runtime_config.allowed_cognito_subject
        ),
    )

    return RuntimeControlApplication(
        controller=controller,
        mcp_server=mcp_server,
        auth_config=auth_config,
    )


def _is_api_gateway_event(
    event: Mapping[str, Any],
) -> bool:
    """Distinguish HTTP events from scheduled watchdog events."""

    if isinstance(event.get("httpMethod"), str):
        return True

    request_context = event.get("requestContext")

    return (
        isinstance(request_context, Mapping)
        and isinstance(
            request_context.get("http"),
            Mapping,
        )
    )




@lru_cache(maxsize=4)
def _load_cognito_oidc_metadata(
    issuer: str,
    required_scope: str,
) -> dict[str, Any]:
    """Complete Cognito metadata for current MCP OAuth validation."""

    canonical_issuer = issuer.rstrip("/")
    parsed = urlsplit(canonical_issuer)

    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(
            "Cognito issuer must be an absolute HTTPS URL"
        )

    request = Request(
        (
            f"{canonical_issuer}"
            "/.well-known/openid-configuration"
        ),
        headers={"Accept": "application/json"},
    )

    with urlopen(
        request,
        timeout=OIDC_FETCH_TIMEOUT_SECONDS,
    ) as response:
        metadata = json.load(response)

    if not isinstance(metadata, dict):
        raise ValueError(
            "Cognito OIDC metadata must be a JSON object"
        )

    if metadata.get("issuer") != canonical_issuer:
        raise ValueError(
            "Cognito OIDC metadata issuer mismatch"
        )

    required_values = (
        ("code_challenge_methods_supported", "S256"),
        ("token_endpoint_auth_methods_supported", "none"),
        ("grant_types_supported", "authorization_code"),
        ("response_types_supported", "code"),
        ("scopes_supported", required_scope),
    )

    for field_name, value in required_values:
        values = metadata.get(field_name, [])

        if not isinstance(values, list):
            raise ValueError(
                f"Invalid Cognito metadata field: {field_name}"
            )

        metadata[field_name] = list(
            dict.fromkeys([*values, value])
        )

    return metadata


def _required_https_metadata_url(
    metadata: Mapping[str, Any],
    field_name: str,
) -> str:
    """Read and validate one HTTPS endpoint from discovery metadata."""

    value = metadata.get(field_name)
    if not isinstance(value, str):
        raise ValueError(f"Missing metadata endpoint: {field_name}")

    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"Invalid metadata endpoint: {field_name}")

    return value


def lambda_handler(
    event: Mapping[str, Any],
    _context: Any,
) -> dict[str, Any]:
    """AWS Lambda entry point configured in the SAM stack."""

    try:
        return _build_application().handle(event)

    except Exception:
        LOGGER.exception(
            "GHOST runtime-control Lambda invocation failed"
        )

        # Scheduled failures must remain visible to Scheduler retry and alarm
        # handling. HTTP callers receive only a sanitized error response.
        if not _is_api_gateway_event(event):
            raise

        return RuntimeControlApplication._http_response(
            500,
            {"error": "internal_server_error"},
        )
