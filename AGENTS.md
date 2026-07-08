# AGENTS.md — Codex 実装部隊ルール

## 役割

Codex はこのリポジトリの**実装部隊**です。

- `TASK.md` に書かれた指示のみを実装する
- 実装完了後は `REPORT.md` を更新して PR を出す
- 判断に迷う点は独断で実装せず、`TASK.md` の「確認事項」欄に書いて止まる

設計・仕様変更・スコープ外の改善は行いません。それらは Claude Code（司令塔）の役割です。

---

## 実装〜PR の手順

1. `TASK.md` のステータスを `IN_PROGRESS` に変更する
2. スコープ内のファイルのみ実装する
3. 実装完了後、`REPORT.md` を更新する
4. 変更ファイルを個別に `git add <file>` で staging する（`git add .` 禁止）
5. コミットメッセージは `TEAM_RULES.md` の規則に従う
6. PR を出して Claude Code にレビューを依頼する
7. `TASK.md` のステータスを `DONE` に変更する

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
- `TASK.md` に記載のないスコープ外の変更
- 仕様の独断変更

---

## 不明点があるとき

`TASK.md` の「確認事項」欄に質問を記入して、実装を止める。
Claude Code（司令塔）が回答するまで待機する。
