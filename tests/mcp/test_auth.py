"""Test Cognito authentication behavior at the GHOST MCP boundary.

The tests create local RS256 tokens and verify that auth.py accepts only valid
Cognito access tokens for the configured GHOST client, resource, and scope.
No AWS connection is required because the Cognito JWKS client is replaced by a
small test mock that returns the locally generated public key.

Main test groups:
    Header tests: Verify extraction and rejection of OAuth Bearer headers.
    Token tests: Verify valid, expired, malformed, and unauthorized tokens.
    Service test: Verify that a Cognito JWKS outage remains distinguishable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.exceptions import PyJWKClientConnectionError

from ragstream.mcp.auth import (
    AuthConfig,
    AuthenticationError,
    AuthenticationServiceError,
    AuthorizationError,
    CognitoTokenVerifier,
    Principal,
    authenticate_request,
    extract_bearer_token,
)


@pytest.fixture(scope="module")
def signing_keys() -> tuple[object, object]:
    """Create one local RSA key pair for all token-verification tests."""

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    return private_key, private_key.public_key()


@pytest.fixture
def auth_config() -> AuthConfig:
    """Provide the fixed Cognito settings expected by GHOST."""

    return AuthConfig(
        issuer=(
            "https://cognito-idp.eu-central-1.amazonaws.com/"
            "eu-central-1_GHOST"
        ),
        app_client_id="ghost-chatgpt-client",
        resource="https://ghost.example.com/mcp",
        required_scope="ghost/invoke",
        leeway_seconds=0,
    )


def _build_token(
    private_key: object,
    config: AuthConfig,
    **claim_overrides: object,
) -> str:
    """Create a signed Cognito-like access token with optional claim changes."""

    now = datetime.now(timezone.utc)

    claims: dict[str, object] = {
        "sub": "user-123",
        "iss": config.issuer,
        "aud": config.resource,
        "exp": int(
            (now + timedelta(minutes=5)).timestamp()
        ),
        "iat": int(now.timestamp()),
        "client_id": config.app_client_id,
        "token_use": "access",
        "scope": f"openid {config.required_scope}",
    }

    claims.update(claim_overrides)

    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={
            "kid": "local-test-key",
        },
    )


def _build_verifier(
    config: AuthConfig,
    public_key: object,
) -> CognitoTokenVerifier:
    """Create a verifier whose JWKS boundary returns the local public key."""

    jwks_client = Mock()

    jwks_client.get_signing_key_from_jwt.return_value = (
        SimpleNamespace(
            key=public_key,
        )
    )

    return CognitoTokenVerifier(
        config,
        jwks_client=jwks_client,
    )


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "Basic abc",
        "Bearer",
        "Bearer   ",
    ],
)
def test_extract_bearer_token_rejects_missing_token(
    header: str | None,
) -> None:
    with pytest.raises(
        AuthenticationError,
        match="missing bearer token",
    ):
        extract_bearer_token(header)


def test_extract_bearer_token_accepts_case_insensitive_scheme() -> None:
    assert (
        extract_bearer_token(
            "bearer token-value"
        )
        == "token-value"
    )


def test_valid_cognito_access_token_returns_principal(
    signing_keys: tuple[object, object],
    auth_config: AuthConfig,
) -> None:
    private_key, public_key = signing_keys

    verifier = _build_verifier(
        auth_config,
        public_key,
    )

    token = _build_token(
        private_key,
        auth_config,
    )

    principal = authenticate_request(
        f"Bearer {token}",
        verifier,
    )

    expected_expiration = jwt.decode(
        token,
        options={
            "verify_signature": False,
        },
    )["exp"]

    assert principal == Principal(
        subject="user-123",
        issuer=auth_config.issuer,
        client_id=auth_config.app_client_id,
        resource=auth_config.resource,
        scopes=(
            "openid",
            "ghost/invoke",
        ),
        expires_at=expected_expiration,
    )


def test_expired_token_is_rejected(
    signing_keys: tuple[object, object],
    auth_config: AuthConfig,
) -> None:
    private_key, public_key = signing_keys

    verifier = _build_verifier(
        auth_config,
        public_key,
    )

    expired = int(
        (
            datetime.now(timezone.utc)
            - timedelta(minutes=1)
        ).timestamp()
    )

    token = _build_token(
        private_key,
        auth_config,
        exp=expired,
    )

    with pytest.raises(
        AuthenticationError,
        match="expired bearer token",
    ):
        verifier.verify_bearer_token(token)


def test_wrong_app_client_is_rejected(
    signing_keys: tuple[object, object],
    auth_config: AuthConfig,
) -> None:
    private_key, public_key = signing_keys

    verifier = _build_verifier(
        auth_config,
        public_key,
    )

    token = _build_token(
        private_key,
        auth_config,
        client_id="another-client",
    )

    with pytest.raises(
        AuthenticationError,
        match="another OAuth client",
    ):
        verifier.verify_bearer_token(token)


def test_id_token_is_rejected(
    signing_keys: tuple[object, object],
    auth_config: AuthConfig,
) -> None:
    private_key, public_key = signing_keys

    verifier = _build_verifier(
        auth_config,
        public_key,
    )

    token = _build_token(
        private_key,
        auth_config,
        token_use="id",
    )

    with pytest.raises(
        AuthenticationError,
        match="not a Cognito access token",
    ):
        verifier.verify_bearer_token(token)


def test_missing_ghost_scope_is_forbidden(
    signing_keys: tuple[object, object],
    auth_config: AuthConfig,
) -> None:
    private_key, public_key = signing_keys

    verifier = _build_verifier(
        auth_config,
        public_key,
    )

    token = _build_token(
        private_key,
        auth_config,
        scope="openid profile",
    )

    with pytest.raises(
        AuthorizationError,
        match="required GHOST scope",
    ):
        verifier.verify_bearer_token(token)


def test_wrong_resource_audience_is_rejected(
    signing_keys: tuple[object, object],
    auth_config: AuthConfig,
) -> None:
    private_key, public_key = signing_keys

    verifier = _build_verifier(
        auth_config,
        public_key,
    )

    token = _build_token(
        private_key,
        auth_config,
        aud="https://another.example.com/mcp",
    )

    with pytest.raises(
        AuthenticationError,
        match="invalid bearer token",
    ):
        verifier.verify_bearer_token(token)


def test_invalid_signature_is_rejected(
    signing_keys: tuple[object, object],
    auth_config: AuthConfig,
) -> None:
    _, trusted_public_key = signing_keys

    untrusted_private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    verifier = _build_verifier(
        auth_config,
        trusted_public_key,
    )

    token = _build_token(
        untrusted_private_key,
        auth_config,
    )

    with pytest.raises(
        AuthenticationError,
        match="invalid bearer token",
    ):
        verifier.verify_bearer_token(token)


def test_jwks_connection_failure_is_service_error(
    auth_config: AuthConfig,
) -> None:
    jwks_client = Mock()

    jwks_client.get_signing_key_from_jwt.side_effect = (
        PyJWKClientConnectionError(
            "JWKS unavailable"
        )
    )

    verifier = CognitoTokenVerifier(
        auth_config,
        jwks_client=jwks_client,
    )

    with pytest.raises(
        AuthenticationServiceError,
        match="temporarily unavailable",
    ):
        verifier.verify_bearer_token(
            "header.payload.signature"
        )