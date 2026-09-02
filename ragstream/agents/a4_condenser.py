# -*- coding: utf-8 -*-
"""
A4 Condenser agent.

Job:
- Read the current SuperPrompt after A3.
- Keep only the A3-useful chunks.
- Re-rank them locally with fresh local ids 1..N.
- Run 3 LLM calls:
    1) chunk phraser
    2) chunk classifier
    3) final condenser
- Run deterministic regrouping and final write-back.
- Update the same SuperPrompt in place.

Important design rules from this chat:
- Exact JSON paths are loaded here, not via AgentFactory path logic.
- All 3 AgentPrompt objects are created at the beginning of the run.
- The repeated chunk/query prefix must stay identical across the 3 A4 calls.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
import json

from ragstream.orchestration.super_prompt import SuperPrompt
from ragstream.orchestration.agent_prompt import AgentPrompt
from ragstream.orchestration.llm_client import LLMClient
from ragstream.utils.logging import SimpleLogger

from ragstream.agents.a4_det_processing import (
    prepare_selected_chunks,
    prepare_active_class_definitions,
    build_grouped_chunk_package,
    finalize_a4_output,
    has_a4_useful_chunks,
    finalize_a4_empty_selection,
)
from ragstream.agents.a4_llm_helper import A4LLMHelper


JsonDict = Dict[str, Any]


class A4Condenser:
    """
    Orchestrates A4 for a single SuperPrompt.

    This class stays high-level:
    - exact-path JSON loading,
    - 7-step workflow order,
    - delegation to deterministic helpers,
    - delegation to the shared LLM helper.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        *,
        max_candidates: int = 30,
        default_max_output_tokens: int = 1200,
    ) -> None:
        self._llm_client = llm_client
        self._max_candidates = int(max_candidates)
        self._default_max_output_tokens = int(default_max_output_tokens)

    def run(
        self,
        sp: SuperPrompt,
        *,
        effective_output_token_limit: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
    ) -> SuperPrompt:
        """
        Main entry point for A4.
        """
        if sp is None:
            raise ValueError("A4Condenser.run: 'sp' must not be None")
        if not has_a4_useful_chunks(sp, max_candidates=self._max_candidates):
            return finalize_a4_empty_selection(
                sp=sp,
                reason="a3_selected_zero_useful_chunks",
            )

        json_paths = self._build_agent_json_paths()

        # Agreed design:
        # create all 3 AgentPrompt objects at the beginning of the workflow.
        chunk_phraser_agent = self._load_agent_prompt(json_paths["chunk_phraser"])
        chunk_classifier_agent = self._load_agent_prompt(json_paths["chunk_classifier"])
        final_condenser_agent = self._load_agent_prompt(json_paths["final_condenser"])

        llm_helper = A4LLMHelper(self._llm_client)

        # ------------------------------------------------------------------
        # 1) deterministic: prepare selected chunks
        # ------------------------------------------------------------------
        selected_payload = prepare_selected_chunks(
            sp,
            max_candidates=self._max_candidates,
        )

        # ------------------------------------------------------------------
        # 2) LLM call: chunk phraser
        # ------------------------------------------------------------------
        phraser_result = llm_helper.run_chunk_phraser(
            chunk_phraser_agent,
            user_prompt_under_evaluation=selected_payload["user_prompt_under_evaluation"],
            evidence_chunks=selected_payload["evidence_chunks"],
        )

        # ------------------------------------------------------------------
        # 3) deterministic: prepare active class definitions + restrict classifier
        # ------------------------------------------------------------------
        active_class_payload = prepare_active_class_definitions(
            phraser_result=phraser_result,
            classifier_agent_prompt=chunk_classifier_agent,
        )

        # ------------------------------------------------------------------
        # 4) LLM call: chunk classifier
        # ------------------------------------------------------------------
        classifier_result = llm_helper.run_chunk_classifier(
            chunk_classifier_agent,
            user_prompt_under_evaluation=selected_payload["user_prompt_under_evaluation"],
            evidence_chunks=selected_payload["evidence_chunks"],
            active_class_definitions=active_class_payload["active_class_definitions_text"],
        )

        # ------------------------------------------------------------------
        # 5) deterministic: regroup, validate, budget logic, final payload prep
        # ------------------------------------------------------------------
        grouped_chunk_package = build_grouped_chunk_package(
            classifier_result=classifier_result,
            selected_payload=selected_payload,
            active_class_payload=active_class_payload,
            effective_output_token_limit=(
                self._default_max_output_tokens
                if effective_output_token_limit is None
                else int(effective_output_token_limit)
            ),
        )

        # ------------------------------------------------------------------
        # 6) LLM call: final condenser
        # ------------------------------------------------------------------
        condenser_result = llm_helper.run_final_condenser(
            final_condenser_agent,
            user_prompt_under_evaluation=selected_payload["user_prompt_under_evaluation"],
            evidence_chunks=selected_payload["evidence_chunks"],
            class_groups=grouped_chunk_package["class_groups_text"],
            effective_output_token_limit=grouped_chunk_package["effective_output_token_limit"],
            decision_targets_text=grouped_chunk_package["decision_targets_text"],
            max_output_tokens=max_output_tokens,
        )

        # ------------------------------------------------------------------
        # 7) deterministic: final write-back to SuperPrompt
        # ------------------------------------------------------------------
        sp = finalize_a4_output(
            sp=sp,
            condenser_result=condenser_result,
            grouped_chunk_package=grouped_chunk_package,
        )

        return sp

    def _build_agent_json_paths(self) -> Dict[str, Path]:
        """
        Build the exact A4 JSON paths agreed in this chat.
        """
        root = Path(__file__).resolve().parents[2]
        base = root / "data" / "agents" / "a4_condenser"

        return {
            "chunk_phraser": base / "chunk_phraser" / "a4_1_001.json",
            "chunk_classifier": base / "chunk_classifier" / "a4_2_001.json",
            "final_condenser": base / "final_condenser" / "a4_3_001.json",
        }

    def _load_agent_prompt(self, json_path: Path) -> AgentPrompt:
        """
        Load one exact-path JSON config and build one AgentPrompt.
        """
        if not json_path.exists():
            raise FileNotFoundError(f"A4Condenser: missing agent JSON: {json_path}")

        try:
            config = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"A4Condenser: failed to read JSON '{json_path}': {exc}") from exc

        agent_prompt = AgentPrompt.from_config(config)
        SimpleLogger.info(f"A4Condenser: loaded AgentPrompt from {json_path}")
        return agent_prompt