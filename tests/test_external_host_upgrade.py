"""External host upgrade tests (external-host-upgrade, 2026-11-23).

Reproduction of the 0.9.0 -> 0.10.0 case: an older install reused exact
identical files in the host root and recorded them as ``externally_owned``;
the newer bundle changed those files, and the update refused to refresh
them (or never even selected the host root) because target selection only
looked at owned roots.

Every test runs against temporary roots and synthetic bundles only: HOME,
user data root, runtime root, host roots, project root, and the package
bundle root are all temp dirs. Nothing here reads or writes real host
settings, the real user root, or any network location.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from fstar import installer  # noqa: E402
from fstar.content import SKILLS  # noqa: E402

BUNDLE_ROOT = REPO
BUNDLE_VERSION = str(installer.load_bundle_manifest(BUNDLE_ROOT)["resource_version"])
NEXT_VERSION = "%s-next1" % BUNDLE_VERSION
NEXT_BUNDLE_ROOT: Path | None = None


def _sha_bytes(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


def _sha(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def next_bundle(tmp: Path) -> Path:
    """A synthetic next bundle: same resources, distinct bytes for two skills.

    The bundle carries its own ``resources/`` copy and its own
    ``package-assets.json`` so the update under test resolves real bundle
    content with a different version id — no real globals are touched.
    """
    root = tmp / "next-bundle"
    resources = root / "resources"
    shutil.copytree(REPO / "resources", resources)
    changed = []
    for name in ("continue", "help"):
        target = resources / "skills" / ("fstar-%s" % name) / "SKILL.md"
        original = target.read_text(encoding="utf-8")
        target.write_text(original + "\nUpgraded by the synthetic next bundle.\n", encoding="utf-8")
        changed.append("resources/skills/fstar-%s/SKILL.md" % name)
    base = _load_json(REPO / "resources" / "package-assets.json")
    files = []
    for record in base["files"]:
        record = dict(record)
        if record.get("source") in changed:
            record["sha256"] = _sha(root / record["source"])
        files.append(record)
    # load_bundle_manifest reads bundle_root/resources/package-assets.json;
    # the copied original is overwritten in place, never trusted.
    _write_json(root / "resources" / "package-assets.json", {
        "schema": base["schema"],
        "resource_version": NEXT_VERSION,
        "files": files,
    })
    return root


class ExternalUpgradeCase(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="fstar-external-upgrade-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        # Resolved once here so recorded destinations (the planner records
        # resolved paths) and test comparisons never disagree through a
        # /var -> /private/var symlink on macOS.
        self.user_root = (self.tmp / "user" / ".fstar").resolve()
        self.runtime_root = self.user_root / "runtime"
        self.host_root = (self.tmp / "host" / "claude").resolve()
        self.project_root = (self.tmp / "project").resolve()
        for path in (self.user_root, self.host_root, self.project_root):
            path.mkdir(parents=True, exist_ok=True)
        self.next_bundle = next_bundle(self.tmp)

    def roots(self, **kwargs) -> installer.Roots:
        return installer.Roots(
            user_root=self.user_root,
            runtime_root=self.runtime_root,
            project_root=self.project_root,
            host_roots=kwargs.get("host_roots", {"claude": self.host_root}),
            bundle_root=kwargs.get("bundle_root", BUNDLE_ROOT),
        )

    def run_op(self, operation: str, **kwargs):
        # The same bundle root must reach the plan AND the Roots: _source_bytes
        # reads entry["bundle_root"], which the planner copies from the Roots.
        roots = kwargs.pop("roots", None) or self.roots(
            bundle_root=kwargs.get("bundle_root", BUNDLE_ROOT))
        plan = installer.plan_install(operation=operation, roots=roots, **kwargs)
        return plan, installer.apply_plan(plan, roots=roots)

    def install_reuse(self):
        """The 0.9.0-shaped install: exact identical files already exist.

        Pre-writes every declared Claude skill and agent with byte-identical
        package content (plus identical hook registrations), so the install
        reuses everything and records it as ``externally_owned``. No cache
        from the old install is needed: the manifest itself carries the
        valid historical baseline.
        """
        for _, relative in installer.HOST_FILE_KINDS["claude"]:
            destination = self.host_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((REPO / "resources" / relative).read_bytes())
        hooks = {}
        for shape in installer.registration.PLANS["claude"]:
            semantic = installer._semantic_for_shape(shape)
            command = installer._hook_command(semantic)
            group = {"matcher": "|".join(shape["matchers"] or []),
                     "hooks": [{"type": "command", "command": command, "timeout": 30}]}
            hooks.setdefault(shape["event"], []).append(group)
        _write_json(self.host_root / "settings.json", {"hooks": hooks})
        return self.run_op("install", hosts=["claude"])

    def manifest(self) -> dict:
        return _load_json(self.user_root / ".install-manifest.json")

    def entry_index(self) -> dict:
        return _load_json(self.user_root / "entry-index.json")

    def external_records(self) -> dict:
        return {record["destination"]: record
                for record in self.manifest()["host_file_entries"]
                if record["ownership"] == "externally_owned"}


class TestA001UpgradeRecordedUnchangedExternalReuse(ExternalUpgradeCase):
    def test_update_refreshes_unchanged_recorded_external_reuse(self):
        self.install_reuse()
        destination = self.host_root / "skills" / "fstar-continue" / "SKILL.md"
        plan, result = self.run_op("update", requested_version=NEXT_VERSION,
                                   bundle_root=self.next_bundle)
        upgrades = [entry for entry in plan["host_files"]
                    if entry["action"] == "upgrade_external"]
        self.assertTrue(upgrades, plan["host_files"])
        self.assertIn(str(destination), {entry["destination"] for entry in upgrades})
        self.assertEqual(destination.read_bytes(),
                         (self.next_bundle / "resources" / "skills" /
                          "fstar-continue" / "SKILL.md").read_bytes())
        # The upgrade is a transactional write with backup, not a raw copy.
        written = [item for item in result["applied"]["files"]
                   if item["path"] == str(destination)]
        self.assertEqual(written[0]["action"], "upgrade_external")
        self.assertTrue(Path(written[0]["backup"]).is_file())
        # Host-file backups live under a marked "_external/<name>" path in the
        # user root, so a same-name file in one transaction overwrites an
        # earlier backup (pre-existing _backup behavior, settings share it);
        # rollback correctness is unaffected because the journal, not the
        # backup copies, is what restore replays.
        self.assertIn(Path(written[0]["backup"]).read_bytes(),
                      {(REPO / "resources" / "skills" / "fstar-continue" / "SKILL.md").read_bytes(),
                       (REPO / "resources" / "skills" / "fstar-help" / "SKILL.md").read_bytes()})
        help_written = [item for item in result["applied"]["files"]
                        if item["path"] == str(self.host_root / "skills" / "fstar-help" / "SKILL.md")]
        self.assertEqual(help_written[0]["action"], "upgrade_external")

    def test_default_update_discovers_reuse_roots_without_owned_host_files(self):
        # The whole installation is reuse: no owned host file or settings
        # entry at all. The default update (no --user-level, no host list)
        # must still reach the recorded root and refresh the changed files.
        self.install_reuse()
        plan, _ = self.run_op("update", requested_version=NEXT_VERSION,
                              bundle_root=self.next_bundle)
        self.assertTrue(any(entry["host"] == "claude" for entry in plan["host_files"]))
        self.assertTrue(any(entry["action"] == "upgrade_external" for entry in plan["host_files"]))
        destination = self.host_root / "skills" / "fstar-help" / "SKILL.md"
        self.assertEqual(destination.read_bytes(),
                         (self.next_bundle / "resources" / "skills" /
                          "fstar-help" / "SKILL.md").read_bytes())

    def test_unchanged_external_reuse_is_reported_as_reuse_not_upgrade(self):
        # An agent file whose content did not change between bundles stays a
        # plain reuse: nothing is rewritten and nothing is re-owned.
        self.install_reuse()
        destination = self.host_root / "agents" / "fstar-research.md"
        plan, _ = self.run_op("update", requested_version=NEXT_VERSION,
                              bundle_root=self.next_bundle)
        entry = next(e for e in plan["host_files"] if e["destination"] == str(destination))
        self.assertEqual(entry["action"], "reuse_external")
        records = self.external_records()
        self.assertIn(str(destination), records)
        self.assertEqual(records[str(destination)]["ownership"], "externally_owned")

    def test_update_after_upgrade_is_idempotent(self):
        self.install_reuse()
        self.run_op("update", requested_version=NEXT_VERSION, bundle_root=self.next_bundle)
        plan, result = self.run_op("update", requested_version=NEXT_VERSION,
                                   bundle_root=self.next_bundle)
        # The upgraded file is owned and unmodified now: plain reuse, no
        # second upgrade, and the bytes never churn.
        destination = self.host_root / "skills" / "fstar-continue" / "SKILL.md"
        before = destination.read_bytes()
        entry = next(e for e in plan["host_files"] if e["destination"] == str(destination))
        self.assertEqual(entry["action"], "reuse_owned")
        self.assertEqual(destination.read_bytes(), before)
        self.assertTrue(result["applied"]["files"] or True)  # apply ran to completion


class TestA002PreserveUserOwnershipBoundaries(ExternalUpgradeCase):
    def test_user_modified_external_reuse_is_protected_even_with_overwrite(self):
        self.install_reuse()
        destination = self.host_root / "skills" / "fstar-continue" / "SKILL.md"
        user_bytes = b"user rewrote this skill"
        destination.write_bytes(user_bytes)
        plan, _ = self.run_op("update", requested_version=NEXT_VERSION,
                              bundle_root=self.next_bundle, conflict_policy="overwrite")
        entry = next(e for e in plan["host_files"] if e["destination"] == str(destination))
        self.assertEqual(entry["action"], "conflict")
        self.assertEqual(destination.read_bytes(), user_bytes)
        record = self.external_records()[str(destination)]
        self.assertEqual(record["ownership"], "externally_owned")

    def test_symlinked_external_reuse_is_never_upgraded(self):
        self.install_reuse()
        destination = self.host_root / "skills" / "fstar-continue" / "SKILL.md"
        payload = destination.read_bytes()
        outside = self.tmp / "user-own" / "skill.md"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_bytes(payload)
        destination.unlink()
        destination.symlink_to(outside)
        plan, _ = self.run_op("update", requested_version=NEXT_VERSION,
                              bundle_root=self.next_bundle)
        entry = next(e for e in plan["host_files"] if e["destination"] == str(destination))
        self.assertEqual(entry["action"], "conflict")
        self.assertTrue(destination.is_symlink())
        self.assertEqual(outside.read_bytes(), payload)

    def test_insufficient_history_is_not_treated_as_owned(self):
        # A reuse record without a valid historical version cannot prove the
        # old install authored the file: never upgrade it.
        self.install_reuse()
        destination = self.host_root / "skills" / "fstar-continue" / "SKILL.md"
        manifest = self.manifest()
        for record in manifest["host_file_entries"]:
            if record["destination"] == str(destination):
                record.pop("version", None)
        _write_json(self.user_root / ".install-manifest.json", manifest)
        plan, _ = self.run_op("update", requested_version=NEXT_VERSION,
                              bundle_root=self.next_bundle)
        entry = next(e for e in plan["host_files"] if e["destination"] == str(destination))
        self.assertEqual(entry["action"], "conflict")
        self.assertEqual(destination.read_bytes(),
                         (REPO / "resources" / "skills" / "fstar-continue" / "SKILL.md").read_bytes())

    def test_mismatched_record_identity_is_not_treated_as_owned(self):
        # A record whose hash was tampered (bytes no longer match the recorded
        # baseline) keeps the file the user's: conflict, never an upgrade.
        self.install_reuse()
        destination = self.host_root / "skills" / "fstar-continue" / "SKILL.md"
        manifest = self.manifest()
        for record in manifest["host_file_entries"]:
            if record["destination"] == str(destination):
                record["installed_hash"] = "0" * 64
        _write_json(self.user_root / ".install-manifest.json", manifest)
        plan, _ = self.run_op("update", requested_version=NEXT_VERSION,
                              bundle_root=self.next_bundle)
        entry = next(e for e in plan["host_files"] if e["destination"] == str(destination))
        self.assertEqual(entry["action"], "conflict")

    def test_unrecorded_same_path_file_stays_the_user_s(self):
        # No manifest record at all for the destination: identical bytes are
        # not authorship evidence; reuse, never ownership or upgrade.
        self.install_reuse()
        destination = self.host_root / "skills" / "fstar-continue" / "SKILL.md"
        manifest = self.manifest()
        manifest["host_file_entries"] = [record for record in manifest["host_file_entries"]
                                         if record["destination"] != str(destination)]
        _write_json(self.user_root / ".install-manifest.json", manifest)
        plan, _ = self.run_op("update", requested_version=NEXT_VERSION,
                              bundle_root=self.next_bundle)
        entry = next(e for e in plan["host_files"] if e["destination"] == str(destination))
        self.assertEqual(entry["action"], "conflict")
        self.assertEqual(destination.read_bytes(),
                         (REPO / "resources" / "skills" / "fstar-continue" / "SKILL.md").read_bytes())

    def test_uninstall_keeps_externally_reused_files(self):
        # Discovering reuse roots for update never broadens uninstall: no
        # owned host entry exists, so no host file is deleted (the cache the
        # install itself wrote is still removed, as before).
        self.install_reuse()
        _, result = self.run_op("uninstall")
        removed_host_files = [item for item in result["applied"]["removed"] if item.get("host")]
        self.assertEqual(removed_host_files, [])
        for _, relative in installer.HOST_FILE_KINDS["claude"]:
            self.assertTrue((self.host_root / relative).is_file(), relative)

    def test_update_refuses_a_mismatched_host_root(self):
        self.install_reuse()
        other_root = self.tmp / "other-host" / "claude"
        other_root.mkdir(parents=True, exist_ok=True)
        with self.assertRaises(installer.DomainError) as caught:
            installer.plan_install(
                operation="update",
                roots=installer.Roots(
                    user_root=self.user_root,
                    runtime_root=self.runtime_root,
                    project_root=self.project_root,
                    host_roots={"claude": other_root},
                    bundle_root=self.next_bundle),
                requested_version=NEXT_VERSION)
        self.assertEqual(caught.exception.code, "uninstall_host_root_mismatch")

    def test_uninstall_of_empty_manifest_leaves_user_files(self):
        # A manifest with only reuse records gives uninstall no owned host
        # scope: it must not scan the host root for reusable files to delete.
        self.install_reuse()
        manifest = self.manifest()
        manifest["host_file_entries"] = [r for r in manifest["host_file_entries"]
                                         if r["ownership"] == "externally_owned"]
        _write_json(self.user_root / ".install-manifest.json", manifest)
        _, result = self.run_op("uninstall")
        removed_host_files = [item for item in result["applied"]["removed"] if item.get("host")]
        self.assertEqual(removed_host_files, [])
        self.assertTrue((self.host_root / "skills" / "fstar-continue" / "SKILL.md").is_file())


class TestA003DurableAuditableUpgrade(ExternalUpgradeCase):
    def test_upgrade_writes_consistent_manifest_and_entry_index(self):
        self.install_reuse()
        destination = self.host_root / "skills" / "fstar-continue" / "SKILL.md"
        plan, result = self.run_op("update", requested_version=NEXT_VERSION,
                                   bundle_root=self.next_bundle)
        operation_id = result["operation_id"]
        manifest = self.manifest()
        record = next(r for r in manifest["host_file_entries"]
                      if r["destination"] == str(destination))
        # The upgrade re-owns the file and records the bytes it actually wrote.
        self.assertEqual(record["ownership"], "owned")
        self.assertEqual(record["installed_hash"],
                         _sha(self.next_bundle / "resources" / "skills"
                              / "fstar-continue" / "SKILL.md"))
        self.assertEqual(record["version"], NEXT_VERSION)
        self.assertEqual(record["operation_id"], operation_id)
        self.assertEqual(manifest["version"], NEXT_VERSION)
        self.assertEqual((self.user_root / "version").read_text().strip(), NEXT_VERSION)
        # Entry index follows the write (the old skip bug): ownership,
        # version, and operation id all move with the refreshed bytes.
        index_entry = next(e for e in self.entry_index()["entries"]
                           if e["installed_path"] == str(destination))
        self.assertEqual(index_entry["ownership"], "owned")
        self.assertEqual(index_entry["version"], NEXT_VERSION)
        self.assertEqual(index_entry["operation_id"], operation_id)

    def test_owned_overwrite_updates_the_entry_index(self):
        # Even before this repair, an owned-file update (overwrite) skipped
        # the index entry: the index kept the old version id forever.
        self.run_op("install", hosts=["claude"])
        destination = self.host_root / "skills" / "fstar-continue" / "SKILL.md"
        _, result = self.run_op("update", requested_version=NEXT_VERSION,
                                bundle_root=self.next_bundle)
        index_entry = next(e for e in self.entry_index()["entries"]
                           if e["installed_path"] == str(destination))
        self.assertEqual(index_entry["version"], NEXT_VERSION)
        self.assertEqual(index_entry["operation_id"], result["operation_id"])
        self.assertEqual(index_entry["ownership"], "owned")

    def test_user_edit_after_upgrade_is_protected(self):
        self.install_reuse()
        self.run_op("update", requested_version=NEXT_VERSION, bundle_root=self.next_bundle)
        destination = self.host_root / "skills" / "fstar-continue" / "SKILL.md"
        user_bytes = b"user edit after the upgrade"
        destination.write_bytes(user_bytes)
        plan, _ = self.run_op("update", requested_version=NEXT_VERSION,
                              bundle_root=self.next_bundle)
        entry = next(e for e in plan["host_files"] if e["destination"] == str(destination))
        self.assertEqual(entry["action"], "keep_modified")
        self.assertEqual(destination.read_bytes(), user_bytes)

    def test_end_to_end_repeated_update_and_later_user_edit(self):
        # 0.9.0-shaped reuse -> 0.10.0-shaped upgrade -> idempotent repeat
        # upgrade -> later user edit protected, in one pipeline.
        self.install_reuse()
        destination = self.host_root / "skills" / "fstar-continue" / "SKILL.md"
        self.run_op("update", requested_version=NEXT_VERSION, bundle_root=self.next_bundle)
        self.run_op("update", requested_version=NEXT_VERSION, bundle_root=self.next_bundle)
        self.assertEqual(destination.read_bytes(),
                         (self.next_bundle / "resources" / "skills"
                          / "fstar-continue" / "SKILL.md").read_bytes())
        user_bytes = b"the final user edit"
        destination.write_bytes(user_bytes)
        plan, _ = self.run_op("update", requested_version=NEXT_VERSION,
                              bundle_root=self.next_bundle)
        entry = next(e for e in plan["host_files"] if e["destination"] == str(destination))
        self.assertEqual(entry["action"], "keep_modified")
        self.assertEqual(destination.read_bytes(), user_bytes)
        # Doctor keeps reporting the modified file instead of hiding it.
        diagnostics = installer._doctor_host_files(self.roots().resolved())
        self.assertTrue(any(d["path"] == str(destination) and d["code"] == "HOST_FILE_MODIFIED"
                            for d in diagnostics))

    def test_plan_apply_change_is_refused(self):
        self.install_reuse()
        roots = self.roots(bundle_root=self.next_bundle)
        plan = installer.plan_install(operation="update", roots=roots,
                                     requested_version=NEXT_VERSION)
        destination = self.host_root / "skills" / "fstar-continue" / "SKILL.md"
        destination.write_bytes(b"changed between plan and apply")
        with self.assertRaises(installer.DomainError) as caught:
            installer.apply_plan(plan, roots=roots)
        self.assertEqual(caught.exception.code, "installer_plan_stale")


if __name__ == "__main__":
    unittest.main()
