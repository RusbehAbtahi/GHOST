# Requirements_AgentStack.md

1. Purpose and scope

---

This document specifies the “Agent Stack” used by the LLM-using agents in RAGstream.

The Agent Stack covers:

* AgentFactory (`agent_factory.py`)
* AgentPrompt (`agent_prompt.py`)
* llm_client (`llm_client.py`)

The Controller and each Agent (e.g. A2 PromptShaper, A3, and later A4/A5) are mentioned only where needed to define interfaces, but their detailed requirements live elsewhere.

The goals of this stack are:

* Neutral, stateless behavior (no hidden state, no A2-specific logic inside AgentFactory / AgentPrompt / llm_client).
* Agents defined as **data** (JSON configs) instead of hard-coded logic.
* Clean separation of concerns:

  * Agent = domain logic and deterministic post-processing
  * AgentFactory = config loader + config resolution + AgentPrompt construction
  * AgentPrompt = neutral prompt composer + parser/validator
  * llm_client = low-level LLM call

Current implementation-aligned neutrality rule:

* AgentFactory, AgentPrompt, and llm_client MUST remain neutral.
* A3-specific evidence rendering, local chunk-id mapping, chunk-text sanitization, and A3-specific prompt assembly MUST live in `a3_nli_gate.py` and/or the A3 JSON config, not inside neutral Agent Stack files.
* [24.04.2026] A4-specific evidence packaging, local chunk-id mapping, class grouping, fallback handling, and final write-back MUST live in `a4_condenser.py`, `a4_det_processing.py`, `a4_llm_helper.py`, and/or the A4 JSON configs, not inside neutral Agent Stack files.

Current practical scope:

* [24.04.2026] The current live Agent Stack consumers are A2 PromptShaper, A3 NLI Gate, and A4 Condenser.
* [24.04.2026] A4 is a special live consumer: it uses `AgentPrompt` objects loaded from exact nested JSON paths, not the normal `AgentFactory.get_agent(agent_id, version)` resolution path.
* The stack is intended to remain reusable for later A5, `NLP_Splitter`, and other agents, but those later consumers must not be described here as if they were already active runtime behavior where code does not yet show that.

Implementation note:

* The current code keeps a transparent read-only cache of constructed `AgentPrompt` objects inside `AgentFactory`. This cache is configuration-level reuse, not agent business state.

A2 PromptShaper is used as the running example, but the same neutral stack is also used by A3 and by the A4 Condenser prompt objects.

2. High-level data flow (A2 example)

---

Example: A2 PromptShaper is called by the Controller with a SuperPrompt that already contains `task`, `purpose`, `context`.

The A2 data flow using the Agent Stack:

1. Controller

   * Calls `A2.run(superprompt)`.
   * Does not know anything about agent configs, AgentFactory, AgentPrompt, or llm_client internals.

2. A2 (agent code)

   * Extracts from `superprompt.body` the fields it wants to send to the LLM, e.g.:

     * `task`
     * `purpose`
     * `context`

   * Builds an `input_payload` dict, for example:

     ```python
     input_payload = {
         "task": superprompt.body.get("task", ""),
         "purpose": superprompt.body.get("purpose", ""),
         "context": superprompt.body.get("context", ""),
     }
     ```

   * Calls AgentFactory:

     ```python
     agent_prompt = self.agent_factory.get_agent(
         agent_id="a2_promptshaper",
         version="003",
     )
     ```

   * Calls AgentPrompt to compose the prompt:

     ```python
     messages, response_format = agent_prompt.compose(input_payload)
     ```

   * Calls llm_client:

     ```python
     llm_raw_output = self.llm_client.chat(
         messages=messages,
         model_name=agent_prompt.model_name,
         temperature=agent_prompt.temperature,
         max_output_tokens=agent_prompt.max_output_tokens,
         response_format=response_format,
     )
     ```

   * Uses AgentPrompt to parse and validate the output:

     ```python
     labels = agent_prompt.parse(llm_raw_output)
     # labels: dict with system, audience, tone, depth, confidence
     ```

   * Runs deterministic checks and logging, updates SuperPrompt with the new labels, and returns to the Controller.

3. AgentFactory

   * Loads the JSON config for agent id `a2_promptshaper` and version `003`.
   * Resolves any catalog-backed decision-target expansions needed by the config.
   * Builds or reuses a configured AgentPrompt instance and returns it to A2.

