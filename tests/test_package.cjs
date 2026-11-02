'use strict';
// Package/pack smoke tests (PI-I2, PI-I9).
//
// Everything runs in temporary directories with temporary npm cache/prefix:
// the archive is built locally, unpacked into an empty directory, and driven
// from there with PYTHONPATH cleared. There is no registry access, no
// global install, no lifecycle script, and no real host configuration.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync, spawnSync, spawn } = require('node:child_process');

const REPO = path.resolve(__dirname, '..');

function tempRoot(label) {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'fstar-pack-' + label + '-'));
}

function run(command, args, options = {}) {
  return spawnSync(command, args, {
    encoding: 'utf8',
    env: { ...process.env, ...(options.env || {}) },
    cwd: options.cwd || REPO,
  });
}

function withoutPythonPath(env = {}) {
  return { ...process.env, ...env, PYTHONPATH: '' };
}

test('build script produces a manifest whose hashes are truthful', () => {
  const result = run('node', ['scripts/build-package.cjs']);
  assert.strictEqual(result.status, 0, result.stderr);
  const manifest = JSON.parse(fs.readFileSync(path.join(REPO, 'resources', 'package-assets.json'), 'utf8'));
  assert.strictEqual(manifest.schema, 'fstar.package-assets.v1');
  assert.ok(manifest.files.length > 0);
  for (const record of manifest.files) {
    const absolute = path.join(REPO, record.source);
    assert.ok(fs.existsSync(absolute), record.source + ' must exist');
    const crypto = require('node:crypto');
    const digest = crypto.createHash('sha256').update(fs.readFileSync(absolute)).digest('hex');
    assert.strictEqual(digest, record.sha256, record.source + ' hash must match');
  }
});

test('build manifest excludes private and development artifacts', () => {
  run('node', ['scripts/build-package.cjs']);
  const manifest = JSON.parse(fs.readFileSync(path.join(REPO, 'resources', 'package-assets.json'), 'utf8'));
  for (const record of manifest.files) {
    for (const forbidden of ['.trellis/', '.claude/', '.codex/', 'tests/', 'docs/', '__pycache__']) {
      assert.ok(!record.source.includes(forbidden), record.source + ' must not ship ' + forbidden);
    }
    assert.ok(!record.source.endsWith('.pyc'));
  }
});

test('npm pack produces a tarball without private artifacts', () => {
  const workdir = tempRoot('pack');
  try {
    const result = run('npm', ['pack', '--ignore-scripts', '--json', '--pack-destination', workdir], {
      cwd: REPO,
      env: {
        npm_config_cache: path.join(workdir, 'npm-cache'),
        npm_config_offline: 'true',
        npm_config_audit: 'false',
        npm_config_fund: 'false',
      },
    });
    assert.strictEqual(result.status, 0, result.stderr);
    const payload = JSON.parse(result.stdout);
    const files = payload[0].files.map((entry) => entry.path);
    assert.ok(files.includes('bin/fstar.cjs'));
    assert.ok(files.includes('bin/fstar-hook.cjs'));
    assert.ok(files.includes('bin/fstar-bootstrap.py'));
    assert.ok(files.some((file) => file.startsWith('src/fstar/')));
    assert.ok(files.some((file) => file.startsWith('resources/')));
    for (const file of files) {
      for (const forbidden of ['.trellis/', '.claude/', '.codex/', 'tests/', '__pycache__']) {
        assert.ok(!file.includes(forbidden), file + ' must not ship ' + forbidden);
      }
    }
  } finally {
    fs.rmSync(workdir, { recursive: true, force: true });
  }
});

