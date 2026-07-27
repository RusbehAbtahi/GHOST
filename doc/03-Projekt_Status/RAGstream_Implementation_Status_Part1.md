# GHOST / RAGstream_Implementation_Status.md

Last update: 28.05.2026

Purpose:
- This file is a compact implementation status snapshot.
- It records what is already working now.
- It also records the currently agreed next implementation direction.
- It is not a requirement file and not a final roadmap.
- For future updates, newly added decisions and implementation changes should be date-stamped inside the relevant section so chronological evolution remains visible.
- [03.05.2026 / KW18 2026] This update adds the implemented Memory Recording layer, the implemented Memory Ingestion layer, and the corrected TextForge / RagLog logging layer.
- [06.05.2026 / KW19 2026] This update adds the corrected MemoryRecord persistence authority split, initial Memory Retrieval, MemoryContextPack wiring, server-side Memory Files management, tabbed Streamlit structure, auto-created memory histories, and the future ActiveRetrievalBrief requirement.
- [06.05.2026 / KW19 2026] This update also adds K-based recency scoring for Green episodic memory and semantic memory chunks.
- [13.05.2026 / KW20 2026] This update adds the immediate hardening work around A4 empty selection, hard retrieval similarity floor, A2 LLM bypass direction, and the new two-dimensional ActiveBrief Relation Classifier.
- [13.05.2026 / KW20 2026] This update also records the ActiveRetrievalBrief compression correction: ActiveBrief must reflect the topic well but remain compressed, normally 150–250 tokens for one narrow topic and at most 500 tokens for several related durable topics.
- [28.05.2026 / KW22 2026] This update records the public project naming as GHOST, the redesigned Streamlit frontend, the live Prompt Builder runner through A4, the ChatGPT shared-link memory import, runtime Memory Compression / MemoryMerge synthesis, updated Supporting Context rendering, and the Metrics visual demo. Blackboard is currently only a future/demo concept, not durable product functionality.

---

## 1. High-level picture

GHOST, formerly RAGstream, already has a stable foundation in thirteen major layers:

1. foundational prompt processing and GUI/controller structure,
2. JSON-based agent architecture with working A2, A3, and A4 stages,
3. project-based document ingestion with manifest-based file tracking,
4. hybrid document retrieval with dense first-pass selection + SPLADE scoring on the same candidate IDs + weighted RRF,
5. GUI-visible SuperPrompt rendering through `SuperPromptProjector`,
6. a working AWS Phase-1 deployment with persistent runtime data outside the image,
7. [03.05.2026 / KW18 2026] structured Memory Recording with durable `.ragmem`, `.ragmeta.json`, and SQLite persistence,
8. [03.05.2026 / KW18 2026] structured Memory Ingestion with dedicated memory vectors and TextForge / RagLog logging support,
9. [06.05.2026 / KW19 2026] initial Memory Retrieval with raw memory candidates, semantic chunks, episodic candidates, working memory, Direct Recall hook, and `MemoryContextPack`,
10. [06.05.2026 / KW19 2026] server-side Memory Files management through a dedicated FILES tab,
11. [13.05.2026 / KW20 2026] ActiveBrief relation classification around PreProcessing, producing independent prompt materiality and topic-relation signals for later deterministic routing,
12. [28.05.2026 / KW22 2026] redesigned GHOST frontend with product identity, sidebar navigation, main Prompt Builder workflow, live pipeline flowchart, Files import area, and Metrics visual demo,
13. [28.05.2026 / KW22 2026] runtime Memory Compression and MemoryMerge synthesis that turn selected memory candidates into synthesized Memory Context for SuperPrompt.

The pipeline now reaches from prompt input and A2 shaping to project-aware hybrid chunk selection from the active document database, and it also includes a deterministic ReRanker stage, a real A3 stage, and a live A4 Condenser that writes `S_CTX_MD`.

[03.05.2026 / KW18 2026] In addition to the document RAG pipeline, RAGstream now has a separate Memory subsystem path:

```text
accepted prompt + accepted response
→ Memory Recording
→ durable MemoryRecord truth
→ Memory Ingestion
→ dedicated memory vector store
→ Memory Retrieval
→ later Memory Merge / Compression
```

[06.05.2026 / KW19 2026] Memory Retrieval was implemented as an initial raw retrieval stage.

[28.05.2026 / KW22 2026] Memory Retrieval has moved beyond raw retrieval: runtime episodic Memory Compression and MemoryMerge synthesis are now wired, and synthesized Memory Context is written into SuperPrompt.

[13.05.2026 / KW20 2026] ActiveBrief relation classification is now introduced as a PreProcessing-adjacent classifier. It does not replace Memory Retrieval or MemoryMerge. It produces early routing signals about whether the current prompt is standalone and how it relates to the current ActiveBrief.

Current practical truth:

* Retrieval is implemented and working.
* Retrieval is no longer dense-only; it now includes a real SPLADE scoring branch and weighted RRF fusion.
* ReRanker is implemented and working in code.
* A3 is implemented and working in code as a real usefulness-classification stage over reranked candidates.
* [24.04.2026] A4 Condenser is implemented and working in code as a real three-call evidence-condensation stage after A3.
* [24.04.2026] `SuperPromptProjector` rendered the GUI-visible prompt with clear separation between System, Configuration, User, Retrieved Context Summary, and Raw Retrieved Evidence.
* [28.05.2026 / KW22 2026] `SuperPromptProjector` now renders a stronger priority separation between `## Current User Request` and `## Supporting Context`.
* [03.05.2026 / KW18 2026] Memory Recording is implemented and working as a durable structured-memory capture layer.
* [03.05.2026 / KW18 2026] Memory Ingestion is implemented and working as a separate vector-preparation layer after durable memory save.
* [03.05.2026 / KW18 2026] TextForge / RagLog has been corrected into a usable project logger with sink-based routing/filtering and GUI/CLI/file/archive output behavior.
* [06.05.2026 / KW19 2026] `LogDeveloper` is now used for detailed developer diagnostics in new Memory Retrieval and file-management related code.
* [06.05.2026 / KW19 2026] Memory Retrieval was implemented enough to retrieve raw memory candidates and write them into SuperPrompt state.
* [28.05.2026 / KW22 2026] Memory Retrieval now also performs runtime episodic compression and LLM-based MemoryMerge synthesis, then writes synthesized Memory Context into SuperPrompt.
* [06.05.2026 / KW19 2026] The FILES tab is implemented as a server-side memory-history manager backed by SQLite and RAGstream file operations.
* [13.05.2026 / KW20 2026] A4 now has empty-selection safety so zero selected A3-useful chunks can be handled gracefully instead of crashing.
* [13.05.2026 / KW20 2026] A hard retrieval similarity floor has been introduced before A3 to discard absolute rubbish retrieval results early; the current working threshold is `0.2`, but this remains a practical runtime parameter to be tested and adjusted.
* [13.05.2026 / KW20 2026] A2 PromptShaper now has a bypass direction: A2 LLM can be deactivated while deterministic/default prompt-shaping values still allow Retrieval to continue.
* [13.05.2026 / KW20 2026] ActiveBrief Relation Classifier now uses two outputs instead of the earlier failed five-state label: `prompt_materiality` and `topic_relation`.
* [28.05.2026 / KW22 2026] Prompt Builder is now the main frontend run path and executes PreProcessing → A2 → Retrieval → ReRanker/pass-through → A3 → A4.
* [28.05.2026 / KW22 2026] ChatGPT shared-link import is implemented in the FILES tab and can create normal memory histories from imported ChatGPT conversations.
* [28.05.2026 / KW22 2026] The Metrics page now contains an interactive visual pipeline demo; Hard Rules and General Settings remain placeholders.
* [28.05.2026 / KW22 2026] The Blackboard Actor selector is currently a demo/future UI concept only; it is not yet persisted as durable memory metadata.
* However, the current SPLADE and reranking branches have not consistently produced better results than normal embeddings in practical tests. They remain optional and should be evaluated cautiously rather than treated as automatically superior.

