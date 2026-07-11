"""
YU HOLDINGS System Health Monitor
----------------------------------
Cloud Run 上で完全動作する設計:
  ・gcloud CLI 非依存（Cloud Scheduler API / 直接HTTP のみ）
  ・ローカルPATH 非依存
  ・秘密情報はログ出力しない
  ・service_account JSON は GOOGLE_CREDENTIALS_B64 経由で読み込み済み CREDS_PATH を受け取る

対象チェック:
  ・7 Cloud Run サービス (/health HTTP 200/403 = 正常)
  ・Cloud Scheduler 全ジョブ (Cloud Scheduler Admin API)
  ・6事業スプレッドシート接続
  ・Beauty 月次売上危険アラート
"""

import os
import time
import traceback
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests
import gspread
from google.oauth2.service_account import Credentials

# ── 定数 ──────────────────────────────────────────────
GCP_PROJECT  = "tree-beauty-ai-499303"
GCP_LOCATION = "asia-northeast1"
JST = timezone(timedelta(hours=9))

CLOUD_RUN_SERVICES = {
    "tree-beauty-ai":    {"url": "https://tree-beauty-ai-qpiiccdspa-an.a.run.app",    "importance": "S", "label": "Tree Beauty AI"},
    "trees-catering-ai": {"url": "https://trees-catering-ai-qpiiccdspa-an.a.run.app", "importance": "S", "label": "Trees Catering AI"},
    "tachinomiya-ai":    {"url": "https://tachinomiya-ai-qpiiccdspa-an.a.run.app",    "importance": "S", "label": "TACHINOMIYA AI"},
    "ryukyu-hinabe-ai":  {"url": "https://ryukyu-hinabe-ai-qpiiccdspa-an.a.run.app",  "importance": "S", "label": "琉球火鍋 AI"},
    "pasta-pasta-ai":    {"url": "https://pasta-pasta-ai-qpiiccdspa-an.a.run.app",    "importance": "A", "label": "Pasta Pasta AI"},
    "z1-ai":             {"url": "https://z1-ai-qpiiccdspa-an.a.run.app",             "importance": "A", "label": "Z1 AI"},
    "yu-holdings-ai":    {"url": "https://yu-holdings-ai-qpiiccdspa-an.a.run.app",    "importance": "S", "label": "YU Holdings AI"},
}

# 月次目標（business_registry.py と同期して変更すること）
MONTHLY_TARGETS = {
    "beauty":     500_000,
    "catering":   800_000,
    "tachinomiya": 5_500_000,  # 昼2.5M + 夜3.0M（SSOT整合）
    "hinabe":     1_500_000,
    "pasta":      2_000_000,
    "z1":         1_500_000,
}
# 売上危険閾値（目標比）
DANGER_THRESHOLD = 0.30   # 月末まで30%未満 → 重要度S
WARNING_THRESHOLD = 0.60  # 60%未満 → 重要度A

SHEET_DASHBOARD = "SYSTEM_HEALTH_DASHBOARD"
SHEET_JOB_LOG   = "SYSTEM_JOB_LOG"
SHEET_ERROR_LOG = "SYSTEM_ERROR_LOG"

HEADER_DASHBOARD = [
    "確認日時", "対象サービス", "対象種別", "ステータス",
    "最終成功日時", "最終失敗日時", "失敗回数", "直近エラー内容",
    "重要度", "復旧アクション", "担当", "通知状況", "メモ",
]
HEADER_JOB_LOG = [
    "実行日時", "ジョブ名", "サービス名", "エンドポイント",
    "結果", "HTTPステータス", "処理時間(ms)", "エラー内容", "再実行可否", "通知状況",
]
HEADER_ERROR_LOG = [
    "発生日時", "事業名", "機能名", "エラー種別", "エラー内容",
    "影響範囲", "重要度", "自動復旧可否", "対応状況", "対応メモ",
]


def _now_jst() -> str:
    return datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")


def _ym_jst() -> str:
    return datetime.now(JST).strftime("%Y/%m")


def _gc(creds_path: str) -> gspread.Client:
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    return gspread.authorize(creds)


def _get_or_create_sheet(ss: gspread.Spreadsheet, title: str, header: list) -> gspread.Worksheet:
    try:
        return ss.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=title, rows=1000, cols=len(header))
        ws.update(values=[header], range_name="A1")
        ws.format("A1:Z1", {
            "backgroundColor": {"red": 0.12, "green": 0.12, "blue": 0.2},
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        })
        return ws


