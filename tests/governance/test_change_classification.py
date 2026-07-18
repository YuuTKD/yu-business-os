"""Phase R2 — tests for diff_risk.classify_change (Change Classification +
Test Selection). Pure/path-based; no git, no network, no production access."""

import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.governance import diff_risk as dr

REG = {
    "catering": {"cloud_run_service": "trees-catering-ai"},
    "tachinomiya": {"cloud_run_service": "tachinomiya-ai"},
    "beauty": {"cloud_run_service": "tree-beauty-ai"},
}


def cc(paths, **kw):
    return dr.classify_change(paths, registry=kw.get("registry", REG))


class SchemaTest(unittest.TestCase):
    def test_schema_keys_present(self):
        r = cc(["docs/x.md"])
        for k in ("risk_level", "categories", "affected_businesses",
                  "affected_services", "selected_test_groups", "full_test_required",
                  "staging_required", "production_approval_required",
                  "rollback_required", "blocked", "reasons"):
            self.assertIn(k, r)

    def test_empty_change_low_no_tests(self):
        r = cc([])
        self.assertEqual(r["risk_level"], "LOW")
        self.assertEqual(r["selected_test_groups"], [])
        self.assertFalse(r["full_test_required"])
        self.assertFalse(r["blocked"])


class CategoryTest(unittest.TestCase):
    def test_docs_only(self):
        r = cc(["docs/a.md", "README.md"])
        self.assertEqual(r["categories"], ["docs_only"])
        self.assertEqual(r["selected_test_groups"], [])
        self.assertFalse(r["staging_required"])
        self.assertFalse(r["production_approval_required"])

    def test_content_policy(self):
        r = cc(["configs/content_policy.yaml"])
        self.assertIn("content_policy", r["categories"])
        self.assertIn("content", r["selected_test_groups"])

    def test_image_policy(self):
        r = cc(["core/blog_image_generator.py"])
        self.assertIn("image_policy", r["categories"])

    def test_business_config(self):
        r = cc(["core/business_config/readiness.py"])
        self.assertTrue({"business_config", "ssot"} & set(r["categories"]))

    def test_ssot_registry(self):
        r = cc(["configs/businesses/registry.yaml"])
        self.assertIn("ssot", r["categories"])
        self.assertTrue(r["full_test_required"])  # ssot forces full

    def test_core_runtime_forces_full(self):
        r = cc(["core/entrypoint.py"])
        self.assertIn("core_runtime", r["categories"])
        self.assertTrue(r["full_test_required"])
        self.assertEqual(r["selected_test_groups"], ["FULL"])

    def test_governance_forces_full(self):
        r = cc(["core/governance/diff_risk.py"])
        self.assertIn("governance", r["categories"])
        self.assertTrue(r["full_test_required"])

    def test_scheduler_category(self):
        r = cc(["scripts/scheduler_setup.py"])
        self.assertIn("scheduler", r["categories"])

    def test_secret_reference_critical(self):
        r = cc([".env"])
        self.assertIn("secret_reference", r["categories"])
        self.assertEqual(r["risk_level"], "CRITICAL")
        self.assertTrue(r["blocked"])

    def test_external_send(self):
        r = cc(["core/daily_line_distributor.py"])
        self.assertIn("external_send", r["categories"])
        self.assertTrue(r["full_test_required"])

    def test_acquisition_blocked(self):
        r = cc(["scripts/acquisition/agent.py"])
        self.assertIn("acquisition", r["categories"])
        self.assertTrue(r["blocked"])

    def test_deployment_workflow(self):
        r = cc([".github/workflows/release.yml"])
        self.assertIn("deployment_workflow", r["categories"])
        self.assertTrue(r["full_test_required"])
        self.assertTrue(r["staging_required"])

    def test_automation_layer_not_unknown(self):
        for p in ("scripts/knowledge/export_daily_knowledge.py",
                  "config/launchagents/com.yuholdings.daily-knowledge-export.plist"):
            r = cc([p])
            self.assertIn("automation", r["categories"], p)
            self.assertNotIn("unknown", r["categories"], p)
            self.assertTrue(r["full_test_required"], p)
            self.assertFalse(r["blocked"], p)

    def test_cross_business(self):
        r = cc(["core/multi_business_content_engine.py"])
        self.assertIn("cross_business", r["categories"])
        self.assertTrue(r["full_test_required"])

    def test_financial_logic(self):
        r = cc(["core/cash_flow_survival.py"])
        self.assertIn("financial_logic", r["categories"])

    def test_cloud_run_service(self):
        r = cc(["Dockerfile"])
        self.assertIn("cloud_run_service", r["categories"])
        self.assertTrue(r["staging_required"])


class UnknownTest(unittest.TestCase):
    def test_unknown_path_fail_closed(self):
        r = cc(["weird/unmapped_dir/thing.bin"])
        self.assertIn("unknown", r["categories"])
        self.assertTrue(r["full_test_required"])
        self.assertTrue(r["blocked"])


class TestSelectionRuleTest(unittest.TestCase):
    def test_low_only_target_groups(self):
        # tests/ change is MEDIUM per classify_paths → adds governance+registry
        r = cc(["tests/content/test_x.py"])
        self.assertEqual(r["risk_level"], "MEDIUM")
        self.assertIn("governance", r["selected_test_groups"])
        self.assertIn("registry", r["selected_test_groups"])

    def test_full_categories_emit_full_sentinel(self):
        for p in ("core/entrypoint.py", "core/governance/validator.py",
                  ".github/workflows/release.yml", ".env",
                  "configs/businesses/registry.yaml"):
            self.assertEqual(cc([p])["selected_test_groups"], ["FULL"], p)

    def test_selected_groups_are_real_dirs(self):
        real = set(dr.TEST_GROUPS) | {dr.FULL}
        for p in ("configs/content_policy.yaml", "core/business_config/readiness.py",
                  "docs/a.md", "scripts/scheduler_setup.py"):
            for g in cc([p])["selected_test_groups"]:
                self.assertIn(g, real, f"{p}->{g}")


class AffectedBusinessTest(unittest.TestCase):
    def test_affected_business_and_service(self):
        r = cc(["configs/businesses/tachinomiya_notes.md", "docs/x.md"])
        self.assertIn("tachinomiya", r["affected_businesses"])
        self.assertIn("tachinomiya-ai", r["affected_services"])

    def test_no_registry_gives_empty(self):
        r = dr.classify_change(["core/entrypoint.py"], registry=None)
        self.assertEqual(r["affected_businesses"], [])
        self.assertEqual(r["affected_services"], [])


class ExistingHelpersUnchangedTest(unittest.TestCase):
    def test_classify_paths_still_works(self):
        self.assertEqual(dr.classify_paths(["docs/x.md"]), "MEDIUM")
        self.assertEqual(dr.classify_paths(["core/x.py"]), "HIGH")
        self.assertEqual(dr.classify_paths([".env"]), "CRITICAL")

    def test_scan_secret_still_boolean(self):
        self.assertIs(dr.scan_secret_lines("api_key = 'x'"), False)


if __name__ == "__main__":
    unittest.main()
