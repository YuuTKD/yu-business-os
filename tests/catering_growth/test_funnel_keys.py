"""ファネル結合キーの付与と埋め戻しのテスト。オフラインのみ・実シートに触らない。

正典: docs/catering-growth/sheet-schema.md §1（結合キー）§2-2〜2-4（追加列）§5（手順）
コード: core/catering_growth.py

`core.catering_growth` は gspread を遅延 import（`_open_sheet` の中）しているため、
gspread 未インストール環境でも本テストは全件実行できる。
"""

import os
import re
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core import catering_growth as cg

# 本番 02_問い合わせ の実際の見出し（core/catering_setup.py:108-112 と一致）
HEADER_02 = [
    "問い合わせ日", "企業名", "担当者名", "電話番号", "メールアドレス",
    "問い合わせ内容", "案件詳細", "希望日程", "人数規模", "予算感",
    "対応状況", "次のアクション", "担当スタッフ", "メモ", "経路",
]
HEADER_02_MIGRATED = HEADER_02 + ["問い合わせID", "対象先ID", "流入元コード", "UTM_campaign"]

HEADER_03 = [
    "見積番号", "問い合わせ日", "企業名", "案件名", "見積状況",
    "見積金額", "見積提出日", "有効期限", "サービス種別", "数量/規模",
    "単価", "原価", "粗利", "粗利率", "備考",
]
HEADER_04 = [
    "受注番号", "受注日", "企業名", "案件名", "受注状況",
    "納品日", "サービス種別", "受注金額", "原価", "粗利",
    "入金状況", "入金日", "請求書番号", "担当スタッフ", "備考",
]


# ── テスト用のフェイクシート（書き込みを検出できる形）────────────

class FakeWorksheet:
    def __init__(self, title, values, col_count=15):
        self.title = title
        self._values = [list(r) for r in values]
        self.col_count = col_count
        self.writes = []          # ("update", range, values) / ("add_cols", n) / ("batch_update", …)

    def row_values(self, n):
        return list(self._values[n - 1]) if 0 < n <= len(self._values) else []

    def get_all_values(self):
        return [list(r) for r in self._values]

    def add_cols(self, n):
        self.writes.append(("add_cols", n))
        self.col_count += n

    def update(self, values=None, range_name=None, **kw):
        self.writes.append(("update", range_name, values))

    def batch_update(self, data, **kw):
        self.writes.append(("batch_update", data))


class FakeSpreadsheet:
    def __init__(self, sheets):
        self._sheets = sheets

    def worksheet(self, title):
        if title in self._sheets:
            return self._sheets[title]
        raise KeyError(f"no worksheet {title}")


def sheet_02(rows=None, header=None, col_count=15):
    values = [["02 問い合わせ管理"] + [""] * 14, list(header or HEADER_02)]
    values += [list(r) for r in (rows or [])]
    return FakeWorksheet("02_問い合わせ", values, col_count=col_count)


# ── 純関数: 不足列の算出 ──────────────────────────────────

