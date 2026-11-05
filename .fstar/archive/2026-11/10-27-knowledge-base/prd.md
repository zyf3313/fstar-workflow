# Knowledge base and authorized learning

## Goal

Deliver a shared Python knowledge API that loads current personal/project guidance with explicit provenance and precedence, and saves authorized learning without losing body, index, or reference consistency. Existing project authority remains the starting point; knowledge survives task archive.

This child implements parent `10-25-fstar-workflow-design` PRD §§4,6,7,169–175 (language/format section) and design §§3.9,3.11,4.1–4.5. Parent prose sections, not historical research, govern. The parent's full design must be read when injection is truncated. This refresh is planning only; the active task remains tool-classifier.

## Current evidence and dependencies

- Core, project-layout, workflow-content, runtime, tool-binding, and classifier have implementation/check records; the reported complete baseline is 323 passing tests on Python 3.9.6. No classifier or core-file-mode blocker remains.
- `project.ProjectContext`, `TopicReference`, `DocumentReference`, `initialize_project` and `initialize_user` exist. Initialization preserves an existing index rather than refreshing it.
- `config.parse_config` and `load_config` exist; language defaults are interaction/artifacts `zh-CN`, specs `en`.
- `resources/references/knowledge-format.md` and current rule/memory/spec/index templates already express the approved format. Existing content frontmatter parsing is private and insufficient for strict knowledge validation. Store atomic JSON writes cover one file, not a knowledge group.
- This child owns the knowledge provider and its tests. Caller wiring in init/learn/runtime/installer is an explicit integration dependency, not a prerequisite that prevents implementing this API.

## Requirements

### KB-01 — Ownership and classification

User `rules/` contains constraints; user `memory/` contains preferences/lessons. Project `specs/` contains required practices and their reasons; project `knowledge/context/` contains facts/terms/FAQ; `knowledge/references/` contains external material and sources. Create these only for authorized content. No decisions/history/journal/workspace, candidate ledger, duplicate historical summary, or new user command.

Init owns initial project-wide discovery, taxonomy, summary, authority and reading indexes. Learn reads existing indexes and relevant bodies, updates an existing topic first, and explains why a new topic or taxonomy change is necessary. Cross-module guidance keeps one authoritative body with references. Preserve existing user prose and authoritative project documents; do not regenerate indexes destructively.

### KB-02 — One strict knowledge format

Rule/memory/spec use `fstar.knowledge.v1` with required scalar string `schema`, `type`, `status`. Type is rule/memory/spec; status active/superseded. Rule requires strength enforced/default; memory requires kind preference/lesson and trust confirmed/unreviewed; spec has no extra type-specific requirement. Missing, duplicate, invalid, wrongly typed or incompatible fields produce explicit diagnostics, including in otherwise excluded documents. Only active rules/specs and active confirmed memories enter effective context. No implicit defaults or automatic memory promotion.

Rules/memory are English; specs follow `language.specs` (English default, project override); context/references follow artifact language and are not forced into the rule frontmatter schema. Structural validation cannot prove natural-language meaning, language correctness or semantic consistency.

### KB-03 — Complete reading and explicit conflicts

Start with project overview, complete indexes, global constraints and existing authority. Then load full applicable topic bodies and upstream/downstream/shared contracts. Unknown applicability broadens reading; truncation or missing required bodies prevents claiming complete context.

After validity/applicability filtering: enforced rule > explicit project spec > default rule > confirmed memory. Within project guidance, existing authoritative project documents outrank derived fstar guidance. Show each identified conflict, sources, winning tier and reason; equal-tier unresolved conflicts remain unresolved. Do not silently merge incompatible statements or claim regex/priority sorting detects semantic conflicts. Current explicit user instructions and host constraints remain above this knowledge policy.

### KB-04 — Exact authorization

Present candidate content, source, destination/ownership, scope, proposed edits and conflicts. Already explicit authorization for the exact content and ownership is reused without another question. Missing authorization, rejection or deferral performs no knowledge writes and cannot produce effective knowledge; optional deferral does not block archive or cause repeated prompts.

