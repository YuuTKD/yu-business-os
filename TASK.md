# TASK.md — 実装タスク指示書

---

## 現在のタスク

| 項目 | 内容 |
|---|---|
| **タスクID** | TASK-015 |
| **ステータス** | TODO（W1-1 設計文書は Claude Code 側で完了・以降を Codex が実装） |
| **担当** | Codex（実装）/ Claude Code（設計・レビュー） |
| **作成日** | 2026-07-27 |
| **リスク分類** | **High**（`core/**` `configs/**` 変更 ＋ 本番 Sheets のスキーマ変更を含む）|
| **対象事業** | `catering`（TREE's Catering）のみ |
| **対象外・不変** | beauty / tachinomiya / ryukyu_hinabe / pasta_pasta / z1 |

### 概要

TREE's Catering の「広告費ゼロ集客OS」Week 1 を実装する。既存の TREE's Catering
ワークブック（`CATERING_SPREADSHEET_ID`）内で完結させ、**新規アプリ・新規ワークブック・
新規依存・新規課金をいずれも発生させない**。

### 背景と設計判断（必読）

監査済み。以下3点が結論。詳細は `docs/catering-growth/repo-audit.md`。

1. 既存ワークブックに `02_問い合わせ`→`03_見積`→`04_受注管理`→`06_売上管理`→
   `07_利益管理` の14シートと営業CRM `CATERING_SALES_TARGETS`（22列・テンプレ20種）が
   すでに存在する。**作るのは新システムではなく既存表をつなぐ配管**。
2. **最大のギャップは UTM ではなく結合キーの欠落。** `02_問い合わせ` に主キーが無く、
   流入元別の受注売上・粗利が現状算出不能。ここが Week 1 の本命。
3. この OS に Web UI は無い。仕様書 §6「画面要件」は
   **Sheets のタブ設計 ＋ LINE の `OWNER_ONLY` 配信**として実装する（オーナー了承済）。

### 正典文書（実装前に必ず読む）

| 文書 | 内容 |
|---|---|
| `docs/catering-growth/YU_BusinessOS_TREEs_Catering_ZeroCost_Growth_Sprint.md` | 上位仕様 |
| `docs/catering-growth/repo-audit.md` | 監査結果・再利用可能な既存機能 |
| `docs/catering-growth/vocabulary.md` | **語彙の正典**（流入元12/ステータス13/種別11/UTM規則/ID形式/失注理由8）|
| `docs/catering-growth/sheet-schema.md` | **表の正典**（追加列・結合キー・数字の正本・マイグレーション手順）|
| `docs/catering-growth/operations-sop.md` | 運用手順・役割分担 |

**コードとこれら文書が矛盾した場合、文書が正しい。** 文書を変えたいときは実装を止めて
Claude Code に確認する（勝手に語彙やスキーマを変えない）。

### 実装単位（W1-2 〜 W1-9 / 1タスク=1PR）

W1-1（設計文書）は完了済み。以下を**この順に**実装する。

| # | 内容 | 主な成果物 |
|---|---|---|
| W1-2 | 語彙のコード化 | `configs/catering_growth_vocab.py` / `tests/catering_growth/test_vocabulary.py` `test_safety.py` |
| W1-3 | UTM URL 生成（純関数） | `core/catering_growth.py` `build_utm_url` `validate_utm_token` / `test_utm.py` |
| W1-4 | 現状シート棚卸し（**read-only**） | `core/catering_growth.py` `inspect()` / `test_inspect.py` |
| W1-5 | CRM 列拡張（+11列） | `ensure_columns()` / `core/catering_sales.py` 更新 / `test_ensure_columns.py` |
| W1-6 | ファネル結合キー付与（`02`+4 / `03`+1 / `04`+2） | `migrate_funnel_keys()` / `test_funnel_keys.py` |
| W1-7 | CSV import/export | `parse_contacts_csv()` `import_contacts()` / `test_csv_import.py` |
| W1-8 | 次アクション抽出（8ルール） | `next_actions()` ＋ `daily_action_commander` への供給 / `test_next_actions.py` |
| W1-9 | `GROWTH_DASHBOARD`（流入元別 受注/売上/粗利） | `aggregate_by_source()` `refresh_dashboard()` / `test_attribution.py` |

各単位の受入条件は `docs/catering-growth/repo-audit.md` §8 に全項目記載。**そこを満たすこと。**

### 実装スコープ

**変更してよいファイル：**
- `configs/catering_growth_vocab.py`（新規・語彙定数のみ）
- `core/catering_growth.py`（新規・**唯一の新規 core モジュール**）
- `core/catering_sales.py`（`CATERING_SHEETS` ヘッダに11列追記 ＋ `generate_test_data` を33列に）
- `core/entrypoint.py`（`@app.route` を最大5本**追加のみ**。既存ルートは触らない）
- `core/daily_action_commander.py`（catering のタスク供給元を1つ追加。**新規 Scheduler は作らない**）
- `tests/catering_growth/**`（新規）
- `.gitignore`（`data/catering_growth/*.csv` を追記）
- `docs/catering-growth/**` / `TASK.md` / `REPORT.md`

