"""
Review & Referral Engine
-------------------------
全事業で口コミ・紹介・再利用を自動で増やし、広告費をかけずに集客力を高める。

最重要ゴール:
  ・口コミ依頼対象を自動抽出
  ・紹介依頼対象を自動抽出
  ・イベント後/来店後/施術後のフォロー漏れを防ぐ
  ・Google口コミ/MEO強化（外国人観光客向け含む）
  ・Daily Action Commander / Knowledge OS へ連携

設計方針: OpenAI不使用・ルールベース＋テンプレート。外部顧客への自動送信はしない（依頼文生成まで）。
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

# ── シート定義 ─────────────────────────────────────────────
REVIEW_SHEETS = {
    "REVIEW_REQUEST_MASTER": [
        "登録日時", "対象日", "事業名", "顧客名", "顧客種別", "連絡先",
        "来店/利用日", "利用内容", "利用金額", "満足度推定", "口コミ依頼優先度",
        "依頼文", "依頼状況", "依頼担当", "依頼日時", "口コミ投稿確認",
        "口コミURL", "評価", "返信状況", "次回アクション", "メモ",
    ],
    "REFERRAL_MASTER": [
        "登録日時", "事業名", "顧客名", "顧客種別", "連絡先",
        "過去利用回数", "過去利用金額", "紹介可能性", "紹介依頼優先度",
        "紹介依頼文", "紹介依頼状況", "紹介先候補", "紹介発生有無",
        "紹介売上", "次回アクション", "担当", "メモ",
    ],
    "REVIEW_DASHBOARD": [
        "日付", "事業名", "口コミ依頼対象数", "依頼済み数", "投稿確認数",
        "平均評価", "未返信口コミ数", "紹介依頼対象数", "紹介発生数",
        "紹介売上", "本日タスク", "最終更新日時",
    ],
    "REVIEW_TEMPLATES": [
        "事業名", "用途", "言語", "顧客種別", "テンプレート本文", "使用条件", "メモ",
    ],
}

REVIEW_USES = ["口コミ依頼", "口コミ返信", "紹介依頼", "イベント後フォロー",
               "施術後フォロー", "来店後フォロー", "外国人観光客向け", "低評価対応"]
LANGS = ["日本語", "英語", "中国語", "韓国語"]


# ── テンプレート（OpenAI不使用・固定文＋言語）─────────────
TEMPLATES = [
    # 事業, 用途, 言語, 顧客種別, 本文, 条件
    ["TACHINOMIYA", "口コミ依頼", "日本語", "観光客",
     "本日はご来店ありがとうございました！沖縄旅行の思い出になっていたら嬉しいです。よろしければGoogle口コミで感想をいただけると、これから沖縄に来る方の参考になります。", "高満足の来店後"],
    ["TACHINOMIYA", "口コミ依頼", "英語", "外国人観光客",
     "Thank you for visiting us today! If you enjoyed your Okinawa experience, we would really appreciate a quick Google review. It helps other travelers find us on Kokusai Street.", "外国人客の来店後"],
    ["TACHINOMIYA", "口コミ依頼", "中国語", "外国人観光客",
     "感谢您今天的光临！如果您喜欢在冲绳的体验，欢迎在Google上留下评价，这将帮助更多游客在国际通找到我们。", "中国語圏の来店後"],
    ["TACHINOMIYA", "口コミ依頼", "韓国語", "外国人観光客",
     "오늘 방문해 주셔서 감사합니다! 오키나와에서 즐거우셨다면 구글 리뷰를 남겨주시면 다른 여행객들에게 큰 도움이 됩니다.", "韓国語圏の来店後"],
    ["Trees Catering", "口コミ依頼", "日本語", "企業担当者",
     "本日はケータリングをご利用いただきありがとうございました。今後の法人イベントや懇親会をご検討される方の参考になりますので、よろしければご感想をいただけますと幸いです。", "イベント完了後"],
    ["Trees Catering", "紹介依頼", "日本語", "幹事",
     "この度はご利用ありがとうございました。もし周りで懇親会やイベントをご予定の方がいらっしゃいましたら、ぜひご紹介いただけますと嬉しいです。", "高満足案件後"],
    ["Tree Beauty", "施術後フォロー", "日本語", "施術後顧客",
     "本日はご来店ありがとうございました。施術後の変化やご感想を口コミでいただけると、とても励みになります。次回のご予約もお気軽にご相談ください。", "施術後"],
    ["Tree Beauty", "紹介依頼", "日本語", "リピート客",
     "いつもありがとうございます。ご友人で美容に興味のある方がいらっしゃいましたら、ぜひご紹介ください。次回ご一緒のご来店もお待ちしております。", "リピート客"],
    ["琉球火鍋", "口コミ依頼", "日本語", "記念日利用客",
     "本日はご来店ありがとうございました。個室・火鍋・しゃぶしゃぶをご検討される方の参考になりますので、よろしければGoogle口コミでご感想をいただけますと幸いです。", "記念日/個室利用後"],
    ["コンサル", "紹介依頼", "日本語", "成果ありクライアント",
     "この度は改善施策をご一緒させていただきありがとうございました。成果事例として今後のご提案品質向上にも活かしたいため、ご感想やご紹介可能な方がいればぜひお知らせください。", "成果確認後"],
    ["全社", "低評価対応", "日本語", "低評価客",
     "この度はご期待に沿えず申し訳ございませんでした。いただいたご意見を真摯に受け止め改善いたします。差し支えなければ詳細をお聞かせいただけますでしょうか。", "★3以下"],
]

# 事業別 口コミ依頼対象ルール（顧客種別・満足度キーワード）
REVIEW_TARGET_RULES = {
    "TACHINOMIYA": ["観光客", "外国人客", "高単価客", "沖縄料理目的客", "サーターアンダギー購入客"],
    "Trees Catering": ["企業担当者", "幹事", "ホテル", "イベント会社", "高満足案件", "写真取得案件", "再注文可能性"],
    "Tree Beauty": ["施術後", "高満足", "初回来店後", "回数券購入後", "効果が出た顧客"],
    "琉球火鍋": ["記念日", "個室利用", "女子会", "観光客", "高単価客"],
    "パスタパスタ": ["成果あり", "売上改善確認", "紹介可能経営者"],
    "Z1": ["成果あり", "売上改善確認", "紹介可能経営者"],
}

REFERRAL_TARGET_RULES = {
    "Trees Catering": ["企業担当者", "幹事", "ホテル", "イベント会社"],
    "Tree Beauty": ["リピート客", "高満足客"],
    "琉球火鍋": ["記念日", "高単価客"],
    "パスタパスタ": ["成果ありクライアント"],
    "Z1": ["成果ありクライアント"],
}


# ── ユーティリティ ────────────────────────────────────────

def _now_jst(): return datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
def _date_jst(): return datetime.now(JST).strftime("%Y-%m-%d")


def _gc(creds_path):
    creds = Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/spreadsheets",
                            "https://www.googleapis.com/auth/drive"])
    return gspread.authorize(creds)


def _gcs(creds_path):
    creds = Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/devstorage.read_write"])
    return gcs_storage.Client(project=GCS_PROJECT, credentials=creds)


def _upload_md_gcs(creds_path, gcs_path, content):
    blob = _gcs(creds_path).bucket(GCS_BUCKET).blob(gcs_path)
    blob.upload_from_string(content.encode("utf-8"), content_type="text/markdown")
    return f"https://storage.googleapis.com/{GCS_BUCKET}/{gcs_path}"


def _get_or_create_sheet(ss, title, header):
    try:
        return ss.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=title, rows=2000, cols=max(len(header), 12))
        ws.update(values=[header], range_name="A1")
        ws.format("A1:Z1", {
            "backgroundColor": {"red": 0.10, "green": 0.10, "blue": 0.25},
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}}})
        return ws


def _pint(v):
    if v is None: return 0
    s = str(v).replace(",", "").replace("¥", "").replace("円", "").replace(" ", "").strip()
    if s in ("", "-", "—"): return 0
    try: return int(float(s))
    except (ValueError, TypeError): return 0


# ── テンプレート選択 ──────────────────────────────────────

def _pick_template(ss_templates, biz, use, lang="日本語", cust_type=""):
    """REVIEW_TEMPLATES（or デフォルト）から最適テンプレを選ぶ"""
    # まず事業×用途×言語、無ければ事業×用途、無ければ全社
    pools = ss_templates if ss_templates else [
        {"事業名": t[0], "用途": t[1], "言語": t[2], "顧客種別": t[3],
         "テンプレート本文": t[4]} for t in TEMPLATES
    ]
    def match(p, strict_lang=True):
        if str(p.get("用途")) != use:
            return False
        if str(p.get("事業名")) not in (biz, "全社"):
            return False
        if strict_lang and lang and str(p.get("言語")) != lang:
            return False
        return True
    for strict in (True, False):
        for p in pools:
            if match(p, strict):
                return str(p.get("テンプレート本文", ""))
    return "ご利用ありがとうございました。よろしければご感想をいただけますと幸いです。"


# ── 優先度・満足度推定（ルールベース）─────────────────────

def _satisfaction(rec) -> str:
    """利用金額・顧客種別・利用内容から満足度を推定（高/中/低）"""
    amt = _pint(rec.get("利用金額"))
    ctype = str(rec.get("顧客種別", ""))
    content = str(rec.get("利用内容", ""))
    keys_high = ["記念日", "個室", "女子会", "成果", "回数券", "効果", "周年", "高満足"]
    if any(k in (ctype + content) for k in keys_high) or amt >= 50_000:
        return "高"
    if amt >= 10_000:
        return "中"
    return "低"


def _review_priority(biz, rec) -> str:
    """口コミ依頼優先度 S/A/B/C"""
    sat = _satisfaction(rec)
    ctype = str(rec.get("顧客種別", ""))
    targets = REVIEW_TARGET_RULES.get(biz, [])
    hit = any(t in (ctype + str(rec.get("利用内容", ""))) for t in targets)
    if sat == "高" and hit:
        return "S"
    if sat == "高" or hit:
        return "A"
    if sat == "中":
        return "B"
    return "C"


def _referral_possibility(biz, rec) -> str:
    cnt = _pint(rec.get("過去利用回数"))
    amt = _pint(rec.get("過去利用金額"))
    ctype = str(rec.get("顧客種別", ""))
    hit = any(t in ctype for t in REFERRAL_TARGET_RULES.get(biz, []))
    if (cnt >= 3 or amt >= 100_000) and hit:
        return "高"
    if cnt >= 2 or hit:
        return "中"
    return "低"


def _lang_for(rec) -> str:
    ctype = str(rec.get("顧客種別", "")) + str(rec.get("利用内容", ""))
    if "外国人" in ctype or "foreign" in ctype.lower():
        return "英語"
    return "日本語"


# ── 公開API ───────────────────────────────────────────────

def setup(spreadsheet_id, creds_path):
    gc = _gc(creds_path); ss = gc.open_by_key(spreadsheet_id)
    created = []
    for name, header in REVIEW_SHEETS.items():
        _get_or_create_sheet(ss, name, header)
        created.append(name)
    # テンプレ初期投入
    try:
        tw = ss.worksheet("REVIEW_TEMPLATES")
        if len(tw.get_all_values()) <= 1:
            rows = [[t[0], t[1], t[2], t[3], t[4], t[5], ""] for t in TEMPLATES]
            tw.append_rows(rows, value_input_option="RAW")
    except Exception:
        pass
    return {"ok": True, "sheets_created": created, "templates_loaded": len(TEMPLATES),
            "url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"}


# ── テストデータ（25件）──────────────────────────────────

def _test_customers():
    now = _now_jst(); d = _date_jst()
    def row(biz, name, ctype, content, amount, cnt=1, past=0, contact=""):
        return {"登録日時": now, "対象日": d, "事業名": biz, "顧客名": name,
                "顧客種別": ctype, "連絡先": contact, "来店/利用日": d,
                "利用内容": content, "利用金額": amount,
                "過去利用回数": cnt, "過去利用金額": past}
    return [
        row("TACHINOMIYA", "観光客A", "観光客", "沖縄料理・泡盛", 6_000),
        row("TACHINOMIYA", "Tourist B", "外国人観光客", "Okinawa food", 8_000),
        row("TACHINOMIYA", "観光客C", "外国人観光客", "サーターアンダギー購入", 4_000),
        row("TACHINOMIYA", "常連D", "高単価客", "沖縄料理目的客", 12_000, cnt=5, past=60_000),
        row("TACHINOMIYA", "一見客E", "一般", "ドリンクのみ", 2_500),
        row("Trees Catering", "F社担当", "企業担当者", "周年パーティー(高満足案件)", 300_000, past=300_000),
        row("Trees Catering", "G幹事", "幹事", "懇親会(写真取得案件)", 200_000),
        row("Trees Catering", "Hホテル", "ホテル", "イベント(再注文可能性)", 250_000, cnt=2, past=500_000),
        row("Trees Catering", "I社小口", "企業担当者", "少人数ランチ", 35_000),
        row("Tree Beauty", "美容客J", "施術後", "脱毛(効果が出た顧客)", 30_000, cnt=1),
        row("Tree Beauty", "リピートK", "リピート客", "よもぎ蒸し(高満足)", 12_000, cnt=4, past=80_000),
        row("Tree Beauty", "初回L", "初回来店後", "ホワイトニング", 15_000),
        row("Tree Beauty", "回数券M", "回数券購入後", "脱毛回数券", 80_000, past=80_000),
        row("琉球火鍋", "記念日N", "記念日", "個室・火鍋", 70_000),
        row("琉球火鍋", "女子会O", "女子会", "個室利用", 60_000),
        row("琉球火鍋", "観光客P", "観光客", "しゃぶしゃぶ", 50_000),
        row("琉球火鍋", "接待Q", "高単価客", "個室・接待", 120_000, cnt=3, past=200_000),
        row("パスタパスタ", "クライアントR", "成果ありクライアント", "売上改善確認", 300_000, cnt=6, past=900_000),
        row("Z1", "クライアントS", "成果ありクライアント", "SNS運用成果", 200_000, cnt=4, past=600_000),
        row("Tree Beauty", "低評価T", "低評価客", "脱毛(★2クレーム)", 30_000),
        row("Trees Catering", "低評価U", "低評価客", "イベント(★3)", 150_000),
        row("TACHINOMIYA", "外国人V", "外国人観光客", "Okinawa local food", 9_000),
        row("琉球火鍋", "記念日W", "記念日", "個室・記念日コース", 80_000),
        row("Tree Beauty", "リピートX", "リピート客", "回数券・高満足", 50_000, cnt=5, past=150_000),
        row("Trees Catering", "イベント会社Y", "イベント会社", "大型イベント(高満足)", 500_000, cnt=2, past=800_000),
    ]


def run_test(spreadsheet_id, creds_path):
    gc = _gc(creds_path); ss = gc.open_by_key(spreadsheet_id)
    for name, header in REVIEW_SHEETS.items():
        _get_or_create_sheet(ss, name, header)
    # テンプレ取得
    try:
        tmpls = ss.worksheet("REVIEW_TEMPLATES").get_all_records()
    except gspread.WorksheetNotFound:
        tmpls = []

    custs = _test_customers()
    rev_rows, ref_rows = [], []
    rev_header = REVIEW_SHEETS["REVIEW_REQUEST_MASTER"]
    ref_header = REVIEW_SHEETS["REFERRAL_MASTER"]
    summary = {"S": 0, "A": 0, "B": 0, "C": 0}
    ref_summary = {"高": 0, "中": 0, "低": 0}

    for c in custs:
        biz = c["事業名"]
        ctype = c["顧客種別"]
        # 低評価対応
        if "低評価" in ctype:
            use, lang = "低評価対応", "日本語"
            pri = "S"
        else:
            use = "口コミ依頼"
            lang = _lang_for(c)
            pri = _review_priority(biz, c)
        summary[pri] = summary.get(pri, 0) + 1
        body = _pick_template(tmpls, biz, use, lang, ctype)
        rev = {**c, "満足度推定": _satisfaction(c), "口コミ依頼優先度": pri,
               "依頼文": body, "依頼状況": "未依頼", "依頼担当": "", "依頼日時": "",
               "口コミ投稿確認": "", "口コミURL": "", "評価": "", "返信状況": "",
               "次回アクション": "本日依頼" if pri in ("S", "A") else "様子見", "メモ": ""}
        rev_rows.append([rev.get(h, "") for h in rev_header])

        # 紹介
        poss = _referral_possibility(biz, c)
        ref_summary[poss] = ref_summary.get(poss, 0) + 1
        if poss in ("高", "中"):
            ref_use = "紹介依頼"
            ref_biz = "コンサル" if biz in ("パスタパスタ", "Z1") else biz
            ref_body = _pick_template(tmpls, ref_biz, ref_use, "日本語", ctype)
            ref = {"登録日時": _now_jst(), "事業名": biz, "顧客名": c["顧客名"],
                   "顧客種別": ctype, "連絡先": c.get("連絡先", ""),
                   "過去利用回数": c.get("過去利用回数", 0), "過去利用金額": c.get("過去利用金額", 0),
                   "紹介可能性": poss, "紹介依頼優先度": "S" if poss == "高" else "A",
                   "紹介依頼文": ref_body, "紹介依頼状況": "未依頼", "紹介先候補": "",
                   "紹介発生有無": "", "紹介売上": 0, "次回アクション": "本日依頼", "担当": "", "メモ": ""}
            ref_rows.append([ref.get(h, "") for h in ref_header])

    ss.worksheet("REVIEW_REQUEST_MASTER").append_rows(rev_rows, value_input_option="RAW")
    if ref_rows:
        ss.worksheet("REFERRAL_MASTER").append_rows(ref_rows, value_input_option="RAW")

    daily(spreadsheet_id, creds_path, write=True)

    return {"ok": True, "test_customers": len(custs),
            "review_priority_summary": summary, "review_requests": len(rev_rows),
            "referral_possibility_summary": ref_summary, "referral_requests": len(ref_rows),
            "dry_run": True,
            "note": "ルールベース＋テンプレート（OpenAI不使用）。外部顧客への自動送信なし。"}


def daily(spreadsheet_id, creds_path, write=True):
    """本日の口コミ/紹介依頼候補を抽出して DASHBOARD 更新"""
    gc = _gc(creds_path); ss = gc.open_by_key(spreadsheet_id)
    try:
        rws = ss.worksheet("REVIEW_REQUEST_MASTER")
    except gspread.WorksheetNotFound:
        return {"ok": False, "error": "REVIEW_REQUEST_MASTER 未作成。/review-setup を実行してください。"}
    rev = rws.get_all_records()
    try:
        ref = ss.worksheet("REFERRAL_MASTER").get_all_records()
    except gspread.WorksheetNotFound:
        ref = []

    by = {}
    for r in rev:
        biz = str(r.get("事業名"))
        b = by.setdefault(biz, {"review_target": 0, "requested": 0, "posted": 0,
                                "unreplied": 0, "ref_target": 0, "ref_done": 0, "ref_sales": 0})
        if str(r.get("口コミ依頼優先度")) in ("S", "A"):
            b["review_target"] += 1
        if str(r.get("依頼状況")) not in ("未依頼", ""):
            b["requested"] += 1
        if str(r.get("口コミ投稿確認")) in ("確認済み", "投稿あり", "あり"):
            b["posted"] += 1
        if str(r.get("評価")) and str(r.get("返信状況")) in ("未返信", ""):
            b["unreplied"] += 1
    for r in ref:
        biz = str(r.get("事業名"))
        b = by.setdefault(biz, {"review_target": 0, "requested": 0, "posted": 0,
                                "unreplied": 0, "ref_target": 0, "ref_done": 0, "ref_sales": 0})
        if str(r.get("紹介依頼優先度")) in ("S", "A"):
            b["ref_target"] += 1
        if str(r.get("紹介発生有無")) in ("あり", "発生"):
            b["ref_done"] += 1
        b["ref_sales"] += _pint(r.get("紹介売上"))

    if write and by:
        dws = _get_or_create_sheet(ss, "REVIEW_DASHBOARD", REVIEW_SHEETS["REVIEW_DASHBOARD"])
        existing = {(str(r.get("日付")), str(r.get("事業名"))) for r in dws.get_all_records()}
        rows = []
        for biz, b in by.items():
            if (_date_jst(), biz) in existing:
                continue
            task = f"口コミ依頼{b['review_target']}件/紹介依頼{b['ref_target']}件" if (b['review_target'] or b['ref_target']) else "なし"
            rows.append([_date_jst(), biz, b["review_target"], b["requested"], b["posted"],
                         "—", b["unreplied"], b["ref_target"], b["ref_done"],
                         b["ref_sales"], task, _now_jst()])
        if rows:
            dws.append_rows(rows, value_input_option="RAW")

    return {"ok": True, "by_business": by,
            "total_review_targets": sum(b["review_target"] for b in by.values()),
            "total_referral_targets": sum(b["ref_target"] for b in by.values())}


def get_status(spreadsheet_id, creds_path):
    return daily(spreadsheet_id, creds_path, write=False)


def actions(spreadsheet_id, creds_path):
    """口コミ/紹介依頼候補 → Daily Action連携タスク"""
    gc = _gc(creds_path); ss = gc.open_by_key(spreadsheet_id)
    biz_key_map = {"TACHINOMIYA": "tachinomiya", "Trees Catering": "catering",
                   "Tree Beauty": "beauty", "琉球火鍋": "ryukyu_hinabe",
                   "パスタパスタ": "pasta_pasta", "Z1": "z1"}
    tasks = []
    try:
        rev = ss.worksheet("REVIEW_REQUEST_MASTER").get_all_records()
    except gspread.WorksheetNotFound:
        rev = []
    # 事業別に高優先の口コミ依頼を1タスク化
    seen = set()
    for r in rev:
        biz = str(r.get("事業名"))
        if str(r.get("口コミ依頼優先度")) in ("S", "A") and str(r.get("依頼状況")) in ("未依頼", "") and biz not in seen:
            tasks.append({"biz_key": biz_key_map.get(biz, "owner"), "priority": "A",
                          "task": f"【口コミ依頼】{biz}：高満足客へ口コミ依頼（{r.get('顧客名')}）"})
            seen.add(biz)
    try:
        ref = ss.worksheet("REFERRAL_MASTER").get_all_records()
    except gspread.WorksheetNotFound:
        ref = []
    seen_ref = set()
    for r in ref:
        biz = str(r.get("事業名"))
        if str(r.get("紹介依頼優先度")) in ("S", "A") and biz not in seen_ref:
            tasks.append({"biz_key": biz_key_map.get(biz, "owner"), "priority": "A",
                          "task": f"【紹介依頼】{biz}：紹介可能客へ依頼（{r.get('顧客名')}）"})
            seen_ref.add(biz)
    return {"ok": True, "daily_action_tasks": tasks, "count": len(tasks), "dry_run": True}


def owner_report(spreadsheet_id, creds_path):
    d = daily(spreadsheet_id, creds_path, write=False)
    txt = f"【口コミ・紹介日次レポート】{_date_jst()}\n\n"
    txt += f"⭐ 口コミ依頼対象：{d['total_review_targets']}件\n"
    txt += f"🤝 紹介依頼対象：{d['total_referral_targets']}件\n\n"
    for biz, b in d.get("by_business", {}).items():
        if b["review_target"] or b["ref_target"]:
            txt += f"・{biz}：口コミ{b['review_target']}件 / 紹介{b['ref_target']}件\n"
    return {"ok": True, "report_text": txt, "dry_run": True}


def export_knowledge(spreadsheet_id, creds_path):
    d = daily(spreadsheet_id, creds_path, write=False)
    today = _date_jst()
    md = (f"---\ntitle: 口コミ・紹介状況 {today}\nbusiness: YU HOLDINGS\n"
          f"category: review_referral\ndate: {today}\nsource: review_referral_engine\n"
          f"status: active\ntags: [review, referral, meo, marketing]\n---\n\n"
          f"# 口コミ・紹介状況 — {today}\n\n"
          f"## サマリー\n- 口コミ依頼対象: {d['total_review_targets']}件\n"
          f"- 紹介依頼対象: {d['total_referral_targets']}件\n\n"
          f"## 事業別\n\n| 事業 | 口コミ対象 | 依頼済 | 投稿確認 | 紹介対象 | 紹介発生 | 紹介売上 |\n|---|---|---|---|---|---|---|\n")
    for biz, b in d.get("by_business", {}).items():
        md += (f"| {biz} | {b['review_target']} | {b['requested']} | {b['posted']} "
               f"| {b['ref_target']} | {b['ref_done']} | ¥{b['ref_sales']:,} |\n")
    path = f"{GCS_PREFIX}/06_Leads_Sales/review_referral_status_{today}.md"
    url = _upload_md_gcs(creds_path, path, md)
    return {"ok": True, "path": path, "url": url}
