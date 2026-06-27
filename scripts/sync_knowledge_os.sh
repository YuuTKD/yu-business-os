#!/bin/bash
# YU HOLDINGS Knowledge OS — GCS→Obsidian同期スクリプト
# 秘密情報は一切出力しない設計
# rsync に -d フラグなし → ローカルの既存メモは削除しない

set -euo pipefail

# ── ログイン直後はネットワーク安定を待つ（LaunchAgent自動実行時） ──
# 手動実行時はスキップしたい場合は SKIP_SLEEP=1 を前置する
if [ "${SKIP_SLEEP:-0}" != "1" ]; then
    sleep 300
fi

# ── PATH ────────────────────────────────────────────────────
export PATH="/Users/tokudayuya/google-cloud-sdk/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

# ── 設定 ────────────────────────────────────────────────────
GCS_SRC="gs://tree-beauty-blog-images/knowledge-os/"
LOCAL_VAULT="$HOME/Documents/YU_HOLDINGS_Knowledge_OS"
LOG_FILE="$HOME/yu-business-os/logs/knowledge_sync.log"
MAX_LOG_LINES=2000

# ── ログ関数 ─────────────────────────────────────────────────
log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
    echo "$msg" | tee -a "$LOG_FILE"
}

# ── ログローテーション（2000行超で先頭500行削除） ────────────
rotate_log() {
    if [ -f "$LOG_FILE" ] && [ "$(wc -l < "$LOG_FILE")" -gt "$MAX_LOG_LINES" ]; then
        tail -n 1500 "$LOG_FILE" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
    fi
}

# ── ログファイルディレクトリ確保 ─────────────────────────────
mkdir -p "$(dirname "$LOG_FILE")"
rotate_log

log "━━━ 同期開始 ━━━"

# ── ネットワーク接続確認 ─────────────────────────────────────
if ! ping -c 1 -W 3 storage.googleapis.com > /dev/null 2>&1; then
    log "❌ ネットワーク未接続。同期をスキップします。"
    exit 1
fi
log "✅ ネットワーク接続確認"

# ── gsutil 存在確認 ─────────────────────────────────────────
if ! command -v gsutil > /dev/null 2>&1; then
    log "❌ gsutil が見つかりません（PATH: $PATH）"
    exit 1
fi
log "✅ gsutil: $(which gsutil)"

# ── Obsidian Vault 作成 ─────────────────────────────────────
if [ ! -d "$LOCAL_VAULT" ]; then
    mkdir -p "$LOCAL_VAULT"
    log "📁 Vault新規作成: $LOCAL_VAULT"
fi

# ── GCS → ローカル同期（-d なし = ローカル削除しない） ──────
log "🔄 同期元: $GCS_SRC"
log "🔄 同期先: $LOCAL_VAULT"

SYNC_OUTPUT=$(gsutil -m rsync -r \
    "$GCS_SRC" \
    "$LOCAL_VAULT/" 2>&1) || {
    log "❌ gsutil rsync 失敗"
    echo "$SYNC_OUTPUT" | grep -v "Copying\|Building\|Starting\|operation" | head -10 >> "$LOG_FILE"
    exit 1
}

COPIED=$(echo "$SYNC_OUTPUT" | grep -c "^Copying" || true)
log "✅ 同期完了 — 転送ファイル数: ${COPIED}件"

TOTAL=$(find "$LOCAL_VAULT" -name "*.md" | wc -l | tr -d ' ')
log "📄 Vault内 Markdown総数: ${TOTAL}件"
log "━━━ 同期終了 ━━━"
