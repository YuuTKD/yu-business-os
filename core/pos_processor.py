"""
YU HOLDINGS - 汎用POSデータ統合基盤

対応POS: Airegi（Tree Beauty・TACHINOMIYA・Catering）
         USENレジ（琉球火鍋）
フロー: Drive CSV → パース → 日次集計 → スプレッドシート反映 → KPI自動計算
"""

import io, csv, json, os, time, hashlib
from datetime import datetime, date, timedelta
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
import gspread
from openai import OpenAI

BOOKING_URL_MAP = {
    "TACHINOMIYA": "",
    "琉球火鍋":    "",
    "Trees Catering": "",
}

# ─────────────────────────────────────────────────────────────
# メニュー → カテゴリ マッピング（事業別）
# ─────────────────────────────────────────────────────────────
MENU_CATEGORIES = {
    "TACHINOMIYA": {
        "サーターアンダギー": ["サーター", "アンダギー", "揚げ菓子", "菓子"],
        "ドリンク":           ["ビール", "酒", "カクテル", "ハイボール", "ドリンク", "飲み物",
                               "ウイスキー", "チューハイ", "ソフトドリンク", "ジュース"],
        "フード":             ["フード", "おつまみ", "料理", "定食", "唐揚げ", "枝豆"],
        "デリバリー":         ["Uber", "出前", "デリバリー", "テイクアウト"],
    },
    "琉球火鍋": {
        "火鍋コース":   ["コース", "セット", "鍋", "スープ"],
        "食材・追加":   ["食材", "追加", "肉", "野菜", "海鮮", "豆腐"],
        "飲み放題":     ["飲み放題", "ドリンク", "アルコール", "ビール", "ハイボール"],
        "シメ":         ["シメ", "ラーメン", "雑炊", "うどん"],
        "テイクアウト": ["テイクアウト", "持ち帰り"],
    },
    "Trees Catering": {
        "ケータリング": ["ケータリング", "立食", "パーティー"],
        "オードブル":   ["オードブル", "前菜", "盛り合わせ"],
        "会議弁当":     ["会議", "ミーティング", "弁当"],
        "来客用弁当":   ["来客", "接待", "お弁当"],
    },
    "Tree Beauty": {
        "脱毛":               ["脱毛", "ムダ毛", "除毛", "VIO"],
        "セルフホワイトニング": ["ホワイトニング", "歯"],
        "よもぎ蒸し":         ["よもぎ", "蒸し"],
    },
}

PAYMENT_NORMALIZE = {
    "現金":   ["現金", "CASH", "cash"],
    "カード": ["カード", "CARD", "Visa", "Master", "JCB", "信販"],
    "QR":     ["QR", "PayPay", "メルペイ", "LINE Pay", "nanaco"],
}

# ─────────────────────────────────────────────────────────────
# 認証
# ─────────────────────────────────────────────────────────────
def get_services(creds_path: str):
    creds = Credentials.from_service_account_file(creds_path, scopes=[
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/spreadsheets",
    ])
    return build("drive", "v3", credentials=creds), gspread.authorize(creds)


# ─────────────────────────────────────────────────────────────
# Drive操作
# ─────────────────────────────────────────────────────────────
def list_csv_files(drive, folder_id: str) -> list[dict]:
    result = drive.files().list(
        q=f"'{folder_id}' in parents and mimeType='text/csv' and trashed=false",
        orderBy="createdTime asc",
        fields="files(id,name,createdTime)",
    ).execute()
    return result.get("files", [])


def download_csv(drive, file_id: str) -> tuple[list[list[str]], bytes]:
    """CSVをDriveから取得。(parsed_rows, raw_bytes) を返す。"""
    raw: bytes = drive.files().get_media(fileId=file_id).execute()
    for enc in ("utf-8-sig", "shift_jis", "cp932", "utf-8"):
        try:
            text = raw.decode(enc)
            return list(csv.reader(io.StringIO(text))), raw
        except (UnicodeDecodeError, Exception):
            continue
    raise ValueError(f"CSV encoding detection failed (tried utf-8-sig/shift_jis/utf-8)")