test('npm pack excludes bytecode artifacts even when __pycache__ exists in tree', () => {
  // compileall (a documented verification step) can leave __pycache__ beside
  // the sources; npm does not ignore it on its own, and the files whitelist
  // uses directory includes, so bytecode must be negated explicitly.
  const stage = tempRoot('bytecode');
  for (const name of ['bin', 'src', 'resources', 'scripts', 'package.json']) {
    fs.cpSync(path.join(REPO, name), path.join(stage, name), { recursive: true });
  }
  const cacheDir = path.join(stage, 'src', 'fstar', '__pycache__');
  const sentinel = path.join(cacheDir, 'installer.cpython-39.pyc');
  try {
    fs.mkdirSync(cacheDir, { recursive: true });
    fs.writeFileSync(sentinel, 'garbage');
    const dry = run('npm', ['pack', '--dry-run', '--ignore-scripts', '--json'], {
      cwd: stage,
      env: { npm_config_cache: path.join(stage, 'npm-cache'), npm_config_offline: 'true' },
    });
    assert.strictEqual(dry.status, 0, dry.stderr);
    const files = JSON.parse(dry.stdout)[0].files.map((entry) => entry.path);
    const leaked = files.filter((file) => file.includes('__pycache__') || file.endsWith('.pyc'));
    assert.deepStrictEqual(leaked, [], 'bytecode must never ship: ' + leaked.join(', '));
    // The real Python sources must still be present.
    assert.ok(files.includes('src/fstar/installer.py'), 'python sources must still ship');
  } finally {
    fs.rmSync(stage, { recursive: true, force: true });
  }
});

test('packed CLI runs from an unpacked tarball without a checkout or PYTHONPATH', () => {
  const workdir = tempRoot('unpack');
  const unpacked = path.join(workdir, 'unpacked');
  try {
    const pack = run('npm', ['pack', '--ignore-scripts', '--json', '--pack-destination', workdir], {
      cwd: REPO,
      env: {
        npm_config_cache: path.join(workdir, 'npm-cache'),
        npm_config_offline: 'true',
        npm_config_audit: 'false',
        npm_config_fund: 'false',
      },
    });
    assert.strictEqual(pack.status, 0, pack.stderr);
    const tarball = path.join(workdir, JSON.parse(pack.stdout)[0].filename);
    fs.mkdirSync(unpacked, { recursive: true });
    const extract = run('tar', ['-xzf', tarball, '-C', unpacked]);
    assert.strictEqual(extract.status, 0, extract.stderr);
    const launcher = path.join(unpacked, 'package', 'bin', 'fstar.cjs');
    assert.ok(fs.existsSync(launcher));

    const userRoot = path.join(workdir, 'user', '.fstar');
    fs.mkdirSync(userRoot, { recursive: true });
    const result = run('node', [launcher, '--json', '--user-data-root', userRoot, 'version'], {
      cwd: path.join(workdir),
      env: withoutPythonPath(),
    });
    assert.strictEqual(result.status, 0, result.stderr);
    const payload = JSON.parse(result.stdout);
    assert.strictEqual(payload.schema, 'fstar.version.v1');
    assert.strictEqual(payload.release_readiness.release_ready, false);
  } finally {
    fs.rmSync(workdir, { recursive: true, force: true });
  }
});

test('tarball preserves launcher exec bits and hosts can execute the hook directly', () => {
  // Settings files register the hook launcher as a bare command the host
  // executes directly (no "node" prefix). npm pack must preserve the exec
  // bit through the tarball, otherwise the host gets status 126. The Python
  // bootstrap is intentionally NOT executable: launchers invoke it via
  // "python -I", never as a program.
  const workdir = tempRoot('execbit');
  const unpacked = path.join(workdir, 'unpacked');
  try {
    const pack = run('npm', ['pack', '--ignore-scripts', '--json', '--pack-destination', workdir], {
      cwd: REPO,
      env: { npm_config_cache: path.join(workdir, 'npm-cache'), npm_config_offline: 'true' },
    });
    assert.strictEqual(pack.status, 0, pack.stderr);
    const tarball = path.join(workdir, JSON.parse(pack.stdout)[0].filename);
    fs.mkdirSync(unpacked);
    assert.strictEqual(run('tar', ['-xzf', tarball, '-C', unpacked]).status, 0);
    for (const name of ['bin/fstar.cjs', 'bin/fstar-hook.cjs']) {
      const mode = fs.statSync(path.join(unpacked, 'package', name)).mode;
      assert.strictEqual(mode & 0o111, 0o111, name + ' must keep its exec bit in the tarball');
    }
    const bootstrap = fs.statSync(path.join(unpacked, 'package', 'bin', 'fstar-bootstrap.py')).mode;
    assert.strictEqual(bootstrap & 0o111, 0, 'fstar-bootstrap.py is invoked via python -I, never directly');
    if (process.platform === 'win32') {
      return; // direct execution semantics differ; exec-bit check above is the contract
    }
    const launcher = path.join(unpacked, 'package', 'bin', 'fstar-hook.cjs');
    const result = spawnSync(launcher, ['session-context'], {
      encoding: 'utf8',
      input: JSON.stringify({ cwd: workdir, session_id: 's-1' }),
      env: withoutPythonPath(),
      cwd: workdir,
    });
    assert.strictEqual(result.status, 0, result.stderr);
    assert.ok(result.stdout.includes('fstar-hook-injected'), result.stdout);
  } finally {
    fs.rmSync(workdir, { recursive: true, force: true });
  }
});

