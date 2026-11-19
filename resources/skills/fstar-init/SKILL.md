---
name: fstar-init
description: "Initialize from verified project facts; preserve authority. 基于事实初始化，保留权威资料。"
---

# Init

## Do NOT use when
- The project is already initialized and the user wants governance content: use `fstar-learn` (init backfills only its own generated placeholders).
- The directory is not a project (no code or docs at all): ask the user what they intend to build first (step 8).

Initialize from facts you can verify, without asking the user to confirm what exploration already proved.

1. Explore the project: directory structure, frameworks, build and test files, package manifests, and existing authoritative documents. Do not ask the user to confirm the discovered facts.
2. Create the user root first when needed: `fstar init <project-path>` auto-creates a missing `~/.fstar` (or the configured user root), validates an existing config, and repairs a partial layout. This initialization-only creation is not a governance write.
3. Collect a JSON context file with `project_summary` (string), `topics` (objects with `id`, `title`, `applies_to`, `read_when`, `path`), and optional `authority_refs` and `knowledge_refs` (objects with `title`, `path`). Every referenced path must be an existing project file.
4. For each topic, write a spec skeleton yourself at `.fstar/specs/<topic-id>/index.md` in the `fstar.knowledge.v1` spec format, using `resources/templates/knowledge/spec.md` as the frontmatter shape. Derive content only from exploration, link existing authority, fill in only verified facts, and never overwrite a user-authored spec. Point the topic's `path` at the skeleton.
5. Topics stay exploration-driven: no fixed global dimension list is forced on every project. Dimensions derive from what the scan actually finds — a backend monolith gets backend topics, a React app gets frontend ones, a docs-only repo gets guide topics.
6. For EACH topic identified, also write the applicable per-dimension detail files at `.fstar/specs/<topic-id>/<detail>.md`. The detail set follows the topic's nature:
   - Structure: `directory-structure.md`
   - Error handling: `error-handling.md`
   - `quality-guidelines.md` and `logging-guidelines.md`
   - `database-guidelines.md` only when a data layer exists
   - For UI topics: `component-guidelines.md`, `state-management.md`, `type-safety.md`
   Each detail file uses the `fstar.knowledge.v1` spec frontmatter (type: spec, status: active), has an Overview section with the verified facts from exploration already filled in where discovery proved them, and 待补 placeholders for unverified parts. Never overwrite a user-authored detail file; write only missing ones. The topic's index.md links its detail files.
7. Run `fstar init <project-path> --context <json-file>`. A fresh skeleton is created; an existing generated placeholder index is backfilled and reports `INDEX_BACKFILLED`, so no confirmation round-trip is needed. `INDEX_PRESERVED` means the index was user-authored and was not touched. The context JSON topics entry keeps pointing at the topic index.md (path field).
8. If and only if the project is empty or near-empty (no meaningful source or docs), ask what the user intends to build. If they give a direction, generate context and spec skeletons from that answer. Otherwise leave the placeholder index as-is and report that.
9. Remove the temporary context file when finished.
