---
name: fstar-check
description: "Independently test, repair in scope, rerun, and report facts. 独立检查、范围内修复并如实报告。"
---

# Check

## Do NOT use when
- A native dispatch has failed twice or repair shows no progress: route to `fstar-debug` (core-automatic).
- You produced the delivery being validated: the check producer must differ from every delivery producer.

Fix scope, baseline, exit conditions, and required validation before work. Be independent of the producer. Inspect documents or code, add/run tests, and repair production or test code only within the authorized scope; never change requirements or expected outcomes to hide a defect. For document consistency, apply the shared document-checklist.md that the editor reread also uses.

Check against three lines, quoting the basis for each judgment: comprehension correctness (was the goal and the user's key quotes understood — nothing missing, nothing silently added), agreement with the settled requirements and plan, and delivery usability (what the user receives is usable and understandable; unverified items are listed with reasons, never guessed). Cite criteria.md item numbers (e.g. A-001) in the 对照 column rather than restating requirements, and compare against the user's key quotes.

Challenger duty (anti-case checking): do not only verify "it was implemented" — construct counter-examples and boundary cases that would fail the delivery and run them. For each checked capability, ask what input, state, or sequence breaks it, and test at least the boundaries that are cheap to exercise (empty/oversized input, missing files, old-format data, concurrent/second invocation where applicable). Report constructed counter-examples and their outcomes as part of the evidence; a check that only reran the producer's happy path is not complete. Scale with the change's blast radius: a small localized fix does not force the full adversarial battery, but even then verify at least one boundary beyond the fixed path; anything touching schema, lifecycle, hooks, or cross-feature behavior gets the full counter-example treatment.

The final check is read-only (C-12): report problems back to the producer for repair; do not modify the delivery yourself. 最终检查证据必须带 "read_only": true 且不得有任何 changed_paths（内核在记录时强制，改动过的最终检查会被拒绝并要求重新检查）。Intermediate checks may repair within authorized scope. For a large task whose criteria items are independent with no shared writes, intermediate checks may be split across multiple fresh checker instances in parallel by criteria item (not by file, to catch cross-file contradictions); the final verdict is assembled by the main Agent or a single checker and is never parallelized; small tasks are not split. After a repair, recheck only the impacted criteria items plus their blast radius — not the whole report — and finish with one overall check.

Report passed/failed/blocked/skipped/not_run separately, commands, test identifiers, environment, run id, baseline, measured duration/retries, repairs, uncovered scope, and blockers. Write the report with the check report template; a persistent task stores records in checks/ (check-001.md, check-002.md, ... in order; a single short record may sit at the task root as check.md). Do not recursively dispatch another checker.
