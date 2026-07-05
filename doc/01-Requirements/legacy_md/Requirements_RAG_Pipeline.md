# Requirements_RAG_Pipeline.md

Last update: 24.04.2026

Note for future maintenance:
- When new implementation-aligned decisions or stage changes are added here, they should be date-stamped inline so the chronology stays visible.

Goal: define the 8-step RAG pipeline (A0…A5 + Prompt Builder), how each stage mutates `SuperPrompt`, which parts are deterministic vs LLM/hybrid, and how the stages fit together in both manual (GUI buttons) and auto mode. This document assumes the data model in `super_prompt.py` and the agent stack described in `Requirements_AgentStack.md`.

---

## 1. Scope and assumptions

1. The pipeline is a single linear chain of stages, driven either:

   * manually via the 8 GUI buttons in the Generation-1 Streamlit GUI (`ui_streamlit.py`, `ui_layout.py`, `ui_actions.py`), or
   * automatically by the controller in the same order.
2. The canonical state carrier is `SuperPrompt` (class in `ragstream/orchestration/super_prompt.py`). All stages are **memoryless**: they take `(SuperPrompt, config)` as input, mutate it in a controlled way, and return it; no stage keeps its own long-lived internal memory.
3. Retrieval and reranking are fully **deterministic** at ranking level. Retrieval uses CPU-friendly dense + sparse retrieval, and ReRanker uses a bounded deterministic reranking stage. The current implementation is cross-encoder based; the agreed immediate next direction is ColBERT. All other “A-agents” use the neutral agent stack (`AgentFactory`, `AgentPrompt`, `llm_client`) defined in `Requirements_AgentStack.md`.
4. The pipeline is designed so that constants (N0, N1, …) are **configurable** via JSON/YAML; no hard-coded “magic numbers” are allowed in code.

---

## 2. Stage overview

### 2.1 Order of stages (GUI / controller)

Button sequence (manual mode), which is also the execution order in auto mode:

1. A0_PreProcessing
2. A2_PromptShaper
3. Retrieval
4. ReRanker
5. A3_NLI_Gate
6. A4_Condenser
7. A5_Format_Enforcer
8. Prompt_Builder

`SuperPrompt.stage` uses the fixed vocabulary:

* `"raw"` → initial
* `"preprocessed"` → after A0_PreProcessing
* `"a2"` → after A2_PromptShaper
* `"retrieval"` → after Retrieval
* `"reranked"` → after ReRanker
* `"a3"` → after A3_NLI_Gate
* `"a4"` → after A4_Condenser
* `"a5"` → after A5_Format_Enforcer (Prompt_Builder does not introduce a new stage).

`SuperPrompt.history_of_stages` is append-only and records each stage name as it completes.

### 2.2 Stage summary table

| Step | Name               | `stage` value  | Kind           | LLM usage                             | Agent role (Axis 4)                  | Main responsibility                                                                                                                                     |
| ---- | ------------------ | -------------- | -------------- | ------------------------------------- | ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1    | A0_PreProcessing   | `preprocessed` | Function/Agent | Deterministic + optional LLM fallback | Extractor + Chooser (if LLM enabled) | Canonicalize user prompt into `sp.body`, enforce MUST fields, build `prompt_ready`.                                                                     |
| 2    | A2_PromptShaper    | `a2`           | Agent          | LLM-only                              | Chooser                              | Classify `system`, `audience`, `tone`, `depth`, `confidence` from task/context/purpose.                                                                 |
| 3    | Retrieval          | `retrieval`    | Function       | No LLM                                | –                                    | Hybrid first-pass retrieval: dense branch selects the candidate IDs, SPLADE scores exactly those same candidate IDs, then weighted RRF populates `base_context_chunks` and `views_by_stage["retrieval"]`. |
| 4    | ReRanker           | `reranked`     | Function       | No LLM in the current code path       | –                                    | Current bounded cross-encoder reranking of top Retrieval candidates; agreed immediate next direction is ColBERT.                                        |
| 5    | A3_NLI_Gate        | `a3`           | Agent          | Hybrid                                | Multi-Chooser                        | LLM-based usefulness classification over the reranked candidates, write `views_by_stage["a3"]`, and update `final_selection_ids` with useful-first plus borderline fallback.            |
| 6    | A4_Condenser       | `a4`           | Agent          | LLM-only                              | Writer / Synthesizer                 | Run the implemented three-call condenser over A3-useful chunks and write the resulting `S_CTX_MD`, `views_by_stage["a4"]`, and final retained ids.       |
| 7    | A5_Format_Enforcer | `a5`           | Agent          | LLM-only                              | Writer/Extractor                     | Normalize instructions and output format rules in `sp.body`/`extras` so final answer obeys structure.                                                   |
| 8    | Prompt_Builder     | (stays `a5`)   | Function       | No LLM                                | –                                    | Render `System_MD`, `Prompt_MD`, `S_CTX_MD`, `Attachments_MD`, final `prompt_ready` from `SuperPrompt`.                                                 |

