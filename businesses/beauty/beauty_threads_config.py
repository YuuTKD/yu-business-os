"""
Tree Beauty — Threads自動投稿設定（テーマ・NG表現・画像一致ルール）
作成：2026-07-06
目的：TACHINOMIYA/CATERINGと同一システムへの安全な組み込み準備

# 禁止事項
# - auto_post_enabled を True にするな（ゆうさん承認後のみ）
# - Scheduler を追加するな（ゆうさん承認後のみ）
# - SECRET/TOKEN値を表示するな
"""

# ─────────────────────────────────────────────────────
# STEP 2-3: テーマ定義 & Driveフォルダ→テーマ対応表
# ─────────────────────────────────────────────────────

# beauty用テーマ一覧
BEAUTY_THEMES = [
    "hair_removal",    # 脱毛
    "whitening",       # セルフホワイトニング
    "yomogi",          # よもぎ蒸し
    "cupping",         # カッピング（将来追加）
    "salon_interior",  # 店内・外観
    "staff",           # スタッフ
    "menu",            # メニュー・料金表
    "campaign",        # キャンペーン
    "general_beauty",  # 美容一般（フォールバック）
]

# Driveフォルダ名 → テーマキー 対応表
# 優先順位: カテゴリ列/Driveフォルダ名 > image_theme > allowed > blocked > visual_description(参考) > 推測(最後)
FOLDER_TO_THEME: dict[str, str] = {
    # 脱毛
    "脱毛":               "hair_removal",
    "ムダ毛":             "hair_removal",
    "除毛":               "hair_removal",
    "VIO":               "hair_removal",
    # セルフホワイトニング
    "セルフホワイトニング": "whitening",
    "ホワイトニング":       "whitening",
    "whitening":          "whitening",
    "歯":                 "whitening",
    # よもぎ蒸し
    "よもぎ蒸し":          "yomogi",
    "よもぎ":              "yomogi",
    "ヨモギ":              "yomogi",
    # カッピング（将来拡張用）
    "カッピング":          "cupping",
    "カッピングケア":       "cupping",
    # 店舗内観・外観
    "店舗内観":            "salon_interior",
    "店舗外観":            "salon_interior",
    "内観":               "salon_interior",
    "外観":               "salon_interior",
    "サロン":              "salon_interior",
    "店内":               "salon_interior",
    # スタッフ
    "スタッフ":            "staff",
    # メニュー・料金
    "メニュー":            "menu",
    "料金表":              "menu",
    "POP":               "menu",
    "価格":               "menu",
    # キャンペーン
    "キャンペーン":         "campaign",
    "特典":               "campaign",
    "割引":               "campaign",
    # 美容一般（曖昧フォールバック）
    "ビフォーアフター":     "general_beauty",  # Before/After は薬機法注意 → general扱い
    "お客様の声":          "general_beauty",   # 口コミは内容確認後のみ
    "美容":               "general_beauty",
    "一般":               "general_beauty",
}

# STRONGテーマ（曖昧カテゴリ画像をフォールバックで使ってはいけないテーマ）
# = 本文がこのテーマのとき、フォルダ名が明確に一致する画像のみ使う
STRONG_BEAUTY_THEMES = {
    "hair_removal",
    "whitening",
    "yomogi",
    "cupping",
}

# 曖昧カテゴリ（STRONGテーマ本文では使用禁止）
AMBIGUOUS_BEAUTY_CATEGORIES = {
    "general_beauty",
    "staff",
    "ビフォーアフター",
    "お客様の声",
}


# ─────────────────────────────────────────────────────
# STEP 4: allowed_post_themes / blocked_post_themes
# ─────────────────────────────────────────────────────

