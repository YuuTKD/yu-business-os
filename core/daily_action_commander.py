"""
Daily Action Commander

毎日の売上直結タスクを各事業スタッフLINEへ送信し、
LINE返信で完了認識 → スプレッドシート自動更新を行う。

スケジュール:
  09:00 /daily-action-send   → タスク生成・LINE通知
  17:00 /daily-action-remind → 未完了S/Aリマインド
  21:00 /daily-action-owner-report → オーナー向け夜報告
"""

import os
import re
import base64
import hashlib
import hmac
import datetime
import logging

import requests
import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

# ─── スプレッドシート設定 ──────────────────────────────────
TASKS_SHEET    = "DAILY_ACTION_TASKS"
DASH_SHEET     = "DAILY_ACTION_DASHBOARD"
STAFF_MAP_SHEET = "STAFF_LINE_MAP"
DEFAULT_SS_ID  = "1K4KkAhFwVkQqqvzeqa25-1sR26ltBfP9gY9h-N4gXcc"

TASKS_HEADERS = [
    "日付", "事業名", "タスクID", "タスク番号", "タスクカテゴリ",
    "タスク内容", "売上直結度", "優先度", "担当者", "ステータス",
    "通知状況", "通知日時", "完了日時", "完了返信内容", "LINEユーザーID", "メモ",
]
DASH_HEADERS = [
    "日付", "事業名", "全タスク数", "完了数", "未完了数",
    "Sタスク完了率", "Aタスク完了率", "売上直結タスク未完了一覧",
    "17時リマインド対象", "オーナー確認必要", "最終更新日時",
]
STAFF_MAP_HEADERS = ["LINE_USER_ID", "事業名", "スタッフ名", "登録日時", "有効"]

# スタッフマップキャッシュ（5分TTL）
_staff_map_cache: dict = {"data": {}, "updated": 0.0}

# ─── LINE トークン・チャンネルシークレット ─────────────────
# Webhook で事業を識別するため destination → business_key のマッピングも使う
BUSINESS_LINE_TOKEN_ENV = {
    "tachinomiya":   "LINE_TACHINOMIYASTAFF_TOKEN",
    "catering":      "LINE_cateringSTAFF_TOKEN",
    "beauty":        "LINE_STAFF_TOKEN",
    "ryukyu_hinabe": "LINE_hinabeSTAFF_TOKEN",
}
# LINE公式アカウントの destination (userID) → business_key マッピング
# 実際の destination は LINE_DESTINATION_<BUSINESS> 環境変数で設定する
BUSINESS_CHANNEL_SECRET_ENV = {
    "tachinomiya":   "LINE_TACHINOMIYA_CHANNEL_SECRET",
    "catering":      "LINE_CATERING_CHANNEL_SECRET",
    "beauty":        "LINE_BEAUTY_CHANNEL_SECRET",
    "ryukyu_hinabe": "LINE_HINABE_CHANNEL_SECRET",
}
BUSINESS_DESTINATION_ENV = {
    "tachinomiya":   "LINE_TACHINOMIYA_DESTINATION",
    "catering":      "LINE_CATERING_DESTINATION",
    "beauty":        "LINE_BEAUTY_DESTINATION",
    "ryukyu_hinabe": "LINE_HINABE_DESTINATION",
}

# オーナー通知用トークン（LINE_STAFF_TOKEN か別途 LINE_OWNER_TOKEN を使う）
OWNER_LINE_TOKEN_ENV = "LINE_OWNER_TOKEN"

# ─── 事業別タスク定義 ────────────────────────────────────
BUSINESS_TASKS: dict[str, dict] = {
    "tachinomiya": {
        "name": "TACHINOMIYA",
        "today_focus": "国際通り訴求・口コミ強化",
        "daily_goal": "新規来店3名増・口コミ3件獲得",
        "tasks": [
            # (カテゴリ, タスク内容, 売上直結度, 優先度)
            ("売上直結", "口コミ依頼3件（来店客に声かけ）",              "S", 1),
            ("売上直結", "本日のGoogle投稿（国際通り/沖縄料理/サーターアンダギー訴求）", "S", 2),
            ("売上直結", "本日のおすすめメニュー声かけ実施",              "S", 3),
            ("売上直結", "店前または商品写真撮影",                        "S", 4),
            ("集客強化", "Instagramストーリー投稿",                       "A", 5),
            ("集客強化", "Threads投稿",                                   "A", 6),
            ("集客強化", "夜の集客訴求投稿",                              "A", 7),
            ("運営管理", "昼売上・夜売上確認",                            "B", 8),
        ],
    },
    "catering": {
        "name": "TREE's Catering",
        "today_focus": "新規営業・問い合わせ対応",
        "daily_goal": "新規問い合わせ1件獲得・営業DM5件送信",
        "tasks": [
            ("売上直結", "営業DM送信5件（企業/イベント/ホテル向け）",     "S", 1),
            ("売上直結", "問い合わせ未対応確認・返信",                    "S", 2),
            ("売上直結", "過去実績写真投稿",                              "S", 3),
            ("売上直結", "企業/イベント/ホテル向け営業先確認",            "S", 4),
            ("集客強化", "Google投稿",                                    "A", 5),
            ("集客強化", "Instagramストーリー投稿",                       "A", 6),
            ("集客強化", "Threads投稿",                                   "A", 7),
            ("集客強化", "口コミ/紹介依頼1件",                           "A", 8),
            ("運営管理", "案件進捗確認",                                  "B", 9),
        ],
    },
    "beauty": {
        "name": "Tree Beauty",
        "today_focus": "予約促進・口コミ獲得",
        "daily_goal": "本日予約枠埋め・口コミ1件獲得",
        "tasks": [
            ("売上直結", "予約空き状況投稿（Instagram/SNS）",             "S", 1),
            ("売上直結", "口コミ依頼1件（来店客に声かけ）",               "S", 2),
            ("売上直結", "Hot Pepper Beautyブログ確認・更新",             "S", 3),
            ("売上直結", "本日の重点メニュー訴求（SNSまたは声かけ）",     "S", 4),
            ("集客強化", "Google投稿",                                    "A", 5),
            ("集客強化", "Instagramストーリー投稿",                       "A", 6),
            ("集客強化", "店内/施術風景写真撮影",                         "A", 7),
            ("運営管理", "予約状況確認",                                  "B", 8),
        ],
    },
    "ryukyu_hinabe": {
        "name": "琉球火鍋",
        "today_focus": "個室・記念日・女子会訴求",
        "daily_goal": "本日予約確定・口コミ2件獲得",
        "tasks": [
            ("売上直結", "予約空き状況投稿（Instagram/SNS）",             "S", 1),
            ("売上直結", "個室/記念日/女子会訴求投稿",                    "S", 2),
            ("売上直結", "火鍋/黒毛和牛/アグー豚写真撮影",               "S", 3),
            ("売上直結", "口コミ依頼2件（来店客に声かけ）",               "S", 4),
            ("集客強化", "Instagramストーリー投稿",                       "A", 5),
            ("集客強化", "Threads投稿",                                   "A", 6),
            ("集客強化", "当日予約訴求投稿",                              "A", 7),
            ("運営管理", "予約状況確認",                                  "B", 8),
        ],
    },
}

ALL_BUSINESS_KEYS = list(BUSINESS_TASKS.keys())

