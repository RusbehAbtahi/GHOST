# ragstream/app/ui_files.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import pandas as pd
import streamlit as st

from ragstream.app.ui_actions_files import (
    do_files_confirm_delete_history,
    do_files_create_history,
    do_files_delete_request,
    do_files_import_chatgpt_conversation,
    do_files_load_history,
    do_files_rename_history,
)


COLOR_GHOST_DEEP_GREEN = "#004643"
COLOR_GHOST_MINT = "#afcecc"
COLOR_GHOST_SAND = "#edeae3"
COLOR_FIELD_ICE_BLUE = "#DCE7EE"
COLOR_PANEL_WHITE = "#ffffff"
COLOR_TEXT_BLACK = "#000000"
COLOR_BORDER_BLACK = "#000000"

TABLE_STRIPE_COLOR = COLOR_FIELD_ICE_BLUE

# Main FILES layout:
# left   = memory management panel
# spacer = visual distance between left and right areas
# right  = ChatGPT shared-link import controls
# tail   = unused right-side balancing space
CONTENT_COLS = [3.0, 0.4, 3.0, 1.1]

ACTION_ROW_COLS = [0.8, 2.2]
IMPORT_BUTTON_ROW_COLS = [0.8, 2.2]
IMPORT_SUMMARY_HEIGHT = 110


def render_files_tab() -> None:
    """Server-side FILES tab for memory history management."""
    _inject_files_css()

    st.markdown('<div class="files-main-title">Files</div>', unsafe_allow_html=True)

    memory_manager = st.session_state.memory_manager
    histories = memory_manager.list_histories()

    _repair_selected_file_id(histories)

    left_col, _spacer_col, right_col, _tail_col = st.columns(CONTENT_COLS, gap="small")

    with left_col:
        _render_left_files_area(histories)

    with right_col:
        _render_chatgpt_import_area()


