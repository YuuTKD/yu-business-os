"""
TREES CATERING OS - スプレッドシート初期構築

Beautyの8シートと異なる、ケータリング事業特化の14シート構造。
問い合わせ→見積→受注→顧客台帳→財務→コンテンツ→レポートの一気通貫構造。
"""

import time
import gspread
from gspread.utils import rowcol_to_a1
from google.oauth2.service_account import Credentials


# ─── カラーパレット ───────────────────────────────
def rgb(r, g, b):
    return {"red": r/255, "green": g/255, "blue": b/255}

NAVY   = rgb(15, 23, 42)
GOLD   = rgb(212, 175, 55)
GREEN  = rgb(39, 100, 75)
L_GREEN = rgb(209, 236, 220)
ORANGE = rgb(234, 88, 12)
L_ORANGE = rgb(255, 237, 213)
BLUE   = rgb(30, 64, 175)
L_BLUE = rgb(219, 234, 254)
GRAY   = rgb(60, 60, 60)
L_GRAY = rgb(245, 245, 245)
WHITE  = rgb(255, 255, 255)
RED    = rgb(185, 28, 28)
L_RED  = rgb(252, 228, 228)


def get_gc(creds_path: str):
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds)


def get_or_create(ss, title, rows=500, cols=30):
    try:
        sh = ss.worksheet(title)
        sh.clear()
    except gspread.WorksheetNotFound:
        sh = ss.add_worksheet(title=title, rows=rows, cols=cols)
    return sh


def hdr(sheet, r, c1, c2, bg=NAVY, fg=WHITE, bold=True, size=11):
    a = rowcol_to_a1(r, c1)
    b = rowcol_to_a1(r, c2)
    sheet.format(f"{a}:{b}", {
        "backgroundColor": bg,
        "textFormat": {"bold": bold, "fontSize": size, "foregroundColor": fg},
        "horizontalAlignment": "CENTER",
        "verticalAlignment": "MIDDLE",
    })


def col_hdr(sheet, r, c1, c2, bg=GREEN, fg=WHITE):
    hdr(sheet, r, c1, c2, bg=bg, fg=fg, size=10)


def sleep():
    time.sleep(0.8)


# ─────────────────────────────────────────────────────────────
# 01_KPI ダッシュボード
# ─────────────────────────────────────────────────────────────
def setup_kpi(ss):
    sh = get_or_create(ss, "01_KPI", rows=50, cols=15)
    sh.update("A1:O1", [["TREES CATERING OS - KPI ダッシュボード"] + [""] * 14])
    hdr(sh, 1, 1, 15, bg=NAVY, fg=GOLD)

    rows = [
        ["", ""],
        ["📊 今月のKPI", ""],
        ["問い合わせ件数", "=COUNTA('02_問い合わせ'!B3:B1000)"],
        ["見積件数",       "=COUNTIF('03_見積'!E3:E1000,\"提出済\")"],
        ["受注件数",       "=COUNTIF('04_受注管理'!E3:E1000,\"受注\")"],
        ["受注率（%）",    "=IF(B5=0,0,ROUND(B6/B5*100,1))"],
        ["今月売上合計",   "=SUMIF('06_売上管理'!A3:A1000,TEXT(TODAY(),\"yyyy/mm\"),\'06_売上管理\'!D3:D1000)"],
        ["今月利益合計",   "=SUMIF('07_利益管理'!A3:A1000,TEXT(TODAY(),\"yyyy/mm\"),\'07_利益管理\'!D3:D1000)"],
        ["粗利率（%）",    "=IF(B8=0,0,ROUND(B9/B8*100,1))"],
        ["", ""],
        ["📈 月別推移", ""],
        ["月", "問い合わせ", "見積", "受注", "受注率", "売上", "利益", "粗利率"],
    ]
    sh.update("A2:O13", [r + [""] * (15 - len(r)) for r in rows])
    col_hdr(sh, 3, 1, 2, bg=ORANGE, fg=WHITE)
    for r in range(4, 11):
        col_hdr(sh, r, 1, 1, bg=L_GRAY, fg=GRAY)
    hdr(sh, 13, 1, 8, bg=GREEN, fg=WHITE, size=10)
    sleep()
    print("  ✅ 01_KPI")


