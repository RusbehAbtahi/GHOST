# GHOST StrictDoc Audit Instructions

## 1. Purpose

Each Codex task audits exactly one specified `.sdoc` file.

The task has two outputs:

1. a compact audit report containing only problems;
2. one traceability CSV row for every normative UID.

Do not create a long report for requirements that are correct.

---

## 2. Required Sources

### Target StrictDoc file

The Codex task must name exactly one file under:

```text
doc/01-Requirements/strictdoc/
```

Audit only that file.

### Python implementation

```text
ragstream/
```

Use this inventory first:

```text
doc/01-Requirements/strictdoc_audit/00_PYTHON_STRUCTURE_INVENTORY.csv
```

The inventory is a navigation aid. Verify every mapping against the actual Python source.

### Runtime JSON

Inspect relevant runtime JSON under:

```text
data/agents/**/*.json
ragstream/config/**/*.json
```

Use this inventory first:

```text
doc/01-Requirements/strictdoc_audit/00_JSON_STRUCTURE_INVENTORY.csv
```

JSON is supporting evidence. Trace each relevant JSONPath to the Python file that loads or uses it.

Archived, generated, training-only, old-version, or unused JSON is not current implementation evidence.

### Secondary evidence

Use only when necessary:

```text
doc/01-Requirements/legacy_md/
doc/03-Projekt_Status/RAGstream_Implementation_Status.md
README.md
```

Current executable behavior has priority for claims about what the software does now.

---

## 3. Hard Task Boundary

For the selected `.sdoc` file:

- inspect every normative UID;
- do not audit another `.sdoc` file;
- do not modify requirements, Python, JSON, legacy documents, status documents, inventories, or previous audit outputs;
- do not remediate implementation;
- do not create a pull request unless separately requested.

---

## 4. Audit Conclusions

Use exactly one conclusion internally for every UID:

```text
CONSISTENT
PARTIAL
CONTRADICTED
UNCLEAR
```

### `CONSISTENT`

The requirement matches the inspected evidence.

Do not write a Markdown finding for it.

### `PARTIAL`

Only part of the requirement is implemented or supported.

Write a Markdown finding.

### `CONTRADICTED`

The implementation behaves differently from the requirement.

Write a Markdown finding.

### `UNCLEAR`

The available evidence is insufficient for a reliable conclusion.

Write a Markdown finding.

Do not mark a UID `CONSISTENT` merely because no obvious contradiction was found.

---

## 5. Traceability Status

Every normative UID must receive exactly one CSV row and exactly one of these statuses:

```text
TRACED
SYSTEM_WIDE
IMPLEMENTATION_PENDING
```

### `TRACED`

Use when one clear primary Python file owns or directly represents the requirement.

Rules:

- select exactly one Python file;
- use the exact repository-relative path;
- name the exact relevant class, method, function, constant, or runtime behavior in the explanation;
- mention supporting Python files or JSONPaths only when necessary;
- do not create additional rows for supporting artifacts;
- do not choose an arbitrary file when several files are equally important.

### `SYSTEM_WIDE`

Use when no single Python file can honestly own the requirement.

Rules:

- leave artifact fields empty;
- explain what the UID governs or affects;
- name the relevant subsystems, Python files, runtime behaviors, JSON areas, or governance areas;
- explain why one primary Python file cannot be selected;
- do not use generic boilerplate such as “the code does not contradict it.”

### `IMPLEMENTATION_PENDING`

Use only when the requirement expects future or missing implementation and no current Python artifact implements it.

Rules:

- leave artifact fields empty;
- explain what behavior or artifact is missing;
- cite the evidence showing that it is future, planned, postponed, disabled, placeholder, or absent;
- if the requirement incorrectly claims the behavior is current, also create a `PARTIAL` or `CONTRADICTED` Markdown finding.

---

## 6. Primary Artifact Rule

The primary traceability artifact may be only one Python file.

Allowed artifact type:

```text
PYTHON
```

Do not use a JSON file as the primary artifact.

When JSON controls the behavior:

1. identify the exact JSONPath;
2. identify the Python loader or runtime caller;
3. trace the UID to that Python file;
4. mention the JSON file and JSONPath in `relationship_explanation`.

