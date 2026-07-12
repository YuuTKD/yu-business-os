# TASK.md — 実装タスク指示書

---

## 現在のタスク

| 項目 | 内容 |
|---|---|
| **タスクID** | TASK-001 |
| **ステータス** | DONE |
| **担当** | Claude Code |
| **作成日** | 2026-07-08 |
| **完了日** | 2026-07-08 |

### 概要

Codex × Claude Code × GitHub PR 連携ワークフローの初期運用ファイルを追加する。

### 背景

YU HOLDINGS の AI-EOS を安全に拡張するため、Claude Code を司令塔・Codex を実装部隊とする役割分担を確立する。本番影響・Secret混入・既存構成破壊を防ぐ安全ゲートとして GitHub PR フローを組み込む。

### 完了条件

- [ ] `CLAUDE.md` 作成済み
- [ ] `AGENTS.md` 作成済み
- [ ] `TEAM_RULES.md` 作成済み
- [ ] `TASK.md` 作成済み（このファイル）
- [ ] `REPORT.md` 作成済み
- [ ] `.github/pull_request_template.md` 作成済み

### 実装スコープ

**変更してよいファイル（新規作成のみ）：**
- `CLAUDE.md`
- `AGENTS.md`
- `TEAM_RULES.md`
- `TASK.md`
- `REPORT.md`
- `.github/pull_request_template.md`

**変更禁止：**
- 既存の全ファイル（`core/`, `ceo/`, `configs/`, `skills/` 等）
- `.env.local`
- `Dockerfile`
- `requirements.txt`

### 確認事項

（Codex が不明点を記入する欄）

---

## 次タスク候補

新しいタスクはこのセクション以下に追記する。

```
## TASK-008（タスクタイトル）
ステータス: TODO
概要:
完了条件:
スコープ:
```

## TASK-007 YU Business OS 2.0 Phase B2-2 — TACHINOMIYA SSOT primary + Legacy fallback
ステータス: DONE（2026-07-11 / feat/tachinomiya-ssot-primary-with-legacy-fallback）
概要:
  TACHINOMIYA のみ設定読込の第一候補を SSOT に切替可能にする（Legacy fallback・
  owner 承認必須）。mismatch は fallback せず FIX/STOP。SSOT_ONLY 禁止。
完了条件:
  - [x] core/business_config/runtime_resolver.py（4 mode・fail-closed）
  - [x] scripts/business_config/check_tachinomiya_runtime.py（exit 0/10/20/30/40/50）
  - [x] SSOT は承認+mismatch 0+有効時のみ / 他事業 STOP / rollback=LEGACY_ONLY
  - [x] Unit Test 25件追加 / 合計 206件 全 pass
  - [x] Runtime CLI 承認 GO(SSOT) / 未承認 OWNER_APPROVAL_REQUIRED
スコープ（追加のみ・本番常時経路 未切替）:
  - core/business_config/ · scripts/business_config/ · tests/business_config/
  - docs/YU_BUSINESS_OS_2_*.md · REPORT.md · TASK.md

## TASK-006 YU Business OS 2.0 Phase B2-1 — TACHINOMIYA SSOT Shadow 接続
ステータス: DONE（2026-07-11 / feat/tachinomiya-ssot-shadow-connection）
概要:
  TACHINOMIYA の Legacy 設定と SSOT を実行時比較する Shadow Adapter を追加。
  runtime_source は常に LEGACY（本番読込先は切替えない）。
完了条件:
  - [x] core/business_config/shadow_adapter.py（OFF/SHADOW_ONLY/ENFORCE_COMPARE）
  - [x] scripts/business_config/check_tachinomiya_shadow.py（exit 0/1/2/3）
  - [x] runtime_source=LEGACY 不変・SSOT 値を本番へ流さない
  - [x] Unit Test 20件追加 / 合計 181件 全 pass
  - [x] Shadow CLI GO / exit 0 / mismatch 0
スコープ（追加のみ・本番未切替）:
  - core/business_config/ · scripts/business_config/ · tests/business_config/
  - docs/YU_BUSINESS_OS_2_*.md · REPORT.md · TASK.md

## TASK-005 YU Business OS 2.0 Phase B1.1 — Business Config 不一致の解消
ステータス: DONE（2026-07-11 / feat/yu-business-os-2-resolve-config-mismatches）
概要:
  B1 で検出した5件の不一致をゆうさん確定値で解消し、Business Config CLI を
  GO/exit 0（mismatch 0）にする。legacy alias は削除せず併存（互換期間）。
完了条件:
  - [x] TACHINOMIYA 目標 5.5M（昼2.5M+夜3.0M）へ legacy 統一 + 内訳 API
  - [x] 火鍋 canonical ryukyu_hinabe / alias hinabe
  - [x] LINE canonical/alias（tachinomiya/catering/hinabe）
  - [x] comparator の alias 解決・昼夜整合・循環検知
  - [x] Unit Test 19件追加 / 合計 161件 全 pass
  - [x] Business Config CLI GO / exit 0
