"""
Tree Beauty ブログ画像自動生成システム

Phase1: ブログ解析 → 画像プロンプト3案（GPT-4o）
Phase2: 画像生成（DALL-E 3, 1024×1792縦長）
Phase3: Google Drive保存（Tree Beauty/Blog_Images/）
Phase4: スプレッドシート記録（Blog_Images シート）
Phase5: LINE通知（スタッフ）
Phase6: 品質チェック（70点未満再生成、最大2回）
"""

import os
import io
import json
import base64
import datetime
import requests

import gspread
from google.oauth2.service_account import Credentials
from google.cloud import storage as gcs
from openai import OpenAI

BLOG_IMAGES_FOLDER_ID = os.getenv("BLOG_IMAGES_FOLDER_ID", "1TR_haIfnpi7CU__xpkF3S8rwY8K7KI5o")
GCS_BUCKET = os.getenv("GCS_IMAGE_BUCKET", "tree-beauty-blog-images")
BEAUTY_SPREADSHEET_ID = os.getenv("BEAUTY_SPREADSHEET_ID", "1I6wRRDa-b440DBxZ3TbFbfMxEXZecowzOsxTAYSxyBE")
BLOG_IMAGES_SHEET = "Blog_Images"

_SERVICE_KEYWORDS = {
    "脱毛": (
        "smooth hairless flawless skin on legs or arms, Japanese woman in white linen sitting relaxed, "
        "gentle skin touch, radiant bare skin, soft glow, serene confidence"
    ),
    "セルフホワイトニング": (
        "radiant bright smile, Japanese woman with perfect white teeth, glowing confident expression, "
        "soft warm light on face, clean fresh aesthetic, feminine joy"
    ),
    "よもぎ蒸し": (
        "traditional Korean herbal steam bath, soft rising steam, warm golden light, "
        "Japanese woman in white robe relaxing, wellness sanctuary, calm and serene"
    ),
    "カッピング": (
        "cupping therapy on smooth back, soft amber spa lighting, Japanese woman lying peacefully, "
        "luxury wellness treatment, clean white towels, serene atmosphere"
    ),
}

_BRAND_SYSTEM = """You are a top-tier beauty editorial photographer and art director for a luxury Japanese beauty salon.

Brand: Tree Beauty, Okinawa, Japan.
Target customer: Japanese women aged 20-40 living in Okinawa who want smooth beautiful skin and feminine confidence.
Brand personality: HIGH-END luxury spa + modern clean aesthetic + warm Okinawan brightness.

VISUAL QUALITY STANDARD (match or exceed this):
- Photography style: Japanese beauty magazine editorial quality (Vogue Japan, Voce, Maquia level)
- Lighting: Soft, natural side lighting from large window. Warm cream-toned light. No harsh shadows.
- Color palette: Cream white, soft blush pink, warm beige, sage green accents. Pastel, airy, clean.
- Subject: Beautiful Japanese woman, 20s-30s. Serene expression. Confident but gentle. Natural makeup.
- Clothing: White or cream camisole, slip dress, or robe. Simple, elegant, minimal.
- Skin: Visibly smooth, luminous, flawless skin. This is the hero of the image.
- Composition: Portrait/vertical (9:16). Clean negative space. Feels spacious and premium.
- Background: White or cream interior. Soft bokeh. Hints of greenery (plants). Neutral luxury.
- Mood: "I feel beautiful and confident." Aspirational. Makes women want to book immediately.

ABSOLUTE RULES (never break):
- ZERO text, letters, numbers, watermarks, logos, QR codes, symbols, or written characters of any kind.
- NO "完全セルフ" or self-service impression. Always feels staff-supported and premium.
- NO cheap, discount, flyer, catalog, or cluttered aesthetic.
- NO distorted hands, unnatural body proportions, or AI-artifact faces.
- NO inappropriate, revealing, or uncomfortable imagery.
- Hands must be natural — avoid close-up detail shots of hands.
- Portrait orientation only (taller than wide).
"""


