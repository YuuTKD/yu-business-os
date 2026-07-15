# YU Business OS 2.0 — Implementation Roadmap

作成日: 2026-07-11  
ステータス: 設計書（実装禁止・承認待ち）

**原則**:
- 実装 > テスト > 自動化 > 監査 の順で価値を生む
- 設計書追加は禁止。このロードマップ以外の設計書は作らない
- 各フェーズは「完了条件」が揃うまで次に進まない
- 高リスク作業はすべてゆうさんの明示承認を取ってから開始

---

## フェーズ 0: 待機タスク（ゆうさんが実施・Claude Code は待つ）

**期限**: 〜2026-07-25  
**担当**: ゆうさん（Claude Code は実施不可）

| タスク | 完了条件 | 備考 |
|---|---|---|
| GCP Console → `LINE_TACHINOMIYASTAFF_TOKEN` を空に設定 | Cloud Run 環境変数が空になっていることを確認 | Q1=YES 決定済み |
| スタッフへ撮影依頼 LINE を送信 | スタッフが受信確認 | `data/reports/tachinomiya_staff_photo_request_send_now.txt` |
| Meta Developers で Threads token 期限確認 | 残り 30 日以上を確認 | 今週中 |
| スタッフが店舗内観 4 枚撮影 | Drive に写真アップロード | 期限: 2026-07-18 |
| スタッフがドリンク 5 枚・外観 6 枚撮影 | Drive に写真アップロード | 期限: 2026-07-25 |
| ゆうさんが写真を承認（GO/FIX/STOP） | `tachinomiya_owner_photo_approval_checklist.txt` 全項目 GO | 撮影後 |

---

## フェーズ 1: TACHINOMIYA READY 化（実装フェーズ）

**期限**: 2026-07-18〜2026-07-25  
**前提**: フェーズ 0 のゆうさんタスクが完了していること  
**リスク分類**: 中（画像登録のみ・Scheduler 変更なし）

### Step 1-1: 新規画像を IMAGE_LIBRARY に登録

**担当**: Claude Code（ゆうさんの「登録依頼」を受けてから開始）  
**タスク形式**: ゆうさんが `tachinomiya_image_registration_request_template.txt` を使って依頼

```
実装内容:
  - Google Drive から新規撮影画像を取得
  - EXIF 向き補正（ImageOps.exif_transpose）
  - GCS アップロード（image-library/tachinomiya/{id}_{ts}_fixed.jpeg）
  - HTTP200 確認
  - IMAGE_LIBRARY スプレッドシートに登録
  - image_theme / allowed_post_themes / blocked_post_themes を設定
```

**完了条件**:
- `店舗内観 ≥ 5 枚` active + GCS HTTP200
- `ドリンク ≥ 8 枚` active + GCS HTTP200
- `店舗外観 ≥ 10 枚` active + GCS HTTP200

**高リスク判定**: LOW（既存スクリプト `scripts/gcs_tachinomiya_orientation_fix.py` と同等作業）

---

### Step 1-2: Google 投稿 90 件の画像テーマ一致を再判定

**担当**: Claude Code  
**参照**: `data/reports/tachinomiya_google_post_image_recheck_procedure.txt`

```
実装内容:
  - Google Sheets 08_Google投稿 シートの 90 件を全件読み取り
  - 各行の post_theme と IMAGE_LIBRARY の allowed_post_themes を照合
  - 不一致行（MISMATCH）を CSV 出力
  - GO / FIX / STOP 判定を data/reports/tachinomiya_google_post_image_match_summary.txt に更新
```

**完了条件**:
- 全 90 件が MATCH または代替画像を使用可能
- `tachinomiya_google_post_image_match_summary.txt` が GO

---

### Step 1-3: TACHINOMIYA Scheduler Readiness 再判定

**担当**: Claude Code  
**参照**: `data/reports/tachinomiya_scheduler_readiness_report.txt`

```
更新内容:
  - 画像在庫チェック（Step 1-1 完了後）
  - token 期限チェック（ゆうさん確認後）
  - LINE 通知先チェック（フェーズ 0 完了後）
  - 総合判定を ALMOST_READY → READY に更新
```

**完了条件**: `tachinomiya_scheduler_readiness_report.txt` が **READY**

---

### Step 1-4: TACHINOMIYA Scheduler ON（ゆうさん最終判断）

**担当**: ゆうさん（Claude Code は実施しない）  
**実施条件**: Step 1-3 で READY 判定が出た後

```
ゆうさんがやること:
  Cloud Scheduler Console → tachinomiya-daily-content → ENABLE
```

**Claude Code は「READY です。Scheduler ON 可能です」と報告するだけ。実行しない。**

---

## フェーズ 2: TACHINOMIYA LINE 通知切り替え（高リスク PR）

**期限**: フェーズ 1 完了後・Scheduler 安定後  
**前提**: フェーズ 1 が完了し、Scheduler が安定稼働していること  
**リスク分類**: HIGH（core/ 変更 + Cloud Run 再デプロイ）

### Step 2-1: LINE_OWNER_TOKEN 切り替え PR

```
変更ファイル: core/multi_business_content_engine.py（1 行変更）

Before: "line_token_env": "LINE_TACHINOMIYASTAFF_TOKEN",
After:  "line_token_env": "LINE_OWNER_TOKEN",

PR フロー:
  1. Claude Code が高リスク PR 作成
  2. Codex 120 点レビュー
  3. GO → Merge 前停止・ゆうさん承認待ち
  4. ゆうさんが手動 Merge
  5. Cloud Run 再デプロイ（ゆうさんが実施）
```

