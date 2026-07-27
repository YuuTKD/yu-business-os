"""CSV 一括投入のテスト。オフラインのみ・実シートに触らない・架空データのみ。

正典: docs/catering-growth/sheet-schema.md §2-1 / operations-sop.md §4
コード: core/catering_growth.py

テストデータは架空社名と `090-0000-0000` 形式のダミーのみを使う
（docs/catering-growth/sheet-schema.md §6 の方針）。
"""

import os
import re
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from configs import catering_growth_vocab as v
from core import catering_growth as cg

HEADER = ",".join(cg.CSV_COLUMNS)


def csv_of(*rows: str) -> str:
    return "\n".join([HEADER, *rows]) + "\n"


# CATERING_SALES_TARGETS の33列（core/catering_sales.py の正本を写したもの）。
# core.catering_sales は gspread を import するため、テストでは直接参照しない。
SHEET_HEADER_33 = [
    "登録日時", "営業先名", "カテゴリ", "住所", "電話", "Instagram",
    "Webサイト", "担当者名", "想定ニーズ", "推定単価", "優先度",
    "営業文", "初回アプローチ日", "最終接触日", "返信状況",
    "商談状況", "見積状況", "成約状況", "次回フォロー日",
    "実売上", "メモ", "Obsidian Path",
    "対象先ID", "種別", "流入元コード", "メール", "エリア", "接触元",
    "見込み確度", "ステータス", "使用テンプレートID", "UTM_URL", "紹介者",
]


def row(name="株式会社サンプル商事", ctype="partner_space", source="",
        category="レンタルスペース", contact="", tel="", mail="", ig="",
        web="", area="那覇", origin="", priority="A", conf="70",
        needs="懇親会", unit="200000", referrer="", memo=""):
    return ",".join([name, ctype, source, category, contact, tel, mail, ig,
                     web, area, origin, priority, conf, needs, unit, referrer, memo])


class TemplateTest(unittest.TestCase):

    def test_01_csv_columns_match_template_file(self):
        """コードの CSV_COLUMNS と配布用テンプレCSVのヘッダが一致すること。"""
        path = os.path.join(_REPO_ROOT, "docs", "catering-growth", "contacts_template.csv")
        with open(path, encoding="utf-8") as f:
            first = f.readline().strip()
        self.assertEqual(first.split(","), list(cg.CSV_COLUMNS))

    def test_02_template_has_no_data_rows(self):
        """テンプレCSVにデータ行を入れないこと（個人情報の混入を防ぐ）。"""
        path = os.path.join(_REPO_ROOT, "docs", "catering-growth", "contacts_template.csv")
        with open(path, encoding="utf-8") as f:
            body = [ln for ln in f.read().splitlines()[1:] if ln.strip()]
        self.assertEqual(body, [], "ヘッダのみにすること")

    def test_03_gitignore_excludes_customer_csv(self):
        """実顧客CSVがコミットされない設定になっていること。"""
        with open(os.path.join(_REPO_ROOT, ".gitignore"), encoding="utf-8") as f:
            ignore = f.read()
        self.assertIn("data/catering_growth/", ignore)


class HappyPathTest(unittest.TestCase):

    def test_04_accepts_valid_row(self):
        got = cg.parse_contacts_csv(csv_of(row()))
        self.assertTrue(got["ok"])
        self.assertEqual(got["accepted_count"], 1)
        self.assertEqual(got["rejected"], [])
        rec = got["accepted"][0]
        self.assertEqual(rec["営業先名"], "株式会社サンプル商事", "対象先名 → 営業先名 に写す")
        self.assertEqual(rec["種別"], "partner_space")
        self.assertEqual(rec["優先度"], "A")
        self.assertEqual(rec["見込み確度"], 70)
        self.assertEqual(rec["推定単価"], 200000)
        self.assertEqual(rec["対象先ID"], "tc_0001")

    def test_05_handles_100_rows(self):
        """仕様書の完了条件『100件をCSVで投入可能』。"""
        rows = [row(name=f"サンプル{i:03d}株式会社", tel=f"090-0000-{i:04d}")
                for i in range(1, 101)]
        got = cg.parse_contacts_csv(csv_of(*rows))
        self.assertEqual(got["accepted_count"], 100)
        self.assertEqual(got["rejected_count"], 0)
        self.assertEqual(got["duplicate_count"], 0)
        self.assertEqual(got["accepted"][0]["対象先ID"], "tc_0001")
        self.assertEqual(got["accepted"][-1]["対象先ID"], "tc_0100")

    def test_06_ids_are_sequential_and_unique(self):
        rows = [row(name=f"サンプル{i}株式会社") for i in range(1, 21)]
        got = cg.parse_contacts_csv(csv_of(*rows))
        ids = [r["対象先ID"] for r in got["accepted"]]
        self.assertEqual(len(ids), len(set(ids)))
        for i in ids:
            self.assertRegex(i, v.ID_PATTERN_CONTACT)

    def test_07_start_seq_continues_numbering(self):
        got = cg.parse_contacts_csv(csv_of(row()), start_seq=43)
        self.assertEqual(got["accepted"][0]["対象先ID"], "tc_0043")
        self.assertEqual(got["next_seq"], 44)

    def test_08_ignores_blank_lines(self):
        text = csv_of(row(), ",,,,,,,,,,,,,,,,", row(name="サンプル二号株式会社"))
        got = cg.parse_contacts_csv(text)
        self.assertEqual(got["accepted_count"], 2)
        self.assertEqual(got["rejected_count"], 0)


