"""Acceptance tests for MCP Episodic Memory save and recall.

The suite covers the complete deterministic contract introduced for Episodic
Memory. External embedding and Chroma services are replaced by small in-memory
test doubles, so these tests are fast, repeatable, and require no API key.
"""

from __future__ import annotations

import math
import re
import sqlite3

from collections import Counter
from pathlib import Path
from typing import Any

import pytest

import ragstream.memory.memory_record as memory_record_module
from ragstream.mcp.ghost_memory_recall import (
    RESULT_MODE_DESCRIPTION,
    RESULT_MODE_EPISODE,
    RETRIEVAL_EXACT,
    RETRIEVAL_SEMANTIC,
    WORKFLOW_COMPLETE,
    WORKFLOW_SELECTION_REQUIRED,
    GhostMemoryRecallTool,
)
from ragstream.mcp.ghost_memory_tag import GhostMemoryTagTool
from ragstream.mcp.memory_tool_instructions import (
    load_memory_tool_instructions,
)
from ragstream.memory.mcp_episodic_description_vector_store import (
    McpEpisodicDescriptionVectorStore,
)
from ragstream.memory.mcp_memory_store import McpMemoryStore
from ragstream.memory.memory_record import MemoryRecord


class InMemoryDescriptionVectorStore:
    """Provide deterministic cosine search without OpenAI or Chroma.

    The fake keeps the same public methods used by ``McpMemoryStore``. Text is
    represented as a word-frequency vector, which is sufficient to verify
    owner filtering, candidate filtering, ranking, limits, and workflow wiring.
    """

    def __init__(self) -> None:
        self.records: dict[str, dict[str, str]] = {}
        self.upsert_calls: list[dict[str, str]] = []
        self.deleted_record_ids: list[str] = []

    def upsert_description(
        self,
        *,
        owner_sub: str,
        file_id: str,
        record_id: str,
        episode_description: str,
        created_at_utc: str,
    ) -> None:
        payload = {
            "owner_sub": owner_sub,
            "file_id": file_id,
            "record_id": record_id,
            "episode_description": episode_description,
            "created_at_utc": created_at_utc,
        }
        self.records[record_id] = payload
        self.upsert_calls.append(payload)

    def search_descriptions(
        self,
        *,
        owner_sub: str,
        query_description: str,
        candidate_record_ids: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        allowed_ids = set(candidate_record_ids)
        hits: list[dict[str, Any]] = []

        for record_id, record in self.records.items():
            if record_id not in allowed_ids:
                continue
            if record["owner_sub"] != owner_sub:
                continue

            similarity = self._cosine_similarity(
                query_description,
                record["episode_description"],
            )
            hits.append(
                {
                    "record_id": record_id,
                    "episode_description": record["episode_description"],
                    "cosine_distance": 1.0 - similarity,
                    "cosine_similarity": similarity,
                }
            )

        hits.sort(
            key=lambda item: (
                -float(item["cosine_similarity"]),
                str(item["record_id"]),
            )
        )
        return hits[:limit]

    def delete_records(self, record_ids: list[str] | set[str]) -> None:
        for record_id in record_ids:
            self.records.pop(record_id, None)
            self.deleted_record_ids.append(record_id)

    @classmethod
    def _cosine_similarity(cls, first: str, second: str) -> float:
        first_vector = cls._word_vector(first)
        second_vector = cls._word_vector(second)
        shared_words = set(first_vector).intersection(second_vector)
        numerator = sum(
            first_vector[word] * second_vector[word]
            for word in shared_words
        )
        first_length = math.sqrt(
            sum(value * value for value in first_vector.values())
        )
        second_length = math.sqrt(
            sum(value * value for value in second_vector.values())
        )
        if first_length == 0.0 or second_length == 0.0:
            return 0.0
        return numerator / (first_length * second_length)

    @staticmethod
    def _word_vector(text: str) -> Counter[str]:
        return Counter(re.findall(r"[a-z0-9]+", text.lower()))


class RecordingEmbedder:
    """Record embedded text and return one stable non-empty vector."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[0.25, 0.75] for _ in texts]


class RecordingCollection:
    """Record Chroma-shaped calls and return one cosine-distance result."""

    def __init__(self) -> None:
        self.upserts: list[dict[str, Any]] = []
        self.queries: list[dict[str, Any]] = []
        self.deletes: list[list[str]] = []

    def upsert(self, **arguments: Any) -> None:
        self.upserts.append(arguments)

    def query(self, **arguments: Any) -> dict[str, Any]:
        self.queries.append(arguments)
        return {
            "ids": [["record-1"]],
            "documents": [["Authentication architecture decision"]],
            "metadatas": [[{"record_id": "record-1"}]],
            "distances": [[0.2]],
        }

    def delete(self, *, ids: list[str]) -> None:
        self.deletes.append(ids)


@pytest.fixture(autouse=True)
def disable_keyword_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep this suite independent from YAKE keyword extraction."""
    monkeypatch.setattr(
        MemoryRecord,
        "generate_auto_keywords",
        lambda self: [],
    )


@pytest.fixture
def vector_store() -> InMemoryDescriptionVectorStore:
    return InMemoryDescriptionVectorStore()


@pytest.fixture
def store(
    tmp_path: Path,
    vector_store: InMemoryDescriptionVectorStore,
) -> McpMemoryStore:
    return McpMemoryStore(
        memory_root=tmp_path / "mcp-memory",
        description_vector_store=vector_store,  # type: ignore[arg-type]
    )


def _save(
    store: McpMemoryStore,
    *,
    owner_sub: str = "owner-1",
    recall_key: str = "architecture",
    title: str = "Architecture decision",
    description: str = "Authentication architecture decision",
    input_text: str = "How should authentication work?",
    output_text: str = "Use OAuth with owner-scoped storage.",
) -> MemoryRecord:
    """Save one complete episode with compact defaults."""
    return store.save_episodic_memory(
        owner_sub=owner_sub,
        recall_key=recall_key,
        episode_title=title,
        episode_description=description,
        input_text=input_text,
        output_text=output_text,
    )


def test_save_persists_episode_and_indexes_its_description(
    store: McpMemoryStore,
    vector_store: InMemoryDescriptionVectorStore,
) -> None:
    record = _save(store)

    assert record.direct_recall_key == "architecture"
    assert record.episode_title == "Architecture decision"
    assert record.episode_description == (
        "Authentication architecture decision"
    )

    assert len(vector_store.upsert_calls) == 1
    indexed = vector_store.upsert_calls[0]
    assert indexed["owner_sub"] == "owner-1"
    assert indexed["record_id"] == record.record_id
    assert indexed["episode_description"] == record.episode_description

    with sqlite3.connect(store.sqlite_path) as connection:
        row = connection.execute(
            """
            SELECT mf.owner_sub,
                   mf.memory_type,
                   mr.direct_recall_key,
                   mr.episode_title,
                   mr.episode_description
            FROM memory_records AS mr
            JOIN memory_files AS mf ON mf.file_id = mr.file_id
            WHERE mr.record_id = ?
            """,
            [record.record_id],
        ).fetchone()

    assert row == (
        "owner-1",
        "episodic",
        "architecture",
        "Architecture decision",
        "Authentication architecture decision",
    )


def test_duplicate_recall_key_receives_deterministic_suffix(
    store: McpMemoryStore,
) -> None:
    first = _save(store, recall_key="project-alpha")
    second = _save(store, recall_key="project-alpha")
    third = _save(store, recall_key="project-alpha")

    assert first.direct_recall_key == "project-alpha"
    assert second.direct_recall_key == "project-alpha_1"
    assert third.direct_recall_key == "project-alpha_2"


@pytest.mark.parametrize("reserved_key", ["M1", "m50", "M100"])
def test_clipboard_keys_are_reserved_for_future_clipboard_memory(
    store: McpMemoryStore,
    reserved_key: str,
) -> None:
    with pytest.raises(ValueError, match="reserved for Clipboard Memory"):
        _save(store, recall_key=reserved_key)


def test_exact_recall_supports_key_id_and_owner_isolation(
    store: McpMemoryStore,
) -> None:
    owner_one = _save(store, owner_sub="owner-1", recall_key="shared")
    owner_two = _save(
        store,
        owner_sub="owner-2",
        recall_key="shared",
        input_text="Owner two question",
        output_text="Owner two answer",
    )

    by_key = store.recall_memory(
        "owner-1",
        recall_key="shared",
    )
    by_id = store.recall_memory(
        "owner-1",
        record_id=owner_one.record_id,
    )

    assert by_key is not None
    assert by_id is not None
    assert by_key == by_id
    assert by_key["record_id"] == owner_one.record_id
    assert by_key["input_text"] == "How should authentication work?"
    assert by_key["output_text"] == (
        "Use OAuth with owner-scoped storage."
    )
    assert store.recall_memory(
        "owner-1",
        record_id=owner_two.record_id,
    ) is None


def test_semantic_recall_returns_at_most_ten_ranked_descriptions(
    store: McpMemoryStore,
) -> None:
    best = _save(
        store,
        recall_key="best-match",
        description="authentication architecture oauth security",
    )
    for index in range(11):
        _save(
            store,
            recall_key=f"other-{index}",
            title=f"Other episode {index}",
            description=f"deployment operations topic {index}",
        )

    candidates = store.search_episodic_memories(
        owner_sub="owner-1",
        query_description="authentication oauth architecture",
    )

    assert len(candidates) == 10
    assert candidates[0]["record_id"] == best.record_id
    assert candidates[0]["recall_key"] == "best-match"
    assert candidates[0]["cosine_similarity"] > 0.0
    assert set(candidates[0]) == {
        "record_id",
        "recall_key",
        "episode_title",
        "episode_description",
        "created_at_utc",
        "cosine_similarity",
    }
    assert "input_text" not in candidates[0]
    assert "output_text" not in candidates[0]


def test_semantic_recall_applies_inclusive_date_filter(
    store: McpMemoryStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timestamps = iter(
        [
            "2026-01-10T10:00:00Z",
            "2026-02-10T10:00:00Z",
        ]
    )
    monkeypatch.setattr(
        memory_record_module,
        "_utc_now",
        lambda: next(timestamps),
    )

    _save(store, recall_key="january")
    february = _save(store, recall_key="february")

    candidates = store.search_episodic_memories(
        owner_sub="owner-1",
        query_description="authentication architecture",
        date_from="2026-02-01",
        date_to="2026-02-28",
    )

    assert [candidate["record_id"] for candidate in candidates] == [
        february.record_id
    ]


def test_save_tool_returns_effective_key_and_complete_state(
    store: McpMemoryStore,
) -> None:
    tool = GhostMemoryTagTool(store)
    arguments = {
        "recall_key": "design",
        "episode_title": "Design session",
        "episode_description": "Database schema design decisions",
        "input_text": "Design the schema",
        "output_text": "Use owner-scoped records",
    }

    first = tool.call_sanitized("owner-1", arguments)
    second = tool.call_sanitized("owner-1", arguments)

    assert first.isError is False
    assert first.structuredContent["saved"] is True
    assert first.structuredContent["workflow_state"] == WORKFLOW_COMPLETE
    assert first.structuredContent["requested_recall_key"] == "design"
    assert first.structuredContent["recall_key"] == "design"
    assert second.structuredContent["requested_recall_key"] == "design"
    assert second.structuredContent["recall_key"] == "design_1"


def test_recall_tool_runs_semantic_selection_then_exact_fetch(
    store: McpMemoryStore,
) -> None:
    selected = _save(
        store,
        recall_key="oauth-decision",
        title="OAuth decision",
        description="OAuth authentication architecture decision",
        input_text="Which authentication protocol should we use?",
        output_text="Use OAuth 2.1 with PKCE.",
    )
    _save(
        store,
        recall_key="logging-decision",
        title="Logging decision",
        description="Application logging and metrics decision",
    )
    tool = GhostMemoryRecallTool(store)

    candidate_result = tool.call_sanitized(
        "owner-1",
        {
            "query_description": "OAuth authentication architecture",
            "result_mode": RESULT_MODE_EPISODE,
        },
    )

    assert candidate_result.isError is False
    assert candidate_result.structuredContent["workflow_state"] == (
        WORKFLOW_SELECTION_REQUIRED
    )
    assert candidate_result.structuredContent["retrieval_path"] == (
        RETRIEVAL_SEMANTIC
    )
    assert candidate_result.structuredContent["candidate_count"] == 2
    candidates = candidate_result.structuredContent["candidates"]
    assert candidates[0]["record_id"] == selected.record_id

    final_result = tool.call_sanitized(
        "owner-1",
        {
            "record_id": candidates[0]["record_id"],
            "result_mode": RESULT_MODE_EPISODE,
        },
    )

    assert final_result.isError is False
    assert final_result.structuredContent["workflow_state"] == (
        WORKFLOW_COMPLETE
    )
    assert final_result.structuredContent["retrieval_path"] == RETRIEVAL_EXACT
    assert final_result.structuredContent["record_id"] == selected.record_id
    assert final_result.structuredContent["input_text"] == (
        "Which authentication protocol should we use?"
    )
    assert final_result.structuredContent["output_text"] == (
        "Use OAuth 2.1 with PKCE."
    )


def test_description_mode_returns_only_the_description(
    store: McpMemoryStore,
) -> None:
    record = _save(store, recall_key="description-only")
    tool = GhostMemoryRecallTool(store)

    result = tool.call_sanitized(
        "owner-1",
        {
            "record_id": record.record_id,
            "result_mode": RESULT_MODE_DESCRIPTION,
        },
    )

    assert result.isError is False
    assert result.content == [
        {
            "type": "text",
            "text": "Authentication architecture decision",
        }
    ]
    assert result.structuredContent["result_mode"] == (
        RESULT_MODE_DESCRIPTION
    )
    assert result.structuredContent["workflow_state"] == WORKFLOW_COMPLETE
    assert "input_text" not in result.structuredContent
    assert "output_text" not in result.structuredContent


def test_recall_validation_finishes_with_deterministic_error_state(
    store: McpMemoryStore,
) -> None:
    tool = GhostMemoryRecallTool(store)

    result = tool.call_sanitized(
        "owner-1",
        {
            "recall_key": "known-key",
            "query_description": "conflicting semantic request",
        },
    )

    assert result.isError is True
    assert result.structuredContent["workflow_state"] == WORKFLOW_COMPLETE
    assert result.structuredContent["retrieval_path"] == RETRIEVAL_EXACT
    assert "cannot accompany" in result.structuredContent["reason"]


def test_instruction_json_files_load_into_typed_contract() -> None:
    save_instructions = load_memory_tool_instructions(
        "custom_memory_save.json"
    )
    recall_instructions = load_memory_tool_instructions(
        "custom_memory_recall.json"
    )

    assert save_instructions.tool_description
    assert save_instructions.server_instruction
    assert {
        "recall_key",
        "episode_title",
        "episode_description",
        "input_text",
        "output_text",
    }.issubset(save_instructions.field_descriptions)

    assert recall_instructions.tool_description
    assert recall_instructions.server_instruction
    assert {
        "recall_key",
        "record_id",
        "query_description",
        "date_from",
        "date_to",
        "result_mode",
    }.issubset(recall_instructions.field_descriptions)


def test_description_vector_adapter_embeds_upserts_and_normalizes_cosine(
    tmp_path: Path,
) -> None:
    embedder = RecordingEmbedder()
    collection = RecordingCollection()
    vector_store = McpEpisodicDescriptionVectorStore(
        persist_dir=tmp_path / "vectors",
        embedder=embedder,
    )
    vector_store._collection = collection

    vector_store.upsert_description(
        owner_sub="owner-1",
        file_id="file-1",
        record_id="record-1",
        episode_description="Authentication architecture decision",
        created_at_utc="2026-08-15T10:00:00Z",
    )
    hits = vector_store.search_descriptions(
        owner_sub="owner-1",
        query_description="authentication decision",
        candidate_record_ids=["record-1"],
        limit=10,
    )

    assert embedder.calls == [
        ["Authentication architecture decision"],
        ["authentication decision"],
    ]
    assert collection.upserts[0]["ids"] == ["record-1"]
    assert collection.upserts[0]["embeddings"] == [[0.25, 0.75]]
    assert collection.queries[0]["n_results"] == 1
    assert collection.queries[0]["where"] == {
        "$and": [
            {"owner_sub": "owner-1"},
            {"record_id": {"$in": ["record-1"]}},
        ]
    }
    assert hits == [
        {
            "record_id": "record-1",
            "episode_description": (
                "Authentication architecture decision"
            ),
            "cosine_distance": 0.2,
            "cosine_similarity": 0.8,
        }
    ]