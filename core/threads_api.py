"""
Threads 公式API 連携（OAuth・投稿・インサイト自動取得）
--------------------------------------------------------
目的: 各事業のThreadsアカウントをOAuthで連携し、
  ・投稿の自動公開（任意）
  ・全投稿のインサイト（表示/いいね/返信/リポスト等）を自動取得 → SNS_RESULT
を実現する。手動投稿した分もアカウント連携だけで自動集計できる。

認証: OAuth 2.0（パスワード不使用）。アクセストークンは THREADS_ACCOUNTS シートに保存。
コスト: Threads APIは無料。OpenAI不使用。

必要な環境変数:
  THREADS_APP_ID      … Meta DeveloperアプリのID
  THREADS_APP_SECRET  … アプリシークレット（秘密）
  THREADS_REDIRECT_URI… OAuthコールバックURL（既定: <cloud-run>/threads-oauth-callback）
"""

import os
import time
from datetime import datetime, timezone, timedelta

import requests
import gspread
from google.oauth2.service_account import Credentials

JST = timezone(timedelta(hours=9))
GRAPH = "https://graph.threads.net"
# Threadsはwww.threads.comへ移行。threads.netは301されモバイルアプリが横取りするため直URLを使用
AUTH_BASE = "https://www.threads.com/oauth/authorize"
SCOPES = "threads_basic,threads_content_publish,threads_manage_insights"

# 事業キー → 表示名（SNS_RESULTのbusiness_nameに使用）
BIZ_NAME = {
    "tachinomiya": "TACHINOMIYA", "beauty": "Tree Beauty",
    "catering": "TREE's Catering", "ryukyu_hinabe": "琉球火鍋",
    "pasta_pasta": "パスタパスタ", "z1": "Z1",
}
_NAME_TO_KEY = {v: k for k, v in BIZ_NAME.items()}

# 連携を許可する事業（段階展開）
ALLOWED_BIZ = {"ryukyu_hinabe", "catering", "tachinomiya", "beauty"}

# キーのエイリアス（外部から渡される別名 → 正規キー）
_ALIASES = {"trees_catering": "catering", "trees catering": "catering"}

# PHASE11: business_key ごとの想定username（誤連携・上書き防止の安全チェック）
EXPECTED_USERNAME = {
    "ryukyu_hinabe": "ryukyuhinabe",
    "catering": "trees_catering_",
    "tachinomiya": "tachinomiya.okinawa",
    "beauty": "tree.beauty_okinawa",
}

TEST_POST_MEMO = "Threads APIテスト投稿"


def _canonical_key(s: str) -> str:
    """別名・表示名・キーを正規の事業キーに変換（許可チェックなし）"""
    s = (s or "").strip()
    low = s.lower()
    if low in _ALIASES:
        return _ALIASES[low]
    if s in BIZ_NAME:
        return s
    if s in _NAME_TO_KEY:
        return _NAME_TO_KEY[s]
    return s


def _test_text(biz_name: str) -> str:
    return f"API接続テスト投稿です。\n{biz_name}のSNS管理システム連携テスト中です。"


def resolve_biz(business_name: str):
    """business_name（表示名/キー/別名）→ 正規事業キー。許可外/不明は ("", error)"""
    key = _canonical_key(business_name)
    if not key or key not in BIZ_NAME:
        return "", f"不明な事業: {business_name}"
    if key not in ALLOWED_BIZ:
        return "", f"{BIZ_NAME.get(key, key)} はThreads連携未対応です（対応中: {'・'.join(BIZ_NAME[k] for k in ALLOWED_BIZ)}）"
    return key, ""


THREADS_ACCOUNTS_SHEET = "THREADS_ACCOUNT_CONFIG"
THREADS_ACCOUNTS_HEADER = [
    "事業キー", "事業名", "threads_user_id", "username",
    "access_token", "token_type", "expires_at", "connected_at", "last_sync", "メモ",
]

SNS_RESULT_HEADER = [
    "post_id", "business_name", "platform", "posted_date", "impressions",
    "likes", "comments", "shares", "saves", "profile_access", "line_add",
    "dm_count", "reservation_count", "inquiry_count", "visit_count",
    "sales_amount", "related_screenshot_id", "manual_note",
]
SNS_POST_STOCK_HEADER = [
    "post_id", "business_name", "platform", "post_no", "original_text",
    "current_text", "post_type", "target_stage", "customer_pain", "hook_text",
    "cta", "status", "scheduled_date", "posted_date", "posted_url",
    "rewrite_version", "memo", "image_url",
]