def _inject_files_css() -> None:
    """Inject FILES-tab-only visual typography and color helpers."""
    st.markdown(
        f"""
        <style>
        .files-main-title {{
            font-size: 2.0rem;
            font-weight: 650;
            letter-spacing: -0.025em;
            color: {COLOR_GHOST_DEEP_GREEN};
            line-height: 1.15;
            margin: 0.10rem 0 0.85rem 0;
        }}

        .files-panel-title {{
            font-size: 1.32rem;
            font-weight: 700;
            line-height: 1.25;
            margin: 0.15rem 0 0.85rem 0;
            color: {COLOR_TEXT_BLACK};
        }}

        .files-section-title {{
            font-size: 1.02rem;
            font-weight: 700;
            line-height: 1.25;
            margin: 1.05rem 0 0.50rem 0;
            color: {COLOR_TEXT_BLACK};
        }}

        .files-widget-label {{
            font-size: 0.88rem;
            font-weight: 600;
            line-height: 1.25;
            margin: 0.62rem 0 0.28rem 0;
            color: {COLOR_TEXT_BLACK};
        }}

        div[data-testid="stDataFrame"] {{
            color: {COLOR_TEXT_BLACK} !important;
        }}

        div[data-testid="stTextInput"]:has(input[aria-label="ChatGPT shared link"]) div[data-baseweb="input"],
        div[data-testid="stTextInput"]:has(input[aria-label="Import title"]) div[data-baseweb="input"],
        div[data-testid="stTextInput"]:has(input[aria-label="New memory name"]) div[data-baseweb="input"],
        div[data-testid="stTextInput"]:has(input[aria-label="Rename field"]) div[data-baseweb="input"] {{
            background-color: {COLOR_FIELD_ICE_BLUE} !important;
            border: 1.5px solid {COLOR_BORDER_BLACK} !important;
            box-shadow: none !important;
        }}

        input[aria-label="ChatGPT shared link"],
        input[aria-label="Import title"],
        input[aria-label="New memory name"],
        input[aria-label="Rename field"],
        textarea[aria-label="Summary / MemoryBrief (optional)"] {{
            background-color: {COLOR_FIELD_ICE_BLUE} !important;
            color: {COLOR_TEXT_BLACK} !important;
        }}

        div[data-testid="stTextArea"]:has(textarea[aria-label="Summary / MemoryBrief (optional)"]) textarea {{
            background-color: {COLOR_FIELD_ICE_BLUE} !important;
            border: 1.5px solid {COLOR_BORDER_BLACK} !important;
            box-shadow: none !important;
        }}

        div[data-testid="stTextInput"]:has(input[aria-label="ChatGPT shared link"]) div[data-baseweb="input"]:focus-within,
        div[data-testid="stTextInput"]:has(input[aria-label="Import title"]) div[data-baseweb="input"]:focus-within,
        div[data-testid="stTextInput"]:has(input[aria-label="New memory name"]) div[data-baseweb="input"]:focus-within,
        div[data-testid="stTextInput"]:has(input[aria-label="Rename field"]) div[data-baseweb="input"]:focus-within,
        div[data-testid="stTextArea"]:has(textarea[aria-label="Summary / MemoryBrief (optional)"]) textarea:focus {{
            border-color: {COLOR_GHOST_DEEP_GREEN} !important;
            box-shadow: 0 0 0 1px {COLOR_GHOST_MINT} !important;
        }}

        .st-key-btn_files_import_chatgpt_conversation button,
        .st-key-btn_files_new button,
        div[class*="st-key-btn_files_load_"] button,
        div[class*="st-key-btn_files_rename_"] button,
        div[class*="st-key-btn_files_delete_request_"] button,
        div[class*="st-key-btn_files_confirm_delete_"] button {{
            background-color: {COLOR_GHOST_MINT} !important;
            border: 1.5px solid {COLOR_BORDER_BLACK} !important;
            color: {COLOR_TEXT_BLACK} !important;
            font-weight: 700 !important;
        }}

        .st-key-btn_files_import_chatgpt_conversation button:hover,
        .st-key-btn_files_import_chatgpt_conversation button:focus,
        .st-key-btn_files_new button:hover,
        .st-key-btn_files_new button:focus,
        div[class*="st-key-btn_files_load_"] button:hover,
        div[class*="st-key-btn_files_load_"] button:focus,
        div[class*="st-key-btn_files_rename_"] button:hover,
        div[class*="st-key-btn_files_rename_"] button:focus,
        div[class*="st-key-btn_files_delete_request_"] button:hover,
        div[class*="st-key-btn_files_delete_request_"] button:focus,
        div[class*="st-key-btn_files_confirm_delete_"] button:hover,
        div[class*="st-key-btn_files_confirm_delete_"] button:focus {{
            background-color: {COLOR_GHOST_MINT} !important;
            border-color: {COLOR_BORDER_BLACK} !important;
            color: {COLOR_TEXT_BLACK} !important;
        }}

        .st-key-btn_files_import_chatgpt_conversation button p,
        .st-key-btn_files_new button p,
        div[class*="st-key-btn_files_load_"] button p,
        div[class*="st-key-btn_files_rename_"] button p,
        div[class*="st-key-btn_files_delete_request_"] button p,
        div[class*="st-key-btn_files_confirm_delete_"] button p {{
            color: {COLOR_TEXT_BLACK} !important;
            font-weight: 700 !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _panel_title(text: str) -> None:
    st.markdown(f'<div class="files-panel-title">{text}</div>', unsafe_allow_html=True)


def _section_title(text: str) -> None:
    st.markdown(f'<div class="files-section-title">{text}</div>', unsafe_allow_html=True)


def _widget_label(text: str) -> None:
    st.markdown(f'<div class="files-widget-label">{text}</div>', unsafe_allow_html=True)


def _render_left_files_area(histories: list[dict]) -> None:
    """Render the normal FILES management area on the left side."""
    _panel_title("Manage Memory")

    if not histories:
        st.info("No memory histories found.")
        _render_status()
        return

    _render_history_table(histories)

    selected_file_id = str(st.session_state.get("files_selected_file_id", "") or "").strip()
    selected = _history_by_file_id(histories, selected_file_id)

    _section_title("Selected Memory History")

    if not selected:
        st.info("Select one memory history from the table above.")
        _render_status()
        return

    _render_selected_card(selected)
    _render_action_area(selected)
    _render_status()


def _render_chatgpt_import_area() -> None:
    """Render ChatGPT shared-link import controls."""
    _panel_title("Import from ChatGPT UI")

    _widget_label("ChatGPT shared link")
    st.text_input(
        "ChatGPT shared link",
        key="files_chatgpt_import_url",
        placeholder="https://chatgpt.com/share/...",
        label_visibility="collapsed",
    )

    _widget_label("Import title")
    st.text_input(
        "Import title",
        key="files_chatgpt_import_title",
        placeholder="Memory history title",
        label_visibility="collapsed",
    )

    _widget_label("Summary / MemoryBrief (optional)")
    st.text_area(
        "Summary / MemoryBrief (optional)",
        key="files_chatgpt_import_summary",
        height=IMPORT_SUMMARY_HEIGHT,
        placeholder="Optional shared MemoryBrief assigned to all imported records.",
        label_visibility="collapsed",
    )

    import_btn_col, _import_empty_col = st.columns(IMPORT_BUTTON_ROW_COLS, gap="small")

    with import_btn_col:
        if st.button(
            "Import Conversation",
            key="btn_files_import_chatgpt_conversation",
            use_container_width=True,
        ):
            do_files_import_chatgpt_conversation()


def _render_history_table(histories: list[dict]) -> None:
    """
    Render memory histories as a selectable dataframe.

    User selects one row in the table, then uses the action buttons below.
    """
    _section_title("Memory Histories")

    rows: list[dict[str, str]] = []

    for item in histories:
        rows.append(
            {
                "Filename": str(item.get("filename_ragmem", "") or ""),
                "Created": str(item.get("created_at_utc", "") or ""),
                "Updated": str(item.get("updated_at_utc", "") or ""),
                "Records": str(int(item.get("record_count", 0) or 0)),
                "_file_id": str(item.get("file_id", "") or ""),
            }
        )

    df = pd.DataFrame(rows)

    if df.empty:
        st.info("No memory histories found.")
        return

    visible_df = df[["Filename", "Created", "Updated", "Records"]].copy()
    styled_df = visible_df.style.apply(_stripe_table_rows, axis=1)

    event = st.dataframe(
        styled_df,
        key="files_history_table",
        use_container_width=True,
        hide_index=True,
        height=320,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Filename": st.column_config.TextColumn(
                "Filename",
                width="medium",
            ),
            "Created": st.column_config.TextColumn(
                "Created",
                width="small",
            ),
            "Updated": st.column_config.TextColumn(
                "Updated",
                width="small",
            ),
            "Records": st.column_config.TextColumn(
                "Records",
                width="small",
            ),
        },
    )

    selected_rows = _get_selected_rows(event)
    if selected_rows:
        row_index = int(selected_rows[0])
        if 0 <= row_index < len(df):
            st.session_state["files_selected_file_id"] = str(df.iloc[row_index]["_file_id"])


def _render_selected_card(selected: dict) -> None:
    """Render compact selected-file information."""
    filename = str(selected.get("filename_ragmem", "") or "")
    file_id = str(selected.get("file_id", "") or "")
    created = str(selected.get("created_at_utc", "") or "")
    updated = str(selected.get("updated_at_utc", "") or "")
    records = int(selected.get("record_count", 0) or 0)

    st.markdown(
        f"""
        <div style="
            border:1.5px solid {COLOR_BORDER_BLACK};
            border-radius:0.55rem;
            padding:0.65rem 0.85rem;
            background-color:{COLOR_GHOST_SAND};
            color:{COLOR_TEXT_BLACK};
        ">
            <div style="font-weight:700; font-size:1.02rem; color:{COLOR_TEXT_BLACK};">{filename}</div>
            <div style="font-size:0.84rem; color:{COLOR_TEXT_BLACK};">file_id: {file_id}</div>
            <div style="font-size:0.84rem; color:{COLOR_TEXT_BLACK};">created: {created}</div>
            <div style="font-size:0.84rem; color:{COLOR_TEXT_BLACK};">updated: {updated}</div>
            <div style="font-size:0.84rem; color:{COLOR_TEXT_BLACK};">records: {records}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_action_area(selected: dict) -> None:
    """Render Load / New / Rename / Delete actions for the selected history."""
    file_id = str(selected.get("file_id", "") or "").strip()

    rename_key = f"files_rename_title_{file_id}"
    delete_pending_key = f"files_delete_pending_{file_id}"
    delete_confirm_key = f"files_delete_confirm_text_{file_id}"

    _section_title("Actions")

    load_btn_col, _load_empty_col = st.columns(ACTION_ROW_COLS, gap="small")
    with load_btn_col:
        if st.button("Load", key=f"btn_files_load_{file_id}", use_container_width=True):
            do_files_load_history()

    new_btn_col, new_text_col = st.columns(ACTION_ROW_COLS, gap="small")
    with new_btn_col:
        if st.button("New", key="btn_files_new", use_container_width=True):
            do_files_create_history()
    with new_text_col:
        st.text_input(
            "New memory name",
            key="files_new_memory_title",
            placeholder="New memory name",
            label_visibility="collapsed",
        )

    rename_btn_col, rename_text_col = st.columns(ACTION_ROW_COLS, gap="small")
    with rename_btn_col:
        if st.button("Rename", key=f"btn_files_rename_{file_id}", use_container_width=True):
            do_files_rename_history()
    with rename_text_col:
        st.text_input(
            "Rename field",
            key=rename_key,
            placeholder="New name",
            label_visibility="collapsed",
        )

    if not st.session_state.get(delete_pending_key, False):
        delete_btn_col, _delete_empty_col = st.columns(ACTION_ROW_COLS, gap="small")
        with delete_btn_col:
            if st.button("Delete", key=f"btn_files_delete_request_{file_id}", use_container_width=True):
                do_files_delete_request()
    else:
        st.warning('Type "delete" to confirm deletion.')
        confirm_btn_col, confirm_text_col = st.columns(ACTION_ROW_COLS, gap="small")

        with confirm_btn_col:
            if st.button(
                "Confirm Delete",
                key=f"btn_files_confirm_delete_{file_id}",
                use_container_width=True,
            ):
                do_files_confirm_delete_history()

        with confirm_text_col:
            st.text_input(
                "Delete confirmation",
                key=delete_confirm_key,
                placeholder='type "delete"',
                label_visibility="collapsed",
            )


def _render_status() -> None:
    """Render latest FILES action status."""
    status = st.session_state.get("files_action_status")
    if not status:
        return

    if status.get("type") == "success":
        st.success(status.get("message", ""))
    else:
        st.error(status.get("message", ""))


def _repair_selected_file_id(histories: list[dict]) -> None:
    """
    Keep selected file_id only if it still exists.

    Important:
    - Do not auto-select newest file.
    - User selection must be explicit.
    """
    selected_file_id = str(st.session_state.get("files_selected_file_id", "") or "").strip()
    if not selected_file_id:
        return

    existing_ids = {str(item.get("file_id", "") or "").strip() for item in histories}
    if selected_file_id not in existing_ids:
        st.session_state["files_selected_file_id"] = ""


def _history_by_file_id(histories: list[dict], file_id: str) -> dict | None:
    clean_file_id = str(file_id or "").strip()

    for item in histories:
        if str(item.get("file_id", "") or "").strip() == clean_file_id:
            return item

    return None


def _get_selected_rows(event: object) -> list[int]:
    """Extract selected dataframe row indexes from Streamlit event object."""
    try:
        rows = event.selection.rows
    except Exception:
        return []

    if not rows:
        return []

    return [int(row) for row in rows]


def _stripe_table_rows(row: pd.Series) -> list[str]:
    """Apply soft alternating row colors."""
    color = TABLE_STRIPE_COLOR if int(row.name) % 2 == 1 else COLOR_PANEL_WHITE
    return [f"background-color: {color}; color: {COLOR_TEXT_BLACK}" for _ in row]