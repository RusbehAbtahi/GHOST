````markdown
# Requirements_ActiveRetrievalBrief.md

1. Purpose and scope

---

This document specifies the ActiveRetrievalBrief mechanism used by the Memory subsystem in RAGstream.

ActiveRetrievalBrief is the compact cumulative working-conversation snapshot of the active memory history.

Its purpose is to help later Memory Retrieval, MemoryMerge, and final prompt assembly understand the current conversation state without rereading the full memory history.

The ActiveRetrievalBrief mechanism covers:

* creating the first ActiveRetrievalBrief for a new memory history,
* updating the ActiveRetrievalBrief after accepted MemoryRecords,
* deterministic Q/A sentence-window reduction before LLM update,
* vector-based relevance gating before expensive LLM calls,
* pending-topic buffering for possible topic shifts,
* topic-shift confirmation,
* contributor-id tracking,
* clean-brief selection for non-Black memory records,
* final integration with SuperPrompt and MemoryMerge.

The ActiveRetrievalBrief mechanism does not cover:

* document ingestion,
* document Retrieval,
* document A3,
* document A4,
* document `S_CTX_MD`,
* final MemoryMerge compression,
* final answer generation.

Current architecture decision:

```text
Document path:
document chunks
→ A3
→ A4
→ S_CTX_MD

Memory path:
episodic memory
+ semantic memory chunks
+ working memory
+ Direct Recall
→ MemoryMerge
→ final Memory Context

Conversation-state path:
latest clean ActiveRetrievalBrief
→ injected separately into final SuperPrompt
````

ActiveRetrievalBrief is not document evidence.

ActiveRetrievalBrief is not final Memory Context.

ActiveRetrievalBrief is a derived working-conversation state object.

2. High-level data flow

---

2.1. Standard MemoryRecord flow

A Q/A pair becomes eligible for ActiveRetrievalBrief only after it has been accepted as a MemoryRecord.

Required high-level flow:

```text
accepted user input + accepted assistant output
→ MemoryManager.capture_pair(...)
→ MemoryRecord created
→ durable MemoryRecord truth saved
→ deterministic Q/A reduction and vectorization
→ ActiveBrief relevance gate
→ ActiveBrief route decision
→ ActiveRetrievalBrief written or copied
→ contributor IDs updated or copied
```

Important ordering rule:

```text
MemoryRecord durable truth MUST exist before ActiveRetrievalBrief update is attempted.
```

If ActiveRetrievalBrief update fails, the original MemoryRecord remains valid.

2.2. ActiveBrief routes

The ActiveBrief decision layer supports four conceptual routes:

```text
init_no_previous_activebrief
activebrief_update
skip_and_update_pending_topic
pending_topic_shift
```

Route meanings:

```text
init_no_previous_activebrief
= no previous clean ActiveBrief exists

activebrief_update
= current Q/A is relevant to the current ActiveBrief

skip_and_update_pending_topic
= current Q/A is not relevant enough; copy previous brief and store Q/A as possible new topic

pending_topic_shift
= current Q/A confirms the previously skipped pending topic
```

2.3. Final prompt relation

The final prompt should keep the following context types separate:

```text
Task / Purpose / Context
= user-side current request structure

ActiveRetrievalBrief
= compact working-conversation state

S_CTX_MD
= condensed document evidence from A4

