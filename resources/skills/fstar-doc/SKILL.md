---
name: fstar-doc
description: "Coordinate background document editing and conflict checks. 后台编辑文档并检查冲突。"
---

# Doc

## Do NOT use when
- Requirements are still being clarified: use `fstar-clarify`; doc owns only settled documents.
- The edit targets a single specified item in an already-approved document with a baseline: dispatch `fstar-editor` via `fstar doc-edit`.
- The material is a planning artifact owned by another skill (plan/clarify/criteria): those belong to `fstar-plan`/`fstar-clarify`.

Use after planning-review authorization. Own the specified deliverable files wherever the user's delivery preference puts them — there is no fixed doc/ location; the default is to follow the preference recorded at clarification close. Queue edits to the same file. Every write must use a background fstar-editor dispatch with the discussion revision, source references, baseline fingerprint, and exact file/items. Keep the main conversation available. Before acceptance, collect results, reject stale-baseline overwrite, reread slots/IDs/references, then request an independent consistency check using document-checklist.md. Syncing an already approved, unchanged scope does not require another approval. Editing never proves approval. Maintain the deliverables registry: register new, moved, or versioned deliverables in the task's `deliverables` entries in task.json so the acceptance flow can trace them.

When the user supplies a planning document: preserve their content as the authority, map it onto the template structure (slots, item markers, artifact_map markers) applicable to the document kind without rewriting meaning; unknown facts stay 待确认. Mark origin as user-supplied (author = the user, provenance note naming the supplied document), never drafted-by-agent. The artifact_map marker registration (meta.templates) still applies.
