# Check Report — host-abstraction-magpie-router (final registered check)

- Dispatch: check-host-5 (role: check, `fstar.dispatch.v1`); worker return uses `fstar.dispatch.result.v1` fields.
- Scope: P-001..P-004; complete current PRD/design/plan/clarify consistency; all prior defect locations; slot/ID/reference preservation; R-005 obsolete-demand repair; D-005; README consistency.
- Baseline: `/tmp/fstar-check-host-5-payload.json` (95 input_versions; R/D item snapshots); runtime delivery gated on `/tmp/fstar-check3-code-baseline.json` (86 files).
- Date: 2026-11-20
- Final status: **done** — every prior defect is fixed, the documents are consistent with the delivered code and README, and the runtime delivery is byte-identical to the previously verified check-host-3 tree. No code, test, or config change occurred.

## Failure history (brief, preserved)

- check-host-3: found `design.md` §2/§3 (and D-005 wording) describing the retired `ownership="magpie"` / no-native-copy model.
- check-host-4: design repair verified, but `prd.md` §2/§3 narrative and `plan.md` Risks still carried the retired conditional-fallback model; R-005 still demanded the obsolete “双来源去重/移除后回退” test set.
- check-host-5: the editor synchronized PRD §§1/2/3/5 and R-005, marked historical unknowns as historical in PRD/design §9, and the coordinator fixed `plan.md` Risks. All findings below are from the current files.

## 1. Input verification

```
python3 - <<'EOF'
import json,hashlib
p=json.load(open('/tmp/fstar-check-host-5-payload.json'))
bad=[f['path'] for f in p['input_versions']
     if hashlib.sha256(open(f['path'],'rb').read()).hexdigest()!=f['sha256']]
print('inputs',len(p['input_versions']),'bad',bad)
for art in p['baseline']['artifact_items']:
    text=open(art['artifact'],encoding='utf-8').read().replace('\r\n','\n').replace('\r','\n')
    for it in art['items']:
        s=f"<!-- fstar:item:{it['id']}:start -->"; e=f"<!-- fstar:item:{it['id']}:end -->"
        h=hashlib.sha256(text.split(s,1)[1].split(e,1)[0].encode()).hexdigest()
        print(it['id'],'OK' if h==it['sha256'] else 'MISMATCH '+h)
EOF
```

Result: `inputs 95 bad []`; R-001..R-005 and D-001..D-005 all `OK` against the payload snapshot (R-005 is the revised hash `cc8c5829…`; the other items are unchanged).

Observed document hashes: prd.md `2a9d4d69…`, design.md `c67ae4d6…`, plan.md `7d270364…`, clarify.md `b805bd5f…`, README.md `9999a04c…` — exactly the payload entries.

## 2. Runtime delivery gate — 86/86 unchanged

```
python3 - <<'EOF'
import json,hashlib
b=json.load(open('/tmp/fstar-check3-code-baseline.json'))
bad=[p for p,h in b.items() if hashlib.sha256(open(p,'rb').read()).hexdigest()!=h]
print('runtime',len(b),'changed',bad)
EOF
```

Result: `runtime 86 changed []`. Production, test and resource delivery is byte-identical to check-host-3, so its passing runtime results are reused with provenance, per dispatch; no suite was rerun.

Reused evidence (check-host-3, same 86-file delivery):

