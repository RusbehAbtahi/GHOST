# Requirements_Memory_Ingestion.md

Last update: 05.05.2026

## 1. Purpose and scope

This document defines the Memory Ingestion layer of RAGstream.

Memory Ingestion converts accepted `MemoryRecord` objects into searchable vector representations.

It is the bridge between:

- Memory Recording, which stores the full Q/A truth
- Memory Retrieval, which later searches and reconstructs relevant memory context

Memory Ingestion does not replace Memory Recording.

Memory Ingestion does not decide final retrieval ranking.

Memory Ingestion does not compress memory for prompt injection.

Memory Ingestion only prepares recorded memory for later retrieval.

---

## 2. Core principle

A `MemoryRecord` is the permanent memory truth.

The full original Q/A remains owned by Memory Recording:

- full user question / input
- full assistant answer / output
- tag
- YAKE keywords
- user keywords as a future-reserved metadata field
- project/session metadata
- hashes and source information

The vector layer is only a retrieval index.

No vector entry is allowed to become the source of truth.

No generated summary, compressed text, or reduced context may overwrite the original `MemoryRecord`.

---

## 3. Relation to Memory Recording

Memory Recording is responsible for:

- creating `MemoryRecord` objects
- storing full Q/A text
- appending `.ragmem`
- updating `.ragmeta.json`
- updating SQLite
- maintaining `MemoryManager.records`

Memory Ingestion starts only after Memory Recording succeeds.

Runtime sequence:

```text
accepted Q/A
→ MemoryManager.capture_pair(...)
→ MemoryRecord saved durably
→ MemoryIngestionManager ingests the record into memory vectors
````

During active operation, Memory Ingestion should work from the live `MemoryManager.records`.

The persisted files are used for startup, reload, synchronization, and recovery.

They should not be repeatedly reread during normal chatting when the live `MemoryManager` already holds the active records.

---

## 4. Scope

This document covers:

* memory vector ingestion
* memory-specific block creation
* record-handle, question-block, and answer-block vector roles
* memory vector-store separation from document vector stores
* metadata needed for filtering, debugging, and reconstruction
* asynchronous ingestion after durable MemoryRecord capture
* idempotent re-ingestion

This document does not cover:

* memory retrieval ranking
* MemoryContextPack reconstruction
* compression of retrieved memory
* final SuperPrompt memory-section rendering
* tag-governance behavior during retrieval
* advanced memory-management GUI

Those belong to separate retrieval, compression, and GUI requirements.

---

## 5. Design position

Memory Ingestion is a separate subsystem under `ragstream/memory/`.

It must not be implemented inside `MemoryManager`.

`MemoryManager` remains the owner of memory truth and persistence.

Memory Ingestion receives `MemoryManager` as a dependency and reads the already accepted records from it.

The intended separation is:

```text
MemoryManager
  = memory truth and persistence

MemoryIngestionManager
  = ingestion orchestration

MemoryChunker
  = deterministic/extractive memory block creation

MemoryVectorStore
  = memory vector persistence
```

This keeps Memory Recording clean and prevents `MemoryManager` from becoming responsible for chunking, embedding, or Chroma-specific behavior.

---

## 6. Required implementation modules

The Memory Ingestion layer shall add these main files:

```text
ragstream/memory/memory_ingestion_manager.py
ragstream/memory/memory_chunker.py
ragstream/memory/memory_vector_store.py
```

These files define the ingestion subsystem.

They should remain separate from the existing Memory Recording files:

```text
ragstream/memory/memory_manager.py
ragstream/memory/memory_record.py
ragstream/memory/memory_actions.py
```

---

## 7. MemoryIngestionManager

`MemoryIngestionManager` is the orchestration object for Memory Ingestion.

It is responsible for:

* receiving a `MemoryManager`
* selecting MemoryRecords for ingestion
* coordinating chunk creation
* coordinating vector-store writes
* supporting ingestion of one record or the currently loaded memory history
* supporting asynchronous ingestion after new MemoryRecord capture
* keeping ingestion independent from retrieval and compression

`MemoryIngestionManager` may expose methods such as:

```text
ingest_record(...)
ingest_all(...)
reingest_record(...)
ingest_record_async(...)
```

The exact method signatures are implementation details.

The required behavior is that ingestion can be triggered for one MemoryRecord or for all records currently loaded in `MemoryManager.records`.

---

## 8. MemoryChunker

`MemoryChunker` is responsible for converting a `MemoryRecord` into deterministic ingestion blocks.

It must produce three conceptual block types:

```text
record_handle
question
answer
```

The chunker must not invent content.

It must not call an LLM.

It must not generate a summary or inferred intent.

All text used for vectorization must be copied from the MemoryRecord itself or assembled deterministically from existing metadata.

---

## 9. MemoryVectorStore

`MemoryVectorStore` owns the dedicated memory vector store.

It is responsible for:

* connecting to the memory Chroma collection
* writing vector entries
* deleting/replacing vector entries for a MemoryRecord during re-ingestion
* keeping memory vectors separate from document vectors
* storing vector documents and metadata

It is not responsible for:

* owning MemoryRecord truth
* deciding retrieval ranking
* reconstructing MemoryContextPack
* compressing memory context

---

## 10. Memory vector storage domain

Memory vectors must be stored separately from document vectors.

Required logical storage domain:

```text
data/memory/vector_db/
```

Required conceptual collection:

```text
memory_vectors
```

Memory vectors must not be mixed into:

```text
data/chroma_db/<project>
```

Document retrieval and memory retrieval remain separate domains.

---

## 11. Vector representation model

For each `MemoryRecord`, Memory Ingestion creates three retrieval representations:

```text
MemoryRecord
  → record-handle vector
  → question-block vectors
  → answer-block vectors
