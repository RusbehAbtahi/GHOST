"""Focused tests for Clipboard slot range and retention policy."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ragstream.memory.mcp_clipboard_store import (
    CLIPBOARD_RETENTION_DAYS,
    McpClipboardStore,
    is_clipboard_slot,
    normalize_clipboard_slot,
)


@pytest.mark.parametrize(
    "slot",
    ["M1", "O735", "P20", "CV1", "PR42", "MR500", "MM10000",
     "a1", "z10000", "aa1", "Zz10000", "cv5", "Cv5", "cV5", " CV5 "],
)
def test_clipboard_slot_accepts_full_reserved_range(slot: str) -> None:
    assert is_clipboard_slot(slot)
    assert normalize_clipboard_slot(slot) == slot.strip().upper()


@pytest.mark.parametrize(
    "slot",
    ["M0", "M0001", "M10001", "M1000000", "M-1", "M1.0", "M1x", "1",
     "ABC1", "CV0", "CV10001", "CV01", "CV", "C-V1", "PR 1", "1M",
     "I\u01301", "\u01311", "\u017f1", "\u212a1", "P\u0661"],
)
def test_clipboard_slot_rejects_out_of_range_and_lookalikes(slot: str) -> None:
    assert not is_clipboard_slot(slot)
    with pytest.raises(ValueError, match="one or two ASCII letters"):
        normalize_clipboard_slot(slot)


def test_clipboard_retention_is_thirty_days() -> None:
    assert CLIPBOARD_RETENTION_DAYS == 30


def test_mcp_save_schema_keeps_recall_key_flat_and_generic() -> None:
    from ragstream.mcp.ghost_memory_tag import tool_metadata

    input_schema = tool_metadata()["inputSchema"]
    recall_key_schema = input_schema["properties"]["recall_key"]

    assert input_schema["required"] == ["input_text", "output_text"]
    assert input_schema["additionalProperties"] is False
    assert recall_key_schema["type"] == "string"
    assert recall_key_schema["minLength"] == 1
    assert "pattern" not in recall_key_schema
    assert "oneOf" not in input_schema
    assert "anyOf" not in input_schema
    assert "not" not in input_schema


def test_mcp_save_metadata_advertises_new_clipboard_policy() -> None:
    from ragstream.mcp.ghost_memory_tag import tool_metadata

    description = tool_metadata()["description"]
    assert "one or two ASCII letters followed by 1-10000" in description
    assert "case-insensitive" in description
    assert "thirty days" in description


def test_recall_metadata_advertises_mnemonic_policy() -> None:
    from ragstream.mcp.ghost_memory_recall import tool_metadata

    metadata = tool_metadata()
    assert "one or two ASCII letters followed by 1-10000" in metadata["description"]
    assert "case-insensitive" in metadata["description"]
    assert "pattern" not in metadata["inputSchema"]["properties"]["recall_key"]


@pytest.mark.parametrize("slot", ["M1", "O735", "p10000", "Cv1", "pR42", "Mr500", "mM10000"])
def test_mnemonic_keys_route_save_and_recall_without_memory_type(tmp_path: Path, slot: str) -> None:
    from ragstream.mcp.ghost_memory_recall import GhostMemoryRecallTool
    from ragstream.mcp.ghost_memory_tag import GhostMemoryTagTool
    from ragstream.memory.mcp_memory_store import McpMemoryStore

    memory_store = McpMemoryStore(tmp_path / "memory")
    save_tool = GhostMemoryTagTool(memory_store)
    recall_tool = GhostMemoryRecallTool(memory_store)
    first = save_tool.call_sanitized(
        "owner-1", {"recall_key": slot, "input_text": "First question", "output_text": "First answer"}
    )
    latest = save_tool.call_sanitized(
        "owner-1", {"recall_key": slot.lower(), "input_text": "Latest question", "output_text": "Latest answer"}
    )
    assert not first.isError
    assert not latest.isError
    assert latest.structuredContent["saved"] is True
    assert latest.structuredContent["memory_type"] == "clipboard"
    assert latest.structuredContent["recall_key"] == slot.upper()
    assert first.structuredContent["record_id"] != latest.structuredContent["record_id"]

    recalled = recall_tool.call_sanitized("owner-1", {"recall_key": slot.swapcase()})
    assert not recalled.isError
    assert recalled.structuredContent["workflow_state"] == "complete"
    assert recalled.structuredContent["retrieval_path"] == "clipboard"
    assert recalled.structuredContent["record_id"] == latest.structuredContent["record_id"]
    assert recalled.structuredContent["input_text"] == "Latest question"
    assert recalled.structuredContent["output_text"] == "Latest answer"


def test_mnemonic_prefixes_and_owners_remain_independent(tmp_path: Path) -> None:
    store = McpClipboardStore(tmp_path / "memory")
    for owner, slot, answer in [("owner-1", "P1", "single"), ("owner-1", "PR1", "double"), ("owner-2", "PR1", "other owner")]:
        store.save(owner, slot, "question", answer)

    reopened = McpClipboardStore(tmp_path / "memory")
    assert reopened.recall_latest("owner-1", "p1")["output_text"] == "single"
    assert reopened.recall_latest("owner-1", "pr1")["output_text"] == "double"
    assert reopened.recall_latest("owner-2", "pr1")["output_text"] == "other owner"
    assert reopened.recall_latest("owner-3", "PR1") is None
    assert reopened.recall_latest("owner-1", "PR2") is None


def test_mnemonic_clipboard_keeps_existing_expiration(tmp_path: Path) -> None:
    now = [datetime(2026, 9, 24, tzinfo=timezone.utc)]
    store = McpClipboardStore(tmp_path / "memory", now_provider=lambda: now[0])
    store.save("owner-1", "CV1", "question", "answer")
    assert store.recall_latest("owner-1", "cv1") is not None
    now[0] += timedelta(days=CLIPBOARD_RETENTION_DAYS + 1)
    assert store.recall_latest("owner-1", "cv1") is None


@pytest.mark.parametrize("slot", ["M0", "M10001", "PR10001", "PR01", "ABC1"])
def test_explicit_clipboard_rejects_invalid_keys_without_writes(tmp_path: Path, slot: str) -> None:
    from ragstream.mcp.ghost_memory_recall import GhostMemoryRecallTool
    from ragstream.mcp.ghost_memory_tag import GhostMemoryTagTool
    from ragstream.memory.mcp_memory_store import McpMemoryStore

    memory_store = McpMemoryStore(tmp_path / "memory")
    saved = GhostMemoryTagTool(memory_store).call_sanitized(
        "owner-1", {"memory_type": "clipboard", "recall_key": slot, "input_text": "question", "output_text": "answer"}
    )
    recalled = GhostMemoryRecallTool(memory_store).call_sanitized(
        "owner-1", {"memory_type": "clipboard", "recall_key": slot}
    )
    assert saved.isError
    assert recalled.isError
    assert "one or two ASCII letters" in saved.structuredContent["reason"]
    assert not list((tmp_path / "memory").rglob("*.ragmem"))
