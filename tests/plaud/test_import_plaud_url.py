"""Tests for the PLAUD share-URL importer. Pure/local; no network, no browser,
no GCS, no vault write. The share token must never appear in any output."""

import os
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.plaud import import_plaud_url as pl

# A fake share URL with an obvious token; the token must never be persisted.
TOKEN = "SECRETTOKEN_" + "Z" * 40
URL = f"https://web.plaud.ai/s/pub_abc123::_{TOKEN}"
RID = "pub_abc123"
DATE = "2026-07-18"


def fake_fetch(url):
    return {"title": "テスト会議", "transcript": "本人稼働を減らす方針。担当は田中。",
            "recorded_at": "2026-07-18 10:00", "summary": "要約テキスト",
            "minutes": "", "speakers": "", "business": "catering"}


class UrlTest(unittest.TestCase):
    def test_valid_share_url(self):
        self.assertEqual(pl.validate_share_url(URL), URL)

    def test_non_plaud_url_stops(self):
        for bad in ("https://example.com/x", "http://web.plaud.ai/s/x", ""):
            with self.assertRaises(SystemExit):
                pl.validate_share_url(bad)

    def test_recording_id_excludes_token(self):
        self.assertEqual(pl.recording_id(URL), RID)
        self.assertNotIn(TOKEN, pl.recording_id(URL))

    def test_mask_url_hides_token(self):
        m = pl.mask_url(URL)
        self.assertNotIn(TOKEN, m)
        self.assertIn(RID, m)
        self.assertIn("REDACTED", m)


class TokenNonPersistenceTest(unittest.TestCase):
    def test_token_absent_from_generated_markdown(self):
        d = tempfile.mkdtemp()
        res = pl.run("apply", URL, dest_root=d, date=DATE, lister=lambda s: False,
                     fetcher=fake_fetch)
        for w in res["written"]:
            with open(w, encoding="utf-8") as fh:
                self.assertNotIn(TOKEN, fh.read())

    def test_token_absent_from_result(self):
        res = pl.run("plan", URL, dest_root="gs://x", date=DATE)
        self.assertNotIn(TOKEN, str(res))


class DedupTest(unittest.TestCase):
    def test_same_recording_id_not_resaved(self):
        res = pl.run("apply", URL, dest_root="gs://x", date=DATE,
                     lister=lambda s: True, fetcher=fake_fetch)  # exists → skip
        self.assertEqual(res["status"], "SKIPPED_DUPLICATE")
        self.assertEqual(res["written"], [])

    def test_idempotent_local(self):
        d = tempfile.mkdtemp()

        class L:  # a lister backed by the real dir
            def __call__(self, suffix):
                return os.path.isfile(os.path.join(d, suffix))
        pl.run("apply", URL, dest_root=d, date=DATE, lister=L(), fetcher=fake_fetch)
        # second run sees the raw file exists → SKIPPED (no duplicate)
        r2 = pl.run("apply", URL, dest_root=d, date=DATE, lister=L(), fetcher=fake_fetch)
        self.assertEqual(r2["status"], "SKIPPED_DUPLICATE")


