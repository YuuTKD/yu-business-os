"""
Profit Leak Detector
---------------------
YU HOLDINGS全事業の利益漏れを自動検知し、売上が増えているのに利益が残らない状態を防ぐ。

最重要ゴール:
  ・事業別の粗利/利益率を見える化
  ・案件別の粗利を見える化
  ・原価率/人件費率/外注費率の異常を検知
  ・ケータリング案件ごとの赤字/低粗利を検知
  ・高粗利商品管理を強化
  ・Daily Action Commander / Knowledge OS へ連携

設計方針: OpenAI不使用・ルールベース。LINE本番送信はDRY_RUN。
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
PROFIT_SHEETS = {
    "PROFIT_LEAK_MASTER": [
        "登録日時", "対象日", "事業名", "案件名", "売上", "食材費/原価",
        "人件費", "外注費", "広告費", "配送費", "家賃按分", "その他費用",
        "粗利", "営業利益", "粗利率", "営業利益率", "異常項目", "危険度",
        "AI分析", "改善アクション", "担当", "対応状況", "メモ",
    ],
    "PROJECT_PROFIT": [
        "登録日時", "事業名", "案件名", "顧客名", "案件日", "人数", "売上",
        "食材費", "外注費", "配送費", "装飾費", "人件費", "その他費用",
        "粗利", "粗利率", "目標粗利率", "差分", "危険度",
        "写真有無", "口コミ依頼有無", "再注文可能性", "紹介可能性", "次回アクション", "メモ",
    ],
    "PROFIT_DASHBOARD": [
        "日付", "事業名", "売上", "粗利", "粗利率", "営業利益", "営業利益率",
        "原価率", "人件費率", "外注費率", "広告費率", "危険度",
        "利益漏れ額", "最重要改善アクション", "最終更新日時",
    ],
    "COST_RULES": [
        "事業名", "項目", "目標値", "注意ライン", "危険ライン",
        "判定方法", "改善ルール", "メモ",
    ],
}

# ── 事業別コストルール（COST_RULESシートに初期投入）──────
# 「粗利率」系: 目標以上が良い → 下回ると危険。「原価率」系: 低いほど良い → 上回ると危険。
DEFAULT_COST_RULES = [
    # 事業, 項目, 目標, 注意, 危険, 判定方法, 改善ルール
    ["Trees Catering", "粗利率", 50, 40, 30, "粗利率が下回ると危険", "最低受注単価UP・外注費上限30%・配送別請求"],
    ["TACHINOMIYA",    "原価率", 30, 35, 40, "原価率が上回ると危険", "高粗利商品訴求・仕入れ過多確認"],
    ["Tree Beauty",    "粗利率", 70, 60, 50, "粗利率が下回ると危険", "回数券/セット提案・低単価偏重確認"],
    ["琉球火鍋",        "原価率", 35, 40, 45, "原価率が上回ると危険", "追加メニュー/ドリンク訴求・原価高比率確認"],
    ["パスタパスタ",    "粗利率", 80, 70, 60, "粗利率が下回ると危険", "低単価案件検知・成果報酬未請求確認"],
    ["Z1",             "粗利率", 80, 70, 60, "粗利率が下回ると危険", "低単価案件検知・成果報酬未請求確認"],
]

# 比率系の一般しきい値（対売上）
RATIO_THRESHOLDS = {
    "原価率":   {"warn": 0.40, "danger": 0.50},
    "人件費率": {"warn": 0.35, "danger": 0.45},
    "外注費率": {"warn": 0.25, "danger": 0.35},
    "広告費率": {"warn": 0.15, "danger": 0.25},
}

# 事業別改善アクション
BIZ_IMPROVE_ACTIONS = {
    "Trees Catering": [
        "最低受注単価を引き上げる", "外注費上限を30%に設定", "配送費を別請求にする",
        "20名未満はセットメニュー限定", "原価の高い装飾/料理をオプション化", "見積テンプレを修正",
    ],
    "TACHINOMIYA": [
        "高粗利商品を本日重点販売", "ハブ酒/サーターアンダギー/ドリンク訴求",
        "仕入れ過多を確認", "スタッフ配置を確認", "低粗利商品の提供数を確認",
    ],
    "Tree Beauty": [
        "低単価メニュー偏重を確認", "回数券/セットを提案",
        "再来店候補にLINE", "空き枠対策を実施",
    ],
    "琉球火鍋": [
        "客単価アップ用の追加メニュー提案", "ドリンク/追加肉/個室利用を訴求",
        "原価高メニュー比率を確認",
    ],
    "パスタパスタ": [
        "稼働時間に対し報酬が低い案件を検知", "成果報酬の未請求を確認", "月次レポート作成漏れを確認",
    ],
    "Z1": [
        "稼働時間に対し報酬が低い案件を検知", "成果報酬の未請求を確認", "月次レポート作成漏れを確認",
    ],
}

CATERING_MIN_ORDER = 50_000  # ケータリング最低受注額


# ── ユーティリティ ────────────────────────────────────────

def _now_jst(): return datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
def _date_jst(): return datetime.now(JST).strftime("%Y-%m-%d")


def _gc(creds_path):
    creds = Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/spreadsheets",
                            "https://www.googleapis.com/auth/drive"])
    return gspread.authorize(creds)


def _gcs(creds_path):
    creds = Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/devstorage.read_write"])
    return gcs_storage.Client(project=GCS_PROJECT, credentials=creds)


def _upload_md_gcs(creds_path, gcs_path, content):
    blob = _gcs(creds_path).bucket(GCS_BUCKET).blob(gcs_path)
    blob.upload_from_string(content.encode("utf-8"), content_type="text/markdown")
    return f"https://storage.googleapis.com/{GCS_BUCKET}/{gcs_path}"


def _get_or_create_sheet(ss, title, header):
    try:
        return ss.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=title, rows=2000, cols=max(len(header), 12))
        ws.update(values=[header], range_name="A1")
        ws.format("A1:Z1", {
            "backgroundColor": {"red": 0.20, "green": 0.12, "blue": 0.02},
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}}})
        return ws


def _pint(v):
    if v is None: return 0
    s = str(v).replace(",", "").replace("¥", "").replace("円", "").replace(" ", "").replace("%", "").strip()
    if s in ("", "-", "—"): return 0
    try: return int(float(s))
    except (ValueError, TypeError): return 0


def _pct(part, whole):
    return round(part / whole, 4) if whole else 0.0


def _load_cost_rules(ss) -> dict:
    """COST_RULES を {事業名: {item, target, warn, danger}} で返す"""
    rules = {}
    try:
        ws = ss.worksheet("COST_RULES")
        for r in ws.get_all_records():
            biz = str(r.get("事業名", "")).strip()
            if not biz:
                continue
            rules[biz] = {
                "item":   str(r.get("項目", "")).strip(),
                "target": _pint(r.get("目標値")),
                "warn":   _pint(r.get("注意ライン")),
                "danger": _pint(r.get("危険ライン")),
                "improve": str(r.get("改善ルール", "")),
            }
    except gspread.WorksheetNotFound:
        pass
    # デフォルト補完
    for row in DEFAULT_COST_RULES:
        biz = row[0]
        rules.setdefault(biz, {"item": row[1], "target": row[2], "warn": row[3],
                               "danger": row[4], "improve": row[6]})
    return rules


# ── 利益計算・判定 ────────────────────────────────────────

def _calc_profit(rec) -> dict:
    """1レコードの粗利・利益・各率を計算"""
    sales = _pint(rec.get("売上"))
    cost  = _pint(rec.get("食材費/原価") or rec.get("食材費"))
    labor = _pint(rec.get("人件費"))
    out   = _pint(rec.get("外注費"))
    ad    = _pint(rec.get("広告費"))
    deli  = _pint(rec.get("配送費"))
    rent  = _pint(rec.get("家賃按分"))
    other = _pint(rec.get("その他費用"))

    gross = sales - cost                       # 粗利 = 売上 - 原価
    op    = sales - (cost + labor + out + ad + deli + rent + other)  # 営業利益
    return {
        "sales": sales, "cost": cost, "labor": labor, "out": out,
        "ad": ad, "deli": deli, "rent": rent, "other": other,
        "gross": gross, "op": op,
        "gross_rate": _pct(gross, sales), "op_rate": _pct(op, sales),
        "cost_rate": _pct(cost, sales), "labor_rate": _pct(labor, sales),
        "out_rate": _pct(out, sales), "ad_rate": _pct(ad, sales),
    }


def _judge(biz, calc, rules) -> dict:
    """危険度・異常項目・利益漏れ額を判定"""
    sales = calc["sales"]
    anomalies = []

    # 1) 赤字
    if calc["op"] < 0 or calc["gross"] < 0:
        anomalies.append("赤字")

    # 2) 事業別の主指標（粗利率 or 原価率）
    rule = rules.get(biz, {})
    danger = "C"
    leak = 0
    if rule:
        if rule["item"] == "粗利率":
            gr = calc["gross_rate"] * 100
            if gr < rule["danger"]:
                anomalies.append(f"粗利率{gr:.0f}%が危険ライン{rule['danger']}%未満")
                danger = "S"
                leak = int(sales * (rule["target"] - gr) / 100)
            elif gr < rule["warn"]:
                anomalies.append(f"粗利率{gr:.0f}%が注意ライン{rule['warn']}%未満")
                danger = "A"
                leak = int(sales * (rule["target"] - gr) / 100)
        elif rule["item"] == "原価率":
            cr = calc["cost_rate"] * 100
            if cr > rule["danger"]:
                anomalies.append(f"原価率{cr:.0f}%が危険ライン{rule['danger']}%超")
                danger = "S"
                leak = int(sales * (cr - rule["target"]) / 100)
            elif cr > rule["warn"]:
                anomalies.append(f"原価率{cr:.0f}%が注意ライン{rule['warn']}%超")
                danger = "A"
                leak = int(sales * (cr - rule["target"]) / 100)

    # 3) 比率系異常（人件費/外注費/広告費）
    for label, key in [("人件費率", "labor_rate"), ("外注費率", "out_rate"),
                       ("広告費率", "ad_rate")]:
        th = RATIO_THRESHOLDS.get(label)
        if not th:
            continue
        v = calc[key]
        if v >= th["danger"]:
            anomalies.append(f"{label}{v*100:.0f}%が高すぎ")
            if danger == "C":
                danger = "A"
        elif v >= th["warn"]:
            anomalies.append(f"{label}{v*100:.0f}%やや高")
            if danger == "C":
                danger = "B"

    # 4) ケータリング最低受注額未満
    if biz == "Trees Catering" and 0 < sales < CATERING_MIN_ORDER:
        anomalies.append(f"最低受注額¥{CATERING_MIN_ORDER:,}未満（小口・配送/外注が重い）")
        if danger == "C":
            danger = "B"

    # 5) 売上はあるが粗利が低い
    if sales > 0 and calc["gross_rate"] < 0.3 and "赤字" not in anomalies:
        if "粗利" not in "".join(anomalies):
            anomalies.append("売上はあるが粗利が低い")

    if calc["op"] < 0:
        danger = "S"
        leak = max(leak, -calc["op"])

    if not anomalies:
        danger = "C"

    return {"danger": danger, "anomalies": anomalies, "leak": max(0, leak)}


def _improve_action(biz, judge) -> str:
    acts = BIZ_IMPROVE_ACTIONS.get(biz, ["コスト構造を見直す"])
    # 異常に応じて先頭アクションを選ぶ
    return acts[0] if acts else "改善検討"


def _analysis_text(biz, calc, judge) -> str:
    """AI分析欄（ルールベース生成・OpenAI不使用）"""
    if judge["danger"] == "C":
        return f"{biz}: 利益健全（粗利率{calc['gross_rate']*100:.0f}%）"
    return (f"{biz}: " + "／".join(judge["anomalies"][:3]) +
            f"（粗利率{calc['gross_rate']*100:.0f}% 営業利益率{calc['op_rate']*100:.0f}%）")


# ── 公開API ───────────────────────────────────────────────

def setup(spreadsheet_id, creds_path):
    gc = _gc(creds_path); ss = gc.open_by_key(spreadsheet_id)
    created = []
    for name, header in PROFIT_SHEETS.items():
        _get_or_create_sheet(ss, name, header)
        created.append(name)
    # COST_RULES 初期投入
    try:
        cw = ss.worksheet("COST_RULES")
        if len(cw.get_all_values()) <= 1:
            rows = [[r[0], r[1], r[2], r[3], r[4], r[5], r[6], ""] for r in DEFAULT_COST_RULES]
            cw.append_rows(rows, value_input_option="RAW")
    except Exception:
        pass
    return {"ok": True, "sheets_created": created,
            "url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"}


# ── テストデータ（25件）──────────────────────────────────

def _test_master():
    now = _now_jst(); d = _date_jst()
    def row(biz, proj, sales, cost, labor=0, out=0, ad=0, deli=0, rent=0, other=0):
        return {"登録日時": now, "対象日": d, "事業名": biz, "案件名": proj,
                "売上": sales, "食材費/原価": cost, "人件費": labor, "外注費": out,
                "広告費": ad, "配送費": deli, "家賃按分": rent, "その他費用": other,
                "担当": "", "対応状況": "未対応", "メモ": ""}
    return [
        # Catering: 高粗利 / 低粗利 / 赤字 / 小口
        row("Trees Catering", "A社懇親会(高粗利)", 300_000, 90_000, 30_000, 20_000, 0, 10_000),
        row("Trees Catering", "B社パーティー(低粗利)", 200_000, 120_000, 30_000, 25_000, 0, 15_000),
        row("Trees Catering", "C社イベント(赤字)", 150_000, 110_000, 40_000, 30_000, 5_000, 20_000),
        row("Trees Catering", "個人少人数(小口)", 35_000, 15_000, 8_000, 10_000, 0, 5_000),
        row("Trees Catering", "D社周年(外注過多)", 250_000, 80_000, 30_000, 110_000, 0, 10_000),
        # TACHINOMIYA: 原価正常 / 危険
        row("TACHINOMIYA", "6/20 日次(原価正常)", 92_000, 27_000, 25_000),
        row("TACHINOMIYA", "6/21 日次(原価危険)", 80_000, 38_000, 26_000),
        row("TACHINOMIYA", "6/22 日次(人件費過多)", 70_000, 21_000, 40_000),
        row("TACHINOMIYA", "6/23 日次(正常)", 110_000, 30_000, 28_000),
        # Beauty: 正常 / 危険
        row("Tree Beauty", "脱毛コース(正常)", 30_000, 6_000, 5_000),
        row("Tree Beauty", "低単価偏重(危険)", 8_000, 3_000, 4_000),
        row("Tree Beauty", "よもぎ蒸し(正常)", 12_000, 2_000, 3_000),
        row("Tree Beauty", "ホワイトニング(注意)", 15_000, 7_000, 4_000),
        # 火鍋: 原価高すぎ / 正常
        row("琉球火鍋", "個室宴会(原価高)", 70_000, 34_000, 15_000),
        row("琉球火鍋", "記念日コース(正常)", 80_000, 26_000, 14_000),
        row("琉球火鍋", "女子会(原価やや高)", 60_000, 26_000, 12_000),
        row("琉球火鍋", "接待コース(正常)", 120_000, 38_000, 18_000),
        # コンサル: 低単価 / 正常 / 未請求相当
        row("パスタパスタ", "月次顧問(低単価)", 50_000, 0, 35_000),
        row("パスタパスタ", "成果報酬案件(正常)", 300_000, 0, 30_000),
        row("Z1", "SNS運用(低単価)", 40_000, 0, 30_000),
        row("Z1", "コンサル(正常)", 200_000, 0, 20_000),
        # 追加: 外注/人件費過多・広告過多
        row("Trees Catering", "E社装飾過多", 180_000, 70_000, 25_000, 20_000, 0, 30_000),
        row("TACHINOMIYA", "イベント日(広告過多)", 90_000, 27_000, 25_000, 0, 25_000),
        row("Tree Beauty", "キャンペーン(広告過多)", 20_000, 5_000, 4_000, 0, 8_000),
        row("琉球火鍋", "貸切(人件費過多)", 100_000, 35_000, 50_000),
    ]


def run_test(spreadsheet_id, creds_path):
    gc = _gc(creds_path); ss = gc.open_by_key(spreadsheet_id)
    for name, header in PROFIT_SHEETS.items():
        _get_or_create_sheet(ss, name, header)
    rules = _load_cost_rules(ss)

    mws = ss.worksheet("PROFIT_LEAK_MASTER")
    header = PROFIT_SHEETS["PROFIT_LEAK_MASTER"]
    recs = _test_master()
    rows = []
    summary = {"S": 0, "A": 0, "B": 0, "C": 0}
    total_leak = 0
    for rec in recs:
        calc = _calc_profit(rec)
        j = _judge(rec["事業名"], calc, rules)
        summary[j["danger"]] = summary.get(j["danger"], 0) + 1
        total_leak += j["leak"]
        rec.update({
            "粗利": calc["gross"], "営業利益": calc["op"],
            "粗利率": f"{calc['gross_rate']*100:.0f}%", "営業利益率": f"{calc['op_rate']*100:.0f}%",
            "異常項目": "／".join(j["anomalies"]) or "なし", "危険度": j["danger"],
            "AI分析": _analysis_text(rec["事業名"], calc, j),
            "改善アクション": _improve_action(rec["事業名"], j) if j["danger"] != "C" else "",
        })
        rows.append([rec.get(h, "") for h in header])
    mws.append_rows(rows, value_input_option="RAW")

    daily(spreadsheet_id, creds_path, write=True)

    return {"ok": True, "test_records": len(recs), "danger_summary": summary,
            "total_leak": total_leak, "dry_run": True,
            "note": "判定はルールベース（OpenAI不使用）。LINE送信なし。"}


def _aggregate_by_biz(records, rules):
    """事業別に集計して DASHBOARD 行を作る"""
    by = {}
    for r in records:
        biz = str(r.get("事業名", ""))
        if not biz:
            continue
        calc = _calc_profit(r)
        b = by.setdefault(biz, {"sales": 0, "cost": 0, "labor": 0, "out": 0,
                                "ad": 0, "gross": 0, "op": 0, "leak": 0,
                                "worst": "C", "action": ""})
        for k in ["sales", "cost", "labor", "out", "ad", "gross", "op"]:
            b[k] += calc[k]
        j = _judge(biz, calc, rules)
        b["leak"] += j["leak"]
        order = {"C": 0, "B": 1, "A": 2, "S": 3}
        if order[j["danger"]] > order[b["worst"]]:
            b["worst"] = j["danger"]
            b["action"] = _improve_action(biz, j)
    return by


def daily(spreadsheet_id, creds_path, write=True):
    gc = _gc(creds_path); ss = gc.open_by_key(spreadsheet_id)
    try:
        mws = ss.worksheet("PROFIT_LEAK_MASTER")
    except gspread.WorksheetNotFound:
        return {"ok": False, "error": "PROFIT_LEAK_MASTER 未作成。/profit-setup を実行してください。"}
    records = mws.get_all_records()
    rules = _load_cost_rules(ss)
    by = _aggregate_by_biz(records, rules)

    dash_rows = []
    for biz, b in by.items():
        s = b["sales"]
        dash_rows.append([
            _date_jst(), biz, s, b["gross"], f"{_pct(b['gross'], s)*100:.0f}%",
            b["op"], f"{_pct(b['op'], s)*100:.0f}%",
            f"{_pct(b['cost'], s)*100:.0f}%", f"{_pct(b['labor'], s)*100:.0f}%",
            f"{_pct(b['out'], s)*100:.0f}%", f"{_pct(b['ad'], s)*100:.0f}%",
            b["worst"], b["leak"], b["action"], _now_jst(),
        ])

    if write and dash_rows:
        dws = _get_or_create_sheet(ss, "PROFIT_DASHBOARD", PROFIT_SHEETS["PROFIT_DASHBOARD"])
        # 当日の既存行を消さず追記（簡易）。重複日対策で当日分を一旦読み、無ければ追記
        existing = {(str(r.get("日付")), str(r.get("事業名"))) for r in dws.get_all_records()}
        new_rows = [row for row in dash_rows if (row[0], row[1]) not in existing]
        if new_rows:
            dws.append_rows(new_rows, value_input_option="RAW")

    return {"ok": True, "businesses": list(by.keys()),
            "by_business": {biz: {"売上": b["sales"], "粗利率": f"{_pct(b['gross'], b['sales'])*100:.0f}%",
                                  "危険度": b["worst"], "利益漏れ": b["leak"],
                                  "改善": b["action"]}
                            for biz, b in by.items()},
            "total_leak": sum(b["leak"] for b in by.values())}


def project_check(spreadsheet_id, creds_path):
    """PROJECT_PROFIT（案件別）の粗利判定。MASTERの案件をPROJECT_PROFITにも反映集計"""
    gc = _gc(creds_path); ss = gc.open_by_key(spreadsheet_id)
    rules = _load_cost_rules(ss)
    try:
        mws = ss.worksheet("PROFIT_LEAK_MASTER")
    except gspread.WorksheetNotFound:
        return {"ok": False, "error": "PROFIT_LEAK_MASTER 未作成"}
    low = []
    for r in mws.get_all_records():
        calc = _calc_profit(r)
        j = _judge(str(r.get("事業名")), calc, rules)
        if j["danger"] in ("S", "A"):
            low.append({"事業名": r.get("事業名"), "案件名": r.get("案件名"),
                        "売上": calc["sales"], "粗利率": f"{calc['gross_rate']*100:.0f}%",
                        "危険度": j["danger"], "異常": "／".join(j["anomalies"][:2]),
                        "改善": _improve_action(str(r.get("事業名")), j)})
    return {"ok": True, "low_profit_projects": low, "count": len(low)}


def get_status(spreadsheet_id, creds_path):
    return daily(spreadsheet_id, creds_path, write=False)


def actions(spreadsheet_id, creds_path):
    """危険度S/A事業の改善アクション → Daily Action連携タスク"""
    d = daily(spreadsheet_id, creds_path, write=False)
    biz_key_map = {"TACHINOMIYA": "tachinomiya", "Trees Catering": "catering",
                   "Tree Beauty": "beauty", "琉球火鍋": "ryukyu_hinabe",
                   "パスタパスタ": "pasta_pasta", "Z1": "z1"}
    tasks = []
    for biz, b in d.get("by_business", {}).items():
        if b["危険度"] in ("S", "A") and b["改善"]:
            tasks.append({"biz_key": biz_key_map.get(biz, "owner"),
                          "priority": "S" if b["危険度"] == "S" else "A",
                          "task": f"【利益改善】{b['改善']}（{biz}・漏れ¥{b['利益漏れ']:,}）"})
    return {"ok": True, "daily_action_tasks": tasks, "count": len(tasks), "dry_run": True}


def owner_report(spreadsheet_id, creds_path):
    d = daily(spreadsheet_id, creds_path, write=False)
    txt = f"【利益漏れ日次レポート】{_date_jst()}\n\n"
    txt += f"💸 利益漏れ合計：¥{d.get('total_leak', 0):,}\n\n"
    for biz, b in d.get("by_business", {}).items():
        emoji = {"S": "🔴", "A": "🟠", "B": "🟡", "C": "🟢"}.get(b["危険度"], "")
        txt += f"{emoji} {biz}：粗利率{b['粗利率']} 漏れ¥{b['利益漏れ']:,}\n"
        if b["危険度"] in ("S", "A") and b["改善"]:
            txt += f"   → {b['改善']}\n"
    return {"ok": True, "report_text": txt, "dry_run": True}


def export_knowledge(spreadsheet_id, creds_path):
    d = daily(spreadsheet_id, creds_path, write=False)
    today = _date_jst()
    md = (f"---\ntitle: 利益漏れレポート {today}\nbusiness: YU HOLDINGS\n"
          f"category: profit_leak\ndate: {today}\nsource: profit_leak_detector\n"
          f"status: active\ntags: [profit, finance, leak]\n---\n\n"
          f"# 利益漏れレポート — {today}\n\n"
          f"## サマリー\n- 利益漏れ合計: ¥{d.get('total_leak',0):,}\n\n"
          f"## 事業別\n\n| 事業 | 売上 | 粗利率 | 危険度 | 利益漏れ | 改善 |\n|---|---|---|---|---|---|\n")
    for biz, b in d.get("by_business", {}).items():
        md += f"| {biz} | ¥{b['売上']:,} | {b['粗利率']} | {b['危険度']} | ¥{b['利益漏れ']:,} | {b['改善'] or '—'} |\n"
    path = f"{GCS_PREFIX}/10_Finance_Risk/profit_leak_report_{today}.md"
    url = _upload_md_gcs(creds_path, path, md)
    return {"ok": True, "path": path, "url": url, "total_leak": d.get("total_leak", 0)}
