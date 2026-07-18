#!/usr/bin/env bash
# YU Release & Operations OS — Phase R2.5 Release Infrastructure Bootstrap
#
# WIF + 3 least-privilege service accounts + Artifact Registry + append-only GCS
# Ledger bucket + (best-effort) GitHub Environment. Safe, idempotent, auditable.
#
# MODES (default = plan; plan/verify/rollback-plan never mutate anything):
#   --plan           変更予定のみ表示・一切変更しない（既定）
#   --verify         read-only で各リソースの存在を確認（READY / MISSING）
#   --rollback-plan  削除せず「戻し方」だけ表示
#   --apply          明示指定 + CONFIRM=yes のときだけ実際に作成（人間が実行）
#
# SECURITY: 長期 SA key を作らない（WIF のみ）。Secret 値を出力・保存しない。
#           Cloud Scheduler には一切触れない。Production traffic を変更しない。
set -Eeuo pipefail

# ── fixed values (SSOT) ───────────────────────────────────────────────────────
PROJECT="tree-beauty-ai-499303"
REGION="asia-northeast1"
GH_REPO="YuuTKD/yu-business-os"

POOL_ID="github-release-pool"
POOL_DISPLAY="GitHub Release Pool"
PROVIDER_ID="github-oidc"
ATTR_CONDITION="assertion.repository == '${GH_REPO}'"

SA_DEPLOYER="release-deployer"
SA_VERIFIER="release-verifier"
SA_LEDGER="release-ledger"
SA_DOMAIN="${PROJECT}.iam.gserviceaccount.com"

AR_REPO="yu-release"
LEDGER_BUCKET="yu-release-ledger"
# gcloud storage --retention-period は単位付き duration が必須（例 1y36m / 400d）。
# 秒数の裸指定（例 34560000）は "Duration must end with time part character" で失敗する。
RETENTION_PERIOD="400d"          # 監査保持 400 日
RETENTION_TARGET_SECONDS="34560000"  # 400d を秒換算（describe は秒で返るため比較用）
# OWNER_ACCEPTED_EXCEPTION (2026-07-16): 実バケットの retention は 34495200s
# (≈399日18時間, 目標との差 18h) で設定済み。オーナーが運用上許容。retention policy は
# 変更せず lock もしない。verify はこの値を READY_WITH_EXCEPTION として扱う。
RETENTION_ACCEPTED_SECONDS="34495200"
ENVIRONMENT="production"
# Smoke test invoker: release-verifier needs roles/run.invoker on the SMOKE service
# ONLY (service-scoped, never project-wide) to call the authenticated candidate URL.
SMOKE_SERVICE="trees-catering-ai"

# Project number is NOT a secret (semi-public id). It is the expected value used
# to validate the number resolved dynamically from gcloud. Never use a literal
# a hardcoded project-number placeholder in any executed command (that caused STEP 5
# WIF-binding failure). Resolution is fail-closed (see resolve_project_number).
EXPECTED_PROJECT_NUMBER="75610219333"
PROJECT_NUMBER=""

MODE="plan"
case "${1:-}" in
  --plan|"") MODE="plan" ;;
  --verify) MODE="verify" ;;
  --rollback-plan) MODE="rollback-plan" ;;
  --apply) MODE="apply" ;;
  *) echo "unknown mode: ${1}"; echo "use --plan | --verify | --rollback-plan | --apply"; exit 2 ;;
esac

say()  { printf '\n\033[1m» %s\033[0m\n' "$*"; }
line() { printf '  %s\n' "$*"; }

# run_or_plan "<desc>" <cmd...>
#  - plan  : print only (NEVER executes; no gcloud call)
#  - apply : print + execute (fail-closed on error)
run_or_plan() {
  local desc="$1"; shift
  if [[ "$MODE" == "apply" ]]; then
    printf '  \033[32m[APPLY]\033[0m %s\n' "$desc"
    "$@"
  else
    printf '  [PLAN] %s\n' "$desc"
    printf '         $ %s\n' "$*"
  fi
}