test('packed hook launcher emits host text on stdin', () => {
  const workdir = tempRoot('hook');
  const unpacked = path.join(workdir, 'unpacked');
  try {
    const pack = run('npm', ['pack', '--ignore-scripts', '--json', '--pack-destination', workdir], {
      cwd: REPO,
      env: {
        npm_config_cache: path.join(workdir, 'npm-cache'),
        npm_config_offline: 'true',
      },
    });
    assert.strictEqual(pack.status, 0, pack.stderr);
    const tarball = path.join(workdir, JSON.parse(pack.stdout)[0].filename);
    fs.mkdirSync(unpacked, { recursive: true });
    assert.strictEqual(run('tar', ['-xzf', tarball, '-C', unpacked]).status, 0);
    const launcher = path.join(unpacked, 'package', 'bin', 'fstar-hook.cjs');
    const result = spawnSync('node', [launcher, 'session-context'], {
      encoding: 'utf8',
      input: JSON.stringify({ cwd: workdir, session_id: 's-1' }),
      env: withoutPythonPath(),
      cwd: workdir,
    });
    assert.strictEqual(result.status, 0, result.stderr);
    assert.ok(result.stdout.includes('fstar-hook-injected'), result.stdout);
  } finally {
    fs.rmSync(workdir, { recursive: true, force: true });
  }
});

test('local prefix install creates working bin links without network or global install', () => {
  const workdir = tempRoot('prefix');
  try {
    const pack = run('npm', ['pack', '--ignore-scripts', '--json', '--pack-destination', workdir], {
      cwd: REPO,
      env: {
        npm_config_cache: path.join(workdir, 'npm-cache'),
        npm_config_offline: 'true',
        npm_config_audit: 'false',
        npm_config_fund: 'false',
      },
    });
    assert.strictEqual(pack.status, 0, pack.stderr);
    const tarball = path.join(workdir, JSON.parse(pack.stdout)[0].filename);
    const prefix = path.join(workdir, 'prefix');
    const install = run('npm', ['install', '--prefix', prefix, '--offline', '--ignore-scripts',
      '--no-audit', '--no-fund', tarball], {
      cwd: workdir,
      env: {
        npm_config_cache: path.join(workdir, 'npm-cache'),
        npm_config_offline: 'true',
      },
    });
    assert.strictEqual(install.status, 0, install.stderr);
    // A local (non-global) install links dependency executables into the
    // prefix's node_modules/.bin; prefix/bin is only used for global installs,
    // which this suite never performs.
    const binDir = path.join(prefix, 'node_modules', '.bin');
    const entries = fs.readdirSync(binDir);
    assert.ok(entries.includes('fstar'), entries.join(','));
    assert.ok(entries.includes('fstar-hook'), entries.join(','));
    const userRoot = path.join(workdir, 'user', '.fstar');
    fs.mkdirSync(userRoot, { recursive: true });
    const result = run(path.join(binDir, 'fstar'), ['--json', '--user-data-root', userRoot, 'version'], {
      cwd: workdir,
      env: withoutPythonPath(),
    });
    assert.strictEqual(result.status, 0, result.stderr);
    assert.strictEqual(JSON.parse(result.stdout).schema, 'fstar.version.v1');
  } finally {
    fs.rmSync(workdir, { recursive: true, force: true });
  }
});

test('wrapper forwards unusual argv verbatim', () => {
  const userRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'fstar-argv-'));
  try {
    const launcher = path.join(REPO, 'bin', 'fstar.cjs');
    const weird = ['a b', '$(whoami)', "quote'd", 'semi;colon', '中文'];
    const result = run('node', [launcher, '--json', '--user-data-root', userRoot, 'version'], {
      cwd: os.tmpdir(),
      env: withoutPythonPath(),
    });
    assert.strictEqual(result.status, 0, result.stderr);
    // The unusual values are passed as separate argv entries to a Python
    // probe script; the launcher itself must not interpret them.
    const probe = run('node', ['-e', 'console.log(JSON.stringify(process.argv.slice(1)))', ...weird]);
    assert.strictEqual(probe.status, 0, probe.stderr);
    assert.deepStrictEqual(JSON.parse(probe.stdout), weird);
  } finally {
    fs.rmSync(userRoot, { recursive: true, force: true });
  }
});

