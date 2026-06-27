"""
YU HOLDINGS - TARGETシート管理モジュール

TARGET_MASTER: 目標マスタ（オーナー設定）
TARGET:        実績との突合（Cloud Run書込 + Sheets数式）

設置先: YU HOLDINGS Master OS (1I6wRRDa-b440DBxZ3TbFbfMxEXZecowzOsxTAYSxyBE)
"""

import os, calendar
from datetime import datetime, date
import gspread
from google.oauth2.service_account import Credentials
from openai import OpenAI

# ─── 定数 ────────────────────────────────────────────────────────────────────

MASTER_SS_ID = "1I6wRRDa-b440DBxZ3TbFbfMxEXZecowzOsxTAYSxyBE"

MASTER_HEADERS = [
    "事業名", "優先度", "月売上目標(円)", "利益率目標(%)",
    "月客数目標(人)", "月客単価目標(円)", "月新規顧客目標(人)",
    "月口コミ目標(件)", "責任者", "備考",
]

# 事業名, 優先度, 売上目標, 利益率%, 客数, 客単価, 新規, 口コミ, 責任者, 備考
MASTER_DATA = [
    ["Tree Beauty",    "A", 500000,   50,  80,   6250,   15, 5, "", "美容サロン"],
    ["TACHINOMIYA",    "A", 3500000,  30, 2500,  1400,  100, 8, "", "飲食店"],
    ["Trees Catering", "B", 800000,   35,  30,  26667,   10, 3, "", "ケータリング"],
    ["琉球火鍋",       "B", 1500000,  30, 500,   3000,   50, 5, "", "飲食店"],
    ["パスタパスタ",   "C", 2000000,  20,  20, 100000,    5, 2, "", "コンサル"],
    ["Z1",             "C", 1500000,  40,  15, 100000,    3, 2, "", "コンサル"],
]

TARGET_HEADERS = [
    "年月", "事業名", "売上目標", "実績売上",
    "経過日率(%)", "按分目標", "達成率(%)", "不足額",
    "推定利益(参考)", "残日数", "必要日販", "予測月商",
    "状態", "更新日時", "AIアクション",
]

# 各事業のPOS_KPI参照先スプレッドシートID
BIZ_SS_MAP = {
    "Tree Beauty":    "1I6wRRDa-b440DBxZ3TbFbfMxEXZecowzOsxTAYSxyBE",
    "TACHINOMIYA":    "1K4KkAhFwVkQqqvzeqa25-1sR26ltBfP9gY9h-N4gXcc",
    "Trees Catering": "1tNE35iQAVk6eTGEu68WDrRpv9FDIeVT_eK66iRi78Zs",
    "琉球火鍋":       "1jwFmQtrertjIc6yYFJEyDptLdSUgD5xLdHDAxQhIQzw",
    "パスタパスタ":   "1MVz203ZMD4qoNdP5NZzTWCViQP3etGwOOVuae0XNQnw",
    "Z1":             "10YHdIxqIdk4WP9_AMXETs8GcS1YeKsEIQwaLcAVlCZ8",
}

# ─── ユーティリティ ──────────────────────────────────────────────────────────

def _get_creds(creds_path: str) -> Credentials:
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    return Credentials.from_service_account_file(creds_path, scopes=scopes)


def _get_or_create_sheet(ss, title: str, rows: int = 500, cols: int = 20):
    """シートを取得または新規作成（既存シートは変更しない）"""
    try:
        return ss.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=title, rows=rows, cols=cols)
        print(f"  📋 新規シート作成: {title}")
        return ws


def _read_pos_kpi(gc, ss_id: str) -> dict:
    """POS_KPI シートから {年月: 売上} の辞書を返す"""
    try:
        ss = gc.open_by_key(ss_id)
        ws = ss.worksheet("POS_KPI")
        rows = ws.get_all_values()
        result = {}
        for r in rows[1:]:
            if len(r) >= 2 and r[0] and r[1]:
                try:
                    result[r[0]] = int(r[1])
                except ValueError:
                    pass
        return result
    except Exception as e:
        print(f"    POS_KPI取得失敗 ({ss_id[:20]}...): {e}")
        return {}


def _build_formulas(row_num: int) -> dict:
    """行番号を指定してSheets数式辞書を返す"""
    n = row_num
    today_check = f'TEXT(A{n},"YYYY/MM")=TEXT(TODAY(),"YYYY/MM")'
    return {
        "E": f'=IF({today_check},DAY(TODAY())/DAY(EOMONTH(TODAY(),0))*100,100)',
        "F": f'=C{n}*E{n}/100',
        "G": f'=IFERROR(ROUND(D{n}/F{n}*100,1),0)',
        "H": f'=MAX(0,C{n}-D{n})',
        "J": f'=IF({today_check},DAY(EOMONTH(TODAY(),0))-DAY(TODAY()),0)',
        "K": f'=IFERROR(IF(J{n}>0,CEILING(H{n}/J{n},1000),0),0)',
        "L": f'=IFERROR(IF(E{n}>0,ROUND(D{n}/(E{n}/100),-3),0),0)',
        "M": f'=IF(G{n}>=100,"🟢",IF(G{n}>=80,"🟡",IF(G{n}>=60,"🟠","🔴")))',
    }


