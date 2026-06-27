"""
YU BUSINESS OS - 汎用週次レポート生成

事業設定（BusinessConfig）を受け取り、
その事業用の週次レポートを生成してスプレッドシートへ書き込む。
"""

import os, json
from datetime import datetime, timedelta, date
from openai import OpenAI
import gspread
from google.oauth2.service_account import Credentials


def get_gc(creds_path: str):
    creds = Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return gspread.authorize(creds)


def get_week_range(target_date: date = None):
    if target_date is None:
        target_date = date.today()
    monday = target_date - timedelta(days=target_date.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def date_in_range(date_str: str, start: date, end: date) -> bool:
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            d = datetime.strptime(date_str.strip(), fmt).date()
            return start <= d <= end
        except ValueError:
            continue
    return False


def fetch_weekly_data(ss, config: dict, week_start: date, week_end: date) -> dict:
    target = config.get("monthly_target", 1_000_000)

    try:
        sales_rows = ss.worksheet("②売上入力").get_all_values()[1:]
    except Exception:
        sales_rows = []

    week_sales    = [r for r in sales_rows if len(r) >= 3 and date_in_range(r[0], week_start, week_end)]
    total_sales   = sum(int(r[2].replace(",", "").replace("円", "")) for r in week_sales
                        if r[2].replace(",", "").lstrip("-").isdigit())
    new_customers = sum(1 for r in week_sales if len(r) >= 4 and r[3] == "新規")
    repeat_cust   = sum(1 for r in week_sales if len(r) >= 4 and r[3] == "再来")

    menu_sales: dict = {}
    for r in week_sales:
        menu = r[1] if len(r) >= 2 else "不明"
        try:
            amt = int(r[2].replace(",", ""))
        except Exception:
            amt = 0
        menu_sales[menu] = menu_sales.get(menu, 0) + amt

    media_counts: dict = {}
    for r in week_sales:
        media = r[6] if len(r) >= 7 else "不明"
        if media:
            media_counts[media] = media_counts.get(media, 0) + 1

    try:
        booking_rows = ss.worksheet("③予約入力").get_all_values()[1:]
    except Exception:
        booking_rows = []

    week_bookings = [r for r in booking_rows if len(r) >= 1 and date_in_range(r[0], week_start, week_end)]
    cancellations = sum(1 for r in week_bookings if len(r) >= 7 and "キャンセル" in r[6])

    month_start = date(week_end.year, week_end.month, 1)
    month_rows  = [r for r in sales_rows if len(r) >= 3 and date_in_range(r[0], month_start, week_end)]
    month_total = sum(int(r[2].replace(",", "")) for r in month_rows
                      if r[2].replace(",", "").lstrip("-").isdigit())

    total_visitors = new_customers + repeat_cust
    avg_spend      = round(total_sales / total_visitors) if total_visitors > 0 else 0

    return {
        "week_start":       week_start.strftime("%Y/%m/%d"),
        "week_end":         week_end.strftime("%Y/%m/%d"),
        "total_sales":      total_sales,
        "new_customers":    new_customers,
        "repeat_customers": repeat_cust,
        "total_visitors":   total_visitors,
        "avg_spend":        avg_spend,
        "menu_sales":       menu_sales,
        "media_counts":     media_counts,
        "total_bookings":   len(week_bookings),
        "cancellations":    cancellations,
        "month_total":      month_total,
        "monthly_target":   target,
        "remaining":        target - month_total,
        "achievement_rate": round(month_total / target * 100, 1) if target > 0 else 0,
    }


def generate_ai_report(config: dict, data: dict) -> dict:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    name     = config["name"]
    location = config.get("location", "")
    services = "・".join(config.get("services", []))

    today = date.today()
    if today.month == 12:
        next_month_start = date(today.year + 1, 1, 1)
    else:
        next_month_start = date(today.year, today.month + 1, 1)
    remaining_days = (next_month_start - today).days

    menu_text  = "\n".join([f"  ・{k}: {v:,}円" for k, v in sorted(data["menu_sales"].items(), key=lambda x: -x[1])]) or "  ・データなし"
    media_text = "\n".join([f"  ・{k}: {v}件" for k, v in sorted(data["media_counts"].items(), key=lambda x: -x[1])]) or "  ・データなし"

    prompt = f"""あなたは{name}（{location}）の財務責任者AIです。
今週の経営データを分析して、オーナーへの週次レポートを日本語で作成してください。
事業内容: {services}

【今週データ（{data['week_start']} 〜 {data['week_end']}）】
今週売上: {data['total_sales']:,}円
来客・利用数: {data['total_visitors']}人（新規{data['new_customers']}人・再来{data['repeat_customers']}人）
客単価: {data['avg_spend']:,}円
予約数: {data['total_bookings']}件　キャンセル: {data['cancellations']}件

メニュー・サービス別売上:
{menu_text}

集客媒体別:
{media_text}

【今月累計（月初〜今日）】
今月累計: {data['month_total']:,}円
月商目標: {data['monthly_target']:,}円
達成率: {data['achievement_rate']}%
目標まで残り: {data['remaining']:,}円
今月残り日数: {remaining_days}日

【分析ルール】
・具体的な数字を必ず使う
・Markdownの##や###は絶対に使わない
・値引き・クーポン提案は禁止
・改善提案は「誰が・いつ・何をする」レベルで具体的に
・{name}の強みを活かした施策のみ提案

以下のJSON形式で返してください:
{{
  "summary": "今週の総括（3〜4文。数字を使って具体的に）",
  "good_points": ["良かった点1", "良かった点2", "良かった点3"],
  "issues": ["課題1（具体的な数字付き）", "課題2", "課題3"],
  "remaining_strategy": "月商目標達成に向けた残り{remaining_days}日の具体的施策（3つ）",
  "next_week_actions": [
    {{"priority": 1, "action": "具体的なアクション", "expected_result": "期待効果"}},
    {{"priority": 2, "action": "具体的なアクション", "expected_result": "期待効果"}},
    {{"priority": 3, "action": "具体的なアクション", "expected_result": "期待効果"}}
  ],
  "one_line": "今週を一言で（15文字以内）"
}}"""

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.7,
    )
    return json.loads(resp.choices[0].message.content)


