# TEAM_RULES.md — チーム共通ルール

対象：Claude Code（司令塔）/ Codex（実装部隊）/ 人間レビュアー（ゆうさん）

---

## 作業フロー

```
人間（ゆうさん）
  │  TASK.md にタスクを記入・承認
  ▼
Codex（実装部隊）
  │  TASK.md の指示のみを実装
  │  REPORT.md を更新
  │  PR を作成
  ▼
Claude Code（司令塔）
  │  PR をレビュー（GO / FIX / STOP）
  ▼
人間（ゆうさん）
     最終承認 → main にマージ
```

---

## 全員共通の禁止事項

1. `.env.local` の閲覧・変更
2. APIキー・Secret・パスワードのコード直書き
3. `git add .` の使用（個別ファイル指定を徹底する）
4. 本番 Cloud Run へのデプロイ
5. 本番 Google Sheets の直接変更
6. 自動送信（LINE・メール・SNS）
7. 既存 AI-EOS 構成の破壊
8. 既存 Agents / Skills / Knowledge の削除
9. main ブランチへの直接 push

---

## ブランチ命名規則

```
feature/codex-<task-id>-<短い説明>
例: feature/codex-001-add-workflow-files
```

---

## コミットメッセージ規則

```
<type>: <内容>（日本語可）

type:
  feat    — 新機能追加
  fix     — バグ修正
  refactor — リファクタリング
  docs    — ドキュメント変更
  chore   — ビルド・設定変更
```

---

## Secret / APIキー管理方針

- すべての Secret は Google Secret Manager または `.env.local` で管理する
- コードに直書きした場合は即時 STOP・該当コミットをリセット
- `.env.local` は `.gitignore` に含まれていることを必ず確認する

---

## エスカレーション

| 状況 | 対応 |
|---|---|
| Codex が仕様に迷う | TASK.md 確認事項欄に記入して止まる |
| Claude Code が STOP 判定 | 即時作業停止・人間（ゆうさん）に報告 |
| Secret 混入を発見 | 即時 STOP・コミット取り消し・人間に報告 |
