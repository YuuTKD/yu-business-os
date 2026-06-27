"""
Threads 沖縄旅行需要検知・返信承認システム（App Review前完成版）

フロー:
  1. 投稿データを受け取る（テストデータ or 将来の実API）
  2. 除外フィルタ
  3. 関連性スコア判定（100点満点）
  4. 重複・クールダウン確認
  5. レート制限チェック（1h最大3件、1日最大10件）
  6. 推奨店舗選択
  7. 返信案生成（GPT-4o-mini、個別文）
  8. スプレッドシート記録
  9. LINE承認通知

App Review承認前: テストデータのみ処理
App Review承認後: keyword_search で第三者投稿を取得し差し替え可能
"""

import os
import re
import json
import datetime

import gspread
from google.oauth2.service_account import Credentials
import requests

from core.threads_reply_generator import (
    select_store,
    generate_reply,
    check_reply_quality,
    TACHINOMIYA_INFO,
    HINABE_INFO,
    EXCLUDE_KEYWORDS,
    NON_SEARCH_PATTERNS,
)
from core.threads_reply_publisher import publish_reply, get_dry_run_status

# ─── 設定 ──────────────────────────────────────────────
MONITOR_SHEET_NAME = "THREADS_LEAD_MONITOR"

# THREADS_MONITOR_SPREADSHEET_ID 優先。未設定時はTACHINOMIYAスプレッドシート
DEFAULT_SS_ID = "1K4KkAhFwVkQqqvzeqa25-1sR26ltBfP9gY9h-N4gXcc"

MONITOR_HEADERS = [
    "検知日時", "投稿ID", "投稿URL", "投稿者名", "投稿日時",
    "投稿本文", "検知キーワード", "関連性スコア", "推奨店舗",
    "返信案", "承認状況", "返信日時", "返信投稿ID",
    "結果", "エラー内容", "重複判定", "来店確認", "売上確認",
]

# スコア閾値
SCORE_NOTIFY  = 70   # 70点以上を通知対象
SCORE_HOLD    = 50   # 50〜69点は保留記録（通知しない）
SCORE_EXCLUDE = 49   # 49点以下は除外

# レート制限
MAX_PER_HOUR  = 3
MAX_PER_DAY   = 10

# 同一ユーザーへの返信クールダウン（日数）
USER_COOLDOWN_DAYS = 7

# 沖縄滞在中・旅行予定を示すキーワード
OKINAWA_PRESENT_KEYWORDS = [
    "旅行中", "滞在中", "今日", "今夜", "今晩", "今から", "これから",
    "明日", "今週", "来週", "今夜", "着いた", "着きました", "来ています",
    "旅行予定", "行きます", "行く予定", "計画中",
]

# 飲食店を探している指示語
SEEKING_FOOD_KEYWORDS = [
    "おすすめ", "教えて", "知りたい", "どこか", "どこですか",
    "ありますか", "探しています", "探してます", "候補", "迷っています",
    "どこ", "何食べ", "何を食べ", "行ってみたい",
]

# 那覇・国際通り周辺のキーワード
NAHA_KEYWORDS = [
    "国際通り", "那覇", "ナハ", "牧志", "栄町", "松山", "美栄橋",
    "県庁", "旭橋", "新都心",
]

# 店舗特徴一致キーワード（TACHINOMIYA + 琉球火鍋合算）
STORE_MATCH_KEYWORDS = (
    TACHINOMIYA_INFO["keywords"] + HINABE_INFO["keywords"]
)

