#!/usr/bin/env node
'use strict';
// Thin Node launcher for the fstar CLI (PI-I2).
//
// Contract (child design §2): locate the trusted bootstrap beside this file,
// spawn Python with an argv array (never a shell string, never cwd changes),
// forward process.argv.slice(2) verbatim, inherit stdio, and exit with the
// child's status. Terminating signals are re-raised so the exit status stays
// truthful on POSIX; other platforms map to 1 (the child was killed, which
// must never be reported as success).
//
// This launcher contains no fstar task logic. It never modifies host or user
// configuration; settings writes only happen from the explicit
// `fstar install/update/uninstall/migrate` commands implemented in Python.

const path = require('path');
const { spawn } = require('child_process');

const BOOTSTRAP = path.join(__dirname, 'fstar-bootstrap.py');

function fail(code, message, hint, json) {
  const payload = {
    error: { code: code, message: message, details: { hint: hint || null } },
  };
  const text = json ? JSON.stringify(payload) : 'fstar: ' + code + ': ' + message + (hint ? '\n  ' + hint : '');
  // Missing interpreter is the conventional "command not found" (127); an
  // existing but too-old interpreter is an ordinary failure (1).
  process.stderr.write(text + '\n');
  process.exitCode = code === 'python_unavailable' ? 127 : 1;
}

// `python -V` is captured with a fixed argv; the version is never parsed out
// of a user shell string. FSTAR_PYTHON, when set, must be a single executable
// path and is used verbatim.
function probePython(json, done) {
  const candidates = [];
  if (process.env.FSTAR_PYTHON) {
    candidates.push(process.env.FSTAR_PYTHON);
  } else {
    candidates.push('python3', 'python');
  }
  let index = 0;
  const tryNext = () => {
    if (index >= candidates.length) {
      fail(
        'python_unavailable',
        'No usable Python interpreter found',
        'Install Python 3.9 or newer, or set FSTAR_PYTHON to a single executable path',
        json
      );
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
        // Interpreter exists but is older than 3.9: report it precisely
        // instead of silently trying (and possibly running) something else.
        const version = spawn(candidate, ['-V'], { stdio: ['ignore', 'pipe', 'ignore'], shell: false });
        let reported = '';
        version.stdout.on('data', (chunk) => {
          reported += chunk.toString();
        });
        version.on('error', () => {
          reported = 'unknown version';
        });
        version.on('close', () => {
          fail(
            'python_version_unsupported',
            ('Python 3.9+ is required; ' + candidate + ' reports ' + reported.trim()),
            'Upgrade Python to 3.9+ or set FSTAR_PYTHON to a 3.9+ interpreter path',
            json
          );
          done(null);
        });
      } else {
        tryNext();
      }
    });
  };
  tryNext();
}

function launch(executable, args) {
  // The bootstrap takes the target fstar module as its first argument; the
  // full user argv follows verbatim (never re-parsed, never shell-joined).
  const child = spawn(executable, ['-I', BOOTSTRAP, 'cli'].concat(args), {
    stdio: 'inherit',
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
    fail('spawn_error', 'Failed to start Python: ' + error.message, null, false);
  });
  child.on('close', (status, signal) => {
    for (const [name, forward] of forwarders) process.removeListener(name, forward);
    if (signal) {
      // Re-raise the same signal so the wrapper dies the way the child died;
      // a numeric mapping here would lie about the termination cause.
      const delivered = process.kill(process.pid, signal);
      if (delivered) {
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
  const json = args.indexOf('--json') !== -1;
  probePython(json, (executable) => {
    if (executable) {
      launch(executable, args);
    }
  });
}

main();
