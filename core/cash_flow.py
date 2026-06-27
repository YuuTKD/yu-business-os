"""
Cash Flow Survival OS
----------------------
YU HOLDINGS全体の資金繰り・返済・支払い・入金予定・不足額を自動で見える化し、
「今日いくら必要で、何をすれば現金が増えるか」を毎日判断できる状態にする。

最重要ゴール:
  ・現金ショートを事前に検知
  ・返済/支払い遅れを防ぐ
  ・入金予定と不足額を毎日見える化
  ・不足時に売上回収/営業/催促タスクを自動生成
  ・Knowledge OS / Daily Action Commander へ連携

設計方針: OpenAI不使用・ルールベース。LINE本番送信はDRY_RUNでスキップ。
"""

import os
from datetime import datetime, timezone, timedelta

import gspread
from google.oauth2.service_account import Credentials
from google.cloud import storage as gcs_storage

JST = timezone(timedelta(hours=9))
GCS_BUCKET  = "tree-beauty-blog-images"
GCS_PREFIX  = "knowledge-os"
GCS_PROJECT = "tree-beauty-ai-499303"

# ── 最低残すべき現金（後でCASH_FLOW_SETTINGSシートで上書き可能）──
DEFAULT_MIN_CASH  = 100_000   # 全社最低現金
DEFAULT_DANGER    = 50_000    # 危険ライン
DEFAULT_CRITICAL  = 0         # 超危険ライン（これ未満＝即ショート）

# ── シート定義 ─────────────────────────────────────────────
CASH_FLOW_SHEETS = {
    "CASH_FLOW_MASTER": [
        "登録日時", "対象日", "事業名", "区分", "内容", "相手先",
        "入金予定額", "支払い予定額", "確定/予定", "支払期限", "入金予定日",
        "優先度", "資金影響", "残高反映", "対応状況", "担当者",
        "次回アクション", "メモ", "エラー内容",
    ],
    "CASH_FLOW_DASHBOARD": [
        "日付", "現金残高", "本日入金予定", "本日支払い予定",
        "7日以内入金予定", "7日以内支払い予定", "30日以内入金予定", "30日以内支払い予定",
        "不足見込み", "危険日", "危険度", "今日必要な売上",
        "今日やるべき回収/営業タスク", "最終更新日時",
    ],
    "CASH_FLOW_ACTIONS": [
        "作成日時", "対象日", "事業名", "アクション種別", "内容",
        "推定回収額", "期限", "担当", "通知先", "対応状況",
        "完了日時", "結果", "メモ",
    ],
    "PAYMENT_SCHEDULE": [
        "支払日", "相手先", "内容", "金額", "区分", "優先度",
        "支払原資", "支払状況", "遅延リスク", "交渉余地", "次回アクション", "メモ",
    ],
    "RECEIVABLES_MASTER": [
        "請求日", "入金予定日", "事業名", "相手先", "案件名", "請求額",
        "入金済額", "未回収額", "入金状況", "催促状況", "次回催促日", "担当", "メモ",
    ],
    "CASH_FLOW_SETTINGS": [
        "項目", "値", "説明",
    ],
}

# 区分（資金影響: +入金 / -支払い）
INFLOW_KINDS  = {"現金残高", "入金予定", "売掛金"}
OUTFLOW_KINDS = {"支払い予定", "返済", "税金", "家賃", "人件費",
                 "仕入れ", "外注費", "広告費", "緊急支払い"}


# ── 内部ユーティリティ ────────────────────────────────────

def _now_jst() -> str:
    return datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")


def _date_jst() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d")


def _today() -> datetime:
    return datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0)


def _gc(creds_path: str) -> gspread.Client:
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"],
    )
    return gspread.authorize(creds)


def _gcs(creds_path: str) -> gcs_storage.Client:
    creds = Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/devstorage.read_write"])
    return gcs_storage.Client(project=GCS_PROJECT, credentials=creds)


def _upload_md_gcs(creds_path: str, gcs_path: str, content: str) -> str:
    blob = _gcs(creds_path).bucket(GCS_BUCKET).blob(gcs_path)
    blob.upload_from_string(content.encode("utf-8"), content_type="text/markdown")
    return f"https://storage.googleapis.com/{GCS_BUCKET}/{gcs_path}"


def _get_or_create_sheet(ss, title, header):
    try:
        return ss.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=title, rows=2000, cols=max(len(header), 12))
        ws.update(values=[header], range_name="A1")
        ws.format("A1:Z1", {
            "backgroundColor": {"red": 0.10, "green": 0.18, "blue": 0.10},
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        })
        return ws


def _parse_int(v) -> int:
    if v is None:
        return 0
    s = str(v).replace(",", "").replace("¥", "").replace("円", "").replace(" ", "").strip()
    if s in ("", "-", "—"):
        return 0
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return 0


