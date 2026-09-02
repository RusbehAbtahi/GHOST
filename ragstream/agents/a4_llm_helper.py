# -*- coding: utf-8 -*-
"""
a4_llm_helper.py

Shared LLM-call helper for A4.

Responsibilities:
- receive already-created AgentPrompt objects,
- build the input payloads for the 3 A4 calls,
- compose prompts,
- log the exact prompts/messages to CLI,
- call LLMClient,
- log model name + token usage after each call,
- parse the result back into Python.
"""

from __future__ import annotations

from typing import Any, Dict

import json

from ragstream.orchestration.agent_prompt import AgentPrompt
from ragstream.orchestration.llm_client import LLMClient
from ragstream.utils.logging import SimpleLogger


JsonDict = Dict[str, Any]


class A4LLMHelper:
    """
    Shared LLM-call helper for the 3 A4 calls.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm_client = llm_client

    def run_chunk_phraser(
        self,
        agent_prompt: AgentPrompt,
        *,
        user_prompt_under_evaluation: str,
        evidence_chunks: str,
    ) -> JsonDict:
        inputs: Dict[str, Any] = {
            "user_prompt_under_evaluation": user_prompt_under_evaluation,
            "evidence_chunks": evidence_chunks,
            "decision_targets": (
                "Use only contiguous class ids starting from ID1.\n"
                "Return 1 to 4 active classes only.\n"
                "Each class must contain class_id, class_phrase, class_context_text."
            ),
            "required_output": (
                '{\n'
                '  "class_definitions": [\n'
                '    {\n'
                '      "class_id": "ID1",\n'
                '      "class_phrase": "...",\n'
                '      "class_context_text": "..."\n'
                '    }\n'
                '  ]\n'
                '}'
            ),
        }

        return self._run_agent_call(
            call_name="A4 Chunk Phraser",
            agent_prompt=agent_prompt,
            input_payload=inputs,
            prompt_cache_key="a4_condenser_shared_prefix",  # Added: one stable cache key for the shared A4 prefix family across all 3 calls.
        )

    def run_chunk_classifier(
        self,
        agent_prompt: AgentPrompt,
        *,
        user_prompt_under_evaluation: str,
        evidence_chunks: str,
        active_class_definitions: str,
    ) -> JsonDict:
        inputs: Dict[str, Any] = {
            "user_prompt_under_evaluation": user_prompt_under_evaluation,
            "active_class_definitions": active_class_definitions,
            "evidence_chunks": evidence_chunks,
            "required_output": (
                '{\n'
                '  "item_decisions": [\n'
                '    {\n'
                '      "chunk_id": "1",\n'
                '      "class_id": "one visible class phrase from Active Class Definitions"\n'
                '    }\n'
                '  ]\n'
                '}'
            ),
        }

        return self._run_agent_call(
            call_name="A4 Chunk Classifier",
            agent_prompt=agent_prompt,
            input_payload=inputs,
            prompt_cache_key="a4_condenser_shared_prefix",  # Added: same stable cache key to keep the shared A4 prefix on the same cache-routing family.
        )

    def run_final_condenser(
        self,
        agent_prompt: AgentPrompt,
        *,
        user_prompt_under_evaluation: str,
        evidence_chunks: str,
        class_groups: str,
        effective_output_token_limit: int,
        decision_targets_text: str,
        max_output_tokens: int | None = None,
    ) -> JsonDict:
        inputs: Dict[str, Any] = {
            "user_prompt_under_evaluation": user_prompt_under_evaluation,
            "class_groups": class_groups,
            "evidence_chunks": evidence_chunks,
            "decision_targets": decision_targets_text,
            "required_output": (
                '{\n'
                '  "s_ctx_md": "one coherent condensed context text"\n'
                '}\n'
                f"\nThe visible s_ctx_md content MUST NOT exceed "
                f"{int(effective_output_token_limit)} tokens. "
                f"{int(effective_output_token_limit)} tokens is a strict "
                "maximum, not a target or approximation."
            ),
        }

        return self._run_agent_call(
            call_name="A4 Final Condenser",
            agent_prompt=agent_prompt,
            input_payload=inputs,
            prompt_cache_key="a4_condenser_shared_prefix",  # Added: same stable cache key to maximize hit rate for the identical A4 prefix family.
            max_output_tokens=max_output_tokens,
        )

    def _run_agent_call(
        self,
        *,
        call_name: str,
        agent_prompt: AgentPrompt,
        input_payload: Dict[str, Any],
        prompt_cache_key: str,
        max_output_tokens: int | None = None,
    ) -> JsonDict:
        """
        Shared LLM path for all 3 A4 calls.

        Uses the Responses API with minimal reasoning effort.
        """
        messages, response_format = agent_prompt.compose(input_payload=input_payload)

        SimpleLogger.info(f"{call_name} → LLM messages:")
        try:
            SimpleLogger.info(json.dumps(messages, ensure_ascii=False, indent=2))
        except Exception:
            SimpleLogger.info(repr(messages))

        response = self._llm_client.responses(
            messages=messages,
            model_name=agent_prompt.model_name,
            max_output_tokens=(
                agent_prompt.max_output_tokens
                if max_output_tokens is None
                else int(max_output_tokens)
            ),
            reasoning_effort="minimal",
            return_metadata=True,
            prompt_cache_key=prompt_cache_key,  # Added: explicit cache-routing key for shared A4 prefix family.
          #  prompt_cache_retention="in_memory",  # Added: explicit short-lived cache retention for near-term chained A4 calls.
        )

        raw_content = str(response.get("content", "") or "")
        usage = response.get("usage", {}) or {}
        model_name = str(response.get("model_name", "") or agent_prompt.model_name)
        status = str(response.get("status", "") or "")
        incomplete_reason = str(response.get("incomplete_reason", "") or "")

        SimpleLogger.info(f"{call_name} ← LLM raw result:")
        try:
            SimpleLogger.info(raw_content)
        except Exception:
            SimpleLogger.info(repr(raw_content))

        input_tokens = int(usage.get("input_tokens", 0) or 0)
        cached_input_tokens = int(usage.get("cached_input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)
        reasoning_tokens = int(usage.get("reasoning_tokens", 0) or 0)
        uncached_input_tokens = max(0, input_tokens - cached_input_tokens)

        SimpleLogger.info(
            f"{call_name} | model={model_name} | status={status} | "
            f"input={input_tokens} | cached_input={cached_input_tokens} | "
            f"uncached_input={uncached_input_tokens} | output={output_tokens} | "
            f"reasoning={reasoning_tokens}"
        )

        if incomplete_reason:
            SimpleLogger.warning(
                f"{call_name} | incomplete_reason={incomplete_reason}"
            )

        parsed = agent_prompt.parse(raw_content)

        SimpleLogger.info(f"{call_name} ← parsed result:")
        try:
            SimpleLogger.info(json.dumps(parsed, ensure_ascii=False, indent=2))
        except Exception:
            SimpleLogger.info(repr(parsed))

        return parsed