# ─────────────────────────────────────────────────────────────
# 02_問い合わせ
# ─────────────────────────────────────────────────────────────
def setup_inquiry(ss):
    sh = get_or_create(ss, "02_問い合わせ", rows=500, cols=15)
    sh.update("A1:O1", [["02 問い合わせ管理"] + [""] * 14])
    hdr(sh, 1, 1, 15, bg=BLUE, fg=WHITE)

    headers = [
        "問い合わせ日", "企業名", "担当者名", "電話番号", "メールアドレス",
        "問い合わせ内容", "案件詳細", "希望日程", "人数規模", "予算感",
        "対応状況", "次のアクション", "担当スタッフ", "メモ", "経路"
    ]
    sh.update("A2:O2", [headers])
    col_hdr(sh, 2, 1, 15)

    samples = [
        ["2026/06/01", "株式会社サンプル", "山田太郎", "098-XXX-XXXX", "yamada@sample.com",
         "会議用弁当", "20名×週3回", "2026/07〜", "20名", "〜1,500円/個",
         "見積提出済", "受注確認連絡", "tokuda", "", "WEB"],
    ]
    sh.update("A3:O3", samples)
    sleep()
    print("  ✅ 02_問い合わせ")


# ─────────────────────────────────────────────────────────────
# 03_見積
# ─────────────────────────────────────────────────────────────
def setup_estimate(ss):
    sh = get_or_create(ss, "03_見積", rows=300, cols=15)
    sh.update("A1:O1", [["03 見積管理"] + [""] * 14])
    hdr(sh, 1, 1, 15, bg=BLUE, fg=WHITE)

    headers = [
        "見積番号", "問い合わせ日", "企業名", "案件名", "見積状況",
        "見積金額", "見積提出日", "有効期限", "サービス種別", "数量/規模",
        "単価", "原価", "粗利", "粗利率", "備考"
    ]
    sh.update("A2:O2", [headers])
    col_hdr(sh, 2, 1, 15)
    sleep()
    print("  ✅ 03_見積")


# ─────────────────────────────────────────────────────────────
# 04_受注管理
# ─────────────────────────────────────────────────────────────
def setup_orders(ss):
    sh = get_or_create(ss, "04_受注管理", rows=300, cols=15)
    sh.update("A1:O1", [["04 受注管理"] + [""] * 14])
    hdr(sh, 1, 1, 15, bg=GREEN, fg=WHITE)

    headers = [
        "受注番号", "受注日", "企業名", "案件名", "受注状況",
        "納品日", "サービス種別", "受注金額", "原価", "粗利",
        "入金状況", "入金日", "請求書番号", "担当スタッフ", "備考"
    ]
    sh.update("A2:O2", [headers])
    col_hdr(sh, 2, 1, 15)
    sleep()
    print("  ✅ 04_受注管理")


# ─────────────────────────────────────────────────────────────
# 05_顧客台帳
# ─────────────────────────────────────────────────────────────
def setup_customers(ss):
    sh = get_or_create(ss, "05_顧客台帳", rows=300, cols=20)
    sh.update("A1:T1", [["05 顧客台帳"] + [""] * 19])
    hdr(sh, 1, 1, 20, bg=NAVY, fg=GOLD)

    headers = [
        "顧客ID", "企業名", "業種", "住所", "担当者名",
        "電話番号", "メールアドレス", "初回取引日", "最終取引日", "取引回数",
        "累計売上", "累計利益", "主要サービス", "リピート区分", "優先度",
        "担当スタッフ", "請求先", "特記事項", "契約状況", "紹介元"
    ]
    sh.update("A2:T2", [headers])
    col_hdr(sh, 2, 1, 20)
    sleep()
    print("  ✅ 05_顧客台帳")


# ─────────────────────────────────────────────────────────────
# 06_売上管理
# ─────────────────────────────────────────────────────────────
def setup_sales(ss):
    sh = get_or_create(ss, "06_売上管理", rows=500, cols=15)
    sh.update("A1:O1", [["06 売上管理"] + [""] * 14])
    hdr(sh, 1, 1, 15, bg=GREEN, fg=WHITE)

    headers = [
        "月", "売上日", "企業名", "売上金額", "サービス種別",
        "受注番号", "入金状況", "入金日", "担当スタッフ", "備考",
        "", "", "", "", ""
    ]
    sh.update("A2:O2", [headers])
    col_hdr(sh, 2, 1, 10)
    sleep()
    print("  ✅ 06_売上管理")