**完了条件**:
- ゆうさんの LINE に投稿完了通知が届く
- スタッフへの broadcast 通知がゼロ

---

## フェーズ 3: DRY_RUN 標準化（高リスク PR）

**期限**: 2026-08 以降  
**前提**: フェーズ 2 完了後  
**リスク分類**: HIGH（core/ 変更）

### Step 3-1: EXECUTION_MODE 統一

```
変更ファイル: core/multi_business_content_engine.py

追加内容:
  - EXECUTION_MODE 環境変数読み取り
  - _should_send_line() 関数追加
  - DRY_RUN / OWNER_ONLY / LIVE の 3 モード対応

PR フロー: 高リスク → ゆうさん承認 → 手動 Merge → Cloud Run 再デプロイ
```

**完了条件**:
- EXECUTION_MODE=dry でのテストが全 4 事業でパス
- ログに `[DRY_RUN] LINE 送信スキップ` が出力される

---

## フェーズ 4: 設定単一化（高リスク PR）

**期限**: 2026-09 以降  
**前提**: フェーズ 3 完了後・安定稼働確認後  
**リスク分類**: HIGH（core/ 変更）

### Step 4-1: `_BUSINESS_CONFIGS` を `business_registry.py` から生成

```
変更ファイル: core/multi_business_content_engine.py

追加内容:
  - _build_business_configs() 関数を追加
  - _BUSINESS_CONFIGS = _build_business_configs() に変更

テスト:
  - 4 事業の設定が正しく生成されることを確認
  - 既存の content automation が動作することを確認（DRY_RUN で）
```

**完了条件**:
- 設定が `business_registry.py` から自動生成される
- 4 事業の content automation が DRY_RUN で正常動作

---

## フェーズ 5: GBP 自動投稿デプロイ（高リスク）

**期限**: GBP API 承認後（時期未定）  
**前提**: GBP API の承認が完了していること  
**リスク分類**: HIGH（Cloud Run + GBP API）

### Step 5-1: GBP API 接続確認

```
担当: ゆうさん（API 承認・認証設定）
確認内容:
  - GBP API の承認状況
  - 認証トークン設定（Cloud Run 環境変数）
  - DRY_RUN で 3 事業のキュー 267 件を確認
```

### Step 5-2: GBP 自動投稿デプロイ（ゆうさん承認後）

```
実装内容: core/gbp_api.py のデプロイ（コード準備済み）
PR フロー: 高リスク → ゆうさん承認 → 手動 Merge → Cloud Run 再デプロイ
```

**完了条件**: 3 事業（beauty/catering/tachinomiya）への Google 投稿が自動化

---

## フェーズ 6: SNS PDCA Phase3（将来）

**期限**: Gemini API キー取得後  
**前提**: API キーが設定されていること  
**リスク分類**: MEDIUM（既存機能の拡張）

```
対象: core/sns_pdca.py の Phase3（Gemini リライト）
実装内容: 勝ち投稿の自動リライト
前提: GEMINI_API_KEY が Cloud Run に設定されていること
```

---

## フェーズ 7: Notification Gateway 実装（長期）

**期限**: 2026-10 以降  
**前提**: フェーズ 1-4 が安定していること  
**リスク分類**: HIGH（新モジュール + core/ 変更）

```
実装内容:
  - agents/shared/notification_gateway.py（新規）
  - 全 LINE 通知を一元管理
  - EXECUTION_MODE で通知先を制御
  - チャネル別の承認フロー

完了条件:
  - 全事業の通知が Notification Gateway を経由
  - DRY_RUN / OWNER_ONLY / LIVE で正しく動作
```

---

## 実装優先度マトリクス

| フェーズ | 売上直結度 | リスク | ゆうさん負担 | 優先度 |
|---|---|---|---|---|
| フェーズ 0（ゆうさんタスク） | A（30 日以内）| LOW | HIGH | **最優先** |
| フェーズ 1（TACHINOMIYA READY）| S（7 日以内）| LOW-MEDIUM | LOW | **高** |
| フェーズ 2（LINE 切り替え）| B | HIGH | MEDIUM | 中 |
| フェーズ 3（DRY_RUN 統一）| C | HIGH | LOW | 低 |
| フェーズ 4（設定単一化）| C | HIGH | LOW | 低 |
| フェーズ 5（GBP デプロイ）| A | HIGH | HIGH | API 承認次第 |
| フェーズ 6（PDCA Phase3）| A | MEDIUM | LOW | API キー次第 |
| フェーズ 7（Gateway）| B | HIGH | MEDIUM | 長期 |

---

## GO 条件（フェーズ移行チェックリスト）

### フェーズ 0 → フェーズ 1 の GO 条件

```
□ LINE_TACHINOMIYASTAFF_TOKEN が Cloud Run で空になっている（ゆうさん実施）
□ Threads token 期限が 30 日以上残っている（ゆうさん確認）
□ スタッフに撮影依頼 LINE を送信済み（ゆうさん実施）
□ 内観写真 ≥ 4 枚が Drive にアップロードされている
□ ゆうさんが「IMAGE_LIBRARY 登録をお願いします」と Claude Code に依頼
```

### フェーズ 1 → フェーズ 2 の GO 条件