def _parse_date(s):
    if not s:
        return None
    s = str(s).strip().replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=JST)
        except (ValueError, TypeError):
            continue
    return None


# ── 設定取得 ──────────────────────────────────────────────

def _load_settings(ss) -> dict:
    """CASH_FLOW_SETTINGS から最低現金などを取得（無ければデフォルト）"""
    settings = {
        "min_cash": DEFAULT_MIN_CASH,
        "danger":   DEFAULT_DANGER,
        "critical": DEFAULT_CRITICAL,
    }
    try:
        ws = ss.worksheet("CASH_FLOW_SETTINGS")
        for r in ws.get_all_records():
            key = str(r.get("項目", "")).strip()
            val = _parse_int(r.get("値"))
            if key == "全社最低現金":
                settings["min_cash"] = val
            elif key == "危険ライン":
                settings["danger"] = val
            elif key == "超危険ライン":
                settings["critical"] = val
    except gspread.WorksheetNotFound:
        pass
    return settings


# ── 現金残高 / 予定の集計 ─────────────────────────────────

def _get_current_balance(records) -> int:
    """区分=現金残高 の最新行を現金残高とする"""
    bal_rows = [r for r in records if str(r.get("区分")) == "現金残高"]
    if not bal_rows:
        return 0
    # 対象日が最も新しいもの
    def keyf(r):
        d = _parse_date(r.get("対象日"))
        return d or datetime.min.replace(tzinfo=JST)
    latest = max(bal_rows, key=keyf)
    return _parse_int(latest.get("入金予定額")) or _parse_int(latest.get("残高反映"))


def _project_balance(records, settings, horizon_days=30):
    """
    日次の running balance を horizon_days 分計算し、
    危険日（残高 < 最低現金 になる最初の日）と不足見込みを返す。
    """
    today = _today()
    balance = _get_current_balance(records)
    min_cash = settings["min_cash"]

    # 日付別の純増減を集計（現金残高区分は除外）
    daily_delta = {}
    for r in records:
        kind = str(r.get("区分"))
        if kind == "現金残高":
            continue
        inflow  = _parse_int(r.get("入金予定額"))
        outflow = _parse_int(r.get("支払い予定額"))
        # 入金は入金予定日、支払いは支払期限を基準日に
        d_in  = _parse_date(r.get("入金予定日"))
        d_out = _parse_date(r.get("支払期限"))
        if inflow and d_in:
            key = d_in.strftime("%Y-%m-%d")
            daily_delta[key] = daily_delta.get(key, 0) + inflow
        if outflow and d_out:
            key = d_out.strftime("%Y-%m-%d")
            daily_delta[key] = daily_delta.get(key, 0) - outflow

    running = balance
    danger_date = ""
    min_balance = balance
    horizon_breakdown = []
    for i in range(0, horizon_days + 1):
        day = today + timedelta(days=i)
        key = day.strftime("%Y-%m-%d")
        running += daily_delta.get(key, 0)
        min_balance = min(min_balance, running)
        if running < min_cash and not danger_date:
            danger_date = key
        horizon_breakdown.append((key, running))

    shortage = max(0, min_cash - min_balance)
    return {
        "balance": balance,
        "danger_date": danger_date,
        "min_balance": min_balance,
        "shortage": shortage,
        "daily_delta": daily_delta,
    }


def _window_sum(records, days, inflow=True):
    today = _today()
    end = today + timedelta(days=days)
    total = 0
    for r in records:
        if str(r.get("区分")) == "現金残高":
            continue
        if inflow:
            amt = _parse_int(r.get("入金予定額"))
            d = _parse_date(r.get("入金予定日"))
        else:
            amt = _parse_int(r.get("支払い予定額"))
            d = _parse_date(r.get("支払期限"))
        if amt and d and today <= d <= end:
            total += amt
    return total


def _danger_level(proj, settings) -> str:
    """S: 7日以内不足 / A: 14日以内 / B: 30日以内 / C: 問題なし"""
    dd = proj["danger_date"]
    if not dd:
        return "C"
    d = _parse_date(dd)
    days = (d - _today()).days
    if proj["min_balance"] < settings["critical"] or days <= 7:
        return "S"
    if days <= 14:
        return "A"
    if days <= 30:
        return "B"
    return "C"


# ── アクション自動生成 ────────────────────────────────────