class SecretPiiTest(unittest.TestCase):
    def test_secret_redacted(self):
        red, n = pl.redact("token=ghp_" + "A" * 30)
        self.assertGreaterEqual(n, 1)
        self.assertNotIn("ghp_AAAA", red)

    def test_secret_survive_stops(self):
        d = tempfile.mkdtemp()
        orig = pl.redact
        pl.redact = lambda t: (t, 0)  # no-op → secret survives

        def leaky(url):
            return {"title": "x", "transcript": "sk-" + "B" * 30, "summary": "",
                    "minutes": "", "speakers": "", "recorded_at": "", "business": ""}
        try:
            with self.assertRaises(SystemExit):
                pl.run("apply", URL, dest_root=d, date=DATE, lister=lambda s: False,
                       fetcher=leaky)
        finally:
            pl.redact = orig

    def test_pii_flagged_not_valued(self):
        flags = pl.pii_flags("連絡は tanaka@example.com か 090-1234-5678 まで")
        self.assertGreaterEqual(flags["email"], 1)
        self.assertGreaterEqual(flags["phone"], 1)

    def test_processed_masks_pii_raw_preserves(self):
        # raw keeps the transcript + summary unmodified (secrets already redacted);
        # processed excludes the raw transcript entirely and masks PII in the summary.
        d = tempfile.mkdtemp()
        def f(url):
            return {"title": "会議", "transcript": "顧客 tanaka@example.com へ連絡",
                    "summary": "要約: tanaka@example.com が担当", "minutes": "",
                    "speakers": "", "recorded_at": "", "business": ""}
        res = pl.run("apply", URL, dest_root=d, date=DATE, lister=lambda s: False, fetcher=f)
        raw = open([w for w in res["written"] if "00_Raw" in w][0], encoding="utf-8").read()
        proc = open([w for w in res["written"] if "01_Processed" in w][0], encoding="utf-8").read()
        self.assertIn("tanaka@example.com", raw)      # raw preserved unmodified
        self.assertNotIn("tanaka@example.com", proc)  # processed masks PII in summary
        self.assertIn("REDACTED", proc)
        self.assertNotIn("顧客 tanaka", proc)         # raw transcript not in processed


class BuildTest(unittest.TestCase):
    def test_raw_has_frontmatter_and_no_url(self):
        md = pl.build_raw_md({"recording_id": RID, "title": "T", "transcript": "本文"},
                             DATE, "2026-07-18T10:00:00+09:00")
        self.assertIn("source: PLAUD", md)
        self.assertIn("source_url_masked: true", md)
        self.assertIn("本文", md)
        self.assertNotIn("web.plaud.ai/s/", md)  # URL never embedded

    def test_processed_status_observed_not_confirmed(self):
        md = pl.build_processed_md({"recording_id": RID, "title": "T", "transcript": "決定した"},
                                   DATE, "t")
        self.assertIn("status: observed", md)
        self.assertNotIn("status: confirmed", md)
        self.assertIn("- [ ] Yes / No", md)

    def test_classify_and_unknown(self):
        self.assertEqual(pl.classify_type("見積を出す商談"), "sales")
        self.assertEqual(pl.classify_type("……"), "判定不能")


class DestSafetyTest(unittest.TestCase):
    def test_refuses_vault_and_drive(self):
        for bad in (pl.LOCAL_VAULT, os.path.expanduser("~/Google Drive/x")):
            with self.assertRaises(SystemExit):
                pl.run("apply", URL, dest_root=bad, date=DATE, fetcher=fake_fetch)

    def test_paths_under_10_plaud(self):
        p = pl.dest_paths(RID, DATE)
        for k in ("raw", "processed", "log"):
            self.assertTrue(p[k].startswith("10_PLAUD/"), p[k])


class PlanModeTest(unittest.TestCase):
    def test_plan_writes_nothing_and_no_body_fetch(self):
        d = tempfile.mkdtemp()
        # plan must not call the fetcher and must not create files
        pl.run("plan", URL, dest_root=d, date=DATE,
               fetcher=lambda u: (_ for _ in ()).throw(AssertionError("fetched in plan")))
        self.assertFalse(os.path.exists(os.path.join(d, "10_PLAUD")))


class ShellTest(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(_REPO_ROOT, "scripts", "plaud", "import_plaud_url.sh"),
                  encoding="utf-8") as fh:
            self.src = fh.read()

    def test_rejects_non_plaud_and_masks_token(self):
        self.assertIn("https://web.plaud.ai/s/*", self.src)
        self.assertIn("REDACTED", self.src)          # token masked in logs
        self.assertIn("::REDACTED", self.src)

    def test_no_url_persisted_to_file(self):
        # URL is passed via env to the child; never written to a data file
        self.assertIn('PLAUD_URL="$URL"', self.src)
        self.assertNotIn("echo \"$URL\" >", self.src)

    def test_nonzero_on_failure(self):
        self.assertIn("exit 1", self.src)


if __name__ == "__main__":
    unittest.main()
