"""Targeted regression tests for the retired fstar-doc skill (task merge-fstar-doc).

A-001: no fstar-doc references remain in the packaged resources or README;
       the relocated duties (user-supplied planning-document storage in
       fstar-plan, document-edit coordination and deliverables registry in
       fstar-execute) are explicitly covered.
A-002: the planning-review extension set never gated fstar-doc; retained
       members keep working, and an old task.json whose historical grant
       listed members that are still valid loads and archives without a
       forced schema migration.
A-003: the package manifest has no fstar-doc entries, and an update from an
       install that carried a fstar-doc skill copy retires the stale file
       (removed when unmodified, kept-and-reported when user-modified) —
       never silently kept as an active skill.

All installer tests run against temporary roots only (same contract as
tests/test_installer.py): no real host settings, user root, or network.
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
from fstar.models import DomainError  # noqa: E402
from fstar.store import TaskStore  # noqa: E402
from fstar.tasks import TaskService, EXTENSIONS, source_snapshot  # noqa: E402

RESOURCES = REPO / "resources"


def _sha_bytes(payload: bytes) -> str:
    import hashlib
    return hashlib.sha256(payload).hexdigest()


class InstallerCase(unittest.TestCase):
    """Same temp-root contract as tests/test_installer.py."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="fstar-doc-retirement-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.user_root = self.tmp / "user" / ".fstar"
        self.runtime_root = self.tmp / "user" / ".fstar" / "runtime"
        self.host_root = self.tmp / "host" / "claude"
        self.project_root = self.tmp / "project"
        for path in (self.user_root, self.runtime_root, self.host_root, self.project_root):
            path.mkdir(parents=True, exist_ok=True)

    def roots(self, **kwargs) -> installer.Roots:
        return installer.Roots(
            user_root=self.user_root,
            runtime_root=self.runtime_root,
            project_root=kwargs.get("project_root", self.project_root),
            host_roots=kwargs.get("host_roots", {"claude": self.host_root}),
            bundle_root=REPO,
        )

    def install(self, **kwargs):
        roots = self.roots()
        plan = installer.plan_install(operation="install", roots=roots, **kwargs)
        return installer.apply_plan(plan, roots=roots)


class CoreCase(unittest.TestCase):
    """Same temp-root contract as tests/test_core.py."""

    class Clock:
        def __init__(self):
            self.now = "2026-11-23T00:00:00+00:00"

        def __call__(self):
            return self.now

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.project = root / "project"
        self.project.mkdir()
        (self.project / ".fstar").mkdir()
        (self.project / ".fstar" / ".schema-version").write_text("1\n")
        self.store = TaskStore(self.project, user_home=root / "user", runtime_root=root / "runtime")
        self.clock = CoreCase.Clock()
        self.service = TaskService(self.store, clock=self.clock)
        self.agent = {"role": "agent", "id": "coordinator", "session": "s1"}
        self.user = {"role": "user", "id": "user", "session": "s1"}

    def source(self, ref, source_type="command", actor=None, archived=False):
        task = self.store.read(ref, archived=archived)
        return {"source_id": "source-" + task["id"], "type": source_type,
                "at": self.clock(), "actor": actor or self.user,
                "reference": "prompt:42", "quote": "批准" if source_type == "conversation" else "",
                "scope": "task", "validates": source_snapshot(task)}


