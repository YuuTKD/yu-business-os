"""
YU HOLDINGS IMAGE LIBRARY - AI画像管理・選定システム（実写優先版）

フロー:
  スキャン: Drive自動検出 → GPT-4o Vision解析 → カテゴリ付与 → 台帳登録
  選定: 投稿内容解析 → 実写画像優先検索 → AI生成（実写なし時のみ）
"""

import os
import io
import json
import time
import base64
import datetime

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from openai import OpenAI

METADATA_SPREADSHEET_ID = os.getenv(
    "IMAGE_LIBRARY_SPREADSHEET_ID",
    "15cfsC2HIzu1FGW602dxqNuv-DJpmLiZhatvB-hDn2XM",
)

METADATA_SHEET = "画像台帳"
STATS_SHEET = "利用統計"

FOLDER_MAP = {
    "BEAUTY": {
        "root": "1KwoeBNTiN8jnmuBIBvz2D80xFnwxi2gu",
        "categories": ["脱毛", "セルフホワイトニング", "よもぎ蒸し", "スタッフ", "ビフォーアフター", "お客様の声", "店舗内観", "店舗外観"],
    },
    "CATERING": {
        "root": "1pXpdO5PiSuIt6NCH1ROPFmRnn4IQItqe",
        "categories": ["ケータリング", "オードブル", "会議用弁当", "来客用弁当", "イベント", "配達風景", "法人利用", "お客様の声"],
    },
    "TACHINOMIYA": {
        "root": "12lC9_S6Q_hV4tQ9THcy689YjFC-Vn9Us",
        "categories": ["フード", "ドリンク", "BAR", "UberEats", "出前館", "サーターアンダギー", "店舗内観", "店舗外観", "商品写真", "イベント"],
    },
    "HINABE": {
        "root": "1owSjoNNgAS6vPhr9rVHI7tD4hloBLmdL",
        "categories": ["火鍋", "食材", "店舗内観", "店舗外観", "宴会", "お客様の声"],
    },
    "COMMON": {
        "root": "1v4XRXv9UK2vHiONOW3vVHFwVmysOLUUD",
        "categories": ["ロゴ", "キャンペーン", "季節素材", "背景素材", "アイコン"],
    },
}

BIZ_KEY_MAP = {
    "beauty":        "BEAUTY",
    "catering":      "CATERING",
    "tachinomiya":   "TACHINOMIYA",
    "hinabe":        "HINABE",
    "ryukyu_hinabe": "HINABE",
}

SEASON_MAP = {
    1: "冬", 2: "冬", 3: "春", 4: "春", 5: "春", 6: "夏",
    7: "夏", 8: "夏", 9: "秋", 10: "秋", 11: "秋", 12: "冬",
}

METADATA_HEADERS = [
    # 既存 16 列（変更不可）
    "画像ID", "ファイル名", "Drive URL", "Drive ファイルID",
    "事業名", "カテゴリ", "サブカテゴリ", "季節", "媒体タグ",
    "ALT テキスト", "撮影日", "登録日", "利用回数", "最終利用日", "ソース", "備考",
    # 追加 22 列（GCS再利用・品質管理）
    "gcs_public_url", "gcs_path", "business_key", "image_usage",
    "content_type", "file_size_bytes", "file_size_mb", "width", "height",
    "is_public_url_valid", "http_status", "usage_status",
    "needs_compression", "compression_status",
    "can_use_for_threads", "can_use_for_instagram",
    "ng_reason", "quality_score", "brand_fit_score",
    "updated_at", "last_post_url", "last_post_id",
]

STATS_HEADERS = [
    "利用日時", "画像ID", "ファイル名", "事業名", "カテゴリ",
    "投稿媒体", "投稿内容（抜粋）", "選定スコア",
]

IMAGE_MIMETYPES = {"image/jpeg", "image/png", "image/heic", "image/webp", "image/gif"}


# ─────────────────────────────────────────────────────
# 共通ユーティリティ
# ─────────────────────────────────────────────────────

def _get_gc(creds_path: str, include_drive: bool = False):
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    if include_drive:
        scopes.append("https://www.googleapis.com/auth/drive.readonly")
    creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
    return gspread.authorize(creds)


def get_gc(creds_path: str):
    return _get_gc(creds_path, include_drive=True)


def _get_drive_service(creds_path: str):
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    return build("drive", "v3", credentials=creds)


