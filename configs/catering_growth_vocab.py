"""
TREE's Catering 広告費ゼロ集客OS — 語彙の正典（コード側）
------------------------------------------------------------
流入元・ステータス・種別・UTM・失注理由の許容値を単一の正本として持つ。

正典文書: `docs/catering-growth/vocabulary.md`
コードとドキュメントが矛盾した場合はドキュメントが正しい。値を変えるときは
ドキュメント → このファイル → テスト → シート の順で直す（逆順は本番シートの作り直しになる）。

安全設計:
  - 純粋な定数と純関数のみ。I/O・ネットワーク・gspread・AI API を一切使わない
  - 秘密情報・spreadsheet ID の実値を含まない
  - LP の URL は環境変数から読む（このファイルには持たない）
"""

from __future__ import annotations

# ── 流入元コード（12種）─ vocabulary.md §1 ──────────────────
# どこから来たお客さんか。機械集計の正本。空欄は禁止（迷ったら "other"）。
SOURCE_CODES: dict[str, str] = {
    "existing_customer": "過去のお客さん",
    "existing_network":  "既存人脈",
    "own_business":      "自社の他事業の顧客",
    "partner_space":     "レンタルスペース経由",
    "partner_bar":       "BAR・クラブ経由",
    "partner_wedding":   "結婚式二次会会場経由",
    "google_business":   "Googleビジネスプロフィール",
    "instagram":         "Instagram",
    "line":              "LINE公式アカウント",
    "referral":          "紹介",
    "organic_search":    "検索からの自然流入",
    "other":             "その他・不明",
}

SOURCE_CODE_DEFAULT = "other"

# 自動判定（UTM）で入る流入元。手入力しない。
SOURCE_CODES_AUTO: tuple[str, ...] = (
    "partner_space", "partner_bar", "partner_wedding",
    "google_business", "instagram", "line", "organic_search",
)


# ── 種別（11種）─ vocabulary.md §3 ──────────────────────────
# 相手はどういう立場の人か。攻め方が変わる。
CONTACT_TYPES: dict[str, str] = {
    "past_customer":  "過去顧客",
    "network":        "既存人脈",
    "own_business":   "自社事業の顧客",
    "partner_space":  "レンタルスペース",
    "partner_bar":    "BAR・クラブ",
    "partner_wedding": "結婚式二次会会場",
    "hotel_villa":    "ホテル・ヴィラ",
    "event_company":  "イベント会社",
    "decor":          "バルーン・装飾会社",
    "studio":         "撮影スタジオ",
    "beauty_bridal":  "美容・ブライダル関係",
}

CONTACT_TYPE_DEFAULT = "network"

# 提携先として扱う種別（提携先数のカウント対象）
PARTNER_CONTACT_TYPES: tuple[str, ...] = (
    "partner_space", "partner_bar", "partner_wedding",
    "hotel_villa", "event_company", "decor", "studio", "beauty_bridal",
)


# ── ステータス（13種）─ vocabulary.md §2 ────────────────────
STATUSES: dict[str, str] = {
    "NEW":               "登録したばかり",
    "READY_TO_CONTACT":  "連絡する準備ができた",
    "CONTACTED":         "初回連絡した",
    "FOLLOW_UP_1":       "1回目のフォローをした",
    "FOLLOW_UP_2":       "2回目のフォローをした",
    "REPLIED":           "返事が来た",
    "MEETING":           "打ち合わせ・商談になった",
    "PARTNER_LISTED":    "提携先として掲載された",
    "INQUIRY":           "問い合わせが発生した",
    "QUOTED":            "見積を出した",
    "WON":               "受注した",
    "LOST":              "失注した",
    "DORMANT":           "反応がなく休眠",
}

STATUS_DEFAULT = "NEW"

# 終了状態。ここからは戻さない（追加受注は新しい行として登録する）。
STATUS_TERMINAL: tuple[str, ...] = ("WON", "LOST")

