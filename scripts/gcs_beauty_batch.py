#!/usr/bin/env python3
"""
Tree Beauty 画像 GCS化バッチスクリプト
IMAGE_LIBRARY台帳で 事業=BEAUTY かつ gcs_public_url が空の行を対象に
Drive → GCS アップロードしてシートを更新する。

使い方:
  python3 scripts/gcs_beauty_batch.py              # 全BEAUTY画像をGCS化
  python3 scripts/gcs_beauty_batch.py --limit 10   # 最大10枚ずつ処理
  python3 scripts/gcs_beauty_batch.py --id IMG-BEAUTY-001,IMG-BEAUTY-002  # 指定IDのみ

注意:
  - 認証ファイル: GOOGLE_APPLICATION_CREDENTIALS または /Users/tokudayuya/tree-beauty-ai/credentials.json
  - 既存画像は削除しない（gcs_public_urlが空の行のみ処理）
  - GCS bucket: tree-beauty-blog-images / path: image-library/beauty/{IMG_ID}_{timestamp}.jpeg
  - 429対策: 1.5s/cell + 3s/image
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
    from PIL import Image
except ImportError as e:
    print(f"❌ 依存パッケージが不足しています: {e}")
    print("   pip install gspread google-auth google-api-python-client google-cloud-storage Pillow")
    sys.exit(1)

# ─── 設定 ────────────────────────────────────────────────────────
CREDS_FILE = os.getenv(
    "GOOGLE_APPLICATION_CREDENTIALS",
    "/Users/tokudayuya/tree-beauty-ai/credentials.json"
)
SPREADSHEET_ID = "15cfsC2HIzu1FGW602dxqNuv-DJpmLiZhatvB-hDn2XM"
SHEET_NAME     = "画像台帳"
GCS_BUCKET     = "tree-beauty-blog-images"
GCS_PREFIX     = "image-library/beauty"
GCP_PROJECT    = "tree-beauty-ai-499303"
BUSINESS_KEY   = "BEAUTY"  # 事業列のフィルタ値

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/cloud-platform",
]

SLEEP_PER_CELL  = 1.5  # Sheets API 429防止
SLEEP_PER_IMAGE = 3.0  # Drive → GCS 完了後


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


def _to_jpeg(raw_bytes: bytes) -> bytes:
    from PIL import ImageOps
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw_bytes))).convert("RGB")
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=88)
    return out.getvalue()


def _upload_to_gcs(bucket, img_id: str, jpeg_bytes: bytes) -> tuple[str, str]:
    ts   = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    path = f"{GCS_PREFIX}/{img_id}_{ts}.jpeg"
    blob = bucket.blob(path)
    blob.upload_from_string(jpeg_bytes, content_type="image/jpeg")
    pub_url = f"https://storage.googleapis.com/{GCS_BUCKET}/{path}"
    return pub_url, path


def run(limit: int = 0, target_ids: list[str] = None):
    print("=" * 60)
    print("  Tree Beauty 画像 GCS化バッチ")
    print(f"  認証: {CREDS_FILE}")
    print("=" * 60)

    if not os.path.exists(CREDS_FILE):
        print(f"❌ 認証ファイルが見つかりません: {CREDS_FILE}")
        print("   GOOGLE_APPLICATION_CREDENTIALS 環境変数を設定してください")
        sys.exit(1)

    creds     = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
    gc        = gspread.authorize(creds)
    drive_svc = build("drive", "v3", credentials=creds)
    gcs_cli   = storage.Client(credentials=creds, project=GCP_PROJECT)
    bucket    = gcs_cli.bucket(GCS_BUCKET)

    ws      = gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
    all_data = ws.get_all_values()
    headers  = all_data[0]

    def colidx(name: str) -> int:
        try:
            return headers.index(name)
        except ValueError:
            raise ValueError(f"列 '{name}' が見つかりません。ヘッダー: {headers}")

    IMG_ID_COL    = colidx("画像ID")
    DRIVE_URL_COL = colidx("Drive URL")
    GCS_URL_COL   = colidx("gcs_public_url")
    GCS_PATH_COL  = colidx("gcs_path")
    VALID_COL     = colidx("is_public_url_valid")
    THEME_COL     = colidx("image_theme")
    VERIFIED_COL  = colidx("is_theme_verified")

    # 事業列を探す（なければスキップ）
    try:
        BIZ_COL = colidx("事業")
    except ValueError:
        BIZ_COL = None

    print(f"\nシート行数（ヘッダー含む）: {len(all_data)}")

    # 対象行を絞り込む
    targets = []
    for row_idx, row in enumerate(all_data[1:], start=2):
        img_id = row[IMG_ID_COL] if len(row) > IMG_ID_COL else ""

        # 事業フィルタ（列がある場合）
        if BIZ_COL is not None:
            biz = str(row[BIZ_COL]).strip().upper() if len(row) > BIZ_COL else ""
            if biz != BUSINESS_KEY:
                continue

        # 指定IDフィルタ
        if target_ids and img_id not in target_ids:
            continue

        # GCS化済みはスキップ
        gcs_url = row[GCS_URL_COL] if len(row) > GCS_URL_COL else ""
        if gcs_url:
            continue

        drive_url = row[DRIVE_URL_COL] if len(row) > DRIVE_URL_COL else ""
        if not drive_url:
            print(f"  ⚠️  {img_id}: Drive URLなし → スキップ")
            continue

        targets.append({
            "row_idx":   row_idx,
            "img_id":    img_id,
            "drive_url": drive_url,
            "theme":     row[THEME_COL] if len(row) > THEME_COL else "",
        })

    if limit > 0:
        targets = targets[:limit]

    print(f"対象: {len(targets)}枚（BEAUTY・GCS化未済み）\n")

    if not targets:
        print("✅ 処理対象なし（全件GCS化済み、またはBEAUTY画像が未登録）")
        return

    success = 0
    fail    = 0

    for i, t in enumerate(targets, 1):
        img_id    = t["img_id"]
        drive_url = t["drive_url"]
        row_idx   = t["row_idx"]

        print(f"  [{i}/{len(targets)}] {img_id} ...", end="", flush=True)

        file_id = _extract_drive_id(drive_url)
        if not file_id:
            print(f" ❌ Drive ID抽出失敗: {drive_url}")
            fail += 1
            continue

        try:
            raw   = _download_from_drive(drive_svc, file_id)
            jpeg  = _to_jpeg(raw)
            pub_url, gcs_path = _upload_to_gcs(bucket, img_id, jpeg)
        except Exception as e:
            print(f" ❌ {e}")
            fail += 1
            continue

        # シート更新（列ごとに更新・429対策）
        def cell(col_idx: int) -> str:
            import string
            col_idx += 1  # 1始まり
            letters = ""
            while col_idx:
                col_idx, rem = divmod(col_idx - 1, 26)
                letters = string.ascii_uppercase[rem] + letters
            return f"{letters}{row_idx}"

        updates = [
            (cell(GCS_URL_COL),  pub_url),
            (cell(GCS_PATH_COL), gcs_path),
            (cell(VALID_COL),    "TRUE"),
        ]
        for cell_addr, val in updates:
            for attempt in range(3):
                try:
                    ws.update(values=[[val]], range_name=cell_addr)
                    time.sleep(SLEEP_PER_CELL)
                    break
                except Exception as e:
                    if "429" in str(e) and attempt < 2:
                        print(f"\n    ⏳ 429 rate limit、15秒待機...", end="")
                        time.sleep(15)
                    else:
                        print(f"\n    ⚠️  シート更新失敗 {cell_addr}: {e}")
                        break

        print(f" ✅  {pub_url}")
        success += 1
        time.sleep(SLEEP_PER_IMAGE)

    print(f"\n{'─'*60}")
    print(f"  完了: ✅{success}枚  ❌{fail}枚")
    print(f"{'─'*60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tree Beauty 画像GCS化バッチ")
    parser.add_argument("--limit", type=int, default=0, help="処理上限枚数（0=全件）")
    parser.add_argument("--id",    type=str, default="",  help="カンマ区切り画像ID指定")
    args = parser.parse_args()

    target_ids = [x.strip() for x in args.id.split(",") if x.strip()] if args.id else None
    run(limit=args.limit, target_ids=target_ids)