def _gen_actions(proj, settings, danger, records) -> list:
    """不足がある場合に回収/営業/催促タスクを生成"""
    actions = []
    shortage = proj["shortage"]
    if danger == "C" or shortage <= 0:
        return actions

    now = _date_jst()
    # 未回収金の催促（RECEIVABLES から拾う想定 / MASTERの売掛金区分）
    receivable = sum(_parse_int(r.get("入金予定額")) for r in records
                     if str(r.get("区分")) in ("売掛金", "入金予定")
                     and str(r.get("対応状況")) not in ("回収済み", "入金済み", "完了"))

    candidates = [
        ("回収", "未回収金の催促（請求済み案件の入金確認・督促）", min(shortage, receivable)),
        ("営業", "ケータリング見積未返信への即対応・本日見積提出", int(shortage * 0.5)),
        ("営業", "Catering営業DMを追加5件送信（短期入金見込み）", 0),
        ("販促", "TACHINOMIYA高粗利商品を本日重点訴求", 0),
        ("販促", "Beauty再来店LINE送信候補へ案内（当日予約獲得）", 0),
        ("支払交渉", "支払い先へ分割/期日相談（資金繰り平準化）", 0),
        ("コスト", "不要支出の停止・外注費支払い確認・仕入れ抑制", 0),
    ]
    for kind, content, est in candidates:
        actions.append({
            "作成日時": _now_jst(), "対象日": now, "事業名": "全社",
            "アクション種別": kind, "内容": content,
            "推定回収額": est, "期限": now, "担当": "",
            "通知先": "オーナー", "対応状況": "未対応",
            "完了日時": "", "結果": "", "メモ": f"不足見込み¥{shortage:,}・危険度{danger}",
        })
    return actions


# ── 公開API ───────────────────────────────────────────────

def setup(spreadsheet_id: str, creds_path: str) -> dict:
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    created = []
    for name, header in CASH_FLOW_SHEETS.items():
        _get_or_create_sheet(ss, name, header)
        created.append(name)
    # 設定の初期値を投入（空なら）
    try:
        sw = ss.worksheet("CASH_FLOW_SETTINGS")
        if len(sw.get_all_values()) <= 1:
            sw.append_rows([
                ["全社最低現金", DEFAULT_MIN_CASH, "これを下回ると不足とみなす"],
                ["危険ライン",   DEFAULT_DANGER,   "残高がこれ未満で危険"],
                ["超危険ライン", DEFAULT_CRITICAL, "これ未満で即ショート"],
            ], value_input_option="RAW")
    except Exception:
        pass
    return {"ok": True, "sheets_created": created,
            "settings": {"min_cash": DEFAULT_MIN_CASH, "danger": DEFAULT_DANGER,
                         "critical": DEFAULT_CRITICAL},
            "url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"}


# ── テストデータ（20件以上）──────────────────────────────

def _test_records():
    """対象日は本日基準で相対生成"""
    t = _today()
    def d(offset):
        return (t + timedelta(days=offset)).strftime("%Y-%m-%d")
    now = _now_jst()

    def row(kind, content, party, inflow=0, outflow=0, fixed="予定",
            pay_due="", in_due="", pri="B", biz="全社"):
        return {
            "登録日時": now, "対象日": d(0), "事業名": biz, "区分": kind,
            "内容": content, "相手先": party,
            "入金予定額": inflow, "支払い予定額": outflow, "確定/予定": fixed,
            "支払期限": pay_due, "入金予定日": in_due, "優先度": pri,
            "資金影響": ("+" if inflow else "-") + (f"{inflow:,}" if inflow else f"{outflow:,}"),
            "残高反映": inflow if kind == "現金残高" else "",
            "対応状況": "未対応", "担当者": "", "次回アクション": "", "メモ": "", "エラー内容": "",
        }

    return [
        # 現金残高パターン（テストではdangerシナリオ用に5万円）
        row("現金残高", "本日現金残高", "自社", inflow=50_000, fixed="確定"),
        # 支払い予定（近日に集中＝危険シナリオ）
        row("返済",     "月末返済", "○○リース", outflow=50_000, pay_due=d(6), pri="S"),
        row("家賃",     "店舗家賃", "不動産会社", outflow=120_000, pay_due=d(4), pri="S"),
        row("人件費",   "スタッフ給与", "従業員", outflow=300_000, pay_due=d(10), pri="A"),
        row("外注費",   "デザイン外注", "外注先A", outflow=40_000, pay_due=d(8)),
        row("仕入れ",   "食材仕入れ", "業者B", outflow=80_000, pay_due=d(3), pri="A", biz="TACHINOMIYA"),
        row("税金",     "消費税中間納付", "税務署", outflow=150_000, pay_due=d(20), pri="A"),
        row("広告費",   "MEO広告", "広告代理店", outflow=30_000, pay_due=d(12)),
        row("緊急支払い", "設備修理", "修理業者", outflow=60_000, pay_due=d(2), pri="S", biz="琉球火鍋"),
        # 入金予定
        row("入金予定", "ケータリング案件入金", "A社", inflow=200_000, in_due=d(9), pri="A", biz="Trees Catering"),
        row("入金予定", "ケータリング案件入金", "B社", inflow=150_000, in_due=d(15), biz="Trees Catering"),
        row("売掛金",   "未回収金（請求済み）", "C社", inflow=120_000, in_due=d(5), pri="A", biz="Trees Catering"),
        row("売掛金",   "未回収金（期日超過）", "D社", inflow=80_000, in_due=d(1), pri="S", biz="Trees Catering"),
        row("入金予定", "Beauty予約売上見込み", "予約客", inflow=45_000, in_due=d(2), biz="Tree Beauty"),
        row("入金予定", "TACHINOMIYA日次売上見込み", "店舗", inflow=90_000, in_due=d(1), biz="TACHINOMIYA"),
        row("入金予定", "琉球火鍋 予約売上", "予約客", inflow=70_000, in_due=d(3), biz="琉球火鍋"),
        row("入金予定", "コンサル成果報酬", "クライアントE", inflow=300_000, in_due=d(25), biz="パスタパスタ"),
        # その他
        row("支払い予定", "通信費", "通信会社", outflow=15_000, pay_due=d(7)),
        row("支払い予定", "サブスク各種", "SaaS", outflow=25_000, pay_due=d(11)),
        row("仕入れ",    "酒類仕入れ", "酒販店", outflow=50_000, pay_due=d(5), biz="TACHINOMIYA"),
        row("外注費",    "清掃外注", "清掃業者", outflow=20_000, pay_due=d(14)),
    ]


