"""
SNS投稿 PDCA システム（Phase 1: 記録基盤 / Phase 2: ルールベース分析）
----------------------------------------------------------------
目的: Google投稿/Threads投稿のストック・結果、LINE公式反応(スクショ)、分析、
      未投稿の改善を一元管理。最終目的は予約・来店・問い合わせ・売上の最大化。

方針:
  ・Google/Threadsは手動投稿。本システムは管理・分析・改善に専念。
  ・画像生成は対象外（テキストのみ）。
  ・LINE反応スクショは Google Cloud Vision でOCR（無料・OpenAI不使用）。
  ・既存シートは読むだけ（取込前にバックアップ）。新規シートのみ書込。
  ・元投稿は上書き禁止。改善版は SNS_REWRITE_STOCK へ（Phase3）。
  ・投稿はTYPE-A認知/B興味/C集客で分類。評価は売上貢献度で重み付け。
"""

import os
import json
from datetime import datetime, timezone, timedelta

import gspread
from google.oauth2.service_account import Credentials
from google.cloud import storage as gcs_storage

JST = timezone(timedelta(hours=9))
GCS_BUCKET  = "tree-beauty-blog-images"
GCS_PREFIX  = "knowledge-os"
GCS_PROJECT = "tree-beauty-ai-499303"

# ── 取込元: 各事業の投稿ストック（既存・読むだけ） ─────────
# media は Google投稿 / Threads投稿 のみ対象（Instagram/HPBは対象外）
SOURCE_STOCKS = {
    "Tree Beauty": {"ss": "1I6wRRDa-b440DBxZ3TbFbfMxEXZecowzOsxTAYSxyBE", "sheets": [
        {"name": "08Google投稿", "platform": "Google投稿", "date": "日付", "title": "タイトル", "body": "本文", "status": "投稿状況", "hdr": 1},
        {"name": "10Threads投稿", "platform": "Threads投稿", "date": "日付", "title": "タイトル", "body": "本文", "status": "投稿状況", "hdr": 1},
    ]},
    "TREE's Catering": {"ss": "1tNE35iQAVk6eTGEu68WDrRpv9FDIeVT_eK66iRi78Zs", "sheets": [
        {"name": "08_Google投稿", "platform": "Google投稿", "date": "投稿日", "title": "タイトル", "body": "本文（500文字以内）", "status": "投稿状況", "hdr": 2},
        {"name": "10_Threads", "platform": "Threads投稿", "date": "投稿日", "title": "本文（500文字以内）", "body": "本文（500文字以内）", "status": "投稿状況", "hdr": 2},
    ]},
    "TACHINOMIYA": {"ss": "1K4KkAhFwVkQqqvzeqa25-1sR26ltBfP9gY9h-N4gXcc", "sheets": [
        {"name": "08_Google投稿", "platform": "Google投稿", "date": "投稿日", "title": "タイトル", "body": "本文", "status": "投稿状況", "hdr": 2},
        {"name": "10_Threads", "platform": "Threads投稿", "date": "投稿日", "title": "本文", "body": "本文", "status": "投稿状況", "hdr": 2},
    ]},
    "琉球火鍋": {"ss": "1jwFmQtrertjIc6yYFJEyDptLdSUgD5xLdHDAxQhIQzw", "sheets": [
        {"name": "08_Google投稿", "platform": "Google投稿", "date": "投稿日", "title": "タイトル", "body": "本文", "status": "投稿状況", "hdr": 2},
        {"name": "10_Threads投稿", "platform": "Threads投稿", "date": "投稿日", "title": "本文", "body": "本文", "status": "投稿状況", "hdr": 2},
    ]},
    # パスタパスタ / Z1 は既存ストック未整備 → 手動入力で対応（取込元なし）
}

# ── 新規シート定義（統合SSに作成） ────────────────────────
SNS_SHEETS = {
    "LINE_SCREENSHOT_LOG": [
        "screenshot_id", "business_name", "upload_date", "period_start", "period_end",
        "screenshot_file_url", "extracted_text", "line_friend_add_count",
        "line_message_count", "reservation_count", "inquiry_count",
        "coupon_click_count", "ai_confidence_score", "human_check_status", "memo",
    ],
    "SNS_POST_STOCK": [
        "post_id", "business_name", "platform", "post_no", "original_text",
        "current_text", "post_type", "target_stage", "customer_pain", "hook_text",
        "cta", "status", "scheduled_date", "posted_date", "posted_url",
        "rewrite_version", "memo",
    ],
    "SNS_RESULT": [
        "post_id", "business_name", "platform", "posted_date", "impressions",
        "likes", "comments", "shares", "saves", "profile_access", "line_add",
        "dm_count", "reservation_count", "inquiry_count", "visit_count",
        "sales_amount", "related_screenshot_id", "manual_note",
    ],
    "SNS_AI_ANALYSIS": [
        "analysis_id", "analysis_date", "business_name", "platform",
        "period_start", "period_end", "top_post_ids", "weak_post_ids",
        "winning_hooks", "winning_customer_pains", "winning_cta",
        "line_reaction_summary", "bad_patterns", "next_improvement_policy", "ai_summary",
    ],
    "SNS_REWRITE_STOCK": [
        "rewrite_id", "original_post_id", "business_name", "platform",
        "old_text", "rewritten_text", "rewrite_reason", "improvement_point",
        "expected_effect", "status", "created_at",
    ],
    "SNS_DASHBOARD": [
        "日付", "事業名", "媒体別投稿数", "投稿済み数", "未投稿数",
        "LINE追加数", "問い合わせ数", "予約数", "反応上位投稿",
        "売上につながった投稿", "改善された投稿数", "次に増やすテーマ",
        "次に減らすテーマ", "今週の最重要アクション", "最終更新",
    ],
    # ── PHASE1: スクショOCR記録 ──
    "SNS_SCREENSHOT_LOG": [
        "受信日時", "事業名", "送信元LINE", "画像URL", "OCR結果", "媒体判定",
        "数値抽出結果", "投稿マッチ候補", "信頼度", "処理結果", "返信文", "エラー内容",
    ],
    "SNS_MATCH_CANDIDATES": [
        "登録日時", "事業名", "媒体", "投稿日", "投稿本文候補",
        "投稿タイトル", "シート元", "マッチ対象", "使用済み", "メモ",
    ],
    # ── PHASE2: 勝ち投稿再利用 ──
    "SNS_WINNING_POSTS": [
        "検出日時", "事業名", "媒体", "投稿日", "投稿本文", "冒頭フック", "勝ち理由",
        "売上", "来店", "予約", "問い合わせ", "インプ", "プロフ", "保存", "シェア",
        "再利用優先度", "再利用先", "再利用文", "Daily Action連携", "メモ",
    ],
    "SNS_REUSE_ACTIONS": [
        "作成日時", "事業名", "元媒体", "再利用先", "再利用内容",
        "担当", "期限", "対応状況", "結果", "メモ",
    ],
}