# ─────────────────────────────────────────────────────────────
# 07_利益管理
# ─────────────────────────────────────────────────────────────
def setup_profit(ss):
    sh = get_or_create(ss, "07_利益管理", rows=500, cols=15)
    sh.update("A1:O1", [["07 利益管理"] + [""] * 14])
    hdr(sh, 1, 1, 15, bg=GREEN, fg=WHITE)

    headers = [
        "月", "対象日", "企業名", "売上", "原材料費",
        "外注費", "その他原価", "粗利", "粗利率", "経費按分",
        "営業利益", "受注番号", "備考", "", ""
    ]
    sh.update("A2:O2", [headers])
    col_hdr(sh, 2, 1, 13)

    # 自動計算式のサンプル行（説明用）
    formula_row = [
        "=TEXT(B3,\"yyyy/mm\")", "2026/06/01", "顧客企業名", 100000, 35000,
        10000, 5000, "=D3-E3-F3-G3", "=ROUND(H3/D3*100,1)", 5000,
        "=H3-J3", "ORD-001", ""
    ]
    sh.update("A3:M3", [formula_row], value_input_option="USER_ENTERED")
    sleep()
    print("  ✅ 07_利益管理")


# ─────────────────────────────────────────────────────────────
# 08_Google投稿
# ─────────────────────────────────────────────────────────────
def setup_google_posts(ss):
    sh = get_or_create(ss, "08_Google投稿", rows=200, cols=10)
    sh.update("A1:J1", [["08 Google投稿コンテンツ（90日分）"] + [""] * 9])
    hdr(sh, 1, 1, 10, bg=NAVY, fg=GOLD)

    headers = ["No", "投稿日", "カテゴリ", "タイトル", "本文（500文字以内）",
               "ハッシュタグ", "投稿状況", "投稿日時", "備考", ""]
    sh.update("A2:J2", [headers])
    col_hdr(sh, 2, 1, 9)
    sleep()
    print("  ✅ 08_Google投稿")


# ─────────────────────────────────────────────────────────────
# 09_Instagram
# ─────────────────────────────────────────────────────────────
def setup_instagram(ss):
    sh = get_or_create(ss, "09_Instagram", rows=200, cols=10)
    sh.update("A1:J1", [["09 Instagram投稿コンテンツ（90日分）"] + [""] * 9])
    hdr(sh, 1, 1, 10, bg=NAVY, fg=GOLD)

    headers = ["No", "投稿日", "カテゴリ", "キャプション", "ハッシュタグ",
               "画像メモ", "投稿状況", "いいね数", "備考", ""]
    sh.update("A2:J2", [headers])
    col_hdr(sh, 2, 1, 9)
    sleep()
    print("  ✅ 09_Instagram")


# ─────────────────────────────────────────────────────────────
# 10_Threads
# ─────────────────────────────────────────────────────────────
def setup_threads(ss):
    sh = get_or_create(ss, "10_Threads", rows=200, cols=10)
    sh.update("A1:J1", [["10 Threads投稿コンテンツ（90日分）"] + [""] * 9])
    hdr(sh, 1, 1, 10, bg=NAVY, fg=GOLD)

    headers = ["No", "投稿日", "カテゴリ", "本文（500文字以内）", "ハッシュタグ",
               "投稿状況", "", "", "", ""]
    sh.update("A2:J2", [headers])
    col_hdr(sh, 2, 1, 6)
    sleep()
    print("  ✅ 10_Threads")


# ─────────────────────────────────────────────────────────────
# 11_LINE
# ─────────────────────────────────────────────────────────────
def setup_line(ss):
    sh = get_or_create(ss, "11_LINE", rows=200, cols=10)
    sh.update("A1:J1", [["11 LINE配信コンテンツ（90日分）"] + [""] * 9])
    hdr(sh, 1, 1, 10, bg=NAVY, fg=GOLD)

    headers = ["No", "配信日", "カテゴリ", "件名", "本文",
               "CTA", "配信状況", "開封率", "備考", ""]
    sh.update("A2:J2", [headers])
    col_hdr(sh, 2, 1, 9)
    sleep()
    print("  ✅ 11_LINE")


