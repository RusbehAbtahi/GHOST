
# Architecture_Memory.md

Last sync: 30.04.2026

## 1. Purpose

This document describes the architecture of the RAGstream Memory subsystem.

It explains how Memory Recording, Memory Ingestion, Memory Retrieval, and Memory Compression belong together, which files are responsible for each layer, where their data is stored, and how the layers are wired.

This document is architectural, not low-level implementation detail.

Detailed behavior belongs to the requirement files.
Detailed structure belongs to the UML diagrams.
This document explains the current subsystem shape and wiring.

---

## 2. High-level memory architecture

```text
User / GUI
   │
   │ accepted prompt + accepted response
   ▼
┌──────────────────────────────┐
│      Memory Recording        │
│──────────────────────────────│
│ MemoryManager                │
│ MemoryRecord                 │
│ memory_actions.py            │
└───────────────┬──────────────┘
                │ creates durable truth
                ▼
┌──────────────────────────────┐
│ data/memory/                 │
│──────────────────────────────│
│ memory_index.sqlite3         │
│ files/*.ragmem               │
│ files/*.ragmeta.json         │
└───────────────┬──────────────┘
                │ after durable save
                ▼
┌──────────────────────────────┐
│      Memory Ingestion        │
│──────────────────────────────│
│ MemoryIngestionManager       │
│ MemoryChunker                │
│ MemoryVectorStore            │
└───────────────┬──────────────┘
                │ creates searchable vectors
                ▼
┌──────────────────────────────┐
│ data/memory/vector_db/       │
│──────────────────────────────│
│ Chroma collection:           │
│ memory_vectors               │
└───────────────┬──────────────┘
                │ later queried by
                ▼
┌──────────────────────────────┐
│      Memory Retrieval        │
│──────────────────────────────│
│ search record_handle vectors │
│ search question vectors      │
│ search answer vectors        │
│ reconstruct parent Q/A pack  │
└───────────────┬──────────────┘
                │ if too large
                ▼
┌──────────────────────────────┐
│      Memory Compression      │
│──────────────────────────────│
│ deterministic preselection   │
│ optional cheap LLM reduction │
│ runtime MemoryContextPack    │
└───────────────┬──────────────┘
                │ injected into
                ▼
┌──────────────────────────────┐
│        SuperPrompt           │
│──────────────────────────────│
│ dedicated memory section     │
│ separate from document RAG   │
└──────────────────────────────┘
````

---

## 3. Architectural layers

## 3.1 Memory Recording

Memory Recording is the truth-capture layer.

It accepts a user question and an accepted assistant/tool/model answer, creates a `MemoryRecord`, stores it in the active `MemoryManager`, and persists it to disk.

Main files:

```text
ragstream/memory/memory_record.py
ragstream/memory/memory_manager.py
ragstream/memory/memory_actions.py
```

Main objects:

```text
MemoryRecord
MemoryManager
```

Main responsibility:

```text
accepted Q/A → durable MemoryRecord truth
```

Memory Recording creates and maintains:

```text
data/memory/memory_index.sqlite3
data/memory/files/*.ragmem
data/memory/files/*.ragmeta.json
```

Memory Recording does not create vectors.
Memory Recording does not perform semantic retrieval.
Memory Recording does not compress memory.

---

## 3.2 Memory Ingestion

Memory Ingestion is the vector-preparation layer.

It reads already accepted `MemoryRecord` objects from the live `MemoryManager.records` list and creates searchable vector entries.

Main files:

```text
ragstream/memory/memory_ingestion_manager.py
ragstream/memory/memory_chunker.py
ragstream/memory/memory_vector_store.py
```

Main objects:

```text
MemoryIngestionManager
MemoryChunker
MemoryVectorStore
```

Main responsibility:

```text
MemoryRecord → record_handle vectors + question vectors + answer vectors
```

Memory Ingestion creates and maintains:

```text
data/memory/vector_db/
```

Conceptual Chroma collection:

```text
memory_vectors
```

Memory Ingestion does not change the original MemoryRecord.
Memory Ingestion does not summarize memory.
Memory Ingestion does not decide final retrieval ranking.
Memory Ingestion does not compress memory.

---

## 3.3 Memory Retrieval

Memory Retrieval is the later search and reconstruction layer.

It searches the dedicated memory vector store and reconstructs useful memory context from parent MemoryRecords.

Planned conceptual behavior:

```text
current user query
→ search record_handle vectors
→ search question-block vectors
→ search answer-block vectors
→ group hits by parent MemoryRecord
→ reconstruct reduced Q/A-shaped memory context
```

Memory Retrieval must not treat retrieved memory blocks as unrelated chunks.

It must always be able to trace a vector hit back to the full parent `MemoryRecord`.

Output of Memory Retrieval:

```text
MemoryContextPack
```

Memory Retrieval is separate from document retrieval.

Document retrieval uses:

```text
data/chroma_db/<project>
data/splade_db/<project>
```

Memory retrieval uses:

```text
data/memory/vector_db/
```

---

## 3.4 Memory Compression

Memory Compression is the runtime reduction layer.

It is used only when retrieved memory context is too large for direct SuperPrompt injection.

Conceptual behavior:

```text
large retrieved Q/A memory context
→ deterministic block/window preselection
→ optional cheap LLM compression
→ compact MemoryContextPack
```

Compression output is query-dependent.

Compression output is not memory truth.

Compression must never overwrite:

```text
MemoryRecord.input_text
MemoryRecord.output_text
.ragmem
.ragmeta.json
SQLite memory index
```

---

## 4. Runtime wiring

## 4.1 Normal capture flow

```text
GUI / future LLM call / future tool call
   │
   ▼
memory_actions.py
   │
   ▼
MemoryManager.capture_pair(...)
   │
   ▼
MemoryRecord saved in MemoryManager.records
   │
   ▼
.ragmem / .ragmeta.json / SQLite updated
   │
   ▼
MemoryIngestionManager.ingest_record_async(...)
   │
   ▼
memory_vectors updated in data/memory/vector_db/
```

Important rule:

```text
Memory truth is saved first.
Vector ingestion happens after durable save.
```

If vector ingestion fails, the MemoryRecord remains valid.

---

## 4.2 Startup / reload flow

```text
application start or selected memory history load
   │
   ▼
MemoryManager loads persisted memory history
   │
   ▼
MemoryManager.records rebuilt
   │
   ▼
MemoryIngestionManager can ingest missing/outdated vectors if requested
```

During normal operation, the active truth is:

```text
MemoryManager.records
```

The persisted files remain the recovery and durability layer.

---

## 5. Data layout

Final memory data layout:

```text
data/memory/
├── memory_index.sqlite3
├── files/
│   ├── <memory-history-1>.ragmem
│   ├── <memory-history-1>.ragmeta.json
│   ├── <memory-history-2>.ragmem
│   └── <memory-history-2>.ragmeta.json
└── vector_db/
    └── memory_vectors
```

Meaning:

```text
memory_index.sqlite3
  = searchable/indexed metadata for memory histories and records

files/*.ragmem
  = durable full Q/A memory truth

files/*.ragmeta.json
  = sidecar metadata rebuilt from MemoryManager.records

vector_db/memory_vectors
  = Chroma-based semantic retrieval index for MemoryRecords
```

---

## 6. Main Python files

## 6.1 Existing Memory Recording files

```text
ragstream/memory/memory_record.py
```

Defines one accepted Q/A memory unit.

```text
ragstream/memory/memory_manager.py
```

Owns the active memory history, live MemoryRecord list, and persistence synchronization.

```text
ragstream/memory/memory_actions.py
```

Provides workflow-level capture functions used by GUI and later model/tool capture paths.

---

## 6.2 New Memory Ingestion files

```text
ragstream/memory/memory_ingestion_manager.py
```

Coordinates memory ingestion from `MemoryManager.records` into the memory vector store.

```text
ragstream/memory/memory_chunker.py
```

Creates deterministic/extractive memory vector entries:

```text
record_handle
question
answer
```

```text
ragstream/memory/memory_vector_store.py
```

Owns the dedicated memory Chroma collection and writes/replaces vector entries.

---

## 7. Main object responsibilities

## 7.1 MemoryManager

Owns:

```text
file_id
records: list[MemoryRecord]
memory file names
memory metadata
memory persistence
```

Does not own:

```text
vector ingestion
retrieval ranking
compression
SuperPrompt injection
```

---

## 7.2 MemoryRecord

Owns one accepted memory unit:

```text
input_text
output_text
tag
YAKE keywords
user keywords
project snapshot
hashes
record_id
parent_id
```

It is the source object for ingestion.

---

## 7.3 MemoryIngestionManager

Owns ingestion orchestration.

Conceptual methods:

```text
ingest_record(record_id)
ingest_all()
ingest_record_async(record_id)
```

It reads `MemoryManager.records`, asks `MemoryChunker` to build vector entries, and asks `MemoryVectorStore` to write them.

---

## 7.4 MemoryChunker

Owns deterministic block creation.

It creates:

```text
one record_handle entry
question block entries
answer block entries
```

It does not call an LLM.
It does not invent intent.
It does not summarize the answer.

---

## 7.5 MemoryVectorStore

Owns memory vector persistence.

It writes to:

```text
data/memory/vector_db/
```

It keeps all memory vectors in one memory collection, separated by metadata role:

```text
record_handle
question
answer
```

---

## 8. Vector entry model

Each vector entry has:

```text
id
document
embedding
metadata
```

The vector entry ID identifies the indexed block.

The metadata links the vector entry back to the parent MemoryRecord.

Required conceptual metadata:

```text
file_id
record_id
parent_id
role
block_id
position
start_offset
end_offset
tag
active_project_name
source
input_hash
output_hash
ingestion_hash
YAKE keywords
user keywords
```

Important distinction:

```text
document
  = text that is embedded

metadata
  = fields used for filtering, tracing, debugging, and reconstruction
```

---

## 9. Boundaries

Memory Recording is allowed to write:

```text
.ragmem
.ragmeta.json
memory_index.sqlite3
MemoryManager.records
```

Memory Ingestion is allowed to write:

```text
data/memory/vector_db/
```

Memory Retrieval is allowed to read:

```text
MemoryManager.records
data/memory/vector_db/
```

Memory Compression is allowed to create:

```text
runtime MemoryContextPack
```

Memory Compression is not allowed to overwrite permanent memory truth.

---

## 10. Current status

Current implemented state:

```text
Memory Recording exists.
MemoryManager exists.
MemoryRecord exists.
memory_actions.py exists.
GUI manual memory feed exists.
.ragmem / .ragmeta.json / SQLite persistence exists.
```

Current design target:

```text
Memory Ingestion is next.
```

Planned later:

```text
Memory Retrieval
Memory Compression
SuperPrompt memory-section injection
Advanced memory GUI
```

---

## 11. Architectural invariants

The Memory subsystem follows these invariants:

1. Full Q/A memory truth is never replaced by vectors.

2. Memory vectors are retrieval aids only.

3. Memory Recording and Memory Ingestion remain separate.

4. Memory vectors are not stored in document ChromaDBs.

5. Every vector entry links back to its parent MemoryRecord.

6. Ingestion may run asynchronously after durable save.

7. Compression is runtime-only and query-dependent.

8. Memory context must remain separate from document retrieved context in the SuperPrompt.

9. Retrieval and compression may evolve later without changing the MemoryRecord truth model.

---

## 12. Short summary

```text
Memory Recording
  stores the truth.

Memory Ingestion
  makes the truth searchable.

Memory Retrieval
  finds relevant memory records.

Memory Compression
  reduces retrieved memory for the current query.

MemoryContextPack
  is runtime context for the SuperPrompt.

MemoryRecord
  remains the permanent source of truth.
```

