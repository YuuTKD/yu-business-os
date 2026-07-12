# REPORT.md — 実装完了報告書

---

## Phase B2-2 完了報告 — TACHINOMIYA SSOT primary + Legacy fallback

| 項目 | 内容 |
|---|---|
| **ブランチ** | feat/tachinomiya-ssot-primary-with-legacy-fallback |
| **報告者** | Claude Code |
| **報告日** | 2026-07-11 |
| **リスク分類** | High（`core/**` `scripts/**` 追加）|
| **売上直結度** | B（設定移行・監査性向上）|

### 実装したファイル（追加のみ）

| ファイル | 種別 | 概要 |
|---|---|---|
| `core/business_config/runtime_resolver.py` | ADDED | TACHINOMIYA 限定 source 選択（SSOT primary / Legacy fallback）|
| `scripts/business_config/check_tachinomiya_runtime.py` | ADDED | Runtime CLI（exit 0/10/20/30/40/50）|
| `tests/business_config/test_runtime_resolver.py` | ADDED | 25件 |
| `docs/YU_BUSINESS_OS_2_*.md`（3件）| MODIFIED | SSOT primary/fallback/rollback を役割別に追記 |

### runtime mode / source 選択

- モード: LEGACY_ONLY / SHADOW_ONLY / **SSOT_PRIMARY_WITH_LEGACY_FALLBACK** / SSOT_ONLY(**禁止=STOP**)
- SSOT 使用条件: owner 承認 + mismatch 0 + SSOT 有効 + migration ∈ {SHADOW_DEFINED, VERIFIED}
- fallback 条件: SSOT 読込失敗 / schema 不完全（**mismatch は fallback しない → FIX/STOP**）
- 未承認 → OWNER_APPROVAL_REQUIRED / 他事業 SSOT primary → STOP
- TACHINOMIYA 限定。他事業は常に LEGACY

### 安全設計

- SSOT 値は承認+一致時のみ返す。危険差分（昼夜不一致・他事業混入・secret）は STOP
- env 変数**名**のみ比較（token 値は読まず・出さず・ログしない）
- import 副作用なし（AST）・外部通信ゼロ・fail-closed
- 本番 main path 未変更（default OFF hook のみ）
- **rollback**: `--mode LEGACY_ONLY`（引数1つ）で即復旧・Legacy/alias 削除なし

### テスト実績

- `python3 -m unittest discover -s tests` → **Ran 206 tests OK**（+25）
- Runtime CLI: 未承認 rc=20 / 承認 rc=0（runtime_source=SSOT）/ SSOT_ONLY rc=40 / 他事業 rc=40
- Shadow CLI GO / Business Config CLI GO / Registry CLI GO / Secret scan CLEAN / 外部通信ゼロ

### 既存構成への影響チェック

- [x] 本番常時経路の切替：**なし**（承認時のみ SSOT・default OFF）
- [x] 他事業切替 / SSOT_ONLY：**なし**（STOP）
- [x] Legacy 削除 / alias 削除：**なし**
- [x] Cloud Run / Scheduler / 投稿 / LINE・Gmail / GCS・Sheets：**なし**
- [x] `scripts/acquisition` / Tree Beauty / `daily_post_limit`：**未変更**

### 人間承認が必要な項目

- Merge 実行（High → ゆうさん承認）/ Phase B2-3（本番経路接続）の開始可否

---

## Phase B2-1 完了報告 — TACHINOMIYA SSOT Shadow 接続

| 項目 | 内容 |
|---|---|
| **ブランチ** | feat/tachinomiya-ssot-shadow-connection |
| **報告者** | Claude Code |
| **報告日** | 2026-07-11 |
| **リスク分類** | High（`core/**` `scripts/**` 追加）|
| **売上直結度** | B（設定移行基盤・監査性向上）|

### 実装したファイル（追加のみ）

| ファイル | 種別 | 概要 |
|---|---|---|
| `core/business_config/shadow_adapter.py` | ADDED | TACHINOMIYA 限定 Legacy↔SSOT 比較。runtime_source=LEGACY 不変 |
| `scripts/business_config/check_tachinomiya_shadow.py` | ADDED | Shadow 検証 CLI（exit 0/1/2/3）|
| `tests/business_config/test_shadow_adapter.py` | ADDED | 20件 |
| `docs/YU_BUSINESS_OS_2_*.md`（3件）| MODIFIED | Shadow 接続・runtime_source=LEGACY を役割別に追記 |

