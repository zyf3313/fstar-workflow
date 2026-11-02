"""Trusted bootstrap for the packaged fstar entrypoints (PI-I2).

Started by the Node launchers as ``python -I bin/fstar-bootstrap.py fstar.cli
<argv...>``. Under ``-I`` no site/user-site/PYTHONPATH search happens, so the
only thing this file does is put the packaged ``src`` directory (located
relative to this file, never from cwd) on ``sys.path`` and delegate to the
requested module's ``main``.

It contains no task logic and never touches host or user configuration.
"""
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or "." in argv[0] or argv[0].startswith("_"):
        print("usage: fstar-bootstrap.py <fstar.module> [args...]", file=sys.stderr)
        return 2
    module_name = argv[0]
    import importlib

    sys.path.insert(0, str(_SRC))
    if module_name == "cli":
        # The main CLI surface: fstar.cli owns argparse and optional-module
        # dispatch, including the installer commands.
        from fstar import cli as _cli

        return _cli.main(argv[1:])
    if module_name == "runtime":
        # The host-text hook entry: `fstar.runtime.__main__.main`.
        from fstar.runtime import __main__ as _runtime_main

        return _runtime_main.main(argv[1:])
    try:
        module = importlib.import_module("fstar.%s" % module_name)
    except ImportError as exc:
        print("fstar: bootstrap_import_failed: %s" % exc, file=sys.stderr)
        return 1
    entry = getattr(module, "main", None)
    if not callable(entry):
        print("fstar: bootstrap_no_main: fstar.%s has no main()" % module_name, file=sys.stderr)
        return 1
    return entry(argv[1:])


if __name__ == "__main__":
    sys.exit(main())
