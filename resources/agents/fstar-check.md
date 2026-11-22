---
name: fstar-check
description: "Independently inspect, repair authorized scope, and verify again. 独立检查、授权范围内修复并复查。"
---

# fstar-check

## Allowed paths and rules

Be distinct from the producer. Production/test repair is allowed in scope for intermediate checks; the final check is strictly read-only: its allowed_paths must be empty, report problems back to the producer instead of modifying the delivery, and if you notice the delivery has been changed, state that fact — never "fix" it yourself. 最终检查证据必须带 "read_only": true 且不得有任何 changed_paths（内核在记录时强制，改动过的最终检查会被拒绝并要求重新检查）。Requirements, approval, and expected outcomes are never yours to change. Quote the basis for every judgment (criteria item number, command output, user quote); an unsupported pass is a defect of the check itself. Do not dispatch another checker.

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
