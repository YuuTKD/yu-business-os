"""
AI営業本部 — Lead Command Center
------------------------------------
全事業のリード（Threads・Instagram DM・LINE・Google・その他）を
統合管理し、AI優先度判定・返信案生成・LINE通知・Knowledge OS保存を行う。

安全設計:
  - LINE本番送信: DRY_RUN=True のときは通知文字列生成のみ
  - Threads/Instagram: 自動返信しない（返信案の生成のみ）
  - 秘密情報をMarkdownに絶対出力しない
"""

import os
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials
from google.cloud import storage as gcs_storage

JST = timezone(timedelta(hours=9))
GCS_BUCKET  = "tree-beauty-blog-images"
GCS_PREFIX  = "knowledge-os"
GCS_PROJECT = "tree-beauty-ai-499303"


# ── シート定義 ─────────────────────────────────────────────
LEAD_SHEETS = {
    "LEAD_MASTER": [
        "登録日時", "入力元", "事業名", "見込み客名", "会社名", "連絡先",
        "投稿URL", "問い合わせ本文", "検知キーワード", "AI要約", "推定ニーズ",
        "推定売上", "緊急度", "関連性スコア", "優先度", "推奨対応", "返信案",
        "担当者", "通知先LINE", "通知状況", "対応状況", "次回フォロー日時",
        "完了日時", "結果", "実売上", "メモ", "エラー内容", "Obsidian Path",
    ],
    "LEAD_ACTION_LOG": [
        "日時", "リードID", "事業名", "対応内容", "担当者", "結果",
        "次回アクション", "フォロー予定日", "売上見込み変化", "メモ",
    ],
    "LEAD_DASHBOARD": [
        "日付", "事業名", "Sリード数", "Aリード数", "未対応数",
        "推定売上合計", "本日対応期限", "オーナー確認必要", "最終更新日時",
    ],
}

# ── 事業検知キーワード ────────────────────────────────────
BIZ_KEYWORDS = {
    "TACHINOMIYA": [
        "国際通り", "今からご飯", "夜ご飯", "1人飲み", "沖縄料理", "サーターアンダギー",
        "観光中", "立飲み", "泡盛", "夜遊び", "1人でも", "今夜", "夜営業",
    ],
    "Trees Catering": [
        "企業イベント", "懇親会", "周年", "ホテル", "パーティー", "ケータリング",
        "宴会", "団体", "20名", "30名", "50名", "結婚式", "二次会",
        "法人", "ランチ会", "食事会", "予算あり", "見積", "日程",
    ],
    "Tree Beauty": [
        "脱毛", "よもぎ蒸し", "ホワイトニング", "カッピング", "予約したい",
        "空きありますか", "今日行けますか", "美容", "エステ", "サロン", "ムダ毛", "毛穴",
    ],
    "琉球火鍋": [
        "個室", "記念日", "女子会", "会食", "しゃぶしゃぶ", "火鍋", "鍋",
        "沖縄しゃぶ", "宴会", "誕生日", "接待", "グループ", "4名", "6名", "8名",
    ],
    "コンサル": [
        "売上を上げたい", "集客に困っている", "飲食店オーナー", "美容サロンオーナー",
        "成果報酬", "コンサル", "マーケティング", "Instagram", "SNS運用",
        "Google", "集客相談", "LINE集客", "MEO",
    ],
}

EXCLUDE_KEYWORDS = [
    "フォローありがとう", "フォローお願い", "フォロバ", "相互フォロー",
    "保存しました", "素敵ですね", "いいね", "よかったです", "応援してます",
    "スパム", "業者", "副業", "投資", "稼げる",
]

# ── 返信案テンプレート ─────────────────────────────────────
_REPLY_TEMPLATES = {
    "TACHINOMIYA": (
        "こんにちは！TACHINOMIYA(立呑み屋)です😊\n"
        "国際通りから徒歩1分、沖縄料理と泡盛が自慢のお店です。\n"
        "ぜひお気軽にお越しください！本日も営業中です🍶"
    ),
    "Trees Catering": (
        "お問い合わせありがとうございます！TREE's Cateringです🍽️\n"
        "ご人数・日程・ご予算をお教えいただければ、お見積りをご用意いたします。\n"
        "どうぞお気軽にご相談ください！"
    ),
    "Tree Beauty": (
        "こんにちは！Tree Beautyです✨\n"
        "ご予約・ご相談いつでも承っております。\n"
        "空き状況をすぐにご確認いたします。お気軽にDMください😊"
    ),
    "琉球火鍋": (
        "こんにちは！琉球火鍋です🔥\n"
        "ご予約・個室のご相談承っております。\n"
        "人数・日程をお知らせいただければ空き状況をすぐ確認いたします！"
    ),
    "コンサル": (
        "はじめまして！YU HOLDINGSコンサルです。\n"
        "集客・売上改善のご相談、ぜひ一度詳しくお話しさせてください。\n"
        "無料相談も受け付けております📊"
    ),
}