# ──────────────────────────────────────────────
# Google API ヘルパー
# ──────────────────────────────────────────────

def _get_sheets_client(creds_path: str):
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds)


def _get_gcs_client(creds_path: str):
    return gcs.Client.from_service_account_json(creds_path)


def _get_or_create_sheet(ss) -> gspread.Worksheet:
    headers = [
        "生成日時", "ブログ日付", "ブログタイトル", "使用メニュー",
        "画像1 URL", "画像2 URL", "画像3 URL",
        "推奨画像番号",
        "生成プロンプト1", "生成プロンプト2", "生成プロンプト3",
        "品質スコア1", "品質スコア2", "品質スコア3",
        "Drive フォルダURL",
    ]
    try:
        return ss.worksheet(BLOG_IMAGES_SHEET)
    except gspread.WorksheetNotFound:
        sh = ss.add_worksheet(title=BLOG_IMAGES_SHEET, rows=500, cols=len(headers))
        sh.update(range_name=f"A1:{chr(64+len(headers))}1", values=[headers])
        sh.format(f"A1:{chr(64+len(headers))}1", {
            "backgroundColor": {"red": 0.059, "green": 0.09, "blue": 0.165},
            "textFormat": {
                "bold": True, "fontSize": 10,
                "foregroundColor": {"red": 1, "green": 1, "blue": 1},
            },
            "horizontalAlignment": "CENTER",
        })
        return sh


# ──────────────────────────────────────────────
# Phase 1: プロンプト生成
# ──────────────────────────────────────────────

def _generate_prompts(title: str, body: str, service: str, client: OpenAI) -> tuple[list, list]:
    service_kw = _SERVICE_KEYWORDS.get(service, "beauty salon, Japanese woman, wellness, smooth skin")
    prompt = f"""You are writing image generation prompts for gpt-image-1 (OpenAI's top image model).
These prompts will generate hero images for Tree Beauty, a luxury Japanese beauty salon in Okinawa.

Blog title: {title}
Blog excerpt: {body[:300]}
Service menu: {service}
Visual keywords for this service: {service_kw}

BRAND STANDARD:
{_BRAND_SYSTEM}

Generate 3 DISTINCT, HIGH-QUALITY prompts (150-200 words each, in English):

Prompt 1 — EMOTIONAL TRANSFORMATION PORTRAIT:
A Japanese woman in her late 20s experiencing the joy and confidence from {service} treatment.
She should look serene, happy, and naturally beautiful. Show her skin visibly smooth and glowing.
Seated or reclining pose — relaxed and elegant. White or cream linen setting with soft natural window light.
Editorial beauty photography. Pastel cream and blush color palette.

Prompt 2 — SKIN DETAIL / ASPIRATION:
Close-to-medium shot emphasizing smooth, luminous, flawless skin on legs, arms, or décolletage.
Japanese woman in white minimalist room. Soft side lighting creating gentle skin glow.
The mood: "this is what {service} gives you." Premium, clean, aspirational.
No faces prominently — focus on the skin quality and feminine silhouette.

Prompt 3 — LIFESTYLE / OKINAWA ASPIRATION:
Japanese woman in her 20s-30s in an airy, bright Okinawa-inspired setting.
Relaxed, confident feminine energy. Subtle tropical light and warmth. Soft whites and sage greens.
She looks like she just finished a treatment and feels amazing about herself.
The image should make a woman think "I want her life / her confidence / her skin."

RULES for all prompts:
- Every prompt must end with: "Photorealistic, 9:16 portrait format, editorial beauty photography, luxury Japanese spa aesthetic, absolutely no text or watermarks"
- Do NOT include any text, logos, QR codes, or written characters
- Keep hands natural or out of frame

Return ONLY this JSON (no extra text):
{{
  "prompts": ["prompt1 in English", "prompt2 in English", "prompt3 in English"],
  "jp_descriptions": ["案1説明（15文字以内）", "案2説明（15文字以内）", "案3説明（15文字以内）"]
}}"""

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.85,
            )
            data = json.loads(resp.choices[0].message.content)
            return data.get("prompts", []), data.get("jp_descriptions", [])
        except Exception as e:
            print(f"  ⚠ プロンプト生成 attempt {attempt+1}: {e}")
    return [], []


