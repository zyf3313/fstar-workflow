# fstar optional capabilities

These packages are **off unless the user authorizes them**. They exist so the
workflow can grow beyond the minimal loop; never assume one is on.

When a conversation need matches a package, explain its benefit and cost and
recommend only the highest-value one. Do not enable anything yourself.

- `project-governance` — read and write specs, knowledge, rules, and memory.
  Needed when the user states a durable convention or asks to remember
  something across sessions. Writes still require the learn proposal,
  proposal hash, and the user's exact confirming quote.
- `planning-review` — clarify requirements and produce plan, clarify, and
  criteria documents, with editor and document-check roles. Needed when work
  is more than a trivial fix: requirements must be settled and persisted
  before implementation, or when the user hands over a planning document that
  must be stored into the task directory. There is no fixed document set:
  formal deliveries need criteria; plan and clarify documents follow the
  item's uncertainty and hand-off needs.
- `persistent-task` — keep task state across sessions, including recovery and
  archive workflows. Needed when work spans sessions, must survive context
  compaction or machine changes, or when interrupted dispatches need
  takeover/recovery bookkeeping.
- `multi-agent` — bounded research and parallel implementation by sub-agents.
  Needed when the task needs evidence gathered in the background or multiple
  independent write scopes at once. Includes the `steward` member for the
  fstar-steward role (task lifecycle operations and first-draft task-document
  creation), which the coordinator's pure-dispatch mode relies on.

The project index (`.fstar/index.md`) and user index (`~/.fstar/index.md`) are
injected read-only at session start regardless of grants. Writing to those
surfaces is not implied by reading them; only `fstar init` may backfill a
generated placeholder index without a separate approval.

## External capability classes

Four external capability classes are reached through thin read-only probe +
handshake adapters; none of them is required, and each has an explicit
fallback the workflow always keeps working with:

- session management (external session keepers) — fallback: the main
  session, with fstar's own role separation unchanged.
- distribution (delivering fstar skills to agents without a native
  channel) — fallback: the native fstar skills/hooks entries. The existing
  Magpie library hand-over is this class's actual implementation; it runs
  only at install/update time and never during a task.
- memory (durable knowledge storage outside the project data root) —
  fallback: the existing local knowledge storage under the fstar data root.
- scheduling (external schedulers/triggers) — fallback: manual driving; the
  coordinator or user initiates every action. No scheduler integration
  exists in this version.

A probe or handshake success NEVER constitutes authorization, never
performs an external action or installation, and never widens a grant. A
missing provider, a failed probe, or an incompatible handshake simply
degrades to the fallback listed above; the core keeps running unchanged.
