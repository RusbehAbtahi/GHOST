# ragstream/app/ui_actions.py
# -*- coding: utf-8 -*-
"""
Small callback helpers for Streamlit button/form actions.
Keep controller calls and session-state mutations here.
"""

from __future__ import annotations

import copy
import time

from dataclasses import dataclass
from typing import Any, Callable

import streamlit as st

from ragstream.app.controller import AppController
from ragstream.app.pipeline_runner import (
    PIPELINE_TOTAL_STEPS,
    pipeline_stage_name,
    run_prompt_builder_stage,
)
from ragstream.memory.memory_actions import capture_memory_pair
from ragstream.memory.memory_manager import MemoryManager
from ragstream.orchestration.super_prompt import SuperPrompt
from ragstream.textforge.RagLog import LogALL as logger


SIDEBAR_PIPELINE_TOTAL_STEPS = 8

SIDEBAR_STEP_USER_PROMPT = 0
SIDEBAR_STEP_PROMPT_QUALIFICATION = 1
SIDEBAR_STEP_PROMPT_SHAPING = 2
SIDEBAR_STEP_MEMORY_CONTEXT = 3
SIDEBAR_STEP_DOCUMENT_EVIDENCE = 4
SIDEBAR_STEP_CONTEXT_SYNTHESIS = 5
SIDEBAR_STEP_HARD_RULE_INTEGRATION = 6
SIDEBAR_STEP_LLM_READY_CONTEXT = 7

LIVE_PAINT_SETTLE_SECONDS = 0.00
VISUAL_TAIL_SETTLE_SECONDS = 0.00


@dataclass(slots=True)
class LivePipelineSurfaces:
    """Caller-owned live Streamlit surfaces for Prompt Builder repainting."""

    progress_slot: Any | None = None
    status_slot: Any | None = None
    runtime_log_slot: Any | None = None
    sidebar_flowchart_slot: Any | None = None
    render_runtime_log: Callable[..., None] | None = None
    render_sidebar_flowchart: Callable[[Any | None], None] | None = None


def _settle_live_paint(seconds: float = LIVE_PAINT_SETTLE_SECONDS) -> None:
    if seconds > 0:
        time.sleep(float(seconds))


def _set_sidebar_pipeline_visual_step(
    active_step: int,
    completed_step: int | None = None,
) -> None:
    active_step = max(0, min(int(active_step), SIDEBAR_PIPELINE_TOTAL_STEPS - 1))

    if completed_step is None:
        completed_step = active_step - 1

    completed_step = max(-1, min(int(completed_step), SIDEBAR_PIPELINE_TOTAL_STEPS - 1))

    st.session_state["sidebar_pipeline_active_step"] = active_step
    st.session_state["sidebar_pipeline_completed_step"] = completed_step
    st.session_state["sidebar_pipeline_active_since"] = time.monotonic()


def _sidebar_visual_step_for_stage(
    stage_name: str,
    step_index: int,
) -> int:
    name = str(stage_name or "").lower()

    if "pre" in name:
        return SIDEBAR_STEP_PROMPT_QUALIFICATION

    if "a2" in name or "promptshaper" in name or "prompt shaper" in name:
        return SIDEBAR_STEP_PROMPT_SHAPING

    if "retrieval" in name or "retriever" in name:
        return SIDEBAR_STEP_MEMORY_CONTEXT

    if "rerank" in name:
        return SIDEBAR_STEP_MEMORY_CONTEXT

    if "a3" in name or "nli" in name:
        return SIDEBAR_STEP_DOCUMENT_EVIDENCE

    if "a4" in name or "condenser" in name or "condense" in name:
        return SIDEBAR_STEP_CONTEXT_SYNTHESIS

    fallback_map = {
        0: SIDEBAR_STEP_PROMPT_QUALIFICATION,
        1: SIDEBAR_STEP_PROMPT_SHAPING,
        2: SIDEBAR_STEP_MEMORY_CONTEXT,
        3: SIDEBAR_STEP_MEMORY_CONTEXT,
        4: SIDEBAR_STEP_DOCUMENT_EVIDENCE,
        5: SIDEBAR_STEP_CONTEXT_SYNTHESIS,
    }

    return fallback_map.get(int(step_index), SIDEBAR_STEP_LLM_READY_CONTEXT)


