---
name: fstar-check
description: "Independently test, repair in scope, rerun, and report facts. 独立检查、范围内修复并如实报告。"
---

# Check

Fix scope, baseline, exit conditions, and required validation before work. Be independent of the producer. Inspect documents or code, add/run tests, and repair production or test code only within the authorized scope; never change requirements or expected outcomes to hide a defect. For document consistency, apply the shared document-checklist.md that the editor reread also uses. Recheck impacted areas and finish with one overall check. Report passed/failed/blocked/skipped/not_run separately, commands, test identifiers, environment, run id, baseline, measured duration/retries, repairs, uncovered scope, and blockers. Write the report with the check report template; a persistent task stores it at acceptance/check-<n>.md. Do not recursively dispatch another checker.
