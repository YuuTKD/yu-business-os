"""
Generic Content Generator - 全事業共通90日コンテンツ生成

business_registry の config を受け取り、
その事業に合ったGoogle/Instagram/Threads/LINEコンテンツを生成する。
"""

import os, json, time
from datetime import date, timedelta
from openai import OpenAI
import gspread
from google.oauth2.service_account import Credentials

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def get_gc(creds_path: str):
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds)


def assign_categories(config: dict, days: int = 90) -> list[tuple[date, str]]:
    themes = config.get("content_themes", ["サービス紹介", "お客様の声", "実績紹介"])
    # content_themes が少ない場合は繰り返し
    assignments = []
    start = date.today()
    for i in range(days):
        d = start + timedelta(days=i)
        cat = themes[i % len(themes)]
        assignments.append((d, cat))
    return assignments


def generate_batch(config: dict, category: str, date_str: str) -> dict:
    biz = config["name"]
    biz_type = config.get("business_type", "restaurant")
    services = config.get("services", [])
    location = config.get("location", "沖縄県")

    if biz_type in ["restaurant", "bar"]:
        biz_desc = f"飲食店（{', '.join(services[:3])}）"
        tone = "来店を促す、食欲をそそる文章"
        hashtag_base = f"#{biz.replace(' ', '')} #沖縄グルメ #沖縄飲食店"
    elif biz_type == "catering":
        biz_desc = f"ケータリング・デリバリー（{', '.join(services[:3])}）"
        tone = "法人向け、信頼感のある文章"
        hashtag_base = f"#{biz.replace(' ', '')} #沖縄ケータリング #法人弁当"
    else:  # consulting
        biz_desc = f"経営コンサルティング（{', '.join(services[:3])}）"
        tone = "専門性と実績を示す、信頼感のある文章"
        hashtag_base = f"#{biz.replace(' ', '')} #経営改善 #飲食店コンサル"

    prompt = f"""あなたは{biz}のSNSマーケティング担当です。
{biz_type}事業のSNSコンテンツを作成してください。

事業情報:
- 事業名: {biz}
- 事業種別: {biz_desc}
- エリア: {location}
- 本日のカテゴリ: {category}
- 投稿日: {date_str}

【ルール】
・値引き・クーポン・割引の記載は禁止
・{tone}
・ターゲットに刺さる具体的な内容

JSON形式で返してください:
{{
  "google": {{
    "title": "Google投稿タイトル（20文字以内）",
    "body": "Google投稿本文（400文字以内）",
    "hashtags": "{hashtag_base}"
  }},
  "instagram": {{
    "caption": "Instagramキャプション（300文字以内）",
    "hashtags": "{hashtag_base} #{category.replace(' ', '')} #沖縄"
  }},
  "threads": {{
    "body": "Threads投稿文（200文字以内）"
  }},
  "line": {{
    "subject": "LINE件名（20文字以内）",
    "body": "LINE本文（300文字以内）",
    "cta": "行動喚起（例：ご予約お待ちしています）"
  }}
}}"""

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.75,
    )
    return json.loads(resp.choices[0].message.content)


def run(spreadsheet_id: str, config: dict, creds_path: str,
        days: int = 90,
        google_sheet: str = "08_Google投稿",
        instagram_sheet: str = "09_Instagram",
        threads_sheet: str = "10_Threads",
        line_sheet: str = "11_LINE") -> dict:

    biz = config["name"]
    print(f"\n{'='*55}")
    print(f"{biz} - {days}日分コンテンツ生成開始")
    print(f"{'='*55}")

    gc = get_gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    assignments = assign_categories(config, days)

    # ユニークカテゴリごとにコンテンツ生成
    themes = config.get("content_themes", [])
    generated = {}

    print(f"\n[1/2] AI コンテンツ生成（{len(themes)}カテゴリ）...")
    for i, cat in enumerate(themes):
        date_str = (date.today() + timedelta(days=i)).strftime("%Y年%m月%d日")
        try:
            content = generate_batch(config, cat, date_str)
            generated[cat] = content
            print(f"  ✅ [{i+1}/{len(themes)}] {cat}")
        except Exception as e:
            print(f"  ❌ [{i+1}/{len(themes)}] {cat}: {e}")
            generated[cat] = {
                "google": {"title": cat, "body": f"{biz}の{cat}", "hashtags": ""},
                "instagram": {"caption": f"{biz}の{cat}", "hashtags": ""},
                "threads": {"body": f"{biz}の{cat}"},
                "line": {"subject": cat, "body": f"{biz}の{cat}", "cta": "お問い合わせください"},
            }
        time.sleep(0.3)

    print(f"\n[2/2] スプレッドシートへ書き込み（{days}日分）...")
    google_rows, instagram_rows, threads_rows, line_rows = [], [], [], []

    for i, (d, cat) in enumerate(assignments):
        date_str = d.strftime("%Y/%m/%d")
        c = generated.get(cat, {})
        g = c.get("google", {})
        ig = c.get("instagram", {})
        th = c.get("threads", {})
        ln = c.get("line", {})

        google_rows.append([i+1, date_str, cat, g.get("title",""), g.get("body",""), g.get("hashtags",""), "未投稿", "", ""])
        instagram_rows.append([i+1, date_str, cat, ig.get("caption",""), ig.get("hashtags",""), "写真準備", "未投稿", "", ""])
        threads_rows.append([i+1, date_str, cat, th.get("body",""), "", "未投稿", ""])
        line_rows.append([i+1, date_str, cat, ln.get("subject",""), ln.get("body",""), ln.get("cta",""), "未配信", "", ""])

    sheets_data = [
        (google_sheet,    google_rows,    "A3"),
        (instagram_sheet, instagram_rows, "A3"),
        (threads_sheet,   threads_rows,   "A3"),
        (line_sheet,      line_rows,      "A3"),
    ]

    for sheet_name, rows, start_cell in sheets_data:
        try:
            sh = ss.worksheet(sheet_name)
            sh.update(range_name=start_cell, values=rows, value_input_option="RAW")
            print(f"  ✅ {sheet_name}: {len(rows)}行 書き込み完了")
            time.sleep(1)
        except Exception as e:
            print(f"  ❌ {sheet_name}: {e}")

    print(f"\n✅ {biz} コンテンツ生成完了")
    print("=" * 55)
    return {"ok": True, "business": biz, "days": days, "categories": len(themes)}
