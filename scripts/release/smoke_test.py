#!/usr/bin/env python3
"""Release OS — read-only Smoke Test (Phase R3).

Verifies a candidate Cloud Run revision via its tag URL WITHOUT touching
production traffic. Only GET /health and /status are called (never POST, never
LINE/GBP/Sheets/GCS writes). Expected values come from configs/release/services.yaml
(the endpoint SSOT). Fail-closed: any unknown/missing signal → verdict ROLLBACK.

Never prints secret values (response scanned for secret-like patterns → boolean).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

_THIS = os.path.abspath(__file__)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_THIS)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.governance import diff_risk  # secret scan (boolean only)

try:
    import yaml as _yaml

    def _load_yaml(t):
        return _yaml.safe_load(t)
except Exception:  # pragma: no cover
    from core.registry._yaml_min import safe_load as _load_yaml

SERVICES_PATH = os.path.join("configs", "release", "services.yaml")


def load_service_spec(business, repo_root=None):
    root = os.path.abspath(repo_root or _REPO_ROOT)
    with open(os.path.join(root, SERVICES_PATH), encoding="utf-8") as fh:
        data = _load_yaml(fh.read())
    for s in (data or {}).get("services", []) or []:
        if isinstance(s, dict) and s.get("business") == business:
            return s
    return None


def evaluate(health_code, status_code, status_json, expected):
    """Pure smoke evaluation. Returns a result dict with verdict GO|ROLLBACK.

    Fail-closed: missing/unknown signals or any mismatch → ROLLBACK.
    """
    findings = []
    exp = expected or {}
    rel = (status_json or {}).get("release") if isinstance(status_json, dict) else None

    if health_code != 200:
        findings.append(f"health_code={health_code}")
    if status_code != 200:
        findings.append(f"status_code={status_code}")
    if not isinstance(status_json, dict):
        findings.append("status_body_not_json")
        rel = None

    # business identity
    biz = (status_json or {}).get("business") if isinstance(status_json, dict) else None
    if "business_identity" in exp and biz != exp["business_identity"]:
        findings.append(f"business_identity={biz!r}!={exp['business_identity']!r}")

    # content-policy flags (must be present and match; missing = fail-closed)
    if rel is None or not isinstance(rel, dict) or "delivery_mode" not in rel:
        findings.append("release_block_missing")
    else:
        checks = {
            "image_generation_enabled": exp.get("image_generation_enabled"),
            "line_text_delivery_enabled": exp.get("line_text_delivery_enabled"),
            "line_image_delivery_enabled": exp.get("line_image_delivery_enabled"),
            "delivery_mode": exp.get("delivery_mode"),
        }
        for k, want in checks.items():
            if want is None:
                continue
            got = rel.get(k)
            if got != want:
                findings.append(f"{k}={got!r}!={want!r}")

    # secret exposure in the response body
    secret = diff_risk.scan_secret_lines(json.dumps(status_json or {}, ensure_ascii=False))
    if secret:
        findings.append("secret_like_value_in_status")

    verdict = "GO" if not findings else "ROLLBACK"
    return {
        "health_code": health_code,
        "status_code": status_code,
        "business_identity": biz,
        "release": rel,
        "secret_exposure": bool(secret),
        "findings": findings,
        "verdict": verdict,
    }


def _identity_token(audience):
    """Mint a Cloud Run ID token for the given AUDIENCE. Never printed/returned to logs.

    Cloud Run authenticates the token audience against the SERVICE base URL — even
    when the request target is a traffic-tag (candidate) URL. Audience is required.
    """
    if not audience:
        return ""
    try:
        return subprocess.run(
            ["gcloud", "auth", "print-identity-token", f"--audiences={audience}"],
            capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


def _auth_get(url, audience):
    """Read-only GET with an audience-scoped ID token. Token is never printed."""
    tok = _identity_token(audience)
    headers = ["-H", f"Authorization: Bearer {tok}"] if tok else []
    p = subprocess.run(["curl", "-s", "-o", "-", "-w", "\n%{http_code}", *headers, url],
                       capture_output=True, text=True)
    out = p.stdout.rsplit("\n", 1)
    body = out[0] if len(out) == 2 else ""
    code = int(out[1]) if len(out) == 2 and out[1].strip().isdigit() else 0
    return code, body


def main(argv=None):
    ap = argparse.ArgumentParser(description="Release OS read-only smoke test")
    ap.add_argument("--business", default="catering")
    ap.add_argument("--candidate-url", required=True,
                    help="candidate revision tag URL (request target; NOT the audience)")
    ap.add_argument("--audience", required=True,
                    help="ID token audience = Cloud Run SERVICE base URL (not the tag URL)")
    args = ap.parse_args(argv)

    # fail-closed: audience must be the https service URL, distinct role from target.
    if not args.audience.startswith("https://"):
        print(json.dumps({"verdict": "ROLLBACK", "findings": ["audience_not_https"]}))
        return 1
    if not args.candidate_url.startswith("https://"):
        print(json.dumps({"verdict": "ROLLBACK", "findings": ["candidate_url_not_https"]}))
        return 1

    spec = load_service_spec(args.business)
    if not spec:
        print(json.dumps({"verdict": "ROLLBACK", "findings": ["unknown_business"]}))
        return 1
    ep = spec.get("endpoints", {})
    expected = spec.get("expected", {})

    aud = args.audience
    hc, _ = _auth_get(args.candidate_url.rstrip("/") + ep.get("health", "/health"), aud)
    sc, sbody = _auth_get(args.candidate_url.rstrip("/") + ep.get("status", "/status"), aud)
    try:
        sjson = json.loads(sbody)
    except Exception:
        sjson = None

    result = evaluate(hc, sc, sjson, expected)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
