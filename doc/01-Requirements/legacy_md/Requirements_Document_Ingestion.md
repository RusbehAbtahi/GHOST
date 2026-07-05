# Requirements_Ingestion_Memory.md

Last update: 14.04.2026

Note for future maintenance:
- When new implementation-aligned decisions or features are added here, they should be date-stamped inline so the chronology stays visible.

1. Scope and Goals

---

1. This document specifies how RAGstream ingests and stores:

   * Static project documents (requirements, UML, code snippets, notes, etc.).
   * Conversation history (future phase): Q/A pairs, tags, and session metadata.

2. It covers:

   * Directory layout under `data/` for documents and history.
   * The ingestion pipeline for documents (already implemented).
   * The planned ingestion pipeline for conversation history (to be implemented).
   * Shared concepts (chunking, embeddings, vector stores).
   * Invariants and policies (IDs, durability, deletion rules).

3. It does **not** define:

   * Retrieval ranking logic (see Requirements_RAG_Pipeline.md).
   * Agent behavior (see Requirements_AgentStack.md).
   * GUI behavior (see Requirements_GUI.md).

4. Design principles:

   * One clear, stable pipeline: `source text → canonical chunks → dense embeddings + sparse representations → persistent stores`.
   * Stateless ingestion runs (no hidden global state).
   * Deterministic IDs and metadata so retrieval and logs line up.
   * Durability: all state on disk (no transient-only memory).
   * No deletions of user history without explicit user control.

---

2. Directory Layout and Data Domains

---

2.1 Root layout

1. Project root (Linux/WSL):

   * `/home/rusbeh_ab/project/RAGstream` (referred to as `ROOT`).

2. Under `ROOT/data/` the following logical domains exist:

   * `doc_raw/` – raw project documents (static).
   * `chroma_db/` – dense vector stores for documents (static embeddings).
   * `splade_db/` – sparse document stores for SPLADE term-weight representations.
   * `history/` – conversation logs and history vector stores (future).

2.2 Document domain

1. `data/doc_raw/<project>/...`:

   * Plain-text files: `.md`, `.txt`, maybe `.rst`, `.json` etc.
   * Directory name `<project>` defines one logical document project (e.g. `RAGstream_Req`, `AWS_Notes`).

2. `data/chroma_db/<project>/`:

   * Chroma collection(s) backing that project’s dense document vectors.
   * The current project file manifest (`file_manifest.json`) is stored here.

3. `data/splade_db/<project>/`:

   * Persistent sparse store for that project’s SPLADE document representations.
   * Uses the same chunk IDs and document metadata as the dense branch.

2.3 History domain (future)

1. `data/history/logs/`:

   * Append-only text logs of Q/A history.
   * Each log file belongs to a logical “session” or “history stream” (e.g. `session-YYYYMMDD-HHMMSS.log`).

2. `data/history/vectors/`:

   * Vector store(s) for conversation history (e.g. a Chroma collection `history_main`).
   * Separate from document vector stores, but using the same base vector-store abstraction.

---

3. Document Ingestion (Implemented)

---

3.1 Responsibilities

1. Document ingestion must:

   * Scan a given `doc_raw/<project>` folder.
   * Detect new/changed/deleted files via a file manifest.
   * Load, chunk, encode, and upsert only changed content into the dense and sparse document stores.
   * Optionally delete stale dense/sparse representations for removed or changed files.
   * Leave a durable manifest and aligned persistent stores for retrieval.

2. [14.04.2026] The current implemented document-ingestion direction is parallel dense + SPLADE ingestion with one canonical chunking pass and one shared chunk-id scheme.

3. For the **intermediate GUI phase**, document ingestion is considered **complete** and stable; further changes must be minor and backward compatible.

3.2 Components

1. `DocumentLoader` (`ingestion/loader.py`):

   * Inputs:

     * `doc_root` (base path, e.g. `ROOT/data/doc_raw`)
     * `project_name` (subfolder under `doc_root`)
   * Outputs:

     * `(abs_path, text)` for each discovered file eligible for ingestion.
     * Relative path is derived later by `IngestionManager` from `doc_root`.

2. `Chunker` (`ingestion/chunker.py`):

   * Inputs:

     * Raw `text` for one file.
     * Chunking config (max tokens or characters, overlap).
   * Outputs:

     * Deterministically ordered text chunks, currently returned as `(file_path, chunk_text)` pairs.
     * `chunk_idx` is assigned by enumeration order inside `IngestionManager`.

