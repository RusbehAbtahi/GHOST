"""Authenticate GHOST MCP requests with Amazon Cognito access tokens.

The module extracts an OAuth Bearer token, verifies its Cognito signature and
claims, and returns a trusted user identity. It does not implement the Cognito
login flow or generate HTTP responses; those responsibilities remain with
Cognito and the MCP server boundary.

Main classes:
    AuthConfig: Holds the fixed Cognito and GHOST OAuth settings.
    Principal: Represents the authenticated Cognito user trusted by GHOST.
    CognitoTokenVerifier: Verifies one Cognito access token against JWKS.

Main functions:
    extract_bearer_token(): Reads the token from an Authorization header.
    authenticate_request(): Converts an Authorization header into a Principal.

Important dependency:
    PyJWT[crypto]>=2.10,<3
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

import jwt
from jwt import PyJWKClient
from jwt.exceptions import (
    ExpiredSignatureError,
    InvalidTokenError,
    PyJWKClientConnectionError,
    PyJWKClientError,
)


class AuthenticationError(Exception):
    """The Bearer token is missing, malformed, expired, or invalid."""


class AuthorizationError(Exception):
    """The token is valid but does not grant the required GHOST permission."""


class AuthenticationServiceError(Exception):
    """Cognito public signing keys are temporarily unavailable."""


@dataclass(frozen=True)
class AuthConfig:
    """Configuration required to validate Cognito access tokens for GHOST."""

    issuer: str
    app_client_id: str
    resource: str
    required_scope: str
    leeway_seconds: int = 30

    @property
    def jwks_url(self) -> str:
        """Return the standard JWKS endpoint of the configured user pool."""

        return f"{self.issuer.rstrip('/')}/.well-known/jwks.json"

    @classmethod
    def from_environment(
        cls,
        env: Mapping[str, str] | None = None,
    ) -> "AuthConfig":
        """Load the fixed Cognito settings from deployment variables."""

        values = os.environ if env is None else env
        names = {
            "issuer": "GHOST_COGNITO_ISSUER",
            "app_client_id": "GHOST_COGNITO_APP_CLIENT_ID",
            "resource": "GHOST_MCP_RESOURCE",
            "required_scope": "GHOST_COGNITO_REQUIRED_SCOPE",
        }
        settings = {
            field: str(values.get(variable) or "").strip()
            for field, variable in names.items()
        }
        missing = [
            names[field]
            for field, value in settings.items()
            if not value
        ]
        if missing:
            raise ValueError(
                "missing required authentication setting: "
                + ", ".join(missing)
            )

        try:
            leeway_seconds = int(
                values.get("GHOST_COGNITO_LEEWAY_SECONDS", "30")
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "GHOST_COGNITO_LEEWAY_SECONDS must be an integer"
            ) from exc

        if leeway_seconds < 0:
            raise ValueError(
                "GHOST_COGNITO_LEEWAY_SECONDS cannot be negative"
            )

        return cls(
            issuer=settings["issuer"].rstrip("/"),
            app_client_id=settings["app_client_id"],
            resource=settings["resource"],
            required_scope=settings["required_scope"],
            leeway_seconds=leeway_seconds,
        )


@dataclass(frozen=True)
class Principal:
    """Authenticated Cognito identity that downstream GHOST code may trust."""

    subject: str
    issuer: str
    client_id: str
    resource: str
    scopes: tuple[str, ...]
    expires_at: int


class CognitoTokenVerifier:
    """Verify Cognito access-token signatures, claims, audience, and scope."""

    def __init__(
        self,
        config: AuthConfig,
        jwks_client: PyJWKClient | None = None,
    ) -> None:
        if not config.issuer.startswith("https://"):
            raise ValueError("Cognito issuer must use HTTPS")

        if (
            not config.app_client_id
            or not config.resource
            or not config.required_scope
        ):
            raise ValueError(
                "Cognito authentication configuration is incomplete"
            )

        self._config = config
        self._jwks_client = jwks_client or PyJWKClient(
            config.jwks_url
        )

    def verify_bearer_token(self, token: str) -> Principal:
        """Validate one token and return its authenticated Cognito identity."""

        compact_token = (token or "").strip()
        if not compact_token:
            raise AuthenticationError("missing bearer token")

        claims = self._decode_token(compact_token)

        subject = str(claims.get("sub") or "").strip()
        client_id = str(claims.get("client_id") or "").strip()
        token_use = str(claims.get("token_use") or "").strip()
        scopes = tuple(
            str(claims.get("scope") or "").split()
        )

        if not subject:
            raise AuthenticationError(
                "bearer token has no subject"
            )

        if token_use != "access":
            raise AuthenticationError(
                "token is not a Cognito access token"
            )

        if client_id != self._config.app_client_id:
            raise AuthenticationError(
                "token was issued for another OAuth client"
            )

        if self._config.required_scope not in scopes:
            raise AuthorizationError(
                "token is missing the required GHOST scope"
            )

        return Principal(
            subject=subject,
            issuer=self._config.issuer,
            client_id=client_id,
            resource=self._config.resource,
            scopes=scopes,
            expires_at=int(claims["exp"]),
        )

    def _decode_token(
        self,
        token: str,
    ) -> dict[str, object]:
        """Resolve the Cognito key and verify standard JWT claims."""

        try:
            signing_key = (
                self._jwks_client.get_signing_key_from_jwt(token)
            )

            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=self._config.issuer,
                audience=self._config.resource,
                leeway=self._config.leeway_seconds,
                options={
                    "require": [
                        "sub",
                        "iss",
                        "aud",
                        "exp",
                        "iat",
                        "client_id",
                        "token_use",
                    ]
                },
            )

        except PyJWKClientConnectionError as exc:
            raise AuthenticationServiceError(
                "Cognito signing keys are temporarily unavailable"
            ) from exc

        except ExpiredSignatureError as exc:
            raise AuthenticationError(
                "expired bearer token"
            ) from exc

        except (
            PyJWKClientError,
            InvalidTokenError,
            TypeError,
            ValueError,
        ) as exc:
            raise AuthenticationError(
                "invalid bearer token"
            ) from exc

        return dict(claims)


def extract_bearer_token(
    authorization_header: str | None,
) -> str:
    """Extract one OAuth Bearer token from an Authorization header."""

    scheme, separator, token = (
        authorization_header or ""
    ).strip().partition(" ")

    if (
        not separator
        or scheme.lower() != "bearer"
        or not token.strip()
    ):
        raise AuthenticationError(
            "missing bearer token"
        )

    return token.strip()


def authenticate_request(
    authorization_header: str | None,
    verifier: CognitoTokenVerifier,
) -> Principal:
    """Authenticate an HTTP header through the Cognito verifier."""

    token = extract_bearer_token(
        authorization_header
    )

    return verifier.verify_bearer_token(
        token
    )