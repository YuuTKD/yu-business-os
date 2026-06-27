"""
Threads返信案生成モジュール

投稿内容を解析し、TACHINOMIYA または 琉球火鍋 への来店候補として
返信文を個別生成する（GPT-4o-mini使用）。

固定文の繰り返し禁止、120〜220文字、毎回個別生成。
"""

import os
import re
import json
import datetime
from openai import OpenAI

# ─── 店舗情報 ───────────────────────────────────────────
TACHINOMIYA_INFO = {
    "name": "TACHINOMIYA",
    "url": "https://share.google/NEhQjtFRTqVkf2Lno",
    "keywords": [
        "国際通り", "サーターアンダギー", "1人", "ひとり", "一人",
        "BAR", "バー", "立ち飲み", "昼", "ランチ", "軽食",
        "カジュアル", "気軽", "観光途中", "観光", "居酒屋",
        "沖縄料理", "泡盛", "昼飲み", "飲み", "夜",
    ],
    "features": "国際通り沿いのカジュアルな立ち飲みBAR。昼はサーターアンダギー、夜は沖縄料理とお酒を気軽に楽しめる。1人でも入りやすく観光途中にも立ち寄りやすい。",
    "pitch": "1人でも入りやすく、国際通り沿いで観光途中に寄りやすいです。昼はサーターアンダギーも楽しめます。",
}

HINABE_INFO = {
    "name": "琉球火鍋",
    "url": "https://share.google/qvVymJEMw4bLAzeb4",
    "keywords": [
        "個室", "記念日", "女子会", "会食", "しゃぶしゃぶ", "火鍋",
        "薬膳", "黒毛和牛", "アグー豚", "アグー", "落ち着いた",
        "雰囲気", "特別", "ゆっくり", "ゆったり", "グループ",
    ],
    "features": "全室個室の沖縄しゃぶしゃぶ×薬膳火鍋。黒毛和牛やアグー豚を楽しめる。記念日・女子会・会食に最適で落ち着いた雰囲気。",
    "pitch": "全室個室なので、女子会や記念日、ゆっくり食事したい場合にも使いやすいです。",
}

# ─── 除外キーワード ──────────────────────────────────────
EXCLUDE_KEYWORDS = [
    "レシピ", "作り方", "自炊", "家で作", "求人", "募集", "採用",
    "通販", "お取り寄せ", "お取り寄", "旅行終わり", "旅行が終わ", "帰りました",
    "帰宅しました", "帰ってきた", "振り返り", "振り返ます",
    "当店", "うちの店", "宣伝", "フォロー", "リポスト",
    "県外", "東京", "大阪", "福岡",
]

# 店舗推薦を求めていない投稿パターン
NON_SEARCH_PATTERNS = [
    r"(最高|美味しかった|食べました|行ってきた|行きました|食べてきた)[^？?]*$",
    r"^[^？?]*料理が(好き|好きです|うまい)[^？?]*$",
]


def _keyword_score(text: str, keywords: list[str]) -> int:
    """キーワードマッチ数を返す"""
    t = text.lower()
    return sum(1 for kw in keywords if kw.lower() in t)


def select_store(post_text: str) -> dict:
    """
    投稿本文から推奨店舗を選択する。

    戻り値:
      {"stores": ["tachinomiya"], "reason": "..."}
      {"stores": ["hinabe"], "reason": "..."}
      {"stores": ["tachinomiya", "hinabe"], "reason": "..."}
      {"stores": [], "reason": "no_match"}
    """
    t_score = _keyword_score(post_text, TACHINOMIYA_INFO["keywords"])
    h_score = _keyword_score(post_text, HINABE_INFO["keywords"])

    stores = []
    if t_score > 0 and h_score > 0 and abs(t_score - h_score) <= 1:
        stores = ["tachinomiya", "hinabe"]
        reason = f"両店マッチ(TACHINOMIYA:{t_score}, 琉球火鍋:{h_score})"
    elif h_score > t_score:
        stores = ["hinabe"]
        reason = f"琉球火鍋マッチ(score:{h_score})"
    elif t_score > 0:
        stores = ["tachinomiya"]
        reason = f"TACHINOMIYAマッチ(score:{t_score})"
    else:
        # キーワード未マッチでも沖縄で飲食店を探しているなら両方提案
        stores = ["tachinomiya", "hinabe"]
        reason = "キーワードなし・沖縄飲食需要あり（両店提案）"

    return {"stores": stores, "reason": reason}


def generate_reply(post_text: str, stores: list[str], openai_key: str = "") -> str:
    """
    投稿内容に合わせた個別返信案をGPT-4o-miniで生成する。
    生成失敗時はルールベースのフォールバックを返す。

    戻り値: 返信文（URL含む、120〜220文字）
    """
    key = openai_key or os.getenv("OPENAI_API_KEY", "")
    if key and len(stores) > 0:
        try:
            reply = _generate_with_gpt(post_text, stores, key)
            if 100 <= len(reply) <= 250:
                return reply
        except Exception:
            pass

    return _fallback_reply(post_text, stores)


