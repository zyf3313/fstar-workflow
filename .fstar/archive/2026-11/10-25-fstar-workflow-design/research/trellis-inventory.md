# Research: Trellis CLI Implementation Inventory (reuse-vs-rebuild)

- **Query**: Inventory the Trellis CLI's task layer, spec layer, context/session layer, and channel runtime; report what exists and what is absent, so we can decide reuse vs. rebuild for fstar-workflow.
- **Scope**: mixed (internal code + bundled docs), read-only
- **Date**: 2026-10-25
- **Version studied**: Trellis `0.6.17` (`package.json`), project `.trellis/.version` = `0.6.17`

## Sources

| Layer | Path |
|---|---|
| Installed CLI (JS) | `/Users/zhangyangfan/.nvm/versions/node/v24.14.0/lib/node_modules/@mindfoldhq/trellis/dist/` |
| Core lib (JS) | `.../node_modules/@mindfoldhq/trellis/node_modules/@mindfoldhq/trellis-core/dist/` |
| Project scripts (Python, generated from templates) | `/Users/zhangyangfan/workspace/projects/vibecoding/fstar-workflow/.trellis/scripts/` |
| Script templates (source of the above) | `.../trellis/dist/templates/trellis/scripts/` |
| Bundled skills/docs | `.../trellis/dist/templates/common/bundled-skills/`, `.../dist/templates/trellis/workflow.md` |
| Hooks | `.../trellis/dist/templates/shared-hooks/*.py` |

**Verified**: `.trellis/scripts/common/task_store.py` is byte-identical to the shipped template (`diff` = empty). The Python task layer is *project-local generated code*, not a library — it can be modified per-project, and `trellis update` will flag it as user-modified.

---

## 1. TASK LAYER

### 1.1 `task.json` — full field list and who writes each

Canonical order is defined twice: `dist/templates/trellis/scripts/common/types.py:21-51` (TypedDict) and `trellis-core/dist/task/schema.js:5-30` (`TASK_RECORD_FIELD_ORDER`). Both list **24 fields**. Creation default set is `common/task_store.py:528-553`.

| Field | Type | Written by | Notes |
|---|---|---|---|
| `id` | str | `create` (`task_store.py:529`); `rename` (`RENAME_IDENTITY_FIELDS`, `task_store.py:722`) | = slug, no date prefix |
| `name` | str | same as `id` | duplicate of `id` |
| `title` | str | `create` only (`:531`) | never updated by any command |
| `description` | str | `create` only (`:532`) | required non-empty at create (`:346-354`) |
| `status` | str | `create` → `planning` (`:533`); `task.py start` → `in_progress` (`task.py:112-114`); `archive` → `completed` (`task_store.py:1351`) | **only 3 writers** |
| `dev_type` | str\|null | `create` → `None` (`:534`) | **never written again; dead field** |
| `scope` | str\|null | `create` → `None` (`:535`); `set-scope` (`:1877`) | |
| `package` | str\|null | `create` (`:536`) | monorepo only |
| `priority` | str | `create` (`:537`, default `P2`) | no setter command; only `--priority` at create |
| `creator` | str | `create` (`:538`) | |
| `assignee` | str | `create` (`:539`) | no reassignment command |
| `createdAt` | str (`YYYY-MM-DD`) | `create` (`:540`) | date only, no time |
| `completedAt` | str\|null | `create` → `None` (`:541`); `archive` (`:1352`) | date only |
| `branch` | str\|null | `create` → `None`; `task.py start` fills if empty (`task.py:119-123`); `set-branch` (`:1789`) | |
| `base_branch` | str\|null | `create` (`:543`, resolved from `origin/HEAD` → current branch, or `--base-branch`); `set-base-branch` | |
| `worktree_path` | str\|null | `create` → `None` (`:544`) | **dead field** |
| `commit` | str\|null | `create` → `None` (`:545`) | **dead field** (no writer) |
| `pr_url` | str\|null | `create` → `None` (`:546`) | **dead field** (no writer) |
| `subtasks` | list[str] | `create` → `[]` (`:547`) | **legacy alias for `children`, never written by any command**; only rewritten by `rename` (`:876`) |
| `children` | list[str] | `create` → `[]`; `create --parent` (`:599-602`); `add-subtask` (`:1657-1661`); `remove-subtask` (`:1728-1732`); `archive` clears each child's `parent`, does NOT edit this list | |
| `parent` | str\|null | `create` → `None`; `create --parent` (`:614`); `add-subtask` (`:1664`); `remove-subtask` → `None` (`:1735`); `archive` of the parent sets each child's `parent` to `None` (`:1402`) | |
| `relatedFiles` | list[str] | `create` → `[]` (`:550`) | **dead field**; only the init bootstrap task sets it by hand |
| `notes` | str | `create` → `""` (`:551`) | **dead field**; no command writes it |
| `meta` | dict[str,str] | `create` via `--meta` (`:552`, parsed `:279-296`); `set-meta` (`:1920-1922`) | string values only, no nesting |

