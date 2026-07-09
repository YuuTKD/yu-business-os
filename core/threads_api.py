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
    "rewrite_version", "memo",
]

# LINE Push通知: 事業別DESTINATIONの環境変数名
_LINE_DEST_ENV = {
    "tachinomiya":   "LINE_TACHINOMIYA_DESTINATION",
    "catering":      "LINE_CATERING_DESTINATION",
    "beauty":        "LINE_BEAUTY_DESTINATION",
    "ryukyu_hinabe": "LINE_HINABE_DESTINATION",
}
# 通知対象のFAILステップ（正常停止・時間帯制限は除外）
_NOTIFY_FAIL_STEPS = frozenset({
    "token_expiry", "username_check", "consecutive_errors",
    "post_stock", "image_stock", "image_url", "theme_match",
})
# 通知対象のERRORステータス
_NOTIFY_STATUSES = frozenset({"SUCCESS", "ERROR"})

_NOTIFY_NEXT_ACTION = {
    "token_expiry":       "→ /threads-manual-setup でトークン更新してください",
    "username_check":     "→ EXPECTED_USERNAMEの設定を確認してください",
    "consecutive_errors": "→ THREADS_POST_LOGでエラー原因を確認してください",
    "post_stock":         "→ SNS_POST_STOCKに投稿候補を追加してください",
    "image_stock":        "→ IMAGE_LIBRARYにGCS画像を追加してください",
    "image_url":          "→ GCS画像のHTTP 200を確認してください",
    "theme_match":        "→ image_theme / allowed_post_themesを確認してください",
}

# 商品名が本文に強く出るテーマ: general/tourist_general へのフォールバック禁止
_STRONG_PRODUCT_THEMES = {
    "tachinomiya": {"sata_andagi", "drink", "rafute"},
    "catering":    {"bento", "setup", "decoration", "hors_doeuvre", "corporate_event"},
}

# ===== フォルダ名 → テーマ対応表（最重要・変更禁止） =====
# IMAGE_LIBRARYの「カテゴリ」列 = Google Driveのフォルダ名（人間が手動分類）
# Drive API では親フォルダが取得できないため、カテゴリ列が唯一の一次情報源。
# カテゴリ列とimage_themeが矛盾した場合は 必ずカテゴリ列（フォルダ名）を正とする。
# 新しいフォルダを追加した場合はここにも追記すること。
_RELIABLE_CATEGORY_THEMES = {
    "tachinomiya": {
        # フォルダ名          : 投稿テーマキー
        "サーターアンダギー"   : "sata_andagi",   # 揚げ菓子・沖縄スイーツ系
        "BAR"                : "drink",          # カウンタードリンク系
        "ドリンク"            : "drink",          # ドリンク単体
        "店舗内観"            : "tourist_general",# 店舗・観光向け
        "店舗外観"            : "tourist_general",
        "イベント"            : "tourist_general",
        "ラフテー"            : "rafute",         # 豚肉煮込み料理
    },
    "catering": {
        # フォルダ名          : 投稿テーマキー
        # ── 当初想定フォルダ名（Drive未使用だが将来追加時のため残す）──
        "料理"               : "catering_food",
        "お弁当"             : "bento",
        "設営"               : "setup",
        "会場設営"           : "setup",
        "装飾"               : "decoration",
        "企業イベント"        : "corporate_event",
        # ── IMAGE_LIBRARY 実際のカテゴリ列（2026-07 確認済み） ──
        "オードブル"          : "hors_doeuvre",  # 71件・法人イベント前菜
        "ケータリング"        : "catering_food",  # 21件・汎用料理全般
        "会議用弁当"          : "bento",          # 20件・9マス弁当・仕出し弁当
        "イベント"            : "corporate_event",# 6件・法人イベント・懇親会（目視確認推奨）
        "法人利用"            : "corporate_event",# 1件・法人利用シーン
    },
}
# 曖昧フォルダ: 「何でも入る」フォルダのため内容を特定できない
# → STRONGテーマ（sata_andagi/drink/rafute等）投稿では image_theme を無視してスキップ
# → image_theme が設定されていても is_theme_verified=TRUE でも適用しない
_AMBIGUOUS_CATEGORIES = {"フード", "商品写真", "料理全般", ""}

# テーマ別・補充警告閾値（残り枚数）
_THEME_THRESHOLDS = {
    "tachinomiya": {
        "sata_andagi": 10, "drink": 10, "tourist_general": 10,
        "okinawa_food": 5, "rafute": 5, "general": 5,
    },
    "catering": {
        "catering_food": 10, "general": 10, "corporate_event": 10,
        "setup": 10, "decoration": 10, "bento": 5, "hors_doeuvre": 5,
    },
}

