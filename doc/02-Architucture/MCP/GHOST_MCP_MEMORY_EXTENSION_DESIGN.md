# GHOST MCP Memory Extension — Implementation Design

**Date:** 2026-08-06  
**Repository baseline:** `RusbehAbtahi/GHOST`, `main`, commit `0de257dd0a1bf3106f14eb8b4ce78ae3a91a45f8` (`[deploy] Add GHOST MCP AWS deployment`)  
**Purpose:** fixed design for implementation after review; this document does not implement the change.

## 1. Fixed scope

The existing endpoint remains:

```text
https://ghost.rusbehabtahi.com/mcp
```

It shall expose exactly these three tools:

```text
ghost_engineer_prompt
ghost_memory_tag
ghost_memory_recall
```

`ghost_engineer_prompt` remains functionally unchanged, including its current `Prompt:`, normal-request, and `MEM:` behavior.

The new tools add deterministic cross-chat memory:

```text
ghost_memory_tag(recall_key, input_text, output_text)
    -> save the immediately preceding visible user/assistant pair

ghost_memory_recall(recall_key)
    -> return the exact stored pair selected by Direct Recall
```

The authenticated Cognito `sub` is the owner. It is obtained only from the verified access token and is never accepted as a tool argument.

## 2. Verified current implementation

| Current code | Verified fact | Design consequence |
|---|---|---|
| `ragstream/memory/memory_record.py` | `MemoryRecord` already creates `record_id`, UTC timestamp, hashes, stable `.ragmem` blocks, index dictionaries, and backward-compatible loading. | Reuse this class directly; do not copy its logic. |
| `ragstream/memory/memory_manager.py` | GUI capture owns one active history, creates Active Briefs, writes to a fixed `files/` root, writes `.ragmeta.json`, and mirrors metadata to SQLite. | Do not call `capture_pair()` and do not modify the GUI workflow. Add an MCP-specific store. |
| `ragstream/memory/retrieval/memory_index_lookup.py` | `get_direct_recall()` already performs exact SQLite key matching across histories, excludes configured tags, prefers Gold then Green, then newest, and loads the exact Q/A body from `.ragmem`. | Reuse this lookup with one optional authenticated-owner scope. Do not invent a second recall algorithm. |
| `ragstream/mcp/auth.py` | A verified `Principal.subject` already contains the Cognito `sub`. | Pass this value explicitly into memory tool execution. No email, hash, or additional owner ID. |
| `ragstream/mcp/server.py` | The authenticated subject is already available in the request handler through `_AUTHENTICATED_SUBJECT`; synchronous tools run through `anyio.to_thread.run_sync`. | Pass the subject into the application call and protect file writes against concurrent worker threads. |
| `ragstream/mcp/server.py` | The module is already exactly 600 lines. | Move the existing `GhostMcpApplication` responsibility into a focused module before adding multi-tool routing; otherwise the mandatory code-size rule would be violated. |
| `Dockerfile.mcp` | The MCP image contains the project but the running MCP container currently has no persistent data mount. | Add a narrow persistent bind mount for `/app/data/mcp`. |
| `requirements.txt` | `mcp`, `PyJWT`, `yake`, `chromadb`, and all memory dependencies already exist. | No new Python dependency is required. |

The supplied MCP requirements/UML still describe the completed first one-tool phase. They are historical/stale relative to the deployed code and must be updated for this extension; they are not a prohibition against the new tools.

## 3. Persistent data layout

The fixed MCP data root is:

```text
data/mcp/memory/
├── files/
│   └── <cognito-sub>/
│       ├── MCP_MEM_2026-08-06.ragmem
│       └── MCP_MEM_2026-08-06.ragmeta.json
├── vector_db/
└── memory_index.sqlite3
```

Rules:

1. Use the Cognito `sub` directly as the directory name. Do not create an owner hash or another owner ID.
2. Validate that `sub` is one safe path component before using it. Accept letters, numbers, `.`, `_`, and `-`; reject separators, empty values, `.` and `..`. The value itself is not transformed.
3. Create one paired `.ragmem`/`.ragmeta.json` file per authenticated user per **UTC day**. UTC matches `MemoryRecord.created_at_utc` and avoids server-local timezone ambiguity.
4. Use one shared MCP SQLite database. Ownership is enforced in every MCP recall query.
5. Create `vector_db/` for structural compatibility, but do not create embeddings or a Chroma collection in this implementation. Exact Direct Recall does not use vectors.
6. Runtime memory data remains ignored by Git and outside the Docker image.