# ─── Beauty 売上危険時の強化タスク ────────────────────────
BEAUTY_DANGER_TASKS_S = [
    # 達成率50%未満で追加（重要度S）
    ("売上強化", "【強化】本日の予約空き状況をInstagram/LINE/Google投稿", "S", 21),
    ("売上強化", "【強化】口コミ依頼1件（施術後の客に声かけ）",           "S", 22),
    ("売上強化", "【強化】Hot Pepper Beautyブログ確認・新規更新",          "S", 23),
    ("売上強化", "【強化】Google最新投稿確認・投稿実施",                  "S", 24),
    ("売上強化", "【強化】再来店LINE送信候補リスト確認",                  "S", 25),
]
BEAUTY_DANGER_TASKS_A = [
    # 同上・重要度A
    ("集客強化", "【強化】施術写真または店内写真撮影",                    "A", 26),
    ("集客強化", "【強化】Instagramストーリー投稿（空き枠訴求）",         "A", 27),
    ("集客強化", "【強化】重点メニュー訴求文作成（脱毛/ホワイトニング）", "A", 28),
]

BEAUTY_DANGER_THRESHOLD  = 0.50   # 50%未満 → 強化タスク追加
BEAUTY_CRITICAL_THRESHOLD = 0.30  # 30%未満 → オーナーLINE通知


def _get_beauty_achievement_rate(creds_path: str, beauty_ss_id: str) -> float | None:
    """Beauty POS_KPIから当月達成率を取得"""
    try:
        gc  = _get_gc(creds_path)
        ss  = gc.open_by_key(beauty_ss_id)
        ws  = ss.worksheet("POS_KPI")
        ym  = datetime.date.today().strftime("%Y/%m")
        for row in ws.get_all_values()[1:]:
            if row and row[0] == ym:
                sales  = int(row[1]) if row[1] and row[1].isdigit() else 0
                target = int(row[4]) if len(row) > 4 and row[4] and row[4].isdigit() else 0
                if target > 0:
                    return sales / target
        return None
    except Exception as e:
        logger.warning(f"[DAC] Beauty達成率取得失敗: {e}")
        return None


# ─── Google Sheets ────────────────────────────────────────

def _get_gc(creds_path: str) -> gspread.Client:
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds)


def _get_ss_id() -> str:
    return os.getenv("DAILY_ACTION_SPREADSHEET_ID", "") or \
           os.getenv("THREADS_MONITOR_SPREADSHEET_ID", DEFAULT_SS_ID)


def _today() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d")


def _now_str() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _make_task_id(date: str, biz: str, task_no: int) -> str:
    return f"{date.replace('-','')}_{biz[:3].upper()}_{task_no:02d}"


# ─── シートセットアップ ───────────────────────────────────