# スタッフ向け補充依頼文テンプレート (biz_key, theme) → 本文
_REPLENISHMENT_TEMPLATE = {
    ("tachinomiya", "sata_andagi"):    "サーターアンダギーの写真が残り{n}枚です。揚げたて・食べ歩き・店頭陳列の写真を10枚以上撮影してください。ピンボケ・暗すぎNG。撮影後はDriveのTACHINOMIYAフォルダへ入れて「sata_andagi追加しました」とLINEで報告してください。",
    ("tachinomiya", "drink"):          "ドリンク系の写真が残り{n}枚です。ドリンク単体・カウンターでの一杯・乾杯シーン・夜の雰囲気の写真を10枚以上撮影してください。暗すぎ・ブレNG。撮影後はDriveへ入れて「drink追加しました」とLINEで報告してください。",
    ("tachinomiya", "tourist_general"):"観光客向けの写真が残り{n}枚です。国際通り・観光スポット系の写真を10枚以上撮影してください。撮影後は「tourist_general追加しました」とLINEで報告してください。",
    ("tachinomiya", "okinawa_food"):   "沖縄料理の写真が残り{n}枚です。島料理・郷土料理・泡盛などの写真を5枚以上撮影してください。撮影後は「okinawa_food追加しました」とLINEで報告してください。",
    ("tachinomiya", "rafute"):         "ラフテー・豚料理の写真が残り{n}枚です。煮込み料理の写真を5枚以上撮影してください。",
    ("tachinomiya", "general"):        "汎用写真が残り{n}枚です。店内・商品全般の写真を5枚以上撮影してください。",
    ("catering", "catering_food"):     "ケータリング料理の写真が残り{n}枚です。料理全体・テーブル並び・オードブルの写真を10枚以上撮影してください。撮影後はDriveのCATERINGフォルダへ入れて「catering_food追加しました」とLINEで報告してください。",
    ("catering", "corporate_event"):   "法人イベント・設営の写真が残り{n}枚です。会場設営・懇親会・表彰式の写真を10枚以上撮影してください。人の顔が映る場合は許可確認を。撮影後は「corporate_event追加しました」とLINEで報告してください。",
    ("catering", "setup"):             "設営・セッティングの写真が残り{n}枚です。料理を並べた設営中の写真を10枚以上撮影してください。撮影後は「setup追加しました」とLINEで報告してください。",
    ("catering", "decoration"):        "会場装飾の写真が残り{n}枚です。テーブル装飾・飾り付けの写真を10枚以上撮影してください。撮影後は「decoration追加しました」とLINEで報告してください。",
    ("catering", "bento"):             "弁当・仕出しの写真が残り{n}枚です。9マス弁当・個包装弁当の写真を5枚以上撮影してください。撮影後は「bento追加しました」とLINEで報告してください。",
    ("catering", "hors_doeuvre"):      "オードブルの写真が残り{n}枚です。オードブルセット・前菜盛り合わせの写真を5枚以上撮影してください。撮影後は「hors_doeuvre追加しました」とLINEで報告してください。",
    ("catering", "general"):           "汎用写真が残り{n}枚です。ケータリング全般の写真を10枚以上撮影してください。",
}


def _notify_auto_post(biz_key: str, result: dict,
                      remaining_by_theme: dict = None,
                      today_post_no: int = None,
                      daily_limit: int = 2) -> None:
    """
    自動投稿結果をLINE公式（事業別）へPush通知。
    - dry_run=True時は呼び出し側でガード（この関数内でも二重チェック）
    - 通知失敗は標準エラーログのみ（投稿処理には影響させない）
    - Secret/token値は出力しない
    - remaining_by_theme: テーマ別残り画像枚数 → 在庫サマリー＋補充依頼を付与
    """
    if result.get("dry_run"):
        return
    try:
        import requests as _rq
        token = os.getenv("LINE_OWNER_TOKEN", "")
        dest  = os.getenv(_LINE_DEST_ENV.get(biz_key, ""), "")
        if not token or not dest:
            print(f"[notify] skip {biz_key}: env not set")
            return

        biz_name   = BIZ_NAME.get(biz_key, biz_key)
        status     = result.get("status", "FAIL")
        step       = result.get("step_failed", "")
        reason     = result.get("reason", result.get("error", ""))
        permalink  = result.get("permalink", "")
        image_id   = result.get("image_id", "")
        score      = result.get("quality_score", "")
        post_theme = result.get("post_theme", "")
        slot       = result.get("slot", "")

        if status == "SUCCESS":
            parts = [f"✅ 【{biz_name}】投稿完了"]
            if slot:       parts.append(f"スロット: {slot}")
            if post_theme: parts.append(f"テーマ: {post_theme}")
            if image_id:   parts.append(f"画像: {image_id}　スコア: {score}")
            if today_post_no is not None:
                parts.append(f"本日 {today_post_no}本目 / {daily_limit}本")
            if permalink:  parts.append(f"🔗 {permalink}")
        else:
            parts = [f"❌ 【{biz_name}】投稿失敗"]
            if slot:       parts.append(f"スロット: {slot}")
            if step:       parts.append(f"step: {step}")
            if reason:     parts.append(f"理由: {str(reason)[:80]}")
            if post_theme: parts.append(f"テーマ: {post_theme}")
            parts.append(_NOTIFY_NEXT_ACTION.get(step, "→ THREADS_POST_LOGを確認してください"))

        # 画像在庫サマリー
        if remaining_by_theme:
            thresholds = _THEME_THRESHOLDS.get(biz_key, {})
            if thresholds:
                parts.append("")
                parts.append("📊 画像在庫")
                for theme in thresholds.keys():
                    n = remaining_by_theme.get(theme, 0)
                    mark = "🚨" if n == 0 else ("⚠️" if n <= 3 else ("📷" if n <= 5 else "✅"))
                    parts.append(f"{mark} {theme}: 残り{n}枚")

        # 補充依頼（閾値以下のテーマ）
        if remaining_by_theme:
            alerts = _replenishment_alerts(biz_key, remaining_by_theme)
            if alerts:
                parts.append("")
                parts.append("📷 補充依頼:")
                for (_, _, urgency, msg) in alerts:
                    parts.append(f"{urgency} {msg}")

        _rq.post(
            "https://api.line.me/v2/bot/message/push",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json={"to": dest, "messages": [{"type": "text", "text": "\n".join(parts)[:4900]}]},
            timeout=10,
        )
    except Exception as e:
        print(f"[notify] error (ignored): {e}")


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