# ── テストデータ (15件) ────────────────────────────────────
_TEST_LEADS = [
    # Trees Catering 法人 3件
    {
        "入力元": "Instagram DM",
        "問い合わせ本文": "こんにちは。来月20日に社内懇親会を予定しており、ケータリングをお願いしたいです。人数は30名程度、予算は15万円ほどです。",
        "投稿URL": "",
    },
    {
        "入力元": "LINE",
        "問い合わせ本文": "周年パーティーを企画中です。50名以上のイベントで、高級感のある料理をお願いしたい。日程は7月15日です。予算は25万円以内で。",
        "投稿URL": "",
    },
    {
        "入力元": "Google フォーム",
        "問い合わせ本文": "弊社の納会でケータリングをご依頼したいです。40名、予算20万円。12月に予定。見積を送ってください。",
        "投稿URL": "",
    },
    # TACHINOMIYA 観光客 3件
    {
        "入力元": "Threads",
        "問い合わせ本文": "今から国際通り周辺で夜ご飯探してます！沖縄料理食べたい。今夜おすすめある？1人でも入れますか？",
        "投稿URL": "https://www.threads.net/@test/post/abc123",
    },
    {
        "入力元": "Google 投稿コメント",
        "問い合わせ本文": "今日観光で沖縄来てます！1人でも入れる立飲みありますか？今から行きたいです",
        "投稿URL": "",
    },
    {
        "入力元": "Instagram コメント",
        "問い合わせ本文": "泡盛と沖縄料理が食べたい！今夜国際通り行きます。立飲みできるお店教えてください",
        "投稿URL": "https://www.instagram.com/p/test456/",
    },
    # Tree Beauty 予約相談 2件
    {
        "入力元": "Instagram DM",
        "問い合わせ本文": "脱毛の予約したいんですけど今日空いてますか？初めてなんですが大丈夫でしょうか",
        "投稿URL": "",
    },
    {
        "入力元": "LINE",
        "問い合わせ本文": "よもぎ蒸しとホワイトニングのセットでお願いしたいです。今週の空きを教えてください",
        "投稿URL": "",
    },
    # 琉球火鍋 予約相談 3件
    {
        "入力元": "Instagram DM",
        "問い合わせ本文": "誕生日に個室で火鍋やりたいです！4名で7月3日の夜、空いてますか？",
        "投稿URL": "",
    },
    {
        "入力元": "Google 投稿コメント",
        "問い合わせ本文": "女子会で火鍋したい！個室はありますか？来週末で6名です",
        "投稿URL": "",
    },
    {
        "入力元": "LINE",
        "問い合わせ本文": "接待で使いたいです。個室で会食できますか？6名、来週金曜日。予算は1人12000円くらい",
        "投稿URL": "",
    },
    # コンサル見込み 2件
    {
        "入力元": "Threads",
        "問い合わせ本文": "飲食店やってますが売上が伸び悩んでます。SNS集客相談できますか？成果報酬で考えています",
        "投稿URL": "https://www.threads.net/@owner_test/post/xyz789",
    },
    {
        "入力元": "Instagram DM",
        "問い合わせ本文": "美容サロンオーナーです。InstagramとGoogle集客を強化したい。コンサル相談したいです",
        "投稿URL": "",
    },
    # 除外対象 2件
    {
        "入力元": "Threads",
        "問い合わせ本文": "フォローありがとうございます！素敵なお店ですね",
        "投稿URL": "https://www.threads.net/@spammer/post/spam001",
    },
    {
        "入力元": "Instagram コメント",
        "問い合わせ本文": "素敵な投稿ですね！保存しました✨いいねしました！",
        "投稿URL": "https://www.instagram.com/p/exclude999/",
    },
]


