#!/usr/bin/env python3
"""
Tree Beauty コンテンツ戦略 v2.0
180日 × 4媒体 = 720コンテンツ生成

実行: python3 scripts/beauty_content_v2.py
"""

import os, json, time, sys
from datetime import date, timedelta
from pathlib import Path
from openai import OpenAI
import gspread
from google.oauth2.service_account import Credentials

# ─── 設定 ──────────────────────────────────────────────────────
SPREADSHEET_ID = "1I6wRRDa-b440DBxZ3TbFbfMxEXZecowzOsxTAYSxyBE"
BOOKING_URL = "https://beauty.hotpepper.jp/kr/slnH000532761/"
CREDS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS",
                       "/Users/tokudayuya/tree-beauty-ai/credentials.json")
PROGRESS_FILE = Path(__file__).parent / "beauty_content_progress.json"
START_DATE = date.today()
DAYS = 180

# ─── 20日ブロック × 9 = 180日 ─────────────────────────────────
SERVICE_BLOCKS = (
    ["脱毛"] * 8 +
    ["セルフホワイトニング"] * 6 +
    ["よもぎ蒸し"] * 4 +
    ["口コミ紹介"] * 1 +
    ["店舗紹介"] * 1
)

PSYCHOLOGY = {
    "脱毛": [
        "自己処理の面倒さ・時間的ストレスから解放されたい",
        "清潔感をアップして自分に自信を取り戻したい",
        "恋愛・デートで思いっきり魅力的に見せたい",
        "夏・プール・海を制限なく全力で楽しみたい",
        "肌の見た目をキレイにして自分を好きになりたい",
        "人の視線・評価が気になって行動を制限している",
        "サロン脱毛は高いので安くて通いやすい方法が欲しい",
        "自己処理による肌荒れ・埋没毛に長年悩んでいる",
    ],
    "セルフホワイトニング": [
        "笑顔に自信が持てず、写真で口元を隠してしまう",
        "写真やビデオで歯が気になって笑えない",
        "第一印象で清潔感・明るさを相手に伝えたい",
        "接客・営業・プレゼンで自信を持って話せるようになりたい",
        "若々しく清潔感のある印象を人から持たれたい",
        "歯科ホワイトニングの費用が高くて踏み出せない",
    ],
    "よもぎ蒸し": [
        "慢性疲労が取れず、毎日体が重くて動きたくない",
        "仕事・育児・家事のストレスが限界に近い",
        "末端の冷えがひどく、体の不調が改善しない",
        "睡眠が浅く、翌朝スッキリ起きられない日が続いている",
        "自分だけの整える時間・リセット時間が欲しい",
    ],
    "口コミ紹介": ["実際のお客様の変化・声で信頼感を伝えたい"],
    "店舗紹介": ["完全セルフの使いやすいサロンとして差別化したい"],
}

PATTERNS = [
    "悩み共感", "失敗談", "ビフォーアフター", "口コミ紹介", "お客様ストーリー",
    "美容知識", "セルフ美容のメリット", "季節ネタ", "恋愛", "仕事",
    "第一印象", "自己肯定感", "リラックス", "ストレス解消", "Q&A",
    "よくある誤解", "比較記事", "店舗紹介",
]

SEO_KEYWORDS = {
    "脱毛":             ["沖縄脱毛", "西原町脱毛", "セルフ脱毛沖縄"],
    "セルフホワイトニング": ["セルフホワイトニング沖縄", "沖縄ホワイトニング", "西原町ホワイトニング"],
    "よもぎ蒸し":        ["よもぎ蒸し沖縄", "よもぎ蒸し西原町"],
    "口コミ紹介":        ["美容サロン沖縄", "完全セルフ美容"],
    "店舗紹介":          ["完全セルフ美容", "美容サロン沖縄"],
}


