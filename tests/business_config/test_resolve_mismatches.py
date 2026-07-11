"""Phase B1.1 tests — resolved SSOT mismatches (targets, aliases, LINE, cycles)."""

import os
import sys
import tempfile
import textwrap
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.business_config.loader import BusinessConfigRegistry
from core.business_config.legacy_adapter import LegacyAdapter
from core.business_config.comparator import compare


def build(text):
    tmp = tempfile.mkdtemp()
    p = os.path.join(tmp, "configs", "businesses", "registry.yaml")
    os.makedirs(os.path.dirname(p))
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(text))
    return BusinessConfigRegistry(repo_root=tmp).load()


ALIASED = """
version: 1
businesses:
  - id: ryukyu_hinabe
    slug: ryukyu_hinabe
    display_name: 琉球火鍋
    business_type: restaurant
    status: ACTIVE
    active: true
    migration_status: SHADOW_DEFINED
    slug_aliases:
      - hinabe
    notification_policy:
      owner_channel_env: LINE_OWNER_TOKEN
      staff_channel_env: HINABE_LINE_STAFF_TOKEN
    environment_variable_names:
      - HINABE_LINE_STAFF_TOKEN
      - LINE_OWNER_TOKEN
    environment_variable_aliases:
      LINE_hinabeSTAFF_TOKEN: HINABE_LINE_STAFF_TOKEN
"""

TACHI = """
version: 1
businesses:
  - id: tachinomiya
    slug: tachinomiya
    display_name: TACHINOMIYA
    business_type: restaurant
    status: ACTIVE
    active: true
    migration_status: SHADOW_DEFINED
    monthly_target: 5500000
    monthly_target_day: 2500000
    monthly_target_night: 3000000
    notification_policy:
      owner_channel_env: LINE_OWNER_TOKEN
      staff_channel_env: LINE_TACHINOMIYA_STAFF_TOKEN
    environment_variable_names:
      - LINE_TACHINOMIYA_STAFF_TOKEN
      - LINE_OWNER_TOKEN
    environment_variable_aliases:
      LINE_TACHINOMIYASTAFF_TOKEN: LINE_TACHINOMIYA_STAFF_TOKEN
"""


class TargetTest(unittest.TestCase):
    def setUp(self):
        self.reg = BusinessConfigRegistry().load()

    def test_01_day_target(self):
        _, day, _ = self.reg.get_monthly_target_breakdown("tachinomiya")
        self.assertEqual(day, 2500000)

    def test_02_night_target(self):
        _, _, night = self.reg.get_monthly_target_breakdown("tachinomiya")
        self.assertEqual(night, 3000000)

    def test_03_total_target(self):
        total, _, _ = self.reg.get_monthly_target_breakdown("tachinomiya")
        self.assertEqual(total, 5500000)

    def test_04_breakdown_mismatch_fix(self):
        reg = build(TACHI.replace("monthly_target: 5500000", "monthly_target: 9999999"))
        self.assertEqual(reg.validate().decision, "FIX")


class AliasTest(unittest.TestCase):
    def setUp(self):
        self.reg = BusinessConfigRegistry().load()

    def test_05_canonical_id(self):
        self.assertIsNotNone(self.reg.get_business("ryukyu_hinabe"))

    def test_06_hinabe_alias_resolves(self):
        self.assertEqual(self.reg.resolve_slug("hinabe"), "ryukyu_hinabe")
        self.assertEqual(self.reg.get_business_by_slug("hinabe").id, "ryukyu_hinabe")

    def test_07_alias_cycle_stop(self):
        reg = build("""
            version: 1
            businesses:
              - id: x
                slug: x
                display_name: X
                business_type: t
                status: ACTIVE
                active: true
                migration_status: SHADOW_DEFINED
                environment_variable_names:
                  - A_TOKEN
                  - B_TOKEN
                environment_variable_aliases:
                  A_TOKEN: B_TOKEN
                  B_TOKEN: A_TOKEN
        """)
        self.assertEqual(reg.validate().decision, "STOP")

    def test_08_unknown_alias_target_fix(self):
        reg = build("""
            version: 1
            businesses:
              - id: x
                slug: x
                display_name: X
                business_type: t
                status: ACTIVE
                active: true
                migration_status: SHADOW_DEFINED
                environment_variable_names:
                  - CANON_TOKEN
                environment_variable_aliases:
                  LEGACY_TOKEN: NOT_A_CANONICAL
        """)
        self.assertEqual(reg.validate().decision, "FIX")

    def test_slug_alias_collision_stop(self):
        reg = build("""
            version: 1
            businesses:
              - id: a
                slug: a
                display_name: A
                business_type: t
                status: ACTIVE
                active: true
                migration_status: SHADOW_DEFINED
                slug_aliases:
                  - b
              - id: b
                slug: b
                display_name: B
                business_type: t
                status: ACTIVE
                active: true
                migration_status: SHADOW_DEFINED
        """)
        self.assertEqual(reg.validate().decision, "STOP")


