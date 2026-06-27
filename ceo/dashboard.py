"""
YU CEO Dashboard - 全事業統合ダッシュボード

全事業のスプレッドシートから月次データを集約し、
CEOが一画面で全事業の状態を把握できるマスターシートを構築する。

実行: python3 ceo/dashboard.py
または Cloud Run /ceo-dashboard エンドポイントから
"""

import os, sys, json, time
from datetime import datetime, date

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

import gspread
from google.oauth2.service_account import Credentials
from openai import OpenAI

from configs.business_registry import BUSINESSES

CEO_SPREADSHEET_ID = os.getenv("CEO_SPREADSHEET_ID", "")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def rgb(r, g, b):
    return {"red": r/255, "green": g/255, "blue": b/255}

DARK_NAVY   = rgb(15, 23, 42)
GOLD        = rgb(212, 175, 55)
GREEN_DARK  = rgb(39, 100, 75)
GREEN_LIGHT = rgb(209, 236, 220)
RED_DARK    = rgb(185, 28, 28)
RED_LIGHT   = rgb(252, 228, 228)
WHITE       = rgb(255, 255, 255)
GRAY        = rgb(100, 116, 139)


def get_gc(creds_path: str):
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds)


def fetch_business_data(gc, business_key: str, config: dict) -> dict:
    """各事業のスプレッドシートから当月データを取得"""
    sheet_id_env = config.get("spreadsheet_id_env", "")
    sheet_id     = os.getenv(sheet_id_env, "")

    if not sheet_id:
        return {
            "name": config["name"],
            "status": "no_spreadsheet",
            "monthly_target": config.get("monthly_target", 0),
            "month_total": 0,
            "achievement_rate": 0,
            "total_visitors": 0,
            "avg_spend": 0,
            "new_customers": 0,
            "repeat_customers": 0,
        }

    try:
        ss          = gc.open_by_key(sheet_id)
        sales_sheet = ss.worksheet("②売上入力")
        sales_rows  = sales_sheet.get_all_values()[1:]

        month_prefix = date.today().strftime("%Y/%m")
        month_sales  = [r for r in sales_rows if len(r) >= 3 and r[0].startswith(month_prefix)]
        total  = sum(int(r[2].replace(",", "")) for r in month_sales
                     if r[2].replace(",", "").lstrip("-").isdigit())
        new_c  = sum(1 for r in month_sales if len(r) >= 4 and r[3] == "新規")
        rep_c  = sum(1 for r in month_sales if len(r) >= 4 and r[3] == "再来")
        visits = new_c + rep_c
        target = config.get("monthly_target", 1)

        return {
            "name":             config["name"],
            "status":           "active",
            "monthly_target":   target,
            "month_total":      total,
            "achievement_rate": round(total / target * 100, 1) if target > 0 else 0,
            "remaining":        max(target - total, 0),
            "total_visitors":   visits,
            "new_customers":    new_c,
            "repeat_customers": rep_c,
            "avg_spend":        round(total / visits) if visits > 0 else 0,
        }
    except Exception as e:
        return {
            "name": config["name"],
            "status": f"error: {str(e)[:50]}",
            "monthly_target": config.get("monthly_target", 0),
            "month_total": 0,
            "achievement_rate": 0,
            "total_visitors": 0,
            "avg_spend": 0,
            "new_customers": 0,
            "repeat_customers": 0,
        }


def generate_ceo_insight(all_data: list[dict]) -> str:
    """全事業データをもとにCEO向けのAI総括を生成"""
    total_revenue = sum(d.get("month_total", 0) for d in all_data)
    total_target  = sum(d.get("monthly_target", 0) for d in all_data)
    overall_rate  = round(total_revenue / total_target * 100, 1) if total_target > 0 else 0

    business_summary = "\n".join([
        f"・{d['name']}: {d.get('month_total', 0):,}円（目標達成率{d.get('achievement_rate', 0)}%）"
        for d in all_data
    ])

    prompt = f"""あなたはYU（複数事業を経営するオーナー）の経営AIアドバイザーです。
今月の全事業データを分析し、CEOへの経営サマリーを作成してください。

【全事業今月実績】
合計売上: {total_revenue:,}円 / 合計目標: {total_target:,}円（総達成率: {overall_rate}%）

{business_summary}

【ルール】
・Markdownの##や###は使わない
・数字を必ず使った具体的な分析
・最も注力すべき事業を明確に指摘
・値引き・クーポン提案は禁止
・200文字以内で簡潔に

JSON形式で返してください:
{{
  "headline": "今月を一言で（20文字以内）",
  "summary": "全事業総括（3文以内・数字必須）",
  "top_priority": "最も重点を置くべき事業と理由（1文）",
  "risk_alert": "リスクがある事業・指標（1文）",
  "next_action": "来週CEOがやるべきことTop1（具体的）"
}}"""

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.6,
    )
    return json.loads(resp.choices[0].message.content)


