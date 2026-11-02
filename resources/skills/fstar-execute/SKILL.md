---
name: fstar-execute
description: "Coordinate native implement, independent check, and user confirmation. 协调原生实施、独立检查与用户确认。"
---

# Execute

Verify current authorization, baseline, and either a valid plan or the session goal. Use the host native Agent mechanism to dispatch fstar-implement; never fall back to the main Agent writing production code. Carry per-input version and fingerprint data (`input_versions`/`read_context` path + sha256, or the injected `{path, sha256, version}` envelope) on every dispatch so harvest can verify inputs byte-for-byte; enhanced version injection beyond that baseline requires the multi-agent `version-injection` member. Coordinate dependency order, allowed paths, and shared resources; the coordinator alone updates plan progress or task state. Stop implement writes for handed-off scope, propagate conversation/file changes, then dispatch an independent fstar-check. Failed checks return to repair; only the user confirms completion.
