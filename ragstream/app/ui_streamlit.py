# ragstream/app/ui_streamlit.py
# -*- coding: utf-8 -*-
"""
Run on a free port, e.g.:
  /home/rusbeh_ab/venvs/ragstream/bin/python -m streamlit run /home/rusbeh_ab/project/RAGstream/ragstream/app/ui_streamlit.py --server.port 8503
"""

from __future__ import annotations

import html
import json
import threading

from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from ragstream.app.controller import AppController
from ragstream.app.ui_layout import inject_base_css, render_page
from ragstream.app.ui_files import render_files_tab
from ragstream.app.ui_metrics import render_metrics_tab
from ragstream.app.ui_settings import render_settings_tab
from ragstream.ingestion.embedder import Embedder
from ragstream.memory.ingestion.memory_chunker import MemoryChunker
from ragstream.memory.ingestion.memory_ingestion_manager import MemoryIngestionManager
from ragstream.memory.memory_manager import MemoryManager
from ragstream.memory.ingestion.memory_vector_store import MemoryVectorStore
from ragstream.orchestration.super_prompt import SuperPrompt
from ragstream.textforge.RagLog import LogALL as logger
from ragstream.textforge.RagLog import LogDeveloper as _logger_dev

DEV_LOG_ENABLED = False


def logger_dev(*args, **kwargs):
    if DEV_LOG_ENABLED:
        return _logger_dev(*args, **kwargs)
    return None