# ── 自動投稿サポート関数 ──────────────────────────────────────

THREADS_POST_LOG_SHEET = "THREADS_POST_LOG"
THREADS_POST_LOG_HEADER = [
    "実行日時", "事業キー", "事業名", "media_id", "post_url",
    "投稿本文", "画像URL", "画像ID", "投稿元行番号", "品質スコア",
    "dry_run", "実行結果", "エラー詳細", "token_check", "duplicate_check", "実行者",
    "slot_name", "post_theme", "sales_category",
]

IMAGE_LIBRARY_SS = "15cfsC2HIzu1FGW602dxqNuv-DJpmLiZhatvB-hDn2XM"
IMAGE_LIBRARY_SHEET = "画像台帳"
# 画像台帳カラムインデックス（0始まり）
_IMG_COL = {
    "画像ID": 0, "ファイル名": 1, "Drive URL": 2, "Drive ファイルID": 3,
    "事業名": 4, "カテゴリ": 5, "利用回数": 12, "最終利用日": 13,
    "gcs_public_url": 16,  # PHASE2で追加予定の列（存在しない場合は空）
}


def _img_lib_gc(creds_path):
    creds = Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/spreadsheets",
                            "https://www.googleapis.com/auth/drive"])
    return gspread.authorize(creds)


def validate_image_url(url: str) -> dict:
    """公開HTTPS画像URLが実際にアクセス可能か確認（HEAD request）"""
    import urllib.request
    if not url or not url.startswith("https://"):
        return {"ok": False, "status": 0, "reason": "HTTPSでない"}
    try:
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", "YU-Holdings-Bot/1.0")
        with urllib.request.urlopen(req, timeout=10) as resp:
            ct = resp.headers.get("Content-Type", "")
            status = resp.status
            if status == 200 and ("image" in ct or ct == ""):
                return {"ok": True, "status": status, "content_type": ct}
            return {"ok": False, "status": status, "reason": f"Content-Type={ct}"}
    except Exception as e:
        return {"ok": False, "status": 0, "reason": str(e)[:100]}


def check_token_expiry(acc: dict, warn_days: int = 7) -> dict:
    """
    トークン期限チェック。expires_at が warn_days 日以内なら警告。
    Threads長期トークンは60日有効。
    """
    expires_at = acc.get("expires_at", "")
    if not expires_at:
        return {"ok": True, "status": "unknown", "warn": False}
    try:
        exp = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        days_left = (exp - now).days
        if days_left < 0:
            return {"ok": False, "status": "expired", "days_left": days_left, "warn": True}
        if days_left <= warn_days:
            return {"ok": True, "status": "expiring_soon", "days_left": days_left, "warn": True}
        return {"ok": True, "status": "valid", "days_left": days_left, "warn": False}
    except Exception as e:
        return {"ok": True, "status": f"parse_error:{e}", "warn": False}