# 投稿TYPE推定キーワード（ルールベース）
_TYPE_KEYWORDS = {
    "C": ["予約", "ご予約", "問い合わせ", "お問い合わせ", "限定", "今だけ", "クーポン",
          "割引", "本日", "空き", "席", "来店", "ご来店", "注文", "受付", "キャンペーン"],
    "B": ["プロフィール", "LINE", "フォロー", "DM", "登録", "友だち", "リンク", "詳細は"],
    "A": [],  # それ以外は認知
}

JST_TODAY = lambda: datetime.now(JST).strftime("%Y-%m-%d")


# ── ユーティリティ ────────────────────────────────────────

def _now(): return datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
def _date(): return datetime.now(JST).strftime("%Y-%m-%d")


def _gc(creds_path):
    creds = Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/spreadsheets",
                            "https://www.googleapis.com/auth/drive"])
    return gspread.authorize(creds)


def _gcs(creds_path):
    creds = Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/devstorage.read_write"])
    return gcs_storage.Client(project=GCS_PROJECT, credentials=creds)


def _upload_gcs(creds_path, path, content, ctype="text/markdown"):
    blob = _gcs(creds_path).bucket(GCS_BUCKET).blob(path)
    blob.upload_from_string(content.encode("utf-8") if isinstance(content, str) else content,
                            content_type=ctype)
    return f"https://storage.googleapis.com/{GCS_BUCKET}/{path}"


def _get_or_create_sheet(ss, title, header):
    try:
        return ss.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=title, rows=3000, cols=max(len(header), 12))
        ws.update(values=[header], range_name="A1")
        ws.format("A1:Z1", {
            "backgroundColor": {"red": 0.15, "green": 0.05, "blue": 0.20},
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}}})
        return ws


def _pint(v):
    if v is None: return 0
    s = str(v).replace(",", "").replace("¥", "").replace("円", "").replace("%", "").strip()
    if s in ("", "-", "—"): return 0
    try: return int(float(s))
    except (ValueError, TypeError): return 0


_BIZ_NAME_KW = [
    ("TACHINOMIYA",    ["tachinomiya", "タチノミヤ", "立呑", "立飲", "国際通り"]),
    ("Tree Beauty",    ["tree beauty", "beauty", "ビューティー", "美容", "脱毛"]),
    ("TREE's Catering", ["catering", "ケータリング", "ケータ"]),
    ("琉球火鍋",        ["琉球火鍋", "火鍋", "hinabe"]),
    ("パスタパスタ",    ["パスタパスタ", "パスタ", "pasta"]),
    ("Z1",             ["z1", "ゼットワン"]),
]


def _detect_biz_name(text: str) -> str:
    low = str(text).lower()
    for name, kws in _BIZ_NAME_KW:
        if any(k.lower() in low for k in kws):
            return name
    return ""


def _infer_type(text: str) -> str:
    """本文からTYPE-A/B/Cを推定（ルールベース・後で人手修正可）"""
    t = str(text)
    if any(k in t for k in _TYPE_KEYWORDS["C"]):
        return "C"
    if any(k in t for k in _TYPE_KEYWORDS["B"]):
        return "B"
    return "A"


# ── 1. セットアップ ────────────────────────────────────────

def setup(spreadsheet_id, creds_path):
    """6シートを統合SSに作成（既存に影響なし）"""
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    created = []
    for name, header in SNS_SHEETS.items():
        _get_or_create_sheet(ss, name, header)
        created.append(name)
    return {"ok": True, "sheets_created": created,
            "url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"}


# ── 2. 既存投稿ストックの取込（バックアップ→取込・読むだけ） ─

