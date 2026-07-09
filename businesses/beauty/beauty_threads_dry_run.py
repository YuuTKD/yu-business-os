"""
Tree Beauty Threads自動投稿 — DRY_RUN シミュレーター
作成：2026-07-06

本番APIコールなし・LINE通知なし・実投稿なし
7テーマの投稿候補を検証するシミュレーション。

実行:
  cd /Users/tokudayuya/yu-business-os
  python3 businesses/beauty/beauty_threads_dry_run.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from businesses.beauty.beauty_threads_config import (
    check_ng_expression,
    check_image_theme_match,
    get_stock_alert_level,
    build_stock_report,
    BEAUTY_THEME_KEYWORDS,
    BEAUTY_BLOCK_WORDS,
    STRONG_BEAUTY_THEMES,
)

# ─────────────────────────────────────────────────────
# DRY_RUN候補投稿（Spreadsheetから取得するデータのサンプル）
# 実本番では beauty_content_v2.py で生成したSpreadsheetの内容を読み込む
# ─────────────────────────────────────────────────────

DRY_RUN_POSTS = [
    {
        "slot":        "beauty_morning",
        "post_theme":  "salon_interior",
        "image_theme": "salon_interior",
        "text": (
            "完全セルフって、最初は「え、自分でやるの？」って思いますよね。\n"
            "でも一度体験すると、これが思いのほか自由で良いんです。\n"
            "時間を気にせず、自分のペースで。\n"
            "Tree Beautyは完全個室なので、人目を気にしなくていい。\n"
            "まずは体験から、気になる方へ。"
        ),
        "image_id": "IMG-BEAUTY-001",
        "image_url": "https://storage.googleapis.com/DRY_RUN/salon_interior_001.jpg",
    },
    {
        "slot":        "beauty_morning",
        "post_theme":  "hair_removal",
        "image_theme": "hair_removal",
        "text": (
            "自己処理が面倒だな、と思う日ってありませんか。\n"
            "毎週繰り返して、時間も肌も消耗していく感覚。\n"
            "脱毛を気になる方へ。まずは体験から始められます。\n"
            "個人差がありますが、すっきり感を体感する方も多いです。"
        ),
        "image_id": "IMG-BEAUTY-002",
        "image_url": "https://storage.googleapis.com/DRY_RUN/hair_removal_001.jpg",
    },
    {
        "slot":        "beauty_morning",
        "post_theme":  "whitening",
        "image_theme": "whitening",
        "text": (
            "写真で自然に笑えますか？\n"
            "口元が気になってつい手で隠してしまう方へ。\n"
            "セルフホワイトニングで清潔感のある笑顔を目指したい方に。\n"
            "まずは体験から、ご相談ください。個人差があります。"
        ),
        "image_id": "IMG-BEAUTY-003",
        "image_url": "https://storage.googleapis.com/DRY_RUN/whitening_001.jpg",
    },
    {
        "slot":        "beauty_morning",
        "post_theme":  "yomogi",
        "image_theme": "yomogi",
        "text": (
            "毎日バタバタしていて、自分の時間が後回しになっていませんか。\n"
            "よもぎ蒸しは、30分だけ自分のためにリセットする時間。\n"
            "すっきり感を体感する方も多いです。\n"
            "気になる方へ、まずは体験からどうぞ。"
        ),
        "image_id": "IMG-BEAUTY-004",
        "image_url": "https://storage.googleapis.com/DRY_RUN/yomogi_001.jpg",
    },
    {
        "slot":        "beauty_morning",
        "post_theme":  "cupping",
        "image_theme": "cupping",
        "text": (
            "肩が重くてなんとなく気になる方へ。\n"
            "カッピングケアが気になる方、まずは体験からどうぞ。\n"
            "個人差がありますが、すっきり感を感じる方も。"
        ),
        "image_id": "IMG-BEAUTY-005",
        "image_url": "https://storage.googleapis.com/DRY_RUN/cupping_001.jpg",
    },
    {
        "slot":        "beauty_morning",
        "post_theme":  "campaign",
        "image_theme": "campaign",
        "text": (
            "期間限定で体験メニューをご用意しています。\n"
            "脱毛・ホワイトニング・よもぎ蒸しをまずは試したい方へ。\n"
            "詳しくはプロフィールのリンクからどうぞ。"
        ),
        "image_id": "IMG-BEAUTY-006",
        "image_url": "https://storage.googleapis.com/DRY_RUN/campaign_001.jpg",
    },
    {
        "slot":        "beauty_morning",
        "post_theme":  "general_beauty",
        "image_theme": "salon_interior",
        "text": (
            "自分磨きって、大げさなものじゃなくていい。\n"
            "清潔感のある印象ケアから始めてみる。\n"
            "Tree Beautyで、まずは体験から。"
        ),
        "image_id": "IMG-BEAUTY-007",
        "image_url": "https://storage.googleapis.com/DRY_RUN/salon_interior_002.jpg",
    },
]

# ─────────────────────────────────────────────────────
# DRY_RUN 画像在庫（仮データ / 実際はIMAGE_LIBRARYから取得）
# ─────────────────────────────────────────────────────
# 注意: 以下は現在未確認の推定値。実運用前にIMAGE_LIBRARYで確認必須。
ESTIMATED_STOCK = {
    "salon_interior":  "不明（要確認）",
    "hair_removal":    "不明（要確認）",
    "whitening":       "不明（要確認）",
    "yomogi":          "不明（要確認）",
    "cupping":         "不明（要確認）",
    "menu":            "不明（要確認）",
    "campaign":        "不明（要確認）",
    "general_beauty":  "不明（要確認）",
    "staff":           "不明（要確認）",
}


def run_dry_run():
    print("=" * 62)
    print("  Tree Beauty Threads 自動投稿 DRY_RUN")
    print("  本番APIコールなし / LINE通知なし / 実投稿なし")
    print("=" * 62)
    print()

    results = []

    for i, post in enumerate(DRY_RUN_POSTS, 1):
        slot       = post["slot"]
        post_theme = post["post_theme"]
        img_theme  = post["image_theme"]
        text       = post["text"]
        image_id   = post["image_id"]

        print(f"  [{i}/{len(DRY_RUN_POSTS)}] テーマ: {post_theme}")
        print(f"       スロット: {slot}")
        print(f"       画像テーマ: {img_theme}")
        print(f"       本文: {text[:60]}...")

        # ── STEP A: 美容NG表現チェック ───────────────────
        ng_result = check_ng_expression(text)
        verdict   = ng_result["verdict"]
        print(f"       NG表現チェック: {verdict}", end="")
        if ng_result["found"]:
            print(f" ({', '.join(ng_result['found'])})")
        else:
            print()

        # ── STEP B: 本文×画像一致チェック ───────────────
        match_result = check_image_theme_match(post_theme, img_theme)
        match_ok     = match_result["ok"]
        print(f"       画像一致チェック: {'✅ OK' if match_ok else '❌ NG'} — {match_result['reason']}")

        # ── STEP C: blocked違反チェック ──────────────────
        blocked_ok = True
        if verdict == "BLOCK":
            blocked_ok = False

        # ── STEP D: 総合判定 ─────────────────────────────
        can_post = (verdict != "BLOCK") and match_ok
        status_mark = "✅ PASS" if can_post else ("⚠️ REVISE" if verdict == "REVISE" else "❌ BLOCK")
        print(f"       総合判定: {status_mark}")
        print()

        results.append({
            "theme":     post_theme,
            "verdict":   verdict,
            "match":     match_ok,
            "can_post":  can_post,
            "image_id":  image_id,
        })

    # ── サマリー ─────────────────────────────────────────
    print("─" * 62)
    print("  DRY_RUN サマリー")
    print("─" * 62)
    pass_count   = sum(1 for r in results if r["can_post"])
    revise_count = sum(1 for r in results if r["verdict"] == "REVISE")
    block_count  = sum(1 for r in results if r["verdict"] == "BLOCK")
    mismatch_count = sum(1 for r in results if not r["match"])

    print(f"  PASS    : {pass_count}/{len(results)}")
    print(f"  REVISE  : {revise_count}/{len(results)}")
    print(f"  BLOCK   : {block_count}/{len(results)}")
    print(f"  画像不一致: {mismatch_count}/{len(results)}")
    print()
    print("  ⚠️  注意: IMAGE_LIBRARY在庫は実確認が必要")
    print("       GCS化済み枚数・テーマ別在庫 → IMAGE_LIBRARYシートで確認")
    print("       Spreadsheet ID: 15cfsC2HIzu1FGW602dxqNuv-DJpmLiZhatvB-hDn2XM")
    print()
    print("  DRY_RUNではLINE通知を送信しません。")
    print("=" * 62)

    return results


if __name__ == "__main__":
    run_dry_run()
