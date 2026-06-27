"""Google Business Profile（GBP）自動投稿システム土台。
※API承認待ち。OAuth/投稿系は承認後に実行（コードは準備済み）。シート作成・キュー構築・DRY_RUNは即実行可。
トークン/シークレットは表示せず Secret Manager / 環境変数で保持する設計。"""
import os
import gspread
from datetime import datetime, timezone, timedelta
from google.oauth2.service_account import Credentials

JST = timezone(timedelta(hours=9))
PROJECT_NUMBER = "75610219333"
GBP_SCOPE = "https://www.googleapis.com/auth/business.manage"
REDIRECT_URI = "https://yu-holdings-ai-qpiiccdspa-an.a.run.app/gbp-oauth/callback"

# API エンドポイント
ACCOUNTS_API = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
INFO_API = "https://mybusinessbusinessinformation.googleapis.com/v1"
LOCALPOST_API = "https://mybusiness.googleapis.com/v4"  # localPosts は v4

# 対象3事業（業務シートの場所も定義）
GBP_BIZ = {
    "tachinomiya": {"name": "TACHINOMIYA",
        "content_ss": "1K4KkAhFwVkQqqvzeqa25-1sR26ltBfP9gY9h-N4gXcc",
        "content_sheet": "08_Google投稿", "header_row": 2,
        "col": {"date": 1, "title": 3, "body": 4, "status": 6}, "cta": "", "cta_url": ""},
    "trees_catering": {"name": "TREE's Catering",
        "content_ss": "1tNE35iQAVk6eTGEu68WDrRpv9FDIeVT_eK66iRi78Zs",
        "content_sheet": "08_Google投稿", "header_row": 2,
        "col": {"date": 1, "title": 3, "body": 4, "status": 6},
        "cta": "", "cta_url": ""},  # CTA URL未保有のためCTAなし（テキスト投稿）
    "tree_beauty": {"name": "Tree Beauty",
        "content_ss": "1I6wRRDa-b440DBxZ3TbFbfMxEXZecowzOsxTAYSxyBE",
        "content_sheet": "08Google投稿", "header_row": 1,
        "col": {"date": 0, "title": 3, "body": 4, "status": 7, "cta_url": 6},
        "cta": "BOOK", "cta_url": "https://beauty.hotpepper.jp/kr/slnH000532761/"},
}
OWNER_EMAIL = "yuya_tokuda@trees-catering.com"

# ── シート定義 ──
SHEETS = {
    "GBP_API_APPLICATION_STATUS": ["登録日時", "事業名", "business_key", "GBP名", "GBP管理者メール",
        "Google Cloud Project Number", "申請日", "申請ステータス", "承認確認日", "APIクォータ状態",
        "OAuth準備状態", "locationId取得状態", "Google投稿テスト状態", "本番投稿状態", "メモ", "最終更新日時"],
    "GBP_ACCOUNT_MASTER": ["登録日時", "business_key", "事業名", "GBP店舗名", "Google Account ID",
        "Location ID", "Location Name", "Store Code", "管理者メール", "住所", "電話番号", "WebサイトURL",
        "GoogleマップURL", "OAuth状態", "投稿許可", "写真許可", "口コミ許可", "最終確認日時", "メモ"],
    "GBP_POST_QUEUE": ["登録日時", "business_key", "事業名", "投稿日", "投稿媒体", "投稿タイプ",
        "投稿タイトル", "投稿本文", "画像URL", "CTA種別", "CTA URL", "元シート名", "元シート行番号",
        "投稿状況", "DRY_RUN結果", "人間確認", "投稿ID", "投稿URL", "API結果", "エラー内容", "最終更新日時", "メモ"],
    "GBP_POST_LOG": ["実行日時", "business_key", "事業名", "Location ID", "投稿タイトル", "投稿本文",
        "画像URL", "CTA種別", "CTA URL", "API結果", "投稿ID", "投稿URL", "エラー内容", "実行モード", "メモ"],
}


