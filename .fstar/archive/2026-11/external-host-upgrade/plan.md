# External host upgrade repair plan

User authorized this fix (2026-11-23 “可以”), delegated project acceptance to the coordinator, and authorized Git remote operations; npm publication is the user's responsibility.

<!-- fstar:item:PLAN-1:start -->
1. Implement a narrowly guarded upgrade path for historically recorded, unchanged externally reused host files; account for default update target selection without expanding uninstall rights. Add meaningful temporary-root regression cases for A-001..A-003. Update README behavior and rebuild manifest.
2. An independent checker runs targeted tests and the full Python/Node suites, verifies actual manifest rebuild idempotence in a temporary copy, and records both layers of impact analysis. All production editing stops before this final read-only check.
3. Record delivery and final check evidence against A-001..A-004, self-accept under the user's project delegation, archive, commit and merge to main. Prepare patch 0.10.1 through the release branch convention, then sync Git; do not publish npm or update the user's live configuration as a test.
<!-- fstar:item:PLAN-1:end -->

Progress: implementation frozen; delivery evidence recorded. Independent final review and full regression running. Manifest rebuilt twice in an isolated copy with identical hashes. No npm publication performed.
