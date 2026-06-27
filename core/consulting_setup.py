"""
Consulting OS - 汎用コンサルティング スプレッドシート構築

パスタパスタ・Z1 共通構造。
10シート：クライアント台帳・案件管理・請求・売上・利益・コンテンツ・レポート
"""

import time
import gspread
from gspread.utils import rowcol_to_a1
from google.oauth2.service_account import Credentials


def rgb(r, g, b):
    return {"red": r/255, "green": g/255, "blue": b/255}

NAVY   = rgb(15, 23, 42)
GOLD   = rgb(212, 175, 55)
GREEN  = rgb(39, 100, 75)
ORANGE = rgb(234, 88, 12)
BLUE   = rgb(30, 64, 175)
L_BLUE = rgb(219, 234, 254)
GRAY   = rgb(60, 60, 60)
L_GRAY = rgb(245, 245, 245)
WHITE  = rgb(255, 255, 255)
PURPLE = rgb(88, 28, 135)


def get_gc(creds_path: str):
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds)


def get_or_create(ss, title, rows=300, cols=20):
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
    target = config.get("monthly_target", 2_000_000)
    sh.update(range_name="A1:L1", values=[[f"{biz} - KPI ダッシュボード"] + [""] * 11])
    hdr(sh, 1, 1, 12, bg=NAVY, fg=GOLD)

    rows = [
        ["", ""],
        ["📊 今月のKPI", ""],
        ["アクティブクライアント数", f"=COUNTIF('02_クライアント台帳'!I3:I1000,\"契約中\")"],
        ["今月新規受注件数",         f"=COUNTIFS('03_案件管理'!B3:B1000,TEXT(TODAY(),\"yyyy/mm/*\"),'03_案件管理'!E3:E1000,\"受注\")"],
        ["今月売上合計",             f"=SUMIF('05_売上管理'!A3:A1000,TEXT(TODAY(),\"yyyy/mm\"),'05_売上管理'!C3:C1000)"],
        ["今月利益合計",             f"=SUMIF('06_利益管理'!A3:A1000,TEXT(TODAY(),\"yyyy/mm\"),'06_利益管理'!D3:D1000)"],
        ["月目標",                   target],
        ["達成率（%）",              "=IF(B8=0,0,ROUND(B6/B8*100,1))"],
        ["未請求件数",               f"=COUNTIF('04_請求管理'!F3:F1000,\"未請求\")"],
        ["", ""],
        ["📈 月別推移", ""],
        ["月", "売上", "利益", "粗利率", "新規受注", "達成率"],
    ]
    sh.update(range_name="A2:L13", values=[r + [""] * (12 - len(r)) for r in rows])
    col_hdr(sh, 3, 1, 2, bg=ORANGE)
    for r in range(4, 10):
        col_hdr(sh, r, 1, 1, bg=L_GRAY, fg=GRAY)
    hdr(sh, 12, 1, 6, bg=GREEN, size=10)
    pause()
    print("  ✅ 01_KPI")


# ─────────────────────────────────────────────
# 02_クライアント台帳
# ─────────────────────────────────────────────
def setup_clients(ss):
    sh = get_or_create(ss, "02_クライアント台帳")
    sh.update(range_name="A1:O1", values=[["02 クライアント台帳"] + [""] * 14])
    hdr(sh, 1, 1, 15, bg=PURPLE, fg=WHITE)
    headers = [
        "クライアントID", "企業名", "業種", "所在地", "担当者名",
        "電話番号", "メールアドレス", "契約開始日", "契約状況", "月次顧問料",
        "年間売上", "累計支援実績", "担当コンサル", "特記事項", ""
    ]
    sh.update(range_name="A2:O2", values=[headers])
    col_hdr(sh, 2, 1, 14)
    pause()
    print("  ✅ 02_クライアント台帳")


# ─────────────────────────────────────────────
# 03_案件管理
# ─────────────────────────────────────────────
def setup_projects(ss):
    sh = get_or_create(ss, "03_案件管理")
    sh.update(range_name="A1:N1", values=[["03 案件管理"] + [""] * 13])
    hdr(sh, 1, 1, 14, bg=BLUE, fg=WHITE)
    headers = [
        "案件番号", "受注日", "クライアント名", "案件名", "受注状況",
        "サービス種別", "契約金額", "期間（月数）", "月次売上", "支援内容",
        "担当コンサル", "納品物", "完了日", ""
    ]
    sh.update(range_name="A2:N2", values=[headers])
    col_hdr(sh, 2, 1, 13)
    pause()
    print("  ✅ 03_案件管理")


# ─────────────────────────────────────────────
# 04_請求管理
# ─────────────────────────────────────────────
def setup_billing(ss):
    sh = get_or_create(ss, "04_請求管理")
    sh.update(range_name="A1:K1", values=[["04 請求管理"] + [""] * 10])
    hdr(sh, 1, 1, 11, bg=GREEN, fg=WHITE)
    headers = [
        "請求番号", "請求日", "クライアント名", "案件名", "請求金額",
        "請求状況", "入金予定日", "入金日", "入金確認", "備考", ""
    ]
    sh.update(range_name="A2:K2", values=[headers])
    col_hdr(sh, 2, 1, 10)
    pause()
    print("  ✅ 04_請求管理")