def import_stock(spreadsheet_id, creds_path, dry_run=False, limit_per_sheet=0):
    """
    各事業のGoogle投稿/Threads投稿シートを読み取り、SNS_POST_STOCKへ取込。
    取込前にスナップショットをGCSバックアップ。既存シートには一切書き込まない。
    dry_run=True なら件数カウントのみ。
    """
    gc = _gc(creds_path)
    dest_ss = gc.open_by_key(spreadsheet_id)
    backup_lines = [f"# SNS投稿ストック バックアップ {_now()}\n"]
    imported_rows = []
    counts = {}

    for biz, cfg in SOURCE_STOCKS.items():
        try:
            src = gc.open_by_key(cfg["ss"])
        except Exception as e:
            counts[biz] = f"アクセス不可: {str(e)[:40]}"
            continue
        for sh in cfg["sheets"]:
            try:
                ws = src.worksheet(sh["name"])
            except gspread.WorksheetNotFound:
                continue
            all_vals = ws.get_all_values()
            hdr_idx = sh["hdr"] - 1
            if len(all_vals) <= sh["hdr"]:
                counts[f"{biz}/{sh['platform']}"] = 0
                continue
            header = all_vals[hdr_idx]
            def col(name):
                return header.index(name) if name in header else None
            ci_date, ci_title, ci_body, ci_status = (
                col(sh["date"]), col(sh["title"]), col(sh["body"]), col(sh["status"]))
            rows = all_vals[sh["hdr"]:]
            if limit_per_sheet:
                rows = rows[:limit_per_sheet]
            n = 0
            for i, r in enumerate(rows, start=1):
                def cell(ci):
                    return r[ci].strip() if ci is not None and ci < len(r) else ""
                body = cell(ci_body)
                if not body:
                    continue
                date = cell(ci_date); status_raw = cell(ci_status)
                status = "投稿済み" if ("済" in status_raw or "完了" in status_raw) else "未投稿"
                post_id = f"{biz[:4]}_{sh['platform'][:3]}_{i:04d}"
                row = {
                    "post_id": post_id, "business_name": biz, "platform": sh["platform"],
                    "post_no": i, "original_text": body, "current_text": body,
                    "post_type": _infer_type(cell(ci_title) + " " + body),
                    "target_stage": "", "customer_pain": "", "hook_text": cell(ci_title)[:50],
                    "cta": "", "status": status, "scheduled_date": date,
                    "posted_date": date if status == "投稿済み" else "",
                    "posted_url": "", "rewrite_version": 0, "memo": "既存ストックより取込",
                }
                imported_rows.append(row)
                backup_lines.append(f"- [{biz}/{sh['platform']}] {date} {status} | {body[:60]}")
                n += 1
            counts[f"{biz}/{sh['platform']}"] = n

    result = {"ok": True, "counts": counts, "total": len(imported_rows), "dry_run": dry_run}

    if dry_run:
        return result

    # バックアップをGCSへ
    bkpath = f"{GCS_PREFIX}/07_Marketing/sns_post_stock_backup_{_date()}.md"
    _upload_gcs(creds_path, bkpath, "\n".join(backup_lines))
    result["backup"] = bkpath

    # SNS_POST_STOCKへ取込（重複防止: post_id 既存はスキップ）
    ws = _get_or_create_sheet(dest_ss, "SNS_POST_STOCK", SNS_SHEETS["SNS_POST_STOCK"])
    existing_ids = set(ws.col_values(1)[1:])
    header = SNS_SHEETS["SNS_POST_STOCK"]
    add = [[r.get(h, "") for h in header] for r in imported_rows if r["post_id"] not in existing_ids]
    # バッチ追記（500行ずつ・レート対策）
    for i in range(0, len(add), 500):
        ws.append_rows(add[i:i+500], value_input_option="RAW")
    result["imported"] = len(add)
    result["skipped_existing"] = len(imported_rows) - len(add)
    return result


# ── 3. LINE反応スクショ OCR（Vision・無料） ───────────────

_LINE_LABELS = {
    "line_friend_add_count": ["友だち追加", "友達追加", "新しい友だち", "追加数"],
    "line_message_count":    ["メッセージ", "受信メッセージ", "チャット数", "メッセージ数"],
    "reservation_count":     ["予約", "ご予約", "予約数"],
    "inquiry_count":         ["問い合わせ", "お問い合わせ", "問合せ"],
    "coupon_click_count":    ["クーポン", "クーポン利用", "クーポンクリック"],
}


def _parse_line_insight(full_text: str) -> dict:
    import re
    z2h = str.maketrans("０１２３４５６７８９，", "0123456789,")
    lines = [ln.strip() for ln in full_text.translate(z2h).splitlines() if ln.strip()]
    out = {k: None for k in _LINE_LABELS}

    def nearby_int(keys):
        for i, ln in enumerate(lines):
            for kw in keys:
                if kw in ln:
                    seg = ln.split(kw, 1)[1] if kw in ln else ln
                    m = re.findall(r"\d[\d,]*", seg)
                    if m:
                        return int(m[0].replace(",", ""))
                    if i + 1 < len(lines):
                        m2 = re.findall(r"\d[\d,]*", lines[i+1])
                        if m2:
                            return int(m2[0].replace(",", ""))
        return None

    for field, kws in _LINE_LABELS.items():
        out[field] = nearby_int(kws)

    found = sum(1 for v in out.values() if v is not None)
    out["_confidence"] = min(0.95, 0.5 + 0.1 * found) if found else 0.3
    return out


def classify_screenshot_text(full_text: str) -> str:
    """OCR全文から種別判定: 'sales' / 'line_insight' / 'sns_insight' / 'unknown'
    - sales        : POSレジ売上画面
    - line_insight : LINE公式アカウントの友だち分析画面
    - sns_insight  : Google/Threads/Instagram の投稿インサイト（いいね/保存/インプ等）
    """
    t = str(full_text)
    sales_kw = ["売上合計", "会計数", "客単価", "会計単価", "QR決済", "現金売上",
                "売上基本情報", "売上原価", "粗利", "販管費"]
    # LINE公式アカウント分析に特有
    line_kw  = ["友だち追加", "友達追加", "ブロック", "あいさつメッセージ", "有効友だち",
                "ターゲットリーチ", "メッセージ通数", "チャット", "配信"]
    # SNS投稿インサイトに特有（Threads/Instagram/Googleの実UI表記を含む）
    sns_kw   = ["いいね", "保存", "シェア", "リポスト", "インプレッション", "インプ",
                "プロフィールへのアクセス", "プロフィールアクセス", "プロフィール",
                "コメント", "エンゲージ", "閲覧数", "再生数", "表示", "♡", "❤", "リール",
                "スレッド", "アクティビティ"]
    plat_kw  = ["スレッド", "threads", "スレッズ", "instagram", "インスタ", "リール",
                "ビジネスプロフィール"]
    s = sum(1 for k in sales_kw if k in t)
    l = sum(1 for k in line_kw if k in t)
    n = sum(1 for k in sns_kw if k in t)
    has_plat = any(k in t.lower() for k in plat_kw)
    if s >= 1 and s >= l and s >= n:
        return "sales"
    # プラットフォームが特定でき、メトリクス語が1つでもあればSNS投稿
    if has_plat and n >= 1:
        return "sns_insight"
    if n >= 2 and n >= l:
        return "sns_insight"
    if l >= 2:
        return "line_insight"
    if s >= 1:
        return "sales"
    return "unknown"