# ── 内部ユーティリティ ────────────────────────────────────

def _now_jst() -> str:
    return datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")


def _date_jst() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d")


def _gc(creds_path: str) -> gspread.Client:
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    return gspread.authorize(creds)


def _gcs(creds_path: str) -> gcs_storage.Client:
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/devstorage.read_write"],
    )
    return gcs_storage.Client(project=GCS_PROJECT, credentials=creds)


def _upload_md_gcs(creds_path: str, gcs_path: str, content: str) -> str:
    client = _gcs(creds_path)
    bucket = client.bucket(GCS_BUCKET)
    blob   = bucket.blob(gcs_path)
    blob.upload_from_string(content.encode("utf-8"), content_type="text/markdown")
    return f"https://storage.googleapis.com/{GCS_BUCKET}/{gcs_path}"


def _get_or_create_sheet(ss: gspread.Spreadsheet, title: str, header: list) -> gspread.Worksheet:
    try:
        return ss.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=title, rows=2000, cols=len(header))
        ws.update(values=[header], range_name="A1")
        ws.format("A1:AB1", {
            "backgroundColor": {"red": 0.05, "green": 0.20, "blue": 0.10},
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        })
        return ws


# ── スコアリング ──────────────────────────────────────────

def _detect_biz(text: str) -> str:
    """テキストから最もマッチ事業を返す。マッチなし → '除外'"""
    scores = {}
    for biz, kws in BIZ_KEYWORDS.items():
        scores[biz] = sum(1 for k in kws if k in text)
    best = max(scores, key=lambda b: scores[b])
    return best if scores[best] > 0 else "除外"


def _is_exclude(text: str) -> bool:
    return any(k in text for k in EXCLUDE_KEYWORDS)


def _score_lead(text: str, biz: str) -> dict:
    """優先度・緊急度・関連性スコア・推定ニーズを返す"""
    urgent_kw   = ["今日", "今すぐ", "本日", "急いで", "今から", "すぐ", "早急", "明日", "明後日", "今夜", "今晩"]
    specific_kw = ["人数", "名", "予算", "日程", "日時", "予約", "確認したい", "いくら", "見積", "空いてますか"]

    urgency   = sum(3 for k in urgent_kw if k in text) + sum(2 for k in specific_kw if k in text)
    biz_kws   = BIZ_KEYWORDS.get(biz, [])
    relevance = sum(1 for k in biz_kws if k in text)

    needs_map = {
        "TACHINOMIYA":   "来店・予約",
        "Tree Beauty":   "美容メニュー予約",
        "琉球火鍋":       "個室予約・宴会",
        "Trees Catering": "法人イベント・ケータリング",
        "コンサル":       "集客コンサル・SNS支援",
    }
    needs = needs_map.get(biz, "問い合わせ対応")

    if urgency >= 6 or (relevance >= 3 and urgency >= 3):
        priority = "S"
    elif urgency >= 3 or relevance >= 2:
        priority = "A"
    elif relevance >= 1:
        priority = "B"
    else:
        priority = "C"

    recommended = {
        "S": "今日中に直接返信 or 電話",
        "A": "24時間以内に返信",
        "B": "48時間以内に返信",
        "C": "1週間以内に確認",
    }.get(priority, "確認")

    return {
        "urgency":     urgency,
        "relevance":   relevance,
        "priority":    priority,
        "needs":       needs,
        "recommended": recommended,
    }


def _estimate_sales(text: str, biz: str) -> int:
    match = re.search(r"(\d+)\s*名", text)
    pax = int(match.group(1)) if match else 0

    unit_price = {
        "TACHINOMIYA":    3_500,
        "Trees Catering": 8_000,
        "Tree Beauty":    15_000,
        "琉球火鍋":         10_000,
        "コンサル":         150_000,
    }.get(biz, 5_000)

    default_pax = {
        "Trees Catering": 20,
        "琉球火鍋":          4,
        "TACHINOMIYA":     2,
        "Tree Beauty":     1,
        "コンサル":          1,
    }.get(biz, 2)

    return unit_price * (pax if pax > 0 else default_pax)


def _gen_summary(text: str, biz: str, needs: str) -> str:
    if len(text) <= 60:
        return text
    return f"{biz}への{needs}問い合わせ: {text[:60]}…"


