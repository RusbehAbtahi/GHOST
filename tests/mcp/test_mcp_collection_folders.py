"""Focused tests for Collection folders, physical Archive, and restore."""

from __future__ import annotations

import sqlite3

from pathlib import Path

import pytest

from ragstream.mcp.ghost_memory_collection_init import GhostMemoryCollectionInitTool
from ragstream.mcp.ghost_memory_collection_manage import (
    GhostMemoryCollectionManageTool,
    TOOL_NAME as MANAGE_TOOL_NAME,
)
from ragstream.mcp.ghost_memory_list import GhostMemoryListTool
from ragstream.memory.mcp_memory_collection_browser import McpMemoryCollectionBrowser
from ragstream.memory.mcp_memory_collection_manager import McpMemoryCollectionManager
from ragstream.memory.mcp_memory_collection_retriever import (
    CollectionRecallSelection,
    McpMemoryCollectionRetriever,
)
from ragstream.memory.mcp_memory_collection_store import McpMemoryCollectionStore
from ragstream.memory.mcp_memory_store import McpMemoryStore


OWNER = "owner-1"


@pytest.fixture
def collection_parts(tmp_path: Path):
    memory_root = tmp_path / "data" / "mcp" / "memory"
    memory_store = McpMemoryStore(memory_root)
    collection_store = McpMemoryCollectionStore(memory_root, memory_store.sqlite_path)
    manager = McpMemoryCollectionManager(memory_root, memory_store.sqlite_path)
    browser = McpMemoryCollectionBrowser(memory_root, memory_store.sqlite_path)
    retriever = McpMemoryCollectionRetriever(memory_root, memory_store.sqlite_path)
    return memory_store, collection_store, manager, browser, retriever


def _append(store: McpMemoryCollectionStore, collection_id: str, title: str):
    return store.append_episode(
        OWNER,
        collection_id=collection_id,
        episode_title=title,
        episode_description=f"description-{title}",
        input_text=f"question-{title}",
        output_text=f"answer-{title}",
        active_retrieval_brief=f"brief-{title}",
    )


def test_creation_and_listing_are_scoped_to_one_physical_folder(collection_parts) -> None:
    _, store, _, browser, _ = collection_parts
    root = store.initialize_collection(OWNER, "Root", "root description")
    folder = store.initialize_collection(
        OWNER,
        "Interview",
        "folder description",
        folder="Applications",
    )

    assert root["folder"] == "Main"
    assert folder["folder"] == "Applications"
    assert [item["collection_name"] for item in browser.list_collections(OWNER)] == ["Root"]
    assert [
        item["collection_name"]
        for item in browser.list_collections(OWNER, "Applications")
    ] == ["Interview"]
    assert browser.list_collection_folders(OWNER) == [
        "Main",
        "Applications",
        "Archive",
    ]


def test_move_updates_paths_without_changing_collection_or_episode_identity(collection_parts) -> None:
    memory_store, store, manager, browser, retriever = collection_parts
    collection = store.initialize_collection(OWNER, "MoveMe", "description")
    episode = _append(store, collection["collection_id"], "one")

    result = manager.move_collection(OWNER, collection["collection_id"], "Interviews")

    assert result["folder"] == "Interviews"
    assert browser.list_collections(OWNER) == []
    moved = browser.list_collections(OWNER, "Interviews")
    assert [item["collection_id"] for item in moved] == [collection["collection_id"]]

    with sqlite3.connect(memory_store.sqlite_path) as connection:
        row = connection.execute(
            "SELECT filename_ragmem, filename_meta FROM memory_files WHERE file_id = ?",
            [collection["collection_id"]],
        ).fetchone()
    assert row is not None
    assert row[0].startswith(f"{OWNER}/collections/Interviews/")
    assert row[1].startswith(f"{OWNER}/collections/Interviews/")

    recalled = retriever.recall_episodes(
        OWNER,
        CollectionRecallSelection(mode="all"),
        collection_id=collection["collection_id"],
    )
    assert recalled["episodes"][0]["record_id"] == episode["record_id"]
    assert recalled["episodes"][0]["recall_key"] == episode["recall_key"]

    manager.move_collection(OWNER, collection["collection_id"], "Main")
    assert [item["collection_id"] for item in browser.list_collections(OWNER)] == [
        collection["collection_id"]
    ]


