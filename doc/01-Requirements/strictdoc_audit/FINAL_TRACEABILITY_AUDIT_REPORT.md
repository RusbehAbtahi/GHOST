# Final result

**FINAL TRACEABILITY AUDIT: NOT OK**

I audited **12 CSV files containing 1,592 rows**. I found **257 remaining incorrect rows**.

This large count does **not** mean the first GitHub audit overlooked 257 rows it had examined. The earlier GitHub prompts explicitly said **“audit only rows marked TRACED.”** Of the 257 findings below:

* **244 are currently `SYSTEM_WIDE` or `IMPLEMENTATION_PENDING`** and were therefore outside that first audit’s scope.
* **13 are currently `TRACED`** and represent actual remaining misses or later inconsistencies.

The dominant problem is the reverse of the first audit: many atomic, single-file requirements were classified too broadly as `SYSTEM_WIDE`, often using the same generic explanation despite the `.sdoc` assigning the complete behavior to one component. This is especially visible in files 51 and 52.

No repository content was modified.

---

# `00_ghost_srs_TRACEABILITY.csv`

### REMAINING FINDINGS — 12 rows

1. **`GHOST-SRS-NFR-INT-002`**
   Current: `TRACED` → `pipeline_runner.py`
   Correct: `IMPLEMENTATION_PENDING`
   Reason: Complete requirement–architecture–code synchronization is not implemented by the runner.
   Corrected explanation: `The required bidirectional synchronization and contradiction detection across requirements, architecture, implementation, and verification assets is not implemented.`

2. **`GHOST-SRS-FR-ORCH-001`**
   Current: `TRACED` → `controller.py`
   Correct: `SYSTEM_WIDE`
   Reason: The complete orchestration flow requires controller, runner, preprocessing, retrieval, memory, A3, A4, and projection components.
   Corrected explanation: `The end-to-end Prompt Builder orchestration spans several independently owned runtime components; controller.py coordinates calls but does not own their complete behavior.`

3. **`GHOST-SRS-FR-AGT-002`**
   Current: `TRACED` → `controller.py`
   Correct: `SYSTEM_WIDE`
   Reason: Agent configuration, composition, provider execution, parsing, and concrete-agent processing have separate owners.
   Corrected explanation: `Configuration-driven agent execution spans AgentFactory, AgentPrompt, LLMClient, configuration JSON, and concrete functional agents.`

4. **`GHOST-SRS-FR-KNOW-003`**
   Current: `TRACED` → `retriever.py`
   Correct: `SYSTEM_WIDE`
   Reason: Hybrid document retrieval requires dense retrieval, SPLADE, fusion, hydration, and orchestration.
   Corrected explanation: `Hybrid document retrieval requires Retriever, dense and sparse backends, RRF fusion, source hydration, and shared runtime state.`

5. **`GHOST-SRS-FR-KNOW-004`**
   Current: `TRACED` → `reranker.py`
   Correct: `SYSTEM_WIDE`
   Reason: Evidence selection and condensation include reranking, A3, A4 orchestration, LLM helpers, and deterministic finalization.
   Corrected explanation: `Document evidence refinement spans reranking, usefulness classification, evidence grouping, condensation, and SuperPrompt write-back.`

6. **`GHOST-SRS-FR-MEM-002`**
   Current: `TRACED` → `memory_manager.py`
   Correct: `SYSTEM_WIDE`
   Reason: Memory persistence includes records, manager, file manager, actions, metadata, SQLite, and importer behavior.
   Corrected explanation: `Durable memory recording and history management span several storage, record, action, and import components.`

7. **`GHOST-SRS-FR-MEM-003`**
   Current: `TRACED` → `controller.py`
   Correct: `SYSTEM_WIDE`
   Reason: Memory ingestion and retrieval span vector construction, persistence, lookup, scoring, compression, synthesis, and coordination.
   Corrected explanation: `Memory ingestion and retrieval require several independently owned memory components; controller.py only configures and invokes them.`

8. **`GHOST-SRS-FR-MEM-004`**
   Current: `TRACED` → `retriever_mem.py`
   Correct: `IMPLEMENTATION_PENDING`
   Reason: Memory permission is not enforced before synthesis and write-back.
   Corrected explanation: `The current memory retrieval path does not completely enforce allow_memory_context and memory_context_policy before producing and assigning memory context.`

9. **`GHOST-SRS-FR-MEM-005`**
   Current: `TRACED` → `memory_active_retrieval_brief.py`
   Correct: `SYSTEM_WIDE`
   Reason: ActiveBrief continuity includes builder algorithms, manager persistence, pending state, agent configuration, and retrieval-time use.
   Corrected explanation: `ActiveBrief creation, persistence, continuity state, retrieval-time consumption, and synthesis orientation span several files.`

10. **`GHOST-SRS-FR-UI-001`**
    Current: `TRACED` → `ui_streamlit.py`
    Correct: `SYSTEM_WIDE`
    Reason: The complete workbench includes Streamlit layout, actions, file actions, controller, session state, and runtime components.
    Corrected explanation: `The current workbench behavior spans the Streamlit entry point, action modules, controller integration, and session-managed runtime components.`

