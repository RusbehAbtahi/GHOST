# ragstream/app/ui_actions_files.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import streamlit as st

from ragstream.memory.storage.memory_file_manager import MemoryFileManager
from ragstream.memory.importers.chatgpt_shared_link_importer import import_chatgpt_shared_link
from ragstream.memory.memory_manager import MemoryManager
from ragstream.textforge.RagLog import LogALL as logger


def do_files_create_history() -> None:
    """Create a new empty memory history and make it active."""
    new_title = str(st.session_state.get("files_new_memory_title", "") or "").strip()

    if not new_title:
        _set_status("error", "New memory name must not be empty.")
        return

    try:
        manager = _file_manager()
        result = manager.create_history(new_title)

        st.session_state["files_selected_file_id"] = result.get("file_id", "")

        _clear_memory_widget_state()

        _set_status(
            "success",
            f"Created memory history: {result.get('filename_ragmem', '')}",
        )

        logger(
            f"Memory history created: {result.get('filename_ragmem', '')}",
            "INFO",
            "PUBLIC",
        )

        st.rerun()

    except Exception as e:
        _set_status("error", str(e))
        logger(str(e), "ERROR", "PUBLIC")


def do_files_load_history() -> None:
    """Load selected memory history from server-side storage."""
    file_id = _selected_file_id()
    if not file_id:
        _set_status("error", "No memory history selected.")
        return

    try:
        manager = _file_manager()
        result = manager.load_history(file_id)

        _clear_memory_widget_state()

        _set_status(
            "success",
            f"Loaded memory history: {result.get('filename_ragmem', '')}",
        )

        logger(
            f"Memory history loaded: {result.get('filename_ragmem', '')}",
            "INFO",
            "PUBLIC",
        )

        st.rerun()

    except Exception as e:
        _set_status("error", str(e))
        logger(str(e), "ERROR", "PUBLIC")


def do_files_rename_history() -> None:
    """Rename selected memory history through RAGstream only."""
    file_id = _selected_file_id()
    if not file_id:
        _set_status("error", "No memory history selected.")
        return

    rename_key = _rename_key(file_id)
    new_title = str(st.session_state.get(rename_key, "") or "").strip()

    if not new_title:
        _set_status("error", "New memory name must not be empty.")
        return

    try:
        manager = _file_manager()
        result = manager.rename_history(
            file_id=file_id,
            new_title=new_title,
        )

        _set_status(
            "success",
            f"Renamed memory history: {result.get('filename_ragmem', '')}",
        )

        logger(
            f"Memory history renamed: {result.get('filename_ragmem', '')}",
            "INFO",
            "PUBLIC",
        )

        st.rerun()

    except Exception as e:
        _set_status("error", str(e))
        logger(str(e), "ERROR", "PUBLIC")


def do_files_delete_request() -> None:
    """Show delete confirmation input for selected memory history."""
    file_id = _selected_file_id()
    if not file_id:
        _set_status("error", "No memory history selected.")
        return

    st.session_state[_delete_pending_key(file_id)] = True
    _set_status("error", 'Deletion pending. Type "delete" and press Confirm Delete.')
    st.rerun()


def do_files_confirm_delete_history() -> None:
    """Delete selected memory history after typed confirmation."""
    file_id = _selected_file_id()
    if not file_id:
        _set_status("error", "No memory history selected.")
        return

    confirm_key = _delete_confirm_key(file_id)
    typed_value = str(st.session_state.get(confirm_key, "") or "").strip()

    if typed_value != "delete":
        _set_status("error", 'Deletion confirmation must be exactly: delete')
        return

    try:
        manager = _file_manager()
        result = manager.delete_history(file_id)

        st.session_state["files_selected_file_id"] = ""

        _clear_memory_widget_state()

        _set_status(
            "success",
            (
                "Deleted memory history: "
                f"{result.get('filename_ragmem', '')} | "
                f"vectors deleted: {result.get('vectors_deleted', 0)}"
            ),
        )

        logger(
            (
                "Memory history deleted: "
                f"{result.get('filename_ragmem', '')} | "
                f"vectors={result.get('vectors_deleted', 0)}"
            ),
            "INFO",
            "PUBLIC",
        )

        st.rerun()

    except Exception as e:
        _set_status("error", str(e))
        logger(str(e), "ERROR", "PUBLIC")


