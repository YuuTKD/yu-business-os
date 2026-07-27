"""
TREE's Catering 広告費ゼロ集客OS — UTM リンク生成
------------------------------------------------------------
LP へのリンクに「どこから来たか」の目印を付ける。無料チャネル別の
受注売上・粗利を追跡するための入口となる部分。

正典文書:
  docs/catering-growth/vocabulary.md   §4（UTM 命名規則）
  docs/catering-growth/sheet-schema.md §2-1（UTM_URL 列）

設計方針:
  - 人に URL を手打ちさせない。対象先ID から決定的に生成してコピーさせる。
    手打ちさせるとタイプミスでその売上が「流入元不明」に落ち、
    どの施策が儲かったのか分からなくなる（仕組みが数字を出さなくなる最頻の失敗）。
  - LP のベースURLはコードに持たない。環境変数 CATERING_LP_BASE_URL から読み、
    無ければ configs.business_registry の catering.booking_url にフォールバックする。

安全設計:
  - ネットワークアクセスなし。外部送信なし。AI API なし。
  - 秘密情報・spreadsheet ID の実値を持たない。
  - この段階では Google Sheets にも触らない（純関数のみ）。
"""

from __future__ import annotations

import os
import re
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from configs.catering_growth_vocab import (
    LP_BASE_URL_ENV,
    UTM_TOKEN_PATTERN,
    is_valid_source_code,
    is_valid_utm_medium,
)

# UTM に載せるパラメータ名（Google 共通仕様。無料で使える）
UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content")

# campaign は tc_<年月>_<用途> 形式。例: tc_202608_partner_open
CAMPAIGN_PATTERN = r"^tc_\d{6}_[a-z0-9_]+$"

_TOKEN_RE    = re.compile(UTM_TOKEN_PATTERN)
_CAMPAIGN_RE = re.compile(CAMPAIGN_PATTERN)


class UtmError(ValueError):
    """UTM の入力が命名規則に反しているときに投げる。

    「黙って直す」ことはしない。小文字化などの自動補正をすると、
    シート上の値と実際のURLが食い違い、集計が静かにズレる。
    """


# ── 検証（純関数）─────────────────────────────────────────

def validate_utm_token(value: object, field: str = "token") -> str:
    """UTM に載せる文字列が命名規則を満たすか検証して返す。

    許すのは小文字英数字とアンダースコアのみ。
    日本語・空白・大文字・ハイフンは**拒否する**（自動変換しない）。
    """
    text = str(value if value is not None else "")
    if text != text.strip():
        raise UtmError(f"{field}: 前後に空白があります → {text!r}")
    if not text:
        raise UtmError(f"{field}: 空です")
    if not _TOKEN_RE.match(text):
        raise UtmError(
            f"{field}: 小文字英数字とアンダースコアのみ使えます"
            f"（日本語・空白・大文字・ハイフンは不可） → {text!r}"
        )
    return text


def validate_campaign(value: object) -> str:
    """campaign が tc_<年月6桁>_<用途> 形式かを検証して返す。"""
    text = validate_utm_token(value, field="utm_campaign")
    if not _CAMPAIGN_RE.match(text):
        raise UtmError(
            "utm_campaign: 'tc_<年月6桁>_<用途>' 形式にしてください"
            f"（例: tc_202608_partner_open） → {text!r}"
        )
    return text


# ── LP のベースURL解決 ────────────────────────────────────

def resolve_lp_base_url(explicit: str | None = None) -> str:
    """LP のベースURLを決める。優先順は explicit → 環境変数 → registry。

    コードに URL の実値を持たないため、どこにも無ければ例外を投げる。
    「空文字のまま UTM を組む」と流入元が全て追跡不能になるので、
    黙って続行しない（fail-closed）。
    """
    if explicit:
        return _require_http_url(explicit, source="引数")

    from_env = os.getenv(LP_BASE_URL_ENV, "").strip()
    if from_env:
        return _require_http_url(from_env, source=f"環境変数 {LP_BASE_URL_ENV}")

    try:
        from configs.business_registry import get as get_config
        booking = str(get_config("catering").get("booking_url", "") or "").strip()
    except Exception:
        booking = ""
    if booking:
        return _require_http_url(booking, source="business_registry.catering.booking_url")

    raise UtmError(
        f"LP のベースURLが未設定です。環境変数 {LP_BASE_URL_ENV} を設定するか、"
        "configs/business_registry.py の catering.booking_url を埋めてください。"
    )


