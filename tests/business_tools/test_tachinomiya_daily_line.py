"""Tests for the TACHINOMIYA daily-sales LINE-text tool. Pure; no LINE send."""

import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.business_tools import tachinomiya_daily_line as td


class ReportTest(unittest.TestCase):
    def test_daily_targets_from_monthly(self):
        r = td.build_report(0, 0, operating_days=26)
        self.assertEqual(r["dt_lunch"], round(2_500_000 / 26))
        self.assertEqual(r["dt_dinner"], round(3_000_000 / 26))

    def test_totals_and_pct(self):
        r = td.build_report(96154, 115385, date="2026-07-23")
        self.assertEqual(r["total"], 96154 + 115385)
        self.assertEqual(r["pct_lunch"], 100)
        self.assertEqual(r["pct_dinner"], 100)

    def test_yoy(self):
        r = td.build_report(100000, 100000, last_year=180000)
        self.assertEqual(r["yoy"]["diff"], 200000 - 180000)
        self.assertTrue(r["yoy"]["pct"] > 100)

    def test_negative_or_missing_stops(self):
        with self.assertRaises(SystemExit):
            td.build_report(-1, 100)

    def test_zero_operating_days_stops(self):
        with self.assertRaises(SystemExit):
            td.build_report(100, 100, operating_days=0)


class TextTest(unittest.TestCase):
    def test_line_text_structure(self):
        t = td.to_line_text(td.build_report(98000, 88000, date="2026-07-23",
                                            last_year=177000))
        self.assertIn("【立ち飲み 7/23 売上】", t)
        self.assertIn("昼 ¥98,000", t)
        self.assertIn("夜 ¥88,000", t)
        self.assertIn("合計", t)
        self.assertIn("前年比", t)
        self.assertIn("一言:", t)

    def test_one_liner_from_data_not_fabricated(self):
        # total achieved → positive one-liner
        self.assertIn("達成", td._one_liner(td.build_report(200000, 200000)))
        # lunch on target but dinner short → total below → mentions 夜 (data-derived)
        short = td.build_report(96154, 50000)   # total 146,154 < daily target
        self.assertLess(td.build_report(96154, 50000)["pct_total"], 100)
        self.assertIn("夜", td._one_liner(short))

    def test_no_line_send_code(self):
        src = open(os.path.join(_REPO_ROOT, "scripts", "business_tools",
                                "tachinomiya_daily_line.py"), encoding="utf-8").read()
        for bad in ("requests.post", "api.line.me", "broadcast", "gspread", "gcloud"):
            self.assertNotIn(bad, src, bad)


if __name__ == "__main__":
    unittest.main()
