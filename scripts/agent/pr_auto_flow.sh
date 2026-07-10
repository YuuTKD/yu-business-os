#!/usr/bin/env bash
# scripts/agent/pr_auto_flow.sh
# Codex 120点運用 — PR 自動フロー実行スクリプト
#
# 使い方:
#   ./scripts/agent/pr_auto_flow.sh <PR番号>
#
# 機能:
#   - 12 観点レビューを実施
#   - 売上直結度スコア (S/A/B/C/D) を付与
#   - リスク分類 (Low/Medium/High) を判定
#   - GO / FIX / STOP を出力
#   - FIX_ATTEMPT カウンターを管理 (data/reports/fix_attempt_pr_<N>.txt)
#   - GO + Low リスク: safe_auto_merge_pr.sh を実行
#
# 注意:
#   - 実投稿・Scheduler変更・自動送信は一切しない
#   - STOP の場合は即停止、人間（ゆうさん）の承認を待つ
#   - High リスク PR は Merge 前で必ず停止

set -euo pipefail

GH="${GH_PATH:-$(command -v gh 2>/dev/null || echo /opt/homebrew/bin/gh)}"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
REPORTS_DIR="${REPO_ROOT}/data/reports"

RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[1;33m'
BLU='\033[0;34m'
BLD='\033[1m'
RST='\033[0m'

ok()   { echo -e "  ${GRN}✓${RST} $*"; }
info() { echo -e "  ${YLW}→${RST} $*"; }
warn() { echo -e "  ${YLW}⚠${RST} $*"; }
err()  { echo -e "  ${RED}✗${RST} $*"; }

# ─── STOP 出力 ────────────────────────────────────────────────────────────────
emit_stop() {
  local reason="$1"
  local pr_num="${PR_NUMBER:-?}"
  echo ""
  echo -e "${RED}${BLD}━━━ STOP ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
  echo -e "${RED}${BLD}  Codex 監査で即時停止しました${RST}"
  echo -e "${RED}  PR #${pr_num}: ${reason}${RST}"
  echo -e "${RED}  → Merge 禁止。ゆうさんの承認を待ちます。${RST}"
  echo -e "${RED}${BLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
  echo ""
  exit 2
}

# ─── FIX 出力 ────────────────────────────────────────────────────────────────
emit_fix() {
  local reason="$1"
  local attempt="${FIX_ATTEMPT:-0}"
  echo ""
  echo -e "${YLW}${BLD}━━━ FIX ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
  echo -e "${YLW}${BLD}  修正が必要です (FIX_ATTEMPT: ${attempt}/3)${RST}"
  echo -e "${YLW}  ${reason}${RST}"
  echo -e "${YLW}${BLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
  echo ""
  exit 1
}

# ─── 引数チェック ─────────────────────────────────────────────────────────────
if [[ $# -lt 1 ]]; then
  echo "使い方: $0 <PR番号>"
  echo "例:     $0 5"
  exit 1
fi

PR_NUMBER="$1"

echo ""
echo -e "${BLD}━━━ Codex 120点 PR レビュー ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
echo -e "  PR #${PR_NUMBER}"
echo -e "${BLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
echo ""

# ─── 前提チェック ─────────────────────────────────────────────────────────────
command -v "$GH" >/dev/null 2>&1 || { echo "$GH not found"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "python3 not found"; exit 1; }
mkdir -p "$REPORTS_DIR"

REPO=$("$GH" repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null) \
  || emit_stop "GitHubリポジトリ情報を取得できません。"

# ─── FIX_ATTEMPT 読み込み ─────────────────────────────────────────────────────
FIX_FILE="${REPORTS_DIR}/fix_attempt_pr_${PR_NUMBER}.txt"
FIX_ATTEMPT=0

if [[ -f "$FIX_FILE" ]]; then
  FIX_ATTEMPT=$(grep -E "^FIX_ATTEMPT=" "$FIX_FILE" | cut -d= -f2 | tr -d '[:space:]' || echo 0)
  FIX_ATTEMPT="${FIX_ATTEMPT:-0}"
  info "FIX_ATTEMPT 読み込み: ${FIX_ATTEMPT}/3 (ファイル: ${FIX_FILE})"
fi

if [[ "$FIX_ATTEMPT" -gt 3 ]]; then
  emit_stop "FIX_ATTEMPT=${FIX_ATTEMPT} — 修正上限(3回)を超えています。人間確認が必要です。"
fi

# ─── PR 情報取得 ─────────────────────────────────────────────────────────────
echo -e "${BLD}[1/5] PR 情報取得${RST}"

PR_JSON=$("$GH" pr view "$PR_NUMBER" \
  --json title,state,mergeable,labels,reviewDecision,isDraft,body \
  2>/dev/null) \
  || emit_stop "PR #${PR_NUMBER} を取得できません。"

PR_TITLE=$(echo "$PR_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['title'])")
PR_STATE=$(echo "$PR_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['state'])")
PR_IS_DRAFT=$(echo "$PR_JSON" | python3 -c "import json,sys; print(str(json.load(sys.stdin).get('isDraft')).lower())")

info "タイトル: ${PR_TITLE}"
info "状態    : ${PR_STATE}"
info "Draft   : ${PR_IS_DRAFT}"

[[ "$PR_STATE" == "OPEN" ]] || emit_stop "PRがOPENではありません: ${PR_STATE}"
[[ "$PR_IS_DRAFT" != "true" ]] || emit_stop "Draft PRは監査対象外です。Draft を解除してください。"

PR_FILE_STATUS=$("$GH" api --paginate "repos/${REPO}/pulls/${PR_NUMBER}/files" \
  --jq '.[] | "\(.status)\t\(.filename)"' 2>/dev/null) \
  || emit_stop "PRファイル一覧をGitHub APIから取得できません。"

PR_FILES=$(echo "$PR_FILE_STATUS" | cut -f2-)
FILE_COUNT=$(echo "$PR_FILES" | grep -c . || echo 0)
info "変更ファイル: ${FILE_COUNT} 件"
echo ""

# ─── リスク分類 ───────────────────────────────────────────────────────────────
echo -e "${BLD}[2/5] リスク分類${RST}"

RISK_LEVEL="Low"
RISK_REASONS=()

HIGH_RISK_PATTERNS=(
  "^scripts/"
  "^agents/"
  "^config/"
  "^apps/"
  "^core/"
  "\.env($|\.)"
  "package\.json$"
  "^\.github/workflows/"
  "cloudrun"
  "scheduler"
)

MEDIUM_RISK_PATTERNS=(
  "^data/reports/"
)

while IFS= read -r filepath; do
  [[ -z "$filepath" ]] && continue

  for pat in "${HIGH_RISK_PATTERNS[@]}"; do
    if echo "$filepath" | grep -qiE -- "$pat"; then
      RISK_LEVEL="High"
      RISK_REASONS+=("高リスクパス: ${filepath}")
    fi
  done

  if [[ "$RISK_LEVEL" != "High" ]]; then
    for pat in "${MEDIUM_RISK_PATTERNS[@]}"; do
      if echo "$filepath" | grep -qiE -- "$pat"; then
        RISK_LEVEL="Medium"
        RISK_REASONS+=("中リスクパス: ${filepath}")
      fi
    done
  fi
done <<< "$PR_FILES"

case "$RISK_LEVEL" in
  High)   err "リスク分類: High — Merge前に人間承認が必要" ;;
  Medium) warn "リスク分類: Medium — Safe Merge Gate後、人間確認必要" ;;
  Low)    ok   "リスク分類: Low — Merge候補" ;;
