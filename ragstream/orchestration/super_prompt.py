# ragstream/orchestration/super_prompt.py
# -*- coding: utf-8 -*-
"""
SuperPrompt — central prompt object.

Stage refactor note:
- SuperPrompt remains the authoritative shared state object.
- Projection / render / text-extraction support logic lives in
  superprompt_projector.py.
- compose_prompt_ready() remains here as the stable public wrapper.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from ragstream.orchestration.superprompt_projector import SuperPromptProjector

# Lifecycle stages for this SuperPrompt.
Stage = Literal["raw", "preprocessed", "a2", "retrieval", "reranked", "a3", "a4", "a5"]


class A3ChunkStatus(str, Enum):
    SELECTED = "selected"
    DISCARDED = "discarded"
    DUPLICATED = "duplicated"


class SuperPrompt:
    __slots__ = (
        # session / lifecycle
        "stage",
        "model_target",
        "history_of_stages",

        # canonical prompt data
        "body",
        "extras",

        # effective retrieval query
        "effective_retrieval_query_text",

        # active memory brief
        "active_memory_brief_title",
        "active_memory_brief",

        # synthesized memory context
        "memory_context_text",

        # document retrieval artifacts
        "base_context_chunks",
        "views_by_stage",
        "final_selection_ids",

        # memory retrieval artifacts
        "memory_context_pack",

        # recent conversation
        "recentConversation",

        # rendered strings
        "System_MD",
        "Prompt_MD",
        "S_CTX_MD",
        "Attachments_MD",
        "prompt_ready",
    )

    def __init__(
        self,
        *,
        stage: Stage = "raw",
        model_target: Optional[str] = None,
    ) -> None:
        # Session / lifecycle.
        self.stage: Stage = stage
        self.model_target: Optional[str] = model_target
        self.history_of_stages: List[str] = []

        # Canonical prompt data.
        self.body: Dict[str, Optional[str]] = {
            "system": "consultant",
            "task": None,
            "audience": None,
            "role": None,
            "tone": "neutral",
            "depth": "high",
            "confidence": None,
            "evidence_policy": "normal",
            "context": None,
            "purpose": None,
            "format": None,
            "text": None,
        }

        # Free-form diagnostics and stage metadata.
        self.extras: Dict[str, Any] = {}

        # Effective retrieval query.
        # PreProcessing fills this now from TASK / PURPOSE / CONTEXT.
        # Later PreProcessing can replace it with a weak/strong-aware query.
        self.effective_retrieval_query_text: str = ""

        # Active Memory Brief shown below TASK / PURPOSE / CONTEXT.
        self.active_memory_brief_title: str = ""
        self.active_memory_brief: str = ""

        # Final synthesized query-relevant Memory Context.
        self.memory_context_text: str = ""

        # Document retrieval artifacts.
        self.base_context_chunks: List["Chunk"] = []

        # stage -> ordered rows:
        # (chunk_id, stage_score, stage_status)
        self.views_by_stage: Dict[str, List[tuple[str, float, A3ChunkStatus]]] = {}

        # Current selected document chunk ids.
        self.final_selection_ids: List[str] = []

        # Memory retrieval artifact.
        # Runtime object created by MemoryRetriever.
        # It is not durable memory truth.
        self.memory_context_pack: Any | None = None

        # Recent conversation block.
        self.recentConversation: Dict[str, Any] = {}

        # Rendered strings.
        self.System_MD: str = ""
        self.Prompt_MD: str = ""
        self.S_CTX_MD: str = ""
        self.Attachments_MD: str = ""
        self.prompt_ready: str = ""

    def compose_prompt_ready(self) -> str:
        """
        Stable public wrapper for the central SuperPrompt render path.
        """
        return SuperPromptProjector(self).compose_prompt_ready()

    def __repr__(self) -> str:
        return f"SuperPrompt(stage={self.stage!r})"