# SOP — PLAUD 共有URL → GCS Knowledge OS（10_PLAUD）

PLAUD の公開共有URLから文字起こし・要約・タイトル・録音日時を取得し、GCS 正本へ
保存 → 既存 `knowledge-sync` で Obsidian へ反映する。**追加レイヤー・既存無変更**。

## 使い方（今後）
```bash
bash scripts/plaud/import_plaud_url.sh "PLAUD共有URL"
```
成功時: GCS 保存パス / 抽出タスク数 / 思想候補数 / Yes-No 確認数 を表示。

## 前提（オーナーが一度だけ／各回）
1. `gcloud auth login`（GCS 書込・同期に必須。非対話環境では実行不可）。
2. 文字起こし本文取得は共有ページが JS SPA のため **ブラウザレンダリング**が必要:
   `pip install playwright && playwright install chromium`（owner 環境）。
   未導入時は `--apply` が「Playwright が必要」で **STOP**（推測取得はしない）。

## 手順
```bash
cd ~/yu-business-os
# 1) plan（URL検証・recording_id・保存先のみ／本文取得なし・書込なし）
PLAUD_URL="…共有URL…" python3 scripts/plaud/import_plaud_url.py --mode plan
# 2) 実取込＋同期（GCS 保存 → Obsidian 反映）
bash scripts/plaud/import_plaud_url.sh "…共有URL…"
# 3) 確認
gcloud storage ls gs://tree-beauty-blog-images/knowledge-os/10_PLAUD/00_Raw_Transcripts/
```

## 保存先（GCS 正本・`10_PLAUD/`）
- 原文: `00_Raw_Transcripts/YYYY/MM/YYYY-MM-DD_<recording_id>.md`（文字起こし無改変・secret redact 済）
- 処理済: `01_Processed/…`（分析スケルトン・要約は PII マスク・原文は含めない）
- 思想候補/タスク候補: `03_Philosophy_Candidates/` `04_Task_Candidates/`
- 日次要約: `08_Daily_Summaries/…_PLAUD_SUMMARY.md`
- 処理ログ: `09_Processing_Logs/…json`

## セキュリティ / プライバシー
- 共有URLの**トークン(::以降)は保存・表示・ログ出力しない**（recording_id=pre-'::' のみ保持）。URLは Git/ファイルへ書かない（引数/環境変数のみ）。
- secret 検出 → `REDACTED`、除外不能 → **保存 STOP**。
- PII（メール/電話/郵便番号 等）は**件数フラグ**。原文(raw)は無改変保存、processed の要約は PII マスク、原文は processed に含めない。
- 思想は `observed` のみ。**1発言を confirmed に自動昇格しない**。`YUYA_DECISION_MODEL.md` は自動更新しない（確定は Yes 後・別Phase）。
- 個人Vault/Google Drive へ書込まない（指定すると STOP）。GCS のみ。削除しない。同一 recording_id は重複保存しない（冪等更新）。
- 外部投稿/メール送信/営業連絡/自動見積/自動デプロイ **なし**。Zapier/n8n/Cloud Run/Scheduler 非接続。

## 障害時
| 症状 | 対応 |
|---|---|
| GCS アクセス不可 | `gcloud auth login` 後に再実行（冪等） |
| Playwright 未導入 | `pip install playwright && playwright install chromium` |
| ログイン必須ページ | STOP（非公開データは取得しない）。共有設定を公開に |
| 同期のみ失敗 | GCS 保存は成功。次回 `knowledge-sync` で反映（WARNING） |
| secret STOP | 生成元に secret 混入。`logs/plaud_import.log`（値は出ない）で件数確認→除去→再実行 |

## 既存システムへの影響
なし（既存ファイル・同期・LaunchAgent・Vault・Cloud Run・Scheduler・SNS 無変更）。
