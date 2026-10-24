# ragstream/app/controller.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import json

from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from ragstream.orchestration.super_prompt import SuperPrompt
from ragstream.orchestration.superprompt_projector import SuperPromptProjector
from ragstream.preprocessing.prompt_schema import PromptSchema
from ragstream.preprocessing.preprocessing import preprocess
from ragstream.preprocessing.activebrief_relation_classifier import ActiveBriefRelationClassifier

from ragstream.orchestration.agent_factory import AgentFactory
from ragstream.orchestration.llm_client import LLMClient
from ragstream.agents.a2_promptshaper import A2PromptShaper
from ragstream.agents.a3_nli_gate import A3NLIGate
from ragstream.agents.a4_condenser import A4Condenser

# Added on 10.03.2026:
# Project-based document ingestion is wired here only at controller level.
from ragstream.ingestion.chunker import Chunker
from ragstream.ingestion.embedder import Embedder
from ragstream.ingestion.ingestion_manager import IngestionManager
from ragstream.ingestion.vector_store_chroma import VectorStoreChroma

# Added on 13.04.2026:
# Parallel SPLADE ingestion branch.
from ragstream.ingestion.splade_embedder import SpladeEmbedder
from ragstream.ingestion.vector_store_splade import VectorStoreSplade

# Added on 15.03.2026:
# Deterministic Retrieval stage.
from ragstream.retrieval.retriever import Retriever
from ragstream.retrieval.reranker import Reranker

# Added on 05.05.2026:
# Memory Retrieval stage entry point.
from ragstream.retrieval.retriever_mem import MemoryRetriever

from ragstream.textforge.RagLog import LogALL as logger
from ragstream.textforge.RagLog import LogDeveloper as _logger_dev

DEV_LOG_ENABLED = False


def logger_dev(*args, **kwargs):
    if DEV_LOG_ENABLED:
        return _logger_dev(*args, **kwargs)
    return None


