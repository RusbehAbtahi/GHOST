Below is the complete updated version, with only the necessary corrections applied: explicit human authority, explicit requirement-files source-of-truth wording, clearer threshold-governance wording, and clearer component-card audience-split wording. The rest is kept intact in substance and structure, based on the current governance file and the connected project requirements, architecture, implementation status, and AWS baseline.       

# Requirements_Quality_Governance.md

## 1. Purpose and scope

This document defines cross-cutting quality, evaluation, operational, and documentation requirements for RAGstream. It is not a new subsystem. It is a governance layer applied across the already defined system: Requirements_Main, Requirements_RAG_Pipeline, Requirements_AgentStack, Requirements_Ingestion_Memory, Requirements_Orchestration_Controller, Requirements_GUI, Architecture, UML, and the current AWS Phase-1 deployment.

This document covers exactly five feature families:

1. automated testing,
2. structured logging and observability,
3. benchmarking and evaluation,
4. security hardening and operational monitoring,
5. component cards and stakeholder-facing technical documentation.

These five families are intentionally separable. The system may implement one without forcing the immediate implementation of all others. However, they are not equally mature in timing. Based on the current implementation state, Features 1 and 2 can start immediately with little architectural disturbance, while Feature 3 becomes most useful once the Retrieval and ReRanker directions are stabilized. Features 4 and 5 can begin independently, but both become stronger when Feature 3 later provides measured evidence.

This document does not redefine stage behavior, controller behavior, or ingestion behavior. Those remain defined in the subsystem requirements. This document adds professional quality obligations around them.

This document supports human review and decision-making. It does not replace human authority. Final adoption, prioritization, interpretation, threshold approval, and revision authority remain with the human maintainer.

## 2. Governing baseline

All requirements in this document shall remain consistent with the currently approved architecture, currently implemented components, currently documented deployment baseline, and current repository/runtime structure.

At present, the relevant baseline is:

* Streamlit Generation-1 GUI exists and is wired to controller-driven project ingestion and Retrieval.
* Deterministic preprocessing exists.
* A2 PromptShaper exists and is live through the JSON-based agent stack.
* Chroma-based project ingestion with file manifests exists.
* Retrieval exists and is deterministic, project-aware, and writes into SuperPrompt.
* ReRanker exists in code and the current ranking direction is under agreed redesign.
* A3, A4, A5, and Prompt Builder are not yet complete as stable operational stages.
* The current AWS deployment uses GitHub Actions, ECR, EC2, Docker, nginx, HTTPS via Certbot, Route53 update, SSM Parameter Store, and EBS-backed runtime data under `/home/ubuntu/ragstream_data` mounted to `/app/data`.

Nothing in this document shall assume a different active deployment model than that documented baseline. In particular, the persistent runtime data model remains `data/doc_raw/<project>` and `data/chroma_db/<project>` both locally and on AWS.

## 3. Global design rules

### 3.1 Preserve existing sources of truth

The following invariants remain unchanged:

* SuperPrompt remains the authoritative in-memory state for a run.
* FileManifest remains the authoritative ledger for document ingestion state.
* Project Chroma stores remain the authoritative persistent embedding stores for ingested documents.
* Controller remains an orchestrator and shall not absorb retrieval logic, embedding logic, or LLM-provider logic.
* Retrieval and ReRanker remain deterministic pipeline stages.
* Until explicitly changed by the human maintainer, the approved markdown requirement files remain the project source of truth at requirement level.
* This document is part of that requirement-level governance set, but it shall not silently override the other approved requirement files.

### 3.2 Optionality

Each feature in this document shall be implementable independently. Implementing tests shall not require implementing model/component cards. Implementing structured logging shall not require changing the AWS topology. Implementing security hardening shall not require a different identity platform than the one currently documented. Implementing component cards shall not require a completed evaluation pipeline, although in that case the cards must explicitly state that evaluation evidence is still incomplete. This optionality rule is an added governance requirement in this document; it is not a restatement of another subsystem file.

### 3.3 Local and AWS parity

Any adopted feature shall work in both execution contexts:

* local repository execution under the project `data/` layout,
* AWS runtime execution under the EC2/EBS bind mount at `/app/data`.

### 3.4 No silent behavioral redefinition