def get_or_create_sheet(ss, title: str, rows: int = 1000, cols: int = 20):
    try:
        return ss.worksheet(title)
    except gspread.WorksheetNotFound:
        return ss.add_worksheet(title=title, rows=rows, cols=cols)


# ─────────────────────────────────────────────────────
# Drive スキャン内部関数
# ─────────────────────────────────────────────────────

def _list_folder_contents(drive_svc, folder_id: str) -> tuple[list, list]:
    """フォルダ内の(サブフォルダリスト, 画像ファイルリスト)を返す"""
    subfolders, files = [], []
    page_token = None
    while True:
        result = drive_svc.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken, files(id, name, mimeType, size)",
            pageSize=100,
            pageToken=page_token,
        ).execute()
        for item in result.get("files", []):
            if item["mimeType"] == "application/vnd.google-apps.folder":
                subfolders.append(item)
            elif item.get("mimeType", "").startswith("image/"):
                files.append(item)
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return subfolders, files


def _match_category(folder_name: str, categories: list) -> str:
    if folder_name in categories:
        return folder_name
    for cat in categories:
        if cat in folder_name or folder_name in cat:
            return cat
    return categories[0] if categories else "その他"


def _download_thumbnail(drive_svc, file_id: str, max_px: int = 800) -> bytes | None:
    """Drive画像をダウンロードしてリサイズしたJPEGバイトを返す"""
    try:
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(
            buf, drive_svc.files().get_media(fileId=file_id)
        )
        done = False
        while not done:
            _, done = downloader.next_chunk()
        buf.seek(0)

        from PIL import Image as PILImage
        img = PILImage.open(buf).convert("RGB")
        img.thumbnail(
            (max_px, max_px),
            getattr(PILImage, "Resampling", PILImage).LANCZOS,
        )
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85)
        return out.getvalue()
    except Exception as e:
        print(f"    ⚠ 画像DLエラー {file_id}: {e}")
        return None


def _analyze_with_vision(
    image_bytes: bytes,
    filename: str,
    business: str,
    categories: list,
    openai_client: OpenAI,
) -> dict:
    """GPT-4o Vision で画像を解析（カテゴリ・ALTテキスト自動付与）"""
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    cats_str = "、".join(categories)
    prompt = (
        f"事業「{business}」の実写画像を分類してください。\n\n"
        f"利用可能なカテゴリ: {cats_str}\n\n"
        "以下のJSONのみ返してください（余分なテキスト不可）:\n"
        '{"category":"カテゴリ名","alt_text":"画像説明（日本語50文字以内）",'
        '"quality":0.8,"tags":["タグ1","タグ2"]}'
    )
    try:
        resp = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{b64}",
                        "detail": "low",
                    }},
                ],
            }],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=200,
        )
        result = json.loads(resp.choices[0].message.content)
        if result.get("category") not in categories:
            result["category"] = categories[0]
        return result
    except Exception as e:
        print(f"    ⚠ Vision解析エラー {filename}: {e}")
        return {"category": categories[0], "alt_text": filename[:50], "quality": 0.5, "tags": []}


def _get_registered_file_ids(gc, ss_id: str) -> set:
    try:
        ss = gc.open_by_key(ss_id)
        sh = ss.worksheet(METADATA_SHEET)
        return set(filter(None, sh.col_values(4)[1:]))
    except Exception:
        return set()


# ─────────────────────────────────────────────────────
# セットアップ（初回のみ）
# ─────────────────────────────────────────────────────

