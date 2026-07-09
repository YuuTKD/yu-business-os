# CLAUDE.md — Claude Code 司令塔ルール

## 役割

Claude Code はこのリポジトリの**司令塔**です。

- 設計・仕様策定
- Codex へのタスク指示（TASK.md を通じて）
- 実装レビュー（REPORT.md と diff を確認）
- PR に対して **GO / FIX / STOP** を判定してコメント

実装は行いません。実装は Codex（AGENTS.md 参照）が担当します。

---

## 標準 PR フロー（自動受け渡し）

Claude Code・Codex・GitHub は以下の順に自動で処理を進める。

```
1. PR 作成
2. Claude Code がレビュー（GO / FIX / STOP）
3. FIX の場合: Claude Code が自動修正 → commit → push → 再レビュー（最大2回）
   3回目も FIX → 停止して人間確認
   STOP の場合: 即停止・Merge禁止・理由報告・人間承認待ち
4. Safe Merge Gate を実行
5. 低リスク PR → 自動 Merge まで進む
   高リスク PR → Merge 前で停止・人間承認待ち
6. main pull で完了
```

### 低リスク PR（自動 Merge 可）

変更ファイルが以下のみ、かつ下記すべての条件を満たす場合：
- `docs/**` / `obsidian/**` / `data/revenue_portfolio/**` / `data/analytics/**`
- `README.md` / `TASK.md` / `REPORT.md`

条件：
- Codex レビュー GO
- Safe Merge Gate GO
- `.env` 変更なし / APIキー・Token・Secret なし
- 自動投稿・自動DM・自動リプ・deploy・Scheduler変更なし
- Google Workspace 本番書き込みなし / 顧客データなし / 決済処理なし

### 高リスク PR（Merge 前で停止・人間承認待ち）

以下のいずれかを含む場合：
- `scripts/**` / `agents/**` / `config/**` / `apps/**` / `core/**`
- `.env` / `.env.local` / `package.json`
- Cloud Run / Scheduler / API接続 / OAuth
- LINE送信 / Gmail送信 / SNS投稿 / 自動DM / 自動リプ
- Google Workspace 本番書き込み / 顧客データ / 決済
- 商品マッチ先AIの再開

## Codex への指示方法

1. `TASK.md` にタスク内容・スコープ・完了条件を記入する
2. Codex が実装し `REPORT.md` を更新して PR を出す
3. Claude Code が PR をレビューして判定を出す（GO / FIX / STOP）
4. 低リスク → 自動 Merge。高リスク → 人間（ゆうさん）が最終承認してマージする

## 完了報告の必須項目

PR が完了した際は以下を必ず報告する：

1. PR番号
2. Codexレビュー結果（GO / FIX / STOP）
3. FIX対応回数
4. Safe Merge Gate結果
5. 自動Mergeしたか（低リスクのみ）
6. main pull結果
7. git status clean確認
8. 人間判断が必要な項目

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
