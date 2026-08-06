"""Focused tests for per-owner MCP memory persistence and Direct Recall."""

from __future__ import annotations

import json
import re
import sqlite3

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import ragstream.memory.memory_record as memory_record_module
from ragstream.memory.mcp_memory_store import McpMemoryStore
from ragstream.memory.memory_record import MemoryRecord, RECORD_END, RECORD_START
from ragstream.memory.retrieval.memory_index_lookup import MemoryIndexLookup


STABLE_RAGMEM_FIELDS = {
    "record_id",
    "parent_id",
    "created_at_utc",
    "input_text",
    "output_text",
    "source",
    "input_hash",
    "output_hash",
    "active_retrieval_brief_title",
    "active_retrieval_brief",
    "active_retrieval_brief_contributor_ids",
}


@pytest.fixture(autouse=True)
def disable_keyword_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep persistence tests independent from YAKE's extracted values."""
    monkeypatch.setattr(MemoryRecord, "generate_auto_keywords", lambda self: [])


@pytest.fixture
def store(tmp_path: Path) -> McpMemoryStore:
    return McpMemoryStore(tmp_path / "data" / "mcp" / "memory")


def test_first_tag_creates_compatible_daily_files_and_index(
    store: McpMemoryStore,
) -> None:
    owner_sub = "cognito-user_123"
    record = store.tag_memory(
        owner_sub=owner_sub,
        recall_key="architecture",
        input_text="Original question",
        output_text="Original answer",
    )

    utc_date = record.created_at_utc[:10]
    owner_root = store.files_root / owner_sub
    ragmem_path = owner_root / f"MCP_MEM_{utc_date}.ragmem"
    meta_path = owner_root / f"MCP_MEM_{utc_date}.ragmeta.json"

    assert ragmem_path.is_file()
    assert meta_path.is_file()
    assert store.sqlite_path.is_file()
    assert store.vector_root.is_dir()
    assert list(store.vector_root.iterdir()) == []

    ragmem_records = _read_ragmem_records(ragmem_path)
    assert len(ragmem_records) == 1
    assert set(ragmem_records[0]) == STABLE_RAGMEM_FIELDS
    assert "owner_sub" not in ragmem_records[0]
    assert "direct_recall_key" not in ragmem_records[0]

    metainfo = json.loads(meta_path.read_text(encoding="utf-8"))
    assert metainfo["owner_sub"] == owner_sub
    assert metainfo["filename_ragmem"] == (
        f"{owner_sub}/MCP_MEM_{utc_date}.ragmem"
    )
    assert metainfo["filename_meta"] == (
        f"{owner_sub}/MCP_MEM_{utc_date}.ragmeta.json"
    )
    assert metainfo["record_count"] == 1

    record_meta = metainfo["records"][0]
    assert record_meta["tag"] == "Green"
    assert record_meta["retrieval_source_mode"] == "QA"
    assert record_meta["direct_recall_key"] == "architecture"
    assert record_meta["user_keywords"] == []
    assert record_meta["active_project_name"] is None
    assert record_meta["embedded_files_snapshot"] == []
    assert ragmem_records[0]["active_retrieval_brief_title"] == ""
    assert ragmem_records[0]["active_retrieval_brief"] == ""
    assert ragmem_records[0]["active_retrieval_brief_contributor_ids"] == []

    with sqlite3.connect(store.sqlite_path) as conn:
        file_row = conn.execute(
            "SELECT owner_sub, record_count FROM memory_files"
        ).fetchone()
        record_row = conn.execute(
            "SELECT source, tag, direct_recall_key FROM memory_records"
        ).fetchone()

    assert file_row == (owner_sub, 1)
    assert record_row == ("mcp", "Green", "architecture")


def test_second_tag_appends_to_same_user_day(store: McpMemoryStore) -> None:
    first = store.tag_memory("owner-1", "first", "Input 1", "Output 1")
    second = store.tag_memory("owner-1", "second", "Input 2", "Output 2")

    assert first.created_at_utc[:10] == second.created_at_utc[:10]
    utc_date = first.created_at_utc[:10]
    owner_root = store.files_root / "owner-1"
    ragmem_path = owner_root / f"MCP_MEM_{utc_date}.ragmem"
    meta_path = owner_root / f"MCP_MEM_{utc_date}.ragmeta.json"

    assert len(_read_ragmem_records(ragmem_path)) == 2
    assert json.loads(meta_path.read_text(encoding="utf-8"))["record_count"] == 2

    with sqlite3.connect(store.sqlite_path) as conn:
        file_count = conn.execute("SELECT COUNT(*) FROM memory_files").fetchone()[0]
        record_count = conn.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0]

    assert file_count == 1
    assert record_count == 2