3. `Embedder` (`ingestion/embedder.py`):

   * Inputs:

     * List of `chunk_text` strings.
   * Outputs:

     * List of dense embedding vectors aligned to the same order.

4. `SpladeEmbedder` (`ingestion/splade_embedder.py`):

   * Inputs:

     * List of `chunk_text` strings.
   * Outputs:

     * List of sparse SPLADE representations aligned to the same order.

5. `VectorStoreChroma` (`ingestion/vector_store_chroma.py` + `ingestion/chroma_vector_store_base.py`):

   * Wraps a Chroma collection with a simple API:

     * `add(ids, embeddings, metadatas)`
     * `query(query_vector, k, filters)`
     * `delete_where(filter_dict)`
     * `snapshot()` (optional export/backup)
   * Uses deterministic IDs:

     * `chunk_id = f"{rel_path}::{sha256}::{chunk_idx}"`.

6. `VectorStoreSplade` (`ingestion/vector_store_splade.py` + `ingestion/splade_vector_store_base.py`):

   * Wraps the local SPLADE project store with a simple API parallel to the dense branch:

     * `add(ids, vectors, metadatas)`
     * `query(query_vector, k, filters)`
     * `delete_where(filter_dict)`
     * `snapshot()` (optional export/backup)
   * Uses the same deterministic IDs as the dense branch:

     * `chunk_id = f"{rel_path}::{sha256}::{chunk_idx}"`.

7. `IngestionManager` (`ingestion/ingestion_manager.py`):

   * Orchestrates the whole document pipeline for one project:

     * loads the previous file manifest (if any),
     * computes current file metadata (path, sha256, size, mtime),
     * diffs old vs new,
     * runs loader → chunker → dense embedder / SPLADE embedder → dense/sparse stores for changed files,
     * applies optional deletion policies for old/tombstoned content,
     * writes a new manifest atomically.

3.3 File manifest and diffing

1. Manifest data:

   * For each file under `doc_raw/<project>/`:

     * `rel_path` (relative to project root)
     * `sha256` content hash
     * `size` in bytes
     * `mtime` (last modification time)

2. Manifest responsibilities:

   * On each run, the `IngestionManager` builds the current manifest, loads the previous one (if exists), and produces:

     * `unchanged` – same `sha256` and `mtime`.
     * `updated` – same path, different hash/mtime.
     * `deleted` (tombstones) – in old manifest, not in current file system.

3. Behavior:

   * Only `updated` (and new) files are re-chunked and re-encoded.
   * Optionally, for each `updated` file, the old dense/sparse representations are deleted (see 3.4).
   * Optionally, tombstoned files may have their dense/sparse representations deleted (if configured).
   * A new manifest is written only after successful ingestion; use atomic write to avoid partial manifests.

3.4 Embedding and vector store policies

1. For each `updated` file:

   * Load text.

   * Chunk into `Chunk` objects (`chunk_idx = 0..N-1`).

   * Build one canonical chunk list and one canonical metadata list.

   * Build `chunk_id` and metadata:

     * `id = f"{rel_path}::{sha256}::{chunk_idx}"`
     * `metadata = { "path": rel_path, "sha256": sha256, "chunk_idx": chunk_idx, "mtime": mtime }`

   * Call `Embedder.embed(chunk_texts)` and `VectorStoreChroma.add(ids, embeddings, metadatas)`.

   * [14.04.2026] If the sparse branch is enabled for the run, call `SpladeEmbedder.embed(chunk_texts)` and `VectorStoreSplade.add(ids, sparse_vectors, metadatas)` using the same `ids` and the same `metadatas`.

2. Optional deletion:

   * For changed files:

     * Delete rows where `path == rel_path` and `sha256 == old_sha256` from the dense store and, if present, from the sparse store.
   * For tombstones:

     * Delete rows where `path == rel_path` and `sha256 == old_sha256` from every active document store used by ingestion.

3. IDs and metadata are **invariants**:

   * Retrieval must be able to rely on `chunk_id` pattern and metadata fields.
   * No other code should invent IDs for document chunks; they must go through this pipeline.

3.5 API contract for document ingestion

