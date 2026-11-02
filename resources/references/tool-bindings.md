# fstar tool bindings

This is the single format and API authority for capability bindings. It
describes the `fstar.tools.v1` file, the supported YAML subset, the binding
resolution, the confirmed mutation flow, the scan protocol, and the provenance
record. The five capability contracts live in `capabilities/<id>.md`.

Capability contracts belong to fstar, the selection belongs to the user, and
tools are external facts. Discovery is not binding; availability is not
acceptance. Nothing here installs a tool, creates an index, or changes a
binding automatically.

## Files and precedence

| Layer | Path | Confirmation |
|---|---|---|
| project | `<project>/.fstar/tools.yaml` | required for every binding |
| user | `~/.fstar/tools.yaml` | required for every binding |
| bundled | module defaults in `fstar.tools` | never; recommendation only |

Resolution walks the fixed five capabilities and takes the first layer that
contains the capability key: project, then user, then the bundled
recommendation. A missing key inherits. An explicit `tool: null` binding is an
unbind and stops fallback. The selected binding and the tool snapshot used for
`kind`, `version`, and `match` always come from the same file, so metadata is
never spliced across layers. A bad upper file is an error, not a silent
fallback to the lower layer.

`detected_at` is the saved discovery-snapshot time. It does not mean the tool
is currently available. Availability is a runtime fact reported by
`assess_availability` and is never written into `tools.yaml`; a machine change
requires verification again.

## Supported YAML subset

The file is parsed with the project's existing `config.parse_config`; there is
no separate general YAML parser. Supported:

- one top-level mapping;
- nested mappings indented by exactly two spaces per level;
- plain, single-quoted, and double-quoted scalars;
- JSON flow lists and objects on a single line (complex values use this);
- scalar block sequences (`- value`), for example one JSON object per item.

Not supported: block mapping sequences (`- tool: x` followed by indented
properties), multi-line flow collections, anchors, tags, multi-document
streams, and block strings. A rejected block mapping sequence reports its
path, line, and a migration hint: write each item as a single-line JSON flow
object instead.

The writer emits exactly this schema: one top-level key per line, with complex
values as single-line JSON. Every write is re-parsed and re-validated before it
replaces the target file, so a written file always round-trips.

## Document schema

`resources/schemas/tools.schema.json` is the published contract; the runtime
validates it with explicit standard-library checks.

- Top level (exact keys): `schema`, `detected_at`, `tools`, `bindings`,
  `history`. Unknown keys are errors. `schema` is `fstar.tools.v1`.
- Tool: `tool` (unique stable identifier), `kind` in `cli|mcp|skill|builtin`,
  `version` (string or null; unknown is null), `capabilities[]`.
- Match: `id` (one of the five capabilities, unique per tool), `match` in
  `strong|weak|none`, `basis` (non-empty judgment), `basis_source`
  (`kind` in `registry|probe|user|unclassified`, `reference`, optional
  `confirmation`). A strong match requires a registry basis or a confirmed
  user judgment; a probe can only produce weak; an unclassified tool is none.
  `code-text` and any sixth capability are rejected.
- Binding: `{tool, reason, confirmation}`. `tool` is a tool identifier in the
  same file or null. A dangling reference is an error.
- Confirmation: `source_id`, `type` in `command|conversation|review`, `at`,
  `actor` (`role: user`, `id`), `reference`, `quote`, `scope`, `validates`.
  A conversation needs the user quote and a locateable reference; a review
  needs a record that links back to a current user confirmation, not just the
  word "approved".
- History: `{id, at, kind: binding_changed, changes, source, before_digest}`.
  Only successfully committed binding changes are recorded; a proposal,
  rejection, conflict, or write failure leaves no authorization entry.

Complex values, including the full diff, use JSON flow values. Example
(illustrative; the digest and confirmation must be produced by a real proposal
and a real user confirmation, and this file does not claim any call happened):

```yaml
schema: "fstar.tools.v1"
detected_at: "2026-10-29T08:00:00Z"
tools: [{"tool": "codegraph", "kind": "mcp", "version": null, "capabilities": [{"id": "code-structure", "match": "strong", "basis": "symbol-level definitions, references, and impact", "basis_source": {"kind": "registry", "reference": "registry/codegraph.yaml@v1"}}]}]
bindings:
  code-structure: {"tool": "codegraph", "reason": "user selected structure retrieval", "confirmation": {"source_id": "input-17", "type": "conversation", "at": "2026-10-29T08:05:00Z", "actor": {"role": "user", "id": "user-1"}, "reference": "host/session-1/input-17", "quote": "use codegraph for structure retrieval", "scope": {"target": "project", "path": "/fixture/.fstar/tools.yaml", "changes": {"code-structure": "codegraph"}, "tools": {"codegraph": {"tool": "codegraph", "kind": "mcp", "version": null, "capabilities": [{"id": "code-structure", "match": "strong", "basis": "symbol-level definitions, references, and impact", "basis_source": {"kind": "registry", "reference": "registry/codegraph.yaml@v1"}}]}}}, "validates": "0f4c1c0e5e42ad25bd5b2a3dd665e92d5a1c6a02a15a1d6a59e16e1dcb44b7a2"}}
history: []
```

## Public API

