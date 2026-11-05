# fstar-workflow

A personal, cross-project workflow system for AI coding agents. It keeps task
state, evidence, and routing out of the conversation and on disk, so work
survives compaction, session restarts, and machine changes.

Python 3.9+ standard library only, with a thin Node wrapper for host
integration. No third-party runtime dependencies.

## Status

Personal use, pre-release. The npm package name `fstar-workflow` is verified
unregistered; publishing is a deliberate owner decision and has not happened
yet. `private: true` stays in `package.json` until then.

## Requirements

- Node.js 18 or newer (launcher only)
- Python 3.9 or newer on `PATH` (the kernel)
- Optional hosts: Claude Code, Codex CLI

## Install

From a local build (no registry access):

```bash
npm pack
npm install --prefix ~/.local <the-produced-tarball>.tgz
```

Then put `~/.local/node_modules/.bin` on `PATH`, or use:

```bash
npx --no-install fstar version
```

## Quick start

```bash
fstar version                      # CLI, resource, and data schema versions
fstar doctor                       # read-only install and host health report
fstar install --host claude        # in an fstar project: writes <project>/.claude
fstar install --host claude --user-level   # explicitly writes ~/.claude
fstar uninstall --host claude      # remove only what the installer owns
fstar update                       # refresh an existing install's resources
```

Host root priority: `--host-root claude=PATH` > `--user-level` (`~/.claude`) >
the current fstar project's `.claude`. Outside a fstar project, a bare
`fstar install` refuses to guess and points at `--user-level` or `fstar init`.
`install --dry-run` prints the full plan without writing anything; an
interactive TTY is asked to confirm the host roots before any write.
`update`/`uninstall` resolve roots the same way and refuse with
`uninstall_host_root_mismatch` when the recorded install targets other roots
than the resolved ones (e.g. a user-level install seen from inside a project —
pass `--user-level`).

## What it does

- **Task tree** — `planning → in_progress → completed`, with evidence records,
  leases, and an append-only event log. Task state is a file, not a memory.
- **Verification gates** — evidence goes stale when the artifacts it validated
  change; completion requires fresh check evidence plus explicit user
  acceptance. A command succeeding is not acceptance.
- **Dispatch** — a coordinator hands bounded scope to implement and check
  roles. Every dispatch carries per-input path, hash, and version so harvest
  can verify what the worker actually read.
- **Extension packages** — five packages (`planning-review`,
  `persistent-task`, `multi-agent`, `project-governance`, `tool-capability`)
  are negotiated rather than assumed on. Refusing one leaves the minimal loop
  intact.
- **Routing** — one package-owned routing source, injected at session start,
  that decides what to invoke before invocation. State validation stays with
  the commands.

## Host support

| Host | Hooks | Skills | Agents |
|---|---|---|---|
| Claude Code | verified live | verified live | verified live |
| Codex CLI | user-level hooks exist but require an interactive trust review, so unattended install reports `unsupported-for-unattended` and writes nothing | not adapted | not adapted |

Codex trust is a deliberate gap, not a bug: the host requires a human to
approve each hook the first time, and no installer can consent on your behalf.

## Development

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t .   # 676 tests
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

Unlicensed, personal project. Third-party source provenance and the pending
upstream license status are recorded in `resources/package-assets.json`.
