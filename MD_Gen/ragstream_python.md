# Python Files Index (ragstream)

## /home/rusbeh_ab/project/RAGstream/ragstream/app

### ~\ragstream\app\agents.py
```python
"""
Agents (A1..A4)
===============
- A1 Deterministic Code Injector → builds ❖ FILES and enforces Exact File Lock.
- A2 Prompt Shaper → pass-1 propose headers; audit-2 may trigger one retrieval re-run on scope change.
- A3 NLI Gate → keep/drop via entailment (θ strictness).
- A4 Condenser → emits S_ctx (Facts / Constraints / Open Issues) with citations.
"""
from typing import List, Dict

class A1_DCI:
    def build_files_block(self, named_files: List[str], lock: bool) -> str:
        return "❖ FILES\n"

class A2_PromptShaper:
    def propose(self, question: str) -> Dict[str, str]:
        return {"intent": "explain", "domain": "software", "headers": "H"}
    def audit_and_rerun(self, shape: Dict[str, str], s_ctx: List[str]) -> bool:
        """
        Return True iff audit materially changes task scope (intent/domain),
        allowing exactly one retrieval→A3→A4 re-run.
        """
        return False

class A3_NLIGate:
    def __init__(self, theta: float = 0.6) -> None:
        self.theta = theta
    def filter(self, candidates: List[str], question: str) -> List[str]:
        return candidates

class A4_Condenser:
    def condense(self, kept: List[str]) -> List[str]:
        return ["Facts:", "Constraints:", "Open Issues:"]
```

### ~\ragstream\app\controller.py
```python
# ragstream/app/controller.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import json

from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from ragstream.orchestration.super_prompt import SuperPrompt
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

        # MemoryRetriever is configured by ui_streamlit.py after memory objects exist.
        self.memory_retriever: MemoryRetriever | None = None

    def initialize_heavy_components(self) -> None:
        """
        Heavy initialization only.

        - Creates the document Retrieval stage object.
        - Creates the document ReRanker stage object.
        """

        self.retriever = Retriever(
            doc_root=str(self.doc_root),
            chroma_root=str(self.chroma_root),
            runtime_config=self.runtime_config,
        )

        self.reranker = Reranker()

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

        sp.compose_prompt_ready()

        logger("PreProcessing completed.", "INFO", "PUBLIC")
        return sp

    def run_a2_promptshaper(
        self,
        sp: SuperPrompt,
        *,
        use_llm: bool = True,
    ) -> SuperPrompt:
        """Run A2 on the current SuperPrompt."""
        return self.a2_promptshaper.run(
            sp,
            use_llm=bool(use_llm),
        )

    def run_a3(self, sp: SuperPrompt) -> SuperPrompt:
        """
        Run A3 on the current SuperPrompt.
        """
        return self.a3_nli_gate.run(sp)

    def run_a4(
        self,
        sp: SuperPrompt,
        *,
        effective_output_token_limit: int | None = None,
    ) -> SuperPrompt:
        """
        Run A4 on the current SuperPrompt.
        """
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
```

### ~\ragstream\app\controller_legacy.py
```python
"""
AppController
=============
Controller orchestrates A1..A4 with ConversationMemory and the retrieval path.
- Exact File Lock short-circuits retrieval.
- A2 runs twice (propose → audit); at most one retrieval re-run on scope change.
"""
from typing import List
from ragstream.retrieval.retriever import Retriever, DocScore
from ragstream.retrieval.reranker import Reranker
from ragstream.orchestration.prompt_builder import PromptBuilder
from ragstream.orchestration.llm_client import LLMClient
from ragstream.app.agents import A1_DCI, A2_PromptShaper, A3_NLIGate, A4_Condenser
from ragstream.memory.conversation_memory import ConversationMemory

class AppController:
    def __init__(self) -> None:
        self.retriever = Retriever()
        self.reranker = Reranker()
        self.prompt_builder = PromptBuilder()
        self.llm_client = LLMClient()
        self.a1 = A1_DCI()
        self.a2 = A2_PromptShaper()
        self.a3 = A3_NLIGate()
        self.a4 = A4_Condenser()
        self.convmem = ConversationMemory()
        self.eligibility_pool = set()  # ON/OFF file gating handled by UI/controller

    def handle(self, user_prompt: str, named_files: List[str], exact_lock: bool) -> str:
        # A2 pass-1
        _shape = self.a2.propose(user_prompt)

        # A1 — ❖ FILES
        files_block = self.a1.build_files_block(named_files, exact_lock)

        # Retrieval path (skip if lock)
        kept_chunks: List[str] = []
        if not exact_lock:
            results: List[DocScore] = self.retriever.retrieve(user_prompt, k=10)
            ids = [r.id for r in results]
            kept_chunks = self.a3.filter(ids, user_prompt)

        # A4 — condense to S_ctx
        s_ctx = self.a4.condense(kept_chunks)

        # A2 audit-2 (may trigger one re-run on scope change)
        if self.a2.audit_and_rerun(_shape, s_ctx) and not exact_lock:
            results = self.retriever.retrieve(user_prompt, k=10)
            ids = [r.id for r in results]
            kept_chunks = self.a3.filter(ids, user_prompt)
            s_ctx = self.a4.condense(kept_chunks)

        # Compose & send
        prompt = self.prompt_builder.build(user_prompt, files_block, s_ctx, shape=_shape)
        return self.llm_client.complete(prompt)
```

### ~\ragstream\app\Hook_ChatGTP.py
```python
# Hook_ChatGTP.py
# Logic:
# - attach to an already running Chrome/Chromium via CDP
# - identify the active ChatGPT tab
# - optionally write a message into the composer
# - optionally send it
# - read the latest assistant message from the page

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import sys

from playwright.sync_api import sync_playwright, Page, Locator


CDP_URL = "http://127.0.0.1:9222"
MESSAGE_TEXT = "hello, how are you"


@dataclass
class TabInfo:
    page: Page
    url: str
    title: str
    has_focus: bool
    visibility_state: str


def _safe_title(page: Page) -> str:
    try:
        return page.title()
    except Exception:
        return ""


def _safe_has_focus(page: Page) -> bool:
    try:
        return bool(page.evaluate("document.hasFocus()"))
    except Exception:
        return False


def _safe_visibility(page: Page) -> str:
    try:
        value = page.evaluate("document.visibilityState")
        return str(value) if value is not None else ""
    except Exception:
        return ""


def _is_chatgpt_tab(page: Page) -> bool:
    url = (page.url or "").lower()
    return ("chatgpt.com" in url) or ("chat.openai.com" in url)


def _score_tab(info: TabInfo) -> int:
    score = 0

    if info.has_focus:
        score += 100
    if info.visibility_state == "visible":
        score += 50

    url_lower = info.url.lower()
    title_lower = info.title.lower()

    if "/c/" in url_lower:
        score += 20
    if "chatgpt" in title_lower or "rag" in title_lower:
        score += 10

    return score


def _find_active_chatgpt_tab(browser) -> Optional[TabInfo]:
    candidates: list[TabInfo] = []

    for context in browser.contexts:
        for page in context.pages:
            if not _is_chatgpt_tab(page):
                continue

            info = TabInfo(
                page=page,
                url=page.url or "",
                title=_safe_title(page),
                has_focus=_safe_has_focus(page),
                visibility_state=_safe_visibility(page),
            )
            candidates.append(info)

    if not candidates:
        return None

    candidates.sort(key=_score_tab, reverse=True)
    return candidates[0]


def _first_working_locator(page: Page) -> Optional[Locator]:
    candidates = [
        page.get_by_role("textbox").last,
        page.locator("textarea").last,
        page.locator('[contenteditable="true"]').last,
    ]

    for locator in candidates:
        try:
            locator.wait_for(state="visible", timeout=1500)
            if locator.is_visible(timeout=1500):
                return locator
        except Exception:
            pass

    return None


def _last_visible_assistant_message(page: Page) -> Optional[Locator]:
    selectors = [
        'div[data-message-author-role="assistant"]',
        'article [data-message-author-role="assistant"]',
        '[data-message-author-role="assistant"]',
    ]

    for selector in selectors:
        locator = page.locator(selector)

        try:
            count = locator.count()
        except Exception:
            count = 0

        if count == 0:
            continue

        for i in range(count - 1, -1, -1):
            item = locator.nth(i)
            try:
                if item.is_visible(timeout=1000):
                    return item
            except Exception:
                pass

    return None


def get_last_assistant_message(page: Page) -> Optional[str]:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=3000)
    except Exception:
        pass

    try:
        page.wait_for_timeout(700)
    except Exception:
        pass

    message = _last_visible_assistant_message(page)
    if message is None:
        return None

    try:
        text = message.inner_text(timeout=2000).strip()
        return text if text else None
    except Exception:
        return None


def _write_into_composer(page: Page, text: str, submit: bool = False) -> bool:
    locator = _first_working_locator(page)
    if locator is None:
        return False

    try:
        locator.click(timeout=3000)

        try:
            locator.fill("")
        except Exception:
            try:
                locator.press("Control+A")
                locator.press("Backspace")
            except Exception:
                pass

        try:
            locator.fill(text, timeout=3000)
        except Exception:
            locator.press_sequentially(text, delay=20)

        if submit:
            locator.press("Enter")

        return True

    except Exception:
        return False

def wait_for_last_assistant_message_ready(
    page: Page,
    timeout_ms: int = 120000,
    poll_ms: int = 400,
    stable_rounds: int = 4,
) -> Optional[str]:
    start = page.evaluate("Date.now()")
    last_text = None
    stable_count = 0

    while True:
        now = page.evaluate("Date.now()")
        if now - start > timeout_ms:
            return last_text.strip() if last_text and last_text.strip() else None

        message = _last_visible_assistant_message(page)
        if message is None:
            page.wait_for_timeout(poll_ms)
            continue

        try:
            current_text = message.inner_text(timeout=1500).strip()
        except Exception:
            current_text = ""

        if current_text and current_text == last_text:
            stable_count += 1
        else:
            stable_count = 0
            last_text = current_text

        if current_text and stable_count >= stable_rounds:
            return current_text

        page.wait_for_timeout(poll_ms)


def run() -> None:
    text_to_send: Optional[str] = None
    if len(sys.argv) >= 2:
        text_to_send = " ".join(sys.argv[1:]).strip()
        if not text_to_send:
            print("Text argument was provided but is empty.")
            sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        try:
            tab = _find_active_chatgpt_tab(browser)

            if tab is None:
                print("No ChatGPT tab was found through CDP.")
                print("Most likely reason: the special Chrome window is not open.")
                sys.exit(2)

            print("FOUND ACTIVE CHATGPT TAB")
            print(f"URL   : {tab.url}")
            print(f"TITLE : {tab.title}")
            print(f"FOCUS : {tab.has_focus}")
            print(f"VIS   : {tab.visibility_state}")
            print()

            if text_to_send is not None:
                ok = _write_into_composer(tab.page, text_to_send, submit=True)

                if not ok:
                    print("ACTIVE TAB WAS FOUND, BUT COMPOSER COULD NOT BE DETECTED")
                    sys.exit(3)

                print("TEXT WRITTEN INTO CHATGPT COMPOSER")
                print("MESSAGE WAS SENT")
                print()

                # Small wait so the page can start updating.
                try:
                    tab.page.wait_for_timeout(2500)
                except Exception:
                    pass

            last_message = wait_for_last_assistant_message_ready(tab.page)

            print("LAST ASSISTANT MESSAGE:")
            if last_message:
                print(last_message)
            else:
                print("(not found)")

        finally:
            browser.close()


if __name__ == "__main__":
    run()
```

### ~\ragstream\app\Hook_ChatGTP2.py
```python
# Hook_ChatGTP.py
# Logic:
# - attach to an already running Chrome/Chromium via CDP
# - identify the active ChatGPT tab
# - locate the composer box
# - write dynamic text into the box
# - do NOT send anything

from __future__ import annotations

import sys

from dataclasses import dataclass
from typing import Optional

from playwright.sync_api import sync_playwright, Page, Locator


CDP_URL = "http://127.0.0.1:9222"


@dataclass
class TabInfo:
    page: Page
    url: str
    title: str
    has_focus: bool
    visibility_state: str


def _safe_title(page: Page) -> str:
    try:
        return page.title()
    except Exception:
        return ""


def _safe_has_focus(page: Page) -> bool:
    try:
        return bool(page.evaluate("document.hasFocus()"))
    except Exception:
        return False


def _safe_visibility(page: Page) -> str:
    try:
        value = page.evaluate("document.visibilityState")
        return str(value) if value is not None else ""
    except Exception:
        return ""


def _is_chatgpt_tab(page: Page) -> bool:
    url = (page.url or "").lower()
    return ("chatgpt.com" in url) or ("chat.openai.com" in url)


def _score_tab(info: TabInfo) -> int:
    score = 0

    if info.has_focus:
        score += 100
    if info.visibility_state == "visible":
        score += 50

    url_lower = info.url.lower()
    title_lower = info.title.lower()

    if "/c/" in url_lower:
        score += 20
    if "chatgpt" in title_lower or "rag" in title_lower:
        score += 10

    return score


def _find_active_chatgpt_tab(browser) -> Optional[TabInfo]:
    candidates: list[TabInfo] = []

    for context in browser.contexts:
        for page in context.pages:
            if not _is_chatgpt_tab(page):
                continue

            info = TabInfo(
                page=page,
                url=page.url or "",
                title=_safe_title(page),
                has_focus=_safe_has_focus(page),
                visibility_state=_safe_visibility(page),
            )
            candidates.append(info)

    if not candidates:
        return None

    candidates.sort(key=_score_tab, reverse=True)
    return candidates[0]


def _first_working_locator(page: Page) -> Optional[Locator]:
    candidates = [
        page.get_by_role("textbox").last,
        page.locator("textarea").last,
        page.locator('[contenteditable="true"]').last,
    ]

    for locator in candidates:
        try:
            locator.wait_for(state="visible", timeout=1500)
            if locator.is_visible(timeout=1500):
                return locator
        except Exception:
            pass

    return None


def _write_into_composer(page: Page, text: str, submit: bool = False) -> bool:
    locator = _first_working_locator(page)
    if locator is None:
        return False

    try:
        locator.click(timeout=3000)

        try:
            locator.fill("")
        except Exception:
            try:
                locator.press("Control+A")
                locator.press("Backspace")
            except Exception:
                pass

        try:
            locator.fill(text, timeout=3000)
        except Exception:
            locator.press_sequentially(text, delay=20)

        if submit:
            locator.press("Enter")

        return True

    except Exception:
        return False


def write_text_to_active_chatgpt(text: str) -> bool:
    if not text or not text.strip():
        raise ValueError("Text must not be empty.")

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        try:
            tab = _find_active_chatgpt_tab(browser)

            if tab is None:
                print("No ChatGPT tab was found through CDP.")
                print("Most likely reason: the special Chrome window is not open.")
                return False

            print("FOUND ACTIVE CHATGPT TAB")
            print(f"URL   : {tab.url}")
            print(f"TITLE : {tab.title}")
            print(f"FOCUS : {tab.has_focus}")
            print(f"VIS   : {tab.visibility_state}")

            ok = _write_into_composer(tab.page, text, submit=True)

            if ok:
                print("TEXT WRITTEN INTO CHATGPT COMPOSER")
                print("MESSAGE WAS NOT SENT")
                return True

            print("ACTIVE TAB WAS FOUND, BUT COMPOSER COULD NOT BE DETECTED")
            return False

        finally:
            browser.close()


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python Hook_ChatGTP.py "your text here"')
        sys.exit(1)

    text = " ".join(sys.argv[1:])
    ok = write_text_to_active_chatgpt(text)

    if not ok:
        sys.exit(2)


if __name__ == "__main__":
    main()
```

### ~\ragstream\app\pipeline_runner.py
```python
# ragstream/app/pipeline_runner.py
# -*- coding: utf-8 -*-
"""
Step-wise pipeline runner for the Prompt Builder button.

Runs the current document-RAG pipeline automatically, one stage per Streamlit
rerun cycle:

PreProcessing
→ A2 PromptShaper
→ Retrieval
→ ReRanker
→ A3 NLI Gate
→ A4 Condenser

This file contains execution sequencing only.
It does not render the GUI layout.
It does not own Streamlit widgets.
It does not implement stage logic.
"""

from __future__ import annotations

import copy
from typing import Any, Callable

from ragstream.app.controller import AppController
from ragstream.orchestration.super_prompt import SuperPrompt


PIPELINE_STEPS: list[str] = [
    "Pre-Processing",
    "A2-PromptShaper",
    "Retrieval",
    "ReRanker",
    "A3 NLI Gate",
    "A4 Condenser",
]

PIPELINE_TOTAL_STEPS: int = len(PIPELINE_STEPS)


def pipeline_stage_name(step_index: int) -> str:
    """Return the display name for one Prompt Builder pipeline step."""
    if 0 <= int(step_index) < PIPELINE_TOTAL_STEPS:
        return PIPELINE_STEPS[int(step_index)]
    return "Done"


def run_prompt_builder_stage(
    *,
    step_index: int,
    ctrl: AppController,
    sp: SuperPrompt | None,
    user_text: str,
    project_name: str,
    top_k: int,
    use_a2_promptshaper_llm: bool,
    use_retrieval_splade: bool,
    use_reranking_colbert: bool,
    memory_manager: Any | None = None,
    ensure_memory_retrieval_configured: Callable[[AppController], None] | None = None,
) -> dict[str, Any]:
    """
    Run exactly one Prompt Builder pipeline stage.

    Return shape:
        {
            "sp": SuperPrompt,
            "snapshots": {
                "sp_pre": SuperPrompt,
                ...
            }
        }
    """
    clean_user_text = str(user_text or "").strip()
    if not clean_user_text:
        raise ValueError("Prompt is empty. Prompt Builder cannot run.")

    clean_project_name = str(project_name or "").strip()
    if not clean_project_name or clean_project_name == "(no projects yet)":
        raise ValueError("No active project is available for Prompt Builder.")

    idx = int(step_index)
    snapshots: dict[str, SuperPrompt] = {}

    if idx == 0:
        current_sp = SuperPrompt()

        current_sp = ctrl.preprocess(
            clean_user_text,
            current_sp,
            memory_manager=memory_manager,
        )

        snapshots["sp_pre"] = copy.deepcopy(current_sp)

        return {
            "sp": current_sp,
            "snapshots": snapshots,
        }

    if sp is None:
        raise ValueError("Prompt Builder internal state error: SuperPrompt is missing.")

    current_sp = sp

    if idx == 1:
        current_sp = ctrl.run_a2_promptshaper(
            current_sp,
            use_llm=bool(use_a2_promptshaper_llm),
        )

        snapshots["sp_a2"] = copy.deepcopy(current_sp)

        return {
            "sp": current_sp,
            "snapshots": snapshots,
        }

    if idx == 2:
        if ensure_memory_retrieval_configured is not None:
            ensure_memory_retrieval_configured(ctrl)

        current_sp = ctrl.run_retrieval(
            current_sp,
            clean_project_name,
            int(top_k),
            use_retrieval_splade=bool(use_retrieval_splade),
        )

        current_sp.compose_prompt_ready()

        snapshots["sp_rtv"] = copy.deepcopy(current_sp)

        # Retrieval initializes an A3-ready passthrough reranked view.
        # This snapshot remains valid until the real ReRanker overwrites it.
        snapshots["sp_rrk"] = copy.deepcopy(current_sp)

        return {
            "sp": current_sp,
            "snapshots": snapshots,
        }

    if idx == 3:
        if bool(use_reranking_colbert):
            current_sp = ctrl.run_reranker(
                current_sp,
                use_reranking_colbert=True,
            )
        else:
            # ColBERT is disabled.
            # Retrieval already created an A3-ready passthrough view under
            # views_by_stage["reranked"], so ReRanker is intentionally skipped.
            current_sp.compose_prompt_ready()

        snapshots["sp_rrk"] = copy.deepcopy(current_sp)

        return {
            "sp": current_sp,
            "snapshots": snapshots,
        }

    if idx == 4:
        current_sp = ctrl.run_a3(current_sp)

        snapshots["sp_a3"] = copy.deepcopy(current_sp)

        return {
            "sp": current_sp,
            "snapshots": snapshots,
        }

    if idx == 5:
        current_sp = ctrl.run_a4(current_sp)
        current_sp.compose_prompt_ready()

        snapshots["sp_a4"] = copy.deepcopy(current_sp)

        return {
            "sp": current_sp,
            "snapshots": snapshots,
        }

    raise ValueError(f"Unknown Prompt Builder pipeline step_index: {step_index}")
```

### ~\ragstream\app\ui_actions.py
```python
# ragstream/app/ui_actions.py
# -*- coding: utf-8 -*-
"""
Small callback helpers for Streamlit button/form actions.
Keep controller calls and session-state mutations here.
"""

from __future__ import annotations

import copy
import time

from typing import Any

import streamlit as st

from ragstream.app.controller import AppController
from ragstream.app.pipeline_runner import (
    PIPELINE_TOTAL_STEPS,
    pipeline_stage_name,
    run_prompt_builder_stage,
)
from ragstream.memory.memory_actions import capture_memory_pair
from ragstream.memory.memory_manager import MemoryManager
from ragstream.orchestration.super_prompt import SuperPrompt
from ragstream.textforge.RagLog import LogALL as logger


SIDEBAR_PIPELINE_TOTAL_STEPS = 8
SIDEBAR_MIN_VISIBLE_SECONDS = 1.0

SIDEBAR_STEP_USER_PROMPT = 0
SIDEBAR_STEP_PROMPT_QUALIFICATION = 1
SIDEBAR_STEP_PROMPT_SHAPING = 2
SIDEBAR_STEP_MEMORY_CONTEXT = 3
SIDEBAR_STEP_DOCUMENT_EVIDENCE = 4
SIDEBAR_STEP_CONTEXT_SYNTHESIS = 5
SIDEBAR_STEP_HARD_RULE_INTEGRATION = 6
SIDEBAR_STEP_LLM_READY_CONTEXT = 7

PROMPT_BUILDER_VISUAL_TAIL = [
    ("Hard Rule Integration", SIDEBAR_STEP_HARD_RULE_INTEGRATION, 0.0),
    ("LLM-Ready Context", SIDEBAR_STEP_LLM_READY_CONTEXT, 0.0),
]


def _set_sidebar_pipeline_visual_step(
    active_step: int,
    completed_step: int | None = None,
) -> None:
    active_step = max(0, min(int(active_step), SIDEBAR_PIPELINE_TOTAL_STEPS - 1))

    if completed_step is None:
        completed_step = active_step - 1

    completed_step = max(-1, min(int(completed_step), SIDEBAR_PIPELINE_TOTAL_STEPS - 1))

    st.session_state["sidebar_pipeline_active_step"] = active_step
    st.session_state["sidebar_pipeline_completed_step"] = completed_step
    st.session_state["sidebar_pipeline_active_since"] = time.monotonic()


def _hold_sidebar_active_step_minimum() -> None:
    started_at = st.session_state.get("sidebar_pipeline_active_since")

    if started_at is None:
        st.session_state["sidebar_pipeline_active_since"] = time.monotonic()
        return

    elapsed = time.monotonic() - float(started_at)
    remaining = SIDEBAR_MIN_VISIBLE_SECONDS - elapsed

    if remaining > 0:
        time.sleep(float(remaining))


def _sidebar_visual_step_for_stage(
    stage_name: str,
    step_index: int,
) -> int:
    name = str(stage_name or "").lower()

    if "pre" in name:
        return SIDEBAR_STEP_PROMPT_QUALIFICATION

    if "a2" in name or "promptshaper" in name or "prompt shaper" in name:
        return SIDEBAR_STEP_PROMPT_SHAPING

    if "retrieval" in name or "retriever" in name:
        return SIDEBAR_STEP_MEMORY_CONTEXT

    if "rerank" in name:
        return SIDEBAR_STEP_MEMORY_CONTEXT

    if "a3" in name or "nli" in name:
        return SIDEBAR_STEP_DOCUMENT_EVIDENCE

    if "a4" in name or "condenser" in name or "condense" in name:
        return SIDEBAR_STEP_CONTEXT_SYNTHESIS

    fallback_map = {
        0: SIDEBAR_STEP_PROMPT_QUALIFICATION,
        1: SIDEBAR_STEP_PROMPT_SHAPING,
        2: SIDEBAR_STEP_MEMORY_CONTEXT,
        3: SIDEBAR_STEP_MEMORY_CONTEXT,
        4: SIDEBAR_STEP_DOCUMENT_EVIDENCE,
        5: SIDEBAR_STEP_CONTEXT_SYNTHESIS,
    }

    return fallback_map.get(int(step_index), SIDEBAR_STEP_LLM_READY_CONTEXT)


def _run_prompt_builder_visual_tail() -> None:
    tail_index = int(st.session_state.get("pipeline_visual_tail_index", 0) or 0)

    if tail_index >= len(PROMPT_BUILDER_VISUAL_TAIL):
        st.session_state["pipeline_running"] = False
        st.session_state["pipeline_stage_armed"] = False
        st.session_state["pipeline_visual_tail_index"] = 0

        _set_sidebar_pipeline_visual_step(
            SIDEBAR_STEP_LLM_READY_CONTEXT,
            SIDEBAR_STEP_HARD_RULE_INTEGRATION,
        )

        _set_pipeline_status(
            stage_name="Done",
            step_index=SIDEBAR_PIPELINE_TOTAL_STEPS,
            total_steps=SIDEBAR_PIPELINE_TOTAL_STEPS,
            message="Prompt Builder pipeline completed.",
        )
        return

    stage_name, visual_step, wait_seconds = PROMPT_BUILDER_VISUAL_TAIL[tail_index]

    if not bool(st.session_state.get("pipeline_stage_armed", False)):
        _set_sidebar_pipeline_visual_step(visual_step)

        _set_pipeline_status(
            stage_name=stage_name,
            step_index=visual_step + 1,
            total_steps=SIDEBAR_PIPELINE_TOTAL_STEPS,
            message=f"Running {stage_name}.",
        )

        st.session_state["pipeline_stage_armed"] = True
        st.rerun()

    if wait_seconds > 0:
        time.sleep(float(wait_seconds))

    st.session_state["pipeline_visual_tail_index"] = tail_index + 1
    st.session_state["pipeline_stage_armed"] = False

    if tail_index + 1 >= len(PROMPT_BUILDER_VISUAL_TAIL):
        st.session_state["pipeline_running"] = False

        _set_sidebar_pipeline_visual_step(
            SIDEBAR_STEP_LLM_READY_CONTEXT,
            SIDEBAR_STEP_HARD_RULE_INTEGRATION,
        )

        _set_pipeline_status(
            stage_name="Done",
            step_index=SIDEBAR_PIPELINE_TOTAL_STEPS,
            total_steps=SIDEBAR_PIPELINE_TOTAL_STEPS,
            message="Prompt Builder pipeline completed.",
        )

        logger(
            "Prompt Builder finished.",
            "INFO",
            "PUBLIC",
        )

    st.rerun()


def _pipeline_is_running() -> bool:
    return bool(st.session_state.get("pipeline_running", False))


def _guard_pipeline_running(action_name: str) -> bool:
    """
    Logical execution lock only.

    This does not disable or grey out widgets.
    It only prevents another action from being executed while the full
    Prompt Builder pipeline is already running.
    """
    if not _pipeline_is_running():
        return False

    logger(
        f"{action_name} ignored: Prompt Builder pipeline is running.",
        "WARN",
        "PUBLIC",
    )
    return True


def _set_pipeline_status(
    stage_name: str,
    step_index: int,
    total_steps: int,
    message: str,
) -> None:
    progress = 0.0
    if total_steps > 0:
        progress = max(0.0, min(1.0, float(step_index) / float(total_steps)))

    st.session_state["pipeline_status"] = {
        "stage_name": stage_name,
        "step_index": int(step_index),
        "total_steps": int(total_steps),
        "message": message,
        "progress": progress,
    }

def do_user_prompt_changed() -> None:
    st.session_state["pipeline_running"] = False
    st.session_state["pipeline_stage_armed"] = False
    st.session_state["pipeline_stage_index"] = 0
    st.session_state["pipeline_visual_tail_index"] = 0

    _set_sidebar_pipeline_visual_step(
        SIDEBAR_STEP_USER_PROMPT,
        -1,
    )

    _set_pipeline_status(
        stage_name="User Prompt",
        step_index=1,
        total_steps=SIDEBAR_PIPELINE_TOTAL_STEPS,
        message="User prompt changed.",
    )

def request_prompt_builder_run() -> None:
    """
    Start the Prompt Builder state machine.

    The pipeline is executed one stage per Streamlit rerun. This keeps the GUI
    visually normal between stages and avoids one long blocking callback.
    """
    if _guard_pipeline_running("Prompt Builder"):
        return

    try:
        ctrl: AppController = st.session_state.controller

        user_text = str(st.session_state.get("prompt_text", "") or "").strip()
        if not user_text:
            logger(
                "Prompt Builder cannot run because Prompt is empty.",
                "WARN",
                "PUBLIC",
            )
            st.error("Prompt is empty. Prompt Builder cannot run.")
            return

        project_name = _resolve_active_project(ctrl)
        top_k = int(st.session_state.get("retrieval_top_k", 100))

        use_a2_promptshaper_llm = bool(st.session_state.get("use_a2_promptshaper_llm", True))
        use_retrieval_splade = bool(st.session_state.get("use_retrieval_splade", False))
        use_reranking_colbert = bool(st.session_state.get("use_reranking_colbert", False))
        st.session_state.sp = SuperPrompt()
        st.session_state.sp_pre = SuperPrompt()
        st.session_state.sp_a2 = SuperPrompt()
        st.session_state.sp_rtv = SuperPrompt()
        st.session_state.sp_rrk = SuperPrompt()
        st.session_state.sp_a3 = SuperPrompt()
        st.session_state.sp_a4 = SuperPrompt()
        st.session_state["super_prompt_text"] = ""

        _set_sidebar_pipeline_visual_step(
            SIDEBAR_STEP_USER_PROMPT,
            -1,
        )

        st.session_state["pipeline_running"] = True
        st.session_state["pipeline_stage_index"] = 0
        st.session_state["pipeline_stage_armed"] = False
        st.session_state["pipeline_visual_tail_index"] = 0
        st.session_state["pipeline_config"] = {
            "user_text": user_text,
            "project_name": project_name,
            "top_k": top_k,
            "use_a2_promptshaper_llm": use_a2_promptshaper_llm,
            "use_retrieval_splade": use_retrieval_splade,
            "use_reranking_colbert": use_reranking_colbert,
        }

        _set_pipeline_status(
            stage_name="Queued",
            step_index=0,
            total_steps=SIDEBAR_PIPELINE_TOTAL_STEPS,
            message="Prompt Builder pipeline queued.",
        )

        logger(
            (
                "Prompt Builder started: "
                f"A2_LLM={use_a2_promptshaper_llm}, "
                f"SPLADE={use_retrieval_splade}, "
                f"ColBERT={use_reranking_colbert}, "
                f"top_k={top_k}, "
                f"project={project_name}"
            ),
            "INFO",
            "PUBLIC",
        )

        st.rerun()

    except Exception as e:
        logger(str(e), "ERROR", "PUBLIC")
        st.error(str(e))


def run_next_prompt_builder_step() -> None:
    """
    Advance the Prompt Builder pipeline state machine by one visual/execution phase.

    Two-phase logic per stage:
    1. Arm phase:
       - write status for the next stage
       - rerun so the user sees that status before the stage starts
    2. Execute phase:
       - run exactly one pipeline stage
       - write SuperPrompt / snapshots
       - rerun to expose logs and move to the next stage
    """
    if not _pipeline_is_running():
        return

    _hold_sidebar_active_step_minimum()

    step_index = int(st.session_state.get("pipeline_stage_index", 0) or 0)

    if step_index >= PIPELINE_TOTAL_STEPS:
        _run_prompt_builder_visual_tail()
        return

    stage_name = pipeline_stage_name(step_index)

    if not bool(st.session_state.get("pipeline_stage_armed", False)):
        visual_step = _sidebar_visual_step_for_stage(
            stage_name=stage_name,
            step_index=step_index,
        )

        _set_sidebar_pipeline_visual_step(visual_step)

        _set_pipeline_status(
            stage_name=stage_name,
            step_index=visual_step + 1,
            total_steps=SIDEBAR_PIPELINE_TOTAL_STEPS,
            message=f"Running {stage_name}.",
        )
        st.session_state["pipeline_stage_armed"] = True
        st.rerun()

    try:
        ctrl: AppController = st.session_state.controller
        config = st.session_state.get("pipeline_config", {}) or {}

        current_sp = st.session_state.get("sp")
        if not isinstance(current_sp, SuperPrompt):
            current_sp = None

        logger(
            f"Prompt Builder stage running: {step_index + 1}/{PIPELINE_TOTAL_STEPS} — {stage_name}",
            "INFO",
            "PUBLIC",
        )

        result = run_prompt_builder_stage(
            step_index=step_index,
            ctrl=ctrl,
            sp=current_sp,
            user_text=str(config.get("user_text", "") or ""),
            project_name=str(config.get("project_name", "") or ""),
            top_k=int(config.get("top_k", st.session_state.get("retrieval_top_k", 100)) or 100),
            use_a2_promptshaper_llm=bool(config.get("use_a2_promptshaper_llm", True)),
            use_retrieval_splade=bool(config.get("use_retrieval_splade", False)),
            use_reranking_colbert=bool(config.get("use_reranking_colbert", False)),
            memory_manager=st.session_state.get("memory_manager"),
            ensure_memory_retrieval_configured=_ensure_memory_retrieval_configured,
        )

        sp: SuperPrompt = result["sp"]
        snapshots: dict[str, SuperPrompt] = result.get("snapshots", {}) or {}

        st.session_state.sp = sp

        for snapshot_key, snapshot_value in snapshots.items():
            st.session_state[snapshot_key] = snapshot_value

        st.session_state["super_prompt_text"] = sp.prompt_ready

        logger(
            f"Prompt Builder stage finished: {step_index + 1}/{PIPELINE_TOTAL_STEPS} — {stage_name}",
            "INFO",
            "PUBLIC",
        )

        next_step_index = step_index + 1
        st.session_state["pipeline_stage_index"] = next_step_index
        st.session_state["pipeline_stage_armed"] = False

        if next_step_index >= PIPELINE_TOTAL_STEPS:
            st.session_state["pipeline_visual_tail_index"] = 0
            _set_pipeline_status(
                stage_name="Pipeline Tail",
                step_index=SIDEBAR_STEP_HARD_RULE_INTEGRATION + 1,
                total_steps=SIDEBAR_PIPELINE_TOTAL_STEPS,
                message="Continuing final prompt assembly.",
            )

        st.rerun()

    except Exception as e:
        st.session_state["pipeline_running"] = False
        st.session_state["pipeline_stage_armed"] = False
        _set_pipeline_status(
            stage_name="Failed",
            step_index=step_index + 1,
            total_steps=SIDEBAR_PIPELINE_TOTAL_STEPS,
            message=str(e),
        )
        logger(str(e), "ERROR", "PUBLIC")
        st.error(str(e))
        st.rerun()


def do_preprocess() -> None:
    if _guard_pipeline_running("PreProcessing"):
        return

    ctrl: AppController = st.session_state.controller
    user_text = st.session_state.get("prompt_text", "")

    # Start a fresh pipeline run from clean SuperPrompt objects.
    st.session_state.sp = SuperPrompt()
    st.session_state.sp_pre = SuperPrompt()
    st.session_state.sp_a2 = SuperPrompt()
    st.session_state.sp_rtv = SuperPrompt()
    st.session_state.sp_rrk = SuperPrompt()
    st.session_state.sp_a3 = SuperPrompt()
    st.session_state.sp_a4 = SuperPrompt()

    _set_sidebar_pipeline_visual_step(SIDEBAR_STEP_PROMPT_QUALIFICATION)

    sp: SuperPrompt = st.session_state.sp
    sp = ctrl.preprocess(
        user_text,
        sp,
        memory_manager=st.session_state.get("memory_manager"),
    )

    st.session_state.sp = sp
    st.session_state.sp_pre = copy.deepcopy(sp)
    st.session_state["super_prompt_text"] = sp.prompt_ready


def do_a2_promptshaper() -> None:
    """A2 button callback."""
    if _guard_pipeline_running("A2 PromptShaper"):
        return

    ctrl: AppController = st.session_state.controller
    sp: SuperPrompt = st.session_state.sp

    use_llm = bool(st.session_state.get("use_a2_promptshaper_llm", True))

    _set_sidebar_pipeline_visual_step(SIDEBAR_STEP_PROMPT_SHAPING)

    sp = ctrl.run_a2_promptshaper(
        sp,
        use_llm=use_llm,
    )

    st.session_state.sp = sp
    st.session_state.sp_a2 = copy.deepcopy(sp)
    st.session_state["super_prompt_text"] = sp.prompt_ready


def do_feed_memory_manually() -> None:
    """Manual memory feed button callback."""
    if _guard_pipeline_running("Manual Memory Feed"):
        return

    prompt_text = st.session_state.get("prompt_text", "")
    output_text = st.session_state.get("manual_memory_feed_text", "")

    if not (prompt_text or "").strip():
        logger("Prompt is empty. No memory record was created.", "WARN", "PUBLIC")
        return

    if not (output_text or "").strip():
        logger("Manual memory response is empty. No memory record was created.", "WARN", "PUBLIC")
        return

    _save_memory_pair(
        input_text=prompt_text,
        output_text=output_text,
    )


def _save_memory_pair(
    input_text: str,
    output_text: str,
) -> None:
    try:
        ctrl: AppController = st.session_state.controller
        memory_manager: MemoryManager = st.session_state.memory_manager

        active_project_name, embedded_files_snapshot = _get_active_project_snapshot(ctrl)
        gui_records_state = _collect_memory_gui_state(memory_manager)

        result = capture_memory_pair(
            memory_manager=memory_manager,
            input_text=input_text,
            output_text=output_text,
            source="manual_memory_feed",
            active_project_name=active_project_name,
            embedded_files_snapshot=embedded_files_snapshot,
            gui_records_state=gui_records_state,
            memory_ingestion_manager=st.session_state.get("memory_ingestion_manager"),
        )

        if result.get("success"):
            st.session_state["manual_memory_feed_text"] = ""
            st.rerun()
        else:
            logger(result.get("message", "Memory record was not saved."), "WARN", "PUBLIC")

    except Exception as e:
        logger(str(e), "ERROR", "PUBLIC")


def _get_active_project_snapshot(ctrl: AppController) -> tuple[str | None, list[str]]:
    active_project = st.session_state.get("active_project")

    if not active_project or active_project == "(no projects yet)":
        return None, []

    try:
        embedded_info = ctrl.get_embedded_files(active_project)
    except Exception:
        return active_project, []

    if embedded_info.get("success"):
        return active_project, list(embedded_info.get("files", []))

    return active_project, []


def _collect_memory_gui_state(memory_manager: MemoryManager) -> list[dict[str, Any]]:
    gui_state: list[dict[str, Any]] = []

    for record in memory_manager.records:
        tag_key = f"memory_tag_{record.record_id}"
        source_mode_key = f"memory_retrieval_source_mode_{record.record_id}"
        keywords_key = f"memory_user_keywords_{record.record_id}"
        direct_recall_key = f"memory_direct_recall_key_{record.record_id}"

        tag = st.session_state.get(tag_key, record.tag)

        retrieval_source_mode = st.session_state.get(
            source_mode_key,
            getattr(record, "retrieval_source_mode", "QA"),
        )

        user_keywords_text = st.session_state.get(
            keywords_key,
            ", ".join(record.user_keywords),
        )

        direct_recall_value = st.session_state.get(
            direct_recall_key,
            getattr(record, "direct_recall_key", ""),
        )

        gui_state.append(
            {
                "record_id": record.record_id,
                "tag": tag,
                "retrieval_source_mode": retrieval_source_mode,
                "user_keywords": _parse_user_keywords(user_keywords_text),
                "direct_recall_key": str(direct_recall_value or "").strip(),
            }
        )

    return gui_state


def _parse_user_keywords(text: str) -> list[str]:
    raw_items = str(text or "").replace("\n", ",").split(",")

    result: list[str] = []
    seen: set[str] = set()

    for item in raw_items:
        keyword = item.strip()
        if not keyword:
            continue

        key = keyword.lower()
        if key in seen:
            continue

        result.append(keyword)
        seen.add(key)

    return result


def _ensure_memory_retrieval_configured(ctrl: AppController) -> None:
    """
    Defensive wiring for development.

    ui_streamlit.py normally configures MemoryRetriever at startup.
    This helper guarantees that Retrieval button still wires memory retrieval
    if the session was created before the new startup code existed.
    """
    if getattr(ctrl, "memory_retriever", None) is not None:
        return

    memory_manager = st.session_state.get("memory_manager")
    memory_vector_store = st.session_state.get("memory_vector_store")
    runtime_config = st.session_state.get("runtime_config", {})

    if memory_manager is None or memory_vector_store is None:
        logger(
            "Memory Retrieval is not configured because memory objects are missing.",
            "WARN",
            "PUBLIC",
        )
        return

    ctrl.configure_memory_retrieval(
        memory_manager=memory_manager,
        memory_vector_store=memory_vector_store,
        runtime_config=runtime_config,
    )


def _resolve_active_project(ctrl: AppController) -> str:
    project_name = st.session_state.get("active_project")
    if not project_name:
        available_projects = ctrl.list_projects()
        if available_projects:
            project_name = available_projects[0]
            st.session_state["active_project"] = project_name

    if not project_name or project_name == "(no projects yet)":
        raise ValueError("No active project is available.")

    return str(project_name)


def do_retrieval() -> None:
    """Retrieval button callback."""
    if _guard_pipeline_running("Retrieval"):
        return

    try:
        ctrl: AppController = st.session_state.controller
        sp: SuperPrompt = st.session_state.sp

        _ensure_memory_retrieval_configured(ctrl)

        project_name = _resolve_active_project(ctrl)

        top_k = int(st.session_state.get("retrieval_top_k", 100))
        use_retrieval_splade = bool(st.session_state.get("use_retrieval_splade", False))

        _set_sidebar_pipeline_visual_step(SIDEBAR_STEP_MEMORY_CONTEXT)

        sp = ctrl.run_retrieval(
            sp,
            project_name,
            top_k,
            use_retrieval_splade=use_retrieval_splade,
        )

        sp.compose_prompt_ready()

        st.session_state.sp = sp
        st.session_state.sp_rtv = copy.deepcopy(sp)

        # Retrieval now also initializes an A3-ready passthrough view
        # under views_by_stage["reranked"].
        # Therefore sp_rrk can safely mirror this state until real ColBERT
        # ReRanker overwrites it.
        st.session_state.sp_rrk = copy.deepcopy(sp)

        st.session_state["super_prompt_text"] = sp.prompt_ready

    except Exception as e:
        st.error(str(e))


def do_reranker() -> None:
    """ReRanker button callback."""
    if _guard_pipeline_running("ReRanker"):
        return

    try:
        ctrl: AppController = st.session_state.controller
        sp: SuperPrompt = st.session_state.sp

        if getattr(ctrl, "reranker", None) is None:
            st.error("ReRanker is not initialized yet.")
            return

        use_reranking_colbert = bool(st.session_state.get("use_reranking_colbert", False))

        _set_sidebar_pipeline_visual_step(SIDEBAR_STEP_MEMORY_CONTEXT)

        sp = ctrl.run_reranker(
            sp,
            use_reranking_colbert=use_reranking_colbert,
        )

        sp.compose_prompt_ready()

        st.session_state.sp = sp
        st.session_state.sp_rrk = copy.deepcopy(sp)
        st.session_state["super_prompt_text"] = sp.prompt_ready

    except Exception as e:
        st.error(str(e))


def do_a3_nli_gate() -> None:
    """A3 button callback."""
    if _guard_pipeline_running("A3 NLI Gate"):
        return

    try:
        ctrl: AppController = st.session_state.controller
        sp: SuperPrompt = st.session_state.sp

        _set_sidebar_pipeline_visual_step(SIDEBAR_STEP_DOCUMENT_EVIDENCE)

        sp = ctrl.run_a3(sp)

        st.session_state.sp = sp
        st.session_state.sp_a3 = copy.deepcopy(sp)
        st.session_state["super_prompt_text"] = sp.prompt_ready

    except Exception as e:
        st.error(str(e))


def do_a4_condenser() -> None:
    """A4 button callback."""
    if _guard_pipeline_running("A4 Condenser"):
        return

    try:
        ctrl: AppController = st.session_state.controller
        sp: SuperPrompt = st.session_state.sp

        _set_sidebar_pipeline_visual_step(SIDEBAR_STEP_CONTEXT_SYNTHESIS)

        sp = ctrl.run_a4(sp)
        sp.compose_prompt_ready()

        st.session_state.sp = sp
        st.session_state.sp_a4 = copy.deepcopy(sp)
        st.session_state["super_prompt_text"] = sp.prompt_ready

    except Exception as e:
        st.error(str(e))


def do_create_project() -> None:
    """Create Project form callback."""
    if _guard_pipeline_running("Create Project"):
        return

    try:
        ctrl: AppController = st.session_state.controller
        result = ctrl.create_project(st.session_state.get("new_project_name", ""))

        st.session_state["ingestion_status"] = {
            "type": "success",
            "message": f"Project created: {result['project_name']}",
            "details": [
                f"doc_raw: {result['raw_dir']}",
                f"chroma_db: {result['chroma_dir']}",
                f"manifest: {result['manifest_path']}",
            ],
        }
        st.session_state["pending_active_project"] = result["project_name"]
        st.rerun()

    except Exception as e:
        st.session_state["ingestion_status"] = {
            "type": "error",
            "message": str(e),
            "details": [],
        }


def do_add_files() -> None:
    """Add Files form callback."""
    if _guard_pipeline_running("Add Files"):
        return

    try:
        ctrl: AppController = st.session_state.controller

        result = ctrl.import_files_to_project(
            st.session_state.get("add_files_project", ""),
            uploaded_files=st.session_state.get("ingestion_uploaded_files"),
        )

        if result.get("success"):
            st.session_state["ingestion_status"] = {
                "type": "success",
                "message": (
                    f"Files added to {result['project_name']} "
                    f"and ingestion finished."
                ),
                "details": [
                    f"copied files: {result.get('copied_count', 0)}",
                    f"files scanned: {result.get('files_scanned', 0)}",
                    f"to process: {result.get('to_process', 0)}",
                    f"unchanged: {result.get('unchanged', 0)}",
                    f"vectors upserted: {result.get('vectors_upserted', 0)}",
                    f"manifest: {result.get('manifest_path', '')}",
                ] + [
                    f"rejected: {item}" for item in result.get("rejected_files", [])
                ],
            }
            st.session_state["pending_active_project"] = result["project_name"]
            st.rerun()
        else:
            st.session_state["ingestion_status"] = {
                "type": "error",
                "message": result.get("message", "No files were added."),
                "details": [
                    f"rejected: {item}" for item in result.get("rejected_files", [])
                ],
            }

    except Exception as e:
        st.session_state["ingestion_status"] = {
            "type": "error",
            "message": str(e),
            "details": [],
        }
```

### ~\ragstream\app\ui_actions_files.py
```python
# ragstream/app/ui_actions_files.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import streamlit as st

from ragstream.memory.storage.memory_file_manager import MemoryFileManager
from ragstream.memory.importers.chatgpt_shared_link_importer import import_chatgpt_shared_link
from ragstream.memory.memory_manager import MemoryManager
from ragstream.textforge.RagLog import LogALL as logger


def do_files_create_history() -> None:
    """Create a new empty memory history and make it active."""
    new_title = str(st.session_state.get("files_new_memory_title", "") or "").strip()

    if not new_title:
        _set_status("error", "New memory name must not be empty.")
        return

    try:
        manager = _file_manager()
        result = manager.create_history(new_title)

        st.session_state["files_selected_file_id"] = result.get("file_id", "")

        _clear_memory_widget_state()

        _set_status(
            "success",
            f"Created memory history: {result.get('filename_ragmem', '')}",
        )

        logger(
            f"Memory history created: {result.get('filename_ragmem', '')}",
            "INFO",
            "PUBLIC",
        )

        st.rerun()

    except Exception as e:
        _set_status("error", str(e))
        logger(str(e), "ERROR", "PUBLIC")


def do_files_load_history() -> None:
    """Load selected memory history from server-side storage."""
    file_id = _selected_file_id()
    if not file_id:
        _set_status("error", "No memory history selected.")
        return

    try:
        manager = _file_manager()
        result = manager.load_history(file_id)

        _clear_memory_widget_state()

        _set_status(
            "success",
            f"Loaded memory history: {result.get('filename_ragmem', '')}",
        )

        logger(
            f"Memory history loaded: {result.get('filename_ragmem', '')}",
            "INFO",
            "PUBLIC",
        )

        st.rerun()

    except Exception as e:
        _set_status("error", str(e))
        logger(str(e), "ERROR", "PUBLIC")


def do_files_rename_history() -> None:
    """Rename selected memory history through RAGstream only."""
    file_id = _selected_file_id()
    if not file_id:
        _set_status("error", "No memory history selected.")
        return

    rename_key = _rename_key(file_id)
    new_title = str(st.session_state.get(rename_key, "") or "").strip()

    if not new_title:
        _set_status("error", "New memory name must not be empty.")
        return

    try:
        manager = _file_manager()
        result = manager.rename_history(
            file_id=file_id,
            new_title=new_title,
        )

        _set_status(
            "success",
            f"Renamed memory history: {result.get('filename_ragmem', '')}",
        )

        logger(
            f"Memory history renamed: {result.get('filename_ragmem', '')}",
            "INFO",
            "PUBLIC",
        )

        st.rerun()

    except Exception as e:
        _set_status("error", str(e))
        logger(str(e), "ERROR", "PUBLIC")


def do_files_delete_request() -> None:
    """Show delete confirmation input for selected memory history."""
    file_id = _selected_file_id()
    if not file_id:
        _set_status("error", "No memory history selected.")
        return

    st.session_state[_delete_pending_key(file_id)] = True
    _set_status("error", 'Deletion pending. Type "delete" and press Confirm Delete.')
    st.rerun()


def do_files_confirm_delete_history() -> None:
    """Delete selected memory history after typed confirmation."""
    file_id = _selected_file_id()
    if not file_id:
        _set_status("error", "No memory history selected.")
        return

    confirm_key = _delete_confirm_key(file_id)
    typed_value = str(st.session_state.get(confirm_key, "") or "").strip()

    if typed_value != "delete":
        _set_status("error", 'Deletion confirmation must be exactly: delete')
        return

    try:
        manager = _file_manager()
        result = manager.delete_history(file_id)

        st.session_state["files_selected_file_id"] = ""

        _clear_memory_widget_state()

        _set_status(
            "success",
            (
                "Deleted memory history: "
                f"{result.get('filename_ragmem', '')} | "
                f"vectors deleted: {result.get('vectors_deleted', 0)}"
            ),
        )

        logger(
            (
                "Memory history deleted: "
                f"{result.get('filename_ragmem', '')} | "
                f"vectors={result.get('vectors_deleted', 0)}"
            ),
            "INFO",
            "PUBLIC",
        )

        st.rerun()

    except Exception as e:
        _set_status("error", str(e))
        logger(str(e), "ERROR", "PUBLIC")


def do_files_import_chatgpt_conversation() -> None:
    """Import a public ChatGPT shared-link conversation as a memory history."""
    shared_url = str(st.session_state.get("files_chatgpt_import_url", "") or "").strip()
    title = str(st.session_state.get("files_chatgpt_import_title", "") or "").strip()
    summary = str(st.session_state.get("files_chatgpt_import_summary", "") or "").strip()

    if not shared_url:
        _set_status("error", "ChatGPT shared link must not be empty.")
        return

    if not title:
        _set_status("error", "Import title must not be empty.")
        return

    try:
        memory_manager: MemoryManager = st.session_state.memory_manager
        memory_ingestion_manager = st.session_state.get("memory_ingestion_manager")

        active_project_name, embedded_files_snapshot = _get_active_project_snapshot()

        result = import_chatgpt_shared_link(
            shared_url=shared_url,
            title=title,
            memory_manager=memory_manager,
            memory_ingestion_manager=memory_ingestion_manager,
            memory_brief=summary,
            memory_brief_title=title if summary else "",
            active_project_name=active_project_name,
            embedded_files_snapshot=embedded_files_snapshot,
        )

        st.session_state["files_selected_file_id"] = result.get("file_id", "")

        _clear_memory_widget_state()

        vector_info = result.get("vector_ingestion") or {}
        vector_text = ""
        if isinstance(vector_info, dict) and vector_info:
            vector_text = (
                f" | vector ingestion: "
                f"{vector_info.get('success_count', 0)} ok, "
                f"{vector_info.get('failure_count', 0)} failed"
            )

        _set_status(
            "success",
            (
                "Imported ChatGPT conversation: "
                f"{result.get('filename_ragmem', '')} | "
                f"records: {result.get('record_count', 0)}"
                f"{vector_text}"
            ),
        )

        logger(
            (
                "ChatGPT shared conversation imported: "
                f"{result.get('filename_ragmem', '')} | "
                f"records={result.get('record_count', 0)}"
            ),
            "INFO",
            "PUBLIC",
        )

        st.rerun()

    except Exception as e:
        _set_status("error", str(e))
        logger(str(e), "ERROR", "PUBLIC")


def _get_active_project_snapshot() -> tuple[str | None, list[str]]:
    active_project = st.session_state.get("active_project")

    if not active_project or active_project == "(no projects yet)":
        return None, []

    try:
        ctrl = st.session_state.get("controller")
        if ctrl is None:
            return str(active_project), []

        embedded_info = ctrl.get_embedded_files(active_project)
        if embedded_info.get("success"):
            return str(active_project), list(embedded_info.get("files", []))

    except Exception:
        return str(active_project), []

    return str(active_project), []


def _file_manager() -> MemoryFileManager:
    memory_manager: MemoryManager = st.session_state.memory_manager
    memory_vector_store = st.session_state.get("memory_vector_store")

    return MemoryFileManager(
        memory_manager=memory_manager,
        memory_vector_store=memory_vector_store,
    )


def _selected_file_id() -> str:
    return str(st.session_state.get("files_selected_file_id", "") or "").strip()


def _rename_key(file_id: str) -> str:
    return f"files_rename_title_{file_id}"


def _delete_pending_key(file_id: str) -> str:
    return f"files_delete_pending_{file_id}"


def _delete_confirm_key(file_id: str) -> str:
    return f"files_delete_confirm_text_{file_id}"


def _set_status(status_type: str, message: str) -> None:
    st.session_state["files_action_status"] = {
        "type": status_type,
        "message": message,
    }


def _clear_memory_widget_state() -> None:
    prefixes = (
        "memory_tag_",
        "memory_retrieval_source_mode_",
        "memory_user_keywords_",
        "memory_direct_recall_key_",
    )

    for key in list(st.session_state.keys()):
        if str(key).startswith(prefixes):
            st.session_state.pop(key, None)
```

### ~\ragstream\app\ui_files.py
```python
# ragstream/app/ui_files.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import pandas as pd
import streamlit as st

from ragstream.app.ui_actions_files import (
    do_files_confirm_delete_history,
    do_files_create_history,
    do_files_delete_request,
    do_files_import_chatgpt_conversation,
    do_files_load_history,
    do_files_rename_history,
)


TABLE_STRIPE_COLOR = "#E2FBD8"

# Main FILES layout:
# left  = memory creation / histories / selected file / actions
# right = ChatGPT shared-link import panel
CONTENT_COLS = [3.0, 4.5]


def render_files_tab() -> None:
    """Server-side FILES tab for memory history management."""
    st.markdown("## Files")

    memory_manager = st.session_state.memory_manager
    histories = memory_manager.list_histories()

    _repair_selected_file_id(histories)

    left_col, right_col = st.columns(CONTENT_COLS, gap="large")

    with left_col:
        _render_left_files_area(histories)

    with right_col:
        _render_chatgpt_import_area()


def _render_left_files_area(histories: list[dict]) -> None:
    """Render the normal FILES management area on the left side."""
    _render_new_memory_area()

    if not histories:
        st.info("No memory histories found.")
        _render_status()
        return

    _render_history_table(histories)

    selected_file_id = str(st.session_state.get("files_selected_file_id", "") or "").strip()
    selected = _history_by_file_id(histories, selected_file_id)

    st.markdown("### Selected Memory History")

    if not selected:
        st.info("Select one memory history from the table above.")
        _render_status()
        return

    _render_selected_card(selected)
    _render_action_area(selected)
    _render_status()


def _render_new_memory_area() -> None:
    """Render compact New Memory action."""
    st.markdown("### New Memory")

    name_col, btn_col = st.columns([2.2, 0.8], gap="small")

    with name_col:
        st.text_input(
            "New memory name",
            key="files_new_memory_title",
            placeholder="New memory name",
            label_visibility="collapsed",
        )

    with btn_col:
        if st.button("New", key="btn_files_new", use_container_width=True):
            do_files_create_history()


def _render_chatgpt_import_area() -> None:
    """Render ChatGPT shared-link import controls in a right-side panel."""
    st.markdown(
        """
        <style>
        div[data-testid="stVerticalBlockBorderWrapper"]:has(#chatgpt-import-panel-marker) {
            background-color: #f6fbff;
            border: 1px solid #d6e8f5;
            border-radius: 0.75rem;
            padding: 0.85rem 1.0rem 1.0rem 1.0rem;
            box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        st.markdown('<span id="chatgpt-import-panel-marker"></span>', unsafe_allow_html=True)

        st.markdown("### Import from ChatGPT UI")

        st.text_input(
            "ChatGPT shared link",
            key="files_chatgpt_import_url",
            placeholder="https://chatgpt.com/share/...",
        )

        st.text_input(
            "Import title",
            key="files_chatgpt_import_title",
            placeholder="Memory history title",
        )

        st.text_area(
            "Summary / MemoryBrief (optional)",
            key="files_chatgpt_import_summary",
            height=110,
            placeholder="Optional shared MemoryBrief assigned to all imported records.",
        )

        if st.button(
            "Import Conversation",
            key="btn_files_import_chatgpt_conversation",
            use_container_width=True,
        ):
            do_files_import_chatgpt_conversation()


def _render_history_table(histories: list[dict]) -> None:
    """
    Render memory histories as a selectable dataframe.

    User selects one row in the table, then uses the action buttons below.
    """
    st.markdown("### Memory Histories")

    rows: list[dict[str, str]] = []

    for item in histories:
        rows.append(
            {
                "Filename": str(item.get("filename_ragmem", "") or ""),
                "Created": str(item.get("created_at_utc", "") or ""),
                "Updated": str(item.get("updated_at_utc", "") or ""),
                "Records": str(int(item.get("record_count", 0) or 0)),
                "_file_id": str(item.get("file_id", "") or ""),
            }
        )

    df = pd.DataFrame(rows)

    if df.empty:
        st.info("No memory histories found.")
        return

    visible_df = df[["Filename", "Created", "Updated", "Records"]].copy()
    styled_df = visible_df.style.apply(_stripe_table_rows, axis=1)

    event = st.dataframe(
        styled_df,
        key="files_history_table",
        use_container_width=True,
        hide_index=True,
        height=320,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Filename": st.column_config.TextColumn(
                "Filename",
                width="medium",
            ),
            "Created": st.column_config.TextColumn(
                "Created",
                width="small",
            ),
            "Updated": st.column_config.TextColumn(
                "Updated",
                width="small",
            ),
            "Records": st.column_config.TextColumn(
                "Records",
                width="small",
            ),
        },
    )

    selected_rows = _get_selected_rows(event)
    if selected_rows:
        row_index = int(selected_rows[0])
        if 0 <= row_index < len(df):
            st.session_state["files_selected_file_id"] = str(df.iloc[row_index]["_file_id"])


def _render_selected_card(selected: dict) -> None:
    """Render compact selected-file information."""
    filename = str(selected.get("filename_ragmem", "") or "")
    file_id = str(selected.get("file_id", "") or "")
    created = str(selected.get("created_at_utc", "") or "")
    updated = str(selected.get("updated_at_utc", "") or "")
    records = int(selected.get("record_count", 0) or 0)

    st.markdown(
        f"""
        <div style="
            border:1px solid #d8d8d8;
            border-radius:0.55rem;
            padding:0.65rem 0.85rem;
            background-color:#fafafa;
        ">
            <div style="font-weight:700; font-size:1.02rem;">{filename}</div>
            <div style="font-size:0.84rem; color:#555;">file_id: {file_id}</div>
            <div style="font-size:0.84rem; color:#555;">created: {created}</div>
            <div style="font-size:0.84rem; color:#555;">updated: {updated}</div>
            <div style="font-size:0.84rem; color:#555;">records: {records}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_action_area(selected: dict) -> None:
    """Render Load / New / Rename / Delete actions for the selected history."""
    file_id = str(selected.get("file_id", "") or "").strip()

    rename_key = f"files_rename_title_{file_id}"
    delete_pending_key = f"files_delete_pending_{file_id}"
    delete_confirm_key = f"files_delete_confirm_text_{file_id}"

    st.markdown("### Actions")

    if st.button("Load", key=f"btn_files_load_{file_id}", use_container_width=True):
        do_files_load_history()

    rename_text_col, rename_btn_col = st.columns([2.1, 1.0], gap="small")
    with rename_text_col:
        st.text_input(
            "Rename field",
            key=rename_key,
            placeholder="New name",
            label_visibility="collapsed",
        )
    with rename_btn_col:
        if st.button("Rename", key=f"btn_files_rename_{file_id}", use_container_width=True):
            do_files_rename_history()

    if not st.session_state.get(delete_pending_key, False):
        if st.button("Delete", key=f"btn_files_delete_request_{file_id}", use_container_width=True):
            do_files_delete_request()
    else:
        st.warning('Type "delete" to confirm deletion.')
        confirm_text_col, confirm_btn_col = st.columns([2.1, 1.0], gap="small")

        with confirm_text_col:
            st.text_input(
                "Delete confirmation",
                key=delete_confirm_key,
                placeholder='type "delete"',
                label_visibility="collapsed",
            )

        with confirm_btn_col:
            if st.button(
                "Confirm Delete",
                key=f"btn_files_confirm_delete_{file_id}",
                use_container_width=True,
            ):
                do_files_confirm_delete_history()


def _render_status() -> None:
    """Render latest FILES action status."""
    status = st.session_state.get("files_action_status")
    if not status:
        return

    if status.get("type") == "success":
        st.success(status.get("message", ""))
    else:
        st.error(status.get("message", ""))


def _repair_selected_file_id(histories: list[dict]) -> None:
    """
    Keep selected file_id only if it still exists.

    Important:
    - Do not auto-select newest file.
    - User selection must be explicit.
    """
    selected_file_id = str(st.session_state.get("files_selected_file_id", "") or "").strip()
    if not selected_file_id:
        return

    existing_ids = {str(item.get("file_id", "") or "").strip() for item in histories}
    if selected_file_id not in existing_ids:
        st.session_state["files_selected_file_id"] = ""


def _history_by_file_id(histories: list[dict], file_id: str) -> dict | None:
    clean_file_id = str(file_id or "").strip()

    for item in histories:
        if str(item.get("file_id", "") or "").strip() == clean_file_id:
            return item

    return None


def _get_selected_rows(event: object) -> list[int]:
    """Extract selected dataframe row indexes from Streamlit event object."""
    try:
        rows = event.selection.rows
    except Exception:
        return []

    if not rows:
        return []

    return [int(row) for row in rows]


def _stripe_table_rows(row: pd.Series) -> list[str]:
    """Apply soft alternating row colors."""
    color = TABLE_STRIPE_COLOR if int(row.name) % 2 == 1 else "white"
    return [f"background-color: {color}" for _ in row]
```

### ~\ragstream\app\ui_layout.py
```python
# ragstream/app/ui_layout.py
# -*- coding: utf-8 -*-
"""
Layout / geometry helpers for Streamlit UI.
Keep columns, containers, labels and visual order here.
"""

from __future__ import annotations

import html
import re
import time

from typing import Any

import streamlit as st

from ragstream.app.controller import AppController
from ragstream.app.ui_actions import (
    do_a2_promptshaper,
    do_a3_nli_gate,
    do_a4_condenser,
    do_add_files,
    do_create_project,
    do_feed_memory_manually,
    do_preprocess,
    do_reranker,
    do_retrieval,
    do_user_prompt_changed,
    request_prompt_builder_run,
    run_next_prompt_builder_step,
)

TAG_COLORS: dict[str, str] = {
    "Gold": "#D4AF37",
    "Green": "#00A86B",
    "Black": "#111111",
}

MEMORY_HEIGHT = 650
PROMPT_HEIGHT = 180
ENGINEERED_PROMPT_EXPANDED_HEIGHT = 1200
MANUAL_MEMORY_FEED_HEIGHT = 68
RUNTIME_LOG_HEIGHT = 150
EMBEDDED_FILES_HEIGHT = 120

MAIN_COLUMNS = [4, 0.25, 4]
ACTION_ROW_COLUMNS = [1.15, 3.35]
MODEL_ROW_COLUMNS = [1.15, 1.1, 2.25]
ENGINEERED_PROMPT_COLUMNS = [20, 1.8]
ADVANCED_TOPK_COLUMNS = [0.9, 3.1]
MEMORY_RECORD_COLUMNS = [8.8, 1.0]
MEMORY_TAG_COLUMNS = [0.22, 1.0]
PROJECT_HALF_COLUMNS = [1, 1]


def _vertical_gap(height: str) -> None:
    """Render a small vertical spacer."""
    st.markdown(f"<div style='height:{height}'></div>", unsafe_allow_html=True)


def _memory_display_name(filename_ragmem: str | None) -> tuple[str, str]:
    """Return clean visible memory name plus real source filename."""
    filename = str(filename_ragmem or "").strip()

    if not filename:
        return "Memory", ""

    visible_name = re.sub(r"(?i)\.ragmem$", "", filename)
    visible_name = re.sub(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-", "", visible_name)
    visible_name = visible_name.strip() or filename

    return visible_name, filename


def _model_options() -> list[str]:
    return [
        "OpenAI GPT-5.5",
        "OpenAI GPT-5.4",
        "OpenAI o3",
        "OpenAI o2",
        "OpenAI GPT-5 mini",
        "OpenAI GPT-5 nano",
        "Claude Opus 4.1",
        "Claude Sonnet 4.5",
        "Claude Haiku 3.5",
        "Gemini 2.5 Pro",
        "Gemini 2.5 Flash",
        "Gemini 2.0 Flash",
        "Local / Custom",
    ]


def _base_page_css() -> str:
    return """
        div[data-testid="stHeader"] {
            display: none !important;
        }
        
                /* Prevent accidental sidebar collapse */
        button[aria-label="Close sidebar"],
        button[title="Close sidebar"],
        [data-testid="stSidebarCollapseButton"] {
            display: none !important;
        }

        .block-container {
            padding-top: 0.20rem;
            padding-bottom: 0rem;
            padding-left: 0.65rem;
            padding-right: 0.65rem;
        }

        div[data-testid="stHorizontalBlock"] {
            gap: 0.45rem !important;
        }

        div[data-baseweb="select"] > div {
            min-height: 34px;
        }
    """


def _product_identity_css() -> str:
    return """
        .ghost-product-title {
            font-size: 2.0rem;
            font-weight: 520;
            font-style: italic;
            letter-spacing: -0.025em;
            color: #7A1E1E;
            line-height: 1.15;
            margin: 0.10rem 0 0.18rem 0;
        }

        .ghost-product-title .brand-initial {
            font-weight: 800;
        }

        .ghost-product-subtitle {
            font-size: 0.88rem;
            color: #6B7280;
            line-height: 1.25;
            margin-bottom: 0.55rem;
        }
    """


def _title_css() -> str:
    return """
        .field-title,
        .panel-title,
        .memory-title {
            font-size: 1.08rem;
            font-weight: 600;
            line-height: 1.2;
            margin-bottom: 0.30rem;
            color: #1F2937;
            letter-spacing: -0.010em;
        }

        .memory-title {
            font-size: 1.12rem;
            margin-bottom: 0.08rem;
        }
    """


def _memory_css() -> str:
    return """
        .memory-box {
            border-radius: 0.45rem;
            padding: 0.55rem 0.70rem;
            border: 1px solid #d8d8d8;
            font-size: 1.02rem;
            line-height: 1.38;
            white-space: normal;
            word-break: break-word;
        }

        .memory-input-box {
            background-color: #ffffff;
        }

        .memory-output-box {
            background-color: #f3f4f6;
        }

        .memory-label {
            font-size: 0.78rem;
            font-weight: 650;
            margin-bottom: 0.25rem;
            color: #4b5563;
            letter-spacing: 0.02em;
        }

        .memory-plain-text {
            white-space: pre-wrap;
            font-size: 1.02rem;
            line-height: 1.38;
            margin: 0;
            font-family: inherit;
        }

        .memory-tag-indicator {
            display: flex;
            align-items: center;
            gap: 0.35rem;
            margin-bottom: 0.25rem;
            min-height: 24px;
        }

        .memory-tag-square {
            width: 18px;
            height: 18px;
            border-radius: 0.25rem;
            border: 1px solid rgba(0, 0, 0, 0.25);
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.16);
            flex: 0 0 auto;
        }
    """


def _button_css() -> str:
    return """
        div[data-testid="stButton"] > button[kind="primary"] {
            background-color: #BB0000 !important;
            border-color: #BB0000 !important;
            color: white !important;
            font-weight: 800 !important;
        }

        div[data-testid="stButton"] > button[kind="primary"]:hover,
        div[data-testid="stButton"] > button[kind="primary"]:focus {
            background-color: #990000 !important;
            border-color: #990000 !important;
            color: white !important;
        }

        div[data-testid="stButton"] > button[kind="primary"] p {
            color: white !important;
            font-weight: 800 !important;
        }

        /* Prompt Builder intentionally uses the normal Streamlit button style. */

        .st-key-btn_feed_memory_manually button {
            background-color: #00A2E8 !important;
            border-color: #00A2E8 !important;
            color: white !important;
            font-weight: 650 !important;
        }

        .st-key-btn_feed_memory_manually button:hover,
        .st-key-btn_feed_memory_manually button:focus {
            background-color: #00A2E8 !important;
            border-color: #00A2E8 !important;
            color: white !important;
        }

        .st-key-btn_feed_memory_manually button p {
            color: white !important;
            font-weight: 650 !important;
        }
    """


def _form_field_css() -> str:
    return """
        textarea[aria-label="Manual Memory Feed (hidden)"] {
            background-color: #EAF7FF !important;
        }

        div[data-testid="stTextInput"]:has(input[aria-label="Direct Recall Key"]) div[data-baseweb="input"] {
            border: 2px solid #D11A2A !important;
            border-radius: 0.45rem !important;
            box-shadow: none !important;
        }

        div[data-testid="stTextInput"]:has(input[aria-label="Direct Recall Key"]) div[data-baseweb="input"]:focus-within {
            border: 2px solid #D11A2A !important;
            box-shadow: 0 0 0 1px rgba(209, 26, 42, 0.25) !important;
        }
    """


def _runtime_log_css() -> str:
    return """
        .textforge-log-box {
            background-color: #EAFBEA;
            border: 1px solid #B7E4B7;
            border-radius: 0.45rem;
            padding: 0.55rem 0.70rem;
            min-height: 140px;
            max-height: 180px;
            overflow-y: auto;
            white-space: normal;
            word-break: break-word;
            font-family: monospace;
            font-size: 0.88rem;
            line-height: 1.35;
        }
    """


def inject_base_css() -> None:
    """Global CSS for page spacing, product identity, panels, and buttons."""
    css = "\n".join(
        [
            _base_page_css(),
            _product_identity_css(),
            _title_css(),
            _memory_css(),
            _button_css(),
            _form_field_css(),
            _runtime_log_css(),
        ]
    )

    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def render_page() -> None:
    """
    MAIN page layout:
    - Product identity header
    - Full-width Memory area
    - LEFT: User Prompt + main actions
    - RIGHT: Engineered Prompt + project/file context
    """
    render_product_identity_header()
    render_memory_records(height=MEMORY_HEIGHT)

    _vertical_gap("0.55rem")

    col_user, spacer, col_engineered = st.columns(MAIN_COLUMNS, gap="small")

    with col_user:
        render_user_prompt_panel()
        render_main_action_controls()
        render_pipeline_status()

        _vertical_gap("0.45rem")
        render_textforge_gui_log(height=RUNTIME_LOG_HEIGHT)

        if st.session_state.get("show_advanced_controls", False):
            _vertical_gap("0.55rem")
            render_advanced_controls()

        # Must run after status/log rendering, but before Engineered Prompt widget creation.
        run_next_prompt_builder_step()

    with spacer:
        st.empty()

    with col_engineered:
        render_engineered_prompt_panel()

        _vertical_gap("0.55rem")

        ctrl: AppController = st.session_state.controller
        render_project_area(
            ctrl,
            show_ingestion_controls=bool(
                st.session_state.get("enable_file_ingestion_controls", False)
            ),
        )


def render_product_identity_header() -> None:
    """Render the MAIN-page product identity."""
    st.markdown(
        """
        <div class="ghost-product-title">
            <span class="brand-initial">G</span>enAI
            <span class="brand-initial">H</span>ybrid
            <span class="brand-initial">O</span>rchestrator
            for
            <span class="brand-initial">S</span>oftware
            <span class="brand-initial">T</span>ooling
            <span style="font-style:normal; font-weight:700;">(GHOST)</span>
        </div>
        <div class="ghost-product-subtitle">
            Professional prompt orchestration, memory, retrieval, and software-tooling workflow control.
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_user_prompt_panel() -> None:
    """Left column: User Prompt."""
    st.markdown('<div class="panel-title">User Prompt</div>', unsafe_allow_html=True)

    st.text_area(
        label="Prompt (hidden)",
        key="prompt_text",
        height=180,
        label_visibility="collapsed",
        on_change=do_user_prompt_changed,
    )


def render_engineered_prompt_panel() -> None:
    """Right column: Engineered Prompt with compact/expanded display."""
    if "engineered_prompt_expanded" not in st.session_state:
        st.session_state["engineered_prompt_expanded"] = False

    expanded = bool(st.session_state.get("engineered_prompt_expanded", False))
    prompt_height = ENGINEERED_PROMPT_EXPANDED_HEIGHT if expanded else PROMPT_HEIGHT

    st.markdown('<div class="panel-title">Engineered Prompt</div>', unsafe_allow_html=True)

    prompt_col, expand_col = st.columns(ENGINEERED_PROMPT_COLUMNS, gap="small")

    with prompt_col:
        st.text_area(
            label="Engineered Prompt (hidden)",
            key="super_prompt_text",
            height=prompt_height,
            label_visibility="collapsed",
        )

    with expand_col:
        toggle_label = "⟪" if expanded else "⟫"
        if st.button(
            toggle_label,
            key="btn_toggle_engineered_prompt",
            use_container_width=True,
            help="Expand / collapse Engineered Prompt",
        ):
            st.session_state["engineered_prompt_expanded"] = not expanded
            st.rerun()


def render_main_action_controls() -> None:
    """Left column: main execution controls below User Prompt."""
    _vertical_gap("0.45rem")

    _render_prompt_builder_row()
    _render_llm_call_row()
    _render_manual_memory_feed_row()

    _vertical_gap("0.45rem")


def _render_prompt_builder_row() -> None:
    action_col, detail_col = st.columns(ACTION_ROW_COLUMNS, gap="small")

    with action_col:
        if st.button(
            "Prompt Builder",
            key="btn_builder",
            use_container_width=True,
        ):
            request_prompt_builder_run()

    with detail_col:
        cb1, cb2, cb3 = st.columns(3, gap="small")

        with cb1:
            use_a2_promptshaper_llm = st.checkbox(
                "use PromptShaper",
                key="use_a2_promptshaper_llm_widget",
            )

        with cb2:
            use_retrieval_splade = st.checkbox(
                "use Retrieval Splade",
                key="use_retrieval_splade_widget",
            )

        with cb3:
            use_reranking_colbert = st.checkbox(
                "use Reranking Colbert",
                key="use_reranking_colbert_widget",
            )

        st.session_state["use_a2_promptshaper_llm"] = bool(use_a2_promptshaper_llm)
        st.session_state["use_retrieval_splade"] = bool(use_retrieval_splade)
        st.session_state["use_reranking_colbert"] = bool(use_reranking_colbert)


def _render_llm_call_row() -> None:
    action_col, model_col, model_spacer = st.columns(MODEL_ROW_COLUMNS, gap="small")

    with action_col:
        if st.button(
            "LLM Call",
            key="btn_llm_call",
            use_container_width=True,
            type="primary",
        ):
            st.session_state["llm_call_status"] = "LLM Call requested."

    with model_col:
        st.selectbox(
            "Model",
            options=_model_options(),
            key="selected_llm_model",
            label_visibility="collapsed",
        )

    with model_spacer:
        st.empty()


def _render_manual_memory_feed_row() -> None:
    action_col, detail_col = st.columns(ACTION_ROW_COLUMNS, gap="small")

    with action_col:
        if st.button(
            "Feed Memory Manually",
            key="btn_feed_memory_manually",
            use_container_width=True,
        ):
            do_feed_memory_manually()

    with detail_col:
        st.text_area(
            label="Manual Memory Feed (hidden)",
            key="manual_memory_feed_text",
            height=MANUAL_MEMORY_FEED_HEIGHT,
            label_visibility="collapsed",
            placeholder="Paste LLM reply here for manual memory feed.",
        )


def render_advanced_controls() -> None:
    """Advanced/debug controls shown only when enabled from the sidebar."""
    st.markdown('<div class="panel-title">Advanced Controls</div>', unsafe_allow_html=True)

    _normalise_retrieval_top_k_widget()
    _render_retrieval_top_k_control()
    _render_manual_pipeline_buttons()


def _normalise_retrieval_top_k_widget() -> None:
    if "retrieval_top_k_widget" not in st.session_state:
        st.session_state["retrieval_top_k_widget"] = int(
            st.session_state.get("retrieval_top_k", 30) or 30
        )


def _render_retrieval_top_k_control() -> None:
    topk_c, gap_c = st.columns(ADVANCED_TOPK_COLUMNS, gap="small")

    with topk_c:
        selected_top_k = st.number_input(
            "Retrieval Top-K",
            min_value=1,
            max_value=1000,
            step=1,
            key="retrieval_top_k_widget",
        )

        st.session_state["retrieval_top_k"] = int(selected_top_k)

    with gap_c:
        st.empty()


def _render_manual_pipeline_buttons() -> None:
    b1c1, b1c2, b1c3, b1c4 = st.columns(4, gap="small")

    with b1c1:
        if st.button("Pre-Processing", key="btn_preproc", use_container_width=True):
            do_preprocess()

    with b1c2:
        if st.button("A2-PromptShaper", key="btn_a2", use_container_width=True):
            do_a2_promptshaper()

    with b1c3:
        if st.button("Retrieval", key="btn_retrieval", use_container_width=True):
            do_retrieval()

    with b1c4:
        if st.button("ReRanker", key="btn_reranker", use_container_width=True):
            do_reranker()

    b2c1, b2c2, b2c3, b2c4 = st.columns(4, gap="small")

    with b2c1:
        if st.button("A3 NLI Gate", key="btn_a3", use_container_width=True):
            do_a3_nli_gate()

    with b2c2:
        if st.button("A4 Condenser", key="btn_a4", use_container_width=True):
            do_a4_condenser()

    with b2c3:
        st.button("A5 Format Enforcer", key="btn_a5", use_container_width=True)

    with b2c4:
        st.empty()


def render_pipeline_status() -> Any:
    """Render only the Prompt Builder pipeline progress bar."""
    status = st.session_state.get("pipeline_status")
    if not isinstance(status, dict):
        status = {
            "stage_name": "Idle",
            "step_index": 0,
            "total_steps": 8,
            "message": "No pipeline run active.",
            "progress": 0.0,
        }

    stage_name = str(status.get("stage_name", "Idle") or "Idle")
    step_index = int(status.get("step_index", 0) or 0)
    total_steps = int(status.get("total_steps", 8) or 8)
    progress = float(status.get("progress", 0.0) or 0.0)

    st.progress(
        progress,
        text=f"{step_index}/{total_steps} — {stage_name}",
    )


def render_textforge_gui_log(height: int = RUNTIME_LOG_HEIGHT) -> None:
    """Render the TextForge GUI log box."""
    st.markdown(
        '<div class="field-title" style="font-size:1.05rem;">Runtime Log</div>',
        unsafe_allow_html=True,
    )

    log_html = _build_textforge_log_html()
    log_box_style = _runtime_log_box_style(height=height)

    st.markdown(
        f'<div class="textforge-log-box" style="{log_box_style}">{log_html}</div>',
        unsafe_allow_html=True,
    )


def _build_textforge_log_html() -> str:
    log_text = st.session_state.get("textforge_gui_log", "")
    if not log_text:
        log_text = "(no log messages yet)"

    lines = log_text.splitlines()
    if not lines:
        return ""

    first_line = html.escape(lines[0])
    older_lines = "<br>".join(
        f"<i>{html.escape(line)}</i>"
        for line in lines[1:]
    )

    if older_lines:
        return f"{first_line}<br>{older_lines}"

    return first_line


def _runtime_log_box_style(height: int) -> str:
    flash_active = time.time() < st.session_state.get("runtime_log_flash_until", 0)

    if flash_active:
        return (
            f"min-height:{height}px; max-height:{height}px;"
            "background-color:#FFE5E5; border-color:#FF9A9A;"
        )

    return f"min-height:{height}px; max-height:{height}px;"


def render_memory_records(height: int = MEMORY_HEIGHT) -> None:
    """Memory record list."""
    memory_manager = st.session_state.memory_manager

    _render_memory_title(memory_manager)

    memory_entries = memory_manager.records

    try:
        memory_container = st.container(height=height)
    except TypeError:
        memory_container = st.container()

    with memory_container:
        if not memory_entries:
            st.info("No memory records yet.")
            return

        for record in memory_entries:
            _render_memory_record(memory_manager, record)


def _render_memory_title(memory_manager: Any) -> None:
    memory_title, memory_source_file = _memory_display_name(
        getattr(memory_manager, "filename_ragmem", "")
    )

    if memory_source_file:
        st.markdown(
            f"""
            <div class="memory-title">
                {html.escape(memory_title)}
            </div>
            <div style="
                font-size:0.66rem;
                color:#6b7280;
                line-height:1.1;
                margin-top:-0.02rem;
                margin-bottom:0.30rem;
            ">
                extracted from {html.escape(memory_source_file)}
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        f'<div class="memory-title">{html.escape(memory_title)}</div>',
        unsafe_allow_html=True,
    )


def _memory_record_keys(record: Any) -> tuple[str, str, str, str]:
    return (
        f"memory_tag_{record.record_id}",
        f"memory_retrieval_source_mode_{record.record_id}",
        f"memory_user_keywords_{record.record_id}",
        f"memory_direct_recall_key_{record.record_id}",
    )


def _ensure_memory_record_session_state(
    memory_manager: Any,
    record: Any,
    tag_key: str,
    source_mode_key: str,
    keywords_key: str,
    direct_recall_key: str,
) -> list[str]:
    tag_options = list(memory_manager.tag_catalog)
    record_tag = record.tag if record.tag in tag_options else "Green"

    if tag_key not in st.session_state:
        st.session_state[tag_key] = record_tag
    elif st.session_state[tag_key] not in tag_options:
        st.session_state[tag_key] = "Green"

    if source_mode_key not in st.session_state:
        st.session_state[source_mode_key] = getattr(record, "retrieval_source_mode", "QA")
    elif st.session_state[source_mode_key] not in {"QA", "Q", "A"}:
        st.session_state[source_mode_key] = "QA"

    if keywords_key not in st.session_state:
        st.session_state[keywords_key] = ", ".join(record.user_keywords)

    if direct_recall_key not in st.session_state:
        st.session_state[direct_recall_key] = getattr(record, "direct_recall_key", "")

    return tag_options


def _render_memory_record(memory_manager: Any, record: Any) -> None:
    tag_key, source_mode_key, keywords_key, direct_recall_key = _memory_record_keys(record)

    tag_options = _ensure_memory_record_session_state(
        memory_manager=memory_manager,
        record=record,
        tag_key=tag_key,
        source_mode_key=source_mode_key,
        keywords_key=keywords_key,
        direct_recall_key=direct_recall_key,
    )

    selected_tag = st.session_state.get(tag_key, record.tag)
    tag_color = TAG_COLORS.get(selected_tag, "#6B7280")

    input_col, meta_col = st.columns(MEMORY_RECORD_COLUMNS, gap="small")

    with input_col:
        _render_memory_record_input(record)

    with meta_col:
        _render_memory_record_meta(
            tag_key=tag_key,
            tag_options=tag_options,
            tag_color=tag_color,
            source_mode_key=source_mode_key,
            direct_recall_key=direct_recall_key,
        )

    _render_memory_record_output(record)

    _vertical_gap("0.40rem")


def _render_memory_record_input(record: Any) -> None:
    input_html = html.escape(record.input_text).replace("\n", "<br>")

    st.markdown(
        f"""
        <div class="memory-box memory-input-box">
            <div class="memory-label">INPUT</div>
            <div class="memory-plain-text">{input_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_memory_record_meta(
    tag_key: str,
    tag_options: list[str],
    tag_color: str,
    source_mode_key: str,
    direct_recall_key: str,
) -> None:
    tag_square_col, tag_select_col = st.columns(MEMORY_TAG_COLUMNS, gap="small")

    with tag_square_col:
        st.markdown(
            f"""
            <div class="memory-tag-indicator">
                <span class="memory-tag-square" style="background-color:{tag_color};"></span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with tag_select_col:
        st.selectbox(
            "Tag",
            options=tag_options,
            key=tag_key,
            label_visibility="collapsed",
        )

    st.selectbox(
        "Retrieval Source Mode",
        options=["QA", "Q", "A"],
        key=source_mode_key,
        format_func={
            "QA": "Retrieve Q+A",
            "Q": "Retrieve only Q",
            "A": "Retrieve only A",
        }.get,
        label_visibility="collapsed",
    )

    st.text_input(
        "Direct Recall Key",
        key=direct_recall_key,
        placeholder="Direct Recall Key",
    )


def _render_memory_record_output(record: Any) -> None:
    output_html = html.escape(record.output_text).replace("\n", "<br>")

    st.markdown(
        f"""
        <div class="memory-box memory-output-box">
            <div class="memory-label">OUTPUT</div>
            <div class="memory-plain-text">{output_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_project_area(ctrl: AppController, show_ingestion_controls: bool = False) -> None:
    """
    Project selector, embedded files, and optional file-ingestion controls.
    """
    projects = ctrl.list_projects()

    _sync_pending_project(projects)

    st.markdown('<div class="panel-title">Project Context</div>', unsafe_allow_html=True)

    _render_project_selector(projects)
    _render_embedded_files(ctrl, projects)

    if show_ingestion_controls:
        _vertical_gap("0.45rem")
        _render_file_ingestion_controls(ctrl)

    _render_ingestion_status()


def _sync_pending_project(projects: list[str]) -> None:
    pending_project = st.session_state.get("pending_active_project")
    if pending_project is None:
        return

    if projects and pending_project in projects:
        st.session_state["active_project"] = pending_project

    st.session_state["pending_active_project"] = None


def _render_project_selector(projects: list[str]) -> None:
    project_col, project_spacer = st.columns(PROJECT_HALF_COLUMNS, gap="small")

    with project_col:
        if projects:
            if st.session_state.get("active_project") not in projects:
                st.session_state["active_project"] = projects[0]

            st.selectbox(
                "Active DB / Project",
                options=projects,
                key="active_project",
            )
        else:
            st.selectbox(
                "Active DB / Project",
                options=["(no projects yet)"],
                index=0,
                disabled=True,
            )

    with project_spacer:
        st.empty()


def _render_embedded_files(ctrl: AppController, projects: list[str]) -> None:
    active_project = st.session_state.get("active_project")
    if not projects or active_project not in projects:
        return

    embedded_info = ctrl.get_embedded_files(active_project)

    _vertical_gap("0.25rem")

    embedded_col, embedded_spacer = st.columns(PROJECT_HALF_COLUMNS, gap="small")

    with embedded_col:
        st.markdown(
            '<div class="panel-title" style="font-size:0.95rem;">Embedded Files</div>',
            unsafe_allow_html=True,
        )

        if embedded_info.get("success"):
            embedded_files = embedded_info.get("files", [])
            embedded_text = "\n".join(embedded_files) if embedded_files else "(no embedded files yet)"
            st.text_area(
                label="Embedded Files (hidden)",
                value=embedded_text,
                height=EMBEDDED_FILES_HEIGHT,
                disabled=True,
                label_visibility="collapsed",
            )
        else:
            st.error(embedded_info.get("message", "Could not read embedded file list."))

    with embedded_spacer:
        st.empty()


def _render_file_ingestion_controls(ctrl: AppController) -> None:
    st.markdown('<div class="panel-title">File Ingestion Controls</div>', unsafe_allow_html=True)

    create_col, add_col = st.columns(2, gap="small")

    with create_col:
        _render_create_project_form()

    with add_col:
        _render_add_files_form(ctrl)


def _render_create_project_form() -> None:
    with st.form("create_project_form", clear_on_submit=False):
        st.text_input("Project Name", key="new_project_name")
        create_clicked = st.form_submit_button("Create Project", use_container_width=True)

        if create_clicked:
            do_create_project()


def _render_add_files_form(ctrl: AppController) -> None:
    with st.form("add_files_form", clear_on_submit=False):
        add_projects = ctrl.list_projects()

        if not add_projects:
            st.info("Create a project first, then add files.")
            return

        current_active_project = st.session_state.get("active_project")
        if current_active_project in add_projects:
            default_add_project = current_active_project
        else:
            default_add_project = add_projects[0]

        st.selectbox(
            "Choose Project",
            options=add_projects,
            key="add_files_project",
            index=add_projects.index(default_add_project),
        )

        st.file_uploader(
            "Select .txt / .md files from your local machine",
            type=["txt", "md"],
            accept_multiple_files=True,
            key="ingestion_uploaded_files",
        )

        add_clicked = st.form_submit_button("Add Files", use_container_width=True)

        if add_clicked:
            do_add_files()


def _render_ingestion_status() -> None:
    status = st.session_state.get("ingestion_status")
    if not status:
        return

    if status.get("type") == "success":
        st.success(status.get("message", ""))
    else:
        st.error(status.get("message", ""))

    for detail in status.get("details", []):
        st.caption(detail)
```

### ~\ragstream\app\ui_metrics.py
```python
# ragstream/app/ui_metrics.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import html
from dataclasses import dataclass

import streamlit as st
import streamlit.components.v1 as components


@dataclass(frozen=True)
class DemoPath:
    path_id: int
    label: str
    subtitle: str
    accent: str
    soft: str
    glow: str
    nodes: tuple[str, ...]


def _demo_paths() -> dict[int, DemoPath]:
    return {
        1: DemoPath(
            path_id=1,
            label="Path 1 — Requirements Audit",
            subtitle="User request → requirements → trace matrix → engineered prompt",
            accent="#38BDF8",
            soft="#E0F7FF",
            glow="rgba(56, 189, 248, 0.55)",
            nodes=("ROOT", "REQ", "TRACE", "PROMPT"),
        ),
        2: DemoPath(
            path_id=2,
            label="Path 2 — Architecture Trace",
            subtitle="User request → architecture → UML view → engineered prompt",
            accent="#A78BFA",
            soft="#F1EAFE",
            glow="rgba(167, 139, 250, 0.55)",
            nodes=("ROOT", "ARCH", "UML", "PROMPT"),
        ),
        3: DemoPath(
            path_id=3,
            label="Path 3 — Code Review",
            subtitle="User request → code → focused files → engineered prompt",
            accent="#34D399",
            soft="#E8FFF4",
            glow="rgba(52, 211, 153, 0.55)",
            nodes=("ROOT", "CODE", "FILES", "PROMPT"),
        ),
        4: DemoPath(
            path_id=4,
            label="Path 4 — Quality Gate",
            subtitle="User request → tests → validation gate → engineered prompt",
            accent="#FBBF24",
            soft="#FFF7DF",
            glow="rgba(251, 191, 36, 0.58)",
            nodes=("ROOT", "TEST", "QUALITY", "PROMPT"),
        ),
        5: DemoPath(
            path_id=5,
            label="Path 5 — Release Brief",
            subtitle="User request → release → status pack → engineered prompt",
            accent="#FB7185",
            soft="#FFF0F3",
            glow="rgba(251, 113, 133, 0.55)",
            nodes=("ROOT", "RELEASE", "STATUS", "PROMPT"),
        ),
    }


def _node_catalog() -> dict[str, dict[str, str]]:
    return {
        "ROOT": {"title": "User Request", "caption": "incoming task", "x": "50", "y": "8"},
        "REQ": {"title": "Requirements", "caption": "rules · scope", "x": "12", "y": "30"},
        "ARCH": {"title": "Architecture", "caption": "system shape", "x": "31", "y": "30"},
        "CODE": {"title": "Code", "caption": "implementation", "x": "50", "y": "30"},
        "TEST": {"title": "Tests", "caption": "evidence", "x": "69", "y": "30"},
        "RELEASE": {"title": "Release", "caption": "delivery", "x": "88", "y": "30"},
        "TRACE": {"title": "Trace Matrix", "caption": "REQ → code", "x": "16", "y": "56"},
        "UML": {"title": "UML View", "caption": "structure", "x": "34", "y": "56"},
        "FILES": {"title": "File Focus", "caption": "exact sources", "x": "50", "y": "56"},
        "QUALITY": {"title": "Quality Gate", "caption": "checks", "x": "66", "y": "56"},
        "STATUS": {"title": "Status Pack", "caption": "summary", "x": "84", "y": "56"},
        "PROMPT": {"title": "Engineered Prompt", "caption": "LLM-ready", "x": "50", "y": "82"},
    }


def _edge_catalog() -> list[tuple[str, str]]:
    return [
        ("ROOT", "REQ"),
        ("ROOT", "ARCH"),
        ("ROOT", "CODE"),
        ("ROOT", "TEST"),
        ("ROOT", "RELEASE"),
        ("REQ", "TRACE"),
        ("ARCH", "UML"),
        ("CODE", "FILES"),
        ("TEST", "QUALITY"),
        ("RELEASE", "STATUS"),
        ("TRACE", "PROMPT"),
        ("UML", "PROMPT"),
        ("FILES", "PROMPT"),
        ("QUALITY", "PROMPT"),
        ("STATUS", "PROMPT"),
    ]


def _init_metrics_state() -> None:
    if "metrics_demo_active_path" not in st.session_state:
        st.session_state["metrics_demo_active_path"] = 1


def _active_path_id() -> int:
    try:
        value = int(st.session_state.get("metrics_demo_active_path", 1))
    except Exception:
        value = 1

    if value not in _demo_paths():
        value = 1

    return value


def _set_active_path(path_id: int) -> None:
    st.session_state["metrics_demo_active_path"] = int(path_id)


def _render_path_selector() -> DemoPath:
    paths = _demo_paths()
    active_id = _active_path_id()

    st.markdown("### Interactive Flow Demo")

    left, right = st.columns([1.1, 2.9], gap="medium")

    with left:
        selected_path_id = st.number_input(
            "Choose active path",
            min_value=1,
            max_value=5,
            value=active_id,
            step=1,
            key="metrics_demo_path_number",
        )
        _set_active_path(int(selected_path_id))

    active_path = paths[_active_path_id()]

    with right:
        st.markdown(
            f"""
            <div style="
                border:1px solid rgba(30,41,59,0.10);
                border-radius:18px;
                padding:0.75rem 1rem;
                background:linear-gradient(90deg, {active_path.soft}, #ffffff);
                box-shadow:0 8px 22px rgba(15,23,42,0.06);
            ">
                <div style="font-size:1.05rem; font-weight:800; color:#1f2937;">
                    {html.escape(active_path.label)}
                </div>
                <div style="font-size:0.92rem; color:#64748b; margin-top:0.15rem;">
                    {html.escape(active_path.subtitle)}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    return active_path


def _is_active_node(node_id: str, active_path: DemoPath) -> bool:
    return node_id in active_path.nodes


def _is_active_edge(edge: tuple[str, str], active_path: DemoPath) -> bool:
    src, dst = edge
    nodes = list(active_path.nodes)

    for i in range(len(nodes) - 1):
        if nodes[i] == src and nodes[i + 1] == dst:
            return True

    return False


def _edge_svg(
    src_id: str,
    dst_id: str,
    nodes: dict[str, dict[str, str]],
    active: bool,
    active_path: DemoPath,
) -> str:
    src = nodes[src_id]
    dst = nodes[dst_id]

    x1 = float(src["x"])
    y1 = float(src["y"]) + 5.9
    x2 = float(dst["x"])
    y2 = float(dst["y"]) - 5.9

    edge_class = "edge active-edge" if active else "edge"
    stroke = active_path.accent if active else "#CBD5E1"
    width = "1.75" if active else "0.85"

    return (
        f'<path class="{edge_class}" '
        f'd="M {x1} {y1} C {x1} {(y1 + y2) / 2}, {x2} {(y1 + y2) / 2}, {x2} {y2}" '
        f'stroke="{stroke}" stroke-width="{width}" fill="none" />'
    )


def _node_svg(
    node_id: str,
    data: dict[str, str],
    active: bool,
    active_path: DemoPath,
) -> str:
    x = float(data["x"])
    y = float(data["y"])

    title = html.escape(data["title"])
    caption = html.escape(data["caption"])

    if active:
        fill = active_path.soft
        stroke = active_path.accent
        title_color = "#0F172A"
        caption_color = "#334155"
        node_class = "node active-node"
    else:
        fill = "#F8FAFC"
        stroke = "#E2E8F0"
        title_color = "#475569"
        caption_color = "#94A3B8"
        node_class = "node"

    return f"""
    <g class="{node_class}" transform-origin="{x}px {y}px">
        <rect
            x="{x - 8.9}"
            y="{y - 5.0}"
            width="17.8"
            height="10.0"
            rx="5.0"
            fill="{fill}"
            stroke="{stroke}"
            stroke-width="0.9"
        />
        <text
            x="{x}"
            y="{y - 0.9}"
            text-anchor="middle"
            font-size="2.15"
            font-weight="800"
            fill="{title_color}"
        >{title}</text>
        <text
            x="{x}"
            y="{y + 2.25}"
            text-anchor="middle"
            font-size="1.55"
            font-weight="500"
            fill="{caption_color}"
        >{caption}</text>
    </g>
    """


def _legend_card(path_id: int, active_path: DemoPath) -> str:
    paths = _demo_paths()
    path = paths[path_id]

    css_class = "legend-card"
    if path_id == active_path.path_id:
        css_class += " legend-card-active"

    short_name = path.label.replace(f"Path {path_id} — ", "")

    return f"""
    <div class="{css_class}">
        <div class="legend-number">Path {path_id}</div>
        <div class="legend-name">{html.escape(short_name)}</div>
    </div>
    """


def _build_flow_html(active_path: DemoPath) -> str:
    nodes = _node_catalog()
    edges = _edge_catalog()

    svg_edges = "\n".join(
        _edge_svg(
            src_id=edge[0],
            dst_id=edge[1],
            nodes=nodes,
            active=_is_active_edge(edge, active_path),
            active_path=active_path,
        )
        for edge in edges
    )

    svg_nodes = "\n".join(
        _node_svg(
            node_id=node_id,
            data=data,
            active=_is_active_node(node_id, active_path),
            active_path=active_path,
        )
        for node_id, data in nodes.items()
    )

    legend_cards = "\n".join(
        _legend_card(path_id, active_path)
        for path_id in range(1, 6)
    )

    return f"""
    <!doctype html>
    <html>
    <head>
        <meta charset="utf-8" />
        <style>
            html, body {{
                margin: 0;
                padding: 0;
                background: transparent;
                font-family:
                    -apple-system,
                    BlinkMacSystemFont,
                    "Segoe UI",
                    Roboto,
                    Helvetica,
                    Arial,
                    sans-serif;
            }}

            .ghost-flow-shell {{
                box-sizing: border-box;
                width: 100%;
                padding: 20px 22px 22px 22px;
                border-radius: 28px;
                background:
                    radial-gradient(circle at 18% 20%, rgba(56,189,248,0.16), transparent 24%),
                    radial-gradient(circle at 82% 28%, rgba(167,139,250,0.14), transparent 25%),
                    radial-gradient(circle at 45% 92%, rgba(52,211,153,0.13), transparent 30%),
                    linear-gradient(180deg, #FFFFFF 0%, #F8FAFC 100%);
                border: 1px solid rgba(148,163,184,0.24);
                box-shadow:
                    0 24px 58px rgba(15,23,42,0.08),
                    inset 0 1px 0 rgba(255,255,255,0.92);
            }}

            .title-row {{
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
                gap: 18px;
                margin-bottom: 12px;
            }}

            .title-main {{
                font-size: 22px;
                font-weight: 850;
                letter-spacing: 0.01em;
                color: #111827;
                line-height: 1.15;
            }}

            .title-sub {{
                margin-top: 5px;
                color: #64748B;
                font-size: 14px;
            }}

            .active-pill {{
                white-space: nowrap;
                font-size: 13px;
                font-weight: 800;
                color: #334155;
                background: {active_path.soft};
                border: 1px solid {active_path.accent};
                border-radius: 999px;
                padding: 8px 14px;
                box-shadow:
                    0 8px 20px rgba(15,23,42,0.07),
                    0 0 18px {active_path.glow};
            }}

            .svg-wrap {{
                width: 100%;
                overflow: hidden;
                border-radius: 22px;
                background:
                    linear-gradient(rgba(148,163,184,0.06) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(148,163,184,0.06) 1px, transparent 1px),
                    rgba(255,255,255,0.78);
                background-size: 28px 28px;
                border: 1px solid rgba(226,232,240,0.95);
            }}

            svg {{
                display: block;
                width: 100%;
                height: 560px;
            }}

            .edge {{
                opacity: 0.72;
                stroke-linecap: round;
            }}

            .active-edge {{
                opacity: 1.0;
                filter: drop-shadow(0 0 3px {active_path.accent});
                stroke-dasharray: 2.8 2.0;
                animation:
                    ghostDash 1.1s linear infinite,
                    ghostEdgePulse 1.55s ease-in-out infinite;
            }}

            .node rect {{
                filter: drop-shadow(0 5px 8px rgba(15,23,42,0.10));
            }}

            .active-node rect {{
                filter:
                    drop-shadow(0 0 7px {active_path.accent})
                    drop-shadow(0 12px 16px rgba(15,23,42,0.14));
                animation: ghostNodePulse 1.55s ease-in-out infinite;
            }}

            @keyframes ghostNodePulse {{
                0% {{
                    opacity: 0.88;
                    transform: scale(1);
                }}
                50% {{
                    opacity: 1.0;
                    transform: scale(1.018);
                }}
                100% {{
                    opacity: 0.88;
                    transform: scale(1);
                }}
            }}

            @keyframes ghostEdgePulse {{
                0% {{
                    opacity: 0.60;
                }}
                50% {{
                    opacity: 1.0;
                }}
                100% {{
                    opacity: 0.60;
                }}
            }}

            @keyframes ghostDash {{
                from {{
                    stroke-dashoffset: 0;
                }}
                to {{
                    stroke-dashoffset: -18;
                }}
            }}

            .legend {{
                display: grid;
                grid-template-columns: repeat(5, minmax(0, 1fr));
                gap: 10px;
                margin-top: 13px;
            }}

            .legend-card {{
                box-sizing: border-box;
                border-radius: 16px;
                padding: 11px 12px;
                border: 1px solid rgba(148,163,184,0.22);
                background: rgba(255,255,255,0.74);
                color: #475569;
                font-size: 12px;
                min-height: 62px;
            }}

            .legend-card-active {{
                border-color: {active_path.accent};
                background: {active_path.soft};
                color: #0F172A;
                box-shadow:
                    0 10px 24px rgba(15,23,42,0.08),
                    0 0 18px {active_path.glow};
            }}

            .legend-number {{
                font-weight: 900;
                margin-bottom: 3px;
            }}

            .legend-name {{
                font-weight: 750;
                line-height: 1.2;
            }}
        </style>
    </head>

    <body>
        <div class="ghost-flow-shell">
            <div class="title-row">
                <div>
                    <div class="title-main">GHOST Pipeline Tree — Interactive Path Demo</div>
                    <div class="title-sub">
                        Select a number from 1 to 5. The active route receives stronger color, glow, and motion.
                    </div>
                </div>
                <div class="active-pill">
                    Active: {html.escape(active_path.label)}
                </div>
            </div>

            <div class="svg-wrap">
                <svg viewBox="0 0 100 92" preserveAspectRatio="xMidYMid meet">
                    {svg_edges}
                    {svg_nodes}
                </svg>
            </div>

            <div class="legend">
                {legend_cards}
            </div>
        </div>
    </body>
    </html>
    """


def _render_flow_chart(active_path: DemoPath) -> None:
    flow_html = _build_flow_html(active_path)
    components.html(flow_html, height=720, scrolling=False)


def render_metrics_tab() -> None:
    """METRICS tab demo with an interactive visual flowchart."""
    _init_metrics_state()

    st.markdown("## Metrics")
    st.info(
        "Demo page: this visualizes how a future GHOST metrics / pipeline cockpit could show active execution paths."
    )

    active_path = _render_path_selector()
    _render_flow_chart(active_path)

    st.markdown("### Selected Path")
    st.markdown(
        f"""
        <div style="
            border-left:5px solid {active_path.accent};
            background:{active_path.soft};
            border-radius:14px;
            padding:0.85rem 1rem;
            margin-top:0.75rem;
            color:#1f2937;
        ">
            <div style="font-weight:850; font-size:1rem;">
                {html.escape(active_path.label)}
            </div>
            <div style="margin-top:0.2rem; color:#475569;">
                {html.escape(active_path.subtitle)}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
```

### ~\ragstream\app\ui_settings.py
```python
# ragstream/app/ui_settings.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import streamlit as st


def render_settings_tab() -> None:
    """GENERAL SETTINGS tab placeholder."""
    st.markdown("## General Settings")
    st.info("General Settings tab placeholder.")
```

### ~\ragstream\app\ui_streamlit.py
```python
# ragstream/app/ui_streamlit.py
# -*- coding: utf-8 -*-
"""
Run on a free port, e.g.:
  /home/rusbeh_ab/venvs/ragstream/bin/python -m streamlit run /home/rusbeh_ab/project/RAGstream/ragstream/app/ui_streamlit.py --server.port 8503
"""

from __future__ import annotations

import html
import json
import threading

from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from ragstream.app.controller import AppController
from ragstream.app.ui_layout import inject_base_css, render_page
from ragstream.app.ui_files import render_files_tab
from ragstream.app.ui_metrics import render_metrics_tab
from ragstream.app.ui_settings import render_settings_tab
from ragstream.ingestion.embedder import Embedder
from ragstream.memory.ingestion.memory_chunker import MemoryChunker
from ragstream.memory.ingestion.memory_ingestion_manager import MemoryIngestionManager
from ragstream.memory.memory_manager import MemoryManager
from ragstream.memory.ingestion.memory_vector_store import MemoryVectorStore
from ragstream.orchestration.super_prompt import SuperPrompt
from ragstream.textforge.RagLog import LogALL as logger
from ragstream.textforge.RagLog import LogDeveloper as _logger_dev

DEV_LOG_ENABLED = False


def logger_dev(*args, **kwargs):
    if DEV_LOG_ENABLED:
        return _logger_dev(*args, **kwargs)
    return None


def _load_runtime_config(project_root: Path) -> dict[str, Any]:
    """
    Read ragstream/config/runtime_config.json during Streamlit startup.

    This config is used for Memory Retrieval limits and later runtime defaults.
    """
    config_path = project_root / "ragstream" / "config" / "runtime_config.json"

    if not config_path.exists():
        logger(f"runtime_config.json not found: {config_path}", "WARN", "PUBLIC")
        return {}

    try:
        with config_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError("runtime_config.json root must be a JSON object.")

        logger("runtime_config.json loaded in Streamlit session.", "INFO", "INTERNAL")

        logger_dev(
            "runtime_config.json loaded in Streamlit session\n"
            + json.dumps(data, ensure_ascii=False, indent=2, default=str),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return data

    except Exception as e:
        logger(f"Failed to load runtime_config.json: {e}", "ERROR", "PUBLIC")
        return {}


def init_session_state() -> None:
    """
    Create one controller + one SuperPrompt set per user session.

    Startup also initializes:
    - MemoryManager
    - MemoryVectorStore
    - MemoryIngestionManager
    - MemoryRetriever wiring through AppController.configure_memory_retrieval(...)
    """
    project_root = Path(__file__).resolve().parents[2]

    if "runtime_config" not in st.session_state:
        st.session_state.runtime_config = _load_runtime_config(project_root)

    if "controller" not in st.session_state:
        ctrl = AppController()
        st.session_state.controller = ctrl

    if "textforge_gui_log" not in st.session_state:
        st.session_state["textforge_gui_log"] = ""

    if "memory_manager" not in st.session_state:
        memory_root = project_root / "data" / "memory"
        sqlite_path = memory_root / "memory_index.sqlite3"

        st.session_state.memory_manager = MemoryManager(
            memory_root=memory_root,
            sqlite_path=sqlite_path,
            title="",
        )

    if "memory_vector_store" not in st.session_state:
        memory_root = project_root / "data" / "memory"
        memory_vector_root = memory_root / "vector_db"

        memory_embedder = Embedder(model="text-embedding-3-large")

        st.session_state.memory_vector_store = MemoryVectorStore(
            persist_dir=str(memory_vector_root),
            collection_name="memory_vectors",
            embedder=memory_embedder,
        )

    if "memory_chunker" not in st.session_state:
        st.session_state.memory_chunker = MemoryChunker()

    if "memory_ingestion_manager" not in st.session_state:
        st.session_state.memory_ingestion_manager = MemoryIngestionManager(
            memory_manager=st.session_state.memory_manager,
            memory_chunker=st.session_state.memory_chunker,
            memory_vector_store=st.session_state.memory_vector_store,
        )

        logger(
            "Memory ingestion layer ready: data/memory/vector_db/ | collection=memory_vectors",
            "INFO",
            "PUBLIC",
        )

    if "memory_retrieval_configured" not in st.session_state:
        st.session_state["memory_retrieval_configured"] = False

    if not st.session_state["memory_retrieval_configured"]:
        ctrl: AppController = st.session_state.controller
        ctrl.configure_memory_retrieval(
            memory_manager=st.session_state.memory_manager,
            memory_vector_store=st.session_state.memory_vector_store,
            runtime_config=st.session_state.runtime_config,
        )
        st.session_state["memory_retrieval_configured"] = True

    if "heavy_init_started" not in st.session_state:
        st.session_state["heavy_init_started"] = False

    if not st.session_state["heavy_init_started"]:
        ctrl = st.session_state.controller

        t = threading.Thread(
            target=ctrl.initialize_heavy_components,
            daemon=True,
        )
        t.start()

        st.session_state["heavy_init_started"] = True

    if "sp" not in st.session_state:
        st.session_state.sp = SuperPrompt()
    if "sp_pre" not in st.session_state:
        st.session_state.sp_pre = SuperPrompt()
    if "sp_a2" not in st.session_state:
        st.session_state.sp_a2 = SuperPrompt()
    if "sp_rtv" not in st.session_state:
        st.session_state.sp_rtv = SuperPrompt()
    if "sp_rrk" not in st.session_state:
        st.session_state.sp_rrk = SuperPrompt()
    if "sp_a3" not in st.session_state:
        st.session_state.sp_a3 = SuperPrompt()
    if "sp_a4" not in st.session_state:
        st.session_state.sp_a4 = SuperPrompt()

    if "super_prompt_text" not in st.session_state:
        st.session_state["super_prompt_text"] = ""

    if "ingestion_status" not in st.session_state:
        st.session_state["ingestion_status"] = None

    if "new_project_name" not in st.session_state:
        st.session_state["new_project_name"] = ""

    if "pending_active_project" not in st.session_state:
        st.session_state["pending_active_project"] = None

    if "retrieval_top_k" not in st.session_state:
        st.session_state["retrieval_top_k"] = 30

    if "use_a2_promptshaper_llm" not in st.session_state:
        st.session_state["use_a2_promptshaper_llm"] = True

    if "use_retrieval_splade" not in st.session_state:
        st.session_state["use_retrieval_splade"] = False

    if "use_reranking_colbert" not in st.session_state:
        st.session_state["use_reranking_colbert"] = False

    if "use_a2_promptshaper_llm_widget" not in st.session_state:
        st.session_state["use_a2_promptshaper_llm_widget"] = bool(
            st.session_state["use_a2_promptshaper_llm"]
        )

    if "use_retrieval_splade_widget" not in st.session_state:
        st.session_state["use_retrieval_splade_widget"] = bool(
            st.session_state["use_retrieval_splade"]
        )

    if "use_reranking_colbert_widget" not in st.session_state:
        st.session_state["use_reranking_colbert_widget"] = bool(
            st.session_state["use_reranking_colbert"]
        )

    if "manual_memory_feed_text" not in st.session_state:
        st.session_state["manual_memory_feed_text"] = ""

    if "show_advanced_controls" not in st.session_state:
        st.session_state["show_advanced_controls"] = False

    if "enable_file_ingestion_controls" not in st.session_state:
        st.session_state["enable_file_ingestion_controls"] = False

    if "active_sidebar_page" not in st.session_state:
        st.session_state["active_sidebar_page"] = "Main"

    if "sidebar_pipeline_active_step" not in st.session_state:
        st.session_state["sidebar_pipeline_active_step"] = 0

    if "sidebar_pipeline_completed_step" not in st.session_state:
        st.session_state["sidebar_pipeline_completed_step"] = -1


def _page_options() -> list[str]:
    return [
        "Main",
        "Files",
        "Hard Rules",
        "Metrics",
        "General Settings",
    ]


def _sidebar_pipeline_steps() -> list[str]:
    return [
        "User Prompt",
        "Prompt Qualification",
        "Prompt Shaping",
        "Memory Context",
        "Document Evidence",
        "Context Synthesis",
        "Hard Rule Integration",
        "LLM-Ready Context",
    ]


def _init_page_state() -> None:
    if "active_sidebar_page" not in st.session_state:
        st.session_state["active_sidebar_page"] = "Main"

    if st.session_state["active_sidebar_page"] not in _page_options():
        st.session_state["active_sidebar_page"] = "Main"


def _render_sidebar_flowchart() -> None:
    steps = _sidebar_pipeline_steps()

    try:
        active_step = int(st.session_state.get("sidebar_pipeline_active_step", 0) or 0)
    except Exception:
        active_step = 0

    if active_step < 0:
        active_step = 0

    if active_step >= len(steps):
        active_step = len(steps) - 1

    items: list[str] = []

    for index, label in enumerate(steps):
        state_class = " flow-box-active" if index == active_step else ""

        items.append(
            f"""
            <div class="flow-box{state_class}">
                {html.escape(label)}
            </div>
            """
        )

        if index < len(steps) - 1:
            items.append('<div class="flow-arrow">↓</div>')

    flow_html = f"""
    <!doctype html>
    <html>
    <head>
        <meta charset="utf-8" />
        <style>
            html, body {{
                margin: 0;
                padding: 0;
                background: transparent;
                font-family:
                    -apple-system,
                    BlinkMacSystemFont,
                    "Segoe UI",
                    Roboto,
                    Helvetica,
                    Arial,
                    sans-serif;
            }}

            .flow-shell {{
                box-sizing: border-box;
                width: 61.8%;
                margin: 18px auto 0 auto;
                padding: 0;
            }}

            .flow-box {{
                box-sizing: border-box;
                width: 100%;
                min-height: 32px;
                border: 1.3px solid #111111;
                border-radius: 2px;
                background: transparent;
                color: #111111;
                display: flex;
                align-items: center;
                justify-content: center;
                text-align: center;
                padding: 3px 5px;
                font-size: 14px;
                font-weight: 400;
                line-height: 1.12;
            }}

            .flow-box-active {{
                background: #FFF176;
            }}

            .flow-arrow {{
                text-align: center;
                font-size: 18px;
                line-height: 1.05;
                color: #111111;
                margin: 2px 0;
            }}
        </style>
    </head>
    <body>
        <div class="flow-shell">
            {"".join(items)}
        </div>
    </body>
    </html>
    """

    components.html(
        flow_html,
        height=500,
        scrolling=False,
    )


def render_sidebar_navigation() -> str:
    _init_page_state()

    options = _page_options()
    active_page = st.session_state["active_sidebar_page"]

    with st.sidebar:
        st.markdown(
            """
            <div style="
                padding:0.45rem 0.25rem 0.90rem 0.25rem;
            ">
                <div style="
                    font-size:1.55rem;
                    font-weight:800;
                    letter-spacing:0.045em;
                    color:#111827;
                    line-height:1.05;
                ">
                    GHOST
                </div>
                <div style="
                    margin-top:0.32rem;
                    font-size:0.88rem;
                    color:#4B5563;
                    line-height:1.32;
                ">
                    GenAI Hybrid Orchestrator<br>
                    for Software Tooling
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        selected_page = st.radio(
            "Navigation",
            options=options,
            index=options.index(active_page),
            key="sidebar_navigation_radio",
            label_visibility="collapsed",
        )

        st.session_state["active_sidebar_page"] = selected_page

        st.markdown("---")

        if selected_page == "Main":
            st.caption("Main workflow")
            st.caption("Memory · Prompt · Builder · LLM")

            st.checkbox(
                "Enable file ingestion controls",
                key="enable_file_ingestion_controls",
            )

            st.checkbox(
                "Show advanced controls",
                key="show_advanced_controls",
            )

            _render_sidebar_flowchart()

        elif selected_page == "Files":
            st.caption("Memory files and imports")
        elif selected_page == "Hard Rules":
            st.caption("Rule governance")
        elif selected_page == "Metrics":
            st.caption("Metrics and visual pipeline demos")
        elif selected_page == "General Settings":
            st.caption("Runtime configuration")

    return selected_page


def render_active_page(page_name: str) -> None:
    if page_name == "Main":
        render_page()
    elif page_name == "Files":
        render_files_tab()
    elif page_name == "Hard Rules":
        st.markdown("## Hard Rules")
        st.info("Hard Rules tab placeholder.")
    elif page_name == "Metrics":
        render_metrics_tab()
    elif page_name == "General Settings":
        render_settings_tab()
    else:
        render_page()


def main() -> None:
    st.set_page_config(
        page_title="GHOST",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    inject_base_css()

    init_session_state()

    selected_page = render_sidebar_navigation()
    render_active_page(selected_page)


if __name__ == "__main__":
    main()
```


## /home/rusbeh_ab/project/RAGstream/ragstream/config

### ~\ragstream\config\settings.py
```python
"""
Settings
========
Centralised, cached access to environment configuration.
"""
import os
from typing import Any, Dict

class Settings:
    _CACHE: Dict[str, Any] = {}

    @classmethod
    def get(cls, key: str, default: Any | None = None) -> Any:
        if key not in cls._CACHE:
            cls._CACHE[key] = os.getenv(key, default)
        return cls._CACHE[key]
```


## /home/rusbeh_ab/project/RAGstream/ragstream/ingestion

### ~\ragstream\ingestion\chroma_vector_store_base.py
```python
# -*- coding: utf-8 -*-
"""
chroma_vector_store_base.py

Shared, production-grade base class for Chroma-backed vector stores.

Context:
- Replaces the old NumPy PKL store with a persistent, crash-safe, on-disk DB.
- Both VectorStoreChroma and HistoryStoreChroma should inherit from this class.
- We intentionally removed any separate "IVectorStore" interface; this concrete
  base provides the canonical add/query/snapshot API and small hook points so
  subclasses can enforce their own policies without duplicating core logic.

Contract (compatible with your former NumPy store):
    add(ids, vectors, metadatas) -> None
    query(vector, k=10, where=None) -> List[str]
    snapshot(timestamp=None) -> Path

Design notes:
- Uses chromadb.PersistentClient(path=...) to ensure physical persistence on disk.
- Stores ONLY embeddings + metadatas (documents are optional for this project).
- Provides hook methods (_pre_add/_post_add/_pre_query/_post_query) so that the
  history store can enforce selection-only / capacity / eligibility rules later.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import shutil
from datetime import datetime

import chromadb
from chromadb.config import Settings


class ChromaVectorStoreBase:
    """
    Base implementation of a Chroma-backed vector store.

    Responsibilities:
      - Own the PersistentClient and a single collection.
      - Provide simple, deterministic add/query/snapshot methods.
      - Offer policy hooks for subclasses (history vs. document store).

    Subclasses:
      - VectorStoreChroma(ChromaVectorStoreBase)
      - HistoryStoreChroma(ChromaVectorStoreBase)

    Typical metadata for each chunk (recommended):
      {
        "path": "<relative/original file path>",
        "sha256": "<content hash>",
        "mtime": <float or iso string>,
        "chunk_idx": <int>
      }
    """

    def __init__(
        self,
        persist_dir: str,
        collection_name: str,
        *,
        anonymized_telemetry: bool = False,
    ) -> None:
        """
        Initialize a persistent Chroma client and open/create a collection.

        Args:
            persist_dir: Directory where Chroma DB files live (e.g. PATHS.chroma_db).
            collection_name: Logical collection name (e.g. "docs" or "history").
            anonymized_telemetry: Pass False to avoid any telemetry (default False).
        """
        self.persist_path = Path(persist_dir)
        self.persist_path.mkdir(parents=True, exist_ok=True)

        # Settings keep the DB local, file-backed, and quiet (no telemetry).
        self._client = chromadb.PersistentClient(
            path=str(self.persist_path),
            settings=Settings(anonymized_telemetry=anonymized_telemetry),
        )

        self.collection_name = collection_name
        self._col = self._client.get_or_create_collection(self.collection_name)

    # -------------------------------------------------------------------------
    # Public API (stable)
    # -------------------------------------------------------------------------

    def add(
        self,
        ids: List[str],
        vectors: List[List[float]],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """
        Upsert vectors and metadatas into the collection.

        Contract matches the previous NumPy store:
          - ids:      unique stable IDs per chunk (e.g. "path::sha256::i")
          - vectors:  2D list [N, D] of float embeddings
          - metadatas: optional [N] list of dicts (same length as ids)

        Notes:
          - If an id already exists, Chroma upserts (replaces) it.
          - Subclasses may enforce policies via _pre_add/_post_add hooks.
        """
        if not ids or not vectors:
            return
        if len(ids) != len(vectors):
            raise ValueError("ids and vectors length mismatch")
        if metadatas is not None and len(metadatas) != len(ids):
            raise ValueError("metadatas length must match ids (or be None)")

        ids, vectors, metadatas = self._pre_add(ids, vectors, metadatas)

        # Core upsert (embeddings + optional metadatas). Documents are unused here.
        self._col.upsert(
            ids=ids,
            embeddings=vectors,
            metadatas=metadatas,
        )

        self._post_add(ids, vectors, metadatas)

    def query(
        self,
        vector: List[float],
        k: int = 10,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """
        Nearest-neighbor search against the collection by embedding vector.

        Args:
            vector: 1D float embedding of the query.
            k: number of neighbors to return.
            where: optional Chroma metadata filter; pass None for no filter.

        Returns:
            List[str]: top-k IDs (sorted by similarity).
                       This mirrors the former NumPy store return type.

        Subclasses may adjust behavior via _pre_query/_post_query.
        """
        if not isinstance(vector, list) or not vector:
            raise ValueError("query vector must be a non-empty 1D list[float]")

        k = max(1, int(k))

        # IMPORTANT: some Chroma versions reject {} and require None when no filter is used.
        where = None if not where else where

        vector, k, where = self._pre_query(vector, k, where)

        res = self._col.query(
            query_embeddings=[vector],
            n_results=k,
            where=where,               # None means "no filter"
            include=["metadatas"],     # metadatas available for post-processing if needed
        )
        # result shape: {"ids": [[...]], "metadatas": [[...]], ...}
        ids: List[str] = res.get("ids", [[]])[0] if res else []
        ids = self._post_query(ids, res)
        return ids

    def snapshot(self, timestamp: Optional[str] = None) -> Path:
        """
        Create a filesystem snapshot of the current Chroma DB directory.

        Implementation:
          - Copies the entire persist_dir into ./snapshots/<db_name>_<timestamp>/
          - This is a coarse, but deterministic snapshot suitable for local dev.
          - For very large DBs, consider OS-level copy-on-write or backup tooling.

        Returns:
            Path to the created snapshot directory.
        """
        ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
        snapshots_dir = self.persist_path.parent / "snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        dst = snapshots_dir / f"{self.persist_path.name}_{ts}"

        # Copy the whole DB dir. dirs_exist_ok=False to avoid accidental overwrite.
        shutil.copytree(self.persist_path, dst, dirs_exist_ok=False)
        return dst

    # Optional utility, handy for re-ingestion flows that need to remove stale chunks
    def delete_where(self, where: Dict[str, Any]) -> None:
        """
        Delete by metadata filter (two-phase: lookup ids, then delete ids).
        This makes the operation explicit and auditable.
        """
        if not where:
            return
        res = self._col.get(where=where, include=[])  # get ids only
        ids: List[str] = res.get("ids", []) if res else []
        if ids:
            self._col.delete(ids=ids)

    # Expose underlying collection for advanced ops if needed (debug, migration)
    @property
    def collection(self):
        return self._col

    # -------------------------------------------------------------------------
    # Hook methods (subclasses override as needed)
    # -------------------------------------------------------------------------

    def _pre_add(
        self,
        ids: List[str],
        vectors: List[List[float]],
        metadatas: Optional[List[Dict[str, Any]]],
    ) -> tuple[List[str], List[List[float]], Optional[List[Dict[str, Any]]]]:
        """
        Override in subclasses to enforce policies before upsert, e.g.:
          - capacity checks, eviction, dedup, eligibility constraints (history store)
          - metadata normalization or enrichment
        Default: no-op, return inputs unchanged.
        """
        return ids, vectors, metadatas

    def _post_add(
        self,
        ids: List[str],
        vectors: List[List[float]],
        metadatas: Optional[List[Dict[str, Any]]],
    ) -> None:
        """
        Override in subclasses to log / index / audit after upsert.
        Default: no-op.
        """
        return None

    def _pre_query(
        self,
        vector: List[float],
        k: int,
        where: Optional[Dict[str, Any]],
    ) -> tuple[List[float], int, Optional[Dict[str, Any]]]:
        """
        Override in subclasses to enforce query-time policies, e.g.:
          - eligibility alignment (history store)
          - metadata filter injection
        Default: no-op, return inputs unchanged.
        """
        return vector, k, where

    def _post_query(self, ids: List[str], raw_result: Dict[str, Any]) -> List[str]:
        """
        Override in subclasses to transform the result list, e.g.:
          - strip restricted items
          - reorder by additional heuristics
        Default: no-op, return ids unchanged.
        """
        return ids
```

### ~\ragstream\ingestion\chunker.py
```python
"""
Chunker
=======
Splits raw text into overlapping, character-based chunks for embedding.
"""

from typing import List, Tuple

class Chunker:
    """Window-based text splitter."""

    def split(self, file_path: str, text: str, chunk_size: int = 1200, overlap: int = 120) -> List[Tuple[str, str]]:
        """
        Split the given text into overlapping chunks.

        :param file_path: Absolute path to the source file (kept with each chunk)
        :param text: The full text content of the file
        :param chunk_size: Maximum characters per chunk (default=500)
        :param overlap: Number of characters to overlap between chunks (default=100)
        :return: List of (file_path, chunk_text) tuples
        """
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if overlap < 0:
            raise ValueError("overlap must be non-negative")
        if overlap >= chunk_size:
            raise ValueError("overlap must be smaller than chunk_size")

        chunks: List[Tuple[str, str]] = []
        start = 0
        text_length = len(text)

        while start < text_length:
            end = min(start + chunk_size, text_length)
            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append((file_path, chunk_text))
            start += chunk_size - overlap

        return chunks
```

### ~\ragstream\ingestion\embedder.py
```python
"""
Embedder
========
Wraps OpenAI embeddings API to convert text chunks into dense vectors.
"""
from typing import List
import os
from dotenv import load_dotenv
from openai import OpenAI

class Embedder:
    """High-level embedding interface using OpenAI API."""
    def __init__(self, model: str = "text-embedding-3-small"):
        load_dotenv()  # Load .env file
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment or .env file")

        self.client = OpenAI(api_key=api_key)
        self.model = model

    def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for a list of texts.
        Returns: list of embedding vectors (one per text)
        """
        if not texts:
            return []

        # OpenAI API allows batch embedding calls
        response = self.client.embeddings.create(
            model=self.model,
            input=texts
        )

        # Extract embeddings from response
        embeddings = [item.embedding for item in response.data]
        return embeddings
```

### ~\ragstream\ingestion\file_manifest.py
```python
# -*- coding: utf-8 -*-
"""
file_manifest.py

Purpose:
    A tiny, deterministic "ledger" for document ingestion. It tells the
    ingestion pipeline which files have changed since last run so we only
    re-chunk/re-embed what's necessary.

What this module provides:
    1) compute_sha256(file_path) -> str
       - Returns the SHA-256 hex digest for ONE file on disk.

    2) load_manifest(manifest_path) -> dict
       - Loads the last published manifest JSON (or returns an empty one).

    3) diff(records_now, manifest_prev) -> (to_process, unchanged, tombstones)
       - Compares current scan results ("records_now") against the previous
         manifest ("manifest_prev") and decides what to ingest or clean up.

    4) publish_atomic(manifest_dict, manifest_path) -> None
       - Writes the ENTIRE manifest JSON atomically: *.tmp then os.replace.

Data shapes:
    Record (one per file; used both during scan and inside the manifest):
        {
          "path":   str,    # RELATIVE path from doc root, e.g. "project1/file.md"
          "sha256": str,    # content hash (hex)
          "mtime":  float,  # UNIX mtime
          "size":   int     # bytes
        }

    Manifest JSON written to disk:
        {
          "version": "1",
          "generated_at": "YYYY-MM-DDTHH:MM:SSZ",
          "files": [Record, Record, ...]
        }

Notes:
    - This module does NOT scan directories. IngestionManager (or caller) is
      responsible for building 'records_now' from the doc root using compute_sha256.
    - 'diff' expects 'records_now' as a list[Record] and the previous manifest dict.
    - 'tombstones' are files that were present in the previous manifest but are
      missing on disk now (useful for deleting stale vectors).
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple, TypedDict


# ---------------------------------------------------------------------------
# Typed structures for clarity (no runtime dependency; just type hints)
# ---------------------------------------------------------------------------

class Record(TypedDict):
    """A single file's state at scan time (also stored in the manifest)."""
    path: str     # relative path from doc root, POSIX style (e.g., "project1/file.md")
    sha256: str   # hex SHA-256 of the file contents
    mtime: float  # last modified time (float UNIX timestamp)
    size: int     # file size in bytes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_sha256(file_path: str, *, chunk_size: int = 1024 * 1024) -> str:
    """
    Compute a SHA-256 hex digest for a SINGLE file.

    Args:
        file_path: absolute or relative path to a file on disk.
        chunk_size: read size in bytes (default 1MB) to handle large files safely.

    Returns:
        The hex string of the SHA-256 content hash.

    Raises:
        FileNotFoundError: if the file does not exist.
        IsADirectoryError: if 'file_path' is a directory.
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if p.is_dir():
        raise IsADirectoryError(f"Expected a file, got directory: {file_path}")

    h = hashlib.sha256()
    with p.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def load_manifest(manifest_path: str) -> Dict[str, Any]:
    """
    Load the manifest JSON if it exists; otherwise, return a valid empty structure.

    Args:
        manifest_path: full filesystem path to 'file_manifest.json'.

    Returns:
        Dict with keys:
            - "version": "1"
            - "generated_at": ISO-8601 string (UTC) or ""
            - "files": list[Record]
    """
    mp = Path(manifest_path)
    if not mp.exists():
        # Return a deterministic empty manifest structure.
        return {
            "version": "1",
            "generated_at": "",
            "files": [],
        }

    try:
        with mp.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        # If the file is corrupted, fail loudly; caller can decide what to do.
        raise ValueError(f"Manifest is not valid JSON: {manifest_path}") from e

    # Normalize to expected keys (be forgiving about missing keys).
    if "version" not in data:
        data["version"] = "1"
    if "generated_at" not in data:
        data["generated_at"] = ""
    if "files" not in data or not isinstance(data["files"], list):
        data["files"] = []

    return data


def diff(
    records_now: List[Record],
    manifest_prev: Dict[str, Any],
) -> Tuple[List[Record], List[Record], List[Record]]:
    """
    Compare the current scan against the previous manifest.

    Args:
        records_now: list of current file Records (built by the caller during scan).
        manifest_prev: manifest dict as returned by load_manifest().

    Returns:
        (to_process, unchanged, tombstones)
            to_process: Records that are NEW or CHANGED (sha256 differs).
            unchanged:  Records that are IDENTICAL to previous (same path + sha256).
            tombstones: Records from the PREVIOUS manifest that are MISSING now on disk.

    Matching logic:
        - Key by 'path'.
        - If 'path' is new (not in previous) => to_process.
        - If 'path' exists but sha256 changed => to_process.
        - Else => unchanged.
        - tombstones = previous paths not present in records_now.
    """
    prev_files = manifest_prev.get("files", []) if isinstance(manifest_prev, dict) else []

    # Build fast lookups by path.
    prev_by_path: Dict[str, Record] = {rec["path"]: rec for rec in prev_files}  # type: ignore[typeddict-item]
    now_by_path: Dict[str, Record] = {rec["path"]: rec for rec in records_now}

    to_process: List[Record] = []
    unchanged: List[Record] = []
    tombstones: List[Record] = []

    # Decide new/changed vs unchanged.
    for path, now_rec in now_by_path.items():
        prev_rec = prev_by_path.get(path)
        if prev_rec is None:
            # New file.
            to_process.append(now_rec)
        else:
            # Same path existed previously; compare hashes.
            if str(prev_rec["sha256"]) != str(now_rec["sha256"]):
                to_process.append(now_rec)   # Content changed.
            else:
                unchanged.append(now_rec)    # Identical (skip re-ingest).

    # Anything in previous but not in current is a tombstone (missing on disk).
    for path, prev_rec in prev_by_path.items():
        if path not in now_by_path:
            tombstones.append(prev_rec)

    return to_process, unchanged, tombstones


def publish_atomic(manifest_dict: Dict[str, Any], manifest_path: str) -> None:
    """
    Atomically write the ENTIRE manifest JSON to disk.

    Implementation:
        - Ensure parent directory exists.
        - Write to <manifest_path>.tmp with UTF-8 + pretty JSON.
        - os.replace(tmp, manifest_path) for atomic swap (POSIX-safe).

    Args:
        manifest_dict: the full manifest payload to persist.
        manifest_path: destination JSON path, e.g. ".../data/file_manifest.json".
    """
    mp = Path(manifest_path)
    mp.parent.mkdir(parents=True, exist_ok=True)

    # Stamp/refresh generated_at if caller forgot; harmless overwrite is fine.
    if "generated_at" not in manifest_dict:
        manifest_dict["generated_at"] = _utc_now_iso()
    else:
        # If present but empty, also refresh.
        if not manifest_dict["generated_at"]:
            manifest_dict["generated_at"] = _utc_now_iso()

    tmp_path = mp.with_suffix(mp.suffix + ".tmp")

    # Write JSON with a stable format (sorted keys, indentation).
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(manifest_dict, f, ensure_ascii=False, indent=2, sort_keys=True)

    # Atomic replace: either the old file stays, or the new one fully replaces it.
    os.replace(str(tmp_path), str(mp))


# ---------------------------------------------------------------------------
# Internal helpers (not part of the public API)
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    """Return a UTC timestamp in ISO-8601 format with 'Z' suffix."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
```

### ~\ragstream\ingestion\ingestion_manager.py
```python
# -*- coding: utf-8 -*-
"""
ingestion_manager.py

Purpose:
    Orchestrate deterministic document ingestion for RAGstream:
      scan → diff vs. manifest → chunk → embed → store → publish manifest

Scope:
    • This module focuses on the "documents" ingestion path only
      (conversation history layers are postponed as agreed).
    • Works with your existing loader, chunker, embedder, and Chroma vector store.
    • Also supports an optional parallel SPLADE sparse-ingestion branch.

Notes:
    • We compute file hashes from bytes on disk (compute_sha256), NOT from text.
    • Chunk IDs are stable: f"{rel_path}::{sha256}::{idx}" (matches your store helpers).
    • We only publish a new manifest after all target files in this run succeed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

# Local imports: existing dense components
from .loader import DocumentLoader
from .chunker import Chunker
from .embedder import Embedder
from .vector_store_chroma import VectorStoreChroma

# Added on 13.04.2026:
# Optional sparse SPLADE ingestion components.
from .splade_embedder import SpladeEmbedder
from .vector_store_splade import VectorStoreSplade

# Manifest utilities
from .file_manifest import (
    compute_sha256,
    load_manifest,
    diff as manifest_diff,
    publish_atomic,
    Record,
)


@dataclass(frozen=True)
class IngestionStats:
    """Aggregate numbers for quick reporting / testing."""
    files_scanned: int
    to_process: int
    unchanged: int
    tombstones: int
    chunks_added: int
    vectors_upserted: int
    deleted_old_versions: int
    deleted_tombstones: int
    published_manifest_path: str
    embedded_bytes: int

    # Added on 13.04.2026:
    # Split counters for the parallel dense + sparse branches.
    dense_vectors_upserted: int
    sparse_vectors_upserted: int
    dense_embedded_bytes: int
    sparse_embedded_bytes: int


class IngestionManager:
    """
    Coordinates the full ingestion pipeline for a given doc root.
    """

    def __init__(self, doc_root: str) -> None:
        """
        Args:
            doc_root: Absolute path to the "doc_raw" root folder.
        """
        self.doc_root = Path(doc_root).resolve()
        if not self.doc_root.exists():
            raise FileNotFoundError(f"doc_root does not exist: {self.doc_root}")
        if not self.doc_root.is_dir():
            raise NotADirectoryError(f"doc_root is not a directory: {self.doc_root}")

        # A loader is tied to a root; it returns absolute file paths + text for a subfolder
        self.loader = DocumentLoader(root=self.doc_root)

    def run(
        self,
        subfolder: str,
        store: VectorStoreChroma,
        chunker: Chunker,
        embedder: Embedder,
        manifest_path: str,
        *,
        sparse_store: VectorStoreSplade | None = None,
        sparse_embedder: SpladeEmbedder | None = None,
        chunk_size: int = 1200,
        overlap: int = 120,
        delete_old_versions: bool = True,
        delete_tombstones: bool = False,
    ) -> IngestionStats:
        """
        Execute a full ingestion cycle for one subfolder under doc_root.

        Dense branch is always active.
        Sparse SPLADE branch is active only if both sparse_store and sparse_embedder are provided.

        Returns:
            IngestionStats with useful counters.
        """
        manifest_path = str(Path(manifest_path).resolve())

        use_sparse = (sparse_store is not None) or (sparse_embedder is not None)
        if use_sparse and (sparse_store is None or sparse_embedder is None):
            raise ValueError(
                "Sparse ingestion requires both sparse_store and sparse_embedder."
            )

        # 1) Load documents (absolute path + raw text) from the subfolder.
        docs = self.loader.load_documents(subfolder)
        text_by_abs: Dict[str, str] = {abs_path: text for abs_path, text in docs}

        # 2) Build current Records by hashing files on disk (bytes).
        records_now: List[Record] = []
        for abs_path, _text in docs:
            ap = Path(abs_path)
            rel_path = ap.relative_to(self.doc_root).as_posix()
            sha = compute_sha256(abs_path)
            st = ap.stat()
            records_now.append({
                "path": rel_path,
                "sha256": sha,
                "mtime": float(st.st_mtime),
                "size": int(st.st_size),
            })

        # 3) Load the previous manifest and compute the diff.
        manifest_prev = load_manifest(manifest_path)
        to_process, unchanged, tombstones = manifest_diff(records_now, manifest_prev)

        prev_by_path: Dict[str, Record] = {
            rec["path"]: rec for rec in manifest_prev.get("files", [])
        }

        # 4) Process changed/new files (shared chunking pass → dense and optional sparse upsert).
        total_chunks = 0
        total_deleted_old = 0

        dense_upserts = 0
        sparse_upserts = 0

        dense_embedded_bytes = 0
        sparse_embedded_bytes = 0

        for rec in to_process:
            rel_path = rec["path"]
            sha_new = rec["sha256"]

            abs_path = (self.doc_root / rel_path).as_posix()
            text = text_by_abs.get(abs_path)
            if text is None:
                text = Path(abs_path).read_text(encoding="utf-8", errors="ignore")

            chunks = chunker.split(abs_path, text, chunk_size=chunk_size, overlap=overlap)
            chunk_texts: List[str] = []
            ids: List[str] = []
            metas: List[Dict[str, Any]] = []

            for idx, (_fp, chunk_txt) in enumerate(chunks):
                if not chunk_txt.strip():
                    continue
                chunk_texts.append(chunk_txt)
                ids.append(store.make_chunk_id(rel_path, sha_new, idx))
                metas.append({
                    "path": rel_path,
                    "sha256": sha_new,
                    "chunk_idx": idx,
                    "mtime": rec["mtime"],
                })

            if not chunk_texts:
                continue

            if delete_old_versions and rel_path in prev_by_path:
                sha_old = prev_by_path[rel_path]["sha256"]
                if sha_old != sha_new:
                    total_deleted_old += self._delete_file_version(store, rel_path, sha_old)
                    if use_sparse and sparse_store is not None:
                        total_deleted_old += self._delete_file_version(sparse_store, rel_path, sha_old)

            file_embedded_bytes = sum(len(s.encode("utf-8")) for s in chunk_texts)

            # Dense branch
            dense_vecs = embedder.embed(chunk_texts)
            store.add(ids=ids, vectors=dense_vecs, metadatas=metas)
            dense_upserts += len(ids)
            dense_embedded_bytes += file_embedded_bytes

            # Optional sparse branch
            if use_sparse and sparse_store is not None and sparse_embedder is not None:
                sparse_vecs = sparse_embedder.embed(chunk_texts)
                sparse_store.add(ids=ids, vectors=sparse_vecs, metadatas=metas)
                sparse_upserts += len(ids)
                sparse_embedded_bytes += file_embedded_bytes

            total_chunks += len(chunk_texts)

        # 5) Optionally delete tombstones (files that disappeared from disk).
        total_deleted_tombs = 0
        if delete_tombstones and tombstones:
            for prev_rec in tombstones:
                rel_path = prev_rec["path"]
                sha_prev = prev_rec["sha256"]

                total_deleted_tombs += self._delete_file_version(store, rel_path, sha_prev)
                if use_sparse and sparse_store is not None:
                    total_deleted_tombs += self._delete_file_version(sparse_store, rel_path, sha_prev)

        # 6) Publish a fresh manifest that reflects the CURRENT disk state.
        manifest_new = {
            "version": "1",
            "generated_at": "",
            "files": records_now,
        }
        publish_atomic(manifest_new, manifest_path)

        return IngestionStats(
            files_scanned=len(records_now),
            to_process=len(to_process),
            unchanged=len(unchanged),
            tombstones=len(tombstones),
            chunks_added=total_chunks,
            vectors_upserted=dense_upserts + sparse_upserts,
            deleted_old_versions=total_deleted_old,
            deleted_tombstones=total_deleted_tombs,
            published_manifest_path=manifest_path,
            embedded_bytes=dense_embedded_bytes + sparse_embedded_bytes,
            dense_vectors_upserted=dense_upserts,
            sparse_vectors_upserted=sparse_upserts,
            dense_embedded_bytes=dense_embedded_bytes,
            sparse_embedded_bytes=sparse_embedded_bytes,
        )

    @staticmethod
    def _delete_file_version(store: Any, rel_path: str, sha256: str) -> int:
        """
        Remove all chunks belonging to one specific file version.

        Uses the store's native delete_file_version(...) when available.
        Falls back to metadata-filter delete_where(...) if needed.
        """
        if hasattr(store, "delete_file_version"):
            return int(store.delete_file_version(rel_path, sha256))

        before = IngestionManager._count_ids(store, rel_path, sha256)
        store.delete_where({"$and": [{"path": rel_path}, {"sha256": sha256}]})
        after = IngestionManager._count_ids(store, rel_path, sha256)
        return max(0, before - after)

    @staticmethod
    def _count_ids(store: Any, rel_path: str, sha256: str) -> int:
        """
        Return how many IDs exist for a given (path, sha256) pair.
        """
        # Dense Chroma store
        if hasattr(store, "collection"):
            res = store.collection.get(
                where={"$and": [{"path": rel_path}, {"sha256": sha256}]},
                include=[],
            )
            ids = res.get("ids", []) if res else []
            return len(ids)

        # Local sparse SPLADE store
        meta_store = getattr(store, "_meta_store", None)
        if isinstance(meta_store, dict):
            return sum(
                1
                for meta in meta_store.values()
                if meta.get("path") == rel_path and meta.get("sha256") == sha256
            )

        return 0
```

### ~\ragstream\ingestion\loader.py
```python
"""
DocumentLoader
==============
Responsible for discovering and loading raw files from *data/doc_raw* and its subfolders.
"""

from pathlib import Path
from typing import List, Tuple

class DocumentLoader:
    """Scans the raw-document directory and yields (file_path, file_text) tuples."""

    def __init__(self, root: Path) -> None:
        """
        :param root: Path to the base 'data/doc_raw' folder.
        """
        self.root = root

    def load_documents(self, subfolder: str) -> List[Tuple[str, str]]:
        """
        Load all files from the given subfolder inside data/doc_raw.
        Reads any file extension as plain text.

        :param subfolder: Name of the subfolder (e.g., 'project1').
        :return: List of tuples (absolute_file_path_str, file_text).
        """
        folder_path = self.root / subfolder
        if not folder_path.exists():
            raise FileNotFoundError(f"Input folder does not exist: {folder_path}")

        docs: List[Tuple[str, str]] = []

        for file_path in folder_path.rglob("*"):
            if file_path.is_file():
                try:
                    text = file_path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    # Fallback: try latin-1 to avoid crash on non-UTF8 files
                    text = file_path.read_text(encoding="latin-1")
                docs.append((str(file_path.resolve()), text))

        return docs
```

### ~\ragstream\ingestion\splade_embedder.py
```python
# -*- coding: utf-8 -*-
"""
splade_embedder.py

Purpose:
    SPLADE-side counterpart of embedder.py for RAGstream ingestion.

Role in architecture:
    - Dense side:
        Embedder.embed(texts) -> List[List[float]]
    - Sparse SPLADE side:
        SpladeEmbedder.embed(texts) -> List[Dict[str, float]]

Design goals:
    - Keep the public ingestion-facing API parallel to Embedder:
        embed(texts) -> one sparse representation per text
    - Add query-specific helpers for the later retrieval phase:
        embed_queries(...)
        embed_query(...)
    - Persist nothing here; this module is encoder-only.
"""

from __future__ import annotations

from typing import Dict, List, Sequence

try:
    import torch
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "splade_embedder.py requires PyTorch. Please install torch first."
    ) from exc

try:
    from sentence_transformers import SparseEncoder
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "splade_embedder.py requires sentence-transformers with SparseEncoder support."
    ) from exc


SparseVector = Dict[str, float]


class SpladeEmbedder:
    """
    High-level SPLADE sparse encoder.

    Public API is intentionally parallel to dense Embedder where possible:
        - embed(texts)         : document-side sparse encoding for ingestion
        - embed_queries(texts) : query-side sparse encoding for retrieval
        - embed_query(text)    : single-query convenience wrapper

    Internal sparse representation:
        Dict[str, float]
            key   = vocabulary dimension id as string
            value = SPLADE weight for that active dimension
    """

    def __init__(
        self,
        model: str = "naver/splade-cocondenser-ensembledistil",
        *,
        device: str = "cpu",
        backend: str = "torch",
        batch_size: int = 16,
        max_active_dims: int | None = 256,
        show_progress_bar: bool = False,
    ) -> None:
        """
        Args:
            model:
                SPLADE model name or local path.
            device:
                Usually "cpu" on your laptop for now.
            backend:
                SparseEncoder backend, e.g. "torch", "onnx", "openvino".
            batch_size:
                Default batch size for encoding.
            max_active_dims:
                Optional cap on active dimensions to keep sparse output bounded.
            show_progress_bar:
                Whether Sentence Transformers should show progress bars.
        """
        self.model = model
        self.device = device
        self.backend = backend
        self.batch_size = int(batch_size)
        self.max_active_dims = max_active_dims
        self.show_progress_bar = bool(show_progress_bar)

        self.encoder = SparseEncoder(
            model,
            device=device,
            backend=backend,
            max_active_dims=max_active_dims,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def embed(self, texts: List[str]) -> List[SparseVector]:
        """
        Document-side sparse encoding for ingestion.

        This is the ingestion-parallel counterpart of dense Embedder.embed(...).

        Args:
            texts:
                List of chunk texts.

        Returns:
            List[Dict[str, float]]:
                One sparse representation per input text.
        """
        return self._encode_documents(texts)

    def embed_queries(self, texts: List[str]) -> List[SparseVector]:
        """
        Query-side sparse encoding for retrieval.

        Kept here already so retriever_splade.py can later use the same class.
        """
        if not texts:
            return []

        raw = self.encoder.encode_query(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=self.show_progress_bar,
            convert_to_tensor=False,
            convert_to_sparse_tensor=True,
            save_to_cpu=True,
            max_active_dims=self.max_active_dims,
        )
        return [self._tensor_to_sparse_dict(t) for t in self._ensure_list(raw)]

    def embed_query(self, text: str) -> SparseVector:
        """
        Convenience wrapper for one retrieval query.
        """
        text = (text or "").strip()
        if not text:
            return {}
        return self.embed_queries([text])[0]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _encode_documents(self, texts: Sequence[str]) -> List[SparseVector]:
        if not texts:
            return []

        raw = self.encoder.encode_document(
            list(texts),
            batch_size=self.batch_size,
            show_progress_bar=self.show_progress_bar,
            convert_to_tensor=False,
            convert_to_sparse_tensor=True,
            save_to_cpu=True,
            max_active_dims=self.max_active_dims,
        )
        return [self._tensor_to_sparse_dict(t) for t in self._ensure_list(raw)]

    @staticmethod
    def _ensure_list(raw: object) -> List[torch.Tensor]:
        """
        Sentence Transformers may return a single tensor or a list of tensors,
        depending on input shape and conversion settings.
        """
        if isinstance(raw, list):
            return raw
        if isinstance(raw, torch.Tensor):
            return [raw]
        raise TypeError(f"Unsupported sparse encoder output type: {type(raw)!r}")

    @staticmethod
    def _tensor_to_sparse_dict(tensor: torch.Tensor) -> SparseVector:
        """
        Convert one sparse tensor into Dict[str, float].

        Expected common case:
            sparse COO tensor, shape [vocab_size]

        Fallback:
            dense tensor -> convert non-zero entries only
        """
        if tensor.is_sparse:
            t = tensor.coalesce()
            indices = t.indices()
            values = t.values()

            if indices.numel() == 0:
                return {}

            # 1D sparse vector: indices shape [1, nnz]
            # Defensive fallback: use last row if shape differs.
            if indices.dim() == 2:
                dim_ids = indices[-1].tolist()
            else:
                dim_ids = indices.tolist()

            return {
                str(int(dim_id)): float(value)
                for dim_id, value in zip(dim_ids, values.tolist())
                if float(value) != 0.0
            }

        # Dense fallback
        nonzero = torch.nonzero(tensor, as_tuple=False).flatten().tolist()
        if not nonzero:
            return {}

        return {
            str(int(idx)): float(tensor[idx].item())
            for idx in nonzero
            if float(tensor[idx].item()) != 0.0
        }
```

### ~\ragstream\ingestion\splade_vector_store_base.py
```python
# -*- coding: utf-8 -*-
"""
splade_vector_store_base.py

Shared, production-grade base class for a local SPLADE-backed sparse store.

Purpose:
    Provide the sparse-store analogue of chroma_vector_store_base.py, with the
    same public culture wherever possible:

        add(ids, vectors, metadatas) -> None
        query(vector, k=10, where=None) -> List[str]
        delete_where(where) -> None
        snapshot(timestamp=None) -> Path

Storage model:
    Local filesystem persistence under one project folder.
    The store persists:
        - sparse vectors by id
        - metadatas by id

Why local and simple:
    For your current architecture, SPLADE ingestion is the first step.
    Later retrieval can rescore a bounded set of chunk_ids efficiently from this
    store without requiring a full external search engine.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import os
import pickle
import shutil


SparseVector = Dict[str, float]


class SpladeVectorStoreBase:
    """
    Base implementation of a local persistent sparse store.

    Responsibilities:
      - Own one filesystem-backed sparse index bundle.
      - Provide deterministic add/query/delete/snapshot methods.
      - Offer policy hooks for subclasses, matching the Chroma base style.
    """

    def __init__(self, persist_dir: str, index_name: str) -> None:
        self.persist_path = Path(persist_dir)
        self.persist_path.mkdir(parents=True, exist_ok=True)

        self.index_name = index_name
        self._bundle_path = self.persist_path / f"{self.index_name}.pkl"

        self._index: Dict[str, SparseVector] = {}
        self._meta_store: Dict[str, Dict[str, Any]] = {}

        self._load()

    # ------------------------------------------------------------------
    # Public API (parallel to Chroma base)
    # ------------------------------------------------------------------

    def add(
        self,
        ids: List[str],
        vectors: List[SparseVector],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """
        Upsert sparse vectors and metadatas into the local store.
        """
        if not ids or not vectors:
            return
        if len(ids) != len(vectors):
            raise ValueError("ids and vectors length mismatch")
        if metadatas is not None and len(metadatas) != len(ids):
            raise ValueError("metadatas length must match ids (or be None)")

        ids, vectors, metadatas = self._pre_add(ids, vectors, metadatas)

        metas = metadatas or [{} for _ in ids]

        for chunk_id, vector, meta in zip(ids, vectors, metas):
            self._index[chunk_id] = self._normalize_sparse_vector(vector)
            self._meta_store[chunk_id] = dict(meta)

        self._persist()
        self._post_add(ids, vectors, metadatas)

    def query(
        self,
        vector: SparseVector,
        k: int = 10,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """
        Query the sparse store by sparse-vector dot product.

        Args:
            vector:
                Query sparse vector, same representation as stored doc vectors.
            k:
                Number of top results to return.
            where:
                Optional metadata filter, supporting:
                    - {"path": "...", "sha256": "..."}
                    - {"$and": [ ... ]}
                    - {"$or":  [ ... ]}
        """
        if not isinstance(vector, dict):
            raise ValueError("query vector must be a Dict[str, float]")

        k = max(1, int(k))
        vector, k, where = self._pre_query(vector, k, where)

        scored: List[tuple[str, float]] = []
        for chunk_id, doc_vec in self._index.items():
            meta = self._meta_store.get(chunk_id, {})

            if where and not self._metadata_matches(meta, where):
                continue

            score = self._dot_sparse(vector, doc_vec)
            scored.append((chunk_id, score))

        scored.sort(key=lambda row: (-row[1], row[0]))
        ids = [chunk_id for chunk_id, _score in scored[:k]]
        return self._post_query(ids, {"scored": scored})

    def delete_where(self, where: Dict[str, Any]) -> None:
        """
        Delete records by metadata filter.
        """
        if not where:
            return

        ids_to_delete = [
            chunk_id
            for chunk_id, meta in self._meta_store.items()
            if self._metadata_matches(meta, where)
        ]
        self._delete_ids(ids_to_delete)

    def snapshot(self, timestamp: Optional[str] = None) -> Path:
        """
        Create a filesystem snapshot of the persistent sparse store directory.
        """
        ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
        snapshots_dir = self.persist_path.parent / "snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        dst = snapshots_dir / f"{self.persist_path.name}_{ts}"

        shutil.copytree(self.persist_path, dst, dirs_exist_ok=False)
        return dst

    @property
    def index(self) -> Dict[str, SparseVector]:
        """
        Expose the underlying sparse vector mapping for advanced ops/debugging.
        """
        return self._index

    # ------------------------------------------------------------------
    # Hook methods (parallel to Chroma base)
    # ------------------------------------------------------------------

    def _pre_add(
        self,
        ids: List[str],
        vectors: List[SparseVector],
        metadatas: Optional[List[Dict[str, Any]]],
    ) -> tuple[List[str], List[SparseVector], Optional[List[Dict[str, Any]]]]:
        return ids, vectors, metadatas

    def _post_add(
        self,
        ids: List[str],
        vectors: List[SparseVector],
        metadatas: Optional[List[Dict[str, Any]]],
    ) -> None:
        return None

    def _pre_query(
        self,
        vector: SparseVector,
        k: int,
        where: Optional[Dict[str, Any]],
    ) -> tuple[SparseVector, int, Optional[Dict[str, Any]]]:
        return vector, k, where

    def _post_query(self, ids: List[str], raw_result: Dict[str, Any]) -> List[str]:
        return ids

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self._bundle_path.exists():
            return

        with self._bundle_path.open("rb") as f:
            payload = pickle.load(f)

        self._index = dict(payload.get("index", {}))
        self._meta_store = dict(payload.get("metadatas", {}))

    def _persist(self) -> None:
        payload = {
            "version": "1",
            "index_name": self.index_name,
            "index": self._index,
            "metadatas": self._meta_store,
        }

        tmp_path = self._bundle_path.with_suffix(self._bundle_path.suffix + ".tmp")
        with tmp_path.open("wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)

        os.replace(str(tmp_path), str(self._bundle_path))

    def _delete_ids(self, ids: Iterable[str]) -> None:
        changed = False
        for chunk_id in ids:
            if chunk_id in self._index:
                del self._index[chunk_id]
                changed = True
            if chunk_id in self._meta_store:
                del self._meta_store[chunk_id]
                changed = True

        if changed:
            self._persist()

    @staticmethod
    def _normalize_sparse_vector(vector: SparseVector) -> SparseVector:
        """
        Remove zero entries and normalize key/value types.
        """
        normalized: SparseVector = {}
        for key, value in vector.items():
            fval = float(value)
            if fval != 0.0:
                normalized[str(key)] = fval
        return normalized

    @staticmethod
    def _dot_sparse(left: SparseVector, right: SparseVector) -> float:
        """
        Dot product over sparse dicts.

        Iterate over the smaller dict for efficiency.
        """
        if len(left) > len(right):
            left, right = right, left

        score = 0.0
        for key, value in left.items():
            score += float(value) * float(right.get(key, 0.0))
        return score

    @classmethod
    def _metadata_matches(cls, metadata: Dict[str, Any], where: Dict[str, Any]) -> bool:
        """
        Minimal local filter engine compatible with the current ingestion needs.

        Supported:
            {"path": "..."}
            {"sha256": "..."}
            {"$and": [cond1, cond2, ...]}
            {"$or":  [cond1, cond2, ...]}
        """
        if not where:
            return True

        if "$and" in where:
            conditions = where["$and"]
            if not isinstance(conditions, list):
                raise ValueError("$and value must be a list")
            return all(cls._metadata_matches(metadata, cond) for cond in conditions)

        if "$or" in where:
            conditions = where["$or"]
            if not isinstance(conditions, list):
                raise ValueError("$or value must be a list")
            return any(cls._metadata_matches(metadata, cond) for cond in conditions)

        for key, expected in where.items():
            if key.startswith("$"):
                raise ValueError(f"Unsupported filter operator: {key}")
            if metadata.get(key) != expected:
                return False

        return True
```

### ~\ragstream\ingestion\vector_store_chroma.py
```python
# -*- coding: utf-8 -*-
"""
vector_store_chroma.py

Concrete document vector store for RAGstream, backed by Chroma.
This subclass is intentionally thin: it inherits all core mechanics
(add/query/snapshot/delete_where) from ChromaVectorStoreBase and exposes
a couple of convenience helpers that are useful for the ingestion flow.

Usage:
    store = VectorStoreChroma(persist_dir=PATHS.chroma_db)   # default collection "docs"
    store.add(ids=[...], vectors=[...], metadatas=[...])
    top_ids = store.query(vector=q_emb, k=5)
    snap_dir = store.snapshot()  # filesystem snapshot of the persistent DB

Notes:
- We removed the separate "IVectorStore" interface; this concrete class
  (via its base) is now the canonical storage API for documents.
- History policies (selection-only, capacity, eligibility alignment) belong
  to a separate HistoryStoreChroma subclass and are not implemented here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .chroma_vector_store_base import ChromaVectorStoreBase


class VectorStoreChroma(ChromaVectorStoreBase):
    """
    Chroma-backed vector store for document chunks.

    Responsibilities:
      - Provide a ready-to-use, persistent collection (default: "docs").
      - Reuse base add/query/snapshot/delete_where without policy overrides.
      - Offer tiny utilities for common ingestion tasks (e.g., ID formatting).
    """

    def __init__(
        self,
        persist_dir: str,
        collection_name: str = "docs",
        *,
        anonymized_telemetry: bool = False,
    ) -> None:
        """
        Create (or open) the persistent "docs" collection inside persist_dir.

        Args:
            persist_dir: Directory where Chroma keeps its on-disk files.
            collection_name: Logical collection name (default: "docs").
            anonymized_telemetry: Disable/enable Chroma telemetry (default: False).
        """
        super().__init__(
            persist_dir=persist_dir,
            collection_name=collection_name,
            anonymized_telemetry=anonymized_telemetry,
        )

    # ---------------------------------------------------------------------
    # Convenience helpers (optional; used by ingestion code paths)
    # ---------------------------------------------------------------------

    @staticmethod
    def make_chunk_id(rel_path: str, sha256: str, chunk_idx: int) -> str:
        """
        Deterministic ID format used across RAGstream ingestion.
        Example: "docs/Req.md::a1b2c3...::12"
        """
        return f"{rel_path}::{sha256}::{chunk_idx}"

    def delete_file_version(self, rel_path: str, sha256: str) -> int:
        """
        Remove all chunks belonging to a specific file content version.

        This is typically called when a file changes: we ingest the new sha256,
        then delete the old one to prevent duplicate versions.

        Args:
            rel_path: File path relative to the project doc root.
            sha256: Content hash of the OLD version to remove.

        Returns:
            Number of deleted IDs (best-effort; 0 if nothing matched).
        """
        # Look up matching IDs by metadata, then delete by ID for clarity/audit.
        res = self.collection.get(where={"path": rel_path, "sha256": sha256}, include=[])
        ids = res.get("ids", []) if res else []
        if ids:
            self.collection.delete(ids=ids)
        return len(ids)

    # Introspection utilities (handy for tests/diagnostics)

    @property
    def name(self) -> str:
        """Return the collection name (e.g., 'docs')."""
        return self.collection_name

    @property
    def persist_root(self) -> Path:
        """Return the directory containing the on-disk Chroma database."""
        return self.persist_path

    def count(self) -> int:
        """Return total number of stored vectors (documents/chunks)."""
        try:
            return int(self.collection.count())
        except Exception:
            # Older clients may not implement .count(); fall back to get(ids=None)
            res = self.collection.get()  # may be heavy on very large stores
            return len(res.get("ids", [])) if res else 0
```

### ~\ragstream\ingestion\vector_store_splade.py
```python
# -*- coding: utf-8 -*-
"""
vector_store_splade.py

Concrete sparse document store for RAGstream, backed by SpladeVectorStoreBase.

This is the sparse-side counterpart of vector_store_chroma.py.

Usage:
    store = VectorStoreSplade(persist_dir=".../data/splade_db/project1")
    store.add(ids=[...], vectors=[...], metadatas=[...])
    top_ids = store.query(vector=q_sparse, k=5)
    snap_dir = store.snapshot()
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .splade_vector_store_base import SpladeVectorStoreBase


class VectorStoreSplade(SpladeVectorStoreBase):
    """
    Local persistent sparse store for document chunks.

    Responsibilities:
      - Provide a ready-to-use sparse project store (default: "docs_sparse").
      - Reuse base add/query/snapshot/delete_where without policy overrides.
      - Offer the same tiny convenience helpers as VectorStoreChroma wherever
        possible, so both branches stay structurally parallel.
    """

    def __init__(self, persist_dir: str, index_name: str = "docs_sparse") -> None:
        super().__init__(persist_dir=persist_dir, index_name=index_name)

    @staticmethod
    def make_chunk_id(rel_path: str, sha256: str, chunk_idx: int) -> str:
        """
        Deterministic chunk id format shared with the dense branch.
        Example: "docs/Req.md::a1b2c3...::12"
        """
        return f"{rel_path}::{sha256}::{chunk_idx}"

    def delete_file_version(self, rel_path: str, sha256: str) -> int:
        """
        Remove all chunks belonging to one specific file content version.

        This mirrors VectorStoreChroma.delete_file_version(...).
        """
        ids = [
            chunk_id
            for chunk_id, meta in self._meta_store.items()
            if meta.get("path") == rel_path and meta.get("sha256") == sha256
        ]
        self._delete_ids(ids)
        return len(ids)

    @property
    def name(self) -> str:
        """
        Return the logical sparse index name.
        """
        return self.index_name

    @property
    def persist_root(self) -> Path:
        """
        Return the directory containing the on-disk sparse store.
        """
        return self.persist_path

    def count(self) -> int:
        """
        Return total number of stored sparse vectors.
        """
        return len(self._index)
```


## /home/rusbeh_ab/project/RAGstream/ragstream/orchestration

### ~\ragstream\orchestration\agent_factory.py
```python
# -*- coding: utf-8 -*-
"""
AgentFactory
============

- This is the single place where AgentPrompt objects are created from JSON configs.
- It hides all file-system details (where JSON lives, how paths are built).
- It also caches created agents, so JSON is read only once per (agent_id, version).

Usage model (high level):
- Controller creates ONE AgentFactory instance at startup.
- Each Agent (A2, A3, ...) asks this factory for its AgentPrompt:
    factory.get_agent("a2_promptshaper", "003")
- The returned AgentPrompt is then used to compose/parse LLM calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ragstream.utils.logging import SimpleLogger
from ragstream.orchestration.agent_prompt import AgentPrompt


class AgentFactory:
    """
    Central factory for building and caching AgentPrompt instances.

    Design goals:
    - Neutral: knows nothing about A2/A3/etc. beyond their (agent_id, version).
    - File-based: loads JSON configs from data/agents/<agent_id>/<version>.json.
    - Cached: Agents are constructed once and reused for the lifetime of the factory.
    """

    def __init__(self, agents_root: Optional[Path] = None) -> None:
        if agents_root is None:
            repo_root = Path(__file__).resolve().parents[2]
            agents_root = repo_root / "data" / "agents"

        self.agents_root: Path = agents_root
        self._cache: Dict[Tuple[str, str], AgentPrompt] = {}

        SimpleLogger.info(f"AgentFactory initialized with agents_root={self.agents_root}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_config_path(self, agent_id: str, version: str) -> Path:
        return self.agents_root / agent_id / f"{version}.json"

    def _load_json_file(self, path: Path) -> Dict[str, Any]:
        if not path.is_file():
            msg = f"AgentFactory: JSON file not found at {path}"
            SimpleLogger.error(msg)
            raise FileNotFoundError(msg)

        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            msg = f"AgentFactory: failed to load JSON from {path}: {exc}"
            SimpleLogger.error(msg)
            raise RuntimeError(msg) from exc

        if not isinstance(data, dict):
            msg = f"AgentFactory: top-level JSON in {path} must be an object/dict"
            SimpleLogger.error(msg)
            raise ValueError(msg)

        return data

    def _extract_catalog_block(
        self,
        *,
        catalog: Dict[str, Any],
        target_id: str,
        catalog_path: Path,
    ) -> Dict[str, Any]:
        """
        Extract one decision-target block from an external catalog.

        Supported neutral shapes:

        1) Wrapped-by-target_id
           {
             "system": {
               "options": [...],
               "default": ...
             }
           }

        2) Direct/root block
           {
             "options": [...],
             "default": ...
           }

        3) Single-valid-block fallback
           {
             "<some_other_name>": {
               "options": [...],
               "default": ...
             }
           }

        Shape (3) remains neutral and is accepted only when there is exactly
        one valid block in the catalog, so no agent-specific logic is needed.
        """
        exact_block = catalog.get(target_id)
        if isinstance(exact_block, dict):
            return exact_block

        root_options = catalog.get("options")
        if isinstance(root_options, list):
            return catalog

        valid_blocks: Dict[str, Dict[str, Any]] = {}
        for key, value in catalog.items():
            if isinstance(value, dict) and isinstance(value.get("options"), list):
                valid_blocks[key] = value

        if len(valid_blocks) == 1:
            block_name, block = next(iter(valid_blocks.items()))
            SimpleLogger.info(
                "AgentFactory: catalog fallback accepted single valid block "
                f"'{block_name}' for decision_target id='{target_id}' from {catalog_path}"
            )
            return block

        msg = (
            f"AgentFactory: catalog {catalog_path} does not contain a valid block "
            f"for decision_target id='{target_id}'"
        )
        SimpleLogger.error(msg)
        raise KeyError(msg)

    def _resolve_decision_targets(
        self,
        *,
        config: Dict[str, Any],
        cfg_path: Path,
    ) -> Dict[str, Any]:
        """
        Resolve external catalog references inside decision_targets.

        Neutral convention:
        - main config contains decision_targets
        - each target may point to an external catalog file via:
              "options": "a2_catalogs/003_option_catalogs_system.json"
        - supported external catalog shapes are handled by _extract_catalog_block()

        Result:
        - options path string is replaced by the real inline options list
        - default from the catalog is copied into the decision target
        """
        targets = config.get("decision_targets")
        if not isinstance(targets, list):
            return config

        resolved_targets = []
        base_dir = cfg_path.parent

        for target in targets:
            if not isinstance(target, dict):
                continue

            target_id = target.get("id")
            if not target_id:
                continue

            resolved = dict(target)
            options_ref = resolved.get("options")

            if isinstance(options_ref, str):
                catalog_path = base_dir / options_ref
                catalog = self._load_json_file(catalog_path)
                block = self._extract_catalog_block(
                    catalog=catalog,
                    target_id=str(target_id),
                    catalog_path=catalog_path,
                )

                options_list = block.get("options", [])
                if not isinstance(options_list, list):
                    msg = (
                        f"AgentFactory: catalog block for '{target_id}' in {catalog_path} "
                        f"has invalid 'options' (expected list)"
                    )
                    SimpleLogger.error(msg)
                    raise ValueError(msg)

                resolved["options"] = options_list

                if "default" in block:
                    resolved["default"] = block["default"]

            resolved_targets.append(resolved)

        config["decision_targets"] = resolved_targets
        return config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_config(self, agent_id: str, version: str) -> Dict[str, Any]:
        cfg_path = self._build_config_path(agent_id, version)
        config = self._load_json_file(cfg_path)
        config = self._resolve_decision_targets(config=config, cfg_path=cfg_path)
        return config

    def get_agent(self, agent_id: str, version: str = "001") -> AgentPrompt:
        key = (agent_id, version)
        if key in self._cache:
            return self._cache[key]

        config = self.load_config(agent_id, version)
        agent = AgentPrompt.from_config(config)
        self._cache[key] = agent

        SimpleLogger.info(
            f"AgentFactory: created AgentPrompt for agent_id={agent_id}, version={version}"
        )
        return agent

    def clear_cache(self) -> None:
        self._cache.clear()
        SimpleLogger.info("AgentFactory: cache cleared")
```

### ~\ragstream\orchestration\agent_prompt.py
```python
# ragstream/orchestration/agent_prompt.py
# -*- coding: utf-8 -*-
"""
AgentPrompt
===========
Main neutral prompt engine used by all LLM-using agents.

This file only:
- Defines AgentPrompt (the main class).
- Defines AgentPromptValidationError (small helper exception).
- Delegates JSON parsing, field config extraction, normalization and text
  composition to helper modules in agent_prompt_helpers.

Neutrality rule:
- No agent-specific visible wording is invented here.
- Visible prompt wording must come from JSON or from the agent runtime payload.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ragstream.utils.logging import SimpleLogger
from ragstream.orchestration.agent_prompt_helpers.config_loader import (
    extract_field_config,
)
from ragstream.orchestration.agent_prompt_helpers.schema_map import (
    build_result_key_map,
)
from ragstream.orchestration.agent_prompt_helpers.json_parser import (
    extract_json_object,
)
from ragstream.orchestration.agent_prompt_helpers.field_normalizer import (
    normalize_one,
    normalize_many,
)
from ragstream.orchestration.agent_prompt_helpers.compose_texts import (
    build_system_text,
    build_user_text_for_selector,
    build_user_text_for_classifier,
    build_user_text_for_synthesizer,
)


class AgentPromptValidationError(Exception):
    """Raised when the LLM output cannot be parsed or validated."""


class AgentPrompt:
    """
    Neutral prompt engine.

    Configuration is passed in once (from JSON via AgentFactory) and is read-only.
    No per-call state is stored inside the instance; all inputs for a run are passed
    to compose()/parse() as parameters.
    """

    def __init__(
        self,
        agent_name: str,
        version: str,
        mode: str,
        static_prompt: Dict[str, Any],
        dynamic_bindings: List[Dict[str, Any]],
        decision_targets: List[Dict[str, Any]],
        output_schema: Dict[str, Any],
        enums: Dict[str, List[str]],
        defaults: Dict[str, Any],
        cardinality: Dict[str, str],
        option_descriptions: Dict[str, Dict[str, str]],
        option_labels: Dict[str, Dict[str, str]],
        model_name: str,
        temperature: float,
        max_output_tokens: int,
        elements_order: Optional[List[str]] = None,
    ) -> None:
        self.agent_name: str = agent_name
        self.version: str = version
        self.mode: str = mode  # "selector" | "classifier" | "synthesizer" | "writer" | "extractor" | "scorer"

        self.static_prompt: Dict[str, Any] = static_prompt
        self.dynamic_bindings: List[Dict[str, Any]] = dynamic_bindings
        self.decision_targets: List[Dict[str, Any]] = decision_targets
        self.output_schema: Dict[str, Any] = output_schema
        self.elements_order: List[str] = list(elements_order or [])

        self.enums: Dict[str, List[str]] = enums
        self.defaults: Dict[str, Any] = defaults
        self.cardinality: Dict[str, str] = cardinality
        self.option_descriptions: Dict[str, Dict[str, str]] = option_descriptions
        self.option_labels: Dict[str, Dict[str, str]] = option_labels

        self.model_name: str = model_name
        self.temperature: float = temperature
        self.max_output_tokens: int = max_output_tokens

        self._result_keys: Dict[str, str] = build_result_key_map(output_schema)
        self._top_level_result_keys: Dict[str, str] = self._build_field_map(
            output_schema.get("top_level_fields", []) or output_schema.get("fields", []) or []
        )
        self._item_result_keys: Dict[str, str] = self._build_field_map(
            output_schema.get("item_fields", []) or []
        )

        if self.mode not in ("selector", "classifier", "synthesizer", "writer", "extractor", "scorer"):
            SimpleLogger.error(f"AgentPrompt[{self.agent_name}] unknown mode: {self.mode}")

    @staticmethod
    def _build_field_map(fields_cfg: List[Dict[str, Any]]) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for field in fields_cfg:
            field_id = field.get("field_id")
            if not field_id:
                continue
            result[field_id] = field.get("result_key", field_id)
        return result

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "AgentPrompt":
        agent_meta = config.get("agent_meta", {}) or {}
        llm_cfg = config.get("llm_config", {}) or {}
        output_schema = config.get("output_schema", {}) or {}

        static_prompt = config.get("static_prompt", {}) or {}
        dynamic_bindings = config.get("dynamic_bindings", []) or []
        decision_targets = config.get("decision_targets", []) or []
        elements_order = config.get("elements_order", []) or []

        if not static_prompt:
            prompt_profile = config.get("prompt_profile", {}) or {}
            static_prompt = {
                "system_role": prompt_profile.get("system_role", ""),
                "agent_purpose": prompt_profile.get("agent_purpose", ""),
                "notes": prompt_profile.get("notes", ""),
            }

        if not decision_targets:
            decision_targets = config.get("fields", []) or []

        agent_name = agent_meta.get("agent_id") or agent_meta.get("agent_name") or "unknown_agent"
        version = str(agent_meta.get("version", "000"))

        raw_mode = str(agent_meta.get("agent_type", "selector")).strip().lower()
        mode_aliases = {
            "chooser": "selector",
            "multi-chooser": "classifier",
            "multi_chooser": "classifier",
        }
        mode = mode_aliases.get(raw_mode, raw_mode)

        model_name = llm_cfg.get("model_name", "gpt-4.1-mini")
        temperature = float(llm_cfg.get("temperature", 0.0))
        max_tokens = int(llm_cfg.get("max_tokens", 256))

        enums, defaults, cardinality, opt_desc, opt_labels = extract_field_config(decision_targets)

        return cls(
            agent_name=agent_name,
            version=version,
            mode=mode,
            static_prompt=static_prompt,
            dynamic_bindings=dynamic_bindings,
            decision_targets=decision_targets,
            output_schema=output_schema,
            enums=enums,
            defaults=defaults,
            cardinality=cardinality,
            option_descriptions=opt_desc,
            option_labels=opt_labels,
            model_name=model_name,
            temperature=temperature,
            max_output_tokens=max_tokens,
            elements_order=elements_order,
        )

    @property
    def model(self) -> str:
        return self.model_name

    @property
    def max_tokens(self) -> int:
        return self.max_output_tokens

    def compose(
        self,
        input_payload: Dict[str, Any],
        active_fields: Optional[List[str]] = None,
    ) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
        """
        Build SYSTEM + USER messages and the response_format for the LLM.

        Neutrality rule:
        - SYSTEM text comes from JSON-owned config sections handled by AgentPrompt.
        - USER text comes only from dynamic_bindings + runtime payload.
        """
        for binding in self.dynamic_bindings:
            binding_id = binding.get("id")
            if not binding_id:
                continue
            if binding.get("required", False) and binding_id not in input_payload:
                raise AgentPromptValidationError(
                    f"AgentPrompt[{self.agent_name}] missing required input binding: '{binding_id}'"
                )

        if self.mode == "selector":
            if active_fields is None:
                active_list: List[str] = list(self.enums.keys())
            else:
                active_list = [field_id for field_id in active_fields if field_id in self.enums]
        elif self.mode == "classifier":
            if active_fields is None:
                active_list = list(self.enums.keys())
            else:
                active_list = [field_id for field_id in active_fields if field_id in self.enums]
        else:
            active_list = []

        system_text, system_consumed_binding_ids = build_system_text(
            static_prompt=self.static_prompt,
            agent_name=self.agent_name,
            version=self.version,
            decision_targets=self.decision_targets,
            result_keys=self._result_keys,
            enums=self.enums,
            option_labels=self.option_labels,
            option_descriptions=self.option_descriptions,
            active_fields=active_list,
            input_payload=input_payload,
            dynamic_bindings=self.dynamic_bindings,
            elements_order=self.elements_order,
        )

        if self.mode == "selector":
            user_text = build_user_text_for_selector(
                input_payload=input_payload,
                dynamic_bindings=self.dynamic_bindings,
                consumed_binding_ids=system_consumed_binding_ids,
            )
        elif self.mode == "classifier":
            user_text = build_user_text_for_classifier(
                input_payload=input_payload,
                dynamic_bindings=self.dynamic_bindings,
                consumed_binding_ids=system_consumed_binding_ids,
            )
        elif self.mode == "synthesizer":
            user_text = build_user_text_for_synthesizer(
                input_payload=input_payload,
                dynamic_bindings=self.dynamic_bindings,
                consumed_binding_ids=system_consumed_binding_ids,
            )
        else:
            raise AgentPromptValidationError(
                f"AgentPrompt[{self.agent_name}] compose() currently only supports "
                f"mode='selector', mode='classifier', or mode='synthesizer'"
            )

        messages = [{"role": "system", "content": system_text}]
        if user_text.strip():
            messages.append({"role": "user", "content": user_text})

        response_format = {"type": "json_object"}

        SimpleLogger.info(f"AgentPrompt[{self.agent_name}] SYSTEM prompt:")
        SimpleLogger.info(system_text)
        SimpleLogger.info(f"AgentPrompt[{self.agent_name}] USER prompt:")
        SimpleLogger.info(user_text)

        return messages, response_format

    def parse(
        self,
        raw_output: Any,
        active_fields: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Parse and validate the LLM raw output into a clean Python dict.
        """
        json_obj = extract_json_object(raw_output)

        if self.mode == "selector":
            if active_fields is None:
                active_list: List[str] = list(self.enums.keys())
            else:
                active_list = [field_id for field_id in active_fields if field_id in self.enums]

            active_set = set(active_list)
            result: Dict[str, Any] = {}

            for field_id, allowed in self.enums.items():
                if field_id not in active_set:
                    continue

                result_key = self._result_keys.get(field_id, field_id)
                card = self.cardinality.get(field_id, "one")
                default_value = self.defaults.get(field_id)

                raw_value = json_obj.get(result_key, None)

                if card == "many":
                    normalized = normalize_many(
                        field_id=field_id,
                        raw_value=raw_value,
                        allowed=allowed,
                        default_value=default_value,
                    )
                else:
                    normalized = normalize_one(
                        field_id=field_id,
                        raw_value=raw_value,
                        allowed=allowed,
                        default_value=default_value,
                    )

                result[field_id] = normalized

            return result

        if self.mode == "classifier":
            result: Dict[str, Any] = {}

            for field_id, result_key in self._top_level_result_keys.items():
                raw_value = json_obj.get(result_key, "")
                if isinstance(raw_value, str):
                    result[field_id] = raw_value.strip().lower()
                elif raw_value is None:
                    result[field_id] = ""
                else:
                    result[field_id] = str(raw_value).strip()

            root_key = self.output_schema.get("root_key", "item_decisions")
            item_id_key = self.output_schema.get("item_id_key", "chunk_id")

            raw_items = json_obj.get(root_key, []) or []
            if not isinstance(raw_items, list):
                raw_items = []

            normalized_items: List[Dict[str, Any]] = []

            for raw_item in raw_items:
                if not isinstance(raw_item, dict):
                    continue

                raw_chunk_id = raw_item.get(item_id_key)
                if raw_chunk_id is None:
                    continue

                chunk_id = str(raw_chunk_id).strip()
                if not chunk_id:
                    continue

                item_result: Dict[str, Any] = {item_id_key: chunk_id}

                for field_id, allowed in self.enums.items():
                    result_key = self._item_result_keys.get(field_id, field_id)
                    default_value = self.defaults.get(field_id)
                    raw_value = raw_item.get(result_key, None)

                    normalized = normalize_one(
                        field_id=field_id,
                        raw_value=raw_value,
                        allowed=allowed,
                        default_value=default_value,
                    )
                    item_result[field_id] = normalized

                normalized_items.append(item_result)

            result[root_key] = normalized_items
            return result

        if self.mode == "synthesizer":
            result: Dict[str, Any] = {}

            root_key = self.output_schema.get("root_key", "")
            item_id_key = self.output_schema.get("item_id_key", "")

            if root_key and self._item_result_keys:
                raw_items = json_obj.get(root_key, []) or []
                if not isinstance(raw_items, list):
                    raw_items = []

                normalized_items: List[Dict[str, Any]] = []
                for raw_item in raw_items:
                    if not isinstance(raw_item, dict):
                        continue

                    item_result: Dict[str, Any] = {}
                    if item_id_key:
                        raw_item_id = raw_item.get(item_id_key)
                        if raw_item_id is None:
                            continue
                        item_result[item_id_key] = str(raw_item_id).strip()

                    for field_id, result_key in self._item_result_keys.items():
                        raw_value = raw_item.get(result_key, "")
                        if raw_value is None:
                            item_result[field_id] = ""
                        elif isinstance(raw_value, str):
                            item_result[field_id] = raw_value.strip()
                        else:
                            item_result[field_id] = str(raw_value).strip()

                    normalized_items.append(item_result)

                result[root_key] = normalized_items
                return result

            for field_id, result_key in self._top_level_result_keys.items():
                raw_value = json_obj.get(result_key, "")
                if raw_value is None:
                    result[field_id] = ""
                elif isinstance(raw_value, str):
                    result[field_id] = raw_value.strip()
                else:
                    result[field_id] = str(raw_value).strip()

            return result

        raise AgentPromptValidationError(
            f"AgentPrompt[{self.agent_name}] parse() currently only supports "
            f"mode='selector', mode='classifier', or mode='synthesizer'"
        )
```

### ~\ragstream\orchestration\llm_client.py
```python
# ragstream/orchestration/llm_client.py
# -*- coding: utf-8 -*-
"""
LLMClient — thin wrapper around an LLM provider.

Current implementation:
- Uses OpenAI Python client v1 (OpenAI() + client.chat.completions.create).
- Reads OPENAI_API_KEY from environment (or optional api_key in __init__).
- Keeps backward compatibility for old callers:
    * default return = raw content string
- Supports optional metadata return for cache/token inspection:
    * return_metadata=True -> {"content": "...", "usage": {...}}

Added:
- Responses API path for A4 / reasoning-model calls.
- Metadata extraction for:
    * model name
    * status
    * incomplete reason
    * input tokens
    * cached input tokens
    * output tokens
    * reasoning tokens

CLI logging:
- Always logs model name, total input tokens, cached input tokens, and output tokens
  for both chat() and responses().
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
import os

from ragstream.utils.logging import SimpleLogger

try:
    from openai import OpenAI  # type: ignore[import]
except ImportError:  # pragma: no cover - import guard
    OpenAI = None  # type: ignore[assignment]

JsonDict = Dict[str, Any]


class LLMClient:
    """
    Neutral LLM gateway.

    Default behavior stays backward compatible:
    - chat() returns raw content string

    Optional metadata:
    - chat(..., return_metadata=True)
    - responses(..., return_metadata=True)
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        key = api_key or os.getenv("OPENAI_API_KEY") or ""
        self._client: Optional[OpenAI] = None  # type: ignore[type-arg]

        if OpenAI is None:
            SimpleLogger.info(
                "LLMClient: 'openai' v1 client not installed. Any LLM call will fail until you "
                "install it (e.g. 'pip install openai')."
            )
            return

        if not key:
            SimpleLogger.info(
                "LLMClient: OPENAI_API_KEY not set. Any LLM call will fail until you set it."
            )
            return

        try:
            self._client = OpenAI(api_key=key)
            SimpleLogger.info("LLMClient: OpenAI client initialised (v1 API).")
        except Exception as exc:
            SimpleLogger.error(f"LLMClient: failed to initialise OpenAI client: {exc!r}")
            self._client = None

    def chat(
        self,
        *,
        messages: List[Dict[str, str]],
        model_name: str,
        temperature: float,
        max_output_tokens: int,
        response_format: Dict[str, Any] | None = None,
        return_metadata: bool = False,
        prompt_cache_key: Optional[str] = None,
        prompt_cache_retention: Optional[str] = None,
    ) -> Union[str, JsonDict]:
        """
        Thin wrapper over OpenAI chat.completions.

        Notes:
        - Uses max_completion_tokens (new API) instead of max_tokens.
        - For gpt-5* reasoning models, temperature is omitted.
        - Prompt caching for recent models is automatic on the provider side.
        """
        if self._client is None:
            raise RuntimeError("LLMClient: OpenAI client is not initialised")

        kwargs: Dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "max_completion_tokens": int(max_output_tokens),
        }

        if response_format is not None:
            kwargs["response_format"] = response_format

        if temperature is not None and not str(model_name).startswith("gpt-5"):
            kwargs["temperature"] = float(temperature)

        if prompt_cache_key:
            kwargs["prompt_cache_key"] = prompt_cache_key  # Added: stable cache-routing key per prompt family.

      # if prompt_cache_retention:
           # kwargs["prompt_cache_retention"] = prompt_cache_retention  # Added: explicit retention policy for prompt cache.

        resp = self._client.chat.completions.create(**kwargs)

        content = resp.choices[0].message.content
        content_text = content if isinstance(content, str) else str(content or "")

        usage = self._extract_chat_usage(resp)
        actual_model_name = str(getattr(resp, "model", "") or model_name)
        self._log_chat_usage(actual_model_name, usage)

        if not return_metadata:
            return content_text

        return {
            "content": content_text,
            "usage": usage,
            "model_name": actual_model_name,
            "status": "",
            "incomplete_reason": "",
        }

    def responses(
        self,
        *,
        messages: List[Dict[str, str]],
        model_name: str,
        max_output_tokens: int,
        reasoning_effort: Optional[str] = None,
        return_metadata: bool = False,
        prompt_cache_key: Optional[str] = None,
        prompt_cache_retention: Optional[str] = None,
    ) -> Union[str, JsonDict]:
        """
        Responses API path used for A4 / reasoning-style calls.

        Design:
        - First SYSTEM message becomes `instructions`.
        - Remaining messages are collapsed into one text input string.
        - reasoning_effort is explicitly controlled here.

        Important fix:
        - If the composed prompt has no non-system message, Responses API still
          requires `input`.
        - In that case we move the instructions text into `input` and clear
          `instructions`.
        """
        if self._client is None:
            raise RuntimeError("LLMClient: OpenAI client is not initialised")

        instructions = ""
        input_parts: List[str] = []

        for message in messages:
            role = str(message.get("role", "") or "").strip().lower()
            content = str(message.get("content", "") or "")

            if role == "system" and not instructions:
                instructions = content
            else:
                if content:
                    input_parts.append(content)

        input_text = "\n\n".join(part for part in input_parts if part).strip()

        # Fix for "missing_required_parameter":
        # if everything is inside the system message, move it into input.
        if not input_text and instructions:
            input_text = instructions
            instructions = ""

        kwargs: Dict[str, Any] = {
            "model": model_name,
            "input": input_text,
            "max_output_tokens": int(max_output_tokens),
        }

        if reasoning_effort is not None:
            kwargs["reasoning"] = {"effort": reasoning_effort}

        if instructions:
            kwargs["instructions"] = instructions

        if prompt_cache_key:
            kwargs["prompt_cache_key"] = prompt_cache_key  # Added: stable cache-routing key per prompt family.

       # if prompt_cache_retention:
         #   kwargs["prompt_cache_retention"] = prompt_cache_retention  # Added: explicit retention policy for prompt cache.

        resp = self._client.responses.create(**kwargs)

        content_text = self._extract_response_text(resp)
        usage = self._extract_response_usage(resp)
        status = self._extract_response_status(resp)
        incomplete_reason = self._extract_response_incomplete_reason(resp)
        actual_model_name = str(getattr(resp, "model", "") or model_name)

        self._log_response_usage(
            actual_model_name=actual_model_name,
            usage=usage,
            status=status,
            incomplete_reason=incomplete_reason,
        )

        if not return_metadata:
            return content_text

        return {
            "content": content_text,
            "usage": usage,
            "model_name": actual_model_name,
            "status": status,
            "incomplete_reason": incomplete_reason,
        }

    @staticmethod
    def _extract_chat_usage(resp: Any) -> JsonDict:
        """
        Extract token usage including cached tokens when the provider returns it.
        """
        usage_obj = getattr(resp, "usage", None)
        if usage_obj is None:
            return {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cached_tokens": 0,
            }

        prompt_tokens = int(getattr(usage_obj, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage_obj, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage_obj, "total_tokens", 0) or 0)

        prompt_tokens_details = getattr(usage_obj, "prompt_tokens_details", None)
        cached_tokens = 0
        if prompt_tokens_details is not None:
            cached_tokens = int(getattr(prompt_tokens_details, "cached_tokens", 0) or 0)

        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cached_tokens": cached_tokens,
        }

    @staticmethod
    def _extract_response_text(resp: Any) -> str:
        """
        Extract visible text from a Responses API object.
        """
        output_text = getattr(resp, "output_text", None)
        if isinstance(output_text, str) and output_text:
            return output_text

        output = getattr(resp, "output", None)
        if not isinstance(output, list):
            return ""

        parts: List[str] = []

        for item in output:
            item_type = str(getattr(item, "type", "") or "")
            if item_type != "message":
                continue

            content_list = getattr(item, "content", None)
            if not isinstance(content_list, list):
                continue

            for content_item in content_list:
                content_type = str(getattr(content_item, "type", "") or "")
                if content_type in ("output_text", "text"):
                    text = getattr(content_item, "text", None)
                    if isinstance(text, str) and text:
                        parts.append(text)

        return "\n".join(parts).strip()

    @staticmethod
    def _extract_response_usage(resp: Any) -> JsonDict:
        """
        Extract token usage from a Responses API object.
        """
        usage_obj = getattr(resp, "usage", None)
        if usage_obj is None:
            return {
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "total_tokens": 0,
            }

        input_tokens = int(getattr(usage_obj, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage_obj, "output_tokens", 0) or 0)
        total_tokens = int(getattr(usage_obj, "total_tokens", 0) or 0)

        input_tokens_details = getattr(usage_obj, "input_tokens_details", None)
        cached_input_tokens = 0
        if input_tokens_details is not None:
            cached_input_tokens = int(getattr(input_tokens_details, "cached_tokens", 0) or 0)

        output_tokens_details = getattr(usage_obj, "output_tokens_details", None)
        reasoning_tokens = 0
        if output_tokens_details is not None:
            reasoning_tokens = int(getattr(output_tokens_details, "reasoning_tokens", 0) or 0)

        return {
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "output_tokens": output_tokens,
            "reasoning_tokens": reasoning_tokens,
            "total_tokens": total_tokens,
        }

    @staticmethod
    def _extract_response_status(resp: Any) -> str:
        return str(getattr(resp, "status", "") or "")

    @staticmethod
    def _extract_response_incomplete_reason(resp: Any) -> str:
        incomplete_details = getattr(resp, "incomplete_details", None)
        if incomplete_details is None:
            return ""
        return str(getattr(incomplete_details, "reason", "") or "")

    @staticmethod
    def _log_chat_usage(actual_model_name: str, usage: JsonDict) -> None:
        prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        cached_tokens = int(usage.get("cached_tokens", 0) or 0)
        completion_tokens = int(usage.get("completion_tokens", 0) or 0)

        SimpleLogger.info(
            f"LLMClient.chat | model={actual_model_name} | "
            f"input={prompt_tokens} | cached_input={cached_tokens} | output={completion_tokens}"
        )

    @staticmethod
    def _log_response_usage(
        *,
        actual_model_name: str,
        usage: JsonDict,
        status: str,
        incomplete_reason: str,
    ) -> None:
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        cached_input_tokens = int(usage.get("cached_input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)

        SimpleLogger.info(
            f"LLMClient.responses | model={actual_model_name} | "
            f"input={input_tokens} | cached_input={cached_input_tokens} | output={output_tokens}"
        )

        if status:
            SimpleLogger.info(f"LLMClient.responses | status={status}")

        if incomplete_reason:
            SimpleLogger.warning(f"LLMClient.responses | incomplete_reason={incomplete_reason}")
```

### ~\ragstream\orchestration\prompt_builder.py
```python
"""
PromptBuilder
=============
Composes the Super-Prompt with fixed authority order:
[Hard Rules] → [Project Memory] → [❖ FILES] → [S_ctx] → [Task/Mode]
(RECENT HISTORY may be shown for continuity; non-authoritative.)
"""
from typing import List, Optional, Dict

class PromptBuilder:
    def build(self, question: str, files_block: Optional[str], s_ctx: List[str], shape: Optional[Dict] = None) -> str:
        return "PROMPT"
```

### ~\ragstream\orchestration\super_prompt.py
```python
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
```

### ~\ragstream\orchestration\superprompt_projector.py
```python
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

        lines.append("")
        lines.append("## Configuration")
        lines.extend(config_lines)

        return "\n".join(lines).strip()

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
```

### ~\ragstream\orchestration\agent_prompt_helpers\compose_texts.py
```python
# ragstream/orchestration/agent_prompt_helpers/compose_texts.py
# -*- coding: utf-8 -*-
"""
compose_texts
=============

Neutral text render helpers for AgentPrompt.

Rule:
- No agent-specific visible wording is invented here.
- Visible prompt wording must come from JSON or from agent-prepared runtime text.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set, Tuple


def _stringify_for_prompt(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False, indent=2)
        except Exception:
            return str(value)

    return str(value)


def _build_decision_targets_system_text(
    decision_targets: List[Dict[str, Any]],
    result_keys: Dict[str, str],
    enums: Dict[str, List[str]],
    option_labels: Dict[str, Dict[str, str]],
    option_descriptions: Dict[str, Dict[str, str]],
    active_fields: Optional[List[str]] = None,
) -> str:
    lines: List[str] = []

    if active_fields is None:
        active_set = None
    else:
        active_set = set(active_fields)

    for target in decision_targets or []:
        field_id = target.get("id")
        if not field_id:
            continue
        if active_set is not None and field_id not in active_set:
            continue

        label = target.get("label", field_id)
        result_key = result_keys.get(field_id, field_id)

        min_selected = int(target.get("min_selected", 1))
        max_selected = int(target.get("max_selected", 1))

        lines.append(f"Field '{label}' (JSON key: '{result_key}')")

        if max_selected > 1:
            lines.append(f"- Select between {min_selected} and {max_selected} option ids.")
        else:
            lines.append("- Select exactly one option id.")

        for opt_id in enums.get(field_id, []):
            opt_label = (option_labels.get(field_id, {}).get(opt_id) or "").strip()
            opt_desc = (option_descriptions.get(field_id, {}).get(opt_id) or "").strip()

            if opt_label and opt_desc:
                lines.append(f"  * {opt_id}: {opt_label} — {opt_desc}")
            elif opt_label:
                lines.append(f"  * {opt_id}: {opt_label}")
            elif opt_desc:
                lines.append(f"  * {opt_id}: {opt_desc}")
            else:
                lines.append(f"  * {opt_id}")

        lines.append("")

    return "\n".join(lines).strip()


def build_system_text(
    static_prompt: Dict[str, Any],
    agent_name: str,
    version: str,
    decision_targets: Optional[List[Dict[str, Any]]] = None,
    result_keys: Optional[Dict[str, str]] = None,
    enums: Optional[Dict[str, List[str]]] = None,
    option_labels: Optional[Dict[str, Dict[str, str]]] = None,
    option_descriptions: Optional[Dict[str, Dict[str, str]]] = None,
    active_fields: Optional[List[str]] = None,
    input_payload: Optional[Dict[str, Any]] = None,
    dynamic_bindings: Optional[List[Dict[str, Any]]] = None,
    elements_order: Optional[List[str]] = None,
) -> Tuple[str, Set[str]]:
    """
    Build the SYSTEM message content for the LLM.

    Important A4-compatible rule:
    - preamble is always first if present,
    - elements_order may then inject selected dynamic bindings directly into SYSTEM,
    - any dynamic binding moved into SYSTEM is removed from USER,
    - old behavior remains when elements_order is absent.
    """
    input_payload = input_payload or {}
    dynamic_bindings = dynamic_bindings or []
    elements_order = elements_order or []

    lines: List[str] = []
    consumed_binding_ids: Set[str] = set()

    preamble_text = _stringify_for_prompt(static_prompt.get("preamble", ""))
    if preamble_text:
        lines.append(preamble_text)
        lines.append("")

    remaining_static_keys = [key for key in static_prompt.keys() if str(key).strip().lower() != "preamble"]
    binding_by_id: Dict[str, Dict[str, Any]] = {
        str(binding.get("id", "")).strip(): binding
        for binding in dynamic_bindings
        if str(binding.get("id", "")).strip()
    }

    decision_targets_text = _build_decision_targets_system_text(
        decision_targets=decision_targets or [],
        result_keys=result_keys or {},
        enums=enums or {},
        option_labels=option_labels or {},
        option_descriptions=option_descriptions or {},
        active_fields=active_fields,
    )

    rendered_static_keys: Set[str] = set()
    rendered_config_decision_targets = False

    # New optional ordered render path.
    for raw_item in elements_order:
        item = str(raw_item or "").strip()
        if not item:
            continue

        normalized_item = item[3:] if item.lower().startswith("id:") else item

        if normalized_item in binding_by_id:
            binding = binding_by_id[normalized_item]
            if binding.get("visible_in_prompt", True):
                prompt_text = (binding.get("prompt_text") or "").strip()
                if prompt_text:
                    lines.append(prompt_text)

                rendered = _stringify_for_prompt(input_payload.get(normalized_item, ""))
                if rendered:
                    lines.append(rendered)

                lines.append("")
            consumed_binding_ids.add(normalized_item)
            continue

        if normalized_item == "decision_targets":
            runtime_rendered = _stringify_for_prompt(input_payload.get("decision_targets", ""))
            if runtime_rendered:
                lines.append("## Decision Targets")
                lines.append(runtime_rendered)
                lines.append("")
                consumed_binding_ids.add("decision_targets")
            elif decision_targets_text and not rendered_config_decision_targets:
                lines.append("## Decision Targets")
                lines.append(decision_targets_text)
                lines.append("")
                rendered_config_decision_targets = True
            continue

        for static_key in remaining_static_keys:
            if static_key == normalized_item and static_key not in rendered_static_keys:
                text = _stringify_for_prompt(static_prompt.get(static_key, ""))
                if text:
                    lines.append(f"## {static_key}")
                    lines.append(text)
                    lines.append("")
                rendered_static_keys.add(static_key)
                break

    # Backward-compatible default remainder for static prompt keys.
    for static_key in remaining_static_keys:
        if static_key in rendered_static_keys:
            continue
        text = _stringify_for_prompt(static_prompt.get(static_key, ""))
        if not text:
            continue
        lines.append(f"## {static_key}")
        lines.append(text)
        lines.append("")

    # Backward-compatible default remainder for config-owned decision targets.
    if decision_targets_text and not rendered_config_decision_targets:
        lines.append("## Decision Targets")
        lines.append(decision_targets_text)
        lines.append("")

    return "\n".join(lines).strip(), consumed_binding_ids


def _build_user_text_from_dynamic_bindings(
    input_payload: Dict[str, Any],
    dynamic_bindings: List[Dict[str, Any]],
    consumed_binding_ids: Optional[Set[str]] = None,
) -> str:
    lines: List[str] = []
    consumed_binding_ids = consumed_binding_ids or set()

    for binding in dynamic_bindings:
        if not binding.get("visible_in_prompt", True):
            continue

        binding_id = str(binding.get("id", "") or "").strip()
        if not binding_id:
            continue
        if binding_id in consumed_binding_ids:
            continue

        prompt_text = (binding.get("prompt_text") or "").strip()
        value = input_payload.get(binding_id, "")

        if prompt_text:
            lines.append(prompt_text)

        rendered = _stringify_for_prompt(value)
        if rendered:
            lines.append(rendered)

        lines.append("")

    return "\n".join(lines).strip()


def build_user_text_for_selector(
    input_payload: Dict[str, Any],
    dynamic_bindings: List[Dict[str, Any]],
    consumed_binding_ids: Optional[Set[str]] = None,
) -> str:
    return _build_user_text_from_dynamic_bindings(
        input_payload=input_payload,
        dynamic_bindings=dynamic_bindings,
        consumed_binding_ids=consumed_binding_ids,
    )


def build_user_text_for_classifier(
    input_payload: Dict[str, Any],
    dynamic_bindings: List[Dict[str, Any]],
    consumed_binding_ids: Optional[Set[str]] = None,
) -> str:
    return _build_user_text_from_dynamic_bindings(
        input_payload=input_payload,
        dynamic_bindings=dynamic_bindings,
        consumed_binding_ids=consumed_binding_ids,
    )


def build_user_text_for_synthesizer(
    input_payload: Dict[str, Any],
    dynamic_bindings: List[Dict[str, Any]],
    consumed_binding_ids: Optional[Set[str]] = None,
) -> str:
    return _build_user_text_from_dynamic_bindings(
        input_payload=input_payload,
        dynamic_bindings=dynamic_bindings,
        consumed_binding_ids=consumed_binding_ids,
    )
```

### ~\ragstream\orchestration\agent_prompt_helpers\config_loader.py
```python
# -*- coding: utf-8 -*-
"""
config_loader
=============

Why this helper exists:
- Agent JSON configs define decision targets with enums, defaults and selection counts.
- Converting these targets into clean Python dictionaries is generic logic and should
  not clutter AgentPrompt.

What it does:
- Provides a single function `extract_field_config(fields_cfg)` that returns:
  - enums[field_id] = list of allowed option ids
  - defaults[field_id] = default value from config (may be str or list)
  - cardinality[field_id] = "one" or "many"
  - option_labels[field_id][opt_id] = human-readable label (optional)
  - option_descriptions[field_id][opt_id] = human-readable description (optional)

Compatibility:
- Works with the new `decision_targets` structure.
- Also tolerates older inline `fields` configs, as long as they use the same
  basic keys (`id`, `type`, `options`, `default`, `cardinality`).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def extract_field_config(
    fields_cfg: List[Dict[str, Any]]
) -> Tuple[
    Dict[str, List[str]],
    Dict[str, Any],
    Dict[str, str],
    Dict[str, Dict[str, str]],
    Dict[str, Dict[str, str]],
]:
    """
    Convert decision targets / fields into:
    - enums[field_id] = ["opt1", "opt2", ...]
    - defaults[field_id] = default value from config (may be str or list)
    - cardinality[field_id] = "one" | "many"
    - option_descriptions[field_id][opt_id] = description (if present)
    - option_labels[field_id][opt_id] = label (if present)
    """
    enums: Dict[str, List[str]] = {}
    defaults: Dict[str, Any] = {}
    cardinality: Dict[str, str] = {}
    option_descriptions: Dict[str, Dict[str, str]] = {}
    option_labels: Dict[str, Dict[str, str]] = {}

    for field in fields_cfg:
        field_id = field.get("id")
        if not field_id:
            continue

        field_type = field.get("type", "enum")
        if field_type != "enum":
            # For v1 implementation, AgentPrompt only supports enum-based Selector behaviour.
            continue

        options = field.get("options", []) or []
        if not isinstance(options, list):
            options = []

        allowed_ids: List[str] = []
        descs: Dict[str, str] = {}
        labels: Dict[str, str] = {}

        for opt in options:
            if not isinstance(opt, dict):
                continue

            opt_id = opt.get("id")
            if not opt_id:
                continue

            allowed_ids.append(opt_id)

            if "label" in opt:
                labels[opt_id] = opt["label"]
            if "description" in opt:
                descs[opt_id] = opt["description"]

        if allowed_ids:
            enums[field_id] = allowed_ids
            if labels:
                option_labels[field_id] = labels
            if descs:
                option_descriptions[field_id] = descs

        defaults[field_id] = field.get("default")

        if "cardinality" in field:
            cardinality[field_id] = field.get("cardinality", "one")
        else:
            try:
                max_selected = int(field.get("max_selected", 1))
            except Exception:
                max_selected = 1
            cardinality[field_id] = "many" if max_selected > 1 else "one"

    return enums, defaults, cardinality, option_descriptions, option_labels
```

### ~\ragstream\orchestration\agent_prompt_helpers\field_normalizer.py
```python
# -*- coding: utf-8 -*-
"""
field_normalizer
================

Why this helper exists:
- Every Chooser agent must clean and validate what the LLM returns.
- This logic (enforcing enums, cardinality and defaults) is generic and should
  not sit inside the main AgentPrompt file.

What it does:
- Provides `normalize_one()` for single-choice enum fields.
- Provides `normalize_many()` for multi-choice enum fields.
- Both functions take the allowed options and default value and always return
  a safe, normalized result.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ragstream.utils.logging import SimpleLogger


def normalize_one(
    field_id: str,
    raw_value: Any,
    allowed: List[str],
    default_value: Any,
) -> Optional[str]:
    """
    Normalize a single-choice enum field to one allowed id.

    Rules:
    - If raw_value is a string in allowed → use it.
    - If raw_value is a list → pick the first element that is in allowed.
    - Else → fall back to default_value if valid; otherwise first allowed or None.
    """
    chosen: Optional[str] = None

    if isinstance(raw_value, str) and raw_value in allowed:
        chosen = raw_value
    elif isinstance(raw_value, list):
        for item in raw_value:
            if isinstance(item, str) and item in allowed:
                chosen = item
                break

    if chosen is None:
        if isinstance(default_value, str) and default_value in allowed:
            chosen = default_value
        elif allowed:
            chosen = allowed[0]

    if chosen is None:
        SimpleLogger.error(f"field_normalizer.normalize_one: no valid value for field '{field_id}'")

    return chosen


def normalize_many(
    field_id: str,
    raw_value: Any,
    allowed: List[str],
    default_value: Any,
) -> List[str]:
    """
    Normalize a multi-choice enum field to a list of allowed ids.

    Rules:
    - If raw_value is a list → keep only items that are allowed and strings.
    - If raw_value is a single string → convert to [value] if allowed.
    - If after filtering we have nothing → use default_value if list/str and valid.
    - If still nothing and allowed is non-empty → use [allowed[0]] as last resort.
    """
    selected: List[str] = []

    if isinstance(raw_value, list):
        for item in raw_value:
            if isinstance(item, str) and item in allowed and item not in selected:
                selected.append(item)
    elif isinstance(raw_value, str) and raw_value in allowed:
        selected.append(raw_value)

    if not selected:
        if isinstance(default_value, list):
            for item in default_value:
                if isinstance(item, str) and item in allowed and item not in selected:
                    selected.append(item)
        elif isinstance(default_value, str) and default_value in allowed:
            selected.append(default_value)

    if not selected and allowed:
        selected.append(allowed[0])

    if not selected:
        SimpleLogger.error(
            f"field_normalizer.normalize_many: no valid values for field '{field_id}'"
        )

    return selected
```

### ~\ragstream\orchestration\agent_prompt_helpers\json_parser.py
```python
# -*- coding: utf-8 -*-
"""
json_parser
===========

Why this helper exists:
- LLMs often return messy strings: JSON plus explanations or extra text.
- AgentPrompt should not be cluttered with low-level parsing details.

What it does:
- Provides a single function `extract_json_object(raw_output)` that tries
  to extract and load a JSON object.
- On failure it returns {} instead of raising, so caller can fall back to defaults.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from ragstream.utils.logging import SimpleLogger


def extract_json_object(raw_output: Any) -> Dict[str, Any]:
    """
    Best-effort extraction of a JSON object from the raw LLM output.

    Strategy:
    - If already a dict: return as-is.
    - If a string: try json.loads directly.
    - If that fails: try to locate the first '{' and last '}' and parse that slice.
    - On failure: return {} (caller will fall back to defaults).
    """
    if isinstance(raw_output, dict):
        return raw_output

    if not isinstance(raw_output, str):
        SimpleLogger.error("json_parser.extract_json_object: raw_output is neither dict nor str")
        return {}

    text = raw_output.strip()

    # First attempt: direct JSON
    try:
        return json.loads(text)
    except Exception:
        pass

    # Second attempt: find JSON substring
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            SimpleLogger.error(
                "json_parser.extract_json_object: failed to parse JSON substring; returning {}"
            )

    return {}
```

### ~\ragstream\orchestration\agent_prompt_helpers\schema_map.py
```python
# -*- coding: utf-8 -*-
"""
schema_map
==========

Why this helper exists:
- The agent JSON has an 'output_schema' which maps internal field ids
  to JSON keys used in the LLM response.
- Building this field_id → result_key mapping is a small, generic task.

What it does:
- Provides `build_result_key_map(output_schema)` which returns:
    result_keys[field_id] = result_key
"""

from __future__ import annotations

from typing import Any, Dict


def build_result_key_map(output_schema: Dict[str, Any]) -> Dict[str, str]:
    """
    Build field_id -> result_key map from the 'output_schema' section
    of the JSON config.
    """
    result: Dict[str, str] = {}
    fields = output_schema.get("fields", []) or []
    for field in fields:
        field_id = field.get("field_id")
        if not field_id:
            continue
        result_key = field.get("result_key", field_id)
        result[field_id] = result_key
    return result
```


## /home/rusbeh_ab/project/RAGstream/ragstream/retrieval

### ~\ragstream\retrieval\attention.py
```python
"""
AttentionWeights (legacy)
=========================
Kept for compatibility; not central in current eligibility model.
"""
from typing import Dict

class AttentionWeights:
    def weight(self, scores: Dict[str, float]) -> Dict[str, float]:
        return scores
```

### ~\ragstream\retrieval\chunk.py
```python
# -*- coding: utf-8 -*-
"""
Chunk — minimal data record for retrieved context pieces (no helpers).
Place at: ragstream/retrieval/types.py
"""

from __future__ import annotations
from typing import Any, Dict, Tuple

class Chunk:
    __slots__ = (
        "id",       # str: stable identifier (e.g., vector-store id) used by views/selection_ids
        "source",   # str: provenance (file path or URI) to locate the original text
        "snippet",  # str: the actual text excerpt of this chunk
        "span",     # (int, int): start/end character (or line) offsets within the source
        "meta",     # dict: extra metadata (e.g., sha256, mtime, file_type, chunk_index)
    )

    def __init__(
        self,
        *,
        id: str,
        source: str,
        snippet: str,
        span: Tuple[int, int],
        meta: Dict[str, Any] | None = None,
    ) -> None:
        self.id = id
        self.source = source
        self.snippet = snippet
        self.span = span
        self.meta = {} if meta is None else meta
```

### ~\ragstream\retrieval\doc_score.py
```python
# -*- coding: utf-8 -*-
"""
DocScore
========
Pure data container for retrieval results.

Structure mandated by UML (Retriever ..> DocScore) and requirements:
- `id`:   document/chunk identifier (string)
- `score`: cosine similarity score (float, higher is better)
"""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class DocScore:
    id: str
    score: float
```

### ~\ragstream\retrieval\reranker.py
```python
# -*- coding: utf-8 -*-
"""
reranker.py

Purpose:
    Deterministic ReRanker stage for RAGstream.

Scope of this file:
    - Read the Retrieval candidates already stored in the current SuperPrompt.
    - Build reranking query pieces from TASK / PURPOSE / CONTEXT.
    - Clean chunk text dynamically before ColBERT scoring.
    - Score each Retrieval candidate with ColBERT over the split query pieces.
    - Fuse Retrieval ranking and ColBERT ranking with deterministic weighted RRF.
    - Write the ReRanker stage result back into the same SuperPrompt.

Non-goals:
    - No Chroma query here.
    - No raw-file hydration here.
    - No A3 filtering here.
    - No GUI rendering here.
    - No final prompt composition here.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from pylate import models, rank

from ragstream.ingestion.chunker import Chunker
from ragstream.orchestration.super_prompt import A3ChunkStatus, SuperPrompt
from ragstream.orchestration.superprompt_projector import SuperPromptProjector
from ragstream.retrieval.chunk import Chunk
from ragstream.retrieval.rrf_merger import rrf_merge
from ragstream.retrieval.smart_query_splitter import split_query_into_pieces


# ---------------------------------------------------------------------
# Shared row contract
# ---------------------------------------------------------------------

RankedRow = Tuple[str, float, Dict[str, Any]]

# ---------------------------------------------------------------------
# Module-level reranker defaults
# ---------------------------------------------------------------------

# Agreed current reranker model direction.
DEFAULT_RERANK_MODEL = "lightonai/GTE-ModernColBERT-v1"

# Conceptual cap from the current requirement set for how many Retrieval
# candidates should be passed into ReRanker.
DEFAULT_RERANK_TOP_K = 50

# Agreed current runtime direction: CPU-only deterministic stage.
DEFAULT_DEVICE = "cpu"

# Keep query splitting aligned with Retrieval.
DEFAULT_QUERY_CHUNK_SIZE = 1200
DEFAULT_QUERY_OVERLAP = 120

# Equal-weight fusion between Retrieval and ColBERT.
DEFAULT_RETRIEVAL_WEIGHT = 0.75
DEFAULT_COLBERT_WEIGHT = 0.25


class Reranker:
    """
    Deterministic ReRanker stage for document chunks.

    Design:
    - Keep this class stateless with respect to pipeline history.
      The evolving pipeline state lives in SuperPrompt.
    - This class only reads the current SuperPrompt, computes reranking,
      and writes the reranked result back into the same SuperPrompt.
    - The controller decides when to call this class.
    """

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_RERANK_MODEL,
        top_k: int = DEFAULT_RERANK_TOP_K,
        device: str = DEFAULT_DEVICE,
    ) -> None:
        """
        Initialize ReRanker with the agreed ColBERT model.

        Args:
            model_name:
                Hugging Face / PyLate-compatible model id for the reranker.
            top_k:
                Maximum number of Retrieval candidates to rerank.
            device:
                Runtime device. Current agreed direction is CPU.
                Kept as part of the stable ReRanker interface.
        """
        self._model_name = model_name
        self._top_k = int(top_k) if int(top_k) > 0 else DEFAULT_RERANK_TOP_K
        self._device = device
        self._chunker = Chunker()
        self._colbert_model = models.ColBERT(model_name_or_path=self._model_name)

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def run(
        self,
        sp: SuperPrompt,
        *,
        use_reranking_colbert: bool = True,
    ) -> SuperPrompt:
        """
        Execute the ReRanker stage and update the same SuperPrompt in place.

        Inputs:
            sp:
                The current evolving SuperPrompt, typically after Retrieval.
            use_reranking_colbert:
                If False, bypass real ColBERT scoring and copy the Retrieval
                order directly into the reranked stage.

        Returns:
            The same SuperPrompt instance, mutated in place.

        Effects on SuperPrompt:
            - Writes the reranked stage snapshot into sp.views_by_stage["reranked"]
            - Writes reranked chunk IDs into sp.final_selection_ids
            - Appends "reranked" to sp.history_of_stages
            - Sets sp.stage = "reranked"
        """
        if not use_reranking_colbert:
            reranked_view, reranked_ids = self._build_passthrough_from_retrieval(sp)
            sp.views_by_stage["reranked"] = reranked_view
            sp.final_selection_ids = reranked_ids
            sp.stage = "reranked"
            sp.history_of_stages.append("reranked")
            return sp

        query_pieces, retrieval_rows, chunk_lookup = self._prepare_inputs(sp)
        colbert_rows = self._score_with_colbert(query_pieces, retrieval_rows, chunk_lookup)
        fused_rows = self._fuse_with_retrieval(retrieval_rows, colbert_rows, chunk_lookup)
        fused_rows = self._project_fused_metadata_to_reranker_contract(fused_rows)
        self._write_scores_back_to_chunks(fused_rows, chunk_lookup)
        reranked_view, reranked_ids = self._build_reranked_view(fused_rows)

        sp.views_by_stage["reranked"] = reranked_view
        sp.final_selection_ids = reranked_ids
        sp.stage = "reranked"
        sp.history_of_stages.append("reranked")

        return sp

    # -----------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------

    def _build_passthrough_from_retrieval(
        self,
        sp: SuperPrompt,
    ) -> tuple[List[tuple[str, float, A3ChunkStatus]], List[str]]:
        """
        Bypass real ColBERT and copy the Retrieval order directly into the
        reranked stage so downstream A3 can run unchanged.
        """
        if sp is None:
            raise ValueError("Reranker.run: 'sp' must not be None")

        retrieval_rows = sp.views_by_stage.get("retrieval")
        if not retrieval_rows:
            raise ValueError(
                "Reranker.run: Retrieval candidates are missing. "
                "Please run Retrieval before ReRanker."
            )

        if not sp.base_context_chunks:
            raise ValueError(
                "Reranker.run: base_context_chunks is empty. "
                "Please run Retrieval before ReRanker."
            )

        candidate_rows = list(retrieval_rows)[: self._top_k]
        chunk_lookup = {chunk_obj.id: chunk_obj for chunk_obj in sp.base_context_chunks}

        reranked_view: List[tuple[str, float, A3ChunkStatus]] = []
        reranked_ids: List[str] = []

        for position, (chunk_id, retrieval_score, _status) in enumerate(candidate_rows, start=1):
            chunk_id_str = str(chunk_id)
            score = float(retrieval_score)

            reranked_view.append((chunk_id_str, score, A3ChunkStatus.SELECTED))
            reranked_ids.append(chunk_id_str)

            chunk_obj = chunk_lookup.get(chunk_id_str)
            if chunk_obj is None:
                continue

            merged_meta = dict(chunk_obj.meta or {})
            base_retrieval_rrf = float(merged_meta.get("rrf_score", score))

            merged_meta["retrieval_rrf_score"] = float(
                merged_meta.get("retrieval_rrf_score", base_retrieval_rrf)
            )
            merged_meta["retrieval_score"] = score
            merged_meta["colbert_score"] = score
            merged_meta["retrieval_rank"] = int(position)
            merged_meta["colbert_rank"] = int(position)
            merged_meta["rerank_rrf_score"] = score

            chunk_obj.meta = merged_meta

        return reranked_view, reranked_ids

    def _prepare_inputs(
        self,
        sp: SuperPrompt,
    ) -> tuple[List[str], List[tuple[str, float, A3ChunkStatus]], Dict[str, Chunk]]:
        """
        Prepare the reranking job from the current SuperPrompt.

        Responsibilities grouped here on purpose:
        - validate stage and Retrieval availability,
        - build reranking query pieces from TASK / PURPOSE / CONTEXT,
        - trim Retrieval rows to the active rerank cap,
        - build chunk_id -> Chunk lookup from base_context_chunks.
        """
        if sp is None:
            raise ValueError("Reranker.run: 'sp' must not be None")

        retrieval_rows = sp.views_by_stage.get("retrieval")
        if not retrieval_rows:
            raise ValueError(
                "Reranker.run: Retrieval candidates are missing. "
                "Please run Retrieval before ReRanker."
            )

        if not sp.base_context_chunks:
            raise ValueError(
                "Reranker.run: base_context_chunks is empty. "
                "Please run Retrieval before ReRanker."
            )

        query_text = SuperPromptProjector.build_query_text(sp)

        query_pieces = split_query_into_pieces(
            query_text=query_text,
            chunker=self._chunker,
            chunk_size=DEFAULT_QUERY_CHUNK_SIZE,
            overlap=DEFAULT_QUERY_OVERLAP,
        )

        if not query_pieces:
            raise ValueError(
                "Reranker.run: no reranking query pieces could be built from SuperPrompt."
            )

        candidate_rows = list(retrieval_rows)[: self._top_k]
        chunk_lookup = {chunk_obj.id: chunk_obj for chunk_obj in sp.base_context_chunks}

        return query_pieces, candidate_rows, chunk_lookup

    def _clean_chunk_text(self, text: str) -> str:
        """
        Clean one chunk dynamically before ColBERT scoring.

        Design intention:
        - Remove obvious markdown / YAML / prompt-artifact rubbish.
        - Keep the original stored Chunk unchanged.
        - Stay conservative: preserve normal prose headings and content.
        """
        text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            return ""

        metadata_key_re = re.compile(
            r"^(title|author|version|updated|tags|date|created|modified|description)\s*:\s*.*$",
            re.IGNORECASE,
        )

        lines = text.split("\n")
        cleaned_lines: List[str] = []

        front_matter_active = False
        front_matter_checked = False
        seen_content = False

        for raw_line in lines:
            line = raw_line.strip()

            if not front_matter_checked:
                if not line:
                    continue
                if line == "---":
                    front_matter_active = True
                    front_matter_checked = True
                    continue
                front_matter_checked = True

            if front_matter_active:
                if line in {"---", "..."}:
                    front_matter_active = False
                continue

            if not line:
                if seen_content and (not cleaned_lines or cleaned_lines[-1] != ""):
                    cleaned_lines.append("")
                continue

            if line.startswith("```"):
                continue
            if line.lower().startswith("@@meta"):
                continue
            if line in {"### END_OF_PROMPT", "## END_OF_PROMPT", "END_OF_PROMPT"}:
                continue
            if metadata_key_re.match(line):
                continue

            cleaned_lines.append(line)
            seen_content = True

        while cleaned_lines and cleaned_lines[-1] == "":
            cleaned_lines.pop()

        return "\n".join(cleaned_lines).strip()

    def _score_with_colbert(
        self,
        query_pieces: List[str],
        retrieval_rows: List[tuple[str, float, A3ChunkStatus]],
        chunk_lookup: Dict[str, Chunk],
    ) -> List[RankedRow]:
        """
        Score the Retrieval candidates with ColBERT over the reranking query pieces.

        Returns:
            List[(chunk_id, aggregated_colbert_score, metadata)]

        Aggregation rule:
        - Each query piece produces one ColBERT reranked list.
        - For each chunk, aggregate piece-level scores by arithmetic mean.
        - The final ColBERT ranked list is then sorted deterministically.
        """
        valid_ids: List[str] = []
        cleaned_snippets: List[str] = []

        for row in retrieval_rows:
            chunk_id = str(row[0])
            chunk_obj = chunk_lookup.get(chunk_id)
            if chunk_obj is None:
                continue

            cleaned_snippet = self._clean_chunk_text(chunk_obj.snippet or "")
            if not cleaned_snippet:
                continue

            valid_ids.append(chunk_id)
            cleaned_snippets.append(cleaned_snippet)

        if not valid_ids:
            raise ValueError(
                "Reranker.run: no valid Retrieval candidates could be prepared for ColBERT."
            )

        documents_per_query: List[List[str]] = [list(cleaned_snippets) for _ in query_pieces]
        document_ids_per_query: List[List[str]] = [list(valid_ids) for _ in query_pieces]

        queries_embeddings = self._colbert_model.encode(
            query_pieces,
            is_query=True,
            show_progress_bar=False,
        )

        documents_embeddings = self._colbert_model.encode(
            documents_per_query,
            is_query=False,
            show_progress_bar=False,
        )

        reranked_documents = rank.rerank(
            documents_ids=document_ids_per_query,
            queries_embeddings=queries_embeddings,
            documents_embeddings=documents_embeddings,
        )

        score_sums: Dict[str, float] = {}
        score_counts: Dict[str, int] = {}

        for one_query_result in reranked_documents:
            for item in one_query_result:
                chunk_id = str(item["id"])
                score = float(item["score"])
                score_sums[chunk_id] = score_sums.get(chunk_id, 0.0) + score
                score_counts[chunk_id] = score_counts.get(chunk_id, 0) + 1

        scored_rows: List[RankedRow] = []

        for chunk_id in valid_ids:
            if chunk_id not in score_counts:
                continue

            mean_score = score_sums[chunk_id] / float(score_counts[chunk_id])
            base_meta = dict((chunk_lookup.get(chunk_id).meta or {}))
            meta_out = dict(base_meta)
            meta_out["colbert_score"] = float(mean_score)

            scored_rows.append((chunk_id, float(mean_score), meta_out))

        scored_rows.sort(key=lambda row: (-row[1], row[0]))
        return scored_rows

    def _fuse_with_retrieval(
        self,
        retrieval_rows: List[tuple[str, float, A3ChunkStatus]],
        colbert_rows: List[RankedRow],
        chunk_lookup: Dict[str, Chunk],
    ) -> List[RankedRow]:
        """
        Fuse Retrieval ranking and ColBERT ranking with equal-weight RRF.
        """
        retrieval_ranked_rows: List[RankedRow] = []

        for chunk_id, retrieval_score, _status in retrieval_rows:
            chunk_obj = chunk_lookup.get(str(chunk_id))
            if chunk_obj is None:
                continue

            meta_out = dict(chunk_obj.meta or {})

            # Preserve the old Retrieval fused score explicitly before the
            # second RRF merge overwrites the generic key "rrf_score".
            if "rrf_score" in meta_out and "retrieval_rrf_score" not in meta_out:
                meta_out["retrieval_rrf_score"] = float(meta_out["rrf_score"])

            retrieval_ranked_rows.append((str(chunk_id), float(retrieval_score), meta_out))

        return rrf_merge(
            retrieval_ranked_rows,
            colbert_rows,
            top_k=self._top_k,
            weight_a=DEFAULT_RETRIEVAL_WEIGHT,
            weight_b=DEFAULT_COLBERT_WEIGHT,
        )

    def _project_fused_metadata_to_reranker_contract(
        self,
        fused_rows: List[RankedRow],
    ) -> List[RankedRow]:
        """
        Translate neutral RRF merger metadata into reranker-specific metadata.

        Design rule:
        - Preserve existing Retrieval metadata in chunk.meta.
        - Preserve the old Retrieval fused score under:
            retrieval_rrf_score
        - Add reranker-specific aliases here:
            retrieval_score
            colbert_score
            retrieval_rank
            colbert_rank
            rerank_rrf_score
        """
        projected_rows: List[RankedRow] = []

        for chunk_id, fused_score, meta in fused_rows:
            meta_in = dict(meta or {})
            meta_out = dict(meta_in)

            if "score_a" in meta_in and "retrieval_score" not in meta_out:
                meta_out["retrieval_score"] = float(meta_in["score_a"])

            if "score_b" in meta_in and "colbert_score" not in meta_out:
                meta_out["colbert_score"] = float(meta_in["score_b"])

            if "rank_a" in meta_in and "retrieval_rank" not in meta_out:
                meta_out["retrieval_rank"] = int(meta_in["rank_a"])

            if "rank_b" in meta_in and "colbert_rank" not in meta_out:
                meta_out["colbert_rank"] = int(meta_in["rank_b"])

            if "retrieval_rrf_score" not in meta_out and "score_a" in meta_in:
                meta_out["retrieval_rrf_score"] = float(meta_in["score_a"])

            meta_out["rerank_rrf_score"] = float(fused_score)

            projected_rows.append((str(chunk_id), float(fused_score), meta_out))

        return projected_rows

    def _write_scores_back_to_chunks(
        self,
        fused_rows: List[RankedRow],
        chunk_lookup: Dict[str, Chunk],
    ) -> None:
        """
        Persist the reranker metadata into the hydrated chunk objects so that
        SuperPromptProjector can render the score text directly from chunk.meta.
        """
        for chunk_id, _score, meta in fused_rows:
            chunk_obj = chunk_lookup.get(str(chunk_id))
            if chunk_obj is None:
                continue

            merged_meta = dict(chunk_obj.meta or {})
            for key, value in dict(meta or {}).items():
                merged_meta[key] = value

            chunk_obj.meta = merged_meta

    def _build_reranked_view(
        self,
        fused_rows: List[RankedRow],
    ) -> tuple[List[tuple[str, float, A3ChunkStatus]], List[str]]:
        """
        Build the ordered ReRanker stage snapshot.

        Deterministic sort:
        1) higher final fused rerank score first
        2) stable fallback by chunk_id
        """
        fused_rows.sort(key=lambda row: (-row[1], row[0]))

        reranked_view: List[tuple[str, float, A3ChunkStatus]] = []
        reranked_ids: List[str] = []

        for chunk_id, score, _meta in fused_rows:
            reranked_view.append((str(chunk_id), float(score), A3ChunkStatus.SELECTED))
            reranked_ids.append(str(chunk_id))

        return reranked_view, reranked_ids
```

### ~\ragstream\retrieval\retriever.py
```python
# retriever.py
# -*- coding: utf-8 -*-
"""
retriever.py

Purpose:
    Deterministic Retrieval stage orchestrator for RAGstream.

Design:
    - Keep Retriever as the top-level stage class used by the controller.
    - Keep query-building / query-splitting support logic outside this file.
    - Keep the dense retrieval backend in RetrieverEmb.
    - Add a parallel SPLADE retrieval backend in RetrieverSplade.
    - Merge both branches with deterministic RRF.
    - Keep hydration and SuperPrompt write-back in this file.
    - Preserve the current external Retriever.run(...) contract.

Current flow inside Retriever.run(...):
    1) PreProcessing
       - build retrieval query text from SuperPrompt
       - split the query into overlapping query pieces
    2) Retriever_EMB
       - run the dense embedding-based retrieval backend
    3) Retriever_SPLADE
       - score exactly the dense-selected candidate IDs
    4) RRF_Merger
       - fuse both ranked lists deterministically
    5) PostProcessing
       - hydrate ranked rows into real Chunk objects
       - write the retrieval result into SuperPrompt
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from ragstream.ingestion.chunker import Chunker
from ragstream.ingestion.embedder import Embedder
from ragstream.ingestion.splade_embedder import SpladeEmbedder
from ragstream.orchestration.super_prompt import A3ChunkStatus, SuperPrompt
from ragstream.orchestration.superprompt_projector import SuperPromptProjector
from ragstream.retrieval.chunk import Chunk
from ragstream.retrieval.doc_score import DocScore  # compatibility re-export
from ragstream.retrieval.retriever_emb import RetrieverEmb
from ragstream.retrieval.retriever_splade import RetrieverSplade
from ragstream.retrieval.rrf_merger import rrf_merge
from ragstream.retrieval.smart_query_splitter import split_query_into_pieces


# Keep old import compatibility:
# from ragstream.retrieval.retriever import DocScore
DocScore = DocScore

# Ranked row returned by RetrieverEmb / RetrieverSplade / RRF merger:
# (chunk_id, retrieval_score, metadata)
RankedRow = Tuple[str, float, Dict[str, Any]]

# Retrieval query splitting defaults.
# These MUST stay aligned with the current behavior so that the refactor
# preserves the same practical output as before.
DEFAULT_QUERY_CHUNK_SIZE = 1200
DEFAULT_QUERY_OVERLAP = 120


class Retriever:
    """
    Deterministic Retrieval stage orchestrator for document chunks.

    Design:
    - Keep this class focused on stage orchestration.
    - Keep low-level retrieval engine logic outside this file.
    - Keep hydration + SuperPrompt write-back here.
    - The evolving pipeline state still lives in SuperPrompt.
    """

    def __init__(
        self,
        *,
        doc_root: str,
        chroma_root: str,
        embedder: Embedder | None = None,
        chunker: Chunker | None = None,
        runtime_config: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize Retrieval with explicit project roots and shared helpers.

        Args:
            doc_root:
                Absolute path to the doc_raw root folder.
            chroma_root:
                Absolute path to the chroma_db root folder.
            embedder:
                Optional shared Embedder instance.
            chunker:
                Optional shared Chunker instance.
        """
        self.doc_root = Path(doc_root).resolve()
        self.chroma_root = Path(chroma_root).resolve()

        # SPLADE DB is kept parallel to chroma_db under the same data root.
        self.splade_root = self.chroma_root.parent / "splade_db"

        self.embedder = embedder if embedder is not None else Embedder(model="text-embedding-3-small")
        self.chunker = chunker if chunker is not None else Chunker()
        self.runtime_config = runtime_config if isinstance(runtime_config, dict) else {}

        # Keep the chunk class explicit so hydration remains readable and testable.
        self.chunk_cls = Chunk

        # Dense backend remains unchanged and independent.
        self.retriever_emb = RetrieverEmb(
            chroma_root=str(self.chroma_root),
            embedder=self.embedder,
        )

        # Lazy init for SPLADE so app startup does not immediately load the sparse model.
        self._splade_embedder: SpladeEmbedder | None = None
        self._retriever_splade: RetrieverSplade | None = None

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def run(
        self,
        sp: SuperPrompt,
        project_name: str,
        top_k: int,
        *,
        use_retrieval_splade: bool = True,
    ) -> SuperPrompt:
        """
        Execute the Retrieval stage and update the same SuperPrompt in place.

        Visible flow:
            1) PreProcessing
            2) Retriever_EMB
            3) Retriever_SPLADE or dense passthrough clone
            4) RRF_Merger
            5) PostProcessing

        Returns:
            The same SuperPrompt instance, mutated in place.
        """
        query_pieces = self._preprocess(sp)

        ranked_rows_emb = self.retriever_emb.run(
            project_name=project_name,
            query_pieces=query_pieces,
            top_k=top_k,
        )

        ranked_rows_emb = self._apply_hard_embedding_floor(ranked_rows_emb)

        ranked_rows_splade: List[RankedRow]

        if use_retrieval_splade and ranked_rows_emb:
            candidate_ids = [str(chunk_id) for chunk_id, _score, _meta in ranked_rows_emb]

            try:
                ranked_rows_splade = self._get_retriever_splade().run(
                    project_name=project_name,
                    query_pieces=query_pieces,
                    top_k=top_k,
                    candidate_ids=candidate_ids,
                )
            except FileNotFoundError:
                # Keep Retrieval usable even if an older project has no SPLADE store yet.
                ranked_rows_splade = []
        else:
            # Bypass real SPLADE and duplicate the dense branch into the second
            # RRF input slot so the downstream Retrieval contract stays unchanged.
            ranked_rows_splade = [
                (str(chunk_id), float(score), dict(meta or {}))
                for chunk_id, score, meta in ranked_rows_emb
            ]

        ranked_rows = rrf_merge(
            ranked_rows_emb,
            ranked_rows_splade,
            top_k=top_k,
            weight_a=0.75,
            weight_b=0.25,
        )

        ranked_rows = self._project_rrf_metadata_to_retrieval_contract(ranked_rows)

        sp = self._postprocess(sp, ranked_rows)
        return sp

    # -----------------------------------------------------------------
    # Stage-level orchestration helpers
    # -----------------------------------------------------------------

    def _preprocess(self, sp: SuperPrompt) -> List[str]:
        """
        Build the retrieval query text from SuperPrompt and split it into
        overlapping query pieces.

        Query-building and query-splitting support logic lives outside this file.
        Retriever keeps only the stage-level orchestration.
        """
        query_text = SuperPromptProjector.build_query_text(sp)

        query_pieces = split_query_into_pieces(
            query_text=query_text,
            chunker=self.chunker,
            chunk_size=DEFAULT_QUERY_CHUNK_SIZE,
            overlap=DEFAULT_QUERY_OVERLAP,
        )

        return query_pieces

    def _postprocess(self, sp: SuperPrompt, ranked_rows: List[RankedRow]) -> SuperPrompt:
        """
        Complete the Retrieval stage after the backend retrievers have finished.

        Responsibilities:
        - hydrate ranked rows into real Chunk objects
        - write the fused retrieval result into SuperPrompt
        """
        valid_ranked_rows, hydrated_chunks = self._hydrate_ranked_chunks(ranked_rows)
        self._write_stage_to_superprompt(sp, valid_ranked_rows, hydrated_chunks)
        return sp

    def _get_retriever_splade(self) -> RetrieverSplade:
        """
        Lazily initialize the SPLADE backend on first retrieval use.
        """
        if self._retriever_splade is None:
            if self._splade_embedder is None:
                self._splade_embedder = SpladeEmbedder(device="cpu")

            self._retriever_splade = RetrieverSplade(
                splade_root=str(self.splade_root),
                splade_embedder=self._splade_embedder,
            )

        return self._retriever_splade

    # -----------------------------------------------------------------
    # Internal helpers kept in retriever.py
    # -----------------------------------------------------------------

    def _apply_hard_embedding_floor(
        self,
        ranked_rows_emb: List[RankedRow],
    ) -> List[RankedRow]:
        """
        Remove dense retrieval rows below the configured hard embedding floor.

        The dense row score is the embedding similarity score that later appears
        as Emb=... in the SuperPrompt raw retrieved evidence.
        """
        document_retrieval_config = self.runtime_config.get("document_retrieval", {}) or {}
        hard_embedding_floor = float(document_retrieval_config.get("hard_embedding_floor", 0.0) or 0.0)

        if hard_embedding_floor <= 0.0:
            return ranked_rows_emb

        return [
            (str(chunk_id), float(score), dict(meta or {}))
            for chunk_id, score, meta in ranked_rows_emb
            if float(score) >= hard_embedding_floor
        ]

    def _project_rrf_metadata_to_retrieval_contract(
        self,
        ranked_rows: List[RankedRow],
    ) -> List[RankedRow]:
        """
        Translate neutral RRF merger metadata into retrieval-specific metadata.

        Why this exists:
        - rrf_merger.py is intentionally neutral and uses generic names:
            score_a, score_b, rank_a, rank_b
        - Retriever is the correct higher-level place that knows:
            a = dense embedding branch
            b = SPLADE branch
        - SuperPrompt projector and other retrieval-facing code can therefore
          keep reading the retrieval-specific names:
            emb_score, splade_score, emb_rank, splade_rank, rrf_score

        Design rule:
        - Preserve the neutral keys if they already exist.
        - Add the retrieval-specific aliases here.
        """
        projected_rows: List[RankedRow] = []

        for chunk_id, fused_score, meta in ranked_rows:
            meta_in = dict(meta or {})
            meta_out = dict(meta_in)

            if "score_a" in meta_in and "emb_score" not in meta_out:
                meta_out["emb_score"] = float(meta_in["score_a"])

            if "score_b" in meta_in and "splade_score" not in meta_out:
                meta_out["splade_score"] = float(meta_in["score_b"])

            if "rank_a" in meta_in and "emb_rank" not in meta_out:
                meta_out["emb_rank"] = int(meta_in["rank_a"])

            if "rank_b" in meta_in and "splade_rank" not in meta_out:
                meta_out["splade_rank"] = int(meta_in["rank_b"])

            if "rrf_score" not in meta_out:
                meta_out["rrf_score"] = float(fused_score)

            projected_rows.append((str(chunk_id), float(fused_score), meta_out))

        return projected_rows

    def _hydrate_ranked_chunks(
        self,
        ranked_rows: List[RankedRow],
    ) -> tuple[List[RankedRow], List[Chunk]]:
        """
        Reconstruct real Chunk objects for the selected ranked rows.

        Why reconstruction is needed:
        - Vector stores keep vectors + metadata only.
        - The actual chunk text must therefore be rebuilt from doc_raw
          using the same chunker and the stored chunk_idx.

        Important robustness rule:
        - If one retrieved row points to a stale or broken source file,
          we skip that row instead of crashing the whole Retrieval stage.

        Returns:
            (valid_ranked_rows, hydrated_chunks)

            valid_ranked_rows:
                Only the rows that could be reconstructed successfully.
            hydrated_chunks:
                Chunk objects aligned 1:1 with valid_ranked_rows.
        """
        valid_ranked_rows: List[RankedRow] = []
        hydrated: List[Chunk] = []

        # Local caches avoid re-reading and re-splitting the same source file
        # when several retrieved chunks come from that file.
        text_cache: Dict[str, str] = {}
        split_cache: Dict[str, List[tuple[str, str]]] = {}

        step = DEFAULT_QUERY_CHUNK_SIZE - DEFAULT_QUERY_OVERLAP

        for chunk_id, score, meta in ranked_rows:
            meta = meta or {}

            rel_path = str(meta.get("path") or "").strip()
            if not rel_path:
                continue

            raw_path = self.doc_root / rel_path
            if not raw_path.exists():
                continue

            chunk_idx_raw = meta.get("chunk_idx")
            if chunk_idx_raw is None:
                continue

            chunk_idx = int(chunk_idx_raw)

            cache_key = raw_path.as_posix()
            if cache_key not in text_cache:
                text_cache[cache_key] = raw_path.read_text(encoding="utf-8", errors="ignore")

            if cache_key not in split_cache:
                split_cache[cache_key] = self.chunker.split(
                    file_path=str(raw_path),
                    text=text_cache[cache_key],
                    chunk_size=DEFAULT_QUERY_CHUNK_SIZE,
                    overlap=DEFAULT_QUERY_OVERLAP,
                )

            all_chunks_for_file = split_cache[cache_key]
            if chunk_idx < 0 or chunk_idx >= len(all_chunks_for_file):
                continue

            _fp, snippet = all_chunks_for_file[chunk_idx]

            source_text = text_cache[cache_key]
            start = chunk_idx * step
            end = min(start + DEFAULT_QUERY_CHUNK_SIZE, len(source_text))

            chunk_obj = self.chunk_cls(
                id=chunk_id,
                source=rel_path,
                snippet=snippet,
                span=(start, end),
                meta=dict(meta),
            )

            valid_ranked_rows.append((chunk_id, float(score), dict(meta)))
            hydrated.append(chunk_obj)

        return valid_ranked_rows, hydrated

    def _write_stage_to_superprompt(
            self,
            sp: SuperPrompt,
            ranked_rows: List[RankedRow],
            hydrated_chunks: List[Chunk],
    ) -> None:
        """
        Persist the Retrieval result into the evolving SuperPrompt.

        Write-back contract for this stage:
        - base_context_chunks:
            the hydrated Chunk objects in retrieval order
        - views_by_stage["retrieval"]:
            ordered triples (chunk_id, retrieval_score, SELECTED)
            where retrieval_score is the current retrieval score
        - views_by_stage["reranked"]:
            A3-ready passthrough view initialized from Retrieval.
            If real ColBERT ReRanker runs later, it overwrites this view.
        - final_selection_ids:
            ordered chunk IDs from the current retrieval result
        - stage/history:
            Retrieval remains the current lifecycle stage.
        """
        if len(ranked_rows) != len(hydrated_chunks):
            raise RuntimeError(
                "Retriever._write_stage_to_superprompt: ranked_rows and hydrated_chunks length mismatch"
            )

        sp.base_context_chunks = list(hydrated_chunks)

        retrieval_view: List[tuple[str, float, A3ChunkStatus]] = []
        a3_ready_view: List[tuple[str, float, A3ChunkStatus]] = []
        final_ids: List[str] = []

        for position, (chunk_id, score, _meta) in enumerate(ranked_rows, start=1):
            chunk_id_str = str(chunk_id)
            score_float = float(score)

            retrieval_view.append((chunk_id_str, score_float, A3ChunkStatus.SELECTED))
            a3_ready_view.append((chunk_id_str, score_float, A3ChunkStatus.SELECTED))
            final_ids.append(chunk_id_str)

        sp.views_by_stage["retrieval"] = retrieval_view

        # Important:
        # Retrieval initializes an A3-ready candidate view immediately.
        # This is not real ColBERT reranking.
        # It is a deterministic passthrough so A3 can run directly after Retrieval.
        # If ColBERT is enabled later, Reranker.run(...) overwrites this key.
        sp.views_by_stage["reranked"] = a3_ready_view

        sp.final_selection_ids = final_ids
        sp.stage = "retrieval"
        sp.history_of_stages.append("retrieval")

        if not hasattr(sp, "extras") or sp.extras is None:
            sp.extras = {}

        sp.extras["a3_ready_source"] = "retrieval_passthrough"
        sp.extras["a3_ready_candidate_count"] = len(a3_ready_view)
        sp.extras["reranked_is_passthrough"] = True
```

### ~\ragstream\retrieval\retriever_emb.py
```python
# retriever_emb.py
# -*- coding: utf-8 -*-
"""
retriever_emb.py

Purpose:
    Current embedding-based retrieval backend extracted out of retriever.py.

Scope of this file:
    - Receive neutral retrieval inputs only:
        * project_name
        * query_pieces
        * top_k
    - Open the active project's Chroma document store.
    - Compare every stored chunk embedding against all query-piece embeddings.
    - Aggregate per-chunk similarities with p-norm averaging.
    - Return ranked retrieval rows to the top-level Retriever stage.

Important design rule:
    - This class does NOT know SuperPrompt.
    - This class does NOT hydrate chunk text from doc_raw.
    - This class does NOT write anything back into the pipeline state.
    - It only performs the current embedding-based ranking backend.

Stage-1 refactor goal:
    Preserve the current embedding-based retrieval behavior while moving the
    backend ranking logic out of retriever.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

from ragstream.ingestion.embedder import Embedder
from ragstream.ingestion.vector_store_chroma import VectorStoreChroma

# Ranked row returned to Retriever:
# (chunk_id, retrieval_score, metadata)
RankedRow = Tuple[str, float, Dict[str, Any]]

# Fallback number of chunks to keep if the caller gives no valid top-k.
DEFAULT_TOP_K = 100

# Agreed retrieval aggregation constant:
# p-value for p-norm averaging across query pieces.
DEFAULT_P_NORM = 10


class RetrieverEmb:
    """
    Current embedding-based retrieval backend.

    Design:
    - Receive neutral retrieval inputs only.
    - Perform current dense retrieval ranking.
    - Return ranked rows to the top-level Retriever.
    """

    def __init__(self, *, chroma_root: str, embedder: Embedder) -> None:
        """
        Initialize the embedding-based retrieval backend.

        Args:
            chroma_root:
                Absolute path to the chroma_db root folder.
            embedder:
                Shared Embedder instance used to embed the query pieces.
        """
        self.chroma_root = Path(chroma_root).resolve()
        self.embedder = embedder

    def run(self, *, project_name: str, query_pieces: List[str], top_k: int) -> List[RankedRow]:
        """
        Execute the current embedding-based retrieval backend.

        Inputs:
            project_name:
                Active project selected in the GUI.
            query_pieces:
                Pre-split retrieval query pieces.
            top_k:
                Number of chunks to keep after ranking.

        Returns:
            Ranked retrieval rows in this format:
                [
                    (chunk_id, retrieval_score, metadata),
                    ...
                ]

        Error-handling rule:
        - Local validation belongs here, at the lower level.
        - The top-level Retriever.run(...) stays visually simple.
        """
        project_name = (project_name or "").strip()
        if not project_name:
            raise ValueError("RetrieverEmb.run: project_name must not be empty")

        if not self.chroma_root.exists():
            raise FileNotFoundError(
                f"RetrieverEmb.run: chroma_root does not exist: {self.chroma_root}"
            )

        project_db_dir = self.chroma_root / project_name
        if not project_db_dir.exists():
            raise FileNotFoundError(
                f"RetrieverEmb.run: active project Chroma DB does not exist: {project_db_dir}"
            )

        if not query_pieces:
            return []

        k = int(top_k) if int(top_k) > 0 else DEFAULT_TOP_K

        store = VectorStoreChroma(persist_dir=str(project_db_dir))
        raw = store.collection.get(include=["embeddings", "metadatas"])

        ids: List[str] = raw.get("ids", []) if raw else []
        metadatas: List[Dict[str, Any] | None] = raw.get("metadatas", []) if raw else []
        embeddings = raw.get("embeddings", []) if raw else []

        # embeddings may come back as a NumPy array, so never test it with
        # "if not embeddings". Use explicit length checks instead.
        if len(ids) == 0 or len(embeddings) == 0:
            return []

        if len(ids) != len(embeddings):
            raise RuntimeError(
                "RetrieverEmb.run: Chroma returned mismatched ids/embeddings lengths"
            )

        if len(metadatas) > 0 and len(metadatas) != len(ids):
            raise RuntimeError(
                "RetrieverEmb.run: Chroma returned mismatched ids/metadatas lengths"
            )

        query_vectors = self.embedder.embed(query_pieces)

        if len(query_vectors) == 0:
            return []

        A = np.asarray(embeddings, dtype=np.float32)    # stored chunks: [N, D]
        Q = np.asarray(query_vectors, dtype=np.float32) # query pieces:  [M, D]

        if A.ndim != 2 or Q.ndim != 2:
            raise RuntimeError(
                "RetrieverEmb.run: unexpected embedding dimensions returned by Chroma/OpenAI"
            )

        if A.shape[1] != Q.shape[1]:
            raise RuntimeError(
                "RetrieverEmb.run: stored vectors and query vectors have different dimensions"
            )

        # Normalize rows to compute cosine similarity as a matrix product.
        # Similarities shape: [N_chunks, M_query_pieces]
        A_norm = A / (np.linalg.norm(A, axis=1, keepdims=True) + 1e-12)
        Q_norm = Q / (np.linalg.norm(Q, axis=1, keepdims=True) + 1e-12)
        sims = A_norm @ Q_norm.T

        # p-mean aggregation over the query-piece axis.
        # Strongly favors the best match, but is still not pure max.
        p = DEFAULT_P_NORM
        sims_pos = np.clip(sims, 0.0, None)
        aggregated_scores = np.power(np.mean(np.power(sims_pos, p), axis=1), 1.0 / p)

        rows: List[RankedRow] = []
        for idx, chunk_id in enumerate(ids):
            meta = metadatas[idx] if (len(metadatas) > 0 and metadatas[idx] is not None) else {}
            rows.append(
                (
                    str(chunk_id),
                    float(aggregated_scores[idx]),
                    dict(meta),
                )
            )

        # Deterministic sort:
        # 1) higher score first
        # 2) stable fallback by chunk_id
        rows.sort(key=lambda row: (-row[1], row[0]))

        return rows[: min(k, len(rows))]
```

### ~\ragstream\retrieval\retriever_mem.py
```python
# ragstream/retrieval/retriever_mem.py
# -*- coding: utf-8 -*-
"""
MemoryRetriever
===============
Memory Retrieval stage orchestrator.

This file is the retrieval-side entry point for the Memory subsystem.

It reads:
- current SuperPrompt
- current active MemoryManager
- dedicated MemoryVectorStore
- memory_index.sqlite3 through MemoryIndexLookup
- runtime_config["memory_retrieval"]

It writes:
- raw MemoryContextPack into SuperPrompt
- synthesized Memory Context into SuperPrompt
- latest ActiveRetrievalBrief into SuperPrompt

It does NOT run:
- A3
- A4
- PromptBuilder
"""

from __future__ import annotations

import json

from pathlib import Path
from typing import Any

from ragstream.memory.retrieval.memory_context_pack import MemoryContextPack
from ragstream.memory.retrieval.memory_index_lookup import MemoryIndexLookup
from ragstream.memory.retrieval.memory_scoring import MemoryScorer
from ragstream.memory.compression.memory_compressor import MemoryCompressor
from ragstream.memory.memory_merge_synthesizer import MemoryMergeSynthesizer
from ragstream.orchestration.superprompt_projector import SuperPromptProjector
from ragstream.textforge.RagLog import LogALL as logger
from ragstream.textforge.RagLog import LogDeveloper as _logger_dev
DEV_LOG_ENABLED = False

def logger_dev(*args, **kwargs):
    if DEV_LOG_ENABLED:
        return _logger_dev(*args, **kwargs)
    return None

class MemoryRetriever:
    """
    Main Memory Retrieval orchestrator.

    This class is intentionally thin:
    - vector querying is delegated to MemoryVectorStore / Chroma access
    - SQLite lookup is delegated to MemoryIndexLookup
    - scoring is delegated to MemoryScorer
    - candidate storage is delegated to MemoryContextPack
    - final Memory Context synthesis is delegated to MemoryMergeSynthesizer
    """

    def __init__(
        self,
        memory_manager: Any,
        memory_vector_store: Any,
        sqlite_path: str | Path,
        config: dict[str, Any],
    ) -> None:
        self.memory_manager = memory_manager
        self.memory_vector_store = memory_vector_store
        self.runtime_config = dict(config or {})

        # Accept either the full runtime_config or only runtime_config["memory_retrieval"].
        if "memory_retrieval" in (config or {}):
            self.config = dict(config.get("memory_retrieval", {}) or {})
        else:
            self.config = dict(config or {})

        memory_root = getattr(memory_manager, "memory_root", None)
        self.index_lookup = MemoryIndexLookup(
            sqlite_path=sqlite_path,
            memory_root=memory_root,
        )
        self.scorer = MemoryScorer(self.config)
        self.compressor = MemoryCompressor(self.runtime_config)
        self.memory_synthesizer = MemoryMergeSynthesizer(runtime_config=self.runtime_config)

    def run(
        self,
        sp: Any,
    ) -> Any:
        """
        Run Memory Retrieval for the current SuperPrompt.

        The method mutates and returns the same SuperPrompt object.
        """
        if self.config.get("enabled", True) is False:
            logger("Memory Retrieval skipped: disabled in runtime_config.", "INFO", "INTERNAL")
            return sp

        active_file_id = str(getattr(self.memory_manager, "file_id", "") or "").strip()
        if not active_file_id:
            logger("Memory Retrieval skipped: no active memory file.", "INFO", "INTERNAL")
            return self._write_empty_pack(sp, reason="no_active_memory_file")

        query_text = self._build_query_text(sp)
        if not query_text:
            logger("Memory Retrieval skipped: empty query text.", "WARN", "PUBLIC")
            return self._write_empty_pack(sp, reason="empty_query_text")

        direct_recall_key = self._extract_direct_recall_key(sp)
        active_brief_info = self._find_latest_active_brief_info()

        logger(
            f"Memory Retrieval started: file={active_file_id[:8]}",
            "INFO",
            "PUBLIC",
        )

        logger_dev(
            (
                "Memory Retrieval input\n"
                f"active_file_id={active_file_id}\n"
                f"memory_title={getattr(self.memory_manager, 'title', '')}\n"
                f"query_text={query_text}\n"
                f"active_brief_title={active_brief_info.get('active_retrieval_brief_title', '')}\n"
                f"direct_recall_key={direct_recall_key}\n"
                f"config={json.dumps(self.config, ensure_ascii=False, indent=2, default=str)}"
            ),
            "DEBUG",
            "CONFIDENTIAL",
        )

        semantic_result = self._run_semantic_pass(
            query_text=query_text,
            active_file_id=active_file_id,
        )

        index_candidates = self._collect_index_candidates(
            active_file_id=active_file_id,
            direct_recall_key=direct_recall_key,
        )

        pack = self._build_context_pack(
            semantic_chunks=semantic_result["semantic_chunks"],
            episodic_candidates=semantic_result["episodic_candidates"],
            working_candidates=index_candidates["working_memory"],
            direct_recall_candidate=index_candidates["direct_recall"],
            gold_candidates=index_candidates["gold"],
            query_text=query_text,
            active_brief_info=active_brief_info,
            diagnostics={
                "query_text": query_text,
                "active_file_id": active_file_id,
                "direct_recall_key": direct_recall_key,
                "raw_vector_hit_count": len(semantic_result["raw_hits"]),
                "scored_vector_hit_count": len(semantic_result["scored_hits"]),
                "parent_score_count": len(semantic_result["parent_scores"]),
                "index_counts": {
                    "working_memory": len(index_candidates["working_memory"]),
                    "gold": len(index_candidates["gold"]),
                    "direct_recall": 1 if index_candidates["direct_recall"] else 0,
                },
                "scoring_policy": self.scorer.describe_policy(),
            },
        )

        self._write_to_superprompt(
            sp=sp,
            pack=pack,
            active_brief_info=active_brief_info,
        )

        self._log_developer_diagnostics(
            query_text=query_text,
            active_file_id=active_file_id,
            semantic_result=semantic_result,
            index_candidates=index_candidates,
            pack=pack,
        )

        logger(
            (
                "Memory Retrieval finished: "
                f"working={len(pack.working_memory_candidates)}, "
                f"episodic={len(pack.episodic_candidates)}, "
                f"semantic_chunks={len(pack.semantic_memory_chunks)}, "
                f"memory_context={1 if pack.synthesized_memory_context else 0}, "
                f"direct_recall={1 if pack.direct_recall_candidate else 0}"
            ),
            "INFO",
            "PUBLIC",
        )

        return sp

    def _build_query_text(
        self,
        sp: Any,
    ) -> str:
        """
        Build memory retrieval query text from SuperPrompt.

        Primary source:
        - sp.effective_retrieval_query_text filled by PreProcessing.

        Fallback:
        - build from TASK / PURPOSE / CONTEXT using SuperPromptProjector.
        """
        effective_query_text = str(getattr(sp, "effective_retrieval_query_text", "") or "").strip()
        if effective_query_text:
            return effective_query_text

        try:
            return SuperPromptProjector.build_query_text(sp)
        except Exception:
            pass

        body = getattr(sp, "body", {}) or {}

        parts: list[str] = []

        for key in ("task", "purpose", "context", "text"):
            value = str(body.get(key, "") or "").strip()
            if value:
                parts.append(value)

        if not parts:
            prompt_ready = str(getattr(sp, "prompt_ready", "") or "").strip()
            if prompt_ready:
                parts.append(prompt_ready)

        return "\n\n".join(parts).strip()

    def _run_semantic_pass(
        self,
        query_text: str,
        active_file_id: str,
    ) -> dict[str, Any]:
        """
        Run memory vector search and parent aggregation.
        """
        semantic_cfg = self.config.get("semantic_memory_chunks", {}) or {}
        if semantic_cfg.get("enabled", True) is False:
            return {
                "raw_hits": [],
                "scored_hits": [],
                "parent_scores": [],
                "semantic_chunks": [],
                "episodic_candidates": [],
            }

        max_memory_chunks = int(semantic_cfg.get("max_memory_chunks", 5))

        # Retrieve more raw hits than final memory chunks because parent scoring
        # needs enough question/answer/handle evidence.
        raw_hit_limit = max(max_memory_chunks * 6, 20)

        raw_hits = self._query_memory_vectors(
            query_text=query_text,
            active_file_id=active_file_id,
            n_results=raw_hit_limit,
        )

        metadata_by_record = self._metadata_by_live_record()

        scored_hits = self.scorer.score_vector_hits(raw_hits)
        parent_scores = self.scorer.aggregate_parent_scores(
            scored_hits=scored_hits,
            metadata_by_record=metadata_by_record,
        )

        semantic_chunks = self.scorer.select_semantic_chunks(
            scored_hits=scored_hits,
            max_memory_chunks=max_memory_chunks,
            metadata_by_record=metadata_by_record,
        )

        episodic_candidates = self._parent_scores_to_episodic_candidates(
            parent_scores=parent_scores,
            active_file_id=active_file_id,
        )

        return {
            "raw_hits": raw_hits,
            "scored_hits": scored_hits,
            "parent_scores": parent_scores,
            "semantic_chunks": semantic_chunks,
            "episodic_candidates": episodic_candidates,
        }

    def _collect_index_candidates(
        self,
        active_file_id: str,
        direct_recall_key: str,
    ) -> dict[str, Any]:
        """
        Collect deterministic non-vector memory candidates.
        """
        working_memory = self.index_lookup.get_working_memory(
            file_id=active_file_id,
            cfg=self.config,
        )

        gold = self.index_lookup.get_latest_gold(
            file_id=active_file_id,
            cfg=self.config,
        )

        direct_recall = self.index_lookup.get_direct_recall(
            direct_recall_key=direct_recall_key,
            cfg=self.config,
        )

        working_memory = self._enrich_candidates_from_live_records(working_memory)
        gold = self._enrich_candidates_from_live_records(gold)

        if direct_recall:
            direct_recall = self._enrich_candidates_from_live_records([direct_recall])[0]

        return {
            "working_memory": working_memory,
            "gold": gold,
            "direct_recall": direct_recall,
        }

    def _build_context_pack(
        self,
        semantic_chunks: list[dict[str, Any]],
        episodic_candidates: list[dict[str, Any]],
        working_candidates: list[dict[str, Any]],
        direct_recall_candidate: dict[str, Any] | None,
        gold_candidates: list[dict[str, Any]],
        query_text: str,
        active_brief_info: dict[str, Any],
        diagnostics: dict[str, Any],
    ) -> MemoryContextPack:
        """
        Combine all raw memory candidates into one runtime pack.
        """
        pack = MemoryContextPack()

        for candidate in working_candidates:
            pack.add_working_memory(candidate)

        episodic_final = self._merge_episodic_candidates(
            semantic_episodic=episodic_candidates,
            gold_candidates=gold_candidates,
        )

        episodic_final = self.compressor.compress_episodic_candidates(
            episodic_candidates=episodic_final,
            effective_query_text=query_text,
        )

        for candidate in episodic_final:
            pack.add_episodic_candidate(candidate)

        for candidate in semantic_chunks:
            pack.add_semantic_chunk(candidate)

        pack.set_direct_recall(direct_recall_candidate)

        synthesis_result = self.memory_synthesizer.synthesize(
            effective_retrieval_query_text=query_text,
            active_retrieval_brief_title=str(active_brief_info.get("active_retrieval_brief_title", "") or ""),
            active_retrieval_brief=str(active_brief_info.get("active_retrieval_brief", "") or ""),
            episodic_candidates=pack.episodic_candidates,
            semantic_memory_chunks=pack.semantic_memory_chunks,
        )

        pack.set_synthesized_memory_context(
            memory_context=str(synthesis_result.get("memory_context", "") or ""),
            diagnostics=dict(synthesis_result.get("memory_synthesis_diagnostics", {}) or {}),
        )

        pack.set_selection_diagnostics(diagnostics)
        pack.set_token_budget_report(self._estimate_token_budget(pack))

        return pack

    def _write_to_superprompt(
        self,
        *,
        sp: Any,
        pack: MemoryContextPack,
        active_brief_info: dict[str, Any],
    ) -> None:
        """
        Store MemoryContextPack, synthesized Memory Context, and ActiveBrief
        into SuperPrompt.
        """
        setattr(sp, "memory_context_pack", pack)
        setattr(sp, "memory_context_text", pack.synthesized_memory_context)

        active_title = str(active_brief_info.get("active_retrieval_brief_title", "") or "").strip()
        active_brief = str(active_brief_info.get("active_retrieval_brief", "") or "").strip()

        setattr(sp, "active_memory_brief_title", active_title)
        setattr(sp, "active_memory_brief", active_brief)

        if not hasattr(sp, "extras") or getattr(sp, "extras") is None:
            setattr(sp, "extras", {})

        sp.extras["memory_context_pack"] = pack.to_dict()
        sp.extras["memory_context_text"] = pack.synthesized_memory_context
        sp.extras["memory_debug_markdown"] = pack.to_debug_markdown()
        sp.extras["memory_retrieval_counts"] = pack.counts()
        sp.extras["active_memory_brief_title"] = active_title
        sp.extras["active_memory_brief"] = active_brief

    def _query_memory_vectors(
        self,
        query_text: str,
        active_file_id: str,
        n_results: int,
    ) -> list[dict[str, Any]]:
        """
        Query the underlying Chroma memory vector collection.

        Current MemoryVectorStore owns the Chroma collection internally.
        This method uses that object without changing the existing store API.
        A later cleanup can move this method into MemoryVectorStore directly.
        """
        collection = getattr(self.memory_vector_store, "_collection", None)
        embedder = getattr(self.memory_vector_store, "embedder", None)

        if collection is None or embedder is None:
            logger("Memory vector search unavailable: store has no collection/embedder.", "WARN", "PUBLIC")
            return []

        query_embedding = self._embed_query(query_text, embedder)

        where = {"file_id": active_file_id} if active_file_id else None

        try:
            result = collection.query(
                query_embeddings=[query_embedding],
                n_results=int(n_results),
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as first_error:
            logger(
                f"Memory vector search with file_id filter failed; retrying without filter: {first_error}",
                "WARN",
                "INTERNAL",
            )
            result = collection.query(
                query_embeddings=[query_embedding],
                n_results=int(n_results),
                include=["documents", "metadatas", "distances"],
            )

        raw_hits = self._normalize_chroma_query_result(result)

        logger_dev(
            "Raw memory vector hits\n"
            + json.dumps(raw_hits, ensure_ascii=False, indent=2, default=str),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return raw_hits

    def _embed_query(
        self,
        query_text: str,
        embedder: Any,
    ) -> list[float]:
        """
        Create one dense vector for memory query text.
        """
        vectors = embedder.embed([query_text])
        vector = vectors[0]

        if hasattr(vector, "tolist"):
            vector = vector.tolist()

        return [float(value) for value in vector]

    def _normalize_chroma_query_result(
        self,
        result: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Convert Chroma query result shape into a flat list of hit dictionaries.
        """
        ids = (result.get("ids") or [[]])[0] or []
        documents = (result.get("documents") or [[]])[0] or []
        metadatas = (result.get("metadatas") or [[]])[0] or []
        distances = (result.get("distances") or [[]])[0] or []

        hits: list[dict[str, Any]] = []

        for idx, vector_id in enumerate(ids):
            metadata = metadatas[idx] if idx < len(metadatas) and metadatas[idx] else {}
            document = documents[idx] if idx < len(documents) else ""
            distance = distances[idx] if idx < len(distances) else None

            hits.append(
                {
                    "id": vector_id,
                    "document": document,
                    "metadata": metadata,
                    "distance": distance,
                    "rank": idx + 1,
                }
            )

        return hits

    def _metadata_by_live_record(self) -> dict[str, dict[str, Any]]:
        """
        Build record metadata map from live MemoryManager.records.

        Adds episode-distance metadata:
        - latest record gets episode_distance_k = 0
        - one older record gets episode_distance_k = 1
        - and so on

        This is intentionally K-based, not clock-time-based.
        """
        result: dict[str, dict[str, Any]] = {}

        records = list(getattr(self.memory_manager, "records", []) or [])
        total_records = len(records)

        for idx, record in enumerate(records):
            record_id = str(getattr(record, "record_id", "") or "").strip()
            if not record_id:
                continue

            if hasattr(record, "to_full_dict"):
                data = record.to_full_dict()
            elif hasattr(record, "to_index_dict"):
                data = record.to_index_dict()
            else:
                data = {
                    "record_id": record_id,
                    "tag": getattr(record, "tag", ""),
                    "retrieval_source_mode": getattr(record, "retrieval_source_mode", "QA"),
                }

            data["episode_index"] = idx
            data["episode_distance_k"] = max(0, total_records - 1 - idx)
            data["episode_count_in_active_file"] = total_records

            result[record_id] = data

        return result

    def _parent_scores_to_episodic_candidates(
        self,
        parent_scores: list[dict[str, Any]],
        active_file_id: str,
    ) -> list[dict[str, Any]]:
        """
        Convert ranked parent scores into episodic candidates with Q/A body.
        """
        episodic_cfg = self.config.get("episodic_memory", {}) or {}
        if episodic_cfg.get("enabled", True) is False:
            return []

        max_total_records = int(episodic_cfg.get("max_total_records", 3))
        selected_scores = parent_scores[:max_total_records]

        live_by_id = self._live_records_by_id()
        candidates: list[dict[str, Any]] = []

        for parent in selected_scores:
            record_id = str(parent.get("record_id", "")).strip()
            candidate = dict(parent)

            live_record = live_by_id.get(record_id)
            if live_record is not None:
                candidate.update(self._record_to_candidate(live_record, active_file_id))
            else:
                # Fallback to SQLite/.ragmem if the record is not in live RAM.
                indexed = self.index_lookup.get_records_by_ids(active_file_id, [record_id])
                if indexed:
                    candidate.update(indexed[0])

            candidates.append(candidate)

        candidates = self._enrich_candidates_from_live_records(candidates)

        return candidates

    def _merge_episodic_candidates(
        self,
        semantic_episodic: list[dict[str, Any]],
        gold_candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Merge Gold and semantic episodic candidates without duplicate record_ids.

        Gold candidates remain a priority/bypass path and are inserted before
        normal Green semantic episodic candidates.
        """
        episodic_cfg = self.config.get("episodic_memory", {}) or {}
        max_total_records = int(episodic_cfg.get("max_total_records", 3))

        result: list[dict[str, Any]] = []
        seen: set[str] = set()

        for source_name, candidates in (
            ("gold", gold_candidates),
            ("semantic", semantic_episodic),
        ):
            for candidate in candidates:
                record_id = str(candidate.get("record_id", "")).strip()
                if not record_id or record_id in seen:
                    continue

                merged = dict(candidate)
                merged["episodic_source"] = source_name
                result.append(merged)
                seen.add(record_id)

                if len(result) >= max_total_records:
                    return result

        return result

    def _enrich_candidates_from_live_records(
        self,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Overlay live MemoryRecord body/metadata onto candidate dicts when possible.
        """
        live_by_id = self._live_records_by_id()
        metadata_by_record = self._metadata_by_live_record()

        enriched: list[dict[str, Any]] = []

        for candidate in candidates:
            record_id = str(candidate.get("record_id", "")).strip()
            live_record = live_by_id.get(record_id)

            if live_record is not None:
                enriched_candidate = dict(candidate)
                enriched_candidate.update(
                    self._record_to_candidate(
                        live_record,
                        file_id=str(candidate.get("file_id", getattr(self.memory_manager, "file_id", ""))),
                    )
                )
                enriched_candidate.update(metadata_by_record.get(record_id, {}))
                enriched.append(enriched_candidate)
            else:
                enriched.append(candidate)

        return enriched

    def _record_to_candidate(
        self,
        record: Any,
        file_id: str,
    ) -> dict[str, Any]:
        """
        Convert a live MemoryRecord object into a candidate dictionary.
        """
        if hasattr(record, "to_full_dict"):
            data = record.to_full_dict()
        elif hasattr(record, "to_index_dict"):
            data = record.to_index_dict()
            data["input_text"] = getattr(record, "input_text", "")
            data["output_text"] = getattr(record, "output_text", "")
        else:
            data = {
                "record_id": getattr(record, "record_id", ""),
                "input_text": getattr(record, "input_text", ""),
                "output_text": getattr(record, "output_text", ""),
                "tag": getattr(record, "tag", ""),
                "retrieval_source_mode": getattr(record, "retrieval_source_mode", "QA"),
                "direct_recall_key": getattr(record, "direct_recall_key", ""),
            }

        data["file_id"] = file_id
        data["filename_ragmem"] = getattr(self.memory_manager, "filename_ragmem", "")
        data["filename_meta"] = getattr(self.memory_manager, "filename_meta", "")
        data["memory_title"] = getattr(self.memory_manager, "title", "")

        return data

    def _live_records_by_id(self) -> dict[str, Any]:
        result: dict[str, Any] = {}

        for record in getattr(self.memory_manager, "records", []) or []:
            record_id = str(getattr(record, "record_id", "") or "").strip()
            if record_id:
                result[record_id] = record

        return result

    def _find_latest_active_brief_info(self) -> dict[str, Any]:
        """
        Find latest non-Black ActiveRetrievalBrief in live memory records.
        """
        records = list(getattr(self.memory_manager, "records", []) or [])

        for record in reversed(records):
            tag = str(getattr(record, "tag", "") or "").strip()
            if tag == "Black":
                continue

            active_brief = str(getattr(record, "active_retrieval_brief", "") or "").strip()
            if not active_brief:
                continue

            return {
                "record_id": str(getattr(record, "record_id", "") or ""),
                "active_retrieval_brief_title": str(
                    getattr(record, "active_retrieval_brief_title", "") or ""
                ).strip(),
                "active_retrieval_brief": active_brief,
                "active_retrieval_brief_contributor_ids": list(
                    getattr(record, "active_retrieval_brief_contributor_ids", []) or []
                ),
            }

        return {
            "record_id": "",
            "active_retrieval_brief_title": "",
            "active_retrieval_brief": "",
            "active_retrieval_brief_contributor_ids": [],
        }

    def _extract_direct_recall_key(
        self,
        sp: Any,
    ) -> str:
        """
        Extract an optional Direct Recall Key from SuperPrompt.

        Current GUI does not yet require a separate direct-recall query field.
        This keeps the hook ready without forcing new UI behavior.
        """
        extras = getattr(sp, "extras", {}) or {}
        body = getattr(sp, "body", {}) or {}

        for source in (extras, body):
            for key in ("direct_recall_key", "memory_direct_recall_key"):
                value = str(source.get(key, "") or "").strip()
                if value:
                    return value

        return ""

    def _estimate_token_budget(
        self,
        pack: MemoryContextPack,
    ) -> dict[str, Any]:
        """
        Rough token estimate for diagnostics.

        Exact final answer trimming belongs to later stages.
        """
        data = pack.to_dict()
        text = json.dumps(data, ensure_ascii=False, default=str)

        estimated_tokens = max(1, len(text) // 4)

        return {
            "estimated_raw_memory_tokens": estimated_tokens,
            "method": "len(json)//4 rough estimate",
            "limits": {
                "working_memory": self.config.get("working_memory", {}),
                "episodic_memory": self.config.get("episodic_memory", {}),
                "direct_recall": self.config.get("direct_recall", {}),
                "semantic_memory_chunks": self.config.get("semantic_memory_chunks", {}),
                "memory_merge_synthesizer": self.runtime_config.get("memory_merge_synthesizer", {}),
            },
        }

    def _write_empty_pack(
        self,
        sp: Any,
        reason: str,
    ) -> Any:
        pack = MemoryContextPack()
        pack.set_selection_diagnostics({"empty_reason": reason})
        self._write_to_superprompt(
            sp=sp,
            pack=pack,
            active_brief_info=self._find_latest_active_brief_info(),
        )
        return sp

    def _log_developer_diagnostics(
        self,
        query_text: str,
        active_file_id: str,
        semantic_result: dict[str, Any],
        index_candidates: dict[str, Any],
        pack: MemoryContextPack,
    ) -> None:
        """
        Write a complete retrieval snapshot for later manual analysis.
        """
        payload = {
            "query_text": query_text,
            "active_file_id": active_file_id,
            "memory_manager": {
                "file_id": getattr(self.memory_manager, "file_id", ""),
                "title": getattr(self.memory_manager, "title", ""),
                "filename_ragmem": getattr(self.memory_manager, "filename_ragmem", ""),
                "filename_meta": getattr(self.memory_manager, "filename_meta", ""),
                "record_count": len(getattr(self.memory_manager, "records", []) or []),
            },
            "semantic_result": semantic_result,
            "index_candidates": index_candidates,
            "memory_context_pack": pack.to_dict(),
            "scoring_policy": self.scorer.describe_policy(),
        }

        logger_dev(
            "FULL MEMORY RETRIEVAL DIAGNOSTIC SNAPSHOT\n"
            + json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            "DEBUG",
            "CONFIDENTIAL",
        )
```

### ~\ragstream\retrieval\retriever_splade.py
```python
# retriever_splade.py
# -*- coding: utf-8 -*-
"""
retriever_splade.py

Purpose:
    SPLADE-based retrieval backend extracted out of retriever.py.

Scope of this file:
    - Receive neutral retrieval inputs only:
        * project_name
        * query_pieces
        * top_k
        * optional candidate_ids
    - Open the active project's SPLADE document store.
    - Compare stored sparse chunk representations against all query-piece
      sparse representations.
    - Aggregate per-chunk similarities with p-norm averaging.
    - Return ranked retrieval rows to the top-level Retriever stage.

Important design rule:
    - This class does NOT know SuperPrompt.
    - This class does NOT hydrate chunk text from doc_raw.
    - This class does NOT write anything back into the pipeline state.
    - It only performs the SPLADE-based ranking backend.

Design goal:
    Keep the same programming culture and return contract as RetrieverEmb
    wherever possible.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from ragstream.ingestion.splade_embedder import SpladeEmbedder
from ragstream.ingestion.vector_store_splade import VectorStoreSplade

# Ranked row returned to Retriever:
# (chunk_id, retrieval_score, metadata)
RankedRow = Tuple[str, float, Dict[str, Any]]

# Fallback number of chunks to keep if the caller gives no valid top-k.
DEFAULT_TOP_K = 100

# Agreed retrieval aggregation constant:
# p-value for p-norm averaging across query pieces.
DEFAULT_P_NORM = 10


class RetrieverSplade:
    """
    SPLADE-based retrieval backend.

    Design:
    - Receive neutral retrieval inputs only.
    - Perform sparse retrieval ranking.
    - Return ranked rows to the top-level Retriever.
    """

    def __init__(self, *, splade_root: str, splade_embedder: SpladeEmbedder) -> None:
        """
        Initialize the SPLADE retrieval backend.

        Args:
            splade_root:
                Absolute path to the splade_db root folder.
            splade_embedder:
                Shared SpladeEmbedder instance used to encode the query pieces.
        """
        self.splade_root = Path(splade_root).resolve()
        self.splade_embedder = splade_embedder

    def run(
        self,
        *,
        project_name: str,
        query_pieces: List[str],
        top_k: int,
        candidate_ids: List[str] | None = None,
    ) -> List[RankedRow]:
        """
        Execute the SPLADE-based retrieval backend.

        Args:
            project_name:
                Active project name selected in the GUI.
            query_pieces:
                Overlapping retrieval query pieces prepared by the top-level Retriever.
            top_k:
                Number of rows to keep after ranking when running in global-search mode.
            candidate_ids:
                Optional fixed candidate set. When provided, SPLADE scores exactly
                these IDs and does not perform its own independent top-k search.

        Returns:
            Ranked retrieval rows in this format:
                [
                    (chunk_id, retrieval_score, metadata),
                    ...
                ]

        Error-handling rule:
        - Local validation belongs here, at the lower level.
        - The top-level Retriever.run(...) stays visually simple.
        """
        project_name = (project_name or "").strip()
        if not project_name:
            raise ValueError("RetrieverSplade.run: project_name must not be empty")

        if not self.splade_root.exists():
            raise FileNotFoundError(
                f"RetrieverSplade.run: splade_root does not exist: {self.splade_root}"
            )

        project_db_dir = self.splade_root / project_name
        if not project_db_dir.exists():
            raise FileNotFoundError(
                f"RetrieverSplade.run: active project SPLADE DB does not exist: {project_db_dir}"
            )

        if not query_pieces:
            return []

        k = int(top_k) if int(top_k) > 0 else DEFAULT_TOP_K

        store = VectorStoreSplade(persist_dir=str(project_db_dir))

        doc_vectors: Dict[str, Dict[str, float]] = store.index
        meta_store: Dict[str, Dict[str, Any]] = getattr(store, "_meta_store", {})

        if len(doc_vectors) == 0:
            return []

        query_vectors = self.splade_embedder.embed_queries(query_pieces)
        if len(query_vectors) == 0:
            return []

        target_ids: List[str]
        use_fixed_candidates = candidate_ids is not None

        if use_fixed_candidates:
            seen: set[str] = set()
            target_ids = []

            for chunk_id in candidate_ids or []:
                cid = str(chunk_id).strip()
                if not cid:
                    continue
                if cid in seen:
                    continue
                seen.add(cid)
                target_ids.append(cid)

            if len(target_ids) == 0:
                return []

            missing_ids = [cid for cid in target_ids if cid not in doc_vectors]
            if missing_ids:
                preview = ", ".join(missing_ids[:10])
                suffix = " ..." if len(missing_ids) > 10 else ""
                raise RuntimeError(
                    "RetrieverSplade.run: candidate_ids are missing in the active SPLADE store. "
                    f"Missing {len(missing_ids)} id(s): {preview}{suffix}"
                )
        else:
            target_ids = list(doc_vectors.keys())

        rows: List[RankedRow] = []

        p = DEFAULT_P_NORM

        for chunk_id in target_ids:
            doc_vec = doc_vectors[chunk_id]
            per_piece_scores: List[float] = []

            for query_vec in query_vectors:
                sim = self._dot_sparse(doc_vec, query_vec)
                per_piece_scores.append(float(sim))

            if len(per_piece_scores) == 0:
                aggregated_score = 0.0
            else:
                sims_pos = [max(0.0, float(s)) for s in per_piece_scores]
                aggregated_score = (
                    sum(pow(s, p) for s in sims_pos) / float(len(sims_pos))
                ) ** (1.0 / p)

            meta = meta_store.get(chunk_id, {})
            rows.append(
                (
                    str(chunk_id),
                    float(aggregated_score),
                    dict(meta),
                )
            )

        # Deterministic sort:
        # 1) higher score first
        # 2) stable fallback by chunk_id
        rows.sort(key=lambda row: (-row[1], row[0]))

        if use_fixed_candidates:
            return rows

        return rows[: min(k, len(rows))]

    @staticmethod
    def _dot_sparse(left: Dict[str, float], right: Dict[str, float]) -> float:
        """
        Dot product over sparse dicts.

        Iterate over the smaller dict for efficiency.
        """
        if len(left) > len(right):
            left, right = right, left

        score = 0.0
        for key, value in left.items():
            score += float(value) * float(right.get(key, 0.0))
        return score
```

### ~\ragstream\retrieval\rrf_merger.py
```python
# rrf_merger.py
# -*- coding: utf-8 -*-
"""
rrf_merger.py

Purpose:
    Deterministic weighted Reciprocal Rank Fusion (RRF) helper.

Role:
    - Merge two ranked result lists in a neutral way.
    - Produce one fused ranked list.
    - Preserve metadata and attach neutral rank/score fields.

Important design rule:
    - This module is purely deterministic.
    - It does not know SuperPrompt.
    - It does not know dense / SPLADE semantics.
    - It does not hydrate chunk text.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

# Ranked row contract shared with retriever.py / retriever_emb.py / retriever_splade.py
RankedRow = Tuple[str, float, Dict[str, Any]]

# Common practical default for RRF.
DEFAULT_RRF_K = 60


def rrf_merge(
    rows_a: List[RankedRow],
    rows_b: List[RankedRow],
    *,
    top_k: int | None = None,
    rrf_k: int = DEFAULT_RRF_K,
    weight_a: float = 1.0,
    weight_b: float = 1.0,
) -> List[RankedRow]:
    """
    Merge two ranked lists with weighted Reciprocal Rank Fusion.

    Args:
        rows_a:
            First ranked row list.
        rows_b:
            Second ranked row list.
        top_k:
            Optional final cutoff.
        rrf_k:
            RRF constant. Larger values flatten rank differences more.
        weight_a:
            Weight for the first ranked list.
        weight_b:
            Weight for the second ranked list.

    Returns:
        One fused ranked row list:
            [
                (chunk_id, fused_rrf_score, metadata_with_neutral_scores),
                ...
            ]
    """
    by_id: Dict[str, Dict[str, Any]] = {}

    for rank, (chunk_id, score, meta) in enumerate(rows_a, start=1):
        row = by_id.setdefault(str(chunk_id), {})
        row["meta"] = _merge_meta(row.get("meta"), meta)
        row["rank_a"] = int(rank)
        row["score_a"] = float(score)

    for rank, (chunk_id, score, meta) in enumerate(rows_b, start=1):
        row = by_id.setdefault(str(chunk_id), {})
        row["meta"] = _merge_meta(row.get("meta"), meta)
        row["rank_b"] = int(rank)
        row["score_b"] = float(score)

    fused_rows: List[RankedRow] = []

    for chunk_id, row in by_id.items():
        rank_a = row.get("rank_a")
        rank_b = row.get("rank_b")

        fused_score = 0.0
        if rank_a is not None:
            fused_score += float(weight_a) / float(rrf_k + int(rank_a))
        if rank_b is not None:
            fused_score += float(weight_b) / float(rrf_k + int(rank_b))

        meta = dict(row.get("meta") or {})

        if row.get("score_a") is not None:
            meta["score_a"] = float(row["score_a"])
        if row.get("score_b") is not None:
            meta["score_b"] = float(row["score_b"])

        if rank_a is not None:
            meta["rank_a"] = int(rank_a)
        if rank_b is not None:
            meta["rank_b"] = int(rank_b)

        meta["rrf_score"] = float(fused_score)

        fused_rows.append((str(chunk_id), float(fused_score), meta))

    # Deterministic sort:
    # 1) higher fused score first
    # 2) stable fallback by chunk_id
    fused_rows.sort(key=lambda row: (-row[1], row[0]))

    if top_k is None:
        return fused_rows

    k = int(top_k)
    if k <= 0:
        return fused_rows

    return fused_rows[: min(k, len(fused_rows))]


def _merge_meta(
    base_meta: Dict[str, Any] | None,
    new_meta: Dict[str, Any] | None,
) -> Dict[str, Any]:
    """
    Merge metadata conservatively.

    Rule:
    - keep existing keys
    - add missing keys from the new metadata
    - do not silently overwrite existing values
    """
    merged = dict(base_meta or {})
    for key, value in dict(new_meta or {}).items():
        if key not in merged:
            merged[key] = value
    return merged
```

### ~\ragstream\retrieval\smart_query_splitter.py
```python
# smart_query_splitter.py
# -*- coding: utf-8 -*-
"""
smart_query_splitter.py

Purpose:
    External query-splitting support functions for Retrieval.

Stage-1 refactor scope:
    - Keep the current linear overlapping query-splitting logic outside retriever.py.
    - Preserve the current behavior exactly as closely as possible.

Important note:
    The current splitting logic is still the existing deterministic linear
    windowing logic. Later, this file can be upgraded internally to a smarter
    query-splitting implementation (for example wtpsplit) without changing the
    top-level Retriever stage contract.
"""

from __future__ import annotations

from typing import List

from ragstream.ingestion.chunker import Chunker


def split_query_into_pieces(
    *,
    query_text: str,
    chunker: Chunker,
    chunk_size: int,
    overlap: int,
) -> List[str]:
    """
    Split the retrieval query into overlapping query pieces.

    Current Stage-1 behavior:
    - Reuse the same deterministic chunking idea as ingestion.
    - Preserve the current retrieval splitter behavior.
    - Return only the text pieces.

    Later upgrade path:
    - This function body can be replaced by a smarter splitter implementation
      without changing the top-level Retriever stage contract.
    """
    query_text = (query_text or "").strip()
    if not query_text:
        return []

    if chunker is None:
        raise ValueError("split_query_into_pieces: 'chunker' must not be None")

    if chunk_size <= 0:
        raise ValueError("split_query_into_pieces: chunk_size must be positive")

    if overlap < 0:
        raise ValueError("split_query_into_pieces: overlap must be non-negative")

    if overlap >= chunk_size:
        raise ValueError(
            "split_query_into_pieces: overlap must be smaller than chunk_size"
        )

    pieces = chunker.split(
        file_path="__prompt__",
        text=query_text,
        chunk_size=chunk_size,
        overlap=overlap,
    )

    return [chunk_text for _fp, chunk_text in pieces if (chunk_text or "").strip()]
```


## /home/rusbeh_ab/project/RAGstream/ragstream/memory

### ~\ragstream\memory\memory_actions.py
```python
# ragstream/memory/memory_actions.py
# -*- coding: utf-8 -*-
"""
Memory actions
==============
Reusable workflow functions for memory capture.

GUI buttons, future LLM calls, Copilot calls, or tool results should call
these functions instead of embedding memory logic directly in UI callbacks.
"""

from __future__ import annotations

from typing import Any

from ragstream.memory.memory_manager import MemoryManager
from ragstream.textforge.RagLog import LogALL as logger


def capture_memory_pair(
    memory_manager: MemoryManager,
    input_text: str,
    output_text: str,
    source: str,
    active_project_name: str | None = None,
    embedded_files_snapshot: list[str] | None = None,
    parent_id: str | None = None,
    user_keywords: list[str] | None = None,
    gui_records_state: list[dict[str, Any]] | None = None,
    memory_ingestion_manager: Any | None = None,
) -> dict[str, Any]:
    clean_input = (input_text or "").strip()
    clean_output = (output_text or "").strip()

    if not clean_input:
        return {
            "success": False,
            "message": "Prompt is empty. No memory record was created.",
            "record": None,
        }

    if not clean_output:
        return {
            "success": False,
            "message": "Manual memory response is empty. No memory record was created.",
            "record": None,
        }

    memory_manager.sync_gui_edits(gui_records_state or [])

    record = memory_manager.capture_pair(
        input_text=clean_input,
        output_text=clean_output,
        source=source,
        parent_id=parent_id,
        user_keywords=user_keywords,
        active_project_name=active_project_name,
        embedded_files_snapshot=embedded_files_snapshot or [],
    )

    logger(
        f"Memory record saved: {record.record_id}",
        "INFO",
        "PUBLIC",
    )

    logger(
        (
            "MemoryRecord captured: "
            f"record={record.record_id[:8]} | "
            f"file={memory_manager.filename_ragmem} | "
            f"tag={record.tag}"
        ),
        "INFO",
        "INTERNAL",
    )

    if memory_ingestion_manager is not None:
        try:
            memory_ingestion_manager.ingest_record_async(record.record_id)
        except Exception as e:
            logger(
                f"MemoryRecord was saved, but vector ingestion could not be scheduled: {e}",
                "WARN",
                "PUBLIC",
            )

    return {
        "success": True,
        "message": f"Memory record saved: {record.record_id}",
        "record": record,
        "record_id": record.record_id,
        "file_id": memory_manager.file_id,
        "filename_ragmem": memory_manager.filename_ragmem,
    }
```

### ~\ragstream\memory\memory_manager.py
```python
# ragstream/memory/memory_manager.py
# -*- coding: utf-8 -*-
"""
MemoryManager
=============
Owns one active memory history file, its MemoryRecords, MetaInfo,
.ragmem persistence, .ragmeta.json persistence, and SQLite indexing.

Authority split:
- .ragmem is append-only and stores stable memory body fields only.
- .ragmeta.json stores current editable/readable metadata.
- SQLite mirrors .ragmeta.json for fast lookup/indexing.

ActiveBrief pending-topic buffer:
- RAM-only.
- Not written to .ragmem, .ragmeta.json, or SQLite.
- Used only to detect whether consecutive skipped Q/A pairs form a new topic.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ragstream.memory.memory_record import (
    MemoryRecord,
    RECORD_END,
    RECORD_START,
)
from ragstream.textforge.RagLog import LogDeveloper as _logger_dev

DEV_LOG_ENABLED = False

def logger_dev(*args, **kwargs):
    if DEV_LOG_ENABLED:
        return _logger_dev(*args, **kwargs)
    return None

def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _filename_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H-%M")


def _safe_title(title: str) -> str:
    value = (title or "").strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-._")
    return value or "Untitled"


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        item = str(value).strip()
        if not item:
            continue

        key = item.lower()
        if key in seen:
            continue

        result.append(item)
        seen.add(key)

    return result


def _clean_retrieval_source_mode(value: str | None) -> str | None:
    if value is None:
        return None

    mode = str(value or "").strip().upper()
    if mode in {"QA", "Q", "A"}:
        return mode

    return "QA"


def _clean_direct_recall_key(value: str | None) -> str | None:
    if value is None:
        return None

    return str(value or "").strip()


class MemoryManager:
    def __init__(
        self,
        memory_root: Path,
        sqlite_path: Path,
        title: str = "",
    ) -> None:
        self.file_id: str = uuid.uuid4().hex
        self.title: str = ""
        self.filename_ragmem: str = ""
        self.filename_meta: str = ""

        self.memory_root: Path = Path(memory_root)
        self.sqlite_path: Path = Path(sqlite_path)

        self.records: list[MemoryRecord] = []
        self.metainfo: dict[str, Any] = {}

        # RAM-only buffer for topic-shift detection.
        # If Q/A is skipped as unrelated to the current ActiveBrief,
        # its reduced text and vectors are kept here.
        # The next skipped Q/A is compared to this buffer.
        self.pending_activebrief_topic_buffer: dict[str, Any] = {}

        self.tag_catalog: list[str] = ["Gold", "Green", "Black"]
        self.b_file_created: bool = False

        self.memory_root.mkdir(parents=True, exist_ok=True)
        self.files_root.mkdir(parents=True, exist_ok=True)
        self._init_sqlite()

        if title.strip():
            self.start_new_history(title)

    @property
    def files_root(self) -> Path:
        return self.memory_root / "files"

    @property
    def ragmem_path(self) -> Path:
        return self.files_root / self.filename_ragmem

    @property
    def meta_path(self) -> Path:
        return self.files_root / self.filename_meta

    def start_new_history(self, title: str) -> None:
        clean_title = (title or "").strip()
        if not clean_title:
            raise ValueError("Memory title must not be empty.")

        self.file_id = uuid.uuid4().hex
        self.title = clean_title
        self.records = []
        self.metainfo = {}
        self.pending_activebrief_topic_buffer = {}
        self.b_file_created = False

        stem = f"{_filename_timestamp()}-{_safe_title(clean_title)}"
        filename_ragmem = f"{stem}.ragmem"
        filename_meta = f"{stem}.ragmeta.json"

        if (self.files_root / filename_ragmem).exists():
            stem = f"{stem}-{self.file_id[:8]}"
            filename_ragmem = f"{stem}.ragmem"
            filename_meta = f"{stem}.ragmeta.json"

        self.filename_ragmem = filename_ragmem
        self.filename_meta = filename_meta

    def load_history(self, file_id: str) -> None:
        file_row = self._lookup_file(file_id)
        if not file_row:
            raise ValueError(f"Memory history not found: {file_id}")

        self.file_id = file_row["file_id"]
        self.title = file_row["title"]
        self.filename_ragmem = file_row["filename_ragmem"]
        self.filename_meta = file_row["filename_meta"]

        self.records = self._read_ragmem_records(self.ragmem_path)
        self.pending_activebrief_topic_buffer = {}
        self.b_file_created = self.ragmem_path.exists()

        if self.meta_path.exists():
            with self.meta_path.open("r", encoding="utf-8") as f:
                loaded_meta = json.load(f)
            self.metainfo = loaded_meta if isinstance(loaded_meta, dict) else {}
            self._apply_metainfo_overlay_to_records()
        else:
            self.save_metainfo()

        self.refresh_sqlite_index()

    def list_histories(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT file_id, title, filename_ragmem, filename_meta,
                       created_at_utc, updated_at_utc, record_count
                FROM memory_files
                ORDER BY updated_at_utc DESC
                """
            ).fetchall()

        return [dict(row) for row in rows]

    def capture_pair(
        self,
        input_text: str,
        output_text: str,
        source: str,
        parent_id: str | None = None,
        user_keywords: list[str] | None = None,
        active_project_name: str | None = None,
        embedded_files_snapshot: list[str] | None = None,
    ) -> MemoryRecord:
        record = MemoryRecord(
            input_text=input_text,
            output_text=output_text,
            source=source,
            parent_id=parent_id,
            tag="Green",
            user_keywords=user_keywords,
            active_project_name=active_project_name,
            embedded_files_snapshot=embedded_files_snapshot,
            retrieval_source_mode="QA",
            direct_recall_key="",
        )

        if not self.title.strip():
            auto_title = self._build_auto_history_title(
                record=record,
                active_project_name=active_project_name,
            )
            self.start_new_history(auto_title)

        self._update_active_retrieval_brief(record)

        self.records.append(record)
        self._append_record_to_ragmem(record)
        self.save_metainfo()
        self.refresh_sqlite_index()

        return record

    def sync_gui_edits(
        self,
        gui_records_state: list[dict[str, Any]],
    ) -> None:
        if not gui_records_state:
            return

        records_by_id = {record.record_id: record for record in self.records}
        changed = False

        for item in gui_records_state:
            record_id = str(item.get("record_id", "")).strip()
            if not record_id or record_id not in records_by_id:
                continue

            record = records_by_id[record_id]

            tag = item.get("tag")
            if tag is not None:
                tag = str(tag).strip()
                if tag not in self.tag_catalog:
                    tag = None

            user_keywords = item.get("user_keywords")
            if user_keywords is not None and not isinstance(user_keywords, list):
                user_keywords = []

            retrieval_source_mode = _clean_retrieval_source_mode(item.get("retrieval_source_mode"))
            direct_recall_key = _clean_direct_recall_key(item.get("direct_recall_key"))

            before = record.to_index_dict()
            record.update_editable_metadata(
                tag=tag,
                user_keywords=user_keywords,
                retrieval_source_mode=retrieval_source_mode,
                direct_recall_key=direct_recall_key,
            )
            after = record.to_index_dict()

            if before != after:
                changed = True

        if changed:
            self.save_metainfo()
            self.refresh_sqlite_index()

    def save_metainfo(self) -> None:
        self.metainfo = self._build_metainfo()

        if not self.filename_meta:
            return

        self.files_root.mkdir(parents=True, exist_ok=True)
        with self.meta_path.open("w", encoding="utf-8") as f:
            json.dump(self.metainfo, f, ensure_ascii=False, indent=2)

    def refresh_sqlite_index(self) -> None:
        self._init_sqlite()

        if not self.file_id or not self.filename_ragmem:
            return

        metainfo = self._build_metainfo()
        now = _utc_now()

        created_at_utc = metainfo.get("created_at_utc") or now
        updated_at_utc = metainfo.get("updated_at_utc") or now
        record_count = int(metainfo.get("record_count", 0))

        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute(
                """
                INSERT INTO memory_files (
                    file_id, title, filename_ragmem, filename_meta,
                    created_at_utc, updated_at_utc, record_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_id) DO UPDATE SET
                    title = excluded.title,
                    filename_ragmem = excluded.filename_ragmem,
                    filename_meta = excluded.filename_meta,
                    created_at_utc = excluded.created_at_utc,
                    updated_at_utc = excluded.updated_at_utc,
                    record_count = excluded.record_count
                """,
                (
                    self.file_id,
                    self.title,
                    self.filename_ragmem,
                    self.filename_meta,
                    created_at_utc,
                    updated_at_utc,
                    record_count,
                ),
            )

            for record in self.records:
                index_data = record.to_index_dict()

                conn.execute(
                    """
                    INSERT INTO memory_records (
                        file_id, record_id, parent_id, created_at_utc,
                        source, tag, retrieval_source_mode, direct_recall_key,
                        auto_keywords_json, user_keywords_json,
                        active_project_name, embedded_files_snapshot_json,
                        input_hash, output_hash
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(file_id, record_id) DO UPDATE SET
                        parent_id = excluded.parent_id,
                        created_at_utc = excluded.created_at_utc,
                        source = excluded.source,
                        tag = excluded.tag,
                        retrieval_source_mode = excluded.retrieval_source_mode,
                        direct_recall_key = excluded.direct_recall_key,
                        auto_keywords_json = excluded.auto_keywords_json,
                        user_keywords_json = excluded.user_keywords_json,
                        active_project_name = excluded.active_project_name,
                        embedded_files_snapshot_json = excluded.embedded_files_snapshot_json,
                        input_hash = excluded.input_hash,
                        output_hash = excluded.output_hash
                    """,
                    (
                        self.file_id,
                        index_data["record_id"],
                        index_data["parent_id"],
                        index_data["created_at_utc"],
                        index_data["source"],
                        index_data["tag"],
                        index_data["retrieval_source_mode"],
                        index_data["direct_recall_key"],
                        json.dumps(index_data["auto_keywords"], ensure_ascii=False),
                        json.dumps(index_data["user_keywords"], ensure_ascii=False),
                        index_data["active_project_name"],
                        json.dumps(index_data["embedded_files_snapshot"], ensure_ascii=False),
                        index_data["input_hash"],
                        index_data["output_hash"],
                    ),
                )

            self._delete_sqlite_rows_not_in_memory(conn)
            conn.commit()

    def _build_metainfo(self) -> dict[str, Any]:
        record_ids = [record.record_id for record in self.records]
        parent_ids = _unique([record.parent_id for record in self.records if record.parent_id])

        tag_summary: dict[str, int] = {}
        auto_keywords: list[str] = []
        user_keywords: list[str] = []

        for record in self.records:
            tag_summary[record.tag] = tag_summary.get(record.tag, 0) + 1
            auto_keywords.extend(record.auto_keywords)
            user_keywords.extend(record.user_keywords)

        created_at_utc = self.records[0].created_at_utc if self.records else ""
        updated_at_utc = _utc_now() if self.records else ""

        return {
            "file_id": self.file_id,
            "title": self.title,
            "filename_ragmem": self.filename_ragmem,
            "filename_meta": self.filename_meta,
            "created_at_utc": created_at_utc,
            "updated_at_utc": updated_at_utc,
            "record_count": len(self.records),
            "record_ids": record_ids,
            "parent_ids": parent_ids,
            "tag_summary": tag_summary,
            "auto_keywords": _unique(auto_keywords),
            "user_keywords": _unique(user_keywords),
            "records": [record.to_index_dict() for record in self.records],
        }

    def close(self) -> None:
        self.save_metainfo()
        self.refresh_sqlite_index()

    def _update_active_retrieval_brief(self, record: MemoryRecord) -> None:
        """
        Build the ActiveRetrievalBrief for the new MemoryRecord.

        This happens before the record is first written to .ragmem so that
        active_retrieval_brief remains part of the stable body block.

        The pending-topic buffer is updated here too, because it belongs to
        the active memory history, not to Streamlit and not to the builder.
        """
        try:
            from ragstream.memory.compression.memory_active_retrieval_brief import (
                MemoryActiveRetrievalBriefBuilder,
            )

            builder = MemoryActiveRetrievalBriefBuilder()
            result = builder.build_for_record(
                record=record,
                previous_records=list(self.records),
                pending_topic_buffer=dict(self.pending_activebrief_topic_buffer or {}),
            )

            active_brief_title = str(result.get("active_retrieval_brief_title", "") or "").strip()
            active_brief = str(result.get("active_retrieval_brief", "") or "").strip()
            contributor_ids = list(result.get("active_retrieval_brief_contributor_ids") or [])

            record.update_active_retrieval_brief(
                active_retrieval_brief=active_brief,
                contributor_ids=contributor_ids,
                active_retrieval_brief_title=active_brief_title,
            )

            new_buffer = result.get("pending_activebrief_topic_buffer", {})
            self.pending_activebrief_topic_buffer = new_buffer if isinstance(new_buffer, dict) else {}

            logger_dev(
                "MemoryManager ActiveBrief update result\n"
                + json.dumps(
                    {
                        "record_id": record.record_id,
                        "activebrief_llm_skipped": bool(result.get("activebrief_llm_skipped", False)),
                        "activebrief_gate_route": str(result.get("activebrief_gate_route", "") or ""),
                        "active_retrieval_brief_title": active_brief_title,
                        "active_retrieval_brief": active_brief,
                        "active_retrieval_brief_contributor_ids": contributor_ids,
                        "pending_activebrief_topic_buffer": self._pending_buffer_log_view(
                            self.pending_activebrief_topic_buffer
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                "DEBUG",
                "CONFIDENTIAL",
            )

        except Exception as e:
            logger_dev(
                "ActiveRetrievalBrief generation failed\n"
                + json.dumps(
                    {
                        "record_id": record.record_id,
                        "error": str(e),
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                "ERROR",
                "CONFIDENTIAL",
            )

    def _append_record_to_ragmem(self, record: MemoryRecord) -> None:
        if not self.filename_ragmem:
            raise ValueError("Memory filename is not initialized.")

        self.files_root.mkdir(parents=True, exist_ok=True)

        with self.ragmem_path.open("a", encoding="utf-8") as f:
            f.write(record.to_ragmem_block())
            f.write("\n")

        self.b_file_created = True

    def _read_ragmem_records(self, path: Path) -> list[MemoryRecord]:
        if not path.exists():
            return []

        text = path.read_text(encoding="utf-8")
        pattern = re.compile(
            rf"{re.escape(RECORD_START)}\n(.*?)\n{re.escape(RECORD_END)}",
            re.DOTALL,
        )

        records: list[MemoryRecord] = []

        for match in pattern.finditer(text):
            raw_block = match.group(1)
            try:
                data = json.loads(raw_block)
                if isinstance(data, dict):
                    records.append(MemoryRecord.from_dict(data))
            except Exception:
                continue

        return records

    def _apply_metainfo_overlay_to_records(self) -> None:
        """
        Overlay current .ragmeta.json metadata onto records loaded from .ragmem.

        .ragmem supplies the stable body.
        .ragmeta.json supplies current metadata.
        """
        meta_records = self.metainfo.get("records", [])
        if not isinstance(meta_records, list):
            return

        metadata_by_record_id: dict[str, dict[str, Any]] = {}

        for item in meta_records:
            if not isinstance(item, dict):
                continue

            record_id = str(item.get("record_id", "")).strip()
            if not record_id:
                continue

            metadata_by_record_id[record_id] = item

        for record in self.records:
            metadata = metadata_by_record_id.get(record.record_id)
            if metadata is None:
                continue

            record.update_metadata_overlay(metadata)

    def _delete_sqlite_rows_not_in_memory(self, conn: sqlite3.Connection) -> None:
        """
        Keep SQLite as a mirror of the active MemoryManager.records list.
        SQLite is not allowed to keep extra current rows for this file_id.
        """
        if not self.records:
            conn.execute(
                "DELETE FROM memory_records WHERE file_id = ?",
                (self.file_id,),
            )
            return

        record_ids = [record.record_id for record in self.records]
        placeholders = ",".join("?" for _ in record_ids)

        conn.execute(
            f"""
            DELETE FROM memory_records
            WHERE file_id = ?
              AND record_id NOT IN ({placeholders})
            """,
            [self.file_id, *record_ids],
        )

    def _lookup_file(self, file_id: str) -> dict[str, Any] | None:
        self._init_sqlite()

        with sqlite3.connect(self.sqlite_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT file_id, title, filename_ragmem, filename_meta,
                       created_at_utc, updated_at_utc, record_count
                FROM memory_files
                WHERE file_id = ?
                """,
                (file_id,),
            ).fetchone()

        return dict(row) if row else None

    def _build_auto_history_title(
        self,
        record: MemoryRecord,
        active_project_name: str | None = None,
    ) -> str:
        """
        Build the first memory history title automatically.

        The file name must stay generic and deterministic:
        YYYY-MM-DD-HH-mm-memory-record.ragmem
        """
        return "memory-record"

    @staticmethod
    def _pending_buffer_log_view(buffer: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(buffer, dict) or not buffer:
            return {}

        return {
            "record_id": str(buffer.get("record_id", "") or ""),
            "created_at_utc": str(buffer.get("created_at_utc", "") or ""),
            "question_vector_count": len(buffer.get("question_vectors", []) or []),
            "answer_vector_count": len(buffer.get("answer_vectors", []) or []),
            "vector_count": int(buffer.get("vector_count", 0) or 0),
            "has_center_vector": bool(buffer.get("center_vector", [])),
            "reduced_question_preview": str(buffer.get("reduced_question", "") or "")[:500],
            "reduced_answer_preview": str(buffer.get("reduced_answer", "") or "")[:500],
        }

    def _init_sqlite(self) -> None:
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_files (
                    file_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    filename_ragmem TEXT NOT NULL,
                    filename_meta TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    record_count INTEGER NOT NULL
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_records (
                    file_id TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    parent_id TEXT,
                    created_at_utc TEXT NOT NULL,
                    source TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    retrieval_source_mode TEXT NOT NULL DEFAULT 'QA',
                    direct_recall_key TEXT NOT NULL DEFAULT '',
                    auto_keywords_json TEXT NOT NULL,
                    user_keywords_json TEXT NOT NULL,
                    active_project_name TEXT,
                    embedded_files_snapshot_json TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    output_hash TEXT NOT NULL,
                    PRIMARY KEY (file_id, record_id)
                )
                """
            )

            self._ensure_memory_records_columns(conn)

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_records_tag
                ON memory_records(tag)
                """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_records_project
                ON memory_records(active_project_name)
                """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_records_direct_recall_key
                ON memory_records(direct_recall_key)
                """
            )

            conn.commit()

    @staticmethod
    def _ensure_memory_records_columns(conn: sqlite3.Connection) -> None:
        rows = conn.execute("PRAGMA table_info(memory_records)").fetchall()
        existing_columns = {str(row[1]) for row in rows}

        if "retrieval_source_mode" not in existing_columns:
            conn.execute(
                "ALTER TABLE memory_records "
                "ADD COLUMN retrieval_source_mode TEXT NOT NULL DEFAULT 'QA'"
            )

        if "direct_recall_key" not in existing_columns:
            conn.execute(
                "ALTER TABLE memory_records "
                "ADD COLUMN direct_recall_key TEXT NOT NULL DEFAULT ''"
            )
```

### ~\ragstream\memory\memory_merge_synthesizer.py
```python
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
            max_output_tokens=agent_prompt.max_output_tokens,
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
            f"Keep memory_context at or below about {self.target_context_tokens} tokens."
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
```

### ~\ragstream\memory\memory_record.py
```python
# ragstream/memory/memory_record.py
# -*- coding: utf-8 -*-
"""
MemoryRecord
============
One accepted input/output memory unit.

Authority split:
- .ragmem stores only the stable append-only memory body.
- .ragmeta.json stores current metadata.
- SQLite mirrors .ragmeta.json for fast lookup/indexing.

A MemoryRecord in RAM contains both:
- stable body fields
- current metadata fields

Only stable body fields are serialized into .ragmem.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from datetime import datetime, timezone
from typing import Any


RECORD_START = "----- MEMORY RECORD START -----"
RECORD_END = "----- MEMORY RECORD END -----"


RETRIEVAL_SOURCE_MODES = {"QA", "Q", "A"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _clean_list(values: list[str] | None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()

    for value in values or []:
        item = str(value).strip()
        if not item:
            continue

        key = item.lower()
        if key in seen:
            continue

        cleaned.append(item)
        seen.add(key)

    return cleaned


def _clean_retrieval_source_mode(value: str | None) -> str:
    mode = str(value or "QA").strip().upper()
    return mode if mode in RETRIEVAL_SOURCE_MODES else "QA"


def _clean_direct_recall_key(value: str | None) -> str:
    return str(value or "").strip()


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    return text if text else None


class MemoryRecord:
    def __init__(
        self,
        input_text: str,
        output_text: str,
        source: str,
        parent_id: str | None = None,
        tag: str = "Green",
        user_keywords: list[str] | None = None,
        active_project_name: str | None = None,
        embedded_files_snapshot: list[str] | None = None,
        retrieval_source_mode: str = "QA",
        direct_recall_key: str = "",
        active_retrieval_brief_title: str = "",
        active_retrieval_brief: str = "",
        active_retrieval_brief_contributor_ids: list[str] | None = None,
        *,
        record_id: str | None = None,
        created_at_utc: str | None = None,
        auto_keywords: list[str] | None = None,
        input_hash: str | None = None,
        output_hash: str | None = None,
    ) -> None:
        self.record_id: str = record_id or uuid.uuid4().hex
        self.parent_id: str | None = parent_id
        self.created_at_utc: str = created_at_utc or _utc_now()

        self.input_text: str = input_text or ""
        self.output_text: str = output_text or ""
        self.source: str = source or ""

        self.tag: str = tag or "Green"
        self.user_keywords: list[str] = _clean_list(user_keywords)
        self.retrieval_source_mode: str = _clean_retrieval_source_mode(retrieval_source_mode)
        self.direct_recall_key: str = _clean_direct_recall_key(direct_recall_key)

        self.active_project_name: str | None = active_project_name
        self.embedded_files_snapshot: list[str] = list(embedded_files_snapshot or [])

        self.active_retrieval_brief_title: str = str(active_retrieval_brief_title or "").strip()
        self.active_retrieval_brief: str = str(active_retrieval_brief or "").strip()
        self.active_retrieval_brief_contributor_ids: list[str] = _clean_list(
            active_retrieval_brief_contributor_ids
        )

        self.input_hash: str = input_hash or _sha256(self.input_text)
        self.output_hash: str = output_hash or _sha256(self.output_text)

        if auto_keywords is None:
            self.auto_keywords: list[str] = self.generate_auto_keywords()
        else:
            self.auto_keywords = _clean_list(auto_keywords)

    def generate_auto_keywords(self) -> list[str]:
        text = f"{self.input_text}\n\n{self.output_text}".strip()
        if not text:
            return []

        try:
            import yake
        except Exception:
            return []

        try:
            extractor = yake.KeywordExtractor(
                lan="en",
                n=3,
                dedupLim=0.9,
                top=5,
                features=None,
            )
            keywords = extractor.extract_keywords(text)
            return _clean_list([kw for kw, _score in keywords])
        except Exception:
            return []

    def update_editable_metadata(
        self,
        tag: str | None = None,
        user_keywords: list[str] | None = None,
        retrieval_source_mode: str | None = None,
        direct_recall_key: str | None = None,
    ) -> None:
        if tag is not None:
            clean_tag = str(tag).strip()
            if clean_tag:
                self.tag = clean_tag

        if user_keywords is not None:
            self.user_keywords = _clean_list(user_keywords)

        if retrieval_source_mode is not None:
            self.retrieval_source_mode = _clean_retrieval_source_mode(retrieval_source_mode)

        if direct_recall_key is not None:
            self.direct_recall_key = _clean_direct_recall_key(direct_recall_key)

    def update_active_retrieval_brief(
        self,
        active_retrieval_brief: str,
        contributor_ids: list[str] | None = None,
        active_retrieval_brief_title: str = "",
    ) -> None:
        self.active_retrieval_brief_title = str(active_retrieval_brief_title or "").strip()
        self.active_retrieval_brief = str(active_retrieval_brief or "").strip()
        self.active_retrieval_brief_contributor_ids = _clean_list(contributor_ids)

    def update_metadata_overlay(
        self,
        metadata: dict[str, Any],
    ) -> None:
        """
        Apply current metadata loaded from .ragmeta.json.

        This method deliberately does not modify stable .ragmem body fields:
        - record_id
        - parent_id
        - created_at_utc
        - input_text
        - output_text
        - source
        - input_hash
        - output_hash
        - active_retrieval_brief_title
        - active_retrieval_brief
        - active_retrieval_brief_contributor_ids
        """
        if not isinstance(metadata, dict):
            return

        self.update_editable_metadata(
            tag=metadata.get("tag"),
            user_keywords=list(metadata.get("user_keywords") or []),
            retrieval_source_mode=metadata.get("retrieval_source_mode"),
            direct_recall_key=metadata.get("direct_recall_key"),
        )

        if "auto_keywords" in metadata:
            self.auto_keywords = _clean_list(list(metadata.get("auto_keywords") or []))

        if "active_project_name" in metadata:
            self.active_project_name = _optional_str(metadata.get("active_project_name"))

        if "embedded_files_snapshot" in metadata:
            self.embedded_files_snapshot = list(metadata.get("embedded_files_snapshot") or [])

    def to_ragmem_dict(self) -> dict[str, Any]:
        """
        Stable append-only .ragmem body.

        Editable GUI metadata is intentionally excluded from this dictionary.
        """
        return {
            "record_id": self.record_id,
            "parent_id": self.parent_id,
            "created_at_utc": self.created_at_utc,
            "input_text": self.input_text,
            "output_text": self.output_text,
            "source": self.source,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "active_retrieval_brief_title": self.active_retrieval_brief_title,
            "active_retrieval_brief": self.active_retrieval_brief,
            "active_retrieval_brief_contributor_ids": self.active_retrieval_brief_contributor_ids,
        }

    def to_ragmem_block(self) -> str:
        body = json.dumps(self.to_ragmem_dict(), ensure_ascii=False, indent=2)
        return f"{RECORD_START}\n{body}\n{RECORD_END}\n"

    def to_index_dict(self) -> dict[str, Any]:
        """
        Current metadata/index view.

        This dictionary is used for:
        - .ragmeta.json per-record metadata
        - SQLite mirror rows

        It does not duplicate full input_text, output_text, or full ActiveBrief text.
        """
        return {
            "record_id": self.record_id,
            "parent_id": self.parent_id,
            "created_at_utc": self.created_at_utc,
            "source": self.source,
            "tag": self.tag,
            "retrieval_source_mode": self.retrieval_source_mode,
            "direct_recall_key": self.direct_recall_key,
            "auto_keywords": self.auto_keywords,
            "user_keywords": self.user_keywords,
            "active_project_name": self.active_project_name,
            "embedded_files_snapshot": self.embedded_files_snapshot,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
        }

    def to_full_dict(self) -> dict[str, Any]:
        """
        Full in-RAM diagnostic/export view.

        This is not used for .ragmem serialization.
        """
        data = self.to_ragmem_dict()
        data.update(
            {
                "tag": self.tag,
                "retrieval_source_mode": self.retrieval_source_mode,
                "direct_recall_key": self.direct_recall_key,
                "auto_keywords": self.auto_keywords,
                "user_keywords": self.user_keywords,
                "active_project_name": self.active_project_name,
                "embedded_files_snapshot": self.embedded_files_snapshot,
            }
        )
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryRecord":
        """
        Load one MemoryRecord from a .ragmem block.

        Supports both:
        - new body-only .ragmem blocks
        - older full .ragmem blocks that still contain metadata

        Current metadata from .ragmeta.json is applied later by MemoryManager.
        """
        auto_keywords_raw = data.get("auto_keywords")

        return cls(
            input_text=str(data.get("input_text", "")),
            output_text=str(data.get("output_text", "")),
            source=str(data.get("source", "")),
            parent_id=_optional_str(data.get("parent_id")),
            tag=str(data.get("tag", "Green")),
            user_keywords=list(data.get("user_keywords") or []),
            active_project_name=_optional_str(data.get("active_project_name")),
            embedded_files_snapshot=list(data.get("embedded_files_snapshot") or []),
            retrieval_source_mode=str(data.get("retrieval_source_mode", "QA")),
            direct_recall_key=str(data.get("direct_recall_key", "")),
            active_retrieval_brief_title=str(data.get("active_retrieval_brief_title", "") or ""),
            active_retrieval_brief=str(data.get("active_retrieval_brief", "") or ""),
            active_retrieval_brief_contributor_ids=list(
                data.get("active_retrieval_brief_contributor_ids") or []
            ),
            record_id=str(data.get("record_id") or uuid.uuid4().hex),
            created_at_utc=str(data.get("created_at_utc") or _utc_now()),
            auto_keywords=(
                list(auto_keywords_raw)
                if isinstance(auto_keywords_raw, list)
                else None
            ),
            input_hash=data.get("input_hash"),
            output_hash=data.get("output_hash"),
        )
```

### ~\ragstream\memory\compression\memory_active_retrieval_brief.py
```python
# ragstream/memory/compression/memory_active_retrieval_brief.py
# -*- coding: utf-8 -*-
"""
MemoryActiveRetrievalBriefBuilder
=================================

Creates the ActiveRetrievalBrief for a newly captured MemoryRecord.

Current design:
- runs during Memory Recording
- uses K-1 ActiveBrief + reduced Q/A of K
- creates K ActiveBrief
- writes nothing directly to disk
- returns result to MemoryManager, which owns MemoryRecord truth

LLM calls:
- first record: init JSON
- later records: update JSON

Relevance-gate behavior:
- normal case:
    Q/A passes against current ActiveBrief center -> update ActiveBrief with LLM
- unrelated case:
    Q/A fails against ActiveBrief and pending topic -> skip LLM, copy old brief
- topic-shift case:
    Q/A fails against ActiveBrief but passes against pending skipped Q/A -> create a new brief from pending Q/A + current Q/A
"""

from __future__ import annotations

import json

from pathlib import Path
from typing import Any

from ragstream.memory.memory_record import MemoryRecord
from ragstream.memory.compression.memory_sentence_reducer import (
    MemorySentenceReducer,
    ReducedQA,
)
from ragstream.memory.compression.memory_activebrief_relevance_gate import (
    MemoryActiveBriefRelevanceGate,
)
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


class MemoryActiveRetrievalBriefBuilder:
    def __init__(
        self,
        *,
        runtime_config: JsonDict | None = None,
        agent_factory: AgentFactory | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.runtime_config = runtime_config if isinstance(runtime_config, dict) else self._load_runtime_config()

        cfg = self.runtime_config.get("memory_active_retrieval_brief", {}) or {}
        reducer_cfg = cfg.get("reducer", {}) or {}
        llm_cfg = cfg.get("llm", {}) or {}
        gate_cfg = cfg.get("activebrief_relevance_gate", {}) or {}

        self.target_brief_tokens = int(llm_cfg.get("target_brief_tokens", 700))
        self.prompt_cache_key = str(
            llm_cfg.get("prompt_cache_key", "memory_activebrief_qa_summarizer")
        )

        self.agent_id = str(
            llm_cfg.get("agent_id", "memory_activebrief_qa_summarizer")
        )
        self.init_agent_version = str(
            llm_cfg.get(
                "init_agent_version",
                "memory_activebrief_qa_summarizer_init_001",
            )
        )
        self.update_agent_version = str(
            llm_cfg.get(
                "update_agent_version",
                "memory_activebrief_qa_summarizer_update_001",
            )
        )

        embedding_model = str(reducer_cfg.get("embedding_model", "text-embedding-3-small"))
        window_size_sentences = int(reducer_cfg.get("window_size_sentences", 3))
        window_overlap_sentences = int(reducer_cfg.get("window_overlap_sentences", 1))

        self.relevance_gate_enabled = bool(gate_cfg.get("enabled", True))

        self.reducer = MemorySentenceReducer(
            max_tokens_total=int(reducer_cfg.get("max_tokens_total", 3000)),
            question_max_tokens=int(reducer_cfg.get("question_max_tokens", 1000)),
            window_size_sentences=window_size_sentences,
            window_overlap_sentences=window_overlap_sentences,
            redundancy_threshold=float(reducer_cfg.get("redundancy_threshold", 0.92)),
            embedding_model=embedding_model,
        )

        self.relevance_gate = MemoryActiveBriefRelevanceGate(
            embedding_model=embedding_model,
            window_size_sentences=window_size_sentences,
            window_overlap_sentences=window_overlap_sentences,
            activebrief_threshold=float(gate_cfg.get("activebrief_threshold", 0.25)),
            pending_topic_threshold=float(gate_cfg.get("pending_topic_threshold", 0.25)),
        )

        self.agent_factory = agent_factory or AgentFactory()
        self.llm_client = llm_client or LLMClient()

    def build_for_record(
        self,
        *,
        record: MemoryRecord,
        previous_records: list[MemoryRecord],
        pending_topic_buffer: dict[str, Any] | None = None,
    ) -> JsonDict:
        if record is None:
            raise ValueError("MemoryActiveRetrievalBriefBuilder.build_for_record: record is None")

        pending_topic_buffer = pending_topic_buffer if isinstance(pending_topic_buffer, dict) else {}

        previous_brief_info = self._find_previous_clean_brief(previous_records)

        reduced_qa = self.reducer.reduce_with_centroid(
            input_text=record.input_text,
            output_text=record.output_text,
        )

        logger_dev(
            "ActiveBrief current raw Q/A\n"
            + json.dumps(
                {
                    "record_id": record.record_id,
                    "input_text": record.input_text,
                    "output_text": record.output_text,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            "DEBUG",
            "CONFIDENTIAL",
        )

        logger_dev(
            "ActiveBrief reduced Q/A after deterministic reduction\n"
            + json.dumps(
                {
                    "record_id": record.record_id,
                    "reduced_question": reduced_qa.reduced_question,
                    "reduced_answer": reduced_qa.reduced_answer,
                    "question_vector_count": len(reduced_qa.question_vectors),
                    "answer_vector_count": len(reduced_qa.answer_vectors),
                    "diagnostics": reduced_qa.diagnostics,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            "DEBUG",
            "CONFIDENTIAL",
        )

        logger_dev(
            "ActiveBrief previous clean brief and pending-topic state\n"
            + json.dumps(
                {
                    "previous_brief_info": previous_brief_info,
                    "pending_topic_buffer": self._pending_buffer_log_view(pending_topic_buffer),
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            "DEBUG",
            "CONFIDENTIAL",
        )

        if previous_brief_info["previous_active_retrieval_brief"]:
            return self._handle_update_or_skip(
                record=record,
                reduced_qa=reduced_qa,
                previous_brief_info=previous_brief_info,
                pending_topic_buffer=pending_topic_buffer,
            )

        result = self._run_init_agent(
            record=record,
            reduced_qa=reduced_qa,
            call_name="Memory ActiveBrief Init",
        )
        contributor_ids = [record.record_id]
        active_brief_title = str(result.get("active_retrieval_brief_title", "") or "").strip()
        active_brief = str(result.get("active_retrieval_brief", "") or "").strip()

        logger_dev(
            "ActiveBrief new LLM result\n"
            + json.dumps(
                {
                    "record_id": record.record_id,
                    "route": "init_no_previous_activebrief",
                    "active_retrieval_brief_title": active_brief_title,
                    "active_retrieval_brief": active_brief,
                    "active_retrieval_brief_contributor_ids": contributor_ids,
                    "pending_topic_buffer_after": {},
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return {
            "active_retrieval_brief_title": active_brief_title,
            "active_retrieval_brief": active_brief,
            "active_retrieval_brief_contributor_ids": contributor_ids,
            "reduced_qa_diagnostics": reduced_qa.diagnostics,
            "activebrief_llm_skipped": False,
            "activebrief_gate_route": "init_no_previous_activebrief",
            "pending_activebrief_topic_buffer": {},
        }

    def _handle_update_or_skip(
        self,
        *,
        record: MemoryRecord,
        reduced_qa: ReducedQA,
        previous_brief_info: JsonDict,
        pending_topic_buffer: dict[str, Any],
    ) -> JsonDict:
        previous_brief_title = str(previous_brief_info.get("previous_active_retrieval_brief_title", "") or "").strip()
        previous_brief = str(previous_brief_info["previous_active_retrieval_brief"])
        previous_contributor_ids = list(previous_brief_info.get("contributor_ids") or [])

        if not self.relevance_gate_enabled:
            result = self._run_update_agent(
                record=record,
                reduced_qa=reduced_qa,
                previous_brief=previous_brief,
                call_name="Memory ActiveBrief Update",
            )
            contributor_ids = self._merge_contributor_ids(previous_contributor_ids, [record.record_id])
            active_brief_title = str(result.get("active_retrieval_brief_title", "") or "").strip()
            active_brief = str(result.get("active_retrieval_brief", "") or "").strip()

            return {
                "active_retrieval_brief_title": active_brief_title,
                "active_retrieval_brief": active_brief,
                "active_retrieval_brief_contributor_ids": contributor_ids,
                "reduced_qa_diagnostics": reduced_qa.diagnostics,
                "activebrief_llm_skipped": False,
                "activebrief_gate_route": "gate_disabled",
                "pending_activebrief_topic_buffer": {},
            }

        gate_result = self.relevance_gate.evaluate(
            record_id=record.record_id,
            previous_active_retrieval_brief=previous_brief,
            question_vectors=reduced_qa.question_vectors,
            answer_vectors=reduced_qa.answer_vectors,
            pending_topic_buffer=pending_topic_buffer,
        )

        if gate_result.route == "activebrief_update":
            result = self._run_update_agent(
                record=record,
                reduced_qa=reduced_qa,
                previous_brief=previous_brief,
                call_name="Memory ActiveBrief Update",
            )
            contributor_ids = self._merge_contributor_ids(previous_contributor_ids, [record.record_id])
            active_brief_title = str(result.get("active_retrieval_brief_title", "") or "").strip()
            active_brief = str(result.get("active_retrieval_brief", "") or "").strip()

            logger_dev(
                "ActiveBrief update accepted by relevance gate\n"
                + json.dumps(
                    {
                        "record_id": record.record_id,
                        "route": gate_result.route,
                        "reason": gate_result.reason,
                        "active_retrieval_brief_title": active_brief_title,
                        "active_retrieval_brief_contributor_ids": contributor_ids,
                        "pending_topic_buffer_after": {},
                        "gate_diagnostics": gate_result.diagnostics,
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                "DEBUG",
                "CONFIDENTIAL",
            )

            return {
                "active_retrieval_brief_title": active_brief_title,
                "active_retrieval_brief": active_brief,
                "active_retrieval_brief_contributor_ids": contributor_ids,
                "reduced_qa_diagnostics": reduced_qa.diagnostics,
                "activebrief_relevance_gate": gate_result.diagnostics,
                "activebrief_llm_skipped": False,
                "activebrief_gate_route": gate_result.route,
                "pending_activebrief_topic_buffer": {},
            }

        if gate_result.route == "pending_topic_shift":
            combined_reduced_qa = self._combine_pending_and_current_reduced_qa(
                pending_topic_buffer=pending_topic_buffer,
                current_reduced_qa=reduced_qa,
            )

            result = self._run_update_agent(
                record=record,
                reduced_qa=combined_reduced_qa,
                previous_brief=previous_brief,
                call_name="Memory ActiveBrief Topic Shift",
            )

            pending_record_id = str(pending_topic_buffer.get("record_id", "") or "")
            contributor_ids = self._merge_contributor_ids(
                previous_contributor_ids,
                [pending_record_id, record.record_id],
            )
            active_brief_title = str(result.get("active_retrieval_brief_title", "") or "").strip()
            active_brief = str(result.get("active_retrieval_brief", "") or "").strip()

            logger_dev(
                "ActiveBrief topic shift confirmed by pending-topic gate\n"
                + json.dumps(
                    {
                        "record_id": record.record_id,
                        "pending_record_id": pending_record_id,
                        "route": gate_result.route,
                        "reason": gate_result.reason,
                        "active_retrieval_brief_title": active_brief_title,
                        "active_retrieval_brief": active_brief,
                        "active_retrieval_brief_contributor_ids": contributor_ids,
                        "pending_topic_buffer_after": {},
                        "gate_diagnostics": gate_result.diagnostics,
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                "DEBUG",
                "CONFIDENTIAL",
            )

            return {
                "active_retrieval_brief_title": active_brief_title,
                "active_retrieval_brief": active_brief,
                "active_retrieval_brief_contributor_ids": contributor_ids,
                "reduced_qa_diagnostics": reduced_qa.diagnostics,
                "activebrief_relevance_gate": gate_result.diagnostics,
                "activebrief_llm_skipped": False,
                "activebrief_gate_route": gate_result.route,
                "pending_activebrief_topic_buffer": {},
            }

        new_pending_buffer = self.relevance_gate.build_pending_topic_buffer(
            record_id=record.record_id,
            created_at_utc=record.created_at_utc,
            reduced_question=reduced_qa.reduced_question,
            reduced_answer=reduced_qa.reduced_answer,
            question_vectors=reduced_qa.question_vectors,
            answer_vectors=reduced_qa.answer_vectors,
        )

        logger_dev(
            "ActiveBrief update skipped by relevance gate\n"
            + json.dumps(
                {
                    "record_id": record.record_id,
                    "route": gate_result.route,
                    "reason": gate_result.reason,
                    "copied_previous_brief_record_id": previous_brief_info.get("record_id", ""),
                    "active_retrieval_brief_title": previous_brief_title,
                    "active_retrieval_brief": previous_brief,
                    "active_retrieval_brief_contributor_ids": previous_contributor_ids,
                    "pending_topic_buffer_after": self._pending_buffer_log_view(new_pending_buffer),
                    "gate_diagnostics": gate_result.diagnostics,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return {
            "active_retrieval_brief_title": previous_brief_title,
            "active_retrieval_brief": previous_brief,
            "active_retrieval_brief_contributor_ids": previous_contributor_ids,
            "reduced_qa_diagnostics": reduced_qa.diagnostics,
            "activebrief_relevance_gate": gate_result.diagnostics,
            "activebrief_llm_skipped": True,
            "activebrief_gate_route": gate_result.route,
            "pending_activebrief_topic_buffer": new_pending_buffer,
        }

    def _run_init_agent(
        self,
        *,
        record: MemoryRecord,
        reduced_qa: ReducedQA,
        call_name: str,
    ) -> JsonDict:
        agent_prompt = self.agent_factory.get_agent(
            self.agent_id,
            self.init_agent_version,
        )

        payload = self._compose_init_payload(
            record=record,
            reduced_qa=reduced_qa,
        )

        return self._run_agent_call(
            call_name=call_name,
            agent_prompt=agent_prompt,
            input_payload=payload,
        )

    def _run_update_agent(
        self,
        *,
        record: MemoryRecord,
        reduced_qa: ReducedQA,
        previous_brief: str,
        call_name: str,
    ) -> JsonDict:
        agent_prompt = self.agent_factory.get_agent(
            self.agent_id,
            self.update_agent_version,
        )

        payload = self._compose_update_payload(
            record=record,
            reduced_qa=reduced_qa,
            previous_brief=previous_brief,
        )

        return self._run_agent_call(
            call_name=call_name,
            agent_prompt=agent_prompt,
            input_payload=payload,
        )

    def _compose_init_payload(
        self,
        *,
        record: MemoryRecord,
        reduced_qa: ReducedQA,
    ) -> JsonDict:
        return {
            "reduced_question": reduced_qa.reduced_question,
            "reduced_answer": reduced_qa.reduced_answer,
            "memory_record_metadata": self._build_metadata_text(record),
            "required_output": self._build_required_output_text(),
        }

    def _compose_update_payload(
        self,
        *,
        record: MemoryRecord,
        reduced_qa: ReducedQA,
        previous_brief: str,
    ) -> JsonDict:
        return {
            "previous_active_retrieval_brief": previous_brief,
            "reduced_question": reduced_qa.reduced_question,
            "reduced_answer": reduced_qa.reduced_answer,
            "memory_record_metadata": self._build_metadata_text(record),
            "required_output": self._build_required_output_text(),
        }

    def _run_agent_call(
        self,
        *,
        call_name: str,
        agent_prompt: AgentPrompt,
        input_payload: JsonDict,
    ) -> JsonDict:
        messages, response_format = agent_prompt.compose(input_payload=input_payload)

        logger_dev(
            f"{call_name} LLM prompt payload\n"
            + json.dumps(input_payload, ensure_ascii=False, indent=2, default=str),
            "DEBUG",
            "CONFIDENTIAL",
        )

        logger_dev(
            f"{call_name} LLM messages\n"
            + json.dumps(messages, ensure_ascii=False, indent=2, default=str),
            "DEBUG",
            "CONFIDENTIAL",
        )

        response = self.llm_client.responses(
            messages=messages,
            model_name=agent_prompt.model_name,
            max_output_tokens=agent_prompt.max_output_tokens,
            reasoning_effort="minimal",
            return_metadata=True,
            prompt_cache_key=self.prompt_cache_key,
        )

        raw_content = str(response.get("content", "") or "")
        usage = response.get("usage", {}) or {}

        logger_dev(
            f"{call_name} LLM raw response\n"
            + json.dumps(
                {
                    "content": raw_content,
                    "usage": usage,
                    "model_name": response.get("model_name", ""),
                    "status": response.get("status", ""),
                    "incomplete_reason": response.get("incomplete_reason", ""),
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            "DEBUG",
            "CONFIDENTIAL",
        )

        parsed = agent_prompt.parse(raw_content)

        logger_dev(
            f"{call_name} parsed result\n"
            + json.dumps(parsed, ensure_ascii=False, indent=2, default=str),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return parsed

    def _combine_pending_and_current_reduced_qa(
        self,
        *,
        pending_topic_buffer: dict[str, Any],
        current_reduced_qa: ReducedQA,
    ) -> ReducedQA:
        """
        Topic-shift LLM payload.

        When the current Q/A is not related to the old ActiveBrief but is related
        to the previously skipped Q/A, we create a new ActiveBrief from both:
        - the previous pending Q/A
        - the current Q/A

        This prevents the first skipped item of the new theme from being lost.
        """
        pending_question = str(pending_topic_buffer.get("reduced_question", "") or "").strip()
        pending_answer = str(pending_topic_buffer.get("reduced_answer", "") or "").strip()

        combined_question_parts = []
        if pending_question:
            combined_question_parts.append("[Pending skipped Q/A question]\n" + pending_question)
        if current_reduced_qa.reduced_question:
            combined_question_parts.append("[Current Q/A question]\n" + current_reduced_qa.reduced_question)

        combined_answer_parts = []
        if pending_answer:
            combined_answer_parts.append("[Pending skipped Q/A answer]\n" + pending_answer)
        if current_reduced_qa.reduced_answer:
            combined_answer_parts.append("[Current Q/A answer]\n" + current_reduced_qa.reduced_answer)

        return ReducedQA(
            reduced_question="\n\n".join(combined_question_parts).strip(),
            reduced_answer="\n\n".join(combined_answer_parts).strip(),
            question_vectors=[],
            answer_vectors=[],
            diagnostics={
                "mode": "topic_shift_combined_pending_and_current",
                "pending_record_id": str(pending_topic_buffer.get("record_id", "") or ""),
                "current_question_vector_count": len(current_reduced_qa.question_vectors),
                "current_answer_vector_count": len(current_reduced_qa.answer_vectors),
            },
        )

    def _find_previous_clean_brief(
        self,
        previous_records: list[MemoryRecord],
    ) -> JsonDict:
        records = list(previous_records or [])
        black_ids = {
            record.record_id
            for record in records
            if str(getattr(record, "tag", "") or "").strip() == "Black"
        }

        for record in reversed(records):
            if str(getattr(record, "tag", "") or "").strip() == "Black":
                continue

            brief = str(getattr(record, "active_retrieval_brief", "") or "").strip()
            if not brief:
                continue

            brief_title = str(getattr(record, "active_retrieval_brief_title", "") or "").strip()

            contributor_ids = list(
                getattr(record, "active_retrieval_brief_contributor_ids", []) or []
            )

            if any(contributor_id in black_ids for contributor_id in contributor_ids):
                continue

            return {
                "record_id": record.record_id,
                "previous_active_retrieval_brief_title": brief_title,
                "previous_active_retrieval_brief": brief,
                "contributor_ids": contributor_ids or [record.record_id],
            }

        return {
            "record_id": "",
            "previous_active_retrieval_brief_title": "",
            "previous_active_retrieval_brief": "",
            "contributor_ids": [],
        }

    def _build_metadata_text(
        self,
        record: MemoryRecord,
    ) -> str:
        data = {
            "record_id": record.record_id,
            "parent_id": record.parent_id,
            "created_at_utc": record.created_at_utc,
            "source": record.source,
            "tag": record.tag,
            "retrieval_source_mode": record.retrieval_source_mode,
            "active_project_name": record.active_project_name,
            "auto_keywords": record.auto_keywords,
            "user_keywords": record.user_keywords,
            "embedded_files_snapshot": record.embedded_files_snapshot,
        }

        return json.dumps(data, ensure_ascii=False, indent=2, default=str)

    def _build_required_output_text(self) -> str:
        return (
            "{\n"
            '  "active_retrieval_brief_title": "operational backend title following the JSON Title Rules",\n'
            '  "active_retrieval_brief": "one compact query-independent Current Working Conversation brief"\n'
            "}\n\n"
            "Follow the JSON Title Rules for active_retrieval_brief_title.\n"
            f"Keep active_retrieval_brief at or below about {self.target_brief_tokens} tokens."
        )

    @staticmethod
    def _merge_contributor_ids(
        old_ids: list[str],
        new_ids: list[str],
    ) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()

        for value in list(old_ids or []) + list(new_ids or []):
            item = str(value or "").strip()
            if not item:
                continue

            if item in seen:
                continue

            result.append(item)
            seen.add(item)

        return result

    @staticmethod
    def _pending_buffer_log_view(buffer: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(buffer, dict) or not buffer:
            return {}

        return {
            "record_id": str(buffer.get("record_id", "") or ""),
            "created_at_utc": str(buffer.get("created_at_utc", "") or ""),
            "question_vector_count": len(buffer.get("question_vectors", []) or []),
            "answer_vector_count": len(buffer.get("answer_vectors", []) or []),
            "vector_count": int(buffer.get("vector_count", 0) or 0),
            "has_center_vector": bool(buffer.get("center_vector", [])),
            "reduced_question_preview": str(buffer.get("reduced_question", "") or "")[:500],
            "reduced_answer_preview": str(buffer.get("reduced_answer", "") or "")[:500],
        }

    @staticmethod
    def _load_runtime_config() -> JsonDict:
        root = Path(__file__).resolve().parents[3]
        path = root / "ragstream" / "config" / "runtime_config.json"

        if not path.exists():
            return {}

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
```

### ~\ragstream\memory\compression\memory_activebrief_relevance_gate.py
```python
# ragstream/memory/compression/memory_activebrief_relevance_gate.py
# -*- coding: utf-8 -*-
"""
MemoryActiveBriefRelevanceGate
==============================

Non-LLM gate before ActiveBrief update.

Purpose:
- Avoid sending unrelated Q/A pairs to the ActiveBrief LLM updater.
- Still save every MemoryRecord normally.
- If a Q/A is not worthy, copy the previous ActiveBrief into the new record.
- If a new topic becomes stable, allow it to replace/update the ActiveBrief.

Current logic:
1. Compare new Q/A vectors to the center of the current ActiveBrief.
2. If Q/A top-score mean passes activebrief_threshold:
   -> normal ActiveBrief update.
3. If it fails, compare new Q/A vectors to the center of the previous skipped Q/A.
4. If Q/A top-score mean passes pending_topic_threshold:
   -> topic shift confirmed, call LLM using the pending Q/A + current Q/A.
5. If both fail:
   -> skip LLM, copy previous ActiveBrief, update pending-topic buffer.

Important:
- No ActiveBrief weak-tail / 80% logic remains here.
- The gate uses fixed development thresholds from runtime_config.
- The gate logs only scores and summaries, not full vectors.
"""

from __future__ import annotations

import json
import math
import re

from dataclasses import dataclass
from typing import Any

from ragstream.ingestion.embedder import Embedder
from ragstream.textforge.RagLog import LogDeveloper as _logger_dev
DEV_LOG_ENABLED = False

def logger_dev(*args, **kwargs):
    if DEV_LOG_ENABLED:
        return _logger_dev(*args, **kwargs)
    return None

Vector = list[float]


@dataclass
class RelevanceGateResult:
    should_update_activebrief: bool
    route: str
    reason: str
    activebrief_top_mean: float
    pending_topic_top_mean: float
    diagnostics: dict[str, Any]


class MemoryActiveBriefRelevanceGate:
    def __init__(
        self,
        *,
        embedding_model: str = "text-embedding-3-small",
        window_size_sentences: int = 3,
        window_overlap_sentences: int = 1,
        activebrief_threshold: float = 0.25,
        pending_topic_threshold: float = 0.25,
    ) -> None:
        self.embedding_model = str(embedding_model)
        self.window_size_sentences = int(window_size_sentences)
        self.window_overlap_sentences = int(window_overlap_sentences)
        self.activebrief_threshold = float(activebrief_threshold)
        self.pending_topic_threshold = float(pending_topic_threshold)

        self._embedder = Embedder(model=self.embedding_model)

    def evaluate(
        self,
        *,
        record_id: str,
        previous_active_retrieval_brief: str,
        question_vectors: list[Vector],
        answer_vectors: list[Vector],
        pending_topic_buffer: dict[str, Any] | None = None,
    ) -> RelevanceGateResult:
        """
        Decide whether the current Q/A should update ActiveBrief.

        Q/A vectors are reused from MemorySentenceReducer.
        The only new embedding cost here is the previous ActiveBrief text.
        """
        previous_brief = str(previous_active_retrieval_brief or "").strip()
        pending_topic_buffer = pending_topic_buffer if isinstance(pending_topic_buffer, dict) else {}

        qa_vectors = list(question_vectors or []) + list(answer_vectors or [])

        if not previous_brief:
            return self._log_and_return(
                record_id=record_id,
                result=RelevanceGateResult(
                    should_update_activebrief=True,
                    route="init_no_previous_activebrief",
                    reason="no_previous_activebrief",
                    activebrief_top_mean=0.0,
                    pending_topic_top_mean=0.0,
                    diagnostics={
                        "record_id": record_id,
                        "decision": "pass",
                        "route": "init_no_previous_activebrief",
                        "reason": "no_previous_activebrief",
                    },
                ),
            )

        if not qa_vectors:
            return self._log_and_return(
                record_id=record_id,
                result=RelevanceGateResult(
                    should_update_activebrief=False,
                    route="skip_no_qa_vectors",
                    reason="no_qa_vectors",
                    activebrief_top_mean=0.0,
                    pending_topic_top_mean=0.0,
                    diagnostics={
                        "record_id": record_id,
                        "decision": "skip",
                        "route": "skip_no_qa_vectors",
                        "reason": "no_qa_vectors",
                    },
                ),
            )

        activebrief_center = self._build_activebrief_center(previous_brief)

        if not activebrief_center:
            # Safe pass:
            # If the ActiveBrief reference space cannot be built,
            # do not risk blocking an update.
            return self._log_and_return(
                record_id=record_id,
                result=RelevanceGateResult(
                    should_update_activebrief=True,
                    route="activebrief_safe_pass",
                    reason="no_activebrief_center_safe_pass",
                    activebrief_top_mean=0.0,
                    pending_topic_top_mean=0.0,
                    diagnostics={
                        "record_id": record_id,
                        "decision": "pass",
                        "route": "activebrief_safe_pass",
                        "reason": "no_activebrief_center_safe_pass",
                    },
                ),
            )

        activebrief_eval = self._evaluate_against_center(
            center_vector=activebrief_center,
            question_vectors=question_vectors,
            answer_vectors=answer_vectors,
        )

        if activebrief_eval["qa_top_mean"] >= self.activebrief_threshold:
            diagnostics = {
                "record_id": record_id,
                "decision": "pass",
                "route": "activebrief_update",
                "reason": "qa_top_mean_passed_activebrief_threshold",
                "embedding_model": self.embedding_model,
                "activebrief_threshold": self.activebrief_threshold,
                "pending_topic_threshold": self.pending_topic_threshold,
                "activebrief_comparison": activebrief_eval,
                "pending_topic_comparison": {},
            }

            return self._log_and_return(
                record_id=record_id,
                result=RelevanceGateResult(
                    should_update_activebrief=True,
                    route="activebrief_update",
                    reason="qa_top_mean_passed_activebrief_threshold",
                    activebrief_top_mean=float(activebrief_eval["qa_top_mean"]),
                    pending_topic_top_mean=0.0,
                    diagnostics=diagnostics,
                ),
            )

        pending_center = self._extract_pending_center(pending_topic_buffer)

        pending_eval: dict[str, Any] = {}
        if pending_center:
            pending_eval = self._evaluate_against_center(
                center_vector=pending_center,
                question_vectors=question_vectors,
                answer_vectors=answer_vectors,
            )

            if pending_eval["qa_top_mean"] >= self.pending_topic_threshold:
                diagnostics = {
                    "record_id": record_id,
                    "decision": "pass",
                    "route": "pending_topic_shift",
                    "reason": "qa_top_mean_passed_pending_topic_threshold",
                    "embedding_model": self.embedding_model,
                    "activebrief_threshold": self.activebrief_threshold,
                    "pending_topic_threshold": self.pending_topic_threshold,
                    "pending_topic_record_id": str(pending_topic_buffer.get("record_id", "") or ""),
                    "activebrief_comparison": activebrief_eval,
                    "pending_topic_comparison": pending_eval,
                }

                return self._log_and_return(
                    record_id=record_id,
                    result=RelevanceGateResult(
                        should_update_activebrief=True,
                        route="pending_topic_shift",
                        reason="qa_top_mean_passed_pending_topic_threshold",
                        activebrief_top_mean=float(activebrief_eval["qa_top_mean"]),
                        pending_topic_top_mean=float(pending_eval["qa_top_mean"]),
                        diagnostics=diagnostics,
                    ),
                )

        diagnostics = {
            "record_id": record_id,
            "decision": "skip",
            "route": "skip_and_update_pending_topic",
            "reason": "qa_failed_activebrief_and_pending_topic_thresholds",
            "embedding_model": self.embedding_model,
            "activebrief_threshold": self.activebrief_threshold,
            "pending_topic_threshold": self.pending_topic_threshold,
            "pending_topic_record_id": str(pending_topic_buffer.get("record_id", "") or ""),
            "activebrief_comparison": activebrief_eval,
            "pending_topic_comparison": pending_eval,
        }

        return self._log_and_return(
            record_id=record_id,
            result=RelevanceGateResult(
                should_update_activebrief=False,
                route="skip_and_update_pending_topic",
                reason="qa_failed_activebrief_and_pending_topic_thresholds",
                activebrief_top_mean=float(activebrief_eval["qa_top_mean"]),
                pending_topic_top_mean=float(pending_eval.get("qa_top_mean", 0.0) or 0.0),
                diagnostics=diagnostics,
            ),
        )

    def build_pending_topic_buffer(
        self,
        *,
        record_id: str,
        created_at_utc: str,
        reduced_question: str,
        reduced_answer: str,
        question_vectors: list[Vector],
        answer_vectors: list[Vector],
    ) -> dict[str, Any]:
        """
        Build the RAM-only pending-topic buffer.

        This buffer is not persisted into .ragmem or SQLite.
        It exists only to detect a possible topic shift:
        first skipped Q/A creates the buffer;
        next skipped Q/A is compared against this buffer.
        """
        qa_vectors = list(question_vectors or []) + list(answer_vectors or [])
        center_vector = self._centroid(qa_vectors)

        buffer = {
            "record_id": str(record_id or ""),
            "created_at_utc": str(created_at_utc or ""),
            "reduced_question": str(reduced_question or ""),
            "reduced_answer": str(reduced_answer or ""),
            "question_vectors": list(question_vectors or []),
            "answer_vectors": list(answer_vectors or []),
            "center_vector": center_vector,
            "vector_count": len(qa_vectors),
        }

        logger_dev(
            "ActiveBrief pending-topic buffer updated\n"
            + json.dumps(
                {
                    "record_id": buffer["record_id"],
                    "created_at_utc": buffer["created_at_utc"],
                    "question_vector_count": len(buffer["question_vectors"]),
                    "answer_vector_count": len(buffer["answer_vectors"]),
                    "vector_count": buffer["vector_count"],
                    "has_center_vector": bool(buffer["center_vector"]),
                    "reduced_question_preview": buffer["reduced_question"][:500],
                    "reduced_answer_preview": buffer["reduced_answer"][:500],
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return buffer

    def _build_activebrief_center(self, previous_brief: str) -> Vector:
        activebrief_windows = self._build_sentence_windows(previous_brief)
        activebrief_texts = [item["text"] for item in activebrief_windows]
        activebrief_vectors = self._embed_texts(activebrief_texts)
        return self._centroid(activebrief_vectors)

    def _evaluate_against_center(
        self,
        *,
        center_vector: Vector,
        question_vectors: list[Vector],
        answer_vectors: list[Vector],
    ) -> dict[str, Any]:
        """
        Score Q/A vectors against a reference center.

        Used twice:
        - Q/A against current ActiveBrief center
        - Q/A against pending skipped-topic center
        """
        question_scores = [
            self._cosine(vector, center_vector)
            for vector in question_vectors or []
        ]
        answer_scores = [
            self._cosine(vector, center_vector)
            for vector in answer_vectors or []
        ]
        qa_scores = question_scores + answer_scores
        qa_scores_sorted = sorted(qa_scores, reverse=True)

        top_count = self._select_count(len(qa_scores_sorted))
        top_scores = qa_scores_sorted[:top_count]
        top_mean = self._mean(top_scores)

        return {
            "qa_vector_count": len(qa_scores),
            "question_vector_count": len(question_scores),
            "answer_vector_count": len(answer_scores),
            "qa_top_count": top_count,
            "qa_top_mean": top_mean,
            "qa_top_scores": self._round_list(top_scores),
            "qa_all_scores_best_to_worst": self._round_list(qa_scores_sorted),
            "qa_score_summary": self._score_summary(qa_scores),
            "question_score_summary": self._score_summary(question_scores),
            "answer_score_summary": self._score_summary(answer_scores),
        }

    @staticmethod
    def _select_count(n: int) -> int:
        """
        Stable 20% top-score selection rule.

        For small texts, pure percentage is unstable:
        - <= 4 vectors: use all
        - 5..20 vectors: use top 4
        - > 20 vectors: use floor(n / 5)
        """
        n = int(n)
        if n <= 0:
            return 0
        if n <= 4:
            return n
        if n <= 20:
            return 4
        return max(1, n // 5)

    @staticmethod
    def _extract_pending_center(pending_topic_buffer: dict[str, Any]) -> Vector:
        center = pending_topic_buffer.get("center_vector", [])
        if not isinstance(center, list):
            return []
        return [float(value) for value in center]

    def _build_sentence_windows(self, text: str) -> list[dict[str, Any]]:
        sentences = self._split_sentences(text)

        if not sentences:
            return []

        window_size = max(1, self.window_size_sentences)
        overlap = max(0, min(self.window_overlap_sentences, window_size - 1))
        step = max(1, window_size - overlap)

        windows: list[dict[str, Any]] = []

        start = 0
        while start < len(sentences):
            end = min(len(sentences), start + window_size)
            indexes = list(range(start, end))
            window_text = " ".join(sentences[start:end]).strip()

            if window_text:
                windows.append(
                    {
                        "text": window_text,
                        "sentence_indexes": indexes,
                    }
                )

            if end >= len(sentences):
                break

            start += step

        return windows

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        clean = str(text or "").strip()
        if not clean:
            return []

        clean = re.sub(r"\n{2,}", "\n", clean)
        rough_parts = re.split(r"(?<=[.!?])\s+|\n+", clean)

        sentences: list[str] = []
        for part in rough_parts:
            item = str(part or "").strip()
            if item:
                sentences.append(item)

        if not sentences and clean:
            sentences.append(clean)

        return sentences

    def _embed_texts(self, texts: list[str]) -> list[Vector]:
        clean_texts = [str(text or "").strip() for text in texts]
        clean_texts = [text for text in clean_texts if text]

        if not clean_texts:
            return []

        vectors = self._embedder.embed(clean_texts)
        return [list(vector) for vector in vectors]

    @staticmethod
    def _centroid(vectors: list[Vector]) -> Vector:
        if not vectors:
            return []

        dim = len(vectors[0])
        if dim <= 0:
            return []

        sums = [0.0 for _ in range(dim)]
        count = 0

        for vector in vectors:
            if len(vector) != dim:
                continue

            for i, value in enumerate(vector):
                sums[i] += float(value)

            count += 1

        if count <= 0:
            return []

        return [value / float(count) for value in sums]

    @staticmethod
    def _cosine(a: Vector, b: Vector) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0

        dot = 0.0
        norm_a = 0.0
        norm_b = 0.0

        for x, y in zip(a, b):
            fx = float(x)
            fy = float(y)
            dot += fx * fy
            norm_a += fx * fx
            norm_b += fy * fy

        if norm_a <= 0.0 or norm_b <= 0.0:
            return 0.0

        return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))

    @staticmethod
    def _mean(values: list[float]) -> float:
        if not values:
            return 0.0
        return float(sum(float(value) for value in values) / len(values))

    @staticmethod
    def _round_list(values: list[float]) -> list[float]:
        return [round(float(value), 6) for value in values]

    def _score_summary(self, values: list[float]) -> dict[str, Any]:
        if not values:
            return {
                "count": 0,
                "min": 0.0,
                "max": 0.0,
                "mean": 0.0,
            }

        return {
            "count": len(values),
            "min": round(min(values), 6),
            "max": round(max(values), 6),
            "mean": round(self._mean(values), 6),
        }

    def _log_and_return(
        self,
        *,
        record_id: str,
        result: RelevanceGateResult,
    ) -> RelevanceGateResult:
        logger_dev(
            "ActiveBrief relevance gate decision\n"
            + json.dumps(
                {
                    "record_id": record_id,
                    "should_update_activebrief": result.should_update_activebrief,
                    "route": result.route,
                    "reason": result.reason,
                    "activebrief_top_mean": result.activebrief_top_mean,
                    "pending_topic_top_mean": result.pending_topic_top_mean,
                    "diagnostics": result.diagnostics,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            "DEBUG",
            "CONFIDENTIAL",
        )
        return result
```

### ~\ragstream\memory\compression\memory_compressor.py
```python
# ragstream/memory/compression/memory_compressor.py
# -*- coding: utf-8 -*-
"""
MemoryCompressor
================

Runtime-only memory compression helper.

Current Part-I responsibility:
- receive effective_retrieval_query_text
- reduce it to the configured query token budget
- embed the reduced query once
- use that query vector as anchor
- reduce selected episodic Q/A candidates with MemorySentenceReducer

Important:
- This does not modify MemoryRecord truth.
- This does not write .ragmem, .ragmeta.json, SQLite, or vectors.
- Compression output is query-dependent runtime data only.
"""

from __future__ import annotations

import math
import re

from typing import Any

from ragstream.ingestion.embedder import Embedder
from ragstream.memory.compression.memory_sentence_reducer import MemorySentenceReducer
from ragstream.textforge.RagLog import LogDeveloper as _logger_dev
DEV_LOG_ENABLED = False

def logger_dev(*args, **kwargs):
    if DEV_LOG_ENABLED:
        return _logger_dev(*args, **kwargs)
    return None
Vector = list[float]


class MemoryCompressor:
    def __init__(
        self,
        config: dict[str, Any] | None = None,
    ) -> None:
        runtime_config = dict(config or {})

        if "memory_compression" in runtime_config:
            cfg = dict(runtime_config.get("memory_compression", {}) or {})
        else:
            cfg = dict(runtime_config or {})

        self.config = cfg
        self.enabled = bool(cfg.get("enabled", True))

        query_cfg = dict(cfg.get("effective_query", {}) or {})
        episodic_cfg = dict(cfg.get("episodic_memory", {}) or {})

        self.query_max_tokens = int(query_cfg.get("max_tokens", 300))
        self.embedding_model = str(query_cfg.get("embedding_model", "text-embedding-3-small"))

        self.episodic_enabled = bool(episodic_cfg.get("enabled", True))
        self.episodic_max_tokens_total = int(episodic_cfg.get("max_tokens_total", 400))
        self.episodic_question_max_tokens = int(episodic_cfg.get("question_max_tokens", 150))

        self.window_size_sentences = int(episodic_cfg.get("window_size_sentences", 3))
        self.window_overlap_sentences = int(episodic_cfg.get("window_overlap_sentences", 1))
        self.redundancy_threshold = float(episodic_cfg.get("redundancy_threshold", 0.92))

        self._embedder = Embedder(model=self.embedding_model)

        self._episode_reducer = MemorySentenceReducer(
            max_tokens_total=self.episodic_max_tokens_total,
            question_max_tokens=self.episodic_question_max_tokens,
            window_size_sentences=self.window_size_sentences,
            window_overlap_sentences=self.window_overlap_sentences,
            redundancy_threshold=self.redundancy_threshold,
            embedding_model=self.embedding_model,
        )

    def is_enabled(self) -> bool:
        return bool(self.enabled)

    def compress_episodic_candidates(
        self,
        episodic_candidates: list[dict[str, Any]],
        effective_query_text: str,
    ) -> list[dict[str, Any]]:
        """
        Reduce episodic Q/A candidates against one query anchor vector.

        The returned candidates keep all original candidate keys and add
        compressed runtime-only fields.
        """
        candidates = list(episodic_candidates or [])

        if not self.enabled or not self.episodic_enabled:
            logger_dev(
                "MEMORY COMPRESSION SKIPPED\n"
                + str(
                    {
                        "reason": "disabled",
                        "enabled": self.enabled,
                        "episodic_enabled": self.episodic_enabled,
                        "candidate_count": len(candidates),
                    }
                ),
                "DEBUG",
                "CONFIDENTIAL",
            )
            return candidates

        query_info = self.build_query_anchor(effective_query_text)
        query_anchor_vector = list(query_info.get("query_anchor_vector", []) or [])

        if not query_anchor_vector:
            logger_dev(
                "MEMORY COMPRESSION SKIPPED\n"
                + str(
                    {
                        "reason": "empty_query_anchor_vector",
                        "candidate_count": len(candidates),
                        "query_diagnostics": query_info.get("diagnostics", {}),
                        "reduced_query_text": query_info.get("reduced_query_text", ""),
                    }
                ),
                "DEBUG",
                "CONFIDENTIAL",
            )
            return candidates

        compressed: list[dict[str, Any]] = []

        for candidate in candidates:
            compressed.append(
                self.compress_episodic_candidate(
                    candidate=candidate,
                    query_anchor_vector=query_anchor_vector,
                    query_diagnostics=query_info.get("diagnostics", {}),
                )
            )

        logger_dev(
            "MEMORY COMPRESSION RESULT\n"
            + str(
                {
                    "candidate_count_before": len(candidates),
                    "candidate_count_after": len(compressed),
                    "query_original_tokens_estimated": self._count_tokens(effective_query_text),
                    "query_reduced_tokens_estimated": self._count_tokens(
                        str(query_info.get("reduced_query_text", "") or "")
                    ),
                    "reduced_query_text": str(query_info.get("reduced_query_text", "") or ""),
                    "episodes": [
                        {
                            "record_id": str(item.get("record_id", "") or ""),
                            "memory_compression_mode": str(item.get("memory_compression_mode", "") or ""),
                            "input_tokens_before": self._count_tokens(str(item.get("input_text", "") or "")),
                            "output_tokens_before": self._count_tokens(str(item.get("output_text", "") or "")),
                            "compressed_input_tokens": self._count_tokens(str(item.get("compressed_input_text", "") or "")),
                            "compressed_output_tokens": self._count_tokens(str(item.get("compressed_output_text", "") or "")),
                            "compressed_input_text": str(item.get("compressed_input_text", "") or ""),
                            "compressed_output_text": str(item.get("compressed_output_text", "") or ""),
                        }
                        for item in compressed
                    ],
                }
            ),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return compressed

    def compress_episodic_candidate(
        self,
        *,
        candidate: dict[str, Any],
        query_anchor_vector: Vector,
        query_diagnostics: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Reduce one episodic MemoryRecord candidate.

        Original input_text/output_text stay unchanged in the candidate.
        Reduced Q/A is added as runtime compression fields.
        """
        item = dict(candidate or {})

        input_text = str(item.get("input_text", "") or "")
        output_text = str(item.get("output_text", "") or "")

        reduced = self._episode_reducer.reduce_with_anchor(
            input_text=input_text,
            output_text=output_text,
            anchor_vector=query_anchor_vector,
        )

        item["compressed_input_text"] = reduced.reduced_question
        item["compressed_output_text"] = reduced.reduced_answer
        item["memory_compression_mode"] = "query_anchor_episode"
        item["memory_compression_query_diagnostics"] = dict(query_diagnostics or {})
        item["memory_compression_diagnostics"] = reduced.diagnostics

        return item

    def build_query_anchor(
        self,
        effective_query_text: str,
    ) -> dict[str, Any]:
        """
        Reduce effective query to max query_max_tokens and embed it once.
        """
        original_query = str(effective_query_text or "").strip()
        reduced_query = self.reduce_query_text(original_query)

        if not reduced_query:
            return {
                "reduced_query_text": "",
                "query_anchor_vector": [],
                "diagnostics": {
                    "reason": "empty_query",
                    "query_max_tokens": self.query_max_tokens,
                },
            }

        query_anchor_vector = self._embed_query(reduced_query)

        return {
            "reduced_query_text": reduced_query,
            "query_anchor_vector": query_anchor_vector,
            "diagnostics": {
                "mode": "query_anchor",
                "embedding_model": self.embedding_model,
                "query_max_tokens": self.query_max_tokens,
                "original_query_tokens_estimated": self._count_tokens(original_query),
                "reduced_query_tokens_estimated": self._count_tokens(reduced_query),
            },
        }

    def reduce_query_text(
        self,
        query_text: str,
    ) -> str:
        """
        Reduce query text to query_max_tokens by preserving sentence order.

        This is deterministic. It removes sentences beyond the budget.
        It does not call an LLM.
        """
        clean = str(query_text or "").strip()
        if not clean:
            return ""

        if self._count_tokens(clean) <= self.query_max_tokens:
            return clean

        sentences = self._split_sentences(clean)

        if not sentences:
            return clean[: max(1, self.query_max_tokens * 4)].strip()

        selected: list[str] = []
        used_tokens = 0

        for sentence in sentences:
            sentence = str(sentence or "").strip()
            if not sentence:
                continue

            sentence_tokens = self._count_tokens(sentence)

            if used_tokens + sentence_tokens > self.query_max_tokens:
                continue

            selected.append(sentence)
            used_tokens += sentence_tokens

        if selected:
            return " ".join(selected).strip()

        return sentences[0][: max(1, self.query_max_tokens * 4)].strip()

    def _embed_query(
        self,
        query_text: str,
    ) -> Vector:
        vectors = self._embedder.embed([query_text])
        vector = vectors[0]

        if hasattr(vector, "tolist"):
            vector = vector.tolist()

        return [float(value) for value in vector]

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        clean = str(text or "").strip()
        if not clean:
            return []

        clean = re.sub(r"\n{2,}", "\n", clean)
        rough_parts = re.split(r"(?<=[.!?])\s+|\n+", clean)

        sentences: list[str] = []
        for part in rough_parts:
            item = str(part or "").strip()
            if item:
                sentences.append(item)

        if not sentences and clean:
            sentences.append(clean)

        return sentences

    @staticmethod
    def _count_tokens(text: str) -> int:
        clean = str(text or "")
        if not clean:
            return 0

        try:
            import tiktoken  # type: ignore

            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(clean))
        except Exception:
            return max(1, math.ceil(len(clean) / 4))
```

### ~\ragstream\memory\compression\memory_sentence_reducer.py
```python
# ragstream/memory/compression/memory_sentence_reducer.py
# -*- coding: utf-8 -*-
"""
MemorySentenceReducer
=====================

Shared deterministic Q/A reducer for memory compression.

Current use:
- ActiveRetrievalBrief creation uses centroid-anchor reduction.

Future use:
- Retrieval-time memory compression can use query-anchor reduction.

Core idea:
- split Q and A into sentence windows
- always embed Q/A windows
- score windows against an anchor vector
- remove highly redundant windows
- respect Q/A token budget
- restore original sentence order

Important:
- The output keeps Q_vectors and A_vectors.
- If no reduction happens, these vectors represent all Q/A windows.
- If reduction happens, these vectors represent only surviving windows.
"""

from __future__ import annotations

import math
import re

from dataclasses import dataclass
from typing import Any

from ragstream.ingestion.embedder import Embedder
from ragstream.textforge.RagLog import LogDeveloper as _logger_dev
DEV_LOG_ENABLED = False

def logger_dev(*args, **kwargs):
    if DEV_LOG_ENABLED:
        return _logger_dev(*args, **kwargs)
    return None

Vector = list[float]


@dataclass
class ReducedQA:
    reduced_question: str
    reduced_answer: str
    question_vectors: list[Vector]
    answer_vectors: list[Vector]
    diagnostics: dict[str, Any]


class MemorySentenceReducer:
    def __init__(
        self,
        *,
        max_tokens_total: int = 3000,
        question_max_tokens: int = 1000,
        window_size_sentences: int = 3,
        window_overlap_sentences: int = 1,
        redundancy_threshold: float = 0.92,
        embedding_model: str = "text-embedding-3-small",
    ) -> None:
        self.max_tokens_total = int(max_tokens_total)
        self.question_max_tokens = int(question_max_tokens)
        self.window_size_sentences = int(window_size_sentences)
        self.window_overlap_sentences = int(window_overlap_sentences)
        self.redundancy_threshold = float(redundancy_threshold)
        self.embedding_model = str(embedding_model)

        self._embedder = Embedder(model=self.embedding_model)

    def reduce_with_centroid(
        self,
        input_text: str,
        output_text: str,
    ) -> ReducedQA:
        """
        Query-independent reduction.

        The anchor vector is the centroid of all Q/A sentence-window vectors.
        Used for ActiveRetrievalBrief creation.
        """
        prepared = self._prepare_qa_windows_and_vectors(
            input_text=input_text,
            output_text=output_text,
        )

        all_vectors = prepared["question_vectors"] + prepared["answer_vectors"]

        if not all_vectors:
            return ReducedQA(
                reduced_question="",
                reduced_answer="",
                question_vectors=[],
                answer_vectors=[],
                diagnostics={
                    "mode": "centroid",
                    "reason": "no_vectors",
                },
            )

        anchor_vector = self._centroid(all_vectors)

        return self._reduce_prepared(
            input_text=input_text,
            output_text=output_text,
            question_windows=prepared["question_windows"],
            answer_windows=prepared["answer_windows"],
            question_vectors=prepared["question_vectors"],
            answer_vectors=prepared["answer_vectors"],
            anchor_vector=anchor_vector,
            mode="centroid",
        )

    def reduce_with_anchor(
        self,
        input_text: str,
        output_text: str,
        anchor_vector: Vector,
    ) -> ReducedQA:
        """
        Anchor-based reduction.

        The anchor vector may be:
        - centroid vector, for query-independent reduction
        - query vector, for future retrieval-time compression
        """
        prepared = self._prepare_qa_windows_and_vectors(
            input_text=input_text,
            output_text=output_text,
        )

        return self._reduce_prepared(
            input_text=input_text,
            output_text=output_text,
            question_windows=prepared["question_windows"],
            answer_windows=prepared["answer_windows"],
            question_vectors=prepared["question_vectors"],
            answer_vectors=prepared["answer_vectors"],
            anchor_vector=anchor_vector,
            mode="external_anchor",
        )

    def _prepare_qa_windows_and_vectors(
        self,
        *,
        input_text: str,
        output_text: str,
    ) -> dict[str, Any]:
        """
        Always vectorize Q and A windows.

        Reason:
        - Even if no deterministic reduction is needed, the vectors are useful
          for the later ActiveBrief relevance gate.
        - This avoids paying again to embed the same Q/A.
        """
        question_windows = self._build_sentence_windows(input_text)
        answer_windows = self._build_sentence_windows(output_text)

        question_vectors = self._embed_texts([item["text"] for item in question_windows])
        answer_vectors = self._embed_texts([item["text"] for item in answer_windows])

        return {
            "question_windows": question_windows,
            "answer_windows": answer_windows,
            "question_vectors": question_vectors,
            "answer_vectors": answer_vectors,
        }

    def _reduce_prepared(
        self,
        *,
        input_text: str,
        output_text: str,
        question_windows: list[dict[str, Any]],
        answer_windows: list[dict[str, Any]],
        question_vectors: list[Vector],
        answer_vectors: list[Vector],
        anchor_vector: Vector,
        mode: str,
    ) -> ReducedQA:
        input_tokens = self._count_tokens(input_text)
        output_tokens = self._count_tokens(output_text)

        q_budget, a_budget = self._allocate_qa_budget(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        reduced_question, surviving_q_vectors, q_diag = self._reduce_side(
            text=input_text,
            windows=question_windows,
            vectors=question_vectors,
            anchor_vector=anchor_vector,
            token_budget=q_budget,
            side="question",
        )

        reduced_answer, surviving_a_vectors, a_diag = self._reduce_side(
            text=output_text,
            windows=answer_windows,
            vectors=answer_vectors,
            anchor_vector=anchor_vector,
            token_budget=a_budget,
            side="answer",
        )

        diagnostics = {
            "mode": mode,
            "embedding_model": self.embedding_model,
            "max_tokens_total": self.max_tokens_total,
            "question_max_tokens": self.question_max_tokens,
            "input_tokens_estimated": input_tokens,
            "output_tokens_estimated": output_tokens,
            "question_budget": q_budget,
            "answer_budget": a_budget,
            "question_vector_count_before": len(question_vectors),
            "answer_vector_count_before": len(answer_vectors),
            "question_vector_count_after": len(surviving_q_vectors),
            "answer_vector_count_after": len(surviving_a_vectors),
            "question": q_diag,
            "answer": a_diag,
        }

        logger_dev(
            "MemorySentenceReducer result\n"
            + self._safe_json_dump(
                {
                    "diagnostics": diagnostics,
                    "reduced_question": reduced_question,
                    "reduced_answer": reduced_answer,
                }
            ),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return ReducedQA(
            reduced_question=reduced_question,
            reduced_answer=reduced_answer,
            question_vectors=surviving_q_vectors,
            answer_vectors=surviving_a_vectors,
            diagnostics=diagnostics,
        )

    def _allocate_qa_budget(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
    ) -> tuple[int, int]:
        total_tokens = max(1, int(input_tokens) + int(output_tokens))

        proportional_q = round(self.max_tokens_total * (int(input_tokens) / total_tokens))
        q_budget = min(int(proportional_q), self.question_max_tokens)

        if input_tokens > 0 and q_budget <= 0:
            q_budget = min(self.question_max_tokens, self.max_tokens_total)

        a_budget = max(0, self.max_tokens_total - q_budget)

        return q_budget, a_budget

    def _reduce_side(
        self,
        *,
        text: str,
        windows: list[dict[str, Any]],
        vectors: list[Vector],
        anchor_vector: Vector,
        token_budget: int,
        side: str,
    ) -> tuple[str, list[Vector], dict[str, Any]]:
        clean_text = str(text or "").strip()
        if not clean_text or token_budget <= 0:
            return "", [], {
                "side": side,
                "reason": "empty_or_zero_budget",
                "token_budget": token_budget,
            }

        original_tokens = self._count_tokens(clean_text)

        if original_tokens <= token_budget:
            # No reduction needed.
            # Still return all vectors, because the relevance gate needs them.
            return clean_text, list(vectors), {
                "side": side,
                "reason": "already_below_budget",
                "original_tokens_estimated": original_tokens,
                "token_budget": token_budget,
                "window_count": len(windows),
                "surviving_vector_count": len(vectors),
            }

        sentences = self._split_sentences(clean_text)

        if not windows or not vectors:
            return clean_text[: max(1, token_budget * 4)], [], {
                "side": side,
                "reason": "no_windows_or_vectors_fallback",
                "original_tokens_estimated": original_tokens,
                "token_budget": token_budget,
            }

        scored: list[dict[str, Any]] = []
        max_count = min(len(windows), len(vectors))

        for idx in range(max_count):
            item = windows[idx]
            vector = vectors[idx]

            scored.append(
                {
                    "window_index": idx,
                    "score": self._cosine(vector, anchor_vector),
                    "text": item["text"],
                    "sentence_indexes": item["sentence_indexes"],
                    "vector": vector,
                    "tokens": self._count_tokens(item["text"]),
                }
            )

        scored.sort(key=lambda item: item["score"], reverse=True)

        selected: list[dict[str, Any]] = []
        selected_sentence_indexes: set[int] = set()
        used_window_tokens = 0

        for candidate in scored:
            if used_window_tokens + int(candidate["tokens"]) > token_budget:
                continue

            if self._is_redundant(candidate["vector"], selected):
                continue

            selected.append(candidate)
            used_window_tokens += int(candidate["tokens"])
            selected_sentence_indexes.update(candidate["sentence_indexes"])

        if not selected and scored:
            first = scored[0]
            selected.append(first)
            selected_sentence_indexes.update(first["sentence_indexes"])

        reduced_sentences: list[str] = []
        used_tokens = 0

        for sentence_index in sorted(selected_sentence_indexes):
            if sentence_index < 0 or sentence_index >= len(sentences):
                continue

            sentence = sentences[sentence_index]
            sentence_tokens = self._count_tokens(sentence)

            if used_tokens + sentence_tokens > token_budget:
                continue

            reduced_sentences.append(sentence)
            used_tokens += sentence_tokens

        reduced_text = " ".join(reduced_sentences).strip()

        if not reduced_text and selected:
            # Last-resort fallback:
            # If one sentence is longer than the budget, keep a bounded text slice.
            reduced_text = str(selected[0].get("text", "") or "")[: max(1, token_budget * 4)].strip()

        surviving_vectors = [list(item["vector"]) for item in selected]

        return reduced_text, surviving_vectors, {
            "side": side,
            "reason": "reduced",
            "original_tokens_estimated": original_tokens,
            "token_budget": token_budget,
            "window_count": len(windows),
            "selected_window_count": len(selected),
            "selected_sentence_count": len(reduced_sentences),
            "surviving_vector_count": len(surviving_vectors),
            "reduced_tokens_estimated": self._count_tokens(reduced_text),
        }

    def _is_redundant(
        self,
        candidate_vector: Vector,
        selected: list[dict[str, Any]],
    ) -> bool:
        for item in selected:
            existing_vector = item.get("vector") or []
            if self._cosine(candidate_vector, existing_vector) >= self.redundancy_threshold:
                return True
        return False

    def _build_sentence_windows(self, text: str) -> list[dict[str, Any]]:
        sentences = self._split_sentences(text)
        return self._build_windows_from_sentences(sentences)

    def _build_windows_from_sentences(
        self,
        sentences: list[str],
    ) -> list[dict[str, Any]]:
        if not sentences:
            return []

        window_size = max(1, self.window_size_sentences)
        overlap = max(0, min(self.window_overlap_sentences, window_size - 1))
        step = max(1, window_size - overlap)

        windows: list[dict[str, Any]] = []

        start = 0
        while start < len(sentences):
            end = min(len(sentences), start + window_size)
            indexes = list(range(start, end))
            text = " ".join(sentences[start:end]).strip()

            if text:
                windows.append(
                    {
                        "text": text,
                        "sentence_indexes": indexes,
                    }
                )

            if end >= len(sentences):
                break

            start += step

        return windows

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        clean = str(text or "").strip()
        if not clean:
            return []

        clean = re.sub(r"\n{2,}", "\n", clean)
        rough_parts = re.split(r"(?<=[.!?])\s+|\n+", clean)

        sentences: list[str] = []
        for part in rough_parts:
            item = str(part or "").strip()
            if item:
                sentences.append(item)

        if not sentences and clean:
            sentences.append(clean)

        return sentences

    def _embed_texts(self, texts: list[str]) -> list[Vector]:
        clean_texts = [str(text or "").strip() for text in texts]
        clean_texts = [text for text in clean_texts if text]

        if not clean_texts:
            return []

        vectors = self._embedder.embed(clean_texts)
        return [list(vector) for vector in vectors]

    @staticmethod
    def _centroid(vectors: list[Vector]) -> Vector:
        if not vectors:
            return []

        dim = len(vectors[0])
        if dim <= 0:
            return []

        sums = [0.0 for _ in range(dim)]
        count = 0

        for vector in vectors:
            if len(vector) != dim:
                continue

            for i, value in enumerate(vector):
                sums[i] += float(value)

            count += 1

        if count <= 0:
            return []

        return [value / float(count) for value in sums]

    @staticmethod
    def _cosine(a: Vector, b: Vector) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0

        dot = 0.0
        norm_a = 0.0
        norm_b = 0.0

        for x, y in zip(a, b):
            fx = float(x)
            fy = float(y)
            dot += fx * fy
            norm_a += fx * fx
            norm_b += fy * fy

        if norm_a <= 0.0 or norm_b <= 0.0:
            return 0.0

        return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))

    @staticmethod
    def _count_tokens(text: str) -> int:
        clean = str(text or "")
        if not clean:
            return 0

        try:
            import tiktoken  # type: ignore

            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(clean))
        except Exception:
            return max(1, math.ceil(len(clean) / 4))

    @staticmethod
    def _safe_json_dump(data: Any) -> str:
        import json

        try:
            return json.dumps(data, ensure_ascii=False, indent=2, default=str)
        except Exception:
            return repr(data)
```

### ~\ragstream\memory\importers\chatgpt_shared_link_importer.py
```python
# ragstream/memory/importers/chatgpt_shared_link_importer.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from ragstream.memory.importers.chatgpt_shared_link_importer_helpers import (
    assign_memory_brief_to_records,
    build_memory_records,
    ingest_imported_history,
    messages_to_pairs,
    persist_records_as_new_history,
    read_chatgpt_shared_link,
    validate_shared_url,
    validate_title,
)


def import_chatgpt_shared_link(
    *,
    shared_url: str,
    title: str,
    memory_manager: Any,
    memory_ingestion_manager: Any | None = None,
    memory_brief: str = "",
    memory_brief_title: str = "",
    active_project_name: str | None = None,
    embedded_files_snapshot: list[str] | None = None,
    headless: bool = True,
    timeout_ms: int = 60000,
    wait_after_load_ms: int = 3000,
    wait_for_stable_messages: bool = True,
) -> dict[str, Any]:
    """
    Import one public ChatGPT shared conversation into RAGstream Memory.

    This main file intentionally stays small:
    - validate input
    - read the shared page
    - convert messages into Q/A memory pairs
    - build MemoryRecord objects
    - persist them as a normal memory history
    - optionally ingest vectors
    """

    # 1. Validate user-facing import inputs before opening the browser.
    clean_url = validate_shared_url(shared_url)
    clean_title = validate_title(title)
    clean_memory_brief = str(memory_brief or "").strip()
    clean_memory_brief_title = str(memory_brief_title or "").strip() or clean_title

    # 2. Open the public ChatGPT shared page and extract conversation messages.
    page_data = read_chatgpt_shared_link(
        clean_url,
        headless=headless,
        timeout_ms=timeout_ms,
        wait_after_load_ms=wait_after_load_ms,
        wait_for_stable_messages=wait_for_stable_messages,
    )

    # 3. Convert extracted user/assistant messages into RAGstream Q/A pairs.
    pairs = messages_to_pairs(
        messages=page_data.get("messages", []),
        raw_text=str(page_data.get("raw_text", "") or ""),
        shared_url=clean_url,
        title=clean_title,
    )

    if not pairs:
        raise ValueError("No importable conversation text was found in the shared link.")

    # 4. Build normal MemoryRecord objects without changing MemoryRecord itself.
    records = build_memory_records(
        pairs=pairs,
        shared_url=clean_url,
        active_project_name=active_project_name,
        embedded_files_snapshot=embedded_files_snapshot or [],
    )

    # 5. Attach the optional MemoryBrief to all imported records as shared context.
    if clean_memory_brief:
        assign_memory_brief_to_records(
            records=records,
            memory_brief=clean_memory_brief,
            memory_brief_title=clean_memory_brief_title,
        )

    # 6. Persist the imported records as a new ordinary RAGstream memory history.
    persist_records_as_new_history(
        memory_manager=memory_manager,
        title=clean_title,
        records=records,
    )

    # 7. Optionally ingest the new memory history into the memory vector store.
    vector_ingestion_result = ingest_imported_history(
        memory_ingestion_manager=memory_ingestion_manager,
    )

    # 8. Return a compact import report for the Streamlit action/status layer.
    return {
        "success": True,
        "shared_url": clean_url,
        "title": memory_manager.title,
        "file_id": memory_manager.file_id,
        "filename_ragmem": memory_manager.filename_ragmem,
        "filename_meta": memory_manager.filename_meta,
        "record_count": len(records),
        "pair_count": len(pairs),
        "message_count": len(page_data.get("messages", []) or []),
        "raw_text_chars": len(str(page_data.get("raw_text", "") or "")),
        "extraction_method": page_data.get("extraction_method", ""),
        "memory_brief_assigned": bool(clean_memory_brief),
        "vector_ingestion": vector_ingestion_result,
    }
```

### ~\ragstream\memory\importers\chatgpt_shared_link_importer_helpers.py
```python
# ragstream/memory/importers/chatgpt_shared_link_importer_helpers.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Any

from ragstream.memory.memory_record import MemoryRecord


CHATGPT_SHARED_LINK_PATTERN = re.compile(
    r"^https://chatgpt\.com/share/[A-Za-z0-9_-]+(?:\?.*)?$"
)

VALID_CHATGPT_ROLES = {"user", "assistant"}


# -----------------------------------------------------------------------------
# Public helper API used by chatgpt_shared_link_importer.py
# -----------------------------------------------------------------------------


def read_chatgpt_shared_link(
    shared_url: str,
    *,
    headless: bool = True,
    timeout_ms: int = 60000,
    wait_after_load_ms: int = 3000,
    wait_for_stable_messages: bool = True,
) -> dict[str, Any]:
    """
    Read a public ChatGPT shared-link page.

    Preferred extraction:
    - DOM message blocks converted to cleaner Markdown.
    - Code blocks are reconstructed as fenced code frames.

    Fallback extraction:
    - embedded page data.
    - full body text if structured extraction fails.
    """
    clean_url = validate_shared_url(shared_url)

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError(
            "Playwright is required for ChatGPT shared-link import. "
            "Install it through requirements.txt and run: "
            "python -m playwright install chromium"
        ) from exc

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            page = browser.new_page()

            _goto_with_retry(
                page,
                clean_url,
                timeout_ms=timeout_ms,
                attempts=3,
                wait_between_attempts_ms=2500,
            )

            try:
                page.wait_for_selector(
                    "[data-message-author-role]",
                    timeout=min(20000, int(timeout_ms)),
                )
            except PlaywrightTimeoutError:
                pass

            if int(wait_after_load_ms) > 0:
                page.wait_for_timeout(int(wait_after_load_ms))

            if wait_for_stable_messages:
                _scroll_and_wait_until_messages_are_stable(
                    page,
                    timeout_ms=min(25000, int(timeout_ms)),
                    poll_ms=500,
                    stable_rounds=4,
                    max_scroll_rounds=8,
                )

            dom_messages = _extract_dom_messages_as_markdown(page)
            structured_messages = _extract_structured_messages(page)
            raw_text = _extract_body_text(page)

            selected_messages, extraction_method = _select_best_message_source(
                dom_messages=dom_messages,
                structured_messages=structured_messages,
            )

            if selected_messages:
                return {
                    "shared_url": clean_url,
                    "messages": selected_messages,
                    "raw_text": raw_text,
                    "extraction_method": extraction_method,
                }

            return {
                "shared_url": clean_url,
                "messages": [],
                "raw_text": raw_text,
                "extraction_method": "body_text_fallback",
            }

        finally:
            browser.close()


def messages_to_pairs(
    *,
    messages: list[dict[str, str]],
    raw_text: str,
    shared_url: str,
    title: str,
) -> list[dict[str, str]]:
    """Convert ordered user/assistant messages into Q/A memory pairs."""
    pairs: list[dict[str, str]] = []
    pending_user_parts: list[str] = []
    pending_assistant_parts: list[str] = []

    def flush_pair() -> None:
        nonlocal pending_user_parts
        nonlocal pending_assistant_parts

        input_text = "\n\n".join(pending_user_parts).strip()
        output_text = "\n\n".join(pending_assistant_parts).strip()

        if input_text and output_text:
            pairs.append(
                {
                    "input_text": input_text,
                    "output_text": output_text,
                }
            )

        pending_user_parts = []
        pending_assistant_parts = []

    for message in messages or []:
        role = str(message.get("role", "") or "").strip().lower()
        text = clean_text(str(message.get("text", "") or ""))

        if role not in VALID_CHATGPT_ROLES or not text:
            continue

        if role == "user":
            if pending_user_parts and pending_assistant_parts:
                flush_pair()
            pending_user_parts.append(text)
            continue

        if role == "assistant" and pending_user_parts:
            pending_assistant_parts.append(text)

    if pending_user_parts and pending_assistant_parts:
        flush_pair()

    if pairs:
        return pairs

    clean_raw_text = clean_text(raw_text)
    if clean_raw_text:
        return [
            {
                "input_text": (
                    "Imported ChatGPT shared conversation\n"
                    f"Title: {title}\n"
                    f"Source URL: {shared_url}"
                ),
                "output_text": clean_raw_text,
            }
        ]

    return []


def build_memory_records(
    *,
    pairs: list[dict[str, str]],
    shared_url: str,
    active_project_name: str | None,
    embedded_files_snapshot: list[str],
) -> list[MemoryRecord]:
    """Build normal MemoryRecord objects from imported Q/A pairs."""
    records: list[MemoryRecord] = []
    previous_record_id: str | None = None
    source = f"chatgpt_shared_link:{shared_url}"

    for pair in pairs:
        input_text = clean_text(str(pair.get("input_text", "") or ""))
        output_text = clean_text(str(pair.get("output_text", "") or ""))

        if not input_text or not output_text:
            continue

        record = MemoryRecord(
            input_text=input_text,
            output_text=output_text,
            source=source,
            parent_id=previous_record_id,
            tag="Green",
            user_keywords=["chatgpt_shared_link"],
            active_project_name=active_project_name,
            embedded_files_snapshot=embedded_files_snapshot,
            retrieval_source_mode="QA",
            direct_recall_key="",
            active_retrieval_brief_title="",
            active_retrieval_brief="",
            active_retrieval_brief_contributor_ids=[],
        )

        records.append(record)
        previous_record_id = record.record_id

    return records


def assign_memory_brief_to_records(
    *,
    records: list[MemoryRecord],
    memory_brief: str,
    memory_brief_title: str,
) -> None:
    """Attach one shared MemoryBrief to all imported records."""
    clean_memory_brief = clean_text(memory_brief)
    clean_memory_brief_title = clean_text(memory_brief_title)

    if not clean_memory_brief:
        return

    contributor_ids = [record.record_id for record in records]
    for record in records:
        record.update_active_retrieval_brief(
            active_retrieval_brief=clean_memory_brief,
            contributor_ids=contributor_ids,
            active_retrieval_brief_title=clean_memory_brief_title,
        )


def persist_records_as_new_history(
    *,
    memory_manager: Any,
    title: str,
    records: list[MemoryRecord],
) -> None:
    """Persist imported records as a new ordinary RAGstream memory history."""
    if memory_manager is None:
        raise ValueError("memory_manager is required.")

    if not records:
        raise ValueError("No MemoryRecord objects were created.")

    memory_manager.start_new_history(title)
    memory_manager.records = list(records)
    memory_manager.pending_activebrief_topic_buffer = {}

    memory_manager.files_root.mkdir(parents=True, exist_ok=True)

    with memory_manager.ragmem_path.open("w", encoding="utf-8") as f:
        for record in memory_manager.records:
            f.write(record.to_ragmem_block())
            f.write("\n")

    memory_manager.b_file_created = True
    memory_manager.save_metainfo()
    memory_manager.refresh_sqlite_index()


def ingest_imported_history(*, memory_ingestion_manager: Any | None) -> dict[str, Any] | None:
    """Run vector ingestion for the imported history when the ingestion layer exists."""
    if memory_ingestion_manager is None:
        return None

    return memory_ingestion_manager.ingest_all()


def validate_shared_url(shared_url: str) -> str:
    """Validate and normalize a ChatGPT shared conversation URL."""
    clean_url = str(shared_url or "").strip()

    if not clean_url:
        raise ValueError("ChatGPT shared link must not be empty.")

    if not CHATGPT_SHARED_LINK_PATTERN.match(clean_url):
        raise ValueError(
            "ChatGPT shared link must match: https://chatgpt.com/share/<conversation-id>"
        )

    return clean_url


def validate_title(title: str) -> str:
    """Validate and normalize the memory history title."""
    clean_title = str(title or "").strip()

    if not clean_title:
        raise ValueError("Import title must not be empty.")

    return clean_title


# -----------------------------------------------------------------------------
# Playwright navigation / extraction internals
# -----------------------------------------------------------------------------


def _goto_with_retry(
    page: Any,
    url: str,
    *,
    timeout_ms: int = 60000,
    attempts: int = 3,
    wait_between_attempts_ms: int = 2500,
) -> None:
    """Navigate with retry for temporary browser/network errors."""
    last_error: Exception | None = None

    for attempt in range(1, int(attempts) + 1):
        try:
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=int(timeout_ms),
            )
            return

        except Exception as exc:
            last_error = exc
            message = str(exc)

            retryable = any(
                token in message
                for token in (
                    "ERR_NETWORK_CHANGED",
                    "ERR_TIMED_OUT",
                    "ERR_CONNECTION_RESET",
                    "ERR_INTERNET_DISCONNECTED",
                    "net::ERR_NETWORK_CHANGED",
                    "net::ERR_TIMED_OUT",
                    "net::ERR_CONNECTION_RESET",
                    "net::ERR_INTERNET_DISCONNECTED",
                )
            )

            if not retryable or attempt >= int(attempts):
                raise

            page.wait_for_timeout(int(wait_between_attempts_ms))

    if last_error is not None:
        raise last_error


def _scroll_and_wait_until_messages_are_stable(
    page: Any,
    *,
    timeout_ms: int = 25000,
    poll_ms: int = 500,
    stable_rounds: int = 4,
    max_scroll_rounds: int = 8,
) -> None:
    """Scroll gently and wait until visible message count stops increasing."""
    try:
        start_ms = int(page.evaluate("Date.now()"))
    except Exception:
        return

    previous_count = -1
    stable_count = 0
    scroll_round = 0

    while True:
        try:
            now_ms = int(page.evaluate("Date.now()"))
        except Exception:
            return

        if now_ms - start_ms > int(timeout_ms):
            return

        try:
            current_count = int(
                page.evaluate(
                    '() => document.querySelectorAll("[data-message-author-role]").length'
                )
            )
        except Exception:
            current_count = 0

        if current_count > 0 and current_count == previous_count:
            stable_count += 1
        else:
            stable_count = 0
            previous_count = current_count

        if current_count > 0 and stable_count >= int(stable_rounds):
            return

        if scroll_round < int(max_scroll_rounds):
            try:
                page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                pass
            scroll_round += 1

        page.wait_for_timeout(int(poll_ms))


def _extract_dom_messages_as_markdown(page: Any) -> list[dict[str, str]]:
    """Extract visible message DOM and reconstruct cleaner Markdown/code frames."""
    script = r'''
    () => {
        const nodes = Array.from(document.querySelectorAll("[data-message-author-role]"));

        function normalizeLanguage(value) {
            const raw = String(value || "").trim().toLowerCase();
            if (!raw) return "";

            const cleaned = raw
                .replace(/^language-/, "")
                .replace(/^lang-/, "")
                .replace(/[^a-z0-9#+.-]/g, "");

            const aliases = {
                py: "python",
                python3: "python",
                sh: "bash",
                shell: "bash",
                zsh: "bash",
                ps1: "powershell",
                yml: "yaml",
                js: "javascript",
                ts: "typescript",
                md: "markdown",
                docker: "dockerfile"
            };

            return aliases[cleaned] || cleaned;
        }

        function detectLanguage(codeText, preNode, codeNode) {
            const candidates = [];

            if (codeNode) candidates.push(codeNode.getAttribute("data-language"));
            if (codeNode) candidates.push(codeNode.getAttribute("class"));
            if (preNode) candidates.push(preNode.getAttribute("data-language"));
            if (preNode) candidates.push(preNode.getAttribute("class"));

            for (const candidate of candidates) {
                const text = String(candidate || "");
                const match = text.match(/(?:language-|lang-)([a-zA-Z0-9#+.-]+)/);
                if (match) return normalizeLanguage(match[1]);
                const direct = normalizeLanguage(text);
                if (direct && direct.length <= 20) return direct;
            }

            const code = String(codeText || "").trim();

            if (/^FROM\s+\S+/m.test(code) || /^RUN\s+/m.test(code) || /^CMD\s+\[/m.test(code)) {
                return "dockerfile";
            }
            if (/^\s*def\s+\w+\s*\(/m.test(code) || /^\s*class\s+\w+/m.test(code) || /^\s*import\s+\w+/m.test(code) || /^\s*from\s+\w+/m.test(code)) {
                return "python";
            }
            if (/^\s*\{[\s\S]*\}\s*$/.test(code) || /^\s*\[[\s\S]*\]\s*$/.test(code)) {
                return "json";
            }
            if (/^\s*<\?xml/m.test(code) || /^\s*<[^>]+>/m.test(code)) {
                return "xml";
            }
            if (/^\s*(git|python|pip|pytest|streamlit|docker|aws|cd|ls|mkdir|rm|cp|mv)\b/m.test(code)) {
                return "bash";
            }
            if (/^\s*SELECT\s+/im.test(code) || /^\s*INSERT\s+/im.test(code) || /^\s*UPDATE\s+/im.test(code)) {
                return "sql";
            }

            return "";
        }

        function labelForLanguage(language) {
            if (!language) return "Code frame";

            const labels = {
                python: "Code frame: Python",
                bash: "Code frame: Bash",
                powershell: "Code frame: PowerShell",
                json: "Code frame: JSON",
                yaml: "Code frame: YAML",
                javascript: "Code frame: JavaScript",
                typescript: "Code frame: TypeScript",
                dockerfile: "Code frame: Dockerfile",
                markdown: "Code frame: Markdown",
                html: "Code frame: HTML",
                css: "Code frame: CSS",
                xml: "Code frame: XML",
                sql: "Code frame: SQL"
            };

            return labels[language] || `Code frame: ${language.charAt(0).toUpperCase()}${language.slice(1)}`;
        }

        function removeUiNoise(root) {
            const selectors = [
                "button",
                "svg",
                "[role='button']",
                "[aria-label*='Copy']",
                "[data-testid*='copy']",
                ".sr-only"
            ];

            for (const selector of selectors) {
                for (const item of Array.from(root.querySelectorAll(selector))) {
                    item.remove();
                }
            }
        }

        function convertInlineCode(root) {
            for (const codeNode of Array.from(root.querySelectorAll("code"))) {
                if (codeNode.closest("pre")) continue;

                const text = codeNode.innerText || codeNode.textContent || "";
                if (!text.trim()) continue;

                codeNode.replaceWith(document.createTextNode("`" + text.trim() + "`"));
            }
        }

        function convertCodeBlocks(root) {
            for (const preNode of Array.from(root.querySelectorAll("pre"))) {
                const codeNode = preNode.querySelector("code");
                const codeText = (codeNode ? codeNode.innerText : preNode.innerText) || "";
                const cleanCode = codeText.replace(/\n*Copy code\n*/gi, "").trim();

                if (!cleanCode) {
                    preNode.remove();
                    continue;
                }

                const language = detectLanguage(cleanCode, preNode, codeNode);
                const label = labelForLanguage(language);
                const fenceLanguage = language || "";
                const markdownBlock = `\n\n${label}\n\n\`\`\`${fenceLanguage}\n${cleanCode}\n\`\`\`\n\n`;

                preNode.replaceWith(document.createTextNode(markdownBlock));
            }
        }

        return nodes.map((node) => {
            const clone = node.cloneNode(true);
            removeUiNoise(clone);
            convertCodeBlocks(clone);
            convertInlineCode(clone);

            return {
                role: node.getAttribute("data-message-author-role") || "",
                text: clone.innerText || clone.textContent || ""
            };
        });
    }
    '''

    try:
        raw_messages = page.evaluate(script)
    except Exception:
        raw_messages = []

    return _normalize_messages(raw_messages)


def _extract_structured_messages(page: Any) -> list[dict[str, str]]:
    """Extract fallback messages from embedded JSON-like page state."""
    script = r'''
    () => {
        const roots = [];

        function safePush(value) {
            if (value !== undefined && value !== null) roots.push(value);
        }

        safePush(window.__NEXT_DATA__);
        safePush(window.__remixContext);
        safePush(window.__reactRouterContext);
        safePush(window.__NUXT__);
        safePush(window.__APOLLO_STATE__);

        for (const scriptNode of Array.from(document.querySelectorAll("script"))) {
            const text = scriptNode.textContent || "";
            const trimmed = text.trim();
            if (!trimmed) continue;

            if (scriptNode.type === "application/json" || trimmed.startsWith("{") || trimmed.startsWith("[")) {
                try { safePush(JSON.parse(trimmed)); } catch (e) {}
            }
        }

        const out = [];
        const seen = new Set();

        function contentToText(content) {
            if (!content) return "";
            if (typeof content === "string") return content;
            if (Array.isArray(content)) return content.map(contentToText).filter(Boolean).join("\n");
            if (typeof content !== "object") return "";
            if (typeof content.text === "string") return content.text;
            if (typeof content.value === "string") return content.value;
            if (Array.isArray(content.parts)) return content.parts.map(contentToText).filter(Boolean).join("\n");
            if (Array.isArray(content.content)) return content.content.map(contentToText).filter(Boolean).join("\n");
            if (typeof content.content === "string") return content.content;
            return "";
        }

        function visit(value) {
            if (!value || typeof value !== "object") return;
            if (seen.has(value)) return;
            seen.add(value);

            const role = value?.author?.role || value?.message?.author?.role || value?.node?.message?.author?.role || "";
            const message = value?.message || value?.node?.message || value;
            const content = message?.content || message?.text || value?.content || value?.text || null;
            const text = contentToText(content);

            if ((role === "user" || role === "assistant") && text && text.trim()) {
                out.push({role, text: text.trim()});
            }

            if (Array.isArray(value)) {
                for (const item of value) visit(item);
            } else {
                for (const key of Object.keys(value)) visit(value[key]);
            }
        }

        for (const root of roots) visit(root);
        return out;
    }
    '''

    try:
        raw_messages = page.evaluate(script)
    except Exception:
        raw_messages = []

    return _normalize_messages(raw_messages)


def _select_best_message_source(
    *,
    dom_messages: list[dict[str, str]],
    structured_messages: list[dict[str, str]],
) -> tuple[list[dict[str, str]], str]:
    """Prefer DOM Markdown when message coverage is comparable; otherwise use larger source."""
    dom_count = len(dom_messages or [])
    structured_count = len(structured_messages or [])

    if dom_count <= 0 and structured_count <= 0:
        return [], ""

    if dom_count >= structured_count:
        return dom_messages, "dom_markdown_codeframe"

    if dom_count >= 2 and structured_count - dom_count <= 2:
        return dom_messages, "dom_markdown_codeframe"

    return structured_messages, "embedded_author_role"


def _extract_body_text(page: Any) -> str:
    try:
        text = page.locator("body").inner_text(timeout=10000)
    except Exception:
        return ""

    return clean_text(text)


def _normalize_messages(raw_messages: Any) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []

    for item in raw_messages or []:
        if not isinstance(item, dict):
            continue

        role = str(item.get("role", "") or "").strip().lower()
        text = clean_text(str(item.get("text", "") or ""))

        if role not in VALID_CHATGPT_ROLES:
            continue

        if not text:
            continue

        messages.append(
            {
                "role": role,
                "text": text,
            }
        )

    return _dedupe_consecutive_messages(messages)


def _dedupe_consecutive_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Remove only consecutive duplicates; repeated later turns remain valid."""
    result: list[dict[str, str]] = []
    previous_key: tuple[str, str] | None = None

    for message in messages:
        role = str(message.get("role", "") or "").strip().lower()
        text = clean_text(str(message.get("text", "") or ""))

        if role not in VALID_CHATGPT_ROLES or not text:
            continue

        key = (role, text)
        if key == previous_key:
            continue

        result.append({"role": role, "text": text})
        previous_key = key

    return result


def clean_text(text: str) -> str:
    """Normalize imported text and remove common shared-page UI noise."""
    value = str(text or "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")

    noise_lines = {
        "copy",
        "copy code",
        "copied",
        "edit",
        "share",
        "regenerate",
        "open in app",
        "chatgpt can make mistakes. check important info.",
    }

    cleaned_lines: list[str] = []
    for line in value.split("\n"):
        stripped = line.strip()
        if stripped.lower() in noise_lines:
            continue
        cleaned_lines.append(line)

    value = "\n".join(cleaned_lines)
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n[ \t]+", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()
```

### ~\ragstream\memory\ingestion\memory_chunker.py
```python
# ragstream/memory/memory_chunker.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import re

from typing import Any


class MemoryChunker:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config: dict[str, Any] = {
            "config_version": "memory_chunker_001",
            "target_tokens": 500,
            "max_tokens": 800,
            "question_anchor_tokens": 220,
        }
        self.config.update(config or {})

    def build_vector_entries(
        self,
        record: Any,
        *,
        file_id: str,
        filename_ragmem: str = "",
        filename_meta: str = "",
    ) -> list[dict[str, Any]]:
        ingestion_hash = self._build_ingestion_hash(record, file_id)

        entries: list[dict[str, Any]] = []

        question_anchor = self._build_question_anchor(record.input_text)
        record_handle_text = self._build_record_handle_text(record, question_anchor)

        entries.append(
            self._make_entry(
                file_id=file_id,
                filename_ragmem=filename_ragmem,
                filename_meta=filename_meta,
                record=record,
                role="record_handle",
                block_id="0000",
                position=0,
                text=record_handle_text,
                start_offset=0,
                end_offset=len(question_anchor),
                ingestion_hash=ingestion_hash,
            )
        )

        for position, block in enumerate(self._split_text(record.input_text), start=1):
            entries.append(
                self._make_entry(
                    file_id=file_id,
                    filename_ragmem=filename_ragmem,
                    filename_meta=filename_meta,
                    record=record,
                    role="question",
                    block_id=f"{position:04d}",
                    position=position,
                    text=block["text"],
                    start_offset=block["start_offset"],
                    end_offset=block["end_offset"],
                    ingestion_hash=ingestion_hash,
                )
            )

        for position, block in enumerate(self._split_text(record.output_text), start=1):
            entries.append(
                self._make_entry(
                    file_id=file_id,
                    filename_ragmem=filename_ragmem,
                    filename_meta=filename_meta,
                    record=record,
                    role="answer",
                    block_id=f"{position:04d}",
                    position=position,
                    text=block["text"],
                    start_offset=block["start_offset"],
                    end_offset=block["end_offset"],
                    ingestion_hash=ingestion_hash,
                )
            )

        return [entry for entry in entries if entry["document"].strip()]

    def _build_record_handle_text(self, record: Any, question_anchor: str) -> str:
        return "\n".join(
            [
                f"PROJECT: {record.active_project_name or ''}",
             #   f"TAG: {record.tag or ''}",
            #    f"USER_KEYWORDS: {self._join_list(record.user_keywords)}",
                f"YAKE_KEYWORDS: {self._join_list(record.auto_keywords)}",
                "QUESTION_ANCHOR:",
                question_anchor.strip(),
            ]
        ).strip()

    def _build_question_anchor(self, text: str) -> str:
        clean_text = (text or "").strip()
        if not clean_text:
            return ""

        max_tokens = int(self.config["question_anchor_tokens"])
        blocks = self._split_text(clean_text)

        if blocks:
            return self._truncate_by_tokens(blocks[0]["text"], max_tokens)

        return self._truncate_by_tokens(clean_text, max_tokens)

    def _split_text(self, text: str) -> list[dict[str, Any]]:
        if not (text or "").strip():
            return []

        target_tokens = int(self.config["target_tokens"])
        max_tokens = int(self.config["max_tokens"])

        units = self._semantic_units(text)
        blocks: list[dict[str, Any]] = []

        current_units: list[tuple[int, int, str]] = []
        current_tokens = 0

        for start, end, unit_text in units:
            unit_tokens = self._count_tokens(unit_text)

            if unit_tokens > max_tokens:
                if current_units:
                    blocks.append(self._units_to_block(current_units))
                    current_units = []
                    current_tokens = 0

                blocks.extend(self._hard_split(unit_text, base_offset=start, max_tokens=max_tokens))
                continue

            if current_units and current_tokens + unit_tokens > max_tokens:
                blocks.append(self._units_to_block(current_units))
                current_units = []
                current_tokens = 0

            current_units.append((start, end, unit_text))
            current_tokens += unit_tokens

            if current_tokens >= target_tokens:
                blocks.append(self._units_to_block(current_units))
                current_units = []
                current_tokens = 0

        if current_units:
            blocks.append(self._units_to_block(current_units))

        return blocks

    def _semantic_units(self, text: str) -> list[tuple[int, int, str]]:
        units: list[tuple[int, int, str]] = []

        paragraph_pattern = re.compile(r"\S(?:.*?\S)?(?=\n\s*\n|\Z)", re.DOTALL)

        for paragraph_match in paragraph_pattern.finditer(text):
            paragraph_text = paragraph_match.group(0)
            paragraph_start = paragraph_match.start()
            paragraph_end = paragraph_match.end()

            if self._count_tokens(paragraph_text) <= int(self.config["max_tokens"]):
                units.append((paragraph_start, paragraph_end, paragraph_text))
                continue

            sentence_pattern = re.compile(r"\S[^.!?\n]*(?:[.!?]+|$)", re.DOTALL)

            for sentence_match in sentence_pattern.finditer(paragraph_text):
                sentence_text = sentence_match.group(0).strip()
                if not sentence_text:
                    continue

                start = paragraph_start + sentence_match.start()
                end = paragraph_start + sentence_match.end()
                units.append((start, end, text[start:end]))

        if not units and text.strip():
            units.append((0, len(text), text.strip()))

        return units

    def _hard_split(
        self,
        text: str,
        *,
        base_offset: int,
        max_tokens: int,
    ) -> list[dict[str, Any]]:
        word_matches = list(re.finditer(r"\S+", text))
        blocks: list[dict[str, Any]] = []

        for i in range(0, len(word_matches), max_tokens):
            group = word_matches[i : i + max_tokens]
            if not group:
                continue

            start = base_offset + group[0].start()
            end = base_offset + group[-1].end()
            block_text = text[group[0].start() : group[-1].end()]

            blocks.append(
                {
                    "text": block_text,
                    "start_offset": start,
                    "end_offset": end,
                    "token_count": self._count_tokens(block_text),
                }
            )

        return blocks

    @staticmethod
    def _units_to_block(units: list[tuple[int, int, str]]) -> dict[str, Any]:
        start = units[0][0]
        end = units[-1][1]
        text = "\n\n".join(unit[2].strip() for unit in units if unit[2].strip())

        return {
            "text": text,
            "start_offset": start,
            "end_offset": end,
            "token_count": MemoryChunker._count_tokens(text),
        }

    def _make_entry(
        self,
        *,
        file_id: str,
        filename_ragmem: str,
        filename_meta: str,
        record: Any,
        role: str,
        block_id: str,
        position: int,
        text: str,
        start_offset: int,
        end_offset: int,
        ingestion_hash: str,
    ) -> dict[str, Any]:
        metadata = {
            "file_id": file_id or "",
            "filename_ragmem": filename_ragmem or "",
            "filename_meta": filename_meta or "",
            "record_id": record.record_id or "",
            "parent_id": record.parent_id or "",
            "role": role,
            "block_id": block_id,
            "position": int(position),
            "start_offset": int(start_offset),
            "end_offset": int(end_offset),
            "token_count": int(self._count_tokens(text)),
            "tag": record.tag or "",
            "active_project_name": record.active_project_name or "",
            "source": record.source or "",
            "created_at_utc": record.created_at_utc or "",
            "input_hash": record.input_hash or "",
            "output_hash": record.output_hash or "",
            "auto_keywords_text": self._join_list(record.auto_keywords),
            "yake_keywords_text": self._join_list(record.auto_keywords),
            "user_keywords_text": self._join_list(record.user_keywords),
            "embedded_files_snapshot_text": self._join_list(record.embedded_files_snapshot),
            "chunking_config_version": str(self.config["config_version"]),
            "ingestion_hash": ingestion_hash,
        }

        return {
            "id": f"mem::{file_id}::{record.record_id}::{role}::{block_id}",
            "document": text or "",
            "metadata": metadata,
        }

    def _build_ingestion_hash(self, record: Any, file_id: str) -> str:
        payload = {
            "file_id": file_id,
            "record_id": record.record_id,
            "input_hash": record.input_hash,
            "output_hash": record.output_hash,
            "tag": record.tag,
            "auto_keywords": list(record.auto_keywords or []),
            "user_keywords": list(record.user_keywords or []),
            "active_project_name": record.active_project_name,
            "chunking_config_version": self.config["config_version"],
        }

        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _truncate_by_tokens(text: str, max_tokens: int) -> str:
        words = re.findall(r"\S+", text or "")
        if len(words) <= max_tokens:
            return (text or "").strip()
        return " ".join(words[:max_tokens]).strip()

    @staticmethod
    def _count_tokens(text: str) -> int:
        return len(re.findall(r"\S+", text or ""))

    @staticmethod
    def _join_list(values: list[str] | None) -> str:
        cleaned: list[str] = []
        seen: set[str] = set()

        for value in values or []:
            item = str(value).strip()
            if not item:
                continue

            key = item.lower()
            if key in seen:
                continue

            cleaned.append(item)
            seen.add(key)

        return "; ".join(cleaned)
```

### ~\ragstream\memory\ingestion\memory_ingestion_manager.py
```python
# ragstream/memory/memory_ingestion_manager.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import threading

from typing import Any

from ragstream.textforge.RagLog import LogALL as logger


class MemoryIngestionManager:
    def __init__(
        self,
        memory_manager: Any,
        memory_chunker: Any,
        memory_vector_store: Any,
    ) -> None:
        self.memory_manager = memory_manager
        self.memory_chunker = memory_chunker
        self.memory_vector_store = memory_vector_store

        self._lock = threading.Lock()
        self._active_record_ids: set[str] = set()

    def ingest_record(self, record_id: str) -> dict[str, Any]:
        clean_record_id = (record_id or "").strip()
        if not clean_record_id:
            return {
                "success": False,
                "record_id": record_id,
                "message": "record_id is empty.",
            }

        record = self._find_record(clean_record_id)
        if record is None:
            message = f"MemoryRecord not found for ingestion: {clean_record_id}"
            logger(message, "WARN", "PUBLIC")
            return {
                "success": False,
                "record_id": clean_record_id,
                "message": message,
            }

        try:
            logger(
                (
                    "Memory ingestion started: "
                    f"record={clean_record_id[:8]} | file_id={self.memory_manager.file_id[:8]}"
                ),
                "INFO",
                "INTERNAL",
            )

            entries = self.memory_chunker.build_vector_entries(
                record,
                file_id=self.memory_manager.file_id,
                filename_ragmem=self.memory_manager.filename_ragmem,
                filename_meta=self.memory_manager.filename_meta,
            )

            role_counts = self._count_roles(entries)

            logger(
                (
                    "Memory blocks prepared: "
                    f"handle={role_counts.get('record_handle', 0)}, "
                    f"question={role_counts.get('question', 0)}, "
                    f"answer={role_counts.get('answer', 0)}"
                ),
                "INFO",
                "INTERNAL",
            )

            result = self.memory_vector_store.replace_record_entries(
                record_id=clean_record_id,
                entries=entries,
            )

            result.update(
                {
                    "role_counts": role_counts,
                    "file_id": self.memory_manager.file_id,
                    "filename_ragmem": self.memory_manager.filename_ragmem,
                }
            )

            logger(
                (
                    "Memory ingestion finished: "
                    f"{role_counts.get('record_handle', 0)} handle, "
                    f"{role_counts.get('question', 0)} question blocks, "
                    f"{role_counts.get('answer', 0)} answer blocks "
                    f"→ {result.get('vectors_written', 0)} vectors."
                ),
                "INFO",
                "PUBLIC",
            )

            logger(
                (
                    "Memory vector store updated: "
                    f"path={result.get('persist_dir', '')} | "
                    f"collection={result.get('collection_name', '')} | "
                    f"record_vectors={result.get('record_vector_count', 0)}"
                ),
                "INFO",
                "INTERNAL",
            )

            return result

        except Exception as e:
            message = f"Memory ingestion failed for {clean_record_id[:8]}: {e}"
            logger(message, "ERROR", "PUBLIC")
            return {
                "success": False,
                "record_id": clean_record_id,
                "message": message,
            }

    def ingest_all(self) -> dict[str, Any]:
        records = list(getattr(self.memory_manager, "records", []) or [])

        total = len(records)
        success_count = 0
        failure_count = 0
        results: list[dict[str, Any]] = []

        logger(f"Memory ingestion started for loaded history: {total} records.", "INFO", "PUBLIC")

        for record in records:
            result = self.ingest_record(record.record_id)
            results.append(result)

            if result.get("success"):
                success_count += 1
            else:
                failure_count += 1

        logger(
            (
                "Memory history ingestion finished: "
                f"{success_count} succeeded, {failure_count} failed."
            ),
            "INFO" if failure_count == 0 else "WARN",
            "PUBLIC",
        )

        return {
            "success": failure_count == 0,
            "total": total,
            "success_count": success_count,
            "failure_count": failure_count,
            "results": results,
        }

    def ingest_record_async(self, record_id: str) -> None:
        clean_record_id = (record_id or "").strip()
        if not clean_record_id:
            return

        record = self._find_record(clean_record_id)
        if record is None:
            logger(f"Memory ingestion was not scheduled; record not found: {clean_record_id}", "WARN", "PUBLIC")
            return

        with self._lock:
            if clean_record_id in self._active_record_ids:
                logger(
                    f"Memory ingestion already running for record: {clean_record_id[:8]}",
                    "INFO",
                    "INTERNAL",
                )
                return

            self._active_record_ids.add(clean_record_id)

        logger(
            (
                "Memory ingestion scheduled: "
                f"record={clean_record_id[:8]} | "
                f"question_chars={len(record.input_text or '')} | "
                f"answer_chars={len(record.output_text or '')}"
            ),
            "INFO",
            "PUBLIC",
        )

        thread = threading.Thread(
            target=self._async_worker,
            args=(clean_record_id,),
            daemon=True,
            name=f"memory-ingest-{clean_record_id[:8]}",
        )

        try:
            from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx

            ctx = get_script_run_ctx()
            if ctx is not None:
                add_script_run_ctx(thread, ctx)
        except Exception:
            pass

        thread.start()

    def _async_worker(self, record_id: str) -> None:
        try:
            self.ingest_record(record_id)
        finally:
            with self._lock:
                self._active_record_ids.discard(record_id)

    def _find_record(self, record_id: str) -> Any | None:
        for record in getattr(self.memory_manager, "records", []) or []:
            if getattr(record, "record_id", None) == record_id:
                return record
        return None

    @staticmethod
    def _count_roles(entries: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}

        for entry in entries:
            metadata = entry.get("metadata", {})
            role = str(metadata.get("role", "")).strip() or "unknown"
            counts[role] = counts.get(role, 0) + 1

        return counts
```

### ~\ragstream\memory\ingestion\memory_vector_store.py
```python
# ragstream/memory/memory_vector_store.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import json

from pathlib import Path
from typing import Any

from ragstream.textforge.RagLog import LogALL as logger
from ragstream.textforge.RagLog import LogDeveloper as _logger_dev

DEV_LOG_ENABLED = False

def logger_dev(*args, **kwargs):
    if DEV_LOG_ENABLED:
        return _logger_dev(*args, **kwargs)
    return None


class MemoryVectorStore:
    """
    Dedicated memory Chroma vector store.

    This store is separate from document Chroma stores.

    It owns:
    - memory vector persistence
    - record vector replacement
    - record vector deletion
    - file/history vector deletion by file_id
    - raw vector search for MemoryRetriever

    It does not own:
    - MemoryRecord truth
    - SQLite metadata truth
    - memory scoring
    - MemoryContextPack creation
    """

    def __init__(
        self,
        persist_dir: str,
        collection_name: str,
        embedder: Any,
    ) -> None:
        self.persist_dir = str(persist_dir)
        self.collection_name = collection_name
        self.embedder = embedder

        Path(self.persist_dir).mkdir(parents=True, exist_ok=True)

        import chromadb

        self._client = chromadb.PersistentClient(path=self.persist_dir)
        self._collection = self._client.get_or_create_collection(name=self.collection_name)

        logger(
            f"MemoryVectorStore ready: {self.persist_dir} | collection={self.collection_name}",
            "INFO",
            "INTERNAL",
        )

    def replace_record_entries(
        self,
        record_id: str,
        entries: list[dict[str, Any]],
    ) -> dict[str, Any]:
        clean_record_id = (record_id or "").strip()
        if not clean_record_id:
            raise ValueError("record_id must not be empty.")

        old_count = self.count_record(clean_record_id)
        self.delete_record(clean_record_id)

        if not entries:
            return {
                "success": True,
                "record_id": clean_record_id,
                "deleted_old_vectors": old_count,
                "vectors_written": 0,
                "record_vector_count": 0,
                "collection_name": self.collection_name,
                "persist_dir": self.persist_dir,
            }

        ids = [str(entry["id"]) for entry in entries]
        documents = [str(entry.get("document", "")) for entry in entries]
        metadatas = [self._sanitize_metadata(entry.get("metadata", {})) for entry in entries]

        embeddings = self._embed_documents(documents)

        self._collection.add(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

        new_count = self.count_record(clean_record_id)

        logger(
            (
                "Memory vectors written: "
                f"record={clean_record_id[:8]} | deleted={old_count} | "
                f"new={len(ids)} | total_for_record={new_count}"
            ),
            "INFO",
            "INTERNAL",
        )

        logger_dev(
            (
                "MemoryVectorStore.replace_record_entries\n"
                f"record_id={clean_record_id}\n"
                f"ids={json.dumps(ids, ensure_ascii=False, indent=2)}\n"
                f"metadatas={json.dumps(metadatas, ensure_ascii=False, indent=2, default=str)}"
            ),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return {
            "success": True,
            "record_id": clean_record_id,
            "deleted_old_vectors": old_count,
            "vectors_written": len(ids),
            "record_vector_count": new_count,
            "collection_name": self.collection_name,
            "persist_dir": self.persist_dir,
        }

    def query(
        self,
        query_text: str,
        n_results: int = 10,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search memory vectors and return flat hit dictionaries.

        Returned hit format:
        {
            "id": str,
            "document": str,
            "metadata": dict,
            "distance": float | None,
            "rank": int
        }
        """
        text = str(query_text or "").strip()
        if not text:
            return []

        query_embedding = self._embed_documents([text])[0]

        query_kwargs: dict[str, Any] = {
            "query_embeddings": [query_embedding],
            "n_results": int(n_results),
            "include": ["documents", "metadatas", "distances"],
        }

        if where:
            query_kwargs["where"] = self._sanitize_where(where)

        result = self._collection.query(**query_kwargs)
        hits = self._normalize_query_result(result)

        logger(
            f"MemoryVectorStore query finished: hits={len(hits)}",
            "INFO",
            "INTERNAL",
        )

        logger_dev(
            (
                "MemoryVectorStore.query\n"
                f"query_text={text}\n"
                f"n_results={n_results}\n"
                f"where={json.dumps(where or {}, ensure_ascii=False, indent=2, default=str)}\n"
                f"hits={json.dumps(hits, ensure_ascii=False, indent=2, default=str)}"
            ),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return hits

    def delete_record(self, record_id: str) -> dict[str, Any]:
        """Delete all memory vectors belonging to one MemoryRecord."""
        clean_record_id = (record_id or "").strip()
        if not clean_record_id:
            return {
                "success": False,
                "record_id": record_id,
                "deleted_vectors": 0,
                "message": "record_id is empty.",
            }

        old_count = self.count_record(clean_record_id)

        if old_count > 0:
            self._collection.delete(where={"record_id": clean_record_id})

        new_count = self.count_record(clean_record_id)

        deleted_vectors = max(old_count - new_count, 0)

        logger_dev(
            (
                "MemoryVectorStore.delete_record\n"
                f"record_id={clean_record_id}\n"
                f"old_count={old_count}\n"
                f"new_count={new_count}\n"
                f"deleted_vectors={deleted_vectors}"
            ),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return {
            "success": True,
            "record_id": clean_record_id,
            "deleted_vectors": deleted_vectors,
            "record_vector_count": new_count,
        }

    def delete_file(self, file_id: str) -> dict[str, Any]:
        """
        Delete all memory vectors belonging to one memory history.

        This is used by FILES tab Delete.
        """
        clean_file_id = (file_id or "").strip()
        if not clean_file_id:
            return {
                "success": False,
                "file_id": file_id,
                "deleted_vectors": 0,
                "message": "file_id is empty.",
            }

        old_count = self.count_file(clean_file_id)

        if old_count > 0:
            self._collection.delete(where={"file_id": clean_file_id})

        new_count = self.count_file(clean_file_id)
        deleted_vectors = max(old_count - new_count, 0)

        logger(
            (
                "Memory vectors deleted by file_id: "
                f"file={clean_file_id[:8]} | deleted={deleted_vectors}"
            ),
            "INFO",
            "INTERNAL",
        )

        logger_dev(
            (
                "MemoryVectorStore.delete_file\n"
                f"file_id={clean_file_id}\n"
                f"old_count={old_count}\n"
                f"new_count={new_count}\n"
                f"deleted_vectors={deleted_vectors}"
            ),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return {
            "success": True,
            "file_id": clean_file_id,
            "deleted_vectors": deleted_vectors,
            "file_vector_count": new_count,
            "collection_name": self.collection_name,
            "persist_dir": self.persist_dir,
        }

    def count_record(self, record_id: str) -> int:
        """Count vectors belonging to one MemoryRecord."""
        clean_record_id = (record_id or "").strip()
        if not clean_record_id:
            return 0

        try:
            result = self._collection.get(where={"record_id": clean_record_id})
            return len(result.get("ids", []))
        except Exception:
            return 0

    def count_file(self, file_id: str) -> int:
        """Count vectors belonging to one memory history."""
        clean_file_id = (file_id or "").strip()
        if not clean_file_id:
            return 0

        try:
            result = self._collection.get(where={"file_id": clean_file_id})
            return len(result.get("ids", []))
        except Exception:
            return 0

    def _embed_documents(self, documents: list[str]) -> list[list[float]]:
        if not documents:
            return []

        vectors = self.embedder.embed(documents)

        result: list[list[float]] = []
        for vector in vectors:
            if hasattr(vector, "tolist"):
                vector = vector.tolist()
            result.append([float(value) for value in vector])

        return result

    @staticmethod
    def _normalize_query_result(result: dict[str, Any]) -> list[dict[str, Any]]:
        ids = (result.get("ids") or [[]])[0] or []
        documents = (result.get("documents") or [[]])[0] or []
        metadatas = (result.get("metadatas") or [[]])[0] or []
        distances = (result.get("distances") or [[]])[0] or []

        hits: list[dict[str, Any]] = []

        for idx, vector_id in enumerate(ids):
            metadata = metadatas[idx] if idx < len(metadatas) and metadatas[idx] else {}
            document = documents[idx] if idx < len(documents) else ""
            distance = distances[idx] if idx < len(distances) else None

            hits.append(
                {
                    "id": vector_id,
                    "document": document,
                    "metadata": metadata,
                    "distance": distance,
                    "rank": idx + 1,
                }
            )

        return hits

    @staticmethod
    def _sanitize_where(where: dict[str, Any]) -> dict[str, str | int | float | bool]:
        clean: dict[str, str | int | float | bool] = {}

        for key, value in (where or {}).items():
            if value is None:
                continue

            clean_key = str(key)

            if isinstance(value, bool):
                clean[clean_key] = value
            elif isinstance(value, int):
                clean[clean_key] = value
            elif isinstance(value, float):
                clean[clean_key] = value
            else:
                clean[clean_key] = str(value)

        return clean

    @staticmethod
    def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, str | int | float | bool]:
        clean: dict[str, str | int | float | bool] = {}

        for key, value in (metadata or {}).items():
            clean_key = str(key)

            if value is None:
                clean[clean_key] = ""
            elif isinstance(value, bool):
                clean[clean_key] = value
            elif isinstance(value, int):
                clean[clean_key] = value
            elif isinstance(value, float):
                clean[clean_key] = value
            elif isinstance(value, str):
                clean[clean_key] = value
            else:
                clean[clean_key] = json.dumps(value, ensure_ascii=False, sort_keys=True)

        return clean
```

### ~\ragstream\memory\retrieval\memory_context_pack.py
```python
# ragstream/memory/retrieval/memory_context_pack.py
# -*- coding: utf-8 -*-
"""
MemoryContextPack
=================
Runtime container for Memory Retrieval results.

This object is NOT durable memory truth.
It is only the run-local candidate package written into SuperPrompt after
the Retrieval button has run.

It keeps raw memory candidates available for later stages:
- Memory compression
- Memory synthesis / MemoryMerge
- final PromptBuilder rendering
"""

from __future__ import annotations

import json

from typing import Any


class MemoryContextPack:
    """
    Structured runtime result of Memory Retrieval.

    The pack separates memory candidates by retrieval role so later stages can
    decide what to do with each group independently.
    """

    def __init__(self) -> None:
        # Recent non-Black records from the active memory file.
        self.working_memory_candidates: list[dict[str, Any]] = []

        # Parent MemoryRecord candidates selected from semantic scoring and Gold lookup.
        self.episodic_candidates: list[dict[str, Any]] = []

        # Raw question/answer vector-hit chunks selected for later synthesis.
        self.semantic_memory_chunks: list[dict[str, Any]] = []

        # One Direct Recall candidate, usually selected by exact key lookup.
        self.direct_recall_candidate: dict[str, Any] | None = None

        # Final synthesized query-relevant Memory Context.
        self.synthesized_memory_context: str = ""

        # Diagnostics from MemoryMerge synthesis.
        self.memory_synthesis_diagnostics: dict[str, Any] = {}

        # Human/developer-readable explanation of selections and exclusions.
        self.selection_diagnostics: dict[str, Any] = {}

        # Token information is only estimated here; MemoryMerge later owns trimming.
        self.token_budget_report: dict[str, Any] = {}

    def add_working_memory(self, candidate: dict[str, Any]) -> None:
        """Add one recent working-memory candidate."""
        if candidate:
            self.working_memory_candidates.append(candidate)

    def add_episodic_candidate(self, candidate: dict[str, Any]) -> None:
        """Add one episodic parent MemoryRecord candidate."""
        if candidate:
            self.episodic_candidates.append(candidate)

    def add_semantic_chunk(self, candidate: dict[str, Any]) -> None:
        """Add one raw semantic memory chunk candidate."""
        if candidate:
            self.semantic_memory_chunks.append(candidate)

    def set_direct_recall(self, candidate: dict[str, Any] | None) -> None:
        """Set the Direct Recall candidate for this run."""
        self.direct_recall_candidate = candidate if candidate else None

    def set_synthesized_memory_context(
        self,
        memory_context: str,
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        """Store the final synthesized Memory Context for this run."""
        self.synthesized_memory_context = str(memory_context or "").strip()
        self.memory_synthesis_diagnostics = dict(diagnostics or {})

    def set_selection_diagnostics(self, diagnostics: dict[str, Any]) -> None:
        """Store diagnostic information explaining the retrieval result."""
        self.selection_diagnostics = diagnostics or {}

    def set_token_budget_report(self, report: dict[str, Any]) -> None:
        """Store estimated token usage before later MemoryMerge compression."""
        self.token_budget_report = report or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert the pack into a plain dictionary for SuperPrompt.extras."""
        return {
            "working_memory_candidates": self.working_memory_candidates,
            "episodic_candidates": self.episodic_candidates,
            "semantic_memory_chunks": self.semantic_memory_chunks,
            "direct_recall_candidate": self.direct_recall_candidate,
            "synthesized_memory_context": self.synthesized_memory_context,
            "memory_synthesis_diagnostics": self.memory_synthesis_diagnostics,
            "selection_diagnostics": self.selection_diagnostics,
            "token_budget_report": self.token_budget_report,
            "counts": self.counts(),
        }

    def counts(self) -> dict[str, int]:
        """Return compact candidate counts for logs and GUI status."""
        return {
            "working_memory_candidates": len(self.working_memory_candidates),
            "episodic_candidates": len(self.episodic_candidates),
            "semantic_memory_chunks": len(self.semantic_memory_chunks),
            "direct_recall_candidate": 1 if self.direct_recall_candidate else 0,
            "synthesized_memory_context": 1 if self.synthesized_memory_context else 0,
        }

    def to_debug_markdown(self) -> str:
        """
        Render raw memory candidates for developer inspection.

        This is intentionally not final prompt context.
        The GUI projector no longer shows this raw memory block by default.
        """
        lines: list[str] = []

        lines.append("### Raw Memory Retrieval Candidates")
        lines.append("")
        lines.append("These are raw memory candidates produced by the Retrieval stage.")
        lines.append("They are not final prompt context.")
        lines.append("")

        self._append_synthesized_memory_context(lines)
        self._append_working_memory(lines)
        self._append_episodic_memory(lines)
        self._append_semantic_chunks(lines)
        self._append_direct_recall(lines)
        self._append_diagnostics(lines)

        return "\n".join(lines).strip()

    def _append_synthesized_memory_context(self, lines: list[str]) -> None:
        lines.append("#### Synthesized Memory Context")
        if not self.synthesized_memory_context:
            lines.append("(none)")
            lines.append("")
            return

        lines.append("```text")
        lines.append(self.synthesized_memory_context)
        lines.append("```")
        lines.append("")

    def _append_working_memory(self, lines: list[str]) -> None:
        lines.append("#### Working Memory Candidates")
        if not self.working_memory_candidates:
            lines.append("(none)")
            lines.append("")
            return

        for idx, candidate in enumerate(self.working_memory_candidates, start=1):
            lines.append(f"**W{idx}. record_id:** `{candidate.get('record_id', '')}`")
            lines.append(f"- tag: `{candidate.get('tag', '')}`")
            lines.append(f"- retrieval_source_mode: `{candidate.get('retrieval_source_mode', '')}`")
            lines.append("")
            lines.append(self._format_qa(candidate))
            lines.append("")

    def _append_episodic_memory(self, lines: list[str]) -> None:
        lines.append("#### Episodic Candidates")
        if not self.episodic_candidates:
            lines.append("(none)")
            lines.append("")
            return

        for idx, candidate in enumerate(self.episodic_candidates, start=1):
            final_score = candidate.get("final_parent_score", candidate.get("score", ""))
            semantic_score = candidate.get("semantic_parent_score", "")
            recency_score = candidate.get("recency_score", "")
            episode_distance_k = candidate.get("episode_distance_k", "")

            lines.append(f"**E{idx}. record_id:** `{candidate.get('record_id', '')}`")
            lines.append(f"- tag: `{candidate.get('tag', '')}`")
            lines.append(f"- final_score: `{final_score}`")
            lines.append(f"- semantic_score: `{semantic_score}`")
            lines.append(f"- recency_score: `{recency_score}`")
            lines.append(f"- episode_distance_k: `{episode_distance_k}`")
            lines.append(f"- retrieval_source_mode: `{candidate.get('retrieval_source_mode', '')}`")
            lines.append("")
            lines.append(self._format_qa(candidate))
            lines.append("")

    def _append_semantic_chunks(self, lines: list[str]) -> None:
        lines.append("#### Semantic Memory Chunks")
        if not self.semantic_memory_chunks:
            lines.append("(none)")
            lines.append("")
            return

        for idx, candidate in enumerate(self.semantic_memory_chunks, start=1):
            lines.append(f"**M{idx}. vector_id:** `{candidate.get('vector_id', candidate.get('id', ''))}`")
            lines.append(f"- record_id: `{candidate.get('record_id', '')}`")
            lines.append(f"- role: `{candidate.get('role', '')}`")
            lines.append(f"- final_score: `{candidate.get('score', '')}`")
            lines.append(f"- semantic_score: `{candidate.get('semantic_score', '')}`")
            lines.append(f"- recency_score: `{candidate.get('recency_score', '')}`")
            lines.append(f"- episode_distance_k: `{candidate.get('episode_distance_k', '')}`")
            lines.append("")
            text = str(candidate.get("document", candidate.get("text", ""))).strip()
            if text:
                lines.append("```text")
                lines.append(text)
                lines.append("```")
            lines.append("")

    def _append_direct_recall(self, lines: list[str]) -> None:
        lines.append("#### Direct Recall Candidate")
        if not self.direct_recall_candidate:
            lines.append("(none)")
            lines.append("")
            return

        candidate = self.direct_recall_candidate
        lines.append(f"**record_id:** `{candidate.get('record_id', '')}`")
        lines.append(f"- file_id: `{candidate.get('file_id', '')}`")
        lines.append(f"- tag: `{candidate.get('tag', '')}`")
        lines.append(f"- direct_recall_key: `{candidate.get('direct_recall_key', '')}`")
        lines.append("")
        lines.append(self._format_qa(candidate))
        lines.append("")

    def _append_diagnostics(self, lines: list[str]) -> None:
        lines.append("#### Selection Diagnostics")
        if not self.selection_diagnostics and not self.memory_synthesis_diagnostics:
            lines.append("(none)")
            lines.append("")
            return

        diagnostics = {
            "selection_diagnostics": self.selection_diagnostics,
            "memory_synthesis_diagnostics": self.memory_synthesis_diagnostics,
        }

        lines.append("```json")
        lines.append(json.dumps(diagnostics, ensure_ascii=False, indent=2, default=str))
        lines.append("```")
        lines.append("")

    @staticmethod
    def _format_qa(candidate: dict[str, Any]) -> str:
        input_text = str(candidate.get("compressed_input_text", candidate.get("input_text", "")) or "").strip()
        output_text = str(candidate.get("compressed_output_text", candidate.get("output_text", "")) or "").strip()

        lines: list[str] = []

        if input_text:
            lines.append("INPUT")
            lines.append("```text")
            lines.append(input_text)
            lines.append("```")

        if output_text:
            lines.append("OUTPUT")
            lines.append("```text")
            lines.append(output_text)
            lines.append("```")

        return "\n".join(lines).strip() if lines else "(no Q/A body available)"
```

### ~\ragstream\memory\retrieval\memory_index_lookup.py
```python
# ragstream/memory/memory_index_lookup.py
# -*- coding: utf-8 -*-
"""
MemoryIndexLookup
=================
Deterministic lookup layer for Memory Retrieval.

This class reads memory_index.sqlite3 and, when needed, reconstructs Q/A body
text from the corresponding .ragmem file.

It does not perform vector search.
It does not score semantic hits.
It does not modify memory truth.
"""

from __future__ import annotations

import json
import re
import sqlite3

from pathlib import Path
from typing import Any

from ragstream.memory.memory_record import RECORD_END, RECORD_START
from ragstream.textforge.RagLog import LogALL as logger
from ragstream.textforge.RagLog import LogDeveloper as _logger_dev
DEV_LOG_ENABLED = False

def logger_dev(*args, **kwargs):
    if DEV_LOG_ENABLED:
        return _logger_dev(*args, **kwargs)
    return None

class MemoryIndexLookup:
    """
    SQLite-backed deterministic lookup helper.

    The SQLite table mirrors .ragmeta.json metadata.
    Full Q/A body is loaded from .ragmem only when needed for candidates.
    """

    def __init__(
        self,
        sqlite_path: str | Path,
        memory_root: str | Path | None = None,
    ) -> None:
        self.sqlite_path: Path = Path(sqlite_path)
        self.memory_root: Path | None = Path(memory_root) if memory_root is not None else None

    def get_working_memory(
        self,
        file_id: str,
        cfg: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Return latest non-Black records from the active memory file.

        This is the current-log working memory.
        """
        clean_file_id = str(file_id or "").strip()
        if not clean_file_id:
            return []

        working_cfg = cfg.get("working_memory", {}) if isinstance(cfg, dict) else {}
        if working_cfg.get("enabled", True) is False:
            return []

        max_pairs = int(working_cfg.get("max_pairs", 2))
        exclude_tags = self._as_list(working_cfg.get("exclude_tags", ["Black"]))

        query = """
            SELECT *
            FROM memory_records
            WHERE file_id = ?
        """
        params: list[Any] = [clean_file_id]

        if exclude_tags:
            placeholders = ",".join("?" for _ in exclude_tags)
            query += f" AND tag NOT IN ({placeholders})"
            params.extend(exclude_tags)

        query += " ORDER BY created_at_utc DESC LIMIT ?"
        params.append(max_pairs)

        rows = self._fetch_rows(query, params)
        candidates = [self._row_to_candidate(row) for row in rows]
        candidates = self._attach_file_rows(candidates)
        candidates = self._attach_ragmem_bodies(candidates)

        logger(
            f"Memory working lookup: file={clean_file_id[:8]} | candidates={len(candidates)}",
            "INFO",
            "INTERNAL",
        )

        logger_dev(
            "Memory working lookup result\n"
            + json.dumps(candidates, ensure_ascii=False, indent=2, default=str),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return candidates

    def get_latest_gold(
        self,
        file_id: str,
        cfg: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Return latest Gold candidates from the active memory file.

        Gold is still bounded by config; it is not unlimited context.
        """
        clean_file_id = str(file_id or "").strip()
        if not clean_file_id:
            return []

        episodic_cfg = cfg.get("episodic_memory", {}) if isinstance(cfg, dict) else {}
        if episodic_cfg.get("enabled", True) is False:
            return []

        max_gold_records = int(episodic_cfg.get("max_gold_records", 1))

        rows = self._fetch_rows(
            """
            SELECT *
            FROM memory_records
            WHERE file_id = ?
              AND tag = 'Gold'
            ORDER BY created_at_utc DESC
            LIMIT ?
            """,
            [clean_file_id, max_gold_records],
        )

        candidates = [self._row_to_candidate(row) for row in rows]
        candidates = self._attach_file_rows(candidates)
        candidates = self._attach_ragmem_bodies(candidates)

        logger(
            f"Memory Gold lookup: file={clean_file_id[:8]} | candidates={len(candidates)}",
            "INFO",
            "INTERNAL",
        )

        logger_dev(
            "Memory Gold lookup result\n"
            + json.dumps(candidates, ensure_ascii=False, indent=2, default=str),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return candidates

    def get_direct_recall(
        self,
        direct_recall_key: str,
        cfg: dict[str, Any],
    ) -> dict[str, Any] | None:
        """
        Lookup a Direct Recall candidate across all memory histories.

        Automatic retrieval stays current-file only, but Direct Recall is allowed
        to cross histories through exact key lookup.
        """
        key = str(direct_recall_key or "").strip()
        if not key:
            return None

        direct_cfg = cfg.get("direct_recall", {}) if isinstance(cfg, dict) else {}
        if direct_cfg.get("enabled", True) is False:
            return None

        exclude_tags = self._as_list(direct_cfg.get("exclude_tags", ["Black"]))

        query = """
            SELECT *
            FROM memory_records
            WHERE direct_recall_key = ?
        """
        params: list[Any] = [key]

        if exclude_tags:
            placeholders = ",".join("?" for _ in exclude_tags)
            query += f" AND tag NOT IN ({placeholders})"
            params.extend(exclude_tags)

        query += """
            ORDER BY
              CASE tag WHEN 'Gold' THEN 0 WHEN 'Green' THEN 1 ELSE 2 END,
              created_at_utc DESC
            LIMIT 1
        """

        rows = self._fetch_rows(query, params)
        if not rows:
            logger(f"Direct Recall lookup found no match: key={key}", "INFO", "INTERNAL")
            return None

        candidates = [self._row_to_candidate(rows[0])]
        candidates = self._attach_file_rows(candidates)
        candidates = self._attach_ragmem_bodies(candidates)

        candidate = candidates[0] if candidates else None

        logger(
            f"Direct Recall lookup matched: key={key} | record={candidate.get('record_id', '')[:8] if candidate else ''}",
            "INFO",
            "INTERNAL",
        )

        logger_dev(
            "Direct Recall lookup result\n"
            + json.dumps(candidate, ensure_ascii=False, indent=2, default=str),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return candidate

    def get_records_by_ids(
        self,
        file_id: str,
        record_ids: list[str],
    ) -> list[dict[str, Any]]:
        """
        Load metadata rows for selected parent MemoryRecord ids.
        """
        clean_file_id = str(file_id or "").strip()
        clean_ids = [str(record_id).strip() for record_id in record_ids if str(record_id).strip()]

        if not clean_file_id or not clean_ids:
            return []

        placeholders = ",".join("?" for _ in clean_ids)

        rows = self._fetch_rows(
            f"""
            SELECT *
            FROM memory_records
            WHERE file_id = ?
              AND record_id IN ({placeholders})
            """,
            [clean_file_id, *clean_ids],
        )

        candidates = [self._row_to_candidate(row) for row in rows]
        candidates = self._attach_file_rows(candidates)
        candidates = self._attach_ragmem_bodies(candidates)

        return candidates

    def get_file_row(
        self,
        file_id: str,
    ) -> dict[str, Any] | None:
        """Return one row from memory_files."""
        clean_file_id = str(file_id or "").strip()
        if not clean_file_id:
            return None

        rows = self._fetch_rows(
            """
            SELECT *
            FROM memory_files
            WHERE file_id = ?
            """,
            [clean_file_id],
            table_name="memory_files",
        )

        return dict(rows[0]) if rows else None

    def _fetch_rows(
        self,
        query: str,
        params: list[Any],
        *,
        table_name: str = "memory_records",
    ) -> list[sqlite3.Row]:
        if not self.sqlite_path.exists():
            logger(f"Memory SQLite not found: {self.sqlite_path}", "WARN", "PUBLIC")
            return []

        with sqlite3.connect(self.sqlite_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()

        logger_dev(
            (
                "MemoryIndexLookup SQL result\n"
                f"table={table_name}\n"
                f"query={query.strip()}\n"
                f"params={params}\n"
                f"rows={len(rows)}"
            ),
            "TRACE",
            "CONFIDENTIAL",
        )

        return rows

    def _row_to_candidate(self, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        data = dict(row)

        candidate: dict[str, Any] = {
            "file_id": data.get("file_id", ""),
            "record_id": data.get("record_id", ""),
            "parent_id": data.get("parent_id", ""),
            "created_at_utc": data.get("created_at_utc", ""),
            "source": data.get("source", ""),
            "tag": data.get("tag", ""),
            "retrieval_source_mode": data.get("retrieval_source_mode", "QA"),
            "direct_recall_key": data.get("direct_recall_key", ""),
            "auto_keywords": self._json_list(data.get("auto_keywords_json")),
            "user_keywords": self._json_list(data.get("user_keywords_json")),
            "active_project_name": data.get("active_project_name", ""),
            "embedded_files_snapshot": self._json_list(data.get("embedded_files_snapshot_json")),
            "input_hash": data.get("input_hash", ""),
            "output_hash": data.get("output_hash", ""),
            "sqlite_metadata": data,
        }

        return candidate

    def _attach_file_rows(
        self,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        file_cache: dict[str, dict[str, Any]] = {}

        for candidate in candidates:
            file_id = str(candidate.get("file_id", "")).strip()
            if not file_id:
                continue

            if file_id not in file_cache:
                file_cache[file_id] = self.get_file_row(file_id) or {}

            file_row = file_cache[file_id]
            candidate["file_row"] = file_row
            candidate["title"] = file_row.get("title", "")
            candidate["filename_ragmem"] = file_row.get("filename_ragmem", "")
            candidate["filename_meta"] = file_row.get("filename_meta", "")

        return candidates

    def _attach_ragmem_bodies(
        self,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Attach stable Q/A body from .ragmem.

        SQLite intentionally stores metadata only, so Q/A body comes from
        the durable .ragmem file.
        """
        if self.memory_root is None:
            return candidates

        body_cache: dict[tuple[str, str], dict[str, Any]] = {}

        for candidate in candidates:
            file_id = str(candidate.get("file_id", "")).strip()
            record_id = str(candidate.get("record_id", "")).strip()

            if not file_id or not record_id:
                continue

            cache_key = (file_id, record_id)
            if cache_key not in body_cache:
                body_cache[cache_key] = self._load_ragmem_body(candidate)

            body = body_cache[cache_key]
            candidate["input_text"] = body.get("input_text", "")
            candidate["output_text"] = body.get("output_text", "")
            candidate["ragmem_body"] = body

        return candidates

    def _load_ragmem_body(
        self,
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        if self.memory_root is None:
            return {}

        filename_ragmem = str(candidate.get("filename_ragmem", "")).strip()
        record_id = str(candidate.get("record_id", "")).strip()

        if not filename_ragmem or not record_id:
            return {}

        ragmem_path = self.memory_root / "files" / filename_ragmem
        if not ragmem_path.exists():
            return {}

        text = ragmem_path.read_text(encoding="utf-8")
        pattern = re.compile(
            rf"{re.escape(RECORD_START)}\n(.*?)\n{re.escape(RECORD_END)}",
            re.DOTALL,
        )

        for match in pattern.finditer(text):
            raw_block = match.group(1)
            try:
                data = json.loads(raw_block)
            except Exception:
                continue

            if isinstance(data, dict) and str(data.get("record_id", "")) == record_id:
                return data

        return {}

    @staticmethod
    def _json_list(value: Any) -> list[Any]:
        if isinstance(value, list):
            return value

        if value is None:
            return []

        try:
            parsed = json.loads(str(value))
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []

    @staticmethod
    def _as_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]

        if value is None:
            return []

        text = str(value).strip()
        return [text] if text else []
```

### ~\ragstream\memory\retrieval\memory_scoring.py
```python
# ragstream/memory/memory_scoring.py
# -*- coding: utf-8 -*-
"""
MemoryScorer
============
Scoring and aggregation logic for Memory Retrieval.

It receives raw vector hits and converts them into:
- normalized hit scores
- parent MemoryRecord scores
- selected semantic memory chunks

This class does not read SQLite.
This class does not query Chroma.
This class does not mutate SuperPrompt.
"""

from __future__ import annotations

import json
import math

from typing import Any

from ragstream.textforge.RagLog import LogALL as logger
from ragstream.textforge.RagLog import LogDeveloper as _logger_dev
DEV_LOG_ENABLED = False

def logger_dev(*args, **kwargs):
    if DEV_LOG_ENABLED:
        return _logger_dev(*args, **kwargs)
    return None

class MemoryScorer:
    """
    Memory retrieval scoring helper.

    Role-separated scoring:
    - question hits represent similarity to an old problem
    - answer hits represent similarity to an old solution
    - record_handle hits represent metadata/keyword/anchor discovery

    Recency scoring is episode-distance based:
    - k = 0 means latest MemoryRecord
    - k = 1 means one MemoryRecord older
    - k = 2 means two MemoryRecords older
    """

    def __init__(
        self,
        config: dict[str, Any],
    ) -> None:
        self.config: dict[str, Any] = config or {}
        self.parent_score_weights: dict[str, dict[str, float]] = dict(
            self.config.get("parent_score_weights", {}) or {}
        )

        self.default_weights: dict[str, float] = {
            "answer": 0.55,
            "question": 0.35,
            "meta": 0.10,
        }

        self.semantic_chunk_cfg: dict[str, Any] = dict(
            self.config.get("semantic_memory_chunks", {}) or {}
        )
        self.episodic_cfg: dict[str, Any] = dict(
            self.config.get("episodic_memory", {}) or {}
        )

    def score_vector_hits(
        self,
        raw_hits: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Normalize raw vector-store hits.

        Chroma usually returns distance, where smaller means better.
        This method converts distance into a simple similarity-like score.
        """
        scored_hits: list[dict[str, Any]] = []

        for rank, hit in enumerate(raw_hits, start=1):
            metadata = dict(hit.get("metadata", {}) or {})
            role = str(metadata.get("role", hit.get("role", "")) or "").strip()

            distance = hit.get("distance")
            score = hit.get("score")

            if score is None:
                score = self._distance_to_score(distance)

            scored_hit = {
                "rank": rank,
                "vector_id": hit.get("id", hit.get("vector_id", "")),
                "record_id": metadata.get("record_id", hit.get("record_id", "")),
                "role": role,
                "score": float(score),
                "semantic_score": float(score),
                "distance": distance,
                "document": hit.get("document", ""),
                "metadata": metadata,
                "raw_hit": hit,
            }

            scored_hits.append(scored_hit)

        logger(
            f"Memory vector hits scored: {len(scored_hits)}",
            "INFO",
            "INTERNAL",
        )

        logger_dev(
            "Memory scored vector hits\n"
            + json.dumps(scored_hits, ensure_ascii=False, indent=2, default=str),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return scored_hits

    def aggregate_parent_scores(
        self,
        scored_hits: list[dict[str, Any]],
        metadata_by_record: dict[str, dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Aggregate vector-hit scores by parent MemoryRecord.

        The parent score is the main episodic score.
        Individual chunks remain available separately for A3/A4 later.
        """
        metadata_by_record = metadata_by_record or {}
        grouped: dict[str, dict[str, Any]] = {}

        for hit in scored_hits:
            record_id = str(hit.get("record_id", "")).strip()
            if not record_id:
                continue

            role = str(hit.get("role", "")).strip()
            score = float(hit.get("score", 0.0))

            if record_id not in grouped:
                metadata = dict(metadata_by_record.get(record_id, {}) or {})
                grouped[record_id] = {
                    "record_id": record_id,
                    "tag": metadata.get("tag", "Green") or "Green",
                    "retrieval_source_mode": metadata.get("retrieval_source_mode", "QA"),
                    "episode_distance_k": metadata.get("episode_distance_k"),
                    "episode_index": metadata.get("episode_index"),
                    "episode_count_in_active_file": metadata.get("episode_count_in_active_file"),
                    "question_score": 0.0,
                    "answer_score": 0.0,
                    "meta_score": 0.0,
                    "semantic_parent_score": 0.0,
                    "recency_score": None,
                    "final_parent_score": 0.0,
                    "hit_count": 0,
                    "hits": [],
                    "metadata": metadata,
                }

            parent = grouped[record_id]
            parent["hit_count"] += 1
            parent["hits"].append(hit)

            if role == "question":
                parent["question_score"] = max(float(parent["question_score"]), score)
            elif role == "answer":
                parent["answer_score"] = max(float(parent["answer_score"]), score)
            else:
                parent["meta_score"] = max(float(parent["meta_score"]), score)

        parents = list(grouped.values())
        parents = self.apply_retrieval_source_mode(parents)
        parents = self.apply_tag_rules(parents)
        parents = self.apply_episodic_recency_policy(parents)
        parents = self.rank_parents(parents)

        logger(
            f"Memory parent scores aggregated: {len(parents)} parents",
            "INFO",
            "INTERNAL",
        )

        logger_dev(
            "Memory parent score aggregation\n"
            + json.dumps(parents, ensure_ascii=False, indent=2, default=str),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return parents

    def apply_retrieval_source_mode(
        self,
        parent_scores: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Apply QA/Q/A weighting to parent MemoryRecord scores.

        This produces the semantic parent score before recency is applied.
        """
        for parent in parent_scores:
            mode = str(parent.get("retrieval_source_mode", "QA") or "QA").strip().upper()
            if mode not in {"QA", "Q", "A"}:
                mode = "QA"

            weights = self.parent_score_weights.get(mode, self.default_weights)

            answer_score = float(parent.get("answer_score", 0.0))
            question_score = float(parent.get("question_score", 0.0))
            meta_score = float(parent.get("meta_score", 0.0))

            semantic_parent_score = (
                answer_score * float(weights.get("answer", 0.0))
                + question_score * float(weights.get("question", 0.0))
                + meta_score * float(weights.get("meta", 0.0))
            )

            parent["semantic_parent_score"] = semantic_parent_score
            parent["final_parent_score"] = semantic_parent_score
            parent["applied_weights"] = weights
            parent["retrieval_source_mode"] = mode

        return parent_scores

    def apply_tag_rules(
        self,
        parent_scores: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Apply current retrieval tag rules.

        Black records are excluded from automatic Memory Retrieval.
        Gold records are not decayed here because Gold is handled as a separate
        priority/bypass path by MemoryRetriever.
        """
        excluded_tags = self._collect_excluded_tags()
        result: list[dict[str, Any]] = []

        for parent in parent_scores:
            tag = str(parent.get("tag", "") or "Green").strip()

            if tag in excluded_tags:
                parent["excluded"] = True
                parent["exclude_reason"] = f"tag={tag}"
                continue

            parent["excluded"] = False
            parent["gold_bypass_recency"] = tag == "Gold"

            result.append(parent)

        return result

    def apply_episodic_recency_policy(
        self,
        parent_scores: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Apply Green episodic recency policy.

        Formula:
            final = semantic_weight * semantic_parent_score
                    + recency_weight * recency_score

        Gold bypasses this normal recency policy.
        Black has already been excluded.
        """
        semantic_weight = float(self.episodic_cfg.get("green_semantic_weight", 0.75))
        recency_weight = float(self.episodic_cfg.get("green_recency_weight", 0.25))
        half_life_k = float(self.episodic_cfg.get("green_half_life_k", 10.0))
        recency_enabled = bool(self.episodic_cfg.get("recency_enabled", True))

        semantic_weight, recency_weight = self._normalize_two_weights(
            semantic_weight,
            recency_weight,
        )

        for parent in parent_scores:
            tag = str(parent.get("tag", "") or "Green").strip()
            semantic_score = float(parent.get("semantic_parent_score", 0.0))

            if tag == "Gold":
                parent["final_parent_score"] = semantic_score
                parent["recency_score"] = None
                parent["recency_policy"] = "bypassed_for_gold"
                continue

            if not recency_enabled:
                parent["final_parent_score"] = semantic_score
                parent["recency_score"] = None
                parent["recency_policy"] = "disabled"
                continue

            recency_score = self._recency_score_from_episode_distance(
                parent.get("episode_distance_k"),
                half_life_k,
            )

            final_score = (
                semantic_weight * semantic_score
                + recency_weight * recency_score
            )

            parent["final_parent_score"] = final_score
            parent["recency_score"] = recency_score
            parent["recency_half_life_k"] = half_life_k
            parent["semantic_recency_weights"] = {
                "semantic": semantic_weight,
                "recency": recency_weight,
            }
            parent["recency_policy"] = "green_episodic_semantic_plus_recency"

        return parent_scores

    def rank_parents(
        self,
        parent_scores: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Return parent MemoryRecords sorted by final score."""
        return sorted(
            parent_scores,
            key=lambda item: float(item.get("final_parent_score", 0.0)),
            reverse=True,
        )

    def select_semantic_chunks(
        self,
        scored_hits: list[dict[str, Any]],
        max_memory_chunks: int,
        metadata_by_record: dict[str, dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Select raw semantic memory chunks for later A3/A4.

        record_handle hits are not selected here because they are discovery
        handles, not semantic evidence chunks.

        Semantic chunks use weaker recency weighting than episodic memory.
        """
        metadata_by_record = metadata_by_record or {}
        candidates: list[dict[str, Any]] = []

        semantic_weight = float(self.semantic_chunk_cfg.get("semantic_weight", 0.90))
        recency_weight = float(self.semantic_chunk_cfg.get("recency_weight", 0.10))
        half_life_k = float(self.semantic_chunk_cfg.get("half_life_k", 10.0))
        recency_enabled = bool(self.semantic_chunk_cfg.get("recency_enabled", True))

        semantic_weight, recency_weight = self._normalize_two_weights(
            semantic_weight,
            recency_weight,
        )

        for hit in scored_hits:
            role = str(hit.get("role", "")).strip()
            if role not in {"question", "answer"}:
                continue

            record_id = str(hit.get("record_id", "") or "").strip()
            live_metadata = dict(metadata_by_record.get(record_id, {}) or {})
            metadata = dict(hit.get("metadata", {}) or {})
            merged_metadata = {**metadata, **live_metadata}

            tag = str(merged_metadata.get("tag", "") or "Green").strip()
            if tag in self._collect_excluded_tags():
                continue

            semantic_score = float(hit.get("semantic_score", hit.get("score", 0.0)))

            if tag == "Gold":
                final_score = semantic_score
                recency_score = None
                recency_policy = "bypassed_for_gold"
            elif recency_enabled:
                recency_score = self._recency_score_from_episode_distance(
                    merged_metadata.get("episode_distance_k"),
                    half_life_k,
                )
                final_score = (
                    semantic_weight * semantic_score
                    + recency_weight * recency_score
                )
                recency_policy = "semantic_chunk_semantic_plus_recency"
            else:
                final_score = semantic_score
                recency_score = None
                recency_policy = "disabled"

            candidates.append(
                {
                    "vector_id": hit.get("vector_id", ""),
                    "record_id": record_id,
                    "role": role,
                    "score": float(final_score),
                    "semantic_score": semantic_score,
                    "recency_score": recency_score,
                    "episode_distance_k": merged_metadata.get("episode_distance_k"),
                    "recency_half_life_k": half_life_k if recency_enabled and tag != "Gold" else None,
                    "semantic_recency_weights": {
                        "semantic": semantic_weight,
                        "recency": recency_weight,
                    },
                    "recency_policy": recency_policy,
                    "distance": hit.get("distance"),
                    "document": hit.get("document", ""),
                    "metadata": merged_metadata,
                    "rank": hit.get("rank"),
                }
            )

        candidates.sort(
            key=lambda item: float(item.get("score", 0.0)),
            reverse=True,
        )

        selected = candidates[: max(0, int(max_memory_chunks))]

        logger(
            f"Semantic memory chunks selected: {len(selected)}",
            "INFO",
            "INTERNAL",
        )

        logger_dev(
            "Selected semantic memory chunks\n"
            + json.dumps(selected, ensure_ascii=False, indent=2, default=str),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return selected

    def describe_policy(self) -> dict[str, Any]:
        """Return compact scoring policy for developer diagnostics."""
        return {
            "episodic_memory": {
                "green_semantic_weight": float(self.episodic_cfg.get("green_semantic_weight", 0.75)),
                "green_recency_weight": float(self.episodic_cfg.get("green_recency_weight", 0.25)),
                "green_half_life_k": float(self.episodic_cfg.get("green_half_life_k", 10.0)),
                "recency_enabled": bool(self.episodic_cfg.get("recency_enabled", True)),
                "gold_policy": "bypass_recency_normal_scoring",
            },
            "semantic_memory_chunks": {
                "semantic_weight": float(self.semantic_chunk_cfg.get("semantic_weight", 0.90)),
                "recency_weight": float(self.semantic_chunk_cfg.get("recency_weight", 0.10)),
                "half_life_k": float(self.semantic_chunk_cfg.get("half_life_k", 10.0)),
                "recency_enabled": bool(self.semantic_chunk_cfg.get("recency_enabled", True)),
                "gold_policy": "bypass_recency_normal_scoring",
            },
        }

    def _collect_excluded_tags(self) -> set[str]:
        tags: set[str] = set()

        for section_name in ("working_memory", "episodic_memory", "direct_recall", "semantic_memory_chunks"):
            section = self.config.get(section_name, {})
            for tag in section.get("exclude_tags", []) or []:
                clean = str(tag).strip()
                if clean:
                    tags.add(clean)

        if not tags:
            tags.add("Black")

        return tags

    @staticmethod
    def _recency_score_from_episode_distance(
        episode_distance_k: Any,
        half_life_k: float,
    ) -> float:
        """
        Episode-distance half-life decay.

        k = 0 -> 1.0
        k = H -> 0.5
        k = 2H -> 0.25

        Missing k returns 1.0 so missing metadata does not silently kill
        otherwise relevant memory.
        """
        try:
            k = float(episode_distance_k)
        except Exception:
            return 1.0

        if math.isnan(k) or math.isinf(k):
            return 1.0

        if k < 0:
            k = 0.0

        try:
            h = float(half_life_k)
        except Exception:
            h = 10.0

        if math.isnan(h) or math.isinf(h) or h <= 0:
            h = 10.0

        score = 2.0 ** (-k / h)

        return max(0.0, min(1.0, float(score)))

    @staticmethod
    def _normalize_two_weights(
        semantic_weight: float,
        recency_weight: float,
    ) -> tuple[float, float]:
        """
        Normalize two active weights so semantic=1 and recency=1 still gives 1.

        This avoids the inactive-importance problem.
        """
        s = max(0.0, float(semantic_weight))
        r = max(0.0, float(recency_weight))
        total = s + r

        if total <= 0:
            return 1.0, 0.0

        return s / total, r / total

    @staticmethod
    def _distance_to_score(distance: Any) -> float:
        """
        Convert Chroma distance into a bounded similarity-like score.

        Smaller distance means better match.
        """
        try:
            d = float(distance)
        except Exception:
            return 0.0

        if math.isnan(d) or math.isinf(d):
            return 0.0

        if d < 0:
            d = 0.0

        return 1.0 / (1.0 + d)
```

### ~\ragstream\memory\storage\memory_file_manager.py
```python
# ragstream/memory/memory_file_manager.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import sqlite3
import uuid

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ragstream.memory.memory_manager import MemoryManager
from ragstream.textforge.RagLog import LogALL as logger
from ragstream.textforge.RagLog import LogDeveloper as _logger_dev
DEV_LOG_ENABLED = False

def logger_dev(*args, **kwargs):
    if DEV_LOG_ENABLED:
        return _logger_dev(*args, **kwargs)
    return None

def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_title(title: str) -> str:
    value = (title or "").strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-._")
    return value or "Memory"


class MemoryFileManager:
    """
    Server-side manager for memory history files.

    Owns file-level operations:
    - list histories
    - create history
    - load history
    - rename history
    - delete history

    Identity rule:
    - file_id is stable identity.
    - filename_ragmem / filename_meta are mutable path/display fields.
    """

    def __init__(
        self,
        memory_manager: MemoryManager,
        memory_vector_store: Any | None = None,
    ) -> None:
        self.memory_manager = memory_manager
        self.memory_vector_store = memory_vector_store

    def list_histories(self) -> list[dict[str, Any]]:
        """Return all memory histories from SQLite."""
        return self.memory_manager.list_histories()

    def create_history(self, title: str) -> dict[str, Any]:
        """
        Create a new empty memory history and make it active.

        Creates:
        - empty .ragmem file
        - .ragmeta.json file
        - SQLite memory_files row
        """
        clean_title = str(title or "").strip()
        if not clean_title:
            raise ValueError("title must not be empty.")

        self.memory_manager.start_new_history(clean_title)

        now = _utc_now()

        self.memory_manager.files_root.mkdir(parents=True, exist_ok=True)
        self.memory_manager.ragmem_path.touch(exist_ok=False)

        metainfo = {
            "file_id": self.memory_manager.file_id,
            "title": self.memory_manager.title,
            "filename_ragmem": self.memory_manager.filename_ragmem,
            "filename_meta": self.memory_manager.filename_meta,
            "created_at_utc": now,
            "updated_at_utc": now,
            "record_count": 0,
            "record_ids": [],
            "parent_ids": [],
            "tag_summary": {},
            "auto_keywords": [],
            "user_keywords": [],
            "records": [],
        }

        self.memory_manager.metainfo = metainfo
        self.memory_manager.b_file_created = True

        with self.memory_manager.meta_path.open("w", encoding="utf-8") as f:
            json.dump(metainfo, f, ensure_ascii=False, indent=2)

        self._insert_empty_file_row(
            file_id=self.memory_manager.file_id,
            title=self.memory_manager.title,
            filename_ragmem=self.memory_manager.filename_ragmem,
            filename_meta=self.memory_manager.filename_meta,
            created_at_utc=now,
            updated_at_utc=now,
        )

        logger_dev(
            (
                "MemoryFileManager.create_history\n"
                f"file_id={self.memory_manager.file_id}\n"
                f"title={self.memory_manager.title}\n"
                f"filename_ragmem={self.memory_manager.filename_ragmem}\n"
                f"filename_meta={self.memory_manager.filename_meta}"
            ),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return {
            "success": True,
            "file_id": self.memory_manager.file_id,
            "title": self.memory_manager.title,
            "filename_ragmem": self.memory_manager.filename_ragmem,
            "filename_meta": self.memory_manager.filename_meta,
            "record_count": 0,
        }

    def load_history(self, file_id: str) -> dict[str, Any]:
        """Load one memory history into the active MemoryManager."""
        clean_file_id = self._clean_file_id(file_id)
        self.memory_manager.load_history(clean_file_id)

        return {
            "success": True,
            "file_id": self.memory_manager.file_id,
            "title": self.memory_manager.title,
            "filename_ragmem": self.memory_manager.filename_ragmem,
            "filename_meta": self.memory_manager.filename_meta,
            "record_count": len(self.memory_manager.records),
        }

    def rename_history(
        self,
        file_id: str,
        new_title: str,
    ) -> dict[str, Any]:
        """
        Rename one memory history.

        Updates:
        - physical .ragmem filename
        - physical .ragmeta.json filename
        - SQLite memory_files row
        - file-level fields inside .ragmeta.json
        """
        clean_file_id = self._clean_file_id(file_id)
        clean_title = (new_title or "").strip()

        if not clean_title:
            raise ValueError("new_title must not be empty.")

        row = self._lookup_file(clean_file_id)
        if not row:
            raise ValueError(f"Memory history not found: {clean_file_id}")

        old_ragmem = self.memory_manager.files_root / row["filename_ragmem"]
        old_meta = self.memory_manager.files_root / row["filename_meta"]

        timestamp_prefix = self._extract_timestamp_prefix(row["filename_ragmem"])
        stem = f"{timestamp_prefix}-{_safe_title(clean_title)}"

        new_ragmem_name = f"{stem}.ragmem"
        new_meta_name = f"{stem}.ragmeta.json"

        new_ragmem = self.memory_manager.files_root / new_ragmem_name
        new_meta = self.memory_manager.files_root / new_meta_name

        if new_ragmem.exists() or new_meta.exists():
            stem = f"{stem}-{clean_file_id[:8]}"
            new_ragmem_name = f"{stem}.ragmem"
            new_meta_name = f"{stem}.ragmeta.json"
            new_ragmem = self.memory_manager.files_root / new_ragmem_name
            new_meta = self.memory_manager.files_root / new_meta_name

        if old_ragmem.exists():
            old_ragmem.rename(new_ragmem)

        if old_meta.exists():
            old_meta.rename(new_meta)

        now = _utc_now()

        self._update_sqlite_file_row(
            file_id=clean_file_id,
            title=clean_title,
            filename_ragmem=new_ragmem_name,
            filename_meta=new_meta_name,
            updated_at_utc=now,
        )

        if self.memory_manager.file_id == clean_file_id:
            self.memory_manager.title = clean_title
            self.memory_manager.filename_ragmem = new_ragmem_name
            self.memory_manager.filename_meta = new_meta_name
            self.memory_manager.save_metainfo()
            self.memory_manager.refresh_sqlite_index()
        else:
            self._update_meta_json_file_fields(
                meta_path=new_meta,
                title=clean_title,
                filename_ragmem=new_ragmem_name,
                filename_meta=new_meta_name,
                updated_at_utc=now,
            )

        logger_dev(
            (
                "MemoryFileManager.rename_history\n"
                f"file_id={clean_file_id}\n"
                f"old_ragmem={row['filename_ragmem']}\n"
                f"new_ragmem={new_ragmem_name}\n"
                f"old_meta={row['filename_meta']}\n"
                f"new_meta={new_meta_name}"
            ),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return {
            "success": True,
            "file_id": clean_file_id,
            "title": clean_title,
            "filename_ragmem": new_ragmem_name,
            "filename_meta": new_meta_name,
        }

    def delete_history(self, file_id: str) -> dict[str, Any]:
        """
        Delete one memory history.

        Deletes:
        - physical .ragmem
        - physical .ragmeta.json
        - SQLite memory_files row
        - SQLite memory_records rows
        - memory vectors by file_id
        """
        clean_file_id = self._clean_file_id(file_id)
        row = self._lookup_file(clean_file_id)

        if not row:
            raise ValueError(f"Memory history not found: {clean_file_id}")

        ragmem_path = self.memory_manager.files_root / row["filename_ragmem"]
        meta_path = self.memory_manager.files_root / row["filename_meta"]

        vectors_deleted = 0
        if self.memory_vector_store is not None and hasattr(self.memory_vector_store, "delete_file"):
            vector_result = self.memory_vector_store.delete_file(clean_file_id)
            vectors_deleted = int(vector_result.get("deleted_vectors", 0) or 0)

        self._delete_sqlite_rows(clean_file_id)

        if ragmem_path.exists():
            ragmem_path.unlink()

        if meta_path.exists():
            meta_path.unlink()

        if self.memory_manager.file_id == clean_file_id:
            self._reset_active_memory_manager()

        logger_dev(
            (
                "MemoryFileManager.delete_history\n"
                f"file_id={clean_file_id}\n"
                f"filename_ragmem={row['filename_ragmem']}\n"
                f"filename_meta={row['filename_meta']}\n"
                f"vectors_deleted={vectors_deleted}"
            ),
            "DEBUG",
            "CONFIDENTIAL",
        )

        return {
            "success": True,
            "file_id": clean_file_id,
            "title": row["title"],
            "filename_ragmem": row["filename_ragmem"],
            "filename_meta": row["filename_meta"],
            "vectors_deleted": vectors_deleted,
        }

    def _lookup_file(self, file_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.memory_manager.sqlite_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT file_id, title, filename_ragmem, filename_meta,
                       created_at_utc, updated_at_utc, record_count
                FROM memory_files
                WHERE file_id = ?
                """,
                (file_id,),
            ).fetchone()

        return dict(row) if row else None

    def _insert_empty_file_row(
        self,
        *,
        file_id: str,
        title: str,
        filename_ragmem: str,
        filename_meta: str,
        created_at_utc: str,
        updated_at_utc: str,
    ) -> None:
        with sqlite3.connect(self.memory_manager.sqlite_path) as conn:
            conn.execute(
                """
                INSERT INTO memory_files (
                    file_id, title, filename_ragmem, filename_meta,
                    created_at_utc, updated_at_utc, record_count
                )
                VALUES (?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(file_id) DO UPDATE SET
                    title = excluded.title,
                    filename_ragmem = excluded.filename_ragmem,
                    filename_meta = excluded.filename_meta,
                    created_at_utc = excluded.created_at_utc,
                    updated_at_utc = excluded.updated_at_utc,
                    record_count = excluded.record_count
                """,
                (
                    file_id,
                    title,
                    filename_ragmem,
                    filename_meta,
                    created_at_utc,
                    updated_at_utc,
                ),
            )
            conn.commit()

    def _update_sqlite_file_row(
        self,
        *,
        file_id: str,
        title: str,
        filename_ragmem: str,
        filename_meta: str,
        updated_at_utc: str,
    ) -> None:
        with sqlite3.connect(self.memory_manager.sqlite_path) as conn:
            conn.execute(
                """
                UPDATE memory_files
                SET title = ?,
                    filename_ragmem = ?,
                    filename_meta = ?,
                    updated_at_utc = ?
                WHERE file_id = ?
                """,
                (
                    title,
                    filename_ragmem,
                    filename_meta,
                    updated_at_utc,
                    file_id,
                ),
            )
            conn.commit()

    def _delete_sqlite_rows(self, file_id: str) -> None:
        with sqlite3.connect(self.memory_manager.sqlite_path) as conn:
            conn.execute(
                "DELETE FROM memory_records WHERE file_id = ?",
                (file_id,),
            )
            conn.execute(
                "DELETE FROM memory_files WHERE file_id = ?",
                (file_id,),
            )
            conn.commit()

    @staticmethod
    def _update_meta_json_file_fields(
        *,
        meta_path: Path,
        title: str,
        filename_ragmem: str,
        filename_meta: str,
        updated_at_utc: str,
    ) -> None:
        if not meta_path.exists():
            return

        try:
            with meta_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

        if not isinstance(data, dict):
            data = {}

        data["title"] = title
        data["filename_ragmem"] = filename_ragmem
        data["filename_meta"] = filename_meta
        data["updated_at_utc"] = updated_at_utc

        with meta_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _reset_active_memory_manager(self) -> None:
        self.memory_manager.file_id = uuid.uuid4().hex
        self.memory_manager.title = ""
        self.memory_manager.filename_ragmem = ""
        self.memory_manager.filename_meta = ""
        self.memory_manager.records = []
        self.memory_manager.metainfo = {}
        self.memory_manager.b_file_created = False

    @staticmethod
    def _extract_timestamp_prefix(filename_ragmem: str) -> str:
        text = str(filename_ragmem or "").strip()
        match = re.match(r"^(\d{4}-\d{2}-\d{2}-\d{2}-\d{2})-", text)
        if match:
            return match.group(1)

        return datetime.now().strftime("%Y-%m-%d-%H-%M")

    @staticmethod
    def _clean_file_id(file_id: str) -> str:
        clean_file_id = str(file_id or "").strip()
        if not clean_file_id:
            raise ValueError("file_id must not be empty.")
        return clean_file_id
```


## /home/rusbeh_ab/project/RAGstream/ragstream/utils

### ~\ragstream\utils\logging.py
```python
# -*- coding: utf-8 -*-
"""
SimpleLogger — tiny logging facade for RAGstream.

Goal:
- Avoid crashes when code calls SimpleLogger.info/debug/warning/error.
- Keep it trivial: one class with classmethods, printing to stdout.
- Later you can swap this to Python's 'logging' without touching callers.
"""

from __future__ import annotations
import sys
import datetime
from typing import ClassVar


class SimpleLogger:
    """
    Very small logging helper.

    Usage:
        SimpleLogger.info("message")
        SimpleLogger.debug("details")
    """

    _enabled: ClassVar[bool] = True
    _prefix: ClassVar[str] = "RAGstream"

    @classmethod
    def _log(cls, level: str, msg: str) -> None:
        if not cls._enabled:
            return
        now = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"{cls._prefix} | {level.upper():5s} | {now} | {msg}"
        print(line, file=sys.stdout, flush=True)

    @classmethod
    def debug(cls, msg: str) -> None:
        cls._log("DEBUG", msg)

    @classmethod
    def info(cls, msg: str) -> None:
        cls._log("INFO", msg)

    @classmethod
    def warning(cls, msg: str) -> None:
        cls._log("WARN", msg)

    @classmethod
    def error(cls, msg: str) -> None:
        cls._log("ERROR", msg)

    @classmethod
    def set_enabled(cls, enabled: bool) -> None:
        cls._enabled = enabled

    @classmethod
    def set_prefix(cls, prefix: str) -> None:
        cls._prefix = prefix
```

### ~\ragstream\utils\paths.py
```python
"""
Paths
=====
Centralises on-disk locations so a single import
(`from ragstream.utils.paths import PATHS`) gives typed access.
"""
from pathlib import Path
from typing import TypedDict

class _Paths(TypedDict):
    root:        Path
    data:        Path
    raw_docs:    Path
    chroma_db:   Path
    vector_pkls: Path
    logs:        Path

ROOT = Path(__file__).resolve().parents[2]

PATHS: _Paths = {
    "root":        ROOT,
    "data":        ROOT / "data",
    "raw_docs":    ROOT / "data" / "doc_raw",
    "chroma_db":   ROOT / "data" / "chroma_db",   # planned
    "vector_pkls": ROOT / "data" / "vector_pkls", # current persistence
    "logs":        ROOT / "logs",                 # present as a path; no persistent logging required
}
```

