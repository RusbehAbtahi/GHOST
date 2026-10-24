from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import ragstream.app.controller as controller_module
from ragstream.app.controller import AppController
from ragstream.orchestration.super_prompt import SuperPrompt


class _MustNotRun:
    def run(self, *args, **kwargs):
        raise AssertionError("stage must have been bypassed")


def _relation_sp(materiality: str, relation: str) -> SuperPrompt:
    sp = SuperPrompt(stage="preprocessed")
    sp.body["task"] = "current request"
    sp.extras["activebrief_prompt_materiality"] = materiality
    sp.extras["activebrief_topic_relation"] = relation
    sp.extras["activebrief_relation_decision"] = {
        "allow_memory_context": not (relation == "IRRELEVANT")
    }
    sp.extras["activebrief_relation_activebrief"] = {
        "record_id": "old-record",
        "title": "Old Topic",
        "body": "Old topic details that must not leak.",
    }
    return sp


def test_prompt_shaping_off_is_true_a2_bypass() -> None:
    ctrl = object.__new__(AppController)
    ctrl.a2_promptshaper = _MustNotRun()

    sp = SuperPrompt(stage="preprocessed")
    sp.body["task"] = "keep me unchanged"
    before_body = dict(sp.body)
    before_extras = dict(sp.extras)

    out = ctrl.run_a2_promptshaper(sp, use_llm=False)

    assert out is sp
    assert sp.body == before_body
    assert sp.extras == before_extras
    assert sp.stage == "preprocessed"
    assert "a2" not in sp.history_of_stages


def test_preprocess_rebuilds_query_after_relation_classification(monkeypatch) -> None:
    def fake_preprocess(text, sp, schema):
        sp.body["task"] = text
        sp.effective_retrieval_query_text = "STALE PRE-CLASSIFIER QUERY"

    class _Classifier:
        def run(self, *, sp, memory_manager, raw_user_text):
            sp.extras["activebrief_prompt_materiality"] = "WEAK"
            sp.extras["activebrief_topic_relation"] = "IRRELEVANT"
            sp.extras["activebrief_relation_decision"] = {
                "allow_memory_context": False,
            }
            sp.extras["activebrief_relation_activebrief"] = {
                "record_id": "old-record",
                "title": "Old Topic",
                "body": "Old summary",
            }
            return sp

    monkeypatch.setattr(controller_module, "preprocess", fake_preprocess)

    ctrl = object.__new__(AppController)
    ctrl.schema = object()
    ctrl.activebrief_relation_classifier = _Classifier()

    sp = SuperPrompt()
    out = ctrl.preprocess("haha", sp, memory_manager=None)

    assert out is sp
    assert sp.effective_retrieval_query_text == ""
    assert "Old Topic" not in sp.prompt_ready
    assert "Old summary" not in sp.prompt_ready
    assert "haha" in sp.prompt_ready


def test_weak_irrelevant_bypasses_all_enrichment_stages() -> None:
    ctrl = object.__new__(AppController)
    ctrl.retriever = _MustNotRun()
    ctrl.reranker = _MustNotRun()
    ctrl.a3_nli_gate = _MustNotRun()
    ctrl.a4_condenser = _MustNotRun()
    ctrl.memory_retriever = _MustNotRun()

    sp = _relation_sp("WEAK", "IRRELEVANT")
    sp.effective_retrieval_query_text = "stale query"
    sp.memory_context_text = "stale memory"
    sp.S_CTX_MD = "stale document summary"
    sp.extras["memory_context_text"] = "stale memory"
    sp.extras["a3_selection_band"] = "stale"

    assert ctrl.run_retrieval(sp, "unused-project", 5) is sp
    assert ctrl.run_reranker(sp) is sp
    assert ctrl.run_a3(sp) is sp
    assert ctrl.run_a4(sp) is sp

    assert sp.effective_retrieval_query_text == ""
    assert sp.memory_context_text == ""
    assert sp.S_CTX_MD == ""
    assert sp.base_context_chunks == []
    assert sp.views_by_stage == {}
    assert sp.final_selection_ids == []
    assert "Old Topic" not in sp.prompt_ready
    assert "Old topic details" not in sp.prompt_ready
    assert "current request" in sp.prompt_ready


def test_strong_irrelevant_keeps_topic_title_but_hides_memory_context() -> None:
    sp = _relation_sp("STRONG", "IRRELEVANT")
    sp.memory_context_text = "STALE MEMORY CONTEXT"
    sp.extras["memory_context_text"] = "STALE MEMORY CONTEXT"

    sp.compose_prompt_ready()

    assert "Old Topic" in sp.prompt_ready
    assert "Old topic details" not in sp.prompt_ready
    assert "STALE MEMORY CONTEXT" not in sp.prompt_ready


def test_heavy_components_become_ready_only_after_both_initialize(monkeypatch) -> None:
    retriever_obj = object()
    reranker_obj = object()

    monkeypatch.setattr(controller_module, "Retriever", lambda **kwargs: retriever_obj)
    monkeypatch.setattr(controller_module, "Reranker", lambda: reranker_obj)

    ctrl = object.__new__(AppController)
    ctrl.retriever = None
    ctrl.reranker = None
    ctrl.heavy_initialization_error = ""
    ctrl.doc_root = Path("/tmp/doc")
    ctrl.chroma_root = Path("/tmp/chroma")
    ctrl.runtime_config = {}

    assert ctrl.heavy_components_ready is False
    ctrl.initialize_heavy_components()

    assert ctrl.heavy_components_ready is True
    assert ctrl.retriever is retriever_obj
    assert ctrl.reranker is reranker_obj
    assert ctrl.heavy_initialization_error == ""


def test_heavy_initialization_failure_leaves_both_components_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(controller_module, "Retriever", lambda **kwargs: object())

    def fail_reranker():
        raise RuntimeError("synthetic init failure")

    monkeypatch.setattr(controller_module, "Reranker", fail_reranker)

    ctrl = object.__new__(AppController)
    ctrl.retriever = None
    ctrl.reranker = None
    ctrl.heavy_initialization_error = ""
    ctrl.doc_root = Path("/tmp/doc")
    ctrl.chroma_root = Path("/tmp/chroma")
    ctrl.runtime_config = {}

    ctrl.initialize_heavy_components()

    assert ctrl.heavy_components_ready is False
    assert ctrl.retriever is None
    assert ctrl.reranker is None
    assert "RuntimeError: synthetic init failure" in ctrl.heavy_initialization_error