# テスト用疑似投稿データ（20件）
TEST_POSTS = [
    # ─── 高関連（通知対象）───────────────────────────────
    {
        "id": "TEST001",
        "username": "test_user_001",
        "text": "沖縄旅行中です！国際通りでおすすめのご飯どこかありますか？夜ごはんに困ってます",
        "timestamp": (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat(),
        "permalink": "https://www.threads.net/@test_user_001/post/TEST001",
    },
    {
        "id": "TEST002",
        "username": "test_user_002",
        "text": "那覇で1人でも入りやすい居酒屋を探しています。観光客ですが気軽に入れますか？",
        "timestamp": (datetime.datetime.now() - datetime.timedelta(hours=2)).isoformat(),
        "permalink": "https://www.threads.net/@test_user_002/post/TEST002",
    },
    {
        "id": "TEST003",
        "username": "test_user_003",
        "text": "来週沖縄旅行！女子会で使える個室のお店が知りたいです。雰囲気も重視したい",
        "timestamp": (datetime.datetime.now() - datetime.timedelta(hours=3)).isoformat(),
        "permalink": "https://www.threads.net/@test_user_003/post/TEST003",
    },
    {
        "id": "TEST004",
        "username": "test_user_004",
        "text": "明日の記念日ディナー、沖縄那覇で雰囲気の良いお店を探しています。個室希望",
        "timestamp": (datetime.datetime.now() - datetime.timedelta(hours=4)).isoformat(),
        "permalink": "https://www.threads.net/@test_user_004/post/TEST004",
    },
    {
        "id": "TEST005",
        "username": "test_user_005",
        "text": "沖縄でしゃぶしゃぶか火鍋を食べたい！薬膳系も興味あります。どこかおすすめ？",
        "timestamp": (datetime.datetime.now() - datetime.timedelta(hours=5)).isoformat(),
        "permalink": "https://www.threads.net/@test_user_005/post/TEST005",
    },
    {
        "id": "TEST006",
        "username": "test_user_006",
        "text": "国際通りでサーターアンダギーが美味しいお店ってどこですか？沖縄名物食べたい！",
        "timestamp": (datetime.datetime.now() - datetime.timedelta(hours=6)).isoformat(),
        "permalink": "https://www.threads.net/@test_user_006/post/TEST006",
    },
    {
        "id": "TEST007",
        "username": "test_user_007",
        "text": "那覇国際通り周辺でランチ探してます。観光しながら気軽に入れる沖縄料理の店がいい",
        "timestamp": (datetime.datetime.now() - datetime.timedelta(hours=7)).isoformat(),
        "permalink": "https://www.threads.net/@test_user_007/post/TEST007",
    },
    {
        "id": "TEST008",
        "username": "test_user_008",
        "text": "沖縄旅行中。夜は友達と飲みたい。国際通り近くでカジュアルに飲めるBAR教えてください",
        "timestamp": (datetime.datetime.now() - datetime.timedelta(hours=8)).isoformat(),
        "permalink": "https://www.threads.net/@test_user_008/post/TEST008",
    },
    {
        "id": "TEST009",
        "username": "test_user_009",
        "text": "那覇で記念日に使いたいお店を探しています。落ち着いた雰囲気で美味しいお肉が食べたい",
        "timestamp": (datetime.datetime.now() - datetime.timedelta(hours=9)).isoformat(),
        "permalink": "https://www.threads.net/@test_user_009/post/TEST009",
    },
    {
        "id": "TEST010",
        "username": "test_user_010",
        "text": "沖縄でアグー豚のしゃぶしゃぶが食べられるお店ってありますか？旅行で来ています",
        "timestamp": (datetime.datetime.now() - datetime.timedelta(hours=10)).isoformat(),
        "permalink": "https://www.threads.net/@test_user_010/post/TEST010",
    },
    {
        "id": "TEST011",
        "username": "test_user_011",
        "text": "沖縄何食べる？明日那覇に着くので夜ごはんの場所を事前に決めたい",
        "timestamp": (datetime.datetime.now() - datetime.timedelta(hours=11)).isoformat(),
        "permalink": "https://www.threads.net/@test_user_011/post/TEST011",
    },
    {
        "id": "TEST012",
        "username": "test_user_012",
        "text": "黒毛和牛が食べられる沖縄那覇のお店を探しています。会食で使える雰囲気のいいところ",
        "timestamp": (datetime.datetime.now() - datetime.timedelta(hours=12)).isoformat(),
        "permalink": "https://www.threads.net/@test_user_012/post/TEST012",
    },
    # ─── 中程度スコア（保留）────────────────────────────────
    {
        "id": "TEST013",
        "username": "test_user_013",
        "text": "今度沖縄旅行を計画しています。どんなグルメが有名？教えてください",
        "timestamp": (datetime.datetime.now() - datetime.timedelta(hours=13)).isoformat(),
        "permalink": "https://www.threads.net/@test_user_013/post/TEST013",
    },
    {
        "id": "TEST014",
        "username": "test_user_014",
        "text": "沖縄の居酒屋っていろいろあるよね。どんな感じなんだろう",
        "timestamp": (datetime.datetime.now() - datetime.timedelta(hours=14)).isoformat(),
        "permalink": "https://www.threads.net/@test_user_014/post/TEST014",
    },
    # ─── 除外対象 ──────────────────────────────────────────
    {
        "id": "TEST015",
        "username": "test_user_015",
        "text": "沖縄旅行が終わりました！食べたものを振り返ります。ゴーヤチャンプルーが最高でした",
        "timestamp": (datetime.datetime.now() - datetime.timedelta(hours=15)).isoformat(),
        "permalink": "https://www.threads.net/@test_user_015/post/TEST015",
    },
    {
        "id": "TEST016",
        "username": "test_user_016",
        "text": "沖縄そばのレシピを教えてください。自炊で作りたい",
        "timestamp": (datetime.datetime.now() - datetime.timedelta(hours=16)).isoformat(),
        "permalink": "https://www.threads.net/@test_user_016/post/TEST016",
    },
    {
        "id": "TEST017",
        "username": "test_user_017",
        "text": "沖縄グルメの通販でおすすめはありますか？自宅で食べたい",
        "timestamp": (datetime.datetime.now() - datetime.timedelta(hours=17)).isoformat(),
        "permalink": "https://www.threads.net/@test_user_017/post/TEST017",
    },
    {
        "id": "TEST018",
        "username": "test_user_018",
        "text": "沖縄の飲食店スタッフを募集しています。経験者優遇。詳細はDMへ",
        "timestamp": (datetime.datetime.now() - datetime.timedelta(hours=18)).isoformat(),
        "permalink": "https://www.threads.net/@test_user_018/post/TEST018",
    },
    {
        "id": "TEST019",
        "username": "test_user_019",
        "text": "当店の沖縄料理レストランをよろしくお願いします！国際通りにあります！ぜひ来てね！",
        "timestamp": (datetime.datetime.now() - datetime.timedelta(hours=19)).isoformat(),
        "permalink": "https://www.threads.net/@test_user_019/post/TEST019",
    },
    {
        "id": "TEST020",
        "username": "test_user_020",
        "text": "沖縄料理って美味しいよね。チャンプルーとかゴーヤとか好き",
        "timestamp": (datetime.datetime.now() - datetime.timedelta(hours=20)).isoformat(),
        "permalink": "https://www.threads.net/@test_user_020/post/TEST020",
    },
]


# ─────────────────────────────────────────────────────────
# Google Sheets 操作
# ─────────────────────────────────────────────────────────

def _get_gc(creds_path: str) -> gspread.Client:
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds)


