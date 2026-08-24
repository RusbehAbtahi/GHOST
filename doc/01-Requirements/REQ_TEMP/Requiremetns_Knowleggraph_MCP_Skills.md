# GHOST Knowledge Graph — Initial Architecture Requirements and Stakeholder Wishes

## 1. Purpose and architectural direction

GHOST shall introduce a reusable Knowledge Graph architecture whose first practical pilot is **MCP CLI Skills**, but whose backbone must remain suitable for substantially more complex future domains such as:

* Requirements
* Python code
* Architecture
* UML
* Tests
* Configuration
* Memory
* other engineering knowledge

The first implementation shall therefore remain simple enough for `CLI_SKILLS`, while establishing boundaries that do not need to be redesigned when more complicated knowledge domains are introduced.

The main reusable architectural pattern is:

```text
RAW DOMAIN MATERIAL
        ↓
DOMAIN-SPECIFIC PREPARATION
        ↓
NORMALIZED RAGMEM KNOWLEDGE OBJECTS
        ↓
STATELESS / DOMAIN-NEUTRAL KG BACKBONE
        ↓
NEO4J
```

The KG backbone shall not understand the business meaning of a Skill, Requirement, Python class, UML element, Test or Memory episode.

Domain understanding belongs **before** the KG backbone.

---

# 2. Existing GHOST architecture as reference

Three existing GHOST subsystems are considered architectural reference patterns for future development.

### 2.1 Memory — primary reference

The Memory architecture is the strongest reference because it combines:

* one durable source of truth,
* stable IDs,
* append-oriented historical records,
* separate mutable metadata,
* SQLite indexing,
* vector representations,
* multiple retrieval behaviors,
* late materialization of full content,
* separation between authoritative information and derived representations.

The Knowledge Graph architecture should preserve this practical separation wherever applicable.

### 2.2 Agent Stack / AgentFactory — stateless reference

The Agent Stack is a reference for building neutral, reusable services.

The KG backbone should follow the same general principle:

> Receive all necessary state for one operation, perform the operation, persist the result externally, and retain no domain-specific mutable process state.

### 2.3 TextForge — simple interface / multiple controlled actions

TextForge is a reference for providing a simple public interface while allowing multiple configured internal actions to occur automatically.

The KG architecture should similarly keep its public operations small and understandable even if persistence, vector search, validation and maintenance operations happen underneath.

---

# 3. Knowledge Graph fundamentals

GHOST shall use **Neo4j** as its graph database.

The fundamental graph vocabulary is:

```text
Node
Relationship
Triple
Path
```

A Triple is:

```text
Node ──Relationship──> Node
```

A Path is formed automatically when multiple stored triples connect:

```text
A → B
B → C

therefore:

A → B → C
```

The connected path does not need to be stored separately.

Traversal depth is explicit:

```text
1 hop from A → A → B
2 hops from A → A → B → C
```

Nodes and Relationships may contain properties such as descriptions and identifiers.

A Path itself is a traversal/result structure and does not have its own persistent properties unless GHOST explicitly models that higher-level concept as another graph object.

---

# 4. Main functional decomposition

The Knowledge Graph work is divided into **three main parts**:

```text
1. Graph Generation
2. GraphRAG
3. Graph Maintenance
```

Graph Generation and GraphRAG are themselves divided into two clearly different responsibilities.

---

# 5. Part 1 — Graph Generation

Graph Generation is divided into:

```text
1A. Domain-Specific Knowledge Preparation
1B. Generic Stateless KG Backbone
```

This distinction is essential.

---

## 5.1 Part 1A — Domain-Specific Knowledge Preparation

Different knowledge domains require different preparation before they can enter the generic graph system.

### CLI Skills

`CLI_SKILLS` is the first pilot because almost everything already exists:

```text
Skill RagMem Episode
        ↓
Stable Record ID
Title
Description
Complete Episode
Description Vector
Source / Collection
```

Very little additional preparation is necessary.

### Requirements

A Requirement may already provide:

```text
UID
Requirement text
Description
Source document
```

This can be transformed into a graph-ready RagMem representation.

### Python

Raw Python requires more preparation.

Possible preparation includes:

