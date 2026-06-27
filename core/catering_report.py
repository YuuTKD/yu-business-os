"""
TREES CATERING OS - 週次・月次レポート自動生成

問い合わせ→見積→受注→利益の全データを読み込み、
AI COO/CFOが分析してLINEスタッフチャンネルへ送信。
CEO Dashboardへも連携。
"""

import os, json, time, requests
from datetime import date, timedelta
from openai import OpenAI
import gspread
from google.oauth2.service_account import Credentials

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

CATERING_SS_ID = os.getenv("CATERING_SPREADSHEET_ID", "")
LINE_STAFF_TOKEN = os.getenv("CATERING_LINE_STAFF_TOKEN", "")
MONTHLY_TARGET = int(os.getenv("CATERING_MONTHLY_TARGET", "800000"))


def get_gc(creds_path: str):
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds)


def _line_notify(token: str, message: str):
    if len(token) < 100:
        print(f"[LINE] トークン未設定のためスキップ")
        return
    try:
        requests.post(
            "https://api.line.me/v2/bot/message/broadcast",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"messages": [{"type": "text", "text": message}]},
            timeout=10,
        )
        print("[LINE] Catering スタッフチャンネル送信完了")
    except Exception as e:
        print(f"[LINE] エラー: {e}")


def fetch_catering_data(gc, ss_id: str) -> dict:
    """全シートからKPIデータを集計"""
    today = date.today()
    month_prefix = today.strftime("%Y/%m")

    try:
        ss = gc.open_by_key(ss_id)
    except Exception as e:
        return {"error": str(e)}

    data = {
        "inquiries": 0, "estimates": 0, "orders": 0,
        "month_sales": 0, "month_profit": 0,
        "new_customers": 0, "repeat_customers": 0,
    }

    # 02_問い合わせ
    try:
        rows = ss.worksheet("02_問い合わせ").get_all_values()[2:]
        data["inquiries"] = sum(1 for r in rows if r and r[0].startswith(month_prefix[:4]))
    except Exception:
        pass

    # 03_見積
    try:
        rows = ss.worksheet("03_見積").get_all_values()[2:]
        data["estimates"] = sum(1 for r in rows if r and len(r) >= 5 and r[4] in ["提出済", "検討中"])
    except Exception:
        pass

    # 04_受注管理
    try:
        rows = ss.worksheet("04_受注管理").get_all_values()[2:]
        data["orders"] = sum(1 for r in rows if r and len(r) >= 5 and r[4] == "受注")
    except Exception:
        pass

    # 06_売上管理
    try:
        rows = ss.worksheet("06_売上管理").get_all_values()[2:]
        for r in rows:
            if r and r[0].startswith(month_prefix):
                try:
                    data["month_sales"] += int(str(r[3]).replace(",", "").replace("¥", ""))
                except Exception:
                    pass
    except Exception:
        pass

    # 07_利益管理
    try:
        rows = ss.worksheet("07_利益管理").get_all_values()[2:]
        for r in rows:
            if r and r[0].startswith(month_prefix):
                try:
                    data["month_profit"] += int(str(r[7]).replace(",", "").replace("¥", ""))
                except Exception:
                    pass
    except Exception:
        pass

    data["order_rate"] = round(data["orders"] / data["estimates"] * 100, 1) if data["estimates"] > 0 else 0
    data["gross_margin"] = round(data["month_profit"] / data["month_sales"] * 100, 1) if data["month_sales"] > 0 else 0
    data["target"] = MONTHLY_TARGET
    data["achievement_rate"] = round(data["month_sales"] / MONTHLY_TARGET * 100, 1) if MONTHLY_TARGET > 0 else 0
    return data


def generate_catering_analysis(data: dict) -> dict:
    prompt = f"""あなたはYU HOLDINGSのAI COO兼CFOです。
Trees Cateringの今週のKPIを分析し、スタッフへのブリーフィングを作成してください。

【今月のKPI】
問い合わせ件数: {data['inquiries']}件
見積件数: {data['estimates']}件
受注件数: {data['orders']}件
受注率: {data['order_rate']}%
売上: {data['month_sales']:,}円（月目標{data['target']:,}円 / 達成率{data['achievement_rate']}%）
利益: {data['month_profit']:,}円（粗利率{data['gross_margin']}%）

【ルール】
・値引き・クーポン提案は禁止
・「誰が・いつ・何をする」の具体的指示
・数字を必ず含める

JSON形式で返してください:
{{
  "weekly_summary": "今週の総評（3文、数字必須）",
  "top3_actions": [
    {{"priority": 1, "action": "具体的アクション", "expected": "期待効果"}},
    {{"priority": 2, "action": "具体的アクション", "expected": "期待効果"}},
    {{"priority": 3, "action": "具体的アクション", "expected": "期待効果"}}
  ],
  "sales_comment": "売上コメント（達成率を含む1文）",
  "profit_comment": "利益コメント（粗利率を含む1文）",
  "order_rate_comment": "受注率コメント（改善提案含む1文）",
  "one_line": "今週を一言で（15文字以内）"
}}"""

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.65,
    )
    return json.loads(resp.choices[0].message.content)


