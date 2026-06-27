"""
YU HOLDINGS AI Executive Team

AI COO - 全事業進捗管理・優先順位決定
AI CFO - 全事業財務管理・キャッシュフロー
AI CMO - 全媒体マーケティング統括
AI CTO - インフラ監視・障害検知

毎週月曜8:00に /executive-briefing エンドポイントから呼び出される。
結果はCEO DashboardシートとLINEに送信される。
"""

import os, json, time, requests
from datetime import datetime, date, timedelta
from openai import OpenAI
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MASTER_SS_ID = os.getenv("GOOGLE_SPREADSHEET_ID")  # YU HOLDINGS Master OS
LINE_STAFF_TOKEN = os.getenv("LINE_STAFF_TOKEN", "")


def get_gc(creds_path: str):
    creds = Credentials.from_service_account_file(creds_path, scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ])
    return gspread.authorize(creds), creds


def _line_notify(token: str, message: str):
    if len(token) < 100:
        return
    try:
        requests.post(
            "https://api.line.me/v2/bot/message/broadcast",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"messages": [{"type": "text", "text": message}]},
            timeout=10,
        )
    except Exception as e:
        print(f"LINE通知エラー: {e}")


# ─────────────────────────────────────────────
# 事業データ収集（全事業スプレッドシートを横断）
# ─────────────────────────────────────────────

# ─── 事業ごとの売上シート・カラム定義 ───────────────────────────
# sales_sheet: 売上が記録されているシート名
# date_col: 日付列のインデックス（0始まり）
# amount_col: 売上金額列のインデックス（0始まり）
# month_format: 日付の月プレフィックス形式（"yyyy/mm" または "yyyy/mm/"）

BUSINESS_TARGETS = {
    "Tree Beauty": {
        "target": 500_000, "ss_env": "GOOGLE_SPREADSHEET_ID", "status": "active",
        "sales_sheet": "②売上入力", "date_col": 0, "amount_col": 2,
    },
    "Trees Catering": {
        "target": 800_000, "ss_env": "CATERING_SPREADSHEET_ID", "status": "active",
        "sales_sheet": "06_売上管理", "date_col": 0, "amount_col": 3,
    },
    "TACHINOMIYA": {
        "target": 1_200_000, "ss_env": "TACHINOMIYA_SPREADSHEET_ID", "status": "active",
        "sales_sheet": "02_日次売上", "date_col": 1, "amount_col": 2,
    },
    "琉球火鍋": {
        "target": 1_500_000, "ss_env": "HINABE_SPREADSHEET_ID", "status": "active",
        "sales_sheet": "02_日次売上", "date_col": 1, "amount_col": 2,
    },
    "パスタパスタ": {
        "target": 2_000_000, "ss_env": "PASTA_SPREADSHEET_ID", "status": "active",
        "sales_sheet": "05_売上管理", "date_col": 1, "amount_col": 3,
    },
    "Z1": {
        "target": 1_500_000, "ss_env": "Z1_SPREADSHEET_ID", "status": "active",
        "sales_sheet": "05_売上管理", "date_col": 1, "amount_col": 3,
    },
}


def _read_monthly_sales(ss, cfg: dict, month_prefix: str) -> int:
    """汎用売上読み取り：シート・列定義に基づいて今月の売上を集計"""
    sheet_name = cfg.get("sales_sheet", "")
    date_col   = cfg.get("date_col", 0)
    amount_col = cfg.get("amount_col", 2)

    rows = ss.worksheet(sheet_name).get_all_values()[2:]  # ヘッダー2行スキップ
    month_rows = [r for r in rows if len(r) > date_col and r[date_col].startswith(month_prefix)]

    total = 0
    for r in month_rows:
        if len(r) > amount_col:
            try:
                total += int(str(r[amount_col]).replace(",", "").replace("¥", "").strip() or 0)
            except (ValueError, TypeError):
                pass
    return total


