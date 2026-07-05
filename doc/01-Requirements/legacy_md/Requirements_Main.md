# Requirements_Main.md

## 1. Purpose and document map

This document gives the top-level requirements for RAGstream as a whole.
It explains how the major subsystems work together, which files define their details, and how a single user prompt flows through the system from GUI to final SuperPrompt (and optionally to an external LLM).

RAGstream is an agentic software engineering system designed to:

* Turn free-form user prompts into a structured `SuperPrompt`.
* Retrieve, rerank, and compress relevant knowledge from persistent vector stores.
* Combine deterministic pipeline stages with JSON-defined LLM stages through a neutral Agent Stack.
* Add memory, tag-governed history handling, and explicit context selection to the same pipeline.
* Remain compatible with AWS deployment, DevOps delivery, and future local or remote model backends.

This main requirement file is the “spine” for the following subsystem specifications:

* Requirements_RAG_Pipeline.md
  – Defines the 8-step pipeline (A0, A2, Retrieval, ReRanker, A3, A4, A5, Prompt Builder), how each step mutates the SuperPrompt, and the deterministic vs LLM nature of each stage.

* Requirements_AgentStack.md
  – Defines the neutral, stateless agent stack (AgentFactory, AgentPrompt, llm_client), agent JSON configs, and the four agent types (Chooser, Writer, Extractor, Multi-Chooser).

* Requirements_Ingestion_Memory.md
  – Defines document ingestion (already implemented) and conversation history ingestion (future), including directory layout (`doc_raw`, `chroma_db`, `history`) and vector-store invariants.

* Requirements_Orchestration_Controller.md
  – Defines controller.py (AppController), which owns the current SuperPrompt, enforces stage order, and calls the pipeline stages.

* Requirements_GUI.md
  – Defines the intermediate GUI (button-driven pipeline tester), outlines the main GUI with history and LLM calls, and sketches an advanced future GUI.

* Backlog_Future_Features.md
  – Collects non-binding, forward-looking ideas (tags, cross-session history import, TOON adapter, advanced attention controls, etc.).

All detailed constraints live in those subsystem documents; Requirements_Main.md only summarizes and connects them.

## 2. High-level system overview

At the highest level, RAGstream consists of:

* A GUI (initially Streamlit) where the user:

  * Selects a document project / DB.
  * Enters a free-form prompt.
  * Manually triggers stages of the pipeline via buttons (intermediate phase).
* A Controller (AppController) which:

  * Owns a single SuperPrompt instance per session.
  * Receives button events and runs the corresponding pipeline stage.
  * Updates the SuperPrompt and pushes a text snapshot back to the GUI.
* A RAG pipeline with 8 stages:

  * A0_PreProcessing (deterministic, optional LLM help later).
  * A2 PromptShaper (LLM-based Chooser agent).
  * Retrieval (deterministic hybrid first-pass retrieval stage).
  * ReRanker (deterministic bounded reranking stage).
  * A3 NLI Gate (LLM-based usefulness classifier over reranked chunks).
  * A4 Condenser (LLM-based summarization / context compressor).
  * A5 Format Enforcer (LLM-based format / style agent).
  * Prompt Builder (deterministic prompt composer).
* The Agent Stack:

  * AgentFactory – reads agent JSON config and creates a concrete AgentPrompt.
  * AgentPrompt – neutral composer that turns enums + input payload into a text prompt.
  * llm_client – abstracts away OpenAI vs future local/remote models.
* Ingestion & Memory:

  * Document ingestion: loader → chunker → embedder → Chroma vector store.
  * History (future): append-only logs + a separate history vector store with tags and session metadata.

Conceptually:

GUI → Controller → [PreProcessing, A2, Retrieval, ReRanker, A3, A4, A5, Prompt Builder via AgentStack & VectorStores] → SuperPrompt → (optional) external LLM.

## 3. Core data model (shared assumptions)

RAGstream’s subsystems share a small set of core concepts. The detailed schema for each lives in the relevant requirement or Python module; here we only fix the roles.

### 3.1 SuperPrompt

SuperPrompt is the central, structured representation of “what we are doing right now”. It is the only long-lived in-memory object in the pipeline.

At minimum, SuperPrompt must represent:

* User’s ask, normalized into canonical fields such as:

  * system (role of the model),
  * audience,
  * task / purpose / context,
  * tone,
  * depth,
  * confidence (desired or inferred).
* RAG context:

  * `base_context_chunks`: the current authoritative working set of selected `Chunk` objects.
  * `views_by_stage`: ordered stage snapshots for retrieval/reranking/filtering views.
  * `final_selection_ids`: the currently active selected chunk IDs for downstream stages and rendering.
  * A condensed context block (S_CTX) produced by A4 (facts / constraints / open issues).
  * Optional attachments (raw excerpts that the final LLM may see).
* Stage and history:

  * Current stage name (raw, preprocessed, a2, retrieval, reranked, a3, a4, a5). Prompt Builder does not introduce a new lifecycle stage; it keeps the stage at `a5`.
  * A history of stages that have been run in order.
* GUI snapshot:

  * A single text representation (`prompt_ready`) that the GUI shows as the current SuperPrompt preview.
  * During the current implementation phase this preview may already be refreshed by earlier stages; the final authoritative assembly still belongs to Prompt Builder.
* Extra diagnostics and meta:

  * Per-agent decisions, confidence scores, error messages, and other internal notes.

SuperPrompt is owned by the Controller. All stages read and write it; no other object is allowed to keep a parallel source of truth.

### 3.2 Vector stores and chunks

Documents and history are never passed as raw text lists between pipeline stages. Instead:

* Ingestion pipelines (document or history) convert raw text into:

  * Chunk objects with stable IDs and metadata.
  * Embeddings stored in Chroma collections under `data/chroma_db/<project>` or `data/history/vectors/`.
* Retrieval and reranking work with:

  * Chunk IDs and metadata (path, session_id, tags, etc.).
  * Embedding vectors hidden behind the vector-store abstraction.

SuperPrompt currently holds:

* The hydrated `Chunk` objects for the active working set (`base_context_chunks`).
* Ordered per-stage views for Retrieval / ReRanker / later filtering stages (`views_by_stage`).
* The currently active selected IDs (`final_selection_ids`).
* A small number of rendered text blocks (such as S_CTX, attachments, and GUI preview text) needed for LLM input or GUI display.

### 3.3 Agent configuration data

Each agent (A0, A2, A3, A4, A5, and future agents) is described by JSON config files (and optionally YAML profiles later if needed). They define, for that agent:

* Agent name and version.
* Agent type: Chooser, Writer, Extractor, or Multi-Chooser.
* Enums:

  * Fields where the agent must choose from a finite list (e.g. tone, confidence, system roles).
* Input payload fields:

  * Which parts of SuperPrompt (or PreProcessing outputs) are exposed to the agent as input text.
* Constant strings:

  * Agent-level system and purpose texts (“what is your job overall?”).
* LLM configuration:

  * Default model, temperature, max tokens, etc.

AgentFactory reads this config, checks that A2 (or another agent) passes the expected enums and payload shapes, and then creates a concrete AgentPrompt ready to compose a prompt for llm_client.

## 4. End-to-end lifecycle of a single run

This section describes, at a high level, what happens from the moment the user types a prompt in the GUI until the final SuperPrompt is ready.

### 4.1 Manual mode (intermediate GUI)

In intermediate mode, the GUI exposes eight buttons, one per stage. The typical flow is:

1. User enters an initial prompt in the GUI input box.

2. A0_PreProcessing (button “PreProcessing”):

   * Controller calls a deterministic PreProcessing module.
   * The module:

     * Parses the raw text (or JSON/YAML/HTML etc.) into a canonical markdown structure.
     * Validates and normalizes field names (task, purpose, context, audience, etc.).
     * Records unknown attributes and normalization decisions in SuperPrompt extras.
   * SuperPrompt.stage becomes “preprocessed”; prompt_ready shows the normalized view.

3. A2 PromptShaper (button “A2 PromptShaper”):

   * Controller calls the A2 agent with the current SuperPrompt.
   * A2 is a Chooser-type agent:

     * It receives task/purpose/context and enum lists for system, audience, tone, depth, confidence.
     * Through AgentFactory → AgentPrompt → llm_client → OpenAI, it chooses 1–3 system roles and single values for the other fields.
   * SuperPrompt’s header fields (system, audience, tone, etc.) are updated.
   * A2 can be re-run later if needed.