# Resolve the project NUMBER dynamically and fail-closed. Sets PROJECT_NUMBER.
#   apply : gcloud value MUST be numeric AND == EXPECTED, else STOP.
#   plan/verify: prefer gcloud; if unavailable/non-numeric fall back to the known
#               EXPECTED constant (never a placeholder); mismatch → STOP.
resolve_project_number() {
  local n=""
  if command -v gcloud >/dev/null 2>&1; then
    n="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)' 2>/dev/null || true)"
  fi
  if [[ "$MODE" == "apply" ]]; then
    [[ -n "$n" ]] || { echo "STOP: project number を取得できません（空）。apply 中止。" >&2; exit 1; }
    [[ "$n" =~ ^[0-9]+$ ]] || { echo "STOP: project number が数字ではありません: '$n'。apply 中止。" >&2; exit 1; }
  else
    if [[ ! "$n" =~ ^[0-9]+$ ]]; then n="$EXPECTED_PROJECT_NUMBER"; fi
  fi
  if [[ "$n" != "$EXPECTED_PROJECT_NUMBER" ]]; then
    echo "STOP: project number 不一致（取得=$n / 想定=$EXPECTED_PROJECT_NUMBER）。中止。" >&2
    exit 1
  fi
  PROJECT_NUMBER="$n"
}

# create_idempotent "<desc>" "<exists-check cmd>" -- <create cmd...>
#   apply : run exists-check; SKIP if present, else create.
#   plan  : print intended create (marked idempotent).
create_idempotent() {
  local desc="$1" check="$2"; shift 2
  [[ "${1:-}" == "--" ]] && shift
  if [[ "$MODE" == "apply" ]]; then
    if eval "$check" >/dev/null 2>&1; then
      printf '  \033[33m[SKIP]\033[0m %s (既存)\n' "$desc"
    else
      printf '  \033[32m[APPLY]\033[0m %s\n' "$desc"
      "$@"
    fi
  else
    printf '  [PLAN] %s (idempotent: 既存ならSKIP)\n' "$desc"
    printf '         $ %s\n' "$*"
  fi
}

# ensure_retention: retention を安全に設定する。
#   plan  : 変更予定を表示（400d・単位付き）。
#   apply : describe で現在値を確認 → 未設定なら SET(400d) / 400d 済なら SKIP /
#           別値が設定済みなら STOP（勝手に変更しない）。
# describe の retention_period は秒で返るため RETENTION_TARGET_SECONDS と比較する。
ensure_retention() {
  if [[ "$MODE" != "apply" ]]; then
    printf '  [PLAN] set retention %s on gs://%s (未設定=SET / 400d済=SKIP / 別値=STOP)\n' "$RETENTION_PERIOD" "$LEDGER_BUCKET"
    printf '         $ gcloud storage buckets update gs://%s --retention-period=%s\n' "$LEDGER_BUCKET" "$RETENTION_PERIOD"
    return 0
  fi
  local cur
  cur="$(gcloud storage buckets describe "gs://${LEDGER_BUCKET}" \
        --format='value(retention_policy.retention_period)' 2>/dev/null || true)"
  cur="${cur//[^0-9]/}"   # keep digits only (seconds)
  if [[ -z "$cur" ]]; then
    printf '  \033[32m[APPLY]\033[0m set retention %s\n' "$RETENTION_PERIOD"
    gcloud storage buckets update "gs://${LEDGER_BUCKET}" --retention-period="${RETENTION_PERIOD}"
  elif [[ "$cur" == "$RETENTION_TARGET_SECONDS" ]]; then
    printf '  \033[33m[SKIP]\033[0m retention already 400d (%ss)\n' "$cur"
  elif [[ "$cur" == "$RETENTION_ACCEPTED_SECONDS" ]]; then
    printf '  \033[33m[SKIP]\033[0m retention %ss = OWNER_ACCEPTED_EXCEPTION (≈399d18h)。変更しません\n' "$cur"
  else
    echo "STOP: 別の retention が設定済み (${cur}s != 400d/accepted)。勝手に変更しません。" >&2
    exit 1
  fi
}