class AppController:
    def __init__(self, schema_path: str = "ragstream/config/prompt_schema.json") -> None:
        """
        Central app controller.

        Light initialization only.

        - Loads PromptSchema once for PreProcessing.
        - Creates shared AgentFactory + LLMClient.
        - Creates A2, A3, A4 agent objects.
        - Prepares project/data paths.
        - Loads runtime_config.json.
        - Keeps MemoryRetriever optional until Streamlit provides MemoryManager
          and MemoryVectorStore from session_state.
        """
        # PreProcessing schema.
        self.schema = PromptSchema(schema_path)

        # Shared AgentFactory for LLM-based agents.
        self.agent_factory = AgentFactory()

        # Shared LLM client.
        self.llm_client = LLMClient()

        # A2 agent.
        self.a2_promptshaper = A2PromptShaper(
            agent_factory=self.agent_factory,
            llm_client=self.llm_client,
        )

        # ActiveBrief relation classifier.
        self.activebrief_relation_classifier = ActiveBriefRelationClassifier(
            agent_factory=self.agent_factory,
            llm_client=self.llm_client,
        )

        # A3 agent.
        self.a3_nli_gate = A3NLIGate(
            agent_factory=self.agent_factory,
            llm_client=self.llm_client,
        )

        # A4 agent.
        self.a4_condenser = A4Condenser(
            llm_client=self.llm_client,
        )

        # Project/data roots.
        self.project_root = Path(__file__).resolve().parents[2]
        self.data_root = self.project_root / "data"
        self.doc_root = self.data_root / "doc_raw"
        self.chroma_root = self.data_root / "chroma_db"
        self.splade_root = self.data_root / "splade_db"
        self.memory_root = self.data_root / "memory"
        self.memory_sqlite_path = self.memory_root / "memory_index.sqlite3"

        self.doc_root.mkdir(parents=True, exist_ok=True)
        self.chroma_root.mkdir(parents=True, exist_ok=True)
        self.splade_root.mkdir(parents=True, exist_ok=True)
        self.memory_root.mkdir(parents=True, exist_ok=True)

        # Global runtime defaults.
        self.runtime_config_path = self.project_root / "ragstream" / "config" / "runtime_config.json"
        self.runtime_config: dict[str, Any] = self._load_runtime_config()

        # Heavy components are created later in initialize_heavy_components().
        self.retriever: Retriever | None = None
        self.reranker: Reranker | None = None
        self.heavy_initialization_error: str = ""

        # MemoryRetriever is configured by ui_streamlit.py after memory objects exist.
        self.memory_retriever: MemoryRetriever | None = None

    @property
    def heavy_components_ready(self) -> bool:
        """Return True only when both heavy document components are usable."""
        return self.retriever is not None and self.reranker is not None

    def initialize_heavy_components(self) -> None:
        """
        Initialize document Retrieval and ReRanker atomically.

        Until both objects are ready, the controller remains in the not-ready
        state so GUI controls can stay disabled instead of racing startup.
        """
        self.heavy_initialization_error = ""

        try:
            retriever = Retriever(
                doc_root=str(self.doc_root),
                chroma_root=str(self.chroma_root),
                runtime_config=self.runtime_config,
            )
            reranker = Reranker()
        except Exception as error:
            self.retriever = None
            self.reranker = None
            self.heavy_initialization_error = (
                f"{type(error).__name__}: {error}"
            )
            logger(
                f"Heavy component initialization failed: {self.heavy_initialization_error}",
                "ERROR",
                "PUBLIC",
            )
            logger_dev(
                f"Heavy component initialization exception: {self.heavy_initialization_error}",
                "ERROR",
                "CONFIDENTIAL",
            )
            return

        self.retriever = retriever
        self.reranker = reranker
        logger("Retrieval and ReRanker initialization completed.", "INFO", "INTERNAL")

    def configure_memory_retrieval(
        self,
        *,
        memory_manager: Any,
        memory_vector_store: Any,
        runtime_config: dict[str, Any] | None = None,
    ) -> None:
        """
        Configure MemoryRetriever after Streamlit session_state has created:
        - MemoryManager
        - MemoryVectorStore

        This keeps controller construction light and avoids putting Streamlit
        objects inside AppController.__init__.
        """
        if runtime_config is not None:
            self.runtime_config = runtime_config

        self.memory_retriever = MemoryRetriever(
            memory_manager=memory_manager,
            memory_vector_store=memory_vector_store,
            sqlite_path=self.memory_sqlite_path,
            config=self.runtime_config,
        )

        logger(
            "Memory Retrieval configured.",
            "INFO",
            "INTERNAL",
        )

        logger_dev(
            (
                "Memory Retrieval configured\n"
                f"memory_root={self.memory_root}\n"
                f"sqlite_path={self.memory_sqlite_path}\n"
                f"runtime_config={json.dumps(self.runtime_config.get('memory_retrieval', {}), ensure_ascii=False, indent=2, default=str)}"
            ),
            "DEBUG",
            "CONFIDENTIAL",
        )

    def preprocess(
        self,
        user_text: str,
        sp: SuperPrompt,
        *,
        memory_manager: Any | None = None,
    ) -> SuperPrompt:
        """
        Keep existing behavior:
        - Ignore empty/whitespace-only input.
        - Otherwise run deterministic preprocessing and update SuperPrompt.
        """
        text = (user_text or "").strip()
        if not text:
            return sp

        logger("PreProcessing started.", "INFO", "PUBLIC")
        preprocess(text, sp, self.schema)

        sp = self.activebrief_relation_classifier.run(
            sp=sp,
            memory_manager=memory_manager,
            raw_user_text=text,
        )

        # The relation classifier is authoritative for retrieval routing.
        # Rebuild after classification so the query cannot retain the stale
        # pre-classification ActiveBrief policy.
        sp.effective_retrieval_query_text = SuperPromptProjector.build_query_text(sp)

        sp.compose_prompt_ready()

        logger("PreProcessing completed.", "INFO", "PUBLIC")
        return sp

    def run_a2_promptshaper(
        self,
        sp: SuperPrompt,
        *,
        use_llm: bool = True,
    ) -> SuperPrompt:
        """Run A2, or bypass it completely when Prompt Shaping is off."""
        if not use_llm:
            logger("A2 PromptShaper bypassed: Prompt Shaping is off.", "INFO", "INTERNAL")
            return sp

        return self.a2_promptshaper.run(
            sp,
            use_llm=True,
        )

    @staticmethod
    def _should_bypass_enrichment(sp: SuperPrompt) -> bool:
        extras = getattr(sp, "extras", {}) or {}
        materiality = str(
            extras.get("activebrief_prompt_materiality", "") or ""
        ).strip().upper()
        topic_relation = str(
            extras.get("activebrief_topic_relation", "") or ""
        ).strip().upper()
        return materiality == "WEAK" and topic_relation == "IRRELEVANT"

    @staticmethod
    def _clear_enrichment_artifacts(sp: SuperPrompt) -> None:
        """Remove retrieval/memory artifacts from a bypassed SuperPrompt."""
        sp.effective_retrieval_query_text = ""
        sp.base_context_chunks = []
        sp.views_by_stage = {}
        sp.final_selection_ids = []
        sp.memory_context_pack = None
        sp.memory_context_text = ""
        sp.active_memory_brief_title = ""
        sp.active_memory_brief = ""
        sp.S_CTX_MD = ""

        extras = getattr(sp, "extras", {}) or {}
        for key in (
            "memory_context_pack",
            "memory_context_text",
            "memory_debug_markdown",
            "memory_retrieval_counts",
            "active_memory_brief_title",
            "active_memory_brief",
            "a3_ready_source",
            "a3_ready_candidate_count",
            "reranked_is_passthrough",
        ):
            extras.pop(key, None)

        for key in list(extras):
            if key.startswith("a3_") or key.startswith("a4_"):
                extras.pop(key, None)

        sp.compose_prompt_ready()

    def run_a3(self, sp: SuperPrompt) -> SuperPrompt:
        """Run A3 unless enrichment is bypassed for WEAK + IRRELEVANT."""
        if self._should_bypass_enrichment(sp):
            self._clear_enrichment_artifacts(sp)
            logger("A3 bypassed for WEAK + IRRELEVANT prompt.", "INFO", "INTERNAL")
            return sp

        return self.a3_nli_gate.run(sp)

    def run_a4(
        self,
        sp: SuperPrompt,
        *,
        effective_output_token_limit: int | None = None,
    ) -> SuperPrompt:
        """Run A4 unless enrichment is bypassed for WEAK + IRRELEVANT."""
        if self._should_bypass_enrichment(sp):
            self._clear_enrichment_artifacts(sp)
            logger("A4 bypassed for WEAK + IRRELEVANT prompt.", "INFO", "INTERNAL")
            return sp

        return self.a4_condenser.run(
            sp,
            effective_output_token_limit=effective_output_token_limit,
        )

    def build_a2_memory_demo_entry(self, sp: SuperPrompt) -> dict[str, str]:
        """
        Build one demo memory entry for the A2 memory view.
        """
        input_text = self._build_a2_memory_demo_input(sp)
        if not input_text:
            input_text = "(empty)"

        return {
            "input_text": input_text,
            "output_text": "XXXXX",
            "tag": "Green",
        }

    def _build_a2_memory_demo_input(self, sp: SuperPrompt) -> str:
        """
        Build a simple plain-text prompt for the memory demo.
        """
        lines: list[str] = []

        task_value = (sp.body.get("task") or "").strip()
        purpose_value = (sp.body.get("purpose") or "").strip()
        context_value = (sp.body.get("context") or "").strip()

        if task_value:
            lines.append("TASK")
            lines.append(task_value)
            lines.append("")

        if purpose_value:
            lines.append("PURPOSE")
            lines.append(purpose_value)
            lines.append("")

        if context_value:
            lines.append("CONTEXT")
            lines.append(context_value)
            lines.append("")

        return "\n".join(lines).strip()

    def run_retrieval(
        self,
        sp: SuperPrompt,
        project_name: str,
        top_k: int,
        *,
        use_retrieval_splade: bool = True,
    ) -> SuperPrompt:
        """
        Run Retrieval on the current SuperPrompt.

        Current behavior:
        1. Run document retrieval.
        2. Run memory retrieval if MemoryRetriever is configured.
        3. Store raw document chunks and raw memory candidates in SuperPrompt.

        This method does not run:
        - ReRanker
        - A3
        - A4
        - MemoryMerge
        """
        if self._should_bypass_enrichment(sp):
            self._clear_enrichment_artifacts(sp)
            logger("Retrieval bypassed for WEAK + IRRELEVANT prompt.", "INFO", "INTERNAL")
            return sp

        if self.retriever is None:
            raise RuntimeError("Document Retriever is not initialized yet.")

        project_name = self._normalize_project_name(project_name)

        sp = self.retriever.run(
            sp=sp,
            project_name=project_name,
            top_k=int(top_k),
            use_retrieval_splade=bool(use_retrieval_splade),
        )

        if self.memory_retriever is not None:
            try:
                sp = self.memory_retriever.run(sp)
            except Exception as e:
                logger(f"Memory Retrieval failed: {e}", "ERROR", "PUBLIC")
                logger_dev(
                    f"Memory Retrieval exception during AppController.run_retrieval: {e}",
                    "ERROR",
                    "CONFIDENTIAL",
                )
        else:
            logger(
                "Memory Retrieval skipped: MemoryRetriever is not configured.",
                "INFO",
                "INTERNAL",
            )

        return sp

    def run_reranker(
        self,
        sp: SuperPrompt,
        *,
        use_reranking_colbert: bool = True,
    ) -> SuperPrompt:
        """
        Run ReRanker on the current SuperPrompt.

        ReRanker currently operates only on document retrieval results.
        Memory candidates remain separately stored in SuperPrompt.
        """
        if self._should_bypass_enrichment(sp):
            self._clear_enrichment_artifacts(sp)
            logger("ReRanker bypassed for WEAK + IRRELEVANT prompt.", "INFO", "INTERNAL")
            return sp

        if self.reranker is None:
            raise RuntimeError("ReRanker is not initialized yet.")

        return self.reranker.run(
            sp,
            use_reranking_colbert=bool(use_reranking_colbert),
        )

    def list_projects(self) -> list[str]:
        doc_projects = {p.name for p in self.doc_root.iterdir() if p.is_dir()}
        chroma_projects = {p.name for p in self.chroma_root.iterdir() if p.is_dir()}
        splade_projects = {p.name for p in self.splade_root.iterdir() if p.is_dir()}
        return sorted(doc_projects | chroma_projects | splade_projects)

    def create_project(self, project_name: str) -> dict[str, Any]:
        project_name = self._normalize_project_name(project_name)
        raw_dir = self.doc_root / project_name
        chroma_dir = self.chroma_root / project_name
        splade_dir = self.splade_root / project_name

        raw_dir.mkdir(parents=True, exist_ok=True)
        chroma_dir.mkdir(parents=True, exist_ok=True)
        splade_dir.mkdir(parents=True, exist_ok=True)

        return {
            "success": True,
            "project_name": project_name,
            "raw_dir": str(raw_dir),
            "chroma_dir": str(chroma_dir),
            "splade_dir": str(splade_dir),
            "manifest_path": str(chroma_dir / "file_manifest.json"),
        }

    def ingest_project(self, project_name: str) -> dict[str, Any]:
        project_name = self._normalize_project_name(project_name)
        paths = self.create_project(project_name)

        manifest_path = Path(paths["manifest_path"])

        manager = IngestionManager(doc_root=str(self.doc_root))
        store = VectorStoreChroma(persist_dir=str(self.chroma_root / project_name))
        sparse_store = VectorStoreSplade(persist_dir=str(self.splade_root / project_name))
        chunker = Chunker()
        embedder = Embedder(model="text-embedding-3-small")
        sparse_embedder = SpladeEmbedder(device="cpu")

        stats = manager.run(
            subfolder=project_name,
            store=store,
            chunker=chunker,
            embedder=embedder,
            sparse_store=sparse_store,
            sparse_embedder=sparse_embedder,
            manifest_path=str(manifest_path),
        )

        result = asdict(stats)
        result.update(
            {
                "success": True,
                "project_name": project_name,
                "raw_dir": str(self.doc_root / project_name),
                "chroma_dir": str(self.chroma_root / project_name),
                "splade_dir": str(self.splade_root / project_name),
                "manifest_path": str(manifest_path),
            }
        )
        return result

    def import_files_to_project(
        self,
        project_name: str,
        *,
        uploaded_files: Iterable[Any] | None = None,
    ) -> dict[str, Any]:
        project_name = self._normalize_project_name(project_name)
        self.create_project(project_name)

        target_dir = self.doc_root / project_name
        allowed_suffixes = {".txt", ".md"}

        copied_files: list[str] = []
        rejected_files: list[str] = []

        for uploaded in uploaded_files or []:
            filename = Path(getattr(uploaded, "name", "")).name
            if not filename:
                continue

            if Path(filename).suffix.lower() not in allowed_suffixes:
                rejected_files.append(f"{filename}  [only .txt/.md allowed]")
                continue

            dst = target_dir / filename
            with dst.open("wb") as f:
                f.write(uploaded.getbuffer())
            copied_files.append(dst.name)

        if not copied_files:
            return {
                "success": False,
                "project_name": project_name,
                "copied_files": [],
                "copied_count": 0,
                "rejected_files": rejected_files,
                "message": "No valid .txt or .md files were added.",
            }

        ingest_result = self.ingest_project(project_name)
        ingest_result.update(
            {
                "copied_files": copied_files,
                "copied_count": len(copied_files),
                "rejected_files": rejected_files,
            }
        )
        return ingest_result

    def get_embedded_files(self, project_name: str) -> dict[str, Any]:
        project_name = self._normalize_project_name(project_name)
        manifest_path = self.chroma_root / project_name / "file_manifest.json"

        if not manifest_path.exists():
            return {
                "success": True,
                "project_name": project_name,
                "manifest_path": str(manifest_path),
                "files": [],
            }

        try:
            with manifest_path.open("r", encoding="utf-8") as f:
                manifest_data = json.load(f)

            records: list[dict[str, Any]] = []

            if isinstance(manifest_data, dict):
                manifest_records = manifest_data.get("files")

                if isinstance(manifest_records, list):
                    records = [r for r in manifest_records if isinstance(r, dict)]
                elif isinstance(manifest_records, dict):
                    records = [r for r in manifest_records.values() if isinstance(r, dict)]
                elif all(isinstance(v, dict) for v in manifest_data.values()):
                    records = [r for r in manifest_data.values() if isinstance(r, dict)]

            elif isinstance(manifest_data, list):
                records = [r for r in manifest_data if isinstance(r, dict)]

            file_names: list[str] = []
            for record in records:
                record_path = str(record.get("path", "")).strip()
                if record_path:
                    file_names.append(Path(record_path).name)

            unique_sorted_files = sorted(set(file_names), key=str.lower)

            return {
                "success": True,
                "project_name": project_name,
                "manifest_path": str(manifest_path),
                "files": unique_sorted_files,
            }

        except Exception as e:
            return {
                "success": False,
                "project_name": project_name,
                "manifest_path": str(manifest_path),
                "files": [],
                "message": str(e),
            }

    def reload_runtime_config(self) -> dict[str, Any]:
        """
        Reload runtime_config.json.

        Useful during development when limits are changed without restarting
        the whole app process.
        """
        self.runtime_config = self._load_runtime_config()
        return self.runtime_config

    def _load_runtime_config(self) -> dict[str, Any]:
        """
        Load runtime_config.json.

        If the file is missing or invalid, return an empty dictionary so the
        stage defaults inside retrieval components can still run.
        """
        if not self.runtime_config_path.exists():
            logger(
                f"runtime_config.json not found: {self.runtime_config_path}",
                "WARN",
                "PUBLIC",
            )
            return {}

        try:
            with self.runtime_config_path.open("r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                raise ValueError("runtime_config.json root must be a JSON object.")

            logger(
                "runtime_config.json loaded.",
                "INFO",
                "INTERNAL",
            )

            return data

        except Exception as e:
            logger(
                f"Failed to load runtime_config.json: {e}",
                "ERROR",
                "PUBLIC",
            )
            return {}

    @staticmethod
    def _normalize_project_name(project_name: str) -> str:
        name = (project_name or "").strip()
        if not name:
            raise ValueError("Project name must not be empty.")
        if "/" in name or "\\" in name:
            raise ValueError("Project name must not contain path separators.")
        if name in {".", ".."} or ".." in name:
            raise ValueError("Project name must not contain relative path markers.")
        return name