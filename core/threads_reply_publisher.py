"""
Threads返信送信モジュール（DRY_RUN固定・App Review前完成版）

DRY_RUN=true（デフォルト）: 実際の送信は行わず、送信予定内容をログに残す。
DRY_RUN=false: App Review承認後のみ設定変更を許可。

App Review承認前に DRY_RUN=false に変更してはいけない。
"""

import os
import datetime
import requests


# App Review承認前は必ず true のまま
# 承認後に環境変数 THREADS_DRY_RUN=false を設定して本番移行
DRY_RUN = os.getenv("THREADS_DRY_RUN", "true").lower() != "false"

THREADS_API_BASE = "https://graph.threads.net/v1.0"


def publish_reply(
    reply_text: str,
    reply_to_id: str,
    threads_user_id: str = "",
    access_token: str = "",
) -> dict:
    """
    Threads投稿への返信を送信する（DRY_RUN時はログのみ）。

    戻り値:
      {"ok": True, "mode": "dry_run", "reply_text": "...", "reply_to_id": "..."}
      {"ok": True, "mode": "live",    "reply_id": "...", "reply_text": "..."}
      {"ok": False, "error": "..."}
    """
    if DRY_RUN:
        return _log_dry_run(reply_text, reply_to_id)

    # --- 本番送信（App Review承認後のみ到達） ---
    uid = threads_user_id or os.getenv("THREADS_USER_ID", "")
    token = access_token or os.getenv("THREADS_ACCESS_TOKEN", "")

    if not uid or not token:
        return {"ok": False, "error": "THREADS_USER_ID または THREADS_ACCESS_TOKEN が未設定"}

    return _send_reply(reply_text, reply_to_id, uid, token)


def _log_dry_run(reply_text: str, reply_to_id: str) -> dict:
    """DRY_RUN: 実際には送信せずログのみ記録"""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[DRY_RUN] {now} | reply_to_id={reply_to_id}")
    print(f"[DRY_RUN] reply_text:\n{reply_text}")
    return {
        "ok": True,
        "mode": "dry_run",
        "reply_to_id": reply_to_id,
        "reply_text": reply_text,
        "note": "DRY_RUN=true のため実際には送信していません。App Review承認後に THREADS_DRY_RUN=false を設定してください。",
    }


def _send_reply(reply_text: str, reply_to_id: str, uid: str, token: str) -> dict:
    """
    実際のThreads返信送信（2ステップ）。
    Step1: コンテナ作成 → Step2: 公開
    App Review承認 + threads_manage_replies 権限取得後のみ動作。
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Step1: 返信コンテナ作成
    container_resp = requests.post(
        f"{THREADS_API_BASE}/{uid}/threads",
        headers=headers,
        json={
            "media_type": "TEXT",
            "text": reply_text,
            "reply_to_id": reply_to_id,
        },
        timeout=15,
    )
    if not container_resp.ok:
        return {
            "ok": False,
            "error": f"コンテナ作成失敗: {container_resp.status_code} {container_resp.text[:200]}",
        }

    container_id = container_resp.json().get("id", "")
    if not container_id:
        return {"ok": False, "error": "コンテナIDが取得できませんでした"}

    # Step2: 30秒待機後に公開（メディア処理のため）
    import time
    time.sleep(30)

    publish_resp = requests.post(
        f"{THREADS_API_BASE}/{uid}/threads_publish",
        headers=headers,
        json={"creation_id": container_id},
        timeout=15,
    )
    if not publish_resp.ok:
        return {
            "ok": False,
            "error": f"公開失敗: {publish_resp.status_code} {publish_resp.text[:200]}",
        }

    reply_id = publish_resp.json().get("id", "")
    return {
        "ok": True,
        "mode": "live",
        "reply_id": reply_id,
        "reply_to_id": reply_to_id,
        "reply_text": reply_text,
    }


def get_dry_run_status() -> dict:
    """現在のDRY_RUNステータスを返す"""
    return {
        "dry_run": DRY_RUN,
        "env_value": os.getenv("THREADS_DRY_RUN", "true"),
        "threads_user_id_set": bool(os.getenv("THREADS_USER_ID", "")),
        "threads_token_set": bool(os.getenv("THREADS_ACCESS_TOKEN", "")),
        "note": "App Review承認前は DRY_RUN=true のまま運用してください" if DRY_RUN else "本番モード: App Review承認済みの場合のみ使用してください",
    }
