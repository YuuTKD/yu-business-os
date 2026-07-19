"""Tests for the PLAUD file importer. Pure/local; no network, GCS, or vault."""

import os
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.plaud import import_plaud_file as fi

DATE = "2026-07-19"


def _write(dirpath, name, content, mode="w"):
    p = os.path.join(dirpath, name)
    with open(p, mode) as fh:
        fh.write(content)
    return p


def _apply(src, dest, **kw):
    date = kw.pop("date", DATE)
    return fi.run("apply", src, dest_root=dest, date=date,
                  lister=lambda s: os.path.isfile(os.path.join(dest, s)),
                  reader=lambda s: (open(os.path.join(dest, s), encoding="utf-8").read()
                                    if os.path.isfile(os.path.join(dest, s)) else ""),
                  log_path=os.path.join(dest, "_log", "l.log"), **kw)


class ExtractTest(unittest.TestCase):
    def test_txt(self):
        d = tempfile.mkdtemp()
        p = _write(d, "a.txt", "会議メモ\n本人稼働を減らす")
        self.assertIn("本人稼働", fi.extract_text(p))

    def test_md(self):
        d = tempfile.mkdtemp()
        p = _write(d, "a.md", "# タイトル\n内容")
        self.assertIn("内容", fi.extract_text(p))

    def test_csv_to_md_table(self):
        d = tempfile.mkdtemp()
        p = _write(d, "a.csv", "項目,値\n売上,100")
        md = fi.extract_text(p)
        self.assertIn("| 項目 | 値 |", md)
        self.assertIn("| 売上 | 100 |", md)

    def test_json(self):
        d = tempfile.mkdtemp()
        p = _write(d, "a.json", '{"k": "本人稼働"}')
        self.assertIn("本人稼働", fi.extract_text(p))

    def test_unsupported_stops(self):
        d = tempfile.mkdtemp()
        p = _write(d, "a.xyz", "x")
        with self.assertRaises(SystemExit):
            fi.extract_text(p)

    def test_docx_missing_lib_stops(self):
        # python-docx absent in CI → clear STOP (not a crash)
        d = tempfile.mkdtemp()
        p = _write(d, "a.docx", "x")
        try:
            import docx  # noqa
            self.skipTest("python-docx present")
        except Exception:
            with self.assertRaises(SystemExit):
                fi.extract_text(p)


class EmptyTest(unittest.TestCase):
    def test_empty_file_stops(self):
        d = tempfile.mkdtemp(); dst = tempfile.mkdtemp()
        p = _write(d, "e.txt", "   \n  ")
        with self.assertRaises(SystemExit):
            _apply(p, dst)


class SaveTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.dst = tempfile.mkdtemp()

    def test_saves_raw_processed_bybusiness_index(self):
        p = _write(self.d, "m.txt", "ケータリングの商談。見積を出す。")
        res = _apply(p, self.dst)
        self.assertEqual(res["status"], "OK")
        got = {os.path.relpath(w, self.dst) for w in res["written"]}
        self.assertTrue(any("00_Raw_Transcripts" in g for g in got))
        self.assertTrue(any("01_Processed" in g for g in got))
        self.assertTrue(any("02_By_Business" in g for g in got))
        self.assertTrue(any(g.endswith("INDEX.md") for g in got))

    def test_business_override_and_classify(self):
        p = _write(self.d, "m.txt", "ケータリングの話")
        self.assertEqual(_apply(p, self.dst, business="投資")["business"], "投資")  # override wins
        p2 = _write(self.d, "n.txt", "脱毛サロンの新メニュー")
        self.assertEqual(_apply(p2, self.dst)["business"], "Tree Beauty")

    def test_tags_and_raw_unmodified(self):
        p = _write(self.d, "m.txt", "決定した方針\n本文そのまま")
        res = _apply(p, self.dst)
        raw = open([w for w in res["written"] if "00_Raw" in w][0], encoding="utf-8").read()
        self.assertIn("#plaud", raw)
        self.assertIn("本文そのまま", raw)          # raw unmodified

    def test_dedup_same_sha(self):
        p = _write(self.d, "m.txt", "同じ内容の会議")
        r1 = _apply(p, self.dst)
        self.assertEqual(r1["status"], "OK")
        r2 = _apply(p, self.dst)                      # same file/sha → skip
        self.assertEqual(r2["status"], "SKIPPED_DUPLICATE")

    def test_past_files_preserved(self):
        p1 = _write(self.d, "a.txt", "会議A 2026-07-17")
        _apply(p1, self.dst, date="2026-07-17")
        p2 = _write(self.d, "b.txt", "会議B")
        _apply(p2, self.dst, date=DATE)
        raws = []
        for root, _, files in os.walk(os.path.join(self.dst, "10_PLAUD", "00_Raw_Transcripts")):
            raws += [f for f in files if f.endswith(".md")]
        self.assertEqual(len(raws), 2)               # both kept, none deleted


class SecretPiiTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.dst = tempfile.mkdtemp()

    def test_secret_redacted_in_raw(self):
        p = _write(self.d, "s.txt", "議事\ntoken=ghp_" + "A" * 30)
        res = _apply(p, self.dst)
        raw = open([w for w in res["written"] if "00_Raw" in w][0], encoding="utf-8").read()
        self.assertNotIn("ghp_AAAA", raw)
        self.assertIn("REDACTED", raw)

    def test_private_key_stops(self):
        # marker built via concatenation so the literal never appears in source
        # (avoids the governance secret-scan flagging this test file itself).
        mark = "-----BEGIN " + "PRIVATE KEY" + "-----"
        p = _write(self.d, "k.txt", mark + "\nabc\n" + mark.replace("BEGIN", "END"))
        orig = fi.redact
        fi.redact = lambda t: (t, 0)  # simulate unredactable → STOP
        try:
            with self.assertRaises(SystemExit):
                _apply(p, self.dst)
        finally:
            fi.redact = orig

    def test_processed_masks_pii(self):
        p = _write(self.d, "m.txt", "顧客 tanaka@example.com 090-1234-5678 と商談")
        res = _apply(p, self.dst)
        raw = open([w for w in res["written"] if "00_Raw" in w][0], encoding="utf-8").read()
        proc = open([w for w in res["written"] if "01_Processed" in w][0], encoding="utf-8").read()
        self.assertIn("tanaka@example.com", raw)     # raw BODY preserved
        self.assertNotIn("tanaka@example.com", proc)  # processed masks PII
        # PII must never leak into the filename / INDEX link
        self.assertNotIn("tanaka@example.com", res["filename"])

    def test_log_has_no_raw_or_secret(self):
        # first line = clean title; sensitive body text + secret come later, and
        # must NOT appear in the log (log records paths/counts, not the body).
        p = _write(self.d, "s.txt", "定例会議メモ\n機微な本文詳細です token=ghp_" + "B" * 30)
        _apply(p, self.dst)
        logf = os.path.join(self.dst, "_log", "l.log")
        content = open(logf, encoding="utf-8").read() if os.path.isfile(logf) else ""
        self.assertNotIn("ghp_BBBB", content)          # secret value not logged
        self.assertNotIn("機微な本文詳細", content)     # transcript body not logged


class IndexTest(unittest.TestCase):
    def test_update_index_caps_and_dedups(self):
        idx = ""
        for i in range(25):
            idx = fi.update_index(idx, f"T{i}", f"2026-07-19_T{i}_x.md", "Catering")
        links = [l for l in idx.splitlines() if l.startswith("- [[")]
        self.assertLessEqual(len(links), 20)
        self.assertIn("## 事業別（タグ検索）", idx)


class DestSafetyTest(unittest.TestCase):
    def test_refuses_vault_and_drive(self):
        d = tempfile.mkdtemp()
        p = _write(d, "m.txt", "x")
        for bad in (fi.LOCAL_VAULT, os.path.expanduser("~/Google Drive/x")):
            with self.assertRaises(SystemExit):
                fi.run("apply", p, dest_root=bad, date=DATE)


class SanitizeTest(unittest.TestCase):
    def test_japanese_title_kept_unsafe_removed(self):
        self.assertEqual(fi.sanitize_title("守成/クラブ:那覇*会議"), "守成クラブ那覇会議")

    def test_plan_writes_nothing(self):
        d = tempfile.mkdtemp(); dst = tempfile.mkdtemp()
        p = _write(d, "m.txt", "内容")
        fi.run("plan", p, dest_root=dst, date=DATE)
        self.assertFalse(os.path.exists(os.path.join(dst, "10_PLAUD")))


if __name__ == "__main__":
    unittest.main()