def classify_screenshot(image_bytes, creds_path) -> tuple:
    """画像をVision OCRし、(種別, 全文) を返す。種別='line_insight'/'sales'/'unknown'"""
    try:
        from google.cloud import vision
        sa = Credentials.from_service_account_file(
            creds_path, scopes=["https://www.googleapis.com/auth/cloud-platform"])
        client = vision.ImageAnnotatorClient(credentials=sa)
        resp = client.document_text_detection(image=vision.Image(content=image_bytes))
        full_text = resp.full_text_annotation.text if resp.full_text_annotation else ""
        return classify_screenshot_text(full_text), full_text
    except Exception:
        return "unknown", ""


def process_line_screenshot(spreadsheet_id, creds_path, image_bytes, business_name,
                            image_url="", period_start="", period_end="", refresh=True):
    """LINE反応スクショをVision OCR → LINE_SCREENSHOT_LOG へ記録"""
    from google.cloud import vision
    sa = Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/cloud-platform"])
    client = vision.ImageAnnotatorClient(credentials=sa)
    resp = client.document_text_detection(image=vision.Image(content=image_bytes))
    if resp.error.message:
        return {"ok": False, "error": resp.error.message}
    full_text = resp.full_text_annotation.text if resp.full_text_annotation else ""
    parsed = _parse_line_insight(full_text)
    conf = parsed.pop("_confidence", 0.5)

    gc = _gc(creds_path); ss = gc.open_by_key(spreadsheet_id)
    ws = _get_or_create_sheet(ss, "LINE_SCREENSHOT_LOG", SNS_SHEETS["LINE_SCREENSHOT_LOG"])
    sid = f"LSS_{datetime.now(JST).strftime('%Y%m%d%H%M%S')}"
    human = "要確認" if conf < 0.7 else "OK"
    row = {
        "screenshot_id": sid, "business_name": business_name, "upload_date": _now(),
        "period_start": period_start, "period_end": period_end,
        "screenshot_file_url": image_url, "extracted_text": full_text[:1000],
        "line_friend_add_count": parsed.get("line_friend_add_count") or "",
        "line_message_count": parsed.get("line_message_count") or "",
        "reservation_count": parsed.get("reservation_count") or "",
        "inquiry_count": parsed.get("inquiry_count") or "",
        "coupon_click_count": parsed.get("coupon_click_count") or "",
        "ai_confidence_score": f"{conf:.0%}", "human_check_status": human, "memo": "",
    }
    header = SNS_SHEETS["LINE_SCREENSHOT_LOG"]
    ws.append_row([row.get(h, "") for h in header], value_input_option="RAW")

    # 自動でダッシュボードへ反映
    if refresh:
        try:
            refresh_dashboard(spreadsheet_id, creds_path)
        except Exception:
            pass

    # LINE返信文（読み取り結果）
    def _n(v): return f"{int(v):,}" if v not in (None, "", 0) else ("0" if v == 0 else "—")
    reply = (
        ("【LINE反応スクショ 読み取り完了】" if human == "OK" else "【LINE反応スクショ 要確認】") + "\n"
        f"事業：{business_name}\n"
        f"友だち追加：{_n(parsed.get('line_friend_add_count'))}\n"
        f"メッセージ：{_n(parsed.get('line_message_count'))}\n"
        f"予約：{_n(parsed.get('reservation_count'))}\n"
        f"問い合わせ：{_n(parsed.get('inquiry_count'))}\n"
        f"クーポン：{_n(parsed.get('coupon_click_count'))}\n"
        f"AI信頼度：{conf:.0%}\n"
        + ("\nこの内容で記録しました。" if human == "OK"
           else "\n数値が怪しい場合は、はっきり見える画面で再送してください。")
    )
    return {"ok": True, "screenshot_id": sid, "confidence": conf,
            "human_check_status": human, "parsed": parsed, "reply_text": reply}


# ── 4. ステータス / ダッシュボード ────────────────────────

def get_status(spreadsheet_id, creds_path):
    gc = _gc(creds_path); ss = gc.open_by_key(spreadsheet_id)
    out = {"ok": True}
    try:
        stock = ss.worksheet("SNS_POST_STOCK").get_all_records()
    except gspread.WorksheetNotFound:
        return {"ok": True, "note": "未セットアップ（/sns-setup を実行）"}
    by_biz = {}
    for r in stock:
        b = by_biz.setdefault(r.get("business_name", "?"),
                              {"total": 0, "posted": 0, "unposted": 0, "A": 0, "B": 0, "C": 0})
        b["total"] += 1
        if str(r.get("status")) == "投稿済み":
            b["posted"] += 1
        else:
            b["unposted"] += 1
        t = str(r.get("post_type", "A"))
        if t in ("A", "B", "C"):
            b[t] += 1
    out["post_stock"] = by_biz
    out["total_posts"] = len(stock)
    # LINE反応集計
    try:
        ls = ss.worksheet("LINE_SCREENSHOT_LOG").get_all_records()
        out["line_screenshots"] = len(ls)
        out["line_friend_add_total"] = sum(_pint(r.get("line_friend_add_count")) for r in ls)
        out["reservation_total"] = sum(_pint(r.get("reservation_count")) for r in ls)
        out["inquiry_total"] = sum(_pint(r.get("inquiry_count")) for r in ls)
    except gspread.WorksheetNotFound:
        pass
    return out


