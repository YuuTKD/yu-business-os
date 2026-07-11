# AUTO_PR_FLOW.md — Codex 120点 PR 自動フロー全体設計

## 概要

YU HOLDINGS AI-EOS において、Claude Code が作成した変更は **全て Codex による監査** を経てから Merge される。

Codex は単なるコードレビュー役ではなく：

- **品質責任者** — 実装品質・仕様整合を検証
- **安全監査役** — Secret・本番影響・既存破壊を監査
- **売上導線監査役** — 変更が売上に繋がるか評価
- **自動化暴走防止役** — Scheduler・自動送信の暴走を阻止

Codex は「する」のではなく「させない」が主な仕事。

---

## フロー全体図

```
┌─────────────────────────────────────────────────────────┐
│  Claude Code (司令塔)                                    │
│  設計 → TASK.md 更新 → 実装 → PR 作成                   │
└─────────────────────┬───────────────────────────────────┘
                      │ PR 作成
                      ▼
┌─────────────────────────────────────────────────────────┐
│  Codex 120点レビュー                                     │
│  scripts/agent/pr_auto_flow.sh <PR番号>                 │
│                                                         │
│  ① 12観点チェック                                       │
│  ② 売上直結度スコア (S/A/B/C/D)                         │
│  ③ リスク分類 (Low/Medium/High)                         │
│  ④ FIX_ATTEMPT 管理                                    │
└──────┬──────────────┬──────────────────────────────────┘
       │ GO           │ FIX               │ STOP
       ▼              ▼                   ▼
┌──────────┐  ┌───────────────┐  ┌──────────────────┐
│ Safe     │  │ 修正指示      │  │ 即時停止          │
│ Merge    │  │ FIX_ATTEMPT++ │  │ Merge禁止         │
│ Gate     │  │ 再レビュー    │  │ ゆうさん承認待ち  │
└──────┬───┘  │ (最大3回)     │  └──────────────────┘
       │      └───────┬───────┘
       │              │ 3回超え → STOP
       ▼
┌──────────────────────────────────────────────────────────┐
│  リスク別 Merge ルール                                    │
│  Low    → Merge候補（人間承認後）                         │
│  Medium → Safe Merge Gate後、人間確認                    │
│  High   → Merge前で停止、ゆうさん最終判断               │
└──────────────────────────────────────────────────────────┘
```

---

## 売上直結度スコア

| スコア | 定義 | 対応 |
|---|---|---|
| **S** | 7日以内に売上直結 | GO（高優先度） |
| **A** | 30日以内に売上直結 | GO |
| **B** | 中長期の自動化・効率化 | GO |
| **C** | 管理・ドキュメントのみ | FIX（スコープ確認） |
| **D** | ターゲット外・スコープ外 | FIX（方針確認） |

スコア C/D は GO にしない。スコープ確認を求めてから再レビュー。

---

## リスク分類

### Low（docs/reports/dataのみ）

変更が以下のみの場合：
- `docs/**` / `obsidian/**` / `data/revenue_portfolio/**` / `data/analytics/**`
- `README.md` / `TASK.md` / `REPORT.md`

→ Codex GO 後、Safe Merge Gate → 人間承認でMerge

### Medium（DRY_RUN・テスト・軽微修正）

- `scripts/**` の DRY_RUN 専用スクリプト
- `data/reports/**` のCSV/ログ追記
- `core/**` の設定値変更なしバグ修正

→ Codex GO → Safe Merge Gate → **人間確認必須** → Merge

### High（機能変更・API・本番系）

以下のいずれかを含む：
- `scripts/**` / `agents/**` / `config/**` / `apps/**` / `core/**` の機能変更
- `.env` / `.env.local` / `package.json`
- Cloud Run / Scheduler / API / OAuth
- LINE / Gmail / SNS / 自動DM / 自動リプ
- Google Workspace 本番 / 顧客データ / 決済

→ Codex GO でも **Merge前で必ず停止** → ゆうさんが最終判断

---

## FIX_ATTEMPT 管理

ファイル: `data/reports/fix_attempt_pr_<N>.txt`

```
FIX_ATTEMPT=1
LAST_FIX=2026-07-10
REASON=Revenue score C: docs-only change
```

| FIX回数 | 動作 |
|---|---|
| 1回目 FIX | 修正指示 → commit → push → 再レビュー |
| 2回目 FIX | 修正指示 → commit → push → 再レビュー |
| 3回目 FIX | 修正指示 → commit → push → 再レビュー |
| 4回目以降 | **STOP** に格上げ → 人間確認必須 |

