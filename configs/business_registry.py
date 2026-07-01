"""
YU BUSINESS OS - 全事業設定レジストリ

新規事業追加手順:
1. このファイルに事業設定を追加
2. deploy/add_business.sh を実行（Cloud Run + Scheduler + Sheets 自動構築）
3. 完了（所要時間: 約30分）
"""

from typing import TypedDict

class BusinessConfig(TypedDict):
    name: str              # 事業正式名
    short_name: str        # Cloud Run サービス名 / env prefix
    email: str             # 事業メールアドレス
    location: str          # 所在地
    booking_url: str       # 予約・問い合わせURL
    monthly_target: int    # 月商目標（円）
    services: list         # サービスカテゴリ一覧
    menu_map: dict         # メニュー名→カテゴリ マッピング
    media_channels: list   # 集客媒体一覧
    content_themes: list   # コンテンツテーマ一覧（投稿生成用）
    line_channels: dict    # LINE channel設定
    platforms: list        # 投稿先SNS一覧
    csv_sources: list      # CSV取込元システム一覧
    business_type: str     # restaurant / salon / consulting / bar / retail


BUSINESSES: dict[str, BusinessConfig] = {

    # ─────────────────────────────────────
    # ① Tree Beauty（稼働中）
    # ─────────────────────────────────────
    "beauty": {
        "name": "Tree Beauty",
        "short_name": "beauty",
        "email": "tree.beauty.okinawa@gmail.com",
        "location": "沖縄県西原町",
        "booking_url": "https://beauty.hotpepper.jp/kr/slnH000532761/",
        "monthly_target": 500_000,
        "services": ["脱毛", "セルフホワイトニング", "よもぎ蒸し"],
        "menu_map": {
            "keywords": {
                "脱毛": ["脱毛", "ムダ毛", "除毛", "VIO", "vio"],
                "セルフホワイトニング": ["ホワイトニング", "whitening", "歯"],
                "よもぎ蒸し": ["よもぎ", "蒸し", "ヨモギ"],
            }
        },
        "media_channels": ["HPB", "LINE", "Instagram", "Google", "紹介", "直接"],
        "content_themes": [
            "脱毛の悩み・自己処理のストレス",
            "セルフホワイトニングで自信ある笑顔",
            "よもぎ蒸しで身体の中からキレイに",
            "沖縄のセルフ美容サロンという独自性",
        ],
        "line_channels": {
            "staff": {"env_key": "LINE_STAFF_TOKEN", "broadcast_ok": True},
            "datsumo": {"env_key": "LINE_DATSUMO_TOKEN", "broadcast_ok": False},  # 実顧客・要注意
            "whitening": {"env_key": "LINE_WHITENING_TOKEN", "broadcast_ok": False},  # 実顧客・要注意
        },
        "platforms": ["google", "instagram", "threads", "line", "hpb"],
        "csv_sources": ["airegi", "salonboard"],
        "business_type": "salon",
        "cloud_run_service": "tree-beauty-ai",
        "spreadsheet_id_env": "BEAUTY_SPREADSHEET_ID",
        "status": "active",
        "pos_folder_in":   "1jSMMTd8BEztLhTraN7O_OVj2I3wKq6dH",
        "pos_folder_done": "1YAUzIUGETe2NDCkgCj3J4oT3otQE7zmH",
    },

    # ─────────────────────────────────────
    # ② Trees Catering（未構築）
    # ─────────────────────────────────────
    "catering": {
        "name": "Trees Catering",
        "short_name": "catering",
        "email": "trees.catering098@gmail.com",
        "location": "沖縄県",
        "booking_url": "",  # 問い合わせフォームURLを設定
        "monthly_target": 800_000,
        "services": ["ケータリング", "オードブル", "会議用弁当", "来客用弁当"],
        "menu_map": {
            "keywords": {
                "ケータリング": ["ケータリング", "立食", "パーティー"],
                "オードブル": ["オードブル", "前菜", "盛り合わせ"],
                "会議用弁当": ["会議", "ミーティング", "弁当"],
                "来客用弁当": ["来客", "接待", "お弁当"],
            }
        },
        "media_channels": ["電話", "LINE", "WEB", "メール", "紹介", "直接"],
        "content_themes": [
            "旬の沖縄食材を使ったケータリング",
            "会議・イベントの食事手配をお任せ",
            "オードブルで特別な場を演出",
            "法人向け弁当の品質と信頼",
        ],
        "line_channels": {
            "staff": {"env_key": "CATERING_LINE_STAFF_TOKEN", "broadcast_ok": True},
            "customer": {"env_key": "CATERING_LINE_CUSTOMER_TOKEN", "broadcast_ok": True},
        },
        "platforms": ["google", "instagram", "threads", "line"],
        "csv_sources": ["airegi"],
        "business_type": "catering",
        "cloud_run_service": "trees-catering-ai",
        "spreadsheet_id_env": "CATERING_SPREADSHEET_ID",
        "spreadsheet_id": "1tNE35iQAVk6eTGEu68WDrRpv9FDIeVT_eK66iRi78Zs",
        "status": "active",
        "pos_folder_in":   "1k4Ncd1k7T5jiCEhd0oyz1CWYaiz5engR",
        "pos_folder_done": "1WzkAA6GXtDPVB5jjbbj64aFR-kIEGQyT",
    },

    # ─────────────────────────────────────
    # ③ Consulting - パスタパスタ（未構築）
    # ─────────────────────────────────────
    "pasta_pasta": {
        "name": "パスタパスタ",
        "short_name": "pasta_pasta",
        "email": "yuya_tokuda@trees-catering.com",
        "location": "沖縄県",
        "booking_url": "",
        "monthly_target": 2_000_000,
        "services": ["経営コンサルティング", "売上改善", "採用支援", "SNS運用支援"],
        "menu_map": {
            "keywords": {
                "経営顧問": ["顧問", "経営", "戦略"],
                "売上改善": ["売上", "集客", "マーケティング"],
                "採用": ["採用", "求人", "HR"],
                "SNS運用": ["SNS", "Instagram", "投稿"],
            }
        },
        "media_channels": ["紹介", "WEB", "メール", "直接"],
        "content_themes": [
            "飲食店の売上改善事例",
            "SNS集客の具体的な成果",
            "採用コストを下げる方法",
            "経営数字の見方・使い方",
        ],
        "line_channels": {
            "staff": {"env_key": "PASTA_LINE_STAFF_TOKEN", "broadcast_ok": True},
        },
        "platforms": ["google", "instagram", "line"],
        "csv_sources": ["airegi"],
        "business_type": "consulting",
        "cloud_run_service": "pasta-pasta-ai",
        "spreadsheet_id_env": "PASTA_SPREADSHEET_ID",
        "spreadsheet_id": "1MVz203ZMD4qoNdP5NZzTWCViQP3etGwOOVuae0XNQnw",
        "status": "active",
    },

    # ─────────────────────────────────────
    # ③ Consulting - Z1
    # ─────────────────────────────────────
    "z1": {
        "name": "Z1",
        "short_name": "z1",
        "email": "yuya_tokuda@trees-catering.com",
        "location": "沖縄県",
        "booking_url": "",
        "monthly_target": 1_500_000,
        "services": ["経営コンサルティング", "財務改善", "業務効率化", "デジタル化支援"],
        "menu_map": {
            "keywords": {
                "経営顧問": ["顧問", "経営", "戦略"],
                "財務改善": ["財務", "資金", "利益"],
                "業務効率化": ["業務", "効率", "DX"],
                "デジタル化": ["デジタル", "IT", "システム"],
            }
        },
        "media_channels": ["紹介", "WEB", "直接"],
        "content_themes": [
            "中小企業の財務改善",
            "業務効率化で人件費を削減",
            "デジタル化で競合に差をつける",
            "経営者が見るべき数字",
        ],
        "line_channels": {
            "staff": {"env_key": "Z1_LINE_STAFF_TOKEN", "broadcast_ok": True},
        },
        "platforms": ["google", "instagram", "line"],
        "csv_sources": ["airegi"],
        "business_type": "consulting",
        "cloud_run_service": "z1-ai",
        "spreadsheet_id_env": "Z1_SPREADSHEET_ID",
        "spreadsheet_id": "10YHdIxqIdk4WP9_AMXETs8GcS1YeKsEIQwaLcAVlCZ8",
        "status": "active",
    },

    # ─────────────────────────────────────
    # ④ TACHINOMIYA
    # ─────────────────────────────────────
    "tachinomiya": {
        "name": "TACHINOMIYA",
        "short_name": "tachinomiya",
        "email": "tachinomiya.kokusaidoori.okinawa@gmail.com",
        "location": "沖縄県那覇市国際通り",
        "booking_url": "",
        "monthly_target": 3_500_000,
        "services": ["サーターアンダギー専門（昼）", "カジュアルBAR（夜）", "Uber Eats", "出前館"],
        "menu_map": {
            "keywords": {
                "サーターアンダギー": ["サーター", "アンダギー", "揚げ菓子"],
                "ドリンク": ["ドリンク", "飲み物", "ビール", "酒", "カクテル"],
                "フード": ["おつまみ", "フード", "料理"],
                "デリバリー": ["Uber", "出前", "デリバリー"],
            }
        },
        "media_channels": ["直接", "Instagram", "Google", "Uber Eats", "出前館", "食べログ"],
        "content_themes": [
            "沖縄の定番おやつ・サーターアンダギー",
            "仕事帰りのカジュアルな一杯",
            "国際通りの隠れ家的立ち飲みBAR",
            "デリバリーで自宅でも沖縄の味",
        ],
        "line_channels": {
            "staff": {"env_key": "TACHINOMIYA_LINE_STAFF_TOKEN", "broadcast_ok": True},
            "customer": {"env_key": "TACHINOMIYA_LINE_CUSTOMER_TOKEN", "broadcast_ok": True},
        },
        "platforms": ["google", "instagram", "threads", "line"],
        "csv_sources": ["airegi", "ubereats", "demaekan"],
        "business_type": "restaurant",
        "cloud_run_service": "tachinomiya-ai",
        "spreadsheet_id_env": "TACHINOMIYA_SPREADSHEET_ID",
        "spreadsheet_id": "1K4KkAhFwVkQqqvzeqa25-1sR26ltBfP9gY9h-N4gXcc",
        "status": "active",
        "pos_folder_in":   "1IfjRjHPhG7rnUceSImaW-EeHCxUpVGKd",
        "pos_folder_done": "1cXkIa8H9gfI_qflhDYfjTfGF2TjxXXK8",
    },

    # ─────────────────────────────────────
    # ⑤ 琉球火鍋（未構築）
    # ─────────────────────────────────────
    "ryukyu_hinabe": {
        "name": "琉球火鍋",
        "short_name": "ryukyu_hinabe",
        "email": "ryukyuhinabe2025@gmail.com",
        "location": "沖縄県",
        "booking_url": "",  # 食べログ / 直接予約URLを設定
        "monthly_target": 1_500_000,
        "services": ["火鍋コース", "単品メニュー", "飲み放題", "テイクアウト"],
        "menu_map": {
            "keywords": {
                "火鍋コース": ["コース", "火鍋", "セット"],
                "単品": ["単品", "追加", "食材"],
                "飲み放題": ["飲み放題", "ドリンク", "アルコール"],
                "テイクアウト": ["テイクアウト", "持ち帰り"],
            }
        },
        "media_channels": ["食べログ", "Google", "Instagram", "LINE", "直接", "紹介"],
        "content_themes": [
            "身体の中から温まる本格火鍋",
            "沖縄で食べられる本場の辛さ",
            "特別な日の火鍋コース",
            "シメのラーメン・雑炊まで楽しめる",
        ],
        "line_channels": {
            "staff": {"env_key": "HINABE_LINE_STAFF_TOKEN", "broadcast_ok": True},
            "customer": {"env_key": "HINABE_LINE_CUSTOMER_TOKEN", "broadcast_ok": True},
        },
        "platforms": ["google", "instagram", "threads", "line"],
        "csv_sources": ["usen", "tabelog"],
        "pos_type": "usen",
        "business_type": "restaurant",
        "cloud_run_service": "ryukyu-hinabe-ai",
        "spreadsheet_id_env": "HINABE_SPREADSHEET_ID",
        "spreadsheet_id": "1jwFmQtrertjIc6yYFJEyDptLdSUgD5xLdHDAxQhIQzw",
        "status": "active",
    },
}


def get(short_name: str) -> BusinessConfig:
    if short_name not in BUSINESSES:
        raise ValueError(f"Unknown business: {short_name}. Available: {list(BUSINESSES.keys())}")
    return BUSINESSES[short_name]


def list_active() -> list[str]:
    return [k for k, v in BUSINESSES.items() if v.get("status") == "active"]


def list_all() -> list[str]:
    return list(BUSINESSES.keys())
