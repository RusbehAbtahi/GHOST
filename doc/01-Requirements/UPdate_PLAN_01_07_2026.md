````markdown
# GHOST / RAGstream StrictDoc Requirement Migration — Conversation Summary and Final Implementation Plan

## 1. Core Objective

The current work is about modernizing the GHOST / RAGstream requirement system.

The goal is not simply to convert existing Markdown files into StrictDoc.

The real goal is to design a new, modern, professional requirement structure from first principles, using StrictDoc `.sdoc` files as the future requirement source of truth.

This new structure should support:

- stable requirement IDs
- requirement hierarchy
- functional capability mapping
- traceability to architecture / UML
- traceability to Python implementation units
- future GitHub Agent audits
- future GHOST requirement-code synchronization agents
- professional requirement governance
- machine-readable JSON export
- human-controlled review and approval

The new requirement tree should not be a copy of:

- the old Markdown file structure
- the Python project folder tree
- the earlier dummy `strictdoc/srs/...` suggestion

The new tree should be designed deliberately around GHOST’s future functional capability model.

---

## 2. Important Clarification About the Earlier Suggested Tree

Earlier, this tree was suggested:

```text
strictdoc/
  srs/
    ghost_srs.sdoc
    rag_pipeline.sdoc
    agent_stack.sdoc
    orchestration_controller.sdoc
    gui.sdoc
    document_ingestion.sdoc
    memory_recording.sdoc
    memory_ingestion.sdoc
    memory_retrieval.sdoc
    quality_governance.sdoc
    aws_deployment.sdoc
````

This was confirmed to be only a dummy / first skeleton suggestion.

It was reasonable because it was based on the current requirement modules, but it is not final and must not be treated as binding.

The final plan is to create a new tree from zero, probably with new names, based on a better future capability structure.

Especially these items may need different placement:

```text
quality_governance.sdoc
aws_deployment.sdoc
```

because they are more cross-cutting / operational than normal SRS functional modules.

---

## 3. StrictDoc Decision

StrictDoc is accepted as the requirement-management foundation for this phase.

The reasoning established in the conversation:

* `.sdoc` is suitable for structured requirements.
* `.sdoc` is better than plain Markdown for stable IDs, traceability, relation modeling, and validation.
* Markdown is easier for loose writing, but not ideal as source of truth.
* StrictDoc JSON export may be enough for machine / AI / audit use.
* Markdown export can be postponed.
* Bidirectional Markdown ↔ StrictDoc sync should not be built early because it risks creating two competing truths.

Final rule:

```text
.sdoc = source of truth after explicit cutover
JSON = machine / audit / export view
Markdown = optional derived view later, only if needed
```

---

## 4. Current Markdown Requirement Files

The current project has many Markdown requirement and architecture files, including:

```text
Requirements_Main.md
Requirements_RAG_Pipeline.md
Requirements_GUI.md
Requirements_AgentStack.md
Requirements_Orchestration_Controller.md
Requirements_Quality_Governance.md
Requirements_Memory_Recording.md
Requirements_Memory_Ingestion.md
Requirements_Memory_Retrieval.md
Requirements_Document_Ingestion.md
Architecture.md
Architecture_Memory.md
RAGstream_AWS_Deployment_Guide_v02.md
RAGstream_Implementation_Status.md
UML_*.txt
Project_Tree.md
ragstream_python.md
```

These files are currently important evidence and migration input.

However, after explicit migration approval, the plan is:

```text
StrictDoc .sdoc files become the new requirement source of truth.
Old Markdown files become archived, historical, or derived views.
```

There must be an explicit source-of-truth cutover. It must not happen silently.

---

## 5. Requirement Tree Philosophy

The new requirement tree must mirror the functional capability map of GHOST.

It must not mirror the Python project tree.

Reason:

* Project tree only says where code lives.
* Requirement tree says what the system must do.
* Code can move; requirement meaning should remain stable.
* Future synchronization needs stable requirement IDs independent of folder reshuffling.

The user’s important idea:

```text
Every meaningful Python implementation unit should eventually map to one parent functional capability.
```

This parent capability belongs to the requirement / functional capability map, not to the project folder tree.

Security, governance, compliance, observability, and deployment are cross-cutting or operational concerns. They should not automatically become normal functional parents unless deliberately designed that way.

---

## 6. Requirement Levels Discussed

The conversation separated two ideas:

### 6.1 Document / requirement levels

```text
BRS  = Business Requirements Specification
StRS = Stakeholder Requirements Specification
SyRS = System Requirements Specification
SRS  = Software Requirements Specification
```

For GHOST, the current work is mainly around a structured SRS / software requirement model, but higher-level business and stakeholder intent can also be captured where useful.

### 6.2 Classic SRS internal structure

Classic SRS structure:

```text
Introduction
Overall Description
Specific Requirements
```

A root SRS file can follow this structure.

Real GHOST capability branches belong mainly under:

```text
Specific Requirements
```

The exact file split is flexible. Standards define logical structure, not necessarily one physical file.

---

## 7. UID / Requirement ID Policy

Stable IDs are central.

The ID must be a stable address, not a semantic sentence.

Good style:

```text
GHOST-SRS-RAG-001
GHOST-SRS-MEM-010
GHOST-SRS-GUI-003
```

Bad style:

```text
GHOST-SRS-MEM-ACTIVE-BRIEF
```

because names and concepts may evolve, but IDs should remain stable.

Final UID rule:

```text
UID = stable address
TITLE = human-readable meaning
```

StrictDoc auto-UID can be used only as a helper for missing IDs.

It must not be used blindly.

Correct policy:

```text
Define UID prefixes first.
Assign IDs according to GHOST UID policy.
Use StrictDoc auto-UID only as helper.
Review generated IDs.
Freeze accepted UIDs.
Never renumber frozen IDs.
Deprecated requirements keep their IDs.
```

Possible UID prefix style:

```text
GHOST-SRS-ROOT-###
GHOST-SRS-RAG-###
GHOST-SRS-AGT-###
GHOST-SRS-CTL-###
GHOST-SRS-GUI-###
GHOST-SRS-DOC-###
GHOST-SRS-MREC-###
GHOST-SRS-MING-###
GHOST-SRS-MRET-###
GHOST-SRS-GOV-###
GHOST-SRS-OPS-###
```

But these are examples only. Final prefixes must be defined during Step 0.

---

## 8. Requirement Grammar / Schema

A GHOST-specific requirement grammar should be defined before migration.

Minimum useful fields:

```text
UID
TITLE
STATEMENT
RATIONALE
STATUS
PRIORITY
TYPE
VERIFICATION_METHOD
IMPLEMENTATION_STATUS
SOURCE
RELATIONS
```

Possible `TYPE` values:

```text
Functional
NonFunctional
Interface
Constraint
Data
Operational
Governance
```

Possible `STATUS` values:

```text
Draft
Active
Deprecated
Rejected
```

Possible `IMPLEMENTATION_STATUS` values:

```text
Implemented
PartiallyImplemented
Planned
Gap
Obsolete
```

This schema must be decided before creating serious `.sdoc` files.

---

## 9. Relation Policy

Relation types must be defined before migration.

Start simple.

Recommended initial relation concepts:

```text
Parent / Refines
Implemented by / File
Verified by test / File
Related to
Depends on
```

Do not create too many relation types too early.

Important traceability model:

```text
Requirement = behavioral truth
Architecture = narrative design explanation
UML = structural / component / class truth
Code = implementation evidence
Tests = verification evidence
```

Future full traceability target:

```text
requirement ↔ architecture/UML ↔ code ↔ test
```

Not only:

```text
requirement ↔ code
```

---

## 10. Migration Must Be Semantic, Not Mechanical

The migration from Markdown to StrictDoc must not be:

```text
Markdown heading → StrictDoc section
Paragraph → requirement
```

That would be too shallow.

Correct migration:

```text
existing requirement intent
→ atomic requirement
→ stable UID
→ title
→ statement
→ rationale/source if needed
→ relation to parent capability
→ status
→ implementation status
```

The current Markdown files are input material, not final structure.

The migration should preserve source/origin information.

A migration map should be created:

```text
old_file
old_heading
old_text_hash
new_sdoc_file
new_UID
migration_note
```

This protects traceability from the old requirement system to the new one.

---

## 11. Source-of-Truth Cutover

This is a critical missing link that must be included.

Current state:

```text
Markdown requirement files are still the project requirement source of truth.
```

Future state:

```text
StrictDoc .sdoc files become the requirement source of truth.
```

This transition must be explicit.

Cutover rule:

```text
After migration approval:
.sdoc becomes requirement source of truth.
Old Markdown becomes archived or generated read-only view.
```

Without this, the project would have two competing truths.

---

## 12. JSON and Markdown Export Policy

The current likely direction:

```text
StrictDoc JSON is enough for machine / AI / audit use.
```

Markdown export may be postponed.

Final current export policy:

```text
.sdoc = source of truth
JSON = machine/audit/export view
Markdown = optional derived view later
```

The earlier step about Python helper should be softened.

Instead of:

```text
StrictDoc JSON → Markdown
Markdown → StrictDoc
```

Better current version:

```text
Optional later helper:
StrictDoc JSON → clean Markdown for AI/RAG use, if needed.
Markdown → StrictDoc only if a real need appears.
```

Do not build bidirectional Markdown sync early.

---

## 13. GitHub Agent Audit Concept

The GitHub Agent should not modify requirements at first.

Initial GitHub Agent role:

```text
read-only audit
```

It compares:

```text
code ↔ StrictDoc requirements ↔ architecture/UML
```

Expected audit output:

```text
Requirement ID
Expected behavior
Linked architecture/UML item
Linked code file/function/class
Evidence found
Mismatch found
Missing implementation
Possible obsolete code
Suggested action
Confidence
```

Important rule:

```text
GitHub Agent proposes.
Human decides.
StrictDoc changes only after human approval.
```

No automatic requirement rewriting at first.

---

## 14. Human Review Rule

The human maintainer remains final authority.

Audit findings are suggestions, not truth.

Correct governance:

```text
Agent detects possible mismatch.
Agent writes evidence report.
Human reviews.
Human accepts/rejects.
Only accepted changes update .sdoc.
```

This preserves control and avoids destructive automated synchronization.

---

## 15. CI / Validation Plan

Before real sync agents exist, validation must be added.

Validation should check:

```text
StrictDoc validation passes
JSON export succeeds
no duplicate UIDs
no missing mandatory fields
no broken relations
no circular parent chains
no orphan detailed requirements
code/file relations resolve where expected
requirement-code references follow policy
```

Later, these checks can be added into GitHub Actions.

CI should first validate the requirement system before any sync automation becomes serious.

---

## 16. Code Annotation / Code Trace Policy

Before GitHub audit, define how code will reference requirement IDs.

Possible styles:

```text
# REQ: GHOST-SRS-RAG-004
# REQ: GHOST-SRS-CTL-002
```

or in docstrings:

```text
Implements:
- GHOST-SRS-RAG-004
- GHOST-SRS-CTL-002
```

But do not annotate every tiny helper.

Preferred rule:

```text
each meaningful Python implementation unit
→ one parent functional capability
→ optional multiple detailed requirement IDs
```

The parent functional capability is the important anchor.

---

## 17. StrictDoc DOCUMENT_FROM_FILE Caution

StrictDoc may support document inclusion / composition, but this should not be relied on too early.

Safer first step:

```text
multiple normal .sdoc documents in one StrictDoc project tree
```

Only use advanced include/composition features after testing them on the real project tree.

---

## 18. Final Implementation Plan — High Priority

This is the current final plan.

### Step 0 — Baseline and Rule Definition

Before creating serious `.sdoc` files, define everything.

```text
0.1 Commit current Markdown requirements.
0.2 Tag/archive current Markdown baseline.
0.3 Define that migration happens on a separate branch.
0.4 Define new requirement tree from zero.
0.5 Define UID prefixes and ownership.
0.6 Define required fields.
0.7 Define requirement types.
0.8 Define status values.
0.9 Define implementation-status values.
0.10 Define verification method values.
0.11 Define relation types.
0.12 Define source/origin policy.
0.13 Define code trace policy.
0.14 Define architecture/UML trace policy.
0.15 Define baseline/freeze/no-renumbering policy.
0.16 Define source-of-truth cutover rule.
```

This is mandatory.

No migration should happen before Step 0.

---

### Step 1 — Create New `.sdoc` Skeleton Tree

Create empty StrictDoc skeleton files using the new modern capability structure.

Important:

```text
Use new functional capability names.
Do not copy old Markdown structure blindly.
Do not copy Python folder structure.
Cross-cutting/operational topics may live separately.
```

The earlier tree was only a dummy suggestion.

The new tree must be designed deliberately.

---

### Step 2 — Define Root SRS and Capability Structure

Root SRS should likely contain:

```text
Introduction
Overall Description
Specific Requirements
```

Under `Specific Requirements`, branch into the new functional capability map.

The exact names are still to be designed.

The tree should support future traceability to:

```text
requirements
architecture
UML
Python code
tests
audit reports
```

---

### Step 3 — Semantic Migration from Markdown to `.sdoc`

Refactor current Markdown requirements into the new `.sdoc` system.

This must be semantic migration.

For each old requirement-like item:

```text
extract intent
split into atomic requirement if needed
assign correct new capability parent
assign UID according to policy
write TITLE
write STATEMENT
write RATIONALE if needed
write SOURCE / old origin
write STATUS
write IMPLEMENTATION_STATUS
write RELATIONS
```

Create migration map:

```text
old file/heading/text hash
→ new .sdoc file
→ new UID
→ migration note
```

---

### Step 4 — Assign and Freeze UIDs

Use GHOST UID policy.

StrictDoc auto-UID may help fill missing IDs, but only after rules exist.

Correct flow:

```text
assign/generate missing UIDs
review UIDs
fix wrong prefixes or placements
freeze accepted UIDs
do not renumber after freeze
```

---

### Step 5 — Validate with StrictDoc

Run validation/export checks.

Minimum acceptance:

```text
no duplicate UID
no missing required fields
no broken relations
no circular parent chains
no orphan detailed requirements
JSON export succeeds
```

---

### Step 6 — Export JSON

Export StrictDoc JSON.

Use JSON as:

```text
machine-readable requirement view
audit input
future GHOST/GitHub Agent input
possible RAG/AI ingestion input
```

Do not build Markdown conversion unless needed.

---

### Step 7 — Source-of-Truth Cutover

After human review and approval:

```text
.sdoc becomes requirement source of truth.
old Markdown becomes archived or derived.
```

This must be written explicitly in governance.

---

### Step 8 — Define and Apply Code Trace Policy

Define how requirement IDs appear in code.

Possible options:

```text
comments
docstrings
StrictDoc file relations
external trace map
```

Preferred early rule:

```text
annotate meaningful implementation units only
avoid over-annotating tiny helpers
each meaningful unit maps to one parent functional capability
detailed requirement IDs may be added where useful
```

---

### Step 9 — Read-Only GitHub Audit

Run GitHub Agent only as auditor.

Compare:

```text
StrictDoc requirements
architecture / UML
Python implementation
tests if available
```

Output evidence report only.

No automatic edits.

---

### Step 10 — Human Review and Controlled Updates

Human reviews audit findings.

Possible outcomes:

```text
accept mismatch
reject mismatch
update requirement
update architecture/UML
update code
create backlog item
mark requirement obsolete
mark code obsolete
```

StrictDoc changes happen only after human approval.

---

### Step 11 — Add CI Validation Later

Add automated checks into GitHub Actions later:

```text
StrictDoc validation
JSON export
UID uniqueness
required-field completeness
broken relation check
code reference check
test reference check
```

This comes after basic migration is stable.

---

### Step 12 — Build Real GHOST Requirement-Code Sync Agents

Only after all previous steps are stable:

```text
stable .sdoc source of truth
frozen UID policy
validated JSON export
defined code trace policy
defined audit report format
human review loop working
```

Then build real GHOST sync agents.

Do not build sync agents before the requirement system exists.

---

## 19. Corrected Final Process in One Block

```text
0. Baseline current Markdown and define all rules:
   file tree, UID prefixes, required fields, relation types,
   status values, verification method, implementation status,
   source/origin policy, code trace policy, architecture/UML trace policy,
   freeze/no-renumbering policy, source-of-truth cutover rule.

