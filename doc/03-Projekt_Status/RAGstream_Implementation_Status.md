# GHOST / RAGstream Implementation Status

**Last update:** 27.07.2026 / KW31 2026

## Purpose and Use

This file is the current, standalone implementation-status snapshot for GHOST.

It is intended to give a new development or AI session a reliable overall picture of:

- what is implemented and working;
- what is currently in progress;
- what has been decided but not implemented;
- what remains open or requires verification.

Requirements may describe target or future behavior, while the codebase contains more detail than is practical for session transfer. This file therefore records the high-level implementation truth and current development direction.

The detailed historical implementation record through **28.05.2026 / KW22 2026** is preserved in:

```text
doc/03-Projekt_Status/RAGstream_Implementation_Status_Part1.md
```

---

## 1. Current Overall Picture

GHOST, formerly RAGstream, is a human-controlled AI orchestration platform for software-engineering work.

The current product has a working Streamlit frontend, an orchestration and SuperPrompt layer, JSON-configured LLM agents, project-document ingestion and retrieval, reusable engineering memory, structured logging, and an AWS deployment path.

The current executable Prompt Builder path is:

```text
User Prompt
→ deterministic PreProcessing
→ A2 PromptShaper
→ document Retrieval
→ ReRanker or pass-through
→ A3 usefulness gate
→ A4 evidence condensation
→ engineered prompt rendered through SuperPromptProjector
```

The current pipeline produces and displays an engineered prompt. A dedicated final product-level LLM send boundary is not yet completed. A5 and full Hard Rules enforcement remain postponed.

The Memory subsystem is separate from document knowledge and currently provides:

```text
Memory Recording
→ durable .ragmem / .ragmeta.json / SQLite truth
→ Memory Ingestion into a dedicated vector store
→ Memory Retrieval
→ runtime compression
→ MemoryMerge synthesis
→ synthesized Memory Context in SuperPrompt
```

The current implementation remains a private, single-user, single-workspace system. Blackboard persistence, multi-user SaaS behavior, and automatic requirement–architecture–code–test synchronization are not current product functionality.

---

## 2. High-Level Implementation History Through 28 May 2026

### By April 2026

The main document-processing and prompt-engineering foundation was operational:

- deterministic prompt preprocessing;
- JSON-based Agent Stack;
- A2 PromptShaper;
- project-based document ingestion;
- dense and SPLADE-based document retrieval with weighted fusion;
- optional reranking;
- A3 usefulness classification;
- A4 evidence condensation;
- SuperPrompt as shared runtime state;
- SuperPromptProjector for engineered-prompt rendering.

### 03.05.2026 / KW18 2026

The first structured Memory foundation was implemented:

- durable Memory Recording;
- Memory Ingestion into a dedicated memory vector store;
- corrected TextForge / RagLog sink-based logging.

### 06.05.2026 / KW19 2026

The Memory subsystem was extended with:

- initial Memory Retrieval;
- `MemoryContextPack`;
- semantic and recency scoring;
- server-side Memory Files management;
- automatic memory-history creation;
- Streamlit tab structure.

### 13.05.2026 / KW20 2026

The pipeline and ActiveBrief path were hardened:

- A4 empty-selection safety;
- hard retrieval similarity floor;
- A2 LLM bypass direction;
- two-dimensional ActiveBrief Relation Classifier using `prompt_materiality` and `topic_relation`;
- corrected ActiveRetrievalBrief compression limits.

### 28.05.2026 / KW22 2026

The project had reached the following integrated state:

- public product naming changed to GHOST;
- Streamlit UI redesigned around GHOST product identity;
- branding, visual presentation and pipeline overview improved;
- Prompt Builder frontend runner implemented through A4;
- ReRanker pass-through implemented when optional reranking is disabled;
- ChatGPT shared-link import added to the Files page;
- runtime Memory Compression and MemoryMerge synthesis implemented;
- Current User Request and Supporting Context clearly separated in prompt rendering;
- Metrics received an interactive visual pipeline demonstration;
- Blackboard remained a future/demo concept only.

By this point, the AWS Phase-1 deployment path was already working through GitHub Actions, ECR, EC2, Docker, nginx, HTTPS, Route53, SSM-based secret loading, and persistent runtime data outside the container image.

For detailed historical implementation bullets, see `RAGstream_Implementation_Status_Part1.md`.

---

## 3. Current Implemented Foundation

### 3.1 Frontend and Human Workbench

The current user interface is Streamlit.

Implemented frontend capabilities include:

- GHOST branding and visual identity;
- prompt input and engineered-prompt display;
- main Prompt Builder execution;
- optional manual pipeline controls;
- live pipeline status and runtime logging;
- project creation, selection and document ingestion;
- memory recording and memory cards;
- Files page for memory-history management;
- ChatGPT shared-link memory import;
- Metrics visual demonstration.

Hard Rules and General Settings are still incomplete areas. The Blackboard Actor control is not persisted as durable Blackboard functionality.

