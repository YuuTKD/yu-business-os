"""Windsor AI コネクタ変換のテスト。オフラインのみ。鍵直書き無し・書き込み無しを検証。"""

import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.instagram import windsor_source as ws


class NormalizeTest(unittest.TestCase):
    def test_passthrough_when_already_normalized(self):
        data = {"profile": {"username": "x"}, "posts": [{"id": "1"}]}
        self.assertIs(ws.normalize(data), data)

    def test_normalizes_windsor_rows(self):
        raw = {"data": [
            {"post_id": "a1", "date": "2026-06-01T18:00:00+0000",
             "message": "hi #x", "media_product_type": "REEL",
             "like_count": 10, "comments_count": 2, "reach": 500,
             "followers_count": 1000, "account_name": "acct", "biography": "bio here"},
        ]}
        n = ws.normalize(raw)
        self.assertEqual(len(n["posts"]), 1)
        p = n["posts"][0]
        self.assertEqual(p["id"], "a1")
        self.assertEqual(p["likes"], 10)
        self.assertEqual(p["media_type"], "REEL")
        self.assertEqual(n["profile"]["followers"], 1000)
        self.assertEqual(n["profile"]["username"], "acct")

    def test_list_input(self):
        raw = [{"id": "1", "timestamp": "2026-06-01", "caption": "c"}]
        n = ws.normalize(raw)
        self.assertEqual(len(n["posts"]), 1)

    def test_live_requires_key(self):
        old = os.environ.pop("WINDSOR_API_KEY", None)
        try:
            with self.assertRaises(SystemExit):
                ws.fetch_live("instagram_insights", ["date"])
        finally:
            if old is not None:
                os.environ["WINDSOR_API_KEY"] = old


class SafetyTest(unittest.TestCase):
    def test_no_hardcoded_key_or_write_calls(self):
        src = open(os.path.join(_REPO_ROOT, "scripts", "instagram", "windsor_source.py"),
                   encoding="utf-8").read()
        # 鍵は環境変数からのみ
        self.assertIn("os.environ.get(\"WINDSOR_API_KEY\")", src)
        # 送信・投稿・OpenAI は使わない
        for bad in ("requests.post", "api.line.me", "gcloud", "broadcast", "openai",
                    "method=\"POST\"", "method='POST'"):
            self.assertNotIn(bad, src, bad)


if __name__ == "__main__":
    unittest.main()
