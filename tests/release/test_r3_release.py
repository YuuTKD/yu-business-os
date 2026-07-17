"""Phase R3 — tests for the candidate/smoke release pipeline. All read-only /
pure; no deploy, no network, no traffic change."""

import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.release import smoke_test

CATERING_EXPECTED = {
    "business_identity": "TREE'S CATERING",
    "image_generation_enabled": False,
    "line_text_delivery_enabled": True,
    "line_image_delivery_enabled": False,
    "delivery_mode": "TEXT_ONLY",
}


def good_status():
    return {
        "business": "TREE'S CATERING",
        "release": {
            "commit": "abc",
            "image_generation_enabled": False,
            "line_text_delivery_enabled": True,
            "line_image_delivery_enabled": False,
            "delivery_mode": "TEXT_ONLY",
        },
    }


class SmokeEvaluateTest(unittest.TestCase):
    def test_all_good_is_go(self):
        r = smoke_test.evaluate(200, 200, good_status(), CATERING_EXPECTED)
        self.assertEqual(r["verdict"], "GO", r["findings"])

    def test_health_not_200_rollback(self):
        self.assertEqual(smoke_test.evaluate(503, 200, good_status(), CATERING_EXPECTED)["verdict"], "ROLLBACK")

    def test_status_not_200_rollback(self):
        self.assertEqual(smoke_test.evaluate(200, 500, good_status(), CATERING_EXPECTED)["verdict"], "ROLLBACK")

    def test_identity_mismatch_rollback(self):
        s = good_status(); s["business"] = "SOMETHING ELSE"
        self.assertEqual(smoke_test.evaluate(200, 200, s, CATERING_EXPECTED)["verdict"], "ROLLBACK")

    def test_missing_release_block_fail_closed(self):
        s = {"business": "TREE'S CATERING"}  # no release block
        r = smoke_test.evaluate(200, 200, s, CATERING_EXPECTED)
        self.assertEqual(r["verdict"], "ROLLBACK")
        self.assertIn("release_block_missing", r["findings"])

    def test_image_generation_enabled_rollback(self):
        s = good_status(); s["release"]["image_generation_enabled"] = True
        self.assertEqual(smoke_test.evaluate(200, 200, s, CATERING_EXPECTED)["verdict"], "ROLLBACK")

    def test_line_image_enabled_rollback(self):
        s = good_status(); s["release"]["line_image_delivery_enabled"] = True
        self.assertEqual(smoke_test.evaluate(200, 200, s, CATERING_EXPECTED)["verdict"], "ROLLBACK")

    def test_delivery_mode_wrong_rollback(self):
        s = good_status(); s["release"]["delivery_mode"] = "TEXT_AND_IMAGE"
        self.assertEqual(smoke_test.evaluate(200, 200, s, CATERING_EXPECTED)["verdict"], "ROLLBACK")

    def test_line_text_stopped_rollback(self):
        s = good_status(); s["release"]["line_text_delivery_enabled"] = False
        self.assertEqual(smoke_test.evaluate(200, 200, s, CATERING_EXPECTED)["verdict"], "ROLLBACK")

    def test_secret_exposure_rollback(self):
        s = good_status(); s["leak"] = "sk-" + "A" * 30
        r = smoke_test.evaluate(200, 200, s, CATERING_EXPECTED)
        self.assertTrue(r["secret_exposure"])
        self.assertEqual(r["verdict"], "ROLLBACK")

    def test_non_json_body_fail_closed(self):
        self.assertEqual(smoke_test.evaluate(200, 200, None, CATERING_EXPECTED)["verdict"], "ROLLBACK")


class ServiceSpecTest(unittest.TestCase):
    def test_catering_spec_loaded(self):
        spec = smoke_test.load_service_spec("catering")
        self.assertIsNotNone(spec)
        self.assertEqual(spec["cloud_run_service"], "trees-catering-ai")
        self.assertTrue(spec["deploy_target"])
        self.assertEqual(spec["endpoints"]["health"], "/health")
        self.assertEqual(spec["expected"]["delivery_mode"], "TEXT_ONLY")

    def test_out_of_scope_not_deploy_target(self):
        for b in ("tachinomiya", "beauty", "ryukyu_hinabe", "pasta_pasta", "z1"):
            spec = smoke_test.load_service_spec(b)
            self.assertFalse(spec.get("deploy_target", False), b)

    def test_unknown_business_none(self):
        self.assertIsNone(smoke_test.load_service_spec("does_not_exist"))


