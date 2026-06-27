"""
Restaurant OS - 汎用レストラン・バー スプレッドシート構築

TACHINOMIYA（立呑み居酒屋）・琉球火鍋 共通構造。
13シート：日次売上・予約・顧客・メニュー分析・経費・利益・コンテンツ・レポート
"""

import time
import gspread
from gspread.utils import rowcol_to_a1
from google.oauth2.service_account import Credentials


def rgb(r, g, b):
    return {"red": r/255, "green": g/255, "blue": b/255}

NAVY    = rgb(15, 23, 42)
GOLD    = rgb(212, 175, 55)
GREEN   = rgb(39, 100, 75)
ORANGE  = rgb(234, 88, 12)
L_ORANGE= rgb(255, 237, 213)
L_GREEN = rgb(209, 236, 220)
GRAY    = rgb(60, 60, 60)
L_GRAY  = rgb(245, 245, 245)
WHITE   = rgb(255, 255, 255)
BLUE    = rgb(30, 64, 175)


def get_gc(creds_path: str):
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds)


def get_or_create(ss, title, rows=500, cols=20):
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


def pause():
    time.sleep(0.8)


# ─────────────────────────────────────────────
# 01_KPI
# ─────────────────────────────────────────────
def setup_kpi(ss, config: dict):
    sh = get_or_create(ss, "01_KPI")
    biz = config["name"]
    sh.update(range_name="A1:P1", values=[[f"{biz} - KPI ダッシュボード"] + [""] * 15])
    hdr(sh, 1, 1, 16, bg=NAVY, fg=GOLD)

    target = config.get("monthly_target", 1_000_000)
    rows = [
        ["", ""],
        ["📊 今月のKPI", ""],
        ["今月売上合計",   f"=SUMIF('02_日次売上'!A3:A1000,TEXT(TODAY(),\"yyyy/mm\"),'02_日次売上'!C3:C1000)"],
        ["今月客数",       f"=SUMIF('02_日次売上'!A3:A1000,TEXT(TODAY(),\"yyyy/mm\"),'02_日次売上'!D3:D1000)"],
        ["客単価（平均）", "=IF(B5=0,0,ROUND(B4/B5))"],
        ["月目標",         target],
        ["達成率（%）",    "=IF(B7=0,0,ROUND(B4/B7*100,1))"],
        ["予約件数",       f"=COUNTIF('03_予約管理'!A3:A1000,TEXT(TODAY(),\"yyyy/mm/*\"))"],
        ["", ""],
        ["📈 月別推移", ""],
        ["月", "売上", "客数", "客単価", "達成率", "利益"],
    ]
    sh.update(range_name="A2:P12", values=[r + [""] * (16 - len(r)) for r in rows])
    col_hdr(sh, 3, 1, 2, bg=ORANGE)
    for r in range(4, 9):
        col_hdr(sh, r, 1, 1, bg=L_GRAY, fg=GRAY)
    hdr(sh, 12, 1, 6, bg=GREEN, size=10)
    pause()
    print("  ✅ 01_KPI")


# ─────────────────────────────────────────────
# 02_日次売上
# ─────────────────────────────────────────────
def setup_daily_sales(ss):
    sh = get_or_create(ss, "02_日次売上")
    sh.update(range_name="A1:L1", values=[["02 日次売上"] + [""] * 11])
    hdr(sh, 1, 1, 12, bg=GREEN, fg=WHITE)
    headers = [
        "月", "日付", "売上金額", "客数", "客単価",
        "テーブル数", "回転数", "現金", "カード", "QR決済",
        "メモ", ""
    ]
    sh.update(range_name="A2:L2", values=[headers])
    col_hdr(sh, 2, 1, 11)
    # 計算式サンプル行
    sh.update(range_name="A3:L3", values=[[
        '=TEXT(B3,"yyyy/mm")', "2026/06/01", 0, 0,
        "=IF(D3=0,0,ROUND(C3/D3))", 0, "", 0, 0, 0, "", ""
    ]], value_input_option="USER_ENTERED")
    pause()
    print("  ✅ 02_日次売上")


# ─────────────────────────────────────────────
# 03_予約管理
# ─────────────────────────────────────────────
def setup_reservations(ss):
    sh = get_or_create(ss, "03_予約管理")
    sh.update(range_name="A1:L1", values=[["03 予約管理"] + [""] * 11])
    hdr(sh, 1, 1, 12, bg=BLUE, fg=WHITE)
    headers = [
        "予約日時", "来店日時", "氏名", "人数", "電話番号",
        "予約内容", "コース", "金額目安", "状況", "チャネル",
        "備考", ""
    ]
    sh.update(range_name="A2:L2", values=[headers])
    col_hdr(sh, 2, 1, 11)
    pause()
    print("  ✅ 03_予約管理")