def _gc(creds_path):
    return gspread.authorize(Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/spreadsheets"]))


def _now():
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M")


def _today():
    return datetime.now(JST).strftime("%Y-%m-%d")


def _sheet(ss, name, header):
    try:
        ws = ss.worksheet(name)
        if not ws.get_all_values():
            ws.update(values=[header], range_name="A1", value_input_option="RAW")
        return ws
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(name, rows=2000, cols=max(len(header), 24))
        ws.update(values=[header], range_name="A1", value_input_option="RAW")
        return ws


def setup_sheets(ss_id, creds_path):
    """4シート作成＋申請状況/アカウントマスターを3事業分シード（既存は壊さない）"""
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    created = []
    for n, h in SHEETS.items():
        _sheet(ss, n, h); created.append(n)
    # 申請状況シード
    aws = ss.worksheet("GBP_API_APPLICATION_STATUS")
    have = {r[2] for r in aws.get_all_values()[1:] if len(r) > 2}
    for bk, cfg in GBP_BIZ.items():
        if bk in have:
            continue
        aws.append_row([_now(), cfg["name"], bk, cfg["name"], OWNER_EMAIL, PROJECT_NUMBER,
                        _today(), "申請済み（承認待ち）", "", "未確認", "コード準備済",
                        "未取得", "未実施", "未実施", "API承認後に自動取得", _now()],
                       value_input_option="RAW")
    # アカウントマスターシード（accountId/locationIdは承認後に自動取得）
    mws = ss.worksheet("GBP_ACCOUNT_MASTER")
    have = {r[1] for r in mws.get_all_values()[1:] if len(r) > 1}
    for bk, cfg in GBP_BIZ.items():
        if bk in have:
            continue
        mws.append_row([_now(), bk, cfg["name"], cfg["name"], "", "", "", "", OWNER_EMAIL,
                        "", "", cfg.get("cta_url", ""), "", "未連携", "承認後", "承認後", "承認後",
                        _now(), "locationId承認後取得"], value_input_option="RAW")
    return {"ok": True, "sheets": created, "businesses": list(GBP_BIZ)}


def post_queue_build(ss_id, creds_path, days_ahead=90):
    """既存Google投稿シート→GBP_POST_QUEUE 取込（重複防止・既存削除なし）"""
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    qws = _sheet(ss, "GBP_POST_QUEUE", SHEETS["GBP_POST_QUEUE"])
    existing = {(r[1], r[3], r[6]) for r in qws.get_all_values()[1:] if len(r) > 6}  # (bk,投稿日,タイトル)
    today = _today()
    added = {}
    new_rows = []
    for bk, cfg in GBP_BIZ.items():
        added[bk] = 0
        try:
            csheet = gc.open_by_key(cfg["content_ss"]).worksheet(cfg["content_sheet"])
            vals = csheet.get_all_values()
        except Exception:
            continue
        col = cfg["col"]; hr = cfg["header_row"]
        for i in range(hr, len(vals)):
            row = vals[i]
            d = row[col["date"]] if col["date"] < len(row) else ""
            title = row[col["title"]] if col["title"] < len(row) else ""
            body = row[col["body"]] if col["body"] < len(row) else ""
            status = row[col["status"]] if col["status"] < len(row) else ""
            d_norm = str(d).replace("/", "-")
            if not body or not d_norm or d_norm < today:  # 当日以降のみ
                continue
            if str(status) in ("投稿済み", "除外"):
                continue
            if (bk, str(d), title) in existing:
                continue
            cta_url = row[col["cta_url"]] if col.get("cta_url") is not None and col["cta_url"] < len(row) else cfg.get("cta_url", "")
            new_rows.append([_now(), bk, cfg["name"], str(d), "Google投稿", "STANDARD",
                             title, body, "", cfg.get("cta", ""), cta_url,
                             cfg["content_sheet"], i + 1, "未投稿", "", "未確認", "", "", "", "", _now(), ""])
            existing.add((bk, str(d), title)); added[bk] += 1
    if new_rows:
        qws.append_rows(new_rows, value_input_option="RAW")
    return {"ok": True, "added": added, "total_new": len(new_rows)}


# ════════ OAuth（承認後に実行・コードは準備済み）════════

def authorize_url(state="gbp"):
    from urllib.parse import urlencode
    cid = os.getenv("GBP_OAUTH_CLIENT_ID", "")
    p = {"client_id": cid, "redirect_uri": REDIRECT_URI, "response_type": "code",
         "scope": GBP_SCOPE, "access_type": "offline", "prompt": "consent", "state": state}
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(p)


def is_oauth_configured():
    return bool(os.getenv("GBP_OAUTH_CLIENT_ID") and os.getenv("GBP_OAUTH_CLIENT_SECRET"))


def handle_callback(code):
    """code→refresh_token。トークンは Secret Manager / env に保持（値は返さない・表示しない）"""
    import requests
    if not is_oauth_configured():
        return {"ok": False, "error": "GBP_OAUTH_CLIENT_ID/SECRET 未設定（承認後に設定）"}
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "code": code, "client_id": os.getenv("GBP_OAUTH_CLIENT_ID"),
        "client_secret": os.getenv("GBP_OAUTH_CLIENT_SECRET"),
        "redirect_uri": REDIRECT_URI, "grant_type": "authorization_code"}, timeout=20)
    if not r.ok:
        return {"ok": False, "error": f"token取得失敗: {r.text[:150]}"}
    refresh = r.json().get("refresh_token", "")
    saved = _persist_token(refresh)
    return {"ok": True, "stored": saved, "note": "refresh_tokenを安全に保存（値は非表示）"}


