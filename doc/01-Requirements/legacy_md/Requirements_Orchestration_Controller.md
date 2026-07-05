# Requirements_Orchestration_Controller.md

Last update: 24.04.2026

1. Purpose and scope

This document specifies the orchestration and controller layer for RAGstream. It describes how the controller coordinates the eight-stage RAG pipeline, integrates with the GUI, and remains compatible with the current stateless agent design (AgentFactory, AgentPrompt, llm_client) and the SuperPrompt data model.

The focus here is:

* What controller.py is responsible for.
* How it calls agents and deterministic stages.
* How it manages SuperPrompt and session state.
* How it prepares for future auto-mode and richer orchestration without breaking today’s design.

Details of individual pipeline stages (A0_PreProcessing, A2, A3, A4, A5) are defined in Requirements_RAG_Pipeline.md. The neutral stateless agent infrastructure (AgentFactory, AgentPrompt, llm_client) is defined in Requirements_AgentStack.md. Retrieval and ReRanker mechanics are defined in Requirements_RAG_Pipeline.md, while storage and ingestion dependencies are defined in Requirements_Ingestion_Memory.md.

2. Position in the architecture

File: ragstream/app/controller.py

The controller sits between:

* The GUI (ui_streamlit.py) and
* The “brain” components:

  * PreProcessing (A0_PreProcessing)
  * A2 PromptShaper
  * Retrieval and ReRanker
  * future helper agent for ReRanker query splitting
  * A3 NLI Gate
  * A4 Condenser
  * A5 Format Enforcer
  * Prompt Builder

It does not implement LLM logic or vector math itself. Instead, it:

* Owns one SuperPrompt instance per session.
* Knows how to call each stage in the correct order.
* Updates SuperPrompt.stage, history_of_stages, prompt_ready, and the GUI snapshot.
* Manages global choices like active project / active vector store.

All heavy work (PreProcessing normalization, agents, retrieval, reranking, A3 filtering, and A4 condensation) lives in their own modules.

3. Controller responsibilities (high-level)

3.1 Core responsibilities

The controller must:

* Maintain one SuperPrompt for the current session.
* Provide simple methods for each pipeline stage, called from GUI buttons and from future auto-mode.
* Enforce legal stage order (no retrieval before pre-processing, etc.), but allow A2 to be re-run when needed.
* Pass only clean, well-typed arguments to each stage (agents see SuperPrompt plus any stage-specific config, not raw GUI state).
* Capture stage outputs into SuperPrompt and update prompt_ready for the GUI.
* Handle basic errors in a predictable way (do not corrupt SuperPrompt on failure).
* Expose a single “run full pipeline” function that calls stages 1–8 in sequence, equivalent to clicking all buttons in order.

3.2 Non-responsibilities

The controller must not:

* Implement AgentFactory or AgentPrompt logic.
* Implement llm_client logic or talk directly to OpenAI or any other LLM provider.
* Implement ingestion, chunking, or vector math; it only calls retrieval/reranking interfaces.
* Persist history or tags on disk (that is part of ingestion/memory; the controller may trigger it, but not implement it).

4. Main class and state model

4.1 AppController class

File: ragstream/app/controller.py

AppController is a small, stateful object that lives in Streamlit’s session_state.

Mandatory fields:

* sp: SuperPrompt

  * The single source of truth for the current session state, as defined in the SuperPrompt requirements.
* active_project: string or None

  * Logical project key, used to select Chroma DB and doc roots.
* active_store_path: string or None

  * Full path to the current Chroma DB root (e.g., myroot/data/chroma_db/Project1).
* config: dictionary

  * High-level configuration (paths to config files, default models, flags like “use_history”).

Optional fields (depending on current implementation stage):

* history_profile: string or None (which history mode to use later).
* last_error: string or None (for GUI display).

4.2 Lifecycle

At GUI start:

* ui_streamlit.py checks st.session_state; if no controller exists, it creates AppController().
* AppController.**init** creates the shared controller infrastructure. [24.04.2026] In the current implementation this includes a shared `AgentFactory`, shared `LLMClient`, `A2PromptShaper`, `A3NLIGate`, and `A4Condenser`; Streamlit session state owns the active `SuperPrompt` objects used by the GUI.

On each button click:

* The GUI calls a controller method (for example preprocess or run_a2), passing:

  * Raw user text (for A0) or nothing (for later stages).
  * The current SuperPrompt (if needed), or lets the controller own and mutate it directly.