---

## 3. Common data model and invariants

All stages use the same `SuperPrompt` invariants:

1. `base_context_chunks` is the **authoritative set** of hydrated `Chunk` objects returned by the current project-document retrieval path for the session, de-duplicated by `id`. In the current implemented code path this is document/project retrieval, not conversation-history retrieval. No stage creates a second corpus; later stages only manipulate views on these chunks.
2. `views_by_stage[stage]` is an **ordered list of per-chunk stage snapshots** written by each stage that deals with retrieval results. In the current implementation the snapshot item is `(chunk_id, stage_score, stage_status)`. This keeps ranking/filter information next to the `chunk_id` without mutating the `Chunk` itself.
3. `final_selection_ids` always contains the current chosen `chunk_id`s for building `S_CTX_MD` and `Attachments_MD`. After A4 it reflects the token-budgeted subset that feeds the final LLM.
4. `Chunk` objects are **immutable** after creation. Scores and keep/drop status live in `views_by_stage` (and optionally in other stage-local metadata), not inside `Chunk`.
5. `System_MD`, `Prompt_MD`, `S_CTX_MD`, `Attachments_MD` remain the final rendered blocks for send-time use. `prompt_ready` may also be regenerated earlier for GUI preview purposes, either by stage-local helpers (A0/A2 current implementation) or by `SuperPrompt.compose_prompt_ready()` in later stages.
6. [24.04.2026] `S_CTX_MD` is condensed retrieved context. It is supporting context for the task, not user task text and not the final answer. GUI-visible rendering must keep it under a retrieved-context block rather than directly below the task.

---

## 4. Fixed numeric defaults (N-constants)

The pipeline uses named limits instead of uncontrolled magic numbers. The current retrieval implementation uses these practical defaults:

* `QUERY_CHUNK_SIZE = 1200`

  * Query decomposition window size for Retrieval. The same chunking idea as ingestion is reused.
* `QUERY_OVERLAP = 120`

  * Overlap between retrieval query pieces.
* `DEFAULT_TOP_K = 50`

  * Default GUI/runtime value for the number of Retrieval candidates to keep.
* `N1_RETR_MAX_CANDIDATES = 50`

  * Hard cap for the Retrieval result band after dense + SPLADE scoring over the dense-selected candidate set.
* `RRF_K = 60`

  * Current reciprocal-rank fusion constant.
* `RRF_WEIGHT_DENSE = 5.9`

  * Current weight for the dense branch in Retrieval fusion.
* `RRF_WEIGHT_SPLADE = 0.0`

  * Current weight for the SPLADE branch in Retrieval fusion.
* `N2_RERANK_TOP_K = 30`

  * Number of candidates from `views_by_stage["retrieval"]` passed into the ReRanker stage.
* `N2B_SPLITTER_MAX_TOKENS = 32`

  * Upper token limit for each meaning-based query part produced for the future ColBERT reranking path.
* `N3_FINAL_SELECTION_MAX = 24`

  * Upper bound on `final_selection_ids` after A4 (token budget + readability constraint).
* `N4_RECENT_CONV_MAX_PAIRS` (e.g. 8–12)

  * Max turn-pairs in `recentConversation` that may be included in the final prompt.

Requirements:

1. Retrieval limits must stay explicit and centralized; future cleanup may move all of them into a single config.
2. Stages treat these as **soft caps**: they can internally cut below the limit but never exceed the active runtime cap.
3. Query decomposition for Retrieval currently follows deterministic chunking (`chunk_size`, `overlap`) instead of the older `N0_QUERY_PIECES` wording.

