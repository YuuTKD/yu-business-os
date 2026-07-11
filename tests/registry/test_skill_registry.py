"""Unit tests for the Skill Registry loader (Phase A).

Runs with stdlib unittest (``python3 -m unittest``) and is also pytest-compatible.
No network, no secrets, no SKILL.md execution.
"""

import os
import sys
import tempfile
import textwrap
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.registry.skill_registry import SkillRegistry
from core.registry.models import SkillStatus


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(text))


class FixtureRepo:
    """Build a throwaway repo root containing a skills registry."""

    def __init__(self, registry_text, md_files=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        _write(os.path.join(self.root, "configs", "skills", "registry.yaml"), registry_text)
        for rel in md_files or []:
            _write(os.path.join(self.root, rel), "# SKILL\n")

    def registry(self):
        return SkillRegistry(repo_root=self.root).load()

    def close(self):
        self.tmp.cleanup()


class SkillRegistryRealTest(unittest.TestCase):
    def setUp(self):
        self.reg = SkillRegistry().load()

    def test_01_loads_clean(self):
        self.assertIsNone(self.reg.load_error)
        self.assertGreaterEqual(len(self.reg.all_skills()), 8)

    def test_02_get_registered_skill(self):
        skill = self.reg.get_skill("pre-deploy-qa")
        self.assertIsNotNone(skill)
        self.assertTrue(skill.active)

    def test_03_unknown_skill_not_found(self):
        res = self.reg.resolve("does-not-exist")
        self.assertEqual(res.status, SkillStatus.NOT_FOUND.value)

    def test_05_skill_md_present_available(self):
        res = self.reg.resolve("pre-deploy-qa")
        self.assertEqual(res.status, SkillStatus.AVAILABLE.value)

    def test_skills_never_hold_elevated_permissions(self):
        for skill in self.reg.all_skills():
            self.assertFalse(skill.permissions.deploy, skill.id)
            self.assertFalse(skill.permissions.scheduler, skill.id)
            self.assertFalse(skill.permissions.secret_access, skill.id)


class SkillRegistryFixtureTest(unittest.TestCase):
    def test_04_inactive_skill_returns_inactive(self):
        repo = FixtureRepo("""
            version: 1
            skills:
              - id: dormant
                name: Dormant
                skill_md_path: ""
                fallback_behavior: LOGIC_DIRECT_APPLY
                active: false
        """)
        self.addCleanup(repo.close)
        res = repo.registry().resolve("dormant")
        self.assertEqual(res.status, SkillStatus.INACTIVE.value)

    def test_06_active_skill_without_md_falls_back_to_logic(self):
        repo = FixtureRepo("""
            version: 1
            skills:
              - id: logic-only
                name: Logic Only
                skill_md_path: ""
                fallback_behavior: LOGIC_DIRECT_APPLY
                active: true
        """)
        self.addCleanup(repo.close)
        res = repo.registry().resolve("logic-only")
        self.assertEqual(res.status, SkillStatus.FALLBACK_LOGIC.value)

    def test_06b_direct_md_fallback_when_md_exists(self):
        repo = FixtureRepo(
            """
            version: 1
            skills:
              - id: with-md
                name: With MD
                skill_md_path: skills/with-md/SKILL.md
                fallback_behavior: DIRECT_SKILL_MD
                active: true
            """,
            md_files=["skills/with-md/SKILL.md"],
        )
        self.addCleanup(repo.close)
        res = repo.registry().resolve("with-md")
        # md exists + active -> AVAILABLE
        self.assertEqual(res.status, SkillStatus.AVAILABLE.value)

    def test_07_repo_external_path_invalid_config(self):
        repo = FixtureRepo("""
            version: 1
            skills:
              - id: escaper
                name: Escaper
                skill_md_path: /etc/passwd
                fallback_behavior: DIRECT_SKILL_MD
                active: true
        """)
        self.addCleanup(repo.close)
        reg = repo.registry()
        res = reg.resolve("escaper")
        self.assertEqual(res.status, SkillStatus.INVALID_CONFIG.value)
        # Path escape is also flagged as a STOP-severity issue.
        self.assertTrue(any(i.field == "skill_md_path" for i in reg.issues()))

    def test_07b_path_traversal_rejected(self):
        repo = FixtureRepo("""
            version: 1
            skills:
              - id: traverse
                name: Traverse
                skill_md_path: "../../../etc/hosts"
                fallback_behavior: DIRECT_SKILL_MD
                active: true
        """)
        self.addCleanup(repo.close)
        res = repo.registry().resolve("traverse")
        self.assertEqual(res.status, SkillStatus.INVALID_CONFIG.value)

    def test_08_duplicate_id_flagged_and_invalid(self):
        repo = FixtureRepo("""
            version: 1
            skills:
              - id: twin
                name: Twin A
                active: true
              - id: twin
                name: Twin B
                active: true
        """)
        self.addCleanup(repo.close)
        reg = repo.registry()
        self.assertTrue(any("duplicate" in i.reason for i in reg.issues()))
        res = reg.resolve("twin")
        self.assertEqual(res.status, SkillStatus.INVALID_CONFIG.value)

    def test_missing_file_fails_safe(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        reg = SkillRegistry(repo_root=tmp.name).load()
        self.assertIsNotNone(reg.load_error)
        res = reg.resolve("anything")
        self.assertEqual(res.status, SkillStatus.INVALID_CONFIG.value)


if __name__ == "__main__":
    unittest.main()