* The controller:

  * Validates that the requested stage is allowed given sp.stage.
  * Delegates to the appropriate module (agent or deterministic function).
  * Updates SuperPrompt, including:

    * stage
    * history_of_stages
    * prompt_ready (for the GUI)
    * views_by_stage and final_selection_ids for retrieval-related stages
  * Returns the updated SuperPrompt to the GUI (or the GUI reads controller.sp).

5. Stage methods in the controller

The controller exposes one method per pipeline step, plus a composite method for auto-mode.

5.1 PreProcessing (A0_PreProcessing)

Signature (conceptual):

* preprocess(user_text: str) -> SuperPrompt

Behavior:

* Create or reset sp if stage is “raw” or if a reset is requested.
* Call PreProcessing module (deterministic code) with:

  * user_text
  * current prompt_schema config (JSON)
  * possibly previous decisions from sp.extras
* Receive updated SuperPrompt with:

  * body normalized (canonical keys)
  * extras updated (normalized_map, unknown_attributes, etc.)
  * stage set to "preprocessed"
  * history_of_stages appended with "preprocessed"
  * prompt_ready regenerated as per Req_PreProcessing. 
* Store updated sp on the controller and return it.

Stage gating:

* Allowed only if current stage is "raw" or if explicit “restart” flag is set.
* If strict mode is active and unknown attributes are unresolved, block subsequent stages until the user decides in the GUI.

5.2 A2 PromptShaper

Signature (conceptual):

* run_a2() -> SuperPrompt

Behavior:

* Require stage >= "preprocessed".
* Call A2 agent module (for example ragstream/app/agents/a2_prompt_shaper.py) with the current SuperPrompt.
* A2 uses the shared AgentFactory, AgentPrompt, and llm_client to query the configured model and returns structured headers (system, audience, tone, confidence, depth) plus any meta info, following its own requirements. [24.04.2026] A2 also applies deterministic selector sanitization before updating `SuperPrompt`. 
* The controller receives an updated SuperPrompt from A2 with:

  * body fields updated or filled only where sanitized A2 output remains valid (system, tone, depth, audience, confidence).
  * extras updated with sanitized selected ids and A2 diagnostics.
  * stage set to "a2".
  * history_of_stages appended with "a2".
  * prompt_ready regenerated for the GUI (from the updated body).

Stage gating:

* A2 can be run multiple times after "preprocessed" or later stages.
* Controller must allow re-running A2 to refine headers, without resetting retrieval results; later calls simply move stage back to "a2" and push "a2" into history_of_stages again.

5.3 Retrieval

Signature (conceptual):

* run_retrieval() -> SuperPrompt

Behavior:

* Require stage >= "preprocessed" (A2 recommended but not mandatory).
* Build a query representation from SuperPrompt (for example Prompt_MD or a combination of task, context, purpose) as defined in Requirements_RAG_Pipeline.md. 
* Call retrieval module (for example ragstream/retrieval/retriever.py) with:

  * active_project / active_store_path
  * SuperPrompt (for query pieces)
  * any retrieval config (max_candidates, scoring parameters).
* Retrieval returns:

  * base_context_chunks: list of hydrated `Chunk` objects.
  * retrieval_view: ordered stage snapshots for stage `"retrieval"`, in fused Retrieval order.
  * final_selection_ids initialized to the same Retrieval order for the current intermediate GUI view.
  * optional component-score metadata for dense Retrieval, SPLADE, and fused Retrieval display.
* Controller updates sp:

  * base_context_chunks set from Retrieval output.
  * views_by_stage["retrieval"] = retrieval_view.
  * final_selection_ids initialized to the Retrieval ids (before ReRanker / A3 / A4 adjust them).
  * stage set to "retrieval".
  * history_of_stages appended with "retrieval".
  * prompt_ready may be regenerated via `sp.compose_prompt_ready()` so the GUI shows a simple Related Context preview.

5.4 ReRanker

Signature (conceptual):

* run_reranker() -> SuperPrompt

Behavior:

* Require stage >= "retrieval".
* Call reranker module with:

  * the current Retrieval-ranked candidate band,
  * the current prompt fields from SuperPrompt,
  * and, if needed, the future `NLP_Splitter` helper agent for meaning-based query splitting under the active token limit.
* Reranker returns:

  * `reranked_view`: ordered stage snapshots in the new fused order.
  * optional component-score metadata for the previous Retrieval ranking, ColBERT ranking, and final fused reranking.