# ─────────────────────────────────────────────
# 05_売上管理
# ─────────────────────────────────────────────
def setup_sales(ss):
    sh = get_or_create(ss, "05_売上管理")
    sh.update(range_name="A1:J1", values=[["05 売上管理"] + [""] * 9])
    hdr(sh, 1, 1, 10, bg=GREEN, fg=WHITE)
    headers = [
        "月", "売上日", "クライアント名", "売上金額", "サービス種別",
        "案件番号", "入金状況", "担当", "備考", ""
    ]
    sh.update(range_name="A2:J2", values=[headers])
    col_hdr(sh, 2, 1, 9)
    pause()
    print("  ✅ 05_売上管理")


# ─────────────────────────────────────────────
# 06_利益管理
# ─────────────────────────────────────────────
def setup_profit(ss):
    sh = get_or_create(ss, "06_利益管理")
    sh.update(range_name="A1:K1", values=[["06 利益管理"] + [""] * 10])
    hdr(sh, 1, 1, 11, bg=GREEN, fg=WHITE)
    headers = [
        "月", "売上", "外注費", "交通費", "その他原価",
        "粗利", "粗利率", "経費按分", "営業利益", "営業利益率", ""
    ]
    sh.update(range_name="A2:K2", values=[headers])
    col_hdr(sh, 2, 1, 10)
    pause()
    print("  ✅ 06_利益管理")


# ─────────────────────────────────────────────
# 07_改善提案ログ
# ─────────────────────────────────────────────
def setup_proposals(ss):
    sh = get_or_create(ss, "07_改善提案ログ")
    sh.update(range_name="A1:J1", values=[["07 改善提案ログ（支援実績）"] + [""] * 9])
    hdr(sh, 1, 1, 10, bg=NAVY, fg=GOLD)
    headers = [
        "日付", "クライアント名", "提案カテゴリ", "提案内容", "実施状況",
        "効果測定", "改善数値", "SNS化", "備考", ""
    ]
    sh.update(range_name="A2:J2", values=[headers])
    col_hdr(sh, 2, 1, 9)
    pause()
    print("  ✅ 07_改善提案ログ")


# ─────────────────────────────────────────────
# 08_Google投稿
# ─────────────────────────────────────────────
def setup_google_posts(ss):
    sh = get_or_create(ss, "08_Google投稿")
    sh.update(range_name="A1:I1", values=[["08 Google投稿（90日分）"] + [""] * 8])
    hdr(sh, 1, 1, 9, bg=NAVY, fg=GOLD)
    sh.update(range_name="A2:I2", values=[["No", "投稿日", "カテゴリ", "タイトル", "本文", "ハッシュタグ", "投稿状況", "投稿日時", "備考"]])
    col_hdr(sh, 2, 1, 9)
    pause()
    print("  ✅ 08_Google投稿")


# ─────────────────────────────────────────────
# 09_月次レポート
# ─────────────────────────────────────────────
def setup_monthly_report(ss):
    sh = get_or_create(ss, "09_月次レポート")
    sh.update(range_name="A1:L1", values=[["09 月次レポート"] + [""] * 11])
    hdr(sh, 1, 1, 12, bg=NAVY, fg=GOLD)
    sh.update(range_name="A2:L2", values=[[
        "生成日時", "対象月", "売上", "利益", "粗利率",
        "新規受注", "クライアント数", "達成率", "AI総評（COO）",
        "AI財務（CFO）", "改善提案", ""
    ]])
    col_hdr(sh, 2, 1, 11)
    pause()
    print("  ✅ 09_月次レポート")


# ─────────────────────────────────────────────
# 10_AI分析
# ─────────────────────────────────────────────
def setup_ai_analysis(ss):
    sh = get_or_create(ss, "10_AI分析")
    sh.update(range_name="A1:I1", values=[["10 AI分析レポート"] + [""] * 8])
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
    print("  ✅ 10_AI分析")


# ─────────────────────────────────────────────
# メイン実行
# ─────────────────────────────────────────────
def setup_all(spreadsheet_id: str, config: dict, creds_path: str) -> str:
    biz = config["name"]
    print(f"\n{'='*55}")
    print(f"{biz} Consulting OS - スプレッドシート構築開始")
    print(f"{'='*55}")

    gc = get_gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)

    try:
        ss.update_title(f"{biz} Consulting OS")
        print(f"  📋 タイトル設定: {biz} Consulting OS")
    except Exception as e:
        print(f"  ⚠ タイトル更新スキップ: {e}")

    print("\n[シート構築中...]")
    setup_kpi(ss, config)
    setup_clients(ss)
    setup_projects(ss)
    setup_billing(ss)
    setup_sales(ss)
    setup_profit(ss)
    setup_proposals(ss)
    setup_google_posts(ss)
    setup_monthly_report(ss)
    setup_ai_analysis(ss)

    for default_name in ["Sheet1", "シート1"]:
        try:
            ss.del_worksheet(ss.worksheet(default_name))
            print(f"  🗑  {default_name} 削除")
        except Exception:
            pass

    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
    print(f"\n✅ {biz} Consulting OS 全10シート構築完了")
    print(f"   {url}")
    print("=" * 55 + "\n")
    return url
