# Merge and retire fstar-doc: plan

User authorization: 2026-11-23 "我觉得可以合并删除就好" (after options were presented including the cost). npm publication stays with the user.

<!-- fstar:item:PLAN-1:start -->
1. Implement: remove resources/skills/fstar-doc; relocate its duties into fstar-plan (user-supplied document storage with preserved origin, template mapping) and fstar-execute (deliverables registry, background editor coordination for multi-file document edits); update routing.md member references; keep document-checklist.md (still used by fstar-check/editor). Update README. Rebuild manifest. Add targeted tests.
2. Independent read-only final check covering A-001..A-004 with two-layer impact review; coordinator runs full Python/Node suites.
3. Record evidence, delegated acceptance (project rule), archive, merge to main, sync Git. Release preparation (0.11.0, minor: feature delivery) on a release branch; user publishes.
<!-- fstar:item:PLAN-1:end -->

Progress: implementation pending.
