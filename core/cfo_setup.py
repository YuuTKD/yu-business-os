"""
YU BUSINESS OS - 汎用CFO Spreadsheet セットアップ

事業設定を受け取り、その事業用の財務OSスプレッドシートを構築する。
シート構成は全事業共通（8シート）。事業固有の数値・ラベルのみ差し替える。
"""

import os, time
import gspread
from gspread.utils import rowcol_to_a1
from google.oauth2.service_account import Credentials


def rgb(r, g, b):
    return {"red": r/255, "green": g/255, "blue": b/255}

DARK_GREEN  = rgb(39, 100, 75)
LIGHT_GREEN = rgb(209, 236, 220)
DARK_GRAY   = rgb(60, 60, 60)
LIGHT_GRAY  = rgb(245, 245, 245)
GOLD        = rgb(212, 175, 55)
WHITE       = rgb(255, 255, 255)
RED_LIGHT   = rgb(252, 228, 228)
BLUE_LIGHT  = rgb(219, 234, 254)


def get_gc(creds_path: str):
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds)


def get_or_create(ss, title, rows=200, cols=20):
    try:
        sh = ss.worksheet(title)
        sh.clear()
    except gspread.WorksheetNotFound:
        sh = ss.add_worksheet(title=title, rows=rows, cols=cols)
    return sh


def fmt_header(sheet, row, c1, c2, text, bg, fg=None):
    if fg is None:
        fg = WHITE
    a1 = rowcol_to_a1(row, c1)
    b1 = rowcol_to_a1(row, c2)
    sheet.format(f"{a1}:{b1}", {
        "backgroundColor": bg,
        "textFormat": {"bold": True, "fontSize": 11, "foregroundColor": fg},
        "horizontalAlignment": "CENTER",
        "verticalAlignment": "MIDDLE",
    })


def setup_all(spreadsheet_id: str, config: dict, creds_path: str):
    """
    全8シートを構築してスプレッドシートURLを返す。
    config: BUSINESSES[short_name]
    """
    gc = get_gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)

    name    = config["name"]
    target  = config.get("monthly_target", 1_000_000)
    services = config.get("services", ["サービス"])

    print(f"[CFO Setup] {name} スプレッドシート構築開始")

    # 構築順序：参照元シートを先に、ダッシュボードを最後に
    _setup_sales_input(ss, services)
    _setup_booking_input(ss, services)
    _setup_expense_input(ss)
    _setup_kpi(ss, target)
    _setup_menu_analysis(ss, services)
    _setup_weekly_report(ss)
    _setup_monthly_report(ss, name)
    _setup_improvements(ss)
    _setup_csv_log(ss)
    _setup_dashboard(ss, name, target)  # 最後

    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
    print(f"[CFO Setup] 完了: {url}")
    return url


def _setup_sales_input(ss, services: list):
    sh = get_or_create(ss, "②売上入力", rows=500, cols=10)
    categories = "/".join(services)
    headers = ["日付", f"メニュー（{categories}）", "売上(円)", "顧客区分\n(新規/再来)", "担当者", "決済方法", "予約媒体", "備考"]
    sh.append_row(headers, value_input_option="RAW")
    fmt_header(sh, 1, 1, len(headers), "②売上入力", DARK_GREEN)
    print("  ②売上入力 完了")
    time.sleep(1)


def _setup_booking_input(ss, services: list):
    sh = get_or_create(ss, "③予約入力", rows=500, cols=10)
    headers = ["予約日", "来店/利用日", "メニュー", "新規/再来", "予約媒体", "担当者", "キャンセル", "備考"]
    sh.append_row(headers, value_input_option="RAW")
    fmt_header(sh, 1, 1, len(headers), "③予約入力", DARK_GREEN)
    print("  ③予約入力 完了")
    time.sleep(1)


