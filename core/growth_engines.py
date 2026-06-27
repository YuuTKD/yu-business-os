"""
集客・売上直結エンジン群（Phase 3-5）
--------------------------------------
Phase 3: Google Map Domination Engine（MEO集客タスク自動生成）
Phase 4: Lost Customer Revival Engine（失客復活）
Phase 5: High Profit Offer Push Engine（高粗利商品訴求）

方針: OpenAI不使用・ルールベース・テンプレート。LINE本番送信はDRY_RUN。
Daily Action Commander へ連携可能なタスクを生成（注入はsend_daily_tasks側）。
"""

import os
from datetime import datetime, timezone, timedelta

import gspread
from google.oauth2.service_account import Credentials
from google.cloud import storage as gcs_storage

JST = timezone(timedelta(hours=9))
GCS_BUCKET  = "tree-beauty-blog-images"
GCS_PREFIX  = "knowledge-os"
GCS_PROJECT = "tree-beauty-ai-499303"


def _now(): return datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
def _date(): return datetime.now(JST).strftime("%Y-%m-%d")


def _gc(creds_path):
    creds = Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/spreadsheets",
                            "https://www.googleapis.com/auth/drive"])
    return gspread.authorize(creds)


def _gcs(creds_path):
    creds = Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/devstorage.read_write"])
    return gcs_storage.Client(project=GCS_PROJECT, credentials=creds)


def _upload_md(creds_path, path, content):
    blob = _gcs(creds_path).bucket(GCS_BUCKET).blob(path)
    blob.upload_from_string(content.encode("utf-8"), content_type="text/markdown")
    return f"https://storage.googleapis.com/{GCS_BUCKET}/{path}"


def _sheet(ss, title, header):
    try:
        return ss.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=title, rows=2000, cols=max(len(header), 12))
        ws.update(values=[header], range_name="A1")
        ws.format("A1:Z1", {"backgroundColor": {"red": 0.10, "green": 0.20, "blue": 0.15},
                            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}}})
        return ws


def _pint(v):
    if v is None: return 0
    s = str(v).replace(",", "").replace("¥", "").replace("円", "").replace("%", "").strip()
    if s in ("", "-", "—"): return 0
    try: return int(float(s))
    except (ValueError, TypeError): return 0


BIZ_KEY = {"TACHINOMIYA": "tachinomiya", "Tree Beauty": "beauty",
           "TREE's Catering": "catering", "Trees Catering": "catering",
           "琉球火鍋": "ryukyu_hinabe"}

# ══════════════════════════════════════════════════════════
# PHASE 3: Google Map Domination Engine
# ══════════════════════════════════════════════════════════

GMAP_SHEETS = {
    "GOOGLE_MAP_ACTIONS": [
        "作成日時", "事業名", "アクション種別", "内容", "狙うキーワード", "対象写真",
        "口コミ依頼対象", "優先度", "担当", "期限", "対応状況", "結果", "メモ",
    ],
    "GOOGLE_MAP_DASHBOARD": [
        "日付", "事業名", "Google投稿数", "写真追加数", "口コミ依頼数", "口コミ返信数",
        "外国語対応数", "MEO強化キーワード", "不足アクション", "危険度", "最終更新",
    ],
}

GMAP_KEYWORDS = {
    "TACHINOMIYA": ["国際通り", "沖縄料理", "那覇バー", "沖縄旅行", "サーターアンダギー",
                    "ハブ酒", "Kokusai Street", "Okinawa local food", "Naha bar"],
    "Tree Beauty": ["那覇 脱毛", "よもぎ蒸し", "ホワイトニング", "カッピング", "沖縄 美容サロン"],
    "TREE's Catering": ["沖縄 ケータリング", "那覇 オードブル", "法人パーティー", "懇親会 沖縄"],
    "琉球火鍋": ["沖縄 火鍋", "那覇 しゃぶしゃぶ", "個室", "記念日", "女子会",
                "Wagyu", "private room dinner"],
}

GMAP_ACTION_TYPES = [
    ("Google最新投稿", "S", "今週の最新情報をGoogleビジネスプロフィールに投稿"),
    ("写真追加", "A", "新しい料理/店内/施術写真を3枚追加"),
    ("口コミ依頼", "S", "本日の満足度の高い客へGoogle口コミ依頼"),
    ("口コミ返信案", "A", "未返信の口コミに返信（高評価は感謝・低評価は誠実対応）"),
    ("外国人向け口コミ依頼", "B", "外国人観光客へ英語で口コミ依頼"),
    ("英語キーワード入り投稿", "B", "英語キーワードを含む投稿で訪日客流入を強化"),
    ("写真不足アラート", "C", "写真が30日以上未更新→追加を促す"),
]


