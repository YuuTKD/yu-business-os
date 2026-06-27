"""
Daily Sales Screenshot Capture OS
-----------------------------------
各事業スタッフがLINE公式へ売上スクショを送信 → AIが画像から売上数値を読み取り
→ スプレッドシートへ日次売上として記録 → 異常値・未報告を検知する仕組み。

フロー:
  1. LINE公式で画像受信（Webhook）
  2. LINE Messaging API で画像バイナリ取得
  3. 画像を GCS へ保存
  4. OpenAI Vision (gpt-4o) で売上数値を構造化抽出
  5. SALES_SCREENSHOT_LOG へ記録
  6. 信頼度・異常値で判定（自動記録 / 確認待ち / 再送依頼 / オーナー確認）
  7. POS_日次売上 へ仮反映 → POS_KPI へ日次集計
  8. Knowledge OS へ日次売上Markdown保存
  9. 未報告事業を検知

安全設計:
  - DRY_RUN=True のとき LINE送信・本番反映をスキップし通知文のみ生成
  - 秘密情報（トークン等）を Markdown / ログに出力しない
  - 同一事業・同一日付の重複は自動上書きしない
"""

import os
import io
import json
import base64
from datetime import datetime, timezone, timedelta

import requests
import gspread
from google.oauth2.service_account import Credentials
from google.cloud import storage as gcs_storage

JST = timezone(timedelta(hours=9))
GCS_BUCKET  = "tree-beauty-blog-images"
GCS_PREFIX  = "knowledge-os"
GCS_IMG_PREFIX = "sales-screenshots"
GCS_PROJECT = "tree-beauty-ai-499303"

# ── 判定しきい値 ───────────────────────────────────────────
CONF_AUTO    = 0.90   # これ以上: 自動記録
CONF_CONFIRM = 0.70   # これ以上: 仮記録＋確認依頼 / 未満: 再送依頼
ANOMALY_RATE = 0.50   # 前日比 ±50% 以上で異常値

# ── 事業設定 ───────────────────────────────────────────────
# screenshot_ok=False はコンサル業態（POSなし）→ スクショ読取対象外
SALES_BIZ_CONFIG = {
    "tachinomiya": {
        "name": "TACHINOMIYA", "ss_env": "TACHINOMIYA_SPREADSHEET_ID",
        "token_env": "LINE_TACHINOMIYASTAFF_TOKEN",
        "secret_env": "LINE_TACHINOMIYA_CHANNEL_SECRET",
        "dest_env": "LINE_TACHINOMIYA_DESTINATION",
        "monthly_target": 3_500_000, "screenshot_ok": True, "folder": "TACHINOMIYA",
    },
    "catering": {
        "name": "TREE's Catering", "ss_env": "CATERING_SPREADSHEET_ID",
        "token_env": "LINE_cateringSTAFF_TOKEN",
        "secret_env": "LINE_CATERING_CHANNEL_SECRET",
        "dest_env": "LINE_CATERING_DESTINATION",
        "monthly_target": 800_000, "screenshot_ok": True, "folder": "Trees_Catering",
    },
    "beauty": {
        "name": "Tree Beauty", "ss_env": "BEAUTY_SPREADSHEET_ID",
        "token_env": "LINE_STAFF_TOKEN",
        "secret_env": "LINE_BEAUTY_CHANNEL_SECRET",
        "dest_env": "LINE_BEAUTY_DESTINATION",
        "monthly_target": 500_000, "screenshot_ok": True, "folder": "Tree_Beauty",
    },
    "ryukyu_hinabe": {
        "name": "琉球火鍋", "ss_env": "HINABE_SPREADSHEET_ID",
        "token_env": "LINE_hinabeSTAFF_TOKEN",
        "secret_env": "LINE_HINABE_CHANNEL_SECRET",
        "dest_env": "LINE_HINABE_DESTINATION",
        "monthly_target": 1_500_000, "screenshot_ok": True, "folder": "Ryukyu_Hinabe",
    },
    "pasta_pasta": {
        "name": "パスタパスタ", "ss_env": "PASTA_SPREADSHEET_ID",
        "token_env": "", "secret_env": "", "dest_env": "",
        "monthly_target": 2_000_000, "screenshot_ok": False, "folder": "Pasta_Pasta",
    },
    "z1": {
        "name": "Z1", "ss_env": "Z1_SPREADSHEET_ID",
        "token_env": "", "secret_env": "", "dest_env": "",
        "monthly_target": 1_500_000, "screenshot_ok": False, "folder": "Z1",
    },
}

# スクショ対象事業（POS業態のみ）
SCREENSHOT_BIZ_KEYS = [k for k, v in SALES_BIZ_CONFIG.items() if v["screenshot_ok"]]

# ── シート定義 ─────────────────────────────────────────────
SCREENSHOT_SHEETS = {
    "SALES_SCREENSHOT_LOG": [
        "登録日時", "事業名", "LINEチャンネル", "送信者", "対象日", "画像URL",
        "読み取り売上", "読み取り客数", "読み取り客単価", "現金", "カード",
        "電子決済", "割引", "返金", "AI信頼度", "判定ステータス",
        "確認ステータス", "反映ステータス", "異常検知", "エラー内容", "Obsidian Path",
    ],
    "DAILY_SALES_CONFIRMATION": [
        "日付", "事業名", "売上", "客数", "客単価", "前日比",
        "目標日販", "達成率", "報告状況", "確認状況", "担当者", "次アクション",
    ],
    "SALES_SCREENSHOT_ERROR_LOG": [
        "日時", "事業名", "画像URL", "エラー種別", "エラー内容",
        "再送依頼状況", "対応状況",
    ],
}


# ── 内部ユーティリティ ────────────────────────────────────

def _now_jst() -> str:
    return datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")


def _date_jst() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d")


def _gc(creds_path: str) -> gspread.Client:
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    return gspread.authorize(creds)


def _gcs(creds_path: str) -> gcs_storage.Client:
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/devstorage.read_write"],
    )
    return gcs_storage.Client(project=GCS_PROJECT, credentials=creds)


def _upload_md_gcs(creds_path: str, gcs_path: str, content: str) -> str:
    client = _gcs(creds_path)
    blob = client.bucket(GCS_BUCKET).blob(gcs_path)
    blob.upload_from_string(content.encode("utf-8"), content_type="text/markdown")
    return f"https://storage.googleapis.com/{GCS_BUCKET}/{gcs_path}"


