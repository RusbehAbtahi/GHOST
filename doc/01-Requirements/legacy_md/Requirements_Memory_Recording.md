# Requirements_Memory_Recording.md

Last update: 05.05.2026

Purpose:
This document defines the memory-recording layer of RAGstream.

It specifies how accepted prompt/response pairs are captured as MemoryRecords, managed by MemoryManager, displayed in the Streamlit GUI, persisted into append-only `.ragmem` body files, synchronized into `.ragmeta.json` metadata files, and indexed in SQLite.

This document does not define memory vector ingestion, memory chunking, semantic retrieval, or merging memory with the RAG pipeline. Those are defined in separate future requirement files.

---

## 1. Scope

### 1.1 This document covers

This requirement covers the recording and persistence of structured memory.

It covers:

- `MemoryManager`
- `MemoryRecord`
- manual memory feed from the GUI
- memory display in Streamlit
- `.ragmem` durable memory files
- `.ragmeta.json` sidecar metadata files
- `memory_index.sqlite3`
- YAKE-based automatic keywords
- user keywords as a future-reserved backend field
- per-record tag handling
- per-record active project snapshot
- synchronization between GUI, MemoryManager, `.ragmeta.json`, and SQLite

### 1.2 This document does not cover

This document does not define:

- Chroma memory ingestion
- memory chunking
- frame-based embedding rules
- memory retrieval
- deterministic memory fetching
- merging memory context with document retrieval context
- client-side export/import
- advanced history management

Those belong to separate requirement documents:

- `Requirements_Memory_Ingestion.md`
- `Requirements_Memory_Retrieval.md`
- future memory-management / import-export requirements

---

## 2. Design position

Memory recording is a first-class subsystem of RAGstream.

It is not only runtime logging.

It is not the same as TextForge / RagLog.

It is not a sink.

It manages structured, reusable memory records.

The accepted core model has exactly two central classes:

- `MemoryManager`
- `MemoryRecord`

There is no separate `MemorySession` class.

There is no separate `ActiveMemoryFileState` class.

The active memory file/session is represented by `MemoryManager` itself.

---

## 3. File and folder layout

### 3.1 Code files

The memory recording implementation shall live under:

`ragstream/memory/`

Required files:

```text
ragstream/memory/
├─ __init__.py
├─ memory_record.py
├─ memory_manager.py
└─ memory_actions.py
````

### 3.2 File responsibilities

`memory_record.py`

* Contains `MemoryRecord`.
* Does not manage files.
* Does not manage SQLite.
* Does not know Streamlit.
* Represents one accepted input/output memory unit.

`memory_manager.py`

* Contains `MemoryManager`.
* Owns one active memory history file.
* Owns the current list of MemoryRecords.
* Owns current MetaInfo.
* Handles `.ragmem`, `.ragmeta.json`, and SQLite synchronization.

`memory_actions.py`

* Contains reusable workflow functions.

* Main required function:

  `capture_memory_pair(...)`

* This function is called by:

  * manual memory feed button,
  * later direct LLM calls,
  * later Copilot calls,
  * later tool/external-function calls.

The GUI shall not embed memory persistence logic directly.

---

## 4. Data layout

### 4.1 Memory data root

Memory data shall be stored under:

```text
data/memory/
```

Reason:
This subsystem manages structured memory, not merely chronological chat history.

### 4.2 Required data structure

```text
data/memory/
├─ files/
│  ├─ YYYY-MM-DD-HH-mm-TITLE.ragmem
│  └─ YYYY-MM-DD-HH-mm-TITLE.ragmeta.json
│
└─ memory_index.sqlite3
```

### 4.3 Local path example

With project root:

```text
/home/rusbeh_ab/project/RAGstream
```

the memory files shall be stored under:

```text
/home/rusbeh_ab/project/RAGstream/data/memory/files/
```

SQLite shall be stored at:

```text
/home/rusbeh_ab/project/RAGstream/data/memory/memory_index.sqlite3
```

### 4.4 AWS path behavior

Inside the Docker container, the corresponding path is:

```text
/app/data/memory/
```

On the EC2 host, because `/app/data` is mounted from persistent runtime data, the equivalent host path is:

```text
/home/ubuntu/ragstream_data/memory/
```

---

## 5. Startup behavior

### 5.1 MemoryManager initialization

When the Streamlit application starts, one `MemoryManager` shall be initialized and stored in `st.session_state`.

The initialization shall be similar in principle to the current controller and SuperPrompt session initialization.

At startup:

* GUI memory display is empty.
* `MemoryManager.records` is empty.
* `MemoryManager.metainfo` is empty.
* No `.ragmem` file is physically created yet.
* No `.ragmeta.json` file is physically created yet.
* SQLite may be initialized if it does not exist.

### 5.2 No file creation without memory

A physical `.ragmem` file shall not be created at application startup.

A physical `.ragmem` file shall be created only when the first accepted MemoryRecord is captured.

Reason:
An empty application session is not yet a meaningful memory history.

---

## 6. Core class: MemoryManager

`MemoryManager` represents one active memory history file.

It owns:

* file identity,
* filenames,
* current MemoryRecords,
* current MetaInfo,
* memory persistence,
* SQLite synchronization.

It is the central coordinator for memory recording.

### 6.1 MemoryManager variables

```text
MemoryManager
│
├─ file_id: str
│    Unique ID of the active .ragmem memory file/history.
│
├─ title: str
│    Human-readable title used for GUI display and filename generation.
│
├─ filename_ragmem: str
│    Planned or existing durable memory filename.
│    Pattern: YYYY-MM-DD-HH-mm-TITLE.ragmem
│
├─ filename_meta: str
│    Planned or existing sidecar metadata filename.
│    Pattern: YYYY-MM-DD-HH-mm-TITLE.ragmeta.json
│
├─ memory_root: Path
│    Server-side root folder for memory files.
│    Expected root: data/memory/
│
├─ sqlite_path: Path
│    Path to the global memory_index.sqlite3 file.
│
├─ records: list[MemoryRecord]
│    Full active list of MemoryRecords belonging to the currently loaded memory file.
│
├─ metainfo: dict
│    Lightweight metadata rebuilt from records and rewritten to .ragmeta.json.
│
├─ tag_catalog: list[str]
│    Allowed tag values.
│    Required values: ["Gold", "Green", "Black"]
│
└─ b_file_created: bool
     False until the first MemoryRecord is captured and the .ragmem file is physically created.
```

### 6.2 MemoryManager methods

```text
MemoryManager.methods
│
├─ __init__(
│      memory_root: Path,
│      sqlite_path: Path,
│      title: str = "Untitled"
│   ) -> None
│      Creates an empty MemoryManager with new file_id, planned filenames,
│      empty records, empty MetaInfo, and no physical .ragmem file yet.
│
├─ start_new_history(
│      title: str
│   ) -> None
│      Resets the manager to a new empty memory history with new file_id,
│      title, filenames, empty records, and empty MetaInfo.
│
├─ load_history(
│      file_id: str
│   ) -> None
│      Loads an existing .ragmem file and its .ragmeta.json metadata using
│      SQLite file lookup, then rebuilds records in memory.
│
├─ list_histories() -> list[dict]
│      Returns lightweight history entries for GUI selection:
│      file_id, title, filename, created_at, updated_at, record_count.
│
├─ capture_pair(
│      input_text: str,
│      output_text: str,
│      source: str,
│      parent_id: str | None = None,
│      user_keywords: list[str] | None = None,
│      active_project_name: str | None = None,
│      embedded_files_snapshot: list[str] | None = None
│   ) -> MemoryRecord
│      Creates one MemoryRecord from raw Prompt input plus accepted response,
│      appends it, persists it, updates MetaInfo, and refreshes SQLite.
│
├─ sync_gui_edits(
│      gui_records_state: list[dict]
│   ) -> None
│      Reads current GUI edits for existing records and updates the matching
│      MemoryRecord objects by record_id.
│
├─ save_metainfo() -> None
│      Rebuilds MetaInfo from current records and rewrites the full
│      .ragmeta.json file.
│
├─ refresh_sqlite_index() -> None
│      Synchronizes SQLite rows for the active file_id and its MemoryRecords.
│
├─ _build_metainfo() -> dict
│      Internal method that builds the complete current MetaInfo dictionary
│      from MemoryManager.records.
│
└─ close() -> None
       Flushes pending metadata/index updates and releases resources if needed.
