"""Tests for the per-business growth-plan engine. Pure; proposals only."""

import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.team import growth_plan as gp
from scripts.team.assemble_team import load_roles


class TypeTest(unittest.TestCase):
    def setUp(self):
        self.data, _ = load_roles()

    def test_detect_types(self):
        self.assertEqual(gp.detect_type("TACHINOMIYA", self.data)[0], "izakaya")
        self.assertEqual(gp.detect_type("Tree Beauty", self.data)[0], "salon")
        self.assertEqual(gp.detect_type("琉球火鍋", self.data)[0], "hotpot")
        self.assertEqual(gp.detect_type("ツリーズケータリング catering", self.data)[0], "catering")

    def test_unknown_type(self):
        self.assertEqual(gp.detect_type("謎の事業", self.data)[0], "unknown")


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.data, _ = load_roles()

    def test_plan_has_all_sections(self):
        p = gp.build_growth_plan("TACHINOMIYA", self.data)
        for key in ("menu_ideas", "research_points", "kpis", "marketing",
                    "pricing", "retention", "team", "levers"):
            self.assertTrue(p[key], key)

    def test_menu_ideas_match_business_type(self):
        p = gp.build_growth_plan("Tree Beauty", self.data)
        self.assertTrue(any("回数券" in m or "継続" in m for m in p["menu_ideas"]))

    def test_empty_business_stops(self):
        with self.assertRaises(SystemExit):
            gp.build_growth_plan("   ", self.data)

    def test_markdown_is_draft_with_yesno(self):
        md = gp.to_markdown(gp.build_growth_plan("琉球火鍋", self.data))
        self.assertIn("利益成長プラン（案）", md)
        self.assertIn("status: draft", md)
        self.assertIn("新メニュー", md)
        self.assertIn("見るべきKPI", md)
        self.assertIn("- [ ] Yes / No", md)
        self.assertIn("実行=価格変更/投稿/送信/仕入は承認後", md)

    def test_unknown_business_still_produces_plan(self):
        p = gp.build_growth_plan("新規事業X", self.data)
        self.assertEqual(p["type"], "unknown")
        self.assertTrue(p["kpis"])   # 共通KPIは出る（捏造メニューは出さない）
        self.assertEqual(p["menu_ideas"], [])

    def test_no_exec_code(self):
        src = open(os.path.join(_REPO_ROOT, "scripts", "team", "growth_plan.py"),
                   encoding="utf-8").read()
        for bad in ("requests.post", "gcloud", "run deploy", "api.line.me", "broadcast"):
            self.assertNotIn(bad, src, bad)


if __name__ == "__main__":
    unittest.main()
