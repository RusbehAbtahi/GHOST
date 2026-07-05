# Backlog_Future_Features.md

This document collects future feature ideas and long-term directions for RAGstream.
These are not current requirements. Each item describes the intended final behavior and goals, not the implementation details.

The purpose is to preserve the ideas so they can later be promoted into proper requirements when the core system (Agents, RAG pipeline, GUI, memory) is stable.

---

## 1. History Tagging System (GOLD / SILVER / RED / BLUE / etc.)

Goal
The system should allow the user to assign one or more tags to every question–answer pair (history entry). Tags have both:

* A short tag name (e.g. GOLD, SILVER, RED, BLUE, GREEN).
* A free-text user description (e.g. “Very important permanent rule”, “Unrelated topic”, “Old requirement, maybe obsolete”).

Tags are designed for the human user, not for the LLM. They are used to keep long histories disciplined and to separate “core knowledge” from noise.

Behavior

* Every Q/A pair can have multiple tags, and tags can be edited later.
* Tag meanings are visible in the GUI so the user remembers why something was marked GOLD, SILVER, etc.
* Tags are stored as part of the history metadata and are available to all future retrieval / memory logic.

---

## 2. Tag-Based Retrieval Rules

Goal
Tags should directly influence which history entries are eligible for retrieval and how strongly they are prioritized. Examples:

* GOLD: Always eligible for Layer-G, very high priority.
* SILVER: Eligible but must still pass semantic relevance checks (E-layer).
* RED: Explicitly excluded from retrieval.
* GREEN: Optional or “nice to have” material; lower priority.

Behavior

* The user can define, per tag, simple rules like “always include in G”, “only via embeddings”, “never include”, “include only for specific projects/pipelines”.
* These rules affect both automatic retrieval and any manual “import from history” tool.
* The retrieval pipeline should respect tag rules even if embeddings say something is relevant or irrelevant.

---

## 3. Tag Lifecycle and Versioning

Goal
Tags should support lifecycle management so outdated or superseded information does not continue to influence new prompts.

Behavior

* It should be possible to “retire” a tag or change its meaning. For example, SPEC_v1 (“old requirement version”) can be deprecated when SPEC_v2 is created.
* When a tag is retired or redefined, the system should stop treating those entries as active GOLD/SILVER (according to the user’s new rules).
* Optionally, some tags (e.g. GOLD) may have variants like GOLD_ACTIVE, GOLD_ARCHIVED to distinguish between current and historical gold.

---

## 4. Cross-Chat History Import by Tags

Goal
The system should allow a new project/chat to import only selected parts of older histories, based on tags, without pulling in noise.

Behavior

* In a new project, the user can choose “import all GOLD entries from these past sessions” (or any combination of tags).
* Only the entries that match these tags are loaded into the new project’s memory (Layer-G/E), not the full raw conversations.
* This enables combining the best prompts, requirements, and insights from multiple old chats into a clean starting knowledge base for a new project.

---

## 5. Generalized Fetcher Module (A1 Successor)

Goal
Create a general “Fetcher” module (instead of a narrow A1) that can load arbitrary blocks of information directly into Layer-G without embeddings.

Behavior

* Fetcher can load content from multiple sources: requirements files, UML blocks, code snippets, notes, external text files, etc.
* The user can target specific regions (e.g. “only this section of the UML text”) rather than whole files.
* Fetched content appears as “manual context chunks” in Layer-G and is clearly distinguished from embedding-based retrieval.
* Fetcher can be used both in the GUI and programmatically by controllers/agents.

---

## 6. Multi-DB Retrieval Orchestration

Goal
Allow the retrieval system to work with multiple Chroma DB projects (ProjectA, ProjectB, …) in flexible combinations.

Behavior

* The user can select one or more databases (e.g. “Requirements_DB” + “Code_DB”) for a given pipeline run.
* The controller can run retrieval on several DBs either separately or merged, and then union, intersect, or otherwise combine the results.
* Different pipeline stages (or even different agents) can query different DBs, depending on their task.
* All of this happens through a consistent API so retrieval remains stateless and composable.

---

## 7. Memory-Aware Future Agents

Goal
Enable future generations of agents (beyond A2–A5) to perform their own retrieval queries instead of relying only on the main RAG pipeline.

Behavior

* Agents can optionally call a retrieval interface to fetch additional context relevant to their specific sub-task (e.g. a “Refactorer” agent retrieving code snippets).
* These agent-driven retrievals still respect tag rules, DB selections, and global limits.
* The main controller remains responsible for overall budget and orchestration, but agents gain controlled autonomy in querying the memory.

---

## 8. Advanced History GUI

Goal
Provide a rich GUI for viewing, filtering, and managing conversation history and tags.

