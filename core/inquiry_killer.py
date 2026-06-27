"""
AI営業本部 — Inquiry Killer
-----------------------------
全チャネルからの問い合わせ（Gmail・LINE・Instagram DM・HPB等）を
一元管理し、AI要約・返信案・担当者通知・GCS保存を行う。

現フェーズ: スプレッドシート手動入力対応 (Phase 1)
将来連携: Gmail API / LINE Webhook / Instagram Graph API (Phase 2以降)

安全設計:
  - LINE本番送信: DRY_RUN=True のときは通知文字列生成のみ
  - 秘密情報をMarkdownに絶対出力しない
"""

import os
import re
from datetime import datetime, timezone, timedelta

import gspread
from google.oauth2.service_account import Credentials
from google.cloud import storage as gcs_storage

JST = timezone(timedelta(hours=9))
GCS_BUCKET  = "tree-beauty-blog-images"
GCS_PREFIX  = "knowledge-os"
GCS_PROJECT = "tree-beauty-ai-499303"

# ── シート定義 ─────────────────────────────────────────────
INQUIRY_SHEET = {
    "INQUIRY_MASTER": [
        "登録日時", "入力元", "事業名", "問い合わせ者", "連絡先",
        "問い合わせ本文", "希望日", "人数", "予算",
        "推定売上", "緊急度", "AI要約", "返信案", "担当者",
        "通知状況", "対応状況", "初回返信日時", "次回フォロー日時",
        "成約状況", "メモ",
    ],
}

# ── テスト問い合わせデータ (5件) ─────────────────────────
_TEST_INQUIRIES = [
    {
        "入力元": "HPB フォーム",
        "事業名": "Trees Catering",
        "問い合わせ者": "田中企画部長",
        "連絡先": "tanaka@company.co.jp",
        "問い合わせ本文": "7月20日に社内懇親会を予定しています。人数は40名、予算は20万円です。場所は弊社会議室（那覇市内）。ケータリングをお願いできますか？",
        "希望日": "2026/07/20",
        "人数": "40",
        "予算": "200000",
    },
    {
        "入力元": "Google フォーム",
        "事業名": "Trees Catering",
        "問い合わせ者": "佐藤様",
        "連絡先": "sato@event.jp",
        "問い合わせ本文": "8月のイベントで60名規模のケータリングをお願いしたいです。琉球料理中心で、予算は30万円以内でお願いします。日程は8月10日か17日を検討中。",
        "希望日": "2026/08/10",
        "人数": "60",
        "予算": "300000",
    },
    {
        "入力元": "Instagram DM",
        "事業名": "Tree Beauty",
        "問い合わせ者": "山田さん",
        "連絡先": "@yamada_okinawa",
        "問い合わせ本文": "全身脱毛コースの予約をしたいです。来週の木曜日か金曜日に空きはありますか？初めて利用します。",
        "希望日": "2026/07/02",
        "人数": "1",
        "予算": "30000",
    },
    {
        "入力元": "LINE",
        "事業名": "Tree Beauty",
        "問い合わせ者": "鈴木様",
        "連絡先": "LINE友達",
        "問い合わせ本文": "よもぎ蒸しと歯のホワイトニングのセットメニューはありますか？今月中に予約したいです。",
        "希望日": "",
        "人数": "1",
        "予算": "20000",
    },
    {
        "入力元": "Google フォーム",
        "事業名": "琉球火鍋",
        "問い合わせ者": "中村様",
        "連絡先": "nakamura@mail.com",
        "問い合わせ本文": "7月5日（土）に誕生日会を予定しています。8名で個室を使いたいです。コース料理はありますか？予算は1人1万円くらい。",
        "希望日": "2026/07/05",
        "人数": "8",
        "予算": "80000",
    },
]

# ── 返信案テンプレート ─────────────────────────────────────
_REPLY_TEMPLATES = {
    "Trees Catering": (
        "お問い合わせいただきありがとうございます！TREE's Cateringです🍽️\n\n"
        "ご希望の日程・人数・ご予算を確認いたしました。\n"
        "詳細なお見積りをご用意いたしますので、\n"
        "以下の情報をお教えいただけますでしょうか？\n\n"
        "① 開始時間・終了時間\n"
        "② 会場の住所\n"
        "③ ご希望のお料理（和食・洋食・琉球料理など）\n"
        "④ アレルギーのある方の有無\n\n"
        "ご連絡をお待ちしております！"
    ),
    "Tree Beauty": (
        "お問い合わせありがとうございます！Tree Beautyです✨\n\n"
        "ご希望の日程の空き状況をすぐに確認いたします。\n"
        "メニューのご希望とご都合の良い時間帯をお教えいただければ、\n"
        "スムーズにご予約が可能です。\n\n"
        "お気軽にご連絡ください😊"
    ),
    "琉球火鍋": (
        "お問い合わせいただきありがとうございます！琉球火鍋です🔥\n\n"
        "ご希望の日程・人数を確認いたしました。\n"
        "個室・コース料理の詳細をご案内いたします。\n\n"
        "ご希望の開始時間をお教えいただければ、\n"
        "空き状況をすぐにご確認いたします！"
    ),
}


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
        ws.format("A1:T1", {
            "backgroundColor": {"red": 0.15, "green": 0.05, "blue": 0.20},
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        })
        return ws


