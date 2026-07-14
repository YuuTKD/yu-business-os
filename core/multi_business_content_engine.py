"""
Multi Business Content Automation Engine
毎朝9:00 に各事業の今日の未通知コンテンツを取得し
  STEP1: スプレッドシートから未通知行を取得
  STEP2: 1投稿につき1枚画像を生成（gpt-image-1, 1024×1024）
  STEP3: GCS保存（Business_Content_Images/{事業}/）
  STEP4: LINEスタッフへ通知（テキスト + 画像）
  STEP5: 通知済みへステータス更新
  STEP6: エラー処理（最大3回リトライ）
  STEP7: SYSTEM_LOG シートへ記録

対象事業: Tree Beauty / TREE's Catering / TACHINOMIYA / 琉球火鍋
"""

import os
import io
import json
import time
import datetime
import base64
from urllib.parse import quote

import gspread
from google.oauth2.service_account import Credentials
from google.cloud import storage as gcs_lib
from openai import OpenAI
import requests

GCS_BUCKET = os.getenv("GCS_IMAGE_BUCKET", "tree-beauty-blog-images")

# ─────────────────────────────────────────────────────────────
# 事業設定
# ─────────────────────────────────────────────────────────────

_BUSINESS_CONFIGS: dict = {
    "beauty": {
        "name": "Tree Beauty",
        "display": "🌸 Tree Beauty",
        "spreadsheet_id": "1I6wRRDa-b440DBxZ3TbFbfMxEXZecowzOsxTAYSxyBE",
        "line_token_env": "LINE_STAFF_TOKEN",
        "gcs_folder": "content/TreeBeauty",
        "image_style": "beauty",
        "sheets": [
            {"name": "08Google投稿",    "media": "Google投稿",   "date_col": "日付", "title_col": "タイトル", "body_col": "本文", "hashtag_col": None,          "status_col": "投稿状況", "header_row": 1},
            {"name": "09Instagram投稿", "media": "Instagram投稿","date_col": "日付", "title_col": "タイトル", "body_col": "本文", "hashtag_col": "ハッシュタグ", "status_col": "投稿状況", "header_row": 1},
            {"name": "10Threads投稿",   "media": "Threads投稿",  "date_col": "日付", "title_col": "タイトル", "body_col": "本文", "hashtag_col": None,          "status_col": "投稿状況", "header_row": 1},
            {"name": "HPBブログ",       "media": "HPBブログ",    "date_col": "日付", "title_col": "タイトル", "body_col": "本文", "hashtag_col": None,          "status_col": "投稿状況", "header_row": 1},
        ],
    },
    "catering": {
        "name": "TREE's Catering",
        "display": "🍱 TREE's Catering",
        "spreadsheet_id": "1tNE35iQAVk6eTGEu68WDrRpv9FDIeVT_eK66iRi78Zs",
        "line_token_env": "LINE_cateringSTAFF_TOKEN",
        "gcs_folder": "content/Catering",
        "image_style": "catering",
        "sheets": [
            {"name": "08_Google投稿", "media": "Google投稿",   "date_col": "投稿日", "title_col": "タイトル",     "body_col": "本文（500文字以内）", "hashtag_col": "ハッシュタグ", "status_col": "投稿状況", "header_row": 2},
            {"name": "09_Instagram",  "media": "Instagram投稿","date_col": "投稿日", "title_col": "キャプション", "body_col": "キャプション",        "hashtag_col": "ハッシュタグ", "status_col": "投稿状況", "header_row": 2},
            {"name": "10_Threads",    "media": "Threads投稿",  "date_col": "投稿日", "title_col": "本文（500文字以内）","body_col": "本文（500文字以内）","hashtag_col": "ハッシュタグ","status_col": "投稿状況","header_row": 2},
        ],
    },
    "tachinomiya": {
        "name": "TACHINOMIYA",
        "display": "🍶 TACHINOMIYA",
        "spreadsheet_id": "1K4KkAhFwVkQqqvzeqa25-1sR26ltBfP9gY9h-N4gXcc",
        "line_token_env": "LINE_TACHINOMIYASTAFF_TOKEN",
        "gcs_folder": "content/Tachinomiya",
        "image_style": "tachinomiya",
        "sheets": [
            {"name": "08_Google投稿", "media": "Google投稿",   "date_col": "投稿日", "title_col": "タイトル",    "body_col": "本文",       "hashtag_col": "ハッシュタグ", "status_col": "投稿状況", "header_row": 2},
            {"name": "09_Instagram",  "media": "Instagram投稿","date_col": "投稿日", "title_col": "キャプション","body_col": "キャプション","hashtag_col": "ハッシュタグ", "status_col": "投稿状況", "header_row": 2},
            {"name": "10_Threads",    "media": "Threads投稿",  "date_col": "投稿日", "title_col": "本文",        "body_col": "本文",       "hashtag_col": "ハッシュタグ", "status_col": "投稿状況", "header_row": 2},
        ],
    },
    "hinabe": {
        "name": "琉球火鍋",
        "display": "🍲 琉球火鍋",
        "spreadsheet_id": "1jwFmQtrertjIc6yYFJEyDptLdSUgD5xLdHDAxQhIQzw",
        "line_token_env": "LINE_hinabeSTAFF_TOKEN",
        "gcs_folder": "content/Hotpot",
        "image_style": "hinabe",
        "sheets": [
            {"name": "08_Google投稿",  "media": "Google投稿",   "date_col": "投稿日", "title_col": "タイトル",    "body_col": "本文",       "hashtag_col": "ハッシュタグ", "status_col": "投稿状況", "header_row": 2},
            {"name": "09_Instagram投稿","media": "Instagram投稿","date_col": "投稿日", "title_col": "キャプション","body_col": "キャプション","hashtag_col": "ハッシュタグ", "status_col": "投稿状況", "header_row": 2},
            {"name": "10_Threads投稿", "media": "Threads投稿",  "date_col": "投稿日", "title_col": "本文",        "body_col": "本文",       "hashtag_col": "ハッシュタグ", "status_col": "投稿状況", "header_row": 2},
        ],
    },
    # ryukyu_hinabe は hinabe の別名（Cloud Run BUSINESS_NAME=ryukyu_hinabe 対応）
    "ryukyu_hinabe": {
        "name": "琉球火鍋",
        "display": "🍲 琉球火鍋",
        "spreadsheet_id": "1jwFmQtrertjIc6yYFJEyDptLdSUgD5xLdHDAxQhIQzw",
        "line_token_env": "LINE_hinabeSTAFF_TOKEN",
        "gcs_folder": "content/Hotpot",
        "image_style": "hinabe",
        "sheets": [
            {"name": "08_Google投稿",  "media": "Google投稿",   "date_col": "投稿日", "title_col": "タイトル",    "body_col": "本文",       "hashtag_col": "ハッシュタグ", "status_col": "投稿状況", "header_row": 2},
            {"name": "09_Instagram投稿","media": "Instagram投稿","date_col": "投稿日", "title_col": "キャプション","body_col": "キャプション","hashtag_col": "ハッシュタグ", "status_col": "投稿状況", "header_row": 2},
            {"name": "10_Threads投稿", "media": "Threads投稿",  "date_col": "投稿日", "title_col": "本文",        "body_col": "本文",       "hashtag_col": "ハッシュタグ", "status_col": "投稿状況", "header_row": 2},
        ],
    },
}

