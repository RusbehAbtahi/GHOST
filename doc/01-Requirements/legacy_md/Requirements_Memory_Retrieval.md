Based on the current MemoryMerge note and the existing retrieval requirement draft, here is the polished replacement version.  

````markdown
# Requirements_Memory_Retrieval.md

Last update: 04.05.2026

Purpose:
This document defines the Memory Retrieval layer of RAGstream.

It specifies how recorded and ingested `MemoryRecord` objects are selected, scored, exposed for inspection, and prepared for later memory merging and compression.

This document assumes that Memory Recording and Memory Ingestion already exist as separate layers. It does not repeat their full persistence or ingestion requirements.

---

## 1. Scope

This document covers:

- Memory Retrieval execution when the user presses the `Retrieval` button,
- current-log automatic memory retrieval,
- Direct Recall Key lookup across all memory histories,
- working-memory candidate selection,
- episodic MemoryRecord candidate selection,
- semantic memory chunk selection,
- parent-level MemoryRecord scoring,
- runtime configuration for memory retrieval limits,
- memory candidate storage inside `SuperPrompt`,
- handoff to A3/A4 for semantic memory chunks,
- handoff to `MemoryMerge` for working / episodic / Direct Recall memory.

This document does not cover:

- `.ragmem` / `.ragmeta.json` persistence details,
- memory vector ingestion details,
- full memory compression prompt design,
- HardRules implementation,
- final Prompt Builder implementation,
- benchmarking and evaluation.

Those belong to separate requirement files or later requirement updates.

---

## 2. Relation to existing memory layers

Memory Retrieval depends on two already defined layers:

