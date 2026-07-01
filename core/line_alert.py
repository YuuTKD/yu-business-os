"""
Threads 自動投稿 LINE アラートシステム
--------------------------------------
alert_type  : success / post_failed / image_url_error / username_mismatch /
              token_expired / no_candidate / no_image / low_quality /
              duplicate_detected / cloud_run_error / scheduler_failed / sheet_write_failed
severity    : INFO / WARNING / ERROR / CRITICAL

動作モード:
  dry_run=True  : THREADS_ALERT_LOG 記録のみ。LINE 未送信。
  dry_run=False : CRITICAL/ERROR のみ OWNER_LINE チャンネルへ送信。INFO/WARNING は送信しない。
  環境変数 ALERT_DRY_RUN=true でも強制 dry_run。

LINE token は環境変数から取得。ソースに書かない。
通知失敗でも投稿フローは継続。
"""

import os
import datetime
from datetime import timezone, timedelta

JST = timezone(timedelta(hours=9))

_OWNER_LINE_TOKEN_ENV = "LINE_OWNER_TOKEN"

_ALERT_TYPE_MAP: dict[str, dict] = {
    "success":            {"severity": "INFO",     "emoji": "✅", "title": "Threads投稿成功"},
    "post_failed":        {"severity": "ERROR",    "emoji": "❌", "title": "Threads投稿失敗"},
    "image_url_error":    {"severity": "WARNING",  "emoji": "⚠️", "title": "画像URLエラー"},
    "username_mismatch":  {"severity": "CRITICAL", "emoji": "🚨", "title": "username不一致 - 即確認"},
    "token_expired":      {"severity": "ERROR",    "emoji": "🔑", "title": "Threads token期限切れ"},
    "no_candidate":       {"severity": "WARNING",  "emoji": "📭", "title": "投稿候補なし"},
    "no_image":           {"severity": "WARNING",  "emoji": "🖼️",  "title": "画像候補なし"},
    "low_quality":        {"severity": "WARNING",  "emoji": "⚠️", "title": "低品質候補のみ"},
    "duplicate_detected": {"severity": "WARNING",  "emoji": "⚠️", "title": "重複投稿検出"},
    "cloud_run_error":    {"severity": "CRITICAL", "emoji": "🔥", "title": "Cloud Runエラー"},
    "scheduler_failed":   {"severity": "ERROR",    "emoji": "❌", "title": "Scheduler実行失敗"},
    "sheet_write_failed": {"severity": "ERROR",    "emoji": "❌", "title": "シート更新失敗"},
}

_ALERT_LOG_SHEET = "THREADS_ALERT_LOG"
_ALERT_LOG_HEADERS = [
    "alert_type", "business_key", "severity", "message",
    "error_detail", "post_candidate_id", "image_id", "post_url",
    "sent_at", "status", "resolved_at",
]


# ── メッセージ組み立て ─────────────────────────────────

def _build_message(alert_type: str, biz_key: str, **kwargs) -> str:
    meta = _ALERT_TYPE_MAP.get(alert_type, {"emoji": "ℹ️", "title": alert_type})
    emoji = meta["emoji"]
    title = meta["title"]
    biz_name = kwargs.get("business_name", biz_key)

    if alert_type == "success":
        img_info = kwargs.get("image_filename", "")
        cat = kwargs.get("category", "")
        img_part = f"{img_info}（{cat}）" if img_info else "なし（テキストのみ）"
        return (
            f"【{emoji} {title}】\n"
            f"事業：{biz_name}\n"
            f"投稿URL：{kwargs.get('permalink', '—')}\n"
            f"画像：{img_part}\n"
            f"文字数：{kwargs.get('text_length', '—')}字\n"
            f"次回インサイト取得：翌日以降"
        )

    if alert_type == "post_failed":
        return (
            f"【{emoji} {title}】\n"
            f"事業：{biz_name}\n"
            f"原因：{kwargs.get('error_message', '不明')}\n"
            f"投稿候補ID：{kwargs.get('post_candidate_id', '—')}\n"
            f"対応：SNS_POST_STOCKの当該行を確認してください\n"
            f"再実行可否：手動で dry_run=false を再実行"
        )

    if alert_type == "image_url_error":
        return (
            f"【{emoji} {title}】\n"
            f"事業：{biz_name}\n"
            f"画像ID：{kwargs.get('image_id', '—')}\n"
            f"URL：{kwargs.get('image_url', '—')}\n"
            f"HTTP状態：{kwargs.get('http_status', '—')}\n"
            f"対応：IMAGE_LIBRARYの当該行を確認してください"
        )

    if alert_type == "username_mismatch":
        return (
            f"【{emoji} {title}】\n"
            f"事業：{biz_name}\n"
            f"期待username：{kwargs.get('expected', '—')}\n"
            f"実際のusername：{kwargs.get('actual', '—')}\n"
            f"対応：投稿を中止しました。Threads OAuth を再確認してください。"
        )

    if alert_type == "token_expired":
        return (
            f"【{emoji} {title}】\n"
            f"事業：{biz_name}\n"
            f"有効期限：{kwargs.get('expires_at', '—')}\n"
            f"対応：/threads-oauth/{biz_key} でトークン更新してください"
        )

    if alert_type == "no_candidate":
        return (
            f"【{emoji} {title}】\n"
            f"事業：{biz_name}\n"
            f"SNS_POST_STOCKに「未投稿」の Threads 行がありません。\n"
            f"対応：新しい投稿候補をSNS_POST_STOCKに追加してください。"
        )

    if alert_type == "no_image":
        return (
            f"【{emoji} {title} - テキスト投稿に移行しません】\n"
            f"事業：{biz_name}\n"
            f"IMAGE_LIBRARYに使用可能な画像がありません。\n"
            f"対応：Drive フォルダに写真を追加して /scan-drive-images を実行"
        )

    # 汎用フォールバック
    error_detail = kwargs.get("error_detail") or kwargs.get("error_message", "")
    return f"【{emoji} {title}】\n事業：{biz_name}\n{error_detail}".strip()