def _setup_expense_input(ss):
    sh = get_or_create(ss, "④経費入力", rows=300, cols=8)
    headers = ["日付", "科目", "金額(円)", "支払先", "支払方法", "領収書", "備考"]
    expense_categories = [
        ["─ 科目例 ─", "", "", "", "", "", ""],
        ["", "原材料費", "食材・消耗品", "", "", "", ""],
        ["", "人件費", "スタッフ給与・アルバイト", "", "", "", ""],
        ["", "家賃", "テナント・駐車場", "", "", "", ""],
        ["", "水道光熱費", "電気・水道・ガス", "", "", "", ""],
        ["", "広告宣伝費", "SNS広告・チラシ", "", "", "", ""],
        ["", "通信費", "Wi-Fi・スマホ", "", "", "", ""],
        ["", "その他", "", "", "", "", ""],
    ]
    sh.append_row(headers, value_input_option="RAW")
    sh.append_rows(expense_categories, value_input_option="RAW")
    fmt_header(sh, 1, 1, len(headers), "④経費入力", DARK_GREEN)
    print("  ④経費入力 完了")
    time.sleep(1)


def _setup_kpi(ss, monthly_target: int):
    sh = get_or_create(ss, "⑤KPI管理", rows=50, cols=6)
    rows = [
        ["⑤ KPI管理", "", "", "", "", ""],
        ["", "", "", "", "", ""],
        ["項目", "今月実績", "目標", "達成率", "前月比", "判定"],
        ["月間売上", f"=SUMIF('②売上入力'!A:A,TEXT(TODAY(),\"YYYY/MM\")&\"*\",'②売上入力'!C:C)",
         monthly_target,
         "=IF(C4>0,TEXT(B4/C4,\"0.0%\"),\"-\")", "", "=IF(B4>=C4,\"✅ 達成\",\"⚠ 未達\")"],
        ["月間来客数", "=COUNTIF('②売上入力'!A:A,TEXT(TODAY(),\"YYYY/MM\")&\"*\")", 80, "=IF(C5>0,TEXT(B5/C5,\"0.0%\"),\"-\")", "", ""],
        ["新規比率", "=COUNTIFS('②売上入力'!A:A,TEXT(TODAY(),\"YYYY/MM\")&\"*\",'②売上入力'!D:D,\"新規\")/MAX(B5,1)", 0.3, "=IF(C6>0,TEXT(B6/C6,\"0.0%\"),\"-\")", "", ""],
        ["リピート率", "=1-B6", 0.7, "=IF(C7>0,TEXT(B7/C7,\"0.0%\"),\"-\")", "", ""],
        ["客単価", "=IF(B5>0,B4/B5,0)", 8000, "=IF(C8>0,TEXT(B8/C8,\"0.0%\"),\"-\")", "", ""],
        ["キャンセル率", "=COUNTIF('③予約入力'!G:G,\"キャンセル\")/MAX(COUNTA('③予約入力'!A:A)-1,1)", 0.05, "=IF(C9>0,TEXT(B9/C9,\"0.0%\"),\"-\")", "", ""],
    ]
    sh.append_rows(rows, value_input_option="USER_ENTERED")
    fmt_header(sh, 1, 1, 6, "⑤ KPI管理", DARK_GREEN)
    fmt_header(sh, 3, 1, 6, "KPI項目ヘッダー", DARK_GRAY)
    print("  ⑤KPI管理 完了")
    time.sleep(1)