4. AgentPrompt

   * Holds the agent’s configuration (from JSON): mode, static prompt fields, dynamic bindings, decision targets, output schema, model name, temperature, etc.
   * Is neutral: no A2-specific or agent-specific business logic.
   * When `compose(input_payload)` is called, it produces the LLM prompt (SYSTEM + USER messages) and the response-format object.
   * When `parse(raw_output)` is called, it parses and validates the LLM’s JSON against schema/enums/defaults and returns a clean Python dict.

5. llm_client

   * Low-level wrapper around the LLM API (OpenAI for now).
   * Only knows about `messages`, `model_name`, `temperature`, `max_output_tokens`, and optional `response_format`.
   * Does not know anything about agents or AgentPrompt.

3) Agent configuration data (JSON)

---

3.1. Storage format

* All agent configurations MUST be stored as **JSON** files.
* The primary reason: JSON is native to your LLM structured output, to OpenAI APIs, and to Python dicts; it avoids an extra format conversion layer.
* YAML is NOT required at this stage and MUST NOT be used for agent configs unless explicitly introduced later by a separate decision.

3.2. File layout (within RAGstream project)

* Agent config files currently live under the runtime/project data folder:

  * `data/agents/{agent_id}/{version}.json`

  Examples:

  * `data/agents/a2_promptshaper/003.json`
  * `data/agents/a3_nli_gate/001.json`
  * `data/agents/a4_condenser/chunk_phraser/a4_1_001.json`
  * `data/agents/a4_condenser/chunk_classifier/a4_2_001.json`
  * `data/agents/a4_condenser/final_condenser/a4_3_001.json`

* For ordinary agents such as A2 and A3, the exact path construction is the responsibility of AgentFactory; calling agents must not hard-code file paths.
* [24.04.2026] A4 is the explicit exception in the current implementation: `A4Condenser` loads its three nested JSON files by exact path because A4 is a fixed three-agent workflow rather than one normal `(agent_id, version)` lookup.
* The current AgentFactory derives its ordinary base path from the repository root and treats it as the single source of truth for standard runtime agent configs.

3.3. AgentConfig JSON schema (current implementation-aligned conceptual structure)

Each agent config JSON is currently expected to follow this conceptual structure:

```json
{
  "agent_meta": {
    "agent_id": "a2_promptshaper",
    "version": "003",
    "agent_type": "chooser"
  },

  "llm_config": {
    "model_name": "gpt-4.1-mini",
    "temperature": 0.0,
    "max_tokens": 256
  },

  "static_prompt": {
    "system_role": "You are A2 PromptShaper.",
    "agent_purpose": "Inspect task/purpose/context and choose labels.",
    "notes": ""
  },

  "dynamic_bindings": [
    {"id": "task", "required": true},
    {"id": "purpose", "required": false},
    {"id": "context", "required": false}
  ],

  "decision_targets": [
    {
      "id": "tone",
      "result_key": "tone",
      "options": ["direct", "friendly", "formal"],
      "default": "direct"
    }
  ],

  "output_schema": {
    "type": "object"
  }
}
```

Requirements:

* `agent_meta.agent_id` and `agent_meta.version` MUST match what the Agent passes to AgentFactory.
* The current code reads `agent_meta.agent_type` and maps conceptual aliases into runtime modes. In particular:

  * `chooser` -> runtime mode `selector`
  * `multi-chooser` / `multi_chooser` -> runtime mode `classifier`

* The current live compose/parse path actively supports runtime modes `selector`, `classifier`, and the A4 synthesizer-style path used by the condenser JSONs.
* The broader conceptual families Writer / Extractor / Scorer may appear in code comments or future config vocabulary, but they must not be described as separate active runtime branches unless the code path explicitly supports them.
* `static_prompt`, `dynamic_bindings`, `decision_targets`, `llm_config`, and `output_schema` are the current primary config blocks consumed by `AgentPrompt.from_config(...)`.
* The current code still supports limited backward-compatible fallbacks when some configs use older names such as `prompt_profile` instead of `static_prompt`, or `fields` instead of `decision_targets`.
* `output_schema` defines the structured response target. In the current code path the response format sent to the LLM is `{"type": "json_object"}`, while schema/enums/defaults are enforced during parse/validation.
* `decision_targets` are the source of enums, defaults, cardinality, and option metadata for selector/classifier behavior.
* `model_name` MUST match an OpenAI model name or fine-tuned model id.
* [24.04.2026] `model_name` is the required key used by `AgentPrompt.from_config(...)`. The older or incorrect key `model` must not be documented as the active model-name source.
* `temperature` and `max_tokens` / `max_output_tokens` are basic numeric parameters. Additional per-agent runtime choices such as `prompt_cache_key` and `reasoning_effort` are handled by the calling agent/helper and `llm_client`, not by ad-hoc JSON fields unless explicitly introduced.

