"""Test isolated GHOST prompt engineering and its local rate limiter.

The tests use deterministic local doubles and do not call OpenAI, AWS, Uvicorn,
or Cognito. They verify the real PromptEngineeringRunner workflow, public tool
input and output behavior, request isolation, sanitized failures, tool
discovery, and the standalone rate-limiter component.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any

import pytest

from ragstream.mcp.ghost_engineer_prompt import (
    ANSWER_PROMPT_MODE,
    ANSWER_PROMPT_WITH_MEMORY_MODE,
    SHOW_PROMPT_ONLY_MODE,
    GhostEngineerPromptTool,
    ToolInputError,
    validate_arguments,
)
from ragstream.mcp.prompt_engineering_runner import PromptEngineeringRunner
from ragstream.mcp.rate_limiter import InMemoryRateLimiter
from ragstream.mcp.server import GhostMcpApplication


ENGINEERED_PROMPT = "## TASK\nengineered"
SUPPORTIVE_CONTEXT = "The immediately preceding assistant response."


class Schema:
    """Minimal schema double accepted by the injected preprocessing function."""


def test_runner_uses_one_fresh_superprompt_in_the_required_order() -> None:
    calls: list[tuple[object, ...]] = []
    super_prompts: list[object] = []

    class SuperPrompt:
        def __init__(self) -> None:
            self.stage = "raw"
            self.prompt_ready = ""
            super_prompts.append(self)

    def preprocess(
        prompt_text: str,
        super_prompt: Any,
        _schema: Schema,
    ) -> None:
        calls.append(("preprocess", prompt_text, id(super_prompt)))
        super_prompt.stage = "preprocessed"

    class A2PromptShaper:
        def __init__(self, _agent_factory: object, _llm_client: object) -> None:
            pass

        def run(
            self,
            super_prompt: Any,
            *,
            agent_id: str,
            version: str,
            use_llm: bool,
        ) -> Any:
            calls.append(
                (
                    "a2",
                    agent_id,
                    version,
                    use_llm,
                    id(super_prompt),
                )
            )
            assert super_prompt.stage == "preprocessed"
            super_prompt.stage = "a2"
            super_prompt.prompt_ready = ENGINEERED_PROMPT
            return super_prompt

    runner = PromptEngineeringRunner(
        schema=Schema(),  # type: ignore[arg-type]
        super_prompt_factory=SuperPrompt,  # type: ignore[arg-type]
        preprocess_func=preprocess,  # type: ignore[arg-type]
        agent_factory=object(),  # type: ignore[arg-type]
        llm_client=object(),  # type: ignore[arg-type]
        a2_factory=A2PromptShaper,  # type: ignore[arg-type]
    )

    assert runner.run("hello") == ENGINEERED_PROMPT
    assert len(super_prompts) == 1
    assert calls == [
        ("preprocess", "hello", id(super_prompts[0])),
        (
            "a2",
            "a2_promptshaper",
            "003",
            True,
            id(super_prompts[0]),
        ),
    ]


def test_simultaneous_prompts_use_different_superprompts() -> None:
    barrier = threading.Barrier(2)
    super_prompt_ids: list[int] = []
    results: list[str] = []
    errors: list[BaseException] = []

    class SuperPrompt:
        def __init__(self) -> None:
            self.stage = "raw"
            self.prompt_ready = ""
            self.prompt_text = ""

    def preprocess(
        prompt_text: str,
        super_prompt: Any,
        _schema: Schema,
    ) -> None:
        super_prompt.prompt_text = prompt_text
        super_prompt_ids.append(id(super_prompt))
        barrier.wait(timeout=5)
        super_prompt.stage = "preprocessed"

    class A2PromptShaper:
        def __init__(self, _agent_factory: object, _llm_client: object) -> None:
            pass

        def run(self, super_prompt: Any, **_kwargs: object) -> Any:
            super_prompt.stage = "a2"
            super_prompt.prompt_ready = f"out:{super_prompt.prompt_text}"
            return super_prompt

    runner = PromptEngineeringRunner(
        schema=Schema(),  # type: ignore[arg-type]
        super_prompt_factory=SuperPrompt,  # type: ignore[arg-type]
        preprocess_func=preprocess,  # type: ignore[arg-type]
        agent_factory=object(),  # type: ignore[arg-type]
        llm_client=object(),  # type: ignore[arg-type]
        a2_factory=A2PromptShaper,  # type: ignore[arg-type]
    )

    def run_prompt(prompt_text: str) -> None:
        try:
            results.append(runner.run(prompt_text))
        except BaseException as exc:  # noqa: BLE001 - preserve thread failure
            errors.append(exc)

    threads = [
        threading.Thread(target=run_prompt, args=(prompt_text,))
        for prompt_text in ("one", "two")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert sorted(results) == ["out:one", "out:two"]
    assert len(set(super_prompt_ids)) == 2


def test_input_validation_preserves_unicode_markdown_and_context() -> None:
    prompt_text = "# TASK\nحافظ على Markdown ✅\n## CONTEXT\nLine two"
    supportive_context = "Vorherige Antwort — بدون تغییر"

    assert validate_arguments({"prompt_text": prompt_text}) == (
        prompt_text,
        None,
    )
    assert validate_arguments(
        {
            "prompt_text": prompt_text,
            "supportive_context": supportive_context,
        }
    ) == (
        prompt_text,
        supportive_context,
    )


@pytest.mark.parametrize(
    "arguments",
    [
        None,
        {},
        {"prompt_text": "   "},
        {"prompt_text": 3},
        {"prompt_text": "x", "extra": "no"},
        {"prompt_text": "x", "supportive_context": 3},
    ],
)
def test_input_validation_rejects_invalid_arguments(
    arguments: Mapping[str, object] | None,
) -> None:
    with pytest.raises(ToolInputError):
        validate_arguments(arguments)


@pytest.mark.parametrize(
    (
        "arguments",
        "expected_runner_prompt",
        "expected_engineered_prompt",
        "expected_mode",
    ),
    [
        pytest.param(
            {"prompt_text": "Explain OAuth."},
            "Explain OAuth.",
            ENGINEERED_PROMPT,
            ANSWER_PROMPT_MODE,
            id="normal",
        ),
        pytest.param(
            {"prompt_text": "PROMPT: Explain OAuth."},
            "Explain OAuth.",
            ENGINEERED_PROMPT,
            SHOW_PROMPT_ONLY_MODE,
            id="prompt",
        ),
        pytest.param(
            {
                "prompt_text": "MEM: Explain OAuth.",
                "supportive_context": SUPPORTIVE_CONTEXT,
            },
            "Explain OAuth.",
            (
                f"{ENGINEERED_PROMPT}\n\n"
                f"## Supportive Context\n\n{SUPPORTIVE_CONTEXT}"
            ),
            ANSWER_PROMPT_WITH_MEMORY_MODE,
            id="memory",
        ),
    ],
)
def test_tool_returns_exact_contract_for_all_three_modes(
    arguments: dict[str, str],
    expected_runner_prompt: str,
    expected_engineered_prompt: str,
    expected_mode: str,
) -> None:
    calls: list[str] = []

    class Runner:
        def run(self, prompt_text: str) -> str:
            calls.append(prompt_text)
            return ENGINEERED_PROMPT

    result = GhostEngineerPromptTool(
        Runner()  # type: ignore[arg-type]
    ).call(arguments)

    assert result.isError is False
    assert result.content == [
        {
            "type": "text",
            "text": expected_engineered_prompt,
        }
    ]
    assert result.structuredContent == {
        "engineered_prompt": expected_engineered_prompt,
        "stage": "a2",
        "mode": expected_mode,
    }
    assert calls == [expected_runner_prompt]


def test_tool_discovery_exposes_exactly_one_tool() -> None:
    class Runner:
        def run(self, _prompt_text: str) -> str:
            return "ok"

    application = GhostMcpApplication(
        tool=GhostEngineerPromptTool(
            Runner()  # type: ignore[arg-type]
        )
    )

    tools = application.list_tools()

    assert [tool.name for tool in tools] == ["ghost_engineer_prompt"]
    assert tools[0].inputSchema["additionalProperties"] is False
    assert set(tools[0].outputSchema["required"]) == {
        "engineered_prompt",
        "stage",
        "mode",
    }


def test_sanitized_failure_hides_internal_details() -> None:
    class Runner:
        def run(self, _prompt_text: str) -> str:
            raise RuntimeError(
                "/tmp/secret OPENAI_API_KEY raw model output Traceback"
            )

    result = GhostEngineerPromptTool(
        Runner()  # type: ignore[arg-type]
    ).call_sanitized({"prompt_text": "x"})

    assert result.isError is True
    message = result.content[0]["text"]
    assert message == "GHOST prompt engineering failed"
    assert "OPENAI" not in message
    assert "Traceback" not in message
    assert "/tmp" not in message


def test_rate_limiter_rejects_the_second_call_in_the_same_window() -> None:
    limiter = InMemoryRateLimiter(
        limit=1,
        window_seconds=60,
        clock=lambda: 1.0,
    )

    first = limiter.check("user-123")
    second = limiter.check("user-123")

    assert first.allowed is True
    assert second.allowed is False
    assert second.retry_after_seconds == 60.0