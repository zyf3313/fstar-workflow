"""Optional Magpie skills integration (P-003, D-004).

Verified public capabilities of the local app (magpie 0.1.4582,
2026-11-20, read-only ``--version``, ``library --help`` and
``library instructions --help``):

- ``library skill hand-over <name...>``: hand skills over from
  ``~/.agents/skills`` to Magpie's library (named skills only).
- ``library instructions``: print the shared library instructions.
  ``library instructions set <file|->`` REPLACES them with a file's text
  (``-`` reads stdin), so the writer must read the current text first and
  must never replace content it does not own.
- ``library skill rm <name>``: remove a skill from Magpie's library
  (verified present in magpie 0.1.4722, 2026-11-24; its help notes "skills
  are installed from the app's Library page" and the folder goes to
  magpie's backups). fstar retains stale entries because their actual library content cannot
  currently be verified through a known public reader.
- ``skill agents <name> <a,b>`` / ``skill router <name> direct`` /
  ``skill how`` / ``library sync`` exist, but their exact preconditions
  were not verified; this module only uses ``hand-over``, the guarded
  and the library instructions channel, never edits
  Magpie-private files
  (library.json/providers.json), never changes models/accounts/providers/
  routing, and never claims to import hooks or sub-agent definitions
  (Magpie's ``agents`` are coding tools, not fstar role definitions).

Design points:

- Native skill copies are ALWAYS installed by the installer (manual
  /fstar-* slash commands are supplied only by the host's native skills
  directory; Magpie delivers skills through a single aggregated router
  skill). Everything here is the ADDITIONAL library distribution for
  agents without a native channel; no result here ever implies a missing
  native skill.
- Discovery is injectable (``discover`` parameter) and the subprocess
  runner is injectable (``runner``); all tests use fakes and isolated
  roots so the real app is never invoked in tests and never discovered
  by accident from a redirected environment.
- Only read-only probes (``--version``) run against a real binary here;
  every mutating call must come through an explicitly passed runner.
- Conflicts (a user's same-named skill in ~/.agents/skills) stop that
  skill's library distribution and are reported; fstar-owned,
  fingerprint-matching skills are staged into ~/.agents/skills first, then
  handed over.
- Idempotent: an already-handed-over skill (recorded in the user root's
  magpie-integration.json with a matching fingerprint) is skipped.
- Failure/degradation never aborts the base fstar install.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

INTEGRATION_SCHEMA = "fstar.magpie-integration.v1"
HANDOVER_TIMEOUT = 30.0
PROBE_TIMEOUT = 10.0
MAGPIE_APP_CANDIDATES = (
    "/Applications/magpie.app/Contents/MacOS/magpie",
    "~/Applications/magpie.app/Contents/MacOS/magpie",
)
# Explicit injection points. They exist so an isolated run (a test, a
# sandbox) can point the integration at a fake binary and a fake skills
# directory instead of discovering the real app on the machine.
BINARY_ENV = "FSTAR_MAGPIE_BINARY"
AGENTS_SOURCE_ENV = "FSTAR_MAGPIE_AGENTS_SOURCE"


@dataclass(frozen=True)
class MagpieStatus:
    available: bool
    binary: Optional[str]
    version: Optional[str]
    reason: Optional[str] = None


def default_discovery(home: Optional[Path] = None) -> Optional[str]:
    """PATH first, then known app locations; None when absent.

    Uses shutil.which (PATH) and the verified app path list. A test can
    inject its own discovery or set PATH to a fake dir; the module never
    shells out to `which` or touches other apps.
    """
    import shutil
    # Only PATH + the verified app locations; never a broad walk of the real
    # home. Tests redirect HOME or inject discovery entirely.
    override = os.environ.get(BINARY_ENV)
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_file() and os.access(str(candidate), os.X_OK):
            return str(candidate)
        return None
    found = shutil.which("magpie")
    if found:
        return found
    if home is not None:
        path = home / "Applications" / "magpie.app" / "Contents" / "MacOS" / "magpie"
        if path.is_file() and os.access(str(path), os.X_OK):
            return str(path)
    else:
        for candidate in MAGPIE_APP_CANDIDATES:
            path = Path(candidate).expanduser()
            if path.is_file() and os.access(str(path), os.X_OK):
                return str(path)
    return None


def default_runner(argv: Sequence[str], *, timeout: float) -> Tuple[int, str, str]:
    """Bounded argv subprocess; never a shell string (space-safe paths)."""
    completed = subprocess.run(list(argv), capture_output=True, text=True,
                               timeout=timeout, shell=False)
    return completed.returncode, completed.stdout or "", completed.stderr or ""


def probe(*, binary: str, runner: Callable = default_runner) -> MagpieStatus:
    """Read-only --version probe; an old/unknown binary still counts as
    available for hand-over only if it answers."""
    try:
        code, out, err = runner([binary, "--version"], timeout=PROBE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return MagpieStatus(False, binary, None, "version probe timed out")
    except OSError as exc:
        return MagpieStatus(False, binary, None, "cannot execute: %s" % exc)
    if code != 0:
        return MagpieStatus(False, binary, None, "version probe failed (exit %s)" % code)
    version = (out or err).strip().splitlines()[-1] if (out or err).strip() else None
    return MagpieStatus(True, binary, version)


# ---------------------------------------------------------------------------
# record


def default_agents_source() -> Path:
    """Where fstar stages its skills for the hand-over (``~/.agents/skills``).

    The ``FSTAR_MAGPIE_AGENTS_SOURCE`` environment variable redirects it, so
    an isolated run never touches the real Magpie staging directory.
    """
    override = os.environ.get(AGENTS_SOURCE_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".agents" / "skills"


def _record_path(user_root: Path) -> Path:
    return user_root / "magpie-integration.json"


def _load_record(user_root: Path) -> dict:
    try:
        value = json.loads(_record_path(user_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": INTEGRATION_SCHEMA, "skills": {}}
    if not isinstance(value, dict) or not isinstance(value.get("skills"), dict):
        return {"schema": INTEGRATION_SCHEMA, "skills": {}}
    return value


def load_record(user_root: Path) -> dict:
    """The ownership record of the last Magpie integration (read-only)."""
    return _load_record(user_root)


def _atomic_write(path: Path, payload: dict) -> None:
    import uuid
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-%s" % uuid.uuid4().hex[:8])
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


# ---------------------------------------------------------------------------
# integration


def integrate(*, skills_root: Path, agents_source: Path,
              binary: Optional[str] = None, user_root: Path,
              discover: Callable = default_discovery,
              runner: Callable = default_runner,
              handover: Optional[Callable] = None,
              skill_names: Optional[Sequence[str]] = None,
              probe_status: Optional[MagpieStatus] = None) -> dict:
    """Best-effort named-skill hand-over. Never raises for missing Magpie.

    ``skills_root`` is fstar's staged skills directory (the bundle's
    resources/skills); ``agents_source`` is ~/.agents/skills. Each fstar
    skill is staged to agents_source only when nothing (or fstar's own
    identical content) is already there, then handed over by name through
    the public CLI. Per-skill results are independent: one failure never
    blocks the others, and a failed base install is impossible here because
    this function is called after install succeeds.
    """
    status = probe_status or (probe(binary=binary, runner=runner) if binary
                              else None)
    if status is None and binary is None:
        # No binary was passed: fall back to the injected discovery. The
        # discovery only locates the executable; it never runs it.
        try:
            found = discover() if discover else None
        except Exception as exc:  # a broken discovery is a skip, not a crash
            found = None
            discovery_reason = str(exc)
        else:
            discovery_reason = None
        if found:
            binary = str(found)
            status = probe(binary=binary, runner=runner)
        else:
            status = MagpieStatus(False, None, None,
                                  discovery_reason or "magpie binary not found")
    if status is None or not status.available:
        reason = status.reason if status else "magpie binary not found"
        return {"schema": INTEGRATION_SCHEMA, "status": "skipped",
                "reason": reason, "skills": []}
    record = _load_record(user_root)
    results: List[dict] = []
    handover_call = handover or _public_handover
    names = list(skill_names or sorted(path.parent.name for path in skills_root.glob("*/SKILL.md")))
    for name in names:
        staged = skills_root / name / "SKILL.md"
        if not staged.is_file():
            results.append({"skill": name, "action": "skip",
                            "reason": "no staged SKILL.md"})
            continue
        payload = staged.read_bytes()
        fingerprint = hashlib.sha256(payload).hexdigest()
        prior = record["skills"].get(name)
        if prior and prior.get("sha256") == fingerprint:
            results.append({"skill": name, "action": "already_integrated"})
            continue
        # Additive model (R-003 rework): changed content is re-staged and
        # re-handed-over through the public CLI; a stale record from the
        # retired ownership model (ownership="magpie") is read the same way.
        staged_ok, staged_reason = _stage_skill(agents_source, name, payload, prior or {})
        if not staged_ok:
            results.append({"skill": name, "action": "conflict", "reason": staged_reason})
            continue
        outcome = handover_call([name], binary=binary, runner=runner)
        if outcome.get("ok"):
            record["skills"][name] = {"sha256": fingerprint, "at": outcome.get("at"),
                                      "library": "handed_over"}
            results.append({"skill": name, "action": "handed_over"})
        else:
            record["skills"][name] = {"sha256": fingerprint, "library": "handover_failed",
                                      "staged": True, "error": outcome.get("reason")}
            results.append({"skill": name, "action": "staged_unconfirmed",
                            "reason": outcome.get("reason")})
    record["version"] = status.version
    record["binary"] = status.binary
    _atomic_write(_record_path(user_root), record)
    failed = [item for item in results if item["action"] in ("error", "staged_unconfirmed", "conflict")]
    return {"schema": INTEGRATION_SCHEMA,
            "status": "degraded" if failed else "integrated",
            "magpie_version": status.version, "binary": status.binary,
            "skills": results}


def _public_handover(names: Sequence[str], *, binary: str,
                     runner: Callable = default_runner) -> dict:
    """The verified public hand-over command, by exact skill names."""
    import time
    argv = [binary, "library", "skill", "hand-over", *names]
    try:
        code, out, err = runner(argv, timeout=HANDOVER_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "hand-over timed out"}
    except OSError as exc:
        return {"ok": False, "reason": "hand-over failed: %s" % exc}
    if code != 0:
        return {"ok": False, "reason": "hand-over exited %s: %s" % (code, (err or out).strip()[:200])}
    return {"ok": True, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "output": (out or "").strip()[:200]}


def _public_skill_rm(names: Sequence[str], *, binary: str,
                     runner: Callable = default_runner) -> dict:
    """The verified public library removal command, by exact skill names.

    ``magpie library skill rm <name>`` (present in magpie 0.1.4722):
    removes a skill from Magpie's library (its folder goes to magpie's
    backups). Invoked one name at a time by the guarded prune so one bad
    skill never affects another.
    """
    argv = [binary, "library", "skill", "rm", *names]
    try:
        code, out, err = runner(argv, timeout=HANDOVER_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "library skill rm timed out"}
    except OSError as exc:
        return {"ok": False, "reason": "library skill rm failed: %s" % exc}
    if code != 0:
        return {"ok": False,
                "reason": "library skill rm exited %s: %s" % (code, (err or out).strip()[:200])}
    return {"ok": True, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "output": (out or "").strip()[:200]}


def _fstar_ledger_history(entry: Mapping) -> bool:
    """True when the ledger entry carries fstar's own hand-over history.

    fstar always writes the hand-over timestamp ``at`` (the retired
    ownership model wrote ``ownership``); a hand-written or foreign ledger
    entry has neither, so it is never treated as fstar history.
    """
    if not entry:
        return False
    if entry.get("at"):
        return True
    return entry.get("ownership") in ("magpie", "native", "staged")


def _is_fstar_managed(name: str, record: Mapping) -> bool:
    """A skill fstar may prune: the fstar- prefix or a ledger-recorded
    fstar hand-over history for that exact name."""
    if name.startswith("fstar-"):
        return True
    entry = (record.get("skills") or {}).get(name)
    return bool(entry) and _fstar_ledger_history(entry)


def _prune_stale_skill(*, name: str, record: dict, agents_source: Path,
                       binary: str, runner: Callable) -> dict:
    """Report a stale skill without deletion when library content is unverified.

    A staged source copy cannot establish the current library fingerprint.
    The public rm command exists, but no safe public content reader is known.
    """
    entry = (record.get("skills") or {}).get(name) or {}
    state, _note = _library_state(entry)
    if state != "handed_over":
        return {"skill": name, "library": state or "absent", "action": "prune_failed",
                "reason": "the ledger does not record this skill as handed over "
                          "(state: %s); nothing was removed" % (state or "none")}
    if not _is_fstar_managed(name, record):
        return _prune_foreign_entry(name=name, record=record)
    # The staged source is independent of the library and cannot prove its
    # current contents. No verified public library-content reader is known.
    return {"skill": name, "library": "handed_over", "action": "stale_but_modified",
            "reason": "current library content cannot be independently verified; "
                      "the stale skill and its ledger entry were kept"}


def _prune_foreign_entry(*, name: str, record: dict) -> dict:
    """A ledger entry fstar never created (a hand-written or foreign ledger):
    the name is not fstar-managed, so it is reported and kept."""
    return {"skill": name, "library": "handed_over", "action": "prune_failed",
            "reason": "the skill is not fstar-managed (no fstar- prefix and no "
                      "fstar hand-over history for this name); nothing was removed"}


def _stale_handed_over(record: Mapping, names: Sequence[str]) -> List[str]:
    """Ledger skills recorded as handed_over but absent from the current
    bundle. Skills the ledger never recorded are never considered."""
    current = set(names)
    stale = []
    for name, entry in (record.get("skills") or {}).items():
        if name in current:
            continue
        if _library_state(entry or {})[0] == "handed_over":
            stale.append(name)
    return sorted(stale)


def uninstall_local(*, user_root: Path, agents_source: Path) -> dict:
    """Remove only fstar-staged, fingerprint-matching entries we still own.

    Magpie-managed content is not deleted here or by stale reconciliation:
    actual library content cannot currently be independently verified.
    """
    record = _load_record(user_root)
    removed, kept = [], []
    for name, entry in sorted(record.get("skills", {}).items()):
        target = agents_source / name / "SKILL.md"
        state, _note = _library_state(entry or {})
        if state == "handed_over":
            kept.append({"skill": name,
                         "reason": "handed over to the Magpie library; the next "
                                   "library content cannot currently be verified; retained"})
            continue
        if entry.get("ownership") == "native":
            # The skill lives in the host's native channel; nothing is staged
            # for Magpie, so there is nothing to remove here.
            kept.append({"skill": name, "reason": "installed natively; nothing staged for Magpie"})
            continue
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == entry.get("sha256"):
            target.unlink()
            removed.append(name)
        else:
            kept.append({"skill": name, "reason": "content changed; not removed"})
    if removed:
        for name in removed:
            record["skills"].pop(name, None)
        _atomic_write(_record_path(user_root), record)
    return {"schema": INTEGRATION_SCHEMA, "removed": removed, "kept": kept}


# ---------------------------------------------------------------------------
# Additive library distribution (R-003, reworked 2026-11-20)
#
# ``route_skills`` is the install/update entry point of the additive Magpie
# distribution: native copies are ALWAYS installed by the installer (slash
# commands such as /fstar-* are a client feature supplied only by the host's
# native skills directory; Magpie delivers skills to hosts through a single
# aggregated router skill, so it can never provide the per-skill commands).
# When Magpie is available, each skill is additionally handed over to
# Magpie's library so agents WITHOUT a native skills channel can share the
# skills through Magpie's router. The per-skill result therefore describes
# ONLY the library distribution status (handed_over / handover_failed / ...);
# it never implies anything about the native copy, which stays
# installer-owned.
#
# Record layout (magpie-integration.json, schema fstar.magpie-integration.v1):
#   skills.<name>.sha256   - fingerprint of the last handed-over content
#   skills.<name>.library  - "handed_over" | "handover_failed" | ...
#   skills.<name>.at       - hand-over timestamp
# A legacy record written by the retired ownership model
# (skills.<name>.ownership == "magpie" or "native") is read compatibly:
# ownership="magpie" is treated as "library handed over with this
# fingerprint" (native copy is reinstalled by the installer as usual);
# ownership="native" is treated as "no library distribution".

ROUTING_SCHEMA = "fstar.magpie-routing.v1"

# The shared library entry. It is natural language on purpose: it tells a
# tool without hooks when to enter the fstar workflow, not which commands to
# run. The commands live in the installed package and the project data root.
SHARED_INSTRUCTIONS = """fstar workflow entry (written by fstar-workflow)