def _generate_with_gpt(post_text: str, stores: list[str], openai_key: str) -> str:
    """GPT-4o-mini で個別返信文を生成"""
    client = OpenAI(api_key=openai_key)

    store_info_parts = []
    urls = []
    for s in stores:
        info = TACHINOMIYA_INFO if s == "tachinomiya" else HINABE_INFO
        store_info_parts.append(f"・{info['name']}: {info['features']}")
        urls.append(f"\n{info['url']}")

    stores_text = "\n".join(store_info_parts)
    url_text = "".join(urls)

    today_weekday = ["月", "火", "水", "木", "金", "土", "日"][datetime.datetime.now().weekday()]

    system_prompt = f"""あなたは沖縄のグルメに詳しいローカルガイドです。
Threadsの投稿に対して自然で親しみやすい返信を日本語で作成してください。

【返信ルール】
・相手の投稿内容に自然に共感する書き出し（毎回変える）
・推奨店舗の特徴を1〜2文で自然に紹介
・宣伝臭を出さず、友人のアドバイスのような文体
・文字数：URLを除いて80〜160文字
・URLはリストの末尾に1行ずつ追加（加工しない）
・「絶対」「沖縄で一番」「No.1」などの誇大表現は禁止
・ハッシュタグは使わない
・敬語は丁寧語（です・ます）を基本とする
・今日は{today_weekday}曜日

【紹介する店舗】
{stores_text}"""

    user_prompt = f"""以下の投稿に対して返信を生成してください：

「{post_text}」

URLを含む完全な返信文を出力してください。URLは必ず末尾に含めてください。"""

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=300,
        temperature=0.9,
    )

    reply = resp.choices[0].message.content.strip()

    # URLが含まれていなければ追加
    for s in stores:
        info = TACHINOMIYA_INFO if s == "tachinomiya" else HINABE_INFO
        if info["url"] not in reply:
            reply += f"\n{info['url']}"

    return reply


def _fallback_reply(post_text: str, stores: list[str]) -> str:
    """GPT失敗時のルールベースフォールバック（内容別テンプレート）"""
    if not stores:
        return ""

    text_lower = post_text.lower()
    parts = []

    # 共感フレーズ（投稿内容に合わせて選択）
    if "記念日" in post_text:
        parts.append("記念日のご予定ですね。")
    elif "女子会" in post_text:
        parts.append("女子会の場所を探しているんですね。")
    elif "1人" in post_text or "ひとり" in text_lower or "一人" in post_text:
        parts.append("1人でも気軽に入れるお店を探しているんですね。")
    elif "観光" in post_text:
        parts.append("観光中のご飯を探しているんですね。")
    elif "会食" in post_text:
        parts.append("会食でのお店を探しているんですね。")
    elif "夜" in post_text or "夜ご飯" in post_text or "夜ごはん" in post_text:
        parts.append("夜ご飯の場所を探しているんですね。")
    elif "ランチ" in post_text or "昼" in post_text:
        parts.append("ランチの場所を探しているんですね。")
    elif "しゃぶしゃぶ" in post_text or "火鍋" in post_text:
        parts.append("しゃぶしゃぶや火鍋を探しているんですね。")
    else:
        parts.append("沖縄でのお食事を探しているんですね。")

    for s in stores:
        info = TACHINOMIYA_INFO if s == "tachinomiya" else HINABE_INFO
        # 投稿内容に合ったピッチを選択
        pitch = _context_pitch(info, post_text)
        parts.append(f"{info['name']}も候補に入れてみてください。{pitch}")
        parts.append(info["url"])

    return "\n".join(parts)


def _context_pitch(info: dict, post_text: str) -> str:
    """投稿内容に応じたピッチ文を選択"""
    if info["name"] == "TACHINOMIYA":
        if "サーターアンダギー" in post_text or "昼" in post_text or "ランチ" in post_text:
            return "昼はサーターアンダギー専門店としても楽しめる、国際通りの立ち飲みBARです。"
        if "1人" in post_text or "ひとり" in post_text.lower() or "一人" in post_text:
            return "1人でも入りやすく、国際通り沿いで観光途中にも気軽に立ち寄れます。"
        if "BAR" in post_text or "バー" in post_text or "飲み" in post_text:
            return "国際通りのカジュアルな立ち飲みBAR。沖縄料理とお酒を気軽に楽しめます。"
        return "国際通り沿いで観光途中にも寄りやすく、1人でも入りやすいカジュアルなお店です。"
    else:  # 琉球火鍋
        if "しゃぶしゃぶ" in post_text or "火鍋" in post_text:
            return "沖縄しゃぶしゃぶと薬膳火鍋を個室でゆっくり楽しめます。黒毛和牛・アグー豚も。"
        if "記念日" in post_text:
            return "全室個室で雰囲気も落ち着いており、記念日のディナーにも使いやすいです。"
        if "女子会" in post_text:
            return "全室個室なので女子会にも最適です。沖縄しゃぶしゃぶと薬膳火鍋が楽しめます。"
        if "会食" in post_text:
            return "全室個室で落ち着いた雰囲気、会食にも使いやすいお店です。"
        return "全室個室の沖縄しゃぶしゃぶ×薬膳火鍋。ゆっくり落ち着いて食事できます。"


def check_reply_quality(reply: str) -> dict:
    """生成した返信文の品質チェック"""
    issues = []
    length = len(reply)

    if length < 100:
        issues.append(f"文字数不足({length}文字)")
    if length > 300:
        issues.append(f"文字数超過({length}文字)")

    prohibited = ["絶対", "沖縄で一番", "No.1", "ナンバーワン"]
    for p in prohibited:
        if p in reply:
            issues.append(f"誇大表現含む: {p}")

    url_count = reply.count("https://")
    if url_count > 2:
        issues.append(f"URL多すぎ({url_count}件)")
    if url_count == 0:
        issues.append("URLなし")

    return {"ok": len(issues) == 0, "issues": issues, "length": length}