class DefaultingTest(unittest.TestCase):

    def test_09_type_inferred_from_category_when_blank(self):
        got = cg.parse_contacts_csv(csv_of(row(ctype="", category="ホテル")))
        self.assertEqual(got["accepted"][0]["種別"], "hotel_villa")

    def test_10_source_falls_back_and_is_never_blank(self):
        """流入元コードは空欄禁止（空欄は集計を壊す）。"""
        got = cg.parse_contacts_csv(csv_of(row(source="", ctype="partner_bar")))
        rec = got["accepted"][0]
        self.assertEqual(rec["流入元コード"], "partner_bar")
        self.assertTrue(v.is_valid_source_code(rec["流入元コード"]))

    def test_11_source_becomes_other_when_type_is_not_a_source(self):
        got = cg.parse_contacts_csv(csv_of(row(source="", ctype="hotel_villa",
                                               category="ホテル")))
        self.assertEqual(got["accepted"][0]["流入元コード"], "other",
                         "hotel_villa は流入元コードに無いので other")

    def test_12_priority_defaults_to_b(self):
        got = cg.parse_contacts_csv(csv_of(row(priority="")))
        self.assertEqual(got["accepted"][0]["優先度"], v.PRIORITY_DEFAULT)

    def test_13_priority_is_case_insensitive(self):
        got = cg.parse_contacts_csv(csv_of(row(priority="a")))
        self.assertEqual(got["accepted"][0]["優先度"], "A")

    def test_14_status_reflects_contactability(self):
        with_tel = cg.parse_contacts_csv(csv_of(row(tel="090-0000-0001")))
        self.assertEqual(with_tel["accepted"][0]["ステータス"], "READY_TO_CONTACT")
        without = cg.parse_contacts_csv(csv_of(row(tel="", mail="", ig="")))
        self.assertEqual(without["accepted"][0]["ステータス"], "NEW")

    def test_15_all_defaults_are_in_vocabulary(self):
        got = cg.parse_contacts_csv(csv_of(row(ctype="", source="", priority="")))
        rec = got["accepted"][0]
        self.assertTrue(v.is_valid_contact_type(rec["種別"]))
        self.assertTrue(v.is_valid_source_code(rec["流入元コード"]))
        self.assertTrue(v.is_valid_priority(rec["優先度"]))
        self.assertTrue(v.is_valid_status(rec["ステータス"]))