## 4. Compatible `MemoryRecord` values

`ghost_memory_tag` creates the standard current `MemoryRecord` with these values:

| Field | MCP value |
|---|---|
| `input_text` | Immediately preceding visible user message, copied verbatim |
| `output_text` | Immediately preceding visible assistant response, copied verbatim |
| `source` | `mcp` |
| `parent_id` | `None` |
| `tag` | `Green` — this is displayed in the GUI as **Standard** |
| `retrieval_source_mode` | `QA` |
| `direct_recall_key` | Supplied key, trimmed |
| `user_keywords` | `[]` |
| `active_project_name` | `None` |
| `embedded_files_snapshot` | `[]` |
| `active_retrieval_brief_title` | empty string |
| `active_retrieval_brief` | empty string |
| `active_retrieval_brief_contributor_ids` | `[]` |
| `auto_keywords` | Use the existing `MemoryRecord` default generation; do not replace it with copied code |
| IDs, timestamps, hashes | Generated by the existing `MemoryRecord` implementation |

This preserves future compatibility: the stable Active Brief fields already exist in every MCP `.ragmem` block and are simply empty for this version.

## 5. File formats

### 5.1 `.ragmem`

Write the block returned by:

```python
record.to_ragmem_block()
```

The format and stable fields remain identical to ordinary GHOST memory:

```text
record_id
parent_id
created_at_utc
input_text
output_text
source
input_hash
output_hash
active_retrieval_brief_title
active_retrieval_brief
active_retrieval_brief_contributor_ids
```

Do not add `owner_sub`, `recall_key`, tags, paths, or vectors to `.ragmem`.

### 5.2 `.ragmeta.json`

Keep the existing metadata structure and per-record values from:

```python
record.to_index_dict()
```

The only MCP-specific file-level field is:

```json
"owner_sub": "<verified Cognito sub>"
```

The paired filename fields shall contain paths relative to `data/mcp/memory/files/`, for example:

```json
"filename_ragmem": "<sub>/MCP_MEM_2026-08-06.ragmem",
"filename_meta": "<sub>/MCP_MEM_2026-08-06.ragmeta.json"
```

This lets the existing `MemoryIndexLookup` resolve the nested file through:

```text
memory_root / files / filename_ragmem
```

If a recall key is editable in a later version, update `.ragmeta.json` and SQLite only. The stable `.ragmem` body remains unchanged.

### 5.3 SQLite

Use the existing table names and existing record schema:

```text
memory_files
memory_records
```

Keep `memory_records` structurally identical. Add only this file-level ownership column in the MCP database:

```sql
memory_files.owner_sub TEXT NOT NULL
```

Owner is a property of the daily file, so it does not need to be duplicated into every record row.

Keep the existing primary keys and indexes, and add an index on:

```sql
memory_files(owner_sub)
```

The owner-scoped Direct Recall query is the existing exact lookup with a file-owner join:

```sql
SELECT mr.*
FROM memory_records AS mr
JOIN memory_files AS mf ON mf.file_id = mr.file_id
WHERE mf.owner_sub = ?
  AND mr.direct_recall_key = ?
```

Then preserve the current exclusion and ordering logic:

```text
exclude Black
prefer Gold
then Green
then other tags
then newest created_at_utc
LIMIT 1
```

Therefore duplicate keys are allowed exactly as in current GHOST Direct Recall. For MCP records, which are Green by default, the newest exact match for that user is returned. Do not add a unique constraint or a new duplicate-key policy.

## 6. New storage class

Create:

```text
ragstream/memory/mcp_memory_store.py
```

Primary class:

```text
McpMemoryStore
├── tag_memory(owner_sub, recall_key, input_text, output_text)
└── recall_memory(owner_sub, recall_key)
```

It shall call existing `MemoryRecord` public behavior:

```text
MemoryRecord(...)
MemoryRecord.to_ragmem_block()
MemoryRecord.to_index_dict()
MemoryRecord.from_dict()
MemoryRecord.update_metadata_overlay()
```

It owns only MCP-specific persistence:

- daily path selection;
- owner-path validation;
- loading the daily file and metadata;
- appending the new block;
- rebuilding compatible `.ragmeta.json`;
- initializing/updating the MCP SQLite mirror;
- calling owner-scoped Direct Recall.

Do not subclass `MemoryManager`, copy `MemoryRecord` algorithms, add a repository layer, add a generic storage adapter, or modify the GUI `MemoryManager` workflow.

### Write sequence

Under one store-wide `threading.Lock` shared by both tag and recall operations:

1. Resolve the authenticated user's UTC daily paths.
2. Load existing valid blocks through `MemoryRecord.from_dict()` when the daily file exists.
3. Overlay current metadata through `update_metadata_overlay()`.
4. Verify that an existing metadata file has the same `owner_sub` as the authenticated request.
5. Create the new `MemoryRecord` with the fixed defaults.
6. Append `to_ragmem_block()` to the daily `.ragmem` file.
7. Rewrite the paired compatible `.ragmeta.json` including file-level `owner_sub`.
8. In one SQLite transaction, upsert the file row and record rows and remove stale mirror rows for that `file_id`.
9. Return the saved record result.

The single lock is sufficient for the current deployment because Uvicorn runs one process and tool calls use worker threads. Do not add distributed locks or a new locking dependency. Multi-process/multi-instance storage coordination belongs to a later scaling requirement.

### Recall sequence

1. Validate and trim `recall_key`.
2. Call the existing `MemoryIndexLookup.get_direct_recall()` with the MCP SQLite path, MCP memory root, and authenticated `owner_sub`.
3. Let the lookup resolve `file_id`, `record_id`, relative filename, and exact `.ragmem` body.
4. Return the original `input_text` and `output_text` without rewriting or summarizing them.

No Chroma, embedding, LLM, Active Brief builder, retrieval scorer, compressor, merger, or SuperPrompt is involved.

## 7. MCP tool contracts

### 7.1 `ghost_memory_tag`

Input schema:

```json
{
  "type": "object",
  "properties": {
    "recall_key": {"type": "string", "minLength": 1},
    "input_text": {"type": "string", "minLength": 1},
    "output_text": {"type": "string", "minLength": 1}
  },
  "required": ["recall_key", "input_text", "output_text"],
  "additionalProperties": false
}
```

The tool description and server instructions must tell the client:

- the user normally supplies only the recall key;
- `input_text` is the visible user message immediately before the assistant response being tagged;
- `output_text` is that complete immediately preceding visible assistant response;
- both texts must be copied verbatim from the same conversation;
- hidden reasoning, internal tool results, earlier episodes, and summaries are forbidden substitutes.

The MCP server cannot inspect the native client conversation by itself. It can validate that both strings are present, but the client model is responsible for supplying the correct preceding visible pair according to these instructions.

Success structured result:

```json
{
  "saved": true,
  "recall_key": "XYZ",
  "record_id": "<MemoryRecord record_id>",
  "created_at_utc": "<UTC timestamp>"
}
```

Annotations:

```text
readOnlyHint = false
destructiveHint = false
idempotentHint = false
openWorldHint = false
```

### 7.2 `ghost_memory_recall`

Input schema:

```json
{
  "type": "object",
  "properties": {
    "recall_key": {"type": "string", "minLength": 1}
  },
  "required": ["recall_key"],
  "additionalProperties": false
}
```

Success structured result:

```json
{
  "recall_key": "XYZ",
  "record_id": "<MemoryRecord record_id>",
  "created_at_utc": "<UTC timestamp>",
  "input_text": "<original input>",
  "output_text": "<original output>"
}
```

The text result shall deterministically contain both the recalled input and output. It shall not expose `owner_sub`, `file_id`, filesystem paths, SQLite details, or internal metadata.

Annotations:

```text
readOnlyHint = true
destructiveHint = false
idempotentHint = true
openWorldHint = false
```

### 7.3 Shared security and errors

