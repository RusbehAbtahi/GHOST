# Audit Findings: 52_memory_ingestion_and_retrieval.sdoc

## Audit Scope

- Target file: doc/01-Requirements/strictdoc/52_memory_ingestion_and_retrieval.sdoc
- Repository commit: 9f432457493a7539848d0769502b8a74e65f3206
- Normative UID count: 217
- CONSISTENT count: 216
- PARTIAL count: 1
- CONTRADICTED count: 0
- UNCLEAR count: 0

## Findings

### GHOST-MEM-IR-AC-PERMISSION — AC: Memory Context Permission

**Conclusion**

PARTIAL

**Requirement claim**

When PreProcessing sets allow_memory_context false, the final SuperPrompt shall not receive synthesized memory context for that request.

**Exact evidence**

- `ragstream/retrieval/retriever_mem.py`: `MemoryRetriever.run()` builds and writes memory artifacts through `_write_to_superprompt()`.
- `ragstream/preprocessing/activebrief_relation_classifier.py`: `ActiveBriefRelationDecision` carries `allow_memory_context` and `memory_context_policy`, including disabled decisions for irrelevant prompts; `ragstream/orchestration/super_prompt.py` carries `memory_context_text` and `memory_context_pack`.

**Why it is not OK**

Memory context permission is claimed for final SuperPrompt write-back, but MemoryRetriever.run does not inspect allow_memory_context before _write_to_superprompt writes memory_context_text and memory_context_pack.

**Required correction**

Either add an executable guard preventing memory-context write-back when the request disallows memory context, or revise the requirement to name the component that enforces the permission and limit this UID to that component.

## File Verdict

The file was audited against the current Python memory implementation and relevant runtime JSON. Findings above are limited to non-CONSISTENT UIDs.

## No-Finding Statement

All normative UIDs not listed under `Findings` were inspected and classified `CONSISTENT`.