def _ensure_monitor_sheet(ss: gspread.Spreadsheet) -> gspread.Worksheet:
    """THREADS_LEAD_MONITOR シートを取得、なければ作成"""
    try:
        ws = ss.worksheet(MONITOR_SHEET_NAME)
        # ヘッダー確認・不足列を追加
        existing = ws.row_values(1)
        missing = [h for h in MONITOR_HEADERS if h not in existing]
        if missing:
            for h in missing:
                ws.add_cols(1)
                col = len(ws.row_values(1)) + 1
                ws.update_cell(1, col, h)
        return ws
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=MONITOR_SHEET_NAME, rows=1000, cols=len(MONITOR_HEADERS))
        ws.update([MONITOR_HEADERS], "A1")
        # ヘッダー行を太字・背景色
        try:
            ws.format("A1:R1", {
                "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.6},
                "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
            })
        except Exception:
            pass
        return ws


def _load_history(ws: gspread.Worksheet) -> list[dict]:
    """既存の全レコードをロード（重複チェック用）"""
    try:
        records = ws.get_all_records(expected_headers=MONITOR_HEADERS)
        return records
    except Exception:
        return []


def _save_lead(ws: gspread.Worksheet, row: dict) -> None:
    """新規候補を末尾行に追記"""
    values = [str(row.get(h, "")) for h in MONITOR_HEADERS]
    ws.append_row(values, value_input_option="USER_ENTERED")


def _update_status(ws: gspread.Worksheet, post_id: str, updates: dict) -> bool:
    """投稿IDで行を特定してステータスを更新"""
    try:
        records = ws.get_all_records(expected_headers=MONITOR_HEADERS)
        for i, rec in enumerate(records):
            if str(rec.get("投稿ID", "")) == str(post_id):
                row_num = i + 2  # ヘッダー行分+1
                for col_name, val in updates.items():
                    if col_name in MONITOR_HEADERS:
                        col_idx = MONITOR_HEADERS.index(col_name) + 1
                        ws.update_cell(row_num, col_idx, str(val))
                return True
        return False
    except Exception:
        return False


# ─────────────────────────────────────────────────────────
# スコアリング・フィルタリング
# ─────────────────────────────────────────────────────────