def collect_all_business_data(gc) -> list[dict]:
    month_prefix = date.today().strftime("%Y/%m")
    all_data = []

    for biz_name, cfg in BUSINESS_TARGETS.items():
        ss_id = os.getenv(cfg["ss_env"], "")
        if not ss_id:
            all_data.append({
                "name": biz_name, "status": "no_id",
                "target": cfg["target"], "month_total": 0,
                "achievement_rate": 0, "remaining": cfg["target"],
            })
            continue

        try:
            ss = gc.open_by_key(ss_id)
            total = _read_monthly_sales(ss, cfg, month_prefix)
            target = cfg["target"]
            all_data.append({
                "name": biz_name, "status": "active",
                "target": target, "month_total": total,
                "achievement_rate": round(total / target * 100, 1) if target else 0,
                "remaining": max(target - total, 0),
            })
        except Exception as e:
            all_data.append({
                "name": biz_name, "status": f"error: {str(e)[:40]}",
                "target": cfg["target"], "month_total": 0,
                "achievement_rate": 0, "remaining": cfg["target"],
            })

    return all_data


# ─────────────────────────────────────────────
# AI COO - 全事業進捗管理・優先順位決定
# ─────────────────────────────────────────────

def run_coo(all_data: list[dict]) -> dict:
    total_revenue = sum(d["month_total"] for d in all_data)
    total_target  = sum(d["target"] for d in all_data)
    overall_rate  = round(total_revenue / total_target * 100, 1) if total_target else 0

    active = [d for d in all_data if d["status"] == "active"]
    danger = [d for d in active if d["achievement_rate"] < 60]
    warning = [d for d in active if 60 <= d["achievement_rate"] < 80]

    biz_text = "\n".join([
        f"・{d['name']}: {d['month_total']:,}円（目標達成率{d['achievement_rate']}%、残り{d['remaining']:,}円）"
        for d in all_data
    ])

    prompt = f"""あなたはYU HOLDINGSのAI COO（最高執行責任者）です。
今月の全事業データを分析し、CEOへの週次経営ブリーフィングを作成してください。

【全事業今月データ】
合計売上: {total_revenue:,}円 / 合計目標: {total_target:,}円（総達成率: {overall_rate}%）

{biz_text}

危険事業（達成率60%未満）: {len(danger)}社
警告事業（達成率60-80%）: {warning.__len__()}社

【ルール】
・Markdownの##や###は使わない
・数字を必ず含める
・値引き・クーポン提案は禁止
・「誰が・いつ・何をする」の具体的指示のみ

JSON形式で返してください:
{{
  "headline": "今週の経営状態を一言で（20文字以内）",
  "overall_assessment": "全事業総評（3文、数字必須）",
  "top3_this_week": [
    {{"priority": 1, "business": "事業名", "action": "具体的アクション", "expected": "期待効果"}},
    {{"priority": 2, "business": "事業名", "action": "具体的アクション", "expected": "期待効果"}},
    {{"priority": 3, "business": "事業名", "action": "具体的アクション", "expected": "期待効果"}}
  ],
  "danger_alert": "危険事業のアラート（なければ空文字）",
  "coo_one_word": "COOからCEOへのひとこと（15文字以内）"
}}"""

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.65,
    )
    result = json.loads(resp.choices[0].message.content)
    result["total_revenue"] = total_revenue
    result["total_target"] = total_target
    result["overall_rate"] = overall_rate
    result["danger_count"] = len(danger)
    print(f"[AI COO] {result.get('headline', '')}")
    return result


# ─────────────────────────────────────────────
# AI CFO - 全事業財務管理
# ─────────────────────────────────────────────

def run_cfo(all_data: list[dict]) -> dict:
    total_revenue = sum(d["month_total"] for d in all_data)
    total_target  = sum(d["target"] for d in all_data)

    # 達成率ランキング
    ranked = sorted([d for d in all_data if d["status"]=="active"],
                    key=lambda x: x["achievement_rate"], reverse=True)

    prompt = f"""あなたはYU HOLDINGSのAI CFO（最高財務責任者）です。
全事業の財務状況を分析し、CEOへの財務ブリーフィングを作成してください。

【今月の全事業財務データ】
合計売上: {total_revenue:,}円 / 合計目標: {total_target:,}円
達成率ランキング:
{chr(10).join([f"{i+1}位 {d['name']}: {d['achievement_rate']}%（{d['month_total']:,}円）" for i,d in enumerate(ranked)])}

【ルール】
・Markdownの##や###は使わない
・利益率・投資対効果を数値で語る
・投資優先順位を明確に

JSON形式で返してください:
{{
  "revenue_summary": "売上総括（2文、数字必須）",
  "top_performer": "最高達成事業と理由（1文）",
  "bottom_performer": "最低達成事業と改善方向性（1文）",
  "investment_priority": "次の投資優先事業と理由（1文）",
  "cashflow_comment": "資金繰りコメント（1文、具体的数値）",
  "cfo_alert": "CFOからの警告（リスクがあれば、なければ空文字）"
}}"""

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.6,
    )
    result = json.loads(resp.choices[0].message.content)
    print(f"[AI CFO] {result.get('revenue_summary', '')[:40]}...")
    return result