def _now(): return datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
def _date(): return datetime.now(JST).strftime("%Y-%m-%d")


def _gc(creds_path):
    creds = Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/spreadsheets",
                            "https://www.googleapis.com/auth/drive"])
    return gspread.authorize(creds)


def _sheet(ss, title, header):
    try:
        return ss.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=title, rows=1000, cols=max(len(header), 10))
        ws.update(values=[header], range_name="A1")
        ws.format("A1:Z1", {"backgroundColor": {"red": 0.0, "green": 0.1, "blue": 0.2},
                            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}}})
        return ws


def _infer_type(text: str) -> str:
    t = str(text)
    if any(k in t for k in ["予約", "問い合わせ", "限定", "クーポン", "本日", "席", "来店", "注文"]):
        return "C"
    if any(k in t for k in ["プロフィール", "LINE", "フォロー", "DM", "リンク", "詳細"]):
        return "B"
    return "A"


# ── 設定取得 ──────────────────────────────────────────────

def _app_id(): return os.getenv("THREADS_APP_ID", "")
def _app_secret(): return os.getenv("THREADS_APP_SECRET", "")
def _redirect_uri():
    return os.getenv("THREADS_REDIRECT_URI",
                     "https://yu-holdings-ai-qpiiccdspa-an.a.run.app/threads-oauth/callback")


def is_configured() -> bool:
    return bool(_app_id() and _app_secret())


# ── OAuth ─────────────────────────────────────────────────

def authorize_url(business_key: str) -> str:
    """ユーザーがクリックして認可する画面のURL（stateに事業キーを載せる）"""
    from urllib.parse import urlencode
    q = {
        "client_id": _app_id(),
        "redirect_uri": _redirect_uri(),
        "scope": SCOPES,
        "response_type": "code",
        "state": business_key,
    }
    return f"{AUTH_BASE}?{urlencode(q)}"


def handle_callback(spreadsheet_id: str, creds_path: str, code: str, state: str) -> dict:
    """コールバック: code→短期トークン→長期トークン→プロフィール→保存"""
    if not is_configured():
        return {"ok": False, "error": "THREADS_APP_ID / THREADS_APP_SECRET 未設定"}
    biz_key = _canonical_key(state) or state
    # 1) 短期トークン
    r = requests.post(f"{GRAPH}/oauth/access_token", data={
        "client_id": _app_id(), "client_secret": _app_secret(),
        "grant_type": "authorization_code", "redirect_uri": _redirect_uri(), "code": code,
    }, timeout=20)
    if not r.ok:
        return {"ok": False, "error": f"短期トークン取得失敗: {r.text[:200]}"}
    short = r.json().get("access_token", "")
    user_id = str(r.json().get("user_id", ""))
    # 2) 長期トークン（60日）
    r2 = requests.get(f"{GRAPH}/access_token", params={
        "grant_type": "th_exchange_token", "client_secret": _app_secret(), "access_token": short,
    }, timeout=20)
    if not r2.ok:
        return {"ok": False, "error": f"長期トークン取得失敗: {r2.text[:200]}"}
    long_token = r2.json().get("access_token", "")
    expires_in = int(r2.json().get("expires_in", 5184000))
    expires_at = (datetime.now(JST) + timedelta(seconds=expires_in)).strftime("%Y-%m-%d")
    # 3) プロフィール
    username = ""
    try:
        pr = requests.get(f"{GRAPH}/v1.0/me", params={
            "fields": "id,username", "access_token": long_token}, timeout=15)
        if pr.ok:
            username = pr.json().get("username", "")
            user_id = str(pr.json().get("id", user_id))
    except Exception:
        pass
    # 3.5) PHASE11 安全チェック: 想定usernameと一致しなければ保存拒否（既存トークンは温存）
    expected = EXPECTED_USERNAME.get(biz_key)
    if expected and username and username != expected:
        _log_system_error(spreadsheet_id, creds_path, "threads_username_mismatch",
                          f"state={state} biz_key={biz_key} 想定=@{expected} 実際=@{username} → 保存拒否")
        return {"ok": False, "rejected": True, "business_key": biz_key,
                "error": (f"連携先アカウントが想定と異なります（@{username}）。"
                          f"{BIZ_NAME.get(biz_key, biz_key)}は @{expected} で再認可してください。"
                          "既存の連携は保持しています。")}
    # 4) 保存
    _save_account(spreadsheet_id, creds_path, biz_key, user_id, username,
                  long_token, expires_at)
    return {"ok": True, "business_key": biz_key, "username": username,
            "user_id": user_id[:6] + "****", "expires_at": expires_at}