def setup_metadata_sheet(creds_path: str = None):
    if creds_path is None:
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "/app/credentials.json")

    gc = get_gc(creds_path)
    ss = gc.open_by_key(METADATA_SPREADSHEET_ID)

    sh = get_or_create_sheet(ss, METADATA_SHEET)
    sh.clear()
    sh.update(range_name="A1", values=[METADATA_HEADERS])
    sh.format("A1:P1", {
        "backgroundColor": {"red": 0.059, "green": 0.09, "blue": 0.165},
        "textFormat": {"bold": True, "fontSize": 10,
                       "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        "horizontalAlignment": "CENTER",
    })

    st = get_or_create_sheet(ss, STATS_SHEET)
    st.clear()
    st.update(range_name="A1", values=[STATS_HEADERS])
    st.format("A1:H1", {
        "backgroundColor": {"red": 0.153, "green": 0.392, "blue": 0.294},
        "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
    })

    fl = get_or_create_sheet(ss, "フォルダ一覧")
    fl.clear()
    fl.update(range_name="A1", values=[["事業名", "カテゴリ", "ルートフォルダID"]])
    folder_rows = []
    for biz, data in FOLDER_MAP.items():
        for cat in data["categories"]:
            folder_rows.append([biz, cat, data["root"]])
    if folder_rows:
        fl.update(range_name="A2", values=folder_rows)

    print(f"✅ IMAGE_LIBRARY_METADATA セットアップ完了")
    return METADATA_SPREADSHEET_ID


# ─────────────────────────────────────────────────────
# Drive スキャン（実写画像自動登録）
# ─────────────────────────────────────────────────────

def scan_drive_images(
    business_keys: list = None,
    creds_path: str = None,
    max_per_folder: int = 50,
) -> dict:
    """
    Drive フォルダをスキャンし、新規画像を Vision 解析して台帳登録する。

    Args:
        business_keys: ["BEAUTY","CATERING","TACHINOMIYA","HINABE"] (None=全事業)
        max_per_folder: フォルダあたりの最大スキャン枚数
    """
    if creds_path is None:
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "/app/credentials.json")

    targets = business_keys or ["BEAUTY", "CATERING", "TACHINOMIYA", "HINABE"]

    drive_svc = _get_drive_service(creds_path)
    gc = get_gc(creds_path)
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    registered_ids = _get_registered_file_ids(gc, METADATA_SPREADSHEET_ID)
    ss = gc.open_by_key(METADATA_SPREADSHEET_ID)
    sh = get_or_create_sheet(ss, METADATA_SHEET)

    # ヘッダーが古い場合は更新
    existing_headers = sh.row_values(1)
    if "ソース" not in existing_headers:
        sh.update(range_name="A1", values=[METADATA_HEADERS])

    today = datetime.date.today().strftime("%Y/%m/%d")
    season = SEASON_MAP.get(datetime.date.today().month, "")
    total_new = 0
    total_skipped = 0
    by_biz = {}

    for biz_key in targets:
        biz_data = FOLDER_MAP.get(biz_key)
        if not biz_data:
            continue

        root_id = biz_data["root"]
        categories = biz_data["categories"]
        new_count = 0

        print(f"\n[Scan] {biz_key}")

        try:
            subfolders, root_files = _list_folder_contents(drive_svc, root_id)
        except Exception as e:
            print(f"  ❌ {e}")
            by_biz[biz_key] = {"error": str(e)}
            continue

        # (カテゴリ, ファイル情報) のリストを構築
        scan_items: list[tuple[str, dict]] = []
        for folder in subfolders:
            cat = _match_category(folder["name"], categories)
            try:
                _, ff = _list_folder_contents(drive_svc, folder["id"])
                for f in ff[:max_per_folder]:
                    scan_items.append((cat, f))
            except Exception:
                continue

        for f in root_files[:max_per_folder]:
            scan_items.append((categories[0], f))

        new_items = [(c, f) for c, f in scan_items if f["id"] not in registered_ids]
        print(f"  新規: {len(new_items)} / 全体: {len(scan_items)}")

        for cat, file_info in new_items:
            file_id = file_info["id"]
            filename = file_info["name"]

            thumb = _download_thumbnail(drive_svc, file_id)
            if not thumb:
                continue

            analysis = _analyze_with_vision(thumb, filename, biz_key, categories, openai_client)

            all_ids = sh.col_values(1)[1:]
            nums = [int(x.replace("IMG-", "")) for x in all_ids if x.startswith("IMG-")]
            image_id = f"IMG-{max(nums, default=0) + 1:05d}"

            row = [
                image_id,
                filename,
                f"https://drive.google.com/file/d/{file_id}/view",
                file_id,
                biz_key,
                analysis.get("category", cat),
                "",
                season,
                "、".join(analysis.get("tags", [])),
                analysis.get("alt_text", filename)[:50],
                "",
                today,
                0,
                "",
                "real",
                "",
            ]
            sh.append_row(row, value_input_option="RAW")
            registered_ids.add(file_id)
            new_count += 1
            total_new += 1
            print(f"  ✅ {image_id}: {filename} → {analysis.get('category', cat)}")
            time.sleep(0.8)

        total_skipped += len(scan_items) - len(new_items)
        by_biz[biz_key] = {"new": new_count, "scanned": len(scan_items)}

    return {
        "ok": True,
        "total_new": total_new,
        "total_skipped": total_skipped,
        "by_business": by_biz,
    }


# ─────────────────────────────────────────────────────
# 実写画像選定（投稿生成後に呼ぶ）
# ─────────────────────────────────────────────────────

