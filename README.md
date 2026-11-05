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
Plan ──► Start ──► Implement ⇄ Check ──► Fresh evidence ──► User acceptance ──► Archive
  │                                                          │
  └── every step recorded in task.json + event log ◄─────────┘
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
fstar init                       # create .fstar/ (tasks, specs, knowledge)
fstar install --host claude      # wire hooks + skills + agents into <project>/.claude
fstar task create "My feature" --name my-feature
fstar start my-feature           # planning → in_progress
# ... work with your agent; fstar-managed skills drive the flow ...
fstar accept my-feature          # user acceptance
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
change, the evidence goes stale and completion is blocked. Completion requires
fresh check evidence **plus explicit user acceptance** (`fstar accept`) — a
command succeeding is not acceptance. `fstar evidence invalidate --file PATH`
expires evidence on demand; `fstar acceptance status` shows what's missing.

### 6. Archive (`archive`, `drop`)

`fstar archive <task>` moves the accepted tree to `.fstar/archive/YYYY-MM/`,
keeping the event log intact. Tasks that won't proceed use `fstar drop
--reason ... --disposition keep|discard|knowledge` — knowledge-worthy lessons
can be routed into `.fstar/knowledge/` instead of vanishing.

### 7. Resume & interrupts (`continue`, `interrupt`, `doc-edit`)

`fstar continue` resumes an interrupted task from verified on-disk state
(takeover / replan / revise / reopen / unblock). Long-running dispatches can
be steered with `fstar interrupt` (change propagation, cancel, checkpoint
stop). Concurrent document edits go through `fstar doc-edit`, which rejects
stale baselines instead of silently overwriting.

### Extensions (opt-in, never default-on)

`fstar extension enable <id> [--scope full|custom]` negotiates extra
capability packages — `planning-review`, `persistent-task`, `multi-agent`,
`project-governance`, `tool-capability`. Refusing one leaves the minimal loop
intact; nothing is assumed on for you.

## What lands in your project

```
.fstar/            tasks, specs, archive, knowledge — the project's data root
<host>/.claude/    hooks (settings.json), 12 skills, 4 agent cards   [project-level by default]
~/.fstar/          user-level resource cache (shared, versioned) — never host config
```

`fstar uninstall` removes only what the installer itself owns (verified by
content hashes recorded at install time); your specs, tasks, and any file you
touched are never removed.

## Host support

| Host | Hooks | Skills | Agents |
|---|---|---|---|
| Claude Code | verified live | verified live | verified live |
| Codex CLI | user-level hooks require an interactive trust review, so unattended install reports `unsupported-for-unattended` and writes nothing | not adapted | not adapted |

Codex trust is a deliberate gap, not a bug: the host requires a human to
approve each hook the first time, and no installer can consent on your behalf.

## Command reference

Run `fstar <command> --help` for flags. The commands group by purpose:

- **Task lifecycle** — `task create|list|current`, `start`, `accept`,
  `archive`, `drop`, `continue`, `state show`
- **Verification** — `review record|list`, `evidence invalidate`,
  `acceptance status`
- **Extensions** — `extension list|enable|disable`
- **Project** — `init`
- **Install maintenance** — `install`, `update`, `uninstall`, `doctor`,
  `migrate`, `version`
- **Agent-side** (invoked by agents, rarely by hand) — `dispatch ...`,
  `interrupt`, `doc-edit`, `hook ...`, `tools scan`

Global flags: `--project PATH`, `--session ID`, `--user-data-root`,
`--runtime-root`, `--json`, `--actor`, `--actor-role`.

## Updating

```bash
npm update -g fstar-workflow     # or: npm install -g fstar-workflow@latest
fstar update                     # refresh the installed resources in your projects
fstar doctor                     # confirm everything is healthy
```

## Development

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t .   # 687 tests
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
resources/   12 skills, 4 role cards, templates, routing, registries
scripts/     package build
tests/       Python and Node suites
```

## License

[MIT](LICENSE)