def _pipeline_is_running() -> bool:
    return bool(st.session_state.get("pipeline_running", False))


def _guard_pipeline_running(action_name: str) -> bool:
    """
    Logical execution lock only.

    This does not disable or grey out widgets.
    It only prevents another action from being executed while the full
    Prompt Builder pipeline is already running.
    """
    if not _pipeline_is_running():
        return False

    logger(
        f"{action_name} ignored: Prompt Builder pipeline is running.",
        "WARN",
        "PUBLIC",
    )
    return True


def _set_pipeline_status(
    stage_name: str,
    step_index: int,
    total_steps: int,
    message: str,
) -> None:
    progress = 0.0
    if total_steps > 0:
        progress = max(0.0, min(1.0, float(step_index) / float(total_steps)))

    st.session_state["pipeline_status"] = {
        "stage_name": stage_name,
        "step_index": int(step_index),
        "total_steps": int(total_steps),
        "message": message,
        "progress": progress,
    }


def _paint_progress(surfaces: LivePipelineSurfaces) -> None:
    status = st.session_state.get("pipeline_status")
    if not isinstance(status, dict):
        return

    stage_name = str(status.get("stage_name", "Idle") or "Idle")
    step_index = int(status.get("step_index", 0) or 0)
    total_steps = int(
        status.get("total_steps", SIDEBAR_PIPELINE_TOTAL_STEPS)
        or SIDEBAR_PIPELINE_TOTAL_STEPS
    )
    progress = float(status.get("progress", 0.0) or 0.0)
    message = str(status.get("message", "") or "")

    if surfaces.progress_slot is not None:
        surfaces.progress_slot.progress(
            progress,
            text=f"{step_index}/{total_steps} — {stage_name}",
        )

    if surfaces.status_slot is not None:
        if message and stage_name not in {"Idle", "Done"}:
            surfaces.status_slot.info(message)
        else:
            surfaces.status_slot.empty()


def _paint_sidebar_flowchart(surfaces: LivePipelineSurfaces) -> None:
    if surfaces.sidebar_flowchart_slot is None or surfaces.render_sidebar_flowchart is None:
        return

    surfaces.render_sidebar_flowchart(surfaces.sidebar_flowchart_slot)


def _paint_runtime_log(surfaces: LivePipelineSurfaces) -> None:
    if surfaces.runtime_log_slot is None or surfaces.render_runtime_log is None:
        return

    surfaces.render_runtime_log(log_slot=surfaces.runtime_log_slot)


def _paint_live_status(surfaces: LivePipelineSurfaces) -> None:
    _paint_progress(surfaces)
    _paint_sidebar_flowchart(surfaces)
    _paint_runtime_log(surfaces)


def _reset_superprompt_runtime_state() -> None:
    st.session_state.sp = SuperPrompt()
    st.session_state.sp_pre = SuperPrompt()
    st.session_state.sp_a2 = SuperPrompt()
    st.session_state.sp_rtv = SuperPrompt()
    st.session_state.sp_rrk = SuperPrompt()
    st.session_state.sp_a3 = SuperPrompt()
    st.session_state.sp_a4 = SuperPrompt()
    st.session_state["super_prompt_text"] = ""


def do_user_prompt_changed() -> None:
    st.session_state["pipeline_running"] = False
    st.session_state["pipeline_config"] = {}

    _set_sidebar_pipeline_visual_step(
        SIDEBAR_STEP_USER_PROMPT,
        -1,
    )

    _set_pipeline_status(
        stage_name="User Prompt",
        step_index=1,
        total_steps=SIDEBAR_PIPELINE_TOTAL_STEPS,
        message="User prompt changed.",
    )


