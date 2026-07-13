"""Phase B2-6 tests — readiness approvals, TACHINOMIYA audit, activation dry run,
rollback. Read-only; no production ops."""

import os
import re
import shutil
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.business_config.approvals import ApprovalLedger
from core.business_config.readiness import assess_business, OPERATIONAL_REQUIREMENTS
from core.business_config.tachinomiya_audit import (
    audit_tachinomiya, audit_threads_token, audit_gbp, audit_image_inventory)
from core.business_config.activation import (
    dry_run_activation, dry_run_batch, verify_rollback, verify_batch_rollback,
    generate_activation_plan, SSOT_ENABLED)
from core.business_config.loader import BusinessConfigRegistry

APPROVED = ("catering", "beauty", "ryukyu_hinabe")
TACHI_OPS = set(OPERATIONAL_REQUIREMENTS["tachinomiya"])


def _no_secret(obj):
    blob = repr(obj)
    return not any(re.search(p, blob) for p in
                   (r"sk-[A-Za-z0-9]{20,}", r"ghp_[A-Za-z0-9]{20,}", r"-----BEGIN"))


def full_registry_with(extra_business=None):
    real = os.path.join(_REPO_ROOT, "configs", "businesses", "registry.yaml")
    tmp = tempfile.mkdtemp()
    dst = os.path.join(tmp, "configs", "businesses", "registry.yaml")
    os.makedirs(os.path.dirname(dst))
    shutil.copy(real, dst)
    if extra_business:
        with open(dst, "a", encoding="utf-8") as fh:
            fh.write(extra_business)
    return BusinessConfigRegistry(repo_root=tmp).load()


CLASH = (
    "\n  - id: clash\n    slug: clash\n    display_name: Clash\n"
    "    business_type: restaurant\n    status: ACTIVE\n    active: true\n"
    "    migration_status: SHADOW_DEFINED\n    services:\n"
    "      cloud_run_service: tachinomiya-ai\n"
    "    environment_variable_names:\n      - CLASH_SPREADSHEET_ID\n"
)


class ApprovalLedgerTest(unittest.TestCase):
    def setUp(self):
        self.led = ApprovalLedger().load()

    def test_01_02_03_readiness_approved(self):
        for b in APPROVED:
            self.assertTrue(self.led.is_readiness_approved(b), b)

    def test_04_deploy_approval_false(self):
        for b in APPROVED:
            self.assertFalse(self.led.is_deploy_approved(b), b)

    def test_05_scheduler_approval_false(self):
        for b in APPROVED:
            self.assertFalse(self.led.is_scheduler_approved(b), b)

    def test_06_external_send_approval_false(self):
        for b in APPROVED:
            self.assertFalse(self.led.is_external_send_approved(b), b)

    def test_07_scope_is_readiness(self):
        for b in APPROVED:
            self.assertEqual(self.led.approval_scope(b), "SSOT_PRODUCTION_READINESS")

    def test_08_unknown_business_not_approved(self):
        self.assertFalse(self.led.is_readiness_approved("nope"))
        self.assertFalse(self.led.is_readiness_approved("tachinomiya"))  # not in ledger

    def test_ledger_loads_clean(self):
        self.assertIsNone(self.led.load_error)
        self.assertEqual(self.led.issues(), [])

    def test_no_secret_in_ledger(self):
        self.assertTrue(_no_secret(self.led.get("catering")))


class ReadinessUpdateTest(unittest.TestCase):
    def test_09_10_11_three_ready(self):
        for b in APPROVED:
            self.assertEqual(assess_business(b)["readiness_decision"], "READY", b)

    def test_12_not_ready_if_supply_fails(self):
        r = assess_business("pasta_pasta")  # out of scope
        self.assertNotEqual(r["readiness_decision"], "READY")

    def test_13_owner_approval_required_when_unapproved(self):
        r = assess_business("catering", owner_approved=False)
        self.assertEqual(r["readiness_decision"], "OWNER_APPROVAL_REQUIRED")

    def test_14_secret_stop(self):
        secret = "ghp_" + ("A" * 30)
        reg = full_registry_with(extra_business=f"\n# {secret}\n")
        r = assess_business("catering", registry=reg)
        self.assertEqual(r["readiness_decision"], "STOP")


class TachinomiyaAuditTest(unittest.TestCase):
    def test_15_token_metadata(self):
        t = audit_threads_token()
        self.assertTrue(t["env_name_declared"])
        self.assertEqual(t["status"], "MANUAL_CHECK_REQUIRED")

    def test_16_token_no_value(self):
        self.assertTrue(_no_secret(audit_threads_token()))

    def test_17_gbp_status(self):
        g = audit_gbp()
        self.assertIn(g["status"], ("MANUAL_CHECK_REQUIRED", "MISSING"))

    def test_18_gbp_no_credentials_value(self):
        self.assertTrue(_no_secret(audit_gbp()))

    def test_19_image_shortage_preserved(self):
        img = audit_image_inventory()
        self.assertEqual(img["status"], "PHOTO_PENDING")
        self.assertEqual(set(img["priority_themes"]), {"interior", "drink", "exterior"})

    def test_20_photo_only_pending_ready(self):
        r = assess_business("tachinomiya",
                            operational_confirmed={"threads_token_verified", "gbp_auth_verified"})
        self.assertEqual(r["readiness_decision"], "PHOTO_PENDING_READY")

    def test_21_other_missing_almost_ready(self):
        r = assess_business("tachinomiya")  # nothing confirmed
        self.assertEqual(r["readiness_decision"], "ALMOST_READY")

    def test_22_scheduler_off(self):
        self.assertEqual(audit_tachinomiya()["scheduler_expected"], "OFF")

    def test_23_no_posting(self):
        self.assertFalse(audit_tachinomiya()["posting_executed"])


