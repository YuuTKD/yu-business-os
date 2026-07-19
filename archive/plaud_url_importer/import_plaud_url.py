#!/usr/bin/env python3
"""PLAUD share-URL importer → GCS Knowledge OS (10_PLAUD).

Takes a PLAUD public share URL, extracts title / recorded_at / transcript /
summary, builds raw + processed Markdown, redacts secrets, flags PII, saves to
GCS (source of truth), and (optionally) triggers the existing Obsidian sync.

SECURITY (hard rules enforced here):
  * only https://web.plaud.ai/s/ URLs are accepted (else STOP),
  * the share TOKEN (after '::') is NEVER stored, printed, or logged,
  * the URL is masked in all output; recording_id (pre-'::') is the only id kept,
  * secrets → REDACTED (unredactable → STOP); PII is flagged (values not exposed
    in processed docs; raw transcript is preserved unmodified per spec),
  * never writes to the personal vault or Google Drive; GCS only,
  * never deletes; same recording_id is not re-saved (idempotent update only).

Modes: --plan (validate + id + paths + accessibility; NO body fetch, NO save)
       --apply (fetch + build + redact + save to GCS)
       --sync  (run the existing sync_knowledge_os.sh once, after apply)

The live transcript fetch requires a JS-rendering browser (the share page is a
SPA). If Playwright is unavailable or a login wall is detected, fetch STOPS with
a clear reason (no guessing, no auth bypass).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys

_THIS = os.path.abspath(__file__)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_THIS)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.governance import diff_risk  # secret patterns / boolean scan

SHARE_PREFIX = "https://web.plaud.ai/s/"
LOCAL_VAULT = os.path.expanduser("~/Documents/YU_HOLDINGS_Knowledge_OS")  # never written
GCS_ROOT = "gs://tree-beauty-blog-images/knowledge-os"
NO_DATA = "取得なし"
REDACTED = "REDACTED"

_SECRET_RE = re.compile("|".join(list(diff_risk.SECRET_LINE_PATTERNS) + [
    r"ya29\.[A-Za-z0-9_\-]{20,}", r"1//[A-Za-z0-9_\-]{20,}",
    r"Bearer\s+[A-Za-z0-9._\-]{20,}", r"AKIA[0-9A-Z]{16}",
]))
# PII detectors — used to FLAG (counts), never to print the matched value.
_PII = {
    "email": re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
    "phone": re.compile(r"(?<!\d)(?:0\d{1,4}[-（(]?\d{1,4}[-）)]?\d{3,4}|\+81[\d\-]{9,})(?!\d)"),
    "postal": re.compile(r"〒?\d{3}-\d{4}"),
}
_TYPE_HINTS = [
    ("decision", r"決定|決める|方針|GO|承認"),
    ("sales", r"商談|見積|受注|営業|提案|契約"),
    ("instruction", r"指示|お願い|やって|依頼|担当"),
    ("incident", r"障害|エラー|事故|クレーム|失敗|トラブル"),
    ("idea", r"アイデア|案|思いつき|やりたい|構想"),
    ("meeting", r"例会|会議|ミーティング|打ち合わせ"),
]


def validate_share_url(url: str) -> str:
    if not url or not url.startswith(SHARE_PREFIX):
        raise SystemExit(f"STOP: PLAUD 共有URL ({SHARE_PREFIX}…) 以外は処理しません。")
    return url


def recording_id(url: str) -> str:
    """Public share id = the path segment BEFORE '::'. The token (after '::') is
    never returned/stored."""
    path = url.split("/s/", 1)[1]
    return path.split("::", 1)[0]


def mask_url(url: str) -> str:
    """Return a safe representation: host + share id, token REDACTED."""
    try:
        rid = recording_id(url)
        return f"{SHARE_PREFIX}{rid}::{REDACTED}"
    except Exception:
        return f"{SHARE_PREFIX}{REDACTED}"


def redact(text: str):
    if not text:
        return text or "", 0
    count = 0

    def _s(m):
        nonlocal count
        count += 1
        return REDACTED

    return _SECRET_RE.sub(_s, text), count


def pii_flags(text: str) -> dict:
    """Return {category: count}. Values are NOT returned."""
    return {k: len(rx.findall(text or "")) for k, rx in _PII.items()}


def _mask_pii(text: str) -> str:
    out = text or ""
    for rx in _PII.values():
        out = rx.sub(REDACTED, out)
    return out


def classify_type(text: str) -> str:
    for name, pat in _TYPE_HINTS:
        if re.search(pat, text or ""):
            return name
    return "判定不能"


def dest_paths(rid: str, date: str) -> dict:
    y, m = date[:4], date[5:7]
    b = f"10_PLAUD"
    return {
        "raw": f"{b}/00_Raw_Transcripts/{y}/{m}/{date}_{rid}.md",
        "processed": f"{b}/01_Processed/{y}/{m}/{date}_{rid}.md",
        "philosophy": f"{b}/03_Philosophy_Candidates/{y}/{m}/{date}_{rid}.md",
        "task": f"{b}/04_Task_Candidates/{y}/{m}/{date}_{rid}.md",
        "summary": f"{b}/08_Daily_Summaries/{y}/{m}/{date}_PLAUD_SUMMARY.md",
        "log": f"{b}/09_Processing_Logs/{y}/{m}/{date}_{rid}.json",
    }


def build_raw_md(meta: dict, date: str, imported_at: str) -> str:
    t = meta.get("transcript") or NO_DATA
    return "\n".join([
        "---", "source: PLAUD", f"recording_id: {meta.get('recording_id','')}",
        f"recorded_at: {meta.get('recorded_at', NO_DATA)}",
        f"imported_at: {imported_at}", f"title: {meta.get('title', NO_DATA)}",
        f"business: {meta.get('business', NO_DATA)}",
        "type: raw-transcript", "status: observed", "source_url_masked: true", "---",
        "", f"# {meta.get('title', NO_DATA)}", "",
        "## PLAUD原本", "共有URLは保存しない（recording_id のみ）。", "",
        "## 録音情報", f"- recorded_at: {meta.get('recorded_at', NO_DATA)}",
        f"- business: {meta.get('business', NO_DATA)}", "",
        "## 文字起こし原文", "", t, "",   # preserved unmodified (secrets already redacted upstream)
        "## PLAUD要約", "", meta.get("summary") or NO_DATA, "",
        "## PLAUD会議議事録", "", meta.get("minutes") or NO_DATA, "",
        "## 話者情報", "", meta.get("speakers") or NO_DATA, "",
    ])


def build_processed_md(meta: dict, date: str, processed_at: str) -> str:
    body = meta.get("transcript") or ""
    return "\n".join([
        "---", "source: PLAUD", f"recording_id: {meta.get('recording_id','')}",
        f"recorded_at: {meta.get('recorded_at', NO_DATA)}",
        f"processed_at: {processed_at}", f"business: {meta.get('business', NO_DATA)}",
        f"type: {classify_type(body)}", "confidence: low", "status: observed", "---",
        "", f"# {meta.get('title', NO_DATA)}", "",
        "## 要約", meta.get("summary") or NO_DATA, "",
        "## 事実", f"- {NO_DATA}（自動抽出は行わず、原文 §文字起こし を参照）", "",
        "## 決定事項", f"- {NO_DATA}", "", "## タスク", f"- {NO_DATA}", "",
        "## 担当者・期限", f"- {NO_DATA}", "",
        "## 思想・価値観候補", f"- {NO_DATA}（observed のみ・confirmed 昇格は Yes 後）", "",
        "## 判断原則候補", f"- {NO_DATA}", "", "## SOP候補", f"- {NO_DATA}", "",
        "## 売上・利益への影響", f"- {NO_DATA}", "",
        "## ゆうさんの稼働削減への影響", f"- {NO_DATA}", "",
        "## 他事業への波及", f"- {NO_DATA}", "",
        "## 既存方針との一致", f"- {NO_DATA}", "", "## 既存方針との矛盾", f"- {NO_DATA}", "",
        "## 確認事項", "- [ ] Yes / No：（自動確定しない・observed）", "",
    ])


def _assert_safe_dest(dest_root: str):
    low = os.path.abspath(os.path.expanduser(dest_root)).lower()
    if low == os.path.abspath(LOCAL_VAULT).lower() \
       or "yu_holdings_knowledge_os" in low or "drive.google" in low \
       or "google drive" in low or "googledrive" in low or "/dropbox" in low:
        raise SystemExit(f"STOP: 個人Vault/Drive への保存は禁止: {dest_root}")


def _exists(dest_root: str, suffix: str, lister=None) -> bool:
    if lister is not None:
        return lister(suffix)
    if dest_root.startswith("gs://"):
        tgt = dest_root.rstrip("/") + "/" + suffix
        return subprocess.run(["gcloud", "storage", "ls", tgt],
                              capture_output=True).returncode == 0
    return os.path.isfile(os.path.join(dest_root, suffix))


def _write(dest_root: str, suffix: str, content: str) -> str:
    if dest_root.startswith("gs://"):
        tgt = dest_root.rstrip("/") + "/" + suffix
        p = subprocess.run(["gcloud", "storage", "cp", "-", tgt],
                           input=content, text=True, capture_output=True)
        if p.returncode != 0:
            raise SystemExit(f"STOP: GCS 保存失敗 {tgt}: {p.stderr.strip()[:200]}")
        return tgt
    tgt = os.path.join(dest_root, suffix)
    os.makedirs(os.path.dirname(tgt), exist_ok=True)
    with open(tgt, "w", encoding="utf-8") as fh:
        fh.write(content)
    return tgt


def fetch_transcript(url: str) -> dict:
    """Render the SPA and extract fields. STOPS (no guessing) if a JS browser is
    unavailable or a login wall is detected. Never bypasses auth/CAPTCHA."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:
        raise SystemExit("STOP: 文字起こし取得には JS レンダリング(Playwright)が必要です。"
                         "owner 環境で `pip install playwright && playwright install chromium` 後に再実行。")
    with sync_playwright() as p:  # pragma: no cover (requires browser + network)
        b = p.chromium.launch(headless=True)
        pg = b.new_page()
        pg.goto(url, wait_until="networkidle", timeout=60000)
        html = pg.content()
        if re.search(r"(login|sign in|ログイン)", html, re.I) and "transcript" not in html.lower():
            b.close()
            raise SystemExit("STOP: ログインが必要なページです（非公開データ取得はしません）。")
        title = (pg.title() or "").strip()
        text = pg.inner_text("body")
        b.close()
        return {"title": title, "transcript": text, "recorded_at": NO_DATA,
                "summary": NO_DATA, "minutes": NO_DATA, "speakers": NO_DATA}