def request_prompt_builder_run() -> None:
    """Backward-compatible wrapper for older imports."""
    run_prompt_builder_live()


def run_next_prompt_builder_step() -> None:
    """Backward-compatible no-op. The rerun state machine is no longer used."""
    return


def run_prompt_builder_live(
    *,
    surfaces: LivePipelineSurfaces | None = None,
) -> None:
    """
    Run the full Prompt Builder pipeline in one controlled Streamlit run.

    Layout ownership stays in ui_layout.py. This function only mutates state,
    runs stages, and repaints caller-owned surfaces. It does not create layout
    objects and does not call st.rerun().
    """
    if _guard_pipeline_running("Prompt Builder"):
        return

    if surfaces is None:
        surfaces = LivePipelineSurfaces()

    try:
        ctrl: AppController = st.session_state.controller

        user_text = str(st.session_state.get("prompt_text", "") or "").strip()
        if not user_text:
            logger(
                "Prompt Builder cannot run because Prompt is empty.",
                "WARN",
                "PUBLIC",
            )
            st.error("Prompt is empty. Prompt Builder cannot run.")
            return

        project_name = _resolve_active_project(ctrl)
        top_k = int(st.session_state.get("retrieval_top_k", 100))

        use_a2_promptshaper_llm = bool(st.session_state.get("use_a2_promptshaper_llm", True))
        use_retrieval_splade = bool(st.session_state.get("use_retrieval_splade", False))
        use_reranking_colbert = bool(st.session_state.get("use_reranking_colbert", False))

        _reset_superprompt_runtime_state()

        st.session_state["pipeline_running"] = True
        st.session_state["pipeline_config"] = {
            "user_text": user_text,
            "project_name": project_name,
            "top_k": top_k,
            "use_a2_promptshaper_llm": use_a2_promptshaper_llm,
            "use_retrieval_splade": use_retrieval_splade,
            "use_reranking_colbert": use_reranking_colbert,
        }

        logger(
            (
                "Prompt Builder started: "
                f"A2_LLM={use_a2_promptshaper_llm}, "
                f"SPLADE={use_retrieval_splade}, "
                f"ColBERT={use_reranking_colbert}, "
                f"top_k={top_k}, "
                f"project={project_name}"
            ),
            "INFO",
            "PUBLIC",
        )

        _set_sidebar_pipeline_visual_step(
            SIDEBAR_STEP_USER_PROMPT,
            -1,
        )
        _set_pipeline_status(
            stage_name="Queued",
            step_index=0,
            total_steps=SIDEBAR_PIPELINE_TOTAL_STEPS,
            message="Prompt Builder pipeline started.",
        )
        _paint_live_status(surfaces)
        _settle_live_paint()

        for step_index in range(PIPELINE_TOTAL_STEPS):
            stage_name = pipeline_stage_name(step_index)
            visual_step = _sidebar_visual_step_for_stage(
                stage_name=stage_name,
                step_index=step_index,
            )

            _set_sidebar_pipeline_visual_step(
                visual_step,
                visual_step - 1,
            )
            _set_pipeline_status(
                stage_name=stage_name,
                step_index=step_index + 1,
                total_steps=SIDEBAR_PIPELINE_TOTAL_STEPS,
                message=f"Running {stage_name}.",
            )
            logger(
                f"Prompt Builder stage running: {step_index + 1}/{PIPELINE_TOTAL_STEPS} — {stage_name}",
                "INFO",
                "PUBLIC",
            )
            _paint_live_status(surfaces)
            _settle_live_paint()

            current_sp = st.session_state.get("sp")
            if not isinstance(current_sp, SuperPrompt):
                current_sp = None

            result = run_prompt_builder_stage(
                step_index=step_index,
                ctrl=ctrl,
                sp=current_sp,
                user_text=user_text,
                project_name=project_name,
                top_k=top_k,
                use_a2_promptshaper_llm=use_a2_promptshaper_llm,
                use_retrieval_splade=use_retrieval_splade,
                use_reranking_colbert=use_reranking_colbert,
                memory_manager=st.session_state.get("memory_manager"),
                ensure_memory_retrieval_configured=_ensure_memory_retrieval_configured,
            )

            sp: SuperPrompt = result["sp"]
            snapshots: dict[str, SuperPrompt] = result.get("snapshots", {}) or {}

            st.session_state.sp = sp

            for snapshot_key, snapshot_value in snapshots.items():
                st.session_state[snapshot_key] = snapshot_value

            st.session_state["super_prompt_text"] = sp.prompt_ready

            logger(
                f"Prompt Builder stage finished: {step_index + 1}/{PIPELINE_TOTAL_STEPS} — {stage_name}",
                "INFO",
                "PUBLIC",
            )

            _set_sidebar_pipeline_visual_step(
                visual_step,
                visual_step,
            )
            _set_pipeline_status(
                stage_name=stage_name,
                step_index=step_index + 1,
                total_steps=SIDEBAR_PIPELINE_TOTAL_STEPS,
                message=f"Finished {stage_name}.",
            )
            _paint_live_status(surfaces)
            _settle_live_paint()

        _set_sidebar_pipeline_visual_step(
            SIDEBAR_STEP_HARD_RULE_INTEGRATION,
            SIDEBAR_STEP_CONTEXT_SYNTHESIS,
        )
        _set_pipeline_status(
            stage_name="Hard Rule Integration",
            step_index=SIDEBAR_STEP_HARD_RULE_INTEGRATION + 1,
            total_steps=SIDEBAR_PIPELINE_TOTAL_STEPS,
            message="Final assembly state updated.",
        )
        _paint_live_status(surfaces)
        _settle_live_paint(VISUAL_TAIL_SETTLE_SECONDS)

        _set_sidebar_pipeline_visual_step(
            SIDEBAR_STEP_LLM_READY_CONTEXT,
            SIDEBAR_STEP_HARD_RULE_INTEGRATION,
        )
        _set_pipeline_status(
            stage_name="Done",
            step_index=SIDEBAR_PIPELINE_TOTAL_STEPS,
            total_steps=SIDEBAR_PIPELINE_TOTAL_STEPS,
            message="Prompt Builder pipeline completed.",
        )
        logger(
            "Prompt Builder finished.",
            "INFO",
            "PUBLIC",
        )
        _paint_live_status(surfaces)

    except Exception as e:
        _set_pipeline_status(
            stage_name="Failed",
            step_index=0,
            total_steps=SIDEBAR_PIPELINE_TOTAL_STEPS,
            message=str(e),
        )
        _paint_live_status(surfaces)
        logger(str(e), "ERROR", "PUBLIC")
        st.error(str(e))

    finally:
        st.session_state["pipeline_running"] = False
        st.session_state["pipeline_config"] = {}