def _upload_image_gcs(creds_path: str, gcs_path: str, image_bytes: bytes,
                      content_type: str = "image/jpeg") -> str:
    client = _gcs(creds_path)
    blob = client.bucket(GCS_BUCKET).blob(gcs_path)
    blob.upload_from_string(image_bytes, content_type=content_type)
    return f"https://storage.googleapis.com/{GCS_BUCKET}/{gcs_path}"


def _get_or_create_sheet(ss: gspread.Spreadsheet, title: str, header: list) -> gspread.Worksheet:
    try:
        return ss.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=title, rows=2000, cols=len(header))
        ws.update(values=[header], range_name="A1")
        ws.format("A1:U1", {
            "backgroundColor": {"red": 0.20, "green": 0.12, "blue": 0.02},
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        })
        return ws


def _parse_int(val) -> int:
    if val is None:
        return 0
    cleaned = str(val).replace(",", "").replace("¥", "").replace("円", "").replace(" ", "").strip()
    try:
        return int(float(cleaned))
    except (ValueError, TypeError):
        return 0


def _biz_key_from_name(name: str) -> str:
    for k, v in SALES_BIZ_CONFIG.items():
        if v["name"] == name or k == name:
            return k
    return ""


# ── LINE 画像取得 ─────────────────────────────────────────