# 事業別画像生成システムプロンプト
_IMAGE_STYLE_PROMPTS = {
    "beauty": (
        "Luxury Japanese beauty salon editorial photo. Tree Beauty, Okinawa. "
        "Japanese woman aged 20-35, smooth flawless skin, soft natural window light, "
        "cream/blush/white color palette, serene confident expression. "
        "Photorealistic, 1:1 square format, high-end spa aesthetic. "
        "ZERO text, ZERO logos, ZERO watermarks."
    ),
    "catering": (
        "Premium catering photography for TREE's Catering, Okinawa. "
        "Elegantly plated dishes for corporate party or upscale event, "
        "beautifully arranged buffet spread, sophisticated food presentation, "
        "professional studio lighting, clean white or dark background. "
        "1:1 square format. ZERO text, ZERO logos."
    ),
    "tachinomiya": (
        "Vibrant Okinawan izakaya food photography for TACHINOMIYA, Kokusai-dori Okinawa. "
        "Appetizing Okinawan cuisine, awamori cocktails, sata andagi, habu sake, "
        "warm amber izakaya lighting, inviting and lively atmosphere. "
        "1:1 square format. ZERO text, ZERO logos."
    ),
    "hinabe": (
        "Stunning premium hot pot restaurant photo for 琉球火鍋, Okinawa. "
        "Wagyu beef slices, fresh Okinawan seafood, simmering hot pot with steam rising, "
        "medicinal herb broth, dramatic sizzle effect, rich warm tones. "
        "Luxurious and appetizing. 1:1 square format. ZERO text, ZERO logos."
    ),
}

