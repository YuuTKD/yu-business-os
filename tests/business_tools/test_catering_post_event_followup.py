"""Tests for the Catering post-event follow-up draft tool. Pure; no sending."""

import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.business_tools import catering_post_event_followup as pf


class FollowupTest(unittest.TestCase):
    def test_three_parts_generated(self):
        f = pf.build_followup("会社懇親会", date="2026-08-10", guests=25, contact_name="田中")
        self.assertIn("ありがとう", f["thanks"])
        self.assertIn("田中様", f["thanks"])
        self.assertIn("クチコミ", f["review"])
        self.assertIn("次回", f["proposal"])

    def test_send_on_is_next_day(self):
        self.assertEqual(pf.build_followup("パーティー", date="2026-08-10")["send_on"],
                         "2026-08-11")

    def test_missing_date_defaults(self):
        self.assertEqual(pf.build_followup("パーティー")["send_on"], "実施翌日")

    def test_next_suggestion_by_event(self):
        self.assertIn("定例懇親", pf.build_followup("懇親会")["next_suggestion"])
        self.assertIn("オリジナル", pf.build_followup("不明な種別")["next_suggestion"])

    def test_no_contact_name_uses_generic(self):
        self.assertIn("ご担当者様", pf.build_followup("パーティー")["thanks"])

    def test_pii_not_echoed_in_name(self):
        f = pf.build_followup("パーティー", contact_name="a@b.com")
        self.assertNotIn("a@b.com", f["thanks"])


class OutputTest(unittest.TestCase):
    def test_markdown_draft_and_checklist(self):
        md = pf.to_markdown(pf.build_followup("懇親会", date="2026-08-10", guests=20))
        self.assertIn("イベント後フォロー下書き", md)
        self.assertIn("status: draft", md)
        self.assertIn("お礼メッセージ", md)
        self.assertIn("クチコミ依頼", md)
        self.assertIn("次回提案", md)
        self.assertIn("送信前チェック", md)
        self.assertIn("自動送信・自動投稿はしません", md)

    def test_no_send_or_api_code(self):
        src = open(os.path.join(_REPO_ROOT, "scripts", "business_tools",
                                "catering_post_event_followup.py"), encoding="utf-8").read()
        for bad in ("requests.post", "smtplib", "api.line.me", "gspread",
                    "gcloud", "googleapis"):
            self.assertNotIn(bad, src, bad)


if __name__ == "__main__":
    unittest.main()
