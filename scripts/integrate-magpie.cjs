#!/usr/bin/env node
'use strict';
// Optional Magpie integration entry (P-003). Runs the fstar install/update
// path first, then offers the public-CLI skill hand-over. Magpie absence or
// failure degrades the report but never fails the base fstar delivery.
//
// Usage: node scripts/integrate-magpie.cjs [--user-data-root PATH]
//                                          [--runtime-root PATH]
//                                          [--skills-root PATH]
//                                          [--agents-source PATH]
//                                          [--dry-run]
//
// Only the public Magpie CLI (`--version`, `library skill hand-over <name>`)
// is invoked, via argv subprocess with a bounded timeout. Private Magpie
// files (library.json / providers.json), models, accounts, providers, and
// unrelated routing are never read or written. All mutation happens only in
// roots passed explicitly on the command line; defaults are the standard
// user roots.

const { spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

function parseArgs(argv) {
  const args = {
    userDataRoot: process.env.FSTAR_USER_ROOT || path.join(os.homedir(), '.fstar'),
    runtimeRoot: null,
    skillsRoot: null,
    agentsSource: path.join(os.homedir(), '.agents', 'skills'),
    dryRun: false,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const value = argv[i + 1];
    switch (argv[i]) {
      case '--user-data-root': args.userDataRoot = value; i += 1; break;
      case '--runtime-root': args.runtimeRoot = value; i += 1; break;
      case '--skills-root': args.skillsRoot = value; i += 1; break;
      case '--agents-source': args.agentsSource = value; i += 1; break;
      case '--dry-run': args.dryRun = true; break;
      default: throw new Error('unknown argument ' + argv[i]);
    }
  }
  return args;
}

function discoverMagpie() {
  const which = spawnSync('which', ['magpie'], { encoding: 'utf8', shell: false });
  if (which.status === 0 && which.stdout.trim()) {
    return which.stdout.trim();
  }
  const candidates = [
    '/Applications/magpie.app/Contents/MacOS/magpie',
    path.join(os.homedir(), 'Applications', 'magpie.app', 'Contents', 'MacOS', 'magpie'),
  ];
  for (const candidate of candidates) {
    try {
      fs.accessSync(candidate, fs.constants.X_OK);
      return candidate;
    } catch (_) { /* next */ }
  }
  return null;
}

function probe(binary) {
  const result = spawnSync(binary, ['--version'], { encoding: 'utf8', shell: false, timeout: 10000 });
  if (result.error || result.status !== 0) {
    return { available: false, reason: result.error ? String(result.error) : 'exit ' + result.status };
  }
  return { available: true, version: (result.stdout || result.stderr || '').trim().split('\n').pop() };
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const skillsRoot = args.skillsRoot
    || path.join(path.dirname(__dirname), 'resources', 'skills');
  const fstarRoot = path.join(path.dirname(__dirname));
  // A dry run must really write nothing: the install itself is planned, not
  // applied, and no skill is staged and no hand-over command is issued.
  const install = spawnSync('node', [path.join(fstarRoot, 'bin', 'fstar.cjs'),
    '--user-data-root', args.userDataRoot].concat(args.runtimeRoot ? ['--runtime-root', args.runtimeRoot] : []).concat(args.dryRun ? ['install', '--host', 'claude', '--dry-run'] : ['install', '--host', 'claude']),
    { encoding: 'utf8', shell: false, stdio: args.dryRun ? 'pipe' : 'inherit' });
  const baseOk = !install.error && install.status === 0;
  const binary = discoverMagpie();
  if (args.dryRun) {
    // Report what WOULD be handed over. Nothing is staged and Magpie is not
    // asked to do anything: a dry run that writes is not a dry run.
    const skills = fs.existsSync(skillsRoot)
      ? fs.readdirSync(skillsRoot, { withFileTypes: true })
        .filter((entry) => entry.isDirectory()
          && fs.existsSync(path.join(skillsRoot, entry.name, 'SKILL.md')))
        .map((entry) => entry.name)
        .sort()
      : [];
    process.stdout.write(JSON.stringify({
      ok: baseOk,
      dry_run: true,
      magpie: {
        status: binary ? 'would_hand_over' : 'skipped',
        reason: binary ? undefined : 'magpie binary not found',
        binary: binary || null,
        skills: skills,
        agents_source: args.agentsSource,
      },
    }, null, 2) + '\n');
    process.exitCode = baseOk ? 0 : 1;
    return;
  }
  if (!binary) {
    process.stdout.write(JSON.stringify({
      ok: baseOk, magpie: { status: 'skipped', reason: 'magpie binary not found' },
    }, null, 2) + '\n');
    process.exitCode = baseOk ? 0 : 1;
    return;
  }
  const status = probe(binary);
  if (!status.available) {
    process.stdout.write(JSON.stringify({
      ok: baseOk, magpie: { status: 'skipped', reason: status.reason },
    }, null, 2) + '\n');
    process.exitCode = baseOk ? 0 : 1;
    return;
  }
  // Delegate the named hand-over to the Python module, which owns ownership
  // records, fingerprint checks, and idempotency.
  const pythonArgs = [ '-c',
    'import json,sys;from pathlib import Path;from fstar.magpie import integrate;' +
    'args=json.loads(sys.argv[1]);' +
    'print(json.dumps(integrate(skills_root=Path(args["skillsRoot"]),' +
    'agents_source=Path(args["agentsSource"]),binary=args["binary"],' +
    'user_root=Path(args["userDataRoot"])),ensure_ascii=False))',
    JSON.stringify({ skillsRoot, agentsSource: args.agentsSource, binary,
      userDataRoot: args.userDataRoot }) ];
  const integration = spawnSync('python3', pythonArgs,
    { encoding: 'utf8', shell: false, timeout: 60000,
      env: Object.assign({}, process.env, { PYTHONPATH: path.join(fstarRoot, 'src') }) });
  let report;
  try {
    report = JSON.parse(integration.stdout || '{}');
  } catch (_) {
    report = { status: 'degraded', reason: (integration.stderr || 'unreadable output').slice(0, 300) };
  }
  process.stdout.write(JSON.stringify({
    ok: baseOk,
    install_exit: baseOk ? 0 : (install.status === null ? 'signal' : install.status),
    magpie: report,
  }, null, 2) + '\n');
  // Degraded Magpie never fails the run; a failed base install does.
  process.exitCode = baseOk ? 0 : 1;
}

main();
