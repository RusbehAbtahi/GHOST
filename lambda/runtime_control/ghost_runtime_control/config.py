# Requirements: GHOST-MCP-RUNTIME-FIXED-TARGET,
# GHOST-MCP-RUNTIME-PROFILE-INPUT, GHOST-MCP-RUNTIME-IDLE-INPUT,
# GHOST-MCP-RUNTIME-AUTH, GHOST-MCP-RUNTIME-NO-GENERAL-AWS-CONTROL

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse


_INSTANCE_ID_PATTERN = re.compile(r"^i-[0-9a-fA-F]+$")

_PROFILE_1 = 1
_PROFILE_2 = 2
_PROFILE_1_INSTANCE_TYPE = "t3.medium"
_PROFILE_2_INSTANCE_TYPE = "m7i-flex.xlarge"

_DEFAULT_PROFILE = _PROFILE_1
_DEFAULT_IDLE_TIMEOUT_MINUTES = 20
_MIN_IDLE_TIMEOUT_MINUTES = 10
_MAX_IDLE_TIMEOUT_MINUTES = 120


class ConfigurationError(ValueError):
    """Raised when the deployed Lambda configuration is incomplete or invalid."""


@dataclass(frozen=True, slots=True)
class RuntimeControlConfig:
    """Validated configuration shared by all Runtime Control Lambda modules."""

    managed_instance_id: str

    profile_1_instance_type: str
    profile_2_instance_type: str
    default_profile: int

    default_idle_timeout_minutes: int
    min_idle_timeout_minutes: int
    max_idle_timeout_minutes: int

    readiness_url: str
    startup_wait_seconds: int

    cognito_issuer: str
    cognito_app_client_id: str
    cognito_required_scope: str
    protected_resource: str
    allowed_cognito_subject: str

    ssm_idle_timeout_parameter: str
    ssm_last_activity_parameter: str
    ssm_active_calls_parameter: str
    ssm_runtime_profile_parameter: str

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "RuntimeControlConfig":
        """Create validated configuration from Lambda environment variables."""

        source = os.environ if environ is None else environ

        profile_1_instance_type = _required(
            source,
            "GHOST_PROFILE_1_INSTANCE_TYPE",
        )
        profile_2_instance_type = _required(
            source,
            "GHOST_PROFILE_2_INSTANCE_TYPE",
        )

        # These are deliberately fixed requirements, not caller-selectable
        # or freely configurable AWS instance types.
        if profile_1_instance_type != _PROFILE_1_INSTANCE_TYPE:
            raise ConfigurationError(
                "GHOST_PROFILE_1_INSTANCE_TYPE must be "
                f"{_PROFILE_1_INSTANCE_TYPE!r}."
            )

        if profile_2_instance_type != _PROFILE_2_INSTANCE_TYPE:
            raise ConfigurationError(
                "GHOST_PROFILE_2_INSTANCE_TYPE must be "
                f"{_PROFILE_2_INSTANCE_TYPE!r}."
            )

        default_profile = _integer(
            source,
            "GHOST_DEFAULT_PROFILE",
            minimum=_PROFILE_1,
            maximum=_PROFILE_2,
        )
        if default_profile != _DEFAULT_PROFILE:
            raise ConfigurationError(
                f"GHOST_DEFAULT_PROFILE must be {_DEFAULT_PROFILE}."
            )

        default_idle_timeout_minutes = _integer(
            source,
            "GHOST_DEFAULT_IDLE_TIMEOUT_MINUTES",
            minimum=_MIN_IDLE_TIMEOUT_MINUTES,
            maximum=_MAX_IDLE_TIMEOUT_MINUTES,
        )
        if default_idle_timeout_minutes != _DEFAULT_IDLE_TIMEOUT_MINUTES:
            raise ConfigurationError(
                "GHOST_DEFAULT_IDLE_TIMEOUT_MINUTES must be "
                f"{_DEFAULT_IDLE_TIMEOUT_MINUTES}."
            )

        min_idle_timeout_minutes = _integer(
            source,
            "GHOST_MIN_IDLE_TIMEOUT_MINUTES",
            minimum=_MIN_IDLE_TIMEOUT_MINUTES,
            maximum=_MIN_IDLE_TIMEOUT_MINUTES,
        )
        max_idle_timeout_minutes = _integer(
            source,
            "GHOST_MAX_IDLE_TIMEOUT_MINUTES",
            minimum=_MAX_IDLE_TIMEOUT_MINUTES,
            maximum=_MAX_IDLE_TIMEOUT_MINUTES,
        )

        return cls(
            managed_instance_id=_instance_id(source),
            profile_1_instance_type=profile_1_instance_type,
            profile_2_instance_type=profile_2_instance_type,
            default_profile=default_profile,
            default_idle_timeout_minutes=default_idle_timeout_minutes,
            min_idle_timeout_minutes=min_idle_timeout_minutes,
            max_idle_timeout_minutes=max_idle_timeout_minutes,
            readiness_url=_https_url(
                source,
                "GHOST_READINESS_URL",
            ),
            startup_wait_seconds=_integer(
                source,
                "GHOST_STARTUP_WAIT_SECONDS",
                minimum=60,
                maximum=300,
            ),
            cognito_issuer=_https_url(
                source,
                "GHOST_COGNITO_ISSUER",
            ),
            cognito_app_client_id=_required(
                source,
                "GHOST_COGNITO_APP_CLIENT_ID",
            ),
            cognito_required_scope=_scope(source),
            protected_resource=_https_url(
                source,
                "GHOST_RUNTIME_CONTROL_RESOURCE",
                required_path="/mcp",
            ),
            allowed_cognito_subject=_required(
                source,
                "GHOST_ALLOWED_COGNITO_SUBJECT",
            ),
            ssm_idle_timeout_parameter=_ssm_parameter_name(
                source,
                "GHOST_SSM_IDLE_TIMEOUT_PARAMETER",
            ),
            ssm_last_activity_parameter=_ssm_parameter_name(
                source,
                "GHOST_SSM_LAST_ACTIVITY_PARAMETER",
            ),
            ssm_active_calls_parameter=_ssm_parameter_name(
                source,
                "GHOST_SSM_ACTIVE_CALLS_PARAMETER",
            ),
            ssm_runtime_profile_parameter=_ssm_parameter_name(
                source,
                "GHOST_SSM_RUNTIME_PROFILE_PARAMETER",
            ),
        )

    def instance_type_for(self, profile: int) -> str:
        """Return the approved EC2 type for profile 1 or profile 2."""

        if profile == _PROFILE_1:
            return self.profile_1_instance_type

        if profile == _PROFILE_2:
            return self.profile_2_instance_type

        raise ValueError(
            f"Unsupported runtime profile {profile!r}; only 1 and 2 are valid."
        )

    @property
    def cognito_jwks_url(self) -> str:
        """Return the public Cognito key-set URL used for JWT verification."""

        return f"{self.cognito_issuer}/.well-known/jwks.json"


