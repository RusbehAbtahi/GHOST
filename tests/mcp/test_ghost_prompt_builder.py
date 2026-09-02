"""Tests for the central internal GHOST prompt builder."""

from __future__ import annotations

from typing import Any

from ragstream.mcp.ghost_prompt_builder import (
    GhostPromptBuilder,
    STATUS_CLARIFICATION_REQUIRED,
    STATUS_COMPLETE,
    STATUS_SELECTION_REQUIRED,
)
from ragstream.mcp.ghost_prompt_settings import DEFAULT_PROMPT_SETTINGS
from ragstream.mcp.prompt_context_adapters import DocumentContextAdapter
from ragstream.orchestration.agent_factory import AgentFactory
from ragstream.orchestration.super_prompt import A3ChunkStatus, SuperPrompt
from ragstream.retrieval.chunk import Chunk


class Settings:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values

    def effective(
        self,
        _owner_sub: str,
        overrides=None,
    ) -> dict[str, Any]:
        result = dict(self.values)
        if overrides:
            result.update(overrides)
        return result


class Unused:
    def apply(self, *_args, **_kwargs):
        raise AssertionError("adapter must not be called")


def configured(**updates: Any) -> dict[str, Any]:
    result = dict(DEFAULT_PROMPT_SETTINGS)
    result.update(updates)
    return result


def test_cleanup_agent_json_loads_through_neutral_agent_factory() -> None:
    agent = AgentFactory().get_agent("prompt_input_cleanup", "001")

    messages, response_format = agent.compose(
        input_payload={"input_text": "helo"}
    )

    assert agent.agent_name == "prompt_input_cleanup"
    assert messages[0]["role"] == "system"
    assert any("helo" in message["content"] for message in messages)
    assert response_format == {"type": "json_object"}


def test_builder_with_enrichment_off_keeps_raw_task_text() -> None:
    text = "dont correct THIS path /A/B"
    builder = GhostPromptBuilder(
        settings=Settings(configured(prompt_shaping=False)),
        prompt_runner=Unused(),  # type: ignore[arg-type]
        document_adapter=Unused(),  # type: ignore[arg-type]
        memory_adapter=Unused(),  # type: ignore[arg-type]
        general_skill_adapter=Unused(),  # type: ignore[arg-type]
        agent_factory=object(),  # type: ignore[arg-type]
        llm_client=object(),  # type: ignore[arg-type]
        runtime_config={},
    )

    result = builder.build(owner_sub="owner", prompt_text=text)

    assert result["status"] == STATUS_COMPLETE
    assert text in result["prompt"]
    assert result["receipt"]["sources_used"] == []
    assert result["receipt"]["cleanup_changed"] is False


def test_cleanup_ambiguity_stops_before_shaping_and_retrieval() -> None:
    class Agent:
        model = "model"
        temperature = 0.0
        max_tokens = 100

        def compose(self, input_payload):
            assert input_payload == {"input_text": "unclear"}
            return ([{"role": "user", "content": "unclear"}], {})

        def parse(self, _raw):
            return {
                "status": STATUS_CLARIFICATION_REQUIRED,
                "cleaned_text": "",
                "clarification_question": "Which project did you mean?",
            }

    class Factory:
        def get_agent(self, agent_id, version):
            assert (agent_id, version) == ("prompt_input_cleanup", "001")
            return Agent()

    class Llm:
        def chat(self, **_kwargs):
            return "{}"

    builder = GhostPromptBuilder(
        settings=Settings(
            configured(
                input_cleanup=True,
                prompt_shaping=True,
                document_retrieval=True,
            )
        ),
        prompt_runner=Unused(),  # type: ignore[arg-type]
        document_adapter=Unused(),  # type: ignore[arg-type]
        memory_adapter=Unused(),  # type: ignore[arg-type]
        general_skill_adapter=Unused(),  # type: ignore[arg-type]
        agent_factory=Factory(),  # type: ignore[arg-type]
        llm_client=Llm(),  # type: ignore[arg-type]
        runtime_config={},
    )

    result = builder.build(
        owner_sub="owner",
        prompt_text="unclear",
        project_name="Project",
    )

    assert result["status"] == STATUS_CLARIFICATION_REQUIRED
    assert result["prompt"] == ""
    assert result["clarification_question"] == "Which project did you mean?"


