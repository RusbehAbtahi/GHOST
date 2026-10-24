# ragstream/memory/memory_actions.py
# -*- coding: utf-8 -*-
"""
Memory actions
==============
Reusable workflow functions for memory capture.

GUI buttons, future LLM calls, Copilot calls, or tool results should call
these functions instead of embedding memory logic directly in UI callbacks.
"""

from __future__ import annotations

from typing import Any

from ragstream.memory.memory_manager import MemoryManager
from ragstream.textforge.RagLog import LogALL as logger


def capture_memory_pair(
    memory_manager: MemoryManager,
    input_text: str,
    output_text: str,
    source: str,
    active_project_name: str | None = None,
    embedded_files_snapshot: list[str] | None = None,
    parent_id: str | None = None,
    user_keywords: list[str] | None = None,
    gui_records_state: list[dict[str, Any]] | None = None,
    memory_ingestion_manager: Any | None = None,
) -> dict[str, Any]:
    clean_input = (input_text or "").strip()
    clean_output = (output_text or "").strip()

    if not clean_input:
        return {
            "success": False,
            "message": "Prompt is empty. No memory record was created.",
            "record": None,
        }

    if not clean_output:
        return {
            "success": False,
            "message": "Manual memory response is empty. No memory record was created.",
            "record": None,
        }

    memory_manager.sync_gui_edits(gui_records_state or [])

    record = memory_manager.capture_pair(
        input_text=clean_input,
        output_text=clean_output,
        source=source,
        parent_id=parent_id,
        user_keywords=user_keywords,
        active_project_name=active_project_name,
        embedded_files_snapshot=embedded_files_snapshot or [],
    )

    warning = str(getattr(memory_manager, "last_capture_warning", "") or "").strip()
    message = f"Memory record saved: {record.record_id}"
    if warning:
        message = f"{message}. Warning: {warning}"

    logger(
        f"Memory record saved: {record.record_id}",
        "INFO",
        "PUBLIC",
    )

    if warning:
        logger(warning, "WARN", "PUBLIC")

    logger(
        (
            "MemoryRecord captured: "
            f"record={record.record_id[:8]} | "
            f"file={memory_manager.filename_ragmem} | "
            f"tag={record.tag}"
        ),
        "INFO",
        "INTERNAL",
    )

    if memory_ingestion_manager is not None:
        try:
            memory_ingestion_manager.ingest_record_async(record.record_id)
        except Exception as e:
            logger(
                f"MemoryRecord was saved, but vector ingestion could not be scheduled: {e}",
                "WARN",
                "PUBLIC",
            )

    return {
        "success": True,
        "message": message,
        "warning": warning,
        "record": record,
        "record_id": record.record_id,
        "file_id": memory_manager.file_id,
        "filename_ragmem": memory_manager.filename_ragmem,
    }