class LineChannelTest(unittest.TestCase):
    def setUp(self):
        self.reg = BusinessConfigRegistry().load()

    def test_09_owner_canonical(self):
        self.assertEqual(self.reg.get_owner_channel_env("tachinomiya"), "LINE_OWNER_TOKEN")

    def test_10_staff_canonical(self):
        self.assertEqual(self.reg.get_staff_channel_env("tachinomiya"),
                         "LINE_TACHINOMIYA_STAFF_TOKEN")

    def test_11_staff_legacy_fallback(self):
        # canonical absent, legacy alias present → fallback to legacy NAME
        got = self.reg.resolve_staff_env("tachinomiya", {"LINE_TACHINOMIYASTAFF_TOKEN"})
        self.assertEqual(got, "LINE_TACHINOMIYASTAFF_TOKEN")

    def test_12_canonical_preferred(self):
        got = self.reg.resolve_staff_env(
            "tachinomiya", {"LINE_TACHINOMIYA_STAFF_TOKEN", "LINE_TACHINOMIYASTAFF_TOKEN"})
        self.assertEqual(got, "LINE_TACHINOMIYA_STAFF_TOKEN")

    def test_neither_present_safe_stop(self):
        self.assertIsNone(self.reg.resolve_staff_env("tachinomiya", set()))

    def test_13_no_token_values_only_names(self):
        # returned staff/owner refs are ENV NAMES, never values
        for bid in ("tachinomiya", "catering", "ryukyu_hinabe"):
            for name in (self.reg.get_owner_channel_env(bid),
                         self.reg.get_staff_channel_env(bid)):
                self.assertRegex(name, r"^[A-Z][A-Za-z0-9_]*$")

    def test_14_staff_send_requires_owner_approval(self):
        self.assertTrue(self.reg.staff_send_requires_owner_approval("tachinomiya"))


class ComparatorResolvedTest(unittest.TestCase):
    def test_hinabe_alias_not_flagged(self):
        reg = build(ALIASED)
        ce = {"hinabe": {"slug": "hinabe", "line_token_env": "LINE_hinabeSTAFF_TOKEN"},
              "ryukyu_hinabe": {"slug": "ryukyu_hinabe", "line_token_env": "LINE_hinabeSTAFF_TOKEN"}}

        class FakeAdapter:
            def business_registry(self):
                from core.business_config.models import LegacySource
                return LegacySource("business_registry", {})
            def content_engine(self):
                from core.business_config.models import LegacySource
                return LegacySource("content_engine", ce)
            def executive_targets(self):
                from core.business_config.models import LegacySource
                return LegacySource("executive_team", {})

        r = compare(reg, FakeAdapter())
        self.assertNotEqual(r.decision, "STOP")
        self.assertFalse(any(d.kind == "legacy_only" for d in r.differences),
                         [d.line() for d in r.differences])


class CliGoTest(unittest.TestCase):
    def test_15_16_17_real_repo_cli_go(self):
        import importlib.util
        p = os.path.join(_REPO_ROOT, "scripts", "business_config",
                         "validate_business_configs.py")
        spec = importlib.util.spec_from_file_location("vbc", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.run(), 0)   # GO / exit 0 / mismatch 0 / STOP 0


class RealComparatorTest(unittest.TestCase):
    def test_real_repo_compare_go(self):
        reg = BusinessConfigRegistry().load()
        r = compare(reg, LegacyAdapter())
        self.assertEqual(r.decision, "GO", [d.line() for d in r.differences])


if __name__ == "__main__":
    unittest.main()
