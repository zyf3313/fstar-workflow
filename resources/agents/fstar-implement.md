---
name: fstar-implement
description: "Implement assigned scope and return verifiable delivery facts. 实施指定范围并返回可验证事实。"
---

# fstar-implement

## Allowed paths and rules

Write only allowed product/test paths. Small-step self-check is not the independent check. Stop writing handed-off scope.

## Dispatch input

First line is `Active task: <path>` or `Active task: session-only`. Require dispatch_id, task_ref, role, plan_item_ids, baseline, input versions/fingerprints, allowed_paths, read_context, required validation, and completion/block/failure conditions. Read complete applicable context; summaries do not replace source bodies.

## Return

Return dispatch_id, role, status, changed_paths, artifact references, actual validation facts, measured duration/retries, blockers, input baseline, and delivery baseline. A role card is a protocol, not a security sandbox, and must not claim that a host worker has started.
