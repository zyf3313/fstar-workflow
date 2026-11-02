---
name: fstar-check
description: "Independently inspect, repair authorized scope, and verify again. 独立检查、授权范围内修复并复查。"
---

# fstar-check

## Allowed paths and rules

Be distinct from the producer. Production/test repair is allowed in scope; requirements, approval, and expected outcomes are not. Do not dispatch another checker.

## Dispatch input

First line is `Active task: <path>` or `Active task: session-only`. Require dispatch_id, task_ref, role, plan_item_ids, baseline, input versions/fingerprints, allowed_paths, read_context, required validation, and completion/block/failure conditions. Read complete applicable context; summaries do not replace source bodies.

## Return

Return dispatch_id, role, status, changed_paths, artifact references, actual validation facts, measured duration/retries, blockers, input baseline, and delivery baseline. A role card is a protocol, not a security sandbox, and must not claim that a host worker has started.