# 想定される遷移。ここに無い遷移は「警告を出すが止めない」（現場が実態に合わせられるように）。
STATUS_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "NEW":              ("READY_TO_CONTACT",),
    "READY_TO_CONTACT": ("CONTACTED",),
    "CONTACTED":        ("FOLLOW_UP_1", "REPLIED"),
    "FOLLOW_UP_1":      ("FOLLOW_UP_2", "REPLIED"),
    "FOLLOW_UP_2":      ("DORMANT", "REPLIED"),
    "REPLIED":          ("MEETING", "INQUIRY", "PARTNER_LISTED", "DORMANT"),
    "MEETING":          ("PARTNER_LISTED", "INQUIRY", "LOST"),
    "PARTNER_LISTED":   ("INQUIRY", "DORMANT"),
    "INQUIRY":          ("QUOTED", "LOST"),
    "QUOTED":           ("WON", "LOST"),
    "WON":              (),
    "LOST":             (),
    "DORMANT":          ("READY_TO_CONTACT",),
}

# REPLIED はどの段階からでも入る（相手はいつ返事してくるか分からない）。
STATUS_ALWAYS_REACHABLE: tuple[str, ...] = ("REPLIED",)


# ── UTM（vocabulary.md §4）────────────────────────────────
# utm_source には SOURCE_CODES のキーをそのまま使う。
UTM_MEDIUMS: dict[str, str] = {
    "line":           "LINEのメッセージ",
    "dm":             "Instagram/ThreadsのDM",
    "email":          "メール",
    "story":          "Instagramストーリー",
    "feed":           "Instagramフィード投稿",
    "gbp_post":       "Googleビジネスプロフィールの投稿",
    "qr":             "印刷物のQRコード",
    "referral_card":  "紹介カード（紙）",
    "organic":        "自然流入",
}

# 小文字英数字とアンダースコアのみ。日本語・空白・大文字・ハイフンは禁止。
UTM_TOKEN_PATTERN = r"^[a-z0-9_]+$"

# LP のベースURLは実値を持たず、この環境変数から読む。
# 未設定時のフォールバックは configs.business_registry の catering.booking_url。
LP_BASE_URL_ENV = "CATERING_LP_BASE_URL"


# ── 失注理由（8種）─ vocabulary.md §6 ───────────────────────
# price と date_unavailable は打ち手が正反対（値下げ / 値上げ）なので必ず記録する。
LOST_REASONS: dict[str, str] = {
    "price":             "予算が合わなかった",
    "date_unavailable":  "日程が埋まっていた",
    "menu_mismatch":     "料理内容が希望と違った",
    "headcount":         "人数が対応範囲外",
    "competitor":        "他社に決まった",
    "internal_cancel":   "相手側の都合で企画が消えた",
    "no_response":       "途中で連絡が途絶えた",
    "other":             "その他",
}

LOST_REASON_DEFAULT = "other"


# ── 優先度（3種）─ vocabulary.md §7 ────────────────────────
# 行動の優先順。受注確率は別列の「見込み確度」(0-100) で持つ。
PRIORITIES: tuple[str, ...] = ("A", "B", "C")
PRIORITY_DEFAULT = "B"

CONFIDENCE_MIN = 0
CONFIDENCE_MAX = 100


# ── ID 形式（vocabulary.md §5）─────────────────────────────
# 一度振ったIDは変えない・使い回さない（行を消しても欠番にする）。
ID_PREFIX_CONTACT  = "tc_"    # tc_0042      対象先ID
ID_PREFIX_INQUIRY  = "inq_"   # inq_202608_007  問い合わせID
ID_PREFIX_TEMPLATE = "tpl_"   # tpl_partner_space_01

ID_PATTERN_CONTACT  = r"^tc_\d{4}$"
ID_PATTERN_INQUIRY  = r"^inq_\d{6}_\d{3}$"
ID_PATTERN_TEMPLATE = r"^tpl_[a-z0-9_]+$"