* identifying files, classes, functions or methods;
* creating stable identities;
* determining source references;
* generating semantic descriptions;
* extracting deterministic structural relationships.

The chosen granularity remains under GHOST/user control.

A Python artifact may therefore be represented as:

```text
whole file
```

or:

```text
file
 ├── class
 ├── class
 │    ├── method
 │    └── method
 └── function
```

The KG backbone shall not dictate this choice.

### UML / Architecture / Tests / Configuration

The same principle applies:

```text
Raw artifact
      ↓
domain-specific interpretation
      ↓
graph-ready RagMem knowledge object
```

The complexity belongs in this preparation layer, not inside the generic KG backbone.

---

# 6. RagMem as the normalized KG input contract

GHOST shall use **RagMem as the common representation presented to the Knowledge Graph backbone**.

This avoids building separate KG ingestion contracts for Skills, Python, Requirements, UML, Tests and other domains.

The conceptual flow is:

```text
Anything
   ↓
Domain-specific preparation
   ↓
RagMem
   ↓
KG Backbone
   ↓
Neo4j
```

A graph-ready RagMem record shall provide enough information to identify, understand, retrieve and materialize the represented knowledge object.

At minimum the architecture expects concepts such as:

```text
Stable ID
Type
Title
Description
Source
Q
A
Vector derived from semantic description
```

The exact existing RagMem representation should be reused rather than replaced with an independent KG-specific data format.

---

## 6.1 Meaning of Q and A for KG-ready RagMem

For this purpose:

### Q

`Q` describes the **nature, role or general meaning of A**.

It gives the knowledge object understandable semantic context.

### A

`A` may contain either:

```text
the complete content
```

or:

```text
a path / source reference to the authoritative content
```

This decision remains domain-specific.

Examples:

### CLI Skill

```text
Q:
What operational knowledge does this Skill contain?

A:
Complete Skill episode
```

### Python artifact stored by reference

```text
Q:
What does this Python class/function/file do?

A:
Path/reference to authoritative Python source
```

### Requirement

```text
Q:
What does this Requirement specify?

A:
Complete Requirement text
```

or, where appropriate:

```text
A:
Reference to authoritative StrictDoc Requirement
```

The original source remains authoritative when RagMem stores only a reference.

---

# 7. Semantic descriptions are required for high-quality semantic GraphRAG

A major conclusion of the design discussion is that **structural graph connectivity and semantic relevance are different things**.

GHOST may know deterministically that:

```text
A2.py ──READS──> A2.json
```

That establishes graph structure.

It does not by itself establish whether this path is more relevant to a natural-language query than nine other valid paths from `A2.py`.

Under equal conditions:

```text
Path 1
Path 2
Path 3
...
```

with:

* no distinguishing constraint,
* no additional metadata,
* no semantic information,

there is no meaningful deterministic way to decide which path is most relevant to a natural-language prompt.

Therefore:

> **Semantic path relevance requires semantic information somewhere in the participating Nodes and/or Relationships.**

For GHOST, semantic descriptions shall be the main representation used for this purpose.

Descriptions may be produced automatically by an LLM.

For code, this allows the system to combine:

```text
Deterministically discovered structure
+
LLM-generated semantic meaning
```

Example:

```text
A2.py
Description:
Implements the A2 PromptShaper workflow and loads
its configured agent definition.

        │
        │ READS
        ▼

A2.json
Description:
Defines PromptShaper configuration, model settings,
decision targets and prompt instructions.
```

The descriptions can then be embedded and used for semantic retrieval and path ranking.

---

# 8. Two kinds of Relationship creation

Graph Generation shall support both **deterministically asserted Relationships** and **semantically inferred Relationships**.

## 8.1 Deterministically known Relationship

If the relationship is explicitly known from source information, no LLM inference is necessary.

Example:

```python
# REQ-ABC-017
def calculate_something(...):
```

This can directly create:

```text
REQ-ABC-017
    ──IMPLEMENTED_BY──>
calculate_something()
```

Other deterministic relationships may come from facts already available during domain preparation.

These relationships should be created directly.

---

## 8.2 Semantically discovered Relationship

If no explicit relationship is known, GHOST may discover candidates semantically.

The first `CLI_SKILLS` pilot should follow a process similar to:

```text
New Skill
   ↓
Description Vector
   ↓
Compare against existing Node vectors
   ↓
Cosine similarity
   ↓
Top-N plausible candidates
   ↓
ChatGPT receives candidate descriptions
   ↓
ChatGPT requests full Episodes where necessary
   ↓
ChatGPT chooses an allowed Relationship
   ↓
GHOST validates decision
   ↓
Neo4j Relationship is persisted
```

Candidate count and similarity thresholds are configuration parameters, not architectural constants.

Examples discussed for the first Skill graph include concepts such as:

```text
RELATED_TO
PRECEDES / FOLLOWS
DUPLICATE_OF
VERY_SIMILAR_TO
MORE_COMPLETE_VERSION_OF
```

The final relationship vocabulary belongs to the Knowledge Base definition rather than being hard-coded into the generic Python backend.

---

# 9. Part 1B — Generic Stateless KG Backbone

After domain preparation, all knowledge enters the same neutral backbone.

Conceptually:

```text
Receive/register graph-ready RagMem Node
        ↓
Persist / update Node
        ↓
Find semantic candidate Nodes when requested
        ↓
Accept deterministic or LLM-selected Relationships
        ↓
Validate against Knowledge Base definition
        ↓
Persist Relationships
```

The backbone shall not contain logic such as:

```text
if object is Python...
if object is Requirement...
if object is Skill...
```

It shall work from normalized information such as:

```text
knowledge_base_id
node_id
node_type
title
description
embedding
source_reference
version
```

Persistent state belongs in:

* RagMem / source artifacts,
* vector storage/indexes,
* Neo4j.

The Python service itself remains stateless.

---

# 10. Multiple Memory Collections

The KG backbone shall **not assume that one Knowledge Base corresponds to one Memory Collection**.

The first `CLI_SKILLS` pilot may remain a single collection.

Larger future knowledge domains may use many collections, for example:

```text
Requirements
Python
Tests
UML
Configuration
Architecture
```

The KG backbone shall therefore be able to consume a **folder/root containing multiple eligible RagMem collections**.

Conceptually:

```text
Folder of RagMem Collections
          ↓
Eligible RagMem records
          ↓
Generic KG Backbone
          ↓
Neo4j
```

The collection layout must not change the graph-generation logic.

---

# 11. Part 2 — GraphRAG

GraphRAG is divided into:

```text
2A. Candidate Node / Path Retrieval
2B. Context Materialization and Retrieval Execution
```

The distinction is important because **Part 2B is designed to work identically whether ChatGPT controls it through MCP or GHOST controls it internally later.**

---

# 12. Part 2A — Candidate Node and Path Retrieval

The first responsibility is to identify graph structures that may be relevant.

The process consists conceptually of:

```text
Natural-language Prompt
        ↓
Semantic retrieval of starting Nodes
        ↓
Candidate Relationships / Paths around those Nodes
        ↓
Semantic ranking of those candidates
        ↓
Top-N compact Paths
```

Starting-node retrieval is analogous to ordinary document retrieval:

```text
Document RAG
Prompt → relevant Chunks

GraphRAG
Prompt → relevant Nodes
```

The algorithms may use:

* vector similarity,
* hybrid methods,
* deterministic filters,
* other ranking mechanisms.

Neo4j can provide vector indexes and graph traversal.

The KG backend does not need to implement its own low-level cosine-search database if Neo4j already provides the needed capability.

---

## 12.1 Path relevance

After a starting Node is found, it may have many possible outgoing or incoming paths.

Example:

```text
                 → Path A
                /
Starting Node ──→ Path B
                \
                 → Path C
                 → ...
```

Structural existence does not determine semantic relevance.

Therefore path ranking may use the semantic descriptions of:

* Relationship,
* target Node,
* source Node where useful.

A practical first approach may be:

```text
10 starting Nodes
       ↓
up to 5 semantically relevant candidate paths per Node
       ↓
maximum ~50 compact candidate paths before overlap removal
       ↓
LLM chooses the small number actually useful
```

These numbers are examples for the pilot and shall remain configurable.

The important principle is:

> **Generate candidates deterministically and cheaply; use semantic judgment only where relevance actually has to be decided.**

---

# 13. Part 2B — Context Materialization and Retrieval Execution

