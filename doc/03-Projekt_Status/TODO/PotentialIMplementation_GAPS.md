# Potential Implementation Gaps for Later Review

## 1. Memory permission and policy enforcement may be incomplete

### Problem

The memory-retrieval path contains configuration concepts such as:

```text
allow_memory_context
memory_context_policy
```

However, the current audit found that these values may not be enforced consistently before memory processing continues.

The possible problem is that GHOST may still:

* retrieve memory candidates,
* compress memory,
* call the MemoryMerge synthesizer,
* create `memory_context_text`,
* assign synthesized memory context to `SuperPrompt`,

even when the current preprocessing or routing policy indicates that memory context should not be used, or should be restricted.

### Why this matters

These fields are intended to control whether memory is allowed to influence the current engineered prompt.

If enforcement happens only partially or too late, memory could be processed or inserted despite the current request’s memory policy.

This is especially important for:

* unrelated prompts,
* prompts that should not reuse historical context,
* future privacy or security controls,
* deterministic control over what information is sent to an external model.

### What must later be checked

Verify the complete call path from preprocessing to memory retrieval and synthesis:

```text
PreProcessing
→ allow_memory_context / memory_context_policy
→ Controller
→ MemoryRetriever
→ MemoryMergeSynthesizer
→ SuperPrompt.memory_context_text
→ SuperPromptProjector
```

The review must determine:

* where the two policy values are created,
* where they are read,
* whether memory retrieval is skipped when forbidden,
* whether synthesis is skipped when forbidden,
* whether previously existing memory context is cleared or preserved,
* whether the final prompt excludes memory when policy forbids it.

**Audit basis:** The traceability audit classified the full memory-permission requirement as implementation-pending because complete enforcement before synthesis and write-back could not be confirmed.

---

## 2. The final ActiveBrief-aware retrieval query may not be rebuilt after classification

### Problem

The retrieval query can initially be created from:

```text
TASK
PURPOSE
CONTEXT
```

Later, the ActiveBrief Relation Classifier determines values such as:

```text
prompt_materiality:
STRONG / WEAK

topic_relation:
SAME_TOPIC / RELATED_DOMAIN / IRRELEVANT
```

These results are intended to change the final document-retrieval query.

Expected routing includes:

```text
STRONG
→ current prompt only

WEAK + SAME_TOPIC
→ current prompt + full ActiveBrief

WEAK + RELATED_DOMAIN
→ current prompt + ActiveBrief title

WEAK + IRRELEVANT
→ empty query / no document retrieval
```

The audit found that the query stored in:

```text
SuperPrompt.effective_retrieval_query_text
```

may still contain an earlier pre-classification version instead of being rebuilt from the final ActiveBrief routing decision.

### Why this matters

The code may contain correct query-building logic in `SuperPromptProjector`, but that does not automatically prove that the final result is written back into the authoritative `SuperPrompt` field before Retrieval begins.

Possible consequences include:

* ActiveBrief content not being included when it should be,
* ActiveBrief content being included when it should not be,
* retrieval using an outdated query,
* retrieval behavior disagreeing with the final routing state,
* `prompt_ready` and the actual retrieval query representing different decisions.

### Related schema-mapping concern

The same audit also reported that some requirement-facing schema fields may not be consistently mapped to their runtime equivalents, particularly mappings such as:

```text
response_depth → depth
output_format  → format
```

This can create multiple representations of the same setting, where preprocessing, A2, runtime state, and final projection do not all use the same field.

### What must later be checked

Trace the exact lifecycle of:

```text
effective_retrieval_query_text
```

Confirm:

1. when it is first created;
2. when ActiveBrief classification finishes;
3. whether it is rebuilt after classification;
4. whether Retrieval uses the rebuilt value;
5. whether `SuperPrompt.body`, routing extras, query text, stage history, and `prompt_ready` remain synchronized.

Also verify whether schema names and runtime field names are mapped once, explicitly, and consistently.

**Audit basis:** The audit states that final routing-aware query reconstruction and some schema-to-runtime field mappings were incomplete at the downstream handoff boundary.

---

## 3. An empty retrieval query may not reliably suppress document retrieval

### Problem

For this routing result:

```text
prompt_materiality = WEAK
topic_relation = IRRELEVANT
```

the intended document-retrieval query is empty.

The empty value is not merely missing input. It is supposed to be a deliberate control signal meaning:

```text
Do not perform document retrieval for this request.
```