def _calc_snapshot(year_month: str, actual: int, target: int, profit_rate: int) -> dict:
    """Cloud Run実行時点のスナップショット値を計算"""
    today = date.today()
    ym = datetime.strptime(year_month, "%Y/%m")
    days_in_month = calendar.monthrange(ym.year, ym.month)[1]

    if ym.year == today.year and ym.month == today.month:
        elapsed = today.day
        remaining = days_in_month - today.day
    else:
        elapsed = days_in_month
        remaining = 0

    progress = elapsed / days_in_month * 100
    prorated  = target * progress / 100
    rate      = round(actual / prorated * 100, 1) if prorated > 0 else 0
    shortage  = max(0, target - actual)
    daily     = int(shortage / remaining / 1000) * 1000 if remaining > 0 else 0
    forecast  = round(actual / (progress / 100) / 1000) * 1000 if progress > 0 else 0
    profit    = int(actual * profit_rate / 100)

    if rate >= 100:  status = "🟢"
    elif rate >= 80: status = "🟡"
    elif rate >= 60: status = "🟠"
    else:            status = "🔴"

    return {
        "progress": progress, "remaining": remaining,
        "prorated": prorated, "rate": rate, "shortage": shortage,
        "daily": daily, "forecast": forecast, "profit": profit, "status": status,
    }


# ─── AIアクション生成 ────────────────────────────────────────────────────────

def generate_ai_action(
    biz_name: str, year_month: str,
    actual: int, target: int, rate: float,
    shortage: int, daily_needed: int, forecast: int,
    openai_key: str,
) -> str:
    """AI CFOによる次のアクション生成"""
    if not openai_key:
        return ""
    try:
        client = OpenAI(api_key=openai_key)

        if actual == 0:
            context = f"実績データ未取込。売上目標¥{target:,}に対して実績が0円。データ収集体制の確認が必要。"
        elif rate >= 100:
            context = f"目標達成。¥{actual:,}（達成率{rate:.1f}%）。利益確保と来月の上積みを検討。"
        else:
            context = (
                f"目標¥{target:,}に対して実績¥{actual:,}（按分達成率{rate:.1f}%）。"
                f"不足¥{shortage:,}。残日数で¥{daily_needed:,}/日が必要。"
                f"現ペースの月商予測は¥{forecast:,}。"
            )

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "system",
                "content": (
                    "あなたはYU HOLDINGSのAI CFOです。"
                    "経営データを元に、今すぐ取るべき最重要アクションを40文字以内で断言形で出力してください。"
                    "数字を必ず1つ含め、「〜する」「〜を実施」「〜を優先」の形で書く。敬語不要。"
                ),
            }, {
                "role": "user",
                "content": f"事業: {biz_name} / {year_month}\n{context}",
            }],
            max_tokens=80,
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"    AIアクション生成失敗: {e}")
        return ""


# ─── メイン処理 ──────────────────────────────────────────────────────────────

def setup_target_master(gc, ss):
    """TARGET_MASTER シートを初期構築（初回のみ）"""
    ws = _get_or_create_sheet(ss, "TARGET_MASTER", rows=20, cols=12)

    existing = ws.get_all_values()
    if existing and existing[0] == MASTER_HEADERS:
        print("  TARGET_MASTER: 既存データあり。スキップ。")
        return ws

    # ヘッダー + データを書込（初回のみ）
    all_rows = [MASTER_HEADERS] + MASTER_DATA
    ws.update(
        range_name="A1",
        values=all_rows,
        value_input_option="USER_ENTERED",
    )
    print(f"  TARGET_MASTER: {len(MASTER_DATA)}事業分を書込。")
    return ws


