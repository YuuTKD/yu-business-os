#!/usr/bin/env python3
"""YU Knowledge OS — Daily Export layer (additive).

Collects READ-ONLY facts from the given projects, builds daily Markdown, redacts
secrets, and (in --apply) uploads to the GCS Knowledge OS. GCS is the single
source of truth; the existing sync (sync_knowledge_os.sh) reflects it into the
local Obsidian vault. This layer NEVER:
  * deletes anything (past dated files are preserved),
  * writes to the personal Obsidian vault or Google Drive,
  * writes business data, commits git, or changes Scheduler/Cloud Run/SNS,
  * stores secret VALUES (they are redacted; unredactable → upload STOP).

Modes: --plan (default, no writes) / --apply (write to dest) / --verify (read-only checks).
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

# Reuse the governance secret patterns as the single source for redaction.
from core.governance import diff_risk

GCS_DEST_ROOT = "gs://tree-beauty-blog-images/knowledge-os"
LOCAL_VAULT = os.path.expanduser("~/Documents/YU_HOLDINGS_Knowledge_OS")  # NEVER written
NO_RECORD = "記録なし"

DEFAULT_PROJECTS = ["yu-business-os", "ai-net-business-sns-os", "local-business-ai-content-os"]

# Redaction patterns: governance secret patterns + a few token-ish extras.
_REDACT_PATTERNS = list(diff_risk.SECRET_LINE_PATTERNS) + [
    r"ya29\.[A-Za-z0-9_\-]{20,}",              # Google OAuth access token
    r"1//[A-Za-z0-9_\-]{20,}",                 # Google refresh token
    r"Bearer\s+[A-Za-z0-9._\-]{20,}",          # Authorization: Bearer
    r"AKIA[0-9A-Z]{16}",                       # AWS access key id
]
_REDACT_RE = re.compile("|".join(_REDACT_PATTERNS))
REDACTED = "REDACTED"


def redact(text: str):
    """Return (redacted_text, count). Secret VALUES are never returned."""
    if not text:
        return text or "", 0
    count = 0

    def _sub(m):
        nonlocal count
        count += 1
        return REDACTED

    return _REDACT_RE.sub(_sub, text), count


def _run(cmd, cwd=None):
    """Read-only subprocess; returns stdout or '' on any failure (fail-soft)."""
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=30)
        return p.stdout.strip() if p.returncode == 0 else ""
    except Exception:
        return ""


def collect_project(path: str) -> dict:
    """READ-ONLY facts for one project. Missing data → NO_RECORD (never guessed)."""
    if not path or not os.path.isdir(os.path.join(path, ".git")):
        return {"path": path, "available": False}
    commits = _run(["git", "log", "--since=midnight", "--pretty=format:%h %s"], cwd=path)
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    dirty = _run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=path)
    # gh is optional / may be unauthenticated → fail-soft
    prs = _run(["gh", "pr", "list", "--state", "all", "--limit", "20",
                "--json", "number,title,state,updatedAt",
                "--jq", '.[] | select(.updatedAt >= (now|strftime("%Y-%m-%d"))) | "#\\(.number) \\(.state) \\(.title)"'],
               cwd=path)
    return {
        "path": path,
        "available": True,
        "branch": branch or NO_RECORD,
        "commits_today": commits or NO_RECORD,
        "uncommitted_tracked": "あり(読み取りのみ・commitしない)" if dirty else "なし",
        "prs_today": prs or NO_RECORD,
    }


def _status_from(projects_data: list) -> str:
    # GO by default; WARNING if any project unavailable; conservative.
    if any(not d.get("available") for d in projects_data):
        return "WARNING"
    return "GO"


def build_daily_report(projects_data: list, date: str, generated_at: str) -> str:
    status = _status_from(projects_data)
    fm = [
        "---",
        f"date: {date}",
        "type: daily-report",
        "projects:",
    ] + [f"  - {p}" for p in DEFAULT_PROJECTS] + [
        f"status: {status}",
        "production_impact: none",
        f"generated_at: {generated_at}",
        "---",
        "",
        f"# {date} 日次経営・開発レポート",
        "",
        "## 1. 本日の結論",
        f"- status: {status} / production_impact: none（自動収集・判断項目は {NO_RECORD}）",
        "",
        "## 2. 完了したこと",
    ]
    for d in projects_data:
        fm.append(f"### {os.path.basename(d.get('path',''))}")
        if not d.get("available"):
            fm.append(f"- {NO_RECORD}（リポジトリ未取得）")
            continue
        commits = d["commits_today"]
        if commits == NO_RECORD:
            fm.append(f"- 本日のコミット: {NO_RECORD}")
        else:
            for line in commits.splitlines():
                fm.append(f"- {line}")
        fm.append(f"- PR(本日更新): {d['prs_today']}")
    fm += [
        "",
        "## 3. 発生したエラー",
        f"- {NO_RECORD}（自動収集対象外・ログ確認は各 logs/ 参照）",
        "",
        "## 4. 根本原因",
        f"- {NO_RECORD}",
        "",
        "## 5. 修正内容",
        f"- {NO_RECORD}（コミット履歴は §2 参照）",
        "",
        "## 6. GitHub / Actions",
    ]
    for d in projects_data:
        if d.get("available"):
            fm.append(f"- {os.path.basename(d['path'])}: branch={d['branch']} / 未コミット={d['uncommitted_tracked']}")
    fm += [
        "",
        "## 7. 本番への影響",
        "- none（本レイヤーは read-only 収集・GCS 保存のみ。traffic/Scheduler/Cloud Run 変更なし）",
        "",
        "## 8. 売上・集客への影響",
        f"- {NO_RECORD}",
        "",
        "## 9. 未完了",
        f"- {NO_RECORD}",
        "",
        "## 10. 明日の最優先3項目",
        f"1. {NO_RECORD}",
        f"2. {NO_RECORD}",
        f"3. {NO_RECORD}",
        "",
        "## 11. ゆうさんの判断",
        "- [ ] Yes / No：（自動記録なし）",
        "",
        "## 12. 再発防止・資産化",
        f"- {NO_RECORD}",
        "",
    ]
    return "\n".join(fm)


def build_decisions(date: str, generated_at: str) -> str:
    return "\n".join([
        "---", f"date: {date}", "type: decisions", f"generated_at: {generated_at}", "---",
        "", f"# {date} 意思決定ログ", "",
        f"- 自動収集では意思決定を推測しない。人手記録がなければ {NO_RECORD}。", "",
        "## Yes/No で回答できる意思決定", f"- {NO_RECORD}", "",
        "## 重要な経営判断", f"- {NO_RECORD}", "",
    ])


def build_automation(projects_data: list, date: str, generated_at: str) -> str:
    lines = [
        "---", f"date: {date}", "type: automation-log", f"generated_at: {generated_at}", "---",
        "", f"# {date} 自動化変更履歴", "",
        "## Cloud Run / Scheduler / IAM 変更",
        "- 本レイヤーによる変更: なし（read-only）",
        f"- その他の自動化変更: {NO_RECORD}（推測しない）", "",
        "## 本日のコミット（自動化に関わり得る変更）",
    ]
    for d in projects_data:
        if d.get("available") and d["commits_today"] != NO_RECORD:
            for line in d["commits_today"].splitlines():
                lines.append(f"- {os.path.basename(d['path'])}: {line}")
    lines.append("")
    return "\n".join(lines)


def build_dashboard(projects_data: list, date: str, generated_at: str) -> str:
    status = _status_from(projects_data)
    lines = [
        "---", f"date: {date}", "type: latest-daily-status",
        f"status: {status}", f"generated_at: {generated_at}", "---",
        "", "# LATEST DAILY STATUS", "",
        f"- 最終更新: {generated_at}", f"- 対象日: {date}", f"- status: {status}", "",
        "## プロジェクト状況",
    ]
    for d in projects_data:
        name = os.path.basename(d.get("path", "")) or d.get("path", "")
        if d.get("available"):
            n = 0 if d["commits_today"] == NO_RECORD else len(d["commits_today"].splitlines())
            lines.append(f"- {name}: branch={d['branch']} / 本日コミット {n} 件")
        else:
            lines.append(f"- {name}: {NO_RECORD}（未取得）")
    lines += ["", f"詳細は 05_Reports/Daily/ 参照。判断項目は {NO_RECORD}。", ""]
    return "\n".join(lines)


def dest_paths(date: str) -> dict:
    y, m = date[:4], date[5:7]
    return {
        "daily": f"05_Reports/Daily/{y}/{m}/{date}_DAILY_REPORT.md",
        "decisions": f"04_Decisions/{y}/{m}/{date}_DECISIONS.md",
        "automation": f"08_Automation_System/{y}/{m}/{date}_AUTOMATION_LOG.md",
        "dashboard": "00_Dashboard/LATEST_DAILY_STATUS.md",
    }


def _assert_safe_dest(dest_root: str):
    """Never allow the personal vault or Google Drive as a destination."""
    low = dest_root.lower()
    if os.path.abspath(os.path.expanduser(dest_root)) == os.path.abspath(LOCAL_VAULT) \
       or "yu_holdings_knowledge_os" in low or "google drive" in low \
       or "/googledrive" in low or "drive.google" in low:
        raise SystemExit(f"STOP: 個人Vault/Drive への保存は禁止です: {dest_root}")


def _write(dest_root: str, suffix: str, content: str):
    """Write content to dest_root/suffix. gs:// → gcloud storage cp; else local file."""
    if dest_root.startswith("gs://"):
        target = dest_root.rstrip("/") + "/" + suffix
        p = subprocess.run(["gcloud", "storage", "cp", "-", target],
                           input=content, text=True, capture_output=True)
        if p.returncode != 0:
            raise SystemExit(f"STOP: GCS 保存失敗 {target}: {p.stderr.strip()[:200]}")
        return target
    # local (tests / non-gcs): create dirs, write file (no deletion of others)
    target = os.path.join(dest_root, suffix)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(content)
    return target


