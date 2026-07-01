# ragstream/app/ui_layout.py
# -*- coding: utf-8 -*-
"""
Layout / geometry helpers for Streamlit UI.
Keep columns, containers, labels and visual order here.
"""

from __future__ import annotations

import base64
import html
import re
import time

from pathlib import Path

from typing import Any, Callable

import streamlit as st

from ragstream.app.controller import AppController
from ragstream.app.ui_actions import (
    LivePipelineSurfaces,
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
    run_prompt_builder_live,
)

FONT_FAMILY = (
    '"Manrope", -apple-system, BlinkMacSystemFont, '
    '"Segoe UI", Roboto, Helvetica, Arial, sans-serif'
)

COLOR_PRIMARY = "#004643"
COLOR_SECONDARY = "#afcecc"
COLOR_SURFACE = "#edeae3"
COLOR_FIELD_BACKGROUND = "#DCE7EE"
COLOR_SURFACE_MUTED = "#f7f6f1"
COLOR_INPUT_BACKGROUND = COLOR_FIELD_BACKGROUND
COLOR_PANEL = "#ffffff"
COLOR_BORDER = "#000000"
COLOR_TEXT = "#000000"
COLOR_TEXT_MUTED = "#6B7280"
COLOR_TEXT_SOFT = "#6B7280"
COLOR_TEXT_INVERSE = "#ffffff"
COLOR_BUTTON_MAIN = "#edeae3"
COLOR_BUTTON_ACTION = "#004643"
COLOR_BUTTON_MEMORY = "#afcecc"
COLOR_PRIORITY_BORDER = "#004643"
COLOR_EXCLUDED_TEXT = "#8A8F93"
COLOR_RUNTIME_LOG_BG = "#afcecc"
COLOR_RUNTIME_LOG_BORDER = "#004643"
COLOR_FLASH_BG = "#FFE5E5"
COLOR_FLASH_BORDER = "#FF9A9A"

TAG_DISPLAY_LABELS: dict[str, str] = {
    "Green": "Standard",
    "Gold": "Priority",
    "Black": "Excluded",
}

BLACKBOARD_ACTOR_OPTIONS: list[str] = [
    "Programmer — Claude Sonnet 4.5",
    "Watchdog — Claude Sonnet 4.5",
    "Auditor — ChatGPT 5.5",
    "Documentation Lead — ChatGPT 5.5",
]

MEMORY_HEIGHT = 1000
MEMORY_PANEL_HEIGHT = 1000

PROMPT_HEIGHT = 180
ENGINEERED_PROMPT_EXPANDED_HEIGHT = 1200
MANUAL_MEMORY_FEED_HEIGHT = 68
RUNTIME_LOG_HEIGHT = 150
EMBEDDED_FILES_HEIGHT = 120

MAIN_COLUMNS = [4.2, 0.25, 4.8]
ACTION_ROW_COLUMNS = [1.15, 3.35]
MODEL_ROW_COLUMNS = [1.15, 1.1, 2.25]
ENGINEERED_PROMPT_COLUMNS = [20, 1.8]
ADVANCED_TOPK_COLUMNS = [0.9, 3.1]
MEMORY_META_AREA_COLUMNS = [0.95, 0.05]
MEMORY_META_ROW_COLUMNS = [1.00, 0.80, 2.0, 0.62, 1.18]
PROJECT_HALF_COLUMNS = [1, 1]

MAIN_WORKSPACE_TITLE = "Prompt Workspace"
MAIN_WORKSPACE_SUBTITLE = (
    "Prompt orchestration, memory retrieval, and agentic software-tooling workflow control."
)

SIDEBAR_PRODUCT_SUBTITLE = "GenAI Hybrid Orchestrator<br>for Software Tooling"

GHOST_LOGO_CANDIDATE_PATHS = (
    "ragstream/app/assets/Ghost-Logo-08.png",
    "assets/Ghost-Logo-08.png",
    "doc/04-GUI/Ghost-Logo-08.png",
    "docs/04-GUI/Ghost-Logo-08.png",
    "Ghost-Logo-08.png",
)


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