BEAUTY_THEME_RULES: dict[str, dict] = {
    "hair_removal": {
        "allowed_post_themes": ["hair_removal", "general_beauty", "campaign"],
        "blocked_post_themes": ["whitening", "yomogi", "cupping", "menu"],
    },
    "whitening": {
        "allowed_post_themes": ["whitening", "general_beauty", "campaign"],
        "blocked_post_themes": ["hair_removal", "yomogi", "cupping"],
    },
    "yomogi": {
        "allowed_post_themes": ["yomogi", "general_beauty", "campaign"],
        "blocked_post_themes": ["hair_removal", "whitening", "cupping"],
    },
    "cupping": {
        "allowed_post_themes": ["cupping", "general_beauty", "campaign"],
        "blocked_post_themes": ["hair_removal", "whitening", "yomogi"],
    },
    "salon_interior": {
        "allowed_post_themes": ["salon_interior", "general_beauty", "staff"],
        "blocked_post_themes": ["hair_removal", "whitening", "yomogi", "cupping"],
    },
    "staff": {
        "allowed_post_themes": ["staff", "salon_interior", "general_beauty"],
        "blocked_post_themes": ["hair_removal", "whitening", "yomogi", "cupping"],
    },
    "menu": {
        "allowed_post_themes": ["menu", "campaign", "general_beauty"],
        "blocked_post_themes": ["hair_removal", "whitening", "yomogi", "cupping"],
    },
    "campaign": {
        "allowed_post_themes": ["campaign", "menu", "general_beauty"],
        "blocked_post_themes": [],
    },
    "general_beauty": {
        "allowed_post_themes": ["general_beauty", "salon_interior"],
        "blocked_post_themes": [],
    },
}


# ─────────────────────────────────────────────────────
# STEP 5: 美容NG表現チェック（薬機法・誇大表現対策）
# ─────────────────────────────────────────────────────

# BLOCKワード（含んだら自動投稿禁止）
BEAUTY_BLOCK_WORDS: list[str] = [
    "絶対",
    "必ず",
    "100%",
    "永久",
    "完全に",
    "確実に",
    "治る",
    "治ります",
    "治った",
    "改善する",
    "改善します",
    "改善しました",
    "痩せる",
    "痩せます",
    "痩せました",
    "小顔になる",
    "小顔になります",
    "白くなる",           # 断定系のみ（「白くしたい」はOK）
    "効果を保証",
    "効果が保証",
    "保証します",
    "医学的に",
    "医療効果",
    "病気を治",
    "症状が改善",
    "Before/After",
    "ビフォーアフター保証",
    "個人差なし",
    "誰でも必ず",
    "不安にさせる",
    "コンプレックスを解消できる",  # 断定系
]

# REVISEワード（修正すれば投稿可）
BEAUTY_REVISE_WORDS: list[str] = [
    "効果あり",           # → 「効果を感じる方も」に変更
    "かならず",           # → 削除または「ぜひ」に変更
    "ぐんぐん",           # 誇大表現の可能性
    "劇的に",            # → 削除
    "みるみる",           # → 削除
    "すごく効く",          # → 削除
    "完璧な",            # → 削除
    "理想の体型に",        # 断定的な場合 → 「目指したい方へ」
    "コンプレックスを治す",  # → 「ケアしたい方へ」
]

# 安全表現（これらは積極的に使ってよい）
BEAUTY_SAFE_PHRASES: list[str] = [
    "目指したい方へ",
    "気になる方へ",
    "清潔感",
    "印象ケア",
    "自分磨き",
    "リラックスタイム",
    "すっきり感",
    "ご相談ください",
    "まずは体験から",
    "個人差があります",
    "体感する方も",
    "感じる方も",
    "お試しください",
    "気軽に体験",
]

# NG判定関数
def check_ng_expression(text: str) -> dict:
    """
    Returns:
      {"verdict": "PASS"|"REVISE"|"BLOCK", "reason": str, "found": list}
    """
    # BLOCKチェック（優先）
    block_found = [w for w in BEAUTY_BLOCK_WORDS if w in text]
    if block_found:
        return {
            "verdict": "BLOCK",
            "reason": f"自動投稿禁止ワード検出: {', '.join(block_found)}",
            "found": block_found,
        }

    # REVISEチェック
    revise_found = [w for w in BEAUTY_REVISE_WORDS if w in text]
    if revise_found:
        return {
            "verdict": "REVISE",
            "reason": f"修正推奨ワード検出: {', '.join(revise_found)}",
            "found": revise_found,
        }

    return {"verdict": "PASS", "reason": "NG表現なし", "found": []}


