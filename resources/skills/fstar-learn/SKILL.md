---
name: fstar-learn
description: "Save authorized knowledge with scope, conflict, and index checks. 按授权沉淀知识并核对归属。"
---

# Learn

Use after project-governance authorization. Read complete indexes and applicable bodies, prefer an existing topic, and justify a new one. Show candidate content, source, destination scope, and conflicts; save only when that exact content and scope are authorized. Use a general background Agent for lengthy organization; deferred optional learning does not block archive.

Invoke the packaged internal bridge with `python3 -I <package-root>/bin/fstar-bootstrap.py learn_bridge`, passing one JSON object on stdin. Resolve the package root from the installed fstar executable, not the current project. It returns one JSON envelope on stdout. This is an internal skill interface, not a new user command.

For `action: "prepare"`, supply absolute `project_root` and `user_root`, explicit `task_ref` (`session-only` or persistent task), `edits` (objects with `owner`, owner-relative `path`, `action`, and exact `content` or `rename_to`), `intent` (`summary`, `action`, `scope`, `source` with `source_type` and `reference`, and optional `topic`, `language`, `consent`, `extra_reference_files`), and `assessment` (reviewed source keys and byte digests, applicability, conflicts, coverage and language review). Session-only calls also carry the current `extensions` records; persistent calls omit them and read current grants from the task. If task commands use a custom `--runtime-root`, provide that exact absolute path as `runtime_root` on every persistent call; otherwise both use the default user runtime. The project must already be initialized. The provider validates paths, topic, indexes and reference closure; include explicit edits for affected references.

Present the returned complete `proposal` and `proposal_hash` for review, including all generated index changes. For `action: "apply"`, resend the exact inputs and add `confirmation` with `disposition: "approved"`, `source_type`, `source_ref`, the user's actual `quote`, `confirmed_at`, the returned `proposal_hash`, and exact `scope` and `owners` from the proposal; review sources also require `user_ref`, and promotion requires matching `consent`. Record only real user authorization; do not invent approval. If the digest changes, show the new proposal and obtain authorization for it. Report success only after the receipt and verification. Session grants and confirmation are caller-provided and cannot prevent forgery by another process with the same OS permissions; the independent knowledge API remains available.
