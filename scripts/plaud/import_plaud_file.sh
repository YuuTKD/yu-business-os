#!/usr/bin/env bash
# PLAUD 文字起こしファイル → GCS → Obsidian. Usage:
#   bash scripts/plaud/import_plaud_file.sh "/path/to/file" ["事業名"]
set -Eeuo pipefail

REPO_ROOT="${KNOWLEDGE_REPO_ROOT:-$HOME/yu-business-os}"
GCS_ROOT="gs://tree-beauty-blog-images/knowledge-os"
SYNC="${REPO_ROOT}/scripts/sync_knowledge_os.sh"
LOG="${REPO_ROOT}/logs/plaud_file_import.log"
export PATH="$HOME/google-cloud-sdk/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

FILE="${1:-}"
BUSINESS="${2:-}"
mkdir -p "$(dirname "$LOG")"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG"; }

[ -n "$FILE" ] || { log "STOP: ファイルパス未指定"; exit 1; }
[ -f "$FILE" ] || { log "STOP: ファイルが存在しません: $(basename "$FILE")"; exit 1; }
command -v python3 >/dev/null 2>&1 || { log "STOP: python3 不在"; exit 1; }
command -v gcloud  >/dev/null 2>&1 || { log "STOP: gcloud 不在"; exit 1; }
gcloud storage ls "${GCS_ROOT}/" >/dev/null 2>&1 || { log "STOP: GCS アクセス不可（gcloud auth login 要）"; exit 1; }

log "import 開始: $(basename "$FILE") business=${BUSINESS:-auto}"
if python3 "${REPO_ROOT}/scripts/plaud/import_plaud_file.py" \
     --file "$FILE" --business "$BUSINESS" --mode apply --dest-root "$GCS_ROOT" >>"$LOG" 2>&1; then
  log "OK: GCS 保存成功"
else
  log "STOP: import 失敗"; exit 1
fi

if [ -x "$SYNC" ]; then
  if SKIP_SLEEP=1 "$SYNC" >>"$LOG" 2>&1; then log "OK: Obsidian 同期完了"
  else log "WARNING: 同期失敗（次回 knowledge-sync で反映）"; fi
fi
log "import 完了"