4. Retrieval (button “Retrieval”):

   * Controller builds a retrieval query from SuperPrompt `task + purpose + context` and calls the Retrieval module.
   * Retrieval splits that query into overlapping pieces, runs dense retrieval and SPLADE sparse retrieval on the active project's Chroma document store, fuses the rankings with RRF, and keeps the bounded candidate set.
   * Retrieval reconstructs the real chunk text from `data/doc_raw/<project>` using stored metadata and the same chunking logic as ingestion.
   * SuperPrompt records the hydrated selected chunks in `base_context_chunks`, writes the Retrieval stage snapshot into `views_by_stage["retrieval"]`, and updates `final_selection_ids`.

5. ReRanker (button “ReRanker”):

   * Controller calls ReRanker on those Retrieval candidates.
   * ReRanker is a deterministic bounded reranking stage. The current implemented code path is cross-encoder based; the agreed immediate next direction is ColBERT.
   * SuperPrompt records the reranked stage snapshot in `views_by_stage["reranked"]` and updates the current selection accordingly.

6. A3 NLI Gate (button “A3 NLI Gate”):

   * Controller calls A3, another agent driven via AgentFactory/AgentPrompt/llm_client.
   * A3 inspects the reranked candidate set, assigns usefulness labels such as `useful`, `borderline`, or `discarded`, and produces a structured working set for downstream stages.
   * SuperPrompt’s selection is filtered through useful-first selection with deterministic borderline fallback when needed.

7. A4 Condenser (button “A4 Condenser”):

   * Controller calls A4 on the final selection.
   * A4 condenses selected chunks into S_CTX (facts, constraints, open issues), plus optionally drops low-value chunks for token budget reasons.
   * SuperPrompt stores this S_CTX as the main context the final LLM should think from.

8. A5 Format Enforcer (button “A5 Format Enforcer”):

   * Controller calls A5 on the partially prepared SuperPrompt.
   * A5 ensures that the final prompt’s instructions and expectations match the desired structure (e.g. explicit JSON schema, code block scaffolding, or narrative format).
   * SuperPrompt header and other fields may be adjusted slightly.

9. Prompt Builder (button “Prompt Builder”):

   * Controller calls Prompt Builder to generate the exact final prompt package from SuperPrompt:

     * System block (System_MD).
     * Main task/purpose/context block (Prompt_MD).
     * Condensed context block (S_CTX).
     * Optional attachments with raw excerpts.
   * `SuperPrompt.prompt_ready` becomes the final authoritative text snapshot of what would be sent to an LLM. Earlier stages may already refresh a GUI preview, but Prompt Builder remains the final assembly owner.

At any stage, the user may:

* Inspect SuperPrompt in the GUI,
* Re-run A2 or higher agents,
* Return to PreProcessing and start again.

Manual mode is the primary debugging and learning environment and must remain stable and predictable.

### 4.2 Auto mode (future)

Later, the controller will provide a single method such as:

* run_full_pipeline(user_text, options) → SuperPrompt

which internally executes the same steps (A0 → A2 → Retrieval → ReRanker → A3 → A4 → A5 → PromptBuilder) with the same semantics as pressing the buttons in order.

Auto mode must:

* Respect the same stage gating and SuperPrompt mutations.
* Allow configuration of which stages are human-in-the-loop (for example, pause after A4).
* Never bypass the agent stack or retrieval modules.

## 5. Subsystem summaries and cross-references

### 5.1 Ingestion & Memory

* Documents:

  * Raw text lives under `data/doc_raw/<project>/`.
  * IngestionManager scans, chunks, embeds, and writes embeddings to `data/chroma_db/<project>/` with a file manifest for incremental updates.
  * Retrieval reads from these stores; ingestion never calls LLMs.

* History (future):

  * Raw conversation logs (Q/A pairs, tags, metadata) live in `data/history/logs/` as append-only records.
  * A separate history vector store in `data/history/vectors/` holds embeddings of selected turns.
  * Retrieval can query history with metadata filters (session_id, tags like GOLD/SILVER, projects, recency).