---

## 5. Stage-by-stage requirements

### 5.1 A0_PreProcessing

Reference: `Req_PreProcessing.md` and the implemented `preprocessing.py`.

Purpose

* Convert raw user prompt text into a canonical `sp.body`, enforce MUST attributes, and generate a clean GUI snapshot in `sp.prompt_ready`. No retrieval, no LLM by default.

Inputs

* `user_text: str` – raw prompt from GUI.
* `sp: SuperPrompt` – preferably at `stage="raw"` (but may be re-run).
* `prompt_schema.json` – canonical keys, MUST keys, defaults, aliases, bilingual map, typo tolerance, etc.

Outputs / mutations

1. Header parsing and mapping:

   * Use the deterministic “mapping ladder” (normalize → exact → alias → tiny-typo → bilingual → templates → keyword → unknown).
   * Map headers into canonical keys `{system, task, audience, tone, depth, context, purpose, format, text, ...}`.
2. MUST enforcement:

   * Apply TASK/CONTEXT special rule and fill defaults for other MUST keys.
3. Write into `sp.body` only for known keys; unknowns go to `sp.extras["unknown_attributes"]`.
4. Build `sp.prompt_ready` with the current preprocessing compose helper and update stage:

   * `sp.stage = "preprocessed"`
   * `sp.history_of_stages.append("preprocessed")`
5. No changes to retrieval fields: `base_context_chunks`, `views_by_stage`, `final_selection_ids` remain untouched.
6. Migration note: the long-term target is to route this preview rendering through `SuperPrompt.compose_prompt_ready()`, but A0 currently still uses its stage-local helper.

Optional LLM fallback

* If `prompt_schema.modes.semantic_enabled = true`, A0 may call an LLM via the AgentStack as a **tiny Chooser agent** for header mapping, but:

  * It must still be deterministic at the pipeline level (fixed threshold, logged decisions).
  * All LLM operations and decisions are recorded into `sp.extras["semantic_used"]`, `normalized_map`, and `decisions`.

### 5.2 A2_PromptShaper

Purpose

* Classify the five meta-fields `system`, `audience`, `tone`, `depth`, `confidence` based on `task`, `context`, `purpose`, and the user prompt, using a fine-tuned OpenAI model (A2).

Nature

* Kind: Agent (uses AgentFactory, AgentPrompt, llm_client).
* Type: **Chooser** (closed enums, JSON output).
* LLM usage: LLM-only (stateless, single call per pass).

Inputs

* `sp: SuperPrompt` with `stage="preprocessed"`.
* A2 agent config JSON (see `Requirements_AgentStack.md`), containing:

  * Agent id / version (e.g. `"agent_meta": {"agent_id": "a2_promptshaper", "version": "003"}`).
  * Enum lists for `system`, `audience`, `tone`, `depth`, `confidence`.
  * Default values and thresholds (e.g. min confidence).
  * Underlying model id (e.g. `ft:gpt-4.1-mini-...`), temperature, etc.

Behaviour

1. A2 **pass-1**:

   * Build input payload from `sp.body["task"]`, `sp.body["context"]`, `sp.body["purpose"]`, and possibly the raw prompt text.
   * Through AgentFactory → AgentPrompt → llm_client, call the A2 model to get a JSON object:
     `{ "system": ..., "audience": ..., "tone": ..., "depth": ..., "confidence": ... }`.
   * [24.04.2026] After `AgentPrompt.parse(...)`, run a deterministic selector sanitizer before writing anything back into `SuperPrompt`.
   * [24.04.2026] The sanitizer removes invalid ids, cross-field ids, invented ids, malformed ids, and duplicate ids, while preserving the original selection order and enforcing each field's `max_selected` rule.
   * [24.04.2026] If a field becomes empty after sanitization, A2 must not apply catalog defaults as semantic repair. It must preserve the existing preprocessing value by not overwriting that field.
2. Update `sp.body` fields (`system`, `audience`, `tone`, `depth`, `confidence`) only for fields that still have valid sanitized output, and write selected ids into `sp.extras["a2_selected_ids"]`.
3. Bookkeeping:

   * `sp.stage = "a2"`
   * `sp.history_of_stages.append("a2")`
