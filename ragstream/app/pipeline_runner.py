# ragstream/app/pipeline_runner.py
# -*- coding: utf-8 -*-
"""
Step-wise pipeline runner for the Prompt Builder button.

Runs the current document-RAG pipeline automatically, one stage per Streamlit
rerun cycle:

PreProcessing
→ A2 PromptShaper
→ Retrieval
→ ReRanker
→ A3 NLI Gate
→ A4 Condenser

This file contains execution sequencing only.
It does not render the GUI layout.
It does not own Streamlit widgets.
It does not implement stage logic.
"""

from __future__ import annotations

import copy
from typing import Any, Callable

from ragstream.app.controller import AppController
from ragstream.orchestration.super_prompt import SuperPrompt


PIPELINE_STEPS: list[str] = [
    "Pre-Processing",
    "A2-PromptShaper",
    "Retrieval",
    "ReRanker",
    "A3 NLI Gate",
    "A4 Condenser",
]

PIPELINE_TOTAL_STEPS: int = len(PIPELINE_STEPS)


def pipeline_stage_name(step_index: int) -> str:
    """Return the display name for one Prompt Builder pipeline step."""
    if 0 <= int(step_index) < PIPELINE_TOTAL_STEPS:
        return PIPELINE_STEPS[int(step_index)]
    return "Done"


def run_prompt_builder_stage(
    *,
    step_index: int,
    ctrl: AppController,
    sp: SuperPrompt | None,
    user_text: str,
    project_name: str,
    top_k: int,
    use_a2_promptshaper_llm: bool,
    use_retrieval_splade: bool,
    use_reranking_colbert: bool,
    memory_manager: Any | None = None,
    ensure_memory_retrieval_configured: Callable[[AppController], None] | None = None,
) -> dict[str, Any]:
    """
    Run exactly one Prompt Builder pipeline stage.

    Return shape:
        {
            "sp": SuperPrompt,
            "snapshots": {
                "sp_pre": SuperPrompt,
                ...
            }
        }
    """
    clean_user_text = str(user_text or "").strip()
    if not clean_user_text:
        raise ValueError("Prompt is empty. Prompt Builder cannot run.")

    clean_project_name = str(project_name or "").strip()
    if not clean_project_name or clean_project_name == "(no projects yet)":
        raise ValueError("No active project is available for Prompt Builder.")

    idx = int(step_index)
    snapshots: dict[str, SuperPrompt] = {}

    if idx == 0:
        current_sp = SuperPrompt()

        current_sp = ctrl.preprocess(
            clean_user_text,
            current_sp,
            memory_manager=memory_manager,
        )

        snapshots["sp_pre"] = copy.deepcopy(current_sp)

        return {
            "sp": current_sp,
            "snapshots": snapshots,
        }

    if sp is None:
        raise ValueError("Prompt Builder internal state error: SuperPrompt is missing.")

    current_sp = sp

    if idx == 1:
        current_sp = ctrl.run_a2_promptshaper(
            current_sp,
            use_llm=bool(use_a2_promptshaper_llm),
        )

        snapshots["sp_a2"] = copy.deepcopy(current_sp)

        return {
            "sp": current_sp,
            "snapshots": snapshots,
        }

    if idx == 2:
        if ensure_memory_retrieval_configured is not None:
            ensure_memory_retrieval_configured(ctrl)

        current_sp = ctrl.run_retrieval(
            current_sp,
            clean_project_name,
            int(top_k),
            use_retrieval_splade=bool(use_retrieval_splade),
        )

        current_sp.compose_prompt_ready()

        snapshots["sp_rtv"] = copy.deepcopy(current_sp)

        # Retrieval initializes an A3-ready passthrough reranked view.
        # This snapshot remains valid until the real ReRanker overwrites it.
        snapshots["sp_rrk"] = copy.deepcopy(current_sp)

        return {
            "sp": current_sp,
            "snapshots": snapshots,
        }

    if idx == 3:
        if bool(use_reranking_colbert):
            current_sp = ctrl.run_reranker(
                current_sp,
                use_reranking_colbert=True,
            )
        else:
            # ColBERT is disabled.
            # Retrieval already created an A3-ready passthrough view under
            # views_by_stage["reranked"], so ReRanker is intentionally skipped.
            current_sp.compose_prompt_ready()

        snapshots["sp_rrk"] = copy.deepcopy(current_sp)

        return {
            "sp": current_sp,
            "snapshots": snapshots,
        }

    if idx == 4:
        current_sp = ctrl.run_a3(current_sp)

        snapshots["sp_a3"] = copy.deepcopy(current_sp)

        return {
            "sp": current_sp,
            "snapshots": snapshots,
        }

    if idx == 5:
        current_sp = ctrl.run_a4(current_sp)
        current_sp.compose_prompt_ready()

        snapshots["sp_a4"] = copy.deepcopy(current_sp)

        return {
            "sp": current_sp,
            "snapshots": snapshots,
        }

    raise ValueError(f"Unknown Prompt Builder pipeline step_index: {step_index}")