The currently agreed next implementation direction is:

* keep the existing Retrieval / ReRanker stage structure,
* keep the new hybrid Retrieval backbone,
* keep A3 as the current semantic usefulness gate,
* keep A4 as the current live condenser stage,
* keep the Memory Recording and Memory Ingestion truth stable,
* keep initial Memory Retrieval stable,
* keep runtime Memory Compression and MemoryMerge synthesis as the current memory-context path,
* preserve ActiveRetrievalBrief as the compact current working memory anchor,
* keep ActiveBrief relation classification as a PreProcessing-adjacent routing signal,
* continue hardening the FILES tab as the official server-side memory-history manager,
* harden the live Prompt Builder runner and final prompt/LLM-call boundary,
* postpone A5 and full Hard Rules behavior to a later phase because their final action is still open,
* keep ColBERT / reranking improvement as a later evaluation topic, not an immediate assumption.

---

## 2. What is already implemented

### 2.1 Foundational app structure

* A Streamlit GUI exists and has been redesigned toward the current GHOST product workflow.

  * Prompt input area exists.
  * Engineered Prompt display area exists.
  * Prompt Builder is the main visible execution button.
  * Manual pipeline buttons still exist under Advanced Controls.
  * Project-based ingestion controls exist and are now optionally shown from the sidebar.
  * Active project selection exists.
  * Embedded-file display for the selected project exists.
  * [03.05.2026 / KW18 2026] Manual Memory Feed exists.
  * [03.05.2026 / KW18 2026] Memory cards / memory display exists.
  * [03.05.2026 / KW18 2026] Runtime Log display exists and is connected to the TextForge / RagLog GUI sink.
  * [06.05.2026 / KW19 2026] The Streamlit app now has top-level tabs:

```text
Main
Files
Hard Rules
Metrics
General Settings
```

* [06.05.2026 / KW19 2026] The current tab responsibility is:

```text
MAIN
= current RAGstream working page

FILES
= server-side memory-history manager

HARD RULES
= placeholder for later hard-rule editor

METRICS
= interactive visual pipeline demo now; later observability / logs / token usage / diagnostics area

GENERAL SETTINGS
= placeholder for runtime and application settings
```

* [06.05.2026 / KW19 2026] The tab structure is defined in `ui_streamlit.py`, while the MAIN tab still calls the existing `render_page()` from `ui_layout.py`.
* [28.05.2026 / KW22 2026] The sidebar now contains GHOST branding, page navigation, optional file-ingestion and advanced-control toggles, and a live 8-step pipeline flowchart.
* [28.05.2026 / KW22 2026] The MAIN page now includes the GHOST product identity header, LLM Call row with model selector, Prompt Builder row, Manual Memory Feed row, Engineered Prompt panel, progress/status area, Runtime Log, Project Context, and a right-side memory panel.
* [28.05.2026 / KW22 2026] The FILES tab now also contains ChatGPT shared-link import controls.
* [28.05.2026 / KW22 2026] The Metrics tab now contains an interactive visual path demo.
* [28.05.2026 / KW22 2026] The Blackboard Actor selector in memory cards is currently demo/future UI only and should not be described as a completed persisted feature.
* The current GUI supports prompt processing, project creation, file ingestion, active project selection, embedded-file display, manual memory recording, runtime log visibility, and server-side memory-file management.
* [13.05.2026 / KW20 2026] GUI-side control direction includes keeping optional bypasses for slow or low-value stages, especially A2 LLM and optional SPLADE / ColBERT reranking branches.

### 2.2 Deterministic prompt preprocessing

* Deterministic Pre-Processing is implemented.

  * Markdown/header parsing exists.
  * Schema-based field mapping exists.
  * MUST/default handling exists.
  * `prompt_ready` generation exists for the current preprocessing path.
* This stage is already part of the live GUI/controller wiring and acts as the first normalization layer for user input.
* [03.05.2026 / KW18 2026] PreProcessing logging now uses the corrected project-level RagLog import pattern.
* [13.05.2026 / KW20 2026] ActiveBrief relation classification is called around the PreProcessing button flow, after deterministic preprocessing, while the classifier logic remains separate from `preprocessing.py`.

### 2.3 JSON-based agent architecture

* JSON-based agent infrastructure is implemented.

  * `AgentFactory` exists.
  * JSON agent loading and transparent config-level caching exist.
  * `LLMClient` exists.
  * [24.04.2026] `LLMClient.responses(...)` exists for A4 / reasoning-style calls, in addition to the existing `chat(...)` path.
  * `AgentPrompt` architecture exists.
* A2 PromptShaper is implemented and already wired.

  * It reads the current `SuperPrompt`.
  * It uses a JSON-configured agent prompt.
  * It calls the LLM.
  * It writes selected values back into `SuperPrompt`.
  * [24.04.2026] It now applies deterministic selector sanitization after parsing and before write-back; invalid, cross-field, invented, malformed, and duplicate ids are removed.
  * [24.04.2026] If a field becomes empty after sanitization, A2 preserves the existing preprocessing value instead of applying catalog defaults.
  * It updates stage/history.
  * [13.05.2026 / KW20 2026] A2 LLM bypass direction is implemented so the pipeline can proceed with deterministic/default A2 values when the A2 LLM call is deactivated.
* A3 NLI Gate is implemented and already wired.

  * It reads the reranked candidate set from the current `SuperPrompt`.
  * It uses the JSON-configured neutral Agent Stack.
  * It performs usefulness-only classification.
  * It writes `views_by_stage["a3"]`, `extras["a3_selection_band"]`, `extras["a3_item_decisions"]`, and `final_selection_ids`.
* [24.04.2026] A4 Condenser is now implemented and wired as the next live LLM-based stage after A3.
* [13.05.2026 / KW20 2026] ActiveBrief Relation Classifier is implemented as a new JSON-based classifier with a dedicated Python module and JSON config.
* [24.04.2026] The next implementation target after A4 was Prompt Builder.
* [28.05.2026 / KW22 2026] The Prompt Builder frontend runner is now implemented through A4. A5 and full Hard Rule behavior remain postponed because their final action is still open to revision.

### 2.4 SuperPrompt as shared state

* `SuperPrompt` exists as the central shared prompt object.
* It already stores:

  * canonical body fields,
  * stage,
  * stage history,
  * retrieval-related fields,
  * recent conversation placeholder fields,
  * rendered prompt fields.
* In the current implementation direction, `SuperPrompt` is the evolving shared state object across the pipeline rather than a one-off prompt string.
* A general `compose_prompt_ready()` path is part of the recent implementation direction so that later stages can reuse one central render logic instead of keeping rendering scattered across multiple modules.
* [24.04.2026] `SuperPromptProjector` rendered the GUI-visible SuperPrompt into explicit sections:

  * `## System`
  * `## Configuration`
  * `## User`
  * `## Retrieved Context`
* [28.05.2026 / KW22 2026] The current rendering now uses stronger priority separation:

  * `## System`
  * `## Configuration`
  * `## Current User Request`
  * `## Supporting Context`
