"""
投稿テーマ自動判定 & 画像テーマ許可/禁止ルール
------------------------------------------------------
- extract_post_theme(text, biz_key) で投稿本文からテーマを抽出
- IMAGE_LIBRARY の image_theme / blocked_post_themes / allowed_post_themes 列と照合
- テーマ不一致画像を除外し、ミスマッチ投稿を防止する
"""

# 事業別：テーマキーワード（リスト上位が優先判定）
THEME_KEYWORDS: dict = {
    "tachinomiya": [
        ("sata_andagi", [
            "サーターアンダギー", "アンダギー", "揚げたて", "沖縄スイーツ",
            "食べ歩き", "昼営業", "おやつ", "サーター",
        ]),
        ("drink", [
            "一杯", "カウンター", "BAR", "バー", "夜営業",
            "立ち飲み", "乾杯", "飲み歩き",
        ]),
        ("rafute", [
            "ラフテー", "豚肉", "煮込み",
        ]),
        ("tourist_general", [
            "観光", "国際通り", "沖縄旅行", "旅行者",
        ]),
    ],
    "catering": [
        ("catering_food", [
            "料理", "ケータリング", "オードブル", "パーティー",
        ]),
    ],
    "beauty": [],
    "ryukyu_hinabe": [],
}


def extract_post_theme(text: str, biz_key: str) -> str:
    """
    投稿本文からテーマキーを抽出する。
    マッチしない / 事業ルール未定義 の場合は 'general' を返す。
    """
    for theme_key, keywords in THEME_KEYWORDS.get(biz_key, []):
        if any(kw in text for kw in keywords):
            return theme_key
    return "general"