def do_files_import_chatgpt_conversation() -> None:
    """Import a public ChatGPT shared-link conversation as a memory history."""
    shared_url = str(st.session_state.get("files_chatgpt_import_url", "") or "").strip()
    title = str(st.session_state.get("files_chatgpt_import_title", "") or "").strip()
    summary = str(st.session_state.get("files_chatgpt_import_summary", "") or "").strip()

    if not shared_url:
        _set_status("error", "ChatGPT shared link must not be empty.")
        return

    if not title:
        _set_status("error", "Import title must not be empty.")
        return

    try:
        memory_manager: MemoryManager = st.session_state.memory_manager
        memory_ingestion_manager = st.session_state.get("memory_ingestion_manager")

        active_project_name, embedded_files_snapshot = _get_active_project_snapshot()

        result = import_chatgpt_shared_link(
            shared_url=shared_url,
            title=title,
            memory_manager=memory_manager,
            memory_ingestion_manager=memory_ingestion_manager,
            memory_brief=summary,
            memory_brief_title=title if summary else "",
            active_project_name=active_project_name,
            embedded_files_snapshot=embedded_files_snapshot,
        )

        st.session_state["files_selected_file_id"] = result.get("file_id", "")

        _clear_memory_widget_state()

        vector_info = result.get("vector_ingestion") or {}
        vector_text = ""
        if isinstance(vector_info, dict) and vector_info:
            vector_text = (
                f" | vector ingestion: "
                f"{vector_info.get('success_count', 0)} ok, "
                f"{vector_info.get('failure_count', 0)} failed"
            )

        _set_status(
            "success",
            (
                "Imported ChatGPT conversation: "
                f"{result.get('filename_ragmem', '')} | "
                f"records: {result.get('record_count', 0)}"
                f"{vector_text}"
            ),
        )

        logger(
            (
                "ChatGPT shared conversation imported: "
                f"{result.get('filename_ragmem', '')} | "
                f"records={result.get('record_count', 0)}"
            ),
            "INFO",
            "PUBLIC",
        )

        st.rerun()

    except Exception as e:
        _set_status("error", str(e))
        logger(str(e), "ERROR", "PUBLIC")


def _get_active_project_snapshot() -> tuple[str | None, list[str]]:
    active_project = st.session_state.get("active_project")

    if not active_project or active_project == "(no projects yet)":
        return None, []

    try:
        ctrl = st.session_state.get("controller")
        if ctrl is None:
            return str(active_project), []

        embedded_info = ctrl.get_embedded_files(active_project)
        if embedded_info.get("success"):
            return str(active_project), list(embedded_info.get("files", []))

    except Exception:
        return str(active_project), []

    return str(active_project), []


def _file_manager() -> MemoryFileManager:
    memory_manager: MemoryManager = st.session_state.memory_manager
    memory_vector_store = st.session_state.get("memory_vector_store")

    return MemoryFileManager(
        memory_manager=memory_manager,
        memory_vector_store=memory_vector_store,
    )


def _selected_file_id() -> str:
    return str(st.session_state.get("files_selected_file_id", "") or "").strip()


def _rename_key(file_id: str) -> str:
    return f"files_rename_title_{file_id}"


def _delete_pending_key(file_id: str) -> str:
    return f"files_delete_pending_{file_id}"


def _delete_confirm_key(file_id: str) -> str:
    return f"files_delete_confirm_text_{file_id}"


def _set_status(status_type: str, message: str) -> None:
    st.session_state["files_action_status"] = {
        "type": status_type,
        "message": message,
    }


def _clear_memory_widget_state() -> None:
    prefixes = (
        "memory_tag_",
        "memory_retrieval_source_mode_",
        "memory_user_keywords_",
        "memory_direct_recall_key_",
    )

    for key in list(st.session_state.keys()):
        if str(key).startswith(prefixes):
            st.session_state.pop(key, None)