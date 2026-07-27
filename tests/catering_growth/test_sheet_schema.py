"""CATERING_SALES_TARGETS 33列スキーマのテスト。オフラインのみ・書き込みなし。

正典: docs/catering-growth/sheet-schema.md §2-1
コード: core/catering_sales.py

core.catering_sales は gspread / google-cloud-storage を import するため、
未インストール環境ではモジュール単位でスキップする（CI は requirements.lock から install 済）。
"""

import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from configs import catering_growth_vocab as v

try:
    from core import catering_sales as cs
    _IMPORT_ERROR = None
except Exception as exc:  # gspread / google-cloud-storage 未インストール等
    cs = None
    _IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


# 既存22列（順序・名称を変更してはいけない）。sheet-schema.md §2-1 の正本を写したもの。
EXISTING_22 = [
    "登録日時", "営業先名", "カテゴリ", "住所", "電話", "Instagram",
    "Webサイト", "担当者名", "想定ニーズ", "推定単価", "優先度",
    "営業文", "初回アプローチ日", "最終接触日", "返信状況",
    "商談状況", "見積状況", "成約状況", "次回フォロー日",
    "実売上", "メモ", "Obsidian Path",
]

# 集客OS用の追加11列（右端のみ）。
ADDED_11 = [
    "対象先ID", "種別", "流入元コード", "メール", "エリア", "接触元",
    "見込み確度", "ステータス", "使用テンプレートID", "UTM_URL", "紹介者",
]