Extra field seen in the wild: `hooks` (per-task lifecycle hooks) is documented in `workflow.md:700-712` but **is not read by any code** — `run_task_hooks` reads only `.trellis/config.yaml` `hooks` (`common/config.py:262-292`). The `task.json.hooks` documented in workflow.md is documentation drift.

Notable: `workflow.md:73` advertises `task.py create-pr [name] [--dry-run]`. **`create-pr` does not exist** in `task.py` (no subparser, no handler; `grep` across scripts and templates finds only the workflow.md line and a copilot prompt). Same for the `worktree.yaml.txt` reference to `create_pr.py` — no such script ships.

### 1.2 Status enum — every writer, every reader

**The enum is implicit. There is no validation of status values anywhere.**

| Status | Written by | File:line |
|---|---|---|
| `planning` | `task.py create` | `common/task_store.py:533` |
| `in_progress` | `task.py start` (only if current status is exactly `planning`) | `task.py:112-114` |
| `completed` | `task.py archive` (unconditionally, whatever the prior status) | `common/task_store.py:1351` |

Readers/recognizers of additional values:
- `review` — appears **only** as a CLI help string (`task.py:569`) and in `trellis-core/dist/task/phase.js:15-16` (`inferTaskPhase`). **No code path ever writes `review`.** The help text advertises a status the system cannot produce.
- `done` — recognized as equivalent to `completed` in child-progress math (`common/tasks.py:120`, `common/session_context.py:750`) and in a "my tasks" filter (`session_context.py:683` `t.status != "done"`). **No writer.** This is a latent bug: the filter excludes `done` but the system writes `completed`, so completed tasks still show under "MY TASKS".
- `unknown` — fallback when the field is missing (`common/tasks.py:54`).

Readers that map status to behavior:
- `task.py:_display_status` (`task.py:356-371`): a `planning` parent with any non-`planning` child is *displayed* as `active`. Stored value untouched.
- `inject-workflow-state.py:192-195` (`shared-hooks`): empty/non-string status → `task_error` breadcrumb.
- `inject-workflow-state.py:203-231`: breadcrumb text is looked up by status tag in `workflow.md`. Unknown status → generic line. Custom statuses are supported *if* a lifecycle hook writes them and a `[workflow-state:X]` block exists (`workflow.md:685-699`).
- `session-start.py:461-466` special-cases `completed`.

### 1.3 Parent / child / subtask links

Three fields, only two are live:

- **`children`** (parent side, list of full task dir names) — authoritative. Written by `create --parent`, `add-subtask`, `remove-subtask`.
- **`parent`** (child side, single full dir name) — authoritative. Maintained bidirectionally by the same three commands.
- **`subtasks`** — **legacy spelling of `children`**, still present in old `task.json` files. Explicitly documented as legacy at `task_store.py:851` ("`subtasks` is the legacy spelling of `children`"). It is never written by any command, never read for logic, and only touched by `rename` so old files don't keep dangling names (`task_store.py:876`).

So: `parent` + `children` are the real bidirectional link; `subtasks` is a dead compatibility field.

Link semantics (worth knowing before designing a superset):
- A child may have **at most one parent**; `add-subtask` refuses a child that already has one (`task_store.py:1651-1654`).
- No cycle check anywhere. `add-subtask A B` and later `add-subtask B A` would create a loop.
- No dependency/ordering semantics. Docs are explicit: `task-system.md:49-57` — "not a dependency scheduler"; ordering must be written into the child's `prd.md`.
- On **archive of a parent**, every child's `parent` is set to `None` (`task_store.py:1402`), but the parent's `children` list is *kept* (deliberately — see next section). This means an archived parent's children become orphans pointing at nothing.
- On **archive of a child**, the parent's `children` list is *not* pruned (deliberate; changelog `dist/migrations/manifests/0.5.0-beta.18.json` documents the reversal: pruning made `[1/6 done]` become `[0/5 done]`).
- On **rename**, back-refs in other tasks' `parent` and `children`/`subtasks` are rewritten (`task_store.py:846-889`).

### 1.4 Parent progress computation

