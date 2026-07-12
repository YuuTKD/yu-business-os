"""Phase B2-5 tests — SSOT production readiness gate (4 businesses)."""

import importlib.util
import os
import re
import sys
import tempfile
import textwrap
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.business_config.loader import BusinessConfigRegistry
from core.business_config.readiness import (
    assess_business, assess_batch, SSOT_ENABLED, OPERATIONAL_REQUIREMENTS)

FOUR = ("tachinomiya", "catering", "beauty", "ryukyu_hinabe")
TACHI_OPS = set(OPERATIONAL_REQUIREMENTS["tachinomiya"])


def full_registry_with(tachi_overrides=None, extra_business=None):
    """Write a temp registry.yaml (copy of real + overrides) and load it."""
    import shutil
    real = os.path.join(_REPO_ROOT, "configs", "businesses", "registry.yaml")
    tmp = tempfile.mkdtemp()
    dst = os.path.join(tmp, "configs", "businesses", "registry.yaml")
    os.makedirs(os.path.dirname(dst))
    shutil.copy(real, dst)
    text = open(dst, encoding="utf-8").read()
    if tachi_overrides:
        for old, new in tachi_overrides:
            text = text.replace(old, new, 1)
    if extra_business:
        text += extra_business
    open(dst, "w", encoding="utf-8").write(text)
    return BusinessConfigRegistry(repo_root=tmp).load()


class BasicTest(unittest.TestCase):
    def test_01_02_03_04_four_businesses(self):
        for bid in FOUR:
            r = assess_business(bid, owner_approved=True,
                                operational_confirmed=set(OPERATIONAL_REQUIREMENTS[bid]))
            self.assertEqual(r["config_supply"], "GO", bid)         # supply
            self.assertEqual(r["runtime_source"], "SSOT", bid)      # ssot
            self.assertTrue(r["legacy_fallback"], bid)             # fallback
            self.assertTrue(r["rollback_ready"], bid)              # rollback

    def test_09_owner_approval_required(self):
        r = assess_business("catering", owner_approved=False)
        self.assertEqual(r["readiness_decision"], "OWNER_APPROVAL_REQUIRED")

    def test_10_almost_ready(self):
        r = assess_business("tachinomiya", owner_approved=True)  # ops unconfirmed
        self.assertEqual(r["readiness_decision"], "ALMOST_READY")
        self.assertTrue(r["missing_requirements"])

    def test_12_ready_all_satisfied(self):
        r = assess_business("tachinomiya", owner_approved=True,
                            operational_confirmed=TACHI_OPS)
        self.assertEqual(r["readiness_decision"], "READY")
        r2 = assess_business("catering", owner_approved=True)
        self.assertEqual(r2["readiness_decision"], "READY")


class StopTest(unittest.TestCase):
    def test_08_production_write_stop(self):
        r = assess_business("tachinomiya", owner_approved=True, production_write=True)
        self.assertEqual(r["readiness_decision"], "STOP")

    def test_05_secret_like_stop(self):
        secret = "ghp_" + ("A" * 30)
        reg = full_registry_with(tachi_overrides=[
            ("notes: Scheduler currently OFF", f"notes: {secret} OFF")])
        r = assess_business("tachinomiya", owner_approved=True, registry=reg)
        self.assertEqual(r["readiness_decision"], "STOP")

    def test_06_cross_business_contamination_stop(self):
        # a second business sharing tachinomiya's cloud_run_service → contamination.
        # 2-space list-item indentation so it parses as a businesses[] entry.
        extra = (
            "\n"
            "  - id: clash\n"
            "    slug: clash\n"
            "    display_name: Clash\n"
            "    business_type: restaurant\n"
            "    status: ACTIVE\n"
            "    active: true\n"
            "    migration_status: SHADOW_DEFINED\n"
            "    services:\n"
            "      cloud_run_service: tachinomiya-ai\n"
            "    environment_variable_names:\n"
            "      - CLASH_SPREADSHEET_ID\n"
        )
        reg = full_registry_with(extra_business=extra)
        # sanity: the fixture actually loaded the clashing business
        self.assertIsNotNone(reg.get_business("clash"))
        r = assess_business("tachinomiya", owner_approved=True, registry=reg)
        self.assertEqual(r["readiness_decision"], "STOP")

    def test_07_ssot_only_rejected_at_supply(self):
        from core.business_config.config_supply import supply
        self.assertEqual(supply("tachinomiya", "SSOT_ONLY", True)["decision"], "STOP")

    def test_11_not_ready_on_mismatch(self):
        reg = full_registry_with(tachi_overrides=[
            ("monthly_target: 5500000", "monthly_target: 4444444")])
        r = assess_business("tachinomiya", owner_approved=True, registry=reg)
        self.assertIn(r["readiness_decision"], ("NOT_READY", "STOP"))
        self.assertNotEqual(r["readiness_decision"], "READY")

    def test_22_batch_stop_if_one_stop(self):
        bt = assess_batch(["tachinomiya", "catering"], owner_approved=True)
        # inject a production_write STOP into one via direct assess
        stop = assess_business("tachinomiya", owner_approved=True, production_write=True)
        decisions = [bt["results"]["catering"]["readiness_decision"],
                     stop["readiness_decision"]]
        self.assertIn("STOP", decisions)