スコープ:
  - configs/business_registry.py · core/system_health.py · ceo/executive_team.py（値のみ）
  - configs/businesses/registry.yaml · core/business_config/ · tests/business_config/
  - docs/YU_BUSINESS_OS_2_*.md · REPORT.md · TASK.md

## TASK-004 YU Business OS 2.0 Phase B1 — Business Config SSOT（Shadow）
ステータス: DONE（2026-07-11 / feat/yu-business-os-2-business-config-ssot）
概要:
  6事業の設定を単一正本（shadow）で表現し、既存設定との差分を自動検査する。
  本番接続・既存設定の削除/上書き/切替は行わない（Shadow Mode）。
完了条件:
  - [x] configs/businesses/registry.yaml（6事業・secret-free）
  - [x] core/business_config/（models/loader/legacy_adapter/comparator）
  - [x] scripts/business_config/validate_business_configs.py（exit 0/1/2/3）
  - [x] Unit Test 47件追加 / 合計 142件 全 pass
  - [x] 設計書5件へ役割別に追記
スコープ（追加のみ・既存無変更）:
  - configs/businesses/ · core/business_config/ · scripts/business_config/
  - tests/business_config/ · docs/YU_BUSINESS_OS_2_*.md · REPORT.md · TASK.md

## TASK-003 YU Business OS 2.0 Phase D-Lite — Governance × PR Auto Flow
ステータス: DONE（2026-07-11 / feat/yu-business-os-2-governance-pr-gate）
概要:
  Phase A の Governance Validator を既存 PR 自動フローへ安全に接続し、
  PR ごとに GO / FIX / STOP / OWNER_APPROVAL_REQUIRED を機械判定する。
  gh 非依存・fail-closed・自動 Merge なし・外部送信なし。
完了条件:
  - [x] scripts/agent/governance_gate.py（exit 0/10/20/30/40）
  - [x] core/governance/diff_risk.py（分類・単一ソース）
  - [x] core/governance/validator.py に pr_change_review 追加
  - [x] pr_auto_flow.sh Step 0 に接続（fail-closed）
  - [x] Unit Test 39件追加 / 合計 91件 全 pass
  - [x] 既存ドキュメント4件へ役割別に追記
スコープ（追加中心・既存 gh 処理は不変）:
  - scripts/agent/ · core/governance/ · tests/agent/ · tests/governance/
  - docs/AUTO_PR_FLOW.md · .claude/commands/pr-auto-flow.md
  - docs/YU_BUSINESS_OS_2_{ROADMAP,EXECUTIVE_SUMMARY}.md · REPORT.md · TASK.md

## TASK-002 YU Business OS 2.0 Phase A — Registry & Governance 土台
ステータス: DONE（2026-07-11 / feat/yu-business-os-2-phase-a-registry-governance）
概要:
  2.0 設計に基づく最小安全実装。Skill Registry / Agent Registry /
  Governance Policy / Loader / Validator / 整合性 CLI / Unit Test を追加する。
  既存機能への本番接続・deploy・Scheduler 変更・外部送信は行わない。
完了条件:
  - [x] configs/skills/registry.yaml（10件）
  - [x] configs/agents/registry.yaml（9件・全 default deny）
  - [x] configs/governance/policies.yaml（21ポリシー）
  - [x] core/registry/*（models / skill / agent / yaml_min）
  - [x] core/governance/validator.py（GO/FIX/STOP/OWNER_APPROVAL）
  - [x] scripts/registry/validate_registry.py（exit 0/1/2）
  - [x] Unit Test 52件 全 pass
  - [x] 設計書5件へ実装状況を追記
スコープ（新規追加のみ・既存無変更）:
  - configs/{skills,agents,governance}/ · core/{registry,governance}/
  - scripts/registry/ · tests/ · docs/YU_BUSINESS_OS_2_*.md · REPORT.md · TASK.md


## Safe Merge Audit Gate 運用ルール

yu-business-os 本体では、PRの自動Merge実行は禁止する。

目的：
- 低リスクPRかどうかを監査する
- 危険PRをSTOPする
- Merge可否判断を補助する

運用：
- `scripts/agent/safe_auto_merge_pr.sh <PR番号>` は監査専用
- Mergeは必ず人間承認後に `gh pr merge <PR番号> --squash` で実行
- `AUTO_MERGE=1` は yu-business-os では使用禁止

必須条件：
- `safe-auto-merge` ラベルあり
- Draft PRではない
- reviewDecision が APPROVED
- CI/status check が未完了・失敗ではない
- 変更ファイルが docs / templates / reports / README / TASK / REPORT / PRテンプレのみ
- Secret/APIキーらしき文字列なし
- deploy / scheduler / auth / customer / payment などの危険語なし
- 削除/renameなし

自動Merge禁止対象：
- scripts
- agents
- skills
- core
- configs
- businesses
- knowledge
- .env
- Cloud Run
- Scheduler
- SNS投稿
- DM送信
- Gmail/LINE送信
- 決済
- 認証
- 顧客データ