def run_test(spreadsheet_id: str, creds_path: str) -> dict:
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    for name, header in CASH_FLOW_SHEETS.items():
        _get_or_create_sheet(ss, name, header)

    ws = ss.worksheet("CASH_FLOW_MASTER")
    header = CASH_FLOW_SHEETS["CASH_FLOW_MASTER"]
    recs = _test_records()
    ws.append_rows([[r.get(h, "") for h in header] for r in recs],
                   value_input_option="RAW")

    # 判定
    result = daily(spreadsheet_id, creds_path, write=True)
    return {
        "ok": True,
        "test_records": len(recs),
        "danger_level": result.get("危険度"),
        "balance": result.get("現金残高"),
        "shortage": result.get("不足見込み"),
        "danger_date": result.get("危険日"),
        "today_needed_sales": result.get("今日必要な売上"),
        "actions_generated": result.get("actions_count"),
        "dry_run": True,
        "note": "判定はルールベース（OpenAI不使用）。LINE送信なし。",
    }


def daily(spreadsheet_id: str, creds_path: str, write: bool = True) -> dict:
    """本日の資金繰り判定 → DASHBOARD更新 + 不足時ACTIONS生成"""
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    try:
        mws = ss.worksheet("CASH_FLOW_MASTER")
    except gspread.WorksheetNotFound:
        return {"ok": False, "error": "CASH_FLOW_MASTER 未作成。/cash-flow-setup を実行してください。"}

    records  = mws.get_all_records()
    settings = _load_settings(ss)
    proj     = _project_balance(records, settings)
    danger   = _danger_level(proj, settings)

    in_today  = _window_sum(records, 0, inflow=True)
    out_today = _window_sum(records, 0, inflow=False)
    in_7   = _window_sum(records, 7, inflow=True)
    out_7  = _window_sum(records, 7, inflow=False)
    in_30  = _window_sum(records, 30, inflow=True)
    out_30 = _window_sum(records, 30, inflow=False)

    needed_sales = proj["shortage"]
    actions = _gen_actions(proj, settings, danger, records)
    action_summary = "／".join(a["内容"][:20] for a in actions[:3]) or "なし"

    if write:
        dash = _get_or_create_sheet(ss, "CASH_FLOW_DASHBOARD", CASH_FLOW_SHEETS["CASH_FLOW_DASHBOARD"])
        row = [
            _date_jst(), proj["balance"], in_today, out_today,
            in_7, out_7, in_30, out_30,
            proj["shortage"], proj["danger_date"] or "—", danger, needed_sales,
            action_summary, _now_jst(),
        ]
        # 当日行は上書き、なければ追記
        recs = dash.get_all_records()
        wrote = False
        for i, r in enumerate(recs, start=2):
            if str(r.get("日付")) == _date_jst():
                dash.update(values=[row], range_name=f"A{i}:N{i}", value_input_option="RAW")
                wrote = True
                break
        if not wrote:
            dash.append_row(row, value_input_option="RAW")

        # アクション記録
        if actions:
            aws = _get_or_create_sheet(ss, "CASH_FLOW_ACTIONS", CASH_FLOW_SHEETS["CASH_FLOW_ACTIONS"])
            ah = CASH_FLOW_SHEETS["CASH_FLOW_ACTIONS"]
            aws.append_rows([[a.get(h, "") for h in ah] for a in actions],
                            value_input_option="RAW")

    return {
        "ok": True, "日付": _date_jst(), "現金残高": proj["balance"],
        "危険度": danger, "危険日": proj["danger_date"] or "",
        "不足見込み": proj["shortage"], "今日必要な売上": needed_sales,
        "本日入金予定": in_today, "本日支払い予定": out_today,
        "7日入金": in_7, "7日支払い": out_7, "30日入金": in_30, "30日支払い": out_30,
        "actions_count": len(actions),
        "actions": [a["内容"] for a in actions],
    }