This document may require tests, logs, metrics, hardening checks, and documentation around a stage, but it shall not silently redefine what that stage functionally does. Functional stage semantics remain in the subsystem requirements.

### 3.5 Failure integrity

Where this document adds cross-cutting requirements to stage execution, it shall respect the controller rule that stage failures must not partially corrupt SuperPrompt state. Either a stage update is applied coherently, or the prior state remains intact.

## 4. Feature 1 — Automated testing

### 4.1 Goal

RAGstream shall gain a formal automated test layer that supports safe refactoring, non-regression, and professional software engineering discipline across the already implemented modules and the next planned stages. This is especially important because the system is no longer at pure planning level: it already has live preprocessing, A2, project ingestion, Retrieval, and working AWS deployment.

### 4.2 Scope

Automated testing shall apply to:

* preprocessing,
* controller stage methods,
* ingestion modules,
* retrieval modules,
* agent-stack modules,
* project-ingestion GUI/controller flows at the action boundary,
* ReRanker stage, including its current implementation and agreed redesign direction.

This first wave does not require full browser-level UI automation.

### 4.3 Required test layers

#### 4.3.1 Unit tests

Unit tests shall exist for at least:

* `ragstream/preprocessing/preprocessing.py`,
* `ragstream/preprocessing/prompt_schema.py`,
* `ragstream/ingestion/file_manifest.py`,
* `ragstream/ingestion/ingestion_manager.py`,
* `ragstream/ingestion/chunker.py`,
* `ragstream/ingestion/vector_store_chroma.py`,
* `ragstream/orchestration/agent_factory.py`,
* `ragstream/orchestration/agent_prompt.py`,
* `ragstream/app/controller.py`,
* `ragstream/retrieval/retriever.py`,
* `ragstream/utils/logging.py`.

The reason these files are explicitly in scope is factual, not aspirational: they already exist in the current project tree and current Python index.

#### 4.3.2 Integration tests

Integration tests shall exist for at least these flows:

* Create Project -> Add Files -> automatic ingestion -> manifest written,
* active project selection -> embedded file list retrieval,
* PreProcessing -> A2 -> Retrieval on a fixture project,
* Retrieval with known project data and expected selected chunk ids or file-level expectations,
* local Docker smoke run of the application image.

These integration tests are grounded in already documented flows: the GUI already exposes project creation, file import, active DB selection, and Retrieval Top-K controls, and the controller already implements those action boundaries.

#### 4.3.3 Regression tests

Whenever a defect is fixed in one of the following areas, a regression test shall be added:

* stage gating,
* project-name validation,
* manifest diffing,
* stale chunk cleanup,
* stale retrieval row handling,
* retrieval ranking behavior,
* retrieval hydration from raw documents.

This is mandatory because those areas are structurally critical and already appear as live responsibilities in controller, ingestion, and Retrieval behavior.

### 4.4 Test structure

A repository-local test tree shall be introduced with at least:

* `tests/unit/`
* `tests/integration/`
* `tests/regression/`
* `tests/fixtures/`

Fixtures shall include:

* small `doc_raw/<project>` trees,
* fixture `file_manifest.json` files,
* fixture SuperPrompt objects,
* fixture Retrieval queries with expected relevant chunk ids or expected relevant files,
* mocked LLM outputs for A2 and later A3/A4/A5 tests.

### 4.5 CI relation

The test layer shall integrate into the already documented GitHub Actions path. The required professional behavior is that testing becomes part of the same delivery chain that currently builds and pushes the Docker image. This extends the existing workflow; it does not require a new CI platform.

### 4.6 Independence

Feature 1 can begin immediately. It does not require changes to AWS topology, persistent storage structure, or pipeline semantics.

## 5. Feature 2 — Structured logging and observability

### 5.1 Goal

RAGstream shall move from minimal ad hoc logging toward structured, stage-aware logging that supports debugging, auditability, operational diagnosis, and later evaluation work.

### 5.2 Current factual baseline

The current code already contains a `SimpleLogger` facade that prints to stdout and is explicitly designed so it can later be swapped to Python logging without changing callers.

The controller requirements already require stage-level logging with timestamp, stage name, and basic statistics.

The architecture also explicitly distinguishes developer debug logging from user-facing transparency. Those are separate concerns and must remain separate in any improved design.

