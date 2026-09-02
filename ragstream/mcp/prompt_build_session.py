"""Keep short-lived state for multi-call GHOST prompt construction.

Main classes:
    PromptBuildSession:
        Captures the exact effective inputs that must survive an intermediate
        clarification or General Skill selection response.
    PromptBuildSessionStore:
        Owns thread-safe creation, retrieval, expiry, and removal.

Main methods:
    create():
        Stores one immutable session and returns its opaque build ID.
    get():
        Returns one owner-scoped live session.
    delete():
        Removes a completed session.

Important notes:
    Sessions are process-local and intentionally short lived. Persistent prompt
    settings remain owned by GhostPromptSettings.
"""

from __future__ import annotations

import copy
import time
import uuid

from dataclasses import dataclass
from threading import Lock
from typing import Any, Callable, Mapping


DEFAULT_SESSION_TTL_SECONDS = 900.0


class PromptBuildSessionError(ValueError):
    """Report an invalid, expired, or owner-mismatched build session."""


@dataclass(frozen=True, slots=True)
class PromptBuildSession:
    """Preserve the effective state of one interrupted prompt build."""

    workflow_state: str
    prompt_text: str
    cleaned_text: str
    cleanup_changed: bool
    effective_settings: Mapping[str, Any]
    project_name: str | None
    ragmem_path: str | None
    general_skill_query: str
    document_context_tokens: int = 1200
    document_max_output_tokens: int = 4000
    memory_context_tokens: int = 1200
    memory_max_output_tokens: int = 3500
    warnings: tuple[str, ...] = ()


class PromptBuildSessionStore:
    """Own short-lived owner-scoped prompt build sessions."""

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_SESSION_TTL_SECONDS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._ttl_seconds = float(ttl_seconds)
        self._clock = clock or time.monotonic
        self._sessions: dict[
            tuple[str, str],
            tuple[float, PromptBuildSession],
        ] = {}
        self._lock = Lock()

    def create(
        self,
        owner_sub: str,
        session: PromptBuildSession,
    ) -> str:
        """Store one immutable snapshot and return an opaque build ID."""
        owner = self._require_text(owner_sub, "owner_sub")
        if not isinstance(session, PromptBuildSession):
            raise TypeError("session must be a PromptBuildSession")
        build_id = uuid.uuid4().hex
        expires_at = self._clock() + self._ttl_seconds
        snapshot = PromptBuildSession(
            workflow_state=session.workflow_state,
            prompt_text=session.prompt_text,
            cleaned_text=session.cleaned_text,
            cleanup_changed=session.cleanup_changed,
            effective_settings=copy.deepcopy(
                dict(session.effective_settings)
            ),
            project_name=session.project_name,
            ragmem_path=session.ragmem_path,
            general_skill_query=session.general_skill_query,
            document_context_tokens=session.document_context_tokens,
            document_max_output_tokens=session.document_max_output_tokens,
            memory_context_tokens=session.memory_context_tokens,
            memory_max_output_tokens=session.memory_max_output_tokens,
            warnings=tuple(session.warnings),
        )
        with self._lock:
            self._sessions[(owner, build_id)] = (
                expires_at,
                snapshot,
            )
        return build_id

    def get(
        self,
        owner_sub: str,
        build_id: str,
    ) -> PromptBuildSession:
        """Return one live session owned by the authenticated subject."""
        owner = self._require_text(owner_sub, "owner_sub")
        identifier = self._require_text(build_id, "build_id")
        with self._lock:
            stored = self._sessions.get((owner, identifier))
            if stored is None:
                raise PromptBuildSessionError(
                    "build_id was not found for the authenticated owner"
                )
            expires_at, session = stored
            if self._clock() >= expires_at:
                self._sessions.pop((owner, identifier), None)
                raise PromptBuildSessionError("build_id has expired")
            return copy.deepcopy(session)

    def delete(self, owner_sub: str, build_id: str) -> None:
        """Remove one session after its prompt build completes."""
        owner = self._require_text(owner_sub, "owner_sub")
        identifier = self._require_text(build_id, "build_id")
        with self._lock:
            self._sessions.pop((owner, identifier), None)

    @staticmethod
    def _require_text(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise PromptBuildSessionError(
                f"{field_name} must be a non-empty string"
            )
        return value.strip()