def refresh_dashboard(spreadsheet_id, creds_path):
    """SNS_DASHBOARD を最新集計で更新"""
    st = get_status(spreadsheet_id, creds_path)
    gc = _gc(creds_path); ss = gc.open_by_key(spreadsheet_id)
    dws = _get_or_create_sheet(ss, "SNS_DASHBOARD", SNS_SHEETS["SNS_DASHBOARD"])
    rows = []
    for biz, b in st.get("post_stock", {}).items():
        rows.append([
            _date(), biz, b["total"], b["posted"], b["unposted"],
            st.get("line_friend_add_total", "—"), st.get("inquiry_total", "—"),
            st.get("reservation_total", "—"), "（分析後に反映）", "（分析後に反映）",
            0, "（分析後に反映）", "（分析後に反映）",
            "未投稿の消化＋LINE反応スクショ送付", _now(),
        ])
    if rows:
        # 既存当日分はクリアして書き直し（簡易）
        existing = dws.get_all_values()
        if len(existing) > 1:
            dws.batch_clear([f"A2:O{len(existing)}"])
        dws.append_rows(rows, value_input_option="RAW")
    return {"ok": True, "businesses": len(rows)}


# ── 4b. 投稿結果のテキスト入力（投稿文＋反応） ───────────
import re as _re

# 反応ラベル（specific→genericの順）
_REACT_LABELS = [
    ("impressions",     ["インプレッション", "インプ", "表示回数", "表示", "閲覧", "視聴", "再生", "リーチ"]),
    ("profile_access",  ["プロフィールアクセス", "プロフィール", "プロフ"]),
    ("line_add",        ["line追加", "ライン追加", "友だち追加", "友達追加", "line", "ライン"]),
    ("dm_count",        ["dm", "ダイレクト"]),
    ("saves",           ["保存", "セーブ"]),
    ("shares",          ["シェア", "リポスト", "拡散"]),
    ("comments",        ["コメント", "返信数"]),
    ("likes",           ["いいね", "ライク", "♡", "❤", "♥", "ハート"]),
    ("reservation_count", ["予約"]),
    ("inquiry_count",   ["問い合わせ", "問合せ", "問合わせ"]),
    ("visit_count",     ["来店"]),
    ("sales_amount",    ["売上", "売り上げ"]),
]

_PLATFORM_KW = {"Google投稿": ["google", "グーグル", "gbp", "マップ", "ビジネスプロフィール"],
                "Threads投稿": ["threads", "スレッズ", "スレッド", "@"],
                "Instagram投稿": ["instagram", "インスタ", "リール", "ストーリーズ"]}


def _react_value(text: str, labels: list):
    """ラベル近傍の数値を取得（万対応）。無ければNone"""
    z = text.translate(str.maketrans("０１２３４５６７８９，", "0123456789,"))
    low = z.lower()
    for lb in labels:
        m = _re.search(_re.escape(lb.lower()) + r"\s*[:：]?\s*(\d[\d,]*)\s*(万)?", low)
        if m:
            v = int(m.group(1).replace(",", ""))
            if m.group(2):
                v *= 10000
            return v
    return None


def _detect_platform(text: str) -> str:
    low = text.lower()
    for plat, kws in _PLATFORM_KW.items():
        if any(k in low for k in kws):
            return plat
    return ""


def is_sns_result_message(text: str) -> bool:
    t = str(text)
    has_kw = ("投稿結果" in t) or ("反応" in t)
    # 反応ラベルが何個ヒットするか
    hits = 0
    for _, labels in _REACT_LABELS:
        if _react_value(t, labels) is not None:
            hits += 1
    return (has_kw and hits >= 1) or hits >= 2


def parse_sns_result(text: str, business_name: str = ""):
    """投稿結果メッセージを解析。{platform, reactions{}, post_text, business_name} or None"""
    if not is_sns_result_message(text):
        return None
    reactions = {}
    for field, labels in _REACT_LABELS:
        v = _react_value(text, labels)
        if v is not None:
            reactions[field] = v
    if not reactions:
        return None
    platform = _detect_platform(text) or "Threads投稿"
    biz = business_name or _detect_biz_name(text) or "全社"

    # 投稿本文の抽出: 反応行・プラットフォーム行・トリガー行を除いた残り
    lines = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        low = s.lower()
        if s in ("投稿結果", "結果", "反応") or low in ("google", "threads", "instagram"):
            continue
        # 反応ラベルを多く含む行は除外
        label_hits = sum(1 for _, labs in _REACT_LABELS for lb in labs if lb.lower() in low)
        if label_hits >= 2 and _re.search(r"\d", s):
            continue
        # 「投稿結果 Threads」のようなヘッダ行
        if ("投稿結果" in s or "反応" in s) and len(s) < 20:
            continue
        lines.append(s)
    post_text = "\n".join(lines).strip()
    return {"platform": platform, "reactions": reactions,
            "post_text": post_text, "business_name": biz}


