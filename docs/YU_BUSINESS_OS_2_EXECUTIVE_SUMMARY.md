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

---

## Phase B2-2 実装完了報告（2026-07-11）

TACHINOMIYA だけ、設定の**第一候補を正本（SSOT）に切替**えられるようにした。
ただし SSOT に問題があれば**自動で従来（Legacy）に戻る**安全装置つき。

**何ができるようになったか**
- TACHINOMIYA の設定を SSOT 優先で読める（承認必須）。ズレていれば SSOT は使わず止まる
- SSOT が読めない/不完全なら Legacy に自動フォールバック（理由も記録）
- 他事業は従来どおり Legacy のまま。戻したいときは 1 引数（`LEGACY_ONLY`）で即復旧

**安全性**: Cloud Run へのデプロイ・Scheduler・投稿・LINE 送信いずれも**なし**。
本番の常時経路はまだ切替えておらず（承認時のみ SSOT）、token 値は読まず・出さず、
外部通信ゼロ。Unit Test **206件 全 pass**。

**経営上の意味**: 「設定を1箇所（正本）に集約して使う」実移行の第一歩を、事故ゼロ・
即ロールバック可能な形で TACHINOMIYA から開始した。

**ゆうさんが判断すること**
1. この Phase B2-2 PR を Merge するか（HIGH → 人間承認必須。本番常時経路は未切替＝即時影響なし）
2. Phase B2-3（本番経路への段階接続 → 将来 Legacy 廃止）へ進むか

---

## Phase B2-3 実装完了報告（2026-07-11）

本番の設定読込経路（entrypoint）に、正本（SSOT）の判定器を**スイッチ付きで接続**した。
**スイッチは既定オフ（LEGACY_ONLY）＝今までと完全に同じ動作**。

**何ができるようになったか**
- 環境変数のスイッチ（`YU_CONFIG_RUNTIME_MODE`）で、TACHINOMIYA のみ SSOT 判定を有効化できる
- 有効化は owner 承認時のみ。SSOT が使えない/ズレていれば自動で Legacy に戻る
- スイッチを既定に戻すだけ（1 設定）で即ロールバック

**安全性**: 既定では判定器すら呼ばず、設定オブジェクトは**一切変更せず同じものを返す**
（形も値も不変）。Cloud Run へのデプロイ・Scheduler・投稿・LINE 送信いずれも**なし**。
token 値は読まず・出さず、外部通信ゼロ、起動を止めない（fail-closed）。
Unit Test **225件 全 pass**。

**経営上の意味**: 「本番が正本を見に行く」配線を、既定オフ・即ロールバック可能な形で
安全に敷設した。実際に SSOT の値で動かす切替は次段階（B2-4）で慎重に行う。

**ゆうさんが判断すること**
1. この Phase B2-3 PR を Merge するか（HIGH → 人間承認必須。既定オフのため即時影響なし）
2. Phase B2-4（判定のみ→SSOT 値の実供給、将来 Legacy 廃止）へ進むか

---

## Phase B2-4 Batch 1 実装完了報告（2026-07-11）

正本（SSOT）を「一致チェックに使うだけ」から、**SSOT の値を実際の設定として供給できる
段階**へ進めた。対象は **3事業（TACHINOMIYA / TREE'S CATERING / TREE BEAUTY）**。

**何ができるようになったか**
- owner 承認時のみ、この3事業の設定を SSOT 由来で供給（形は従来と同一・値は SSOT 発）
- SSOT がズレ/読めない時は自動で Legacy に戻り、ズレは**隠さず報告**（FIX）
- 対象外の3事業（火鍋・パスタ・Z1）は従来のまま。スイッチ既定オフで挙動不変

**安全性**: 既定 LEGACY_ONLY で完全同一挙動。**LINE トークン名などの env 実体は変更せず**
（Cloud Run を壊さない）、Secret 値は読まず・出さず、外部通信ゼロ。deploy・Scheduler・
投稿・LINE 送信いずれもなし。Unit Test **255件 全 pass**、供給チェック **batch GO**。

