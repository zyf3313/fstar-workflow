---
name: fstar-init
description: "Initialize from verified project facts; preserve authority. 基于事实初始化，保留权威资料。"
---

# Init

Initialize from facts you can verify, without asking the user to confirm what exploration already proved.

1. Explore the project: directory structure, frameworks, build and test files, package manifests, and existing authoritative documents. Do not ask the user to confirm the discovered facts.
2. Create the user root first when needed: `fstar init <project-path>` auto-creates a missing `~/.fstar` (or the configured user root), validates an existing config, and repairs a partial layout. This initialization-only creation is not a governance write.
3. Collect a JSON context file with `project_summary` (string), `topics` (objects with `id`, `title`, `applies_to`, `read_when`, `path`), and optional `authority_refs` and `knowledge_refs` (objects with `title`, `path`). Every referenced path must be an existing project file.
4. For each topic, write a spec skeleton yourself at `.fstar/specs/<topic-id>/index.md` in the `fstar.knowledge.v1` spec format, using `resources/templates/knowledge/spec.md` as the frontmatter shape. Derive content only from exploration, link existing authority, fill in only verified facts, and never overwrite a user-authored spec. Point the topic's `path` at the skeleton.
5. Run `fstar init <project-path> --context <json-file>`. A fresh skeleton is created; an existing generated placeholder index is backfilled and reports `INDEX_BACKFILLED`, so no confirmation round-trip is needed. `INDEX_PRESERVED` means the index was user-authored and was not touched.
6. If and only if the project is empty or near-empty (no meaningful source or docs), ask what the user intends to build. If they give a direction, generate context and spec skeletons from that answer. Otherwise leave the placeholder index as-is and report that.
7. Remove the temporary context file when finished.