def _load_runtime_config(project_root: Path) -> dict[str, Any]:
    """
    Read ragstream/config/runtime_config.json during Streamlit startup.

    This config is used for Memory Retrieval limits and later runtime defaults.
    """
    config_path = project_root / "ragstream" / "config" / "runtime_config.json"

    if not config_path.exists():
        logger(f"runtime_config.json not found: {config_path}", "WARN", "PUBLIC")
        return {}

    try:
        with config_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError("runtime_config.json root must be a JSON object.")

        logger("runtime_config.json loaded in Streamlit session.", "INFO", "INTERNAL")

        logger_dev(
            "runtime_config.json loaded in Streamlit session\n"
            + json.dumps(data, ensure_ascii=False, indent=2, default=str),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return data

    except Exception as e:
        logger(f"Failed to load runtime_config.json: {e}", "ERROR", "PUBLIC")
        return {}


def init_session_state() -> None:
    """
    Create one controller + one SuperPrompt set per user session.

    Startup also initializes:
    - MemoryManager
    - MemoryVectorStore
    - MemoryIngestionManager
    - MemoryRetriever wiring through AppController.configure_memory_retrieval(...)
    """
    project_root = Path(__file__).resolve().parents[2]

    if "runtime_config" not in st.session_state:
        st.session_state.runtime_config = _load_runtime_config(project_root)

    if "controller" not in st.session_state:
        ctrl = AppController()
        st.session_state.controller = ctrl

    if "textforge_gui_log" not in st.session_state:
        st.session_state["textforge_gui_log"] = ""

    if "memory_manager" not in st.session_state:
        memory_root = project_root / "data" / "memory"
        sqlite_path = memory_root / "memory_index.sqlite3"

        st.session_state.memory_manager = MemoryManager(
            memory_root=memory_root,
            sqlite_path=sqlite_path,
            title="",
        )

    if "memory_vector_store" not in st.session_state:
        memory_root = project_root / "data" / "memory"
        memory_vector_root = memory_root / "vector_db"

        memory_embedder = Embedder(model="text-embedding-3-large")

        st.session_state.memory_vector_store = MemoryVectorStore(
            persist_dir=str(memory_vector_root),
            collection_name="memory_vectors",
            embedder=memory_embedder,
        )

    if "memory_chunker" not in st.session_state:
        st.session_state.memory_chunker = MemoryChunker()

    if "memory_ingestion_manager" not in st.session_state:
        st.session_state.memory_ingestion_manager = MemoryIngestionManager(
            memory_manager=st.session_state.memory_manager,
            memory_chunker=st.session_state.memory_chunker,
            memory_vector_store=st.session_state.memory_vector_store,
        )

        logger(
            "Memory ingestion layer ready: data/memory/vector_db/ | collection=memory_vectors",
            "INFO",
            "PUBLIC",
        )

    if "memory_retrieval_configured" not in st.session_state:
        st.session_state["memory_retrieval_configured"] = False

    if not st.session_state["memory_retrieval_configured"]:
        ctrl: AppController = st.session_state.controller
        ctrl.configure_memory_retrieval(
            memory_manager=st.session_state.memory_manager,
            memory_vector_store=st.session_state.memory_vector_store,
            runtime_config=st.session_state.runtime_config,
        )
        st.session_state["memory_retrieval_configured"] = True

    if "heavy_init_started" not in st.session_state:
        st.session_state["heavy_init_started"] = False

    if not st.session_state["heavy_init_started"]:
        ctrl = st.session_state.controller

        t = threading.Thread(
            target=ctrl.initialize_heavy_components,
            daemon=True,
        )
        t.start()

        st.session_state["heavy_init_started"] = True

    if "sp" not in st.session_state:
        st.session_state.sp = SuperPrompt()
    if "sp_pre" not in st.session_state:
        st.session_state.sp_pre = SuperPrompt()
    if "sp_a2" not in st.session_state:
        st.session_state.sp_a2 = SuperPrompt()
    if "sp_rtv" not in st.session_state:
        st.session_state.sp_rtv = SuperPrompt()
    if "sp_rrk" not in st.session_state:
        st.session_state.sp_rrk = SuperPrompt()
    if "sp_a3" not in st.session_state:
        st.session_state.sp_a3 = SuperPrompt()
    if "sp_a4" not in st.session_state:
        st.session_state.sp_a4 = SuperPrompt()

    if "super_prompt_text" not in st.session_state:
        st.session_state["super_prompt_text"] = ""

    if "ingestion_status" not in st.session_state:
        st.session_state["ingestion_status"] = None

    if "new_project_name" not in st.session_state:
        st.session_state["new_project_name"] = ""

    if "pending_active_project" not in st.session_state:
        st.session_state["pending_active_project"] = None

    if "retrieval_top_k" not in st.session_state:
        st.session_state["retrieval_top_k"] = 30

    if "use_a2_promptshaper_llm" not in st.session_state:
        st.session_state["use_a2_promptshaper_llm"] = True

    if "use_retrieval_splade" not in st.session_state:
        st.session_state["use_retrieval_splade"] = False

    if "use_reranking_colbert" not in st.session_state:
        st.session_state["use_reranking_colbert"] = False

    if "use_a2_promptshaper_llm_widget" not in st.session_state:
        st.session_state["use_a2_promptshaper_llm_widget"] = bool(
            st.session_state["use_a2_promptshaper_llm"]
        )

    if "use_retrieval_splade_widget" not in st.session_state:
        st.session_state["use_retrieval_splade_widget"] = bool(
            st.session_state["use_retrieval_splade"]
        )

    if "use_reranking_colbert_widget" not in st.session_state:
        st.session_state["use_reranking_colbert_widget"] = bool(
            st.session_state["use_reranking_colbert"]
        )

    if "manual_memory_feed_text" not in st.session_state:
        st.session_state["manual_memory_feed_text"] = ""

    if "show_advanced_controls" not in st.session_state:
        st.session_state["show_advanced_controls"] = False

    if "enable_file_ingestion_controls" not in st.session_state:
        st.session_state["enable_file_ingestion_controls"] = False

    if "active_sidebar_page" not in st.session_state:
        st.session_state["active_sidebar_page"] = "Main"

    if "sidebar_pipeline_active_step" not in st.session_state:
        st.session_state["sidebar_pipeline_active_step"] = 0

    if "sidebar_pipeline_completed_step" not in st.session_state:
        st.session_state["sidebar_pipeline_completed_step"] = -1


def _page_options() -> list[str]:
    return [
        "Main",
        "Files",
        "Hard Rules",
        "Metrics",
        "General Settings",
    ]


def _sidebar_pipeline_steps() -> list[str]:
    return [
        "User Prompt",
        "Prompt Qualification",
        "Prompt Shaping",
        "Memory Context",
        "Document Evidence",
        "Context Synthesis",
        "Hard Rule Integration",
        "LLM-Ready Context",
    ]


def _init_page_state() -> None:
    if "active_sidebar_page" not in st.session_state:
        st.session_state["active_sidebar_page"] = "Main"

    if st.session_state["active_sidebar_page"] not in _page_options():
        st.session_state["active_sidebar_page"] = "Main"


def _render_sidebar_flowchart() -> None:
    steps = _sidebar_pipeline_steps()

    try:
        active_step = int(st.session_state.get("sidebar_pipeline_active_step", 0) or 0)
    except Exception:
        active_step = 0

    if active_step < 0:
        active_step = 0

    if active_step >= len(steps):
        active_step = len(steps) - 1

    items: list[str] = []

    for index, label in enumerate(steps):
        state_class = " flow-box-active" if index == active_step else ""

        items.append(
            f"""
            <div class="flow-box{state_class}">
                {html.escape(label)}
            </div>
            """
        )

        if index < len(steps) - 1:
            items.append('<div class="flow-arrow">↓</div>')

    flow_html = f"""
    <!doctype html>
    <html>
    <head>
        <meta charset="utf-8" />
        <style>
            html, body {{
                margin: 0;
                padding: 0;
                background: transparent;
                font-family:
                    -apple-system,
                    BlinkMacSystemFont,
                    "Segoe UI",
                    Roboto,
                    Helvetica,
                    Arial,
                    sans-serif;
            }}

            .flow-shell {{
                box-sizing: border-box;
                width: 61.8%;
                margin: 18px auto 0 auto;
                padding: 0;
            }}

            .flow-box {{
                box-sizing: border-box;
                width: 100%;
                min-height: 32px;
                border: 1.3px solid #111111;
                border-radius: 2px;
                background: transparent;
                color: #111111;
                display: flex;
                align-items: center;
                justify-content: center;
                text-align: center;
                padding: 3px 5px;
                font-size: 14px;
                font-weight: 400;
                line-height: 1.12;
            }}

            .flow-box-active {{
                background: #FFF176;
            }}

            .flow-arrow {{
                text-align: center;
                font-size: 18px;
                line-height: 1.05;
                color: #111111;
                margin: 2px 0;
            }}
        </style>
    </head>
    <body>
        <div class="flow-shell">
            {"".join(items)}
        </div>
    </body>
    </html>
    """

    components.html(
        flow_html,
        height=500,
        scrolling=False,
    )


def render_sidebar_navigation() -> str:
    _init_page_state()

    options = _page_options()
    active_page = st.session_state["active_sidebar_page"]

    with st.sidebar:
        st.markdown(
            """
            <div style="
                padding:0.45rem 0.25rem 0.90rem 0.25rem;
            ">
                <div style="
                    font-size:1.55rem;
                    font-weight:800;
                    letter-spacing:0.045em;
                    color:#111827;
                    line-height:1.05;
                ">
                    GHOST
                </div>
                <div style="
                    margin-top:0.32rem;
                    font-size:0.88rem;
                    color:#4B5563;
                    line-height:1.32;
                ">
                    GenAI Hybrid Orchestrator<br>
                    for Software Tooling
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        selected_page = st.radio(
            "Navigation",
            options=options,
            index=options.index(active_page),
            key="sidebar_navigation_radio",
            label_visibility="collapsed",
        )

        st.session_state["active_sidebar_page"] = selected_page

        st.markdown("---")

        if selected_page == "Main":
            st.caption("Main workflow")
            st.caption("Memory · Prompt · Builder · LLM")

            st.checkbox(
                "Enable file ingestion controls",
                key="enable_file_ingestion_controls",
            )

            st.checkbox(
                "Show advanced controls",
                key="show_advanced_controls",
            )

            _render_sidebar_flowchart()

        elif selected_page == "Files":
            st.caption("Memory files and imports")
        elif selected_page == "Hard Rules":
            st.caption("Rule governance")
        elif selected_page == "Metrics":
            st.caption("Metrics and visual pipeline demos")
        elif selected_page == "General Settings":
            st.caption("Runtime configuration")

    return selected_page


def render_active_page(page_name: str) -> None:
    if page_name == "Main":
        render_page()
    elif page_name == "Files":
        render_files_tab()
    elif page_name == "Hard Rules":
        st.markdown("## Hard Rules")
        st.info("Hard Rules tab placeholder.")
    elif page_name == "Metrics":
        render_metrics_tab()
    elif page_name == "General Settings":
        render_settings_tab()
    else:
        render_page()


def main() -> None:
    st.set_page_config(
        page_title="GHOST",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    inject_base_css()

    init_session_state()

    selected_page = render_sidebar_navigation()
    render_active_page(selected_page)


if __name__ == "__main__":
    main()