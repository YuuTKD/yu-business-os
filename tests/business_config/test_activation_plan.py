"""Phase B2-7 tests — production activation preparation + TACHINOMIYA technical
readiness. Read-only; no production ops; no command execution."""

import importlib.util
import os
import re
import sys
import types
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.business_config import production_plan as pp
from core.business_config.production_plan import (
    build_production_plan, build_batch, tachinomiya_technical_readiness,
    READY_THREE, PROJECT_ID, REGION, UNKNOWN)

SERVICES = {"catering": "trees-catering-ai", "beauty": "tree-beauty-ai",
            "ryukyu_hinabe": "ryukyu-hinabe-ai"}


def _no_secret(obj):
    blob = repr(obj)
    return not any(re.search(p, blob) for p in
                   (r"sk-[A-Za-z0-9]{20,}", r"ghp_[A-Za-z0-9]{20,}", r"-----BEGIN",
                    r"AIza[0-9A-Za-z_\-]{20,}"))


class PlanTest(unittest.TestCase):
    def test_01_02_03_three_plans_prepared(self):
        for b in READY_THREE:
            p = build_production_plan(b)
            self.assertEqual(p["decision"], "PREPARED", (b, p["blockers"]))
            self.assertEqual(p["cloud_run_service"], SERVICES[b])
            self.assertEqual(p["project_id"], PROJECT_ID)
            self.assertEqual(p["region"], REGION)

    def test_04_05_06_approvals(self):
        # catering deploy approved (scoped); scheduler/external always false
        self.assertTrue(build_production_plan("catering")["deploy_approved"])
        for b in ("beauty", "ryukyu_hinabe"):
            self.assertFalse(build_production_plan(b)["deploy_approved"], b)
        for b in READY_THREE:
            p = build_production_plan(b)
            self.assertFalse(p["scheduler_approved"])
            self.assertFalse(p["external_send_approved"])

    def test_07_command_execution_flag_false(self):
        p = build_production_plan("catering")
        self.assertFalse(p["command_candidates"]["execute"])
        for key in ("deploy_command", "env_update_command", "rollback_command"):
            self.assertIn("NOT EXECUTED", p["command_candidates"][key])

    def test_08_no_secret(self):
        self.assertTrue(_no_secret(build_batch(list(READY_THREE))))

    def test_09_unknown_service_placeholder(self):
        p = build_production_plan("ghost")           # unknown business
        self.assertEqual(p["cloud_run_service"], UNKNOWN)
        self.assertIn(UNKNOWN, p["command_candidates"]["deploy_command"])

    def test_10_missing_service_manual_check(self):
        # READY but no cloud_run_service → MANUAL_CHECK_REQUIRED (monkeypatched).
        import core.business_config.readiness as rd_mod
        import core.business_config.loader as loader_mod
        orig_assess = rd_mod.assess_business
        try:
            pp_ns = sys.modules["core.business_config.readiness"]
            pp_ns.assess_business = lambda *a, **k: {
                "readiness_decision": "READY", "blockers": []}

            class _Svc:  # stub business with no service
                class services:
                    cloud_run_service = None

            class _Reg:
                def get_business(self, _):
                    return _Svc()
            p = build_production_plan("catering", registry=_Reg())
            self.assertEqual(p["decision"], "MANUAL_CHECK_REQUIRED")
        finally:
            pp_ns.assess_business = orig_assess

    def test_11_12_13_rollback(self):
        bt = build_batch(list(READY_THREE))
        self.assertTrue(bt["rollback"]["all_rollback_ready"])
        self.assertIn("LEGACY_ONLY", bt["results"]["catering"]["rollback_steps"][0])

    def test_14_readiness_and_deploy_fields_separate(self):
        p = build_production_plan("catering")
        self.assertEqual(p["readiness"], "READY")
        self.assertTrue(p["deploy_approved"])           # deploy now approved (scoped)
        self.assertEqual(p["decision"], "PREPARED")

    def test_15_deploy_approval_only_catering(self):
        # catering deploy approved (scoped); beauty / ryukyu_hinabe not
        self.assertTrue(build_production_plan("catering")["deploy_approved"])
        for b in ("beauty", "ryukyu_hinabe"):
            self.assertFalse(build_production_plan(b)["deploy_approved"], b)

    def test_batch_prepared(self):
        self.assertEqual(build_batch(list(READY_THREE))["batch_decision"], "PREPARED")

    def test_out_of_scope_not_ready(self):
        for b in ("pasta_pasta", "z1", "tachinomiya"):
            self.assertEqual(build_production_plan(b)["decision"], "NOT_READY")


