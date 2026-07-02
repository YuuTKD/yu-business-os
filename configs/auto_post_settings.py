"""
自動投稿 事業別設定（Threads画像投稿）
--------------------------------------
auto_post_enabled = True にするまで全事業で自動投稿は起動しない。
環境変数 AUTO_POST_MASTER_SWITCH=false で全事業即停止。
"""

# グローバルOFFスイッチ（環境変数で上書き可）
MASTER_SWITCH_ENV = "AUTO_POST_MASTER_SWITCH"  # "false" で全停止

# 事業別設定
BUSINESS_AUTO_POST_CONFIG = {
    "catering": {
        "auto_post_enabled": False,       # 2026-07-02 初回実投稿成功確認後、通常運用前のため停止
        "business_name": "TREE's Catering",
        "daily_post_limit": 1,            # 1日最大投稿数
        "posting_window": ("09:00", "11:00"),  # 通常運用ウィンドウ
        "min_quality_score": 3,           # この未満の候補はスキップ
        "consecutive_error_limit": 3,     # 連続エラーでこの事業を自動停止
        "image_min_stock": 5,             # IMAGE_LIBRARY 最低在庫数（未満でWARN）
        "post_stock_min": 3,              # SNS_POST_STOCK 最低在庫数（未満でWARN）
    },
    "tachinomiya": {
        "auto_post_enabled": False,
        "business_name": "TACHINOMIYA",
        "daily_post_limit": 1,
        "posting_window": ("18:00", "21:00"),
        "min_quality_score": 3,
        "consecutive_error_limit": 3,
        "image_min_stock": 5,
        "post_stock_min": 3,
    },
    "beauty": {
        "auto_post_enabled": False,       # 画像補充後も False のまま維持
        "business_name": "Tree Beauty",
        "daily_post_limit": 1,
        "posting_window": ("10:00", "12:00"),
        "min_quality_score": 3,
        "consecutive_error_limit": 3,
        "image_min_stock": 20,            # 最低20枚必要
        "post_stock_min": 5,
    },
    "ryukyu_hinabe": {
        "auto_post_enabled": False,
        "business_name": "琉球火鍋",
        "daily_post_limit": 1,
        "posting_window": ("17:00", "20:00"),
        "min_quality_score": 3,
        "consecutive_error_limit": 3,
        "image_min_stock": 20,
        "post_stock_min": 5,
    },
}

# Scheduler設計（Cloud Schedulerに追加するときの設定案）
# 注: 現時点では Scheduler は未追加。追加許可後にこの設定を使う。
SCHEDULER_PLAN = {
    "catering":      {"cron": "0 9 * * *",  "timezone": "Asia/Tokyo"},
    "tachinomiya":   {"cron": "0 18 * * *", "timezone": "Asia/Tokyo"},
    "beauty":        {"cron": "0 10 * * *", "timezone": "Asia/Tokyo"},
    "ryukyu_hinabe": {"cron": "0 17 * * *", "timezone": "Asia/Tokyo"},
}