def _fetch_line_image(message_id: str, token: str) -> bytes:
    """LINE Messaging API から画像バイナリを取得"""
    resp = requests.get(
        f"https://api-data.line.me/v2/bot/message/{message_id}/content",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.content


def _send_line_reply(reply_token: str, message: str, access_token: str) -> bool:
    """LINE Reply 送信（DRY_RUN時は呼ばない）"""
    if not reply_token or not access_token:
        return False
    try:
        resp = requests.post(
            "https://api.line.me/v2/bot/message/reply",
            headers={"Authorization": f"Bearer {access_token}",
                     "Content-Type": "application/json"},
            json={"replyToken": reply_token, "messages": [{"type": "text", "text": message}]},
            timeout=10,
        )
        return resp.ok
    except Exception:
        return False


# ══════════════════════════════════════════════════════════
#  OCRプロバイダ切替
#   SALES_OCR_PROVIDER = "vision"(既定/無料) | "openai"
# ══════════════════════════════════════════════════════════

def analyze_image(image_bytes: bytes, business_name: str,
                  creds_path: str = "") -> dict:
    """
    売上スクショを構造化抽出する統一エントリ。
    既定は Google Cloud Vision（無料枠）。環境変数で OpenAI に切替可能。
    """
    provider = os.getenv("SALES_OCR_PROVIDER", "vision").lower()
    if provider == "openai":
        return analyze_sales_image(image_bytes, business_name)
    # 既定: Vision（失敗時、OpenAIキーがあればフォールバック）
    res = analyze_sales_image_vision(image_bytes, business_name, creds_path)
    if res.get("_error") and os.getenv("OPENAI_API_KEY", ""):
        alt = analyze_sales_image(image_bytes, business_name)
        if not alt.get("_error"):
            alt["note"] = (alt.get("note", "") + " [Visionフォールバック→OpenAI]").strip()
            return alt
    return res


# ── Google Cloud Vision OCR（無料枠・既定） ───────────────

# 数値抽出用ラベル辞書（POS画面の表記ゆれに対応）
_VISION_LABELS = {
    "sales":     ["売上合計", "純売上", "総売上", "税込売上", "売上", "総売", "合計金額", "お会計", "総計"],
    "customers": ["客数", "組数", "来客数", "人数", "総客数", "会計数", "客数合計"],
    "avg_spend": ["客単価", "平均単価", "一人当", "客単"],
    "cash":      ["現金", "現金売上"],
    "card":      ["クレジット", "カード", "クレカ", "信用"],
    "emoney":    ["電子マネー", "電子決済", "QR", "QR決済", "ｸﾞ", "交通系", "PayPay", "iD", "QUICPay"],
    "discount":  ["値引", "割引", "値引き"],
    "refund":    ["返金", "返品"],
}


def _yen_to_int(token: str) -> int | None:
    """¥金額トークンを整数化（¥・カンマ・ピリオド桁区切り・全角を除去）"""
    z2h = str.maketrans("０１２３４５６７８９", "0123456789")
    t = token.translate(z2h)
    # 通貨は整数（円）のため、数字以外を全除去（91.960/91,960 → 91960）
    digits = "".join(ch for ch in t if ch.isdigit())
    return int(digits) if digits else None


def _label_nearby_int(lines: list, keys: list, lo: int, hi: int,
                      look_ahead: int = 2) -> int | None:
    """ラベル行とその直後数行から lo〜hi の整数を探す（¥なしの個数系向け）"""
    import re
    z2h = str.maketrans("０１２３４５６７８９", "0123456789")
    for i, ln in enumerate(lines):
        if any(kw in ln for kw in keys):
            # ラベル以降〜look_ahead行を走査
            for j in range(i, min(i + 1 + look_ahead, len(lines))):
                seg = lines[j].translate(z2h)
                if j == i:
                    # ラベル自体の後ろ側のみ見る
                    for kw in keys:
                        if kw in seg:
                            seg = seg.split(kw, 1)[1]
                            break
                for n in re.findall(r"\d[\d,]*", seg):
                    v = int(n.replace(",", ""))
                    if lo <= v <= hi:
                        return v
    return None


def _parse_vision_text(full_text: str) -> dict:
    """Vision OCRの全文テキストから売上各値をルールベース抽出（POS2カラム配置対応）"""
    import re
    z2h = str.maketrans("０１２３４５６７８９，．：", "0123456789,.:")
    raw_lines = [ln.strip() for ln in full_text.translate(z2h).splitlines() if ln.strip()]

    result = {k: None for k in
              ["date", "sales", "customers", "avg_spend", "cash", "card",
               "emoney", "discount", "refund", "confidence", "note"]}

    joined = " ".join(raw_lines)

    # 日付
    m = re.search(r"(20\d{2})[/\-年\.](\d{1,2})[/\-月\.](\d{1,2})", joined)
    if m:
        result["date"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # ── 売上合計 = 画面内の最大¥金額（POSの売上合計は常に最大）──
    yen_amounts = []
    for tok in re.findall(r"[¥\\][\d.,]+", joined):
        v = _yen_to_int(tok)
        if v and v < 100_000_000:   # 1億円未満の常識範囲
            yen_amounts.append(v)
    # ¥記号が落ちた場合の保険：カンマ付き大きな数も拾う
    for tok in re.findall(r"\d{1,3}(?:,\d{3})+", joined):
        v = int(tok.replace(",", ""))
        if v and v < 100_000_000:
            yen_amounts.append(v)

    if yen_amounts:
        result["sales"] = max(yen_amounts)

    # ── 客数（¥なしの整数・1〜9999）──
    result["customers"] = (
        _label_nearby_int(raw_lines, ["客数"], 1, 9999) or
        _label_nearby_int(raw_lines, ["会計数", "組数", "来客数"], 1, 9999)
    )

    # ── 客単価（「客単価」を厳密優先。会計単価は別指標なので除外）──
    result["avg_spend"] = _label_nearby_int(raw_lines, ["客単価"], 1, 1_000_000)

    # ── 決済内訳（ベストエフォート：ラベル直後の最初の¥金額）──
    def first_yen_after(keys):
        for i, ln in enumerate(raw_lines):
            if any(kw in ln for kw in keys):
                for j in range(i, min(i + 3, len(raw_lines))):
                    seg = raw_lines[j]
                    if j == i:
                        for kw in keys:
                            if kw in seg:
                                seg = seg.split(kw, 1)[1]; break
                    mm = re.search(r"[¥\\]([\d.,]+)", seg)
                    if mm:
                        v = _yen_to_int(mm.group(1))
                        if v is not None:
                            return v
        return None

    result["cash"]     = first_yen_after(["現金売上", "現金"])
    result["card"]     = first_yen_after(["クレジット", "カード", "クレカ"])
    result["emoney"]   = first_yen_after(["QR決済", "QR", "電子マネー", "電子決済", "交通系"])
    result["discount"] = first_yen_after(["割引", "値引"])
    result["refund"]   = first_yen_after(["返金"])

    # 決済内訳の誤検出ガード: 売上合計と同額を拾った場合は無効化（2カラム配置での取り違え対策）
    for f in ["cash", "card", "emoney"]:
        if result.get(f) is not None and result.get(f) == result.get("sales"):
            result[f] = None

    # 客単価が無く売上・客数があれば計算
    if not result.get("avg_spend") and result.get("sales") and result.get("customers"):
        try:
            result["avg_spend"] = int(result["sales"]) // int(result["customers"])
        except (ValueError, ZeroDivisionError, TypeError):
            pass

    # ── 信頼度 ──
    if result.get("sales") is None:
        result["confidence"] = 0.3
        result["note"] = "売上金額を検出できず"
    else:
        # 売上検出=0.75ベース、客数も取れたら+0.15、客単価整合で+0.05
        conf = 0.75
        if result.get("customers"):
            conf += 0.15
        # 売上÷客数 と 読み取り客単価 が近ければ整合ボーナス
        if result.get("customers") and result.get("avg_spend"):
            calc = result["sales"] // result["customers"]
            if abs(calc - result["avg_spend"]) <= max(50, result["avg_spend"] * 0.1):
                conf += 0.05
        result["confidence"] = min(0.97, conf)
        result["note"] = "Vision OCR（売上=最大金額方式）"

    return result


def analyze_sales_image_vision(image_bytes: bytes, business_name: str,
                               creds_path: str = "") -> dict:
    """Google Cloud Vision でOCR → ルールベース構造化"""
    creds_path = creds_path or os.getenv("GOOGLE_CREDS_PATH", "")
    try:
        from google.cloud import vision
        if creds_path:
            from google.oauth2.service_account import Credentials as SACreds
            sa = SACreds.from_service_account_file(
                creds_path, scopes=["https://www.googleapis.com/auth/cloud-platform"])
            client = vision.ImageAnnotatorClient(credentials=sa)
        else:
            client = vision.ImageAnnotatorClient()

        image = vision.Image(content=image_bytes)
        resp = client.document_text_detection(image=image)
        if resp.error.message:
            return {"_error": f"Vision API: {resp.error.message}", "confidence": 0.0}

        full_text = resp.full_text_annotation.text if resp.full_text_annotation else ""
        if not full_text.strip():
            return {"_error": "テキスト未検出（画像が不鮮明/文字なし）", "confidence": 0.0}

        return _parse_vision_text(full_text)
    except Exception as e:
        return {"_error": f"Vision処理失敗: {e}", "confidence": 0.0}


# ── OpenAI Vision OCR（オプション） ───────────────────────

def analyze_sales_image(image_bytes: bytes, business_name: str,
                        openai_key: str = "") -> dict:
    """
    売上スクショから売上数値を構造化抽出（OpenAI gpt-4o）。
    返り値: dict（売上・客数・客単価・各決済・信頼度など）
    """
    openai_key = openai_key or os.getenv("OPENAI_API_KEY", "")
    if not openai_key:
        return {"_error": "OPENAI_API_KEY 未設定", "confidence": 0.0}

    from openai import OpenAI
    client = OpenAI(api_key=openai_key)

    b64 = base64.b64encode(image_bytes).decode("utf-8")
    prompt = (
        f"これは飲食店「{business_name}」のPOSレジ売上画面（日次売上）のスクリーンショットです。\n"
        "画像から以下の数値を読み取り、JSONのみで返してください（余分なテキスト不可）。\n"
        "読み取れない項目は null にしてください。金額は数値のみ（カンマや円記号は除く）。\n"
        "confidence は画面全体の読み取り自信度を0.0〜1.0で示してください。\n\n"
        "{\n"
        '  "date": "YYYY-MM-DD または null",\n'
        '  "sales": 売上合計(整数) または null,\n'
        '  "customers": 客数(整数) または null,\n'
        '  "avg_spend": 客単価(整数) または null,\n'
        '  "cash": 現金売上(整数) または null,\n'
        '  "card": カード売上(整数) または null,\n'
        '  "emoney": 電子決済(整数) または null,\n'
        '  "discount": 割引(整数) または null,\n'
        '  "refund": 返金(整数) または null,\n'
        '  "confidence": 0.0〜1.0,\n'
        '  "note": "読み取り上の補足（50文字以内）"\n'
        "}"
    )

    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{b64}",
                        "detail": "high",
                    }},
                ],
            }],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=400,
        )
        result = json.loads(resp.choices[0].message.content)
        # 客単価が無いが売上・客数があれば計算
        if not result.get("avg_spend") and result.get("sales") and result.get("customers"):
            try:
                result["avg_spend"] = int(result["sales"]) // int(result["customers"])
            except (ValueError, ZeroDivisionError, TypeError):
                pass
        return result
    except Exception as e:
        return {"_error": str(e), "confidence": 0.0}


# ── 判定ロジック ──────────────────────────────────────────