# 画像生成ステータスコードが不要なモデル設定（1024×1024 square）
_IMAGE_MODEL_CONFIGS = [
    {"model": "gpt-image-1", "size": "1024x1024", "quality": "high"},
    {"model": "dall-e-3",    "size": "1024x1024", "quality": "hd"},
]

_BIZ_KEY_MAP = {
    "beauty":        "BEAUTY",
    "catering":      "CATERING",
    "tachinomiya":   "TACHINOMIYA",
    "hinabe":        "HINABE",
    "ryukyu_hinabe": "HINABE",
}


def _fetch_real_image(
    lib_key: str,
    post_content: str,
    gcs_folder: str,
    today_dash: str,
    gcs_client,
    creds_path: str,
) -> tuple[str, str] | None:
    """
    IMAGE_LIBRARY から実写画像を選定 → Drive DL → GCS UP → (original_url, thumb_url)
    実写画像なし → None
    """
    from core import content_policy
    if not content_policy.line_image_delivery_enabled():
        # 画像配信停止: 実写画像の取得・GCS書込も行わない（TEXT_ONLY）
        return None
    from core.image_manager import select_real_image, fetch_drive_image_bytes, track_usage

    selected = select_real_image(post_content, lib_key, platform="line", creds_path=creds_path)
    if not selected:
        return None

    image_bytes = fetch_drive_image_bytes(selected["drive_file_id"], creds_path)
    if not image_bytes:
        return None

    # JPEG変換（LINE互換）
    try:
        from PIL import Image as PILImage, ImageOps
        buf_in = io.BytesIO(image_bytes)
        img = ImageOps.exif_transpose(PILImage.open(buf_in)).convert("RGB")
        buf_out = io.BytesIO()
        img.save(buf_out, format="JPEG", quality=90)
        image_bytes = buf_out.getvalue()
    except Exception:
        pass

    import re as _re
    title_safe = _re.sub(r"[^\w\-.]", "_", selected["filename"][:20])
    gcs_path = f"{gcs_folder}/{today_dash}_real_{title_safe}.jpg"
    original_url, thumbnail_url = _upload_image(image_bytes, gcs_path, gcs_client)

    track_usage(selected["image_id"], "LINE", post_content[:100], selected.get("score", 0), creds_path)
    print(f"    ✅ 実写: {selected['filename']} ({selected['category']})")
    return original_url, thumbnail_url


# ─────────────────────────────────────────────────────────────
# Google API クライアント
# ─────────────────────────────────────────────────────────────

def _gc(creds_path: str) -> gspread.Client:
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds)


def _gcs(creds_path: str):
    return gcs_lib.Client.from_service_account_json(creds_path)


# ─────────────────────────────────────────────────────────────
# STEP1: スプレッドシートから未通知行を取得
# ─────────────────────────────────────────────────────────────

