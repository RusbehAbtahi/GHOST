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
````

Audit only that file.

### Python implementation

```text
ragstream/
```

Use this inventory first:

```text
doc/01-Requirements/strictdoc_audit/00_PYTHON_STRUCTURE_INVENTORY.csv
```

The inventory is a navigation aid only.

Verify every mapping against the actual Python source.

Do not assume ownership from:

* filenames;
* class names;
* function names;
* imports;
* call sites;
* comments;
* docstrings;
* architectural importance.

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

JSON is supporting evidence.

Trace each relevant JSONPath to the Python file that loads, interprets, or uses it.

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

* inspect every normative UID;
* do not audit another `.sdoc` file;
* do not modify requirements;
* do not modify Python;
* do not modify JSON;
* do not modify legacy documents;
* do not modify status documents;
* do not modify inventories;
* do not modify previous audit outputs;
* do not remediate implementation;
* do not create a pull request unless separately requested.

---

## 4. Requirement Audit Conclusions

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

A requirement that explicitly and correctly describes functionality as future, postponed, placeholder, optional, or partial is not incorrect merely because that functionality is incomplete.

---

## 5. Traceability Status

Every normative UID must receive exactly one CSV row and exactly one of these statuses:

```text
TRACED
SYSTEM_WIDE
IMPLEMENTATION_PENDING
```

Audit conclusion and traceability status are separate decisions.

A requirement may be:

* `CONSISTENT` and `TRACED`;
* `CONSISTENT` and `SYSTEM_WIDE`;
* `CONSISTENT` and `IMPLEMENTATION_PENDING`;
* `PARTIAL`, `CONTRADICTED`, or `UNCLEAR` with any traceability status supported by the evidence.

---

## 6. `TRACED`

Use `TRACED` only when one clear primary Python file owns the full normative scope of the UID.

The selected Python file must implement or directly represent the complete central responsibility stated by the requirement.

It is not enough that the file:

* is an entry point;
* coordinates other components;
* constructs subsystem objects;
* calls several other owners;
* represents only one important part;
* belongs to the same subsystem;
* is the most visible file;
* contains a convenient class name;
* is the closest available approximation.

### Full-Scope Ownership Test

Before assigning `TRACED`, answer:

> Does this one Python file own the full central behavior required by this UID?

Use `TRACED` only when the answer is clearly yes.

Supporting files are allowed only when their roles are subordinate dependencies of the selected primary owner.

If two or more independent Python files own different essential parts of the requirement, the UID is not `TRACED`.

Use `SYSTEM_WIDE` instead.

### `TRACED` Rules

For `TRACED`:

* select exactly one Python file;
* use the exact repository-relative path;
* set `artifact_name` to the actual filename from `artifact_path`;
* set `artifact_type` to `PYTHON`;
* name the exact relevant class, method, function, constant, or runtime behavior;
* mention supporting Python files or JSONPaths only when necessary;
* explain why the selected file owns the complete central requirement;
* do not create additional rows for supporting artifacts.

Example:

```text
artifact_name = controller.py
artifact_path = ragstream/app/controller.py
artifact_type = PYTHON
```

Do not write a class or function name in `artifact_name`.

Incorrect:

```text
artifact_name = AppController
artifact_name = run_prompt_builder_stage
```

Correct:

```text
artifact_name = controller.py
artifact_name = pipeline_runner.py
```

---

## 7. `SYSTEM_WIDE`

Use `SYSTEM_WIDE` when no single Python file owns the full normative scope.

Use it when:

* several independent Python files own different essential parts;
* the UID governs an entire capability spanning several implementations;
* the UID is architectural, operational, governance-related, deployment-wide, or cross-cutting;
* one file coordinates the behavior but does not implement the complete behavior;
* selecting one file would hide equally important implementation owners;
* the requirement describes an absence, boundary, or project-wide constraint rather than one implementation unit.

Do not force a representative Python file merely to reduce the number of `SYSTEM_WIDE` rows.

### `SYSTEM_WIDE` Rules

For `SYSTEM_WIDE`:

* leave `artifact_name` empty;
* leave `artifact_path` empty;
* leave `artifact_type` empty;
* explain what the UID governs or affects;
* name the relevant subsystems, Python files, runtime behaviors, JSON areas, deployment areas, or governance areas;
* explain why no single Python file owns the full requirement.

Do not use generic boilerplate such as:

```text
The code does not contradict this requirement.
```

---

## 8. `IMPLEMENTATION_PENDING`

Use `IMPLEMENTATION_PENDING` only when the requirement expects future or missing implementation and no current Python artifact implements it.

Use it when the capability is demonstrably:

* future;
* planned;
* postponed;
* disabled;
* placeholder;
* reserved;
* absent.

### `IMPLEMENTATION_PENDING` Rules

For `IMPLEMENTATION_PENDING`:

* leave `artifact_name` empty;
* leave `artifact_path` empty;
* leave `artifact_type` empty;
* explain what behavior or artifact is missing;
* cite evidence showing that it is future, planned, postponed, disabled, placeholder, reserved, or absent.

If the requirement incorrectly describes missing behavior as current, also create a `PARTIAL` or `CONTRADICTED` Markdown finding.

---

## 9. Primary Artifact Rule