def _theme_css() -> str:
    return f"""
        @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap');

        html,
        body,
        .stApp,
        button,
        input,
        textarea,
        select,
        [class*="css"] {{
            font-family: {FONT_FAMILY} !important;
        }}

        .stApp {{
            background-color: {COLOR_PANEL};
            color: {COLOR_TEXT};
        }}
    """


def _base_page_css() -> str:
    return f"""
        header,
        header[data-testid="stHeader"],
        div[data-testid="stHeader"] {{
            display: none !important;
            height: 0 !important;
        }}

        button[aria-label="Close sidebar"],
        button[title="Close sidebar"],
        [data-testid="stSidebarCollapseButton"] {{
            display: none !important;
        }}

        .block-container {{
            padding-top: 0.65rem;
            padding-bottom: 0rem;
            padding-left: 0.65rem;
            padding-right: 0.65rem;
        }}

        div[data-testid="stHorizontalBlock"] {{
            gap: 0.45rem !important;
        }}

        div[data-baseweb="select"] > div {{
            min-height: 34px;
        }}

        textarea,
        div[data-baseweb="select"] > div,
        div[data-baseweb="input"] {{
            background-color: {COLOR_INPUT_BACKGROUND} !important;
            border-color: {COLOR_BORDER}33 !important;
            box-shadow: none !important;
        }}

        textarea:focus,
        div[data-baseweb="select"] > div:focus-within,
        div[data-baseweb="input"]:focus-within {{
            background-color: {COLOR_INPUT_BACKGROUND} !important;
            border-color: {COLOR_PRIMARY} !important;
            box-shadow: 0 0 0 1px {COLOR_SECONDARY} !important;
        }}

        textarea:disabled,
        div[data-baseweb="input"][aria-disabled="true"] {{
            background-color: {COLOR_INPUT_BACKGROUND} !important;
            color: {COLOR_TEXT} !important;
            opacity: 1 !important;
        }}
    """


def _product_identity_css() -> str:
    return f"""
        .ghost-product-title {{
            font-size: 2.0rem;
            font-weight: 650;
            letter-spacing: -0.025em;
            color: {COLOR_PRIMARY};
            line-height: 1.15;
            margin: 0.10rem 0 0.18rem 0;
        }}

        .ghost-product-title .brand-initial {{
            font-weight: 800;
        }}

        .ghost-product-subtitle {{
            font-size: 0.88rem;
            color: {COLOR_TEXT_MUTED};
            line-height: 1.25;
            margin-bottom: 0.55rem;
        }}
    """


def _sidebar_brand_css() -> str:
    return f"""
        .ghost-sidebar-brand {{
            padding: 0.25rem 0.25rem 0.92rem 0.25rem;
        }}

        .ghost-sidebar-logo {{
            width: 100%;
            max-width: 210px;
            margin: 0 0 0.52rem 0;
            display: block;
        }}

        .ghost-sidebar-subtitle {{
            font-size: 0.94rem;
            font-weight: 650;
            color: {COLOR_TEXT_MUTED};
            line-height: 1.28;
            letter-spacing: -0.010em;
            margin-top: 0.05rem;
        }}

        .ghost-sidebar-fallback-title {{
            font-size: 1.75rem;
            font-weight: 850;
            letter-spacing: 0.055em;
            color: {COLOR_PRIMARY};
            line-height: 1.0;
            margin-bottom: 0.48rem;
        }}
    """


def _title_css() -> str:
    return f"""
        .field-title,
        .panel-title,
        .memory-title {{
            font-size: 1.08rem;
            font-weight: 700;
            line-height: 1.2;
            margin-bottom: 0.30rem;
            color: {COLOR_TEXT};
            letter-spacing: -0.010em;
        }}

        .memory-title {{
            font-size: 1.12rem;
            margin-bottom: 0.08rem;
        }}
    """