class BusinessSpecificTest(unittest.TestCase):
    def setUp(self):
        self.reg = BusinessConfigRegistry().load()

    def test_13_tachinomiya_targets(self):
        self.assertEqual(self.reg.get_monthly_target_breakdown("tachinomiya"),
                         (5500000, 2500000, 3000000))
        r = assess_business("tachinomiya", owner_approved=True,
                            operational_confirmed=TACHI_OPS)
        self.assertNotIn("tachinomiya_target_mismatch", r["blockers"])

    def test_14_tachinomiya_staff_gated(self):
        self.assertTrue(self.reg.staff_send_requires_owner_approval("tachinomiya"))
        r = assess_business("tachinomiya", owner_approved=True,
                            operational_confirmed=TACHI_OPS)
        self.assertNotIn("staff_notify_not_gated", r["blockers"])

    def test_15_catering_no_activation(self):
        r = assess_business("catering", owner_approved=True)
        self.assertIn("no_service_activation_by_supply", r["warnings"])

    def test_16_beauty_status_preserved(self):
        from configs.business_registry import get
        from core.business_config.config_builder import build_tree_beauty_config
        self.assertEqual(build_tree_beauty_config().config["status"], get("beauty")["status"])

    def test_17_hinabe_gbp_excluded(self):
        r = assess_business("ryukyu_hinabe", owner_approved=True)
        self.assertIn("gbp_automation_excluded", r["warnings"])

    def test_18_hinabe_alias_maintained(self):
        self.assertEqual(self.reg.resolve_slug("hinabe"), "ryukyu_hinabe")


class OutOfScopeTest(unittest.TestCase):
    def test_19_pasta_pasta_not_ready(self):
        r = assess_business("pasta_pasta", owner_approved=True)
        self.assertEqual(r["readiness_decision"], "NOT_READY")
        self.assertIn("out_of_ssot_scope", r["blockers"])

    def test_20_z1_not_ready(self):
        r = assess_business("z1", owner_approved=True)
        self.assertEqual(r["readiness_decision"], "NOT_READY")

    def test_pasta_z1_supply_still_legacy(self):
        from core.business_config.config_supply import supply
        for b in ("pasta_pasta", "z1"):
            self.assertEqual(supply(b, "OWNER_APPROVED", True)["runtime_source"], "LEGACY")


class BatchTest(unittest.TestCase):
    def test_21_batch_decision(self):
        bt = assess_batch(list(SSOT_ENABLED), owner_approved=False)
        # tachinomiya ALMOST_READY present → NEEDS_WORK
        self.assertEqual(bt["batch_decision"], "NEEDS_WORK")

    def test_batch_all_ready_when_confirmed(self):
        conf = {"tachinomiya": TACHI_OPS}
        bt = assess_batch(list(SSOT_ENABLED), owner_approved=True,
                          operational_confirmed=conf)
        self.assertEqual(bt["batch_decision"], "READY")


class SafetyTest(unittest.TestCase):
    def test_24_no_network(self):
        import socket

        class N(socket.socket):
            def __init__(self, *a, **k):
                raise AssertionError("net")
        orig = socket.socket
        socket.socket = N
        try:
            bt = assess_batch(list(SSOT_ENABLED), owner_approved=True,
                              operational_confirmed={"tachinomiya": TACHI_OPS})
            self.assertEqual(bt["batch_decision"], "READY")
        finally:
            socket.socket = orig

    def test_25_no_secret_in_result(self):
        r = assess_business("tachinomiya", owner_approved=True)
        blob = repr({k: v for k, v in r.items()})
        for pat in (r"sk-[A-Za-z0-9]{20,}", r"ghp_[A-Za-z0-9]{20,}", r"-----BEGIN"):
            self.assertIsNone(re.search(pat, blob))


class CliTest(unittest.TestCase):
    def _cli(self):
        p = os.path.join(_REPO_ROOT, "scripts", "business_config",
                         "check_ssot_readiness.py")
        spec = importlib.util.spec_from_file_location("rdy", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_cli_batch_rc1_almost_ready(self):
        # batch has tachinomiya ALMOST_READY → exit 1
        self.assertEqual(self._cli().main(["--batch", "ssot-enabled"]), 1)

    def test_cli_catering_rc0(self):
        self.assertEqual(self._cli().main(["--business", "catering"]), 0)


if __name__ == "__main__":
    unittest.main()