def _setup_menu_analysis(ss, services: list):
    sh = get_or_create(ss, "⑥メニュー分析", rows=50, cols=6)
    rows = [["⑥ メニュー分析", "", "", "", "", ""],
            ["", "", "", "", "", ""],
            ["メニュー", "今月売上(円)", "構成比", "来客数", "客単価", "前月比"]]
    for svc in services:
        rows.append([
            svc,
            f"=SUMIF('②売上入力'!B:B,\"{svc}\",'②売上入力'!C:C)",
            f"=IF(SUMIF('②売上入力'!B:B,\"{svc}\",'②売上入力'!C:C)>0,SUMIF('②売上入力'!B:B,\"{svc}\",'②売上入力'!C:C)/SUM('②売上入力'!C:C),0)",
            f"=COUNTIF('②売上入力'!B:B,\"{svc}\")",
            "",
            "",
        ])
    sh.append_rows(rows, value_input_option="USER_ENTERED")
    fmt_header(sh, 1, 1, 6, "⑥ メニュー分析", DARK_GREEN)
    fmt_header(sh, 3, 1, 6, "メニューヘッダー", DARK_GRAY)
    print("  ⑥メニュー分析 完了")
    time.sleep(1)


def _setup_weekly_report(ss):
    sh = get_or_create(ss, "週次レポート", rows=2000, cols=4)
    sh.append_row(["生成日時", "週", "項目", "内容"], value_input_option="RAW")
    fmt_header(sh, 1, 1, 4, "週次レポートヘッダー", DARK_GREEN)
    print("  週次レポート 完了")
    time.sleep(1)


def _setup_monthly_report(ss, name: str):
    sh = get_or_create(ss, "⑦月次レポート", rows=200, cols=4)
    sh.append_row([f"{name} 月次レポート（自動生成）", "", "", ""], value_input_option="RAW")
    fmt_header(sh, 1, 1, 4, "⑦月次レポートヘッダー", DARK_GREEN)
    print("  ⑦月次レポート 完了")
    time.sleep(1)


def _setup_improvements(ss):
    sh = get_or_create(ss, "⑧改善提案", rows=200, cols=4)
    sh.append_row(["生成日時", "優先度", "改善施策", "期待効果"], value_input_option="RAW")
    fmt_header(sh, 1, 1, 4, "⑧改善提案ヘッダー", DARK_GREEN)
    print("  ⑧改善提案 完了")
    time.sleep(1)


def _setup_csv_log(ss):
    try:
        ss.worksheet("CSV取込ログ")
    except gspread.WorksheetNotFound:
        sh = ss.add_worksheet(title="CSV取込ログ", rows=500, cols=6)
        sh.append_row(["処理日時", "ファイル名", "種別", "件数", "ステータス", "メモ"])
        fmt_header(sh, 1, 1, 6, "CSV取込ログヘッダー", DARK_GRAY)
    print("  CSV取込ログ 完了")
    time.sleep(1)


def _setup_dashboard(ss, name: str, monthly_target: int):
    sh = get_or_create(ss, "①経営ダッシュボード", rows=60, cols=8)
    now = __import__("datetime").datetime.now().strftime("%Y/%m/%d")

    rows = [
        [f"【 {name} 経営ダッシュボード 】", "", "", "", "", "", "", ""],
        [f"最終更新: {now}", "", "", "", "", "", "", ""],
        ["", "", "", "", "", "", "", ""],
        ["📊 今月のKPI", "", "", "", "", "", "", ""],
        ["月商目標", monthly_target, "円", "今月売上", "=⑤KPI管理!B4", "円", "達成率", "=⑤KPI管理!D4"],
        ["今月来客", "=⑤KPI管理!B5", "人", "客単価", "=⑤KPI管理!B8", "円", "", ""],
        ["新規比率", "=⑤KPI管理!B6", "", "リピート率", "=⑤KPI管理!B7", "", "", ""],
        ["", "", "", "", "", "", "", ""],
        ["📈 メニュー別売上（今月）", "", "", "", "", "", "", ""],
    ]
    sh.append_rows(rows, value_input_option="USER_ENTERED")
    fmt_header(sh, 1, 1, 8, f"{name} ダッシュボード", DARK_GREEN)
    fmt_header(sh, 4, 1, 8, "KPIセクション", DARK_GRAY)
    print("  ①経営ダッシュボード 完了")
    time.sleep(1)