- `common/tasks.py:86-97` `get_all_statuses` → `{dir_name: status}` for **active tasks only** (`iter_active_tasks` skips `archive/`, `tasks.py:79`).
- `common/tasks.py:100-122` `children_progress`: counts a child as done if it is **missing from the active map** (i.e. archived) OR its status is `completed`/`done`. Returns `" [2/3 done]"`.
- **Consequence / architectural fact**: progress is derived from *absence from the active directory listing*, not from a recorded outcome. Archiving is what makes a child "done". A child archived without being finished still counts as done.
- `session_context.py:744-757` (record mode) computes `childrenDone` **differently** — it does *not* count missing children as done, only `completed`/`done`. So `task.py list` and `get_context.py --mode record` can disagree on the same parent's progress. (`session_context.py:750` vs `tasks.py:120`.)

### 1.5 `cmd_archive` — step by step, and what it does NOT do

`common/task_store.py:1257-1460`. Steps in order:

1. `resolve_task_dir` containment check (`:1269`); refuse if unresolvable.
2. `is_within_tasks_dir` — must be a *direct child* of `.trellis/tasks/`, so an already-archived task can't be re-archived (`:1292-1297`, impl `task_utils.py:32-52`).
3. Pre-check archive destination collision (`:1303-1312`) before any mutation.
4. Read `task.json`. If unreadable: **warn and continue** — archives anyway without status/children updates (`:1324-1335`).
5. `_validate_branch_metadata` (`:1177-1254`, called `:1339`):
   - warn if recorded branch no longer exists locally;
   - **refuse** if `branch == base_branch` (both non-empty);
   - **refuse** if `branch` empty while `base_branch` set and repo has a remote;
   - `--skip-branch-validation` bypasses both refusals.
6. Write `status = "completed"`, `completedAt = today` (`:1351-1352`).
7. For each child: set `parent = None` (`:1376-1426`). On write failure, roll back the links already removed (`_restore_child_links`, `:199-230`) and abort. **This is the only real integrity gate.**
8. `clear_task_from_sessions(task_dir)` — delete every `.trellis/.runtime/sessions/*.json` pointing at this task (`:1429-1430`).
9. `archive_task_complete` → `shutil.move` to `.trellis/tasks/archive/<YYYY-MM>/<dir>` (`task_utils.py:117-188`).
10. Unless `--no-commit`: `_auto_commit_archive` (`:1463-1567`) — narrow `git add`, `git rm --cached` for the moved source, commit `chore(task): archive <name>` with an explicit pathspec.
11. Print archive path to stdout; run `after_archive` hooks with the archived `task.json` (`:1457`).

**What `cmd_archive` does NOT do** (each verified by search):
- **No acceptance gate.** Nothing checks that `prd.md` acceptance criteria are met, or even that `prd.md` exists. (The create-time comments at `task_store.py:335,341` claim empty title/description "is refused at archive" — **no such pre-archive validator exists in this codebase**; `grep -rn "preflight"` finds only comments and the unrelated `ablation-store.js`.)
- **No status gate.** A task still in `planning` archives cleanly. It is force-written to `completed` first.
- **No `check` evidence.** `check.jsonl` is never consulted at archive.
- **No test/lint/CI gate.**
- **No user confirmation.** `finish-work.md` asks the *AI* to prompt the user for cleanup of *other* tasks, but `task.py archive` itself is unconditional.
- **No "archived-but-not-reminded" bookkeeping** (see §5).
- **Does not remove the child from the parent's `children` list** (deliberate).
- **Does not clear the parent link on itself** — an archived child keeps `parent: <name>` pointing at an active task that may later be archived.
- **Does not record `commit`/`pr_url`** on the task before archiving.

### 1.6 "Evidence" / "stale evidence"

**No concept of evidence as task state exists.** Searches:
- `grep -rni "evidence"` across project scripts → hits are only (a) `add_session.py` commit-subject resolution ("Commit evidence (R1)", `add_session.py:318-430`), (b) comments in `active_task.py:66,98` about platform-name verification, (c) `trellis mem`/skill prose.
- `grep -rniE "stale.evidence|evidence.stale|evidence_expired|invalidat"` across `dist/` and `trellis-core/dist/` → only UI-cache `invalidate` in the Pi/OMP extensions. Nothing task-related.
- `stale` in the task layer means exactly one thing: a **session pointer to a task directory that no longer exists** (`active_task.py:638-639`, surfaced as `active_task.stale` and `task.py current --json` `"stale": true` at `task.py:330`).
- "Evidence" in the *docs* is a planning discipline, not a data structure: `common/skills/brainstorm.md:11` "Non-Negotiable Evidence Rule" — repository evidence must be inspected before asking questions. It is prose guidance to the model, with no persistence.

**Conclusion: there is no `evidence` field, no evidence file, no freshness/staleness computation over acceptance artifacts, and no invalidation mechanism.**

---

## 2. SPEC LAYER

### 2.1 `.trellis/spec/` structure

