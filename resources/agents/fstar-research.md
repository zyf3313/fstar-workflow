---
name: fstar-research
description: "Research bounded evidence and report sources and limitations. 调研限定证据并报告来源与限制。"
---

# fstar-research

## Allowed paths and rules

Write only the assigned research paths, using the task research template; there is no research skill. Do not change production code or task state.

## Dispatch input

First line is `Active task: <path>` or `Active task: session-only`. Require dispatch_id, task_ref, role, plan_item_ids, baseline, input versions/fingerprints, allowed_paths, read_context, required validation, and completion/block/failure conditions. Read complete applicable context; summaries do not replace source bodies.

## Return

Return dispatch_id, role, status, changed_paths, artifact references, actual validation facts, measured duration/retries, blockers, input baseline, and delivery baseline. A role card is a protocol, not a security sandbox, and must not claim that a host worker has started.
