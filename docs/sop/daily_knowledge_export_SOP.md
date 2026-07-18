# SOP — YU Knowledge OS 日次自動保存（Daily Knowledge Export）

追加レイヤー。既存 Knowledge OS / 同期 / 個人 Vault を変更しない。GCS が正本。

## 何をするか
毎日 23:50、3プロジェクト（yu-business-os / ai-net-business-sns-os /
local-business-ai-content-os）の当日情報を **read-only** で収集し、Markdown を
GCS `gs://tree-beauty-blog-images/knowledge-os/` へ保存する。既存の
`knowledge-sync`（3時間毎 GCS→Obsidian）で翌朝までに Vault へ反映される。

## 保存先（GCS のみ・正本）
- 日次: `05_Reports/Daily/YYYY/MM/YYYY-MM-DD_DAILY_REPORT.md`
- 意思決定: `04_Decisions/YYYY/MM/YYYY-MM-DD_DECISIONS.md`
- 自動化: `08_Automation_System/YYYY/MM/YYYY-MM-DD_AUTOMATION_LOG.md`
- Dashboard: `00_Dashboard/LATEST_DAILY_STATUS.md`（毎日上書き更新）
- 日付別ファイルは上書き保存（同日再実行=内容更新）。**過去日付は削除しない**。

## 導入手順（オーナーが一度だけ実施）
```bash
cd ~/yu-business-os
# 1) 変更予定の確認（書き込みなし）
python3 scripts/knowledge/export_daily_knowledge.py --mode plan

# 2) GCS 認証（期限切れなら）
gcloud auth login

# 3) 手動で 1 回 export（GCS へ実書き込み）
bash scripts/knowledge/run_daily_export.sh

# 4) LaunchAgent を導入（23:50 自動実行）
cp config/launchagents/com.yuholdings.daily-knowledge-export.plist \
   ~/Library/LaunchAgents/
launchctl load  ~/Library/LaunchAgents/com.yuholdings.daily-knowledge-export.plist

# 5) 確認
launchctl list | grep daily-knowledge-export
gcloud storage ls gs://tree-beauty-blog-images/knowledge-os/00_Dashboard/
```
> Claude Code はこの手順を実行しません（GCS 書き込み・LaunchAgent 導入はオーナー操作）。

## 日常運用
- 何もしなくてよい。翌朝 Obsidian の `00_Dashboard/LATEST_DAILY_STATUS.md` を開けば前日状況を確認できる。
- 判断項目（明日の最優先 / ゆうさんの Yes/No / 経営判断）は**自動では埋めない**（`記録なし`）。必要なら人手で追記。

## Secret 対策
- 保存前に全文を secret スキャンし、検出値は `REDACTED` へ置換。件数のみ記録。
- 置換後も secret が残る場合は **アップロード STOP**（保存しない）。
- token / API key / credentials / .env 値 / Authorization ヘッダは保存しない。

## 障害時の復旧
| 症状 | 対応 |
|---|---|
| export 失敗（GCS 保存できず） | `logs/daily_knowledge_export.log` を確認。`gcloud auth login` 後 `bash scripts/knowledge/run_daily_export.sh` を手動再実行（冪等・当日ファイルを更新するだけ） |
| 同期だけ失敗（WARNING） | GCS 保存は成功済み。次回 `knowledge-sync`（3時間毎）で自動反映。急ぐ場合 `SKIP_SLEEP=1 scripts/sync_knowledge_os.sh` |
| LaunchAgent が動かない | `launchctl list \| grep daily-knowledge-export` / `~/Library/LaunchAgents/...err.log` 確認。再導入は unload→load |
| 23:50 を逃した（スリープ） | 次回起動時に launchd が 1 回実行。手動なら run スクリプトを実行（同日は上書きのみ） |
| Secret STOP が出た | 該当ドキュメントの生成元データに secret が混入。`logs` で件数確認（値は出ない）。原因除去後に再実行 |

## ロールバック
- LaunchAgent を外す: `launchctl unload ~/Library/LaunchAgents/com.yuholdings.daily-knowledge-export.plist` → ファイル削除。
- 本レイヤーは追加のみ。削除しても既存 Knowledge OS / 同期に影響しない。GCS 既存ファイルは残す。

## 既存システムへの影響
なし。既存ファイル・同期スクリプト・LaunchAgent・個人 Vault・Cloud Run・Scheduler・
SNS 自動投稿は無変更。rsync は `-d` なしのまま（ローカル削除なし）。Google Drive 不使用。

サンプル: `docs/sop/sample_DAILY_REPORT.md` / `docs/sop/sample_LATEST_DAILY_STATUS.md`。