11. **`GHOST-SRS-FR-UI-002`**
    Current: `TRACED` → `ui_streamlit.py`
    Correct: `SYSTEM_WIDE`
    Reason: Prompt Builder execution and preview require UI, runner, controller, SuperPrompt, and projector behavior.
    Corrected explanation: `Prompt Builder execution and preview rendering span UI actions, pipeline coordination, shared state, and central prompt projection.`

12. **`GHOST-SRS-FR-EXT-001`**
    Current: `TRACED` → `superprompt_projector.py`
    Correct: `SYSTEM_WIDE`
    Reason: Final provider-ready output depends on upstream prompt, document, memory, attachment, and projection components.
    Corrected explanation: `The final provider-ready prompt combines artifacts produced by several subsystems and rendered by the central projector.`

---

# `10_orchestrator_and_pipeline_TRACEABILITY.csv`

### REMAINING FINDINGS — 10 rows

The following nine rows are currently `IMPLEMENTATION_PENDING` with blank artifacts but define implemented architectural or sibling-ownership boundaries rather than missing future behavior:

* `GHOST-ORCH-ROOT`
* `GHOST-ORCH-PRODUCT-NAME`
* `GHOST-ORCH-LOWER-LEVEL-OWNERSHIP`
* `GHOST-ORCH-BOUNDARY-AGENTSTACK`
* `GHOST-ORCH-BOUNDARY-DOCUMENT-INGESTION`
* `GHOST-ORCH-BOUNDARY-DOCUMENT-RETRIEVAL`
* `GHOST-ORCH-BOUNDARY-MEMORY`
* `GHOST-ORCH-BOUNDARY-GUI`
* `GHOST-ORCH-BOUNDARY-QUALITY`

**Correct status:** `SYSTEM_WIDE`
**Correct artifact:** blank

**Reason:** These UIDs define orchestrator scope, product identity, decomposition, or cross-subsystem ownership boundaries. They are not missing executable features.

**Corrected relationship explanation:**
`This UID establishes a system-level orchestration, naming, decomposition, or sibling-ownership boundary that applies across several requirement and implementation areas; no single Python file owns the complete scope.`

The boundary requirements explicitly allocate detailed behavior to sibling requirement families.

### `GHOST-ORCH-COMPOSE-OUTPUT`

Current: `IMPLEMENTATION_PENDING`
Correct: `TRACED`
Correct artifact: `superprompt_projector.py`
Path: `ragstream/orchestration/superprompt_projector.py`

Reason: The corrected requirement now assigns final rendering of `System_MD`, `Prompt_MD`, and `prompt_ready` to final composition while consuming existing `S_CTX_MD` and optional `Attachments_MD`.

Corrected relationship explanation:

`superprompt_projector.py owns final prompt projection by writing System_MD, Prompt_MD, and prompt_ready while consuming previously populated document-context and attachment fields without claiming ownership of their production.`

---

# `20_agent_stack_TRACEABILITY.csv`

### FINAL OK

`FINAL OK — No incorrect traceability rows found.`

The current division between `SYSTEM_WIDE` infrastructure contracts and atomic `TRACED` AgentFactory, AgentPrompt-helper, and LLMClient behaviors is consistent with the requirement’s explicit responsibility separation.

---

# `30_preprocessing_prompt_functions_TRACEABILITY.csv`

### REMAINING FINDINGS — 15 rows

The following rows are currently `SYSTEM_WIDE` with blank artifacts but require behavior that is presently incomplete:

* `GHOST-PREPROCESS-ROOT`
* `GHOST-PREPROCESS-CURRENT-SCOPE`
* `GHOST-PREPROCESS-END-TO-END-FLOW`
* `GHOST-PREPROCESS-KNOWLEDGE-BOUNDARY`
* `GHOST-PREPROCESS-SCHEMA-RUNTIME-MAPPING`
* `GHOST-PREPROCESS-MUST-DESTINATION`
* `GHOST-PREPROCESS-KNOWLEDGE-HANDOFF`
* `GHOST-PREPROCESS-HANDOFF-CONSISTENCY`
* `GHOST-PREPROCESS-AC-WEAK-SAME-QUERY`
* `GHOST-PREPROCESS-AC-WEAK-RELATED-QUERY`
* `GHOST-PREPROCESS-AC-WEAK-IRRELEVANT-QUERY`
* `GHOST-PREPROCESS-AC-QUERY-REBUILD`
* `GHOST-PREPROCESS-AC-HANDOFF`

**Correct status:** `IMPLEMENTATION_PENDING`
**Correct artifact:** blank

**Reason:** The final effective retrieval query is not rebuilt after ActiveBrief classification, and schema-facing `response_depth` and `output_format` are not consistently routed to runtime `depth` and `format`. Consequently, the promised synchronized handoff is incomplete.

**Corrected relationship explanation:**
`The complete requirement is not currently implemented because final routing-aware query reconstruction and/or required schema-to-runtime field mapping remains incomplete at the downstream handoff boundary.`

The requirement explicitly demands synchronized post-classification query construction and schema-to-runtime mappings.

### `GHOST-PREPROCESS-EMPTY-QUERY-SIGNAL`