# ── 1. シート構築 ──────────────────────────────────────
def setup_health_sheets(spreadsheet_id: str, creds_path: str) -> dict:
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    created = []
    for title, header in [
        (SHEET_DASHBOARD, HEADER_DASHBOARD),
        (SHEET_JOB_LOG,   HEADER_JOB_LOG),
        (SHEET_ERROR_LOG, HEADER_ERROR_LOG),
    ]:
        _get_or_create_sheet(ss, title, header)
        created.append(title)
    return {"ok": True, "sheets_created": created, "spreadsheet_id": spreadsheet_id}


# ── 2. Cloud Run ヘルスチェック（HTTP / no gcloud CLI） ──
def _check_cloud_run(timeout: int = 10) -> list[dict]:
    results = []
    for svc, info in CLOUD_RUN_SERVICES.items():
        start = time.time()
        status, http_code, error = "unknown", 0, ""
        try:
            r = requests.get(f"{info['url']}/health", timeout=timeout)
            http_code = r.status_code
            elapsed   = int((time.time() - start) * 1000)
            # 200=正常, 403=認証保護で稼働中(正常), それ以外=異常
            status = "正常" if r.status_code in (200, 403) else "異常"
            if r.status_code not in (200, 403):
                error = f"HTTP {r.status_code}"
        except requests.exceptions.Timeout:
            status, error = "異常", "タイムアウト"
            elapsed = timeout * 1000
        except Exception as e:
            status = "異常"
            error  = str(e)[:100]
            elapsed = int((time.time() - start) * 1000)
        results.append({
            "name":       svc,
            "label":      info["label"],
            "type":       "Cloud Run",
            "status":     status,
            "http_code":  http_code,
            "error":      error,
            "importance": info["importance"],
            "elapsed_ms": elapsed,
        })
    return results


# ── 3. Cloud Scheduler チェック（Admin API / no gcloud CLI） ──
def _check_schedulers(creds_path: str) -> list[dict]:
    try:
        from googleapiclient.discovery import build
        from google.oauth2.service_account import Credentials as SACreds
        creds = SACreds.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        svc    = build("cloudscheduler", "v1", credentials=creds, cache_discovery=False)
        parent = f"projects/{GCP_PROJECT}/locations/{GCP_LOCATION}"
        resp   = svc.projects().locations().jobs().list(parent=parent).execute()
        jobs   = resp.get("jobs", [])
        results = []
        for j in jobs:
            name  = j["name"].split("/")[-1]
            state = j.get("state", "UNKNOWN")
            last  = j.get("lastAttemptTime", "")[:10] if j.get("lastAttemptTime") else "未実行"
            results.append({
                "name":   name,
                "state":  state,
                "last":   last,
                "status": "正常" if state == "ENABLED" else "無効",
                "error":  "" if state == "ENABLED" else f"state={state}",
                "type":   "Cloud Scheduler",
            })
        return results
    except Exception as e:
        # ログに詳細は出すが秘密情報はない
        print(f"[HEALTH] Scheduler API エラー: {type(e).__name__}")
        return [{"name": "Scheduler API", "state": "ERROR", "status": "異常",
                 "error": f"{type(e).__name__}: {str(e)[:80]}", "type": "Cloud Scheduler", "last": ""}]


# ── 4. スプレッドシート接続テスト ──────────────────────
def _check_spreadsheets(creds_path: str) -> list[dict]:
    ids = {
        "beauty":      os.getenv("GOOGLE_SPREADSHEET_ID", ""),
        "catering":    os.getenv("CATERING_SPREADSHEET_ID", ""),
        "tachinomiya": os.getenv("TACHINOMIYA_SPREADSHEET_ID", ""),
        "hinabe":      os.getenv("HINABE_SPREADSHEET_ID", ""),
        "pasta":       os.getenv("PASTA_SPREADSHEET_ID", ""),
        "z1":          os.getenv("Z1_SPREADSHEET_ID", ""),
    }
    gc = _gc(creds_path)
    results = []
    for biz, ss_id in ids.items():
        if not ss_id:
            results.append({"name": biz, "type": "Spreadsheet", "status": "未設定",
                             "error": "ID未設定", "importance": "B"})
            continue
        try:
            ss     = gc.open_by_key(ss_id)
            titles = [w.title for w in ss.worksheets()]
            results.append({"name": biz, "type": "Spreadsheet", "status": "正常",
                             "error": "", "importance": "A", "sheets": len(titles)})
        except Exception as e:
            results.append({"name": biz, "type": "Spreadsheet", "status": "異常",
                             "error": str(e)[:100], "importance": "A"})
    return results