def gmap_setup(ss_id, creds_path):
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    for n, h in GMAP_SHEETS.items():
        _sheet(ss, n, h)
    return {"ok": True, "sheets_created": list(GMAP_SHEETS)}


def gmap_generate(ss_id, creds_path, dry_run=True):
    """事業別にMEOタスクを自動生成→GOOGLE_MAP_ACTIONS＋Daily Action連携タスク"""
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    ws = _sheet(ss, "GOOGLE_MAP_ACTIONS", GMAP_SHEETS["GOOGLE_MAP_ACTIONS"])
    rows, dac = [], []
    for biz, kws in GMAP_KEYWORDS.items():
        kw_str = "、".join(kws[:5])
        for atype, pri, content in GMAP_ACTION_TYPES:
            rows.append([_now(), biz, atype, content, kw_str, "", "", pri, "", _date(),
                         "未対応", "", ""])
        dac.append({"biz_key": BIZ_KEY.get(biz, "owner"), "priority": "S",
                    "task": f"【MEO】{biz}: Google最新投稿＋口コミ依頼（{kws[0]}強化）"})
    if not dry_run:
        ws.append_rows(rows, value_input_option="RAW")
    # ダッシュボード
    dws = _sheet(ss, "GOOGLE_MAP_DASHBOARD", GMAP_SHEETS["GOOGLE_MAP_DASHBOARD"])
    drows = [[_date(), biz, 0, 0, 0, 0, 0, "、".join(kws[:3]),
              "Google投稿/写真/口コミ", "🟡", _now()] for biz, kws in GMAP_KEYWORDS.items()]
    if not dry_run:
        ex = len(dws.get_all_values())
        if ex > 1:
            dws.batch_clear([f"A2:K{ex}"])
        dws.append_rows(drows, value_input_option="RAW")
    return {"ok": True, "actions_generated": len(rows), "businesses": len(GMAP_KEYWORDS),
            "daily_action_tasks": dac, "dry_run": dry_run}


def gmap_status(ss_id, creds_path):
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    try:
        rows = ss.worksheet("GOOGLE_MAP_ACTIONS").get_all_records()
    except gspread.WorksheetNotFound:
        return {"ok": True, "note": "未セットアップ"}
    by = {}
    for r in rows:
        b = by.setdefault(r.get("事業名"), {"total": 0, "未対応": 0})
        b["total"] += 1
        if r.get("対応状況") in ("未対応", ""):
            b["未対応"] += 1
    return {"ok": True, "by_business": by, "total": len(rows)}


# ══════════════════════════════════════════════════════════
# PHASE 4: Lost Customer Revival Engine
# ══════════════════════════════════════════════════════════

REVIVAL_SHEETS = {
    "CUSTOMER_REVIVAL_MASTER": [
        "登録日時", "事業名", "顧客名", "顧客種別", "連絡先", "最終利用日", "利用回数",
        "累計売上", "前回利用内容", "失客日数", "再来店可能性", "推定売上", "優先度",
        "提案内容", "送信用文案", "担当", "対応状況", "次回フォロー日", "結果", "実売上", "メモ",
    ],
    "REVIVAL_DASHBOARD": [
        "日付", "事業名", "30日以上未利用", "60日以上未利用", "90日以上未利用",
        "再来店候補数", "本日対応数", "推定売上", "実売上", "未対応", "最終更新",
    ],
}

# 事業別 復活提案テンプレート
REVIVAL_TEMPLATES = {
    "Tree Beauty": "ご無沙汰しております、Tree Beautyです。お肌の調子はいかがですか？久しぶりのご来店に使えるお得なご案内があります。次回のご予約お待ちしております✨",
    "TREE's Catering": "いつもお世話になっております、TREE's Cateringです。前回のイベント以来ご無沙汰しております。次回の懇親会・イベントのご予定があればぜひお手伝いさせてください🍽️",
    "TACHINOMIYA": "TACHINOMIYAです！しばらくお会いできていませんね。お得なドリンクや新メニューをご用意してお待ちしています🍶",
    "琉球火鍋": "琉球火鍋です。記念日や女子会にまた個室をご利用いただけませんか？特別コースのご案内があります🔥",
    "コンサル": "その後の事業の調子はいかがですか？追加の改善施策や次の打ち手について、一度お話しできればと思います📊",
}