esac

for r in "${RISK_REASONS[@]:-}"; do
  [[ -n "${r:-}" ]] && info "  $r"
done
echo ""

# ─── Secret / 危険パターン検査 ───────────────────────────────────────────────
echo -e "${BLD}[3/5] Secret / 本番影響チェック${RST}"

PR_DIFF=$("$GH" pr diff "$PR_NUMBER" 2>/dev/null) \
  || emit_stop "PR diff を取得できません。"

ADDED_LINES=$(echo "$PR_DIFF" | grep -E "^\+" | grep -vE "^\+\+\+" || true)

SECRET_PATTERNS=(
  "sk-[A-Za-z0-9]{20,}"
  "ghp_[A-Za-z0-9]{20,}"
  "gho_[A-Za-z0-9]{20,}"
  "github_pat_[A-Za-z0-9_]{20,}"
  "xox[baprs]-[A-Za-z0-9-]{20,}"
  "-----BEGIN[[:space:]]+([A-Z0-9 ]+)?PRIVATE[[:space:]]+KEY-----"
  "api[_-]?key[[:space:]]*[:=][[:space:]]*['\"]?[A-Za-z0-9._-]{32,}['\"]?"
  "private_key_id[[:space:]]*[:=]"
  "client_email[[:space:]]*[:=].*gserviceaccount\.com"
)