Current: `TRACED` → `superprompt_projector.py`
Correct: `IMPLEMENTATION_PENDING`

Reason: The projector can produce an empty query, but the complete downstream suppression contract is not enforced before ordinary document-retrieval setup and validation.

Corrected relationship explanation:

`The projector can represent an empty routing result, but downstream orchestration does not yet completely treat it as an early document-retrieval suppression signal.`

### `GHOST-PREPROCESS-AC-FINAL-MODE`

Current: `SYSTEM_WIDE`
Correct: `TRACED`
Correct artifact: `superprompt_projector.py`
Path: `ragstream/orchestration/superprompt_projector.py`

Reason: The projector alone owns deterministic inclusion of the permitted ActiveBrief continuity material in the final prompt projection.

Corrected relationship explanation:

`superprompt_projector.py owns final_prompt_mode rendering and includes exactly the permitted ActiveBrief continuity material without independently redefining the routing state.`

---

# `40_knowledge_management_TRACEABILITY.csv`

### REMAINING FINDINGS — 9 rows

### `GHOST-KM-FLOW-QUERY`

Current: `SYSTEM_WIDE`
Correct: `IMPLEMENTATION_PENDING`

Reason: Knowledge retrieval does not reliably receive the finalized post-classification query required by the requirement.

Corrected relationship explanation:

`The prepared-query dependency is incomplete because final ActiveBrief-aware query reconstruction is not consistently completed before Knowledge Management begins.`

### `GHOST-KM-FLOW-RETRIEVAL`

Current: `SYSTEM_WIDE`
Correct: `TRACED` → `retriever.py`
Path: `ragstream/retrieval/retriever.py`

Corrected relationship explanation:

`retriever.py owns hydrated document-candidate creation, ordered retrieval-stage views, current selection identifiers, and retrieval-stage SuperPrompt write-back.`

### `GHOST-KM-FLOW-A3`

Current: `SYSTEM_WIDE`
Correct: `TRACED` → `a3_nli_gate.py`
Path: `ragstream/agents/a3_nli_gate.py`

Corrected relationship explanation:

`a3_nli_gate.py owns selection of the correct candidate view and document usefulness processing before A4.`

### `GHOST-KM-NO-MEMORY-IN-A3`

Current: `SYSTEM_WIDE`
Correct: `TRACED` → `a3_nli_gate.py`
Path: `ragstream/agents/a3_nli_gate.py`

Corrected relationship explanation:

`a3_nli_gate.py owns A3 document-only classification and contains no MemoryContextPack, memory retrieval, or memory-synthesis processing.`

The following five rows currently `SYSTEM_WIDE` describe configuration migration or validation that is not complete:

* `GHOST-KM-CONFIG-AUTHORITY`
* `GHOST-KM-CONFIG-SCOPE`
* `GHOST-KM-CONFIG-VALIDATION`
* `GHOST-KM-EFFECTIVE-CONFIG`
* `GHOST-KM-AC-CONFIG`

**Correct status:** `IMPLEMENTATION_PENDING`

**Corrected relationship explanation:**
`The required migration, validation, centralized consumption, and effective-value observability of Knowledge Management tuning parameters is not yet completely implemented.`

The requirements explicitly require versioned JSON control, validation, and run-level observability.

---

# `41_document_ingestion_TRACEABILITY.csv`

### FINAL OK

`FINAL OK — No incorrect traceability rows found.`

---

# `42_document_retrieval_and_reranking_TRACEABILITY.csv`

### FINAL OK

`FINAL OK — No incorrect traceability rows found.`

---

# `43_evidence_selection_and_condensation_TRACEABILITY.csv`

### REMAINING FINDINGS — 8 rows

The following configuration-migration rows are currently `SYSTEM_WIDE`:

* `GHOST-EVIDENCE-CONFIG-JSON`
* `GHOST-EVIDENCE-CONFIG-FIELDS`
* `GHOST-EVIDENCE-AC-CONFIG`

**Correct status:** `IMPLEMENTATION_PENDING`

**Reason:** Complete migration of A3/A4 operational parameters to validated versioned JSON has not occurred.

**Corrected relationship explanation:**
`The required JSON migration and validated runtime control of evidence-stage limits, thresholds, models, versions, and optional-stage settings remains incomplete.`

### A3 acceptance rows

The following rows are currently `SYSTEM_WIDE`:

* `GHOST-EVIDENCE-AC-A3-LABELS`
* `GHOST-EVIDENCE-AC-A3-SELECT`

**Correct status:** `TRACED`
**Correct artifact:** `a3_nli_gate.py`
**Path:** `ragstream/agents/a3_nli_gate.py`

**Corrected relationship explanation:**
`a3_nli_gate.py owns normalized A3 classification, invalid or missing-result handling, useful-only selection, hard selection limits, and final-selection identifier write-back.`

### A4 deterministic acceptance rows

The following rows are currently `SYSTEM_WIDE`:

* `GHOST-EVIDENCE-AC-A4-CLASSES`
* `GHOST-EVIDENCE-AC-A4-GROUP`
* `GHOST-EVIDENCE-AC-A4-BUDGET`