### 5.3 Scope

Structured logging shall apply to:

* controller stage execution,
* ingestion runs,
* retrieval runs,
* agent-stack compose/call/parse operations,
* deployment/runtime operational checks.

It does not require introducing a new observability platform.

### 5.4 Required logging classes

#### 5.4.1 Application logs

Each major event shall log a structured record containing at least:

* timestamp,
* level,
* component,
* stage when relevant,
* project name when relevant,
* session or request identifier when available,
* concise event message,
* compact statistics payload where relevant.

#### 5.4.2 Developer debug logs

A deeper developer-oriented log stream may exist for richer internal diagnosis. That remains separate from user transparency panels.

#### 5.4.3 Operational runtime logs

In AWS, operational diagnosis shall remain compatible with the real log surfaces already in use:

* application stdout/stderr,
* `docker logs`,
* `journalctl` for `ragstream.service`,
* nginx validation and service logs.

### 5.5 Minimum required log events

#### 5.5.1 Controller

Controller logs shall include:

* requested stage,
* stage allowed or blocked,
* stage completed or failed,
* basic stage summary metrics,
* `last_error` when stage failure occurs.

#### 5.5.2 Ingestion

Ingestion logs shall include:

* project name,
* files scanned,
* to-process count,
* unchanged count,
* tombstones,
* vectors upserted,
* deleted old versions,
* deleted tombstones,
* published manifest path,
* embedded bytes.

These are grounded in the existing `IngestionStats` model, not invented here.

#### 5.5.3 Retrieval

Retrieval logs shall include:

* project name,
* top_k,
* retrieval query source fields used,
* chunking parameters,
* candidate count,
* final selected count,
* stale/broken row skip count when applicable,
* elapsed time.

These are grounded in current Retrieval behavior and current robustness notes.

#### 5.5.4 Agent stack

Agent logs shall include:

* agent id,
* version,
* model name,
* compose result,
* parse/validation result,
* failure surface when safe to log.

This is grounded in the existing JSON-configured agent architecture and validation role of AgentFactory and AgentPrompt.

### 5.6 Implementation rule

`SimpleLogger` may remain the caller-facing facade in the first step, but the output format shall be made structured and consistent enough to support later testing, evaluation, and operational diagnosis.

### 5.7 Independence

Feature 2 can also begin immediately. It does not require a change in AWS topology or pipeline semantics.

## 6. Feature 3 — Benchmarking and evaluation

### 6.1 Goal

RAGstream shall gain a formal evaluation layer that measures quality, performance, and non-regression of the implemented pipeline stages.

### 6.2 Actual centrality of this feature

Feature 3 is central to quality maturity, but not as a strict dependency claim. The correct audited statement is this:

* Feature 3 is the main source of measured quality evidence.
* Feature 4 and Feature 5 do not require Feature 3 in order to start.
* However, Feature 4 and Feature 5 become materially stronger, more defensible, and more objective once Feature 3 exists.

That is the correct statement. It is not a prerequisite claim.

### 6.3 Stage-based evaluation roadmap

The evaluation roadmap shall follow actual project maturity, not theoretical full-pipeline completeness.

#### 6.3.1 Wave 1 — Retrieval evaluation

Mandatory first, because Retrieval is already implemented.

#### 6.3.2 Wave 2 — ReRanker evaluation

Mandatory because ReRanker already exists in code and remains the main precision stage under redesign relative to Retrieval.

#### 6.3.3 Wave 3 — A3/A4/A5/Prompt Builder evaluation

Mandatory only when those stages become stable implemented stages. Today they are still scaffold or partial and therefore should not be treated as mature evaluation targets.

### 6.4 Retrieval evaluation requirements

Retrieval shall be evaluated on:

* Recall@k,
* Precision@k,
* ranked-hit metric such as MRR,
* latency,
* project routing correctness,
* stale-row robustness,
* correctness of hydrated chunk reconstruction from raw project data.

This is directly grounded in the agreed Retrieval design: query text comes from `task`, `purpose`, and `context`; dense and SPLADE branches run against the active project’s Chroma store; rankings are fused with RRF; and raw chunk text is reconstructed from `doc_raw/<project>`.

### 6.5 ReRanker evaluation requirements

