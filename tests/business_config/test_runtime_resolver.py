"""TACHINOMIYA Runtime Resolver tests (Phase B2-2)."""

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
from core.business_config.runtime_resolver import resolve, RuntimeMode
from core.business_config.models import BusinessConfig

MATCH_LEGACY = {
    "slug": "tachinomiya", "display_name": "TACHINOMIYA", "business_type": "restaurant",
    "status": "active", "active": True, "monthly_target": 5500000,
    "cloud_run_service": "tachinomiya-ai", "spreadsheet_id_env": "TACHINOMIYA_SPREADSHEET_ID",
    "line_staff_env": "TACHINOMIYA_LINE_STAFF_TOKEN",
    "platforms": ["google", "instagram", "threads", "line"], "timezone": None,
    "_other_services": {"tree-beauty-ai", "ryukyu-hinabe-ai"},
}

TACHI_BLOCK = """
version: 1
businesses:
  - id: tachinomiya
    slug: tachinomiya
    display_name: TACHINOMIYA
    business_type: restaurant
    status: ACTIVE
    active: true
    monthly_target: {total}
    monthly_target_day: {day}
    monthly_target_night: {night}
    migration_status: {migration}
    services:
      cloud_run_service: tachinomiya-ai
    notification_policy:
      owner_channel_env: LINE_OWNER_TOKEN
      staff_channel_env: LINE_TACHINOMIYA_STAFF_TOKEN
    posting_policy:
      platforms:
        - google
        - instagram
        - threads
        - line
    environment_variable_names:
      - TACHINOMIYA_SPREADSHEET_ID
      - LINE_TACHINOMIYA_STAFF_TOKEN
      - LINE_OWNER_TOKEN
    environment_variable_aliases:
      LINE_TACHINOMIYASTAFF_TOKEN: LINE_TACHINOMIYA_STAFF_TOKEN
      TACHINOMIYA_LINE_STAFF_TOKEN: LINE_TACHINOMIYA_STAFF_TOKEN
"""

SSOT_PRIMARY = RuntimeMode.SSOT_PRIMARY_WITH_LEGACY_FALLBACK.value


def build_registry(total=5500000, day=2500000, night=3000000, migration="SHADOW_DEFINED"):
    tmp = tempfile.mkdtemp()
    p = os.path.join(tmp, "configs", "businesses", "registry.yaml")
    os.makedirs(os.path.dirname(p))
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(TACHI_BLOCK).format(
            total=total, day=day, night=night, migration=migration))
    return BusinessConfigRegistry(repo_root=tmp).load()


def r(mode, approved=False, reg=None, legacy=MATCH_LEGACY, business_id="tachinomiya"):
    return resolve(business_id=business_id, mode=mode, owner_approved=approved,
                   registry=reg if reg is not None else build_registry(),
                   legacy_override=legacy)


class ModeTest(unittest.TestCase):
    def test_01_legacy_only(self):
        self.assertEqual(r("LEGACY_ONLY")["runtime_source"], "LEGACY")

    def test_02_shadow_only_legacy(self):
        self.assertEqual(r("SHADOW_ONLY")["runtime_source"], "LEGACY")

    def test_03_ssot_primary_unapproved(self):
        self.assertEqual(r(SSOT_PRIMARY)["decision"], "OWNER_APPROVAL_REQUIRED")

    def test_04_ssot_primary_approved_source(self):
        res = r(SSOT_PRIMARY, approved=True)
        self.assertEqual(res["decision"], "GO")
        self.assertEqual(res["runtime_source"], "SSOT")

    def test_05_mismatch_zero_uses_ssot(self):
        res = r(SSOT_PRIMARY, approved=True)
        self.assertEqual(res["mismatch_count"], 0)
        self.assertEqual(res["runtime_source"], "SSOT")

    def test_19_ssot_only_stop(self):
        self.assertEqual(r("SSOT_ONLY", approved=True)["decision"], "STOP")

    def test_20_unknown_mode_stop(self):
        self.assertEqual(r("TURBO", approved=True)["decision"], "STOP")


class FallbackTest(unittest.TestCase):
    def test_06_ssot_load_failure_fallback(self):
        tmp = tempfile.mkdtemp()  # empty → registry load fails
        reg = BusinessConfigRegistry(repo_root=tmp).load()
        res = resolve("tachinomiya", SSOT_PRIMARY, owner_approved=True,
                      registry=reg, legacy_override=MATCH_LEGACY)
        self.assertEqual(res["decision"], "GO_WITH_FALLBACK")
        self.assertEqual(res["runtime_source"], "LEGACY")
        self.assertTrue(res["fallback_used"])
        self.assertIsNotNone(res["fallback_reason"])

    def test_24_fallback_config_is_legacy(self):
        tmp = tempfile.mkdtemp()
        reg = BusinessConfigRegistry(repo_root=tmp).load()
        res = resolve("tachinomiya", SSOT_PRIMARY, owner_approved=True,
                      registry=reg, legacy_override=MATCH_LEGACY)
        self.assertEqual(res["config"], MATCH_LEGACY)

    def test_25_ssot_config_is_business_config(self):
        res = r(SSOT_PRIMARY, approved=True)
        self.assertIsInstance(res["config"], BusinessConfig)


