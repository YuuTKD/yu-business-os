#!/usr/bin/env python3
"""PLAUD transcript FILE → GCS Knowledge OS (10_PLAUD).

Give a downloaded transcript file (.txt/.md/.docx/.pdf/.csv, optional .rtf/.json);
this extracts the text, builds raw + processed Markdown, classifies the business,
dedups by SHA-256, saves to GCS (source of truth), updates INDEX.md, and (with
--sync) triggers the existing Obsidian sync. No scraping, no URL, no Playwright.

Rules: raw = original text unmodified (severe secret → STOP before save);
processed masks PII/secrets; never writes to the personal vault or Google Drive;
never deletes; same file (SHA-256) is not re-saved. Logs never contain the raw
text or secret values.
"""

from __future__ import annotations

import argparse
import csv as _csv
import datetime
import hashlib
import io
import json
import os
import re
import subprocess
import sys

_THIS = os.path.abspath(__file__)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_THIS)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.governance import diff_risk

GCS_ROOT = "gs://tree-beauty-blog-images/knowledge-os"
LOCAL_VAULT = os.path.expanduser("~/Documents/YU_HOLDINGS_Knowledge_OS")
PLAUD = "10_PLAUD"
NO_DATA = "取得なし"
REDACTED = "REDACTED"
SUPPORTED = (".txt", ".md", ".docx", ".pdf", ".csv", ".rtf", ".json")

_SECRET_RE = re.compile("|".join(list(diff_risk.SECRET_LINE_PATTERNS) + [
    r"ya29\.[A-Za-z0-9_\-]{20,}", r"1//[A-Za-z0-9_\-]{20,}",
    r"Bearer\s+[A-Za-z0-9._\-]{20,}", r"AKIA[0-9A-Z]{16}",
    r"-----BEGIN[ A-Z0-9]*PRIVATE KEY-----",
]))
_PII = {
    "email": re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
    "phone": re.compile(r"(?<!\d)(?:0\d{1,4}[-（(]?\d{1,4}[-）)]?\d{3,4}|\+81[\d\-]{9,})(?!\d)"),
    "postal": re.compile(r"〒?\d{3}-\d{4}"),
}

BUSINESSES = ["TACHINOMIYA", "Catering", "Tree Beauty", "コンサル", "AIネットビジネス",
              "琉球火鍋", "東町", "投資", "パーソナル", "全事業", "未分類"]
_BIZ_HINTS = {
    "TACHINOMIYA": r"立ち飲み|タチノミヤ|tachinomiya",
    "Catering": r"ケータリング|catering|仕出し",
    "Tree Beauty": r"tree ?beauty|脱毛|ビューティ|サロン",
    "コンサル": r"コンサル|consult",
    "AIネットビジネス": r"ai.?ネット|ネットビジネス|物販|せどり",
    "琉球火鍋": r"琉球火鍋|火鍋|hot ?pot",
    "東町": r"東町",
    "投資": r"投資|株|不動産|invest",
}
_TYPE_HINTS = [
    ("decision", r"決定|方針|承認|GO"), ("sales", r"商談|見積|受注|営業|提案"),
    ("instruction", r"指示|依頼|お願い|担当"), ("incident", r"障害|エラー|事故|クレーム|トラブル"),
    ("idea", r"アイデア|案|構想"), ("meeting", r"例会|会議|ミーティング|打ち合わせ|議事"),
]