def _gen_line_notification(row: dict, dry_run: bool = True) -> str:
    mode = "[DRY RUN] " if dry_run else ""
    return (
        f"{mode}【売上見込みリード 優先度{row['優先度']}】\n\n"
        f"事業：{row['事業名']}\n"
        f"入力元：{row['入力元']}\n"
        f"推定売上：¥{int(row['推定売上']):,}\n"
        f"緊急度スコア：{row['緊急度']}\n\n"
        f"【問い合わせ内容】\n{str(row['問い合わせ本文'])[:150]}\n\n"
        f"【AI要約】\n{row['AI要約']}\n\n"
        f"【推奨対応】{row['推奨対応']}\n\n"
        f"【返信案】\n{str(row['返信案'])[:200]}\n\n"
        f"対応期限：{row['次回フォロー日時']}\n"
        f"---\n1.返信済み → 「完了」と返信\n2.見送り  → 「見送り」と返信"
    )


def _make_lead_row(lead: dict, dry_run: bool = True) -> dict:
    text = lead.get("問い合わせ本文", "")
    source = lead.get("入力元", "不明")
    url    = lead.get("投稿URL", "")
    now    = _now_jst()

    if _is_exclude(text):
        return {
            "登録日時": now, "入力元": source, "事業名": "除外",
            "見込み客名": "", "会社名": "", "連絡先": url,
            "投稿URL": url, "問い合わせ本文": text,
            "検知キーワード": "", "AI要約": "除外対象（スパム・一般コメント）",
            "推定ニーズ": "なし", "推定売上": 0,
            "緊急度": 0, "関連性スコア": 0, "優先度": "除外",
            "推奨対応": "対応不要", "返信案": "",
            "担当者": "", "通知先LINE": "", "通知状況": "対象外",
            "対応状況": "除外", "次回フォロー日時": "",
            "完了日時": "", "結果": "", "実売上": 0,
            "メモ": "", "エラー内容": "", "Obsidian Path": "",
        }

    biz    = _detect_biz(text)
    score  = _score_lead(text, biz)
    sales  = _estimate_sales(text, biz)
    reply  = _REPLY_TEMPLATES.get(biz, "お問い合わせありがとうございます！詳細をお聞かせください。")
    summary = _gen_summary(text, biz, score["needs"])

    matched_kws = [k for k in BIZ_KEYWORDS.get(biz, []) if k in text]

    today = datetime.now(JST)
    followup_days = {"S": 0, "A": 1, "B": 2, "C": 7}.get(score["priority"], 3)
    followup_dt   = (today + timedelta(days=followup_days)).strftime("%Y/%m/%d %H:%M")

    row = {
        "登録日時": now, "入力元": source, "事業名": biz,
        "見込み客名": "", "会社名": "", "連絡先": url,
        "投稿URL": url, "問い合わせ本文": text,
        "検知キーワード": "、".join(matched_kws[:5]),
        "AI要約": summary,
        "推定ニーズ": score["needs"],
        "推定売上": sales,
        "緊急度": score["urgency"],
        "関連性スコア": score["relevance"],
        "優先度": score["priority"],
        "推奨対応": score["recommended"],
        "返信案": reply,
        "担当者": "", "通知先LINE": "",
        "通知状況": "DRY_RUN生成済み" if dry_run else "未通知",
        "対応状況": "未対応",
        "次回フォロー日時": followup_dt,
        "完了日時": "", "結果": "", "実売上": 0,
        "メモ": "", "エラー内容": "", "Obsidian Path": "",
    }
    return row


# ── 公開API ───────────────────────────────────────────────

def setup(spreadsheet_id: str, creds_path: str) -> dict:
    """3シート (LEAD_MASTER / LEAD_ACTION_LOG / LEAD_DASHBOARD) を作成"""
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    created = []
    for name, header in LEAD_SHEETS.items():
        _get_or_create_sheet(ss, name, header)
        created.append(name)
    return {
        "ok": True,
        "sheets_created": created,
        "spreadsheet_id": spreadsheet_id,
        "url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}",
    }