class MismatchTest(unittest.TestCase):
    def test_08_mismatch_stop_or_fix_not_fallback(self):
        bad = dict(MATCH_LEGACY, display_name="WRONG")
        res = r(SSOT_PRIMARY, approved=True, legacy=bad)
        self.assertEqual(res["decision"], "FIX")             # not GO_WITH_FALLBACK
        self.assertFalse(res["fallback_used"])
        self.assertEqual(res["runtime_source"], "LEGACY")

    def test_09_cross_business_stop(self):
        bad = dict(MATCH_LEGACY, cloud_run_service="ryukyu-hinabe-ai")
        res = r(SSOT_PRIMARY, approved=True, legacy=bad)
        self.assertEqual(res["decision"], "STOP")

    def test_13_breakdown_mismatch_stop(self):
        reg = build_registry(total=5500000, day=1, night=1)
        res = r(SSOT_PRIMARY, approved=True, reg=reg)
        self.assertEqual(res["decision"], "STOP")


class TargetLineTest(unittest.TestCase):
    def setUp(self):
        self.reg = BusinessConfigRegistry().load()

    def test_10_11_12_targets(self):
        total, day, night = self.reg.get_monthly_target_breakdown("tachinomiya")
        self.assertEqual((total, day, night), (5500000, 2500000, 3000000))

    def test_14_owner_env(self):
        self.assertEqual(self.reg.get_owner_channel_env("tachinomiya"), "LINE_OWNER_TOKEN")

    def test_15_staff_canonical(self):
        self.assertEqual(self.reg.get_staff_channel_env("tachinomiya"),
                         "LINE_TACHINOMIYA_STAFF_TOKEN")

    def test_16_legacy_alias_preserved(self):
        # legacy alias still resolves and does not break SSOT-primary
        alias_legacy = dict(MATCH_LEGACY, line_staff_env="LINE_TACHINOMIYASTAFF_TOKEN")
        res = resolve("tachinomiya", SSOT_PRIMARY, owner_approved=True,
                      registry=BusinessConfigRegistry().load(), legacy_override=alias_legacy)
        self.assertEqual(res["runtime_source"], "SSOT")


class OtherBusinessTest(unittest.TestCase):
    def test_21_other_business_legacy(self):
        res = resolve("catering", "LEGACY_ONLY", owner_approved=True)
        self.assertEqual(res["runtime_source"], "LEGACY")

    def test_22_other_business_ssot_primary_stop(self):
        res = resolve("catering", SSOT_PRIMARY, owner_approved=True)
        self.assertEqual(res["decision"], "STOP")


class SafetyTest(unittest.TestCase):
    def test_17_18_no_secret_values(self):
        res = r(SSOT_PRIMARY, approved=True)
        # strip the config object (BusinessConfig) before scanning the log view
        log_view = {k: v for k, v in res.items() if k != "config"}
        blob = repr(log_view)
        for pat in (r"sk-[A-Za-z0-9]{20,}", r"ghp_[A-Za-z0-9]{20,}", r"-----BEGIN"):
            self.assertIsNone(re.search(pat, blob))

    def test_23_fallback_reason_present(self):
        tmp = tempfile.mkdtemp()
        reg = BusinessConfigRegistry(repo_root=tmp).load()
        res = resolve("tachinomiya", SSOT_PRIMARY, owner_approved=True,
                      registry=reg, legacy_override=MATCH_LEGACY)
        self.assertTrue(res["fallback_reason"])

    def test_26_no_network(self):
        import socket

        class N(socket.socket):
            def __init__(self, *a, **k):
                raise AssertionError("net")
        orig = socket.socket
        socket.socket = N
        try:
            self.assertEqual(r(SSOT_PRIMARY, approved=True)["runtime_source"], "SSOT")
        finally:
            socket.socket = orig

    def test_27_no_heavy_import(self):
        sys.modules.pop("core.multi_business_content_engine", None)
        r(SSOT_PRIMARY, approved=True)
        self.assertNotIn("core.multi_business_content_engine", sys.modules)


class CliTest(unittest.TestCase):
    def _cli(self):
        p = os.path.join(_REPO_ROOT, "scripts", "business_config",
                         "check_tachinomiya_runtime.py")
        spec = importlib.util.spec_from_file_location("rtc", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_28_cli_unapproved_rc20(self):
        self.assertEqual(self._cli().main(
            ["--mode", "SSOT_PRIMARY_WITH_LEGACY_FALLBACK"]), 20)

    def test_29_cli_approved_rc0(self):
        self.assertEqual(self._cli().main(
            ["--mode", "SSOT_PRIMARY_WITH_LEGACY_FALLBACK", "--owner-approved"]), 0)


if __name__ == "__main__":
    unittest.main()