# ensure_run_invoker: release-verifier に SMOKE_SERVICE 単位で roles/run.invoker を付与。
#   plan  : 付与予定を表示。
#   apply : service 不存在 → STOP。既存の binding → SKIP。それ以外 → 付与。
# project 全体への run.invoker は付与しない（service-scoped のみ）。
ensure_run_invoker() {
  local member="serviceAccount:${SA_VERIFIER}@${SA_DOMAIN}"
  if [[ "$MODE" != "apply" ]]; then
    printf '  [PLAN] grant roles/run.invoker on %s -> %s (service単位・既存ならSKIP)\n' "$SMOKE_SERVICE" "$member"
    printf '         $ gcloud run services add-iam-policy-binding %s --region=%s --project=%s --member=%s --role=roles/run.invoker\n' \
      "$SMOKE_SERVICE" "$REGION" "$PROJECT" "$member"
    return 0
  fi
  gcloud run services describe "$SMOKE_SERVICE" --region="$REGION" --project="$PROJECT" >/dev/null 2>&1 \
    || { echo "STOP: Cloud Run service ${SMOKE_SERVICE} 不存在。invoker 付与中止。" >&2; exit 1; }
  if gcloud run services get-iam-policy "$SMOKE_SERVICE" --region="$REGION" --project="$PROJECT" \
       --flatten="bindings[].members" \
       --filter="bindings.role=roles/run.invoker AND bindings.members=${member}" \
       --format='value(bindings.role)' 2>/dev/null | grep -q "run.invoker"; then
    printf '  \033[33m[SKIP]\033[0m run.invoker 既存 (%s -> %s)\n' "$SMOKE_SERVICE" "$member"
  else
    printf '  \033[32m[APPLY]\033[0m grant run.invoker on %s -> %s\n' "$SMOKE_SERVICE" "$member"
    gcloud run services add-iam-policy-binding "$SMOKE_SERVICE" --region="$REGION" --project="$PROJECT" \
      --member="$member" --role="roles/run.invoker"
  fi
}

# ── apply guard (fail-closed) ─────────────────────────────────────────────────
if [[ "$MODE" == "apply" ]]; then
  command -v gcloud >/dev/null 2>&1 || { echo "STOP: gcloud 未導入。--apply 不可。"; exit 1; }
  [[ "${CONFIRM:-}" == "yes" ]] || {
    echo "STOP: --apply には CONFIRM=yes が必須（誤実行防止）。"
    echo "      例: CONFIRM=yes $0 --apply"
    exit 1
  }
  local_acct="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -1)"
  [[ -n "$local_acct" ]] || { echo "STOP: gcloud 有効アカウントなし。"; exit 1; }
  proj="$(gcloud config get-value project 2>/dev/null)"
  [[ "$proj" == "$PROJECT" ]] || { echo "STOP: project 不一致 ($proj != $PROJECT)。"; exit 1; }
fi

header() {
  say "Release Infra Bootstrap — mode=${MODE}"
  line "project=${PROJECT}  region=${REGION}  repo=${GH_REPO}"
  line "Cloud Scheduler / Production traffic には一切触れません。"
  if [[ "$MODE" == "plan" ]]; then line "これは PLAN です。変更は行いません。"; fi
  return 0
}