Behavior

* The GUI shows Q/A pairs with metadata: timestamps, tags, project, and possibly which pipeline stages were used.
* The user can filter by tag (e.g. show only GOLD+SILVER), by date, by project, or by text search.
* The GUI supports bulk operations (e.g. tag multiple entries, retire tags on many entries, move entries to archived).
* History view remains read-only for content but fully editable for metadata (tags, notes, status).

---

## 9. Manual Answer Capture GUI

Goal
Support workflows where the final LLM call is done manually in ChatGPT UI (or another tool), but the answer is still captured and stored as history.

Behavior

* The GUI provides a field where the user can paste the model’s response obtained from an external UI.
* The system stores this response paired with the final SuperPrompt and tags, as if it came from an API call.
* These manually captured pairs participate in retrieval, tagging, and import rules exactly like automatically captured ones.

---

## 10. Requirements Knowledge Graph File

Goal
Maintain a structured “knowledge graph” representation of the system architecture and requirements.

Behavior

* A dedicated markdown file (e.g. Requirements_KnowledgeGraph.md or System_KG.md) describes the main nodes (modules, agents, layers, pipelines) and edges (calls, depends_on, writes_to, reads_from).
* This graph is kept in sync with the real system at a high level, not down to every function.
* The graph serves both as human documentation and as input to future tools/agents that want to reason about system structure.

---

## 11. Optional TOON Export Adapter

Goal
Keep JSON as the internal standard format, but optionally support TOON (or any compact textual format) as an “export” wire format to the LLM.

Behavior

* All internal configs, schemas, and agent outputs remain JSON.
* At the edge (llm_client or AgentPrompt), the system can convert a JSON object into TOON syntax before sending it to the model.
* If TOON proves useful or widely adopted in future, this adapter can be enabled per agent or per call; otherwise it can be left disabled.

---

## 12. Multi-Provider LLM Routing

Goal
Allow the system to use different LLM providers and models (OpenAI, local TinyLlama, AWS, etc.) behind a unified interface.

Behavior

* Agents specify “what they need” (capabilities and constraints), not a hard-coded provider.
* The llm_client (or a routing layer) decides which backend to use based on configuration (e.g. OpenAI for A2 now, TinyLlama for some other agent later).
* Routing respects token budgets, cost preferences, and model quality requirements.
* The rest of the system (AgentFactory, AgentPrompt, pipeline stages) remains unchanged when switching backends.

---

## 13. Data-Driven AgentMaker / Agent Composition

Goal
Make agent behaviors highly configurable by data (JSON configs), so new agents can be created by combining existing building blocks instead of writing new Python each time.

Behavior

* AgentMaker reads configuration describing: enums, input fields, purpose text, system role, output schema, and type (Chooser/Writer/Extractor).
* Based on these configs, AgentMaker assembles an agent (via AgentFactory + AgentPrompt) without changing core code.
* A new agent (e.g. “A6_Refactorer”) can be created by adding a new JSON file and registering it, with minimal or no new Python logic.

---

## 14. GUI Attention Controls

Goal
Give the user direct, simple control over which data sources and tag classes are active for a given run.

Behavior

* GUI controls (checkboxes, drop-downs, sliders) allow selecting:

  * Which DB projects are used (Project1, Project2, etc.).
  * Which tags are considered (include GOLD+SILVER, exclude BLUE, etc.).
* The retrieval / pipeline respects these settings for that run, making it easy to test different attention profiles without code changes.

---

## 15. Per-Stage Debug Views

Goal
Provide introspection tools to see what each pipeline stage did, to support debugging and learning.

Behavior

* For Retrieval: show which chunks were retrieved, with scores.
* For ReRanker: show reranked order and cross-encoder scores.
* For A3: show keep/drop decisions and reasons (if available).
* For A4: show which chunks were condensed into S_CTX and which were dropped due to budget.
* These views are read-only and do not affect the pipeline; they are diagnostic tools.

---

## 16. Input Format Normalizer (JSON / YAML / TOON / HTML → Canonical Markdown)

Goal
Allow the user to submit prompts in multiple formats (plain text, markdown, JSON, YAML, TOON, HTML, etc.), and convert them to a single canonical format before PreProcessing.

Behavior

* At the very beginning of A0_PreProcessing, the system detects whether the raw input looks like valid JSON, YAML, TOON, or other structured formats.
* If a known format is detected, it is parsed and converted into the internal markdown / key–value representation that PreProcessing expects (e.g. mapping fields to TASK, CONTEXT, PURPOSE, etc.).
* If no structured format is detected, the input is treated as plain text (as today).
* This makes the system robust to different user workflows and allows future automation that sends JSON or other formats directly.