# ── 既存列からの写像 ──────────────────────────────────────
# 既存の自由記述列は消さずに残し、機械集計用の正本列へ機械的に変換する。

# `02_問い合わせ.経路`（自由記述）→ 流入元コード。
# 部分一致・大小文字無視。**上から順に評価し、最初に当たったものを採用する。**
# 「結婚式二次会会場」は「会場」にも当たるため partner_wedding を partner_space より前に置く。
SOURCE_FROM_ROUTE_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("二次会", "ウェディング", "結婚式", "ブライダル"), "partner_wedding"),
    (("紹介", "口コミ", "クチコミ"),                      "referral"),
    (("リピート", "既存", "前回", "再依頼", "再注文"),      "existing_customer"),
    (("知り合い", "人脈", "直接", "知人"),                "existing_network"),
    (("インスタ", "instagram", "insta"),                 "instagram"),
    (("line", "ライン"),                                 "line"),
    (("google", "グーグル", "マップ", "meo", "gbp"),       "google_business"),
    (("検索", "seo", "web", "hp", "ホームページ", "サイト"), "organic_search"),
    (("立ち飲み", "tachinomiya", "サロン", "火鍋", "自社"),  "own_business"),
    (("bar", "バー", "クラブ"),                           "partner_bar"),
    (("スペース", "会場"),                                "partner_space"),
)

# 短くて誤爆しやすいトークンは完全一致のみで判定する（例: "ig" が "signature" に当たるのを防ぐ）。
SOURCE_FROM_ROUTE_EXACT: dict[str, str] = {
    "ig":   "instagram",
    "fb":   "other",
    "tel":  "other",
    "電話":  "other",
}

# `CATERING_SALES_TARGETS.カテゴリ`（既存・日本語）→ 種別。
TYPE_FROM_CATEGORY_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("結婚式", "二次会", "ウェディング", "ブライダル会場"), "partner_wedding"),
    (("ホテル", "ヴィラ", "旅館", "リゾート"),              "hotel_villa"),
    (("レンタルスペース", "スペース", "貸切", "会場"),        "partner_space"),
    (("bar", "バー", "クラブ", "居酒屋", "ラウンジ"),        "partner_bar"),
    (("イベント", "企画"),                                "event_company"),
    (("バルーン", "装飾", "デコレーション", "花"),           "decor"),
    (("スタジオ", "撮影", "フォト"),                       "studio"),
    (("美容", "サロン", "ヘア", "ネイル", "エステ"),         "beauty_bridal"),
    (("過去顧客", "既存顧客", "リピート"),                  "past_customer"),
    (("自社",),                                          "own_business"),
)


# ── 純関数 ───────────────────────────────────────────────

def _norm(value: object) -> str:
    """比較用に正規化（前後空白を落として小文字化）。None も安全に扱う。"""
    return str(value or "").strip().lower()


def col_letter(n: int) -> str:
    """1始まりの列番号を A1 記法の列文字に変換する（1→A, 22→V, 33→AG）。

    シートのヘッダ書式の範囲を列数から算出するために使う。
    範囲をハードコードすると、列を増やしたときに右端が未装飾のまま残る。
    """
    if n < 1:
        raise ValueError("列番号は 1 以上にしてください")
    letters = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def is_valid_source_code(value: object) -> bool:
    return str(value or "").strip() in SOURCE_CODES


def is_valid_contact_type(value: object) -> bool:
    return str(value or "").strip() in CONTACT_TYPES


def is_valid_status(value: object) -> bool:
    return str(value or "").strip() in STATUSES


def is_valid_lost_reason(value: object) -> bool:
    return str(value or "").strip() in LOST_REASONS


def is_valid_priority(value: object) -> bool:
    return str(value or "").strip().upper() in PRIORITIES


def is_valid_utm_medium(value: object) -> bool:
    return str(value or "").strip() in UTM_MEDIUMS