def move_to_done(drive, file_id: str, done_folder_id: str):
    if not done_folder_id:
        return
    file = drive.files().get(fileId=file_id, fields="parents").execute()
    prev = ",".join(file.get("parents", []))
    drive.files().update(
        fileId=file_id, addParents=done_folder_id,
        removeParents=prev, fields="id,parents",
    ).execute()


# ─────────────────────────────────────────────────────────────
# ユーティリティ
# ─────────────────────────────────────────────────────────────
def normalize_date(raw: str) -> str:
    raw = raw.strip().split(" ")[0].split("T")[0]
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y年%m月%d日", "%m/%d/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y/%m/%d")
        except ValueError:
            continue
    return raw


def categorize(menu_raw: str, biz_name: str) -> str:
    cats = MENU_CATEGORIES.get(biz_name, {})
    for cat, keywords in cats.items():
        if any(kw in menu_raw for kw in keywords):
            return cat
    return menu_raw or "その他"


def normalize_payment(raw: str) -> str:
    for norm, variants in PAYMENT_NORMALIZE.items():
        if any(v.lower() in raw.lower() for v in variants):
            return norm
    return raw or "その他"


def col_finder(headers: list[str], candidates: list[str]) -> int | None:
    for c in candidates:
        for i, h in enumerate(headers):
            if c in h:
                return i
    return None


# ─────────────────────────────────────────────────────────────
# Airegi CSVパース
# ─────────────────────────────────────────────────────────────
def parse_airegi(rows: list[list[str]], biz_name: str) -> list[dict]:
    if not rows:
        return []
    headers = rows[0]
    idx_date    = col_finder(headers, ["取引日", "日付", "売上日"])
    idx_menu    = col_finder(headers, ["商品名", "品名", "メニュー"])
    idx_amount  = col_finder(headers, ["金額", "売上", "合計"])
    idx_payment = col_finder(headers, ["支払方法", "支払い方法", "決済"])
    idx_qty     = col_finder(headers, ["数量", "個数"])

    records = []
    for row in rows[1:]:
        if not row or len(row) < 2 or not row[0].strip():
            continue
        try:
            amt_raw = row[idx_amount].replace(",", "").replace("¥", "").replace("円", "").strip() if idx_amount is not None else "0"
            amount = int(float(amt_raw)) if amt_raw else 0
            if amount <= 0:
                continue
            qty = int(row[idx_qty].strip() or 1) if idx_qty is not None else 1
            menu_raw = row[idx_menu].strip() if idx_menu is not None else ""
            records.append({
                "date":     normalize_date(row[idx_date].strip() if idx_date is not None else ""),
                "menu":     categorize(menu_raw, biz_name),
                "amount":   amount,
                "qty":      qty,
                "payment":  normalize_payment(row[idx_payment].strip() if idx_payment is not None else ""),
                "raw_menu": menu_raw,
            })
        except (ValueError, IndexError):
            continue
    return records


# ─────────────────────────────────────────────────────────────
# USENレジ CSVパース（琉球火鍋専用）
#
# 実CSVフォーマット（汎用検索・売上データ伝票）:
#   col 7:  集計対象営業年月日  → 日付
#   col 12: 支払ステータス      → "02.会計済" のみ有効
#   col 17: 客数（合計）        → 客数
#   col 25: 伝票金額            → 売上（値引後）
#   col 35: 値引金額            → 値引額
#   col 37: 支払金額（現金）    → 現金
#   col 38: 支払金額（クレジットカード） → カード
#   col 39: 支払金額（電子マネー）      → QR/電子マネー
#   col 50: 客層                → 集客経路・客層メモ
# ─────────────────────────────────────────────────────────────
USEN_COL = {
    "date":    "集計対象営業年月日",
    "status":  "支払ステータス",
    "count":   "客数（合計）",
    "amount":  "伝票金額",
    "discount":"値引金額",
    "cash":    "支払金額（現金）",
    "card":    "支払金額（クレジットカード）",
    "emoney":  "支払金額（電子マネー）",
    "segment": "客層",
}