# テスト用 失客顧客データ
_REVIVAL_TEST = [
    ("Tree Beauty", "山田様", "初回来店のみ", 35, 1, 30000, "脱毛初回"),
    ("Tree Beauty", "佐藤様", "リピート", 65, 4, 120000, "よもぎ蒸し"),
    ("Tree Beauty", "鈴木様", "高単価", 95, 6, 280000, "回数券"),
    ("TREE's Catering", "A社", "過去利用企業", 70, 3, 600000, "懇親会"),
    ("TREE's Catering", "B幹事", "過去幹事", 45, 1, 200000, "周年イベント"),
    ("TACHINOMIYA", "常連C", "高単価客", 40, 8, 96000, "宴会"),
    ("TACHINOMIYA", "D様", "LINE登録者", 55, 2, 18000, "通常来店"),
    ("琉球火鍋", "E様", "記念日利用客", 80, 2, 140000, "個室記念日"),
    ("琉球火鍋", "F様", "団体利用客", 100, 1, 120000, "団体宴会"),
    ("コンサル", "G社", "成果ありクライアント", 35, 6, 900000, "売上改善"),
]


def revival_setup(ss_id, creds_path):
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    for n, h in REVIVAL_SHEETS.items():
        _sheet(ss, n, h)
    return {"ok": True, "sheets_created": list(REVIVAL_SHEETS)}


def _revival_priority(days, count, total):
    """失客日数・利用回数・累計売上から優先度・再来店可能性・推定売上"""
    if total >= 100000 or count >= 3:
        poss = "高"
    elif count >= 2 or 30 <= days <= 90:
        poss = "中"
    else:
        poss = "低"
    if days >= 90:
        pri = "A"
    elif days >= 60:
        pri = "S" if poss == "高" else "A"
    elif days >= 30:
        pri = "S" if poss == "高" else "B"
    else:
        pri = "C"
    est = int(total / count) if count else 10000
    return pri, poss, est


def revival_generate_test(ss_id, creds_path):
    """テスト失客データを投入し、復活候補を生成"""
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    ws = _sheet(ss, "CUSTOMER_REVIVAL_MASTER", REVIVAL_SHEETS["CUSTOMER_REVIVAL_MASTER"])
    rows = []
    for biz, name, ctype, days, cnt, total, last in _REVIVAL_TEST:
        pri, poss, est = _revival_priority(days, cnt, total)
        tmpl = REVIVAL_TEMPLATES.get(biz, REVIVAL_TEMPLATES.get("コンサル"))
        rows.append([_now(), biz, name, ctype, "", _date(), cnt, total, last, days,
                     poss, est, pri, f"{biz}復活提案", tmpl, "", "未対応", _date(), "", 0, "テスト"])
    ws.append_rows(rows, value_input_option="RAW")
    return {"ok": True, "candidates": len(rows)}


def revival_status(ss_id, creds_path):
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    try:
        rows = ss.worksheet("CUSTOMER_REVIVAL_MASTER").get_all_records()
    except gspread.WorksheetNotFound:
        return {"ok": True, "note": "未セットアップ"}
    by = {}
    for r in rows:
        b = by.setdefault(r.get("事業名"), {"total": 0, "d30": 0, "d60": 0, "d90": 0, "est": 0})
        b["total"] += 1
        d = _pint(r.get("失客日数"))
        if d >= 90: b["d90"] += 1
        elif d >= 60: b["d60"] += 1
        elif d >= 30: b["d30"] += 1
        b["est"] += _pint(r.get("推定売上"))
    return {"ok": True, "by_business": by, "total": len(rows)}


def revival_actions(ss_id, creds_path):
    """高優先の復活候補をDaily Action連携タスク化"""
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    try:
        rows = ss.worksheet("CUSTOMER_REVIVAL_MASTER").get_all_records()
    except gspread.WorksheetNotFound:
        return {"ok": True, "daily_action_tasks": []}
    tasks, seen = [], {}
    for r in rows:
        if r.get("優先度") in ("S", "A") and r.get("対応状況") in ("未対応", ""):
            biz = r.get("事業名")
            if seen.get(biz, 0) >= 3:
                continue
            seen[biz] = seen.get(biz, 0) + 1
            tasks.append({"biz_key": BIZ_KEY.get(biz, "owner"), "priority": "A",
                          "task": f"【失客復活】{biz}: {r.get('顧客名')}へ再来店提案（推定¥{_pint(r.get('推定売上')):,}）"})
    return {"ok": True, "daily_action_tasks": tasks, "count": len(tasks), "dry_run": True}


