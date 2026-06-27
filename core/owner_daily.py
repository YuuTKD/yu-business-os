"""OWNER_ONLY Daily Action: 完成原稿生成・オーナー限定LINEテスト配信・返信処理。
実スタッフ/外部送信・自動投稿は一切しない。"""
import os, json
import gspread
from datetime import datetime, timezone, timedelta
from google.oauth2.service_account import Credentials

JST = timezone(timedelta(hours=9))
OWNER_TOKEN_ENV = "LINE_OWNER_TOKEN"
DELIVERY_LOG = "LINE_DELIVERY_LOG"
DELIVERY_LOG_COLS = ["配信日時", "配信モード", "配信先", "対象事業", "タスク数", "配信可否件数",
                     "task_map(JSON)", "本文プレビュー", "結果"]


def _gc(creds_path):
    return gspread.authorize(Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/spreadsheets"]))


def _now():
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M")


def _today():
    return datetime.now(JST).strftime("%Y-%m-%d")


def _sheet(ss, name, header):
    try:
        return ss.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(name, rows=1000, cols=max(len(header), 12))
        ws.update(values=[header], range_name="A1", value_input_option="RAW")
        return ws


# ══ 完成原稿テンプレート（業種×再利用先・そのまま投稿できる形）══
_BIZ_DEFAULT = {
    "tachinomiya": ("国際通りで沖縄の夜を楽しむなら",
        "那覇・国際通り周辺で、沖縄料理やハブ酒を気軽に楽しみたい方へ。\n"
        "TACHINOMIYAでは、観光途中の一杯・一人飲み・沖縄らしい夜の時間にぴったりのメニューをご用意しています。\n"
        "国際通り近くで沖縄の雰囲気を味わいたい方は、ぜひお立ち寄りください。",
        "📍国際通りから徒歩1分／本日も営業中"),
    "catering": ("法人イベント・懇親会のケータリングなら",
        "沖縄県内で法人イベントや懇親会の料理手配をお考えの幹事様へ。\n"
        "TREE's Cateringでは、企業懇親会・周年パーティー・ホテルスイート・BAR/クラブイベントなど、"
        "イベント内容に合わせたケータリングをご相談いただけます。\n"
        "人数・会場・ご予算に合わせてご提案可能です。",
        "🍽️お見積り無料／20名以上はお得"),
    "beauty": ("脱毛・よもぎ蒸し・ホワイトニングのご予約受付中",
        "那覇でセルフケアを始めたい方へ。\n"
        "Tree Beautyでは脱毛・よもぎ蒸し・セルフホワイトニングを、お一人おひとりのお悩みに合わせてご提案します。\n"
        "初回体験・空き枠のご相談もお気軽にどうぞ。",
        "💆初回体験受付中／ご予約はプロフィールから"),
    "ryukyu_hinabe": ("記念日・女子会に琉球薬膳火鍋を",
        "那覇で特別な夜をお探しの方へ。\n"
        "琉球火鍋では、薬膳スープのアグー豚しゃぶしゃぶを完全個室でお楽しみいただけます。\n"
        "記念日・女子会・接待・ご家族のお祝いに、ぜひご利用ください。",
        "🔥ご予約承り中／個室・記念日プレートのご相談も"),
}
_DEST_OVERRIDE = {
    ("catering", "Catering営業DM"): ("【法人ご担当者様へ】懇親会・周年パーティーのご相談",
        "突然のご連絡失礼いたします。沖縄でケータリングを手がけるTREE's Cateringと申します。\n"
        "企業懇親会・周年パーティー・採用イベント等の料理手配を、人数・会場・ご予算に合わせてご提案しております。\n"
        "もしご検討の機会がございましたら、無料でお見積りいたします。",
        "ご返信お待ちしております／お見積り無料"),
    ("beauty", "HPBブログ"): ("自己処理のお悩み、根本から解決しませんか？",
        "毎日のムダ毛処理や肌トラブルにお悩みの方へ。\n"
        "Tree Beautyの脱毛は、自己処理の回数を減らし肌への負担をやさしくケアします。\n"
        "よもぎ蒸し・ホワイトニングと合わせて、トータルで美しさを整えられます。",
        "初回体験のご予約はこちらから"),
}


def finished_copy(bk, dest):
    """(タイトル, 本文, CTA) を返す。完成形・そのまま投稿/送付できる文面。"""
    if (bk, dest) in _DEST_OVERRIDE:
        return _DEST_OVERRIDE[(bk, dest)]
    return _BIZ_DEFAULT.get(bk, ("", "", ""))


# ══ LINE配信モード ══
def delivery_mode():
    return os.getenv("DAILY_ACTION_LINE_MODE", "OFF").upper()  # OFF / OWNER_ONLY / STAFF / DRY_RUN


def _deliverable_reuse(ss):
    """SNS_REUSE_ACTIONS から LINE配信可否=配信OK の行を取得"""
    try:
        rv = ss.worksheet("SNS_REUSE_ACTIONS").get_all_values()
    except gspread.WorksheetNotFound:
        return []
    h = {x: i for i, x in enumerate(rv[0])}
    out = []
    for r in rv[1:]:
        def g(n):
            return r[h[n]] if n in h and h[n] < len(r) else ""
        if g("LINE配信可否") == "配信OK" and g("タスク状態") not in ("完了", "除外"):
            out.append({"bk": g("business_key"), "biz": g("事業名"), "dest": g("再利用先"),
                        "url": g("元投稿URL"), "title": g("完成原稿_タイトル"),
                        "body": g("完成原稿_本文"), "cta": g("完成原稿_CTA"),
                        "perf": g("元投稿実績"), "reason": g("再利用理由")})
    return out


def compose_owner_message(ss, date=None):
    """PHASE E フォーマットでオーナー向けLINE本文を生成。返り値: (text, task_map)"""
    date = date or _today()
    reuse = _deliverable_reuse(ss)
    lines = [f"【YU HOLDINGS Daily Action｜{date}】", "",
             "配信モード：OWNER_ONLY",
             "※現在はゆうさん限定テスト配信です。スタッフには送信されていません。", ""]
    task_map = {}
    if reuse:
        lines.append("━━ SNS勝ち投稿 再利用タスク（確認用）━━")
        for i, t in enumerate(reuse, 1):
            task_map[str(i)] = {"url": t["url"], "dest": t["dest"], "bk": t["bk"]}
            lines += [f"\n【{t['biz']}】No.{i}",
                      f"投稿先：{t['dest']}",
                      f"元投稿実績：{t['perf']}（{t['reason']}）",
                      "完成原稿：",
                      (f"{t['title']}\n{t['body']}\n{t['cta']}").strip(),
                      f"期待アクション：{t['dest']}としてそのまま使えるか確認",
                      "期限：本日中",
                      f"返信：OK {i} ／ 修正 {i} ／ 除外 {i} ／ 再生成 {i}"]
    else:
        lines.append("本日、配信条件を満たす再利用タスクはありません（品質フィルタ通過0件）。")
    lines += ["", "━━ 完了・確認の返信方法 ━━",
              "OK N（確認OK）／修正 N（要修正）／除外 N（除外）／完了 N,M（複数完了）／再生成 N（原稿再生成）"]
    return "\n".join(lines), task_map


def send_owner_daily(creds_path, ss_id, dry_run=None):
    """OWNER_ONLYモードでオーナーにLINEテスト配信し LINE_DELIVERY_LOG に記録"""
    from core.daily_action_commander import _send_line
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    mode = delivery_mode()
    text, task_map = compose_owner_message(ss)
    do_send = (mode == "OWNER_ONLY") and (dry_run is not True)
    sent = False; result = "dry_run/プレビュー"
    if mode == "STAFF":
        return {"ok": False, "error": "STAFF_MODEは未許可（OWNER_ONLY運用中）"}
    if do_send:
        token = os.getenv(OWNER_TOKEN_ENV, "")
        if not token:
            result = f"{OWNER_TOKEN_ENV} 未設定"
        else:
            sent = _send_line(token, text)
            result = "送信成功(オーナー限定)" if sent else "送信失敗"
    # ログ
    log = _sheet(ss, DELIVERY_LOG, DELIVERY_LOG_COLS)
    log.append_row([_now(), mode, "オーナーのみ", "4事業", len(task_map),
                    sum(1 for _ in task_map), json.dumps(task_map, ensure_ascii=False),
                    text[:300], result], value_input_option="RAW")
    return {"ok": True, "mode": mode, "sent": sent, "tasks": len(task_map),
            "result": result, "preview": text}


# ══ PHASE F: 返信コマンド処理 ══
_CMD = {"OK": "オーナー確認OK", "修正": "修正必要", "除外": "除外", "完了": "完了", "再生成": "再生成候補"}


def is_owner_cmd(text):
    import re
    t = str(text).strip()
    return bool(re.match(r"^(OK|修正|除外|完了|再生成)\s*[\d, ，]+$", t, re.I))


def handle_owner_reply(creds_path, ss_id, text, reply_token=""):
    """OK/修正/除外/完了/再生成 N[,M] を SNS_REUSE_ACTIONS に反映"""
    import re
    from core.daily_action_commander import _send_line_reply
    gc = _gc(creds_path); ss = gc.open_by_key(ss_id)
    m = re.match(r"^(OK|修正|除外|完了|再生成)\s*(.+)$", str(text).strip(), re.I)
    if not m:
        return {"ok": False}
    cmd = m.group(1).upper() if m.group(1).upper() == "OK" else m.group(1)
    nums = [n for n in re.split(r"[,\s，]+", m.group(2)) if n.strip().isdigit()]
    # 最新の配信task_mapを取得
    log = ss.worksheet(DELIVERY_LOG).get_all_values()
    task_map = {}
    if len(log) > 1:
        task_map = json.loads(log[-1][6]) if len(log[-1]) > 6 and log[-1][6] else {}
    rws = ss.worksheet("SNS_REUSE_ACTIONS")
    rv = rws.get_all_values(); h = {x: i for i, x in enumerate(rv[0])}
    updated = []
    status = _CMD.get(cmd, cmd)
    for n in nums:
        tinfo = task_map.get(n)
        if not tinfo:
            continue
        for ri in range(1, len(rv)):
            row = rv[ri]
            bkv = row[h["business_key"]] if h.get("business_key", 1) < len(row) else ""
            dest = row[h["再利用先"]] if h.get("再利用先", 5) < len(row) else ""
            if bkv == tinfo["bk"] and dest == tinfo["dest"]:
                def setc(col, val):
                    if col in h:
                        rws.update_cell(ri + 1, h[col] + 1, val)
                setc("オーナー確認ステータス", status)
                setc("返信内容", str(text).strip())
                setc("返信日時", _now())
                if cmd == "完了":
                    setc("タスク状態", "完了"); setc("完了日時", _now())
                elif cmd == "除外":
                    setc("タスク状態", "除外"); setc("除外理由", "オーナー除外")
                elif cmd == "修正":
                    setc("タスク状態", "修正待ち")
                elif cmd == "再生成":
                    setc("タスク状態", "再生成待ち")
                else:  # OK
                    setc("タスク状態", "確認OK")
                updated.append(n)
                break
    if not updated:
        # 再利用タスクに一致しない→既存のDaily Action完了処理へフォールスルー
        return {"ok": False, "cmd": cmd, "updated": []}
    reply = f"✅ {cmd} を記録しました（No.{','.join(updated)}）"
    if reply_token:
        token = os.getenv(OWNER_TOKEN_ENV, "")
        if token:
            _send_line_reply(reply_token, reply, token)
    return {"ok": True, "cmd": cmd, "updated": updated, "reply": reply}