class PlanMissingColumnsTest(unittest.TestCase):

    def test_01_all_missing_go_to_right_end(self):
        plan = cg.plan_missing_columns(HEADER_02, cg.FUNNEL_KEY_SPEC["02_問い合わせ"]["columns"])
        self.assertEqual(plan["existing_count"], 15)
        self.assertEqual(plan["missing"],
                         ["問い合わせID", "対象先ID", "流入元コード", "UTM_campaign"])
        self.assertEqual(plan["start_col"], 16)
        self.assertEqual(plan["start_letter"], "P")
        self.assertEqual(plan["end_letter"], "S")
        self.assertEqual(plan["final_count"], 19)

    def test_02_idempotent_when_already_present(self):
        plan = cg.plan_missing_columns(HEADER_02_MIGRATED,
                                       cg.FUNNEL_KEY_SPEC["02_問い合わせ"]["columns"])
        self.assertEqual(plan["missing"], [])
        self.assertIsNone(plan["start_letter"])
        self.assertEqual(plan["final_count"], 19)

    def test_03_partial_adds_only_the_gap(self):
        header = HEADER_02 + ["問い合わせID", "対象先ID"]
        plan = cg.plan_missing_columns(header, cg.FUNNEL_KEY_SPEC["02_問い合わせ"]["columns"])
        self.assertEqual(plan["missing"], ["流入元コード", "UTM_campaign"])
        self.assertEqual(plan["start_col"], 18)
        self.assertEqual(plan["start_letter"], "R")

    def test_04_trailing_empties_are_ignored(self):
        """06_売上管理 のように末尾に空見出しがあっても位置を誤らない。"""
        plan = cg.plan_missing_columns(HEADER_02 + ["", "", ""], ["問い合わせID"])
        self.assertEqual(plan["existing_count"], 15)
        self.assertEqual(plan["start_letter"], "P")

    def test_05_never_reorders_existing(self):
        plan = cg.plan_missing_columns(HEADER_03, ["問い合わせID"])
        self.assertEqual(plan["existing_header"], HEADER_03, "既存見出しを1つも動かさない")

    def test_06_duplicate_header_is_fatal(self):
        """見出しが重複していると get_all_records() が壊れるので止める。"""
        with self.assertRaises(cg.SchemaError):
            cg.plan_missing_columns(HEADER_02 + ["企業名"], ["問い合わせID"])

    def test_07_all_three_sheets_start_at_column_p(self):
        """02/03/04 はいずれも15列なので追加開始は P 列。"""
        for header in (HEADER_02, HEADER_03, HEADER_04):
            plan = cg.plan_missing_columns(header, ["問い合わせID"])
            self.assertEqual(plan["start_letter"], "P")


class SpecTest(unittest.TestCase):

    def test_08_spec_matches_doc(self):
        spec = cg.FUNNEL_KEY_SPEC
        self.assertEqual(set(spec), {"02_問い合わせ", "03_見積", "04_受注管理"})
        self.assertEqual(spec["02_問い合わせ"]["columns"],
                         ["問い合わせID", "対象先ID", "流入元コード", "UTM_campaign"])
        self.assertEqual(spec["03_見積"]["columns"], ["問い合わせID"])
        self.assertEqual(spec["04_受注管理"]["columns"], ["問い合わせID", "見積番号"])

    def test_09_header_row_is_2_for_all(self):
        """02〜04 は1行目がタイトル、2行目が見出し（catering_setup.py の作り）。"""
        for spec in cg.FUNNEL_KEY_SPEC.values():
            self.assertEqual(spec["header_row"], 2)

    def test_10_added_columns_are_beyond_protected_positions(self):
        """既存の位置参照（r[0] / r[4] / r[7]）より右に追加していること。"""
        for title, positions in cg.PROTECTED_POSITIONS.items():
            spec = cg.FUNNEL_KEY_SPEC.get(title)
            if not spec:
                continue
            plan = cg.plan_missing_columns(
                {"02_問い合わせ": HEADER_02, "03_見積": HEADER_03,
                 "04_受注管理": HEADER_04}[title],
                spec["columns"])
            for idx in positions:
                self.assertLess(idx, plan["start_col"] - 1,
                                f"{title}: r[{idx}] より左に追加してはいけない")


# ── ensure_columns（dry_run / apply）──────────────────────

