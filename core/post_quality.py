"""
投稿品質スコアリング（ルールベース・OpenAI不使用）
---------------------------------------------------
score() は 0-10 の整数を返す。
threshold: configs/auto_post_settings.py の min_quality_score（既定3）未満はスキップ。
"""

import re

# キーワードリスト（加点）
HOOK_KEYWORDS = [
    "限定", "本日", "今だけ", "残り", "お得", "特別", "無料", "プレゼント",
    "キャンペーン", "割引", "クーポン", "先着", "期間限定", "新メニュー", "新作",
    "人気No.1", "人気ナンバーワン", "おすすめ", "イチオシ", "好評", "大好評",
]
CTA_KEYWORDS = [
    "予約", "問い合わせ", "お問い合わせ", "来店", "ご来店", "注文", "お電話", "DM",
    "詳しくは", "プロフィール", "リンク", "タップ", "クリック",
]
ENGAGEMENT_KEYWORDS = [
    "コメント", "いいね", "シェア", "保存", "フォロー", "タグ付け",
]
NG_KEYWORDS = [
    "テスト", "test", "TEST", "サンプル", "ダミー", "dummy", "削除予定",
    "★★★", "〇〇", "××", "XXXXXXX",
]

# 事業別推奨キーワード（存在すれば加点）
BIZ_KEYWORDS = {
    "catering": ["ケータリング", "オードブル", "弁当", "法人", "イベント", "会議"],
    "tachinomiya": ["立呑み", "たちのみ", "沖縄", "BAR", "バー", "泡盛", "サーターアンダギー"],
    "beauty": ["脱毛", "ホワイトニング", "よもぎ", "美容", "エステ"],
    "ryukyu_hinabe": ["火鍋", "琉球", "鍋", "宴会", "コース"],
}


def score(text: str, business: str = "") -> dict:
    """
    投稿テキストの品質スコアを計算。
    Returns: {"score": int, "details": dict, "ng_reason": str}
    """
    if not text or not text.strip():
        return {"score": 0, "details": {"empty": True}, "ng_reason": "本文が空"}

    t = text.strip()
    details = {}
    total = 0
    ng_reason = ""

    # NGワード検出 → 即0点
    for ng in NG_KEYWORDS:
        if ng in t:
            ng_reason = f"NGワード検出: {ng}"
            return {"score": 0, "details": {"ng_keyword": ng}, "ng_reason": ng_reason}

    # 文字数（0-2点）
    char_count = len(t)
    details["char_count"] = char_count
    if char_count >= 100:
        total += 2
    elif char_count >= 50:
        total += 1

    # 改行あり（0-1点）: 読みやすさ
    if "\n" in t:
        total += 1
        details["has_newline"] = True

    # ハッシュタグ（0-1点）: 3個以上で加点
    hashtags = re.findall(r"#\S+", t)
    details["hashtag_count"] = len(hashtags)
    if len(hashtags) >= 3:
        total += 1

    # フックキーワード（0-2点）
    found_hooks = [kw for kw in HOOK_KEYWORDS if kw in t]
    details["hook_keywords"] = found_hooks
    if found_hooks:
        total += min(2, len(found_hooks))

    # CTAキーワード（0-1点）
    found_cta = [kw for kw in CTA_KEYWORDS if kw in t]
    details["cta_keywords"] = found_cta
    if found_cta:
        total += 1

    # エンゲージメント誘導（0-1点）
    found_eng = [kw for kw in ENGAGEMENT_KEYWORDS if kw in t]
    details["engagement_keywords"] = found_eng
    if found_eng:
        total += 1

    # 疑問文（0-1点）: 読者への問いかけ
    if "？" in t or "?" in t:
        total += 1
        details["has_question"] = True

    # 事業別キーワード（0-1点）
    biz_kws = BIZ_KEYWORDS.get(business, [])
    found_biz = [kw for kw in biz_kws if kw in t]
    details["biz_keywords"] = found_biz
    if found_biz:
        total += 1

    # 上限10点
    total = min(total, 10)
    details["total"] = total
    return {"score": total, "details": details, "ng_reason": ng_reason}


def batch_score(rows: list, text_col_idx: int = 0, business: str = "") -> list:
    """
    行リスト（各行はリスト）に対してスコアリングを一括実行。
    Returns: [{"row_idx": int, "text": str, "score": int, ...}, ...]
    """
    results = []
    for i, row in enumerate(rows):
        text = row[text_col_idx] if len(row) > text_col_idx else ""
        r = score(text, business)
        results.append({"row_idx": i, "text": text[:80], **r})
    return results
