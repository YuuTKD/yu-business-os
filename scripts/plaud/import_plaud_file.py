#!/usr/bin/env python3
"""PLAUD transcript FILE → Obsidian Vault (10_PLAUD) — direct save.

Give a downloaded transcript file (.txt/.md/.docx/.pdf/.csv, optional .rtf/.json).
This extracts the text, builds raw + processed Markdown, classifies the business,
dedups by SHA-256, saves DIRECTLY into the Obsidian vault's 10_PLAUD folder, adds
internal links (decisions / tasks / philosophy / meeting / by-business / by-month),
and updates INDEX.md. No GCS, no URL, no Playwright, no scraping.

Rules: raw text saved unmodified (severe secret → STOP before save); processed
masks PII/secrets; title/filename secret+PII masked; never deletes/overwrites past
files; same SHA-256 → SKIPPED_DUPLICATE. Logs never contain the body/secret/PII.
Personal info stays inside the vault (no external send / SNS / reuse).
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
import sys

_THIS = os.path.abspath(__file__)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_THIS)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.governance import diff_risk

VAULT_PLAUD = os.path.expanduser("~/Documents/YU_HOLDINGS_Knowledge_OS/10_PLAUD")
NO_DATA = "取得なし"
REDACTED = "REDACTED"
SUPPORTED = (".txt", ".md", ".docx", ".pdf", ".csv", ".rtf", ".json")

# Japanese folder layout inside 10_PLAUD/
D_RAW = "01_文字起こし原文"
D_PROC = "02_整理済み"
D_BIZ = "03_事業別"
D_DECISION = "04_決定事項"
D_TASK = "05_タスク"
D_PHILO = "06_思想候補"
D_MEETING = "07_会議議事録"
D_MONTH = "08_月別"
D_LOG = "09_取込ログ"

_SECRET_RE = re.compile("|".join(list(diff_risk.SECRET_LINE_PATTERNS) + [
    r"ya29\.[A-Za-z0-9_\-]{20,}", r"1//[A-Za-z0-9_\-]{20,}",
    r"Bearer\s+[A-Za-z0-9._\-]{20,}", r"AKIA[0-9A-Z]{16}",
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
    "コンサル": r"コンサル|consult", "AIネットビジネス": r"ai.?ネット|ネットビジネス|物販|せどり",
    "琉球火鍋": r"琉球火鍋|火鍋|hot ?pot", "東町": r"東町", "投資": r"投資|株|不動産|invest",
}
_HAS_DECISION = r"決定|決めた|方針|承認|GO"
_HAS_TASK = r"タスク|担当|期限|対応する|やる"
_HAS_PHILO = r"思想|価値観|信念|大事|重視|べき|哲学"
_HAS_MEETING = r"会議|例会|議事|打ち合わせ|ミーティング"


# ── extraction ────────────────────────────────────────────────────────────────
def _read_text(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    for enc in ("utf-8", "utf-8-sig", "cp932", "shift_jis"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _csv_to_md(path):
    rows = list(_csv.reader(io.StringIO(_read_text(path))))
    if not rows:
        return ""
    out = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * len(rows[0])) + " |"]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(out)


def _json_to_text(path):
    try:
        return json.dumps(json.loads(_read_text(path)), ensure_ascii=False, indent=2)
    except Exception:
        return _read_text(path)


def _docx_to_text(path):
    try:
        import docx  # type: ignore
    except Exception:
        raise SystemExit("STOP: .docx には python-docx が必要です（pip install python-docx）。")
    return "\n".join(p.text for p in docx.Document(path).paragraphs)


def _pdf_to_text(path):
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        raise SystemExit("STOP: .pdf には pypdf が必要です（pip install pypdf）。")
    text = "\n".join((pg.extract_text() or "") for pg in PdfReader(path).pages)
    if not text.strip():
        raise SystemExit("STOP: テキスト埋込みのない画像PDFです（OCR は使用しません）。")
    return text


def _rtf_to_text(path):
    try:
        from striprtf.striprtf import rtf_to_text  # type: ignore
    except Exception:
        raise SystemExit("STOP: .rtf には striprtf が必要です（pip install striprtf）。")
    return rtf_to_text(_read_text(path))


def extract_text(path):
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED:
        raise SystemExit(f"STOP: 未対応形式（{ext}）。対応: {', '.join(SUPPORTED)}")
    return {".txt": _read_text, ".md": _read_text, ".csv": _csv_to_md, ".json": _json_to_text,
            ".docx": _docx_to_text, ".pdf": _pdf_to_text, ".rtf": _rtf_to_text}[ext](path)


# ── helpers ───────────────────────────────────────────────────────────────────
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for c in iter(lambda: fh.read(65536), b""):
            h.update(c)
    return h.hexdigest()


def redact(text):
    if not text:
        return text or "", 0
    c = 0

    def _s(m):
        nonlocal c
        c += 1
        return REDACTED
    return _SECRET_RE.sub(_s, text), c


def pii_flags(text):
    return {k: len(rx.findall(text or "")) for k, rx in _PII.items()}


def mask_pii(text):
    out = text or ""
    for rx in _PII.values():
        out = rx.sub(REDACTED, out)
    return out


def sanitize_title(t):
    t = re.sub(r"[\\/:*?\"<>|#\[\]]+", "", (t or "").strip())
    return (re.sub(r"\s+", "_", t) or "untitled")[:60]


def guess_title(text, filename):
    for line in (text or "").splitlines():
        s = line.strip().lstrip("# ").strip()
        if s:
            return s[:80]
    return os.path.splitext(os.path.basename(filename))[0]


def guess_date(text, filename, default):
    for src in (filename, text or ""):
        m = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", src)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return default


def classify_business(text, override=""):
    if override:
        for b in BUSINESSES:
            if override.strip() == b:
                return b
        return override.strip()
    for b, pat in _BIZ_HINTS.items():
        if re.search(pat, text or "", re.I):
            return b
    return "未分類"


def content_flags(text):
    return {"decision": bool(re.search(_HAS_DECISION, text or "")),
            "task": bool(re.search(_HAS_TASK, text or "")),
            "philosophy": bool(re.search(_HAS_PHILO, text or "")),
            "meeting": bool(re.search(_HAS_MEETING, text or ""))}


def _sentences(text):
    parts = re.split(r"(?<=[。！？!?])\s*|\n+", text or "")
    return [s.strip() for s in parts if s and s.strip()]


def extract_candidates(text, limit=10):
    """Extract VERBATIM candidate sentences (not summaries) for decisions / tasks /
    philosophy. These are observed candidates for the owner to confirm (Yes/No),
    never auto-confirmed. Returns {kind: [masked_sentence, ...]}. Empty when none
    match (no fabrication)."""
    pats = {"decision": _HAS_DECISION, "task": _HAS_TASK, "philosophy": _HAS_PHILO}
    out = {"decision": [], "task": [], "philosophy": []}
    for s in _sentences(text):
        for kind, pat in pats.items():
            if len(out[kind]) < limit and re.search(pat, s):
                out[kind].append(mask_pii(s)[:200])
    return out


def _section(title, items, suffix=""):
    lines = [f"## {title}"]
    if items:
        lines += [f"- {it}  ⟨observed・要確認⟩" for it in items]
        lines.append("- [ ] Yes / No：上記を確定して差し支えないか")
    else:
        lines.append(f"- {NO_DATA}{suffix}")
    lines.append("")
    return lines


def tags_for(business, flags):
    biz = re.sub(r"[^a-z0-9\-]+", "-", business.lower()) or "unclassified"
    tags = ["plaud", "transcript", f"biz-{biz}"]
    if flags["meeting"]:
        tags.append("meeting")
    if flags["decision"]:
        tags.append("decision")
    if flags["task"]:
        tags.append("task")
    if flags["philosophy"]:
        tags.append("philosophy-candidate")
    return tags


def out_filename(date, title, sha):
    return f"{date}_{sanitize_title(title)}_{sha[:8]}.md"


def build_raw_md(meta):
    return "\n".join([
        "---", "source: PLAUD", "source_type: uploaded-file",
        f"source_filename: {meta['source_filename']}", f"file_sha256: {meta['sha']}",
        f"recorded_at: {meta['recorded_at']}", f"imported_at: {meta['imported_at']}",
        f"title: {meta['title']}", f"business: {meta['business']}", "status: observed",
        "tags:", "  - plaud", "  - transcript", "---", "",
        f"# {meta['title']}", "",
        "## 元ファイル情報",
        f"- 元ファイル名：{meta['source_filename']}", f"- ファイル形式：{meta['ext']}",
        f"- 取込日時：{meta['imported_at']}", f"- SHA-256：{meta['sha']}", "",
        "## 文字起こし原文", "", meta["text"], "",
    ])


def build_processed_md(meta):
    tags = "\n".join(f"  - {t}" for t in meta["tags"])
    cand = meta.get("candidates") or {"decision": [], "task": [], "philosophy": []}
    lines = [
        "---", "source: PLAUD", "source_type: uploaded-file",
        f"title: {meta['title']}", f"business: {meta['business']}",
        f"type: {meta['type']}", "status: observed", "confidence: low",
        "tags:", tags, "---", "", f"# {meta['title']}", "",
        f"原文: [[{D_RAW}/{meta['stem']}]]", "",
        "> 以下は原文からの**該当文抽出（observed 候補）**。要約は生成せず、確定は Yes/No 後。", "",
        "## 3行要約", f"- {NO_DATA}（要約は自動生成しない・原文参照）", "",
        "## 詳細要約", NO_DATA, "", "## 事実", f"- {NO_DATA}", "",
    ]
    lines += _section("決定事項", cand["decision"], "（該当文なし）")
    lines += ["## 保留事項", f"- {NO_DATA}", ""]
    # tasks: candidate sentences + an empty template row for manual fill
    lines += ["## タスク"]
    if cand["task"]:
        for t in cand["task"]:
            lines.append(f"- {t}  ⟨observed・要確認⟩")
        lines.append("- [ ] Yes / No：タスク化してよいか")
    lines += ["", "| タスク | 担当者 | 期限 | 状態 |", "|---|---|---|---|",
              "| (確定後に記入) |  |  | observed |", ""]
    lines += ["## 数値・KPI", f"- {NO_DATA}", "", "## 人物・組織", f"- {NO_DATA}（PIIマスク）", ""]
    lines += _section("思想・価値観候補", cand["philosophy"],
                      "（該当文なし・confirmed 昇格は Yes 後）")
    lines += ["## 判断原則候補", f"- {NO_DATA}", "", "## SOP候補", f"- {NO_DATA}", "",
              "## 売上・利益への影響", f"- {NO_DATA}", "",
              "## ゆうさんの稼働削減への影響", f"- {NO_DATA}", "",
              "## 他事業への波及", f"- {NO_DATA}", "",
              "## 既存方針との一致", f"- {NO_DATA}", "", "## 既存方針との矛盾", f"- {NO_DATA}", "",
              "## Yes / No確認事項", "- [ ] Yes / No：（上記候補の確定・自動確定しない）", ""]
    return "\n".join(lines)


def update_link_page(existing, title, link, header):
    """Prepend a wikilink to an aggregation page (dedup, keep order). Pure."""
    entry = f"- [[{link}]] — {title}"
    links = [l for l in (existing or "").splitlines() if l.startswith("- [[")]
    links = [entry] + [l for l in links if l != entry]
    return "\n".join([f"# {header}", ""] + links + [""])


def build_index(existing, title, proc_link, business):
    entry = f"- [[{proc_link}]] — {business}"
    recent = [l for l in (existing or "").splitlines() if l.startswith("- [[")]
    recent = [entry] + [l for l in recent if l != entry]
    recent = recent[:30]
    lines = ["# PLAUD Knowledge Index", "", "## 最新の取込", *recent, "", "## 事業別"]
    for b in BUSINESSES:
        lines.append(f"- [[{D_BIZ}/{sanitize_title(b)}]]")
    lines += ["", "## 決定事項", f"- [[{D_DECISION}/_決定事項]]",
              "", "## 未完了タスク", f"- [[{D_TASK}/_タスク]]",
              "", "## 思想候補", f"- [[{D_PHILO}/_思想候補]]",
              "", "## 会議議事録", f"- [[{D_MEETING}/_会議議事録]]",
              "", "## 月別", "- `08_月別/YYYY-MM.md` を参照", ""]
    return "\n".join(lines)


# ── IO ────────────────────────────────────────────────────────────────────────
def _assert_safe_dest(dest_root):
    low = os.path.abspath(os.path.expanduser(dest_root)).lower()
    if "google drive" in low or "googledrive" in low or "drive.google" in low or "/dropbox" in low:
        raise SystemExit(f"STOP: Google Drive/Dropbox への保存は禁止: {dest_root}")


def _exists_sha(dest_root, sha, lister=None):
    if lister is not None:
        return lister(sha)
    rawdir = os.path.join(dest_root, D_RAW)
    if not os.path.isdir(rawdir):
        return False
    for root, _, files in os.walk(rawdir):
        if any(f"_{sha[:8]}.md" in f for f in files):
            return True
    return False


def _read(dest_root, suffix, reader=None):
    if reader is not None:
        return reader(suffix)
    fp = os.path.join(dest_root, suffix)
    return open(fp, encoding="utf-8").read() if os.path.isfile(fp) else ""


def _write(dest_root, suffix, content):
    tgt = os.path.join(dest_root, suffix)
    os.makedirs(os.path.dirname(tgt), exist_ok=True)
    with open(tgt, "w", encoding="utf-8") as fh:
        fh.write(content)
    return tgt


def run(mode, path, dest_root=VAULT_PLAUD, business="", title="", date=None,
        lister=None, reader=None, log_path=None):
    if not path or not os.path.isfile(path):
        raise SystemExit(f"STOP: ファイルが存在しません: {path}")
    _assert_safe_dest(dest_root)
    ext = os.path.splitext(path)[1].lower()
    text = extract_text(path)
    if not (text and text.strip()):
        raise SystemExit("STOP: ファイル内容が空です。")

    sha = sha256_file(path)
    # An explicit --date is authoritative (overrides the text/filename heuristic,
    # which can pick a deadline mentioned in the body). Only auto-detect when the
    # caller did not pass a date.
    explicit_date = date is not None
    date = date or datetime.date.today().strftime("%Y-%m-%d")
    fdate = date if explicit_date else guess_date(text, path, date)[:10]
    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    ttl = title.strip() or mask_pii(redact(guess_title(text, path))[0])
    biz = classify_business(text, business)
    flags = content_flags(text)
    ttype = "meeting" if flags["meeting"] else ("decision" if flags["decision"] else "meeting")
    fname = out_filename(fdate, ttl, sha)
    stem = fname[:-3]
    result = {"mode": mode, "sha8": sha[:8], "filename": fname, "business": biz,
              "flags": flags, "chars": len(text), "written": [], "links": [],
              "secrets_redacted": 0, "pii_flags": {}, "status": "PLANNED"}

    if mode == "plan":
        print(f"file      : {os.path.basename(path)} ({ext}, {len(text)} 文字)")
        print(f"sha256(8) : {sha[:8]} / title: {ttl} / business: {biz}")
        print(f"routing   : 決定={flags['decision']} タスク={flags['task']} "
              f"思想={flags['philosophy']} 会議={flags['meeting']}")
        print(f"  raw : {dest_root}/{D_RAW}/{fname}")
        print(f"  proc: {dest_root}/{D_PROC}/{fname}")
        print("保存先: Obsidian Vault 10_PLAUD / Drive 不使用 / 削除なし")
        return result

    if mode != "apply":
        raise SystemExit(f"unknown mode: {mode}")

    if _exists_sha(dest_root, sha, lister):
        result["status"] = "SKIPPED_DUPLICATE"
        print(json.dumps({"status": "SKIPPED_DUPLICATE", "sha8": sha[:8]}, ensure_ascii=False))
        return result

    red_text, n = redact(text)
    result["secrets_redacted"] = n
    result["pii_flags"] = pii_flags(text)
    if diff_risk.scan_secret_lines(red_text):
        raise SystemExit("STOP: 除外不能な重大 secret を検出。保存中止。")

    meta = {"source_filename": os.path.basename(path), "sha": sha, "ext": ext,
            "recorded_at": date if explicit_date else guess_date(text, path, NO_DATA),
            "imported_at": now,
            "title": ttl, "business": biz, "type": ttype, "stem": stem,
            "text": red_text, "tags": tags_for(biz, flags),
            "candidates": extract_candidates(red_text)}
    result["candidate_counts"] = {k: len(v) for k, v in meta["candidates"].items()}
    raw_md, proc_md = build_raw_md(meta), build_processed_md(meta)
    for doc in (raw_md, proc_md):
        if diff_risk.scan_secret_lines(doc):
            raise SystemExit("STOP: 生成 Markdown に secret 残存。保存中止。")

    result["written"].append(_write(dest_root, f"{D_RAW}/{fname}", raw_md))
    result["written"].append(_write(dest_root, f"{D_PROC}/{fname}", proc_md))

    # internal-link routing (links, not copies)
    proc_link = f"{D_PROC}/{stem}"
    routes = [(D_BIZ, f"{sanitize_title(biz)}.md", biz)]
    if flags["decision"]:
        routes.append((D_DECISION, "_決定事項.md", "決定事項"))
    if flags["task"]:
        routes.append((D_TASK, "_タスク.md", "タスク"))
    if flags["philosophy"]:
        routes.append((D_PHILO, "_思想候補.md", "思想候補"))
    if flags["meeting"]:
        routes.append((D_MEETING, "_会議議事録.md", "会議議事録"))
    routes.append((D_MONTH, f"{fdate[:7]}.md", fdate[:7]))
    for folder, page, header in routes:
        suffix = f"{folder}/{page}"
        updated = update_link_page(_read(dest_root, suffix, reader), ttl, proc_link, header)
        result["written"].append(_write(dest_root, suffix, updated))
        result["links"].append(suffix)

    idx = build_index(_read(dest_root, "INDEX.md", reader), ttl, proc_link, biz)
    result["written"].append(_write(dest_root, "INDEX.md", idx))
    # per-file json log (no body / no secret)
    _write(dest_root, f"{D_LOG}/{stem}.json",
           json.dumps({"at": now, "file": os.path.basename(path), "ext": ext,
                       "sha8": sha[:8], "chars": len(text), "business": biz,
                       "secrets_redacted": n}, ensure_ascii=False, indent=2))
    result["status"] = "OK"

    if log_path:
        try:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"at": now, "file": os.path.basename(path), "ext": ext,
                                     "sha8": sha[:8], "chars": len(text),
                                     "raw": f"{D_RAW}/{fname}", "secrets_redacted": n},
                                    ensure_ascii=False) + "\n")
        except Exception:
            pass

    print(json.dumps({"status": "OK", "filename": fname, "business": biz,
                      "secrets_redacted": n, "pii_flags": result["pii_flags"],
                      "links": result["links"]}, ensure_ascii=False))
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description="PLAUD transcript file → Obsidian 10_PLAUD")
    ap.add_argument("--file", required=True)
    ap.add_argument("--mode", choices=["plan", "apply"], default="plan")
    ap.add_argument("--dest-root", default=VAULT_PLAUD)
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