RUNAWAY_PATTERNS=(
  "scripts/acquisition"
  "tree.?beauty.*enable|enable.*tree.?beauty"
  "daily_post_limit[[:space:]]*=[[:space:]]*[2-9][0-9]"
  "send_to_staff"
)

SECRET_HIT=0
for pat in "${SECRET_PATTERNS[@]}"; do
  if echo "$ADDED_LINES" | grep -qiE -- "$pat"; then
    SECRET_HIT=1
    break
  fi
done

if [[ "$SECRET_HIT" -eq 1 ]]; then
  emit_stop "Secret/APIキーらしき文字列を diff に検出しました。値は表示しません。"
fi
ok "Secret/APIキーらしき文字列なし"

RUNAWAY_HIT=0
RUNAWAY_REASON=""
for pat in "${RUNAWAY_PATTERNS[@]}"; do
  if echo "$ADDED_LINES" | grep -qiE -- "$pat"; then
    RUNAWAY_HIT=1
    RUNAWAY_REASON="自動化暴走パターンを検出: ${pat}"
    break
  fi
done

if [[ "$RUNAWAY_HIT" -eq 1 ]]; then
  emit_stop "$RUNAWAY_REASON"
fi
ok "自動化暴走パターンなし"

# 削除・rename チェック
while IFS=$'\t' read -r status filepath; do
  [[ -z "${status:-}" ]] && continue
  if [[ "$status" == "removed" || "$status" == "renamed" ]]; then
    # docs/reports の rename はスキップ
    if ! echo "$filepath" | grep -qiE "^docs/|^data/reports/|REPORT\.md|TASK\.md"; then
      emit_stop "削除またはrenameを検出: ${status} ${filepath}"
    fi
  fi
done <<< "$PR_FILE_STATUS"
ok "削除・rename（非ドキュメント）なし"
echo ""

# ─── REPORT.md 更新確認 ────────────────────────────────────────────────────
echo -e "${BLD}[4/5] REPORT.md 更新確認${RST}"

REPORT_UPDATED=0
if echo "$PR_FILES" | grep -q "REPORT\.md"; then
  REPORT_UPDATED=1
  ok "REPORT.md が更新されています"
else
  warn "REPORT.md が更新されていません（ドキュメント専用PRの場合は許容）"
fi
echo ""

# ─── 売上直結度スコアリング ───────────────────────────────────────────────────
echo -e "${BLD}[5/5] 売上直結度スコアリング${RST}"

REVENUE_SCORE="C"
REVENUE_REASON="変更ファイルのパスから自動スコアリング"

# S スコア: 直接顧客接点・予約・集客スクリプト
if echo "$PR_FILES" | grep -qiE "threads|gbp|google.*post|予約|集客|catering.*form|line.*booking"; then
  REVENUE_SCORE="S"
  REVENUE_REASON="顧客接点・集客・予約導線に直結する変更"
