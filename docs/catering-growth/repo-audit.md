# リポジトリ監査レポート — TREE's Catering 広告費ゼロ集客OS

対象仕様書: `docs/catering-growth/YU_BusinessOS_TREEs_Catering_ZeroCost_Growth_Sprint.md`
監査日: 2026-07-27
監査者: Claude Code（司令塔）
**本レポートはコード変更を一切行っていない読み取り専用監査である。**

---

## 0. 結論サマリー（先に読む3点）

1. **新規アプリは不要。既存の TREE's Catering ワークブック（`CATERING_SPREADSHEET_ID`）に、CRM・見積・受注・売上・粗利のファネルが14シートで既に存在する。** 作るべきものは「新システム」ではなく「既存ファネルに流入元IDを通す配管」である。

2. **最大のギャップは UTM ではなく「結合キーの欠落」。** `02_問い合わせ` → `03_見積` → `04_受注管理` → `07_利益管理` の間に共通IDが無く、現状**問い合わせと粗利を機械的に突き合わせられない**。仕様書の完了定義「見積・受注・売上・粗利まで追跡できる」は、ここを直さない限り達成不能。

3. **この OS に Web UI は存在しない。** 仕様書 §6「画面要件」は、そのままでは実装先が無い。UI は実質 **Google Sheets のタブ + LINE通知 + Apps Script の CEOダッシュボード** の3つ。画面はシートタブ設計として実装するのが唯一の最小変更ルートである（後述 §3-E）。

---

## 1. 調査結果（8観点）

### 1.1 CLAUDE.md と README

| 項目 | 結果 |
|---|---|
| `CLAUDE.md` | あり。Claude Code は**司令塔＝設計・レビュー専任、実装は Codex**。PRフロー・低/高リスク分類・禁止事項を規定。 |
| `AGENTS.md` / `TEAM_RULES.md` / `TASK.md` / `REPORT.md` | すべてルートに存在。Codex への指示は `TASK.md` 経由が正規ルート。 |
| **README.md** | **ルートに存在しない。** 代替は `docs/SYSTEM_INVENTORY.md` と `docs/YU_BUSINESS_OS_2_ARCHITECTURE.md`。 |
| 設計正典 | `docs/YU_BUSINESS_OS_2_DATA_CONTRACTS.md`（承認ポリシー・staff通知は常にオーナー承認必須）、`docs/YU_BUSINESS_OS_2_ARCHITECTURE.md` |

**規約上の重要制約（CLAUDE.md より）**
- `core/**` `scripts/**` `configs/**` `agents/**` への変更は **高リスクPR → マージ前に停止・人間承認待ち**。
- `docs/**` のみの変更は **低リスクPR → 自動マージ可**。
- 禁止: 本番 Sheets の直接変更 / 自動送信（LINE・メール・SNS）/ Secret 直書き / `git add .`。

**追加の恒久ルール（プロジェクト記憶）**
- **今後のシステムで OpenAI API を使わない**（無料構成のみ）。既存の `core/catering_content.py` 等は GPT を使うが、**今回追加するモジュールは固定テンプレート＋変数差し込みのみ**とする。仕様書 §8「AI APIを使った大量文章生成」を実装しない、と整合。

### 1.2 使用言語・フレームワーク・パッケージ管理

| 項目 | 結果 | 根拠 |
|---|---|---|
| 言語 | **Python 3.11**（168 .py ファイル） | `Dockerfile:1` `FROM python:3.11-slim` |
| Web | **Flask + gunicorn**（Cloud Run） | `Dockerfile:14`, `core/entrypoint.py` |
| 補助 | FastAPI（`simulator/` — 社内デモ専用、本番外） | `simulator/server.py` |
| データアクセス | **gspread**（Google Sheets API） | `requirements.txt` |
| 依存管理 | `requirements.txt`（正本・手書き）→ `requirements.lock`（`pip freeze` 固定、CIは `pip install --no-deps -r requirements.lock`） | `requirements.lock:1-12`, `.github/workflows/pr-validation.yml:53` |
| Node/JS | `agents/shared/` に17ファイル、`apps_script/` に Apps Script。**package.json は無し**（npm 管理外） | — |

→ **新規課金ゼロの条件は満たせる。** gspread / Google Sheets API / Drive は既存の無料枠内。追加の有料SaaSは不要。

### 1.3 ルーティングと画面構成

| 項目 | 結果 |
|---|---|
| HTTPルート | **`core/entrypoint.py` に 165 ルート**（2,521行の単一 Flask ファイル） |
| 起動 | `gunicorn core.entrypoint:app`、`BUSINESS_NAME` env で事業を切替（catering なら `trees-catering-ai` サービス） |
| 呼び出し元 | ほぼ全て **Cloud Scheduler の HTTP POST**。人が叩く画面ではない。 |
| LINE Webhook | `/line-task-webhook`（`core/entrypoint.py:665`）— タスク完了返信・売上スクショ受信 |
| MCPサーバー | `core/mcp_server.py` — JSON-RPC、**read-only 8ツール**（Claude カスタムコネクタ用） |
| Apps Script | `apps_script/ceo_dashboard_v2.js` — 6事業横断ランキング／資産進捗／シナジー／アラートログ。週1(月8:00)＋日次(9:00)トリガー |
| **Web UI** | **存在しない。** |

**既存 catering ルート**: `/catering-weekly` `/catering-monthly` `/catering-setup` `/catering-content` `/catering-sales-setup` `/catering-sales-generate-test` `/catering-sales-daily` `/catering-sales-followup` `/catering-sales-status`

→ 追加ルートは `core/entrypoint.py` に `@app.route` を足すだけで既存規約に乗る。**ただし同ファイルは既に2,521行あり、ロジックは `core/<module>.py` に置き `entrypoint` は薄い委譲のみ**という既存パターンを厳守する。

### 1.4 DB・ORM・マイグレーション

**RDBMS は存在しない。ORM も無い。マイグレーション基盤も無い。**

永続層は **Google Sheets のみ**（＋ GCS の Markdown アーカイブ）。

事業別ワークブック（`configs/business_registry.py`）:

| 事業 | env 名（ID実値は本文書に転記しない） |
|---|---|
| **catering** | `CATERING_SPREADSHEET_ID` |
| tachinomiya | `TACHINOMIYA_SPREADSHEET_ID` |
| beauty / hinabe / pasta / z1 | 各 `*_SPREADSHEET_ID` |

> ID の実値は `configs/business_registry.py` に既に追跡されているが、`configs/businesses/registry.yaml:10-15`
> のポリシーは「spreadsheet-id の値を持たず env 名のみ」を要求している（移行途上の既知の不整合）。
> **新しい文書・コードに実値を転記しない。**

**TREE's Catering ワークブックの既存14シート**（`core/catering_setup.py`）:

| シート | 主要列 | 集客OSでの役割 |
|---|---|---|
| `01_KPI` | 問い合わせ/見積/受注/受注率/売上/利益/粗利率（数式集計） | **KPI土台として再利用可** |
| `02_問い合わせ` | 問い合わせ日, 企業名, 担当者名, 電話番号, メールアドレス, 問い合わせ内容, 案件詳細, 希望日程, 人数規模, 予算感, 対応状況, 次のアクション, 担当スタッフ, メモ, **経路** | **流入元の受け皿。`経路` 列が既にある** |
| `03_見積` | 見積番号, 問い合わせ日, 企業名, 案件名, 見積状況, 見積金額, 見積提出日, 有効期限, サービス種別, 数量/規模, 単価, **原価, 粗利, 粗利率**, 備考 | 見積段階の粗利まで既にある |
| `04_受注管理` | 受注番号, 受注日, 企業名, 案件名, 受注状況, 納品日, サービス種別, **受注金額, 原価, 粗利**, 入金状況, 入金日, 請求書番号, 担当スタッフ, 備考 | 受注・粗利の正本 |
| `05_顧客台帳` | 顧客ID, 企業名, 業種, …, 初回取引日, 最終取引日, 取引回数, 累計売上, 累計利益, 主要サービス, リピート区分, 優先度, …, **紹介元** | **過去顧客リストの正本。`紹介元` 列あり** |
| `06_売上管理` | 月, 売上日, 企業名, 売上金額, サービス種別, **受注番号**, 入金状況, … | 月次売上 |
| `07_利益管理` | 月, 対象日, 企業名, 売上, 原材料費, 外注費, その他原価, **粗利, 粗利率**, 経費按分, 営業利益, **受注番号** | **粗利の最終正本** |
| `08_Google投稿` / `09_Instagram` / `10_Threads` / `11_LINE` | 投稿日, タイトル, 本文, 投稿状況 | コンテンツ再利用の受け皿 |
| `12_口コミ` | — | 口コミ管理の受け皿 |
| `13_月次レポート` / `14_AI分析` | — | 出力先 |

**同一ワークブック内に追加されている営業CRM**（`core/catering_sales.py:25`）:

- `CATERING_SALES_TARGETS`（22列）: 登録日時, 営業先名, カテゴリ, 住所, 電話, Instagram, Webサイト, 担当者名, 想定ニーズ, 推定単価, 優先度, 営業文, 初回アプローチ日, 最終接触日, 返信状況, 商談状況, 見積状況, 成約状況, 次回フォロー日, 実売上, メモ, Obsidian Path
- `CATERING_SALES_DASHBOARD`（12列）
- カテゴリ別営業文テンプレート **20種以上**（ホテル/BAR/クラブ/企業/レンタルスペース/結婚式場/イベント会社/不動産/美容サロン/学校/観光団体/撮影スタジオ/スポーツ施設 …）を `SALES_TEMPLATES` にハードコード

> **重要**: `core/entrypoint.py:51-55` により `SPREADSHEET_ID` は `CATERING_SPREADSHEET_ID` に解決される。したがって `CATERING_SALES_TARGETS` は `02_問い合わせ`〜`07_利益管理` と**同一ワークブック内**にある。＝ CRM とファネルは同じ場所にあり、結合は技術的に容易。

**シートの「マイグレーション」慣習**: `_get_or_create_sheet(ss, title, header)`（`core/catering_sales.py:203`）が **新規作成時のみ**ヘッダを書く。既存シートへの列追加を行う関数は**存在しない**。→ 冪等な `ensure_columns()` を自作する必要あり（§5）。

### 1.5 認証・権限管理

| 項目 | 結果 |
|---|---|
| 認証 | **Google サービスアカウント1本**。`core/credentials_loader.py:13-45` `load_google_credentials()` が正典ローダー |
| 供給方法 | Cloud Run: `GOOGLE_CREDENTIALS_B64`（base64 JSON）→ tempfile 展開。ローカル: `GOOGLE_SERVICE_ACCOUNT_JSON` / `./credentials.json` |
| ユーザー認証 | **無し。ログイン・ユーザーテーブル・ロールは存在しない。** |
| 権限分離の実態 | ①**Google Sheets の共有設定**（誰にどのワークブックを見せるか）②**LINE配信先チャンネルの分離**（staff / customer / owner）③`DAILY_ACTION_LINE_MODE` = `OFF`/`OWNER_ONLY`/`STAFF`/`DRY_RUN`（`core/owner_daily.py:84`）④`STAFF_LINE_MAP` シートで LINE User ID → 事業を紐付け |
| 承認ポリシー | `docs/YU_BUSINESS_OS_2_DATA_CONTRACTS.md`: **staff通知は常にオーナー承認必須**（`staff_send_requires_owner_approval = True`）。外部送信・公開変更は承認なしで実行しない |
| Governance ゲート | `core/governance/validator.py` / `diff_risk.py` が PR 単位のリスク判定（後述1.7） |

→ **「オーナー向け画面には承認・重要判断だけ」は行レベル権限では実現できない。** シートを分ける（オーナー用集約シート）＋ LINE を `OWNER_ONLY` に固定する、の2手段のみ。

### 1.6 既存のCRM・案件・タスク・KPI・事業管理機能

`core/` に42モジュール。集客OSに関係する既存システム（すべて **DRY_RUN 既定 / 実送信オフ**）:

| # | システム | ファイル | 集客OSとの関係 |
|---|---|---|---|
| 1 | **Catering B2B Sales Autopilot** | `core/catering_sales.py` | ★**集客先CRMの本体候補**。`setup/generate_test_data/daily_targets/followup/get_status/export_knowledge` |
| 2 | **Catering 週次・月次レポート** | `core/catering_report.py:62-100` | ★**ファネル集計の既存実装**。`02_問い合わせ`〜`07_利益管理` を読み、受注率・粗利率・達成率を算出 |
| 3 | Lead Command Center | `core/lead_command.py` | 全事業のリード統合（LEAD_MASTER 26列、S/A/B/C 優先度スコアリング）。**流入元は SNS/DM 起点で、無料チャネル別の設計は無い** |
| 4 | Inquiry Killer | `core/inquiry_killer.py` | INQUIRY_MASTER（19列）。Phase1 は手入力前提 |
| 5 | Review & Referral Engine | `core/review_referral.py` | ★**口コミ・紹介の既存実装**。`REVIEW_REQUEST_MASTER` `REFERRAL_MASTER` `REVIEW_TEMPLATES`。Catering 用の紹介依頼文も既に登録済み |
| 6 | Customer Revival（失客復活） | `core/growth_engines.py` | ★**過去顧客への再アプローチの既存実装**。`CUSTOMER_REVIVAL_MASTER`（20列） |
| 7 | Profit Leak Detector | `core/profit_leak.py` | ★**粗利追跡の既存実装**。`PROJECT_PROFIT`（23列: 案件別 売上/食材費/外注費/装飾費/粗利/粗利率/**写真有無/口コミ依頼有無/再注文可能性/紹介可能性**）。Catering 目標粗利率 50% |
| 8 | Cash Flow Survival OS | `core/cash_flow.py` | 資金繰り。今回は範囲外 |
| 9 | Daily Action Commander | `core/daily_action_commander.py` | ★**次アクション配信の既存実装**。Catering は既に日次9タスク定義済み（営業DM5件/問い合わせ返信/実績投稿/Google・IG・Threads投稿/口コミ・紹介依頼/案件進捗）。09:00送信・17:00リマインド・21:00オーナー報告 |
| 10 | Owner Daily（OWNER_ONLY配信） | `core/owner_daily.py` | ★**オーナー限定・承認フローの既存実装**。「OK N / 修正 N / 除外 N / 完了 N,M」返信コマンド対応 |
| 11 | MEO / GBP | `core/gbp_api.py`, `growth_engines.py` | `GOOGLE_MAP_ACTIONS` `MEO_DAILY_TASKS`。`trees_catering` キー定義済み・**OAuth未設定** |
| 12 | Multi-business Content Engine | `core/multi_business_content_engine.py` | Catering の `08_Google投稿`/`09_Instagram`/`10_Threads` を読み、LINE staff へ通知。**自動投稿は `configs/auto_post_settings.py:13` で `auto_post_enabled: False`** |
| 13 | Knowledge OS | `core/knowledge_os.py` | 決定ログ・SOP・実行ログ → Obsidian/GCS |
| 14 | 商品マッチ先AIエージェント | `scripts/acquisition/` | ⛔ **`PAUSED=true`（mock混入）かつ `core/governance/validator.py:91` で `BLOCKED_PATH_PREFIXES = ("scripts/acquisition/",)` = 凍結パス。触れると PR が STOP になる** |

**存在しないもの（新規実装が必要）**
- ❌ **UTM** — リポジトリ全体で `utm` の実装ヒットは**0件**（仕様書内の記述のみ）
- ❌ **提携先（partner）の概念** — 実装ヒット0件（`core/catering_sales.py:71` の営業文文面に「提携」の語があるだけ）
- ❌ **流入元コードの共通語彙** — `02_問い合わせ.経路` 列は存在するが、値の正典（enum）が無い
- ❌ **ファネル結合キー** — 下記が最大のギャップ

**ファネル結合の現状（致命的ギャップ）**

```
02_問い合わせ  ─ ID列なし ─✗
03_見積        ─ 見積番号 / 問い合わせ日+企業名 だけ
04_受注管理    ─ 受注番号（見積番号への参照なし）
06_売上管理    ─ 受注番号 ✔
07_利益管理    ─ 受注番号 ✔ ＋ 粗利 ✔
```
→ `06`/`07` は `受注番号` で `04` に繋がるが、**`02` と `03`/`04` を機械的に繋ぐキーが無い**。「流入元別の受注売上・粗利」は現状**算出不能**。仕様書の完了定義の中核なので、ここが Week 1 の本命。

### 1.7 テスト・lint・型チェック・CI

| 項目 | 結果 |
|---|---|
| テストFW | **標準 `unittest`**（pytest 不使用、`conftest.py` / `pytest.ini` なし） |
| 構成 | `tests/` 配下12グループ・44ファイル（business_config 15, governance 3, release 2, instagram 2, knowledge, content, agent, registry, team, business_tools, plaud） |
| 命名 | ファイル `test_<module>.py` / クラス `<Scope>Test(unittest.TestCase)` / メソッド `test_<番号>_<説明>` |
| 実行 | `python -m unittest discover -s tests -p "test_*.py"` |
| 外部APIモック | **mock ライブラリ不使用。モジュール属性の直接差し替え＋finally復元**（例: `tests/business_config/test_activation_plan.py:66-84`, `tests/knowledge/test_daily_knowledge_export.py:78-90`） |
| ネットワーク禁止テスト | `tests/business_config/test_config_supply.py:200-212` `test_24_28_29_no_network`。また **ソース文字列を走査して `api.line.me` / `requests.post` / `openai` が無いことを検証**するパターンあり（`tests/instagram/test_windsor_source.py:57`） |
| **lint** | **無し**（ruff/flake8/black/isort の設定ファイルすべて不在） |
| **型チェック** | **無し**（mypy/pyright 設定なし） |
| CI が行う静的検査 | `python -m compileall -q core configs scripts tests` ＋ 主要モジュールの import 検証のみ（`.github/workflows/pr-validation.yml:55-58`） |
| CI | `.github/workflows/pr-validation.yml`（PR時）: 依存lock install → 構文 → **Governance Gate** → 変更分類 → 対象グループのunittest |
| Governance Gate 終了コード | `0=GO / 10=FIX / 20=OWNER_APPROVAL_REQUIRED / 30=STOP / 40=INTERNAL_ERROR`（`scripts/agent/governance_gate.py:34-40`） |
| リスク分類 | HIGH: `core/` `scripts/` `agents/` `config/` `configs/` `.github/workflows/`。MEDIUM: `tests/` `docs/` `.claude/`。CRITICAL: `.env` / credentials / private_key 等（`core/governance/diff_risk.py:22-40`） |
| 凍結パス | `scripts/acquisition/**` → 触ると STOP（`core/governance/validator.py:91`） |
| リリース | `.github/workflows/release.yml` は `workflow_dispatch` 手動のみ。`--no-traffic --tag candidate` でデプロイ → **read-only スモーク（GET /health, /status のみ）** → fail-closed |
| pre-commit | **無し**（`.pre-commit-config.yaml` なし、git hooks は sample のみ） |
| Secret スキャン | CI内のみ。`core/governance/diff_risk.py:122-141` `scan_secret_lines()` — **真偽値のみ返し、値は絶対に返さない**。10パターン（sk-, ghp_, xox-, BEGIN PRIVATE KEY, AIza, private_key_id, client_email, api_key…） |

→ **新規モジュールに求められるのは「unittest で書く」「純関数を分離してネットワーク無しでテストできる形にする」だけ。** lint/型は既存に無いので追加しない（規約優先）。

### 1.8 環境変数と秘密情報の管理方法

| 項目 | 結果 |
|---|---|
| テンプレート | `.env.template`（実値なし・キー名のみ、28+キー） |
| ローダー | `dotenv.load_dotenv()`（`core/entrypoint.py:24`）＋ `os.getenv()` 直読み。設定モジュールは無い |
| `.gitignore` | `.env` `*.env` `.env.*` `configs/env_templates/` `backups/` `*credentials*.json` `*token*.json` `*.key` `*.pem` を除外。さらに**実値が直書きされた3スクリプト＋`apps_script/ceo_dashboard_v2.js` を明示的に除外中**（要サニタイズ扱い） |
| Catering の秘密情報 | `CATERING_LINE_STAFF_TOKEN` / `CATERING_LINE_CUSTOMER_TOKEN` / `GOOGLE_CREDENTIALS_B64` / `OPENAI_API_KEY` — **すべて env 供給のみ、追跡ファイルに実値なし（確認済）** |
| Spreadsheet ID | **実値が `configs/business_registry.py` に追跡されている**。`configs/businesses/registry.yaml:10-15` のポリシーは「spreadsheet-id の値を持たず env 名のみ」を要求しており、**移行途上の既知の不整合**。新規実装で ID 実値を追加しないこと |
| PII の現状 | **追跡ファイルに顧客の氏名・電話・メールは無い（確認済）**。`data/acquisition/lead_review_export.csv` はサンプル社名（`ホテルXXX那覇` 等のマスク済み）、`fixtures/` は fake データのみ |
| 写真・公開許可 | 再利用可能な既存パターンあり: `data/reports/tachinomiya_owner_photo_approval_checklist.txt`（8項目 GO/FIX/STOP。項目3 が顔・個人情報チェック、許諾なし複数枚 → STOP） |
| Catering LP | **`configs/business_registry.py:79` の `booking_url` は空文字**。リポジトリ内に LP URL・LP用HTML・問い合わせフォームのエンドポイントは**存在しない** |

---

## 2. 再利用できる既存機能

| 仕様書の要件 | 再利用先 | 再利用の度合い |
|---|---|---|
| §5.1 集客先CRM | **`core/catering_sales.py` + `CATERING_SALES_TARGETS`** | ★★★ 列追加で足りる。名称/種別/担当者/電話/Instagram/Web/優先度/最終接触/次回フォロー/実売上は既にある |
| §5.1 過去顧客 | **`05_顧客台帳`**（取引回数/累計売上/累計利益/紹介元） | ★★★ そのまま正本として使える |
| §5.1 失客復活 | `core/growth_engines.py` `CUSTOMER_REVIVAL_MASTER` | ★★★ 既存の優先度ロジックを流用 |
| §5.4 次アクション自動抽出 | **`core/daily_action_commander.py`**（catering 9タスク定義済・09:00/17:00/21:00配信） | ★★★ タスク供給元を1つ足すだけ |
| §5.4 オーナー向けは承認・重要判断のみ | **`core/owner_daily.py`**（`OWNER_ONLY` モード・返信コマンド） | ★★★ そのまま |
| §5.5 テンプレートライブラリ | `core/catering_sales.py` `SALES_TEMPLATES`（20種以上）＋ `core/review_referral.py` `REVIEW_TEMPLATES`（口コミ・紹介、多言語） | ★★☆ 文面資産は流用可。**シート化・利用実績カウントは未実装** |
| §5.6 コンテンツ再利用 | `08_Google投稿`/`09_Instagram`/`10_Threads`/`11_LINE` ＋ `core/multi_business_content_engine.py` | ★★☆ 投稿先の受け皿は完成。**1案件→5媒体の派生タスク生成は未実装** |
| §5.6 事例の原価・粗利 | **`core/profit_leak.py` `PROJECT_PROFIT`**（写真有無/口コミ依頼有無/再注文可能性/紹介可能性の列を既に持つ） | ★★★ 事例台帳としてほぼ完成形 |
| §5.7 KPIダッシュボード | **`01_KPI`（数式集計）＋ `core/catering_report.py:62-100`（受注率/粗利率/達成率の算出済）** | ★★☆ 集計器は再利用。**流入元別の切り口だけ無い** |
| §5.7 口コミ・紹介KPI | `core/review_referral.py` `REVIEW_DASHBOARD` | ★★★ |
| 画面E 公開許可管理 | `tachinomiya_owner_photo_approval_checklist.txt` パターン | ★★☆ 手順は流用、Catering版を作る |
| 認証・Sheets接続 | `core/credentials_loader.py` `load_google_credentials()`、各モジュールの `_gc(creds_path)` | ★★★ |
| DRY_RUN 安全設計 | 関数引数 `dry_run: bool = True` 既定安全（`core/growth_engines.py:113` 等） | ★★★ |
| PRゲート | `core/governance/` + `.github/workflows/pr-validation.yml` | ★★★ |

**再利用率の見立て: 仕様書の機能要件のうち約 70% は既存資産の設定・列追加・接続で満たせる。**

---

## 3. 新規追加が必要な機能

| # | 機能 | なぜ新規か | 規模 |
|---|---|---|---|
| N1 | **流入元コードの共通語彙（12種）** | 実装ヒット0件。`02_問い合わせ.経路` に入れる値の正典が無い | 小（定数＋docs） |
| N2 | **ファネル結合キー（問い合わせID）** | `02`↔`03`↔`04` を繋ぐキーが無く、流入元別の受注・粗利が算出不能 | **中（既存シート3枚に列追加）** |
| N3 | **UTM URL生成** | 実装ヒット0件 | 小（純関数） |
| N4 | **提携先（partner）管理** | 概念そのものが無い。`CATERING_SALES_TARGETS.カテゴリ` の値拡張＋掲載日/掲載URL/掲載後問い合わせ数 | 小〜中 |
| N5 | **13ステータスの状態機械** | 現状は `返信状況/商談状況/見積状況/成約状況` の4列に分散。仕様書は単一 `ステータス` 13値 | 中（既存4列は残し、派生1列を追加） |
| N6 | **CSV import/export（100件一括投入）** | 既存に一括投入経路が無い | 小〜中 |
| N7 | **テンプレートのシート化＋実績カウント** | 文面はコード内ハードコード。利用回数/返信率/受注件数の記録先が無い | 中 |
| N8 | **流入元別 KPI 集計（受注/売上/粗利）** | N2 完了後に初めて可能 | 中 |
| N9 | **1案件→5媒体の派生タスク生成** | 未実装 | 中（Week3） |
| N10 | **集客用オーナー向け集約ビュー** | 権限機構が無いため「シート分離＋LINE OWNER_ONLY」で代替設計が必要 | 小 |

**明示的に作らないもの**: 新規Webアプリ / 有料API / 自動DM / 自動投稿 / スクレイピング / AI文章生成 / `scripts/acquisition/` への変更。

---

## 4. 最小変更で実現する設計案

### 設計原則

1. **新規ワークブックを作らない。** すべて `CATERING_SPREADSHEET_ID` の既存ワークブック内で完結させる（CRMとファネルが同一ワークブックにあるため結合が容易）。
2. **新規シートは最小限（2枚）。** 既存シートは**列の右端追加のみ**（並べ替え・削除・改名は禁止）。
3. **新規モジュールは1つ: `core/catering_growth.py`。** `core/entrypoint.py` には薄い委譲ルートのみ追加。
4. **純関数と I/O を分離する。** 語彙判定・UTM生成・次アクション抽出・流入元集計は**ネットワーク不要の純関数**にし、既存のテスト規約（unittest・ソース文字列走査）でテスト可能にする。
5. **`dry_run: bool = True` 既定。** シート書込みを伴う全関数に適用。外部送信は一切実装しない。
6. **AI API を使わない。** 文面は固定テンプレート＋`{変数}` 差し込みのみ。

### 4-A. 集客先CRM = `CATERING_SALES_TARGETS` を拡張（新規シートを作らない）

既存22列を**一切動かさず**、右端に11列を追加:

| 追加列 | 用途 |
|---|---|
| `対象先ID` | `tc_0001` 形式。CRMの主キー（現状主キーが無い） |
| `種別` | past_customer / network / own_business / partner_space / partner_bar / partner_wedding / hotel_villa / event_company / decor / studio / beauty_bridal |
| `流入元コード` | §5.2 の12コード |
| `メール` | 既存に電話/Instagram/Webはあるがメールが無い |
| `エリア` | — |
| `接触元` | 誰から/どこから知ったか |
| `見込み確度` | 0〜100 |
| `ステータス` | 13値（N5） |
| `使用テンプレートID` | `TEMPLATE_LIBRARY` への参照 |
| `UTM_URL` | 生成済みURL |
| `紹介者` | — |

`LP_URL` は列にせず `configs/business_registry.py` の `booking_url` を正本にする（重複を作らない）。

### 4-B. ファネル結合キー（本命）

| シート | 追加列 | 意味 |
|---|---|---|
| `02_問い合わせ` | `問い合わせID`, `対象先ID`, `流入元コード`, `UTM_campaign` | `経路`（既存）は自由記述のまま残し、`流入元コード` を機械可読な正本にする |
| `03_見積` | `問い合わせID` | 02 との結合 |
| `04_受注管理` | `問い合わせID`, `見積番号` | 03・02 との結合 |

これで結合が閉じる:

```
CATERING_SALES_TARGETS.対象先ID
   ↓
02_問い合わせ(問い合わせID, 流入元コード)
   ↓ 問い合わせID
03_見積(見積金額, 粗利)
   ↓ 問い合わせID / 見積番号
04_受注管理(受注番号, 受注金額, 粗利)
   ↓ 受注番号
06_売上管理(売上金額) / 07_利益管理(粗利, 粗利率)
```

→ **流入元 × 受注 × 売上 × 粗利** が算出可能になる。

### 4-C. 新規シート2枚のみ

| シート | 列 |
|---|---|
| `TEMPLATE_LIBRARY` | テンプレートID, 対象種別, チャネル, 用途, 件名, 本文, CTA, 変数一覧, LP差込位置, 利用回数, 返信数, 返信率, 受注件数, 更新日 |
| `GROWTH_DASHBOARD` | 日付, 流入元コード, 接触数, 返信数, 返信率, 問い合わせ数, 見積数, 受注数, 受注率, 売上, 粗利, 平均受注額, 紹介数, 口コミ獲得数, 提携先数, 最終更新 |

`PARTNER_*` は作らず `CATERING_SALES_TARGETS.種別` で表現（シート乱立を避ける）。提携掲載日・掲載URLは `メモ` ではなく上記追加列で扱う（掲載後30日問い合わせゼロ検知は `最終接触日` + `流入元コード` 別の問い合わせ有無で算出）。

### 4-D. モジュール構成

```
core/catering_growth.py         # 唯一の新規 core モジュール
  ├─ 純関数（ネットワーク不要・テスト対象）
  │   ├─ SOURCE_CODES / STATUSES / CONTACT_TYPES  … 語彙定数
  │   ├─ build_utm_url(base, source, medium, campaign, content, partner_id)
  │   ├─ validate_utm_token(s)          # 小文字英数_のみ、日本語/空白は拒否
  │   ├─ next_actions(rows, today)      # 8種の抽出ルール
  │   ├─ parse_contacts_csv(text)       # CSV → 行dict + バリデーション結果
  │   ├─ render_template(body, vars)    # {var} 差し込み（AI не使用）
  │   └─ aggregate_by_source(inq, est, ord, profit)  # 流入元別 受注/売上/粗利
  └─ I/O（dry_run=True 既定）
      ├─ ensure_columns(ss, sheet, want_headers, dry_run=True)  # 冪等・右端追加のみ
      ├─ setup(spreadsheet_id, creds_path, dry_run=True)
      ├─ import_contacts(csv_path, …, dry_run=True)
      ├─ refresh_dashboard(…, dry_run=True)
      └─ get_status(…)   # read-only

core/entrypoint.py  # 薄い委譲ルートのみ追加（既存パターン踏襲）
  /catering-growth-setup, -import, -next-actions, -dashboard, -status
```

CLI は既存慣習（`sys.argv` 分岐、argparse は既存コードで未使用）に合わせる。

### 4-E. 「画面」の実装先（仕様書§6の読み替え）

Web UI が無いため、以下に読み替える。**これは仕様変更なので承認が必要**:

| 仕様書の画面 | 実装先 |
|---|---|
| A. 無料集客ダッシュボード | `GROWTH_DASHBOARD` シート ＋ `core/owner_daily.py` の LINE `OWNER_ONLY` 配信（承認待ち・重要判断のみ） |
| B. 集客先一覧 | `CATERING_SALES_TARGETS` シート ＋ Sheets のフィルタビュー（人が作成、コード不要） |
| C. 集客先詳細 | 同シートの行 ＋ `02_問い合わせ` への `対象先ID` 結合 |
| D. テンプレート管理 | `TEMPLATE_LIBRARY` シート（編集は人が直接シートで行う） |
| E. 事例資産化 | `PROJECT_PROFIT`（既存）＋ Catering版 写真承認チェックリスト（docs） |

「1クリックでコピー」は Sheets の完成文セル（`render_template` 済み文字列）をコピーする形で満たす。追加アプリ不要。

---

## 5. 変更予定ファイル一覧

| ファイル | 変更種別 | リスク区分 | 備考 |
|---|---|---|---|
| `docs/catering-growth/repo-audit.md` | 新規 | **低（自動マージ可）** | 本レポート |
| `docs/catering-growth/vocabulary.md` | 新規 | **低** | 流入元12コード・13ステータス・種別・UTM命名規則の正典 |
| `docs/catering-growth/sheet-schema.md` | 新規 | **低** | 追加列と結合キーの正典（Before/After） |
| `docs/catering-growth/owner-photo-approval-catering.md` | 新規 | **低** | 公開許可チェックリスト（tachinomiya版の流用） |
| `docs/catering-growth/operations-sop.md` | 新規 | **低** | 日次運用SOP（誰が何を何分やるか） |
| `configs/catering_growth_vocab.py` | 新規 | **高（承認要）** | 語彙定数のみ。秘密情報・ID実値なし |
| `core/catering_growth.py` | 新規 | **高（承認要）** | 唯一の新規 core モジュール |
| `core/entrypoint.py` | 変更（追加のみ） | **高（承認要）** | `@app.route` を5本追加、既存ルートは触らない |
| `core/catering_sales.py` | 変更（最小） | **高（承認要）** | `CATERING_SHEETS` を33列に。**`_get_or_create_sheet` の書式範囲 `A1:V1`（22列固定）を列数算出に変更**。`generate_test_data` は見出し駆動なので変更不要（下記訂正参照） |
| `tests/catering_growth/__init__.py` | 新規 | 中 | — |
| `tests/catering_growth/test_vocabulary.py` | 新規 | 中 | 語彙の網羅・重複なし |
| `tests/catering_growth/test_utm.py` | 新規 | 中 | UTM生成・日本語/空白拒否 |
| `tests/catering_growth/test_next_actions.py` | 新規 | 中 | 8ルールの境界値 |
| `tests/catering_growth/test_csv_import.py` | 新規 | 中 | 100件・不正行・PII無しサンプル |
| `tests/catering_growth/test_attribution.py` | 新規 | 中 | 流入元別 受注/売上/粗利の集計 |
| `tests/catering_growth/test_safety.py` | 新規 | 中 | ソース走査で `api.line.me` / `requests.post` / `openai` / `broadcast` 不在を検証（既存 `test_windsor_source.py:57` パターン） |
| `.gitignore` | 変更（追記） | 中 | `data/catering_growth/*.csv` を除外（実顧客CSVの誤コミット防止） |
| `TASK.md` / `REPORT.md` | 変更 | 低 | Codex への指示・報告 |

**触らないファイル（明示）**: `.env*` / `scripts/acquisition/**`（凍結）/ `configs/business_registry.py` の ID 実値 / `apps_script/ceo_dashboard_v2.js` / `.github/workflows/**` / `Dockerfile` / `requirements*.txt`（**新規依存ゼロ ＝ 新規課金ゼロ**）。

---

## 6. DB変更とマイグレーションの必要性

**RDBMS が無いため SQL マイグレーションは不要。** ただし **Google Sheets のスキーマ変更は必要**で、これが実質のマイグレーションになる。

> ⚠️ **2026-07-27 訂正**（実地調査より）: `03_見積` `04_受注管理` `05_顧客台帳` `12_口コミ`
> `13_月次レポート` は**すべて0行**、`02_問い合わせ` はサンプル1件のみ。**位置参照コードが読む
> 対象データが存在しない**ため破壊性を **中 → 低** に下げる。また `CATERING_SALES_TARGETS` は
> **本番未作成**のため「列追加」ではなく「33列で新規作成」になる。手順（版履歴の復元ポイント →
> dry-run → 承認）は省略しない。

| 対象 | 変更 | 破壊性 |
|---|---|---|
| `CATERING_SALES_TARGETS` | ~~右端に11列追加~~ → **33列で新規作成** | なし（シート自体が未作成。`get_all_records()` 利用のため将来の列追加にも耐性あり） |
| `02_問い合わせ` | 右端に4列追加（P〜S列） | ~~中~~ → **低**（実データ1行）— `core/catering_report.py:64` が `get_all_values()[2:]` で**位置参照**している。右端追加なら既存インデックスは不変。**左・中間への挿入は禁止** |
| `03_見積` | 右端に1列 | ~~中~~ → **低**（0行）（同上、`:71`） |
| `04_受注管理` | 右端に2列 | ~~中~~ → **低**（0行）（同上、`:78` — `r[4] == "受注"` の位置参照あり） |
| 新規 `TEMPLATE_LIBRARY` / `GROWTH_DASHBOARD` | 新規作成 | なし |

**マイグレーション方式（基盤が無いので自作）**

```
ensure_columns(ss, sheet_title, want_headers, dry_run=True)
  1. 現ヘッダ行（2行目）を読む
  2. want_headers のうち未存在のものだけを右端に追加する差分を算出
  3. dry_run=True → 追加予定の列名を返すだけ。シートは触らない
  4. dry_run=False → 右端にのみ append。既存列の並べ替え・改名・削除は実装しない
  5. 何度実行しても同じ結果（冪等）
```

**必須の運用手順（本番シート保護）**
1. `core/catering_setup.py` は**再実行しない**（`sh.update("A2:O2", …)` でヘッダを上書きするため、既存データのある本番シートに走らせると危険）。
2. 適用前に **Google Sheets の版履歴で復元ポイントを作る**（オーナー操作、コードでは行わない）。
3. `--dry-run` の出力をオーナーが確認 → 承認 → `--apply`。
4. データ移行（既存行への値埋め）は**必要**: 既存の `02_問い合わせ` 行に `問い合わせID` を後付けする。既存行は `流入元コード = other`、ID は `既存行番号ベース` で採番。**この埋め戻しも dry-run → 承認 → apply の2段**。

---

## 7. 権限・個人情報・既存機能へのリスク

### R1. 個人情報（最重要）

| リスク | 内容 | 対策 |
|---|---|---|
| **実顧客CSVの誤コミット** | 過去顧客100件（氏名・電話・メール）を扱う。現状リポジトリに PII は無いが、CSV import 機能を作ると持ち込まれる | ①`.gitignore` に `data/catering_growth/*.csv` を追記 ②CSV の置き場所をリポジトリ外（`~/YU_HOLDINGS_Knowledge_OS` 等）に規定 ③テスト用サンプルは**架空の企業名・`090-0000-0000` 形式のダミーのみ**（既存 `fixtures/` 慣習に合わせる） ④`tests/catering_growth/test_safety.py` で追跡ファイル内に電話/メール正規表現が無いことを検証 |
| **PII の Sheets 共有範囲** | CRMシートに個人情報が入り、ワークブックを共有された全スタッフが閲覧可能になる | 個人情報（氏名/電話/メール）は `05_顧客台帳` と CRM に留め、`GROWTH_DASHBOARD` には**集計値のみ**書く。オーナー向け LINE 配信文に個人名を含めない |
| **公開許可なき事例公開** | 事例→5媒体展開で顧客名・写真が無断公開されうる | `PROJECT_PROFIT` に公開許可フラグを必須化し、**未許可は派生タスクを生成しない**（Week3の受入条件） |

### R2. 権限

| リスク | 内容 | 対策 |
|---|---|---|
| 行レベル権限が無い | 「オーナー向けは承認・重要判断のみ」を技術的に強制できない | シート分離 ＋ `DAILY_ACTION_LINE_MODE=OWNER_ONLY` ＋ オーナー宛は `core/owner_daily.py` 経由に限定 |
| サービスアカウント1本 | 集客OSも既存の全権SAで動く。最小権限化されていない | 今回は現状維持（SA分割は別PR案件）。**書込み先シートをコード側でホワイトリスト化**して事故範囲を絞る |

### R3. 既存機能の破壊

| リスク | 内容 | 対策 |
|---|---|---|
| **位置参照コードの列ズレ** | `core/catering_report.py:62-100` が `get_all_values()[2:]` + `r[4]` で位置参照 | **右端追加のみ**を機械的に強制（`ensure_columns` が挿入位置を持たない設計）。`test_attribution.py` で既存インデックス不変を検証 |
| ~~`generate_test_data` の列数不整合~~ | **2026-07-27 訂正: 誤りだった。** 実際は `[row_data.get(h, "") for h in header]` と**見出し駆動**で、列を増やせば自動追従し追加列は空欄で入る。列ズレは起きない | 対応不要。`tests/catering_growth/test_sheet_schema.py` で回帰を固定 |
| **ヘッダ書式範囲のハードコード**（新規に発見） | `_get_or_create_sheet` が `ws.format("A1:V1", …)` と22列目で固定。33列にすると右端11列が未装飾で残る | 列数から算出（`col_letter(len(header))`）。`test_06_format_range_matches_column_count` で検証 |
| `catering_setup.py` の再実行 | ヘッダ行を上書きし追加列を消す | 実行禁止をSOPに明記し、`ensure_columns` を正規の変更経路にする |
| Governance Gate STOP | `scripts/acquisition/**` は凍結パス | 一切触らない |
| 依存追加による課金 | — | `requirements.txt` を変更しない（新規依存ゼロ） |

### R4. 外部送信・自動化

| リスク | 対策 |
|---|---|
| LINE / Gmail / SNS の自動送信 | **実装しない。** `test_safety.py` でソース内に `api.line.me` / `requests.post` / `broadcast` が無いことを検証 |
| Cloud Scheduler の新規追加 | Week1では**追加しない**（既存 `core/daily_action_commander.py` の 09:00 枠に相乗り）。Scheduler 変更は高リスクPR |
| OpenAI 課金 | 使わない。`test_safety.py` で `openai` import 不在を検証 |

### R5. 未検証事項（正直な申告）

> **2026-07-27 追記 — 下記1件は解消済。** 実地調査の結果は `current-state-2026-07-27.md` を参照。
> **重要な訂正が3件出ている**ため、本レポート §2 の再利用評価と §6 のリスク評価は
> `current-state-2026-07-27.md` §2〜§6 で上書きされる。要点:
> ① **`CATERING_SALES_TARGETS` は本番未作成**（コードはあるが `/catering-sales-setup` 未実行）
> → §2 の「★★★ 列追加で足りる」は「シート新規作成が必要」に訂正
> ② **ファネルの表はほぼ空**（`03`/`04`/`05`/`12`/`13` が0行）→ 列追加の破壊性は §6 の「中」から**低**に低下
> ③ **`05_顧客台帳` が空** → 「過去顧客を `05_顧客台帳` からコピー」が成立しない

- ~~**本番ワークブックの実データ量が不明。**~~ → **2026-07-27 解消。** 読み取り専用調査を実施。
  ファネルの表は実質空（`02_問い合わせ` サンプル1件 / `03`・`04`・`05`・`12`・`13` が0行 /
  `07_利益管理` は setup のデモ値1行）。実売上は POS 由来の月次合計のみで
  **半年 ¥507,899 / 14件**、うち41%が単一商品ライン1件（¥211,500）。詳細は `current-state-2026-07-27.md`。
- **Catering LP の URL が不明。** `booking_url` が空で、リポジトリ内に LP のヒットが無い。UTM 生成にはベースURLが必須なので**オーナーからの提供が必要**（下記 §9 の前提）。
- **デプロイ済み `trees-catering-ai` の `SPREADSHEET_ID` env が上書きされていないか未確認**（`core/entrypoint.py:51` は `SPREADSHEET_ID` を最優先で読む）。CRMとファネルが同一ワークブックである前提はここに依存する。

---

## 8. Week 1 の分解（9タスク）と受入条件・テスト方法

各タスクは **1タスク=1PR** とする。リスク区分は CLAUDE.md の分類。

### W1-1. 語彙の正典化（docs のみ） ← **最初に着手**
- **内容**: `docs/catering-growth/vocabulary.md` に流入元12コード / ステータス13値 / 種別11値 / UTM命名規則 / 既存 `02_問い合わせ.経路` との対応表を確定。`docs/catering-growth/sheet-schema.md` に追加列と結合キーの Before/After を確定。
- **リスク**: 低（`docs/**` のみ → 自動マージ可）
- **受入条件**: ①12コード・13ステータスが一意で重複なし ②既存 `経路` 列の想定値がすべて12コードのいずれかに写像できる ③UTM命名規則が「小文字英数字とアンダースコアのみ・日本語空白禁止」と明記 ④追加列がすべて「右端追加」と明記され、挿入・改名・削除が禁止と書かれている
- **テスト**: レビューのみ（コード変更なし）。W1-2 のテストがこの表を参照する。

### W1-2. 語彙のコード化 + テスト
- **内容**: `configs/catering_growth_vocab.py` に定数（`SOURCE_CODES` `STATUSES` `CONTACT_TYPES` `STATUS_TRANSITIONS`）。I/O・ネットワークなし。
- **リスク**: 高（`configs/**` → 承認要）
- **受入条件**: ①`docs/vocabulary.md` と1:1一致 ②import 時にネットワーク・ファイルI/Oを一切行わない ③秘密情報・spreadsheet ID 実値を含まない
- **テスト**: `python -m unittest discover -s tests/catering_growth -t . -p "test_*.py"` / `test_vocabulary.py`: 重複なし・件数一致・不正コード拒否 / `test_safety.py`: ソース内に `api.line.me` `requests` `openai` `gspread` が無い

### W1-3. UTM URL生成（純関数）+ テスト
- **内容**: `core/catering_growth.py` に `build_utm_url()` / `validate_utm_token()`。ベースURLは引数（ハードコードしない）。
- **リスク**: 高（`core/**`）
- **受入条件**: ①`?` 有無・既存クエリ有無の両方で正しいURLを生成 ②日本語・空白・大文字を含むトークンを**拒否**（例外またはエラー返却） ③`content` `partner_id` が空なら該当パラメータを出力しない ④URLエンコードが正しい ⑤ネットワークアクセスなし
- **テスト**: `test_utm.py` — 正常5件 / 日本語拒否 / 空白拒否 / 大文字拒否 / 既存クエリ付きベースURL / 冪等性（2回呼んで同一）

### W1-4. 現状シート棚卸し（read-only CLI）
- **内容**: `core/catering_growth.py` に `inspect(spreadsheet_id, creds_path) -> dict`。14シート＋CRM2シートの**シート名・ヘッダ・行数・空列**を読み取り、追加が必要な列の差分を出力。**書込みゼロ。**
- **リスク**: 高（`core/**`）。ただし本番シートは**読み取りのみ**（CLAUDE.md の「本番Sheets直接変更」に該当しない）
- **受入条件**: ①`append_row` `update` `add_worksheet` を一切呼ばない（ソース走査で検証） ②出力に個人情報を含めない（**ヘッダと行数のみ、セル値は出さない**） ③シート欠損時も例外を投げず `missing` として報告 ④出力に spreadsheet ID 実値・トークンを含めない
- **テスト**: `test_inspect.py` — スタブ `_Reg()` 相当のフェイク `Spreadsheet` を注入（既存 `tests/business_config/test_activation_plan.py:66-84` の属性差し替えパターン）。実行時テストはネットワーク不要。**手動確認**: オーナー承認のうえローカルで1回実行し、実データ量とヘッダを確定して R5 を解消。

### W1-5. CRM列拡張（`ensure_columns`、dry-run→apply）
- **内容**: ~~`CATERING_SALES_TARGETS` に11列追加~~ → **W1-4.5 で33列新規作成に統合済（2026-07-27）**。`ensure_columns()` の実装は W1-6 で行う。
- **リスク**: 高（`core/**` ＋ 本番シート書込み → **オーナー承認必須**）
- **受入条件**: ①`dry_run=True` 既定。dry-run では**1セルも書かない**で追加予定列名を返す ②2回実行しても列が重複しない（冪等） ③既存22列の順序・名称が不変 ④中間挿入・改名・削除のコードパスが存在しない ⑤`get_all_records()` を使う既存関数（`daily_targets` `followup` `get_status`）が拡張後も同じ結果を返す ⑥`generate_test_data` の行が33列ぶん揃う（見出し駆動なので自動。テストで固定）
- **テスト**: `test_ensure_columns.py` — フェイクワークシートで(a)全列既存→追加0件 (b)一部欠落→欠落分のみ右端追加 (c)2回実行で冪等 (d)dry_run で書込みメソッド未呼出をアサート。**手動確認**: 版履歴で復元ポイント作成 → dry-run 出力をオーナー確認 → apply → シート目視。

### W1-6. ファネル結合キー付与（`02`/`03`/`04`、dry-run→apply）
- **内容**: `02_問い合わせ` に `問い合わせID` `対象先ID` `流入元コード` `UTM_campaign`、`03_見積` に `問い合わせID`、`04_受注管理` に `問い合わせID` `見積番号` を右端追加。既存行への `問い合わせID` 埋め戻し（`流入元コード = other`）も dry-run → apply。
- **リスク**: 高（本番シート書込み → **オーナー承認必須**）
- **受入条件**: ①`core/catering_report.py:62-100` の位置参照（`r[4]` 等）が拡張後も同じ値を読む ②既存行の `問い合わせID` が一意 ③埋め戻しが既存セルを1つも上書きしない（空セルのみ埋める） ④dry-run で差分件数のみ報告し書込みゼロ
- **テスト**: `test_attribution.py` の前半 — フェイク行で `r[4]` の値が列追加前後で不変であることをアサート。`test_funnel_keys.py` — ID採番の一意性・既存値の非破壊。**手動確認**: apply 後に `/catering-weekly` を dry-run 相当で叩き、受注率・粗利率が変更前と一致することを確認（**既存レポートの数値が変わらないことが合格条件**）。

### W1-7. CSV import/export（100件一括投入）
- **内容**: `parse_contacts_csv()`（純関数）＋ `import_contacts(..., dry_run=True)`。テンプレートCSVは `docs/catering-growth/` にヘッダのみ（データ行なし）で置く。
- **リスク**: 高（`core/**` ＋ 書込み）
- **受入条件**: ①100行のCSVを取り込める ②必須列欠落・不正な流入元コード・不正な優先度を**行単位で reject し理由を返す**（1行の不正で全体を落とさない） ③`対象先ID` を自動採番し既存と衝突しない ④重複判定（同一 電話 or メール or Instagram）で既存行を二重登録しない ⑤dry_run で「取込予定N件 / reject M件」のみ返す ⑥**リポジトリにコミットされるCSVは架空データのみ**
- **テスト**: `test_csv_import.py` — 100行ダミー（架空社名・`090-0000-0000`）/ 必須欠落 / 不正コード / 重複 / dry_run 非書込み。`test_safety.py` に「追跡CSVに実電話番号パターンが無い」検証を追加。**手動確認**: ダミー20件を実シートへ apply → 目視 → 手動削除。

### W1-8. 次アクション抽出（純関数）+ 既存日次配信への相乗り
- **内容**: `next_actions(rows, today)` で仕様書§5.4の8ルールを算出。`core/daily_action_commander.py` の catering タスク供給元に**1件追加するだけ**（新規Scheduler は作らない）。
- **リスク**: 高（`core/**`）
- **受入条件**: ①8ルールすべて実装（本日初回接触/3日後/7日後フォロー/返信あり未対応/見積後48h/受注後口コミ/受注後紹介/提携掲載後30日問い合わせゼロ） ②境界値が正しい（3日後は「ちょうど3日」を含む、48時間は「ちょうど48h」を含む） ③日付未設定・不正日付の行で例外を投げずスキップ ④出力にオーナー向け項目（承認待ち・重要判断）と staff 向けの区別がある ⑤LINE 送信コードを含まない（既存配信に文字列を渡すだけ）
- **テスト**: `test_next_actions.py` — 8ルール × (境界前/境界当日/境界後) の27ケース＋不正日付。`today` を引数化して固定日でテスト（`Date.now()` 相当の非決定性を排除）。

### W1-9. `GROWTH_DASHBOARD` 最小版（流入元別 受注/売上/粗利）
- **内容**: `aggregate_by_source()`（純関数）＋ `refresh_dashboard(..., dry_run=True)`。W1-6 の結合キーで `02→03→04→07` を突合。
- **リスク**: 高（`core/**` ＋ 書込み。ただし書込み先は**新規シートのみ**）
- **受入条件**: ①流入元12コード別に 接触数/返信数/返信率/問い合わせ数/見積数/受注数/受注率/売上/粗利/平均受注額 を出力 ②結合キーが欠落した行を `other` に寄せ、**欠落件数を明示的に報告する**（黙って落とさない） ③粗利は `07_利益管理` を正本とし、無い場合は `04_受注管理.粗利` にフォールバックし、どちらを使ったか出力に記録 ④ゼロ除算しない ⑤既存シートに書き込まない ⑥ダッシュボードに個人情報を書かない
- **テスト**: `test_attribution.py` — 既知の小さなフェイクデータセットで期待値を手計算し完全一致を検証 / 結合欠落あり / 粗利フォールバック / 分母ゼロ。**手動確認**: apply 後 `GROWTH_DASHBOARD` の売上合計が `01_KPI` の今月売上と一致することを目視。

### 全タスク共通の完了条件
```
python -m compileall -q core configs scripts tests
python -m unittest discover -s tests -p "test_*.py"
```
がパスし、Governance Gate が `0`（GO）または `20`（オーナー承認待ち）で、`30`（STOP）でないこと。**lint / 型チェックは既存に無いため追加しない。**

### Week 1 完了条件（仕様書 §7 との対応）
| 仕様書の完了条件 | 達成タスク |
|---|---|
| 100件の連絡先をCSVで投入可能 | W1-7 |
| 連絡先ごとの次回アクションを表示可能 | W1-8 |
| LP流入元をUTMで区別可能 | W1-3 ＋ W1-6 |
| （追加）受注売上・粗利まで追える | **W1-6 ＋ W1-9** ← 仕様書 §11 完了定義の中核 |

---

## 9. 最初に着手すべき1タスク

# → **W1-1: 語彙の正典化（docs のみ）**

**成果物**
- `docs/catering-growth/vocabulary.md` — 流入元12コード / ステータス13値 / 種別11値 / UTM命名規則 / 既存 `02_問い合わせ.経路` からの写像表
- `docs/catering-growth/sheet-schema.md` — `CATERING_SALES_TARGETS`（+11列）、`02_問い合わせ`（+4列）、`03_見積`（+1列）、`04_受注管理`（+2列）、新規2シートの Before/After ＋「右端追加のみ・挿入改名削除禁止」の明文化

**なぜこれが最初か**
1. **後続9タスク全部の前提。** 語彙が固まらないまま列を追加すると、本番シートの列を作り直す＝最も避けたい作業が発生する。
2. **リスクがゼロ。** `docs/**` のみなので CLAUDE.md の低リスクPR＝自動マージ可。本番シートに触らない。コードも動かさない。
3. **オーナー判断を最も安く引き出せる。** シート列の追加はオーナー承認が必須（高リスク）。承認判断に必要な情報を、実装前にドキュメント1本で提示できる。
4. **不可逆性が最小。** docs は後から直せる。本番シートの列は直しにくい。

**W1-1 の実行前にオーナー（ゆうさん）から必要な情報 — 2点のみ**
1. **Catering LP の URL**（`configs/business_registry.py:79` の `booking_url` が空。UTM生成のベースURLとして必須）
2. **§4-E の読み替えの承認**: この OS に Web UI は存在しないため、仕様書 §6「画面要件」を **Google Sheets のタブ設計 ＋ LINE の OWNER_ONLY 配信** として実装する。新規 Web アプリは作らない。

**次に着手するタスク**: W1-2（語彙のコード化）→ W1-4（read-only 棚卸しで §7 R5 の未検証事項を解消）→ W1-3（UTM）。
**本番シートに書き込む W1-5 / W1-6 は、W1-4 の棚卸し結果をオーナーが確認した後にのみ着手する。**

---

## 監査完了 — 承認待ち

本レポートの時点で作業を停止している。コード変更・シート変更・外部送信はいずれも行っていない。

**承認いただきたい事項**
1. §4 の設計方針（新規ワークブックを作らない／新規 core モジュールは1つ／既存シートは右端追加のみ）
2. §4-E の画面の読み替え（Web UI なし → Sheets タブ ＋ LINE OWNER_ONLY）
3. §9 の最初の1タスク = W1-1（docs のみ）
4. Catering LP の URL の提供