```

These are stored in one dedicated memory vector store.

They are separated by metadata, not by three different databases.

Required role values:

```text
record_handle
question
answer
```

---

## 12. Record-handle vector

The record-handle vector is one compact deterministic representation of the MemoryRecord.

Its purpose is candidate discovery.

It answers:

```text
This MemoryRecord may be relevant.
```

The record-handle text shall be built from existing fields only:

* project name
* tag
* user keywords
* YAKE keywords
* copied question anchor from the original user question

No LLM-generated summary is allowed.

No LLM-generated intent is allowed.

No generated title is required.

The question anchor must be copied from the original `MemoryRecord.input_text`.

---

## 13. Question-block vectors

Question-block vectors are created from the original user question.

Source:

```text
MemoryRecord.input_text
```

Purpose:

```text
This current query resembles an old user problem.
```

The original question is split into meaningful blocks.

Each question block becomes its own vector entry.

The original text, block order, and parent MemoryRecord link must be preserved.

---

## 14. Answer-block vectors

Answer-block vectors are created from the original assistant answer.

Source:

```text
MemoryRecord.output_text
```

Purpose:

```text
This old answer contains useful knowledge for the current query.
```

The original answer is split into meaningful blocks.

Each answer block becomes its own vector entry.

The original text, block order, and parent MemoryRecord link must be preserved.

---

## 15. Chunking strategy

Memory chunking should be smarter than simple linear document chunking.

The accepted direction is sentence-based semantic chunking.

The chunker should split where the meaning changes, while still preserving original order and traceability.

The implementation may use a semantic chunking library through an adapter.

Accepted target direction:

```text
LlamaIndex SemanticSplitterNodeParser
```

The chunking process should follow this conceptual order:

```text
semantic split
→ max-size safety split if needed
→ assign role, block id, position, and offsets
```

Exact chunk-size constants are implementation configuration.

They should be centralized and not scattered across files.

---

## 16. Vector entry identity

Every memory vector entry must have its own unique vector-store ID.

The vector entry ID identifies the indexed block.

It is not the same as the parent `MemoryRecord.record_id`.

Each vector entry must also store the parent MemoryRecord ID in metadata.

Conceptual relation:

```text
vector entry id
  → identifies one stored vector block

record_id metadata
  → links that vector block back to the full MemoryRecord
```

This parent link is mandatory because retrieval results must later reconstruct memory context from the original MemoryRecord, not from isolated chunks alone.

---

## 17. Required metadata

Every memory vector entry must store metadata needed for:

* filtering
* debugging
* re-ingestion
* parent reconstruction
* tag-aware retrieval later

Required metadata categories:

```text
identity:
  file_id
  record_id
  parent_id

vector role:
  role
  block_id
  position

traceability:
  start_offset
  end_offset
  token_count

memory metadata:
  tag
  active_project_name
  source
  created_at_utc

integrity:
  input_hash
  output_hash
  ingestion_hash

keywords:
  YAKE keywords
  user keywords as a future-reserved metadata field