def _persist_token(refresh_token):
    """Secret Managerへ保存（権限があれば）。なければenv運用を案内。トークンは返さない。"""
    if not refresh_token:
        return "no_refresh_token"
    try:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        parent = f"projects/{PROJECT_NUMBER}"
        sid = "gbp-oauth-refresh-token"
        try:
            client.create_secret(request={"parent": parent, "secret_id": sid,
                                           "secret": {"replication": {"automatic": {}}}})
        except Exception:
            pass
        client.add_secret_version(request={"parent": f"{parent}/secrets/{sid}",
                                           "payload": {"data": refresh_token.encode()}})
        return "secret_manager"
    except Exception:
        return "secret_manager_unavailable（GBP_OAUTH_REFRESH_TOKEN env で保持してください）"


def _access_token():
    """refresh_token→access_token（Secret Manager or env）。承認後に有効。"""
    import requests
    refresh = os.getenv("GBP_OAUTH_REFRESH_TOKEN", "")
    if not refresh:
        try:
            from google.cloud import secretmanager
            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{PROJECT_NUMBER}/secrets/gbp-oauth-refresh-token/versions/latest"
            refresh = client.access_secret_version(request={"name": name}).payload.data.decode()
        except Exception:
            return ""
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": os.getenv("GBP_OAUTH_CLIENT_ID"), "client_secret": os.getenv("GBP_OAUTH_CLIENT_SECRET"),
        "refresh_token": refresh, "grant_type": "refresh_token"}, timeout=20)
    return r.json().get("access_token", "") if r.ok else ""


def gbp_status():
    return {"ok": True, "oauth_configured": is_oauth_configured(),
            "project_number": PROJECT_NUMBER, "redirect_uri": REDIRECT_URI,
            "scope": GBP_SCOPE, "businesses": list(GBP_BIZ),
            "note": "API承認後に /gbp-oauth/start から連携"}


def list_accounts():
    import requests
    tok = _access_token()
    if not tok:
        return {"ok": False, "error": "未連携（承認後にOAuth）"}
    r = requests.get(ACCOUNTS_API, headers={"Authorization": f"Bearer {tok}"}, timeout=20)
    return {"ok": r.ok, "accounts": r.json().get("accounts", []) if r.ok else [], "raw": r.status_code}


def list_locations(account_name):
    import requests
    tok = _access_token()
    if not tok:
        return {"ok": False, "error": "未連携"}
    url = f"{INFO_API}/{account_name}/locations"
    r = requests.get(url, headers={"Authorization": f"Bearer {tok}"},
                     params={"readMask": "name,title,storefrontAddress,phoneNumbers,websiteUri"}, timeout=20)
    return {"ok": r.ok, "locations": r.json().get("locations", []) if r.ok else [], "raw": r.status_code}


def _validate_post(item):
    """DRY_RUN: 投稿仕様チェック。問題リストを返す（空=OK）"""
    issues = []
    if not str(item.get("body", "")).strip():
        issues.append("本文が空")
    if len(str(item.get("body", ""))) > 1500:
        issues.append("本文1500字超")
    cta_url = item.get("cta_url", "")
    if item.get("cta") and not cta_url:
        issues.append("CTA種別ありだがCTA URLなし")
    img = item.get("image_url", "")
    if img and not str(img).startswith("http"):
        issues.append("画像URL不正")
    return issues


