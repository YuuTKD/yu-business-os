"""SNS統合中間管理: 4事業インサイト一括同期 / 分析 / SNS_POST_MASTER・勝ち投稿・再利用の再生成。
本番LINE送信や自動投稿は行わない（データ生成のみ）。"""
import gspread
from datetime import datetime, timezone, timedelta
from google.oauth2.service_account import Credentials

JST = timezone(timedelta(hours=9))
BIZ_KEYS = ["ryukyu_hinabe", "catering", "tachinomiya", "beauty"]
NAME2KEY = {"琉球火鍋": "ryukyu_hinabe", "TREE's Catering": "catering",
            "TACHINOMIYA": "tachinomiya", "Tree Beauty": "beauty"}
REUSE = {
    "ryukyu_hinabe": "Google投稿/Instagram投稿/Threads再投稿/予約導線投稿/口コミ依頼文",
    "catering": "Catering営業DM/Google投稿/Instagram投稿/Threads再投稿/提案書/CATERING_SALES_TARGETS",
    "tachinomiya": "Google投稿/Instagramストーリー/Threads再投稿/店頭POP/口コミ依頼文",
    "beauty": "HPBブログ/Google投稿/Instagramストーリー/再来店LINE文/口コミ依頼文",
}
MASTER_COLS = ["登録日時", "business_key", "事業名", "媒体", "元シート名", "元シート行番号", "予定投稿日",
               "実投稿日時", "投稿本文", "冒頭フック", "投稿URL", "投稿ID", "投稿方法", "投稿ステータス",
               "マッチングステータス", "インサイト取得ステータス", "表示数", "いいね", "保存", "シェア",
               "返信", "リポスト", "コメント", "プロフィール遷移", "LINE", "DM", "予約", "問い合わせ",
               "来店", "売上", "反応率", "売上貢献スコア", "勝ち判定", "勝ち理由", "改善方針",
               "再利用優先度", "再利用先", "Daily Action連携", "Knowledge OS保存先", "最終更新日時",
               "メモ", "エラー内容"]
WIN_COLS = ["検出日時", "business_key", "事業名", "媒体", "元シート名", "元シート行番号", "投稿日時",
            "投稿URL", "投稿本文", "冒頭フック", "勝ち判定", "勝ち理由", "表示数", "いいね", "返信",
            "リポスト", "DM", "予約", "問い合わせ", "来店", "売上", "再利用優先度", "再利用先",
            "再利用文", "Daily Action連携", "メモ"]
REU_COLS = ["作成日時", "business_key", "事業名", "元投稿URL", "元媒体", "再利用先", "再利用内容",
            "担当", "期限", "対応状況", "結果", "売上影響", "メモ"]
# PHASE G/H: 完成原稿＋LINE配信トラッキングを末尾追加した全列
REU_COLS_FULL = REU_COLS + [
    "完成原稿_タイトル", "完成原稿_本文", "完成原稿_CTA", "使用画像有無", "元投稿実績", "再利用理由",
    "LINE配信可否", "LINE配信モード", "LINE配信日時", "LINE配信先", "オーナー確認ステータス",
    "返信内容", "返信日時", "タスク状態", "除外理由", "修正メモ", "完了日時"]


