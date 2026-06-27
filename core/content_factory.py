"""
YU BUSINESS OS - 汎用コンテンツファクトリー

事業設定（BusinessConfig）を受け取り、
その事業向けの5媒体コンテンツを一括生成する。

Beauty固有の記述を一切持たない共通モジュール。
"""

import os, json
from datetime import datetime
from openai import OpenAI


def generate(config: dict, topic: str, source_content: str = "") -> dict:
    """
    config: BUSINESSES[short_name] の辞書
    topic:  投稿テーマ
    """
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    name         = config["name"]
    location     = config["location"]
    services     = "・".join(config["services"])
    booking_url  = config.get("booking_url", "")
    biz_type     = config.get("business_type", "shop")
    platforms    = config.get("platforms", ["google", "instagram", "line"])

    business_desc = _build_business_description(biz_type)

    base_info = f"""
事業名: {name}
所在地: {location}
業態: {business_desc}
サービス: {services}
予約・問い合わせURL: {booking_url}
投稿トピック: {topic}
元原稿: {source_content[:800] if source_content else "なし（トピックから生成）"}
"""

    # 対象媒体のJSONスキーマを動的に構築
    platform_schema = _build_platform_schema(platforms)

    prompt = f"""{base_info}

上記の情報をもとに、各媒体向けの投稿コンテンツをJSON形式で生成してください。

ルール:
- Markdown記号（# ## ** -- など）は絶対に使わない
- スタッフが書いたような自然な日本語
- 各媒体の文字数・特性を厳守
- 値引き・クーポンの提案は禁止
- {name}の強みを具体的に訴求すること

{platform_schema}

JSONのみ出力（コードブロック不要）"""

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2500,
        temperature=0.65,
    )
    text = resp.choices[0].message.content.strip()
    if "```" in text:
        text = text.split("```")[1].lstrip("json").strip()

    content = json.loads(text)
    content["topic"]        = topic
    content["business"]     = config["short_name"]
    content["generated_at"] = datetime.now().isoformat()
    return content


def generate_from_kpi(config: dict, kpi_data: dict) -> dict:
    """KPIデータから訴求テーマを自動決定してコンテンツ生成"""
    target = config.get("monthly_target", 1_000_000)
    sales  = kpi_data.get("sales", 0)
    gap    = max(target - sales, 0)
    name   = config["name"]
    services = config["services"][0] if config["services"] else "サービス"

    if gap > target * 0.4:
        topic = f"{name}の{services}を今月ぜひ体験してください"
    elif gap > target * 0.2:
        topic = f"今月もあと少し！{name}でお待ちしています"
    else:
        topic = f"今月も多くのお客様にご利用いただきありがとうございます"

    return generate(config, topic)


def _build_business_description(biz_type: str) -> str:
    desc_map = {
        "salon":       "セルフ式美容サロン",
        "restaurant":  "飲食店・レストラン",
        "catering":    "ケータリング・仕出し業",
        "consulting":  "経営コンサルティング",
        "bar":         "バー・居酒屋",
        "retail":      "小売店",
    }
    return desc_map.get(biz_type, "事業者")


def _build_platform_schema(platforms: list) -> str:
    schema = "出力JSONのキーと仕様:\n"
    specs = {
        "google":    '"google": {"text": "Googleビジネスプロフィール投稿文（300〜400文字、信頼感・具体性重視）", "cta": "行動喚起（30文字以内）"}',
        "instagram": '"instagram": {"caption": "Instagram投稿文（200〜300文字、絵文字2〜3個、読みやすい改行）", "hashtags": "#関連ハッシュタグ10個"}',
        "threads":   '"threads": {"text": "Threads投稿文（100〜150文字、会話調、短く刺さる）"}',
        "line":      '"line": {"text": "LINE配信文（150〜200文字、親しみやすい呼びかけ、行動誘導で終わる）"}',
        "hpb":       '"hpb": {"title": "HPBブログタイトル（30文字以内）", "body": "HPBブログ本文（500〜700文字）"}',
    }
    for p in platforms:
        if p in specs:
            schema += f"  {specs[p]}\n"
    return schema
