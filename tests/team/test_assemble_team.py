"""Tests for the growth-ops team orchestrator. Pure; no execution/publish."""

import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.team import assemble_team as at


class RolesTest(unittest.TestCase):
    def test_roles_loaded_and_lead_is_ops(self):
        _data, roles = at.load_roles()
        self.assertIn("ops", roles)
        self.assertEqual(at.lead_id(roles), "ops")
        # numbers are contiguous from 1
        nums = sorted(r["num"] for r in roles.values())
        self.assertEqual(nums[0], 1)

    def test_revenue_roles_present(self):
        _data, roles = at.load_roles()
        for rid in ("product", "research", "analytics", "marketing", "pricing",
                    "crm", "sales", "meo", "sns", "review_referral", "winback"):
            self.assertIn(rid, roles, rid)

    def test_all_non_lead_roles_in_phase_order(self):
        data, roles = at.load_roles()
        po = set(data["phase_order"])
        missing = [r for r in roles if r not in po and r != "ops"]
        self.assertEqual(missing, [])


class SelectTest(unittest.TestCase):
    def setUp(self):
        self.data, self.roles = at.load_roles()

    def test_lead_always_included(self):
        eng, _ = at.select_roles("なんでも", self.roles)
        self.assertIn("ops", eng)

    def test_menu_keyword_selects_product(self):
        eng, _ = at.select_roles("新メニューを考えたい", self.roles)
        self.assertIn("product", eng)

    def test_meo_selects_marketing_parent(self):
        eng, _ = at.select_roles("MEOを強化", self.roles)
        self.assertIn("meo", eng)
        self.assertIn("marketing", eng)

    def test_profit_selects_analytics(self):
        eng, _ = at.select_roles("粗利と原価を分析", self.roles)
        self.assertIn("analytics", eng)

    def test_vague_falls_back_to_research_analytics(self):
        eng, needs = at.select_roles("なんとかして", self.roles)  # キーワード無し
        self.assertTrue(needs)
        self.assertIn("research", eng)
        self.assertIn("analytics", eng)


class SafetyTest(unittest.TestCase):
    def test_guardrails_mention_approval(self):
        a = at.assemble("新メニュー")
        self.assertTrue(any("承認" in g for g in a["guardrails"]))

    def test_no_send_or_deploy_code(self):
        src = open(os.path.join(_REPO_ROOT, "scripts", "team", "assemble_team.py"),
                   encoding="utf-8").read()
        for bad in ("requests.post", "gcloud", "run deploy", "api.line.me"):
            self.assertNotIn(bad, src, bad)


if __name__ == "__main__":
    unittest.main()
