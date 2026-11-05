# Knowledge provider design

## 1. Boundary and reuse

Own `src/fstar/knowledge.py` and `tests/test_knowledge.py`, Python 3.9 stdlib. Internal library only: no CLI registration, role, hook, ledger or search engine. Parent design §§3.9,3.11,4.1–4.5 governs; read it fully if injection truncates it.

Reuse public `config.parse_config(text, path)` for delimited frontmatter, `load_config(project_root, user_root)` for languages, `store.canonical_json/content_hash` for proposal digests, `atomic_write_json` for transaction metadata, `find_project_root`, `TaskStore.require_project/scan(archived=True)` and `models.DomainError`. Raw file hashes use SHA-256 over bytes. Private `content._frontmatter` loses types and private `tools._atomic_write` is not shared; `TaskStore.transaction` does not coordinate user+project knowledge. Keep byte staging and knowledge locks private here without copying tool schemas.

Existing `ProjectContext(project_summary, topics, authority_refs, knowledge_refs)` and `TopicReference(id,title,applies_to,read_when,path)` belong to init. Initialization renders Applies to/Read when/Authority links and preserves existing indexes (`INDEX_PRESERVED`). Do not call private renderers to overwrite indexes. Templates guide navigation, not fixed body structure.

## 2. Public Python API

Use explicit Path roots and immutable data objects or validated dictionaries defined in knowledge.py. Proposed signatures are deliverables, not claims of existing integration.

| API | Contract |
|---|---|
| `parse_knowledge(text, *, path, expected_type=None)` | Pure strict decoding → KnowledgeDocument(metadata,body,path,digest); no filtering or defaulting. |
| `load_catalog(*, user_root, project_root=None)` | Read-only snapshot → Catalog(documents,indexes,authority_refs,topic_refs,diagnostics,snapshot_hash). |
| `load_context(catalog, *, selection, max_bytes=None)` | ReadSelection → ContextBundle(full_documents,excluded,required_unloaded,conflicts_pending,complete,snapshot_hash) with language policy and ordered path/hash/role. |
| `resolve_context(bundle, *, assessment)` | Pure precedence over source-bound SemanticAssessment → Resolution(ordered_sources,conflicts,unresolved,complete). |
| `prepare_change(catalog, *, edits, intent, assessment)` | Exact bytes/deletions and governance intent → KnowledgeProposal; validates without writing. |
| `apply_change(proposal, confirmation, *, user_root, project_root=None)` | Locked authorization and baseline check, stage/commit → receipt with proposal hash, changed paths, before/after hashes, recovery outcome. |
| `recover_changes(*, user_root, project_root=None)` | Explicit maintenance under the same locks → operation outcomes or recovery conflict; never a side effect of read-only calls. |

Catalog keeps private raw snapshots for byte-preserving edits and inactive metadata for diagnostics, while exported guidance excludes inactive bodies. Low-level parse may return inactive bodies for diagnosis; injection must use context/resolve. Invalid schema or unreadable required sources make the catalog unusable for effective resolution, never silently absent.

ReadSelection covers selected topic IDs, explicit dependency and global-constraint paths, applicability include/exclude/unknown with reasons, and snapshot hash. Full overview/index always precedes selected bodies. SemanticAssessment carries reviewed source hashes, applicability, incompatible source/section pairs with rationale, semantic coverage and language review status. Missing review means conflicts_pending/complete=false. Scope strings and APPLIES/NOT prose are not regex semantics.

KnowledgeProposal: operation ID, owner roots, action, exact edits (relative path, before hash/absence, after UTF-8 bytes/deletion), sources, existing-topic choice or new-topic reason, language, authorization scope, index/reference inventory, assessment hash and proposal hash. Digest covers all executable fields. Confirmation requires approved disposition, source type command/conversation/review, user source reference/quote/time, matching proposal hash and ownership/scope. Review sources must link user confirmation. This checks consistency, not authenticity against same-permission forgery.

DomainError codes: knowledge_invalid_schema/read_error/unsafe_path/context_incomplete/reference_error/confirmation_required/confirmation_mismatch/write_conflict/lock_timeout/recovery_required/recovery_conflict, with path/field/line or operation and expected/actual hashes. Partial work never gets a success envelope.

