"""Verify exact Collection episode editing preserves stable identity."""

from pathlib import Path

from ragstream.mcp.ghost_memory_edit import GhostMemoryEditEpisodeTool
from ragstream.memory.mcp_memory_collection_retriever import (
    CollectionRecallSelection,
    McpMemoryCollectionRetriever,
)
from ragstream.memory.mcp_memory_collection_store import McpMemoryCollectionStore
from ragstream.memory.mcp_memory_store import McpMemoryStore


OWNER = "owner-1"


def _recall_episode(
    retriever: McpMemoryCollectionRetriever,
    collection_id: str,
) -> dict:
    result = retriever.recall_episodes(
        OWNER,
        CollectionRecallSelection(
            mode="episode_number",
            episode_number=1,
        ),
        collection_id=collection_id,
    )
    return result["episodes"][0]


def _build_collection(tmp_path: Path):
    memory_root = tmp_path / "mcp-memory"
    memory_store = McpMemoryStore(memory_root)
    collection_store = McpMemoryCollectionStore(
        memory_root,
        memory_store.sqlite_path,
    )
    retriever = McpMemoryCollectionRetriever(
        memory_root,
        memory_store.sqlite_path,
    )
    collection = collection_store.initialize_collection(
        OWNER,
        "Editable Collection",
        "Collection description stays fixed.",
    )
    saved = collection_store.append_episode(
        OWNER,
        collection_id=collection["collection_id"],
        episode_title="Fixed title",
        episode_description="Fixed episode description",
        input_text="Original question",
        output_text="Original answer",
        active_retrieval_brief="Fixed ActiveBrief",
    )
    return collection_store, retriever, collection, saved


def test_edit_episode_output_remains_backward_compatible(
    tmp_path: Path,
) -> None:
    collection_store, retriever, collection, saved = _build_collection(
        tmp_path
    )
    before = _recall_episode(retriever, collection["collection_id"])

    result = collection_store.edit_episode_output(
        OWNER,
        saved["record_id"],
        "Corrected answer with added reference.",
    )
    after = _recall_episode(retriever, collection["collection_id"])

    assert result["edited"] is True
    assert after["output_text"] == "Corrected answer with added reference."

    for field in (
        "episode_number",
        "record_id",
        "recall_key",
        "episode_title",
        "episode_description",
        "created_at_utc",
        "input_text",
        "active_retrieval_brief_title",
        "active_retrieval_brief",
        "active_retrieval_brief_contributor_ids",
    ):
        assert after[field] == before[field]


def test_edit_episode_can_replace_title_description_and_answer(
    tmp_path: Path,
) -> None:
    collection_store, retriever, collection, saved = _build_collection(
        tmp_path
    )
    before = _recall_episode(retriever, collection["collection_id"])

    result = collection_store.edit_episode_output(
        OWNER,
        saved["record_id"],
        "Replacement answer",
        new_episode_title="Replacement title",
        new_episode_description="Replacement description",
    )
    after = _recall_episode(retriever, collection["collection_id"])
    listed = retriever.list_episodes(
        OWNER,
        collection_id=collection["collection_id"],
    )["episodes"][0]

    assert result["edited"] is True
    assert after["output_text"] == "Replacement answer"
    assert after["episode_title"] == "Replacement title"
    assert after["episode_description"] == "Replacement description"
    assert listed["episode_title"] == "Replacement title"
    assert listed["episode_description"] == "Replacement description"

    for field in (
        "episode_number",
        "record_id",
        "recall_key",
        "created_at_utc",
        "input_text",
        "active_retrieval_brief_title",
        "active_retrieval_brief",
        "active_retrieval_brief_contributor_ids",
    ):
        assert after[field] == before[field]


def test_edit_tool_accepts_title_only_and_requires_exact_record_id(
    tmp_path: Path,
) -> None:
    collection_store, retriever, collection, saved = _build_collection(
        tmp_path
    )
    tool = GhostMemoryEditEpisodeTool(collection_store)

    edited = tool.call_sanitized(
        OWNER,
        {
            "record_id": saved["record_id"],
            "new_episode_title": "Title only",
        },
    )
    recalled = _recall_episode(retriever, collection["collection_id"])

    assert edited.isError is False
    assert recalled["episode_title"] == "Title only"
    assert recalled["output_text"] == "Original answer"

    missing = tool.call_sanitized(
        OWNER,
        {
            "record_id": "does-not-exist",
            "new_output_text": "Replacement",
        },
    )
    assert missing.isError is True
    assert missing.structuredContent["edited"] is False


def test_edit_tool_requires_at_least_one_replacement(
    tmp_path: Path,
) -> None:
    collection_store, _retriever, _collection, saved = _build_collection(
        tmp_path
    )
    tool = GhostMemoryEditEpisodeTool(collection_store)

    result = tool.call_sanitized(
        OWNER,
        {"record_id": saved["record_id"]},
    )

    assert result.isError is True
    assert result.structuredContent["edited"] is False