def _has_exclude_keyword(text: str) -> tuple[bool, str]:
    """除外キーワードが含まれているか確認"""
    for kw in EXCLUDE_KEYWORDS:
        if kw in text:
            return True, kw
    return False, ""


def _is_non_search(text: str) -> bool:
    """飲食店を探していない投稿（単なる感想・宣伝）を検知"""
    for p in NON_SEARCH_PATTERNS:
        if re.search(p, text):
            return True
    return False


def _kw_match(text: str, keywords: list[str]) -> int:
    t = text.lower()
    return sum(1 for kw in keywords if kw.lower() in t)


def score_post(post: dict) -> dict:
    """
    投稿の関連性スコアを計算する（100点満点）。

    戻り値:
      {"score": 85, "breakdown": {...}, "keywords_matched": [...]}
    """
    text = post.get("text", "")
    ts = post.get("timestamp", "")
    breakdown = {}
    matched_keywords = []

    # ① 沖縄滞在中または旅行予定（25点）
    present_matches = [kw for kw in OKINAWA_PRESENT_KEYWORDS if kw in text]
    if present_matches:
        breakdown["滞在/旅行予定"] = 25
        matched_keywords.extend(present_matches[:3])
    else:
        breakdown["滞在/旅行予定"] = 0

    # ② 飲食店を探している（25点）
    seek_matches = [kw for kw in SEEKING_FOOD_KEYWORDS if kw in text]
    if seek_matches:
        breakdown["飲食探索意向"] = 25
        matched_keywords.extend(seek_matches[:2])
    else:
        breakdown["飲食探索意向"] = 0

    # ③ 那覇・国際通り周辺（20点）
    naha_matches = [kw for kw in NAHA_KEYWORDS if kw in text]
    if naha_matches:
        breakdown["那覇周辺"] = 20
        matched_keywords.extend(naha_matches[:2])
    else:
        breakdown["那覇周辺"] = 0

    # ④ 店舗特徴と一致（20点）
    store_matches = [kw for kw in STORE_MATCH_KEYWORDS if kw in text]
    if len(store_matches) >= 2:
        breakdown["店舗マッチ"] = 20
        matched_keywords.extend(store_matches[:3])
    elif len(store_matches) == 1:
        breakdown["店舗マッチ"] = 10
        matched_keywords.extend(store_matches)
    else:
        breakdown["店舗マッチ"] = 0

    # ⑤ 投稿が24時間以内（10点）
    try:
        post_dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        post_dt = post_dt.replace(tzinfo=None)
        age_hours = (datetime.datetime.now() - post_dt).total_seconds() / 3600
        if age_hours <= 24:
            breakdown["投稿新鮮度"] = 10
        else:
            breakdown["投稿新鮮度"] = 0
    except Exception:
        breakdown["投稿新鮮度"] = 5  # 取得不能時は中間値

    total = sum(breakdown.values())
    return {
        "score": total,
        "breakdown": breakdown,
        "keywords_matched": list(dict.fromkeys(matched_keywords)),  # 重複除去
    }


def should_exclude(post: dict) -> tuple[bool, str]:
    """
    除外すべき投稿かどうかを判定する。

    戻り値: (除外すべきか, 除外理由)
    """
    text = post.get("text", "")

    # 除外キーワード
    has_ex, ex_kw = _has_exclude_keyword(text)
    if has_ex:
        return True, f"除外キーワード: {ex_kw}"

    # 非検索投稿（単なる感想・宣伝）
    if _is_non_search(text):
        return True, "飲食店を探していない投稿（感想/宣伝）"

    # 沖縄に全く関係ない
    okinawa_related = ["沖縄", "那覇", "国際通り", "ナハ", "琉球", "オキナワ"]
    if not any(kw in text for kw in okinawa_related):
        return True, "沖縄関連キーワードなし"

    return False, ""


# ─────────────────────────────────────────────────────────
# 重複・レート制限チェック
# ─────────────────────────────────────────────────────────

def _is_duplicate_post(post_id: str, history: list[dict]) -> bool:
    """同一投稿IDへの処理済みチェック"""
    return any(str(r.get("投稿ID", "")) == str(post_id) for r in history)