# ── plan / apply: create resources ────────────────────────────────────────────
do_plan_or_apply() {
  resolve_project_number   # sets PROJECT_NUMBER (fail-closed; never a placeholder)
  line "project_number=${PROJECT_NUMBER} (dynamic, validated)"

  say "1) Workload Identity Pool"
  create_idempotent "create WIF pool ${POOL_ID}" \
    "gcloud iam workload-identity-pools describe '$POOL_ID' --project='$PROJECT' --location=global" -- \
    gcloud iam workload-identity-pools create "$POOL_ID" \
      --project="$PROJECT" --location=global --display-name="$POOL_DISPLAY"

  say "2) GitHub OIDC Provider (repo 限定 attribute condition)"
  create_idempotent "create OIDC provider ${PROVIDER_ID} (condition: ${ATTR_CONDITION})" \
    "gcloud iam workload-identity-pools providers describe '$PROVIDER_ID' --project='$PROJECT' --location=global --workload-identity-pool='$POOL_ID'" -- \
    gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
      --project="$PROJECT" --location=global --workload-identity-pool="$POOL_ID" \
      --display-name="GitHub OIDC" \
      --issuer-uri="https://token.actions.githubusercontent.com" \
      --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
      --attribute-condition="$ATTR_CONDITION"

  say "3) Service Accounts (長期 key を作らない・WIF のみ)"
  for sa in "$SA_DEPLOYER" "$SA_VERIFIER" "$SA_LEDGER"; do
    create_idempotent "create SA ${sa}" \
      "gcloud iam service-accounts describe '${sa}@${SA_DOMAIN}' --project='$PROJECT'" -- \
      gcloud iam service-accounts create "$sa" --project="$PROJECT" \
        --display-name="release ${sa}"
  done

  say "4) SA IAM roles (least privilege)"
  # deployer: image push (AR write) + Cloud Run deploy + actAs runtime SA。
  # NOTE(R3): image は runner 上で docker build → AR push（release.yml, Option C）。
  #   Cloud Build / staging bucket は使わない（bucket buckets.get 権限問題の回避）。
  #   よって build に必須なのは artifactregistry.writer。cloudbuild.builds.editor は
  #   将来 Cloud Build を使う場合の予備として残す（build には不要）。
  for role in roles/run.developer roles/cloudbuild.builds.editor \
              roles/artifactregistry.writer roles/iam.serviceAccountUser; do
    run_or_plan "grant ${role} -> ${SA_DEPLOYER}" \
      gcloud projects add-iam-policy-binding "$PROJECT" \
        --member="serviceAccount:${SA_DEPLOYER}@${SA_DOMAIN}" --role="$role" --condition=None
  done
  # verifier: read-only (run + logs + AR read)
  for role in roles/run.viewer roles/logging.viewer roles/artifactregistry.reader; do
    run_or_plan "grant ${role} -> ${SA_VERIFIER}" \
      gcloud projects add-iam-policy-binding "$PROJECT" \
        --member="serviceAccount:${SA_VERIFIER}@${SA_DOMAIN}" --role="$role" --condition=None
  done
  # ledger: NO project role. Bucket-level objectCreator only (append-only) — set in step 7.

  say "5) WIF binding (repo の GitHub Actions → 各 SA を impersonate)"
  # principalSet は動的取得した実 project number を使う（プレースホルダは使わない）。
  local principal="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${GH_REPO}"
  # add-iam-policy-binding は冪等（同一 member+role の再付与は no-op 成功）。
  for sa in "$SA_DEPLOYER" "$SA_VERIFIER" "$SA_LEDGER"; do
    run_or_plan "bind workloadIdentityUser: repo=${GH_REPO} -> ${sa}" \
      gcloud iam service-accounts add-iam-policy-binding "${sa}@${SA_DOMAIN}" \
        --project="$PROJECT" --role="roles/iam.workloadIdentityUser" --member="$principal"
  done

  say "6) Artifact Registry (docker, ${REGION})"
  create_idempotent "create AR repo ${AR_REPO}" \
    "gcloud artifacts repositories describe '$AR_REPO' --project='$PROJECT' --location='$REGION'" -- \
    gcloud artifacts repositories create "$AR_REPO" --project="$PROJECT" \
      --repository-format=docker --location="$REGION" --description="YU release images"

  say "7) GCS Ledger bucket (append-only)"
  create_idempotent "create bucket gs://${LEDGER_BUCKET}" \
    "gcloud storage buckets describe 'gs://${LEDGER_BUCKET}'" -- \
    gcloud storage buckets create "gs://${LEDGER_BUCKET}" --project="$PROJECT" \
      --location="$REGION" --uniform-bucket-level-access --public-access-prevention
  run_or_plan "enable object versioning" \
    gcloud storage buckets update "gs://${LEDGER_BUCKET}" --versioning
  ensure_retention
  # ledger SA: objectCreator only (create, NOT overwrite/delete) — append-only
  run_or_plan "grant objectCreator (append-only) on bucket -> ${SA_LEDGER}" \
    gcloud storage buckets add-iam-policy-binding "gs://${LEDGER_BUCKET}" \
      --member="serviceAccount:${SA_LEDGER}@${SA_DOMAIN}" --role="roles/storage.objectCreator"
  # verifier can read the ledger
  run_or_plan "grant objectViewer on bucket -> ${SA_VERIFIER}" \
    gcloud storage buckets add-iam-policy-binding "gs://${LEDGER_BUCKET}" \
      --member="serviceAccount:${SA_VERIFIER}@${SA_DOMAIN}" --role="roles/storage.objectViewer"

  say "7b) Smoke invoker: release-verifier に run.invoker（${SMOKE_SERVICE} 単位）"
  ensure_run_invoker

  say "8) GitHub Actions repo variables (workflow が infra 名を知るため・Secret ではない)"
  run_or_plan "set repo variables" bash -c ':'  # placeholder printed below
  cat <<EOF
         # gh variable set RELEASE_PROJECT   -R ${GH_REPO} -b "${PROJECT}"
         # gh variable set RELEASE_REGION    -R ${GH_REPO} -b "${REGION}"
         # gh variable set RELEASE_AR_REPO   -R ${GH_REPO} -b "${AR_REPO}"
         # gh variable set LEDGER_BUCKET     -R ${GH_REPO} -b "${LEDGER_BUCKET}"
         # gh variable set WIF_PROVIDER      -R ${GH_REPO} -b "projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/providers/${PROVIDER_ID}"
         # gh variable set SA_DEPLOYER       -R ${GH_REPO} -b "${SA_DEPLOYER}@${SA_DOMAIN}"
         # gh variable set SA_VERIFIER       -R ${GH_REPO} -b "${SA_VERIFIER}@${SA_DOMAIN}"
         # gh variable set SA_LEDGER         -R ${GH_REPO} -b "${SA_LEDGER}@${SA_DOMAIN}"
EOF

  say "9) GitHub Environment '${ENVIRONMENT}' (required reviewer / main 限定)"
  echo "  MANUAL_STEP_REQUIRED: GitHub Environment の required reviewer 設定は"
  echo "    リポジトリのアクセス制御変更のため、オーナーが実施してください（下記 3 手順）。"
  echo "    1. Repo Settings → Environments → New environment → 'production'"
  echo "    2. Required reviewers に YuuTKD を追加"
  echo "    3. Deployment branches: 'Selected branches' → main のみ許可"
}