class RejectTest(unittest.TestCase):
    """1行の不備で全体を落とさず、行ごとに理由を返すこと。"""

    def test_16_missing_name_is_rejected_not_fatal(self):
        text = csv_of(row(), row(name=""), row(name="サンプル三号株式会社"))
        got = cg.parse_contacts_csv(text)
        self.assertTrue(got["ok"], "1行の不備で全体を落とさない")
        self.assertEqual(got["accepted_count"], 2)
        self.assertEqual(got["rejected_count"], 1)
        self.assertEqual(got["rejected"][0]["line"], 3)
        self.assertIn("対象先名", got["rejected"][0]["reason"])

    def test_17_invalid_source_is_rejected_not_silently_othered(self):
        """不正な流入元コードを黙って other にしない（入力ミスに気付けなくなる）。"""
        got = cg.parse_contacts_csv(csv_of(row(source="インスタ")))
        self.assertEqual(got["accepted_count"], 0)
        self.assertEqual(got["rejected_count"], 1)
        self.assertIn("流入元コード", got["rejected"][0]["reason"])

    def test_18_invalid_type_is_rejected(self):
        got = cg.parse_contacts_csv(csv_of(row(ctype="レンタルスペース")))
        self.assertEqual(got["rejected_count"], 1)
        self.assertIn("種別", got["rejected"][0]["reason"])

    def test_19_invalid_priority_is_rejected(self):
        for bad in ("S", "D", "1", "高"):
            got = cg.parse_contacts_csv(csv_of(row(priority=bad)))
            self.assertEqual(got["rejected_count"], 1, f"優先度={bad!r}")
            self.assertIn("優先度", got["rejected"][0]["reason"])

    def test_20_out_of_range_confidence_is_rejected(self):
        for bad in ("101", "-1", "あ", "70%%"):
            got = cg.parse_contacts_csv(csv_of(row(conf=bad)))
            self.assertEqual(got["rejected_count"], 1, f"見込み確度={bad!r}")

    def test_21_confidence_boundaries_are_accepted(self):
        for ok in ("0", "100", "50"):
            got = cg.parse_contacts_csv(csv_of(row(conf=ok)))
            self.assertEqual(got["accepted_count"], 1, f"見込み確度={ok!r}")

    def test_22_unparseable_price_is_rejected(self):
        got = cg.parse_contacts_csv(csv_of(row(unit="応相談")))
        self.assertEqual(got["rejected_count"], 1)
        self.assertIn("推定単価", got["rejected"][0]["reason"])

    def test_23_price_accepts_formatted_numbers(self):
        """桁区切りカンマは引用符で囲まれている前提（Sheets/Excel の CSV 出力と同じ）。"""
        for text, expected in (('"200,000"', 200000), ("¥200000", 200000),
                               ("200000円", 200000), ("200000", 200000)):
            got = cg.parse_contacts_csv(csv_of(row(unit=text)))
            self.assertEqual(got["accepted_count"], 1, text)
            self.assertEqual(got["accepted"][0]["推定単価"], expected, text)

    def test_23b_unquoted_comma_is_rejected_not_silently_shifted(self):
        """引用符なしのカンマで列が割れた行は reject する。

        黙って取り込むと以降の列が全部ずれて**静かに壊れる**（最悪の壊れ方）。
        """
        got = cg.parse_contacts_csv(csv_of(row(unit="200,000")))
        self.assertEqual(got["accepted_count"], 0)
        self.assertEqual(got["rejected_count"], 1)
        self.assertIn("列数", got["rejected"][0]["reason"])
        self.assertIn("引用符", got["rejected"][0]["reason"])

    def test_24_multiple_errors_are_all_reported(self):
        got = cg.parse_contacts_csv(csv_of(row(source="ダメ", priority="Z", conf="999")))
        reason = got["rejected"][0]["reason"]
        for word in ("流入元コード", "優先度", "見込み確度"):
            self.assertIn(word, reason, "全部の理由を返すこと")

    def test_25_rejected_rows_keep_line_numbers(self):
        text = csv_of(row(), row(name=""), row(), row(priority="Z"))
        got = cg.parse_contacts_csv(text)
        self.assertEqual([r["line"] for r in got["rejected"]], [3, 5])


class DuplicateTest(unittest.TestCase):

    def test_26_duplicate_phone_within_csv(self):
        text = csv_of(row(name="サンプルA株式会社", tel="090-0000-0001"),
                      row(name="サンプルB株式会社", tel="090-0000-0001"))
        got = cg.parse_contacts_csv(text)
        self.assertEqual(got["accepted_count"], 1)
        self.assertEqual(got["duplicate_count"], 1)
        self.assertIn("電話", got["duplicates"][0]["reason"])

    def test_27_duplicate_email_and_instagram(self):
        for field, val in (("mail", "a@example.test"), ("ig", "@sample_shop")):
            text = csv_of(row(name="サンプルA株式会社", **{field: val}),
                          row(name="サンプルB株式会社", **{field: val}))
            got = cg.parse_contacts_csv(text)
            self.assertEqual(got["duplicate_count"], 1, field)

    def test_28_duplicate_name(self):
        text = csv_of(row(name="サンプル同名株式会社"), row(name="サンプル同名株式会社"))
        got = cg.parse_contacts_csv(text)
        self.assertEqual(got["accepted_count"], 1)
        self.assertEqual(got["duplicate_count"], 1)

    def test_29_duplicate_against_existing_sheet_rows(self):
        existing = [{"営業先名": "既存株式会社", "電話": "090-0000-9999",
                     "メール": "", "Instagram": "", "対象先ID": "tc_0007"}]
        text = csv_of(row(name="別名株式会社", tel="090-0000-9999"),
                      row(name="既存株式会社"),
                      row(name="新規株式会社", tel="090-0000-0002"))
        got = cg.parse_contacts_csv(text, existing=existing)
        self.assertEqual(got["accepted_count"], 1)
        self.assertEqual(got["duplicate_count"], 2)
        for d in got["duplicates"]:
            self.assertIn("既存シート", d["reason"])

    def test_30_case_insensitive_duplicate(self):
        text = csv_of(row(name="サンプルA株式会社", mail="A@Example.Test"),
                      row(name="サンプルB株式会社", mail="a@example.test"))
        got = cg.parse_contacts_csv(text)
        self.assertEqual(got["duplicate_count"], 1)

    def test_31_blank_contact_fields_do_not_collide(self):
        """電話・メールが両方空の行が複数あっても重複扱いしない。"""
        text = csv_of(row(name="サンプルA株式会社", tel="", mail="", ig=""),
                      row(name="サンプルB株式会社", tel="", mail="", ig=""))
        got = cg.parse_contacts_csv(text)
        self.assertEqual(got["accepted_count"], 2)
        self.assertEqual(got["duplicate_count"], 0)