**変更禁止：**
- `scripts/acquisition/**` — **凍結パス**（`core/governance/validator.py:91`）。触ると PR が STOP
- `core/catering_setup.py` — ヘッダ行を上書きし追加列を消す。**実行も変更も禁止**
- `requirements.txt` / `requirements.lock` — **新規依存ゼロ ＝ 新規課金ゼロ**
- `.env` / `.env.template` / `configs/business_registry.py` の ID 実値
- `Dockerfile` / `.github/workflows/**` / `apps_script/**`
- 他5事業に関わるコードパス

### 設計制約（違反したら FIX）

1. **既存シートの列は右端追加のみ。** 挿入・並べ替え・改名・削除のコードパスを実装しない。
   理由: `core/catering_report.py:62-100` が `get_all_values()[2:]` + `r[4]` で**位置参照**している。
2. **シート書込みを伴う全関数は `dry_run: bool = True` 既定。** dry-run では1セルも書かない。
3. **純関数と I/O を分離する。** 語彙判定・UTM生成・次アクション抽出・流入元集計は
   ネットワーク不要の純関数にし、既存のテスト規約でテスト可能にする。
4. **`ensure_columns()` は冪等。** 2回実行して列が重複しない。
5. **外部送信を一切実装しない。** LINE / Gmail / SNS / DM の送信コードを書かない。
   文字列を生成して既存の配信機構に渡すだけ。
6. **OpenAI・有料 API を使わない**（プロジェクト恒久ルール）。テンプレートは
   固定文＋`{変数}` の文字列置換のみ。
7. **秘密情報・spreadsheet ID 実値をコードに書かない。** LP の URL は
   環境変数 `CATERING_LP_BASE_URL`（fallback: `business_registry` の `booking_url`）から読む。
8. **リポジトリに個人情報を置かない。** テストデータは架空社名・`090-0000-0000` 形式のみ。
9. **結合できなかった行を黙って落とさない。** 件数と金額を出力に含める。
10. **既存レポートの数値を変えない。** `/catering-weekly` の受注率・粗利率が
    列追加の前後で一致すること（列ズレ検知）。

### 完了条件（W1-2 〜 W1-9 共通）

- [ ] `python -m compileall -q core configs scripts tests` が通る
- [ ] `python -m unittest discover -s tests -p "test_*.py"` が**全件 pass**（既存件数を減らさない）
- [ ] Governance Gate が `0`（GO）または `20`（オーナー承認待ち）。**`30`（STOP）でない**
- [ ] `tests/catering_growth/test_safety.py` が以下の不在を検証（既存 `tests/instagram/test_windsor_source.py:57` パターン）
      — `api.line.me` / `requests.post` / `broadcast` / `openai` / `gcloud` / `method="POST"`
- [ ] 追跡ファイルに実電話番号・実メールアドレスのパターンが無い
- [ ] `REPORT.md` を更新（変更ファイル・テスト結果・手動確認手順・未解決事項）

### 本番 Sheets 変更（W1-5 / W1-6）の追加ゲート

**コードのマージと、本番シートへの適用は別。** 適用は以下の順にオーナーが行う。

1. オーナーが Sheets の版履歴で復元ポイントを作成（`ファイル > 版履歴 > 現在の版に名前を付ける`）
2. `dry_run=True` で実行 → 追加予定列の一覧をオーナーが確認
3. **オーナー承認**
4. `dry_run=False` で適用
5. `/catering-weekly` を実行し**受注率・粗利率が適用前と一致することを確認**。不一致なら版履歴から戻す

Codex は 1〜5 を**実行しない**。dry-run 出力を見せるところまでが担当。

### 未解決事項（実装前にオーナー確認が必要）

| # | 内容 | ブロックするタスク |
|---|---|---|
| 1 | **ケータリング LP の URL** — `configs/business_registry.py:79` の `booking_url` が空。UTM のベース URL に必須 | W1-3 の手動確認 / 運用開始 |
| 2 | **本番ワークブックの実データ量が未確認** — サンプル行のみか実データありか不明 | W1-5 / W1-6 の適用（W1-4 の read-only 棚卸しで解消） |
| 3 | デプロイ済み `trees-catering-ai` の `SPREADSHEET_ID` env が上書きされていないか未確認 | W1-9（CRM とファネルが同一ワークブックである前提） |

### 確認事項

（Codex が不明点を記入する欄）

---

## 次タスク候補

新しいタスクはこのセクション以下に追記する。