# ── ログ書き込み ──────────────────────────────────────

def _write_alert_log(
    alert_type: str, biz_key: str, severity: str, message: str,
    error_detail: str, post_candidate_id: str, image_id: str, post_url: str,
    sent_at: str, status: str, ss_id: str, creds_path: str,
) -> dict:
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds = Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        gc = gspread.authorize(creds)
        ss = gc.open_by_key(ss_id)

        try:
            ws = ss.worksheet(_ALERT_LOG_SHEET)
        except gspread.WorksheetNotFound:
            ws = ss.add_worksheet(title=_ALERT_LOG_SHEET, rows=1000, cols=len(_ALERT_LOG_HEADERS))
            ws.update(range_name="A1", values=[_ALERT_LOG_HEADERS])

        existing_header = ws.row_values(1)
        if not existing_header or existing_header[0] != "alert_type":
            ws.update(range_name="A1", values=[_ALERT_LOG_HEADERS])

        row_data = [
            alert_type, biz_key, severity, message,
            error_detail, post_candidate_id, image_id, post_url,
            sent_at, status, "",
        ]
        ws.append_row(row_data, value_input_option="RAW")
        all_rows = ws.get_all_values()
        return {"ok": True, "row": len(all_rows)}
    except Exception as e:
        print(f"  ⚠ THREADS_ALERT_LOG 書き込み失敗: {e}")
        return {"ok": False, "error": str(e)}


def _update_log_status(row: int, status: str, ss_id: str, creds_path: str) -> None:
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds = Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        gc = gspread.authorize(creds)
        ws = gc.open_by_key(ss_id).worksheet(_ALERT_LOG_SHEET)
        header = ws.row_values(1)
        try:
            col = header.index("status") + 1
            ws.update_cell(row, col, status)
        except ValueError:
            pass
    except Exception as e:
        print(f"  ⚠ THREADS_ALERT_LOG status 更新失敗: {e}")


# ── LINE 送信 ─────────────────────────────────────────

def _send_line_owner(message: str) -> bool:
    try:
        import requests
        token = os.getenv(_OWNER_LINE_TOKEN_ENV, "")
        if not token:
            print(f"  ⚠ {_OWNER_LINE_TOKEN_ENV} 未設定、LINE送信スキップ")
            return False

        resp = requests.post(
            "https://api.line.me/v2/bot/message/broadcast",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"messages": [{"type": "text", "text": message}]},
            timeout=10,
        )
        if resp.status_code == 200:
            print("  ✅ LINE OWNER 送信完了")
            return True
        print(f"  ⚠ LINE 送信失敗: {resp.status_code}")
        return False
    except Exception as e:
        print(f"  ⚠ LINE 送信例外: {e}")
        return False


# ── メイン公開関数 ────────────────────────────────────

def send_threads_alert(
    alert_type: str,
    biz_key: str,
    dry_run: bool = True,
    ss_id: str = None,
    creds_path: str = None,
    **kwargs,
) -> dict:
    """
    Threads 投稿アラートを LINE 送信 + THREADS_ALERT_LOG 記録。

    dry_run=True  : THREADS_ALERT_LOG 記録のみ、LINE 未送信
    dry_run=False : CRITICAL/ERROR のみ OWNER チャンネルへ LINE 送信
    """
    if creds_path is None:
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "/app/credentials.json")
    if ss_id is None:
        ss_id = os.getenv("SPREADSHEET_ID") or os.getenv("GOOGLE_SPREADSHEET_ID", "")

    env_dry_run = os.getenv("ALERT_DRY_RUN", "").lower() in ("1", "true", "yes")
    effective_dry_run = dry_run or env_dry_run

    meta = _ALERT_TYPE_MAP.get(alert_type, {"severity": "INFO", "emoji": "ℹ️", "title": alert_type})
    severity = meta["severity"]
    message = _build_message(alert_type, biz_key, **kwargs)
    now = datetime.datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")

    log_status = "dry_run" if effective_dry_run else "pending"
    log_result = _write_alert_log(
        alert_type=alert_type,
        biz_key=biz_key,
        severity=severity,
        message=message,
        error_detail=str(kwargs.get("error_detail", "")),
        post_candidate_id=str(kwargs.get("post_candidate_id", "")),
        image_id=str(kwargs.get("image_id", "")),
        post_url=str(kwargs.get("permalink") or kwargs.get("post_url", "")),
        sent_at=now,
        status=log_status,
        ss_id=ss_id,
        creds_path=creds_path,
    )

    if effective_dry_run:
        print(f"  [LINE_ALERT DRY_RUN] {severity} | {biz_key} | {alert_type}")
        print(f"  通知文:\n{message}")
        return {"ok": True, "dry_run": True, "severity": severity, "alert_type": alert_type, "message": message}

    # CRITICAL/ERROR のみ OWNER チャンネルへ送信（INFO/WARNING は送信しない）
    sent = False
    if severity in ("CRITICAL", "ERROR"):
        sent = _send_line_owner(message)

    if log_result.get("row"):
        _update_log_status(
            row=log_result["row"],
            status="sent" if sent else ("skipped" if severity not in ("CRITICAL", "ERROR") else "failed"),
            ss_id=ss_id,
            creds_path=creds_path,
        )

    return {
        "ok": True,
        "dry_run": False,
        "severity": severity,
        "alert_type": alert_type,
        "line_sent": sent,
        "message": message,
    }
