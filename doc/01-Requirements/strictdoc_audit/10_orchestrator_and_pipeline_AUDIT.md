# Audit Findings: 10_orchestrator_and_pipeline.sdoc

## Audit Scope

- Target file: `doc/01-Requirements/strictdoc/10_orchestrator_and_pipeline.sdoc`
- Repository commit: `b039a53354f49405139ba52d8816466b1015420d`
- Normative UID count: 77
- CONSISTENT count: 74
- PARTIAL count: 3
- CONTRADICTED count: 0
- UNCLEAR count: 0

## Findings

### GHOST-ORCH-PREPROCESS-QUERY-ROUTING — Retrieval Routing Preparation

**Conclusion**

PARTIAL

**Requirement claim**

Preprocessing shall prepare routing information used later to build retrieval intent, allowing current prompt text, ActiveBrief body, ActiveBrief title, or empty document retrieval intent depending on materiality and topic relation.

**Exact evidence**

- `ragstream/preprocessing/preprocessing.py` builds `sp.effective_retrieval_query_text` directly from TASK/PURPOSE/CONTEXT before ActiveBrief relation decisions are incorporated. 【F:ragstream/preprocessing/preprocessing.py†L168-L175】
- `ragstream/preprocessing/activebrief_relation_classifier.py` writes materiality/topic routing decisions and ActiveBrief snapshots into `sp.extras`, including `use_activebrief_for_retrieval` decisions. 【F:ragstream/preprocessing/activebrief_relation_classifier.py†L281-L300】【F:ragstream/preprocessing/activebrief_relation_classifier.py†L361-L418】

**Why it is not OK**

The relation classifier stores routing metadata, but current effective document-retrieval query construction does not use those decisions to switch among current prompt text, ActiveBrief body, ActiveBrief title, or empty intent. The implemented query path is therefore only partially aligned with the UID.

**Required correction**

Either update the requirement to state that ActiveBrief-aware document retrieval intent is not yet implemented, or update executable preprocessing/retrieval-query construction to consume the relation decision when producing document retrieval intent.

### GHOST-ORCH-MEMORY-EMPTY-PACK — Empty Memory Pack Behavior

**Conclusion**

PARTIAL

**Requirement claim**

When memory retrieval is disabled, no active memory file exists, or query text is empty, the Memory Management path shall write an empty `MemoryContextPack` with diagnostics rather than fabricating memory context.

**Exact evidence**

- `ragstream/retrieval/retriever_mem.py` returns the unchanged SuperPrompt when `config.enabled` is false. 【F:ragstream/retrieval/retriever_mem.py†L97-L99】
- The same method writes an empty pack for no active memory file and empty query text. 【F:ragstream/retrieval/retriever_mem.py†L101-L109】

**Why it is not OK**

The no-active-file and empty-query branches satisfy the empty-pack behavior, but the disabled-memory branch exits without writing an empty pack or diagnostics. The UID covers all three conditions, so current executable behavior is incomplete.

**Required correction**

Either change the disabled-memory branch to call `_write_empty_pack(sp, reason="disabled")`, or revise the requirement to exclude disabled memory retrieval from the empty-pack write-back contract.

### GHOST-ORCH-COMPOSE-OUTPUT — Prompt Ready Output Contract

**Conclusion**

PARTIAL

**Requirement claim**

Final composition shall write rendered strings into `System_MD`, `Prompt_MD`, `S_CTX_MD`, `Attachments_MD` where used, and `prompt_ready`, with `prompt_ready` as the final Prompt Builder output presented to the user.

**Exact evidence**

- `ragstream/orchestration/superprompt_projector.py` writes `System_MD`, `Prompt_MD`, and `prompt_ready`, and appends `Attachments_MD` only if already present. 【F:ragstream/orchestration/superprompt_projector.py†L203-L223】
- `ragstream/agents/a4_det_processing.py` writes `sp.S_CTX_MD` during A4 finalization, not inside the final composition method itself. 【F:ragstream/agents/a4_det_processing.py†L388-L402】

**Why it is not OK**

The current final projection does assemble `prompt_ready`, but it does not itself write all listed rendered-string fields. `S_CTX_MD` is independently owned by A4 finalization, and `Attachments_MD` is only consumed as an existing field. The UID overstates the current central composition owner.

**Required correction**

Either revise the requirement to say final composition consumes `S_CTX_MD` and optional `Attachments_MD` while writing `System_MD`, `Prompt_MD`, and `prompt_ready`, or consolidate those rendered-string writes under the final composition path.

## File Verdict

The orchestrator requirements are largely consistent with the current executable Prompt Builder path through A4, but three UIDs overstate current routing, disabled-memory diagnostics, or final rendering ownership.

## No-Finding Statement

All normative UIDs not listed under `Findings` were inspected and classified `CONSISTENT`.
