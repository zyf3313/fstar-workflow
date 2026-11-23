# Independent review: fstar-doc retirement

Checker: fstar-check a2980d0150d79639f, distinct from implementer af99c62e0bad6aa11. Initial review found a custom-grant routing contradiction and a stale expected skill count. Both were repaired and independently rechecked: document-kind storage no longer requires the unrelated plan member, plan creation still requires plan, and doctor expects 10 skills. The targeted doc-retirement suite passed 12 tests.

The checker verified 63 manifest entries and twice rebuilt the then-current combined delivery in a temporary copy with identical hashes. The parallel pointer-safety repair subsequently changed `store.py`; the manifest was rebuilt again, and the Node package test verified its hashes. Final manifest SHA-256: d0aae22a9c9338ccfb8c72c65d4afeadbaebc3c0cdba8643feb995916b82b569. The earlier independent two-build check predates this final rebuild.

The checker confirmed relocated responsibilities, retained checklist references, legacy grant load/archive coverage and update handling for owned, modified, and missing retired files. It did not independently exercise every host variant or a real previous-version installation. The custom-grant test checks authorization records and routing text, not model execution.

Final combined suite after pointer repair: canonical `PYTHONPATH=src python3 -m unittest discover -s tests -t . -q`, 992 passed; Node package suite, 16 passed. The alternate discovery command without `-t .` failed four Magpie installer tests; the checker reproduced these failures on the baseline under that discovery mode. Following the README-only worktree correction, the 12 doc-retirement tests passed again.

This report records review facts, not task acceptance. The shared README and manifest changed after the earlier review; delivery freshness must be re-established.