def run(mode, url, dest_root=GCS_ROOT, date=None, lister=None, fetcher=fetch_transcript):
    validate_share_url(url)
    _assert_safe_dest(dest_root)
    rid = recording_id(url)
    date = date or datetime.date.today().strftime("%Y-%m-%d")
    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    paths = dest_paths(rid, date)
    result = {"mode": mode, "recording_id": rid, "masked_url": mask_url(url),
              "targets": paths, "written": [], "secrets_redacted": 0,
              "pii_flags": {}, "status": "PLANNED"}

    if mode == "plan":
        print(f"masked url : {mask_url(url)}")
        print(f"recording_id: {rid}")
        for k in ("raw", "processed", "log"):
            print(f"  would write: {dest_root.rstrip('/')}/{paths[k]}")
        print("body fetch : NOT performed in --plan（--apply で JS レンダリング取得）")
        print("token stored: NO / dest: GCS only / vault・Drive: 不使用")
        return result

    if mode != "apply":
        raise SystemExit(f"unknown mode: {mode}")

    # dedup: same recording_id already saved → do not duplicate (idempotent update only)
    if _exists(dest_root, paths["raw"], lister):
        result["status"] = "SKIPPED_DUPLICATE"
        print(json.dumps({"status": "SKIPPED_DUPLICATE", "recording_id": rid}, ensure_ascii=False))
        return result

    meta = fetcher(url)
    meta["recording_id"] = rid
    # redact secrets from every text field; fail-closed if a secret survives
    total = 0
    for key in ("title", "transcript", "summary", "minutes", "speakers", "recorded_at", "business"):
        red, n = redact(str(meta.get(key) or ""))
        total += n
        meta[key] = red
    result["secrets_redacted"] = total
    result["pii_flags"] = pii_flags(str(meta.get("transcript") or ""))

    raw_md = build_raw_md(meta, date, now)
    # processed side masks PII (raw is preserved unmodified per spec)
    pmeta = dict(meta)
    pmeta["transcript"] = _mask_pii(meta.get("transcript") or "")
    pmeta["summary"] = _mask_pii(meta.get("summary") or "")
    proc_md = build_processed_md(pmeta, date, now)

    for doc in (raw_md, proc_md):
        if diff_risk.scan_secret_lines(doc):
            raise SystemExit("STOP: 除外不能な secret を検出。保存中止。")

    result["written"].append(_write(dest_root, paths["raw"], raw_md))
    result["written"].append(_write(dest_root, paths["processed"], proc_md))
    result["status"] = "OK"
    print(json.dumps({"status": "OK", "recording_id": rid,
                      "secrets_redacted": total, "pii_flags": result["pii_flags"],
                      "written": result["written"]}, ensure_ascii=False))
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description="PLAUD share URL → GCS Knowledge OS")
    ap.add_argument("--url", default=os.environ.get("PLAUD_URL", ""))
    ap.add_argument("--mode", choices=["plan", "apply"], default="plan")
    ap.add_argument("--dest-root", default=GCS_ROOT)
    ap.add_argument("--date", default=None)
    args = ap.parse_args(argv)
    if not args.url:
        raise SystemExit("STOP: --url 未指定（環境変数 PLAUD_URL も可）。")
    run(args.mode, args.url, args.dest_root, args.date)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
