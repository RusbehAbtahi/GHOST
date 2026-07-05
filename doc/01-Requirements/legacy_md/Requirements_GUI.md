# Requirements_GUI.md

Last update: 24.04.2026

Note for future maintenance:
- When new implementation-aligned GUI features or behavior changes are added here, they should be date-stamped inline so the chronology stays visible.

1. Scope and assumptions

---

1. The GUI is the human-facing front-end for RAGstream. Its main job is:

   * to let the user write and inspect prompts,
   * to step through or trigger the 8-stage RAG pipeline,
   * to manage ingestion and active DB selection,
   * and, in later versions, to manage history, tags, and model calls.

2. There will be three GUI “generations”:

   * Generation 1: Intermediate GUI (current Streamlit view, manual, pipeline-centric).
   * Generation 2: Main GUI with history, tags, model selection, cost view, manual answer capture.
   * Generation 3: Advanced GUI (multi-history, attention controls, tools, etc.) – ideas only.

3. The implementation technology for Generation 1 and 2 is currently Streamlit. In the current implemented Generation-1 structure, the GUI is split into `ui_streamlit.py` (bootstrap / session setup / controller startup), `ui_layout.py` (geometry and widget layout), and `ui_actions.py` (callbacks and controller-triggered actions). The requirements are still written so that the GUI could later be reimplemented in another framework without changing behavior.

4. All pipeline logic and state live in the controller + `SuperPrompt`. The GUI is a thin layer that:

   * sends user actions to the controller, and
   * renders the current `SuperPrompt.prompt_ready` and relevant debug information.

5. Core concepts used by the GUI

---

1. `SuperPrompt` is the canonical object that represents the current prompt and context. It has fields like:

   * `body`, `System_MD`, `Prompt_MD`, `S_CTX_MD`, `Attachments_MD`,
   * `prompt_ready` (final composed prompt),
   * `stage`, `history_of_stages`,
   * retrieval views and selection ids.

2. The 8 RAG pipeline stages are:

   * A0_PreProcessing
   * A2_PromptShaper
   * Retrieval
   * ReRanker
   * A3_NLI_Gate
   * A4_Condenser
   * A5_Format_Enforcer
   * Prompt_Builder

   Their behavior is defined in `Requirements_RAG_Pipeline.md`. GUI requirements here only describe their *invocation* and *visualization*.

3. The GUI must always operate on a single active `SuperPrompt` instance per session. After each stage, the controller updates that instance, and the GUI re-renders the current `prompt_ready` and any stage-specific info.

4. Generation 1 – Intermediate GUI (pipeline tester)

---

3.1 Objectives

1. Let the user:

   * type or paste a raw prompt (plain text or markdown with `##` headers),
   * manually run each of the 8 pipeline stages in order,
   * inspect how `SuperPrompt` changes after each stage,
   * run ingestion and choose the active project / DB pair.

2. This GUI is primarily for development and debugging, not for end users:

   * it exposes all stages,
   * everything is triggered manually with buttons,
   * there is no history or tagging yet,
   * no API call to external LLMs from this generation.

3.2 Layout

The intermediate GUI must provide at least the following UI elements:

1. Prompt input area

   * A large text area labeled “User Prompt” (or similar).
   * The user can:

     * paste a simple, naked text prompt, or
     * paste markdown with `##SYSTEM`, `##TASK`, etc.
   * When A0_PreProcessing runs, this text is the raw input.

2. SuperPrompt view

   * A large text area labeled “SuperPrompt (prompt_ready)”.
   * After each stage button is pressed, this area shows the current `SuperPrompt.prompt_ready` exactly as it would be sent to an LLM (for this generation, it is just visible, not sent).
   * This field can be read-only in the UI; editing is not required in Generation 1.