```

### 6.3 MemoryManager responsibility boundaries

MemoryManager shall:

* own the active memory file identity,
* own `records: list[MemoryRecord]`,
* own current `metainfo`,
* append records to `.ragmem`,
* rewrite `.ragmeta.json`,
* refresh SQLite for the active file,
* provide records for GUI rendering.

MemoryManager shall not:

* perform document retrieval,
* perform memory retrieval,
* perform Chroma ingestion,
* decide memory chunking strategy,
* act as a general runtime logger,
* contain Streamlit widget definitions.

---

## 7. Core class: MemoryRecord

`MemoryRecord` represents one accepted prompt/response pair.

It is the atomic memory unit.

It does not represent a list of records.

It does not represent a file.

It does not own MetaInfo.

### 7.1 MemoryRecord variables

```text
MemoryRecord
│
├─ record_id: str
│    Unique stable ID of this memory input/output pair.
│
├─ parent_id: str | None
│    Optional parent MemoryRecord ID, used for future corrections,
│    continuations, or related follow-up records.
│
├─ created_at_utc: str
│    UTC timestamp when this MemoryRecord was created.
│
├─ input_text: str
│    Raw Prompt text written by the user.
│    This is not the SuperPrompt.
│
├─ output_text: str
│    Accepted response from manual memory feed, LLM call, tool call,
│    or external function.
│
├─ source: str
│    Origin of the response.
│    Examples: "manual_memory_feed", "llm_response", "tool_result".
│
├─ tag: str
│    User-facing tag value.
│    Default: "Green".
│
├─ auto_keywords: list[str]
│    Keywords generated automatically by YAKE from input_text + output_text.
│
├─ user_keywords: list[str]
│    Future-reserved backend metadata field.
│    In the current GUI flow this remains empty.
│
├─ active_project_name: str | None
│    Active DB / Project selected in GUI at the moment this record was created.
│
├─ embedded_files_snapshot: list[str]
│    Complete list of embedded files visible for the active project at the
│    moment this record was created.
│
├─ input_hash: str
│    Hash of input_text for integrity checking and diagnostics.
│
└─ output_hash: str
     Hash of output_text for integrity checking and diagnostics.
```

### 7.2 MemoryRecord methods

```text
MemoryRecord.methods
│
├─ __init__(
│      input_text: str,
│      output_text: str,
│      source: str,
│      parent_id: str | None = None,
│      tag: str = "Green",
│      user_keywords: list[str] | None = None,
│      active_project_name: str | None = None,
│      embedded_files_snapshot: list[str] | None = None
│   ) -> None
│      Creates one MemoryRecord, generates record_id, timestamp, hashes,
│      default tag, YAKE keywords, and project/file snapshot.
│
├─ generate_auto_keywords() -> list[str]
│      Runs YAKE locally on input_text + output_text and returns automatic keywords.
│
├─ update_editable_metadata(
│      tag: str | None = None,
│      retrieval_source_mode: str | None = None,
│      direct_recall_key: str | None = None,
│      user_keywords: list[str] | None = None
│   ) -> None
│      Updates editable metadata in RAM.
│      user_keywords is future-reserved and remains empty in the current GUI flow.
│      Does not change input_text, output_text, record_id, hashes, or project snapshot.
│
├─ to_ragmem_block() -> str
│      Converts the stable full record content into one appendable .ragmem block.
│
└─ to_index_dict() -> dict
       Converts record metadata into a structured dictionary for MetaInfo and SQLite indexing.
