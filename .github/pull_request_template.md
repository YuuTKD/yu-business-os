## 変更概要

<!-- 何を・なぜ変更したか1〜3行で記入 -->

関連タスク: TASK-

---

## チェックリスト

### 実装スコープ
- [ ] TASK.md に記載されたスコープ内の変更のみ
- [ ] REPORT.md を更新した
- [ ] `git add .` を使っていない（個別ファイル指定）

### YU HOLDINGS OS 整合
- [ ] YU HOLDINGS 全体 OS（AI-EOS）に整合している
- [ ] 既存 Agents / Skills / Knowledge を削除・上書きしていない
- [ ] Cash-First 原則に反していない

### 安全確認
- [ ] APIキー・Secret・パスワードの直書きなし
- [ ] `.env.local` を変更していない
- [ ] 本番 Cloud Run へのデプロイを含まない
- [ ] 本番 Google Sheets の直接変更を含まない
- [ ] 自動送信（LINE・メール・SNS）を含まない

---

## Claude Code レビュー判定

<!-- Claude Code が記入する -->

**判定：** GO / FIX / STOP

**コメント：**
