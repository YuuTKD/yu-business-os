"""
Threads 自動投稿エンジン（4事業共通）
--------------------------------------
SNS_POST_STOCK シートの以下の条件行を自動で Threads 投稿する。

  platform  : "Threads投稿"
  status    : "未投稿"
  scheduled_date: 本日以前（空なら即日扱い）

投稿後に status="投稿済み"・posted_date・posted_url を書き戻す。

画像自動選定:
  image_url が空の行は Drive IMAGE_LIBRARY から投稿テキストに最も合う実写画像を AI が選定し
  GCS にアップロードして公開 HTTPS URL を生成してから Threads へ投稿する。
  画像が見つからない場合はテキストのみ投稿。

安全装置:
  - dry_run=True がデフォルト（誤投稿防止）
  - 1事業あたり max_per_biz=1 件/回（スパム防止）
  - business_name が ALLOWED_BIZ 以外は自動スキップ
  - 投稿失敗時は status を変更せず次の行へ

Cloud Scheduler 推奨設定:
  毎日 11:00 JST → POST /threads-auto-post  (dry_run=false は body で明示指定)
"""

import io
import os
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import gspread
from google.oauth2.service_account import Credentials

GCS_BUCKET = os.getenv("GCS_IMAGE_BUCKET", "tree-beauty-blog-images")

# biz_key → IMAGE_LIBRARY の事業キー（image_manager.FOLDER_MAP と対応）
_BIZ_TO_LIB = {
    "beauty":        "BEAUTY",
    "catering":      "CATERING",
    "tachinomiya":   "TACHINOMIYA",
    "ryukyu_hinabe": "HINABE",
}

JST = timezone(timedelta(hours=9))

# business_name（シート表示名）→ threads_api の正規 biz_key
_NAME_TO_KEY: dict[str, str] = {
    "Tree Beauty":       "beauty",
    "TREE's Catering":   "catering",
    "Trees Catering":    "catering",
    "TACHINOMIYA":       "tachinomiya",
    "琉球火鍋":            "ryukyu_hinabe",
    # 短縮キー直打ち対応
    "beauty":            "beauty",
    "catering":          "catering",
    "tachinomiya":       "tachinomiya",
    "ryukyu_hinabe":     "ryukyu_hinabe",
}

# platform 列で Threads 投稿と判断する値
_THREADS_PLATFORMS = {"Threads投稿", "threads", "Threads", "THREADS"}

PENDING_STATUS  = "未投稿"
DONE_STATUS     = "投稿済み"


# ── helpers ───────────────────────────────────────────────

def _now() -> str:
    return datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")

def _today() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d")

def _gc(creds_path: str) -> gspread.Client:
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"],
    )
    return gspread.authorize(creds)

def _extract_image_url(row: dict) -> str:
    """image_url 列 → なければ memo 列から https://...jpg/png パターンを抽出"""
    url = str(row.get("image_url", "") or "").strip()
    if url.startswith("https://"):
        return url
    memo = str(row.get("memo", "") or "").strip()
    m = re.search(r"https://\S+\.(jpg|jpeg|png)", memo, re.IGNORECASE)
    return m.group(0) if m else ""