Classes, methods, functions, constants, JSONPaths, tests, call chains, and secondary files belong in the explanation, not in additional rows.

---

## 7. Traceability CSV

Use this template:

```text
doc/01-Requirements/strictdoc_audit/TRACEABILITY_TEMPLATE.csv
```

Do not change the columns or order:

```csv
uid,artifact_traceability_status,artifact_name,artifact_path,artifact_type,relationship_explanation
```

Rules:

- exactly one row for every normative UID;
- preserve UID order from the target `.sdoc`;
- never omit a UID;
- never create a second row for a UID;
- never invent a UID;
- never use a status other than the three allowed statuses;
- keep each CSV record on one physical line;
- use valid CSV quoting.

### For `TRACED`

Fill:

```text
artifact_name
artifact_path
artifact_type = PYTHON
```

The explanation must name the exact relevant symbols and behavior.

### For `SYSTEM_WIDE`

Leave these empty:

```text
artifact_name
artifact_path
artifact_type
```

The explanation must state the affected scope and why no single Python file owns it.

### For `IMPLEMENTATION_PENDING`

Leave these empty:

```text
artifact_name
artifact_path
artifact_type
```

The explanation must state what is missing and why it is classified as pending.

---

## 8. Compact Audit Markdown

The Markdown report contains only alarms:

- `PARTIAL`
- `CONTRADICTED`
- `UNCLEAR`

Do not create a section for a `CONSISTENT` UID.

Use this structure:

```markdown
# Audit Findings: <target StrictDoc filename>

## Audit Scope

- Target file:
- Repository commit:
- Normative UID count:
- CONSISTENT count:
- PARTIAL count:
- CONTRADICTED count:
- UNCLEAR count:

## Findings

### <UID> — <requirement title>

**Conclusion**

<PARTIAL, CONTRADICTED, or UNCLEAR>

**Requirement claim**

<concise statement of the claim>

**Exact evidence**

- <Python path and exact symbol or behavior>
- <supporting JSONPath, test, legacy, status, or README evidence only when needed>

**Why it is not OK**

<precise explanation>

**Required correction**

<exact requirement or implementation correction>

## File Verdict

<short overall verdict>

## No-Finding Statement

All normative UIDs not listed under `Findings` were inspected and classified `CONSISTENT`.
```

Do not copy every full requirement statement into the report.

Do not create repetitive text for passing UIDs.

Do not use generic explanations.

If there are no findings, keep the report short and state that all normative UIDs were inspected and classified `CONSISTENT`.

---

## 9. Required Output Files

For target:

```text
doc/01-Requirements/strictdoc/<name>.sdoc
```

create exactly:

```text
doc/01-Requirements/strictdoc_audit/<name>_AUDIT.md
doc/01-Requirements/strictdoc_audit/<name>_TRACEABILITY.csv
```

Do not create master files, state files, scripts, temporary files, additional reports, or additional CSV files.

---

## 10. Mandatory Validation Before Stopping

Codex must verify:

1. CSV UID count equals the number of normative UIDs in the target `.sdoc`.
2. Every UID appears exactly once.
3. Every status is one of:
   - `TRACED`
   - `SYSTEM_WIDE`
   - `IMPLEMENTATION_PENDING`
4. Every `TRACED` row has:
   - one Python file;
   - `artifact_type = PYTHON`;
   - a non-empty explanation naming exact relevant symbols or behavior.
5. Every `SYSTEM_WIDE` row has empty artifact fields and a concrete affected-scope explanation.
6. Every `IMPLEMENTATION_PENDING` row has empty artifact fields and a concrete missing-implementation explanation.
7. The Markdown report contains no section for any `CONSISTENT` UID.
8. Every `PARTIAL`, `CONTRADICTED`, or `UNCLEAR` UID appears in the Markdown report.
9. No repeated generic explanation is used across unrelated UIDs.
10. No source file or previous audit output was modified.

If any validation fails, correct the two new output files before stopping.

---

## 11. Final Codex Response

After creating and validating the two files, stop.

The final Codex response must contain only the two created repository-relative paths, one per line.