def parse_amount_jpy(raw: str) -> int:
    """'¥ 24,926' や '¥0' などを整数に変換"""
    cleaned = str(raw).replace("¥", "").replace(",", "").replace(" ", "").strip()
    try:
        return int(float(cleaned))
    except (ValueError, TypeError):
        return 0


def parse_usen(rows: list[list[str]], biz_name: str = "琉球火鍋") -> list[dict]:
    if not rows:
        return []

    headers = rows[0]
    idx = {k: col_finder(headers, [v]) for k, v in USEN_COL.items()}

    records = []
    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        try:
            # 支払ステータスフィルター（会計済のみ）
            status = row[idx["status"]].strip() if idx["status"] is not None else ""
            if "会計済" not in status:
                continue

            amount  = parse_amount_jpy(row[idx["amount"]])  if idx["amount"]   is not None else 0
            if amount <= 0:
                continue

            count   = int(row[idx["count"]].strip()  or 0)  if idx["count"]    is not None else 0
            cash    = parse_amount_jpy(row[idx["cash"]])     if idx["cash"]     is not None else 0
            card    = parse_amount_jpy(row[idx["card"]])     if idx["card"]     is not None else 0
            emoney  = parse_amount_jpy(row[idx["emoney"]])   if idx["emoney"]   is not None else 0
            segment = row[idx["segment"]].strip()            if idx["segment"]  is not None else ""
            date_raw= row[idx["date"]].strip()               if idx["date"]     is not None else ""

            # 主な支払い方法を判定
            if card > 0:
                payment = "カード"
            elif emoney > 0:
                payment = "QR"
            elif cash > 0:
                payment = "現金"
            else:
                payment = "その他"

            # 客層から集客経路を抽出（例: "集客：紹介／客層：ファミリー／住居：地元"）
            source = ""
            if "集客：" in segment:
                source = segment.split("集客：")[-1].split("／")[0]

            records.append({
                "date":    normalize_date(date_raw),
                "menu":    "火鍋コース",  # USEN伝票データにはメニュー詳細なし（別CSVで取得）
                "amount":  amount,
                "qty":     1,
                "count":   count,
                "cash":    cash,
                "card":    card,
                "qr":      emoney,
                "payment": payment,
                "source":  source,
            })
        except (ValueError, IndexError):
            continue
    return records


# ─────────────────────────────────────────────────────────────
# 日次集計（取引明細 → 1日1行）
# ─────────────────────────────────────────────────────────────
def aggregate_daily(records: list[dict]) -> list[dict]:
    """取引明細を日付単位に集計（Airegi = 取引行ベース / USEN = 伝票ベース）"""
    by_date: dict[str, dict] = {}
    for r in records:
        d = r["date"]
        if not d:
            continue
        if d not in by_date:
            by_date[d] = {"date": d, "amount": 0, "count": 0, "cash": 0, "card": 0, "qr": 0, "menus": []}
        by_date[d]["amount"] += r["amount"]
        # USEN: 客数フィールドあり / Airegi: qtyで代替
        by_date[d]["count"]  += r.get("count", 0) or r.get("qty", 1)
        by_date[d]["menus"].append(r["menu"])
        # USEN: 個別に金額フィールドあり
        if "cash" in r:
            by_date[d]["cash"] += r["cash"]
            by_date[d]["card"] += r["card"]
            by_date[d]["qr"]   += r["qr"]
        else:
            pm = r.get("payment", "")
            if pm == "現金":
                by_date[d]["cash"] += r["amount"]
            elif pm == "カード":
                by_date[d]["card"] += r["amount"]
            elif pm == "QR":
                by_date[d]["qr"]   += r["amount"]

    result = []
    for d in sorted(by_date.keys()):
        day = by_date[d]
        per_person = round(day["amount"] / day["count"]) if day["count"] > 0 else 0
        result.append({
            "date":     d,
            "month":    d[:7] if len(d) >= 7 else "",
            "amount":   day["amount"],
            "count":    day["count"],
            "per_head": per_person,
            "cash":     day["cash"],
            "card":     day["card"],
            "qr":       day["qr"],
            "menus":    list(set(day["menus"])),
        })
    return result