def record_sns_result(spreadsheet_id, creds_path, text, business_name=""):
    """投稿文＋反応を SNS_POST_STOCK(投稿済) と SNS_RESULT に記録し、返信文を返す"""
    parsed = parse_sns_result(text, business_name)
    if parsed is None:
        return {"ok": False, "reply": (
            "投稿結果として認識できませんでした😅\n"
            "例：\n投稿結果 Threads\n（投稿した本文）\n"
            "いいね20 保存5 プロフ10 LINE3 予約1 売上12000")}

    gc = _gc(creds_path); ss = gc.open_by_key(spreadsheet_id)
    pid = f"SNSR_{datetime.now(JST).strftime('%Y%m%d%H%M%S')}"
    biz = parsed["business_name"]; plat = parsed["platform"]
    ptext = parsed["post_text"]; rc = parsed["reactions"]

    # 投稿文を SNS_POST_STOCK に投稿済として記録（分析で内容を使う）
    if ptext:
        sw = _get_or_create_sheet(ss, "SNS_POST_STOCK", SNS_SHEETS["SNS_POST_STOCK"])
        srow = {
            "post_id": pid, "business_name": biz, "platform": plat, "post_no": "",
            "original_text": ptext, "current_text": ptext, "post_type": _infer_type(ptext),
            "target_stage": "", "customer_pain": "", "hook_text": ptext.splitlines()[0][:50],
            "cta": "", "status": "投稿済み", "scheduled_date": "", "posted_date": _date(),
            "posted_url": "", "rewrite_version": 0, "memo": "LINE投稿結果入力",
        }
        sw.append_row([srow.get(h, "") for h in SNS_SHEETS["SNS_POST_STOCK"]],
                      value_input_option="RAW")

    # SNS_RESULT に反応を記録
    rw = _get_or_create_sheet(ss, "SNS_RESULT", SNS_SHEETS["SNS_RESULT"])
    rrow = {
        "post_id": pid, "business_name": biz, "platform": plat, "posted_date": _date(),
        "impressions": rc.get("impressions", ""), "likes": rc.get("likes", ""),
        "comments": rc.get("comments", ""), "shares": rc.get("shares", ""),
        "saves": rc.get("saves", ""), "profile_access": rc.get("profile_access", ""),
        "line_add": rc.get("line_add", ""), "dm_count": rc.get("dm_count", ""),
        "reservation_count": rc.get("reservation_count", ""),
        "inquiry_count": rc.get("inquiry_count", ""), "visit_count": rc.get("visit_count", ""),
        "sales_amount": rc.get("sales_amount", ""), "related_screenshot_id": "",
        "manual_note": "LINE入力: " + ptext[:80],
    }
    rw.append_row([rrow.get(h, "") for h in SNS_SHEETS["SNS_RESULT"]],
                  value_input_option="RAW")

    def _n(k): return f"{int(rc[k]):,}" if k in rc else "—"
    reply = (
        "✅ 投稿結果を記録しました\n"
        f"事業：{biz}\n媒体：{plat}\n"
        + (f"投稿：{ptext[:40]}…\n" if ptext else "")
        + f"いいね{_n('likes')} 保存{_n('saves')} プロフ{_n('profile_access')}\n"
        + f"LINE{_n('line_add')} 予約{_n('reservation_count')} 問合せ{_n('inquiry_count')} 売上{_n('sales_amount')}\n"
        + "\n「SNS分析」で勝ちパターンを確認できます。"
    )
    return {"ok": True, "reply": reply, "post_id": pid, "parsed": parsed}


# ── PHASE1拡張: SNSインサイトのスクショOCR記録（投稿本文不要） ──

def process_sns_insight_screenshot(spreadsheet_id, creds_path, image_bytes,
                                   business_name, sender="", image_url=""):
    """
    SNS投稿インサイトのスクショをVision OCR→数値抽出→SNS_RESULT記録。
    投稿本文の入力は不要。低信頼度は確認状況=要確認。
    返り値に reply_text を含む（LINE返信用）。
    """
    from google.cloud import vision
    sa = Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/cloud-platform"])
    client = vision.ImageAnnotatorClient(credentials=sa)
    resp = client.document_text_detection(image=vision.Image(content=image_bytes))
    if resp.error.message:
        return {"ok": False, "error": resp.error.message,
                "reply_text": "⚠️ 画像を読み取れませんでした。分かる数字だけ送ってください（例：いいね10 インプ500 売上3000）"}
    full_text = resp.full_text_annotation.text if resp.full_text_annotation else ""

    # 反応数値を抽出（既存 _REACT_LABELS を流用）
    reactions = {}
    for field, labels in _REACT_LABELS:
        v = _react_value(full_text, labels)
        if v is not None:
            reactions[field] = v
    platform = _detect_platform(full_text) or "不明"

    found = len(reactions)
    conf = min(0.95, 0.45 + 0.1 * found) if found else 0.25
    human = "OK" if conf >= 0.7 else "要確認"

    gc = _gc(creds_path); ss = gc.open_by_key(spreadsheet_id)
    pid = f"SNSS_{datetime.now(JST).strftime('%Y%m%d%H%M%S')}"

    # SNS_SCREENSHOT_LOG
    slog = _get_or_create_sheet(ss, "SNS_SCREENSHOT_LOG", SNS_SHEETS["SNS_SCREENSHOT_LOG"])
    slog.append_row([
        _now(), business_name, sender, image_url, full_text[:1000], platform,
        json.dumps(reactions, ensure_ascii=False), "", f"{conf:.0%}",
        "記録" if found else "要再送", "", "" if found else "数値抽出0",
    ], value_input_option="RAW")

    if not found:
        return {"ok": True, "recorded": False, "confidence": conf, "platform": platform,
                "reply_text": ("⚠️ 読み取りが不安定です\n分かる数字だけ送ってください。\n"
                               "例：いいね 10 インプ 500 売上 3000")}

    # SNS_RESULT へ記録（既存列にマッピング）
    rw = _get_or_create_sheet(ss, "SNS_RESULT", SNS_SHEETS["SNS_RESULT"])
    rrow = {
        "post_id": pid, "business_name": business_name,
        "platform": platform if platform != "不明" else "", "posted_date": _date(),
        "impressions": reactions.get("impressions", ""), "likes": reactions.get("likes", ""),
        "comments": reactions.get("comments", ""), "shares": reactions.get("shares", ""),
        "saves": reactions.get("saves", ""), "profile_access": reactions.get("profile_access", ""),
        "line_add": reactions.get("line_add", ""), "dm_count": reactions.get("dm_count", ""),
        "reservation_count": reactions.get("reservation_count", ""),
        "inquiry_count": reactions.get("inquiry_count", ""),
        "visit_count": reactions.get("visit_count", ""),
        "sales_amount": reactions.get("sales_amount", ""),
        "related_screenshot_id": pid,
        "manual_note": f"スクショOCR({human}) 信頼度{conf:.0%}",
    }
    rw.append_row([rrow.get(h, "") for h in SNS_SHEETS["SNS_RESULT"]], value_input_option="RAW")

    def _n(k): return f"{int(reactions[k]):,}" if k in reactions else "—"
    reply = (
        ("✅ SNS結果を記録しました" if human == "OK" else "⚠️ 読み取りが不安定です（記録はしました）") + "\n"
        f"事業：{business_name}\n媒体：{platform}\n"
        f"いいね：{_n('likes')}　インプ：{_n('impressions')}\n"
        f"プロフ：{_n('profile_access')}　保存：{_n('saves')}\n"
        f"LINE：{_n('line_add')}　予約：{_n('reservation_count')}　売上：{_n('sales_amount')}\n"
        f"信頼度：{conf:.0%}\n\n"
        "売上や来店があれば「売上 3200 来店 2」のように追加送信してください。"
    )
    return {"ok": True, "recorded": True, "post_id": pid, "confidence": conf,
            "platform": platform, "reactions": reactions, "human_check_status": human,
            "reply_text": reply}


