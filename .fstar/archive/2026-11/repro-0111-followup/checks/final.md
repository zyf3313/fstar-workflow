# Check report — dispatch f2fee6b6-e201-4688-be5a-4189c4f18c2b

Independent checker: fresh agent, no shared context with implement workers.
Scope owned: criteria A-001, A-003..A-006 in
`/Users/zhangyangfan/workspace/projects/vibecoding/fstar-workflow/.fstar/tasks/repro-0111-followup/criteria.md`;
production `src/fstar/{cli,crossproject,dispatch,evidence,tasks}.py`, tests
(incl. `tests/test_repro_followup.py`), schema/README text. installer/magpie
reviewed only for interactions (another checker owns them).

Baseline: uncommitted working tree on branch `fix/repro-0111-followup`
(main = 9e980e1). No production edits made by this check; only this report
file was written.

## Environment

- `/usr/bin/python3` 3.9.6; PYTHONPATH=src; repo at
  `/Users/zhangyangfan/workspace/projects/vibecoding/fstar-workflow`.
- Isolated probes: temp project `/tmp/fstar-check-Bwgsxg/proj` (+ `proj2`,
  separate user registry under `/tmp/fstar-check-Bwgsxg/userhome`), created
  via `fstar init` / `init --storage user-directory` with real CLI subprocesses.

## Test suites (actual runs)

- `PYTHONPATH=src python3 -m unittest discover -s tests -t .` →
  `Ran 1044 tests in 128.690s` / `OK` (exit 0).
- `PYTHONPATH=src python3 -m unittest tests.test_repro_followup tests.test_dispatch tests.test_core` →
  `Ran 203 tests ... OK`.
- `node --test tests/test_package.cjs` → `pass 16 / fail 0` (exit 0).
- `node scripts/build-package.cjs` → resource_version 10, cli_version 0.11.1;
  re-running the build produced a manifest whose every `sha256` matches the
  current working-tree files (verified by recomputing all entry hashes:
  "manifest fresh"). No drift after rebuild.

## A-001 — deliverable evidence mapping (VERIFIED, with one caveat)

CLI flow in a fresh temp project, supported commands only, no task.json repair:

1. `fstar task create`, `fstar start --confirm-user`, `fstar state
   add-deliverable t1 --name out --path out.txt --criteria A-001` (exit 0).
   The registered map became
   `{"out.txt": {"A-001": {"mode": "file", "dependencies": []}}}` — a usable
   item-scoped mapping, not an empty entry.
2. Implement dispatch `fstar dispatch implement --payload …` → harvest (exit 0,
   `state: valid`), then a distinct-producer check dispatch with check
   evidence → harvest (exit 0, `next: enter_awaiting_acceptance`), lease
   released, `fstar accept t1 --awaiting` → phase `awaiting_acceptance`
   (exit 0).
3. Freshness: after `printf 'hello v3' > out.txt`, `fstar acceptance status`
   reports `"fresh": false`; `fstar accept --confirm-user` fails
   `acceptance_blocked` "Fresh independent final check evidence is required"
   (exit 3). Delivered-file change stales earlier evidence.
4. Independence: check evidence with producer id equal to the delivery
   implementer is rejected `check_not_independent` (verified in
   tests/test_repro_followup.py:367 and by the guard at evidence.py:377-381).
5. Scope: evidence with invented requirement id → `invalid_check_scope`
   (exit 2, task.json unchanged, md5 before == after).
6. Unsafe paths: `../escape.txt`, `.`, ` mode` (trailing-space alias of
   "mode"), absolute paths → `unsafe_evidence_path` without mutation (CLI and
   test_unsafe_registration_does_not_mutate, which also covers symlink-dir
   paths and NUL bytes).
7. Mixed maps: a pre-existing marker mapping for the same path is preserved
   (probe: MARK-1 mapping survived two more add-deliverable calls with
   criteria); file-mode items are added only when the artifact has no
   non-file-mode items; a deliverable with no criteria_refs binds the path
   itself as item id (verified `{"z.txt": {"z.txt": …}}`); empty legacy map
   grants no scope (mapping_missing).