def get_status(spreadsheet_id: str, creds_path: str) -> dict:
    return daily(spreadsheet_id, creds_path, write=False)


def actions(spreadsheet_id: str, creds_path: str) -> dict:
    """不足時のアクション候補を生成して返す（Daily Action連携用）"""
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    mws = ss.worksheet("CASH_FLOW_MASTER")
    records = mws.get_all_records()
    settings = _load_settings(ss)
    proj = _project_balance(records, settings)
    danger = _danger_level(proj, settings)
    acts = _gen_actions(proj, settings, danger, records)

    # Daily Action 連携用タスク
    dac_tasks = [{
        "biz_key": "owner", "priority": "S" if danger in ("S", "A") else "B",
        "task": a["内容"], "category": a["アクション種別"],
    } for a in acts]

    return {"ok": True, "danger_level": danger, "shortage": proj["shortage"],
            "actions": acts, "daily_action_tasks": dac_tasks, "dry_run": True}


def owner_report(spreadsheet_id: str, creds_path: str) -> dict:
    d = daily(spreadsheet_id, creds_path, write=False)
    emoji = {"S": "🔴", "A": "🟠", "B": "🟡", "C": "🟢"}.get(d["危険度"], "")
    txt = (
        f"【資金繰り日次レポート】{_date_jst()}\n\n"
        f"{emoji} 危険度：{d['危険度']}\n"
        f"💰 現金残高：¥{d['現金残高']:,}\n"
        f"📅 危険日：{d['危険日'] or 'なし'}\n"
        f"⚠️ 不足見込み：¥{d['不足見込み']:,}\n"
        f"🎯 今日必要な売上：¥{d['今日必要な売上']:,}\n\n"
        f"入金 本日¥{d['本日入金予定']:,} / 7日¥{d['7日入金']:,} / 30日¥{d['30日入金']:,}\n"
        f"支払 本日¥{d['本日支払い予定']:,} / 7日¥{d['7日支払い']:,} / 30日¥{d['30日支払い']:,}\n\n"
        f"【今日やるべきこと】\n"
    )
    for a in d.get("actions", [])[:5]:
        txt += f"・{a}\n"
    if not d.get("actions"):
        txt += "・資金繰りは問題なし。通常営業でOK。\n"
    return {"ok": True, "report_text": txt, "danger_level": d["危険度"], "dry_run": True}


# ══════════════════════════════════════════════════════════
#  LINE家計簿 — オーナーLINEから送るだけで記録
# ══════════════════════════════════════════════════════════

import re as _re
import calendar as _calendar

# 区分キーワード（上から順に判定。具体的・誤解の少ないものを上に）
_KIND_KEYWORDS = [
    ("売掛金",     ["売掛", "未回収", "未収", "請求済", "請求書"]),
    ("入金予定",   ["入金予定", "入金", "売上入金", "売上", "振込", "振り込み", "回収", "入る予定", "売掛回収"]),
    ("現金残高",   ["現金残高", "残高", "手元現金", "手元", "手持ち", "現金", "預金", "口座"]),
    ("返済",       ["返済", "ローン", "リース", "借入", "返金予定"]),
    ("家賃",       ["家賃", "賃料", "テナント", "地代"]),
    ("人件費",     ["人件費", "給与", "給料", "バイト代", "スタッフ給", "アルバイト", "賞与", "ボーナス", "日給", "時給"]),
    ("税金",       ["税金", "消費税", "法人税", "源泉", "住民税", "社会保険", "年金", "国保", "納税", "予定納税"]),
    ("仕入れ",     ["仕入", "材料費", "食材", "酒類", "ドリンク仕入"]),
    ("外注費",     ["外注", "委託", "業務委託"]),
    ("広告費",     ["広告", "ＭＥＯ", "meo", "リスティング", "宣伝", "販促費"]),
    ("緊急支払い", ["緊急", "修理", "故障", "弁償", "設備"]),
    ("支払い予定", ["支払", "通信費", "サブスク", "光熱", "電気代", "電気", "水道", "ガス", "経費", "雑費", "リース料"]),
]

_QUERY_WORDS = ["状況", "資金繰り", "残高確認", "レポート", "サマリー", "確認", "今日"]