```
## TASK-016（タスクタイトル）
ステータス: TODO
概要:
完了条件:
スコープ:
```

## TASK-015 TREE's Catering 広告費ゼロ集客OS — Week 1
ステータス: TODO（→ 上部「現在のタスク」に詳細）
概要:
  既存 catering ワークブック内で流入元→問い合わせ→見積→受注→売上→粗利をつなぐ。
  W1-1（設計文書4本）は Claude Code 側で完了。W1-2〜W1-9 を Codex が実装。
完了条件:
  - [x] W1-1 設計文書（vocabulary / sheet-schema / operations-sop / contacts_template）
  - [ ] W1-2〜W1-9（受入条件は docs/catering-growth/repo-audit.md §8）
スコープ:
  - configs/catering_growth_vocab.py · core/catering_growth.py（新規）
  - core/catering_sales.py（+11列）· core/entrypoint.py（ルート追加のみ）
  - core/daily_action_commander.py（タスク供給元1件追加）· tests/catering_growth/
  - docs/catering-growth/ · .gitignore · REPORT.md · TASK.md
  変更禁止: scripts/acquisition/**（凍結）· core/catering_setup.py · requirements*.txt

## TASK-014 YU Business OS 2.0 Phase B2-8A — Catering deploy 承認の監査台帳記録
ステータス: DONE（2026-07-14 / feat/yu-business-os-2-catering-deploy-approval）
概要:
  catering の deploy 承認を readiness_approvals.yaml に scoped で記録（deploy 実行
  ではなく承認の記録）。beauty/hinabe/tachinomiya は deploy 未承認・不変。
完了条件:
  - [x] catering deploy_approval: true + deploy_scope（service/env/mode/smoke/rollback）
  - [x] approvals.py: deploy 承認は scope 必須・scheduler/send は false 強制維持
  - [x] production_plan: 承認済み時の warning 条件分岐
  - [x] テスト 8件を承認反映へ更新 / 合計 371件 全 pass
  - [x] catering 以外 deploy 未承認を維持
スコープ（承認記録のみ・deploy 実行なし）:
  - configs/governance/readiness_approvals.yaml · core/business_config/{approvals,production_plan}.py
  - tests/business_config/ · docs/YU_BUSINESS_OS_2_DATA_CONTRACTS.md · REPORT.md · TASK.md

## TASK-013 YU Business OS 2.0 Phase B2-7 — Production Activation Preparation
ステータス: DONE（2026-07-12 / feat/yu-business-os-2-production-activation-prep）
概要:
  READY 3事業（catering/beauty/ryukyu_hinabe）を deploy 直前状態まで準備し、
  TACHINOMIYA を技術確認。deploy は未承認・本番操作なし。
完了条件:
  - [x] core/business_config/production_plan.py（PREPARED/MANUAL_CHECK/NOT_READY/STOP）
  - [x] check_activation_plan.py / check_tachinomiya_technical_readiness.py
  - [x] 3事業 PREPARED・deploy/scheduler/send approval=false・command 未実行
  - [x] TACHINOMIYA token/GBP=MANUAL_CHECK・写真15枚不足・PHOTO_PENDING_READY 対応
  - [x] rollback（事業別+一括）検証
  - [x] Unit Test 32件追加 / 合計 371件 全 pass
スコープ（準備・技術確認のみ・本番操作なし）:
  - core/business_config/ · scripts/business_config/ · tests/business_config/
  - docs/YU_BUSINESS_OS_2_*.md · REPORT.md · TASK.md

## TASK-012 YU Business OS 2.0 Phase B2-6 — Readiness 承認 + Activation Dry Run
ステータス: DONE（2026-07-12 / feat/yu-business-os-2-readiness-activation-batch）
概要:
  catering/beauty/ryukyu_hinabe の readiness 承認を台帳記録し READY へ。TACHINOMIYA
  を read-only 監査。4事業の本番接続を Dry Run 判定。deploy は未承認・本番操作なし。
完了条件:
  - [x] configs/governance/readiness_approvals.yaml + approvals.py（deploy=false 強制）
  - [x] 3事業 READY / tachinomiya ALMOST_READY（PHOTO_PENDING_READY 対応）
  - [x] tachinomiya_audit.py（token/GBP/画像・値は読まない）
  - [x] activation.py + dry_run CLI（deploy 未承認で DEPLOY_APPROVAL_REQUIRED 停止）
  - [x] rollback（事業別 + 一括・LEGACY_ONLY）検証
  - [x] Unit Test 39件追加 / 合計 339件 全 pass
スコープ（承認記録・監査・Dry Run のみ・本番操作なし）:
  - configs/governance/ · core/business_config/ · scripts/business_config/
  - tests/business_config/ · docs/YU_BUSINESS_OS_2_*.md · REPORT.md · TASK.md

## TASK-011 YU Business OS 2.0 Phase B2-5 — SSOT Production Readiness Gate
ステータス: DONE（2026-07-12 / feat/yu-business-os-2-ssot-readiness-gate）
概要:
  SSOT 供給対象4事業を本番接続前に判定する Readiness Gate を追加。監査のみ・
  deploy/Scheduler/投稿/送信なし。READY/ALMOST_READY/OWNER_APPROVAL/NOT_READY/STOP。
完了条件:
  - [x] core/business_config/readiness.py（5段階判定・fail-closed）
  - [x] scripts/business_config/check_ssot_readiness.py（exit 0/1/2/3）
  - [x] TACHINOMIYA を ALMOST_READY（画像不足等）= READY にしない
  - [x] pasta_pasta / z1 不変
  - [x] Unit Test 25件追加 / 合計 300件 全 pass
スコープ（監査・Gate のみ・追加中心）:
  - core/business_config/{readiness,config_supply}.py · scripts/business_config/
  - tests/business_config/ · docs/YU_BUSINESS_OS_2_*.md · REPORT.md · TASK.md

## TASK-010 YU Business OS 2.0 Phase B2-4 Batch 2 — 琉球火鍋 SSOT 供給
ステータス: DONE（2026-07-12 / feat/yu-business-os-2-ssot-config-supply-ryukyu-hinabe）
概要:
  ryukyu_hinabe のみを SSOT 供給対象に追加（hinabe alias 対応）。pasta_pasta /
  z1 は対象外・不変。既定 LEGACY_ONLY・owner 承認時のみ SSOT・deploy なし。
完了条件:
  - [x] config_builder に BATCH2(ryukyu_hinabe) + build_ryukyu_hinabe_config
  - [x] config_supply の scope 拡張 + hinabe alias 解決
  - [x] POS/売上/別オーナー email/approval 保持・GBP 等 非有効化
  - [x] pasta_pasta / z1 不変
  - [x] Unit Test 20件追加 / 合計 275件 全 pass
  - [x] Supply CLI ryukyu_hinabe OWNER_APPROVED → SSOT / GO
スコープ（火鍋だけの one PR one purpose）:
  - core/business_config/{config_builder,config_supply}.py
  - tests/business_config/{test_ryukyu_hinabe_supply,test_config_supply}.py
  - docs/YU_BUSINESS_OS_2_*.md · REPORT.md · TASK.md

## TASK-009 YU Business OS 2.0 Phase B2-4 Batch 1 — SSOT 由来 config 供給（3事業）
ステータス: DONE（2026-07-11 / feat/yu-business-os-2-ssot-config-supply-batch-1）
概要:
  TACHINOMIYA / TREE'S CATERING / TREE BEAUTY について、owner 承認時のみ SSOT
  由来の Legacy 互換 config を供給。既定 LEGACY_ONLY・対象外3事業は不変。
完了条件:
  - [x] core/business_config/config_builder.py（変換・shape 検証・mutation なし）
  - [x] core/business_config/config_supply.py（3事業供給・batch）
  - [x] runtime_loader.apply_runtime_config を supply へ拡張
  - [x] scripts/business_config/check_ssot_config_supply.py（exit 0/1/2/3）
  - [x] Unit Test 30件追加 / 合計 255件 全 pass
  - [x] Supply CLI batch OWNER_APPROVED → 3事業 SSOT / batch GO
スコープ（追加中心・既定挙動不変・対象外事業不変）:
  - core/business_config/ · scripts/business_config/ · tests/business_config/
  - docs/YU_BUSINESS_OS_2_*.md · REPORT.md · TASK.md

## TASK-008 YU Business OS 2.0 Phase B2-3 — Runtime main path SSOT 接続
ステータス: DONE（2026-07-11 / feat/runtime-main-path-ssot-connection）
概要:
  entrypoint / Runtime Loader / Business Loader に SSOT Resolver を feature
  flag（既定 LEGACY_ONLY）越しに安全接続。既定は挙動不変・fail-closed。
完了条件:
  - [x] core/business_config/runtime_loader.py（LEGACY_ONLY/AUTO/OWNER_APPROVED）
  - [x] core/business_config/business_loader.py
  - [x] core/entrypoint.py に apply_runtime_config 追加（CONFIG 不変）
  - [x] scripts/business_config/check_runtime_main_path.py（exit 0/10/20/30/40/50）
  - [x] Unit Test 19件追加 / 合計 225件 全 pass
  - [x] rollback=YU_CONFIG_RUNTIME_MODE=LEGACY_ONLY
スコープ（追加中心・既存削除なし・既定挙動不変）:
  - core/business_config/ · scripts/business_config/ · core/entrypoint.py（追加のみ）
  - tests/business_config/ · docs/YU_BUSINESS_OS_2_*.md · REPORT.md · TASK.md

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