* Controller updates sp:

  * `views_by_stage["reranked"] = reranked_view`.
  * `final_selection_ids` updated to the reranked ids (subject to later filtering by A3 and token budgeting by A4).
  * stage set to "reranked".
  * history_of_stages appended with "reranked".
  * `prompt_ready` may be regenerated for the GUI snapshot.

5.5 A3 NLI Gate

Signature (conceptual):

* run_a3() -> SuperPrompt

Behavior:

* Require stage >= "retrieval" (recommended: >= "reranked").
* Call A3 agent module with:

  * SuperPrompt (including chunks for current selection).
* A3 uses its own AgentFactory and llm_client to inspect candidate chunks and assign one structured decision per chunk.
* A3 returns:

  * updated final_selection_ids (only chunks that pass the gate or remain eligible under the active policy).
  * optionally a view list `views_by_stage["a3"]`.
  * usefulness labels and selection-band metadata per chunk. Duplicate metadata is not part of the current A3 contract.
* Controller updates sp:

  * final_selection_ids set to A3’s decision.
  * views_by_stage["a3"] updated if provided.
  * stage set to "a3".
  * history_of_stages appended with "a3".
  * prompt_ready optionally extended with A3 diagnostics (optional).

5.6 A4 Condenser

Signature (conceptual):

* run_a4(sp: SuperPrompt, *, effective_output_token_limit: int | None = None) -> SuperPrompt

Behavior:

* Require stage >= "a3" with A3 rows available and useful chunks present.
* [24.04.2026] Call the live `A4Condenser` module with:

  * SuperPrompt,
  * optional `effective_output_token_limit`.
* [24.04.2026] A4 does not use normal `AgentFactory.get_agent(...)` lookup. `A4Condenser` loads the three exact A4 JSON configs, creates the three `AgentPrompt` objects at the beginning of the run, and delegates:

  * deterministic preparation / grouping / finalization to `a4_det_processing.py`,
  * repeated LLM-call mechanics to `A4LLMHelper`,
  * OpenAI Responses API calls to `LLMClient.responses(...)`.
* [24.04.2026] A4 produces:

  * `S_CTX_MD`: neutral condensed retrieved context from A3-useful evidence,
  * updated `final_selection_ids`,
  * `views_by_stage["a4"]`,
  * A4 diagnostic fields in `sp.extras`.
* Controller updates sp:

  * S_CTX_MD set.
  * final_selection_ids adjusted to the A4 retained ids.
  * views_by_stage["a4"] set to the final list.
  * stage set to "a4".
  * history_of_stages appended with "a4".
  * prompt_ready updated via `sp.compose_prompt_ready()` / `SuperPromptProjector` so `S_CTX_MD` appears under Retrieved Context Summary, not under the user task.

5.7 A5 Format Enforcer

Signature (conceptual):

* run_a5() -> SuperPrompt

Behavior:

* Require stage >= "a4".
* Call A5 agent module with:

  * SuperPrompt (body + S_CTX_MD + possibly recentConversation).
* A5 uses AgentFactory and llm_client to produce:

  * A cleaned or fully structured Prompt_MD and/or body fields that match the desired output format (for example JSON spec or code-structure instructions).
* Controller updates sp:

  * body and extras with any final formatting decisions.
  * stage set to "a5".
  * history_of_stages appended with "a5".
  * prompt_ready regenerated as “almost final” SuperPrompt snapshot for the GUI.

5.8 Prompt Builder

Signature (conceptual):

* build_prompt() -> SuperPrompt

Behavior:

* Require stage >= "a4" (strongly recommended: >= "a5").
* Call Prompt Builder module (for example ragstream/orchestration/prompt_builder.py) to render the final LLM message blocks from SuperPrompt:

  * System_MD (system block)
  * Prompt_MD (task/purpose/context)
  * S_CTX_MD (already set by A4)
  * Attachments_MD (raw chunk excerpts from final_selection_ids) 
* Controller updates sp:

  * System_MD, Prompt_MD, Attachments_MD filled.
  * stage set to "built" or reuses "a5" if no extra stage name is desired; history_of_stages updated.
  * prompt_ready updated to show the final composed prompt exactly as it will be sent to LLM.

Prompt Builder itself remains deterministic; it just renders strings from SuperPrompt.

6. Manual vs automatic orchestration

6.1 Manual mode (intermediate GUI)

* Eight buttons call controller methods:

  * PreProcessing → preprocess()
  * A2 PromptShaper → run_a2()
  * Retrieval → run_retrieval()
  * ReRanker → run_reranker()
  * A3 NLI Gate → run_a3()
  * A4 Condenser → run_a4()
  * A5 Format Enforcer → run_a5()
  * Prompt Builder → build_prompt()