def _judge(parsed: dict, prev_sales: int) -> dict:
    """
    読み取り結果から判定ステータス・異常検知・LINE返信文タイプを決める。
    返り値: {status, anomaly, reply_type, reason}
    """
    conf  = float(parsed.get("confidence") or 0.0)
    sales = parsed.get("sales")

    if parsed.get("_error") or sales is None:
        return {"status": "再送依頼", "anomaly": "", "reply_type": "resend",
                "reason": "売上が読み取れません"}

    sales = _parse_int(sales)

    # 売上0円
    if sales == 0:
        return {"status": "オーナー確認", "anomaly": "売上0円（休業/入力ミス/未営業）",
                "reply_type": "confirm", "reason": "売上0円"}

    # 異常値（前日比 ±50%以上）
    anomaly = ""
    if prev_sales > 0:
        rate = abs(sales - prev_sales) / prev_sales
        if rate >= ANOMALY_RATE:
            direction = "急増" if sales > prev_sales else "急減"
            anomaly = f"前日比{direction} {rate*100:.0f}%（前日¥{prev_sales:,}→本日¥{sales:,}）"

    # 信頼度判定
    if conf >= CONF_AUTO:
        status     = "オーナー確認" if anomaly else "自動記録"
        reply_type = "confirm" if anomaly else "ok"
    elif conf >= CONF_CONFIRM:
        status     = "確認待ち"
        reply_type = "confirm"
    else:
        status     = "再送依頼"
        reply_type = "resend"

    return {"status": status, "anomaly": anomaly, "reply_type": reply_type,
            "reason": f"信頼度{conf:.0%}" + (f" / {anomaly}" if anomaly else "")}


# ── LINE返信文生成 ────────────────────────────────────────

def gen_reply_text(reply_type: str, biz_name: str, parsed: dict) -> str:
    sales = _parse_int(parsed.get("sales")) if parsed.get("sales") is not None else 0
    cust  = _parse_int(parsed.get("customers")) if parsed.get("customers") is not None else 0
    avg   = _parse_int(parsed.get("avg_spend")) if parsed.get("avg_spend") is not None else 0
    date  = parsed.get("date") or _date_jst()
    conf  = float(parsed.get("confidence") or 0.0)

    if reply_type == "ok":
        return (
            "【売上スクショ読み取り完了】\n"
            f"事業：{biz_name}\n"
            f"日付：{date}\n"
            f"売上：¥{sales:,}\n"
            f"客数：{cust}名\n"
            f"客単価：¥{avg:,}\n"
            f"AI信頼度：{conf:.0%}\n\n"
            "この内容で記録しました。\n"
            "修正がある場合は「修正 売上〇〇円 客数〇名」と返信してください。"
        )
    if reply_type == "confirm":
        return (
            "【売上確認が必要です】\n"
            "スクショから以下のように読み取りました。\n\n"
            f"売上：¥{sales:,}\n"
            f"客数：{cust}名\n"
            f"客単価：¥{avg:,}\n\n"
            "正しければ「OK」\n"
            "違う場合は「修正 売上〇〇円 客数〇名」と返信してください。"
        )
    # resend
    return (
        "【売上スクショを読み取れませんでした】\n"
        "売上合計がはっきり見える画面をもう一度送ってください。"
    )


# ── 公開API: セットアップ ─────────────────────────────────

def setup(spreadsheet_id: str, creds_path: str) -> dict:
    """3シートを作成"""
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    created = []
    for name, header in SCREENSHOT_SHEETS.items():
        _get_or_create_sheet(ss, name, header)
        created.append(name)
    return {
        "ok": True,
        "sheets_created": created,
        "screenshot_target_businesses": [SALES_BIZ_CONFIG[k]["name"] for k in SCREENSHOT_BIZ_KEYS],
        "excluded_consulting": [SALES_BIZ_CONFIG[k]["name"]
                                for k in SALES_BIZ_CONFIG if not SALES_BIZ_CONFIG[k]["screenshot_ok"]],
        "url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}",
    }


# ── 1件分の記録処理（共通コア） ───────────────────────────

def _record_one(ss, creds_path: str, biz_key: str, parsed: dict,
                image_url: str, sender: str, channel: str,
                dry_run: bool = True) -> dict:
    """1件の読み取り結果を SALES_SCREENSHOT_LOG / DAILY_SALES_CONFIRMATION に記録"""
    cfg      = SALES_BIZ_CONFIG.get(biz_key, {})
    biz_name = cfg.get("name", biz_key)
    now      = _now_jst()
    target_date = parsed.get("date") or _date_jst()

    # 前日売上を取得（異常検知用）
    prev_sales = _get_prev_sales(ss, biz_name, target_date)
    judge = _judge(parsed, prev_sales)

    # 重複チェック
    dup = _is_duplicate(ss, biz_name, target_date)
    if dup and judge["status"] in ("自動記録",):
        judge["status"] = "重複候補"
        judge["reason"] += " / 同日重複（自動上書きしない）"

    sales = _parse_int(parsed.get("sales")) if parsed.get("sales") is not None else 0
    cust  = _parse_int(parsed.get("customers")) if parsed.get("customers") is not None else 0
    avg   = _parse_int(parsed.get("avg_spend")) if parsed.get("avg_spend") is not None else 0
    conf  = float(parsed.get("confidence") or 0.0)

    # 反映ステータス
    if judge["status"] == "自動記録" and not dry_run:
        reflect = "POS反映済み"
        _reflect_to_pos(ss, biz_key, target_date, sales, cust, avg)
    elif judge["status"] == "自動記録":
        reflect = "DRY_RUN(未反映)"
    else:
        reflect = "保留"

    log_ws = _get_or_create_sheet(ss, "SALES_SCREENSHOT_LOG", SCREENSHOT_SHEETS["SALES_SCREENSHOT_LOG"])
    row = {
        "登録日時": now, "事業名": biz_name, "LINEチャンネル": channel,
        "送信者": sender, "対象日": target_date, "画像URL": image_url,
        "読み取り売上": sales, "読み取り客数": cust, "読み取り客単価": avg,
        "現金": _parse_int(parsed.get("cash")), "カード": _parse_int(parsed.get("card")),
        "電子決済": _parse_int(parsed.get("emoney")), "割引": _parse_int(parsed.get("discount")),
        "返金": _parse_int(parsed.get("refund")),
        "AI信頼度": f"{conf:.0%}", "判定ステータス": judge["status"],
        "確認ステータス": "確認待ち" if judge["reply_type"] == "confirm" else "—",
        "反映ステータス": reflect, "異常検知": judge["anomaly"],
        "エラー内容": parsed.get("_error", ""), "Obsidian Path": "",
    }
    header = SCREENSHOT_SHEETS["SALES_SCREENSHOT_LOG"]
    log_ws.append_row([row.get(h, "") for h in header], value_input_option="RAW")

    # 確認テーブル更新
    _update_confirmation(ss, biz_key, target_date, sales, cust, avg, prev_sales, judge["status"])

    reply = gen_reply_text(judge["reply_type"], biz_name, parsed)

    # エラーログ
    if judge["status"] == "再送依頼":
        _log_error(ss, biz_name, image_url, "読み取り失敗",
                   parsed.get("_error", "売上を読み取れず"))

    return {
        "biz": biz_name, "target_date": target_date,
        "sales": sales, "customers": cust, "avg_spend": avg,
        "confidence": conf, "status": judge["status"],
        "anomaly": judge["anomaly"], "reply_type": judge["reply_type"],
        "reply_text": reply, "reflect": reflect, "duplicate": dup,
    }