def do_preprocess() -> None:
    if _guard_pipeline_running("PreProcessing"):
        return

    ctrl: AppController = st.session_state.controller
    user_text = st.session_state.get("prompt_text", "")

    # Start a fresh pipeline run from clean SuperPrompt objects.
    st.session_state.sp = SuperPrompt()
    st.session_state.sp_pre = SuperPrompt()
    st.session_state.sp_a2 = SuperPrompt()
    st.session_state.sp_rtv = SuperPrompt()
    st.session_state.sp_rrk = SuperPrompt()
    st.session_state.sp_a3 = SuperPrompt()
    st.session_state.sp_a4 = SuperPrompt()

    _set_sidebar_pipeline_visual_step(SIDEBAR_STEP_PROMPT_QUALIFICATION)

    sp: SuperPrompt = st.session_state.sp
    sp = ctrl.preprocess(
        user_text,
        sp,
        memory_manager=st.session_state.get("memory_manager"),
    )

    st.session_state.sp = sp
    st.session_state.sp_pre = copy.deepcopy(sp)
    st.session_state["super_prompt_text"] = sp.prompt_ready


def do_a2_promptshaper() -> None:
    """A2 button callback."""
    if _guard_pipeline_running("A2 PromptShaper"):
        return

    ctrl: AppController = st.session_state.controller
    sp: SuperPrompt = st.session_state.sp

    use_llm = bool(st.session_state.get("use_a2_promptshaper_llm", True))

    _set_sidebar_pipeline_visual_step(SIDEBAR_STEP_PROMPT_SHAPING)

    sp = ctrl.run_a2_promptshaper(
        sp,
        use_llm=use_llm,
    )

    st.session_state.sp = sp
    st.session_state.sp_a2 = copy.deepcopy(sp)
    st.session_state["super_prompt_text"] = sp.prompt_ready