def check_duplicate_post(ss, biz_key: str, stock_row_no: str) -> bool:
    """
    THREADS_POST_LOG に同じ投稿元行番号・同じ事業の投稿済みレコードがあれば True（重複）。
    """
    try:
        ws = _sheet(ss, THREADS_POST_LOG_SHEET, THREADS_POST_LOG_HEADER)
        rows = ws.get_all_values()[1:]
        for r in rows:
            if len(r) >= 9 and r[1] == biz_key and str(r[8]) == str(stock_row_no):
                if r[11] not in ("DRY_RUN", "ERROR", ""):
                    return True
    except Exception:
        pass
    return False


def count_today_posts(ss, biz_key: str) -> int:
    """今日の実投稿数（dry_run=False かつ成功）を返す"""
    today = _date()
    count = 0
    try:
        ws = _sheet(ss, THREADS_POST_LOG_SHEET, THREADS_POST_LOG_HEADER)
        for r in ws.get_all_values()[1:]:
            if len(r) >= 12 and r[1] == biz_key:
                dt = str(r[0])[:10]
                dry = str(r[10]).upper()
                result = str(r[11])
                if dt == today and dry != "TRUE" and result == "SUCCESS":
                    count += 1
    except Exception:
        pass
    return count


def count_consecutive_errors(ss, biz_key: str) -> int:
    """直近の連続エラー数（最新行から遡って SUCCESS が出るまでの ERROR 数）"""
    count = 0
    try:
        ws = _sheet(ss, THREADS_POST_LOG_SHEET, THREADS_POST_LOG_HEADER)
        rows = [r for r in ws.get_all_values()[1:] if len(r) >= 12 and r[1] == biz_key
                and str(r[10]).upper() != "TRUE"]  # dry_run除外
        for r in reversed(rows):
            result = str(r[11])
            if result == "SUCCESS":
                break
            if result == "ERROR":
                count += 1
    except Exception:
        pass
    return count


def is_in_posting_window(window: tuple) -> bool:
    """現在時刻が投稿許可ウィンドウ内か判定 (JST)"""
    now = datetime.now(JST)
    cur = now.strftime("%H:%M")
    return window[0] <= cur <= window[1]


def _select_best_stock_row(ss, biz_key: str, min_score: int = 0) -> dict:
    """
    SNS_POST_STOCK から未投稿の最高スコア行を1件選ぶ。
    Returns {"row_no": int, "text": str, "score": int, "post_id": str} or None
    """
    from core.post_quality import score as qs
    biz_name_map = {
        "catering": "TREE's Catering", "tachinomiya": "TACHINOMIYA",
        "beauty": "Tree Beauty", "ryukyu_hinabe": "琉球火鍋",
    }
    biz_name = biz_name_map.get(biz_key, biz_key)
    try:
        ws = _sheet(ss, "SNS_POST_STOCK", SNS_POST_STOCK_HEADER)
        rows = ws.get_all_values()
        header = rows[0] if rows else []
        # カラム位置
        ci = {h: i for i, h in enumerate(header)}
        biz_col = ci.get("business_name", 1)
        text_col = ci.get("current_text", 5)
        status_col = ci.get("status", 11)
        postid_col = ci.get("post_id", 0)

        candidates = []
        for i, r in enumerate(rows[1:], start=2):
            if len(r) <= max(biz_col, text_col, status_col):
                continue
            if r[biz_col] != biz_name:
                continue
            if r[status_col] in ("投稿済み", "済み", "posted", "POSTED"):
                continue
            text = r[text_col]
            if not text.strip():
                continue
            s = qs(text, biz_key)
            candidates.append({
                "row_no": i, "text": text, "score": s["score"],
                "post_id": r[postid_col] if len(r) > postid_col else "",
                "ng_reason": s.get("ng_reason", ""),
            })

        candidates = [c for c in candidates if not c["ng_reason"] and c["score"] >= min_score]
        if not candidates:
            return None
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[0]
    except Exception as e:
        return None


