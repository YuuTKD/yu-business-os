"""広告費ゼロ集客OS 語彙の正典のテスト。オフラインのみ・ネットワーク非接続。

正典: docs/catering-growth/vocabulary.md
コード: configs/catering_growth_vocab.py
"""

import os
import re
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from configs import catering_growth_vocab as v


class CountTest(unittest.TestCase):
    """vocabulary.md に書かれた件数と一致すること。"""

    def test_01_counts_match_doc(self):
        self.assertEqual(len(v.SOURCE_CODES), 12, "流入元コードは12種（vocabulary.md §1）")
        self.assertEqual(len(v.CONTACT_TYPES), 11, "種別は11種（§3）")
        self.assertEqual(len(v.STATUSES), 13, "ステータスは13種（§2）")
        self.assertEqual(len(v.UTM_MEDIUMS), 9, "utm_medium は9種（§4）")
        self.assertEqual(len(v.LOST_REASONS), 8, "失注理由は8種（§6）")
        self.assertEqual(len(v.PRIORITIES), 3, "優先度は3種（§7）")

    def test_02_defaults_are_members(self):
        self.assertIn(v.SOURCE_CODE_DEFAULT, v.SOURCE_CODES)
        self.assertIn(v.CONTACT_TYPE_DEFAULT, v.CONTACT_TYPES)
        self.assertIn(v.STATUS_DEFAULT, v.STATUSES)
        self.assertIn(v.LOST_REASON_DEFAULT, v.LOST_REASONS)
        self.assertIn(v.PRIORITY_DEFAULT, v.PRIORITIES)

    def test_03_no_duplicate_labels(self):
        # 表示名の重複はシートのプルダウンで区別できなくなるため許さない
        for name, table in (("SOURCE_CODES", v.SOURCE_CODES),
                            ("CONTACT_TYPES", v.CONTACT_TYPES),
                            ("STATUSES", v.STATUSES),
                            ("LOST_REASONS", v.LOST_REASONS)):
            labels = list(table.values())
            self.assertEqual(len(labels), len(set(labels)), f"{name} の表示名が重複")

    def test_04_codes_are_lower_snake(self):
        # 流入元コードは utm_source にそのまま入るため UTM 規則を満たす必要がある
        for code in v.SOURCE_CODES:
            self.assertRegex(code, v.UTM_TOKEN_PATTERN, f"{code} が UTM 規則違反")
        for code in v.UTM_MEDIUMS:
            self.assertRegex(code, v.UTM_TOKEN_PATTERN, f"{code} が UTM 規則違反")

    def test_05_statuses_are_upper_snake(self):
        for code in v.STATUSES:
            self.assertRegex(code, r"^[A-Z][A-Z0-9_]*$", f"{code} は大文字スネークにする")

    def test_06_subsets_are_members(self):
        for c in v.SOURCE_CODES_AUTO:
            self.assertIn(c, v.SOURCE_CODES)
        for c in v.PARTNER_CONTACT_TYPES:
            self.assertIn(c, v.CONTACT_TYPES)
        for s in v.STATUS_TERMINAL + v.STATUS_ALWAYS_REACHABLE:
            self.assertIn(s, v.STATUSES)


class ValidatorTest(unittest.TestCase):

    def test_07_accepts_valid(self):
        self.assertTrue(v.is_valid_source_code("instagram"))
        self.assertTrue(v.is_valid_contact_type("partner_bar"))
        self.assertTrue(v.is_valid_status("QUOTED"))
        self.assertTrue(v.is_valid_lost_reason("date_unavailable"))
        self.assertTrue(v.is_valid_priority("a"), "優先度は大小文字を問わない")
        self.assertTrue(v.is_valid_utm_medium("story"))

    def test_08_rejects_invalid(self):
        for bad in ("", None, "インスタ", "Instagram", "instagram ", "unknown_code"):
            if bad == "instagram ":
                continue  # 前後空白は落として受け付ける（下で個別に検証）
            self.assertFalse(v.is_valid_source_code(bad), f"{bad!r} を受け付けてはいけない")
        self.assertFalse(v.is_valid_status("won"), "ステータスは大文字のみ")
        self.assertFalse(v.is_valid_priority("D"))

    def test_09_trims_whitespace(self):
        self.assertTrue(v.is_valid_source_code("  instagram  "))
        self.assertTrue(v.is_valid_status(" WON "))


