# ragstream/memory/memory_merge_synthesizer.py
# -*- coding: utf-8 -*-
"""
MemoryMergeSynthesizer
======================

Runtime-only Memory Context synthesizer.

Purpose:
- receive compressed episodic Q/A candidates
- receive semantic memory chunks
- receive effective_retrieval_query_text
- receive ActiveRetrievalBrief as anti-duplication reference
- call one LLM synthesizer agent
- produce one compact query-relevant Memory Context

Important:
- This does not modify durable MemoryRecord truth.
- This does not write .ragmem, .ragmeta.json, SQLite, or vectors.
- The synthesized Memory Context is query-dependent runtime data.
"""

from __future__ import annotations

import json

from pathlib import Path
from typing import Any

from ragstream.orchestration.agent_factory import AgentFactory
from ragstream.orchestration.agent_prompt import AgentPrompt
from ragstream.orchestration.llm_client import LLMClient
from ragstream.textforge.RagLog import LogDeveloper as _logger_dev

DEV_LOG_ENABLED = False

def logger_dev(*args, **kwargs):
    if DEV_LOG_ENABLED:
        return _logger_dev(*args, **kwargs)
    return None

JsonDict = dict[str, Any]


class MemoryMergeSynthesizer:
    def __init__(
        self,
        *,
        runtime_config: JsonDict | None = None,
        agent_factory: AgentFactory | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.runtime_config = runtime_config if isinstance(runtime_config, dict) else self._load_runtime_config()

        cfg = self.runtime_config.get("memory_merge_synthesizer", {}) or {}

        self.enabled = bool(cfg.get("enabled", True))
        self.agent_id = str(cfg.get("agent_id", "memory_synthesizer"))
        self.agent_version = str(cfg.get("agent_version", "memory_synthesizer_001"))
        self.target_context_tokens = int(cfg.get("target_context_tokens", 700))
        self.max_output_tokens = int(cfg.get("max_output_tokens", 0) or 0)
        self.max_episodic_records = int(cfg.get("max_episodic_records", 3))
        self.max_semantic_chunks = int(cfg.get("max_semantic_chunks", 5))
        self.prompt_cache_key = str(cfg.get("prompt_cache_key", "memory_synthesizer"))

        self.agent_factory = agent_factory or AgentFactory()
        self.llm_client = llm_client or LLMClient()

    def synthesize(
        self,
        *,
        effective_retrieval_query_text: str,
        active_retrieval_brief_title: str,
        active_retrieval_brief: str,
        episodic_candidates: list[dict[str, Any]],
        semantic_memory_chunks: list[dict[str, Any]],
    ) -> JsonDict:
        if not self.enabled:
            return self._skipped_result(
                reason="disabled",
                effective_retrieval_query_text=effective_retrieval_query_text,
                episodic_candidates=episodic_candidates,
                semantic_memory_chunks=semantic_memory_chunks,
            )

        selected_episodes = list(episodic_candidates or [])[: self.max_episodic_records]
        selected_chunks = list(semantic_memory_chunks or [])[: self.max_semantic_chunks]

        evidence_text = self._build_memory_evidence_text(
            episodic_candidates=selected_episodes,
            semantic_memory_chunks=selected_chunks,
        )

        if not evidence_text.strip():
            return self._skipped_result(
                reason="no_memory_evidence",
                effective_retrieval_query_text=effective_retrieval_query_text,
                episodic_candidates=episodic_candidates,
                semantic_memory_chunks=semantic_memory_chunks,
            )

        payload = {
            "effective_retrieval_query_text": str(effective_retrieval_query_text or "").strip(),
            "active_retrieval_brief_title": str(active_retrieval_brief_title or "").strip(),
            "active_retrieval_brief": str(active_retrieval_brief or "").strip(),
            "memory_evidence": evidence_text,
            "required_output": self._build_required_output_text(),
        }

        try:
            result = self._run_agent_call(
                call_name="Memory Merge Synthesizer",
                input_payload=payload,
            )

            memory_context = str(result.get("memory_context", "") or "").strip()

            diagnostics = {
                "llm_skipped": False,
                "reason": "synthesized",
                "target_context_tokens": self.target_context_tokens,
                "episodic_candidate_count": len(selected_episodes),
                "semantic_memory_chunk_count": len(selected_chunks),
                "memory_context_chars": len(memory_context),
                "usage": result.get("_usage", {}),
                "model_name": result.get("_model_name", ""),
                "status": result.get("_status", ""),
                "incomplete_reason": result.get("_incomplete_reason", ""),
            }

            logger_dev(
                "MEMORY MERGE SYNTHESIZER RESULT\n"
                + json.dumps(
                    {
                        "diagnostics": diagnostics,
                        "memory_context": memory_context,
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                "DEBUG",
                "CONFIDENTIAL",
            )

            return {
                "memory_context": memory_context,
                "memory_synthesis_diagnostics": diagnostics,
                "memory_synthesis_llm_skipped": False,
            }

        except Exception as e:
            diagnostics = {
                "llm_skipped": True,
                "reason": "synthesis_failed",
                "error": str(e),
                "target_context_tokens": self.target_context_tokens,
                "episodic_candidate_count": len(selected_episodes),
                "semantic_memory_chunk_count": len(selected_chunks),
            }

            logger_dev(
                "MEMORY MERGE SYNTHESIZER FAILED\n"
                + json.dumps(diagnostics, ensure_ascii=False, indent=2, default=str),
                "ERROR",
                "CONFIDENTIAL",
            )

            return {
                "memory_context": "",
                "memory_synthesis_diagnostics": diagnostics,
                "memory_synthesis_llm_skipped": True,
            }

    def _run_agent_call(
        self,
        *,
        call_name: str,
        input_payload: JsonDict,
    ) -> JsonDict:
        agent_prompt = self.agent_factory.get_agent(
            self.agent_id,
            self.agent_version,
        )

        messages, response_format = agent_prompt.compose(input_payload=input_payload)

        response = self.llm_client.responses(
            messages=messages,
            model_name=agent_prompt.model_name,
            max_output_tokens=(
                self.max_output_tokens
                if self.max_output_tokens > 0
                else agent_prompt.max_output_tokens
            ),
            reasoning_effort="minimal",
            return_metadata=True,
            prompt_cache_key=self.prompt_cache_key,
        )

        raw_content = str(response.get("content", "") or "")
        parsed = agent_prompt.parse(raw_content)

        parsed["_usage"] = response.get("usage", {}) or {}
        parsed["_model_name"] = response.get("model_name", "")
        parsed["_status"] = response.get("status", "")
        parsed["_incomplete_reason"] = response.get("incomplete_reason", "")

        return parsed

    def _build_memory_evidence_text(
        self,
        *,
        episodic_candidates: list[dict[str, Any]],
        semantic_memory_chunks: list[dict[str, Any]],
    ) -> str:
        lines: list[str] = []

        if episodic_candidates:
            lines.append("## Reduced Episodic Memory Episodes")
            lines.append("")

            for idx, candidate in enumerate(episodic_candidates, start=1):
                record_id = str(candidate.get("record_id", "") or "").strip()
                tag = str(candidate.get("tag", "") or "").strip()
                source = str(candidate.get("episodic_source", "") or "").strip()
                score = candidate.get("final_parent_score", candidate.get("score", ""))

                question = str(
                    candidate.get("compressed_input_text", candidate.get("input_text", "")) or ""
                ).strip()
                answer = str(
                    candidate.get("compressed_output_text", candidate.get("output_text", "")) or ""
                ).strip()

                lines.append(f"### Episode {idx}")
                lines.append(f"record_id: {record_id}")
                if tag:
                    lines.append(f"tag: {tag}")
                if source:
                    lines.append(f"source: {source}")
                if score != "":
                    lines.append(f"score: {score}")
                lines.append("")

                if question:
                    lines.append("QUESTION:")
                    lines.append(question)
                    lines.append("")

                if answer:
                    lines.append("ANSWER:")
                    lines.append(answer)
                    lines.append("")

        if semantic_memory_chunks:
            lines.append("## Semantic Memory Chunks")
            lines.append("")

            for idx, chunk in enumerate(semantic_memory_chunks, start=1):
                record_id = str(chunk.get("record_id", "") or "").strip()
                vector_id = str(chunk.get("vector_id", chunk.get("id", "")) or "").strip()
                role = str(chunk.get("role", "") or "").strip()
                score = chunk.get("score", "")
                text = str(chunk.get("document", chunk.get("text", "")) or "").strip()

                lines.append(f"### Semantic Chunk {idx}")
                if vector_id:
                    lines.append(f"vector_id: {vector_id}")
                if record_id:
                    lines.append(f"record_id: {record_id}")
                if role:
                    lines.append(f"role: {role}")
                if score != "":
                    lines.append(f"score: {score}")
                lines.append("")

                if text:
                    lines.append("TEXT:")
                    lines.append(text)
                    lines.append("")

        return "\n".join(lines).strip()

    def _build_required_output_text(self) -> str:
        return (
            "{\n"
            '  "memory_context": "query-relevant synthesized Memory Context"\n'
            "}\n\n"
            f"The visible memory_context content MUST NOT exceed "
            f"{self.target_context_tokens} tokens. "
            f"{self.target_context_tokens} tokens is a strict maximum, "
            "not a target or approximation."
        )

    def _skipped_result(
        self,
        *,
        reason: str,
        effective_retrieval_query_text: str,
        episodic_candidates: list[dict[str, Any]],
        semantic_memory_chunks: list[dict[str, Any]],
    ) -> JsonDict:
        diagnostics = {
            "llm_skipped": True,
            "reason": reason,
            "target_context_tokens": self.target_context_tokens,
            "effective_retrieval_query_chars": len(str(effective_retrieval_query_text or "")),
            "episodic_candidate_count": len(episodic_candidates or []),
            "semantic_memory_chunk_count": len(semantic_memory_chunks or []),
        }

        logger_dev(
            "MEMORY MERGE SYNTHESIZER SKIPPED\n"
            + json.dumps(diagnostics, ensure_ascii=False, indent=2, default=str),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return {
            "memory_context": "",
            "memory_synthesis_diagnostics": diagnostics,
            "memory_synthesis_llm_skipped": True,
        }

    @staticmethod
    def _load_runtime_config() -> JsonDict:
        root = Path(__file__).resolve().parents[2]
        path = root / "config" / "runtime_config.json"

        if not path.exists():
            return {}

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}