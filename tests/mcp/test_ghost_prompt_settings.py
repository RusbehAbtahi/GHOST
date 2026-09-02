"""Tests for owner-scoped GHOST prompt-builder settings."""

from __future__ import annotations

import json
import threading

import pytest

from ragstream.mcp.ghost_prompt_settings import (
    DEFAULT_PROMPT_SETTINGS,
    ENRICHMENT_FLAG_KEYS,
    GhostPromptSettings,
    PromptSettingsError,
)


def test_defaults_are_created_lazily_and_scoped_by_owner(tmp_path) -> None:
    settings = GhostPromptSettings(tmp_path)

    first = settings.show("owner-one")
    second = settings.set(
        "owner-two",
        {"document_retrieval": True},
    )

    assert first == DEFAULT_PROMPT_SETTINGS
    assert second["document_retrieval"] is True
    assert settings.show("owner-one")["document_retrieval"] is False
    path = settings.settings_path("owner-one")
    assert json.loads(path.read_text(encoding="utf-8")) == first


def test_effective_overrides_do_not_mutate_persistent_settings(tmp_path) -> None:
    settings = GhostPromptSettings(tmp_path)
    settings.set(
        "owner",
        {
            "default_project_name": "Project A",
            "memory_retrieval": True,
        },
    )

    effective = settings.effective(
        "owner",
        {
            "memory_retrieval": False,
            "memory_recency_enabled": False,
        },
    )

    assert effective["memory_retrieval"] is False
    assert effective["memory_recency_enabled"] is False
    persisted = settings.show("owner")
    assert persisted["memory_retrieval"] is True
    assert persisted["memory_recency_enabled"] is True


def test_all_off_preserves_paths_and_recency_then_reset_restores_defaults(
    tmp_path,
) -> None:
    settings = GhostPromptSettings(tmp_path)
    settings.set(
        "owner",
        {
            **{key: True for key in ENRICHMENT_FLAG_KEYS},
            "memory_recency_enabled": False,
            "default_project_name": "Project",
            "default_ragmem_path": "/tmp/example.ragmem",
        },
    )

    disabled = settings.all_off("owner")

    assert all(disabled[key] is False for key in ENRICHMENT_FLAG_KEYS)
    assert disabled["memory_recency_enabled"] is False
    assert disabled["default_project_name"] == "Project"
    assert disabled["default_ragmem_path"] == "/tmp/example.ragmem"
    assert settings.reset("owner") == DEFAULT_PROMPT_SETTINGS


def test_invalid_owner_and_settings_are_rejected(tmp_path) -> None:
    settings = GhostPromptSettings(tmp_path)

    with pytest.raises(PromptSettingsError):
        settings.show("../owner")
    with pytest.raises(PromptSettingsError):
        settings.set("owner", {"unknown": True})
    with pytest.raises(PromptSettingsError):
        settings.set("owner", {"prompt_shaping": "yes"})


def test_concurrent_updates_never_leave_partial_json(tmp_path) -> None:
    settings = GhostPromptSettings(tmp_path)
    errors: list[BaseException] = []

    def update(index: int) -> None:
        try:
            settings.set(
                "owner",
                {
                    "default_project_name": f"Project-{index}",
                    "memory_recency_enabled": bool(index % 2),
                },
            )
            settings.show("owner")
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    threads = [
        threading.Thread(target=update, args=(index,))
        for index in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert errors == []
    assert all(not thread.is_alive() for thread in threads)
    stored = json.loads(
        settings.settings_path("owner").read_text(encoding="utf-8")
    )
    assert set(stored) == set(DEFAULT_PROMPT_SETTINGS)