```text
Memory Recording
  = durable MemoryRecord truth
  = .ragmem + .ragmeta.json + memory_index.sqlite3

Memory Ingestion
  = searchable vector representation
  = record-handle vector + question vectors + answer vectors
````

Memory Retrieval must not replace either of these layers.

Memory Retrieval must not modify original `MemoryRecord` content.

Memory Retrieval must not overwrite `.ragmem`, `.ragmeta.json`, or memory vectors.

It only reads existing memory truth and vector representations, then produces a run-local candidate pack.

---

## 3. Core retrieval principle

Automatic Memory Retrieval works only on the current active memory log.

Other memory histories do not influence the current chat automatically.

Cross-history memory access is allowed only through:

```text
Direct Recall Key
```

This keeps automatic memory local, inspectable, and predictable.

---

## 4. Runtime pipeline wiring

### 4.1 Retrieval button

For the current implementation, pressing the existing `Retrieval` button shall trigger two retrieval paths:

```text
retriever.py      = document retrieval
retriever_mem.py  = memory retrieval
```

Both paths produce candidate pools.

Document Retrieval continues to populate the existing document retrieval fields and GUI inspection views.

Memory Retrieval populates an additional memory candidate structure inside `SuperPrompt`.

At this stage, memory candidates are not yet final compressed prompt context.

The behavior is analogous to document retrieval: candidates are collected and shown for inspection before later stages reduce them.

### 4.2 ReRanker

The existing ReRanker path shall ignore memory for now.

ReRanker continues to operate only on document retrieval results.

Memory candidates remain stored separately in `SuperPrompt`.

### 4.3 A3 NLI Gate

A3 receives mixed semantic evidence candidates:

```text
semantic memory chunks + document chunks
```

Current default balance:

```text
5 memory chunks + 25 document chunks = 30 A3 candidates
```

A3 judges usefulness across both memory and document chunks.

### 4.4 A4 Condenser

A4 condenses the A3-useful mixed evidence into `S_CTX_MD`.

Current A4 final condenser output limit:

```text
5000 tokens
```

A4 handles semantic memory chunks and document chunks together.

### 4.5 MemoryMerge

Working memory, episodic MemoryRecords, and Direct Recall are not handled by A3/A4 in the current design.

They are handled by a separate memory merge path.

The current `A5 Format Enforcer` button shall be renamed and repurposed as:

```text
MemoryMerge
```

Current `MemoryMerge` responsibility:

```text
working memory candidates
+ episodic MemoryRecord candidates
+ Direct Recall candidate
→ apply token limits
→ compress / trim / format
→ write final memory context block into SuperPrompt
```

A5 Format Enforcer remains outside this implementation step.

### 4.6 Future Prompt Builder

Later, Prompt Builder shall run the whole process automatically:

```text
Document Retrieval
+ Memory Retrieval
+ A3/A4 semantic evidence condensation
+ MemoryMerge
+ future HardRules / direct fetchers
+ final deterministic prompt assembly
```

Manual buttons remain useful now because they expose intermediate candidate pools for inspection.

---

## 5. Required implementation modules

Memory Retrieval should be split into small responsibility-focused files.

Required files:

```text
ragstream/retrieval/retriever_mem.py
ragstream/memory/memory_scoring.py
ragstream/memory/memory_index_lookup.py
ragstream/memory/memory_context_pack.py
```

### 5.1 retriever_mem.py

Role:

```text
Memory Retrieval orchestration
```

Responsibilities:

* receive query / current SuperPrompt / config,
* call memory vector scoring,
* call deterministic SQLite/index lookup,
* assemble selected memory candidates,
* create/update `MemoryContextPack`,
* write memory retrieval result into `SuperPrompt`.

This file should remain thin.

It should not contain all scoring math or SQLite-specific lookup logic.

### 5.2 memory_scoring.py

Role:

```text
memory ranking mathematics
```

Responsibilities:

* score memory chunks,
* aggregate multiple Q chunks into one Q score,
* aggregate multiple A chunks into one A score,
* handle meta score,
* apply role-separated weighting,
* apply temporal decay for Green records,
* calculate parent MemoryRecord scores.

### 5.3 memory_index_lookup.py

Role:

```text
deterministic memory index lookup
```

Responsibilities:

* latest effective Gold lookup,
* Direct Recall Key lookup,
* recent non-Black working-memory lookup,
* tag and timestamp filtering using `memory_index.sqlite3`.

This name is preferred over `memory_sqlite_lookup.py` because the conceptual role is index lookup. SQLite is the current implementation backend.

### 5.4 memory_context_pack.py

Role:

```text
structured run-local memory retrieval result
```

Responsibilities:

* define the candidate-pack structure,
* hold working-memory candidates,
* hold episodic candidates,
* hold semantic memory chunk candidates,
* hold Direct Recall candidate,
* hold diagnostics and token-budget information,
* provide renderable inspection data for SuperPrompt / GUI.

---

## 6. MemoryContextPack

Memory Retrieval shall produce a structured run-local object, conceptually called:

```text
MemoryContextPack
```

This object is not memory truth.

It is a runtime candidate package.

It may contain:

```text
working_memory_candidates
episodic_candidates
semantic_memory_chunks
direct_recall_candidate
selection_diagnostics
token_budget_report
```

The `SuperPrompt` model must be extended so this memory candidate pack can be stored and rendered for GUI inspection.

MemoryContextPack should keep candidates visible before they are compressed or merged.

---

## 7. Simplified memory tags

For Memory Retrieval, active tags are:

```text
Gold
Green
Black
```

### 7.1 Green

Green is the normal memory class.

Green records participate in semantic retrieval and decay-based scoring.

Green token cap:

```text
1500 tokens
```

### 7.2 Gold

Gold is a rare high-authority memory class.

Gold gives priority in episodic retrieval, but it does not mean unlimited context.

Gold token cap:

```text
3000 tokens
```

Only one effective Gold is used by default.

### 7.3 Black

Black means retrieval removal in practice.

Black records:

* remain physically stored,
* remain indexed,
* are excluded from automatic Memory Retrieval,
* are excluded from Direct Recall injection.

Black is not physical deletion.

### 7.4 Removed tags

The following old tags are not part of the current retrieval design:

```text
Red
Platin
Silver
```

Reason:

* Red belongs better to a future HardRules subsystem.
* Platin and Silver add complexity that is not needed now.
* Gold / Green / Black are enough for the current memory retrieval behavior.

---

## 8. Retrieval source mode

Each MemoryRecord shall support:

```text
retrieval_source_mode = "QA" | "Q" | "A"
```

Default:

```text
QA
```

Meaning:

```text
QA = use question and answer
Q  = use only question/input side
A  = use only answer/output side
```

This is metadata, not a tag.

It must not be encoded as a tag prefix.

GUI labels may be:

```text
Retrieve Q+A
Retrieve only Q
Retrieve only A
```

The retrieval source mode affects:

* which vectors contribute to scoring,
* which chunks may be selected as semantic memory chunks,
* which side is later allowed for MemoryMerge / compression.

---

## 9. Direct Recall Key

Direct Recall Key is an explicit user-controlled lookup.

It is the only Memory Retrieval lane allowed to search across all memory histories.

### 9.1 Scope

Direct Recall Key searches:

```text
memory_index.sqlite3
```

across all memory histories.

### 9.2 Limit

Only one Direct Recall Key is active per run.

If the field is empty, Direct Recall is skipped.

If the key is provided but no match exists, the system issues a warning, not an error.

### 9.3 Token limits

Direct Recall uses the same tag token caps:

```text
Gold  = 3000 tokens
Green = 1500 tokens
Black = excluded
```

Direct Recall is independent from automatic episodic slots.

### 9.4 Retrieval source mode

Direct Recall must respect `retrieval_source_mode`.

Examples:

```text
QA → Direct Recall uses Q+A
Q  → Direct Recall uses only question/input
A  → Direct Recall uses only answer/output
```

---

## 10. Working-memory candidates

Working memory is recency-based.

It uses the current active memory log only.

Default behavior:

```text
select latest non-Black Q/A pair
select second latest non-Black Q/A pair
```

Config values:

```text
max_pairs = 2
latest_pair_max_tokens = 3000
other_pair_max_tokens = 1500
total_max_tokens = 4000
exclude_tags = ["Black"]
```

Budget rule:

```text
latest pair gets up to latest_pair_max_tokens
remaining budget = total_max_tokens - used_by_latest
other pair gets min(other_pair_max_tokens, remaining budget)
```

This replaces the older `second_latest_pair_max_tokens` wording.

Working-memory candidates are shown after Retrieval but are not final prompt context until MemoryMerge runs.

---

## 11. Episodic MemoryRecord candidates

Episodic retrieval selects parent MemoryRecords from the current active memory log.

Eligible tags:

```text
Gold
Green
```

Excluded tag:

```text
Black
```

Config values:

```text
max_total_records = 3
max_gold_records = 1
gold_max_tokens = 3000
green_max_tokens = 1500
```

### 11.1 Gold

The system selects the most recent effective Gold record, if available.

If several Gold records exist, only one receives effective Gold priority by default.

### 11.2 Green slots

Green slots are computed from effective Gold count:

```text
green_slots = max_total_records - effective_gold_count
```

Examples:

```text
Gold exists:
1 Gold + 2 Green