def update_target(gc, creds_path: str, openai_key: str = "") -> dict:
    """TARGET シートを最新実績で更新する（Cloud Run から呼び出し）"""
    ss     = gc.open_by_key(MASTER_SS_ID)
    today  = date.today()
    now_str = datetime.now().strftime("%Y/%m/%d %H:%M")

    # TARGET_MASTER から目標値を読込
    setup_target_master(gc, ss)
    master_ws  = ss.worksheet("TARGET_MASTER")
    master_rows = master_ws.get_all_values()[1:]  # ヘッダー除く
    master_map  = {}
    for r in master_rows:
        if r[0]:
            master_map[r[0]] = {
                "priority":    r[1],
                "target":      int(r[2]) if r[2] else 0,
                "profit_rate": int(r[3]) if r[3] else 0,
            }

    # 各事業の POS_KPI を取得
    kpi_data = {}
    for biz, ss_id in BIZ_SS_MAP.items():
        kpi_data[biz] = _read_pos_kpi(gc, ss_id)
        print(f"  {biz}: {len(kpi_data[biz])}ヶ月分取得")

    # TARGET シートを取得または新規作成
    target_ws = _get_or_create_sheet(ss, "TARGET", rows=500, cols=16)

    # 既存データを読込（重複チェック用）
    existing = target_ws.get_all_values()
    if not existing or existing[0] != TARGET_HEADERS:
        # ヘッダー書込
        target_ws.update(
            range_name="A1",
            values=[TARGET_HEADERS],
            value_input_option="USER_ENTERED",
        )
        existing = [TARGET_HEADERS]

    # 既存の（年月, 事業名）インデックスを作成
    existing_keys = set()
    for row in existing[1:]:
        if len(row) >= 2 and row[0] and row[1]:
            existing_keys.add((row[0], row[1]))

    # 当月文字列
    current_ym = today.strftime("%Y/%m")

    # 書込む行を収集
    new_rows     = []   # 新規追加行
    update_cells = []   # 既存行の更新セル

    for biz, cfg in master_map.items():
        target      = cfg["target"]
        profit_rate = cfg["profit_rate"]
        kpi         = kpi_data.get(biz, {})

        # KPIがある月 + 当月（KPIなくても追加）を対象
        months_to_process = set(kpi.keys()) | {current_ym}

        for ym in sorted(months_to_process):
            actual = kpi.get(ym, 0)
            snap   = _calc_snapshot(ym, actual, target, profit_rate)

            # 当月のみ AIアクション 生成
            if ym == current_ym and openai_key:
                ai_action = generate_ai_action(
                    biz, ym, actual, target,
                    snap["rate"], snap["shortage"],
                    snap["daily"], snap["forecast"], openai_key,
                )
            else:
                ai_action = ""

            if (ym, biz) in existing_keys:
                # 既存行を更新（D=実績, I=推定利益, N=更新日時, O=AIアクション）
                # 行番号を検索
                for i, row in enumerate(existing[1:], start=2):
                    if len(row) >= 2 and row[0] == ym and row[1] == biz:
                        update_cells.append({
                            "row": i, "actual": actual,
                            "profit": snap["profit"], "now": now_str, "ai": ai_action,
                        })
                        break
            else:
                # 新規行追加
                next_row = len(existing) + len(new_rows) + 1
                formulas = _build_formulas(next_row)
                row_data = [
                    ym,             # A
                    biz,            # B
                    target,         # C
                    actual,         # D
                    formulas["E"],  # E
                    formulas["F"],  # F
                    formulas["G"],  # G
                    formulas["H"],  # H
                    snap["profit"], # I
                    formulas["J"],  # J
                    formulas["K"],  # K
                    formulas["L"],  # L
                    formulas["M"],  # M
                    now_str,        # N
                    ai_action,      # O
                ]
                new_rows.append(row_data)

    # 新規行をまとめて追加
    written = 0
    if new_rows:
        start_row = len(existing) + 1
        target_ws.update(
            range_name=f"A{start_row}",
            values=new_rows,
            value_input_option="USER_ENTERED",
        )
        written = len(new_rows)
        print(f"  TARGET: {written}行を新規追加")

    # 既存行の D, I, N, O を更新
    updated = 0
    for cell in update_cells:
        r = cell["row"]
        target_ws.update(
            range_name=f"D{r}:D{r}",
            values=[[cell["actual"]]],
        )
        target_ws.update(
            range_name=f"I{r}:I{r}",
            values=[[cell["profit"]]],
        )
        target_ws.update(
            range_name=f"N{r}:O{r}",
            values=[[cell["now"], cell["ai"]]],
        )
        updated += 1
    if updated:
        print(f"  TARGET: {updated}行を更新")

    return {
        "ok": True,
        "written": written,
        "updated": updated,
        "current_month": current_ym,
    }


def run(creds_path: str, openai_key: str = "") -> dict:
    """エントリポイント: TARGET_MASTER + TARGET を初期化・更新"""
    print("\n=== TARGET シート更新開始 ===")
    creds = _get_creds(creds_path)
    gc    = gspread.authorize(creds)
    ss    = gc.open_by_key(MASTER_SS_ID)

    # TARGET_MASTER 初期構築（初回のみ書込）
    setup_target_master(gc, ss)

    # TARGET 更新
    result = update_target(gc, creds_path, openai_key)
    print(f"=== TARGET 更新完了: {result} ===\n")
    return result