The primary traceability artifact may be only one Python file.

Allowed artifact type:

```text
PYTHON
```

Do not use a JSON file as the primary artifact.

When JSON controls behavior:

1. identify the exact JSONPath;
2. identify the Python loader, interpreter, or runtime caller;
3. determine whether that Python file owns the full UID scope;
4. use `TRACED` only when it owns the full scope;
5. otherwise use `SYSTEM_WIDE`;
6. mention the JSON file and JSONPath in `relationship_explanation`.

Classes, methods, functions, constants, JSONPaths, tests, call chains, and secondary files belong in the explanation, not in additional rows.

---

## 10. Relationship Explanation Rules

The explanation must be consistent with the selected status.

### For `TRACED`

The explanation must:

* identify the exact owner file;
* identify exact symbols or behavior;
* explain why the file owns the full central UID scope;
* describe supporting files only as subordinate dependencies.

A `TRACED` explanation must not say or imply:

* no single file owns the requirement;
* the behavior is owned elsewhere;
* essential parts belong to independent files;
* the selected file covers only part of the requirement;
* deployment or governance owns the real behavior;
* the selected file is merely a representative or entry point.

If the explanation contains such meaning, the status must be `SYSTEM_WIDE`.

### For `SYSTEM_WIDE`

The explanation must:

* describe the complete affected scope;
* name the main implementation areas;
* explain why no single file owns the full UID.

### For `IMPLEMENTATION_PENDING`

The explanation must:

* identify the missing behavior;
* identify evidence of future, postponed, placeholder, disabled, or absent status.

Do not reuse identical generic explanations across unrelated UIDs.

---

## 11. Traceability CSV

Use this template:

```text
doc/01-Requirements/strictdoc_audit/TRACEABILITY_TEMPLATE.csv
```

Do not change the columns or order:

```csv
uid,artifact_traceability_status,artifact_name,artifact_path,artifact_type,relationship_explanation
```

Rules:

* exactly one row for every normative UID;
* preserve UID order from the target `.sdoc`;
* never omit a UID;
* never create a second row for a UID;
* never invent a UID;
* never use a status other than the three allowed statuses;
* keep each CSV record on one physical line;
* use valid CSV quoting.

### For `TRACED`

Fill:

```text
artifact_name
artifact_path
artifact_type = PYTHON
```

`artifact_name` must equal the filename at the end of `artifact_path`.

Example:

```text
artifact_name = controller.py
artifact_path = ragstream/app/controller.py
```

### For `SYSTEM_WIDE`

Leave these empty:

```text
artifact_name
artifact_path
artifact_type
```

### For `IMPLEMENTATION_PENDING`

Leave these empty:

```text
artifact_name
artifact_path
artifact_type
```

---

## 12. Compact Audit Markdown

The Markdown report contains only alarms:

* `PARTIAL`
* `CONTRADICTED`
* `UNCLEAR`

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

## 13. Required Output Files

For target:

```text
doc/01-Requirements/strictdoc/<name>.sdoc
```

create exactly:

```text
doc/01-Requirements/strictdoc_audit/<name>_AUDIT.md
doc/01-Requirements/strictdoc_audit/<name>_TRACEABILITY.csv
```

Do not create:

* master traceability files;
* state files;
* validation scripts;
* temporary files;
* additional reports;
* additional CSV files;
* modified source files.

---

## 14. Mandatory Validation Before Stopping

Codex must verify:

1. CSV UID count equals the number of normative UIDs in the target `.sdoc`.
2. Every UID appears exactly once.
3. Every status is one of:

   * `TRACED`
   * `SYSTEM_WIDE`
   * `IMPLEMENTATION_PENDING`
4. Every `TRACED` row has:

   * exactly one Python path;
   * `artifact_type = PYTHON`;
   * `artifact_name` equal to the filename from `artifact_path`;
   * a non-empty explanation naming exact relevant symbols or behavior.
5. Every `TRACED` file owns the full central scope of the UID.
6. No `TRACED` explanation states or implies that:

   * no single file owns the requirement;
   * essential behavior belongs to independent files;
   * the selected file owns only part of the UID;
   * deployment, governance, or another subsystem owns the actual behavior.
7. When several independent files own essential parts of a UID, the status is `SYSTEM_WIDE`.
8. Every `SYSTEM_WIDE` row has:

   * empty artifact fields;
   * a concrete affected-scope explanation;
   * named relevant implementation areas when available.
9. Every `IMPLEMENTATION_PENDING` row has:

   * empty artifact fields;
   * a concrete missing-implementation explanation;
   * evidence of future, planned, postponed, disabled, placeholder, reserved, or absent status.
10. The Markdown report contains no section for any `CONSISTENT` UID.
11. Every `PARTIAL`, `CONTRADICTED`, or `UNCLEAR` UID appears in the Markdown report.
12. A correctly stated future or partial requirement is not falsely reported as a defect merely because implementation is incomplete.
13. No repeated generic explanation is used across unrelated UIDs.
14. No source file or previous audit output was modified.

If any validation fails, correct the two new output files before stopping.

---

## 15. Final Codex Response

After creating and validating the two files, stop.

The final Codex response must contain only the two created repository-relative paths, one per line.

