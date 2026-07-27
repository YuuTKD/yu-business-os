"""
TREE's Catering 広告費ゼロ集客OS — UTM リンク生成 ＋ ファネル結合キー
------------------------------------------------------------------------
1) UTM: LP へのリンクに「どこから来たか」の目印を付ける。
2) ファネル結合キー: 02_問い合わせ → 03_見積 → 04_受注管理 を共通の
   `問い合わせID` でつなぎ、流入元別の受注売上・粗利を算出可能にする。

正典文書:
  docs/catering-growth/vocabulary.md   §4（UTM 命名規則）§5（ID 形式）
  docs/catering-growth/sheet-schema.md §1（結合キー）§2（追加列）§5（手順）

設計方針:
  - 人に URL を手打ちさせない。対象先ID から決定的に生成してコピーさせる。
    手打ちさせるとタイプミスでその売上が「流入元不明」に落ち、
    どの施策が儲かったのか分からなくなる（仕組みが数字を出さなくなる最頻の失敗）。
  - LP のベースURLはコードに持たない。環境変数 CATERING_LP_BASE_URL から読み、
    無ければ configs.business_registry の catering.booking_url にフォールバックする。
  - 列の追加は**右端のみ**。挿入・並べ替え・改名・削除の機能を実装しない。
    `core/catering_report.py:62-100` が `get_all_values()[2:]` + `r[4]` で
    列の位置を数えて読んでいるため、中間挿入は週次レポートの数字を静かに壊す。

安全設計:
  - シート書込みを伴う関数は `dry_run=True` 既定。dry-run では1セルも書かない。
  - 既に値が入っているセルは絶対に上書きしない（空セルのみ埋める）。
  - 外部送信なし・AI API なし。秘密情報・spreadsheet ID の実値を持たない。
  - 判断ロジックは純関数に分離し、ネットワーク不要でテストできる形にする。
"""

from __future__ import annotations

