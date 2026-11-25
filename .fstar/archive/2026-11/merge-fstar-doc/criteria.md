# Merge and retire fstar-doc: acceptance criteria

Source: user approved merge-and-delete on 2026-11-23 ("我觉得可以合并删除就好") after the option was presented with its cost (routing/clarify/execute references and extension member mapping). All criteria are machine-verifiable.

<!-- fstar:item:A-001:start -->
### A-001 Responsibilities relocated, references consistent

- 判定方式：machine
- The fstar-doc skill is removed from the packaged resources. Its remaining duties (user-supplied planning document storage with origin preserved, deliverables registry maintenance, multi-file document-edit coordination) are explicitly covered by fstar-plan and/or fstar-execute. routing.md, fstar-clarify, and fstar-execute contain no dangling references to fstar-doc; the document-consistency checklist reference used by fstar-check stays intact.
- 检查方法：resource listing + full-text search across resources/ and README for "fstar-doc" (zero hits outside archived/history notes); updated routing/clarify/execute text reviewed.
<!-- fstar:item:A-001:end -->

<!-- fstar:item:A-002:start -->
### A-002 Extension mapping and compatibility

- 判定方式：machine
- The planning-review extension set no longer gates fstar-doc; retained members (clarify, prd, design, plan, editor, doc-check) keep working. An old task with an enabled planning-review grant that included historical members still loads and archives; no schema migration is forced. Existing installs update cleanly to the new resource set.
- 检查方法：extension enable/list on a temporary task with the new mapping; old task.json (with historical grants) read/archive test; install/update tests pass.
<!-- fstar:item:A-002:end -->

<!-- fstar:item:A-003:start -->
### A-003 Package and installer consistency

- 判定方式：machine
- package-assets.json rebuilt and truthful (no fstar-doc entries); installer/uninstall/doctor handle the removed skill correctly on a fresh install and on update from a previous version (stale fstar-doc copy retired or reported, never silently kept as active).
- 检查方法：manifest rebuild idempotence; install/update/uninstall/doctor fixtures covering the removed skill.
<!-- fstar:item:A-003:end -->

<!-- fstar:item:A-004:start -->
### A-004 Regression and delivery

- 判定方式：machine
- Full Python and Node suites pass; targeted tests cover A-001..A-003; independent final read-only check confirms. README updated. No npm publish (user's responsibility) and no unrelated changes.
- 检查方法：full test suite + independent check + impact review (callers and mechanism interactions).
<!-- fstar:item:A-004:end -->
