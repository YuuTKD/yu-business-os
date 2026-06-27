"""PHASE4/8/9: SNS_POST_MASTER構築 + 勝ち投稿/再利用 + Daily Action連携データ"""
import sys, os, base64, tempfile
from datetime import datetime, timezone, timedelta
sys.path.insert(0, '/Users/tokudayuya/yu-business-os')
b64 = os.getenv('GOOGLE_CREDENTIALS_B64', '')
tf = tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='wb')
tf.write(base64.b64decode(b64)); tf.flush()
import gspread
from google.oauth2.service_account import Credentials
creds = Credentials.from_service_account_file(tf.name, scopes=["https://www.googleapis.com/auth/spreadsheets"])
gc = gspread.authorize(creds)
SS = "1I6wRRDa-b440DBxZ3TbFbfMxEXZecowzOsxTAYSxyBE"
ss = gc.open_by_key(SS)
JST = timezone(timedelta(hours=9))
now = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
today = datetime.now(JST).strftime("%Y-%m-%d")

NAME2KEY = {"琉球火鍋": "ryukyu_hinabe", "TREE's Catering": "catering",
            "TACHINOMIYA": "tachinomiya", "Tree Beauty": "beauty"}
REUSE = {
    "ryukyu_hinabe": "Google投稿/Instagram投稿/Threads再投稿/予約導線投稿/口コミ依頼文",
    "catering": "Catering営業DM/Google投稿/Instagram投稿/Threads再投稿/提案書/CATERING_SALES_TARGETS",
    "tachinomiya": "Google投稿/Instagramストーリー/Threads再投稿/店頭POP/口コミ依頼文",
    "beauty": "HPBブログ/Google投稿/Instagramストーリー/再来店LINE文/口コミ依頼文",
}
KO = {"ryukyu_hinabe": "06_Leads_Sales/threads_winning_posts", "catering": "06_Leads_Sales/threads_winning_posts",
      "tachinomiya": "06_Leads_Sales/threads_winning_posts", "beauty": "06_Leads_Sales/threads_winning_posts"}


def gi(headers):
    return {h: i for i, h in enumerate(headers)}


def num(v):
    try:
        return float(str(v).replace(",", "")) if str(v).strip() not in ("", "-") else 0
    except Exception:
        return 0


# ── SNS_RESULT / SNS_POST_STOCK 読み込み ──
rv = ss.worksheet("SNS_RESULT").get_all_values()
rh, rrows = rv[0], rv[1:]
ri = gi(rh)
sv = ss.worksheet("SNS_POST_STOCK").get_all_values()
sh, srows = sv[0], sv[1:]
si = gi(sh)
# post_id → 本文（stock）
stock_text = {}
for r in srows:
    pid = r[si.get("post_id", 0)] if si.get("post_id", 0) < len(r) else ""
    txt = r[si["original_text"]] if "original_text" in si and si["original_text"] < len(r) else ""
    if pid:
        stock_text[pid] = txt


def col(r, name):
    return r[ri[name]] if name in ri and ri[name] < len(r) else ""


def grade(sales, visit, resv, inq, dm, line, prof, soft, likes):
    if sales > 0 or visit > 0 or resv > 0 or inq > 0:
        return "S", "売上/来店/予約/問合せに直結"
    if dm > 0 or line > 0 or prof > 0:
        return "A", "DM/LINE/プロフィール遷移が発生"
    if soft >= 3:
        return "B", "保存/返信/リポスト等の強い反応"
    if likes > 0:
        return "C", "いいね中心の反応"
    return "除外", "目立った反応なし"


# ── PHASE4: SNS_POST_MASTER ──
MASTER = ["登録日時", "business_key", "事業名", "媒体", "元シート名", "元シート行番号", "予定投稿日",
          "実投稿日時", "投稿本文", "冒頭フック", "投稿URL", "投稿ID", "投稿方法", "投稿ステータス",
          "マッチングステータス", "インサイト取得ステータス", "表示数", "いいね", "保存", "シェア",
          "返信", "リポスト", "コメント", "プロフィール遷移", "LINE", "DM", "予約", "問い合わせ",
          "来店", "売上", "反応率", "売上貢献スコア", "勝ち判定", "勝ち理由", "改善方針",
          "再利用優先度", "再利用先", "Daily Action連携", "Knowledge OS保存先", "最終更新日時",
          "メモ", "エラー内容"]
try:
    mws = ss.worksheet("SNS_POST_MASTER")
except gspread.WorksheetNotFound:
    mws = ss.add_worksheet("SNS_POST_MASTER", rows=2000, cols=len(MASTER))
mws.update(values=[MASTER], range_name="A1", value_input_option="RAW")

existing_ids = set()
ev = mws.get_all_values()
if len(ev) > 1:
    mi = gi(ev[0])
    for r in ev[1:]:
        if mi.get("投稿ID", 11) < len(r):
            existing_ids.add(r[mi["投稿ID"]])

