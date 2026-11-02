#!/usr/bin/env node
'use strict';
// Internal host-text hook launcher (PI-I2). Hosts register this executable
// when the package is explicitly installed; it forwards the host payload on
// stdin to `fstar.runtime.__main__.main` (host-text injection output on
// stdout) using the same bootstrap and Python probe rules as bin/fstar.cjs.
// It is NOT an additional manual flow entry and adds no CLI surface.

const path = require('path');
const { spawn } = require('child_process');
const fs = require('fs');

const BOOTSTRAP = path.join(__dirname, 'fstar-bootstrap.py');

function fail(code, message) {
  process.stderr.write('fstar-hook: ' + code + ': ' + message + '\n');
  process.exitCode = code === 'python_unavailable' ? 127 : 1;
}

function probePython(done) {
  const candidates = [];
  if (process.env.FSTAR_PYTHON) {
    candidates.push(process.env.FSTAR_PYTHON);
  } else {
    candidates.push('python3', 'python');
  }
  let index = 0;
  const tryNext = () => {
    if (index >= candidates.length) {
      fail('python_unavailable', 'No usable Python interpreter found');
      return void done(null);
    }
    const candidate = candidates[index++];
    const probe = spawn(candidate, ['-c', 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 5)'], {
      stdio: ['ignore', 'ignore', 'ignore'],
      shell: false,
    });
    let failed = false;
    probe.on('error', () => { failed = true; tryNext(); });
    probe.on('close', (status) => {
      if (failed) return;
      if (status === 0) {
        done(candidate);
      } else if (status === 5) {
        fail('python_version_unsupported', 'Python 3.9+ is required for fstar hooks');
        done(null);
      } else {
        tryNext();
      }
    });
  };
  tryNext();
}

function launch(executable, args) {
  const child = spawn(executable, ['-I', BOOTSTRAP, 'runtime', args[0]].concat(args.slice(1)), {
    stdio: ['inherit', 'inherit', 'inherit'],
    shell: false,
    env: process.env,
  });
  const forwarders = new Map();
  for (const signal of ['SIGTERM', 'SIGINT', 'SIGHUP']) {
    const forward = () => child.kill(signal);
    forwarders.set(signal, forward);
    process.on(signal, forward);
  }
  child.on('error', (error) => {
    fail('spawn_error', 'Failed to start Python: ' + error.message);
  });
  child.on('close', (status, signal) => {
    for (const [name, forward] of forwarders) process.removeListener(name, forward);
    if (signal) {
      if (process.kill(process.pid, signal)) {
        return;
      }
      process.exitCode = 1;
      return;
    }
    process.exitCode = status === null ? 1 : status;
  });
}

function main() {
  const args = process.argv.slice(2);
  if (args.length === 0) {
    fail('hook_name_required', 'A hook name argument is required (session-context|worker-context|worker-result|doc-change)');
    return;
  }
  // Keep the launcher honest about being unreadable when it must read stdin
  // through inheritance: the Python side reads stdin itself.
  probePython((executable) => {
    if (executable) {
      launch(executable, args);
    }
  });
}

main();
