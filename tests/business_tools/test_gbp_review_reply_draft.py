"""Tests for the GBP review-reply draft tool. Pure; no GBP posting."""

import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.business_tools import gbp_review_reply_draft as gr


class ReplyTest(unittest.TestCase):
    def test_high_rating_thanks_and_invites(self):
        r = gr.build_reply("Tree Beauty", 5, "接客が丁寧で最高でした")
        self.assertIn("ありがとう", r["reply"])
        self.assertIn("接客・スタッフ", r["topics"])
        self.assertIn("お待ちしております", r["reply"])

    def test_mid_rating_acknowledges_improvement(self):
        r = gr.build_reply("琉球火鍋", 3, "味は良いが待ち時間が長い")
        self.assertIn("改善", r["reply"])

    def test_low_rating_apologizes_and_offline(self):
        r = gr.build_reply("Catering", 2, "予約時間に案内されなかった")
        self.assertIn("申し訳", r["reply"])
        self.assertIn("ご連絡", r["reply"])   # offline contact invite

    def test_invalid_rating_stops(self):
        for bad in (0, 6, None):
            with self.assertRaises(SystemExit):
                gr.build_reply("X", bad)

    def test_topics_only_when_present(self):
        self.assertEqual(gr.build_reply("X", 5, "普通でした").get("topics"), [])

    def test_no_pii_in_reply(self):
        # even if PII somehow appears, reply must not contain it
        r = gr.build_reply("X", 2, "連絡は a@b.com 090-1234-5678 まで")
        self.assertNotIn("@b.com", r["reply"])
        self.assertNotIn("090-1234-5678", r["reply"])


class OutputSafetyTest(unittest.TestCase):
    def test_output_marks_draft_and_checklist(self):
        out = gr.to_output(gr.build_reply("Tree Beauty", 4, "雰囲気が良い"))
        self.assertIn("GBP返信ドラフト", out)
        self.assertIn("投稿前チェック", out)
        self.assertIn("自動投稿はしません", out)

    def test_no_posting_or_api_code(self):
        src = open(os.path.join(_REPO_ROOT, "scripts", "business_tools",
                                "gbp_review_reply_draft.py"), encoding="utf-8").read()
        for bad in ("requests.post", "gbp_api", "mybusiness", "googleapis",
                    "gcloud", "access_token"):
            self.assertNotIn(bad, src, bad)


if __name__ == "__main__":
    unittest.main()