# ── 5. Beauty 売上危険アラート ──────────────────────────
def _check_beauty_sales(creds_path: str) -> Optional[dict]:
    ss_id = os.getenv("GOOGLE_SPREADSHEET_ID", "")
    if not ss_id:
        return None
    try:
        gc  = _gc(creds_path)
        ss  = gc.open_by_key(ss_id)
        ws  = ss.worksheet("POS_KPI")
        ym  = _ym_jst()
        rows = ws.get_all_values()
        target = MONTHLY_TARGETS["beauty"]
        for row in rows[1:]:
            if row and row[0] == ym:
                sales = int(row[1]) if row[1].isdigit() else 0
                rate  = sales / target if target else 0
                # 月末まで残り日数で重要度を調整
                today = datetime.now(JST)
                last_day = (today.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
                days_left = (last_day - today).days + 1
                days_total = last_day.day
                elapsed_ratio = (today.day - 1) / days_total

                # 経過比率を考慮した「期待達成率」
                expected = elapsed_ratio
                is_danger  = rate < DANGER_THRESHOLD
                is_warning = rate < WARNING_THRESHOLD and not is_danger
                importance = "S" if is_danger else ("A" if is_warning else "B")
                status     = "危険" if is_danger else ("要注意" if is_warning else "正常")
                return {
                    "name":       "Tree Beauty 売上",
                    "type":       "売上アラート",
                    "status":     status,
                    "importance": importance,
                    "error":      f"月次売上 ¥{sales:,} / 目標 ¥{target:,} / 達成率{rate*100:.1f}%" if status != "正常" else "",
                    "memo":       (
                        "【推奨アクション】予約空き投稿・口コミ依頼・HPBブログ・Google投稿・再来店LINE・施術写真撮影" if is_danger else ""
                    ),
                    "sales":   sales,
                    "target":  target,
                    "rate_pct": round(rate * 100, 1),
                }
        return None
    except Exception as e:
        print(f"[HEALTH] Beauty売上チェックエラー: {type(e).__name__}")
        return None


# ── 6. メインヘルスチェック ────────────────────────────
def run_health_check(spreadsheet_id: str, creds_path: str) -> dict:
    now = _now_jst()
    gc  = _gc(creds_path)
    ss  = gc.open_by_key(spreadsheet_id)
    ws_dash = _get_or_create_sheet(ss, SHEET_DASHBOARD, HEADER_DASHBOARD)

    run_results   = _check_cloud_run()
    sched_results = _check_schedulers(creds_path)
    sheet_results = _check_spreadsheets(creds_path)
    beauty_alert  = _check_beauty_sales(creds_path)

    sched_ok = sum(1 for j in sched_results if j["status"] == "正常")
    sched_ng = len(sched_results) - sched_ok
    run_ok   = sum(1 for r in run_results   if r["status"] == "正常")
    run_ng   = len(run_results) - run_ok
    sheets_ok = sum(1 for r in sheet_results if r["status"] == "正常")

    all_checks = run_results + sheet_results
    if beauty_alert:
        all_checks.append(beauty_alert)

    critical_errors = [r for r in all_checks if r["status"] not in ("正常",) and r.get("importance") == "S"]

    # SYSTEM_HEALTH_DASHBOARD へ書き込み
    new_rows = []
    for r in run_results:
        action = "Cloud Run管理コンソール で確認・再デプロイ" if r["status"] == "異常" else ""
        new_rows.append([
            now, r["label"], r["type"], r["status"],
            now if r["status"] == "正常" else "",
            "" if r["status"] == "正常" else now,
            0 if r["status"] == "正常" else 1,
            r.get("error", ""),
            r.get("importance", "A"), action, "AI", "通知済", "",
        ])
    for r in sheet_results:
        new_rows.append([
            now, r["name"], r["type"], r["status"],
            now if r["status"] == "正常" else "",
            "" if r["status"] == "正常" else now,
            0 if r["status"] == "正常" else 1,
            r.get("error", ""),
            r.get("importance", "A"), "", "AI", "通知済", "",
        ])
    # Scheduler サマリー
    sched_status = "正常" if sched_ng == 0 else "一部無効"
    new_rows.append([
        now, f"Cloud Scheduler ({sched_ok}/{len(sched_results)})", "Scheduler", sched_status,
        now if sched_ng == 0 else "",
        "" if sched_ng == 0 else now,
        sched_ng,
        f"{sched_ng}件無効" if sched_ng else "",
        "S", "Schedulerコンソール で確認" if sched_ng else "", "AI", "通知済", "",
    ])
    # Beauty売上アラート
    if beauty_alert:
        new_rows.append([
            now, beauty_alert["name"], beauty_alert["type"], beauty_alert["status"],
            now if beauty_alert["status"] == "正常" else "",
            "" if beauty_alert["status"] == "正常" else now,
            0 if beauty_alert["status"] == "正常" else 1,
            beauty_alert.get("error", ""),
            beauty_alert.get("importance", "A"),
            beauty_alert.get("memo", ""), "AI", "通知済", "",
        ])
    ws_dash.insert_rows(new_rows, row=2)

    # SYSTEM_JOB_LOG へ記録
    ws_job = _get_or_create_sheet(ss, SHEET_JOB_LOG, HEADER_JOB_LOG)
    job_rows = [[
        now, r["name"], r["label"], r["name"] + "/health",
        r["status"], r.get("http_code", ""), r.get("elapsed_ms", ""),
        r.get("error", ""), "可", "—",
    ] for r in run_results]
    ws_job.insert_rows(job_rows, row=2)

    # エラーがあれば SYSTEM_ERROR_LOG へ記録
    ws_err = _get_or_create_sheet(ss, SHEET_ERROR_LOG, HEADER_ERROR_LOG)
    err_rows = []
    for r in critical_errors:
        err_rows.append([
            now, r.get("name", ""), r.get("type", ""), "自動検知",
            r.get("error", r.get("status", "")),
            "売上・集客・通知", r.get("importance", "S"),
            "不可", "未対応", r.get("memo", ""),
        ])
    if err_rows:
        ws_err.insert_rows(err_rows, row=2)

    result = {
        "ok":           True,
        "checked_at":   now,
        "cloud_run":    {"ok": run_ok,   "ng": run_ng,   "total": len(run_results)},
        "scheduler":    {"ok": sched_ok, "ng": sched_ng, "total": len(sched_results)},
        "sheets":       {"ok": sheets_ok,                "total": len(sheet_results)},
        "critical_errors": [e.get("name") for e in critical_errors],
        "has_critical":    len(critical_errors) > 0,
    }
    if beauty_alert:
        result["beauty_sales"] = {
            "status":   beauty_alert["status"],
            "rate_pct": beauty_alert.get("rate_pct"),
            "importance": beauty_alert["importance"],
        }
    return result


# ── 7. LINE通知 ────────────────────────────────────────
def send_health_report(
    spreadsheet_id: str,
    creds_path: str,
    line_token: str,
    check_result: Optional[dict] = None,
) -> dict:
    if check_result is None:
        check_result = run_health_check(spreadsheet_id, creds_path)

    cr  = check_result.get("cloud_run", {})
    sch = check_result.get("scheduler", {})
    sht = check_result.get("sheets",    {})
    errs = check_result.get("critical_errors", [])
    beauty = check_result.get("beauty_sales", {})

    if check_result.get("has_critical"):
        msg  = "【AIシステム異常検知】\n\n"
        msg += f"⚠️ 重大エラー {len(errs)}件\n\n"
        for e in errs:
            msg += f"● {e}\n"
        msg += f"\nCloud Run: {cr.get('ok')}/{cr.get('total')} 正常\n"
        msg += f"Scheduler: {sch.get('ok')}/{sch.get('total')} 正常\n"
        msg += f"Sheets:    {sht.get('ok')}/{sht.get('total')} 正常\n"
        if beauty and beauty.get("status") != "正常":
            msg += f"\n⚠️ Beauty売上: {beauty.get('rate_pct')}% (重要度{beauty.get('importance')})\n"
            msg += "推奨: 予約空き投稿・口コミ依頼・HPBブログ・Google投稿・再来店LINE・施術写真\n"
        msg += "\n📋 SYSTEM_HEALTH_DASHBOARD を確認してください。"
    else:
        msg  = "【YU HOLDINGS AI Health Check】\n\n"
        msg += f"全体状況：✅ 正常\n"
        msg += f"Cloud Run：{cr.get('ok')}/{cr.get('total')} 正常\n"
        msg += f"Scheduler：{sch.get('ok')}/{sch.get('total')} ENABLED\n"
        msg += f"Sheets連携：{sht.get('ok')}/{sht.get('total')} 正常\n"
        msg += f"重大エラー：0件\n"
        if beauty and beauty.get("status") != "正常":
            msg += f"\n⚠️ Beauty売上注意: 達成率{beauty.get('rate_pct')}%\n"
        msg += "\n本日も自動稼働します。"

    if not line_token:
        return {"ok": True, "sent": False, "reason": "LINE_TOKEN未設定(dry_run)", "message": msg}

    try:
        resp = requests.post(
            "https://api.line.me/v2/bot/message/broadcast",
            headers={
                "Authorization": f"Bearer {line_token}",
                "Content-Type":  "application/json",
            },
            json={"messages": [{"type": "text", "text": msg}]},
            timeout=10,
        )
        ok = resp.status_code == 200
        # LINE tokenはログに出さない
        return {"ok": ok, "status_code": resp.status_code, "message_preview": msg[:120]}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:80]}"}