**Correct status:** `TRACED`
**Correct artifact:** `a4_det_processing.py`
**Path:** `ragstream/agents/a4_det_processing.py`

**Corrected relationship explanation:**
`a4_det_processing.py owns active-class validation, complete deterministic grouping, class-priority ordering, token-budget profile selection, and retained-group behavior.`

The A4 budget and grouping rules are deterministic requirements assigned to that processing component.

---

# `50_memory_management_TRACEABILITY.csv`

### REMAINING FINDINGS — 8 rows

All rows below are currently `SYSTEM_WIDE` with blank artifacts unless stated otherwise.

| UID                                | Correct status           | Correct artifact    |
| ---------------------------------- | ------------------------ | ------------------- |
| `GHOST-MEMORY-ONE-ACTIVE-HISTORY`  | `TRACED`                 | `memory_manager.py` |
| `GHOST-MEMORY-IDENTITY-SEPARATION` | `TRACED`                 | `memory_manager.py` |
| `GHOST-MEMORY-PARENT-TRACE`        | `TRACED`                 | `memory_record.py`  |
| `GHOST-MEMORY-SEMANTIC-ROLE`       | `TRACED`                 | `memory_scoring.py` |
| `GHOST-MEMORY-STARTUP-EMBEDDER`    | `TRACED`                 | `ui_streamlit.py`   |
| `GHOST-MEMORY-CONFIG-VALIDATION`   | `IMPLEMENTATION_PENDING` | blank               |
| `GHOST-MEMORY-AC-METADATA`         | `TRACED`                 | `memory_manager.py` |
| `GHOST-MEMORY-AC-EMPTY`            | `TRACED`                 | `retriever_mem.py`  |

Corrected relationship explanations:

* `memory_manager.py owns the single-active-history state, stable file identity versus mutable filenames, editable metadata overlay, and corresponding acceptance behavior.`
* `memory_record.py owns the optional parent_id field without changing record_id identity.`
* `memory_scoring.py owns selected semantic-chunk score, traceability, and recency metadata behavior.`
* `ui_streamlit.py owns startup construction of the configured memory vector embedder and collection.`
* Configuration validation row: `Validation of invalid memory budgets, thresholds, weights, window relationships, and required agent identities is not completely implemented.`
* `retriever_mem.py owns creation and SuperPrompt write-back of explicit empty retrieval packs with diagnostic reasons.`

The requirements assign these state and candidate contracts directly rather than making them cross-system responsibilities.

---

# `51_memory_recording_and_files_TRACEABILITY.csv`

### REMAINING FINDINGS — 85 rows

Every row in this section is currently:

* Status: `SYSTEM_WIDE`
* Artifact: blank

Each should be `TRACED` to the indicated artifact.

## `memory_record.py` — 28 rows

Path: `ragstream/memory/memory_record.py`

* `GHOST-MEM-REC-ID`
* `GHOST-MEM-REC-PARENT-ID`
* `GHOST-MEM-REC-CREATED-UTC`
* `GHOST-MEM-REC-INPUT`
* `GHOST-MEM-REC-OUTPUT`
* `GHOST-MEM-REC-SOURCE`
* `GHOST-MEM-REC-INPUT-HASH`
* `GHOST-MEM-REC-OUTPUT-HASH`
* `GHOST-MEM-REC-TAG`
* `GHOST-MEM-REC-USER-KEYWORDS`
* `GHOST-MEM-REC-AUTO-KEYWORDS`
* `GHOST-MEM-REC-PROJECT`
* `GHOST-MEM-REC-FILE-SNAPSHOT`
* `GHOST-MEM-REC-SOURCE-MODE`
* `GHOST-MEM-REC-LIST-NORMALIZATION`
* `GHOST-MEM-REC-YAKE`
* `GHOST-MEM-REC-YAKE-BASELINE`
* `GHOST-MEM-REC-YAKE-UNAVAILABLE`
* `GHOST-MEM-REC-EDITABLE-FIELDS`
* `GHOST-MEM-REC-RAGMEM-MARKERS`
* `GHOST-MEM-REC-RAGMEM-JSON`
* `GHOST-MEM-REC-RAGMEM-FIELDS`
* `GHOST-MEM-REC-RAGMEM-NO-EDITABLE`
* `GHOST-MEM-REC-RAGMEM-BACKWARD`
* `GHOST-MEM-REC-RAGMEM-NO-VECTORS`
* `GHOST-MEM-REC-META-RECORD-VIEW`
* `GHOST-MEM-REC-META-NO-STABLE-OVERWRITE`
* `GHOST-MEM-REC-HASH-INTEGRITY`

Reason: These are atomic `MemoryRecord` field, normalization, hashing, keyword-generation, serialization, or metadata-view contracts.

Corrected relationship explanation:

`memory_record.py owns the complete MemoryRecord field, normalization, hashing, keyword, serialization, or metadata-view behavior required by this UID.`

The `.sdoc` explicitly assigns these fields to `MemoryRecord`.

## `memory_manager.py` — 25 rows

Path: `ragstream/memory/memory_manager.py`