class EnsureColumnsTest(unittest.TestCase):

    def test_11_dry_run_writes_nothing(self):
        ws = sheet_02()
        ss = FakeSpreadsheet({"02_問い合わせ": ws})
        got = cg.ensure_columns(ss, "02_問い合わせ",
                                cg.FUNNEL_KEY_SPEC["02_問い合わせ"]["columns"],
                                header_row=2, dry_run=True)
        self.assertTrue(got["ok"])
        self.assertTrue(got["dry_run"])
        self.assertEqual(ws.writes, [], "1セルも書き込まないこと")
        self.assertEqual(got["missing"],
                         ["問い合わせID", "対象先ID", "流入元コード", "UTM_campaign"])
        self.assertIn("P", got["action"])

    def test_12_dry_run_is_default(self):
        ws = sheet_02()
        ss = FakeSpreadsheet({"02_問い合わせ": ws})
        cg.ensure_columns(ss, "02_問い合わせ", ["問い合わせID"], header_row=2)
        self.assertEqual(ws.writes, [], "dry_run の既定は True")

    def test_13_apply_writes_to_right_end_only(self):
        ws = sheet_02()
        ss = FakeSpreadsheet({"02_問い合わせ": ws})
        cg.ensure_columns(ss, "02_問い合わせ",
                          cg.FUNNEL_KEY_SPEC["02_問い合わせ"]["columns"],
                          header_row=2, dry_run=False)
        kinds = [w[0] for w in ws.writes]
        self.assertIn("add_cols", kinds, "列数が足りないので先に広げること")
        update = next(w for w in ws.writes if w[0] == "update")
        self.assertEqual(update[1], "P2:S2", "見出し行の P〜S にのみ書く")
        self.assertEqual(update[2], [["問い合わせID", "対象先ID", "流入元コード", "UTM_campaign"]])

    def test_14_apply_is_idempotent(self):
        ws = sheet_02(header=HEADER_02_MIGRATED, col_count=19)
        ss = FakeSpreadsheet({"02_問い合わせ": ws})
        got = cg.ensure_columns(ss, "02_問い合わせ",
                                cg.FUNNEL_KEY_SPEC["02_問い合わせ"]["columns"],
                                header_row=2, dry_run=False)
        self.assertEqual(ws.writes, [], "2回目は書き込みゼロ")
        self.assertEqual(got["missing"], [])
        self.assertIn("追加なし", got["action"])

    def test_15_no_add_cols_when_room_exists(self):
        ws = sheet_02(col_count=30)
        ss = FakeSpreadsheet({"02_問い合わせ": ws})
        cg.ensure_columns(ss, "02_問い合わせ", ["問い合わせID"], header_row=2, dry_run=False)
        self.assertNotIn("add_cols", [w[0] for w in ws.writes])

    def test_16_missing_sheet_is_reported_not_raised(self):
        ss = FakeSpreadsheet({})
        got = cg.ensure_columns(ss, "02_問い合わせ", ["問い合わせID"], dry_run=True)
        self.assertFalse(got["ok"])
        self.assertIn("見つかりません", got["error"])

    def test_17_has_no_insert_or_delete_capability(self):
        """挿入・改名・削除の機能を実装していないこと（機能が無ければ事故も起きない）。"""
        path = os.path.join(_REPO_ROOT, "core", "catering_growth.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        for forbidden in ("insert_cols", "insert_col", "delete_columns", "delete_col",
                          "update_title", "delete_rows", "clear("):
            self.assertNotIn(forbidden, src, f"{forbidden} を実装してはいけない")


# ── 純関数: 埋め戻し ─────────────────────────────────────

class ParseYearMonthTest(unittest.TestCase):

    def test_18_accepts_common_formats(self):
        for text in ("2026/06/01", "2026-06-01", "2026/6/1", "2026.06.01",
                     "2026/06/01 10:00"):
            self.assertEqual(cg.parse_year_month(text), "202606", text)

    def test_19_returns_none_for_garbage(self):
        for bad in ("", None, "来月", "6/1", "20260601", "abc"):
            self.assertIsNone(cg.parse_year_month(bad), f"{bad!r}")

    def test_20_rejects_impossible_month(self):
        for bad in ("2026/13/01", "2026/00/01"):
            self.assertIsNone(cg.parse_year_month(bad))


