from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from types import SimpleNamespace

import pytest

from ragstream.memory.memory_actions import capture_memory_pair
from ragstream.memory.memory_manager import MemoryManager
from ragstream.orchestration.super_prompt import SuperPrompt
from ragstream.retrieval.retriever_mem import MemoryRetriever


class _FailingCollection:
    def __init__(self) -> None:
        self.calls = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        raise ValueError("filter rejected")


class _Embedder:
    def embed(self, texts):
        return [[0.1, 0.2, 0.3]]


def test_memory_policy_false_skips_retrieval_and_clears_stale_context() -> None:
    retriever = object.__new__(MemoryRetriever)
    retriever.config = {"enabled": True}
    retriever.memory_manager = SimpleNamespace(file_id="history-1", records=[])

    sp = SuperPrompt()
    sp.body["task"] = "new unrelated topic"
    sp.memory_context_text = "OLD MEMORY"
    sp.active_memory_brief = "OLD BRIEF"
    sp.extras["memory_context_text"] = "OLD MEMORY"
    sp.extras["activebrief_relation_decision"] = {
        "allow_memory_context": False,
    }

    out = retriever.run(sp)

    assert out is sp
    assert sp.memory_context_text == ""
    assert sp.active_memory_brief == ""
    assert sp.extras["memory_context_text"] == ""
    assert sp.memory_context_pack is not None
    assert (
        sp.memory_context_pack.selection_diagnostics.get("empty_reason")
        == "memory_context_disabled_by_activebrief_policy"
    )


def test_file_id_filter_failure_never_retries_unfiltered() -> None:
    collection = _FailingCollection()
    retriever = object.__new__(MemoryRetriever)
    retriever.memory_vector_store = SimpleNamespace(
        _collection=collection,
        embedder=_Embedder(),
    )

    with pytest.raises(RuntimeError) as exc_info:
        retriever._query_memory_vectors(
            query_text="test query",
            active_file_id="history-123",
            n_results=5,
        )

    assert len(collection.calls) == 1
    assert collection.calls[0]["where"] == {"file_id": "history-123"}
    message = str(exc_info.value)
    assert "file_id isolation filter" in message
    assert "history-123" in message
    assert "ValueError: filter rejected" in message


def test_failed_memory_retrieval_leaves_no_stale_memory_context() -> None:
    retriever = object.__new__(MemoryRetriever)
    retriever.config = {"enabled": True}
    retriever.memory_manager = SimpleNamespace(file_id="history-1", records=[])

    def fail_semantic_pass(**kwargs):
        raise RuntimeError("synthetic retrieval failure")

    retriever._run_semantic_pass = fail_semantic_pass

    sp = SuperPrompt()
    sp.body["task"] = "current query"
    sp.effective_retrieval_query_text = "current query"
    sp.memory_context_text = "STALE MEMORY"
    sp.memory_context_pack = object()
    sp.extras["memory_context_text"] = "STALE MEMORY"
    sp.extras["memory_context_pack"] = {"old": True}

    with pytest.raises(RuntimeError, match="synthetic retrieval failure"):
        retriever.run(sp)

    assert sp.memory_context_text == ""
    assert sp.memory_context_pack is None
    assert "memory_context_text" not in sp.extras
    assert "memory_context_pack" not in sp.extras


def test_activebrief_failure_saves_record_preserves_previous_brief_and_returns_warning(
    tmp_path,
    monkeypatch,
) -> None:
    from ragstream.memory.compression import memory_active_retrieval_brief as brief_module

    class _ControlledBuilder:
        calls = 0

        def build_for_record(self, *, record, previous_records, pending_topic_buffer):
            type(self).calls += 1
            if type(self).calls == 1:
                return {
                    "active_retrieval_brief_title": "Stable Topic",
                    "active_retrieval_brief": "Stable previous brief",
                    "active_retrieval_brief_contributor_ids": [record.record_id],
                    "pending_activebrief_topic_buffer": {"kept": "state"},
                    "activebrief_llm_skipped": False,
                    "activebrief_gate_route": "test",
                }
            raise ValueError("synthetic ActiveBrief failure")

    monkeypatch.setattr(
        brief_module,
        "MemoryActiveRetrievalBriefBuilder",
        _ControlledBuilder,
    )

    manager = MemoryManager(
        memory_root=tmp_path / "memory",
        sqlite_path=tmp_path / "memory.sqlite3",
    )
    manager.start_new_history("M50 Test")

    first = manager.capture_pair(
        input_text="first question",
        output_text="first answer",
        source="test",
    )
    assert first.active_retrieval_brief == "Stable previous brief"
    previous_buffer = dict(manager.pending_activebrief_topic_buffer)

    result = capture_memory_pair(
        memory_manager=manager,
        input_text="second question",
        output_text="second answer",
        source="test",
    )

    assert result["success"] is True
    assert "ValueError: synthetic ActiveBrief failure" in result["warning"]
    assert result["warning"] in result["message"]
    assert len(manager.records) == 2
    assert manager.records[0].active_retrieval_brief == "Stable previous brief"
    assert manager.records[1].active_retrieval_brief == ""
    assert manager.records[1].active_retrieval_brief_title == ""
    assert manager.pending_activebrief_topic_buffer == previous_buffer
    assert manager.ragmem_path.exists()
    assert "second answer" in manager.ragmem_path.read_text(encoding="utf-8")