def write_weekly_report(gc, ss_id: str, data: dict, analysis: dict):
    """14_AI分析シートに週次レポートを追記"""
    try:
        ss = gc.open_by_key(ss_id)
        sh = ss.worksheet("14_AI分析")
        now_str = date.today().strftime("%Y/%m/%d")
        week_range = f"{(date.today() - timedelta(days=6)).strftime('%m/%d')}〜{date.today().strftime('%m/%d')}"

        top3_text = " / ".join([f"{a['priority']}.{a['action']}" for a in analysis.get("top3_actions", [])])

        new_row = [
            now_str, "週次", week_range,
            f"{analysis.get('weekly_summary', '')} | TOP3: {top3_text}",
            "高", top3_text[:50], "AI COO", "", ""
        ]
        sh.append_row(new_row, value_input_option="RAW")
        print("[週次レポート] 14_AI分析 書き込み完了")
    except Exception as e:
        print(f"[週次レポート] エラー: {e}")


def send_staff_line(data: dict, analysis: dict):
    """スタッフLINEへ週次ブリーフィング送信"""
    top3 = analysis.get("top3_actions", [])
    actions = "\n".join([f"{a['priority']}. {a['action']}" for a in top3[:3]])

    msg = (
        f"📦 Trees Catering 週次レポート\n"
        f"({date.today().strftime('%Y/%m/%d')} 集計)\n\n"
        f"【今月のKPI】\n"
        f"問い合わせ: {data['inquiries']}件\n"
        f"見積: {data['estimates']}件\n"
        f"受注: {data['orders']}件（受注率{data['order_rate']}%）\n"
        f"売上: {data['month_sales']:,}円（達成率{data['achievement_rate']}%）\n"
        f"利益: {data['month_profit']:,}円（粗利{data['gross_margin']}%）\n\n"
        f"【今週やること TOP3】\n{actions}\n\n"
        f"AI分析: {analysis.get('one_line', '')}"
    )
    _line_notify(LINE_STAFF_TOKEN, msg)


def run_weekly(creds_path: str) -> dict:
    print("\n[Catering] 週次レポート生成開始")
    ss_id = CATERING_SS_ID
    if not ss_id:
        return {"ok": False, "error": "CATERING_SPREADSHEET_ID 未設定"}

    gc = get_gc(creds_path)
    data = fetch_catering_data(gc, ss_id)
    if "error" in data:
        return {"ok": False, "error": data["error"]}

    analysis = generate_catering_analysis(data)
    write_weekly_report(gc, ss_id, data, analysis)
    send_staff_line(data, analysis)

    print("[Catering] 週次レポート完了")
    return {"ok": True, "data": data, "analysis": analysis}


def run_monthly(creds_path: str) -> dict:
    """月次レポート（毎月1日実行）"""
    print("\n[Catering] 月次レポート生成開始")
    ss_id = CATERING_SS_ID
    if not ss_id:
        return {"ok": False, "error": "CATERING_SPREADSHEET_ID 未設定"}

    gc = get_gc(creds_path)
    data = fetch_catering_data(gc, ss_id)
    if "error" in data:
        return {"ok": False, "error": data["error"]}

    analysis = generate_catering_analysis(data)

    # 13_月次レポートに追記
    try:
        ss = gc.open_by_key(ss_id)
        sh = ss.worksheet("13_月次レポート")
        last_month = (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y/%m")
        new_row = [
            date.today().strftime("%Y/%m/%d %H:%M"),
            last_month,
            data["inquiries"], data["estimates"], data["orders"],
            f"{data['order_rate']}%",
            data["month_sales"], data["month_profit"],
            f"{data['gross_margin']}%",
            "", "",
            analysis.get("weekly_summary", ""),
            analysis.get("profit_comment", ""),
            " / ".join([a["action"] for a in analysis.get("top3_actions", [])[:3]]),
        ]
        sh.append_row(new_row, value_input_option="RAW")
        print("[Catering] 月次レポート書き込み完了")
    except Exception as e:
        print(f"[Catering] 月次レポートエラー: {e}")

    return {"ok": True, "type": "monthly", "data": data}
