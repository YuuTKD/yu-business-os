"""
Tree Beauty 日次LINEコンテンツ配信システム

毎日9:00 JST に Beauty Master OS から今日のコンテンツを取得し、
画像を生成してLINEスタッフへ送信する。

配信内容（1日4メッセージ）:
  ① Google投稿（テキスト + 画像）
  ② Instagram投稿（テキスト + ハッシュタグ + 画像）
  ③ Threads投稿（テキスト + 画像）
  ④ HPBブログ（タイトル + 本文冒頭 + 画像）

画像: DALL-E 3 で1枚生成（HPBブログ内容基準）→ Drive保存 → LINE送信
"""

import os
import io
import datetime
import requests

import gspread
from google.oauth2.service_account import Credentials
from google.cloud import storage as gcs

BEAUTY_SPREADSHEET_ID = os.getenv(
    "BEAUTY_SPREADSHEET_ID", "1I6wRRDa-b440DBxZ3TbFbfMxEXZecowzOsxTAYSxyBE"
)
GCS_BUCKET = os.getenv("GCS_IMAGE_BUCKET", "tree-beauty-blog-images")


def _get_sheets(creds_path: str):
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds)


def _get_gcs_client(creds_path: str):
    return gcs.Client.from_service_account_json(creds_path)


def _find_today_row(records: list, date_str: str) -> dict | None:
    """日付列（YYYY/MM/DD）で今日の行を検索"""
    for r in records:
        cell = str(r.get("日付", "")).strip().replace("-", "/")
        if cell == date_str:
            return r
    return None


def _fetch_today_content(creds_path: str, target_date: str) -> dict:
    """今日の4媒体コンテンツをスプレッドシートから取得"""
    gc = _get_sheets(creds_path)
    ss = gc.open_by_key(BEAUTY_SPREADSHEET_ID)

    result = {}
    sheet_map = {
        "google":    "08Google投稿",
        "instagram": "09Instagram投稿",
        "threads":   "10Threads投稿",
        "hpb":       "HPBブログ",
    }

    for key, sheet_name in sheet_map.items():
        try:
            sh = ss.worksheet(sheet_name)
            records = sh.get_all_records()
            row = _find_today_row(records, target_date)
            result[key] = row or {}
            if row:
                print(f"  ✅ {sheet_name}: {str(row.get('タイトル', row.get('本文', '')))[:30]}...")
            else:
                print(f"  ⚠ {sheet_name}: {target_date} のデータなし")
        except gspread.WorksheetNotFound:
            print(f"  ❌ シートなし: {sheet_name}")
            result[key] = {}

    return result


def _generate_image_for_line(
    title: str, body: str, service: str, today: str, creds_path: str
) -> tuple[str, str, str]:
    """
    gpt-image-1 で画像生成 → GCS保存 → (filename, original_url, thumbnail_url) を返す。
    失敗時は ("", "", "") を返す。
    thumbnail_url は JPEG 400px幅サムネイルで LINE previewImageUrl (≤1MB) 要件を満たす。
    """
    from core import content_policy
    if not content_policy.image_generation_enabled():
        print("  [image] image_generation=DISABLED (no API call)")
        return "", "", ""
    try:
        from core.blog_image_generator import (
            _generate_prompts,
            _generate_with_quality,
            _upload_to_gcs,
        )
        from openai import OpenAI

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        gcs_client = _get_gcs_client(creds_path)

        prompts, _ = _generate_prompts(title, body, service, client)
        if not prompts:
            return "", "", ""

        best = _generate_with_quality(prompts[0], service, client)
        if not best["bytes"]:
            return "", "", ""

        title_safe = title[:15].replace("/", "_").replace(" ", "_")
        filename = f"{today}_LINE_{title_safe}.png"
        _, original_url, thumbnail_url = _upload_to_gcs(best["bytes"], filename, gcs_client)
        return filename, original_url, thumbnail_url

    except Exception as e:
        print(f"  ❌ 画像生成エラー: {e}")
        import traceback; traceback.print_exc()
        return "", "", ""


def _send_line_text(token: str, text: str):
    """LINE Messaging API broadcast（テキスト）"""
    if len(token) < 100:
        return
    requests.post(
        "https://api.line.me/v2/bot/message/broadcast",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"messages": [{"type": "text", "text": text}]},
        timeout=10,
    )


def _send_line_image(token: str, image_url: str, preview_url: str = ""):
    """LINE Messaging API broadcast（画像）"""
    from core import content_policy
    if not content_policy.line_image_delivery_enabled():
        print("  [image] delivery_mode=TEXT_ONLY (LINE image not attached)")
        return
    if len(token) < 100 or not image_url:
        print(f"  [LINE画像] スキップ: token={len(token)}文字, url={bool(image_url)}")
        return
    # LINE仕様: originalContentUrl ≤10MB, previewImageUrl ≤1MB(HTTPS必須)
    # preview_url にはJPEGサムネイルURLを渡すこと
    effective_preview = preview_url or image_url
    resp = requests.post(
        "https://api.line.me/v2/bot/message/broadcast",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"messages": [{
            "type": "image",
            "originalContentUrl": image_url,
            "previewImageUrl": effective_preview,
        }]},
        timeout=15,
    )
    if resp.status_code == 200:
        print(f"  ✅ [LINE画像] 送信完了 ({len(image_url)}文字URL)")
    else:
        print(f"  ❌ [LINE画像] 失敗 HTTP {resp.status_code}: {resp.text[:200]}")