* [28.05.2026 / KW22 2026] Supporting Context may contain Previous Conversation Summary, Previous Conversation Topic, synthesized Memory Context, Retrieved Project Evidence Summary, and Raw Retrieved Evidence.
* [28.05.2026 / KW22 2026] Raw memory candidates remain available as debug markdown but are no longer shown by default in the GUI-visible SuperPrompt preview.
* [06.05.2026 / KW19 2026] `SuperPrompt` now includes `memory_context_pack` as a runtime field.
* [28.05.2026 / KW22 2026] `SuperPrompt` also carries synthesized `memory_context_text`, ActiveBrief fields, and memory retrieval counts/diagnostics in `extras`.
* [13.05.2026 / KW20 2026] ActiveBrief relation outputs are written into `sp.extras`, including prompt materiality, topic relation, derived relation state, classifier-used flag, deterministic decision mapping, and the ActiveBrief snapshot.

### 2.5 Project-based ingestion

* Project-based ingestion is implemented and connected to the GUI.

  * Create Project button exists.
  * Add Files button exists.
  * Files are copied into `data/doc_raw/<project>`.
  * Ingestion runs automatically afterward.
* The project-specific storage model is implemented:

  * `data/doc_raw/<project>`
  * `data/chroma_db/<project>`
  * `data/splade_db/<project>`
  * `file_manifest.json` belongs to the matching Chroma DB project folder.
* The embedded-files list for the active project is visible in the GUI through the manifest/controller path.

### 2.6 Parallel dense + SPLADE document ingestion backend

* Parallel dense + SPLADE ingestion is implemented.

  * Loader exists.
  * Chunker exists.
  * Dense Embedder exists.
  * SPLADE Embedder exists.
  * Chroma vector store exists.
  * SPLADE vector store exists.
  * `IngestionManager` exists.
  * manifest-based diff/hash logic exists.
  * deterministic stable chunk IDs exist.
* The ingestion model now uses one canonical chunking pass and writes the same chunk IDs and metadata into both branches:

  * dense branch → `data/chroma_db/<project>`
  * sparse branch → `data/splade_db/<project>`
* This means ingestion is no longer conceptually dense-only.

### 2.7 Retrieval is implemented as a hybrid stage

* Retrieval is implemented as a deterministic, project-aware hybrid stage.
* Its logic now is:

  * read retrieval query text from the current `SuperPrompt`,
  * use `task`, `purpose`, and `context` as the retrieval source,
  * split the retrieval query into overlapping pieces,
  * run the dense embedding branch on the active project's Chroma document store,
  * select the dense top-k candidate IDs,
  * run the SPLADE sparse branch on the active project's SPLADE store for exactly those same dense-selected candidate IDs,
  * fuse both ranked lists with weighted RRF,
  * reconstruct the real chunk text from `doc_raw/<project>` using the same chunking logic as ingestion,
  * write the result back into `SuperPrompt`.
* Retrieval ranks chunks, reconstructs their text from `doc_raw/<project>`, and writes the selected chunks into `base_context_chunks`.
* [06.05.2026 / KW19 2026] `AppController.run_retrieval(...)` now also calls Memory Retrieval if `MemoryRetriever` is configured.
* [06.05.2026 / KW19 2026] Pressing the Retrieval button produced both document retrieval output and raw memory retrieval output.
* [28.05.2026 / KW22 2026] The Retrieval stage now also calls Memory Retrieval with runtime episodic compression and MemoryMerge synthesis when MemoryRetriever is configured. It still does not run A3 or A4; those remain later pipeline stages.
* [13.05.2026 / KW20 2026] A hard embedding similarity floor was added before A3 so absolute rubbish retrieval results can be discarded early. The current working value is `0.2` and is configured through runtime configuration.

### 2.8 Retrieval-related GUI/controller integration

* The Retrieval Top-K field exists in the GUI.
* The active project selector exists in the GUI.
* Snapshot keys such as `sp_pre`, `sp_a2`, `sp_rtv`, `sp_rrk`, and `sp_a3` exist so that stage-specific prompt states can be preserved as snapshots rather than overwritten mentally.
* Retrieval is already a live button path after PreProcessing and A2.
* ReRanker is also already wired as a live stage after Retrieval.
* A3 is already wired as a live stage after ReRanker.
* The current Super-Prompt rendering path can now show Retrieval-related score information in the GUI.
* [17.04.2026] The GUI/controller startup path is split into light startup plus background heavy initialization so the page appears before Retrieval / ReRanker warm-up is complete.
* [17.04.2026] Optional slow-component bypass controls are already live in Generation-1:

  * `use Retrieval Splade`
  * `use Reranking Colbert`
* [06.05.2026 / KW19 2026] `ui_streamlit.py` now configures Memory Retrieval during Streamlit startup after `MemoryManager` and `MemoryVectorStore` exist.
* [06.05.2026 / KW19 2026] `ui_actions.py` has a defensive `_ensure_memory_retrieval_configured(...)` helper so older sessions can still configure Memory Retrieval before running Retrieval.
* [13.05.2026 / KW20 2026] When optional reranking is disabled, the desired behavior was that Retrieval should prepare the state for A3 without forcing the user to press ReRanker only to pass values through.
* [28.05.2026 / KW22 2026] This pass-through behavior is now wired: Retrieval can initialize an A3-ready reranked view, and the Prompt Builder runner skips real ColBERT when `use_reranking_colbert` is disabled.

### 2.9 ReRanker is implemented

* ReRanker is implemented as a deterministic stage.
* It is no longer only a planned step.
* The currently implemented ReRanker direction is optional and should remain bypassable.
* Its logic is:

  * read the Retrieval candidates already stored in `SuperPrompt`,
  * rebuild one reranking query from:

    * `task`
    * `purpose`
    * `context`
  * dynamically clean chunk text before scoring,
  * score each `(query, chunk)` pair,
  * sort by reranker score,
  * write the reranked view back into `SuperPrompt`.
* ReRanker reranks Retrieval candidates and writes the reranked view back into `SuperPrompt`.
* [06.05.2026 / KW19 2026] ReRanker currently operates only on document retrieval results. Memory candidates remain separately stored in `SuperPrompt`.

### 2.10 A3 is implemented as a real stage

* A3 is implemented as a real semantic stage.
* It is no longer only a placeholder or abstract future idea.
* The current implemented A3 direction is:

  * usefulness-only classification over reranked candidates,
  * one global `selection_band`,
  * one usefulness decision per candidate chunk,
  * deterministic useful-first selection with borderline fallback.
* Important current A3 truth:

  * long real chunk ids are not shown to the LLM,
  * local chunk ids `1..N` are used in the prompt and mapped back internally,
  * chunk-internal heading markers are sanitized to avoid prompt-structure conflicts,
  * duplicate marking has been intentionally removed.
* A3 already performs meaningful semantic filtering and is considered good enough to keep as the current stage truth while the next work moves to Prompt Builder.
* [06.05.2026 / KW19 2026] A3 does not yet process raw memory candidates. Memory-specific semantic filtering is reserved for later MemoryMerge / Memory Compression design.
* [13.05.2026 / KW20 2026] A3 speed remains an open optimization topic. Current planned improvements are to reduce normal A3 prompt logging, compact `required_output`, carefully reduce max output tokens, preserve the same classification rules, and benchmark model/API-call variants using the same candidate set.

### 2.11 Why the current SPLADE / reranking direction is not accepted as final

* Practical evaluation showed that SPLADE and reranking have not consistently improved the already good dense Retrieval ranking.
* In important real examples, they sometimes made ranking quality worse instead of better.
* Therefore these branches are currently treated as optional evaluation branches, not as guaranteed quality improvements.
* The agreed direction is to keep the stage structure, keep bypass controls, and evaluate improvements carefully before increasing their weight.

