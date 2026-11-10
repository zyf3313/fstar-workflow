---
name: fstar-init
description: "Initialize from verified project facts; preserve authority. 基于事实初始化，保留权威资料。"
---

# Init

Explore the whole project and existing authoritative material before asking for missing background. Collect a JSON object with `project_summary` (string), `topics` (objects with `id`, `title`, `applies_to`, `read_when`, `path`), and optional `authority_refs` and `knowledge_refs` (objects with `title`, `path`). All paths refer to existing project files. Pass the file to `fstar init <project-path> --context <json-file>` and verify navigation. The command also attempts a read-only initial tool proposal scan without requiring extension grants; binding changes require separate user confirmation. If it reports `TOOL_SCAN_FAILED`, initialization succeeded but the scan failed. Reference existing authority instead of inventing guidance. `INDEX_PRESERVED` means new context was not applied. Remove any temporary context file when finished.

## Initial capability binding

The scan returned by `fstar init` is an index, not a decision. After the
skeleton is verified, classify what this machine actually offers and bind at
most one tool per capability contract. The user selects nothing per item:
review the inventory yourself, then present one consolidated summary and ask
for a single confirmation.

1. Candidate set: the host's skill listing (global `~/.claude/skills` and the
   project's `.claude/skills`) plus the CLI tools in `tool_proposals.tools`.
   A proposal whose matches are all `none` carries only a description snippet;
   treat it as a candidate, not a conclusion.
2. Review in batches of 30–50 entries. Read a skill's frontmatter and
   description before judging it; never bind on a keyword coincidence. For a
   long inventory, hand each batch to a background agent and keep the main
   conversation free.
3. For each of `code-structure`, `web-research`, `knowledge-retrieval`,
   `data-access`, and `test-execution`, choose at most one tool whose evidence
   actually supports that capability. Prefer a registry `strong` match; a
   verified `weak` match or an explicit capability in the tool's own
   description is acceptable; otherwise leave the capability unbound. Do not
   fill a slot with an unrelated tool.
4. Bindings are project-level only: write `<project>/.fstar/tools.yaml` and
   never create or edit the user-level `~/.fstar/tools.yaml`. If
   `.fstar/tools.yaml` already exists, show its current bindings and ask
   before changing anything; never overwrite silently.
5. Present one summary before writing: selected (capability → tool → evidence),
   skipped (count by reason: unrelated or insufficient evidence), and unbound
   capabilities. Ask once for approval. On approval, apply through
   `python3 -I <package-root>/bin/fstar-bootstrap.py tools_bridge`
   (`prepare`, show the proposal and its digest, then `apply` with the user's
   exact quote and a session-only `tool-capability` grant carrying `bindings` —
   materialize that grant first with
   `fstar extension enable tool-capability --confirm-user` and reuse its
   returned authorization record in the bridge request).
   On refusal, leave no `tools.yaml` and report that the scan remains
   available. Report the final file path and digest in the same summary shape.
