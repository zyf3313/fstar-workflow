---
name: fstar-doc
description: "Coordinate background document editing and conflict checks. 后台编辑文档并检查冲突。"
---

# Doc

## Do NOT use when
- Requirements are still being clarified: use `fstar-clarify`; doc owns only settled documents.
- The edit targets a single specified item in an already-approved document with a baseline: dispatch `fstar-editor` via `fstar doc-edit`.
- The material is a planning artifact other than prd/design (plan/clarify): those are owned by `fstar-plan`/`fstar-clarify`.

Use after planning-review authorization. Own only doc/prd.md and doc/design.md. Queue edits to the same file. Every write must use a background fstar-editor dispatch with the discussion revision, source references, baseline fingerprint, and exact file/items. Keep the main conversation available. Before acceptance, collect results, reject stale-baseline overwrite, reread slots/IDs/references, then request an independent consistency check using document-checklist.md. Syncing an already approved, unchanged scope does not require another approval. Editing never proves approval.

When the user supplies a planning document: preserve their content as the authority, map it onto the template structure (slots, R-item markers, artifact_map markers) without rewriting meaning; unknown facts stay 待确认. Mark origin as user-supplied (author = the user, provenance note naming the supplied document), never drafted-by-agent. The artifact_map marker registration (meta.templates) still applies.