### Shadow 接続の要点

- **runtime_source は常に LEGACY**（SSOT 値は本番へ渡さない・渡せば STOP）
- モード: OFF / SHADOW_ONLY(既定) / ENFORCE_COMPARE（引数・CLI・テスト限定・.env 保存なし）
- 比較は env 変数**名**のみ（token 値は読まず・出さず）
- fail-closed: unknown mode / 昼夜不一致 / 他事業混入 / production 誤表示 / import 副作用 → STOP
- 本番 main path は**未変更**（default OFF の hook のみ・強制接続なし）

### テスト実績

- `python3 -m unittest discover -s tests` → **Ran 181 tests OK**（+20）
- Shadow CLI SHADOW_ONLY/ENFORCE_COMPARE → **GO / exit 0 / mismatch 0**
- Business Config CLI GO / Registry CLI GO / `bash -n` OK / Secret scan CLEAN / 外部通信ゼロ

### 既存構成への影響チェック

- [x] 本番読込先切替：**なし**（runtime_source LEGACY）
- [x] Legacy 削除 / alias 削除：**なし**
- [x] Cloud Run / Scheduler / 投稿 / LINE・Gmail / GCS・Sheets：**なし**
- [x] `scripts/acquisition` / Tree Beauty / `daily_post_limit`：**未変更**
- [x] Secret 直書き：**なし**

### 人間承認が必要な項目

- Merge 実行（High → ゆうさん承認）/ Phase B2-2（実切替）の開始可否

---

## Phase B1.1 完了報告 — Business Config 不一致の解消

| 項目 | 内容 |
|---|---|
| **ブランチ** | feat/yu-business-os-2-resolve-config-mismatches |
| **報告者** | Claude Code |
| **報告日** | 2026-07-11 |
| **リスク分類** | High（既存 `core/**` `configs/**` の値変更を含む）|
| **売上直結度** | B（設定整合・監査性/売却可能性の向上）|

### 確定値（ゆうさん確定）

- TACHINOMIYA 月商目標: **5,500,000**（昼 2,500,000 + 夜 3,000,000）
- 火鍋 canonical id: `ryukyu_hinabe` / legacy alias: `hinabe`
- TACHINOMIYA staff LINE canonical: `LINE_TACHINOMIYA_STAFF_TOKEN` / legacy alias: `LINE_TACHINOMIYASTAFF_TOKEN`

### 変更したファイル

| ファイル | 種別 | 概要 |
|---|---|---|
| `configs/business_registry.py` | MODIFIED | tachinomiya monthly_target 3.5M→**5.5M** |
| `core/system_health.py` | MODIFIED | MONTHLY_TARGETS tachinomiya 3.5M→**5.5M** |
| `ceo/executive_team.py` | MODIFIED | BUSINESS_TARGETS TACHINOMIYA 1.2M→**5.5M** |
| `configs/businesses/registry.yaml` | MODIFIED | 昼夜内訳・slug alias(hinabe)・env alias 追加 |
| `core/business_config/models.py` | MODIFIED | day/night・slug_aliases・env aliases フィールド |
| `core/business_config/loader.py` | MODIFIED | 昼夜整合・alias 検証/解決・LINE channel API |
| `core/business_config/comparator.py` | MODIFIED | alias 解決で乖離を正常化 |
| `tests/business_config/test_resolve_mismatches.py` | ADDED | 19件 |
| `docs/YU_BUSINESS_OS_2_*.md`（4件）| MODIFIED | canonical/alias/互換期間を役割別に追記 |

### 解消結果

- Business Config CLI: **FIX(5件) → GO / exit 0 / mismatch 0**
- alias は削除せず併存（canonical 優先・legacy fallback）
- token 値は読まず・出さず（NAME のみ）/ staff 通知は owner approval 必須
- env 変数の実体名は変更なし（Cloud Run の実 env を壊さない）

### テスト実績