# ─────────────────────────────────────────────
# AI CMO - マーケティング統括
# ─────────────────────────────────────────────

def run_cmo(all_data: list[dict]) -> dict:
    active_biz = [d["name"] for d in all_data if d["status"] == "active"]
    pending_biz = [d["name"] for d in all_data if d["status"] == "pending"]

    prompt = f"""あなたはYU HOLDINGSのAI CMO（最高マーケティング責任者）です。
全事業のマーケティング状況を分析し、CEOへのブリーフィングを作成してください。

【現在のSNS/マーケティング稼働状況】
稼働中事業: {', '.join(active_biz) or 'なし'}
未構築事業: {', '.join(pending_biz) or 'なし'}

稼働中システム:
・毎日9時: Google Business Profile投稿自動生成（Tree Beauty）
・180日分コンテンツ: スプレッドシート生成済み（Google/Instagram/Threads/LINE/HPB）
・Instagram/Threads: APIトークン未設定（手動投稿状態）
・LINE: スタッフ通知自動化済み、顧客LINE未配信

【ルール】
・Markdownの##や###は使わない
・具体的な媒体名・数値を使う

JSON形式で返してください:
{{
  "marketing_status": "現在のマーケティング総括（2文）",
  "sns_priority": "今週最優先のSNSアクション（1つ、具体的）",
  "content_recommendation": "コンテンツ戦略の推奨（1文）",
  "next_platform": "次に稼働させるべきSNS媒体と理由（1文）",
  "cmo_alert": "マーケティングリスクアラート（あれば）"
}}"""

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.65,
    )
    result = json.loads(resp.choices[0].message.content)
    print(f"[AI CMO] {result.get('marketing_status', '')[:40]}...")
    return result


# ─────────────────────────────────────────────
# AI CTO - インフラ監視
# ─────────────────────────────────────────────

def run_cto() -> dict:
    services = {
        "tree-beauty-ai": "https://tree-beauty-ai-75610219333.asia-northeast1.run.app/health",
    }
    pending_services = ["trees-catering-ai", "tachinomiya-ai", "ryukyu-hinabe-ai", "pasta-pasta-ai", "z1-ai"]

    health_results = {}
    for svc_name, url in services.items():
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                health_results[svc_name] = {"status": "✅ 正常", "mode": data.get("mode", ""), "detail": ""}
            else:
                health_results[svc_name] = {"status": f"⚠ HTTP {resp.status_code}", "mode": "", "detail": ""}
        except Exception as e:
            health_results[svc_name] = {"status": f"❌ 障害: {str(e)[:30]}", "mode": "", "detail": ""}

    all_ok = all("✅" in v["status"] for v in health_results.values())

    health_text = "\n".join([f"・{k}: {v['status']} (mode={v['mode']})" for k, v in health_results.items()])
    pending_text = "\n".join([f"・{s}: 未デプロイ" for s in pending_services])

    result = {
        "health_summary": health_text,
        "pending_services": pending_text,
        "all_services_ok": all_ok,
        "active_count": len(services),
        "pending_count": len(pending_services),
        "schedulers_active": 3,
        "cto_alert": "" if all_ok else f"障害検知: {[k for k,v in health_results.items() if '✅' not in v['status']]}",
        "cto_status": "✅ 全システム正常" if all_ok else "⚠ 要対応あり",
    }
    print(f"[AI CTO] {result['cto_status']}")
    return result


# ─────────────────────────────────────────────
# CEO Dashboard 更新
# ─────────────────────────────────────────────

