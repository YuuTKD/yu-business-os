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

安全装置（基本）:
  - dry_run=True がデフォルト（誤投稿防止）
  - 1事業あたり max_per_biz=1 件/回（スパム防止）
  - business_name が ALLOWED_BIZ 以外は自動スキップ
  - 投稿失敗時は status を変更せず次の行へ

安全装置（完全自動用 run_full_auto）:
  - AUTO_POST_MASTER_SWITCH=false 環境変数でグローバル停止
  - auto_post_enabled=False の事業をスキップ
  - 投稿時間帯制限（posting_window）
  - 1日投稿上限（daily_post_limit）
  - 連続エラー自動停止（consecutive_error_threshold）
  - 品質スコアフィルター（min_quality_score >= 3）
  - 重複投稿防止（Jaccard ≥ 0.75 で30日以内の類似投稿を除外）
  - 画像URL HTTP疎通確認（GCS URLのみ）
  - テキストのみへのフォールバック禁止（fallback_to_text_allowed=False）
  - token期限7日前警告

Cloud Scheduler 推奨設定:
  毎日 11:00 JST → POST /threads-auto-post-full  (dry_run=false は body で明示指定)
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
    GCS 公開 HTTPS URL を返す。

    gcs_public_url が IMAGE_LIBRARY に保存済みなら再アップロードをスキップする。
    画像なし・アップロード失敗時は "" を返す（テキスト投稿は呼び出し元で判断）。
    """
    try:
        from core.image_manager import select_real_image, fetch_drive_image_bytes, track_usage, save_gcs_url
        from google.cloud import storage as gcs_lib

        lib_key = _BIZ_TO_LIB.get(biz_key, biz_key.upper())
        selected = select_real_image(text, lib_key, platform="threads", creds_path=creds_path)
        if not selected:
            print(f"  ℹ {biz_key}: 実写画像なし → テキスト投稿")
            return ""

        # ── GCS URL キャッシュ確認（再アップロード不要なら即返す） ──
        cached_url = selected.get("gcs_public_url", "")
        if cached_url and cached_url.startswith("https://storage.googleapis.com/"):
            print(f"  ✅ GCS キャッシュ利用: {selected['filename']} ({selected['category']})")
            try:
                track_usage(selected["image_id"], "Threads", text[:100],
                            selected.get("score", 0), creds_path)
            except Exception:
                pass
            return cached_url

        # ── Drive DL → PIL変換 → GCS アップロード ──
        image_bytes = fetch_drive_image_bytes(selected["drive_file_id"], creds_path)
        if not image_bytes:
            print(f"  ⚠ {biz_key}: Drive DL 失敗 → テキスト投稿")
            return ""

        try:
            from PIL import Image as PILImage
            img = PILImage.open(io.BytesIO(image_bytes)).convert("RGB")
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=90)
            image_bytes = out.getvalue()
        except Exception:
            pass

        today = _today()
        fname_safe = re.sub(r"[^\w\-.]", "_", selected["filename"][:20])
        gcs_path = f"content/threads/{biz_key}/{today}_{fname_safe}.jpg"
        gcs_client = gcs_lib.Client.from_service_account_json(creds_path)
        bucket = gcs_client.bucket(GCS_BUCKET)
        bucket.blob(gcs_path).upload_from_string(image_bytes, content_type="image/jpeg")

        public_url = f"https://storage.googleapis.com/{GCS_BUCKET}/{quote(gcs_path, safe='/')}"

        # IMAGE_LIBRARY に GCS URL 保存（次回再利用のため）
        try:
            save_gcs_url(selected["image_id"], public_url, gcs_path, creds_path=creds_path)
        except Exception:
            pass

        # 利用記録
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


# ── 安全装置ユーティリティ ────────────────────────────────

def validate_image_url(url: str, timeout: int = 8) -> dict:
    """
    GCS 公開URL等の HTTP 疎通・Content-Type・サイズを確認する。
    非GCS URL（Drive等）は検証スキップ。
    """
    if not url or not url.startswith("https://"):
        return {"ok": False, "reason": "URLが空またはHTTPS非対応"}
    try:
        import requests as _req
        resp = _req.head(url, timeout=timeout, allow_redirects=True)
        http_status = resp.status_code
        content_type = resp.headers.get("Content-Type", "")
        content_length = int(resp.headers.get("Content-Length", 0) or 0)
        size_mb = round(content_length / 1024 / 1024, 2)

        if http_status != 200:
            return {"ok": False, "http_status": http_status, "reason": f"HTTP {http_status}"}
        if "image/jpeg" not in content_type and "image/png" not in content_type:
            return {
                "ok": False, "http_status": http_status, "content_type": content_type,
                "reason": f"Content-Type不正: {content_type}",
            }
        if size_mb > 3:
            return {
                "ok": False, "http_status": http_status, "content_type": content_type,
                "size_mb": size_mb, "reason": f"ファイルサイズ超過: {size_mb}MB > 3MB",
            }
        return {"ok": True, "http_status": http_status, "content_type": content_type, "size_mb": size_mb}
    except Exception as e:
        return {"ok": False, "reason": f"検証例外: {e}"}


def check_duplicate_post(
    text: str, biz_name: str, ss_id: str, creds_path: str,
    lookback_days: int = 30,
) -> dict:
    """
    SNS_POST_STOCK 投稿済み行と Jaccard 類似度（文字バイグラム）で比較し重複を検出する。
    Jaccard ≥ 0.75 かつ 30 日以内の投稿を重複とみなす。
    """
    try:
        gc = _gc(creds_path)
        ws = gc.open_by_key(ss_id).worksheet("SNS_POST_STOCK")
        rows = ws.get_all_records()
        cutoff_str = (datetime.now(JST) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        text_head = text[:80].strip()

        def _bigrams(s: str) -> set:
            return {s[i:i + 2] for i in range(len(s) - 1)}

        bg_text = _bigrams(text_head)

        for row in rows:
            if str(row.get("business_name", "")) != biz_name:
                continue
            if str(row.get("status", "")) != DONE_STATUS:
                continue
            posted_date = str(row.get("posted_date", "") or "")
            if posted_date and posted_date < cutoff_str:
                continue
            existing = str(row.get("current_text", "") or row.get("original_text", "") or "").strip()
            bg_existing = _bigrams(existing[:80])
            if not bg_text or not bg_existing:
                continue
            union = bg_text | bg_existing
            if not union:
                continue
            jaccard = len(bg_text & bg_existing) / len(union)
            if jaccard >= 0.75:
                return {
                    "is_duplicate": True,
                    "jaccard": round(jaccard, 2),
                    "existing_posted_date": posted_date,
                    "existing_preview": existing[:50],
                }
        return {"is_duplicate": False}
    except Exception as e:
        print(f"  ⚠ 重複チェック失敗（スキップ）: {e}")
        return {"is_duplicate": False, "check_error": str(e)}


def count_consecutive_errors(biz_key: str, ss_id: str, creds_path: str) -> int:
    """
    THREADS_ALERT_LOG を新しい順に走査し、最初の success が現れるまでの
    post_failed 件数を返す（連続エラーカウント）。
    シートが存在しない場合は 0 を返す。
    """
    try:
        gc = _gc(creds_path)
        try:
            ws = gc.open_by_key(ss_id).worksheet("THREADS_ALERT_LOG")
        except gspread.WorksheetNotFound:
            return 0
        rows = ws.get_all_records()
        biz_rows = [
            r for r in rows
            if str(r.get("business_key", "")) == biz_key
            and str(r.get("alert_type", "")) in ("post_failed", "success")
        ]
        biz_rows.reverse()  # 最新から遡る
        count = 0
        for row in biz_rows:
            if str(row.get("alert_type", "")) == "post_failed":
                count += 1
            else:
                break
        return count
    except Exception as e:
        print(f"  ⚠ エラーカウント失敗: {e}")
        return 0


def count_today_posts(biz_name: str, ss_id: str, creds_path: str) -> int:
    """SNS_POST_STOCK から今日の投稿済み件数を返す"""
    try:
        today = _today()
        gc = _gc(creds_path)
        ws = gc.open_by_key(ss_id).worksheet("SNS_POST_STOCK")
        rows = ws.get_all_records()
        return sum(
            1 for r in rows
            if str(r.get("business_name", "")) == biz_name
            and str(r.get("platform", "")) in _THREADS_PLATFORMS
            and str(r.get("status", "")) == DONE_STATUS
            and str(r.get("posted_date", "")) == today
        )
    except Exception as e:
        print(f"  ⚠ 今日の投稿数取得失敗: {e}")
        return 0


def is_in_posting_window(cfg: dict) -> bool:
    """現在 JST 時刻が posting_window_start〜end の範囲内か"""
    try:
        now = datetime.now(JST)
        start_h, start_m = map(int, cfg.get("posting_window_start", "00:00").split(":"))
        end_h, end_m = map(int, cfg.get("posting_window_end", "23:59").split(":"))
        start_dt = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
        end_dt   = now.replace(hour=end_h,   minute=end_m,   second=0, microsecond=0)
        return start_dt <= now <= end_dt
    except Exception:
        return True  # エラー時は通過（安全方向）


def check_token_expiry(acc: dict, warn_days: int = 7) -> dict:
    """
    THREADS_ACCOUNT_CONFIG の expires_at を確認し、
    warn_days 以内に期限切れなら警告を返す。
    """
    expires_at = str(acc.get("expires_at", "") or "")
    if not expires_at:
        return {"ok": True, "status": "unknown"}
    try:
        exp = datetime.strptime(expires_at, "%Y-%m-%d").replace(tzinfo=JST)
        now = datetime.now(JST)
        days_left = (exp.date() - now.date()).days
        if days_left < 0:
            return {"ok": False, "status": "expired", "expires_at": expires_at, "days_left": days_left}
        if days_left <= warn_days:
            return {"ok": True, "status": "expiring_soon", "expires_at": expires_at, "days_left": days_left}
        return {"ok": True, "status": "valid", "expires_at": expires_at, "days_left": days_left}
    except ValueError:
        return {"ok": True, "status": "parse_error", "expires_at": expires_at}


# ── 完全自動投稿エンジン ──────────────────────────────────

def run_full_auto(
    ss_id: str,
    creds_path: str,
    biz_keys: list[str] | None = None,
    dry_run: bool = True,
    skip_window_check: bool = False,
) -> dict:
    """
    完全自動投稿エンジン（全安全チェック付き）。

    biz_keys=None  → AUTO_POST_CONFIG で auto_post_enabled=True の事業のみ
    biz_keys 指定  → 指定事業（auto_post_enabled チェックをバイパス）
    dry_run=True   → 全チェック実行、投稿はしない（デフォルト）
    skip_window_check=True → 投稿時間帯チェックをスキップ（DRY_RUN テスト用）

    安全装置チェック順:
      ① グローバルOFFスイッチ（AUTO_POST_MASTER_SWITCH env）
      ② 事業ステータス（offline はスキップ）
      ③ 投稿時間帯
      ④ 今日の投稿数上限
      ⑤ 連続エラー停止
      ⑥ token 期限確認
      ⑦ 投稿候補取得（get_pending）
      ⑧ 品質スコアフィルター（score_post ≥ min_quality_score）
      ⑨ 重複チェック（Jaccard ≥ 0.75 で除外）
      ⑩ 画像取得 + URL 検証
      ⑪ username/business_key 検証
      ⑫ 投稿実行（dry_run=False 時のみ）
    """
    from core.threads_api import publish_text, publish_image, resolve_biz, get_account
    from core.line_alert import send_threads_alert as _alert_fn
    from core.post_quality import score_post
    from configs.auto_post_settings import AUTO_POST_CONFIG

    # ── ① グローバルOFFスイッチ ──
    master = os.getenv("AUTO_POST_MASTER_SWITCH", "true").lower()
    if master in ("false", "0", "off"):
        return {
            "ok": True, "dry_run": dry_run,
            "stopped": True,
            "reason": "AUTO_POST_MASTER_SWITCH=false（グローバルOFF）",
        }

    # ── 対象事業決定 ──
    if biz_keys is None:
        biz_keys = [k for k, v in AUTO_POST_CONFIG.items() if v.get("auto_post_enabled")]
    if not biz_keys:
        return {
            "ok": True, "dry_run": dry_run, "posted": 0,
            "message": "自動投稿対象事業なし（全て auto_post_enabled=False）",
            "hint": "configs/auto_post_settings.py で auto_post_enabled=True に変更後、Scheduler ON条件を確認してください",
        }

    # 全体の未投稿候補を一度に取得（シート読み込みを最小化）
    all_pending = get_pending(ss_id, creds_path)

    results = []

    for bk in biz_keys:
        cfg = AUTO_POST_CONFIG.get(bk, {})
        biz_name = cfg.get("business_name", bk)

        def _do_alert(alert_type: str, **kwargs):
            try:
                _alert_fn(alert_type, bk, dry_run=dry_run, ss_id=ss_id, creds_path=creds_path,
                           business_name=biz_name, **kwargs)
            except Exception:
                pass

        result: dict = {
            "biz_key": bk,
            "business_name": biz_name,
            "dry_run": dry_run,
            "checks": {},
            "ok": False,
        }

        # ── ② 事業設定・ステータス確認 ──
        if not cfg:
            result.update({"skipped": True, "reason": "configs/auto_post_settings.py に設定なし"})
            results.append(result); continue

        if cfg.get("status") == "offline":
            result.update({"skipped": True, "reason": f"status=offline: {cfg.get('notes', '')}"})
            results.append(result); continue

        # ── ③ 投稿時間帯チェック ──
        in_window = is_in_posting_window(cfg)
        result["checks"]["posting_window"] = (
            f"✅ {cfg.get('posting_window_start')}〜{cfg.get('posting_window_end')}"
            if in_window else
            f"⚠️ 時間帯外（現在: {datetime.now(JST).strftime('%H:%M')} JST）"
        )
        if not skip_window_check and not dry_run and not in_window:
            result.update({"skipped": True, "reason": f"投稿時間帯外（{cfg.get('posting_window_start')}〜{cfg.get('posting_window_end')} JST）"})
            results.append(result); continue

        # ── ④ 今日の投稿数チェック ──
        today_count = count_today_posts(biz_name, ss_id, creds_path)
        limit = cfg.get("daily_post_limit", 1)
        result["checks"]["today_posts"] = f"{today_count}/{limit}件"
        if today_count >= limit:
            result.update({"skipped": True, "reason": f"本日投稿上限達成（{today_count}/{limit}件）"})
            results.append(result); continue

        # ── ⑤ 連続エラーチェック ──
        threshold = cfg.get("consecutive_error_threshold", 3)
        consec = count_consecutive_errors(bk, ss_id, creds_path)
        result["checks"]["consecutive_errors"] = f"{consec}回（閾値: {threshold}）"
        if cfg.get("stop_on_error") and consec >= threshold:
            result.update({
                "stopped": True,
                "reason": f"連続エラー {consec}回（閾値: {threshold}）→ 自動停止。THREADS_ALERT_LOGを確認してください。",
            })
            _do_alert("cloud_run_error",
                      error_detail=f"連続エラー{consec}回で自動停止。手動でエラー原因を解消後、再開してください。")
            results.append(result); continue

        # ── ⑥ token 期限確認 ──
        try:
            acc = get_account(ss_id, creds_path, bk)
            token_check = check_token_expiry(acc)
            result["checks"]["token"] = f"{'✅' if token_check['ok'] else '❌'} {token_check.get('status', '')} (残{token_check.get('days_left', '?')}日)"
            if not token_check["ok"]:
                result.update({"skipped": True, "reason": f"token期限切れ（{token_check.get('expires_at')}）"})
                _do_alert("token_expired", expires_at=token_check.get("expires_at", "不明"))
                results.append(result); continue
            if token_check.get("status") == "expiring_soon":
                _do_alert("token_expired",
                          expires_at=token_check.get("expires_at", ""),
                          error_detail=f"あと{token_check.get('days_left', '?')}日で期限切れ。リフレッシュ推奨。")
        except Exception as e:
            result["checks"]["token"] = f"⚠️ 取得失敗: {e}"

        # ── ⑦ 投稿候補取得 ──
        biz_pending = [p for p in all_pending if p["biz_key"] == bk]
        result["checks"]["pending_count"] = f"{len(biz_pending)}件"
        if not biz_pending:
            result.update({"skipped": True, "reason": "投稿候補なし（SNS_POST_STOCKに未投稿行がありません）"})
            _do_alert("no_candidate")
            results.append(result); continue

        # ── ⑧ 品質スコアフィルター ──
        min_score = cfg.get("min_quality_score", 3)
        scored = []
        for p in biz_pending:
            sq = score_post(p["text"], bk)
            scored.append({**p, "quality_score": sq["quality_score"],
                           "quality_passed": sq["passed"], "quality_failed": sq["failed"]})
        valid = [p for p in scored if p["quality_score"] >= min_score]
        result["quality_breakdown"] = [
            {"text_preview": p["text"][:50], "score": p["quality_score"],
             "passed": p["quality_passed"], "failed": p["quality_failed"]}
            for p in scored
        ]
        result["checks"]["quality_filter"] = f"{len(valid)}/{len(scored)}件 (スコア≥{min_score})"
        if not valid:
            max_score = max(p["quality_score"] for p in scored) if scored else 0
            result.update({
                "skipped": True,
                "reason": f"品質スコア{min_score}以上の候補なし（最高スコア: {max_score}）",
            })
            _do_alert("low_quality",
                      error_detail=f"最高スコア: {max_score}（基準: ≥{min_score}）。投稿候補の品質を改善してください。")
            results.append(result); continue

        # ── ⑨ 重複チェック ──
        non_dup = []
        for p in valid:
            dup = check_duplicate_post(p["text"], biz_name, ss_id, creds_path)
            if not dup.get("is_duplicate"):
                non_dup.append({**p, "dup_check": dup})
            else:
                print(f"  ⚠ 重複スキップ: {biz_name} | Jaccard={dup.get('jaccard')} | {dup.get('existing_preview', '')[:30]}")
        result["checks"]["dup_filter"] = f"{len(non_dup)}/{len(valid)}件（重複除外後）"
        if not non_dup:
            result.update({"skipped": True, "reason": "全有効候補が重複投稿判定（直近30日以内）"})
            _do_alert("duplicate_detected",
                      error_detail="全候補が直近30日の投稿と類似。新しい投稿候補をSNS_POST_STOCKに追加してください。")
            results.append(result); continue

        # 最上位候補を選定
        selected = sorted(non_dup, key=lambda p: p["quality_score"], reverse=True)[0]
        result["selected"] = {
            "text_preview": selected["text"][:80],
            "quality_score": selected["quality_score"],
            "row_index": selected["row_index"],
            "post_no": selected["post_no"],
            "scheduled_date": selected["scheduled_date"] or "（即日）",
        }

        # ── ⑩ 画像取得 + URL 検証 ──
        requires_image = cfg.get("requires_image", True)
        fallback_ok = cfg.get("fallback_to_text_allowed", False)
        image_url = selected["image_url"]
        auto_selected = False

        if not image_url:
            print(f"  [画像自動選定] {biz_name}...")
            image_url = _resolve_image_for_threads(bk, selected["text"], creds_path)
            auto_selected = bool(image_url)

        result["checks"]["image"] = "✅ あり" if image_url else "❌ なし"
        result["image_url_preview"] = (image_url[:80] + "...") if len(image_url) > 80 else image_url

        if not image_url and requires_image and not fallback_ok:
            result.update({"skipped": True, "reason": "画像候補なし・テキストフォールバック禁止"})
            _do_alert("no_image")
            results.append(result); continue

        # GCS URL は HTTP 疎通確認
        img_validation: dict = {"ok": True, "reason": "非GCS URL（検証スキップ）"}
        if image_url and image_url.startswith("https://storage.googleapis.com/"):
            img_validation = validate_image_url(image_url)
            result["checks"]["image_url_http"] = (
                f"✅ HTTP{img_validation.get('http_status')} {img_validation.get('content_type','')} {img_validation.get('size_mb','')}MB"
                if img_validation.get("ok") else
                f"❌ {img_validation.get('reason')}"
            )
            if not img_validation.get("ok"):
                result.update({"skipped": True, "reason": f"画像URL無効: {img_validation.get('reason')}"})
                _do_alert("image_url_error",
                          image_url=image_url,
                          http_status=img_validation.get("http_status", "—"),
                          error_detail=img_validation.get("reason", ""))
                results.append(result); continue

        # ── ⑪ 事業キー検証 ──
        valid_key, err = resolve_biz(bk)
        if err:
            result.update({"ok": False, "error": err})
            _do_alert("post_failed", error_message=err)
            results.append(result); continue

        result["checks"]["biz_key"] = f"✅ {valid_key}"

        # ── DRY_RUN 終了地点 ──
        if dry_run:
            line_preview = _build_line_preview(
                bk, biz_name, selected["text"], image_url, selected["quality_score"]
            )
            result.update({
                "ok": True,
                "message": "DRY_RUN: 全チェック通過。実投稿はされません。",
                "would_post": {
                    "text": selected["text"],
                    "image_url": image_url or "なし（テキストのみ）",
                    "quality_score": selected["quality_score"],
                    "auto_selected_image": auto_selected,
                },
                "line_alert_preview": line_preview,
            })
            _do_alert("success",
                      permalink="（DRY_RUN）",
                      text_length=len(selected["text"]),
                      image_filename="" if not auto_selected else "自動選定",
                      category="")
            results.append(result)
            continue

        # ── ⑫ 本番投稿 ──
        if image_url:
            res = publish_image(ss_id, creds_path, valid_key, selected["text"], image_url)
        else:
            res = publish_text(ss_id, creds_path, valid_key, selected["text"])

        permalink = res.get("permalink", "")

        if res.get("ok"):
            try:
                gc = _gc(creds_path)
                ws = gc.open_by_key(ss_id).worksheet("SNS_POST_STOCK")
                header = ws.row_values(1)
                ri = selected["row_index"]
                c = lambda name: _col_index(header, name)  # noqa: E731
                if c("status"):    ws.update_cell(ri, c("status"), DONE_STATUS)
                if c("posted_date"): ws.update_cell(ri, c("posted_date"), _today())
                if permalink and c("posted_url"): ws.update_cell(ri, c("posted_url"), permalink)
            except Exception as e:
                _do_alert("sheet_write_failed", error_detail=str(e))

            result.update({
                "ok": True,
                "media_id":      res.get("media_id", ""),
                "permalink":     permalink,
                "had_image":     bool(image_url),
                "auto_selected": auto_selected,
            })
            _do_alert("success", permalink=permalink, text_length=len(selected["text"]))
        else:
            result.update({"ok": False, "error": res.get("error", "不明なエラー")})
            _do_alert("post_failed",
                      error_message=res.get("error", ""),
                      post_candidate_id=selected.get("post_no") or selected["row_index"])

        results.append(result)

    # ── サマリー ──
    posted   = sum(1 for r in results if r.get("ok") and not dry_run)
    dry_ok   = sum(1 for r in results if r.get("ok") and dry_run)
    skipped  = sum(1 for r in results if r.get("skipped"))
    stopped  = sum(1 for r in results if r.get("stopped"))
    failed   = sum(1 for r in results if not r.get("ok") and not r.get("skipped") and not r.get("stopped"))

    return {
        "ok":  True,
        "dry_run": dry_run,
        "summary": {
            "posted":            posted,
            "dry_run_passed":    dry_ok if dry_run else 0,
            "skipped":           skipped,
            "stopped":           stopped,
            "failed":            failed,
        },
        "results": results,
    }


def _build_line_preview(bk: str, biz_name: str, text: str, image_url: str, quality_score: int) -> str:
    """DRY_RUN 時に生成される LINE 通知文のプレビューを返す"""
    img_note = "あり" if image_url else "なし（テキストのみ）"
    return (
        f"【✅ Threads自動投稿成功（予定）】\n"
        f"事業：{biz_name}\n"
        f"品質スコア：{quality_score}/5\n"
        f"文字数：{len(text)}字\n"
        f"画像：{img_note}\n"
        f"次回インサイト取得：翌日以降"
    )


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
    from core.line_alert import send_threads_alert as _alert

    def _do_alert(alert_type: str, biz_key: str, **kwargs):
        try:
            _alert(alert_type, biz_key, dry_run=dry_run, ss_id=ss_id, creds_path=creds_path, **kwargs)
        except Exception:
            pass  # アラート失敗で投稿フローを止めない

    pending = get_pending(ss_id, creds_path, target_date)

    if not pending:
        _do_alert("no_candidate", "all", business_name="全事業（未投稿行なし）")
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
        permalink = res.get("permalink", "")
        if res.get("ok"):
            ri = p["row_index"]
            if col("status"):
                ws.update_cell(ri, col("status"), DONE_STATUS)
            if col("posted_date"):
                ws.update_cell(ri, col("posted_date"), _today())
            if permalink and col("posted_url"):
                ws.update_cell(ri, col("posted_url"), permalink)
            posted_per_biz[bk] = posted_per_biz.get(bk, 0) + 1
            _do_alert("success", bk,
                      business_name=biz_name,
                      permalink=permalink,
                      text_length=len(text))
        else:
            _do_alert("post_failed", bk,
                      business_name=biz_name,
                      error_message=res.get("error", "不明"),
                      post_candidate_id=p.get("post_no") or p["row_index"])

        results.append({
            "business":      biz_name,
            "ok":            res.get("ok", False),
            "media_id":      res.get("media_id", ""),
            "permalink":     permalink,
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