* After each call, the GUI updates the SuperPrompt text area from sp.prompt_ready. [24.04.2026] After A4, this visible prompt is rendered with explicit separation between System, Configuration, User, Retrieved Context Summary, and Raw Retrieved Evidence. 
* Stage gating is enforced by the controller; buttons may be visually enabled/disabled in the GUI later, but logic must not rely on UI alone.

6.2 Auto mode (future)

AppController exposes:

* run_full_pipeline(user_text: str, options: dict) -> SuperPrompt

Behavior:

* Internally calls:

  * preprocess(user_text)
  * run_a2()
  * run_retrieval()
  * run_reranker()
  * run_a3()
  * run_a4()
  * run_a5()
  * build_prompt()
* Ensures that results are identical to pressing the same buttons in the same order with the same configuration (same SuperPrompt at the end).
* Options may later define which stages to skip or which agents to treat as human-in-the-loop (for example, stopping after A4 for manual review).

For now, auto mode is optional and can be implemented after the manual pipeline is stable.

7. Error handling and logging

7.1 Error categories

The controller distinguishes:

* User errors (invalid stage order, empty input text, missing active_project).
* Config errors (missing JSON config, missing vector store path).
* Stage failures (exceptions in an agent or retrieval).

7.2 Behavior on error

* Do not partially mutate SuperPrompt on stage failure.

  * Either apply all stage updates, or leave sp as it was before the call.
* Store a human-readable last_error on the controller (for GUI display).
* Optionally add error details into sp.extras["errors"] for later debugging.
* Never silently skip a stage; if something fails, show that the stage was not completed.

7.3 Logging

* High-level: controller logs each stage call with timestamp, stage name, and basic stats (for example number of chunks retrieved).
* Detailed logging remains inside agents, retrieval code, and ingestion code. The controller only logs stage-level events.

8. Integration with ingestion and memory

8.1 Selecting active project / DB

* Controller exposes:

  * select_project(project_name: str)
  * set_store_path(path: str)

* These methods:

  * Update active_project and active_store_path.
  * Optionally perform a light health check (for example ensuring that the Chroma DB exists).

8.2 Calling ingestion

* The GUI may provide an “Ingest” button that calls a controller method:

  * ingest_docs(project_name: str) -> IngestionStats

* Controller calls IngestionManager for the given project (doc_raw/project_name → chroma_db/project_name) and returns stats. 

8.3 Conversation history (future)

* Later, when conversation history ingestion is implemented, the controller will:

  * Append prompt/response pairs after each external LLM call.
  * Trigger history ingestion per the history design (for example, batched or async).
  * Pass history weights, tags, and filters to retrieval.

For now, this is a future extension; the controller API should leave room for a history_profile or similar flag.

9. Extensibility and governance

9.1 Adding new agents or stages

When a new agent or stage is added:

* A new controller method is introduced (or an existing one is extended) that:

  * Validates prerequisites.
  * Calls the agent module.
  * Updates SuperPrompt.stage, history_of_stages, and any stage-specific lists.
* The RAG_Pipeline requirements and GUI requirements are updated to reflect the new stage.

The controller must remain a thin orchestrator; complex agent behavior must live inside the agent modules.

9.2 Introducing AI agency or complex branching

Future advanced orchestrations (multiple retrieval passes, planner agents, different sequences per project) should:

* Keep controller methods as the “atomic” building blocks.
* Implement orchestration policies as small, explicit Python functions that call these methods in a specific order, rather than hiding orchestration inside agents.
* Preserve the invariant that a single SuperPrompt flows through the stages and carries all authoritative state.

9.3 Testing and acceptance

* For each stage method, write unit tests that:

  * Given a known SuperPrompt input and fixture outputs of the called module, assert that:

    * stage and history_of_stages are updated correctly.
    * views_by_stage and final_selection_ids are updated as expected.
    * prompt_ready contains expected markers (for example S_CTX_MD present after A4).
    * [24.04.2026] A4 tests must verify that A4 writes `S_CTX_MD`, `views_by_stage["a4"]`, `final_selection_ids`, stage/history, and A4 extras without corrupting previous retrieval/A3 state.
* For run_full_pipeline, write tests that:

  * Simulate the same steps as the GUI and ensure that the final SuperPrompt is identical.

This ensures that the controller remains a transparent, predictable orchestrator around the RAG pipeline and the agent stack.
