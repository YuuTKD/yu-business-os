"""
Threads 投稿品質スコアリング（ルールベース・OpenAI不使用）
============================================================
score_post(text, biz_key) → {quality_score: 0-5, passed: [...], failed: [...]}

採点基準（各1点、合計6点 → 0-5スケールに変換）:
  1. 文字数60文字以上
  2. 事業テーマキーワードあり
  3. 具体的な情報あり（数字・メニュー名等）
  4. CTA（行動喚起）あり
  5. 形式的すぎない（コーポレート文体でない）
  6. 今出す意味がある（季節・タイミング性）

ハードNGチェック（いずれか該当で score=0 確定）:
  - NGワード含有
  - テキスト500文字超過
"""

import re
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))

# ── 事業別テーマキーワード ────────────────────────────────

_BIZ_KEYWORDS: dict[str, list[str]] = {
    "catering": [
        "ケータリング", "オードブル", "弁当", "法人", "会議", "イベント", "配達", "仕出し",
        "宴会", "ビュッフェ", "サンドイッチ", "お惣菜", "企業", "職場", "手配",
    ],
    "tachinomiya": [
        "立飲み", "たちのみや", "サーターアンダギー", "沖縄", "国際通り",
        "一杯", "ビール", "泡盛", "BAR", "スタンディング", "飲み", "おつまみ",
        "もつ", "ゆし豆腐", "あぐー", "アグー", "串", "肴",
    ],
    "beauty": [
        "脱毛", "美肌", "よもぎ蒸し", "ホワイトニング", "美容", "エステ", "ケア",
        "毛穴", "スキンケア", "セルフ", "サロン", "ツルツル", "白い歯",
    ],
    "ryukyu_hinabe": [
        "火鍋", "黒毛和牛", "アグー豚", "琉球", "個室", "しゃぶしゃぶ",
        "スープ", "白湯", "麻辣", "食べ放題", "飲み放題", "宴会", "女子会",
        "記念日", "コース", "牛肉", "豚肉", "野菜",
    ],
}
_BIZ_KEYWORDS["all"] = list({kw for kwlist in _BIZ_KEYWORDS.values() for kw in kwlist})

# ── CTA（行動喚起）ワード ─────────────────────────────────

_CTA_WORDS = [
    "ぜひ", "来てね", "来てください", "お越し", "予約", "注文", "詳細は",
    "チェック", "フォロー", "プロフ", "DM", "LINE", "お問い合わせ", "お待ち",
    "食べに", "飲みに", "試してみて", "見てみて", "覗いてみて", "気軽に",
    "お気軽に", "お電話", "ご連絡", "ご予約",
]

# ── NGワード（ハードNG） ──────────────────────────────────

_NG_WORDS = [
    "いつもお世話になっております",
    "平素よりお世話になっております",
    "ご不明な点がございましたら",
    "何卒よろしくお願い申し上げます",
    "本日もよろしくお願いいたします",
    "貴社のますますのご発展",
]

# ── 過度に形式的な表現 ────────────────────────────────────

_FORMAL_PATTERNS = [
    "スタッフ一同心よりお待ち申し上げております",
    "心よりお待ち申し上げております",
    "ご来店を心よりお待ちしております",
    "誠にありがとうございます",
    "何卒",
]

# ── 季節・タイミング性ワード ──────────────────────────────

_SEASONAL_ALWAYS = [
    "今日", "今週", "今月", "明日", "週末", "今夜", "夜", "ランチ", "ディナー",
    "期間限定", "季節", "限定", "新", "NEW", "本日", "今なら", "今だけ",
]
_SEASONAL_BY_MONTH: dict[tuple, list[str]] = {
    (3, 4, 5):   ["春", "花見", "新生活", "入学", "卒業", "歓迎", "さくら"],
    (6, 7, 8):   ["夏", "暑", "ビール", "冷たい", "納涼", "BBQ", "夏バテ", "冷やし"],
    (9, 10, 11): ["秋", "食欲", "ハロウィン", "秋冬", "肌寒"],
    (12, 1, 2):  ["冬", "忘年会", "新年", "クリスマス", "年末", "お正月", "鍋"],
}

# ── 具体的情報パターン ────────────────────────────────────