4. A2 **pass-2** (optional runtime refinement) uses the same model and agent config, but includes the earlier A2 output as part of the input payload. The requirement here is only to keep it **compatible**; details of pass-2 policies can be added later.
5. Current GUI snapshot rendering may still be produced by the existing A2 compose helper. Migration to `SuperPrompt.compose_prompt_ready()` is allowed later without changing the stage contract.

No retrieval fields are touched here.

### 5.3 Retrieval

Purpose

* Build the first ranked candidate list of chunks from the active project document stores.
* [14.04.2026] The current implemented Retrieval stage is hybrid and already uses dense + SPLADE + weighted RRF.
* [14.04.2026] The current candidate-selection rule is now fixed as: dense first, SPLADE second. Dense Retrieval selects the candidate IDs, and SPLADE must score exactly those same IDs instead of running an independent top-k search.

Nature

* Kind: Function (no LLM).
* Type: deterministic, CPU-friendly vector search.

Inputs

* `sp: SuperPrompt` with `stage="a2"`.
* Active project dense store (`data/chroma_db/<project>`), active project sparse store (`data/splade_db/<project>`), with raw source files in `data/doc_raw/<project>`.
* Config:

  * runtime `top_k`, query `chunk_size`, query `overlap`, dense embedding model name, SPLADE model/config, and RRF parameters.

Behaviour

1. Query decomposition:

   * Build a **normalized query string** from `sp.body["task"]`, `sp.body["context"]`, `sp.body["purpose"]`.
   * Split that query string with deterministic chunking (`chunk_size = 1200`, `overlap = 120`).
2. Dense branch:

   * Embed all query pieces with the dense embedding model.
   * Compare them against all stored dense vectors from the active project Chroma collection.
   * Aggregate per-chunk dense scores across pieces with p-norm averaging (`p = 10`).
   * Sort globally and select the active `top_k` dense candidate IDs.
3. SPLADE branch:

   * Encode all query pieces with the active SPLADE query encoder.
   * Compare them against the active project sparse store in `data/splade_db/<project>`.
   * Aggregate per-chunk sparse scores across pieces with p-norm averaging (`p = 10`).
   * [14.04.2026] SPLADE does not perform its own independent top-k selection anymore in the Retrieval stage.
   * [14.04.2026] SPLADE must score exactly the dense-selected candidate IDs from step 2.
4. Fuse both ranked lists with weighted reciprocal-rank fusion using the active RRF parameters.
5. [14.04.2026] The current implemented weighting is dense `5.9` and SPLADE `0.0`.
6. [14.04.2026] Because the current dense-selected IDs are also the SPLADE scoring set, every final Retrieval candidate is expected to have both dense and SPLADE score metadata available for GUI/debug display.
7. Reconstruct the real chunk text from `data/doc_raw/<project>` using the stored metadata (`path`, `chunk_idx`) and the same chunker. If a stale DB row points to a missing raw file, skip that row instead of failing the stage.
8. Populate `sp.base_context_chunks` with the hydrated `Chunk` objects.
9. Write:

   * `sp.views_by_stage["retrieval"] = [(chunk_id, retrieval_score, SELECTED), ...]` in fused score order.
   * `sp.final_selection_ids = [chunk_id_1, chunk_id_2, ...]` in the same order for the current GUI / intermediate stage view.
   * `sp.stage = "retrieval"` and append to history.
10. [14.04.2026] The neutral RRF merger remains branch-agnostic; retrieval-specific metadata names needed by rendering are projected in `Retriever` after fusion and before hydration/write-back.

The Retrieval step remains independent from ReRanker and A3.

### 5.4 ReRanker

Purpose

* Use a bounded reranking stage to refine the ranking of the top candidates from Retrieval without discarding the Retrieval backbone.

Nature

* Kind: Function.
* Type: deterministic at ranking level, with an optional helper agent for query splitting.

Inputs

* `sp: SuperPrompt` with `stage="retrieval"`.
* Candidate stage snapshots: first `N2_RERANK_TOP_K` items from `sp.views_by_stage["retrieval"]`.
* Current implemented model direction: cross-encoder reranking.
* Current implemented model: `cross-encoder/ms-marco-MiniLM-L-12-v2`.
* [14.04.2026] Immediate next direction: ColBERT.
* Optional helper agent: `NLP_Splitter` remains a future helper for the later ColBERT path.

Behaviour