class TransitionTest(unittest.TestCase):

    def test_10_documented_path_is_allowed(self):
        path = ["NEW", "READY_TO_CONTACT", "CONTACTED", "FOLLOW_UP_1", "FOLLOW_UP_2", "DORMANT"]
        for cur, nxt in zip(path, path[1:]):
            self.assertTrue(v.is_transition_allowed(cur, nxt), f"{cur}→{nxt} は想定内")

    def test_11_win_path_is_allowed(self):
        path = ["REPLIED", "INQUIRY", "QUOTED", "WON"]
        for cur, nxt in zip(path, path[1:]):
            self.assertTrue(v.is_transition_allowed(cur, nxt), f"{cur}→{nxt} は想定内")

    def test_12_replied_reachable_from_anywhere(self):
        # 相手はいつ返事してくるか分からない
        for cur in ("CONTACTED", "FOLLOW_UP_1", "FOLLOW_UP_2", "PARTNER_LISTED", "NEW"):
            self.assertTrue(v.is_transition_allowed(cur, "REPLIED"), f"{cur}→REPLIED は許可")

    def test_13_terminal_never_leaves(self):
        for term in v.STATUS_TERMINAL:
            for nxt in v.STATUSES:
                self.assertFalse(v.is_transition_allowed(term, nxt),
                                 f"{term}→{nxt}: 終了状態からは戻さない")

    def test_14_dormant_can_restart(self):
        self.assertTrue(v.is_transition_allowed("DORMANT", "READY_TO_CONTACT"))

    def test_15_unknown_status_rejected(self):
        self.assertFalse(v.is_transition_allowed("NEW", "NOT_A_STATUS"))
        self.assertFalse(v.is_transition_allowed("", "WON"))


class RouteMappingTest(unittest.TestCase):
    """既存の自由記述 `経路` → 流入元コード。"""

    def test_16_maps_documented_examples(self):
        cases = {
            "紹介":                 "referral",
            "知人紹介":              "referral",
            "口コミ":               "referral",
            "リピート":              "existing_customer",
            "既存顧客":              "existing_customer",
            "知り合い":              "existing_network",
            "インスタ":              "instagram",
            "Instagram DM":        "instagram",
            "LINE":                "line",
            "Googleマップ":         "google_business",
            "MEO":                 "google_business",
            "検索":                 "organic_search",
            "ホームページ":           "organic_search",
            "立ち飲み屋":            "own_business",
            "TACHINOMIYA":         "own_business",
            "BAR":                 "partner_bar",
            "クラブ":               "partner_bar",
            "レンタルスペース":        "partner_space",
            "結婚式二次会":           "partner_wedding",
            "ウェディング":           "partner_wedding",
        }
        for route, expected in cases.items():
            self.assertEqual(v.source_from_route(route), expected, f"経路={route!r}")

    def test_17_web_maps_to_organic(self):
        # 本番 02_問い合わせ のサンプル行の経路は "WEB" だった
        self.assertEqual(v.source_from_route("WEB"), "organic_search")
        self.assertEqual(v.source_from_route("web"), "organic_search")

    def test_18_wedding_beats_space(self):
        # 「結婚式二次会会場」は「会場」にも当たる。より具体的な方を採る
        self.assertEqual(v.source_from_route("結婚式二次会会場"), "partner_wedding")

    def test_19_empty_and_unknown_fall_back_to_other(self):
        for bad in ("", None, "   ", "なんだかよく分からない経路"):
            self.assertEqual(v.source_from_route(bad), v.SOURCE_CODE_DEFAULT)

    def test_20_short_token_needs_exact_match(self):
        # "ig" の部分一致は誤爆する（signature 等）。完全一致のみ許す
        self.assertEqual(v.source_from_route("ig"), "instagram")
        self.assertEqual(v.source_from_route("signature design"), v.SOURCE_CODE_DEFAULT)

    def test_21_always_returns_valid_code(self):
        samples = ["紹介", "WEB", "", None, "謎", "BAR", "ig", "結婚式", 12345]
        for s in samples:
            self.assertTrue(v.is_valid_source_code(v.source_from_route(s)),
                            f"{s!r} の変換結果が語彙外")


