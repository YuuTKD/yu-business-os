#!/usr/bin/env bash
# PLAUD share URL → GCS → Obsidian. Usage:
#   bash scripts/plaud/import_plaud_url.sh "PLAUD共有URL"
# URL は引数/環境変数で一時的に受け取り、ファイル・Git へ保存しない。
# ログには先頭の共有IDのみ表示し、トークン部分(::以降)は出さない。
set -Eeuo pipefail

REPO_ROOT="${KNOWLEDGE_REPO_ROOT:-$HOME/yu-business-os}"
GCS_ROOT="gs://tree-beauty-blog-images/knowledge-os"
SYNC="${REPO_ROOT}/scripts/sync_knowledge_os.sh"
LOG="${REPO_ROOT}/logs/plaud_import.log"
export PATH="$HOME/google-cloud-sdk/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

URL="${1:-${PLAUD_URL:-}}"
mkdir -p "$(dirname "$LOG")"

# token を出さないマスク表示（:: 以降を落とす）
mask() { printf '%s' "$1" | sed -E 's#(https://web\.plaud\.ai/s/[^:]+)::.*#\1::REDACTED#'; }
log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG"; }

[ -n "$URL" ] || { log "STOP: URL 未指定"; exit 1; }
case "$URL" in
  https://web.plaud.ai/s/*) : ;;
  *) log "STOP: PLAUD 共有URL 以外は処理しません（$(mask "$URL")）"; exit 1 ;;
esac
log "import 開始: $(mask "$URL")"

command -v python3 >/dev/null 2>&1 || { log "STOP: python3 不在"; exit 1; }
command -v gcloud  >/dev/null 2>&1 || { log "STOP: gcloud 不在"; exit 1; }
gcloud storage ls "${GCS_ROOT}/" >/dev/null 2>&1 || { log "STOP: GCS アクセス不可（gcloud auth login 要）"; exit 1; }

# URL は環境変数で子プロセスへ渡す（コマンドライン露出/ファイル保存を避ける）
if PLAUD_URL="$URL" python3 "${REPO_ROOT}/scripts/plaud/import_plaud_url.py" \
     --mode apply --dest-root "$GCS_ROOT" >>"$LOG" 2>&1; then
  log "OK: GCS 保存成功"
else
  log "STOP: import 失敗"
  exit 1
fi

# 即時反映（GCS 成功後）。同期失敗は WARNING（GCS 保存は成功済み）。
if [ -x "$SYNC" ]; then
  if SKIP_SLEEP=1 "$SYNC" >>"$LOG" 2>&1; then log "OK: Obsidian 同期完了"
  else log "WARNING: 同期失敗（次回 knowledge-sync で反映）"; fi
fi
log "import 完了"