Caveat (not a criterion failure, pre-existing behavior): artifact-map item
dependencies are resolved per-artifact only. A file-mode item whose
`dependencies` list names an item mapped under a different artifact path is
reported as `dependency_missing` at record time (probe on t5: A1 listed as
dependency of b.txt's B1 while A1 is mapped under a.txt). I confirmed the
old marker-mode code has the same per-artifact limitation at baseline 9e980e1
(_validate_current reads `mappings.get(artifact)`), and the same-file marker
dependency case (test_mixed_mapping_dependency_and_file_freshness) works,
including dependency_changed detection. New whole-file dependencies work
within one artifact. The criteria text ("dependency/freshness checks …
remain intact") is satisfied: intact means no regression, and there is none.

## A-003 — idempotent dispatch registration (VERIFIED)

- Identical retry: registering payload d-check-1 twice → second reply has
  `existing_registration: true`, `registration_state: registered`; exactly
  one `dispatch_registered` event and one meta record
  `{"sha256": …, "state": "registered"}` in
  `meta.templates.dispatch_registrations`.
- Divergent reuse, same id: role change, plan_item_ids change, allowed_paths
  change, editor fields (`item_ids`, `baseline_sha256`), extensions change →
  `dispatch_id_conflict` (exit 4) without mutation. Extension changes are
  included because persisted grants are folded into the effective payload
  before identity hashing (dispatch.py:~590), verified live and by
  test_editor_fields_and_authoritative_extensions and the new assertions in
  tests/test_dispatch.py.
- Harvest also verifies identity (dispatch.py:1184-1190): harvesting with an
  altered payload → `dispatch_id_conflict`.
- Compaction: after padding events past EVENT_LIMIT (200), all
  `dispatch_registered` events were folded away, yet replay still returned a
  coherent existing registration (`state: harvested`) from the persisted
  meta record — one event, no duplicates. (test_four_retries… covers the
  supported path to the same state via set_next_step.)
- Interrupt: `fstar interrupt … --release-lease-token` marks the record
  `state: interrupted` and releases the lease (verified live); replay reports
  `registration_state: interrupted`, `lease_token: null`, no re-registration.
- Lease conflicts: replay while another holder (id other-coordinator) holds
  an active lease → `lease_conflict` (exit 4) without re-acquire; same
  holder with an active lease gets the existing token back only when the
  record state is `registered` and phase is in_progress.
- Harvested results stay terminal: replay after harvest →
  `registration_state: harvested`.
- Legacy tasks: id with a historical `dispatch_registered` event but no
  identity record → `dispatch_identity_unknown` "use a new id" (exit 4), no
  history rewrite; a new id registers normally. Tasks predating this feature
  carry no new metadata until they register a new dispatch (probe: t1's meta
  gained `dispatch_registrations` only after a registration).

## A-004 — JSON stdin (VERIFIED)

- `dispatch implement --payload -` with a valid session-only JSON object →
  exit 0. `start --confirmation -` with a valid confirmation object →
  in_progress (exit 0); with invalid JSON → `invalid_json_file`, no mutation.
- Invalid input: `not json`, `[1,2]`, empty → `invalid_json_file` /
  "document must be an object", task.json byte-identical before/after.
- Duplicate consumers: `--payload - --result -`, `--result - …
  --check-evidence -`, `--confirmation -` + another `-` → deterministic
  `stdin_document_reuse` (exit 2) raised before any document is read (arg
  preflight in cli.py main), so it can never block or silently cross-wire
  documents. Single-use is per-invocation: a second `main()` call in the same
  process resets the reader (test_repeated_main_invocations…).
- One consumer per invocation is enforced across payload, result,
  confirmation, check_evidence, record, scope_file, rule, plan_items fields.
- File paths behave as before (all file-based probes above used files).

## A-005 — cross-project not-found hints (VERIFIED)

Setup: proj (project-shared) + proj2 (user-directory, registered in the
shared user registry) each with real tasks.

- From proj, `task locate <proj2-task-id>` → local `task_not_found` failure
  (exit 2) whose details include `foreign_candidates` (project path, task id,
  name, phase, archived flag, path) and a `hint` naming `--project PATH`.
  JSON and human output both carry the enrichment.
- The advertised guidance is truthful: `--project <proj2> task locate <id>`
  → `status: found` (exit 0).
- Read-only: byte-for-byte comparison of all files under the temp root before
  vs after lookup showed no writes (also asserted by the test); proj2's
  task.json mtime unchanged across probes.
- Broken registry entries: a project at a nonexistent path and a corrupt
  (wrong marker) existing project are reported under
  `foreign_candidates_skipped` and never break the local lookup; a corrupt
  registry file itself (invalid JSON) still yields the plain local
  task_not_found with no crash.
- Registry-scoped only: foreign_task_candidates (crossproject.py:568+) reads
  only `<user_home>/projects.json` and probes registered roots read-only; no
  filesystem-wide scan path exists in the function.
- Same-name hits: proj2's `t1` resolved locally first; multiple foreign hits
  remain explicit separate candidate entries (test asserts 2 candidates for
  two same-named projects; third unregistered project is excluded).

## A-006 — evidence schema and digest guidance (VERIFIED)

- `fstar schema evidence` (exit 0) exposes field reference + example. The
  fixture hashes are real: example.txt `sha256` = sha256("hello\n") =
  5891b5…be03, and example `delivery.digest` a59fb9…5a8a equals
  content_hash of the sorted path/existence/raw-byte entry list — I
  recomputed both independently and they match.
- README (lines 175-187) is accurate against implementation:
  - delivery_snapshot (evidence.py:204-210) sorts+dedupes paths, records
    {path, exists, sha256} with `file_digest` = raw-byte SHA-256 (null when
    missing); `digest` = `content_hash(entries)` = SHA-256 of UTF-8 JSON with
    sorted keys, no whitespace, non-ASCII preserved (store.py:26-31). Matches.
  - Whole-file item snapshots hash `_normal_text` (CRLF/CR → LF) — verified
    divergence live: same file raw hash cd2eca… vs normalized item hash
    5891b5… (b"hello\r\n"). Matches README's statement that the two can
    differ.
  - "Item dependencies are tracked too" — dependency_changed detection works
    (same-artifact marker and file-mode dependencies; see the A-001 caveat
    for the cross-artifact limitation which is pre-existing).
- Empty baselines valid: `schema payload` example now uses `"baseline": {}`
  and registers successfully; `schema result` example has empty
  input_baseline/delivery_baseline objects that pass validate_result; docs
  state both must be objects and may be empty; harvest verifies payload input
  fingerprints and computes its own delivery snapshot (verified: harvest
  returned unverified_inputs: [] and a valid delivery-derived evidence).
- No actual→expected copying advice: README explicitly says "Do not copy a
  reported actual hash over an expected hash…that would not establish that
  the new contents were checked" and prescribes recomputation + fresh
  independent check. Schema guidance likewise labels the example an
  illustrative fixture not to submit as a real check.

## README/schema accuracy spot-checks

- `fstar schema payload|result|change|evidence` — all four choices accepted.
- schema result documents input_baseline/delivery_baseline as required
  objects possibly empty — matches validate_result (dispatch.py:332-334).
- README §5 digest text matches implementation (verified above).
- README Magpie/hand-over paragraphs (stale_pending_removal,
  stale_but_modified, magpie 0.1.4722) — outside my primary scope; I only
  confirmed the text exists and the installer/magpie code contains the
  corresponding states; another checker owns verifying those claims.

## Interactions reviewed (installer/magpie, secondary)

- `_read_stdin_json` import in dispatch.py uses the cli module-level
  `_STDIN_DOCUMENT` reset in `main()`; no circular-import problem observed
  (full suite green).
- tasks.py `_acquire_lease` refactor: acquire_lease delegates under the same
  transaction; verified lease takeovers, conflicts, and release still behave
  (probes above). No behavior change detected for callers outside dispatch.
- Nothing in the diff weakens path confinement: project_file rejects
  escapes (unsafe_evidence_path probes), crossproject probing is read-only.

## Unverifiable / limits

- I did not run a real Magpie CLI or install/update on the host (out of
  scope, and no real Magpie actions allowed). Installer symlink/magpie claims
  rest on the other checker.
- The uTools note and field-report artifacts referenced in criteria were not
  re-verified; local reproductions under /var/folders/... were not re-run.
- "Same-name multiple hits remain explicit candidates" verified via the
  unit test (two foreign projects) plus code reading, not a second live
  foreign project (only one registered foreign project was created live).

## Verdict

A-001, A-003, A-004, A-005, A-006: PASS within the checked scope. No
production changes were needed; no repair performed. No criterion failed.
One caveat documented (cross-artifact dependency resolution) is pre-existing
baseline behavior, not introduced by this delivery.