def _find_today_rows(sh: gspread.Worksheet, sc: dict, today_str: str) -> list[dict]:
    """
    今日の未通知行をすべて取得する。
    戻り値: [{row_num, title, body, hashtags, header_row_idx, status_col_idx, headers}]
    """
    header_row = sc["header_row"]
    all_values = sh.get_all_values()

    if len(all_values) < header_row:
        return []

    headers = all_values[header_row - 1]

    def idx(col_name: str | None) -> int | None:
        if col_name is None:
            return None
        return headers.index(col_name) if col_name in headers else None

    date_idx    = idx(sc["date_col"])
    title_idx   = idx(sc["title_col"])
    body_idx    = idx(sc["body_col"])
    hashtag_idx = idx(sc.get("hashtag_col"))
    status_idx  = idx(sc["status_col"])

    if date_idx is None:
        return []

    results = []
    for row_offset, row in enumerate(all_values[header_row:]):
        row_num = header_row + row_offset + 1  # 1-indexed spreadsheet row

        def cell(i):
            return row[i].strip() if i is not None and i < len(row) else ""

        if cell(date_idx) != today_str:
            continue

        # 重複通知防止: 通知済みはスキップ
        if status_idx is not None and cell(status_idx) == "通知済み":
            continue

        title    = cell(title_idx) if title_idx is not None else ""
        body     = cell(body_idx)  if body_idx  is not None else ""
        hashtags = cell(hashtag_idx)

        if not (title or body):
            continue

        results.append({
            "row_num":      row_num,
            "title":        title,
            "body":         body,
            "hashtags":     hashtags,
            "status_idx":   status_idx,
            "headers":      headers,
            "header_row":   header_row,
        })

    return results


def _ensure_status_column(sh: gspread.Worksheet, sc: dict) -> int | None:
    """
    status_col が存在しないシートに列を追加する（Tree Beauty 系）。
    既存なら idx を返すだけ。なければグリッド拡張後に追加して idx を返す。
    """
    header_row = sc["header_row"]
    headers = sh.row_values(header_row)
    status_col = sc["status_col"]

    if status_col in headers:
        return headers.index(status_col)

    # グリッドを拡張してから追加（col_count を超えると APIError になるため）
    new_col_num = len(headers) + 1
    if new_col_num > sh.col_count:
        sh.resize(rows=sh.row_count, cols=new_col_num + 5)
        time.sleep(0.5)

    sh.update_cell(header_row, new_col_num, status_col)
    return len(headers)  # 0-indexed


# ─────────────────────────────────────────────────────────────
# STEP2+3: 画像生成 → GCS保存
# ─────────────────────────────────────────────────────────────

def _build_image_prompt(title: str, body: str, image_style: str) -> str:
    style_base = _IMAGE_STYLE_PROMPTS.get(image_style, _IMAGE_STYLE_PROMPTS["beauty"])
    return (
        f"{style_base} "
        f"Theme: {title}. "
        f"Context: {body[:150]}. "
        "Photorealistic, square 1:1 format, professional photography. "
        "Absolutely ZERO text, letters, numbers, watermarks, or logos anywhere in the image."
    )


def _generate_image_bytes(prompt: str, client: OpenAI) -> bytes | None:
    """gpt-image-1 → dall-e-3 の順で試みる。最大3回リトライ。"""
    from core import content_policy
    if not content_policy.image_generation_enabled():
        print("    [image] image_generation=DISABLED (no API call, no retry)")
        return None
    for attempt in range(3):
        for cfg in _IMAGE_MODEL_CONFIGS:
            try:
                kwargs = {
                    "model":  cfg["model"],
                    "prompt": prompt,
                    "size":   cfg["size"],
                    "n":      1,
                }
                if cfg.get("quality"):
                    kwargs["quality"] = cfg["quality"]
                resp = client.images.generate(**kwargs)
                item = resp.data[0]
                if getattr(item, "b64_json", None):
                    import base64 as _b64
                    return _b64.b64decode(item.b64_json)
                url = item.url or ""
                if url:
                    r = requests.get(url, timeout=30)
                    if r.status_code == 200:
                        return r.content
            except Exception as e:
                print(f"    ⚠ {cfg['model']} attempt {attempt+1}: {e}")
                if attempt < 2:
                    time.sleep(2)
    return None


