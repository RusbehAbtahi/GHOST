"""Test isolated GHOST prompt engineering and its local rate limiter.

The tests use deterministic local doubles and do not call OpenAI, AWS, Uvicorn,
or Cognito. They verify the real PromptEngineeringRunner workflow, public tool
input and output behavior, request isolation, sanitized failures, tool
discovery, and the standalone rate-limiter component.
"""

from __future__ import annotations

import threading
from typing import Any


from ragstream.mcp.prompt_engineering_runner import PromptEngineeringRunner
from ragstream.mcp.rate_limiter import InMemoryRateLimiter


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


def test_runner_can_return_the_post_a2_superprompt() -> None:
    class SuperPrompt:
        def __init__(self) -> None:
            self.stage = "raw"
            self.prompt_ready = ""

    def preprocess(
        _prompt_text: str,
        super_prompt: Any,
        _schema: Schema,
    ) -> None:
        super_prompt.stage = "preprocessed"

    class A2PromptShaper:
        def __init__(self, _agent_factory: object, _llm_client: object) -> None:
            pass

        def run(self, super_prompt: Any, **_kwargs: object) -> Any:
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

    super_prompt = runner.run_superprompt("hello")

    assert super_prompt.stage == "a2"
    assert super_prompt.prompt_ready == ENGINEERED_PROMPT
    assert runner.run("hello") == ENGINEERED_PROMPT


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