# 事業名の判定キーワード
_BIZ_NAME_KEYWORDS = [
    ("TACHINOMIYA",    ["tachinomiya", "タチノミヤ", "たちのみや", "立呑", "立飲", "国際通り"]),
    ("Tree Beauty",    ["tree beauty", "beauty", "ビューティー", "ビューティ", "美容", "脱毛", "ツリービューティー"]),
    ("Trees Catering", ["trees catering", "catering", "ケータリング", "ケータ", "ケー タリング"]),
    ("琉球火鍋",        ["琉球火鍋", "火鍋", "かなべ", "ひなべ", "hinabe"]),
    ("パスタパスタ",    ["パスタパスタ", "パスタ", "pasta"]),
    ("Z1",             ["z1", "ｚ1", "ゼットワン"]),
]


def _detect_biz_name(text: str) -> str:
    """テキストから事業名を判定。該当なしは空文字。"""
    low = text.lower()
    for name, kws in _BIZ_NAME_KEYWORDS:
        if any(kw.lower() in low for kw in kws):
            return name
    return ""


def _to_amount(text: str):
    """「12万」「12万5千」「120,000」「8万円」→ int。無ければ None
    ※ 万・千の後続小数字は『隣接』時のみ加算（日付の数字混入を防ぐ）"""
    z2h = str.maketrans("０１２３４５６７８９", "0123456789")
    t = text.translate(z2h)
    # 万・千表記（後続groupはスペースを挟まず隣接する場合のみ）
    m = _re.search(r"(\d+(?:\.\d+)?)\s*万(?:(\d)\s*千)?(\d{1,4})?", t)
    if m:
        v = float(m.group(1)) * 10000
        if m.group(2):
            v += int(m.group(2)) * 1000
        if m.group(3):
            v += int(m.group(3))
        return int(v)
    m = _re.search(r"(\d+)\s*千", t)
    if m:
        return int(m.group(1)) * 1000
    return None


def _next_occurrence(day):
    """毎月day日（dayはint or '末'）の次回到来日を YYYY-MM-DD で返す"""
    today = _today()
    y, mo = today.year, today.month

    def build(yy, mm, dd):
        last = _calendar.monthrange(yy, mm)[1]
        dd2 = last if dd == "末" else min(int(dd), last)
        return today.replace(year=yy, month=mm, day=dd2)

    cand = build(y, mo, day)
    if cand < today:
        mo2 = mo + 1
        y2 = y + (1 if mo2 > 12 else 0)
        mo2 = (mo2 - 1) % 12 + 1
        cand = build(y2, mo2, day)
    return cand.strftime("%Y-%m-%d")


def _parse_date_token(text: str):
    """テキストから支払/入金日を抽出。(date_str, label) を返す。無ければ ('', '')"""
    z2h = str.maketrans("０１２３４５６７８９", "0123456789")
    t = text.translate(z2h)
    today = _today()

    # 毎月N日 / 毎月末
    m = _re.search(r"毎月\s*(末|\d{1,2})\s*日?", t)
    if m:
        d = m.group(1)
        return _next_occurrence(d), f"毎月{d}日(継続)"
    # 月末
    if "月末" in t or _re.search(r"末日?", t):
        if "毎月" not in t:
            return _next_occurrence("末"), "月末"
    # M月D日 / M/D
    m = _re.search(r"(\d{1,2})\s*[月/]\s*(\d{1,2})\s*日?", t)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        y = today.year
        try:
            cand = today.replace(year=y, month=mo, day=d)
            if cand < today:
                cand = cand.replace(year=y + 1)
            return cand.strftime("%Y-%m-%d"), ""
        except ValueError:
            pass
    # 今日/明日/明後日
    if "今日" in t or "本日" in t:
        return today.strftime("%Y-%m-%d"), "今日"
    if "明後日" in t:
        return (today + timedelta(days=2)).strftime("%Y-%m-%d"), "明後日"
    if "明日" in t:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d"), "明日"
    return "", ""


