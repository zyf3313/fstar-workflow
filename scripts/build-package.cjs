#!/usr/bin/env node
'use strict';
// Local pack/manifest validation (PI-I2). Standard Node APIs only: no
// network, no host settings, no npm lifecycle writes. Running this script
// builds a package manifest (resources/package-assets.json) and validates
// that every declared runtime file exists. Publishability still requires
// owner sign-off: source/license verification results recorded here
// (2026-11-01) describe evidence, not a release decision (child design §8).

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const ROOT = path.resolve(__dirname, '..');
const ASSETS_PATH = path.join(ROOT, 'resources', 'package-assets.json');

// The whitelist mirrors package.json "files"; keep both in sync when editing.
const RESOURCE_DIRS = ['skills', 'agents', 'templates', 'references', 'capabilities', 'registry', 'schemas', 'runtime'];
const SRC_DIR = path.join(ROOT, 'src', 'fstar');
const BIN_FILES = ['bin/fstar.cjs', 'bin/fstar-hook.cjs', 'bin/fstar-bootstrap.py'];

function walk(dir, collected) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walk(full, collected);
    } else if (entry.isFile()) {
      collected.push(path.relative(ROOT, full));
    }
  }
  return collected;
}

function sha256(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}

function loadPackageMetadata() {
  const raw = fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8');
  const pkg = JSON.parse(raw);
  if (!pkg.fstar || !pkg.fstar.resource_version || !Array.isArray(pkg.fstar.supported_data_schemas)) {
    throw new Error('package.json is missing the fstar {cli_version, resource_version, supported_data_schemas} block');
  }
  return pkg;
}

function collectFiles() {
  const files = [];
  for (const relative of BIN_FILES) {
    const absolute = path.join(ROOT, relative);
    if (!fs.existsSync(absolute)) {
      throw new Error('missing launcher ' + relative);
    }
    files.push({ source: relative, destination: relative, kind: 'launcher' });
  }
  const python = walk(SRC_DIR, [])
    .filter((relative) => relative.endsWith('.py'))
    .sort();
  for (const relative of python) {
    files.push({ source: relative, destination: relative, kind: 'python' });
  }
  for (const dir of RESOURCE_DIRS) {
    const absolute = path.join(ROOT, 'resources', dir);
    if (!fs.existsSync(absolute)) {
      throw new Error('missing resource directory resources/' + dir);
    }
    const items = walk(absolute, [])
      .map((relative) => path.relative(path.join(ROOT, 'resources'), relative))
      .sort();
    for (const relative of items) {
      files.push({ source: 'resources/' + relative, destination: 'resources/' + relative, kind: 'resource' });
    }
  }
  return files;
}

function validateNoPrivateArtifacts(files) {
  const forbiddenRoots = ['.trellis', '.claude', '.codex', '.git', 'tests', 'node_modules', 'docs'];
  const offenders = files.filter((entry) => forbiddenRoots.some((root) => entry.source === root || entry.source.startsWith(root + '/')));
  if (offenders.length) {
    throw new Error('private/dev artifacts leaked into the package: ' + offenders.map((entry) => entry.source).join(', '));
  }
  if (files.some((entry) => entry.source.endsWith('.pyc'))) {
    throw new Error('bytecode artifacts are not allowed in the package');
  }
}

function main() {
  const pkg = loadPackageMetadata();
  const files = collectFiles();
  validateNoPrivateArtifacts(files);
  const indexed = files.map((entry) => ({
    source: entry.source,
    destination: entry.destination,
    kind: entry.kind,
    sha256: sha256(path.join(ROOT, entry.source)),
  }));
  const manifest = {
    schema: 'fstar.package-assets.v1',
    generated_by: 'scripts/build-package.cjs',
    cli_version: pkg.fstar.cli_version,
    resource_version: String(pkg.fstar.resource_version),
    supported_data_schemas: pkg.fstar.supported_data_schemas,
    source_ref: pkg.fstar.source_ref,
    license_status: pkg.fstar.license_status,
    notes: [
      'Source fixed-commit originals verified 2026-11-01: prd.zh-CN.md / technical-design.zh-CN.md / technical-design-profiles.zh-CN.md exist at the pinned commit; fstar templates differ from them (slot markers, restructured sections) and each carries a provenance note. Upstream license remains pending; verbatim copying stays disallowed.',
      'npm package name verified available 2026-11-01: fstar-workflow unregistered (fstar, @fstar/*, fstar-hook also free; near-names fstarter/fstar-wangeditor are unrelated).',
    ],
    files: indexed,
  };
  fs.mkdirSync(path.dirname(ASSETS_PATH), { recursive: true });
  fs.writeFileSync(ASSETS_PATH, JSON.stringify(manifest, null, 2) + '\n', 'utf8');
  process.stdout.write(
    JSON.stringify(
      {
        ok: true,
        assets_path: path.relative(ROOT, ASSETS_PATH),
        file_count: indexed.length,
        resource_version: manifest.resource_version,
        cli_version: manifest.cli_version,
      },
      null,
      2
    ) + '\n'
  );
}

main();
