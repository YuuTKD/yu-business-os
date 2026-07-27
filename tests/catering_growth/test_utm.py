"""UTM リンク生成のテスト。オフラインのみ・ネットワーク非接続・書き込みなし。

正典: docs/catering-growth/vocabulary.md §4
コード: core/catering_growth.py
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

BASE = "https://example.test/catering"


class ValidateTokenTest(unittest.TestCase):

    def test_01_accepts_lower_snake(self):
        for ok in ("instagram", "partner_space", "tc_0042", "story", "a1_b2"):
            self.assertEqual(cg.validate_utm_token(ok), ok)

    def test_02_rejects_japanese(self):
        for bad in ("パートナー", "紹介", "インスタ"):
            with self.assertRaises(cg.UtmError, msg=f"{bad!r} を通してはいけない"):
                cg.validate_utm_token(bad)

    def test_03_rejects_space(self):
        for bad in ("instagram story", "a b", " instagram", "instagram "):
            with self.assertRaises(cg.UtmError, msg=f"{bad!r} を通してはいけない"):
                cg.validate_utm_token(bad)

    def test_04_rejects_uppercase(self):
        for bad in ("Instagram", "IG", "Partner_Space"):
            with self.assertRaises(cg.UtmError, msg=f"{bad!r} を通してはいけない"):
                cg.validate_utm_token(bad)

    def test_05_rejects_hyphen_and_symbols(self):
        for bad in ("partner-space", "a.b", "a/b", "a?b", "a=b", "a&b", "a%20b"):
            with self.assertRaises(cg.UtmError, msg=f"{bad!r} を通してはいけない"):
                cg.validate_utm_token(bad)

    def test_06_rejects_empty_and_none(self):
        for bad in ("", None):
            with self.assertRaises(cg.UtmError):
                cg.validate_utm_token(bad)

    def test_07_does_not_silently_fix(self):
        """自動で小文字化しないこと。直すとシートの値と実URLが食い違い集計がズレる。"""
        with self.assertRaises(cg.UtmError):
            cg.validate_utm_token("Instagram")

    def test_08_error_message_names_the_field(self):
        with self.assertRaises(cg.UtmError) as ctx:
            cg.validate_utm_token("ダメ", field="utm_source")
        self.assertIn("utm_source", str(ctx.exception))


class CampaignTest(unittest.TestCase):

    def test_09_accepts_documented_format(self):
        for ok in ("tc_202608_partner_open", "tc_202601_past_customer", "tc_202612_x"):
            self.assertEqual(cg.validate_campaign(ok), ok)

    def test_10_rejects_wrong_shape(self):
        for bad in ("partner_open", "tc_2026_partner", "tc_20260801_x",
                    "xx_202608_partner", "tc_202608", "tc_202608_"):
            with self.assertRaises(cg.UtmError, msg=f"{bad!r} を通してはいけない"):
                cg.validate_campaign(bad)

    def test_11_make_campaign(self):
        self.assertEqual(cg.make_campaign("202608", "partner_open"),
                         "tc_202608_partner_open")

    def test_12_make_campaign_rejects_bad_month(self):
        for ym in ("2026-08", "20268", "", "abcdef", None):
            with self.assertRaises(cg.UtmError):
                cg.make_campaign(ym, "x")

    def test_13_make_campaign_rejects_bad_purpose(self):
        for purpose in ("提携", "Partner Open", "partner-open", ""):
            with self.assertRaises(cg.UtmError):
                cg.make_campaign("202608", purpose)


class ResolveBaseUrlTest(unittest.TestCase):

    def setUp(self):
        self._saved = os.environ.pop(v.LP_BASE_URL_ENV, None)

    def tearDown(self):
        os.environ.pop(v.LP_BASE_URL_ENV, None)
        if self._saved is not None:
            os.environ[v.LP_BASE_URL_ENV] = self._saved

    def test_14_explicit_wins(self):
        os.environ[v.LP_BASE_URL_ENV] = "https://from-env.test/"
        self.assertEqual(cg.resolve_lp_base_url(BASE), BASE)

    def test_15_env_is_used(self):
        os.environ[v.LP_BASE_URL_ENV] = BASE
        self.assertEqual(cg.resolve_lp_base_url(), BASE)

    def test_16_raises_when_nowhere_configured(self):
        """booking_url が空 かつ 環境変数なし → 例外。黙って空URLで続行しない。"""
        from configs.business_registry import get as get_config
        if str(get_config("catering").get("booking_url", "") or "").strip():
            self.skipTest("booking_url が設定済みのため未設定ケースを再現できない")
        with self.assertRaises(cg.UtmError) as ctx:
            cg.resolve_lp_base_url()
        self.assertIn(v.LP_BASE_URL_ENV, str(ctx.exception))

    def test_17_rejects_non_http(self):
        for bad in ("example.test/catering", "ftp://example.test", "javascript:alert(1)",
                    "/catering", "https://"):
            with self.assertRaises(cg.UtmError, msg=f"{bad!r} を通してはいけない"):
                cg.resolve_lp_base_url(bad)


class BuildUrlTest(unittest.TestCase):

    def test_18_basic(self):
        got = cg.build_utm_url("instagram", "story", "tc_202608_past_customer",
                               base_url=BASE)
        self.assertEqual(
            got,
            "https://example.test/catering"
            "?utm_source=instagram&utm_medium=story&utm_campaign=tc_202608_past_customer")

    def test_19_with_content(self):
        got = cg.build_utm_url("referral", "line", "tc_202608_referral",
                               content="tc_0042", base_url=BASE)
        self.assertIn("utm_content=tc_0042", got)

    def test_20_omits_empty_content(self):
        for empty in (None, "", "   "):
            got = cg.build_utm_url("line", "line", "tc_202608_x",
                                   content=empty, base_url=BASE)
            self.assertNotIn("utm_content", got, f"content={empty!r} で空パラメータを付けない")

    def test_21_preserves_existing_query(self):
        got = cg.build_utm_url("instagram", "feed", "tc_202608_x",
                               base_url="https://example.test/lp?plan=party")
        self.assertIn("plan=party", got)
        self.assertIn("utm_source=instagram", got)

    def test_22_overwrites_existing_utm(self):
        """既に utm_* が付いた URL を渡しても重複させず上書きすること。"""
        got = cg.build_utm_url(
            "referral", "dm", "tc_202608_new",
            base_url="https://example.test/lp?utm_source=old&utm_medium=old")
        self.assertEqual(got.count("utm_source="), 1)
        self.assertEqual(got.count("utm_medium="), 1)
        self.assertIn("utm_source=referral", got)
        self.assertNotIn("old", got)

    def test_23_preserves_fragment(self):
        got = cg.build_utm_url("line", "line", "tc_202608_x",
                               base_url="https://example.test/lp#form")
        self.assertTrue(got.endswith("#form"), got)

    def test_24_is_idempotent(self):
        """同じ入力からは常に同じURL（2回呼んで一致）。"""
        args = ("instagram", "story", "tc_202608_x")
        first  = cg.build_utm_url(*args, content="tc_0001", base_url=BASE)
        second = cg.build_utm_url(*args, content="tc_0001", base_url=BASE)
        self.assertEqual(first, second)

    def test_25_feeding_output_back_does_not_duplicate(self):
        """生成済みURLを再度ベースにしても utm_* が増殖しないこと。"""
        once  = cg.build_utm_url("instagram", "story", "tc_202608_x", base_url=BASE)
        twice = cg.build_utm_url("instagram", "story", "tc_202608_x", base_url=once)
        self.assertEqual(once, twice)

    def test_26_rejects_unknown_source(self):
        for bad in ("インスタ", "Instagram", "tiktok", "", "unknown_source"):
            with self.assertRaises(cg.UtmError, msg=f"source={bad!r} を通してはいけない"):
                cg.build_utm_url(bad, "story", "tc_202608_x", base_url=BASE)

    def test_27_rejects_unknown_medium(self):
        for bad in ("ストーリー", "Story", "tv", ""):
            with self.assertRaises(cg.UtmError, msg=f"medium={bad!r} を通してはいけない"):
                cg.build_utm_url("instagram", bad, "tc_202608_x", base_url=BASE)

    def test_28_rejects_japanese_content(self):
        with self.assertRaises(cg.UtmError):
            cg.build_utm_url("instagram", "story", "tc_202608_x",
                             content="対象先", base_url=BASE)

    def test_29_all_12_sources_and_9_mediums_work(self):
        """語彙の全組み合わせが生成できること（108通り）。"""
        count = 0
        for src in v.SOURCE_CODES:
            for med in v.UTM_MEDIUMS:
                url = cg.build_utm_url(src, med, "tc_202608_all", base_url=BASE)
                self.assertIn(f"utm_source={src}", url)
                self.assertIn(f"utm_medium={med}", url)
                count += 1
        self.assertEqual(count, 12 * 9)

    def test_30_no_percent_encoding_needed_for_valid_tokens(self):
        """命名規則を守った値はエンコードされず、そのまま読める形で出ること。"""
        got = cg.build_utm_url("partner_wedding", "referral_card",
                               "tc_202608_partner_open", content="tc_0099",
                               base_url=BASE)
        self.assertNotIn("%", got, got)


class BuildForContactTest(unittest.TestCase):

    def test_31_puts_contact_id_in_content(self):
        got = cg.build_utm_url_for_contact("tc_0042", "partner_space", "qr",
                                           "tc_202608_partner_open", base_url=BASE)
        self.assertIn("utm_content=tc_0042", got)
        self.assertIn("utm_source=partner_space", got)

    def test_32_rejects_invalid_contact_id(self):
        for bad in ("TC_0042", "tc-0042", "対象先42", "", None):
            with self.assertRaises(cg.UtmError, msg=f"{bad!r} を通してはいけない"):
                cg.build_utm_url_for_contact(bad, "partner_space", "qr",
                                             "tc_202608_x", base_url=BASE)

    def test_33_matches_documented_id_pattern(self):
        cid = v.format_contact_id(42)
        self.assertRegex(cid, v.ID_PATTERN_CONTACT)
        got = cg.build_utm_url_for_contact(cid, "referral", "line",
                                           "tc_202608_referral", base_url=BASE)
        self.assertIn(f"utm_content={cid}", got)


class ParseUtmTest(unittest.TestCase):

    def test_34_round_trip(self):
        url = cg.build_utm_url("google_business", "gbp_post", "tc_202608_meo",
                               content="tpl_gbp_01", base_url=BASE)
        self.assertEqual(cg.parse_utm(url), {
            "utm_source":   "google_business",
            "utm_medium":   "gbp_post",
            "utm_campaign": "tc_202608_meo",
            "utm_content":  "tpl_gbp_01",
        })

    def test_35_ignores_non_utm_params(self):
        got = cg.parse_utm("https://example.test/lp?plan=party&utm_source=line")
        self.assertEqual(got, {"utm_source": "line"})

    def test_36_handles_empty_and_garbage(self):
        for bad in ("", None, "not a url", "https://example.test/lp"):
            self.assertEqual(cg.parse_utm(bad), {})

    def test_37_returns_unknown_values_as_is(self):
        """未知の値でも例外にせず返す（判定は呼び出し側の責任）。"""
        got = cg.parse_utm("https://example.test/lp?utm_source=tiktok")
        self.assertEqual(got, {"utm_source": "tiktok"})


class SafetyTest(unittest.TestCase):
    """外部送信・課金・秘密情報・本番書き込みを持ち込まないこと。"""

    def _src(self):
        path = os.path.join(_REPO_ROOT, "core", "catering_growth.py")
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_38_no_external_send(self):
        """外部への送信手段を持たないこと。

        W1-6 で Sheets 操作が加わったため gspread は許容するが、
        遅延 import であることは test_funnel_keys.test_35 で検証している。
        """
        src = self._src()
        for bad in ("requests", "urllib.request", "httpx", "socket",
                    "api.line.me", "broadcast", "smtplib", "openai", "gcloud"):
            self.assertNotIn(bad, src, f"{bad} を含めてはいけない")

    def test_39_no_sheet_or_row_creation(self):
        """シート作成・行追加は行わないこと。

        W1-6 で見出し行への `update` と空セルへの `batch_update` が入ったが、
        いずれも dry_run 既定（test_40b）で、**行やシートを増やさない**。
        """
        src = self._src()
        for bad in ("append_row", "append_rows", "add_worksheet", "del_worksheet"):
            self.assertNotIn(bad, src, f"{bad}: 行やシートを増やしてはいけない")

    def test_40_no_secret_or_id_or_pii(self):
        src = self._src()
        for pattern in (r"sk-[A-Za-z0-9]{20,}", r"ghp_[A-Za-z0-9]{20,}",
                        r"AIza[0-9A-Za-z_\-]{20,}", r"-----BEGIN",
                        r"1[A-Za-z0-9_\-]{40,}",
                        r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}",
                        r"0\d{1,3}-\d{2,4}-\d{4}"):
            self.assertIsNone(re.search(pattern, src), f"検出: {pattern}")

    def test_40b_write_functions_default_to_dry_run(self):
        """シートに書く公開関数はすべて dry_run 既定 True であること。"""
        src = self._src()
        for fn in ("ensure_columns", "migrate_funnel_keys", "backfill_inquiry_ids"):
            self.assertIsNotNone(
                re.search(rf"def {fn}\([^)]*dry_run: bool = True", src, re.DOTALL),
                f"{fn} の dry_run 既定が True でない")

    def test_41_no_hardcoded_lp_url(self):
        """LP の URL 実値をコードに持たない（環境変数名だけを持つ）。

        許容するのは Google API のスコープ識別子（`https://www.googleapis.com/auth/...`）
        とテスト用の `example.test` のみ。
        """
        src = self._src()
        self.assertIn("LP_BASE_URL_ENV", src)
        found = re.findall(r"https?://[A-Za-z0-9.\-]+", src)
        allowed = {"https://www.googleapis.com", "https://example.test"}
        unexpected = [u for u in found if u not in allowed]
        self.assertEqual(unexpected, [],
                         f"実在しそうな URL がハードコードされている: {unexpected}")


if __name__ == "__main__":
    unittest.main()
