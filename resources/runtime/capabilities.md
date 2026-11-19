# fstar optional capabilities

These packages are **off unless the user authorizes them**. They exist so the
workflow can grow beyond the minimal loop; never assume one is on.

When a conversation need matches a package, explain its benefit and cost and
recommend only the highest-value one. Do not enable anything yourself.

- `project-governance` — read and write specs, knowledge, rules, and memory.
  Needed when the user states a durable convention or asks to remember
  something across sessions. Writes still require the learn proposal,
  proposal hash, and the user's exact confirming quote.
- `planning-review` — clarify requirements and produce PRD, design, plan, and
  clarify documents, with editor and document-check roles. Needed when work
  is more than a trivial fix: requirements must be settled and persisted
  before implementation, or when the user hands over a planning document
  (PRD/design) that must be stored into the task directory.
- `persistent-task` — keep task state across sessions, including recovery and
  archive workflows. Needed when work spans sessions, must survive context
  compaction or machine changes, or when interrupted dispatches need
  takeover/recovery bookkeeping.
- `multi-agent` — bounded research and parallel implementation by sub-agents.
  Needed when the task needs evidence gathered in the background or multiple
  independent write scopes at once.

The project index (`.fstar/index.md`) and user index (`~/.fstar/index.md`) are
injected read-only at session start regardless of grants. Writing to those
surfaces is not implied by reading them; only `fstar init` may backfill a
generated placeholder index without a separate approval.
