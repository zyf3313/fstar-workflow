# fstar knowledge format

This is the single format authority for built-in rule, memory, and spec documents. Frontmatter uses simple scalar values.

## Common fields

- `schema: fstar.knowledge.v1` (required)
- `type: rule | memory | spec` (required)
- `status: active | superseded` (required)

A rule additionally requires `strength: enforced | default`. A memory additionally requires `kind: preference | lesson` and `trust: confirmed | unreviewed`. Missing or unknown values are errors; never silently default them. Superseded documents and unreviewed memories are not loaded. A memory never becomes a rule automatically.

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