### 2.12 A4 Condenser is implemented

* [24.04.2026] A4 Condenser is implemented as a live stage after A3.
* [24.04.2026] The implementation files are:

  * `ragstream/agents/a4_condenser.py`
  * `ragstream/agents/a4_det_processing.py`
  * `ragstream/agents/a4_llm_helper.py`
* [24.04.2026] A4 uses three exact JSON configurations:

  * `data/agents/a4_condenser/chunk_phraser/a4_1_001.json`
  * `data/agents/a4_condenser/chunk_classifier/a4_2_001.json`
  * `data/agents/a4_condenser/final_condenser/a4_3_001.json`
* [24.04.2026] The implemented workflow is:

  * prepare selected A3-useful chunks,
  * run Chunk Phraser,
  * prepare active class definitions,
  * run Chunk Classifier,
  * build grouped chunk package,
  * run Final Condenser,
  * finalize A4 output into SuperPrompt.
* [24.04.2026] A4 writes:

  * `S_CTX_MD`,
  * `views_by_stage["a4"]`,
  * `final_selection_ids`,
  * A4 diagnostic fields in `sp.extras`,
  * `stage = "a4"` and stage history.
* [24.04.2026] A4 uses `LLMClient.responses(...)` and stable `prompt_cache_key="a4_condenser_shared_prefix"` through `A4LLMHelper`.
* [24.04.2026] The final condenser prompt was corrected so A4 produces neutral internal context, not a polished final answer to the user.
* [24.04.2026] If classifier output is empty or unusable, A4 continues through fallback grouping instead of crashing; the warning belongs in logs/status, not inside the final SuperPrompt.
* [06.05.2026 / KW19 2026] A4 currently condenses document evidence, not MemoryContextPack content.
* [13.05.2026 / KW20 2026] A4 empty-selection safety is implemented. If A3 selects zero useful document chunks, A4 can finalize a controlled empty-selection state instead of crashing.

### 2.13 GUI-visible SuperPrompt rendering hardening

* [24.04.2026] `SuperPromptProjector.compose_prompt_ready()` hardened the GUI-visible SuperPrompt with stable top-level separation.
* [28.05.2026 / KW22 2026] The current render structure is:

  * `## System`
  * `## Configuration`
  * `## Current User Request`
  * `## Supporting Context`
* [28.05.2026 / KW22 2026] The current user request is explicitly marked as highest priority. Memory and retrieved evidence are explicitly marked as supporting background.
* [28.05.2026 / KW22 2026] A4 `S_CTX_MD` appears as Retrieved Project Evidence Summary under Supporting Context.
* [28.05.2026 / KW22 2026] Synthesized Memory Context appears under Supporting Context when available.
* [28.05.2026 / KW22 2026] Raw document chunks can still appear as Raw Retrieved Evidence for development/audit visibility and are hidden after A4/A5.
* [28.05.2026 / KW22 2026] Raw memory retrieval candidates remain available as debug markdown but are not shown by default in the SuperPrompt preview.
* [24.04.2026] Raw source Markdown headings inside retrieved chunks are neutralized to markers such as `[H1]`, `[H2]`, and `[H3]`.

### 2.14 AWS Phase-1 deployment

* AWS Phase-1 deployment is implemented and working.
* The current live deployment already provides:

  * GitHub Actions builds and pushes Docker image to ECR,
  * EC2 pulls the latest image and starts the container,
  * nginx reverse proxy is working,
  * HTTPS/TLS is working,
  * Route53 update is working,
  * SSM secret loading is working,
  * persistent runtime data on EC2/EBS is working.
* The public network path is already stable:

  * Route53 → AWS public IPv4 → EC2 → nginx → Docker → Streamlit.
* [03.05.2026 / KW18 2026] The Memory subsystem uses the same project-relative runtime-data principle under `data/memory/`. AWS documentation may still explicitly mention `doc_raw` and `chroma_db`; the Memory data path should be aligned with the persistent `/app/data` mount before AWS production use of Memory.
* [06.05.2026 / KW19 2026] The current architecture is still private-instance / single-user / single-workspace, even if deployed on AWS. It is not yet a multi-user SaaS design.
* [06.05.2026 / KW19 2026] Future multi-user extension remains possible through stable ownership identifiers such as `user_id` and `workspace_id` in SQLite, but this is not part of the current implementation.

### 2.15 TextForge / RagLog logging is implemented and corrected

* [03.05.2026 / KW18 2026] TextForge / RagLog is implemented as the project logging subsystem.
* The implemented logging files are:

  * `ragstream/textforge/TextForge.py`
  * `ragstream/textforge/TextSink.py`
  * `ragstream/textforge/FileSink.py`
  * `ragstream/textforge/CliSink.py`
  * `ragstream/textforge/GUISink.py`
  * `ragstream/textforge/RagLog.py`
* The logger architecture uses:

  * one `TextForge` facade,
  * multiple sinks,
  * sink-level type filtering,
  * sink-level sensitivity filtering,
  * `b_enable` routing flags.
* The current intended public logger functions in `RagLog.py` are:

  * `LogALL`
  * `LogNoGUI`
  * `LogConf`
  * [06.05.2026 / KW19 2026] `LogDeveloper`
* The corrected application import pattern is:

```python
from ragstream.textforge.RagLog import LogALL as logger
```

* [06.05.2026 / KW19 2026] New developer-diagnostic modules should additionally use:

```python
from ragstream.textforge.RagLog import LogDeveloper as _logger_dev
```

and use a wrapper such as:

```python
DEV_LOG_ENABLED = False

def logger_dev(*args, **kwargs):
    if DEV_LOG_ENABLED:
        return _logger_dev(*args, **kwargs)
    return None
```

* [13.05.2026 / KW20 2026] The wrapper must call `_logger_dev`, not `logger_dev`, otherwise it creates recursion when developer logging is enabled.
* The important corrected rule is:

  * `type` and `sensitivity` are message labels,
  * their default values are only fallback defaults,
  * `LogALL`, `LogNoGUI`, and `LogConf` must not apply additional semantic filtering,
  * filtering happens inside the sinks through `accept_types` and `accept_sensitivities`.
* Current sink routing intention:

  * `LogALL` routes to archive, public run file, CLI, and GUI.
  * `LogNoGUI` routes to archive, public run file, and CLI.
  * `LogConf` routes only to archive.
  * `LogDeveloper` routes detailed internal diagnostics according to the developer logging flag/configuration.
* The GUI log now receives public runtime messages through the GUI sink.
* The CLI and file/archive sinks can receive more detailed internal messages according to their own sink configuration.
* [03.05.2026 / KW18 2026] The previous `st.session_state.raglog` helper/wrapper direction has been rejected. Application modules should import the public RagLog function directly instead of passing logger objects through Streamlit state.
* [06.05.2026 / KW19 2026] Memory Retrieval developer diagnostics log detailed payloads such as vector hits, SQLite candidates, metadata, scores, and packed memory context through `logger_dev`.
* [06.05.2026 / KW19 2026] MAIN Runtime Log is append-style operational logging. FILES status messages are intentionally latest-action status only and overwrite previous FILES action state to avoid UI noise.
* [13.05.2026 / KW20 2026] ActiveBrief Relation Classifier developer logging is intentionally limited to LLM INPUT and LLM OUTPUT only, so prompt, ActiveBrief, raw model output, and parsed classifier values can be audited without extra deterministic decision noise.

### 2.16 Memory Recording is implemented