No Gold:
0 Gold + 3 Green
```

If Gold is disabled later through GUI/config, `effective_gold_count = 0`.

### 11.3 Inspection candidates

Memory Retrieval may keep more episodic candidates for inspection than are finally merged.

For example, it may calculate and show up to 5 ranked episodic candidates, while MemoryMerge later uses only the configured final limit.

This mirrors the document retrieval pattern: candidate pool first, final compressed context later.

---

## 12. Shared semantic scoring pass

Memory Retrieval should not run completely separate semantic and episodic scoring systems.

One shared memory-vector scoring pass should produce both:

```text
1. semantic memory chunk candidates
2. parent-level episodic MemoryRecord scores
```

The process:

```text
query
→ score memory vector entries
→ rank Q/A/meta chunks
→ produce top semantic memory chunks
→ aggregate chunk scores by parent MemoryRecord
→ produce episodic parent scores
```

This keeps semantic chunk retrieval and episodic parent retrieval aligned.

---

## 13. Chunk-level scoring and filtering

Memory vector entries have roles:

```text
question
answer
record_handle / meta
```

The system first scores chunks by similarity against the current query.

Black records are removed or scored to zero.

Gold records are excluded from Green semantic competition where appropriate because Gold has its own priority lane.

The system may keep a larger internal candidate list for debugging, but the semantic memory chunk output limit remains:

```text
max_memory_chunks = 5
```

Top memory chunks should preserve:

```text
file_id
record_id
role
block_id
tag
retrieval_source_mode
score
source_type = memory_chunk
```

---

## 14. Parent-level scoring

For each MemoryRecord, scoring shall aggregate chunk scores into role scores:

```text
Q_score    = aggregate question chunk scores
A_score    = aggregate answer chunk scores
Meta_score = record-handle / meta score
```

### 14.1 P-norm aggregation inside each role

When a MemoryRecord has multiple Q chunks or multiple A chunks, their scores may be aggregated by p-norm.

Current agreed default:

```text
p = 9
```

Purpose:

* a very strong chunk should matter,
* but aggregation remains role-local,
* Q and A are still treated as different evidence roles.

This p-norm is used inside Q or A aggregation, not as the final parent-score rule.

### 14.2 Final role weighting

After role-local aggregation, final parent score uses role-separated weighted sum.

Default weights:

```text
QA mode:
answer   = 0.55
question = 0.35
meta     = 0.10

