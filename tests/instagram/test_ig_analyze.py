"""Instagram 分析・監査レポートのテスト。純粋関数／送信・投稿コードなしを検証。"""

import json
import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.instagram import ig_analyze as ig

_FIX = os.path.join(_REPO_ROOT, "tests", "instagram", "fixtures", "sample.json")


def _data():
    with open(_FIX, encoding="utf-8") as fh:
        return json.load(fh)


class AnalyzeTest(unittest.TestCase):
    def setUp(self):
        self.data = _data()

    def test_engagement_rate_uses_reach(self):
        post = {"likes": 100, "comments": 0, "saves": 0, "shares": 0, "reach": 1000}
        self.assertEqual(ig.post_engagement_rate(post, followers=500), 10.0)

    def test_engagement_rate_falls_back_to_followers(self):
        post = {"likes": 50, "comments": 0, "saves": 0, "shares": 0}
        self.assertEqual(ig.post_engagement_rate(post, followers=500), 10.0)

    def test_analyze_posts_shapes(self):
        a = ig.analyze_posts(self.data)
        self.assertEqual(a["n_posts"], 6)
        self.assertTrue(a["avg_engagement_rate"] > 0)
        self.assertTrue(a["top_posts"])
        # 最上位はエンゲージメント率降順
        rates = [e["engagement_rate"] for e in a["top_posts"]]
        self.assertEqual(rates, sorted(rates, reverse=True))
        # REEL が上位に来る（サンプル設計）
        self.assertEqual(a["top_posts"][0]["media_type"], "REEL")

    def test_hashtag_extraction(self):
        tags = ig.extract_hashtags("楽しい #立ち飲み #泡盛　#那覇")
        self.assertIn("#立ち飲み", tags)
        self.assertIn("#那覇", tags)

    def test_by_media_present(self):
        a = ig.analyze_posts(self.data)
        media = {r["key"] for r in a["by_media"]}
        self.assertTrue({"REEL", "IMAGE", "CAROUSEL"} <= media)


class AuditTest(unittest.TestCase):
    def setUp(self):
        self.data = _data()

    def test_audit_score_and_checks(self):
        au = ig.audit_profile(self.data)
        self.assertEqual(au["max"], 5)
        self.assertTrue(0 <= au["score"] <= au["max"])
        keys = {c["key"] for c in au["checks"]}
        self.assertTrue({"bio_present", "bio_cta", "link_present",
                         "name_searchable", "posting_frequency"} <= keys)

    def test_weak_profile_flags_issues(self):
        weak = {"profile": {"username": "x", "name": "x", "bio": "", "followers": 100},
                "posts": []}
        au = ig.audit_profile(weak)
        by = {c["key"]: c["ok"] for c in au["checks"]}
        self.assertFalse(by["bio_present"])
        self.assertFalse(by["link_present"])


class CompareTest(unittest.TestCase):
    def test_compare_with_competitors(self):
        cm = ig.compare_competitors(_data())
        self.assertTrue(cm["has_competitors"])
        self.assertEqual(cm["rows"][0]["username"], "tachinomiya_higashimachi")
        self.assertTrue(len(cm["rows"]) == 3)

    def test_compare_without_competitors(self):
        d = _data()
        d.pop("competitors")
        cm = ig.compare_competitors(d)
        self.assertFalse(cm["has_competitors"])


class ActionAndReportTest(unittest.TestCase):
    def test_action_plan_is_draft(self):
        pl = ig.action_plan(_data())
        self.assertTrue(pl["actions"])
        self.assertTrue(pl["themes_30d"])
        self.assertIn("週", pl["target_frequency"])

    def test_report_markdown_all_sections(self):
        md = ig.build_report(_data(), "all")
        self.assertIn("status: draft", md)
        self.assertIn("## 1. 投稿分析", md)
        self.assertIn("## 2. プロフィール監査", md)
        self.assertIn("## 3. 競合比較", md)
        self.assertIn("## 4. 改善アクション案", md)
        self.assertIn("- [ ] Yes / No", md)
        self.assertIn("投稿・送信・公開は行いません", md)

    def test_report_single_section(self):
        md = ig.build_report(_data(), "audit")
        self.assertIn("## 2. プロフィール監査", md)
        self.assertNotIn("## 1. 投稿分析", md)


class SafetyTest(unittest.TestCase):
    def test_no_send_or_post_code(self):
        src = open(os.path.join(_REPO_ROOT, "scripts", "instagram", "ig_analyze.py"),
                   encoding="utf-8").read()
        for bad in ("requests.post", "urlopen", "api.line.me", "gcloud",
                    "broadcast", "openai"):
            self.assertNotIn(bad, src, bad)


if __name__ == "__main__":
    unittest.main()
