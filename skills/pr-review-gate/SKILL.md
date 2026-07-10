# SKILL: PR Review Gate（自動PRフロー管理）

## 概要

Claude Code がPRを受け取ったとき、自動でレビュー・FIX・Safe Merge Gate・Mergeまで進める標準フロー。
低リスクは自動Merge、高リスクはMerge前停止・人間承認待ち。

## 発動条件

- PR が作成されたとき
- ゆうさんから「PRをレビューして」と指示されたとき
- Codex が REPORT.md を更新して PR を出したとき

---

## フロー

```
PR 受信
  ↓
1. リスク区分を判定（下記参照）
  ↓
2. Claude Code レビュー（GO / FIX / STOP）
  ↓
  ├─ STOP → 即停止・Merge禁止・理由報告・人間承認待ち
  │
  ├─ FIX → Claude Code が自動修正 → commit → push → 再レビュー
  │         最大2回まで。3回目FIX → 停止・人間確認
  │
  └─ GO → Safe Merge Gate 実行
            ↓
            ├─ 低リスク → 自動 Merge（gh pr merge <番号> --squash）
            │            → git checkout main → git pull origin main
            │            → 完了報告
            │
            └─ 高リスク → Merge前停止 → 人間承認待ち → 承認後にMerge
```

---

## リスク区分

### 低リスク（自動 Merge 可）

**変更ファイルが以下のみ、かつ全条件を満たす場合：**

対象ファイル：
- `docs/**`
- `obsidian/**`
- `data/revenue_portfolio/**`
- `data/analytics/**`
- `README.md`
- `TASK.md`
- `REPORT.md`

全条件：
- Codex レビュー GO
- Safe Merge Gate GO
- `.env` 変更なし
- APIキー / Token / Secret なし
- 自動投稿・自動DM・自動リプ なし
- deploy なし
- Scheduler 変更なし
- Google Workspace 本番書き込みなし
- 顧客データなし
- 決済処理なし

### 高リスク（Merge 前停止・人間承認待ち）

以下のいずれかを含む場合：

| カテゴリ | 対象 |
|---|---|
| コード | `scripts/**` / `agents/**` / `config/**` / `apps/**` / `core/**` |
| 設定 | `.env` / `.env.local` / `package.json` |
| インフラ | Cloud Run / Scheduler / API接続 / OAuth |
| 送信系 | LINE送信 / Gmail送信 / SNS投稿 / 自動DM / 自動リプ |
| データ | Google Workspace本番書き込み / 顧客データ / 決済 |
| 特別 | 商品マッチ先AIの再開 |

---

## PRレビュー判定基準

| 観点 | 確認内容 |
|---|---|
| OS整合 | YU HOLDINGS 全体 OS（AI-EOS）に整合しているか |
| 既存破壊NG | 既存 Agents / Skills / Knowledge を削除・上書きしていないか |
| Cash-First | キャッシュフローに悪影響を与える変更でないか |
| Secret混入NG | APIキー・Secret・パスワードがコードに直書きされていないか |
| 本番影響NG | Cloud Run 自動デプロイ・本番Sheets直接変更・自動送信を含んでいないか |
| TASK整合 | TASK.md に記載されたスコープ内の実装か |
| REPORT更新 | REPORT.md が更新されているか（docs変更のみの場合は省略可） |

判定：
- **GO** — 全項目クリア
- **FIX** — 修正が必要な点あり（自動修正 → 最大2回）
- **STOP** — 本番影響・Secret混入・既存破壊を検知 → 即停止

---

## FIX 自動修正ルール

1. FIX 内容を保存
2. Claude Code が自動修正
3. commit → push
4. 再レビュー（最大2回まで）
5. 3回目 FIX → 停止して人間確認

---

## 完了報告テンプレート

```
【PR #<番号> merge結果】<merged / 停止中>
【main pull結果】<成功 / 未実施>
【git status】<clean / 差分あり>
【Scheduler OFF確認】<OFF維持 / 変更なし>
【beauty_morning NOT_DEPLOYED確認】<NOT_DEPLOYED維持>
【scripts/acquisition再開なし確認】<再開なし>
【自動投稿していない確認】<していない>
【LINE本番通知していない確認】<していない>
【次に進める作業候補】<候補リスト>
```

---

## 禁止事項（このスキル内で絶対にやらないこと）

- 高リスク PR の自動 Merge
- STOP 判定後の作業続行
- Secret / APIキー / Token の表示
- `git add .` の使用
- 本番 Cloud Run への自動デプロイ
- 自動送信（LINE・メール・SNS）
- beauty_morning の有効化
- scripts/acquisition 取得スクリプトの再開