def parse_finance_message(text: str):
    """
    「家賃 12万 毎月25日」「入金予定 A社 20万 7月9日」「現金残高 8万」等を解析。
    CASH_FLOW_MASTER 用の行dictを返す。資金メッセージでなければ None。
    """
    if not text or not text.strip():
        return None
    raw = text.strip()

    # 区分判定
    kind = ""
    for k, kws in _KIND_KEYWORDS:
        if any(kw in raw for kw in kws):
            kind = k
            break
    if not kind:
        return None

    date_str, date_label = _parse_date_token(raw)

    # 金額抽出は先に日付部分を除去（日付の数字混入を防ぐ）
    z2h = raw.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    amt_src = _re.sub(r"\d{1,2}\s*[月/]\s*\d{1,2}\s*日?", " ", z2h)
    amt_src = _re.sub(r"毎月\s*(末|\d{1,2})\s*日?", " ", amt_src)
    amount = _to_amount(amt_src)
    if amount is None:
        nums = [int(n.replace(",", "")) for n in _re.findall(r"\d[\d,]*", amt_src)
                if int(n.replace(",", "")) >= 100]
        amount = max(nums) if nums else None
    if amount is None:
        return None

    is_inflow = kind in INFLOW_KINDS
    # 相手先抽出（区分名・キーワード・数字・日付語を除いた残り）
    party = raw.replace(kind, " ")
    for k, kws in _KIND_KEYWORDS:
        for kw in kws:
            party = party.replace(kw, " ")
    party = _re.sub(r"毎月\s*(末|\d{1,2})\s*日?", " ", party)
    party = _re.sub(r"\d{1,2}\s*[月/]\s*\d{1,2}\s*日?", " ", party)
    party = _re.sub(r"[\d,万千円]+", " ", party)
    party = _re.sub(r"(今日|本日|明日|明後日|月末|末日?)", " ", party)
    # 残った単独の助数詞・接尾辞を除去
    party = _re.sub(r"(?:^|\s)[費金料代税](?:\s|$)", " ", party)
    # フィラー語を除去
    for filler in ["現在", "手元", "手持ち", "今月", "来月", "予定", "です", "ます",
                   "お願い", "よろしく", "テスト", "分", "の", "は", "が", "を", "に", "へ"]:
        party = party.replace(filler, " ")
    party = " ".join(party.split()).strip()
    # 残高系・固定費系は相手先を持たない
    if kind in ("現金残高", "家賃", "人件費", "返済", "税金", "広告費"):
        party = ""

    now = _now_jst()
    today_str = _date_jst()
    row = {
        "登録日時": now, "対象日": today_str, "事業名": "全社", "区分": kind,
        "内容": f"{kind}" + (f"（{date_label}）" if date_label else ""),
        "相手先": party,
        "入金予定額": amount if is_inflow else "",
        "支払い予定額": amount if not is_inflow else "",
        "確定/予定": "確定" if kind == "現金残高" else "予定",
        "支払期限": "" if is_inflow else date_str,
        "入金予定日": date_str if is_inflow else "",
        "優先度": "S" if kind in ("返済", "税金", "緊急支払い") else "A",
        "資金影響": ("+" if is_inflow else "-") + f"{amount:,}",
        "残高反映": amount if kind == "現金残高" else "",
        "対応状況": "未対応", "担当者": "", "次回アクション": "",
        "メモ": "LINE入力" + (f"・{date_label}" if date_label else ""), "エラー内容": "",
    }
    return row


def parse_finance_entries(text: str) -> list:
    """
    複数行メッセージを解析して複数の記録行を返す（事業別対応）。
    ・事業名だけの行 → 以降の行の事業名コンテキストになる
    ・資金行 → 行内の事業名 or 直前のコンテキストでタグ付け
    """
    entries = []
    current_biz = ""
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        biz_in_line = _detect_biz_name(line)
        row = parse_finance_message(line)
        if row:
            row["事業名"] = biz_in_line or current_biz or "全社"
            if biz_in_line:
                current_biz = biz_in_line
            entries.append(row)
        elif biz_in_line:
            # 事業名だけの見出し行 → コンテキスト更新
            current_biz = biz_in_line
    # 1行も取れなければ全文を1エントリとして試す（従来互換）
    if not entries:
        row = parse_finance_message(text)
        if row:
            row["事業名"] = _detect_biz_name(text) or "全社"
            entries.append(row)
    return entries


