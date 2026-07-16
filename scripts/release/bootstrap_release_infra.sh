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
RETENTION_SECONDS="34560000"   # ~400 days audit retention
ENVIRONMENT="production"

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
  local pnum
  pnum="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)' 2>/dev/null || echo '<PROJECT_NUMBER>')"

  say "1) Workload Identity Pool"
  run_or_plan "create WIF pool ${POOL_ID}" \
    gcloud iam workload-identity-pools create "$POOL_ID" \
      --project="$PROJECT" --location=global --display-name="$POOL_DISPLAY"

  say "2) GitHub OIDC Provider (repo 限定 attribute condition)"
  run_or_plan "create OIDC provider ${PROVIDER_ID} (condition: ${ATTR_CONDITION})" \
    gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
      --project="$PROJECT" --location=global --workload-identity-pool="$POOL_ID" \
      --display-name="GitHub OIDC" \
      --issuer-uri="https://token.actions.githubusercontent.com" \
      --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
      --attribute-condition="$ATTR_CONDITION"

  say "3) Service Accounts (長期 key を作らない・WIF のみ)"
  for sa in "$SA_DEPLOYER" "$SA_VERIFIER" "$SA_LEDGER"; do
    run_or_plan "create SA ${sa}" \
      gcloud iam service-accounts create "$sa" --project="$PROJECT" \
        --display-name="release ${sa}"
  done

  say "4) SA IAM roles (least privilege)"
  # deployer: build + AR write + Cloud Run deploy + actAs runtime SA
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
  local principal="principalSet://iam.googleapis.com/projects/${pnum}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${GH_REPO}"
  for sa in "$SA_DEPLOYER" "$SA_VERIFIER" "$SA_LEDGER"; do
    run_or_plan "bind workloadIdentityUser: repo=${GH_REPO} -> ${sa}" \
      gcloud iam service-accounts add-iam-policy-binding "${sa}@${SA_DOMAIN}" \
        --project="$PROJECT" --role="roles/iam.workloadIdentityUser" --member="$principal"
  done

  say "6) Artifact Registry (docker, ${REGION})"
  run_or_plan "create AR repo ${AR_REPO}" \
    gcloud artifacts repositories create "$AR_REPO" --project="$PROJECT" \
      --repository-format=docker --location="$REGION" --description="YU release images"

  say "7) GCS Ledger bucket (append-only)"
  run_or_plan "create bucket gs://${LEDGER_BUCKET}" \
    gcloud storage buckets create "gs://${LEDGER_BUCKET}" --project="$PROJECT" \
      --location="$REGION" --uniform-bucket-level-access --public-access-prevention
  run_or_plan "enable object versioning" \
    gcloud storage buckets update "gs://${LEDGER_BUCKET}" --versioning
  run_or_plan "set retention ${RETENTION_SECONDS}s (~400d)" \
    gcloud storage buckets update "gs://${LEDGER_BUCKET}" --retention-period="${RETENTION_SECONDS}"
  # ledger SA: objectCreator only (create, NOT overwrite/delete) — append-only
  run_or_plan "grant objectCreator (append-only) on bucket -> ${SA_LEDGER}" \
    gcloud storage buckets add-iam-policy-binding "gs://${LEDGER_BUCKET}" \
      --member="serviceAccount:${SA_LEDGER}@${SA_DOMAIN}" --role="roles/storage.objectCreator"
  # verifier can read the ledger
  run_or_plan "grant objectViewer on bucket -> ${SA_VERIFIER}" \
    gcloud storage buckets add-iam-policy-binding "gs://${LEDGER_BUCKET}" \
      --member="serviceAccount:${SA_VERIFIER}@${SA_DOMAIN}" --role="roles/storage.objectViewer"

  say "8) GitHub Actions repo variables (workflow が infra 名を知るため・Secret ではない)"
  run_or_plan "set repo variables" bash -c ':'  # placeholder printed below
  cat <<EOF
         # gh variable set RELEASE_PROJECT   -R ${GH_REPO} -b "${PROJECT}"
         # gh variable set RELEASE_REGION    -R ${GH_REPO} -b "${REGION}"
         # gh variable set RELEASE_AR_REPO   -R ${GH_REPO} -b "${AR_REPO}"
         # gh variable set LEDGER_BUCKET     -R ${GH_REPO} -b "${LEDGER_BUCKET}"
         # gh variable set WIF_PROVIDER      -R ${GH_REPO} -b "projects/${pnum}/locations/global/workloadIdentityPools/${POOL_ID}/providers/${PROVIDER_ID}"
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
