#!/usr/bin/env bash
# PLAUD 文字起こしファイル → Obsidian Vault 10_PLAUD へ直接保存.
#   bash scripts/plaud/import_plaud_file.sh "/絶対パス" ["事業名"]
set -Eeuo pipefail

REPO_ROOT="${KNOWLEDGE_REPO_ROOT:-$HOME/yu-business-os}"
VAULT_PLAUD="${PLAUD_VAULT_DIR:-$HOME/Documents/YU_HOLDINGS_Knowledge_OS/10_PLAUD}"
LOG="${REPO_ROOT}/logs/plaud_file_import.log"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

FILE="${1:-}"; BUSINESS="${2:-}"
mkdir -p "$(dirname "$LOG")"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG"; }

[ -n "$FILE" ] || { log "STOP: ファイルパス未指定"; exit 1; }
[ -f "$FILE" ] || { log "STOP: ファイルが存在しません: $(basename "$FILE")"; exit 1; }
command -v python3 >/dev/null 2>&1 || { log "STOP: python3 不在"; exit 1; }

log "import 開始: $(basename "$FILE") business=${BUSINESS:-auto}"
if python3 "${REPO_ROOT}/scripts/plaud/import_plaud_file.py" \
     --file "$FILE" --business "$BUSINESS" --mode apply --dest-root "$VAULT_PLAUD" >>"$LOG" 2>&1; then
  log "OK: Obsidian 10_PLAUD へ保存完了"
else
  log "STOP: import 失敗"; exit 1
fi
log "import 完了"