def _upload_image(image_bytes: bytes, gcs_path: str, gcs_client) -> tuple[str, str]:
    """
    GCS へフル画像 + JPEGサムネイルをアップロードし
    (original_url, thumbnail_url) を返す。
    URLは LINE API 用にパーセントエンコード済み。
    """
    from urllib.parse import quote as _q

    def make_url(path: str) -> str:
        return f"https://storage.googleapis.com/{GCS_BUCKET}/{_q(path, safe='/')}"

    bucket = gcs_client.bucket(GCS_BUCKET)

    # フル画像（PNG）
    blob = bucket.blob(gcs_path)
    blob.upload_from_string(image_bytes, content_type="image/png")
    original_url = make_url(gcs_path)
    print(f"    GCS: {len(image_bytes)//1024}KB → {gcs_path}")

    # サムネイル（JPEG, ≤1MB for LINE previewImageUrl）
    thumb_path = gcs_path.replace(".png", "_thumb.jpg")
    thumbnail_url = original_url
    try:
        from PIL import Image as PILImage
        img = PILImage.open(io.BytesIO(image_bytes)).convert("RGB")
        resample = getattr(PILImage, "Resampling", PILImage).LANCZOS
        img.thumbnail((512, 512), resample)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82, optimize=True)
        thumb_bytes = buf.getvalue()
        bucket.blob(thumb_path).upload_from_string(thumb_bytes, content_type="image/jpeg")
        thumbnail_url = make_url(thumb_path)
        print(f"    Thumb: {len(thumb_bytes)//1024}KB")
    except Exception as e:
        print(f"    ⚠ サムネイル生成スキップ: {e}")

    return original_url, thumbnail_url


# ─────────────────────────────────────────────────────────────
# STEP4: LINE通知
# ─────────────────────────────────────────────────────────────

_LINE_API = "https://api.line.me/v2/bot/message/broadcast"


def _line_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _send_line_text(token: str, text: str) -> bool:
    if len(token) < 100:
        return False
    try:
        resp = requests.post(
            _LINE_API,
            headers=_line_headers(token),
            json={"messages": [{"type": "text", "text": text}]},
            timeout=15,
        )
        ok = resp.status_code == 200
        if not ok:
            print(f"    ❌ LINE text HTTP {resp.status_code}: {resp.text[:100]}")
        return ok
    except Exception as e:
        print(f"    ❌ LINE text error: {e}")
        return False


def _send_line_image(token: str, original_url: str, preview_url: str) -> bool:
    from core import content_policy
    if not content_policy.line_image_delivery_enabled():
        print("    [image] delivery_mode=TEXT_ONLY (LINE image not attached)")
        return False
    if len(token) < 100 or not original_url:
        return False
    try:
        resp = requests.post(
            _LINE_API,
            headers=_line_headers(token),
            json={"messages": [{
                "type": "image",
                "originalContentUrl": original_url,
                "previewImageUrl": preview_url or original_url,
            }]},
            timeout=15,
        )
        ok = resp.status_code == 200
        if ok:
            print(f"    ✅ LINE画像 送信完了")
        else:
            print(f"    ❌ LINE画像 HTTP {resp.status_code}: {resp.text[:150]}")
        return ok
    except Exception as e:
        print(f"    ❌ LINE画像 error: {e}")
        return False


def _build_line_message(biz_display: str, media: str, title: str, body: str, hashtags: str,
                         image_url: str, notify_dt: str) -> str:
    lines = [
        f"{'='*30}",
        f"{biz_display}",
        f"【媒体】{media}",
        f"{'='*30}",
        f"【タイトル】\n{title}",
        "",
        f"【投稿本文】\n{body[:500]}{'...' if len(body) > 500 else ''}",
    ]
    if hashtags:
        lines += ["", f"【ハッシュタグ】\n{hashtags}"]
    if image_url:
        lines += ["", f"【画像URL】\n{image_url}"]
    lines += ["", f"【生成日時】{notify_dt}"]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# STEP5: 通知済みステータス更新