# ─────────────────────────────────────────────────────────────
# スプレッドシート書き込み（02_日次売上 フォーマット）
# ─────────────────────────────────────────────────────────────
def write_daily_sales(ss, daily: list[dict], source_file: str) -> int:
    """
    02_日次売上 シートへ追記（重複日付はスキップ）
    列: A=月, B=日付, C=売上金額, D=客数, E=客単価, F=テーブル数, G=回転数,
        H=現金, I=カード, J=QR決済, K=メモ
    """
    try:
        sh = ss.worksheet("02_日次売上")
    except gspread.WorksheetNotFound:
        print("  ⚠ 02_日次売上 シートが見つかりません")
        return 0

    existing = sh.col_values(2)[2:]  # ヘッダー2行除く（B列=日付）
    written = 0
    rows_to_add = []

    for day in daily:
        if day["date"] in existing:
            print(f"    ⏭ {day['date']}: 既存データのためスキップ")
            continue
        rows_to_add.append([
            f'=TEXT(B{sh.row_count + written + 3},"yyyy/mm")',  # A: 月（数式）
            day["date"],
            day["amount"],
            day["count"],
            day["per_head"],
            "",   # テーブル数（手入力）
            "",   # 回転数（手入力）
            day["cash"],
            day["card"],
            day["qr"],
            f"Airレジ/USEN自動取込: {source_file}",
        ])
        written += 1

    if rows_to_add:
        sh.append_rows(rows_to_add, value_input_option="USER_ENTERED")

    return written


# ─────────────────────────────────────────────────────────────
# 前日比・前週比・前月比 自動計算（KPIシート更新）
# ─────────────────────────────────────────────────────────────
def update_kpi_trends(ss) -> dict:
    """02_日次売上から前日比・前週比を計算してKPI用辞書を返す"""
    try:
        sh = ss.worksheet("02_日次売上")
        rows = sh.get_all_values()[2:]  # ヘッダー2行除く
    except Exception:
        return {}

    sales_by_date = {}
    for row in rows:
        if len(row) >= 3 and row[1] and row[2]:
            try:
                sales_by_date[row[1]] = int(str(row[2]).replace(",", ""))
            except ValueError:
                pass

    today = date.today().strftime("%Y/%m/%d")
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y/%m/%d")
    last_week = (date.today() - timedelta(days=7)).strftime("%Y/%m/%d")
    this_month_prefix = date.today().strftime("%Y/%m")
    last_month = (date.today().replace(day=1) - timedelta(days=1))
    last_month_prefix = last_month.strftime("%Y/%m")

    today_sales    = sales_by_date.get(today, 0)
    yesterday_sales = sales_by_date.get(yesterday, 0)
    last_week_sales = sales_by_date.get(last_week, 0)
    this_month_total = sum(v for k, v in sales_by_date.items() if k.startswith(this_month_prefix))
    last_month_total = sum(v for k, v in sales_by_date.items() if k.startswith(last_month_prefix))

    return {
        "today":            today_sales,
        "yesterday":        yesterday_sales,
        "day_over_day":     round((today_sales / yesterday_sales - 1) * 100, 1) if yesterday_sales else 0,
        "week_over_week":   round((today_sales / last_week_sales - 1) * 100, 1) if last_week_sales else 0,
        "this_month":       this_month_total,
        "last_month":       last_month_total,
        "month_over_month": round((this_month_total / last_month_total - 1) * 100, 1) if last_month_total else 0,
    }


