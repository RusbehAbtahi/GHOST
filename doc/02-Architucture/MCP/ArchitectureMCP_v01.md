# GHOST MCP Architecture

**Project:** GHOST — GenAI Hybrid Orchestrator for Software Tooling  
**Document type:** Authoritative MCP architecture  
**Version:** 1.0  
**Date:** 29 July 2026  
**Status:** Current architecture with explicitly marked immediate and future extensions

---

## 1. Purpose

This document defines the authoritative architecture of the GHOST Model Context Protocol integration.

It describes:

```text
what the MCP subsystem is;
where it sits inside GHOST;
which components own which responsibilities;
how ChatGPT or Claude reaches GHOST;
how OAuth protects the service;
how MCP tools are exposed and executed;
which behavior is currently implemented;
which behavior is the immediate next implementation;
how the architecture expands to multiple tools, memory, GitHub, and AWS.
```

The renamed `MCP_Conceptual_Request_Flow.md` remains a learning document. This file is the architecture source of truth.

Operational commands, fixed identifiers, callback URLs, and troubleshooting belong in:

```text
doc/05-Design_Process/MCP/MCP_002/MCP_Operations_Runbook.md
```

Implementation history, failures, and validation evidence belong in:

```text
doc/05-Design_Process/MCP/MCP_002/MCP_Implementation_Report.md
```

---

## 2. Architectural Goal

The MCP subsystem turns GHOST from a standalone Python application into a reusable capability layer that external AI clients can invoke.

```text
ChatGPT or Claude
→ authenticated MCP tool call
→ GHOST Python architecture
→ deterministic processing, LLM agents, memory, retrieval, project systems, and external APIs
```

The first implemented capability is prompt engineering. The architecture is deliberately designed so that later capabilities can be added as additional MCP tools without rebuilding the complete connection.

---

## 3. System Boundary

### 3.1 Inside the GHOST MCP subsystem

```text
MCP HTTP endpoint
OAuth metadata endpoint
Cognito token verification
MCP server and transport
tool discovery
tool dispatch
tool input/output validation
GHOST capability adapters
sanitized error handling
```

### 3.2 Existing GHOST components reused by MCP

```text
SuperPrompt
deterministic PreProcessing
A2 PromptShaper
existing model configuration
later: retrieval, memory, ingestion, requirements, architecture, and GitHub services
```

### 3.3 Outside the GHOST MCP subsystem

```text
ChatGPT or Claude user interface
client-side MCP implementation
OpenAI Secure MCP Tunnel
Amazon Cognito hosted login
nginx and public TLS termination in AWS
external GitHub or other service APIs
```

---

## 4. Architectural Principles

### 4.1 One server, one MCP endpoint, many tools

```text
one GHOST MCP server
one logical /mcp endpoint
one OAuth protection model
many semantically separate tools
```

A new GHOST capability normally becomes a new MCP tool, not a new server or HTTP endpoint.

### 4.2 Stable external contracts

Tool names, input fields, output fields, and general metadata should remain stable once registered with an AI client.

Runtime behavior that must be tuned should be returned dynamically in the tool result rather than repeatedly changing frozen client metadata.

### 4.3 GHOST owns deterministic behavior

Python code selects modes, validates inputs, retrieves data, writes persistent state, and enforces application rules.

The AI client remains heuristic and controls how it responds in its own interface.

### 4.4 Existing GHOST logic is reused

MCP adapters must call existing GHOST application services. They must not create duplicate implementations of preprocessing, agents, retrieval, or memory.

### 4.5 Request isolation

Each prompt-engineering request creates a fresh `SuperPrompt`. Mutable prompt state is not shared across independent requests.

### 4.6 Persistent state belongs to GHOST

Cross-chat memory, tagged episodes, indexes, and project state belong to GHOST-controlled storage, not to the temporary conversation memory of ChatGPT or Claude.

### 4.7 ChatGPT remains the final answering model

For the current prompt-engineering use case, GHOST shapes the prompt and returns it. GHOST does not make an additional final-answer LLM call.

---

## 5. System Context