# ─────────────────────────────────────────────────────────────
def build_schedule():
    schedule = []
    for i in range(DAYS):
        d = START_DATE + timedelta(days=i)
        service = SERVICE_BLOCKS[i % 20]
        pattern = PATTERNS[i % len(PATTERNS)]
        psych_list = PSYCHOLOGY[service]
        psych = psych_list[(i // len(PATTERNS)) % len(psych_list)]
        kw_list = SEO_KEYWORDS[service]
        seo_kw = kw_list[(i // 3) % len(kw_list)]
        schedule.append({
            "day_num": i + 1,
            "date": d.strftime("%Y/%m/%d"),
            "service": service,
            "pattern": pattern,
            "psychology": psych,
            "seo_keyword": seo_kw,
        })
    return schedule


# ─────────────────────────────────────────────────────────────
def generate_main_batch(batch, used_themes, client):
    """Google + Instagram + Threads を10日分生成"""
    day_list = "\n".join(
        f"Day{d['day_num']}: {d['date']} | サービス:{d['service']} | パターン:{d['pattern']} "
        f"| 心理:{d['psychology']} | Google必須SEOキーワード:{d['seo_keyword']}"
        for d in batch
    )
    forbidden = "、".join(used_themes[-30:]) if used_themes else "なし"

    prompt = f"""あなたは女性向け美容メディアで15年の経験を持つ、日本トップクラスのコピーライターです。
沖縄県西原町の完全セルフ美容サロン「Tree Beauty」のSNS投稿を書きます。

【絶対に守るルール — 違反したら全文やり直し】
1. 本文に「#」「##」「*」「■」「▶」「→」「①②③」「・」など記号・箇条書き・見出しを一切使わない
2. すべて流れるような自然な文章（段落）で書く。リスト形式は禁止
3. 以下のフレーズは1回も使わない：
   「ぜひ」「いかがでしょう」「してみましょう」「ではないでしょうか」「お気軽に」「なんと」「素晴らしい」「充実した」「きっと」「することができます」「提供しています」「サポートします」「ご来店」「スタッフ一同」
4. AI感・マニュアル感のある表現禁止。人が普通に話すような自然な言葉で
5. 使用禁止テーマ（重複回避）: {forbidden}

【ターゲット読者の人物像】
沖縄在住20〜40代の女性。仕事か育児で毎日バタバタしている。自分のことは後回しにしがち。
コンプレックスはあるけど人には言えない。「安かろう悪かろう」は嫌だが節約もしたい。
「いつかやろう」がずっと続いている。スマホを見る時間は隙間だけ。

【文体の基準（これを必ず参考にする）】
NG例：「Tree Beautyでは脱毛サービスを提供しています。お肌がスベスベになり自信が持てます。ぜひお気軽にお越しください。」
OK例：「海に行く前の日、どうしても気になってしまう。隠せてるはずなのに、なぜか視線が気になる。そういうとき、自分でも気づいてないうちに一歩引いてる自分がいる。」

【Tree Beauty】
沖縄県西原町 / 完全セルフ（施術中にスタッフが同席しない） / 通いやすい価格
予約: {BOOKING_URL}

【媒体別の書き方】
Google投稿: 段落を2〜3つ使った読み物形式。500〜700文字。指定SEOキーワードを文中に自然に入れる。最後の1〜2文で行動を促す
Instagram本文: 最初の1文で読む人の心を掴む（共感か驚き）。感情を動かす描写。200〜350文字。本文に#は一切入れない（ハッシュタグは別フィールドに）
Threads: 友人に話しかけるような口調。120〜250文字。共感から入って気づきで終わる

以下{len(batch)}日分をJSONで返してください:
{day_list}

{{
  "days": [
    {{
      "day_num": 1,
      "date": "YYYY/MM/DD",
      "service": "サービス名",
      "pattern": "パターン名",
      "theme": "今日使ったテーマ（15文字以内）",
      "google": {{
        "title": "タイトル（記号なし・30文字以内）",
        "body": "本文（記号・箇条書き・見出し一切なし・500〜700文字の流れる文章）",
        "cta": "行動を促す自然な一言（記号なし・30文字以内）"
      }},
      "instagram": {{
        "title": "冒頭1文（共感か問いかけ・20文字以内）",
        "body": "本文（#など記号なし・200〜350文字の流れる文章）",
        "hashtags": "#西原町 #沖縄脱毛 など10個（本文とは完全に分けて記載）"
      }},
      "threads": {{
        "body": "投稿文（記号なし・会話口調・120〜250文字）"
      }}
    }}
  ]
}}"""

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.82,
                max_tokens=8000,
            )
            return json.loads(resp.choices[0].message.content)
        except Exception as e:
            print(f"    ⚠ retry {attempt+1}/3: {e}")
            time.sleep(10)
    raise RuntimeError("generate_main_batch: 3回失敗")


# ─────────────────────────────────────────────────────────────
def generate_hpb_batch(batch, used_titles, client):
    """HPBブログを3日分生成（1記事1000〜2000文字）"""
    day_list = "\n".join(
        f"Day{d['day_num']}: {d['date']} | サービス:{d['service']} | パターン:{d['pattern']} "
        f"| 心理:{d['psychology']}"
        for d in batch
    )
    forbidden = "、".join(used_titles[-15:]) if used_titles else "なし"

    prompt = f"""あなたは女性向け美容・ライフスタイルメディアで活躍する、読者に寄り添う文章が得意な日本人ライターです。
沖縄県西原町の完全セルフ美容サロン「Tree Beauty」のホットペッパービューティーブログ記事を書きます。

【絶対に守るルール — 違反したら全文やり直し】
1. 本文に「#」「##」「###」「■」「▶」「→」「①②③」「・」などの記号・見出し記号・箇条書きを一切使わない
2. 見出しタグや箇条書きは禁止。すべて段落（改行あり）の自然な文章として書く
3. 段落ごとに1行空ける。読みやすいリズムにする
4. 以下のフレーズは1回も使わない：
   「ぜひ」「いかがでしょう」「してみましょう」「ではないでしょうか」「お気軽に」「なんと」「素晴らしい」「充実した」「きっと」「することができます」「提供しています」「サポートします」「ご来店」「スタッフ一同」「是非」
5. AI感・マニュアル感のある表現禁止。人が実際に書くような自然な言葉で
6. 機能の羅列禁止。感情の動きと変化後の自分のイメージを軸に書く
7. 使用禁止タイトル（重複回避）: {forbidden}

【文体の基準（必ず参考にする）】
NG例：「脱毛のメリットをご紹介します。①自己処理の手間が省けます ②肌トラブルが減ります ③自信が持てます」
OK例：「自己処理のたびに、なんとなく気持ちが重くなることってないですか。肌が赤くなって、また明日も同じことをしなければいけないという感覚。それが毎週、毎月続いている。」

【ターゲット読者の人物像】
沖縄在住20〜40代の女性。忙しくて自分の時間が取れない。コンプレックスはあるけど誰にも言えない。「いつかやろう」を繰り返している。

【記事構成の流れ（この順番で書く）】
共感（読者の現状・悩みに寄り添う）→ 本質的な問題（なぜ解決できないのか）→ Tree Beautyの話（特徴・完全セルフの安心感）→ 変化のイメージ（利用後の自分を映像で描写）→ 予約への自然な導線

【Tree Beauty】
沖縄県西原町 / 完全セルフ（施術中にスタッフが同席しない） / 通いやすい価格
予約: {BOOKING_URL}

以下{len(batch)}日分のHPBブログをJSONで返してください:
{day_list}

{{
  "days": [
    {{
      "day_num": 1,
      "date": "YYYY/MM/DD",
      "service": "サービス名",
      "hpb_title": "ブログタイトル（記号なし・SEO重視・30〜45文字）",
      "hpb_body": "本文（記号・箇条書き・見出し一切なし・段落で書く・1000〜2000文字・文末に予約URL自然に含める）",
      "hpb_cta": "最後の一言（記号なし・読者の背中を自然に押す・40文字以内）"
    }}
  ]
}}"""

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.8,
                max_tokens=12000,
            )
            return json.loads(resp.choices[0].message.content)
        except Exception as e:
            print(f"    ⚠ retry {attempt+1}/3: {e}")
            time.sleep(15)
    raise RuntimeError("generate_hpb_batch: 3回失敗")


# ─────────────────────────────────────────────────────────────
def get_gc():
    creds = Credentials.from_service_account_file(
        CREDS_PATH,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds)


def get_or_create_sheet(ss, title, rows=200, cols=10):
    try:
        sh = ss.worksheet(title)
        sh.clear()
        return sh
    except gspread.WorksheetNotFound:
        return ss.add_worksheet(title=title, rows=rows, cols=cols)


def format_header(sh, col_end="H"):
    sh.format(f"A1:{col_end}1", {
        "backgroundColor": {"red": 0.059, "green": 0.09, "blue": 0.165},
        "textFormat": {
            "bold": True, "fontSize": 10,
            "foregroundColor": {"red": 1, "green": 1, "blue": 1},
        },
        "horizontalAlignment": "CENTER",
    })


# ─────────────────────────────────────────────────────────────
def write_to_sheets(results):
    print("\n[3/3] スプレッドシートへ書き込み中...")
    schedule = build_schedule()
    gc = get_gc()
    ss = gc.open_by_key(SPREADSHEET_ID)

    # 旧シート削除
    for old_name in ["180日コンテンツ計画", "コンテンツカレンダー", "content_plan"]:
        try:
            ss.del_worksheet(ss.worksheet(old_name))
            print(f"  🗑  {old_name} 削除")
        except Exception:
            pass

    # Instagram: 8列（ハッシュタグを本文と分離）
    ig_headers  = ["日付", "媒体", "カテゴリ", "タイトル", "本文", "CTA", "予約URL", "ハッシュタグ"]
    # その他: 7列
    std_headers = ["日付", "媒体", "カテゴリ", "タイトル", "本文", "CTA", "予約URL"]

    def make_rows_google(results):
        rows = []
        for i, r in enumerate(results):
            d = r.get("google", {})
            rows.append([
                r.get("date", schedule[i]["date"]),
                "Google投稿",
                r.get("service", schedule[i]["service"]),
                d.get("title", ""), d.get("body", ""),
                d.get("cta", ""), BOOKING_URL,
            ])
        return rows

    def make_rows_instagram(results):
        rows = []
        for i, r in enumerate(results):
            d = r.get("instagram", {})
            rows.append([
                r.get("date", schedule[i]["date"]),
                "Instagram",
                r.get("service", schedule[i]["service"]),
                d.get("title", ""),
                d.get("body", ""),         # 本文のみ（#なし）
                "",
                BOOKING_URL,
                d.get("hashtags", ""),     # ハッシュタグ列（H列）
            ])
        return rows

    def make_rows_threads(results):
        rows = []
        for i, r in enumerate(results):
            d = r.get("threads", {})
            rows.append([
                r.get("date", schedule[i]["date"]),
                "Threads",
                r.get("service", schedule[i]["service"]),
                "", d.get("body", ""), "", BOOKING_URL,
            ])
        return rows

    def make_rows_hpb(results):
        rows = []
        for i, r in enumerate(results):
            d = r.get("hpb", {})
            rows.append([
                r.get("date", schedule[i]["date"]),
                "HPBブログ",
                r.get("service", schedule[i]["service"]),
                d.get("hpb_title", ""), d.get("hpb_body", ""),
                d.get("hpb_cta", ""), BOOKING_URL,
            ])
        return rows

    sheet_tasks = [
        ("Google投稿",    make_rows_google,    std_headers, "G", 7),
        ("Instagram投稿", make_rows_instagram,  ig_headers,  "H", 8),
        ("Threads投稿",   make_rows_threads,   std_headers, "G", 7),
        ("HPBブログ",     make_rows_hpb,       std_headers, "G", 7),
    ]

    for sheet_name, row_fn, headers, col_end, n_cols in sheet_tasks:
        sh = get_or_create_sheet(ss, sheet_name, rows=185, cols=n_cols)
        sh.update(range_name=f"A1:{col_end}1", values=[headers])
        format_header(sh, col_end)
        rows = row_fn(results)
        if rows:
            # 429対策: バッチ書き込み
            for attempt in range(5):
                try:
                    sh.update(range_name="A2", values=rows, value_input_option="RAW")
                    break
                except gspread.exceptions.APIError as e:
                    if "429" in str(e) and attempt < 4:
                        print(f"    ⏳ rate limit、15秒待機...")
                        time.sleep(15)
                    else:
                        raise
        print(f"  ✅ {sheet_name}: {len(rows)}行")
        time.sleep(3)


# ─────────────────────────────────────────────────────────────
def main():
    print("=" * 62)
    print("Tree Beauty コンテンツ戦略 v2.0")
    print(f"180日 × 4媒体 = 720コンテンツ生成")
    print(f"開始日: {START_DATE}")
    print("=" * 62)

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    schedule = build_schedule()

    # 進捗ロード
    progress = {}
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            progress = json.load(f)
        done = sum(1 for r in progress.get("results", []) if r.get("google"))
        print(f"  📂 進捗ファイル検出: main={done}件 完了済み")

    results = progress.get("results", [{} for _ in range(DAYS)])
    if len(results) < DAYS:
        results += [{} for _ in range(DAYS - len(results))]
    used_themes = progress.get("used_themes", [])
    used_hpb_titles = progress.get("used_hpb_titles", [])

    # ── フェーズ1: Google + Instagram + Threads ─────────────
    BATCH_MAIN = 10
    total_main = DAYS // BATCH_MAIN
    print(f"\n[1/3] Google・Instagram・Threads ({total_main}バッチ × 10日)")

    for batch_start in range(0, DAYS, BATCH_MAIN):
        batch_days = schedule[batch_start:batch_start + BATCH_MAIN]
        indices = list(range(batch_start, min(batch_start + BATCH_MAIN, DAYS)))
        batch_num = batch_start // BATCH_MAIN + 1

        if all(results[i].get("google") for i in indices):
            print(f"  ⏭  batch {batch_num:02d}/{total_main}: スキップ")
            continue

        day_range = f"Day{indices[0]+1}〜{indices[-1]+1}"
        print(f"  🔄 batch {batch_num:02d}/{total_main} ({day_range}) 生成中...", end="", flush=True)
        try:
            res = generate_main_batch(batch_days, used_themes, client)
            for pos, day_data in enumerate(res.get("days", [])):
                if pos >= len(indices):
                    break
                idx = indices[pos]  # day_numに頼らず順番で対応付け
                results[idx].update({
                    "date":      day_data.get("date", schedule[idx]["date"]),
                    "service":   day_data.get("service", schedule[idx]["service"]),
                    "pattern":   day_data.get("pattern", schedule[idx]["pattern"]),
                    "google":    day_data.get("google", {}),
                    "instagram": day_data.get("instagram", {}),
                    "threads":   day_data.get("threads", {}),
                })
                if theme := day_data.get("theme"):
                    used_themes.append(theme)

            progress.update({"results": results, "used_themes": used_themes})
            with open(PROGRESS_FILE, "w") as f:
                json.dump(progress, f, ensure_ascii=False)
            print(f" ✅")
        except Exception as e:
            print(f" ❌ {e}")

        time.sleep(2)

    # ── フェーズ2: HPBブログ ─────────────────────────────────
    BATCH_HPB = 3
    total_hpb = -(-DAYS // BATCH_HPB)  # ceil div
    print(f"\n[2/3] HPBブログ ({total_hpb}バッチ × 3日、1記事1000〜2000文字)")

    for batch_start in range(0, DAYS, BATCH_HPB):
        batch_days = schedule[batch_start:batch_start + BATCH_HPB]
        indices = list(range(batch_start, min(batch_start + BATCH_HPB, DAYS)))
        batch_num = batch_start // BATCH_HPB + 1

        if all(results[i].get("hpb") for i in indices):
            print(f"  ⏭  batch {batch_num:02d}/{total_hpb}: スキップ")
            continue

        day_range = f"Day{indices[0]+1}〜{indices[-1]+1}"
        print(f"  🔄 batch {batch_num:02d}/{total_hpb} ({day_range}) 生成中...", end="", flush=True)
        try:
            res = generate_hpb_batch(batch_days, used_hpb_titles, client)
            for pos, day_data in enumerate(res.get("days", [])):
                if pos >= len(indices):
                    break
                idx = indices[pos]  # day_numに頼らず順番で対応付け
                results[idx]["hpb"] = {
                    "hpb_title": day_data.get("hpb_title", ""),
                    "hpb_body":  day_data.get("hpb_body", ""),
                    "hpb_cta":   day_data.get("hpb_cta", ""),
                }
                if t := day_data.get("hpb_title"):
                    used_hpb_titles.append(t)

            progress.update({"results": results, "used_hpb_titles": used_hpb_titles})
            with open(PROGRESS_FILE, "w") as f:
                json.dump(progress, f, ensure_ascii=False)
            print(f" ✅")
        except Exception as e:
            print(f" ❌ {e}")

        time.sleep(3)

    # ── フェーズ3: スプレッドシート書き込み ─────────────────
    write_to_sheets(results)

    # ── 完了レポート ─────────────────────────────────────────
    service_count = {}
    for r in results:
        s = r.get("service", "不明")
        service_count[s] = service_count.get(s, 0) + 1

    kw_count = {}
    for r in results:
        body = r.get("google", {}).get("body", "")
        for kws in SEO_KEYWORDS.values():
            for kw in kws:
                if kw in body:
                    kw_count[kw] = kw_count.get(kw, 0) + 1

    g_ok  = sum(1 for r in results if r.get("google",    {}).get("body"))
    ig_ok = sum(1 for r in results if r.get("instagram", {}).get("body"))
    th_ok = sum(1 for r in results if r.get("threads",   {}).get("body"))
    hp_ok = sum(1 for r in results if r.get("hpb",       {}).get("hpb_body"))
    cta_ok = sum(1 for r in results if r.get("google",   {}).get("cta"))

    print("\n" + "=" * 62)
    print("✅ 完了レポート")
    print("=" * 62)
    print("\n【媒体別件数】")
    print(f"  Google投稿   : {g_ok}件")
    print(f"  Instagram投稿: {ig_ok}件")
    print(f"  Threads投稿  : {th_ok}件")
    print(f"  HPBブログ    : {hp_ok}件")
    print(f"  合計         : {g_ok+ig_ok+th_ok+hp_ok}件")
    print("\n【カテゴリ別件数】")
    for svc, cnt in sorted(service_count.items(), key=lambda x: -x[1]):
        print(f"  {svc:22s}: {cnt}日 ({cnt/DAYS*100:.0f}%)")
    print("\n【SEOキーワード出現数（Google投稿）】")
    for kw, cnt in sorted(kw_count.items(), key=lambda x: -x[1]):
        print(f"  {kw}: {cnt}件")
    print(f"\n【予約導線】")
    print(f"  Google CTA設定済み: {cta_ok}/{DAYS}日")
    print(f"  予約URL全媒体設定 : {DAYS * 4}件（G列）")
    print(f"\nスプレッドシート: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}")
    print("=" * 62)

    # 進捗ファイル削除（完了）
    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()


if __name__ == "__main__":
    main()