3. Pipeline control buttons (8 buttons)
   Each stage has its own button, in this order:

   * Button: “A0 – PreProcessing”
   * Button: “A2 – PromptShaper”
   * Button: “Retrieval”
   * Button: “ReRanker”
   * Button: “A3 – NLI Gate”
   * Button: “A4 – Condenser”
   * Button: “A5 – Format Enforcer”
   * Button: “Prompt Builder (Final Prompt)”

   Behavior:

   * When a button is pressed, the controller:

     * runs the corresponding stage on the active `SuperPrompt`,
     * returns the updated `SuperPrompt`.
   * The GUI then:

     * updates the SuperPrompt view,
     * updates any stage-specific debug area (see 3.3.2).

4. Ingestion controls

   * Text input / file-browser-like field “Raw folder under data/doc_raw” (e.g. `Project1`).
   * Button: “Ingest Folder”:

     * It must take a folder path under `data/doc_raw` (e.g. `myroot/data/doc_raw/Project1`),
     * run the ingestion pipeline on all text/markdown files in that folder,
     * create/update the corresponding dense store in `data/chroma_db/Project1`,
     * and create/update the corresponding sparse store in `data/splade_db/Project1`.
   * A small status area shows:

     * success message (number of files, project name),
     * or clear error messages.

5. Active DB selection

   * A dropdown or radio button group labeled “Active DB / Project”.
   * Options correspond to project names known to the controller. In the current implementation this may be derived from the project folders under `data/doc_raw`, `data/chroma_db`, and `data/splade_db`.
   * The currently selected project name is passed to Retrieval/ReRanker so they know which dense/sparse stores to query.

6. Retrieval / ReRanker score display

   * The intermediate GUI must support score-aware inspection for Retrieval and ReRanker.
   * [14.04.2026] After Retrieval, the GUI should be able to show the fused Retrieval order together with the component Retrieval signals used for that order. In the current implementation this includes the fused retrieval score and the dense/SPLADE component signals.
   * After ReRanker, the GUI should be able to show the final reranked order together with the previous Retrieval ranking and the ReRanker-related score or rank data used for the fused final order.

7. Minimal debug/status info

   * A small area (or a few lines) showing:

     * the current stage (`SuperPrompt.stage`),
     * number of retrieval candidates and final selections (after Retrieval, ReRanker, A3, A4).
   * A status line at the bottom showing the result of the last action (OK, error, message).

3.2.1 Additional project-based ingestion controls

1. In addition to the ingestion controls above, the intermediate GUI must provide two explicit project-based ingestion buttons placed below the 8 pipeline control buttons.

2. Button: “Create Project”

   * When pressed, the GUI opens a small popup/dialog/input flow that asks for a project name (for example `project1`).
   * After confirmation, the controller creates the matching project folders:

     * `data/doc_raw/<project_name>`
     * `data/chroma_db/<project_name>`
     * `data/splade_db/<project_name>`

3. Button: “Add Files”

   * When pressed, the GUI opens a popup/menu/dialog flow where the user:

     * chooses an existing project,
     * selects one or multiple source files.

4. Supported file scope for this flow

   * The selected source files for this GUI flow must be text files or markdown files.
   * The GUI flow is intended for `.txt` and `.md` ingestion input.

5. File import behavior

   * The selected files are copied into the chosen raw project folder under:

     * `data/doc_raw/<project_name>`

   * After the copy step, the controller automatically triggers ingestion for that same project.

6. Chroma update behavior

   * The automatic ingestion step must create or update the matching dense/sparse project stores under:

     * `data/chroma_db/<project_name>`
     * `data/splade_db/<project_name>`

7. Status behavior for the new buttons

   * The GUI status area must report:

     * selected project name,
     * number of files copied,
     * and whether the automatic ingestion/update completed successfully or failed.


3.2.2 Current implemented Generation-1 layout and runtime behavior

1. [17.04.2026] The current implemented Generation-1 layout is split visually into two main sides:

   * left side:

     * Prompt input at the top,
     * SuperPrompt view directly below it.

   * right side:

     * Memory Demo at the top,
     * pipeline buttons below Memory Demo,
     * Retrieval / ReRanker controls below the buttons,
     * project / ingestion controls and related status areas below that.

