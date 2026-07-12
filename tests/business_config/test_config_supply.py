"""Phase B2-4 Batch 1 tests — SSOT config supply for 3 businesses."""

import copy
import importlib.util
import os
import re
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from configs.business_registry import get as get_config
from core.business_config.models import BusinessConfig
from core.business_config.config_builder import (
    build_legacy_compatible_config, validate_legacy_shape,
    build_tachinomiya_config, build_trees_catering_config, build_tree_beauty_config,
)
from core.business_config.config_supply import supply, supply_batch
from core.business_config.loader import BusinessConfigRegistry

BATCH = ("tachinomiya", "catering", "beauty")


def ssot_of(bid):
    return BusinessConfigRegistry().load().get_business(bid)


def _no_secret(obj):
    blob = repr(obj)
    for pat in (r"sk-[A-Za-z0-9]{20,}", r"ghp_[A-Za-z0-9]{20,}", r"-----BEGIN",
                r"AIza[0-9A-Za-z_\-]{20,}"):
        if re.search(pat, blob):
            return False
    return True


class BuilderTest(unittest.TestCase):
    def test_01_builds_all_three(self):
        for f in (build_tachinomiya_config, build_trees_catering_config, build_tree_beauty_config):
            b = f()
            self.assertEqual(b.decision, "GO", b.issues)
            self.assertEqual(b.source, "SSOT")

    def test_02_input_not_mutated(self):
        legacy = get_config("tachinomiya")
        snapshot = copy.deepcopy(legacy)
        b = build_legacy_compatible_config("tachinomiya", ssot_of("tachinomiya"), legacy)
        self.assertEqual(legacy, snapshot)         # legacy untouched
        self.assertIsNot(b.config, legacy)         # new dict

    def test_03_no_secret_values(self):
        b = build_tachinomiya_config()
        self.assertTrue(_no_secret(b.config))

    def test_04_missing_required_field_fix(self):
        ssot = BusinessConfig.from_dict({
            "id": "tachinomiya", "slug": "tachinomiya", "business_type": "restaurant",
            "status": "ACTIVE", "active": True,
            "services": {"cloud_run_service": "tachinomiya-ai"}})  # no monthly_target
        b = build_legacy_compatible_config("tachinomiya", ssot, get_config("tachinomiya"))
        self.assertEqual(b.decision, "FIX")
        self.assertEqual(b.source, "FALLBACK_LEGACY")

    def test_05_type_mismatch_fix(self):
        ssot = BusinessConfig.from_dict({
            "id": "tachinomiya", "slug": "tachinomiya", "business_type": "restaurant",
            "status": "ACTIVE", "active": True, "monthly_target": "5500000",
            "services": {"cloud_run_service": "tachinomiya-ai"}})
        b = build_legacy_compatible_config("tachinomiya", ssot, get_config("tachinomiya"))
        self.assertEqual(b.decision, "FIX")

    def test_06_unknown_business_stop(self):
        b = build_legacy_compatible_config("xyz", ssot_of("tachinomiya"), {"a": 1})
        self.assertEqual(b.decision, "STOP")

    def test_34_cross_business_contamination_stop(self):
        b = build_legacy_compatible_config("tachinomiya", ssot_of("beauty"),
                                           get_config("tachinomiya"))
        self.assertEqual(b.decision, "STOP")

    def test_19_legacy_shape_compatible(self):
        for bid in BATCH:
            b = build_legacy_compatible_config(bid, ssot_of(bid), get_config(bid))
            ok, missing, tm = validate_legacy_shape(b.config, get_config(bid))
            self.assertTrue(ok, (bid, missing, tm))


class SupplyTest(unittest.TestCase):
    def test_07_unsupported_business_legacy(self):
        for bid in ("ryukyu_hinabe", "pasta_pasta", "z1"):
            r = supply(bid, mode="OWNER_APPROVED", owner_approved=True)
            self.assertEqual(r["runtime_source"], "LEGACY", bid)

    def test_08_ssot_only_stop(self):
        self.assertEqual(supply("tachinomiya", mode="SSOT_ONLY",
                                owner_approved=True)["decision"], "STOP")

    def test_09_unapproved_legacy(self):
        r = supply("tachinomiya", mode="AUTO", owner_approved=False)
        self.assertEqual(r["runtime_source"], "LEGACY")

    def test_10_approved_ssot(self):
        r = supply("tachinomiya", mode="OWNER_APPROVED", owner_approved=True)
        self.assertEqual(r["runtime_source"], "SSOT")
        self.assertEqual(r["decision"], "GO")

    def test_12_13_fallback_reason_present(self):
        # unsupported mode value etc. always carries a reason (no silent fallback)
        r = supply("tachinomiya", mode="BOGUS", owner_approved=True)
        self.assertEqual(r["decision"], "STOP")
        self.assertIsNotNone(r["fallback_reason"])


