---
name: plaud-file-to-obsidian
description: 文字起こしファイル（.txt/.md/.docx/.pdf/.csv/.rtf/.json）を添付/パス指定され「このファイルをObsidianに保存して」「この文字起こしを保存して」「この議事録を蓄積して」「このファイルをPLAUDフォルダへ入れて」「この内容をKnowledge OSへ保存して」等と言われたら、このSkillを使う。Obsidian Vault の 10_PLAUD へ直接保存・分類・INDEX更新する。URL/スクレイピング/Playwright/GCS は使わない。
---

# plaud-file-to-obsidian（文字起こしファイル → Obsidian 10_PLAUD 直接保存）

## 使う場面
文字起こしファイルを添付/パス指定され、Obsidian/Knowledge OS/PLAUDフォルダ/思想OS への保存を指示されたとき。通常は追加質問せず自動で進める。

## 実行手順
1. 今回添付されたファイルの絶対パスを取得（複数なら1つずつ）。
2. plan（書込なし・内容と保存先を確認）:
   `python3 scripts/plaud/import_plaud_file.py --file "<絶対PATH>" --mode plan [--business "<事業名>"]`
   - 空/破損/未対応形式/画像PDF/重大secret は STOP → 日本語で理由を報告して終了。
3. 問題なければ apply（Obsidian へ保存）:
   `bash scripts/plaud/import_plaud_file.sh "<絶対PATH>" "<事業名(任意)>"`
4. `~/Documents/YU_HOLDINGS_Knowledge_OS/10_PLAUD/` に保存されたことを確認（INDEX.md も更新される）。
5. 保存場所・事業分類・生成リンク・secret/PII件数を日本語で報告。

## 判断
- 事業名をユーザーが言えば優先。不明でも止めず「未分類」で保存。
- 追加質問は原則しない（自動判定）。

## 禁止
- URL取得/スクレイピング/Playwright/GCS 経由。
- Google Drive/Dropbox への保存（STOP）。原文の改変・削除・過去ファイル上書き。同一SHA-256の再保存。
- secret値・原文全文・個人情報をログ/報告へ出す。重大secretは保存前STOP。
- 個人情報の外部送信・SNS投稿・営業/見積・公開データ転用。
- 思想の自動確定（observed のみ）。

## 保存構成（10_PLAUD/）
01_文字起こし原文（原文無改変）/ 02_整理済み（要約・PIIマスク）/ 03_事業別 / 04_決定事項 /
05_タスク / 06_思想候補 / 07_会議議事録 / 08_月別 / 09_取込ログ / INDEX.md。
分類先には**内部リンク**を追加（コピーしない）。ファイル名 `YYYY-MM-DD_タイトル_SHA先頭8.md`。

## 前提（無いときは該当形式のみSTOP）
.docx→python-docx / .pdf→pypdf / .rtf→striprtf（txt/md/csv/json は不要）。GCS/認証は不要（ローカルVault保存）。