@unittest.skipUnless(cs, f"core.catering_sales を import できない ({_IMPORT_ERROR})")
class TargetsHeaderTest(unittest.TestCase):

    def setUp(self):
        self.header = cs.CATERING_SHEETS["CATERING_SALES_TARGETS"]

    def test_01_has_33_columns(self):
        self.assertEqual(len(self.header), 33, "既存22 + 追加11 = 33列")

    def test_02_existing_22_unchanged_and_first(self):
        """既存22列は順序・名称そのままで先頭に来ること（位置参照コード保護）。"""
        self.assertEqual(self.header[:22], EXISTING_22)

    def test_03_added_11_are_at_the_right_end(self):
        """追加列は必ず右端。中間挿入は既存の位置参照を壊す。"""
        self.assertEqual(self.header[22:], ADDED_11)

    def test_04_headers_unique_and_non_empty(self):
        """get_all_records() は見出しの一意・非空を要求する。"""
        self.assertEqual(len(self.header), len(set(self.header)), "見出しの重複は不可")
        for h in self.header:
            self.assertTrue(str(h).strip(), "空の見出しは不可")

    def test_05_dashboard_unchanged(self):
        dash = cs.CATERING_SHEETS["CATERING_SALES_DASHBOARD"]
        self.assertEqual(dash, [
            "日付", "営業先数", "本日DM対象", "送信済み", "返信あり",
            "商談化", "見積提出", "成約", "推定売上", "実売上",
            "未対応", "最終更新",
        ], "ダッシュボードは今回変更しない")

    def test_06_format_range_matches_column_count(self):
        """ヘッダ書式の範囲が列数と一致すること（22列固定の A1:V1 が残っていない）。"""
        self.assertEqual(v.col_letter(len(self.header)), "AG")
        src_path = os.path.join(_REPO_ROOT, "core", "catering_sales.py")
        with open(src_path, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn('ws.format("A1:V1"', src, "列数固定の書式範囲が残っている")
        self.assertIn("col_letter(len(header))", src, "書式範囲を列数から算出していない")


@unittest.skipUnless(cs, f"core.catering_sales を import できない ({_IMPORT_ERROR})")
class TestDataAlignmentTest(unittest.TestCase):
    """generate_test_data の行が33列に揃うこと（列ズレの回帰テスト）。"""

    def test_07_rows_are_header_driven(self):
        """行の組み立てが見出し駆動で、列数に自動追従すること。"""
        src_path = os.path.join(_REPO_ROOT, "core", "catering_sales.py")
        with open(src_path, encoding="utf-8") as f:
            src = f.read()
        self.assertIn('[row_data.get(h, "") for h in header]', src,
                      "固定長リストではなく見出し駆動で組み立てること")

    def test_08_simulated_row_width_is_33(self):
        header = cs.CATERING_SHEETS["CATERING_SALES_TARGETS"]
        # generate_test_data と同じ組み立てを再現（シートには一切触らない）
        row_data = {
            "登録日時": "2026/08/01 10:00:00", "営業先名": "株式会社サンプル商事",
            "カテゴリ": "ホテル", "返信状況": "未送信", "商談状況": "未商談",
            "見積状況": "未提出", "成約状況": "未成約", "推定単価": 200_000,
            "優先度": "A", "実売上": 0,
        }
        row = [row_data.get(h, "") for h in header]
        self.assertEqual(len(row), 33)
        self.assertEqual(row[1], "株式会社サンプル商事")
        # 追加列は既定で空欄になる（既存の投入処理を壊さない）
        for i in range(22, 33):
            self.assertEqual(row[i], "", f"追加列 {header[i]} は空欄で入る")

    def test_09_existing_defaults_derive_to_new_status(self):
        """既存テストデータの既定値が NEW に導出されること（未成約→WON の誤判定回帰）。"""
        self.assertEqual(
            v.derive_status(reply="未送信", negotiation="未商談",
                            quote="未提出", deal="未成約"),
            "NEW")


@unittest.skipUnless(cs, f"core.catering_sales を import できない ({_IMPORT_ERROR})")
class AddedColumnVocabularyTest(unittest.TestCase):
    """追加列の許容値が語彙モジュールと対応していること。"""

    def test_10_vocab_backed_columns_exist(self):
        header = cs.CATERING_SHEETS["CATERING_SALES_TARGETS"]
        for col in ("種別", "流入元コード", "ステータス"):
            self.assertIn(col, header)

    def test_11_id_column_matches_format(self):
        self.assertIn("対象先ID", cs.CATERING_SHEETS["CATERING_SALES_TARGETS"])
        self.assertEqual(v.format_contact_id(42), "tc_0042")


@unittest.skipUnless(cs, f"core.catering_sales を import できない ({_IMPORT_ERROR})")
class SetupDryRunTest(unittest.TestCase):
    """setup(dry_run=True) が1セルも書かないこと。"""

    class _FakeWorksheet:
        def __init__(self, title):
            self.title = title

    class _FakeSpreadsheet:
        """書き込み系メソッドを呼ばれたら即座に失敗するスタブ。"""

        def __init__(self, titles):
            self._titles = list(titles)
            self.write_calls = []

        def worksheets(self):
            return [SetupDryRunTest._FakeWorksheet(t) for t in self._titles]

        def worksheet(self, title):
            if title in self._titles:
                return SetupDryRunTest._FakeWorksheet(title)
            raise AssertionError(f"dry_run で worksheet({title}) を引かせない想定")

        def add_worksheet(self, **kwargs):
            self.write_calls.append(("add_worksheet", kwargs))
            raise AssertionError("dry_run 中に add_worksheet が呼ばれた")

    def _patched_setup(self, existing_titles, dry_run):
        fake_ss = self._FakeSpreadsheet(existing_titles)

        class _FakeClient:
            def open_by_key(self, key):
                return fake_ss

        orig_gc = cs._gc
        try:
            cs._gc = lambda creds_path: _FakeClient()
            result = cs.setup("FAKE_SPREADSHEET_KEY", "/nonexistent/creds.json",
                              dry_run=dry_run)
        finally:
            cs._gc = orig_gc
        return result, fake_ss

    def test_12_dry_run_writes_nothing(self):
        result, fake_ss = self._patched_setup([], dry_run=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(fake_ss.write_calls, [], "1セルも書き込まないこと")
        self.assertEqual(
            sorted(result["would_create"]),
            ["CATERING_SALES_DASHBOARD", "CATERING_SALES_TARGETS"])

    def test_13_dry_run_reports_33_columns(self):
        result, _ = self._patched_setup([], dry_run=True)
        targets = next(p for p in result["plan"] if p["sheet"] == "CATERING_SALES_TARGETS")
        self.assertEqual(targets["columns"], 33)
        self.assertEqual(targets["action"], "新規作成")
        self.assertEqual(targets["header"][:22], EXISTING_22)

    def test_14_dry_run_detects_existing_sheet(self):
        result, _ = self._patched_setup(["CATERING_SALES_TARGETS"], dry_run=True)
        targets = next(p for p in result["plan"] if p["sheet"] == "CATERING_SALES_TARGETS")
        self.assertEqual(targets["action"], "既存（変更しない）")
        self.assertEqual(result["would_create"], ["CATERING_SALES_DASHBOARD"])

    def test_15_dry_run_result_has_no_secret(self):
        result, _ = self._patched_setup([], dry_run=True)
        self.assertNotIn("creds", str(result).lower())
        self.assertNotIn("/nonexistent/creds.json", str(result))


@unittest.skipUnless(cs, f"core.catering_sales を import できない ({_IMPORT_ERROR})")
class NoExternalSendTest(unittest.TestCase):
    """このモジュールが外部送信・AI API を持ち込まないこと。"""

    def test_16_no_line_gmail_openai(self):
        src_path = os.path.join(_REPO_ROOT, "core", "catering_sales.py")
        with open(src_path, encoding="utf-8") as f:
            src = f.read()
        for bad in ("api.line.me", "requests.post", "openai", "broadcast",
                    "smtplib", "gmail"):
            self.assertNotIn(bad, src, f"{bad} を含めてはいけない")


if __name__ == "__main__":
    unittest.main()