GO 完了時は fix_attempt ファイルを自動削除する。

---

## 12観点レビュー詳細

| # | 観点 | STOP条件 | FIX条件 |
|---|---|---|---|
| 1 | OS整合 | — | 方針逸脱 |
| 2 | 既存破壊NG | 既存削除・上書き | — |
| 3 | Cash-First | キャッシュ悪化 | — |
| 4 | Secret混入NG | diff にSecret | — |
| 5 | 本番影響NG | 自動送信・deploy・Scheduler | — |
| 6 | TASK整合 | — | スコープ外変更 |
| 7 | REPORT更新 | — | 未更新 |
| 8 | 売上直結度 | — | スコアC/D |
| 9 | リスク分類 | — | 判定不能 |
| 10 | 自動化暴走 | acquisition再開・Tree Beauty有効化 | 怪しいパターン |
| 11 | FIX_ATTEMPT | >3回 | — |
| 12 | 禁止事項 | 絶対禁止リスト | 軽微違反 |

---

## 実行コマンドまとめ

```bash
# PR レビュー実行
bash scripts/agent/pr_auto_flow.sh <PR番号>

# Safe Merge Gate 単体実行
bash scripts/agent/safe_auto_merge_pr.sh <PR番号>

# FIX_ATTEMPT 確認
cat data/reports/fix_attempt_pr_<N>.txt

# FIX_ATTEMPT リセット（手動）
rm data/reports/fix_attempt_pr_<N>.txt
```

---

## 絶対禁止事項

- 実投稿・自動送信（LINE・メール・SNS・DM・リプ）
- Scheduler の新規作成・時刻変更・ON化
- 本番 Cloud Run デプロイ
- 本番 Google Sheets 直接変更
- `.env.local` の閲覧・変更
- Secret/Token/APIキーの表示・直書き
- Tree Beauty を有効化・商品マッチ対象にする
- `scripts/acquisition` の再開
- `daily_post_limit` の増加
- 既存 AI-EOS 構成の破壊
- `git add .` の使用

---

## Governance Gate（Phase D-Lite・2026-07-11 追加）

Phase A の Governance Validator を PR フローの**先頭**に接続した。gh に依存せず
ローカル diff だけで判定するため、PR 作成前でも実行できる。

### 実行位置

```
pr_auto_flow.sh 起動
  → [0/5] Governance Gate（governance_gate.py・ローカル diff）  ← 追加
       GO 以外はここで停止（fail-closed）
  → [1/5] PR 情報取得（gh）
  → [2/5] リスク分類
  → ... 既存フロー
```

### アダプタ構成（既存判定ロジックを重複させない）

```
scripts/agent/governance_gate.py   diff 収集 → 事実抽出 → Validator 呼び出し
core/governance/diff_risk.py       ファイル→risk 分類（単一ソース・純関数）
core/governance/validator.py       GO/FIX/STOP/OWNER_APPROVAL 判定（唯一の決定者）
```

Shell は exit code だけを解釈する:

| exit | 判定 | Shell の挙動 |
|---|---|---|
| 0 | GO | 既存フロー継続 |
| 10 | FIX | 停止 |
| 20 | OWNER_APPROVAL_REQUIRED | ゆうさん承認待ちで停止 |
| 30 | STOP | 即停止 |
| 40 | INTERNAL_ERROR | STOP 扱い（fail-closed）|

### 安全特性

- **fail-closed**: import 失敗 / git diff 失敗 / base ref 不存在 / 不明 decision → INTERNAL_ERROR → STOP
- **owner approval**: `YU_OWNER_APPROVED=true`（1回限り・非永続・.env に書かない）または `--owner-approved`
- **HIGH** は承認があっても自動 Merge しない（human merge のみ）
- **CRITICAL**（.env / credentials / secret / scripts/acquisition / Tree Beauty 有効化 / daily_post_limit 変更）は承認があっても STOP
- Secret 値・token 値は一切出力しない
- 外部通信なし・gh 不要・GitHub API 不要

### rollback

追加のみ（`governance_gate.py` / `diff_risk.py` / 4行未満の pr_auto_flow.sh 呼び出し追加）。
PR を Merge しなければ影響なし。既存 pr_auto_flow.sh の gh ベース処理は不変。

---

## 更新履歴

| 日付 | 変更内容 |
|---|---|
| 2026-07-10 | Codex 120点運用ルール初版作成 |
| 2026-07-11 | Phase D-Lite: Governance Gate をフロー先頭に接続（fail-closed）|