- `python3 -m unittest discover -s tests` → **Ran 161 tests OK**（+19）
- `python3 scripts/business_config/validate_business_configs.py` → **GO（exit 0）**
- Registry CLI GO / `bash -n` OK / Secret scan CLEAN / 外部通信ゼロ

### 既存構成への影響チェック

- [x] legacy alias 削除：**なし**（併存）
- [x] Cloud Run / Scheduler / 外部送信 / GCS / Sheets：**なし**
- [x] env 変数の実体・本番読込先切替：**なし**
- [x] `scripts/acquisition` / Tree Beauty / `daily_post_limit`：**未変更**
- [x] Secret 直書き：**なし**

### 人間承認が必要な項目

- Merge 実行（High → ゆうさん承認）/ Phase B2 開始可否

---

## Phase B1 完了報告 — Business Config SSOT（Shadow Mode）

| 項目 | 内容 |
|---|---|
| **ブランチ** | feat/yu-business-os-2-business-config-ssot |
| **報告者** | Claude Code |
| **報告日** | 2026-07-11 |
| **リスク分類** | High（`core/**` `configs/**` `scripts/**` への追加を含む）|
| **売上直結度** | B（設定二重管理の解消・売却可能性/監査性向上の基盤）|

### 実装したファイル（すべて新規追加・既存の変更/削除なし）

| ファイル | 変更種別 | 概要 |
|---|---|---|
| `configs/businesses/registry.yaml` | ADDED | 6事業 SSOT（shadow・env 名のみ・secret-free）|
| `core/business_config/models.py` | ADDED | スキーマ（dataclass + enum）|
| `core/business_config/loader.py` | ADDED | 読込・検証・クエリ（fail-closed）|
| `core/business_config/legacy_adapter.py` | ADDED | 既存設定を AST 静的読取（import/exec なし）|
| `core/business_config/comparator.py` | ADDED | SSOT↔Legacy 差分 → GO/FIX/STOP |
| `core/business_config/__init__.py` | ADDED | 公開 API |
| `scripts/business_config/validate_business_configs.py` | ADDED | 検証 CLI（exit 0/1/2/3）|
| `tests/business_config/*.py` | ADDED | Unit Test 47件 |
| `docs/YU_BUSINESS_OS_2_*.md`（5件）| MODIFIED | Phase B1 状況を役割別に追記 |

### 発見した既存の二重管理（Comparator が検出）

- 事業設定が 5 箇所に分散（`business_registry.py` / `_BUSINESS_CONFIGS` / `system_health.py` / `executive_team.py` / `entrypoint.py`）
- TACHINOMIYA 月商目標: `executive_team` 1,200,000 ≠ 正本 3,500,000
- `_BUSINESS_CONFIGS` に `ryukyu_hinabe` と重複する別名キー `hinabe`
- LINE トークン env 名が `business_registry.py` と `_BUSINESS_CONFIGS` で不一致（catering/tachinomiya/hinabe）

### Shadow Mode（本番未接続）

- 本番読込先は既存のまま（`business_registry.py` / `_BUSINESS_CONFIGS` を**削除も切替もしない**）
- 値の自動同期・自動上書きなし / `PRODUCTION_CONNECTED` なし（全事業 SHADOW_DEFINED）

### テスト実績

- `python3 -m unittest discover -s tests` → **Ran 142 tests OK**（47件追加）
- `python3 scripts/business_config/validate_business_configs.py` → **FIX（exit 1）**（実 legacy 乖離を正しく報告）
- `python3 scripts/registry/validate_registry.py` → GO（既存不変）/ `bash -n pr_auto_flow.sh` → OK
- Secret scan CLEAN / 外部通信ゼロ / AST 静的読取（exec/eval なし・import 副作用なし）

### 既存構成への影響チェック

- [x] 既存設定の削除・上書き・本番読込先切替：**なし**
- [x] Cloud Run / Scheduler / 外部送信 / GCS / Sheets：**なし**
- [x] `scripts/acquisition` / Tree Beauty / `daily_post_limit`：**未変更**
- [x] Secret 直書き：**なし**（env 名のみ）

### 人間承認が必要な項目

- Merge 実行（High → ゆうさん承認）/ Phase B2（本番接続）の開始可否

---

## Phase D-Lite 完了報告 — Governance Validator × PR Auto Flow 接続