```

The exact encoding of list-like values is an implementation detail.

If the vector store only supports scalar metadata values, keyword lists may be stored in a deterministic text form.

---

## 18. Embedded text vs metadata

For every vector entry, there are two separate concerns:

1. embedded text
2. metadata

The embedded text is the actual text passed to the embedding model.

Examples:

```text
record-handle text
question block text
answer block text
```

Metadata is attached beside the vector entry.

Examples:

```text
record_id
role
tag
project
keywords
offsets
hashes
```

The record-handle embedded text shall use YAKE keywords and the copied question anchor.

Tag, project name, and user keywords shall remain metadata only.

Embedding supports semantic matching.

Metadata supports filtering, debugging, boosting, and parent reconstruction.

---

## 19. Embedding behavior

Memory Ingestion requires only normal embedding capability.

It does not require an LLM call.

It does not require compression.

The embedding model must be configurable.

Memory Ingestion should follow the existing project’s embedding infrastructure style where practical, but it remains a separate memory ingestion path.

---

## 20. Idempotency and re-ingestion

Memory Ingestion must be idempotent.

Re-ingesting the same MemoryRecord must not create duplicate vector entries.

The required behavior is:

```text
existing vectors for record_id are removed or replaced
→ current vector entries are written
```

This is necessary when:

* explicit re-ingestion is requested after metadata changes
* ingestion is retried
* chunking configuration changes
* the embedding model changes
* a memory history is reloaded and re-ingested

The exact delete/update mechanism belongs to implementation.

---

## 21. Ingestion hash

Memory vector entries should include an ingestion hash.

The ingestion hash should represent the inputs that affect vector content or metadata.

It may include:

* record identity
* input hash
* output hash
* YAKE keywords
* metadata fields that are intentionally mirrored into vector metadata
* chunking configuration version
* embedding model name

The purpose is:

* skip unchanged records later
* support reproducibility
* support debugging
* make re-ingestion behavior inspectable

The first implementation may still use delete-and-rebuild.

The hash is required as a governance and future-optimization field.

---

## 22. Asynchronous ingestion

Memory Recording must remain synchronous and durable.

Memory Ingestion should run asynchronously after the MemoryRecord has been safely stored.

Required rule:

```text
MemoryRecord is saved first.
Vector ingestion happens after that.
```

If vector ingestion fails, the MemoryRecord remains valid and durable.

Ingestion failure must not roll back Memory Recording.

Normal chatting should not wait for memory vector ingestion.

---

## 23. Integration with memory_actions.py

`memory_actions.py` remains the workflow boundary used by the GUI and later model/tool capture paths.

After successful `MemoryManager.capture_pair(...)`, it may trigger Memory Ingestion.

Conceptual flow:

```text
memory_actions.py
→ MemoryManager.capture_pair(...)
→ durable MemoryRecord saved
→ MemoryIngestionManager.ingest_record_async(...)
```

The exact wiring can be implemented in a way that stays compatible with Streamlit session state.

The important requirement is the ordering:

1. save memory truth
2. then ingest vector representation

---

## 24. Startup behavior

At application startup:

* `MemoryManager` initializes normally.
* Existing memory histories may be loaded into `MemoryManager.records`.
* `MemoryIngestionManager` may be initialized after `MemoryManager`.
* Memory vectors do not need to be rebuilt automatically unless explicitly requested or detected as missing.

Startup must not force expensive full re-ingestion by default.

---

## 25. Error handling

If Memory Ingestion fails:

* the MemoryRecord remains saved
* `.ragmem` remains valid
* `.ragmeta.json` remains valid
* SQLite remains valid
* the error is logged
* the record can be re-ingested later

Memory Ingestion errors must not corrupt Memory Recording state.

---

## 26. Non-functional requirements

### 26.1 Separation of concerns

Memory Recording, Memory Ingestion, Memory Retrieval, and Compression must remain separate layers.

### 26.2 Determinism

Memory Ingestion must be deterministic given:

* the same MemoryRecord
* the same vector-relevant metadata
* the same chunking configuration
* the same embedding model

### 26.3 Traceability

Every vector entry must be traceable back to:

* its MemoryRecord
* its role
* its original text span
* its tag and project context

### 26.4 Testability

The ingestion layer must be testable without running the full RAG pipeline.

At minimum, tests should be possible for:

* record-handle construction
* question/answer chunking
* metadata creation
* idempotent re-ingestion
* vector-store write/delete behavior

### 26.5 Extensibility

The design must allow later addition of:

* memory retrieval
* tag-governed retrieval rules
* memory context reconstruction
* compression
* advanced GUI controls

without changing the basic MemoryRecord truth model.

---

## 27. Acceptance criteria

Memory Ingestion is complete when:

1. A saved MemoryRecord can be ingested into the dedicated memory vector store.

2. Each MemoryRecord produces:

   * one record-handle vector
   * question-block vectors
   * answer-block vectors

3. All vector entries are stored in one memory vector collection.

4. Every vector entry has:

   * unique vector entry ID
   * parent `record_id`
   * role metadata
   * block metadata
   * tag/project metadata and future-reserved user-keyword metadata

5. Record-handle text is deterministic and extractive.

6. No LLM-generated summary or intent is created during ingestion.

7. No compression is performed during ingestion.

8. Re-ingesting a MemoryRecord does not create duplicate vectors.

9. Memory Recording remains independent and durable.

10. Ingestion can run after MemoryRecord capture without blocking normal interaction.

11. Document vector stores and memory vector stores remain separate.

12. The original full MemoryRecord remains the only memory truth.