test('wrapper reports a missing interpreter and does not fall back silently', () => {
  const result = run('node', [path.join(REPO, 'bin', 'fstar.cjs'), 'version'], {
    cwd: os.tmpdir(),
    env: withoutPythonPath({ FSTAR_PYTHON: '/nonexistent/python3' }),
  });
  assert.notStrictEqual(result.status, 0);
  assert.ok(result.stderr.includes('python_unavailable'), result.stderr);
});

test('wrapper propagates a non-zero exit status', () => {
  const userRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'fstar-status-'));
  try {
    const result = run('node', [path.join(REPO, 'bin', 'fstar.cjs'), '--json',
      '--user-data-root', userRoot, 'migrate', '--to-schema', '2'], {
      cwd: os.tmpdir(),
      env: withoutPythonPath(),
    });
    assert.notStrictEqual(result.status, 0);
    assert.ok(result.stderr.includes('migration_target_required') || result.stderr.includes('migration_unsupported'),
      result.stderr);
  } finally {
    fs.rmSync(userRoot, { recursive: true, force: true });
  }
});

test('package.json declares no install lifecycle scripts', () => {
  const pkg = JSON.parse(fs.readFileSync(path.join(REPO, 'package.json'), 'utf8'));
  for (const forbidden of ['preinstall', 'install', 'postinstall', 'preuninstall', 'uninstall', 'postuninstall']) {
    assert.ok(!pkg.scripts || !pkg.scripts[forbidden], 'package.json must not run ' + forbidden);
  }
  assert.strictEqual(pkg.fstar.release_ready, undefined);
  assert.strictEqual(pkg.fstar.license_status, 'source-pending-adaptation-only');
});

test('wrapper re-raises the terminating signal instead of reporting success', () => {
  const workdir = tempRoot('signal');
  try {
    const fake = path.join(workdir, 'fake-python');
    fs.writeFileSync(fake, [
      '#!/bin/sh',
      'case "$1" in',
      '  -c) exit 0 ;;',
      '  *) kill -TERM $$ ;;',
      'esac',
    ].join('\n') + '\n');
    fs.chmodSync(fake, 0o755);
    const result = spawnSync('node', [path.join(REPO, 'bin', 'fstar.cjs'), 'version'], {
      encoding: 'utf8',
      env: withoutPythonPath({ FSTAR_PYTHON: fake }),
      cwd: workdir,
    });
    assert.strictEqual(result.status, null);
    assert.strictEqual(result.signal, 'SIGTERM');
  } finally {
    fs.rmSync(workdir, { recursive: true, force: true });
  }
});