class HeaderTest(unittest.TestCase):

    def test_32_empty_csv_is_reported(self):
        got = cg.parse_contacts_csv("")
        self.assertFalse(got["ok"])
        self.assertIn("空", got["error"])

    def test_33_missing_required_column_is_fatal(self):
        got = cg.parse_contacts_csv("種別,カテゴリ\npartner_bar,BAR\n")
        self.assertFalse(got["ok"])
        self.assertIn("対象先名", got["error"])

    def test_34_unknown_columns_are_reported_not_fatal(self):
        text = "対象先名,謎の列\n株式会社サンプル商事,x\n"
        got = cg.parse_contacts_csv(text)
        self.assertTrue(got["ok"])
        self.assertEqual(got["unknown_columns"], ["謎の列"])
        self.assertEqual(got["accepted_count"], 1)

    def test_35_whitespace_in_header_and_values_is_trimmed(self):
        text = " 対象先名 , 種別 \n  株式会社サンプル商事  , partner_bar \n"
        got = cg.parse_contacts_csv(text)
        self.assertEqual(got["accepted_count"], 1)
        self.assertEqual(got["accepted"][0]["営業先名"], "株式会社サンプル商事")
        self.assertEqual(got["accepted"][0]["種別"], "partner_bar")


class NextSeqTest(unittest.TestCase):

    def test_36_continues_from_max_existing_id(self):
        existing = [{"対象先ID": "tc_0003"}, {"対象先ID": "tc_0041"}, {"対象先ID": ""}]
        self.assertEqual(cg._next_contact_seq(existing), 42)

    def test_37_starts_at_one_when_empty(self):
        self.assertEqual(cg._next_contact_seq([]), 1)
        self.assertEqual(cg._next_contact_seq([{"対象先ID": "壊れた値"}]), 1)

    def test_38_does_not_reuse_gaps(self):
        """欠番は再利用しない（過去の売上との紐付けが切れるため）。"""
        existing = [{"対象先ID": "tc_0001"}, {"対象先ID": "tc_0005"}]
        self.assertEqual(cg._next_contact_seq(existing), 6)