1. Build one ReRanker query from `sp.body["task"]`, `sp.body["context"]`, and `sp.body["purpose"]`.
2. Read the bounded candidate pool from `sp.views_by_stage["retrieval"]`.
3. Dynamically clean chunk text before scoring, if needed by the current implementation.
4. Score each `(query, chunk)` pair with the active cross-encoder model.
5. Sort by reranker score.
6. Write:

   * `sp.views_by_stage["reranked"] = [(chunk_id, reranker_score, SELECTED), ...]` in the new order.
7. Update:

   * `sp.final_selection_ids` to the reranked ids for the current intermediate view.
   * `sp.stage = "reranked"`; append history.
8. [14.04.2026] The current implemented ReRanker is still the cross-encoder path. ColBERT is the agreed immediate next step, but it is not yet the active code path.

ReRanker must therefore act as a bounded refinement stage, not as a blind overwrite of the Retrieval backbone.

### 5.5 A3_NLI_Gate

Purpose

* Filter and clean the reranked list using an LLM as a usefulness classifier over the reranked candidate set.
* Current implemented truth: A3 is usefulness-only. Duplicate marking has been intentionally removed from the A3 contract.

Nature

* Kind: Agent.
* Type: **Hybrid**: LLM usefulness classification over a candidate list plus deterministic post-processing.

Inputs

* `sp: SuperPrompt` with `stage="reranked"`.
* Candidate stage snapshots: `sp.views_by_stage["reranked"]`.
* A3 agent config JSON (via AgentFactory), including:

  * max candidates to consider,
  * allowed usefulness labels,
  * selection-band contract,
  * final-selection policy parameters.

Behaviour

1. Optional deterministic pre-filter:

   * cap candidates to the working set produced by ReRanker,
   * remove obviously empty or trivial chunks.
2. Build the prompt-under-evaluation block from the current user prompt in this semantic order:

   * `purpose`, if present,
   * `task`,
   * `context`, if present.

   Important current rule:

   * no `## Purpose` / `## Task` / `## Context` labels,
   * no A2 meta fields such as audience / tone / depth / confidence,
   * only the real prompt text is sent to A3.
3. Build the evidence block from the reranked candidates using local ids `1..N` mapped internally back to the real chunk ids.

   Important current rules:

   * the LLM-facing prompt must not expose the long real chunk ids,
   * evidence chunks use one outer XML-like wrapper style only,
   * chunk-internal line-start structure markers such as headings and code fences are sanitized so they do not fight with the outer prompt structure.
4. Call the LLM via `AgentFactory -> AgentPrompt -> llm_client` and parse the structured JSON response.
5. The current A3 output contract is conceptually:

   * one global `selection_band`, and
   * `item_decisions` with one `usefulness_label` per local chunk id.

   Current usefulness labels are:

   * `useful`
   * `borderline`
   * `discarded`

   No duplicate fields, canonical ids, or duplicate references belong to the current A3 contract.
6. Deterministic post-processing is mandatory after the LLM response:

   * `useful` chunks form the primary selected working set,
   * a hard max selection cap is enforced,
   * if too few useful chunks exist, the best `borderline` chunks are promoted in reranker order until the minimum working floor is reached.
7. Write:

   * `sp.views_by_stage["a3"] = [(chunk_id, a3_score, a3_status), ...]`,
   * `sp.final_selection_ids` from the useful-first policy plus borderline fallback.
8. Update stage:

   * `sp.stage = "a3"`; append history.

A3 must **never** mutate `Chunk` contents; it only changes usefulness labels, stage statuses, and which ids survive into the downstream selection.

### 5.6 A4_Condenser

Purpose

* Condense the selected context into a high-authority `S_CTX_MD` and enforce a context/output budget while preserving traceability back to the selected evidence.
* [24.04.2026] A4 output is internal retrieved context for downstream prompt assembly. It must not be written as a final answer to the user and must not be rendered as part of the user task.

Nature

* Kind: Agent.
* Type: LLM-only, Writer / Synthesizer.
* [24.04.2026] Current implementation: three LLM calls plus deterministic pre/post-processing.

Inputs

* `sp: SuperPrompt` with `stage="a3"`.
* Candidate evidence: A3-useful chunks from `sp.views_by_stage["a3"]`, mapped back to hydrated chunks in `sp.base_context_chunks`.
* Runtime limit: optional `effective_output_token_limit`, otherwise the A4 default output allowance.