def run_test(spreadsheet_id: str, creds_path: str) -> dict:
    """15件のテストリードをLEAD_MASTERに投入し、判定結果を返す"""
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    ws = _get_or_create_sheet(ss, "LEAD_MASTER", LEAD_SHEETS["LEAD_MASTER"])

    rows_to_add = []
    summary     = {"S": 0, "A": 0, "B": 0, "C": 0, "除外": 0}
    notifications = []

    for lead in _TEST_LEADS:
        row = _make_lead_row(lead, dry_run=True)
        rows_to_add.append([row.get(h, "") for h in LEAD_SHEETS["LEAD_MASTER"]])
        priority = row["優先度"]
        summary[priority] = summary.get(priority, 0) + 1

        if priority in ("S", "A"):
            notif_text = _gen_line_notification(row, dry_run=True)
            notifications.append({
                "priority": priority,
                "biz":      row["事業名"],
                "sales":    row["推定売上"],
                "preview":  notif_text[:200],
            })

    ws.append_rows(rows_to_add, value_input_option="RAW")

    total_sales = sum(
        int(r.get("推定売上", 0))
        for r in [_make_lead_row(l, dry_run=True) for l in _TEST_LEADS]
    )

    return {
        "ok": True,
        "test_leads": len(_TEST_LEADS),
        "priority_summary": summary,
        "estimated_total_sales": total_sales,
        "line_notifications_generated": len(notifications),
        "line_notification_samples": notifications[:3],
        "dry_run": True,
        "note": "LINE通知はDRY_RUN=Trueのため送信しません。本番はLINE_OWNER_TOKEN設定後に有効化。",
    }


def process_leads(spreadsheet_id: str, creds_path: str, dry_run: bool = True) -> dict:
    """LEAD_MASTERの未処理行（対応状況=空）を判定・返信案生成"""
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    try:
        ws = ss.worksheet("LEAD_MASTER")
    except gspread.WorksheetNotFound:
        return {"ok": False, "error": "LEAD_MASTER シートが見つかりません。/lead-setup を先に実行してください。"}

    all_rows = ws.get_all_records()
    processed = 0
    skipped   = 0

    for i, row in enumerate(all_rows, start=2):
        if row.get("対応状況"):
            skipped += 1
            continue
        text = str(row.get("問い合わせ本文", ""))
        if not text.strip():
            skipped += 1
            continue
        new_row = _make_lead_row({"入力元": row.get("入力元", ""), "問い合わせ本文": text, "投稿URL": row.get("投稿URL", "")}, dry_run=dry_run)
        header = LEAD_SHEETS["LEAD_MASTER"]
        for col_idx, h in enumerate(header, start=1):
            if h in new_row:
                ws.update_cell(i, col_idx, new_row[h])
        processed += 1

    return {
        "ok": True,
        "processed": processed,
        "skipped": skipped,
        "dry_run": dry_run,
    }


def get_status(spreadsheet_id: str, creds_path: str) -> dict:
    """LEAD_MASTERの統計サマリーを返す"""
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    try:
        ws = ss.worksheet("LEAD_MASTER")
    except gspread.WorksheetNotFound:
        return {"ok": True, "total": 0, "priority": {}, "note": "シート未作成"}

    rows = ws.get_all_records()
    total     = len(rows)
    priority  = {}
    unhandled = 0
    sales_sum = 0

    for r in rows:
        p = r.get("優先度", "C")
        priority[p] = priority.get(p, 0) + 1
        if not r.get("対応状況") or r.get("対応状況") == "未対応":
            unhandled += 1
        try:
            sales_sum += int(str(r.get("推定売上", 0)).replace(",", "") or 0)
        except (ValueError, TypeError):
            pass

    return {
        "ok": True,
        "total": total,
        "priority": priority,
        "unhandled": unhandled,
        "estimated_sales_total": sales_sum,
    }


def followup(spreadsheet_id: str, creds_path: str) -> dict:
    """フォロー期限が過ぎた未対応リードを返す"""
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    try:
        ws = ss.worksheet("LEAD_MASTER")
    except gspread.WorksheetNotFound:
        return {"ok": True, "followup_leads": [], "note": "シート未作成"}

    now   = datetime.now(JST)
    rows  = ws.get_all_records()
    due   = []

    for r in rows:
        if r.get("対応状況") in ("完了", "除外", "見送り"):
            continue
        dt_str = str(r.get("次回フォロー日時", "")).strip()
        if not dt_str:
            continue
        try:
            dt = datetime.strptime(dt_str, "%Y/%m/%d %H:%M").replace(tzinfo=JST)
            if dt <= now:
                due.append({
                    "事業名": r.get("事業名"), "優先度": r.get("優先度"),
                    "推定売上": r.get("推定売上"), "入力元": r.get("入力元"),
                    "AI要約": r.get("AI要約"), "次回フォロー日時": dt_str,
                })
        except (ValueError, TypeError):
            continue

    return {"ok": True, "followup_leads": due, "count": len(due)}


