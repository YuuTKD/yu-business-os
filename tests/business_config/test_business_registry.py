"""Business Config Registry loader tests (Phase B1)."""

import os
import sys
import tempfile
import textwrap
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.business_config.loader import BusinessConfigRegistry
from core.business_config.models import LoaderStatus

VALID = """
version: 1
businesses:
  - id: alpha
    slug: alpha
    display_name: Alpha
    business_type: restaurant
    status: ACTIVE
    active: true
    migration_status: SHADOW_DEFINED
    environment_variable_names:
      - ALPHA_SPREADSHEET_ID
      - LINE_OWNER_TOKEN
"""


def build(text):
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "configs", "businesses", "registry.yaml")
    os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(text))
    return BusinessConfigRegistry(repo_root=tmp).load(), tmp


class RealRegistryTest(unittest.TestCase):
    def setUp(self):
        self.reg = BusinessConfigRegistry().load()

    def test_01_loads_clean(self):
        self.assertIsNone(self.reg.load_error)
        self.assertEqual(len(self.reg.list_businesses()), 6)

    def test_02_list_all(self):
        ids = {b.id for b in self.reg.list_businesses()}
        self.assertEqual(ids, {"beauty", "catering", "pasta_pasta", "z1",
                               "tachinomiya", "ryukyu_hinabe"})

    def test_03_get_by_id(self):
        self.assertEqual(self.reg.get_business("tachinomiya").display_name, "TACHINOMIYA")

    def test_04_get_by_slug(self):
        self.assertEqual(self.reg.get_business_by_slug("ryukyu_hinabe").business_type, "restaurant")

    def test_05_unknown_not_found(self):
        self.assertEqual(self.reg.resolve("ghost"), LoaderStatus.NOT_FOUND.value)

    def test_15_env_names_only_go(self):
        self.assertEqual(self.reg.validate().decision, "GO")
        # every env name is NAME-style, never a value
        for b in self.reg.list_businesses():
            for n in b.environment_variable_names:
                self.assertRegex(n, r"^[A-Z][A-Z0-9_]*$")


class FixtureTest(unittest.TestCase):
    def test_06_inactive(self):
        reg, _ = build(VALID.replace("status: ACTIVE\n    active: true",
                                     "status: INACTIVE\n    active: false"))
        self.assertEqual(reg.resolve("alpha"), LoaderStatus.INACTIVE.value)

    def test_07_duplicate_id_stop(self):
        reg, _ = build("""
            version: 1
            businesses:
              - id: dup
                slug: a
                display_name: A
                business_type: x
                status: ACTIVE
                migration_status: SHADOW_DEFINED
              - id: dup
                slug: b
                display_name: B
                business_type: x
                status: ACTIVE
                migration_status: SHADOW_DEFINED
        """)
        self.assertEqual(reg.validate().decision, "STOP")
        self.assertEqual(reg.resolve("dup"), LoaderStatus.INVALID_CONFIG.value)

    def test_08_duplicate_slug_stop(self):
        reg, _ = build("""
            version: 1
            businesses:
              - id: a
                slug: same
                display_name: A
                business_type: x
                status: ACTIVE
                migration_status: SHADOW_DEFINED
              - id: b
                slug: same
                display_name: B
                business_type: x
                status: ACTIVE
                migration_status: SHADOW_DEFINED
        """)
        self.assertEqual(reg.validate().decision, "STOP")

    def test_09_bad_structure_invalid_config(self):
        reg, _ = build("version: 1\nbusinesses: not_a_list\n")
        self.assertIsNotNone(reg.load_error)
        self.assertEqual(reg.resolve("x"), LoaderStatus.INVALID_CONFIG.value)

    def test_10_absolute_legacy_path_stop(self):
        reg, _ = build(VALID + "    legacy_sources:\n      - /etc/passwd::X\n")
        self.assertEqual(reg.validate().decision, "STOP")

    def test_11_path_traversal_stop(self):
        reg, _ = build(VALID + '    legacy_sources:\n      - "../../secret::X"\n')
        self.assertEqual(reg.validate().decision, "STOP")

    def test_12_secret_like_value_stop(self):
        # assemble at runtime so the test source has no literal secret
        secret = "ghp_" + ("A" * 30)
        reg, _ = build(VALID + f'    metadata:\n      note: "{secret}"\n')
        self.assertIsNotNone(reg.load_error)
        self.assertEqual(reg.resolve("alpha"), LoaderStatus.INVALID_CONFIG.value)

    def test_13_forbidden_field_token_stop(self):
        reg, _ = build(VALID + "    token: SOMETHING\n")
        self.assertEqual(reg.validate().decision, "STOP")

    def test_14_forbidden_field_api_key_stop(self):
        reg, _ = build(VALID + "    api_key: SOMETHING\n")
        self.assertEqual(reg.validate().decision, "STOP")

    def test_env_value_instead_of_name_stop(self):
        secret = "sk-" + ("b" * 30)
        reg, _ = build("""
            version: 1
            businesses:
              - id: alpha
                slug: alpha
                display_name: Alpha
                business_type: x
                status: ACTIVE
                migration_status: SHADOW_DEFINED
                environment_variable_names:
                  - "%s"
        """ % secret)
        # secret-like value scanned at file level → STOP
        self.assertEqual(reg.validate().decision, "STOP")


if __name__ == "__main__":
    unittest.main()
