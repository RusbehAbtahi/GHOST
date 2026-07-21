# Audit Findings: 30_preprocessing_prompt_functions.sdoc

## Audit Scope

- Target file: doc/01-Requirements/strictdoc/30_preprocessing_prompt_functions.sdoc
- Repository commit: b039a53354f49405139ba52d8816466b1015420d
- Normative UID count: 146
- CONSISTENT count: 135
- PARTIAL count: 2
- CONTRADICTED count: 9
- UNCLEAR count: 0

## Findings

### GHOST-PREPROCESS-SCHEMA-RUNTIME-MAPPING — Schema-to-Runtime Field Mapping

**Conclusion**

CONTRADICTED

**Requirement claim**

Recognized schema names `response_depth` and `output_format` must be deterministically routed to the active runtime body fields `depth` and `format`.

**Exact evidence**

- `ragstream/config/prompt_schema.json` declares `$.canonical_keys` entries `response_depth` and `output_format`, declares aliases such as `depth -> response_depth` and `format -> output_format`, and provides defaults at `$.defaults.response_depth` and `$.defaults.output_format`.
- `ragstream/preprocessing/name_matcher.py` returns canonical schema keys directly from `NameMatcher.resolve()` and does not translate schema-facing canonical names to runtime body names.
- `ragstream/preprocessing/preprocessing.py` writes only keys in the literal runtime list `system`, `task`, `audience`, `role`, `tone`, `depth`, `context`, `purpose`, `format`, and `text`; therefore mapped keys named `response_depth` or `output_format` are recognized but never written to `sp.body["depth"]` or `sp.body["format"]`.

**Why it is not OK**

The executable behavior recognizes schema fields without delivering their values to their required runtime destinations, which is exactly the failure mode the requirement forbids.

**Required correction**

Either add an executable schema-to-runtime mapping for `response_depth -> depth` and `output_format -> format`, or change the requirement and schema so active canonical keys match the runtime body contract directly.

### GHOST-PREPROCESS-MUST-DESTINATION — Mandatory Field Runtime Destination

**Conclusion**

CONTRADICTED

**Requirement claim**

Every mandatory schema field must have a runtime destination, or it must not remain in the active mandatory-field set.

**Exact evidence**

- `ragstream/config/prompt_schema.json` declares mandatory keys at `$.must_keys`, including `constraints` and `output_format`.
- `ragstream/preprocessing/preprocessing.py` iterates `schema.must` and populates defaults into `mapped[must_key]`, but the write-back whitelist excludes `constraints` and expects `format` rather than `output_format`.
- `ragstream/orchestration/super_prompt.py` defines the active body contract without a `constraints` field.

**Why it is not OK**

Mandatory defaults can be applied into the transient `mapped` dictionary and then discarded before SuperPrompt write-back, so the runtime cannot truthfully claim those mandatory fields are enforced.

**Required correction**

Remove unsupported mandatory fields from the active schema, add supported SuperPrompt destinations, or implement an explicit schema-to-runtime destination map before mandatory-field enforcement is reported as current behavior.

### GHOST-PREPROCESS-MANDATORY-DEFAULTS — Other Mandatory Field Defaults

**Conclusion**

PARTIAL

**Requirement claim**

After TASK fallback, every other active mandatory field that is absent or empty must receive its configured default only when the field has an active runtime destination.

**Exact evidence**

- `ragstream/preprocessing/preprocessing.py` applies defaults for every `schema.must` key other than `task`.
- The same function writes back only a fixed runtime-key whitelist, so mandatory defaults for `system`, `audience`, `purpose`, `tone`, and `context` can reach `SuperPrompt.body`, while `constraints` and `output_format` cannot.
- `ragstream/config/prompt_schema.json` provides defaults under `$.defaults.constraints` and `$.defaults.output_format`, but `SuperPrompt.body` does not contain `constraints` and preprocessing does not translate `output_format` to `format`.

**Why it is not OK**

The defaulting mechanism exists, but it is broader than the active runtime destination set and therefore partially enforces mandatory defaults in a way that can silently discard configured mandatory fields.

**Required correction**

Constrain mandatory defaulting to mapped runtime destinations, or add explicit destinations for every active mandatory schema key.

### GHOST-PREPROCESS-QUERY-FINALIZATION — Post-Classification Retrieval-Query Finalization

**Conclusion**