Directory convention (docs `trellis-meta/.../spec-system.md:7-42`; actual project matches):
- Single-repo: `.trellis/spec/<layer>/index.md` + guideline `.md` files in the same dir. Project has `backend/`, `frontend/`, `guides/`.
- Monorepo: `.trellis/spec/<package>/<layer>/index.md`.
- `guides/` is cross-package and **always included**.

`index.md` is a *pointer* file: it holds a Pre-Development Checklist and a Quality Check, and links to the specific guideline files. There is **no machine-readable index** (no manifest, no frontmatter, no schema) — the index is prose Markdown with links.

`trellis init` generates scaffolded spec files with "To fill" placeholders (see `.trellis/spec/frontend/index.md:11-19`).

### 2.2 Indexing — `get_context.py --mode packages`

- Entry: `scripts/get_context.py` → `common/git_context.py:main()`.
- `--mode packages` → `packages_context.py:157-210` (text) / `:213-238` (JSON).
- Package discovery comes from `.trellis/config.yaml` `packages:` (`packages_context.py:91-122`, `config.py get_packages`). **For this project it prints `Single-repo project (no packages configured)` with `Spec layers: backend, frontend`.**
- Layer scan: `_scan_spec_layers` (`packages_context.py:30-41`) = subdirectory names of `spec/` (or `spec/<pkg>/`), excluding `guides`.
- Output lists each package, its path, its spec layers, and for each layer the path `.trellis/spec/<pkg>/<layer>/index.md` (`:195-198`).
- `spec_scope` (`config.yaml`) can restrict which packages are annotated "out of scope" (`_resolve_scope_set`, `packages_context.py:53-84`); `active_task` is a valid value, resolved from the active task's `package` field (`:44-50`).
- **This command only *lists* index paths. It does not read or rank spec content.**

Separately, `session-start.py:666-694` (`_collect_spec_index_paths`) enumerates index paths for the SessionStart compact state, honoring `spec_scope` (`:607-664`). It emits only a **count** into the context (`:752`: `Spec indexes: N available.`), not the paths.

### 2.3 How sub-agents learn which spec files to read

Two mechanisms, both driven by task-local manifests:

**A. `implement.jsonl` / `check.jsonl`** (the primary path)
- Format: one JSON object per line — `{"file": "<repo-relative path>", "reason": "<why>"}`. Optional `"type": "directory"` (`task_context.py:110-118`). Readers also accept legacy `"path"` key (`task_context.py:152`).
- Created **empty** by `task.py create` on sub-agent-capable platforms (`task_store.py:586-591`); absent on non-sub-agent platforms (Kilo/Antigravity/Devin/Codex-inline).
- Curated via `task.py add-context <task> implement|check <path> "<reason>"` (`task_context.py:63-121`). Duplicate detection is a naive substring check `f'"{path}"' in content` (`:106`).
- Validation `task.py validate` (`task_context.py:157-198`, `_validate_jsonl` `:270-409`):
  - hard errors: invalid JSON, non-object row, `_example` placeholder row, `file` not a string, file/dir not found, **0 curated entries**;
  - warnings (non-blocking): code-file extension outside exempt prefixes (`.trellis/spec/`, `docs/`, `docs-site/`, the task dir), file exceeding `context_injection.max_file_bytes`.
- Gate at start: `task.py start` refuses if either manifest exists with 0 curated entries, unless `--allow-empty-context` (`task.py:199-215`, `curated_entry_count` `task_context.py:128-154`).
- Injection: `shared-hooks/inject-subagent-context.py:483-507` (`get_agent_context`) reads `<task>/<agent_type>.jsonl`, materializes each entry into the sub-agent's prompt with the reason as a header. Then `get_implement_context` (`:534-589`) appends `prd.md` → `design.md` → `implement.md`; `get_check_context` (`:592-...`) uses `check.jsonl` + artifacts; `get_finish_context` (`:640`) reuses `check.jsonl` + `prd.md`.
- Byte budgets: `max_file_bytes` 32 KB, `max_artifact_bytes` 64 KB, `max_total_bytes` 128 KB, overridable in `config.yaml` (`inject-subagent-context.py:188-199`; documented `config.yaml:108-119`). Overflow degrades to index lines.

**B. Skill-driven reading** (inline / non-sub-agent platforms)
- No JSONL. The model is told to read `.trellis/spec/` directly per `workflow.md` and the `trellis-before-dev` / `trellis-check` skills (`common/skills/check.md:26-31`).

**Architectural fact**: spec selection is **curated by hand per task**. There is no automatic relevance matching from a changed file set to spec files. `check.md` instructs the agent to map changed packages → `get_context.py --mode packages` → read each layer's `index.md` → follow links — but that mapping is a prompt instruction, not code.

---

## 3. CONTEXT / SESSION LAYER

### 3.1 Active-task pointer