def _select_image(creds_path: str, biz_key: str, post_text: str = "") -> dict:
    """
    IMAGE_LIBRARY から投稿本文テーマに合致する画像を選ぶ。
    - post_text からテーマを抽出し、blocked_post_themes に該当する画像を除外する
    - image_theme が一致する画像を優先。未分類画像はフォールバックとして使用
    - gcs_public_url があるものを優先、利用回数少ない順
    Returns:
      {"image_id": str, "url": str, "needs_gcs": bool, "file_name": str,
       "post_theme": str, "theme_matched": bool, "img_theme": str, "theme_match_reason": str}
    or {"theme_blocked": True, "post_theme": str, "blocked_count": int}  (全候補除外)
    or None  (対象画像ゼロ)
    """
    from configs.post_theme_rules import extract_post_theme
    biz_name_map = {
        "catering": "CATERING", "tachinomiya": "TACHINOMIYA",
        "beauty": "BEAUTY", "ryukyu_hinabe": "HINABE",
    }
    biz_name = biz_name_map.get(biz_key, biz_key.upper())
    post_theme = extract_post_theme(post_text, biz_key) if post_text else "general"
    try:
        gc = _img_lib_gc(creds_path)
        ws = gc.open_by_key(IMAGE_LIBRARY_SS).worksheet(IMAGE_LIBRARY_SHEET)
        rows = ws.get_all_values()
        if not rows or len(rows) < 2:
            return None
        header = rows[0]
        ci = {h: i for i, h in enumerate(header)}

        img_id_col       = ci.get("画像ID", 0)
        fname_col        = ci.get("ファイル名", 1)
        drive_url_col    = ci.get("Drive URL", 2)
        biz_col          = ci.get("事業名", 4)
        usage_col        = ci.get("利用回数", 12)
        gcs_col          = ci.get("gcs_public_url", -1)
        img_theme_col    = ci.get("image_theme", -1)
        blocked_col      = ci.get("blocked_post_themes", -1)
        allowed_col      = ci.get("allowed_post_themes", -1)

        candidates = []
        blocked_count = 0
        for r in rows[1:]:
            if not r or len(r) <= biz_col:
                continue
            if r[biz_col] != biz_name:
                continue
            image_id  = r[img_id_col] if len(r) > img_id_col else ""
            fname     = r[fname_col]  if len(r) > fname_col  else ""
            drive_url = r[drive_url_col] if len(r) > drive_url_col else ""
            gcs_url   = (r[gcs_col] if gcs_col >= 0 and len(r) > gcs_col else "") or ""
            img_theme = (r[img_theme_col] if img_theme_col >= 0 and len(r) > img_theme_col else "") or ""
            blocked_str = (r[blocked_col] if blocked_col >= 0 and len(r) > blocked_col else "") or ""
            allowed_str = (r[allowed_col] if allowed_col >= 0 and len(r) > allowed_col else "") or ""
            usage = 0
            try:
                usage = int(r[usage_col]) if len(r) > usage_col and r[usage_col] else 0
            except ValueError:
                pass

            # テーマ除外チェック（post_theme が blocked_post_themes に含まれる → 除外）
            if post_theme != "general" and blocked_str:
                blocked_list = [t.strip() for t in blocked_str.split(",") if t.strip()]
                if post_theme in blocked_list:
                    blocked_count += 1
                    continue

            # テーマ一致スコア
            allowed_list = [t.strip() for t in allowed_str.split(",") if t.strip()]
            if post_theme == "general":
                theme_matched = True
            else:
                theme_matched = (img_theme == post_theme) or (post_theme in allowed_list)

            candidates.append({
                "image_id": image_id, "file_name": fname,
                "drive_url": drive_url, "gcs_url": gcs_url,
                "usage": usage, "img_theme": img_theme,
                "theme_matched": theme_matched,
            })

        if not candidates:
            if blocked_count > 0:
                return {"theme_blocked": True, "post_theme": post_theme, "blocked_count": blocked_count}
            return None

        # GCS優先プール
        with_gcs = [c for c in candidates if c["gcs_url"].startswith("https://")]
        pool = with_gcs if with_gcs else candidates

        if post_theme != "general":
            # テーマ一致（分類済み）のみ使用。未分類・テーマ違いは使わない
            matched = sorted([c for c in pool if c["theme_matched"] and c["img_theme"]], key=lambda x: x["usage"])
            ordered = matched
            if not ordered and with_gcs:
                # GCSプールになかった場合のみ全候補から再検索（Driveフォールバック）
                matched = sorted([c for c in candidates if c["theme_matched"] and c["img_theme"]], key=lambda x: x["usage"])
                ordered = matched
        else:
            # general: 未分類・分類済みすべて使用（利用回数少ない順）
            ordered = sorted(pool, key=lambda x: x["usage"])

        if not ordered:
            if blocked_count > 0:
                return {"theme_blocked": True, "post_theme": post_theme, "blocked_count": blocked_count}
            if post_theme != "general":
                return {"theme_no_match": True, "post_theme": post_theme,
                        "total_biz_images": len(candidates)}
            return None

        best = ordered[0]
        url = best["gcs_url"] if best["gcs_url"].startswith("https://") else best["drive_url"]
        needs_gcs = not best["gcs_url"].startswith("https://")

        if post_theme == "general":
            reason = "general（テーマフィルタ適用外）"
        elif best["img_theme"] and best["theme_matched"]:
            reason = f"image_theme={best['img_theme']} match"
        elif not best["img_theme"]:
            reason = "未分類画像（フォールバック）"
        else:
            reason = f"allowed_post_themes match"

        return {
            "image_id": best["image_id"], "url": url,
            "needs_gcs": needs_gcs, "file_name": best["file_name"],
            "post_theme": post_theme, "theme_matched": best["theme_matched"],
            "img_theme": best["img_theme"], "theme_match_reason": reason,
        }
    except Exception:
        return None