# ─────────────────────────────────────────────
# 04_顧客台帳
# ─────────────────────────────────────────────
def setup_customers(ss):
    sh = get_or_create(ss, "04_顧客台帳")
    sh.update(range_name="A1:N1", values=[["04 顧客台帳"] + [""] * 13])
    hdr(sh, 1, 1, 14, bg=NAVY, fg=GOLD)
    headers = [
        "顧客ID", "氏名", "電話番号", "メール", "初回来店日",
        "最終来店日", "来店回数", "累計売上", "区分", "誕生月",
        "LINE登録", "特記事項", "担当", ""
    ]
    sh.update(range_name="A2:N2", values=[headers])
    col_hdr(sh, 2, 1, 13)
    pause()
    print("  ✅ 04_顧客台帳")


# ─────────────────────────────────────────────
# 05_メニュー分析
# ─────────────────────────────────────────────
def setup_menu_analysis(ss, config: dict):
    sh = get_or_create(ss, "05_メニュー分析")
    sh.update(range_name="A1:J1", values=[["05 メニュー分析"] + [""] * 9])
    hdr(sh, 1, 1, 10, bg=NAVY, fg=GOLD)
    headers = [
        "カテゴリ", "メニュー名", "販売価格", "原価", "粗利",
        "粗利率", "今月注文数", "今月売上", "ランキング", "備考"
    ]
    sh.update(range_name="A2:J2", values=[headers])
    col_hdr(sh, 2, 1, 9)
    # サービス別サンプルデータ
    services = config.get("services", ["メニューA", "メニューB", "メニューC"])
    sample_rows = [[s, "", 0, 0, "=IF(C-D>0,C-D,0)", "", 0, 0, "", ""] for s in services[:5]]
    if sample_rows:
        sh.update(range_name=f"A3:J{2+len(sample_rows)}", values=sample_rows)
    pause()
    print("  ✅ 05_メニュー分析")


# ─────────────────────────────────────────────
# 06_経費管理
# ─────────────────────────────────────────────
def setup_expenses(ss):
    sh = get_or_create(ss, "06_経費管理")
    sh.update(range_name="A1:J1", values=[["06 経費管理"] + [""] * 9])
    hdr(sh, 1, 1, 10, bg=NAVY, fg=GOLD)
    headers = [
        "月", "日付", "費目", "内容", "金額",
        "支払方法", "仕訳", "領収書", "メモ", ""
    ]
    sh.update(range_name="A2:J2", values=[headers])
    col_hdr(sh, 2, 1, 9)

    # 主要費目一覧
    expense_categories = [
        "食材費", "飲料費", "人件費", "水道光熱費", "家賃",
        "広告費", "消耗品費", "修繕費", "その他"
    ]
    rows = [["", "", cat, "", 0, "", "", "", ""] for cat in expense_categories]
    sh.update(range_name="A3:I11", values=rows)
    pause()
    print("  ✅ 06_経費管理")


# ─────────────────────────────────────────────
# 07_利益管理
# ─────────────────────────────────────────────
def setup_profit(ss):
    sh = get_or_create(ss, "07_利益管理")
    sh.update(range_name="A1:J1", values=[["07 利益管理"] + [""] * 9])
    hdr(sh, 1, 1, 10, bg=GREEN, fg=WHITE)
    headers = [
        "月", "売上", "原価合計", "粗利", "粗利率",
        "経費合計", "営業利益", "営業利益率", "メモ", ""
    ]
    sh.update(range_name="A2:J2", values=[headers])
    col_hdr(sh, 2, 1, 9)
    pause()
    print("  ✅ 07_利益管理")


# ─────────────────────────────────────────────
# コンテンツシート（Google/Instagram/Threads/LINE）
# ─────────────────────────────────────────────
def setup_google_posts(ss):
    sh = get_or_create(ss, "08_Google投稿")
    sh.update(range_name="A1:I1", values=[["08 Google投稿（90日分）"] + [""] * 8])
    hdr(sh, 1, 1, 9, bg=NAVY, fg=GOLD)
    sh.update(range_name="A2:I2", values=[["No", "投稿日", "カテゴリ", "タイトル", "本文", "ハッシュタグ", "投稿状況", "投稿日時", "備考"]])
    col_hdr(sh, 2, 1, 9)
    pause()
    print("  ✅ 08_Google投稿")