def owner_report(spreadsheet_id: str, creds_path: str) -> dict:
    """オーナー向け日次リードサマリーを生成（テキストのみ、LINE送信なし）"""
    status = get_status(spreadsheet_id, creds_path)
    fup    = followup(spreadsheet_id, creds_path)
    now    = _now_jst()

    p = status.get("priority", {})
    report_text = (
        f"【AI営業本部 日次リポート】{now}\n\n"
        f"📊 リード合計: {status.get('total', 0)}件\n"
        f"  S優先度: {p.get('S', 0)}件  A優先度: {p.get('A', 0)}件\n"
        f"  B: {p.get('B', 0)}件  C: {p.get('C', 0)}件  除外: {p.get('除外', 0)}件\n\n"
        f"💰 推定売上合計: ¥{status.get('estimated_sales_total', 0):,}\n"
        f"⚠️ 未対応: {status.get('unhandled', 0)}件\n"
        f"🔔 フォロー期限超過: {fup.get('count', 0)}件\n\n"
        f"要確認リード:\n"
    )
    for lead in fup.get("followup_leads", [])[:5]:
        report_text += f"  • [{lead['優先度']}] {lead['事業名']} ¥{int(lead.get('推定売上', 0) or 0):,} — {lead.get('AI要約', '')[:50]}\n"

    return {
        "ok": True,
        "report_text": report_text,
        "status": status,
        "followup": fup,
        "dry_run": True,
    }


def export_knowledge(spreadsheet_id: str, creds_path: str) -> dict:
    """優先度S/AリードをGCS Knowledge OSへ保存"""
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    try:
        ws = ss.worksheet("LEAD_MASTER")
    except gspread.WorksheetNotFound:
        return {"ok": False, "error": "LEAD_MASTER シート未作成"}

    rows     = ws.get_all_records()
    exported = []
    today    = _date_jst()

    for r in rows:
        if r.get("優先度") not in ("S", "A"):
            continue
        biz  = str(r.get("事業名", "Unknown")).replace(" ", "_")
        slug = f"lead_{today}_{len(exported)+1:02d}"
        path = f"{GCS_PREFIX}/06_Leads_Sales/{biz}/{slug}.md"

        md = (
            f"---\n"
            f"title: リード — {r.get('AI要約', '')[:40]}\n"
            f"business: {r.get('事業名', '')}\n"
            f"category: lead\n"
            f"date: {today}\n"
            f"priority: {r.get('優先度', '')}\n"
            f"source: lead_command_center\n"
            f"status: {r.get('対応状況', '未対応')}\n"
            f"---\n\n"
            f"# リード記録 — 優先度{r.get('優先度', '')}\n\n"
            f"## 基本情報\n"
            f"- 事業: {r.get('事業名', '')}\n"
            f"- 入力元: {r.get('入力元', '')}\n"
            f"- 登録: {r.get('登録日時', '')}\n"
            f"- 推定売上: ¥{int(str(r.get('推定売上', 0)).replace(',', '') or 0):,}\n\n"
            f"## 問い合わせ内容\n{r.get('問い合わせ本文', '')}\n\n"
            f"## AI判定\n"
            f"- 推定ニーズ: {r.get('推定ニーズ', '')}\n"
            f"- 優先度: {r.get('優先度', '')}\n"
            f"- 推奨対応: {r.get('推奨対応', '')}\n\n"
            f"## 返信案\n{r.get('返信案', '')}\n\n"
            f"## 対応記録\n"
            f"- 担当: {r.get('担当者', '未定')}\n"
            f"- 状況: {r.get('対応状況', '未対応')}\n"
            f"- 次回フォロー: {r.get('次回フォロー日時', '')}\n"
        )

        url = _upload_md_gcs(creds_path, path, md)
        exported.append({"path": path, "biz": biz, "priority": r.get("優先度"), "url": url})

    return {
        "ok": True,
        "exported": len(exported),
        "files": [e["path"] for e in exported],
    }
