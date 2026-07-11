"""Integration tests: validation CLI exit codes, parser, and safety guarantees."""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.registry._yaml_min import safe_load, YamlMinError

CLI = os.path.join(_REPO_ROOT, "scripts", "registry", "validate_registry.py")

_MIN_AGENTS = """
version: 1
agents:
  - id: a1
    name: A1
    active: false
"""
_MIN_POLICIES = """
version: 1
max_fix_attempts: 3
policies:
  - id: default_deny
    description: deny
    enforcement: STOP
"""


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(text))


def _run_cli(repo_root=None):
    env = dict(os.environ)
    if repo_root:
        env["YU_REGISTRY_ROOT"] = repo_root
    return subprocess.run(
        [sys.executable, CLI],
        cwd=_REPO_ROOT, env=env,
        capture_output=True, text=True,
    )


class CliExitCodeTest(unittest.TestCase):
    def test_30_real_registry_exit_zero(self):
        result = _run_cli()
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("RESULT: GO", result.stdout)

    def test_31_broken_registry_nonzero(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # Duplicate skill id -> FIX severity -> exit 1.
        _write(os.path.join(tmp.name, "configs", "skills", "registry.yaml"), """
            version: 1
            skills:
              - id: dup
                name: Dup A
                active: true
              - id: dup
                name: Dup B
                active: true
        """)
        _write(os.path.join(tmp.name, "configs", "agents", "registry.yaml"), _MIN_AGENTS)
        _write(os.path.join(tmp.name, "configs", "governance", "policies.yaml"), _MIN_POLICIES)
        result = _run_cli(repo_root=tmp.name)
        self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
        self.assertIn("RESULT: FIX", result.stdout)

    def test_31b_missing_config_stop_exit_two(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)  # empty repo -> everything missing -> STOP
        result = _run_cli(repo_root=tmp.name)
        self.assertEqual(result.returncode, 2, msg=result.stdout + result.stderr)
        self.assertIn("RESULT: STOP", result.stdout)


class SafetyTest(unittest.TestCase):
    def test_33_no_secret_patterns_in_output(self):
        result = _run_cli()
        lowered = result.stdout.lower()
        for needle in ("begin private key", "bearer ", "api_key=", "password="):
            self.assertNotIn(needle, lowered)

    def test_32_no_network_access(self):
        # Deny all socket creation, then exercise the full stack. If any code
        # tried to open a network connection this would raise.
        import socket

        class _NoNet(socket.socket):
            def __init__(self, *a, **k):
                raise AssertionError("network access attempted")

        original = socket.socket
        socket.socket = _NoNet
        try:
            from core.registry.skill_registry import SkillRegistry
            from core.registry.agent_registry import AgentRegistry
            from core.governance.validator import GovernanceValidator, GovernanceRequest
            skills = SkillRegistry().load()
            agents = AgentRegistry().load()
            gov = GovernanceValidator(skill_registry=skills, agent_registry=agents)
            gov.decide(GovernanceRequest(agent_id="codex-review-agent", action="audit_read"))
            self.assertIsNone(skills.load_error)
            self.assertIsNone(agents.load_error)
        finally:
            socket.socket = original

    def test_34_existing_namespaces_import_clean(self):
        # New packages import, and an existing pure-config module is unaffected.
        import importlib
        importlib.import_module("core.registry")
        importlib.import_module("core.governance")
        importlib.import_module("configs.business_registry")


class YamlSubsetParserTest(unittest.TestCase):
    def test_nested_maps_and_sequences(self):
        data = safe_load(textwrap.dedent("""
            version: 1
            items:
              - id: a
                flags:
                  read: true
                  write: false
                tags:
                  - x
                  - y
              - id: b
        """))
        self.assertEqual(data["version"], 1)
        self.assertEqual(len(data["items"]), 2)
        self.assertTrue(data["items"][0]["flags"]["read"])
        self.assertFalse(data["items"][0]["flags"]["write"])
        self.assertEqual(data["items"][0]["tags"], ["x", "y"])

    def test_empty_collections_and_scalars(self):
        data = safe_load(textwrap.dedent("""
            empty_list: []
            empty_map: {}
            quoted: "0.1.0"
            nothing:
            flag: false
        """))
        self.assertEqual(data["empty_list"], [])
        self.assertEqual(data["empty_map"], {})
        self.assertEqual(data["quoted"], "0.1.0")
        self.assertIsNone(data["nothing"])
        self.assertFalse(data["flag"])

    def test_tabs_rejected(self):
        with self.assertRaises(YamlMinError):
            safe_load("key:\n\t- bad")


if __name__ == "__main__":
    unittest.main()
