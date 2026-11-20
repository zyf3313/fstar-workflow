"""Optional Magpie skills integration (P-003, D-004).

Verified public capabilities of the local app (magpie 0.1.4380,
2026-11-20, read-only ``--version`` and ``library --help``):

- ``library skill hand-over <name...>``: hand skills over from
  ``~/.agents/skills`` to Magpie's library (named skills only).
- ``skill agents <name> <a,b>`` / ``skill router <name> direct`` /
  ``skill how`` / ``library sync`` exist, but their exact preconditions
  were not verified; this module only uses ``hand-over`` and never edits
  Magpie-private files (library.json/providers.json), never changes
  models/accounts/providers/routing, and never claims to import hooks or
  sub-agent definitions (Magpie's ``agents`` are coding tools, not fstar
  role definitions).

Design points:

- Discovery is injectable (``discover`` parameter) and the subprocess
  runner is injectable (``runner``); all tests use fakes and isolated
  roots so the real app is never invoked in tests and never discovered
  by accident from a redirected environment.
- Only read-only probes (``--version``) run against a real binary here;
  every mutating call must come through an explicitly passed runner.
- Conflicts (a user's same-named skill in ~/.agents/skills) stop that
  skill and are reported; fstar-owned, fingerprint-matching skills are
  staged into ~/.agents/skills first, then handed over.
- Idempotent: an already-handed-over skill (recorded in the user root's
  magpie-integration.json with a matching fingerprint) is skipped.
- Failure/degradation never aborts the base fstar install.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
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
        if prior and prior.get("ownership") == "magpie":
            # Magpie owns this skill (the hand-over moved it into Magpie's
            # library). A new fstar version must not drop a competing copy
            # back into ~/.agents/skills: there is no verified public update
            # path for a handed-over skill, so the update is reported for the
            # user to make in Magpie instead of being faked here.
            results.append({"skill": name, "action": "magpie_managed_update_required",
                            "reason": "Magpie manages this skill; there is no verified public "
                                      "update path for a handed-over skill. Update it in Magpie "
                                      "(or hand it back first); fstar placed no competing copy."})
            continue
        target = agents_source / name / "SKILL.md"
        if target.exists():
            current = target.read_bytes()
            if current != payload:
                results.append({"skill": name, "action": "conflict",
                                "reason": "a different skill with this name exists; not overwritten"})
                continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        except OSError as exc:
            results.append({"skill": name, "action": "error", "reason": str(exc)})
            continue
        outcome = handover_call([name], binary=binary, runner=runner)
        if outcome.get("ok"):
            record["skills"][name] = {"sha256": fingerprint, "at": outcome.get("at"),
                                      "ownership": "magpie"}
            results.append({"skill": name, "action": "handed_over"})
        else:
            record["skills"][name] = {"sha256": fingerprint, "ownership": "staged",
                                      "error": outcome.get("reason")}
            results.append({"skill": name, "action": "staged_unconfirmed",
                            "reason": outcome.get("reason")})
    record["version"] = status.version
    record["binary"] = status.binary
    _atomic_write(_record_path(user_root), record)
    failed = [item for item in results if item["action"] in ("error", "staged_unconfirmed", "conflict",
                                                             "magpie_managed_update_required")]
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


def uninstall_local(*, user_root: Path, agents_source: Path) -> dict:
    """Remove only fstar-staged, fingerprint-matching entries we still own.

    Magpie-managed content is never deleted (no verified public removal
    API): those entries are reported for manual handling.
    """
    record = _load_record(user_root)
    removed, kept = [], []
    for name, entry in sorted(record.get("skills", {}).items()):
        target = agents_source / name / "SKILL.md"
        if entry.get("ownership") == "magpie":
            kept.append({"skill": name, "reason": "managed by Magpie; remove via Magpie"})
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