| 項目 | 内容 |
|---|---|
| **ブランチ** | feat/yu-business-os-2-governance-pr-gate |
| **報告者** | Claude Code |
| **報告日** | 2026-07-11 |
| **リスク分類** | High（`core/**` `scripts/**` の変更を含む）|
| **売上直結度** | B（自動化ガバナンス強化・事故防止基盤）|

### 実装したファイル

| ファイル | 変更種別 | 概要 |
|---|---|---|
| `scripts/agent/governance_gate.py` | ADDED | ローカル diff アダプタ。diff収集→事実抽出→Validator呼出。exit 0/10/20/30/40 |
| `core/governance/diff_risk.py` | ADDED | ファイル→risk 分類・secret/runaway 検知（純関数・単一ソース）|
| `core/governance/validator.py` | MODIFIED | `pr_change_review` レビューアクションを追加 + `_norm` の `.env`/`.github` 判定バグ修正 |
| `scripts/agent/pr_auto_flow.sh` | MODIFIED | Step 0 に Governance Gate を接続（fail-closed）+ `emit_owner` 追加 |
| `tests/agent/test_governance_gate.py` | ADDED | ゲート 28 シナリオ + 統合テスト |
| `tests/governance/test_diff_risk.py` | ADDED | 分類器 単体テスト |
| `docs/AUTO_PR_FLOW.md` ほか docs 3件 | MODIFIED | Gate 実行位置・exit code・fail-closed を役割別に追記 |

### 接続方式（既存判定を重複させない）

- 決定ロジックは **Validator 一本**（gate は事実収集のみ）
- Shell は exit code だけ解釈（GO=0 / FIX=10 / OWNER=20 / STOP=30 / INTERNAL_ERROR=40）
- fail-closed: import/git/base-ref/unknown decision → INTERNAL_ERROR → STOP
- gh 非依存・GitHub API 不要・外部通信ゼロ

### テスト実績

- `python3 -m unittest discover -s tests` → **Ran 91 tests OK**（39件追加）
- `bash -n scripts/agent/pr_auto_flow.sh` → OK
- `python3 scripts/registry/validate_registry.py` → GO（exit 0・既存不変）
- Secret scan CLEAN（テスト fixture は実行時組み立てで自己検知を回避）

### 既存構成への影響チェック

- [x] 既存 pr_auto_flow.sh の gh ベース処理：**不変**（先頭に gate 追加のみ）
- [x] Cloud Run / Scheduler / 外部送信 / GCS / Sheets：**なし**
- [x] `scripts/acquisition` / Tree Beauty / `daily_post_limit`：**未変更**（gate が保護）
- [x] Secret 直書き：**なし**

### 人間承認が必要な項目

- Merge 実行（High リスク → ゆうさん最終承認）
- 次工程 Phase B の開始可否

---

## Phase A 完了報告 — YU Business OS 2.0 Registry & Governance 土台

| 項目 | 内容 |
|---|---|
| **ブランチ** | feat/yu-business-os-2-phase-a-registry-governance |
| **報告者** | Claude Code |
| **報告日** | 2026-07-11 |
| **リスク分類** | High（`core/**` `configs/**` `scripts/**` への追加を含む）|
| **売上直結度** | B（自動化・売却可能性を高める基盤。中長期）|

### 実装したファイル（すべて新規追加・既存の変更/削除/移動なし）

| ファイル | 変更種別 | 概要 |
|---|---|---|
| `configs/skills/registry.yaml` | ADDED | Skill Registry 10件（active 7 / inactive 3）|
| `configs/agents/registry.yaml` | ADDED | Agent Registry 9件（active 3 / inactive 6・全 default deny）|
| `configs/governance/policies.yaml` | ADDED | Governance Policy 21件 + リスク定義 |
| `core/registry/_yaml_min.py` | ADDED | 依存ゼロ YAML サブセットパーサ |
| `core/registry/models.py` | ADDED | dataclass + Enum（標準ライブラリのみ）|
| `core/registry/skill_registry.py` | ADDED | Skill Loader（fallback / path安全 / 重複検知）|
| `core/registry/agent_registry.py` | ADDED | Agent Loader（default deny / 参照整合）|
| `core/registry/__init__.py` | ADDED | 公開 API |
| `core/governance/validator.py` | ADDED | GO/FIX/STOP/OWNER_APPROVAL 判定（14段）|
| `core/governance/__init__.py` | ADDED | 公開 API |
| `scripts/registry/validate_registry.py` | ADDED | 整合性 CLI（exit 0/1/2）|
| `tests/registry/*.py`, `tests/governance/*.py` | ADDED | Unit Test 52件 |
| `docs/YU_BUSINESS_OS_2_*.md`（5件）| MODIFIED | Phase A 実装状況を役割別に追記 |