1. `IngestionManager.run(subfolder, ...)`:

   * Inputs:

     * `subfolder` / project name (maps to `doc_raw/<project_name>`, `chroma_db/<project_name>`, `splade_db/<project_name>`).
     * Dense store, chunker, dense embedder, manifest path.
     * Optional sparse store and sparse embedder.
     * Chunking and deletion settings.

   * Outputs:

     * `IngestionStats` (number of files scanned, updated, skipped, deleted; number of chunks added; aggregate and per-branch embedding/upsert counters).

   * Side effects:

     * Dense store under `chroma_db/<project_name>` updated.
     * Sparse store under `splade_db/<project_name>` updated when the sparse branch is active.
     * `file_manifest.json` updated atomically in `chroma_db/<project_name>`.

2. The controller and GUI:

   * Only call `IngestionManager.run()` per project when the user presses “Ingest Folder” (intermediate GUI) or triggers ingestion in other ways later.
   * Do **not** perform ad-hoc embedding outside this manager for documents.

---

4. Conversation History & Memory (Future)

---

4.1 Goals

1. Capture and reuse conversation history as:

   * Append-only textual logs (Layer G – ground truth narrative).
   * A separate history vector store for semantic retrieval (Layer E – embeddings).

2. Integrate tags, sessions, and project hints into metadata so that retrieval can:

   * filter by tag (e.g. GOLD, SILVER, BLUE),
   * filter by session or group of sessions,
   * optionally consider project-related hints without locking history to a single project.

3. Reuse the **same ingestion mechanics** as documents (chunk → embed → add to vector store), with different policies and metadata.

4. Maintain strict durability and user control:

   * No implicit deletions of history.
   * Clear “persist” / “clear” behavior controlled by the GUI (future).
   * Ability to import history snippets from other sessions/logs by tag.

4.2 History log (Layer G – raw text)

1. For every conversation, the system maintains an append-only log:

   * Each turn (user–assistant) is written as a record with at least:

     * `id` (unique turn id, e.g. incrementing integer or UUID),
     * `session_id` (the GUI/chat session),
     * `timestamp`,
     * `user_text`,
     * `assistant_text` (if available),
     * `tags` (list of strings; initially empty or populated by GUI),
     * optional `projects` (list of project labels active in this turn),
     * optional `active_dbs` (list of DB names used in this turn).

2. Logs are stored under `data/history/logs/`:

   * Filenames may be per session (e.g. `session-<session_id>.log`).
   * Log format can be JSONL or another structured, line-based format.

3. Important:

   * Logs are append-only; older entries are never rewritten in place.
   * Edits (e.g. changing tags) are recorded as new metadata records or maintained in a separate metadata file; the original text is not destroyed.

4.3 History vector store (Layer E – embeddings)

1. History vectors are stored in one or a few Chroma collections:

   * Typically one primary collection, e.g. `history_main`.
   * Partitioning (by time, size, or user) is a later decision; the default is one collection.

2. Each vector store entry corresponds to a chunk of one or more turns:

   * Common case: one chunk per turn (user+assistant), or small groups of turns.
   * Chunking uses the same `Chunker` logic but may use different parameters (e.g. smaller chunks).

3. Metadata for each history chunk must include:

   * `session_id`
   * `turn_id_start`, `turn_id_end` (if spanning multiple turns)
   * `tags` (copied from log at embedding time)
   * `timestamp_first`, `timestamp_last`
   * optional `projects`
   * optional `active_dbs` at time of creation

4. IDs for history chunks:

   * Pattern such as:

     * `history::<session_id>::<turn_id_start>-<turn_id_end>::<chunk_idx>`
   * This separates them from document IDs and makes it clear they come from history.

4.4 History ingestion pipeline

1. A future `HistoryIngestionWorker` (name can change) is responsible for embedding history:

   * Reads the text log(s) from `data/history/logs/`.
   * Keeps track of how far it has embedded (e.g. last turn id per session).
   * For new turns, builds chunk texts (maybe based on one or more turns).
   * Uses the same `Embedder` to create vectors.
   * Calls a `HistoryStoreChroma` (subclass of `ChromaVectorStoreBase`) to add them.

2. This worker can be:

   * Periodic (triggered manually or by a timer), or
   * Async (running in background),
   * But must never block the main prompt pipeline: the RAG pipeline uses the **latest published history vectors**, but does not wait for embeddings.

3. History ingestion is **selection-only**:

   * It adds new embeddings for new turns.
   * It does not delete old history embeddings automatically.
   * Deletion (e.g. for privacy) requires explicit commands and clear UI.

4.5 Tag- and session-aware retrieval (integration hint)