| API | Contract |
|---|---|
| `load_tools(path)` | one layer: `{state: missing\|loaded, path, document, digest}`; missing digest is null; an existing empty/invalid/unreadable/wrongly encoded file raises `DomainError`. |
| `validate_tools(document)` | pure schema and cross-field validation; returns a normalized copy. |
| `serialize_tools(document)` | schema-specific writer; output round-trips through `parse_config`. |
| `load_defaults()` | bundled recommendation layer; recommendation only. |
| `resolve_bindings(project=, user=, defaults=)` | per-item project > user > defaults resolution; no I/O. |
| `build_binding_proposal(target=, loaded=, changes=, reason=, tools=)` | pure proposal with target, absolute path, old-byte digest, complete diff, and proposal digest. `changes` maps a capability to a tool identifier or null; `tools` carries metadata/classification snapshots (or null removals) so the confirmed diff covers more than the selected tool id. |
| `apply_binding(proposal, confirmation, *, clock, user_root, project_root, runtime_root, lock_timeout=5.0)` | internal API; re-validates confirmation and roots, locks, re-reads, commits atomically, and appends authorization and history in the same file. `user_root`/`project_root`/`runtime_root` are the caller's explicit roots (API extension over the plan's `clock`-only signature; roots are required to reject a forged target). |
| `assess_availability(resolution, observations, *, now=None, max_age_seconds=None)` | pure three-layer assessment and gap output; no host call. |
| `build_provenance(resolution, call_record, availability=None)` | builds `fstar.tool-use.v1` from a real call only. |
| `record_provenance(store, ref, record, *, lease_token, clock)` | core-store transaction bridge; `ref=None` is session-only and touches no store. |
| `register_commands(subparsers)` | the only user command: `fstar tools scan`. |

## Proposal and confirmation

A proposal contains `schema`, `target` (`user` or `project`), absolute `path`,
`old_digest` (SHA-256 of the target bytes, null when missing), `changes`,
`tools`, `reason`, and a `digest` computed with the core `content_hash`.

The confirmation `scope` must equal the proposal's `target`, `path`,
`changes`, and `tools` exactly, and `validates` must equal the proposal
digest. Any mismatch is rejected without touching the file:

- missing or structurally invalid confirmation: `tools_confirmation_required`;
- scope mismatch: `tools_invalid_confirmation`;
- proposal digest mismatch: `tools_stale_confirmation`;
- wrong or out-of-root target, including a symlink: `tools_unsafe_target`;
- target changed after the proposal was built: `tools_binding_conflict`.

The write order is: pure confirmation/target validation, lock the target's
runtime lock (POSIX `fcntl`), re-read the target and compare its byte digest,
build and serialize the candidate, re-parse and validate it, then write a
temporary file in the same directory, fsync, and `os.replace`. Errors and
conflicts leave the original bytes and history unchanged and remove the
temporary file. A replay of the same `source_id` and diff returns
`already_applied` without a second history entry. The lock and target
directories are only created after the confirmation is validated; reads and
proposals never touch the filesystem. Project bindings require an initialized
project; user bindings never initialize anything else.

`tools.yaml` is shareable configuration. Machine paths, credentials, and live
verification state never go into it.

## Scan protocol

`fstar tools scan` is the only user command. Its handler is registered on the
`tools` parent parser and runs before core project discovery, so a scan can
report unavailability on a project that is not initialized yet. It lazily
imports `fstar.tool_classifier.scan_tools` (a later subtask) and calls:

`scan_tools(*, project_root, user_root, host_snapshot) -> fstar.tools.scan.v1`

The result contains `detected_at`, `tools`, `observations`, `proposals`, and
`diagnostics`. A missing classifier is a stable non-zero
`tools_classifier_unavailable`; an internal import failure is
`tools_classifier_import_failed` and is never turned into an empty successful
scan. A scan is proposal-only: it writes no binding, creates no index, and
installs nothing. The classifier reuses the `Tool` and `Observation` shapes
above; `fstar-tools` owns binding guidance and calls the internal APIs only
after an explicit user confirmation.

## Provenance

`fstar.tool-use.v1` records an actual call:
`id, capability, tool, kind, version, at, binding_origin, binding_digest,
match, basis, call{id, reference, operation, result}, availability, fallback`.
`result` is `passed|failed|blocked`; a failure is recorded honestly. Only
attempted calls with a real call id and source reference produce a record; a
scan candidate or binding proposal is not a call. `tool` is the tool actually
used: when the call took the degraded path (the capability is unbound, or a
different tool than the bound one served it), the caller names that tool in
`call_record.tool` and `kind`/`version` stay null unless they come from the
bound snapshot; `fallback` is then true and the binding fields still show what
was authorized. An unbound capability cannot record a provenance without
naming its degraded-path tool. `operation` is a sanitized
summary; credentials, SQL row data, and raw responses are never stored. An
unknown version stays null.

`record_provenance` appends the record to `capabilities[]` and a unified event
inside a core `TaskStore` transaction. It requires an in-progress, non-dropped
task with the current unexpired lease token; it never renews the lease, never
touches `extensions[]`, `phase`, or `acceptance`, and never creates a
`task.json` when `ref` is null (session-only). A `capabilities[]` record is a
call fact, not an extension grant and not an independent check.