# ══════════════════════════════════════════════════════════
# PHASE 5: High Profit Offer Push Engine
# ══════════════════════════════════════════════════════════

OFFER_SHEETS = {
    "HIGH_PROFIT_OFFERS": [
        "事業名", "商品/メニュー名", "価格", "想定原価", "粗利", "粗利率",
        "訴求文", "おすすめタイミング", "対象客", "優先度", "メモ",
    ],
    "OFFER_PUSH_ACTIONS": [
        "作成日時", "事業名", "対象日", "トリガー", "推奨商品", "理由",
        "スタッフ指示文", "担当", "対応状況", "結果", "メモ",
    ],
}

# 事業別 初期高粗利商品（価格・想定原価は仮・後で調整）
HIGH_PROFIT_OFFERS = {
    "TACHINOMIYA": [
        ("ハブ酒", 1500, 300, "観光客に話題性で訴求"),
        ("サーターアンダギー", 500, 100, "お土産需要・追加注文"),
        ("ドリンク各種", 600, 120, "客単価アップの基本"),
        ("WAGYUすき焼き寿司", 1800, 600, "高単価名物として訴求"),
        ("沖縄料理セット", 2500, 800, "観光客向けセット"),
    ],
    "TREE's Catering": [
        ("法人プラン", 200000, 90000, "法人イベントに提案"),
        ("20名以上プラン", 160000, 70000, "大人数で粗利確保"),
        ("装飾オプション", 30000, 8000, "高粗利オプション"),
        ("配送費別請求", 5000, 1000, "原価回収"),
        ("年間契約提案", 0, 0, "継続収益化"),
    ],
    "Tree Beauty": [
        ("回数券", 80000, 16000, "高粗利・継続来店"),
        ("セットメニュー", 25000, 5000, "客単価アップ"),
        ("よもぎ蒸し", 6000, 1000, "高粗利メニュー"),
        ("ホワイトニング", 15000, 3000, "高粗利"),
    ],
    "琉球火鍋": [
        ("ドリンク", 700, 140, "客単価アップ基本"),
        ("追加肉(WAGYU)", 2500, 900, "高単価追加"),
        ("記念日プレート", 3000, 800, "記念日利用に訴求"),
        ("個室利用", 2000, 200, "高粗利・予約単価UP"),
        ("高単価コース", 10000, 3500, "客単価最大化"),
    ],
    "コンサル": [
        ("月額プラン", 150000, 0, "継続収益"),
        ("成果報酬", 0, 0, "成果連動で上振れ"),
        ("スポット診断", 50000, 0, "入口商品"),
        ("月次レポート", 30000, 0, "付加価値"),
    ],
}

OFFER_TRIGGERS = ["売上未達", "客単価低下", "資金繰り危険", "利益率低下",
                  "雨の日", "週末", "観光客増加", "予約少ない", "リード少ない"]


def offer_setup(ss_id, creds_path):
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    for n, h in OFFER_SHEETS.items():
        _sheet(ss, n, h)
    # 初期商品投入（空なら）
    ws = _sheet(ss, "HIGH_PROFIT_OFFERS", OFFER_SHEETS["HIGH_PROFIT_OFFERS"])
    if len(ws.get_all_values()) <= 1:
        rows = []
        for biz, items in HIGH_PROFIT_OFFERS.items():
            for name, price, cost, pitch in items:
                gp = price - cost
                rate = f"{(gp/price*100):.0f}%" if price else "—"
                rows.append([biz, name, price, cost, gp, rate, pitch, "売上が弱い日/週末", "全客", "A", ""])
        ws.append_rows(rows, value_input_option="RAW")
    return {"ok": True, "sheets_created": list(OFFER_SHEETS), "offers_loaded": True}