- Storage: `.trellis/.runtime/sessions/<context_key>.json`, one file per session/window (`active_task.py:253-254`, `:642-643`).
- File contents (observed in this project): `{"platform": "claude", "last_seen_at": "2026-10-25T11:22:38Z", "current_task": ".trellis/tasks/10-25-fstar-workflow-design", "current_run": null}`. Fields written by `_context_metadata` (`active_task.py:710-729`) + `current_task` (`:754`) + `current_run` default `None` (`:755`). `current_run` has **no writer anywhere else** — dead field.
- `set_active_task` (`:732-758`): canonicalize the task ref (must exist and be inside repo/.trellis), resolve context key, merge-write JSON atomically.
- `clear_active_task` (`:761-778`): **deletes** the whole session file. So `task.py finish` loses `platform`/`last_seen_at` too.
- `clear_task_from_sessions` (`:781-803`): used by archive — deletes every session file whose `current_task` matches.
- `repoint_task_in_sessions` (`:806-845`): used by rename — rewrites `current_task` in place (deliberately not a delete).

### 3.2 Platform session identity detection

`resolve_context_key` (`active_task.py:514-555`), strict precedence:
1. `TRELLIS_CONTEXT_ID` env var (explicit override).
2. **Hook payload** (`platform_input` dict): `session_id`/`sessionId`/`sessionID` → `conversation_id` → `transcript_path`; also looks inside nested `input`/`properties`/`event`/`hook_input` (`:38-41`, `:278-292`).
3. **Platform env vars** (`_ENV_SESSION_KEYS`, `:68-121`) — a hand-audited table with per-entry verification notes. e.g. `CLAUDE_CODE_SESSION_ID`, `CODEX_THREAD_ID`, `DSH_SESSION_ID`, `GEMINI_SESSION_ID`. Only *verified* names are listed; the comment at `:62-67` documents that 12 of 21 previously-declared names were invented and were removed.
4. **Shell ticket bridge** (`_lookup_shell_ticket_context_key`, `:484-511`): a `PreToolUse` hook writes `.trellis/.runtime/shell-tickets/<ts>-<digest>.json` (30 s TTL, `SHELL_TICKET_TTL_SECONDS=30` at `:35`) containing `context_key` + the pending `task.py` subcommand; `task.py start/current/finish` reads it back. Accepted only if fresh, cwd inside repo, and **exactly one** candidate matches — two concurrent windows both degrade (`:509-511`).
5. None → `None` (degraded mode).

Resulting key format: `<platform>_<sanitized-id>` or `<platform>_transcript_<sha256[:24]>` (`_context_key`, `:308-315`). Platform aliases canonicalize `zcode`→`claude`, `factory`→`droid` (`:154-160`).

### 3.3 Multiple sessions

- Pointers are per-context-key, so different AI windows can hold different active tasks without clobbering each other (`active_task.py:1-7`; docs `task-system.md:84`).
- `resolve_active_task` (`:646-678`) resolves **only** the current context key. There is no "global active task".
- Opt-in fallback `allow_single_session_fallback` (`:681-703`): if exactly **one** session file exists, use it. Returns `None` if 0 or ≥2 — explicitly refuses to pick across windows. Used by pull-based sub-agent callers; the Codex native subagent path deliberately disables it (`inject-subagent-context.py` `_handle_codex_subagent_start`).
- Degraded mode: if no context key, `task.py start` prints a warning and **still flips `planning → in_progress`** (`task.py:235-255`) — status advances but no pointer is written.

### 3.4 Lock / lease

**No lock or lease exists on the session pointer or on `task.json`.**
- `grep -rn "fcntl|msvcrt|flock|FileLock|lease"` in `.trellis/scripts` → no matches (only `_release_hook_process`, unrelated).
- Writes are *atomic* (temp-file + rename, `common/io.py write_json`, referenced `active_task.py:564-576`), so no torn file — but **no mutual exclusion**. Two concurrent `task.py start` on the same task in the same session can interleave last-writer-wins.
- Locks **do** exist in the channel runtime only: `trellis-core/dist/channel/internal/store/lock.js` — O_EXCL lockfile + pid-based stale-lock stealing. Scope: channel `events.jsonl` append and per-worker `spawnlock`. Nothing task-side.
- The only concurrency protection in the task layer is *retry*: `run_git_retry_index_lock` for the archive auto-commit (`common/git.py`, used `task_store.py:1529-1564`).

---

## 4. CHANNEL RUNTIME

Storage root: `~/.trellis/channels/<project-key>/<channel>/` (override `TRELLIS_CHANNEL_ROOT` / `TRELLIS_CHANNEL_PROJECT`; `dist/commands/channel/store/paths.js:6-44`). Global scope uses bucket `_global`.