def update_ceo_dashboard(gc, coo: dict, cfo: dict, cmo: dict, cto: dict, all_data: list[dict]):
    ss = gc.open_by_key(MASTER_SS_ID)
    try:
        sheet = ss.worksheet("YU CEO Dashboard")
    except gspread.WorksheetNotFound:
        return

    now = datetime.now().strftime("%Y/%m/%d %H:%M")
    month_label = date.today().strftime("%Y年%m月")

    # AI役員ブリーフィング行を更新（行17-20）
    updates = [
        ["AI COO指令", f"{coo.get('headline','')} | {coo.get('coo_one_word','')}"],
        ["AI CFO状況", f"{cfo.get('revenue_summary','')}"],
        ["AI CMO状況", f"{cmo.get('sns_priority','')}"],
        ["AI CTO状態", f"{cto.get('cto_status','')}"],
    ]
    for i, (label, content) in enumerate(updates):
        row = 17 + i
        sheet.update(f"A{row}:B{row}", [[label, content]], value_input_option="RAW")
        time.sleep(0.3)

    # 更新日時を更新
    sheet.update("B2", [[f"最終更新: {now}  |  管理者: yuya_tokuda@trees-catering.com"]])

    print("[CEO Dashboard] 更新完了")


# ─────────────────────────────────────────────
# LINE CEO ブリーフィング通知
# ─────────────────────────────────────────────

def send_ceo_briefing_line(coo: dict, cfo: dict, cto: dict):
    token = LINE_STAFF_TOKEN
    if len(token) < 100:
        return

    top3 = coo.get("top3_this_week", [])
    actions_text = "\n".join([
        f"{a.get('priority')}. [{a.get('business','')}] {a.get('action','')}"
        for a in top3[:3]
    ])

    alert = ""
    if coo.get("danger_alert"):
        alert = f"\n⚠ COO警告: {coo['danger_alert']}"
    if cto.get("cto_alert"):
        alert += f"\n⚠ CTO警告: {cto['cto_alert']}"

    msg = (
        f"📊 YU HOLDINGS 週次CEOブリーフィング\n"
        f"({date.today().strftime('%Y/%m/%d')} 集計)\n\n"
        f"【AI COO】{coo.get('headline','')}\n"
        f"全事業売上: {coo.get('total_revenue',0):,}円"
        f"（達成率{coo.get('overall_rate',0)}%）\n\n"
        f"【今週やること TOP3】\n{actions_text}\n"
        f"{alert}\n\n"
        f"詳細: YU HOLDINGS Master OS で確認"
    )

    _line_notify(token, msg)
    print("[LINE] CEO ブリーフィング送信完了")


# ─────────────────────────────────────────────
# メイン実行
# ─────────────────────────────────────────────

def run(creds_path: str) -> dict:
    print("=" * 55)
    print("YU HOLDINGS AI Executive Team ブリーフィング開始")
    print(f"  {datetime.now().strftime('%Y/%m/%d %H:%M')}")
    print("=" * 55)

    gc, _ = get_gc(creds_path)

    print("\n[1/5] 全事業データ収集...")
    all_data = collect_all_business_data(gc)
    for d in all_data:
        rate = d['achievement_rate']
        icon = "✅" if rate >= 80 else ("⚠" if rate >= 50 else "❌")
        print(f"  {icon} {d['name']}: {d['month_total']:,}円（{rate}%）")

    print("\n[2/5] AI COO 分析...")
    coo = run_coo(all_data)

    print("\n[3/5] AI CFO 分析...")
    cfo = run_cfo(all_data)

    print("\n[4/5] AI CMO 分析...")
    cmo = run_cmo(all_data)

    print("\n[5/5] AI CTO 監視...")
    cto = run_cto()

    print("\n[6/6] CEO Dashboard 更新 & LINE通知...")
    update_ceo_dashboard(gc, coo, cfo, cmo, cto, all_data)
    send_ceo_briefing_line(coo, cfo, cto)

    print("\n" + "=" * 55)
    print("✅ AI Executive Team ブリーフィング完了")
    print(f"   https://docs.google.com/spreadsheets/d/{MASTER_SS_ID}")
    print("=" * 55)

    return {
        "ok": True,
        "coo": coo,
        "cfo": cfo,
        "cmo": cmo,
        "cto": cto,
        "total_revenue": coo.get("total_revenue", 0),
        "overall_rate": coo.get("overall_rate", 0),
    }