1. Retrieval logic (in Requirements_RAG_Pipeline.md) must be able to query:

   * Document vectors (by project) and
   * History vectors (from `history_main` or similar).

2. History queries must support filters using metadata:

   * `session_id in {...}` – current session only or selected set.
   * `tags contains GOLD` – only gold-level entries.
   * `projects contains "RAGstream"` – project-aware filtering.
   * Time-based constraints (e.g. recent N days) as needed.

3. Decay weighting and tag-based rules:

   * Recency can be implemented by scoring (e.g. older entries downweighted), not by deletion.
   * Tag rules (GOLD, SILVER, BLUE) influence eligibility and scoring:

     * GOLD may get a large positive bias.
     * BLUE may be excluded entirely.

4. The exact retrieval-scoring formula is outside this document, but the **metadata fields** and the **availability of history vectors** are guaranteed by these ingestion requirements.

4.6 Cross-log and cross-project import (future feature)

1. The system must support:

   * Importing chunks or turns from other sessions/logs into the active project based on tags.
   * Example: “Load all GOLD-tagged turns from past month into the current project’s history context.”

2. Implementation hint:

   * This is primarily a retrieval/selection problem; the ingestion requirement is that:

     * tags and session ids are always recorded,
     * metadata is rich enough to filter on `tags`, `session_id`, `projects`, and time.

3. No special ingestion pipeline is required for cross-log import; it reuses the existing history vectors and metadata.

---

5. Multi-Project and Multi-DB Strategy

---

5.1 Documents

1. There is a **1:1** mapping between:

   * `data/doc_raw/<project>` and
   * `data/chroma_db/<project>`.

2. Each project is ingested separately via `IngestionManager.run(project)`.

3. Retrieval may:

   * query one or several document DBs in a single pipeline, but this is a **retrieval** decision, not an ingestion decision.

5.2 History

1. History is not strictly tied to a project:

   * A single global history store is allowed, with metadata fields controlling which turns are considered relevant for a given project or run.

2. Project and DB context appear as metadata only:

   * `projects` tag (list of strings).
   * `active_dbs` at time of turn.

3. Retrieval for a given run can choose:

   * to only consider history chunks whose `projects` contain the current project label, or
   * to always include general/global GOLD history entries, etc.

4. This approach avoids creating one Chroma DB per chat session or per project, keeping ingestion and retrieval manageable.

---

6. Durability, Deletion, and User Control

---

6.1 Documents

1. Documents are considered long-term assets:

   * Deletions occur only when files are physically removed or replaced in `doc_raw`.
   * Embeddings for tombstoned files may be deleted automatically as part of ingestion.

2. No additional guarantees beyond “manifest-driven” consistency are required.

6.2 History

1. History entries are **never deleted silently**:

   * Any removal of history vectors or log entries must be triggered by explicit user action (e.g. “clear history” in GUI) or clear configuration.

2. “Clear history” semantics:

   * When a user chooses to clear history (per session or globally), the system may:

     * mark entries as inactive in metadata, and/or
     * delete corresponding vectors from the history store,
     * optionally archive or anonymize the raw logs.

3. Persist toggle:

   * The GUI must allow the user to choose whether a session’s turns are persisted at all (e.g. a “Persist history” checkbox).
   * If persistence is off, turns may still exist in transient memory for the current run but are not written to `data/history`.

---

7. Non-Goals and Constraints

---

1. This document does not prescribe:

   * Which embedding model is used (OpenAI, local, etc.).
   * How exactly chunk sizes are tuned for history vs documents.
   * How retrieval scores are computed.

2. All such choices must respect the invariants defined here:

   * Stable ID patterns.
   * Required metadata fields for documents and history.
   * Append-only raw logs for history.
   * No implicit history deletion.

---

8. Summary

---

* Document ingestion is **implemented and stable**:

  * `doc_raw/<project>` → loader → chunker → dense embedder + sparse embedder → `chroma_db/<project>` + `splade_db/<project>`, with manifest-driven incremental updates and deterministic IDs.

* Conversation history ingestion is **planned**:

  * Append-only logs under `data/history/logs/`.
  * A separate history vector store under `data/history/vectors/`.
  * A future worker reusing the same chunk/embed/add pipeline with different metadata and policies (no silent deletions, tag/session-aware retrieval).

* Both domains share the same core mechanics but differ in how they are **queried**, **prioritized**, and **controlled** by the user.