def offer_push(ss_id, creds_path, triggers=None, dry_run=True):
    """
    トリガー（資金繰り危険/利益率低下等）を検知し、事業別に高粗利商品の
    スタッフ指示文を生成→OFFER_PUSH_ACTIONS＋Daily Action連携。
    triggers未指定時は cash_flow/profit_leak から自動判定。
    """
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    trg = set(triggers or [])

    # 自動トリガー判定（read-only）
    if not trg:
        try:
            from core.cash_flow import get_status as cf
            d = cf(ss_id, creds_path)
            if d.get("ok") and d.get("危険度") in ("S", "A"):
                trg.add("資金繰り危険")
        except Exception:
            pass
        try:
            from core.profit_leak import get_status as pl
            d = pl(ss_id, creds_path)
            for biz, b in d.get("by_business", {}).items():
                if b.get("危険度") in ("S", "A"):
                    trg.add("利益率低下")
        except Exception:
            pass
    if not trg:
        trg = {"週末"}  # デフォルト

    # 高粗利商品（粗利率上位）を事業別に選定
    rows, dac = [], []
    for biz, items in HIGH_PROFIT_OFFERS.items():
        ranked = sorted(items, key=lambda x: ((x[1]-x[2])/x[1] if x[1] else 0), reverse=True)
        top = ranked[:2]
        names = "・".join(n for n, *_ in top)
        reason = "／".join(sorted(trg))
        instr = f"本日は{reason}のため、{names}を重点案内してください"
        rows.append([_now(), biz, _date(), reason, names, reason, instr, "", "未対応", "", ""])
        dac.append({"biz_key": BIZ_KEY.get(biz, "owner"), "priority": "A",
                    "task": f"【高粗利訴求】{biz}: {names}を本日重点案内（{reason}）"})
    if not dry_run:
        ws = _sheet(ss, "OFFER_PUSH_ACTIONS", OFFER_SHEETS["OFFER_PUSH_ACTIONS"])
        ws.append_rows(rows, value_input_option="RAW")
    return {"ok": True, "triggers": sorted(trg), "pushes": len(rows),
            "daily_action_tasks": dac, "dry_run": dry_run}


def offer_status(ss_id, creds_path):
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    try:
        offers = ss.worksheet("HIGH_PROFIT_OFFERS").get_all_records()
    except gspread.WorksheetNotFound:
        return {"ok": True, "note": "未セットアップ"}
    by = {}
    for r in offers:
        by.setdefault(r.get("事業名"), 0)
        by[r.get("事業名")] += 1
    return {"ok": True, "offers_by_business": by, "total": len(offers)}


# ══════════════════════════════════════════════════════════
# MEO Daily（TACHINOMIYA / 琉球火鍋）— Google集客タスク自動割当
# ══════════════════════════════════════════════════════════

MEO_DAILY_SHEETS = {
    "MEO_DAILY_TASKS": [
        "日付", "事業名", "daily_action_type", "meo_task_type",
        "target_keyword_ja", "target_keyword_en", "post_language_type",
        "google_post_text_ja", "google_post_text_en", "photo_required",
        "review_request_required", "review_reply_required", "assigned_staff",
        "due_time", "completion_status", "completion_screenshot_url",
        "ai_check_result", "next_improvement",
    ],
    "MEO_DASHBOARD": [
        "日付", "事業名", "本日のMEOタスク数", "完了", "未完了", "Google投稿数",
        "写真追加数", "口コミ依頼数", "口コミ返信数", "英語投稿数",
        "Google経由(電話/ルート/予約/来店)", "次に強化すべきキーワード", "最終更新",
    ],
}

MEO_BIZ = {
    "tachinomiya": {
        "name": "TACHINOMIYA",
        "content_ss": "1K4KkAhFwVkQqqvzeqa25-1sR26ltBfP9gY9h-N4gXcc",
        "content_sheet": "08_Google投稿",
        "kw_ja": ["国際通り", "沖縄料理", "立ち飲み", "ローカルバー", "観光客歓迎", "一人飲み", "サク飲み", "沖縄名物"],
        "kw_en": ["okinawa bar", "naha bar", "kokusai street bar", "okinawan food", "standing bar okinawa", "local bar naha"],
        "offer": "ハブ酒・WAGYUすき焼き寿司・泡盛飲み比べ",
    },
    "ryukyu_hinabe": {
        "name": "琉球火鍋",
        "content_ss": "1jwFmQtrertjIc6yYFJEyDptLdSUgD5xLdHDAxQhIQzw",
        "content_sheet": "08_Google投稿",
        "kw_ja": ["沖縄ディナー", "琉球火鍋", "黒毛和牛", "アグー豚", "高単価ディナー", "観光客向け", "グループ利用", "予約導線"],
        "kw_en": ["okinawa dinner", "naha hot pot", "okinawa wagyu", "agu pork okinawa", "okinawa restaurant", "naha restaurant"],
        "offer": "追加肉(アグー)・個室利用・記念日プレート",
    },
}
MEO_ALLOWED = set(MEO_BIZ.keys())


_LANG_FLAG = {"en": "🇺🇸", "zh-CN": "🇨🇳", "zh-TW": "🇹🇼", "ko": "🇰🇷", "th": "🇹🇭"}