- All three tools use the existing OAuth security scheme and the existing scope `https://ghost.rusbehabtahi.com/mcp/invoke`.
- Do not create additional Cognito scopes or app clients.
- Apply the existing per-subject rate limiter across all three tool calls, not only `ghost_engineer_prompt`.
- Invalid inputs return sanitized MCP tool errors.
- A missing recall key match returns a sanitized `isError=true` result stating that no memory was found.
- File, JSON, or SQLite failures return a generic memory-save or memory-recall failure; do not disclose paths, tokens, `sub`, stored content, or stack traces.

## 8. Production files

### Create

| File | Responsibility |
|---|---|
| `ragstream/memory/mcp_memory_store.py` | Daily per-user memory persistence and exact owner-scoped recall |
| `ragstream/mcp/ghost_memory_tools.py` | Input/output schemas, metadata, validation, and execution for the two memory tools |
| `ragstream/mcp/application.py` | Move the existing `GhostMcpApplication` here and extend it with explicit three-tool discovery, dispatch, and result validation |

`ghost_memory_tools.py` shall have one primary `GhostMemoryTools` class with two real operations: tag and recall. Do not create one class hierarchy or registry per tool.

### Modify

| File | Required change |
|---|---|
| `ragstream/mcp/server.py` | Import the extracted application, pass authenticated `sub` explicitly, rate-limit all known tools, make result logging tool-neutral, and bump the server version |
| `ragstream/memory/retrieval/memory_index_lookup.py` | Add optional `owner_sub` to `get_direct_recall()` and apply the owner join only when supplied; existing normal-memory callers remain unchanged |
| `ragstream/mcp/__init__.py` | Export the current public MCP modules consistently |
| `.dockerignore` | Add `data/mcp/` so local memory can never be copied into an MCP image build context |
| `tests/mcp/test_mcp_server.py` | Change exact inventory from one to three and verify dispatch, subject propagation, results, errors, and rate limiting |
| `tests/mcp/test_mcp_oauth_contract.py` | Verify all three discovered tools use the same OAuth scope and authenticated calls remain protected |
| `tests/mcp/test_mcp_prompt_engineering.py` | Preserve prompt-tool tests while changing application inventory expectations to three tools |
| `tests/mcp/live_mcp_client.py` | Expect three tools and support live tag/recall acceptance |

### Do not modify for this implementation

```text
ragstream/memory/memory_record.py
ragstream/memory/memory_manager.py
ragstream/memory/ingestion/*
ragstream/mcp/auth.py
ragstream/mcp/prompt_engineering_runner.py
Dockerfile.mcp
requirements.txt
nginx route
Route53
Cognito user pool, app client, resource, or scope
ghost_engineer_prompt public contract and behavior
```

## 9. New tests

Create:

```text
tests/memory/test_mcp_memory_store.py
tests/mcp/test_ghost_memory_tools.py
```

Required test cases:

1. First tag creates the correct `files/<sub>/MCP_MEM_<UTC-date>` pair and SQLite database.
2. A second tag for the same user/day appends a second record to the same `.ragmem` file.
3. Another `sub` writes to a different directory but the same MCP SQLite database.
4. `.ragmem` fields are identical to current stable-body format and contain no owner or recall key.
5. `.ragmeta.json` keeps the current format plus one file-level `owner_sub`.
6. Standard is stored internally as `Green`; project and Active Brief defaults are empty.
7. Exact recall returns the original Unicode/Markdown input and output unchanged.
8. The same key under two different `sub` values never crosses owners.
9. Duplicate keys for one owner preserve current Direct Recall priority/recency behavior.
10. A new UTC day creates a new daily pair.
11. Simultaneous tag calls do not lose a record or corrupt JSON/SQLite.
12. Missing key, malformed arguments, unsafe subject, corrupt/mismatched owner metadata, and I/O failures are sanitized.
13. `owner_sub` supplied as a public tool argument is rejected.
14. `vector_db/` is not populated by tag or recall.
15. All existing prompt-engineering, OAuth, transport, and rate-limit tests continue to pass.

Relevant verification command after implementation:

```text
pytest tests/memory/test_mcp_memory_store.py tests/mcp
```

Then run the existing local Docker test and public OAuth client acceptance.

## 10. AWS persistence change