do_verify() {
  say "VERIFY (read-only)"
  local ok
  chk() { # <label> <cmd...>
    local label="$1"; shift
    if "$@" >/dev/null 2>&1; then printf '  \033[32mREADY\033[0m  %s\n' "$label"
    else printf '  \033[33mMISSING\033[0m %s\n' "$label"; fi
  }
  chk "WIF pool ${POOL_ID}" gcloud iam workload-identity-pools describe "$POOL_ID" --project="$PROJECT" --location=global
  chk "OIDC provider ${PROVIDER_ID}" gcloud iam workload-identity-pools providers describe "$PROVIDER_ID" --project="$PROJECT" --location=global --workload-identity-pool="$POOL_ID"
  for sa in "$SA_DEPLOYER" "$SA_VERIFIER" "$SA_LEDGER"; do
    chk "SA ${sa}" gcloud iam service-accounts describe "${sa}@${SA_DOMAIN}" --project="$PROJECT"
  done
  chk "Artifact Registry ${AR_REPO}" gcloud artifacts repositories describe "$AR_REPO" --project="$PROJECT" --location="$REGION"
  chk "Ledger bucket ${LEDGER_BUCKET}" gcloud storage buckets describe "gs://${LEDGER_BUCKET}"
  # retention = 400 日 (34560000s) を確認
  local rp
  rp="$(gcloud storage buckets describe "gs://${LEDGER_BUCKET}" \
        --format='value(retention_policy.retention_period)' 2>/dev/null || true)"
  rp="${rp//[^0-9]/}"
  if [[ "$rp" == "$RETENTION_TARGET_SECONDS" ]]; then
    printf '  \033[32mREADY\033[0m  Retention 400 日 (%ss)\n' "$rp"
  elif [[ "$rp" == "$RETENTION_ACCEPTED_SECONDS" ]]; then
    printf '  \033[32mREADY_WITH_EXCEPTION\033[0m Retention %ss ≈399d18h (OWNER_ACCEPTED 2026-07-16)\n' "$rp"
  elif [[ -z "$rp" ]]; then
    printf '  \033[33mMISSING\033[0m Retention 未設定\n'
  else
    printf '  \033[33mOTHER\033[0m  Retention %ss (!= 400 日 / accepted)\n' "$rp"
  fi
  # release-verifier run.invoker on the smoke service (service-scoped)
  local vmember="serviceAccount:${SA_VERIFIER}@${SA_DOMAIN}"
  if gcloud run services get-iam-policy "$SMOKE_SERVICE" --region="$REGION" --project="$PROJECT" \
       --flatten="bindings[].members" \
       --filter="bindings.role=roles/run.invoker AND bindings.members=${vmember}" \
       --format='value(bindings.role)' 2>/dev/null | grep -q "run.invoker"; then
    printf '  \033[32mREADY\033[0m  run.invoker (%s -> release-verifier, service単位)\n' "$SMOKE_SERVICE"
  else
    printf '  \033[33mMISSING\033[0m run.invoker (%s に release-verifier 未付与)\n' "$SMOKE_SERVICE"
  fi
  echo "  (GitHub Environment '${ENVIRONMENT}' は GitHub 側で確認: Settings → Environments)"
}

