# ragstream/orchestration/superprompt_projector.py
# -*- coding: utf-8 -*-
"""
superprompt_projector.py

Purpose:
    Companion projection / render / text-extraction support for SuperPrompt.

Design:
    - SuperPrompt remains the authoritative shared state object.
    - This module owns derived render logic and text-oriented support logic.
    - compose_prompt_ready() remains publicly callable through the wrapper
      method on SuperPrompt for compatibility.
    - build_query_text(sp) also lives here, because it is a projection of
      SuperPrompt state into a retrieval-oriented text representation.
"""

from __future__ import annotations

from typing import Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from ragstream.orchestration.super_prompt import SuperPrompt


class SuperPromptProjector:
    """
    Projection / render helper around one SuperPrompt instance.
    """

    def __init__(self, sp: "SuperPrompt") -> None:
        if sp is None:
            raise ValueError("SuperPromptProjector.__init__: 'sp' must not be None")
        self.sp = sp

    @staticmethod
    def build_query_text(sp: "SuperPrompt") -> str:
        """
        Build the document Retrieval query text from SuperPrompt.

        6-state routing:

        1. SAME_TOPIC + STRONG       -> current prompt only
        2. RELATED_DOMAIN + STRONG   -> current prompt only
        3. IRRELEVANT + STRONG       -> current prompt only
        4. SAME_TOPIC + WEAK         -> current prompt + full ActiveBrief
        5. RELATED_DOMAIN + WEAK     -> current prompt + ActiveBrief title
        6. IRRELEVANT + WEAK         -> no document retrieval
        """
        if sp is None:
            raise ValueError("SuperPromptProjector.build_query_text: 'sp' must not be None")

        if not hasattr(sp, "body") or sp.body is None:
            raise ValueError("SuperPromptProjector.build_query_text: SuperPrompt has no usable 'body'")

        extras = getattr(sp, "extras", {}) or {}

        materiality = str(
            extras.get("activebrief_prompt_materiality", "") or ""
        ).strip().upper()

        topic_relation = str(
            extras.get("activebrief_topic_relation", "") or ""
        ).strip().upper()

        activebrief_snapshot = extras.get("activebrief_relation_activebrief", {}) or {}
        if isinstance(activebrief_snapshot, dict):
            active_brief_title = str(activebrief_snapshot.get("title", "") or "").strip()
            active_brief_text = str(activebrief_snapshot.get("body", "") or "").strip()
        else:
            active_brief_title = ""
            active_brief_text = ""

        if materiality == "WEAK" and topic_relation == "IRRELEVANT":
            return ""

        blocks: List[str] = []

        task = (sp.body.get("task") or "").strip()
        purpose = (sp.body.get("purpose") or "").strip()
        context = (sp.body.get("context") or "").strip()

        if task:
            blocks.append("## TASK")
            blocks.append(task)
            blocks.append("")

        if purpose:
            blocks.append("## PURPOSE")
            blocks.append(purpose)
            blocks.append("")

        if context:
            blocks.append("## CONTEXT")
            blocks.append(context)
            blocks.append("")

        if materiality == "WEAK" and topic_relation == "SAME_TOPIC":
            if active_brief_text:
                blocks.append("## PREVIOUS MEMORY SUMMARY")
                blocks.append(active_brief_text)
                blocks.append("")

        elif materiality == "WEAK" and topic_relation == "RELATED_DOMAIN":
            if active_brief_title:
                blocks.append("## PREVIOUS MEMORY TITLE")
                blocks.append(active_brief_title)
                blocks.append("")

        query_text = "\n".join(blocks).strip()

        if not query_text:
            raise ValueError(
                "SuperPromptProjector.build_query_text: retrieval query is empty. "
                "At least one of TASK / PURPOSE / CONTEXT must be present."
            )

        return query_text

    @staticmethod
    def build_a3_comparison_prompt_text(sp: "SuperPrompt") -> str:
        """
        Build the A3 comparison prompt.

        6-state routing:

        1. SAME_TOPIC + STRONG       -> current prompt + full ActiveBrief
        2. RELATED_DOMAIN + STRONG   -> current prompt + full ActiveBrief
        3. IRRELEVANT + STRONG       -> current prompt + ActiveBrief title
        4. SAME_TOPIC + WEAK         -> current prompt + full ActiveBrief
        5. RELATED_DOMAIN + WEAK     -> current prompt + ActiveBrief title
        6. IRRELEVANT + WEAK         -> current prompt + full ActiveBrief
        """
        if sp is None:
            raise ValueError("SuperPromptProjector.build_a3_comparison_prompt_text: 'sp' must not be None")

        if not hasattr(sp, "body") or sp.body is None:
            raise ValueError(
                "SuperPromptProjector.build_a3_comparison_prompt_text: SuperPrompt has no usable 'body'"
            )

        extras = getattr(sp, "extras", {}) or {}

        materiality = str(
            extras.get("activebrief_prompt_materiality", "") or ""
        ).strip().upper()

        topic_relation = str(
            extras.get("activebrief_topic_relation", "") or ""
        ).strip().upper()

        activebrief_snapshot = extras.get("activebrief_relation_activebrief", {}) or {}
        if isinstance(activebrief_snapshot, dict):
            active_brief_title = str(activebrief_snapshot.get("title", "") or "").strip()
            active_brief_text = str(activebrief_snapshot.get("body", "") or "").strip()
        else:
            active_brief_title = ""
            active_brief_text = ""

        lines: List[str] = ["<user_prompt_under_evaluation>"]

        task = (sp.body.get("task") or "").strip()
        purpose = (sp.body.get("purpose") or "").strip()
        context = (sp.body.get("context") or "").strip()

        if task:
            lines.append("TASK:")
            lines.append(task)
            lines.append("")

        if purpose:
            lines.append("PURPOSE:")
            lines.append(purpose)
            lines.append("")

        if context:
            lines.append("CONTEXT:")
            lines.append(context)
            lines.append("")

        use_full_brief = (
            (materiality == "STRONG" and topic_relation in {"SAME_TOPIC", "RELATED_DOMAIN"})
            or (materiality == "WEAK" and topic_relation in {"SAME_TOPIC", "IRRELEVANT"})
        )

        use_title_only = (
            (materiality == "STRONG" and topic_relation == "IRRELEVANT")
            or (materiality == "WEAK" and topic_relation == "RELATED_DOMAIN")
        )

        if use_full_brief and active_brief_text:
            lines.append("PREVIOUS MEMORY SUMMARY:")
            lines.append(active_brief_text)
            lines.append("")
        elif use_title_only and active_brief_title:
            lines.append("PREVIOUS MEMORY TITLE:")
            lines.append(active_brief_title)
            lines.append("")

        lines.append("</user_prompt_under_evaluation>")
        return "\n".join(lines).strip()

    def compose_prompt_ready(self) -> str:
        self.sp.System_MD = self._render_system_md()
        self.sp.Prompt_MD = self._render_prompt_md()

        parts: List[str] = []

        if self.sp.System_MD:
            parts.append(self.sp.System_MD)

        if self.sp.Prompt_MD:
            parts.append(self.sp.Prompt_MD)

        retrieved_context_md = self._render_retrieved_context_md()
        if retrieved_context_md:
            parts.append(retrieved_context_md)

        if self.sp.Attachments_MD:
            parts.append(self.sp.Attachments_MD)

        self.sp.prompt_ready = "\n\n".join(parts).strip()
        return self.sp.prompt_ready

    def _render_system_md(self) -> str:
        lines: List[str] = []

        system_value = (self.sp.body.get("system") or "").strip()
        role_value = (self.sp.body.get("role") or "").strip()
        audience_value = (self.sp.body.get("audience") or "").strip()
        tone_value = (self.sp.body.get("tone") or "").strip()
        depth_value = (self.sp.body.get("depth") or "").strip()
        confidence_value = (self.sp.body.get("confidence") or "").strip()

        extras = getattr(self.sp, "extras", {}) or {}
        selected_ids = extras.get("a2_selected_ids", {}) or {}
        if not isinstance(selected_ids, dict):
            selected_ids = {}

        evidence_policy_id = str(
            selected_ids.get("evidence_policy")
            or self.sp.body.get("evidence_policy")
            or "normal"
        ).strip()

        lines.append("## System")
        if system_value:
            lines.append(system_value)
        else:
            lines.append("")

        config_lines: List[str] = []

        if role_value:
            config_lines.append(f"- Role: {role_value}")
        if audience_value:
            config_lines.append(f"- Audience: {audience_value}")
        if tone_value:
            config_lines.append(f"- Tone: {tone_value}")
        if depth_value:
            config_lines.append(f"- Depth: {depth_value}")
        if confidence_value:
            config_lines.append(f"- Confidence: {confidence_value}")

        evidence_policy_md = self._render_evidence_policy_md(evidence_policy_id)

        if evidence_policy_md:
            config_lines.append(f"- Evidence Policy: {evidence_policy_id}")

        lines.append("")
        lines.append("## Configuration")
        lines.extend(config_lines)

        if evidence_policy_md:
            lines.append("")
            lines.append(evidence_policy_md)

        return "\n".join(lines).strip()

    @staticmethod
    def _render_evidence_policy_md(evidence_policy_id: str) -> str:
        policy = str(evidence_policy_id or "").strip()

        if not policy or policy == "normal":
            return ""

        if policy == "local_context_first":
            return "\n".join(
                [
                    "## Evidence Policy",
                    "Mode: local_context_first",
                    "",
                    "Instructions:",
                    "- First use available project files, retrieved context, memory, and prior chat context.",
                    "- Do not replace missing local/project/history facts with generic claims.",
                    "- If a required local/project/history fact is missing, say what is missing instead of inventing.",
                ]
            ).strip()

        if policy == "strict_history_and_online_fact_check":
            return "\n".join(
                [
                    "## Evidence Policy",
                    "Mode: strict_history_and_online_fact_check",
                    "",
                    "Instructions:",
                    "- First use only evidence actually available in the current prompt, chat-history summary, memory context, project files, and retrieved context.",
                    "- Do not answer generically when project/history facts are missing.",
                    "- For external, recent, niche, unstable, salary, job-market, company, legal, financial, medical, product, or political facts, verify online before answering when web access is available.",
                    "- Cite evidence when possible.",
                    "- If evidence is missing or verification is unavailable, say what is missing instead of inventing.",
                ]
            ).strip()

        return ""

    def _render_prompt_md(self) -> str:
        lines: List[str] = []

        task_value = (self.sp.body.get("task") or "").strip()
        purpose_value = (self.sp.body.get("purpose") or "").strip()
        context_value = (self.sp.body.get("context") or "").strip()
        format_value = (self.sp.body.get("format") or "").strip()
        text_value = (self.sp.body.get("text") or "").strip()

        lines.append("## Current User Request")
        lines.append(
            "Priority: highest. Answer this request directly. "
            "Treat all later memory and retrieved context as supporting background only."
        )
        lines.append("")

        lines.append("### Task")
        lines.append(task_value)
        lines.append("")

        if purpose_value:
            lines.append("### Purpose")
            lines.append(purpose_value)
            lines.append("")

        if context_value:
            lines.append("### Context")
            lines.append(context_value)
            lines.append("")

        if format_value:
            lines.append("### Format")
            lines.append(format_value)
            lines.append("")

        if text_value:
            lines.append("### Text")
            lines.append(text_value)
            lines.append("")

        return "\n".join(lines).strip()

    def _render_retrieved_context_md(self) -> str:
        """
        Render supporting context for GUI-visible SuperPrompt preview.

        Rules:
        - Previous Conversation Summary belongs under Supporting Context.
        - Memory Context belongs under Supporting Context.
        - Retrieved Project Evidence Summary belongs under Supporting Context.
        - show document raw chunks after Retrieval/Reranker/A3
        - hide document raw chunks after A4/A5
        """
        extras = getattr(self.sp, "extras", {}) or {}

        materiality = str(
            extras.get("activebrief_prompt_materiality", "") or ""
        ).strip().upper()

        topic_relation = str(
            extras.get("activebrief_topic_relation", "") or ""
        ).strip().upper()

        activebrief_snapshot = extras.get("activebrief_relation_activebrief", {}) or {}
        if isinstance(activebrief_snapshot, dict):
            active_brief_title = str(activebrief_snapshot.get("title", "") or "").strip()
            active_brief_text = str(activebrief_snapshot.get("body", "") or "").strip()
        else:
            active_brief_title = ""
            active_brief_text = ""

        use_full_brief = (
            (materiality == "STRONG" and topic_relation in {"SAME_TOPIC", "RELATED_DOMAIN"})
            or (materiality == "WEAK" and topic_relation in {"SAME_TOPIC", "IRRELEVANT"})
        )

        use_title_only = (
            (materiality == "STRONG" and topic_relation == "IRRELEVANT")
            or (materiality == "WEAK" and topic_relation == "RELATED_DOMAIN")
        )

        memory_context_md = self._render_memory_context_md()
        document_context_md = self._render_document_context_summary_md()
        raw_document_evidence_md = self._render_raw_document_evidence_for_stage_md()

        has_previous_summary = use_full_brief and (active_brief_title or active_brief_text)
        has_previous_topic = use_title_only and active_brief_title

        if (
            not has_previous_summary
            and not has_previous_topic
            and not memory_context_md
            and not document_context_md
            and not raw_document_evidence_md
        ):
            return ""

        lines: List[str] = []

        lines.append("## Supporting Context")
        lines.append("Priority: supporting only. Use this material only when it helps answer the current TASK.")
        lines.append("")

        if has_previous_summary:
            lines.append("### Previous Conversation Summary")
            lines.append("Priority: background only. Use this for continuity, but do not treat it as the current task.")
            lines.append("")

            if active_brief_title:
                lines.append(f"Title: {active_brief_title}")
                lines.append("")

            if active_brief_text:
                lines.append(active_brief_text)
                lines.append("")

        elif has_previous_topic:
            lines.append("### Previous Conversation Topic")
            lines.append("Priority: weak background only. Use only for continuity or topic-shift awareness.")
            lines.append("")
            lines.append(f"Title: {active_brief_title}")
            lines.append("")

        if memory_context_md:
            lines.append("### Memory Context")
            lines.append("This is synthesized memory context. It is background support, not the current task.")
            lines.append("")
            lines.append(memory_context_md)
            lines.append("")

        if document_context_md:
            lines.append("### Retrieved Project Evidence Summary")
            lines.append(
                "The following summary is retrieved from selected project files. "
                "It is supporting evidence for the current TASK, not the task itself."
            )
            lines.append("")
            lines.append(document_context_md)
            lines.append("")

        if raw_document_evidence_md:
            lines.append("### Raw Retrieved Evidence")
            lines.append("Raw evidence is lower priority than the current TASK and should only support the answer.")
            lines.append("")
            lines.append(raw_document_evidence_md)

        return "\n".join(lines).strip()

    def _render_memory_context_md(self) -> str:
        memory_context = str(getattr(self.sp, "memory_context_text", "") or "").strip()

        if not memory_context:
            extras = getattr(self.sp, "extras", {}) or {}
            memory_context = str(extras.get("memory_context_text", "") or "").strip()

        return memory_context

    def _render_document_context_summary_md(self) -> str:
        return str(getattr(self.sp, "S_CTX_MD", "") or "").strip()

    def _render_raw_document_evidence_for_stage_md(self) -> str:
        if str(getattr(self.sp, "stage", "") or "").strip() in {"a4", "a5"}:
            return ""

        return self._render_raw_retrieved_evidence_md()

    def _render_raw_memory_retrieval_md(self) -> str:
        """
        Backward-compatible raw memory renderer.

        The GUI path no longer calls this method because raw memory episodes and
        raw memory chunks should not be shown in the SuperPrompt preview.
        """
        extras = getattr(self.sp, "extras", {}) or {}
        memory_debug_md = str(extras.get("memory_debug_markdown", "") or "").strip()
        return memory_debug_md

    def _render_raw_retrieved_evidence_md(self) -> str:
        """
        Render raw retrieved document chunks as nested evidence.

        Source Markdown headings inside chunks are converted to [H1]/[H2]/[H3]
        so they do not compete with the visible SuperPrompt structure.
        """
        ordered_chunks = self._get_ordered_context_chunks()
        if not ordered_chunks:
            return ""

        retrieval_score_map: Dict[str, float] = {
            chunk_id: float(score)
            for chunk_id, score, _status in self.sp.views_by_stage.get("retrieval", [])
        }

        reranked_score_map: Dict[str, float] = {
            chunk_id: float(score)
            for chunk_id, score, _status in self.sp.views_by_stage.get("reranked", [])
        }

        a3_decision_map: Dict[str, Dict[str, Any]] = {}
        raw_a3_decisions = self.sp.extras.get("a3_item_decisions", {})
        if isinstance(raw_a3_decisions, dict):
            a3_decision_map = raw_a3_decisions

        selection_band = str(self.sp.extras.get("a3_selection_band", "") or "").strip()

        lines: List[str] = []
        lines.append("<retrieved_chunks>")

        if self.sp.stage == "a3" and selection_band:
            lines.append(f'  <selection_band>{selection_band}</selection_band>')

        chunk_counter = 1
        for chunk_obj in ordered_chunks:
            attributes: List[str] = [
                f'index="{chunk_counter}"',
                f'chunk_id="{self._escape_attr(str(chunk_obj.id))}"',
            ]

            source_value = ""
            meta = getattr(chunk_obj, "meta", None)
            if isinstance(meta, dict):
                source_value = str(meta.get("source") or meta.get("path") or meta.get("file") or "").strip()
            if source_value:
                attributes.append(f'source="{self._escape_attr(source_value)}"')

            score_label = self._build_chunk_score_label(
                chunk_obj=chunk_obj,
                retrieval_score_map=retrieval_score_map,
                reranked_score_map=reranked_score_map,
                a3_decision_map=a3_decision_map,
            )
            if score_label:
                attributes.append(f'info="{self._escape_attr(score_label)}"')

            lines.append(f"  <chunk {' '.join(attributes)}>")
            lines.append("    <chunk_text>")

            snippet = self._sanitize_chunk_text(chunk_obj.snippet.strip())
            if snippet:
                for snippet_line in snippet.splitlines():
                    lines.append(f"      {snippet_line}")

            lines.append("    </chunk_text>")
            lines.append("  </chunk>")
            chunk_counter += 1

        lines.append("</retrieved_chunks>")

        return "\n".join(lines).strip()

    def _build_chunk_score_label(
        self,
        *,
        chunk_obj: Any,
        retrieval_score_map: Dict[str, float],
        reranked_score_map: Dict[str, float],
        a3_decision_map: Dict[str, Dict[str, Any]],
    ) -> str:
        score_parts: List[str] = []

        emb_score = self._get_meta_float(chunk_obj.meta, "emb_score")
        splade_score = self._get_meta_float(chunk_obj.meta, "splade_score")

        if self.sp.stage == "retrieval":
            rt_score = retrieval_score_map.get(chunk_obj.id)
            if rt_score is not None:
                score_parts.append(f"Rt={self._format_score(rt_score)}")
            if emb_score is not None:
                score_parts.append(f"Emb={self._format_score(emb_score)}")
            if splade_score is not None:
                score_parts.append(f"Splade={self._format_score(splade_score)}")

        elif self.sp.stage == "reranked":
            rnk_score = reranked_score_map.get(chunk_obj.id)
            if rnk_score is None:
                rnk_score = self._get_meta_float(chunk_obj.meta, "rerank_rrf_score")

            rcolb_score = self._get_meta_float(chunk_obj.meta, "colbert_score")

            rt_score = self._get_meta_float(chunk_obj.meta, "retrieval_rrf_score")
            if rt_score is None:
                rt_score = self._get_meta_float(chunk_obj.meta, "retrieval_score")
            if rt_score is None:
                rt_score = retrieval_score_map.get(chunk_obj.id)

            if rnk_score is not None:
                score_parts.append(f"Rnk={self._format_score(rnk_score)}")
            if rcolb_score is not None:
                score_parts.append(f"RcolB={self._format_score(rcolb_score)}")
            if rt_score is not None:
                score_parts.append(f"Rt={self._format_score(rt_score)}")

        elif self.sp.stage == "a3":
            decision = a3_decision_map.get(chunk_obj.id, {})
            usefulness = str(decision.get("usefulness_label", "") or "").strip()
            if usefulness:
                score_parts.append(f"Use={usefulness}")

        return ", ".join(score_parts).strip()

    @staticmethod
    def _sanitize_chunk_text(text: str) -> str:
        """
        Prevent source Markdown headings from becoming real prompt headings.
        """
        if not text:
            return ""

        sanitized_lines: List[str] = []

        for line in text.splitlines():
            stripped = line.lstrip()
            indent = line[: len(line) - len(stripped)]

            if stripped.startswith("### "):
                sanitized_lines.append(f"{indent}[H3] {stripped[4:].strip()}")
            elif stripped.startswith("## "):
                sanitized_lines.append(f"{indent}[H2] {stripped[3:].strip()}")
            elif stripped.startswith("# "):
                sanitized_lines.append(f"{indent}[H1] {stripped[2:].strip()}")
            else:
                sanitized_lines.append(line)

        return "\n".join(sanitized_lines).strip()

    @staticmethod
    def _escape_attr(value: str) -> str:
        return (
            str(value or "")
            .replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def _format_score(self, score: float) -> str:
        return f"{float(score):.8f}".rstrip("0").rstrip(".")

    def _render_related_context_md(self) -> str:
        """
        Backward-compatible wrapper.
        """
        return self._render_raw_retrieved_evidence_md()

    @staticmethod
    def _get_meta_float(meta: Dict[str, Any] | None, key: str) -> float | None:
        if not isinstance(meta, dict):
            return None

        value = meta.get(key)
        if value is None:
            return None

        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _get_ordered_context_chunks(self) -> List["Chunk"]:
        if not self.sp.base_context_chunks:
            return []

        chunk_by_id: Dict[str, "Chunk"] = {}
        for chunk_obj in self.sp.base_context_chunks:
            chunk_by_id[chunk_obj.id] = chunk_obj

        ordered_chunks: List["Chunk"] = []

        if self.sp.stage == "a3" and "a3" in self.sp.views_by_stage:
            stage_rows = self.sp.views_by_stage["a3"]
            for row in stage_rows:
                chunk_id = row[0]
                if chunk_id in chunk_by_id:
                    ordered_chunks.append(chunk_by_id[chunk_id])
            return ordered_chunks

        if self.sp.final_selection_ids:
            for chunk_id in self.sp.final_selection_ids:
                if chunk_id in chunk_by_id:
                    ordered_chunks.append(chunk_by_id[chunk_id])
            return ordered_chunks

        if self.sp.stage in self.sp.views_by_stage:
            stage_rows = self.sp.views_by_stage[self.sp.stage]
            for row in stage_rows:
                chunk_id = row[0]
                if chunk_id in chunk_by_id:
                    ordered_chunks.append(chunk_by_id[chunk_id])
            return ordered_chunks

        for chunk_obj in self.sp.base_context_chunks:
            ordered_chunks.append(chunk_obj)

        return ordered_chunks