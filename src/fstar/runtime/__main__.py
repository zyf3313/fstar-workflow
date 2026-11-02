"""Host-facing entry for the four semantic hooks.

Host registration commands execute ``python3 -m fstar.runtime <hook>`` with
the host event payload as JSON on stdin and inject stdout into the session
(the same mechanism the existing host hooks use). The explicit machine entry
``fstar hook <name>`` stays JSON-only; both paths call the same entry
functions in ``fstar.runtime.hooks``.

Passive semantics: a missing task.json / uninitialized project is a silent
exit 0 with no placeholder output, while routing/role injection still
happens. Unexpected DomainErrors surface on stderr with a non-zero exit;
internal import errors are never wrapped or swallowed.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from ..models import DomainError
from . import hooks


def _read_payload() -> dict:
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _start_from(payload: dict) -> Path:
    explicit = os.environ.get("FSTAR_PROJECT")
    if explicit:
        return Path(explicit)
    cwd = payload.get("cwd")
    return Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()


def _user_root() -> Optional[Path]:
    value = os.environ.get("FSTAR_USER_ROOT")
    return Path(value) if value else None


def _runtime_root() -> Optional[Path]:
    value = os.environ.get("FSTAR_RUNTIME_ROOT")
    return Path(value) if value else None


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    name = argv[0] if argv else ""
    if name not in hooks.HOOK_NAMES:
        print("usage: python3 -m fstar.runtime {%s}" % "|".join(hooks.HOOK_NAMES), file=sys.stderr)
        return 2
    payload = _read_payload()
    start = _start_from(payload)
    user_root = _user_root()
    runtime_root = _runtime_root()
    try:
        if name == "session-context":
            result = hooks.session_context(payload, start=start, user_root=user_root, runtime_root=runtime_root)
            if result.get("text"):
                print(result["text"])
            return 0
        if name == "worker-context":
            if hooks._role_from_payload(payload) is None:
                # Not an fstar role dispatch: emit nothing rather than guess.
                return 0
            result = hooks.worker_context(payload, start=start, user_root=user_root, runtime_root=runtime_root)
            if result.get("text"):
                print(result["text"])
            return 0
        if name == "worker-result":
            # Host events cannot carry the dispatch result message; the
            # runtime-dispatch recovery boundary owns the real call.
            return 0
        # doc-change: emit exactly one propagation line, only when changed.
        result = hooks.doc_change(payload, start=start, user_root=user_root, runtime_root=runtime_root, passive=True)
        hint = result.get("hint")
        if hint:
            print(hint)
        return 0
    except DomainError as exc:
        print("fstar: %s: %s" % (exc.code, exc.message), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
