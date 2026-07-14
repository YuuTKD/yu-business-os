"""Content policy SSOT — image generation / LINE image delivery kill-switch.

Single source of truth used by every content module to decide whether AI image
generation and LINE image delivery are allowed. **Default is OFF and fail-closed**
for images; text generation / LINE text delivery default ON.

Locks (image is enabled only if ALL hold):
    1. configs/content_policy.yaml says image_generation_enabled: true
    2. env IMAGE_GENERATION_ENABLED == "true"
    3. the per-business override does not set it false
Any load/parse error → image flags false (fail-closed). Per-business overrides
may only make a flag MORE restrictive; they can never enable it.

No secrets are read or logged here.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

try:
    import yaml as _yaml  # type: ignore

    def _load_yaml(text):
        return _yaml.safe_load(text)
except Exception:  # pragma: no cover
    from core.registry._yaml_min import safe_load as _load_yaml

IMAGE_GEN_ENV = "IMAGE_GENERATION_ENABLED"
LINE_IMAGE_ENV = "LINE_IMAGE_DELIVERY_ENABLED"

# Image flags default OFF (fail-closed); text flags default ON.
_DEFAULT = {
    "text_generation_enabled": True,
    "image_generation_enabled": False,
    "line_text_delivery_enabled": True,
    "line_image_delivery_enabled": False,
}


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


DEFAULT_POLICY_PATH = os.path.join("configs", "content_policy.yaml")


def _load(repo_root: Optional[str] = None) -> Tuple[Dict[str, bool], Dict[str, Any]]:
    """Return (global_policy, per_business_overrides). Fail-closed on error."""
    root = os.path.abspath(repo_root or _repo_root())
    path = os.path.join(root, DEFAULT_POLICY_PATH)
    policy = dict(_DEFAULT)
    businesses: Dict[str, Any] = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = _load_yaml(fh.read())
        if isinstance(data, dict):
            cp = data.get("content_policy")
            if isinstance(cp, dict):
                for k in _DEFAULT:
                    if k in cp:
                        policy[k] = bool(cp[k])
            biz = data.get("businesses")
            if isinstance(biz, dict):
                businesses = biz
    except Exception:
        # fail-closed: keep defaults (image off, text on)
        return dict(_DEFAULT), {}
    return policy, businesses


def _env_true(name: str) -> bool:
    return (os.getenv(name, "") or "").strip().lower() == "true"


def _biz_restricts(businesses: Dict[str, Any], business_id: Optional[str], flag: str) -> bool:
    if not business_id:
        return False
    ov = businesses.get(business_id)
    return isinstance(ov, dict) and ov.get(flag) is False


def image_generation_enabled(business_id: Optional[str] = None,
                             repo_root: Optional[str] = None) -> bool:
    """True only if config AND env enable it and the business does not restrict."""
    policy, businesses = _load(repo_root)
    if not policy.get("image_generation_enabled", False):
        return False
    if not _env_true(IMAGE_GEN_ENV):
        return False
    if _biz_restricts(businesses, business_id, "image_generation_enabled"):
        return False
    return True


def line_image_delivery_enabled(business_id: Optional[str] = None,
                                repo_root: Optional[str] = None) -> bool:
    """True only if config AND env enable it and the business does not restrict."""
    policy, businesses = _load(repo_root)
    if not policy.get("line_image_delivery_enabled", False):
        return False
    if not _env_true(LINE_IMAGE_ENV):
        return False
    if _biz_restricts(businesses, business_id, "line_image_delivery_enabled"):
        return False
    return True


def text_generation_enabled(business_id: Optional[str] = None,
                            repo_root: Optional[str] = None) -> bool:
    policy, _ = _load(repo_root)
    return bool(policy.get("text_generation_enabled", True))


def line_text_delivery_enabled(business_id: Optional[str] = None,
                               repo_root: Optional[str] = None) -> bool:
    policy, _ = _load(repo_root)
    return bool(policy.get("line_text_delivery_enabled", True))


def delivery_mode(business_id: Optional[str] = None, repo_root: Optional[str] = None) -> str:
    """TEXT_ONLY when images are off (current state); TEXT_AND_IMAGE otherwise."""
    return "TEXT_AND_IMAGE" if line_image_delivery_enabled(business_id, repo_root) else "TEXT_ONLY"