def _get_prev_sales(ss, biz_name: str, target_date: str) -> int:
    """DAILY_SALES_CONFIRMATION から前日売上を取得"""
    try:
        ws = ss.worksheet("DAILY_SALES_CONFIRMATION")
    except gspread.WorksheetNotFound:
        return 0
    try:
        td = datetime.strptime(target_date, "%Y-%m-%d")
        prev = (td - timedelta(days=1)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return 0
    for r in ws.get_all_records():
        if str(r.get("日付")) == prev and str(r.get("事業名")) == biz_name:
            return _parse_int(r.get("売上"))
    return 0


def _is_duplicate(ss, biz_name: str, target_date: str) -> bool:
    try:
        ws = ss.worksheet("SALES_SCREENSHOT_LOG")
    except gspread.WorksheetNotFound:
        return False
    for r in ws.get_all_records():
        if (str(r.get("事業名")) == biz_name and str(r.get("対象日")) == target_date
                and str(r.get("判定ステータス")) in ("自動記録", "確認待ち", "重複候補")):
            return True
    return False


def _update_confirmation(ss, biz_key: str, target_date: str, sales: int,
                         cust: int, avg: int, prev_sales: int, status: str):
    cfg = SALES_BIZ_CONFIG.get(biz_key, {})
    biz_name = cfg.get("name", biz_key)
    daily_target = cfg.get("monthly_target", 0) // 30 if cfg.get("monthly_target") else 0
    ws = _get_or_create_sheet(ss, "DAILY_SALES_CONFIRMATION",
                              SCREENSHOT_SHEETS["DAILY_SALES_CONFIRMATION"])
    prev_ratio = f"{((sales - prev_sales) / prev_sales * 100):+.0f}%" if prev_sales > 0 else "—"
    achieve = f"{(sales / daily_target * 100):.0f}%" if daily_target > 0 else "—"
    next_action = {
        "自動記録": "なし", "確認待ち": "スタッフにOK/修正を確認",
        "オーナー確認": "オーナーに異常値を報告", "再送依頼": "スクショ再送依頼",
        "重複候補": "重複を手動確認",
    }.get(status, "確認")

    # 既存行があれば更新、なければ追加
    records = ws.get_all_records()
    header  = SCREENSHOT_SHEETS["DAILY_SALES_CONFIRMATION"]
    row = {
        "日付": target_date, "事業名": biz_name, "売上": sales, "客数": cust,
        "客単価": avg, "前日比": prev_ratio, "目標日販": daily_target,
        "達成率": achieve, "報告状況": "報告済み",
        "確認状況": "確認待ち" if status in ("確認待ち", "オーナー確認") else "—",
        "担当者": "", "次アクション": next_action,
    }
    values = [row.get(h, "") for h in header]
    last_col = chr(64 + len(header))  # 12列 → "L"
    for i, r in enumerate(records, start=2):
        if str(r.get("日付")) == target_date and str(r.get("事業名")) == biz_name:
            # 行全体を1回のレンジ更新（書込API節約）
            ws.update(values=[values], range_name=f"A{i}:{last_col}{i}",
                      value_input_option="RAW")
            return
    ws.append_row(values, value_input_option="RAW")


def _reflect_to_pos(ss, biz_key: str, target_date: str, sales: int, cust: int, avg: int):
    """POS_日次売上 へ仮反映（重複日付はスキップ）。列: A=月,B=日付,C=売上,D=客数,E=客単価"""
    try:
        ws = ss.worksheet("POS_日次売上")
    except gspread.WorksheetNotFound:
        try:
            ws = ss.worksheet("02_日次売上")
        except gspread.WorksheetNotFound:
            return
    existing = ws.col_values(2)  # B列=日付
    ymd = target_date.replace("-", "/")
    if ymd in existing or target_date in existing:
        return
    month = target_date[:7].replace("-", "/")
    ws.append_row([month, target_date, sales, cust, avg, "", "", "スクショ仮反映"],
                  value_input_option="USER_ENTERED")


def _log_error(ss, biz_name: str, image_url: str, err_type: str, err_msg: str):
    ws = _get_or_create_sheet(ss, "SALES_SCREENSHOT_ERROR_LOG",
                              SCREENSHOT_SHEETS["SALES_SCREENSHOT_ERROR_LOG"])
    ws.append_row([_now_jst(), biz_name, image_url, err_type, err_msg, "再送依頼予定", "未対応"],
                  value_input_option="RAW")


# ── 公開API: Webhook ──────────────────────────────────────

def handle_webhook(spreadsheet_id: str, creds_path: str, body_json: dict,
                   destination: str = "", dry_run: bool = True,
                   biz_key_override: str = "") -> dict:
    """
    LINE Webhook の image メッセージを処理。
    事業特定の優先順位:
      1. biz_key_override（呼び出し側が事業を特定済みの場合。各事業別サービス等）
      2. destination → LINE_<BIZ>_DESTINATION 環境変数との一致
    画像取得→Vision解析→記録→返信。dry_run=True のとき LINE返信・POS反映はスキップ。
    """
    biz_key = biz_key_override if biz_key_override in SALES_BIZ_CONFIG else ""
    # destination から事業特定（override が無い場合）
    if not biz_key:
        for k, cfg in SALES_BIZ_CONFIG.items():
            if cfg.get("dest_env") and os.getenv(cfg["dest_env"], "") == destination and destination:
                biz_key = k
                break

    events  = body_json.get("events", [])
    results = []
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)

    for ev in events:
        if ev.get("type") != "message":
            continue
        msg = ev.get("message", {})
        if msg.get("type") != "image":
            continue
        message_id  = msg.get("id", "")
        reply_token = ev.get("replyToken", "")
        sender      = ev.get("source", {}).get("userId", "")[:8] + "****" if ev.get("source", {}).get("userId") else "unknown"

        cfg   = SALES_BIZ_CONFIG.get(biz_key, {})
        token = os.getenv(cfg.get("token_env", ""), "")
        if not biz_key or not token:
            results.append({"ok": False, "error": "事業特定/トークン未設定", "biz_key": biz_key})
            continue

        try:
            img = _fetch_line_image(message_id, token)
        except Exception as e:
            _log_error(ss, cfg.get("name", biz_key), "", "画像取得失敗", str(e))
            results.append({"ok": False, "error": f"画像取得失敗: {e}"})
            continue

        img_path = f"{GCS_IMG_PREFIX}/{biz_key}/{_date_jst()}_{message_id}.jpg"
        img_url  = _upload_image_gcs(creds_path, img_path, img)

        # 画像種別を自動判定（売上スクショ vs LINE反応スクショ）
        kind = "sales"
        try:
            from core.sns_pdca import classify_screenshot
            kind, _ = classify_screenshot(img, creds_path)
        except Exception:
            kind = "sales"

        # ── LINE公式の友だち分析スクショ → LINE_SCREENSHOT_LOG ──
        if kind == "line_insight":
            try:
                from core.sns_pdca import process_line_screenshot
                sns_ss = os.getenv("GOOGLE_SPREADSHEET_ID", "") or spreadsheet_id
                sns_img_path = f"sns-screenshots/{biz_key}/{_date_jst()}_{message_id}.jpg"
                sns_url = _upload_image_gcs(creds_path, sns_img_path, img)
                sres = process_line_screenshot(
                    sns_ss, creds_path, img, cfg.get("name", biz_key), image_url=sns_url)
                if not dry_run and sres.get("reply_text"):
                    _send_line_reply(reply_token, sres["reply_text"], token)
                results.append({"ok": True, "kind": "line_insight", **{k: v for k, v in sres.items() if k != "parsed"}})
            except Exception as e:
                results.append({"ok": False, "kind": "line_insight", "error": str(e)})
            continue

        # ── SNS投稿インサイトスクショ → SNS_RESULT（投稿本文不要）──
        if kind == "sns_insight":
            try:
                from core.sns_pdca import process_sns_insight_screenshot
                sns_ss = os.getenv("GOOGLE_SPREADSHEET_ID", "") or spreadsheet_id
                sns_img_path = f"sns-insight/{biz_key}/{_date_jst()}_{message_id}.jpg"
                sns_url = _upload_image_gcs(creds_path, sns_img_path, img)
                sres = process_sns_insight_screenshot(
                    sns_ss, creds_path, img, cfg.get("name", biz_key),
                    sender=sender, image_url=sns_url)
                if not dry_run and sres.get("reply_text"):
                    _send_line_reply(reply_token, sres["reply_text"], token)
                results.append({"ok": True, "kind": "sns_insight",
                                **{k: v for k, v in sres.items() if k not in ("parsed", "reactions")}})
            except Exception as e:
                results.append({"ok": False, "kind": "sns_insight", "error": str(e)})
            continue

        # ── 不明スクショ → 当日の未完了MEOタスクがあれば完了証跡として記録 ──
        if kind == "unknown":
            try:
                from core.growth_engines import has_open_meo_task, meo_record_completion_screenshot
                meo_ss = os.getenv("GOOGLE_SPREADSHEET_ID", "") or spreadsheet_id
                if has_open_meo_task(meo_ss, creds_path, biz_key):
                    res = meo_record_completion_screenshot(meo_ss, creds_path, biz_key, img_url)
                    if res.get("ok"):
                        if not dry_run and res.get("reply"):
                            _send_line_reply(reply_token, res["reply"], token)
                        results.append({"ok": True, "kind": "meo_completion", **res})
                        continue
            except Exception as e:
                results.append({"ok": False, "kind": "meo_completion", "error": str(e)})

        # ── 売上スクショ → 既存フロー ──
        parsed = analyze_image(img, cfg.get("name", biz_key), creds_path)
        rec = _record_one(ss, creds_path, biz_key, parsed, img_url,
                          sender, cfg.get("name", biz_key), dry_run=dry_run)

        if not dry_run and rec["reply_type"]:
            _send_line_reply(reply_token, rec["reply_text"], token)
            rec["line_sent"] = True
        else:
            rec["line_sent"] = False
        results.append({"ok": True, "kind": "sales", **rec})

    return {"ok": True, "processed": len(results), "results": results, "dry_run": dry_run}