After relevant candidate paths exist, another decision is required:

```text
Which path should be expanded?
How deep should traversal go?
What underlying material should be loaded?
```

The deterministic GHOST backend shall provide operations that can execute instructions such as:

```text
Expand Node X by one hop
Expand Node Y by two hops
Retrieve content behind Node Z
Load referenced Python artifact
Load Requirement UID ABC
Load complete Skill episode
```

Neo4j performs traversal deterministically.

RagMem determines how the underlying content is materialized:

```text
A contains content
    → return content

A contains path/reference
    → load referenced authoritative artifact
```

This execution service must remain neutral.

---

# 14. MCP-first orchestration

The first implementation target is **MCP-based GraphRAG**.

In this mode:

```text
User
 ↓
ChatGPT
 ↓
GHOST MCP
 ↓
GraphRAG Part 2A
 ↓
candidate Nodes / Paths
 ↓
ChatGPT decides:
    - which Path matters
    - desired depth
    - which content is required
 ↓
GHOST GraphRAG Part 2B
 ↓
deterministic traversal/materialization
 ↓
ChatGPT
```

GHOST therefore does **not** initially need its own complete agentic GraphRAG reasoning loop.

ChatGPT performs semantic planning.

GHOST acts as the deterministic provider/executor.

This keeps the first implementation focused on the KG itself rather than prematurely implementing a complex internal retrieval orchestrator.

---

# 15. Future internal GHOST GraphRAG

Later, GHOST may use the same KG without MCP/ChatGPT controlling each retrieval decision.

The future internal architecture may perform:

```text
Initial Retrieval
      ↓
LLM evaluates available context
      ↓
LLM selects graph expansions/depth
      ↓
SAME deterministic GraphRAG Part 2B service
      ↓
Expanded context
      ↓
optional second LLM reasoning round
```

The essential compatibility requirement is:

> **The deterministic GraphRAG execution backend implemented for MCP today must remain reusable unchanged by GHOST's own future retrieval orchestrator.**

Only the decision-maker changes:

```text
TODAY:
ChatGPT → deterministic GHOST retrieval service

FUTURE:
GHOST internal orchestrator → same deterministic retrieval service
```

The underlying KG, RagMem records, traversal methods and content-materialization logic remain the same.

---

# 16. Context-size strategy

Document Retrieval, Memory Retrieval and Knowledge Graph Retrieval can all produce substantial context.

The KG shall therefore **not blindly multiply the existing context**.

Graph information should be introduced progressively.

A possible future internal GHOST flow established during the discussion is:

```text
ROUND 1

Main Prompt
+ Document Retrieval
+ Memory Retrieval
+ small number of compact KG Paths
        ↓
LLM
        ↓
1. summarize useful Memory + document evidence
2. identify required KG Paths
3. identify required traversal depth
```

Then:

```text
ROUND 2

Main Prompt
+ compact summary from Round 1
+ materialized information from selected KG Paths
        ↓
final reasoning
```

The original large document/memory context can therefore be replaced by a smaller synthesized representation before deeper graph information is added.

The main architectural principle is:

> **KG retrieval should compete for a bounded context budget rather than simply accumulate on top of all existing retrieved information.**

The exact token budget remains configurable and should be validated experimentally.

---

# 17. Content granularity remains under domain control

The KG backbone shall not force one content granularity.

For example, Python can be represented as:

```text
one whole file
```

or:

```text
one RagMem per class
```

or:

```text
one RagMem per function/method
```

or:

```text
a RagMem containing only a reference to the Python source
```

A large Python file may be supplied completely when the task genuinely requires it and the context budget permits it.

Fine-grained Nodes exist to allow **selective retrieval**, not because whole-file retrieval is inherently invalid.

---

# 18. Part 3 — Graph Maintenance

Graph Maintenance shall use the same general architectural philosophy as Graph Generation:

```text
Generic maintenance mechanism
        +
Knowledge-base-specific policy
```

The generic backend shall provide reusable operations.

The selected Knowledge Base determines what those operations mean for its domain.

---

## 18.1 CLI Skills maintenance

The Skills pilot may allow new Skills to be created relatively freely.

The graph can later discover relationships such as:

```text
Skill A ──DUPLICATE_OF──> Skill B

Skill C ──VERY_SIMILAR_TO──> Skill D

Skill E ──MORE_COMPLETE_VERSION_OF──> Skill C
```

The Skills maintenance policy may then:

* identify duplicates,
* consolidate overlapping Skills,
* create a more complete Skill from useful information in several episodes,
* retire redundant graph representations,
* preserve the most complete current Skill,
* update relationships accordingly.

The generic maintenance backend must not assume that `VERY_SIMILAR_TO` always means “merge”.

A Requirement Knowledge Base may interpret the same general situation very differently.

Therefore maintenance actions remain **knowledge-base policy**, not universal KG behavior.

---

# 19. Change and growth

Graph Generation and Graph Maintenance shall support an evolving Knowledge Base.

A newly added knowledge object should not require reprocessing the complete graph through an LLM.

For semantic relationship discovery:

```text
New Node
   ↓
its Description Vector
   ↓
compare/search against existing graph vectors
   ↓
Top-N candidate Nodes
   ↓
semantic relationship decision only for those candidates
```

Periodic maintenance may later perform broader reconciliation for:

* missing Relationships,
* stale descriptions,
* changed source versions,
* duplicates,
* superseded material,
* newly discovered semantic connections.

---

# 20. Knowledge Base configuration

Different Knowledge Bases may define different:

* Node types,
* Relationship types,
* permitted source/target combinations,
* traversal rules,
* maintenance policies.

These differences should remain configuration/domain policy rather than becoming branches throughout the generic KG backend.

A `CLI_SKILLS` Knowledge Base can therefore remain simple while a later Requirements–Code–Architecture Knowledge Base may contain much richer relationship semantics.

The generic backend remains the same.

---

# 21. Initial development order

The initial development sequence is:

```text
1. Establish the KG-ready RagMem contract.

2. Use CLI_SKILLS as the first pilot.
   Existing RagMem records already provide most required information.

3. Implement the generic stateless KG backbone.

4. Implement Neo4j Node/Relationship persistence.

5. Implement semantic candidate discovery for new Nodes.

6. Expose relationship-selection workflow through MCP/ChatGPT.

7. Implement GraphRAG Part 2A:
   starting Nodes + compact candidate Paths.

8. Implement GraphRAG Part 2B as a neutral deterministic
   traversal/materialization service.

9. Use ChatGPT through MCP as the first semantic orchestrator.

10. Implement generic maintenance methods plus
    CLI_SKILLS-specific maintenance policy.

11. Only later introduce richer domain preparation for
    Requirements, Code, UML, Tests and Architecture.

12. Only later, if required, implement GHOST's own internal
    adaptive GraphRAG orchestration.
```

---

# 22. Core architectural result

The target architecture is:

```text
                    DOMAIN SOURCES
                         │
       ┌─────────────────┼──────────────────┐
       │                 │                  │
     Skills            Python          Requirements/UML/...
       │                 │                  │
       └──────── DOMAIN-SPECIFIC PREPARATION ────────┘
                         │
                         ▼
                       RAGMEM
          ID + Type + Title + Description
           Q + A + Source + Semantic Vector
                         │
                         ▼
          ┌──────────────────────────────┐
          │   STATELESS KG BACKBONE      │
          │                              │
          │ Node registration            │
          │ Candidate discovery          │
          │ Relationship validation      │
          │ Neo4j persistence            │
          │ Maintenance mechanisms       │
          └──────────────────────────────┘
                         │
                         ▼
                       NEO4J
                         │
           ┌─────────────┴──────────────┐
           │                            │
           ▼                            ▼
    GraphRAG Part 2A             Graph Maintenance
 Candidate Node/Path             generic mechanism
      retrieval                  + KB-specific policy
           │
           ▼
    GraphRAG Part 2B
 deterministic expansion /
 content materialization
           │
     ┌─────┴─────────────┐
     │                   │
     ▼                   ▼
ChatGPT via MCP      Future GHOST
    TODAY             Orchestrator
                           LATER
```

The central compatibility principle is:

> **Domain intelligence prepares knowledge. RagMem normalizes it. The KG backbone stores and connects it. GraphRAG retrieves it. The semantic orchestrator may change, but the deterministic GHOST backbone should not.**
