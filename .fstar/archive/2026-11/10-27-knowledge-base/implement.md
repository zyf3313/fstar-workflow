# Knowledge-base execution plan

## Summary and authority

Implement the approved knowledge provider contract in this child's design. Parent current prd/design/implement supersede historical decisions/history/append-only plans. This file is a Trellis execution artifact; the product task artifact remains `plan.md`.

This preparation changes only prd.md/design.md/implement.md/implement.jsonl/check.jsonl. Do not start a task, edit product files, change task metadata, dispatch agents or run git during this refresh. Future execution already has parent authorization; ordinary technical choices do not create a new approval gate.

## Patterns to mirror and files to change

| Ownership | Files / use |
|---|---|
| New provider | `src/fstar/knowledge.py`: all knowledge parsing, catalogs, context resolution, proposals and recoverable transactions. |
| Tests | `tests/test_knowledge.py`: unit/contract, failure injection and real two-process lock/recovery tests. |
| Conditional sole resource edit | `resources/references/knowledge-format.md`: only if strict parser/link/transaction conventions need clarification; explicitly report whether used. No added required field or policy change. |
| Read-only dependencies | `src/fstar/config.py`, `project.py`, `store.py`, `models.py`, `content.py`, `tools.py`; existing resource templates, skills and capability text. |

Use public config parser/loader, canonical JSON/proposal hashing, atomic JSON metadata writer and DomainError. Raw byte hashes use hashlib. Do not depend on private content/tools helpers, mutate task storage, add YAML dependencies, add CLI registration, or modify another child's modules. Runtime/init/learn/installer wiring needs its owner's follow-up; provider contract tests do not mean those consumers are integrated.

## Ordered work

### K-1 — Establish read and format boundary (AC-01–03)

- [x] Read full parent design, current reference/templates, backend index and all applicable bodies; placeholder backend guidelines contain no invented project requirements.
- [x] Reconfirm actual public APIs with CodeGraph; read code only for specific missing details. Baseline is the reported 323-test delivered suite, not an obsolete blocker.
- [x] Define dataclasses/data validation and stable DomainError diagnostics in knowledge.py. Implement UTF-8/scalar frontmatter parsing with parse_config, strict type/category checks and active/confirmed filtering.
- [x] Implement root/path safety and read-only catalog snapshots; no directory creation, configuration writes or task requirement for user-only reads.
- [x] Add template compatibility, invalid inactive documents, malformed encoding/types/duplicates, category mismatch and language-policy tests. Review language semantics manually; do not build a fake regex proof.

Completion: exact schema acceptance/rejection and no-side-effect reads are independently testable. Dependency: existing project/config/content resources only.

### K-2 — Complete context and resolution (AC-04–05)

- [x] Implement full overview/index/global constraint loading, topic/authority extraction and explicit selection fallback for customized indexes.
- [x] Load full applicable topic bodies and all identified upstream/downstream/shared contracts; unknown scope broadens selection. Detect cycles, missing refs, unresolved fragments and budget omissions.
- [x] Define source-bound SemanticAssessment. Resolve supplied conflicts by enforced > project > default > confirmed memory and existing authority within project tier. Return conflicts, precedence reasons and unresolved equal-tier pairs.
- [x] Test source changes invalidate assessments, inactive records never win, unrelated constraints remain, incomplete assessment cannot claim conflict-free, and budget limits never silently truncate.

Completion: deterministic structural loading/resolution with honest semantic coverage. No tool invocation or runtime-hook mutation.

### K-3 — Authorized edit proposals (AC-06–07)

- [x] Implement prepare_change over exact edits, baselines, source/ownership, language policy, topic review and reference inventory. No proposal persistence.
- [x] Preserve existing index prose. Default to existing topic; require a reason for new topic. Validate required user/project navigation information without imposing a new fixed body skeleton.
- [x] Support create/correct/replace/supersede/delete/rename and explicit promotion. Discover supported inbound references in the defined corpus; require complete staged updates or return an actionable reference error.
- [x] Bind confirmation to exact proposal hash/content/paths/ownership/scope/assessment. Missing, denied or deferred confirmation does no writes; changed proposal or baseline fails. Clearly preauthorized content can be represented without another prompt.
- [x] Test unrelated prose preservation, source traceability, alias/symlink/traversal rejection, stale before-hash, broken/unsupported relevant references, explicit authority-edit scope and changed trust/strength/ownership.

Completion: proposals are concrete and reviewable; no promotion or scope expansion is implicit.

### K-4 — Group transaction and recovery (AC-08–09)