```text
┌──────────────────────────────────────────────────────────────┐
│ AI Client                                                    │
│ ChatGPT or Claude                                            │
│                                                              │
│ User interaction                                             │
│ MCP client implementation                                    │
│ Tool selection and client-side orchestration                 │
└──────────────────────────────┬───────────────────────────────┘
                               │ HTTPS / MCP Streamable HTTP
                               │ OAuth 2.0 Bearer token
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Connection Boundary                                          │
│                                                              │
│ Current local path: OpenAI Secure MCP Tunnel                  │
│ Target AWS path: public HTTPS + nginx                         │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ GHOST MCP Server                                             │
│                                                              │
│ Uvicorn                                                      │
│ Starlette                                                    │
│ OAuth metadata and authorization challenge                   │
│ Cognito token verification                                   │
│ StreamableHTTPSessionManager                                 │
│ MCP Server                                                   │
│ tool registry and dispatcher                                 │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ GHOST Capability Layer                                       │
│                                                              │
│ ghost_engineer_prompt                                        │
│ future memory, retrieval, GitHub, requirements, architecture │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ GHOST Core and Persistent Systems                            │
│                                                              │
│ SuperPrompt, PreProcessing, A2, later A3/A4                  │
│ SQLite, JSON memory, ChromaDB, project files, GitHub APIs     │
└──────────────────────────────────────────────────────────────┘
```

---

## 6. Five-Entity Communication Model

The MCP integration follows the reusable communication ontology:

```text
Client
→ Client Interface
→ Communication Channel
→ Server Interface
→ Server
```

Mapped to GHOST:

```text
Client
  ChatGPT or Claude

Client Interface
  MCP client embedded in ChatGPT or Claude

Communication Channel
  HTTPS + MCP Streamable HTTP + OAuth Bearer token
  currently transported through OpenAI Secure MCP Tunnel

Server Interface
  nginx or tunnel boundary
  Uvicorn
  Starlette
  OAuth middleware and MCP transport

Server
  GHOST MCP application
  GHOST tools
  existing GHOST core services
```

This model is independent of a particular AI vendor.

---

## 7. Current Local Deployment Topology

The currently proven local topology is:

```text
ChatGPT
→ OpenAI Secure MCP Tunnel
→ tunnel-client on the local Linux machine
→ http://127.0.0.1:8000/mcp
→ Uvicorn
→ Starlette
→ Cognito token verification
→ MCP transport and server
→ GHOST tool
```

Two local processes must run:

```text
1. python -m ragstream.mcp.server
2. ~/.local/bin/tunnel-client run
```

The Streamlit GUI is not part of this request path.

```text
Streamlit application       GHOST MCP server
independent process         independent process
browser GUI                 protocol server
session-oriented UI         stateless MCP requests
```

---

## 8. Server-Side Component Architecture

### 8.1 Uvicorn

Responsibility:

```text
open the network socket;
receive HTTP traffic;
run the ASGI application;
return HTTP responses.
```

Uvicorn does not understand GHOST tools or prompt engineering.

### 8.2 Starlette

Responsibility:

```text
define HTTP routes;
run startup and shutdown lifecycle;
connect HTTP requests to handlers;
host the public OAuth metadata endpoint;
host the protected /mcp endpoint.
```

### 8.3 Cognito authentication component

Responsibility:

```text
extract Bearer access token;
retrieve and cache Cognito JWKS;
verify JWT signature;
verify issuer;
verify app-client identity;
verify token use;
verify required OAuth scope;
return authenticated claims or a sanitized HTTP error.
```

### 8.4 Streamable HTTP Session Manager

Responsibility:

```text
translate HTTP traffic into MCP transport messages;
manage the MCP Streamable HTTP lifecycle;
forward MCP messages to the low-level MCP server;
convert MCP responses back into HTTP responses.
```

The current server uses stateless operation. Each request must be independently processable.

### 8.5 Low-level MCP Server

Responsibility:

```text
MCP initialization;
capability negotiation;
tools/list;
tools/call;
dispatch to registered handlers.
```

### 8.6 GHOST MCP application layer

Responsibility:

```text
advertise available tools;
validate requested tool names;
validate tool arguments;
call the correct GHOST capability adapter;
validate internal results;
convert results to MCP CallToolResult;
sanitize failures.
```

