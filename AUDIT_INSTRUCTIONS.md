# GHOST StrictDoc Audit Instructions

## 1. Purpose

These instructions define a controlled, file-by-file audit of the GHOST StrictDoc requirements.

Each Codex task audits exactly one specified `.sdoc` file.

The audit has only two goals:

1. Verify that the requirements in the selected StrictDoc file accurately reflect the current implementation, or at minimum do not contradict it.
2. Create a traceability map that assigns every requirement UID in the selected StrictDoc file to one of the three agreed artifact-traceability statuses.

Do not introduce additional audit goals.

---

## 2. Repository Sources

### New StrictDoc requirements

```text
doc/01-Requirements/strictdoc/
````

The target `.sdoc` file will be explicitly named in the individual Codex task.

Audit only that selected StrictDoc file during the task.

### Current Python implementation

```text
ragstream/
```

Inspect all relevant Python files under this directory when determining current implemented behavior.

Follow imports and runtime calls when necessary to understand the actual behavior.

Do not rely only on filenames, comments, class names, method names, or docstrings.

### Runtime JSON sources

Inspect relevant runtime JSON files, especially:

```text
data/agents/**/*.json
ragstream/config/**/*.json
```

Also inspect another JSON file only when current Python code under `ragstream/` demonstrably loads or uses it.

Archived, generated, training-only, or unused JSON files are not current implementation evidence.

### Legacy requirements

```text
doc/01-Requirements/legacy_md/
```

Legacy requirements are secondary evidence only.

Do not perform a complete line-by-line comparison against all legacy requirements.

Consult relevant legacy requirements only when:

* the new requirement and current code appear to disagree;
* the current code is unclear;
* an important behavior may have been lost during migration;
* it is unclear whether a capability is obsolete, postponed, or still intended.

Current executable behavior has priority for claims about what the software does now.

A difference from legacy requirements is not automatically an error because the implementation and product design may have changed.

### Implementation-status document

```text
doc/03-Projekt_Status/RAGstream_Implementation_Status.md
```

Use this document only as supporting evidence when implementation maturity, postponed behavior, disabled behavior, or future intent is unclear.

Verify its claims against current code whenever possible.

### Audit output directory

```text
doc/01-Requirements/strictdoc_audit/
```

### Traceability template

```text
doc/01-Requirements/strictdoc_audit/TRACEABILITY_TEMPLATE.csv
```

Use this template without changing its columns or column order.

The required header is:

```csv
uid,artifact_traceability_status,artifact_name,artifact_path,artifact_type,relationship_explanation
```

---

## 3. Task Boundary

Each Codex task receives exactly one target StrictDoc file.

For example:

```text
doc/01-Requirements/strictdoc/10_orchestrator_and_pipeline.sdoc
```

Audit every normative requirement UID contained in that target file.

Do not audit another StrictDoc file as an additional task.

Another StrictDoc file may be read only when the target file explicitly depends on it and that context is necessary to understand the selected requirement.

Do not modify:

* the target StrictDoc file;
* any other StrictDoc file;
* Python code;
* JSON files;
* legacy requirements;
* the implementation-status document;
* `TRACEABILITY_TEMPLATE.csv`;
* previous audit outputs.

---

## 4. Requirement Audit

For every normative requirement UID in the selected StrictDoc file:

1. Read the complete requirement statement and its surrounding context.
2. Determine what the requirement claims.
3. Locate the relevant current Python or runtime JSON evidence.
4. Inspect the effective behavior rather than relying only on comments or names.
5. Determine whether the requirement:

   * is consistent with the current implementation;
   * is only partially supported;
   * contradicts the current implementation;
   * cannot be determined clearly from available evidence.
6. Consult relevant legacy requirements or the implementation-status document only when necessary.
7. Record exact evidence and reasoning in the audit Markdown file.
8. Assign exactly one traceability status in the traceability CSV.

Use the following audit conclusions:

### `CONSISTENT`

Use when the current implementation supports the requirement, or when a correctly stated future or system-wide requirement does not contradict the current implementation.

### `PARTIAL`

Use when only part of the requirement is supported or implemented.

### `CONTRADICTED`

Use when the current implementation behaves differently from what the requirement states.

### `UNCLEAR`

Use only when the available evidence is insufficient to reach a reliable conclusion.

Do not weaken or reinterpret code evidence merely to protect the requirement.

Do not treat every implementation detail as a missing requirement.

---

## 5. Artifact Definition

For this traceability process, a directly associated artifact may be only:

* one Python file; or
* one JSON file.

The association is made at file level.

Do not use the following as the directly associated artifact:

* an entire directory;
* an entire subsystem;
* several Python files;
* several JSON files;
* a class;
* a method;
* a function;
* a JSON key;
* a test case;
* an architecture document;
* a legacy requirement;
* the implementation-status document.

Symbols, functions, methods, JSON keys, call chains, and additional dependent files may be described in `relationship_explanation`, but they must not become additional artifact rows.

---

## 6. Artifact Traceability Status

Every normative requirement UID must receive exactly one of these three statuses.

### `TRACED`

Use `TRACED` only when there is one clear primary Python file or one clear primary JSON file that directly represents or implements the requirement.

For `TRACED`:

* create exactly one CSV row for the UID;
* provide exactly one artifact;
* fill `artifact_name`;
* fill `artifact_path`;
* fill `artifact_type`;
* explain why this file is the clear primary artifact.

Allowed `artifact_type` values:

```text
PYTHON
JSON
```

Do not select a file merely because it belongs to the same subsystem.

Do not select an arbitrary winner when several files appear equally important.

Additional dependencies may be named only inside `relationship_explanation`.

### `IMPLEMENTATION_PENDING`

Use `IMPLEMENTATION_PENDING` when the requirement expects implementation through a Python or JSON artifact, but no such artifact currently exists.

For `IMPLEMENTATION_PENDING`:

* create exactly one CSV row for the UID;
* leave `artifact_name` empty;
* leave `artifact_path` empty;
* leave `artifact_type` empty;
* explain what implementation is missing;
* state the evidence showing that no current artifact exists.

If the requirement wording incorrectly presents missing behavior as currently implemented, report that contradiction in the audit Markdown file.

### `SYSTEM_WIDE`

Use `SYSTEM_WIDE` when the requirement, by its nature, does not have one clear primary Python or JSON artifact.

This includes broad requirements that apply across the project, across a complete capability, or across several equally relevant implementation files.

For `SYSTEM_WIDE`:

* create exactly one CSV row for the UID;
* leave `artifact_name` empty;
* leave `artifact_path` empty;
* leave `artifact_type` empty;
* explain why no single primary artifact can honestly be selected;
* name relevant related files in `relationship_explanation` when useful.

Do not use `SYSTEM_WIDE` merely because several files are involved.

Use it only when there is genuinely no clear single primary artifact.

---

## 7. Traceability Rules

The traceability CSV must contain exactly one row for every normative requirement UID in the selected StrictDoc file.

A UID must never have several CSV rows.

A UID must never point directly to several artifacts.

For a `TRACED` UID:

* select one clear primary artifact only;
* record its repository-relative path;
* mention secondary dependencies only in the explanation.

For a `SYSTEM_WIDE` UID:

* do not force an arbitrary artifact association;
* describe the relevant implementation scope in the explanation.

For an `IMPLEMENTATION_PENDING` UID:

* do not invent an artifact;
* explain what is absent.

Preserve the UID order used in the target StrictDoc file.

Do not omit a UID because it is difficult to classify.

Do not create new UIDs.

Do not modify existing UIDs.

---

## 8. CSV Content Rules

Use the exact columns from `TRACEABILITY_TEMPLATE.csv`:

```text
uid
artifact_traceability_status
artifact_name
artifact_path
artifact_type
relationship_explanation
```

### `uid`

The exact requirement UID from the target StrictDoc file.

### `artifact_traceability_status`

Exactly one of:

```text
TRACED
IMPLEMENTATION_PENDING
SYSTEM_WIDE
```

### `artifact_name`

For `TRACED`, write the selected file name.

For the other two statuses, leave this field empty.

### `artifact_path`

For `TRACED`, write the exact repository-relative path.

Example format:

```text
ragstream/example/example_file.py
```

For the other two statuses, leave this field empty.

### `artifact_type`

For `TRACED`, use exactly:

```text
PYTHON
```

or:

```text
JSON
```

For the other two statuses, leave this field empty.

### `relationship_explanation`

Write one concise but complete paragraph.

For `TRACED`, explain:

* why the selected file is the clear primary artifact;
* which relevant symbol, function, method, class, JSON section, or behavior supports the mapping;
* any important secondary dependencies.

For `IMPLEMENTATION_PENDING`, explain:

* what artifact or behavior is expected;
* why it is currently missing.

For `SYSTEM_WIDE`, explain:

* why no single primary artifact exists;
* which files or implementation areas are relevant, when applicable.

The explanation must be based on inspected evidence, not generic assumptions.

Use valid CSV quoting when the explanation contains commas, quotation marks, or line-sensitive content.

Keep each CSV record on one physical line.

---

## 9. Required Output Files

For each target StrictDoc file, create exactly two files.

If the target file is:

```text
doc/01-Requirements/strictdoc/<strictdoc_filename>.sdoc
```

create:

```text
doc/01-Requirements/strictdoc_audit/<strictdoc_filename>_AUDIT.md
```

and:

```text
doc/01-Requirements/strictdoc_audit/<strictdoc_filename>_TRACEABILITY.csv
```

Remove only the `.sdoc` extension when constructing the output names.

Do not create:

* `TRACEABILITY_MASTER.csv`;
* `AUDIT_SUMMARY.md`;
* merge scripts;
* validation scripts;
* state files;
* temporary audit files;
* additional CSV files;
* additional Markdown reports;
* modified source files.

---

## 10. Audit Markdown Format

The audit Markdown file must use exactly this structure:

```markdown
# Audit: <target StrictDoc filename>