- `PYTHONPATH=src python3 -m unittest discover -s tests -t .` → `Ran 788 tests in 97.262s — OK`.
- `node --test tests/test_package.cjs` → `tests 16, pass 16, fail 0` (7306 ms).
- `PYTHONPATH=src python3 -m unittest tests.test_global_resources tests.test_magpie tests.test_installer tests.test_hooks tests.test_e2e_scenarios` → `Ran 306 tests in 71.813s — OK` (two-layer impact: prior global-resource/migration/Magpie batch + installer/hooks/e2e, existing Claude native path).
- Isolated temp-root smoke with fake Magpie (working-tree CLI via `PYTHONPATH=src python3 -m fstar`; the global `fstar` binary is stale 0.4.1): (a) Magpie present → 11 claude + 11 codex native skills, `diff -r` clean vs `resources/skills`, `magpie.status=handed_over`, per-skill `library=handed_over`; (b) `--native-only` → `native_only`, `consulted=false`, 11+11 native, agents source empty, no record; (c) Magpie absent → `skipped`, 11× `magpie_absent`, 11+11 native; (d) Magpie removed then doctor → `healthy=True`, single `MAGPIE_LIBRARY_UNREACHABLE` severity `info`, native 11+11 intact; (e) rerun → 0 writes, 11× `already_integrated`; legacy `ownership="magpie"` record read as `handed_over`.
- Code facts bound by hash identity: no `route=="magpie"` skip/retire branch in `installer.py`; `MAGPIE_OWNER_MISSING` absent from `src/`; doctor ignores `severity=="info"` for `healthy`.

## 3. Document consistency recheck (current files)

### 3.1 Structural preservation — PASS

```
PYTHONPATH=src python3 - <<'EOF'
from pathlib import Path
from fstar.content import load_mapping, extract_artifact, build_artifact_map
pairs=[('.fstar/tasks/host-abstraction-magpie-router/doc/prd.md','resources/templates/doc/prd.mapping.yaml'),
       ('.fstar/tasks/host-abstraction-magpie-router/doc/design.md','resources/templates/doc/design.mapping.yaml'),
       ('.fstar/tasks/host-abstraction-magpie-router/plan.md','resources/templates/task/plan.mapping.yaml')]
for d,m in pairs:
    e=extract_artifact(Path(d).read_text(encoding='utf-8'), load_mapping(Path(m)), artifact=d)
    print(d,'ok=',e.ok,'slots=',sorted(e.slots),'items=',[i.id for i in e.items],'diags=',[x.code for x in e.diagnostics])
print('map ok:', bool(build_artifact_map([extract_artifact(Path(d).read_text(encoding='utf-8'), load_mapping(Path(m)), artifact=d) for d,m in pairs])))
EOF
```

Result: PRD and design `ok=True` with the six required slots (`prd`/`design`, `0.1`, `draft`, `FrancisZhang`, `2026-11-20`, empty reviewer); item IDs exactly R-001..R-005, D-001..D-005, P-001..P-004 with zero diagnostics; artifact map builds. No `fstar:ref` markers exist, so D→R references remain textual in headings (unchanged authoring convention).

Requirement coverage: R-001→D-001→P-001; R-002→D-002→P-002; R-003→D-003→P-003; R-004→D-004 and R-005→D-005→P-004. No orphaned item.

### 3.2 PRD — PASS (all prior defects fixed)

- §1 line 14 now labels the pre-implementation state as historical background and points to the README matrix for current capability; line 16 records the user's rework quote and the native-always + additive semantics.
- §2 line 76: native skills unconditionally installed; Magpie hand-over additive per skill; failure affects library distribution only.
- §2 line 78: Magpie failure skips library distribution only; doctor reports `MAGPIE_LIBRARY_UNREACHABLE` at info level, explicitly “不需要回退”; the prior “失去管理者/提示用户回退” text is gone.
- §3 lines 82-85: manifest/fingerprint + `fstar.magpie-integration.v1` legacy compatibility; magpie module records per-skill `library` status; doctor informational diagnostic with no fallback.
- §5 line 95: the pending list is marked historical with the actual verification result (Codex user-level hooks/skills supported, trust-review caveat) and the old degradation rule marked as historical.
- R-005 line 65 no longer demands “双来源去重/移除后回退”; it now lists native-always, library-only failure, `--native-only`, informational doctor, idempotency and legacy compatibility — matching D-005 and the actual tests.

### 3.3 design.md — PASS