2. [17.04.2026] The Retrieval / ReRanker control row currently includes:

   * `Retrieval Top-K`,
   * checkbox `use Retrieval Splade`,
   * checkbox `use Reranking Colbert`.

3. [17.04.2026] The two checkboxes above are current Generation-1 controls and must default to `off` unless the user changes them.

4. [17.04.2026] The current Generation-1 GUI/controller path supports optional slow-component bypass while keeping downstream stage contracts stable:

   * if `use Retrieval Splade` is off, the system may bypass real SPLADE retrieval/scoring and preserve the downstream Retrieval contract with a deterministic substitute,
   * if `use Reranking Colbert` is off, the system may bypass real ColBERT reranking and preserve the downstream reranked-stage contract with a deterministic substitute.

5. [17.04.2026] The current controller/UI startup design is no longer a single blocking initialization step. The GUI must support:

   * light startup for immediate page visibility,
   * heavy Retrieval / ReRanker component warm-up in the background,
   * readiness-gated behavior so buttons that depend on heavy components do not behave as if those components are ready before they actually are.

6. [24.04.2026] The A4 Condenser button is now connected to the live controller path. When pressed, it runs `ctrl.run_a4(sp)`, stores `sp_a4`, and refreshes the SuperPrompt view from the updated `sp.prompt_ready`.

7. [24.04.2026] The GUI-visible SuperPrompt rendering after A4 is owned by `SuperPromptProjector.compose_prompt_ready()`. The GUI remains thin and only displays the rendered `prompt_ready`.

3.3 Stage-specific behavior and state machine

3.3.1 Global state machine

1. The GUI must enforce a legal order of stages using a simple state machine:

   * Precondition: A0_PreProcessing must be run at least once before any retrieval stage.
   * Normal forward order:

     * A0 → A2 → Retrieval → ReRanker → A3 → A4 → A5 → Prompt Builder.
   * A2 may be re-run any time after A0 (and before or after retrieval), as long as the pipeline is in a consistent state:

     * e.g. user can do A0 → A2 → A2 (refine meta labels) → Retrieval → …
   * Buttons for illegal transitions must either:

     * be disabled, or
     * show a clear error message (“Please run PreProcessing first”, “You must run Retrieval before ReRanker”, etc.).

2. The controller is the single authority for stage transitions:

   * It validates whether a stage can be run given the current `SuperPrompt.stage`.
   * If not, it returns an error that the GUI displays.

3. The GUI must not mutate `SuperPrompt` directly; only stages do so.

3.3.2 What is shown in SuperPrompt view per stage

The SuperPrompt view always shows the current `SuperPrompt.prompt_ready`. Internally, this is updated step by step as defined in `Requirements_RAG_Pipeline.md`. For the GUI, the behavior should feel like this:

1. After “A0 – PreProcessing”

   * `prompt_ready` shows the normalized prompt with canonical headers, MUST defaults, and any extras that A0 writes.
   * No retrieval context is shown yet.

2. After “A2 – PromptShaper”

   * `prompt_ready` still shows the whole prompt, but now with the updated `system`, `audience`, `tone`, `depth`, and `confidence`.
   * The GUI doesn’t need to highlight these specifically, but the text reflects the new meta labels.

3. After “Retrieval”

   * In addition to the prompt text, the resulting `prompt_ready` should include the retrieved raw chunks in a clearly separated retrieved-context block.

   * The displayed order must reflect the final Retrieval ranking used by the stage.
   * [14.04.2026] In the current implementation, the GUI-compatible projection may show component Retrieval values such as fused Retrieval score, dense branch score, and SPLADE branch score for debugging.
   * [24.04.2026] The current GUI-visible projector should place raw retrieved chunks under `## Retrieved Context / ### Raw Retrieved Evidence` rather than merging them with the user task.

   * This is primarily for human inspection, not the final production-send format.