do_rollback_plan() {
  say "ROLLBACK PLAN (このスクリプトは削除しません。戻し方の表示のみ)"
  cat <<EOF
  # 逆順で削除（必要時に人間が実行）:
  gcloud storage buckets delete gs://${LEDGER_BUCKET}            # ※ retention 中は不可
  gcloud artifacts repositories delete ${AR_REPO} --location=${REGION} --project=${PROJECT}
  for sa in ${SA_DEPLOYER} ${SA_VERIFIER} ${SA_LEDGER}; do
    gcloud iam service-accounts delete \$sa@${SA_DOMAIN} --project=${PROJECT}
  done
  gcloud iam workload-identity-pools providers delete ${PROVIDER_ID} --location=global --workload-identity-pool=${POOL_ID} --project=${PROJECT}
  gcloud iam workload-identity-pools delete ${POOL_ID} --location=global --project=${PROJECT}
  # GitHub: Environment 'production' を Settings → Environments から削除
  # 一時停止だけなら: repo variable RELEASE_ENABLED=false（release.yml が起動時に停止）
EOF
}

header
case "$MODE" in
  plan|apply) do_plan_or_apply ;;
  verify)     do_verify ;;
  rollback-plan) do_rollback_plan ;;
esac

say "done (mode=${MODE})"
if [[ "$MODE" == "plan" ]]; then line "変更は行っていません。--apply は CONFIRM=yes + 人間承認で実行。"; fi
exit 0
