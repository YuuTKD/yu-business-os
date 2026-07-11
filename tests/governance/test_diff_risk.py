"""Unit tests for core.governance.diff_risk (Phase D-Lite)."""

import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.governance import diff_risk


class ClassifyPathsTest(unittest.TestCase):
    def test_empty_is_low(self):
        self.assertEqual(diff_risk.classify_paths([]), "LOW")

    def test_docs_medium(self):
        self.assertEqual(diff_risk.classify_paths(["docs/x.md"]), "MEDIUM")

    def test_core_high(self):
        self.assertEqual(diff_risk.classify_paths(["core/x.py"]), "HIGH")

    def test_env_critical(self):
        self.assertEqual(diff_risk.classify_paths([".env"]), "CRITICAL")

    def test_credentials_critical(self):
        self.assertEqual(diff_risk.classify_paths(["configs/credentials.json"]), "CRITICAL")

    def test_highest_wins(self):
        self.assertEqual(diff_risk.classify_paths(["docs/x.md", "core/y.py"]), "HIGH")
        self.assertEqual(diff_risk.classify_paths(["core/y.py", ".env"]), "CRITICAL")


class BlockedAndSignalsTest(unittest.TestCase):
    def test_find_blocked_acquisition(self):
        self.assertEqual(diff_risk.find_blocked(["scripts/acquisition/run.js", "docs/x.md"]),
                         ["scripts/acquisition/run.js"])

    # Dangerous literals are assembled at runtime (see note in the gate tests).
    def test_scan_secret_true(self):
        val = "ghp_" + ("A" * 30)
        self.assertTrue(diff_risk.scan_secret_lines("k=" + val))

    def test_scan_secret_false(self):
        self.assertFalse(diff_risk.scan_secret_lines("just a normal line of code"))

    def test_scan_runaway_daily_limit(self):
        line = "daily_post_limit" + " = 9"
        self.assertIn("daily_post_limit_change", diff_risk.scan_runaway(line))

    def test_scan_runaway_tree_beauty(self):
        target = "tree beauty acquisition"
        self.assertIn("tree_beauty_activate", diff_risk.scan_runaway("enable " + target))

    def test_scan_runaway_none(self):
        self.assertEqual(diff_risk.scan_runaway("x = 1"), [])


if __name__ == "__main__":
    unittest.main()