def _require_http_url(value: str, source: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise UtmError(f"{source}: http(s) の URL ではありません → {value!r}")
    return value


# ── UTM URL 生成（純関数）─────────────────────────────────

def build_utm_url(
    source: str,
    medium: str,
    campaign: str,
    content: str | None = None,
    base_url: str | None = None,
) -> str:
    """UTM 付きの LP URL を組み立てる。

    source は流入元コード（vocabulary.md §1 の12値）、
    medium は utm_medium（§4 の9値）、
    campaign は tc_<年月>_<用途>、
    content は対象先ID かテンプレートID（省略時は付けない）。

    既存のクエリ文字列やフラグメント（#...）は保持し、UTM だけを上書きする。
    同じ入力からは常に同じURLが出る（冪等）。
    """
    resolved_base = resolve_lp_base_url(base_url)

    if not is_valid_source_code(source):
        raise UtmError(
            f"utm_source: 流入元コード12値のいずれかにしてください → {source!r}"
        )
    if not is_valid_utm_medium(medium):
        raise UtmError(
            f"utm_medium: 9値のいずれかにしてください → {medium!r}"
        )

    params = {
        "utm_source":   validate_utm_token(source, "utm_source"),
        "utm_medium":   validate_utm_token(medium, "utm_medium"),
        "utm_campaign": validate_campaign(campaign),
    }
    if content is not None and str(content).strip() != "":
        params["utm_content"] = validate_utm_token(content, "utm_content")

    parts = urlsplit(resolved_base)
    # 既存クエリは残し、utm_* だけ差し替える（重複した utm_* は落とす）
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k not in UTM_KEYS]
    query = urlencode(kept + list(params.items()), quote_via=quote)

    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def build_utm_url_for_contact(
    contact_id: str,
    source: str,
    medium: str,
    campaign: str,
    base_url: str | None = None,
) -> str:
    """対象先ID から UTM 付きURLを生成する（`UTM_URL` 列に入れる値）。

    utm_content に対象先ID を入れることで、どの相手が踏んだリンクか特定できる。
    スタッフには**この出力をコピーさせるだけ**にして、手打ちさせない。
    """
    return build_utm_url(
        source=source,
        medium=medium,
        campaign=campaign,
        content=validate_utm_token(contact_id, "対象先ID"),
        base_url=base_url,
    )


def make_campaign(year_month: str, purpose: str) -> str:
    """campaign 文字列を組み立てる。year_month は 'YYYYMM'、purpose は小文字英数_。"""
    ym = str(year_month or "").strip()
    if len(ym) != 6 or not ym.isdigit():
        raise UtmError("year_month は 'YYYYMM'（数字6桁）で指定してください")
    return validate_campaign(f"tc_{ym}_{validate_utm_token(purpose, 'purpose')}")


def parse_utm(url: str) -> dict[str, str]:
    """URL から utm_* を取り出す。流入元の突き合わせ確認に使う。

    未知の値でも例外にせずそのまま返す。判定は呼び出し側が行う。
    """
    parts = urlsplit(str(url or ""))
    found = dict(parse_qsl(parts.query, keep_blank_values=True))
    return {k: found[k] for k in UTM_KEYS if k in found}


if __name__ == "__main__":  # pragma: no cover
    import json
    import sys

    # 使い方: python -m core.catering_growth <source> <medium> <campaign> [content]
    # LP のベースURLは環境変数 CATERING_LP_BASE_URL から読む。
    args = sys.argv[1:]
    if len(args) < 3:
        print("usage: python -m core.catering_growth <source> <medium> <campaign> [content]")
        print(f"       ベースURLは環境変数 {LP_BASE_URL_ENV} から読みます")
        sys.exit(2)
    try:
        url = build_utm_url(args[0], args[1], args[2], args[3] if len(args) > 3 else None)
        print(json.dumps({"ok": True, "utm_url": url}, ensure_ascii=False, indent=2))
    except UtmError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        sys.exit(1)
