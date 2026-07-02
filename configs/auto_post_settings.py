"""
完全自動投稿 事業別設定
========================
auto_post_enabled=True にすれば完全自動投稿が動くが、初期値は全てFalse。
Scheduler ON前に手動でTrueに変更してから /threads-auto-post-full を呼ぶこと。

グローバルOFFスイッチ（最優先）:
  環境変数 AUTO_POST_MASTER_SWITCH=false で全事業即停止。
  Scheduler実行中でもこの変数で止められる。

Scheduler ON条件（20項目）を全て満たしてからのみ True に変更すること。
→ /threads-auto-post-ready-check で判定可能。
"""

# ── 事業別設定 ──────────────────────────────────────────────

AUTO_POST_CONFIG: dict[str, dict] = {
    "catering": {
        "business_name":               "TREE's Catering",
        "threads_username":            "trees_catering_",
        "auto_post_enabled":           False,       # ← True にすれば自動ON
        "image_post_enabled":          True,
        "daily_post_limit":            1,           # 1日最大投稿数
        "posting_window_start":        "10:30",     # JST投稿許可ウィンドウ（開始）
        "posting_window_end":          "12:00",     # JST投稿許可ウィンドウ（終了）
        "min_quality_score":           3,           # 品質スコア下限（0-5）
        "min_text_length":             60,          # 最低文字数
        "max_posts_per_day":           1,           # run_full_auto 1回あたり上限
        "requires_image":              True,        # 画像必須
        "fallback_to_text_allowed":    False,       # 画像なし時にテキストのみ投稿禁止
        "line_alert_enabled":          True,        # LINE通知有効
        "stop_on_error":               True,        # 連続エラー時自動停止
        "consecutive_error_threshold": 3,           # 連続エラー閾値（N回で停止）
        "status":                      "standby",   # standby / active / stopped / offline
        "notes":                       "画像付き投稿成功確認済み。Scheduler ON条件確認後にTrueに変更。",
    },
    "tachinomiya": {
        "business_name":               "TACHINOMIYA",
        "threads_username":            "tachinomiya.okinawa",
        "auto_post_enabled":           False,
        "image_post_enabled":          True,
        "daily_post_limit":            1,
        "posting_window_start":        "11:00",
        "posting_window_end":          "13:00",
        "min_quality_score":           3,
        "min_text_length":             60,
        "max_posts_per_day":           1,
        "requires_image":              True,
        "fallback_to_text_allowed":    False,
        "line_alert_enabled":          True,
        "stop_on_error":               True,
        "consecutive_error_threshold": 3,
        "status":                      "standby",
        "notes":                       "画像付き投稿成功確認済み。Scheduler ON条件確認後にTrueに変更。",
    },
    "beauty": {
        "business_name":               "Tree Beauty",
        "threads_username":            "tree.beauty_okinawa",
        "auto_post_enabled":           False,
        "image_post_enabled":          False,
        "daily_post_limit":            0,
        "posting_window_start":        "10:00",
        "posting_window_end":          "12:00",
        "min_quality_score":           3,
        "min_text_length":             60,
        "max_posts_per_day":           0,
        "requires_image":              True,
        "fallback_to_text_allowed":    False,
        "line_alert_enabled":          True,
        "stop_on_error":               True,
        "consecutive_error_threshold": 3,
        "status":                      "offline",
        "notes":                       "画像不足（0枚）のため自動投稿対象外。IMAGE_LIBRARY 20枚追加後に有効化。",
    },
    "ryukyu_hinabe": {
        "business_name":               "琉球火鍋",
        "threads_username":            "ryukyuhinabe",
        "auto_post_enabled":           False,
        "image_post_enabled":          False,
        "daily_post_limit":            0,
        "posting_window_start":        "11:00",
        "posting_window_end":          "14:00",
        "min_quality_score":           3,
        "min_text_length":             60,
        "max_posts_per_day":           0,
        "requires_image":              True,
        "fallback_to_text_allowed":    False,
        "line_alert_enabled":          True,
        "stop_on_error":               True,
        "consecutive_error_threshold": 3,
        "status":                      "offline",
        "notes":                       "画像不足（0枚）のため自動投稿対象外。IMAGE_LIBRARY 20枚追加後に有効化。",
    },
}


