#!/usr/bin/env python3
"""Windsor AI コネクタ → Instagram 正規化データ変換（DRY_RUN 既定・鍵は環境変数のみ）。

Windsor AI (windsor.ai) の API が返す行データを、ig_analyze が使う正規化 dict
（profile / posts / competitors）へ変換する。

安全設計:
  - API キーはコードに書かない。環境変数 WINDSOR_API_KEY からのみ読む（値は出力しない）。
  - 既定は DRY_RUN（ネットワーク非接続）。ローカル JSON を読んで normalize するだけ。
  - --live 指定かつ鍵があるときだけ GET 取得（読み取り専用）。投稿・送信・書き込みはしない。
  - 取得は urllib（stdlib）。外部ライブラリ不要。

使用例（オフライン）:
  python3 scripts/instagram/windsor_source.py --raw raw.json --out normalized.json
使用例（ライブ取得は owner が鍵を設定して実行）:
  WINDSOR_API_KEY=*** python3 scripts/instagram/windsor_source.py --live --connector instagram_insights --out normalized.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

WINDSOR_BASE = "https://connectors.windsor.ai/all"

# Windsor/各コネクタで表記ゆれのあるフィールド名を吸収するためのエイリアス表
_ALIASES = {
    "id": ("id", "post_id", "media_id"),
    "timestamp": ("timestamp", "date", "created_time", "post_time"),
    "caption": ("caption", "message", "text", "title"),
    "media_type": ("media_type", "media_product_type", "type"),
    "permalink": ("permalink", "permalink_url", "url"),
    "likes": ("likes", "like_count", "likes_count"),
    "comments": ("comments", "comments_count", "comment_count"),
    "saves": ("saves", "saved", "save_count"),
    "shares": ("shares", "share_count"),
    "reach": ("reach",),
    "impressions": ("impressions", "impression_count"),
}
_PROFILE_ALIASES = {
    "username": ("username", "account_name", "page_name"),
    "name": ("name", "account_username", "full_name"),
    "bio": ("bio", "biography", "about"),
    "followers": ("followers", "followers_count", "follower_count"),
    "follows": ("follows", "follows_count", "following_count"),
    "website": ("website", "link", "external_url"),
    "category": ("category", "account_category"),
}


def _first(row, keys):
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return None


def _pick(row, aliases):
    return {field: _first(row, keys) for field, keys in aliases.items()}


def normalize(raw):
    """Windsor 風の生データ（{"data": [...]} か行のリスト）を正規化 dict へ。

    raw が既に {profile, posts} 形なら（オフライン fixture 等）そのまま返す。
    """
    if isinstance(raw, dict) and ("posts" in raw or "profile" in raw):
        return raw
    rows = raw.get("data") if isinstance(raw, dict) else raw
    rows = rows or []

    posts = []
    profile = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        p = _pick(row, _ALIASES)
        if p.get("id") or p.get("timestamp") or p.get("caption"):
            posts.append(p)
        # プロフィール系フィールドは行に混在しうるので上書き集約
        pf = _pick(row, _PROFILE_ALIASES)
        for k, v in pf.items():
            if v not in (None, "") and not profile.get(k):
                profile[k] = v
    return {"profile": profile, "posts": posts}


def fetch_live(connector, fields, date_preset="last_30d", base=WINDSOR_BASE, timeout=30):
    """Windsor AI から GET 取得（読み取り専用）。鍵は環境変数からのみ。"""
    api_key = os.environ.get("WINDSOR_API_KEY")
    if not api_key:
        raise SystemExit("STOP: 環境変数 WINDSOR_API_KEY が未設定です（--live には鍵が必要）。")
    query = urlencode({
        "api_key": api_key,
        "connector": connector,
        "date_preset": date_preset,
        "fields": ",".join(fields),
    })
    url = f"{base}?{query}"
    req = Request(url, method="GET", headers={"Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (GET only, read-only)
        return json.loads(resp.read().decode("utf-8"))


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Windsor AI → Instagram 正規化（既定オフライン）")
    ap.add_argument("--raw", help="オフライン: Windsor 生 JSON を読み込む")
    ap.add_argument("--live", action="store_true", help="ライブ取得（鍵と承認が必要）")
    ap.add_argument("--connector", default="instagram_insights")
    ap.add_argument("--fields", default="date,caption,media_type,permalink,likes,"
                    "comments,saves,shares,reach,impressions,followers,username,bio,website")
    ap.add_argument("--out", help="正規化 JSON の保存先")
    args = ap.parse_args(argv)

    if args.live:
        raw = fetch_live(args.connector, [f.strip() for f in args.fields.split(",")])
    elif args.raw:
        raw = load_json(args.raw)
    else:
        raise SystemExit("STOP: --raw か --live のどちらかを指定してください。")

    normalized = normalize(raw)
    payload = json.dumps(normalized, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(payload)
        print(f"正規化データを保存: {args.out}（posts={len(normalized.get('posts', []))}件）",
              file=sys.stderr)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