Memory Context
= MemoryMerge output from episodic / semantic / working / Direct Recall memory
```

ActiveRetrievalBrief must not be hidden inside `S_CTX_MD`.

MemoryMerge may receive ActiveRetrievalBrief only as anti-duplication reference.

3. Data model and persistence authority

---

3.1. MemoryRecord truth

The original MemoryRecord Q/A remains the durable truth.

ActiveRetrievalBrief must never replace or overwrite:

```text
MemoryRecord.input_text
MemoryRecord.output_text
.ragmem stable body
.ragmeta.json current metadata
SQLite memory_records truth
memory vector entries
```

ActiveRetrievalBrief is derived context.

It may be stored with the MemoryRecord, but the original Q/A remains authoritative.

3.2. ActiveBrief fields

Each accepted MemoryRecord must support the following ActiveBrief-related fields:

```text
active_retrieval_brief : str
active_retrieval_brief_contributor_ids : list[str]
```

`active_retrieval_brief` stores the cumulative brief after this MemoryRecord.

`active_retrieval_brief_contributor_ids` stores the MemoryRecord IDs that contributed to the brief.

A skipped MemoryRecord may copy the previous ActiveBrief forward, but it must not become a contributor unless it later becomes part of a confirmed topic shift.

3.3. Contributor ID rules

Contributor IDs must be updated according to route.

Init route:

```text
contributor_ids = [current_record_id]
```

Normal update route:

```text
contributor_ids =
previous_contributor_ids
+ current_record_id
```

Skip route:

```text
contributor_ids =
previous_contributor_ids
```

Topic-shift route:

```text
contributor_ids =
previous_contributor_ids
+ pending_record_id
+ current_record_id
```

Duplicates must be avoided.

Contributor order should preserve chronological contribution order.

3.4. Clean ActiveBrief selection

Runtime should normally use:

```text
latest clean non-Black ActiveRetrievalBrief
```

A clean ActiveRetrievalBrief means:

```text
the contributor list does not include records that are currently excluded by Black tagging.
```

Black-tagged records must not automatically contribute to future working context.

If the latest brief is polluted by a Black-tagged contributor, the system should fall back to the latest earlier clean brief.

The exact lookup may be implemented in MemoryManager or a memory helper layer.

3.5. Persistence authority

Current memory persistence authority remains:

```text
.ragmem
= stable durable memory body

.ragmeta.json
= current readable/editable metadata mirror

SQLite
= current query/index layer

memory vectors
= retrieval index