CONTRADICTED

**Requirement claim**

After relation classification and deterministic routing, `SuperPrompt.effective_retrieval_query_text` must be rebuilt from the final routing state.

**Exact evidence**

- `ragstream/preprocessing/preprocessing.py` builds `effective_retrieval_query_text` before ActiveBrief relation extras exist.
- `ragstream/app/controller.py` then calls `ActiveBriefRelationClassifier.run()` and `sp.compose_prompt_ready()`, but does not call `SuperPromptProjector.build_query_text()` or any other query rebuild after classification.
- `ragstream/orchestration/superprompt_projector.py` has final routing-aware query logic in `SuperPromptProjector.build_query_text()`, but the controller does not invoke it after classifier extras are written.

**Why it is not OK**

A final state that requires ActiveBrief inclusion or retrieval suppression can leave the pre-classification current-prompt-only query in place at handoff.

**Required correction**

After `ActiveBriefRelationClassifier.run()`, rebuild `sp.effective_retrieval_query_text` through the central query projector before prompt handoff.

### GHOST-PREPROCESS-FINAL-MODE-AUTHORITY — Final Prompt Mode Authority

**Conclusion**

CONTRADICTED

**Requirement claim**

Central prompt projection must honor the deterministic `final_prompt_mode` stored by prompt preparation and must not independently derive contradictory ActiveBrief inclusion behavior.

**Exact evidence**

- `ragstream/preprocessing/activebrief_relation_classifier.py` stores `final_prompt_mode` inside `sp.extras["activebrief_relation_decision"]`.
- `ragstream/orchestration/superprompt_projector.py` does not read that `final_prompt_mode` in `_render_retrieved_context_md()`; it derives `use_full_brief` and `use_title_only` directly from `activebrief_prompt_materiality` and `activebrief_topic_relation`.
- The projector's derived table includes full ActiveBrief text for `STRONG + RELATED_DOMAIN`, while the requirement's current mode for that state is `title_related_domain_note`.

**Why it is not OK**

The central preview path contains an independent routing table and can contradict the routing decision written by prompt preparation.

**Required correction**

Make prompt projection consume `activebrief_relation_decision.final_prompt_mode` as the authority, or update the requirement and routing implementation together if a different table is intended.

### GHOST-PREPROCESS-QUERY-ACTIVEBRIEF — ActiveBrief Contribution to Retrieval Query

**Conclusion**

PARTIAL

**Requirement claim**

ActiveBrief content must contribute to the effective retrieval query only according to the deterministic routing state.

**Exact evidence**

- `ragstream/orchestration/superprompt_projector.py` implements the correct routing-aware query table in `SuperPromptProjector.build_query_text()`.
- `ragstream/app/controller.py` does not rebuild `sp.effective_retrieval_query_text` after `ActiveBriefRelationClassifier.run()` writes the classifier extras that `build_query_text()` needs.

**Why it is not OK**

The table exists, but the complete prompt-preparation path can hand off a stale query built before that table had the final routing inputs.

**Required correction**

Invoke the routing-aware query projection after classifier extras are available and before handoff.

### GHOST-PREPROCESS-AC-SCHEMA-RUNTIME-MAP — AC: Schema-to-Runtime Mapping

**Conclusion**

CONTRADICTED

**Requirement claim**

Recognized `response_depth` or `output_format` values must route to runtime `depth` or `format`, and mandatory fields without a destination must not be reported as enforced.

**Exact evidence**

- `ragstream/preprocessing/name_matcher.py` resolves aliases to schema canonical keys such as `response_depth` and `output_format`.
- `ragstream/preprocessing/preprocessing.py` never maps those canonical keys to runtime destinations before SuperPrompt write-back.
- `ragstream/config/prompt_schema.json` keeps mandatory `constraints` and `output_format` active in `$.must_keys`.

**Why it is not OK**

The acceptance criterion fails for both named mapping examples and for mandatory-field destination conformance.

**Required correction**

Implement and validate the schema-to-runtime map, and ensure mandatory schema fields without runtime destinations are not active mandatory fields.

### GHOST-PREPROCESS-AC-WEAK-SAME-QUERY — AC: Weak Same-Topic Retrieval Query

**Conclusion**

CONTRADICTED

**Requirement claim**

For `WEAK + SAME_TOPIC`, the finalized query must include the current prompt projection and full ActiveBrief body.