# ── 公開API: 未処理画像の再解析 ───────────────────────────

def process(spreadsheet_id: str, creds_path: str, dry_run: bool = True) -> dict:
    """
    SALES_SCREENSHOT_LOG の判定ステータスが空 or 「再送依頼」以外で
    反映ステータスが「保留」の行は確認用に再集計（再OCRはしない簡易処理）。
    主に確認テーブルの整合を取る。
    """
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    try:
        ws = ss.worksheet("SALES_SCREENSHOT_LOG")
    except gspread.WorksheetNotFound:
        return {"ok": False, "error": "SALES_SCREENSHOT_LOG 未作成"}

    records = ws.get_all_records()
    reprocessed = 0
    for r in records:
        if r.get("判定ステータス") == "自動記録" and r.get("反映ステータス") == "DRY_RUN(未反映)" and not dry_run:
            biz_key = _biz_key_from_name(str(r.get("事業名")))
            _reflect_to_pos(ss, biz_key, str(r.get("対象日")),
                            _parse_int(r.get("読み取り売上")),
                            _parse_int(r.get("読み取り客数")),
                            _parse_int(r.get("読み取り客単価")))
            reprocessed += 1

    return {"ok": True, "reprocessed": reprocessed, "total_rows": len(records), "dry_run": dry_run}


# ── 公開API: テスト ───────────────────────────────────────

_TEST_PARSED = [
    # 正常・高信頼度（自動記録）
    {"biz_key": "tachinomiya", "parsed": {"date": _date_jst(), "sales": 142000, "customers": 38,
        "avg_spend": 3736, "cash": 80000, "card": 50000, "emoney": 12000,
        "discount": 0, "refund": 0, "confidence": 0.95, "note": "明瞭"}},
    # 中信頼度（確認待ち）
    {"biz_key": "catering", "parsed": {"date": _date_jst(), "sales": 38000, "customers": 1,
        "avg_spend": 38000, "cash": 0, "card": 38000, "emoney": 0,
        "discount": 0, "refund": 0, "confidence": 0.78, "note": "一部不鮮明"}},
    # 低信頼度（再送依頼）
    {"biz_key": "beauty", "parsed": {"date": _date_jst(), "sales": None, "customers": None,
        "avg_spend": None, "confidence": 0.4, "note": "ブレあり読み取り困難"}},
    # 売上0（オーナー確認）
    {"biz_key": "ryukyu_hinabe", "parsed": {"date": _date_jst(), "sales": 0, "customers": 0,
        "avg_spend": 0, "confidence": 0.92, "note": "売上0表示"}},
    # 高信頼度・異常値（前日比急増→オーナー確認）※前日データを先に入れる
    {"biz_key": "tachinomiya", "parsed": {"date": _date_jst(), "sales": 142000, "customers": 38,
        "avg_spend": 3736, "confidence": 0.93, "note": "重複テスト"}},
]


