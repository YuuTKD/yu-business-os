"""PHASE3/2: 既存Threads投稿管理シートへ実績反映列を追加＋本文マッチング"""
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
JST = timezone(timedelta(hours=9))
now = datetime.now(JST).strftime("%Y-%m-%d %H:%M")

# 実投稿（SNS_POST_MASTER）から first30→実績 を作る
cs = gc.open_by_key(SS)
mv = cs.worksheet("SNS_POST_MASTER").get_all_values()
mh = {h: i for i, h in enumerate(mv[0])}


def mc(r, n):
    return r[mh[n]] if n in mh and mh[n] < len(r) else ""


def norm(t):
    return "".join(str(t).split())[:30]


actual = {}  # business_key → {first30: rowdict}
for r in mv[1:]:
    bk = mc(r, "business_key")
    actual.setdefault(bk, {})[norm(mc(r, "投稿本文"))] = r

REFLECT = ["Threads投稿ID", "投稿URL_実績", "実投稿日時", "表示数_実績", "いいね_実績", "返信_実績",
           "リポスト_実績", "インサイト取得日時", "分析ステータス", "勝ち判定", "勝ち理由",
           "改善コメント", "再利用先", "DailyAction連携予定", "連携メモ"]

CFG = {
    "beauty": (SS, "10Threads投稿", 1, 4),
    "tachinomiya": ("1K4KkAhFwVkQqqvzeqa25-1sR26ltBfP9gY9h-N4gXcc", "10_Threads", 2, 3),
    "catering": ("1tNE35iQAVk6eTGEu68WDrRpv9FDIeVT_eK66iRi78Zs", "10_Threads", 2, 3),
    "ryukyu_hinabe": ("1jwFmQtrertjIc6yYFJEyDptLdSUgD5xLdHDAxQhIQzw", "10_Threads投稿", 2, 3),
}

result = {}
for bk, (sid, sheet, hrow, bidx) in CFG.items():
    ss = gc.open_by_key(sid)
    ws = ss.worksheet(sheet)
    vals = ws.get_all_values()
    header = vals[hrow - 1]
    base = len(header)
    # 既存に反映列が無ければ末尾追加
    if "Threads投稿ID" not in header:
        from gspread.utils import rowcol_to_a1
        start = rowcol_to_a1(hrow, base + 1)
        ws.update(values=[REFLECT], range_name=start, value_input_option="RAW")
        col_start = base
    else:
        col_start = header.index("Threads投稿ID")
    # データ行を走査してマッチング
    amap = actual.get(bk, {})
    matched = 0; unmatched = 0
    updates = []  # (row, [reflect values])
    for ri in range(hrow, len(vals)):
        row = vals[ri]
        body = row[bidx] if bidx < len(row) else ""
        if not str(body).strip():
            continue
        a = amap.get(norm(body))
        if a:
            matched += 1
            ref = [mc(a, "投稿ID"), mc(a, "投稿URL"), mc(a, "実投稿日時"), mc(a, "表示数"),
                   mc(a, "いいね"), mc(a, "返信"), mc(a, "リポスト"), now, "本文マッチ済み",
                   mc(a, "勝ち判定"), mc(a, "勝ち理由"), mc(a, "改善方針"), mc(a, "再利用先"),
                   mc(a, "Daily Action連携"), "API実績照合"]
        else:
            unmatched += 1
            ref = ["", "", "", "", "", "", "", "", "未マッチ(投稿予定)", "", "", "", "", "", "投稿後に再照合"]
        updates.append((ri + 1, ref))
    # バッチ書き込み（反映列範囲）
    if updates:
        from gspread.utils import rowcol_to_a1
        data = []
        for rownum, ref in updates:
            a1 = rowcol_to_a1(rownum, col_start + 1)
            data.append({"range": a1, "values": [ref]})
        ws.batch_update(data, value_input_option="RAW")
    result[bk] = {"matched": matched, "unmatched": unmatched, "cols_added": "Threads投稿ID" not in header}

print("=== PHASE3 反映結果 ===")
for bk, r in result.items():
    print(f"  {bk:14} マッチ{r['matched']} / 未マッチ{r['unmatched']} / 列追加{r['cols_added']}")