1. Design new modern requirement tree from zero:
   use functional capability structure,
   probably with new names,
   not old Markdown structure,
   not Python folder structure.

2. Create empty .sdoc skeletons:
   root SRS plus capability documents,
   using the new tree.

3. Semantically migrate current Markdown requirements:
   intent → atomic requirement → UID → title → statement →
   rationale/source → relations → status → implementation status.

4. Assign and freeze UIDs:
   use GHOST UID policy,
   StrictDoc auto-UID only as helper,
   review and freeze,
   never renumber frozen IDs.

5. Validate with StrictDoc:
   no duplicate UIDs,
   no missing mandatory fields,
   no broken relations,
   no circular parent chains,
   no orphan detailed requirements,
   JSON export succeeds.

6. Export JSON:
   use as machine/audit/export view.
   Postpone Markdown export unless needed.

7. Explicit source-of-truth cutover:
   .sdoc becomes requirement truth,
   old Markdown becomes archived or derived.

8. Define code and architecture trace policy:
   map meaningful Python units to functional capability parents,
   link detailed requirement IDs where useful,
   connect requirements to UML/architecture/test evidence.

9. Run read-only GitHub Agent audit:
   code ↔ StrictDoc requirements ↔ architecture/UML,
   output evidence/mismatch report only.

10. Human review:
   human accepts/rejects audit findings,
   only approved changes update .sdoc/code/UML.

11. Add CI validation:
   StrictDoc validation/export,
   UID checks,
   relation checks,
   missing-field checks,
   code-reference checks.

12. Only after this:
   build real GHOST requirement-code synchronization agents.
```

---

## 20. High-Priority Constraints for the Next Chat

The next chat must preserve these rules:

```text
Do not treat the old dummy tree as final.
Do not copy the Python folder tree.
Do not perform mechanical Markdown-to-SDoc conversion.
Do not auto-generate and accept UIDs blindly.
Do not create two competing truths.
Do not build sync agents before stable .sdoc + UID + JSON + trace policy exist.
Do not let GitHub Agent modify requirements automatically at first.
Do not over-annotate tiny helper functions.
Do not postpone Step 0.
```

---

## 21. Immediate Next Action

The next practical task should be:

```text
Design Step 0:
- new modern GHOST requirement tree
- UID prefix scheme
- mandatory requirement fields
- relation types
- status/type/implementation-status values
- source-of-truth cutover rule
- code/UML trace policy
```

Only after Step 0 is accepted should real `.sdoc` skeleton files be created.

```
```