4. After “ReRanker”

   * `prompt_ready` is updated so that the raw retrieved evidence block lists the reranked chunks in their new order.
   * The displayed order must reflect the final fused ReRanker result used by the stage.
   * [14.04.2026] In the current implementation, the GUI-compatible projection may show ReRanker score together with the previous fused Retrieval score and the dense/SPLADE component signals for debugging.
   * [24.04.2026] The ReRanker view must still use the same retrieved-context separation as Retrieval; reranked evidence must not be rendered as part of `### Task`.

5. After “A3 – NLI Gate”

   * `prompt_ready` is updated so the raw retrieved evidence block now contains only the chunks that survive A3 usefulness filtering. Discarded chunks are removed; borderline chunks may still survive if the deterministic A3 post-processing promotes them to satisfy the working-set floor.

6. After “A4 – Condenser”

   * [24.04.2026] `prompt_ready` must show the A4 condensed context as retrieved support material, not as part of the user task.
   * [24.04.2026] The GUI-visible structure after A4 must be:

     ```markdown
     ## System
     <system roles / system instruction>

     ## Configuration
     - Audience: ...
     - Tone: ...
     - Depth: ...
     - Confidence: ...   <!-- if available -->

     ## User

     ### Task
     <always present>

     ### Purpose
     <only if present>

     ### Context
     <only if present>

     ## Retrieved Context

     ### Retrieved Context Summary
     The following summary is retrieved from selected project files or memory. It is supporting context for the task, not part of the task itself.

     <S_CTX_MD if available>

     ### Raw Retrieved Evidence
     <raw retrieved chunks if available>
     ```

   * [24.04.2026] Raw retrieved chunks may remain visible in Generation 1 for development, audit, and debugging, but `S_CTX_MD` is the main condensed context block after A4.

6.1. [24.04.2026] Raw retrieved evidence rendering rules

1. Raw retrieved chunks must be nested under an XML-like wrapper, for example:

   ```xml
   <retrieved_chunks>
     <chunk index="1" chunk_id="..." source="...">
       <chunk_text>
         ...
       </chunk_text>
     </chunk>
   </retrieved_chunks>
   ```

2. Source Markdown headings inside retrieved chunks must not remain active markdown headings in the GUI-visible SuperPrompt. They must be neutralized as markers such as:

   * `# Heading` -> `[H1] Heading`
   * `## Heading` -> `[H2] Heading`
   * `### Heading` -> `[H3] Heading`

3. The purpose of this rule is to prevent source-document headings from competing with the main prompt structure (`## System`, `## Configuration`, `## User`, `## Retrieved Context`).

7. After “A5 – Format Enforcer”

   * The prompt reflects normalized output format instructions (for JSON/markdown/etc.), but in Generation 1 it is still just a textual prompt shown in the SuperPrompt view.

8. After “Prompt Builder (Final Prompt)”

   * `prompt_ready` is the true final SuperPrompt as it would be sent to the answering LLM:

     * System block,
     * Prompt/User block,
     * Retrieved Context / S_CTX block,
     * Attachments or raw evidence block when enabled,
     * Optional recent conversation block.

   * [24.04.2026] Prompt Builder should reuse or stay aligned with the same high-level section separation already used by `SuperPromptProjector` so GUI preview and final-send assembly do not diverge.

3.3.3 Project-based ingestion routing and manifest placement

1. For the project-based ingestion buttons, the GUI must not implement embedding, hashing, chunking, or vector-store logic itself.

2. The GUI only collects user actions and inputs:

   * project creation request,
   * project selection,
   * file selection.

3. The controller is responsible for:

   * creating the matching project folders,
   * copying the selected files into `data/doc_raw/<project_name>`,
   * and calling the existing ingestion pipeline for that same project.