```
□ 店舗内観 ≥ 5 枚 active + GCS HTTP200
□ ドリンク ≥ 8 枚 active + GCS HTTP200
□ 店舗外観 ≥ 10 枚 active + GCS HTTP200
□ Google 投稿 90 件テーマ一致 GO
□ tachinomiya_scheduler_readiness_report.txt が READY
□ ゆうさんが Scheduler ON を承認・実施
□ Scheduler が 3 日以上正常稼働
□ LINE_OWNER_TOKEN が Cloud Run に設定済み（ゆうさん確認）
□ ゆうさんが「owner 通知 PR を作って」と依頼
```

### フェーズ 2 → フェーズ 3 の GO 条件

```
□ TACHINOMIYA の Scheduler が 1 週間以上正常稼働
□ LINE_OWNER_TOKEN へのみ通知が届いていることを確認
□ スタッフへの broadcast がゼロであることを確認
□ ゆうさんが DRY_RUN 統一 PR の作成を承認
```

---

## タイムライン（最速シナリオ）

```
2026-07-11（今日）:
  → ゆうさん: Cloud Run で LINE_TACHINOMIYASTAFF_TOKEN を空化
  → ゆうさん: スタッフへ撮影依頼 LINE 送信
  → ゆうさん: Threads token 期限確認

2026-07-18:
  → スタッフ: 内観 4 枚以上撮影 → Drive アップ
  → ゆうさん: 写真承認 → Claude Code に登録依頼
  → Claude Code: IMAGE_LIBRARY 登録・GCS 化・HTTP200 確認

2026-07-25:
  → スタッフ: ドリンク 5 枚・外観 6 枚撮影 → Drive アップ
  → ゆうさん: 写真承認 → Claude Code に登録依頼
  → Claude Code: 登録・GCS 化・テーマ一致再判定
  → Claude Code: Scheduler Readiness → READY 報告
  → ゆうさん: Scheduler ON の最終判断・実施

2026-08 以降:
  → Scheduler 安定稼働を確認後に owner LINE 切り替え PR
  → その後 DRY_RUN 統一 PR
  → 設定単一化 PR

GBP API 承認後（時期未定）:
  → GBP 自動投稿デプロイ
```

---

## 実装禁止リスト（ロードマップ外）

以下はゆうさんから明示的な依頼がある場合のみ検討する:

- `daily_post_limit` / `posting_window` の変更
- 新規 Scheduler ジョブの追加
- 新規 Cloud Run サービスのデプロイ
- Tree Beauty への商品マッチ対象化
- 琉球火鍋の既存投稿基盤への変更
- acquisition エージェントの再開
- Gmail / SNS の本番自動送信
- `data/reports/` ファイルの削除・移動

---

## Phase A（Registry & Governance 土台）— 実装完了 2026-07-11

TACHINOMIYA のフェーズ群とは独立した**基盤フェーズ**。売却可能・自動化可能な
OS にするための「一元管理 + 機械判定ガバナンス」の土台を先行実装した。

### 実装スコープ（完了）

| 項目 | 状態 |
|---|---|
| Skill Registry（`configs/skills/registry.yaml` + Loader）| ✅ 10件登録（active 7 / inactive 3）|
| Agent Registry（`configs/agents/registry.yaml` + Loader）| ✅ 9件登録（active 3 / inactive 6・全て default deny）|
| Governance Policy（`configs/governance/policies.yaml`）| ✅ 21ポリシー + リスク定義 |
| Governance Validator（GO/FIX/STOP/OWNER_APPROVAL）| ✅ 実装・14段判定 |
| 整合性 CLI（`scripts/registry/validate_registry.py`）| ✅ exit 0/1/2 |
| Unit Test | ✅ **52件 全 pass** |

### テスト結果

```
python3 scripts/registry/validate_registry.py   → RESULT: GO (exit 0)
python3 -m unittest discover -s tests            → Ran 52 tests OK
```

検証済み安全特性: 外部通信ゼロ / Secret 出力ゼロ / 既存 namespace import 無破壊 /
SKILL.md 非実行 / path traversal 拒否 / default deny。

### 既存本番への影響

deploy なし・Scheduler 変更なし・外部送信なし・GCS/Sheets 書き込みなし・
既存ファイル削除/移動なし。Phase A は「追加・検証可能」までで本番未接続。

### 次 Phase 候補

| Phase | 内容 | リスク | 前提 |
|---|---|---|---|
| **Phase B: Single Source of Truth** | `core/multi_business_content_engine.py` の `_BUSINESS_CONFIGS` を `configs/business_registry.py` から生成。設定二重管理の解消 | HIGH | Phase A Merge 後・ゆうさん承認 |
| Phase C: Notification Gateway | 全 LINE 通知を Registry 経由の単一ゲートに集約 | HIGH | Phase B 安定後 |
| Phase D: Governance の PR フロー統合 | Validator を `pr_auto_flow.sh` に接続 | MEDIUM | Phase A Merge 後 |

---

## Phase D-Lite（Governance × PR Auto Flow）— 実装完了 2026-07-11

Phase A の Governance Validator を既存 PR 自動フローの**先頭**に接続した。
PR ごとに GO / FIX / STOP / OWNER_APPROVAL_REQUIRED を機械判定できる。

### 実装スコープ（完了・追加のみ）

| 項目 | 状態 |
|---|---|
| `scripts/agent/governance_gate.py`（ローカル diff アダプタ）| ✅ exit 0/10/20/30/40 |
| `core/governance/diff_risk.py`（ファイル→risk 分類・単一ソース）| ✅ 純関数 |
| `core/governance/validator.py`（`pr_change_review` 対応を追加）| ✅ 既存判定は不変 |
| `scripts/agent/pr_auto_flow.sh`（Step 0 に gate 接続・fail-closed）| ✅ gh 非依存 |
| Unit Test | ✅ **39件追加 / 合計 91件 全 pass** |