def _is_user_in_cooldown(username: str, history: list[dict]) -> bool:
    """同一ユーザーへの7日以内返信チェック"""
    now = datetime.datetime.now()
    cutoff = now - datetime.timedelta(days=USER_COOLDOWN_DAYS)
    for r in history:
        if str(r.get("投稿者名", "")) != username:
            continue
        status = str(r.get("承認状況", ""))
        if status not in ("承認", "返信済み"):
            continue
        try:
            dt = datetime.datetime.strptime(str(r.get("検知日時", ""))[:19], "%Y-%m-%d %H:%M:%S")
            if dt > cutoff:
                return True
        except Exception:
            pass
    return False


def _check_rate_limits(history: list[dict]) -> tuple[bool, str]:
    """1時間3件・1日10件のレート制限チェック"""
    now = datetime.datetime.now()
    hour_ago = now - datetime.timedelta(hours=1)
    day_ago  = now - datetime.timedelta(days=1)

    hour_count = 0
    day_count  = 0

    for r in history:
        status = str(r.get("承認状況", ""))
        if status not in ("承認待ち", "承認", "返信済み"):
            continue
        try:
            dt = datetime.datetime.strptime(str(r.get("検知日時", ""))[:19], "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
        if dt > hour_ago:
            hour_count += 1
        if dt > day_ago:
            day_count += 1

    if hour_count >= MAX_PER_HOUR:
        return False, f"1時間レート超過({hour_count}/{MAX_PER_HOUR}件)"
    if day_count >= MAX_PER_DAY:
        return False, f"1日レート超過({day_count}/{MAX_PER_DAY}件)"
    return True, ""


# ─────────────────────────────────────────────────────────
# LINE 通知
# ─────────────────────────────────────────────────────────

def _send_line_notification(token: str, message: str) -> bool:
    if not token:
        return False
    try:
        resp = requests.post(
            "https://api.line.me/v2/bot/message/broadcast",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"messages": [{"type": "text", "text": message}]},
            timeout=10,
        )
        return resp.ok
    except Exception:
        return False


def _build_line_message(post: dict, score: int, stores: list[str], reply: str) -> str:
    store_names = []
    for s in stores:
        store_names.append(TACHINOMIYA_INFO["name"] if s == "tachinomiya" else HINABE_INFO["name"])

    ts = post.get("timestamp", "")[:19].replace("T", " ")
    text_preview = post["text"][:100] + ("..." if len(post["text"]) > 100 else "")

    return (
        f"【Threads来店候補】\n\n"
        f"投稿者：@{post.get('username', '')}\n"
        f"投稿日時：{ts}\n"
        f"投稿URL：{post.get('permalink', '')}\n\n"
        f"投稿本文：\n{text_preview}\n\n"
        f"関連性スコア：{score}点\n"
        f"推奨店舗：{' / '.join(store_names)}\n\n"
        f"返信案：\n{reply}\n\n"
        f"─────────────────\n"
        f"承認方法：THREADS_LEAD_MONITOR シートの\n「承認状況」列を「承認」に変更してください\n"
        f"（見送りは「見送り」と入力）"
    )


# ─────────────────────────────────────────────────────────
# メイン処理
# ─────────────────────────────────────────────────────────

