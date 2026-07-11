"""Legacy adapter tests (Phase B1) — static read, no import/exec, no network."""

import os
import re
import sys
import tempfile
import textwrap
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.business_config.legacy_adapter import LegacyAdapter, extract_dict_literal


class RealLegacyTest(unittest.TestCase):
    def setUp(self):
        self.adapter = LegacyAdapter()

    def test_16_business_registry_read(self):
        src = self.adapter.business_registry()
        self.assertIsNone(src.error)
        self.assertEqual(len(src.businesses), 6)
        self.assertIn("tachinomiya", src.businesses)

    def test_17_no_import_side_effect(self):
        # The content engine is read via AST, never imported.
        sys.modules.pop("core.multi_business_content_engine", None)
        self.adapter.content_engine()
        self.assertNotIn("core.multi_business_content_engine", sys.modules)

    def test_18_no_exec_or_eval(self):
        src_path = os.path.join(_REPO_ROOT, "core", "business_config", "legacy_adapter.py")
        code = open(src_path, encoding="utf-8").read()
        # bare eval(/exec( — but literal_eval( is allowed
        self.assertIsNone(re.search(r"(?<![_.\w])eval\(", code))
        self.assertIsNone(re.search(r"(?<![_.\w])exec\(", code))

    def test_19_no_network(self):
        import socket

        class _NoNet(socket.socket):
            def __init__(self, *a, **k):
                raise AssertionError("network attempted")
        orig = socket.socket
        socket.socket = _NoNet
        try:
            for s in self.adapter.all_sources():
                self.assertTrue(s.businesses or s.error is not None)
        finally:
            socket.socket = orig

    def test_20_content_engine_lists_legacy_alias(self):
        src = self.adapter.content_engine()
        self.assertIsNone(src.error)
        # both the alias and canonical key exist in the legacy source
        self.assertIn("hinabe", src.businesses)
        self.assertIn("ryukyu_hinabe", src.businesses)


class BadFormatTest(unittest.TestCase):
    def test_21_non_literal_raises(self):
        tmp = tempfile.mkdtemp()
        p = os.path.join(tmp, "mod.py")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("X = make_config()\n")
        with self.assertRaises(ValueError):
            extract_dict_literal(p, "X")

    def test_21b_missing_var_raises(self):
        tmp = tempfile.mkdtemp()
        p = os.path.join(tmp, "mod.py")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("Y = {'a': 1}\n")
        with self.assertRaises(ValueError):
            extract_dict_literal(p, "X")

    def test_adapter_surfaces_error(self):
        tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(tmp, "configs"))
        with open(os.path.join(tmp, "configs", "business_registry.py"), "w") as fh:
            fh.write("BUSINESSES = compute()\n")
        src = LegacyAdapter(repo_root=tmp).business_registry()
        self.assertIsNotNone(src.error)
        self.assertEqual(src.businesses, {})


if __name__ == "__main__":
    unittest.main()