def test_archive_removes_sqlite_and_restore_preserves_permanent_numbering(collection_parts) -> None:
    memory_store, store, manager, browser, retriever = collection_parts
    collection = store.initialize_collection(OWNER, "ArchiveMe", "description")
    first = _append(store, collection["collection_id"], "first")
    second = _append(store, collection["collection_id"], "second")

    archived = manager.archive_collection(OWNER, collection["collection_id"])
    assert archived["folder"] == "Archive"
    archive_root = memory_store.files_root / OWNER / "collections" / "Archive"
    assert len(list(archive_root.glob("*.ragmem"))) == 1
    assert len(list(archive_root.glob("*.ragmeta.json"))) == 1

    with sqlite3.connect(memory_store.sqlite_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_files WHERE file_id = ?",
            [collection["collection_id"]],
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_records WHERE file_id = ?",
            [collection["collection_id"]],
        ).fetchone()[0] == 0

    archived_list = browser.list_collections(OWNER, "Archive")
    assert [item["collection_id"] for item in archived_list] == [collection["collection_id"]]
    with pytest.raises(ValueError):
        _append(store, collection["collection_id"], "blocked")

    restored = manager.restore_collection(OWNER, collection["collection_id"])
    assert restored["folder"] == "Main"
    recalled = retriever.recall_episodes(
        OWNER,
        CollectionRecallSelection(mode="all"),
        collection_id=collection["collection_id"],
    )
    assert recalled["returned_episode_numbers"] == [1, 2]
    assert [episode["record_id"] for episode in recalled["episodes"]] == [
        first["record_id"],
        second["record_id"],
    ]
    assert [episode["recall_key"] for episode in recalled["episodes"]] == [
        first["recall_key"],
        second["recall_key"],
    ]

    third = _append(store, collection["collection_id"], "third")
    assert third["episode_number"] == 3


def test_restore_rejects_active_name_collision_safely(collection_parts) -> None:
    _, store, manager, _, _ = collection_parts
    collection = store.initialize_collection(OWNER, "Reserved", "description")
    manager.archive_collection(OWNER, collection["collection_id"])
    store.initialize_collection(OWNER, "Reserved", "new active Collection")

    with pytest.raises(ValueError, match="active Collection"):
        manager.restore_collection(OWNER, collection["collection_id"])


def test_unsafe_and_archive_creation_folders_are_rejected(collection_parts) -> None:
    _, store, manager, _, _ = collection_parts
    collection = store.initialize_collection(OWNER, "Safe", "description")

    with pytest.raises(ValueError):
        store.initialize_collection(OWNER, "Unsafe", "description", folder="../bad")
    with pytest.raises(ValueError, match="Archive"):
        store.initialize_collection(OWNER, "Archived", "description", folder="Archive")
    with pytest.raises(ValueError, match="archive action"):
        manager.move_collection(OWNER, collection["collection_id"], "Archive")


def test_mcp_init_list_and_manage_contracts(collection_parts) -> None:
    memory_store, store, manager, browser, retriever = collection_parts
    init_tool = GhostMemoryCollectionInitTool(store)
    list_tool = GhostMemoryListTool(memory_store, retriever, browser)
    manage_tool = GhostMemoryCollectionManageTool(manager)

    created = init_tool.call_sanitized(
        OWNER,
        {
            "collection_name": "MCP",
            "collection_description": "description",
            "folder": "Applications",
        },
    )
    assert created.isError is False
    collection_id = created.structuredContent["collection_id"]
    assert created.structuredContent["folder"] == "Applications"

    folders = list_tool.call_sanitized(OWNER, {"list_mode": "collection_folders"})
    assert folders.structuredContent["folders"] == ["Main", "Applications", "Archive"]

    listed = list_tool.call_sanitized(
        OWNER,
        {"list_mode": "collections", "folder": "Applications"},
    )
    assert [item["collection_id"] for item in listed.structuredContent["collections"]] == [
        collection_id
    ]

    archived = manage_tool.call_sanitized(
        OWNER,
        {"action": "archive", "collection_id": collection_id},
    )
    assert archived.isError is False
    assert archived.structuredContent["folder"] == "Archive"

    restored = manage_tool.call_sanitized(
        OWNER,
        {
            "action": "restore",
            "collection_id": collection_id,
            "destination_folder": "Applications",
        },
    )
    assert restored.isError is False
    assert restored.structuredContent["folder"] == "Applications"
    assert MANAGE_TOOL_NAME == "ghost_memory_collection_manage"