def _required(source: Mapping[str, str], name: str) -> str:
    """Read a required non-empty environment variable without logging its value."""

    value = source.get(name, "").strip()
    if not value:
        raise ConfigurationError(f"Missing required environment variable: {name}.")

    return value


def _integer(
    source: Mapping[str, str],
    name: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    """Read an integer environment variable and enforce its inclusive range."""

    raw_value = _required(source, name)

    try:
        value = int(raw_value)
    except ValueError as error:
        raise ConfigurationError(
            f"{name} must be an integer, received {raw_value!r}."
        ) from error

    if not minimum <= value <= maximum:
        raise ConfigurationError(
            f"{name} must be between {minimum} and {maximum}, received {value}."
        )

    return value


def _instance_id(source: Mapping[str, str]) -> str:
    """Read and validate the one fixed EC2 instance identifier."""

    instance_id = _required(source, "GHOST_MANAGED_INSTANCE_ID")

    if not _INSTANCE_ID_PATTERN.fullmatch(instance_id):
        raise ConfigurationError(
            "GHOST_MANAGED_INSTANCE_ID must be a valid EC2 instance ID."
        )

    return instance_id


def _https_url(
    source: Mapping[str, str],
    name: str,
    *,
    required_path: str | None = None,
) -> str:
    """Read an HTTPS URL and reject fragments or query-string configuration."""

    value = _required(source, name).rstrip("/")
    parsed = urlparse(value)

    if parsed.scheme != "https" or not parsed.netloc:
        raise ConfigurationError(f"{name} must be a complete HTTPS URL.")

    if parsed.query or parsed.fragment:
        raise ConfigurationError(
            f"{name} must not contain a query string or fragment."
        )

    if required_path is not None and parsed.path != required_path:
        raise ConfigurationError(
            f"{name} must use the path {required_path!r}."
        )

    return value


def _scope(source: Mapping[str, str]) -> str:
    """Read one required OAuth scope."""

    scope = _required(source, "GHOST_COGNITO_REQUIRED_SCOPE")

    if any(character.isspace() for character in scope):
        raise ConfigurationError(
            "GHOST_COGNITO_REQUIRED_SCOPE must contain exactly one scope."
        )

    return scope


def _ssm_parameter_name(source: Mapping[str, str], name: str) -> str:
    """Read an SSM Parameter Store path used by the runtime watchdog state."""

    parameter_name = _required(source, name)

    if not parameter_name.startswith("/") or " " in parameter_name:
        raise ConfigurationError(
            f"{name} must be an SSM parameter path beginning with '/'."
        )

    return parameter_name