### 3.2 Document Knowledge Pipeline

The implemented document path includes:

- project-specific `.txt` and `.md` ingestion;
- stable chunk IDs and manifest-based file tracking;
- dense embeddings and ChromaDB;
- SPLADE sparse representations;
- weighted retrieval fusion;
- optional reranking;
- A3 usefulness selection;
- A4 document-context condensation;
- inspectable selected evidence and prompt-ready rendering.

SPLADE and reranking remain optional because practical testing has not consistently shown them to improve normal dense retrieval.

### 3.3 Agent and Prompt System

The current Agent Stack uses JSON-defined configurations and shared infrastructure:

- `AgentFactory`;
- `AgentPrompt`;
- `LLMClient`;
- selector, classifier and synthesizer behavior;
- A2, ActiveBrief classification, A3, A4 and memory-synthesis users.

`SuperPrompt` remains the authoritative in-memory state for one run. `SuperPromptProjector` remains the current rendering authority for the GUI-visible engineered prompt.

### 3.4 Memory System

Implemented Memory capabilities include:

- durable prompt/response recording;
- stable memory identity through `file_id` and `record_id`;
- `.ragmem`, `.ragmeta.json` and SQLite persistence;
- dedicated memory-vector ingestion;
- semantic and episodic retrieval;
- recency-aware scoring;
- ActiveRetrievalBrief generation and use;
- runtime memory compression;
- MemoryMerge synthesis;
- server-side create, load, rename and delete operations;
- ChatGPT conversation import into normal memory histories.

Memory compression and synthesized Memory Context are runtime products and do not replace durable MemoryRecord truth.

### 3.5 Logging and Deployment

TextForge / RagLog provides archive, file, CLI, GUI and developer-oriented logging routes.

The current AWS deployment runs the Streamlit product through:

```text
GitHub Actions
→ Amazon ECR
→ EC2
→ Docker
→ nginx
→ HTTPS
```

Persistent project, document, vector, memory and log data are intended to remain outside the disposable Docker image.

---

## 4. React / TypeScript and FastAPI Vision

### Decision History

- **24.05.2026 / KW21:** initial discussion;
- **23–25.06.2026 / KW26:** architecture discussion;
- **29.06.2026 / KW27:** main architectural decision;
- **22.07.2026 / KW30:** later refinement;
- **27.07.2026 / KW31:** current review.

### Status

This is an approved architectural direction, not an implemented migration.

The target structure is:

```text
React / TypeScript frontend
→ HTTPS / JSON
→ FastAPI backend
→ session_id
→ GhostSession / SessionStore
→ existing GHOST Python core
```

The existing Python pipeline, agents, retrieval, memory, orchestration, persistence and TextForge logic are to remain in the backend.

State ownership is intended to be separated:

- React owns temporary presentation state;
- FastAPI owns authoritative runtime state and live GHOST objects.

React, the temporary Streamlit frontend and MCP are intended to use shared backend capabilities. Pipeline and application logic must not be duplicated separately for each client.

The first planned vertical slice is:

```text
prompt in React
→ FastAPI
→ existing GHOST pipeline
→ structured JSON result
→ React display
```

Streamlit may remain temporarily during migration. A future deployment may use nginx to serve the built React frontend and proxy API requests to FastAPI.

A StrictDoc placeholder file exists for this future capability, but detailed atomic React/FastAPI requirements and implementation do not yet exist.

---

## 5. StrictDoc Requirements Refactoring

### Start and Direction

The main refactoring plan was documented on **01.07.2026 / KW27 2026**.

The objective is to replace the previous collection of large Markdown requirement documents with a structured StrictDoc requirement system using stable UIDs and explicit ownership.

### Current Status

A large part of the refactoring has been completed:

- root GHOST SRS created;
- capability-oriented StrictDoc tree created;
- stable requirement UIDs introduced;
- legacy Markdown requirements moved to `legacy_md/`;
- rendered StrictDoc HTML published through GitHub Pages;
- requirement ownership divided across orchestration, agents, preprocessing, knowledge, memory, context assembly, interfaces, operations, quality and future synchronization;
- audit instructions and Python/JSON inventories created;
- traceability CSV files created;
- major requirement-to-code audit and correction passes performed;
- future React/FastAPI and current MCP capability areas represented in the requirement tree.

The requirements refactoring is still formally in progress. The complete source-of-truth cutover from legacy Markdown to StrictDoc has not yet been declared finished.

Remaining requirement-management work includes:

- completing or reviewing remaining child requirement files;
- completing human-approved source-of-truth cutover;
- maintaining corrected UID-to-code traceability;
- later CI validation;
- later implementation of actual requirement–architecture–code–test synchronization agents.

---

## 6. Smaller June–July Implementation Changes

These are secondary changes rather than separate major project tracks.

### A2 Evidence Policy

A2 PromptShaper now selects an additional field:

```text
evidence_policy
```

Supported modes are:

```text
normal
local_context_first
strict_history_and_online_fact_check
```

The selected policy is written into SuperPrompt and rendered as explicit evidence-handling instructions in the engineered prompt.

A2 configuration rules were also strengthened for task-aware role, audience, tone, depth and evidence selection.

### Streamlit Refinements

Smaller frontend changes include:

- Files-page visual styling aligned with GHOST branding;
- stronger field and action-button presentation;
- callback-based manual pipeline buttons;
- cleaner Retrieval Top-K initialization;
- minor pipeline-status and UI corrections.

---

## 7. Potential Implementation Gaps Requiring Later Verification

Detailed analysis is stored in:

```text
doc/03-Projekt_Status/TODO/PotentialIMplementation_GAPS.md
```

These points came from requirement-to-code auditing. They should be verified against runtime call paths before being converted into implementation tickets.

Current potential gaps are:

1. `allow_memory_context` and `memory_context_policy` may not be enforced completely before memory retrieval, synthesis and SuperPrompt write-back.

2. The final ActiveBrief-aware `effective_retrieval_query_text` may not always be rebuilt after relation classification. Some requirement-facing schema fields may also not be mapped consistently to runtime fields.

3. An intentionally empty query from `WEAK + IRRELEVANT` routing may not be handled consistently as an explicit document-retrieval suppression signal.

4. Several document, evidence and memory tuning values still require consolidation into validated, versioned JSON configuration.

These are open verification and hardening topics, not automatically proven runtime failures.

---

## 8. MCP Server — Current Development Work

### Start and Objective

The current MCP implementation work started on **23.07.2026 / KW30 2026**.

The implementation status was reviewed on **27.07.2026 / KW31 2026**.

The first MCP version exposes one bounded tool:

```text
ghost_engineer_prompt
```

Its processing path is:

```text
prompt_text
→ fresh SuperPrompt
→ deterministic PreProcessing
→ A2 PromptShaper
→ engineered prompt
→ MCP client
```

The MCP server returns the engineered prompt. It does not produce the final answer and does not currently execute the full document-retrieval or Memory pipeline.

### Implemented MCP Core

The current server-side implementation includes:

- `ragstream/mcp/` package;
- prompt-engineering runner;
- strict tool input and output contract;
- fresh SuperPrompt per request;
- PreProcessing-before-A2 sequencing;
- stage and result validation;
- sanitized processing errors;
- unknown-tool rejection;
- low-level MCP Server;
- Streamable HTTP transport;
- Starlette `/mcp` route;
- Uvicorn runtime;
- synchronous GHOST work isolated from the asynchronous server loop;
- Host and Origin transport protection;
- authentication scaffold;
- in-memory rate-limiter scaffold;
- MCP architecture documentation;
- partial automated tests.

### MCP Work Still Open

The first release is not yet complete.

Remaining work includes:

- selecting and integrating an OAuth-compatible authorization solution;
- token, scope and protected-resource validation;
- integrating rate limiting before GHOST execution;
- aligning the tested MCP dependency version;
- replacing stale tests with final protocol-path tests;
- creating the separate MCP Docker container and ECR delivery path;
- creating independent EC2 activation and systemd startup;
- adding the nginx `/mcp` route without changing the Streamlit `/` route;
- injecting production secrets and deployment values;
- protocol acceptance;
- real Claude acceptance;
- real ChatGPT acceptance;
- verifying that ChatGPT uses the returned engineered prompt inside the same conversation.

Future MCP versions may investigate Active Memory, memory recording and memory retrieval. These contracts have not yet been finalized, and the server must not assume access to an entire native ChatGPT or Claude conversation unless the client explicitly supplies that information.

---

## 9. Current Open Product Areas

The principal open areas as of 27.07.2026 are:

1. complete and deploy MCP Version 1;
2. complete the StrictDoc migration and source-of-truth cutover;
3. verify and, where necessary, correct the potential implementation gaps listed in the TODO file;
4. test and tune memory selection, compression, Direct Recall and final memory-context policy;
5. define the final engineered-prompt / product-level LLM send boundary;
6. keep A5 and full Hard Rules enforcement postponed until their final responsibilities are approved;
7. preserve React/TypeScript + FastAPI as the approved future interface architecture, without describing it as implemented;
8. keep Blackboard, multi-user operation and automatic lifecycle synchronization clearly separated from current functionality.

---

## 10. Bottom Line

GHOST currently has a working Streamlit-based engineering workbench, document RAG pipeline through A4, structured Memory subsystem, central SuperPrompt construction, reusable logging infrastructure and working AWS deployment foundation.

Since June 2026, the main work has shifted to three new tracks:

```text
React / FastAPI
= approved future architecture vision

StrictDoc
= advanced requirement refactoring and traceability, largely built but not fully cut over

MCP
= current implementation track; functional server core exists, secured deployment and real-client acceptance remain open
```

The current immediate development focus is the MCP Version 1 completion and deployment path.
