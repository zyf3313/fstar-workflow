---
name: fstar-implement
description: "Implement assigned scope and return verifiable delivery facts. 实施指定范围并返回可验证事实。"
---

# fstar-implement

## Allowed paths and rules

Write only allowed product/test paths. Small-step self-check is not the independent check. Stop writing handed-off scope. Self-check results cite the criteria item numbers they cover (e.g. "A-001 covered by test X"); a self-check without a criteria reference is not a completion claim.

## Skill selection

Before acting, select applicable local skills from the host's exposed skill
catalog following routing (semantic intent → catalog → applicability →
actual invocation). User-named applicable skills come first; the task phase
is only context. The dispatch's `selected_skills` lists the coordinator's
selection with reasons — read the applicable rules of every listed skill
and actually invoke the matching ones. You may supplement from your own
exposed capabilities (the coordinator could not see them); never install a
skill. No match is normal: continue without it. Report actual usage in
`skill_usage` (attempted / succeeded / failed / not_used with a reason) —
selecting, recommending, or reading a skill is never execution. A skill
never widens allowed_paths, never counts as permission, and must not
recursively start the same fstar action.

## Dispatch input

First line is `Active task: <path>` or `Active task: session-only`. Require dispatch_id, task_ref, role, plan_item_ids, baseline, input versions/fingerprints, allowed_paths, read_context, required validation, and completion/block/failure conditions. Read complete applicable context; summaries do not replace source bodies.

## Return

Return dispatch_id, role, status, changed_paths, artifact references, actual validation facts, measured duration/retries, blockers, input baseline, and delivery baseline. A role card is a protocol, not a security sandbox, and must not claim that a host worker has started.
