---
schema: fstar.knowledge.v1
type: memory
status: active
kind: preference
trust: confirmed
---

# Memory title

Record the confirmed preference or lesson in English.
APPLIES: define the scope.
NOT: define exclusions.
SOURCE: provide a traceable source.

## Optional experience fields

The five fields below are optional; omit any that does not apply rather than
inventing a value. Every value is one strict scalar string.

- `scope: personal | scenario:<id> | item:<id>` — how far the memory reaches.
  Omit it (or use `personal`) when the memory applies broadly; a scenario or
  item memory is injected only when the current reading carries that exact
  scope tag.
- `confidence: explicit-request | inferred | verified` — why the memory
  exists. `inferred` records a guess the agent formed; it never upgrades
  itself to a rule. Omit when the provenance is simply the confirmed source
  below.
- `source: <reference>` — the durable provenance (task, conversation, or
  review reference). Omit when there is no traceable reference; do not
  fabricate one.
- `expires: YYYY-MM-DD` — a machine-judgeable calendar date. On and after
  that date the memory stops being injected. Omit when there is no known
  expiry; do not pick an arbitrary date to fake a policy.
- `conditions: <natural language>` — prose applicability conditions ("only
  while the legacy deployment flow is in use"). The system never judges this
  text itself: the memory stays excluded with an `unknown` judgement until
  the user explicitly decides it applies. Omit when no such condition
  exists.

Example (only when the values are real):

```
scope: scenario:payments
confidence: inferred
source: task-payments-042
expires: 2030-01-01
conditions: only while the legacy deployment flow is in use
```
