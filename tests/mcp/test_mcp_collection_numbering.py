"""Verify Collection deletion keeps middle gaps and reclaims only the tail."""

from pathlib import Path

from ragstream.memory.mcp_memory_collection_retriever import (
    McpMemoryCollectionRetriever,
)
from ragstream.memory.mcp_memory_collection_store import McpMemoryCollectionStore
from ragstream.memory.mcp_memory_store import McpMemoryStore


OWNER = "owner-1"


def _build_store(tmp_path: Path):
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
        "Numbering Collection",
        "Numbering regression test.",
    )
    return collection_store, retriever, collection


def _append(
    store: McpMemoryCollectionStore,
    collection_id: str,
    number: int,
) -> dict:
    return store.append_episode(
        OWNER,
        collection_id=collection_id,
        episode_title=f"Episode {number}",
        episode_description=f"Description {number}",
        input_text=f"Question {number}",
        output_text=f"Answer {number}",
        active_retrieval_brief=f"Brief {number}",
    )


def test_deleting_current_tail_reuses_that_number(
    tmp_path: Path,
) -> None:
    store, retriever, collection = _build_store(tmp_path)
    saved = [
        _append(store, collection["collection_id"], number)
        for number in range(1, 6)
    ]

    deleted = store.delete_episode(
        OWNER,
        record_id=saved[-1]["record_id"],
    )
    replacement = _append(store, collection["collection_id"], 5)
    listed = retriever.list_episodes(
        OWNER,
        collection_id=collection["collection_id"],
    )

    assert deleted["episode_number"] == 5
    assert deleted["next_sequence_number"] == 5
    assert replacement["episode_number"] == 5
    assert listed["next_sequence_number"] == 6
    assert listed["unavailable_episode_numbers"] == []


def test_middle_gap_stays_reserved_while_tail_contracts(
    tmp_path: Path,
) -> None:
    store, retriever, collection = _build_store(tmp_path)
    saved = [
        _append(store, collection["collection_id"], number)
        for number in range(1, 6)
    ]

    middle = store.delete_episode(
        OWNER,
        record_id=saved[2]["record_id"],
    )
    tail_five = store.delete_episode(
        OWNER,
        record_id=saved[4]["record_id"],
    )
    tail_four = store.delete_episode(
        OWNER,
        record_id=saved[3]["record_id"],
    )
    replacement = _append(store, collection["collection_id"], 4)
    listed = retriever.list_episodes(
        OWNER,
        collection_id=collection["collection_id"],
    )

    assert middle["next_sequence_number"] == 6
    assert tail_five["next_sequence_number"] == 5
    assert tail_four["next_sequence_number"] == 4
    assert replacement["episode_number"] == 4
    assert listed["unavailable_episode_numbers"] == [3]


def test_existing_reserved_gap_blocks_contraction_past_it(
    tmp_path: Path,
) -> None:
    store, retriever, collection = _build_store(tmp_path)
    saved = [
        _append(store, collection["collection_id"], number)
        for number in range(1, 6)
    ]

    store.delete_episode(
        OWNER,
        record_id=saved[2]["record_id"],
    )
    store.delete_episode(
        OWNER,
        record_id=saved[4]["record_id"],
    )
    store.delete_episode(
        OWNER,
        record_id=saved[3]["record_id"],
    )

    deleted_two = store.delete_episode(
        OWNER,
        record_id=saved[1]["record_id"],
    )
    replacement = _append(store, collection["collection_id"], 4)
    listed = retriever.list_episodes(
        OWNER,
        collection_id=collection["collection_id"],
    )

    assert deleted_two["next_sequence_number"] == 4
    assert replacement["episode_number"] == 4
    assert listed["unavailable_episode_numbers"] == [2, 3]

def test_legacy_reserved_tail_number_remains_reserved(
    tmp_path: Path,
) -> None:
    store, retriever, collection = _build_store(tmp_path)
    saved = [
        _append(store, collection["collection_id"], number)
        for number in range(1, 7)
    ]

    deleted_six = store.delete_episode(
        OWNER,
        record_id=saved[5]["record_id"],
    )
    assert deleted_six["next_sequence_number"] == 6

    # Simulate a pre-upgrade Collection: old deletion policy would have kept
    # episode 6 reserved and therefore left next_sequence_number at 7.
    collection_row = store._resolve_collection(
        OWNER,
        collection_id=collection["collection_id"],
        collection_name=None,
    )
    manager, _ = store._load_collection_manager(collection_row)
    manager.metainfo["next_sequence_number"] = 7
    manager.save_metainfo()
    store._write_next_sequence_number(collection["collection_id"], 7)

    deleted_five = store.delete_episode(
        OWNER,
        record_id=saved[4]["record_id"],
    )
    replacement = _append(store, collection["collection_id"], 7)
    listed = retriever.list_episodes(
        OWNER,
        collection_id=collection["collection_id"],
    )

    assert deleted_five["next_sequence_number"] == 7
    assert replacement["episode_number"] == 7
    assert listed["unavailable_episode_numbers"] == [5, 6]