def _log_post_result(ss, biz_key: str, biz_name: str, media_id: str, post_url: str,
                     text: str, image_url: str, image_id: str, stock_row_no,
                     quality_score: int, dry_run: bool, result: str, error: str = "",
                     token_check: str = "ok", dup_check: str = "ok",
                     slot_name: str = "", post_theme: str = "",
                     sales_category: str = ""):
    """THREADS_POST_LOG にログを1行追記"""
    ws = _sheet(ss, THREADS_POST_LOG_SHEET, THREADS_POST_LOG_HEADER)
    ws.append_row([
        _now(), biz_key, biz_name, media_id, post_url,
        text[:200], image_url, image_id, str(stock_row_no), quality_score,
        "TRUE" if dry_run else "FALSE", result, error[:200],
        token_check, dup_check, "AUTO",
        slot_name, post_theme, sales_category,
    ], value_input_option="RAW")


def run_full_auto(ss_id: str, creds_path: str, biz_key: str, dry_run: bool = True) -> dict:
    """
    12段階安全チェック付き完全自動投稿。
    dry_run=True（既定）: 実際には投稿せずプレビューのみ返す。
    dry_run=False: 本番投稿（configs/auto_post_settings.py の auto_post_enabled=True 必須）。
    """
    import os
    from configs.auto_post_settings import BUSINESS_AUTO_POST_CONFIG, MASTER_SWITCH_ENV

    gc = _gc(creds_path)
    ss = gc.open_by_key(ss_id)
    biz_name = BIZ_NAME.get(biz_key, biz_key)

    checks = []

    def fail(step: str, reason: str, **kw):
        checks.append({"step": step, "ok": False, "reason": reason})
        return {"ok": False, "step_failed": step, "reason": reason, "checks": checks,
                "biz_key": biz_key, "dry_run": dry_run, **kw}

    def ok_step(step: str, note: str = ""):
        checks.append({"step": step, "ok": True, "note": note})

    # 1. マスタースイッチ
    master = os.getenv(MASTER_SWITCH_ENV, "true").lower()
    if master == "false":
        return fail("master_switch", "AUTO_POST_MASTER_SWITCH=false → 全停止中")
    ok_step("master_switch", "true")

    # 2. 事業別ON/OFFスイッチ（dry_run時はスキップ）
    cfg = BUSINESS_AUTO_POST_CONFIG.get(biz_key, {})
    if not cfg:
        return fail("biz_config", f"{biz_key} の設定が存在しない")
    if not dry_run and not cfg.get("auto_post_enabled", False):
        return fail("biz_enabled", f"auto_post_enabled=False。configs/auto_post_settings.py を変更後に有効化してください")
    ok_step("biz_enabled", "dry_run=True なのでスキップ" if dry_run else "enabled")

    # 3. トークン有効確認
    acc = get_account(ss_id, creds_path, biz_key)
    if not acc.get("access_token"):
        return fail("token", "未連携（先にOAuth連携してください）")
    token_chk = check_token_expiry(acc)
    token_note = token_chk.get("status", "unknown")
    if not token_chk["ok"]:
        return fail("token_expiry", f"トークン期限切れ ({token_note})")
    ok_step("token_expiry", token_note)

    # 4. username安全チェック
    expected = EXPECTED_USERNAME.get(biz_key)
    actual = acc.get("username", "")
    if expected and actual and actual != expected:
        return fail("username_check", f"username不一致(@{actual}≠@{expected})")
    ok_step("username_check", f"@{actual}")

    # 5. 投稿ウィンドウ（dry_run時はスキップ）
    window = cfg.get("posting_window", ("00:00", "23:59"))
    if not dry_run and not is_in_posting_window(window):
        now_str = datetime.now(JST).strftime("%H:%M")
        return fail("posting_window", f"投稿ウィンドウ外 ({now_str} ∉ {window[0]}-{window[1]})")
    ok_step("posting_window", f"{window[0]}-{window[1]} (dry_run={dry_run})")

    # 6. 1日投稿上限（dry_run時はスキップ）
    daily_limit = cfg.get("daily_post_limit", 1)
    if not dry_run:
        today_count = count_today_posts(ss, biz_key)
        if today_count >= daily_limit:
            return fail("daily_limit", f"本日投稿済み {today_count}/{daily_limit}")
        ok_step("daily_limit", f"{today_count}/{daily_limit}")
    else:
        ok_step("daily_limit", "dry_run=True なのでスキップ")

    # 7. 連続エラー停止チェック
    err_limit = cfg.get("consecutive_error_limit", 3)
    consec_err = count_consecutive_errors(ss, biz_key)
    if consec_err >= err_limit:
        return fail("consecutive_errors", f"連続エラー {consec_err}/{err_limit} 回 → 自動停止")
    ok_step("consecutive_errors", f"{consec_err}/{err_limit}")

    # 8. 投稿候補選定（SNS_POST_STOCK）
    min_score = cfg.get("min_quality_score", 3)
    candidate = _select_best_stock_row(ss, biz_key, min_score)
    if not candidate:
        return fail("post_stock", f"SNS_POST_STOCK に利用可能な候補なし（スコア>={min_score}）")
    ok_step("post_stock", f"row#{candidate['row_no']} score={candidate['score']}")
    text = candidate["text"]  # テーマ判定のため事前取得

    # 8.5. 美容NG表現チェック（beauty専用・薬機法対策）
    if biz_key == "beauty":
        try:
            from businesses.beauty.beauty_threads_config import check_ng_expression
            ng_result = check_ng_expression(text)
            verdict = ng_result.get("verdict", "PASS")
            found   = ng_result.get("found", [])
            if verdict == "BLOCK":
                return fail("beauty_ng_check",
                            f"薬機法BLOCKワード検出: {', '.join(found)} → 投稿中止。投稿候補を修正してください。")
            elif verdict == "REVISE":
                return fail("beauty_ng_check",
                            f"修正推奨ワード検出: {', '.join(found)} → 修正後に再実行してください。")
            ok_step("beauty_ng_check", f"PASS（検出なし）")
        except ImportError:
            ok_step("beauty_ng_check", "SKIP（beauty_threads_config未ロード）")

    # 9. 重複チェック
    if check_duplicate_post(ss, biz_key, str(candidate["row_no"])):
        return fail("duplicate", f"row#{candidate['row_no']} は既投稿")
    ok_step("duplicate", "重複なし")

    # 10. 画像選定（投稿本文テーマ考慮）
    img = _select_image(creds_path, biz_key, post_text=text)
    if not img:
        return fail("image_stock", "IMAGE_LIBRARY に利用可能な画像なし（gcs_public_url または Drive URL）")
    if img.get("theme_blocked"):
        return fail("image_stock",
                    f"post_theme={img['post_theme']} 対象画像なし（{img['blocked_count']}件除外）"
                    "。対応カテゴリの画像をGCS化・image_theme設定後に再実行してください。")
    if img.get("theme_no_match"):
        return fail("image_stock",
                    f"post_theme={img['post_theme']} に分類済みの一致画像なし（全{img['total_biz_images']}件はテーマ違い）"
                    "。対応カテゴリの画像をGCS化・image_theme設定後に再実行してください。")
    ok_step("image_stock", f"{img['image_id']} needs_gcs={img['needs_gcs']}")

    # 11. 画像URL検証
    image_url = img["url"]
    if not image_url.startswith("https://"):
        return fail("image_url", f"画像URLが HTTPS でない: {image_url[:80]}")
    # Drive URLはThreads APIで使えない（GCS化が必要）
    if "drive.google.com" in image_url:
        if not dry_run:
            return fail("image_url", "Drive URLのまま実投稿不可。先にGCS化（/image-library-gcs-upload）が必要")
        ok_step("image_url_validate", "DRY_RUN: Drive URL（実投稿前にGCS化必要）")
    elif not dry_run:
        url_chk = validate_image_url(image_url)
        if not url_chk["ok"]:
            return fail("image_url_validate", f"画像URLアクセス失敗: {url_chk.get('reason','')}")
        ok_step("image_url_validate", f"HTTP {url_chk.get('status')}")
    else:
        ok_step("image_url_validate", "dry_run=True なのでスキップ")

    # 13. 投稿テーマ × 画像テーマ整合チェック（新規）
    post_theme   = img.get("post_theme", "general")
    theme_matched = img.get("theme_matched", True)
    img_theme    = img.get("img_theme", "")
    theme_reason = img.get("theme_match_reason", "")
    # 分類済み画像がテーマ不一致の場合は投稿中止（フォールバック禁止）
    if post_theme != "general" and img_theme and not theme_matched:
        _log_post_result(ss, biz_key, biz_name, "", "", text, image_url,
                         img["image_id"], candidate["row_no"], candidate["score"],
                         dry_run, "SKIP",
                         f"テーマ不一致: post={post_theme} / image={img_theme}",
                         token_check=token_note, dup_check="ok")
        return fail("theme_match",
                    f"テーマ不一致: post_theme={post_theme} / image_theme={img_theme} "
                    "→ 投稿中止。対応カテゴリの画像をGCS化・image_theme設定後に再実行してください。")
    if post_theme == "general":
        ok_step("theme_match", "general（テーマフィルタ適用外）")
    else:
        warn = " ⚠️未分類画像使用" if (not img_theme) else ""
        ok_step("theme_match", f"post_theme={post_theme} | {theme_reason}{warn}")

    # 12. 実投稿 or DRY_RUN
    preview = {
        "biz_key": biz_key, "biz_name": biz_name, "dry_run": dry_run,
        "post_text": text[:200], "image_url": image_url,
        "image_id": img["image_id"], "needs_gcs": img["needs_gcs"],
        "quality_score": candidate["score"], "stock_row_no": candidate["row_no"],
        "checks": checks,
        "request_body": {
            "business": biz_key, "text": text[:200], "image_url": image_url,
        },
    }

    if dry_run:
        _log_post_result(ss, biz_key, biz_name, "", "", text, image_url,
                         img["image_id"], candidate["row_no"],
                         candidate["score"], True, "DRY_RUN",
                         token_check=token_note, dup_check="ok")
        return {"ok": True, **preview, "status": "DRY_RUN"}

    # 本番投稿
    result = publish_image(ss_id, creds_path, biz_key, text, image_url)
    if not result.get("ok"):
        err = result.get("error", "unknown")
        _log_post_result(ss, biz_key, biz_name, "", "", text, image_url,
                         img["image_id"], candidate["row_no"],
                         candidate["score"], False, "ERROR", err,
                         token_check=token_note, dup_check="ok")
        return {"ok": False, **preview, "status": "ERROR", "error": err}

    media_id = result.get("media_id", "")
    permalink = result.get("permalink", "")
    _log_post_result(ss, biz_key, biz_name, media_id, permalink, text, image_url,
                     img["image_id"], candidate["row_no"],
                     candidate["score"], False, "SUCCESS",
                     token_check=token_note, dup_check="ok")

    # 投稿成功後: SNS_POST_STOCK を「投稿済み」に更新
    try:
        sw = _sheet(ss, "SNS_POST_STOCK", SNS_POST_STOCK_HEADER)
        sw_header = sw.row_values(1)
        sw_ci = {h: i+1 for i, h in enumerate(sw_header)}
        row = candidate["row_no"]
        if "status" in sw_ci:
            sw.update_cell(row, sw_ci["status"], "投稿済み")
        if "posted_date" in sw_ci:
            sw.update_cell(row, sw_ci["posted_date"], _date())
        if "posted_url" in sw_ci:
            sw.update_cell(row, sw_ci["posted_url"], permalink)
    except Exception:
        pass  # ログ記録は成功済みのためエラーは継続

    # 投稿成功後: IMAGE_LIBRARY の利用回数・最終利用日を更新
    try:
        img_gc = _img_lib_gc(creds_path)
        img_ws = img_gc.open_by_key(IMAGE_LIBRARY_SS).worksheet(IMAGE_LIBRARY_SHEET)
        img_header = img_ws.row_values(1)
        img_ci = {h: i+1 for i, h in enumerate(img_header)}
        cell = img_ws.find(img["image_id"], in_column=1)
        if cell:
            usage_col = img_ci.get("利用回数", 13)
            date_col  = img_ci.get("最終利用日", 14)
            cur = img_ws.cell(cell.row, usage_col).value
            img_ws.update_cell(cell.row, usage_col, (int(cur) if cur else 0) + 1)
            img_ws.update_cell(cell.row, date_col, _date())
    except Exception:
        pass

    return {"ok": True, **preview, "status": "SUCCESS",
            "media_id": media_id, "permalink": permalink}