def record_from_message(spreadsheet_id: str, creds_path: str, text: str) -> dict:
    """LINEメッセージを解析してCASH_FLOW_MASTERへ記録し、返信文を返す（複数行・事業別対応）"""
    raw = (text or "").strip()

    # 照会コマンド（状況/残高など）→ 現在の資金繰りを返す
    if raw in _QUERY_WORDS or raw in ("状況確認", "資金状況"):
        d = daily(spreadsheet_id, creds_path, write=False)
        if not d.get("ok"):
            return {"ok": False, "reply": "まだデータがありません。『家賃 12万 毎月25日』のように送って記録を始めてください。"}
        emoji = {"S": "🔴", "A": "🟠", "B": "🟡", "C": "🟢"}.get(d["危険度"], "")
        reply = (
            f"【資金繰り {d['日付']}】\n"
            f"{emoji} 危険度：{d['危険度']}\n"
            f"現金残高：¥{d['現金残高']:,}\n"
            f"危険日：{d['危険日'] or 'なし'}\n"
            f"不足見込み：¥{d['不足見込み']:,}\n"
            f"今日必要な売上：¥{d['今日必要な売上']:,}"
        )
        return {"ok": True, "reply": reply, "query": True}

    entries = parse_finance_entries(raw)
    if not entries:
        return {"ok": False, "reply": (
            "認識できませんでした😅\n"
            "最初に『種類』の言葉を入れてください。\n\n"
            "【支払い系】家賃／人件費（給与）／返済／税金／仕入れ／外注費／広告費／光熱費／緊急\n"
            "【入金系】入金予定／売上／売掛／未回収\n"
            "【残高】現金残高（手元現金）\n\n"
            "例：\n"
            "・家賃 12万 毎月25日\n"
            "・TACHINOMIYA 家賃 36万 毎月18日\n"
            "・入金予定 A社 20万 7月9日\n"
            "・現金 10万（残高）\n"
            "・「状況」で資金繰り確認\n\n"
            "※複数行で送れば一度に複数記録できます"
        )}

    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    ws = _get_or_create_sheet(ss, "CASH_FLOW_MASTER", CASH_FLOW_SHEETS["CASH_FLOW_MASTER"])
    header = CASH_FLOW_SHEETS["CASH_FLOW_MASTER"]
    ws.append_rows([[r.get(h, "") for h in header] for r in entries],
                   value_input_option="USER_ENTERED")

    # 返信文（複数件はサマリー）
    if len(entries) == 1:
        row = entries[0]
        amount = _parse_int(row.get("入金予定額")) or _parse_int(row.get("支払い予定額"))
        date_disp = row.get("入金予定日") or row.get("支払期限") or "—"
        biz = row.get("事業名", "全社")
        reply = (
            "✅ 記録しました\n"
            + (f"事業：{biz}\n" if biz != "全社" else "")
            + f"区分：{row['区分']}\n"
            + (f"相手先：{row['相手先']}\n" if row.get("相手先") else "")
            + f"金額：¥{amount:,}\n"
            + (f"日付：{date_disp}\n" if date_disp != "—" else "")
            + "\n「状況」と送れば今の資金繰りを確認できます。"
        )
    else:
        lines = [f"✅ {len(entries)}件 記録しました\n"]
        for r in entries:
            amt = _parse_int(r.get("入金予定額")) or _parse_int(r.get("支払い予定額"))
            dt = r.get("入金予定日") or r.get("支払期限") or ""
            biz = r.get("事業名", "全社")
            biz_tag = f"[{biz}] " if biz != "全社" else ""
            lines.append(f"・{biz_tag}{r['区分']} ¥{amt:,}" + (f"（{dt}）" if dt else ""))
        lines.append("\n「状況」で資金繰り確認")
        reply = "\n".join(lines)

    return {"ok": True, "reply": reply, "entries": entries, "count": len(entries)}


def export_knowledge(spreadsheet_id: str, creds_path: str) -> dict:
    d = daily(spreadsheet_id, creds_path, write=False)
    today = _date_jst()
    emoji = {"S": "🔴", "A": "🟠", "B": "🟡", "C": "🟢"}.get(d["危険度"], "")
    md = (
        f"---\ntitle: 資金繰り状況 {today}\nbusiness: YU HOLDINGS\n"
        f"category: cash_flow\ndate: {today}\nsource: cash_flow_survival_os\n"
        f"status: active\ntags: [cash_flow, finance, survival]\n---\n\n"
        f"# 資金繰り状況 — {today}\n\n"
        f"## サマリー\n"
        f"- {emoji} 危険度: **{d['危険度']}**\n"
        f"- 現金残高: ¥{d['現金残高']:,}\n"
        f"- 危険日: {d['危険日'] or 'なし'}\n"
        f"- 不足見込み: ¥{d['不足見込み']:,}\n"
        f"- 今日必要な売上: ¥{d['今日必要な売上']:,}\n\n"
        f"## 入出金予定\n\n"
        f"| 期間 | 入金予定 | 支払い予定 |\n|---|---|---|\n"
        f"| 本日 | ¥{d['本日入金予定']:,} | ¥{d['本日支払い予定']:,} |\n"
        f"| 7日以内 | ¥{d['7日入金']:,} | ¥{d['7日支払い']:,} |\n"
        f"| 30日以内 | ¥{d['30日入金']:,} | ¥{d['30日支払い']:,} |\n\n"
        f"## 今日やるべきこと\n"
    )
    for a in d.get("actions", []):
        md += f"- {a}\n"
    if not d.get("actions"):
        md += "- 資金繰りは問題なし\n"
    path = f"{GCS_PREFIX}/10_Finance_Risk/cash_flow_status_{today}.md"
    url = _upload_md_gcs(creds_path, path, md)
    return {"ok": True, "path": path, "url": url, "danger_level": d["危険度"]}