**Exact evidence**

- `ragstream/orchestration/superprompt_projector.py` can add the full ActiveBrief body for `WEAK + SAME_TOPIC` when `build_query_text()` sees final classifier extras.
- `ragstream/app/controller.py` builds the query before classification through `preprocess()` and then never rebuilds it after relation extras are present.

**Why it is not OK**

The end-to-end prepared handoff can omit the required ActiveBrief body for this routing state.

**Required correction**

Rebuild `effective_retrieval_query_text` after relation classification and before handoff.

### GHOST-PREPROCESS-AC-WEAK-RELATED-QUERY — AC: Weak Related-Domain Retrieval Query

**Conclusion**

CONTRADICTED

**Requirement claim**

For `WEAK + RELATED_DOMAIN`, the finalized query must include the current prompt projection and the ActiveBrief title but not the full ActiveBrief body.

**Exact evidence**

- `ragstream/orchestration/superprompt_projector.py` contains this routing branch in `build_query_text()`.
- `ragstream/app/controller.py` does not call the routing-aware query builder after classifier extras are written.

**Why it is not OK**

The finalized query at controller handoff can remain the pre-classification current-prompt-only query and miss the required title contribution.

**Required correction**

Rebuild the effective retrieval query after relation classification.

### GHOST-PREPROCESS-AC-WEAK-IRRELEVANT-QUERY — AC: Weak Irrelevant Retrieval Suppression

**Conclusion**

CONTRADICTED

**Requirement claim**

For `WEAK + IRRELEVANT`, the finalized effective document-retrieval query must be empty and memory context must be disabled.

**Exact evidence**

- `ragstream/preprocessing/activebrief_relation_classifier.py` disables memory context for `WEAK + IRRELEVANT` in `_build_decision()`.
- `ragstream/orchestration/superprompt_projector.py` returns an empty query for `WEAK + IRRELEVANT` in `build_query_text()`.
- `ragstream/app/controller.py` does not rebuild `effective_retrieval_query_text` after classification, so a non-empty pre-classification query can remain stored.

**Why it is not OK**

Only the memory-context side is reliably updated in the controller path; the document-query suppression signal can be stale.

**Required correction**

Rebuild the effective retrieval query from final relation extras before retrieval handoff.

### GHOST-PREPROCESS-AC-QUERY-REBUILD — AC: Query Rebuilt after Classification

**Conclusion**

CONTRADICTED

**Requirement claim**

A pre-classification query must be rebuilt after classification when the final routing state changes ActiveBrief contribution or suppresses retrieval.

**Exact evidence**

- `ragstream/preprocessing/preprocessing.py` computes an initial query before ActiveBrief relation classification.
- `ragstream/app/controller.py` invokes the classifier and central prompt preview, but does not update `effective_retrieval_query_text` afterward.

**Why it is not OK**

The mandatory post-classification rebuild step is absent from the current controller coordination.

**Required correction**

Add the post-classification query rebuild to the prompt-preparation sequence.

### GHOST-PREPROCESS-AC-FINAL-MODE — AC: Final Prompt Mode Projection

**Conclusion**

CONTRADICTED

**Requirement claim**

Given a deterministic `final_prompt_mode`, the projector must include exactly the permitted ActiveBrief continuity material and must not apply a contradictory independent state table.

**Exact evidence**

- `ragstream/preprocessing/activebrief_relation_classifier.py` stores the deterministic mode in `activebrief_relation_decision.final_prompt_mode`.
- `ragstream/orchestration/superprompt_projector.py` derives preview inclusion from materiality and relation labels instead of reading `final_prompt_mode`.
- The projector includes full ActiveBrief text for `STRONG + RELATED_DOMAIN`, which contradicts the required `title_related_domain_note` behavior.

**Why it is not OK**

The acceptance criterion is specifically about central projection honoring final mode; the current projector has an independent table that can disagree with the classifier decision.

**Required correction**

Use the stored `final_prompt_mode` as the projector authority and align the projection behavior with the required mode definitions.

## File Verdict

The deterministic parser, classifier, A2 sanitizer/default behavior, and SuperPrompt storage are substantially traceable, but the current baseline has real conformance defects in schema-to-runtime field mapping and post-classification query/final-mode projection synchronization.

## No-Finding Statement

All normative UIDs not listed under `Findings` were inspected and classified `CONSISTENT`.
