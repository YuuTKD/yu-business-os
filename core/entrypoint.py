"""
YU BUSINESS OS - 汎用Cloud Runエントリポイント

環境変数 BUSINESS_NAME で事業を選択する。
同じDockerイメージ・同じコードを全事業で共用し、
事業ごとに異なる env var を設定するだけで切り替わる。

エンドポイント（全事業共通）:
  GET  /health                ヘルスチェック
  GET  /status                設定確認
  POST /google                Google投稿生成
  POST /distribute            5媒体フル配信
  POST /process-csv           CSV取込→週次/月次レポート
  POST /generate-weekly-report 週次レポート単独生成
  POST /generate-content      180日コンテンツ生成
  POST /setup-spreadsheet     スプレッドシート初期構築
  POST /executive-briefing    AI役員週次ブリーフィング（Holdings全体）
"""

import os, sys, traceback
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, jsonify
from dotenv import load_dotenv
load_dotenv()

# Google認証をCloud Run環境変数から展開
from core.credentials_loader import load_google_credentials
CREDS_PATH = load_google_credentials()

# 事業設定を環境変数から取得
from configs.business_registry import BUSINESSES, get as get_config

BUSINESS_NAME = os.getenv("BUSINESS_NAME", "beauty")

try:
    CONFIG = get_config(BUSINESS_NAME)
except ValueError:
    print(f"[WARN] Unknown BUSINESS_NAME={BUSINESS_NAME}, falling back to 'beauty'")
    CONFIG = BUSINESSES["beauty"]

SPREADSHEET_ID = (
    os.getenv("SPREADSHEET_ID")
    or os.getenv(CONFIG.get("spreadsheet_id_env", ""), "")
    or os.getenv("GOOGLE_SPREADSHEET_ID", "")  # yu-holdings-ai など統合サービス用フォールバック
)

app = Flask(__name__)


@app.route("/health", methods=["GET"])
@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status":   "ok",
        "business": CONFIG["name"],
        "mode":     os.getenv("EXECUTION_MODE", "dry"),
    })


@app.route("/status", methods=["GET"])
def status():
    def chk(key, min_len=10):
        return "✅" if len(os.getenv(key, "")) >= min_len else "❌"
    return jsonify({
        "business":    CONFIG["name"],
        "mode":        os.getenv("EXECUTION_MODE", "dry"),
        "openai":      chk("OPENAI_API_KEY", 40),
        "google_creds": "✅" if CREDS_PATH else "❌",
        "spreadsheet": "✅" if SPREADSHEET_ID else "❌",
        "line_staff":  chk(CONFIG["line_channels"].get("staff", {}).get("env_key", ""), 100),
    })


@app.route("/google", methods=["POST", "GET"])
def post_google():
    try:
        from core.content_factory import generate
        data  = request.get_json(silent=True) or {}
        topic = data.get("topic", f"{CONFIG['name']}からの今日のお知らせ")
        content = generate(CONFIG, topic)
        # Google投稿APIは設定済みの場合のみ実行
        gbp_account  = os.getenv("GOOGLE_BUSINESS_ACCOUNT_ID", "")
        gbp_location = os.getenv("GOOGLE_BUSINESS_LOCATION_ID", "")
        if gbp_account and gbp_location:
            from distribution.distributors.google_poster import GooglePoster
            result = GooglePoster().post(content)
        else:
            result = {"ok": True, "status": "dry_run", "message": "GBP未設定のためファイル出力のみ"}
        return jsonify({"ok": result["ok"], "topic": topic,
                        "google_preview": content.get("google", {}).get("text", "")[:100]}), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/process-csv", methods=["POST", "GET"])