def do_feed_memory_manually() -> None:
    """Manual memory feed button callback."""
    if _guard_pipeline_running("Manual Memory Feed"):
        return

    prompt_text = st.session_state.get("prompt_text", "")
    output_text = st.session_state.get("manual_memory_feed_text", "")

    if not (prompt_text or "").strip():
        logger("Prompt is empty. No memory record was created.", "WARN", "PUBLIC")
        return

    if not (output_text or "").strip():
        logger("Manual memory response is empty. No memory record was created.", "WARN", "PUBLIC")
        return

    _save_memory_pair(
        input_text=prompt_text,
        output_text=output_text,
    )


def _save_memory_pair(
    input_text: str,
    output_text: str,
) -> None:
    try:
        ctrl: AppController = st.session_state.controller
        memory_manager: MemoryManager = st.session_state.memory_manager

        active_project_name, embedded_files_snapshot = _get_active_project_snapshot(ctrl)
        gui_records_state = _collect_memory_gui_state(memory_manager)

        result = capture_memory_pair(
            memory_manager=memory_manager,
            input_text=input_text,
            output_text=output_text,
            source="manual_memory_feed",
            active_project_name=active_project_name,
            embedded_files_snapshot=embedded_files_snapshot,
            gui_records_state=gui_records_state,
            memory_ingestion_manager=st.session_state.get("memory_ingestion_manager"),
        )

        if result.get("success"):
            st.session_state["manual_memory_feed_text"] = ""
            st.rerun()
        else:
            logger(result.get("message", "Memory record was not saved."), "WARN", "PUBLIC")

    except Exception as e:
        logger(str(e), "ERROR", "PUBLIC")


def _get_active_project_snapshot(ctrl: AppController) -> tuple[str | None, list[str]]:
    active_project = st.session_state.get("active_project")

    if not active_project or active_project == "(no projects yet)":
        return None, []

    try:
        embedded_info = ctrl.get_embedded_files(active_project)
    except Exception:
        return active_project, []

    if embedded_info.get("success"):
        return active_project, list(embedded_info.get("files", []))

    return active_project, []


def _collect_memory_gui_state(memory_manager: MemoryManager) -> list[dict[str, Any]]:
    gui_state: list[dict[str, Any]] = []

    for record in memory_manager.records:
        tag_key = f"memory_tag_{record.record_id}"
        source_mode_key = f"memory_retrieval_source_mode_{record.record_id}"
        keywords_key = f"memory_user_keywords_{record.record_id}"
        direct_recall_key = f"memory_direct_recall_key_{record.record_id}"

        tag = st.session_state.get(tag_key, record.tag)

        retrieval_source_mode = st.session_state.get(
            source_mode_key,
            getattr(record, "retrieval_source_mode", "QA"),
        )

        user_keywords_text = st.session_state.get(
            keywords_key,
            ", ".join(record.user_keywords),
        )

        direct_recall_value = st.session_state.get(
            direct_recall_key,
            getattr(record, "direct_recall_key", ""),
        )

        gui_state.append(
            {
                "record_id": record.record_id,
                "tag": tag,
                "retrieval_source_mode": retrieval_source_mode,
                "user_keywords": _parse_user_keywords(user_keywords_text),
                "direct_recall_key": str(direct_recall_value or "").strip(),
            }
        )

    return gui_state


