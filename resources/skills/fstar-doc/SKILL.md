---
name: fstar-doc
description: "Coordinate background document editing and conflict checks. 后台编辑文档并检查冲突。"
---

# Doc

Use after planning-review authorization. Own only doc/prd.md and doc/design.md. Queue edits to the same file. Every write must use a background fstar-editor dispatch with the discussion revision, source references, baseline fingerprint, and exact file/items. Keep the main conversation available. Before acceptance, collect results, reject stale-baseline overwrite, reread slots/IDs/references, then request an independent consistency check using document-checklist.md. Syncing an already approved, unchanged scope does not require another approval. Editing never proves approval.
