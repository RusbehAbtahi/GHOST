"""Tests for the thin Prompt Show, Run, and Settings MCP adapters."""

from __future__ import annotations

from typing import Any

from ragstream.mcp.ghost_prompt_builder import (
    STATUS_CLARIFICATION_REQUIRED,
    STATUS_COMPLETE,
    STATUS_SELECTION_REQUIRED,
)
from ragstream.mcp.ghost_prompt_run import (
    MODE_RUN,
    GhostPromptRunTool,
)
from ragstream.mcp.ghost_prompt_settings import (
    DEFAULT_PROMPT_SETTINGS,
    GhostPromptSettings,
    GhostPromptSettingsTool,
)
from ragstream.mcp.ghost_prompt_show import (
    DISPLAY_POLICY_EXECUTE_ONCE,
    DISPLAY_POLICY_NOT_APPLICABLE,
    DISPLAY_POLICY_VERBATIM,
    MODE_SHOW,
    GhostPromptShowTool,
)


class RecordingBuilder:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def build(self, **arguments: Any) -> dict[str, Any]:
        self.calls.append(arguments)
        return self.result


def built_result(
    *,
    status: str = STATUS_COMPLETE,
    prompt: str = "FINAL PROMPT",
    clarification_question: str = "",
    candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "prompt": prompt,
        "clarification_question": clarification_question,
        "general_skill_candidates": candidates or [],
        "receipt": {"status": status},
    }


def test_prompt_argument_aliases_are_normalized_before_builder_call() -> None:
    builder = RecordingBuilder(built_result())

    result = GhostPromptShowTool(builder).call_sanitized(
        "owner",
        {
            "prompt": "Do the task",
            "document_project_name": "Project",
        },
    )

    assert result.isError is False
    assert builder.calls == [
        {
            "owner_sub": "owner",
            "prompt_text": "Do the task",
            "project_name": "Project",
        }
    ]


def test_prompt_token_controls_are_forwarded_to_builder() -> None:
    builder = RecordingBuilder(built_result())

    result = GhostPromptShowTool(builder).call_sanitized(
        "owner",
        {
            "prompt_text": "Do the task",
            "document_context_tokens": 900,
            "document_max_output_tokens": 3600,
            "memory_context_tokens": 800,
            "memory_max_output_tokens": 3200,
        },
    )

    assert result.isError is False
    assert builder.calls == [
        {
            "owner_sub": "owner",
            "prompt_text": "Do the task",
            "document_context_tokens": 900,
            "document_max_output_tokens": 3600,
            "memory_context_tokens": 800,
            "memory_max_output_tokens": 3200,
        }
    ]


def test_conflicting_prompt_alias_is_rejected() -> None:
    builder = RecordingBuilder(built_result())

    result = GhostPromptShowTool(builder).call_sanitized(
        "owner",
        {"prompt": "A", "prompt_text": "B"},
    )

    assert result.isError is True
    assert builder.calls == []


def test_single_general_skill_candidate_is_continued_automatically() -> None:
    class TwoStepBuilder:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def build(self, **arguments: Any) -> dict[str, Any]:
            self.calls.append(arguments)
            if len(self.calls) == 1:
                result = built_result(
                    status=STATUS_SELECTION_REQUIRED,
                    prompt="",
                    candidates=[{"skill_id": "skill-1", "skill_title": "Skill"}],
                )
                result["receipt"] = {
                    "status": STATUS_SELECTION_REQUIRED,
                    "build_id": "build-1",
                }
                return result
            return built_result(prompt="FINAL WITH SKILL")

    builder = TwoStepBuilder()
    result = GhostPromptShowTool(builder).call_sanitized(
        "owner",
        {"prompt_text": "task"},
    )

    assert result.isError is False
    assert result.structuredContent["status"] == STATUS_COMPLETE
    assert result.structuredContent["prompt"] == "FINAL WITH SKILL"
    assert builder.calls == [
        {"owner_sub": "owner", "prompt_text": "task"},
        {
            "owner_sub": "owner",
            "build_id": "build-1",
            "general_skill_ids": ["skill-1"],
        },
    ]


