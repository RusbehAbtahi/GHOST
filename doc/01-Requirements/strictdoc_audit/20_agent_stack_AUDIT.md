# Audit Findings: 20_agent_stack.sdoc

## Audit Scope

- Target file: doc/01-Requirements/strictdoc/20_agent_stack.sdoc
- Repository commit: b039a53354f49405139ba52d8816466b1015420d
- Normative UID count: 107
- CONSISTENT count: 106
- PARTIAL count: 1
- CONTRADICTED count: 0
- UNCLEAR count: 0

## Findings

### GHOST-AGENT-STACK-CONFIG-ERRORS — Configuration Error Integrity

**Conclusion**

PARTIAL

**Requirement claim**

The Agent Stack must fail explicitly for missing, unreadable, invalid JSON, non-object JSON, structurally incompatible required construction, and unresolved ambiguous catalogs, without fabricating or substituting a configuration.

**Exact evidence**

- `AgentFactory._load_json_file` explicitly fails for missing files, JSON load errors, and non-object top-level JSON values. 【F:ragstream/orchestration/agent_factory.py†L56-L71】
- `AgentFactory.get_agent` loads the selected config, constructs `AgentPrompt`, and caches that exact result without substituting a different version. 【F:ragstream/orchestration/agent_factory.py†L215-L222】
- `AgentPrompt.from_config` tolerates absent structural blocks by substituting empty dictionaries/lists and compatibility/default values for `agent_meta`, `llm_config`, `output_schema`, `static_prompt`, `dynamic_bindings`, `decision_targets`, and `elements_order`. 【F:ragstream/orchestration/agent_prompt.py†L119-L153】

**Why it is not OK**

The executable path satisfies the file-level and catalog-loading failure portions, but it does not fully satisfy the structurally incompatible configuration portion. A malformed or incomplete configuration can still become an `AgentPrompt` with defaults such as `unknown_agent`, version `000`, model `gpt-4.1-mini`, and empty prompt/schema structures instead of an explicit construction failure.

**Required correction**

Either update the requirement to describe the current permissive compatibility/defaulting behavior, or add explicit construction validation for the configuration blocks and fields considered required for an executable AgentPrompt.

## File Verdict

The Agent Stack requirements are largely consistent with current executable behavior. The only audited defect is the gap between explicit configuration-error integrity and the permissive defaulting in `AgentPrompt.from_config` for structurally incomplete configurations.

## No-Finding Statement

All normative UIDs not listed under `Findings` were inspected and classified `CONSISTENT`.