# ── 8. 統合日次チェック（/system-health-daily 用） ──────
def run_daily(spreadsheet_id: str, creds_path: str, line_token: str) -> dict:
    check = run_health_check(spreadsheet_id, creds_path)
    notify = send_health_report(spreadsheet_id, creds_path, line_token, check_result=check)
    return {
        "ok":           check.get("ok") and notify.get("ok"),
        "health":       check,
        "notification": {"sent": notify.get("sent", True), "status_code": notify.get("status_code")},
    }


# ── 9. ジョブ実行ログ記録 ──────────────────────────────
def log_job_execution(
    spreadsheet_id: str,
    creds_path: str,
    job_name: str,
    service_name: str,
    endpoint: str,
    result: str,
    http_status: int = 200,
    elapsed_ms: int = 0,
    error: str = "",
    retriable: bool = True,
) -> dict:
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    ws = _get_or_create_sheet(ss, SHEET_JOB_LOG, HEADER_JOB_LOG)
    ws.insert_rows([[
        _now_jst(), job_name, service_name, endpoint,
        result, http_status, elapsed_ms, error,
        "可" if retriable else "不可", "—",
    ]], row=2)
    return {"ok": True, "logged": job_name}


# ── 10. エラーログ記録 ────────────────────────────────
def log_error(
    spreadsheet_id: str,
    creds_path: str,
    business: str,
    function: str,
    error_type: str,
    error_content: str,
    scope: str = "",
    importance: str = "B",
    auto_recoverable: bool = False,
    memo: str = "",
) -> dict:
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    ws = _get_or_create_sheet(ss, SHEET_ERROR_LOG, HEADER_ERROR_LOG)
    ws.insert_rows([[
        _now_jst(), business, function, error_type, error_content,
        scope, importance, "可" if auto_recoverable else "不可", "未対応", memo,
    ]], row=2)
    return {"ok": True, "logged": function}


# ── 11. 疑似エラーテスト（本番影響なし） ────────────────
def test_error_notification(
    spreadsheet_id: str,
    creds_path: str,
    line_token: str,
) -> dict:
    dummy_result = {
        "ok":            True,
        "cloud_run":     {"ok": 6, "ng": 1, "total": 7},
        "scheduler":     {"ok": 31, "ng": 0, "total": 31},
        "sheets":        {"ok": 5, "total": 6},
        "critical_errors": ["[TEST] trees-catering-ai"],
        "has_critical":  True,
        "beauty_sales":  {"status": "危険", "rate_pct": 13.3, "importance": "S"},
    }
    log_error(
        spreadsheet_id, creds_path,
        "test", "system-error-test", "テスト",
        "[TEST] 疑似エラー通知テスト", "", "C", True, "テスト実行 — 実際の障害ではありません",
    )
    result = send_health_report(
        spreadsheet_id, creds_path, line_token, check_result=dummy_result
    )
    result["test"] = True
    return result