**経営上の意味**: 「設定を正本1箇所で持ち、本番がそれを使う」への実移行を、3事業・
即ロールバック可能・事故ゼロの形で開始した。

**ゆうさんが判断すること**
1. この Phase B2-4 Batch 1 PR を Merge するか（HIGH → 人間承認必須。既定オフのため即時影響なし）
2. Batch 2（火鍋 → パスタ・Z1）へ進むか

---

## Phase B2-4 Batch 2 実装完了報告（2026-07-12）

SSOT 供給の対象に **琉球火鍋（ryukyu_hinabe）のみ**を追加した。パスタ・Z1 は**対象外・
一切変更なし**。旧名 `hinabe` は別名として維持され、別名で呼んでも同じ設定になる。

**要点**
- owner 承認時のみ火鍋を SSOT 由来 config で供給（形は従来同一・値は SSOT 発）
- POS/売上連携・別オーナーのメール・承認ポリシーは従来どおり保持
- GBP 自動化・投稿・LINE・Gmail・Scheduler・Cloud Run は**有効化しない**
- 既定 LEGACY_ONLY ＝ 挙動不変・`YU_CONFIG_RUNTIME_MODE=LEGACY_ONLY` で即ロールバック

**安全性**: Secret 値は読まず・出さず、外部通信ゼロ、deploy なし。Unit Test **275件 全 pass**。

**ゆうさんが判断すること**
1. この Batch 2（火鍋）PR を Merge するか（HIGH → 人間承認必須・既定オフで即時影響なし）
2. 次候補（パスタ・Z1）へ進むか

---

## Phase B2-5 実装完了報告（2026-07-12）

SSOT 供給対象の **4事業**を本番接続前に判定する「準備完了ゲート」を追加した。
**判定するだけ**で、deploy・投稿・LINE・Scheduler 変更は一切しない。

**現状の判定（承認・運用確認まだ）**
- **TACHINOMIYA → ALMOST_READY**（画像不足・Threads token 未確認・Google 認証未確認）
  ※「画像不足なのに READY」にはしない安全設計
- Catering / Beauty / 琉球火鍋 → **OWNER_APPROVAL_REQUIRED**（技術的には準備完了・承認待ち）
- パスタ・Z1 → NOT_READY（対象外・不変）

**判定の意味**
- READY = 本番接続の技術条件+承認+運用確認が揃った（deploy はさらに別承認）
- ALMOST_READY = 危険ではないが不足あり（例: 火鍋店の写真不足）
- STOP = Secret・事業混入・危険な有効化など（絶対に通さない）

**安全性**: 監査のみ・外部通信ゼロ・Secret 非表示・既定 LEGACY_ONLY 不変・
rollback 可。Unit Test **300件 全 pass**。

**ゆうさんが判断すること**
1. この Readiness Gate PR を Merge するか（HIGH → 人間承認必須・監査のみで即時影響なし）
2. TACHINOMIYA の運用確認（画像補充・token・GBP）を進め READY 化するか

---

## Phase B2-6 実装完了報告（2026-07-12）

ゆうさんの承認（Catering・Beauty・琉球火鍋）を**監査可能な台帳に記録**し、3事業を
**READY** に更新した。TACHINOMIYA は自動監査し、本番接続を**予行演習（Dry Run）**した。

**結果**
- Catering / Beauty / 琉球火鍋 → **READY**（承認記録済み）。ただし **deploy は別承認**
- TACHINOMIYA → **ALMOST_READY**（写真不足 + Threads token/Google 認証は要手動確認）
  ※ token・認証の値は一切読まず、期限は「Meta/GCP で要確認」と正直に報告
- 本番接続 Dry Run: 3事業は「readiness 完了・deploy 承認待ち」、火鍋店は「準備未了」で停止
- **実際の deploy・投稿・LINE・Scheduler 変更は一切なし**。全事業 1 設定で即ロールバック可

**重要な線引き**: 今回の承認は**「準備完了」の承認**であって、**deploy（本番反映）の承認では
ありません**。deploy はさらに別の承認が必要です（今回は未承認＝実行なし）。

