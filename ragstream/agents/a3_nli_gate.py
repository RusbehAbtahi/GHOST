# ragstream/agents/a3_nli_gate.py
# -*- coding: utf-8 -*-
"""
A3 NLI Gate agent.

Job:
- Read the current SuperPrompt after ReRanker, or after Retrieval passthrough.
- Build one combined user prompt block for evaluation.
- Build one evidence chunk block with local ids 1..N.
- Ask AgentFactory for the A3 AgentPrompt configuration.
- Use AgentPrompt.compose(...) to build SYSTEM + USER messages.
- Call LLMClient with those messages, using ONLY model settings coming from JSON.
- Expect a JSON object with:
    - item_decisions[] containing chunk_id / usefulness_label
- Update the same SuperPrompt in place.
- Preserve candidate order in views_by_stage["a3"].
- Rebuild sp.prompt_ready and mark stage='a3'.

A3 scope:
- A3 is a usefulness classifier over already retrieved/reranked chunks.
- A3 is not a prompt-validity gate.
- A3 is not a garbage detector.
- A3 is not a retrieval-stage replacement.
- A3 is not a memory-merge component.

A3 selection rule:
- The LLM classifies every candidate chunk as useful, borderline, or discarded.
- Python keeps useful chunks only.
- Python enforces only a maximum useful count.
- Python does not force a minimum number of useful chunks.
- Borderline chunks are not promoted automatically.
- If no chunk is useful, A4 empty-selection safety handles the next step.

Logging policy:
- PUBLIC: compact stage summary visible in GUI and CLI.
- INTERNAL: compact per-chunk decisions visible in CLI/internal logs, not GUI.
- Full LLM input/output logging is disabled in normal mode.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple, Union
import json
import re
import time

from ragstream.orchestration.super_prompt import SuperPrompt, A3ChunkStatus
from ragstream.orchestration.agent_factory import AgentFactory
from ragstream.orchestration.llm_client import LLMClient
from ragstream.orchestration.superprompt_projector import SuperPromptProjector
from ragstream.textforge.RagLog import LogALL as logger
from ragstream.textforge.RagLog import LogDeveloper as logger_dev


JsonDict = Dict[str, Any]

# Keep full prompt / raw model I/O logging off in normal mode.
# Important: full debug payloads are built only inside an explicit if-block,
# so normal mode does not pay the JSON-dump cost.
A3_FULL_LLM_LOG_ENABLED = False


class A3NLIGate:
    """
    Orchestrates A3 for a single SuperPrompt.

    This class stays thin:
    - It does NOT know JSON file layout (AgentFactory does that).
    - It does NOT know prompt templates (AgentPrompt does that).
    - It only:
        * extracts input from SuperPrompt,
        * asks AgentPrompt to compose messages,
        * calls LLMClient,
        * writes the result back into SuperPrompt.
    """

    def __init__(
        self,
        agent_factory: AgentFactory,
        llm_client: LLMClient,
        *,
        max_candidates: int = 30,
        useful_hard_min: int = 0,
        useful_hard_max: int = 12,
    ) -> None:
        self._factory = agent_factory
        self._llm_client = llm_client
        self._max_candidates = int(max_candidates)

        # Kept only for backward-compatible constructor calls.
        # A3 no longer forces a minimum number of useful chunks.
        self._useful_hard_min = 0

        # A3 now enforces only the maximum useful count.
        self._useful_hard_max = int(useful_hard_max) if int(useful_hard_max) > 0 else 12

    def run(
        self,
        sp: SuperPrompt,
        *,
        agent_id: str = "a3_nli_gate",
        version: str = "002",
    ) -> SuperPrompt:
        """
        Main entry point for A3.
        """
        t0 = time.perf_counter()

        candidate_source = "reranked"
        reranked_rows = list(sp.views_by_stage.get("reranked", []))[: self._max_candidates]

        if not reranked_rows:
            candidate_source = "retrieval"
            reranked_rows = list(sp.views_by_stage.get("retrieval", []))[: self._max_candidates]

        if not reranked_rows:
            logger(
                "A3 skipped: no candidate chunks available. Run Retrieval first.",
                "WARN",
                "PUBLIC",
            )
            raise RuntimeError("A3NLIGate: no candidate chunks available. Run Retrieval first.")

        candidate_count = len(reranked_rows)

        logger(
            f"A3 started: candidates={candidate_count}, source={candidate_source}.",
            "INFO",
            "PUBLIC",
        )

        evidence_chunks_text, local_to_real = self._build_evidence_chunks_text(sp, reranked_rows)
        if not evidence_chunks_text:
            logger(
                "A3 failed: could not build evidence chunk text.",
                "ERROR",
                "PUBLIC",
            )
            raise RuntimeError("A3NLIGate: could not build evidence chunk text from candidate rows.")

        user_prompt_text = SuperPromptProjector.build_a3_comparison_prompt_text(sp)
        required_output_text = self._build_required_output_text(len(local_to_real))

        inputs: Dict[str, Any] = {
            "user_prompt_under_evaluation": user_prompt_text,
            "evidence_chunks": evidence_chunks_text,
            "required_output": required_output_text,
        }

        agent = self._factory.get_agent(agent_id=agent_id, version=version)

        logger(
            (
                "A3 LLM call prepared: "
                f"model={agent.model_name}, "
                f"candidate_count={candidate_count}, "
                f"source={candidate_source}"
            ),
            "INFO",
            "INTERNAL",
        )

        messages, response_format = agent.compose(input_payload=inputs)

        if A3_FULL_LLM_LOG_ENABLED:
            logger_dev(
                "A3 FULL LLM INPUT\n"
                + json.dumps(
                    {
                        "agent_id": agent_id,
                        "version": version,
                        "model_name": agent.model_name,
                        "candidate_count": candidate_count,
                        "messages": messages,
                        "response_format": response_format,
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                "DEBUG",
                "CONFIDENTIAL",
            )

        raw_result: Union[str, JsonDict] = self._llm_client.responses(
            messages=messages,
            model_name=agent.model_name,
            max_output_tokens=agent.max_output_tokens,
            reasoning_effort="minimal",
            return_metadata=False,
            prompt_cache_key=f"{agent_id}_{version}",
        )

        if A3_FULL_LLM_LOG_ENABLED:
            if isinstance(raw_result, dict):
                raw_result_text = json.dumps(raw_result, ensure_ascii=False, indent=2, default=str)
            else:
                raw_result_text = str(raw_result)

            logger_dev(
                "A3 FULL LLM RAW RESULT\n" + raw_result_text,
                "DEBUG",
                "CONFIDENTIAL",
            )

        try:
            parsed_result = agent.parse(raw_result)
            parse_ok = True
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            logger(
                f"A3 parse failed: latency_ms={elapsed_ms}, error={exc}",
                "ERROR",
                "PUBLIC",
            )
            raise

        item_root = agent.output_schema.get("root_key", "item_decisions")
        parsed_items = parsed_result.get(item_root, []) or []

        decisions_by_real_id: Dict[str, Dict[str, Any]] = {}

        if isinstance(parsed_items, list):
            for item in parsed_items:
                if not isinstance(item, dict):
                    continue

                local_chunk_id = str(item.get("chunk_id", "") or "").strip()
                if not local_chunk_id:
                    continue

                real_chunk_id = local_to_real.get(local_chunk_id)
                if not real_chunk_id:
                    continue

                usefulness_label = str(item.get("usefulness_label", "") or "").strip().lower()
                if usefulness_label not in {"useful", "borderline", "discarded"}:
                    usefulness_label = "borderline"

                decisions_by_real_id[real_chunk_id] = {
                    "chunk_id": real_chunk_id,
                    "local_chunk_id": local_chunk_id,
                    "usefulness_label": usefulness_label,
                }

        ordered_stage_rows: List[tuple[str, float, A3ChunkStatus]] = []
        ordered_decision_map: Dict[str, Dict[str, Any]] = {}

        useful_ids: List[str] = []
        borderline_ids: List[str] = []
        discarded_ids: List[str] = []

        decision_log_lines: List[str] = []

        for rank_index, row in enumerate(reranked_rows, start=1):
            real_chunk_id = str(row[0])
            try:
                stage_score = float(row[1])
            except Exception:
                stage_score = 0.0

            decision = decisions_by_real_id.get(real_chunk_id, {})
            usefulness_label = str(decision.get("usefulness_label", "") or "").strip().lower()
            if usefulness_label not in {"useful", "borderline", "discarded"}:
                usefulness_label = "borderline"

            local_chunk_id = str(decision.get("local_chunk_id", "") or rank_index)

            if usefulness_label == "discarded":
                stage_status = A3ChunkStatus.DISCARDED
                discarded_ids.append(real_chunk_id)
            else:
                stage_status = A3ChunkStatus.SELECTED

            ordered_stage_rows.append((real_chunk_id, stage_score, stage_status))

            ordered_decision_map[real_chunk_id] = {
                "chunk_id": real_chunk_id,
                "local_chunk_id": str(local_chunk_id),
                "rank": rank_index,
                "usefulness_label": usefulness_label,
            }

            if usefulness_label == "useful":
                useful_ids.append(real_chunk_id)
            elif usefulness_label == "borderline":
                borderline_ids.append(real_chunk_id)

            decision_log_lines.append(
                (
                    f"rank={rank_index} | "
                    f"local_chunk_id={local_chunk_id} | "
                    f"label={usefulness_label} | "
                    f"score={stage_score:.8f} | "
                    f"chunk_id={real_chunk_id}"
                )
            )

        # Final A3 selection:
        # - useful chunks only
        # - maximum useful count only
        # - no minimum useful count
        # - no automatic borderline promotion
        selected_ids: List[str] = useful_ids[: self._useful_hard_max]

        sp.views_by_stage["a3"] = ordered_stage_rows
        sp.final_selection_ids = selected_ids
        sp.extras["a3_item_decisions"] = ordered_decision_map
        sp.extras["a3_selected_ids"] = selected_ids
        sp.extras["a3_candidate_source"] = candidate_source
        sp.extras["a3_candidate_count"] = candidate_count
        sp.extras["a3_parse_ok"] = parse_ok
        sp.extras["a3_max_useful"] = self._useful_hard_max
        sp.extras["a3_min_useful_forced"] = 0

        # Remove stale selection_band if this SuperPrompt object was reused
        # after an older A3 implementation.
        sp.extras.pop("a3_selection_band", None)

        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        logger(
            (
                "A3 finished: "
                f"candidates={candidate_count}, "
                f"useful={len(useful_ids)}, "
                f"borderline={len(borderline_ids)}, "
                f"discarded={len(discarded_ids)}, "
                f"selected={len(selected_ids)}, "
                f"max_useful={self._useful_hard_max}, "
                f"model={agent.model_name}, "
                f"latency_ms={elapsed_ms}"
            ),
            "INFO",
            "PUBLIC",
        )

        if decision_log_lines:
            logger(
                "A3 chunk decisions:\n" + "\n".join(decision_log_lines),
                "INFO",
                "INTERNAL",
            )

        if selected_ids:
            logger(
                "A3 selected ids: " + ", ".join(str(item) for item in selected_ids),
                "INFO",
                "INTERNAL",
            )

        sp.history_of_stages.append("a3")
        sp.stage = "a3"
        sp.compose_prompt_ready()

        return sp

    def _build_user_prompt_under_evaluation(self, sp: SuperPrompt) -> str:
        """
        Build only the real user-prompt text for A3, in this exact order:
        1) purpose, if present
        2) task, always expected in the system
        3) context, if present

        No labels, no A2 meta fields, no other body fields.
        Wrapped with one outer XML-like structure only.
        """
        parts: List[str] = []

        purpose = (sp.body.get("purpose") or "").strip()
        task = (sp.body.get("task") or "").strip()
        context = (sp.body.get("context") or "").strip()

        if purpose:
            parts.append(purpose)
        if task:
            parts.append(task)
        if context:
            parts.append(context)

        inner_text = "\n\n".join(parts).strip()
        lines: List[str] = ["<user_prompt_under_evaluation>"]
        if inner_text:
            lines.append(inner_text)
        lines.append("</user_prompt_under_evaluation>")
        return "\n".join(lines).strip()

    def _build_evidence_chunks_text(
        self,
        sp: SuperPrompt,
        reranked_rows: List[tuple[str, float, A3ChunkStatus]],
    ) -> Tuple[str, Dict[str, str]]:
        """
        Build the A3-specific evidence block text and a local-id -> real-id mapping.

        Uses one outer XML-like structure only, with per-chunk wrappers.
        Inside chunk_text, structure-forming markdown is sanitized line-by-line
        so inner headings cannot compete with outer prompt structure.
        """
        chunk_by_id: Dict[str, Any] = {}
        for chunk_obj in sp.base_context_chunks:
            chunk_by_id[getattr(chunk_obj, "id", "")] = chunk_obj

        lines: List[str] = ["<evidence_chunks>"]
        local_to_real: Dict[str, str] = {}

        for rank_index, row in enumerate(reranked_rows, start=1):
            real_chunk_id = str(row[0])
            chunk_obj = chunk_by_id.get(real_chunk_id)
            if chunk_obj is None:
                continue

            local_chunk_id = str(rank_index)
            local_to_real[local_chunk_id] = real_chunk_id

            chunk_text = self._extract_chunk_text(chunk_obj)
            chunk_text_lines = chunk_text.splitlines() if chunk_text else [""]

            lines.append(
                f'  <chunk index="{local_chunk_id}" chunk_id="{local_chunk_id}" rank="{rank_index}">'
            )
            lines.append("    <chunk_text>")
            for line in chunk_text_lines:
                lines.append(f"      {line}")
            lines.append("    </chunk_text>")
            lines.append("  </chunk>")

        lines.append("</evidence_chunks>")

        return "\n".join(lines).strip(), local_to_real

    def _build_required_output_text(self, n_chunks: int) -> str:
        """
        Build the A3-specific JSON shape text shown to the LLM.
        Wrapped with one outer XML-like structure only.
        """
        lines: List[str] = []
        lines.append("<required_output>")
        lines.append("Return exactly one JSON object in this shape:")
        lines.append("")
        lines.append("{")
        lines.append('  "item_decisions": [')

        for idx in range(1, n_chunks + 1):
            suffix = "," if idx < n_chunks else ""
            lines.append("    {")
            lines.append(f'      "chunk_id": "{idx}",')
            lines.append('      "usefulness_label": "useful | borderline | discarded"')
            lines.append(f"    }}{suffix}")

        lines.append("  ]")
        lines.append("}")
        lines.append("</required_output>")

        return "\n".join(lines).strip()

    @staticmethod
    def _sanitize_line_start_structure_markers(text: str) -> str:
        """
        Sanitize only structure-forming markers at line start inside chunk text.

        Rules:
        - line-start # / ## / ### ... -> [H1] / [H2] / [H3] ...
        - line-start ```               -> [CODE_FENCE]
        - line-start ---               -> [RULE]

        This preserves meaning better than replacing every '#' globally.
        """
        text = (text or "").replace("\r\n", "\n").replace("\r", "\n")

        sanitized_lines: List[str] = []
        heading_pattern = re.compile(r"^(#{1,6})(\s*)(.*)$")
        rule_pattern = re.compile(r"^-{3,}\s*$")

        for line in text.split("\n"):
            stripped = line.lstrip()
            indent = line[: len(line) - len(stripped)]

            if stripped.startswith("```"):
                remainder = stripped[3:].strip()
                if remainder:
                    sanitized_lines.append(f"{indent}[CODE_FENCE] {remainder}")
                else:
                    sanitized_lines.append(f"{indent}[CODE_FENCE]")
                continue

            heading_match = heading_pattern.match(stripped)
            if heading_match:
                level = len(heading_match.group(1))
                content = heading_match.group(3).strip()
                if content:
                    sanitized_lines.append(f"{indent}[H{level}] {content}")
                else:
                    sanitized_lines.append(f"{indent}[H{level}]")
                continue

            if rule_pattern.match(stripped):
                sanitized_lines.append(f"{indent}[RULE]")
                continue

            sanitized_lines.append(line)

        return "\n".join(sanitized_lines).strip()

    @classmethod
    def _clean_prompt_chunk_text(cls, text: str) -> str:
        """
        Clean one chunk text for safe inclusion inside the A3 prompt.
        """
        return cls._sanitize_line_start_structure_markers(text)

    @classmethod
    def _extract_chunk_text(cls, chunk_obj: Any) -> str:
        """
        Extract one readable text body from a hydrated chunk object.
        """
        snippet = getattr(chunk_obj, "snippet", None)
        if isinstance(snippet, str) and snippet.strip():
            return cls._clean_prompt_chunk_text(snippet.strip())

        text_value = getattr(chunk_obj, "text", None)
        if isinstance(text_value, str) and text_value.strip():
            return cls._clean_prompt_chunk_text(text_value.strip())

        return ""