def is_transition_allowed(current: object, nxt: object) -> bool:
    """想定内の遷移かを返す。呼び出し側は False でも止めず警告に留める。"""
    cur = str(current or "").strip()
    nx  = str(nxt or "").strip()
    if nx not in STATUSES:
        return False
    if nx in STATUS_ALWAYS_REACHABLE:
        return cur in STATUSES and cur not in STATUS_TERMINAL
    return nx in STATUS_TRANSITIONS.get(cur, ())


def source_from_route(route: object) -> str:
    """既存の自由記述 `経路` から流入元コードを機械的に決める。当たらなければ other。"""
    text = _norm(route)
    if not text:
        return SOURCE_CODE_DEFAULT
    if text in SOURCE_FROM_ROUTE_EXACT:
        return SOURCE_FROM_ROUTE_EXACT[text]
    for keywords, code in SOURCE_FROM_ROUTE_RULES:
        if any(kw in text for kw in keywords):
            return code
    return SOURCE_CODE_DEFAULT


def contact_type_from_category(category: object) -> str:
    """既存の `カテゴリ`（日本語）から種別を機械的に決める。当たらなければ既定値。"""
    text = _norm(category)
    if not text:
        return CONTACT_TYPE_DEFAULT
    for keywords, code in TYPE_FROM_CATEGORY_RULES:
        if any(kw in text for kw in keywords):
            return code
    return CONTACT_TYPE_DEFAULT


def derive_status(
    reply: object = "",
    negotiation: object = "",
    quote: object = "",
    deal: object = "",
    first_contact: object = "",
    days_since_contact: int | None = None,
) -> str:
    """既存4列（返信状況・商談状況・見積状況・成約状況）から 13値ステータスを導出する。

    vocabulary.md §2 の判定表と同じ順で、上から最初に当たったものを返す。
    既存4列は消さずに残し、この関数の出力を `ステータス` 列の正本とする。
    """
    r, n, q, d = _norm(reply), _norm(negotiation), _norm(quote), _norm(deal)

    # 「未成約」「未提出」は否定形。"未" を含む値を成立扱いしないこと（既存テストデータの既定値）。
    if ("成約" in d or "受注" in d) and "未" not in d:
        return "WON"
    if "失注" in d:
        return "LOST"
    if "提出済" in q or ("提出" in q and "未" not in q):
        return "QUOTED"
    if any(k in n for k in ("商談中", "打合せ", "打ち合わせ", "商談化")):
        return "MEETING"
    if "返信あり" in r or ("返信" in r and "待ち" not in r and "未" not in r):
        return "REPLIED"

    if str(first_contact or "").strip():
        if days_since_contact is not None:
            if days_since_contact > 7:
                return "FOLLOW_UP_2"
            if days_since_contact > 3:
                return "FOLLOW_UP_1"
        return "CONTACTED"

    return STATUS_DEFAULT


def has_contact_channel(row: dict) -> bool:
    """連絡手段（電話・メール・Instagram）が1つでもあるか。READY_TO_CONTACT の判定に使う。"""
    return any(str(row.get(k, "") or "").strip() for k in ("電話", "メール", "Instagram"))


def format_contact_id(seq: int) -> str:
    """対象先ID を採番する。tc_0042 形式。"""
    if seq < 1:
        raise ValueError("対象先ID の連番は 1 以上にしてください")
    if seq > 9999:
        raise ValueError("対象先ID は 4 桁までです（tc_9999 が上限）")
    return f"{ID_PREFIX_CONTACT}{seq:04d}"


def format_inquiry_id(year_month: str, seq: int) -> str:
    """問い合わせID を採番する。inq_202608_007 形式。year_month は 'YYYYMM'。"""
    ym = str(year_month or "").strip()
    if len(ym) != 6 or not ym.isdigit():
        raise ValueError("year_month は 'YYYYMM'（数字6桁）で指定してください")
    if seq < 1 or seq > 999:
        raise ValueError("問い合わせID の連番は 1〜999 です")
    return f"{ID_PREFIX_INQUIRY}{ym}_{seq:03d}"