# ─────────────────────────────────────────────────────────────
# Alert Engine（売上異常検知）
# ─────────────────────────────────────────────────────────────
def check_alerts(trends: dict, biz_name: str, targets: dict) -> list[str]:
    """KPIを閾値チェックしてAlertリストを返す"""
    alerts = []
    monthly_target = targets.get("monthly_target", 0)
    month_progress = date.today().day / 30

    if trends.get("day_over_day", 0) <= -20:
        alerts.append(f"🔴 {biz_name}: 前日比 {trends['day_over_day']}%（-20%超）")
    if trends.get("week_over_week", 0) <= -20:
        alerts.append(f"🔴 {biz_name}: 前週比 {trends['week_over_week']}%（-20%超）")
    if monthly_target and month_progress >= 0.5:
        achievement = trends.get("this_month", 0) / monthly_target
        if achievement < month_progress * 0.8:
            alerts.append(f"🟡 {biz_name}: 月間達成率 {achievement*100:.0f}%（月の{month_progress*100:.0f}%経過）")

    return alerts


def send_line_alert(token: str, message: str):
    if not token or len(token) < 100:
        return
    import requests
    requests.post(
        "https://api.line.me/v2/bot/message/broadcast",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"messages": [{"type": "text", "text": message}]},
        timeout=10,
    )


# ─────────────────────────────────────────────────────────────
# Airレジ 日次集計CSVパース（売上集計_YYYYMMDD-YYYYMMDD.csv 形式）
#
# ヘッダー例:
#   集計期間 / 売上 / 会計数 / 会計単価 / 客数 / 客単価 / 商品数
#   / 現金支払合計額 / 現金その他支払合計額 / 割引額
# ─────────────────────────────────────────────────────────────
def parse_airegi_daily_agg(rows: list[list[str]], biz_name: str) -> list[dict]:
    """Airレジ 日次集計CSV（集計期間=YYYYMMDD形式）をパース"""
    if not rows:
        return []
    headers = [h.strip() for h in rows[0]]

    def col(names):
        for n in names:
            for i, h in enumerate(headers):
                if n in h:
                    return i
        return None

    idx_date   = col(["集計期間"])
    idx_amount = col(["売上"])
    idx_count  = col(["客数"])
    idx_cash   = col(["現金支払合計額"])
    idx_other  = col(["現金その他", "その他支払"])
    idx_disc   = col(["割引"])

    records = []
    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        try:
            date_raw = str(row[idx_date]).strip() if idx_date is not None else ""
            if len(date_raw) == 8:
                date_str = f"{date_raw[:4]}/{date_raw[4:6]}/{date_raw[6:8]}"
            elif len(date_raw) == 6:
                # 月次集計（YYYYMM）→ 月末日として扱う
                date_str = f"{date_raw[:4]}/{date_raw[4:6]}/01"
            else:
                continue

            amount = int(str(row[idx_amount]).replace(",","").strip() or 0) if idx_amount is not None else 0
            if amount <= 0:
                continue
            count  = int(str(row[idx_count]).replace(",","").strip() or 0)  if idx_count  is not None else 0
            cash   = int(str(row[idx_cash]).replace(",","").strip()   or 0)  if idx_cash   is not None else 0
            other  = int(str(row[idx_other]).replace(",","").strip()  or 0)  if idx_other  is not None else 0

            records.append({
                "date":     date_str,
                "menu":     "売上集計",
                "amount":   amount,
                "qty":      count,
                "count":    count,
                "cash":     cash,
                "card":     other,  # 「その他」=カード+QR合算
                "qr":       0,
                "payment":  "混在",
                "raw_menu": "",
            })
        except (ValueError, IndexError):
            continue
    return records


def detect_csv_format(rows: list[list[str]]) -> str:
    """CSVヘッダーからフォーマットを判定。'daily_agg' / 'transaction' / 'unknown'"""
    if not rows:
        return "unknown"
    header = [h.strip() for h in rows[0]]
    if "集計期間" in header:
        return "daily_agg"
    if any(h in header for h in ["取引日", "売上日", "日付", "商品名", "品名"]):
        return "transaction"
    return "unknown"


# ─────────────────────────────────────────────────────────────
# V2: 追加機能（既存関数は変更しない）
# IMPORT_LOG / POS_日次売上 / POS_KPI / バックアップ/復元
# ─────────────────────────────────────────────────────────────

def compute_checksum(raw: bytes) -> str:
    """CSVバイト列のMD5チェックサム（先頭12文字）"""
    return hashlib.md5(raw).hexdigest()[:12]