### 8.7 GHOST capability adapters

Responsibility:

```text
bridge stable MCP contracts to existing GHOST services.
```

The current adapter is `GhostEngineerPromptTool`.

---

## 9. OAuth and Authorization Architecture

### 9.1 Authentication authority

Amazon Cognito User Pool is the authorization server and token issuer.

The current flow is:

```text
OAuth 2.0 Authorization Code Grant
+ PKCE
+ Cognito Managed Login
+ email one-time password
+ public app client without client secret
```

### 9.2 Protected resource discovery

The server exposes a public metadata endpoint:

```text
/.well-known/oauth-protected-resource/mcp
```

It tells the client:

```text
which protected resource it is accessing;
which authorization server protects it;
which OAuth scope is required.
```

### 9.3 Protected MCP endpoint

The MCP endpoint is:

```text
/mcp
```

Without a valid token, it returns:

```text
HTTP 401
WWW-Authenticate: Bearer
resource_metadata=<public metadata URL>
scope=<required invoke scope>
```

A valid token without the required scope returns `403 Forbidden`.

### 9.4 Authorization boundary

Authentication and scope validation occur before the MCP request is processed.

```text
HTTP request
→ token verification
→ scope verification
→ MCP transport
→ tool dispatch
```

Unauthenticated traffic must never reach GHOST tool execution.

---

## 10. Current Tool Architecture

### 10.1 Tool name

```text
ghost_engineer_prompt
```

### 10.2 Current purpose

```text
receive one user prompt;
create a fresh SuperPrompt;
run deterministic PreProcessing;
run A2 PromptShaper;
return the engineered prompt to the AI client.
```

### 10.3 Current processing path

```text
prompt_text
→ validate non-empty input
→ create fresh SuperPrompt
→ preprocess(...)
→ verify stage == preprocessed
→ A2 PromptShaper
→ verify stage == a2
→ read prompt_ready
→ construct MCP result
```

### 10.4 Current exclusions

The first tool does not currently run:

```text
document ingestion
project retrieval
memory retrieval
A3 usefulness/NLI gate
A4 condenser
memory recording
complete orchestration pipeline
final-answer generation inside GHOST
```

### 10.5 Current state boundary

The proven implementation baseline returned:

```json
{
  "engineered_prompt": "...",
  "stage": "a2"
}
```

A later conditional-mode revision added:

```json
{
  "mode": "show_prompt_only | answer_prompt"
}
```

That later revision still requires complete repository verification and retesting before it becomes the declared stable baseline.

---

## 11. Immediate Dynamic-Instruction Architecture

This is the immediate next implementation, not a distant future vision.

### 11.1 Problem

ChatGPT may retain the tool description, server instructions, and schemas discovered when the app is created.

Repeatedly changing static metadata can require deleting and recreating the registered GHOST app.

That is not an acceptable instruction-development loop.

### 11.2 Architectural solution

Use one permanent tool contract and return the exact client behavior instruction dynamically with every successful call.

Proposed stable result:

```json
{
  "engineered_prompt": "...",
  "stage": "a2",
  "mode": "show_prompt_only | answer_prompt",
  "response_instruction": "exact runtime instruction for the current call"
}
```

### 11.3 Stable fields

```text
engineered_prompt
  Final A2-generated prompt.

stage
  Current GHOST processing stage, initially "a2".

mode
  Deterministic behavior category selected by Python.

response_instruction
  Exact runtime instruction that tells the AI client how to use
  engineered_prompt for this call.
```

### 11.4 Mode selection

Only one explicit condition exists.

Input matching the following conceptual rule:

```text
optional leading whitespace
+ case-insensitive word Prompt
+ optional whitespace
+ colon
+ optional whitespace
```

selects:

```text
show_prompt_only
```

Equivalent parser:

```python
re.compile(r"^\s*prompt\s*:\s*", re.IGNORECASE)
```

The prefix is removed before GHOST processing.

All other valid inputs select:

```text
answer_prompt
```

### 11.5 `show_prompt_only`

Required client behavior:

```text
display engineered_prompt verbatim;
use exactly one fenced code block;
add no text before or after;
do not answer the prompt;
do not research;
do not call another tool.
```

### 11.6 `answer_prompt`

Required client behavior:

```text
treat engineered_prompt as the complete effective user request;
answer or execute it;
use other tools when the request requires them;
do not merely display the engineered prompt;
do not discuss the rewriting step unless asked.
```

### 11.7 Stability rule

After this change:

```text
tool name remains stable;
input schema remains stable;
output field names remain stable;
general tool description remains stable;
general server instructions remain stable;
mode-specific behavior is carried by response_instruction.
```

The effectiveness of this approach must be validated in the real ChatGPT client. It is the chosen architecture, but the degree to which the client obeys dynamic instructions remains an empirical client behavior.

---

## 12. Multi-Tool Extension Architecture

The MCP server is designed to expose multiple capabilities through the same endpoint.

Candidate inventory:

```text
ghost_engineer_prompt
ghost_tag_episode
ghost_recall_episode
ghost_github_retrieve
ghost_requirements_trace
ghost_architecture_check
ghost_ingest_document
ghost_project_retrieve
```

Each tool must define:

```text
stable tool name;
single clear responsibility;
input schema;
output schema;
read/write classification;
error contract;
required OAuth scope;
unit tests;
protocol contract tests;
real-client acceptance tests where client behavior matters.
```

Tool-specific code should remain separate from transport and authentication code.

---

## 13. Persistent Memory Extension

### 13.1 GHOST Tagger

Conceptual user command:

```text
GHOST_Tagger::<tag>::
```

Required flow:

```text
user issues tag command;
ChatGPT invokes ghost_tag_episode;
ChatGPT passes the immediately preceding user question and assistant answer;
GHOST validates the payload;
GHOST writes the episode to persistent storage;
GHOST returns a compact success result.
```

Important boundary:

```text
the MCP server does not automatically receive the entire ChatGPT conversation.
```

The client must explicitly provide the episode content in the tool arguments.

Practical write path:

```text
ChatGPT calls MCP tool
→ GHOST Python writes SQLite and JSON
```

### 13.2 GHOST Recall

Conceptual user command:

```text
GHOST_Recall::<tag>::<current prompt>
```

Required flow:

```text
ChatGPT invokes ghost_recall_episode;
GHOST retrieves the exact tagged episode;
GHOST attaches it as supporting context;
GHOST returns an enriched prompt or structured context result;
ChatGPT continues from that result.
```

### 13.3 Storage ownership

Candidate storage model:

```text
SQLite index
+ structured JSON episode payload
+ exact tag
+ timestamp
+ source-client metadata
+ optional content hash and stable episode ID
```

Exact overwrite, duplicate-tag, and versioning behavior remains a later design decision.

---

## 14. GitHub and External-System Integration

Two orchestration patterns are possible.

### 14.1 Client-side cross-tool orchestration

```text
User
→ ChatGPT
→ GHOST tool
→ GHOST returns an instruction requesting GitHub retrieval
→ ChatGPT invokes its GitHub connector
→ ChatGPT receives GitHub content
→ optionally sends the content back to GHOST
```

Properties:

```text
uses an existing client-side connector;
depends on ChatGPT choosing to follow the returned instruction;
depends on connector availability and user authorization;
is heuristic rather than deterministic.
```

An MCP tool cannot directly invoke another ChatGPT-side tool.

### 14.2 Direct GHOST integration

```text
User
→ ChatGPT
→ GHOST MCP tool
→ GHOST Python calls GitHub API directly
→ GHOST returns the retrieved result
```

Properties:

```text
deterministic server-side control;
independent of client-side connector orchestration;
requires GitHub authentication and API integration inside GHOST;
better suited to repeatable engineering workflows.
```

The direct GHOST integration is the more reliable architecture for requirements, architecture, code, and traceability workflows.

---

## 15. Read and Write Semantics

MCP tool annotations describe the behavior of the GHOST operation.

Examples:

```text
ghost_engineer_prompt
  read-only with respect to project persistence

ghost_recall_episode
  read-only

ghost_tag_episode
  write operation, non-destructive unless overwrite is allowed

ghost_ingest_document
  write operation

ghost_requirements_trace
  read-only when reporting
  write operation when modifying traceability artifacts
```

“ChatGPT writes SQLite” means, in practical architecture:

```text
ChatGPT triggers the MCP tool
→ GHOST Python performs the SQLite write
```

The AI client does not directly open the database file.

---

## 16. Error Architecture

Errors are divided by boundary.

### 16.1 HTTP and authentication errors

```text
401 Unauthorized
  token absent or invalid

403 Forbidden
  token valid but required scope missing

503 Service Unavailable
  authentication dependency temporarily unavailable
```

### 16.2 MCP contract errors

```text
unknown tool name
invalid arguments
unsupported operation
invalid internal result shape
```

### 16.3 GHOST execution errors

Internal exceptions must be logged server-side and returned to the client as sanitized failures.

The client must not receive:

```text
stack traces
secret values
token contents
internal file-system details
uncontrolled exception text
```

---

## 17. Concurrency and Execution Model

The network stack is asynchronous:

```text
Uvicorn
Starlette
MCP Streamable HTTP transport
```

Current GHOST preprocessing and A2 execution are synchronous.

Therefore, synchronous GHOST work is moved into a worker thread:

```text
async MCP request
→ anyio.to_thread.run_sync(...)
→ synchronous GHOST processing
→ async response
```

This prevents one synchronous prompt-engineering call from blocking the complete asynchronous server event loop.

Request isolation requires a fresh `SuperPrompt` per call.

---

## 18. Security Architecture

### 18.1 Current local security

```text
MCP server bound to 127.0.0.1;
local port not publicly reachable;
remote access only through Secure MCP Tunnel;
Cognito OAuth required before MCP processing;
required invoke scope enforced;
no client secret in the public OAuth client;
PKCE used for the authorization-code flow.
```

### 18.2 Secret handling

Secrets include:

```text
OpenAI tunnel control-plane key
OpenAI API key used by GHOST
temporary Cognito access and refresh tokens
future GitHub credentials
```

Secret values must not be stored in architecture or implementation reports.

### 18.3 Future AWS security

```text
MCP container publishes only to 127.0.0.1:8000 on EC2;
Security Group does not expose port 8000;
nginx terminates public HTTPS;
only intended public routes are proxied;
OAuth remains mandatory;
secrets are injected from AWS-managed storage;
rate limiting and production logging are enabled.
```

---

## 19. Testing Architecture

Testing is layered.

### 19.1 Unit tests

```text
prompt validation
mode selection
prefix removal
runtime instruction generation
token validation
scope validation
result-shape validation
error sanitization
```

### 19.2 MCP protocol tests

```text
initialize
tools/list
tools/call
unknown tool
invalid argument
structured output
text output
tool annotations
security metadata
```

### 19.3 OAuth contract tests

```text
public protected-resource metadata
401 Bearer challenge
resource_metadata URL
required scope
valid-token access
invalid-token rejection
missing-scope rejection
```

### 19.4 Real-client acceptance tests

```text
Cognito login through ChatGPT
email OTP
authenticated tool discovery
authenticated tool invocation
show_prompt_only behavior
answer_prompt behavior
runtime response_instruction behavior
cross-tool orchestration behavior where applicable
```

The last recorded stable automated baseline was:

```text
51 passed, 1 warning
```

That baseline predates the latest conditional-mode revision and must not be presented as validation of later changes.

---

## 20. Target AWS Deployment Architecture

The next deployment topology is:

```text
ChatGPT or Claude
→ public HTTPS
→ ragstream.rusbehabtahi.com
→ nginx on EC2
→ 127.0.0.1:8000
→ separate GHOST MCP Docker container
→ Cognito verification
→ MCP server
→ GHOST capabilities
```

Deployment decisions:

```text
same EC2 instance as the existing GHOST application;
separate MCP container;
separate systemd service;
container listens on port 8000;
host publication restricted to 127.0.0.1:8000;
no Security Group inbound rule for port 8000;
nginx proxies exact MCP and metadata paths;
OpenAI key loaded from AWS Systems Manager Parameter Store;
no unnecessary project, ChromaDB, or memory mounts for the first tool;
OpenAI Secure MCP Tunnel removed from the production path after validation.
```

