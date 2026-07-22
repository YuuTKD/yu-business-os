"""Tests for the PLAUD file → Obsidian 10_PLAUD importer. Pure/local; a temp dir
stands in for the vault (no real vault, no network)."""

import importlib.util
import os
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.plaud import import_plaud_file as fi

DATE = "2026-07-19"


def _w(d, name, content):
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(content)
    return p


def _apply(src, dest, **kw):
    date = kw.pop("date", DATE)
    return fi.run("apply", src, dest_root=dest, date=date,
                  reader=lambda s: (open(os.path.join(dest, s), encoding="utf-8").read()
                                    if os.path.isfile(os.path.join(dest, s)) else ""),
                  log_path=os.path.join(dest, "_log", "l.log"), **kw)


class ExtractTest(unittest.TestCase):
    def test_txt_md_csv_json(self):
        d = tempfile.mkdtemp()
        self.assertIn("本人", fi.extract_text(_w(d, "a.txt", "会議\n本人稼働")))
        self.assertIn("内容", fi.extract_text(_w(d, "a.md", "# T\n内容")))
        self.assertIn("| 項目 | 値 |", fi.extract_text(_w(d, "a.csv", "項目,値\n売上,100")))
        self.assertIn("本人", fi.extract_text(_w(d, "a.json", '{"k":"本人"}')))

    def test_unsupported_stops(self):
        d = tempfile.mkdtemp()
        with self.assertRaises(SystemExit):
            fi.extract_text(_w(d, "a.xyz", "x"))

    @unittest.skipIf(importlib.util.find_spec("docx") is not None, "python-docx present")
    def test_docx_missing_lib_stops(self):
        # when python-docx is absent, .docx extraction must STOP cleanly (not crash)
        d = tempfile.mkdtemp()
        with self.assertRaises(SystemExit):
            fi.extract_text(_w(d, "a.docx", "x"))

    @unittest.skipIf(importlib.util.find_spec("pypdf") is not None, "pypdf present")
    def test_pdf_missing_lib_stops(self):
        d = tempfile.mkdtemp()
        with self.assertRaises(SystemExit):
            fi.extract_text(_w(d, "a.pdf", "%PDF-1.4"))


class SaveTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.v = tempfile.mkdtemp()

    def test_saves_raw_and_processed(self):
        p = _w(self.d, "m.txt", "ケータリングの会議。見積を決定した。担当は田中、期限は来週。")
        res = _apply(p, self.v)
        self.assertEqual(res["status"], "OK")
        got = {os.path.relpath(w, self.v) for w in res["written"]}
        self.assertTrue(any(g.startswith("01_文字起こし原文/") for g in got))
        self.assertTrue(any(g.startswith("02_整理済み/") for g in got))
        self.assertTrue(any(g == "INDEX.md" for g in got))

    def test_routing_links(self):
        p = _w(self.d, "m.txt", "例会の議事。方針を決定。担当と期限のタスク。価値観として本人稼働削減を重視。")
        res = _apply(p, self.v)
        links = set(res["links"])
        self.assertTrue(any("04_決定事項" in l for l in links))
        self.assertTrue(any("05_タスク" in l for l in links))
        self.assertTrue(any("06_思想候補" in l for l in links))
        self.assertTrue(any("07_会議議事録" in l for l in links))
        self.assertTrue(any("03_事業別" in l for l in links))
        self.assertTrue(any("08_月別" in l for l in links))
        # aggregation pages use internal links, not content copies
        dec = open(os.path.join(self.v, "04_決定事項", "_決定事項.md"), encoding="utf-8").read()
        self.assertIn("[[02_整理済み/", dec)

    def test_business_override_and_auto(self):
        self.assertEqual(_apply(_w(self.d, "a.txt", "ケータリングの話"), self.v,
                                business="投資")["business"], "投資")
        self.assertEqual(_apply(_w(self.d, "b.txt", "脱毛サロンの新メニュー"), self.v)["business"],
                         "Tree Beauty")

    def test_dedup_same_sha(self):
        p = _w(self.d, "m.txt", "同じ内容の会議")
        self.assertEqual(_apply(p, self.v)["status"], "OK")
        self.assertEqual(_apply(p, self.v)["status"], "SKIPPED_DUPLICATE")

    def test_raw_unmodified_and_tags(self):
        p = _w(self.d, "m.txt", "会議メモ\n本文はそのまま保存される")
        res = _apply(p, self.v)
        raw = open([w for w in res["written"] if "01_文字起こし原文" in w][0], encoding="utf-8").read()
        self.assertIn("本文はそのまま保存される", raw)
        self.assertIn("- plaud", raw)

    def test_past_files_preserved(self):
        _apply(_w(self.d, "a.txt", "会議A"), self.v, date="2026-07-17")
        _apply(_w(self.d, "b.txt", "会議B"), self.v, date=DATE)
        raws = []
        for _r, _dd, files in os.walk(os.path.join(self.v, "01_文字起こし原文")):
            raws += [f for f in files if f.endswith(".md")]
        self.assertEqual(len(raws), 2)

    def test_month_page(self):
        res = _apply(_w(self.d, "m.txt", "2026-07-19 の会議"), self.v)
        self.assertTrue(os.path.isfile(os.path.join(self.v, "08_月別", "2026-07.md")))


class CandidateTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.v = tempfile.mkdtemp()

    def test_extract_verbatim_candidates(self):
        text = "来週から新メニューを開始すると決定した。田中が資料を準備する担当。本人稼働削減を最優先で重視する。"
        c = fi.extract_candidates(text)
        self.assertTrue(any("決定した" in s for s in c["decision"]))
        self.assertTrue(any("担当" in s for s in c["task"]))
        self.assertTrue(any("重視" in s for s in c["philosophy"]))
        # verbatim (from the original text), not a fabricated summary
        self.assertTrue(all(s in fi.mask_pii(text) or s[:20] in fi.mask_pii(text)
                            for s in c["decision"]))

    def test_no_match_is_empty_not_fabricated(self):
        c = fi.extract_candidates("ただの雑談です。天気の話。")
        self.assertEqual(c, {"decision": [], "task": [], "philosophy": []})

    def test_processed_shows_candidates_and_yesno(self):
        p = _w(self.d, "m.txt", "値上げを決定した。担当は田中で期限は来週。")
        res = _apply(p, self.v)
        proc = open([w for w in res["written"] if "02_整理済み" in w][0], encoding="utf-8").read()
        self.assertIn("値上げを決定した", proc)
        self.assertIn("observed・要確認", proc)
        self.assertIn("- [ ] Yes / No", proc)
        self.assertIn("candidate_counts", str(res.keys()) or "")

    def test_candidate_pii_masked(self):
        p = _w(self.d, "m.txt", "顧客 tanaka@example.com へ連絡すると決定した。")
        res = _apply(p, self.v)
        proc = open([w for w in res["written"] if "02_整理済み" in w][0], encoding="utf-8").read()
        self.assertIn("決定した", proc)
        self.assertNotIn("tanaka@example.com", proc)   # PII masked in candidate

    def test_empty_sections_stay_no_data(self):
        p = _w(self.d, "m.txt", "天気の話だけ。特に何もなし。")
        res = _apply(p, self.v)
        proc = open([w for w in res["written"] if "02_整理済み" in w][0], encoding="utf-8").read()
        self.assertIn("取得なし", proc)  # no fabricated decisions/tasks


class EmptyTest(unittest.TestCase):
    def test_empty_stops(self):
        d = tempfile.mkdtemp(); v = tempfile.mkdtemp()
        with self.assertRaises(SystemExit):
            _apply(_w(d, "e.txt", "   \n  "), v)


class SecretPiiTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.v = tempfile.mkdtemp()

    def test_secret_redacted(self):
        res = _apply(_w(self.d, "s.txt", "議事\ntoken=ghp_" + "A" * 30), self.v)
        raw = open([w for w in res["written"] if "01_文字起こし原文" in w][0], encoding="utf-8").read()
        self.assertNotIn("ghp_AAAA", raw)
        self.assertIn("REDACTED", raw)

    def test_severe_secret_stops(self):
        mark = "-----BEGIN " + "PRIVATE KEY" + "-----"
        p = _w(self.d, "k.txt", mark + "\nabc")
        orig = fi.redact
        fi.redact = lambda t: (t, 0)
        try:
            with self.assertRaises(SystemExit):
                _apply(p, self.v)
        finally:
            fi.redact = orig

    def test_pii_masked_in_processed_and_filename(self):
        p = _w(self.d, "m.txt", "顧客 tanaka@example.com 090-1234-5678 と商談を決定")
        res = _apply(p, self.v)
        raw = open([w for w in res["written"] if "01_文字起こし原文" in w][0], encoding="utf-8").read()
        proc = open([w for w in res["written"] if "02_整理済み" in w][0], encoding="utf-8").read()
        self.assertIn("tanaka@example.com", raw)          # raw preserved
        self.assertNotIn("tanaka@example.com", proc)      # processed has no raw body
        self.assertNotIn("tanaka@example.com", res["filename"])  # filename masked

    def test_log_no_body_or_secret(self):
        _apply(_w(self.d, "s.txt", "定例会議\n機微な本文詳細 token=ghp_" + "B" * 30), self.v)
        lf = os.path.join(self.v, "_log", "l.log")
        c = open(lf, encoding="utf-8").read() if os.path.isfile(lf) else ""
        self.assertNotIn("ghp_BBBB", c)
        self.assertNotIn("機微な本文詳細", c)


class DestSafetyTest(unittest.TestCase):
    def test_refuses_drive(self):
        d = tempfile.mkdtemp()
        p = _w(d, "m.txt", "x")
        for bad in (os.path.expanduser("~/Google Drive/x"), "~/Dropbox/x"):
            with self.assertRaises(SystemExit):
                fi.run("apply", p, dest_root=bad, date=DATE)

    def test_vault_is_allowed(self):
        # the vault path is now the intended target (not blocked)
        try:
            fi._assert_safe_dest(fi.VAULT_PLAUD)
        except SystemExit:
            self.fail("vault should be an allowed destination")


class PlanTest(unittest.TestCase):
    def test_plan_writes_nothing(self):
        d = tempfile.mkdtemp(); v = tempfile.mkdtemp()
        fi.run("plan", _w(d, "m.txt", "内容"), dest_root=v, date=DATE)
        self.assertFalse(os.path.exists(os.path.join(v, "01_文字起こし原文")))


class IndexTest(unittest.TestCase):
    def test_index_caps_30(self):
        idx = ""
        for i in range(35):
            idx = fi.build_index(idx, f"T{i}", f"02_整理済み/f{i}", "Catering")
        links = [l for l in idx.splitlines() if l.startswith("- [[02_整理済み/")]
        self.assertLessEqual(len(links), 30)
        self.assertIn("## 決定事項", idx)


class SanitizeTest(unittest.TestCase):
    def test_japanese_kept_unsafe_removed(self):
        self.assertEqual(fi.sanitize_title("守成/クラブ:那覇*例会"), "守成クラブ那覇例会")


if __name__ == "__main__":
    unittest.main()