def test_general_skill_search_returns_candidates_before_other_retrievals() -> None:
    class Skills:
        def apply(self, *_args, **_kwargs):
            return {
                "workflow_state": STATUS_SELECTION_REQUIRED,
                "candidates": [{"skill_id": "skill-1"}],
                "selected_skill_ids": [],
            }

    builder = GhostPromptBuilder(
        settings=Settings(
            configured(
                prompt_shaping=False,
                document_retrieval=True,
                general_skill_retrieval=True,
            )
        ),
        prompt_runner=Unused(),  # type: ignore[arg-type]
        document_adapter=Unused(),  # type: ignore[arg-type]
        memory_adapter=Unused(),  # type: ignore[arg-type]
        general_skill_adapter=Skills(),  # type: ignore[arg-type]
        agent_factory=object(),  # type: ignore[arg-type]
        llm_client=object(),  # type: ignore[arg-type]
        runtime_config={},
    )

    result = builder.build(
        owner_sub="owner",
        prompt_text="Do the task",
        project_name="Project",
    )

    assert result["status"] == STATUS_SELECTION_REQUIRED
    assert result["general_skill_candidates"] == [
        {"skill_id": "skill-1"}
    ]


def test_builder_composes_selected_skills_document_and_memory_context() -> None:
    calls: list[tuple[Any, ...]] = []

    class Runner:
        def run_superprompt(self, prompt_text: str) -> SuperPrompt:
            calls.append(("shape", prompt_text))
            super_prompt = SuperPrompt(stage="a2")
            super_prompt.body["task"] = prompt_text
            super_prompt.effective_retrieval_query_text = prompt_text
            return super_prompt

    class Skills:
        def apply(
            self,
            super_prompt,
            *,
            selected_skill_ids,
            **_kwargs,
        ):
            calls.append(("skills", list(selected_skill_ids)))
            super_prompt.Attachments_MD = (
                "## General Skill Instructions\nSkill body"
            )
            return {
                "workflow_state": STATUS_COMPLETE,
                "candidates": [],
                "selected_skill_ids": list(selected_skill_ids),
            }

    class Documents:
        def apply(self, super_prompt, *, project_name, **_kwargs):
            calls.append(("document", project_name))
            super_prompt.S_CTX_MD = "Condensed document context"
            return {
                "source": "document",
                "retrieved_chunk_count": 2,
                "a3_accepted_chunk_count": 1,
                "a3_rejected_chunk_count": 1,
                "s_ctx_md_produced": True,
                "stages_completed": [
                    "dense_document_retrieval",
                    "a3_document_gate",
                    "a4_document_condenser",
                ],
            }

    class Memory:
        def apply(
            self,
            super_prompt,
            *,
            ragmem_path,
            recency_enabled,
            **_kwargs,
        ):
            calls.append(("memory", ragmem_path, recency_enabled))
            super_prompt.memory_context_text = "Retrieved memory"
            return {
                "source": "memory",
                "file_id": "memory-file",
                "memory_title": "Memory",
                "recency_enabled": recency_enabled,
            }

    builder = GhostPromptBuilder(
        settings=Settings(
            configured(
                prompt_shaping=True,
                document_retrieval=True,
                memory_retrieval=True,
                general_skill_retrieval=True,
                memory_recency_enabled=False,
            )
        ),
        prompt_runner=Runner(),  # type: ignore[arg-type]
        document_adapter=Documents(),  # type: ignore[arg-type]
        memory_adapter=Memory(),  # type: ignore[arg-type]
        general_skill_adapter=Skills(),  # type: ignore[arg-type]
        agent_factory=object(),  # type: ignore[arg-type]
        llm_client=object(),  # type: ignore[arg-type]
        runtime_config={},
    )

    result = builder.build(
        owner_sub="owner",
        prompt_text="Task",
        project_name="Project",
        ragmem_path="/memory.ragmem",
        general_skill_ids=["skill-1"],
    )

    assert result["status"] == STATUS_COMPLETE
    assert calls == [
        ("shape", "Task"),
        ("skills", ["skill-1"]),
        ("document", "Project"),
        ("memory", "/memory.ragmem", False),
    ]
    assert "Skill body" in result["prompt"]
    assert "Condensed document context" in result["prompt"]
    assert "Retrieved memory" in result["prompt"]
    assert result["receipt"]["stages_completed"] == [
        "prompt_shaping",
        "general_skill_retrieval",
        "dense_document_retrieval",
        "a3_document_gate",
        "a4_document_condenser",
        "memory_retrieval",
        "prompt_composition",
    ]
    assert result["receipt"]["document_pipeline"][
        "s_ctx_md_produced"
    ] is True
    assert result["receipt"]["sources_used"] == [
        "general_skills",
        "document",
        "memory",
    ]
    assert result["receipt"]["ragmem_file_id"] == "memory-file"
    assert result["receipt"]["selected_general_skill_ids"] == ["skill-1"]