### 設計判断

- `config/` ではなく既存 `configs/` を採用（設計書「既存命名規約を優先」に一致）
- PyYAML / pytest 未インストール環境のため、YAML は内蔵パーサ・テストは stdlib `unittest`
- モデルは pydantic 未採用に合わせ標準ライブラリ dataclass

### テスト実績

- `python3 scripts/registry/validate_registry.py` → **RESULT: GO（exit 0）**
- `python3 -m unittest discover -s tests` → **Ran 52 tests OK**
- 検証済み: 外部通信ゼロ / Secret 出力ゼロ / SKILL.md 非実行 / path traversal 拒否 / default deny / 既存 namespace import 無破壊

### 既存構成への影響チェック

- [x] 既存ファイルの変更：**なし**（`docs/` 設計書追記のみ）
- [x] 既存 Agents / Skills / Knowledge の削除：**なし**
- [x] Cloud Run deploy / Scheduler 変更：**なし**（本番未接続）
- [x] 外部送信（LINE/Gmail/SNS）：**なし**
- [x] GCS / Sheets 書き込み：**なし**
- [x] `scripts/acquisition` 変更：**なし**
- [x] Tree Beauty 有効化 / `daily_post_limit` 変更：**なし**

### Secret混入チェック

- [x] APIキー・Secret の直書き：**なし**（secret scan clean）
- [x] `.env.local` の閲覧・変更：**なし**

### 人間承認が必要な項目

- Merge 実行（High リスク → ゆうさん最終承認）
- Phase B（設定二重管理の解消）の開始可否

---

## PR #5 完了報告 — TACHINOMIYA Google投稿ループ解消・画像向き修正

| 項目 | 内容 |
|---|---|
| **PR番号** | #5 |
| **ブランチ** | fix/tachinomiya-content-orientation |
| **報告者** | Claude Code |
| **報告日** | 2026-07-10 |
| **リスク分類** | High |
| **売上直結度** | A（Google投稿・SNS品質向上で30日以内に集客貢献） |

### 実装したファイル

| ファイル | 変更種別 | 概要 |
|---|---|---|
| `scripts/gen_content_3biz.py` | MODIFIED | TACHINOMIYAトピックを30件→90件に拡張・ループ解消。サーターアンダギー27/90=30.0%、昼間訴求強化 |
| `core/multi_business_content_engine.py` | MODIFIED | `_fetch_real_image`にImageOps.exif_transposeを追加（2行）。EXIF回転情報をピクセルに反映 |
| `scripts/gcs_beauty_batch.py` | MODIFIED | `_to_jpeg`にImageOps.exif_transposeを追加（2行）。BEAUTY画像GCS化の向き修正 |
| `scripts/gcs_tachinomiya_orientation_fix.py` | ADDED | TACHINOMIYA既存GCS画像の向き修正バッチ（手動実行専用）。--category/--limit/--idオプション付き |

### 修正内容の詳細

#### 1. TACHINOMIYA Google投稿ループ解消（gen_content_3biz.py）
- **問題**: TACHI 30件トピックが `i % 30` で循環し、90日分が3ループになっていた
- **修正**: TACHIを90件ユニークトピックに拡張。`i % 90 = i（i=0..89）`で全件ユニーク
- **サーターアンダギー**: 27/90件（30.0%）。昼間・午後・観光客向け訴求を重点配置
- **確認**: タイトル重複0件、本文重複0件

#### 2. Threads画像横向き修正（core/multi_business_content_engine.py, scripts/gcs_beauty_batch.py）
- **問題**: PIL.Image.open().convert("RGB")がEXIF向き情報を無視してピクセル展開
- **修正**: `ImageOps.exif_transpose()` を `.convert("RGB")` の前に追加
- **影響範囲**: TACHINOMIYA・CATERING・BEAUTY全事業の画像処理（既存ロジックは温存）