def setup_sheets(creds_path: str, ss_id: str = "") -> dict:
    """DAILY_ACTION_TASKS・DAILY_ACTION_DASHBOARD シートを作成または確認"""
    sid = ss_id or _get_ss_id()
    gc = _get_gc(creds_path)
    ss = gc.open_by_key(sid)

    results = {}
    for sheet_name, headers in [
        (TASKS_SHEET,    TASKS_HEADERS),
        (DASH_SHEET,     DASH_HEADERS),
        (STAFF_MAP_SHEET, STAFF_MAP_HEADERS),
    ]:
        try:
            ws = ss.worksheet(sheet_name)
            results[sheet_name] = "既存シートを確認（変更なし）"
        except gspread.WorksheetNotFound:
            ws = ss.add_worksheet(title=sheet_name, rows=2000, cols=len(headers))
            ws.update([headers], "A1")
            try:
                color = {"red": 0.1, "green": 0.4, "blue": 0.2} if sheet_name == TASKS_SHEET \
                        else {"red": 0.1, "green": 0.2, "blue": 0.5}
                col_end = chr(ord("A") + len(headers) - 1)
                ws.format(f"A1:{col_end}1", {
                    "backgroundColor": color,
                    "textFormat": {"bold": True,
                                   "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                })
                ws.freeze(rows=1)
            except Exception:
                pass
            results[sheet_name] = f"新規作成（{len(headers)}列）"

    return {"ok": True, "sheets": results,
            "spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{sid}"}


# ─── タスク生成・LINE送信 ─────────────────────────────────

def _build_line_task_message(biz_key: str, date: str, tasks: list[dict]) -> str:
    """朝の LINE タスク通知メッセージを生成"""
    info = BUSINESS_TASKS[biz_key]
    biz_name = info["name"]
    weekday = ["月", "火", "水", "木", "金", "土", "日"][
        datetime.datetime.strptime(date, "%Y-%m-%d").weekday()
    ]
    date_label = f"{date}（{weekday}）"

    s_tasks = [t for t in tasks if t["売上直結度"] == "S"]
    a_tasks = [t for t in tasks if t["売上直結度"] == "A"]
    b_tasks = [t for t in tasks if t["売上直結度"] == "B"]

    lines = [
        f"【今日の売上直結タスク｜{biz_name}】",
        "",
        f"日付：{date_label}",
        f"今日の重点：{info['today_focus']}",
        f"目標：{info['daily_goal']}",
        "",
    ]

    if s_tasks:
        lines.append("S｜売上直結")
        for t in s_tasks:
            lines.append(f"{t['タスク番号']}. {t['タスク内容']}")
        lines.append("")

    if a_tasks:
        lines.append("A｜集客強化")
        for t in a_tasks:
            lines.append(f"{t['タスク番号']}. {t['タスク内容']}")
        lines.append("")

    if b_tasks:
        lines.append("B｜運営管理")
        for t in b_tasks:
            lines.append(f"{t['タスク番号']}. {t['タスク内容']}")
        lines.append("")

    lines += [
        "返信方法：",
        "完了したら「完了 1,2,3」と送ってください。",
        "全部終わったら「完了」と送ってください。",
        "",
        "例：",
        "完了 1,3",
        "口コミ3件完了",
        "写真完了",
    ]

    return "\n".join(lines)


def _generate_task_rows(biz_key: str, date: str) -> list[dict]:
    """事業キーと日付からタスク行データを生成"""
    info = BUSINESS_TASKS[biz_key]
    rows = []
    for cat, content, grade, priority in info["tasks"]:
        task_no = priority
        rows.append({
            "日付": date,
            "事業名": info["name"],
            "タスクID": _make_task_id(date, biz_key, task_no),
            "タスク番号": str(task_no),
            "タスクカテゴリ": cat,
            "タスク内容": content,
            "売上直結度": grade,
            "優先度": str(priority),
            "担当者": "",
            "ステータス": "未通知",
            "通知状況": "未通知",
            "通知日時": "",
            "完了日時": "",
            "完了返信内容": "",
            "LINEユーザーID": "",
            "メモ": "",
        })
    return rows


def send_daily_tasks(creds_path: str, ss_id: str = "",
                     businesses: list[str] | None = None,
                     dry_run: bool = False) -> dict:
    """
    当日タスクをシートに書き込み、各事業の LINE へ送信する。
    dry_run=True の場合は LINE 送信をスキップし通知文のみ返す。
    """
    sid = ss_id or _get_ss_id()
    date = _today()
    targets = businesses or ALL_BUSINESS_KEYS

    gc = _get_gc(creds_path)
    ss = gc.open_by_key(sid)

    try:
        ws = ss.worksheet(TASKS_SHEET)
    except gspread.WorksheetNotFound:
        setup_sheets(creds_path, sid)
        ws = ss.worksheet(TASKS_SHEET)

    # ─ 売上スクショ未報告事業を取得（Daily Action 自動注入用） ─
    sales_missing_keys = set()
    try:
        from core.sales_screenshot import missing_report
        miss = missing_report(sid, creds_path, date)
        sales_missing_keys = {m["biz_key"] for m in miss.get("missing_businesses", [])}
    except Exception as e:
        logger.warning(f"sales_screenshot missing_report skip: {e}")

    # ─ 財務・成長3システムの改善タスクを取得（事業別に注入用） ─
    # 統合SS(GOOGLE_SPREADSHEET_ID)から profit/review のアクションを1回ずつ取得し biz_key で配る
    finance_tasks_by_biz = {}
    fin_ss = os.getenv("GOOGLE_SPREADSHEET_ID", "") or sid
    for mod_name in ("profit_leak", "review_referral"):
        try:
            mod = __import__(f"core.{mod_name}", fromlist=["actions"])
            for t in mod.actions(fin_ss, creds_path).get("daily_action_tasks", []):
                bk = t.get("biz_key", "")
                if bk in BUSINESS_TASKS:   # staff事業のみ（owner宛は別途オーナー報告へ）
                    finance_tasks_by_biz.setdefault(bk, []).append(t)
        except Exception as e:
            logger.warning(f"{mod_name} actions skip: {e}")

    # ─ 集客・売上直結エンジンのタスク（MEO/失客復活/高粗利訴求）を取得 ─
    growth_tasks_by_biz = {}
    # MEO daily 対象事業（TACHINOMIYA/琉球火鍋）は専用の詳細MEOを使うため汎用gmapから除外
    meo_enabled = os.getenv("MEO_DAILY_ENABLED", "0") == "1"
    meo_biz_keys = {"tachinomiya", "ryukyu_hinabe"} if meo_enabled else set()
    try:
        from core.growth_engines import gmap_generate, revival_actions, offer_push
        growth_results = [
            gmap_generate(fin_ss, creds_path, dry_run=True),
            revival_actions(fin_ss, creds_path),
            offer_push(fin_ss, creds_path, dry_run=True),
        ]
        for gr in growth_results:
            for t in gr.get("daily_action_tasks", []):
                bk = t.get("biz_key", "")
                if bk in BUSINESS_TASKS and bk not in meo_biz_keys:
                    growth_tasks_by_biz.setdefault(bk, []).append(t)
    except Exception as e:
        logger.warning(f"growth_engines tasks skip: {e}")

    # ─ MEO daily（TACHINOMIYA/琉球火鍋・日英Google投稿/写真/口コミ/高粗利）─
    if meo_enabled:
        try:
            from core.growth_engines import meo_daily_assign
            for bk in ("tachinomiya", "ryukyu_hinabe"):
                res = meo_daily_assign(fin_ss, creds_path, bk, dry_run=False)
                for t in res.get("daily_action_tasks", []):
                    if t.get("biz_key") in BUSINESS_TASKS:
                        growth_tasks_by_biz.setdefault(t["biz_key"], []).append(t)
        except Exception as e:
            logger.warning(f"meo_daily_assign skip: {e}")

    results = {}
    for biz_key in targets:
        if biz_key not in BUSINESS_TASKS:
            results[biz_key] = {"ok": False, "error": "未知の事業キー"}
            continue

        # 当日・当事業の既存行を確認（重複防止）
        existing = ws.get_all_records()
        already = [r for r in existing
                   if str(r.get("日付","")).startswith(date)
                   and r.get("事業名","") == BUSINESS_TASKS[biz_key]["name"]]
        if already:
            results[biz_key] = {"ok": True, "status": "skip_already_sent",
                                 "rows": len(already)}
            continue

        # タスク行を生成・シートへ追記
        task_rows = _generate_task_rows(biz_key, date)

        # 売上スクショ未報告 → スクショ送信タスクを自動注入（優先度S）
        if biz_key in sales_missing_keys:
            task_rows.append({
                "日付": date,
                "事業名": BUSINESS_TASKS[biz_key]["name"],
                "タスクID": _make_task_id(date, biz_key, 30),
                "タスク番号": "30",
                "タスクカテゴリ": "売上報告",
                "タスク内容": "本日の売上スクショをLINE公式へ送信してください",
                "売上直結度": "S",
                "優先度": "30",
                "担当者": "",
                "ステータス": "未通知",
                "通知状況": "未通知",
                "通知日時": "",
                "完了日時": "",
                "完了返信内容": "",
                "LINEユーザーID": "",
                "メモ": "Daily Sales Screenshot OS 自動注入（未報告検知）",
            })

        # 利益改善・口コミ/紹介 → 財務成長3システムからのタスクを注入（最大3件）
        for n, t in enumerate(finance_tasks_by_biz.get(biz_key, [])[:3], start=31):
            task_rows.append({
                "日付": date,
                "事業名": BUSINESS_TASKS[biz_key]["name"],
                "タスクID": _make_task_id(date, biz_key, n),
                "タスク番号": str(n),
                "タスクカテゴリ": "利益/口コミ改善",
                "タスク内容": t.get("task", ""),
                "売上直結度": t.get("priority", "A"),
                "優先度": str(n),
                "担当者": "",
                "ステータス": "未通知",
                "通知状況": "未通知",
                "通知日時": "",
                "完了日時": "",
                "完了返信内容": "",
                "LINEユーザーID": "",
                "メモ": "Profit/Review Engine 自動注入",
            })

        # 集客・売上直結（MEO/失客復活/高粗利訴求）→ 各1件ずつ・最大3件
        _seen_cat = set()
        _g_added = 0
        for t in growth_tasks_by_biz.get(biz_key, []):
            cat = t.get("task", "")[:8]  # 種別の重複を避ける簡易キー
            if cat in _seen_cat or _g_added >= 4:
                continue
            _seen_cat.add(cat)
            num = 40 + _g_added
            task_rows.append({
                "日付": date,
                "事業名": BUSINESS_TASKS[biz_key]["name"],
                "タスクID": _make_task_id(date, biz_key, num),
                "タスク番号": str(num),
                "タスクカテゴリ": "集客/売上強化",
                "タスク内容": t.get("task", ""),
                "売上直結度": t.get("priority", "A"),
                "優先度": str(num),
                "担当者": "",
                "ステータス": "未通知",
                "通知状況": "未通知",
                "通知日時": "",
                "完了日時": "",
                "完了返信内容": "",
                "LINEユーザーID": "",
                "メモ": "Growth Engine 自動注入",
            })
            _g_added += 1

        # Beauty 売上危険 → 強化タスク自動追加
        if biz_key == "beauty":
            beauty_ss = os.getenv("BEAUTY_SPREADSHEET_ID") or os.getenv("GOOGLE_SPREADSHEET_ID", "")
            if beauty_ss:
                rate = _get_beauty_achievement_rate(creds_path, beauty_ss)
                if rate is not None and rate < BEAUTY_DANGER_THRESHOLD:
                    extra = BEAUTY_DANGER_TASKS_S[:]
                    if rate < BEAUTY_DANGER_THRESHOLD:
                        extra += BEAUTY_DANGER_TASKS_A
                    for cat, content, grade, priority in extra:
                        task_rows.append({
                            "日付": date,
                            "事業名": BUSINESS_TASKS["beauty"]["name"],
                            "タスクID": _make_task_id(date, "beauty", priority),
                            "タスク番号": str(priority),
                            "タスクカテゴリ": cat,
                            "タスク内容": content,
                            "売上直結度": grade,
                            "優先度": str(priority),
                            "担当者": "",
                            "ステータス": "未通知",
                            "通知状況": "未通知",
                            "通知日時": "",
                            "完了日時": "",
                            "完了返信内容": "",
                            "LINEユーザーID": "",
                            "メモ": f"売上危険アラート(達成率{round(rate*100,1)}%)",
                        })
                    # 30%未満はオーナーLINEへ追加通知
                    if rate < BEAUTY_CRITICAL_THRESHOLD and not dry_run:
                        owner_token = os.getenv(OWNER_LINE_TOKEN_ENV, "") or os.getenv("LINE_STAFF_TOKEN", "")
                        if owner_token:
                            alert_msg = (
                                f"【Beauty 売上危険アラート🚨】\n"
                                f"達成率 {round(rate*100,1)}%（重要度S）\n\n"
                                f"強化タスク{len(extra)}件を本日のDAC追加済み。\n"
                                f"早急な行動が必要です。"
                            )
                            _send_line(owner_token, alert_msg)

        now = _now_str()
        for row in task_rows:
            row["通知状況"] = "通知済み" if not dry_run else "dry_run"
            row["通知日時"] = now
            row["ステータス"] = "通知済み" if not dry_run else "dry_run"
        ws.append_rows(
            [[row[h] for h in TASKS_HEADERS] for row in task_rows],
            value_input_option="USER_ENTERED",
        )

        # LINE 送信
        token = os.getenv(BUSINESS_LINE_TOKEN_ENV.get(biz_key, ""), "")
        msg = _build_line_task_message(biz_key, date, task_rows)

        sent = False
        error = ""
        if not dry_run:
            if token:
                sent = _send_line(token, msg)
                if not sent:
                    error = "LINE送信失敗"
            else:
                error = f"{BUSINESS_LINE_TOKEN_ENV[biz_key]} 未設定"

        results[biz_key] = {
            "ok": True,
            "tasks": len(task_rows),
            "line_sent": sent,
            "dry_run": dry_run,
            "message_preview": msg[:200] + "...",
            "error": error,
        }

    _update_dashboard(ws, ss, sid, date)

    return {"ok": True, "date": date, "results": results,
            "spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{sid}"}


# ─── 17:00 リマインド ─────────────────────────────────────

def send_reminder(creds_path: str, ss_id: str = "",
                  businesses: list[str] | None = None,
                  dry_run: bool = False) -> dict:
    """未完了の S/A タスクを各事業 LINE へリマインド"""
    sid = ss_id or _get_ss_id()
    date = _today()
    targets = businesses or ALL_BUSINESS_KEYS

    gc = _get_gc(creds_path)
    ss = gc.open_by_key(sid)
    ws = ss.worksheet(TASKS_SHEET)
    all_rows = ws.get_all_records()

    results = {}
    for biz_key in targets:
        biz_name = BUSINESS_TASKS[biz_key]["name"]
        incomplete = [
            r for r in all_rows
            if str(r.get("日付","")).startswith(date)
            and r.get("事業名","") == biz_name
            and r.get("売上直結度","") in ("S", "A")
            and r.get("ステータス","") not in ("完了", "見送り")
        ]
        if not incomplete:
            results[biz_key] = {"ok": True, "status": "all_complete", "reminded": 0}
            continue

        lines = [
            f"【未完了リマインド｜{biz_name}】",
            "",
            "売上に直結する未完了タスクがあります。",
            "",
            "未完了：",
        ]
        for r in incomplete:
            grade = r.get("売上直結度","")
            lines.append(f"{r.get('タスク番号','?')}. {r.get('タスク内容','')} [{grade}]")
        lines += [
            "",
            "完了したら「完了 1,3」のように返信してください。",
        ]
        msg = "\n".join(lines)

        token = os.getenv(BUSINESS_LINE_TOKEN_ENV.get(biz_key, ""), "")
        sent = False
        error = ""
        if not dry_run:
            if token:
                sent = _send_line(token, msg)
                if not sent:
                    error = "LINE送信失敗"
            else:
                error = f"{BUSINESS_LINE_TOKEN_ENV[biz_key]} 未設定"

        results[biz_key] = {
            "ok": True,
            "incomplete_tasks": len(incomplete),
            "line_sent": sent,
            "dry_run": dry_run,
            "message_preview": msg[:300],
            "error": error,
        }

    return {"ok": True, "date": date, "results": results}


# ─── 21:00 オーナー報告 ───────────────────────────────────

def send_owner_report(creds_path: str, ss_id: str = "",
                      owner_line_token: str = "",
                      dry_run: bool = False) -> dict:
    """全事業の完了率をオーナー LINE へ報告"""
    sid = ss_id or _get_ss_id()
    date = _today()

    gc = _get_gc(creds_path)
    ss = gc.open_by_key(sid)
    ws = ss.worksheet(TASKS_SHEET)
    all_rows = ws.get_all_records()
    today_rows = [r for r in all_rows if str(r.get("日付","")).startswith(date)]

    report_parts = ["【本日の実行状況】", ""]
    tomorrow_focus = []

    for biz_key in ALL_BUSINESS_KEYS:
        biz_name = BUSINESS_TASKS[biz_key]["name"]
        biz_rows = [r for r in today_rows if r.get("事業名","") == biz_name]
        if not biz_rows:
            report_parts.append(f"{biz_name}：データなし")
            report_parts.append("")
            continue

        s_rows = [r for r in biz_rows if r.get("売上直結度","") == "S"]
        s_done = [r for r in s_rows if r.get("ステータス","") == "完了"]
        s_rate = int(len(s_done) / len(s_rows) * 100) if s_rows else 0

        incomplete_s = [r for r in s_rows if r.get("ステータス","") not in ("完了","見送り")]

        report_parts.append(f"{biz_name}：")
        report_parts.append(f"Sタスク完了率：{s_rate}%")
        if incomplete_s:
            report_parts.append("未完了：" + "、".join(
                r.get("タスク内容","")[:15] for r in incomplete_s
            ))
            for r in incomplete_s:
                tomorrow_focus.append(f"・{biz_name}：{r.get('タスク内容','')[:20]}")
        report_parts.append("")

    if tomorrow_focus:
        report_parts.append("明日の重点：")
        report_parts.extend(tomorrow_focus[:5])

    msg = "\n".join(report_parts)

    token = owner_line_token or os.getenv(OWNER_LINE_TOKEN_ENV, "") \
            or os.getenv("LINE_STAFF_TOKEN", "")
    sent = False
    error = ""
    if not dry_run:
        if token:
            sent = _send_line(token, msg)
            if not sent:
                error = "LINE送信失敗"
        else:
            error = "オーナーLINEトークン未設定"

    return {"ok": True, "date": date, "line_sent": sent,
            "dry_run": dry_run, "report": msg, "error": error}


# ─── ステータス取得 ───────────────────────────────────────

def get_status(creds_path: str, ss_id: str = "", date: str = "") -> dict:
    """当日の事業別タスク状況を返す"""
    sid = ss_id or _get_ss_id()
    target_date = date or _today()

    gc = _get_gc(creds_path)
    ss = gc.open_by_key(sid)
    ws = ss.worksheet(TASKS_SHEET)
    all_rows = ws.get_all_records()
    today_rows = [r for r in all_rows if str(r.get("日付","")).startswith(target_date)]

    summary = {}
    for biz_key in ALL_BUSINESS_KEYS:
        biz_name = BUSINESS_TASKS[biz_key]["name"]
        biz_rows = [r for r in today_rows if r.get("事業名","") == biz_name]
        if not biz_rows:
            summary[biz_key] = {"name": biz_name, "tasks": 0}
            continue

        done   = [r for r in biz_rows if r.get("ステータス","") == "完了"]
        s_rows = [r for r in biz_rows if r.get("売上直結度","") == "S"]
        s_done = [r for r in s_rows   if r.get("ステータス","") == "完了"]

        summary[biz_key] = {
            "name": biz_name,
            "total": len(biz_rows),
            "complete": len(done),
            "incomplete": len(biz_rows) - len(done),
            "s_total": len(s_rows),
            "s_complete": len(s_done),
            "s_rate": f"{int(len(s_done)/len(s_rows)*100)}%" if s_rows else "N/A",
            "incomplete_tasks": [
                {"no": r.get("タスク番号",""), "content": r.get("タスク内容",""),
                 "grade": r.get("売上直結度","")}
                for r in biz_rows if r.get("ステータス","") not in ("完了","見送り")
            ],
        }

    return {"ok": True, "date": target_date, "summary": summary,
            "spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{sid}"}


# ─── LINE 返信パーサー ────────────────────────────────────

# キーワード → タスク内容の部分マッチ候補
_KEYWORD_TASK_MAP = [
    (r"口コミ|クチコミ",          "口コミ"),
    (r"google|Google|グーグル|投稿", "Google投稿"),  # 注意: Threads/Instagram と区別
    (r"instagram|インスタ|スト[ーーリ]",  "Instagramストーリー"),
    (r"threads|スレッズ",          "Threads投稿"),
    (r"写真|撮影",                "写真"),
    (r"dm|DM|営業",               "営業DM"),
    (r"問い合わせ|問合|問合せ",   "問い合わせ"),
    (r"メニュー|声かけ",          "メニュー"),
    (r"予約",                     "予約"),
    (r"売上|売り上げ",            "売上"),
    (r"案件|進捗",                "案件"),
    (r"hot.?pepper|ホットペッパー|hpb|HPB", "Hot Pepper"),
    (r"夜|ナイト|night",          "夜の集客"),
    (r"実績|過去",                "実績写真"),
    (r"個室|記念日|女子会",       "個室"),
    (r"火鍋|しゃぶしゃぶ|アグー|黒毛", "写真撮影"),
]


def parse_completion_reply(text: str, task_rows: list[dict]) -> dict:
    """
    LINE 返信テキストから完了タスクを解析する。

    Returns:
        {
          "type": "all" | "partial" | "dismiss" | "confirm" | "unknown",
          "completed_numbers": [1, 2, 3],  # タスク番号
          "completed_tasks": [...],         # 該当タスク行
          "needs_confirm": bool,
          "confirm_message": str,
        }
    """
    t = text.strip()
    t_lower = t.lower()

    # ─ 全完了パターン ─
    ALL_COMPLETE = [
        "完了", "全部完了", "全て完了", "すべて完了",
        "おわり", "終わりました", "終わり", "全完了", "全部できました",
    ]
    if t in ALL_COMPLETE or t_lower in [s.lower() for s in ALL_COMPLETE]:
        return {
            "type": "all",
            "completed_numbers": [int(r["タスク番号"]) for r in task_rows],
            "completed_tasks": task_rows,
            "needs_confirm": False,
            "confirm_message": "",
        }

    # ─ 未完了・見送り ─
    DISMISS_PATTERNS = [
        r"できません", r"未完了", r"見送り", r"今日は無理", r"明日にします",
        r"できない", r"無理", r"スキップ",
    ]
    if any(re.search(p, t) for p in DISMISS_PATTERNS):
        return {"type": "dismiss", "completed_numbers": [], "completed_tasks": [],
                "needs_confirm": False, "confirm_message": ""}

    # ─ 確認・相談 ─
    CONFIRM_PATTERNS = [r"わからない", r"どれ[？?]?$", r"確認お願い", r"できない理由"]
    if any(re.search(p, t) for p in CONFIRM_PATTERNS):
        return {
            "type": "confirm",
            "completed_numbers": [],
            "completed_tasks": [],
            "needs_confirm": True,
            "confirm_message": "どのタスクが完了しましたか？「完了 1,2」の形式で返信してください。",
        }

    # ─ 番号指定パターン（「完了 1,2,3」「1,2完了」「完了1」等） ─
    number_matches = re.findall(r"(\d+)", t)
    nums_from_text = [int(n) for n in number_matches if 1 <= int(n) <= 20]

    if re.search(r"完了|できました|やりました|やった|済み|ok|OK|○|◯", t) and nums_from_text:
        matched = [r for r in task_rows if int(r["タスク番号"]) in nums_from_text]
        return {
            "type": "partial",
            "completed_numbers": nums_from_text,
            "completed_tasks": matched,
            "needs_confirm": False,
            "confirm_message": "",
        }

    # ─ キーワードパターン（「口コミ完了」「写真撮影完了」等） ─
    keyword_matched = []
    for pattern, hint in _KEYWORD_TASK_MAP:
        if re.search(pattern, t, re.IGNORECASE):
            for row in task_rows:
                if hint.lower() in row["タスク内容"].lower():
                    if row not in keyword_matched:
                        keyword_matched.append(row)

    if keyword_matched:
        return {
            "type": "partial",
            "completed_numbers": [int(r["タスク番号"]) for r in keyword_matched],
            "completed_tasks": keyword_matched,
            "needs_confirm": False,
            "confirm_message": "",
        }

    # ─ 不明 ─
    return {
        "type": "unknown",
        "completed_numbers": [],
        "completed_tasks": [],
        "needs_confirm": True,
        "confirm_message": "どのタスクが完了しましたか？「完了 1,2」の形式で返信してください。",
    }


def process_line_reply(
    reply_text: str,
    line_user_id: str,
    biz_key: str,
    creds_path: str,
    ss_id: str = "",
    reply_token: str = "",
) -> dict:
    """
    LINE 返信を受けてタスク完了を処理し、シートを更新する。

    Args:
        reply_text:   スタッフからの返信テキスト
        line_user_id: LINE ユーザー ID
        biz_key:      事業キー (tachinomiya / catering / beauty / ryukyu_hinabe)
        creds_path:   サービスアカウント JSON パス
        ss_id:        スプレッドシート ID
        reply_token:  LINE reply token（確認メッセージ返信用）
    """
    sid = ss_id or _get_ss_id()
    date = _today()

    # ─ 売上スクショの「OK」/「修正」コマンドを優先判定 ─
    # 該当する確認待ち行があれば Daily Sales Screenshot OS 側で処理する。
    try:
        from core.sales_screenshot import maybe_handle_text_reply
        sales_dry = os.getenv("SALES_SCREENSHOT_DRY_RUN", "1") != "0"
        # 売上スクショの台帳は統合SS(YU CEO Dashboard)にあるため GOOGLE_SPREADSHEET_ID を優先
        sales_ss = os.getenv("GOOGLE_SPREADSHEET_ID", "") or sid
        sales_res = maybe_handle_text_reply(
            reply_text=reply_text, biz_key=biz_key, creds_path=creds_path,
            ss_id=sales_ss, reply_token=reply_token, dry_run=sales_dry,
        )
        if sales_res.get("handled"):
            return {"ok": True, "routed_to": "sales_screenshot", **sales_res}
    except Exception as e:
        logger.warning(f"sales_screenshot ルーティングskip: {e}")

    # ─ オーナー返信コマンド（OK/修正/除外/完了/再生成 N）→ SNS_REUSE_ACTIONS ─
    try:
        from core.owner_daily import is_owner_cmd, handle_owner_reply
        if is_owner_cmd(reply_text):
            meo_ss = os.getenv("GOOGLE_SPREADSHEET_ID", "") or sid
            r = handle_owner_reply(creds_path, meo_ss, reply_text, reply_token=reply_token)
            if r.get("ok"):
                return {"ok": True, "routed_to": "owner_reuse_cmd", **r}
    except Exception as e:
        logger.warning(f"owner cmd routing skip: {e}")

    # ─ GBP実績入力（「GBP 電話5 ルート12 予約2 来店8」）→ MEO_GBP_STATS ─
    try:
        from core.growth_engines import is_gbp_message, record_gbp
        if is_gbp_message(reply_text):
            meo_ss = os.getenv("GOOGLE_SPREADSHEET_ID", "") or sid
            biz_name = BUSINESS_TASKS.get(biz_key, {}).get("name", "")
            r = record_gbp(meo_ss, creds_path, reply_text, business_name=biz_name)
            if r.get("ok"):
                token = os.getenv(BUSINESS_LINE_TOKEN_ENV.get(biz_key, ""), "")
                if reply_token and token and r.get("reply"):
                    _send_line_reply(reply_token, r["reply"], token)
                return {"ok": True, "routed_to": "gbp_stats", **r}
    except Exception as e:
        logger.warning(f"gbp routing skip: {e}")

    # ─ SNS追記数値（「売上3200 来店2」等）→ 直近スクショ結果へ追記 ─
    try:
        from core.sns_pdca import is_followup_numbers, apply_followup_numbers
        if is_followup_numbers(reply_text):
            sns_ss = os.getenv("GOOGLE_SPREADSHEET_ID", "") or sid
            biz_name = BUSINESS_TASKS.get(biz_key, {}).get("name", "")
            r = apply_followup_numbers(sns_ss, creds_path, reply_text, business_name=biz_name)
            if r.get("ok"):
                token = os.getenv(BUSINESS_LINE_TOKEN_ENV.get(biz_key, ""), "")
                if reply_token and token and r.get("reply"):
                    _send_line_reply(reply_token, r["reply"], token)
                return {"ok": True, "routed_to": "sns_followup", **r}
    except Exception as e:
        logger.warning(f"sns_followup ルーティングskip: {e}")

    # ─ SNS投稿結果（投稿文＋反応）の記録ルーティング ─
    try:
        from core.sns_pdca import is_sns_result_message, record_sns_result
        if is_sns_result_message(reply_text):
            sns_ss = os.getenv("GOOGLE_SPREADSHEET_ID", "") or sid
            biz_name = BUSINESS_TASKS.get(biz_key, {}).get("name", "")
            r = record_sns_result(sns_ss, creds_path, reply_text, business_name=biz_name)
            # 返信
            if reply_token and r.get("reply"):
                token = os.getenv(BUSINESS_LINE_TOKEN_ENV.get(biz_key, ""), "")
                if token:
                    _send_line_reply(reply_token, r["reply"], token)
            return {"ok": True, "routed_to": "sns_result", **{k: v for k, v in r.items() if k != "parsed"}}
    except Exception as e:
        logger.warning(f"sns_result ルーティングskip: {e}")

    gc = _get_gc(creds_path)
    ss = gc.open_by_key(sid)
    ws = ss.worksheet(TASKS_SHEET)
    all_vals = ws.get_all_values()
    if len(all_vals) < 2:
        return {"ok": False, "error": "シートデータなし"}

    header = all_vals[0]
    biz_name = BUSINESS_TASKS.get(biz_key, {}).get("name", "")

    def col(name):
        return header.index(name) if name in header else None

    # 当日・当事業の未完了タスク行を取得
    task_rows_raw = []
    for row_idx, row in enumerate(all_vals[1:], start=2):
        def cell(h):
            i = col(h)
            return row[i].strip() if i is not None and i < len(row) else ""
        if cell("日付") == date and cell("事業名") == biz_name \
                and cell("ステータス") not in ("完了", "見送り"):
            task_rows_raw.append({h: cell(h) for h in TASKS_HEADERS} | {"_row": row_idx})

    if not task_rows_raw:
        return {"ok": True, "status": "no_pending_tasks", "business": biz_key}

    # 返信を解析
    parsed = parse_completion_reply(reply_text, task_rows_raw)
    now = _now_str()
    updated_count = 0

    if parsed["type"] in ("all", "partial"):
        completed_rows = parsed["completed_tasks"]
        for row_data in completed_rows:
            row_num = row_data["_row"]
            # シートの各列を更新
            updates = []
            for field, value in [
                ("ステータス",      "完了"),
                ("完了日時",        now),
                ("完了返信内容",    reply_text[:100]),
                ("LINEユーザーID",  line_user_id),
            ]:
                c = col(field)
                if c is not None:
                    updates.append({"range": f"{chr(65+c)}{row_num}", "values": [[value]]})
            if updates:
                ws.batch_update(updates)
            updated_count += 1

    elif parsed["type"] == "dismiss":
        for row_data in task_rows_raw:
            row_num = row_data["_row"]
            c = col("ステータス")
            if c is not None:
                ws.update_cell(row_num, c + 1, "見送り")

    # ダッシュボード更新
    _update_dashboard(ws, ss, sid, date)

    # LINE 確認返信
    confirm_msg = ""
    if parsed["type"] == "all":
        confirm_msg = f"✅ {biz_name}の全タスク完了を記録しました！お疲れ様でした。"
    elif parsed["type"] == "partial":
        nums = ",".join(str(n) for n in parsed["completed_numbers"])
        confirm_msg = f"✅ タスク {nums} の完了を記録しました。\n残りのタスクもよろしくお願いします！"
    elif parsed["type"] == "dismiss":
        confirm_msg = "了解しました。本日は見送りで記録しました。"
    elif parsed.get("needs_confirm"):
        confirm_msg = parsed["confirm_message"]

    if confirm_msg and reply_token:
        token_env_key = BUSINESS_LINE_TOKEN_ENV.get(biz_key, "")
        access_token = os.getenv(token_env_key, "")
        _send_line_reply(reply_token, confirm_msg, access_token)

    return {
        "ok": True,
        "type": parsed["type"],
        "completed": updated_count,
        "business": biz_key,
        "confirm_message": confirm_msg,
    }


# ─── スタッフ LINE マップ ─────────────────────────────────

def _load_staff_map(ss: gspread.Spreadsheet) -> dict[str, str]:
    """STAFF_LINE_MAP シートを読み込み {user_id: biz_key} を返す（5分キャッシュ）"""
    import time
    now = time.time()
    if now - _staff_map_cache["updated"] < 300 and _staff_map_cache["data"]:
        return _staff_map_cache["data"]

    result: dict[str, str] = {}
    try:
        ws = ss.worksheet(STAFF_MAP_SHEET)
        rows = ws.get_all_records()
        biz_name_to_key = {info["name"]: key for key, info in BUSINESS_TASKS.items()}
        for row in rows:
            uid  = str(row.get("LINE_USER_ID", "")).strip()
            biz  = str(row.get("事業名", "")).strip()
            valid = str(row.get("有効", "TRUE")).strip().upper()
            if uid and biz and valid == "TRUE":
                biz_key = biz_name_to_key.get(biz, "")
                if not biz_key:
                    # biz_key 直接指定も許容（tachinomiya / catering 等）
                    biz_key = biz if biz in BUSINESS_TASKS else ""
                if biz_key:
                    result[uid] = biz_key
    except gspread.WorksheetNotFound:
        pass
    except Exception as e:
        logger.warning(f"staff_map 読み込みエラー: {e}")

    _staff_map_cache["data"] = result
    _staff_map_cache["updated"] = now
    return result


def get_business_from_user_id(user_id: str, ss: gspread.Spreadsheet) -> str | None:
    """LINE User ID から business_key を返す。未登録の場合は None。"""
    staff_map = _load_staff_map(ss)
    return staff_map.get(user_id)


def register_staff(
    user_id: str,
    biz_key: str,
    staff_name: str,
    creds_path: str,
    ss_id: str = "",
) -> dict:
    """スタッフの LINE User ID を STAFF_LINE_MAP に登録する"""
    if biz_key not in BUSINESS_TASKS:
        return {"ok": False, "error": f"未知の事業キー: {biz_key}"}

    sid = ss_id or _get_ss_id()
    gc  = _get_gc(creds_path)
    ss  = gc.open_by_key(sid)

    try:
        ws = ss.worksheet(STAFF_MAP_SHEET)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=STAFF_MAP_SHEET, rows=200, cols=5)
        ws.update([STAFF_MAP_HEADERS], "A1")

    rows = ws.get_all_records()
    # 既存レコードを確認
    for i, row in enumerate(rows, start=2):
        if str(row.get("LINE_USER_ID", "")).strip() == user_id:
            # 上書き更新
            ws.update(f"A{i}:E{i}", [[
                user_id,
                BUSINESS_TASKS[biz_key]["name"],
                staff_name,
                _now_str(),
                "TRUE",
            ]])
            _staff_map_cache["updated"] = 0  # キャッシュ無効化
            return {"ok": True, "action": "updated", "user_id": user_id,
                    "biz_key": biz_key, "name": staff_name}

    ws.append_rows([[
        user_id,
        BUSINESS_TASKS[biz_key]["name"],
        staff_name,
        _now_str(),
        "TRUE",
    ]])
    _staff_map_cache["updated"] = 0
    return {"ok": True, "action": "registered", "user_id": user_id,
            "biz_key": biz_key, "name": staff_name}


def list_staff(creds_path: str, ss_id: str = "") -> dict:
    """STAFF_LINE_MAP の登録スタッフ一覧を返す"""
    sid = ss_id or _get_ss_id()
    gc  = _get_gc(creds_path)
    ss  = gc.open_by_key(sid)
    try:
        ws   = ss.worksheet(STAFF_MAP_SHEET)
        rows = ws.get_all_records()
        return {"ok": True, "count": len(rows), "staff": rows}
    except gspread.WorksheetNotFound:
        return {"ok": True, "count": 0, "staff": [],
                "note": "STAFF_LINE_MAP シートが未作成。/daily-action-setup を実行してください。"}


# ─── LINE Webhook ハンドラ ────────────────────────────────

def get_business_from_destination(destination: str) -> str | None:
    """LINE destination (公式アカウントのUID) から business_key を取得"""
    for biz_key in ALL_BUSINESS_KEYS:
        env_key = BUSINESS_DESTINATION_ENV.get(biz_key, "")
        dest = os.getenv(env_key, "")
        if dest and dest == destination:
            return biz_key
    return None


def verify_line_signature(body: bytes, signature: str, channel_secret: str) -> bool:
    """LINE Webhook の署名を検証する"""
    expected = hmac.new(
        channel_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    return hmac.compare_digest(
        base64.b64encode(expected).decode("utf-8"),
        signature,
    )


def handle_webhook_event(event: dict, destination: str,
                         creds_path: str, ss_id: str = "",
                         verified_biz_key: str = "") -> dict:
    """
    LINE Webhook のイベント1件を処理する。
    事業の特定順序：
      1. verified_biz_key（署名検証で特定済みのチャンネル）
      2. destination 環境変数との一致（各事業が別LINEアカウントの場合）
      3. STAFF_LINE_MAP シートの User ID マッピング（共有LINEアカウントの場合）
      4. どちらも不明 → 登録案内メッセージを返信
    """
    if event.get("type") != "message":
        return {"ok": True, "status": "skip_non_message"}
    if event.get("message", {}).get("type") != "text":
        return {"ok": True, "status": "skip_non_text"}

    text        = event["message"].get("text", "").strip()
    user_id     = event.get("source", {}).get("userId", "")
    reply_token = event.get("replyToken", "")
    sid         = ss_id or _get_ss_id()

    # 1. 署名検証で特定済みのチャンネル（最優先）
    biz_key = verified_biz_key or ""
    logger.info(f"Webhook: verified={verified_biz_key or 'unknown'} text={text!r}")

    # 2. destination で事業を特定（verified_biz_key が複数チャンネル共有の場合の補完）
    if not biz_key:
        biz_key = get_business_from_destination(destination)

    # 3. destination が重複/未設定 → User ID で再検索
    if not biz_key:
        gc  = _get_gc(creds_path)
        ss  = gc.open_by_key(sid)
        biz_key = get_business_from_user_id(user_id, ss)

    # 4. それでも不明 → 登録案内
    if not biz_key:
        logger.warning(f"Webhook: user_id='{user_id}' が STAFF_LINE_MAP 未登録")
        guide = (
            f"【スタッフ登録が必要です】\n\n"
            f"あなたのIDをオーナーに伝えてください：\n{user_id}\n\n"
            f"オーナーが /staff-line-register で登録後、再度「完了」と返信してください。"
        )
        # verified_biz_key があればそのチャンネルのトークンを優先使用
        # なければ全チャンネルを試行（reply_tokenはチャンネル固有のため）
        guide_sent = False
        candidate_keys = (
            [verified_biz_key] if verified_biz_key
            else list(BUSINESS_LINE_TOKEN_ENV.keys())
        )
        for bk in candidate_keys:
            token = os.getenv(BUSINESS_LINE_TOKEN_ENV.get(bk, ""), "")
            if token and _send_line_reply(reply_token, guide, token):
                guide_sent = True
                logger.info(f"Webhook: 登録ガイド送信成功 biz={bk} user={user_id}")
                break
        if not guide_sent:
            logger.warning(f"Webhook: 登録ガイド送信失敗 user={user_id}")
        return {"ok": False, "error": "user_id未登録",
                "user_id": user_id, "guide_sent": guide_sent}

    return process_line_reply(
        reply_text=text,
        line_user_id=user_id,
        biz_key=biz_key,
        creds_path=creds_path,
        ss_id=sid,
        reply_token=reply_token,
    )


# ─── ダッシュボード更新 ───────────────────────────────────

def _update_dashboard(tasks_ws: gspread.Worksheet,
                      ss: gspread.Spreadsheet,
                      sid: str,
                      date: str) -> None:
    """DAILY_ACTION_DASHBOARD シートを当日データで更新"""
    try:
        dash_ws = ss.worksheet(DASH_SHEET)
    except gspread.WorksheetNotFound:
        return

    all_rows = tasks_ws.get_all_records()
    today_rows = [r for r in all_rows if str(r.get("日付","")).startswith(date)]

    dash_rows = []
    for biz_key in ALL_BUSINESS_KEYS:
        biz_name = BUSINESS_TASKS[biz_key]["name"]
        biz_rows = [r for r in today_rows if r.get("事業名","") == biz_name]
        if not biz_rows:
            continue

        done   = [r for r in biz_rows if r.get("ステータス","") == "完了"]
        s_rows = [r for r in biz_rows if r.get("売上直結度","") == "S"]
        a_rows = [r for r in biz_rows if r.get("売上直結度","") == "A"]
        s_done = [r for r in s_rows if r.get("ステータス","") == "完了"]
        a_done = [r for r in a_rows if r.get("ステータス","") == "完了"]

        s_rate = f"{int(len(s_done)/len(s_rows)*100)}%" if s_rows else "N/A"
        a_rate = f"{int(len(a_done)/len(a_rows)*100)}%" if a_rows else "N/A"

        incomplete_s = [r for r in s_rows
                        if r.get("ステータス","") not in ("完了","見送り")]
        incomplete_sa = [r for r in biz_rows
                         if r.get("売上直結度","") in ("S","A")
                         and r.get("ステータス","") not in ("完了","見送り")]

        dash_rows.append([
            date,
            biz_name,
            str(len(biz_rows)),
            str(len(done)),
            str(len(biz_rows) - len(done)),
            s_rate,
            a_rate,
            "、".join(r.get("タスク内容","")[:12] for r in incomplete_s),
            "あり" if incomplete_sa else "なし",
            "要確認" if len(incomplete_s) >= 2 else "",
            _now_str(),
        ])

    # 当日分を全クリアして書き直す
    existing = dash_ws.get_all_values()
    header = existing[0] if existing else DASH_HEADERS
    other_rows = [r for r in existing[1:] if not str(r[0]).startswith(date)]

    dash_ws.clear()
    dash_ws.update([header] + other_rows + dash_rows, "A1")


# ─── LINE ユーティリティ ─────────────────────────────────

def _send_line(token: str, message: str) -> bool:
    """LINE Broadcast 送信"""
    if not token:
        return False
    try:
        resp = requests.post(
            "https://api.line.me/v2/bot/message/broadcast",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json={"messages": [{"type": "text", "text": message}]},
            timeout=10,
        )
        return resp.ok
    except Exception:
        return False


def _send_line_reply(reply_token: str, message: str, access_token: str = "") -> bool:
    """LINE Reply 送信（Webhook への返信）"""
    if not reply_token or not access_token:
        return False
    try:
        resp = requests.post(
            "https://api.line.me/v2/bot/message/reply",
            headers={"Authorization": f"Bearer {access_token}",
                     "Content-Type": "application/json"},
            json={"replyToken": reply_token,
                  "messages": [{"type": "text", "text": message}]},
            timeout=10,
        )
        if not resp.ok:
            logger.warning(f"LINE reply failed: status={resp.status_code} body={resp.text[:200]}")
        return resp.ok
    except Exception as e:
        logger.warning(f"LINE reply exception: {e}")
        return False


# ─── テスト用 ─────────────────────────────────────────────

def run_test(creds_path: str, ss_id: str = "") -> dict:
    """
    dry_run モードでテストを実行する。
    1. シート作成確認
    2. TACHINOMIYA のタスク生成・通知文生成
    3. 返信パーサーのテスト（全完了・番号指定・キーワード指定）
    4. リマインド文生成
    5. オーナー報告文生成
    LINE 本番送信は行わない。
    """
    results = {}

    # 1. シート作成
    setup_result = setup_sheets(creds_path, ss_id)
    results["setup"] = setup_result

    # 2. 全事業タスク生成（dry_run: LINEは送信しないがシートには書き込む）
    send_result = send_daily_tasks(creds_path, ss_id,
                                   businesses=None, dry_run=True)
    results["send_dry_run"] = send_result

    # 3. 返信パーサーテスト（シート未使用のダミー行）
    dummy_tasks = [
        {"タスク番号": str(i+1), "タスク内容": c, "売上直結度": g, "_row": i+2}
        for i, (_, c, g, _p) in enumerate(BUSINESS_TASKS["tachinomiya"]["tasks"])
    ]
    parser_tests = {
        "全完了「完了」":          parse_completion_reply("完了",        dummy_tasks),
        "番号指定「完了 1,2」":    parse_completion_reply("完了 1,2",    dummy_tasks),
        "キーワード「口コミ完了」": parse_completion_reply("口コミ完了",  dummy_tasks),
        "キーワード「写真撮影完了」":parse_completion_reply("写真撮影完了",dummy_tasks),
        "未完了「できません」":    parse_completion_reply("できません",  dummy_tasks),
        "曖昧「わからない」":      parse_completion_reply("わからない",  dummy_tasks),
    }
    results["parser_tests"] = {
        k: {"type": v["type"], "completed_numbers": v["completed_numbers"],
            "needs_confirm": v.get("needs_confirm", False)}
        for k, v in parser_tests.items()
    }

    # 4. リマインド文生成（dry_run）
    remind_result = send_reminder(creds_path, ss_id,
                                  businesses=["tachinomiya"], dry_run=True)
    results["remind_dry_run"] = remind_result

    # 5. オーナー報告文生成（dry_run）
    owner_result = send_owner_report(creds_path, ss_id, dry_run=True)
    results["owner_report_dry_run"] = {
        "report_preview": owner_result.get("report","")[:400],
        "ok": owner_result.get("ok"),
    }

    return {"ok": True, "test_results": results}


def simulate_webhook(
    biz_key: str,
    reply_text: str,
    creds_path: str,
    ss_id: str = "",
    user_id: str = "TEST_USER_001",
) -> dict:
    """
    LINE Webhook の疑似テスト。
    destination/署名検証をバイパスし biz_key を直接指定する。
    本番 Webhook 設定前の動作確認専用。
    """
    if biz_key not in BUSINESS_TASKS:
        return {"ok": False, "error": f"未知の事業キー: {biz_key}"}

    return process_line_reply(
        reply_text=reply_text,
        line_user_id=user_id,
        biz_key=biz_key,
        creds_path=creds_path,
        ss_id=ss_id,
        reply_token="",  # 疑似テストなので返信なし
    )