# ──────────────────────────────────────────────
# Phase 2 + 6: 画像生成 + 品質チェック
# ──────────────────────────────────────────────

_IMAGE_SUFFIX = (
    " Photorealistic, editorial beauty photography quality. "
    "Soft natural window light, cream and blush color palette, luxury Japanese spa aesthetic. "
    "Portrait vertical orientation (9:16). "
    "CRITICAL: absolutely zero text, letters, numbers, watermarks, logos, QR codes, "
    "or any written characters anywhere in the image."
)

# gpt-image-1 → dall-e-3 の順で試す
_IMAGE_MODELS = [
    {"model": "gpt-image-1", "size": "1024x1536", "quality": "high"},
    {"model": "dall-e-3",    "size": "1024x1792", "quality": "hd"},
]


def _generate_one_image(prompt: str, client: OpenAI) -> tuple[bytes | None, str]:
    """画像を生成し (bytes, url) を返す。gpt-image-1 → dall-e-3 の順で試みる"""
    from core import content_policy
    if not content_policy.image_generation_enabled():
        print("    [image] image_generation=DISABLED (no API call)")
        return None, "IMAGE_GEN_DISABLED"
    full_prompt = prompt + _IMAGE_SUFFIX
    last_err = None
    for cfg in _IMAGE_MODELS:
        try:
            kwargs = {
                "model":  cfg["model"],
                "prompt": full_prompt,
                "size":   cfg["size"],
                "n":      1,
            }
            if cfg.get("quality"):
                kwargs["quality"] = cfg["quality"]
            resp = client.images.generate(**kwargs)
            item = resp.data[0]
            # gpt-image-1 は b64_json を返す場合がある
            if getattr(item, "b64_json", None):
                import base64 as _b64
                return _b64.b64decode(item.b64_json), ""
            url = item.url or ""
            if url:
                r = requests.get(url, timeout=30)
                return (r.content if r.status_code == 200 else None), url
        except Exception as e:
            last_err = e
            print(f"    ⚠ {cfg['model']} エラー: {e}")
    print(f"    ❌ 全モデル失敗: {last_err}")
    return None, ""


def _check_quality(image_bytes: bytes, service: str, client: OpenAI) -> tuple[int, str]:
    """GPT-4o visionで品質スコア（0-100）と理由を返す"""
    try:
        b64 = base64.b64encode(image_bytes).decode()
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"""You are a beauty brand creative director evaluating an AI-generated image for Tree Beauty ({service}), a luxury Japanese beauty salon in Okinawa.

Rate this image strictly (0-100) against these criteria:

QUALITY STANDARD: The image must match Japanese beauty magazine editorial quality (Vogue Japan / Maquia level).

Scoring breakdown:
- [25pts] Luxury & premium feel: Does it look high-end, clean, and editorial? (NOT cheap/clipart/stock)
- [25pts] Smooth beautiful skin is visible and aspirational: Does the skin look glowing and flawless?
- [20pts] Japanese woman aged 20-40 would want to book {service} after seeing this image
- [15pts] ZERO text/letters/numbers/QR codes anywhere (score 0 for this section if any text exists)
- [10pts] Natural body proportions: No distorted hands, unnatural face, or AI artifacts
- [5pts] Soft natural lighting, cream/blush/white color palette, vertical portrait format

STRICT DISQUALIFIERS (force score to 0-30 max):
- Any text, letters, numbers, or symbols visible → max 30pts total
- Distorted/unnatural body parts → max 40pts total
- Cheap, stock-photo, or clinical feel → max 50pts total

Return JSON only: {{"score": 0-100, "reason": "評価理由（日本語30文字以内）", "has_text": true/false, "is_premium": true/false}}""",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{b64}",
                            "detail": "low",
                        },
                    },
                ],
            }],
            response_format={"type": "json_object"},
            max_tokens=150,
        )
        data = json.loads(resp.choices[0].message.content)
        score = int(data.get("score", 50))
        if data.get("has_text"):
            score = min(score, 30)
        if not data.get("is_premium", True):
            score = min(score, 50)
        return score, data.get("reason", "")
    except Exception as e:
        print(f"    ⚠ 品質チェックエラー: {e}")
        return 55, "評価スキップ"