Per-channel files: `events.jsonl`, `<channel>.lock`, `.seq` (sidecar), `<worker>.pid`, `<worker>.worker-pid`, `<worker>.spawnlock`, `<worker>.session-id`, `<worker>.thread-id`, `<worker>.inbox-cursor`, `<worker>.log`, `<worker>.reservation`, `<worker>.shutdown-reason` (`paths.js:86-105`, docs `multi-agent-channel.md:17-28`).

### 4.1 Event schema in `events.jsonl`

Canonical source: `trellis-core/dist/channel/internal/store/events.js:7-29` (set) and `events.d.ts:12-178` (types).

Every event: `{ seq: number, ts: ISO8601, kind: <enum>, by: string, idempotencyKey?, to?: string|string[], origin?: "cli"|"api"|"worker", meta?: object, ...kind-specific }` (`events.d.ts:12-22`).

**21 kinds** (`CHANNEL_EVENT_KINDS`, `events.js:7-29`):
`create`, `join`, `leave`, `message`, `thread`, `context`, `channel`, `spawned`, `killed`, `respawned`, `progress`, `done`, `error`, `waiting`, `awake`, `undeliverable`, `interrupt_requested`, `turn_started`, `turn_finished`, `interrupted`, `supervisor_warning`.

Kind-specific payloads (from `events.d.ts:23-176`):

| Kind | Key fields |
|---|---|
| `create` | `cwd?`, `task?`, `type` (`chat`\|`forum`), `description?`, `context?`, `labels?`, `ephemeral?` |
| `message` | `text?`, `to?` |
| `thread` | `action` (`opened`/`comment`/`status`/`labels`/`assignees`/`summary`/`processed`/`rename`), `thread`, `title?`, `status?`, `labels?`, `newThread?` |
| `context` | `target`, `action`, `context: [{type:"file",path}\|{type:"raw",text}]`, `thread?` |
| `channel` | `action: "title"`, `title?` |
| `spawned` | `as`, `provider?`, `pid?`, `agent?`, `files?`, `manifests?`, `inboxPolicy?` |
| `killed` | `reason?` (`explicit-kill`/`timeout`/`crash`/`idle-timeout`), `signal?`, `worker?`, `timeout_ms?`, `idle_timeout_ms?` |
| `done` | `duration_ms?`, `exit_code?`, `synthesized?` |
| `error` | `message?`, `provider?`, `synthesized?`, `exit_code?`, `exit_signal?` |
| `progress` | `detail?: object` |
| `undeliverable` | `targetWorker`, `messageSeq`, `reason` (`worker-terminal`\|`worker-unknown`) |
| `interrupt_requested` | `worker`, `turnId?`, `reason?` (`user`/`system`/`timeout`/`superseded`), `message?` |
| `turn_started` | `worker`, `inputSeq`, `turnId?` |
| `turn_finished` | `worker`, `inputSeq?`, `turnId?`, `outcome?` (`done`/`error`/`aborted`) |
| `interrupted` | `worker`, `turnId?`, `reason?`, `method` (`provider`/`stdin`/`signal`/`none`), `outcome` (`interrupted`/`queued`/`unsupported`/`no-active-turn`/`failed`), `message?` |
| `supervisor_warning` | `worker`, `reason: "approaching_timeout"`, `timeout_ms`, `remaining_ms` |

Write mechanics (`events.js:107-127`): under channel lock → truncate torn tail → idempotency-key dedupe (throws if same key reused for a different kind) → `seq = last + 1` from `.seq` sidecar → append one JSON line → rewrite sidecar. Reads tolerate corrupt lines by skipping (`events.js:159-175`).

There is **no schema version field** and no per-event schema registry — consumers pattern-match on `kind`.

### 4.2 What `interrupt` does mechanically

Two layers:

**CLI path** (`dist/commands/channel/interrupt.js:4-21`): reads message body (required), calls `requestInterrupt({channel, by: --as, workerId: --to, message, reason: "user", origin: "cli"})`, prints the appended event as one JSON line. `requestInterrupt` (`trellis-core/dist/channel/api/interrupt.js:8-26`) is **durable-intent-only**: it appends one `interrupt_requested` event and touches no process.

**Runtime path** (the actual behavior): the worker's **supervisor inbox watcher** is tailing `events.jsonl` for `kind ∈ {"message","interrupt_requested"}` (`dist/commands/channel/supervisor/inbox.js:22-27`). On `interrupt_requested` addressed to it (`ev.worker === workerName`, `:46-48`):
1. `turnTracker.abortCurrent()` → append `turn_finished` with `outcome: "aborted"` (`inbox.js:72-80`).
2. append `interrupted` with `method: "stdin"`, `outcome: interrupted|no-active-turn` (`inbox.js:82-91`).
3. write the replacement instruction to the worker's stdin via `adapter.encodeInterruptMessage(text, ctx)` (`inbox.js:103-106`) — for Claude this is a `control_request{subtype:"interrupt"}` line followed by the user message (`adapters/claude.js:165-177`); Codex maps `turn/aborted` to an `error` event (`adapters/codex.js:200-202`).