- [x] Implement per-user/per-project POSIX locks, ordered multi-owner acquisition, timeout and shared reader protocol. Project lock location must work across callers with different user roots.
- [x] Add staged after/before images, participant pointers, coordinator/commit markers, fsync and same-filesystem per-file replacement. Bind recovery metadata to canonical owner roots and hashes.
- [x] Revalidate every edit and reference-inventory baseline under locks; reject stale proposals after waiting. Commit only after full staged/published validation.
- [x] Implement rollback and explicit idempotent recover_changes; preserve backups and fail on unexpected external bytes, unsafe metadata or missing participants. Read APIs report pending recovery without mutating storage.
- [x] Inject failures at each stage/publish/commit/cleanup boundary. Kill a child process at controlled checkpoints and recover in another process. Verify byte-for-byte restoration, absent-file/mode handling and committed cleanup retry.
- [x] Use real two-process tests for same body, shared index and cross-owner ordering; verify stale loser and API-reader snapshots. Document that arbitrary filesystem readers can see intermediate publishes.

Completion: failure never reports saved; cooperating readers see complete snapshots; crash recovery never clobbers external edits. Do not claim os.replace provides group atomic visibility.

## Execution record (2026-10-30, Python 3.9.6 at /usr/bin/python3)

Delivered files: `src/fstar/knowledge.py` (provider), `tests/test_knowledge.py` (95 tests), one conditional resource edit (`resources/references/knowledge-format.md`, clarifying sections only).

Commands and results:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_knowledge.py'   # 95 tests, OK (~3.4s)
PYTHONPATH=src python3 -m unittest discover -s tests                            # 489 tests, 1 failure (~35.6s)
python3 -m compileall -q src tests                                              # OK
PYTHONPATH=src python3 -c '...validate_resources(Path("resources"))...'         # issues: ()
```

The single full-suite failure is `test_parser_exposes_only_tools_scan (test_tools.ScanCommandTests)`, which asserts the parser has no `install` command; the package-install implementer added `install/update/uninstall/doctor/migrate/version` to `fstar.installer.register_commands` concurrently. It is outside this child's owned files and was not modified here.

Remaining integration (explicitly not done here): init passes discovered taxonomy/authority; learn supplies source-bound assessment/authorization and calls apply; runtime injects bundles and handles omissions/recovery; installer/doctor uses shared validation; tools consumes sources read-only; e2e proves both hosts.

### K-5 — Consumer contracts and final check (AC-10 and all ACs)

- [x] Exercise ProjectContext-produced indexes, current config precedence, public store archive scans and tools consumer source records in fixtures. Retain explicit missing caller integration items below.
- [x] Verify no new command, knowledge search engine, binding/install mutation, candidate/history ledger, or archive restore path. Dynamic archive view remains owned by core.
- [x] If needed, make only the listed minimal knowledge-format reference clarification; do not duplicate schema authority or edit templates/skills. Used: two clarifying sections (strict parsing conventions, group update transactions) were appended to `resources/references/knowledge-format.md`; no new field, no policy change.
- [x] Run focused tests, complete regression suite, compile and resource validation. Record actual Python version, commands/results, durations, run IDs and limitations; do not turn baseline counts into new execution evidence.
- [ ] Future independent check reviews all ACs and semantic prose/ownership boundaries, including body/index/reference failure behavior. Fix within this child's owned files and rerun affected tests, then final regression once justified.

## Independent check record (2026-10-30, Python 3.9.6 at /usr/bin/python3)

Checked all ACs adversarially against the actual code (full read of `src/fstar/knowledge.py` ~2900 lines, `tests/test_knowledge.py`, parent prd/design/implement, child prd/design, config/project/store public APIs, `resources/references/knowledge-format.md`).

### Defects found and fixed (all in owned files)

1. **Index-only edit bypassed prose preservation** (`src/fstar/knowledge.py`, `prepare_change`): a supplied `index.md` edit from an owner with no planned entry/topic changes never entered the `index_inventory` loop (it iterated `index_changes` keys only), so a wholesale destructive index rewrite could be prepared and published, deleting overview/authority/prose. Fixed by iterating `sorted(set(index_changes) | set(supplied_index))` and using `index_changes.get(owner, ())`. Regression: `test_an_index_only_edit_cannot_discard_unrelated_prose`.
2. **Raw `PermissionError` leaked from lock acquisition** (`_FileLock.acquire`): a pre-created read-only lock file raised a bare `PermissionError` instead of a `DomainError`. Fixed by wrapping the exclusive create-open in the `knowledge_lock_timeout` error envelope. Regression: `test_an_unreadable_lock_is_an_explicit_error_not_a_leak`.
3. **Stale semantic assessment accepted for delete/supersede/rename** (`prepare_change`): `required_review` was only populated when `current is not None` in the replace branch and (with old-bytes semantics) for rename; delete/supersede of an unreviewed document prepared fine. Fixed: the replace-branch guard now also records for delete/supersede, and the rename branch records the old document's current hash. Regression: `test_a_stale_assessment_blocks_delete_supersede_and_rename`.

### Verified per AC (summary; full matrix in check handoff)

- AC-01: read-only calls create no lock/runtime files (fixture-diff tests re-verified); no `knowledge`/`learn` CLI command in `cli.build_parser()`; absent-store read initializes nothing; forbidden directories never created.
- AC-02: strict accept/reject matrix holds (missing fields, unknown/duplicate/type-inapplicable keys, non-string values, wrong category, malformed frontmatter, BOM-before-`---` rejected, CRLF accepted with original-byte digest, superseded-but-invalid rejected).
- AC-03: language policy via real `load_config` (rules/memory en, specs `language.specs` with project override, context/references artifacts language, plain prose accepted without frontmatter).
- AC-04: overview → indexes → global constraints → authority → topics/dependencies with cycle detection; unknown applicability broadens; budget exactly-at-boundary loads the body (probe verified `complete=True` at exact total, one-under defers exactly 1 item); no slicing.
- AC-05: tier 0/1/2/3 ordering, existing authority rank-0 in project tier, equal-tier unresolved, excluded memories moot, missing review → incomplete.
- AC-06: confirmation binds hash/scope/owners/quote/time; denied/deferred/missing → zero writes; repeat apply → `already_applied`; promotion consent enforced.
- AC-07: body+index+references as one group; rename with stale inbound link fails at prepare with actionable file list.
- AC-08: failure injection at stage/coordinator/publish/validate/commit/cleanup; crash recovery in the same and a retry process; third-value external edit → `recovery_conflict` without clobbering; recovery explicit and idempotent.
- AC-09: real two-process flock serialization; a two-process prepare→apply with stale digest loses with `knowledge_write_conflict` and the other writer's bytes survive (probe re-verified after fixes).
- AC-10: consumers get paths/bytes/hashes read-only; TaskStore.scan(archived=True) archive evidence; no caller-wiring claims.

### Commands and results

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_knowledge.py'   # 98 tests, OK (~3.5s)
PYTHONPATH=src python3 -m unittest discover -s tests                            # 492 tests, OK (~38s)
python3 -m compileall -q src tests                                              # OK
PYTHONPATH=src python3 -c '...validate_resources(Path("resources"))...'         # issues: ()
```