# ─────────────────────────────────────────────────────
# STEP 6: 本文×画像 一致チェック
# ─────────────────────────────────────────────────────

# 投稿本文テーマキーワード（extract_post_themeに追加すること）
BEAUTY_THEME_KEYWORDS: list[tuple[str, list[str]]] = [
    ("hair_removal", [
        "脱毛", "ムダ毛", "除毛", "VIO", "自己処理", "ツルツル", "毛が", "毛を",
        "剃る", "カミソリ", "埋没毛",
    ]),
    ("whitening", [
        "ホワイトニング", "歯を白く", "歯の白さ", "口元", "笑顔に自信",
        "歯が気になる", "白い歯",
    ]),
    ("yomogi", [
        "よもぎ蒸し", "よもぎ", "ヨモギ", "蒸し", "温活", "冷え", "デトックス",
        "リラックス", "体の中から",
    ]),
    ("cupping", [
        "カッピング", "吸い玉", "コリ", "肩こり", "血行",
    ]),
    ("salon_interior", [
        "サロン", "店内", "空間", "内観", "セルフ完全個室", "プライベート",
        "完全個室", "一人で", "スタッフが同席しない",
    ]),
    ("menu", [
        "料金", "メニュー", "価格", "円から", "コース", "プラン",
        "お得", "割引", "キャンペーン価格",
    ]),
    ("campaign", [
        "キャンペーン", "限定", "特別価格", "期間限定", "お得情報",
        "今だけ", "特典", "モニター",
    ]),
]

# 禁止組み合わせ（本文テーマ → 使ってはいけない画像テーマ）
MISMATCH_RULES: list[tuple[str, str, str]] = [
    # (本文テーマ, 禁止画像テーマ, 理由)
    ("whitening",    "hair_removal",   "ホワイトニング本文に脱毛画像は誤解を招く"),
    ("whitening",    "yomogi",         "ホワイトニング本文によもぎ蒸し画像は無関係"),
    ("whitening",    "cupping",        "ホワイトニング本文にカッピング画像は無関係"),
    ("hair_removal", "whitening",      "脱毛本文にホワイトニング画像は誤解を招く"),
    ("hair_removal", "yomogi",         "脱毛本文によもぎ蒸し画像は無関係"),
    ("hair_removal", "salon_interior", "脱毛本文に店内画像のみは説明不足"),
    ("hair_removal", "cupping",        "脱毛本文にカッピング画像は無関係"),
    ("yomogi",       "hair_removal",   "よもぎ蒸し本文に脱毛画像は無関係"),
    ("yomogi",       "whitening",      "よもぎ蒸し本文にホワイトニング画像は無関係"),
    ("yomogi",       "cupping",        "よもぎ蒸し本文にカッピング画像は無関係"),
    ("cupping",      "whitening",      "カッピング本文にホワイトニング画像は無関係"),
    ("cupping",      "hair_removal",   "カッピング本文に脱毛画像は無関係"),
    ("cupping",      "menu",           "カッピング本文に料金表だけの画像は説明不足"),
    ("campaign",     "hair_removal",   "注意: テーマ確認が必要"),  # campaign+脱毛本文は許可だが確認推奨
]


def check_image_theme_match(post_theme: str, image_theme: str) -> dict:
    """
    本文テーマと画像テーマの一致チェック。
    Returns: {"ok": bool, "reason": str}
    """
    rules = BEAUTY_THEME_RULES.get(post_theme, {})
    allowed = rules.get("allowed_post_themes", [])
    blocked = rules.get("blocked_post_themes", [])

    if image_theme in blocked:
        return {"ok": False, "reason": f"禁止組み合わせ: 本文={post_theme} × 画像={image_theme}"}
    if allowed and image_theme not in allowed:
        return {"ok": False, "reason": f"許可外: 本文={post_theme}に{image_theme}画像は使用不可"}
    return {"ok": True, "reason": "OK"}


# ─────────────────────────────────────────────────────
# STEP 7: 残り画像枚数通知設計
# ─────────────────────────────────────────────────────