# ── Scheduler 設計（ON前の設計のみ・まだ追加しない） ─────────

SCHEDULER_DESIGN = {
    "catering_post": {
        "endpoint":       "/threads-auto-post-full",
        "body":           '{"dry_run":false,"biz_keys":["catering"]}',
        "schedule_cron":  "30 1 * * *",          # UTC 10:30 JST = 01:30 UTC
        "schedule_human": "毎日 10:30 JST",
        "timezone":       "Asia/Tokyo",
        "on_condition":   "catering成功3件以上 + READY判定後",
    },
    "tachinomiya_post": {
        "endpoint":       "/threads-auto-post-full",
        "body":           '{"dry_run":false,"biz_keys":["tachinomiya"]}',
        "schedule_cron":  "0 2 * * *",           # UTC 11:00 JST = 02:00 UTC
        "schedule_human": "毎日 11:00 JST",
        "timezone":       "Asia/Tokyo",
        "on_condition":   "tachinomiya成功3件以上 + READY判定後",
    },
    "insights_sync": {
        "endpoint":       "/threads-insights-sync-all",
        "schedule_cron":  "20 22 * * *",          # UTC 7:20 JST = 22:20 UTC (前日)
        "schedule_human": "毎日 7:20 JST",
        "timezone":       "Asia/Tokyo",
        "on_condition":   "即時追加可能（既存エンドポイント）",
    },
    "analyze": {
        "endpoint":       "/sns-analyze-all",
        "schedule_cron":  "25 22 * * *",
        "schedule_human": "毎日 7:25 JST",
        "timezone":       "Asia/Tokyo",
        "on_condition":   "即時追加可能（既存エンドポイント）",
    },
    "reuse": {
        "endpoint":       "/sns-reuse-actions-generate",
        "schedule_cron":  "30 22 * * *",
        "schedule_human": "毎日 7:30 JST",
        "timezone":       "Asia/Tokyo",
        "on_condition":   "即時追加可能（既存エンドポイント）",
    },
}


# ── READY判定 20条件 ───────────────────────────────────────

READY_CONDITIONS = [
    "自動候補選定（get_pending）",
    "画像自動選定（_resolve_image_for_threads + GCS キャッシュ）",
    "品質スコア自動判定（score_post ≥ 3）",
    "画像URL HTTP疎通確認（validate_image_url）",
    "username安全チェック（publish_image 内）",
    "token期限チェック（check_token_expiry 7日前警告）",
    "重複投稿防止（check_duplicate_post Jaccard ≥ 0.75）",
    "LINEアラート（send_threads_alert DRY_RUN確認済み）",
    "グローバルOFFスイッチ（AUTO_POST_MASTER_SWITCH env）",
    "連続エラー自動停止（count_consecutive_errors ≥ threshold）",
    "1日投稿上限（daily_post_limit=1）",
    "Scheduler設計完了（SCHEDULER_DESIGN）",
    "THREADS_ALERT_LOGへのログ保存",
    "インサイト自動同期（/threads-insights-sync-all）",
    "勝ち投稿自動分析（/sns-analyze-all）",
    "画像在庫監視（IMAGE_LIBRARY 登録数確認）",
    "投稿候補監視（SNS_POST_STOCK 未投稿数確認）",
    "事業別ON/OFF（auto_post_enabled per biz）",
    "テキストのみフォールバック禁止（fallback_to_text_allowed=False）",
    "ロールバック手順（git revert + auto_post_enabled=False）",
]


# ── ユーティリティ ─────────────────────────────────────────

def get_config(biz_key: str) -> dict | None:
    return AUTO_POST_CONFIG.get(biz_key)


def get_enabled_keys() -> list[str]:
    """auto_post_enabled=True の事業キーリスト"""
    return [k for k, v in AUTO_POST_CONFIG.items() if v.get("auto_post_enabled")]


def get_standby_keys() -> list[str]:
    """standby または active の事業キーリスト（offline除外）"""
    return [k for k, v in AUTO_POST_CONFIG.items() if v.get("status") in ("standby", "active")]
