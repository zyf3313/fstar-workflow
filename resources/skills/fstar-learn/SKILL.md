---
name: fstar-learn
description: "Save authorized knowledge with scope, conflict, and index checks. 按授权沉淀知识并核对归属。"
---

# Learn

## Do NOT use when
- No project-governance grant covers the destination: negotiate it first; never write without authorization.
- The user is mid-correction on task output: continue the task first; offer the learn candidate after the work settles.
- The knowledge is actually a procedure ("how to do X step by step"): record it under the project references category in the procedure format (below); no separate export path exists — procedures are read live from the knowledge base, never converted into host skills.

## Rejected-proposals ledger

When the user rejects a proposed approach and the rejection is durable (not a task-specific tradeoff), offer to record it in `.fstar/knowledge/references/rejected.md` with one entry per rejected approach:

```markdown
## <approach summary>
- rejected_at: YYYY-MM-DD
- user quote: "<the user's exact words>"
- reason: <why, from the user's words>
- scope: <this project | all projects — all-projects rejections belong in user rules instead>
```

Writing follows the normal pipeline (project-governance `knowledge` member, proposal, hash, user's exact quote). Cross-project rejections go to the user's rules, not this file.

## Procedure format

Procedural knowledge ("how to do X") is recorded under `.fstar/knowledge/references/procedures/<name>.md` in the same authorized pipeline. Each stage must carry an `evidence` field (how to prove the stage was done right); stages stay tool-agnostic (no host-specific commands, model names, or absolute paths). Workers read procedures live through dispatch `read_context` (path + sha256); the file in the knowledge base is the only authoritative copy.

Use after project-governance authorization. Read complete indexes and applicable bodies, prefer an existing topic, and justify a new one. Show candidate content, source, destination scope, and conflicts; save only when that exact content and scope are authorized. Use a general background Agent for lengthy organization; deferred optional learning does not block archive.

Invoke the packaged internal bridge with `python3 -I <package-root>/bin/fstar-bootstrap.py learn_bridge`, passing one JSON object on stdin. Resolve the package root from the installed fstar executable, not the current project. It returns one JSON envelope on stdout. This is an internal skill interface, not a new user command.

For `action: "prepare"`, supply absolute `project_root` and `user_root`, explicit `task_ref` (`session-only` or persistent task), `edits` (objects with `owner`, owner-relative `path`, `action`, and exact `content` or `rename_to`), `intent` (`summary`, `action`, `scope`, `source` with `source_type` and `reference`, and optional `topic`, `language`, `consent`, `extra_reference_files`), and `assessment` (reviewed source keys and byte digests, applicability, conflicts, coverage and language review). Session-only calls also carry the current `extensions` records; persistent calls omit them and read current grants from the task. If task commands use a custom `--runtime-root`, provide that exact absolute path as `runtime_root` on every persistent call; otherwise both use the default user runtime. The project must already be initialized. The provider validates paths, topic, indexes and reference closure; include explicit edits for affected references.

Present the returned complete `proposal` and `proposal_hash` for review, including all generated index changes. For `action: "apply"`, resend the exact inputs and add `confirmation` with `disposition: "approved"`, `source_type`, `source_ref`, the user's actual `quote`, `confirmed_at`, the returned `proposal_hash`, and exact `scope` and `owners` from the proposal; review sources also require `user_ref`, and promotion requires matching `consent`. Record only real user authorization; do not invent approval. If the digest changes, show the new proposal and obtain authorization for it. Report success only after the receipt and verification. Session grants and confirmation are caller-provided and cannot prevent forgery by another process with the same OS permissions; the independent knowledge API remains available.
