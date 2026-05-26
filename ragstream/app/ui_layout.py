# ragstream/app/ui_layout.py
# -*- coding: utf-8 -*-
"""
Layout / geometry helpers for Streamlit UI.
Keep columns, containers, labels and visual order here.
"""

from __future__ import annotations

import html
import re
import time

from typing import Any

import streamlit as st

from ragstream.app.controller import AppController
from ragstream.app.ui_actions import (
    do_a2_promptshaper,
    do_a3_nli_gate,
    do_a4_condenser,
    do_add_files,
    do_create_project,
    do_feed_memory_manually,
    do_preprocess,
    do_reranker,
    do_retrieval,
    do_user_prompt_changed,
    request_prompt_builder_run,
    run_next_prompt_builder_step,
)

TAG_COLORS: dict[str, str] = {
    "Gold": "#D4AF37",
    "Green": "#00A86B",
    "Black": "#111111",
}

MEMORY_HEIGHT = 650
PROMPT_HEIGHT = 180
ENGINEERED_PROMPT_EXPANDED_HEIGHT = 1200
MANUAL_MEMORY_FEED_HEIGHT = 68
RUNTIME_LOG_HEIGHT = 150
EMBEDDED_FILES_HEIGHT = 120

MAIN_COLUMNS = [4, 0.25, 4]
ACTION_ROW_COLUMNS = [1.15, 3.35]
MODEL_ROW_COLUMNS = [1.15, 1.1, 2.25]
ENGINEERED_PROMPT_COLUMNS = [20, 1.8]
ADVANCED_TOPK_COLUMNS = [0.9, 3.1]
MEMORY_RECORD_COLUMNS = [8.8, 1.0]
MEMORY_TAG_COLUMNS = [0.22, 1.0]
PROJECT_HALF_COLUMNS = [1, 1]


def _vertical_gap(height: str) -> None:
    """Render a small vertical spacer."""
    st.markdown(f"<div style='height:{height}'></div>", unsafe_allow_html=True)