class CategoryMappingTest(unittest.TestCase):
    """既存の `カテゴリ`（日本語）→ 種別。"""

    def test_22_maps_existing_test_data_categories(self):
        # core/catering_sales.py の _TEST_TARGETS が使うカテゴリ
        cases = {
            "ホテル":          "hotel_villa",
            "BAR":            "partner_bar",
            "クラブ":          "partner_bar",
            "レンタルスペース":  "partner_space",
            "結婚式場":        "partner_wedding",
            "イベント会社":     "event_company",
            "撮影スタジオ":     "studio",
            "美容サロン":      "beauty_bridal",
        }
        for cat, expected in cases.items():
            self.assertEqual(v.contact_type_from_category(cat), expected, f"カテゴリ={cat!r}")

    def test_23_wedding_beats_space(self):
        self.assertEqual(v.contact_type_from_category("結婚式二次会会場"), "partner_wedding")

    def test_24_always_returns_valid_type(self):
        for s in ("ホテル", "", None, "謎の業種", "企業", 999):
            self.assertTrue(v.is_valid_contact_type(v.contact_type_from_category(s)),
                            f"{s!r} の変換結果が語彙外")


class DeriveStatusTest(unittest.TestCase):
    """既存4列 → 13値ステータスの導出。"""

    def test_25_existing_test_data_defaults_to_new_or_contacted(self):
        # generate_test_data が入れる既定値。「未成約」を WON と誤判定しないこと（回帰）
        got = v.derive_status(reply="未送信", negotiation="未商談",
                              quote="未提出", deal="未成約")
        self.assertEqual(got, "NEW", "未成約/未提出/未商談/未送信 は NEW")

    def test_26_negative_forms_are_not_positive(self):
        self.assertNotEqual(v.derive_status(deal="未成約"), "WON")
        self.assertNotEqual(v.derive_status(quote="未提出"), "QUOTED")
        self.assertNotEqual(v.derive_status(negotiation="未商談"), "MEETING")
        self.assertNotEqual(v.derive_status(reply="未返信"), "REPLIED")

    def test_27_priority_order_matches_doc(self):
        self.assertEqual(v.derive_status(deal="成約"), "WON")
        self.assertEqual(v.derive_status(deal="失注"), "LOST")
        self.assertEqual(v.derive_status(quote="提出済"), "QUOTED")
        self.assertEqual(v.derive_status(negotiation="商談中"), "MEETING")
        self.assertEqual(v.derive_status(reply="返信あり"), "REPLIED")
        # 成約は見積・商談・返信より優先される
        self.assertEqual(
            v.derive_status(reply="返信あり", negotiation="商談中",
                            quote="提出済", deal="成約"), "WON")

    def test_28_follow_up_boundaries(self):
        base = {"first_contact": "2026/08/01"}
        self.assertEqual(v.derive_status(**base, days_since_contact=0), "CONTACTED")
        self.assertEqual(v.derive_status(**base, days_since_contact=3), "CONTACTED",
                         "ちょうど3日はまだ CONTACTED")
        self.assertEqual(v.derive_status(**base, days_since_contact=4), "FOLLOW_UP_1")
        self.assertEqual(v.derive_status(**base, days_since_contact=7), "FOLLOW_UP_1",
                         "ちょうど7日はまだ FOLLOW_UP_1")
        self.assertEqual(v.derive_status(**base, days_since_contact=8), "FOLLOW_UP_2")

    def test_29_no_first_contact_is_new(self):
        self.assertEqual(v.derive_status(), "NEW")
        self.assertEqual(v.derive_status(first_contact="", days_since_contact=99), "NEW")

    def test_30_always_returns_valid_status(self):
        for kwargs in ({}, {"deal": "謎"}, {"reply": None}, {"first_contact": "x"}):
            self.assertTrue(v.is_valid_status(v.derive_status(**kwargs)))


class IdFormatTest(unittest.TestCase):

    def test_31_contact_id(self):
        self.assertEqual(v.format_contact_id(1), "tc_0001")
        self.assertEqual(v.format_contact_id(42), "tc_0042")
        self.assertEqual(v.format_contact_id(9999), "tc_9999")
        for got in (v.format_contact_id(1), v.format_contact_id(9999)):
            self.assertRegex(got, v.ID_PATTERN_CONTACT)

    def test_32_contact_id_rejects_out_of_range(self):
        for bad in (0, -1, 10000):
            with self.assertRaises(ValueError):
                v.format_contact_id(bad)

    def test_33_inquiry_id(self):
        self.assertEqual(v.format_inquiry_id("202608", 7), "inq_202608_007")
        self.assertRegex(v.format_inquiry_id("202601", 999), v.ID_PATTERN_INQUIRY)

    def test_34_inquiry_id_rejects_bad_input(self):
        for ym, seq in (("2026-08", 1), ("20268", 1), ("", 1), ("202608", 0), ("202608", 1000)):
            with self.assertRaises(ValueError):
                v.format_inquiry_id(ym, seq)


