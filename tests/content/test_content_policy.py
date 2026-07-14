"""Tests: disable AI image generation across all businesses, keep LINE text.

Read-only / behavioural. No image API calls, no GCS writes, no LINE image
attach; text generation + LINE text delivery continue.
"""

import os
import sys
import tempfile
import textwrap
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core import content_policy as cp

ALL_BUSINESSES = ("beauty", "catering", "tachinomiya", "hinabe", "ryukyu_hinabe",
                  "pasta_pasta", "z1", "unknown", None)


class _RaiseClient:
    """OpenAI-like client whose images.generate must never be called."""
    class images:
        @staticmethod
        def generate(**kwargs):
            raise AssertionError("images.generate was CALLED")


def _write_policy(text):
    tmp = tempfile.mkdtemp()
    p = os.path.join(tmp, "configs", "content_policy.yaml")
    os.makedirs(os.path.dirname(p))
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(text))
    return tmp


class PolicyTest(unittest.TestCase):
    def test_01_image_gen_false_all_businesses(self):
        for b in ALL_BUSINESSES:
            self.assertFalse(cp.image_generation_enabled(b), b)

    def test_02_unknown_business_false(self):
        self.assertFalse(cp.image_generation_enabled("does_not_exist"))

    def test_03_fail_closed_on_bad_config(self):
        self.assertFalse(cp.image_generation_enabled(repo_root="/nonexistent-root"))
        self.assertFalse(cp.line_image_delivery_enabled(repo_root="/nonexistent-root"))
        # text stays on even on failure
        self.assertTrue(cp.text_generation_enabled(repo_root="/nonexistent-root"))

    def test_08_09_10_text_stays_on(self):
        for b in ALL_BUSINESSES:
            self.assertTrue(cp.text_generation_enabled(b), b)
            self.assertTrue(cp.line_text_delivery_enabled(b), b)

    def test_12_delivery_mode_text_only(self):
        for b in ALL_BUSINESSES:
            self.assertEqual(cp.delivery_mode(b), "TEXT_ONLY", b)

    def test_line_image_delivery_false(self):
        for b in ALL_BUSINESSES:
            self.assertFalse(cp.line_image_delivery_enabled(b), b)

    def test_cannot_enable_via_env_alone(self):
        # config says false → even with env true, image stays off
        os.environ["IMAGE_GENERATION_ENABLED"] = "true"
        try:
            self.assertFalse(cp.image_generation_enabled("beauty"))
        finally:
            os.environ.pop("IMAGE_GENERATION_ENABLED", None)

    def test_business_override_cannot_enable(self):
        root = _write_policy("""
            content_policy:
              image_generation_enabled: false
            businesses:
              beauty:
                image_generation_enabled: true
        """)
        os.environ["IMAGE_GENERATION_ENABLED"] = "true"
        try:
            # global false wins; business override cannot enable
            self.assertFalse(cp.image_generation_enabled("beauty", repo_root=root))
        finally:
            os.environ.pop("IMAGE_GENERATION_ENABLED", None)

    def test_re_enable_requires_config_and_env(self):
        # both config true AND env true → enabled (owner-controlled re-enable)
        root = _write_policy("""
            content_policy:
              image_generation_enabled: true
              line_image_delivery_enabled: true
        """)
        # without env → still off
        self.assertFalse(cp.image_generation_enabled("beauty", repo_root=root))
        os.environ["IMAGE_GENERATION_ENABLED"] = "true"
        try:
            self.assertTrue(cp.image_generation_enabled("beauty", repo_root=root))
        finally:
            os.environ.pop("IMAGE_GENERATION_ENABLED", None)
        # per-business false still restricts
        root2 = _write_policy("""
            content_policy:
              image_generation_enabled: true
            businesses:
              beauty:
                image_generation_enabled: false
        """)
        os.environ["IMAGE_GENERATION_ENABLED"] = "true"
        try:
            self.assertFalse(cp.image_generation_enabled("beauty", repo_root=root2))
        finally:
            os.environ.pop("IMAGE_GENERATION_ENABLED", None)


class EngineGuardTest(unittest.TestCase):
    def test_04_05_16_image_api_not_called_no_retry(self):
        import core.multi_business_content_engine as m
        import core.blog_image_generator as b
        # images.generate must NOT be called; returns cleanly (no retry loop reached)
        self.assertIsNone(m._generate_image_bytes("p", _RaiseClient()))
        self.assertEqual(b._generate_one_image("p", _RaiseClient()), (None, "IMAGE_GEN_DISABLED"))

    def test_06_no_gcs_write_real_or_ai(self):
        import core.multi_business_content_engine as m
        # real-image path returns None before any GCS work
        self.assertIsNone(m._fetch_real_image("beauty", "t", "g", "d", None, None))
        # AI path returns None → _upload_image never reached
        self.assertIsNone(m._generate_image_bytes("p", _RaiseClient()))

    def test_07_line_image_not_attached(self):
        import core.multi_business_content_engine as m
        import core.daily_line_distributor as d
        self.assertFalse(m._send_line_image("x" * 120, "http://u", ""))
        self.assertIsNone(d._send_line_image("x" * 120, "http://u"))

    def test_daily_image_gen_disabled(self):
        import core.daily_line_distributor as d
        self.assertEqual(d._generate_image_for_line("t", "b", "脱毛", "2026-07-14", "x"),
                         ("", "", ""))

    def test_11_no_exception_when_image_disabled(self):
        # guards return cleanly (no raise) so text-only flow succeeds
        import core.multi_business_content_engine as m
        try:
            m._generate_image_bytes("p", _RaiseClient())
            m._send_line_image("x" * 120, "http://u", "")
        except Exception as e:  # pragma: no cover
            self.fail(f"image guard raised: {e}")

    def test_08_line_text_send_not_guarded(self):
        # _send_line_text must NOT be gated by the image policy
        import inspect
        import core.multi_business_content_engine as m
        src = inspect.getsource(m._send_line_text)
        self.assertNotIn("content_policy", src)

    def test_16_no_network(self):
        import socket
        import core.multi_business_content_engine as m

        class N(socket.socket):
            def __init__(self, *a, **k):
                raise AssertionError("network attempted")
        orig = socket.socket
        socket.socket = N
        try:
            self.assertIsNone(m._generate_image_bytes("p", _RaiseClient()))
            self.assertFalse(m._send_line_image("x" * 120, "http://u", ""))
        finally:
            socket.socket = orig


class NoDestructiveChangeTest(unittest.TestCase):
    def test_13_14_15_no_delete_or_scheduler_in_guards(self):
        # the new content_policy module contains no delete / IMAGE_LIBRARY write /
        # scheduler change / secret read
        with open(os.path.join(_REPO_ROOT, "core", "content_policy.py"),
                  encoding="utf-8") as fh:
            src = fh.read().lower()
        for forbidden in ("delete", "scheduler", "upload_from_string", "images.generate",
                          "os.environ[", "api_key"):
            self.assertNotIn(forbidden, src, forbidden)


if __name__ == "__main__":
    unittest.main()