class ImportContactsTest(unittest.TestCase):
    """import_contacts の dry_run が1セルも書かないこと。"""

    class _FakeWs:
        def __init__(self, header, rows):
            self._header = list(header)
            self._rows = [list(r) for r in rows]
            self.writes = []

        def row_values(self, n):
            return list(self._header) if n == 1 else []

        def get_all_values(self):
            return [list(self._header)] + self._rows

        def get_all_records(self):
            return [dict(zip(self._header, r)) for r in self._rows]

        def append_rows(self, rows, **kw):
            self.writes.append(("append_rows", rows))

    class _FakeSs:
        def __init__(self, ws):
            self._ws = ws

        def worksheet(self, title):
            if title == "CATERING_SALES_TARGETS":
                return self._ws
            raise KeyError(title)

    def _run(self, csv_text, dry_run, existing_rows=()):
        ws = self._FakeWs(SHEET_HEADER_33, existing_rows)
        ss = self._FakeSs(ws)
        orig = cg._open_sheet
        try:
            cg._open_sheet = lambda sid, cp: ss
            result = cg.import_contacts("FAKE_KEY", "/nonexistent/creds.json",
                                        csv_text, dry_run=dry_run)
        finally:
            cg._open_sheet = orig
        return result, ws

    def test_39_dry_run_writes_nothing(self):
        result, ws = self._run(csv_of(row(), row(name="サンプル二号株式会社")), dry_run=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(ws.writes, [], "1セルも書き込まないこと")
        self.assertEqual(result["accepted_count"], 2)
        self.assertEqual(result["start_contact_id"], "tc_0001")

    def test_40_dry_run_is_default(self):
        ws = self._FakeWs(SHEET_HEADER_33, [])
        ss = self._FakeSs(ws)
        orig = cg._open_sheet
        try:
            cg._open_sheet = lambda sid, cp: ss
            cg.import_contacts("FAKE_KEY", "/nonexistent/creds.json", csv_of(row()))
        finally:
            cg._open_sheet = orig
        self.assertEqual(ws.writes, [], "dry_run の既定は True")

    def test_41_apply_appends_only(self):
        result, ws = self._run(csv_of(row()), dry_run=False)
        self.assertEqual([w[0] for w in ws.writes], ["append_rows"],
                         "既存行を書き換えず末尾に追加するのみ")
        appended = ws.writes[0][1]
        self.assertEqual(len(appended[0]), 33, "33列ぶんで揃うこと")

    def test_42_apply_reports_rejects_too(self):
        result, _ = self._run(csv_of(row(), row(priority="Z")), dry_run=False)
        self.assertEqual(result["accepted_count"], 1)
        self.assertEqual(result["rejected_count"], 1)
        self.assertIn("優先度", result["rejected"][0]["reason"])

    def test_43_no_write_when_everything_rejected(self):
        result, ws = self._run(csv_of(row(priority="Z")), dry_run=False)
        self.assertEqual(ws.writes, [])
        self.assertEqual(result["accepted_count"], 0)
        self.assertIn("取込対象がありません", result["note"])

    def test_44_missing_sheet_is_reported(self):
        class _EmptySs:
            def worksheet(self, title):
                raise KeyError(title)
        orig = cg._open_sheet
        try:
            cg._open_sheet = lambda sid, cp: _EmptySs()
            result = cg.import_contacts("K", "/x", csv_of(row()), dry_run=True)
        finally:
            cg._open_sheet = orig
        self.assertFalse(result["ok"])
        self.assertIn("catering-sales-setup", result["error"])

    def test_45_continues_numbering_from_existing_rows(self):
        header = SHEET_HEADER_33
        existing = [["" for _ in header]]
        existing[0][header.index("対象先ID")] = "tc_0009"
        existing[0][header.index("営業先名")] = "既存株式会社"
        result, _ = self._run(csv_of(row(name="新規株式会社")), dry_run=True,
                              existing_rows=existing)
        self.assertEqual(result["start_contact_id"], "tc_0010")
        self.assertEqual(result["existing_rows"], 1)


class SafetyTest(unittest.TestCase):

    def test_46_no_pii_in_this_test_file(self):
        """テストデータは架空社名とダミー番号のみ。"""
        with open(os.path.abspath(__file__), encoding="utf-8") as f:
            src = f.read()
        # 実在しそうな電話番号（090-0000-xxxx 以外）を含めない
        for m in re.findall(r"0\d{1,3}-\d{4}-\d{4}", src):
            self.assertTrue(m.startswith("090-0000-"), f"ダミー以外の電話番号: {m}")
        # メールは example.test ドメインのみ
        for m in re.findall(r"[\w.+-]+@[\w.-]+", src):
            self.assertTrue(m.lower().endswith("example.test"),
                            f"example.test 以外のメール: {m}")

    def test_47_parse_is_pure(self):
        """parse_contacts_csv がネットワーク・ファイルI/Oを行わないこと。"""
        src_path = os.path.join(_REPO_ROOT, "core", "catering_growth.py")
        with open(src_path, encoding="utf-8") as f:
            src = f.read()
        body = src[src.index("def parse_contacts_csv"):src.index("def import_contacts")]
        for bad in ("open(", "requests", "gspread", "_open_sheet", "os.getenv"):
            self.assertNotIn(bad, body, f"{bad} を純関数に持ち込まない")

    def test_48_import_defaults_to_dry_run(self):
        src_path = os.path.join(_REPO_ROOT, "core", "catering_growth.py")
        with open(src_path, encoding="utf-8") as f:
            src = f.read()
        self.assertIsNotNone(
            re.search(r"def import_contacts\([^)]*dry_run: bool = True", src, re.DOTALL))


if __name__ == "__main__":
    unittest.main()
