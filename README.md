# fstar-workflow

[![npm version](https://img.shields.io/npm/v/fstar-workflow.svg)](https://www.npmjs.com/package/fstar-workflow)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![GitHub](https://img.shields.io/badge/GitHub-zyf3313%2Ffstar--workflow-black)](https://github.com/zyf3313/fstar-workflow)

A cross-project workflow system for AI coding agents. It keeps task state,
evidence, and routing **on disk instead of in the conversation**, so work
survives context compaction, session restarts, and machine changes.

Python 3.9+ standard library only, with a thin Node wrapper for host
integration. No third-party runtime dependencies.

```
Session starts ──► hook injects routing + project index (from disk, not memory)
      │
      ▼
Plan ──► Start ──► Implement ⇄ Check ──► Fresh evidence ──► Awaiting acceptance ──► User acceptance ──► Archive
  │                                                          │        ▲
  │                     user reports a problem ──────────────┘        │ (rework: back to planning)
  └── every step recorded in task.json + event log ◄─────────────────┘
```

## Requirements

- Node.js 18 or newer (launcher only)
- Python 3.9 or newer on `PATH` (the kernel)
- Optional hosts: Claude Code (verified), Codex CLI (limited, see below)

## Install

**From npm (recommended):**

```bash
npm install -g fstar-workflow@latest
```

Package page: https://www.npmjs.com/package/fstar-workflow

**From GitHub (latest commit, bypassing the registry):**

```bash
npm install -g github:zyf3313/fstar-workflow
```

**From a local build:**

```bash
git clone https://github.com/zyf3313/fstar-workflow && cd fstar-workflow
npm pack
npm install -g <the-produced-tarball>.tgz
```

Verify:

```bash
fstar version    # CLI, resource, and data schema versions
fstar doctor     # read-only install and host health report
```

## Quick start

```bash
cd your-project
fstar init                       # create .fstar/ and a missing ~/.fstar; create/backfill the project index from supplied context
fstar install --host claude      # wire hooks + skills + agents into <project>/.claude
fstar task create "My feature" --name my-feature
fstar start my-feature           # planning → in_progress
# ... work with your agent; fstar-managed skills drive the flow ...
# ... after a fresh final check: in_progress → awaiting_acceptance ...
fstar accept my-feature          # user acceptance: awaiting_acceptance → completed
fstar archive my-feature         # archive to .fstar/archive/
```

Host root priority: `--host-root claude=PATH` > `--user-level` (`~/.claude`) >
the current fstar project's `.claude`. Outside a fstar project, a bare
`fstar install` refuses to guess and points at `--user-level` or `fstar init`.
`--dry-run` prints the full plan without writing anything; an interactive
terminal is asked to confirm the host roots before any write. `update` and
`uninstall` resolve roots the same way and refuse with
`uninstall_host_root_mismatch` when the recorded install targets other roots
than the resolved ones — pass `--user-level` to select it.

## The workflow, stage by stage

### 1. Plan (`task create` → planning)

`fstar task create <title> --name <slug>` creates a task under `.fstar/tasks/`
with a 26-field `task.json`: phase (`planning`), priority (P0–P3), parent/child
links, and an append-only event log. Requirements live in the task directory
as `prd.md` (requirements + acceptance criteria), plus `design.md` and
`implement.md` for complex work. Nothing is implemented before the artifacts
exist — planning is persisted, never held in a chat window.

Related commands: `task list` (browse), `task current`, `state show`
(inspect status before acting).

### 2. Start (`start`)

`fstar start <task>` moves the task to `in_progress` and records the branch.
This is the gate that authorizes implementation — writing product code before
`start` is a workflow violation, not a style preference.

### 3. Implement (`dispatch implement`)

A coordinator hands **bounded scope** to implement and check roles. Every
dispatch carries per-input path, hash, and version, so the harvest step can
verify what the worker actually read. Sub-agents only touch their authorized
scope; the main session integrates and inspects consequential changes.

### 4. Check (`dispatch check`)

Checks are **independent** — a different agent than the one that implemented,
re-running the validation commands and reporting facts (exit codes, counts,
failures). Skipped environment gates and fresh-vs-reused evidence are tracked
separately, so "tests passed" always names its exact code state.

### 5. Evidence & acceptance (`review`, `evidence`, `acceptance`)

Evidence records are content-addressed: when the artifacts they validated
change, the evidence goes stale and completion is blocked. After a fresh
final check is recorded, the task moves to the `awaiting_acceptance` phase
(`fstar accept <task> --awaiting`, a coordinator action — the transition is
explicit, never automatic at check-harvest time) and `completedAt` stays
empty. Completion requires a task in `awaiting_acceptance` **plus explicit
user acceptance** (`fstar accept`) — a command succeeding is not acceptance.
If the user reports a problem during `awaiting_acceptance`,
`fstar accept <task> --rework --reason ...` returns the task to `planning`
and stales the evidence; the normal start → check cycle re-applies.
`fstar evidence invalidate --file PATH`
expires evidence on demand; `fstar acceptance status` shows what's missing.

### 6. Archive (`archive`, `drop`)

`fstar archive <task>` moves the accepted tree to `.fstar/archive/YYYY-MM/`,
keeping the event log intact. Tasks that won't proceed use `fstar drop
--reason ... --disposition keep|discard|knowledge` — knowledge-worthy lessons
can be routed into `.fstar/knowledge/` instead of vanishing.

### 7. Resume & interrupts (`continue`, `interrupt`, `doc-edit`)

`fstar continue` resumes an interrupted task from verified on-disk state
(takeover / replan / reopen / unblock). **Replan** stales all evidence,
returns the task to `planning`, and records the pre-replan documents plus
the baseline git commit — the session context then surfaces those documents
for re-clarification, and dispatch is refused until `plan.md` has actually
been rewritten (`stale_plan_dispatch`), so a pre-replan plan can never
silently flow to implementation. **Reopen** (user-only, unarchived
completed tasks) returns the task to `planning` and stales the final-check
evidence so re-acceptance requires a fresh independent check (deliveries
stay valid); archived tasks are immutable — follow-up only, never reopen.
A task whose fresh final check went stale in `awaiting_acceptance` goes
back to `in_progress` for a re-check via `fstar accept <task> --recheck`.
Long-running dispatches can
be steered with `fstar interrupt` (change propagation, cancel, checkpoint
stop). Concurrent document edits go through `fstar doc-edit`, which rejects
stale baselines instead of silently overwriting.

Requirement clarification runs as a design-tree interview: questions whose
prerequisites are settled are asked in numbered rounds, each with a
recommended answer, and the requirements only hand off to planning when the
frontier is empty — an unanswered question is an unresolved requirement,
not optional context.

### Extensions (opt-in, never default-on)

`fstar extension enable <id> [--scope full|custom]` negotiates extra
capability packages — `planning-review`, `persistent-task`, `multi-agent`,
`project-governance`. Refusing one leaves the minimal loop
intact; nothing is assumed on for you.

### Prompt-context breadcrumbs (per user prompt)

In an initialized fstar project, a `UserPromptSubmit` hook
(`prompt-context`, 15 s timeout) injects exactly one short state reminder
per user prompt, selected from `resources/runtime/prompt-states.md` by the
current task state — e.g. with no active task the agent is reminded to
state a one-line workflow decision (`large | small | discussion |
read-only`) before substantive work; `large` must create or reuse a
persistent task and run the full loop. The hook never creates a task
itself — classification is the agent's job. If the state file or the
needed tag is missing, the hook degrades to a single fixed line instead
of staying silent. Outside an initialized project the hook emits nothing.

`fstar init` clarification: the `fstar-init` **skill** (not the bare CLI)
explores the project and writes the spec content — the CLI's `init`
command creates the project/user data roots and creates/backfills the
project index from supplied context.

### Learning loop (corrections, rejections, rule-delegated acceptance)

User corrections mid-task are captured as append-only `correction` events
(`fstar correction record/list`) carrying the user's exact words — pure
capture, no knowledge write, no behavior change. Rejected proposals are
offered a slot in the rejected ledger
(`.fstar/knowledge/references/rejected.md`, written through the authorized
learn pipeline); its index line is injected at session start so agents stop
re-proposing what you already refused. Requirement clarification checks that
ledger and your rules before asking, so settled questions are not re-asked.
Acceptance stays user-only, with one traceable exemption: an active user rule
may delegate acceptance for a class of work — `fstar accept --rule FILE`
records the citation (`accepted_via_rule` with the rule's reference and your
exact quote) in the event log; priority or risk level alone never waives
acceptance. Procedural knowledge ("how to do X") lives in
`.fstar/knowledge/references/procedures/` and is read live through dispatch
`read_context` — never exported into host skills, so the knowledge base stays
the single authority.

## Where the project data lives

`fstar init --storage MODE` chooses where the project's data root lives.
Every mode keeps the same task/spec/archive structure and the same commands;
only the location and the ignore rule change.

| Mode | Data root | Ignore rule | Use when |
|---|---|---|---|
| `project-shared` (default) | `<repo>/.fstar/` | none — the data root is committed with the repository | the team should share tasks and specs |
| `project-local` | `<repo>/.fstar/` | `.git/info/exclude` (machine-local; the shared `.gitignore` is never rewritten) | you want the data in the repository but not uploaded |
| `user-directory` | `~/.fstar/projects/<uuid>-<name>/` | the repo holds only a small pointer file (`.fstar-pointer.json`), itself machine-local | you do not want fstar data inside the repository at all |

```bash
fstar init --storage project-local     # data stays in the repo, untracked
fstar init --storage user-directory    # data lives under the user root
fstar install --storage user-directory # initialize the mode, then install
```

`install --storage` initializes an uninitialized project in the requested
mode before installing; an already-initialized project keeps its mode — data
is never moved silently (`storage_mode_mismatch`).

Identity is a stable project UUID plus a readable name. Two projects with the
same name never collide: each gets its own `projects/<uuid>-<name>/` folder.
Nothing is ever merged by name or by remote URL.

In `user-directory` mode the project folder carries a pointer file that records
where its data lives. If the repository is moved, the pointer no longer
matches and every command stops with `project_moved_needs_rebind` instead of
guessing. Rebinding is always explicit:

```bash
fstar rebind /new/path/to/project     # rebind the project to its new location
```

`fstar doctor` reports the storage mode and the resolved data root for every
mode, and additionally checks that a user-directory project folder and its
registered UUID agree.

## Cross-project tasks (master + child in different repositories)

A master task in one project can own child tasks that live in other
initialized fstar projects. Each side records its own copy of the link in
`task.json` `meta.cross_project_links`
(`{direction: child|parent, project_id, task_id, path_hint}`); the existing
26-field structure and same-repo `children` semantics are untouched. The
`path_hint` is a location hint only — authoritative resolution goes through
the project registry / recorded project identity.

```bash
# from the master project (master task "root" must exist and hold the link;
# the TARGET child task must be in_progress — dispatch registers on it)
fstar cross create-child root --target /path/to/other-repo \
    --name child-a --title "Deliver the other repo's part"
fstar cross link root --target /path/to/other-repo --target-task existing-task
fstar cross links root          # list links with live target task status
fstar cross dispatch root --target /path/to/other-repo --target-task child-a \
    --role implement --plan-item P-1 --allowed-path src/app.py
```

`--target` accepts an existing project path or a registered user-directory
project id. Pre-dispatch checks (by design):

- **Target not initialized** (no fstar data root): the operation is refused
  with `target_not_initialized` and you are directed to the init flow.
- **Target has no real specs yet** (missing/empty/placeholder): the dispatch
  continues and the fact is recorded on the child task
  (`cross_project_spec_note`) — a placeholder never permanently blocks.
- **Spec loading**: the dispatched worker's `read_context` is built from the
  TARGET project's own specs; the master project's specs are never
  substituted.
- **Unavailable target path** (moved/deleted): link status reports it and new
  dispatches are blocked with the recorded path as reason.

Failure handling: duplicate links and cross-project parent-child cycles are
refused; cross-project writes take the master project lock first and then
any further project locks in sorted order, so a failed operation leaves no
partial records and is retriable as a whole.

## Branch binding & task locate (QA)

`fstar start` records the branch and worktree a task actually runs on
(detached HEAD is recorded as detached, never fabricated). When QA finds a
problem on a branch, `fstar task locate` finds the task it belongs to:

```bash
fstar task locate --branch feat/some-branch   # unique candidate: found
fstar task locate --branch feat/shared --worktree /path/to/wt  # disambiguate
fstar task locate my-task                     # explicit ref beats everything
```

Lookup order: explicit task ref > a valid compatible session pointer > a
unique project/worktree/branch candidate. Same-named branches in sibling
worktrees are distinguished by the worktree path. Several matches —
including completed and archived ones, which stay searchable for QA — are
listed with identifiable info for a natural-language choice; nothing is
auto-selected and no branch is auto-switched. Archived hits can only be
linked to a follow-up task, never reopened or mutated.

## Unified cross-project acceptance

When a master task carries cross-project child links, one explicit user
confirmation can complete the master and every listed child together:

```bash
# every linked child must be in awaiting_acceptance with a fresh final
# check, and the master must be in awaiting_acceptance itself
fstar accept root --unified --confirm-user --invocation <this confirmation>
```

Any stale, unavailable, or not-yet-awaiting child blocks the whole
acceptance with the reason (`unified_child_not_ready`) and nothing is
written — partial failure never fakes full success. Each child's
acceptance event records its source as the master's unified confirmation
reference, and the confirmation binds the current version of every task,
so an old acceptance can never be reused for a new delivery.

## Natural-language UX

All fstar commands are agent-internal. In a conversation the agent reports
in natural language — what was done, what the verification showed, and
what confirmation is awaited — and runs the commands itself, recording the
actual conversation as the confirmation source when one is required. You
never see (or need to run) a command like `fstar accept <task>
--confirm-user` as a reply; the CLI flags above exist for scripted and
agent-internal use. This is presentation only: confirmation stays
explicit, one-time, user-initiated, and traceable in the event log.

## What lands in your project

```
.fstar/            tasks, specs, archive, knowledge — the project's data root
                   init writes exploration-driven spec skeletons: a topic
                   index plus per-dimension detail files (directory
                   structure, error handling, quality/logging guidelines;
                   UI topics get component/state/type-safety) — user-authored
                   specs are never overwritten
~/.claude/         hooks (settings.json), 11 skills, 4 agent cards   [global by default]
~/.fstar/          user-level resource cache (shared, versioned) — never host config
```

Resources are installed and updated **globally by default** (since 0.7.0):
`fstar install` and `fstar update` target the user-level `~/.claude` skills,
agents, and hooks, so one global update serves every project. Your project
keeps only its own data (tasks, specs, identity). An explicit
`--host-root claude=PATH` still selects a specific project-level host root
when you want one.

Projects created before the global default may still carry their own
per-project copies or a `resources.version` pin. Nothing migrates silently:

- On session start, fstar compares the project's legacy resources against the
  global target (read-only) and points out the per-project copies/pin that
  still shadow the global delivery. The comparison writes nothing — not to the
  project, not to the tasks, not to the runtime.
- `fstar resource-inspect` prints the same comparison on demand.
- Showing the question is an explicit operation:
  `fstar resource-remind --session ID` decides and records whether the
  migration question may be shown in this session, so the same question is
  not asked twice in one session (a clear/compact keeps the same session).
  A record that cannot be written is reported, never claimed.
  The comparison, reminder, and migration commands accept
  `--host-root claude=PATH` when the host entry does not live in the global
  default location.
- Migration runs only with an explicit approval file:
  `fstar resource-migrate --confirmation FILE` (the file records the user's
  conversation approval). It moves only copies the installer provably owns
  and that were not modified since install (backed up first under
  `~/.fstar/install-backups/`), drops the project pin while preserving
  identity/other config keys, and reports every kept or conflicting file.
  Re-running on a migrated project is a no-op.
- `fstar resource-defer` records the explicit deferral (per project and target
  version; a new global version makes the project eligible again).

Resource migration never touches data schemas: `fstar migrate` remains the
only schema-migration path (schema 1 → 1 is a no-op; anything else is
`unsupported`).

`fstar uninstall` removes only what the installer itself owns (verified by
content hashes recorded at install time); your specs, tasks, and any file you
touched are never removed. Because the global entry is the default target,
`fstar uninstall` acts on the global `~/.claude` entry; when the recorded
install lives in another host root the command refuses
(`uninstall_host_root_mismatch`) and asks for `--host-root claude=PATH` (or
`--user-level`) instead of touching the wrong root.

## Host support

| Host | Hooks | Skills | Agents |
|---|---|---|---|
| Claude Code | four existing events verified live; the newer `UserPromptSubmit` prompt-context hook has unit/CLI verification only — no live host firing observed yet | verified live | verified live |
| Codex CLI | four hook events verified live (SessionStart / SubagentStart / SubagentStop / PostToolUse fired with exit code 0 on 2026-11-05); the newer `userPromptSubmit` prompt-context registration is unverified live (event/schema casing not observed in the Codex schema); installer still requires manual trust approval in the TUI before any `.codex/hooks.json` is written, and remains read-only when run headless | not adapted | not adapted |

Codex trust is a deliberate gap, not a bug: the host requires a human to
approve each hook the first time, and no installer can consent on your behalf.
To collect live evidence without changing your real configuration, run the
read-only adapter plan and copy the four commands into a disposable project
hook configuration, then approve the trust prompt in the Codex TUI:

```bash
fstar --json hook plan --host codex
```

If any event does not fire, keep the event payload and exit status as evidence
and file it against the `to_verify` item in the plan. Do not commit the
project hook file. `fstar install --host codex` remains read-only by design,
while `--host claude` continues to use its independently verified `.claude`
adapter; the two host roots never share configuration.

## Command reference

Run `fstar <command> --help` for flags. The commands group by purpose:

- **Task lifecycle** — `task create|list|current|locate`, `start`, `accept`,
  `archive`, `drop`, `continue`, `state show`
- **Verification** — `review record|list`, `evidence invalidate`,
  `acceptance status`
- **Extensions** — `extension list|enable|disable`
- **Project** — `init`, `rebind`
- **Cross-project** — `cross create-child|link|links|dispatch`
- **Install maintenance** — `install`, `update`, `uninstall`, `doctor`,
  `migrate`, `version`, `resource-inspect`, `resource-remind`,
  `resource-migrate`, `resource-defer`
- **Optional Magpie integration** — `scripts/integrate-magpie.cjs` (see
  "Optional Magpie skills integration" below)
- **Agent-side** (invoked by agents, rarely by hand) — `dispatch ...`,
  `interrupt`, `doc-edit`, `hook ...`

Global flags: `--project PATH`, `--session ID`, `--user-data-root`,
`--runtime-root`, `--json`, `--actor`, `--actor-role`.

## Updating

```bash
npm update -g fstar-workflow     # or: npm install -g fstar-workflow@latest
fstar update                     # refresh the shared global resources once, for all projects
fstar doctor                     # confirm everything is healthy
```

A running session may have the previous resource version cached; restart the
session (or clear/compact it) for the new version to take effect.

## Optional Magpie skills integration

If you use [Magpie](https://magpie.dev), install-time integration can hand
fstar's named skills over to Magpie's library through its public CLI:

```bash
node scripts/integrate-magpie.cjs                # installs globally, then offers the hand-over
node scripts/integrate-magpie.cjs --dry-run      # never writes anything
fstar install --host claude --magpie             # opt-in hand-over as part of an install
```

Facts and boundaries (verified against magpie 0.1.4380 on 2026-11-20):

- The hand-over is opt-in (`fstar install --magpie`) or run through the
  script; a plain `fstar install` never touches Magpie.
- Discovery checks `PATH` first, then the standard app location
  (`/Applications/magpie.app/Contents/MacOS/magpie`). No Magpie found → the
  step is skipped and the base fstar install is unaffected.
- `FSTAR_MAGPIE_BINARY` and `FSTAR_MAGPIE_AGENTS_SOURCE` redirect the binary
  and the staging directory, so an isolated run never reaches the real app.
- Only the public `magpie library skill hand-over <name>` command is used,
  with a bounded timeout and argv (never a shell string). fstar stages its
  skills into `~/.agents/skills` first; a user's same-named skill is never
  overwritten (reported as a conflict).
- Re-running is idempotent: skills already handed over with the same content
  fingerprint are skipped.
- fstar does NOT edit Magpie-private files (`library.json`,
  `providers.json`), never changes models, accounts, providers, or other
  skills' routing, and does not import hooks or sub-agent definitions —
  Magpie's `agents` are coding tools, not fstar roles. Hooks and agent cards
  stay in the tool-native global host entry described above.
- Updating or removing Magpie-managed skills has no verified public CLI
  path: manage those through Magpie itself. `fstar` only removes local
  staged entries it still owns and that still match the recorded
  fingerprint.

## Development

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t .
node --test tests/test_package.cjs                          # 16 tests
node scripts/build-package.cjs                              # rebuild manifest
```

The test suite runs entirely in temporary directories. It never reads or
writes real host settings, the real user root, or any network location.

`resources/package-assets.json` records a SHA-256 for every shipped file; the
build script regenerates it and the tests verify it is truthful.

## Layout

```
bin/         Node launchers + Python bootstrap
src/fstar/   the kernel (install, tasks, dispatch, evidence, hooks runtime)
resources/   11 skills, 4 role cards, templates, routing
scripts/     package build
tests/       Python and Node suites
```

## License

[MIT](LICENSE)