class PlanBackfillTest(unittest.TestCase):

    def _rows(self):
        # 本番のサンプル行に近い形（架空データ）
        return [
            ["2026/06/01", "株式会社サンプル商事", "", "", "", "会議用弁当",
             "", "", "20名", "", "", "", "", "", "WEB", "", "", "", ""],
            ["2026/06/15", "サンプル合同会社", "", "", "", "オードブル",
             "", "", "30名", "", "", "", "", "", "紹介", "", "", "", ""],
            ["2026/07/02", "サンプル工業", "", "", "", "ケータリング",
             "", "", "50名", "", "", "", "", "", "インスタ", "", "", "", ""],
        ]

    def test_21_assigns_ids_by_month(self):
        plan = cg.plan_inquiry_backfill(HEADER_02_MIGRATED, self._rows())
        ids = [u["value"] for u in plan["updates"] if u["col"] == 16]
        self.assertEqual(ids, ["inq_202606_001", "inq_202606_002", "inq_202607_001"])
        self.assertEqual(plan["id_filled"], 3)

    def test_22_converts_route_to_source_code(self):
        plan = cg.plan_inquiry_backfill(HEADER_02_MIGRATED, self._rows())
        sources = [u["value"] for u in plan["updates"] if u["col"] == 18]
        self.assertEqual(sources, ["organic_search", "referral", "instagram"])
        self.assertEqual(plan["source_filled"], 3)

    def test_23_never_overwrites_existing_values(self):
        rows = self._rows()
        rows[0][15] = "inq_202606_099"   # 問い合わせID が既に入っている
        rows[0][17] = "line"             # 流入元コードも入っている
        plan = cg.plan_inquiry_backfill(HEADER_02_MIGRATED, rows)
        touched = {(u["row_offset"], u["col"]) for u in plan["updates"]}
        self.assertNotIn((0, 16), touched, "既存の問い合わせIDを上書きしない")
        self.assertNotIn((0, 18), touched, "既存の流入元コードを上書きしない")
        self.assertEqual(plan["id_filled"], 2)
        self.assertEqual(plan["source_filled"], 2)

    def test_24_avoids_collision_with_existing_ids(self):
        """既に inq_202606_001 がある月は 002 から採番すること。"""
        rows = self._rows()
        rows[0][15] = "inq_202606_001"
        plan = cg.plan_inquiry_backfill(HEADER_02_MIGRATED, rows)
        new_ids = [u["value"] for u in plan["updates"] if u["col"] == 16]
        self.assertEqual(new_ids, ["inq_202606_002", "inq_202607_001"])
        self.assertNotIn("inq_202606_001", new_ids)

    def test_25_skips_unparseable_date_and_reports(self):
        """日付が読めない行は黙って落とさず件数を返す。"""
        rows = self._rows()
        rows[1][0] = "来月"
        plan = cg.plan_inquiry_backfill(HEADER_02_MIGRATED, rows)
        self.assertEqual(plan["skipped_no_date_count"], 1)
        self.assertEqual(plan["skipped_no_date"], [1])
        self.assertEqual(plan["id_filled"], 2)
        # 日付が読めなくても流入元コードは埋める（経路は独立して使える）
        self.assertEqual(plan["source_filled"], 3)

    def test_26_ignores_fully_empty_rows(self):
        rows = self._rows() + [["", "", ""], [""] * 19]
        plan = cg.plan_inquiry_backfill(HEADER_02_MIGRATED, rows)
        self.assertEqual(plan["id_filled"], 3)
        self.assertEqual(plan["data_rows"], 5)

    def test_27_empty_route_becomes_other(self):
        rows = self._rows()
        rows[0][14] = ""
        plan = cg.plan_inquiry_backfill(HEADER_02_MIGRATED, rows)
        first_source = next(u["value"] for u in plan["updates"]
                            if u["col"] == 18 and u["row_offset"] == 0)
        self.assertEqual(first_source, "other", "空欄にせず other を入れる")

    def test_28_requires_migration_first(self):
        """列追加前の見出しで呼ぶと fail-closed で止まること。"""
        with self.assertRaises(cg.SchemaError) as ctx:
            cg.plan_inquiry_backfill(HEADER_02, self._rows())
        self.assertIn("問い合わせID", str(ctx.exception))

    def test_29_all_generated_ids_match_documented_pattern(self):
        from configs.catering_growth_vocab import ID_PATTERN_INQUIRY
        plan = cg.plan_inquiry_backfill(HEADER_02_MIGRATED, self._rows())
        for upd in plan["updates"]:
            if upd["col"] == 16:
                self.assertRegex(upd["value"], ID_PATTERN_INQUIRY)

    def test_30_all_generated_sources_are_valid(self):
        from configs.catering_growth_vocab import is_valid_source_code
        plan = cg.plan_inquiry_backfill(HEADER_02_MIGRATED, self._rows())
        for upd in plan["updates"]:
            if upd["col"] == 18:
                self.assertTrue(is_valid_source_code(upd["value"]), upd["value"])

    def test_31_no_updates_when_already_complete(self):
        """全部埋まっていれば書き込み対象ゼロ（冪等）。"""
        rows = self._rows()
        for i, (rid, src) in enumerate([("inq_202606_001", "organic_search"),
                                        ("inq_202606_002", "referral"),
                                        ("inq_202607_001", "instagram")]):
            rows[i][15] = rid
            rows[i][17] = src
        plan = cg.plan_inquiry_backfill(HEADER_02_MIGRATED, rows)
        self.assertEqual(plan["updates"], [])
        self.assertEqual(plan["id_filled"], 0)
        self.assertEqual(plan["source_filled"], 0)


