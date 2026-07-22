# SOP — PLAUD 文字起こしファイル → Obsidian 10_PLAUD（直接保存）

**現行方式＝ファイル添付・Obsidian直接保存**（2026-07-19〜）。GCS/URL/スクレイピング/
Playwright は使わない。旧 URL 方式は `archive/plaud_url_importer/` へ退避（非運用）。

## ゆうさんの操作は2つだけ
1. PLAUD で文字起こしファイルをダウンロード（.txt/.md/.docx/.pdf/.csv/.rtf/.json）。
2. Claude Code へ添付し「このファイルを Obsidian に保存して」。
   （ターミナル: `bash scripts/plaud/import_plaud_file.sh "/絶対パス" "事業名(任意)"`）

Claude は Skill `plaud-file-to-obsidian` で plan→apply→保存先報告を自動実行。

## 保存先（Obsidian Vault のみ・認証不要）
`~/Documents/YU_HOLDINGS_Knowledge_OS/10_PLAUD/`
```
01_文字起こし原文/  原文（無改変・secret redact）
02_整理済み/        要約スケルトン（PIIマスク・原文は原文ページへ内部リンク）
03_事業別/<事業>.md  ← 内部リンクを蓄積
04_決定事項/ 05_タスク/ 06_思想候補/ 07_会議議事録/  ← 内容に応じ内部リンク
08_月別/YYYY-MM.md   09_取込ログ/*.json   INDEX.md（最新30+事業別+決定+タスク+思想+月別）
```
ファイル名 `YYYY-MM-DD_タイトル_SHA先頭8.md`（不可記号除去・日本語可・secret/PIIマスク）。
**分類はコピーせず内部リンク**で行う。

## 対応形式
txt/md/csv/json は追加依存なし。docx→python-docx、pdf→pypdf（**OCRなし**・画像PDF STOP）、
rtf→striprtf（未導入なら該当形式のみ STOP）。空/破損/未対応は STOP。

## 手順
```bash
cd ~/yu-business-os
python3 scripts/plaud/import_plaud_file.py --file "<絶対PATH>" --mode plan   # 確認（書込なし）
bash scripts/plaud/import_plaud_file.sh "<絶対PATH>" "<事業名(任意)>"          # Obsidian へ保存
ls ~/Documents/YU_HOLDINGS_Knowledge_OS/10_PLAUD/01_文字起こし原文/
```

## Obsidian でできること
全文/タイトル/人名/事業名/タグ検索、月別・最新順・決定/タスク/思想候補だけ閲覧、内部リンク移動・
バックリンク。タグ例 `#plaud #transcript #meeting #decision #task #philosophy-candidate #biz-catering`。

## 安全 / プライバシー
- secret→`REDACTED`、除外不能な重大secret(private key等)→**保存前STOP**。secret値/原文全文/PIIは**ログに出さない**（パス/件数/sha8のみ）。
- **raw は原文無改変**、**processed は原文非包含・PIIマスク**、**タイトル/ファイル名も secret+PII マスク**。
- 個人情報は Vault 内に限定。**外部送信/SNS/営業/見積/学習用公開へ自動転用しない**。
- **同一SHA-256は再保存しない**（`SKIPPED_DUPLICATE`）。過去ファイルを削除・上書きしない。
- Google Drive/Dropbox への保存は STOP。思想は `observed` のみ・confirmed 自動昇格なし。
- 事業は指定優先、不明は「未分類」で保存（止めない・推測しない）。

## 障害時
| 症状 | 対応 |
|---|---|
| .docx/.pdf/.rtf で STOP | `pip install python-docx / pypdf / striprtf` |
| 画像PDF | テキスト埋込PDFを使用（OCRなし） |
| 空/破損/未対応 | STOP。ファイルを確認 |
| secret STOP | 重大secret混入。`logs/plaud_file_import.log`（値は出ない）で件数確認→除去→再実行 |

## 既存システムへの影響
なし（既存ファイル・同期・LaunchAgent・Cloud Run・Scheduler・SNS 無変更）。GCS/認証も不要。
URL importer は `archive/` に保管（参照用・非運用）。