def test_recall_preserves_markdown_unicode_and_owner_isolation(
    store: McpMemoryStore,
) -> None:
    input_text = "سؤال با Markdown:\n\n```python\nprint('سلام')\n```"
    output_text = "```mermaid\nflowchart TD\n    A --> B\n```"

    first_record = store.tag_memory("owner.alpha", "shared-key", input_text, output_text)
    second_record = store.tag_memory(
        "owner.beta",
        "shared-key",
        "Different input",
        "Different output",
    )

    first_result = store.recall_memory("owner.alpha", "shared-key")
    second_result = store.recall_memory("owner.beta", "shared-key")

    assert first_result is not None
    assert first_result["record_id"] == first_record.record_id
    assert first_result["input_text"] == input_text
    assert first_result["output_text"] == output_text
    assert second_result is not None
    assert second_result["record_id"] == second_record.record_id
    assert store.recall_memory("owner.alpha", "missing-key") is None
    assert (store.files_root / "owner.alpha").is_dir()
    assert (store.files_root / "owner.beta").is_dir()

    with sqlite3.connect(store.sqlite_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM memory_files").fetchone()[0] == 2


def test_duplicate_key_keeps_existing_priority_and_recency_rules(
    store: McpMemoryStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timestamps = iter(
        [
            "2026-08-06T10:00:00Z",
            "2026-08-06T11:00:00Z",
        ]
    )
    monkeypatch.setattr(memory_record_module, "_utc_now", lambda: next(timestamps))

    older = store.tag_memory("owner-1", "duplicate", "Older", "Older answer")
    newer = store.tag_memory("owner-1", "duplicate", "Newer", "Newer answer")

    result = store.recall_memory("owner-1", "duplicate")
    assert result is not None
    assert result["record_id"] == newer.record_id

    with sqlite3.connect(store.sqlite_path) as conn:
        conn.execute(
            "UPDATE memory_records SET tag = 'Gold' WHERE record_id = ?",
            (older.record_id,),
        )
        conn.commit()

    result = store.recall_memory("owner-1", "duplicate")
    assert result is not None
    assert result["record_id"] == older.record_id
    assert result["tag"] == "Gold"


def test_new_utc_day_creates_another_daily_pair(
    store: McpMemoryStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timestamps = iter(
        [
            "2026-08-06T23:59:59Z",
            "2026-08-07T00:00:01Z",
        ]
    )
    monkeypatch.setattr(memory_record_module, "_utc_now", lambda: next(timestamps))

    store.tag_memory("owner-1", "day-one", "Input 1", "Output 1")
    store.tag_memory("owner-1", "day-two", "Input 2", "Output 2")

    owner_root = store.files_root / "owner-1"
    assert (owner_root / "MCP_MEM_2026-08-06.ragmem").is_file()
    assert (owner_root / "MCP_MEM_2026-08-07.ragmem").is_file()

    with sqlite3.connect(store.sqlite_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM memory_files").fetchone()[0] == 2


def test_concurrent_tags_do_not_lose_records(store: McpMemoryStore) -> None:
    def save(index: int) -> str:
        return store.tag_memory(
            "owner-1",
            f"key-{index}",
            f"Input {index}",
            f"Output {index}",
        ).record_id

    with ThreadPoolExecutor(max_workers=8) as executor:
        record_ids = list(executor.map(save, range(20)))

    assert len(set(record_ids)) == 20

    with sqlite3.connect(store.sqlite_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0] == 20

    meta_path = next((store.files_root / "owner-1").glob("*.ragmeta.json"))
    metainfo = json.loads(meta_path.read_text(encoding="utf-8"))
    ragmem_path = next((store.files_root / "owner-1").glob("*.ragmem"))
    assert metainfo["record_count"] == 20
    assert len(_read_ragmem_records(ragmem_path)) == 20


@pytest.mark.parametrize(
    "unsafe_owner",
    ["", ".", "..", "../owner", "owner/name", r"owner\name", "owner name"],
)
def test_unsafe_owner_sub_is_rejected(
    store: McpMemoryStore,
    unsafe_owner: str,
) -> None:
    with pytest.raises(ValueError, match="safe path component"):
        store.tag_memory(unsafe_owner, "key", "Input", "Output")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("recall_key", "   "),
        ("input_text", ""),
        ("output_text", "\n\t"),
    ],
)
def test_empty_required_text_is_rejected(
    store: McpMemoryStore,
    field: str,
    value: str,
) -> None:
    arguments = {
        "owner_sub": "owner-1",
        "recall_key": "key",
        "input_text": "Input",
        "output_text": "Output",
    }
    arguments[field] = value

    with pytest.raises(ValueError, match=field):
        store.tag_memory(**arguments)


@pytest.mark.parametrize("corruption", ["wrong_owner", "invalid_json"])
def test_corrupt_or_mismatched_metadata_stops_the_next_write(
    store: McpMemoryStore,
    corruption: str,
) -> None:
    record = store.tag_memory("owner-1", "first", "Input", "Output")
    meta_path = (
        store.files_root
        / "owner-1"
        / f"MCP_MEM_{record.created_at_utc[:10]}.ragmeta.json"
    )

    if corruption == "wrong_owner":
        metainfo = json.loads(meta_path.read_text(encoding="utf-8"))
        metainfo["owner_sub"] = "owner-2"
        meta_path.write_text(json.dumps(metainfo), encoding="utf-8")
    else:
        meta_path.write_text("{invalid", encoding="utf-8")

    with pytest.raises(ValueError, match="metadata|owner"):
        store.tag_memory("owner-1", "second", "Input 2", "Output 2")


def test_direct_recall_without_owner_remains_compatible_with_legacy_schema(
    tmp_path: Path,
) -> None:
    memory_root = tmp_path / "legacy-memory"
    files_root = memory_root / "files"
    files_root.mkdir(parents=True)
    sqlite_path = memory_root / "memory_index.sqlite3"

    record = MemoryRecord(
        input_text="Legacy input",
        output_text="Legacy output",
        source="manual",
        direct_recall_key="legacy-key",
    )
    (files_root / "legacy.ragmem").write_text(
        record.to_ragmem_block(),
        encoding="utf-8",
    )
    _create_legacy_index(sqlite_path, record)

    lookup = MemoryIndexLookup(sqlite_path, memory_root)
    result = lookup.get_direct_recall("legacy-key", {})

    assert result is not None
    assert result["record_id"] == record.record_id
    assert result["input_text"] == "Legacy input"
    assert result["output_text"] == "Legacy output"
    assert lookup.get_direct_recall("legacy-key", {}, owner_sub="") is None


def _read_ragmem_records(path: Path) -> list[dict[str, object]]:
    pattern = re.compile(
        rf"{re.escape(RECORD_START)}\n(.*?)\n{re.escape(RECORD_END)}",
        re.DOTALL,
    )
    return [
        json.loads(match.group(1))
        for match in pattern.finditer(path.read_text(encoding="utf-8"))
    ]


def _create_legacy_index(sqlite_path: Path, record: MemoryRecord) -> None:
    index_data = record.to_index_dict()

    with sqlite3.connect(sqlite_path) as conn:
        conn.execute(
            """
            CREATE TABLE memory_files (
                file_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                filename_ragmem TEXT NOT NULL,
                filename_meta TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL,
                record_count INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE memory_records (
                file_id TEXT NOT NULL,
                record_id TEXT NOT NULL,
                parent_id TEXT,
                created_at_utc TEXT NOT NULL,
                source TEXT NOT NULL,
                tag TEXT NOT NULL,
                retrieval_source_mode TEXT NOT NULL,
                direct_recall_key TEXT NOT NULL,
                auto_keywords_json TEXT NOT NULL,
                user_keywords_json TEXT NOT NULL,
                active_project_name TEXT,
                embedded_files_snapshot_json TEXT NOT NULL,
                input_hash TEXT NOT NULL,
                output_hash TEXT NOT NULL,
                PRIMARY KEY (file_id, record_id)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO memory_files VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-file",
                "Legacy",
                "legacy.ragmem",
                "legacy.ragmeta.json",
                record.created_at_utc,
                record.created_at_utc,
                1,
            ),
        )
        conn.execute(
            """
            INSERT INTO memory_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-file",
                index_data["record_id"],
                index_data["parent_id"],
                index_data["created_at_utc"],
                index_data["source"],
                index_data["tag"],
                index_data["retrieval_source_mode"],
                index_data["direct_recall_key"],
                json.dumps(index_data["auto_keywords"]),
                json.dumps(index_data["user_keywords"]),
                index_data["active_project_name"],
                json.dumps(index_data["embedded_files_snapshot"]),
                index_data["input_hash"],
                index_data["output_hash"],
            ),
        )
        conn.commit()