def _memory_css() -> str:
    return f"""
        .memory-content-shell {{
            border-radius: 0.55rem;
            padding: 0.10rem 0.10rem 0.20rem 0.10rem;
            margin-bottom: 0.40rem;
        }}

        .memory-content-shell.priority {{
            border: 2px solid {COLOR_PRIORITY_BORDER};
            padding: 0.55rem 0.60rem 0.65rem 0.60rem;
            background-color: {COLOR_PANEL};
        }}

        .memory-content-shell.excluded {{
            opacity: 0.68;
        }}

        .memory-request-box {{
            border: none;
            border-radius: 0.45rem;
            padding: 0.35rem 0.25rem 0.45rem 0.25rem;
            background-color: {COLOR_PANEL};
            font-size: 1.00rem;
            line-height: 1.36;
            white-space: normal;
            word-break: break-word;
        }}

        .memory-response-box {{
            border-radius: 0.45rem;
            padding: 0.55rem 0.70rem;
            border: 1.5px solid {COLOR_BORDER};
            background-color: {COLOR_BUTTON_MAIN};
            font-size: 1.00rem;
            line-height: 1.36;
            white-space: normal;
            word-break: break-word;
        }}

        .memory-label {{
            font-size: 0.92rem;
            font-weight: 800;
            margin-bottom: 0.25rem;
            color: {COLOR_PRIMARY};
            letter-spacing: 0.02em;
        }}

        .memory-content-shell.priority .memory-label {{
            font-size: 0.96rem;
            font-weight: 850;
        }}

        .memory-content-shell.excluded .memory-label,
        .memory-content-shell.excluded .memory-plain-text {{
            color: {COLOR_EXCLUDED_TEXT};
        }}

        .memory-plain-text {{
            white-space: pre-wrap;
            font-size: 1.00rem;
            line-height: 1.36;
            margin: 0;
            font-family: inherit;
            color: {COLOR_TEXT};
        }}

        .memory-meta-label {{
            display: flex;
            align-items: center;
            justify-content: flex-end;
            min-height: 34px;
            padding-right: 0.12rem;
            font-size: 0.78rem;
            font-weight: 750;
            color: {COLOR_TEXT};
            white-space: nowrap;
        }}
    """


def _button_css() -> str:
    return f"""
        div[data-testid="stButton"] > button {{
            border-radius: 0.35rem !important;
            border: 1.5px solid {COLOR_BORDER} !important;
            font-weight: 700 !important;
        }}

        div[data-testid="stButton"] > button p {{
            font-weight: 700 !important;
        }}

        div[data-testid="stButton"] > button[kind="primary"] {{
            background-color: {COLOR_BUTTON_ACTION} !important;
            border-color: {COLOR_BORDER} !important;
            color: {COLOR_TEXT_INVERSE} !important;
            font-weight: 800 !important;
        }}

        div[data-testid="stButton"] > button[kind="primary"] p,
        .st-key-btn_llm_call button p {{
            color: {COLOR_TEXT_INVERSE} !important;
            font-weight: 800 !important;
        }}

        .st-key-btn_builder button {{
            background-color: {COLOR_BUTTON_MAIN} !important;
            border-color: {COLOR_BORDER} !important;
            color: {COLOR_TEXT} !important;
            font-weight: 750 !important;
        }}

        .st-key-btn_builder button:hover,
        .st-key-btn_builder button:focus {{
            background-color: {COLOR_BUTTON_MAIN} !important;
            border-color: {COLOR_BORDER} !important;
            color: {COLOR_TEXT} !important;
        }}

        .st-key-btn_builder button p {{
            color: {COLOR_TEXT} !important;
            font-weight: 750 !important;
        }}

        .st-key-btn_llm_call button {{
            background-color: {COLOR_BUTTON_ACTION} !important;
            border-color: {COLOR_BORDER} !important;
            color: {COLOR_TEXT_INVERSE} !important;
            font-weight: 800 !important;
        }}

        .st-key-btn_llm_call button:hover,
        .st-key-btn_llm_call button:focus {{
            background-color: {COLOR_BUTTON_ACTION} !important;
            border-color: {COLOR_BORDER} !important;
            color: {COLOR_TEXT_INVERSE} !important;
        }}

        .st-key-btn_feed_memory_manually button {{
            background-color: {COLOR_BUTTON_MEMORY} !important;
            border-color: {COLOR_BORDER} !important;
            color: {COLOR_TEXT} !important;
            font-weight: 750 !important;
        }}

        .st-key-btn_feed_memory_manually button:hover,
        .st-key-btn_feed_memory_manually button:focus {{
            background-color: {COLOR_BUTTON_MEMORY} !important;
            border-color: {COLOR_BORDER} !important;
            color: {COLOR_TEXT} !important;
        }}

        .st-key-btn_feed_memory_manually button p {{
            color: {COLOR_TEXT} !important;
            font-weight: 750 !important;
        }}
    """