### Honest limitations

- Two-probe observations that are NOT defects (documented, not changed): non-`.md` files in strict category directories are simply not loaded (design only reads Markdown knowledge files, and `_walk_files` filters by suffix; the `knowledge_unindexed` diagnostic family covers reachability, not extension policy); the project index can still be deleted via an explicit authorized index-only delete edit (consent-bound and reported in `changed_paths`; treating index deletion as forbidden would be a design decision, not a defect).
- Windows/other non-POSIX hosts and the `fcntl` fallback path cannot be exercised here (`knowledge_unsupported_platform` is the designed behavior).
- Semantic/language review remains structurally unverifiable by script; the module's docstrings claim no regex semantic proof.
- The `resources/references/knowledge-format.md` two appended sections were verified to add no new required field and no policy change; no edit was needed by the check.


## Validation commands for implementation

Run from the repository root in the future implementation session:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_knowledge.py' -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
PYTHONPATH=src python3 -c 'from pathlib import Path; from fstar.content import validate_resources; issues = validate_resources(Path("resources")); print(issues); raise SystemExit(bool(issues))'
```

Use the repository's available Python 3.9 interpreter for compatibility verification and report its actual version. No test requires real home-directory writes or live retrieval services. Isolated fixtures prove API contracts; live host semantic loading and installer preservation need separate integration evidence. No new tests are written or run merely to verify this planning refresh.

## Risks, rollback and dependencies

- All body/index/reference writes are user data: function rollback preserves content; code rollback never deletes it. Recover pending operations before later writes; corruption/external changes stop recovery with backups retained.
- Existing templates and project indexes differ in presentation. Full-source/explicit-selection fallback must work; do not require rewriting an existing index to read it.
- POSIX flock support matches current core; unsupported hosts get an explicit error. Same-permission edits do not honor locks and cannot be made safe by approval JSON.
- Markdown link coverage is bounded and explicit. Unsupported potentially relevant links block destructive edits until reviewed; structural success is not semantic deduplication/conflict proof.
- No parent product decision remains open. Actual integration remains: init passes discovered taxonomy/authority; learn supplies source-bound semantic assessment/authorization and calls apply; runtime uses complete bundles and handles omissions/recovery; installer/doctor uses shared validation and preserves user knowledge; tools consumes sources read-only; e2e proves these in both hosts. These require owner coordination and are not silently included as completed child work.

## Planning validation / readiness

- Check all five artifacts exist, each Markdown document is <15,000 UTF-8 bytes, JSONL parses, all paths exist and refer only to documentation/research/specs (no src/tests).
- Compare PRD/design/plan against parent decisions manually. Text search catches stale wording but does not establish semantic consistency.
- Report concrete provider APIs, exact future ownership and remaining integration dependencies. Leave task status/current pointer untouched.
