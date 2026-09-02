"""Tests for thin prompt context adapters."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from ragstream.mcp.mcp_skill_loader import (
    WORKFLOW_COMPLETE,
    WORKFLOW_SELECTION_REQUIRED,
)
from ragstream.mcp.prompt_context_adapters import (
    DocumentContextAdapter,
    GeneralSkillContextAdapter,
    MemoryContextAdapter,
)
from ragstream.memory.mcp_skill_memory_store import GENERAL_SKILL_DOMAIN
from ragstream.memory.memory_merge_synthesizer import (
    MemoryMergeSynthesizer,
)
from ragstream.memory.retrieval.memory_context_pack import MemoryContextPack
from ragstream.orchestration.agent_factory import AgentFactory
from ragstream.orchestration.super_prompt import (
    A3ChunkStatus,
    SuperPrompt,
)
from ragstream.retrieval.chunk import Chunk
from ragstream.retrieval.retriever_mem import MemoryRetriever


def test_document_adapter_runs_dense_then_a3_then_a4(tmp_path) -> None:
    (tmp_path / "data" / "doc_raw" / "Project").mkdir(parents=True)
    (tmp_path / "data" / "chroma_db" / "Project").mkdir(parents=True)
    calls: list[tuple[Any, ...]] = []

    class Retriever:
        def run(
            self,
            super_prompt: SuperPrompt,
            project_name: str,
            top_k: int,
            *,
            use_retrieval_splade: bool,
        ) -> SuperPrompt:
            calls.append(
                (
                    "dense",
                    project_name,
                    top_k,
                    use_retrieval_splade,
                )
            )
            super_prompt.views_by_stage["retrieval"] = [
                ("chunk-1", 1.0, A3ChunkStatus.SELECTED)
            ]
            super_prompt.final_selection_ids = ["chunk-1"]
            return super_prompt

    class A3:
        def run(self, super_prompt: SuperPrompt) -> SuperPrompt:
            calls.append(("a3",))
            super_prompt.extras["a3_item_decisions"] = {
                "chunk-1": {"usefulness_label": "useful"}
            }
            return super_prompt

    class A4:
        def run(
            self,
            super_prompt: SuperPrompt,
            *,
            effective_output_token_limit: int,
            max_output_tokens: int,
        ) -> SuperPrompt:
            calls.append(
                (
                    "a4",
                    effective_output_token_limit,
                    max_output_tokens,
                )
            )
            super_prompt.S_CTX_MD = "Condensed document context"
            return super_prompt

    adapter = DocumentContextAdapter(
        repo_root=tmp_path,
        retriever_factory=lambda **kwargs: (
            calls.append(("factory", kwargs)) or Retriever()
        ),
        agent_factory=object(),
        llm_client=object(),
    )
    adapter._a3_gate = A3()
    adapter._a4_condenser = A4()
    super_prompt = SuperPrompt()
    super_prompt.body["task"] = "Find architecture"

    receipt = adapter.apply(
        super_prompt,
        project_name="Project",
        runtime_config={
            "document_retrieval": {
                "semantic_stage_max_total_chunks": 12,
            }
        },
    )

    assert calls[1:] == [
        ("dense", "Project", 12, False),
        ("a3",),
        ("a4", 1200, 4000),
    ]
    assert receipt["selected_chunk_ids"] == ["chunk-1"]
    assert receipt["retrieved_chunk_count"] == 1
    assert receipt["a3_accepted_chunk_count"] == 1
    assert receipt["a3_rejected_chunk_count"] == 0
    assert receipt["s_ctx_md_produced"] is True
    assert receipt["context_token_limit"] == 1200
    assert receipt["max_output_tokens"] == 4000
    assert receipt["stages_completed"] == [
        "dense_document_retrieval",
        "a3_document_gate",
        "a4_document_condenser",
    ]


def test_a3_discard_all_produces_no_s_ctx_or_raw_fallback(tmp_path) -> None:
    (tmp_path / "data" / "doc_raw" / "Project").mkdir(parents=True)
    (tmp_path / "data" / "chroma_db" / "Project").mkdir(parents=True)
    llm_calls = 0

    class Retriever:
        def run(
            self,
            super_prompt,
            _project_name,
            _top_k,
            *,
            use_retrieval_splade,
        ):
            assert use_retrieval_splade is False
            super_prompt.base_context_chunks = [
                Chunk(
                    id="chunk-1",
                    source="source.md",
                    snippet="Raw document text must not bypass A3.",
                    span=(0, 36),
                )
            ]
            super_prompt.views_by_stage["retrieval"] = [
                ("chunk-1", 0.8, A3ChunkStatus.SELECTED)
            ]
            super_prompt.final_selection_ids = ["chunk-1"]
            return super_prompt

    class DiscardingLlm:
        def responses(self, *, return_metadata, **_kwargs):
            nonlocal llm_calls
            llm_calls += 1
            assert return_metadata is False
            return {
                "item_decisions": [
                    {
                        "chunk_id": "1",
                        "usefulness_label": "discarded",
                    }
                ]
            }

    adapter = DocumentContextAdapter(
        repo_root=tmp_path,
        retriever_factory=lambda **_kwargs: Retriever(),
        agent_factory=AgentFactory(),
        llm_client=DiscardingLlm(),
    )
    super_prompt = SuperPrompt()
    super_prompt.body["task"] = "Find relevant evidence"
    super_prompt.effective_retrieval_query_text = "Find relevant evidence"

    receipt = adapter.apply(
        super_prompt,
        project_name="Project",
        runtime_config={"document_retrieval": {}},
    )

    assert llm_calls == 1
    assert super_prompt.final_selection_ids == []
    assert super_prompt.S_CTX_MD == ""
    assert "Raw document text" not in super_prompt.compose_prompt_ready()
    assert receipt["a3_accepted_chunk_count"] == 0
    assert receipt["a3_rejected_chunk_count"] == 1
    assert receipt["s_ctx_md_produced"] is False

def test_memory_adapter_overrides_both_recency_flags_in_request_copy() -> None:
    captured: dict[str, Any] = {}

    class Resolver:
        def resolve(self, *, ragmem_path: str, owner_sub: str):
            captured["ragmem_path"] = ragmem_path
            captured["owner_sub"] = owner_sub
            return SimpleNamespace(vectors_created=3)

    class Retriever:
        memory_manager = SimpleNamespace(
            file_id="file-1",
            title="Memory",
        )

        def run(self, super_prompt: SuperPrompt) -> SuperPrompt:
            captured["ran"] = True
            pack = MemoryContextPack()
            pack.add_episodic_candidate({"record_id": "episode-1"})
            pack.add_semantic_chunk({"vector_id": "vector-1"})
            pack.set_synthesized_memory_context(
                "Synthesized memory",
                {
                    "reason": "synthesized",
                    "episodic_candidate_count": 1,
                    "semantic_memory_chunk_count": 1,
                },
            )
            pack.set_selection_diagnostics(
                {
                    "raw_vector_hit_count": 3,
                    "parent_score_count": 2,
                }
            )
            pack.set_token_budget_report({"estimated_tokens": 10})
            super_prompt.memory_context_pack = pack
            super_prompt.memory_context_text = pack.synthesized_memory_context
            return super_prompt

    def factory(resolved, runtime_config):
        captured["resolved"] = resolved
        captured["config"] = runtime_config
        return Retriever()

    original = {
        "memory_retrieval": {
            "episodic_memory": {"recency_enabled": True},
            "semantic_memory_chunks": {"recency_enabled": True},
        }
    }
    adapter = MemoryContextAdapter(
        ragmem_resolver=Resolver(),
        memory_retriever_factory=factory,
    )

    receipt = adapter.apply(
        SuperPrompt(),
        owner_sub="owner",
        ragmem_path="memory.ragmem",
        runtime_config=original,
        recency_enabled=False,
    )
    assert captured["ragmem_path"] == "memory.ragmem"
    assert captured["owner_sub"] == "owner"

    memory_cfg = captured["config"]["memory_retrieval"]
    assert memory_cfg["episodic_memory"]["recency_enabled"] is False
    assert (
        memory_cfg["semantic_memory_chunks"]["recency_enabled"]
        is False
    )
    assert original["memory_retrieval"]["episodic_memory"][
        "recency_enabled"
    ] is True
    merge_cfg = captured["config"]["memory_merge_synthesizer"]
    assert merge_cfg["target_context_tokens"] == 1200
    assert merge_cfg["max_output_tokens"] == 3500
    assert "memory_merge_synthesizer" not in original
    assert receipt["source"] == "memory"
    assert receipt["retrieval_backend"] == "MemoryRetriever"
    assert receipt["condenser_backend"] == "MemoryMergeSynthesizer"
    assert receipt["file_id"] == "file-1"
    assert receipt["context_token_limit"] == 1200
    assert receipt["max_output_tokens"] == 3500
    assert receipt["vectors_created"] == 3
    assert receipt["returned_counts"]["episodic_candidates"] == 1
    assert receipt["returned_counts"]["semantic_memory_chunks"] == 1
    assert receipt["omitted_counts"] == {
        "vector_hits_not_returned_as_semantic_chunks": 2,
        "returned_episodes_not_used_by_memory_merge": 0,
        "returned_chunks_not_used_by_memory_merge": 0,
    }
    assert receipt["memory_context_produced"] is True



def test_memory_adapter_factory_uses_production_ghost_backend(tmp_path) -> None:
    sqlite_path = tmp_path / "memory.sqlite3"
    sqlite_path.touch()
    manager = SimpleNamespace(
        memory_root=tmp_path,
        file_id="file-1",
        title="Memory",
    )
    vector_store = object()
    resolved = SimpleNamespace(
        memory_manager=manager,
        memory_vector_store=vector_store,
        sqlite_path=sqlite_path,
    )

    retriever = MemoryContextAdapter._create_memory_retriever(
        resolved,
        {"memory_retrieval": {}},
    )

    assert type(retriever) is MemoryRetriever
    assert retriever.memory_manager is manager
    assert retriever.memory_vector_store is vector_store
    assert isinstance(
        retriever.memory_synthesizer,
        MemoryMergeSynthesizer,
    )

def test_general_skill_adapter_preserves_two_stage_selection() -> None:
    calls: list[dict[str, Any]] = []

    class Result:
        isError = False
        content: list[dict[str, str]] = []

        def __init__(self, data: dict[str, Any]) -> None:
            self.structuredContent = data

    class Loader:
        def call_sanitized(
            self,
            owner_sub: str,
            arguments: dict[str, Any],
        ) -> Result:
            calls.append({"owner_sub": owner_sub, **arguments})
            if "query" in arguments:
                return Result(
                    {
                        "workflow_state": WORKFLOW_SELECTION_REQUIRED,
                        "candidates": [
                            {
                                "skill_id": "skill-1",
                                "skill_title": "Skill",
                                "skill_description": "Description",
                                "cosine_similarity": 0.8,
                            }
                        ],
                    }
                )
            return Result(
                {
                    "workflow_state": WORKFLOW_COMPLETE,
                    "skills": [
                        {
                            "skill_id": "skill-1",
                            "skill_text": "Follow this procedure.",
                        }
                    ],
                }
            )

    adapter = GeneralSkillContextAdapter(
        loader=Loader(),  # type: ignore[arg-type]
    )
    super_prompt = SuperPrompt()

    candidates = adapter.apply(
        super_prompt,
        owner_sub="owner",
        query="task",
    )
    loaded = adapter.apply(
        super_prompt,
        owner_sub="owner",
        query="task",
        selected_skill_ids=["skill-1"],
    )

    assert candidates["workflow_state"] == WORKFLOW_SELECTION_REQUIRED
    assert candidates["candidates"][0]["skill_id"] == "skill-1"
    assert loaded["selected_skill_ids"] == ["skill-1"]
    assert "## General Skill Instructions" in super_prompt.Attachments_MD
    assert "Follow this procedure." in super_prompt.Attachments_MD
    assert all(
        call["skill_domain"] == GENERAL_SKILL_DOMAIN
        for call in calls
    )

