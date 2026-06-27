"""
TREES CATERING OS - 90日コンテンツ自動生成

9カテゴリ × 4媒体（Google/Instagram/Threads/LINE）の
コンテンツをAIで生成してスプレッドシートへ書き込む。
"""

import os, json, time
from datetime import date, timedelta
from openai import OpenAI
import gspread
from google.oauth2.service_account import Credentials

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

CATERING_CATEGORIES = [
    "ケータリング",
    "オードブル",
    "会議弁当",
    "来客用弁当",
    "実績紹介",
    "お客様の声",
    "法人向け提案",
    "季節提案",
    "イベント提案",
]

# 90日分 = カテゴリを順番に割り当て
def assign_categories(days=90) -> list[tuple[date, str]]:
    assignments = []
    start = date.today()
    for i in range(days):
        d = start + timedelta(days=i)
        cat = CATERING_CATEGORIES[i % len(CATERING_CATEGORIES)]
        assignments.append((d, cat))
    return assignments


def generate_batch(category: str, date_str: str) -> dict:
    """1日分 × 4媒体のコンテンツを1回のAPI呼び出しで生成"""
    prompt = f"""あなたはTrees Cateringの敏腕マーケティング担当です。
沖縄のケータリング・弁当事業のSNSコンテンツを作成してください。

事業情報:
- 事業名: Trees Catering
- サービス: ケータリング・オードブル・会議用弁当・来客用弁当
- エリア: 沖縄県
- ターゲット: 法人企業（会議・接待・イベント）
- メール: trees.catering098@gmail.com

本日のカテゴリ: {category}
投稿日: {date_str}

【ルール】
・値引き・クーポン・割引の記載は禁止
・具体的で信頼感のある内容
・法人営業に効果的な文章

JSON形式で返してください:
{{
  "google": {{
    "title": "Google投稿タイトル（20文字以内）",
    "body": "Google投稿本文（400文字以内）",
    "hashtags": "#ケータリング #沖縄 #法人弁当"
  }},
  "instagram": {{
    "caption": "Instagramキャプション（300文字以内）",
    "hashtags": "#trees_catering #ケータリング沖縄 #法人弁当 #会議弁当 #オードブル #沖縄ケータリング"
  }},
  "threads": {{
    "body": "Threads投稿文（200文字以内）"
  }},
  "line": {{
    "subject": "LINE件名（20文字以内）",
    "body": "LINE本文（300文字以内）",
    "cta": "行動喚起（例：お気軽にご相談ください）"
  }}
}}"""

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.75,
    )
    return json.loads(resp.choices[0].message.content)


def get_gc(creds_path: str):
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds)


def run(spreadsheet_id: str, creds_path: str, days: int = 90) -> dict:
    print("\n" + "=" * 55)
    print(f"TREES CATERING - {days}日分コンテンツ生成開始")
    print("=" * 55)

    gc = get_gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)

    assignments = assign_categories(days)

    # 各シートのデータ蓄積
    google_rows = []
    instagram_rows = []
    threads_rows = []
    line_rows = []

    # 9カテゴリごとにバッチ生成（API節約のため代表カテゴリのみ生成→全日に展開）
    generated = {}
    unique_cats = CATERING_CATEGORIES

    print(f"\n[1/2] AI コンテンツ生成（{len(unique_cats)}カテゴリ）...")
    for i, cat in enumerate(unique_cats):
        date_str = (date.today() + timedelta(days=i)).strftime("%Y年%m月%d日")
        try:
            content = generate_batch(cat, date_str)
            generated[cat] = content
            print(f"  ✅ [{i+1}/{len(unique_cats)}] {cat}")
        except Exception as e:
            print(f"  ❌ [{i+1}/{len(unique_cats)}] {cat}: {e}")
            generated[cat] = {
                "google": {"title": cat, "body": f"{cat}のコンテンツ", "hashtags": "#ケータリング"},
                "instagram": {"caption": f"{cat}のコンテンツ", "hashtags": "#ケータリング"},
                "threads": {"body": f"{cat}のコンテンツ"},
                "line": {"subject": cat, "body": f"{cat}のコンテンツ", "cta": "お問い合わせください"},
            }
        time.sleep(0.3)

    print(f"\n[2/2] スプレッドシートへ書き込み（{days}日分）...")
    for i, (d, cat) in enumerate(assignments):
        date_str = d.strftime("%Y/%m/%d")
        c = generated.get(cat, {})

        g = c.get("google", {})
        instagram = c.get("instagram", {})
        th = c.get("threads", {})
        ln = c.get("line", {})

        google_rows.append([
            i + 1, date_str, cat,
            g.get("title", ""),
            g.get("body", ""),
            g.get("hashtags", ""),
            "未投稿", "", ""
        ])
        instagram_rows.append([
            i + 1, date_str, cat,
            instagram.get("caption", ""),
            instagram.get("hashtags", ""),
            "写真準備",
            "未投稿", "", ""
        ])
        threads_rows.append([
            i + 1, date_str, cat,
            th.get("body", ""),
            "",
            "未投稿"
        ])
        line_rows.append([
            i + 1, date_str, cat,
            ln.get("subject", ""),
            ln.get("body", ""),
            ln.get("cta", ""),
            "未配信", "", ""
        ])

    # バッチ書き込み
    sheets_data = [
        ("08_Google投稿",  google_rows,    "A3"),
        ("09_Instagram",   instagram_rows, "A3"),
        ("10_Threads",     threads_rows,   "A3"),
        ("11_LINE",        line_rows,      "A3"),
    ]

    for sheet_name, rows, start_cell in sheets_data:
        try:
            sh = ss.worksheet(sheet_name)
            sh.update(start_cell, rows, value_input_option="RAW")
            print(f"  ✅ {sheet_name}: {len(rows)}行 書き込み完了")
            time.sleep(1)
        except Exception as e:
            print(f"  ❌ {sheet_name}: {e}")

    print("\n✅ コンテンツ生成完了")
    print("=" * 55)

    return {
        "ok": True,
        "days": days,
        "categories": len(unique_cats),
        "google_rows": len(google_rows),
        "instagram_rows": len(instagram_rows),
        "threads_rows": len(threads_rows),
        "line_rows": len(line_rows),
    }