Implemented A4 structure

1. [24.04.2026] A4 uses three exact JSON configurations under `data/agents/a4_condenser/`:

   * `chunk_phraser/a4_1_001.json`
   * `chunk_classifier/a4_2_001.json`
   * `final_condenser/a4_3_001.json`

2. [24.04.2026] `A4Condenser` loads these exact JSON paths directly and creates the three `AgentPrompt` objects at the beginning of the run.
3. [24.04.2026] Deterministic A4 preparation and write-back logic lives in `ragstream/agents/a4_det_processing.py`.
4. [24.04.2026] Shared A4 LLM-call mechanics live in `ragstream/agents/a4_llm_helper.py`.

Behaviour

1. Deterministic preparation:

   * Read A3 output.
   * Keep only chunks whose A3 usefulness label is `useful`.
   * Preserve the A3/reranked order.
   * Assign local A4 chunk ids `1..N` while preserving mappings from local ids back to real chunk ids.
   * Build the shared repeated evidence/query prefix for the A4 prompt family.

2. LLM call 1 — Chunk Phraser:

   * Read the selected chunks and the user prompt under evaluation.
   * Propose 1–4 active thematic class definitions with contiguous ids such as `ID1`, `ID2`, etc.

3. Deterministic active-class preparation:

   * Validate returned class definitions.
   * Keep only valid active classes.
   * Restrict the classifier's visible class options to the active class phrases for this A4 run.

4. LLM call 2 — Chunk Classifier:

   * Assign each selected local chunk to exactly one active class phrase.

5. Deterministic grouping and budget preparation:

   * Map classifier decisions back from class phrases to internal class ids.
   * Group chunks by active class.
   * Build the class-group package for the final condenser.
   * If classifier output is empty or unusable, continue in fallback mode by passing all selected chunks in their original order, together with the class overview.

6. LLM call 3 — Final Condenser:

   * Produce one neutral internal markdown context block as `s_ctx_md`.
   * Stay close to the evidence.
   * Do not address the user directly.
   * Do not add motivational framing, decorative introductions, or final-answer wording.

7. Final write-back:

   * `sp.S_CTX_MD = <condensed markdown>`.
   * `sp.final_selection_ids = [ordered retained real ids]`.
   * `sp.views_by_stage["a4"] = [(chunk_id, 1.0, SELECTED), ...]` for the final retained subset.
   * `sp.extras["a4_selected_local_to_real"]`, `sp.extras["a4_class_definitions"]`, and related A4 diagnostic fields may be populated for traceability.
   * `sp.stage = "a4"`; append history.

A4 is the stage where **S_CTX becomes the authoritative condensed context block** for the final LLM call, based on the A3-selected useful evidence. In the current Generation-1 GUI, raw chunks may still remain visible for inspection, but production prompt assembly should later be able to prefer `S_CTX_MD` as the normal context payload and treat raw evidence as debug/audit material.

### 5.7 A5_Format_Enforcer

Purpose

* Ensure that the final answer will follow the requested format (JSON, Markdown, checklist, code fence, etc.), and that instructions in `sp.body` are coherent and deterministic.

Nature

* Kind: Agent.
* Type: LLM-only, Writer/Extractor.

Inputs

* `sp: SuperPrompt` with `stage="a4"`.
* Fields from `sp.body`: `format`, `constraints`, `deterministic_rules`, `deterministic_codes`, any relevant extras from PreProcessing.

Behaviour

1. Build an AgentPrompt for A5:

   * Input payload:

     * the current `Prompt_MD` and `System_MD` concepts (from `sp.body`),
     * the target output format description,
     * any deterministic rules / codes.
   * Output: a small JSON or text block with:

     * `normalized_format_spec`,
     * `example_shape` (optional),
     * `hard_rules` (constraints restated in a model-friendly way).
2. A5 writes its results into:

   * `sp.extras["format_enforcer"] = {...}`;
   * may also rewrite `sp.body["format"]` into a cleaner description.
3. Update:

   * `sp.stage = "a5"`; append history.

A5 **does not** call retrieval again and does not change `final_selection_ids` or `S_CTX_MD`.

### 5.8 Prompt_Builder

Purpose

