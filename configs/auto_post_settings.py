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
        "auto_post_enabled": False,        # 2026-07-04 初回実投稿成功確認後、通常運用前のため停止
        "business_name": "TACHINOMIYA",
        "daily_post_limit": 1,
        "posting_window": ("18:00", "21:00"),  # 通常運用ウィンドウ
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

# スロット別設定（時間帯×テーマ制御）
SLOT_CONFIG = {
    "tachinomiya_morning": {
        "business": "tachinomiya",
        "posting_window": ("10:00", "12:00"),
        "preferred_post_themes": ["sata_andagi", "tourist_general", "general"],
    },
    "tachinomiya_evening": {
        "business": "tachinomiya",
        "posting_window": ("18:00", "21:00"),
        "preferred_post_themes": ["drink", "tourist_general", "okinawa_food", "general"],
    },
    "catering_lunch": {
        "business": "catering",
        "posting_window": ("09:00", "11:00"),
        "preferred_post_themes": ["catering_food", "bento", "hors_doeuvre", "general"],
    },
    "catering_night": {
        "business": "catering",
        "posting_window": ("18:00", "20:00"),
        "preferred_post_themes": ["corporate_event", "setup", "decoration", "catering_food", "general"],
    },
    "beauty_morning": {
        "business": "beauty",
        "posting_window": ("11:00", "12:00"),
        "preferred_post_themes": [
            "salon_interior",   # 1. 安全（NG表現リスク最低）
            "hair_removal",     # 2. 主力サービス
            "whitening",        # 3. 主力サービス
            "yomogi",           # 4. 主力サービス
            "general_beauty",   # 5. フォールバック
        ],
    },
}

# Scheduler設計（毎日実行・曜日制限なし）
SCHEDULER_PLAN = {
    "tachinomiya_morning": {"cron": "0 10 * * *", "timezone": "Asia/Tokyo", "slot": "tachinomiya_morning"},
    "tachinomiya_evening": {"cron": "0 18 * * *", "timezone": "Asia/Tokyo", "slot": "tachinomiya_evening"},
    "catering_lunch":      {"cron": "0 9 * * *",  "timezone": "Asia/Tokyo", "slot": "catering_lunch"},
    "catering_night":      {"cron": "0 18 * * *", "timezone": "Asia/Tokyo", "slot": "catering_night"},
    # beauty_morning: 設計済み・未デプロイ。ゆうさん承認後に gcloud scheduler jobs create で追加すること。
    # 有効化条件: auto_post_enabled=True かつ 全テーマGCS化済み かつ HTTP200確認済み
    "beauty_morning":      {"cron": "0 11 * * *", "timezone": "Asia/Tokyo", "slot": "beauty_morning", "status": "NOT_DEPLOYED"},
}