def run_test(spreadsheet_id: str, creds_path: str) -> dict:
    """疑似読み取りデータ5件で判定・記録・返信文生成のフルフローをDRY_RUNで確認"""
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    # シート確保
    for name, header in SCREENSHOT_SHEETS.items():
        _get_or_create_sheet(ss, name, header)

    results = []
    for i, t in enumerate(_TEST_PARSED, start=1):
        rec = _record_one(
            ss, creds_path, t["biz_key"], t["parsed"],
            image_url=f"https://storage.googleapis.com/{GCS_BUCKET}/{GCS_IMG_PREFIX}/test/test_{i}.jpg",
            sender="TEST****", channel=SALES_BIZ_CONFIG[t["biz_key"]]["name"],
            dry_run=True,
        )
        results.append({
            "事業": rec["biz"], "売上": rec["sales"], "信頼度": f"{rec['confidence']:.0%}",
            "判定": rec["status"], "異常": rec["anomaly"] or "—",
            "返信タイプ": rec["reply_type"], "重複": rec["duplicate"],
        })

    status_count = {}
    for r in results:
        status_count[r["判定"]] = status_count.get(r["判定"], 0) + 1

    return {
        "ok": True,
        "test_count": len(results),
        "status_breakdown": status_count,
        "results": results,
        "sample_reply": gen_reply_text("ok", "TACHINOMIYA", _TEST_PARSED[0]["parsed"]),
        "dry_run": True,
        "note": "OpenAI Vision呼び出しはスキップ（疑似読み取りデータ使用）。LINE送信なし。",
    }


# ── 公開API: ステータス ───────────────────────────────────

def get_status(spreadsheet_id: str, creds_path: str, date: str = "") -> dict:
    """指定日（省略時は本日）の事業別報告状況を返す"""
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    target = date or _date_jst()
    try:
        ws = ss.worksheet("DAILY_SALES_CONFIRMATION")
    except gspread.WorksheetNotFound:
        return {"ok": True, "date": target, "reported": [], "note": "シート未作成"}

    records  = ws.get_all_records()
    reported = [r for r in records if str(r.get("日付")) == target]

    total_sales = sum(_parse_int(r.get("売上")) for r in reported)
    return {
        "ok": True,
        "date": target,
        "reported_count": len(reported),
        "screenshot_target_total": len(SCREENSHOT_BIZ_KEYS),
        "total_sales": total_sales,
        "details": [{
            "事業": r.get("事業名"), "売上": r.get("売上"), "客数": r.get("客数"),
            "達成率": r.get("達成率"), "確認状況": r.get("確認状況"),
        } for r in reported],
    }


# ── 公開API: 未報告検知 ───────────────────────────────────

def missing_report(spreadsheet_id: str, creds_path: str, date: str = "") -> dict:
    """本日（指定日）まだ売上報告のない事業を抽出（スクショ対象事業のみ）"""
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    target = date or _date_jst()
    try:
        ws = ss.worksheet("DAILY_SALES_CONFIRMATION")
        reported_names = {str(r.get("事業名")) for r in ws.get_all_records()
                          if str(r.get("日付")) == target}
    except gspread.WorksheetNotFound:
        reported_names = set()

    missing = []
    for k in SCREENSHOT_BIZ_KEYS:
        name = SALES_BIZ_CONFIG[k]["name"]
        if name not in reported_names:
            missing.append({"biz_key": k, "事業名": name})

    # Daily Action 連携用のタスク文を生成
    action_tasks = []
    for m in missing:
        action_tasks.append({
            "biz_key": m["biz_key"],
            "task": f"本日の売上スクショをLINE公式へ送信してください（{m['事業名']}）",
            "priority": "S",
        })

    return {
        "ok": True,
        "date": target,
        "missing_count": len(missing),
        "missing_businesses": missing,
        "daily_action_tasks": action_tasks,
    }


# ── 公開API: Knowledge OS 出力 ────────────────────────────

# ── 修正コマンド処理（LINEテキスト返信） ─────────────────

def parse_sales_correction(text: str) -> dict:
    """
    「修正 売上12000円 客数5名」「OK」などのテキストを解析。
    返り値: {"type": "ok"|"correct"|"none", "sales": int|None, "customers": int|None}
    """
    import re
    t = text.strip()

    # 修正コマンド
    if "修正" in t or re.search(r"売上\s*[\d,]+", t):
        sales = cust = None
        m = re.search(r"売上\s*([\d,]+)", t)
        if m:
            sales = int(m.group(1).replace(",", ""))
        m = re.search(r"客数\s*([\d,]+)", t)
        if m:
            cust = int(m.group(1).replace(",", ""))
        if sales is not None or cust is not None:
            return {"type": "correct", "sales": sales, "customers": cust}

    # OK確認
    OK_WORDS = ["ok", "おっけー", "オッケー", "了解", "りょうかい", "確認しました",
                "これでok", "はい", "正しい", "合ってます", "あってます", "👍", "⭕", "◯", "○"]
    if t.lower() in [w.lower() for w in OK_WORDS] or t.lower().startswith("ok"):
        return {"type": "ok", "sales": None, "customers": None}

    return {"type": "none", "sales": None, "customers": None}


def _find_pending_row(ws, biz_name: str):
    """SALES_SCREENSHOT_LOG から確認待ちの最新行を返す (row_idx, record) or (None, None)"""
    all_vals = ws.get_all_values()
    if len(all_vals) < 2:
        return None, None
    header = all_vals[0]
    def idx(h):
        return header.index(h) if h in header else None
    i_biz   = idx("事業名")
    i_conf  = idx("確認ステータス")
    # 下（新しい行）から探す
    for r in range(len(all_vals) - 1, 0, -1):
        row = all_vals[r]
        biz = row[i_biz].strip() if i_biz is not None and i_biz < len(row) else ""
        cs  = row[i_conf].strip() if i_conf is not None and i_conf < len(row) else ""
        if biz == biz_name and cs == "確認待ち":
            rec = {h: (row[k] if k < len(row) else "") for k, h in enumerate(header)}
            return r + 1, rec  # 1-indexed sheet row
    return None, None


