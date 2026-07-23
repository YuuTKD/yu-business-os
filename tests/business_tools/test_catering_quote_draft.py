"""Tests for the Trees Catering quote-draft tool. Pure/local; no sending."""

import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.business_tools import catering_quote_draft as cq


class PricingTest(unittest.TestCase):
    def test_basic_total_with_tax(self):
        q = cq.build_quote(20, event="パーティー")
        self.assertEqual(q["unit"], 1500)
        self.assertEqual(q["subtotal"], 30000)
        self.assertEqual(q["tax"], 3000)
        self.assertEqual(q["total"], 33000)

    def test_volume_tiers(self):
        self.assertEqual(cq.per_person_price(20), 1500)
        self.assertEqual(cq.per_person_price(30), 1400)
        self.assertEqual(cq.per_person_price(50), 1300)

    def test_options_added(self):
        q = cq.build_quote(20, options=["装飾", "運営スタッフ"])
        self.assertEqual(q["option_total"], 8000 + 15000)
        self.assertEqual(q["net"], 30000 + 23000)

    def test_budget_judgement(self):
        self.assertTrue(cq.build_quote(20, budget=40000)["within_budget"])
        self.assertFalse(cq.build_quote(20, budget=10000)["within_budget"])

    def test_per_person_override(self):
        self.assertEqual(cq.build_quote(20, per_person=2000)["unit"], 2000)

    def test_min_guests_stops(self):
        with self.assertRaises(SystemExit):
            cq.build_quote(5)

    def test_unknown_option_stops(self):
        with self.assertRaises(SystemExit):
            cq.build_quote(20, options=["未知"])


class MarkdownTest(unittest.TestCase):
    def test_markdown_is_draft_with_checklist(self):
        md = cq.to_markdown(cq.build_quote(20, event="懇親会", date="2026-08-10",
                                           budget=40000, options=["装飾"]))
        self.assertIn("見積ドラフト", md)
        self.assertIn("status: draft", md)
        self.assertIn("合計（税込）", md)
        self.assertIn("送信前チェック", md)   # human confirms before sending
        self.assertIn("献立案", md)
        self.assertIn("オードブル", md)        # 懇親会 menu

    def test_menu_by_event(self):
        md = cq.to_markdown(cq.build_quote(20, event="結婚式二次会"))
        self.assertIn("デザートビュッフェ", md)

    def test_no_send_or_external(self):
        # tool must not contain any send/post/mail action
        src = open(os.path.join(_REPO_ROOT, "scripts", "business_tools",
                                "catering_quote_draft.py"), encoding="utf-8").read()
        for bad in ("requests.post", "smtplib", "line.me", "send_message",
                    "gspread", "gcloud"):
            self.assertNotIn(bad, src, bad)


if __name__ == "__main__":
    unittest.main()
