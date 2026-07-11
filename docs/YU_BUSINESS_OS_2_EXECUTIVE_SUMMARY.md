# YU Business OS 2.0 — Executive Summary

作成日: 2026-07-11  
作成者: Claude Code（監査フェーズ）  
用途: ゆうさんへの意思決定報告

---

## 現状評価（2026-07-11 フルスキャン）

### YU HOLDINGS 全体スコア

| 評価軸 | スコア | 根拠 |
|---|---|---|
| インフラ安定性 | **A** | 7 Cloud Run + Scheduler 稼働中、毎朝 8:30 自動監視 |
| コンテンツ自動化 | **B** | Beauty/Catering/Hinabe は稼働、TACHINOMIYA のみ ALMOST_READY |
| 財務管理 | **B** | 月次目標 ¥9.8M 設定済み、週次・月次レポート自動化 |
| ガバナンス | **A** | PR フロー・12 点レビュー・Codex 120 点運用中 |
| セキュリティ | **B** | Secret 管理適切、LINE broadcast リスクが 1 件残存 |
| 技術的負債 | **C** | 設定二重管理・DRY_RUN 欠如・data/reports 過増殖 |

### 月商ポテンシャル vs 現状

```
TACHINOMIYA   ¥3,500,000 目標 → Scheduler OFF で機会損失中
Trees Catering ¥800,000 目標  → 稼働中
Tree Beauty    ¥500,000 目標  → 稼働中
パスタパスタ   ¥2,000,000 目標 → 稼働中
Z1             ¥1,500,000 目標 → 稼働中
琉球火鍋       ¥1,500,000 目標 → 稼働中
─────────────────────────────
合計目標       ¥9,800,000 / 月
```

**TACHINOMIYA の Scheduler OFF が最大の機会損失**。  
READY 化により自動投稿が開始され、Google/Threads への露出が増える。

---

## ゆうさんへの意思決定事項（優先順）

### 今すぐ実施（2026-07-11 中）

**1. LINE_TACHINOMIYASTAFF_TOKEN を Cloud Run で空に設定**
- 手順書: `data/reports/tachinomiya_line_staff_token_disable_procedure.txt`
- 効果: broadcast 誤通知リスクがゼロになる
- 所要時間: 約 5 分（GCP Console 操作）

**2. スタッフへ撮影依頼 LINE を送信**
- 送付文: `data/reports/tachinomiya_staff_photo_request_send_now.txt`
- 効果: 最短 7/18 に内観写真が揃い、READY 化に近づく

**3. Meta Developers で Threads token 期限確認**
- Scheduler ON 前の必須確認事項
- 60 日有効のため、残り 30 日以上を確認

---

### 7/18 以降（写真が揃ってから）

**4. 写真承認 → Claude Code に IMAGE_LIBRARY 登録依頼**
- 手順書: `data/reports/tachinomiya_image_registration_request_template.txt`
- Claude Code が自動登録・GCS 化・HTTP200 確認を実施

**5. Scheduler ON の最終判断（Claude Code が READY 報告後）**
- Claude Code は「READY です」と報告するだけで、実行しない
- ゆうさんが GCP Console で手動実施

---

### 7/25 以降（Scheduler 安定稼働後）

**6. owner LINE 通知切り替え PR の承認**
- PR 内容: `LINE_TACHINOMIYASTAFF_TOKEN` → `LINE_OWNER_TOKEN` に 1 行変更
- 効果: 投稿完了をゆうさんの LINE に通知
- リスク: HIGH（core/ 変更・Cloud Run 再デプロイ必要）

---

## 2.0 アーキテクチャの概要

2.0 は既存システムを **壊さず** に上位レイヤーを追加する設計。

```
[ 現行 1.x（変更しない）]
  core/ agents/ configs/ skills/ scripts/ data/
    ↓ 読み取り・呼び出しのみ
[ 2.0 追加レイヤー ]
  ガバナンス強化（PR フロー改善）
  単一設定源（business_registry.py 統一）
  DRY_RUN 標準化（全エンドポイント対応）
  通知ゲートウェイ（LINE_OWNER_TOKEN 統一）
  品質ゲート（投稿品質・Scheduler 準備・デプロイ前 QA）
```

---

## リスク評価

### 現在アクティブなリスク（要対応）

| リスク | 重大度 | 対応状況 |
|---|---|---|
| LINE broadcast → スタッフ誤通知（TACHINOMIYA）| HIGH | Q1=YES で空化対応中（ゆうさんタスク） |
| TACHINOMIYA Scheduler OFF → 機会損失 | HIGH | 画像補充完了後 READY 化で解消 |
| Threads token 期限未確認 | MEDIUM | ゆうさんが今週確認 |

