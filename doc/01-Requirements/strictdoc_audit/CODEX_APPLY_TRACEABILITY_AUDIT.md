# Codex Task — Apply Final Traceability Corrections

## Goal

Apply exactly the 257 CSV-row corrections listed in:

`doc/01-Requirements/strictdoc_audit/FINAL_TRACEABILITY_AUDIT_REPORT.md`

The report is the sole authority for this task.

Do not perform a new audit.
Do not reinterpret the findings.
Do not add your own corrections.

## Strict Change Boundary

Modify only the 257 UIDs explicitly listed in the report.

Do not modify any other row or file.

Only these nine CSV files may be changed:

- `doc/01-Requirements/strictdoc_audit/00_ghost_srs_TRACEABILITY.csv`
- `doc/01-Requirements/strictdoc_audit/10_orchestrator_and_pipeline_TRACEABILITY.csv`
- `doc/01-Requirements/strictdoc_audit/30_preprocessing_prompt_functions_TRACEABILITY.csv`
- `doc/01-Requirements/strictdoc_audit/40_knowledge_management_TRACEABILITY.csv`
- `doc/01-Requirements/strictdoc_audit/43_evidence_selection_and_condensation_TRACEABILITY.csv`
- `doc/01-Requirements/strictdoc_audit/50_memory_management_TRACEABILITY.csv`
- `doc/01-Requirements/strictdoc_audit/51_memory_recording_and_files_TRACEABILITY.csv`
- `doc/01-Requirements/strictdoc_audit/52_memory_ingestion_and_retrieval_TRACEABILITY.csv`
- `doc/01-Requirements/strictdoc_audit/53_memory_merge_activebrief_blackboard_TRACEABILITY.csv`

Do not modify:

- any unlisted CSV row
- any `.sdoc` file
- any Python file
- any JSON file
- any other documentation
- the audit report
- this instruction file
- the three CSV files marked `FINAL OK`

The following files must remain unchanged:

- `20_agent_stack_TRACEABILITY.csv`
- `41_document_ingestion_TRACEABILITY.csv`
- `42_document_retrieval_and_reranking_TRACEABILITY.csv`

## Required Changes

For every UID listed in the audit report:

1. Find the exact UID in the stated CSV file.
2. Apply the corrected status from the report.
3. Apply the exact artifact filename and path from the report.
4. Apply the exact corrected relationship explanation from the report.
5. Preserve the UID and row position.
6. Do not change any unlisted row.

For corrected `TRACED` rows:

- set `artifact_traceability_status` to `TRACED`
- set `artifact_name` to the exact Python filename from the report
- set `artifact_path` to the exact Python path from the report
- set `artifact_type` to `PYTHON`
- use the exact corrected explanation from the report

For corrected `SYSTEM_WIDE` rows:

- set `artifact_traceability_status` to `SYSTEM_WIDE`
- clear `artifact_name`
- clear `artifact_path`
- clear `artifact_type`
- use the exact corrected explanation from the report

For corrected `IMPLEMENTATION_PENDING` rows:

- set `artifact_traceability_status` to `IMPLEMENTATION_PENDING`
- clear `artifact_name`
- clear `artifact_path`
- clear `artifact_type`
- use the exact corrected explanation from the report

When the report groups several UIDs under one correction, apply that correction separately to every listed UID.

Do not paraphrase or improve the explanations.

## Required Row Counts

The exact number of modified rows must be:

- `00_ghost_srs_TRACEABILITY.csv`: 12
- `10_orchestrator_and_pipeline_TRACEABILITY.csv`: 10
- `30_preprocessing_prompt_functions_TRACEABILITY.csv`: 15
- `40_knowledge_management_TRACEABILITY.csv`: 9
- `43_evidence_selection_and_condensation_TRACEABILITY.csv`: 8
- `50_memory_management_TRACEABILITY.csv`: 8
- `51_memory_recording_and_files_TRACEABILITY.csv`: 85
- `52_memory_ingestion_and_retrieval_TRACEABILITY.csv`: 99
- `53_memory_merge_activebrief_blackboard_TRACEABILITY.csv`: 11

Total: exactly 257 modified rows.

If the total is not exactly 257, stop and report the mismatch.

## Validation

Before committing, verify:

- exactly 257 listed rows were modified
- the per-file counts match the values above
- every listed UID exists exactly once
- no unlisted UID was modified
- no row was added, deleted, reordered, or renamed
- CSV headers and column order remain unchanged
- only the nine permitted CSV files were modified
- all other repository files remain unchanged
- every corrected `TRACED` row has complete artifact fields
- every corrected non-`TRACED` row has blank artifact fields
- all CSV files remain valid and parseable

If any validation fails, do not commit.

## Commit

After validation succeeds, commit only the nine modified CSV files.

Commit message:

`Apply final traceability audit corrections`

## Final Response

Report:

- success or failure
- total modified rows
- modified-row count for each CSV
- confirmation that no unlisted row was changed
- confirmation that no other file was changed
- validation result
- commit hash