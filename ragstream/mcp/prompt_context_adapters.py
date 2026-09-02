"""Thin adapters from the MCP prompt builder to existing GHOST subsystems."""

from __future__ import annotations

import copy
import json

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ragstream.agents.a3_nli_gate import A3NLIGate
from ragstream.agents.a4_condenser import A4Condenser
from ragstream.mcp.mcp_skill_loader import (
    McpSkillLoaderTool,
    WORKFLOW_COMPLETE,
    WORKFLOW_SELECTION_REQUIRED,
)
from ragstream.mcp.ragmem_resolver import (
    RagMemResolutionError,
    RagMemResolver,
    ResolvedRagMem,
)
from ragstream.memory.mcp_skill_memory_store import GENERAL_SKILL_DOMAIN


DEFAULT_DOCUMENT_CONTEXT_TOKENS = 1200
DEFAULT_DOCUMENT_MAX_OUTPUT_TOKENS = 4000
DEFAULT_MEMORY_CONTEXT_TOKENS = 1200
DEFAULT_MEMORY_MAX_OUTPUT_TOKENS = 3500


class ContextAdapterError(RuntimeError):
    """Raised when an enabled prompt context source cannot be used safely."""


def load_runtime_config(
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Load the existing global runtime defaults without mutating them."""
    root = (
        Path(repo_root)
        if repo_root is not None
        else Path(__file__).resolve().parents[2]
    )
    path = root / "ragstream" / "config" / "runtime_config.json"
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise ContextAdapterError("runtime_config.json is unavailable") from error
    if not isinstance(data, dict):
        raise ContextAdapterError("runtime_config.json must contain an object")
    return data


class DocumentContextAdapter:
    """Run dense retrieval, A3, and A4 for one indexed GHOST project."""

    def __init__(
        self,
        *,
        repo_root: str | Path | None = None,
        retriever_factory: Callable[..., Any] | None = None,
        agent_factory: Any | None = None,
        llm_client: Any | None = None,
    ) -> None:
        self.repo_root = (
            Path(repo_root)
            if repo_root is not None
            else Path(__file__).resolve().parents[2]
        )
        self._retriever_factory = (
            retriever_factory or self._create_retriever
        )
        if agent_factory is None or llm_client is None:
            raise ValueError(
                "DocumentContextAdapter requires agent_factory and llm_client"
            )
        self._a3_gate = A3NLIGate(
            agent_factory=agent_factory,
            llm_client=llm_client,
        )
        self._a4_condenser = A4Condenser(llm_client=llm_client)

    def apply(
        self,
        super_prompt: Any,
        *,
        project_name: str,
        runtime_config: dict[str, Any],
        context_tokens: int = DEFAULT_DOCUMENT_CONTEXT_TOKENS,
        max_output_tokens: int = DEFAULT_DOCUMENT_MAX_OUTPUT_TOKENS,
    ) -> dict[str, Any]:
        """Attach existing project retrieval results to the SuperPrompt."""
        project = self._validate_project_name(project_name)
        data_root = self.repo_root / "data"
        doc_root = data_root / "doc_raw"
        chroma_root = data_root / "chroma_db"

        if not (doc_root / project).is_dir():
            raise ContextAdapterError(
                f"document project is not available: {project}"
            )
        if not (chroma_root / project).exists():
            raise ContextAdapterError(
                f"document project is not indexed: {project}"
            )

        document_cfg = runtime_config.get("document_retrieval", {}) or {}
        top_k = int(
            document_cfg.get("semantic_stage_max_total_chunks", 30) or 30
        )
        retriever = self._retriever_factory(
            doc_root=str(doc_root),
            chroma_root=str(chroma_root),
            runtime_config=runtime_config,
        )
        try:
            result = retriever.run(
                super_prompt,
                project,
                top_k,
                use_retrieval_splade=False,
            )
        except Exception as error:
            raise ContextAdapterError(
                f"dense_document_retrieval failed: {error}"
            ) from error
        if result is not super_prompt:
            raise ContextAdapterError(
                "dense_document_retrieval failed: document Retriever "
                "returned a different SuperPrompt"
            )

        retrieved_count = len(
            super_prompt.views_by_stage.get("retrieval", []) or []
        )
        try:
            result = self._a3_gate.run(super_prompt)
        except Exception as error:
            raise ContextAdapterError(
                f"a3_document_gate failed: {error}"
            ) from error
        if result is not super_prompt:
            raise ContextAdapterError(
                "a3_document_gate failed: A3 returned a different SuperPrompt"
            )

        decisions = dict(
            super_prompt.extras.get("a3_item_decisions", {}) or {}
        )
        useful_count = sum(
            1
            for decision in decisions.values()
            if str(decision.get("usefulness_label", "")).lower() == "useful"
        )
        accepted_count = len(super_prompt.final_selection_ids)
        rejected_count = max(0, retrieved_count - accepted_count)
        try:
            result = self._a4_condenser.run(
                super_prompt,
                effective_output_token_limit=int(context_tokens),
                max_output_tokens=int(max_output_tokens),
            )
        except Exception as error:
            raise ContextAdapterError(
                f"a4_document_condenser failed: {error}"
            ) from error
        if result is not super_prompt:
            raise ContextAdapterError(
                "a4_document_condenser failed: A4 returned a different "
                "SuperPrompt"
            )

        return {
            "source": "document",
            "project_name": project,
            "selected_chunk_ids": list(super_prompt.final_selection_ids),
            "retrieved_chunk_count": retrieved_count,
            "a3_useful_decision_count": useful_count,
            "a3_accepted_chunk_count": accepted_count,
            "a3_rejected_chunk_count": rejected_count,
            "s_ctx_md_produced": bool(str(super_prompt.S_CTX_MD or "").strip()),
            "context_token_limit": int(context_tokens),
            "max_output_tokens": int(max_output_tokens),
            "stages_completed": [
                "dense_document_retrieval",
                "a3_document_gate",
                "a4_document_condenser",
            ],
        }

    @staticmethod
    def _validate_project_name(project_name: str) -> str:
        project = str(project_name or "").strip()
        if not project:
            raise ContextAdapterError(
                "document_retrieval requires a project name"
            )
        if (
            "/" in project
            or "\\" in project
            or project in {".", ".."}
            or ".." in project
        ):
            raise ContextAdapterError("project name is invalid")
        return project

    @staticmethod
    def _create_retriever(**kwargs: Any) -> Any:
        from ragstream.retrieval.retriever import Retriever

        return Retriever(**kwargs)

class MemoryContextAdapter:
    """Run the existing full GHOST MemoryRetriever for one local RagMem."""

    def __init__(
        self,
        *,
        ragmem_resolver: RagMemResolver | None = None,
        memory_retriever_factory: (
            Callable[[ResolvedRagMem, dict[str, Any]], Any] | None
        ) = None,
    ) -> None:
        self._ragmem_resolver = ragmem_resolver or RagMemResolver()
        self._memory_retriever_factory = (
            memory_retriever_factory or self._create_memory_retriever
        )

    def apply(
        self,
        super_prompt: Any,
        *,
        owner_sub: str,
        ragmem_path: str,
        runtime_config: dict[str, Any],
        recency_enabled: bool,
        context_tokens: int = DEFAULT_MEMORY_CONTEXT_TOKENS,
        max_output_tokens: int = DEFAULT_MEMORY_MAX_OUTPUT_TOKENS,
    ) -> dict[str, Any]:
        """Attach memory context using a request-local recency configuration."""
        try:
            resolved = self._ragmem_resolver.resolve(
                ragmem_path=ragmem_path,
                owner_sub=owner_sub,
            )
        except RagMemResolutionError as error:
            raise ContextAdapterError(str(error)) from error
        request_config = self.with_recency(
            runtime_config,
            enabled=recency_enabled,
            context_tokens=context_tokens,
            max_output_tokens=max_output_tokens,
        )
        retriever = self._memory_retriever_factory(
            resolved,
            request_config,
        )
        result = retriever.run(super_prompt)
        if result is not super_prompt:
            raise ContextAdapterError(
                "MemoryRetriever returned a different SuperPrompt"
            )

        manager = getattr(retriever, "memory_manager", None)
        pack = getattr(super_prompt, "memory_context_pack", None)
        if pack is None:
            raise ContextAdapterError(
                "memory_retrieval failed: MemoryRetriever produced no "
                "MemoryContextPack"
            )
        returned_counts = dict(pack.counts())
        selection_diagnostics = dict(pack.selection_diagnostics or {})
        synthesis_diagnostics = dict(
            pack.memory_synthesis_diagnostics or {}
        )
        raw_hits = int(
            selection_diagnostics.get("raw_vector_hit_count", 0) or 0
        )
        merge_episodes = int(
            synthesis_diagnostics.get("episodic_candidate_count", 0) or 0
        )
        merge_chunks = int(
            synthesis_diagnostics.get("semantic_memory_chunk_count", 0) or 0
        )
        omitted_counts = {
            "vector_hits_not_returned_as_semantic_chunks": max(
                0,
                raw_hits - returned_counts["semantic_memory_chunks"],
            ),
            "returned_episodes_not_used_by_memory_merge": max(
                0,
                returned_counts["episodic_candidates"] - merge_episodes,
            ),
            "returned_chunks_not_used_by_memory_merge": max(
                0,
                returned_counts["semantic_memory_chunks"] - merge_chunks,
            ),
        }
        return {
            "source": "memory",
            "retrieval_backend": "MemoryRetriever",
            "condenser_backend": "MemoryMergeSynthesizer",
            "file_id": str(getattr(manager, "file_id", "") or ""),
            "memory_title": str(getattr(manager, "title", "") or ""),
            "recency_enabled": recency_enabled,
            "context_token_limit": int(context_tokens),
            "max_output_tokens": int(max_output_tokens),
            "vectors_created": resolved.vectors_created,
            "returned_counts": returned_counts,
            "omitted_counts": omitted_counts,
            "omission_reason": (
                "existing GHOST MemoryRetriever scoring, configured "
                "candidate limits, and MemoryMerge token selection"
            ),
            "selection_diagnostics": selection_diagnostics,
            "memory_synthesis_diagnostics": synthesis_diagnostics,
            "token_budget_report": dict(pack.token_budget_report or {}),
            "memory_context_produced": bool(
                str(pack.synthesized_memory_context or "").strip()
            ),
        }

    @staticmethod
    def with_recency(
        runtime_config: dict[str, Any],
        *,
        enabled: bool,
        context_tokens: int = DEFAULT_MEMORY_CONTEXT_TOKENS,
        max_output_tokens: int = DEFAULT_MEMORY_MAX_OUTPUT_TOKENS,
    ) -> dict[str, Any]:
        """Override both existing recency switches in a deep request copy."""
        request_config = copy.deepcopy(runtime_config)
        memory_cfg = request_config.setdefault("memory_retrieval", {})
        episodic_cfg = memory_cfg.setdefault("episodic_memory", {})
        semantic_cfg = memory_cfg.setdefault("semantic_memory_chunks", {})
        episodic_cfg["recency_enabled"] = bool(enabled)
        semantic_cfg["recency_enabled"] = bool(enabled)
        merge_cfg = request_config.setdefault("memory_merge_synthesizer", {})
        merge_cfg["target_context_tokens"] = int(context_tokens)
        merge_cfg["max_output_tokens"] = int(max_output_tokens)
        return request_config

    @staticmethod
    def _create_memory_retriever(
        resolved: ResolvedRagMem,
        runtime_config: dict[str, Any],
    ) -> Any:
        from ragstream.retrieval.retriever_mem import MemoryRetriever

        return MemoryRetriever(
            memory_manager=resolved.memory_manager,
            memory_vector_store=resolved.memory_vector_store,
            sqlite_path=resolved.sqlite_path,
            config=runtime_config,
        )


class GeneralSkillContextAdapter:
    """Use the existing two-stage Skill loader in the GENERAL_SKILL domain."""

    def __init__(
        self,
        loader: McpSkillLoaderTool | None = None,
    ) -> None:
        self.loader = loader or McpSkillLoaderTool()

    def apply(
        self,
        super_prompt: Any,
        *,
        owner_sub: str,
        query: str,
        selected_skill_ids: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Search candidates or load exact Skills and attach their instructions."""
        if selected_skill_ids is None:
            result = self.loader.call_sanitized(
                owner_sub,
                {
                    "skill_domain": GENERAL_SKILL_DOMAIN,
                    "query": str(query or "").strip(),
                },
            )
            data = self._structured_result(result)
            return {
                "source": "general_skills",
                "workflow_state": data.get(
                    "workflow_state",
                    WORKFLOW_COMPLETE,
                ),
                "candidates": list(data.get("candidates", []) or []),
                "selected_skill_ids": [],
            }

        skill_ids = [
            str(skill_id).strip()
            for skill_id in selected_skill_ids
            if str(skill_id).strip()
        ]
        if not skill_ids:
            return {
                "source": "general_skills",
                "workflow_state": WORKFLOW_COMPLETE,
                "candidates": [],
                "selected_skill_ids": [],
            }

        result = self.loader.call_sanitized(
            owner_sub,
            {
                "skill_domain": GENERAL_SKILL_DOMAIN,
                "skill_ids": skill_ids,
            },
        )
        data = self._structured_result(result)
        skills = list(data.get("skills", []) or [])
        self._attach(super_prompt, skills)
        return {
            "source": "general_skills",
            "workflow_state": WORKFLOW_COMPLETE,
            "candidates": [],
            "selected_skill_ids": [
                str(skill.get("skill_id", "") or "")
                for skill in skills
            ],
        }

    @staticmethod
    def _structured_result(result: Any) -> dict[str, Any]:
        if bool(getattr(result, "isError", False)):
            content = getattr(result, "content", []) or []
            message = "General Skill retrieval failed"
            if content and isinstance(content[0], dict):
                message = str(content[0].get("text", message))
            raise ContextAdapterError(message)
        data = getattr(result, "structuredContent", None)
        if not isinstance(data, dict):
            raise ContextAdapterError(
                "General Skill loader returned no structured result"
            )
        return data

    @staticmethod
    def _attach(super_prompt: Any, skills: list[dict[str, Any]]) -> None:
        if not skills:
            return
        lines = [
            "## General Skill Instructions",
            "",
            (
                "Use these as supporting instructions for the current request. "
                "The current user request remains authoritative."
            ),
        ]
        for skill in skills:
            skill_id = str(skill.get("skill_id", "") or "").strip()
            skill_text = str(skill.get("skill_text", "") or "").strip()
            if not skill_id or not skill_text:
                continue
            lines.extend(["", f"### Skill {skill_id}", skill_text])

        block = "\n".join(lines).strip()
        existing = str(getattr(super_prompt, "Attachments_MD", "") or "").strip()
        super_prompt.Attachments_MD = (
            f"{existing}\n\n{block}".strip()
            if existing
            else block
        )