def _translate(text, creds_path, lang):
    try:
        from google.cloud import translate_v2 as translate
        creds = Credentials.from_service_account_file(
            creds_path, scopes=["https://www.googleapis.com/auth/cloud-platform"])
        cl = translate.Client(credentials=creds)
        return cl.translate(text, target_language=lang, source_language="ja",
                            format_="text")["translatedText"]
    except Exception:
        return ""


def _translate_en(text, creds_path):
    return _translate(text, creds_path, "en")


def _meo_langs():
    """対象言語リスト（env MEO_LANGS。既定は英語のみ。Phase2でzh-TW/ko/th）"""
    raw = os.getenv("MEO_LANGS", "en")
    return [l.strip() for l in raw.split(",") if l.strip()]


def _multilang_block(text, creds_path):
    """日本語textを対象言語に翻訳した併記ブロックを返す（英語等）"""
    parts = []
    for lang in _meo_langs():
        t = _translate(text, creds_path, lang)
        if t:
            parts.append(f"{_LANG_FLAG.get(lang,'')} {t}")
    return "\n".join(parts)


def _todays_google_post(creds_path, cfg, today_slash):
    """事業の08_Google投稿シートから当日のタイトルを取得"""
    try:
        gc = _gc(creds_path)
        cs = gc.open_by_key(cfg["content_ss"]).worksheet(cfg["content_sheet"]).get_all_values()
        for r in cs[2:]:  # ヘッダー2行
            if len(r) > 3 and str(r[1]).strip() == today_slash:
                return str(r[3]).strip()  # タイトル列
    except Exception:
        pass
    return ""


def meo_setup(ss_id, creds_path):
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    for n, h in MEO_DAILY_SHEETS.items():
        _sheet(ss, n, h)
    return {"ok": True, "sheets_created": list(MEO_DAILY_SHEETS)}


def meo_daily_assign(ss_id, creds_path, biz_key, dry_run=False):
    """当日のMEOタスクを割当ルールで生成 → MEO_DAILY_TASKS + Daily Action連携タスク"""
    cfg = MEO_BIZ.get(biz_key)
    if not cfg:
        return {"ok": False, "error": f"{biz_key} はMEO daily対象外"}
    name = cfg["name"]
    now = datetime.now(JST)
    today = now.strftime("%Y-%m-%d")
    today_slash = now.strftime("%Y/%m/%d")
    wd = now.weekday()  # 月=0 .. 日=6
    di = now.timetuple().tm_yday

    title = _todays_google_post(creds_path, cfg, today_slash) or f"{name}の魅力を発信"
    en_title = _translate_en(title, creds_path)
    multilang = _multilang_block(title, creds_path)  # 設定言語の併記ブロック
    kw_ja = cfg["kw_ja"][di % len(cfg["kw_ja"])]
    kw_en = cfg["kw_en"][di % len(cfg["kw_en"])]

    H = MEO_DAILY_SHEETS["MEO_DAILY_TASKS"]
    rows, dac = [], []

    def add(dtype, mtype, post_ja="", post_en="", photo=False, rev_req=False,
            rev_reply=False, pri="A", taskmsg=""):
        r = {h: "" for h in H}
        r.update({"日付": today, "事業名": name, "daily_action_type": dtype,
                  "meo_task_type": mtype, "target_keyword_ja": kw_ja,
                  "target_keyword_en": kw_en,
                  "post_language_type": "日英" if post_en else "日本語",
                  "google_post_text_ja": post_ja, "google_post_text_en": post_en,
                  "photo_required": "要" if photo else "",
                  "review_request_required": "要" if rev_req else "",
                  "review_reply_required": "要" if rev_reply else "",
                  "due_time": "本日中", "completion_status": "未完了"})
        rows.append([r[h] for h in H])
        if taskmsg:
            dac.append({"biz_key": biz_key, "priority": pri, "task": taskmsg})

    # ① Google最新投稿（毎日・日英）
    add("Google投稿", "最新投稿", title, en_title, pri="S",
        taskmsg=f"【MEO】Google投稿(日英): {title}")
    # ② 口コミ依頼（毎日3件以上）
    add("口コミ依頼", "口コミ依頼", rev_req=True, pri="S",
        taskmsg="【MEO】満足度の高い客へGoogle口コミ依頼を3件")
    # ③ 写真追加（週3: 月水金）
    if wd in (0, 2, 4):
        add("写真追加", "写真追加", photo=True, pri="A",
            taskmsg="【MEO】料理/店内/雰囲気の写真を3枚追加")
    # ④ 外国人向け多言語投稿（週3: 火木土）
    if wd in (1, 3, 5):
        add("外国人向け投稿", "多言語投稿", title, multilang or en_title, pri="A",
            taskmsg=f"【MEO/多言語】外国人向け投稿: {(en_title or title)[:30]} ({kw_en})")
    # ⑤ 口コミ返信（週末にまとめ・未返信があれば）
    if wd in (5, 6):
        add("口コミ返信", "口コミ返信", rev_reply=True, pri="B",
            taskmsg="【MEO】未返信のGoogle口コミにまとめて返信")
    # ⑥ 高粗利メニュー訴求（資金繰り危険度S/Aの日に優先）
    danger = False
    try:
        from core.cash_flow import get_status as cf_get
        d = cf_get(ss_id, creds_path)
        danger = d.get("ok") and d.get("危険度") in ("S", "A")
    except Exception:
        pass
    if danger:
        add("高粗利訴求", "高粗利訴求", pri="S",
            taskmsg=f"【MEO/高粗利】{cfg['offer']}を本日重点案内（資金繰り注意日）")

    if not dry_run:
        gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
        ws = _sheet(ss, "MEO_DAILY_TASKS", H)
        # 当日・同事業の既存行は重複させない（あればスキップ）
        existing = {(str(r.get("日付")), str(r.get("事業名")), str(r.get("meo_task_type")))
                    for r in ws.get_all_records()}
        new_rows = [row for row in rows
                    if (today, name, row[3]) not in existing]
        if new_rows:
            ws.append_rows(new_rows, value_input_option="RAW")

    return {"ok": True, "business": name, "date": today, "weekday": wd,
            "tasks": len(rows), "daily_action_tasks": dac, "dry_run": dry_run,
            "keyword_ja": kw_ja, "keyword_en": kw_en}