4. [14.04.2026] In the current implementation, project creation creates all three aligned project folders:

   * `data/doc_raw/<project_name>`
   * `data/chroma_db/<project_name>`
   * `data/splade_db/<project_name>`

5. The hash/manifest file used by ingestion for a given project must be saved inside the matching Chroma DB project folder and use one standard filename (`file_manifest.json`) for all projects.

6. Therefore, the hash/manifest path must be project-scoped and aligned with the matching Chroma DB project path, i.e. it belongs inside:

   * `data/chroma_db/<project_name>`

7. This GUI requirement does not require changes to the internal ingestion backend; it only requires correct GUI/controller wiring for project-based ingestion.

3.3.4 Retrieval / ReRanker evolution compatibility

1. The intermediate GUI must remain compatible if Retrieval evolves from one signal to multiple first-pass signals, as long as it still remains one button and one stage from the user perspective.

2. The intermediate GUI must remain compatible if ReRanker evolves from one reranking model to a fused reranking stage, as long as it still remains one button and one stage from the user perspective.

3. This means the GUI contract is stable at stage level even if the internal ranking logic becomes:

   * multi-signal Retrieval, and/or
   * fused ReRanker ranking.

3.4 Non-goals for Intermediate GUI

1. No history view (only current session).
2. No tagging (GOLD/SILVER/etc.).
3. No model selection or cost estimation.
4. No direct LLM call from this GUI generation.

All of these are reserved for Generation 2 and 3.

4. Generation 2 – Main product GUI (history, tags, LLM)

---

Generation 2 builds on the intermediate GUI and adds:

* chat history,
* tags,
* model selection and direct LLM call,
* cost estimation,
* manual answer capture.

Details are intentionally less strict than Generation 1 but must express the final goals.

4.1 Objectives

1. Provide a usable “product-level” GUI where:

   * the user can create prompts and run them through the pipeline (manual or controller-driven),
   * the final SuperPrompt can be sent directly to an LLM via API,
   * history and tags are visible and manageable,
   * costs are visible and not surprising,
   * manual answer capture is supported.

2. Generation 2 is the first version where you can say “the product is finished” for personal and internal use.

4.2 Chat history and tags

1. The GUI must display a conversation history, where each entry is a Q/A pair:

   * `user` – the prompt (ideally the final SuperPrompt or a simplified view),
   * `assistant` – the model’s answer (either from API or pasted manually),
   * metadata (timestamp, project, etc.).

2. Every conversation entry must support tags:

   * minimal structure example:

     ```json
     {
       "id": 1,
       "user": "...",
       "assistant": "...",
       "tags": ["GOLD"]
     }
     ```

   * The exact JSON shape is not fixed yet, but:

     * each entry can have 0–N tags,
     * tags are strings,
     * tags have user-editable meanings (descriptions) somewhere in the GUI.

3. The GUI must allow:

   * assigning tags to a single entry (e.g. via dropdown, checkbox, or text input),
   * editing or removing tags,
   * filtering history by tags (e.g. show only GOLD, or hide BLUE).

4. These tags will later drive retrieval/tag rules and cross-chat import, but for Generation 2 it is enough that:

   * tags are visible,
   * tags can be assigned and changed,
   * tags are persisted.

4.3 Model selection and sending SuperPrompt to LLM

1. The GUI must provide controls for selecting a model and calling it:

   * A dropdown (“Model”) listing available backends (e.g. OpenAI models).
   * A button “Send Final SuperPrompt” (or similar).

2. When the user presses “Send Final SuperPrompt”:

   * The controller must ensure that:

     * the full pipeline has been run (A0 → … → Prompt Builder),
     * or, at least, that a consistent `prompt_ready` exists.
   * The llm_client is invoked with:

     * the selected model,
     * the final `prompt_ready` contents.
   * The model’s output is stored as a new history entry, associated with:

     * the final SuperPrompt,
     * the model name,
     * any tags the user adds (e.g. GOLD for a very good answer).