The code can produce an empty query for this state, but the audit could not confirm that all downstream execution paths treat it as an explicit skip condition.

The ordinary retrieval path may still:

* validate the query as though a normal query were expected,
* initialize retrieval processing,
* call document retrieval with an empty string,
* raise an avoidable error,
* fall back to another query,
* continue with stale retrieval state from an earlier run.

### Why this matters

An intentional routing decision must be distinguishable from an accidental missing query.

Without an explicit suppression branch, the system may:

* perform irrelevant retrieval,
* waste embedding or retrieval work,
* produce confusing errors,
* reuse stale document evidence,
* behave differently depending on which UI or orchestration path invoked Retrieval.

### What must later be checked

Verify the behavior in:

```text
Controller
Pipeline runner
Retriever entry point
Manual Retrieval button
Prompt Builder execution
MCP or future API paths
```

The desired check is:

```text
if retrieval query is intentionally empty:
    skip document retrieval
    record a clear diagnostic reason
    produce an explicit empty retrieval result
    do not reuse previous document candidates
    allow the remaining legal pipeline behavior to continue
```

The final behavior must also define whether A3 and A4 are skipped when no document candidates exist.

**Audit basis:** The audit found that the projector can represent the empty-routing result, but downstream orchestration does not yet completely enforce it as an early document-retrieval suppression signal.

---

## 4. Runtime tuning parameters are still distributed and not fully governed through validated versioned JSON

### Problem

A number of operational settings for document retrieval, evidence processing, and memory processing still appear to be distributed across:

* Python defaults,
* constructors,
* local constants,
* session-state defaults,
* individual JSON files,
* fallback values inside implementation modules.

The requirements expect important tuning parameters to be moved into a controlled configuration system with:

```text
versioned JSON
validation
defined defaults
one clear authority
runtime consumption
effective-value observability
```

The audit found that this migration is incomplete in several areas.

### Affected configuration areas may include

#### Document retrieval

* retrieval limits,
* dense/sparse weighting,
* similarity floors,
* SPLADE activation,
* reranker activation,
* Top-K values,
* retrieval-stage thresholds.

#### Evidence selection and condensation

* A3 usefulness thresholds,
* A3 selection limits,
* A4 group sizes,
* token budgets,
* active evidence classes,
* model and version selection,
* optional-stage settings.

#### Memory ingestion and retrieval

* chunk sizes,
* overlap or grouping rules,
* semantic and episodic limits,
* recency weights,
* scoring weights,
* candidate budgets,
* compression limits,
* memory retrieval thresholds.

#### Memory merge and ActiveBrief

* synthesis budgets,
* relevance thresholds,
* minimum evidence,
* maximum output lengths,
* ActiveBrief length limits,
* agent identities and versions,
* window relationships.

### Why this matters

When values are spread across Python and JSON, it becomes difficult to know:

* which value is authoritative,
* which fallback actually runs,
* whether an invalid combination is accepted,
* whether local and AWS execution use the same configuration,
* which settings produced a particular result,
* whether changing a JSON file truly changes runtime behavior.

This also weakens future:

* reproducibility,
* benchmarking,
* auditing,
* CI validation,
* requirement-to-code traceability,
* agent-driven synchronization.

### What must later be checked

Create an inventory for each relevant parameter:

```text
parameter name
current location
current default
current consumer
required validation
effective runtime value
planned authoritative JSON path
```

Then determine which parameters genuinely need migration and which values should remain code-level constants.

The configuration system should eventually detect invalid combinations such as:

* negative limits,
* zero token budgets,
* weights outside allowed ranges,
* minimum values greater than maximum values,
* missing required agent IDs,
* nonexistent agent versions,
* incompatible window sizes,
* enabled stages without required configuration.

**Audit basis:** The audit identified incomplete configuration migration and validation across Knowledge Management, evidence processing, memory ingestion/retrieval, and memory transformation.

---

## Current Classification

```text
1. Memory permission enforcement
   Medium ticket — requires call-path verification and likely focused corrections.

2. ActiveBrief-aware query finalization
   Medium-to-major ticket — affects preprocessing, routing, SuperPrompt consistency, and retrieval handoff.

3. Empty-query retrieval suppression
   Small-to-medium ticket — probably limited implementation work, but requires full-path regression tests.

4. Versioned JSON configuration migration
   Major refactoring topic — should probably be divided into separate document, evidence, and memory tickets.
```

These items should first be verified against the actual runtime call paths before being converted into implementation tickets.