Future extension: if you later need multiple providers (OpenAI, local TinyLlama, etc.), a `provider` field can be introduced, but it is not part of this current requirement.

3.4. Current and future agent additions

The following agent additions are part of the current or agreed future direction and must remain compatible with this Agent Stack:

* `NLP_Splitter`

  * Purpose: read retrieval-relevant prompt fields and split a long prompt into several meaning-based subqueries under a configured upper token limit.
  * Expected mode family: Writer or Extractor, depending on the final chosen schema.
  * Expected output shape: a JSON object containing an ordered list of subqueries.

* `A3_NLI_Gate`

  * Current practical truth: A3 is already a live consumer of the Agent Stack.
  * Current implemented direction: inspect multiple reranked chunks at the same time and assign one usefulness label per chunk as part of one structured set-level decision.
  * Conceptual mode family: Multi-Chooser.
  * Current runtime mode mapping: `classifier`.
  * Expected output shape: one JSON object containing one global `selection_band` plus `item_decisions`, where each candidate chunk receives a usefulness label such as `useful`, `borderline`, or `discarded`.

* `A4_Condenser`

  * [24.04.2026] Current practical truth: A4 is already a live condenser stage built on `AgentPrompt` plus `LLMClient.responses(...)`.
  * [24.04.2026] Current implemented direction: run three exact JSON-defined A4 prompt objects — chunk phraser, chunk classifier, and final condenser — through one high-level `A4Condenser` workflow.
  * [24.04.2026] A4 does not use ordinary `AgentFactory.get_agent(...)` resolution for its three sub-agents; it loads exact JSON paths and creates the three `AgentPrompt` objects directly.
  * Expected output shape of the final condenser: one JSON object containing `s_ctx_md`.

4. AgentFactory (agent_factory.py)

---

4.1. Purpose

AgentFactory is responsible for:

* Mapping `(agent_id, version)` to the correct JSON config file.
* Loading and parsing the JSON into an internal configuration dict.
* Resolving external catalog references inside `decision_targets`.
* Constructing and returning a configured AgentPrompt instance, with transparent config-level caching in the current implementation.

AgentFactory MUST NOT:

* Contain any agent-specific logic (no A2-only special cases).
* Call llm_client directly.
* Compose prompts by itself.

4.2. Statelessness

* AgentFactory MUST remain neutral and free of agent business state.
* The current implementation keeps a transparent read-only cache of `AgentPrompt` instances keyed by `(agent_id, version)`. This cache is allowed because it reuses immutable configuration objects and does not introduce agent business memory.

4.3. Public interface

AgentFactory MUST provide at least these public functions or class methods conceptually aligned with the current code:

```python
AgentFactory.load_config(
    agent_id: str,
    version: str,
) -> dict

AgentFactory.get_agent(
    agent_id: str,
    version: str = "001",
) -> AgentPrompt

AgentFactory.clear_cache() -> None
```

Behavior:

1. Resolve the config path:

   * Deduce `data/agents/{agent_id}/{version}.json` according to the runtime path convention.
   * If the file does not exist, raise a clear error.

2. Load and parse JSON:

   * Parse JSON to Python dict.
   * Verify that the top-level structure is a dict/object.

3. Resolve external catalog blocks when needed:

   * If a decision target stores its `options` as a string path to a catalog JSON file, AgentFactory resolves that path relative to the main config file.
   * The resolved catalog block is converted into inline `options` and copied defaults where applicable.
   * This resolution is still neutral because it is purely config loading and resolution, not business logic.

4. Build AgentPrompt:

   * `load_config(...)` returns the resolved config dict.
   * `get_agent(...)` returns a configured `AgentPrompt` created via `AgentPrompt.from_config(config)`.
   * If the same `(agent_id, version)` was already requested, the cached AgentPrompt may be returned.

5. Input-payload validation:

   * In the current code, shallow required-input validation primarily happens at AgentPrompt compose time via `dynamic_bindings`.
   * AgentFactory itself remains focused on config loading/resolution, not on deep payload semantics.

5) AgentPrompt (agent_prompt.py)

---

5.1. Purpose

AgentPrompt is the **neutral prompt engine**.

Responsibilities:

* Hold the agent configuration (as passed from AgentFactory).
* Compose the LLM prompt (SYSTEM + USER message) for a given `input_payload`, using a fixed neutral pattern.
* Provide the `response_format` for structured output.
* Parse and validate the LLM’s raw output into a clean Python dict, enforcing enums, defaults, and required fields.

AgentPrompt MUST NOT:

* Know which concrete agent (A2, A3, etc.) is calling it, beyond the strings in config.
* Contain any logic specific to A2 or any other concrete agent.
* Perform retrieval, reranking, or any pipeline-level decisions.
* Call llm_client directly.

5.2. Statelessness and neutrality

* AgentPrompt instances are **configuration holders**, not conversation memories.
* They MUST NOT store any per-call state (no incremental history).
* All per-call data (`input_payload`, `active_fields`, `raw_output`) MUST be passed as parameters to methods.
* AgentPrompt MUST use the same composition pattern for all agents; the only differences come from the config fields and current runtime mode.

5.3. Configuration fields

An AgentPrompt instance MUST hold the following current implementation-aligned configuration:

* `agent_name: str`
* `version: str`
* `mode: str` (current runtime mode such as `selector`, `classifier`, or A4 synthesizer-style mode)
* `static_prompt: dict`
* `dynamic_bindings: list[dict]`
* `decision_targets: list[dict]`
* `output_schema: dict`
* `enums: dict[str, list[str]]`
* `defaults: dict[str, Any]`
* `cardinality: dict[str, str]`
* `option_descriptions: dict[str, dict[str, str]]`
* `option_labels: dict[str, dict[str, str]]`
* `model_name: str`
* `temperature: float`
* `max_output_tokens: int`

These are passed from `AgentPrompt.from_config(...)` and then remain read-only.

5.4. Public methods

AgentPrompt MUST provide at least these public methods:

### 5.4.1. from_config(config: dict) -> AgentPrompt

Responsibilities:

* Read `agent_meta`, `llm_config`, `static_prompt`, `dynamic_bindings`, `decision_targets`, and `output_schema`.
* Support the current fallback compatibility behavior where older config names may still be mapped into the current internal structure.
* Normalize conceptual agent-type aliases such as `chooser` -> `selector` and `multi-chooser` -> `classifier`.
* Build a configured AgentPrompt instance.

### 5.4.2. compose(input_payload: dict, active_fields: list[str] | None = None) -> (messages: list[dict], response_format: dict)

Responsibilities:

* Build the SYSTEM message text from the static prompt fields carried by the config.
* Keep traceability information such as `agent_name` and `version` in the composed prompt.

* Build the USER message text from `dynamic_bindings` + runtime payload.

  * In current live code:

    * runtime mode `selector` builds a chooser-style prompt over configured decision targets and active fields,
    * runtime mode `classifier` builds a multi-item structured prompt over the configured decision targets and output schema,
    * the A4 synthesizer-style path builds a structured synthesis prompt from dynamic bindings and required output instructions.

  * Separate Writer / Extractor / Scorer branches must not be treated as active requirements unless they are explicitly wired in code.

* Validate required `dynamic_bindings` before prompt composition. Missing required bindings raise `AgentPromptValidationError`.
* Return:

  * `messages`: list of dicts for llm_client, for example:

    ```python
    [
      {"role": "system", "content": "...constructed SYSTEM text..."},
      {"role": "user", "content": "...constructed USER text..."}
    ]
    ```

  * `response_format`: in the current code path, `{"type": "json_object"}`.

### 5.4.3. parse(raw_output: Any, active_fields: list[str] | None = None) -> dict

Input:

* `raw_output` is the raw LLM content returned by llm_client (typically a string).

Responsibilities:

* Extract the JSON object from the LLM response.

* Validate against the current output contract:

  * for `selector` mode, normalize fields against enums/defaults/cardinality;
  * for `classifier` mode, normalize top-level fields plus per-item decisions using the configured schema mappings and enums/defaults.

* Return a clean Python dict representing the agent output.

If validation fails:

* Raise a clear error such as `AgentPromptValidationError`.

### 5.4.4. Convenience properties

The current code also exposes:

```python
agent_prompt.model
agent_prompt.max_tokens
```

as read-only convenience aliases for `model_name` and `max_output_tokens`.

6. llm_client (llm_client.py)

---

6.1. Purpose

llm_client is the lowest-level LLM access layer.

Responsibilities:

* Provide simple functions to call the LLM with:

  * `messages`
  * `model_name`
  * `temperature` where supported
  * `max_output_tokens`
  * optional `response_format`
  * optional `prompt_cache_key`
  * optional `reasoning_effort` for the Responses path

