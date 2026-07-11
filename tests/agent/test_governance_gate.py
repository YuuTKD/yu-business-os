"""Tests for the Governance Gate adapter (Phase D-Lite).

Covers normal / dangerous / failure / shell-contract scenarios. The pure
``evaluate`` function is exercised with synthetic diffs (no git needed); one
integration test drives the CLI over a throwaway git repo.
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

GATE_PATH = os.path.join(_REPO_ROOT, "scripts", "agent", "governance_gate.py")
_spec = importlib.util.spec_from_file_location("governance_gate", GATE_PATH)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

FEATURE_BRANCH = "feat/example"


def ev(files, added="", *, action="pr_change_review", owner=False,
       agent="claude-code-implementation-agent", skill=None, branch=FEATURE_BRANCH):
    return gate.evaluate(
        files, added, agent_id=agent, action=action, skill_id=skill,
        owner_approved=owner, branch_name=branch, repo_root=_REPO_ROOT,
    )


class NormalCasesTest(unittest.TestCase):
    def test_01_docs_only_go(self):
        self.assertEqual(ev(["docs/AUTO_PR_FLOW.md"])["decision"], "GO")

    def test_02_tests_only_go(self):
        r = ev(["tests/agent/test_governance_gate.py"])
        self.assertEqual(r["decision"], "GO")
        self.assertIn(r["risk_level"], ("MEDIUM", "LOW"))

    def test_03_config_add_needs_owner(self):
        # configs/ is HIGH → owner approval before merge.
        self.assertEqual(ev(["configs/skills/registry.yaml"])["decision"],
                         "OWNER_APPROVAL_REQUIRED")

    def test_04_core_add_needs_owner(self):
        self.assertEqual(ev(["core/governance/validator.py"])["decision"],
                         "OWNER_APPROVAL_REQUIRED")

    def test_05_unknown_action_stop(self):
        self.assertEqual(ev(["docs/x.md"], action="frobnicate")["decision"], "STOP")

    def test_06_unknown_agent_stop(self):
        self.assertEqual(ev(["docs/x.md"], agent="ghost-agent")["decision"], "STOP")


class DangerousCasesTest(unittest.TestCase):
    def test_07_env_change_stop(self):
        self.assertEqual(ev([".env"])["decision"], "STOP")

    def test_07b_nested_env_stop(self):
        self.assertEqual(ev(["core/.env.local"])["decision"], "STOP")

    def test_08_credentials_change_stop(self):
        self.assertEqual(ev(["configs/credentials.json"])["decision"], "STOP")

    # NOTE: dangerous fixtures are assembled at runtime from parts so that no
    # single source line literally matches a secret/runaway detector — otherwise
    # this test file would trip the governance gate (and secret scanners) itself.
    def test_09_secret_string_stop(self):
        key = "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
        self.assertEqual(ev(["core/x.py"], "API_KEY = " + key)["decision"], "STOP")

    def test_09b_secret_value_never_echoed(self):
        secret = "ghp_" + ("A" * 36)
        r = ev(["core/x.py"], "token = " + secret)
        self.assertEqual(r["decision"], "STOP")
        self.assertNotIn(secret, repr(r))  # value must never surface

    def test_10_acquisition_change_stop(self):
        self.assertEqual(ev(["scripts/acquisition/run.js"])["decision"], "STOP")

    def test_11_tree_beauty_activate_stop(self):
        target = "tree " + "beauty"                     # not literal on one line
        added = 'x["status"] = "active"  # ' + "enable " + target
        self.assertEqual(ev(["configs/business_registry.py"], added)["decision"], "STOP")

    def test_12_daily_post_limit_change_stop(self):
        added = "daily_post_limit" + " = 5"
        self.assertEqual(ev(["configs/auto_post_settings.py"], added)["decision"], "STOP")

    def test_13_scheduler_change_stop_or_owner(self):
        verb = "enable job"
        added = "gcloud scheduler jobs update --" + verb
        self.assertIn(ev(["scripts/deploy_scheduler.sh"], added)["decision"],
                      ("STOP", "OWNER_APPROVAL_REQUIRED"))

    def test_14_deploy_change_owner_or_stop(self):
        self.assertIn(ev(["scripts/cloud_run_deploy.sh"])["decision"],
                      ("OWNER_APPROVAL_REQUIRED", "STOP"))

    def test_15_line_send_owner_or_stop(self):
        self.assertIn(ev(["core/line_notify.py"])["decision"],
                      ("OWNER_APPROVAL_REQUIRED", "STOP"))

    def test_16_sheets_write_owner_or_stop(self):
        self.assertIn(ev(["core/sheets_writer.py"])["decision"],
                      ("OWNER_APPROVAL_REQUIRED", "STOP"))

    def test_17_critical_plus_owner_still_stop(self):
        # Owner approval must NOT bypass a CRITICAL signal.
        self.assertEqual(ev([".env"], owner=True)["decision"], "STOP")

    def test_18_high_plus_owner_go_no_automerge(self):
        r = ev(["core/governance/validator.py"], owner=True)
        self.assertEqual(r["decision"], "GO")
        self.assertIn("no_auto_merge_for_high_risk", r.get("matched_policies", []))


class FailureModeTest(unittest.TestCase):
    def test_19_validator_import_failure_internal_error(self):
        # Force import failure by removing repo root from sys.path temporarily.
        saved = list(sys.path)
        saved_mods = {k: sys.modules[k] for k in list(sys.modules)
                      if k.startswith("core.governance") or k == "core"}
        try:
            for k in list(sys.modules):
                if k.startswith("core.governance") or k in ("core", "core.registry"):
                    del sys.modules[k]
            sys.path[:] = [p for p in sys.path if os.path.abspath(p) != _REPO_ROOT]
            r = gate.evaluate(["docs/x.md"], "", agent_id="a", action="pr_change_review",
                              skill_id=None, owner_approved=False, branch_name="feat/x",
                              repo_root="/nonexistent-repo-root")
            self.assertEqual(r["decision"], "INTERNAL_ERROR")
        finally:
            sys.path[:] = saved
            sys.modules.update(saved_mods)

    def test_21_unknown_decision_guarded(self):
        # evaluate only ever emits the 5 known decisions.
        r = ev(["docs/x.md"])
        self.assertIn(r["decision"], ("GO", "FIX", "STOP", "OWNER_APPROVAL_REQUIRED",
                                      "INTERNAL_ERROR"))

    def test_22_git_diff_failure_internal_error(self):
        # collect_diff on a non-git dir raises → main() must map to INTERNAL_ERROR.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        rc = gate.main(["--base", "origin/main", "--head", "HEAD",
                        "--repo-root", tmp.name, "--json"])
        self.assertEqual(rc, gate.EXIT["INTERNAL_ERROR"])

    def test_23_bad_base_ref_internal_error(self):
        rc = gate.main(["--base", "origin/does-not-exist-ref", "--head", "HEAD",
                        "--repo-root", _REPO_ROOT, "--json"])
        self.assertEqual(rc, gate.EXIT["INTERNAL_ERROR"])


class ExitCodeContractTest(unittest.TestCase):
    def test_exit_code_mapping(self):
        self.assertEqual(gate.EXIT["GO"], 0)
        self.assertEqual(gate.EXIT["FIX"], 10)
        self.assertEqual(gate.EXIT["OWNER_APPROVAL_REQUIRED"], 20)
        self.assertEqual(gate.EXIT["STOP"], 30)
        self.assertEqual(gate.EXIT["INTERNAL_ERROR"], 40)

    def test_owner_approved_env_one_shot(self):
        # env var acts as owner approval; not persisted anywhere by the gate.
        os.environ["YU_OWNER_APPROVED"] = "true"
        try:
            rc = _run_cli_git_repo(owner_env=True)
        finally:
            del os.environ["YU_OWNER_APPROVED"]
        # HIGH change + owner env → GO (0)
        self.assertEqual(rc, 0)


def _run_cli_git_repo(owner_env=False):
    """Integration: build a self-contained mini-repo (git diff + governance
    config in one root, mirroring production), then run the CLI over it."""
    import shutil
    tmp = tempfile.mkdtemp()
    # Copy the real governance/registry config so the validator can load it.
    for sub in ("configs/skills", "configs/agents", "configs/governance"):
        shutil.copytree(os.path.join(_REPO_ROOT, sub), os.path.join(tmp, sub))

    def sh(*a):
        subprocess.run(["git", *a], cwd=tmp, check=True,
                       capture_output=True, text=True)
    sh("init", "-q")
    sh("config", "user.email", "t@example.com")
    sh("config", "user.name", "t")
    os.makedirs(os.path.join(tmp, "docs"))
    with open(os.path.join(tmp, "docs", "seed.md"), "w") as f:
        f.write("seed\n")
    sh("add", "docs/seed.md", "configs")
    sh("commit", "-q", "-m", "seed")
    sh("branch", "-M", "main")
    sh("checkout", "-q", "-b", "feat/change")
    os.makedirs(os.path.join(tmp, "core"))
    with open(os.path.join(tmp, "core", "thing.py"), "w") as f:
        f.write("x = 1\n")
    sh("add", "core/thing.py")
    sh("commit", "-q", "-m", "core change")
    args = ["--base", "main", "--head", "HEAD", "--repo-root", tmp, "--json"]
    if owner_env:
        args.append("--owner-approved")
    rc = subprocess.run([sys.executable, GATE_PATH, *args],
                        env=dict(os.environ), capture_output=True, text=True)
    shutil.rmtree(tmp, ignore_errors=True)
    return rc.returncode


class RunawayScanScopeTest(unittest.TestCase):
    """The runaway scan must skip the governance engine / docs / tests so the
    detector never flags its own pattern definitions, but must still catch a
    runaway change in real config/business code."""

    def test_excluded_paths(self):
        for p in ("docs/x.md", "tests/agent/test_x.py", "core/governance/diff_risk.py",
                  "scripts/agent/governance_gate.py", "scripts/agent/pr_auto_flow.sh",
                  "README.md"):
            self.assertTrue(gate._runaway_excluded(p), p)

    def test_included_paths(self):
        for p in ("configs/business_registry.py", "core/owner_daily.py",
                  "scripts/gen_content_3biz.py"):
            self.assertFalse(gate._runaway_excluded(p), p)

    def test_filtered_runaway_text_does_not_stop(self):
        # A governance-engine file containing the token, but runaway_text filtered
        # empty → must NOT STOP (classified HIGH → owner approval).
        token = "tree_beauty" + "_activate"
        r = gate.evaluate(
            ["core/governance/validator.py"], f'STOP_ACTIONS = "{token}"',
            agent_id="claude-code-implementation-agent", action="pr_change_review",
            skill_id=None, owner_approved=False, branch_name=FEATURE_BRANCH,
            repo_root=_REPO_ROOT, runaway_text="",
        )
        self.assertEqual(r["decision"], "OWNER_APPROVAL_REQUIRED")

    def test_real_config_runaway_still_stops(self):
        # Same token in a real config file (not filtered) → STOP.
        line = "daily_post_limit" + " = 9"
        r = gate.evaluate(
            ["configs/auto_post_settings.py"], line,
            agent_id="claude-code-implementation-agent", action="pr_change_review",
            skill_id=None, owner_approved=False, branch_name=FEATURE_BRANCH,
            repo_root=_REPO_ROOT, runaway_text=line,
        )
        self.assertEqual(r["decision"], "STOP")


class IntegrationTest(unittest.TestCase):
    def test_24_25_cli_high_change_owner_required_then_go(self):
        # Without approval → OWNER_APPROVAL_REQUIRED (exit 20).
        self.assertEqual(_run_cli_git_repo(owner_env=False),
                         gate.EXIT["OWNER_APPROVAL_REQUIRED"])
        # With approval → GO (exit 0).
        self.assertEqual(_run_cli_git_repo(owner_env=True), gate.EXIT["GO"])


if __name__ == "__main__":
    unittest.main()