def _generate_with_quality(prompt: str, service: str, client: OpenAI) -> dict:
    """品質チェック付き画像生成（最大2回試行、目標80点以上）"""
    best = {"bytes": None, "score": 0, "reason": ""}
    for attempt in range(2):
        img_bytes, _ = _generate_one_image(prompt, client)
        if not img_bytes:
            continue
        score, reason = _check_quality(img_bytes, service, client)
        print(f"    品質: {score}点 {reason}")
        if score > best["score"]:
            best = {"bytes": img_bytes, "score": score, "reason": reason}
        if score >= 80:
            break
        if attempt == 0:
            print(f"    ⚠ {score}点 < 80点 → 再生成（テンプレート品質基準）")
    return best


# ──────────────────────────────────────────────
# Phase 3: GCS保存（Drive SAストレージ制限のため）
# ──────────────────────────────────────────────

def _upload_to_gcs(image_bytes: bytes, filename: str, gcs_client) -> tuple[str, str, str]:
    """
    GCSへフル画像とサムネイルを保存し (filename, original_url, thumbnail_url) を返す。
    LINE画像メッセージ用:
      originalContentUrl  → フル画像（max 10MB）
      previewImageUrl     → サムネイルJPEG（max 1MB）
    URLはLINE APIが要求するURLエンコード済み形式で返す。
    """
    from urllib.parse import quote

    def _gcs_url(name: str) -> str:
        encoded = quote(name, safe="")
        return f"https://storage.googleapis.com/{GCS_BUCKET}/{encoded}"

    bucket = gcs_client.bucket(GCS_BUCKET)

    # フル画像保存（PNG）
    blob = bucket.blob(filename)
    blob.upload_from_string(image_bytes, content_type="image/png")
    original_url = _gcs_url(filename)
    print(f"    GCS フル画像: {len(image_bytes)//1024}KB → {original_url}")

    # サムネイル生成（JPEG, 400×700px以内, <1MB保証）
    thumbnail_url = original_url  # フォールバック: サムネイル失敗時はフル画像URL
    try:
        from PIL import Image as PILImage
        thumb_name = filename.replace(".png", "_thumb.jpg")
        img = PILImage.open(io.BytesIO(image_bytes)).convert("RGB")
        resample = getattr(PILImage, "Resampling", PILImage).LANCZOS
        img.thumbnail((400, 700), resample)
        thumb_buf = io.BytesIO()
        img.save(thumb_buf, format="JPEG", quality=80, optimize=True)
        thumb_bytes = thumb_buf.getvalue()
        thumb_blob = bucket.blob(thumb_name)
        thumb_blob.upload_from_string(thumb_bytes, content_type="image/jpeg")
        thumbnail_url = _gcs_url(thumb_name)
        print(f"    GCS サムネイル: {len(thumb_bytes)//1024}KB → {thumbnail_url}")
    except Exception as thumb_err:
        print(f"    ⚠ サムネイル生成スキップ（フォールバックあり）: {thumb_err}")

    return filename, original_url, thumbnail_url


