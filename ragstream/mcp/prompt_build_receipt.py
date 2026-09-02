"""Serialize factual receipts for the central GHOST prompt builder."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ragstream.mcp.ghost_prompt_settings import BOOLEAN_SETTING_KEYS


def build_prompt_receipt(
    *,
    effective: Mapping[str, Any],
    project_name: str | None,
    document_receipt: Mapping[str, Any] | None,
    memory_receipt: Mapping[str, Any] | None,
    cleanup_changed: bool,
    sources_used: list[str],
    selected_skill_ids: list[str],
    status: str,
    build_id: str | None,
    stages_completed: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    """Return the stable public receipt for one builder state."""
    flags = {
        key: bool(effective[key])
        for key in BOOLEAN_SETTING_KEYS
    }
    return {
        "status": status,
        "build_id": build_id,
        "effective_flags": flags,
        "project_name": project_name,
        "ragmem_file_id": (
            str(memory_receipt.get("file_id", "") or "")
            if memory_receipt is not None
            else None
        ),
        "memory_vectors_created": (
            int(memory_receipt.get("vectors_created", 0) or 0)
            if memory_receipt is not None
            else 0
        ),
        "document_pipeline": (
            dict(document_receipt)
            if document_receipt is not None
            else None
        ),
        "memory_pipeline": (
            dict(memory_receipt)
            if memory_receipt is not None
            else None
        ),
        "cleanup_changed": cleanup_changed,
        "sources_used": list(sources_used),
        "selected_general_skill_ids": list(selected_skill_ids),
        "stages_completed": list(stages_completed),
        "warnings": list(warnings),
    }