## 3. Schema and write ownership

Read UTF-8 frontmatter bounded by standalone `---` lines at the start; normalize line endings only for parsing and hash original bytes. Feed the enclosed mapping into parse_config. Require string values and approved schema/type/status enums. Reject duplicates, containers, bool/number/null values, missing delimiters/fields, unknown keys and type-inapplicable strength/kind/trust. Allowed keys are schema/type/status plus rule strength or memory kind/trust. Empty body is invalid; no new required metadata. Validate inactive documents too, then filter to active rules/specs and active confirmed memories.

User rules require type rule, memory type memory, project specs type spec. Existing authority outside specs remains ordinary source text; never add/require frontmatter. Context/references are ordinary project-language Markdown. They do not become constraints unless an explicit reviewed authority/topic mapping identifies a project specification.

Language policy uses load_config: rules/memory=en, specs=language.specs (default en), context/references=language.artifacts. Tests prove policy selection; semantic review checks prose while preserving identifiers and quoted sources. No ASCII or regex language detector claims correctness.

Default write roots: user rules/memory/index and project specs/knowledge context/references/index. Existing authoritative project docs are read-only unless exact in-project files and edits are explicitly authorized in the proposal; never infer permission from a link. No writes to config/tools/task/archive or arbitrary outside roots. Reject traversal, NUL, ambiguous owner aliases, symlink components and nonregular targets; bind canonical roots to consent. Project writes require initialized schema 1; absent-store reads initialize nothing.

## 4. Complete reading and conflict resolution

Read complete user/project indexes, project overview, global constraints and existing authority first. Discover category files to diagnose unindexed or invalid data; omission from navigation cannot silently disable an enforced rule. Initially read all active enforced rule bodies until their scope and exclusions are reviewed.

Support current generated topic fields and Markdown inline/reference links. Index path semantics follow project.py: project authority links are project-root relative; user index links are user-root relative; body links are relative to their file. Validate local fragments via explicit or documented Markdown heading anchors; ambiguous ones need explicit anchors. Never rewrite fenced examples, code literals or external links.

Customized indexes remain full readable sources. Unsupported structure returns unresolved navigation and requires explicit TopicReference/DocumentReference selections; never guess and mark complete. Traverse caller-identified upstream/downstream/shared contracts and local normative links in selected bodies with cycle detection. Unknown applicability broadens to candidate topics; new dependencies trigger supplemental reads. Budgets defer whole bodies with path/hash/reason; no slicing or summary substitution. Missing or deferred required bodies keep complete=false.

Learn/check review full bodies and supply applicability and conflicting sections. Python verifies freshness and resolves reported conflicts: enforced rule tier 0 > explicit project spec tier 1 > default rule tier 2 > confirmed memory tier 3. Within project tier, existing authority wins over derived guidance. Equal-tier ambiguity keeps both sources unresolved; path order is not a policy winner. Conflict outputs name source sections, winner/unresolved, precedence reason and reviewer rationale. Deterministic sorting does not discover semantic conflicts. Host constraints and current explicit user instructions remain caller-owned priorities.

## 5. Proposal and reference closure

Learn supplies classification, topic review, sources and exact edits; prepare_change neither asks questions nor persists candidates. Init owns initial project discovery/taxonomy through ProjectContext; later authorized enrichment uses the same edit contract.

Read all affected indexes/topics/references/authority before proposing. Prefer existing topics; require why no current topic fits for a new one. Include literal index edits preserving unrelated prose. User navigation includes topic/path and rule strength or memory kind; project navigation includes topic ID/title/Applies to/Read when/authority, knowledge entries and existing-authority priority. Do not regenerate an existing index wholesale.

Inventory reverse references across managed knowledge/index files plus explicitly supplied in-project authoritative or reference documents. Record every scanned file hash and inventory membership, so edits, additions and removals require re-preparation. Validate local links against staged final files. Rename/delete includes inbound updates; supersede/replace removes stale effective navigation or points to the successor while preserving source provenance. Deletion needs explicit consent; storage is not append-only. Unsupported relevant syntax or incomplete inventory blocks closure and returns files for review. Do not claim arbitrary source-file or external-system link rewriting.