* Final deterministic assembly of the messages that will be sent to the final answering model.

Nature

* Kind: Function.
* Type: fully deterministic.

Inputs

* `sp: SuperPrompt` with `stage="a5"`.

Behaviour

1. Render `System_MD` from `sp.body["system"]`, `tone`, `depth`, and any A5 rules.
2. Render `Prompt_MD` from `task`, `purpose`, `context`, `audience`, `format`.
3. Render `S_CTX_MD` (already produced by A4) and **do not edit it**, except for minor non-semantic formatting if needed.
4. Render `Attachments_MD` as raw excerpts from `sp.final_selection_ids`:

   * formatted with provenance fences (`SOURCE: ...`, `SPAN: ...`).
5. Optionally merge `recentConversation` as a distinct block (not mixed into S_CTX).
6. Compose `sp.prompt_ready` as the final concatenation of these blocks in the agreed order:

   1. `System_MD`
   2. `Prompt_MD`
   3. `S_CTX_MD`
   4. `Attachments_MD`
   5. (optional) `Recent Conversation` block
7. Current implementation note: `SuperPrompt.compose_prompt_ready()` may also be used earlier for intermediate GUI previews. Prompt_Builder remains the authoritative final assembly step for send-time use.
8. [24.04.2026] Prompt_Builder must align with the current `SuperPromptProjector` separation of System, Configuration, User, Retrieved Context Summary, and Raw Retrieved Evidence. It must treat `S_CTX_MD` as supporting retrieved context, not as user task text.
9. `sp.stage` stays `"a5"`; Prompt_Builder **does not** change the lifecycle stage, it only prepares the final view/send-time representation.

---

## 6. Controller integration

1. Manual mode (GUI):

   * Each button calls the controller, which:

     * passes the current `SuperPrompt` to the corresponding stage function/agent,
     * receives the mutated `SuperPrompt`,
     * updates the GUI `Super-Prompt` box (`sp.prompt_ready`) after stages that change it (A0, A2, Retrieval, and later stages that render a preview).
2. Auto mode:

   * Controller runs all stages in sequence:

     * `A0 → A2 → Retrieval → ReRanker → A3 → A4 → A5 → Prompt_Builder`,
     * then sends `System_MD + Prompt_MD + S_CTX_MD + Attachments_MD` to the final answering LLM.
3. At every step, controller must check:

   * `sp.stage` sequence is strictly increasing in the allowed order,
   * `views_by_stage` and `final_selection_ids` are consistent with the stage definitions,
   * error conditions (e.g. missing retrieval results) are surfaced to the GUI.

---

## 7. Acceptance criteria (high-level)

The RAG pipeline is considered correctly implemented when:

1. For a fixed prompt + fixed configs, running the full chain twice produces **byte-identical** `sp.body`, `views_by_stage`, `final_selection_ids`, and `S_CTX_MD` (LLM stages at temperature 0 or with fixed seeds).
2. `base_context_chunks` never contains duplicates by `id`, and no stage mutates its `Chunk` contents.
3. The number of candidates at each stage respects the N-constants:

   * `len(views_by_stage["retrieval"]) ≤ N1_RETR_MAX_CANDIDATES`,
   * candidates passed to ReRanker ≤ `N2_RERANK_TOP_K`,
   * `len(final_selection_ids) ≤ N3_FINAL_SELECTION_MAX`.
4. Turning LLM fallbacks off (A0 semantic mapping, A3, A4, A5) either:

   * degrades gracefully to deterministic defaults, or
   * blocks the pipeline with clear error messages; it never produces silent, half-configured output.
5. The final `prompt_ready` always contains:

   * a stable System block,
   * a normalized Prompt block,
   * a condensed S_CTX block,
   * clearly fenced attachments for manual inspection.
6. [24.04.2026] The GUI-visible `prompt_ready` must clearly separate `## System`, `## Configuration`, `## User`, and `## Retrieved Context`. The real user task must appear only under `## User / ### Task`, while A4 condensed context must appear under `## Retrieved Context / ### Retrieved Context Summary`.
7. [14.04.2026] For the current Retrieval design, every chunk that survives into the Retrieval-stage final display is expected to carry both dense and SPLADE score metadata, because SPLADE scores the same dense-selected candidate IDs rather than an unrelated independent top-k set.