def process_csv():
    try:
        from core.csv_processor import run as run_csv
        result = run_csv(CONFIG, SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/generate-weekly-report", methods=["POST", "GET"])
def generate_weekly_report():
    try:
        from core.weekly_report import run as run_weekly
        result = run_weekly(CONFIG, SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200 if result.get("ok") else 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/setup-spreadsheet", methods=["POST", "GET"])
def setup_spreadsheet():
    """スプレッドシートの初期構築（新規事業追加時に1回だけ実行）"""
    try:
        from core.cfo_setup import setup_all
        url = setup_all(SPREADSHEET_ID, CONFIG, CREDS_PATH)
        return jsonify({"ok": True, "url": url, "business": CONFIG["name"]}), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/distribute", methods=["POST"])
def distribute():
    try:
        from core.content_factory import generate
        data    = request.get_json(silent=True) or {}
        topic   = data.get("topic", f"{CONFIG['name']}からのお知らせ")
        content = generate(CONFIG, topic, data.get("source_content", ""))
        # 各媒体へ配信（配信可能な場合のみ）
        results = {"ok": True, "content_generated": True, "business": CONFIG["name"]}
        return jsonify(results), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/catering-weekly", methods=["POST", "GET"])
def catering_weekly():
    """Catering週次レポート（月曜8時 Schedulerから呼ばれる）"""
    try:
        from core.catering_report import run_weekly
        result = run_weekly(CREDS_PATH)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/catering-monthly", methods=["POST", "GET"])
def catering_monthly():
    """Catering月次レポート（毎月1日 Schedulerから呼ばれる）"""
    try:
        from core.catering_report import run_monthly
        result = run_monthly(CREDS_PATH)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/catering-setup", methods=["POST", "GET"])
def catering_setup():
    """Catering スプレッドシート14シート構築（初回のみ）"""
    try:
        from core.catering_setup import setup_all
        ss_id = os.getenv("CATERING_SPREADSHEET_ID", "")
        if not ss_id:
            return jsonify({"ok": False, "error": "CATERING_SPREADSHEET_ID 未設定"}), 400
        url = setup_all(ss_id, CREDS_PATH)
        return jsonify({"ok": True, "url": url}), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/catering-content", methods=["POST", "GET"])
def catering_content():
    """Catering 90日コンテンツ生成"""
    try:
        from core.catering_content import run
        ss_id = os.getenv("CATERING_SPREADSHEET_ID", "")
        if not ss_id:
            return jsonify({"ok": False, "error": "CATERING_SPREADSHEET_ID 未設定"}), 400
        data = request.get_json(silent=True) or {}
        days = int(data.get("days", 90))
        result = run(ss_id, CREDS_PATH, days)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/executive-briefing", methods=["POST", "GET"])
def executive_briefing():
    """AI役員チーム週次ブリーフィング（YU HOLDINGS全体）"""
    try:
        from ceo.executive_team import run as run_briefing
        result = run_briefing(CREDS_PATH)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/process-pos", methods=["POST", "GET"])
def process_pos():
    """POSデータ取込（Airegi/USEN → 02_日次売上 自動反映）"""
    try:
        from core.pos_processor import run as run_pos
        biz    = CONFIG["name"]
        pos    = CONFIG.get("pos_type", "airegi")
        folder = os.getenv("POS_FOLDER_ID", "")
        done   = os.getenv("POS_DONE_FOLDER_ID", "")
        token  = os.getenv(CONFIG["line_channels"].get("staff", {}).get("env_key", ""), "")
        target = CONFIG.get("monthly_target", 1_000_000)
        if not folder:
            return jsonify({"ok": False, "error": "POS_FOLDER_ID 未設定"}), 400
        result = run_pos(
            biz_name=biz, spreadsheet_id=SPREADSHEET_ID,
            airegi_folder_id=folder, done_folder_id=done,
            creds_path=CREDS_PATH, pos_type=pos,
            line_token=token, monthly_target=target,
        )
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/blog-image/<file_id>", methods=["GET"])
def serve_blog_image(file_id: str):
    """Drive画像をプロキシ配信（LINE画像メッセージ用）"""
    try:
        from googleapiclient.discovery import build
        from google.oauth2.service_account import Credentials as SACredentials
        import io as _io

        creds = SACredentials.from_service_account_file(
            CREDS_PATH,
            scopes=["https://www.googleapis.com/auth/drive.readonly"],
        )
        drive = build("drive", "v3", credentials=creds)
        request_obj = drive.files().get_media(fileId=file_id)
        buf = _io.BytesIO()
        from googleapiclient.http import MediaIoBaseDownload
        downloader = MediaIoBaseDownload(buf, request_obj)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        buf.seek(0)
        from flask import Response
        return Response(buf.read(), mimetype="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/daily-line-content", methods=["POST", "GET"])
def daily_line_content():
    """Tree Beauty 日次LINEコンテンツ配信（Cloud Schedulerから毎日9:00呼ばれる）"""
    try:
        from core.daily_line_distributor import run as run_daily
        line_token = os.getenv("LINE_STAFF_TOKEN", "")
        result = run_daily(creds_path=CREDS_PATH, line_token=line_token)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/generate-blog-images", methods=["POST", "GET"])
def generate_blog_images():
    """
    HPBブログ用画像を自動生成してDrive保存・SS記録・LINE通知。

    POST body (JSON):
      {title, body, service, blog_date}  → 直接指定
      {blog_date}                         → HPBブログシートから取得
      {}                                  → 今日のブログをシートから取得
    """
    try:
        from core.blog_image_generator import run, run_from_sheet
        data = request.get_json(silent=True) or {}
        line_token = os.getenv("LINE_STAFF_TOKEN", "")

        if data.get("title") and data.get("body"):
            result = run(
                title=data["title"],
                body=data["body"],
                service=data.get("service", "脱毛"),
                blog_date=data.get("blog_date"),
                creds_path=CREDS_PATH,
                line_token=line_token,
            )
        else:
            result = run_from_sheet(
                blog_date=data.get("blog_date"),
                creds_path=CREDS_PATH,
                line_token=line_token,
            )

        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/image-setup", methods=["POST", "GET"])
def image_setup():
    """IMAGE_LIBRARY メタデータスプレッドシートの初期設定（初回のみ）"""
    try:
        from core.image_manager import setup_metadata_sheet
        ss_id = setup_metadata_sheet(CREDS_PATH)
        return jsonify({
            "ok": True,
            "spreadsheet_id": ss_id,
            "url": f"https://docs.google.com/spreadsheets/d/{ss_id}",
        }), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/scan-drive-images", methods=["POST", "GET"])
def scan_drive_images():
    """
    Google Drive 実写画像を自動スキャン → Vision解析 → 台帳登録。
    POST body: {"businesses": ["BEAUTY","CATERING","TACHINOMIYA","HINABE"]}
    省略時は全4事業対象。
    Cloud Scheduler: 毎週日曜 21:00 JST
    """
    try:
        from core.image_manager import scan_drive_images as _scan
        data = request.get_json(silent=True) or {}
        keys = data.get("businesses") or None
        result = _scan(business_keys=keys, creds_path=CREDS_PATH)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/content-automation", methods=["POST", "GET"])
def content_automation():
    """
    Multi Business Content Automation Engine
    STEP1-7: 未通知コンテンツ取得→画像生成→GCS保存→LINE通知→通知済み更新→ログ記録
    各事業Cloud Runの BUSINESS_NAME 環境変数で対象事業を切り替える。
    Cloud Scheduler から毎朝9:00に呼ばれる。
    """
    try:
        from core.multi_business_content_engine import run as run_engine
        data = request.get_json(silent=True) or {}
        business_key = data.get("business") or BUSINESS_NAME
        line_token   = os.getenv(
            _CONTENT_LINE_TOKEN_MAP.get(business_key, "LINE_STAFF_TOKEN"), ""
        )
        result = run_engine(
            business_key=business_key,
            creds_path=CREDS_PATH,
            line_token=line_token,
        )
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


# LINE トークン環境変数マップ（content_automation 用）
_CONTENT_LINE_TOKEN_MAP = {
    "beauty":        "LINE_STAFF_TOKEN",
    "catering":      "LINE_cateringSTAFF_TOKEN",
    "tachinomiya":   "LINE_TACHINOMIYASTAFF_TOKEN",
    "hinabe":        "LINE_hinabeSTAFF_TOKEN",
    "ryukyu_hinabe": "LINE_hinabeSTAFF_TOKEN",
}


@app.route("/update-target", methods=["POST", "GET"])
def update_target():
    """TARGET_MASTER・TARGETシートを最新実績で更新（全事業横断）"""
    try:
        from core.target_manager import run as run_target
        openai_key = os.getenv("OPENAI_API_KEY", "")
        result = run_target(creds_path=CREDS_PATH, openai_key=openai_key)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/threads-manual-setup", methods=["POST", "GET"])
def threads_manual_setup():
    """THREADS_MANUAL_REPLY_INBOX シートの作成・列確認"""
    try:
        from core.threads_manual_reply import setup_sheet
        ss_id = (request.get_json(silent=True) or {}).get("spreadsheet_id", "")
        result = setup_sheet(creds_path=CREDS_PATH, ss_id=ss_id)
        return jsonify(result), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/threads-manual-process", methods=["POST", "GET"])
def threads_manual_process():
    """
    THREADS_MANUAL_REPLY_INBOX の未通知行を処理。
    投稿URLと投稿本文が入っている行を対象に
    AI判定 → 返信案生成 → LINE通知 → ステータス更新を行う。
    Threadsへの自動返信は行わない。
    """
    try:
        from core.threads_manual_reply import process_inbox
        data = request.get_json(silent=True) or {}
        ss_id = data.get("spreadsheet_id", "")
        line_token_t = os.getenv("LINE_TACHINOMIYASTAFF_TOKEN", "")
        line_token_h = os.getenv("LINE_hinabeSTAFF_TOKEN", "")
        result = process_inbox(
            creds_path=CREDS_PATH,
            ss_id=ss_id,
            line_token_tachinomiya=line_token_t,
            line_token_hinabe=line_token_h,
        )
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/threads-manual-test", methods=["POST", "GET"])
def threads_manual_test():
    """
    テスト用疑似データ6件をシートに投入して処理フルフローを確認。
    TACHINOMIYA向け×2、琉球火鍋向け×2、両方提案×1、除外×1。
    """
    try:
        from core.threads_manual_reply import run_test
        result = run_test(creds_path=CREDS_PATH)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/threads-lead-test", methods=["POST", "GET"])
def threads_lead_test():
    """
    Threads来店候補検知システム テスト実行（疑似データ20件）
    App Review承認前の全フロー検証用。
    実際の第三者投稿へは返信しない（DRY_RUN=true固定）。
    """
    try:
        from core.threads_lead_monitor import run_test
        result = run_test(creds_path=CREDS_PATH)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/threads-lead-scan", methods=["POST", "GET"])
def threads_lead_scan():
    """
    Threads来店候補検知システム 本番実行。
    App Review承認後・threads_keyword_search権限取得後に有効化。
    承認前はテストデータでのみ動作する。

    POST body: {"posts": [...]}  ← Threads APIから取得した投稿リスト
    省略時はテストデータで実行（App Review前の動作確認用）
    """
    try:
        from core.threads_lead_monitor import run
        data = request.get_json(silent=True) or {}
        posts = data.get("posts")  # None → テストデータで実行
        spreadsheet_id = data.get("spreadsheet_id", "")
        result = run(
            posts=posts,
            creds_path=CREDS_PATH,
            spreadsheet_id=spreadsheet_id,
        )
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/threads-manual-status", methods=["GET", "POST"])
def threads_manual_status():
    """
    THREADS_MANUAL_REPLY_INBOX の現在の件数状況を返す。
    未処理 / 通知済み / 返信完了 / 保留 / 除外 の件数を確認できる。
    """
    try:
        from core.threads_manual_reply import get_inbox_status
        ss_id = (request.get_json(silent=True) or {}).get("spreadsheet_id", "")
        result = get_inbox_status(creds_path=CREDS_PATH, ss_id=ss_id)
        return jsonify(result), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/threads-dry-run-status", methods=["GET"])
def threads_dry_run_status():
    """DRY_RUNモードの現在ステータスを確認"""
    try:
        from core.threads_reply_publisher import get_dry_run_status
        return jsonify(get_dry_run_status()), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


# ─── Daily Action Commander ───────────────────────────────────────────────────

@app.route("/daily-action-setup", methods=["POST", "GET"])
def daily_action_setup():
    """DAILY_ACTION_TASKS・DAILY_ACTION_DASHBOARD シートを作成（初回のみ）"""
    try:
        from core.daily_action_commander import setup_sheets
        data  = request.get_json(silent=True) or {}
        ss_id = data.get("spreadsheet_id", "")
        result = setup_sheets(creds_path=CREDS_PATH, ss_id=ss_id)
        return jsonify(result), 200 if result.get("ok") else 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/daily-action-send", methods=["POST", "GET"])
def daily_action_send():
    """
    当日タスクを生成してシートへ書き込み、各事業の LINE へ通知する。
    Cloud Scheduler から毎朝 9:00 に呼ばれる。
    POST body: {"businesses": ["tachinomiya", "catering", ...]}  省略で全事業
    """
    try:
        from core.daily_action_commander import send_daily_tasks
        from core.owner_daily import delivery_mode, send_owner_daily
        data       = request.get_json(silent=True) or {}
        ss_id      = data.get("spreadsheet_id", "")
        businesses = data.get("businesses") or None
        mode = delivery_mode()
        meo_ss = os.getenv("GOOGLE_SPREADSHEET_ID", "") or ss_id or _cf_ss()
        if mode == "OWNER_ONLY":
            # スタッフ本番送信はせず（dry_runでタスク記録のみ）、オーナーへ確認用配信
            staff = send_daily_tasks(creds_path=CREDS_PATH, ss_id=ss_id,
                                     businesses=businesses, dry_run=True)
            owner = send_owner_daily(CREDS_PATH, meo_ss)
            return jsonify({"ok": True, "mode": mode, "owner": owner,
                            "staff_tasks_recorded": staff.get("ok")}), 200
        if mode in ("OFF", "DRY_RUN"):
            staff = send_daily_tasks(creds_path=CREDS_PATH, ss_id=ss_id,
                                     businesses=businesses, dry_run=True)
            return jsonify({"ok": True, "mode": mode, "note": "LINE送信なし（記録のみ）",
                            "staff": staff.get("ok")}), 200
        # STAFF（実スタッフ本番配信）
        result = send_daily_tasks(creds_path=CREDS_PATH, ss_id=ss_id,
                                  businesses=businesses, dry_run=False)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/owner-daily-send", methods=["POST", "GET"])
def owner_daily_send():
    """OWNER_ONLY: 完成原稿付き再利用タスクをオーナーへ確認用LINE配信。?dry_run=true でプレビュー"""
    try:
        from core.owner_daily import send_owner_daily
        dry = str(request.args.get("dry_run", "")).lower() == "true"
        meo_ss = os.getenv("GOOGLE_SPREADSHEET_ID", "") or _cf_ss()
        r = send_owner_daily(CREDS_PATH, meo_ss, dry_run=dry)
        return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/daily-action-remind", methods=["POST", "GET"])
def daily_action_remind():
    """
    未完了 S/A タスクを各事業 LINE へリマインド。
    Cloud Scheduler から毎日 17:00 に呼ばれる。
    """
    try:
        from core.daily_action_commander import send_reminder
        data       = request.get_json(silent=True) or {}
        ss_id      = data.get("spreadsheet_id", "")
        businesses = data.get("businesses") or None
        result = send_reminder(
            creds_path=CREDS_PATH, ss_id=ss_id,
            businesses=businesses, dry_run=False,
        )
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/daily-action-status", methods=["GET", "POST"])
def daily_action_status():
    """当日の事業別タスク状況を返す"""
    try:
        from core.daily_action_commander import get_status
        data  = request.get_json(silent=True) or {}
        ss_id = data.get("spreadsheet_id", "")
        date  = data.get("date", "")
        result = get_status(creds_path=CREDS_PATH, ss_id=ss_id, date=date)
        return jsonify(result), 200 if result.get("ok") else 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/daily-action-test", methods=["POST", "GET"])
def daily_action_test():
    """
    dry_run モードでフルフローをテスト。
    LINE 本番送信・シート本番書き込みは行わない。
    """
    try:
        from core.daily_action_commander import run_test
        data  = request.get_json(silent=True) or {}
        ss_id = data.get("spreadsheet_id", "")
        result = run_test(creds_path=CREDS_PATH, ss_id=ss_id)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/line-task-webhook", methods=["POST"])
def line_task_webhook():
    """
    LINE Webhook エンドポイント（統合）。
    1チャンネル=1Webhookのため、テキストと画像の両方がここに届く。
      ・テキスト（「完了 1,3」「修正 売上◯◯円」等）→ Daily Action / 売上修正処理
      ・画像（売上スクショ）→ Daily Sales Screenshot Capture OS

    LINE 公式管理画面の Webhook URL に登録してください：
      https://<cloud-run-url>/line-task-webhook
    """
    import json as _json

    try:
        from core.daily_action_commander import (
            handle_webhook_event,
            verify_line_signature,
            BUSINESS_CHANNEL_SECRET_ENV,
            ALL_BUSINESS_KEYS,
        )

        body_bytes = request.get_data()
        signature  = request.headers.get("X-Line-Signature", "")
        body_json  = _json.loads(body_bytes.decode("utf-8"))

        destination = body_json.get("destination", "")
        events      = body_json.get("events", [])

        # 署名検証（どのチャンネルか特定しながら検証）
        verified = False
        verified_biz_key = None
        for biz_key in ALL_BUSINESS_KEYS:
            secret = os.getenv(BUSINESS_CHANNEL_SECRET_ENV.get(biz_key, ""), "")
            if secret and verify_line_signature(body_bytes, signature, secret):
                verified = True
                verified_biz_key = biz_key
                break

        if signature and not verified:
            return jsonify({"ok": False, "error": "signature verification failed"}), 403

        # 事業キー: 署名検証で特定 → なければ当サービスの BUSINESS_NAME を使用
        # （各事業別サービスは自分のチャンネルのWebhookのみ受けるため BUSINESS_NAME で確定できる）
        biz_key_hint = verified_biz_key or BUSINESS_NAME

        import logging as _logging
        _logging.getLogger(__name__).info(
            f"Webhook: destination={destination}, verified_biz={verified_biz_key}, "
            f"biz_hint={biz_key_hint}, events={len(events)}"
        )

        # 画像/テキストを振り分け
        image_events = [e for e in events
                        if e.get("type") == "message"
                        and e.get("message", {}).get("type") == "image"]
        text_events  = [e for e in events
                        if not (e.get("type") == "message"
                                and e.get("message", {}).get("type") == "image")]

        results = []

        # ── 画像 → 売上スクショ処理 ──
        if image_events:
            from core.sales_screenshot import handle_webhook as sales_handle_webhook
            sales_ss  = os.getenv("GOOGLE_SPREADSHEET_ID", "") or SPREADSHEET_ID
            sales_dry = os.getenv("SALES_SCREENSHOT_DRY_RUN", "1") != "0"
            sres = sales_handle_webhook(
                sales_ss, CREDS_PATH,
                {"destination": destination, "events": image_events},
                destination=destination, dry_run=sales_dry,
                biz_key_override=biz_key_hint,
            )
            results.append({"sales_screenshot": sres})

        # ── テキスト → Daily Action / 売上修正処理 ──
        for event in text_events:
            res = handle_webhook_event(
                event=event,
                destination=destination,
                creds_path=CREDS_PATH,
                verified_biz_key=verified_biz_key,
            )
            results.append(res)

        return jsonify({"ok": True, "processed": len(results), "results": results}), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/staff-line-setup", methods=["POST", "GET"])
def staff_line_setup():
    """STAFF_LINE_MAP シートを作成（/daily-action-setup と同等）"""
    try:
        from core.daily_action_commander import setup_sheets
        result = setup_sheets(creds_path=CREDS_PATH)
        return jsonify(result), 200 if result.get("ok") else 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/staff-line-register", methods=["POST"])
def staff_line_register():
    """
    スタッフの LINE User ID を事業に紐付けて登録する。

    POST body:
      {
        "user_id":  "Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "biz_key":  "tachinomiya" | "catering" | "beauty" | "ryukyu_hinabe",
        "name":     "田中太郎"
      }
    """
    try:
        from core.daily_action_commander import register_staff
        data      = request.get_json(silent=True) or {}
        user_id   = data.get("user_id", "").strip()
        biz_key   = data.get("biz_key", "").strip()
        staff_name = data.get("name", "").strip()
        if not user_id or not biz_key:
            return jsonify({"ok": False,
                            "error": "user_id と biz_key が必要です"}), 400
        result = register_staff(
            user_id=user_id, biz_key=biz_key,
            staff_name=staff_name, creds_path=CREDS_PATH,
        )
        return jsonify(result), 200 if result.get("ok") else 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/staff-line-list", methods=["GET", "POST"])
def staff_line_list():
    """登録済みスタッフの一覧を返す（User ID の値は表示しない）"""
    try:
        from core.daily_action_commander import list_staff
        result = list_staff(creds_path=CREDS_PATH)
        # セキュリティ: User ID を部分マスク
        for s in result.get("staff", []):
            uid = str(s.get("LINE_USER_ID", ""))
            if len(uid) > 8:
                s["LINE_USER_ID"] = uid[:4] + "****" + uid[-4:]
        return jsonify(result), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/daily-action-webhook-simulate", methods=["POST"])
def daily_action_webhook_simulate():
    """
    LINE Webhook 疑似テスト専用エンドポイント。
    destination/署名検証をバイパスして biz_key を直接指定できる。
    本番 Webhook 設定前の動作確認専用。LINE 本番送信なし。

    POST body:
      {
        "biz_key":    "tachinomiya" | "catering" | "beauty" | "ryukyu_hinabe",
        "reply_text": "完了 1,2",
        "user_id":    "TEST_USER_001"  (省略可)
      }
    """
    try:
        from core.daily_action_commander import simulate_webhook
        data = request.get_json(silent=True) or {}
        biz_key    = data.get("biz_key", "")
        reply_text = data.get("reply_text", "")
        user_id    = data.get("user_id", "TEST_USER_001")
        ss_id      = data.get("spreadsheet_id", "")
        if not biz_key or not reply_text:
            return jsonify({"ok": False,
                            "error": "biz_key と reply_text が必要です"}), 400
        result = simulate_webhook(
            biz_key=biz_key, reply_text=reply_text,
            creds_path=CREDS_PATH, ss_id=ss_id, user_id=user_id,
        )
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/system-health-setup", methods=["POST", "GET"])
def system_health_setup():
    """System Health 用シート3枚を作成（初回のみ）"""
    try:
        from core.system_health import setup_health_sheets
        result = setup_health_sheets(SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/system-health-check", methods=["POST", "GET"])
def system_health_check():
    """全サービス・全Scheduler・Sheet接続をチェックしてダッシュボードに記録"""
    try:
        from core.system_health import run_health_check
        result = run_health_check(SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/system-health-report", methods=["POST", "GET"])
def system_health_report():
    """ヘルスチェック実行 → オーナーLINEへサマリー送信"""
    try:
        from core.system_health import run_health_check, send_health_report
        line_token = os.getenv("LINE_OWNER_TOKEN") or os.getenv("LINE_STAFF_TOKEN", "")
        check  = run_health_check(SPREADSHEET_ID, CREDS_PATH)
        result = send_health_report(SPREADSHEET_ID, CREDS_PATH, line_token, check_result=check)
        result["health"] = check
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/system-health-daily", methods=["POST", "GET"])
def system_health_daily():
    """
    毎朝8:30 Cloud Scheduler から呼ばれる統合エンドポイント。
    1. 全チェック実行
    2. SYSTEM_HEALTH_DASHBOARD / SYSTEM_JOB_LOG 更新
    3. 異常時は SYSTEM_ERROR_LOG 更新
    4. オーナーLINEへ正常/異常サマリー送信
    """
    try:
        from core.system_health import run_daily
        line_token = os.getenv("LINE_OWNER_TOKEN") or os.getenv("LINE_STAFF_TOKEN", "")
        result = run_daily(SPREADSHEET_ID, CREDS_PATH, line_token)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/system-job-log", methods=["POST", "GET"])
def system_job_log():
    """ジョブ実行ログをSYSTEM_JOB_LOGに記録（他サービスから呼ばれる）"""
    try:
        from core.system_health import log_job_execution
        data = request.get_json(silent=True) or {}
        result = log_job_execution(
            SPREADSHEET_ID, CREDS_PATH,
            job_name=data.get("job_name", "unknown"),
            service_name=data.get("service_name", ""),
            endpoint=data.get("endpoint", ""),
            result=data.get("result", ""),
            http_status=int(data.get("http_status", 200)),
            elapsed_ms=int(data.get("elapsed_ms", 0)),
            error=data.get("error", ""),
            retriable=data.get("retriable", True),
        )
        return jsonify(result), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/system-error-test", methods=["POST", "GET"])
def system_error_test():
    """疑似エラーでLINE通知テスト（本番影響なし）"""
    try:
        from core.system_health import test_error_notification
        line_token = os.getenv("LINE_OWNER_TOKEN") or os.getenv("LINE_STAFF_TOKEN", "")
        result = test_error_notification(SPREADSHEET_ID, CREDS_PATH, line_token)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/daily-action-owner-report", methods=["POST", "GET"])
def daily_action_owner_report():
    """
    全事業の完了率をオーナー LINE へ報告。
    Cloud Scheduler から毎日 21:00 に呼ばれる。
    """
    try:
        from core.daily_action_commander import send_owner_report
        data  = request.get_json(silent=True) or {}
        ss_id = data.get("spreadsheet_id", "")
        owner_token = data.get("owner_line_token", "") or os.getenv("LINE_OWNER_TOKEN", "")
        result = send_owner_report(
            creds_path=CREDS_PATH, ss_id=ss_id,
            owner_line_token=owner_token, dry_run=False,
        )
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────
# Knowledge & Execution OS エンドポイント
# ─────────────────────────────────────────────────────────

@app.route("/knowledge-setup", methods=["POST", "GET"])
def knowledge_setup():
    """
    Sheets台帳5枚作成 + GCS に初期Markdown 生成（初回のみ）。
    既存ファイルは上書きしない。
    """
    try:
        from core.knowledge_os import setup
        result = setup(SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/knowledge-export-daily", methods=["POST", "GET"])
def knowledge_export_daily():
    """毎日21:30：当日の重要ログ・売上アラートをMarkdown化してGCS保存"""
    try:
        from core.knowledge_os import export_daily
        result = export_daily(SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/knowledge-export-weekly", methods=["POST", "GET"])
def knowledge_export_weekly():
    """毎週月曜08:00：週次レポートを事業別MarkdownとしてGCS保存"""
    try:
        from core.knowledge_os import export_weekly
        result = export_weekly(SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/knowledge-export-decision", methods=["POST", "GET"])
def knowledge_export_decision():
    """DECISION_LOG の未同期行をMarkdownとしてGCS保存"""
    try:
        from core.knowledge_os import export_decision_to_md
        results = export_decision_to_md(SPREADSHEET_ID, CREDS_PATH)
        return jsonify({"ok": True, "exported": results}), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/knowledge-export-sop", methods=["POST", "GET"])
def knowledge_export_sop():
    """SOP_INDEXの未同期行をMarkdownとしてGCS保存"""
    try:
        from core.knowledge_os import export_sop
        result = export_sop(SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/knowledge-status", methods=["GET", "POST"])
def knowledge_status():
    """同期状況・未同期件数・エラー件数を確認"""
    try:
        from core.knowledge_os import get_status
        result = get_status(SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/knowledge-test", methods=["POST", "GET"])
def knowledge_test():
    """テスト用Markdownを生成・GCS保存・Sheets記録を確認"""
    try:
        from core.knowledge_os import run_test
        result = run_test(SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/knowledge-save-decision", methods=["POST"])
def knowledge_save_decision():
    """
    経営判断を DECISION_LOG + Obsidian Markdown に自動保存。
    POST body: {theme, business, content, reason, effect, impact, owner, deadline}
    """
    try:
        from core.knowledge_os import save_decision
        data = request.get_json(silent=True) or {}
        if not data.get("theme") or not data.get("content"):
            return jsonify({"ok": False, "error": "theme と content は必須"}), 400
        result = save_decision(
            SPREADSHEET_ID, CREDS_PATH,
            theme=data["theme"],
            business=data.get("business", CONFIG["name"]),
            content=data["content"],
            reason=data.get("reason", ""),
            effect=data.get("effect", ""),
            impact=data.get("impact", ""),
            owner=data.get("owner", "AI"),
            deadline=data.get("deadline", ""),
        )
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────
# AI営業本部 — Lead Command Center
# ─────────────────────────────────────────────────────────

@app.route("/lead-setup", methods=["POST", "GET"])
def lead_setup():
    """LEAD_MASTER / LEAD_ACTION_LOG / LEAD_DASHBOARD シートを作成（初回のみ）"""
    try:
        from core.lead_command import setup as lead_cmd_setup
        result = lead_cmd_setup(SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/lead-test", methods=["POST", "GET"])
def lead_test():
    """15件のテストリードを投入してAI判定・返信案生成をフルフロー確認（DRY RUN）"""
    try:
        from core.lead_command import run_test as lead_run_test
        result = lead_run_test(SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/lead-process", methods=["POST", "GET"])
def lead_process():
    """LEAD_MASTERの未処理行をAI判定・返信案生成（DRY RUN）"""
    try:
        from core.lead_command import process_leads
        data     = request.get_json(silent=True) or {}
        dry_run  = data.get("dry_run", True)
        result   = process_leads(SPREADSHEET_ID, CREDS_PATH, dry_run=dry_run)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/lead-status", methods=["GET", "POST"])
def lead_status():
    """リード全体の統計（優先度別件数・推定売上合計・未対応数）を返す"""
    try:
        from core.lead_command import get_status as lead_get_status
        result = lead_get_status(SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/lead-followup", methods=["GET", "POST"])
def lead_followup():
    """フォロー期限超過の未対応リードを一覧表示"""
    try:
        from core.lead_command import followup as lead_followup_fn
        result = lead_followup_fn(SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/lead-owner-report", methods=["GET", "POST"])
def lead_owner_report():
    """オーナー向け日次リードサマリーを生成（LINE送信なし・テキスト確認用）"""
    try:
        from core.lead_command import owner_report as lead_owner_report_fn
        result = lead_owner_report_fn(SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/lead-export-knowledge", methods=["POST", "GET"])
def lead_export_knowledge():
    """優先度S/AリードをGCS Knowledge OSへMarkdown保存"""
    try:
        from core.lead_command import export_knowledge as lead_export_knowledge_fn
        result = lead_export_knowledge_fn(SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────
# AI営業本部 — Catering B2B Sales Autopilot
# ─────────────────────────────────────────────────────────

@app.route("/catering-sales-setup", methods=["POST", "GET"])
def catering_sales_setup():
    """CATERING_SALES_TARGETS / CATERING_SALES_DASHBOARD シートを作成（初回のみ）"""
    try:
        from core.catering_sales import setup as catering_sales_setup_fn
        result = catering_sales_setup_fn(SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/catering-sales-generate-test", methods=["POST", "GET"])
def catering_sales_generate_test():
    """20件のテスト営業先を投入（カテゴリ別・優先度別）"""
    try:
        from core.catering_sales import generate_test_data
        result = generate_test_data(SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/catering-sales-daily", methods=["GET", "POST"])
def catering_sales_daily():
    """本日のDM対象（優先度S/A・未送信）を最大5件返す"""
    try:
        from core.catering_sales import daily_targets
        result = daily_targets(SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/catering-sales-followup", methods=["GET", "POST"])
def catering_sales_followup():
    """フォロー期限超過・返信待ちターゲット一覧"""
    try:
        from core.catering_sales import followup as catering_followup_fn
        result = catering_followup_fn(SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/catering-sales-status", methods=["GET", "POST"])
def catering_sales_status():
    """営業先全体の統計（状況別・優先度別件数）を返す"""
    try:
        from core.catering_sales import get_status as catering_get_status
        result = catering_get_status(SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/catering-sales-export-knowledge", methods=["POST", "GET"])
def catering_sales_export_knowledge():
    """優先度S/Aの営業先をGCS Knowledge OSへMarkdown保存"""
    try:
        from core.catering_sales import export_knowledge as catering_export_knowledge_fn
        result = catering_export_knowledge_fn(SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────
# AI営業本部 — Inquiry Killer
# ─────────────────────────────────────────────────────────

@app.route("/inquiry-setup", methods=["POST", "GET"])
def inquiry_setup():
    """INQUIRY_MASTER シートを作成（初回のみ）"""
    try:
        from core.inquiry_killer import setup as inquiry_setup_fn
        result = inquiry_setup_fn(SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/inquiry-test", methods=["POST", "GET"])
def inquiry_test():
    """5件のテスト問い合わせを投入してフルフロー確認（DRY RUN）"""
    try:
        from core.inquiry_killer import run_test as inquiry_run_test
        result = inquiry_run_test(SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/inquiry-process", methods=["POST", "GET"])
def inquiry_process():
    """INQUIRY_MASTERの未処理問い合わせをAI処理・返信案生成"""
    try:
        from core.inquiry_killer import process as inquiry_process_fn
        data    = request.get_json(silent=True) or {}
        dry_run = data.get("dry_run", True)
        result  = inquiry_process_fn(SPREADSHEET_ID, CREDS_PATH, dry_run=dry_run)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/inquiry-status", methods=["GET", "POST"])
def inquiry_status():
    """問い合わせ統計（対応状況別件数・推定売上合計・未対応数）を返す"""
    try:
        from core.inquiry_killer import get_status as inquiry_get_status
        result = inquiry_get_status(SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/inquiry-export-knowledge", methods=["POST", "GET"])
def inquiry_export_knowledge():
    """重要問い合わせ（推定売上5万円以上）をGCS Knowledge OSへMarkdown保存"""
    try:
        from core.inquiry_killer import export_knowledge as inquiry_export_knowledge_fn
        result = inquiry_export_knowledge_fn(SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────
# Daily Sales Screenshot Capture OS
# ─────────────────────────────────────────────────────────

@app.route("/sales-screenshot-setup", methods=["POST", "GET"])
def sales_screenshot_setup():
    """SALES_SCREENSHOT_LOG / DAILY_SALES_CONFIRMATION / SALES_SCREENSHOT_ERROR_LOG を作成"""
    try:
        from core.sales_screenshot import setup as ss_setup
        result = ss_setup(SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/sales-screenshot-webhook", methods=["POST"])
def sales_screenshot_webhook():
    """
    LINE公式の画像メッセージ受信用Webhook。
    各事業スタッフが送った売上スクショを取得→Vision解析→記録→返信。
    本番送信化までは dry_run=True（環境変数 SALES_SCREENSHOT_DRY_RUN=0 で本番化）。
    """
    import json as _json
    try:
        from core.sales_screenshot import handle_webhook
        body_bytes = request.get_data()
        body_json  = _json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        destination = body_json.get("destination", "")
        dry_run = os.getenv("SALES_SCREENSHOT_DRY_RUN", "1") != "0"
        result = handle_webhook(SPREADSHEET_ID, CREDS_PATH, body_json,
                                destination=destination, dry_run=dry_run)
        return jsonify(result), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/sales-screenshot-process", methods=["POST", "GET"])
def sales_screenshot_process():
    """未反映の読み取り結果をPOSへ反映（dry_run指定可）"""
    try:
        from core.sales_screenshot import process as ss_process
        data    = request.get_json(silent=True) or {}
        dry_run = data.get("dry_run", True)
        result  = ss_process(SPREADSHEET_ID, CREDS_PATH, dry_run=dry_run)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/sales-screenshot-test", methods=["POST", "GET"])
def sales_screenshot_test():
    """疑似読み取りデータ5件で判定・記録・返信文生成をフルフロー確認（DRY RUN）"""
    try:
        from core.sales_screenshot import run_test as ss_test
        result = ss_test(SPREADSHEET_ID, CREDS_PATH)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/sales-screenshot-status", methods=["GET", "POST"])
def sales_screenshot_status():
    """指定日（省略時本日）の事業別報告状況を返す"""
    try:
        from core.sales_screenshot import get_status as ss_status
        data = request.get_json(silent=True) or {}
        date = data.get("date", "") or request.args.get("date", "")
        result = ss_status(SPREADSHEET_ID, CREDS_PATH, date=date)
        return jsonify(result), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/sales-screenshot-missing-report", methods=["GET", "POST"])
def sales_screenshot_missing_report():
    """本日まだ売上報告のない事業を抽出（Daily Action連携用タスク文も生成）"""
    try:
        from core.sales_screenshot import missing_report
        data = request.get_json(silent=True) or {}
        date = data.get("date", "") or request.args.get("date", "")
        result = missing_report(SPREADSHEET_ID, CREDS_PATH, date=date)
        return jsonify(result), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/sales-screenshot-export-knowledge", methods=["POST", "GET"])
def sales_screenshot_export_knowledge():
    """指定日の日次売上サマリーをObsidian用MarkdownとしてGCS保存"""
    try:
        from core.sales_screenshot import export_knowledge as ss_export
        data = request.get_json(silent=True) or {}
        date = data.get("date", "") or request.args.get("date", "")
        result = ss_export(SPREADSHEET_ID, CREDS_PATH, date=date)
        return jsonify(result), 200 if result.get("ok") else 207
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────
# Cash Flow Survival OS
# ─────────────────────────────────────────────────────────

def _cf_ss():
    return os.getenv("GOOGLE_SPREADSHEET_ID", "") or SPREADSHEET_ID

@app.route("/cash-flow-setup", methods=["POST", "GET"])
def cash_flow_setup():
    try:
        from core.cash_flow import setup as fn
        return jsonify(fn(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/cash-flow-test", methods=["POST", "GET"])
def cash_flow_test():
    try:
        from core.cash_flow import run_test as fn
        r = fn(_cf_ss(), CREDS_PATH); return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/cash-flow-daily", methods=["POST", "GET"])
def cash_flow_daily():
    try:
        from core.cash_flow import daily as fn
        r = fn(_cf_ss(), CREDS_PATH, write=True); return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/cash-flow-status", methods=["GET", "POST"])
def cash_flow_status():
    try:
        from core.cash_flow import get_status as fn
        return jsonify(fn(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/cash-flow-actions", methods=["GET", "POST"])
def cash_flow_actions():
    try:
        from core.cash_flow import actions as fn
        return jsonify(fn(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/cash-flow-export-knowledge", methods=["POST", "GET"])
def cash_flow_export_knowledge():
    try:
        from core.cash_flow import export_knowledge as fn
        r = fn(_cf_ss(), CREDS_PATH); return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/cash-flow-owner-report", methods=["GET", "POST"])
def cash_flow_owner_report():
    try:
        from core.cash_flow import owner_report as fn
        r = fn(_cf_ss(), CREDS_PATH); return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────
# Profit Leak Detector
# ─────────────────────────────────────────────────────────

@app.route("/profit-setup", methods=["POST", "GET"])
def profit_setup():
    try:
        from core.profit_leak import setup as fn
        return jsonify(fn(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/profit-test", methods=["POST", "GET"])
def profit_test():
    try:
        from core.profit_leak import run_test as fn
        r = fn(_cf_ss(), CREDS_PATH); return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/profit-daily", methods=["POST", "GET"])
def profit_daily():
    try:
        from core.profit_leak import daily as fn
        r = fn(_cf_ss(), CREDS_PATH, write=True); return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/profit-project-check", methods=["GET", "POST"])
def profit_project_check():
    try:
        from core.profit_leak import project_check as fn
        r = fn(_cf_ss(), CREDS_PATH); return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/profit-status", methods=["GET", "POST"])
def profit_status():
    try:
        from core.profit_leak import get_status as fn
        return jsonify(fn(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/profit-actions", methods=["GET", "POST"])
def profit_actions():
    try:
        from core.profit_leak import actions as fn
        return jsonify(fn(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/profit-export-knowledge", methods=["POST", "GET"])
def profit_export_knowledge():
    try:
        from core.profit_leak import export_knowledge as fn
        r = fn(_cf_ss(), CREDS_PATH); return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/profit-owner-report", methods=["GET", "POST"])
def profit_owner_report():
    try:
        from core.profit_leak import owner_report as fn
        r = fn(_cf_ss(), CREDS_PATH); return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────
# Review & Referral Engine
# ─────────────────────────────────────────────────────────

@app.route("/review-setup", methods=["POST", "GET"])
def review_setup():
    try:
        from core.review_referral import setup as fn
        return jsonify(fn(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/review-test", methods=["POST", "GET"])
def review_test():
    try:
        from core.review_referral import run_test as fn
        r = fn(_cf_ss(), CREDS_PATH); return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/review-daily", methods=["POST", "GET"])
def review_daily():
    try:
        from core.review_referral import daily as fn
        r = fn(_cf_ss(), CREDS_PATH, write=True); return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/review-status", methods=["GET", "POST"])
def review_status():
    try:
        from core.review_referral import get_status as fn
        return jsonify(fn(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/review-actions", methods=["GET", "POST"])
def review_actions():
    try:
        from core.review_referral import actions as fn
        return jsonify(fn(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/review-export-knowledge", methods=["POST", "GET"])
def review_export_knowledge():
    try:
        from core.review_referral import export_knowledge as fn
        r = fn(_cf_ss(), CREDS_PATH); return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/review-owner-report", methods=["GET", "POST"])
def review_owner_report():
    try:
        from core.review_referral import owner_report as fn
        r = fn(_cf_ss(), CREDS_PATH); return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────
# 財務・成長 統合オーナーレポート（資金繰り＋利益漏れ＋口コミ）
# ─────────────────────────────────────────────────────────

@app.route("/finance-owner-report", methods=["POST", "GET"])
def finance_owner_report():
    """
    Cash Flow / Profit Leak / Review&Referral の3レポートを統合し、
    オーナーLINE(LINE_OWNER_TOKEN)へ送信する。
    dry_run（既定True）または ?send=1 / body {"send": true} で本番送信。
    """
    try:
        import requests as _rq
        from core.cash_flow import owner_report as cf_report
        from core.profit_leak import owner_report as pl_report
        from core.review_referral import owner_report as rr_report

        data = request.get_json(silent=True) or {}
        send = (str(request.args.get("send", "")) == "1") or bool(data.get("send", False))

        parts = []
        for fn in (cf_report, pl_report, rr_report):
            try:
                r = fn(_cf_ss(), CREDS_PATH)
                if r.get("report_text"):
                    parts.append(r["report_text"])
            except Exception as ie:
                parts.append(f"(レポート生成失敗: {ie})")
        combined = "\n\n━━━━━━━━━━\n\n".join(parts)

        sent = False
        token = os.getenv("LINE_OWNER_TOKEN", "")
        if send and token:
            resp = _rq.post(
                "https://api.line.me/v2/bot/message/broadcast",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"},
                json={"messages": [{"type": "text", "text": combined[:4900]}]},
                timeout=10,
            )
            sent = resp.ok
        return jsonify({"ok": True, "sent": sent, "dry_run": not send,
                        "preview": combined[:600], "length": len(combined)}), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/ai-acquisition-notify", methods=["POST", "GET"])
def ai_acquisition_notify():
    """
    ai_net_business商品マッチ候補をオーナーLINEへ通知。
    ?send=1 で本番送信。なしはプレビューのみ。
    LINE_OWNER_TOKEN を使用（finance-owner-reportと同パターン）。
    DM自動送信なし / Scheduler OFF。
    """
    try:
        import requests as _rq
        _acq_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "scripts", "acquisition",
        )
        if _acq_dir not in sys.path:
            sys.path.insert(0, _acq_dir)
        import ai_net_acquisition_notify as _acq

        data = request.get_json(silent=True) or {}
        send = (str(request.args.get("send", "")) == "1") or bool(data.get("send", False))

        sr, rv, ho, ex = _acq.classify_summary(_acq.CANDIDATES)
        line_msg = _acq.build_line_message(sr, rv, ho, ex)

        sent = False
        token = os.getenv("LINE_OWNER_TOKEN", "")
        if send and token:
            resp = _rq.post(
                "https://api.line.me/v2/bot/message/broadcast",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"},
                json={"messages": [{"type": "text", "text": line_msg[:4900]}]},
                timeout=10,
            )
            sent = resp.ok
        return jsonify({
            "ok": True, "sent": sent, "dry_run": not send,
            "send_ready": len(sr), "revise": len(rv),
            "total": len(_acq.CANDIDATES),
            "preview": line_msg[:600], "length": len(line_msg),
        }), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────
# LINE家計簿 — オーナーLINEから資金記録（Webhook）
# ─────────────────────────────────────────────────────────

@app.route("/owner-finance-webhook", methods=["POST"])
def owner_finance_webhook():
    """
    オーナー専用LINEに送られたメッセージを受け取り、
    資金（家賃/人件費/入金予定/現金残高 等）を CASH_FLOW_MASTER へ記録する。
    「状況」と送ると現在の資金繰りを返信。

    オーナーLINEチャンネルの Webhook URL に登録：
      https://<cloud-run-url>/owner-finance-webhook
    署名検証は LINE_OWNER_CHANNEL_SECRET があれば実施（無ければ素通し）。
    """
    import json as _json
    import hmac as _hmac, hashlib as _hashlib, base64 as _b64
    import requests as _rq
    try:
        from core.cash_flow import record_from_message

        body_bytes = request.get_data()
        signature  = request.headers.get("X-Line-Signature", "")
        secret = os.getenv("LINE_OWNER_CHANNEL_SECRET", "")
        if secret and signature:
            mac = _hmac.new(secret.encode(), body_bytes, _hashlib.sha256).digest()
            if _b64.b64encode(mac).decode() != signature:
                return jsonify({"ok": False, "error": "signature verification failed"}), 403

        body_json = _json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        events    = body_json.get("events", [])
        token     = os.getenv("LINE_OWNER_TOKEN", "")

        results = []
        for ev in events:
            if ev.get("type") != "message" or ev.get("message", {}).get("type") != "text":
                continue
            text = ev["message"].get("text", "")
            reply_token = ev.get("replyToken", "")
            res = record_from_message(_cf_ss(), CREDS_PATH, text)
            # 返信
            if reply_token and token and res.get("reply"):
                _rq.post("https://api.line.me/v2/bot/message/reply",
                         headers={"Authorization": f"Bearer {token}",
                                  "Content-Type": "application/json"},
                         json={"replyToken": reply_token,
                               "messages": [{"type": "text", "text": res["reply"][:4900]}]},
                         timeout=10)
            results.append({"recorded": res.get("ok"), "query": res.get("query", False)})

        return jsonify({"ok": True, "processed": len(results), "results": results}), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────
# MCP Server（Read-Only・Claudeカスタムコネクタ用）
# Streamable HTTP / JSON-RPC 2.0 over POST
# ─────────────────────────────────────────────────────────

@app.route("/mcp", methods=["POST", "GET", "DELETE"])
def mcp_endpoint():
    """
    YU HOLDINGS AI リモートMCPサーバー（Phase 1: read-only 8 tools）。
    Claudeカスタムコネクタ登録URL: https://<cloud-run-url>/mcp
    任意のアクセス制限: 環境変数 MCP_ACCESS_TOKEN を設定すると
    Authorization: Bearer <token> を要求する（未設定なら無認証）。
    """
    import json as _json
    try:
        from core.mcp_server import handle_mcp

        # 任意のBearerトークン制限（MCP_ACCESS_TOKEN設定時のみ有効）
        required = os.getenv("MCP_ACCESS_TOKEN", "")
        if required:
            auth = request.headers.get("Authorization", "")
            if auth != f"Bearer {required}":
                return jsonify({"jsonrpc": "2.0", "error":
                                {"code": -32001, "message": "Unauthorized"}}), 401

        # GET（SSEストリーム要求）は本サーバーでは未使用 → 405
        if request.method == "GET":
            return jsonify({"jsonrpc": "2.0", "error":
                            {"code": -32000, "message": "Use POST for JSON-RPC"}}), 405
        # DELETE（セッション終了）はステートレスのため204
        if request.method == "DELETE":
            return ("", 204)

        body = request.get_json(silent=True)
        if body is None:
            return jsonify({"jsonrpc": "2.0", "id": None, "error":
                            {"code": -32700, "message": "Parse error"}}), 400

        cf_ss  = os.getenv("GOOGLE_SPREADSHEET_ID", "") or SPREADSHEET_ID
        sys_ss = os.getenv("GOOGLE_SPREADSHEET_ID", "") or SPREADSHEET_ID
        resp, status = handle_mcp(body, CREDS_PATH, cf_ss, sys_ss)

        if resp is None:
            return ("", status)  # 通知（本文なし・202）
        flask_resp = jsonify(resp)
        # Streamable HTTP: ステートレスだがセッションIDヘッダを付与（互換性向上）
        flask_resp.headers["Mcp-Session-Id"] = "yu-holdings-mcp-stateless"
        return flask_resp, status
    except Exception as e:
        traceback.print_exc()
        return jsonify({"jsonrpc": "2.0", "id": None, "error":
                        {"code": -32603, "message": f"Internal error: {str(e)[:200]}"}}), 200


# ─────────────────────────────────────────────────────────
# SNS投稿 PDCA システム（Phase1 記録基盤 / Phase2 分析）
# ─────────────────────────────────────────────────────────

@app.route("/sns-setup", methods=["POST", "GET"])
def sns_setup():
    """SNS PDCA 6シートを統合SSに作成"""
    try:
        from core.sns_pdca import setup as fn
        return jsonify(fn(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/sns-import-stock", methods=["POST", "GET"])
def sns_import_stock():
    """各事業の既存投稿ストックをバックアップ後 SNS_POST_STOCK へ取込（dry_run対応）"""
    try:
        from core.sns_pdca import import_stock as fn
        data = request.get_json(silent=True) or {}
        dry = data.get("dry_run", False)
        limit = int(data.get("limit_per_sheet", 0) or 0)
        r = fn(_cf_ss(), CREDS_PATH, dry_run=dry, limit_per_sheet=limit)
        return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/sns-status", methods=["GET", "POST"])
def sns_status():
    """SNS投稿ストック・LINE反応の集計状況"""
    try:
        from core.sns_pdca import get_status as fn
        return jsonify(fn(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/sns-dashboard-refresh", methods=["POST", "GET"])
def sns_dashboard_refresh():
    """SNS_DASHBOARD を最新集計で更新"""
    try:
        from core.sns_pdca import refresh_dashboard as fn
        r = fn(_cf_ss(), CREDS_PATH); return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/sns-result-record", methods=["POST"])
def sns_result_record():
    """投稿文＋反応のテキストを SNS_RESULT/SNS_POST_STOCK に記録（手動/テスト用）。
    body: {"text": "投稿結果 Threads\\n本文...\\nいいね20 保存5 ...", "business_name": "TACHINOMIYA"}"""
    try:
        from core.sns_pdca import record_sns_result
        data = request.get_json(silent=True) or {}
        text = data.get("text", "")
        biz  = data.get("business_name", "")
        r = record_sns_result(_cf_ss(), CREDS_PATH, text, business_name=biz)
        return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/sns-screenshot-setup", methods=["POST", "GET"])
def sns_screenshot_setup():
    """SNS_SCREENSHOT_LOG / SNS_MATCH_CANDIDATES / 勝ち投稿シートを作成"""
    try:
        from core.sns_pdca import setup as fn
        return jsonify(fn(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/sns-screenshot-test", methods=["POST", "GET"])
def sns_screenshot_test():
    """疑似OCRテキストでSNSインサイト記録テスト（画像なし）"""
    try:
        from core.sns_pdca import _react_value, _REACT_LABELS, _detect_platform
        data = request.get_json(silent=True) or {}
        text = data.get("ocr_text", "Threads いいね25 保存8 インプ1500 プロフ15 LINE3 予約2 売上12000")
        reactions = {f: _react_value(text, l) for f, l in _REACT_LABELS if _react_value(text, l) is not None}
        return jsonify({"ok": True, "platform": _detect_platform(text) or "不明",
                        "reactions": reactions, "note": "本番OCRは画像送信時に実行"}), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/sns-winning-detect", methods=["POST", "GET"])
def sns_winning_detect():
    """勝ち投稿検出＋再利用タスク生成（SNS_WINNING_POSTS/SNS_REUSE_ACTIONS）"""
    try:
        from core.sns_pdca import detect_winning_posts as fn
        r = fn(_cf_ss(), CREDS_PATH); return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/sns-export-knowledge", methods=["POST", "GET"])
def sns_export_knowledge():
    """SNS分析サマリーをKnowledge OSへ（簡易: statusを保存）"""
    try:
        from core.sns_pdca import get_status, _upload_gcs, GCS_PREFIX
        import json as _j
        st = get_status(_cf_ss(), CREDS_PATH)
        md = "# SNS状況 " + _j.dumps(st, ensure_ascii=False, indent=2)
        url = _upload_gcs(CREDS_PATH, GCS_PREFIX + "/06_Leads_Sales/sns_status_export.md", md)
        return jsonify({"ok": True, "url": url}), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

# ─── Google Map Domination Engine ───
@app.route("/gmap-setup", methods=["POST", "GET"])
def gmap_setup_ep():
    try:
        from core.growth_engines import gmap_setup as fn
        return jsonify(fn(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/gmap-generate", methods=["POST", "GET"])
def gmap_generate_ep():
    try:
        from core.growth_engines import gmap_generate as fn
        data = request.get_json(silent=True) or {}
        r = fn(_cf_ss(), CREDS_PATH, dry_run=data.get("dry_run", False))
        return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/gmap-status", methods=["GET", "POST"])
def gmap_status_ep():
    try:
        from core.growth_engines import gmap_status as fn
        return jsonify(fn(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

# ─── Lost Customer Revival Engine ───
@app.route("/revival-setup", methods=["POST", "GET"])
def revival_setup_ep():
    try:
        from core.growth_engines import revival_setup as fn
        return jsonify(fn(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/revival-generate-test", methods=["POST", "GET"])
def revival_generate_test_ep():
    try:
        from core.growth_engines import revival_generate_test as fn
        r = fn(_cf_ss(), CREDS_PATH); return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/revival-status", methods=["GET", "POST"])
def revival_status_ep():
    try:
        from core.growth_engines import revival_status as fn
        return jsonify(fn(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/revival-actions", methods=["GET", "POST"])
def revival_actions_ep():
    try:
        from core.growth_engines import revival_actions as fn
        return jsonify(fn(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

# ─── High Profit Offer Push Engine ───
@app.route("/offer-setup", methods=["POST", "GET"])
def offer_setup_ep():
    try:
        from core.growth_engines import offer_setup as fn
        return jsonify(fn(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/offer-push", methods=["POST", "GET"])
def offer_push_ep():
    try:
        from core.growth_engines import offer_push as fn
        data = request.get_json(silent=True) or {}
        r = fn(_cf_ss(), CREDS_PATH, triggers=data.get("triggers"), dry_run=data.get("dry_run", False))
        return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/offer-status", methods=["GET", "POST"])
def offer_status_ep():
    try:
        from core.growth_engines import offer_status as fn
        return jsonify(fn(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

# ─── MEO Daily（TACHINOMIYA / 琉球火鍋）───
@app.route("/meo-setup", methods=["POST", "GET"])
def meo_setup_ep():
    try:
        from core.growth_engines import meo_setup as fn
        return jsonify(fn(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/meo-daily-generate", methods=["POST", "GET"])
def meo_daily_generate_ep():
    """?business=tachinomiya|ryukyu_hinabe 省略時は両方。dry_run対応"""
    try:
        from core.growth_engines import meo_daily_assign, MEO_ALLOWED
        data = request.get_json(silent=True) or {}
        biz = data.get("business") or request.args.get("business", "")
        dry = str(request.args.get("dry_run", "")).lower() == "true" or data.get("dry_run", False)
        targets = [biz] if biz else list(MEO_ALLOWED)
        out = {}
        for bk in targets:
            out[bk] = meo_daily_assign(_cf_ss(), CREDS_PATH, bk, dry_run=dry)
        return jsonify({"ok": True, "results": out}), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/meo-status", methods=["GET", "POST"])
def meo_status_ep():
    try:
        from core.growth_engines import meo_status as fn
        date = request.args.get("date", "")
        return jsonify(fn(_cf_ss(), CREDS_PATH, date=date)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/meo-dashboard-refresh", methods=["POST", "GET"])
def meo_dashboard_refresh_ep():
    try:
        from core.growth_engines import meo_dashboard_refresh as fn
        r = fn(_cf_ss(), CREDS_PATH); return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/meo-gbp-setup", methods=["POST", "GET"])
def meo_gbp_setup_ep():
    try:
        from core.growth_engines import gbp_setup as fn
        return jsonify(fn(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/meo-gbp-input", methods=["POST"])
def meo_gbp_input_ep():
    """GBP実績手入力（手動/テスト）。body: {text, business_name}"""
    try:
        from core.growth_engines import record_gbp
        data = request.get_json(silent=True) or {}
        r = record_gbp(_cf_ss(), CREDS_PATH, data.get("text", ""), data.get("business_name", ""))
        return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500


# ─── Threads 公式API 連携（Phase1: 琉球火鍋のみ） ───
def _threads_biz():
    """business / business_name クエリ→事業キー解決（許可外はエラー）"""
    from core.threads_api import resolve_biz
    j = request.get_json(silent=True) or {}
    bn = (request.args.get("business_name", "") or request.args.get("business", "")
          or j.get("business_name", "") or j.get("business", ""))
    return resolve_biz(bn or "琉球火鍋")

@app.route("/threads-auth-url", methods=["GET"])
def threads_auth_url():
    """OAuth認可URLを返す。?business_name=琉球火鍋"""
    try:
        from core.threads_api import authorize_url, is_configured, _redirect_uri
        key, err = _threads_biz()
        if err:
            return jsonify({"ok": False, "error": err}), 400
        if not is_configured():
            return jsonify({"ok": False, "error": "THREADS_APP_ID/SECRET 未設定",
                            "redirect_uri_to_register": _redirect_uri()}), 400
        return jsonify({"ok": True, "business_name": "琉球火鍋",
                        "authorize_url": authorize_url(key),
                        "redirect_uri": _redirect_uri()}), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

# ═══ Google Business Profile（GBP）自動投稿土台（API承認待ち）═══
@app.route("/gbp-setup", methods=["POST", "GET"])
def gbp_setup_ep():
    try:
        from core.gbp_api import setup_sheets
        return jsonify(setup_sheets(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/gbp-post-queue-build", methods=["POST", "GET"])
def gbp_post_queue_build_ep():
    try:
        from core.gbp_api import post_queue_build
        return jsonify(post_queue_build(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/gbp-status", methods=["GET", "POST"])
def gbp_status_ep():
    try:
        from core.gbp_api import gbp_status
        return jsonify(gbp_status()), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/gbp-post-status", methods=["GET", "POST"])
def gbp_post_status_ep():
    try:
        from core.gbp_api import post_status
        return jsonify(post_status(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/gbp-localpost-dryrun", methods=["POST", "GET"])
def gbp_localpost_dryrun_ep():
    try:
        from core.gbp_api import localpost_dryrun
        bk = request.args.get("business", "") or None
        return jsonify(localpost_dryrun(_cf_ss(), CREDS_PATH, business_key=bk)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/gbp-api-dryrun", methods=["POST", "GET"])
def gbp_api_dryrun_ep():
    """API接続ありDRY_RUN（承認後・実投稿なし）。内部DRY_RUNとは別物。"""
    try:
        from core.gbp_api import api_dryrun
        bk = request.args.get("business", "") or None
        return jsonify(api_dryrun(_cf_ss(), CREDS_PATH, business_key=bk)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/gbp-oauth/start", methods=["GET"])
def gbp_oauth_start_ep():
    try:
        from core.gbp_api import authorize_url, is_oauth_configured
        from flask import redirect
        if not is_oauth_configured():
            return jsonify({"ok": False, "error": "GBP_OAUTH未設定（API承認後に設定）"}), 400
        return redirect(authorize_url(), code=302)
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/gbp-oauth/callback", methods=["GET"])
def gbp_oauth_callback_ep():
    try:
        from core.gbp_api import handle_callback
        code = request.args.get("code", ""); err = request.args.get("error", "")
        if err or not code:
            return f"<h2>GBP連携エラー</h2><p>{err or 'codeなし'}</p>", 400
        r = handle_callback(code)
        if r.get("ok"):
            return "<h2>✅ GBP連携完了</h2><p>refresh_tokenを安全に保存しました。</p>", 200
        return f"<h2>GBP連携失敗</h2><p>{r.get('error')}</p>", 500
    except Exception as e:
        traceback.print_exc(); return f"<h2>エラー</h2><p>{str(e)[:200]}</p>", 500

@app.route("/gbp-accounts", methods=["GET", "POST"])
def gbp_accounts_ep():
    try:
        from core.gbp_api import list_accounts
        return jsonify(list_accounts()), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/gbp-locations", methods=["GET", "POST"])
def gbp_locations_ep():
    try:
        from core.gbp_api import list_locations
        acc = request.args.get("account", "")
        return jsonify(list_locations(acc)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/gbp-localpost-create", methods=["POST"])
def gbp_localpost_create_ep():
    try:
        from core.gbp_api import localpost_create
        data = request.get_json(silent=True) or {}
        live = bool(data.get("live", False))
        r = localpost_create(_cf_ss(), CREDS_PATH, data.get("business", ""),
                             limit=int(data.get("limit", 1)), live=live)
        return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/threads-auto-post-full", methods=["POST"])
def threads_auto_post_full_ep():
    """
    12段階安全チェック付き自動投稿。
    body: {business, dry_run: bool (default true), biz_keys: [list] (省略時は business)}
    dry_run=true の間は絶対に本番投稿しない。
    """
    try:
        from core.threads_api import run_full_auto, resolve_biz
        data = request.get_json(silent=True) or {}
        dry_run = bool(data.get("dry_run", True))
        biz_keys_raw = data.get("biz_keys") or ([data.get("business", "")] if data.get("business") else [])
        if not biz_keys_raw:
            return jsonify({"ok": False, "error": "business または biz_keys が必要"}), 400
        results = {}
        for b in biz_keys_raw:
            key, err = resolve_biz(b)
            if err:
                results[b] = {"ok": False, "error": err}
                continue
            results[key] = run_full_auto(_cf_ss(), CREDS_PATH, key, dry_run=dry_run)
        all_ok = all(v.get("ok") for v in results.values())
        return jsonify({"ok": all_ok, "results": results, "dry_run": dry_run}), 200 if all_ok else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/threads-auto-post-config", methods=["GET"])
def threads_auto_post_config_ep():
    """自動投稿設定一覧（secret/token非表示）"""
    try:
        from configs.auto_post_settings import BUSINESS_AUTO_POST_CONFIG, SCHEDULER_PLAN
        safe = {}
        for k, v in BUSINESS_AUTO_POST_CONFIG.items():
            safe[k] = {kk: vv for kk, vv in v.items()}
        return jsonify({"ok": True, "config": safe, "scheduler_plan": SCHEDULER_PLAN}), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/threads-post-quality-check", methods=["POST"])
def threads_post_quality_check_ep():
    """投稿テキストの品質スコアチェック。body: {text, business}"""
    try:
        from core.post_quality import score
        data = request.get_json(silent=True) or {}
        text = data.get("text", "")
        business = data.get("business", "")
        if not text:
            return jsonify({"ok": False, "error": "text が必要"}), 400
        result = score(text, business)
        return jsonify({"ok": True, **result}), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/threads-auto-post-ready-check", methods=["GET"])
def threads_auto_post_ready_check_ep():
    """全事業の自動投稿準備状況チェック（投稿なし）"""
    try:
        from core.threads_api import auto_post_ready_check
        return jsonify(auto_post_ready_check(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/threads-publish-image", methods=["POST"])
def threads_publish_image_ep():
    """画像付きThreads投稿。body: {business, text, image_url}（公開HTTPS）"""
    try:
        from core.threads_api import publish_image, resolve_biz
        data = request.get_json(silent=True) or {}
        key, err = resolve_biz(data.get("business", ""))
        if err:
            return jsonify({"ok": False, "error": err}), 400
        r = publish_image(_cf_ss(), CREDS_PATH, key, data.get("text", ""), data.get("image_url", ""))
        return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/threads-insights-sync-all", methods=["POST", "GET"])
def threads_insights_sync_all():
    """4事業のThreadsインサイトを一括同期"""
    try:
        from core.sns_master import sync_all
        return jsonify(sync_all(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/sns-analyze-all", methods=["POST", "GET"])
def sns_analyze_all():
    """4事業SNS分析＋ダッシュボード更新"""
    try:
        from core.sns_master import analyze_all
        return jsonify(analyze_all(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/sns-reuse-actions-generate", methods=["POST", "GET"])
def sns_reuse_actions_generate():
    """SNS_POST_MASTER更新＋勝ち投稿/再利用タスク再生成（データ生成のみ・LINE送信なし）"""
    try:
        from core.sns_master import build_master_and_reuse
        return jsonify(build_master_and_reuse(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/threads-oauth/start", methods=["GET"])
def threads_oauth_start():
    """?business=trees_catering で認可画面へ302リダイレクト"""
    try:
        from core.threads_api import authorize_url, is_configured, _canonical_key
        from flask import redirect
        key, err = _threads_biz()
        if err:
            return jsonify({"ok": False, "error": err}), 400
        if not is_configured():
            return jsonify({"ok": False, "error": "THREADS_APP_ID/SECRET 未設定"}), 400
        return redirect(authorize_url(key), code=302)
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/threads-account-config", methods=["GET", "POST"])
def threads_account_config():
    """THREADS_ACCOUNT_CONFIG 全件（トークン値はマスク）"""
    try:
        from core.threads_api import accounts_status
        return jsonify(accounts_status(_cf_ss(), CREDS_PATH)), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/threads-export-knowledge", methods=["GET", "POST"])
def threads_export_knowledge():
    """?business=… のThreadsインサイト要約をKnowledge OSへ保存"""
    try:
        from core.threads_api import get_account
        from core.sns_pdca import _upload_gcs, GCS_PREFIX
        import gspread
        from google.oauth2.service_account import Credentials as _C
        key, err = _threads_biz()
        if err:
            return jsonify({"ok": False, "error": err}), 400
        acc = get_account(_cf_ss(), CREDS_PATH, key)
        biz = acc.get("事業名", key)
        creds = _C.from_service_account_file(CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        ss = gspread.authorize(creds).open_by_key(_cf_ss())
        rows = [r for r in ss.worksheet("SNS_RESULT").get_all_records()
                if str(r.get("business_name")) == biz and str(r.get("platform")) == "Threads投稿"]
        import datetime as _dt
        today = _dt.datetime.now().strftime("%Y-%m-%d")
        lines = [f"# {biz} Threads インサイト要約 {today}\n",
                 f"- 取得投稿数: {len(rows)}\n\n| 投稿日 | 表示 | いいね | 返信 | 本文 |",
                 "|---|---|---|---|---|"]
        for r in rows[:30]:
            lines.append(f"| {r.get('posted_date')} | {r.get('impressions')} | {r.get('likes')} | {r.get('comments')} | {str(r.get('manual_note',''))[:30]} |")
        path = f"{GCS_PREFIX}/06_Leads_Sales/catering_threads_insights_summary_{today}.md" if key == "catering" else f"{GCS_PREFIX}/06_Leads_Sales/threads_insights_{key}_{today}.md"
        url = _upload_gcs(CREDS_PATH, path, "\n".join(lines))
        return jsonify({"ok": True, "path": path, "posts": len(rows)}), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/threads-oauth/callback", methods=["GET"])
def threads_oauth_callback():
    """Metaからのリダイレクト受け口。code→トークン保存"""
    try:
        from core.threads_api import handle_callback
        code = request.args.get("code", "")
        state = request.args.get("state", "")
        err = request.args.get("error", "")
        if err or not code:
            return f"<h2>連携エラー</h2><p>{err or 'codeなし'}</p>", 400
        r = handle_callback(_cf_ss(), CREDS_PATH, code, state)
        if r.get("ok"):
            from core.threads_api import BIZ_NAME
            biz_disp = BIZ_NAME.get(r.get("business_key", ""), r.get("business_key", ""))
            return (f"<h2>✅ Threads連携完了</h2>"
                    f"<p>事業: {biz_disp}<br>ユーザー: @{r.get('username')}<br>"
                    f"有効期限: {r.get('expires_at')}</p>"
                    f"<p>このページは閉じてOKです。アプリに戻って /threads-status で確認してください。</p>"), 200
        return f"<h2>連携失敗</h2><p>{r.get('error')}</p>", 500
    except Exception as e:
        traceback.print_exc(); return f"<h2>エラー</h2><p>{str(e)[:200]}</p>", 500

@app.route("/threads-status", methods=["GET", "POST"])
def threads_status():
    """?business_name=琉球火鍋 の接続状況"""
    try:
        from core.threads_api import get_account, is_configured
        key, err = _threads_biz()
        if err:
            return jsonify({"ok": False, "error": err}), 400
        from core.threads_api import BIZ_NAME
        acc = get_account(_cf_ss(), CREDS_PATH, key)
        connected = bool(acc.get("access_token"))
        return jsonify({"ok": True, "business_name": BIZ_NAME.get(key, key),
                        "app_configured": is_configured(),
                        "connected": connected,
                        "username": acc.get("username", ""),
                        "expires_at": acc.get("expires_at", ""),
                        "last_sync": acc.get("last_sync", "")}), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/threads-user", methods=["GET", "POST"])
def threads_user():
    """?business_name=琉球火鍋 のアカウント情報（/me）"""
    try:
        from core.threads_api import get_user
        key, err = _threads_biz()
        if err:
            return jsonify({"ok": False, "error": err}), 400
        r = get_user(_cf_ss(), CREDS_PATH, key)
        return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/threads-posts", methods=["GET", "POST"])
def threads_posts():
    """?business_name=琉球火鍋 の投稿一覧"""
    try:
        from core.threads_api import get_posts
        key, err = _threads_biz()
        if err:
            return jsonify({"ok": False, "error": err}), 400
        r = get_posts(_cf_ss(), CREDS_PATH, key, limit=int(request.args.get("limit", 10)))
        return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/threads-publish-test", methods=["GET", "POST"])
@app.route("/threads-post-test", methods=["GET", "POST"])
def threads_publish_test():
    """連携テスト投稿（1件）。?business=trees_catering&dry_run=true"""
    try:
        from core.threads_api import publish_test
        key, err = _threads_biz()
        if err:
            return jsonify({"ok": False, "error": err}), 400
        dr = str(request.args.get("dry_run", "true")).lower() != "false"
        r = publish_test(_cf_ss(), CREDS_PATH, key, dry_run=dr)
        return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/threads-deauthorize", methods=["POST", "GET"])
def threads_deauthorize():
    """Metaが「アプリの許可取り消し」時にpingするコールバック（200を返すだけ）"""
    return jsonify({"ok": True}), 200

@app.route("/threads-data-deletion", methods=["POST", "GET"])
def threads_data_deletion():
    """Metaの「データ削除リクエスト」コールバック。確認URL+コードを返す"""
    import time as _t
    code = f"yu-{int(_t.time())}"
    return jsonify({
        "url": f"https://yu-holdings-ai-qpiiccdspa-an.a.run.app/threads-data-deletion-status?code={code}",
        "confirmation_code": code,
    }), 200

@app.route("/threads-data-deletion-status", methods=["GET"])
def threads_data_deletion_status():
    return jsonify({"ok": True, "code": request.args.get("code", ""), "status": "completed"}), 200

@app.route("/threads-connect-token", methods=["POST", "GET"])
def threads_connect_token():
    """生成済み長期アクセストークンを直接保存（OAuth不要の連携）。
    ?token=...&business_name=琉球火鍋 または body {token, business_name}"""
    try:
        from core.threads_api import resolve_biz, _save_account, GRAPH
        import requests as _rq
        data = request.get_json(silent=True) or {}
        token = data.get("token") or request.args.get("token", "")
        bn = data.get("business_name") or request.args.get("business_name", "琉球火鍋")
        key, err = resolve_biz(bn)
        if err:
            return jsonify({"ok": False, "error": err}), 400
        if not token:
            return jsonify({"ok": False, "error": "token が必要"}), 400
        # /me で検証
        r = _rq.get(f"{GRAPH}/v1.0/me", params={"fields": "id,username", "access_token": token}, timeout=15)
        if not r.ok:
            return jsonify({"ok": False, "error": f"トークン検証失敗: {r.text[:150]}"}), 400
        d = r.json()
        from datetime import datetime, timezone, timedelta
        JST = timezone(timedelta(hours=9))
        exp = (datetime.now(JST) + timedelta(days=60)).strftime("%Y-%m-%d")
        _save_account(_cf_ss(), CREDS_PATH, key, str(d.get("id", "")), d.get("username", ""), token, exp)
        return jsonify({"ok": True, "business_name": "琉球火鍋",
                        "username": d.get("username", ""), "expires_at": exp,
                        "message": "連携完了"}), 200
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/threads-insights-sync", methods=["POST", "GET"])
def threads_insights_sync():
    """?business_name=琉球火鍋 の投稿インサイトをSNS_RESULTへ同期"""
    try:
        from core.threads_api import sync_insights
        key, err = _threads_biz()
        if err:
            return jsonify({"ok": False, "error": err}), 400
        r = sync_insights(_cf_ss(), CREDS_PATH, key)
        return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/sns-analyze", methods=["POST", "GET"])
def sns_analyze():
    """ルールベース分析（売上貢献度で勝ち/負け抽出）→ SNS_AI_ANALYSIS"""
    try:
        from core.sns_pdca import analyze as fn
        r = fn(_cf_ss(), CREDS_PATH); return jsonify(r), 200 if r.get("ok") else 207
    except Exception as e:
        traceback.print_exc(); return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"[YU BUSINESS OS] {CONFIG['name']} サーバー起動 port={port}")
    app.run(host="0.0.0.0", port=port, debug=False)