```

### 7.3 MemoryRecord content rules

`input_text` and `output_text` shall not be freely edited after capture.

If the user is dissatisfied with a MemoryRecord:

* the existing record may be assigned a different tag,
* the user may create a new corrected MemoryRecord,
* the original record remains stored.

Direct modification of stored input/output text is not part of this requirement.

---

## 8. Tag handling

### 8.1 Required tag field

Each MemoryRecord shall contain:

```text
tag: str
```

Default value:

```text
Green
```

### 8.2 Required tag catalog

The GUI tag selector and MemoryManager tag catalog shall support at least:

```text
Gold
Green
Black
```

### 8.3 Tag persistence

The current tag value shall be stored in:

* the MemoryRecord object,
* `.ragmeta.json`,
* SQLite.

The tag shall not be written into `.ragmem`.

### 8.4 GUI tag changes

If the user changes the tag of an existing MemoryRecord in the GUI, the change shall be synchronized during the next memory save/sync cycle.

The synchronization shall use stable `record_id`.

---

## 9. Keyword handling

### 9.1 Auto keywords

Each MemoryRecord shall contain:

```text
auto_keywords: list[str]
```

Auto keywords shall be generated locally using YAKE.

The YAKE input shall be based on:

```text
input_text + output_text
```

Auto keywords shall be stored in:

* MemoryRecord,
* `.ragmeta.json`,
* SQLite.

Auto keywords shall not be written into `.ragmem`.

### 9.2 User keywords

Each MemoryRecord shall contain:

```text
user_keywords: list[str]
```

`user_keywords` is a future-reserved backend metadata field.

In the current GUI flow, no user-keyword input is shown and new records keep:

```text
user_keywords = []
```

User keywords shall be stored in:

* MemoryRecord,
* `.ragmeta.json`,
* SQLite.

User keywords shall not be written into `.ragmem`.

### 9.3 Keyword synchronization

Current GUI synchronization does not collect user keywords.

Future user-keyword synchronization, if reactivated, shall use stable `record_id`.

---

## 10. Project snapshot per MemoryRecord

### 10.1 Reason

The active project may change within one memory history.

Therefore, project context shall not be stored only at MemoryManager/file level.

Each MemoryRecord shall capture its own project snapshot.

### 10.2 Required fields

Each MemoryRecord shall store:

```text
active_project_name: str | None
embedded_files_snapshot: list[str]
```

### 10.3 Active project name

`active_project_name` shall be read from the current GUI active project selection at the moment the MemoryRecord is captured.

### 10.4 Embedded files snapshot

`embedded_files_snapshot` shall contain the complete list of embedded files visible in the GUI for the active project at the moment the MemoryRecord is captured.

### 10.5 SQLite indexing

SQLite shall store at least:

* `record_id`
* `file_id`
* `active_project_name`

The embedded file snapshot may be stored either:

* as serialized JSON in a record metadata field, or
* in a separate normalized SQLite table.

The exact SQLite schema can be finalized during implementation, but the information must be persistently indexable.

---

## 11. Manual Memory Feed flow

### 11.1 Current trigger

The current implemented capture trigger is the Streamlit button:

```text
Feed Memory Manually
```

This button works together with:

```text
manual_memory_feed_text
```

### 11.2 Callback responsibility

The button callback shall remain thin.

It shall read GUI values and call the reusable memory action.

It shall not contain persistence logic directly.

### 11.3 Required GUI values

When the manual feed button is pressed, the GUI/action layer shall read:

* `prompt_text`
* `manual_memory_feed_text`
* active project name
* current embedded files list
* current GUI metadata edits for existing memory cards, if available

### 11.4 Required action call

The callback shall call:

```text
capture_memory_pair(...)
```

from:

```text
ragstream/memory/memory_actions.py
```

### 11.5 Required source value

Manual memory feed shall use:

```text
source = "manual_memory_feed"
```

### 11.6 Empty input handling

A MemoryRecord shall not be created if:

* prompt text is empty, or
* response/output text is empty.

The GUI shall show a clear message in such cases.

---

## 12. Reusable memory action

### 12.1 Function name

The reusable memory capture function shall be:

```text
capture_memory_pair(...)
```

### 12.2 File location

It shall live in:

```text
ragstream/memory/memory_actions.py
```

### 12.3 Responsibility

`capture_memory_pair(...)` shall be the workflow wrapper used by all capture paths.

It shall:

* receive or collect the required capture inputs,
* call `MemoryManager.capture_pair(...)`,
* return the created MemoryRecord or a structured result,
* return status information suitable for GUI/logging.

### 12.4 Intended call sources

The same function shall later be usable by:

* manual memory feed,
* direct LLM call,
* Copilot call,
* external tool result,
* other accepted response-producing mechanisms.

The function name shall not imply manual-only behavior.

---

## 13. Save and synchronization sequence

### 13.1 Required sequence

Whenever a new MemoryRecord is captured, the system shall perform the following sequence:

1. Read current GUI edits for existing MemoryRecords.
2. Synchronize those edits into `MemoryManager.records`.
3. Read current prompt and response.
4. Read current active project name.
5. Read current embedded files snapshot.
6. Create a new MemoryRecord.
7. Append the new MemoryRecord to `MemoryManager.records`.
8. Create the `.ragmem` file if it does not yet exist.
9. Append the new MemoryRecord block to `.ragmem`.
10. Rebuild MetaInfo from the full current record list.
11. Rewrite `.ragmeta.json`.
12. Refresh SQLite for the active `file_id`.
13. Refresh the GUI memory display from `MemoryManager.records`.

### 13.2 Current records as truth

During a save/sync cycle, `MemoryManager.records` shall be treated as the current truth for the active memory file.

`.ragmeta.json` and SQLite shall be synchronized from this current truth.

---

## 14. `.ragmem` file requirements

### 14.1 Purpose

`.ragmem` is the durable append-only memory body file.

It stores stable MemoryRecord body content only.

### 14.2 Filename pattern

The filename shall follow:

```text
YYYY-MM-DD-HH-mm-TITLE.ragmem
```

The title portion shall be sanitized for filesystem use.

### 14.3 Creation rule

The `.ragmem` file shall be physically created only after the first MemoryRecord is captured.

### 14.4 Content rule

Each MemoryRecord shall be written as one stable body block.

The block shall contain only:

* `record_id`
* `parent_id`
* `created_at_utc`
* `source`
* `input_hash`
* `output_hash`
* `input_text`
* `output_text`

The block shall not contain editable GUI metadata:

* `tag`
* `retrieval_source_mode`
* `direct_recall_key`
* `auto_keywords`
* `user_keywords`
* `active_project_name`
* `embedded_files_snapshot`

### 14.5 Append behavior

New MemoryRecords shall be appended to the `.ragmem` file.

The full input/output content shall not be stored only in SQLite.

---

## 15. `.ragmeta.json` file requirements

### 15.1 Purpose

`.ragmeta.json` is the lightweight sidecar metadata file for the matching `.ragmem` file.

It stores current metadata, not full memory text.

### 15.2 Filename pattern

The metadata filename shall match the `.ragmem` filename stem:

```text
YYYY-MM-DD-HH-mm-TITLE.ragmeta.json
```

### 15.3 Rewrite behavior

`.ragmeta.json` shall be rewritten completely during every memory save/sync cycle.

It shall not be append-only.

### 15.4 Required MetaInfo content

MetaInfo shall contain at least:

* `file_id`
* `title`
* `filename_ragmem`
* `filename_meta`
* `created_at_utc`
* `updated_at_utc`
* `record_count`
* `record_ids`
* `parent_ids`
* tag summary
* aggregated auto keywords
* aggregated user keywords as future-reserved metadata
* per-record metadata summary

### 15.5 Per-record metadata summary

For each MemoryRecord, MetaInfo shall include at least:

* `record_id`
* `parent_id`
* `created_at_utc`
* `source`
* `tag`
* `retrieval_source_mode`
* `direct_recall_key`
* `auto_keywords`
* `user_keywords`
* `active_project_name`
* `embedded_files_snapshot`
* `input_hash`
* `output_hash`

MetaInfo shall not duplicate full `input_text` and `output_text`.

---

## 16. SQLite requirements

### 16.1 Purpose

SQLite is the global searchable index for memory files and MemoryRecords.

It shall support fast lookup without scanning all `.ragmem` files.

### 16.2 Database path

SQLite shall be stored at:

```text
data/memory/memory_index.sqlite3
```

### 16.3 Scope of refresh

When one memory file is active, SQLite refresh shall affect only that active file scope.

The key scope is:

```text
file_id
```

Records shall be updated by:

```text
record_id
```

### 16.4 Required file-level index fields

SQLite shall index at least:

* `file_id`
* `title`
* `filename_ragmem`
* `filename_meta`
* `created_at_utc`
* `updated_at_utc`
* `record_count`

### 16.5 Required record-level index fields

SQLite shall index at least:

* `record_id`
* `file_id`
* `parent_id`
* `created_at_utc`
* `source`
* `tag`
* `retrieval_source_mode`
* `direct_recall_key`
* `auto_keywords`
* `user_keywords`
* `active_project_name`
* `embedded_files_snapshot`
* `input_hash`
* `output_hash`

### 16.6 Synchronization rule

SQLite shall be synchronized from the active MemoryManager state.

If a user changes editable metadata for old records and then captures a new memory, SQLite shall update those old records as part of the same synchronization cycle.

### 16.7 Upsert rule

SQLite synchronization shall use stable IDs.

For each record in the active memory file:

* if `(file_id, record_id)` exists, update it;
* if it does not exist, insert it.

### 16.8 Large database behavior

The SQLite database may contain many memory files.

Refreshing one active memory file shall not require rebuilding the whole SQLite database.

Other `file_id`s shall remain untouched.

---

## 17. GUI requirements

### 17.1 GUI role

The GUI is a view/editor.

It is not the source of truth.

The source of truth during runtime is:

```text
MemoryManager.records
```

The durable portable source is:

```text
.ragmem + .ragmeta.json
```

SQLite is the query-optimized mirror and shall not contain unique business truth absent from those files.

### 17.2 Memory display

The current Memory box shall later be driven only by MemoryManager records.

Temporary demo state such as `a2_memory_demo_entries` shall be treated as transitional.

### 17.3 Memory section title

The title `MEMORY DEMO` shall later be renamed to a proper memory title.

Suggested final title:

```text
Memory
```

or:

```text
Memory Records
```

### 17.4 Editable GUI fields per record

The GUI shall allow editing at least:

* tag
* retrieval source mode
* direct recall key

User keywords are not shown in the current GUI.
They remain a future-reserved backend field.

The GUI shall not directly edit:

* record ID,
* input text,
* output text,
* hashes,
* project snapshot.

### 17.5 GUI synchronization

Before appending a new MemoryRecord, the system shall read current GUI edits and synchronize them into existing MemoryRecords.

This avoids requiring immediate callback persistence for every tag/user-keyword edit.

---

## 18. Loading old memory histories

### 18.1 Listing histories

`MemoryManager.list_histories()` shall provide lightweight summaries for GUI selection.

Each summary shall include at least:

* `file_id`
* `title`
* `filename_ragmem`
* `created_at_utc`
* `updated_at_utc`
* `record_count`

### 18.2 Loading a history

When the user selects an old memory history:

* MemoryManager shall load the corresponding `.ragmem`.
* MemoryManager shall load the corresponding `.ragmeta.json`.
* MemoryManager shall rebuild `records` from `.ragmem` body data.
* MemoryManager shall overlay current metadata from `.ragmeta.json` onto the loaded records.
* GUI shall render the loaded records.

### 18.3 Single active memory history

At any given time, one MemoryManager represents one active memory history.

Switching histories replaces the active memory file state inside MemoryManager.

---

## 19. Interaction with SuperPrompt

MemoryRecord input shall be based on raw Prompt text.

It shall not be based on:

* SuperPrompt,
* A2-shaped output,
* Prompt Builder output,
* retrieved context,
* final composed prompt.

Reason:
Memory recording captures what the user asked and what response was accepted.

SuperPrompt belongs to the RAG pipeline.

MemoryRecord belongs to memory recording.

---

## 20. Interaction with project ingestion

Each MemoryRecord shall capture the active project context at the moment of memory creation.

The source for project data is the existing GUI/controller project state:

* Active DB / Project
* Embedded Files list

This document does not redefine project ingestion.

It only requires that the currently visible project context is recorded per MemoryRecord.

---

## 21. Boundary to memory ingestion

Memory recording shall not immediately require vector ingestion.

A MemoryRecord can be fully valid and persisted without Chroma.

Memory vector ingestion is a separate concern.

This document only requires that MemoryRecords contain enough stable IDs and metadata to support later ingestion.

---

## 22. Boundary to framed LLM responses

For future RAGstream-controlled LLM calls, output frames may be used to mark typed sections such as explanation, code, requirements update, or UML.

Memory recording shall store the full response unchanged.

Parsing frames for embedding or exclusion is not part of this document.

---

## 23. Boundary to import/export

Client-side export/import is not part of this requirement.

The `.ragmem` file format should remain suitable for future portability, but this document only requires server-side memory persistence.

---

## 24. Required implementation files

The memory recording requirement shall be implemented primarily in:

```text
ragstream/memory/memory_record.py
ragstream/memory/memory_manager.py
ragstream/memory/memory_actions.py
```

The GUI integration shall touch:

```text
ragstream/app/ui_streamlit.py
ragstream/app/ui_layout.py
ragstream/app/ui_actions.py
```

Optional controller integration may touch:

```text
ragstream/app/controller.py
```

The memory persistence data shall be under:

```text
data/memory/
```

---

## 25. Required implementation behavior summary

The accepted memory-recording flow is:

```text
User writes Prompt
        │
        ▼
User pastes response into Manual Memory Feed
        │
        ▼
User presses Feed Memory Manually
        │
        ▼
GUI/action layer reads prompt, response, active project, embedded files
        │
        ▼
memory_actions.capture_memory_pair(...)
        │
        ▼
MemoryManager.sync_gui_edits(...)
        │
        ▼
MemoryManager.capture_pair(...)
        │
        ▼
MemoryRecord is created
        │
        ▼
MemoryManager.records is updated
        │
        ▼
.ragmem is created/appended
        │
        ▼
.ragmeta.json is rewritten
        │
        ▼
SQLite is refreshed for active file_id
        │
        ▼
GUI memory display is refreshed
```

---

## 26. Final design rule

The memory-recording layer shall remain simple, explicit, and durable.

The core invariant is:

```text
MemoryManager owns one active memory history.
MemoryManager owns records: list[MemoryRecord].
MemoryRecord owns one accepted input/output pair.
.ragmem stores append-only stable body content.
.ragmeta.json stores rewritten current metadata.
SQLite mirrors searchable metadata and is not unique business truth.
GUI displays and edits metadata, but does not own memory truth.
```