* Hide OpenAI API details from agents, AgentPrompt, and AgentFactory.
* Return raw content that AgentPrompt can parse.
* [24.04.2026] Extract and log token/cache usage metadata where the provider response exposes it.

llm_client MUST NOT:

* Know about agents, AgentPrompt, SuperPrompt, or pipeline steps.
* Interpret system_text, enums, or any config semantics.
* Do prompt composition.

6.2. Current provider and future-proofing

* For now, llm_client MUST call OpenAI models through the OpenAI Python client.

* It MUST support both:

  * base models (e.g. `gpt-4.1-mini`, `gpt-5-mini`)
  * fine-tuned models (e.g. `ft:gpt-4.1-mini-2025-04-14:personal:a2-promptshaper-v1:XXXX`)

* [24.04.2026] It must support both the Chat Completions path (`chat(...)`) and the Responses API path (`responses(...)`).
* The interface MUST be designed so that, later, additional backends can be implemented behind the same abstraction without changing A2, A3, A4, AgentFactory, or AgentPrompt.

6.3. Public interface

llm_client MUST provide at least these functions with conceptual signatures aligned to the current code:

```python
llm_client.chat(
    *,
    messages: list[dict],
    model_name: str,
    temperature: float,
    max_output_tokens: int,
    response_format: dict | None = None,
    return_metadata: bool = False,
    prompt_cache_key: str | None = None,
    prompt_cache_retention: str | None = None,
) -> Any

llm_client.responses(
    *,
    messages: list[dict],
    model_name: str,
    max_output_tokens: int,
    reasoning_effort: str | None = None,
    return_metadata: bool = False,
    prompt_cache_key: str | None = None,
    prompt_cache_retention: str | None = None,
) -> Any
```

Behavior:

* Build the appropriate payload for the OpenAI Chat Completions or Responses API client, including:

  * `messages`
  * `model_name`
  * `temperature` where supported
  * `max_output_tokens`
  * optional `response_format` for the chat path
  * optional `prompt_cache_key`
  * optional `reasoning_effort` for the Responses path

* In the current implementation, `gpt-5*` reasoning models are treated specially and temperature is not sent for those models.
* [24.04.2026] `responses(...)` must only send the `reasoning` object if `reasoning_effort` is explicitly provided. If it is omitted or `None`, no `reasoning.effort` field is sent.
* [24.04.2026] If a composed prompt contains only a system message, the Responses wrapper must still provide valid `input`; the implemented fix moves the instruction text into `input` and clears `instructions` for that call.
* [24.04.2026] `prompt_cache_key` may be passed to improve cache routing. `prompt_cache_retention` must not be passed in the current runtime until the installed SDK/API path accepts it.
* Send the request and return the raw response content as a string (or stringified content) so that `AgentPrompt.parse(...)` can validate it.
* [24.04.2026] The client must log model name, input tokens, cached input tokens, output tokens, and reasoning/status fields where available.

7. Non-functional requirements

---

7.1. Determinism and testability

* AgentFactory, AgentPrompt, and llm_client MUST be deterministic given the same inputs and config.
* No timestamps, randomness (except the LLM itself), or hidden global state may influence their behavior.
* Unit tests MUST be possible for each layer:

  * AgentFactory: config validation, error handling.
  * AgentPrompt: composition and validation logic using fake inputs and fake LLM outputs.
  * llm_client: can be tested via mocking the HTTP layer.

7.2. Extensibility and versioning

* Adding a new agent or version MUST require creating a new JSON file only; existing code in AgentFactory / AgentPrompt / llm_client should remain unchanged.
* If output schema changes in an incompatible way, a new `version` MUST be introduced (e.g. `"v2"`), and the old JSON MUST NOT be silently overwritten.

7.3. Logging (minimal expectations)

* Agents (e.g. A2, A3) are responsible for logging their own inputs and outputs.
* AgentStack components SHOULD provide enough structured data so that agents can log:

  * `agent_name`, `version`, `model_name`
  * composed SYSTEM/USER messages (if desired)
  * raw LLM output and validated output

* In the current code path, AgentPrompt already logs the composed SYSTEM and USER prompt text via `SimpleLogger`.
* llm_client itself SHOULD at least log errors and basic metrics where available. [24.04.2026] The current implementation logs model name, input tokens, cached input tokens, output tokens, and reasoning/status fields where available; fuller logging governance can still be defined in a separate document.

---

This completes the requirements for the Agent Stack: AgentFactory, AgentPrompt, and llm_client.
