#!/usr/bin/env python3
"""
TACHINOMIYA 画像向き修正 GCS再アップロードスクリプト
- IMAGE_LIBRARY の TACHINOMIYA 画像（全カテゴリ）を対象
- Drive から再DL → ImageOps.exif_transpose で向き修正 → GCS 再アップロード
- gcs_public_url / gcs_path を上書き更新

使い方:
  GOOGLE_APPLICATION_CREDENTIALS=/path/to/creds.json python3 scripts/gcs_tachinomiya_orientation_fix.py
  GOOGLE_APPLICATION_CREDENTIALS=/path/to/creds.json python3 scripts/gcs_tachinomiya_orientation_fix.py --category BAR
  GOOGLE_APPLICATION_CREDENTIALS=/path/to/creds.json python3 scripts/gcs_tachinomiya_orientation_fix.py --category "サーターアンダギー"
  GOOGLE_APPLICATION_CREDENTIALS=/path/to/creds.json python3 scripts/gcs_tachinomiya_orientation_fix.py --limit 10

注意:
  - 既存 gcs_public_url を上書きします（Drive ファイルIDが空の行はスキップ）
  - Scheduler / 実投稿には触らない・シートへの書き込みのみ
"""

import os
import sys
import re
import time
import io
import datetime
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import gspread
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    from google.cloud import storage
    from PIL import Image, ImageOps
except ImportError as e:
    print(f"❌ 依存パッケージが不足しています: {e}")
    print("   pip install gspread google-auth google-api-python-client google-cloud-storage Pillow")
    sys.exit(1)

# ─── 設定 ──────────────────────────────────────────────────────────
CREDS_FILE = os.getenv(
    "GOOGLE_APPLICATION_CREDENTIALS",
    "/Users/tokudayuya/tree-beauty-ai/credentials.json"
)
SPREADSHEET_ID = "15cfsC2HIzu1FGW602dxqNuv-DJpmLiZhatvB-hDn2XM"
SHEET_NAME     = "画像台帳"
GCS_BUCKET     = "tree-beauty-blog-images"
GCS_PREFIX     = "image-library/tachinomiya"
GCP_PROJECT    = "tree-beauty-ai-499303"
BUSINESS_KEY   = "TACHINOMIYA"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/cloud-platform",
]

SLEEP_PER_CELL  = 1.2
SLEEP_PER_IMAGE = 2.5


def _extract_drive_id(url: str) -> str:
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else ""


def _download_from_drive(drive_svc, file_id: str) -> bytes:
    req = drive_svc.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    dl  = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    return buf.getvalue()


def _to_jpeg_with_orientation_fix(raw_bytes: bytes) -> bytes:
    """EXIF向き情報をピクセルに適用してJPEG変換（横向き→縦向き修正）"""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw_bytes))).convert("RGB")
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=88, optimize=True)
    return out.getvalue()


def _upload_to_gcs(bucket, img_id: str, jpeg_bytes: bytes) -> tuple[str, str]:
    ts   = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    path = f"{GCS_PREFIX}/{img_id}_{ts}_fixed.jpeg"
    blob = bucket.blob(path)
    blob.cache_control = "public, max-age=31536000"
    blob.upload_from_string(jpeg_bytes, content_type="image/jpeg")
    pub_url = f"https://storage.googleapis.com/{GCS_BUCKET}/{path}"
    return pub_url, path