Details: Requirements_Ingestion_Memory.md.

### 5.2 RAG Pipeline & SuperPrompt

* Defines the eight pipeline stages and their nature:

  * Deterministic only: A0_PreProcessing (plus possible light LLM helper), Retrieval, ReRanker, Prompt Builder.
  * Hybrid / LLM-based agents: A2, A3, A4, A5 (each built via the Agent Stack).

* Defines how each stage:

  * Reads the current SuperPrompt,
  * Modifies specific fields (headers, selection IDs, S_CTX),
  * Updates stage + history,
  * Regenerates prompt_ready.

* Uses fixed index constants (e.g. N1 for retrieval, N2 for reranking) to ensure consistent behavior and easy experimentation.

Details: Requirements_RAG_Pipeline.md.

### 5.3 Agent Stack

* AgentFactory:

  * Reads JSON configs for a given agent name + version.
  * Validates that the agent’s enums and input payload are correctly provided by the caller (A2, A3, etc.).
  * Creates and returns an AgentPrompt instance with all static information filled in (system text, purpose text, enums, model choice).

* AgentPrompt:

  * Neutral, stateless prompt composer.
  * Exposes methods to:

    * Accept runtime input payload (e.g. task/purpose/context).
    * Assemble the final text prompt from:

      * Agent system/purpose,
      * Enums (possible choices for each field),
      * Input payload,
      * A simple, generic “TASK text” that explains what LLM must do.
  * Does not know which agent it belongs to; it only sees data and generic instructions.

* llm_client:

  * Receives a fully composed prompt, model name (standard or fine-tuned), and config.
  * Calls OpenAI chat APIs today.
  * Is designed so that future backends (local SLMs, AWS endpoints, SageMaker, etc.) can be plugged in by extending or swapping the client, without changing agents or controller.

Details: Requirements_AgentStack.md.

### 5.4 Orchestration & Controller

* AppController:

  * Lives in app/controller.py.
  * Owns the SuperPrompt for the current session.
  * Manages global context (active project, active vector store, default models).
  * Provides one method per stage (preprocess, run_a2, run_retrieval, run_reranker, run_a3, run_a4, run_a5, build_prompt).
  * Optionally provides a run_full_pipeline method later.

* Responsibilities:

  * Enforce legal stage order (e.g. no Retrieval before PreProcessing).
  * Allow safe re-runs of A2 or later stages without corrupting the SuperPrompt.
  * Keep stage and history fields consistent.
  * Handle basic error reporting and avoid partial updates when a stage fails.

Details: Requirements_Orchestration_Controller.md.

### 5.5 GUI & user interaction

* Intermediate GUI:

  * Simple Streamlit UI.
  * Input text box for raw prompt.
  * SuperPrompt text area for current state.
  * Eight buttons (A0, A2, Retrieval, ReRanker, A3, A4, A5, Prompt Builder).
  * Buttons call the controller methods and then refresh the SuperPrompt display.

* Main GUI (future near term):

  * Adds:

    * Project and DB selection (including ingestion trigger).
    * History view and tag editing (GOLD/SILVER/etc.) once history ingestion is implemented.
    * Optional direct LLM call: send final SuperPrompt to an external API and show the answer.
    * A field to paste external LLM responses (e.g. from ChatGPT UI) so they are stored in history.

* Advanced GUI (longer term vision):

  * Multi-history controls, advanced attention visualization, AI-agency orchestration UI, V-diagram-style software development aids, etc.
  * Only described as ideas; not binding yet.

Details: Requirements_GUI.md.

### 5.6 Backlog & future features

Backlog_Future_Features.md collects ideas that are **intentionally out of scope** for the current implementation but important for the long-term vision, such as:

* Tagging history entries (GOLD/SILVER/BLUE) and using those tags in retrieval.
* Combining history from multiple sessions with filters (by tag, project, time).
* TOON adapter: optional conversion from JSON to TOON format for final LLM prompts if it proves superior.
* Multiple projects and attention profiles, advanced memory control, AI-agency around the pipeline, etc.

Requirements_Main.md and the other requirement files must remain stable even if backlog items evolve; adding a backlog item never changes current core behavior.

## 6. Development phases and stability

### 6.1 Intermediate phase (current)