A mode:
answer   = 0.85
question = 0.00
meta     = 0.15

Q mode:
answer   = 0.00
question = 0.85
meta     = 0.15
```

Reason:

* answer chunks usually contain reusable knowledge,
* question chunks detect similarity of old problems,
* meta is useful but should not dominate real content.

The final parent-score rule is weighted sum, not p-norm.

---

## 15. Temporal decay

Green episodic records use temporal decay.

Gold does not rely on Green-style decay when selected as effective Gold.

Black is excluded.

The exact decay formula is implementation configuration.

The decay calculation belongs in:

```text
memory_scoring.py
```

---

## 16. Semantic memory chunks + document chunks

Semantic memory chunks follow the document-evidence path.

Current A3 candidate balance:

```text
5 memory chunks
25 document chunks
= 30 total candidates
```

A3 judges both source types together.

A4 condenses the useful selected evidence together.

Raw memory/document chunks are not final prompt context.

They are candidates and may be visible for inspection/debugging.

Final semantic/document context comes from A4 condensation.

---

## 17. Runtime configuration

Memory Retrieval limits and scoring constants must be read from:

```text
ragstream/config/runtime_config.json
```

The requirement file does not duplicate the full JSON content.

Required config areas:

```text
memory_retrieval.enabled
memory_retrieval.tag_catalog
memory_retrieval.retrieval_source_modes
memory_retrieval.parent_score_weights
memory_retrieval.working_memory
memory_retrieval.episodic_memory
memory_retrieval.direct_recall
memory_retrieval.semantic_memory_chunks

document_retrieval.semantic_stage_max_total_chunks
document_retrieval.max_document_chunks_for_a3

a4_condenser.max_output_tokens

hard_rules.enabled
```

Required working-memory keys:

```text
max_pairs
latest_pair_max_tokens
other_pair_max_tokens
total_max_tokens
exclude_tags
```

Required scoring keys:

```text
parent_score_weights.QA.answer
parent_score_weights.QA.question
parent_score_weights.QA.meta

parent_score_weights.A.answer
parent_score_weights.A.question
parent_score_weights.A.meta

