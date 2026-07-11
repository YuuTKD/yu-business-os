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