* `GHOST-MEM-REC-TAG-CATALOG`
* `GHOST-MEM-REC-GUI-TAG-VALIDATION`
* `GHOST-MEM-REC-GUI-KEYWORDS-TYPE`
* `GHOST-MEM-REC-GUI-SOURCE-MODE`
* `GHOST-MEM-REC-GUI-CHANGE-DETECTION`
* `GHOST-MEM-REC-INIT-NO-FILE`
* `GHOST-MEM-REC-INIT-ID`
* `GHOST-MEM-REC-CAPTURE-DEFAULTS`
* `GHOST-MEM-REC-AUTO-HISTORY`
* `GHOST-MEM-REC-RAGMEM-APPEND`
* `GHOST-MEM-REC-RAGMEM-CREATED-FLAG`
* `GHOST-MEM-REC-RAGMEM-READ`
* `GHOST-MEM-REC-RAGMEM-MALFORMED-BLOCK`
* `GHOST-MEM-REC-META-REBUILD`
* `GHOST-MEM-REC-META-FILE-FIELDS`
* `GHOST-MEM-REC-META-CREATED`
* `GHOST-MEM-REC-META-UPDATED`
* `GHOST-MEM-REC-META-AGGREGATES`
* `GHOST-MEM-REC-META-OVERLAY`
* `GHOST-MEM-REC-META-MISSING`
* `GHOST-MEM-REC-META-MALFORMED`
* `GHOST-MEM-REC-META-NO-RUNTIME`
* `GHOST-MEM-REC-CLOSE`
* `GHOST-MEM-REC-AC-CAPTURE`
* `GHOST-MEM-REC-AC-AUTHORITY`

Corrected relationship explanation:

`memory_manager.py owns the complete active-history, capture persistence, metadata reconstruction and overlay, SQLite synchronization, or history lifecycle behavior required by this UID.`

## `memory_actions.py` — 4 rows

Path: `ragstream/memory/memory_actions.py`

* `GHOST-MEM-REC-CAPTURE-SYNC-FIRST`
* `GHOST-MEM-REC-CAPTURE-RETURN`
* `GHOST-MEM-REC-NO-EMPTY-PAIR`
* `GHOST-MEM-REC-AC-EMPTY`

Corrected relationship explanation:

`memory_actions.py owns capture-action validation, metadata synchronization ordering, returned capture result, and rejection of empty prompt/response pairs.`

## `memory_file_manager.py` — 6 rows

Path: `ragstream/memory/storage/memory_file_manager.py`

* `GHOST-MEM-REC-FILE-LIST`
* `GHOST-MEM-REC-FILE-CREATE-TITLE`
* `GHOST-MEM-REC-FILE-CREATE`
* `GHOST-MEM-REC-FILE-CREATE-TIMES`
* `GHOST-MEM-REC-FILE-ID-VALIDATION`
* `GHOST-MEM-REC-AC-CREATE`

Corrected relationship explanation:

`memory_file_manager.py owns history listing, creation validation, empty-history creation, creation timestamps, file-id validation, and the corresponding creation acceptance behavior.`

## `chatgpt_shared_link_importer_helpers.py` — 15 rows

Path: `ragstream/memory/importers/chatgpt_shared_link_importer_helpers.py`

* `GHOST-MEM-REC-IMPORT-URL`
* `GHOST-MEM-REC-IMPORT-TITLE`
* `GHOST-MEM-REC-IMPORT-PLAYWRIGHT`
* `GHOST-MEM-REC-IMPORT-NAVIGATION`
* `GHOST-MEM-REC-IMPORT-EXTRACTION-ORDER`
* `GHOST-MEM-REC-IMPORT-STABILITY`
* `GHOST-MEM-REC-IMPORT-ROLES`
* `GHOST-MEM-REC-IMPORT-PAIRING`
* `GHOST-MEM-REC-IMPORT-RAW-FALLBACK`
* `GHOST-MEM-REC-IMPORT-RECORDS`
* `GHOST-MEM-REC-IMPORT-PARENT-CHAIN`
* `GHOST-MEM-REC-IMPORT-PROJECT-SNAPSHOT`
* `GHOST-MEM-REC-IMPORT-BRIEF`
* `GHOST-MEM-REC-IMPORT-PERSIST`
* `GHOST-MEM-REC-AC-IMPORT-FALLBACK`

Corrected relationship explanation:

`chatgpt_shared_link_importer_helpers.py owns the complete shared-link validation, browser extraction, message pairing, fallback construction, imported-record creation, parent chaining, snapshot assignment, brief handling, and persistence behavior required by this UID.`

## `chatgpt_shared_link_importer.py` — 2 rows

Path: `ragstream/memory/importers/chatgpt_shared_link_importer.py`

* `GHOST-MEM-REC-IMPORT-NO-CONTENT`
* `GHOST-MEM-REC-IMPORT-REPORT`

Corrected relationship explanation:

`chatgpt_shared_link_importer.py owns top-level import failure when no usable content exists and the final import result/report returned to the caller.`

## `ui_streamlit.py` — 2 rows

Path: `ragstream/app/ui_streamlit.py`

* `GHOST-MEM-REC-SESSION-MANAGER`
* `GHOST-MEM-REC-SESSION-STORE`

Corrected relationship explanation:

`ui_streamlit.py owns Streamlit-session initialization of the MemoryManager and MemoryVectorStore.`

## `ui_actions.py` — 1 row

Path: `ragstream/app/ui_actions.py`

* `GHOST-MEM-REC-MANUAL-FEED`

Corrected relationship explanation:

`ui_actions.py owns the manual memory-feed action, its input validation, metadata collection, snapshot preparation, and capture_memory_pair invocation.`

## `ui_actions_files.py` — 2 rows

Path: `ragstream/app/ui_actions_files.py`

* `GHOST-MEM-REC-FILES-ACTIONS`
* `GHOST-MEM-REC-WIDGET-CLEAR`

Corrected relationship explanation:

`ui_actions_files.py owns file-page operation delegation and clearing of per-record memory widget state after applicable history operations.`

---

# `52_memory_ingestion_and_retrieval_TRACEABILITY.csv`

### REMAINING FINDINGS — 99 rows

Unless explicitly noted, every row below is currently `SYSTEM_WIDE` with blank artifact and should become `TRACED`.

## `ui_streamlit.py` — 3 rows

Path: `ragstream/app/ui_streamlit.py`

* `GHOST-MEM-IR-STORE-DIR`
* `GHOST-MEM-IR-COLLECTION`
* `GHOST-MEM-IR-EMBEDDER`

Corrected explanation:

`ui_streamlit.py owns startup selection of the memory vector-store directory, collection name, and configured embedding implementation.`

## `memory_chunker.py` — 16 rows

Path: `ragstream/memory/ingestion/memory_chunker.py`

* `GHOST-MEM-IR-ENTRY-ROLES`
* `GHOST-MEM-IR-ONE-HANDLE`
* `GHOST-MEM-IR-EMPTY-ENTRY-FILTER`
* `GHOST-MEM-IR-ID-FORMAT`
* `GHOST-MEM-IR-ID-TRACEABILITY`
* `GHOST-MEM-IR-HANDLE-PROJECT`
* `GHOST-MEM-IR-HANDLE-YAKE`
* `GHOST-MEM-IR-HANDLE-NO-TAG-TEXT`
* `GHOST-MEM-IR-ENTRY-METADATA`
* `GHOST-MEM-IR-METADATA-SNAPSHOT`
* `GHOST-MEM-IR-TOKEN-APPROX`
* `GHOST-MEM-IR-PARAGRAPH-UNITS`
* `GHOST-MEM-IR-SENTENCE-UNITS`
* `GHOST-MEM-IR-HARD-SPLIT`
* `GHOST-MEM-IR-BLOCK-TARGET`
* `GHOST-MEM-IR-BLOCK-OFFSETS`

Corrected explanation:

`memory_chunker.py owns memory vector-entry roles, deterministic identifiers, handle construction, metadata snapshots, token approximation, paragraph/sentence splitting, hard splitting, block sizing, and source offsets.`

## `retriever_mem.py` — 32 rows

Path: `ragstream/retrieval/retriever_mem.py`

* `GHOST-MEM-IR-LIVE-METADATA-OVERLAY`
* `GHOST-MEM-IR-CONFIG-SHAPE`
* `GHOST-MEM-IR-ENABLED`
* `GHOST-MEM-IR-MISSING-FILE-ID`
* `GHOST-MEM-IR-QUERY-PRIMARY`
* `GHOST-MEM-IR-QUERY-PROJECTOR`
* `GHOST-MEM-IR-QUERY-BODY-FALLBACK`
* `GHOST-MEM-IR-QUERY-PROMPT-FALLBACK`
* `GHOST-MEM-IR-EMPTY-QUERY`
* `GHOST-MEM-IR-LATEST-BRIEF`
* `GHOST-MEM-IR-SEMANTIC-ENABLE`
* `GHOST-MEM-IR-SEMANTIC-MAX`
* `GHOST-MEM-IR-RAW-HIT-LIMIT`
* `GHOST-MEM-IR-SEMANTIC-FILE-FILTER`
* `GHOST-MEM-IR-FILTER-FAILURE`
* `GHOST-MEM-IR-QUERY-EMBED`
* `GHOST-MEM-IR-RAW-HIT-SHAPE`
* `GHOST-MEM-IR-LIVE-EPISODE-METADATA`
* `GHOST-MEM-IR-K-NOT-CLOCK`
* `GHOST-MEM-IR-SEMANTIC-PARENT`
* `GHOST-MEM-IR-EPISODIC-ENABLE`
* `GHOST-MEM-IR-EPISODIC-CAP`
* `GHOST-MEM-IR-EPISODIC-LIVE-BODY`
* `GHOST-MEM-IR-EPISODIC-FILE-BODY`
* `GHOST-MEM-IR-EPISODIC-MERGE-ORDER`
* `GHOST-MEM-IR-EPISODIC-DEDUPE`
* `GHOST-MEM-IR-EPISODIC-SOURCE`
* `GHOST-MEM-IR-SP-CONTEXT`
* `GHOST-MEM-IR-SP-BRIEF`
* `GHOST-MEM-IR-SP-EXTRAS`
* `GHOST-MEM-IR-SP-NO-DOCUMENT-OVERWRITE`
* `GHOST-MEM-IR-SP-NO-STAGE`