def _log_system_error(ss_id, creds_path, etype, detail):
    """SYSTEM_ERROR_LOG へ異常を記録 + Knowledge OS へ異常保存（オーナー確認用）"""
    try:
        gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
        ws = _sheet(ss, "SYSTEM_ERROR_LOG", ["発生日時", "種別", "詳細", "対応状況"])
        ws.append_row([_now(), etype, detail, "未対応"], value_input_option="RAW")
    except Exception:
        pass
    try:  # Knowledge OS へ異常として保存（オーナー確認対象）
        from core.cash_flow import _upload_md_gcs, GCS_PREFIX
        ts = _now().replace(":", "").replace(" ", "_").replace("-", "")
        md = (f"---\ntitle: Threads連携 異常\ncategory: system_error\ndate: {_date()}\n"
              f"status: needs_owner_review\n---\n\n# ⚠️ {etype}\n\n発生: {_now()}\n\n{detail}\n\n"
              "**オーナー確認対象。正しいアカウントで再認可してください。**\n")
        _upload_md_gcs(creds_path, f"{GCS_PREFIX}/09_System_Errors/threads_error_{ts}.md", md)
    except Exception:
        pass


def _save_account(ss_id, creds_path, biz_key, user_id, username, token, expires_at):
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    ws = _sheet(ss, THREADS_ACCOUNTS_SHEET, THREADS_ACCOUNTS_HEADER)
    biz_name = BIZ_NAME.get(biz_key, biz_key)
    row = [biz_key, biz_name, user_id, username, token, "long_lived",
           expires_at, _now(), "", ""]
    recs = ws.get_all_values()
    for i, r in enumerate(recs[1:], start=2):
        if r and r[0] == biz_key:
            ws.update(values=[row], range_name=f"A{i}:J{i}", value_input_option="RAW")
            return
    ws.append_row(row, value_input_option="RAW")


def get_account(ss_id, creds_path, biz_key) -> dict:
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    try:
        ws = ss.worksheet(THREADS_ACCOUNTS_SHEET)
    except gspread.WorksheetNotFound:
        return {}
    for r in ws.get_all_records():
        if str(r.get("事業キー")) == biz_key:
            return r
    return {}


def refresh_token(ss_id, creds_path, biz_key) -> dict:
    """長期トークンをリフレッシュ（60日延長）"""
    acc = get_account(ss_id, creds_path, biz_key)
    tok = acc.get("access_token", "")
    if not tok:
        return {"ok": False, "error": "未連携"}
    r = requests.get(f"{GRAPH}/refresh_access_token", params={
        "grant_type": "th_refresh_token", "access_token": tok}, timeout=20)
    if not r.ok:
        return {"ok": False, "error": r.text[:200]}
    new = r.json().get("access_token", tok)
    exp_in = int(r.json().get("expires_in", 5184000))
    exp_at = (datetime.now(JST) + timedelta(seconds=exp_in)).strftime("%Y-%m-%d")
    _save_account(ss_id, creds_path, biz_key, acc.get("threads_user_id", ""),
                  acc.get("username", ""), new, exp_at)
    return {"ok": True, "expires_at": exp_at}


# ── アカウント情報 / 投稿一覧 ─────────────────────────────

def get_user(ss_id, creds_path, biz_key) -> dict:
    """連携アカウントのプロフィールを取得（/me）"""
    acc = get_account(ss_id, creds_path, biz_key)
    tok = acc.get("access_token", "")
    if not tok:
        return {"ok": False, "error": "未連携"}
    r = requests.get(f"{GRAPH}/v1.0/me", params={
        "fields": "id,username,threads_profile_picture_url,threads_biography",
        "access_token": tok}, timeout=15)
    if not r.ok:
        return {"ok": False, "error": r.text[:200]}
    d = r.json()
    return {"ok": True, "user_id": str(d.get("id", "")), "username": d.get("username", ""),
            "biography": d.get("threads_biography", "")}


