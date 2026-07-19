---
name: plaud-file-import
description: PLAUD等の文字起こしファイル（.txt/.md/.docx/.pdf/.csv/.rtf/.json）を添付またはファイルパスで渡され、「このファイルをObsidianに保存して」「PLAUD文字起こしを保存して」「この議事録をKnowledge OSへ入れて」「思想OSに保存して」「この文字起こしを整理して」等と指示されたら、このSkillを使う。ファイルをGCS(10_PLAUD)へ保存し既存sync_knowledge_os.shでObsidian反映する。URL/スクレイピング/Playwrightは使わない。
---

# plaud-file-import（文字起こしファイル → Obsidian）

## 使う場面
ユーザーが文字起こしファイルを添付/パス指定し、Obsidian/Knowledge OS/思想OS への保存を指示したとき。

## 処理手順
1. 添付ファイルまたは指定パスを特定する（複数なら1つずつ）。
2. **plan** を実行して内容と保存先を確認:
   `python3 scripts/plaud/import_plaud_file.py --file "<PATH>" --mode plan [--business "<事業名>"]`
   - 表示: 形式・文字数・SHA-256先頭8・推定タイトル・事業分類・保存予定先。
   - 空ファイル/未対応形式/重大secretはSTOP → 理由を日本語で報告して終了。
3. 問題なければ **apply + sync** を実行:
   `bash scripts/plaud/import_plaud_file.sh "<PATH>" "<事業名(任意)>"`
   - GCS `10_PLAUD/`（raw/processed/by_business/INDEX）へ保存 → 既存同期で Obsidian 反映。
4. Obsidian 側のファイル存在を確認（`~/Documents/YU_HOLDINGS_Knowledge_OS/10_PLAUD/`）。
5. 結果を日本語で報告: 保存先パス・事業分類・タグ・重複有無・secret/PII 件数・確認Yes/No。

## 事業名の指定
ユーザーが事業名を言った場合はそれを優先（--business）。無指定なら本文から自動分類、確信がなければ「未分類」。

## 禁止
- URL取得/スクレイピング/Playwright/PLAUDログイン。
- 個人Vault/Google Drive への直接書込。GCS が正本。
- 原文の改変・削除・過去ファイル削除。同一SHA-256は再保存しない。
- secret値・原文全文・個人情報をログ/報告へ出す。processed側はPIIマスク。
- 外部送信・SNS投稿・営業連絡・見積送付・デプロイ。
- 思想の自動確定（observed のみ・confirmed 昇格は Yes 後）。

## 前提（無いときはSTOPして報告）
- `gcloud auth login` 済（GCS 書込・同期）。
- .docx→python-docx / .pdf→pypdf / .rtf→striprtf が必要（未導入なら該当形式のみSTOP、txt/md/csv/jsonは不要）。

## 成功時の報告テンプレ
「保存しました。事業=<biz> / タイトル=<title> / GCS=<raw path> / Obsidian=10_PLAUD/... / タグ=<tags> / secret <n>件REDACT / PII <flags> / 確認Yes/No <k>件。」