#### 3. 既存GCS画像向き修正スクリプト（scripts/gcs_tachinomiya_orientation_fix.py）
- **目的**: 既存のTACHINOMIYA GCS画像（横向き）を修正して再アップロードする
- **安全性**: 手動実行専用（Schedulerに未接続）。`--category BAR`等で小範囲テスト可能
- **実行方法**: `python3 scripts/gcs_tachinomiya_orientation_fix.py --category BAR --limit 5`

### 既存構成への影響チェック

- [x] 既存ファイルの変更：`core/multi_business_content_engine.py`（2行）・`scripts/gcs_beauty_batch.py`（2行）・`scripts/gen_content_3biz.py`（トピック拡張）
- [x] 既存 Agents / Skills / Knowledge の削除：**なし**
- [x] Scheduler変更：**なし**（Scheduler未接続のまま）
- [x] 自動送信：**なし**（すべて手動実行）
- [x] 本番GCS再アップロード：**未実行**（スクリプトは追加したが実行していない）
- [x] Tree Beauty有効化：**なし**

### Secret混入チェック

- [x] APIキー・Secret の直書き：**なし**（credentials.jsonはパス参照のみ）
- [x] `.env.local` の変更：**なし**
- [x] 顧客情報：**なし**

### テスト実績

- gen_content_3biz.py: Googleスプレッドシート直書きで90件ユニーク確認済み（タイトル重複0・本文重複0・サーターアンダギー27件）
- exif_transpose: PIL公式APIの標準的使用法。副作用なし
- gcs_tachinomiya_orientation_fix.py: dry-run未実施（本番実行前に `--limit 5` テスト推奨）

### 人間承認が必要な項目

- Merge実行（Highリスク → ゆうさん最終承認）
- `gcs_tachinomiya_orientation_fix.py` の本番実行（--category BAR --limit 5 からテスト開始推奨）

---

## TASK-001 完了報告

| 項目 | 内容 |
|---|---|
| **タスクID** | TASK-001 |
| **報告者** | Claude Code |
| **報告日** | 2026-07-08 |
| **PR番号** | （PR作成後に記入） |

### 実装したファイル

| ファイル | 変更種別 | 概要 |
|---|---|---|
| `CLAUDE.md` | 新規作成 | Claude Code 司令塔ルール・PRレビュー判定基準 |
| `AGENTS.md` | 新規作成 | Codex 実装部隊ルール・手順・禁止事項 |
| `TEAM_RULES.md` | 新規作成 | チーム全員共通ルール・フロー・ブランチ規則 |
| `TASK.md` | 新規作成 | 実装タスク指示テンプレート（TASK-001記入済み） |
| `REPORT.md` | 新規作成 | 実装完了報告テンプレート（このファイル） |
| `.github/pull_request_template.md` | 新規作成 | PRチェックリスト自動表示テンプレート |

### 既存構成への影響チェック

- [ ] 既存ファイルの変更：**なし**
- [ ] 既存 Agents / Skills / Knowledge の削除：**なし**
- [ ] `core/` `ceo/` `configs/` `skills/` への変更：**なし**

### Secret混入チェック

- [ ] APIキー・Secret の直書き：**なし**
- [ ] `.env.local` の変更：**なし**

### テスト

- ドキュメントのみの追加のため、自動テストなし
- 内容の整合性を目視確認済み

### 未解決事項・次タスク候補

なし

---

## 報告テンプレート（次回以降のコピー用）

```markdown
## TASK-XXX 完了報告

| 項目 | 内容 |
|---|---|
| **タスクID** | TASK-XXX |
| **報告者** | Codex |
| **報告日** | YYYY-MM-DD |
| **PR番号** | #XXX |

### 実装したファイル

| ファイル | 変更種別 | 概要 |
|---|---|---|

### 既存構成への影響チェック

- [ ] 既存ファイルの変更：
- [ ] 既存 Agents / Skills / Knowledge の削除：

### Secret混入チェック

- [ ] APIキー・Secret の直書き：
- [ ] `.env.local` の変更：

### テスト

### 未解決事項・次タスク候補
```