### 技術的負債（計画的に解消）

| 負債 | 重大度 | 解消フェーズ |
|---|---|---|
| 設定二重管理（business_registry.py vs _BUSINESS_CONFIGS）| HIGH | フェーズ 4 |
| DRY_RUN 未実装（content engine）| HIGH | フェーズ 3 |
| LINE トークン命名不統一 | MEDIUM | フェーズ 7 |
| data/reports/ 過増殖（70+ ファイル）| MEDIUM | ゆうさん承認後に整理 |

### 休止中のリスク（変化なし）

| システム | 状態 | 再開条件 |
|---|---|---|
| 商品マッチ先 AI エージェント | PAUSED | ゆうさん明示承認のみ |
| GBP 自動投稿 | 準備済み・未デプロイ | GBP API 承認 |
| SNS PDCA Phase3（Gemini リライト）| 待機中 | Gemini API キー取得 |

---

## 5 ファイルの位置づけ

| ファイル | 用途 |
|---|---|
| `YU_BUSINESS_OS_2_ARCHITECTURE.md` | 全資産インベントリ + 13 レイヤー設計 |
| `YU_BUSINESS_OS_2_MIGRATION_MAP.md` | 1.x → 2.0 の資産マッピング + リスク評価 |
| `YU_BUSINESS_OS_2_DATA_CONTRACTS.md` | 全インターフェース仕様（設定・API・LINE）|
| `YU_BUSINESS_OS_2_IMPLEMENTATION_ROADMAP.md` | フェーズ計画・GO 条件・タイムライン |
| `YU_BUSINESS_OS_2_EXECUTIVE_SUMMARY.md` | このファイル（意思決定サマリー）|

---

## 次の作業（ゆうさんへのアクション依頼）

```
今日中:
  1. GCP Console → Cloud Run → LINE_TACHINOMIYASTAFF_TOKEN を空に
  2. スタッフに撮影依頼 LINE を送信
  3. Meta Developers で Threads token 期限を確認

写真が揃ったら:
  4. ゆうさんが写真を承認し「IMAGE_LIBRARY 登録をお願いします」と Claude Code に依頼

READY 報告後:
  5. GCP Console で Scheduler ON（最終判断はゆうさん）
```

**Claude Code がゆうさんの承認なしに実施すること: 設計書の追加・読み取り・分析のみ**

---

*このドキュメントは 2.0 設計フェーズの成果物です。実装・デプロイ・Scheduler 変更・LINE 送信はすべて別途ゆうさんの承認が必要です。*

---

## Phase A 実装完了報告（2026-07-11）

設計だけで終わらせず、2.0 の**土台（Registry & Governance）を実装**した。

**何ができるようになったか**
- Skill を一元管理（10件）。Unknown skill でも安全に fallback する
- Agent を一元管理（9件）。全 Agent が原則 default deny（外部送信・デプロイ・Scheduler・Secret アクセスすべて禁止）
- 危険操作を機械判定（GO / FIX / STOP / OWNER_APPROVAL_REQUIRED）
- Registry の参照不整合を CLI で自動検査（`RESULT: GO`）

**安全性**: 外部送信ゼロ・deploy ゼロ・Scheduler 変更ゼロ・Secret 非表示・
既存ファイル無変更。Unit Test **52件 全 pass**。本番未接続。

**ゆうさんが判断すること**
1. この Phase A PR を Merge するか（高リスク: `core/` 追加を含むため Merge 前停止・人間承認待ち）
2. Phase B（設定二重管理の解消 = 売却可能性を高める）を開始してよいか

**このPRのリスク**: HIGH（`core/**`, `configs/**`, `scripts/**` への追加を含む）。
自動 Merge はしない。既存本番へは未接続のため、Merge しても即時の本番影響はない。

---

## Phase D-Lite 実装完了報告（2026-07-11）

Phase A の Governance Validator を**既存 PR 自動フローに接続**した。これで
PR ごとに危険を機械判定して止められる（人手の見落としを防ぐ安全ネット）。

**何ができるようになったか**
- PR 作成前に、変更差分を見て GO / FIX / STOP / 承認要 を自動判定
- Secret 混入・`.env`・credentials・`scripts/acquisition`・Tree Beauty 有効化・`daily_post_limit` 変更を検知して STOP
- HIGH リスクは承認があっても**自動 Merge しない**（人が Merge）
- 判定不能・エラー時は**必ず止まる**（fail-closed、通してしまわない）

