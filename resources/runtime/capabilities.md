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
  clarify documents, with editor and document-check roles.
- `persistent-task` — keep task state across sessions, including recovery and
  archive workflows.
- `multi-agent` — bounded research and parallel implementation by sub-agents.
- `tool-capability` — tool contracts, bindings, classification, validation,
  and fallback behavior.

The project index (`.fstar/index.md`) and user index (`~/.fstar/index.md`) are
injected read-only at session start regardless of grants. Writing to those
surfaces is not implied by reading them.