def get_posts(ss_id, creds_path, biz_key, limit=10) -> dict:
    """連携アカウントの最近の投稿一覧"""
    acc = get_account(ss_id, creds_path, biz_key)
    tok = acc.get("access_token", "")
    uid = acc.get("threads_user_id", "")
    if not tok:
        return {"ok": False, "error": "未連携"}
    r = requests.get(f"{GRAPH}/v1.0/{uid}/threads", params={
        "fields": "id,text,permalink,timestamp,media_type",
        "limit": limit, "access_token": tok}, timeout=20)
    if not r.ok:
        return {"ok": False, "error": r.text[:200]}
    posts = [{"id": p.get("id"), "text": (p.get("text", "") or "")[:60],
              "permalink": p.get("permalink", ""), "timestamp": p.get("timestamp", "")}
             for p in r.json().get("data", [])]
    return {"ok": True, "count": len(posts), "posts": posts}


# ── 連携テスト投稿（1件・dry_run・二重投稿防止） ─────────

def _already_test_posted(ss, biz_name) -> bool:
    """SNS_POST_STOCKにテスト投稿(投稿済)が既にあるか"""
    try:
        ws = ss.worksheet("SNS_POST_STOCK")
    except gspread.WorksheetNotFound:
        return False
    for r in ws.get_all_records():
        if (str(r.get("business_name")) == biz_name
                and TEST_POST_MEMO in str(r.get("memo", ""))
                and str(r.get("status")) == "投稿済み"):
            return True
    return False


def publish_test(ss_id, creds_path, biz_key, dry_run=True) -> dict:
    """
    固定文の連携テスト投稿を1件だけ公開。
    dry_run=True: 投稿せず内容プレビュー。dry_run=False: 1件投稿。
    二重投稿防止: 既にテスト投稿済みなら拒否。元投稿は上書きしない（追記のみ）。
    """
    acc = get_account(ss_id, creds_path, biz_key)
    tok = acc.get("access_token", "")
    if not tok:
        return {"ok": False, "error": "未連携（先にOAuth連携してください）"}
    biz_name = acc.get("事業名") or BIZ_NAME.get(biz_key, biz_key)

    test_text = _test_text(biz_name)
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    if _already_test_posted(ss, biz_name):
        return {"ok": False, "already_posted": True,
                "message": "テスト投稿は既に実施済みです（二重投稿防止）。"}

    if dry_run:
        return {"ok": True, "dry_run": True, "preview_text": test_text,
                "will_post_to": f"@{acc.get('username','')}", "business": biz_name,
                "note": "dry_run=false で実際に1件投稿します"}

    # 実投稿
    res = publish_text(ss_id, creds_path, biz_key, test_text)
    if not res.get("ok"):
        return res
    media_id = res.get("media_id", "")
    permalink = ""
    try:
        pr = requests.get(f"{GRAPH}/v1.0/{media_id}", params={
            "fields": "permalink", "access_token": tok}, timeout=15)
        if pr.ok:
            permalink = pr.json().get("permalink", "")
    except Exception:
        pass

    # SNS_POST_STOCK へ追記（元投稿は上書きしない・新規行）
    sw = _sheet(ss, "SNS_POST_STOCK", SNS_POST_STOCK_HEADER)
    sw.append_row([media_id, biz_name, "Threads投稿", "", test_text, test_text,
                   "A", "", "", test_text.splitlines()[0][:50], "", "投稿済み",
                   "", _date(), permalink, 0, TEST_POST_MEMO], value_input_option="RAW")
    # SNS_RESULT へ記録
    rw = _sheet(ss, "SNS_RESULT", SNS_RESULT_HEADER)
    rw.append_row([media_id, biz_name, "Threads投稿", _date(), "", "", "", "", "", "",
                   "", "", "", "", "", "", permalink, TEST_POST_MEMO],
                  value_input_option="RAW")
    # THREADS_ACCOUNT_CONFIG にメモ更新
    try:
        aws = ss.worksheet(THREADS_ACCOUNTS_SHEET)
        for i, r0 in enumerate(aws.get_all_values()[1:], start=2):
            if r0 and r0[0] == biz_key:
                aws.update_cell(i, THREADS_ACCOUNTS_HEADER.index("メモ") + 1,
                                f"テスト投稿済 {media_id} {_now()}")
                break
    except Exception:
        pass

    return {"ok": True, "dry_run": False, "media_id": media_id, "permalink": permalink,
            "business": biz_name, "recorded": ["SNS_POST_STOCK", "SNS_RESULT", "THREADS_ACCOUNT_CONFIG"]}


