"""Global resource inspection, migration, and deferred reminders.

P-001/P-002 adapter over the installer's ownership/journal machinery:

- ``inspect_project`` (D-003 read-only half): reports the effective resource
  source, the global host-entry health, legacy per-project copies, and the
  resource pin. It performs ZERO writes anywhere (project, task state,
  resources, runtime).
- ``record_delivery`` / ``record_deferral`` / ``remind`` (D-003 explicit
  half): separate runtime writes keyed by project identity + target resource
  version + session id. ``remind`` is the coordinating operation: it decides
  and records the delivery in one step and returns whether the question may
  be shown; only a caller that received that result asks. Delivery records
  dedupe a migration prompt within one session; deferrals persist per
  (project, version) so the same target is not asked about again until the
  global target version changes. A failed write is reported
  (``recorded: False``) and never claimed as durable. The session hook calls
  none of these: it stays read-only.
- ``migration_preview`` / ``apply_migration`` (D-002): migration moves only
  files the installer provably owns at their recorded fingerprints
  (old project-level ``.claude`` copies that still match the recorded
  installed hash, plus the project pin/registration). Backups live in the
  user root's install-backups tree; the journal-based apply means a
  mid-migration failure restores what this run wrote. Re-running on a
  migrated project is a no-op. User-modified or unowned copies are kept and
  reported as conflicts; unrelated project files are never touched.

Resource migration never migrates the data schema: the ``migrate`` schema
command stays the only data-schema path and is not called from here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .installer import (
    Roots,
    _load_cache_manifest,
    _load_manifest_safe,
    _package_root,
    _plan_host_files,
    _reject_symlink_ancestors,
    _safe_relative,
    _sha256,
    _within,
    load_bundle_manifest,
    plan_install,
    resolve_resources,
    SUPPORTED_HOSTS,
)

DEFERRALS_SCHEMA = "fstar.resource-deferrals.v1"
DELIVERIES_SCHEMA = "fstar.resource-deliveries.v1"
MIGRATION_SCHEMA = "fstar.resource-migration.v1"


@dataclass(frozen=True)
class _Legacy:
    kind: str
    path: Path
    owned: bool
    matches_global: bool
    note: str


# ---------------------------------------------------------------------------
# read-only inspection


def inspect_project(*, project_root: Path, user_root: Path,
                    host_roots: Optional[Dict[str, Path]] = None,
                    bundle_root: Optional[Path] = None) -> dict:
    """Read-only legacy/global comparison for one project.

    Returns the effective source, the global host entry's integrity, and the
    per-project legacy copies that shadow the global delivery. No file,
    setting, runtime, or task-state write happens on this path.
    """
    resolved_project = project_root.expanduser().resolve()
    selection = resolve_resources(project_root=resolved_project, user_root=user_root,
                                  bundle_root=bundle_root, strict=False)
    bundle = load_bundle_manifest(bundle_root)
    target_version = str(bundle.get("resource_version", ""))
    host_root = None
    if host_roots and "claude" in host_roots:
        host_root = host_roots["claude"].expanduser().resolve()
    else:
        from .installer import default_host_root
        # The same normalization the explicit branch applies: the installer
        # records host destinations under the resolved host root, so an
        # unresolved default (/var/... vs /private/var/... on macOS) would
        # match no managed file and report a healthy global entry as empty.
        host_root = default_host_root(user_root).expanduser().resolve()
    legacy: List[_Legacy] = []
    manifest, manifest_problem = _load_manifest_safe(user_root)
    project_host = resolved_project / ".claude"
    owned_entries = [record for record in (manifest or {}).get("host_file_entries", [])
                     if record.get("ownership") == "owned"
                     and _within(Path(record.get("destination", "")).resolve(), project_host)]
    for record in owned_entries:
        destination = Path(record["destination"])
        present = destination.is_file() and not destination.is_symlink()
        current = _sha256(destination) if present else None
        # The recorded destination and the scanned project files are compared
        # on resolved paths: the same file must never be counted twice (once
        # as an owned copy, once as an unowned one) just because one of the
        # two spellings is not normalized.
        legacy.append(_Legacy(kind=record.get("kind") or "skill",
                              path=destination.resolve(),
                              owned=True, matches_global=bool(current == record.get("installed_hash")),
                              note="project-level copy recorded by an earlier project install"))
    # Unowned fstar-named copies in the project host root: never migrated,
    # reported so the user can decide (D-002 unknown-ownership conflict).
    if project_host.is_dir():
        for skill in sorted(project_host.glob("skills/fstar-*/SKILL.md")):
            if not any(item.path == skill for item in legacy):
                legacy.append(_Legacy(kind="skill", path=skill, owned=False,
                                      matches_global=False,
                                      note="unowned project copy; kept, needs user decision"))
        for agent in sorted(project_host.glob("agents/fstar-*.md")):
            if not any(item.path == agent for item in legacy):
                legacy.append(_Legacy(kind="agent", path=agent, owned=False,
                                      matches_global=False,
                                      note="unowned project copy; kept, needs user decision"))
    pin = None
    try:
        from .installer import _config_requested_version
        pin, _pin_source = _config_requested_version(resolved_project, user_root)
    except Exception:
        pin = None
    global_health = _global_health(host_root, manifest)
    migrated = bool(manifest) and not owned_entries and pin is None
    return {
        "schema": "fstar.resource-inspection.v1",
        "project_root": str(resolved_project),
        "effective": {"version": selection.version, "source": selection.source,
                      "root": str(selection.root), "problems": list(selection.problems)},
        "global_target_version": target_version,
        "global_health": global_health,
        "legacy": {"copies": [{"kind": item.kind, "path": str(item.path),
                               "owned": item.owned, "matches_global": item.matches_global,
                               "note": item.note} for item in legacy],
                   "pin": pin,
                   "count": len(legacy) + (1 if pin else 0)},
        "migrated": migrated,
        "manifest_problem": manifest_problem,
        "migration_recommended": bool((legacy or pin) and global_health.get("usable")),
        "read_only": True,
    }


def _global_health(host_root: Path, manifest: Optional[dict]) -> dict:
    """Is the global host entry present and unmodified? Read-only."""
    owned = [record for record in (manifest or {}).get("host_file_entries", [])
             if record.get("ownership") == "owned"
             and _within(Path(record.get("destination", "")).resolve(), host_root)]
    problems = []
    for record in owned:
        destination = Path(record["destination"])
        if destination.is_symlink() or not destination.is_file():
            problems.append({"path": str(destination), "reason": "missing"})
        elif _sha256(destination) != record.get("installed_hash"):
            problems.append({"path": str(destination), "reason": "modified"})
    settings_path = host_root / "settings.json"
    settings_present = settings_path.is_file()
    usable = bool(owned) and not problems
    if not owned:
        reason = "not_installed"
    elif problems:
        reason = "damaged"
    else:
        reason = "ok"
    return {"host_root": str(host_root), "managed_files": len(owned),
            "settings_registered": settings_present,
            "problems": problems, "reason": reason,
            "usable": usable}


# ---------------------------------------------------------------------------
# explicit runtime reminders (D-003)


def _deferrals_path(runtime_root: Path) -> Path:
    return runtime_root / "resource-deferrals.json"


def _deliveries_path(runtime_root: Path) -> Path:
    return runtime_root / "resource-deliveries.json"


def _read_runtime_doc(path: Path, schema: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": schema, "records": []}
    if not isinstance(value, dict) or not isinstance(value.get("records"), list):
        return {"schema": schema, "records": []}
    return value


def _atomic_write_runtime(path: Path, payload: dict) -> None:
    import os
    import uuid
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-%s" % uuid.uuid4().hex[:8])
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _reminder_lock(runtime_root: Path):
    """The lock that guards the reminder records against a lost update.

    The delivery/deferral files are read-modify-write documents, so two
    concurrent callers could both read "not yet shown" and both append:
    the question would then be offered twice in the same session. The lock
    (the same exclusive file lock the installer uses) makes the check and
    the write one atomic step.
    """
    from .installer import _Lock

    return _Lock(runtime_root / ".resource-reminders.lock")


def record_delivery(*, runtime_root: Path, project_identity: str, target_version: str,
                    session_id: str) -> dict:
    """Atomically mark a migration prompt as shown for one session.

    Returns ``shown`` False when this session already saw the prompt for this
    project+version. A write failure reports ``recorded: False`` — the caller
    must not claim dedupe it cannot guarantee.
    """
    path = _deliveries_path(runtime_root)
    try:
        with _reminder_lock(runtime_root):
            document = _read_runtime_doc(path, DELIVERIES_SCHEMA)
            for record in document["records"]:
                if (record.get("project_identity") == project_identity
                        and record.get("target_version") == target_version
                        and record.get("session_id") == session_id):
                    return {"shown": False, "recorded": True, "reason": "already_shown_this_session"}
            record = {"project_identity": project_identity, "target_version": target_version,
                      "session_id": session_id}
            document["records"].append(record)
            try:
                _atomic_write_runtime(path, document)
            except OSError as exc:
                return {"shown": True, "recorded": False, "reason": "runtime_write_failed",
                        "error": str(exc)}
    except OSError as exc:
        # The lock itself could not be taken: the dedupe cannot be
        # guaranteed, and that is reported instead of claimed.
        return {"shown": True, "recorded": False, "reason": "runtime_write_failed",
                "error": str(exc)}
    return {"shown": True, "recorded": True}


def clear_sessions(*, runtime_root: Path, project_identity: str, session_id: str) -> dict:
    """Drop one session's delivery records (clear/compact keeps the same
    session key by contract, so this is only needed for explicit resets)."""
    path = _deliveries_path(runtime_root)
    with _reminder_lock(runtime_root):
        document = _read_runtime_doc(path, DELIVERIES_SCHEMA)
        before = len(document["records"])
        document["records"] = [record for record in document["records"]
                               if not (record.get("project_identity") == project_identity
                                       and record.get("session_id") == session_id)]
        removed = before - len(document["records"])
        if removed:
            _atomic_write_runtime(path, document)
    return {"removed": removed, "recorded": True}


def record_deferral(*, runtime_root: Path, project_identity: str, target_version: str) -> dict:
    """Persist an explicit user deferral keyed by project+target version."""
    path = _deferrals_path(runtime_root)
    with _reminder_lock(runtime_root):
        document = _read_runtime_doc(path, DEFERRALS_SCHEMA)
        for record in document["records"]:
            if (record.get("project_identity") == project_identity
                    and record.get("target_version") == target_version):
                return {"recorded": True, "already_deferred": True}
        document["records"].append({"project_identity": project_identity,
                                    "target_version": target_version})
        _atomic_write_runtime(path, document)
    return {"recorded": True, "already_deferred": False}


def is_deferred(*, runtime_root: Path, project_identity: str, target_version: str) -> bool:
    document = _read_runtime_doc(_deferrals_path(runtime_root), DEFERRALS_SCHEMA)
    return any(record.get("project_identity") == project_identity
               and record.get("target_version") == target_version
               for record in document["records"])


def delivered_this_session(*, runtime_root: Path, project_identity: str,
                           target_version: str, session_id: str) -> bool:
    document = _read_runtime_doc(_deliveries_path(runtime_root), DELIVERIES_SCHEMA)
    return any(record.get("project_identity") == project_identity
               and record.get("target_version") == target_version
               and record.get("session_id") == session_id
               for record in document["records"])


def session_prompt_needed(*, runtime_root: Path, project_identity: str,
                          target_version: str, session_id: str) -> dict:
    """Decision for one session: ask again, already shown, or deferred."""
    if is_deferred(runtime_root=runtime_root, project_identity=project_identity,
                   target_version=target_version):
        return {"ask": False, "reason": "deferred_for_target_version"}
    if delivered_this_session(runtime_root=runtime_root, project_identity=project_identity,
                              target_version=target_version, session_id=session_id):
        return {"ask": False, "reason": "already_shown_this_session"}
    return {"ask": True, "reason": "new_target_version"}


def remind(*, project_root: Path, user_root: Path, runtime_root: Path,
           session_id: str, host_roots: Optional[Dict[str, Path]] = None,
           bundle_root: Optional[Path] = None) -> dict:
    """The explicit display operation for the migration question (D-003).

    This is the coordinating operation the read-only check never performs:
    it atomically checks and records the delivery for (project identity,
    target resource version, session id) and returns whether the question
    may be shown. Only a caller that received ``show: True`` may present it;
    ``recorded: False`` means the dedupe could not be persisted, and the
    caller must not claim it was.
    """
    report = inspect_project(project_root=project_root, user_root=user_root,
                             host_roots=host_roots, bundle_root=bundle_root)
    target = str(load_bundle_manifest(bundle_root).get("resource_version", ""))
    identity = _project_identity(project_root, user_root)
    base = {"project_identity": identity, "target_version": target,
            "session_id": session_id}
    decision = session_prompt_needed(runtime_root=runtime_root, project_identity=identity,
                                     target_version=target, session_id=session_id)
    if not decision["ask"]:
        result = dict(base)
        result.update({"show": False, "recorded": False, "reason": decision["reason"]})
        return result
    legacy = report.get("legacy", {})
    if not legacy.get("count"):
        result = dict(base)
        result.update({"show": False, "recorded": False, "reason": "nothing_to_migrate"})
        return result
    if not report.get("global_health", {}).get("usable"):
        result = dict(base)
        result.update({"show": False, "recorded": False,
                       "reason": "global_entry_unusable",
                       "global_health": report.get("global_health")})
        return result
    outcome = record_delivery(runtime_root=runtime_root, project_identity=identity,
                              target_version=target, session_id=session_id)
    result = dict(base)
    result.update({"show": bool(outcome.get("shown")), "recorded": bool(outcome.get("recorded")),
                   "reason": outcome.get("reason", "delivered"),
                   "legacy_count": legacy.get("count"),
                   "global_target_version": report.get("global_target_version")})
    if outcome.get("shown"):
        result["offer"] = (
            "This project still carries %d per-project fstar resource item(s) (copies/pin) "
            "while the shared global delivery (version %s) is healthy. Migrating (one confirmed "
            "`fstar resource-migrate`) backs the copies up, removes them, keeps tasks/specs/"
            "identity, and lets one global update serve every migrated project; modified or "
            "unowned files are kept and reported. Confirm to migrate, or defer."
            % (legacy.get("count", 0), report.get("global_target_version", "?")))
    if not outcome.get("recorded"):
        result["warning"] = ("the delivery record could not be written; the same question may "
                              "be shown again in this session")
    return result


# ---------------------------------------------------------------------------
# migration (D-002)


def migration_preview(*, project_root: Path, user_root: Path,
                      host_roots: Optional[Dict[str, Path]] = None,
                      bundle_root: Optional[Path] = None) -> dict:
    """The per-item migration plan. Pure read: ownership + fingerprint only.

    An item is migratable only when the installer owns the project copy AND
    its content still matches the recorded installed hash (the user did not
    modify it). Everything else is a conflict that stays on disk.
    """
    inspection = inspect_project(project_root=project_root, user_root=user_root,
                                 host_roots=host_roots, bundle_root=bundle_root)
    items = []
    for copy in inspection["legacy"]["copies"]:
        if copy["owned"] and not copy["matches_global"]:
            items.append({"kind": copy["kind"], "path": copy["path"], "action": "conflict",
                          "reason": "owned project copy was modified; kept"})
        elif copy["owned"]:
            items.append({"kind": copy["kind"], "path": copy["path"], "action": "migrate",
                          "reason": "owned and unmodified project copy"})
        else:
            items.append({"kind": copy["kind"], "path": copy["path"], "action": "keep",
                          "reason": copy["note"]})
    pin = inspection["legacy"]["pin"]
    if pin:
        items.append({"kind": "pin", "path": None, "action": "migrate",
                      "reason": "project resources pin (%s) follows the global target" % pin})
    return {"schema": MIGRATION_SCHEMA,
            "project_root": inspection["project_root"],
            "global_health": inspection["global_health"],
            "items": items,
            "conflicts": [item for item in items if item["action"] != "migrate"],
            "migratable_count": sum(1 for item in items if item["action"] == "migrate"),
            "safe": inspection["global_health"].get("usable", False)}


def recover_interrupted_migrations(*, user_root: Path, project_root: Path) -> List[dict]:
    """Restore what an interrupted earlier migration removed or rewrote.

    A migration that was killed mid-way leaves its journal under the user
    root's install-backups tree. The installer's own recovery pass only
    replays its own transactions and only inside the roots it resolves
    (the user root or the current host roots), so a project-level copy
    removed by a migration would stay lost and unreported. Here the
    recorded entries are restored before the next migration runs: a removed
    file comes back with its recorded content, and a rewritten file is put
    back only when the written state is still exactly what the migration
    wrote (a later user edit is never overwritten).
    """
    import base64
    from .installer import _atomic_write_bytes, _sha256_bytes

    resolved_project = project_root.expanduser().resolve()
    project_host = resolved_project / ".claude"
    backups = user_root / "install-backups"
    restored: List[dict] = []
    if not backups.is_dir():
        return restored
    for journal in sorted(backups.glob("mig-res-*/journal.jsonl")):
        entries = []
        try:
            lines = journal.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if "mkdir" in record or not record.get("path"):
                continue
            path = Path(record["path"])
            try:
                if not _within(path.resolve(), project_host):
                    continue
            except OSError:
                continue
            before = (base64.b64decode(record["before"])
                      if record.get("before") is not None else None)
            entries.append((path, before, record.get("after_sha")))
        changed = False
        for path, before, after_sha in entries:
            if before is None:
                continue
            try:
                current = path.read_bytes() if path.is_file() else None
            except OSError:
                continue
            if after_sha is None:
                if current is None:
                    _atomic_write_bytes(path, before)
                    restored.append({"path": str(path),
                                     "action": "restored_after_interrupted_migration"})
                    changed = True
                continue
            if current is not None and _sha256_bytes(current) == after_sha:
                _atomic_write_bytes(path, before)
                restored.append({"path": str(path),
                                 "action": "restored_after_interrupted_migration"})
                changed = True
        if changed:
            journal.unlink(missing_ok=True)
    return restored


def apply_migration(*, project_root: Path, user_root: Path, runtime_root: Path,
                    host_roots: Optional[Dict[str, Path]] = None,
                    bundle_root: Optional[Path] = None,
                    confirmation: Optional[dict] = None) -> dict:
    """Execute an approved migration. Requires explicit user confirmation.

    Steps: re-inspect (fingerprints may have changed since the preview),
    refuse when global is not healthy, back up + remove owned unmodified
    project copies through the journal, drop the project pin by writing the
    migrated marker, and record per-item results. Failures restore this
    run's writes via the installer journal. Not idempotent-unsafe: re-running
    on a migrated project reports zero remaining items.
    """
    if not isinstance(confirmation, dict) or not confirmation.get("approved"):
        raise ValueError("migration requires an explicit approved confirmation record")
    # An earlier migration that was killed mid-way is restored first, so the
    # approved migration always starts from the project's original state.
    recovered = recover_interrupted_migrations(user_root=user_root, project_root=project_root)
    preview = migration_preview(project_root=project_root, user_root=user_root,
                                host_roots=host_roots, bundle_root=bundle_root)
    if not preview["safe"]:
        return {"schema": MIGRATION_SCHEMA, "result": "blocked",
                "reason": "global host entry is missing or modified; resolve that first",
                "recovered": recovered, "items": preview["items"]}
    resolved_project = project_root.expanduser().resolve()
    manifest, _manifest_problem = _load_manifest_safe(user_root)
    project_host = resolved_project / ".claude"
    applied, kept, backups = [], [], {}
    import shutil
    import uuid
    from .installer import _TRANSACTION, _Journal, _atomic_write_json, _atomic_write_bytes
    from .installer import Roots, utc_now
    operation_id = "mig-res-%s" % uuid.uuid4().hex[:10]
    backup_root = user_root / "install-backups" / operation_id
    journal = _Journal(backup_root / "journal.jsonl", Roots(
        user_root=user_root, runtime_root=runtime_root,
        project_root=resolved_project,
        host_roots={"claude": host_roots["claude"] if host_roots and "claude" in host_roots
                    else Path.home() / ".claude"}))
    token = _TRANSACTION.set(journal)
    retired = []
    try:
        for record in (manifest or {}).get("host_file_entries", []):
            if record.get("ownership") != "owned":
                continue
            destination = Path(record.get("destination", ""))
            if not _within(destination.resolve(), project_host):
                continue
            if not destination.is_file() or destination.is_symlink():
                kept.append({"path": str(destination), "action": "keep_missing_or_link"})
                continue
            if _sha256(destination) != record.get("installed_hash"):
                kept.append({"path": str(destination), "action": "keep_modified"})
                continue
            backup = backup_root / destination.resolve().relative_to(project_host)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(destination), str(backup))
            backups[str(destination)] = str(backup)
            journal.record_remove(destination, destination.read_bytes())
            destination.unlink()
            applied.append({"path": str(destination), "backup": str(backup)})
            retired.append(str(destination))
        # Ownership handoff: the installer no longer owns a file it removed,
        # so its ownership record must leave the manifest too. A stale record
        # would keep the project looking legacy forever (a fresh session
        # would offer the migration again) and would report the removed file
        # as a modified copy. Only the records of files this run removed are
        # retired; every other record (global copies, other hosts, user
        # files) stays untouched.
        if retired and manifest is not None:
            updated_manifest = dict(manifest)
            updated_manifest["host_file_entries"] = [
                record for record in manifest.get("host_file_entries", [])
                if record.get("destination") not in retired]
            _atomic_write_json(user_root / ".install-manifest.json", updated_manifest)
            # The entry index describes what is installed on disk; an entry
            # for a file this run removed would be reported as missing.
            index_path = user_root / "entry-index.json"
            if index_path.is_file():
                try:
                    index = json.loads(index_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    index = None
                if isinstance(index, dict) and isinstance(index.get("entries"), list):
                    index = dict(index)
                    index["entries"] = [entry for entry in index["entries"]
                                        if entry.get("installed_path") not in retired]
                    _atomic_write_json(index_path, index)
        # Drop the project pin: the pin's own lines are removed from the
        # config text and every other line (identity, auto_commit, unrelated
        # settings, comments) is preserved byte-for-byte.
        pin = inspection_pin(resolved_project, user_root)
        if pin:
            for candidate in (resolved_project / ".fstar" / "config.yaml",
                              resolved_project / ".fstar" / "config.local.yaml"):
                if not candidate.is_file():
                    continue
                before = candidate.read_bytes()
                updated = _remove_pin_lines(before.decode("utf-8"))
                if updated is None:
                    continue
                after = updated.encode("utf-8")
                backup = backup_root / candidate.resolve().relative_to(resolved_project)
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(candidate), str(backup))
                backups[str(candidate)] = str(backup)
                journal.record_write(candidate, before, after)
                _atomic_write_bytes(candidate, after)
                applied.append({"path": str(candidate), "backup": str(backup),
                                "action": "pin_removed"})
                break
        _atomic_write_json(user_root / "resource-migration.json", {
            "schema": MIGRATION_SCHEMA, "operation_id": operation_id,
            "project_root": str(resolved_project), "at": utc_now(),
            "applied": applied, "kept": kept, "conflicts": preview["conflicts"],
        })
    except BaseException:
        _TRANSACTION.reset(token)
        journal.restore()
        raise
    else:
        journal.complete()
        _TRANSACTION.reset(token)
    return {"schema": MIGRATION_SCHEMA, "result": "migrated",
            "operation_id": operation_id, "backup_root": str(backup_root),
            "recovered": recovered,
            "applied": applied, "kept": kept, "conflicts": preview["conflicts"]}


def _remove_pin_lines(text: str) -> Optional[str]:
    """Remove the ``resources:`` block from a config file, keeping the rest.

    Only the top-level ``resources`` mapping and its indented children are
    dropped, so identity, auto_commit, comments, and unrelated settings stay
    exactly as the user wrote them. Returns None when the file carries no
    such block (nothing to change).
    """
    lines = text.splitlines(keepends=True)
    kept = []
    skipping = False
    changed = False
    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        if not skipping and indent == 0 and stripped.rstrip(":") == "resources" and stripped.endswith(":"):
            skipping = True
            changed = True
            continue
        if skipping:
            if stripped and indent > 0:
                continue  # a child of the removed block
            skipping = False
        kept.append(line)
    if not changed:
        return None
    return "".join(kept)


def inspection_pin(project_root: Path, user_root: Path) -> Optional[str]:
    """The project-layer resources.version pin, or None."""
    try:
        from .installer import _config_requested_version
        return _config_requested_version(project_root.expanduser().resolve(), user_root)[0]
    except Exception:
        return None


# ---------------------------------------------------------------------------
# CLI registration


def register_commands(subparsers) -> None:
    import argparse

    from .cli import OPTIONAL_HANDLER_ATTR

    inspect = subparsers.add_parser(
        "resource-inspect",
        help="read-only comparison of a project's resources against the global target")
    # The session id may be given globally (``fstar --session ID ...``) or
    # after the subcommand. SUPPRESS keeps the global value when the
    # subcommand-level flag is absent.
    inspect.add_argument("--session", default=argparse.SUPPRESS)
    inspect.add_argument("--host-root", action="append",
                          help="HOST=PATH of the host entry to compare against")
    inspect.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_inspect})

    migrate_parser = subparsers.add_parser(
        "resource-migrate",
        help="migrate an approved legacy project to global resource management")
    migrate_parser.add_argument("--confirmation", help="JSON file with {\"approved\": true, ...}")
    migrate_parser.add_argument("--host-root", action="append",
                                help="HOST=PATH of the host entry to migrate to")
    migrate_parser.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_migrate})

    defer = subparsers.add_parser(
        "resource-defer",
        help="record an explicit user deferral for this project and target version")
    defer.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_defer})

    remind_parser = subparsers.add_parser(
        "resource-remind",
        help="explicit operation that decides and records whether the migration question "
             "may be shown in this session")
    remind_parser.add_argument("--session", default=argparse.SUPPRESS)
    remind_parser.add_argument("--host-root", action="append",
                               help="HOST=PATH of the host entry to compare against")
    remind_parser.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_remind})


def _runtime_root(args, user_root: Path) -> Path:
    value = getattr(args, "runtime_root", None)
    return Path(value).expanduser().resolve() if value else user_root / "runtime"


def _project_identity(project_root: Path, user_root: Path) -> str:
    """Stable project identity, not just the working directory."""
    from .store import POINTER_FILE, _read_pointer
    pointer = project_root / POINTER_FILE
    if pointer.is_file() and not pointer.is_symlink():
        try:
            return str(_read_pointer(pointer).get("project_id", project_root))
        except Exception:
            pass
    config = project_root / ".fstar" / "config.yaml"
    if config.is_file():
        try:
            from .config import parse_config
            values = parse_config(config.read_text(encoding="utf-8"), config)
            project = values.get("project")
            if isinstance(project, dict) and isinstance(project.get("id"), str):
                return project["id"]
        except Exception:
            pass
    return str(project_root)


def _project_root_from(args) -> Path:
    explicit = getattr(args, "project", None)
    root = Path(explicit).expanduser() if explicit else Path.cwd()
    from .store import find_project_root
    found = find_project_root(root)
    if found is None:
        from .models import DomainError
        raise DomainError("project_not_initialized",
                          "No initialized fstar project found; pass --project PATH")
    return found


def _user_root_from(args) -> Path:
    value = getattr(args, "user_data_root", None)
    return Path(value).expanduser().resolve() if value else Path.home() / ".fstar"


def _host_roots_from(args, user_root: Path) -> Dict[str, Path]:
    """Resolve the host roots the resource commands inspect.

    Same shape as the installer: an explicit ``--host-root HOST=PATH`` wins,
    otherwise the global default root (``~/.claude``) is used. The explicit
    form is what lets a project with a custom host root be inspected
    correctly, and what keeps every test on isolated roots.
    """
    from .installer import SUPPORTED_HOSTS, default_host_root
    from .models import DomainError

    roots: Dict[str, Path] = {}
    for pair in getattr(args, "host_root", None) or []:
        if "=" not in pair:
            raise DomainError("invalid_host_root", "--host-root expects HOST=PATH", {"value": pair})
        name, _, value = pair.partition("=")
        if name not in SUPPORTED_HOSTS:
            raise DomainError("unknown_host", "Unknown host",
                              {"host": name, "hosts": list(SUPPORTED_HOSTS)})
        roots[name] = Path(value)
    if "claude" not in roots:
        roots["claude"] = default_host_root(user_root)
    return roots


def _handle_inspect(args):
    from .models import DomainError
    user_root = _user_root_from(args)
    project_root = _project_root_from(args)
    report = inspect_project(project_root=project_root, user_root=user_root,
                             host_roots=_host_roots_from(args, user_root))
    runtime_root = _runtime_root(args, user_root)
    identity = _project_identity(project_root, user_root)
    from .installer import load_bundle_manifest
    target = str(load_bundle_manifest().get("resource_version", ""))
    decision = session_prompt_needed(runtime_root=runtime_root, project_identity=identity,
                                     target_version=target, session_id=getattr(args, "session", "") or "")
    report["reminder"] = decision
    if decision["ask"] and report.get("migration_recommended"):
        report["migration_offer"] = (
            "This project still carries its own fstar resource copies/pin. The shared global "
            "delivery (version %s) is healthy. Migrating removes the per-project copies "
            "(backed up first), keeps your tasks/specs/identity, and future updates arrive "
            "through one global update. Modified or unowned files are kept and reported. "
            "Reply with confirmation to migrate, or ask to defer." % target)
    return report


def _handle_migrate(args):
    from .models import DomainError
    user_root = _user_root_from(args)
    project_root = _project_root_from(args)
    if getattr(args, "confirmation", None):
        from .cli import _json_file
        confirmation = _json_file(args.confirmation, "confirmation")
    else:
        raise DomainError("confirmation_required",
                          "resource-migrate requires --confirmation FILE with an approved user confirmation")
    return apply_migration(project_root=project_root, user_root=user_root,
                           runtime_root=_runtime_root(args, user_root),
                           host_roots=_host_roots_from(args, user_root),
                           confirmation=confirmation)


def _handle_defer(args):
    user_root = _user_root_from(args)
    project_root = _project_root_from(args)
    from .installer import load_bundle_manifest
    target = str(load_bundle_manifest().get("resource_version", ""))
    return record_deferral(runtime_root=_runtime_root(args, user_root),
                           project_identity=_project_identity(project_root, user_root),
                           target_version=target)


def _handle_remind(args):
    user_root = _user_root_from(args)
    project_root = _project_root_from(args)
    return remind(project_root=project_root, user_root=user_root,
                  runtime_root=_runtime_root(args, user_root),
                  session_id=getattr(args, "session", "") or "",
                  host_roots=_host_roots_from(args, user_root))
