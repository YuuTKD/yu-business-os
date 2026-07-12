"""Runtime main-path loader tests (Phase B2-3).

Covers feature flag, runtime source resolution, legacy fallback, rollback, the
business loader, and the entrypoint hook's fail-closed / no-shape-change
behaviour.
"""

import importlib.util
import os
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.business_config.runtime_loader import (
    apply_runtime_config, resolve_source, get_flag,
    LEGACY_ONLY, AUTO, OWNER_APPROVED,
)
from core.business_config import business_loader

TACHI = "tachinomiya"


class FeatureFlagTest(unittest.TestCase):
    def test_default_is_legacy_only(self):
        # No env → LEGACY_ONLY
        os.environ.pop("YU_CONFIG_RUNTIME_MODE", None)
        self.assertEqual(get_flag(), LEGACY_ONLY)

    def test_unknown_flag_defaults_legacy(self):
        d = resolve_source(TACHI, flag="TURBO")
        self.assertEqual(d["source"], "LEGACY")

    def test_legacy_only_source(self):
        d = resolve_source(TACHI, flag=LEGACY_ONLY)
        self.assertEqual(d["source"], "LEGACY")
        self.assertEqual(d["reason"], "flag_legacy_only")

    def test_auto_without_approval_legacy(self):
        d = resolve_source(TACHI, flag=AUTO, owner_approved=False)
        self.assertEqual(d["source"], "LEGACY")
        self.assertEqual(d["decision"], "OWNER_APPROVAL_REQUIRED")

    def test_auto_with_approval_ssot(self):
        d = resolve_source(TACHI, flag=AUTO, owner_approved=True)
        self.assertEqual(d["source"], "SSOT")

    def test_owner_approved_ssot(self):
        d = resolve_source(TACHI, flag=OWNER_APPROVED, owner_approved=True)
        self.assertEqual(d["source"], "SSOT")
        self.assertEqual(d["decision"], "GO")
        self.assertEqual(d["mismatch_count"], 0)


class ScopeTest(unittest.TestCase):
    def test_other_business_always_legacy(self):
        for b in ("catering", "beauty", "ryukyu_hinabe", "pasta_pasta", "z1"):
            d = resolve_source(b, flag=OWNER_APPROVED, owner_approved=True)
            self.assertEqual(d["source"], "LEGACY", b)
            self.assertEqual(d["reason"], "business_out_of_scope", b)


class FallbackTest(unittest.TestCase):
    def test_ssot_unavailable_falls_back(self):
        # legacy present but SSOT registry.yaml absent → genuine fallback
        import shutil
        tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(tmp, "configs"))
        shutil.copy(os.path.join(_REPO_ROOT, "configs", "business_registry.py"),
                    os.path.join(tmp, "configs", "business_registry.py"))
        d = resolve_source(TACHI, repo_root=tmp, flag=OWNER_APPROVED,
                           owner_approved=True)
        self.assertEqual(d["source"], "LEGACY")
        self.assertTrue(d["fallback_used"])


class RollbackTest(unittest.TestCase):
    def test_flag_flip_reverts_to_legacy(self):
        ssot = resolve_source(TACHI, flag=OWNER_APPROVED, owner_approved=True)
        self.assertEqual(ssot["source"], "SSOT")
        # one flag flip → back to legacy (rollback switch)
        legacy = resolve_source(TACHI, flag=LEGACY_ONLY)
        self.assertEqual(legacy["source"], "LEGACY")

    def test_env_rollback(self):
        os.environ["YU_CONFIG_RUNTIME_MODE"] = "OWNER_APPROVED"
        os.environ["YU_OWNER_APPROVED"] = "true"
        try:
            self.assertEqual(resolve_source(TACHI)["source"], "SSOT")
            os.environ["YU_CONFIG_RUNTIME_MODE"] = "LEGACY_ONLY"
            self.assertEqual(resolve_source(TACHI)["source"], "LEGACY")
        finally:
            os.environ.pop("YU_CONFIG_RUNTIME_MODE", None)
            os.environ.pop("YU_OWNER_APPROVED", None)


class ApplyHookTest(unittest.TestCase):
    def test_pass_through_identity(self):
        cfg = {"name": "TACHINOMIYA", "line_channels": {"staff": {}}}
        out = apply_runtime_config(TACHI, cfg, emit_log=False)
        self.assertIs(out, cfg)  # object unchanged, same identity

    def test_shape_unchanged_owner_approved(self):
        os.environ["YU_CONFIG_RUNTIME_MODE"] = "OWNER_APPROVED"
        os.environ["YU_OWNER_APPROVED"] = "true"
        try:
            cfg = {"name": "TACHINOMIYA", "monthly_target": 5500000}
            out = apply_runtime_config(TACHI, cfg, emit_log=False)
            self.assertIs(out, cfg)
            self.assertEqual(out, {"name": "TACHINOMIYA", "monthly_target": 5500000})
        finally:
            os.environ.pop("YU_CONFIG_RUNTIME_MODE", None)
            os.environ.pop("YU_OWNER_APPROVED", None)

    def test_fail_closed_never_raises(self):
        # bad repo_root shouldn't matter — hook must return legacy unchanged
        cfg = {"name": "X"}
        out = apply_runtime_config(TACHI, cfg, repo_root="/nonexistent", emit_log=False)
        self.assertIs(out, cfg)


class BusinessLoaderTest(unittest.TestCase):
    def test_load_returns_legacy_config(self):
        cfg = business_loader.load_business_config(TACHI, emit_log=False)
        self.assertEqual(cfg["name"], "TACHINOMIYA")
        # default flag → legacy dict, full shape preserved
        self.assertIn("line_channels", cfg)

    def test_describe_source_default_legacy(self):
        os.environ.pop("YU_CONFIG_RUNTIME_MODE", None)
        d = business_loader.describe_source(TACHI)
        self.assertEqual(d["source"], "LEGACY")


class SafetyTest(unittest.TestCase):
    def test_no_network(self):
        import socket

        class N(socket.socket):
            def __init__(self, *a, **k):
                raise AssertionError("net")
        orig = socket.socket
        socket.socket = N
        try:
            d = resolve_source(TACHI, flag=OWNER_APPROVED, owner_approved=True)
            self.assertEqual(d["source"], "SSOT")
        finally:
            socket.socket = orig

    def test_no_secret_in_decision(self):
        import re
        d = resolve_source(TACHI, flag=OWNER_APPROVED, owner_approved=True)
        blob = repr(d)
        for pat in (r"sk-[A-Za-z0-9]{20,}", r"ghp_[A-Za-z0-9]{20,}", r"-----BEGIN"):
            self.assertIsNone(re.search(pat, blob))


class CliTest(unittest.TestCase):
    def _cli(self):
        p = os.path.join(_REPO_ROOT, "scripts", "business_config",
                         "check_runtime_main_path.py")
        spec = importlib.util.spec_from_file_location("rmp", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_cli_legacy_only_rc0(self):
        self.assertEqual(self._cli().main(["--flag", "LEGACY_ONLY"]), 0)

    def test_cli_owner_approved_rc0(self):
        self.assertEqual(self._cli().main(["--flag", "OWNER_APPROVED", "--owner-approved"]), 0)


if __name__ == "__main__":
    unittest.main()