Corrected explanation:

`retriever_mem.py owns memory-retrieval configuration interpretation, query construction, skip branches, vector-query orchestration, live metadata/body enrichment, episodic merging and capping, and memory-specific SuperPrompt write-back.`

The code performs semantic and deterministic candidate collection, pack construction, synthesis, and write-back in this component.

## `memory_vector_store.py` — 13 rows

Path: `ragstream/memory/ingestion/memory_vector_store.py`

* `GHOST-MEM-IR-STORE-PERSISTENT`
* `GHOST-MEM-IR-STORE-NO-TRUTH`
* `GHOST-MEM-IR-REPLACE-ID`
* `GHOST-MEM-IR-REPLACE-EMPTY`
* `GHOST-MEM-IR-STORE-DOCUMENTS`
* `GHOST-MEM-IR-STORE-METADATA-SANITIZE`
* `GHOST-MEM-IR-STORE-EMBED`
* `GHOST-MEM-IR-STORE-ADD`
* `GHOST-MEM-IR-STORE-REPLACE-REPORT`
* `GHOST-MEM-IR-STORE-QUERY-EMPTY`
* `GHOST-MEM-IR-STORE-QUERY`
* `GHOST-MEM-IR-STORE-COUNT-SAFE`
* `GHOST-MEM-IR-STORE-REPLACEMENT-ATOMICITY`

Corrected explanation:

`memory_vector_store.py owns persistent memory-vector storage, metadata sanitation, embedding, replacement, query, count, reporting, and current replacement-order behavior.`

The corresponding requirements assign persistent Chroma behavior and replacement semantics directly to `MemoryVectorStore`.

## `memory_ingestion_manager.py` — 6 rows

Path: `ragstream/memory/ingestion/memory_ingestion_manager.py`

* `GHOST-MEM-IR-ASYNC-SCHEDULE`
* `GHOST-MEM-IR-ASYNC-DUPLICATE`
* `GHOST-MEM-IR-ASYNC-CLEANUP`
* `GHOST-MEM-IR-ASYNC-STREAMLIT-CONTEXT`
* `GHOST-MEM-IR-ASYNC-NO-DURABLE-QUEUE`
* `GHOST-MEM-IR-IDEMPOTENT-REPRESENTATION`

Corrected explanation:

`memory_ingestion_manager.py owns asynchronous ingestion scheduling, duplicate-task suppression, task cleanup, Streamlit context handling, non-durable task behavior, and idempotent vector replacement orchestration.`

## `memory_scoring.py` — 20 rows

Path: `ragstream/memory/retrieval/memory_scoring.py`

* `GHOST-MEM-IR-DISTANCE-INVALID`
* `GHOST-MEM-IR-GROUP-BY-RECORD`
* `GHOST-MEM-IR-ROLE-MAX`
* `GHOST-MEM-IR-NO-PNORM-PARENT`
* `GHOST-MEM-IR-PARENT-DIAGNOSTICS`
* `GHOST-MEM-IR-SOURCE-MODE-QA`
* `GHOST-MEM-IR-SOURCE-MODE-A`
* `GHOST-MEM-IR-SOURCE-MODE-Q`
* `GHOST-MEM-IR-SOURCE-MODE-FALLBACK`
* `GHOST-MEM-IR-EXCLUDED-TAGS`
* `GHOST-MEM-IR-EPISODIC-WEIGHTS`
* `GHOST-MEM-IR-WEIGHT-NORMALIZATION`
* `GHOST-MEM-IR-PARENT-RANK`
* `GHOST-MEM-IR-SEMANTIC-ROLES`
* `GHOST-MEM-IR-SEMANTIC-WEIGHTS`
* `GHOST-MEM-IR-SEMANTIC-HALF-LIFE`
* `GHOST-MEM-IR-SEMANTIC-SORT`
* `GHOST-MEM-IR-SEMANTIC-TRACE`
* `GHOST-MEM-IR-CONFIG-PARENT-WEIGHTS`
* `GHOST-MEM-IR-CONFIG-TAG-CATALOG`

Corrected explanation:

`memory_scoring.py owns vector-distance normalization, record grouping, role aggregation, source-mode weighting, exclusion policy, recency, ranking, semantic selection, and scoring-policy diagnostics.`

## `controller.py` — 4 rows

Path: `ragstream/app/controller.py`

* `GHOST-MEM-IR-CONTROLLER-CONFIG`
* `GHOST-MEM-IR-CONTROLLER-ORDER`
* `GHOST-MEM-IR-CONTROLLER-FAILURE`
* `GHOST-MEM-IR-CONTROLLER-NOT-CONFIGURED`

Corrected explanation:

`controller.py owns MemoryRetriever construction, current document-before-memory call ordering, retrieval failure isolation, and the unconfigured-retriever skip branch.`

## `superprompt_projector.py` — 1 row

Path: `ragstream/orchestration/superprompt_projector.py`

* `GHOST-MEM-IR-NORMAL-PREVIEW`

Corrected explanation:

`superprompt_projector.py owns the normal prompt preview and renders synthesized memory context rather than raw MemoryContextPack diagnostics.`