def _get_or_create_append(ss, title: str, rows: int = 500, cols: int = 12):
    """シートを取得（なければ作成）。既存データはクリアしない。"""
    try:
        return ss.worksheet(title)
    except gspread.WorksheetNotFound:
        return ss.add_worksheet(title=title, rows=rows, cols=cols)


def backup_sheet(ss, sheet_name: str) -> str:
    """
    対象シートの全データをバックアップシートにコピーする。
    バックアップシート名を返す（空文字=元シートなし）。
    復元: バックアップシートの内容を元シートに貼り直すだけ。
    """
    ts = datetime.now().strftime("%m%d_%H%M%S")
    backup_name = f"BAK_{ts}_{sheet_name}"[:50]
    try:
        src = ss.worksheet(sheet_name)
        data = src.get_all_values()
        bak = ss.add_worksheet(title=backup_name, rows=max(len(data) + 10, 30), cols=15)
        if data:
            bak.update(range_name="A1", values=data, value_input_option="RAW")
        restore_note = (
            f"[バックアップ {datetime.now().strftime('%Y/%m/%d %H:%M')}]"
            f" 復元方法: このシートをA1から全選択→コピー→{sheet_name}のA1に貼り付け"
        )
        bak.update_cell(bak.row_count, 1, restore_note)
        print(f"    📋 バックアップ作成: {backup_name}")
        return backup_name
    except gspread.WorksheetNotFound:
        return ""
    except Exception as e:
        print(f"    ⚠ バックアップ作成失敗（処理は続行）: {e}")
        return ""


def restore_from_backup(ss, backup_sheet_name: str, target_sheet_name: str) -> bool:
    """バックアップシートから元シートを復元する。1クリック復元用。"""
    try:
        bak = ss.worksheet(backup_sheet_name)
        data = bak.get_all_values()
        # 最終行の復元ノートを除外
        data = [r for r in data if not (r and str(r[0]).startswith("[バックアップ"))]
        target = _get_or_create_append(ss, target_sheet_name, rows=max(len(data) + 10, 50), cols=15)
        target.clear()
        if data:
            target.update(range_name="A1", values=data, value_input_option="RAW")
        print(f"  ✅ 復元完了: {backup_sheet_name} → {target_sheet_name}")
        return True
    except Exception as e:
        print(f"  ❌ 復元失敗: {e}")
        return False


IMPORT_LOG_HEADERS = ["ファイル名", "ファイルID", "取込日時", "チェックサム", "ステータス", "取込件数", "エラー内容"]

def check_import_log(ss, file_id: str, checksum: str) -> bool:
    """IMPORT_LOGを確認。True = 同一ファイルのためスキップすべき。"""
    try:
        sh = _get_or_create_append(ss, "IMPORT_LOG", rows=500, cols=7)
        rows = sh.get_all_values()
        for row in rows[1:]:
            if len(row) >= 5 and row[4] == "success":
                if row[1] == file_id or row[3] == checksum:
                    return True
        return False
    except Exception as e:
        print(f"    ⚠ IMPORT_LOG確認エラー（スキップしない）: {e}")
        return False


def record_import_log(ss, file_name: str, file_id: str, checksum: str,
                      status: str, count: int, error_msg: str = "") -> None:
    """IMPORT_LOGに取込結果を記録する。"""
    try:
        sh = _get_or_create_append(ss, "IMPORT_LOG", rows=500, cols=7)
        if not any(sh.row_values(1)):
            sh.update(range_name="A1:G1", values=[IMPORT_LOG_HEADERS])
        sh.append_row([
            file_name, file_id,
            datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
            checksum, status, count, error_msg,
        ], value_input_option="RAW")
    except Exception as e:
        print(f"    ⚠ IMPORT_LOG記録エラー: {e}")


POS_DAILY_HEADERS = ["月", "日付", "売上", "客数", "客単価", "現金", "カード", "QR決済", "取込元"]