def generate(projects, date, generated_at):
    """Build all four documents (pure). Returns {key: (suffix, content)}."""
    data = [collect_project(p) for p in projects]
    paths = dest_paths(date)
    docs = {
        "daily": (paths["daily"], build_daily_report(data, date, generated_at)),
        "decisions": (paths["decisions"], build_decisions(date, generated_at)),
        "automation": (paths["automation"], build_automation(data, date, generated_at)),
        "dashboard": (paths["dashboard"], build_dashboard(data, date, generated_at)),
    }
    return data, docs


def run(mode, projects, dest_root, date=None, log_path=None):
    date = date or datetime.date.today().strftime("%Y-%m-%d")
    generated_at = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    _assert_safe_dest(dest_root)
    data, docs = generate([os.path.join(os.path.dirname(_REPO_ROOT), p)
                           if not os.path.isabs(p) else p for p in projects],
                          date, generated_at)

    # redact every document; fail-closed if a secret survives redaction
    total_redacted = 0
    for key, (suffix, content) in list(docs.items()):
        red, n = redact(content)
        total_redacted += n
        if diff_risk.scan_secret_lines(red):
            raise SystemExit(f"STOP: 除外不能な secret を検出（{suffix}）。アップロード中止。")
        docs[key] = (suffix, red)

    result = {
        "mode": mode, "date": date, "generated_at": generated_at,
        "dest_root": dest_root, "projects": projects,
        "targets": {k: v[0] for k, v in docs.items()},
        "secrets_redacted": total_redacted,
        "written": [], "status": "PLANNED",
    }

    if mode == "plan":
        print("== PLAN (no writes) ==")
        print(f"dest_root: {dest_root}")
        for k, (suffix, _c) in docs.items():
            print(f"  would write: {dest_root.rstrip('/')}/{suffix}")
        print(f"projects read: {projects}")
        print(f"secrets redacted (dry): {total_redacted}")
        result["status"] = "PLANNED"
    elif mode == "apply":
        for k, (suffix, content) in docs.items():
            tgt = _write(dest_root, suffix, content)
            result["written"].append(tgt)
        result["status"] = "OK"
    else:
        raise SystemExit(f"unknown run mode: {mode}")

    if log_path:
        try:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(result, ensure_ascii=False) + "\n")
        except Exception:
            pass
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description="YU Knowledge OS daily export")
    ap.add_argument("--mode", choices=["plan", "apply"], default="plan")
    ap.add_argument("--dest-root", default=GCS_DEST_ROOT)
    ap.add_argument("--projects", nargs="*", default=DEFAULT_PROJECTS)
    ap.add_argument("--date", default=None)
    ap.add_argument("--log", default=os.path.join(_REPO_ROOT, "logs", "daily_knowledge_export.log"))
    args = ap.parse_args(argv)
    res = run(args.mode, args.projects, args.dest_root, args.date, args.log)
    print(json.dumps({"status": res["status"], "targets": res["targets"],
                      "secrets_redacted": res["secrets_redacted"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