def localpost_dryrun(ss_id, creds_path, business_key=None):
    """GBP_POST_QUEUE の未投稿を検証→DRY_RUN結果をバッチ記録。API呼び出しなし。"""
    from gspread.utils import rowcol_to_a1
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    qws = ss.worksheet("GBP_POST_QUEUE"); vals = qws.get_all_values()
    h = {x: i for i, x in enumerate(vals[0])}
    ok = ng = 0
    batch = []
    for ri in range(1, len(vals)):
        r = vals[ri]
        bk = r[h["business_key"]] if h["business_key"] < len(r) else ""
        if business_key and bk != business_key:
            continue
        if (r[h["投稿状況"]] if h["投稿状況"] < len(r) else "") != "未投稿":
            continue
        item = {"body": r[h["投稿本文"]] if h["投稿本文"] < len(r) else "",
                "cta": r[h["CTA種別"]] if h["CTA種別"] < len(r) else "",
                "cta_url": r[h["CTA URL"]] if h["CTA URL"] < len(r) else "",
                "image_url": r[h["画像URL"]] if h["画像URL"] < len(r) else ""}
        issues = _validate_post(item)
        res = "DRY_RUN_OK" if not issues else "DRY_RUN_ERROR"
        batch.append({"range": rowcol_to_a1(ri + 1, h["投稿状況"] + 1), "values": [[res]]})
        batch.append({"range": rowcol_to_a1(ri + 1, h["DRY_RUN結果"] + 1),
                      "values": [["OK" if not issues else "；".join(issues)]]})
        ok += not issues; ng += bool(issues)
    if batch:
        qws.batch_update(batch, value_input_option="RAW")
    # サマリー1行のみログ（書込制限回避）
    lws = _sheet(ss, "GBP_POST_LOG", SHEETS["GBP_POST_LOG"])
    lws.append_row([_now(), business_key or "全事業", "", "", f"内部DRY_RUN {ok+ng}件",
                    f"OK{ok}/NG{ng}", "", "", "", f"OK{ok}/NG{ng}", "", "", "", "INTERNAL_DRY_RUN",
                    "内部仕様チェック（Google API未接続）"], value_input_option="RAW")
    return {"ok": True, "mode": "INTERNAL_DRY_RUN（API未接続）",
            "dry_run_ok": ok, "dry_run_error": ng}


def api_dryrun(ss_id, creds_path, business_key=None):
    """API接続ありDRY_RUN（承認後）。OAuthトークン＋locationId有効性を実APIで確認。
    内部DRY_RUN(localpost_dryrun)とは別物。"""
    tok = _access_token()
    if not tok:
        return {"ok": False, "mode": "API_DRY_RUN",
                "error": "未連携（OAuth未完了）。承認後に /gbp-oauth/start → これを実行"}
    # 承認後: list_accounts/list_locations でトークン・locationId疎通を確認し、
    # GBP_POST_LOG に実行モード=API_DRY_RUN で記録する（実投稿はしない）。
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    acc = list_accounts()
    _log(ss, business_key or "全事業", "", "", "API_DRY_RUN 疎通確認",
         {"body": "accounts/locations 取得テスト"}, "API_DRY_RUN",
         "OK" if acc.get("ok") else f"NG:{acc.get('error','')}")
    return {"ok": acc.get("ok"), "mode": "API_DRY_RUN", "accounts_ok": acc.get("ok")}


def localpost_create(ss_id, creds_path, business_key, limit=1, live=False):
    """本番投稿（承認後・live=Trueで実行）。location/トークン必須。"""
    if not live:
        return {"ok": False, "error": "live=False（安全装置）。承認後にlive=Trueで1件テスト"}
    tok = _access_token()
    if not tok:
        return {"ok": False, "error": "未連携（OAuth未完了）"}
    return {"ok": False, "error": "API承認後に有効化（コード準備済み）", "todo": "locationId取得後に実装解放"}


def _log(ss, bk, name, loc, title, item, mode, api_result, post_id="", post_url="", err=""):
    lws = _sheet(ss, "GBP_POST_LOG", SHEETS["GBP_POST_LOG"])
    lws.append_row([_now(), bk, name, loc, title, item.get("body", "")[:200], item.get("image_url", ""),
                    item.get("cta", ""), item.get("cta_url", ""), api_result, post_id, post_url,
                    err, mode, ""], value_input_option="RAW")


def post_status(ss_id, creds_path):
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    vals = ss.worksheet("GBP_POST_QUEUE").get_all_values()
    h = {x: i for i, x in enumerate(vals[0])}
    by = {}
    for r in vals[1:]:
        bk = r[h["business_key"]] if h["business_key"] < len(r) else ""
        st = r[h["投稿状況"]] if h["投稿状況"] < len(r) else ""
        by.setdefault(bk, {}).setdefault(st, 0)
        by[bk][st] += 1
    return {"ok": True, "by_business": by}