# ─────────────────────────────────────────────────────────────

def _update_row_status(sh: gspread.Worksheet, row_num: int, post: dict,
                        status: str, notify_dt: str, image_url: str):
    """行の投稿状況・通知日時・画像URLを更新する"""
    headers = list(post.get("headers", []))
    status_idx = post.get("status_idx")

    if status_idx is None:
        # 列が存在しない（Tree Beauty系） → _ensure_status_column で追加済みのはず
        # フォールバック: 末尾列インデックスを使う
        status_idx = len(headers)

    def _safe_update(r, c, v):
        """グリッドを必要なら拡張してからセル更新"""
        if c > sh.col_count:
            sh.resize(rows=sh.row_count, cols=c + 5)
            time.sleep(0.3)
        try:
            sh.update_cell(r, c, v)
        except Exception as e:
            print(f"    ⚠ セル更新失敗 ({r},{c}): {e}")
        time.sleep(0.15)

    # 投稿状況
    _safe_update(row_num, status_idx + 1, status)

    # 通知日時
    notify_dt_col = "通知日時"
    if notify_dt_col in headers:
        _safe_update(row_num, headers.index(notify_dt_col) + 1, notify_dt)
    else:
        _safe_update(row_num, status_idx + 2, notify_dt)

    # 画像URL
    img_col = "画像URL"
    if img_col in headers:
        _safe_update(row_num, headers.index(img_col) + 1, image_url)
    else:
        _safe_update(row_num, status_idx + 3, image_url)


# ─────────────────────────────────────────────────────────────
# STEP7: SYSTEM_LOG シートへ記録
# ─────────────────────────────────────────────────────────────

_LOG_HEADERS = ["実行日時", "事業名", "媒体", "投稿タイトル",
                "画像生成", "LINE送信", "ステータス更新", "エラー内容"]


def _write_log(gc_client: gspread.Client, spreadsheet_id: str, entry: dict):
    """SYSTEM_LOG シートへ1行追記する"""
    try:
        ss = gc_client.open_by_key(spreadsheet_id)
        try:
            sh = ss.worksheet("SYSTEM_LOG")
        except gspread.WorksheetNotFound:
            sh = ss.add_worksheet("SYSTEM_LOG", rows=2000, cols=len(_LOG_HEADERS))
            sh.update(range_name="A1", values=[_LOG_HEADERS])
            sh.format("A1:H1", {
                "backgroundColor": {"red": 0.1, "green": 0.1, "blue": 0.2},
                "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
            })

        row = [
            entry.get("dt", ""),
            entry.get("biz", ""),
            entry.get("media", ""),
            entry.get("title", "")[:50],
            "✅" if entry.get("image_ok") else "❌",
            "✅" if entry.get("line_ok")  else "❌",
            "✅" if entry.get("status_ok") else "❌",
            entry.get("error", ""),
        ]
        sh.append_row(row, value_input_option="RAW")
    except Exception as e:
        print(f"  ⚠ SYSTEM_LOG 書き込み失敗: {e}")


# ─────────────────────────────────────────────────────────────
# メインエントリポイント
# ─────────────────────────────────────────────────────────────