This machine shares one fstar workflow, published through Magpie's library
instructions so every tool that reads them can reach the same workflow.

When a request should follow the project's fstar task tree - planning,
implementing, checking, or archiving work that has to survive the session -
treat it as an fstar task: clarify the goal in conversation, create and start
a task, implement it through the fstar implement role, let an independent
fstar check review the result, and wait for the user's explicit acceptance
before anything is archived or merged.

Requests that do not need that lifecycle - a question, a one-off edit, a
quick lookup - do not need fstar; stay in the normal conversation for them.

The workflow's own procedures, templates, and history live in the installed
fstar package and in the project data root. This entry only says when to
enter the workflow; it is not a command list.
"""


def _skill_payload(skills_root: Path, name: str) -> Optional[bytes]:
    staged = skills_root / name / "SKILL.md"
    if not staged.is_file():
        return None
    return staged.read_bytes()


def _stage_skill(agents_source: Path, name: str, payload: bytes,
                 record: Optional[Mapping] = None) -> Tuple[bool, str]:
    """Stage fstar's skill into Magpie's source directory.

    A same-named skill with different content belongs to the user and is
    never overwritten; the caller reports a conflict for that skill alone.
    Content fstar itself staged earlier (the record holds its fingerprint)
    is ours and is refreshed to the incoming payload, so a new fstar
    version re-hands-over instead of being blocked by our own stale copy.
    """
    target = agents_source / name / "SKILL.md"
    if target.exists():
        try:
            current = target.read_bytes()
        except OSError as exc:
            return False, "cannot read %s: %s" % (target, exc)
        if current != payload:
            import hashlib
            ours = record and hashlib.sha256(current).hexdigest() == record.get("sha256")
            if not ours:
                return False, "a different skill with this name exists; not overwritten"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    except OSError as exc:
        return False, str(exc)
    return True, ""


def _drop_staged(agents_source: Path, name: str, payload: bytes) -> None:
    """Remove a staged copy fstar itself wrote (fingerprint match only).

    The native fallback and the Magpie copy must never both be live for the
    same skill, so a failed hand-over removes the staged file again. A file
    whose content differs belongs to the user and is left alone.
    """
    target = agents_source / name / "SKILL.md"
    try:
        if not target.is_file():
            return
        if target.read_bytes() != payload:
            return
        target.unlink()
    except OSError:
        return
    for directory in (target.parent, target.parent.parent):
        try:
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
            else:
                break
        except OSError:
            break


def _resolve_magpie(*, binary: Optional[str], discover: Callable, runner: Callable,
                    probe_status: Optional[MagpieStatus]) -> Tuple[Optional[str], MagpieStatus]:
    """Locate and probe Magpie. Only ``--version`` ever runs against it."""
    if probe_status is not None:
        return binary, probe_status
    if binary:
        return binary, probe(binary=binary, runner=runner)
    reason = None
    try:
        found = discover() if discover else None
    except Exception as exc:  # a broken discovery is a skip, not a crash
        found, reason = None, str(exc)
    if not found:
        return None, MagpieStatus(False, None, None, reason or "magpie binary not found")
    binary = str(found)
    return binary, probe(binary=binary, runner=runner)


def _library_state(prior: Mapping) -> Tuple[str, Optional[str]]:
    """Read a skill's prior library-distribution state from its record entry.

    New records carry ``library`` ("handed_over" / "handover_failed" / ...).
    Legacy records from the retired ownership model are migrated on read:

    - ``ownership == "magpie"``: the skill was handed over to the library
      with the recorded fingerprint. The native copy is installer-owned and
      is (re)installed by the installer as usual.
    - ``ownership == "native"`` or anything else: no library distribution.
    """
    library = prior.get("library")
    if isinstance(library, str) and library:
        return library, None
    ownership = prior.get("ownership")
    if ownership == "magpie":
        return "handed_over", "legacy ownership=magpie record"
    return "", None


def route_skills(*, skills_root: Path, agents_source: Path, user_root: Path,
                 binary: Optional[str] = None, discover: Callable = default_discovery,
                 runner: Callable = default_runner, handover: Optional[Callable] = None,
                 skill_names: Optional[Sequence[str]] = None,
                 probe_status: Optional[MagpieStatus] = None,
                 dry_run: bool = False, native_only: bool = False) -> dict:
    """Distribute every fstar skill additionally to Magpie's library (R-003).

    Native copies are the installer's business and are ALWAYS written by the
    caller; this function never affects them. Each per-skill result below
    describes ONLY the library distribution:

    - Magpie available and the hand-over succeeds: ``handed_over``; the
      record stores the fingerprint under the independent ``library`` field.
    - Magpie available and the hand-over fails, or the user's own skill
      occupies the staging name: ``handover_failed`` / ``conflict``; only the
      library distribution is missing, the native copy is untouched.
    - Magpie absent: ``magpie_absent``; nothing is staged. Skills previously
      handed over are reported ``library_handed_over_magpie_absent`` —
      informational only, the native copy keeps working.
    - Same fingerprint as the last hand-over: ``already_integrated`` (skip).

    A legacy record with ``ownership="magpie"`` is read as "library handed
    over"; a changed fingerprint re-runs the hand-over (the library update
    limitation of the retired model no longer blocks the native update, and
    there is no verified public library-update path, so a changed
    fingerprint re-stages and re-hands-over through the public CLI).

    Stale reconciliation (A-001): skills the ledger records as handed_over
    but that left the current bundle are surfaced in every mode. A dry run
    reports them as ``stale_pending_removal``; an apply run retains them
    because actual library content cannot be verified. With Magpie
    absent or native_only they are reported informationally only, never
    removed, consistent with the other informational actions.

    ``dry_run`` plans the same decisions without staging, handing over, or
    writing the record. ``native_only`` skips Magpie entirely (no probe, no
    staging, no hand-over): native copies only.
    """
    names = list(skill_names or sorted(path.parent.name for path in skills_root.glob("*/SKILL.md")))
    record = _load_record(user_root)
    stale = _stale_handed_over(record, names)
    if native_only:
        # The user asked for native only: Magpie is not consulted at all, and
        # the library distribution is left exactly as it is. Stale handed-over
        # entries are reported informationally (A-001); removal is a guarded
        # library operation and runs on the next normal install/update.
        results = []
        for name in names:
            prior = record["skills"].get(name) or {}
            state, note = _library_state(prior)
            library = "handed_over" if state == "handed_over" else "absent"
            results.append({"skill": name, "library": library, "action": "native_only",
                            "reason": ("Magpie was not consulted; the library distribution "
                                       "state is unchanged" + (" (previously handed over)" if state else ""))})
        for name in stale:
            results.append({"skill": name, "library": "handed_over",
                            "action": "stale_pending_removal",
                            "reason": "the skill left the bundle but is still handed over to "
                                      "the Magpie library; native-only does not consult Magpie, "
                                      "so it remains in the library"})
        library_map = {item["skill"]: item["library"] for item in results}
        for name in stale:
            library_map.setdefault(name, "handed_over")
        return {"schema": ROUTING_SCHEMA, "status": "preview" if dry_run else "native_only",
                "magpie": {"available": False, "consulted": False,
                           "reason": "native-only install: Magpie was not consulted"},
                "skills": results,
                "library": library_map}

    binary, status = _resolve_magpie(binary=binary, discover=discover, runner=runner,
                                    probe_status=probe_status)
    handover_call = handover or _public_handover
    results: List[dict] = []
    changed = False
    # Stale reconciliation (A-001): ledger skills that left the bundle.
    for name in stale:
        if not status.available:
            # Informational only, like library_handed_over_magpie_absent:
            # nothing is removed while Magpie is unreachable.
            results.append({"skill": name, "library": "handed_over",
                            "action": "stale_pending_removal",
                            "reason": "the skill left the bundle but is still handed over "
                                      "to the Magpie library, which is not available (%s); "
                                      "it remains in the library" % (status.reason or "not available")})
            continue
        if dry_run:
            results.append({"skill": name, "library": "handed_over",
                            "action": "stale_pending_removal",
                            "reason": "the skill left the bundle; library content cannot currently "
                                      "be verified, so it would be retained"})
            continue
        outcome = _prune_stale_skill(name=name, record=record,
                                     agents_source=agents_source,
                                     binary=binary, runner=runner)
        if outcome.get("action") == "pruned_from_library":
            changed = True
        results.append(outcome)
    for name in names:
        payload = _skill_payload(skills_root, name)
        if payload is None:
            results.append({"skill": name, "library": "absent", "action": "skip",
                            "reason": "no bundled SKILL.md"})
            continue
        fingerprint = hashlib.sha256(payload).hexdigest()
        prior = record["skills"].get(name) or {}
        state, _note = _library_state(prior)
        if not status.available:
            if state == "handed_over":
                # Informational only: the native copy keeps working; the
                # library distribution is simply unreachable until Magpie
                # returns.
                results.append({"skill": name, "library": "handed_over", "action": "library_unreachable",
                                "reason": "the skill was handed over to the Magpie library but "
                                          "Magpie is not available (%s); the native entry "
                                          "points are unaffected" % (status.reason or "not available")})
            else:
                results.append({"skill": name, "library": "absent", "action": "magpie_absent",
                                "reason": status.reason or "magpie is not available"})
            continue
        if state == "handed_over" and prior.get("sha256") == fingerprint:
            results.append({"skill": name, "library": "handed_over", "action": "already_integrated",
                            "reason": "the Magpie library already holds this content"})
            continue
        if dry_run:
            results.append({"skill": name, "library": "absent", "action": "would_hand_over",
                            "reason": "preview only; nothing was staged or handed over"})
            continue
        staged_ok, staged_reason = _stage_skill(agents_source, name, payload, prior)
        if not staged_ok:
            results.append({"skill": name, "library": "absent", "action": "conflict",
                            "reason": staged_reason})
            continue
        outcome = handover_call([name], binary=binary, runner=runner)
        if outcome.get("ok"):
            record["skills"][name] = {"sha256": fingerprint, "at": outcome.get("at"),
                                      "library": "handed_over"}
            changed = True
            results.append({"skill": name, "library": "handed_over", "action": "handed_over"})
        else:
            # The hand-over failed: only the library distribution is missing.
            # The staged copy is removed again so nothing half-handed-over
            # lingers in the staging directory; the native copy is untouched.
            _drop_staged(agents_source, name, payload)
            record["skills"][name] = {"sha256": fingerprint, "library": "handover_failed",
                                      "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                      "error": outcome.get("reason")}
            changed = True
            results.append({"skill": name, "library": "handover_failed", "action": "handover_failed",
                            "reason": outcome.get("reason")})
    if changed and not dry_run:
        record["version"] = status.version
        record["binary"] = status.binary
        _atomic_write(_record_path(user_root), record)
    degraded = any(item["action"] in ("handover_failed", "conflict",
                                      "prune_failed", "stale_but_modified")
                   for item in results)
    if dry_run:
        overall = "preview"
    elif not status.available:
        overall = "skipped"
    else:
        overall = "degraded" if degraded else "handed_over"
    return {"schema": ROUTING_SCHEMA, "status": overall,
            "magpie": {"available": status.available, "consulted": True,
                       "binary": status.binary, "version": status.version,
                       "reason": status.reason},
            "skills": results,
            "library": {item["skill"]: item["library"] for item in results}}


def stale_handed_over(user_root: Path, names: Optional[Sequence[str]] = None,
                      skills_root: Optional[Path] = None) -> List[str]:
    """Public read-only helper: ledger skills recorded handed_over that are
    absent from the given bundle names (or the bundle under skills_root)."""
    if names is None:
        names = sorted(path.parent.name for path in skills_root.glob("*/SKILL.md"))
    return _stale_handed_over(_load_record(user_root), names)


# ---------------------------------------------------------------------------
# Shared library instructions (R-004)
#
# ``library instructions set`` REPLACES the shared text, so the writer always
# reads the current instructions first. Content that is not fstar's own
# (no matching fingerprint) is kept unchanged and reported as a conflict.


def _read_instructions(binary: str, runner: Callable) -> Tuple[bool, str, str]:
    """Read the shared library instructions through the public CLI."""
    try:
        code, out, err = runner([binary, "library", "instructions"], timeout=HANDOVER_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, "", "reading the library instructions timed out"
    except OSError as exc:
        return False, "", "cannot read the library instructions: %s" % exc
    if code != 0:
        return False, "", "library instructions exited %s: %s" % (code, (err or out).strip()[:200])
    return True, out or "", ""


def _write_instructions(binary: str, runner: Callable, text: str) -> Tuple[bool, str]:
    """Replace the shared library instructions with ``text``."""
    import tempfile

    handle, name = tempfile.mkstemp(prefix="fstar-magpie-instructions-", suffix=".md")
    path = Path(name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        try:
            code, out, err = runner([binary, "library", "instructions", "set", str(path)],
                                     timeout=HANDOVER_TIMEOUT)
        except subprocess.TimeoutExpired:
            return False, "writing the library instructions timed out"
        except OSError as exc:
            return False, "cannot write the library instructions: %s" % exc
        if code != 0:
            return False, "library instructions set exited %s: %s" % (code, (err or out).strip()[:200])
        return True, ""
    finally:
        path.unlink(missing_ok=True)


def share_instructions(*, binary: str, user_root: Path, runner: Callable = default_runner,
                       text: Optional[str] = None, record: Optional[dict] = None,
                       write: bool = True) -> dict:
    """Publish the fstar workflow entry into Magpie's library instructions.

    The current instructions are read first. Only an empty library or text
    fstar itself wrote (fingerprint match) is replaced; anything else is the
    user's own content and is kept exactly as it is, with a conflict report.
    A capability that cannot be read or written is skipped and reported; it
    never fails the install.
    """
    if record is None:
        record = _load_record(user_root)
    if text is None:
        text = SHARED_INSTRUCTIONS
    stored = record.get("instructions") or {}
    ok, current_raw, reason = _read_instructions(binary, runner)
    if not ok:
        return {"action": "unavailable", "reason": reason}
    current = current_raw.strip()
    fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest()
    accepted = {value for value in (stored.get("sha256"), stored.get("observed_sha256")) if value}
    if current and hashlib.sha256(current.encode("utf-8")).hexdigest() not in accepted:
        return {"action": "conflict", "reason": "the library already holds instructions that fstar "
                                                "did not write; they were kept unchanged",
                "sha256": hashlib.sha256(current.encode("utf-8")).hexdigest()}
    if not write:
        return {"action": "would_write", "sha256": fingerprint,
                "reason": "preview only; the library instructions were not changed"}
    written, reason = _write_instructions(binary, runner, text)
    if not written:
        return {"action": "unavailable", "reason": reason}
    observed = ""
    read_ok, read_raw, _ = _read_instructions(binary, runner)
    if read_ok:
        observed = read_raw.strip()
    entry = {"sha256": fingerprint, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if observed:
        entry["observed_sha256"] = hashlib.sha256(observed.encode("utf-8")).hexdigest()
    record["instructions"] = entry
    _atomic_write(_record_path(user_root), record)
    return {"action": "updated" if current else "written", "sha256": fingerprint,
            "reason": "the fstar workflow entry is published in the Magpie library instructions"}