# 追加数値だけのメッセージ（例: 「売上 3200 来店 2」）を直近SNS_RESULTに反映
def is_followup_numbers(text: str) -> bool:
    """投稿本文無し・反応ラベル+数値のみの短文か（直近結果への追記用）"""
    t = str(text).strip()
    if len(t) > 60 or "\n" in t:
        return False
    hits = sum(1 for _, labs in _REACT_LABELS if _react_value(t, labs) is not None)
    return hits >= 1 and hits <= 4


def apply_followup_numbers(spreadsheet_id, creds_path, text, business_name=""):
    """直近のSNS_RESULT（当日・同事業）に売上/来店等を追記"""
    upd = {}
    for field, labels in _REACT_LABELS:
        v = _react_value(text, labels)
        if v is not None:
            upd[field] = v
    if not upd:
        return {"ok": False, "reply": "数値を認識できませんでした。例：売上 3200 来店 2"}
    gc = _gc(creds_path); ss = gc.open_by_key(spreadsheet_id)
    try:
        ws = ss.worksheet("SNS_RESULT")
    except gspread.WorksheetNotFound:
        return {"ok": False, "reply": "先にスクショを送ってください。"}
    vals = ws.get_all_values()
    if len(vals) < 2:
        return {"ok": False, "reply": "先にスクショを送ってください。"}
    header = vals[0]
    # 当日・同事業の最後の行を探す
    target = None
    for i in range(len(vals) - 1, 0, -1):
        r = dict(zip(header, vals[i]))
        if str(r.get("posted_date")) == _date() and (not business_name or str(r.get("business_name")) == business_name):
            target = i + 1
            break
    if target is None:
        target = len(vals)  # 最後の行
    for field, v in upd.items():
        if field in header:
            ws.update_cell(target, header.index(field) + 1, v)
    disp = " ".join(f"{k}{v}" for k, v in upd.items())
    return {"ok": True, "reply": f"✅ 追記しました（{disp}）"}


# ── PHASE2: Winning Post Reuse Engine ─────────────────────

REUSE_TARGETS = ["Google投稿", "Instagramストーリー", "Instagram投稿",
                 "Threads再投稿", "LINE配信", "店頭POP", "口コミ依頼文", "HPBブログ"]


def _win_grade(r) -> tuple:
    """投稿の勝ち判定 S/A/B/C/除外 と理由"""
    sales = _pint(r.get("sales_amount")); visit = _pint(r.get("visit_count"))
    resv = _pint(r.get("reservation_count")); inq = _pint(r.get("inquiry_count"))
    line = _pint(r.get("line_add")); dm = _pint(r.get("dm_count"))
    prof = _pint(r.get("profile_access")); save = _pint(r.get("saves"))
    share = _pint(r.get("shares")); comm = _pint(r.get("comments"))
    like = _pint(r.get("likes")); imp = _pint(r.get("impressions"))

    if sales > 0 or visit > 0 or resv > 0 or inq > 0:
        return "S", "売上/来店/予約/問い合わせ獲得"
    if line > 0 or dm > 0 or prof >= 10:
        return "A", "LINE/DM/プロフィール遷移が多い"
    if save > 0 or share > 0 or comm > 0:
        return "B", "保存/シェア/コメントが良い"
    # バズったが売上導線ゼロ → 除外
    if imp >= 1000 and line == 0 and prof == 0:
        return "除外", "バズったが売上導線ゼロ"
    if like > 0:
        return "C", "いいねのみ"
    return "除外", "反応なし"