class ActivationDryRunTest(unittest.TestCase):
    def test_24_25_26_batch_no_deploy(self):
        bt = dry_run_batch(list(SSOT_ENABLED))
        for bid in SSOT_ENABLED:
            self.assertEqual(bt["results"][bid]["deploy_approval"], "NOT_APPROVED")
            self.assertNotEqual(bt["results"][bid]["decision"], "DRY_RUN_GO")  # no real activation

    def test_27_28_29_supply_fallback_rollback(self):
        r = dry_run_activation("catering")
        self.assertEqual(r["config_supply"], "GO")
        self.assertTrue(r["fallback"])
        self.assertTrue(r["rollback"])

    def test_30_independent(self):
        bt = dry_run_batch(list(SSOT_ENABLED))
        self.assertEqual(set(bt["results"].keys()), set(SSOT_ENABLED))

    def test_31_one_stop_batch_stop(self):
        reg = full_registry_with(extra_business=CLASH)  # contaminates tachinomiya
        bt = dry_run_batch(["tachinomiya", "catering"], registry=reg)
        self.assertEqual(bt["batch_decision"], "STOP")

    def test_32_readiness_blocked_tachinomiya(self):
        self.assertEqual(dry_run_activation("tachinomiya")["decision"], "READINESS_BLOCKED")

    def test_33_deploy_command_not_executed(self):
        r = dry_run_activation("catering")
        self.assertEqual(r["decision"], "DEPLOY_APPROVAL_REQUIRED")  # not DRY_RUN_GO
        self.assertIn("NOT EXECUTED", r["plan"]["deploy_command_candidate"])

    def test_ready_business_deploy_approval_required(self):
        for b in APPROVED:
            self.assertEqual(dry_run_activation(b)["decision"], "DEPLOY_APPROVAL_REQUIRED")


class RollbackTest(unittest.TestCase):
    def test_34_per_business_rollback(self):
        for b in SSOT_ENABLED:
            self.assertTrue(verify_rollback(b)["rollback_ready"], b)

    def test_35_batch_rollback(self):
        self.assertTrue(verify_batch_rollback(list(SSOT_ENABLED))["all_rollback_ready"])

    def test_36_legacy_only_method(self):
        self.assertIn("LEGACY_ONLY", verify_rollback("catering")["method"])

    def test_37_no_code_revert(self):
        self.assertFalse(verify_rollback("catering")["code_revert_required"])

    def test_38_alias_maintained(self):
        self.assertTrue(verify_rollback("ryukyu_hinabe")["alias_maintained"])


class SafetyTest(unittest.TestCase):
    def test_no_network(self):
        import socket

        class N(socket.socket):
            def __init__(self, *a, **k):
                raise AssertionError("net")
        orig = socket.socket
        socket.socket = N
        try:
            bt = dry_run_batch(list(SSOT_ENABLED))
            self.assertEqual(bt["batch_decision"], "READINESS_BLOCKED")
        finally:
            socket.socket = orig

    def test_no_secret_anywhere(self):
        self.assertTrue(_no_secret(dry_run_batch(list(SSOT_ENABLED))))
        self.assertTrue(_no_secret(generate_activation_plan("tachinomiya")))

    def test_pasta_z1_unchanged(self):
        from core.business_config.config_supply import supply
        for b in ("pasta_pasta", "z1"):
            self.assertEqual(supply(b, "OWNER_APPROVED", True)["runtime_source"], "LEGACY")


class CliTest(unittest.TestCase):
    def _cli(self, name):
        import importlib.util
        p = os.path.join(_REPO_ROOT, "scripts", "business_config", name)
        spec = importlib.util.spec_from_file_location("m_" + name.replace(".", "_"), p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_activation_cli_batch_rc1(self):
        # batch has tachinomiya READINESS_BLOCKED → exit 1
        self.assertEqual(self._cli("dry_run_ssot_activation.py").main(
            ["--batch", "ssot-enabled"]), 1)

    def test_activation_cli_catering_rc3(self):
        self.assertEqual(self._cli("dry_run_ssot_activation.py").main(
            ["--business", "catering"]), 3)

    def test_readiness_cli_catering_ready_rc0(self):
        self.assertEqual(self._cli("check_ssot_readiness.py").main(
            ["--business", "catering"]), 0)


if __name__ == "__main__":
    unittest.main()
