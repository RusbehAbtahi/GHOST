"""Request-isolated GHOST prompt-engineering workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ragstream.agents.a2_promptshaper import A2PromptShaper
from ragstream.orchestration.agent_factory import AgentFactory
from ragstream.orchestration.llm_client import LLMClient
from ragstream.orchestration.super_prompt import SuperPrompt
from ragstream.preprocessing.preprocessing import preprocess
from ragstream.preprocessing.prompt_schema import PromptSchema


class PromptEngineeringError(RuntimeError):
    """Expected failure in the approved prompt-engineering path."""


class PromptEngineeringRunner:
    """Runs deterministic PreProcessing followed by A2 for one prompt."""

    def __init__(
        self,
        *,
        schema: PromptSchema | None = None,
        super_prompt_factory: Callable[[], SuperPrompt] = SuperPrompt,
        preprocess_func: Callable[[str, SuperPrompt, PromptSchema], None] = preprocess,
        agent_factory: AgentFactory | None = None,
        llm_client: LLMClient | None = None,
        a2_factory: Callable[[AgentFactory, LLMClient], A2PromptShaper] = A2PromptShaper,
    ) -> None:
        self._schema = schema or PromptSchema(str(_default_schema_path()))
        self._super_prompt_factory = super_prompt_factory
        self._preprocess = preprocess_func
        self._agent_factory = agent_factory or AgentFactory()
        self._llm_client = llm_client or LLMClient()
        self._a2_factory = a2_factory

    def run(self, prompt_text: str) -> str:
        """Return the final post-A2 SuperPrompt.prompt_ready value."""
        sp = self._super_prompt_factory()

        try:
            self._preprocess(prompt_text, sp, self._schema)
        except Exception as exc:  # noqa: BLE001 - sanitize at boundary while preserving phase
            raise PromptEngineeringError("PreProcessing failed") from exc

        if sp.stage != "preprocessed":
            raise PromptEngineeringError("PreProcessing did not complete")

        a2 = self._a2_factory(self._agent_factory, self._llm_client)
        try:
            result_sp = a2.run(
                sp,
                agent_id="a2_promptshaper",
                version="003",
                use_llm=True,
            )
        except Exception as exc:  # noqa: BLE001
            raise PromptEngineeringError("A2 PromptShaper failed") from exc

        if result_sp is not sp:
            raise PromptEngineeringError("A2 returned a different SuperPrompt")
        if sp.stage != "a2":
            raise PromptEngineeringError("A2 did not complete")
        engineered_prompt = sp.prompt_ready
        if not isinstance(engineered_prompt, str) or not engineered_prompt.strip():
            raise PromptEngineeringError("A2 produced an empty engineered prompt")
        return engineered_prompt


def _default_schema_path() -> Path:
    return Path(__file__).resolve().parents[2] / "ragstream" / "config" / "prompt_schema.json"
