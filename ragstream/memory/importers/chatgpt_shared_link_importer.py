# ragstream/memory/importers/chatgpt_shared_link_importer.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from ragstream.memory.importers.chatgpt_shared_link_importer_helpers import (
    assign_memory_brief_to_records,
    build_memory_records,
    ingest_imported_history,
    messages_to_pairs,
    persist_records_as_new_history,
    read_chatgpt_shared_link,
    validate_shared_url,
    validate_title,
)


def import_chatgpt_shared_link(
    *,
    shared_url: str,
    title: str,
    memory_manager: Any,
    memory_ingestion_manager: Any | None = None,
    memory_brief: str = "",
    memory_brief_title: str = "",
    active_project_name: str | None = None,
    embedded_files_snapshot: list[str] | None = None,
    headless: bool = True,
    timeout_ms: int = 60000,
    wait_after_load_ms: int = 3000,
    wait_for_stable_messages: bool = True,
) -> dict[str, Any]:
    """
    Import one public ChatGPT shared conversation into RAGstream Memory.

    This main file intentionally stays small:
    - validate input
    - read the shared page
    - convert messages into Q/A memory pairs
    - build MemoryRecord objects
    - persist them as a normal memory history
    - optionally ingest vectors
    """

    # 1. Validate user-facing import inputs before opening the browser.
    clean_url = validate_shared_url(shared_url)
    clean_title = validate_title(title)
    clean_memory_brief = str(memory_brief or "").strip()
    clean_memory_brief_title = str(memory_brief_title or "").strip() or clean_title

    # 2. Open the public ChatGPT shared page and extract conversation messages.
    page_data = read_chatgpt_shared_link(
        clean_url,
        headless=headless,
        timeout_ms=timeout_ms,
        wait_after_load_ms=wait_after_load_ms,
        wait_for_stable_messages=wait_for_stable_messages,
    )

    # 3. Convert extracted user/assistant messages into RAGstream Q/A pairs.
    pairs = messages_to_pairs(
        messages=page_data.get("messages", []),
        raw_text=str(page_data.get("raw_text", "") or ""),
        shared_url=clean_url,
        title=clean_title,
    )

    if not pairs:
        raise ValueError("No importable conversation text was found in the shared link.")

    # 4. Build normal MemoryRecord objects without changing MemoryRecord itself.
    records = build_memory_records(
        pairs=pairs,
        shared_url=clean_url,
        active_project_name=active_project_name,
        embedded_files_snapshot=embedded_files_snapshot or [],
    )

    # 5. Attach the optional MemoryBrief to all imported records as shared context.
    if clean_memory_brief:
        assign_memory_brief_to_records(
            records=records,
            memory_brief=clean_memory_brief,
            memory_brief_title=clean_memory_brief_title,
        )

    # 6. Persist the imported records as a new ordinary RAGstream memory history.
    persist_records_as_new_history(
        memory_manager=memory_manager,
        title=clean_title,
        records=records,
    )

    # 7. Optionally ingest the new memory history into the memory vector store.
    vector_ingestion_result = ingest_imported_history(
        memory_ingestion_manager=memory_ingestion_manager,
    )

    # 8. Return a compact import report for the Streamlit action/status layer.
    return {
        "success": True,
        "shared_url": clean_url,
        "title": memory_manager.title,
        "file_id": memory_manager.file_id,
        "filename_ragmem": memory_manager.filename_ragmem,
        "filename_meta": memory_manager.filename_meta,
        "record_count": len(records),
        "pair_count": len(pairs),
        "message_count": len(page_data.get("messages", []) or []),
        "raw_text_chars": len(str(page_data.get("raw_text", "") or "")),
        "extraction_method": page_data.get("extraction_method", ""),
        "memory_brief_assigned": bool(clean_memory_brief),
        "vector_ingestion": vector_ingestion_result,
    }
