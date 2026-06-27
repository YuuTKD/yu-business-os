#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# YU BUSINESS OS - 新規事業追加スクリプト
#
# 使い方:
#   ./deploy/add_business.sh catering
#   ./deploy/add_business.sh tachinomiya
#   ./deploy/add_business.sh ryukyu_hinabe
#
# 所要時間: 約30分（スプレッドシートIDの設定待ち含む）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

set -e

BUSINESS_KEY="${1:-}"
PROJECT_ID="tree-beauty-ai-499303"
REGION="asia-northeast1"
GCLOUD="$HOME/google-cloud-sdk/bin/gcloud"

if [ -z "$BUSINESS_KEY" ]; then
  echo "使い方: $0 <business_key>"
  echo "利用可能: beauty | catering | pasta_pasta | z1 | tachinomiya | ryukyu_hinabe"
  exit 1
fi

# business_key → Cloud Runサービス名のマッピング
declare -A SERVICE_NAMES=(
  ["beauty"]="tree-beauty-ai"
  ["catering"]="trees-catering-ai"
  ["pasta_pasta"]="pasta-pasta-ai"
  ["z1"]="z1-ai"
  ["tachinomiya"]="tachinomiya-ai"
  ["ryukyu_hinabe"]="ryukyu-hinabe-ai"
)

SERVICE_NAME="${SERVICE_NAMES[$BUSINESS_KEY]}"
if [ -z "$SERVICE_NAME" ]; then
  echo "エラー: 未知の事業キー '$BUSINESS_KEY'"
  exit 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  YU BUSINESS OS: $BUSINESS_KEY 構築開始"
echo "  サービス名: $SERVICE_NAME"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ─── STEP 1: 環境変数ファイルの確認 ───────────────────
ENV_FILE="/tmp/yu-${BUSINESS_KEY}-envvars.yaml"
TEMPLATE_FILE="$(dirname "$0")/../configs/env_templates/${BUSINESS_KEY}.yaml"

if [ ! -f "$TEMPLATE_FILE" ]; then
  echo "環境変数テンプレートが見つかりません: $TEMPLATE_FILE"
  echo "configs/env_templates/${BUSINESS_KEY}.yaml を作成してください。"
  echo ""
  echo "必要な変数:"
  echo "  BUSINESS_NAME: \"$BUSINESS_KEY\""
  echo "  EXECUTION_MODE: \"live\""
  echo "  OPENAI_API_KEY: \"<your-key>\""
  echo "  SPREADSHEET_ID: \"<google-sheets-id>\""
  echo "  <BUSINESS>_LINE_STAFF_TOKEN: \"<token>\""
  echo "  GOOGLE_CREDENTIALS_B64: \"<base64-encoded-json>\""
  echo "  MONTHLY_SALES_TARGET: \"<target-yen>\""
  exit 1
fi

cp "$TEMPLATE_FILE" "$ENV_FILE"
echo "✅ 環境変数ファイル: $ENV_FILE"

# ─── STEP 2: Cloud Run デプロイ ──────────────────────
echo ""
echo "[STEP 2/5] Cloud Run へデプロイ中..."
$GCLOUD run deploy "$SERVICE_NAME" \
  --source "$(dirname "$0")/.." \
  --region "$REGION" \
  --allow-unauthenticated \
  --timeout 3600 \
  --memory 1Gi \
  --env-vars-file "$ENV_FILE" \
  --project "$PROJECT_ID"

SERVICE_URL=$($GCLOUD run services describe "$SERVICE_NAME" \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --format "value(status.url)")

echo "✅ Cloud Run URL: $SERVICE_URL"

# ─── STEP 3: Cloud Scheduler ジョブ作成 ──────────────
echo ""
echo "[STEP 3/5] Cloud Scheduler ジョブ作成中..."

# 毎日9時 - Google投稿
$GCLOUD scheduler jobs create http "${BUSINESS_KEY}-daily-google" \
  --project "$PROJECT_ID" \
  --location "$REGION" \
  --schedule "0 9 * * *" \
  --uri "${SERVICE_URL}/google" \
  --http-method POST \
  --time-zone "Asia/Tokyo" \
  --message-body '{}' \
  --attempt-deadline 300s \
  --description "${BUSINESS_KEY}: 毎日9時 Google投稿自動生成" 2>/dev/null \
  || echo "  [SKIP] ${BUSINESS_KEY}-daily-google 既存"

# 日曜22:30 - CSV取込
$GCLOUD scheduler jobs create http "${BUSINESS_KEY}-csv-process" \
  --project "$PROJECT_ID" \
  --location "$REGION" \
  --schedule "30 22 * * 0" \
  --uri "${SERVICE_URL}/process-csv" \
  --http-method POST \
  --time-zone "Asia/Tokyo" \
  --message-body '{}' \
  --attempt-deadline 1800s \
  --description "${BUSINESS_KEY}: 日曜22:30 CSV取込・週次レポート" 2>/dev/null \
  || echo "  [SKIP] ${BUSINESS_KEY}-csv-process 既存"

# 日曜23:00 - 週次レポート
$GCLOUD scheduler jobs create http "${BUSINESS_KEY}-weekly-report" \
  --project "$PROJECT_ID" \
  --location "$REGION" \
  --schedule "0 23 * * 0" \
  --uri "${SERVICE_URL}/generate-weekly-report" \
  --http-method POST \
  --time-zone "Asia/Tokyo" \
  --message-body '{}' \
  --attempt-deadline 300s \
  --description "${BUSINESS_KEY}: 日曜23時 週次レポート生成" 2>/dev/null \
  || echo "  [SKIP] ${BUSINESS_KEY}-weekly-report 既存"

echo "✅ Cloud Scheduler: 3ジョブ作成完了"

# ─── STEP 4: スプレッドシート初期構築 ─────────────────
echo ""
echo "[STEP 4/5] スプレッドシート初期構築中..."
curl -s -X POST "${SERVICE_URL}/setup-spreadsheet" \
  -H "Content-Type: application/json" \
  -d '{}' | python3 -m json.tool

# ─── STEP 5: 動作確認 ─────────────────────────────────
echo ""
echo "[STEP 5/5] ヘルスチェック..."
curl -s "${SERVICE_URL}/health" | python3 -m json.tool
curl -s "${SERVICE_URL}/status" | python3 -m json.tool

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ $BUSINESS_KEY OS 構築完了"
echo ""
echo "  Cloud Run URL: $SERVICE_URL"
echo ""
echo "  自動実行スケジュール:"
echo "  ・毎日9時    → Google投稿生成"
echo "  ・日曜22:30  → CSV取込 + 週次レポート生成"
echo "  ・日曜23:00  → 週次レポート LINE通知"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