class StatusEndpointTest(unittest.TestCase):
    def test_status_exposes_release_flags(self):
        os.environ.setdefault("BUSINESS_NAME", "catering")
        import importlib
        entry = importlib.import_module("core.entrypoint")
        client = entry.app.test_client()
        resp = client.get("/status")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertIn("release", body)
        rel = body["release"]
        self.assertIs(rel["image_generation_enabled"], False)
        self.assertIs(rel["line_text_delivery_enabled"], True)
        self.assertIs(rel["line_image_delivery_enabled"], False)
        self.assertEqual(rel["delivery_mode"], "TEXT_ONLY")

    def test_status_has_no_secret_values(self):
        os.environ.setdefault("BUSINESS_NAME", "catering")
        import importlib, json as _json
        entry = importlib.import_module("core.entrypoint")
        resp = entry.app.test_client().get("/status")
        from core.governance import diff_risk
        self.assertFalse(diff_risk.scan_secret_lines(_json.dumps(resp.get_json())))


class ReleaseWorkflowSafetyTest(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(_REPO_ROOT, ".github", "workflows", "release.yml"),
                  encoding="utf-8") as fh:
            self.src = fh.read()
        # executable content only: drop comment lines (explanatory 禁止 lists are
        # comments and legitimately name the forbidden operations).
        self.code = "\n".join(
            ln for ln in self.src.splitlines() if not ln.lstrip().startswith("#")
        )

    def test_manual_trigger_only(self):
        self.assertIn("workflow_dispatch", self.src)
        self.assertNotIn("\n  push:", self.src)  # no push trigger → no auto-deploy on merge

    def test_no_update_traffic(self):
        self.assertNotIn("update-traffic", self.code)

    def test_uses_no_traffic_candidate(self):
        self.assertIn("--no-traffic", self.code)
        self.assertIn("--tag candidate", self.code)

    def test_no_scheduler_or_secret_change(self):
        for bad in ("scheduler", "--set-env-vars", "--update-secrets", "secrets create"):
            self.assertNotIn(bad, self.code.lower() if bad == "scheduler" else self.code, bad)

    def test_environment_gate_and_wif(self):
        self.assertIn("environment: production", self.src)
        self.assertIn("id-token: write", self.src)

    def test_service_allowlist_catering_only(self):
        self.assertIn("trees-catering-ai", self.src)
        for other in ("tachinomiya-ai", "tree-beauty-ai", "ryukyu-hinabe-ai",
                      "pasta-pasta-ai", "z1-ai"):
            self.assertNotIn(other, self.src, other)

    def test_build_uses_runner_docker_not_cloud_build(self):
        # Option C: build on runner + push to AR. No Cloud Build / staging bucket
        # (root cause of the 'forbidden from accessing the bucket' error).
        self.assertNotIn("gcloud builds submit", self.code)
        self.assertNotIn("_cloudbuild", self.code)  # no staging bucket reference
        self.assertIn("docker build", self.code)
        self.assertIn("docker push", self.code)
        self.assertIn("configure-docker", self.code)

    def test_auth_preflight_fail_closed(self):
        # preflight compares active account / project and checks AR access, STOP otherwise
        self.assertIn("active account", self.src)
        self.assertIn("project mismatch", self.code)
        self.assertIn("artifacts repositories describe", self.code)
        self.assertIn("SA_DEPLOYER", self.src)

    def test_preflight_prints_no_secrets(self):
        # diagnostic prints account/project/host only — never tokens/credentials/IAM policy
        for bad in ("print-access-token", "print-identity-token", "get-iam-policy",
                    "auth print", "credentials.json"):
            self.assertNotIn(bad, self.code, bad)


class RetentionExceptionTest(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(_REPO_ROOT, "scripts", "release",
                               "bootstrap_release_infra.sh"), encoding="utf-8") as fh:
            self.src = fh.read()

    def test_accepted_exception_constant(self):
        self.assertIn('RETENTION_ACCEPTED_SECONDS="34495200"', self.src)

    def test_verify_reports_exception(self):
        self.assertIn("READY_WITH_EXCEPTION", self.src)

    def test_ensure_retention_skips_accepted_not_stop(self):
        # accepted value must be a SKIP branch, not fall through to STOP
        self.assertIn("OWNER_ACCEPTED_EXCEPTION", self.src)


if __name__ == "__main__":
    unittest.main()