def _resolve_image_for_threads(biz_key: str, text: str, creds_path: str) -> str:
    """
    Drive IMAGE_LIBRARY から投稿テキストに最も合う実写画像を AI が選定し、
    GCS にアップロードして公開 HTTPS URL を返す。

    画像なし・アップロード失敗時は "" を返す（呼び出し元でテキスト投稿にフォールバック）。
    """
    try:
        from core.image_manager import select_real_image, fetch_drive_image_bytes, track_usage
        from google.cloud import storage as gcs_lib

        lib_key = _BIZ_TO_LIB.get(biz_key, biz_key.upper())
        selected = select_real_image(text, lib_key, platform="threads", creds_path=creds_path)
        if not selected:
            print(f"  ℹ {biz_key}: 実写画像なし → テキスト投稿")
            return ""

        image_bytes = fetch_drive_image_bytes(selected["drive_file_id"], creds_path)
        if not image_bytes:
            print(f"  ⚠ {biz_key}: Drive DL 失敗 → テキスト投稿")
            return ""

        # JPEG 変換（Threads API 推奨形式）
        try:
            from PIL import Image as PILImage
            img = PILImage.open(io.BytesIO(image_bytes)).convert("RGB")
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=90)
            image_bytes = out.getvalue()
        except Exception:
            pass

        # GCS アップロード → 公開 HTTPS URL
        today = _today()
        fname_safe = re.sub(r"[^\w\-.]", "_", selected["filename"][:20])
        gcs_path = f"content/threads/{biz_key}/{today}_{fname_safe}.jpg"
        gcs_client = gcs_lib.Client.from_service_account_json(creds_path)
        bucket = gcs_client.bucket(GCS_BUCKET)
        bucket.blob(gcs_path).upload_from_string(image_bytes, content_type="image/jpeg")

        public_url = f"https://storage.googleapis.com/{GCS_BUCKET}/{quote(gcs_path, safe='/')}"

        # IMAGE_LIBRARY に利用記録
        try:
            track_usage(selected["image_id"], "Threads", text[:100],
                        selected.get("score", 0), creds_path)
        except Exception:
            pass

        print(f"  ✅ 実写画像選定: {selected['filename']} ({selected['category']})")
        return public_url

    except Exception as e:
        print(f"  ⚠ 画像自動選定スキップ ({biz_key}): {e}")
        return ""

def _col_index(header: list[str], name: str) -> int | None:
    try:
        return header.index(name) + 1
    except ValueError:
        return None


# ── 未投稿取得 ─────────────────────────────────────────────

def get_pending(ss_id: str, creds_path: str, target_date: str | None = None) -> list[dict]:
    """
    SNS_POST_STOCK から本日投稿対象を取得。
    target_date: "YYYY-MM-DD"（省略時は本日）
    戻り値: pending 行のリスト（行番号 row_index 含む）
    """
    today = target_date or _today()
    gc = _gc(creds_path)
    ss = gc.open_by_key(ss_id)
    try:
        ws = ss.worksheet("SNS_POST_STOCK")
    except gspread.WorksheetNotFound:
        return []

    rows = ws.get_all_records()
    pending = []
    for i, row in enumerate(rows, start=2):  # 行1はヘッダー
        platform  = str(row.get("platform", "") or "")
        status    = str(row.get("status",   "") or "")
        biz_name  = str(row.get("business_name", "") or "")
        sched     = str(row.get("scheduled_date", "") or "").strip()

        if platform not in _THREADS_PLATFORMS:
            continue
        if status != PENDING_STATUS:
            continue
        if _NAME_TO_KEY.get(biz_name) is None:
            continue
        # scheduled_date が未来ならスキップ（空は今日扱い）
        if sched and sched > today:
            continue

        text = str(row.get("current_text", "") or row.get("original_text", "") or "").strip()
        pending.append({
            "row_index":    i,
            "business_name": biz_name,
            "biz_key":      _NAME_TO_KEY[biz_name],
            "text":         text,
            "image_url":    _extract_image_url(row),
            "scheduled_date": sched,
            "post_no":      str(row.get("post_no", "") or ""),
        })

    return pending


# ── メイン自動投稿 ─────────────────────────────────────────

