"""P-004 regressions: branch binding and QA task location (PRD R-006, D-006).

start()/create() record the ACTUAL git branch/worktree/base of the repo the
task lives in; a detached HEAD is recorded honestly with its commit and NO
fabricated branch name. ``locate`` resolves "which task is this branch?" in
the defined order (explicit ref > compatible session pointer > unique
project/worktree/branch candidate), lists ambiguous candidates (active,
completed, and archived) instead of auto-selecting, never reopens anything,
and never checks out a branch. Only temporary git repos and temporary
user/runtime roots are used.
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

from fstar.models import DomainError
from fstar.project import initialize_project
from fstar.store import TaskStore
from fstar.tasks import TaskService, source_snapshot


def _git(repo: Path, *args) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True,
                            capture_output=True, text=True)
    return result.stdout.strip()


def _make_repo(path: Path, *, branch: str = "main") -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", branch, str(path)], check=True)
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "T")
    (path / "file.txt").write_text("x\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "init")
    return path


class BranchBindingCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.user_root = (self.base / "user").resolve()
        self.user_root.mkdir()
        self.runtime = self.base / "runtime"
        self.actor = {"role": "agent", "id": "coordinator", "session": "s1"}
        self.user = {"role": "user", "id": "user", "session": "s1"}

    def _repo(self, name, branch="main"):
        repo = _make_repo((self.base / name).resolve(), branch=branch)
        initialize_project(repo, self.user_root, storage="project-shared")
        return repo

    def _service(self, repo, clock=None):
        store = TaskStore(repo, user_home=self.user_root, runtime_root=self.runtime)
        return store, TaskService(store, clock=clock) if clock else TaskService(store)

    def _source(self, task):
        return {"source_id": "s-%s" % str(uuid.uuid4())[:8], "type": "command",
                "at": "2026-11-20T10:00:00Z", "actor": self.user,
                "reference": "prompt:1", "quote": "", "scope": "task",
                "validates": source_snapshot(task)}

    def _checkout(self, repo, branch, create=False):
        args = ["checkout", "-q"] + (["-b"] if create else []) + [branch]
        subprocess.run(["git", "-C", str(repo), *args], check=True,
                       capture_output=True)

    def _start(self, repo, name):
        store = TaskStore(repo, user_home=self.user_root, runtime_root=self.runtime)
        service = TaskService(store)
        return service.start(name, actor=self.user,
                             confirmation=self._source(store.read(name)),
                             session_id="s1")

    # -- binding -------------------------------------------------------------

    def test_start_records_actual_branch_and_worktree(self):
        repo = self._repo("proj")
        self._checkout(repo, "feat/x", create=True)
        store, service = self._service(repo)
        service.create(name="root", title="R", description="", actor=self.actor)
        task = self._start(repo, "root")
        self.assertEqual("feat/x", task["branch"])
        self.assertEqual(str(repo), task["worktree_path"])
        self.assertTrue(task["commit"])
        started = [e for e in task["events"] if e["type"] == "started"][-1]
        self.assertEqual("feat/x", started["data"]["branch"])
        self.assertFalse(started["data"]["detached"])

    def test_start_never_overwrites_explicit_branch_values(self):
        repo = self._repo("proj")
        store, service = self._service(repo)
        service.create(name="root", title="R", description="", actor=self.actor)
        with store.transaction():
            task = store.read("root")
            task["branch"] = "explicit/branch"
            task["worktree_path"] = "/elsewhere"
            store.write(store.resolve("root"), task)
        task = self._start(repo, "root")
        self.assertEqual("explicit/branch", task["branch"])
        self.assertEqual("/elsewhere", task["worktree_path"])

    def test_detached_head_is_recorded_honestly(self):
        repo = self._repo("proj")
        head = _git(repo, "rev-parse", "HEAD")
        subprocess.run(["git", "-C", str(repo), "checkout", "-q", "--detach", "HEAD"],
                       check=True)
        store, service = self._service(repo)
        service.create(name="root", title="R", description="", actor=self.actor)
        task = self._start(repo, "root")
        self.assertEqual("", task["branch"])
        self.assertEqual(head, task["commit"])
        self.assertTrue(task["meta"]["git_binding"]["detached"])
        started = [e for e in task["events"] if e["type"] == "started"][-1]
        self.assertTrue(started["data"]["detached"])

    def test_non_git_project_leaves_branch_fields_empty(self):
        plain = self.base / "plain"
        plain.mkdir()
        initialize_project(plain, self.user_root, storage="project-shared")
        store = TaskStore(plain, user_home=self.user_root, runtime_root=self.runtime)
        service = TaskService(store)
        service.create(name="root", title="R", description="", actor=self.actor)
        task = service.start("root", actor=self.user,
                             confirmation=self._source(store.read("root")))
        self.assertEqual("", task["branch"])
        self.assertEqual("", task["worktree_path"])
        self.assertNotIn("git_binding", task["meta"])

    # -- location ------------------------------------------------------------

    def test_same_branch_name_resolves_per_project(self):
        a = self._repo("proj-a")
        b = self._repo("proj-b")
        for repo in (a, b):
            self._checkout(repo, "feat/shared-name", create=True)
            store = TaskStore(repo, user_home=self.user_root, runtime_root=self.runtime)
            service = TaskService(store)
            service.create(name="t", title="T", description="", actor=self.actor)
            self._start(repo, "t")
        for repo in (a, b):
            service = self._service(repo)[1]
            result = service.locate(branch="feat/shared-name")
            self.assertEqual("found", result["status"])
            self.assertEqual("t", result["task"]["ref"])
            self.assertEqual(str(repo), result["task"]["worktree"])

    def test_same_branch_in_two_worktrees_of_one_repo_lists_both(self):
        repo = self._repo("main-repo")
        # Git refuses checking the same branch out in two worktrees; the
        # scenario is a detached-HEAD worktree on the same commit, which the
        # recorded branch on the TASK models instead. Both tasks therefore
        # record branch "feat/two" with their OWN worktree_path.
        wt = (self.base / "wt2").resolve()
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "--detach",
                        "-q", str(wt)], check=True, capture_output=True)
        for project_root, name, branch in ((repo, "root", "feat/two"),
                                           (wt, "root", "feat/two")):
            initialize_project(project_root, self.user_root, storage="project-shared")
            store = TaskStore(project_root, user_home=self.user_root,
                              runtime_root=self.runtime)
            service = TaskService(store)
            service.create(name=name, title=name, description="", actor=self.actor)
            self._start(project_root, name)
            with store.transaction():
                task = store.read(name)
                task["branch"] = branch
                store.write(store.resolve(name), task)
        # From EITHER worktree the same branch matches two tasks -> ambiguity,
        # each candidate showing its own worktree so the user can pick.
        for project_root in (repo, wt):
            service = self._service(project_root)[1]
            result = service.locate(branch="feat/two")
            self.assertEqual("ambiguous", result["status"])
            self.assertEqual(2, len(result["candidates"]))
            worktrees = {c["worktree"] for c in result["candidates"]}
            self.assertEqual({str(repo), str(wt)}, worktrees)

    def test_worktree_filter_narrows_to_unique_candidate(self):
        repo = self._repo("main-repo")
        wt = (self.base / "wt2").resolve()
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "--detach",
                        "-q", str(wt)], check=True, capture_output=True)
        initialize_project(wt, self.user_root, storage="project-shared")
        store = TaskStore(wt, user_home=self.user_root, runtime_root=self.runtime)
        service = TaskService(store)
        service.create(name="in-wt", title="W", description="", actor=self.actor)
        self._start(wt, "in-wt")
        # The detached worktree honestly records no branch; bind it manually
        # as a task record would after a real checkout, keeping its worktree.
        with store.transaction():
            task = store.read("in-wt")
            task["branch"] = "feat/two"
            task["worktree_path"] = str(wt)
            store.write(store.resolve("in-wt"), task)
        result = service.locate(branch="feat/two", worktree=str(wt))
        self.assertEqual("found", result["status"])
        self.assertEqual("in-wt", result["task"]["ref"])

    def test_multiple_tasks_on_same_branch_list_active_completed_archived(self):
        repo = self._repo("proj")
        self._checkout(repo, "feat/busy", create=True)
        store, service = self._service(repo)
        for name in ("active", "done"):
            service.create(name=name, title=name, description="", actor=self.actor)
        # Completed match: bind branch manually, then complete the lifecycle.
        with store.transaction():
            task = store.read("done")
            task["branch"] = "feat/busy"
            task["worktree_path"] = str(repo)
            task["phase"] = "completed"
            task["completedAt"] = "2026-11-20T10:00:00Z"
            task["acceptance"] = {"evidence_refs": [], "state": "valid"}
            store.write(store.resolve("done"), task)
        # Archived match: a task.json placed under the archive with the branch.
        month = store.archive_root / "2026-11"
        month.mkdir(parents=True)
        archived = store.read("done")
        archived["id"] = str(uuid.uuid4())
        archived["name"] = "archived-one"
        archived["branch"] = "feat/busy"
        archived_dir = month / "archived-one"
        archived_dir.mkdir()
        (archived_dir / "task.json").write_text(json.dumps(archived), encoding="utf-8")
        self._start(repo, "active")
        result = service.locate(branch="feat/busy")
        self.assertEqual("ambiguous", result["status"])
        refs = {c["ref"]: c for c in result["candidates"]}
        self.assertIn("active", refs)
        self.assertIn("done", refs)
        self.assertIn("archived-one", refs)
        self.assertTrue(refs["done"]["completed"])
        self.assertTrue(refs["archived-one"]["archived"])
        self.assertFalse(refs["active"]["completed"])

    def test_archived_match_is_reported_never_reopened(self):
        repo = self._repo("proj")
        store, service = self._service(repo)
        service.create(name="root", title="R", description="", actor=self.actor)
        with store.transaction():
            task = store.read("root")
            task["branch"] = "feat/old"
            store.write(store.resolve("root"), task)
        # Simulate the archived tree (archive validation is covered elsewhere):
        # the task moves into the archive with its branch intact, exactly as
        # a real archive relocates the whole directory.
        month = store.archive_root / "2026-11"
        month.mkdir(parents=True)
        archived_dir = month / "root"
        import shutil
        shutil.move(str(store.resolve("root")), str(archived_dir))
        result = service.locate(branch="feat/old")
        self.assertEqual("found", result["status"])
        self.assertTrue(result["task"]["archived"])
        self.assertEqual("feat/old", store.read("root", archived=True)["branch"])
        # The on-disk archived task is untouched: phase and fields unchanged.
        self.assertEqual("planning", store.read("root", archived=True)["phase"])

    def test_no_task_found_is_a_clear_negative(self):
        repo = self._repo("proj")
        service = self._service(repo)[1]
        result = service.locate(branch="does/not-exist")
        self.assertEqual("no_task", result["status"])

    def test_explicit_ref_beats_session_pointer_and_candidates(self):
        repo = self._repo("proj")
        self._checkout(repo, "feat/a", create=True)
        store, service = self._service(repo)
        service.create(name="first", title="F", description="", actor=self.actor,
                       session_id="qa-session")
        self._start(repo, "first")
        service.create(name="second", title="S", description="", actor=self.actor)
        self._start(repo, "second")
        with store.transaction():
            task = store.read("second")
            task["branch"] = "feat/a"
            store.write(store.resolve("second"), task)
        # Session pointer and a branch candidate both point at "first"; the
        # explicit ref still wins.
        result = service.locate(ref="second", session_id="qa-session",
                                branch="feat/a")
        self.assertEqual("found", result["status"])
        self.assertEqual("explicit_ref", result["via"])
        self.assertEqual("second", result["task"]["ref"])

    def test_session_pointer_beats_branch_candidates(self):
        repo = self._repo("proj")
        self._checkout(repo, "feat/a", create=True)
        store, service = self._service(repo)
        service.create(name="first", title="F", description="", actor=self.actor,
                       session_id="qa-session")
        self._start(repo, "first")
        service.create(name="second", title="S", description="", actor=self.actor)
        self._start(repo, "second")
        result = service.locate(session_id="qa-session", branch="feat/a")
        self.assertEqual("found", result["status"])
        self.assertEqual("session_pointer", result["via"])
        self.assertEqual("first", result["task"]["ref"])

    def test_session_pointer_mismatch_falls_through_to_candidates(self):
        repo = self._repo("proj")
        self._checkout(repo, "feat/a", create=True)
        store, service = self._service(repo)
        # A pointer recorded for a DIFFERENT project root (a stale pointer
        # carried from another worktree) must not win over real candidates.
        pointer = {"project": str(self.base / "other-project"), "task_id": "ghost",
                   "task_path": str(self.base / "other-project" / ".fstar" / "tasks" / "ghost")}
        sessions = store.project_runtime / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        digest = __import__("hashlib").sha256(b"qa-session").hexdigest()
        (sessions / (digest + ".json")).write_text(json.dumps(pointer), encoding="utf-8")
        service.create(name="real", title="R", description="", actor=self.actor)
        self._start(repo, "real")
        result = service.locate(session_id="qa-session", branch="feat/a")
        self.assertEqual("found", result["status"])
        self.assertEqual("unique_candidate", result["via"])
        self.assertEqual("real", result["task"]["ref"])

    def test_session_pointer_branch_mismatch_falls_through(self):
        repo = self._repo("proj")
        self._checkout(repo, "feat/a", create=True)
        store, service = self._service(repo)
        service.create(name="first", title="F", description="", actor=self.actor,
                       session_id="qa-session")
        self._start(repo, "first")
        self._checkout(repo, "feat/b", create=True)
        service.create(name="second", title="S", description="", actor=self.actor)
        self._start(repo, "second")
        result = service.locate(session_id="qa-session", branch="feat/b")
        self.assertEqual("found", result["status"])
        self.assertEqual("unique_candidate", result["via"])
        self.assertEqual("second", result["task"]["ref"])

    def test_locate_never_reopens_or_mutates(self):
        repo = self._repo("proj")
        store, service = self._service(repo)
        service.create(name="root", title="R", description="", actor=self.actor)
        self._start(repo, "root")
        with store.transaction():
            task = store.read("root")
            task["phase"] = "completed"
            task["completedAt"] = "2026-11-20T10:00:00Z"
            store.write(store.resolve("root"), task)
        result = service.locate(branch="main")
        self.assertEqual("found", result["status"])
        self.assertTrue(result["task"]["completed"])
        self.assertEqual("completed", store.read("root")["phase"])

    # -- CLI ------------------------------------------------------------------

    def _run_cli(self, repo, *argv):
        from fstar.cli import main
        args = ["--json", "--user-data-root", str(self.user_root),
                "--runtime-root", str(self.runtime), "--project", str(repo), *argv]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(args)
        return code, out.getvalue() + err.getvalue()

    def test_cli_locate_branch(self):
        repo = self._repo("proj")
        self._checkout(repo, "feat/cli", create=True)
        code, out = self._run_cli(repo, "task", "create", "T", "--name", "root")
        self.assertEqual(0, code, out)
        code, out = self._run_cli(repo, "start", "root", "--confirm-user")
        self.assertEqual(0, code, out)
        code, out = self._run_cli(repo, "task", "locate", "--branch", "feat/cli")
        self.assertEqual(0, code, out)
        self.assertIn('"via": "unique_candidate"', out)
        self.assertIn('"ref": "root"', out)
        code, out = self._run_cli(repo, "task", "locate", "--branch", "nope")
        self.assertEqual(0, code)
        self.assertIn("no_task", out)

    def test_cli_locate_ambiguous_lists_candidates(self):
        repo = self._repo("proj")
        self._checkout(repo, "feat/cli", create=True)
        for name in ("one", "two"):
            code, out = self._run_cli(repo, "task", "create", name, "--name", name)
            self.assertEqual(0, code, out)
            code, out = self._run_cli(repo, "start", name, "--confirm-user")
            self.assertEqual(0, code, out)
        code, out = self._run_cli(repo, "task", "locate", "--branch", "feat/cli")
        self.assertEqual(0, code)
        self.assertIn("ambiguous", out)
        self.assertIn("several tasks match", out.lower())

    def test_cli_locate_requires_a_lookup_key(self):
        repo = self._repo("proj")
        code, out = self._run_cli(repo, "task", "locate")
        self.assertNotEqual(0, code)
        self.assertIn("task_required", out)

    def test_explicit_ref_finds_an_archived_task(self):
        # A completed/archived task stays findable for QA by its ref too;
        # the hit is reported as archived and nothing is reopened.
        repo = self._repo("proj")
        store, service = self._service(repo)
        service.create(name="old", title="O", description="", actor=self.actor)
        with store.transaction():
            task = store.read("old")
            task["phase"] = "completed"
            task["completedAt"] = "2026-11-20T10:00:00Z"
            task["acceptance"] = {"evidence_refs": [], "state": "valid"}
            store.write(store.resolve("old"), task)
        month = store.archive_root / "2026-11"
        month.mkdir(parents=True)
        import shutil
        shutil.move(str(store.resolve("old")), str(month / "old"))
        result = service.locate(ref="old")
        self.assertEqual("found", result["status"])
        self.assertEqual("explicit_ref", result["via"])
        self.assertTrue(result["task"]["archived"])
        self.assertEqual("completed", result["task"]["phase"])

    def test_unreadable_sibling_worktree_is_skipped(self):
        # A sibling worktree of the same repo with a corrupt task file must
        # not break the lookup for this project.
        repo = self._repo("main-repo")
        wt = (self.base / "wt-broken").resolve()
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "--detach",
                        "-q", str(wt)], check=True, capture_output=True)
        initialize_project(wt, self.user_root, storage="project-shared")
        broken = wt / ".fstar" / "tasks" / "broken"
        broken.mkdir(parents=True)
        (broken / "task.json").write_text("{oops", encoding="utf-8")
        store, service = self._service(repo)
        service.create(name="root", title="R", description="", actor=self.actor)
        self._start(repo, "root")
        result = service.locate(branch="main")
        self.assertEqual("found", result["status"])
        self.assertEqual("root", result["task"]["ref"])

    def test_locate_without_branch_is_an_honest_negative(self):
        # A lookup with no task ref, no valid session pointer and no branch
        # has no candidate set: matching every task in the project would
        # report an arbitrary task as "the" answer.
        repo = self._repo("proj")
        store, service = self._service(repo)
        service.create(name="only", title="O", description="", actor=self.actor)
        self._start(repo, "only")
        result = service.locate(session_id="unknown-session")
        self.assertEqual("no_task", result["status"])
        self.assertNotIn("candidates", result)
        empty = service.locate()
        self.assertEqual("no_task", empty["status"])
        self.assertNotIn("candidates", empty)

    def test_locate_branch_ignores_tasks_on_other_branches(self):
        repo = self._repo("proj")
        self._checkout(repo, "feat/one", create=True)
        store, service = self._service(repo)
        service.create(name="one", title="1", description="", actor=self.actor)
        self._start(repo, "one")
        self._checkout(repo, "feat/two", create=True)
        service.create(name="two", title="2", description="", actor=self.actor)
        self._start(repo, "two")
        result = service.locate(branch="feat/one")
        self.assertEqual("found", result["status"])
        self.assertEqual("one", result["task"]["ref"])
        self.assertEqual("feat/one", result["task"]["branch"])

    def test_no_auto_checkout_ever(self):
        # locate is read-only: after every lookup the repo branch is unchanged.
        repo = self._repo("proj")
        self._checkout(repo, "feat/stay", create=True)
        store, service = self._service(repo)
        service.create(name="root", title="R", description="", actor=self.actor)
        self._start(repo, "root")
        service.locate(branch="feat/stay")
        service.locate(ref="root")
        service.locate(session_id="s1")
        self.assertEqual("feat/stay", _git(repo, "rev-parse", "--abbrev-ref", "HEAD"))


if __name__ == "__main__":
    unittest.main()
