"""Comparator tests (Phase B1). Registry loaded from fixtures; legacy provided
by a FakeAdapter so the comparison logic is exercised deterministically."""

import os
import sys
import tempfile
import textwrap
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.business_config.loader import BusinessConfigRegistry
from core.business_config.comparator import compare
from core.business_config.models import LegacySource


def build_registry(text):
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "configs", "businesses", "registry.yaml")
    os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(text))
    return BusinessConfigRegistry(repo_root=tmp).load()


class FakeAdapter:
    def __init__(self, breg=None, ce=None, et=None):
        self._breg = breg or {}
        self._ce = ce or {}
        self._et = et or {}

    def business_registry(self):
        return LegacySource("business_registry", dict(self._breg))

    def content_engine(self):
        return LegacySource("content_engine", dict(self._ce))

    def executive_targets(self):
        return LegacySource("executive_team", dict(self._et))


ONE = """
version: 1
businesses:
  - id: alpha
    slug: alpha
    display_name: Alpha
    business_type: restaurant
    status: ACTIVE
    active: true
    timezone: Asia/Tokyo
    monthly_target: 800000
    migration_status: SHADOW_DEFINED
    services:
      cloud_run_service: alpha-ai
    environment_variable_names:
      - ALPHA_SPREADSHEET_ID
      - ALPHA_LINE_STAFF_TOKEN
"""

MATCH_LEGACY = {"alpha": {"slug": "alpha", "business_type": "restaurant",
                          "status": "active", "monthly_target": 800000,
                          "cloud_run_service": "alpha-ai",
                          "spreadsheet_id_env": "ALPHA_SPREADSHEET_ID",
                          "line_staff_env": "ALPHA_LINE_STAFF_TOKEN"}}


class ComparatorTest(unittest.TestCase):
    def test_22_exact_match_go(self):
        r = compare(build_registry(ONE), FakeAdapter(breg=MATCH_LEGACY))
        self.assertEqual(r.decision, "GO", [d.line() for d in r.differences])

    def test_23_registry_only_fix(self):
        r = compare(build_registry(ONE), FakeAdapter(breg={}))
        self.assertEqual(r.decision, "FIX")
        self.assertTrue(any(d.kind == "registry_only" for d in r.differences))

    def test_24_legacy_only_fix(self):
        legacy = dict(MATCH_LEGACY)
        legacy["beta"] = {"slug": "beta", "status": "active"}
        r = compare(build_registry(ONE), FakeAdapter(breg=legacy))
        self.assertEqual(r.decision, "FIX")
        self.assertTrue(any(d.kind == "legacy_only" for d in r.differences))

    def test_25_value_mismatch_fix(self):
        legacy = {"alpha": dict(MATCH_LEGACY["alpha"], monthly_target=999999)}
        r = compare(build_registry(ONE), FakeAdapter(breg=legacy))
        self.assertEqual(r.decision, "FIX")
        self.assertTrue(any(d.kind == "value_mismatch" for d in r.differences))

    def test_26_type_mismatch_fix(self):
        legacy = {"alpha": dict(MATCH_LEGACY["alpha"], business_type=123)}
        r = compare(build_registry(ONE), FakeAdapter(breg=legacy))
        self.assertEqual(r.decision, "FIX")
        self.assertTrue(any(d.kind == "type_mismatch" for d in r.differences))

    def test_27_active_mismatch_fix(self):
        legacy = {"alpha": dict(MATCH_LEGACY["alpha"], status="inactive")}
        r = compare(build_registry(ONE), FakeAdapter(breg=legacy))
        self.assertEqual(r.decision, "FIX")
        self.assertTrue(any(d.kind == "active_mismatch" for d in r.differences))

    def test_28_timezone_mismatch_fix(self):
        legacy = {"alpha": dict(MATCH_LEGACY["alpha"], timezone="America/New_York")}
        r = compare(build_registry(ONE), FakeAdapter(breg=legacy))
        self.assertEqual(r.decision, "FIX")
        self.assertTrue(any(d.field == "timezone" for d in r.differences))

    def test_29_service_mismatch_fix(self):
        legacy = {"alpha": dict(MATCH_LEGACY["alpha"], cloud_run_service="other-ai")}
        r = compare(build_registry(ONE), FakeAdapter(breg=legacy))
        self.assertEqual(r.decision, "FIX")
        self.assertTrue(any(d.field == "cloud_run_service" for d in r.differences))

    def test_30_cross_business_contamination_stop(self):
        two = ONE + """
  - id: beta
    slug: beta
    display_name: Beta
    business_type: restaurant
    status: ACTIVE
    active: true
    migration_status: SHADOW_DEFINED
    services:
      cloud_run_service: alpha-ai
    environment_variable_names:
      - BETA_SPREADSHEET_ID
"""
        r = compare(build_registry(two), FakeAdapter(breg={}))
        self.assertEqual(r.decision, "STOP")
        self.assertTrue(any(d.kind == "cross_business_contamination" for d in r.differences))

    def test_31_secret_value_stop(self):
        secret = "ghp_" + ("A" * 30)
        reg = build_registry(ONE + f'    metadata:\n      note: "{secret}"\n')
        r = compare(reg, FakeAdapter(breg=MATCH_LEGACY))
        self.assertEqual(r.decision, "STOP")

    def test_32_production_connected_stop(self):
        reg = build_registry(ONE.replace("migration_status: SHADOW_DEFINED",
                                         "migration_status: PRODUCTION_CONNECTED"))
        r = compare(reg, FakeAdapter(breg=MATCH_LEGACY))
        self.assertEqual(r.decision, "STOP")

    def test_executive_target_mismatch_fix(self):
        et = {"Alpha": {"display_name": "Alpha", "target": 111111}}
        r = compare(build_registry(ONE), FakeAdapter(breg=MATCH_LEGACY, et=et))
        self.assertEqual(r.decision, "FIX")
        self.assertTrue(any(d.field == "monthly_target" for d in r.differences))


if __name__ == "__main__":
    unittest.main()
