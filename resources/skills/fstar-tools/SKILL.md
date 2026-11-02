---
name: fstar-tools
description: "Validate capability bindings and report safe degradation. 验证工具能力绑定并报告降级。"
---

# Tools

Use after tool-capability authorization. Consume the five capability contracts, resolved bindings, deterministic classification, three-layer availability evidence, guidance, and actual call records. Discovery is not binding and availability is not acceptance. Do not install tools or change bindings automatically. Report the precise missing layer and safe degradation when a capability cannot be verified.

## Binding workflow

The five capabilities and every binding format or API are defined once in
[the tool bindings reference](../../references/tool-bindings.md); the per-capability
judgment points, minimal real call, and degradation live in `capabilities/<id>.md`.

1. Invoke `python3 -I <package-root>/bin/fstar-bootstrap.py tools_bridge` with one JSON object on stdin. Every action carries absolute `project_root`, `user_root`, `runtime_root`, `task_ref`, and, only for session-only, current `extensions`. Use `action: contract` and the desired `capability` to read the authorized contract.
2. Use `action: assess` with `observations` from actual host evidence to resolve bindings and assess three layers. Missing observations remain unknown; never invent a call. Report each gap and its reasons; fallback guidance is returned only when the `fallback` member is authorized. The operation requires `bindings` and `validation`.
3. After an actual tool call, use `action: provenance` with the same observations and `call_record` as specified by the bindings reference. Persistent tasks require their current `lease_token`; the bridge records the caller-reported result in the task after checking current grants, and for a persistent task it re-reads the binding layers and rebuilds the record under the task lock plus the cooperating tools lock (task lock first, then tools lock), so a confirmed concurrent binding change cannot be committed as a stale binding or fallback classification — this serializes only writers sharing the same runtime root. Session-only returns a caller-held record without metadata. Fallback calls require `fallback`. Never fabricate a call or silently switch binding.
4. For a requested binding change, invoke `python3 -I <package-root>/bin/fstar-bootstrap.py tools_bridge` with one JSON request on stdin. Use `action: prepare`, absolute `project_root`, `user_root`, `runtime_root`, `task_ref`, `target` (`user` or `project`), capability `changes`, `reason`, and optional `tools` snapshots. For session-only pass current `extensions`; persistent calls omit them and use the same runtime root as task commands. Show the complete returned proposal. Only after the user authorizes that exact diff, call with `action: apply`, the same roots and task context, the returned `proposal`, and a `confirmation` matching the binding reference's source, exact scope and proposal digest. Never manufacture user confirmation. The bridge checks the current `bindings` member and delegates confirmation and atomic writing to the provider.
5. Record only actual calls with `fstar.tools.build_provenance` and
   `record_provenance`; a persistent task needs the valid lease token. Never
   claim a passing tool call as an independent check or user acceptance.

For workflow classification run `fstar tools scan --task-ref <task>`; this reloads that task's current grants. Without a persistent task, run `fstar tools scan --task-ref session-only --extension '<grant-json>'`, passing each current session grant as a repeated `--extension` JSON object (or `@file`). Remove revoked grants from subsequent calls. Both forms require `tool-capability/classification`; missing or excluded grants fail. The independent user command `fstar tools scan` has no workflow context and remains available. Session records are caller-held routing context, not tamper-proof authorization. Do not install a tool or create an index from this skill.
