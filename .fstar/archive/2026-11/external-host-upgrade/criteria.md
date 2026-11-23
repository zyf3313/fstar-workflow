# Unchanged external host file upgrade

Source: user approved the proposed repair with “可以” on 2026-11-23: include externally_owned host files whose content still matches their recorded baseline in the upgrade path. Scope is installer maintenance; npm publication remains with the user. All criteria below operationalize that repair and its existing safety boundaries.

<!-- fstar:item:A-001:start -->
## A-001 Upgrade recorded, unchanged external reuse
判定方式：machine。
An update against a new bundle refreshes host skills/agents recorded as externally_owned when destination, source, host/kind, valid historical version/hash and current content identify an unchanged reused package file. The default global update must reach these recorded target roots, including when there are no owned host files. No manual deletion is required. Dry run remains read-only. Validate with temporary install/update fixtures.
<!-- fstar:item:A-001:end -->

<!-- fstar:item:A-002:start -->
## A-002 Preserve user ownership boundaries
判定方式：machine。
Unrecorded files, modified externally_owned files, insufficient or inconsistent history, symlinks and paths outside the selected host remain protected, including with overwrite requested. Existing uninstall behavior must not delete externally reused files merely because they are discoverable for update. Verify explicit roots and legacy roots do not broaden the selected scope.
<!-- fstar:item:A-002:end -->

<!-- fstar:item:A-003:start -->
## A-003 Durable and auditable upgrade
判定方式：machine。
A successful authorized refresh backs up replaced bytes and leaves manifest and entry index consistent with the installed hash/version/ownership. Subsequent updates are idempotent and subsequent user edits remain protected. Changes between plan and apply are refused; existing rollback protections remain in force.
<!-- fstar:item:A-003:end -->

<!-- fstar:item:A-004:start -->
## A-004 Regression and delivery
判定方式：machine。
Targeted installer regression, complete Python and Node suites pass; package manifest rebuild is idempotent. Independent read-only review covers callers and installer mechanism interactions (target selection, overwrite/uninstall, backup/rollback, doctor/index). README accurately describes the exception. No unrelated hook cleanup, task schema migration, acceptance-policy code change, real user configuration test writes, or npm publish.
<!-- fstar:item:A-004:end -->