def run(
    ss_id: str,
    creds_path: str,
    dry_run: bool = True,
    max_per_biz: int = 1,
    target_date: str | None = None,
) -> dict:
    """
    自動投稿メイン関数。

    dry_run=True  : 投稿せず pending 一覧を返す（デフォルト・安全側）
    dry_run=False : 実際に Threads へ投稿し status を更新
    max_per_biz   : 1事業あたり最大投稿件数（デフォルト1 → スパム防止）
    target_date   : "YYYY-MM-DD"（省略時は本日）
    """
    from core.threads_api import publish_text, publish_image, resolve_biz

    pending = get_pending(ss_id, creds_path, target_date)

    if not pending:
        return {"ok": True, "dry_run": dry_run, "posted": 0,
                "pending": 0, "message": "投稿対象なし（SNS_POST_STOCK に未投稿行がありません）"}

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "pending_count": len(pending),
            "pending": [
                {
                    "business":      p["business_name"],
                    "biz_key":       p["biz_key"],
                    "text_preview":  p["text"][:60] + ("…" if len(p["text"]) > 60 else ""),
                    "has_image":     bool(p["image_url"]),
                    "scheduled_date": p["scheduled_date"] or "（即日）",
                }
                for p in pending
            ],
            "note": "実投稿するには dry_run=false を body に指定してください",
        }

    # ── 本番投稿 ──
    gc = _gc(creds_path)
    ss = gc.open_by_key(ss_id)
    ws = ss.worksheet("SNS_POST_STOCK")
    header = ws.row_values(1)

    def col(name: str) -> int | None:
        return _col_index(header, name)

    posted_per_biz: dict[str, int] = {}
    results = []

    for p in pending:
        bk       = p["biz_key"]
        biz_name = p["business_name"]

        # 1事業あたり上限チェック
        if posted_per_biz.get(bk, 0) >= max_per_biz:
            results.append({
                "business": biz_name, "skipped": True,
                "reason": f"1回あたり {max_per_biz} 件制限達成済み",
            })
            continue

        # 事業キー検証（ALLOWED_BIZ チェック含む）
        valid_key, err = resolve_biz(bk)
        if err:
            results.append({"business": biz_name, "ok": False, "error": err})
            continue

        text = p["text"]
        if not text:
            results.append({"business": biz_name, "ok": False, "error": "投稿テキストが空"})
            continue

        # 画像 URL 解決（明示指定 → Drive 自動選定 → テキストのみ の優先順）
        image_url = p["image_url"]
        auto_selected = False
        if not image_url:
            print(f"  [画像自動選定] {biz_name}...")
            image_url = _resolve_image_for_threads(bk, text, creds_path)
            auto_selected = bool(image_url)

        # 投稿実行
        if image_url:
            res = publish_image(ss_id, creds_path, valid_key, text, image_url)
        else:
            res = publish_text(ss_id, creds_path, valid_key, text)

        # SNS_POST_STOCK 書き戻し（成功時のみ）
        if res.get("ok"):
            ri = p["row_index"]
            if col("status"):
                ws.update_cell(ri, col("status"), DONE_STATUS)
            if col("posted_date"):
                ws.update_cell(ri, col("posted_date"), _today())
            permalink = res.get("permalink", "")
            if permalink and col("posted_url"):
                ws.update_cell(ri, col("posted_url"), permalink)
            posted_per_biz[bk] = posted_per_biz.get(bk, 0) + 1

        results.append({
            "business":      biz_name,
            "ok":            res.get("ok", False),
            "media_id":      res.get("media_id", ""),
            "permalink":     res.get("permalink", ""),
            "had_image":     bool(image_url),
            "auto_selected": auto_selected,
            "error":         res.get("error", ""),
        })

    posted  = sum(1 for r in results if r.get("ok"))
    skipped = sum(1 for r in results if r.get("skipped"))
    failed  = sum(1 for r in results if not r.get("ok") and not r.get("skipped"))

    return {
        "ok": True, "dry_run": False,
        "posted": posted, "skipped": skipped, "failed": failed,
        "results": results,
    }


def get_status(ss_id: str, creds_path: str) -> dict:
    """今日の投稿予定と投稿済みの状況を返す（確認用）"""
    pending = get_pending(ss_id, creds_path)
    today   = _today()

    gc = _gc(creds_path)
    ss = gc.open_by_key(ss_id)
    try:
        ws = ss.worksheet("SNS_POST_STOCK")
    except gspread.WorksheetNotFound:
        return {"ok": True, "pending": 0, "done_today": 0, "pending_list": []}

    rows      = ws.get_all_records()
    done_today = sum(
        1 for r in rows
        if str(r.get("platform", "")) in _THREADS_PLATFORMS
        and str(r.get("status", "")) == DONE_STATUS
        and str(r.get("posted_date", "")) == today
    )

    return {
        "ok": True,
        "date": today,
        "pending": len(pending),
        "done_today": done_today,
        "pending_list": [
            {
                "business":       p["business_name"],
                "text_preview":   p["text"][:50],
                "has_image":      bool(p["image_url"]),
                "scheduled_date": p["scheduled_date"] or "（即日）",
            }
            for p in pending
        ],
    }