def write_pos_daily(ss, daily: list[dict], source_file: str) -> int:
    """
    POS_日次売上 シートへ追記（既存の 02_日次売上 は変更しない）。
    重複日付はスキップ。書き込み前にバックアップを自動作成。
    返り値: 書き込んだ日数
    """
    backup_sheet(ss, "POS_日次売上")
    sh = _get_or_create_append(ss, "POS_日次売上", rows=500, cols=9)

    if not any(sh.row_values(1)):
        sh.update(range_name="A1:I1", values=[POS_DAILY_HEADERS])

    existing_dates = set(v for v in sh.col_values(2)[1:] if v)

    rows_to_add = []
    for day in daily:
        if day["date"] in existing_dates:
            continue
        rows_to_add.append([
            day["date"][:7],
            day["date"],
            day["amount"],
            day["count"],
            day["per_head"],
            day["cash"],
            day["card"],
            day["qr"],
            source_file,
        ])
        existing_dates.add(day["date"])

    if rows_to_add:
        sh.append_rows(rows_to_add, value_input_option="RAW")

    return len(rows_to_add)


POS_KPI_HEADERS = ["年月", "売上", "客数", "客単価", "前月比(%)", "前週比(%)", "達成率(%)", "更新日時"]

def update_pos_kpi(ss, monthly_target: int = 0) -> dict:
    """
    POS_日次売上 → 月次KPI集計 → POS_KPI シートへ書き込む。
    CEO Dashboard は POS_KPI を参照する（POS_日次売上は直接参照しない）。
    返り値: 最新月のKPI辞書
    """
    try:
        daily_sh = ss.worksheet("POS_日次売上")
        rows = daily_sh.get_all_values()[1:]
    except Exception:
        return {}

    sales_by_date: dict[str, dict] = {}
    for row in rows:
        if len(row) >= 5 and row[1] and row[2]:
            try:
                sales_by_date[row[1]] = {
                    "amount":   int(str(row[2]).replace(",", "") or 0),
                    "count":    int(str(row[3]).replace(",", "") or 0),
                    "per_head": int(str(row[4]).replace(",", "") or 0),
                }
            except ValueError:
                pass

    # 月次集計
    monthly: dict[str, dict] = {}
    for dt, vals in sales_by_date.items():
        m = dt[:7]
        if m not in monthly:
            monthly[m] = {"amount": 0, "count": 0}
        monthly[m]["amount"] += vals["amount"]
        monthly[m]["count"]  += vals["count"]

    sorted_months = sorted(monthly.keys())
    kpi_rows: list[list] = [POS_KPI_HEADERS]
    latest_kpi: dict = {}
    now_str = datetime.now().strftime("%Y/%m/%d %H:%M")

    for i, month in enumerate(sorted_months):
        m = monthly[month]
        avg = round(m["amount"] / m["count"]) if m["count"] > 0 else 0

        # 前月比
        mom = 0.0
        if i > 0:
            prev_amt = monthly[sorted_months[i - 1]]["amount"]
            if prev_amt > 0:
                mom = round((m["amount"] / prev_amt - 1) * 100, 1)

        # 前週比（当月内の最終7日 vs その前7日）
        days_in_month = sorted(d for d in sales_by_date if d.startswith(month))
        wow = 0.0
        if len(days_in_month) >= 14:
            last7 = sum(sales_by_date[d]["amount"] for d in days_in_month[-7:])
            prev7 = sum(sales_by_date[d]["amount"] for d in days_in_month[-14:-7])
            if prev7 > 0:
                wow = round((last7 / prev7 - 1) * 100, 1)

        achievement = round(m["amount"] / monthly_target * 100, 1) if monthly_target > 0 else 0

        kpi_rows.append([month, m["amount"], m["count"], avg, mom, wow, achievement, now_str])
        latest_kpi = {
            "this_month":       m["amount"],
            "count":            m["count"],
            "per_head":         avg,
            "month_over_month": mom,
            "week_over_week":   wow,
            "achievement_rate": achievement,
        }

    # POS_KPI シートへ全行書き込み（バックアップ後に全更新）
    backup_sheet(ss, "POS_KPI")
    kpi_sh = _get_or_create_append(ss, "POS_KPI", rows=50, cols=8)
    kpi_sh.clear()
    if len(kpi_rows) > 1:
        kpi_sh.update(range_name="A1", values=kpi_rows, value_input_option="RAW")

    return latest_kpi


