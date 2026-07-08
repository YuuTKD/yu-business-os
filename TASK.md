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
## TASK-002（タスクタイトル）
ステータス: TODO
概要:
完了条件:
スコープ:
```


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
