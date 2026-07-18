"""Tests for the daily Knowledge OS export layer. Pure/local; no GCS, no network,
no vault write. Uses a temp dest-root to exercise write/idempotency safely."""

import os
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.knowledge import export_daily_knowledge as ex

DATE = "2026-07-18"


def _apply(dest, date=DATE, projects=None):
    return ex.run("apply", projects or ["yu-business-os"], dest, date=date,
                  log_path=os.path.join(dest, "_log.jsonl"))


class DatedFilesTest(unittest.TestCase):
    def test_dated_files_generated(self):
        d = tempfile.mkdtemp()
        res = _apply(d)
        for suffix in (f"05_Reports/Daily/2026/07/{DATE}_DAILY_REPORT.md",
                       f"04_Decisions/2026/07/{DATE}_DECISIONS.md",
                       f"08_Automation_System/2026/07/{DATE}_AUTOMATION_LOG.md"):
            self.assertTrue(os.path.isfile(os.path.join(d, suffix)), suffix)

    def test_latest_dashboard_updated(self):
        d = tempfile.mkdtemp()
        _apply(d)
        self.assertTrue(os.path.isfile(os.path.join(d, "00_Dashboard/LATEST_DAILY_STATUS.md")))

    def test_same_day_idempotent_and_past_preserved(self):
        d = tempfile.mkdtemp()
        _apply(d, date="2026-07-17")
        past = os.path.join(d, "05_Reports/Daily/2026/07/2026-07-17_DAILY_REPORT.md")
        self.assertTrue(os.path.isfile(past))
        # new day + same day re-run
        _apply(d, date=DATE)
        _apply(d, date=DATE)
        # past dated file must still exist (never deleted)
        self.assertTrue(os.path.isfile(past))
        # exactly one file per day (no duplicate/timestamped copies)
        daily_dir = os.path.join(d, "05_Reports/Daily/2026/07")
        self.assertEqual(sorted(os.listdir(daily_dir)),
                         ["2026-07-17_DAILY_REPORT.md", f"{DATE}_DAILY_REPORT.md"])


class DestinationSafetyTest(unittest.TestCase):
    def test_only_writes_under_dest_root(self):
        d = tempfile.mkdtemp()
        res = _apply(d)
        for w in res["written"]:
            self.assertTrue(os.path.abspath(w).startswith(os.path.abspath(d)), w)

    def test_refuses_personal_vault(self):
        with self.assertRaises(SystemExit):
            ex.run("apply", ["yu-business-os"], ex.LOCAL_VAULT, date=DATE)

    def test_refuses_google_drive(self):
        for bad in (os.path.expanduser("~/Google Drive/x"), "~/GoogleDrive/knowledge"):
            with self.assertRaises(SystemExit):
                ex.run("plan", ["yu-business-os"], bad, date=DATE)


class SecretTest(unittest.TestCase):
    def test_redacts_secret_values(self):
        red, n = ex.redact("token=ghp_" + "A" * 30 + " and sk-" + "B" * 30)
        self.assertGreaterEqual(n, 2)
        self.assertIn(ex.REDACTED, red)
        self.assertNotIn("ghp_AAAA", red)

    def test_upload_stops_if_secret_survives(self):
        # monkeypatch redact to a no-op so a secret survives → run must STOP
        d = tempfile.mkdtemp()
        orig = ex.redact
        ex.redact = lambda t: (t, 0)
        # inject a secret into a builder via monkeypatch of build_dashboard
        orig_dash = ex.build_dashboard
        ex.build_dashboard = lambda pd, date, ga: "leak sk-" + "C" * 30
        try:
            with self.assertRaises(SystemExit):
                _apply(d)
        finally:
            ex.redact = orig
            ex.build_dashboard = orig_dash


class NoGuessTest(unittest.TestCase):
    def test_missing_project_marked_no_record_not_guessed(self):
        data = ex.collect_project("/nonexistent/project")
        self.assertFalse(data["available"])
        # dashboard for an unavailable project must say NO_RECORD, not invent data
        md = ex.build_dashboard([data], DATE, "t")
        self.assertIn(ex.NO_RECORD, md)

    def test_empty_sections_use_no_record(self):
        md = ex.build_daily_report([{"path": "x", "available": False}], DATE, "t")
        self.assertIn(ex.NO_RECORD, md)
        self.assertIn("production_impact: none", md)

    def test_github_failure_is_soft(self):
        # collect_project on a git repo with gh unavailable still returns dict
        data = ex.collect_project(_REPO_ROOT)
        self.assertTrue(data["available"])
        self.assertIn("prs_today", data)


class FrontmatterTest(unittest.TestCase):
    def test_daily_report_frontmatter(self):
        md = ex.build_daily_report([{"path": "yu-business-os", "available": True,
                                     "branch": "main", "commits_today": ex.NO_RECORD,
                                     "uncommitted_tracked": "なし", "prs_today": ex.NO_RECORD}],
                                   DATE, "2026-07-18T23:50:00+09:00")
        self.assertIn("type: daily-report", md)
        self.assertIn(f"date: {DATE}", md)
        self.assertIn("## 11. ゆうさんの判断", md)
        self.assertIn("- [ ] Yes / No", md)


class PlanModeTest(unittest.TestCase):
    def test_plan_writes_nothing(self):
        d = tempfile.mkdtemp()
        ex.run("plan", ["yu-business-os"], d, date=DATE)
        # plan must not create any dated file
        self.assertFalse(os.path.exists(os.path.join(d, "05_Reports")))


class LaunchAgentTest(unittest.TestCase):
    def setUp(self):
        self.plist = os.path.join(_REPO_ROOT, "config", "launchagents",
                                  "com.yuholdings.daily-knowledge-export.plist")
        with open(self.plist, encoding="utf-8") as fh:
            self.src = fh.read()

    def test_plist_is_valid_xml(self):
        import plistlib
        with open(self.plist, "rb") as fh:
            d = plistlib.load(fh)
        self.assertEqual(d["Label"], "com.yuholdings.daily-knowledge-export")

    def test_runs_at_2350_not_at_load(self):
        import plistlib
        with open(self.plist, "rb") as fh:
            d = plistlib.load(fh)
        self.assertEqual(d["StartCalendarInterval"]["Hour"], 23)
        self.assertEqual(d["StartCalendarInterval"]["Minute"], 50)
        self.assertFalse(d["RunAtLoad"])

    def test_has_stdout_stderr_workingdir(self):
        for key in ("StandardOutPath", "StandardErrorPath", "WorkingDirectory"):
            self.assertIn(key, self.src)


class RunnerShellTest(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(_REPO_ROOT, "scripts", "knowledge", "run_daily_export.sh"),
                  encoding="utf-8") as fh:
            self.src = fh.read()

    def test_no_local_delete_no_drive(self):
        self.assertNotIn("rsync -d", self.src)
        self.assertNotIn("rm -rf", self.src)
        self.assertNotIn("drive.google", self.src.lower())

    def test_double_run_guard(self):
        self.assertIn("mkdir \"$LOCK\"", self.src)

    def test_export_failure_nonzero(self):
        self.assertIn("exit 1", self.src)

    def test_sync_failure_is_warning_not_failure(self):
        self.assertIn("WARNING: 同期失敗", self.src)


if __name__ == "__main__":
    unittest.main()