def meo_status(ss_id, creds_path, date=""):
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    target = date or _date()
    try:
        rows = [r for r in ss.worksheet("MEO_DAILY_TASKS").get_all_records()
                if str(r.get("日付")) == target]
    except gspread.WorksheetNotFound:
        return {"ok": True, "note": "未セットアップ"}
    by = {}
    for r in rows:
        b = by.setdefault(r.get("事業名"), {"total": 0, "done": 0,
                          "google": 0, "photo": 0, "review_req": 0, "review_reply": 0, "en": 0})
        b["total"] += 1
        if str(r.get("completion_status")) in ("完了", "done"):
            b["done"] += 1
        dt = str(r.get("daily_action_type"))
        if "Google投稿" in dt: b["google"] += 1
        if "写真" in dt: b["photo"] += 1
        if "口コミ依頼" in dt: b["review_req"] += 1
        if "口コミ返信" in dt: b["review_reply"] += 1
        if str(r.get("post_language_type")) == "日英" or "外国人" in dt: b["en"] += 1
    return {"ok": True, "date": target, "by_business": by}


def meo_dashboard_refresh(ss_id, creds_path):
    st = meo_status(ss_id, creds_path)
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    dws = _sheet(ss, "MEO_DASHBOARD", MEO_DAILY_SHEETS["MEO_DASHBOARD"])
    gbp = _latest_gbp(ss)  # 事業名→GBP実績文字列
    rows = []
    for biz, b in st.get("by_business", {}).items():
        bk = "tachinomiya" if biz == "TACHINOMIYA" else "ryukyu_hinabe"
        kw = "、".join(MEO_BIZ.get(bk, {}).get("kw_en", [])[:3])
        rows.append([_date(), biz, b["total"], b["done"], b["total"] - b["done"],
                     b["google"], b["photo"], b["review_req"], b["review_reply"],
                     b["en"], gbp.get(biz, "（未入力）"), kw, _now()])
    if rows:
        ex = len(dws.get_all_values())
        if ex > 1:
            dws.batch_clear([f"A2:M{ex}"])
        dws.append_rows(rows, value_input_option="RAW")
    return {"ok": True, "businesses": len(rows)}


# ── STEP2: 完了スクショ判定 ───────────────────────────────