Confirmation binds the reviewed proposal digest, exact resulting bytes/deletions, source, ownership and baseline. Changing content, paths, strength/trust, scope or references invalidates that confirmation. Memory-to-rule promotion requires its own explicit content/ownership authorization. Same-permission source records provide auditable validation, not an unforgeable approval system.

### KB-05 — Recoverable group update

Create/correct/replace/supersede/delete/rename must update body, index and affected supported references as one recoverable operation. Validate staged content and references before publishing; serialize concurrent writers (owner-root scope, which also covers same-file conflicts), recheck baselines, and reject stale proposals. Report saved only after the entire group validates and commits. Failure restores original bytes/absence; crash recovery must be testable and must not overwrite later external edits.

Guarantee consistent results for cooperating knowledge API readers through a documented transaction protocol. Do not promise simultaneous atomic visibility to arbitrary filesystem readers. Incomplete recovery or reference closure is an explicit error, never partial success.

### KB-06 — Consumers and historical recall

Expose reusable read/resolve/propose/apply/recover APIs. Tools is a read-only consumer of knowledge source paths, bytes, hashes and provenance; it owns tool binding, availability and capability recording. No QMD database, semantic search implementation, scan, installation, binding mutation or tool dependency is introduced here.

Archived history stays dynamically derived by existing `task list --archived`/TaskStore APIs from task records and linked plan/commit evidence. Recall reports sources and applicability differences and never restores an archived task. This child neither stores a ledger nor reimplements task lifecycle/CLI history.

## Acceptance criteria

- [ ] AC-01 / KB-01: isolated user/project fixtures create only authorized categories; no forbidden directory/ledger/CLI or implicit project initialization appears.
- [ ] AC-02 / KB-02: templates and round trips validate; required fields, enums, wrong types, duplicate keys, wrong category, malformed encoding/frontmatter and inactive-invalid records yield explicit errors; superseded/unreviewed bodies never enter effective context.
- [ ] AC-03 / KB-02: language policy follows real config precedence; rule/memory remain English policy, context/references accept project prose without knowledge frontmatter; manual semantic review is distinguished from syntax tests.
- [ ] AC-04 / KB-03: full overview/index/constraint then scoped/dependency bodies are returned with hashes; ambiguity broadens reading; missing/over-budget bodies are itemized and completeness remains false.
- [ ] AC-05 / KB-03: supplied, source-bound conflict fixtures exercise all four tiers, existing authority, equal-tier uncertainty and excluded memories; results explain conflicts without silent merging or automated semantic claims.
- [ ] AC-06 / KB-01,04: existing-topic updates preserve unrelated index prose; new topic needs a reason; candidate/denied/deferred proposals make no writes; exact prior consent works once, changed proposal/ownership/baseline fails, promotion cannot bypass consent.
- [ ] AC-07 / KB-05: create/correct/replace/supersede/delete/rename preserve source traceability and synchronize body/index/references; broken/unsupported relevant links fail before publication.
- [ ] AC-08 / KB-05: failure injection before/after every publication step, process interruption, recovery retry and cleanup verify old-or-committed API snapshots; no partial success or destructive rollback over external edits.
- [ ] AC-09 / KB-05: two-process same-file/index writers serialize; stale writer loses with conflict, independent edits cannot silently overwrite, API readers detect in-flight groups, read-only calls create no runtime files.
- [ ] AC-10 / KB-06: public interfaces have executable contract tests using current project/config/store APIs; tools read-only behavior and dynamically scanned archive evidence are verified without claiming caller wiring or live-host acceptance.

## Delivery boundary

Future implementation files: `src/fstar/knowledge.py`, `tests/test_knowledge.py`. At most one conditional resource edit: `resources/references/knowledge-format.md`, solely to clarify strict parser/reference/transaction conventions if implementation needs it; no second schema or template rewrite. All other modules and resources are read-only dependencies. This planning pass edits only this child's prd/design/implement and two JSONL manifests.

No unresolved product decision blocks this plan. Outstanding integration work and semantic/host evidence are listed in design/implement; completing this module alone does not complete parent acceptance.