def maybe_handle_text_reply(reply_text: str, biz_key: str, creds_path: str,
                            ss_id: str = "", reply_token: str = "",
                            dry_run: bool = True) -> dict:
    """
    LINEテキスト返信が売上スクショの「OK」/「修正」コマンドか判定し、
    該当する場合のみ処理して {"handled": True, ...} を返す。
    売上スクショと無関係なら {"handled": False} を返す（Daily Actionの完了処理へ委譲）。
    """
    cfg = SALES_BIZ_CONFIG.get(biz_key, {})
    if not cfg or not cfg.get("screenshot_ok"):
        return {"handled": False}

    cmd = parse_sales_correction(reply_text)
    if cmd["type"] == "none":
        return {"handled": False}

    biz_name = cfg["name"]
    gc = _gc(creds_path)
    ss = gc.open_by_key(ss_id)
    try:
        log_ws = ss.worksheet("SALES_SCREENSHOT_LOG")
    except gspread.WorksheetNotFound:
        return {"handled": False}

    row_idx, rec = _find_pending_row(log_ws, biz_name)
    if not row_idx:
        # 確認待ちが無ければ売上コマンドとして扱わない（タスク完了処理へ委譲）
        return {"handled": False}

    header = SCREENSHOT_SHEETS["SALES_SCREENSHOT_LOG"]
    def col_letter(h):
        return chr(65 + header.index(h)) if h in header else None

    target_date = str(rec.get("対象日") or _date_jst())
    sales = _parse_int(rec.get("読み取り売上"))
    cust  = _parse_int(rec.get("読み取り客数"))
    avg   = _parse_int(rec.get("読み取り客単価"))

    if cmd["type"] == "correct":
        if cmd["sales"] is not None:
            sales = cmd["sales"]
        if cmd["customers"] is not None:
            cust = cmd["customers"]
        avg = (sales // cust) if cust > 0 else avg
        updates = [
            (col_letter("読み取り売上"), sales),
            (col_letter("読み取り客数"), cust),
            (col_letter("読み取り客単価"), avg),
            (col_letter("確認ステータス"), "確認済み(修正)"),
            (col_letter("判定ステータス"), "確定"),
            (col_letter("反映ステータス"), "POS反映済み" if not dry_run else "確定(DRY_RUN未反映)"),
        ]
        result_kind = "correct"
        reply_msg = (
            "【修正を記録しました】\n"
            f"事業：{biz_name}\n日付：{target_date}\n"
            f"売上：¥{sales:,}\n客数：{cust}名\n客単価：¥{avg:,}\n\n"
            "ご対応ありがとうございます！"
        )
    else:  # ok
        updates = [
            (col_letter("確認ステータス"), "確認済み"),
            (col_letter("判定ステータス"), "確定"),
            (col_letter("反映ステータス"), "POS反映済み" if not dry_run else "確定(DRY_RUN未反映)"),
        ]
        result_kind = "ok"
        reply_msg = (
            "【確認ありがとうございます】\n"
            f"{biz_name} {target_date} の売上 ¥{sales:,}（{cust}名）を確定しました。"
        )

    batch = [{"range": f"{letter}{row_idx}", "values": [[value]]}
             for letter, value in updates if letter]
    if batch:
        log_ws.batch_update(batch)

    # 確認テーブル更新
    biz_key2 = _biz_key_from_name(biz_name)
    prev_sales = _get_prev_sales(ss, biz_name, target_date)
    _update_confirmation(ss, biz_key2, target_date, sales, cust, avg, prev_sales, "確認済み")

    # POS反映
    if not dry_run:
        _reflect_to_pos(ss, biz_key2, target_date, sales, cust, avg)

    # LINE返信
    line_sent = False
    if not dry_run and reply_token:
        token = os.getenv(cfg.get("token_env", ""), "")
        line_sent = _send_line_reply(reply_token, reply_msg, token)

    return {
        "handled": True, "kind": result_kind, "biz": biz_name,
        "target_date": target_date, "sales": sales, "customers": cust,
        "avg_spend": avg, "reply_text": reply_msg, "line_sent": line_sent,
        "dry_run": dry_run,
    }


def export_knowledge(spreadsheet_id: str, creds_path: str, date: str = "") -> dict:
    """指定日の日次売上サマリーをObsidian用Markdownとして保存"""
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    target = date or _date_jst()
    try:
        ws = ss.worksheet("DAILY_SALES_CONFIRMATION")
        reported = [r for r in ws.get_all_records() if str(r.get("日付")) == target]
    except gspread.WorksheetNotFound:
        reported = []

    total_sales = sum(_parse_int(r.get("売上")) for r in reported)
    miss = missing_report(spreadsheet_id, creds_path, target)

    lines = [
        "| 事業 | 売上 | 客数 | 客単価 | 達成率 | 前日比 | 確認状況 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in reported:
        lines.append(
            f"| {r.get('事業名')} | ¥{_parse_int(r.get('売上')):,} | {r.get('客数')}名 "
            f"| ¥{_parse_int(r.get('客単価')):,} | {r.get('達成率')} | {r.get('前日比')} | {r.get('確認状況')} |"
        )
    table = "\n".join(lines)

    missing_md = "\n".join(f"- {m['事業名']}" for m in miss["missing_businesses"]) or "- なし（全事業報告済み）"

    md = (
        f"---\n"
        f"title: 日次売上スクショ集計 {target}\n"
        f"business: YU HOLDINGS\n"
        f"category: daily_sales\n"
        f"date: {target}\n"
        f"source: daily_sales_screenshot_capture_os\n"
        f"status: active\n"
        f"tags: [daily_sales, screenshot, pos]\n"
        f"---\n\n"
        f"# 日次売上スクショ集計 — {target}\n\n"
        f"## サマリー\n"
        f"- 報告事業数: {len(reported)} / {len(SCREENSHOT_BIZ_KEYS)}（スクショ対象）\n"
        f"- 売上合計: ¥{total_sales:,}\n\n"
        f"## 事業別売上\n\n{table}\n\n"
        f"## 未報告事業\n{missing_md}\n"
    )

    path = f"{GCS_PREFIX}/05_Reports/daily_sales_screenshot_{target}.md"
    url  = _upload_md_gcs(creds_path, path, md)

    return {"ok": True, "path": path, "url": url, "reported": len(reported),
            "total_sales": total_sales}