def _form_field_css() -> str:
    return f"""
        textarea[aria-label="Manual Memory Feed (hidden)"] {{
            background-color: {COLOR_INPUT_BACKGROUND} !important;
        }}

        div[data-testid="stTextInput"]:has(input[aria-label="Recall Key"]) div[data-baseweb="input"],
        div[data-testid="stTextInput"]:has(input[aria-label="Direct Recall Key"]) div[data-baseweb="input"] {{
            border: 1.5px solid {COLOR_BORDER} !important;
            border-radius: 0.45rem !important;
            box-shadow: none !important;
        }}

        div[data-testid="stTextInput"]:has(input[aria-label="Recall Key"]) div[data-baseweb="input"]:focus-within,
        div[data-testid="stTextInput"]:has(input[aria-label="Direct Recall Key"]) div[data-baseweb="input"]:focus-within {{
            border: 1.5px solid {COLOR_PRIMARY} !important;
            box-shadow: 0 0 0 1px {COLOR_SECONDARY} !important;
        }}
    """


def _runtime_log_css() -> str:
    return f"""
        .textforge-log-box {{
            background-color: {COLOR_SECONDARY};
            border: 1.5px solid {COLOR_RUNTIME_LOG_BORDER};
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
            color: {COLOR_TEXT};
        }}
    """


def inject_base_css() -> None:
    """Global CSS for page spacing, product identity, panels, and buttons."""
    css = "\n".join(
        [
            _theme_css(),
            _base_page_css(),
            _product_identity_css(),
            _sidebar_brand_css(),
            _title_css(),
            _memory_css(),
            _button_css(),
            _form_field_css(),
            _runtime_log_css(),
        ]
    )

    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_ghost_logo_path() -> Path | None:
    root = _project_root()

    for relative_path in GHOST_LOGO_CANDIDATE_PATHS:
        candidate = root / relative_path
        if candidate.exists() and candidate.is_file():
            return candidate

    return None


