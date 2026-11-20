"""Test package guard: the real Magpie app must stay unreachable.

The soft router consults Magpie on every install/update, and the Magpie
CLI mutates real state (its library, its shared instructions). The test
suite therefore never lets the real app be discovered: the binary override
points at a path that does not exist and the staging directory points into
a throwaway directory. A test that wants a fake Magpie sets its own
override (FSTAR_MAGPIE_BINARY / FSTAR_MAGPIE_AGENTS_SOURCE) and removes
it again afterwards.

The override is read at call time by fstar.magpie, so setting it here
covers every test module in this package.
"""
import os
import tempfile

os.environ.setdefault("FSTAR_MAGPIE_BINARY",
                      os.path.join(tempfile.gettempdir(), "fstar-no-magpie-binary"))
os.environ.setdefault("FSTAR_MAGPIE_AGENTS_SOURCE",
                      os.path.join(tempfile.gettempdir(), "fstar-no-magpie-agents-source"))
