"""
Threads 手動返信支援システム（API承認前完成版）

フロー:
  スタッフが投稿URL＋本文をシートに貼る
  → AI判定（スコア・店舗選択・返信案生成）
  → スタッフ用LINEへ通知（投稿URL＋返信案）
  → スタッフが投稿URLを開いて手動返信
  → 履歴をシートに保存

Threadsへの自動返信は行わない。API承認後に自動検索部分だけ追加できる構造。
"""

import os
import re
import datetime
import requests

import gspread
from google.oauth2.service_account import Credentials

from core.threads_reply_generator import (
    select_store,
    generate_reply,
    check_reply_quality,
    TACHINOMIYA_INFO,
    HINABE_INFO,
    EXCLUDE_KEYWORDS,
    NON_SEARCH_PATTERNS,
)
from core.threads_keyword_loader import (
    get_keywords,
    match_keywords,
    build_keyword_config_sheet_data,
    build_search_keywords_sheet_data,
    KEYWORD_CONFIG_SHEET_NAME,
    SEARCH_KEYWORDS_SHEET_NAME,
    CAT_OKINAWA_NOW,
    CAT_SEEKING,
    CAT_NAHA,
    CAT_STORE_T,
    CAT_STORE_H,
    CAT_SPECIFIC,
    CAT_EXCLUDE,
    _FALLBACK as _KW_FALLBACK,
)

# ─── 設定 ──────────────────────────────────────────────
INBOX_SHEET_NAME = "THREADS_MANUAL_REPLY_INBOX"

# THREADS_MONITOR_SPREADSHEET_ID 優先、未設定時はTACHINOMIYA SS
DEFAULT_SS_ID = "1K4KkAhFwVkQqqvzeqa25-1sR26ltBfP9gY9h-N4gXcc"

INBOX_HEADERS = [
    "登録日時",       # A
    "投稿URL",        # B
    "投稿本文",       # C
    "投稿者名",       # D
    "検知キーワード", # E
    "関連性スコア",   # F
    "推奨店舗",       # G
    "返信案",         # H
    "通知先LINE",     # I
    "通知状況",       # J
    "通知日時",       # K
    "スタッフ対応状況", # L
    "対応者",         # M
    "返信完了日時",   # N
    "メモ",           # O
    "エラー内容",     # P
]

# スコア閾値
SCORE_PRIORITY  = 80   # 80点以上：優先通知
SCORE_NOTIFY    = 70   # 70〜79点：通常通知
SCORE_HOLD      = 50   # 50〜69点：保留（通知しない）
SCORE_EXCLUDE   = 49   # 49点以下：除外

# 同一ユーザーへの通知クールダウン（日数）
USER_COOLDOWN_DAYS = 7

# キーワード定数（フォールバック用。スコアリングはシートから読み込んだ値を優先する）
OKINAWA_NOW_KEYWORDS = _KW_FALLBACK[CAT_OKINAWA_NOW]
SEEKING_KEYWORDS     = _KW_FALLBACK[CAT_SEEKING]
NAHA_KEYWORDS        = _KW_FALLBACK[CAT_NAHA]
SPECIFIC_PATTERNS = [
    r"\d+人", r"\d+名", r"\d+月\d+日", r"\d+日",
    "今夜", "今晩", "明日", "今日", "今週末", "来週",
    "個室", "ランチ", "ディナー", "夕食", "予算", "コース",
    "しゃぶしゃぶ", "火鍋", "サーターアンダギー", "記念日", "女子会",
]

