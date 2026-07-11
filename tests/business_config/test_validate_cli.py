"""CLI exit-code, migration-status, and safety tests (Phase B1)."""

import importlib
import importlib.util
import os
import socket
import sys
import tempfile
import textwrap
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.business_config.loader import BusinessConfigRegistry
from core.business_config.models import LoaderStatus

CLI_PATH = os.path.join(_REPO_ROOT, "scripts", "business_config", "validate_business_configs.py")
_spec = importlib.util.spec_from_file_location("validate_business_configs", CLI_PATH)
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)

_BREG = """BUSINESSES = {
    "alpha": {"business_type": "restaurant", "status": "active", "monthly_target": 800000,
              "cloud_run_service": "alpha-ai", "spreadsheet_id_env": "ALPHA_SPREADSHEET_ID",
              "line_channels": {"staff": {"env_key": "ALPHA_LINE_STAFF_TOKEN"}}},
}
"""
_CE = """_BUSINESS_CONFIGS = {
    "alpha": {"name": "Alpha", "line_token_env": "ALPHA_LINE_STAFF_TOKEN", "spreadsheet_id": "sheet"},
}
"""
_ET = 'BUSINESS_TARGETS = {"Alpha": {"target": 800000, "status": "active", "ss_env": "ALPHA_SPREADSHEET_ID"}}\n'

_REG = """
version: 1
businesses:
  - id: alpha
    slug: alpha
    display_name: Alpha
    business_type: restaurant
    status: ACTIVE
    active: true
    monthly_target: {target}
    migration_status: {migration}
    services:
      cloud_run_service: alpha-ai
    environment_variable_names:
      - ALPHA_SPREADSHEET_ID
      - ALPHA_LINE_STAFF_TOKEN
"""


def build_repo(target=800000, migration="SHADOW_DEFINED"):
    tmp = tempfile.mkdtemp()
    def w(rel, text):
        p = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
    w("configs/businesses/registry.yaml",
      textwrap.dedent(_REG).format(target=target, migration=migration))
    w("configs/business_registry.py", _BREG)
    w("core/multi_business_content_engine.py", _CE)
    w("ceo/executive_team.py", _ET)
    return tmp


class CliExitTest(unittest.TestCase):
    def test_36_match_go_exit_0(self):
        self.assertEqual(cli.run(repo_root=build_repo()), 0)

    def test_37_mismatch_fix_exit_1(self):
        self.assertEqual(cli.run(repo_root=build_repo(target=700000)), 1)

    def test_38_dangerous_stop_exit_2(self):
        self.assertEqual(cli.run(repo_root=build_repo(migration="PRODUCTION_CONNECTED")), 2)

    def test_39_internal_error_exit_3(self):
        # Force compare() to raise → CLI must fail closed with exit 3.
        import core.business_config.comparator as comp
        orig = comp.compare
        comp.compare = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            self.assertEqual(cli.run(repo_root=build_repo()), 3)
        finally:
            comp.compare = orig

    def test_real_repo_cli_runs(self):
        # Real repo has genuine legacy divergence → FIX (exit 1). Must not crash.
        self.assertIn(cli.run(), (0, 1))


class MigrationStatusTest(unittest.TestCase):
    def _reg(self, migration):
        tmp = tempfile.mkdtemp()
        p = os.path.join(tmp, "configs", "businesses", "registry.yaml")
        os.makedirs(os.path.dirname(p))
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent("""
                version: 1
                businesses:
                  - id: alpha
                    slug: alpha
                    display_name: Alpha
                    business_type: x
                    status: ACTIVE
                    active: true
                    migration_status: %s
            """ % migration))
        return BusinessConfigRegistry(repo_root=tmp).load()

    def test_33_shadow_defined_ok(self):
        self.assertEqual(self._reg("SHADOW_DEFINED").resolve("alpha"),
                         LoaderStatus.SHADOW_DEFINED.value)

    def test_34_verified_ok(self):
        self.assertEqual(self._reg("VERIFIED").resolve("alpha"),
                         LoaderStatus.VERIFIED.value)

    def test_35_production_connected_stop(self):
        self.assertEqual(self._reg("PRODUCTION_CONNECTED").validate().decision, "STOP")


class SafetyTest(unittest.TestCase):
    def test_44_no_network(self):
        class _NoNet(socket.socket):
            def __init__(self, *a, **k):
                raise AssertionError("network attempted")
        orig = socket.socket
        socket.socket = _NoNet
        try:
            self.assertEqual(cli.run(repo_root=build_repo()), 0)
        finally:
            socket.socket = orig

    def test_45_no_secret_in_output(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.run()
        low = buf.getvalue().lower()
        for needle in ("ghp_", "sk-", "bearer ", "private key"):
            self.assertNotIn(needle, low)

    def test_46_no_heavy_import_from_business_config(self):
        for m in ("core.multi_business_content_engine",):
            sys.modules.pop(m, None)
        importlib.import_module("core.business_config")
        importlib.import_module("configs.business_registry")
        self.assertNotIn("core.multi_business_content_engine", sys.modules)


if __name__ == "__main__":
    unittest.main()