def _estimate_sales(inq: dict) -> int:
    biz    = inq.get("事業名", "")
    budget = inq.get("予算", "")
    pax    = inq.get("人数", "")

    try:
        if budget:
            return int(str(budget).replace(",", ""))
    except (ValueError, TypeError):
        pass

    try:
        n = int(pax)
    except (ValueError, TypeError):
        n = 1

    unit = {
        "Trees Catering": 8_000,
        "Tree Beauty":    15_000,
        "琉球火鍋":         10_000,
        "TACHINOMIYA":    3_500,
    }.get(biz, 5_000)

    return unit * n


def _urgency_score(text: str, hoped_date: str) -> int:
    urgent_kw = ["今日", "今すぐ", "本日", "急いで", "今週", "来週", "すぐ"]
    score = sum(2 for k in urgent_kw if k in text)
    if hoped_date:
        score += 3
    return score


def _make_inquiry_row(inq: dict) -> dict:
    now    = _now_jst()
    text   = inq.get("問い合わせ本文", "")
    biz    = inq.get("事業名", "")
    hoped  = inq.get("希望日", "")
    sales  = _estimate_sales(inq)
    urgency = _urgency_score(text, hoped)

    summary = f"{biz}への{inq.get('入力元', '')}問い合わせ: {text[:60]}…" if len(text) > 60 else text
    reply   = _REPLY_TEMPLATES.get(biz, "お問い合わせありがとうございます！詳細をご確認の上、ご連絡いたします。")

    today    = datetime.now(JST)
    follow_days = 1 if urgency >= 3 else 2
    followup_dt = (today + timedelta(days=follow_days)).strftime("%Y/%m/%d %H:%M")

    return {
        "登録日時":       now,
        "入力元":         inq.get("入力元", ""),
        "事業名":         biz,
        "問い合わせ者":    inq.get("問い合わせ者", ""),
        "連絡先":         inq.get("連絡先", ""),
        "問い合わせ本文":  text,
        "希望日":         hoped,
        "人数":           inq.get("人数", ""),
        "予算":           inq.get("予算", ""),
        "推定売上":        sales,
        "緊急度":          urgency,
        "AI要約":          summary,
        "返信案":          reply,
        "担当者":          "",
        "通知状況":        "DRY_RUN生成済み",
        "対応状況":        "未対応",
        "初回返信日時":    "",
        "次回フォロー日時": followup_dt,
        "成約状況":        "未成約",
        "メモ":            "",
    }


# ── 公開API ───────────────────────────────────────────────

def setup(spreadsheet_id: str, creds_path: str) -> dict:
    """INQUIRY_MASTER シートを作成"""
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    header = INQUIRY_SHEET["INQUIRY_MASTER"]
    _get_or_create_sheet(ss, "INQUIRY_MASTER", header)
    return {
        "ok": True,
        "sheets_created": ["INQUIRY_MASTER"],
        "spreadsheet_id": spreadsheet_id,
        "url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}",
    }


def run_test(spreadsheet_id: str, creds_path: str) -> dict:
    """5件のテスト問い合わせをINQUIRY_MASTERに投入し、返信案を確認する"""
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    ws = _get_or_create_sheet(ss, "INQUIRY_MASTER", INQUIRY_SHEET["INQUIRY_MASTER"])

    header   = INQUIRY_SHEET["INQUIRY_MASTER"]
    rows_add = []
    results  = []

    for inq in _TEST_INQUIRIES:
        row = _make_inquiry_row(inq)
        rows_add.append([row.get(h, "") for h in header])
        results.append({
            "事業名":    row["事業名"],
            "問い合わせ者": row["問い合わせ者"],
            "推定売上":  row["推定売上"],
            "緊急度":    row["緊急度"],
            "返信案preview": row["返信案"][:100],
        })

    ws.append_rows(rows_add, value_input_option="RAW")
    total_sales = sum(r.get("推定売上", 0) for r in [_make_inquiry_row(i) for i in _TEST_INQUIRIES])

    return {
        "ok": True,
        "test_inquiries": len(_TEST_INQUIRIES),
        "total_estimated_sales": total_sales,
        "results": results,
        "dry_run": True,
        "note": "LINE通知はDRY_RUN=Trueのため送信しません。",
    }