_SPECIFIC_PATTERNS = [
    r'\d+',                    # 数字（金額、人数、個数等）
    r'[A-Z]{2,}',             # 英字略語
    r'[¥￥]\d+',              # 価格
    r'\d+名',                  # 人数
    r'\d+種',                  # 種類
    r'\d+品',                  # 品数
]


def _current_seasonal_words() -> list[str]:
    month = datetime.now(JST).month
    for months, words in _SEASONAL_BY_MONTH.items():
        if month in months:
            return words
    return []


def score_post(text: str, biz_key: str = "") -> dict:
    """
    投稿テキストの品質スコアを0-5で返す。

    Returns:
        {
            "quality_score": 0-5,
            "passed": [...],   # 合格した基準
            "failed": [...],   # 不合格の基準
            "ng_hit": str,     # NGワード（ヒットした場合）
            "ok": bool,        # quality_score >= 3
        }
    """
    passed: list[str] = []
    failed: list[str] = []

    # ── ハードNGチェック ──
    for ng in _NG_WORDS:
        if ng in text:
            return {
                "quality_score": 0,
                "passed": [],
                "failed": ["NGワード含有"],
                "ng_hit": ng,
                "ok": False,
            }

    if len(text) > 500:
        return {
            "quality_score": 0,
            "passed": [],
            "failed": [f"文字数超過（{len(text)}字 > 500字）"],
            "ng_hit": "",
            "ok": False,
        }

    # ── ソフトチェック（各1点） ──

    # 1. 文字数60文字以上
    if len(text) >= 60:
        passed.append(f"文字数OK（{len(text)}字）")
    else:
        failed.append(f"文字数不足（{len(text)}字 < 60字）")

    # 2. 事業テーマキーワードあり
    biz_kws = _BIZ_KEYWORDS.get(biz_key, _BIZ_KEYWORDS.get("all", []))
    hit_kws = [kw for kw in biz_kws if kw in text]
    if hit_kws:
        passed.append(f"事業テーマあり（{hit_kws[0]}）")
    else:
        failed.append("事業テーマキーワードなし")

    # 3. 具体的な情報あり（数字・メニュー名等）
    has_specific = any(re.search(p, text) for p in _SPECIFIC_PATTERNS)
    all_specific_words = [w for biz_list in _BIZ_KEYWORDS.values() for w in biz_list]
    has_menu = any(w in text for w in all_specific_words)
    if has_specific or has_menu:
        passed.append("具体的情報あり")
    else:
        failed.append("具体的な情報なし（数字・メニュー名等）")

    # 4. CTA（行動喚起）あり
    hit_cta = next((w for w in _CTA_WORDS if w in text), None)
    if hit_cta:
        passed.append(f"CTA（行動喚起）あり（{hit_cta}）")
    else:
        failed.append("CTA（行動喚起）なし")

    # 5. 形式的すぎない
    is_formal = any(p in text for p in _FORMAL_PATTERNS)
    if not is_formal:
        passed.append("自然な文体")
    else:
        failed.append("過度に形式的な表現あり")

    # 6. 今出す意味がある（季節・タイミング性）
    seasonal_words = _SEASONAL_ALWAYS + _current_seasonal_words()
    hit_seasonal = next((w for w in seasonal_words if w in text), None)
    if hit_seasonal:
        passed.append(f"タイミング性あり（{hit_seasonal}）")
    else:
        failed.append("季節・タイミング性なし")

    # ── スコア計算（6点満点 → 0-5変換） ──
    # 0点→0, 1点→0, 2点→1, 3点→2, 4点→3, 5点→4, 6点→5
    raw = len(passed)
    quality_score = max(0, raw - 1)

    return {
        "quality_score": quality_score,
        "raw_score": raw,
        "max_raw": 6,
        "passed": passed,
        "failed": failed,
        "ng_hit": "",
        "ok": quality_score >= 3,
    }


def batch_score(posts: list[dict], biz_key: str = "", text_key: str = "text") -> list[dict]:
    """複数投稿を一括採点"""
    results = []
    for p in posts:
        text = str(p.get(text_key, "") or "")
        sq = score_post(text, biz_key)
        results.append({**p, **sq})
    return sorted(results, key=lambda x: x["quality_score"], reverse=True)