3. The GUI must show the model’s answer in the history view and optionally in a “Current Response” pane.

4.4 Cost estimation

1. The GUI must provide a simple cost estimation view for each run:

   * For each agent call (A2, A3, A4, A5, and final answer call), show:

     * approximate prompt tokens,
     * approximate completion tokens,
     * approximate cost based on configured price per token.

   * For each session, show:

     * total estimated cost of all LLM calls in that session.

2. Cost data can be:

   * rough estimates (no need for perfect accuracy),
   * but they must be calculated in a consistent way, based on:

     * token length of `prompt_ready` and other calls,
     * model pricing from configuration.

3. The cost view must be clearly visible but not intrusive, e.g. a side panel or bottom bar.

4.5 Manual answer capture

1. The GUI must support a workflow where:

   * the user copies the final SuperPrompt,
   * pastes it into ChatGPT UI or another external client,
   * then copies the model’s answer back into RAGstream.

2. For this, the GUI must have:

   * a text field labeled e.g. “Paste external model answer here”,
   * a button like “Save as history entry”.

3. When the user presses “Save as history entry”:

   * the system creates a Q/A history entry that:

     * uses the current final SuperPrompt as `user`,
     * uses the pasted text as `assistant`,
     * allows the user to assign tags (e.g. GOLD),
     * stores all metadata as if the answer had come via API.

4. Manual and API answers should be indistinguishable in how history and tags operate.

4.6 Relationship between manual and automatic triggering

1. Generation 2 must allow both:

   * manual step-by-step runs (like Intermediate GUI), and
   * automatic “one click” run, where the controller executes the full pipeline and then calls the LLM.

2. The GUI may reuse the same 8 pipeline buttons or offer:

   * a “Run all stages + send to LLM” button,

   * while still exposing the individual stage buttons for debugging.

3. Generation 3 – Advanced GUI (vision)

---

Generation 3 collects ideas and directions; it is not a commitment. It describes one possible future advanced GUI beyond Generation 2.

5.1 Goals

1. Turn RAGstream into a full interactive workbench for:

   * complex RAG and agentic workflows,
   * multiple projects,
   * software development support (e.g. V-model activities).

2. Provide powerful but controlled tools for:

   * multi-history and multi-project management,
   * dynamic attention / context control,
   * agent orchestration and tool use.

5.2 Possible features (non-binding)

The following ideas are examples; they may change:

1. Multiple history control

   * View and manage many histories across projects.
   * Import/export histories by tag (e.g. import GOLD items from 10 chats).
   * Visualize which histories contribute to the current `SuperPrompt`.

2. Dynamic attention control

   * Sidebars or panels where the user can:

     * toggle which projects/DBs are active,
     * select which tags are considered (GOLD, SILVER, etc.),
     * adjust weights or priorities of different memory sources.

3. Sidebar controls for agents and tools

   * Controls to enable/disable certain agents or tools (e.g. code refactorer, test generator).
   * Configuration of agent roles and models without editing JSON by hand.

4. AI-Agency and orchestration view

   * Visual representation of the agent graph / flow (who calls whom, in what order).
   * Ability to trigger “sub-flows” (e.g. code generation, test design, documentation generation) as separate tasks.

5. V-Diagram aware tooling

   * Panels for requirements, design, implementation, testing, and validation, aligned with V-model stages.
   * Ability to track which requirements and tests relate to which agents and prompts.

6. Extended debug and analysis tools

   * Rich per-stage visualizations (retrieval, rerank, NLI decisions, condensation).
   * Token and cost heatmaps.
   * Comparison of different runs (e.g. “diff” between two S_CTX versions).

5.3 Status of Generation 3

1. Generation 3 is visionary only in this document.
2. No layout, technology, or fixed feature set is decided yet.
3. When Generation 2 is stable and in real use, selected ideas from Generation 3 can be promoted into their own detailed requirement documents.