def process(spreadsheet_id: str, creds_path: str, dry_run: bool = True) -> dict:
    """INQUIRY_MASTERの未処理行を判定・返信案生成"""
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    try:
        ws = ss.worksheet("INQUIRY_MASTER")
    except gspread.WorksheetNotFound:
        return {"ok": False, "error": "INQUIRY_MASTER シート未作成。/inquiry-setup を先に実行してください。"}

    all_rows = ws.get_all_records()
    processed = 0
    skipped   = 0

    header = INQUIRY_SHEET["INQUIRY_MASTER"]
    for i, row in enumerate(all_rows, start=2):
        if row.get("対応状況") and row.get("対応状況") != "未対応":
            skipped += 1
            continue
        if row.get("AI要約"):
            skipped += 1
            continue
        text = str(row.get("問い合わせ本文", ""))
        if not text.strip():
            skipped += 1
            continue

        new_row = _make_inquiry_row({
            "入力元":       row.get("入力元", ""),
            "事業名":       row.get("事業名", ""),
            "問い合わせ者":  row.get("問い合わせ者", ""),
            "連絡先":       row.get("連絡先", ""),
            "問い合わせ本文": text,
            "希望日":       row.get("希望日", ""),
            "人数":         row.get("人数", ""),
            "予算":         row.get("予算", ""),
        })

        for col_idx, h in enumerate(header, start=1):
            if h in new_row and not row.get(h):
                ws.update_cell(i, col_idx, new_row[h])

        processed += 1

    return {
        "ok": True,
        "processed": processed,
        "skipped": skipped,
        "dry_run": dry_run,
    }


def get_status(spreadsheet_id: str, creds_path: str) -> dict:
    """INQUIRY_MASTERの統計を返す"""
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    try:
        ws = ss.worksheet("INQUIRY_MASTER")
    except gspread.WorksheetNotFound:
        return {"ok": True, "total": 0, "note": "シート未作成"}

    rows  = ws.get_all_records()
    total = len(rows)
    status_count = {}
    sales_total  = 0
    unhandled    = 0

    for r in rows:
        s = r.get("対応状況", "未対応")
        status_count[s] = status_count.get(s, 0) + 1
        if s in ("未対応", ""):
            unhandled += 1
        try:
            sales_total += int(str(r.get("推定売上", 0)).replace(",", "") or 0)
        except (ValueError, TypeError):
            pass

    return {
        "ok": True,
        "total": total,
        "status": status_count,
        "unhandled": unhandled,
        "estimated_sales_total": sales_total,
    }


def export_knowledge(spreadsheet_id: str, creds_path: str) -> dict:
    """重要問い合わせをGCS Knowledge OSへ保存"""
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    try:
        ws = ss.worksheet("INQUIRY_MASTER")
    except gspread.WorksheetNotFound:
        return {"ok": False, "error": "INQUIRY_MASTER シート未作成"}

    rows     = ws.get_all_records()
    exported = []
    today    = _date_jst()

    for i, r in enumerate(rows, start=1):
        sales = int(str(r.get("推定売上", 0) or 0).replace(",", "") or 0)
        if sales < 50_000:
            continue
        biz   = str(r.get("事業名", "unknown")).replace(" ", "_")
        path  = f"{GCS_PREFIX}/06_Leads_Sales/{biz}/inquiry_{today}_{i:02d}.md"

        md = (
            f"---\n"
            f"title: 問い合わせ — {r.get('AI要約', '')[:40]}\n"
            f"business: {r.get('事業名', '')}\n"
            f"category: inquiry\n"
            f"date: {today}\n"
            f"source: inquiry_killer\n"
            f"status: {r.get('対応状況', '未対応')}\n"
            f"---\n\n"
            f"# 問い合わせ記録\n\n"
            f"## 基本情報\n"
            f"- 事業: {r.get('事業名', '')}\n"
            f"- 入力元: {r.get('入力元', '')}\n"
            f"- 問い合わせ者: {r.get('問い合わせ者', '')}\n"
            f"- 希望日: {r.get('希望日', '')}\n"
            f"- 人数: {r.get('人数', '')}名\n"
            f"- 予算: ¥{int(str(r.get('予算', 0) or 0)):,}\n"
            f"- 推定売上: ¥{sales:,}\n\n"
            f"## 問い合わせ内容\n{r.get('問い合わせ本文', '')}\n\n"
            f"## AI要約\n{r.get('AI要約', '')}\n\n"
            f"## 返信案\n{r.get('返信案', '')}\n\n"
            f"## 対応記録\n"
            f"- 担当: {r.get('担当者', '未定')}\n"
            f"- 状況: {r.get('対応状況', '未対応')}\n"
            f"- 初回返信: {r.get('初回返信日時', '未返信')}\n"
            f"- 次回フォロー: {r.get('次回フォロー日時', '')}\n"
            f"- 成約状況: {r.get('成約状況', '未成約')}\n"
        )

        url = _upload_md_gcs(creds_path, path, md)
        exported.append({"path": path, "biz": biz, "url": url})

    return {
        "ok": True,
        "exported": len(exported),
        "files": [e["path"] for e in exported],
    }