def setup_instagram(ss):
    sh = get_or_create(ss, "09_Instagram")
    sh.update(range_name="A1:I1", values=[["09 Instagram（90日分）"] + [""] * 8])
    hdr(sh, 1, 1, 9, bg=NAVY, fg=GOLD)
    sh.update(range_name="A2:I2", values=[["No", "投稿日", "カテゴリ", "キャプション", "ハッシュタグ", "画像メモ", "投稿状況", "いいね数", "備考"]])
    col_hdr(sh, 2, 1, 9)
    pause()
    print("  ✅ 09_Instagram")


def setup_threads(ss):
    sh = get_or_create(ss, "10_Threads")
    sh.update(range_name="A1:G1", values=[["10 Threads（90日分）"] + [""] * 6])
    hdr(sh, 1, 1, 7, bg=NAVY, fg=GOLD)
    sh.update(range_name="A2:G2", values=[["No", "投稿日", "カテゴリ", "本文", "ハッシュタグ", "投稿状況", "備考"]])
    col_hdr(sh, 2, 1, 7)
    pause()
    print("  ✅ 10_Threads")


def setup_line(ss):
    sh = get_or_create(ss, "11_LINE")
    sh.update(range_name="A1:I1", values=[["11 LINE配信（90日分）"] + [""] * 8])
    hdr(sh, 1, 1, 9, bg=NAVY, fg=GOLD)
    sh.update(range_name="A2:I2", values=[["No", "配信日", "カテゴリ", "件名", "本文", "CTA", "配信状況", "開封率", "備考"]])
    col_hdr(sh, 2, 1, 9)
    pause()
    print("  ✅ 11_LINE")


# ─────────────────────────────────────────────
# 12_月次レポート
# ─────────────────────────────────────────────
def setup_monthly_report(ss):
    sh = get_or_create(ss, "12_月次レポート")
    sh.update(range_name="A1:M1", values=[["12 月次レポート"] + [""] * 12])
    hdr(sh, 1, 1, 13, bg=NAVY, fg=GOLD)
    sh.update(range_name="A2:M2", values=[[
        "生成日時", "対象月", "売上", "客数", "客単価",
        "達成率", "利益", "粗利率", "前月比", "AI総評（COO）",
        "AI財務（CFO）", "改善提案", ""
    ]])
    col_hdr(sh, 2, 1, 12)
    pause()
    print("  ✅ 12_月次レポート")


# ─────────────────────────────────────────────
# 13_AI分析
# ─────────────────────────────────────────────
def setup_ai_analysis(ss):
    sh = get_or_create(ss, "13_AI分析")
    sh.update(range_name="A1:I1", values=[["13 AI分析レポート"] + [""] * 8])
    hdr(sh, 1, 1, 9, bg=NAVY, fg=GOLD)
    sh.update(range_name="A2:I2", values=[[
        "分析日時", "種別", "分析対象", "AI分析内容",
        "重要度", "アクション", "担当", "期限", "完了"
    ]])
    col_hdr(sh, 2, 1, 9)
    sh.update(range_name="A3:I4", values=[
        ["", "週次", "今週", "（毎週月曜日に自動生成）", "高", "", "AI COO", "", ""],
        ["", "月次", "今月", "（毎月1日に自動生成）",   "高", "", "AI CFO", "", ""],
    ])
    pause()
    print("  ✅ 13_AI分析")


# ─────────────────────────────────────────────
# メイン実行
# ─────────────────────────────────────────────
def setup_all(spreadsheet_id: str, config: dict, creds_path: str) -> str:
    biz = config["name"]
    print(f"\n{'='*55}")
    print(f"{biz} OS - スプレッドシート構築開始")
    print(f"{'='*55}")

    gc = get_gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)

    try:
        ss.update_title(f"{biz} OS")
        print(f"  📋 タイトル設定: {biz} OS")
    except Exception as e:
        print(f"  ⚠ タイトル更新スキップ: {e}")

    print("\n[シート構築中...]")
    setup_kpi(ss, config)
    setup_daily_sales(ss)
    setup_reservations(ss)
    setup_customers(ss)
    setup_menu_analysis(ss, config)
    setup_expenses(ss)
    setup_profit(ss)
    setup_google_posts(ss)
    setup_instagram(ss)
    setup_threads(ss)
    setup_line(ss)
    setup_monthly_report(ss)
    setup_ai_analysis(ss)

    # デフォルトシート削除
    for default_name in ["Sheet1", "シート1"]:
        try:
            ss.del_worksheet(ss.worksheet(default_name))
            print(f"  🗑  {default_name} 削除")
        except Exception:
            pass

    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
    print(f"\n✅ {biz} OS 全13シート構築完了")
    print(f"   {url}")
    print("=" * 55 + "\n")
    return url
