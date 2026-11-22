"""Thin capability adapter interface (S-5, plan item S-5; C-14/C-19).

Four external capability classes share one small injectable contract:

- ``session-management`` — host-side session state beyond the main
  conversation (external session keepers). Fallback: the main session with
  fstar's own role separation.
- ``distribution`` — distributing fstar resources (skills) to agents without
  a native channel. The existing Magpie integration
  (:mod:`fstar.magpie.route_skills`) is the actual implementation. Fallback:
  the native skills/hooks entries the installer always writes.
- ``memory`` — durable knowledge storage outside the project data root.
  Fallback: the existing local knowledge storage under the fstar data root.
- ``scheduling`` — external schedulers/triggers for timed or background
  work. Fallback: manual driving (the coordinator/user initiates every
  action). No scheduler adapter ships in this step.

Contract rules (implementation contract item 4 / S5-A06, S5-A07):

- ``probe()`` is READ-ONLY: it reports availability and a reason. A probe
  success NEVER constitutes authorization and never performs an external
  action or installation.
- ``handshake()`` confirms which capabilities the adapter provides and
  reports incompatibility reasons. It is also read-only.
- A missing provider, a failed probe, or an incompatible handshake degrades
  to the class fallback; the core keeps running. No authorization is
  inferred from any adapter result.
- Adapters are injectable fakes in tests; the real Magpie distribution runs
  only through the installer paths that already existed (no new mutating
  call sites).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

CAPABILITY_CLASSES = ("session-management", "distribution", "memory", "scheduling")

ADAPTER_SCHEMA = "fstar.capability-adapters.v1"

# The fallback each class degrades to when its adapter is absent, fails, or
# is incompatible (spec §4). The fallback is what the workflow already does
# today; an adapter only ADDS an optional channel.
CLASS_FALLBACKS = {
    "session-management": "main session (fstar role separation unchanged)",
    "distribution": "native fstar skills/hooks entries",
    "memory": "existing local knowledge storage under the fstar data root",
    "scheduling": "manual driving (the coordinator/user initiates each action)",
}


@dataclass(frozen=True)
class CapabilityStatus:
    """One read-only probe/handshake outcome for a capability class."""

    available: bool
    reason: Optional[str] = None
    capabilities: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"available": self.available, "reason": self.reason,
                "capabilities": list(self.capabilities)}


class CapabilityAdapter:
    """Base contract: read-only probe and handshake.

    Subclasses (or injected fakes) implement ``probe``/``handshake``. Both
    must be side-effect free: no external action, no installation, no write.
    """

    name = "abstract"

    #: the capability classes this adapter may provide
    classes: tuple = ()

    def probe(self) -> CapabilityStatus:
        raise NotImplementedError

    def handshake(self, needed: List[str]) -> CapabilityStatus:
        """Confirm the needed capabilities; report incompatibility reasons."""
        raise NotImplementedError


class _MissingAdapter(CapabilityAdapter):
    """The absent-provider stand-in: always unavailable, never raises."""

    def __init__(self, reason: str = "no adapter configured"):
        self.reason = reason
        self.name = "missing"
        self.classes = ()

    def probe(self) -> CapabilityStatus:
        return CapabilityStatus(False, self.reason)

    def handshake(self, needed: List[str]) -> CapabilityStatus:
        return CapabilityStatus(False, self.reason, [])


MISSING_ADAPTER = _MissingAdapter()


class MagpieDistributionAdapter(CapabilityAdapter):
    """The distribution capability implemented by the existing Magpie path.

    Probe/handshake reuse :func:`fstar.magpie.probe`-equivalent inputs that
    the CALLER supplies (an already computed :class:`MagpieStatus` or an
    injected probe callable). This adapter itself performs no subprocess
    calls: mutating operations stay in :mod:`fstar.magpie` and keep their
    existing call sites (installer install/update). The adapter only shapes
    availability/fallback decisions, and can wrap a ``route_skills`` call
    when one is explicitly handed in (the installer does that already; here
    it is only exposed for reuse so the interface is not a dead facade).
    """

    name = "magpie"

    def __init__(self, *, probe_status=None, probe_call: Optional[Callable] = None,
                 route: Optional[Callable] = None):
        # probe_status: a MagpieStatus-like object with .available/.reason/.version
        # probe_call: injectable zero-arg callable returning such a status
        # route: injectable callable with route_skills's signature
        self._probe_status = probe_status
        self._probe_call = probe_call
        self._route = route
        self.classes = ("distribution",)

    def probe(self) -> CapabilityStatus:
        status = self._probe_status
        if status is None and self._probe_call is not None:
            try:
                status = self._probe_call()
            except Exception as exc:  # a broken probe degrades, never raises
                return CapabilityStatus(False, "probe failed: %s" % exc, ["distribution"])
        if status is None:
            return CapabilityStatus(False, "no probe result supplied", ["distribution"])
        return CapabilityStatus(bool(getattr(status, "available", False)),
                                getattr(status, "reason", None), ["distribution"])

    def handshake(self, needed: List[str]) -> CapabilityStatus:
        unsupported = [item for item in needed if item not in self.classes]
        if unsupported:
            return CapabilityStatus(False, "magpie does not provide: %s" % ", ".join(unsupported),
                                    list(self.classes))
        return self.probe()

    def route(self, **kwargs):
        """Delegate to the injected ``route_skills``-compatible callable.

        Never invoked by probe/handshake; the installer (or a test fake)
        supplies the callable and decides when a real hand-over happens.
        """
        if self._route is None:
            raise RuntimeError("no route callable injected; distribution stays on the native fallback")
        return self._route(**kwargs)


class CapabilityRegistry:
    """Injectable registry: one adapter per capability class.

    ``adapters`` maps a capability class to its adapter. A class without an
    entry uses the explicit missing-adapter fallback. All decisions return
    plain data; nothing here writes, installs, or authorizes.
    """

    def __init__(self, adapters: Optional[Dict[str, CapabilityAdapter]] = None):
        self.adapters: Dict[str, CapabilityAdapter] = dict(adapters or {})

    def resolve(self, capability_class: str) -> dict:
        """Probe + handshake one class and return availability with fallback.

        The result always names the fallback that applies when the class is
        unavailable, so a caller can proceed without special-casing.
        """
        if capability_class not in CAPABILITY_CLASSES:
            raise ValueError("unknown capability class: %s" % capability_class)
        fallback = {"class": capability_class,
                    "fallback": CLASS_FALLBACKS[capability_class]}
        adapter = self.adapters.get(capability_class, MISSING_ADAPTER)
        try:
            probed = adapter.probe()
        except Exception as exc:  # a broken adapter degrades, never raises
            return {**fallback, "available": False, "adapter": adapter.name,
                    "reason": "probe error: %s" % exc, "capabilities": []}
        if not probed.available:
            return {**fallback, "available": False, "adapter": adapter.name,
                    "reason": probed.reason, "capabilities": list(probed.capabilities)}
        try:
            confirmed = adapter.handshake([capability_class])
        except Exception as exc:
            return {**fallback, "available": False, "adapter": adapter.name,
                    "reason": "handshake error: %s" % exc,
                    "capabilities": list(probed.capabilities)}
        if not confirmed.available:
            return {**fallback, "available": False, "adapter": adapter.name,
                    "reason": confirmed.reason or "handshake rejected the capability",
                    "capabilities": list(confirmed.capabilities)}
        return {**fallback, "available": True, "adapter": adapter.name,
                "reason": None, "capabilities": list(confirmed.capabilities)}

    def report(self) -> dict:
        """Read-only availability report for every capability class."""
        return {"schema": ADAPTER_SCHEMA,
                "classes": {name: self.resolve(name) for name in CAPABILITY_CLASSES},
                "note": "probe/handshake are read-only; availability never "
                        "implies authorization, and a missing adapter degrades "
                        "to the class fallback"}


def default_registry() -> CapabilityRegistry:
    """The registry with no external adapters wired.

    Distribution (Magpie) is wired by the installer when it actually routes
    skills; everywhere else every class takes its fallback. This keeps the
    core runnable with no external providers at all (S5-A07).
    """
    return CapabilityRegistry()