# ──────────────────────────────────────────────
# Phase 5: LINE通知
# ──────────────────────────────────────────────

def _notify_line(token: str, message: str):
    if len(token) < 100:
        print("[LINE] トークン未設定スキップ")
        return
    try:
        requests.post(
            "https://api.line.me/v2/bot/message/broadcast",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"messages": [{"type": "text", "text": message}]},
            timeout=10,
        )
        print("[LINE] 通知送信完了")
    except Exception as e:
        print(f"[LINE] 通知エラー: {e}")


# ──────────────────────────────────────────────
# メインエントリポイント
# ──────────────────────────────────────────────

def run(
    title: str,
    body: str,
    service: str,
    blog_date: str = None,
    creds_path: str = None,
    line_token: str = None,
) -> dict:
    """
    ブログ画像を3枚生成してDrive保存・SS記録・LINE通知を行う。

    Args:
        title:      HPBブログタイトル
        body:       HPBブログ本文
        service:    メニュー（脱毛/セルフホワイトニング/よもぎ蒸し/カッピング）
        blog_date:  ブログ掲載日 (YYYY-MM-DD or YYYY/MM/DD, デフォルト今日)
        creds_path: Google SA credentials.json パス
        line_token: LINE Messaging API チャネルアクセストークン
    """
    if creds_path is None:
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "/app/credentials.json")
    if line_token is None:
        line_token = os.getenv("LINE_STAFF_TOKEN", "")

    today = (blog_date or datetime.date.today().strftime("%Y-%m-%d")).replace("/", "-")
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    folder_url = f"https://storage.googleapis.com/{GCS_BUCKET}/"

    print(f"\n{'='*50}")
    print(f"[BlogImage] {title[:40]} / {service} / {today}")
    print(f"{'='*50}")

    # Phase 1: プロンプト生成
    print("[Phase1] 画像プロンプト3案を生成中...")
    prompts, jp_descs = _generate_prompts(title, body, service, client)
    if not prompts:
        return {"ok": False, "error": "プロンプト生成失敗"}
    for i, (p, d) in enumerate(zip(prompts, jp_descs), 1):
        print(f"  案{i}: {d}")

    # GCS クライアント初期化（Phase3用）
    gcs_client = _get_gcs_client(creds_path)

    # Phase 2+3+6: 各プロンプトで画像生成→品質チェック→GCS保存
    results = []
    for i, (prompt, jp_desc) in enumerate(zip(prompts, jp_descs), 1):
        print(f"\n[Phase2+6] 画像{i}/{len(prompts)} 生成中... ({jp_desc})")
        best = _generate_with_quality(prompt, service, client)

        if not best["bytes"]:
            print(f"  ❌ 画像{i} 生成失敗")
            results.append({"prompt": prompt, "jp_desc": jp_desc, "file_id": "", "url": "", "score": 0})
            continue

        # Phase 3: GCS保存
        print(f"[Phase3] 画像{i} をGCSへ保存中...")
        title_safe = title[:15].replace("/", "_").replace(" ", "_")
        filename = f"{today}_{title_safe}_{i:02d}.png"
        try:
            _, gcs_url, _ = _upload_to_gcs(best["bytes"], filename, gcs_client)
            print(f"  ✅ {filename} 保存完了: {gcs_url}")
        except Exception as e:
            print(f"  ❌ GCS保存失敗: {e}")
            gcs_url = ""

        results.append({
            "prompt": prompt,
            "jp_desc": jp_desc,
            "file_id": filename,
            "url": gcs_url,
            "score": best["score"],
        })

    # 推奨画像（最高スコア）
    best_idx = max(range(len(results)), key=lambda x: results[x]["score"]) if results else 0
    recommended = results[best_idx] if results else {}

    # Phase 4: スプレッドシート記録
    print("\n[Phase4] スプレッドシートへ記録中...")
    try:
        gc = _get_sheets_client(creds_path)
        ss = gc.open_by_key(BEAUTY_SPREADSHEET_ID)
        sh = _get_or_create_sheet(ss)
        now_str = datetime.datetime.now().strftime("%Y/%m/%d %H:%M")
        row = [
            now_str,
            today,
            title,
            service,
            results[0]["url"] if len(results) > 0 else "",
            results[1]["url"] if len(results) > 1 else "",
            results[2]["url"] if len(results) > 2 else "",
            best_idx + 1,
            results[0]["prompt"][:200] if len(results) > 0 else "",
            results[1]["prompt"][:200] if len(results) > 1 else "",
            results[2]["prompt"][:200] if len(results) > 2 else "",
            results[0]["score"] if len(results) > 0 else 0,
            results[1]["score"] if len(results) > 1 else 0,
            results[2]["score"] if len(results) > 2 else 0,
            folder_url,
        ]
        sh.append_row(row)
        print("  ✅ 記録完了")
    except Exception as e:
        print(f"  ❌ SS記録エラー: {e}")

    # Phase 5: LINE通知
    print("\n[Phase5] LINE通知送信中...")
    line_msg = (
        f"【生成完了】Tree Beauty ブログ画像\n\n"
        f"【ブログタイトル】\n{title}\n\n"
        f"【使用メニュー】{service}\n"
        f"【生成日】{today}\n\n"
        f"【推奨画像（案{best_idx+1}）】\n"
        f"{recommended.get('url', '（Drive保存失敗）')}\n\n"
        f"【保存先】\n{folder_url}\n\n"
        f"【推奨案の特徴】\n{recommended.get('jp_desc', '')}\n"
        f"【品質スコア】{recommended.get('score', 0)}点\n\n"
        f"【使用プロンプト（推奨案）】\n{recommended.get('prompt', '')[:150]}...\n\n"
        f"【予約訴求ポイント】\n高級感・清潔感・{service}で自分を磨く女性の世界観"
    )
    _notify_line(line_token, line_msg)

    print(f"\n{'='*50}")
    print(f"✅ 完了: {len([r for r in results if r['url']])}枚保存 / 推奨: 案{best_idx+1}")
    print(f"{'='*50}")

    return {
        "ok": True,
        "title": title,
        "service": service,
        "date": today,
        "images_generated": len([r for r in results if r["url"]]),
        "recommended": best_idx + 1,
        "folder_url": folder_url,
        "images": [
            {
                "number": i + 1,
                "url": r["url"],
                "score": r["score"],
                "jp_desc": r["jp_desc"],
                "prompt": r["prompt"],
            }
            for i, r in enumerate(results)
        ],
    }


def run_from_sheet(blog_date: str = None, creds_path: str = None, line_token: str = None) -> dict:
    """
    HPBブログシートから指定日のブログを取得して run() を実行する。
    blog_date: YYYY-MM-DD or YYYY/MM/DD (省略時は今日)
    """
    if creds_path is None:
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "/app/credentials.json")

    target = (blog_date or datetime.date.today().strftime("%Y/%m/%d")).replace("-", "/")

    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    gc = gspread.authorize(creds)
    ss = gc.open_by_key(BEAUTY_SPREADSHEET_ID)

    try:
        sh = ss.worksheet("HPBブログ")
    except gspread.WorksheetNotFound:
        return {"ok": False, "error": "HPBブログシートが見つかりません"}

    records = sh.get_all_records()
    matched = next(
        (r for r in records if str(r.get("日付", "")).replace("-", "/") == target),
        None,
    )
    if not matched:
        return {"ok": False, "error": f"日付 {target} のブログが見つかりません"}

    return run(
        title=str(matched.get("タイトル", "")),
        body=str(matched.get("本文", "")),
        service=str(matched.get("カテゴリ", "脱毛")),
        blog_date=target,
        creds_path=creds_path,
        line_token=line_token,
    )