class TestNoFstarDocReferences(unittest.TestCase):
    """A-001: resources and README carry zero fstar-doc references."""

    def _search(self, root: Path):
        hits = []
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix in {".md", ".json", ".cjs", ".py"} and "archive" not in path.parts:
                if "fstar-doc" in path.read_text(encoding="utf-8", errors="ignore"):
                    hits.append(str(path))
        return hits

    def test_resources_and_readme_have_no_fstar_doc_references(self):
        self.assertEqual([], self._search(RESOURCES))
        self.assertNotIn("fstar-doc", (REPO / "README.md").read_text(encoding="utf-8"))

    def test_skill_directory_removed_and_checklist_kept(self):
        self.assertFalse((RESOURCES / "skills" / "fstar-doc").exists())
        self.assertEqual(sorted(p.name for p in (RESOURCES / "skills").iterdir()), [
            "fstar-archive", "fstar-check", "fstar-clarify", "fstar-continue",
            "fstar-debug", "fstar-execute", "fstar-help", "fstar-init",
            "fstar-learn", "fstar-plan"])
        # document-checklist.md stays: fstar-check and fstar-editor still use it.
        checklist = RESOURCES / "references" / "document-checklist.md"
        self.assertTrue(checklist.is_file(), checklist)
        check_skill = (RESOURCES / "skills" / "fstar-check" / "SKILL.md").read_text(encoding="utf-8")
        editor_card = (RESOURCES / "agents" / "fstar-editor.md").read_text(encoding="utf-8")
        self.assertIn("document-checklist.md", check_skill + editor_card)

    def test_relocated_duties_are_explicitly_covered(self):
        plan = (RESOURCES / "skills" / "fstar-plan" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("user-supplied planning document", plan)
        self.assertIn("preserve their content as the authority", plan)
        self.assertIn("item markers, artifact_map markers", plan)
        self.assertIn("author = the user", plan)
        self.assertIn("unknown facts stay 待确认", plan)
        execute = (RESOURCES / "skills" / "fstar-execute" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("route it through fstar-plan storage first", execute)
        self.assertIn("deliverables registry", execute)
        self.assertIn("Queue edits to the same file", execute)
        self.assertIn("reject a stale-baseline overwrite", execute)
        routing = (RESOURCES / "runtime" / "routing.md").read_text(encoding="utf-8")
        self.assertIn("user-supplied planning document must be stored into the current task directory", routing)
        self.assertIn("storing a user-supplied planning document through `fstar-plan`", routing)
        clarify = (RESOURCES / "skills" / "fstar-clarify" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("use `fstar-plan`", clarify)


class TestExtensionMappingAndCompatibility(CoreCase):
    """A-002: planning-review extension keeps working without fstar-doc."""

    def test_extension_set_never_gated_fstar_doc(self):
        # The member set in src/fstar/tasks.py never referenced fstar-doc;
        # only routing.md prose did. Removing the skill changes no member.
        self.assertEqual(EXTENSIONS["planning-review"],
                         {"clarify", "prd", "design", "plan", "editor", "doc-check"})

    def test_planning_review_enables_and_lists_retained_members(self):
        self.service.create(name="root", title="Root", description="d", actor=self.agent, session_id="s1")
        record = self.service.enable_extension("root", authorization={
            "id": "planning-review", "scope": "full",
            "source": self.source("root")}, actor=self.user)
        self.assertEqual(record["included"],
                         sorted({"clarify", "prd", "design", "plan", "editor", "doc-check"}))
        # A custom grant over retained members still validates.
        custom = self.service.enable_extension("root", authorization={
            "id": "planning-review", "scope": "custom",
            "included": ["clarify", "doc-check"], "excluded": ["editor"],
            "source": self.source("root")}, actor=self.user)
        self.assertEqual(custom["included"], ["clarify", "doc-check"])
        task = self.store.read("root")
        self.assertEqual([r["id"] for r in task["extensions"]], ["planning-review"])

    def test_document_storage_with_custom_grant_does_not_require_plan(self):
        from fstar.extensions import grants, includes
        self.service.create(name="root", title="Root", description="d", actor=self.agent, session_id="s1")
        self.service.enable_extension("root", authorization={
            "id": "planning-review", "scope": "custom",
            "included": ["prd", "design"], "excluded": ["plan"],
            "source": self.source("root")}, actor=self.user)
        authorized = grants(self.store.read("root")["extensions"])
        self.assertTrue(includes(authorized, "planning-review", "prd"))
        self.assertTrue(includes(authorized, "planning-review", "design"))
        self.assertFalse(includes(authorized, "planning-review", "plan"))
        routing = (RESOURCES / "runtime" / "routing.md").read_text(encoding="utf-8")
        plan = (RESOURCES / "skills" / "fstar-plan" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("does not require `plan` for a `prd` or `design` document", routing)
        self.assertIn("Creating or updating a plan through `fstar-plan` requires `plan`", routing)
        self.assertIn("even if `plan` is excluded or unlisted", plan)
        self.assertIn("including for simple tasks or before requirements review", plan)
        self.assertIn("If the corresponding member is absent, negotiate it before storage", plan)

    def test_old_task_with_historical_grant_loads_and_archives(self):
        # An old task.json whose planning-review grant listed members that
        # are all still valid (a pre-removal install recorded the same set —
        # fstar-doc was never a member) loads and archives unchanged: no
        # schema migration is forced.
        self.service.create(name="old", title="Old", description="d", actor=self.agent, session_id="s1")
        task_dir = self.store.resolve("old")
        task = self.store._read_path(task_dir / "task.json")
        task["extensions"].append({
            "id": "planning-review", "enabled_at": self.clock(),
            "source": {"type": "command", "actor": self.user, "reference": {}},
            "scope": "full",
            "included": ["clarify", "prd", "design", "plan", "editor", "doc-check"],
            "excluded": [], "reason": "historical grant"})
        self.store.write(task_dir, task)
        # Loads without migration.
        reread = self.store.read("old")
        self.assertEqual(reread["extensions"][0]["included"],
                         ["clarify", "prd", "design", "plan", "editor", "doc-check"])
        # Completes and archives through the normal flow. The full planning-
        # review grant includes prd/design, so start requires an artifact map;
        # acceptance requires a final check over a real artifact, delivery
        # files, and a report (mirroring tests/test_core.py fixtures).
        (self.project / "doc").mkdir(exist_ok=True)
        (self.project / "doc" / "prd.md").write_text(
            "<!-- R1:start -->\nrequirements\n<!-- R1:end -->\n")
        (self.project / "src.py").write_text("value = 1\n")
        (self.project / "report.md").write_text("all passed\n")
        with self.store.transaction():
            task = self.store.read("old")
            task["meta"]["templates"] = {"artifact_map": {"doc/prd.md": {
                "R-001": {"start_marker": "<!-- R1:start -->", "end_marker": "<!-- R1:end -->"}}}}
            self.store.write(self.store.resolve("old"), task)
        self.service.start("old", actor=self.user, confirmation=self.source("old"), session_id="s1")
        lease = self.service.acquire_lease("old", holder="coordinator", role="coordinator", actor=self.agent)
        from fstar.evidence import file_digest
        snapshot = self.service.evidence.snapshot("old", artifact="doc/prd.md", items=["R-001"])
        delivery = self.service.evidence.delivery_snapshot(["src.py"])
        self.service.evidence.record("old", lease_token=lease["token"], evidence={
            "kind": "check", "producer": {"role": "check", "id": "checker", "session_id": "c1"},
            "validates": [snapshot], "run_id": "run-1", "environment": {"python": "3.12"},
            "report": {"path": "report.md", "sha256": file_digest(self.project / "report.md")},
            "delivery": delivery,
            "scope": "final", "read_only": True, "items": [
                {"requirement_ids": ["R-001"], "plan_item": "P-1", "test_refs": ["t.py"],
                 "command": "python t.py", "result": "passed", "exit_code": 0,
                 "log_refs": ["report.md"], "duration": 1.0, "retries": 0}]})
        self.service.release_lease("old", token=lease["token"], reason="done")
        self.service.enter_awaiting_acceptance("old", actor=self.agent)
        accepted = self.service.accept("old", actor=self.user, confirmation=self.source("old"))
        self.assertEqual("completed", accepted["phase"])
        archived = self.service.archive("old", actor=self.user, confirmation=self.source("old"))
        self.assertEqual("completed", archived["task"]["phase"])
        self.assertIn("archive", archived["path"])
        self.assertFalse((task_dir / "task.json").exists())


class TestManifestAndStaleRetirement(InstallerCase):
    """A-003: manifest truthful; update from an old install retires fstar-doc."""

    def _manifest_records(self):
        manifest = json.loads((self.user_root / ".install-manifest.json").read_text())
        return {record["destination"]: record for record in manifest["host_file_entries"]}

    def _index_ids(self):
        index = json.loads((self.user_root / "entry-index.json").read_text())
        return {entry["id"] for entry in index["entries"]}

    def _add_retired_fstar_doc_record(self, *, content=b"retired fstar-doc skill", create_file=True) -> Path:
        """Simulate an install from the pre-removal package: it recorded an
        owned host-file entry for resources/skills/fstar-doc/SKILL.md, and
        the copy exists in the host skills directory."""
        self.install(hosts=["claude"])
        target = self.host_root / "skills" / "fstar-doc" / "SKILL.md"
        if create_file:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        destination = str(target.resolve())
        manifest_path = self.user_root / ".install-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["host_file_entries"].append({
            "host": "claude",
            "kind": "skill",
            "source": "resources/skills/fstar-doc/SKILL.md",
            "destination": destination,
            "installed_hash": _sha_bytes(content) if create_file else "0" * 64,
            "version": str(installer.load_bundle_manifest(REPO)["resource_version"]),
            "operation_id": "op-doc00000001",
            "ownership": "owned",
        })
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        index_path = self.user_root / "entry-index.json"
        index = json.loads(index_path.read_text())
        index["entries"].append({
            "id": "host-file:%s" % destination,
            "host": "claude", "kind": "skill", "source": "package",
            "installed_path": destination, "ownership": "owned",
            "status": "active",
            "version": str(installer.load_bundle_manifest(REPO)["resource_version"]),
        })
        index_path.write_text(json.dumps(index), encoding="utf-8")
        return target

    def _update(self, policy="keep"):
        roots = self.roots()
        plan = installer.plan_install(operation="update", roots=roots, conflict_policy=policy)
        return plan, installer.apply_plan(plan, roots=roots)

    def test_doctor_reports_current_and_expected_skill_count(self):
        self.install(hosts=["claude"])
        report = installer.doctor(roots=self.roots())
        self.assertEqual(10, report["counts"]["skills"])
        self.assertEqual(10, report["expected_counts"]["skills"])
        self.assertTrue(report["healthy"], report["diagnostics"])

    def test_manifest_has_no_fstar_doc_entries(self):
        self.install(hosts=["claude"])
        manifest = json.loads((self.user_root / ".install-manifest.json").read_text())
        for record in manifest["host_file_entries"]:
            self.assertNotIn("fstar-doc", record["source"])
        bundle = json.loads((REPO / "resources" / "package-assets.json").read_text())
        for asset in bundle["files"]:
            self.assertNotIn("fstar-doc", asset["source"])
            self.assertNotIn("fstar-doc", asset["destination"])
        self.assertFalse((self.host_root / "skills" / "fstar-doc").exists())

    def test_update_from_old_install_removes_unmodified_fstar_doc(self):
        target = self._add_retired_fstar_doc_record()
        destination = str(target.resolve())
        plan, result = self._update()
        entry = next(e for e in plan["host_files"] if e["destination"] == destination)
        self.assertTrue(entry["stale"])
        self.assertEqual(entry["action"], "remove_owned")
        removed = [r for r in result["applied"]["removed"] if r.get("host")]
        self.assertEqual([r["path"] for r in removed], [destination])
        self.assertFalse(target.exists())
        self.assertFalse((self.host_root / "skills" / "fstar-doc").exists())
        self.assertNotIn(destination, self._manifest_records())
        self.assertNotIn("host-file:%s" % destination, self._index_ids())
        report = installer.doctor(roots=self.roots())
        self.assertTrue(report["healthy"], report["diagnostics"])

    def test_update_from_old_install_keeps_user_modified_fstar_doc_and_reports(self):
        target = self._add_retired_fstar_doc_record()
        target.write_text("user edited the retired skill", encoding="utf-8")
        destination = str(target.resolve())
        plan, result = self._update()
        entry = next(e for e in plan["host_files"] if e["destination"] == destination)
        self.assertTrue(entry["stale"])
        self.assertEqual(entry["action"], "keep_modified")
        kept = [k for k in result["applied"]["kept"] if k["path"] == destination]
        self.assertEqual([k["action"] for k in kept], ["keep_modified"])
        self.assertEqual(target.read_text(), "user edited the retired skill")
        # Kept but never silently active: doctor keeps reporting the file.
        self.assertIn(destination, self._manifest_records())
        codes = [d["code"] for d in installer.doctor(roots=self.roots())["diagnostics"]]
        self.assertIn("HOST_FILE_MODIFIED", codes)

    def test_update_from_old_install_drops_missing_fstar_doc_record(self):
        target = self._add_retired_fstar_doc_record(create_file=False)
        destination = str(target.resolve())
        plan, result = self._update()
        entry = next(e for e in plan["host_files"] if e["destination"] == destination)
        self.assertTrue(entry["stale"])
        self.assertEqual(entry["action"], "remove_missing")
        self.assertNotIn(destination, self._manifest_records())


if __name__ == "__main__":
    unittest.main()