* [03.05.2026 / KW18 2026] Memory Recording is implemented as a first-class RAGstream subsystem.
* It is not runtime logging.
* It is not TextForge / RagLog.
* It is not a sink.
* It manages structured, reusable memory records.
* The implemented memory recording files are:

  * `ragstream/memory/memory_record.py`
  * `ragstream/memory/memory_manager.py`
  * `ragstream/memory/memory_actions.py`
* The central objects are:

  * `MemoryRecord`
  * `MemoryManager`
* `MemoryRecord` represents one accepted prompt/response memory unit.
* `MemoryManager` owns one active memory history and maintains:

  * `file_id`,
  * memory filenames,
  * live `records`,
  * metainfo,
  * `.ragmem` persistence,
  * `.ragmeta.json` persistence,
  * SQLite synchronization.
* `memory_actions.py` provides the workflow boundary for capturing memory pairs from the GUI and later from model/tool capture paths.
* The implemented persistent memory layout is:

```text
data/memory/
├── memory_index.sqlite3
├── vector_db/
└── files/
    ├── *.ragmem
    └── *.ragmeta.json
```

* Current Memory Recording behavior:

  * full Q/A remains the permanent truth,
  * `.ragmem` stores durable stable body data,
  * `.ragmeta.json` stores current readable editable metadata,
  * SQLite indexes memory histories and records,
  * GUI tag/source-mode/direct-recall edits are synchronized through MemoryManager logic.
* [06.05.2026 / KW19 2026] The persistence authority split was corrected:

```text
.ragmem
= stable append-only memory body

.ragmeta.json
= current readable/editable metadata mirror

SQLite
= current query/index layer
```

* [06.05.2026 / KW19 2026] Editable GUI metadata must not be written as authoritative mutable data into `.ragmem`.
* [06.05.2026 / KW19 2026] Editable GUI metadata includes:

```text
tag
user_keywords
retrieval_source_mode
direct_recall_key
```

* [06.05.2026 / KW19 2026] `.ragmem` should only contain stable body fields such as:

```text
record_id
parent_id
created_at_utc
input_text
output_text
source
input_hash
output_hash
```

* [06.05.2026 / KW19 2026] `sync_gui_edits(...)` updates RAM, `.ragmeta.json`, and SQLite. It must not rewrite `.ragmem`.
* [06.05.2026 / KW19 2026] `load_history(...)` loads stable body from `.ragmem` and overlays current metadata from `.ragmeta.json`.
* [06.05.2026 / KW19 2026] User Keywords were removed from the GUI, but the field remains in the data model as an empty/future-use metadata field.
* [06.05.2026 / KW19 2026] First memory history creation is now automatic. The previous manual “enter Memory Title before first save” flow was removed.
* [06.05.2026 / KW19 2026] When the first MemoryRecord is saved and no active memory history exists, RAGstream auto-creates the memory history name using the first available YAKE/auto keyword, with fallback to active project name, source, or `Memory`.
* [06.05.2026 / KW19 2026] Manual memory creation through the FILES tab is also supported through the `New Memory` action.
* Memory Recording intentionally does not perform:

  * semantic retrieval,
  * compression,
  * final memory-context generation.

### 2.17 Memory Ingestion is implemented

* [03.05.2026 / KW18 2026] Memory Ingestion is implemented as a separate layer after Memory Recording.
* The implemented memory ingestion files are:

  * `ragstream/memory/memory_ingestion_manager.py`
  * `ragstream/memory/memory_chunker.py`
  * `ragstream/memory/memory_vector_store.py`
* The central objects are:

  * `MemoryIngestionManager`
  * `MemoryChunker`
  * `MemoryVectorStore`
* The dedicated memory vector store is separate from document vector stores.
* The implemented memory vector path is:

```text
data/memory/vector_db/
```

* The conceptual Chroma collection is:

```text
memory_vectors
```

* Memory Ingestion reads accepted `MemoryRecord` objects from the live `MemoryManager.records`.
* Memory Ingestion creates deterministic vector entries for:

  * `record_handle`
  * `question`
  * `answer`
* The `record_handle` vector supports broad record discovery.
* The question vectors support matching a current question against earlier questions.
* The answer vectors support finding useful old answer material.
* Every memory vector entry links back to its parent `MemoryRecord` through metadata.
* Memory Ingestion keeps full Q/A truth in Memory Recording. The vector layer is only a retrieval index.
* Memory Ingestion uses embeddings but does not call an LLM.
* Memory Ingestion does not summarize, compress, or infer intent.
* Memory Ingestion is intended to be idempotent:

  * existing vectors for a record can be removed/replaced,
  * re-ingesting the same record should not create duplicate vector entries.
* Runtime flow now exists:

```text
Manual Memory Feed
→ memory_actions.py
→ MemoryManager.capture_pair(...)
→ durable MemoryRecord saved
→ MemoryIngestionManager.ingest_record_async(...)
→ MemoryChunker builds entries
→ MemoryVectorStore writes vectors
→ data/memory/vector_db/ updated
```

* Required ordering is implemented conceptually and in wiring:

  * memory truth is saved first,
  * vector ingestion is scheduled after durable save.
* If Memory Ingestion fails, Memory Recording remains valid.
* [03.05.2026 / KW18 2026] Async ingestion was introduced so normal GUI interaction does not wait for embedding/vector writing.
* [03.05.2026 / KW18 2026] A Streamlit `ScriptRunContext` warning was observed when the background ingestion thread logged through the GUI sink. The agreed fix is to attach the current Streamlit script context to the ingestion thread before `thread.start()` so `GuiSink` can update `st.session_state` without warning.
* [06.05.2026 / KW19 2026] `MemoryVectorStore` now supports deletion by `file_id` through `delete_file(...)` and counting by `file_id` through `count_file(...)`.
* [06.05.2026 / KW19 2026] Rename-safe memory design decision: memory vector metadata should not depend on `filename_ragmem` or `filename_meta`. Vector metadata should use stable identifiers such as `file_id`, `record_id`, `role`, and block/vector ids.
* [06.05.2026 / KW19 2026] Filenames remain mutable path/display fields, not vector identity fields.

### 2.18 Memory Retrieval, Compression, and MemoryMerge synthesis are implemented

* [06.05.2026 / KW19 2026] Initial Memory Retrieval was implemented.
* [28.05.2026 / KW22 2026] Memory Retrieval now includes runtime Memory Compression and MemoryMerge synthesis.
* The new implemented files are:

```text
ragstream/retrieval/retriever_mem.py
ragstream/memory/memory_context_pack.py
ragstream/memory/memory_index_lookup.py
ragstream/memory/memory_scoring.py
ragstream/memory/compression/memory_compressor.py
ragstream/memory/compression/memory_sentence_reducer.py
ragstream/memory/memory_merge_synthesizer.py
```

* The existing files updated for initial Memory Retrieval were:

```text
ragstream/app/controller.py
ragstream/app/ui_actions.py
ragstream/app/ui_streamlit.py
ragstream/orchestration/super_prompt.py
ragstream/orchestration/superprompt_projector.py
ragstream/memory/memory_vector_store.py
ragstream/config/runtime_config.json
```

* `retriever_mem.py` is located under `ragstream/retrieval/` because it is a retrieval-stage orchestrator.
* Helper modules remain under `ragstream/memory/`.
* The current Memory Retrieval design separates:

```text
MemoryRetriever
= stage orchestrator

MemoryIndexLookup
= SQLite + .ragmem body lookup

MemoryScorer
= vector-hit scoring and parent-record aggregation

MemoryContextPack
= runtime container for memory retrieval output, diagnostics, and synthesized Memory Context
```

* `MemoryContextPack` is a runtime object only.
* `MemoryContextPack` is not durable memory truth.
* `MemoryContextPack` currently carries:

```text
working_memory_candidates
episodic_candidates
semantic_memory_chunks
direct_recall_candidate
synthesized_memory_context
memory_synthesis_diagnostics
selection_diagnostics
token_budget_report
```

* Current retrieval result groups:

  * working memory candidates,
  * episodic parent-record candidates,
  * raw semantic memory chunks,
  * optional Direct Recall candidate,
  * synthesized Memory Context,
  * diagnostics.
* Memory Retrieval currently reads from:

  * current `SuperPrompt`,
  * active `MemoryManager`,
  * `MemoryVectorStore`,
  * `memory_index.sqlite3`,
  * runtime config under `memory_retrieval`.
* Memory Retrieval currently writes into:

  * `sp.memory_context_pack`,
  * `sp.memory_context_text`,
  * `sp.extras["memory_context_pack"]`,
  * `sp.extras["memory_context_text"]`,
  * `sp.extras["memory_debug_markdown"]`,
  * `sp.extras["memory_retrieval_counts"]`,
  * ActiveBrief title/body fields.
* Memory Retrieval does not run:

  * A3,
  * A4,
  * final Prompt Builder send/LLM-call behavior.
* [06.05.2026 / KW19 2026] Memory Retrieval is triggered when the normal Retrieval button runs, after document retrieval.
* [06.05.2026 / KW19 2026] `runtime_config.json` now contains `memory_retrieval` configuration, including:

  * tag catalog,
  * retrieval source modes,
  * parent score weights,
  * working memory limits,
  * episodic memory limits,
  * Direct Recall limits,
  * semantic memory chunk limits.
* [06.05.2026 / KW19 2026] Memory Retrieval scoring now includes K-based recency weighting. In this model, `k = 0` means the latest MemoryRecord, `k = 1` means one episode older, and so on.
* [06.05.2026 / KW19 2026] Green episodic memory now combines semantic relevance and recency:

```text
final_parent_score =
  green_semantic_weight * semantic_parent_score
+ green_recency_weight  * recency_score
```

* [06.05.2026 / KW19 2026] Semantic memory chunks also combine semantic relevance and recency, but with weaker recency influence than Green episodic memory.
* [06.05.2026 / KW19 2026] Current default values in `runtime_config.json` are:

```text
Green episodic memory:
- semantic = 0.75
- recency = 0.25
- half_life_k = 10

Semantic memory chunks:
- semantic = 0.90
- recency = 0.10
- half_life_k = 10
```

* [06.05.2026 / KW19 2026] Gold and Direct Recall remain outside the normal recency-decay path. Black records remain excluded from automatic Memory Retrieval.
* [06.05.2026 / KW19 2026] `MemoryContextPack` debug output now shows `semantic_score`, `recency_score`, `final_score`, and `episode_distance_k` for memory candidates.
* [28.05.2026 / KW22 2026] Runtime Memory Compression reduces selected episodic Q/A candidates against a query anchor and adds compressed runtime fields without modifying durable MemoryRecord truth.
* [28.05.2026 / KW22 2026] MemoryMergeSynthesizer uses compressed episodic candidates, semantic memory chunks, effective retrieval query text, and ActiveRetrievalBrief to produce one compact synthesized Memory Context.
* [28.05.2026 / KW22 2026] The synthesized Memory Context is query-dependent runtime data; it is not durable memory truth.

### 2.19 Server-side Memory Files tab is implemented

* [06.05.2026 / KW19 2026] The FILES tab is implemented as the official server-side memory-history manager.
* Implemented files:

```text
ragstream/app/ui_files.py
ragstream/app/ui_actions_files.py
ragstream/memory/memory_file_manager.py
```

* `ui_files.py` owns the FILES tab layout.
* `ui_actions_files.py` owns thin Streamlit callbacks.
* `memory_file_manager.py` owns real backend file operations.
* The FILES tab now lists memory histories from SQLite, not by raw manual file browsing.
* The FILES tab displays:

```text
Filename
Created
Updated
Records
```

* The table uses native `st.dataframe` row selection.
* The table supports frontend column sorting.
* The table uses soft alternating row coloring with:

```text
#E2FBD8
```

* Current known table-color limitation:

  * native `st.dataframe` frontend sorting does not re-run Python styling logic,
  * therefore alternating row colors remain based on backend order,
  * default backend order is still `updated_at_utc DESC`.
* The FILES tab supports:

```text
New Memory
Load
Rename
Delete
Import ChatGPT shared conversation
```

* `New Memory` creates an empty `.ragmem` + `.ragmeta.json`, inserts a SQLite `memory_files` row, and makes the new history active.
* `Load` calls `MemoryManager.load_history(file_id)` and makes the selected memory history active.
* `Rename` renames the physical `.ragmem` and `.ragmeta.json`, updates SQLite `memory_files`, and updates file-level fields inside `.ragmeta.json`.
* `Delete` deletes:

```text
physical .ragmem
physical .ragmeta.json
SQLite memory_files row
SQLite memory_records rows
memory vectors by file_id
```

* Delete uses a two-step confirmation flow where the user must type:

```text
delete
```

* [06.05.2026 / KW19 2026] Memory histories must be managed through RAGstream. Manual external rename/delete of `.ragmem` or `.ragmeta.json` can break the link between SQLite file_id and physical files.
* [06.05.2026 / KW19 2026] SQLite `memory_files` is the authority for memory-history listing and path resolution.
* [06.05.2026 / KW19 2026] Filenames are mutable path/display fields. `file_id` is the stable identity.
* [28.05.2026 / KW22 2026] The FILES tab now includes ChatGPT shared-link import. Imported conversations are converted into normal Q/A MemoryRecords, persisted as a normal memory history, and optionally vector-ingested.
* [28.05.2026 / KW22 2026] The importer supports an optional Summary / MemoryBrief assigned to imported records.
* [28.05.2026 / KW22 2026] The importer reconstructs code blocks as labeled code frames where possible.

### 2.20 ActiveRetrievalBrief requirement and current implementation status

* [06.05.2026 / KW19 2026] The `ActiveRetrievalBrief` design decision was captured for later MemoryMerge / Memory Compression work.
* [13.05.2026 / KW20 2026] ActiveRetrievalBrief generation/update is now present enough to be tested through memory histories and relation-classifier logging.
* The core idea remains:

```text
Each MemoryRecord gets its own immutable cumulative ActiveRetrievalBrief.
```

* It is not one global mutable brief.
* It is a query-independent historical snapshot attached to each MemoryRecord.
* It represents the conversation/work context from the beginning of the active memory history up to that MemoryRecord.
* Runtime should normally use:

```text
latest clean non-Black ActiveRetrievalBrief
```

* Current / intended fields:

```text
active_retrieval_brief_title
active_retrieval_brief
active_retrieval_brief_contributor_ids
```

* [28.05.2026 / KW22 2026] These ActiveRetrievalBrief fields are now part of the stable `.ragmem` body for MemoryRecord snapshots.

* [13.05.2026 / KW20 2026] The ActiveBrief summarizer JSON files were corrected so ActiveBrief is a compression, not an expansion.
* [13.05.2026 / KW20 2026] The current compression rule is:

```text
one narrow topic: target 150–250 tokens
several related durable topics: target 250–500 tokens
absolute maximum: 500 tokens
```

* [13.05.2026 / KW20 2026] ActiveBrief must not grow larger than the original reduced Q/A for a narrow single-topic exchange.
* [13.05.2026 / KW20 2026] ActiveBrief must not add checklists, rejected interpretations, operational implications, or implementation decisions unless those are explicitly present in the Q/A or previous brief.
* Intended future use for document retrieval:

```text
TASK
+ PURPOSE
+ CONTEXT
+ latest clean ActiveRetrievalBrief
```

* Intended future use for memory retrieval:

```text
current query support
+ latest clean ActiveRetrievalBrief
```

* `active_retrieval_brief_contributor_ids` are required so Black-tagged records can be avoided by selecting the latest brief whose contributors do not include Black records.
* ActiveBrief is now practically useful, but final MemoryMerge / final prompt injection behavior is still not complete.

### 2.21 ActiveBrief Relation Classifier is implemented

* [13.05.2026 / KW20 2026] ActiveBrief Relation Classifier is implemented as a separate PreProcessing-adjacent classifier.
* New / changed files:

```text
ragstream/preprocessing/activebrief_relation_classifier.py
data/agents/activebrief_relation_classifier/activebrief_relation_classifier_001.json
ragstream/app/controller.py
ragstream/app/ui_actions.py
```

* The first direct five-state classifier design was rejected after testing because it badly confused strong/weak and same/shifted topic.
* The implemented design is now two-dimensional:

```text
prompt_materiality:
  STRONG | WEAK

topic_relation:
  SAME_TOPIC | RELATED_DOMAIN | IRRELEVANT
```

* `prompt_materiality` means:

```text
STRONG
= current prompt has standalone semantic material and does not need memory/context to identify its task, topic, or information need.

WEAK
= current prompt depends mainly on previous context, ActiveBrief, or the preceding conversation.
```

* `topic_relation` means:

```text
SAME_TOPIC
= directly continues the ActiveBrief topic or clearly refers back to the previous discussion.

RELATED_DOMAIN
= different immediate topic but still inside the same broader professional, technical, engineering, IT, AI, software, cloud, RAGstream, or career domain.

IRRELEVANT
= unrelated domain or no useful contextual bridge to the ActiveBrief.
```

* Tested examples showed the new classifier works much better than the five-state version:

```text
What is next?
→ WEAK / SAME_TOPIC

Very Interesting
→ WEAK / SAME_TOPIC

Can you explain cloud engineering?
→ STRONG / RELATED_DOMAIN

What date is it?
→ STRONG / IRRELEVANT

Can you explain how to analyze text and context?
→ STRONG / SAME_TOPIC
```

* The classifier uses `LLMClient.responses(...)` with a short prompt cache key.
* Developer logging for this classifier now records only:

```text
ActiveBriefRelationClassifier LLM INPUT
ActiveBriefRelationClassifier LLM OUTPUT
```

* The deterministic mapping from these two classifier outputs to retrieval/display/memory behavior remains in Python and is not part of the LLM judgment.
* The current classifier writes these values into `SuperPrompt.extras`:

```text
activebrief_prompt_materiality
activebrief_topic_relation
activebrief_relation_state
activebrief_relation_llm_used
activebrief_relation_decision
activebrief_relation_activebrief
```

---

## 3. What is intentionally not complete yet

### 3.1 Prompt Builder

* `prompt_builder.py` exists as a project module and the deterministic final-assembly concept is defined in the requirements.
* [24.04.2026] Prompt Builder became the immediate next target after the successful A4 implementation.
* [28.05.2026 / KW22 2026] The frontend Prompt Builder runner is now implemented and runs PreProcessing → A2 → Retrieval → ReRanker/pass-through → A3 → A4.
* [28.05.2026 / KW22 2026] The remaining incomplete part is the final operational boundary after the engineered prompt is built: final LLM-call/send behavior, full Hard Rule integration, and any later A5 behavior.
* [28.05.2026 / KW22 2026] Prompt Builder should continue to stay aligned with `SuperPromptProjector` so GUI preview and final-send prompt assembly do not diverge.

### 3.2 A5 Format Enforcer

* A5 exists in the long-range 8-stage contract, but it is not a live completed operational stage.
* [21.04.2026] A5 is intentionally postponed to a later phase.
* [21.04.2026] Its future action may be revised before implementation, so the current requirement contract should be treated as provisional rather than implementation-locked.

### 3.3 Remaining MemoryMerge / Memory Compression hardening and final memory policy

* [03.05.2026 / KW18 2026] The older broad “conversation history ingestion” wording is no longer accurate as a description of the current Memory implementation.
* Memory Recording is now implemented.
* Memory Ingestion is now implemented.
* [06.05.2026 / KW19 2026] Initial raw Memory Retrieval is now implemented.
* [13.05.2026 / KW20 2026] ActiveRetrievalBrief generation/update and ActiveBrief relation classification exist.
* [28.05.2026 / KW22 2026] Runtime episodic Memory Compression and MemoryMerge synthesis are now implemented and wired into MemoryRetriever.
* What remains intentionally incomplete is:

  * final tuning of memory-context selection policy,
  * final Direct Recall override/priority behavior,
  * final relationship between synthesized Memory Context and Prompt Builder send boundary,
  * advanced memory-management GUI beyond the current FILES tab,
  * production-level evaluation of MemoryMerge output quality.
* Memory Retrieval now searches, reconstructs, compresses selected episodic candidates, synthesizes Memory Context, and writes it into SuperPrompt.
* Later hardening must decide exact priority, trimming, Direct Recall behavior, and final prompt inclusion policy.
* Memory Compression remains runtime-only and must never overwrite:

  * `MemoryRecord.input_text`,
  * `MemoryRecord.output_text`,
  * stable `.ragmem` body fields,
  * the durable truth of `.ragmeta.json`,
  * the durable truth of `memory_index.sqlite3`.

### 3.4 Logger production hardening

* [03.05.2026 / KW18 2026] TextForge / RagLog is implemented and corrected, but further production hardening may still be useful.
* Open points for later hardening:

  * final decision about normal vs developer logging mode,
  * final retention/rotation policy for archive and public run logs,
  * final AWS log persistence policy under `/app/data`,
  * possible regression tests for sink routing and filtering,
  * possible thread-safety hardening around GUI logging and background workers.
* These points do not block the current Memory Recording / Memory Ingestion / initial Memory Retrieval implementation.
* [06.05.2026 / KW19 2026] Metrics / Observability should be treated as a broader future UI area than just “logs.”
* [28.05.2026 / KW22 2026] The Metrics tab now has an interactive visual pipeline demo, but real logs/token usage/retrieval counts/memory diagnostics/cost/latency observability are still future work.
* [13.05.2026 / KW20 2026] Developer logging should stay compact by default. Full LLM INPUT/OUTPUT logging is useful for classifier debugging but should not become uncontrolled normal-mode logging.

### 3.5 Multi-user support

* [06.05.2026 / KW19 2026] GHOST is currently private-instance / single-user / single-workspace.
* Even on AWS, the current intended deployment is one private instance, not a multi-user SaaS system.
* Future extension is possible through stable ownership fields such as:

```text
user_id
workspace_id
file_id
record_id
```

* The future professional pattern would be:

```text
SQLite source of truth:
user_id → workspace_id → file_id → record_id → paths / metadata / vector references
```

* Files can remain in shared server-side storage as long as SQLite controls ownership, paths, and visibility.
* This is not implemented yet and is not required for the current single-user development path.

---

## 4. Current immediate implementation plan

### 4.1 Immediate next work order

[24.04.2026] The agreed document-RAG pipeline work order was:

1. keep current Retrieval / ReRanker / A3 / A4 truth stable,
2. implement Prompt Builder,
3. postpone A5,
4. revisit ReRanker improvement after the pipeline is stable through A4 and Prompt Builder.

[03.05.2026 / KW18 2026] After the KW18 Memory work, the Memory-subsystem work order was:

1. keep Memory Recording stable,
2. keep Memory Ingestion stable,
3. implement Memory Retrieval,
4. reconstruct parent-aware `MemoryContextPack`,
5. only then decide Memory Compression and SuperPrompt memory-section injection.

[06.05.2026 / KW19 2026] Status after that chat:

1. Memory Recording is stable enough to continue.
2. Memory Ingestion is stable enough to continue.
3. Initial Memory Retrieval is implemented.
4. Raw `MemoryContextPack` exists and is injected into SuperPrompt state / GUI preview.
5. Server-side FILES tab exists for Memory history management.
6. The next Memory-subsystem direction is MemoryMerge / Memory Compression, not another redesign of Recording/Ingestion.
7. The FILES tab should continue to be polished only where needed for presentation quality and safe server-side operations.
8. ActiveRetrievalBrief was captured as a future requirement for MemoryMerge.

[13.05.2026 / KW20 2026] Current status after that chat:

1. A4 empty-selection safety is implemented.
2. Hard retrieval similarity floor is implemented with current value `0.2`, but still needs practical testing and tuning.
3. A2 LLM bypass direction is implemented / prepared so Retrieval can proceed without forcing the A2 LLM call.
4. ActiveBrief Relation Classifier is implemented with two-dimensional output and tested successfully on representative prompts.
5. ActiveBrief summarizer rules were corrected to prevent oversized expansion.
6. ActiveBrief quality must still be tested with new memory histories, because old histories keep old oversized ActiveBriefs.
7. A3 optimization remains open: reduce noisy logging, compact required output, reduce max tokens carefully, and benchmark model/API choices without changing classification quality.

[28.05.2026 / KW22 2026] Current status after the GitHub review:

1. The public/current project name is GHOST; RAGstream remains legacy naming in older files and paths.
2. The Streamlit frontend has been redesigned around GHOST product identity, sidebar navigation, main Prompt Builder workflow, and right-side memory panel.
3. Prompt Builder frontend runner is implemented through A4.
4. ReRanker pass-through is implemented when ColBERT is disabled.
5. ChatGPT shared-link import is implemented in the FILES tab.
6. Runtime Memory Compression and MemoryMerge synthesis are implemented inside Memory Retrieval.
7. SuperPrompt rendering now separates Current User Request from Supporting Context.
8. Metrics has an interactive visual demo; Hard Rules and General Settings remain placeholders.
9. Blackboard is currently only a demo/future concept, not a persisted memory feature.

The two tracks remain related but separate:

```text
Document-RAG pipeline next:
  harden the live Prompt Builder runner
  define the final LLM-call/send boundary
  keep A5 and Hard Rules for later

Memory subsystem next:
  test and tune Memory Compression / MemoryMerge quality
  define final Direct Recall and final memory-context priority behavior
  continue ActiveBrief quality testing on new histories
```

### 4.2 Why this order is now preferred

* Retrieval is already strong enough to continue development.
* ReRanker is live enough to keep the stage contract while its long-term replacement is still open.
* A3 is already good enough to be treated as a real stage.
* [24.04.2026] A4 is now implemented and good enough to be treated as the current condenser stage.
* [13.05.2026 / KW20 2026] A4 is now safer because empty A3 selection does not have to crash the pipeline.
* [13.05.2026 / KW20 2026] ActiveBrief relation classification now provides an early, useful routing signal, but it does not remove the need for MemoryMerge.
* [28.05.2026 / KW22 2026] The biggest missing operational gap in the end-to-end document-RAG pipeline is now after the live Prompt Builder runner:

  * final LLM-call/send behavior,
  * full Hard Rule integration,
  * production decision on raw evidence vs. debug/audit evidence visibility,
  * later A5 behavior.
* Therefore the highest leverage in the document-RAG pipeline is hardening the live Prompt Builder boundary, not redesigning A3/A4.
* [06.05.2026 / KW19 2026] The initial Memory Retrieval gap was closed at raw-candidate level.
* [28.05.2026 / KW22 2026] The next Memory gap is no longer basic MemoryMerge existence. It is quality and policy hardening:

  * which memory episodes to keep,
  * how aggressively to compress them,
  * how Direct Recall should override normal memory,
  * how ActiveRetrievalBrief should support weak or corrective user turns,
  * how synthesized Memory Context should enter the final Prompt Builder boundary.

---

## 5. Compact bottom-line statement

GHOST is now beyond an ingestion + retrieval pipeline.
It already has:

* working preprocessing,
* working JSON-based Agent Stack,
* working A2,
* working project-based ingestion,
* working hybrid Retrieval,
* working deterministic ReRanker,
* working A3 usefulness filtering,
* [24.04.2026] working A4 evidence condensation into `S_CTX_MD`,
* [24.04.2026] hardened GUI-visible SuperPrompt rendering,
* working AWS Phase-1 deployment,
* [03.05.2026 / KW18 2026] working Memory Recording with `.ragmem`, `.ragmeta.json`, and SQLite persistence,
* [03.05.2026 / KW18 2026] working Memory Ingestion into a dedicated memory vector store,
* [03.05.2026 / KW18 2026] corrected TextForge / RagLog logging with archive/file/CLI/GUI sink routing,
* [06.05.2026 / KW19 2026] corrected MemoryRecord persistence authority split,
* [06.05.2026 / KW19 2026] auto-created memory histories from first accepted MemoryRecord,
* [06.05.2026 / KW19 2026] initial Memory Retrieval with `MemoryContextPack`,
* [06.05.2026 / KW19 2026] K-based semantic/recency scoring for Green episodic memory and semantic memory chunks,
* [06.05.2026 / KW19 2026] raw memory retrieval display inside SuperPrompt rendering,
* [06.05.2026 / KW19 2026] server-side FILES tab for New / Load / Rename / Delete memory histories,
* [06.05.2026 / KW19 2026] file-level delete cleanup across physical files, SQLite, and memory vectors,
* [13.05.2026 / KW20 2026] A4 empty-selection safety,
* [13.05.2026 / KW20 2026] hard retrieval similarity floor before A3,
* [13.05.2026 / KW20 2026] A2 LLM bypass direction,
* [13.05.2026 / KW20 2026] corrected ActiveBrief compression rules,
* [13.05.2026 / KW20 2026] implemented two-dimensional ActiveBrief Relation Classifier,
* [28.05.2026 / KW22 2026] public/current GHOST identity and README positioning,
* [28.05.2026 / KW22 2026] redesigned Streamlit frontend with sidebar navigation and live pipeline flowchart,
* [28.05.2026 / KW22 2026] live Prompt Builder runner through A4,
* [28.05.2026 / KW22 2026] ChatGPT shared-link import into normal memory histories,
* [28.05.2026 / KW22 2026] runtime Memory Compression and MemoryMerge synthesis,
* [28.05.2026 / KW22 2026] synthesized Memory Context injection into SuperPrompt,
* [28.05.2026 / KW22 2026] updated Current User Request / Supporting Context rendering,
* [28.05.2026 / KW22 2026] interactive Metrics visual demo.

[28.05.2026 / KW22 2026] The immediate document-RAG milestone is no longer basic Prompt Builder existence. The next work is hardening the live Prompt Builder boundary, defining final LLM-call/send behavior, and keeping A5 / Hard Rules for later.

[28.05.2026 / KW22 2026] The immediate Memory milestone is no longer basic MemoryMerge existence. Runtime Memory Compression and MemoryMerge synthesis are implemented; the next work is quality testing, Direct Recall policy, and final memory-context priority behavior.

[28.05.2026 / KW22 2026] Blackboard should be described only as a demo/future concept at this stage, not as persisted product functionality.