**安全性**: 外部通信ゼロ・gh 不要・deploy/送信/Scheduler 変更なし・Secret 非出力。
Unit Test **91件 全 pass**（39件追加）。既存 PR フローの gh 処理は不変。

**ゆうさんが判断すること**
1. この Phase D-Lite PR を Merge するか（HIGH: `core/` `scripts/` 変更を含む → 人間承認必須）
2. 次は **Phase B（設定二重管理の解消）** へ進むか

---

## Phase B1 実装完了報告（2026-07-11）

事業設定の **正本（Single Source of Truth）** を追加した。これまで6事業の設定が
**5箇所にバラバラ**に存在し、値がズレていた（例: TACHINOMIYA の月商目標が
片方 120万・片方 350万）。この乖離を自動検出できるようになった。

**何ができるようになったか**
- 6事業の設定を 1 つの正本（`configs/businesses/registry.yaml`）で表現
- 既存設定との差分を自動検査（欠損・値違い・重複・事業混入を検出）
- 差分は**自動で書き換えず FIX として報告**（安全側）
- Secret 値は一切保存しない（環境変数の**名前だけ**管理）

**安全性**: 本番未接続（既存コードは従来どおり動く）・自動同期なし・既存設定無変更。
Unit Test **142件 全 pass**。実際に既存の設定ズレ（TACHINOMIYA 目標・hinabe 重複・
LINE トークン名の不一致）を検出済み。

**経営上の意味**: 事業を増やす／売却する際、設定が1箇所に集約されていることは
引き継ぎ・監査・値の信頼性を大きく高める。今回はその土台（読取・検査のみ）。

**ゆうさんが判断すること**
1. この Phase B1 PR を Merge するか（HIGH: `core/` `configs/` `scripts/` 追加 → 人間承認必須。本番未接続のため即時影響なし）
2. Phase B2（検出された設定ズレを整理し、本番読込先を正本へ段階接続）へ進むか

---

## Phase B1.1 実装完了報告（2026-07-11）

B1 で見つかった**設定ズレ5件を、ゆうさん確定値で解消**した。

**確定値**
- TACHINOMIYA 月商目標: **550万円**（昼 サーターアンダギー 250万 + 夜 BAR 300万）
- 火鍋の正式ID: `ryukyu_hinabe`（旧 `hinabe` は別名として互換維持）
- TACHINOMIYA スタッフ LINE: 正式 `LINE_TACHINOMIYA_STAFF_TOKEN`（旧名は互換維持）

**結果**: 設定検査は **GO（ズレ 0件）** に。売却・引き継ぎ時に「設定が1箇所で正しい」
状態に一歩前進。旧名は**削除せず併存**（安全な移行期間）。token 値は一切扱わず、
スタッフ通知は必ずオーナー承認が必要な設計。

**安全性**: 本番未接続・自動同期なし・env 変数の実体は変更なし・Secret 非表示。
Unit Test **161件 全 pass**。

**ゆうさんが判断すること**
1. この Phase B1.1 PR を Merge するか（HIGH → 人間承認必須。本番未接続のため即時影響なし）
2. Phase B2（本番読込先を正本へ段階接続）へ進むか

---

## Phase B2-1 実装完了報告（2026-07-11）

TACHINOMIYA を対象に、正本（SSOT）と現行設定（Legacy）を**実行時に突き合わせる
仕組み**を追加した。ただし **実際に使う値は今まで通り Legacy**（安全な影武者接続）。

**何ができるようになったか**
- TACHINOMIYA の設定が SSOT と一致しているか、いつでも検査できる（`--mode` で厳格度も選べる）
- ズレたら安全に止まる（fail-closed）／一致していれば Legacy のまま継続
- token 値は一切読まず・出さず、外部通信もゼロ

**安全性**: 本番の読込先は**切替えていない**（runtime_source は常に LEGACY）。
Cloud Run・Scheduler・投稿・LINE 送信いずれも未接続。Unit Test **181件 全 pass**、
Shadow 検査は **GO（ズレ0件）**。

**経営上の意味**: 正本への完全移行（設定を1箇所に集約）へ向けた、事故ゼロの一歩。
次段階で初めて「実際に SSOT を使う」切替を、TACHINOMIYA から 1 事業ずつ慎重に行う。

**ゆうさんが判断すること**
1. この Phase B2-1 PR を Merge するか（HIGH → 人間承認必須。本番未切替のため即時影響なし）
2. Phase B2-2（TACHINOMIYA の読込先を実際に SSOT へ切替）へ進むか