def test_show_and_run_share_builder_input_but_return_distinct_modes() -> None:
    show_builder = RecordingBuilder(built_result())
    run_builder = RecordingBuilder(built_result())
    arguments = {
        "prompt_text": "Do the task",
        "project_name": "Project",
        "ragmem_path": "/memory/main.ragmem",
        "general_skill_ids": ["skill-1"],
        "setting_overrides": {"memory_recency_enabled": False},
    }

    show = GhostPromptShowTool(show_builder).call_sanitized(
        "owner",
        arguments,
    )
    run = GhostPromptRunTool(run_builder).call_sanitized(
        "owner",
        arguments,
    )

    assert show.isError is False
    assert run.isError is False
    assert show.structuredContent["mode"] == MODE_SHOW
    assert run.structuredContent["mode"] == MODE_RUN
    assert show.structuredContent["prompt"] == "FINAL PROMPT"
    assert run.structuredContent["prompt"] == "FINAL PROMPT"
    assert (
        show.structuredContent["display_policy"]
        == DISPLAY_POLICY_VERBATIM
    )
    assert (
        run.structuredContent["display_policy"]
        == DISPLAY_POLICY_EXECUTE_ONCE
    )
    assert show.content[0]["text"] == "FINAL PROMPT"
    assert show_builder.calls == run_builder.calls
    assert show_builder.calls[0]["owner_sub"] == "owner"



def test_show_returns_complete_prompt_verbatim_without_placeholders() -> None:
    prompt = (
        "TASK\n"
        "## Retrieved Document Context\nFULL DOCUMENT\n"
        "## Memory Context\nFULL MEMORY\n"
        "## General Skill Instructions\nFULL SKILL"
    )
    result = GhostPromptShowTool(
        RecordingBuilder(built_result(prompt=prompt))
    ).call_sanitized("owner", {"prompt_text": "task"})

    assert result.isError is False
    assert result.structuredContent["status"] == STATUS_COMPLETE
    assert (
        result.structuredContent["display_policy"]
        == DISPLAY_POLICY_VERBATIM
    )
    assert result.structuredContent["prompt"] == prompt
    assert result.content == [{"type": "text", "text": prompt}]

def test_clarification_is_returned_without_a_final_prompt() -> None:
    builder = RecordingBuilder(
        built_result(
            status=STATUS_CLARIFICATION_REQUIRED,
            prompt="",
            clarification_question="Which project did you mean?",
        )
    )

    result = GhostPromptRunTool(builder).call_sanitized(
        "owner",
        {"prompt_text": "unclear"},
    )

    assert result.isError is False
    assert result.structuredContent["status"] == STATUS_CLARIFICATION_REQUIRED
    assert (
        result.structuredContent["display_policy"]
        == DISPLAY_POLICY_NOT_APPLICABLE
    )
    assert result.content[0]["text"] == "Which project did you mean?"


def test_general_skill_selection_is_returned_before_completion() -> None:
    candidates = [{"skill_id": "skill-1", "skill_title": "Skill"}]
    builder = RecordingBuilder(
        built_result(
            status=STATUS_SELECTION_REQUIRED,
            prompt="",
            candidates=candidates,
        )
    )

    result = GhostPromptShowTool(builder).call_sanitized(
        "owner",
        {"prompt_text": "task"},
    )

    assert result.isError is False
    assert result.structuredContent["status"] == STATUS_SELECTION_REQUIRED
    assert result.structuredContent["general_skill_candidates"] == candidates


def test_invalid_prompt_input_is_sanitized_before_builder_call() -> None:
    builder = RecordingBuilder(built_result())

    result = GhostPromptShowTool(builder).call_sanitized(
        "owner",
        {"prompt_text": " ", "extra": True},
    )

    assert result.isError is True
    assert result.structuredContent == {}
    assert builder.calls == []


def test_settings_tool_show_set_all_off_and_reset(tmp_path) -> None:
    settings = GhostPromptSettings(tmp_path)
    tool = GhostPromptSettingsTool(settings)

    shown = tool.call_sanitized("owner", {"action": "show"})
    changed = tool.call_sanitized(
        "owner",
        {
            "action": "set",
            "updates": {
                "memory_retrieval": True,
                "memory_recency_enabled": False,
                "default_ragmem_path": "/memory/collection.ragmem",
            },
        },
    )
    disabled = tool.call_sanitized("owner", {"action": "all_off"})
    reset = tool.call_sanitized("owner", {"action": "reset"})

    assert shown.structuredContent["settings"] == DEFAULT_PROMPT_SETTINGS
    assert changed.structuredContent["settings"]["memory_retrieval"] is True
    assert changed.structuredContent["settings"][
        "memory_recency_enabled"
    ] is False
    assert disabled.structuredContent["settings"]["memory_retrieval"] is False
    assert disabled.structuredContent["settings"][
        "memory_recency_enabled"
    ] is False
    assert reset.structuredContent["settings"] == DEFAULT_PROMPT_SETTINGS


def test_settings_tool_rejects_updates_for_non_set_action(tmp_path) -> None:
    tool = GhostPromptSettingsTool(GhostPromptSettings(tmp_path))

    result = tool.call_sanitized(
        "owner",
        {"action": "show", "updates": {"prompt_shaping": False}},
    )

    assert result.isError is True
    assert result.structuredContent == {}
