"""Phase B2-4 Batch 2 tests — SSOT config supply for Ryukyu Hinabe only."""

import copy
import os
import re
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from configs.business_registry import get as get_config
from core.business_config.loader import BusinessConfigRegistry
from core.business_config.config_builder import (
    build_ryukyu_hinabe_config, build_legacy_compatible_config, validate_legacy_shape,
)
from core.business_config.config_supply import supply, supply_batch

HINABE = "ryukyu_hinabe"


def _no_secret(obj):
    blob = repr(obj)
    return not any(re.search(p, blob) for p in
                   (r"sk-[A-Za-z0-9]{20,}", r"ghp_[A-Za-z0-9]{20,}", r"-----BEGIN",
                    r"AIza[0-9A-Za-z_\-]{20,}"))


class IdentityTest(unittest.TestCase):
    def setUp(self):
        self.reg = BusinessConfigRegistry().load()

    def test_01_canonical_id(self):
        s = self.reg.get_business(HINABE)
        self.assertEqual(s.id, HINABE)
        self.assertEqual(s.slug, HINABE)

    def test_02_hinabe_alias_resolves(self):
        self.assertEqual(self.reg.resolve_slug("hinabe"), HINABE)

    def test_03_alias_gives_same_config(self):
        canonical = supply(HINABE, "OWNER_APPROVED", True)
        alias = supply("hinabe", "OWNER_APPROVED", True)
        self.assertEqual(alias["business_id"], HINABE)
        self.assertEqual(alias["runtime_source"], "SSOT")
        self.assertEqual(alias["config"], canonical["config"])


class ConfigPreservationTest(unittest.TestCase):
    def test_04_gbp_not_activated(self):
        # builder never adds/enables GBP automation; non-overlaid keys pass through
        legacy = get_config(HINABE)
        b = build_ryukyu_hinabe_config()
        self.assertNotIn("gbp_enabled", b.config)
        self.assertEqual(b.config.get("platforms"), legacy.get("platforms"))

    def test_05_pos_settings_preserved(self):
        legacy = get_config(HINABE)
        b = build_ryukyu_hinabe_config()
        self.assertEqual(b.config.get("csv_sources"), legacy.get("csv_sources"))
        self.assertEqual(b.config.get("pos_type"), legacy.get("pos_type"))

    def test_06_owner_and_approval_preserved(self):
        legacy = get_config(HINABE)
        b = build_ryukyu_hinabe_config()
        # different-owner email passes through unchanged (not overlaid)
        self.assertEqual(b.config.get("email"), legacy.get("email"))
        # approval policy: staff notifications still require owner approval
        self.assertTrue(BusinessConfigRegistry().load()
                        .staff_send_requires_owner_approval(HINABE))

    def test_07_legacy_shape_compatible(self):
        b = build_ryukyu_hinabe_config()
        ok, missing, tm = validate_legacy_shape(b.config, get_config(HINABE))
        self.assertTrue(ok, (missing, tm))

    def test_no_activation_side_effects(self):
        legacy = get_config(HINABE)
        b = build_ryukyu_hinabe_config()
        # cloud_run_service name unchanged; no scheduler/posting flags introduced
        self.assertEqual(b.config["cloud_run_service"], legacy["cloud_run_service"])
        self.assertEqual(set(b.config.keys()), set(legacy.keys()))

    def test_no_secret_values(self):
        self.assertTrue(_no_secret(build_ryukyu_hinabe_config().config))

    def test_input_not_mutated(self):
        legacy = get_config(HINABE)
        snap = copy.deepcopy(legacy)
        build_ryukyu_hinabe_config()
        self.assertEqual(get_config(HINABE), snap)


class SupplyModeTest(unittest.TestCase):
    def test_08_unapproved_legacy(self):
        self.assertEqual(supply(HINABE, "AUTO", False)["runtime_source"], "LEGACY")

    def test_09_approved_ssot(self):
        r = supply(HINABE, "OWNER_APPROVED", True)
        self.assertEqual(r["runtime_source"], "SSOT")
        self.assertEqual(r["decision"], "GO")

    def test_10_failure_falls_back(self):
        tmp = tempfile.mkdtemp()  # legacy present in real repo, SSOT absent here
        os.makedirs(os.path.join(tmp, "configs"))
        import shutil
        shutil.copy(os.path.join(_REPO_ROOT, "configs", "business_registry.py"),
                    os.path.join(tmp, "configs", "business_registry.py"))
        r = supply(HINABE, "OWNER_APPROVED", True, repo_root=tmp)
        self.assertEqual(r["runtime_source"], "FALLBACK_LEGACY")

    def test_11_fallback_reason_present(self):
        r = supply(HINABE, "SSOT_ONLY", True)
        self.assertEqual(r["decision"], "STOP")
        self.assertIsNotNone(r["fallback_reason"])

    def test_12_rollback_legacy_only(self):
        self.assertEqual(supply(HINABE, "OWNER_APPROVED", True)["runtime_source"], "SSOT")
        self.assertEqual(supply(HINABE, "LEGACY_ONLY")["runtime_source"], "LEGACY")


class OutOfScopeUnchangedTest(unittest.TestCase):
    def test_13_pasta_pasta_unchanged(self):
        self.assertEqual(supply("pasta_pasta", "OWNER_APPROVED", True)["runtime_source"], "LEGACY")

    def test_14_z1_unchanged(self):
        self.assertEqual(supply("z1", "OWNER_APPROVED", True)["runtime_source"], "LEGACY")

    def test_15_batch1_three_unchanged(self):
        for b in ("tachinomiya", "catering", "beauty"):
            self.assertEqual(supply(b, "OWNER_APPROVED", True)["runtime_source"], "SSOT", b)

    def test_pasta_z1_builder_stop(self):
        # they are not suppliable; builder refuses
        for b in ("pasta_pasta", "z1"):
            res = build_legacy_compatible_config(b, None, get_config(b))
            self.assertIn(res.decision, ("STOP", "FIX"))


class BatchTest(unittest.TestCase):
    def test_batch_now_includes_hinabe(self):
        bt = supply_batch(["tachinomiya", "catering", "beauty", HINABE],
                          mode="OWNER_APPROVED", owner_approved=True)
        self.assertEqual(bt["batch_decision"], "GO")
        self.assertEqual(bt["results"][HINABE]["runtime_source"], "SSOT")


if __name__ == "__main__":
    unittest.main()