def _image_file_to_data_uri(path: Path) -> str:
    suffix = path.suffix.lower()

    if suffix == ".svg":
        mime_type = "image/svg+xml"
    elif suffix in {".jpg", ".jpeg"}:
        mime_type = "image/jpeg"
    else:
        mime_type = "image/png"

    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def render_sidebar_brand_identity() -> None:
    """Render GHOST logo + compact product subtitle in the left sidebar."""
    logo_path = _resolve_ghost_logo_path()

    if logo_path is not None:
        logo_src = _image_file_to_data_uri(logo_path)
        logo_html = f'<img class="ghost-sidebar-logo" src="{logo_src}" alt="GHOST logo" />'
    else:
        logo_html = '<div class="ghost-sidebar-fallback-title">GHOST</div>'

    st.markdown(
        f"""
        <div class="ghost-sidebar-brand">
            {logo_html}
            <div class="ghost-sidebar-subtitle">
                {SIDEBAR_PRODUCT_SUBTITLE}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_page(
    *,
    sidebar_flowchart_slot: Any | None = None,
    render_sidebar_flowchart: Callable[[Any | None], None] | None = None,
) -> None:
    """
    MAIN page layout:
    - Product identity header
    - LEFT: prompt, actions, engineered prompt, status, log, project/files, advanced controls
    - RIGHT: full-height Memory area
    """

    render_product_identity_header()

    col_left, spacer, col_memory = st.columns(MAIN_COLUMNS, gap="small")

    with col_left:
        render_user_prompt_panel()

        builder_clicked = render_main_action_controls()

        engineered_prompt_slot = st.empty()

        progress_slot = st.empty()
        status_slot = st.empty()
        render_pipeline_status(
            progress_slot=progress_slot,
            status_slot=status_slot,
        )

        _vertical_gap("0.45rem")
        runtime_log_slot = st.empty()
        render_textforge_gui_log(
            height=RUNTIME_LOG_HEIGHT,
            log_slot=runtime_log_slot,
        )

        if builder_clicked:
            surfaces = LivePipelineSurfaces(
                progress_slot=progress_slot,
                status_slot=status_slot,
                runtime_log_slot=runtime_log_slot,
                sidebar_flowchart_slot=sidebar_flowchart_slot,
                render_runtime_log=render_textforge_gui_log,
                render_sidebar_flowchart=render_sidebar_flowchart,
            )
            run_prompt_builder_live(surfaces=surfaces)

        with engineered_prompt_slot.container():
            render_engineered_prompt_panel()
        _vertical_gap("0.55rem")
        ctrl: AppController = st.session_state.controller
        render_project_area(
            ctrl,
            show_ingestion_controls=bool(
                st.session_state.get("enable_file_ingestion_controls", False)
            ),
        )

        if st.session_state.get("show_advanced_controls", False):
            _vertical_gap("0.55rem")
            render_advanced_controls()

    with spacer:
        st.empty()

    with col_memory:
        render_memory_records(height=MEMORY_PANEL_HEIGHT)


def render_product_identity_header() -> None:
    """Render the MAIN-page workspace identity."""
    st.markdown(
        f"""
        <div class="ghost-product-title">
            {html.escape(MAIN_WORKSPACE_TITLE)}
        </div>
        <div class="ghost-product-subtitle">
            {html.escape(MAIN_WORKSPACE_SUBTITLE)}
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
    """Engineered Prompt with compact/expanded display."""
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


def render_main_action_controls() -> bool:
    """Left column: main execution controls below User Prompt."""
    _vertical_gap("0.45rem")

    _render_llm_call_row()
    builder_clicked = _render_prompt_builder_row()
    _render_manual_memory_feed_row()

    _vertical_gap("0.45rem")

    return bool(builder_clicked)


def _render_prompt_builder_row() -> bool:
    action_col, detail_col = st.columns(ACTION_ROW_COLUMNS, gap="small")

    with action_col:
        builder_clicked = st.button(
            "Prompt Builder",
            key="btn_builder",
            use_container_width=True,
        )

    with detail_col:
        cb1, cb2, cb3 = st.columns(3, gap="small")

        with cb1:
            use_a2_promptshaper_llm = st.checkbox(
                "Prompt shaping",
                key="use_a2_promptshaper_llm_widget",
            )

        with cb2:
            use_retrieval_splade = st.checkbox(
                "SPLADE retrieval",
                key="use_retrieval_splade_widget",
            )

        with cb3:
            use_reranking_colbert = st.checkbox(
                "ColBERT reranking",
                key="use_reranking_colbert_widget",
            )

        st.session_state["use_a2_promptshaper_llm"] = bool(use_a2_promptshaper_llm)
        st.session_state["use_retrieval_splade"] = bool(use_retrieval_splade)
        st.session_state["use_reranking_colbert"] = bool(use_reranking_colbert)

    return bool(builder_clicked)


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
        st.button(
            "Pre-Processing",
            key="btn_preproc",
            use_container_width=True,
            on_click=do_preprocess,
        )

    with b1c2:
        st.button(
            "A2-PromptShaper",
            key="btn_a2",
            use_container_width=True,
            on_click=do_a2_promptshaper,
        )

    with b1c3:
        st.button(
            "Retrieval",
            key="btn_retrieval",
            use_container_width=True,
            on_click=do_retrieval,
        )

    with b1c4:
        st.button(
            "ReRanker",
            key="btn_reranker",
            use_container_width=True,
            on_click=do_reranker,
        )

    b2c1, b2c2, b2c3, b2c4 = st.columns(4, gap="small")

    with b2c1:
        st.button(
            "A3 NLI Gate",
            key="btn_a3",
            use_container_width=True,
            on_click=do_a3_nli_gate,
        )

    with b2c2:
        st.button(
            "A4 Condenser",
            key="btn_a4",
            use_container_width=True,
            on_click=do_a4_condenser,
        )

    with b2c3:
        st.button("A5 Format Enforcer", key="btn_a5", use_container_width=True)

    with b2c4:
        st.empty()


def render_pipeline_status(
    *,
    progress_slot: Any | None = None,
    status_slot: Any | None = None,
) -> Any:
    """Render the Prompt Builder progress bar in the original status area."""
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
    message = str(status.get("message", "") or "")

    progress_target = progress_slot if progress_slot is not None else st
    progress_target.progress(
        progress,
        text=f"{step_index}/{total_steps} — {stage_name}",
    )

    if status_slot is not None:
        if message and stage_name not in {"Idle", "Done"}:
            status_slot.info(message)
        else:
            status_slot.empty()


def render_textforge_gui_log(
    height: int = RUNTIME_LOG_HEIGHT,
    *,
    log_slot: Any | None = None,
) -> None:
    """Render the TextForge GUI log box in the original Runtime Log area."""
    log_html = _build_textforge_log_html()
    log_box_style = _runtime_log_box_style(height=height)

    log_block = (
        '<div class="field-title" style="font-size:1.05rem;">Runtime Log</div>'
        f'<div class="textforge-log-box" style="{log_box_style}">{log_html}</div>'
    )

    target = log_slot if log_slot is not None else st
    target.markdown(log_block, unsafe_allow_html=True)


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
            f"background-color:{COLOR_FLASH_BG}; border-color:{COLOR_FLASH_BORDER};"
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
                color:{COLOR_TEXT_MUTED};
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


def _memory_record_keys(record: Any) -> tuple[str, str, str, str, str]:
    return (
        f"memory_tag_{record.record_id}",
        f"memory_retrieval_source_mode_{record.record_id}",
        f"memory_user_keywords_{record.record_id}",
        f"memory_direct_recall_key_{record.record_id}",
        f"memory_blackboard_actor_{record.record_id}",
    )


def _tag_display_name(tag_value: str) -> str:
    return TAG_DISPLAY_LABELS.get(str(tag_value), str(tag_value))


def _ensure_memory_record_session_state(
    memory_manager: Any,
    record: Any,
    tag_key: str,
    source_mode_key: str,
    keywords_key: str,
    direct_recall_key: str,
    actor_key: str,
) -> list[str]:
    tag_options = list(memory_manager.tag_catalog)
    record_tag = record.tag if record.tag in tag_options else "Green"

    if tag_key not in st.session_state:
        st.session_state[tag_key] = record_tag
    elif st.session_state[tag_key] not in tag_options:
        st.session_state[tag_key] = "Green"

    # Kept internally for retrieval compatibility. It is no longer shown in the UI.
    if source_mode_key not in st.session_state:
        st.session_state[source_mode_key] = getattr(record, "retrieval_source_mode", "QA")
    elif st.session_state[source_mode_key] not in {"QA", "Q", "A"}:
        st.session_state[source_mode_key] = "QA"

    if keywords_key not in st.session_state:
        st.session_state[keywords_key] = ", ".join(record.user_keywords)

    if direct_recall_key not in st.session_state:
        st.session_state[direct_recall_key] = getattr(record, "direct_recall_key", "")

    if actor_key not in st.session_state:
        st.session_state[actor_key] = getattr(
            record,
            "blackboard_actor",
            BLACKBOARD_ACTOR_OPTIONS[0],
        )

    if st.session_state[actor_key] not in BLACKBOARD_ACTOR_OPTIONS:
        st.session_state[actor_key] = BLACKBOARD_ACTOR_OPTIONS[0]

    return tag_options


def _render_memory_record(memory_manager: Any, record: Any) -> None:
    tag_key, source_mode_key, keywords_key, direct_recall_key, actor_key = _memory_record_keys(record)

    tag_options = _ensure_memory_record_session_state(
        memory_manager=memory_manager,
        record=record,
        tag_key=tag_key,
        source_mode_key=source_mode_key,
        keywords_key=keywords_key,
        direct_recall_key=direct_recall_key,
        actor_key=actor_key,
    )

    selected_tag = st.session_state.get(tag_key, record.tag)

    meta_left, meta_right = st.columns(MEMORY_META_AREA_COLUMNS, gap="small")

    with meta_left:
        _render_memory_record_meta_row(
            tag_key=tag_key,
            tag_options=tag_options,
            actor_key=actor_key,
            direct_recall_key=direct_recall_key,
        )

    with meta_right:
        st.empty()

    _vertical_gap("0.18rem")
    _render_memory_record_content(record, selected_tag=selected_tag)
    _vertical_gap("0.40rem")


def _render_memory_record_meta_row(
    tag_key: str,
    tag_options: list[str],
    actor_key: str,
    direct_recall_key: str,
) -> None:
    tag_col, actor_label_col, actor_col, recall_label_col, recall_col = st.columns(
        MEMORY_META_ROW_COLUMNS,
        gap="small",
    )

    with tag_col:
        st.selectbox(
            "Tag",
            options=tag_options,
            key=tag_key,
            format_func=_tag_display_name,
            label_visibility="collapsed",
        )

    with actor_label_col:
        st.markdown(
            '<div class="memory-meta-label">Blackboard Actor</div>',
            unsafe_allow_html=True,
        )

    with actor_col:
        st.selectbox(
            "Blackboard Actor",
            options=BLACKBOARD_ACTOR_OPTIONS,
            key=actor_key,
            label_visibility="collapsed",
        )

    with recall_label_col:
        st.markdown(
            '<div class="memory-meta-label">Recall Key</div>',
            unsafe_allow_html=True,
        )

    with recall_col:
        st.text_input(
            "Recall Key",
            key=direct_recall_key,
            placeholder="Recall Key",
            label_visibility="collapsed",
        )


def _render_memory_record_content(record: Any, selected_tag: str) -> None:
    state_class = "standard"
    if selected_tag == "Gold":
        state_class = "priority"
    elif selected_tag == "Black":
        state_class = "excluded"

    request_html = html.escape(str(getattr(record, "input_text", "") or "")).replace("\n", "<br>")
    response_html = html.escape(str(getattr(record, "output_text", "") or "")).replace("\n", "<br>")

    memory_html = (
        f'<div class="memory-content-shell {state_class}">'
        f'<div class="memory-request-box">'
        f'<div class="memory-label">REQUEST</div>'
        f'<div class="memory-plain-text">{request_html}</div>'
        f'</div>'
        f'<div class="memory-response-box">'
        f'<div class="memory-label">RESPONSE</div>'
        f'<div class="memory-plain-text">{response_html}</div>'
        f'</div>'
        f'</div>'
    )

    st.markdown(memory_html, unsafe_allow_html=True)


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