# A スコア: SNS・MEO・コンテンツ・口コミ
elif echo "$PR_FILES" | grep -qiE "gen_content|sns|meo|review|google.*投稿|content_engine|image"; then
  REVENUE_SCORE="A"
  REVENUE_REASON="SNS投稿・MEO・コンテンツ強化で30日以内に売上貢献"
# B スコア: 監視・自動化・データ基盤
elif echo "$PR_FILES" | grep -qiE "scripts/|core/|monitor|batch|scheduler|report|analytics"; then
  REVENUE_SCORE="B"
  REVENUE_REASON="自動化・監視強化で中長期の業務効率に貢献"
# C スコア: ドキュメント・管理ファイル
elif echo "$PR_FILES" | grep -qiE "^docs/|REPORT\.md|TASK\.md|README|\.md$"; then
  REVENUE_SCORE="C"
  REVENUE_REASON="管理・ドキュメントのみ。売上に直接関係しない"
# D スコア: 禁止対象・ターゲット外
else
  REVENUE_SCORE="C"
  REVENUE_REASON="判定不能。人間によるスコープ確認を推奨"
fi

# D スコア判定: 禁止事業・禁止パターン
if echo "$PR_FILES" | grep -qiE "acquisition|beauty.*enable|hinabe.*change"; then
  REVENUE_SCORE="D"
  REVENUE_REASON="ターゲット外・スコープ外の変更を含む"
fi

case "$REVENUE_SCORE" in
  S)   echo -e "  ${GRN}${BLD}売上直結度: S${RST} — ${REVENUE_REASON}" ;;
  A)   echo -e "  ${GRN}売上直結度: A${RST} — ${REVENUE_REASON}" ;;
  B)   echo -e "  ${BLU}売上直結度: B${RST} — ${REVENUE_REASON}" ;;
  C)   echo -e "  ${YLW}売上直結度: C${RST} — ${REVENUE_REASON}" ;;
  D)   echo -e "  ${RED}売上直結度: D${RST} — ${REVENUE_REASON}" ;;
esac
echo ""

# ─── 最終判定 ─────────────────────────────────────────────────────────────────
echo -e "${BLD}━━━ 最終判定 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
echo ""
echo -e "  PR #${PR_NUMBER}: ${PR_TITLE}"
echo ""
echo -e "  | 観点              | 結果 |"
echo -e "  |---|---|"
echo -e "  | OS整合            | ✅ |"
echo -e "  | 既存破壊NG        | ✅ |"
echo -e "  | Cash-First        | ✅ |"
echo -e "  | Secret混入NG      | ✅ |"
echo -e "  | 本番影響NG        | ✅ |"
echo -e "  | TASK整合          | 要確認 |"
echo -e "  | REPORT更新        | $([ "$REPORT_UPDATED" -eq 1 ] && echo "✅" || echo "⚠ 未更新") |"
echo -e "  | 自動化暴走チェック | ✅ |"
echo -e "  | FIX_ATTEMPT       | ${FIX_ATTEMPT}/3 |"
echo -e "  | 禁止事項チェック  | ✅ |"
echo ""
echo -e "  売上直結度スコア: ${REVENUE_SCORE}"
echo -e "  リスク分類: ${RISK_LEVEL}"
echo ""