master_rows = []
win_rows = []
reuse_rows = []
counts = {}
for r in rrows:
    plat = col(r, "platform")
    if "Threads" not in plat:
        continue
    pid = col(r, "post_id")
    bn = col(r, "business_name")
    bk = NAME2KEY.get(bn, bn)
    counts.setdefault(bk, {"total": 0, "win_SAB": 0})
    counts[bk]["total"] += 1
    if pid in existing_ids:
        continue
    text = stock_text.get(pid, "") or col(r, "manual_note")
    hook = (text or "").replace("\n", " ")[:30]
    url = col(r, "permalink") or col(r, "post_url") or ""
    pdate = col(r, "posted_date")
    imp = num(col(r, "impressions")); likes = num(col(r, "likes"))
    comments = num(col(r, "comments")); shares = num(col(r, "shares"))
    saves = num(col(r, "saves")); reposts = num(col(r, "reposts")) or num(col(r, "shares"))
    prof = num(col(r, "profile_access")); line = num(col(r, "line_add")); dm = num(col(r, "dm_count"))
    resv = num(col(r, "reservations")) or num(col(r, "予約"))
    inq = num(col(r, "inquiries")) or num(col(r, "問い合わせ"))
    visit = num(col(r, "visits")) or num(col(r, "来店"))
    sales = num(col(r, "sales")) or num(col(r, "売上"))
    soft = saves + shares + comments + reposts
    react = round((likes + soft) / imp, 4) if imp > 0 else 0
    score = sales + visit * 1000 + resv * 800 + inq * 500 + dm * 300 + line * 200 + prof * 50 + (likes + soft)
    g, why = grade(sales, visit, resv, inq, dm, line, prof, soft, likes)
    pri = {"S": "高", "A": "中", "B": "低"}.get(g, "-")
    improve = ""
    if imp > 0 and react < 0.02:
        improve = "低反応率→フック改善"
    elif g in ("C", "除外") and imp > 200:
        improve = "高表示低反応→CTA/オファー見直し"
    elif g == "B":
        improve = "反応良→売上導線(予約/DM)を追加"
    da = "連携予定" if g in ("S", "A") else ""
    master_rows.append([now, bk, bn, "Threads", "SNS_POST_STOCK", "", pdate, pdate, text, hook, url,
                        pid, "手動投稿", "投稿済み", "未マッチ", "インサイト取得済み", imp, likes, saves,
                        shares, comments, reposts, comments, prof, line, dm, resv, inq, visit, sales,
                        react, int(score), g, why, improve, pri, REUSE.get(bk, ""), da,
                        KO.get(bk, ""), now, "", ""])
    # PHASE8: 勝ち投稿（S/A/B）
    if g in ("S", "A", "B"):
        counts[bk]["win_SAB"] += 1
        reuse_text = f"{hook}…の勝ちフックを{REUSE.get(bk,'').split('/')[0]}に再利用"
        win_rows.append([now, bk, bn, "Threads", "SNS_POST_STOCK", "", pdate, url, text, hook, g, why,
                         imp, likes, comments, reposts, dm, resv, inq, visit, sales, pri,
                         REUSE.get(bk, ""), reuse_text, da, ""])
        # 再利用アクション（優先先＝1つ目）
        for dest in REUSE.get(bk, "").split("/")[:2]:
            reuse_rows.append([now, bk, bn, url, "Threads", dest, reuse_text, "スタッフ", today,
                               "未着手", "", "", f"勝ち判定{g}"])

if master_rows:
    mws.append_rows(master_rows, value_input_option="RAW")

# ── PHASE8: SNS_WINNING_POSTS（空シート→spec列に更新）──
WIN = ["検出日時", "business_key", "事業名", "媒体", "元シート名", "元シート行番号", "投稿日時", "投稿URL",
       "投稿本文", "冒頭フック", "勝ち判定", "勝ち理由", "表示数", "いいね", "返信", "リポスト", "DM",
       "予約", "問い合わせ", "来店", "売上", "再利用優先度", "再利用先", "再利用文", "Daily Action連携", "メモ"]
wws = ss.worksheet("SNS_WINNING_POSTS")
if len(wws.get_all_values()) <= 1:  # 空→spec化
    wws.clear(); wws.update(values=[WIN], range_name="A1", value_input_option="RAW")
if win_rows:
    wws.append_rows(win_rows, value_input_option="RAW")

# ── PHASE8: SNS_REUSE_ACTIONS（空シート→spec列）──
REU = ["作成日時", "business_key", "事業名", "元投稿URL", "元媒体", "再利用先", "再利用内容", "担当",
       "期限", "対応状況", "結果", "売上影響", "メモ"]
rws = ss.worksheet("SNS_REUSE_ACTIONS")
if len(rws.get_all_values()) <= 1:
    rws.clear(); rws.update(values=[REU], range_name="A1", value_input_option="RAW")
if reuse_rows:
    rws.append_rows(reuse_rows, value_input_option="RAW")

print("=== PHASE4/8/9 完了 ===")
print(f"SNS_POST_MASTER 新規: {len(master_rows)}行")
print(f"SNS_WINNING_POSTS: {len(win_rows)}行 / SNS_REUSE_ACTIONS: {len(reuse_rows)}行")
print("事業別:")
for bk, c in counts.items():
    print(f"  {bk:14} Threads投稿{c['total']} 勝ち(S/A/B){c['win_SAB']}")