def process_posts(
    posts: list[dict],
    creds_path: str,
    openai_key: str = "",
    line_token_tachinomiya: str = "",
    line_token_hinabe: str = "",
    spreadsheet_id: str = "",
) -> dict:
    """
    投稿リストを処理してスコアリング・返信案生成・シート記録・LINE通知を行う。
    """
    ss_id = spreadsheet_id or os.getenv("THREADS_MONITOR_SPREADSHEET_ID", DEFAULT_SS_ID)
    oai_key = openai_key or os.getenv("OPENAI_API_KEY", "")
    tok_t = line_token_tachinomiya or os.getenv("LINE_TACHINOMIYASTAFF_TOKEN", "")
    tok_h = line_token_hinabe or os.getenv("LINE_hinabeSTAFF_TOKEN", "")

    gc = _get_gc(creds_path)
    ss = gc.open_by_key(ss_id)
    ws = _ensure_monitor_sheet(ss)
    history = _load_history(ws)

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    results = {
        "processed": 0,
        "notified": 0,
        "held": 0,
        "excluded": 0,
        "duplicated": 0,
        "rate_limited": 0,
        "details": [],
    }

    for post in posts:
        post_id = str(post.get("id", ""))
        username = str(post.get("username", ""))
        text = post.get("text", "")
        detail = {"id": post_id, "username": username, "text": text[:50]}

        # 除外チェック
        is_ex, ex_reason = should_exclude(post)
        if is_ex:
            detail.update({"status": "除外", "reason": ex_reason})
            results["excluded"] += 1
            results["details"].append(detail)
            continue

        # スコア計算
        score_result = score_post(post)
        score = score_result["score"]
        keywords = ",".join(score_result["keywords_matched"])

        detail["score"] = score

        if score < SCORE_HOLD:
            detail.update({"status": "除外", "reason": f"スコア不足({score}点)"})
            results["excluded"] += 1
            results["details"].append(detail)
            continue

        # 重複チェック
        if _is_duplicate_post(post_id, history):
            detail.update({"status": "重複", "reason": "処理済み投稿ID"})
            results["duplicated"] += 1
            results["details"].append(detail)
            continue

        if score >= SCORE_NOTIFY and _is_user_in_cooldown(username, history):
            detail.update({"status": "重複", "reason": f"7日クールダウン中: @{username}"})
            results["duplicated"] += 1
            results["details"].append(detail)
            continue

        # レート制限（通知対象のみ）
        if score >= SCORE_NOTIFY:
            rate_ok, rate_msg = _check_rate_limits(history)
            if not rate_ok:
                detail.update({"status": "レート制限", "reason": rate_msg})
                results["rate_limited"] += 1
                results["details"].append(detail)
                continue

        # 店舗選択
        store_result = select_store(text)
        stores = store_result["stores"]
        store_names = [
            TACHINOMIYA_INFO["name"] if s == "tachinomiya" else HINABE_INFO["name"]
            for s in stores
        ]

        # 返信案生成
        reply = generate_reply(text, stores, oai_key) if stores else ""
        quality = check_reply_quality(reply) if reply else {"ok": False, "issues": ["店舗未選択"]}

        # 承認状況の初期値
        initial_status = "承認待ち" if score >= SCORE_NOTIFY else "保留"

        # シート記録
        row_data = {
            "検知日時": now_str,
            "投稿ID": post_id,
            "投稿URL": post.get("permalink", ""),
            "投稿者名": f"@{username}",
            "投稿日時": post.get("timestamp", "")[:19].replace("T", " "),
            "投稿本文": text,
            "検知キーワード": keywords,
            "関連性スコア": str(score),
            "推奨店舗": " / ".join(store_names),
            "返信案": reply,
            "承認状況": initial_status,
            "返信日時": "",
            "返信投稿ID": "",
            "結果": "",
            "エラー内容": "" if quality["ok"] else f"品質警告: {', '.join(quality['issues'])}",
            "重複判定": "新規",
            "来店確認": "",
            "売上確認": "",
        }
        _save_lead(ws, row_data)
        history.append(row_data)  # インメモリ履歴を更新

        results["processed"] += 1

        # LINE通知（通知対象スコアのみ）
        if score >= SCORE_NOTIFY and reply:
            line_message = _build_line_message(post, score, stores, reply)
            notified = False
            if "tachinomiya" in stores and tok_t:
                ok = _send_line_notification(tok_t, line_message)
                if ok:
                    notified = True
            if "hinabe" in stores and tok_h:
                ok = _send_line_notification(tok_h, line_message)
                if ok:
                    notified = True
            if notified:
                results["notified"] += 1
                detail["line_sent"] = True
            else:
                detail["line_sent"] = False
                detail["line_note"] = "LINEトークン未設定またはエラー"

            detail.update({"status": "承認待ち", "stores": store_names, "score": score})
        else:
            results["held"] += 1
            detail.update({"status": "保留", "score": score})

        results["details"].append(detail)

    return {
        "ok": True,
        "summary": results,
        "spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{ss_id}",
        "dry_run_status": get_dry_run_status(),
    }


def run_test(creds_path: str, openai_key: str = "") -> dict:
    """テストデータ20件で処理フルフローを実行"""
    print(f"[THREADS_MONITOR] テストデータ {len(TEST_POSTS)} 件を処理します")
    return process_posts(
        posts=TEST_POSTS,
        creds_path=creds_path,
        openai_key=openai_key,
    )


def run(
    posts: list[dict] | None = None,
    creds_path: str = "",
    openai_key: str = "",
    spreadsheet_id: str = "",
) -> dict:
    """
    メインエントリポイント。

    posts=None の場合はテストデータで実行。
    App Review承認後は posts に実際のThreads APIレスポンスを渡す。
    """
    if posts is None:
        return run_test(creds_path, openai_key)
    return process_posts(
        posts=posts,
        creds_path=creds_path,
        openai_key=openai_key,
        spreadsheet_id=spreadsheet_id,
    )