def test_builder_runs_real_a3_a4_and_composes_s_ctx_md(tmp_path) -> None:
    (tmp_path / "data" / "doc_raw" / "Project").mkdir(parents=True)
    (tmp_path / "data" / "chroma_db" / "Project").mkdir(parents=True)
    calls: list[str] = []

    class DenseRetriever:
        def run(
            self,
            super_prompt,
            project_name,
            top_k,
            *,
            use_retrieval_splade,
        ):
            assert project_name == "Project"
            assert top_k == 30
            assert use_retrieval_splade is False
            calls.append("dense_document_retrieval")
            super_prompt.base_context_chunks = [
                Chunk(
                    id="chunk-1",
                    source="source.md",
                    snippet="The production pipeline uses dense retrieval.",
                    span=(0, 45),
                )
            ]
            super_prompt.views_by_stage["retrieval"] = [
                ("chunk-1", 0.91, A3ChunkStatus.SELECTED)
            ]
            super_prompt.final_selection_ids = ["chunk-1"]
            return super_prompt

    class DeterministicLlm:
        def __init__(self) -> None:
            self.a4_outputs = [
                {
                    "class_definitions": [
                        {
                            "class_id": "ID1",
                            "class_phrase": "Architecture",
                            "class_context_text": "Architecture evidence",
                        }
                    ]
                },
                {
                    "item_decisions": [
                        {
                            "chunk_id": "1",
                            "class_id": "Architecture",
                        }
                    ]
                },
                {"s_ctx_md": "Condensed document context."},
            ]

        def responses(self, *, return_metadata, **_kwargs):
            if not return_metadata:
                calls.append("a3_document_gate")
                return {
                    "item_decisions": [
                        {
                            "chunk_id": "1",
                            "usefulness_label": "useful",
                        }
                    ]
                }
            if len(self.a4_outputs) == 3:
                calls.append("a4_document_condenser")
            output = self.a4_outputs.pop(0)
            import json

            return {
                "content": json.dumps(output),
                "usage": {},
                "model_name": "deterministic",
                "status": "completed",
            }

    llm = DeterministicLlm()
    document_adapter = DocumentContextAdapter(
        repo_root=tmp_path,
        retriever_factory=lambda **_kwargs: DenseRetriever(),
        agent_factory=AgentFactory(),
        llm_client=llm,
    )
    builder = GhostPromptBuilder(
        settings=Settings(
            configured(
                prompt_shaping=False,
                document_retrieval=True,
            )
        ),
        prompt_runner=Unused(),  # type: ignore[arg-type]
        document_adapter=document_adapter,
        memory_adapter=Unused(),  # type: ignore[arg-type]
        general_skill_adapter=Unused(),  # type: ignore[arg-type]
        agent_factory=AgentFactory(),
        llm_client=llm,  # type: ignore[arg-type]
        runtime_config={"document_retrieval": {}},
    )

    result = builder.build(
        owner_sub="owner",
        prompt_text="Explain the production pipeline",
        project_name="Project",
    )

    assert result["status"] == STATUS_COMPLETE
    assert calls == [
        "dense_document_retrieval",
        "a3_document_gate",
        "a4_document_condenser",
    ]
    assert "Condensed document context." in result["prompt"]
    assert result["receipt"]["stages_completed"] == [
        "base_prompt",
        "dense_document_retrieval",
        "a3_document_gate",
        "a4_document_condenser",
        "prompt_composition",
    ]
    document_receipt = result["receipt"]["document_pipeline"]
    assert document_receipt["retrieved_chunk_count"] == 1
    assert document_receipt["a3_accepted_chunk_count"] == 1
    assert document_receipt["a3_rejected_chunk_count"] == 0
    assert document_receipt["s_ctx_md_produced"] is True


def test_builder_uses_token_defaults_and_request_local_overrides() -> None:
    calls: list[tuple[Any, ...]] = []

    class Documents:
        def apply(
            self,
            _super_prompt,
            *,
            context_tokens,
            max_output_tokens,
            **_kwargs,
        ):
            calls.append(("document", context_tokens, max_output_tokens))
            return {"source": "document", "stages_completed": []}

    class Memory:
        def apply(
            self,
            _super_prompt,
            *,
            context_tokens,
            max_output_tokens,
            **_kwargs,
        ):
            calls.append(("memory", context_tokens, max_output_tokens))
            return {
                "source": "memory",
                "file_id": "memory-file",
                "vectors_created": 0,
            }

    builder = GhostPromptBuilder(
        settings=Settings(
            configured(
                prompt_shaping=False,
                document_retrieval=True,
                memory_retrieval=True,
            )
        ),
        prompt_runner=Unused(),  # type: ignore[arg-type]
        document_adapter=Documents(),  # type: ignore[arg-type]
        memory_adapter=Memory(),  # type: ignore[arg-type]
        general_skill_adapter=Unused(),  # type: ignore[arg-type]
        agent_factory=object(),  # type: ignore[arg-type]
        llm_client=object(),  # type: ignore[arg-type]
        runtime_config={},
    )

    first = builder.build(
        owner_sub="owner",
        prompt_text="Task",
        project_name="Project",
        ragmem_path="/memory.ragmem",
    )
    second = builder.build(
        owner_sub="owner",
        prompt_text="Task",
        project_name="Project",
        ragmem_path="/memory.ragmem",
        document_context_tokens=900,
        document_max_output_tokens=3600,
        memory_context_tokens=800,
        memory_max_output_tokens=3200,
    )

    assert first["status"] == STATUS_COMPLETE
    assert second["status"] == STATUS_COMPLETE
    assert calls == [
        ("document", 1200, 4000),
        ("memory", 1200, 3500),
        ("document", 900, 3600),
        ("memory", 800, 3200),
    ]


