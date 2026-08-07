# GHOST Python Coding Standard

## Purpose

This document defines the mandatory design and implementation rules for all Python code in GHOST. The goal is professional, simple, readable, testable code with a visible ownership hierarchy and without unnecessary abstraction.

## Priority

The rules are applied in this order:

1. **Non-negotiable rules** override all other guidance.
2. **Refinement rules** improve quality when they do not conflict with the non-negotiable rules.
3. Existing GHOST architecture, requirements, interfaces, and behavior must be preserved unless a change is explicitly requested.

---

# I. Non-Negotiable Rules

## 1. Design the module as a visible tree

Every module must have one clear root responsibility. Its structure must be easy to understand from top to bottom:

```text
Module responsibility
└── Primary class or primary workflow
    ├── Main method 1
    │   ├── Private helper
    │   └── Private helper
    ├── Main method 2
    └── Main method 3
```

Do not create a flat collection of unrelated classes, functions, or methods. A reader must be able to identify the module root, its public workflow, and its internal helpers immediately.

## 2. Prefer one primary class per module

A module should normally contain one primary class.

Additional classes are allowed only when they directly support the primary class, such as:

* one small immutable data object;
* one enum;
* one or two exceptions that cause genuinely different caller behavior.

Do not place multiple independent service classes in one module. Do not use nested classes.

## 3. Keep the public workflow small

A primary class may normally expose no more than **4 or 5 main public methods**.

These methods must represent the real operations of the class. Constructors, simple properties, serialization methods, and protocol-required methods may be treated separately when justified.

If the class needs more public operations, first check whether it owns more than one responsibility and should be split.

## 4. Use only a few meaningful helpers

Private helper methods or functions are allowed only when they:

* isolate a coherent internal operation;
* remove meaningful duplication;
* isolate external I/O or a complex algorithm;
* materially improve readability or testing.

Do not extract every validation, conversion, or three-line block into a separate helper. Main methods and private helpers must be visibly separated in the file.

As a review threshold, a focused class should normally remain below **10 total meaningful methods**. A class approaching 20 parallel methods must be redesigned or split.

## 5. Keep modules within the size boundary

The normal maximum size of one Python module is **500 lines**, including comments and docstrings.

* Up to 500 lines: allowed when the module remains coherent.
* 501–600 lines: exceptional; warn before writing and justify why one module is still better than a split.
* Above 600 lines: do not write it as one module; split by responsibility.

Do not use compressed formatting, removed documentation, or dense expressions merely to stay below the limit.

## 6. Split by responsibility, not by arbitrary size

When a module must be split, create a semantically named companion module that owns a real sub-responsibility.

Prefer:

```text
memory_manager.py
memory_record.py

super_prompt.py
superprompt_projector.py

auth.py
auth_http.py
```

Avoid vague dumping grounds such as:

```text
utils.py
common.py
misc.py
helpers.py
```

A companion module must have its own clear root and must not become a container for unrelated leftovers.

## 7. Do not create speculative abstractions

Do not add a `Protocol`, abstract base class, factory, strategy, adapter, registry, plugin layer, generic provider layer, or dependency-injection framework unless at least one of these conditions is true:

* two real implementations already exist;
* an explicit requirement demands replaceability;
* a real external boundary must be substituted in tests;
* the existing GHOST architecture already defines that abstraction.

Do not build infrastructure for hypothetical future use. Use the current library or concrete implementation directly when that is sufficient.

## 8. Preserve existing architecture and behavior

Before writing or modifying code, inspect the relevant requirements, architecture, neighboring modules, call sites, and tests.

Do not:

* invent new architecture silently;
* rename public interfaces without instruction;
* change unrelated behavior;
* refactor neighboring modules merely because another style is possible;
* duplicate functionality that already exists in GHOST or in a trusted dependency.

Project consistency has priority over personal style preferences.

## 9. Make control flow explicit and readable

Code must favor explicit, straightforward control flow over cleverness or compression.

Use:

* descriptive names;
* early validation and clear failure paths;
* simple loops and conditions;
* direct library calls;
* typed inputs and outputs at module boundaries.

Avoid:

* deeply nested control flow;
* complicated comprehensions;
* hidden side effects;
* dynamic behavior when static code is sufficient;
* broad exception handling outside a deliberate external boundary.

A long coherent method is better than many meaningless micro-methods, but a method that mixes several responsibilities must be split.

## 10. Verify behavior before declaring completion

Every implementation must be checked against its intended behavior.

At minimum:

* validate normal behavior;
* validate important boundary and failure cases;
* preserve existing tests;
* add focused tests for new behavior;
* run the relevant test command when execution is available;
* report honestly what was and was not verified.

Tests must verify observable behavior, not internal ceremony created only for the tests.

---

# II. Refinement Rules

## A. File organization

Use a predictable top-to-bottom order:

```text
module docstring
imports
constants
small data objects / enums / exceptions
primary class
    constructor
    public/main methods
    private helpers
small module-level boundary functions, only when justified
```

Do not scatter public and private methods randomly through the class.

## B. Functions and methods

Each function or method must have one coherent purpose and one meaningful name. Keep parameters limited and explicit. Group related values into a data object only when that object represents a real concept.

Do not use nested functions merely to hide helpers. A nested function is acceptable only when it genuinely closes over local state and improves clarity.

## C. Data and state

Keep state ownership explicit. Mutable state should belong to the class responsible for its lifecycle. Prefer immutable dataclasses for stable result or configuration objects.

Do not create data classes that only rename an existing dictionary without adding validation, meaning, or safer behavior.

## D. Errors and logging

Create distinct exception types only when callers must react differently. Preserve the original exception as the cause when translating errors at a boundary.

Do not catch `Exception` broadly except at a deliberate external boundary where errors must be sanitized, logged, or converted into a stable interface response.

Log meaningful lifecycle events, boundary failures, and operational decisions. Do not log every local variable or duplicate the same error at multiple layers.

## E. Documentation and code comments

Every production module must begin with a concise module docstring that gives the reader an immediate map of the file.

The opening module docstring must contain:

1. one short paragraph explaining what the module does and where its responsibility ends;
2. the primary class or classes, each with a one-line explanation of what it represents and why it exists;
3. the main public methods or module-level functions, each with a one-line explanation of what it does;
4. only essential notes about external dependencies, important assumptions, side effects, or constraints.

The opening documentation must remain compact. It must not become a tutorial, design report, change history, or repeated description of obvious code.

Recommended structure:

```python
"""Short paragraph describing the module's responsibility and boundary.

Main classes:
    ExampleClass:
        Owns the main workflow and coordinates the module's responsibility.

Main methods:
    run():
        Executes the primary workflow.
    validate():
        Checks the required input before execution.

Important notes:
    Uses an external service and may raise ExampleError when unavailable.
"""
```

Public classes must have short docstrings that explain their responsibility and why they exist.

Main public methods must have short docstrings when their purpose, contract, side effects, return value, or failure behavior is not fully obvious from the method name and type signature.

Private helpers need comments or docstrings only when their logic, purpose, constraint, or reason is non-obvious.

Comments and docstrings must explain:

* purpose;
* responsibility;
* important decisions;
* constraints;
* non-obvious behavior;
* reasons for unusual implementation choices.

Comments and docstrings must not:

* narrate each visible code line;
* repeat the class, method, or variable name;
* describe trivial assignments;
* add decorative section noise;
* contain speculative future plans;
* contain unnecessary meta-commentary;
* duplicate information already clear from types and names.

Documentation must be sufficient for a reader to understand the module's purpose, main classes, main methods, and architectural role without reading every implementation line.

## F. Dependencies

Use the Python standard library and established project dependencies before implementing equivalent infrastructure manually. Add a new dependency only when its value clearly exceeds its maintenance and security cost.

External clients, clocks, databases, filesystems, model APIs, and network services may be injected when substitution is genuinely useful for testing. Do not inject pure local operations unnecessarily.

## G. Types and interfaces

Use type hints for public functions, class methods, configuration objects, and external boundaries. Avoid highly complex type expressions that reduce readability.

Keep the public API minimal. Private implementation details must remain private unless another module genuinely needs them.

## H. Change discipline

For an existing file:

* make the smallest coherent change that fully satisfies the requirement;
* preserve established naming and structure where they remain sound;
* avoid unrelated cleanup;
* return the complete updated file when a complete-file replacement is requested;
* do not claim completion until imports, syntax, and relevant tests have been checked.

---

# III. Mandatory Design Gate Before Writing Code

Before generating a new module or performing a substantial rewrite, determine:

```text
1. What is the single root responsibility?
2. What is the primary class or workflow?
3. What are its maximum 4–5 main operations?
4. Which helpers are genuinely necessary?
5. Which existing GHOST modules or libraries already provide part of the behavior?
6. Will the file remain under 500 lines?
7. If not, what real responsibility belongs in a companion module?
```

Do not begin implementation until this tree is coherent.

---

# IV. Final Compliance Check

Before returning Python code, verify:

```text
[ ] One clear module root exists.
[ ] One primary class or workflow is obvious.
[ ] Public/main methods do not exceed 4–5 without explicit justification.
[ ] Helpers are few, private, meaningful, and visibly separated.
[ ] No speculative abstraction or unnecessary wrapper was added.
[ ] The module is within the 500-line normal limit.
[ ] Existing GHOST architecture and behavior were preserved.
[ ] The module begins with the required concise documentation map.
[ ] Main classes and main methods are briefly explained.
[ ] Comments explain purpose and decisions without creating noise.
[ ] Relevant behavior was tested or the verification limitation was stated.
```

If any item fails, redesign before presenting the code.