**安全性**: Secret 非表示・外部通信ゼロ・既定 LEGACY_ONLY 不変。Unit Test **339件 全 pass**。

**ゆうさんが判断すること**
1. この Readiness 承認 + Activation Dry Run PR を Merge するか（HIGH → 人間承認必須・本番操作なし）
2. TACHINOMIYA の写真補充・token/GBP 確認を進めるか / deploy 承認へ進むか（別 PR）

---

## Phase B2-7 実装完了報告（2026-07-12）

READY 3事業（Catering・Beauty・琉球火鍋）を **「deploy 直前」の状態**まで準備し、
TACHINOMIYA の技術確認を行った。**実際の deploy・投稿・LINE 送信は一切なし**。

**結果**
- Catering / Beauty / 琉球火鍋 → **PREPARED**（準備完了・deploy 承認だけ待ち）
  - Cloud Run サービス名・プロジェクト・リージョン・環境変数名を確定、ロールバック手順も検証
  - deploy コマンドは「候補（実行しない）」として生成。**deploy 承認は未付与**
- TACHINOMIYA → **要手動確認**
  - Threads token・Google 認証は「設定は存在するが、有効性/期限は値を読まずに確認できない」→ 手動確認要
  - 写真は **15枚不足**（店内+4 / ドリンク+5 / 外観+6）
  - Scheduler OFF 維持・投稿ゼロ・LINE ゼロ

**重要な線引き**: 今回は**「deploy できる直前まで」の準備**であって、**deploy そのものの承認では
ありません**。deploy はさらに別の承認が必要です（今回は未承認＝実行なし）。全事業 1 設定で即ロールバック可。

**安全性**: Secret/token 非表示・非読取、外部通信ゼロ、コマンド実行フラグ常に false。
Unit Test **371件 全 pass**。

**ゆうさんが判断すること**
1. この Activation 準備 PR を Merge するか（HIGH → 人間承認必須・本番操作なし）
2. TACHINOMIYA の写真補充・token/GBP 手動確認 / **deploy 承認**（別 PR）へ進むか

---

## Release & Operations OS 設計完了報告（2026-07-15）

### 何が問題だったか

PR #20（全事業の画像生成停止・LINE 文章配信継続）は、コード自体は数時間で完成した
のに、**本番反映に1日以上**かかりました。原因はコードではなく反映経路です:
Mac の Bash/Python 環境差・requirements 不足・gcloud 未導入と認証切れ・同じ 388 テスト
の繰り返し・長いスクリプト貼り付け・Revision の手動確認・timeout なしの待機。

### 最終構成（1行で）

**「PR Merge → 自動テスト → 自動 Staging → LINE に承認通知 → ゆうさんが YES 1タップ →
1事業ずつ自動反映 → 異常なら自動で元に戻す → 記録と完了報告が届く」**

- 実行主体は GitHub Actions（Claude Code の本番 deploy 禁止は維持したまま解決）
- Staging は本番サービスへの「客に見えない 0% リビジョン」= 追加費用ゼロで本番と同一環境
- 承認は GitHub Environment が正本（YES はLINE 内リンクの1タップ・1回限り・使い回し不可）
- 記録は GCS の Deployment Ledger（改ざん耐性あり・監査 100%）
- pasta_pasta / z1 / 琉球火鍋 / yu-holdings-ai は allowlist 外＝構造的に誤 deploy 不可能

### 金額・時間インパクト

| 項目 | Before（PR #20 実績） | After（目標） |
|---|---|---|
| Merge→本番反映 | 1日以上 | **15分以内** |
| ゆうさんの操作 | 貼り付け・実行・確認 多数 | **YES 1タップ** |
| 月額追加コスト | — | **約¥100 未満**（Actions 無料枠内 / GCS 数円 / AR 数十円） |
| 環境差事故・重複テスト・手動確認 | 頻発 | 0（構造的に排除） |

### 実装優先順位（詳細は ROADMAP Phase R0–R8）