def run(creds_path: str = None, line_token: str = None) -> dict:
    """
    今日のTree Beautyコンテンツ4媒体を画像付きでLINEスタッフへ送信する。
    Cloud Runエンドポイント /daily-line-content から呼ばれる。
    """
    if creds_path is None:
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "/app/credentials.json")
    if line_token is None:
        line_token = os.getenv("LINE_STAFF_TOKEN", "")

    today = datetime.date.today().strftime("%Y/%m/%d")
    today_dash = today.replace("/", "-")

    print(f"\n{'='*50}")
    print(f"[DailyLine] Tree Beauty 日次配信 {today}")
    print(f"{'='*50}")

    # Step1: 今日のコンテンツ取得
    print("\n[Step1] コンテンツ取得中...")
    content = _fetch_today_content(creds_path, today)

    # Step2: 画像生成（HPBブログ or Google投稿を基準に1枚）
    print("\n[Step2] 画像生成中（LINE用）...")
    base = content.get("hpb") or content.get("google") or {}
    title = str(base.get("タイトル", "") or base.get("hpb_title", "Tree Beauty 本日のコンテンツ"))
    body = str(base.get("本文", "") or base.get("hpb_body", ""))
    service = str(base.get("カテゴリ", "脱毛"))

    file_id, image_url, thumb_url = "", "", ""
    if title and body:
        file_id, image_url, thumb_url = _generate_image_for_line(title, body, service, today_dash, creds_path)
        if image_url:
            print(f"  画像: {image_url}")
            print(f"  サムネイル: {thumb_url}")

    # Step3: LINE送信
    print("\n[Step3] LINE送信中...")
    sent_count = 0

    # ── ① Google投稿 ──────────────────────
    g = content.get("google", {})
    if g:
        msg = (
            f"【Google投稿 {today}】\n\n"
            f"📝 {g.get('タイトル', '')}\n\n"
            f"{g.get('本文', '')}\n\n"
            f"▶ {g.get('CTA', '')}\n"
            f"{g.get('予約URL', '')}"
        )
        _send_line_text(line_token, msg)
        if image_url:
            _send_line_image(line_token, image_url, thumb_url)
        sent_count += 1
        print("  ✅ Google投稿 送信")

    # ── ② Instagram投稿 ──────────────────
    ig = content.get("instagram", {})
    if ig:
        hashtags = ig.get("ハッシュタグ", "")
        msg = (
            f"【Instagram {today}】\n\n"
            f"{ig.get('タイトル', '')}\n\n"
            f"{ig.get('本文', '')}\n\n"
            f"{hashtags}"
        )
        _send_line_text(line_token, msg)
        if image_url:
            _send_line_image(line_token, image_url, thumb_url)
        sent_count += 1
        print("  ✅ Instagram投稿 送信")

    # ── ③ Threads投稿 ──────────────────
    th = content.get("threads", {})
    if th:
        msg = (
            f"【Threads {today}】\n\n"
            f"{th.get('本文', '')}\n\n"
            f"{th.get('予約URL', '')}"
        )
        _send_line_text(line_token, msg)
        if image_url:
            _send_line_image(line_token, image_url, thumb_url)
        sent_count += 1
        print("  ✅ Threads投稿 送信")

    # ── ④ HPBブログ ──────────────────────
    hpb = content.get("hpb", {})
    if hpb:
        body_hpb = str(hpb.get("本文", "") or hpb.get("hpb_body", ""))
        msg = (
            f"【HPBブログ {today}】\n\n"
            f"📖 {hpb.get('タイトル', '') or hpb.get('hpb_title', '')}\n\n"
            f"{body_hpb[:300]}{'...' if len(body_hpb) > 300 else ''}\n\n"
            f"{hpb.get('CTA', '') or hpb.get('hpb_cta', '')}\n"
            f"{hpb.get('予約URL', '')}"
        )
        _send_line_text(line_token, msg)
        if image_url:
            _send_line_image(line_token, image_url, thumb_url)
        sent_count += 1
        print("  ✅ HPBブログ 送信")

    # 何もデータがなかった場合の通知
    if sent_count == 0:
        _send_line_text(
            line_token,
            f"【Tree Beauty】{today} のコンテンツが見つかりませんでした。"
            f"\nスプレッドシートに {today} のデータを確認してください。",
        )

    folder_url = f"https://storage.googleapis.com/{GCS_BUCKET}/"
    print(f"\n{'='*50}")
    print(f"✅ 完了: {sent_count}媒体送信 / 画像: {'あり' if image_url else 'なし'}")
    print(f"{'='*50}")

    return {
        "ok": True,
        "date": today,
        "sent_count": sent_count,
        "image_generated": bool(image_url),
        "image_file_id": file_id,
        "folder_url": folder_url,
    }