# ── 投稿公開（汎用・内部） ────────────────────────────────

def publish_text(ss_id, creds_path, biz_key, text: str) -> dict:
    """テキスト投稿を公開（2ステップ）"""
    acc = get_account(ss_id, creds_path, biz_key)
    tok = acc.get("access_token", "")
    uid = acc.get("threads_user_id", "")
    if not tok:
        return {"ok": False, "error": "未連携"}
    # 1) コンテナ作成
    c = requests.post(f"{GRAPH}/v1.0/{uid}/threads", data={
        "media_type": "TEXT", "text": text, "access_token": tok}, timeout=20)
    if not c.ok:
        return {"ok": False, "error": f"作成失敗: {c.text[:200]}"}
    cid = c.json().get("id", "")
    time.sleep(2)
    # 2) 公開
    p = requests.post(f"{GRAPH}/v1.0/{uid}/threads_publish", data={
        "creation_id": cid, "access_token": tok}, timeout=20)
    if not p.ok:
        return {"ok": False, "error": f"公開失敗: {p.text[:200]}"}
    media_id = p.json().get("id", "")
    return {"ok": True, "media_id": media_id, "text": text[:40]}


def publish_image(ss_id, creds_path, biz_key, text, image_url):
    """画像付き投稿を公開（media_type=IMAGE）。username安全チェック＋コンテナ処理待ち。"""
    acc = get_account(ss_id, creds_path, biz_key)
    tok = acc.get("access_token", "")
    uid = acc.get("threads_user_id", "")
    if not tok:
        return {"ok": False, "error": "未連携"}
    # username安全チェック（誤投稿防止）
    expected = EXPECTED_USERNAME.get(biz_key)
    if expected and acc.get("username") and acc.get("username") != expected:
        return {"ok": False, "error": f"username不一致(@{acc.get('username')}≠@{expected})。投稿中止"}
    if not str(image_url).startswith("https://"):
        return {"ok": False, "error": "公開HTTPS画像URLが必要"}
    # 1) コンテナ作成（IMAGE）
    c = requests.post(f"{GRAPH}/v1.0/{uid}/threads", data={
        "media_type": "IMAGE", "image_url": image_url, "text": text,
        "access_token": tok}, timeout=30)
    if not c.ok:
        return {"ok": False, "error": f"作成失敗: {c.text[:200]}"}
    cid = c.json().get("id", "")
    # 2) コンテナ処理待ち（status=FINISHED）
    for _ in range(10):
        time.sleep(2)
        s = requests.get(f"{GRAPH}/v1.0/{cid}", params={
            "fields": "status,error_message", "access_token": tok}, timeout=15)
        st = s.json().get("status", "") if s.ok else ""
        if st == "FINISHED":
            break
        if st == "ERROR":
            return {"ok": False, "error": f"画像処理失敗: {s.json().get('error_message','')[:150]}"}
    # 3) 公開
    p = requests.post(f"{GRAPH}/v1.0/{uid}/threads_publish", data={
        "creation_id": cid, "access_token": tok}, timeout=30)
    if not p.ok:
        return {"ok": False, "error": f"公開失敗: {p.text[:200]}"}
    media_id = p.json().get("id", "")
    permalink = ""
    try:
        pr = requests.get(f"{GRAPH}/v1.0/{media_id}", params={
            "fields": "permalink", "access_token": tok}, timeout=15)
        if pr.ok:
            permalink = pr.json().get("permalink", "")
    except Exception:
        pass
    return {"ok": True, "media_id": media_id, "permalink": permalink,
            "username": acc.get("username", ""), "text": text[:40]}


# ── インサイト自動取得 → SNS_RESULT ──────────────────────

INSIGHT_METRICS = "views,likes,replies,reposts,quotes,shares"