def auto_post_ready_check(ss_id: str, creds_path: str) -> dict:
    """全事業の自動投稿準備状況チェック（投稿はしない）"""
    from configs.auto_post_settings import BUSINESS_AUTO_POST_CONFIG
    results = {}
    for biz_key, cfg in BUSINESS_AUTO_POST_CONFIG.items():
        status = "NOT_READY"
        notes = []
        enabled = cfg.get("auto_post_enabled", False)
        try:
            acc = get_account(ss_id, creds_path, biz_key)
            has_token = bool(acc.get("access_token"))
            token_chk = check_token_expiry(acc) if has_token else {"ok": False, "status": "no_token"}
            img = _select_image(creds_path, biz_key)
            has_image = bool(img)
            if not has_token:
                notes.append("token未連携")
            if not token_chk.get("ok"):
                notes.append(f"token: {token_chk.get('status')}")
            if not has_image:
                notes.append("IMAGE_LIBRARY画像なし")
            if not enabled:
                notes.append("auto_post_enabled=False")
            if not notes:
                status = "READY" if enabled else "ALMOST_READY"
            elif len(notes) == 1 and not enabled:
                status = "ALMOST_READY"
        except Exception as e:
            notes.append(f"チェックエラー: {str(e)[:80]}")
        results[biz_key] = {
            "status": status, "auto_post_enabled": enabled, "notes": notes,
            "business_name": cfg.get("business_name", biz_key),
        }
    return {"ok": True, "businesses": results}
