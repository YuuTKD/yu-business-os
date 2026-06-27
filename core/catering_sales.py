"""
AI営業本部 — Catering B2B Sales Autopilot
-------------------------------------------
Trees Cateringの法人営業DM管理・フォロー自動化。
20種以上のカテゴリ別営業文テンプレートで効率的にアプローチ。

安全設計:
  - DM実際の送信は行わない（営業文生成のみ）
  - LINE通知はDRY_RUNのみ
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

# ── シート定義 ─────────────────────────────────────────────
CATERING_SHEETS = {
    "CATERING_SALES_TARGETS": [
        "登録日時", "営業先名", "カテゴリ", "住所", "電話", "Instagram",
        "Webサイト", "担当者名", "想定ニーズ", "推定単価", "優先度",
        "営業文", "初回アプローチ日", "最終接触日", "返信状況",
        "商談状況", "見積状況", "成約状況", "次回フォロー日",
        "実売上", "メモ", "Obsidian Path",
    ],
    "CATERING_SALES_DASHBOARD": [
        "日付", "営業先数", "本日DM対象", "送信済み", "返信あり",
        "商談化", "見積提出", "成約", "推定売上", "実売上",
        "未対応", "最終更新",
    ],
}

# ── カテゴリ別テンプレート ─────────────────────────────────
SALES_TEMPLATES = {
    "ホテル": (
        "はじめまして！TREE's Cateringと申します🍽️\n"
        "宿泊客向けパーティーや企業の懇親会、スイートルームでの会食など、\n"
        "高品質なケータリングをご提供しております。\n"
        "琉球・創作料理が得意で、10名〜100名規模に対応可能です。\n"
        "ご興味がございましたらお気軽にご連絡ください！"
    ),
    "BAR": (
        "こんにちは！TREE's Cateringです🥂\n"
        "周年イベントやVIPナイト、貸切パーティーなど、\n"
        "BARのイベントに合わせたケータリングが得意です。\n"
        "軽食からフルコースまで柔軟にご対応できます。\n"
        "ご一緒できれば嬉しいです！"
    ),
    "クラブ": (
        "こんにちは！TREE's Cateringです🎵\n"
        "VIPイベントや周年パーティーのケータリングをご提供できます。\n"
        "深夜対応・フィンガーフード専門メニューもございます。\n"
        "ご一緒に盛り上がれる企画、ぜひご相談ください！"
    ),
    "企業": (
        "はじめまして！TREE's Cateringです🍾\n"
        "社内懇親会・納会・周年パーティーのケータリングを承っております。\n"
        "30名〜100名規模の実績多数。当日配膳スタッフも同行可能です。\n"
        "お見積り無料ですのでお気軽にご相談ください！"
    ),
    "レンタルスペース": (
        "こんにちは！TREE's Cateringです🎉\n"
        "ご利用者様向けのパートナーとして、\n"
        "提携ケータリングのご提案ができます。\n"
        "スペース予約とケータリングのセット提案で\n"
        "お互いの売上アップにつなげませんか？\n"
        "ぜひ一度お話しさせてください！"
    ),
    "結婚式場": (
        "はじめまして！TREE's Cateringです💍\n"
        "二次会・披露宴後の懇親会向けケータリングをご提供できます。\n"
        "ゲストに喜ばれる琉球×創作料理が自慢です🌺\n"
        "アレルギー対応も万全。ご予算に合わせてご提案いたします！"
    ),
    "イベント会社": (
        "こんにちは！TREE's Cateringです🎪\n"
        "イベントのケータリングパートナーをお探しでしたら\n"
        "ぜひご相談ください。\n"
        "規模・予算・テーマに合わせた柔軟な対応が可能です！\n"
        "過去実績：企業イベント50回以上"
    ),
    "不動産会社": (
        "はじめまして！TREE's Cateringです🏢\n"
        "内見会・竣工式・入居者向けイベントのケータリングを\n"
        "ご提供できます。\n"
        "上品な軽食・スイーツも得意です。\n"
        "ご縁をいただければ嬉しいです！"
    ),
    "美容サロン": (
        "こんにちは！TREE's Cateringです✨\n"
        "周年イベントやスタッフ向け食事会のケータリング、\n"
        "ぜひお任せください！\n"
        "サロンの特別な日をおいしい料理で彩ります🌸\n"
        "小規模（10名〜）にも対応できます。"
    ),
    "学校": (
        "はじめまして！TREE's Cateringです📚\n"
        "卒業式・文化祭・保護者会などのケータリングを承っております。\n"
        "アレルギー対応も柔軟に。学校関係割引あり。\n"
        "ご相談だけでもお気軽にどうぞ！"
    ),
    "観光団体": (
        "こんにちは！TREE's Cateringです🌺\n"
        "沖縄観光の思い出に、本格琉球料理のケータリングはいかがでしょうか？\n"
        "団体様向けの特別プランをご用意できます！\n"
        "バスツアーや研修旅行にも対応しております。"
    ),
    "撮影スタジオ": (
        "はじめまして！TREE's Cateringです📸\n"
        "撮影イベントやキャストの食事、スタジオパーティーの\n"
        "ケータリングを承ります。\n"
        "スタジオの特別な瞬間を彩ります✨\n"
        "小回りの利くスタジオ対応が得意です！"
    ),
    "スポーツ施設": (
        "こんにちは！TREE's Cateringです🏆\n"
        "大会・表彰式・スポンサー向けイベントのケータリングを\n"
        "ご提供できます。\n"
        "健康志向メニューも充実しています！\n"
        "ぜひご相談ください。"
    ),
}

# ── テスト営業先データ (20件) ─────────────────────────────
_TEST_TARGETS = [
    # ホテル 3件
    {"営業先名": "ダブルツリーホテル那覇", "カテゴリ": "ホテル", "住所": "沖縄県那覇市", "優先度": "A", "推定単価": 800_000},
    {"営業先名": "ホテルコレクティブ那覇", "カテゴリ": "ホテル", "住所": "沖縄県那覇市牧志", "優先度": "A", "推定単価": 600_000},
    {"営業先名": "ロワジールホテル那覇", "カテゴリ": "ホテル", "住所": "沖縄県那覇市西", "優先度": "B", "推定単価": 500_000},
    # イベント会社 3件
    {"営業先名": "オキナワイベントプランニング", "カテゴリ": "イベント会社", "住所": "沖縄県那覇市おもろまち", "優先度": "S", "推定単価": 1_000_000},
    {"営業先名": "リュウキュウイベント株式会社", "カテゴリ": "イベント会社", "住所": "沖縄県那覇市", "優先度": "A", "推定単価": 800_000},
    {"営業先名": "南国フェスティバル事務局", "カテゴリ": "イベント会社", "住所": "沖縄県那覇市", "優先度": "B", "推定単価": 500_000},
    # BAR 2件
    {"営業先名": "BAR OKINAWA", "カテゴリ": "BAR", "住所": "沖縄県那覇市松山", "優先度": "B", "推定単価": 300_000},
    {"営業先名": "クラフトビア那覇", "カテゴリ": "BAR", "住所": "沖縄県那覇市", "優先度": "B", "推定単価": 250_000},
    # クラブ 2件
    {"営業先名": "CLUB 430", "カテゴリ": "クラブ", "住所": "沖縄県那覇市松山", "優先度": "B", "推定単価": 400_000},
    {"営業先名": "SOUND BAR NAHA", "カテゴリ": "クラブ", "住所": "沖縄県那覇市", "優先度": "C", "推定単価": 200_000},
    # レンタルスペース 2件
    {"営業先名": "スペースAO那覇", "カテゴリ": "レンタルスペース", "住所": "沖縄県那覇市", "優先度": "A", "推定単価": 500_000},
    {"営業先名": "ルーム国際通り", "カテゴリ": "レンタルスペース", "住所": "沖縄県那覇市牧志", "優先度": "A", "推定単価": 400_000},
    # 企業 2件
    {"営業先名": "DMMグループ沖縄オフィス", "カテゴリ": "企業", "住所": "沖縄県那覇市おもろまち", "優先度": "S", "推定単価": 1_500_000},
    {"営業先名": "ゆいレール沖縄本社", "カテゴリ": "企業", "住所": "沖縄県那覇市", "優先度": "B", "推定単価": 400_000},
    # 結婚式場 2件
    {"営業先名": "リゾートウェディング那覇", "カテゴリ": "結婚式場", "住所": "沖縄県那覇市", "優先度": "A", "推定単価": 600_000},
    {"営業先名": "海の見えるウェディング沖縄", "カテゴリ": "結婚式場", "住所": "沖縄県中頭郡", "優先度": "B", "推定単価": 400_000},
    # 学校 1件
    {"営業先名": "沖縄国際大学学務課", "カテゴリ": "学校", "住所": "沖縄県宜野湾市", "優先度": "B", "推定単価": 300_000},
    # 不動産会社 1件
    {"営業先名": "琉球不動産センター", "カテゴリ": "不動産会社", "住所": "沖縄県那覇市おもろまち", "優先度": "C", "推定単価": 200_000},
    # 美容サロン 2件
    {"営業先名": "ヘアサロンRYUKYU", "カテゴリ": "美容サロン", "住所": "沖縄県那覇市", "優先度": "B", "推定単価": 150_000},
    {"営業先名": "美容室NAHA", "カテゴリ": "美容サロン", "住所": "沖縄県那覇市松山", "優先度": "C", "推定単価": 100_000},
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
        ws.format("A1:V1", {
            "backgroundColor": {"red": 0.05, "green": 0.15, "blue": 0.25},
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        })
        return ws


# ── 公開API ───────────────────────────────────────────────

def setup(spreadsheet_id: str, creds_path: str) -> dict:
    """2シート (CATERING_SALES_TARGETS / CATERING_SALES_DASHBOARD) を作成"""
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    created = []
    for name, header in CATERING_SHEETS.items():
        _get_or_create_sheet(ss, name, header)
        created.append(name)
    return {
        "ok": True,
        "sheets_created": created,
        "spreadsheet_id": spreadsheet_id,
        "url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}",
    }


def generate_test_data(spreadsheet_id: str, creds_path: str) -> dict:
    """20件のテスト営業先をCATE RING_SALES_TARGETSに投入"""
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    ws = _get_or_create_sheet(ss, "CATERING_SALES_TARGETS", CATERING_SHEETS["CATERING_SALES_TARGETS"])

    header   = CATERING_SHEETS["CATERING_SALES_TARGETS"]
    now      = _now_jst()
    rows_add = []

    for t in _TEST_TARGETS:
        cat     = t["カテゴリ"]
        template = SALES_TEMPLATES.get(cat, "お問い合わせありがとうございます！ぜひご相談ください。")
        needs    = f"{cat}向けイベントケータリング"

        row_data = {
            "登録日時":       now,
            "営業先名":       t["営業先名"],
            "カテゴリ":       cat,
            "住所":          t.get("住所", ""),
            "電話":          "",
            "Instagram":     "",
            "Webサイト":      "",
            "担当者名":       "",
            "想定ニーズ":     needs,
            "推定単価":       t.get("推定単価", 0),
            "優先度":         t.get("優先度", "B"),
            "営業文":         template,
            "初回アプローチ日": "",
            "最終接触日":     "",
            "返信状況":       "未送信",
            "商談状況":       "未商談",
            "見積状況":       "未提出",
            "成約状況":       "未成約",
            "次回フォロー日":  "",
            "実売上":         0,
            "メモ":          "",
            "Obsidian Path": "",
        }
        rows_add.append([row_data.get(h, "") for h in header])

    ws.append_rows(rows_add, value_input_option="RAW")

    total_potential = sum(t.get("推定単価", 0) for t in _TEST_TARGETS)
    category_count  = {}
    priority_count  = {}
    for t in _TEST_TARGETS:
        category_count[t["カテゴリ"]] = category_count.get(t["カテゴリ"], 0) + 1
        priority_count[t["優先度"]]   = priority_count.get(t["優先度"], 0) + 1

    return {
        "ok": True,
        "targets_added": len(_TEST_TARGETS),
        "total_potential_sales": total_potential,
        "category_breakdown": category_count,
        "priority_breakdown": priority_count,
    }


def daily_targets(spreadsheet_id: str, creds_path: str) -> dict:
    """本日のDM対象（優先度S/A・未送信）を最大5件返す"""
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    try:
        ws = ss.worksheet("CATERING_SALES_TARGETS")
    except gspread.WorksheetNotFound:
        return {"ok": True, "targets": [], "note": "シート未作成。/catering-sales-setup を実行してください。"}

    rows    = ws.get_all_records()
    targets = []

    for r in rows:
        if r.get("返信状況") not in ("未送信", ""):
            continue
        if r.get("優先度") not in ("S", "A"):
            continue
        targets.append({
            "営業先名": r.get("営業先名"),
            "カテゴリ": r.get("カテゴリ"),
            "優先度":   r.get("優先度"),
            "推定単価": r.get("推定単価"),
            "営業文":   r.get("営業文", "")[:200],
        })
        if len(targets) >= 5:
            break

    return {
        "ok": True,
        "today": _date_jst(),
        "targets": targets,
        "count": len(targets),
    }


def followup(spreadsheet_id: str, creds_path: str) -> dict:
    """フォロー期限超過・返信待ちのターゲットを返す"""
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    try:
        ws = ss.worksheet("CATERING_SALES_TARGETS")
    except gspread.WorksheetNotFound:
        return {"ok": True, "followup": [], "note": "シート未作成"}

    now    = datetime.now(JST)
    rows   = ws.get_all_records()
    result = []

    for r in rows:
        if r.get("成約状況") == "成約":
            continue
        dt_str = str(r.get("次回フォロー日", "")).strip()
        if not dt_str:
            continue
        try:
            dt = datetime.strptime(dt_str, "%Y/%m/%d").replace(tzinfo=JST)
            if dt.date() <= now.date():
                result.append({
                    "営業先名":     r.get("営業先名"),
                    "カテゴリ":     r.get("カテゴリ"),
                    "返信状況":     r.get("返信状況"),
                    "次回フォロー日": dt_str,
                })
        except (ValueError, TypeError):
            continue

    return {"ok": True, "followup": result, "count": len(result)}


def get_status(spreadsheet_id: str, creds_path: str) -> dict:
    """CATERING_SALES_TARGETSの統計を返す"""
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    try:
        ws = ss.worksheet("CATERING_SALES_TARGETS")
    except gspread.WorksheetNotFound:
        return {"ok": True, "total": 0, "note": "シート未作成"}

    rows  = ws.get_all_records()
    total = len(rows)
    status_count = {}
    priority_count = {}

    for r in rows:
        s = r.get("返信状況", "未送信")
        p = r.get("優先度", "B")
        status_count[s]   = status_count.get(s, 0) + 1
        priority_count[p] = priority_count.get(p, 0) + 1

    return {
        "ok": True,
        "total": total,
        "status": status_count,
        "priority": priority_count,
    }


def export_knowledge(spreadsheet_id: str, creds_path: str) -> dict:
    """成約・返信ありのターゲットをGCS Knowledge OSへ保存"""
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    try:
        ws = ss.worksheet("CATERING_SALES_TARGETS")
    except gspread.WorksheetNotFound:
        return {"ok": False, "error": "CATERING_SALES_TARGETS シート未作成"}

    rows     = ws.get_all_records()
    exported = []
    today    = _date_jst()

    for r in rows:
        if r.get("優先度") not in ("S", "A"):
            continue
        name = str(r.get("営業先名", "unknown")).replace(" ", "_")
        path = f"{GCS_PREFIX}/06_Leads_Sales/Trees_Catering/catering_{today}_{name[:20]}.md"

        md = (
            f"---\n"
            f"title: 営業先 — {r.get('営業先名', '')}\n"
            f"business: Trees Catering\n"
            f"category: catering_sales\n"
            f"date: {today}\n"
            f"priority: {r.get('優先度', '')}\n"
            f"source: catering_b2b_autopilot\n"
            f"status: {r.get('商談状況', '未商談')}\n"
            f"---\n\n"
            f"# ケータリング営業先 — {r.get('営業先名', '')}\n\n"
            f"## 基本情報\n"
            f"- カテゴリ: {r.get('カテゴリ', '')}\n"
            f"- 住所: {r.get('住所', '')}\n"
            f"- 推定単価: ¥{int(str(r.get('推定単価', 0) or 0)):,}\n"
            f"- 優先度: {r.get('優先度', '')}\n\n"
            f"## 想定ニーズ\n{r.get('想定ニーズ', '')}\n\n"
            f"## 営業文\n{r.get('営業文', '')}\n\n"
            f"## 商談記録\n"
            f"- 初回アプローチ: {r.get('初回アプローチ日', '未実施')}\n"
            f"- 最終接触: {r.get('最終接触日', '未接触')}\n"
            f"- 返信状況: {r.get('返信状況', '未送信')}\n"
            f"- 商談状況: {r.get('商談状況', '未商談')}\n"
            f"- 成約状況: {r.get('成約状況', '未成約')}\n"
            f"- 実売上: ¥{int(str(r.get('実売上', 0) or 0)):,}\n"
        )

        url = _upload_md_gcs(creds_path, path, md)
        exported.append({"path": path, "name": r.get("営業先名"), "url": url})

    return {
        "ok": True,
        "exported": len(exported),
        "files": [e["path"] for e in exported],
    }
