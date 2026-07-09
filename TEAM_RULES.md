# TEAM_RULES.md — チーム共通ルール

対象：Claude Code（司令塔）/ Codex（実装部隊）/ 人間レビュアー（ゆうさん）

---

## 作業フロー（標準自動受け渡し）

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
  │
  ├─ GO → Safe Merge Gate
  │        ├─ 低リスク → 自動 Merge → main pull → 完了報告
  │        └─ 高リスク → Merge前停止 → 人間承認待ち
  │
  ├─ FIX → Claude Code 自動修正 → commit → push → 再レビュー
  │         最大2回。3回目 FIX → 停止・人間確認
  │
  └─ STOP → 即停止・Merge禁止・理由報告・人間承認待ち
  ▼
人間（ゆうさん）
     高リスクPR・STOP案件のみ最終承認 → main にマージ
```

### PR リスク区分

**低リスク（自動 Merge 可）**
- 変更ファイル: `docs/**` / `obsidian/**` / `data/revenue_portfolio/**` / `data/analytics/**` / `README.md` / `TASK.md` / `REPORT.md`
- 条件: Codexレビュー GO・Safe Merge Gate GO・.env変更なし・APIキー/Token/Secretなし・自動投稿/DM/リプ/deploy/Scheduler変更なし

**高リスク（Merge前停止・人間承認待ち）**
- `scripts/**` / `agents/**` / `config/**` / `apps/**` / `core/**` / `.env` / `.env.local`
- Cloud Run / Scheduler / API接続 / OAuth / LINE送信 / Gmail送信 / SNS投稿 / 自動DM・自動リプ
- Google Workspace本番書き込み / 顧客データ / 決済 / 商品マッチ先AIの再開

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