def select_real_image(
    post_content: str,
    business: str,
    platform: str = "line",
    creds_path: str = None,
) -> dict | None:
    """
    実写画像（ソース=real）を優先して選定する。
    実写なし → None を返す（呼び出し元でAI生成にフォールバック）
    """
    if creds_path is None:
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "/app/credentials.json")

    gc = get_gc(creds_path)
    ss = gc.open_by_key(METADATA_SPREADSHEET_ID)
    sh = ss.worksheet(METADATA_SHEET)

    records = sh.get_all_records()
    candidates = [
        r for r in records
        if r.get("事業名") in (business, "COMMON")
        and r.get("Drive ファイルID")
        and r.get("ソース", "real") == "real"
    ]

    if not candidates:
        print(f"  ℹ {business}: 実写画像なし → AI生成")
        return None

    # 候補3件以下はスコアリングせず利用回数最少を返す
    if len(candidates) <= 3:
        matched = min(candidates, key=lambda r: int(r.get("利用回数", 0) or 0))
        return _build_result(matched, 0.7, "利用回数最少")

    candidate_list = "\n".join(
        f"- ID:{r['画像ID']} | カテゴリ:{r['カテゴリ']} | ALT:{r.get('ALT テキスト','')} | 利用:{r.get('利用回数',0)}"
        for r in candidates[:60]
    )

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    prompt = (
        f"以下の投稿内容に最も合う実写画像を選んでください。\n\n"
        f"【投稿内容】\n{post_content[:400]}\n\n"
        f"【媒体】{platform}\n\n"
        f"【候補】\n{candidate_list}\n\n"
        "選定基準: 1.テーマ一致度 2.カテゴリ 3.利用回数少\n\n"
        '{"selected_id":"IMG-xxxxx","reason":"理由30文字以内","score":0.0}'
    )

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        result = json.loads(resp.choices[0].message.content)
        selected_id = result.get("selected_id")
        matched = next((r for r in candidates if r["画像ID"] == selected_id), None)
        if not matched:
            matched = min(candidates, key=lambda r: int(r.get("利用回数", 0) or 0))
        return _build_result(matched, result.get("score", 0.8), result.get("reason", ""))
    except Exception as e:
        print(f"  ❌ AI選定エラー: {e}")
        matched = min(candidates, key=lambda r: int(r.get("利用回数", 0) or 0))
        return _build_result(matched, 0.5, "フォールバック")


def _build_result(record: dict, score: float, reason: str) -> dict:
    return {
        "image_id":      record["画像ID"],
        "filename":      record["ファイル名"],
        "drive_file_id": record["Drive ファイルID"],
        "drive_url":     record["Drive URL"],
        "category":      record["カテゴリ"],
        "score":         score,
        "reason":        reason,
        "source":        "real",
        "gcs_public_url": str(record.get("gcs_public_url", "") or "").strip(),
        "gcs_path":       str(record.get("gcs_path", "") or "").strip(),
    }


# ─────────────────────────────────────────────────────
# Drive から画像バイト取得（GCS保存用）
# ─────────────────────────────────────────────────────

def fetch_drive_image_bytes(file_id: str, creds_path: str = None) -> bytes | None:
    if creds_path is None:
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "/app/credentials.json")
    try:
        drive_svc = _get_drive_service(creds_path)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, drive_svc.files().get_media(fileId=file_id))
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue()
    except Exception as e:
        print(f"  ❌ Drive DL エラー {file_id}: {e}")
        return None


# ─────────────────────────────────────────────────────
# 利用記録
# ─────────────────────────────────────────────────────

def track_usage(
    image_id: str,
    platform: str,
    post_excerpt: str = "",
    score: float = 0.0,
    creds_path: str = None,
):
    if creds_path is None:
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "/app/credentials.json")

    gc = get_gc(creds_path)
    ss = gc.open_by_key(METADATA_SPREADSHEET_ID)
    sh = ss.worksheet(METADATA_SHEET)
    st = ss.worksheet(STATS_SHEET)

    now = datetime.datetime.now().strftime("%Y/%m/%d %H:%M")
    cell = sh.find(image_id, in_column=1)
    filename = business = category = ""
    if cell:
        row = cell.row
        current = sh.cell(row, 13).value or 0
        sh.update_cell(row, 13, int(current) + 1)
        sh.update_cell(row, 14, now)
        row_data = sh.row_values(row)
        filename = row_data[1] if len(row_data) > 1 else ""
        business = row_data[4] if len(row_data) > 4 else ""
        category = row_data[5] if len(row_data) > 5 else ""

    st.append_row([now, image_id, filename, business, category, platform, post_excerpt[:100], score])
    print(f"  ✅ 利用記録: {image_id} → {platform}")