The immediate goal is to get a full end-to-end pipeline working with:

* Document ingestion & retrieval.
* SuperPrompt and all eight stages (A0, A2, Retrieval, ReRanker, A3, A4, A5, Prompt Builder).
* Intermediate GUI with manual buttons.
* Agent stack (AgentFactory, AgentPrompt, llm_client) used by all LLM-based agents.

In this phase:

* No conversation history ingestion is required yet.
* No direct LLM call from the GUI is strictly required; final SuperPrompt can be copy-pasted into ChatGPT UI if desired.
* Controller and requirements documents are considered stable enough to implement code.

### 6.2 Main GUI phase

In the next phase, the focus shifts to:

* Implementing a more complete GUI:

  * Project selection and ingestion control.
  * Basic history view and editing.
  * LLM call with cost estimation.
  * Field to paste external LLM results.

* Implementing conversation history ingestion:

  * Raw logs and basic embeddings.
  * Minimal tag support (at least GOLD / non-GOLD).
  * Simple retrieval of recent or GOLD history entries.

The fundamental pipeline and AgentStack interfaces should not change. New features sit on top of existing structures.

### 6.3 Advanced / experimental phase

Finally, advanced features can be developed iteratively:

* Rich tag semantics and decay weighting for history.
* Multi-session knowledge import, project-aware history mixing.
* AI-agency around the existing pipeline (planners, self-critique loops).
* Integration with local SLMs or AWS-hosted models through llm_client.

All such work must keep backward compatibility with the data model and basic flow defined here, or go through deliberate versioning.

## 7. Global design principles

Across all subsystems, RAGstream follows these principles:

1. Single source of truth:

   * SuperPrompt is the authoritative in-memory state for the current run.
   * Document and history vector stores are authoritative persistent state for embeddings.

2. Stateless agents:

   * A0, A2, A3, A4, A5 agents never hold long-term state.
   * They read a SuperPrompt (or its subset), call AgentStack → llm_client once (or a small fixed number of times), and return a deterministic update.

3. Deterministic retrieval:

   * Retrieval remains deterministic at ranking level. ReRanker remains deterministic at ranking level, while allowing a helper agent for bounded query splitting in the agreed future design.
   * The rules for which chunks are eligible and how they are scored are defined in RAG_Pipeline and are reproducible.

4. JSON as internal standard:

   * Agent configs, enumerations, and most stateful configs live as JSON on disk.
   * Alternative formats (TOON, YAML) may be added at the edges (LLM calls, configuration convenience) without replacing JSON.

5. Append-only logging:

   * Conversation history is logged append-only; edits or deletions are explicit actions, not silent behaviors.

6. No silent deletions:

   * Documents are removed only when files are removed or changed in doc_raw.
   * History entries and vectors are only removed/ignored under clear user control or explicit retention policies.

7. Clear separation of concerns:

   * GUI only handles interaction and display.
   * Controller only orchestrates stages and manages SuperPrompt.
   * Agents only call LLMs via the AgentStack.
   * Ingestion only deals with files/logs → chunks → embeddings.

8. Future-proofing without over-engineering:

   * The design explicitly leaves hooks for future ML-Ops, AWS, local SLMs, and AI-agency.
   * Current implementation stays as simple as possible while keeping those paths open.

## 8. Non-goals and out-of-scope items

For the current version of RAGstream, the following are **not** goals:

* Building a full multi-agent planner that dynamically rewires the pipeline.
* Full-blown LangChain/LangGraph replacement; instead, RAGstream borrows good ideas but keeps a custom, tight architecture.
* Complex policy engines for access control, user management, or multi-tenant cloud deployment.
* Automatic self-tuning of pipeline parameters (N1/N2, thresholds) via reinforcement learning.

Such features can be revisited later and, if desired, added to Backlog_Future_Features.md.

---

With Requirements_Main.md in place, the combination of:

* Requirements_RAG_Pipeline.md
* Requirements_AgentStack.md
* Requirements_Ingestion_Memory.md
* Requirements_Orchestration_Controller.md
* Requirements_GUI.md
* Backlog_Future_Features.md

forms a coherent, modular specification for RAGstream that is sufficient to guide implementation, testing, and future evolution.