def run(business_key: str = None, creds_path: str = None, line_token: str = None) -> dict:
    """
    指定事業の今日の未通知投稿を画像生成 → LINE通知 → 通知済み更新する。

    Args:
        business_key: "beauty" / "catering" / "tachinomiya" / "hinabe"
                      省略時は BUSINESS_NAME 環境変数を使用
        creds_path:   SA credentials.json パス
        line_token:   LINE channel access token（省略時は env var から取得）
    """
    if creds_path is None:
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "/app/credentials.json")
    if business_key is None:
        business_key = os.getenv("BUSINESS_NAME", "beauty")

    cfg = _BUSINESS_CONFIGS.get(business_key)
    if not cfg:
        return {"ok": False, "error": f"未対応の事業キー: {business_key}"}

    biz_name    = cfg["name"]
    biz_display = cfg["display"]
    ss_id       = cfg["spreadsheet_id"]
    gcs_folder  = cfg["gcs_folder"]
    image_style = cfg["image_style"]

    if line_token is None:
        line_token = os.getenv(cfg["line_token_env"], "")

    today = datetime.date.today()
    today_str = today.strftime("%Y/%m/%d")
    today_dash = today.strftime("%Y-%m-%d")
    now_str   = datetime.datetime.now().strftime("%Y/%m/%d %H:%M")

    print(f"\n{'='*55}")
    print(f"[ContentEngine] {biz_display} — {today_str}")
    print(f"{'='*55}")

    gc_client = _gc(creds_path)
    gcs_client = _gcs(creds_path)
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    ss = gc_client.open_by_key(ss_id)

    total_sent = 0
    total_posts = 0
    results = []

    # ── STEP1: 各シートから今日の未通知行を収集 ──────────────────
    print(f"\n[STEP1] 未通知コンテンツ取得中...")
    posts_by_sheet = []

    for sc in cfg["sheets"]:
        try:
            sh = ss.worksheet(sc["name"])
            rows = _find_today_rows(sh, sc, today_str)
            if rows:
                print(f"  ✅ {sc['name']}: {len(rows)}件 未通知")
                posts_by_sheet.append({"sc": sc, "sh": sh, "rows": rows})
            else:
                print(f"  ─ {sc['name']}: 未通知なし（通知済みor未設定）")
        except gspread.WorksheetNotFound:
            print(f"  ⚠ シート未存在: {sc['name']}")
        except Exception as e:
            print(f"  ❌ {sc['name']} 取得エラー: {e}")

    if not posts_by_sheet:
        msg = f"【{biz_name}】本日 {today_str} の未通知コンテンツはありません"
        _send_line_text(line_token, msg)
        return {"ok": True, "business": biz_name, "sent": 0, "total": 0, "note": "no_posts"}

    # ── STEP2+3: 1投稿につき1枚画像生成 → GCS保存 ───────────────
    print(f"\n[STEP2+3] 画像生成・GCS保存...")

    for sheet_info in posts_by_sheet:
        sc   = sheet_info["sc"]
        sh   = sheet_info["sh"]
        media = sc["media"]

        # status 列がない場合（Tree Beauty）は動的に追加
        actual_status_idx = _ensure_status_column(sh, sc)
        # _find_today_rows で status_idx=None だったポストに実際のidxを反映
        for post in sheet_info["rows"]:
            if post["status_idx"] is None and actual_status_idx is not None:
                post["status_idx"] = actual_status_idx
                # headers にも追加
                post["headers"] = list(post["headers"]) + [sc["status_col"]]

        for post in sheet_info["rows"]:
            total_posts += 1
            title    = post["title"]
            body     = post["body"]
            hashtags = post["hashtags"]
            row_num  = post["row_num"]

            print(f"\n  [{media}] {title[:35]}...")

            image_ok = False
            original_url = ""
            thumbnail_url = ""
            error_msg = ""
            image_source = "ai"

            # ── 実写画像を優先選定（IMAGE_LIBRARY）──────────────
            print(f"    [STEP2a] 実写画像検索...")
            lib_key = _BIZ_KEY_MAP.get(business_key)
            if lib_key:
                try:
                    real_result = _fetch_real_image(
                        lib_key, f"{title}\n{body}", gcs_folder, today_dash,
                        gcs_client, creds_path,
                    )
                    if real_result:
                        original_url, thumbnail_url = real_result
                        image_ok = True
                        image_source = "real"
                        print(f"    ✅ 実写画像使用")
                except Exception as e:
                    print(f"    ⚠ 実写画像取得失敗（AI生成へ）: {e}")

            # ── 実写なし → AI画像生成 ──────────────────────────
            if not image_ok:
                print(f"    [STEP2b] AI画像生成中...")
                prompt = _build_image_prompt(title, body, image_style)
                image_bytes = None
                for attempt in range(3):
                    image_bytes = _generate_image_bytes(prompt, openai_client)
                    if image_bytes:
                        break
                    print(f"    ⚠ 画像生成失敗 attempt {attempt+1}/3")
                    time.sleep(3)

                if image_bytes:
                    try:
                        import re as _re
                        sheet_safe = _re.sub(r"[^\w\-]", "_", sc["name"])[:20]
                        title_safe = _re.sub(r"[^\w\-]", "_", title[:20])
                        gcs_path = f"{gcs_folder}/{today_dash}_{sheet_safe}_{title_safe}.png"
                        original_url, thumbnail_url = _upload_image(image_bytes, gcs_path, gcs_client)
                        image_ok = True
                    except Exception as e:
                        error_msg = f"GCS保存失敗: {e}"
                        print(f"    ❌ {error_msg}")
                else:
                    error_msg = "画像生成3回全て失敗"
                    print(f"    ❌ {error_msg}")

            # ── STEP4: LINE通知（テキスト + 画像）────────────────
            print(f"    [STEP4] LINE送信...")
            if len(line_token) < 100:
                print(f"    ⚠ LINE token未設定 ({cfg['line_token_env']})")
                line_ok = False
                image_sent = False
            else:
                text_msg = _build_line_message(
                    biz_display, media, title, body, hashtags,
                    original_url, now_str
                )
                text_ok  = _send_line_text(line_token, text_msg)
                image_sent = False
                if image_ok:
                    image_sent = _send_line_image(line_token, original_url, thumbnail_url)
                line_ok = text_ok

            # ── STEP5: ステータス更新（画像付き通知成功のみ「通知済み」）────
            # 要件: 画像+テキスト両方成功→通知済み / 画像失敗→画像エラー・再送待ち
            status_ok = False
            if line_ok:
                if image_ok and image_sent:
                    final_status = "通知済み"
                elif not image_ok:
                    final_status = "画像エラー・再送待ち"
                    error_msg = (error_msg + " | 画像なし").lstrip(" | ")
                else:
                    # image_ok=True だが image_sent=False（LINE画像送信失敗）
                    final_status = "画像エラー・再送待ち"
                    error_msg = (error_msg + " | 画像LINE送信失敗").lstrip(" | ")
                try:
                    _update_row_status(sh, row_num, post,
                                       status=final_status,
                                       notify_dt=now_str,
                                       image_url=original_url)
                    status_ok = True
                    if final_status == "通知済み":
                        total_sent += 1
                        print(f"    ✅ 通知済み更新完了")
                    else:
                        print(f"    ⚠ ステータス → {final_status}")
                except Exception as e:
                    error_msg += f" | ステータス更新失敗: {e}"
                    print(f"    ❌ ステータス更新失敗: {e}")
            else:
                print(f"    ⚠ LINE送信失敗のためステータスを未通知のまま保持")

            # ── STEP7: SYSTEM_LOG ───────────────────────────────
            _write_log(gc_client, ss_id, {
                "dt": now_str, "biz": biz_name, "media": media,
                "title": title, "image_ok": image_ok,
                "line_ok": line_ok, "status_ok": status_ok,
                "error": error_msg,
            })

            results.append({
                "media": media, "title": title[:40],
                "image_ok": image_ok, "line_ok": line_ok, "status_ok": status_ok,
            })

            time.sleep(1)  # API負荷軽減

    print(f"\n{'='*55}")
    print(f"✅ {biz_name} 完了: {total_sent}/{total_posts}件 通知成功")
    print(f"{'='*55}")

    return {
        "ok": True,
        "business": biz_name,
        "date": today_str,
        "sent": total_sent,
        "total": total_posts,
        "results": results,
    }
