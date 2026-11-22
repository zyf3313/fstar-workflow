# fstar knowledge format

This is the single format authority for built-in rule, memory, and spec documents. Frontmatter uses simple scalar values.

## Common fields

- `schema: fstar.knowledge.v1` (required)
- `type: rule | memory | spec` (required)
- `status: active | superseded` (required)

A rule additionally requires `strength: enforced | default`. A memory additionally requires `kind: preference | lesson` and `trust: confirmed | unreviewed`. Missing or unknown values are errors; never silently default them. Superseded documents and unreviewed memories are not loaded. A memory never becomes a rule automatically.

A memory may also carry five optional experience fields. All are single scalar strings and all are optional; documents written before these fields existed keep parsing and loading unchanged.

- `scope: personal | scenario:<id> | item:<id>` — how far the memory reaches. Absent (or `personal`) memories apply broadly, exactly as before; a `scenario:<id>` or `item:<id>` memory is injected only when the current reading carries that exact tag.
- `confidence: explicit-request | inferred | verified` — why the memory exists. `inferred` marks an agent-formed guess; it is reported honestly and never upgrades itself to a rule (promotion keeps its own explicit consent path). Absent confidence is simply unspecified.
- `source: <reference>` — durable provenance of the experience (task, conversation, or review reference), separate from the body's `SOURCE:` line. Absent when there is no traceable reference.
- `expires: YYYY-MM-DD` — a machine-judgeable calendar date. On and after that date the memory stops being injected; the exclusion states `memory expired on <date>`. Absent means no known expiry. An `expires` value must be a valid calendar date; `2026-1-1` or `2026-02-30` are errors.
- `conditions: <natural language>` — prose applicability conditions. The system never judges this text: an unjudged `conditions` memory stays excluded with an `unknown` judgement until the user (or an explicit caller judgement) decides it applies. It never silently defaults to applicable.

Retrieval filtering layers machine-judgeable checks first: superseded status, unconfirmed trust, and a passed `expires` date block injection on every path, including direct selection and dependency expansion — a stopped or expired memory always surfaces as an explicit exclusion with its reason, never a silent gap. Scope filtering applies next, then the `conditions` layer. Correction and retirement reuse the normal authorized proposal pipeline: the old record stays on disk with `status: superseded` for audit and its provenance intact; a correction publishes the superseded original plus the replacement (with the new `source`) as one transactional group, it never overwrites the original content in place.

Rules and memories are English. Specs follow `language.specs` (default English). Context and references follow project artifact language and do not use this frontmatter. Rule bodies use concise MUST/NEVER, APPLIES, NOT, and SOURCE statements; memory bodies contain content plus APPLIES, NOT, and SOURCE. Specs are concise and executable, with evidence and short examples only when useful.

After validity and applicability filtering, resolve effective knowledge as enforced rule > explicit project spec > default rule > confirmed memory. Existing authoritative project documents have priority over derived fstar guidance. Explain conflicts rather than merging incompatible statements. Read project summary, complete indexes, and global constraints first, then the complete applicable topics and upstream/shared contracts; an injected summary is not a substitute for those bodies.

## Strict parsing conventions

These notes clarify how the strict parser reads the fields above; they add no field and change no policy.

- The frontmatter block is bounded by two standalone `---` lines at the very start of the file, with one `key: value` pair per line. A missing opening or closing delimiter is an error, and the body after the closing delimiter must not be blank.
- Every value is a plain quoted or unquoted scalar string. Numbers, booleans, `null`, flow collections (`[a, b]`, `{k: v}`), duplicate keys and unknown keys are errors, as is a field that does not apply to the declared `type` (for example `strength` on a `spec`).
- Superseded documents and unreviewed memories still validate. An invalid record that will never be loaded is still reported instead of silently ignored.
- Files must be UTF-8. Index and body links are Markdown inline or reference links; wiki-style `[[...]]` links and HTML link forms are not rewritten automatically and require manual review. Fenced code blocks are never rewritten.

## Group update transactions

Authorized writes publish the body, index, and affected references as one recoverable operation.

- Writers hold the user lock under `<user>/runtime/knowledge/` and the project lock under `<project>/.fstar/runtime/knowledge/`, so callers with different user roots still serialize on project data. Read-only calls never create these files.
- Each file is replaced atomically; simultaneous multi-file visibility to arbitrary filesystem readers is not promised. Cooperating API readers recheck hashes and observe complete before/after snapshots.
- A failure before the commit marker restores the recorded original bytes or absence. A later external edit stops the rollback with an explicit conflict instead of overwriting it. Pending operations must be recovered explicitly before the next write.