# ── extraction ────────────────────────────────────────────────────────────────
def _read_text(path: str) -> str:
    with open(path, "rb") as fh:
        raw = fh.read()
    for enc in ("utf-8", "utf-8-sig", "cp932", "shift_jis"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _csv_to_md(path: str) -> str:
    rows = list(_csv.reader(io.StringIO(_read_text(path))))
    if not rows:
        return ""
    out = ["| " + " | ".join(rows[0]) + " |",
           "| " + " | ".join(["---"] * len(rows[0])) + " |"]
    for r in rows[1:]:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def _json_to_text(path: str) -> str:
    try:
        data = json.loads(_read_text(path))
    except Exception:
        return _read_text(path)
    return json.dumps(data, ensure_ascii=False, indent=2)


def _docx_to_text(path: str) -> str:
    try:
        import docx  # type: ignore
    except Exception:
        raise SystemExit("STOP: .docx 取込には python-docx が必要です。"
                         "`pip install python-docx` 後に再実行してください。")
    d = docx.Document(path)
    return "\n".join(p.text for p in d.paragraphs)


def _pdf_to_text(path: str) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        raise SystemExit("STOP: .pdf 取込には pypdf が必要です。`pip install pypdf` 後に再実行。")
    reader = PdfReader(path)
    text = "\n".join((pg.extract_text() or "") for pg in reader.pages)
    if not text.strip():
        raise SystemExit("STOP: テキスト埋込みのない画像PDFです（OCR は使用しません）。")
    return text


def _rtf_to_text(path: str) -> str:
    try:
        from striprtf.striprtf import rtf_to_text  # type: ignore
    except Exception:
        raise SystemExit("STOP: .rtf 取込には striprtf が必要です。`pip install striprtf` 後に再実行。")
    return rtf_to_text(_read_text(path))


def extract_text(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED:
        raise SystemExit(f"STOP: 未対応形式です（{ext}）。対応: {', '.join(SUPPORTED)}")
    if ext in (".txt", ".md"):
        return _read_text(path)
    if ext == ".csv":
        return _csv_to_md(path)
    if ext == ".json":
        return _json_to_text(path)
    if ext == ".docx":
        return _docx_to_text(path)
    if ext == ".pdf":
        return _pdf_to_text(path)
    if ext == ".rtf":
        return _rtf_to_text(path)
    raise SystemExit(f"STOP: 未対応形式（{ext}）")


# ── helpers ───────────────────────────────────────────────────────────────────
def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sanitize_title(title: str) -> str:
    t = re.sub(r"[\\/:*?\"<>|#\[\]]+", "", (title or "").strip())
    t = re.sub(r"\s+", "_", t)
    return (t or "untitled")[:60]


def guess_title(text: str, filename: str) -> str:
    for line in (text or "").splitlines():
        s = line.strip().lstrip("# ").strip()
        if s:
            return s[:80]
    return os.path.splitext(os.path.basename(filename))[0]


def guess_recorded_at(text: str, filename: str) -> str:
    for src in (filename, text or ""):
        m = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", src)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return NO_DATA


def classify_business(text: str, override: str = "") -> str:
    if override:
        for b in BUSINESSES:
            if override.strip().lower() == b.lower() or override.strip() == b:
                return b
        return override.strip()  # user-specified name is authoritative
    for b, pat in _BIZ_HINTS.items():
        if re.search(pat, text or "", re.I):
            return b
    return "未分類"


def classify_type(text: str) -> str:
    for name, pat in _TYPE_HINTS:
        if re.search(pat, text or ""):
            return name
    return "meeting"


def tags_for(business: str, ttype: str) -> list:
    biz_tag = re.sub(r"[^a-z0-9\-]+", "-", business.lower()) or "unclassified"
    tags = ["#plaud", f"#{ttype}", f"#biz-{biz_tag}"]
    return tags


def redact(text: str):
    if not text:
        return text or "", 0
    c = 0

    def _s(m):
        nonlocal c
        c += 1
        return REDACTED

    return _SECRET_RE.sub(_s, text), c


def pii_flags(text: str) -> dict:
    return {k: len(rx.findall(text or "")) for k, rx in _PII.items()}


def mask_pii(text: str) -> str:
    out = text or ""
    for rx in _PII.values():
        out = rx.sub(REDACTED, out)
    return out


def file_id(sha: str) -> str:
    return sha[:6]


def out_filename(date: str, title: str, sha: str) -> str:
    return f"{date}_{sanitize_title(title)}_{file_id(sha)}.md"


def dest_paths(date: str, fname: str, business: str) -> dict:
    y, m = date[:4], date[5:7]
    biz = sanitize_title(business)
    return {
        "raw": f"{PLAUD}/00_Raw_Transcripts/{y}/{m}/{fname}",
        "processed": f"{PLAUD}/01_Processed/{y}/{m}/{fname}",
        "by_business": f"{PLAUD}/02_By_Business/{biz}/{fname}",
        "log": f"{PLAUD}/09_Processing_Logs/{y}/{m}/{fname}.json",
        "index": f"{PLAUD}/INDEX.md",
    }


def build_raw_md(meta: dict) -> str:
    return "\n".join([
        "---", "source: PLAUD", "source_type: uploaded-file",
        f"source_filename: {meta['source_filename']}", f"file_sha256: {meta['sha']}",
        f"recorded_at: {meta['recorded_at']}", f"imported_at: {meta['imported_at']}",
        f"title: {meta['title']}", f"business: {meta['business']}", "status: observed", "---",
        "", " ".join(meta["tags"]), "", f"# {meta['title']}", "",
        "## 元ファイル情報",
        f"- ファイル名：{meta['source_filename']}", f"- 形式：{meta['ext']}",
        f"- 取込日時：{meta['imported_at']}", f"- SHA-256：{meta['sha']}", "",
        "## 文字起こし原文", "", meta["text"], "",   # unmodified (secrets already checked)
        "## 元ファイル備考", f"- 事業分類：{meta['business']}", "",
    ])


def build_processed_md(meta: dict) -> str:
    summary = mask_pii(meta["text"])[:300]
    return "\n".join([
        "---", "source: PLAUD", "source_type: uploaded-file",
        f"title: {meta['title']}", f"business: {meta['business']}",
        f"type: {meta['type']}", "status: observed", "confidence: low", "---",
        "", " ".join(meta["tags"]), "", f"# {meta['title']}", "",
        "## 3行要約", f"- {NO_DATA}（自動確定しない・原文 raw を参照）", "",
        "## 詳細要約", f"{NO_DATA}", "",
        "## 事実", f"- {NO_DATA}", "", "## 決定事項", f"- {NO_DATA}", "",
        "## 保留事項", f"- {NO_DATA}", "", "## タスク", "",
        "| タスク | 担当 | 期限 | 状態 |", "|---|---|---|---|", "| (未抽出) |  |  | observed |", "",
        "## 数値・KPI", f"- {NO_DATA}", "", "## 人物・組織", f"- {NO_DATA}（PII マスク）", "",
        "## 思想・価値観候補", f"- {NO_DATA}（observed・confirmed 昇格は Yes 後）", "",
        "## 判断原則候補", f"- {NO_DATA}", "", "## SOP候補", f"- {NO_DATA}", "",
        "## 売上・利益への影響", f"- {NO_DATA}", "",
        "## ゆうさんの稼働削減への影響", f"- {NO_DATA}", "",
        "## 他事業への波及", f"- {NO_DATA}", "",
        "## 既存方針との一致", f"- {NO_DATA}", "", "## 既存方針との矛盾", f"- {NO_DATA}", "",
        "## Yes / No確認事項", "- [ ] Yes / No：（自動確定しない）", "",
    ])


def update_index(existing: str, title: str, fname: str, business: str) -> str:
    """Prepend a wikilink to 最新取込 (cap 20); keep business/type nav. Pure."""
    link = f"- [[{fname[:-3]}]] — {business}"
    recent = []
    if existing:
        for line in existing.splitlines():
            if line.startswith("- [[") and "]]" in line:
                recent.append(line)
    recent = [link] + [r for r in recent if r != link]
    recent = recent[:20]
    lines = ["# PLAUD Knowledge Index", "", "## 最新取込", *recent, "",
             "## 事業別（タグ検索）"]
    for b in BUSINESSES:
        biz_tag = re.sub(r"[^a-z0-9\-]+", "-", b.lower()) or "unclassified"
        lines.append(f"- {b} → `#biz-{biz_tag}`")
    lines += ["", "## 種類別（タグ検索）",
              "- 会議 `#meeting` / 決定 `#decision` / タスク `#task` /",
              "  思想候補 `#philosophy-candidate` / SOP `#sop-candidate` / 売上KPI `#kpi`",
              "", "## 月別", "- `10_PLAUD/00_Raw_Transcripts/YYYY/MM/` を参照", ""]
    return "\n".join(lines)


# ── IO ────────────────────────────────────────────────────────────────────────
def _assert_safe_dest(dest_root: str):
    low = os.path.abspath(os.path.expanduser(dest_root)).lower()
    if low == os.path.abspath(LOCAL_VAULT).lower() or "yu_holdings_knowledge_os" in low \
       or "google drive" in low or "googledrive" in low or "drive.google" in low or "/dropbox" in low:
        raise SystemExit(f"STOP: 個人Vault/Drive への保存は禁止: {dest_root}")


def _exists(dest_root, suffix, lister=None):
    if lister is not None:
        return lister(suffix)
    if dest_root.startswith("gs://"):
        return subprocess.run(["gcloud", "storage", "ls", dest_root.rstrip('/') + '/' + suffix],
                              capture_output=True).returncode == 0
    return os.path.isfile(os.path.join(dest_root, suffix))


def _read(dest_root, suffix, reader=None):
    if reader is not None:
        return reader(suffix)
    if dest_root.startswith("gs://"):
        p = subprocess.run(["gcloud", "storage", "cat", dest_root.rstrip('/') + '/' + suffix],
                           capture_output=True, text=True)
        return p.stdout if p.returncode == 0 else ""
    fp = os.path.join(dest_root, suffix)
    return open(fp, encoding="utf-8").read() if os.path.isfile(fp) else ""


def _write(dest_root, suffix, content):
    if dest_root.startswith("gs://"):
        tgt = dest_root.rstrip("/") + "/" + suffix
        p = subprocess.run(["gcloud", "storage", "cp", "-", tgt], input=content, text=True,
                           capture_output=True)
        if p.returncode != 0:
            raise SystemExit(f"STOP: GCS 保存失敗 {tgt}: {p.stderr.strip()[:200]}")
        return tgt
    tgt = os.path.join(dest_root, suffix)
    os.makedirs(os.path.dirname(tgt), exist_ok=True)
    with open(tgt, "w", encoding="utf-8") as fh:
        fh.write(content)
    return tgt


def run(mode, path, dest_root=GCS_ROOT, business="", title="", date=None,
        lister=None, reader=None, log_path=None):
    if not path or not os.path.isfile(path):
        raise SystemExit(f"STOP: ファイルが存在しません: {path}")
    _assert_safe_dest(dest_root)
    ext = os.path.splitext(path)[1].lower()
    text = extract_text(path)
    if not (text and text.strip()):
        raise SystemExit("STOP: ファイル内容が空です。")

    sha = sha256_file(path)
    date = date or datetime.date.today().strftime("%Y-%m-%d")
    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    # user-provided title wins; an auto-derived title is secret-redacted AND
    # PII-masked (it becomes the filename / heading / INDEX link and must not leak
    # secrets or personal data).
    ttl = title.strip() or mask_pii(redact(guess_title(text, path))[0])
    biz = classify_business(text, business)
    ttype = classify_type(text)
    fname = out_filename(guess_recorded_at(text, path).replace(NO_DATA, date)[:10]
                         if guess_recorded_at(text, path) != NO_DATA else date, ttl, sha)
    paths = dest_paths(date, fname, biz)
    result = {"mode": mode, "sha8": sha[:8], "filename": fname, "business": biz,
              "type": ttype, "chars": len(text), "targets": paths, "written": [],
              "secrets_redacted": 0, "pii_flags": {}, "status": "PLANNED"}

    if mode == "plan":
        print(f"file      : {os.path.basename(path)} ({ext}, {len(text)} chars)")
        print(f"sha256(8) : {sha[:8]}")
        print(f"title     : {ttl}")
        print(f"business  : {biz} / type: {ttype}")
        for k in ("raw", "processed", "by_business"):
            print(f"  would write: {dest_root.rstrip('/')}/{paths[k]}")
        print("dest: GCS only / vault・Drive 不使用 / 削除なし")
        return result

    if mode != "apply":
        raise SystemExit(f"unknown mode: {mode}")

    # dedup by SHA (encoded in the filename) — same file not re-saved
    if _exists(dest_root, paths["raw"], lister):
        result["status"] = "SKIPPED_DUPLICATE"
        print(json.dumps({"status": "SKIPPED_DUPLICATE", "sha8": sha[:8]}, ensure_ascii=False))
        return result

    red_text, n = redact(text)
    result["secrets_redacted"] = n
    result["pii_flags"] = pii_flags(text)
    # severe secret (private key) surviving in RAW → STOP before saving raw
    if diff_risk.scan_secret_lines(red_text):
        raise SystemExit("STOP: 除外不能な重大 secret を検出。保存中止。")

    meta = {"source_filename": os.path.basename(path), "sha": sha, "ext": ext,
            "recorded_at": guess_recorded_at(text, path), "imported_at": now,
            "title": ttl, "business": biz, "type": ttype,
            "text": red_text, "tags": tags_for(biz, ttype)}
    raw_md = build_raw_md(meta)
    proc_md = build_processed_md(meta)
    for doc in (raw_md, proc_md):
        if diff_risk.scan_secret_lines(doc):
            raise SystemExit("STOP: 生成 Markdown に secret 残存。保存中止。")

    result["written"].append(_write(dest_root, paths["raw"], raw_md))
    result["written"].append(_write(dest_root, paths["processed"], proc_md))
    result["written"].append(_write(dest_root, paths["by_business"], proc_md))
    idx = update_index(_read(dest_root, paths["index"], reader), ttl, fname, biz)
    result["written"].append(_write(dest_root, paths["index"], idx))
    result["status"] = "OK"

    if log_path:
        try:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"at": now, "file": os.path.basename(path),
                                     "ext": ext, "sha8": sha[:8], "chars": len(text),
                                     "written": result["written"],
                                     "secrets_redacted": n}, ensure_ascii=False) + "\n")
        except Exception:
            pass

    print(json.dumps({"status": "OK", "filename": fname, "business": biz,
                      "secrets_redacted": n, "pii_flags": result["pii_flags"],
                      "written": result["written"]}, ensure_ascii=False))
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description="PLAUD transcript file → GCS Knowledge OS")
    ap.add_argument("--file", required=True)
    ap.add_argument("--mode", choices=["plan", "apply"], default="plan")
    ap.add_argument("--dest-root", default=GCS_ROOT)
    ap.add_argument("--business", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--date", default=None)
    ap.add_argument("--log", default=os.path.join(_REPO_ROOT, "logs", "plaud_file_import.log"))
    args = ap.parse_args(argv)
    run(args.mode, args.file, args.dest_root, args.business, args.title, args.date,
        log_path=args.log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