class TrimTest(unittest.TestCase):

    def test_32_trims_only_trailing(self):
        self.assertEqual(cg.trim_trailing_empty(["a", "", "b", "", ""]), ["a", "", "b"])
        self.assertEqual(cg.trim_trailing_empty(["", ""]), [])
        self.assertEqual(cg.trim_trailing_empty([]), [])

    def test_33_handles_none_and_whitespace(self):
        self.assertEqual(cg.trim_trailing_empty(["a", None, "  "]), ["a"])


class SafetyTest(unittest.TestCase):
    """外部送信・課金・秘密情報を持ち込まないこと。"""

    def _src(self):
        path = os.path.join(_REPO_ROOT, "core", "catering_growth.py")
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_34_no_external_send(self):
        src = self._src()
        for bad in ("requests", "urllib.request", "httpx", "api.line.me",
                    "broadcast", "smtplib", "openai", "gcloud"):
            self.assertNotIn(bad, src, f"{bad} を含めてはいけない")

    def test_35_gspread_is_lazily_imported_only(self):
        """トップレベルで gspread を import しないこと（純関数をオフラインでテストするため）。"""
        src = self._src()
        self.assertIsNone(re.search(r"^import gspread", src, re.MULTILINE))
        self.assertIsNone(re.search(r"^from gspread", src, re.MULTILINE))
        self.assertIn("import gspread", src, "_open_sheet の中で遅延 import する")

    def test_36_no_secret_or_id_or_pii(self):
        src = self._src()
        for pattern in (r"sk-[A-Za-z0-9]{20,}", r"ghp_[A-Za-z0-9]{20,}",
                        r"AIza[0-9A-Za-z_\-]{20,}", r"-----BEGIN",
                        r"1[A-Za-z0-9_\-]{40,}",
                        r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}",
                        r"0\d{1,3}-\d{2,4}-\d{4}"):
            self.assertIsNone(re.search(pattern, src), f"検出: {pattern}")

    def test_37_write_functions_default_to_dry_run(self):
        """シートに書く可能性のある公開関数はすべて dry_run: bool = True 既定。"""
        src = self._src()
        for fn in ("ensure_columns", "migrate_funnel_keys", "backfill_inquiry_ids"):
            self.assertIsNotNone(
                re.search(rf"def {fn}\([^)]*dry_run: bool = True", src, re.DOTALL),
                f"{fn} の dry_run 既定が True でない")


if __name__ == "__main__":
    unittest.main()