Key properties: it is **cooperative**, per-worker, and requires a live supervisor. If the worker is unknown or terminal in the durable registry, `interruptWorker` skips the runtime call (`api/interrupt.js:59-72`). `requestInterrupt` (what the CLI uses) does not even check liveness.

**Doc/code drift to note**: `bundled-skills/trellis-channel/references/workers.md:129-151` describes a `kind: "interrupt"` event and `wait --kind interrupt`. **No `"interrupt"` kind exists** — the set has `interrupt_requested` / `interrupted`. The authoritative `command-reference.md:146-180` contradicts `workers.md` and matches the code. A superset should not copy `workers.md`'s wording.

### 4.3 `worker_guard` idle timeout

Two enforcement points, same TTL policy (`channel/guard.js:1-13`):

**A. Spawn-time sweep + budget** (`enforceSpawnBudget`, `guard.js:427-448`):
1. `scanLiveWorkers` — walks every channel dir in the project bucket, projects the event log through `reduceWorkerRegistry`, keeps non-terminal workers whose **supervisor pid file exists and the pid is alive**, and (best-effort) verifies via `ps -o command=` that the pid really is `channel __supervisor <channel> <worker>` (`guard.js:183-268, 329-350`).
2. `cleanupExpiredIdleWorkers` — for each eligible worker write `<worker>.shutdown-reason` = `idle-timeout`, then `SIGTERM` the supervisor (`guard.js:382-421`).
3. Eligibility (`isIdleCleanupEligible`, `guard.js:359-373`): TTL > 0, `activity === "idle"`, `idleSince` present, not terminal, `now - idleSince >= TTL`. **Mid-turn workers are never swept.**
4. Re-scan, subtract killed, then allow spawn only if `maxLiveWorkers <= 0 || remaining < maxLiveWorkers`.

**B. Supervisor self-termination** (`scheduleSupervisorIdleTimer`, `channel/supervisor/idle.js:23-66`; wired `supervisor.js:337-343`):
- starts right after `spawned` is durable;
- `reset()` on `turn_finished` and `interrupted`; `pause()` on `turn_started` (via TurnTracker hooks `supervisor.js:170-174`);
- on fire → `shutdown.request("SIGTERM", "idle-timeout")` → the shutdown funnel emits the single terminal `killed` event (`supervisor/shutdown.js:62`);
- `idleTimeoutMs <= 0` → no-op handle (disabled).

Precedence: CLI flag > `TRELLIS_CHANNEL_WORKER_IDLE_TIMEOUT` / `TRELLIS_CHANNEL_MAX_LIVE_WORKERS` > `.trellis/config.yaml channel.worker_guard` > defaults `5m` / `6` (`guard.js:36-43`, `DEFAULT_IDLE_TTL_MS`/`DEFAULT_MAX_LIVE_WORKERS` at `:22-24`). The config parser is a hand-rolled line scanner, not YAML (`guard.js:104-154`).

`idleSince` is derived purely from durable events: set at `spawned` and on `turn_finished`/`interrupted`/non-terminal `done`/`error`; deleted at `turn_started` (`worker-state.js:113-174`). No pid-file-based heartbeat.

### 4.4 Is channel state coupled to task state?

**No — effectively zero coupling.**
- `grep` for `task.json`, `task_store`, `task.py`, `.trellis/tasks` across `dist/commands/channel/` and `trellis-core/dist/channel/` returns only: agent-card loading from `.trellis/agents/` (`agent-loader.js:31-56`), `config.yaml` reads for guard/trust, and `~/.trellis/channels` path comments. **No task read, no task write.**
- The only task-ish datum is `create --task <path>`, stored as an opaque string on the `create` event (`create.js:37`; `ChannelMetadata` projection). It is used for `channel list --project` substring filtering (`list.js:53`) and display (`list.js:189`), and for `messages` display (`messages.js:82`). It is never validated, never resolved, never used to gate anything.
- Docs confirm: `multi-agent-channel.md:62` — "**Task layer**: channel workers do not own task state. The supervising main session passes the active task path through the worker inbox; the worker resolves task artifacts from disk."
- Consequences: a worker can run on a task that is already archived; archiving a task does not kill its workers; `done`/`error` do not advance task status; there is no per-task worker budget.

---

## 5. GAPS — explicit absences

Each item below was searched for and **not found**.