# テスト用疑似データ（6件: TACHINOMIYA×2, 琉球火鍋×2, 両方×1, 除外×1）
TEST_ROWS = [
    {
        "url": "https://www.threads.net/@test_t001/post/MTEST001",
        "text": "那覇の国際通りで1人でご飯食べたい。観光中なんだけどどこがいいかな？沖縄料理も気になってます",
        "username": "@test_tachinomiya_01",
        "keyword": "国際通り 1人 観光",
    },
    {
        "url": "https://www.threads.net/@test_t002/post/MTEST002",
        "text": "国際通り周辺でランチを探しています。昼間に沖縄料理を食べたい。サーターアンダギーも気になっています！",
        "username": "@test_tachinomiya_02",
        "keyword": "国際通り ランチ サーターアンダギー",
    },
    {
        "url": "https://www.threads.net/@test_h001/post/MTEST003",
        "text": "来週沖縄で記念日ディナーをします。個室で落ち着いた雰囲気のお店を探しています。予算は2人で1万円前後",
        "username": "@test_hinabe_01",
        "keyword": "沖縄 記念日 個室 ディナー",
    },
    {
        "url": "https://www.threads.net/@test_h002/post/MTEST004",
        "text": "沖縄で友達と女子会をしたいです。しゃぶしゃぶか火鍋が食べられる個室のお店を教えてください！",
        "username": "@test_hinabe_02",
        "keyword": "沖縄 女子会 個室 しゃぶしゃぶ 火鍋",
    },
    {
        "url": "https://www.threads.net/@test_both01/post/MTEST005",
        "text": "沖縄旅行中です。国際通りで昼は軽めに食べて、夜は個室でゆっくり食事したいです。どちらもおすすめを教えてください",
        "username": "@test_both_01",
        "keyword": "沖縄 国際通り 個室 昼 夜",
    },
    {
        "url": "https://www.threads.net/@test_ex01/post/MTEST006",
        "text": "沖縄そばのレシピを教えてください。自宅で作りたいです。ゴーヤチャンプルーも挑戦したい",
        "username": "@test_exclude_01",
        "keyword": "",
    },
]


# ─────────────────────────────────────────────────────────
# Google Sheets
# ─────────────────────────────────────────────────────────

def _get_gc(creds_path: str) -> gspread.Client:
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds)