# 最低在庫ライン
BEAUTY_IMAGE_MIN_STOCK: dict[str, int] = {
    "salon_interior":  10,
    "hair_removal":    10,
    "whitening":       10,
    "yomogi":          10,
    "cupping":          5,
    "menu":             5,
    "campaign":         5,
    "general_beauty":  10,
    "staff":            5,
}

# 通知レベル
def get_stock_alert_level(theme: str, remaining: int) -> str:
    """
    Returns: "🚨緊急" | "⚠️即補充" | "📷今週中" | "通常"
    """
    if remaining == 0:
        return "🚨緊急"
    elif remaining <= 3:
        return "⚠️即補充"
    elif remaining <= 5:
        return "📷今週中"
    else:
        return "通常"


def build_stock_report(theme_counts: dict[str, int]) -> str:
    """
    theme_counts: {"hair_removal": 8, "whitening": 3, ...}
    Returns: LINE通知用の在庫レポート文字列
    """
    lines = ["📊 画像在庫"]
    urgent_themes = []
    for theme, remaining in theme_counts.items():
        level = get_stock_alert_level(theme, remaining)
        lines.append(f"{theme}: 残り{remaining}枚 {level}")
        if level in ("🚨緊急", "⚠️即補充"):
            urgent_themes.append(theme)

    if urgent_themes:
        lines.append("")
        lines.append(f"📷 補充依頼: {', '.join(urgent_themes)}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────
# STEP 8: LINE通知フォーマット
# ─────────────────────────────────────────────────────

def build_success_notification(
    slot: str,
    theme: str,
    image_id: str,
    score: int,
    post_count_today: int,
    daily_limit: int,
    post_url: str,
    stock_report: str,
) -> str:
    return (
        f"✅ 【Tree Beauty】投稿完了\n"
        f"スロット: {slot}\n"
        f"テーマ: {theme}\n"
        f"画像: {image_id}\n"
        f"スコア: {score}\n"
        f"本日 {post_count_today}本目 / {daily_limit}本\n"
        f"投稿URL: {post_url}\n"
        f"\n"
        f"{stock_report}"
    )


def build_failure_notification(
    slot: str,
    step: str,
    reason: str,
    required_theme: str,
    remaining_count: int,
    next_action: str,
) -> str:
    return (
        f"❌ 【Tree Beauty】投稿失敗\n"
        f"スロット: {slot}\n"
        f"step: {step}\n"
        f"理由: {reason}\n"
        f"必要テーマ: {required_theme}\n"
        f"残り画像枚数: {remaining_count}枚\n"
        f"次アクション: {next_action}"
    )


# ─────────────────────────────────────────────────────
# STEP 9: Scheduler設計案（未適用・設計のみ）
# ─────────────────────────────────────────────────────

BEAUTY_SCHEDULER_PLAN = {
    "beauty_morning": {
        "job_name":          "beauty-threads-morning",
        "cron":              "0 11 * * *",      # 毎朝11:00 JST（最初は1日1投稿）
        "timezone":          "Asia/Tokyo",
        "daily_post_limit":  1,                  # 薬機法リスクで最初は1件/日
        "slot":              "beauty_morning",
        "dry_run":           False,              # 本番時はFalse（DRY_RUN時はTrue）
        "preferred_themes":  [                  # テーマ優先順
            "salon_interior",   # 1. 安全（NG表現リスク最低）
            "hair_removal",     # 2. 主力サービス
            "whitening",        # 3. 主力サービス
            "yomogi",           # 4. 主力サービス
            "general_beauty",   # 5. フォールバック
        ],
        "status":            "NOT_DEPLOYED",    # Scheduler追加前状態
    },
}

# Scheduler追加に必要なコマンド（ゆうさん承認後のみ実行）
# gcloud scheduler jobs create http beauty-threads-morning \
#   --schedule="0 11 * * *" \
#   --time-zone="Asia/Tokyo" \
#   --uri="https://yu-holdings-ai-XXXX.run.app/threads-auto-post" \
#   --message-body='{"slot":"beauty_morning","dry_run":false}' \
#   --project=tree-beauty-ai-499303 \
#   --location=asia-northeast1