### テスト結果

```
python3 -m unittest discover -s tests   → Ran 91 tests OK
bash -n scripts/agent/pr_auto_flow.sh   → syntax OK
python3 scripts/registry/validate_registry.py → GO (exit 0)
```

検証済み: fail-closed（import/git/base-ref/unknown-decision → STOP）/ HIGH は承認でも
auto-merge 禁止 / CRITICAL は承認でも STOP / Secret 値非出力 / 外部通信ゼロ /
scripts/acquisition・Tree Beauty・daily_post_limit 保護。

### 次 Phase 候補
- **Phase B: Single Source of Truth**（設定二重管理の解消）— HIGH・売却可能性向上

---

## Phase B1（Business Config SSOT / Shadow）— 実装完了 2026-07-11

事業設定の正本を shadow mode で追加。本番接続は行わず、既存設定との差分を
自動検査できる状態にした。

### 実装スコープ（完了・追加のみ）

| 項目 | 状態 |
|---|---|
| `configs/businesses/registry.yaml`（6事業・secret-free）| ✅ |
| `core/business_config/`（models / loader / legacy_adapter / comparator）| ✅ |
| `scripts/business_config/validate_business_configs.py`（exit 0/1/2/3）| ✅ |
| Unit Test | ✅ **47件追加 / 合計 142件 全 pass** |

### 検証結果

```
python3 scripts/business_config/validate_business_configs.py → FIX (exit 1)
  ※ 実 legacy に本物の乖離があるため FIX が正しい出力（自動上書きしない）
python3 -m unittest discover -s tests → Ran 142 tests OK
```

Shadow 保証: 本番未接続 / 自動同期なし / 既存設定無変更 / PRODUCTION_CONNECTED なし。

### Phase B2 の条件（本番接続）

Phase B2（既存本番コードの読込先を SSOT へ切替）に進む前提:
1. Comparator の FIX 乖離を legacy 側の整理で解消（executive_team target・hinabe 別名・LINE 名の統一）
2. 対象事業を 1 つずつ・DRY_RUN で段階接続（1 PR 1 事業）
3. 各接続は HIGH リスク → ゆうさん承認 → 人間 Merge → Cloud Run 再デプロイ

---

## Phase B1.1（乖離解消）— 実装完了 2026-07-11

B1 で検出した5件の不一致を確定値で解消し、Business Config CLI を **GO / exit 0**
（mismatch 0）にした。**Phase B2 の前提条件1が達成**。

### 完了

| 項目 | 状態 |
|---|---|
| TACHINOMIYA 目標統一（5.5M=昼2.5M+夜3.0M）+ 内訳 API | ✅ |
| 火鍋 canonical `ryukyu_hinabe` / alias `hinabe` | ✅ |
| LINE canonical/alias（tachinomiya/catering/hinabe）| ✅ |
| comparator の alias 解決・昼夜整合・循環検知 | ✅ |
| Unit Test | ✅ **19件追加 / 合計 161件 全 pass** |
| Business Config CLI | ✅ **GO / exit 0 / mismatch 0** |

### Phase B2 前提の達成状況

- [x] 前提1: FIX 乖離の解消（CLI GO）
- [ ] 前提2-3: 1事業ずつ DRY_RUN 段階接続（Phase B2 本体）

---

## Phase B2-1（TACHINOMIYA Shadow 接続）— 実装完了 2026-07-11

TACHINOMIYA の設定に SSOT を **Shadow Mode で副次接続**。Legacy と SSOT を
実行時比較できるが、**返却値は Legacy のまま**（runtime_source=LEGACY）。

### 完了

| 項目 | 状態 |
|---|---|
| `shadow_adapter.py`（OFF/SHADOW_ONLY/ENFORCE_COMPARE・fail-closed）| ✅ |
| `scripts/business_config/check_tachinomiya_shadow.py`（exit 0/1/2/3）| ✅ |
| runtime_source=LEGACY 不変・SSOT 値は本番へ流さない | ✅ |
| Unit Test | ✅ **20件追加 / 合計 181件 全 pass** |
| Shadow CLI | ✅ **GO / exit 0 / mismatch 0** |

### 次の切替条件（Phase B2-2）

1. Shadow 比較が一定期間 GO（mismatch 0）で安定
2. ENFORCE_COMPARE を CI/検証で常時 GO
3. 1 事業（TACHINOMIYA）ずつ read-source を SSOT へ切替（HIGH・owner 承認・人間 Merge）
   ※ env 変数の実体は変えず、参照経路のみ段階切替

---

## Phase B2-2（TACHINOMIYA SSOT primary + Legacy fallback）— 実装完了 2026-07-11

TACHINOMIYA のみ、設定読込の第一候補を SSOT に切替可能にした（Legacy fallback 付き・
owner 承認必須）。**Cloud Run deploy / Scheduler 変更 / 外部送信なし**。

### 完了

