"""OAuth bearer-token validation boundary for the MCP resource server."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Protocol, Sequence


class AuthenticationError(Exception):
    """Credentials were absent or could not be authenticated."""


class AuthorizationError(Exception):
    """Credentials are valid but not authorized for this resource/tool."""


@dataclass(frozen=True)
class AuthConfig:
    issuer: str
    resource: str
    required_scopes: tuple[str, ...] = ()
    leeway_seconds: int = 0


@dataclass(frozen=True)
class Principal:
    subject: str
    issuer: str
    resource: str
    scopes: tuple[str, ...]
    expires_at: int | None = None


class TokenVerifier(Protocol):
    def verify_bearer_token(self, token: str) -> Principal:
        """Validate a bearer token and return the authenticated principal."""


class ConfigurableTokenVerifier:
    """Validates decoded token claims supplied by an injected decoder."""

    def __init__(self, config: AuthConfig, decoder) -> None:
        self._config = config
        self._decoder = decoder

    def verify_bearer_token(self, token: str) -> Principal:
        if not token:
            raise AuthenticationError("missing bearer token")
        try:
            claims = dict(self._decoder(token))
        except Exception as exc:  # noqa: BLE001 - intentionally sanitized boundary
            raise AuthenticationError("invalid bearer token") from exc

        subject = str(claims.get("sub") or "").strip()
        issuer = str(claims.get("iss") or "").strip()
        resource = str(claims.get("aud") or claims.get("resource") or "").strip()
        scopes = _parse_scopes(claims.get("scope") or claims.get("scp") or ())
        expires_at = claims.get("exp")

        if not subject:
            raise AuthenticationError("invalid bearer token")
        if issuer != self._config.issuer:
            raise AuthenticationError("invalid bearer token")
        if resource != self._config.resource:
            raise AuthorizationError("token is not authorized for this resource")
        if expires_at is not None:
            try:
                exp_int = int(expires_at)
            except (TypeError, ValueError) as exc:
                raise AuthenticationError("invalid bearer token") from exc
            now = int(datetime.now(timezone.utc).timestamp())
            if exp_int + self._config.leeway_seconds < now:
                raise AuthenticationError("expired bearer token")
            expires_at = exp_int
        missing = set(self._config.required_scopes).difference(scopes)
        if missing:
            raise AuthorizationError("token is missing required scope")
        return Principal(subject, issuer, resource, tuple(scopes), expires_at)


def extract_bearer_token(authorization_header: str | None) -> str:
    value = (authorization_header or "").strip()
    if not value.lower().startswith("bearer "):
        raise AuthenticationError("missing bearer token")
    token = value[7:].strip()
    if not token:
        raise AuthenticationError("missing bearer token")
    return token


def authenticate_request(authorization_header: str | None, verifier: TokenVerifier) -> Principal:
    return verifier.verify_bearer_token(extract_bearer_token(authorization_header))


def _parse_scopes(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item for item in value.split() if item)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return tuple(str(item) for item in value if str(item).strip())
    return ()