## Configuration migration — 1 row

### `GHOST-MEM-IR-CONFIG-MIGRATION`

Current: `SYSTEM_WIDE`
Correct: `IMPLEMENTATION_PENDING`

Corrected explanation:

`Migration of remaining memory ingestion and retrieval tuning values into validated versioned JSON configuration is not complete.`

## Acceptance rows — 3 rows

* `GHOST-MEM-IR-AC-ENTRIES`
  Correct: `TRACED` → `memory_chunker.py`
  Explanation: `memory_chunker.py owns creation of the required handle, question, and answer vector-entry forms with stable traceability.`

* `GHOST-MEM-IR-AC-ASYNC-FAIL`
  Correct: `TRACED` → `memory_ingestion_manager.py`
  Explanation: `memory_ingestion_manager.py owns asynchronous-ingestion failure reporting and cleanup without invalidating durable memory truth.`

* `GHOST-MEM-IR-AC-IDEMPOTENT`
  Correct: `TRACED` → `memory_vector_store.py`
  Explanation: `memory_vector_store.py owns deterministic replacement of the existing vector representation for a record rather than accumulating duplicate entries.`

---

# `53_memory_merge_activebrief_blackboard_TRACEABILITY.csv`

### REMAINING FINDINGS — 11 rows

### Configuration requirements

* `GHOST-MEM-MERGECFG-MIGRATION`
* `GHOST-MEM-MERGECFG-VALIDATION`

Current: `SYSTEM_WIDE`
Correct: `IMPLEMENTATION_PENDING`

Corrected explanation:

`Migration and validation of all memory transformation parameters, budgets, thresholds, window relationships, and required agent identities is not yet complete.`

### `GHOST-MEM-MERGE-ERROR-EMPTY`

Current: `SYSTEM_WIDE`
Correct: `TRACED` → `memory_merge_synthesizer.py`

Corrected explanation:

`memory_merge_synthesizer.py owns explicit empty-context results and diagnostics when synthesis is skipped or fails.`

### `GHOST-MEM-MERGE-LOG-GATE`

Current: `SYSTEM_WIDE`
Correct: `TRACED` → `memory_activebrief_relevance_gate.py`

Corrected explanation:

`memory_activebrief_relevance_gate.py owns gate score summaries, selected-score counts, route diagnostics, and bounded text previews without exposing full vectors.`

### ActiveBrief acceptance rows

The following rows are currently `SYSTEM_WIDE`:

* `GHOST-MEM-MERGE-AC-RELATED`
* `GHOST-MEM-MERGE-AC-SKIP`
* `GHOST-MEM-MERGE-AC-TOPIC`
* `GHOST-MEM-MERGE-AC-BLACK`

Correct: `TRACED` → `memory_active_retrieval_brief.py`

Corrected explanation:

`memory_active_retrieval_brief.py owns related-update, unrelated-skip, confirmed-topic-shift, and Black-contributor exclusion behavior for ActiveBrief continuity.`

### Synthesis acceptance rows

The following rows are currently `SYSTEM_WIDE`:

* `GHOST-MEM-MERGE-AC-NO-EVIDENCE`
* `GHOST-MEM-MERGE-AC-FAILURE`

Correct: `TRACED` → `memory_merge_synthesizer.py`

Corrected explanation:

`memory_merge_synthesizer.py owns no-evidence LLM-call suppression and provider/parse-failure results with empty memory context and explicit diagnostics.`

### `GHOST-MEM-MERGE-AC-NO-BLACKBOARD`

Current: `IMPLEMENTATION_PENDING`
Correct: `SYSTEM_WIDE`

Reason: This is a present architectural acceptance boundary stating that existing runtime structures must not be misclassified as a Blackboard. It is not a future Blackboard implementation requirement.

Corrected relationship explanation:

`This acceptance criterion verifies the current system-wide architectural absence of a Blackboard protocol and prevents MemoryContextPack, SuperPrompt.extras, or pending-topic state from being represented as one.`

The `.sdoc` expressly says the current baseline must not identify those structures as a Blackboard subsystem.

---

# Final summary

* **CSV files audited:** 12
* **Total rows audited:** 1,592
* **Remaining incorrect rows:** 257
* **Files receiving `FINAL OK`:**

  * `20_agent_stack_TRACEABILITY.csv`
  * `41_document_ingestion_TRACEABILITY.csv`
  * `42_document_retrieval_and_reranking_TRACEABILITY.csv`
* **Files still containing findings:**

  * `00_ghost_srs_TRACEABILITY.csv`
  * `10_orchestrator_and_pipeline_TRACEABILITY.csv`
  * `30_preprocessing_prompt_functions_TRACEABILITY.csv`
  * `40_knowledge_management_TRACEABILITY.csv`
  * `43_evidence_selection_and_condensation_TRACEABILITY.csv`
  * `50_memory_management_TRACEABILITY.csv`
  * `51_memory_recording_and_files_TRACEABILITY.csv`
  * `52_memory_ingestion_and_retrieval_TRACEABILITY.csv`
  * `53_memory_merge_activebrief_blackboard_TRACEABILITY.csv`

# `FINAL TRACEABILITY AUDIT: NOT OK`