# ─────────────────────────────────────────────────────────────
# 12_口コミ
# ─────────────────────────────────────────────────────────────
def setup_reviews(ss):
    sh = get_or_create(ss, "12_口コミ", rows=200, cols=10)
    sh.update("A1:J1", [["12 口コミ・お客様の声"] + [""] * 9])
    hdr(sh, 1, 1, 10, bg=NAVY, fg=GOLD)

    headers = ["日付", "企業名", "担当者", "媒体", "評価（5段階）",
               "口コミ内容", "返信済", "SNS活用", "許諾", ""]
    sh.update("A2:J2", [headers])
    col_hdr(sh, 2, 1, 9)
    sleep()
    print("  ✅ 12_口コミ")


# ─────────────────────────────────────────────────────────────
# 13_月次レポート
# ─────────────────────────────────────────────────────────────
def setup_monthly_report(ss):
    sh = get_or_create(ss, "13_月次レポート", rows=200, cols=15)
    sh.update("A1:O1", [["13 月次レポート"] + [""] * 14])
    hdr(sh, 1, 1, 15, bg=NAVY, fg=GOLD)

    rows = [
        ["生成日時", "対象月", "問い合わせ数", "見積数", "受注数", "受注率",
         "売上", "利益", "粗利率", "新規顧客", "リピート顧客", "AI総評（COO）", "AI財務（CFO）", "改善提案", ""],
    ]
    sh.update("A2:O2", rows)
    col_hdr(sh, 2, 1, 14)
    sleep()
    print("  ✅ 13_月次レポート")


# ─────────────────────────────────────────────────────────────
# 14_AI分析
# ─────────────────────────────────────────────────────────────
def setup_ai_analysis(ss):
    sh = get_or_create(ss, "14_AI分析", rows=200, cols=10)
    sh.update("A1:J1", [["14 AI分析レポート"] + [""] * 9])
    hdr(sh, 1, 1, 10, bg=NAVY, fg=GOLD)

    rows = [
        ["分析日時", "種別", "分析対象期間", "AI分析内容", "重要度", "アクション", "担当", "期限", "完了", ""],
        ["", "週次", "今週", "（毎週月曜日に自動生成）", "高", "", "AI COO", "", "", ""],
        ["", "月次", "今月", "（毎月1日に自動生成）", "高", "", "AI CFO", "", "", ""],
    ]
    sh.update("A2:J4", rows)
    col_hdr(sh, 2, 1, 9)
    sleep()
    print("  ✅ 14_AI分析")


# ─────────────────────────────────────────────────────────────
# メイン実行
# ─────────────────────────────────────────────────────────────
def setup_all(spreadsheet_id: str, creds_path: str) -> str:
    print("\n" + "=" * 55)
    print("TREES CATERING OS - スプレッドシート構築開始")
    print("=" * 55)

    gc = get_gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)

    # スプレッドシート名を確認・設定
    try:
        ss.update_title("TREES CATERING OS")
        print("  📋 スプレッドシート名: TREES CATERING OS")
    except Exception as e:
        print(f"  ⚠ タイトル更新スキップ: {e}")

    print("\n[シート構築中...]")
    setup_kpi(ss)
    setup_inquiry(ss)
    setup_estimate(ss)
    setup_orders(ss)
    setup_customers(ss)
    setup_sales(ss)
    setup_profit(ss)
    setup_google_posts(ss)
    setup_instagram(ss)
    setup_threads(ss)
    setup_line(ss)
    setup_reviews(ss)
    setup_monthly_report(ss)
    setup_ai_analysis(ss)

    # デフォルトのSheet1を削除
    try:
        default = ss.worksheet("Sheet1")
        ss.del_worksheet(default)
        print("  🗑  デフォルトSheet1 削除")
    except Exception:
        pass

    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
    print(f"\n✅ TREES CATERING OS 構築完了")
    print(f"   {url}")
    print("=" * 55 + "\n")
    return url