def test_unimplemented_knowledge_retrieval_is_visible_and_non_blocking() -> None:
    builder = GhostPromptBuilder(
        settings=Settings(
            configured(
                prompt_shaping=False,
                knowledge_retrieval=True,
            )
        ),
        prompt_runner=Unused(),  # type: ignore[arg-type]
        document_adapter=Unused(),  # type: ignore[arg-type]
        memory_adapter=Unused(),  # type: ignore[arg-type]
        general_skill_adapter=Unused(),  # type: ignore[arg-type]
        agent_factory=object(),  # type: ignore[arg-type]
        llm_client=object(),  # type: ignore[arg-type]
        runtime_config={},
    )

    result = builder.build(owner_sub="owner", prompt_text="Task")

    assert result["status"] == STATUS_COMPLETE
    assert (
        result["receipt"]["effective_flags"]["knowledge_retrieval"]
        is False
    )
    assert result["receipt"]["warnings"] == [
        "knowledge_retrieval is not implemented and was skipped"
    ]


def test_skill_selection_continuation_preserves_saved_sources() -> None:
    calls: list[tuple[Any, ...]] = []

    class Skills:
        def apply(
            self,
            super_prompt,
            *,
            query,
            selected_skill_ids,
            **_kwargs,
        ):
            calls.append((
                "skills",
                query,
                None if selected_skill_ids is None else list(selected_skill_ids),
            ))
            if selected_skill_ids is None:
                return {
                    "workflow_state": STATUS_SELECTION_REQUIRED,
                    "candidates": [{"skill_id": "skill-1"}],
                    "selected_skill_ids": [],
                }
            super_prompt.Attachments_MD = "Selected Skill"
            return {
                "workflow_state": STATUS_COMPLETE,
                "candidates": [],
                "selected_skill_ids": list(selected_skill_ids),
            }

    class Documents:
        def apply(self, _super_prompt, *, project_name, **_kwargs):
            calls.append(("document", project_name))
            return {"source": "document"}

    class Memory:
        def apply(
            self,
            _super_prompt,
            *,
            ragmem_path,
            recency_enabled,
            **_kwargs,
        ):
            calls.append(("memory", ragmem_path, recency_enabled))
            return {
                "source": "memory",
                "file_id": "memory-file",
                "memory_title": "Memory",
                "recency_enabled": recency_enabled,
                "vectors_created": 0,
            }

    builder = GhostPromptBuilder(
        settings=Settings(
            configured(
                prompt_shaping=False,
                document_retrieval=True,
                memory_retrieval=True,
                general_skill_retrieval=True,
                memory_recency_enabled=False,
            )
        ),
        prompt_runner=Unused(),  # type: ignore[arg-type]
        document_adapter=Documents(),  # type: ignore[arg-type]
        memory_adapter=Memory(),  # type: ignore[arg-type]
        general_skill_adapter=Skills(),  # type: ignore[arg-type]
        agent_factory=object(),  # type: ignore[arg-type]
        llm_client=object(),  # type: ignore[arg-type]
        runtime_config={},
    )

    first = builder.build(
        owner_sub="owner",
        prompt_text="Task",
        project_name="Project",
        ragmem_path="/memory.ragmem",
        general_skill_query="Exact query",
    )
    build_id = first["receipt"]["build_id"]

    second = builder.build(
        owner_sub="owner",
        build_id=build_id,
        general_skill_ids=["skill-1"],
    )

    assert first["status"] == STATUS_SELECTION_REQUIRED
    assert second["status"] == STATUS_COMPLETE
    assert calls == [
        ("skills", "Exact query", None),
        ("skills", "Exact query", ["skill-1"]),
        ("document", "Project"),
        ("memory", "/memory.ragmem", False),
    ]