def _gc(creds_path):
    return gspread.authorize(Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/spreadsheets"]))


def _now():
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M")


def _today():
    return datetime.now(JST).strftime("%Y-%m-%d")


def _num(v):
    try:
        s = str(v).replace(",", "").strip()
        return float(s) if s not in ("", "-") else 0
    except Exception:
        return 0


def _sheet(ss, name, header):
    try:
        return ss.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(name, rows=2000, cols=max(len(header), 26))
        ws.update(values=[header], range_name="A1", value_input_option="RAW")
        return ws


def sync_all(ss_id, creds_path):
    """4事業のThreadsインサイトを一括同期（既存sync_insights流用）"""
    from core.threads_api import sync_insights
    out = {}
    for bk in BIZ_KEYS:
        try:
            r = sync_insights(ss_id, creds_path, bk, limit=25)
            out[bk] = {"posts_synced": r.get("posts_synced"), "new_stock": r.get("new_stock"),
                       "ok": r.get("ok")}
        except Exception as e:
            out[bk] = {"ok": False, "error": str(e)[:120]}
    return {"ok": True, "synced": out}


def analyze_all(ss_id, creds_path):
    """SNS分析＋ダッシュボード更新"""
    from core.sns_pdca import analyze, refresh_dashboard
    res = {}
    try:
        a = analyze(ss_id, creds_path)
        res["analyze"] = {"ok": a.get("ok"), "top": a.get("top_count"), "weak": a.get("weak_count")}
    except Exception as e:
        res["analyze"] = {"ok": False, "error": str(e)[:120]}
    try:
        refresh_dashboard(ss_id, creds_path); res["dashboard"] = True
    except Exception as e:
        res["dashboard"] = f"err:{str(e)[:80]}"
    return {"ok": True, **res}


# PHASE I: 再利用に向かない投稿（求人/お知らせ/内部告知）を除外
EXCLUDE_KW = ["求人", "募集", "大募集", "スタッフ募集", "アルバイト", "バイト", "採用",
              "営業時間", "臨時休業", "休業", "お休み", "定休", "閉店", "時短",
              "お知らせ", "変更のお知らせ", "ご報告", "顔合わせ", "試食会", "プレオープン準備"]


def _is_excluded_content(text):
    t = str(text)
    return any(k in t for k in EXCLUDE_KW)


def _grade(sales, visit, resv, inq, dm, line, prof, soft, likes, imp, text, bk):
    """PHASE J: 売上導線を最優先。求人/お知らせ/低反応は除外。"""
    if _is_excluded_content(text):
        return "除外", "求人/お知らせ/内部告知（再利用対象外）"
    # 低表示低反応
    if (likes + soft) == 0 and imp < 50:
        return "除外", "低表示・低反応"
    if bk == "catering" and imp < 50 and (likes + soft) == 0:
        return "除外", "Catering 表示50未満かつ反応0"
    if sales > 0 or visit > 0 or resv > 0 or inq > 0:
        return "S", "売上/来店/予約/問合せに直結"
    if dm > 0 or line > 0 or prof > 0 or soft >= 5:
        return "A", "DM/LINE/プロフィール遷移・保存/シェア/返信が強い"
    if imp >= 300 or likes >= 10:
        return "B", "表示・いいねは高いが売上導線は不明（確認用）"
    if likes > 0 or imp > 0:
        return "C", "反応が弱い"
    return "除外", "目立った反応なし"


def build_master_and_reuse(ss_id, creds_path):
    """SNS_RESULT×SNS_POST_STOCK → SNS_POST_MASTER 追記、勝ち投稿/再利用を再生成（重複防止）"""
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    now = _now(); today = _today()
    rv = ss.worksheet("SNS_RESULT").get_all_values()
    ri = {h: i for i, h in enumerate(rv[0])}
    sv = ss.worksheet("SNS_POST_STOCK").get_all_values()
    si = {h: i for i, h in enumerate(sv[0])}
    stock_text = {}
    for r in sv[1:]:
        pid = r[si.get("post_id", 0)] if si.get("post_id", 0) < len(r) else ""
        if pid:
            stock_text[pid] = r[si["original_text"]] if "original_text" in si and si["original_text"] < len(r) else ""

    def c(r, n):
        return r[ri[n]] if n in ri and ri[n] < len(r) else ""

    mws = _sheet(ss, "SNS_POST_MASTER", MASTER_COLS)
    mv = mws.get_all_values()
    if not mv or mv[0] != MASTER_COLS:
        mws.update(values=[MASTER_COLS], range_name="A1", value_input_option="RAW")
        mv = mws.get_all_values()
    mi = {h: i for i, h in enumerate(mv[0])}
    existing_ids = {r[mi["投稿ID"]] for r in mv[1:] if mi.get("投稿ID", 11) < len(r)}

    # ── (1) 新規Threads投稿を SNS_POST_MASTER へ追記 ──
    mrows = []
    counts = {}
    for r in rv[1:]:
        if "Threads" not in c(r, "platform"):
            continue
        pid = c(r, "post_id"); bn = c(r, "business_name"); bk = NAME2KEY.get(bn, bn)
        counts.setdefault(bk, {"total": 0, "new": 0, "win": 0})
        counts[bk]["total"] += 1
        if pid in existing_ids:
            continue
        counts[bk]["new"] += 1
        text = stock_text.get(pid, "") or c(r, "manual_note")
        hook = (text or "").replace("\n", " ")[:30]
        url = c(r, "permalink") or c(r, "post_url") or ""
        pdate = c(r, "posted_date")
        imp = _num(c(r, "impressions")); likes = _num(c(r, "likes")); comments = _num(c(r, "comments"))
        shares = _num(c(r, "shares")); saves = _num(c(r, "saves")); reposts = _num(c(r, "reposts")) or shares
        prof = _num(c(r, "profile_access")); line = _num(c(r, "line_add")); dm = _num(c(r, "dm_count"))
        resv = _num(c(r, "reservations")) or _num(c(r, "予約"))
        inq = _num(c(r, "inquiries")) or _num(c(r, "問い合わせ"))
        visit = _num(c(r, "visits")) or _num(c(r, "来店"))
        sales = _num(c(r, "sales")) or _num(c(r, "売上"))
        soft = saves + shares + comments + reposts
        react = round((likes + soft) / imp, 4) if imp > 0 else 0
        score = int(sales + visit * 1000 + resv * 800 + inq * 500 + dm * 300 + line * 200 + prof * 50 + (likes + soft))
        g, why = _grade(sales, visit, resv, inq, dm, line, prof, soft, likes, imp, text, bk)
        pri = {"S": "高", "A": "中", "B": "低"}.get(g, "-")
        improve = ("低反応率→フック改善" if (imp > 0 and react < 0.02)
                   else "高表示低反応→CTA/オファー見直し" if (g in ("C", "除外") and imp > 200)
                   else "反応良→売上導線(予約/DM)を追加" if g == "B" else "")
        da = "連携予定" if g in ("S", "A", "B") else ""
        mrows.append([now, bk, bn, "Threads", "SNS_POST_STOCK", "", pdate, pdate, text, hook, url, pid,
                      "手動投稿", "投稿済み", "未マッチ", "インサイト取得済み", imp, likes, saves, shares,
                      comments, reposts, comments, prof, line, dm, resv, inq, visit, sales, react, score,
                      g, why, improve, pri, REUSE.get(bk, ""), da, "06_Leads_Sales/threads_winning_posts",
                      now, "", ""])
    if mrows:
        mws.append_rows(mrows, value_input_option="RAW")

    # ── (2) 勝ち投稿/再利用を「全Masterから」再構築（除外データ掃除・完成原稿生成・返信状態保持）──
    return _rebuild_winning_reuse(ss, counts)


def _rebuild_winning_reuse(ss, counts=None):
    from core.owner_daily import finished_copy  # 完成原稿生成
    now = _now(); today = _today()
    mv = ss.worksheet("SNS_POST_MASTER").get_all_values()
    mi = {h: i for i, h in enumerate(mv[0])}

    def mc(r, n):
        return r[mi[n]] if n in mi and mi[n] < len(r) else ""

    # 既存SNS_REUSE_ACTIONSのオーナー返信状態を (元URL,再利用先) で退避
    rws = _sheet(ss, "SNS_REUSE_ACTIONS", REU_COLS_FULL)
    prev = {}
    rvals = rws.get_all_values()
    if len(rvals) > 1:
        rh = {h: i for i, h in enumerate(rvals[0])}
        for r in rvals[1:]:
            key = (r[rh.get("business_key", 1)] if rh.get("business_key", 1) < len(r) else "",
                   r[rh.get("再利用先", 5)] if rh.get("再利用先", 5) < len(r) else "")
            prev[key] = {col: (r[rh[col]] if col in rh and rh[col] < len(r) else "")
                         for col in ["オーナー確認ステータス", "返信内容", "返信日時", "タスク状態",
                                     "除外理由", "修正メモ", "完了日時", "LINE配信日時", "LINE配信先",
                                     "LINE配信モード", "LINE配信可否"]}

    win_rows, reu_rows = [], []
    seen_reuse = set()  # (事業,再利用先)で1件に集約（重複配信防止）
    master_updates = []  # 勝ち判定の再判定をMasterへ反映
    for idx, r in enumerate(mv[1:], start=2):
        if mc(r, "媒体") != "Threads":
            continue
        bk = mc(r, "business_key"); bn = mc(r, "事業名")
        url = mc(r, "投稿URL"); hook = mc(r, "冒頭フック"); text = mc(r, "投稿本文")
        imp = _num(mc(r, "表示数")); likes = _num(mc(r, "いいね")); pdate = mc(r, "実投稿日時")
        saves = _num(mc(r, "保存")); shares = _num(mc(r, "シェア"))
        comments = _num(mc(r, "コメント")) or _num(mc(r, "返信")); reposts = _num(mc(r, "リポスト"))
        prof = _num(mc(r, "プロフィール遷移")); line = _num(mc(r, "LINE")); dm = _num(mc(r, "DM"))
        resv = _num(mc(r, "予約")); inq = _num(mc(r, "問い合わせ")); visit = _num(mc(r, "来店"))
        sales = _num(mc(r, "売上")); soft = saves + shares + comments + reposts
        # ★ Master指標から再判定（フィルタ適用）
        g, why = _grade(sales, visit, resv, inq, dm, line, prof, soft, likes, imp, text, bk)
        # Masterの勝ち判定/連携が古ければ更新対象に
        if "勝ち判定" in mi and mc(r, "勝ち判定") != g:
            master_updates.append((idx, mi["勝ち判定"], g))
            if "勝ち理由" in mi:
                master_updates.append((idx, mi["勝ち理由"], why))
            if "Daily Action連携" in mi:
                master_updates.append((idx, mi["Daily Action連携"], "連携予定" if g in ("S", "A", "B") else ""))
        if g not in ("S", "A", "B"):
            continue
        pri = {"S": "高", "A": "中", "B": "低"}.get(g, "低")
        perf = f"表示{imp}/いいね{likes}"
        if counts is not None:
            counts.setdefault(bk, {"total": 0, "new": 0, "win": 0})["win"] += 1
        win_rows.append([now, bk, bn, "Threads", "SNS_POST_STOCK", "", pdate, url, text, hook, g, why,
                         imp, likes, mc(r, "返信"), mc(r, "リポスト"), mc(r, "DM"), mc(r, "予約"),
                         mc(r, "問い合わせ"), mc(r, "来店"), mc(r, "売上"), pri, REUSE.get(bk, ""),
                         f"{hook}…を{REUSE.get(bk,'').split('/')[0]}へ再利用", "連携予定", ""])
        for dest in REUSE.get(bk, "").split("/")[:2]:
            if (bk, dest) in seen_reuse:  # 事業×再利用先は1件に集約
                continue
            seen_reuse.add((bk, dest))
            ttl, body, cta = finished_copy(bk, dest)
            # 配信可否: 完成原稿あり & S/A/B & 業種整合 → 配信OK
            kahi = "配信OK" if (body and g in ("S", "A", "B")) else "要改善"
            reason = (f"確認用(B判定:{why})" if g == "B" else f"{g}判定:{why}")
            p = prev.get((bk, dest), {})
            reu_rows.append([now, bk, bn, url, "Threads", dest,
                             f"{hook}…の実績を活かし{dest}へ", "オーナー", today,
                             p.get("タスク状態") or "未着手", "", "", reason,
                             ttl, body, cta, "任意", perf, reason,
                             kahi, p.get("LINE配信モード", ""), p.get("LINE配信日時", ""),
                             p.get("LINE配信先", ""), p.get("オーナー確認ステータス", ""),
                             p.get("返信内容", ""), p.get("返信日時", ""),
                             p.get("タスク状態") or "未着手", p.get("除外理由", ""),
                             p.get("修正メモ", ""), p.get("完了日時", "")])

    # 再判定結果を SNS_POST_MASTER へ反映（バッチ）
    if master_updates:
        from gspread.utils import rowcol_to_a1
        mws = ss.worksheet("SNS_POST_MASTER")
        mws.batch_update([{"range": rowcol_to_a1(rw, ci + 1), "values": [[val]]}
                          for rw, ci, val in master_updates], value_input_option="RAW")

    wws = _sheet(ss, "SNS_WINNING_POSTS", WIN_COLS)
    wws.clear(); wws.update(values=[WIN_COLS] + win_rows, range_name="A1", value_input_option="RAW")
    rws.clear(); rws.update(values=[REU_COLS_FULL] + reu_rows, range_name="A1", value_input_option="RAW")
    deliverable = sum(1 for r in reu_rows if r[REU_COLS_FULL.index("LINE配信可否")] == "配信OK")
    return {"ok": True, "master_new": len(counts) and sum(c.get("new", 0) for c in counts.values()),
            "winning": len(win_rows), "reuse": len(reu_rows), "配信OK": deliverable,
            "by_business": counts or {}}