def _parse_user_keywords(text: str) -> list[str]:
    raw_items = str(text or "").replace("\n", ",").split(",")

    result: list[str] = []
    seen: set[str] = set()

    for item in raw_items:
        keyword = item.strip()
        if not keyword:
            continue

        key = keyword.lower()
        if key in seen:
            continue

        result.append(keyword)
        seen.add(key)

    return result


def _ensure_memory_retrieval_configured(ctrl: AppController) -> None:
    """
    Defensive wiring for development.

    ui_streamlit.py normally configures MemoryRetriever at startup.
    This helper guarantees that Retrieval button still wires memory retrieval
    if the session was created before the new startup code existed.
    """
    if getattr(ctrl, "memory_retriever", None) is not None:
        return

    memory_manager = st.session_state.get("memory_manager")
    memory_vector_store = st.session_state.get("memory_vector_store")
    runtime_config = st.session_state.get("runtime_config", {})

    if memory_manager is None or memory_vector_store is None:
        logger(
            "Memory Retrieval is not configured because memory objects are missing.",
            "WARN",
            "PUBLIC",
        )
        return

    ctrl.configure_memory_retrieval(
        memory_manager=memory_manager,
        memory_vector_store=memory_vector_store,
        runtime_config=runtime_config,
    )


def _resolve_active_project(ctrl: AppController) -> str:
    project_name = st.session_state.get("active_project")
    if not project_name:
        available_projects = ctrl.list_projects()
        if available_projects:
            project_name = available_projects[0]
            st.session_state["active_project"] = project_name

    if not project_name or project_name == "(no projects yet)":
        raise ValueError("No active project is available.")

    return str(project_name)


def do_retrieval() -> None:
    """Retrieval button callback."""
    if _guard_pipeline_running("Retrieval"):
        return

    try:
        ctrl: AppController = st.session_state.controller
        sp: SuperPrompt = st.session_state.sp

        _ensure_memory_retrieval_configured(ctrl)

        project_name = _resolve_active_project(ctrl)

        top_k = int(st.session_state.get("retrieval_top_k", 100))
        use_retrieval_splade = bool(st.session_state.get("use_retrieval_splade", False))

        _set_sidebar_pipeline_visual_step(SIDEBAR_STEP_MEMORY_CONTEXT)

        sp = ctrl.run_retrieval(
            sp,
            project_name,
            top_k,
            use_retrieval_splade=use_retrieval_splade,
        )

        sp.compose_prompt_ready()

        st.session_state.sp = sp
        st.session_state.sp_rtv = copy.deepcopy(sp)

        # Retrieval now also initializes an A3-ready passthrough view
        # under views_by_stage["reranked"].
        # Therefore sp_rrk can safely mirror this state until real ColBERT
        # ReRanker overwrites it.
        st.session_state.sp_rrk = copy.deepcopy(sp)

        st.session_state["super_prompt_text"] = sp.prompt_ready

    except Exception as e:
        st.error(str(e))


def do_reranker() -> None:
    """ReRanker button callback."""
    if _guard_pipeline_running("ReRanker"):
        return

    try:
        ctrl: AppController = st.session_state.controller
        sp: SuperPrompt = st.session_state.sp

        if getattr(ctrl, "reranker", None) is None:
            st.error("ReRanker is not initialized yet.")
            return

        use_reranking_colbert = bool(st.session_state.get("use_reranking_colbert", False))

        _set_sidebar_pipeline_visual_step(SIDEBAR_STEP_MEMORY_CONTEXT)

        sp = ctrl.run_reranker(
            sp,
            use_reranking_colbert=use_reranking_colbert,
        )

        sp.compose_prompt_ready()

        st.session_state.sp = sp
        st.session_state.sp_rrk = copy.deepcopy(sp)
        st.session_state["super_prompt_text"] = sp.prompt_ready

    except Exception as e:
        st.error(str(e))