def build_dashboard(creds_path: str):
    """CEOダッシュボードシートを更新"""
    gc  = get_gc(creds_path)
    ss  = gc.open_by_key(CEO_SPREADSHEET_ID)
    now = datetime.now().strftime("%Y/%m/%d %H:%M")
    month_label = date.today().strftime("%Y年%m月")

    print(f"[CEO Dashboard] {month_label} データ集約開始")

    # 全事業データ収集
    all_data = []
    for key, config in BUSINESSES.items():
        print(f"  {config['name']} データ取得中...")
        data = fetch_business_data(gc, key, config)
        all_data.append(data)
        time.sleep(0.5)

    # AI総括生成
    print("  AI総括生成中...")
    insight = generate_ceo_insight(all_data)

    # ダッシュボードシート更新
    try:
        sh = ss.worksheet("YU CEO Dashboard")
        sh.clear()
    except gspread.WorksheetNotFound:
        sh = ss.add_worksheet(title="YU CEO Dashboard", rows=80, cols=10)

    total_revenue = sum(d.get("month_total", 0) for d in all_data)
    total_target  = sum(d.get("monthly_target", 0) for d in all_data)
    overall_rate  = round(total_revenue / total_target * 100, 1) if total_target > 0 else 0

    rows = [
        # タイトル
        ["YU BUSINESS OS - CEO Dashboard", "", "", "", "", "", "", "", "", ""],
        [f"最終更新: {now}", "", "", "", "", "", "", "", "", ""],
        ["", "", "", "", "", "", "", "", "", ""],

        # AI総括
        ["【今月の総括】", insight.get("headline", ""), "", "", "", "", "", "", "", ""],
        ["サマリー", insight.get("summary", ""), "", "", "", "", "", "", "", ""],
        ["最重点事業", insight.get("top_priority", ""), "", "", "", "", "", "", "", ""],
        ["リスクアラート", insight.get("risk_alert", ""), "", "", "", "", "", "", "", ""],
        ["来週のアクション", insight.get("next_action", ""), "", "", "", "", "", "", "", ""],
        ["", "", "", "", "", "", "", "", "", ""],

        # 全事業合計
        ["【全事業合計】", "", "", "", "", "", "", "", "", ""],
        ["合計月商", f"{total_revenue:,}円", "合計目標", f"{total_target:,}円", "総達成率", f"{overall_rate}%", "", "", "", ""],
        ["", "", "", "", "", "", "", "", "", ""],

        # 事業別テーブルヘッダー
        ["事業名", "今月売上(円)", "月商目標(円)", "達成率(%)", "来客数", "新規", "再来", "客単価(円)", "残り(円)", "状態"],
    ]

    # 各事業の行
    for d in all_data:
        status_icon = "✅" if d.get("achievement_rate", 0) >= 80 else ("⚠" if d.get("achievement_rate", 0) >= 50 else "❌")
        rows.append([
            d["name"],
            d.get("month_total", 0),
            d.get("monthly_target", 0),
            d.get("achievement_rate", 0),
            d.get("total_visitors", 0),
            d.get("new_customers", 0),
            d.get("repeat_customers", 0),
            d.get("avg_spend", 0),
            d.get("remaining", 0),
            status_icon,
        ])

    rows.append(["", "", "", "", "", "", "", "", "", ""])

    sh.update(rows, value_input_option="RAW")

    # ヘッダー装飾
    sh.format("A1:J1", {
        "backgroundColor": DARK_NAVY,
        "textFormat": {"bold": True, "fontSize": 14, "foregroundColor": GOLD},
    })
    sh.format("A13:J13", {
        "backgroundColor": DARK_NAVY,
        "textFormat": {"bold": True, "foregroundColor": WHITE},
    })

    url = f"https://docs.google.com/spreadsheets/d/{CEO_SPREADSHEET_ID}"
    print(f"[CEO Dashboard] 完了: {url}")
    return {"ok": True, "total_revenue": total_revenue, "overall_rate": overall_rate, "url": url}


def setup_ceo_spreadsheet(creds_path: str):
    """CEOダッシュボード用スプレッドシートの初期構築"""
    gc = get_gc(creds_path)
    ss = gc.open_by_key(CEO_SPREADSHEET_ID)

    sheets_to_create = [
        ("YU CEO Dashboard", 80, 10),
        ("全事業月次推移", 200, 15),
        ("資金繰りサマリー", 100, 8),
        ("事業別KPI比較", 50, 12),
        ("改善優先順位", 100, 6),
    ]
    for title, rows, cols in sheets_to_create:
        try:
            ss.worksheet(title)
            print(f"  {title} 既存")
        except gspread.WorksheetNotFound:
            ss.add_worksheet(title=title, rows=rows, cols=cols)
            print(f"  {title} 作成")
        time.sleep(0.5)

    print("[CEO Spreadsheet] 初期構築完了")
    return f"https://docs.google.com/spreadsheets/d/{CEO_SPREADSHEET_ID}"


if __name__ == "__main__":
    from core.credentials_loader import load_google_credentials
    creds = load_google_credentials()
    if not CEO_SPREADSHEET_ID:
        print("CEO_SPREADSHEET_ID が設定されていません。")
        print("Google Sheetsで新しいスプレッドシートを作成し、IDを.envに設定してください。")
    else:
        build_dashboard(creds)
