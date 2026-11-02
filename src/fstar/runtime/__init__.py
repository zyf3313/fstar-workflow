"""fstar runtime hooks package (owned by the runtime-hooks subtask).

The module name ``fstar.runtime`` is exclusive to the four semantic hooks
(session-context / worker-context / worker-result / doc-change). The dispatch
adapter lives in a separate module (``fstar.dispatch``, owned by
runtime-dispatch) and only reuses the entry functions exposed here.

Importing this package has no side effects; it defines no hooks beyond the
four semantic ones and no turn-context hook exists.
"""
from __future__ import annotations

RUNTIME_HOOKS_VERSION = "1"


def register_commands(subparsers) -> None:
    """Optional-module CLI entry point (delegates to fstar.runtime.hooks).

    Kept lazy so importing ``fstar.runtime`` stays side-effect free; the core
    imports happen only when the CLI actually registers or runs the hooks.
    Internal import failures are deliberately not wrapped: cli skips a module
    only when it does not exist, never when its body fails to import.
    """
    from .hooks import register_commands as _register_commands

    _register_commands(subparsers)