def do_a3_nli_gate() -> None:
    """A3 button callback."""
    if _guard_pipeline_running("A3 NLI Gate"):
        return

    try:
        ctrl: AppController = st.session_state.controller
        sp: SuperPrompt = st.session_state.sp

        _set_sidebar_pipeline_visual_step(SIDEBAR_STEP_DOCUMENT_EVIDENCE)

        sp = ctrl.run_a3(sp)

        st.session_state.sp = sp
        st.session_state.sp_a3 = copy.deepcopy(sp)
        st.session_state["super_prompt_text"] = sp.prompt_ready

    except Exception as e:
        st.error(str(e))


def do_a4_condenser() -> None:
    """A4 button callback."""
    if _guard_pipeline_running("A4 Condenser"):
        return

    try:
        ctrl: AppController = st.session_state.controller
        sp: SuperPrompt = st.session_state.sp

        _set_sidebar_pipeline_visual_step(SIDEBAR_STEP_CONTEXT_SYNTHESIS)

        sp = ctrl.run_a4(sp)
        sp.compose_prompt_ready()

        st.session_state.sp = sp
        st.session_state.sp_a4 = copy.deepcopy(sp)
        st.session_state["super_prompt_text"] = sp.prompt_ready

    except Exception as e:
        st.error(str(e))


def do_create_project() -> None:
    """Create Project form callback."""
    if _guard_pipeline_running("Create Project"):
        return

    try:
        ctrl: AppController = st.session_state.controller
        result = ctrl.create_project(st.session_state.get("new_project_name", ""))

        st.session_state["ingestion_status"] = {
            "type": "success",
            "message": f"Project created: {result['project_name']}",
            "details": [
                f"doc_raw: {result['raw_dir']}",
                f"chroma_db: {result['chroma_dir']}",
                f"manifest: {result['manifest_path']}",
            ],
        }
        st.session_state["pending_active_project"] = result["project_name"]
        st.rerun()

    except Exception as e:
        st.session_state["ingestion_status"] = {
            "type": "error",
            "message": str(e),
            "details": [],
        }


def do_add_files() -> None:
    """Add Files form callback."""
    if _guard_pipeline_running("Add Files"):
        return

    try:
        ctrl: AppController = st.session_state.controller

        result = ctrl.import_files_to_project(
            st.session_state.get("add_files_project", ""),
            uploaded_files=st.session_state.get("ingestion_uploaded_files"),
        )

        if result.get("success"):
            st.session_state["ingestion_status"] = {
                "type": "success",
                "message": (
                    f"Files added to {result['project_name']} "
                    f"and ingestion finished."
                ),
                "details": [
                    f"copied files: {result.get('copied_count', 0)}",
                    f"files scanned: {result.get('files_scanned', 0)}",
                    f"to process: {result.get('to_process', 0)}",
                    f"unchanged: {result.get('unchanged', 0)}",
                    f"vectors upserted: {result.get('vectors_upserted', 0)}",
                    f"manifest: {result.get('manifest_path', '')}",
                ] + [
                    f"rejected: {item}" for item in result.get("rejected_files", [])
                ],
            }
            st.session_state["pending_active_project"] = result["project_name"]
            st.rerun()
        else:
            st.session_state["ingestion_status"] = {
                "type": "error",
                "message": result.get("message", "No files were added."),
                "details": [
                    f"rejected: {item}" for item in result.get("rejected_files", [])
                ],
            }

    except Exception as e:
        st.session_state["ingestion_status"] = {
            "type": "error",
            "message": str(e),
            "details": [],
        }