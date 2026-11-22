from __future__ import annotations

import unittest

from fstar.capability_adapters import (
    CAPABILITY_CLASSES,
    CLASS_FALLBACKS,
    CapabilityAdapter,
    CapabilityRegistry,
    CapabilityStatus,
    MagpieDistributionAdapter,
    default_registry,
)


class FakeStatus:
    def __init__(self, available, reason=None, version="9.9.9"):
        self.available = available
        self.reason = reason
        self.version = version


class FakeAdapter(CapabilityAdapter):
    def __init__(self, *, probe_status, handshake_status=None, raises=None):
        self.name = "fake"
        self.classes = ("memory",)
        self._probe_status = probe_status
        self._handshake_status = handshake_status or probe_status
        self._raises = raises
        self.probe_calls = 0
        self.handshake_calls = 0

    def probe(self):
        self.probe_calls += 1
        if self._raises:
            raise self._raises
        return self._probe_status

    def handshake(self, needed):
        self.handshake_calls += 1
        if self._raises:
            raise self._raises
        return self._handshake_status


class RegistryContractTests(unittest.TestCase):
    def test_all_four_classes_are_covered_with_explicit_fallbacks(self):
        self.assertEqual(
            set(CAPABILITY_CLASSES),
            {"session-management", "distribution", "memory", "scheduling"})
        self.assertEqual(set(CLASS_FALLBACKS), set(CAPABILITY_CLASSES))
        report = default_registry().report()
        self.assertEqual(report["schema"], "fstar.capability-adapters.v1")
        self.assertEqual(set(report["classes"]), set(CAPABILITY_CLASSES))
        for name, entry in report["classes"].items():
            self.assertFalse(entry["available"], name)
            self.assertEqual(entry["fallback"], CLASS_FALLBACKS[name])
            self.assertTrue(entry["reason"], name)

    def test_available_adapter_is_probed_and_handshaken(self):
        adapter = FakeAdapter(probe_status=CapabilityStatus(True, None, ["memory"]))
        registry = CapabilityRegistry({"memory": adapter})
        result = registry.resolve("memory")
        self.assertTrue(result["available"])
        self.assertEqual(result["adapter"], "fake")
        self.assertEqual(adapter.probe_calls, 1)
        self.assertEqual(adapter.handshake_calls, 1)

    def test_unavailable_adapter_reports_reason_and_fallback_without_handshake(self):
        adapter = FakeAdapter(probe_status=CapabilityStatus(False, "provider not installed"))
        result = CapabilityRegistry({"memory": adapter}).resolve("memory")
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "provider not installed")
        self.assertEqual(result["fallback"], CLASS_FALLBACKS["memory"])
        self.assertEqual(adapter.handshake_calls, 0)

    def test_probe_exception_degrades_without_raising(self):
        adapter = FakeAdapter(probe_status=CapabilityStatus(True),
                              raises=RuntimeError("boom"))
        result = CapabilityRegistry({"memory": adapter}).resolve("memory")
        self.assertFalse(result["available"])
        self.assertIn("probe error", result["reason"])
        self.assertEqual(result["fallback"], CLASS_FALLBACKS["memory"])

    def test_incompatible_handshake_degrades(self):
        adapter = FakeAdapter(
            probe_status=CapabilityStatus(True, None, ["memory"]),
            handshake_status=CapabilityStatus(False, "requires capability x", []))
        result = CapabilityRegistry({"memory": adapter}).resolve("memory")
        self.assertFalse(result["available"])
        self.assertIn("requires capability x", result["reason"])

    def test_unknown_class_is_rejected(self):
        with self.assertRaises(ValueError):
            default_registry().resolve("teleportation")

    def test_probe_does_not_authorize_anything(self):
        # The contract result has no authorization field at all: availability
        # is information only.
        adapter = FakeAdapter(probe_status=CapabilityStatus(True, None, ["memory"]))
        result = CapabilityRegistry({"memory": adapter}).resolve("memory")
        self.assertNotIn("authorized", result)
        self.assertNotIn("granted", result)


class MagpieAdapterTests(unittest.TestCase):
    def test_probe_is_read_only_and_route_is_not_touched(self):
        calls = []
        adapter = MagpieDistributionAdapter(
            probe_status=FakeStatus(True),
            route=lambda **kwargs: calls.append(kwargs) or {"ok": True})
        self.assertTrue(adapter.probe().available)
        self.assertTrue(adapter.handshake(["distribution"]).available)
        self.assertEqual(calls, [])
        self.assertEqual(adapter.classes, ("distribution",))

    def test_missing_magpie_reports_reason(self):
        adapter = MagpieDistributionAdapter(probe_status=FakeStatus(False, "magpie binary not found"))
        status = adapter.probe()
        self.assertFalse(status.available)
        self.assertEqual(status.reason, "magpie binary not found")

    def test_probe_callable_exception_degrades(self):
        def broken():
            raise OSError("boom")
        status = MagpieDistributionAdapter(probe_call=broken).probe()
        self.assertFalse(status.available)
        self.assertIn("probe failed", status.reason)

    def test_handshake_rejects_other_capability_classes(self):
        adapter = MagpieDistributionAdapter(probe_status=FakeStatus(True))
        status = adapter.handshake(["scheduling"])
        self.assertFalse(status.available)
        self.assertIn("scheduling", status.reason)

    def test_route_delegates_when_injected(self):
        seen = {}

        def route(**kwargs):
            seen.update(kwargs)
            return {"status": "handed_over"}

        adapter = MagpieDistributionAdapter(route=route)
        self.assertEqual(adapter.route(skills_root="x"), {"status": "handed_over"})
        self.assertEqual(seen, {"skills_root": "x"})

    def test_route_without_callable_is_an_explicit_error(self):
        with self.assertRaises(RuntimeError):
            MagpieDistributionAdapter().route()


if __name__ == "__main__":
    unittest.main()