ReRanker shall be evaluated on both the current implemented baseline and the agreed redesigned direction:

* quality improvement over Retrieval baseline,
* latency,
* runtime resource cost,
* practical AWS viability on the deployment path that is planned to remain architecturally stable.

This is grounded in the current implementation status, which states that ReRanker already exists in code, that the current cross-encoder direction is not accepted as final, and that the agreed future direction remains a bounded precision stage over Retrieval while keeping the surrounding AWS deployment architecture unchanged.

### 6.6 Late-stage evaluation requirements

When A3, A4, A5, and Prompt Builder become real stable stages, evaluation shall cover:

* A3 keep/drop correctness,
* A4 condensation faithfulness and compression,
* A5 format compliance,
* Prompt Builder final prompt completeness and contract integrity.

This is grounded in current requirement definitions of those stages, but the maturity timing is deferred until they are real.

### 6.7 Evaluation dataset requirements

A repository-local evaluation corpus shall be introduced. Each case shall include at minimum:

* query,
* active project,
* expected relevant chunk ids or expected relevant files,
* notes explaining why that expectation was selected.

Later stages may extend this with expected condensed facts or expected format outputs.

This requirement does not introduce any external storage system.

### 6.8 Evaluation execution modes

#### 6.8.1 Local fast mode

A small fixture set shall run locally and in CI.

#### 6.8.2 Manual heavy mode

A larger evaluation set may run locally or on the deployed EC2 runtime, especially for ReRanker and later heavier stages.

#### 6.8.3 Release mode

If a mature stage changes materially, the relevant evaluation suite shall be run before that change is treated as stable.

### 6.9 Evaluation artifacts

Evaluation outputs shall be stored as inspectable local or runtime files, such as:

* JSON summaries,
* CSV metric tables,
* Markdown reports,
* optional plots.

### 6.10 Threshold governance

Each mature evaluated stage shall define explicit non-regression thresholds. Examples:

* Retrieval must not regress below an agreed Recall@k baseline.
* ReRanker must show measurable improvement over plain Retrieval on the same fixture set.

These thresholds shall be derived from recorded evaluation results on the agreed fixture corpus and baseline implementation, not invented arbitrarily. A threshold becomes binding only after explicit human approval. Until then, reported metrics are informative evidence, not pass/fail gates. Any later threshold change shall be explicitly documented by the human maintainer in the relevant requirement or evaluation artifact.

## 7. Feature 4 — Security hardening and operational monitoring

### 7.1 Goal

RAGstream shall formalize the security controls already present in the current deployment and add the most relevant missing hardening requirements for a serious single-developer system.

### 7.2 Current factual security baseline

The current deployment already includes:

* public access only through 80 and 443,
* public inbound 8501 blocked by Security Group,
* nginx as the public front door,
* TLS handled at nginx,
* OpenAI key stored in SSM Parameter Store,
* GitHub CI AWS credentials stored only in GitHub Secrets,
* no AWS access key stored on EC2,
* runtime data separated from the image and persisted on EBS,
* project-name validation in controller,
* upload file-type restriction in the GUI flow.

### 7.3 Required hardening requirements

#### 7.3.1 Secret discipline

Secrets shall remain only in the currently documented secret channels:

* SSM Parameter Store at runtime,
* GitHub Secrets in CI.

No secret shall be committed into repository code, manifests, evaluation artifacts, or logs.

#### 7.3.2 Backend exposure reduction

The current documented live state still uses broad host publish of port 8501, with effective protection supplied by the Security Group. That is acceptable as current truth, but one future hardening step shall be to reduce backend exposure so that backend reachability is constrained to the intended local reverse-proxy path as tightly as practical.

#### 7.3.3 Input-boundary hardening

Validation shall be systematic at these boundaries:

* project names,
* uploaded file types,
* uploaded file size limits,
* prompt size limits,
* malformed manifest inputs,
* stale retrieval metadata,
* agent-output JSON validation.

#### 7.3.4 Dependency and image hygiene

The existing delivery path shall include dependency and image hygiene checks before deployment. This is a process requirement on the current GitHub Actions + Docker path, not a new infrastructure requirement.

#### 7.3.5 Security-relevant event logging

Security-relevant events shall be logged, including:

* invalid project/path attempts,
* rejected file uploads,
* secret-fetch failures,
* backend start failures,
* nginx/backend connectivity failures,
* repeated malformed input failures.

These events are already natural surfaces in the current startup script, systemd service, controller validation, and runtime checks.

#### 7.3.6 Operational verification checks

The operational hardening playbook shall continue to include:

* nginx configuration validation,
* certificate renewal dry-run,
* service status checks,
* container status checks,
* disk usage checks,
* persistent mount verification.

### 7.4 Out-of-scope items

This document does not newly require:

* Cognito,
* ALB,
* CloudFront,
* autoscaling,
* multi-tenant identity or access architecture.

Those are explicitly outside the current Phase-1 deployment scope.

### 7.5 Relationship to Feature 2 and Feature 3

Feature 4 does not depend on Feature 3 in order to begin. It already has a real baseline from the current deployment and operational model. However, Feature 2 gives it better evidence through logs, and Feature 3 later gives it stronger anomaly baselines and measurable non-regression evidence. That is the correct audited statement.

## 8. Feature 5 — Component cards and stakeholder-facing technical documentation

### 8.1 Goal

RAGstream shall gain concise, evidence-based component documentation so that the system can be understood, reviewed, presented, and evolved professionally.

### 8.2 Why the correct unit is a component card

RAGstream is not only a collection of learned models. It is a mixed architecture of:

* deterministic ingestion,
* deterministic Retrieval,
* deterministic ReRanker orchestration around a model,
* stateless LLM-based agents,
* controller orchestration,
* deployment/runtime infrastructure.

Therefore the correct documentation unit here is a component card, not only a narrow classical model card.

### 8.3 Mandatory card targets

Component cards shall eventually exist for at least:

* A2 PromptShaper,
* Retrieval,
* ReRanker,
* A3 when real,
* A4 when real,
* A5 when real,
* Prompt Builder when it becomes the final authoritative assembly stage,
* document ingestion pipeline,
* AWS runtime/deployment topology.

### 8.4 Minimum content of each card

Each card shall contain:

* component name,
* version,
* module path,
* deterministic or LLM-based classification,
* implementation status,
* inputs,
* outputs,
* dependencies,
* configuration parameters,
* current evaluation status,
* known limitations,
* known failure modes,
* relevant security/privacy notes,
* deployment/runtime notes when applicable.

### 8.5 Evidence rule

No component card shall claim maturity, robustness, or measured quality without corresponding evaluation or operational evidence.

### 8.6 Relation to existing documents

These cards shall summarize a component. They shall not duplicate:

* full subsystem requirements,
* full architecture narrative,
* full UML.

### 8.7 Audience split

Each component card shall have a developer-facing technical view.

A component card may additionally have:

* a stakeholder/interviewer/manager-facing concise view.

The stakeholder-facing concise view is optional. If it exists, it shall remain faithful to the technical view and shall not claim evidence that the technical view does not support.

### 8.8 Relationship to Feature 3

Feature 5 does not depend on Feature 3 in order to begin. Component cards can already be written from current requirements, architecture, implementation status, and code structure. However, without Feature 3 they must explicitly state where measured evaluation evidence is still missing. That is the correct audited statement.

## 9. Recommended implementation order

The recommended implementation order is:

1. automated testing,
2. structured logging and observability,
3. benchmarking and evaluation,
4. security hardening and operational monitoring,
5. component cards and stakeholder-facing technical documentation.

This order is justified by the current system state:

* Features 1 and 2 are the least intrusive and immediately useful,
* Feature 3 becomes the main measured-evidence layer once Retrieval and then ReRanker are stabilized,
* Feature 4 benefits from Features 2 and 3 but can already start from the current deployment,
* Feature 5 benefits from Feature 3 but can already start in a partial honest form.

## 10. Definition of done for this document

This document is satisfied only when:

* each adopted feature has concrete code or operational artifacts,
* each adopted feature can be pointed to in the repository or runtime environment,
* no statement in this document depends on undocumented infrastructure,
* all adopted features remain compatible with the current GitHub Actions -> ECR -> EC2 -> nginx -> Docker -> Streamlit -> persistent `/app/data` deployment baseline,
* no adopted feature in this document overrides human decision authority,
* any requirement-level change to this document or the connected requirement files is made explicitly by the human maintainer.