def _memory_display_name(filename_ragmem: str | None) -> tuple[str, str]:
    """Return clean visible memory name plus real source filename."""
    filename = str(filename_ragmem or "").strip()

    if not filename:
        return "Memory", ""

    visible_name = re.sub(r"(?i)\.ragmem$", "", filename)
    visible_name = re.sub(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-", "", visible_name)
    visible_name = visible_name.strip() or filename

    return visible_name, filename


def _model_options() -> list[str]:
    return [
        "OpenAI GPT-5.5",
        "OpenAI GPT-5.4",
        "OpenAI o3",
        "OpenAI o2",
        "OpenAI GPT-5 mini",
        "OpenAI GPT-5 nano",
        "Claude Opus 4.1",
        "Claude Sonnet 4.5",
        "Claude Haiku 3.5",
        "Gemini 2.5 Pro",
        "Gemini 2.5 Flash",
        "Gemini 2.0 Flash",
        "Local / Custom",
    ]


def _base_page_css() -> str:
    return """
        header,
        header[data-testid="stHeader"],
        div[data-testid="stHeader"] {
            display: none !important;
            height: 0 !important;
        }

        /* Prevent accidental sidebar collapse */
        button[aria-label="Close sidebar"],
        button[title="Close sidebar"],
        [data-testid="stSidebarCollapseButton"] {
            display: none !important;
        }

        .block-container {
            padding-top: 0.65rem;
            padding-bottom: 0rem;
            padding-left: 0.65rem;
            padding-right: 0.65rem;
        }

        div[data-testid="stHorizontalBlock"] {
            gap: 0.45rem !important;
        }

        div[data-baseweb="select"] > div {
            min-height: 34px;
        }
    """


def _product_identity_css() -> str:
    return """
        .ghost-product-title {
            font-size: 2.0rem;
            font-weight: 520;
            font-style: italic;
            letter-spacing: -0.025em;
            color: #7A1E1E;
            line-height: 1.15;
            margin: 0.10rem 0 0.18rem 0;
        }

        .ghost-product-title .brand-initial {
            font-weight: 800;
        }

        .ghost-product-subtitle {
            font-size: 0.88rem;
            color: #6B7280;
            line-height: 1.25;
            margin-bottom: 0.55rem;
        }
    """


def _title_css() -> str:
    return """
        .field-title,
        .panel-title,
        .memory-title {
            font-size: 1.08rem;
            font-weight: 600;
            line-height: 1.2;
            margin-bottom: 0.30rem;
            color: #1F2937;
            letter-spacing: -0.010em;
        }

        .memory-title {
            font-size: 1.12rem;
            margin-bottom: 0.08rem;
        }
    """


def _memory_css() -> str:
    return """
        .memory-box {
            border-radius: 0.45rem;
            padding: 0.55rem 0.70rem;
            border: 1px solid #d8d8d8;
            font-size: 1.02rem;
            line-height: 1.38;
            white-space: normal;
            word-break: break-word;
        }

        .memory-input-box {
            background-color: #ffffff;
        }

        .memory-output-box {
            background-color: #f3f4f6;
        }

        .memory-label {
            font-size: 0.78rem;
            font-weight: 650;
            margin-bottom: 0.25rem;
            color: #4b5563;
            letter-spacing: 0.02em;
        }

        .memory-plain-text {
            white-space: pre-wrap;
            font-size: 1.02rem;
            line-height: 1.38;
            margin: 0;
            font-family: inherit;
        }

        .memory-tag-indicator {
            display: flex;
            align-items: center;
            gap: 0.35rem;
            margin-bottom: 0.25rem;
            min-height: 24px;
        }

        .memory-tag-square {
            width: 18px;
            height: 18px;
            border-radius: 0.25rem;
            border: 1px solid rgba(0, 0, 0, 0.25);
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.16);
            flex: 0 0 auto;
        }
    """


def _button_css() -> str:
    return """
div[data-testid="stButton"] > button[kind="primary"] {
    background-color: #22B14C !important;
    border-color: #22B14C !important;
    color: white !important;
    font-weight: 800 !important;
}

div[data-testid="stButton"] > button[kind="primary"]:hover,
div[data-testid="stButton"] > button[kind="primary"]:focus {
    background-color: #22B14C !important;
    border-color: #22B14C !important;
    color: white !important;
}

        div[data-testid="stButton"] > button[kind="primary"] p {
            color: white !important;
            font-weight: 800 !important;
        }

        /* Prompt Builder intentionally uses the normal Streamlit button style. */

        .st-key-btn_feed_memory_manually button {
            background-color: #00A2E8 !important;
            border-color: #00A2E8 !important;
            color: white !important;
            font-weight: 650 !important;
        }

        .st-key-btn_feed_memory_manually button:hover,
        .st-key-btn_feed_memory_manually button:focus {
            background-color: #00A2E8 !important;
            border-color: #00A2E8 !important;
            color: white !important;
        }

        .st-key-btn_feed_memory_manually button p {
            color: white !important;
            font-weight: 650 !important;
        }
    """


def _form_field_css() -> str:
    return """
        textarea[aria-label="Manual Memory Feed (hidden)"] {
            background-color: #EAF7FF !important;
        }

        div[data-testid="stTextInput"]:has(input[aria-label="Direct Recall Key"]) div[data-baseweb="input"] {
            border: 2px solid #D11A2A !important;
            border-radius: 0.45rem !important;
            box-shadow: none !important;
        }

        div[data-testid="stTextInput"]:has(input[aria-label="Direct Recall Key"]) div[data-baseweb="input"]:focus-within {
            border: 2px solid #D11A2A !important;
            box-shadow: 0 0 0 1px rgba(209, 26, 42, 0.25) !important;
        }
    """


def _runtime_log_css() -> str:
    return """
        .textforge-log-box {
            background-color: #EAFBEA;
            border: 1px solid #B7E4B7;
            border-radius: 0.45rem;
            padding: 0.55rem 0.70rem;
            min-height: 140px;
            max-height: 180px;
            overflow-y: auto;
            white-space: normal;
            word-break: break-word;
            font-family: monospace;
            font-size: 0.88rem;
            line-height: 1.35;
        }
    """


def inject_base_css() -> None:
    """Global CSS for page spacing, product identity, panels, and buttons."""
    css = "\n".join(
        [
            _base_page_css(),
            _product_identity_css(),
            _title_css(),
            _memory_css(),
            _button_css(),
            _form_field_css(),
            _runtime_log_css(),
        ]
    )

    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def render_page() -> None:
    """
    MAIN page layout:
    - Product identity header
    - Full-width Memory area
    - LEFT: User Prompt + main actions
    - RIGHT: Engineered Prompt + project/file context
    """
    render_product_identity_header()
    render_memory_records(height=MEMORY_HEIGHT)

    _vertical_gap("0.55rem")

    col_user, spacer, col_engineered = st.columns(MAIN_COLUMNS, gap="small")

    with col_user:
        render_user_prompt_panel()
        render_main_action_controls()
        render_pipeline_status()

        _vertical_gap("0.45rem")
        render_textforge_gui_log(height=RUNTIME_LOG_HEIGHT)

        if st.session_state.get("show_advanced_controls", False):
            _vertical_gap("0.55rem")
            render_advanced_controls()

        # Must run after status/log rendering, but before Engineered Prompt widget creation.
        run_next_prompt_builder_step()

    with spacer:
        st.empty()

    with col_engineered:
        render_engineered_prompt_panel()

        _vertical_gap("0.55rem")

        ctrl: AppController = st.session_state.controller
        render_project_area(
            ctrl,
            show_ingestion_controls=bool(
                st.session_state.get("enable_file_ingestion_controls", False)
            ),
        )


def render_product_identity_header() -> None:
    """Render the MAIN-page product identity."""
    st.markdown(
        """
        <div class="ghost-product-title">
            <span class="brand-initial">G</span>enAI
            <span class="brand-initial">H</span>ybrid
            <span class="brand-initial">O</span>rchestrator
            for
            <span class="brand-initial">S</span>oftware
            <span class="brand-initial">T</span>ooling
            <span style="font-style:normal; font-weight:700;">(GHOST)</span>
        </div>
        <div class="ghost-product-subtitle">
            Professional prompt orchestration, memory, retrieval, and software-tooling workflow control.
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_user_prompt_panel() -> None:
    """Left column: User Prompt."""
    st.markdown('<div class="panel-title">User Prompt</div>', unsafe_allow_html=True)

    st.text_area(
        label="Prompt (hidden)",
        key="prompt_text",
        height=180,
        label_visibility="collapsed",
        on_change=do_user_prompt_changed,
    )


def render_engineered_prompt_panel() -> None:
    """Right column: Engineered Prompt with compact/expanded display."""
    if "engineered_prompt_expanded" not in st.session_state:
        st.session_state["engineered_prompt_expanded"] = False

    expanded = bool(st.session_state.get("engineered_prompt_expanded", False))
    prompt_height = ENGINEERED_PROMPT_EXPANDED_HEIGHT if expanded else PROMPT_HEIGHT

    st.markdown('<div class="panel-title">Engineered Prompt</div>', unsafe_allow_html=True)

    prompt_col, expand_col = st.columns(ENGINEERED_PROMPT_COLUMNS, gap="small")

    with prompt_col:
        st.text_area(
            label="Engineered Prompt (hidden)",
            key="super_prompt_text",
            height=prompt_height,
            label_visibility="collapsed",
        )

    with expand_col:
        toggle_label = "⟪" if expanded else "⟫"
        if st.button(
            toggle_label,
            key="btn_toggle_engineered_prompt",
            use_container_width=True,
            help="Expand / collapse Engineered Prompt",
        ):
            st.session_state["engineered_prompt_expanded"] = not expanded
            st.rerun()


def render_main_action_controls() -> None:
    """Left column: main execution controls below User Prompt."""
    _vertical_gap("0.45rem")

    _render_llm_call_row()
    _render_prompt_builder_row()
    _render_manual_memory_feed_row()

    _vertical_gap("0.45rem")


def _render_prompt_builder_row() -> None:
    action_col, detail_col = st.columns(ACTION_ROW_COLUMNS, gap="small")

    with action_col:
        if st.button(
            "Prompt Builder",
            key="btn_builder",
            use_container_width=True,
        ):
            request_prompt_builder_run()

    with detail_col:
        cb1, cb2, cb3 = st.columns(3, gap="small")

        with cb1:
            use_a2_promptshaper_llm = st.checkbox(
                "use PromptShaper",
                key="use_a2_promptshaper_llm_widget",
            )

        with cb2:
            use_retrieval_splade = st.checkbox(
                "use Retrieval Splade",
                key="use_retrieval_splade_widget",
            )

        with cb3:
            use_reranking_colbert = st.checkbox(
                "use Reranking Colbert",
                key="use_reranking_colbert_widget",
            )

        st.session_state["use_a2_promptshaper_llm"] = bool(use_a2_promptshaper_llm)
        st.session_state["use_retrieval_splade"] = bool(use_retrieval_splade)
        st.session_state["use_reranking_colbert"] = bool(use_reranking_colbert)


def _render_llm_call_row() -> None:
    action_col, model_col, model_spacer = st.columns(MODEL_ROW_COLUMNS, gap="small")

    with action_col:
        if st.button(
            "LLM Call",
            key="btn_llm_call",
            use_container_width=True,
            type="primary",
        ):
            st.session_state["llm_call_status"] = "LLM Call requested."

    with model_col:
        st.selectbox(
            "Model",
            options=_model_options(),
            key="selected_llm_model",
            label_visibility="collapsed",
        )

    with model_spacer:
        st.empty()


def _render_manual_memory_feed_row() -> None:
    action_col, detail_col = st.columns(ACTION_ROW_COLUMNS, gap="small")

    with action_col:
        if st.button(
            "Feed Memory Manually",
            key="btn_feed_memory_manually",
            use_container_width=True,
        ):
            do_feed_memory_manually()

    with detail_col:
        st.text_area(
            label="Manual Memory Feed (hidden)",
            key="manual_memory_feed_text",
            height=MANUAL_MEMORY_FEED_HEIGHT,
            label_visibility="collapsed",
            placeholder="Paste LLM reply here for manual memory feed.",
        )


def render_advanced_controls() -> None:
    """Advanced/debug controls shown only when enabled from the sidebar."""
    st.markdown('<div class="panel-title">Advanced Controls</div>', unsafe_allow_html=True)

    _normalise_retrieval_top_k_widget()
    _render_retrieval_top_k_control()
    _render_manual_pipeline_buttons()


def _normalise_retrieval_top_k_widget() -> None:
    if "retrieval_top_k_widget" not in st.session_state:
        st.session_state["retrieval_top_k_widget"] = int(
            st.session_state.get("retrieval_top_k", 30) or 30
        )


def _render_retrieval_top_k_control() -> None:
    topk_c, gap_c = st.columns(ADVANCED_TOPK_COLUMNS, gap="small")

    with topk_c:
        selected_top_k = st.number_input(
            "Retrieval Top-K",
            min_value=1,
            max_value=1000,
            step=1,
            key="retrieval_top_k_widget",
        )

        st.session_state["retrieval_top_k"] = int(selected_top_k)

    with gap_c:
        st.empty()


def _render_manual_pipeline_buttons() -> None:
    b1c1, b1c2, b1c3, b1c4 = st.columns(4, gap="small")

    with b1c1:
        if st.button("Pre-Processing", key="btn_preproc", use_container_width=True):
            do_preprocess()

    with b1c2:
        if st.button("A2-PromptShaper", key="btn_a2", use_container_width=True):
            do_a2_promptshaper()

    with b1c3:
        if st.button("Retrieval", key="btn_retrieval", use_container_width=True):
            do_retrieval()

    with b1c4:
        if st.button("ReRanker", key="btn_reranker", use_container_width=True):
            do_reranker()

    b2c1, b2c2, b2c3, b2c4 = st.columns(4, gap="small")

    with b2c1:
        if st.button("A3 NLI Gate", key="btn_a3", use_container_width=True):
            do_a3_nli_gate()

    with b2c2:
        if st.button("A4 Condenser", key="btn_a4", use_container_width=True):
            do_a4_condenser()

    with b2c3:
        st.button("A5 Format Enforcer", key="btn_a5", use_container_width=True)

    with b2c4:
        st.empty()


def render_pipeline_status() -> Any:
    """Render only the Prompt Builder pipeline progress bar."""
    status = st.session_state.get("pipeline_status")
    if not isinstance(status, dict):
        status = {
            "stage_name": "Idle",
            "step_index": 0,
            "total_steps": 8,
            "message": "No pipeline run active.",
            "progress": 0.0,
        }

    stage_name = str(status.get("stage_name", "Idle") or "Idle")
    step_index = int(status.get("step_index", 0) or 0)
    total_steps = int(status.get("total_steps", 8) or 8)
    progress = float(status.get("progress", 0.0) or 0.0)

    st.progress(
        progress,
        text=f"{step_index}/{total_steps} — {stage_name}",
    )


def render_textforge_gui_log(height: int = RUNTIME_LOG_HEIGHT) -> None:
    """Render the TextForge GUI log box."""
    st.markdown(
        '<div class="field-title" style="font-size:1.05rem;">Runtime Log</div>',
        unsafe_allow_html=True,
    )

    log_html = _build_textforge_log_html()
    log_box_style = _runtime_log_box_style(height=height)

    st.markdown(
        f'<div class="textforge-log-box" style="{log_box_style}">{log_html}</div>',
        unsafe_allow_html=True,
    )


def _build_textforge_log_html() -> str:
    log_text = st.session_state.get("textforge_gui_log", "")
    if not log_text:
        log_text = "(no log messages yet)"

    lines = log_text.splitlines()
    if not lines:
        return ""

    first_line = html.escape(lines[0])
    older_lines = "<br>".join(
        f"<i>{html.escape(line)}</i>"
        for line in lines[1:]
    )

    if older_lines:
        return f"{first_line}<br>{older_lines}"

    return first_line


def _runtime_log_box_style(height: int) -> str:
    flash_active = time.time() < st.session_state.get("runtime_log_flash_until", 0)

    if flash_active:
        return (
            f"min-height:{height}px; max-height:{height}px;"
            "background-color:#FFE5E5; border-color:#FF9A9A;"
        )

    return f"min-height:{height}px; max-height:{height}px;"


def render_memory_records(height: int = MEMORY_HEIGHT) -> None:
    """Memory record list."""
    memory_manager = st.session_state.memory_manager

    _render_memory_title(memory_manager)

    memory_entries = memory_manager.records

    try:
        memory_container = st.container(height=height)
    except TypeError:
        memory_container = st.container()

    with memory_container:
        if not memory_entries:
            st.info("No memory records yet.")
            return

        for record in memory_entries:
            _render_memory_record(memory_manager, record)


def _render_memory_title(memory_manager: Any) -> None:
    memory_title, memory_source_file = _memory_display_name(
        getattr(memory_manager, "filename_ragmem", "")
    )

    if memory_source_file:
        st.markdown(
            f"""
            <div class="memory-title">
                {html.escape(memory_title)}
            </div>
            <div style="
                font-size:0.66rem;
                color:#6b7280;
                line-height:1.1;
                margin-top:-0.02rem;
                margin-bottom:0.30rem;
            ">
                extracted from {html.escape(memory_source_file)}
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        f'<div class="memory-title">{html.escape(memory_title)}</div>',
        unsafe_allow_html=True,
    )


def _memory_record_keys(record: Any) -> tuple[str, str, str, str]:
    return (
        f"memory_tag_{record.record_id}",
        f"memory_retrieval_source_mode_{record.record_id}",
        f"memory_user_keywords_{record.record_id}",
        f"memory_direct_recall_key_{record.record_id}",
    )


def _ensure_memory_record_session_state(
    memory_manager: Any,
    record: Any,
    tag_key: str,
    source_mode_key: str,
    keywords_key: str,
    direct_recall_key: str,
) -> list[str]:
    tag_options = list(memory_manager.tag_catalog)
    record_tag = record.tag if record.tag in tag_options else "Green"

    if tag_key not in st.session_state:
        st.session_state[tag_key] = record_tag
    elif st.session_state[tag_key] not in tag_options:
        st.session_state[tag_key] = "Green"

    if source_mode_key not in st.session_state:
        st.session_state[source_mode_key] = getattr(record, "retrieval_source_mode", "QA")
    elif st.session_state[source_mode_key] not in {"QA", "Q", "A"}:
        st.session_state[source_mode_key] = "QA"

    if keywords_key not in st.session_state:
        st.session_state[keywords_key] = ", ".join(record.user_keywords)

    if direct_recall_key not in st.session_state:
        st.session_state[direct_recall_key] = getattr(record, "direct_recall_key", "")

    return tag_options


def _render_memory_record(memory_manager: Any, record: Any) -> None:
    tag_key, source_mode_key, keywords_key, direct_recall_key = _memory_record_keys(record)

    tag_options = _ensure_memory_record_session_state(
        memory_manager=memory_manager,
        record=record,
        tag_key=tag_key,
        source_mode_key=source_mode_key,
        keywords_key=keywords_key,
        direct_recall_key=direct_recall_key,
    )

    selected_tag = st.session_state.get(tag_key, record.tag)
    tag_color = TAG_COLORS.get(selected_tag, "#6B7280")

    input_col, meta_col = st.columns(MEMORY_RECORD_COLUMNS, gap="small")

    with input_col:
        _render_memory_record_input(record)

    with meta_col:
        _render_memory_record_meta(
            tag_key=tag_key,
            tag_options=tag_options,
            tag_color=tag_color,
            source_mode_key=source_mode_key,
            direct_recall_key=direct_recall_key,
        )

    _render_memory_record_output(record)

    _vertical_gap("0.40rem")


def _render_memory_record_input(record: Any) -> None:
    input_html = html.escape(record.input_text).replace("\n", "<br>")

    st.markdown(
        f"""
        <div class="memory-box memory-input-box">
            <div class="memory-label">INPUT</div>
            <div class="memory-plain-text">{input_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_memory_record_meta(
    tag_key: str,
    tag_options: list[str],
    tag_color: str,
    source_mode_key: str,
    direct_recall_key: str,
) -> None:
    tag_square_col, tag_select_col = st.columns(MEMORY_TAG_COLUMNS, gap="small")

    with tag_square_col:
        st.markdown(
            f"""
            <div class="memory-tag-indicator">
                <span class="memory-tag-square" style="background-color:{tag_color};"></span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with tag_select_col:
        st.selectbox(
            "Tag",
            options=tag_options,
            key=tag_key,
            label_visibility="collapsed",
        )

    st.selectbox(
        "Retrieval Source Mode",
        options=["QA", "Q", "A"],
        key=source_mode_key,
        format_func={
            "QA": "Retrieve Q+A",
            "Q": "Retrieve only Q",
            "A": "Retrieve only A",
        }.get,
        label_visibility="collapsed",
    )

    st.text_input(
        "Direct Recall Key",
        key=direct_recall_key,
        placeholder="Direct Recall Key",
    )


def _render_memory_record_output(record: Any) -> None:
    output_html = html.escape(record.output_text).replace("\n", "<br>")

    st.markdown(
        f"""
        <div class="memory-box memory-output-box">
            <div class="memory-label">OUTPUT</div>
            <div class="memory-plain-text">{output_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_project_area(ctrl: AppController, show_ingestion_controls: bool = False) -> None:
    """
    Project selector, embedded files, and optional file-ingestion controls.
    """
    projects = ctrl.list_projects()

    _sync_pending_project(projects)

    st.markdown('<div class="panel-title">Project Context</div>', unsafe_allow_html=True)

    _render_project_selector(projects)
    _render_embedded_files(ctrl, projects)

    if show_ingestion_controls:
        _vertical_gap("0.45rem")
        _render_file_ingestion_controls(ctrl)

    _render_ingestion_status()


def _sync_pending_project(projects: list[str]) -> None:
    pending_project = st.session_state.get("pending_active_project")
    if pending_project is None:
        return

    if projects and pending_project in projects:
        st.session_state["active_project"] = pending_project

    st.session_state["pending_active_project"] = None


def _render_project_selector(projects: list[str]) -> None:
    project_col, project_spacer = st.columns(PROJECT_HALF_COLUMNS, gap="small")

    with project_col:
        if projects:
            if st.session_state.get("active_project") not in projects:
                st.session_state["active_project"] = projects[0]

            st.selectbox(
                "Active DB / Project",
                options=projects,
                key="active_project",
            )
        else:
            st.selectbox(
                "Active DB / Project",
                options=["(no projects yet)"],
                index=0,
                disabled=True,
            )

    with project_spacer:
        st.empty()


def _render_embedded_files(ctrl: AppController, projects: list[str]) -> None:
    active_project = st.session_state.get("active_project")
    if not projects or active_project not in projects:
        return

    embedded_info = ctrl.get_embedded_files(active_project)

    _vertical_gap("0.25rem")

    embedded_col, embedded_spacer = st.columns(PROJECT_HALF_COLUMNS, gap="small")

    with embedded_col:
        st.markdown(
            '<div class="panel-title" style="font-size:0.95rem;">Embedded Files</div>',
            unsafe_allow_html=True,
        )

        if embedded_info.get("success"):
            embedded_files = embedded_info.get("files", [])
            embedded_text = "\n".join(embedded_files) if embedded_files else "(no embedded files yet)"
            st.text_area(
                label="Embedded Files (hidden)",
                value=embedded_text,
                height=EMBEDDED_FILES_HEIGHT,
                disabled=True,
                label_visibility="collapsed",
            )
        else:
            st.error(embedded_info.get("message", "Could not read embedded file list."))

    with embedded_spacer:
        st.empty()


def _render_file_ingestion_controls(ctrl: AppController) -> None:
    st.markdown('<div class="panel-title">File Ingestion Controls</div>', unsafe_allow_html=True)

    create_col, add_col = st.columns(2, gap="small")

    with create_col:
        _render_create_project_form()

    with add_col:
        _render_add_files_form(ctrl)


def _render_create_project_form() -> None:
    with st.form("create_project_form", clear_on_submit=False):
        st.text_input("Project Name", key="new_project_name")
        create_clicked = st.form_submit_button("Create Project", use_container_width=True)

        if create_clicked:
            do_create_project()


def _render_add_files_form(ctrl: AppController) -> None:
    with st.form("add_files_form", clear_on_submit=False):
        add_projects = ctrl.list_projects()

        if not add_projects:
            st.info("Create a project first, then add files.")
            return

        current_active_project = st.session_state.get("active_project")
        if current_active_project in add_projects:
            default_add_project = current_active_project
        else:
            default_add_project = add_projects[0]

        st.selectbox(
            "Choose Project",
            options=add_projects,
            key="add_files_project",
            index=add_projects.index(default_add_project),
        )

        st.file_uploader(
            "Select .txt / .md files from your local machine",
            type=["txt", "md"],
            accept_multiple_files=True,
            key="ingestion_uploaded_files",
        )

        add_clicked = st.form_submit_button("Add Files", use_container_width=True)

        if add_clicked:
            do_add_files()


def _render_ingestion_status() -> None:
    status = st.session_state.get("ingestion_status")
    if not status:
        return

    if status.get("type") == "success":
        st.success(status.get("message", ""))
    else:
        st.error(status.get("message", ""))

    for detail in status.get("details", []):
        st.caption(detail)