The Streamlit application and MCP service remain separate deployable processes even when hosted on the same EC2 instance.

---

## 21. Architecture Decisions

### AD-01 — MCP is the external capability boundary

**Decision:** ChatGPT and Claude invoke GHOST through MCP rather than through Streamlit internals.

### AD-02 — One endpoint exposes multiple tools

**Decision:** New capabilities become tools under the same `/mcp` endpoint.

### AD-03 — OAuth is enforced before MCP processing

**Decision:** Cognito access-token and scope validation occur before the MCP transport handles the request.

### AD-04 — GHOST core logic is reused

**Decision:** MCP adapters call existing GHOST services and do not duplicate preprocessing or agent logic.

### AD-05 — Fresh state per prompt-engineering request

**Decision:** Each call creates a new `SuperPrompt`.

### AD-06 — ChatGPT remains the final responder

**Decision:** GHOST returns the engineered prompt rather than making a second final-answer model call.

### AD-07 — Dynamic instructions become part of the stable result contract

**Decision:** Mode-specific client instructions are returned at runtime in `response_instruction`.

### AD-08 — Persistent memory belongs to GHOST

**Decision:** Tagged episodes and cross-chat recall are stored in GHOST-controlled storage.

### AD-09 — Direct external API integration is preferred for deterministic workflows

**Decision:** Client-side cross-tool orchestration may be used, but direct GitHub integration inside GHOST is preferred for reliable engineering automation.

### AD-10 — Local tunnel and AWS deployment are separate transport variants

**Decision:** The same MCP application architecture runs behind either the Secure MCP Tunnel or nginx without changing GHOST tool logic.

---

## 22. Current Status Tree

```text
GHOST MCP
│
├── Implemented and proven
│   ├── local MCP server
│   ├── exact /mcp endpoint
│   ├── Cognito OAuth
│   ├── Authorization Code + PKCE
│   ├── email OTP login
│   ├── public protected-resource metadata
│   ├── Bearer challenge and scope enforcement
│   ├── OpenAI Secure MCP Tunnel
│   ├── real ChatGPT tool invocation
│   └── prompt-engineering path through PreProcessing and A2
│
├── Implemented or drafted but requiring final verification
│   └── conditional show_prompt_only / answer_prompt mode
│
├── Immediate next implementation
│   ├── permanent response_instruction field
│   ├── stable four-field output contract
│   ├── updated tests
│   ├── real-client validation
│   └── final local source-control checkpoint
│
├── Next deployment phase
│   ├── Docker image
│   ├── ECR
│   ├── EC2 container
│   ├── nginx
│   ├── public HTTPS
│   ├── rate limiting
│   └── production logging
│
└── Planned extensions
    ├── GHOST Tagger
    ├── GHOST Recall
    ├── GitHub retrieval
    ├── requirements tracing
    ├── architecture analysis
    ├── document ingestion
    └── project retrieval
```

---

## 23. Immediate Implementation Order

```text
1. Verify the actual repository state.
2. Implement the permanent response_instruction result field.
3. Keep the tool name and schema stable.
4. Update unit, MCP, and OAuth contract tests.
5. Run the complete test suite.
6. Validate both modes through ChatGPT.
7. Recreate the registered GHOST app one final time only if the permanent schema requires it.
8. Commit the stable local milestone.
9. Begin AWS deployment.
```

---

## 24. Related Documents

```text
doc/02-Architucture/MCP/
├── ArchitectureMCP.md
└── MCP_Conceptual_Request_Flow.md

doc/05-Design_Process/MCP/MCP_002/
├── MCP_Implementation_Report.md
├── MCP_Operations_Runbook.md
├── MCP_Next_Implementation.md
└── MCP_MultiTool_Vision.md
```

The architecture document defines the stable structure and decisions.

The implementation report records what happened.

The runbook records how to operate it.

The next-implementation plan defines the ordered near-term work.

The multi-tool vision records planned extensions without presenting them as implemented.
