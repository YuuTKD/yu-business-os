# /pr-auto-flow — Codex 120点 PR 自動フロー

## 使い方

```
/pr-auto-flow <PR番号>
```

例: `/pr-auto-flow 5`

---

## このコマンドがすること

0. **Governance Gate**（`governance_gate.py`）をローカル diff に対して最初に実行（gh 非依存・fail-closed）
1. **12観点レビュー** を実施（AGENTS.md に準拠）
2. **売上直結度スコア** を付与（S / A / B / C / D）
3. **リスク分類** を判定（Low / Medium / High）
4. **GO / FIX / STOP** を出力
5. **FIX_ATTEMPT** カウンターを管理（`data/reports/fix_attempt_pr_<N>.txt`）
6. GO + Low リスクの場合: `safe_auto_merge_pr.sh` を実行

### Step 0: Governance Gate（Phase D-Lite）

Phase A の Governance Validator を PR フローの**最初**に実行する。GO 以外は
gh ベースの処理へ進む前に停止する（fail-closed）。判定と挙動:

| 判定 | exit | 挙動 |
|---|---|---|
| GO | 0 | 既存フロー継続 |
| FIX | 10 | 停止（commit/push/PR を止める）|
| OWNER_APPROVAL_REQUIRED | 20 | ゆうさん承認待ちで停止 |
| STOP | 30 | 即停止 |
| INTERNAL_ERROR | 40 | STOP 扱い（fail-closed）|

承認は `YU_OWNER_APPROVED=true`（1回限り・非永続）または `--owner-approved`。
HIGH は承認があっても自動 Merge しない。CRITICAL は承認があっても STOP。

---

## 判定ルール

| 判定 | 条件 |
|---|---|
| **GO** | 12観点クリア + スコア S/A/B |
| **FIX** | 問題あり / スコア C/D / REPORT未更新 |
| **STOP** | Secret混入 / 本番影響 / 既存破壊 / FIX_ATTEMPT>3 |

---

## FIX_ATTEMPT 管理

- FIX のたびに `data/reports/fix_attempt_pr_<N>.txt` のカウンターを +1
- 3回超えたら自動的に **STOP** に格上げ
- GO 完了後は fix_attempt ファイルを自動削除

---

## 実行コマンド

```bash
bash scripts/agent/pr_auto_flow.sh <PR番号>
```

---

## 禁止事項（このコマンドは実行しない）

- 実投稿・自動送信
- Scheduler の変更・ON化
- 本番 Cloud Run デプロイ
- 本番 Google Sheets 直接変更
- `.env.local` の参照

---

## 参照

- `AGENTS.md` — 12観点・GO/FIX/STOP の詳細基準
- `CLAUDE.md` — Claude Code 司令塔ルール
- `docs/AUTO_PR_FLOW.md` — PR フロー全体設計
- `scripts/agent/pr_auto_flow.sh` — 実行スクリプト
- `scripts/agent/safe_auto_merge_pr.sh` — Safe Merge Gate