## Audit Scope

- Target file:
- Repository commit:
- Number of normative requirement UIDs:

## Requirement Reviews

### <UID> — <requirement title>

**Requirement statement**

<exact requirement statement>

**Implementation evidence**

- Python or JSON paths:
- Relevant symbols, functions, methods, classes, keys, or runtime behavior:

**Audit conclusion**

<CONSISTENT, PARTIAL, CONTRADICTED, or UNCLEAR>

**Analysis**

<precise explanation based on evidence>

**Legacy or implementation-status evidence**

<relevant evidence, or "Not consulted">

**Required correction**

<exact correction needed, or "None">

## File Verdict

**Overall result**

<concise overall conclusion>

**Contradictions found**

<list, or "None">

**Partial implementations found**

<list, or "None">

**Unclear requirements**

<list, or "None">
```

Create one `Requirement Reviews` subsection for every normative requirement UID.

Do not omit passing requirements.

Do not write generic statements without exact evidence.

Do not rewrite the requirements inside the audit output except when stating an exact recommended correction.

---

## 11. Execution Discipline

Work only on the target StrictDoc file named in the current Codex task.

Inspect as much current Python and runtime JSON implementation as necessary to audit that file correctly.

Do not continue automatically to the next StrictDoc file.

Do not update audit files created for previous StrictDoc files.

Do not merge traceability files.

Do not perform remediation.

Do not modify requirements or implementation.

Do not create a pull request unless a separate instruction explicitly requests it.

When the two required files have been created, stop.

Your final Codex response must contain only the two created repository-relative file paths, one per line.


```