# ─────────────────────────────────────────────────────────────
# メイン処理（事業別に呼ぶ）
# ─────────────────────────────────────────────────────────────
def run(
    biz_name: str,
    spreadsheet_id: str,
    airegi_folder_id: str,
    done_folder_id: str,
    creds_path: str,
    pos_type: str = "airegi",  # "airegi" or "usen"
    line_token: str = "",
    monthly_target: int = 1_000_000,
) -> dict:
    print(f"\n{'='*55}")
    print(f"{biz_name} POS取込処理開始")
    print(f"  POS種別: {pos_type.upper()}")
    print(f"{'='*55}")

    drive, gc = get_services(creds_path)
    ss = gc.open_by_key(spreadsheet_id)

    csv_files = list_csv_files(drive, airegi_folder_id)
    print(f"\n  未処理CSV: {len(csv_files)}件")

    if not csv_files:
        print("  新規ファイルなし。処理スキップ。")
        return {"ok": True, "written": 0, "alerts": [], "trends": {}}

    total_written = 0
    errors        = []

    for f in csv_files:
        fname    = f["name"]
        fid      = f["id"]
        checksum = ""
        print(f"\n  処理中: {fname}")
        try:
            rows, raw = download_csv(drive, fid)
            checksum  = compute_checksum(raw)

            # 重複チェック（IMPORT_LOG）
            if check_import_log(ss, fid, checksum):
                print(f"    ⏭ スキップ（IMPORT_LOG記録済み）")
                continue

            # パース（フォーマット自動検知）
            if pos_type == "usen":
                records = parse_usen(rows, biz_name)
            else:
                fmt = detect_csv_format(rows)
                if fmt == "daily_agg":
                    records = parse_airegi_daily_agg(rows, biz_name)
                else:
                    records = parse_airegi(rows, biz_name)
                print(f"    フォーマット検知: {fmt} → {len(records)}件")

            daily = aggregate_daily(records)

            # POS_日次売上 へ書き込み（バックアップ自動作成）
            count = write_pos_daily(ss, daily, fname)

            # ログ記録・移動
            record_import_log(ss, fname, fid, checksum, "success", count)
            move_to_done(drive, fid, done_folder_id)
            total_written += count
            print(f"    → {count}日分を POS_日次売上 へ反映（{len(records)}件の取引）")
            time.sleep(1)

        except Exception as e:
            msg = str(e)
            print(f"    ❌ エラー: {msg}")
            record_import_log(ss, fname, fid, checksum, "error", 0, msg)
            errors.append(f"{fname}: {msg}")

    # POS_日次売上 → POS_KPI 集計（バックアップ自動作成）
    print(f"\n  POS_KPI を更新中...")
    trends = update_pos_kpi(ss, monthly_target)
    print(f"  📊 KPI概況（POS_KPI）:")
    print(f"    今月売上:   ¥{trends.get('this_month', 0):,}")
    print(f"    前月比:     {trends.get('month_over_month', 0):+.1f}%")
    print(f"    前週比:     {trends.get('week_over_week', 0):+.1f}%")
    print(f"    達成率:     {trends.get('achievement_rate', 0):.1f}%")

    # Alert チェック
    alerts = check_alerts(trends, biz_name, {"monthly_target": monthly_target})
    if alerts:
        alert_msg = "\n".join(alerts)
        print(f"\n  ⚠ Alert:\n{alert_msg}")
        if line_token:
            send_line_alert(line_token, f"⚠️ YU HOLDINGS Alert\n\n{alert_msg}")

    print(f"\n✅ {biz_name} POS取込完了: {total_written}日分")
    return {
        "ok":      len(errors) == 0,
        "written": total_written,
        "trends":  trends,
        "alerts":  alerts,
        "errors":  errors,
    }
