"""Tests for owner-scoped prompt build sessions."""

from __future__ import annotations

import pytest

from ragstream.mcp.prompt_build_session import (
    PromptBuildSession,
    PromptBuildSessionError,
    PromptBuildSessionStore,
)


def _session() -> PromptBuildSession:
    return PromptBuildSession(
        workflow_state="selection_required",
        prompt_text="Task",
        cleaned_text="Task",
        cleanup_changed=False,
        effective_settings={"memory_retrieval": True},
        project_name="Project",
        ragmem_path="/memory.ragmem",
        general_skill_query="query",
    )


def test_session_is_owner_scoped_and_deleted_after_completion() -> None:
    store = PromptBuildSessionStore()
    build_id = store.create("owner-a", _session())

    assert store.get("owner-a", build_id).project_name == "Project"
    with pytest.raises(PromptBuildSessionError, match="not found"):
        store.get("owner-b", build_id)

    store.delete("owner-a", build_id)
    with pytest.raises(PromptBuildSessionError, match="not found"):
        store.get("owner-a", build_id)


def test_session_expires_deterministically() -> None:
    now = [10.0]
    store = PromptBuildSessionStore(
        ttl_seconds=5.0,
        clock=lambda: now[0],
    )
    build_id = store.create("owner", _session())
    now[0] = 15.0

    with pytest.raises(PromptBuildSessionError, match="expired"):
        store.get("owner", build_id)