def detect_winning_posts(spreadsheet_id, creds_path):
    """SNS_RESULT×SNS_POST_STOCKから勝ち投稿を検出→SNS_WINNING_POSTS＋再利用タスク生成"""
    gc = _gc(creds_path); ss = gc.open_by_key(spreadsheet_id)
    try:
        results = ss.worksheet("SNS_RESULT").get_all_records()
        stock = {r.get("post_id"): r for r in ss.worksheet("SNS_POST_STOCK").get_all_records()}
    except gspread.WorksheetNotFound:
        return {"ok": False, "error": "SNS_RESULT/SNS_POST_STOCK 未作成"}
    if not results:
        return {"ok": True, "note": "SNS_RESULTにデータがありません"}

    win_rows, reuse_rows, dac_tasks = [], [], []
    biz_key_map = {"TACHINOMIYA": "tachinomiya", "TREE's Catering": "catering",
                   "Trees Catering": "catering", "Tree Beauty": "beauty", "琉球火鍋": "ryukyu_hinabe"}
    summary = {"S": 0, "A": 0, "B": 0, "C": 0, "除外": 0}

    for r in results:
        grade, reason = _win_grade(r)
        summary[grade] = summary.get(grade, 0) + 1
        if grade in ("S", "A"):
            st = stock.get(r.get("post_id"), {})
            body = str(st.get("current_text") or st.get("original_text") or "")
            hook = body.splitlines()[0][:50] if body else ""
            biz = str(r.get("business_name"))
            # 再利用先（S=売上連動→Google投稿/LINE配信/口コミ依頼、A=遷移→ストーリー/再投稿）
            targets = (["Google投稿", "LINE配信", "口コミ依頼文"] if grade == "S"
                       else ["Instagramストーリー", "Threads再投稿"])
            win_rows.append([
                _now(), biz, r.get("platform", ""), r.get("posted_date", ""), body[:300], hook, reason,
                _pint(r.get("sales_amount")), _pint(r.get("visit_count")), _pint(r.get("reservation_count")),
                _pint(r.get("inquiry_count")), _pint(r.get("impressions")), _pint(r.get("profile_access")),
                _pint(r.get("saves")), _pint(r.get("shares")),
                grade, "／".join(targets), body[:200], "あり", "",
            ])
            for tg in targets:
                reuse_rows.append([_now(), biz, r.get("platform", ""), tg,
                                   f"勝ち投稿({reason})を{tg}へ再利用: {hook}", "", _date(),
                                   "未対応", "", ""])
            dac_tasks.append({"biz_key": biz_key_map.get(biz, "owner"),
                              "priority": "S" if grade == "S" else "A",
                              "task": f"【勝ち投稿再利用】{biz}: {targets[0]}へ再掲（{hook}）"})

    if win_rows:
        ws = _get_or_create_sheet(ss, "SNS_WINNING_POSTS", SNS_SHEETS["SNS_WINNING_POSTS"])
        ws.append_rows(win_rows, value_input_option="RAW")
    if reuse_rows:
        rws = _get_or_create_sheet(ss, "SNS_REUSE_ACTIONS", SNS_SHEETS["SNS_REUSE_ACTIONS"])
        rws.append_rows(reuse_rows, value_input_option="RAW")

    return {"ok": True, "grade_summary": summary, "winning": len(win_rows),
            "reuse_actions": len(reuse_rows), "daily_action_tasks": dac_tasks, "dry_run": True}


# ── 5. ルールベース分析（Phase 2） ────────────────────────

def analyze(spreadsheet_id, creds_path):
    """
    SNS_RESULT + LINE_SCREENSHOT_LOG から売上貢献度で評価し、
    勝ち/負けパターン・TYPE別TOP・改善方針を SNS_AI_ANALYSIS に記録（ルールベース）。
    """
    gc = _gc(creds_path); ss = gc.open_by_key(spreadsheet_id)
    try:
        results = ss.worksheet("SNS_RESULT").get_all_records()
        stock = {r.get("post_id"): r for r in ss.worksheet("SNS_POST_STOCK").get_all_records()}
    except gspread.WorksheetNotFound:
        return {"ok": False, "error": "SNS_RESULT/SNS_POST_STOCK 未作成"}

    if not results:
        return {"ok": True, "note": "SNS_RESULTにデータがありません（投稿結果を記録してください）"}

    # 売上貢献度スコア（売上>来店>予約>問い合わせ>LINE追加>プロフィール >> いいね/保存）
    def score(r):
        return (_pint(r.get("sales_amount")) * 0.001
                + _pint(r.get("visit_count")) * 30
                + _pint(r.get("reservation_count")) * 25
                + _pint(r.get("inquiry_count")) * 20
                + _pint(r.get("line_add")) * 10
                + _pint(r.get("profile_access")) * 2
                + _pint(r.get("saves")) * 0.5
                + _pint(r.get("likes")) * 0.1)

    scored = [(r, score(r)) for r in results]
    scored.sort(key=lambda x: x[1], reverse=True)
    top = [r for r, s in scored if s > 0][:10]
    weak = [r for r, s in scored if s <= 0][:10]

    # 勝ちフック/悩み/CTA（top投稿の元stockから集約）
    def collect(field):
        vals = []
        for r in top:
            st_row = stock.get(r.get("post_id"), {})
            v = str(st_row.get(field, "")).strip()
            if v:
                vals.append(v)
        return "／".join(vals[:5])

    # バズったが売上ゼロ / 売上出たが伸びない
    buzz_no_sales = [r for r in results if _pint(r.get("impressions")) >= 1000
                     and _pint(r.get("sales_amount")) == 0 and _pint(r.get("reservation_count")) == 0]
    sales_low_reach = [r for r in results
                       if (_pint(r.get("sales_amount")) > 0 or _pint(r.get("reservation_count")) > 0)
                       and _pint(r.get("impressions")) < 500]

    analysis = {
        "analysis_id": f"AN_{datetime.now(JST).strftime('%Y%m%d%H%M%S')}",
        "analysis_date": _date(), "business_name": "全社", "platform": "全媒体",
        "period_start": "", "period_end": _date(),
        "top_post_ids": ",".join(str(r.get("post_id")) for r in top),
        "weak_post_ids": ",".join(str(r.get("post_id")) for r in weak),
        "winning_hooks": collect("hook_text"),
        "winning_customer_pains": collect("customer_pain"),
        "winning_cta": collect("cta"),
        "line_reaction_summary": f"バズ無売上{len(buzz_no_sales)}件 / 売上有低リーチ{len(sales_low_reach)}件",
        "bad_patterns": f"高インプレッション×売上ゼロ {len(buzz_no_sales)}件",
        "next_improvement_policy": "勝ちフック/CTAを未投稿へ適用。集客投稿(TYPE-C)比率を上げる。",
        "ai_summary": f"上位{len(top)}投稿が売上貢献。改善対象{len(weak)}件。",
    }
    ws = _get_or_create_sheet(ss, "SNS_AI_ANALYSIS", SNS_SHEETS["SNS_AI_ANALYSIS"])
    header = SNS_SHEETS["SNS_AI_ANALYSIS"]
    ws.append_row([analysis.get(h, "") for h in header], value_input_option="RAW")
    return {"ok": True, "analysis": analysis, "top_count": len(top), "weak_count": len(weak)}