def sync_insights(ss_id, creds_path, biz_key, limit=25) -> dict:
    """
    アカウントの最近の投稿を取得し、各投稿のインサイトを SNS_RESULT へupsert。
    投稿本文も SNS_POST_STOCK(投稿済) に取り込む（分析で内容を使う）。
    手動投稿分も含めて全自動集計される。
    """
    acc = get_account(ss_id, creds_path, biz_key)
    tok = acc.get("access_token", "")
    uid = acc.get("threads_user_id", "")
    if not tok:
        return {"ok": False, "error": "未連携（先にOAuth連携してください）"}
    biz_name = acc.get("事業名") or BIZ_NAME.get(biz_key, biz_key)

    # 投稿一覧
    r = requests.get(f"{GRAPH}/v1.0/{uid}/threads", params={
        "fields": "id,text,permalink,timestamp,media_type",
        "limit": limit, "access_token": tok}, timeout=25)
    if not r.ok:
        return {"ok": False, "error": f"投稿取得失敗: {r.text[:200]}"}
    posts = r.json().get("data", [])

    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    rw = _sheet(ss, "SNS_RESULT", SNS_RESULT_HEADER)
    sw = _sheet(ss, "SNS_POST_STOCK", SNS_POST_STOCK_HEADER)
    existing_result = {r0[0]: i + 2 for i, r0 in enumerate(rw.get_all_values()[1:]) if r0}
    existing_stock = set(c for c in sw.col_values(1)[1:])

    synced = 0
    new_stock = []
    for p in posts:
        mid = str(p.get("id", ""))
        text = p.get("text", "") or ""
        ts = (p.get("timestamp", "") or "")[:10]
        # インサイト
        ins = {}
        try:
            ir = requests.get(f"{GRAPH}/v1.0/{mid}/insights", params={
                "metric": INSIGHT_METRICS, "access_token": tok}, timeout=20)
            if ir.ok:
                for m in ir.json().get("data", []):
                    name = m.get("name")
                    vals = m.get("values", [{}])
                    ins[name] = vals[0].get("value", 0) if vals else 0
        except Exception:
            pass

        shares = (ins.get("reposts", 0) or 0) + (ins.get("quotes", 0) or 0) + (ins.get("shares", 0) or 0)
        row = {
            "post_id": mid, "business_name": biz_name, "platform": "Threads投稿",
            "posted_date": ts or _date(),
            "impressions": ins.get("views", ""), "likes": ins.get("likes", ""),
            "comments": ins.get("replies", ""), "shares": shares, "saves": "",
            "profile_access": "", "line_add": "", "dm_count": "",
            "reservation_count": "", "inquiry_count": "", "visit_count": "",
            "sales_amount": "", "related_screenshot_id": p.get("permalink", ""),
            "manual_note": "Threads API自動取得",
        }
        vals = [row.get(h, "") for h in SNS_RESULT_HEADER]
        if mid in existing_result:
            rw.update(values=[vals], range_name=f"A{existing_result[mid]}:R{existing_result[mid]}",
                      value_input_option="RAW")
        else:
            rw.append_row(vals, value_input_option="RAW")
        # 投稿本文を stock に
        if mid not in existing_stock and text:
            new_stock.append([mid, biz_name, "Threads投稿", "", text, text,
                              _infer_type(text), "", "", text.splitlines()[0][:50] if text else "",
                              "", "投稿済み", "", ts, p.get("permalink", ""), 0, "Threads API取込"])
        synced += 1
        time.sleep(0.3)

    if new_stock:
        sw.append_rows(new_stock, value_input_option="RAW")
    # 最終同期日時を更新
    try:
        aws = ss.worksheet(THREADS_ACCOUNTS_SHEET)
        for i, r0 in enumerate(aws.get_all_values()[1:], start=2):
            if r0 and r0[0] == biz_key:
                aws.update_cell(i, THREADS_ACCOUNTS_HEADER.index("last_sync") + 1, _now())
                break
    except Exception:
        pass

    return {"ok": True, "business": biz_name, "posts_synced": synced,
            "new_stock": len(new_stock)}


def accounts_status(ss_id, creds_path) -> dict:
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    try:
        ws = ss.worksheet(THREADS_ACCOUNTS_SHEET)
    except gspread.WorksheetNotFound:
        return {"ok": True, "connected": [], "note": "未連携"}
    out = []
    for r in ws.get_all_records():
        out.append({"business": r.get("事業名"), "username": r.get("username"),
                    "expires_at": r.get("expires_at"), "last_sync": r.get("last_sync")})
    return {"ok": True, "connected": out, "count": len(out),
            "configured": is_configured()}