R1 固定CI（0.5日）→ R2 差分テスト（0.5日）→ R3 Staging+Smoke（1日）→ R4 Ledger（0.5日）
→ R5 YES 1タップ承認（0.5日）→ R6 catering canary → R7 3事業 → R8 復旧強化。
**合計 約5人日 + ゆうさんの1回だけの設定 約40分**（GCP 30分・GitHub 5分・承認テスト）。
最短 MVP = R1+R3+R5+R6（約2.5日）で「YES 1回 deploy」が catering で動く。

### 最大リスク と 対策

1. **traffic 昇格の自動化そのもの** → 1事業ずつ / smoke fail-closed / 3分 rollback /
   canary 期間中は従来手動手順を併存
2. WIF・Environment の初期設定ミス → 人間作業は runbook 化された40分だけ、R6 前に
   意図的 rollback 試験で検証
3. 承認の形骸化（YES 慣れ） → 通知に risk / 変更概要 / smoke 結果を必ず記載、
   CRITICAL は自動実行しない原則を維持

### ゆうさんの YES / NO 判断項目

1. この Release OS 設計で進めてよいか（**GO なら R1 実装へ**）
2. 承認の正本を GitHub Environment（LINE はリンク通知）とする方式でよいか
3. Ledger 保存先を GCS とすることでよいか
4. R6 canary の第1事業を catering とすることでよいか

### Phase R1 実装完了（2026-07-15・本番非接触）

**入れたもの**: PR を出すたびに、GitHub 上の**固定環境**（Ubuntu + Python 3.11・毎回同じ
バージョンの依存）で「文法チェック → 安全ゲート → 388テスト」が自動で走る仕組み。
これで PR #20 の1日遅延を招いた「Mac の Bash/Python 差・依存不足・手元テスト」が構造的に
消えます。**本番には一切触れません**（deploy も gcloud も Secret も無し）。

**ファイル**: `.github/workflows/pr-validation.yml`（新規1本）+ `requirements.lock`（依存の
固定表）+ 設計書5冊の追記のみ。既存の仕組みは何も壊していません。

**ゆうさんの操作**: この PR を Merge するか YES/NO の1回だけ（緑チェックを確認 → Merge）。
**次（R2）はまだ着手していません**。Merge 後に指示があれば進めます。

### Phase R2 実装完了（2026-07-15・本番非接触）

PR ごとに「変更内容を自動分類 → 必要なテストだけ実行」する仕組みを追加。ドキュメントだけの
変更ならテスト0秒、一部変更なら関連分だけ、危険な変更や判定不能は自動的に全テスト（安全側）。
分類ルールは既存の1ファイル（`diff_risk.py`）に集約し、新しい仕組みを増やしていない。
本番には一切触れていない。ゆうさんの操作は「この PR を Merge する」YES 1回。

### Phase R2.5 実装完了（2026-07-16・本番非接触）

R3 以降に必要な土台（GitHub↔Google Cloud の鍵なし連携=WIF、権限を絞った3つの実行役、
画像置き場、デプロイ記録の保管庫）を**一度だけ作るためのスクリプト**を用意。既定は「表示のみ
（何も変えない）」で、実際に作る `--apply` はゆうさんが承認して実行する1コマンド。長期鍵は作らず、
記録保管庫は「追記のみ（上書き・削除不可）」。私は read-only の確認までを実施済み。
次にゆうさんに実行いただく `--apply` と GitHub の承認環境作成が、R3 本番検証の前提。

## Phase R3 実装結果 + R2.5 Retention 例外（2026-07-16）

R2.5 retention は OWNER_ACCEPTED_EXCEPTION（34495200s≈399d18h・2026-07-16 承認・policy 変更なし・verify=READY_WITH_EXCEPTION）。
R3: `release.yml`(workflow_dispatch のみ・WIF・SHA build→AR→`--no-traffic --tag candidate`→read-only smoke・**update-traffic なし**) + `smoke_test.py` + `configs/release/services.yaml`(endpoint SSOT) + `/status` read-only 拡張。対象=trees-catering-ai のみ(allowlist)。457 tests PASS。candidate deploy は未実行(次の owner YES)。本番 traffic/Scheduler/Secret 不変。