Semantic duplicate/conflict/language review carries source hashes; scripts check structural closure and freshness. Any change to content, metadata, paths, ownership, scope or references changes the digest and needs matching authorization. Clear prior authorization can be represented directly for the exact proposal, without a second question. Promotion requires explicit resulting rule/strength/scope/owner consent.

## 6. Publication, locking and recovery

Use per-user lock under `<user_root>/runtime/knowledge/` and per-project lock under `<project>/.fstar/runtime/knowledge/`, so callers with different user roots still serialize on project data. Acquire all affected owner locks in canonical order with a bounded monotonic timeout. Root-wide locking also serializes shared indexes. POSIX flock matches core; unsupported platforms error explicitly. Read APIs never create lock files.

1. Under exclusive locks check pending operations, exact confirmation, edit and reference-inventory baselines and safe paths; stale proposals fail after waiting. A repeat with the exact final snapshot may return already-applied; never replay old bytes over later changes.
2. Stage before/after bytes, absence markers, modes and operation-created directories in owner runtime. Persist a coordinator plus participant pointers for multi-owner operations, containing validated canonical roots, participants, hashes and operation ID. This short-lived recovery metadata is not a knowledge/history/candidate ledger.
3. Flush/fsync stages and participant records before publication. Use same-filesystem temporary files beside targets, per-file os.replace, authorized deletions and directory fsync. Hold locks through post-write content/index/reference validation.
4. Persist a durable committed coordinator marker only after every final file validates and is durable. Only then report saved. Retryable cleanup removes backups/pointers; keep metadata only while recovery or cleanup needs it. No permanent receipt ledger; callers may keep the returned receipt in existing task evidence.
5. Failure before commit restores before-images in reverse order, removing new files and only empty operation-created directories. Process death leaves pending metadata. Explicit recover_changes reacquires all participant locks, rolls back uncommitted operations or validates/finishes committed cleanup, idempotently.
6. Restore only when bytes equal the recorded before/after value (including absence). Any third value is an external edit: return recovery_conflict, retain backups, never overwrite it. Missing/corrupt participants or coordinator block usable snapshots pending explicit repair. Readers return recovery_required without writing.

Cooperating readers acquire shared locks on existing lock files, inspect participant records and read complete snapshots. When no lock exists, read without creating one, then recheck lock appearance and input hashes; a writer appearing requires retry under its lock. Bound retries and return conflict rather than mixed bytes. Multi-owner reads use the same lock order; pending recovery blocks injection from affected roots. Pure parse and resolve do no filesystem IO.

Guarantee: serialized cooperating writers, complete before/after snapshots through the knowledge API, and durable recovery. Individual replacements are atomic; simultaneous multi-file filesystem visibility is not promised. External editors, readers and search indexes do not honor these locks and may see intermediate state; consumers recheck hashes. Same-permission manipulation is outside the security guarantee.

## 7. Consumer ownership and remaining integration

| Consumer | API/handoff | Remaining owner work |
|---|---|---|
| init/project-layout | ProjectContext topics/authority; prepare/apply for enrichment | Whole-project taxonomy/conversation, preserve existing indexes. No project.py edit here. |
| learn/workflow-content | prepare/apply/recover | Candidate timing, exact user source, semantic review, topic reasons, conflict display and skill wiring. |
| runtime-hooks/dispatch | catalog/context/resolve | Full injection, version hashes, omissions/recovery and supplemental reads; existing manifest reading does not prove new API integration. |
| tools | Read-only source paths/content/hashes | Binding, availability, provenance and retrieval freshness; no knowledge writes here. |
| installer/doctor | Shared parse/catalog diagnostics; explicit recovery preflight | Resource selection, read-only diagnosis, authorized migration/content preservation; no second schema authority. |
| core/recall | Existing TaskStore.scan(archived=True)/task list | Dynamic task/plan/commit/acceptance projection; no ledger or restored archived task. |

Only conditional resource edit: `resources/references/knowledge-format.md`, to clarify strict parsing/link/transaction conventions if necessary, without new required fields or policy. No other schema or template edit planned. Provider fixture tests establish compatible contracts, not completed caller wiring, installation, live-host behavior or parent acceptance. Caller integration and two-host e2e remain explicit dependencies.