| 項目 | 状態 |
|---|---|
| `runtime_resolver.py`（4 mode・SSOT_ONLY 禁止・fail-closed）| ✅ |
| `check_tachinomiya_runtime.py`（exit 0/10/20/30/40/50）| ✅ |
| SSOT は承認+mismatch 0+有効時のみ / mismatch は fallback せず FIX・STOP | ✅ |
| 他事業は LEGACY・SSOT primary 要求は STOP | ✅ |
| rollback switch（`--mode LEGACY_ONLY`）| ✅ |
| Unit Test | ✅ **25件追加 / 合計 206件 全 pass** |
| Runtime CLI（承認）| ✅ **GO / runtime_source=SSOT** |

### Phase B2-3 前提（次段階）

1. SSOT_PRIMARY が一定期間安定 GO（fallback 発生ゼロ）
2. 本番 main path（entrypoint 等）への Resolver 接続を owner 承認で段階導入
3. その後に初めて `SSOT_ONLY`（Legacy 廃止）を別 PR・別承認で検討

---

## Phase B2-3（本番 main path への Resolver 接続）— 実装完了 2026-07-11

`entrypoint` / Runtime Loader / Business Loader に、SSOT Resolver を **feature
flag（既定 LEGACY_ONLY）越しに接続**。既定は従来完全同一挙動。deploy/Scheduler/
Cloud Run/投稿/LINE いずれもなし。

### 完了

| 項目 | 状態 |
|---|---|
| `runtime_loader.py`（LEGACY_ONLY/AUTO/OWNER_APPROVED・fail-closed）| ✅ |
| `business_loader.py`（legacy 取得＋接続の再利用層）| ✅ |
| `entrypoint.py`（`apply_runtime_config` 追加・CONFIG 不変）| ✅ |
| `check_runtime_main_path.py`（exit 0/10/20/30/40/50）| ✅ |
| Unit Test | ✅ **19件追加 / 合計 225件 全 pass** |
| rollback（`YU_CONFIG_RUNTIME_MODE=LEGACY_ONLY`）| ✅ |

### Phase B2-4 前提（次段階・今回は未着手）

1. AUTO/OWNER_APPROVED を検証環境で安定運用（fallback 発生の監視）
2. `apply_runtime_config` を「判定のみ」から「SSOT 由来 config の実供給」へ拡張
   （legacy 互換シェイプを SSOT から構築・1 事業ずつ・owner 承認）
3. 安定後に `SSOT_ONLY`（Legacy 廃止）を別 PR・別承認で検討

---

## Phase B2-4 Batch 1（SSOT 由来 config 供給・3事業）— 実装完了 2026-07-11

対象 = **TACHINOMIYA / TREE'S CATERING / TREE BEAUTY**。owner 承認時のみ、SSOT
由来の Legacy 互換 config を供給。既定 LEGACY_ONLY・本番未 deploy。

### 完了

| 項目 | 状態 |
|---|---|
| `config_builder.py`（SSOT→legacy 互換・shape 検証・mutation なし）| ✅ |
| `config_supply.py`（3事業供給判定・comparator + builder・batch）| ✅ |
| `runtime_loader.apply_runtime_config` を supply へ拡張 | ✅ |
| `check_ssot_config_supply.py`（exit 0/1/2/3）| ✅ |
| Unit Test | ✅ **30件追加 / 合計 255件 全 pass** |
| Supply CLI（batch OWNER_APPROVED）| ✅ **3事業 SSOT / batch GO** |

### Shadow / Runtime 整合

3事業について Shadow comparator・Runtime resolver・Config Builder・Legacy shape
validator がすべて GO で一致（mismatch 0・shape 互換）。

### Batch 2 対象候補（今回は未着手）

`ryukyu_hinabe`（火鍋）→ 続いて `pasta_pasta` / `z1`（別 PR・別承認・1 事業ずつ）。

---

## Phase B2-4 Batch 2（火鍋のみ SSOT 供給）— 実装完了 2026-07-12

`ryukyu_hinabe` を SSOT 供給対象に追加（`hinabe` alias 対応）。`pasta_pasta` /
`z1` は**対象外・不変**。既定 LEGACY_ONLY・本番未 deploy。

### 完了

| 項目 | 状態 |
|---|---|
| supply scope に `ryukyu_hinabe` 追加（`config_builder` / `config_supply`）| ✅ |
| `hinabe` alias 解決（canonical と同一 config）| ✅ |
| POS・売上連携・別オーナー email・approval policy 保持 / GBP 等 非有効化 | ✅ |
| `pasta_pasta` / `z1` 不変（コード・設定・テスト・docs 変更なし）| ✅ |
| Unit Test | ✅ **20件追加 / 合計 275件 全 pass** |
| Supply CLI（ryukyu_hinabe OWNER_APPROVED）| ✅ **SSOT / GO** |

### 次候補（今回は未着手）

`pasta_pasta` → `z1`（別 PR・別承認・1 事業ずつ）。

---

## Phase B2-5（SSOT Production Readiness Gate・4事業）— 実装完了 2026-07-12

SSOT 供給対象の **4事業**（tachinomiya / catering / beauty / ryukyu_hinabe）を
本番接続前に判定する Readiness Gate を追加。**監査のみ・deploy なし**。

### 完了

| 項目 | 状態 |
|---|---|
| `core/business_config/readiness.py`（READY/ALMOST_READY/OWNER_APPROVAL/NOT_READY/STOP）| ✅ |
| `scripts/business_config/check_ssot_readiness.py`（exit 0/1/2/3）| ✅ |
| Unit Test | ✅ **25件追加 / 合計 300件 全 pass** |

### 現在の判定（owner 未承認・運用未確認時）