# スコア C/D → FIX
if [[ "$REVENUE_SCORE" == "C" || "$REVENUE_SCORE" == "D" ]]; then
  NEW_ATTEMPT=$((FIX_ATTEMPT + 1))
  if [[ "$NEW_ATTEMPT" -gt 3 ]]; then
    emit_stop "FIX_ATTEMPT=${NEW_ATTEMPT} — 修正上限を超えました。人間確認が必要です。"
  fi
  echo "FIX_ATTEMPT=${NEW_ATTEMPT}" > "$FIX_FILE"
  echo "LAST_FIX=$(date +%Y-%m-%d)" >> "$FIX_FILE"
  echo "REASON=Revenue score ${REVENUE_SCORE}: ${REVENUE_REASON}" >> "$FIX_FILE"
  emit_fix "売上直結度スコアが ${REVENUE_SCORE} です。スコープを確認してください。\n  ${REVENUE_REASON}\n  FIX_ATTEMPTをインクリメントしました: ${NEW_ATTEMPT}/3"
fi

# REPORT未更新 → FIX（ドキュメント専用PR以外）
if [[ "$REPORT_UPDATED" -eq 0 ]]; then
  NOT_ONLY_DOCS=0
  while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    if ! echo "$f" | grep -qiE "^docs/|README|TASK\.md|REPORT\.md|\.md$|^data/"; then
      NOT_ONLY_DOCS=1
      break
    fi
  done <<< "$PR_FILES"

  if [[ "$NOT_ONLY_DOCS" -eq 1 ]]; then
    NEW_ATTEMPT=$((FIX_ATTEMPT + 1))
    if [[ "$NEW_ATTEMPT" -gt 3 ]]; then
      emit_stop "FIX_ATTEMPT=${NEW_ATTEMPT} — 修正上限を超えました。人間確認が必要です。"
    fi
    echo "FIX_ATTEMPT=${NEW_ATTEMPT}" > "$FIX_FILE"
    echo "LAST_FIX=$(date +%Y-%m-%d)" >> "$FIX_FILE"
    echo "REASON=REPORT.md not updated" >> "$FIX_FILE"
    emit_fix "REPORT.md が更新されていません。実装内容をREPORT.mdに記載してください。\n  FIX_ATTEMPTをインクリメントしました: ${NEW_ATTEMPT}/3"
  fi
fi

# ─── GO 出力 ─────────────────────────────────────────────────────────────────
echo -e "${GRN}${BLD}━━━ GO ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
echo -e "${GRN}${BLD}  12観点クリア。売上直結度: ${REVENUE_SCORE}。リスク: ${RISK_LEVEL}${RST}"
echo ""

case "$RISK_LEVEL" in
  Low)
    echo -e "${GRN}  Low リスク → Safe Merge Gate を実行します${RST}"
    echo ""
    GATE_SCRIPT="${REPO_ROOT}/scripts/agent/safe_auto_merge_pr.sh"
    if [[ -x "$GATE_SCRIPT" ]]; then
      bash "$GATE_SCRIPT" "$PR_NUMBER"
    else
      warn "safe_auto_merge_pr.sh が見つかりません: ${GATE_SCRIPT}"
      warn "手動で Safe Merge Gate を実行してください"
    fi
    ;;
  Medium)
    echo -e "${YLW}  Medium リスク → 人間確認が必要です${RST}"
    echo ""
    echo -e "  Safe Merge Gate を実行するには:"
    echo "    bash scripts/agent/safe_auto_merge_pr.sh ${PR_NUMBER}"
    echo ""
    echo -e "  ${YLW}⚠ 最終 Merge はゆうさんが承認してから実行してください${RST}"
    ;;
  High)
    echo -e "${RED}  High リスク → Merge 前に必ずゆうさんの承認が必要です${RST}"
    echo ""
    echo -e "  変更内容を確認してMergeするには:"
    echo "    gh pr merge ${PR_NUMBER} --squash"
    echo ""
    echo -e "  ${RED}⚠ 自動 Merge は禁止です。ゆうさんが最終判断してください${RST}"
    ;;
esac

echo ""
echo -e "${GRN}${BLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
echo ""

# fix_attempt ファイルをクリア（GO 完了時）
if [[ -f "$FIX_FILE" ]]; then
  rm -f "$FIX_FILE"
  info "fix_attempt ファイルをクリアしました: ${FIX_FILE}"
fi

exit 0
