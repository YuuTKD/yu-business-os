#!/usr/bin/env bash
# YU Knowledge OS — Daily Export runner (LaunchAgent target).
# Preflight → export (apply) → optional one-shot sync. Non-zero on export failure.
# Read-only collection + GCS write only. Never deletes local files, never commits.
set -Eeuo pipefail

REPO_ROOT="${KNOWLEDGE_REPO_ROOT:-$HOME/yu-business-os}"
GCS_ROOT="gs://tree-beauty-blog-images/knowledge-os"
LOG="${REPO_ROOT}/logs/daily_knowledge_export.log"
LOCK="${TMPDIR:-/tmp}/yu_daily_knowledge_export.lock"
SYNC="${REPO_ROOT}/scripts/sync_knowledge_os.sh"
export PATH="$HOME/google-cloud-sdk/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

mkdir -p "$(dirname "$LOG")"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG"; }

# ── 二重起動防止（同時実行は 1 つだけ） ──────────────────────────────
if ! mkdir "$LOCK" 2>/dev/null; then
  log "SKIP: 別の export が実行中（lock: $LOCK）"
  exit 0
fi
cleanup() { rmdir "$LOCK" 2>/dev/null || true; }
trap cleanup EXIT

log "━━━ daily knowledge export 開始 ━━━"

# ── preflight（不足は fail-closed。一部成功を成功扱いしない） ─────────
command -v python3 >/dev/null 2>&1 || { log "STOP: python3 不在"; exit 1; }
command -v gcloud  >/dev/null 2>&1 || { log "STOP: gcloud 不在"; exit 1; }
acct="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -1)"
[ -n "$acct" ] || { log "STOP: gcloud 認証なし（gcloud auth login）"; exit 1; }
gcloud storage ls "${GCS_ROOT}/" >/dev/null 2>&1 || { log "STOP: GCS ${GCS_ROOT} へアクセス不可"; exit 1; }

# ── export（GCS 保存が正本。失敗は非ゼロ終了） ───────────────────────
if python3 "${REPO_ROOT}/scripts/knowledge/export_daily_knowledge.py" \
     --mode apply --dest-root "$GCS_ROOT" >>"$LOG" 2>&1; then
  log "OK: GCS 保存成功"
else
  log "STOP: export 失敗（GCS 保存できず）"
  exit 1
fi

# ── 即時反映（任意）。同期失敗でも export 成功なら WARNING 扱い ───────
if [ -x "$SYNC" ]; then
  if SKIP_SLEEP=1 "$SYNC" >>"$LOG" 2>&1; then
    log "OK: Obsidian 同期完了"
  else
    log "WARNING: 同期失敗（GCS 保存は成功済み。次回 knowledge-sync で反映される）"
  fi
else
  log "INFO: 同期スクリプト未検出（$SYNC）。次回 knowledge-sync で反映される"
fi

log "━━━ daily knowledge export 完了 ━━━"
exit 0