import os
import re
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from configs.catering_growth_vocab import (
    LP_BASE_URL_ENV,
    UTM_TOKEN_PATTERN,
    col_letter,
    format_inquiry_id,
    is_valid_source_code,
    is_valid_utm_medium,
    source_from_route,
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


# ══════════════════════════════════════════════════════════════════
# ファネル結合キー（sheet-schema.md §1 / §2-2〜2-4）
# ══════════════════════════════════════════════════════════════════

# 追加する列の仕様。**この順で右端に並べる。**
#   header_row: 見出しがある行番号。02〜04 は1行目がタイトルで2行目が見出し
#               （core/catering_setup.py が A1 にタイトル、A2 に見出しを書いている）
FUNNEL_KEY_SPEC: dict[str, dict] = {
    "02_問い合わせ": {
        "header_row": 2,
        "columns": ["問い合わせID", "対象先ID", "流入元コード", "UTM_campaign"],
    },
    "03_見積": {
        "header_row": 2,
        "columns": ["問い合わせID"],
    },
    "04_受注管理": {
        "header_row": 2,
        "columns": ["問い合わせID", "見積番号"],
    },
}

# 既存の位置参照。列を挿入すると壊れる箇所。テストで不変を確認するための記録。
#   core/catering_report.py: 02→r[0] / 03→r[4] / 04→r[4] / 06→r[0],r[3] / 07→r[0],r[7]
PROTECTED_POSITIONS: dict[str, tuple[int, ...]] = {
    "02_問い合わせ": (0,),
    "03_見積":      (4,),
    "04_受注管理":   (4,),
    "06_売上管理":   (0, 3),
    "07_利益管理":   (0, 7),
}


class SchemaError(RuntimeError):
    """シートのスキーマが想定と違うときに投げる。fail-closed で止める。"""


# ── 純関数 ───────────────────────────────────────────────

def trim_trailing_empty(values: list) -> list[str]:
    """行末の空セルを落とす。追加列の挿入位置を決めるために使う。"""
    out = [str(v) if v is not None else "" for v in values]
    while out and out[-1].strip() == "":
        out.pop()
    return out


def plan_missing_columns(existing_header: list, want: list[str]) -> dict:
    """不足している列と、その書き込み先を算出する純関数。

    - 既にある列は追加しない（冪等）
    - 追加位置は必ず右端（既存の列位置を1つも動かさない）
    - 見出しに重複があれば `get_all_records()` が壊れるので例外で止める
    """
    header = trim_trailing_empty(existing_header)

    dupes = [h for h in set(header) if h and header.count(h) > 1]
    if dupes:
        raise SchemaError(
            f"見出しが重複しています: {sorted(dupes)}。"
            "get_all_records() が壊れるため先に手で直してください。"
        )

    missing = [c for c in want if c not in header]
    start_col = len(header) + 1
    return {
        "existing_count": len(header),
        "existing_header": header,
        "missing": missing,
        "start_col": start_col,
        "start_letter": col_letter(start_col) if missing else None,
        "end_letter": col_letter(start_col + len(missing) - 1) if missing else None,
        "final_count": len(header) + len(missing),
    }


def parse_year_month(value: object) -> str | None:
    """日付文字列から 'YYYYMM' を取り出す。取れなければ None（例外にしない）。

    受け付ける形: 2026/06/01, 2026-06-01, 2026/6/1, 2026.06.01
    """
    text = str(value or "").strip()
    m = re.match(r"^(\d{4})[/\-.](\d{1,2})", text)
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if not (1 <= month <= 12):
        return None
    return f"{year:04d}{month:02d}"


def plan_inquiry_backfill(header: list, rows: list[list]) -> dict:
    """既存 `02_問い合わせ` 行への埋め戻し内容を算出する純関数。

    ルール（sheet-schema.md §5）:
      - `問い合わせID` は `inq_<行の問い合わせ日の年月>_<その月の連番3桁>`
      - `流入元コード` は既存 `経路` から機械変換。当たらなければ other
      - **空セルのみ埋める。既に値があるセルは絶対に上書きしない**
      - 日付が読めない行はスキップし、件数を報告する（黙って落とさない）

    rows は見出し行より下のデータ行（値のリストのリスト）。
    戻り値の updates は {row_offset, col, value} の並び。row_offset は rows 内の添字。
    """
    head = trim_trailing_empty(header)
    for required in ("問い合わせID", "流入元コード", "経路", "問い合わせ日"):
        if required not in head:
            raise SchemaError(f"`02_問い合わせ` に列 {required!r} がありません。先に列追加を実行してください。")

    i_id     = head.index("問い合わせID")
    i_source = head.index("流入元コード")
    i_route  = head.index("経路")
    i_date   = head.index("問い合わせ日")

    def cell(row: list, idx: int) -> str:
        return str(row[idx]).strip() if idx < len(row) and row[idx] is not None else ""

    # 既に使われている ID を集めて衝突を避ける
    used_ids = {cell(r, i_id) for r in rows if cell(r, i_id)}
    seq_by_month: dict[str, int] = {}
    for existing in used_ids:
        m = re.match(r"^inq_(\d{6})_(\d{3})$", existing)
        if m:
            ym, n = m.group(1), int(m.group(2))
            seq_by_month[ym] = max(seq_by_month.get(ym, 0), n)

    updates: list[dict] = []
    skipped_no_date: list[int] = []
    id_filled = source_filled = 0

    for offset, row in enumerate(rows):
        if not any(str(c or "").strip() for c in row):
            continue  # 完全な空行は対象外

        # 流入元コード: 空セルのみ、経路から変換して埋める
        if not cell(row, i_source):
            updates.append({
                "row_offset": offset,
                "col": i_source + 1,
                "value": source_from_route(cell(row, i_route)),
            })
            source_filled += 1

        # 問い合わせID: 空セルのみ、日付の年月＋連番で採番
        if not cell(row, i_id):
            ym = parse_year_month(cell(row, i_date))
            if ym is None:
                skipped_no_date.append(offset)
                continue
            seq = seq_by_month.get(ym, 0) + 1
            if seq > 999:
                raise SchemaError(f"{ym} の問い合わせが999件を超えました。ID形式の見直しが必要です。")
            seq_by_month[ym] = seq
            new_id = format_inquiry_id(ym, seq)
            if new_id in used_ids:
                raise SchemaError(f"採番した ID が既存と衝突しました: {new_id}")
            used_ids.add(new_id)
            updates.append({"row_offset": offset, "col": i_id + 1, "value": new_id})
            id_filled += 1

    return {
        "updates": updates,
        "id_filled": id_filled,
        "source_filled": source_filled,
        "skipped_no_date": skipped_no_date,
        "skipped_no_date_count": len(skipped_no_date),
        "data_rows": len(rows),
    }


# ── I/O（dry_run=True 既定）────────────────────────────────

def _open_sheet(spreadsheet_id: str, creds_path: str):
    """gspread は必要になった時点で import する（純関数側に依存を持ち込まない）。"""
    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return gspread.authorize(creds).open_by_key(spreadsheet_id)


def ensure_columns(
    ss,
    sheet_title: str,
    want: list[str],
    header_row: int = 2,
    dry_run: bool = True,
) -> dict:
    """不足している列を**右端にのみ**追加する。冪等。

    dry_run=True（既定）では1セルも書かず、追加予定だけを返す。
    挿入・並べ替え・改名・削除は実装しない（機能が無ければ事故も起きない）。
    """
    try:
        ws = ss.worksheet(sheet_title)
    except Exception as exc:
        return {"ok": False, "sheet": sheet_title, "error": f"シートが見つかりません: {exc}"}

    plan = plan_missing_columns(ws.row_values(header_row), want)
    result = {
        "ok": True,
        "sheet": sheet_title,
        "header_row": header_row,
        "dry_run": dry_run,
        **{k: plan[k] for k in
           ("existing_count", "missing", "start_col", "start_letter", "end_letter", "final_count")},
    }

    if not plan["missing"]:
        result["action"] = "追加なし（既に全列あり）"
        return result

    if dry_run:
        result["action"] = (
            f"{len(plan['missing'])}列を {plan['start_letter']}〜{plan['end_letter']} に追加予定"
        )
        result["note"] = "1セルも書き込んでいません。適用するには dry_run=False で再実行してください。"
        return result

    # 実際の書き込み。シートの列数が足りなければ先に広げる
    if getattr(ws, "col_count", 0) < plan["final_count"]:
        ws.add_cols(plan["final_count"] - ws.col_count)

    rng = f"{plan['start_letter']}{header_row}:{plan['end_letter']}{header_row}"
    ws.update(values=[plan["missing"]], range_name=rng)
    result["action"] = f"{len(plan['missing'])}列を {rng} に追加した"
    return result


def migrate_funnel_keys(spreadsheet_id: str, creds_path: str, dry_run: bool = True) -> dict:
    """`02_問い合わせ` `03_見積` `04_受注管理` に結合キー列を右端追加する。

    これが通ると 流入元 → 問い合わせ → 見積 → 受注 → 粗利 が機械的につながる。
    dry_run=True（既定）では1セルも書かない。
    """
    ss = _open_sheet(spreadsheet_id, creds_path)
    results = []
    for title, spec in FUNNEL_KEY_SPEC.items():
        results.append(ensure_columns(
            ss, title, spec["columns"],
            header_row=spec["header_row"], dry_run=dry_run,
        ))

    failed = [r for r in results if not r.get("ok")]
    return {
        "ok": not failed,
        "dry_run": dry_run,
        "sheets": results,
        "failed": [r["sheet"] for r in failed],
        "note": ("1セルも書き込んでいません。" if dry_run else
                 "適用しました。/catering-weekly で受注率・粗利率が適用前と一致することを確認してください。"),
    }


def backfill_inquiry_ids(spreadsheet_id: str, creds_path: str, dry_run: bool = True) -> dict:
    """既存 `02_問い合わせ` 行に `問い合わせID` と `流入元コード` を埋め戻す。

    **空セルのみ埋める。既に値があるセルは絶対に上書きしない。**
    日付が読めない行はスキップし、件数を返す（黙って落とさない）。
    """
    ss = _open_sheet(spreadsheet_id, creds_path)
    spec = FUNNEL_KEY_SPEC["02_問い合わせ"]
    header_row = spec["header_row"]

    try:
        ws = ss.worksheet("02_問い合わせ")
    except Exception as exc:
        return {"ok": False, "error": f"`02_問い合わせ` が見つかりません: {exc}"}

    header = ws.row_values(header_row)
    rows = ws.get_all_values()[header_row:]  # 見出し行より下

    try:
        plan = plan_inquiry_backfill(header, rows)
    except SchemaError as exc:
        return {"ok": False, "error": str(exc)}

    summary = {
        "ok": True,
        "dry_run": dry_run,
        "data_rows": plan["data_rows"],
        "id_filled": plan["id_filled"],
        "source_filled": plan["source_filled"],
        "skipped_no_date_count": plan["skipped_no_date_count"],
        "cells_to_write": len(plan["updates"]),
    }
    if plan["skipped_no_date_count"]:
        summary["skipped_note"] = (
            f"{plan['skipped_no_date_count']}行は問い合わせ日が読めずID未採番。"
            "日付を入れてから再実行してください。"
        )

    if dry_run or not plan["updates"]:
        summary["note"] = "1セルも書き込んでいません。" if dry_run else "埋める対象がありません。"
        return summary

    # 空セルのみを個別に更新する（範囲一括更新にすると既存値を踏む危険がある）
    cells = []
    for upd in plan["updates"]:
        row_no = header_row + 1 + upd["row_offset"]
        cells.append({
            "range": f"{col_letter(upd['col'])}{row_no}",
            "values": [[upd["value"]]],
        })
    ws.batch_update(cells, value_input_option="RAW")
    summary["note"] = f"{len(cells)}セルを埋めました（空セルのみ）。"
    return summary


if __name__ == "__main__":  # pragma: no cover
    import json
    import sys

    # 使い方:
    #   python -m core.catering_growth utm <source> <medium> <campaign> [content]
    #     LP のベースURLは環境変数 CATERING_LP_BASE_URL から読む
    #   （シート操作は Cloud Run のエンドポイント経由。CLI からは実行しない）
    args = sys.argv[1:]
    if not args or args[0] != "utm" or len(args) < 4:
        print("usage: python -m core.catering_growth utm <source> <medium> <campaign> [content]")
        print(f"       ベースURLは環境変数 {LP_BASE_URL_ENV} から読みます")
        print("       シートへの列追加・埋め戻しは CLI からは実行できません")
        print("       （/catering-funnel-keys?dry_run=1 等のエンドポイント経由）")
        sys.exit(2)
    try:
        url = build_utm_url(args[1], args[2], args[3], args[4] if len(args) > 4 else None)
        print(json.dumps({"ok": True, "utm_url": url}, ensure_ascii=False, indent=2))
    except UtmError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        sys.exit(1)