def setup_sheet(creds_path: str, ss_id: str = "") -> dict:
    """THREADS_MANUAL_REPLY_INBOX シートを作成または既存確認"""
    sid = ss_id or os.getenv("THREADS_MONITOR_SPREADSHEET_ID", DEFAULT_SS_ID)
    gc = _get_gc(creds_path)
    ss = gc.open_by_key(sid)

    try:
        ws = ss.worksheet(INBOX_SHEET_NAME)
        existing = ws.row_values(1)
        missing = [h for h in INBOX_HEADERS if h not in existing]
        if missing:
            for h in missing:
                col = len(ws.row_values(1)) + 1
                ws.update_cell(1, col, h)
        status = "既存シートを確認（列追加あり）" if missing else "既存シートを確認（変更なし）"
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(
            title=INBOX_SHEET_NAME,
            rows=500,
            cols=len(INBOX_HEADERS),
        )
        ws.update([INBOX_HEADERS], "A1")
        # ヘッダー書式
        try:
            ws.format("A1:P1", {
                "backgroundColor": {"red": 0.1, "green": 0.4, "blue": 0.2},
                "textFormat": {
                    "bold": True,
                    "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                },
            })
            # B列（投稿URL）を広く
            ws.format("B:B", {"wrapStrategy": "CLIP"})
        except Exception:
            pass
        status = "新規シートを作成"

    # THREADS_KEYWORD_CONFIG シートのセットアップ
    kw_status = _setup_keyword_config_sheet(ss)

    # THREADS_SEARCH_KEYWORDS シートのセットアップ
    search_kw_status = _setup_search_keywords_sheet(ss)

    return {
        "ok": True,
        "status": status,
        "sheet": INBOX_SHEET_NAME,
        "keyword_config_status": kw_status,
        "search_keywords_status": search_kw_status,
        "spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{sid}",
    }


def _setup_search_keywords_sheet(ss: gspread.Spreadsheet) -> str:
    """THREADS_SEARCH_KEYWORDS シートを作成または確認する"""
    try:
        ss.worksheet(SEARCH_KEYWORDS_SHEET_NAME)
        return "既存シートを確認（変更なし）"
    except gspread.WorksheetNotFound:
        pass

    rows = build_search_keywords_sheet_data()
    ws = ss.add_worksheet(
        title=SEARCH_KEYWORDS_SHEET_NAME,
        rows=max(300, len(rows) + 30),
        cols=7,
    )
    ws.update(rows, "A1")
    try:
        ws.format("A1:G1", {
            "backgroundColor": {"red": 0.8, "green": 0.4, "blue": 0.0},
            "textFormat": {
                "bold": True,
                "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
            },
        })
        ws.freeze(rows=1)
    except Exception:
        pass
    return f"新規作成（{len(rows) - 1}語を登録）"


def _setup_keyword_config_sheet(ss: gspread.Spreadsheet) -> str:
    """THREADS_KEYWORD_CONFIG シートを作成または確認する"""
    try:
        ws = ss.worksheet(KEYWORD_CONFIG_SHEET_NAME)
        return "既存シートを確認（変更なし）"
    except gspread.WorksheetNotFound:
        pass

    rows = build_keyword_config_sheet_data()
    ws = ss.add_worksheet(
        title=KEYWORD_CONFIG_SHEET_NAME,
        rows=max(500, len(rows) + 50),
        cols=6,
    )
    ws.update(rows, "A1")
    try:
        ws.format("A1:F1", {
            "backgroundColor": {"red": 0.1, "green": 0.3, "blue": 0.6},
            "textFormat": {
                "bold": True,
                "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
            },
        })
        ws.freeze(rows=1)
    except Exception:
        pass
    return f"新規作成（{len(rows) - 1}語を登録）"


def _load_inbox(ws: gspread.Worksheet) -> list[dict]:
    """全行をロード。行番号を _row_num キーに付加"""
    try:
        all_vals = ws.get_all_values()
    except Exception:
        return []
    if len(all_vals) < 2:
        return []

    header = all_vals[0]

    def safe_idx(name):
        return header.index(name) if name in header else None

    idxs = {h: safe_idx(h) for h in INBOX_HEADERS}
    rows = []
    for row_offset, row in enumerate(all_vals[1:], start=2):
        def cell(name):
            i = idxs.get(name)
            return row[i].strip() if i is not None and i < len(row) else ""

        rows.append({
            "_row_num": row_offset,
            **{h: cell(h) for h in INBOX_HEADERS},
        })
    return rows


def _update_row(ws: gspread.Worksheet, row_num: int, updates: dict) -> None:
    """指定行の列を更新"""
    for col_name, val in updates.items():
        if col_name in INBOX_HEADERS:
            col_idx = INBOX_HEADERS.index(col_name) + 1
            ws.update_cell(row_num, col_idx, str(val))


def _append_test_rows(ws: gspread.Worksheet, rows: list[dict]) -> None:
    """テストデータを末尾に追記"""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for r in rows:
        values = [""] * len(INBOX_HEADERS)
        values[INBOX_HEADERS.index("登録日時")] = now_str
        values[INBOX_HEADERS.index("投稿URL")] = r.get("url", "")
        values[INBOX_HEADERS.index("投稿本文")] = r.get("text", "")
        values[INBOX_HEADERS.index("投稿者名")] = r.get("username", "")
        values[INBOX_HEADERS.index("検知キーワード")] = r.get("keyword", "")
        values[INBOX_HEADERS.index("通知状況")] = "未通知"
        values[INBOX_HEADERS.index("スタッフ対応状況")] = "未対応"
        ws.append_row(values, value_input_option="USER_ENTERED")


# ─────────────────────────────────────────────────────────
# スコアリング
# ─────────────────────────────────────────────────────────

def _kw_match(text: str, keywords: list) -> list:
    """キーワードマッチ（複合フレーズはAND一致）"""
    return match_keywords(text, keywords)


def score_post_manual(text: str, kw_config: dict | None = None) -> dict:
    """
    100点満点スコアリング（手動受付版）。
    ① 沖縄旅行中/予定：25点
    ② 飲食店を探している：25点
    ③ 那覇/国際通り周辺：20点
    ④ 店舗特徴との一致：20点（複合フレーズ対応）
    ⑤ 投稿が具体的：10点（複合フレーズ対応）

    kw_config: get_keywords() の戻り値。None のときはフォールバック使用。
    """
    cfg = kw_config or _KW_FALLBACK
    breakdown = {}
    matched = []

    # ① 滞在/旅行予定
    m1 = _kw_match(text, cfg[CAT_OKINAWA_NOW])
    breakdown["滞在/旅行予定"] = 25 if m1 else 0
    matched.extend(m1[:3])

    # ② 飲食探索意向
    m2 = _kw_match(text, cfg[CAT_SEEKING])
    breakdown["飲食探索意向"] = 25 if m2 else 0
    matched.extend(m2[:2])

    # ③ 那覇/国際通り
    m3 = _kw_match(text, cfg[CAT_NAHA])
    breakdown["那覇周辺"] = 20 if m3 else 0
    matched.extend(m3[:2])

    # ④ 店舗特徴マッチ（シート定義 + 既存ハードコード両方）
    all_store_kw = list(set(
        cfg[CAT_STORE_T] + cfg[CAT_STORE_H]
        + TACHINOMIYA_INFO["keywords"] + HINABE_INFO["keywords"]
    ))
    m4 = _kw_match(text, all_store_kw)
    if len(m4) >= 2:
        breakdown["店舗マッチ"] = 20
    elif len(m4) == 1:
        breakdown["店舗マッチ"] = 10
    else:
        breakdown["店舗マッチ"] = 0
    matched.extend(m4[:3])

    # ⑤ 投稿の具体性（正規表現パターン + シート定義の具体性キーワード）
    specific_count = sum(1 for p in SPECIFIC_PATTERNS if re.search(p, text))
    specific_count += len(_kw_match(text, cfg[CAT_SPECIFIC]))
    if len(text) > 40:
        specific_count += 1
    breakdown["具体性"] = 10 if specific_count >= 2 else (5 if specific_count == 1 else 0)

    total = sum(breakdown.values())
    return {
        "score": total,
        "breakdown": breakdown,
        "keywords_matched": list(dict.fromkeys(matched)),
    }


def _should_exclude(text: str, kw_config: dict | None = None) -> tuple[bool, str]:
    """除外対象かどうかを判定（シート定義の除外キーワードを優先）"""
    cfg = kw_config or _KW_FALLBACK
    exclude_kws = list(set(cfg[CAT_EXCLUDE] + EXCLUDE_KEYWORDS))

    for kw in exclude_kws:
        if kw.lower() in text.lower():
            return True, f"除外キーワード: {kw}"

    for p in NON_SEARCH_PATTERNS:
        if re.search(p, text):
            return True, "飲食店を探していない投稿（感想/宣伝）"

    # 沖縄関連ゼロ
    okinawa_kw = ["沖縄", "那覇", "国際通り", "ナハ", "琉球"]
    if not any(kw in text for kw in okinawa_kw):
        return True, "沖縄関連キーワードなし"

    return False, ""


# ─────────────────────────────────────────────────────────
# URL から本文取得（Threads側の制約で失敗する場合が多い）
# ─────────────────────────────────────────────────────────

def _try_fetch_text_from_url(url: str) -> str:
    """
    Threads投稿URLから本文取得を試行。
    JavaScript レンダリングが必要なため多くの場合失敗する。
    失敗時は空文字を返す。
    """
    if not url or "threads.net" not in url:
        return ""
    try:
        resp = requests.get(
            url,
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1)"},
        )
        if not resp.ok:
            return ""
        # OGP の og:description を探す（JavaScript なしで取れる場合のみ）
        m = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']', resp.text)
        if m:
            return m.group(1).strip()
        m2 = re.search(r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:description["\']', resp.text)
        if m2:
            return m2.group(1).strip()
    except Exception:
        pass
    return ""


# ─────────────────────────────────────────────────────────
# LINE 通知
# ─────────────────────────────────────────────────────────

def _send_line(token: str, message: str) -> bool:
    if not token:
        return False
    try:
        resp = requests.post(
            "https://api.line.me/v2/bot/message/broadcast",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"messages": [{"type": "text", "text": message}]},
            timeout=10,
        )
        return resp.ok
    except Exception:
        return False


def _build_line_message(row: dict, score: int, stores: list[str], reply: str, post_url: str) -> str:
    store_names = [
        TACHINOMIYA_INFO["name"] if s == "tachinomiya" else HINABE_INFO["name"]
        for s in stores
    ]
    text_preview = row["投稿本文"][:150] + ("..." if len(row["投稿本文"]) > 150 else "")

    return (
        f"【Threads手動返信候補】\n\n"
        f"推奨店舗：{' / '.join(store_names)}\n"
        f"関連性スコア：{score}点\n"
        f"投稿URL：{post_url}\n"
        f"投稿本文：{text_preview}\n"
        f"返信案：{reply}\n\n"
        f"【スタッフ作業】\n\n"
        f"1. 投稿URLを開く\n"
        f"2. 返信案をコピー\n"
        f"3. Threadsに手動で貼り付け\n"
        f"4. 完了後、シートの「スタッフ対応状況」を「返信完了」に変更"
    )


# ─────────────────────────────────────────────────────────
# 重複チェック
# ─────────────────────────────────────────────────────────

def _is_duplicate_url(url: str, history: list[dict]) -> bool:
    """同じ投稿URLが既に通知済みか"""
    return any(
        r.get("投稿URL", "") == url and r.get("通知状況", "") == "通知済み"
        for r in history
    )


def _user_cooldown_flag(username: str, history: list[dict]) -> bool:
    """同一ユーザーへの7日以内通知あり（フラグ用、ブロックはしない）"""
    if not username or username == "不明":
        return False
    cutoff = datetime.datetime.now() - datetime.timedelta(days=USER_COOLDOWN_DAYS)
    for r in history:
        if r.get("投稿者名", "") != username:
            continue
        if r.get("通知状況", "") != "通知済み":
            continue
        try:
            dt = datetime.datetime.strptime(r.get("通知日時", "")[:19], "%Y-%m-%d %H:%M:%S")
            if dt > cutoff:
                return True
        except Exception:
            pass
    return False


# ─────────────────────────────────────────────────────────
# メイン処理
# ─────────────────────────────────────────────────────────

def process_inbox(
    creds_path: str,
    ss_id: str = "",
    openai_key: str = "",
    line_token_tachinomiya: str = "",
    line_token_hinabe: str = "",
) -> dict:
    """
    THREADS_MANUAL_REPLY_INBOX の未通知行を処理する。
    投稿URL と 投稿本文 が入っている行を対象とする。
    """
    sid = ss_id or os.getenv("THREADS_MONITOR_SPREADSHEET_ID", DEFAULT_SS_ID)
    oai_key = openai_key or os.getenv("OPENAI_API_KEY", "")
    tok_t = line_token_tachinomiya or os.getenv("LINE_TACHINOMIYASTAFF_TOKEN", "")
    tok_h = line_token_hinabe or os.getenv("LINE_hinabeSTAFF_TOKEN", "")

    gc = _get_gc(creds_path)
    ss = gc.open_by_key(sid)
    ws = ss.worksheet(INBOX_SHEET_NAME)
    history = _load_inbox(ws)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # キーワード設定をシートから読み込む（失敗時はフォールバック）
    try:
        kw_ws = ss.worksheet(KEYWORD_CONFIG_SHEET_NAME)
        kw_config = get_keywords(kw_ws)
    except Exception:
        kw_config = get_keywords(None)

    results = {
        "processed": 0,
        "notified": 0,
        "held": 0,
        "excluded": 0,
        "text_missing": 0,
        "duplicate_url": 0,
        "errors": 0,
        "details": [],
    }

    # 未通知行だけ対象
    target_rows = [
        r for r in history
        if r.get("通知状況", "").strip() in ("", "未通知")
        and r.get("投稿URL", "").strip()
    ]

    for row in target_rows:
        row_num = row["_row_num"]
        post_url = row["投稿URL"].strip()
        text = row["投稿本文"].strip()
        username = row["投稿者名"].strip()
        detail = {"row": row_num, "url": post_url[:60]}

        # 投稿本文が空 → URL取得を試みる
        if not text:
            text = _try_fetch_text_from_url(post_url)
            if text:
                _update_row(ws, row_num, {"投稿本文": text})
            else:
                _update_row(ws, row_num, {
                    "通知状況": "本文不足",
                    "エラー内容": "投稿本文が空。URLからの取得も失敗しました",
                })
                results["text_missing"] += 1
                detail["status"] = "本文不足"
                results["details"].append(detail)
                continue

        # 重複URL確認
        if _is_duplicate_url(post_url, history):
            _update_row(ws, row_num, {
                "通知状況": "除外",
                "エラー内容": "同一URLが既に通知済みです",
            })
            results["duplicate_url"] += 1
            detail["status"] = "重複URL"
            results["details"].append(detail)
            continue

        # 除外チェック
        is_ex, ex_reason = _should_exclude(text, kw_config)
        if is_ex:
            _update_row(ws, row_num, {
                "通知状況": "除外",
                "エラー内容": ex_reason,
            })
            results["excluded"] += 1
            detail.update({"status": "除外", "reason": ex_reason})
            results["details"].append(detail)
            continue

        # スコアリング
        score_result = score_post_manual(text, kw_config)
        score = score_result["score"]
        keywords = ",".join(score_result["keywords_matched"])
        detail["score"] = score

        # 店舗選択・返信案生成（スコア問わず記録）
        store_result = select_store(text)
        stores = store_result["stores"]
        store_names = [
            TACHINOMIYA_INFO["name"] if s == "tachinomiya" else HINABE_INFO["name"]
            for s in stores
        ]
        reply = generate_reply(text, stores, oai_key) if stores else ""
        quality = check_reply_quality(reply) if reply else {"ok": False, "issues": ["店舗未選択"]}

        # 通知先LINE
        line_targets = []
        if "tachinomiya" in stores:
            line_targets.append("TACHINOMIYA")
        if "hinabe" in stores:
            line_targets.append("琉球火鍋")

        # クールダウンフラグ
        cooldown_note = ""
        if username and _user_cooldown_flag(username, history):
            cooldown_note = f" | {username}への7日以内通知あり（注意）"

        # 保留判定（スコア50〜69）
        if score < SCORE_HOLD:
            _update_row(ws, row_num, {
                "関連性スコア": str(score),
                "検知キーワード": keywords,
                "推奨店舗": " / ".join(store_names),
                "返信案": reply,
                "通知先LINE": " / ".join(line_targets),
                "通知状況": "除外",
                "エラー内容": f"スコア不足({score}点)",
            })
            results["excluded"] += 1
            detail["status"] = "除外（スコア不足）"
            results["details"].append(detail)
            continue

        if score < SCORE_NOTIFY:
            _update_row(ws, row_num, {
                "関連性スコア": str(score),
                "検知キーワード": keywords,
                "推奨店舗": " / ".join(store_names),
                "返信案": reply,
                "通知先LINE": " / ".join(line_targets),
                "通知状況": "保留",
                "エラー内容": f"スコア保留({score}点 / 通知は70点以上)" + cooldown_note,
            })
            results["held"] += 1
            detail["status"] = f"保留({score}点)"
            results["details"].append(detail)
            continue

        # 70点以上 → LINE通知
        line_message = _build_line_message(row, score, stores, reply, post_url)
        notified_channels = []
        errors = []

        if "tachinomiya" in stores:
            ok = _send_line(tok_t, line_message)
            if ok:
                notified_channels.append("TACHINOMIYA")
            else:
                errors.append("TACHINOMIYA LINE送信失敗")

        if "hinabe" in stores:
            ok = _send_line(tok_h, line_message)
            if ok:
                notified_channels.append("琉球火鍋")
            else:
                errors.append("琉球火鍋 LINE送信失敗")

        if notified_channels:
            notification_status = "通知済み"
            results["notified"] += 1
        else:
            notification_status = "エラー"
            results["errors"] += 1

        _update_row(ws, row_num, {
            "関連性スコア": str(score),
            "検知キーワード": keywords,
            "推奨店舗": " / ".join(store_names),
            "返信案": reply,
            "通知先LINE": " / ".join(notified_channels or line_targets),
            "通知状況": notification_status,
            "通知日時": now_str if notified_channels else "",
            "スタッフ対応状況": "未対応",
            "エラー内容": (
                (" | ".join(errors) + cooldown_note).strip(" | ")
                if errors or cooldown_note
                else ("品質警告: " + ", ".join(quality["issues"]) if not quality["ok"] else "")
            ),
        })

        results["processed"] += 1
        detail.update({
            "status": notification_status,
            "stores": store_names,
            "score": score,
            "line_channels": notified_channels,
        })
        results["details"].append(detail)

    return {
        "ok": True,
        "summary": results,
        "target_rows": len(target_rows),
        "spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{sid}",
        "sheet": INBOX_SHEET_NAME,
    }


def get_inbox_status(creds_path: str, ss_id: str = "") -> dict:
    """
    THREADS_MANUAL_REPLY_INBOX の現在の状況を集計して返す。
    未処理件数・通知済み件数・返信完了件数・除外件数を返す。
    """
    sid = ss_id or os.getenv("THREADS_MONITOR_SPREADSHEET_ID", DEFAULT_SS_ID)
    gc = _get_gc(creds_path)
    ss = gc.open_by_key(sid)
    ws = ss.worksheet(INBOX_SHEET_NAME)
    rows = _load_inbox(ws)

    counts = {
        "未処理": 0,
        "通知済み": 0,
        "返信完了": 0,
        "保留": 0,
        "除外": 0,
        "本文不足": 0,
        "その他": 0,
        "合計": len(rows),
    }
    for r in rows:
        status = r.get("通知状況", "").strip()
        response = r.get("スタッフ対応状況", "").strip()
        if response == "返信完了":
            counts["返信完了"] += 1
        elif status in ("", "未通知"):
            counts["未処理"] += 1
        elif status == "通知済み":
            counts["通知済み"] += 1
        elif status == "保留":
            counts["保留"] += 1
        elif status == "除外":
            counts["除外"] += 1
        elif status == "本文不足":
            counts["本文不足"] += 1
        else:
            counts["その他"] += 1

    return {
        "ok": True,
        "counts": counts,
        "sheet": INBOX_SHEET_NAME,
        "spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{sid}",
    }


def run_test(creds_path: str, ss_id: str = "", openai_key: str = "") -> dict:
    """
    テストデータ6件を THREADS_MANUAL_REPLY_INBOX に追記し、
    処理を実行して結果を返す。
    実行のたびにユニークなサフィックスを付けてURLを変えるため、重複しない。
    """
    import random, string
    sid = ss_id or os.getenv("THREADS_MONITOR_SPREADSHEET_ID", DEFAULT_SS_ID)
    oai_key = openai_key or os.getenv("OPENAI_API_KEY", "")

    # シートがなければ作成
    setup_result = setup_sheet(creds_path, sid)

    gc = _get_gc(creds_path)
    ss = gc.open_by_key(sid)
    ws = ss.worksheet(INBOX_SHEET_NAME)

    # テストデータURL を毎回ユニーク化（重複防止）
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    test_rows_unique = [
        {**r, "url": r["url"].replace("MTEST00", f"MTEST{suffix}")}
        for r in TEST_ROWS
    ]
    _append_test_rows(ws, test_rows_unique)

    # 処理実行
    process_result = process_inbox(creds_path, sid, oai_key)

    return {
        "ok": True,
        "setup": setup_result,
        "test_rows_added": len(TEST_ROWS),
        "process": process_result,
    }