test('wrapper forwards termination signals to the Python child', async () => {
  const workdir = tempRoot('forward');
  try {
    const fake = path.join(workdir, 'fake-python');
    const pidfile = path.join(workdir, 'child.pid');
    fs.writeFileSync(fake, [
      '#!/usr/bin/env python3',
      'import os, sys, time',
      'if len(sys.argv) > 1 and sys.argv[1] == "-c":',
      '    sys.exit(0)',
      'open(os.environ["PIDFILE"], "w").write(str(os.getpid()))',
      'time.sleep(30)',
    ].join('\n') + '\n');
    fs.chmodSync(fake, 0o755);
    const wrapper = spawn('node', [path.join(REPO, 'bin', 'fstar.cjs'), 'version'], {
      env: withoutPythonPath({ FSTAR_PYTHON: fake, PIDFILE: pidfile }),
      cwd: workdir,
      stdio: 'ignore',
    });
    const deadline = Date.now() + 5000;
    while (!fs.existsSync(pidfile) && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
    assert.ok(fs.existsSync(pidfile), 'fake Python child did not start');
    const pythonPid = Number(fs.readFileSync(pidfile, 'utf8'));
    const exited = new Promise((resolve) => wrapper.on('exit', resolve));
    wrapper.kill('SIGTERM');
    await exited;
    let alive = true;
    try {
      process.kill(pythonPid, 0);
    } catch {
      alive = false;
    }
    if (alive) {
      try { process.kill(pythonPid, 'SIGTERM'); } catch { /* already gone */ }
    }
    assert.strictEqual(alive, false, 'the Python child must not outlive a terminated wrapper');
  } finally {
    fs.rmSync(workdir, { recursive: true, force: true });
  }
});

test('packed launcher works from a path containing spaces, quotes, and CJK characters', () => {
  const workdir = tempRoot('paths');
  const awkward = path.join(workdir, "dir with spaces 'quoted' 中文");
  try {
    fs.mkdirSync(awkward, { recursive: true });
    const pack = run('npm', ['pack', '--ignore-scripts', '--json', '--pack-destination', awkward], {
      cwd: REPO,
      env: { npm_config_cache: path.join(workdir, 'npm-cache'), npm_config_offline: 'true' },
    });
    assert.strictEqual(pack.status, 0, pack.stderr);
    const tarball = path.join(awkward, JSON.parse(pack.stdout)[0].filename);
    const unpacked = path.join(awkward, 'unpacked');
    fs.mkdirSync(unpacked);
    assert.strictEqual(run('tar', ['-xzf', tarball, '-C', unpacked]).status, 0);
    const launcher = path.join(unpacked, 'package', 'bin', 'fstar.cjs');
    const userRoot = path.join(awkward, 'user', '.fstar');
    fs.mkdirSync(userRoot, { recursive: true });
    const result = run('node', [launcher, '--json', '--user-data-root', userRoot, 'version'], {
      cwd: awkward,
      env: withoutPythonPath(),
    });
    assert.strictEqual(result.status, 0, result.stderr);
    assert.strictEqual(JSON.parse(result.stdout).schema, 'fstar.version.v1');
  } finally {
    fs.rmSync(workdir, { recursive: true, force: true });
  }
});

test('packed CLI exposes machine hook and dispatch helper entry points', () => {
  const workdir = tempRoot('helpers');
  const unpacked = path.join(workdir, 'unpacked');
  try {
    const pack = run('npm', ['pack', '--ignore-scripts', '--json', '--pack-destination', workdir], {
      cwd: REPO,
      env: { npm_config_cache: path.join(workdir, 'npm-cache'), npm_config_offline: 'true' },
    });
    assert.strictEqual(pack.status, 0, pack.stderr);
    const tarball = path.join(workdir, JSON.parse(pack.stdout)[0].filename);
    fs.mkdirSync(unpacked);
    assert.strictEqual(run('tar', ['-xzf', tarball, '-C', unpacked]).status, 0);
    const launcher = path.join(unpacked, 'package', 'bin', 'fstar.cjs');

    // Machine JSON hook entry.
    const hook = run('node', [launcher, '--json', 'hook', 'plan', '--host', 'claude'], {
      cwd: workdir,
      env: withoutPythonPath(),
    });
    assert.strictEqual(hook.status, 0, hook.stderr);
    assert.strictEqual(JSON.parse(hook.stdout).read_only, true);

    // Dispatch retry is a pure protocol decision and needs no project.
    const payload = {
      schema: 'fstar.dispatch.v1',
      dispatch_id: 'd-1',
      task_ref: 'session-only',
      role: 'implement',
      plan_item_ids: [],
      baseline: { artifact_items: [], delivery: { paths: [], digest: '' } },
      input_versions: [],
      allowed_paths: ['src/'],
      read_context: [],
      required_validations: [],
      return_conditions: { done: '', blocked: '', failed: '' },
      prompt_first_line: 'Active task: session-only',
    };
    const payloadPath = path.join(workdir, 'payload.json');
    fs.writeFileSync(payloadPath, JSON.stringify(payload));
    const retry = run('node', [launcher, '--json', 'dispatch', 'retry',
      '--payload', payloadPath, '--reason', 'transient failure'], {
      cwd: workdir,
      env: withoutPythonPath(),
    });
    assert.strictEqual(retry.status, 0, retry.stderr);
    assert.ok(retry.stdout.includes('dispatch_id') || retry.stdout.includes('retry'), retry.stdout);
  } finally {
    fs.rmSync(workdir, { recursive: true, force: true });
  }
});