### (a) User acceptance separate from check — ABSENT
- No `acceptance` state anywhere: `grep -rniE "acceptance_criteria|acceptanceCriteria|ac_met|criteria.*checked"` over `dist/` + `trellis-core/dist/` → **0 hits**.
- "Acceptance Criteria" exists **only as prose inside `prd.md`** — a template heading generated at `task_store.py:313-315` ("## Acceptance Criteria\n\n- [ ] TBD"), and as a checklist item for the *check* agent (`common/skills/check.md:69`: "Any file changed that the acceptance criteria do not mention?").
- The nearest thing to a human gate is a **prompt instruction**, not code: `workflow.md:461-466` requires "User confirms task should enter implementation" and `continue.md:30` says "only run `task.py start` after user confirms". Nothing verifies or records that confirmation.
- `check` is an AI sub-agent (`trellis-check`); `acceptance` (human sign-off) does not exist as a distinct state, artifact, or command.

### (b) Archived-but-not-reminded tracking — ABSENT
- `grep -rniE "unarchived|archive_pending|pending_archive|not_archived"` over `dist/` + core → only the `finish-work` prose "completed-but-unarchived tasks" (`commands/finish-work.md:3,17`) and a changelog line.
- There is no "not yet reminded" flag, no reminder ledger, no dismissal record. `finish-work.md:17` asks the AI to *discover* completed-but-unarchived tasks by reading `get_context.py --mode record` (active task list) each session — a re-derivation, not a tracked state.
- The one reminder mechanism that *is* persisted is unrelated to archiving: the update-check marker `.trellis/.runtime/update-check-<platform>_<key>.marker` (`session_context.py:421-457`), throttled once per session. This is the *pattern* (a marker file keyed by session identity) but it is applied only to "Trellis update available".
- The `[workflow-state:completed]` breadcrumb — the closest thing to an archive reminder — is documented as **DEAD** in `workflow.md:270-276` ("`cmd_archive` writes status='completed' in the same call that moves the task dir to archive/, so the active-task resolver loses the pointer and the hook never fires on archived tasks").
- `task.py list-archive` exists (`task.py:491-518`) but is a bare `ls` of month dirs; nothing calls it automatically.

### (c) Global cross-project personal memory — ABSENT (with two partial, non-memory surfaces)
- No global memory store. `grep -rniE "personal memory|cross-project|global memory"` → only channel `--scope global` docs and `_global` bucket references.
- All Trellis memory is **project-local**: `.trellis/workspace/<developer>/journal-N.md` + `index.md` (docs `workspace-memory.md`), `.trellis/spec/`, `.trellis/tasks/`. None of it is shared across repos.
- Partial surfaces that live outside the project, but are **not** personal memory:
  - `trellis mem` (`dist/commands/mem.js`, core `trellis-core/dist/mem/`) — a **read-only** indexer over the *AI platforms' own* session logs (`~/.claude/projects`, `~/.codex/sessions`, `~/.grok/sessions`, `~/.zcode/cli/db/db.sqlite`, OpenCode/Devin/Pi SQLite). Commands: `list`, `search`, `context`, `extract`, `projects`. `grep` for any write primitive (`writeFile|appendFile|mkdir|INSERT|UPDATE`) in `trellis-core/dist/mem/` → **0 hits**. It has `--global` to search across projects, but it writes nothing and is not a memory *store* — it's a search front-end over raw transcripts.
  - `~/.trellis/channels/_global/` — cross-project channel boards. Collaboration substrate, not memory.
- There is no "promote this lesson to my personal global rules" path. The documented promotion ladder is strictly project-scoped: task dir → workspace journal → `.trellis/spec/` (`workspace-memory.md:48-58`).

### Additional absences worth recording
- **No pre-archive validator of any kind** (acceptance, tests, check evidence). The `pre-archive`/`PR preflight` references are comments describing an upstream PR-automation component that is **not shipped in this package**.
- **No status validation / state machine.** Any string can be written to `status`; only 3 code paths write it, all hardcoded.
- **No `review` status writer** despite it being advertised in help text and understood by `inferTaskPhase`.
- **No worktree/PR automation** (`worktree_path`, `commit`, `pr_url` are dead fields; `create-pr` is documented but missing).
- **No lock/lease on tasks or sessions.**
- **No automatic spec↔change relevance matching.**
- **No dependency/ordering semantics between parent and children.**

---

## Caveats

- The Python scripts are **project-local generated files**. Editing them is legitimate (docs `task-system.md:120-130` explicitly lists them as customization points) but they will be reported as modified by `trellis update`.
- The JS CLI/core is installed under nvm and is not intended to be edited.
- Line numbers are from version `0.6.17` and will drift.
- `bundled-skills/trellis-channel/references/workers.md` contains at least one factually wrong statement (`kind: "interrupt"`); prefer `references/command-reference.md` and the code when the two disagree.
