"""Phase R2.5 — tests for scripts/release/bootstrap_release_infra.sh.

Runs the script in non-mutating modes via subprocess and asserts safety
invariants: plan changes nothing, apply is fail-closed, least-privilege roles,
append-only ledger, Environment marked MANUAL_STEP_REQUIRED. No gcloud state is
mutated (plan/guard paths only)."""

import os
import subprocess
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPT = os.path.join(_REPO_ROOT, "scripts", "release", "bootstrap_release_infra.sh")


def run(*args, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    p = subprocess.run(["bash", _SCRIPT, *args], capture_output=True, text=True, env=e)
    return p.returncode, p.stdout + p.stderr


class PlanModeTest(unittest.TestCase):
    def setUp(self):
        self.rc, self.out = run("--plan")

    def test_plan_exit_zero(self):
        self.assertEqual(self.rc, 0, self.out)

    def test_plan_changes_nothing(self):
        self.assertIn("[PLAN]", self.out)
        self.assertNotIn("[APPLY]", self.out)
        self.assertIn("変更は行っていません", self.out)

    def test_plan_lists_all_resources(self):
        for name in ("github-release-pool", "github-oidc", "release-deployer",
                     "release-verifier", "release-ledger", "yu-release",
                     "yu-release-ledger"):
            self.assertIn(name, self.out, name)

    def test_repo_scoped_wif_condition(self):
        self.assertIn("assertion.repository == 'YuuTKD/yu-business-os'", self.out)

    def test_no_scheduler_touch(self):
        self.assertIn("Cloud Scheduler / Production traffic には一切触れません", self.out)


class LeastPrivilegeTest(unittest.TestCase):
    def setUp(self):
        self.rc, self.out = run("--plan")

    def test_no_broad_roles(self):
        for bad in ("roles/owner", "roles/editor", "roles/run.admin"):
            self.assertNotIn(bad, self.out, bad)

    def test_ledger_is_append_only(self):
        # ledger SA gets objectCreator (create, not overwrite/delete), never admin
        self.assertIn("roles/storage.objectCreator", self.out)
        self.assertNotIn("roles/storage.objectAdmin", self.out)
        self.assertNotIn("roles/storage.admin", self.out)

    def test_no_long_lived_key(self):
        # WIF only — the script must never create a service-account key
        self.assertNotIn("keys create", self.out)


class ApplyGuardTest(unittest.TestCase):
    def test_apply_without_confirm_is_fail_closed(self):
        rc, out = run("--apply")  # no CONFIRM (and CI has no gcloud)
        self.assertNotEqual(rc, 0)
        # fail-closed for either reason: gcloud absent OR missing CONFIRM=yes
        self.assertTrue("CONFIRM=yes" in out or "gcloud 未導入" in out, out)
        self.assertNotIn("[APPLY]", out)  # nothing executed

    def test_unknown_mode_exits_2(self):
        rc, out = run("--frobnicate")
        self.assertEqual(rc, 2)


class EnvironmentManualStepTest(unittest.TestCase):
    def test_environment_marked_manual(self):
        rc, out = run("--plan")
        self.assertIn("MANUAL_STEP_REQUIRED", out)
        self.assertIn("production", out)


class ProjectNumberPlaceholderTest(unittest.TestCase):
    """Regression: the STEP 5 WIF-binding failure was a literal <PROJECT_NUMBER>
    placeholder leaking into the real principalSet. Guard against it returning."""

    PLACEHOLDER = "<" + "PROJECT_NUMBER" + ">"  # avoid the literal in this file too

    def test_no_literal_placeholder_in_source(self):
        with open(_SCRIPT, encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn(self.PLACEHOLDER, src)

    def test_no_placeholder_in_any_mode_output(self):
        for mode in ("--plan", "--verify", "--rollback-plan"):
            rc, out = run(mode)
            self.assertNotIn(self.PLACEHOLDER, out, mode)

    def test_plan_principalset_uses_numeric_project_number(self):
        rc, out = run("--plan")
        self.assertEqual(rc, 0, out)
        # principalSet must reference a numeric project number, never a placeholder
        import re
        m = re.search(r"principalSet://iam\.googleapis\.com/projects/([^/]+)/", out)
        self.assertIsNotNone(m, out)
        self.assertRegex(m.group(1), r"^[0-9]+$")

    def test_repo_attribute_path_present(self):
        rc, out = run("--plan")
        self.assertIn("attribute.repository/YuuTKD/yu-business-os", out)


if __name__ == "__main__":
    unittest.main()