class TachinomiyaTechnicalTest(unittest.TestCase):
    def setUp(self):
        self.t = tachinomiya_technical_readiness()

    def test_16_token_env_name(self):
        self.assertEqual(self.t["threads_token"]["env_name"], "THREADS_ACCESS_TOKEN")
        self.assertTrue(self.t["threads_token"]["env_name_declared"])

    def test_17_token_no_value(self):
        self.assertTrue(_no_secret(self.t["threads_token"]))

    def test_18_token_manual_check(self):
        self.assertEqual(self.t["threads_token"]["status"], "MANUAL_CHECK_REQUIRED")

    def test_19_gbp_files_present(self):
        self.assertTrue(self.t["gbp"]["auth_files_present"])

    def test_20_gbp_no_value(self):
        self.assertTrue(_no_secret(self.t["gbp"]))

    def test_21_location_env_declared(self):
        self.assertEqual(self.t["gbp"]["location_env_name"], "GOOGLE_BUSINESS_LOCATION_ID")

    def test_22_gbp_manual_check(self):
        self.assertEqual(self.t["gbp"]["status"], "MANUAL_CHECK_REQUIRED")

    def test_23_photo_shortage_15(self):
        self.assertEqual(self.t["image"]["required_additions"], 15)

    def test_24_photo_pending_ready_when_confirmed(self):
        # monkeypatch the audit to report token+gbp CONFIRMED, only photos left.
        mod = sys.modules["core.business_config.tachinomiya_audit"]
        orig = mod.audit_tachinomiya
        try:
            mod.audit_tachinomiya = lambda *a, **k: {
                "threads_token": {"status": "CONFIRMED"},
                "gbp": {"status": "CONFIRMED"},
                "image": {"status": "PHOTO_PENDING"},
                "scheduler_expected": "OFF", "posting_executed": False}
            t = tachinomiya_technical_readiness()
            self.assertEqual(t["decision"], "PHOTO_PENDING_READY")
        finally:
            mod.audit_tachinomiya = orig

    def test_25_token_unconfirmed_manual_check(self):
        self.assertEqual(self.t["decision"], "MANUAL_CHECK_REQUIRED")

    def test_26_scheduler_off(self):
        self.assertEqual(self.t["scheduler_expected"], "OFF")

    def test_27_no_posting(self):
        self.assertFalse(self.t["posting_executed"])

    def test_28_no_line(self):
        self.assertFalse(self.t["line_sent"])


class SafetyTest(unittest.TestCase):
    def test_29_deploy_command_not_executed(self):
        p = build_production_plan("catering")
        self.assertFalse(p["command_candidates"]["execute"])

    def test_30_31_32_no_env_scheduler_or_send(self):
        p = build_production_plan("catering")
        self.assertTrue(p["deploy_required"])
        self.assertFalse(p["scheduler_approved"])
        self.assertFalse(p["external_send_approved"])

    def test_33_34_pasta_z1_unchanged(self):
        from core.business_config.config_supply import supply
        for b in ("pasta_pasta", "z1"):
            self.assertEqual(supply(b, "OWNER_APPROVED", True)["runtime_source"], "LEGACY")

    def test_36_no_secret_anywhere(self):
        self.assertTrue(_no_secret(tachinomiya_technical_readiness()))
        self.assertTrue(_no_secret(build_batch(list(READY_THREE))))

    def test_37_no_network(self):
        import socket

        class N(socket.socket):
            def __init__(self, *a, **k):
                raise AssertionError("net")
        orig = socket.socket
        socket.socket = N
        try:
            self.assertEqual(build_batch(list(READY_THREE))["batch_decision"], "PREPARED")
            self.assertEqual(tachinomiya_technical_readiness()["decision"],
                             "MANUAL_CHECK_REQUIRED")
        finally:
            socket.socket = orig


class CliTest(unittest.TestCase):
    def _cli(self, name):
        p = os.path.join(_REPO_ROOT, "scripts", "business_config", name)
        spec = importlib.util.spec_from_file_location("m_" + name.replace(".", "_"), p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_activation_plan_batch_rc0(self):
        self.assertEqual(self._cli("check_activation_plan.py").main(
            ["--batch", "ready-three"]), 0)

    def test_activation_plan_catering_rc0(self):
        self.assertEqual(self._cli("check_activation_plan.py").main(
            ["--business", "catering"]), 0)

    def test_tachinomiya_technical_rc1(self):
        self.assertEqual(self._cli("check_tachinomiya_technical_readiness.py").main([]), 1)


if __name__ == "__main__":
    unittest.main()