| 事業 | 判定 | 理由 |
|---|---|---|
| tachinomiya | **ALMOST_READY** | 画像不足 / Threads token 未確認 / GBP 認証未確認 |
| catering | OWNER_APPROVAL_REQUIRED | 技術的に準備完了・承認待ち |
| beauty | OWNER_APPROVAL_REQUIRED | 同上（active 状態維持）|
| ryukyu_hinabe | OWNER_APPROVAL_REQUIRED | 同上（GBP 除外・alias 維持）|
| pasta_pasta / z1 | NOT_READY | SSOT 供給スコープ外（不変）|

### 次工程

TACHINOMIYA の運用確認（画像補充・token・GBP）→ owner 承認で READY。以降 deploy は
別承認・別 PR。pasta_pasta / z1 の SSOT 供給は別途。

---

## Phase B2-6（Readiness 承認 + Activation Dry Run）— 実装完了 2026-07-12

owner の readiness 承認（catering / beauty / ryukyu_hinabe）を台帳に記録し READY へ
更新。TACHINOMIYA を read-only 監査。4事業の本番接続を Dry Run で判定（**実 deploy なし**）。

### 完了

| 項目 | 状態 |
|---|---|
| Owner Approval Ledger（`readiness_approvals.yaml` + `approvals.py`）| ✅ deploy/scheduler/send=false |
| Readiness: catering / beauty / ryukyu_hinabe → **READY** | ✅ 台帳連携 |
| TACHINOMIYA 監査（token/GBP=MANUAL_CHECK・画像=PHOTO_PENDING）→ **ALMOST_READY** | ✅ |
| PHOTO_PENDING_READY（写真のみ残り時）| ✅ |
| Activation Dry Run + Plan + Rollback（`activation.py` + CLI）| ✅ deploy 未承認で停止 |
| Unit Test | ✅ **39件追加 / 合計 339件 全 pass** |

### 現在の状態

| 事業 | Readiness | Activation Dry Run |
|---|---|---|
| catering / beauty / ryukyu_hinabe | READY | DEPLOY_APPROVAL_REQUIRED |
| tachinomiya | ALMOST_READY（写真+token+GBP）| READINESS_BLOCKED |
| pasta_pasta / z1 | NOT_READY（対象外）| — |

### 次工程（別 PR・別承認）

1. TACHINOMIYA: 画像補充 + token/GBP 確認 → READY
2. **deploy 承認**（readiness 承認とは別）→ 実 Activation（1事業ずつ）
3. pasta_pasta / z1 の SSOT 供給

---

## Phase B2-7（Production Activation Preparation）— 実装完了 2026-07-12

READY 3事業を **deploy 直前状態**まで準備し、TACHINOMIYA を技術確認。**deploy は未承認・
本番操作なし**。

### 完了

| 項目 | 状態 |
|---|---|
| `core/business_config/production_plan.py`（PREPARED/MANUAL_CHECK/NOT_READY/STOP）| ✅ |
| `check_activation_plan.py` / `check_tachinomiya_technical_readiness.py`（CLI）| ✅ |
| Unit Test | ✅ **32件追加 / 合計 371件 全 pass** |

### 状態

| 事業 | Plan decision | 備考 |
|---|---|---|
| catering / beauty / ryukyu_hinabe | **PREPARED** | deploy 承認待ち（未付与）・rollback 検証済み・command は候補のみ |
| tachinomiya | (technical) **MANUAL_CHECK_REQUIRED** | token/GBP 手動確認要・写真 **15枚**不足（interior+4/drink+5/exterior+6）|

### 次の承認ポイント（別 PR）

1. TACHINOMIYA: 画像15枚補充 + Threads token/GBP の手動確認 → PHOTO_PENDING_READY → READY
2. **deploy 承認**（readiness 承認とは別・1事業ずつ）→ 実 Activation
3. pasta_pasta / z1 の SSOT 供給

---

## Phase R: Release & Operations OS ロードマップ（設計 2026-07-15）

原則: 1 PR = 1 purpose / 大規模一括実装禁止 / 各 Phase は独立に rollback 可能。

### Phase R0 — 現状監査・SSOT 決定（本設計で完了）

| 項目 | 内容 |
|---|---|
| 目的 | 資産監査・正本決定・設計5文書更新 |
| 変更ファイル | docs 5ファイルのみ |
| リスク | なし（設計のみ） |
| 完了条件 | 本設計のレビュー & ゆうさん GO |
| ゆうさん判断 | この Phase R 設計で進めるか YES/NO |

### Phase R1 — 固定 CI + PR Validation（**実装完了 2026-07-15**）

| 項目 | 内容 |
|---|---|
| 目的 | ローカル Mac 依存の根絶。PR ごとに固定環境でテスト+governance gate |
| 変更ファイル | `.github/workflows/pr-validation.yml`（新規）/ `requirements.lock`（新規・py3.11 freeze 71pkg）/ docs 5ファイル |
| リスク | LOW（本番非接触・gcloud/deploy/Secret/Scheduler 不使用） |
| テスト | workflow YAML 構文 OK / lock-only クリーン venv で 388件 exit0 / gate 再現 / compileall OK |
| 完了条件 | PR 上で自動チェックが緑（GO または OWNER_APPROVAL_REQUIRED） |
| rollback | merge しない / branch 削除 / workflow revert（Cloud Run rollback 不要） |
| ゆうさん判断 | PR Merge YES 1回 |
| 期待削減 | 環境差事故ゼロ化・「手元でテスト」廃止（毎回10-30分→0） |

