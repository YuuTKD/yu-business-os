# SOP — PLAUD 文字起こしファイル → GCS Knowledge OS（10_PLAUD）

**現行方式＝ファイル添付方式**（2026-07-19〜）。URL/スクレイピング方式は運用中止し
`archive/plaud_url_importer/` へ退避（削除せず保管）。追加レイヤー・既存無変更。

## ゆうさんの操作は2つだけ
1. PLAUD で文字起こしファイルをダウンロード（.txt/.md/.docx/.pdf/.csv/.rtf/.json）。
2. Claude Code へ添付し「このファイルを Obsidian に保存して」と指示。
   （ターミナル: `bash scripts/plaud/import_plaud_file.sh "/path/to/file" "事業名(任意)"`）

Claude は Skill `plaud-file-import` で plan→apply→sync→保存先報告を自動実行。

## 対応形式
| 形式 | 抽出 | 備考 |
|---|---|---|
| .txt / .md | UTF-8（cp932 フォールバック） | 追加依存なし |
| .csv | Markdown 表へ変換 | 追加依存なし |
| .json | 整形テキスト | 追加依存なし |
| .docx | python-docx | 未導入なら該当形式のみ STOP |
| .pdf | pypdf（テキスト埋込のみ・**OCRなし**） | 画像PDF は STOP |
| .rtf | striprtf | 未導入なら STOP |

## 保存先（GCS 正本・`10_PLAUD/`）
`00_Raw_Transcripts/`（原文・無改変・secret redact 済）/ `01_Processed/`（要約スケルトン・
PII マスク）/ `02_By_Business/<事業>/` / `09_Processing_Logs/` / `INDEX.md`（自動更新）。
ファイル名 `YYYY-MM-DD_タイトル_<sha6>.md`（不可記号除去・日本語可・**タイトルは secret/PII マスク**）。

## Obsidian で自由に見る
`INDEX.md`（最新20 + 事業別/種類別/月別ナビ）＋各ファイルのタグ（`#plaud #meeting #biz-catering #decision` 等）＋frontmatter で、全文/タイトル/タグ/事業別/月別/最新順/決定・タスク・思想候補だけの閲覧・内部リンク・バックリンクが可能。

## 前提（無いとき STOP して報告）
- `gcloud auth login` 済（GCS 書込・同期。非対話環境では不可＝オーナー実施）。
- .docx/.pdf/.rtf は各ライブラリ（txt/md/csv/json は不要）。

## 手順
```bash
cd ~/yu-business-os
python3 scripts/plaud/import_plaud_file.py --file "<PATH>" --mode plan   # 確認（書込なし）
bash scripts/plaud/import_plaud_file.sh "<PATH>" "<事業名(任意)>"          # 取込＋同期
gcloud storage ls gs://tree-beauty-blog-images/knowledge-os/10_PLAUD/00_Raw_Transcripts/
```

## 安全 / プライバシー
- secret → `REDACTED`（除外不能な重大secret＝private key 等は**保存前STOP**）。secret値・原文全文・PIIはログに出さない（ログはパス/件数/sha8のみ）。
- **raw は原文無改変**（secret のみ redact）。**processed は要約を PII マスク**、原文は含めない。事業/タイトルにも PII/secret を出さない。
- 個人Vault/Google Drive へ書込まない（指定 STOP）。GCS のみ・削除なし・**同一 SHA-256 は再保存しない（冪等）**。
- 思想は `observed` のみ・**1発言を confirmed に自動昇格しない**・`YUYA_DECISION_MODEL.md` 自動更新なし。
- 外部送信/SNS投稿/営業/見積/デプロイ **なし**。

## 事業分類
`--business` 指定を最優先。無指定は本文から自動（TACHINOMIYA/Catering/Tree Beauty/コンサル/AIネットビジネス/琉球火鍋/東町/投資/パーソナル/全事業）。確信なければ **未分類**（推測しない）。

## 障害時
| 症状 | 対応 |
|---|---|
| GCS アクセス不可 | `gcloud auth login` 後に再実行（冪等） |
| .docx/.pdf/.rtf で STOP | 対応ライブラリを `pip install`（python-docx / pypdf / striprtf） |
| 画像PDF | テキスト埋込PDFを使用（OCR は行わない） |
| 同期のみ失敗 | GCS 保存は成功。次回 `knowledge-sync` で反映（WARNING） |
| secret STOP | 生成元に重大 secret。`logs/plaud_file_import.log`（値は出ない）で件数確認→除去→再実行 |

## 既存システムへの影響
なし（既存ファイル・同期・LaunchAgent・Vault・Cloud Run・Scheduler・SNS 無変更）。URL importer は `archive/` に保管（参照用・非運用）。