class TachinomiyaTest(unittest.TestCase):
    def setUp(self):
        self.reg = BusinessConfigRegistry().load()

    def test_14_15_16_targets(self):
        total, day, night = self.reg.get_monthly_target_breakdown("tachinomiya")
        self.assertEqual((total, day, night), (5500000, 2500000, 3000000))
        b = build_tachinomiya_config()
        self.assertEqual(b.config["monthly_target"], 5500000)

    def test_17_owner_staff_env_separated(self):
        s = ssot_of("tachinomiya")
        self.assertNotEqual(s.notification_policy.owner_channel_env,
                            s.notification_policy.staff_channel_env)
        self.assertEqual(s.notification_policy.owner_channel_env, "LINE_OWNER_TOKEN")

    def test_18_staff_send_requires_approval(self):
        self.assertTrue(self.reg.staff_send_requires_owner_approval("tachinomiya"))


class CateringBeautyTest(unittest.TestCase):
    def test_20_21_catering(self):
        b = build_trees_catering_config()
        self.assertEqual(b.decision, "GO")
        ok, _, _ = validate_legacy_shape(b.config, get_config("catering"))
        self.assertTrue(ok)

    def test_22_inactive_not_activated(self):
        # a business whose SSOT is INACTIVE must not be force-activated
        ssot = ssot_of("catering")
        inactive = BusinessConfig.from_dict(dict(ssot.raw, status="INACTIVE", active=False))
        legacy = dict(get_config("catering"))
        legacy["status"] = "inactive"
        b = build_legacy_compatible_config("catering", inactive, legacy)
        self.assertEqual(b.config["status"], "inactive")

    def test_23_env_names_only(self):
        self.assertTrue(_no_secret(build_trees_catering_config().config))

    def test_25_26_beauty(self):
        b = build_tree_beauty_config()
        self.assertEqual(b.decision, "GO")
        ok, _, _ = validate_legacy_shape(b.config, get_config("beauty"))
        self.assertTrue(ok)

    def test_27_beauty_active_state_preserved(self):
        legacy = get_config("beauty")
        b = build_tree_beauty_config()
        self.assertEqual(b.config["status"], legacy["status"])


class BatchTest(unittest.TestCase):
    def test_30_batch_go(self):
        bt = supply_batch(list(BATCH), mode="OWNER_APPROVED", owner_approved=True)
        self.assertEqual(bt["batch_decision"], "GO")
        for bid in BATCH:
            self.assertEqual(bt["results"][bid]["runtime_source"], "SSOT")

    def test_31_independent_results(self):
        # results are independent dict entries (no cross-write)
        bt = supply_batch(list(BATCH), mode="LEGACY_ONLY")
        ids = {bt["results"][b]["business_id"] for b in BATCH}
        self.assertEqual(ids, set(BATCH))

    def test_33_out_of_scope_legacy(self):
        bt = supply_batch(["ryukyu_hinabe", "pasta_pasta", "z1"],
                          mode="OWNER_APPROVED", owner_approved=True)
        for bid in ("ryukyu_hinabe", "pasta_pasta", "z1"):
            self.assertEqual(bt["results"][bid]["runtime_source"], "LEGACY")


class RollbackTest(unittest.TestCase):
    def test_35_legacy_only_all_legacy(self):
        for bid in BATCH:
            self.assertEqual(supply(bid, mode="LEGACY_ONLY")["runtime_source"], "LEGACY")

    def test_36_ssot_then_legacy(self):
        self.assertEqual(supply("tachinomiya", "OWNER_APPROVED", True)["runtime_source"], "SSOT")
        self.assertEqual(supply("tachinomiya", "LEGACY_ONLY")["runtime_source"], "LEGACY")


class SafetyTest(unittest.TestCase):
    def test_24_28_29_no_network(self):
        import socket

        class N(socket.socket):
            def __init__(self, *a, **k):
                raise AssertionError("net")
        orig = socket.socket
        socket.socket = N
        try:
            bt = supply_batch(list(BATCH), mode="OWNER_APPROVED", owner_approved=True)
            self.assertEqual(bt["batch_decision"], "GO")
        finally:
            socket.socket = orig

    def test_11_builder_exception_fallback(self):
        # bad repo_root → registry load fails → fallback legacy (with reason)
        import tempfile
        tmp = tempfile.mkdtemp()
        r = supply("tachinomiya", mode="OWNER_APPROVED", owner_approved=True, repo_root=tmp)
        self.assertEqual(r["runtime_source"], "FALLBACK_LEGACY")
        self.assertIsNotNone(r["fallback_reason"])


class CliTest(unittest.TestCase):
    def _cli(self):
        p = os.path.join(_REPO_ROOT, "scripts", "business_config",
                         "check_ssot_config_supply.py")
        spec = importlib.util.spec_from_file_location("ssup", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_cli_batch_legacy_rc0(self):
        self.assertEqual(self._cli().main(["--batch", "batch-1", "--mode", "LEGACY_ONLY"]), 0)

    def test_cli_batch_owner_rc0(self):
        self.assertEqual(self._cli().main(
            ["--batch", "batch-1", "--mode", "OWNER_APPROVED", "--owner-approved"]), 0)


if __name__ == "__main__":
    unittest.main()