def meo_record_completion_screenshot(ss_id, creds_path, biz_key, image_url):
    """当日の最先の未完了MEOタスクにスクショURLを記録し完了化。返信文を返す。"""
    cfg = MEO_BIZ.get(biz_key)
    if not cfg:
        return {"ok": False}
    name = cfg["name"]; today = _date()
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    try:
        ws = ss.worksheet("MEO_DAILY_TASKS")
    except gspread.WorksheetNotFound:
        return {"ok": False}
    H = MEO_DAILY_SHEETS["MEO_DAILY_TASKS"]
    vals = ws.get_all_values()
    ci = {h: i for i, h in enumerate(H)}
    for r_idx in range(1, len(vals)):
        row = vals[r_idx]
        def c(h): return row[ci[h]] if ci[h] < len(row) else ""
        if c("日付") == today and c("事業名") == name and c("completion_status") != "完了":
            sheet_row = r_idx + 1
            ws.update_acell(f"{chr(65+ci['completion_status'])}{sheet_row}", "完了")
            ws.update_acell(f"{chr(65+ci['completion_screenshot_url'])}{sheet_row}", image_url)
            ws.update_acell(f"{chr(65+ci['ai_check_result'])}{sheet_row}", "スクショ受領・完了")
            return {"ok": True, "completed": c("daily_action_type"),
                    "reply": f"✅ MEO完了を記録しました（{name}: {c('daily_action_type')}）\nスクショありがとうございます！"}
    return {"ok": False, "reply": "本日の未完了MEOタスクが見つかりませんでした。"}


def has_open_meo_task(ss_id, creds_path, biz_key):
    cfg = MEO_BIZ.get(biz_key)
    if not cfg:
        return False
    try:
        gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
        for r in ss.worksheet("MEO_DAILY_TASKS").get_all_records():
            if (str(r.get("日付")) == _date() and str(r.get("事業名")) == cfg["name"]
                    and str(r.get("completion_status")) != "完了"):
                return True
    except Exception:
        pass
    return False


# ── STEP4: GBP実績の手入力（LINEテキスト / EP）─────────────

MEO_GBP_SHEET = {"MEO_GBP_STATS": [
    "登録日時", "事業名", "対象期間", "表示回数", "電話", "ルート検索", "予約", "来店", "メモ"]}

_GBP_LABELS = [("表示回数", ["表示", "インプ", "閲覧"]), ("電話", ["電話", "コール"]),
               ("ルート検索", ["ルート", "経路", "道案内"]), ("予約", ["予約"]),
               ("来店", ["来店", "訪問"])]


def is_gbp_message(text: str) -> bool:
    t = str(text)
    if "GBP" not in t.upper() and "マップ" not in t and "グーグル" not in t:
        return False
    import re
    hits = sum(1 for _, ks in _GBP_LABELS for k in ks if re.search(k + r"\s*\d", t))
    return hits >= 1


def record_gbp(ss_id, creds_path, text, business_name=""):
    import re
    z = str(text).translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    vals = {}
    for field, ks in _GBP_LABELS:
        for k in ks:
            m = re.search(k + r"\s*[:：]?\s*(\d[\d,]*)", z)
            if m:
                vals[field] = int(m.group(1).replace(",", "")); break
    if not vals:
        return {"ok": False, "reply": "GBP実績を認識できませんでした。例：GBP 電話5 ルート12 予約2 来店8"}
    name = business_name
    for bk, cfg in MEO_BIZ.items():
        if cfg["name"] in str(text):
            name = cfg["name"]; break
    name = name or "TACHINOMIYA"
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    ws = _sheet(ss, "MEO_GBP_STATS", MEO_GBP_SHEET["MEO_GBP_STATS"])
    ws.append_row([_now(), name, _date(), vals.get("表示回数", ""), vals.get("電話", ""),
                   vals.get("ルート検索", ""), vals.get("予約", ""), vals.get("来店", ""),
                   "LINE入力"], value_input_option="RAW")
    disp = " ".join(f"{k}{v}" for k, v in vals.items())
    return {"ok": True, "reply": f"✅ GBP実績を記録しました（{name}: {disp}）"}


def _latest_gbp(ss):
    """事業名→最新GBP実績の文字列"""
    out = {}
    try:
        recs = ss.worksheet("MEO_GBP_STATS").get_all_records()
        for r in recs:  # 後勝ち＝最新
            out[r.get("事業名")] = (f"電話{r.get('電話','-')}/ルート{r.get('ルート検索','-')}"
                                   f"/予約{r.get('予約','-')}/来店{r.get('来店','-')}")
    except Exception:
        pass
    return out


def gbp_setup(ss_id, creds_path):
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    _sheet(ss, "MEO_GBP_STATS", MEO_GBP_SHEET["MEO_GBP_STATS"])
    return {"ok": True, "sheet": "MEO_GBP_STATS"}