The EC2 startup script `/usr/local/bin/ragstream-start` is an installed deployment artifact, not currently a repository source file. Its MCP `docker run` command must add the narrow bind mount:

```text
host:      ${HOST_DATA_ROOT}/mcp
container: /app/data/mcp
```

Before starting/replacing the MCP container:

```text
create ${HOST_DATA_ROOT}/mcp if absent
```

Do not mount the whole normal GHOST `data/memory` tree into the MCP container. The MCP container needs only its own `data/mcp` subtree.

Acceptance must prove:

1. tag one memory through the public authenticated endpoint;
2. replace/restart the `ghost-mcp` container;
3. recall the same key successfully afterward;
4. stop/start EC2 and recall it again;
5. verify another Cognito user cannot recall it;
6. verify the root Streamlit application remains unchanged.

No nginx, DNS, TLS, Security Group, ECR repository, or Cognito change is required.

## 11. Requirement and UML synchronization

Update before or together with implementation:

| Document | Required synchronization |
|---|---|
| `doc/01-Requirements/strictdoc/73_mcp_interface.sdoc` | Keep `ghost_engineer_prompt` unchanged; activate the separately approved tag/recall contracts, three-tool inventory, previous-pair input, owner isolation, outputs, errors, and real-client acceptance |
| `doc/01-Requirements/strictdoc/51_memory_recording_and_files.sdoc` | Add the MCP storage profile: `data/mcp/memory`, daily per-sub files, compatible formats, file-level owner field, and separate SQLite mirror |
| `doc/01-Requirements/strictdoc/52_memory_ingestion_and_retrieval.sdoc` | Preserve Direct Recall semantics and specify the optional authenticated-owner scope for MCP calls |
| `doc/01-Requirements/strictdoc/80_runtime_platform_and_operations.sdoc` | Treat the deployed MCP base as current and add the MCP memory persistence boundary |
| `doc/01-Requirements/strictdoc/81_aws_deployment_and_operations.sdoc` | Replace the historical one-tool/no-memory-mount acceptance with the current three-tool inventory and narrow `/app/data/mcp` persistence mount; use the current `ghost.rusbehabtahi.com` domain |
| `doc/02-Architucture/MCP/UML_MCP_Python_Implementation.txt` | Show `application.py`, two memory tools, `McpMemoryStore`, Cognito-sub flow, SQLite/JSON/ragmem, and the now-active auth/rate-limit connections |

The old one-tool statements should be retained only as the completed v1 scope or rewritten as statements specifically about `ghost_engineer_prompt`. They must not remain contradictory active acceptance criteria for the new version.

## 12. Implementation order

1. Synchronize the MCP/memory requirements and UML.
2. Add `McpMemoryStore` and its tests.
3. Extend owner-scoped Direct Recall and test normal-caller non-regression.
4. Add the two MCP memory tool contracts and tests.
5. Extract/extend `GhostMcpApplication`; update the server and existing MCP tests.
6. Add `data/mcp/` to `.dockerignore`.
7. Run Python tests and local Docker acceptance with a temporary bind mount.
8. Deploy the MCP image.
9. Update the EC2 startup script with the persistent mount and recreate `ghost-mcp` once.
10. Refresh/reconnect the GHOST_AWS plugin so ChatGPT retrieves the three-tool inventory and new schemas.
11. Run public tag, container-replacement, recall, cross-user isolation, EC2 restart, and Streamlit non-regression acceptance.

## 13. Explicit exclusions

This implementation does not add:

- email-based ownership;
- owner hashes or helper IDs;
- a new authentication system or OAuth scope;
- semantic memory search;
- vector ingestion;
- Active Brief generation;
- memory merging or synthesis;
- a GUI for MCP memory;
- recall-key editing or deletion tools;
- a generic repository, adapter, plugin, registry, factory, or distributed-lock layer;
- changes to normal `data/memory/` behavior.

## 14. Final design decision

There is no blocking hole requiring clarification before implementation.

The simplest compatible design is:

```text
verified Cognito sub
    + exact recall_key
    + existing MemoryRecord format
    + one UTC daily file per user
    + existing Direct Recall selection
    + separate data/mcp/memory persistence
```

This meets the requested cross-chat memory behavior without changing the normal GHOST memory workflow or adding unnecessary architecture.