class ContactChannelTest(unittest.TestCase):

    def test_35_detects_any_channel(self):
        # ダミーは docs の慣習に合わせる（090-0000-0000 / example.test）
        self.assertTrue(v.has_contact_channel({"電話": "090-0000-0000"}))
        self.assertTrue(v.has_contact_channel({"メール": "a@example.test"}))
        self.assertTrue(v.has_contact_channel({"Instagram": "@x"}))

    def test_36_rejects_empty(self):
        self.assertFalse(v.has_contact_channel({}))
        self.assertFalse(v.has_contact_channel({"電話": "", "メール": "  ", "Instagram": None}))
        self.assertFalse(v.has_contact_channel({"営業先名": "株式会社サンプル商事"}))


class ColumnLetterTest(unittest.TestCase):
    """列番号 → A1記法。33列のヘッダ書式範囲の算出に使う。"""

    def test_37_known_columns(self):
        cases = {1: "A", 22: "V", 26: "Z", 27: "AA", 33: "AG", 52: "AZ", 53: "BA"}
        for n, expected in cases.items():
            self.assertEqual(v.col_letter(n), expected, f"列{n}")

    def test_38_rejects_zero_and_negative(self):
        for bad in (0, -1):
            with self.assertRaises(ValueError):
                v.col_letter(bad)


class SafetyTest(unittest.TestCase):
    """語彙モジュールが外部送信・課金・秘密情報を持ち込まないこと。"""

    def _src(self):
        path = os.path.join(_REPO_ROOT, "configs", "catering_growth_vocab.py")
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_39_no_network_or_paid_api(self):
        """import 文と属性アクセスで検出する（散文中の単語に誤反応しないこと）。"""
        src = self._src()
        forbidden = ("requests", "urllib", "http", "httpx", "socket", "gspread",
                     "openai", "smtplib", "subprocess", "os", "google")
        for mod in forbidden:
            self.assertIsNone(
                re.search(rf"^\s*(?:import|from)\s+{re.escape(mod)}\b", src, re.MULTILINE),
                f"語彙モジュールで {mod} を import してはいけない")
            self.assertIsNone(
                re.search(rf"\b{re.escape(mod)}\s*\.", src),
                f"語彙モジュールで {mod}.* を呼んではいけない")

    def test_39b_imports_are_stdlib_typing_only(self):
        """import は __future__ のみ（純粋な定数と純関数だけで済むこと）。"""
        src = self._src()
        imports = re.findall(r"^\s*(?:import|from)\s+([A-Za-z0-9_.]+)", src, re.MULTILINE)
        self.assertEqual(imports, ["__future__"], f"想定外の import: {imports}")

    def test_40_no_secret_or_spreadsheet_id(self):
        src = self._src()
        for pattern in (r"sk-[A-Za-z0-9]{20,}", r"ghp_[A-Za-z0-9]{20,}",
                        r"AIza[0-9A-Za-z_\-]{20,}", r"-----BEGIN",
                        r"1[A-Za-z0-9_\-]{40,}"):
            self.assertIsNone(re.search(pattern, src), f"秘密情報/ID実値パターン検出: {pattern}")

    def test_41_lp_url_comes_from_env_only(self):
        # LP の URL 実値をコードに持たない（環境変数名だけを持つ）
        src = self._src()
        self.assertIn("CATERING_LP_BASE_URL", src)
        self.assertNotIn("https://", src, "LP や外部 URL の実値をコードに書かない")

    def test_42_no_pii_in_module(self):
        src = self._src()
        self.assertIsNone(re.search(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", src),
                          "メールアドレスらしき文字列を含めない")
        self.assertIsNone(re.search(r"0\d{1,3}-\d{2,4}-\d{4}", src),
                          "電話番号らしき文字列を含めない")


if __name__ == "__main__":
    unittest.main()