**実装メモ（監査で判明した事実）**: 既存 workflow は 0本（重複・Required Check 衝突なし）。
テストは stdlib unittest だが `gspread`/`requests` を top-level import する core 経由で第三者
依存が必須 → CI で lock install が必要と確定。lock は `requirements.txt` を py3.11 クリーン
環境で解決した完全 freeze（proven installable・388件 PASS 済み）。gate は本 PR が
`.github/workflows/` を含むため **OWNER_APPROVAL_REQUIRED(20)** を返す想定＝HIGH の正常挙動。

**固定 CI が即座に検知した環境依存（R1 の狙いどおりの成果）**: 初回 Actions 実行で
`tests/business_config/test_activation_plan.py` の `test_19_gbp_files_present` /
`test_22_gbp_manual_check` が 2件失敗。原因はローカル Mac に存在する GBP 認証ファイル
（`backups/gbp_client_secrets.json` / `gbp_oauth_tokens.json`・`.gitignore` 済のため未コミット）
の有無に依存していたこと。クリーン checkout では常に失敗し、かつファイルは credentials の
ため決してコミットできない。→ テストを**環境非依存の不変条件**（`auth_files_present` と
`status` の整合: present↔MANUAL_CHECK_REQUIRED / absent↔MISSING）に修正。カバレッジは
維持（両分岐の整合を検証）・弱体化なし。ローカル/クリーン CI 双方で 388件 PASS を確認。
これは R1 が「ローカル依存を排除する」目的を初日から果たした実例。

### Phase R2 — Change Classification + Test Selection（推定 0.5日）

| 項目 | 内容 |
|---|---|
| 目的 | diff_risk.py 拡張で分類 JSON を出し、必要テストのみ実行 + SHA skip |
| 変更ファイル | `core/governance/diff_risk.py`（追加のみ）/ `scripts/release/classify_change.py` / pr-validation.yml 修正 / tests/governance 追加 |
| リスク | MEDIUM（governance コード変更 → Full suite 強制対象） |
| テスト | 分類ユニット（カテゴリ×15・full_suite_forced 条件・allowlist 導出）+ Full suite |
| 完了条件 | 分類 JSON が job summary に出る / skip が SHA 単位で効く |
| rollback | 追加関数未使用に戻す（既存 classify_paths は無変更） |
| ゆうさん判断 | PR Merge YES 1回 |
| 期待削減 | 重複 Full Test ゼロ |

### Phase R3 — release.yml（dry-run モード）+ /status 拡張 + Smoke（推定 1日）

| 項目 | 内容 |
|---|---|
| 目的 | main push で build→staging(no-traffic)→smoke まで自動（traffic 昇格はしない） |
| 変更ファイル | `.github/workflows/release.yml` / `.github/actions/deploy-service/` / `scripts/release/smoke_test.py` / `core/entrypoint.py`（/status へ release 情報 read-only 追加） / registry.yaml（release ブロック） |
| 前提（人間1回） | WIF + SA 3種 + Artifact Registry の GCP setup（runbook 提供・約30分） |
| リスク | HIGH（本番サービスに no-traffic revision が乗る。traffic は不変） |
| テスト | Full suite / smoke ユニット / staging 実機で health=200・release_info 取得 |
| 完了条件 | catering の candidate revision に smoke PASS、traffic 0% のまま |
| rollback | `RELEASE_MODE=dry_run`（repo variable）+ candidate revision 放置（無害）/ 削除 |
| ゆうさん判断 | PR Merge YES + GCP setup 実施 |
| 期待削減 | 貼り付けゼロ・Revision 手動確認ゼロの土台 |

### Phase R4 — Deployment Ledger（推定 0.5日）

| 目的 | 全 deploy の監査証跡 100%（GCS 正本） |
| 変更ファイル | release.yml へ ledger step 追加 / `gs://yu-release-ledger` 作成（人間 or Terraformなし・gsutil 1コマンド） |
| リスク | LOW |
| 完了条件 | dry-run の deployment_id JSON が bucket に残る |
| rollback | step 無効化 |
| ゆうさん判断 | PR Merge YES |

### Phase R5 — Owner Approval（Environment）+ LINE 通知（推定 0.5日）

| 目的 | YES 1回の承認 UX 完成 |
| 変更ファイル | release.yml に `environment: production` job / LINE 通知 step |
| 前提（人間1回） | GitHub Environment `production` 作成 + reviewer=ゆうさん 設定（5分） |
| リスク | MEDIUM |
| 完了条件 | LINE に承認通知→リンク1タップ→run が進む（dry-run のまま） |
| rollback | environment 指定を外す |
| ゆうさん判断 | PR Merge YES + Environment 設定 + 承認テスト1回 |
| 期待削減 | 承認＝1タップ化 |

### Phase R6 — Production Canary（catering 1事業・実 traffic 昇格）（推定 0.5日）

| 目的 | 実本番反映を catering で初回実行（自動 rollback 込み） |
| 変更ファイル | release.yml の dry_run 解除（catering のみ allowlist） |
| リスク | **CRITICAL 相当運用**（実 traffic 変更） |
| テスト | Full suite + staging smoke + rollback 実地試験（意図的 rollback 1回を含む） |
| 完了条件 | 実 PR 1件が Merge→YES→ACTIVATED（15分以内）/ 意図的 rollback が3分以内に成功 |
| rollback | rollback.yml + 従来手動 runbook（併存） |
| ゆうさん判断 | canary 実施 YES + 結果確認 |
| 期待削減 | Merge→本番 15分の実証 |