ActiveRetrievalBrief
= derived conversation-state support field
```

ActiveRetrievalBrief is allowed to be persisted as derived context, but it must never become the authority for original Q/A content.

4. Runtime configuration

---

4.1. Required configuration fields

ActiveBrief settings must come from runtime configuration.

Required configurable fields:

```text
embedding_model
activebrief_relevance_threshold
pending_topic_relevance_threshold
max_tokens_total
question_max_tokens
window_size_sentences
window_overlap_sentences
redundancy_threshold
target_brief_tokens
```

Hardcoded values are allowed only as internal fallback defaults.

4.2. Embedding model

ActiveBrief relevance gating currently uses:

```text
text-embedding-3-small
```

The model name must be read from runtime configuration.

The same embedding model must be used consistently inside one gate comparison.

If the embedding model changes later, Q/A vectors, ActiveBrief vectors, and pending-topic comparisons must use the same configured model inside the same run.

4.3. Relevance thresholds

The gate must support two separate thresholds:

```text
activebrief_relevance_threshold
pending_topic_relevance_threshold
```

Current development defaults:

```text
activebrief_relevance_threshold = 0.25
pending_topic_relevance_threshold = 0.25
```

These values are development defaults and may be tuned after log inspection.

5. MemoryManager responsibility

---

5.1. Purpose

MemoryManager owns the active memory history and the runtime state needed for ActiveRetrievalBrief.

MemoryManager is responsible for:

* creating MemoryRecords,
* saving durable MemoryRecord truth,
* triggering ActiveBrief processing after durable save,
* holding the current active memory history,
* holding the pending-topic buffer,
* copying previous ActiveBrief forward when update is skipped,
* writing new or copied ActiveBrief fields into MemoryRecord,
* preserving contributor IDs,
* exposing the latest clean ActiveRetrievalBrief to retrieval / prompt assembly.

5.2. Pending-topic ownership

The pending-topic buffer belongs to MemoryManager.

It must not belong to Streamlit.

Reason:

```text
pending-topic state is memory runtime state, not GUI state.
```

Streamlit may display diagnostics, but it must not be the authority for this state.

5.3. Pending-topic buffer

The pending-topic buffer stores one skipped Q/A that may represent a new emerging topic.

It is runtime-only.

It must not be written as durable truth into:

```text
.ragmem
.ragmeta.json
SQLite memory_records
memory vector entries
```

Minimum pending-topic contents:

```text
record_id
created_at_utc
reduced_question
reduced_answer
question_vectors
answer_vectors
center_vector
vector_count
```

Optional preview fields may be stored for logging or UI diagnostics.

The pending-topic buffer should be replaced when a newer unrelated Q/A is skipped.

The pending-topic buffer should be cleared after a confirmed topic shift.

5.4. Safe failure behavior

If ActiveBrief processing fails, MemoryManager must preserve the durable MemoryRecord.

Safe fallback behavior:

```text
log error
copy previous ActiveBrief forward when possible
do not corrupt contributor IDs
do not rewrite original Q/A truth
```

ActiveBrief failure must not block core Memory Recording.

6. MemorySentenceReducer

---

6.1. Purpose

MemorySentenceReducer is the deterministic pre-compression layer used before ActiveBrief LLM update.

Its responsibilities are:

* split Q/A into sentences or sentence-windows,
* estimate token counts,
* allocate question/answer budgets,
* embed sentence-windows,
* compute center or anchor similarity,
* remove redundant windows where needed,
* return reduced Q/A text,
* return vectors and diagnostics.

6.2. Centroid mode for ActiveBrief

For ActiveBrief update, the current reduction mode is centroid-based.

Conceptual flow:

```text
Q/A windows
→ vectorize
→ compute Q/A centroid
→ rank windows by similarity to centroid
→ keep strongest windows under token budget
```

This creates compact reduced Q/A material for the ActiveBrief updater.

6.3. Query-aware mode for future MemoryMerge

For later episodic MemoryMerge compression, the same reducer should support query-aware mode.

Conceptual flow:

```text
current user query
+ episodic Q/A windows
→ vectorize
→ rank by query similarity
→ keep strongest windows under token budget
```

Query-aware mode belongs to episodic MemoryMerge compression unless explicitly selected elsewhere.

6.4. Reducer output contract

The reducer must return enough information for both LLM input and relevance gating.

Required output shape:

```text
reduced_question
reduced_answer
question_vectors
answer_vectors
diagnostics
```

If the original Q/A is already below the token budget, the reducer must still create vectors.

Reason:

```text
The relevance gate needs vectors even when textual reduction is not needed.
```

If reduction is performed, `question_vectors` and `answer_vectors` must correspond to surviving windows.

The system should not pay for the same vectorization twice.

7. ActiveBrief RelevanceGate

---

7.1. Purpose

The ActiveBrief relevance gate decides whether an LLM update is required.

It receives:

```text
current reduced Q/A vectors
current ActiveRetrievalBrief text
optional pending-topic buffer
threshold settings
```

It returns:

```text
should_update_activebrief : bool
route : str
reason : str
diagnostics : dict
```

The gate must not call the LLM.

The gate is deterministic.

7.2. ActiveBrief comparison

For normal relevance checking, the gate compares current Q/A vectors against the current ActiveRetrievalBrief.

Conceptual rule:

```text
qa_top_mean >= activebrief_relevance_threshold
→ route = activebrief_update
```

Current development default:

```text
activebrief_relevance_threshold = 0.25
```

`qa_top_mean` is calculated from the strongest Q/A sentence-window scores.

The top-window count should follow the configured top-selection logic.

7.3. Pending-topic comparison

If the current Q/A fails against the ActiveBrief and a pending-topic buffer exists, the gate compares the current Q/A against the pending-topic center.

Conceptual rule:

```text
qa_top_mean_against_pending_topic >= pending_topic_relevance_threshold
→ route = pending_topic_shift
```

Current development default:

```text
pending_topic_relevance_threshold = 0.25
```

If this comparison also fails:

```text
route = skip_and_update_pending_topic
```

The current Q/A then replaces the pending-topic buffer.

7.4. Route behavior

Init route:

```text
no previous clean ActiveBrief exists
→ call init LLM path
```

Normal update route:

```text
current Q/A passes against ActiveBrief
→ call update LLM path
```

Skip route:

```text
current Q/A fails against ActiveBrief and pending-topic
→ no LLM call
→ copy previous brief
→ store current Q/A as pending topic
```

Topic-shift route:

```text
current Q/A fails against ActiveBrief but passes against pending-topic
→ call update LLM path with previous brief + pending Q/A + current Q/A
```

Topic shift must not use the init route.

8. MemoryActiveRetrievalBriefBuilder and JSON agent

---

8.1. Builder purpose

MemoryActiveRetrievalBriefBuilder prepares the LLM input and parses the LLM output.

Its responsibilities:

* receive current MemoryRecord,
* receive previous clean ActiveRetrievalBrief,
* receive reduced Q/A,
* compose the LLM payload,
* call the configured ActiveBrief JSON agent,
* parse JSON output,
* return the new ActiveRetrievalBrief text.

The builder must not own durable memory state.

The builder must not own pending-topic buffer state.

State that must survive between calls belongs to MemoryManager.

8.2. Init route

The init route is used only when no previous clean ActiveRetrievalBrief exists.

Init input:

```text
current reduced Q/A
MemoryRecord metadata
```

Init output:

```text
first active_retrieval_brief
contributor_ids = [current_record_id]
```

Init must not be used because the topic changed.

8.3. Normal update route

Normal update input:

```text
previous clean ActiveRetrievalBrief
current reduced Q/A
MemoryRecord metadata
```

Normal update output:

```text
new active_retrieval_brief
updated contributor IDs
```

The updater must preserve previous context unless the new Q/A clearly corrects, rejects, or changes it.

8.4. Topic-shift update route

Topic-shift input:

```text
previous clean ActiveRetrievalBrief
pending skipped Q/A
current reduced Q/A
MemoryRecord metadata
```

The pending skipped Q/A must be included because it may contain the beginning of the new topic.

Topic shift must create a mixed ActiveRetrievalBrief:

```text
new topic = prioritized
old topic = preserved as prior working context
```

If later Q/As continue the new topic, the old topic may be weakened naturally.

A single topic shift must not abruptly erase the previous dominant topic.

8.5. ActiveBrief JSON agent rules

The ActiveBrief LLM agent must be JSON-configured like other RAGstream agents.

Its prompt must enforce:

* never answer the original user request,
* never write as if speaking to the user,
* never produce a final user-facing answer,
* do not create a separate `qa_summary` unless explicitly required later,
* preserve previous ActiveRetrievalBrief as working center,
* update only durable context,
* treat corrections as high-importance constraints,
* treat rejected interpretations as important negative constraints,
* treat insults and frustration as feedback signals, not topic content,
* do not invent facts, project state, files, requirements, or implementation status,
* do not import outside knowledge,
* keep the brief query-independent,
* keep the brief compact and operational,
* return only the required JSON object.

Required output:

```json
{
  "active_retrieval_brief": "..."
}
```

8.6. AgentStack neutrality

The ActiveBrief LLM updater may use AgentStack infrastructure.

ActiveBrief-specific logic must not be pushed into neutral AgentStack components.

The following belong outside neutral AgentStack files:

* route selection,
* relevance gate logic,
* pending-topic buffering,
* contributor-id logic,
* topic-shift behavior,
* MemoryRecord write-back,
* MemoryMerge integration rules.

AgentFactory, AgentPrompt, and LLMClient remain neutral infrastructure.

9. Integration, logging, and non-functional requirements

---

9.1. SuperPrompt integration

ActiveRetrievalBrief must be injected separately into the final SuperPrompt.

It should appear beside the user-side prompt context fields:

```text
Task
Purpose
Context
ActiveRetrievalBrief
```

It must not be hidden inside:

```text
S_CTX_MD
Raw Retrieved Evidence
document A4 output
```

Reason:

```text
ActiveRetrievalBrief is conversation-state memory, not document evidence.
```

9.2. MemoryMerge integration

MemoryMerge may receive ActiveRetrievalBrief only as anti-duplication reference.

Required instruction meaning:

```text
ActiveRetrievalBrief is already included separately in the final prompt.
Use it to avoid repeating information already present there.
Do not summarize ActiveRetrievalBrief again as source material.
```

MemoryMerge source material should be:

```text
reduced episodic Q/A
semantic memory chunks
working memory
Direct Recall
```

ActiveRetrievalBrief is reference context, not MemoryMerge evidence.

9.3. Semantic memory relation

Current final MemoryMerge architecture decision:

```text
semantic memory chunks are memory material,
not document evidence.
```

Document path:

```text
document chunks
→ A3
→ A4
→ S_CTX_MD
```

Memory path:

```text
selected episodic Q/A
+ selected semantic memory chunks
+ working memory
+ Direct Recall
→ MemoryMerge
→ final Memory Context
```

9.4. Logging requirements

The ActiveBrief pipeline must log enough information to debug pass/skip/topic-shift behavior.

Minimum gate diagnostics:

```text
record_id
decision
route
reason
embedding_model
activebrief_relevance_threshold
pending_topic_relevance_threshold
qa_vector_count
question_vector_count
answer_vector_count
qa_top_count
qa_top_mean
qa_top_scores
qa_score_summary
question_score_summary
answer_score_summary
```

If pending-topic comparison is used, diagnostics must also include:

```text
pending_topic_record_id
pending_topic_top_mean
pending_topic_top_scores
pending_topic_score_summary
```

Logs should not dump full vectors by default.

Logs should make it possible to answer:

```text
Why did this Q/A update the brief?
Why was this Q/A skipped?
Why was a topic shift confirmed?
Which scores caused the decision?
Which model and thresholds were used?
```

9.5. Error handling

If ActiveBrief LLM update fails:

* MemoryRecord durable Q/A remains valid,
* error is logged,
* previous ActiveRetrievalBrief may be copied forward,
* failure must not corrupt memory history.

If reducer or gate fails:

* error is logged,
* the system should prefer safe behavior,
* previous brief should be preserved when possible,
* destructive update must be avoided.

ActiveBrief errors must not block core Memory Recording.

9.6. Non-functional requirements

All non-LLM parts of ActiveBrief must be deterministic for the same inputs and configuration.

This includes:

* sentence/window splitting,
* token estimation,
* vector comparison,
* top-window selection,
* relevance-gate routing,
* contributor-id update rules.

The relevance gate exists for cost control.

Unrelated one-off Q/As should not trigger LLM updates.

Every ActiveRetrievalBrief must be traceable through contributor IDs.

ActiveBrief must remain compact, operational, and query-independent.

9.7. Non-goals

ActiveRetrievalBrief must not:

* replace original MemoryRecord Q/A,
* replace MemoryMerge,
* replace document Retrieval,
* replace A3,
* replace A4,
* become `S_CTX_MD`,
* become final answer text,
* store complete conversation history,
* become a multi-brief topic database,
* summarize documents,
* write durable facts not supported by Q/A,
* import outside knowledge.

9.8. Acceptance criteria

The ActiveRetrievalBrief feature is acceptable when:

* first MemoryRecord creates an initial ActiveRetrievalBrief,
* related follow-up Q/A updates the brief normally,
* unrelated Q/A is skipped,
* skipped Q/A copies previous ActiveBrief forward,
* skipped Q/A is stored as pending topic,
* second related Q/A confirms pending-topic shift,
* topic shift uses update route, not init route,
* topic shift preserves old dominant topic while prioritizing new topic,
* contributor IDs are correct for init, update, skip, and topic-shift routes,
* Black-tag exclusion can avoid polluted briefs through contributor IDs,
* `text-embedding-3-small` is used for gate embeddings,
* thresholds come from runtime configuration,
* logs expose route, reason, scores, thresholds, and model,
* ActiveRetrievalBrief is injected separately into SuperPrompt,
* MemoryMerge uses ActiveBrief only as anti-duplication reference,
* durable MemoryRecord truth is never overwritten by ActiveBrief text.

---

This completes the requirements for ActiveRetrievalBrief in the RAGstream Memory subsystem.

```
```
