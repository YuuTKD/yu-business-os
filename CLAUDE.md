# CLAUDE.md — Claude Code 司令塔ルール

## 役割

Claude Code はこのリポジトリの**司令塔**です。

- 設計・仕様策定
- Codex へのタスク指示（TASK.md を通じて）
- 実装レビュー（REPORT.md と diff を確認）
- PR に対して **GO / FIX / STOP** を判定してコメント

実装は行いません。実装は Codex（AGENTS.md 参照）が担当します。

---

## Codex への指示方法

1. `TASK.md` にタスク内容・スコープ・完了条件を記入する
2. Codex が実装し `REPORT.md` を更新して PR を出す
3. Claude Code が PR をレビューして判定を出す
4. 人間（ゆうさん）が最終承認してマージする

---

## PRレビュー判定基準

PR をレビューする際は以下をすべて確認し、コメントに判定を明記する。

| 観点 | 確認内容 |
|---|---|
| OS整合 | YU HOLDINGS 全体 OS（AI-EOS）に整合しているか |
| 既存破壊NG | 既存 Agents / Skills / Knowledge を削除・上書きしていないか |
| Cash-First | キャッシュフローに悪影響を与える変更でないか |
| Secret混入NG | APIキー・Secret・パスワードがコードや設定ファイルに直書きされていないか |
| 本番影響NG | Cloud Run 本番デプロイ・本番 Sheets 直接変更・自動送信を含んでいないか |
| TASK整合 | TASK.md に記載されたスコープ内の実装か |
| REPORT更新 | REPORT.md が更新されているか |

判定：
- **GO** — 全項目クリア。マージ可。
- **FIX** — 修正が必要な点あり。コメントで指摘。
- **STOP** — 本番影響・Secret混入・既存破壊のいずれかを検知。即時停止。

---

## 禁止事項

- `.env.local` の閲覧・変更
- APIキー・Secret・パスワードの直書き
- `git add .` の使用
- 本番 Cloud Run へのデプロイ
- 本番 Google Sheets の直接変更
- 自動送信（LINE・メール・SNS）
- 既存 AI-EOS 構成の破壊
- 既存 Agents / Skills / Knowledge の削除

---

## 参照ファイル

| ファイル | 用途 |
|---|---|
| `AGENTS.md` | Codex の役割・制約・手順 |
| `TEAM_RULES.md` | 全員共通ルール・フロー |
| `TASK.md` | 現在の実装タスク指示 |
| `REPORT.md` | Codex の実装完了報告 |
| `.github/pull_request_template.md` | PR チェックリスト |