### Phase R7 — 3事業展開（推定 0.5日）

| 目的 | tachinomiya / beauty を deploy_order に追加（progressive） |
| リスク | HIGH（tachinomiya readiness gate・beauty 保護ルールを deploy 前チェックに接続） |
| 完了条件 | 3サービス progressive deploy 1回成功（1件失敗→後続停止も試験） |
| ゆうさん判断 | PR Merge YES |

### Phase R8 — Resume / Lock / Emergency 強化（推定 1日）

| 目的 | 途中再開・二重起動防止・production lock・emergency bypass・（任意）LINE 返信 YES ブリッジ |
| リスク | MEDIUM |
| 完了条件 | 中断→resume で ACTIVATED 済み skip / lock 動作 / bypass 証跡が Ledger に残る |
| ゆうさん判断 | PR Merge YES（LINE 返信ブリッジを入れるかもここで判断） |

**合計推定: 実装 約5人日（Claude Code）+ ゆうさん設定作業 約40分（GCP 30分 + GitHub 5分 + 承認テスト）**

## 既存失敗 20件 → 再発防止コントロール

| # | 失敗 | Root cause | Preventive | Detective | Recovery | 責任コンポーネント |
|---|---|---|---|---|---|---|
| 1 | Bash 3.2 declare -A | ローカル既定 shell 依存 | CI=ubuntu(bash5)固定・release 経路からローカル排除 | workflow lint | - | Fixed CI |
| 2 | python3/3.11 依存差 | 複数 Python 環境 | setup-python 3.11 pin（Dockerfile と一致） | CI 上で version assert | - | Fixed CI |
| 3 | requirements 未導入 | 手元 pip 任せ | requirements.lock + CI install | install 失敗で即 FAIL | lock 再生成 | Fixed CI |
| 4 | gspread/requests 不足 | 同上 | 同上 | import smoke | 同上 | Fixed CI |
| 5 | gcloud 未導入 | ローカル依存 | deploy 主体を Actions へ移管（setup-gcloud pin） | preflight assert | - | GitHub Actions |
| 6 | gcloud 認証切れ | 人間認証への依存 | WIF（無期限 key なし・都度 OIDC） | auth 失敗即 FAIL+通知 | 再 run | WIF |
| 7 | Claude Code 認証切れ | 実行主体の誤り | Claude Code を deploy 経路から除外 | - | - | 責任分界 |
| 8 | 重複 Full Test | スクリプト毎に再検証 | SHA+testset の PASS 記録で skip | job summary に SKIPPED 明記 | - | Test Selection |
| 9 | テスト件数パース誤判定 | 出力文字列で成否判定 | **exit code のみで判定**（件数は参考表示） | run_check 形式で cmd/rc/PASS 表示 | - | CI 規約 |
| 10 | 1日以上ハング | timeout なし・待ち状態不可視 | 全 job timeout-minutes + 全体45分 | heartbeat→stuck 検知 | cancel→resume | Timeout/Resume |
| 11 | Git 再認証待ち | ローカル git 操作 | Actions 内 checkout（token 自動） | - | - | GitHub Actions |
| 12 | 過剰 preflight | 検証の都度全部盛り | 検証は CI 1回・deploy 時は smoke のみ | 分類 JSON で必要検証を宣言 | - | Classification |
| 13 | deploy 禁止と実行の矛盾 | 実行主体未定義 | Actions=実行主体・Claude=実装のみを明文化 | governance gate | - | 責任分界 |
| 14 | 長い貼り付け作業 | 人間がスクリプト搬送 | Merge→自動起動（貼り付け0） | - | - | release.yml |
| 15 | スクリプト乱立 | /tmp に都度生成 | workflow + composite に一本化・/tmp 禁止 | PR レビュー | - | Repo 管理 |
| 16 | 同一レポート増殖 | 都度 report 新規作成 | Ledger 正本1つ・docs は既存5のみ | - | - | Ledger |
| 17 | /tmp ファイル依存 | ローカル一時領域 | 全 artifact を Actions artifact/GCS へ | - | - | Fixed CI |
| 18 | 本番と設計の責任境界不明 | 役割文書なし | R.1 責任分界表（ARCHITECTURE） | - | - | 設計文書 |
| 19 | PASS 済み検証の再実行 | 記録なし | #8 と同じ（SHA keyed） | - | - | Test Selection |
| 20 | 手動 Revision/status 確認 | smoke 自動化なし | smoke engine + /status release_info | smoke 結果を LINE 報告 | 自動 rollback | Smoke Engine |

## KPI（Release OS 完成時）

| KPI | 目標 | 実現機構 |
|---|---|---|
| Merge→Production | 15分以内 | build1回+同一image配布 / test skip / no-traffic staging |
| ゆうさん操作 | YES 1回 | Environment 承認（LINE リンク1タップ） |
| 貼り付け / ローカル操作 | 0 | Merge 起点の全自動 |
| Full Test 重複 | 0 | SHA+testset skip |
| 環境差事故 | 0 | 固定 CI |
| 失敗検知 | 5分以内 | smoke timeout 5分 + heartbeat |
| rollback | 3分以内 | update-traffic は秒単位 + 検証2分 |
| 監査 coverage | 100% | Ledger 必須 step（ledger 失敗=deploy 失敗扱い） |
| Secret 露出 / 対象外誤 deploy / 1日ハング / 手動 Revision 確認 | 0 | add-mask+SM / allowlist / timeout / smoke |