def run(category_filter: str = None, limit: int = 0, target_ids: list = None):
    print("=" * 65)
    print("  TACHINOMIYA 画像向き修正 GCS再アップロード")
    cat_label = f"カテゴリ={category_filter}" if category_filter else "全カテゴリ"
    print(f"  対象: {cat_label}")
    print("=" * 65)

    if not os.path.exists(CREDS_FILE):
        print(f"❌ 認証ファイルが見つかりません: {CREDS_FILE}")
        sys.exit(1)

    creds     = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
    gc        = gspread.authorize(creds)
    drive_svc = build("drive", "v3", credentials=creds)
    gcs_cli   = storage.Client(credentials=creds, project=GCP_PROJECT)
    bucket    = gcs_cli.bucket(GCS_BUCKET)

    ws       = gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
    all_data = ws.get_all_values()
    headers  = all_data[0]

    def colidx(name: str) -> int:
        try:
            return headers.index(name)
        except ValueError:
            raise ValueError(f"列 '{name}' が見つかりません。ヘッダー: {headers}")

    IMG_ID_COL      = colidx("画像ID")
    FILENAME_COL    = colidx("ファイル名")
    DRIVE_URL_COL   = colidx("Drive URL")
    DRIVE_ID_COL    = colidx("Drive ファイルID")
    BIZ_COL         = colidx("事業名")
    CAT_COL         = colidx("カテゴリ")

    try:
        GCS_URL_COL  = colidx("gcs_public_url")
        GCS_PATH_COL = colidx("gcs_path")
    except ValueError:
        print("⚠ gcs_public_url / gcs_path 列が見つかりません。処理を中断します。")
        print("  先に gcs_beauty_batch.py でBEAUTY用シートを初期化してください。")
        sys.exit(1)

    targets = []
    for ri, row in enumerate(all_data[1:], start=2):
        def cell(col):
            return row[col].strip() if col < len(row) else ""

        if cell(BIZ_COL) != BUSINESS_KEY:
            continue

        img_id   = cell(IMG_ID_COL)
        filename = cell(FILENAME_COL)
        drive_id = cell(DRIVE_ID_COL)
        drive_url = cell(DRIVE_URL_COL)
        category  = cell(CAT_COL)

        if not drive_id and drive_url:
            drive_id = _extract_drive_id(drive_url)

        if not drive_id:
            continue

        if target_ids and img_id not in target_ids:
            continue

        if category_filter and category != category_filter:
            continue

        targets.append({
            "row": ri, "img_id": img_id, "filename": filename,
            "drive_id": drive_id, "category": category,
        })

    if not targets:
        print(f"⚠ 対象画像が見つかりません（BIZ={BUSINESS_KEY}, category={category_filter}）")
        return

    if limit > 0:
        targets = targets[:limit]

    print(f"\n対象: {len(targets)} 件\n")

    ok = ng = skip = 0
    for t in targets:
        row_no   = t["row"]
        img_id   = t["img_id"]
        filename = t["filename"]
        drive_id = t["drive_id"]
        category = t["category"]

        print(f"  [{row_no}] {img_id} ({category}) {filename[:40]}")

        try:
            raw = _download_from_drive(drive_svc, drive_id)
            if not raw:
                print(f"    ❌ Drive DL 失敗")
                ng += 1
                continue
        except Exception as e:
            print(f"    ❌ Drive DL エラー: {e}")
            ng += 1
            continue

        try:
            jpeg = _to_jpeg_with_orientation_fix(raw)
        except Exception as e:
            print(f"    ❌ JPEG変換失敗: {e}")
            ng += 1
            continue

        try:
            pub_url, gcs_path = _upload_to_gcs(bucket, img_id, jpeg)
        except Exception as e:
            print(f"    ❌ GCS アップロード失敗: {e}")
            ng += 1
            continue

        try:
            ws.update_cell(row_no, GCS_URL_COL + 1, pub_url)
            time.sleep(SLEEP_PER_CELL)
            ws.update_cell(row_no, GCS_PATH_COL + 1, gcs_path)
            time.sleep(SLEEP_PER_CELL)
        except Exception as e:
            print(f"    ⚠ シート更新失敗（GCS URLは上書き済み）: {e}")
            ng += 1
            continue

        print(f"    ✅ 完了 → {pub_url[:80]}")
        ok += 1
        time.sleep(SLEEP_PER_IMAGE)

    print(f"\n{'='*65}")
    print(f"  完了: OK={ok} / NG={ng} / スキップ={skip} / 合計={len(targets)}")
    print(f"{'='*65}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TACHINOMIYA画像向き修正GCS再アップロード")
    parser.add_argument("--category", default=None, help="対象カテゴリ（例: BAR, サーターアンダギー）")
    parser.add_argument("--limit", type=int, default=0, help="処理上限件数（0=無制限）")
    parser.add_argument("--id", default=None, help="対象画像IDをカンマ区切りで指定")
    args = parser.parse_args()
    target_ids = [i.strip() for i in args.id.split(",")] if args.id else None
    run(category_filter=args.category, limit=args.limit, target_ids=target_ids)
