"""Verify Collection ActiveBrief guidance is exposed before save and can be empty."""

from pathlib import Path

from ragstream.mcp.ghost_memory_tag import (
    WORKFLOW_COMPOSITION_REQUIRED,
    WORKFLOW_COMPLETE,
    GhostMemoryTagTool,
)
from ragstream.memory.mcp_memory_collection_store import McpMemoryCollectionStore
from ragstream.memory.mcp_memory_store import McpMemoryStore


OWNER = "owner-1"


def test_collection_save_exposes_description_then_accepts_empty_activebrief(
    tmp_path: Path,
) -> None:
    memory_root = tmp_path / "mcp-memory"
    memory_store = McpMemoryStore(memory_root)
    collection_store = McpMemoryCollectionStore(
        memory_root,
        memory_store.sqlite_path,
    )
    collection = collection_store.initialize_collection(
        OWNER,
        "Applications",
        "ActiveBrief instruction: keep the ActiveBrief empty.",
    )
    tool = GhostMemoryTagTool(memory_store, collection_store)

    base_arguments = {
        "memory_type": "collection",
        "collection_id": collection["collection_id"],
        "episode_title": "Example application",
        "episode_description": "One submitted application",
        "input_text": "Save this application.",
        "output_text": "Application saved.",
    }

    context = tool.call_sanitized(OWNER, base_arguments)

    assert context.isError is False
    assert context.structuredContent["saved"] is False
    assert (
        context.structuredContent["workflow_state"]
        == WORKFLOW_COMPOSITION_REQUIRED
    )
    assert context.structuredContent["collection_description"] == (
        "ActiveBrief instruction: keep the ActiveBrief empty."
    )
    assert context.structuredContent["previous_active_retrieval_brief"] == ""

    saved = tool.call_sanitized(
        OWNER,
        {**base_arguments, "active_retrieval_brief": ""},
    )

    assert saved.isError is False
    assert saved.structuredContent["saved"] is True
    assert saved.structuredContent["workflow_state"] == WORKFLOW_COMPLETE

    stored_context = collection_store.get_activebrief_context(
        OWNER,
        collection_id=collection["collection_id"],
    )
    assert stored_context["previous_active_retrieval_brief"] == ""


def test_collection_context_returns_previous_cumulative_activebrief(
    tmp_path: Path,
) -> None:
    memory_root = tmp_path / "mcp-memory"
    memory_store = McpMemoryStore(memory_root)
    collection_store = McpMemoryCollectionStore(
        memory_root,
        memory_store.sqlite_path,
    )
    collection = collection_store.initialize_collection(
        OWNER,
        "Chronology",
        "ActiveBrief instruction: start every brief with the date.",
    )
    tool = GhostMemoryTagTool(memory_store, collection_store)

    common = {
        "memory_type": "collection",
        "collection_id": collection["collection_id"],
        "episode_description": "Chronological episode",
        "input_text": "Save this.",
        "output_text": "Saved.",
    }
    first = tool.call_sanitized(
        OWNER,
        {
            **common,
            "episode_title": "First",
            "active_retrieval_brief": "2026-09-04 First episode",
        },
    )
    assert first.structuredContent["saved"] is True

    context = tool.call_sanitized(
        OWNER,
        {**common, "episode_title": "Second"},
    )

    assert context.structuredContent["workflow_state"] == WORKFLOW_COMPOSITION_REQUIRED
    assert context.structuredContent["collection_description"] == (
        "ActiveBrief instruction: start every brief with the date."
    )
    assert context.structuredContent["previous_active_retrieval_brief"] == (
        "2026-09-04 First episode"
    )