def write_report(ss, data: dict, analysis: dict):
    try:
        sheet = ss.worksheet("週次レポート")
    except gspread.WorksheetNotFound:
        sheet = ss.add_worksheet(title="週次レポート", rows=2000, cols=4)
        sheet.append_row(["生成日時", "週", "項目", "内容"])

    now   = datetime.now().strftime("%Y/%m/%d %H:%M")
    week  = f"{data['week_start']}〜{data['week_end']}"
    today = date.today()
    if today.month == 12:
        nm = date(today.year + 1, 1, 1)
    else:
        nm = date(today.year, today.month + 1, 1)
    rd = (nm - today).days

    rows = [
        [now, week, "━━━ 週次レポート ━━━", ""],
        [now, week, "【総括】", analysis.get("one_line", "")],
        [now, week, "サマリー", analysis.get("summary", "")],
        [now, week, "", ""],
        [now, week, "今週売上", f"{data['total_sales']:,}円"],
        [now, week, "来客・利用数", f"{data['total_visitors']}人（新規{data['new_customers']}・再来{data['repeat_customers']}）"],
        [now, week, "客単価", f"{data['avg_spend']:,}円"],
        [now, week, "予約", f"{data['total_bookings']}件（キャンセル{data['cancellations']}件）"],
        [now, week, "", ""],
        [now, week, "今月累計", f"{data['month_total']:,}円 / {data['monthly_target']:,}円（{data['achievement_rate']}%）"],
        [now, week, "目標まで残り", f"{data['remaining']:,}円"],
        [now, week, "残り日数での必要日商", f"約{data['remaining'] // max(rd, 1):,}円/日"],
        [now, week, "目標達成戦略", analysis.get("remaining_strategy", "")],
        [now, week, "", ""],
        [now, week, "良かった点", ""],
    ]
    for i, p in enumerate(analysis.get("good_points", []), 1):
        rows.append([now, week, f"  良い点{i}", p])
    rows.append([now, week, "", ""])
    rows.append([now, week, "今週の課題", ""])
    for i, issue in enumerate(analysis.get("issues", []), 1):
        rows.append([now, week, f"  課題{i}", issue])
    rows.append([now, week, "", ""])
    rows.append([now, week, "来週のアクション（優先順位順）", ""])
    for act in analysis.get("next_week_actions", []):
        rows.append([now, week,
                     f"  優先{act.get('priority')}：{act.get('action', '')}",
                     f"期待効果：{act.get('expected_result', '')}"])
    rows.append([now, week, "━━━━━━━━━━━━━━━━━━━━", ""])
    rows.append([now, week, "", ""])

    sheet.append_rows(rows, value_input_option="RAW")


def notify_line(config: dict, data: dict, analysis: dict):
    """スタッフLINEチャンネルへ週次サマリーを通知"""
    try:
        import requests
        channels = config.get("line_channels", {})
        staff_ch = channels.get("staff", {})
        token    = os.getenv(staff_ch.get("env_key", ""), "")
        if len(token) < 100:
            return

        actions = analysis.get("next_week_actions", [])
        top     = actions[0].get("action", "") if actions else ""
        name    = config["name"]

        msg = (
            f"📊 {name} 週次レポート\n"
            f"（{data['week_start']}〜{data['week_end']}）\n\n"
            f"今週売上: {data['total_sales']:,}円\n"
            f"今月累計: {data['month_total']:,}円（達成率{data['achievement_rate']}%）\n"
            f"目標まで残り: {data['remaining']:,}円\n\n"
            f"【来週の最優先アクション】\n{top}\n\n"
            f"詳細はスプレッドシートで確認してください。"
        )

        requests.post(
            "https://api.line.me/v2/bot/message/broadcast",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"messages": [{"type": "text", "text": msg}]},
            timeout=10,
        )
        print(f"  LINE通知送信完了: {name}")
    except Exception as e:
        print(f"  LINE通知スキップ: {e}")


def run(config: dict, spreadsheet_id: str, creds_path: str, target_date: date = None) -> dict:
    print(f"[週次レポート] {config['name']} 生成開始")

    if target_date is None:
        target_date = date.today()
    week_start, week_end = get_week_range(target_date)

    gc = get_gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)

    data     = fetch_weekly_data(ss, config, week_start, week_end)
    analysis = generate_ai_report(config, data)
    write_report(ss, data, analysis)
    notify_line(config, data, analysis)

    print(f"[週次レポート] 完了: {analysis.get('one_line', '')}")
    return {"ok": True, "week": f"{week_start}〜{week_end}", **{k: data[k] for k in ["total_sales", "month_total", "achievement_rate", "remaining"]}, "one_line": analysis.get("one_line", "")}