- §1 line 12, §2 line 16, §3 lines 21-22, §7 lines 69-71, §8 line 78 all describe the additive model; D-003 line 41 names `MAGPIE_LIBRARY_UNREACHABLE` severity=info, info excluded from `healthy`, `MAGPIE_OWNER_MISSING` retired; D-005 line 53 matches the tests (previous “无原生副本” demand removed).
- §9 line 82 now marks the unknown-facts list as a historical design-time snapshot and records the implemented verification results and trust-review caveat.

### 3.4 plan.md — PASS

- Summary line 5: native-always + additive library sharing.
- P-003 line 29: amended semantics and test list.
- Risks line 43: corrected to the live risks (Codex trust review still required, duplicate listings resolved Magpie-side, instructions concurrent-edit window, old/new hooks migration dedup) — stale “未经实机验证 / 部分接管” wording gone.

### 3.5 clarify.md — PASS

Superseded rule is struck through and labelled “**已被返工取代**” (line 21); the rework section records the native-always/additive decision and the defect diagnosis (line 35 describes the removed branch as the defect, i.e. historical context).

### 3.6 Stale-phrase scan and README — PASS

```
grep -n '失败→原生回退|失去管理者|提示用户回退|按技能回退原生|回退需求|未经实机验证|部分接管|不写原生副本' prd.md design.md plan.md clarify.md
```

Result: only `clarify.md:21` (struck-through, marked superseded) and `clarify.md:35` (defect diagnosis in the historical rework record). PRD/design/plan contain none of the retired wording.

```
grep -n -F -- '--native-only' README.md ; grep -n -i 'always installed' README.md
```

Result: README lines 439/460/482/492 state native copies always installed, the single aggregated router skill, `--native-only` skipping the library hand-over, legacy `ownership: magpie` compatibility, and informational `MAGPIE_LIBRARY_UNREACHABLE`. README sha256 unchanged at `9999a04c…`.

## 4. Defects

None remaining in the current delivery.

## 5. Per-plan-item result

| Plan item | Requirement IDs | Result | Review method |
|---|---|---|---|
| P-001 | R-001, D-001 | passed | Read current plan item + D-001 + R-001; structural extraction; runtime baseline hash gate (86/86) with reused check-host-3 matrix/install/doctor tests |
| P-002 | R-002, D-002 | passed | Read current PRD §1/§5 historical marking, R-002, D-002; compared with registration evidence comments and reused Codex installer tests/smoke skills output; runtime unchanged |
| P-003 | R-003, D-003 | passed | Read current PRD §1/§2/§3/R-003/R-005, design §1/§2/§3/D-003/D-005, plan Summary/P-003, clarify rework; stale-phrase scan; reused smoke (a)-(e) + legacy-record check and 306-test impact subset under the 86-file hash gate |
| P-004 | R-004, D-004, R-005, D-005 | passed | Read current R-004/R-005/D-004/D-005 and plan P-004; README grep; reused instructions/conflict/idempotency tests from the unchanged suite, plus Node package tests |

## 6. Residual limitations

- Runtime evidence is reused from check-host-3 under an 86/86 hash gate; no suite was rerun for this docs-only revision, per dispatch.
- Real Magpie was never executed (fake binary only); the public CLI contract is as documented in `magpie.py`.
- The instructions read-then-write concurrent-edit window and the absence of a verified Magpie-side library update path remain as documented risks (plan Risks line 43; D-003).
- D→R linkage is textual in headings rather than `fstar:ref` markers; this matches the authoring convention of every prior document revision and preserves every ID.

## 7. Input baseline

- Payload `/tmp/fstar-check-host-5-payload.json` (`fstar.dispatch.v1`, P-001..P-004); 95/95 input_versions matched; R/D item snapshots all matched (`baseline.artifact_items`).
- Runtime gate `/tmp/fstar-check3-code-baseline.json`: 86/86 unchanged, so the check-host-3 Python/Node/impact/smoke results above are authoritative for this delivery.
- `task.json` was not read.

## 8. Delivery baseline

Only `.fstar/tasks/host-abstraction-magpie-router/check-report.md` was written. No production code, tests, documents, manifests, task/evidence state, commits, merges, publishes, or real host/Magpie configuration were changed.
