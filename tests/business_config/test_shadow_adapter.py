"""TACHINOMIYA SSOT Shadow Adapter tests (Phase B2-1)."""

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
from core.business_config.shadow_adapter import compare_tachinomiya, ShadowMode

# A legacy dict that matches the real SSOT for TACHINOMIYA.
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


def build_registry(total=5500000, day=2500000, night=3000000, migration="SHADOW_DEFINED"):
    tmp = tempfile.mkdtemp()
    p = os.path.join(tmp, "configs", "businesses", "registry.yaml")
    os.makedirs(os.path.dirname(p))
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(TACHI_BLOCK).format(
            total=total, day=day, night=night, migration=migration))
    return BusinessConfigRegistry(repo_root=tmp).load()


class ModeTest(unittest.TestCase):
    def setUp(self):
        self.reg = build_registry()

    def test_01_off_legacy_only(self):
        r = compare_tachinomiya(mode="OFF", registry=self.reg, legacy_override=MATCH_LEGACY)
        self.assertEqual(r["decision"], "GO")
        self.assertEqual(r["runtime_source"], "LEGACY")
        self.assertIn("not read", r["ssot_source"])

    def test_02_shadow_only_compares(self):
        r = compare_tachinomiya(mode="SHADOW_ONLY", registry=self.reg, legacy_override=MATCH_LEGACY)
        self.assertEqual(r["decision"], "GO")
        self.assertEqual(r["mismatch_count"], 0)

    def test_03_shadow_only_runtime_legacy(self):
        r = compare_tachinomiya(mode="SHADOW_ONLY", registry=self.reg, legacy_override=MATCH_LEGACY)
        self.assertEqual(r["runtime_source"], "LEGACY")

    def test_04_enforce_zero_mismatch_go(self):
        r = compare_tachinomiya(mode="ENFORCE_COMPARE", registry=self.reg, legacy_override=MATCH_LEGACY)
        self.assertEqual(r["decision"], "GO")

    def test_05_mismatch_shadow_fix_enforce_stop(self):
        bad = dict(MATCH_LEGACY, display_name="WRONG NAME")
        self.assertEqual(compare_tachinomiya("SHADOW_ONLY", self.reg, bad)["decision"], "FIX")
        self.assertEqual(compare_tachinomiya("ENFORCE_COMPARE", self.reg, bad)["decision"], "STOP")

    def test_16_unknown_mode_stop(self):
        r = compare_tachinomiya(mode="TURBO", registry=self.reg, legacy_override=MATCH_LEGACY)
        self.assertEqual(r["decision"], "STOP")

    def test_17_runtime_source_never_ssot(self):
        for mode in ("OFF", "SHADOW_ONLY", "ENFORCE_COMPARE"):
            r = compare_tachinomiya(mode=mode, registry=self.reg, legacy_override=MATCH_LEGACY)
            self.assertEqual(r["runtime_source"], "LEGACY")


class TargetTest(unittest.TestCase):
    def test_06_07_08_targets(self):
        reg = BusinessConfigRegistry().load()
        total, day, night = reg.get_monthly_target_breakdown("tachinomiya")
        self.assertEqual(total, 5500000)
        self.assertEqual(day, 2500000)
        self.assertEqual(night, 3000000)
        r = compare_tachinomiya("ENFORCE_COMPARE", reg, MATCH_LEGACY)
        self.assertEqual(r["decision"], "GO")

    def test_09_breakdown_mismatch_stop(self):
        reg = build_registry(total=5500000, day=1000000, night=1000000)  # 2M != 5.5M
        r = compare_tachinomiya("SHADOW_ONLY", reg, MATCH_LEGACY)
        self.assertEqual(r["decision"], "STOP")
        self.assertTrue(any(m["field"] == "monthly_target_breakdown" for m in r["mismatches"]))


class ContaminationTest(unittest.TestCase):
    def test_10_other_business_service_stop(self):
        reg = build_registry()
        bad = dict(MATCH_LEGACY, cloud_run_service="ryukyu-hinabe-ai")
        r = compare_tachinomiya("SHADOW_ONLY", reg, bad)
        self.assertEqual(r["decision"], "STOP")
        self.assertTrue(any(m["field"] == "cloud_run_service" and m["severity"] == "STOP"
                            for m in r["mismatches"]))

    def test_production_connected_stop(self):
        reg = build_registry(migration="PRODUCTION_CONNECTED")
        # loader rejects PRODUCTION_CONNECTED → tachinomiya not loaded → INTERNAL_ERROR
        r = compare_tachinomiya("SHADOW_ONLY", reg, MATCH_LEGACY)
        self.assertIn(r["decision"], ("STOP", "INTERNAL_ERROR"))


class LineTest(unittest.TestCase):
    def setUp(self):
        self.reg = BusinessConfigRegistry().load()

    def test_11_owner_env_name(self):
        self.assertEqual(self.reg.get_owner_channel_env("tachinomiya"), "LINE_OWNER_TOKEN")

    def test_12_staff_canonical(self):
        self.assertEqual(self.reg.get_staff_channel_env("tachinomiya"),
                         "LINE_TACHINOMIYA_STAFF_TOKEN")

    def test_13_legacy_alias_allowed(self):
        alias_legacy = dict(MATCH_LEGACY, line_staff_env="LINE_TACHINOMIYASTAFF_TOKEN")
        r = compare_tachinomiya("ENFORCE_COMPARE", self.reg, alias_legacy)
        self.assertEqual(r["decision"], "GO")


class SafetyTest(unittest.TestCase):
    def setUp(self):
        self.reg = BusinessConfigRegistry().load()

    def test_14_no_token_values_in_result(self):
        r = compare_tachinomiya("SHADOW_ONLY", self.reg, MATCH_LEGACY)
        blob = repr(r)
        for pat in (r"sk-[A-Za-z0-9]{20,}", r"ghp_[A-Za-z0-9]{20,}", r"-----BEGIN"):
            self.assertIsNone(re.search(pat, blob))

    def test_18_no_heavy_import(self):
        sys.modules.pop("core.multi_business_content_engine", None)
        compare_tachinomiya("SHADOW_ONLY", self.reg, MATCH_LEGACY)
        self.assertNotIn("core.multi_business_content_engine", sys.modules)

    def test_19_no_network(self):
        import socket

        class N(socket.socket):
            def __init__(self, *a, **k):
                raise AssertionError("net")
        orig = socket.socket
        socket.socket = N
        try:
            r = compare_tachinomiya("SHADOW_ONLY", self.reg, MATCH_LEGACY)
            self.assertEqual(r["decision"], "GO")
        finally:
            socket.socket = orig

    def test_internal_error_on_missing_config(self):
        tmp = tempfile.mkdtemp()  # no registry, no business_registry.py
        r = compare_tachinomiya("SHADOW_ONLY", repo_root=tmp)
        self.assertIn(r["decision"], ("INTERNAL_ERROR", "STOP"))


class CliTest(unittest.TestCase):
    def _load_cli(self):
        p = os.path.join(_REPO_ROOT, "scripts", "business_config",
                         "check_tachinomiya_shadow.py")
        spec = importlib.util.spec_from_file_location("chk", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_20_cli_go_exit_0(self):
        self.assertEqual(self._load_cli().main(["--mode", "SHADOW_ONLY"]), 0)

    def test_cli_enforce_go(self):
        self.assertEqual(self._load_cli().main(["--mode", "ENFORCE_COMPARE"]), 0)


if __name__ == "__main__":
    unittest.main()
