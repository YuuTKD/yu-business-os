"""Tests for the production-team PM orchestrator. Pure; no execution/publish."""

import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.team import assemble_team as at


class RolesTest(unittest.TestCase):
    def test_20_roles_loaded(self):
        _data, roles = at.load_roles()
        self.assertEqual(len(roles), 20)
        self.assertIn("pm", roles)
        # numbers 1..20 all present
        nums = sorted(r["num"] for r in roles.values())
        self.assertEqual(nums, list(range(1, 21)))

    def test_children_have_parent(self):
        _data, roles = at.load_roles()
        self.assertEqual(roles["quote"]["parent"], "sales")
        self.assertEqual(roles["copy"]["parent"], "ux")
        self.assertEqual(roles["aftercare"]["parent"], "analytics")


class SelectTest(unittest.TestCase):
    def setUp(self):
        self.data, self.roles = at.load_roles()

    def test_pm_always_lead(self):
        eng, _ = at.select_roles("なんでもいい", self.roles)
        self.assertIn("pm", eng)

    def test_keyword_selects_role_and_parent(self):
        eng, _ = at.select_roles("見積を出して", self.roles)
        self.assertIn("quote", eng)
        self.assertIn("sales", eng)   # 統括も編成

    def test_seo_selects_research(self):
        eng, _ = at.select_roles("SEOとMEOを強化したい", self.roles)
        self.assertIn("seo_meo", eng)
        self.assertIn("research", eng)

    def test_lp_dev_selects_fe(self):
        eng, _ = at.select_roles("LPを開発してサイト公開まで", self.roles)
        self.assertIn("fe", eng)
        self.assertIn("publish", eng)

    def test_vague_falls_back_to_hearing(self):
        eng, needs = at.select_roles("いい感じにして", self.roles)
        self.assertTrue(needs)
        self.assertEqual(eng, {"pm", "sales", "requirements"})

    def test_explicit_role(self):
        eng, _ = at.select_roles("", self.roles, explicit=["legal"])
        self.assertIn("legal", eng)
        self.assertIn("publish", eng)  # parent


class PlanTest(unittest.TestCase):
    def test_phases_follow_order(self):
        a = at.assemble("BeautyのLP作って。コピーとSEOと見積も")
        ids = [p["id"] for p in a["phases"]]
        # requirements should come before publish; only engaged roles appear
        self.assertIn("copy", ids)
        self.assertIn("seo_meo", ids)
        self.assertIn("quote", ids)
        self.assertTrue(ids.index("requirements") < ids.index("copy")
                        if "requirements" in ids else True)

    def test_guardrails_present(self):
        a = at.assemble("見積出して")
        self.assertTrue(a["guardrails"])
        self.assertTrue(any("承認" in g for g in a["guardrails"]))

    def test_text_output_has_no_exec(self):
        t = at.to_text(at.assemble("LP開発して公開"))
        self.assertIn("編成", t)
        self.assertIn("進行計画", t)
        self.assertIn("実装・投稿・公開・送信は各承認後", t)


class SafetyTest(unittest.TestCase):
    def test_no_send_or_deploy_code(self):
        src = open(os.path.join(_REPO_ROOT, "scripts", "team", "assemble_team.py"),
                   encoding="utf-8").read()
        for bad in ("requests.post", "gcloud", "run deploy", "api.line.me",
                    "subprocess"):
            self.assertNotIn(bad, src, bad)


if __name__ == "__main__":
    unittest.main()