def save_gcs_url(
    image_id: str,
    gcs_public_url: str,
    gcs_path: str = "",
    post_url: str = "",
    post_id: str = "",
    creds_path: str = None,
):
    """GCS アップロード後に IMAGE_LIBRARY へ URL を保存する。次回以降の再アップロードを防ぐ。"""
    if creds_path is None:
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "/app/credentials.json")
    try:
        gc = get_gc(creds_path)
        ss = gc.open_by_key(METADATA_SPREADSHEET_ID)
        sh = ss.worksheet(METADATA_SHEET)
        header = sh.row_values(1)
        cell = sh.find(image_id, in_column=1)
        if not cell:
            print(f"  ⚠ save_gcs_url: {image_id} が IMAGE_LIBRARY に見つからない")
            return

        def _col(name):
            try:
                return header.index(name) + 1
            except ValueError:
                return None

        now = datetime.datetime.now().strftime("%Y/%m/%d %H:%M")
        row = cell.row
        updates = [
            ("gcs_public_url", gcs_public_url),
            ("gcs_path",       gcs_path),
            ("updated_at",     now),
        ]
        if post_url:
            updates.append(("last_post_url", post_url))
        if post_id:
            updates.append(("last_post_id", post_id))

        for col_name, val in updates:
            c = _col(col_name)
            if c:
                sh.update_cell(row, c, val)

        print(f"  ✅ GCS URL 保存: {image_id} → {gcs_public_url[:60]}...")
    except Exception as e:
        print(f"  ⚠ save_gcs_url 失敗 ({image_id}): {e}")


# ─────────────────────────────────────────────────────
# 手動登録
# ─────────────────────────────────────────────────────

def register_image(
    filename: str,
    drive_file_id: str,
    business: str,
    category: str,
    subcategory: str = "",
    season: str = "",
    media_tags: str = "",
    alt_text: str = "",
    shoot_date: str = "",
    source: str = "real",
    note: str = "",
    creds_path: str = None,
) -> str:
    if creds_path is None:
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "/app/credentials.json")

    gc = get_gc(creds_path)
    ss = gc.open_by_key(METADATA_SPREADSHEET_ID)
    sh = ss.worksheet(METADATA_SHEET)

    all_ids = sh.col_values(1)[1:]
    nums = [int(x.replace("IMG-", "")) for x in all_ids if x.startswith("IMG-")]
    image_id = f"IMG-{max(nums, default=0) + 1:05d}"

    today = datetime.date.today().strftime("%Y/%m/%d")
    if not season and shoot_date:
        try:
            month = int(shoot_date.split("/")[1])
            season = SEASON_MAP.get(month, "")
        except Exception:
            pass

    row = [
        image_id,
        filename,
        f"https://drive.google.com/file/d/{drive_file_id}/view",
        drive_file_id,
        business,
        category,
        subcategory,
        season,
        media_tags,
        alt_text,
        shoot_date,
        today,
        0,
        "",
        source,
        note,
    ]
    sh.append_row(row)
    print(f"  ✅ 登録: {image_id} ({business}/{category}/{filename})")
    return image_id


# ─────────────────────────────────────────────────────
# 後方互換: select_and_track
# ─────────────────────────────────────────────────────

def select_image(
    post_content: str,
    business: str,
    platform: str = "instagram",
    top_k: int = 5,
    creds_path: str = None,
) -> dict | None:
    """実写優先で選定（後方互換）"""
    return select_real_image(post_content, business, platform, creds_path)


def select_and_track(
    post_content: str,
    business: str,
    platform: str,
    creds_path: str = None,
) -> dict | None:
    result = select_real_image(post_content, business, platform, creds_path=creds_path)
    if result:
        track_usage(result["image_id"], platform, post_content[:100], result.get("score", 0), creds_path)
    return result


# ─────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "/app/credentials.json")
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""

    if cmd == "setup":
        setup_metadata_sheet(creds)
    elif cmd == "scan":
        keys = sys.argv[2:] or None
        result = scan_drive_images(business_keys=keys, creds_path=creds)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif cmd == "test-select":
        result = select_real_image(
            "国際通りでサーターアンダギーを食べながら一杯いかがですか？",
            "TACHINOMIYA", creds_path=creds,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("Usage: python image_manager.py [setup | scan [BIZ...] | test-select]")