parent_score_weights.Q.answer
parent_score_weights.Q.question
parent_score_weights.Q.meta
```

The runtime config must be loaded at startup.

If the file does not exist, a default file may be created.

Existing config must not be overwritten automatically.

---

## 18. GUI requirements

Memory card metadata area should support:

```text
colored tag square + tag popup
retrieval source popup
User Keywords
Direct Recall Key
```

Preferred tag layout:

```text
■  [ Green ▼ ]
```

The separate duplicate tag text is not needed if the popup already shows the tag.

Retrieval source popup values:

```text
Retrieve Q+A
Retrieve only Q
Retrieve only A
```

Default:

```text
Retrieve Q+A
```

Direct Recall Key field:

* appears below User Keywords,
* uses exact label `Direct Recall Key`,
* may be visually highlighted with a medium red border.

The GUI remains a view/editor, not the source of truth.

New GUI fields must later synchronize into MemoryRecord metadata, `.ragmeta.json`, SQLite, and vector metadata as needed.

---

## 19. SuperPrompt integration

`SuperPrompt` must be extended to hold memory retrieval candidates separately from final prompt text.

It should distinguish at least:

```text
document retrieval candidates
memory retrieval candidates
semantic memory chunks
working-memory candidates
episodic candidates
direct-recall candidate
final merged memory context
```

Memory candidates should be visible in the SuperPrompt GUI after pressing Retrieval.

At this stage they are candidates, not final compressed memory context.

MemoryMerge later writes the final memory context block.

A3/A4 later write the condensed semantic/document evidence block.

---

## 20. MemoryMerge boundary

Memory Retrieval selects candidates.

MemoryMerge compresses / trims / formats the selected memory records.

MemoryMerge handles:

```text
working-memory candidates
episodic MemoryRecord candidates
Direct Recall candidate
```

MemoryMerge does not handle semantic memory/document chunk condensation; that belongs to A3/A4.

MemoryMerge must respect:

```text
Gold token cap
Green token cap
working-memory total cap
retrieval_source_mode
Direct Recall limit
Black exclusion
```

Exact compression prompt or deterministic trimming logic is not defined here.

---

## 21. HardRules boundary

HardRules are postponed.

HardRules are not Red-tagged MemoryRecords.

Runtime config keeps:

```text
hard_rules.enabled = false
```

Future HardRules implementation will be a separate procedural subsystem.

Memory Retrieval must leave a clean boundary for it.

---

## 22. Error handling

If Memory Retrieval fails:

* Memory Recording remains valid,
* Memory Ingestion remains valid,
* `.ragmem` remains unchanged,
* `.ragmeta.json` remains unchanged,
* SQLite is not corrupted,
* vector stores are not modified,
* the error is logged,
* the user receives a clear warning or controlled failure message.

If Direct Recall Key is provided but no record is found:

```text
warning only, no hard error
```

---

## 23. Traceability and diagnostics

Every selected memory candidate should be traceable to:

```text
file_id
record_id
role
tag
retrieval_source_mode
selection lane
score or deterministic selection reason
token budget class
```

The GUI/debug view should make it possible to understand why a memory item was selected.

---

## 24. Acceptance criteria

Memory Retrieval is complete when:

1. Pressing `Retrieval` runs both document retrieval and memory retrieval.

2. Memory Retrieval is implemented through:

   ```text
   retriever_mem.py
   memory_scoring.py
   memory_index_lookup.py
   memory_context_pack.py
   ```

3. `retriever_mem.py` remains orchestration-focused.

4. Memory Retrieval writes a structured candidate pack into `SuperPrompt`.

5. Automatic memory retrieval uses only the current active memory log.

6. Direct Recall Key can look up one matching non-Black record across all memory histories.

7. Working memory selects up to two latest non-Black records.

8. Working memory respects:

   ```text
   latest_pair_max_tokens
   other_pair_max_tokens
   total_max_tokens
   ```

9. Episodic retrieval supports one effective Gold and Green semantic slots.

10. Green slots are calculated as:

    ```text
    max_total_records - effective_gold_count
    ```

11. Memory chunk scoring produces top semantic chunks and parent-level episodic scores from one shared scoring pass.

12. Multiple Q/A chunk scores may be aggregated by p-norm within each role.

13. Final parent scoring uses role-separated weighted sum.

14. Retrieval source mode `QA | Q | A` affects scoring and later compression source.

15. Semantic memory chunks sent to A3 are capped at 5.

16. Mixed A3 evidence uses the current balance:

    ```text
    5 memory chunks + 25 document chunks
    ```

17. A4 condenser output is capped by `a4_condenser.max_output_tokens`.

18. ReRanker ignores memory for now.

19. `A5 Format Enforcer` button is renamed / repurposed as `MemoryMerge`.

20. MemoryMerge handles working memory, episodic MemoryRecords, and Direct Recall.

21. HardRules remain disabled and separate.

22. Memory Retrieval failure does not corrupt Memory Recording or Memory Ingestion state.

---

## 25. Final design rule

The Memory Retrieval layer shall remain explicit, bounded, and inspectable.

Core invariant:

```text
Retrieval button builds candidate pools.
Memory Retrieval runs beside Document Retrieval.
Automatic memory retrieval is current-log only.
Cross-history memory requires Direct Recall Key.
Semantic memory chunks join document chunks for A3/A4.
Working / episodic / Direct Recall memory goes to MemoryMerge.
Gold is rare and limited.
Green is semantic and decay-aware.
Black is excluded.
Q/A/Q+A is metadata, not a tag.
Runtime limits live in runtime_config.json.
```

```
```
