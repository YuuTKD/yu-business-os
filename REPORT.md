# REPORT.md — 実装完了報告書

---

## TASK-015 W1-6 完了報告 — ファネル結合キーの付与

| 項目 | 内容 |
|---|---|
| **ブランチ** | feat/catering-growth-funnel-keys |
| **報告者** | Claude Code |
| **報告日** | 2026-07-27 |
| **リスク分類** | **High**（`core/**` 変更） |
| **対象** | `catering`（TREE's Catering）のみ |
| **本番シートへの適用** | **未実施。** 全エンドポイントが dry-run 既定で、適用にはオーナーが `?dry_run=0` を明示する必要がある |

### 何を解決したか

`02_問い合わせ` → `03_見積` → `04_受注管理` の間に共通キーが無く、**流入元別の受注売上・
粗利が算出不能**だった（`repo-audit.md` §1.6 / `current-state-2026-07-27.md`）。
`問い合わせID` を3枚に右端追加することでファネルが閉じる。

```
CRM(対象先ID・流入元コード) → 02(問い合わせID・流入元コード)
  → 03(問い合わせID) → 04(問い合わせID・受注番号) → 07(受注番号・粗利)
```

### 変更内容

| ファイル | 種別 | 概要 |
|---|---|---|
| `core/catering_growth.py` | MODIFIED | `FUNNEL_KEY_SPEC` / `PROTECTED_POSITIONS` / `SchemaError` ／純関数 `trim_trailing_empty` `plan_missing_columns` `parse_year_month` `plan_inquiry_backfill` ／ I/O `ensure_columns` `migrate_funnel_keys` `backfill_inquiry_ids`。CLI を `utm` サブコマンド式に変更 |
| `core/entrypoint.py` | MODIFIED | `/catering-funnel-keys` `/catering-backfill-inquiry-ids` `/catering-utm` を追加（前2本は **dry-run 既定**）／`_growth_dry_run()` ヘルパ |
| `tests/catering_growth/test_funnel_keys.py` | NEW | 37件 |
| `tests/catering_growth/test_utm.py` | MODIFIED | 安全性テスト3件を実態に合わせて書き直し（下記） |
| `docs/catering-growth/sheet-schema.md` `TASK.md` | MODIFIED | 実エンドポイントを追記・進捗更新 |

### 設計上の判断

1. **列の追加は右端のみ。挿入・並べ替え・改名・削除の機能を実装しない。**
   `core/catering_report.py` の位置参照（`02→r[0]` / `03→r[4]` / `04→r[4]` /
   `06→r[0],r[3]` / `07→r[0],r[7]`）を `PROTECTED_POSITIONS` として記録し、
   追加列が必ずそれより右に来ることをテストで固定した（`test_10`）。
2. **冪等。** 2回実行しても列が重複せず、2回目は書き込みゼロ（`test_14`）。
3. **既存セルを絶対に上書きしない。** 埋め戻しは空セルのみ（`test_23`）。
   既存 ID があればその月の連番を継いで衝突を避ける（`test_24`）。
4. **黙って落とさない。** 日付が読めない行はスキップし、件数と行番号を返す（`test_25`）。
5. **見出しの重複は fail-closed。** `get_all_records()` が壊れるため例外で止める（`test_06`）。
6. **列追加前に埋め戻しを呼ぶと例外で止まる**（`test_28`）。順序ミスを実行時に検出する。
7. **gspread は `_open_sheet()` の中で遅延 import。** 純関数をオフラインでテストできる
   （本タスクの37件は gspread 未インストールでも全件実行できる）。
8. **新規エンドポイントは dry-run 既定。** `?dry_run=0` を明示しない限り書き込まない。
   既存 `/catering-sales-setup` は挙動を変えないため既定のまま。

### 既存テストの書き直し（甘くしていないことの説明）

W1-3 時点の `test_utm.py` は「このモジュールは Sheets に触らない」前提だったが、
W1-6 で Sheets 操作が正当に加わったため3件を書き直した。**緩めたのではなく意図を精緻化した。**

| テスト | 変更前 | 変更後 |
|---|---|---|
| `test_38` | `gspread` の存在を禁止 | 外部送信手段（`requests` / `api.line.me` / `openai` 等）の禁止に限定。gspread は遅延 import であることを `test_funnel_keys.test_35` で別途検証 |
| `test_39` | `update(` `batch_update` も禁止 | **シート作成・行追加の禁止**（`append_row` / `add_worksheet` 等）に変更。`update` は見出し行と空セルのみが対象 |
| `test_41` | すべての `http(s)://` を禁止 | Google API のスコープ識別子（`googleapis.com`）と `example.test` のみ許可し、それ以外の URL 実値を禁止 |
| `test_40b` | — | **新規追加。** 書き込み系3関数の `dry_run` 既定が True であることを検証 |

### テスト結果

`requirements.lock` から依存を入れたクリーン環境（Python 3.11）。

```
python -m unittest discover -s tests -p "test_*.py"
→ Ran 708 tests ... OK      （失敗0 / エラー0 / スキップ0）
python -m compileall -q core configs scripts tests   → OK
```

内訳: 既存 670件 + 新規 37件 + 書き直し1件 = 708件。

### 手動確認

```
ルート登録:      /catering-funnel-keys /catering-backfill-inquiry-ids /catering-utm
                （総ルート数 166 → 169）
dry_run 既定:    引数なし → True ✅
                 ?dry_run=0     → False ✅
                 ?dry_run=false → False ✅
                 ?dry_run=1     → True  ✅
                 ?dry_run=yes   → True  ✅
```

### 安全性

- **本番シートへの書き込みを実行していない。** 新規2本は dry-run 既定
- 外部送信なし（`requests` / `api.line.me` / `openai` / `smtplib` / `gcloud` の不在を検証）
- **行やシートを増やさない**（`append_row` / `add_worksheet` の不在を検証）
- **挿入・改名・削除の機能を実装していない**（`insert_cols` / `delete_columns` 等の不在を検証）
- Secret / spreadsheet ID 実値 / 個人情報なし。テストデータは架空社名のみ
- `requirements.txt` 不変 = 新規依存ゼロ = **新規課金ゼロ**
- `scripts/acquisition/**`（凍結パス）未変更 / 他5事業に影響なし

### 本番適用の手順（オーナー操作・未実施）

```
1. Sheets の版履歴で復元ポイントを作成
2. GET /catering-funnel-keys                  → 追加予定列を確認（書き込みゼロ）
3. GET /catering-funnel-keys?dry_run=0        → 適用
4. GET /catering-weekly                       → 受注率・粗利率が適用前と一致するか確認
5. GET /catering-backfill-inquiry-ids          → 埋め戻し予定を確認（書き込みゼロ）
6. GET /catering-backfill-inquiry-ids?dry_run=0 → 適用
```

### 未解決事項・人間判断が必要な項目

| # | 内容 |
|---|---|
| 1 | **本番シートへの適用（上記手順）— 未実施。ゆうさんの指示により保留中** |
| 2 | **ケータリング LP の URL** — 未設定のため `/catering-utm` は実運用値を返せない（コードは完成） |
| 3 | ¥211,500 のオーダー弁当の発注元 / 過去14件の取引先 |

### 次に実装すべきタスク

W1-7（CSV import/export）。`parse_contacts_csv()` を純関数で実装し、
100件の連絡先を `CATERING_SALES_TARGETS` へ一括投入できるようにする。**dry-run 既定。**

---

## TASK-015 W1-3 完了報告 — UTM リンク生成

| 項目 | 内容 |
|---|---|
| **ブランチ** | feat/catering-growth-utm |
| **報告者** | Claude Code |
| **報告日** | 2026-07-27 |
| **リスク分類** | **High**（`core/**` 追加）→ マージ前に人間承認が必要 |
| **対象** | `catering`（TREE's Catering）のみ |
| **本番影響** | **なし**（純関数のみ。Sheets・LINE・外部送信いずれも触らない） |

### 変更内容

| ファイル | 種別 | 概要 |
|---|---|---|
| `core/catering_growth.py` | NEW | UTM リンク生成。`build_utm_url` / `build_utm_url_for_contact` / `validate_utm_token` / `validate_campaign` / `make_campaign` / `resolve_lp_base_url` / `parse_utm` ＋ CLI |
| `tests/catering_growth/test_utm.py` | NEW | 41件 |
| `TASK.md` | MODIFIED | W1-3 を DONE に |

### 設計上の判断

1. **不正な値は自動補正せず拒否する（`UtmError`）。** `Instagram` を黙って `instagram` に
   直すと、シート上の値と実際のURLが食い違い、**集計が静かにズレる**。落とした方が安全。
2. **LP の URL をコードに持たない。** `CATERING_LP_BASE_URL` → `business_registry.catering.booking_url`
   の順で解決し、どこにも無ければ**例外を投げて止まる**（fail-closed）。空文字で URL を
   組むと全ての流入元が追跡不能になるため、黙って続行しない。
3. **既存クエリとフラグメントを保持し、`utm_*` だけ上書きする。** 生成済みURLを再度
   ベースに渡しても `utm_*` が増殖しない（`test_25`）。
4. **冪等。** 同じ入力からは常に同じURLが出る（`test_24`）。シートの `UTM_URL` 列を
   何度再生成しても値が変わらない。

### テスト結果

`requirements.lock` から依存を入れたクリーン環境（Python 3.11）。

```
python -m unittest discover -s tests -p "test_*.py"
→ Ran 670 tests ... OK      （失敗0 / エラー0 / スキップ0）
python -m compileall -q core configs scripts tests   → OK
```

内訳: 既存 629件 + 新規 41件 = 670件。

**主なテスト観点**: 日本語・空白・大文字・ハイフンの拒否／`campaign` 形式／
既存クエリの保持／`utm_*` の上書き（重複しない）／フラグメント保持／冪等性／
生成済みURLの再投入／**流入元12 × medium 9 = 108通り全組み合わせ**／
未設定LP URL の fail-closed／`parse_utm` の往復一致。

### 手動確認（CLI・ネットワーク未使用）

```
$ python -m core.catering_growth instagram story tc_202608_test
{"ok": false, "error": "LP のベースURLが未設定です。環境変数 CATERING_LP_BASE_URL を…"}
  → 終了コード 1（fail-closed）

$ CATERING_LP_BASE_URL="https://example.test/catering" \
  python -m core.catering_growth partner_space qr tc_202608_partner_open tc_0042
{"ok": true, "utm_url": "https://example.test/catering?utm_source=partner_space
  &utm_medium=qr&utm_campaign=tc_202608_partner_open&utm_content=tc_0042"}
  → 終了コード 0

$ CATERING_LP_BASE_URL=… python -m core.catering_growth インスタ story tc_202608_test
{"ok": false, "error": "utm_source: 流入元コード12値のいずれかにしてください → 'インスタ'"}
  → 終了コード 1
```

### 安全性

- ネットワークアクセスなし・外部送信なし・AI API なし（`test_38` で不在を検証）
- **Sheets への書き込みコードを持たない**（`append_row` / `add_worksheet` 等の不在を `test_39` で検証）
- Secret / spreadsheet ID 実値 / 個人情報なし（`test_40`）
- LP の URL 実値をハードコードしていない（`test_41`）
- `requirements.txt` 不変 = 新規依存ゼロ = **新規課金ゼロ**
- `scripts/acquisition/**`（凍結パス）未変更 / 他5事業に影響なし

### 未解決事項・人間判断が必要な項目

| # | 内容 |
|---|---|
| 1 | **本PRのマージ承認**（`core/**` を含む高リスク） |
| 2 | **ケータリング LP の URL** — 未設定のため実運用のUTMがまだ生成できない（コードは完成） |
| 3 | 本番シートへの33列適用（W1-4.5）— **ゆうさんの指示により保留中** |
| 4 | ¥211,500 のオーダー弁当の発注元 / 過去14件の取引先 |

### 次に実装すべきタスク

W1-6（ファネル結合キーの付与）。`ensure_columns()` を実装し、`02_問い合わせ` に
`問い合わせID` `対象先ID` `流入元コード` `UTM_campaign` を、`03_見積` `04_受注管理` に
`問い合わせID` を右端追加する。**dry-run 既定。本番適用は別承認。**

---

## TASK-015 W1-2 / W1-4.5 完了報告 — 集客OS 語彙のコード化 ＋ CRM 33列化

| 項目 | 内容 |
|---|---|
| **ブランチ** | feat/catering-growth-crm-33cols |
| **報告者** | Claude Code |
| **報告日** | 2026-07-27 |
| **リスク分類** | **High**（`core/**` `configs/**` 変更）→ マージ前に人間承認が必要 |
| **対象** | `catering`（TREE's Catering）のみ |
| **対象外・不変** | beauty / tachinomiya / ryukyu_hinabe / pasta_pasta / z1 |
| **本番シートへの適用** | **未実施**（コードのみ。適用はオーナー承認後） |

### 変更内容

| ファイル | 種別 | 概要 |
|---|---|---|
| `configs/catering_growth_vocab.py` | NEW | 語彙の正典（流入元12 / 種別11 / ステータス13＋遷移 / utm_medium 9 / 失注理由8 / 優先度3 / ID形式 / 既存列からの写像 / 純関数13本）。**import は `__future__` のみ** |
| `core/catering_sales.py` | MODIFIED | `CATERING_SALES_TARGETS` を22→**33列**（既存22列は順序・名称不変、追加11列は右端のみ）／ヘッダ書式範囲を `A1:V1` 固定から `col_letter(len(header))` 算出に／`setup()` に `dry_run` 追加（既定 `False` で既存挙動を維持） |
| `core/entrypoint.py` | MODIFIED | `/catering-sales-setup` に `?dry_run=1` を追加（ルート数は増やさない） |
| `tests/catering_growth/test_vocabulary.py` | NEW | 43件（件数一致・語彙妥当性・遷移・写像・ステータス導出・ID・安全性） |
| `tests/catering_growth/test_sheet_schema.py` | NEW | 16件（33列・既存22列不変・追加列は右端・見出し一意・書式範囲・dry_run 非書込み） |
| `docs/catering-growth/*.md` / `TASK.md` | MODIFIED | 前回の誤記を訂正（下記）・進捗更新 |

### テスト結果

`requirements.lock` から依存を入れたクリーン環境（Python 3.11）で実行。

```
python -m unittest discover -s tests -p "test_*.py"
→ Ran 629 tests ... OK      （失敗0・エラー0・スキップ0）
python -m compileall -q core configs scripts tests   → OK
python -c "import core.entrypoint"                    → OK（routes 166 = 165ルート + static）
```

内訳: 既存 570件 + 新規 59件 = 629件。**既存テストの件数を減らしていない。**

> ⚠️ **注記**: ローカル素の `python3` では `gspread` / `flask` 未インストールのため
> 9件が ERROR になる。これは `main` でも同一に再現する**環境要因**で、
> 依存を入れた環境では全件 pass することを本PRで確認した。

### 前回報告の訂正（2件）

1. **`generate_test_data` の列ズレ懸念は誤りだった。** 実際は
   `[row_data.get(h, "") for h in header]` と**見出し駆動**で組み立てており、
   列を増やせば自動追従して追加列は空欄で入る。読み取り側4関数も
   `get_all_records()` ＋ `.get()` の名前参照で列追加に耐性がある。→ 変更不要。
2. **代わりに真の問題を発見**: `_get_or_create_sheet` のヘッダ書式範囲が
   `ws.format("A1:V1", …)` と**22列目で固定**。33列にすると右端11列が未装飾で残る。
   → 列数から算出する形に修正し、テストで固定した。

### 実装中に見つけて直した不具合

`derive_status()` の初版が **`未成約` を「成約」と誤判定して `WON` を返していた**
（`"成約" in "未成約"` が真になる）。`generate_test_data` が入れる既定値がまさに
`未成約` / `未提出` / `未商談` / `未送信` なので、**テストデータ20件が全部「受注済み」に
見える**不具合だった。否定形（`未` を含む値）を除外し、回帰テストを2件追加。

### 手動確認手順（本番適用は承認後）

```
1. オーナーが Sheets の版履歴で復元ポイントを作成
   （ファイル > 版履歴 > 現在の版に名前を付ける）
2. GET /catering-sales-setup?dry_run=1
   → 1セルも書かず「作成予定シートと列数(33)」を返すことを確認
3. オーナー承認
4. GET /catering-sales-setup        （dry_run なし）
5. シートを目視: 33列・見出しが AG 列まで装飾されていること
6. GET /catering-weekly を実行し、受注率・粗利率が適用前と一致することを確認
   （現状は両方0のため、値が変わらないことの確認）
```

### 未解決事項・人間判断が必要な項目

| # | 内容 |
|---|---|
| 1 | **本PRは高リスク（`core/**` `configs/**`）。マージにオーナー承認が必要** |
| 2 | **本番シートへの適用は未実施。** 上記手順で承認後に実行する |
| 3 | **ケータリング LP の URL** — `booking_url` が空。UTM のベースURLに必須（`CATERING_LP_BASE_URL`） |
| 4 | **¥211,500 のオーダー弁当の発注元** — 売上の41%・月目標の26%を占める最優先の商機 |
| 5 | 過去14件の取引先（`05_顧客台帳` が0行のため掘り起こしが必要） |

### 次に実装すべきタスク

W1-3（UTM URL 生成の純関数）。`core/catering_growth.py` を新規作成し、
`build_utm_url()` / `validate_utm_token()` を実装する。LP のベースURLは
`CATERING_LP_BASE_URL` から読み、コードに実値を持たない。

---

## Phase B2-8A 完了報告 — Catering deploy 承認の監査台帳記録

| 項目 | 内容 |
|---|---|
| **ブランチ** | feat/yu-business-os-2-catering-deploy-approval |
| **報告者** | Claude Code |
| **報告日** | 2026-07-14 |
| **リスク分類** | High（`configs/governance/**` `core/business_config/**` 変更）|
| **対象** | `catering`（trees-catering-ai）のみ |
| **対象外・不変** | beauty / ryukyu_hinabe / tachinomiya / pasta_pasta / z1 |

### 変更内容（deploy 実行ではなく「承認の記録」のみ）

| ファイル | 種別 | 概要 |
|---|---|---|
| `configs/governance/readiness_approvals.yaml` | MODIFIED | catering `deploy_approval: true` + `deploy_scope`（service/env/from-to mode/smoke/rollback）|
| `core/business_config/approvals.py` | MODIFIED | deploy 承認を許可（**scope 必須**）・scheduler/external-send は false 強制維持・`deploy_scope()` 追加 |
| `core/business_config/production_plan.py` | MODIFIED | deploy 承認済み時の warning/next_action を条件分岐 |
| `tests/business_config/test_readiness_activation.py` / `test_activation_plan.py` | MODIFIED | catering=承認・beauty/hinabe=未承認へ 8 件更新 |
| `docs/YU_BUSINESS_OS_2_DATA_CONTRACTS.md` | MODIFIED | deploy_scope 契約を追記 |

### 承認スコープ（限定）

- service: `trees-catering-ai` のみ / env: `YU_CONFIG_RUNTIME_MODE`（`LEGACY_ONLY → OWNER_APPROVED`）
- deploy 後 read-only smoke / 異常時 `LEGACY_ONLY` rollback
- **依然禁止**: Scheduler / 投稿 / LINE・Gmail / GCS・Sheets / SSOT_ONLY / Legacy 削除 / 他事業 deploy

### 影響

- catering: Activation Dry Run → **DRY_RUN_GO**（承認済み・ただし**実 deploy は未実行**）
- beauty / ryukyu_hinabe: deploy 未承認のまま（DEPLOY_APPROVAL_REQUIRED）
- **記録は監査証跡であり deploy 実行ではない**（実 deploy は人間が gcloud で実施）

### テスト実績

- `python3 -m unittest discover -s tests` → **Ran 371 tests OK**（8件を承認反映へ更新）
- Readiness（catering READY）/ Registry / Business Config CLI GO / Secret scan CLEAN / bash -n OK / ledger issues なし

### 既存構成への影響チェック

- [x] deploy / env 変更 / Scheduler / 投稿 / 送信 / 書込：**実行なし**（記録のみ）
- [x] beauty / ryukyu_hinabe / tachinomiya / pasta_pasta / z1：**deploy 未承認・不変**
- [x] Secret / credentials / token：**非表示・非読取**
- [x] `scripts/acquisition` / Tree Beauty 有効化 / `daily_post_limit`：**未変更**

### 人間承認が必要な項目

- Merge 実行（High → ゆうさん承認）/ 実 deploy（人間が gcloud で・別作業）

---

## Phase B2-7 完了報告 — Production Activation Preparation

| 項目 | 内容 |
|---|---|
| **ブランチ** | feat/yu-business-os-2-production-activation-prep |
| **報告者** | Claude Code |
| **報告日** | 2026-07-12 |
| **リスク分類** | High（`core/business_config/**` `scripts/**` 追加）|
| **売上直結度** | B（本番移行準備）|
| **対象（PART A）** | catering / beauty / ryukyu_hinabe（deploy 直前準備）|
| **対象（PART B）** | tachinomiya（技術確認のみ）|
| **対象外・不変** | pasta_pasta / z1 |

### 変更したファイル（追加のみ）

| ファイル | 種別 | 概要 |
|---|---|---|
| `core/business_config/production_plan.py` | ADDED | Activation Plan（PREPARED 等）+ TACHINOMIYA 技術判定 |
| `scripts/business_config/check_activation_plan.py` | ADDED | Plan CLI（exit 0/1/2/3/4）|
| `scripts/business_config/check_tachinomiya_technical_readiness.py` | ADDED | 技術確認 CLI |
| `tests/business_config/test_activation_plan.py` | ADDED | 32件 |
| `docs/YU_BUSINESS_OS_2_*.md`（3件）| MODIFIED | Plan/技術確認/次承認を役割別に追記 |

### PART A: READY 3事業の deploy 直前準備

- 各事業 → **PREPARED**（Cloud Run service 名・project（tree-beauty-ai-499303）・region（asia-northeast1）・env 変数名確定）
- deploy_approved / scheduler_approved / external_send_approved = **すべて false**（readiness 承認と分離）
- deploy / env update / smoke / rollback は**候補コマンド文字列**（`NOT EXECUTED`・実行フラグ常に false）
- rollback: 事業別 + 一括を検証（`YU_CONFIG_RUNTIME_MODE=LEGACY_ONLY`・code revert 不要・alias 維持）

### PART B: TACHINOMIYA 技術確認（値は一切読まない）

- Threads token: env NAME 宣言確認 → **MANUAL_CHECK_REQUIRED**（値非表示・期限は Meta で要確認）
- GBP: auth ファイル存在確認・location env NAME 確認 → **MANUAL_CHECK_REQUIRED**（credentials 非表示）
- 画像: **15枚不足**（interior+4 / drink+5 / exterior+6）
- Scheduler OFF 維持・投稿ゼロ・LINE ゼロ / token+GBP 確認済み+写真のみなら **PHOTO_PENDING_READY**
- 総合: **MANUAL_CHECK_REQUIRED**

### テスト実績

- `python3 -m unittest discover -s tests` → **Ran 371 tests OK**（+32）
- Activation Plan CLI（ready-three）→ **PREPARED / rc=0**・TACHINOMIYA 技術 CLI → MANUAL_CHECK_REQUIRED / rc=1
- Readiness / Activation Dry Run / Config Supply / Business Config / Registry CLI 既知状態・Secret scan CLEAN・外部通信ゼロ・bash -n OK

### 既存構成への影響チェック

- [x] deploy / env 変更 / Scheduler / 投稿 / LINE・Gmail / GCS・Sheets：**実行なし**（候補のみ）
- [x] readiness 承認を deploy 承認へ拡大していない（deploy_approved=false）
- [x] pasta_pasta / z1 / `scripts/acquisition` / Tree Beauty 有効化 / `daily_post_limit`：**未変更**
- [x] Secret / credentials / token 値：**非表示・非読取**

### 人間承認が必要な項目

- Merge 実行（High → ゆうさん承認）/ **deploy 承認**（別 PR）/ TACHINOMIYA 運用確認

---

## Phase B2-6 完了報告 — Readiness 承認 + Activation Dry Run（4事業）

| 項目 | 内容 |
|---|---|
| **ブランチ** | feat/yu-business-os-2-readiness-activation-batch |
| **報告者** | Claude Code |
| **報告日** | 2026-07-12 |
| **リスク分類** | High（`core/business_config/**` `configs/governance/**` `scripts/**` 追加）|
| **売上直結度** | B（本番移行・監査性）|
| **承認3事業** | catering / beauty / ryukyu_hinabe（READINESS scope のみ）|
| **監査対象** | tachinomiya |
| **対象外・不変** | pasta_pasta / z1 |

### 変更したファイル

| ファイル | 種別 | 概要 |
|---|---|---|
| `configs/governance/readiness_approvals.yaml` | ADDED | Owner 承認台帳（READINESS scope・deploy/scheduler/send=false）|
| `core/business_config/approvals.py` | ADDED | 台帳ローダ（deploy/scheduler/send 承認を false 強制）|
| `core/business_config/tachinomiya_audit.py` | ADDED | token/GBP/画像の read-only 監査（値は読まない）|
| `core/business_config/readiness.py` | MODIFIED | 台帳連携 + PHOTO_PENDING_READY + audit 統合 |
| `core/business_config/activation.py` | ADDED | 本番接続 Dry Run + Plan + Rollback 検証 |
| `scripts/business_config/dry_run_ssot_activation.py` | ADDED | Dry Run CLI（exit 0-5）|
| `scripts/business_config/check_ssot_readiness.py` | MODIFIED | 台帳駆動（flag なし→台帳判定）|
| `tests/business_config/test_readiness_activation.py` | ADDED | 39件 |
| `docs/YU_BUSINESS_OS_2_*.md`（4件）| MODIFIED | 承認 scope/監査/Dry Run/rollback を役割別に追記 |

### Owner 承認（監査可能・deploy と分離）

- catering / beauty / ryukyu_hinabe: `approval_type=READINESS`, `approval_scope=SSOT_PRODUCTION_READINESS`, **deploy_approval=false**
- readiness 承認を deploy 承認へ拡大解釈しない（台帳が deploy/scheduler/send を false 強制）

### 判定結果

| 事業 | Readiness | Activation Dry Run |
|---|---|---|
| catering / beauty / ryukyu_hinabe | **READY** | DEPLOY_APPROVAL_REQUIRED |
| tachinomiya | **ALMOST_READY** | READINESS_BLOCKED |
| pasta_pasta / z1 | NOT_READY（対象外）| — |

### TACHINOMIYA 監査（値は一切読まない）

- Threads token: env NAME 宣言確認 → **MANUAL_CHECK_REQUIRED**（期限は Meta で要確認）
- GBP: auth ファイル存在確認 → **MANUAL_CHECK_REQUIRED**（有効性は GCP で要確認）
- 画像: **PHOTO_PENDING**（interior 1→5 / drink 3→8 / exterior 4→10・追加15枚）
- Scheduler OFF 維持・実投稿ゼロ / token+GBP 確認済みなら **PHOTO_PENDING_READY**

### Activation は Dry Run のみ

deploy コマンドは**候補文字列**として生成するだけで**実行しない**。deploy 未承認のため READY 事業も **DEPLOY_APPROVAL_REQUIRED** で停止。**本番操作ゼロ**。Rollback は 4事業とも `YU_CONFIG_RUNTIME_MODE=LEGACY_ONLY`（code revert 不要・alias 維持）で検証済み。

### テスト実績

- `python3 -m unittest discover -s tests` → **Ran 339 tests OK**（+39）
- Readiness CLI（台帳駆動）→ 3 READY / tachinomiya ALMOST_READY / rc=1
- Activation Dry Run CLI → batch READINESS_BLOCKED / rc=1・catering DEPLOY_APPROVAL_REQUIRED / rc=3
- Config Supply / Business Config / Registry CLI GO / Secret scan CLEAN / 外部通信ゼロ / bash -n OK

### 既存構成への影響チェック

- [x] 3事業 readiness 承認のみ・TACHINOMIYA は監査のみ
- [x] deploy / Scheduler / Cloud Run env / 投稿 / LINE・Gmail / GCS・Sheets：**なし**
- [x] SSOT_ONLY / Legacy 削除 / 本番 Activation：**なし**
- [x] pasta_pasta / z1 / `scripts/acquisition` / Tree Beauty 有効化 / `daily_post_limit`：**未変更**
- [x] Secret / credentials / `.env` 内容：**非表示・非読取**

### 人間承認が必要な項目

- Merge 実行（High → ゆうさん承認）/ deploy 承認（別 PR）/ TACHINOMIYA 運用確認

---

## Phase B2-5 完了報告 — SSOT Production Readiness Gate（4事業）

| 項目 | 内容 |
|---|---|
| **ブランチ** | feat/yu-business-os-2-ssot-readiness-gate |
| **報告者** | Claude Code |
| **報告日** | 2026-07-12 |
| **リスク分類** | High（`core/business_config/**` `scripts/**` 追加）|
| **売上直結度** | B（本番接続前監査・移行安全性）|
| **対象4事業** | tachinomiya / catering / beauty / ryukyu_hinabe |
| **対象外・不変** | pasta_pasta / z1 |

### 変更したファイル（監査・Gate 実装のみ）

| ファイル | 種別 | 概要 |
|---|---|---|
| `core/business_config/readiness.py` | ADDED | 本番接続前 Readiness 判定（5段階 + INTERNAL_ERROR）|
| `core/business_config/config_supply.py` | MODIFIED | cross-business 混入検知を detail 参照へ拡張（安全強化）|
| `scripts/business_config/check_ssot_readiness.py` | ADDED | Readiness CLI（exit 0/1/2/3）|
| `tests/business_config/test_ssot_readiness.py` | ADDED | 25件 |
| `docs/YU_BUSINESS_OS_2_*.md`（3件）| MODIFIED | Readiness 契約/判定/次工程を役割別に追記 |

### Readiness 判定（owner 未承認・運用未確認時）

| 事業 | 判定 |
|---|---|
| **tachinomiya** | **ALMOST_READY**（画像不足 / Threads token 未確認 / GBP 認証未確認）|
| catering | OWNER_APPROVAL_REQUIRED |
| beauty | OWNER_APPROVAL_REQUIRED（active 状態維持）|
| ryukyu_hinabe | OWNER_APPROVAL_REQUIRED（GBP 除外・alias 維持）|
| pasta_pasta / z1 | NOT_READY（対象外・不変）|

### 事業別監査（コードで検証）

- TACHINOMIYA: 目標 5.5M=2.5M+3.0M 一致・owner/staff env 分離・staff 通知 gated・Scheduler OFF は要確認（warning）。**画像不足のため READY にしない**
- Catering: 供給 GO・inactive service を有効化しない（warning）
- Beauty: active 状態維持・供給 GO
- 火鍋: canonical `ryukyu_hinabe`・`hinabe` alias 維持・GBP 自動化除外（warning）

### STOP 条件（回避不可）

Secret-like 値 / cross-business 混入 / production write / SSOT_ONLY / 危険な有効化 → **STOP**

### テスト実績

- `python3 -m unittest discover -s tests` → **Ran 300 tests OK**（+25）
- Readiness CLI（batch）→ **NEEDS_WORK / rc=1**（tachinomiya ALMOST_READY）
- Config Supply CLI GO / Business Config CLI GO / Registry CLI GO / Secret scan CLEAN / 外部通信ゼロ / bash -n OK

### 既存構成への影響チェック

- [x] 監査・Gate 実装のみ（**production write なし**）
- [x] pasta_pasta / z1：**未変更**
- [x] deploy / Scheduler / Cloud Run env / 投稿 / LINE・Gmail / GCS・Sheets：**なし**
- [x] runtime 既定（LEGACY_ONLY）/ Legacy fallback：**不変**
- [x] `scripts/acquisition` / Tree Beauty 有効化 / `daily_post_limit`：**未変更**

### 人間承認が必要な項目

- Merge 実行（High → ゆうさん承認）/ TACHINOMIYA 運用確認による READY 化

---

## Phase B2-4 Batch 2 完了報告 — 琉球火鍋の SSOT 由来 config 供給

| 項目 | 内容 |
|---|---|
| **ブランチ** | feat/yu-business-os-2-ssot-config-supply-ryukyu-hinabe |
| **報告者** | Claude Code |
| **報告日** | 2026-07-12 |
| **リスク分類** | High（`core/business_config/**` 拡張）|
| **売上直結度** | B（設定移行・監査性向上）|
| **今回対象** | `ryukyu_hinabe`（琉球火鍋）**のみ** |
| **対象外・不変** | `pasta_pasta` / `z1` |

### 変更したファイル（火鍋だけの one PR one purpose）

| ファイル | 種別 | 概要 |
|---|---|---|
| `core/business_config/config_builder.py` | MODIFIED | `BATCH2_BUSINESSES=(ryukyu_hinabe,)` 追加・`build_ryukyu_hinabe_config` 追加 |
| `core/business_config/config_supply.py` | MODIFIED | supply scope 拡張 + `hinabe` alias 解決 |
| `tests/business_config/test_ryukyu_hinabe_supply.py` | ADDED | 20件 |
| `tests/business_config/test_config_supply.py` | MODIFIED | 2件を「pasta/z1 のみ out-of-scope」へ更新 |
| `docs/YU_BUSINESS_OS_2_*.md`（3件）| MODIFIED | Batch 2＝火鍋のみを役割別に追記 |

### 火鍋の正式設定

- canonical id: `ryukyu_hinabe` / legacy alias: `hinabe`（alias としてのみ維持・削除なし）
- `supply('hinabe')` は canonical に解決され**同一 config**
- POS(usen・tabelog)・売上連携・別オーナー email・approval policy は legacy 通し
- GBP 自動化 / 投稿 / LINE / Gmail / Scheduler / Cloud Run は**有効化しない**
- 既定 LEGACY_ONLY / owner 承認時のみ SSOT / 失敗時 Legacy fallback（silent fallback なし）

### テスト実績

- `python3 -m unittest discover -s tests` → **Ran 275 tests OK**（+20）
- Config Supply CLI（ryukyu_hinabe OWNER_APPROVED）→ **SSOT / GO**
- Business Config CLI GO / Registry CLI GO / Secret scan CLEAN / 外部通信ゼロ / bash -n OK

### 既存構成への影響チェック

- [x] `pasta_pasta` / `z1`：**コード・設定・テスト・docs すべて未変更**
- [x] Batch 1 の3事業：**不変**（SSOT 供給維持）
- [x] Legacy / alias 削除：**なし**（hinabe alias 維持）
- [x] SSOT_ONLY / 本番強制切替：**なし**
- [x] deploy / Scheduler / Cloud Run env / 投稿 / LINE・Gmail / GCS・Sheets：**なし**
- [x] `scripts/acquisition` / Tree Beauty 有効化 / `daily_post_limit`：**未変更**

### 人間承認が必要な項目

- Merge 実行（High → ゆうさん承認）/ 次候補（pasta_pasta・z1）の開始可否

---

## Phase B2-4 Batch 1 完了報告 — SSOT 由来 config 供給（3事業）

| 項目 | 内容 |
|---|---|
| **ブランチ** | feat/yu-business-os-2-ssot-config-supply-batch-1 |
| **報告者** | Claude Code |
| **報告日** | 2026-07-11 |
| **リスク分類** | High（`core/**` `scripts/**` 追加 + runtime_loader 拡張）|
| **売上直結度** | B（設定移行・監査性向上）|
| **対象3事業** | tachinomiya / catering（TREE'S CATERING）/ beauty（TREE BEAUTY）|

### 変更したファイル

| ファイル | 種別 | 概要 |
|---|---|---|
| `core/business_config/config_builder.py` | ADDED | SSOT→Legacy 互換 config 変換・shape 検証・mutation なし |
| `core/business_config/config_supply.py` | ADDED | 3事業の供給判定（comparator + builder）・batch |
| `core/business_config/runtime_loader.py` | MODIFIED | `apply_runtime_config` を supply へ拡張（既定 LEGACY_ONLY は identity）|
| `scripts/business_config/check_ssot_config_supply.py` | ADDED | 供給検証 CLI（exit 0/1/2/3）|
| `tests/business_config/test_config_supply.py` | ADDED | 30件 |
| `tests/business_config/test_runtime_loader.py` | MODIFIED | 1件を B2-4 挙動へ更新（identity→SSOT 供給）|
| `docs/YU_BUSINESS_OS_2_*.md`（5件）| MODIFIED | Builder/供給/rollback を役割別に追記 |

### Config Builder / 供給ルール

- SSOT 所有スカラー（monthly_target / business_type / status / cloud_run_service）のみ overlay、他は legacy 通し
- **LINE env 名は overlay しない**（実 Cloud Run env を壊さない）
- 入力 legacy を変更せず新規 dict を返す・Secret 値は読まない（env 名のみ）
- SSOT 欠損/型不一致 → FIX（Legacy fallback）/ 事業ID混入 → STOP / mismatch は隠さず FIX

### 3事業の結果

- TACHINOMIYA: 昼2.5M+夜3.0M=**5.5M**・owner/staff LINE env 分離・staff 通知 approval 必須・shape 互換 GO
- TREE'S CATERING: SSOT 供給 GO・shape 互換・inactive service を有効化しない・env 名のみ・外部接続ゼロ
- TREE BEAUTY: SSOT 供給 GO・shape 互換・**active 状態維持**・GBP/Scheduler 実行なし・Tree Beauty 有効化なし

### 対象外3事業（挙動不変）

ryukyu_hinabe / pasta_pasta / z1 → supply は常に **LEGACY**（供給対象外）

### テスト実績

- `python3 -m unittest discover -s tests` → **Ran 255 tests OK**（+30）
- Config Supply CLI（batch OWNER_APPROVED）→ 3事業 SSOT / **batch GO**
- Runtime main-path CLI GO / Business Config CLI GO / Registry CLI GO / Secret scan CLEAN / 外部通信ゼロ / bash -n OK

### 既存構成への影響チェック

- [x] 既定挙動：**不変**（LEGACY_ONLY）
- [x] 対象外事業：**変更なし**
- [x] 既存設定削除 / Legacy 削除 / 本番強制切替 / SSOT_ONLY：**なし**
- [x] deploy / Scheduler / Cloud Run env / 投稿 / LINE・Gmail / GCS・Sheets：**なし**
- [x] `scripts/acquisition` / Tree Beauty 有効化 / `daily_post_limit`：**未変更**

### 人間承認が必要な項目

- Merge 実行（High → ゆうさん承認）/ Batch 2 の開始可否

---

## Phase B2-3 完了報告 — Runtime main path を SSOT Resolver へ安全接続

| 項目 | 内容 |
|---|---|
| **ブランチ** | feat/runtime-main-path-ssot-connection |
| **報告者** | Claude Code |
| **報告日** | 2026-07-11 |
| **リスク分類** | High（`core/entrypoint.py` 追加変更 + `core/**` `scripts/**` 追加）|
| **売上直結度** | B（設定移行・監査性向上）|

### 変更したファイル

| ファイル | 種別 | 概要 |
|---|---|---|
| `core/business_config/runtime_loader.py` | ADDED | feature flag 判定・source 解決・fail-closed |
| `core/business_config/business_loader.py` | ADDED | legacy 取得＋接続の再利用層 |
| `scripts/business_config/check_runtime_main_path.py` | ADDED | Runtime main-path CLI（exit 0/10/20/30/40/50）|
| `core/entrypoint.py` | MODIFIED | `apply_runtime_config` を追加呼出（既存ロジック削除なし・CONFIG 不変）|
| `tests/business_config/test_runtime_loader.py` | ADDED | 19件 |
| `docs/YU_BUSINESS_OS_2_*.md`（3件）| MODIFIED | 接続・flag・rollback を役割別に追記 |

### Feature Flag / Runtime

- `YU_CONFIG_RUNTIME_MODE`: **LEGACY_ONLY(既定)** / AUTO / OWNER_APPROVED
- 既定 LEGACY_ONLY → Resolver を呼ばず CONFIG をそのまま返す（**挙動不変**）
- OWNER_APPROVED（または AUTO+`YU_OWNER_APPROVED=true`）→ Resolver 判定 → SSOT（mismatch 0 時）/ 失敗時 Legacy fallback
- 対象は TACHINOMIYA のみ・他事業は常に LEGACY

### 安全設計

- `apply_runtime_config` は CONFIG を**変更せず同一オブジェクトを返す**（形・値不変・identity 保持）
- 例外時は fail-closed（起動を止めず Legacy 継続）
- env 変数**名**のみ・token 値は読まず・出さず・外部通信ゼロ・import 副作用なし
- **rollback**: `YU_CONFIG_RUNTIME_MODE=LEGACY_ONLY`（1 設定）/ code revert 不要

### テスト実績

- `python3 -m unittest discover -s tests` → **Ran 225 tests OK**（+19）
- Runtime main-path CLI: LEGACY rc=0 / OWNER_APPROVED rc=0（source=SSOT）
- Runtime resolver CLI GO / Shadow CLI GO / Business Config CLI GO / Registry CLI GO / Secret scan CLEAN / 外部通信ゼロ / bash -n OK

### 既存構成への影響チェック

- [x] 既存コード削除：**なし**（entrypoint は追加のみ）
- [x] 既存データ変更 / Legacy 削除：**なし**
- [x] deploy / Cloud Run env / Scheduler / 投稿 / LINE・Gmail / GCS・Sheets：**なし**
- [x] `scripts/acquisition` / Tree Beauty / `daily_post_limit`：**未変更**
- [x] 既定挙動：**不変**（LEGACY_ONLY）

### 人間承認が必要な項目

- Merge 実行（High → ゆうさん承認）/ Phase B2-4 の開始可否

---

## Phase B2-2 完了報告 — TACHINOMIYA SSOT primary + Legacy fallback

| 項目 | 内容 |
|---|---|
| **ブランチ** | feat/tachinomiya-ssot-primary-with-legacy-fallback |
| **報告者** | Claude Code |
| **報告日** | 2026-07-11 |
| **リスク分類** | High（`core/**` `scripts/**` 追加）|
| **売上直結度** | B（設定移行・監査性向上）|

### 実装したファイル（追加のみ）

| ファイル | 種別 | 概要 |
|---|---|---|
| `core/business_config/runtime_resolver.py` | ADDED | TACHINOMIYA 限定 source 選択（SSOT primary / Legacy fallback）|
| `scripts/business_config/check_tachinomiya_runtime.py` | ADDED | Runtime CLI（exit 0/10/20/30/40/50）|
| `tests/business_config/test_runtime_resolver.py` | ADDED | 25件 |
| `docs/YU_BUSINESS_OS_2_*.md`（3件）| MODIFIED | SSOT primary/fallback/rollback を役割別に追記 |

### runtime mode / source 選択

- モード: LEGACY_ONLY / SHADOW_ONLY / **SSOT_PRIMARY_WITH_LEGACY_FALLBACK** / SSOT_ONLY(**禁止=STOP**)
- SSOT 使用条件: owner 承認 + mismatch 0 + SSOT 有効 + migration ∈ {SHADOW_DEFINED, VERIFIED}
- fallback 条件: SSOT 読込失敗 / schema 不完全（**mismatch は fallback しない → FIX/STOP**）
- 未承認 → OWNER_APPROVAL_REQUIRED / 他事業 SSOT primary → STOP
- TACHINOMIYA 限定。他事業は常に LEGACY

### 安全設計

- SSOT 値は承認+一致時のみ返す。危険差分（昼夜不一致・他事業混入・secret）は STOP
- env 変数**名**のみ比較（token 値は読まず・出さず・ログしない）
- import 副作用なし（AST）・外部通信ゼロ・fail-closed
- 本番 main path 未変更（default OFF hook のみ）
- **rollback**: `--mode LEGACY_ONLY`（引数1つ）で即復旧・Legacy/alias 削除なし

### テスト実績

- `python3 -m unittest discover -s tests` → **Ran 206 tests OK**（+25）
- Runtime CLI: 未承認 rc=20 / 承認 rc=0（runtime_source=SSOT）/ SSOT_ONLY rc=40 / 他事業 rc=40
- Shadow CLI GO / Business Config CLI GO / Registry CLI GO / Secret scan CLEAN / 外部通信ゼロ

### 既存構成への影響チェック

- [x] 本番常時経路の切替：**なし**（承認時のみ SSOT・default OFF）
- [x] 他事業切替 / SSOT_ONLY：**なし**（STOP）
- [x] Legacy 削除 / alias 削除：**なし**
- [x] Cloud Run / Scheduler / 投稿 / LINE・Gmail / GCS・Sheets：**なし**
- [x] `scripts/acquisition` / Tree Beauty / `daily_post_limit`：**未変更**

### 人間承認が必要な項目

- Merge 実行（High → ゆうさん承認）/ Phase B2-3（本番経路接続）の開始可否

---

## Phase B2-1 完了報告 — TACHINOMIYA SSOT Shadow 接続

| 項目 | 内容 |
|---|---|
| **ブランチ** | feat/tachinomiya-ssot-shadow-connection |
| **報告者** | Claude Code |
| **報告日** | 2026-07-11 |
| **リスク分類** | High（`core/**` `scripts/**` 追加）|
| **売上直結度** | B（設定移行基盤・監査性向上）|

### 実装したファイル（追加のみ）

| ファイル | 種別 | 概要 |
|---|---|---|
| `core/business_config/shadow_adapter.py` | ADDED | TACHINOMIYA 限定 Legacy↔SSOT 比較。runtime_source=LEGACY 不変 |
| `scripts/business_config/check_tachinomiya_shadow.py` | ADDED | Shadow 検証 CLI（exit 0/1/2/3）|
| `tests/business_config/test_shadow_adapter.py` | ADDED | 20件 |
| `docs/YU_BUSINESS_OS_2_*.md`（3件）| MODIFIED | Shadow 接続・runtime_source=LEGACY を役割別に追記 |

### Shadow 接続の要点

- **runtime_source は常に LEGACY**（SSOT 値は本番へ渡さない・渡せば STOP）
- モード: OFF / SHADOW_ONLY(既定) / ENFORCE_COMPARE（引数・CLI・テスト限定・.env 保存なし）
- 比較は env 変数**名**のみ（token 値は読まず・出さず）
- fail-closed: unknown mode / 昼夜不一致 / 他事業混入 / production 誤表示 / import 副作用 → STOP
- 本番 main path は**未変更**（default OFF の hook のみ・強制接続なし）

### テスト実績

- `python3 -m unittest discover -s tests` → **Ran 181 tests OK**（+20）
- Shadow CLI SHADOW_ONLY/ENFORCE_COMPARE → **GO / exit 0 / mismatch 0**
- Business Config CLI GO / Registry CLI GO / `bash -n` OK / Secret scan CLEAN / 外部通信ゼロ

### 既存構成への影響チェック

- [x] 本番読込先切替：**なし**（runtime_source LEGACY）
- [x] Legacy 削除 / alias 削除：**なし**
- [x] Cloud Run / Scheduler / 投稿 / LINE・Gmail / GCS・Sheets：**なし**
- [x] `scripts/acquisition` / Tree Beauty / `daily_post_limit`：**未変更**
- [x] Secret 直書き：**なし**

### 人間承認が必要な項目

- Merge 実行（High → ゆうさん承認）/ Phase B2-2（実切替）の開始可否

---

## Phase B1.1 完了報告 — Business Config 不一致の解消

| 項目 | 内容 |
|---|---|
| **ブランチ** | feat/yu-business-os-2-resolve-config-mismatches |
| **報告者** | Claude Code |
| **報告日** | 2026-07-11 |
| **リスク分類** | High（既存 `core/**` `configs/**` の値変更を含む）|
| **売上直結度** | B（設定整合・監査性/売却可能性の向上）|

### 確定値（ゆうさん確定）

- TACHINOMIYA 月商目標: **5,500,000**（昼 2,500,000 + 夜 3,000,000）
- 火鍋 canonical id: `ryukyu_hinabe` / legacy alias: `hinabe`
- TACHINOMIYA staff LINE canonical: `LINE_TACHINOMIYA_STAFF_TOKEN` / legacy alias: `LINE_TACHINOMIYASTAFF_TOKEN`

### 変更したファイル

| ファイル | 種別 | 概要 |
|---|---|---|
| `configs/business_registry.py` | MODIFIED | tachinomiya monthly_target 3.5M→**5.5M** |
| `core/system_health.py` | MODIFIED | MONTHLY_TARGETS tachinomiya 3.5M→**5.5M** |
| `ceo/executive_team.py` | MODIFIED | BUSINESS_TARGETS TACHINOMIYA 1.2M→**5.5M** |
| `configs/businesses/registry.yaml` | MODIFIED | 昼夜内訳・slug alias(hinabe)・env alias 追加 |
| `core/business_config/models.py` | MODIFIED | day/night・slug_aliases・env aliases フィールド |
| `core/business_config/loader.py` | MODIFIED | 昼夜整合・alias 検証/解決・LINE channel API |
| `core/business_config/comparator.py` | MODIFIED | alias 解決で乖離を正常化 |
| `tests/business_config/test_resolve_mismatches.py` | ADDED | 19件 |
| `docs/YU_BUSINESS_OS_2_*.md`（4件）| MODIFIED | canonical/alias/互換期間を役割別に追記 |

### 解消結果

- Business Config CLI: **FIX(5件) → GO / exit 0 / mismatch 0**
- alias は削除せず併存（canonical 優先・legacy fallback）
- token 値は読まず・出さず（NAME のみ）/ staff 通知は owner approval 必須
- env 変数の実体名は変更なし（Cloud Run の実 env を壊さない）

### テスト実績

- `python3 -m unittest discover -s tests` → **Ran 161 tests OK**（+19）
- `python3 scripts/business_config/validate_business_configs.py` → **GO（exit 0）**
- Registry CLI GO / `bash -n` OK / Secret scan CLEAN / 外部通信ゼロ

### 既存構成への影響チェック

- [x] legacy alias 削除：**なし**（併存）
- [x] Cloud Run / Scheduler / 外部送信 / GCS / Sheets：**なし**
- [x] env 変数の実体・本番読込先切替：**なし**
- [x] `scripts/acquisition` / Tree Beauty / `daily_post_limit`：**未変更**
- [x] Secret 直書き：**なし**

### 人間承認が必要な項目

- Merge 実行（High → ゆうさん承認）/ Phase B2 開始可否

---

## Phase B1 完了報告 — Business Config SSOT（Shadow Mode）

| 項目 | 内容 |
|---|---|
| **ブランチ** | feat/yu-business-os-2-business-config-ssot |
| **報告者** | Claude Code |
| **報告日** | 2026-07-11 |
| **リスク分類** | High（`core/**` `configs/**` `scripts/**` への追加を含む）|
| **売上直結度** | B（設定二重管理の解消・売却可能性/監査性向上の基盤）|

### 実装したファイル（すべて新規追加・既存の変更/削除なし）

| ファイル | 変更種別 | 概要 |
|---|---|---|
| `configs/businesses/registry.yaml` | ADDED | 6事業 SSOT（shadow・env 名のみ・secret-free）|
| `core/business_config/models.py` | ADDED | スキーマ（dataclass + enum）|
| `core/business_config/loader.py` | ADDED | 読込・検証・クエリ（fail-closed）|
| `core/business_config/legacy_adapter.py` | ADDED | 既存設定を AST 静的読取（import/exec なし）|
| `core/business_config/comparator.py` | ADDED | SSOT↔Legacy 差分 → GO/FIX/STOP |
| `core/business_config/__init__.py` | ADDED | 公開 API |
| `scripts/business_config/validate_business_configs.py` | ADDED | 検証 CLI（exit 0/1/2/3）|
| `tests/business_config/*.py` | ADDED | Unit Test 47件 |
| `docs/YU_BUSINESS_OS_2_*.md`（5件）| MODIFIED | Phase B1 状況を役割別に追記 |

### 発見した既存の二重管理（Comparator が検出）

- 事業設定が 5 箇所に分散（`business_registry.py` / `_BUSINESS_CONFIGS` / `system_health.py` / `executive_team.py` / `entrypoint.py`）
- TACHINOMIYA 月商目標: `executive_team` 1,200,000 ≠ 正本 3,500,000
- `_BUSINESS_CONFIGS` に `ryukyu_hinabe` と重複する別名キー `hinabe`
- LINE トークン env 名が `business_registry.py` と `_BUSINESS_CONFIGS` で不一致（catering/tachinomiya/hinabe）

### Shadow Mode（本番未接続）

- 本番読込先は既存のまま（`business_registry.py` / `_BUSINESS_CONFIGS` を**削除も切替もしない**）
- 値の自動同期・自動上書きなし / `PRODUCTION_CONNECTED` なし（全事業 SHADOW_DEFINED）

### テスト実績

- `python3 -m unittest discover -s tests` → **Ran 142 tests OK**（47件追加）
- `python3 scripts/business_config/validate_business_configs.py` → **FIX（exit 1）**（実 legacy 乖離を正しく報告）
- `python3 scripts/registry/validate_registry.py` → GO（既存不変）/ `bash -n pr_auto_flow.sh` → OK
- Secret scan CLEAN / 外部通信ゼロ / AST 静的読取（exec/eval なし・import 副作用なし）

### 既存構成への影響チェック

- [x] 既存設定の削除・上書き・本番読込先切替：**なし**
- [x] Cloud Run / Scheduler / 外部送信 / GCS / Sheets：**なし**
- [x] `scripts/acquisition` / Tree Beauty / `daily_post_limit`：**未変更**
- [x] Secret 直書き：**なし**（env 名のみ）

### 人間承認が必要な項目

- Merge 実行（High → ゆうさん承認）/ Phase B2（本番接続）の開始可否

---

## Phase D-Lite 完了報告 — Governance Validator × PR Auto Flow 接続

| 項目 | 内容 |
|---|---|
| **ブランチ** | feat/yu-business-os-2-governance-pr-gate |
| **報告者** | Claude Code |
| **報告日** | 2026-07-11 |
| **リスク分類** | High（`core/**` `scripts/**` の変更を含む）|
| **売上直結度** | B（自動化ガバナンス強化・事故防止基盤）|

### 実装したファイル

| ファイル | 変更種別 | 概要 |
|---|---|---|
| `scripts/agent/governance_gate.py` | ADDED | ローカル diff アダプタ。diff収集→事実抽出→Validator呼出。exit 0/10/20/30/40 |
| `core/governance/diff_risk.py` | ADDED | ファイル→risk 分類・secret/runaway 検知（純関数・単一ソース）|
| `core/governance/validator.py` | MODIFIED | `pr_change_review` レビューアクションを追加 + `_norm` の `.env`/`.github` 判定バグ修正 |
| `scripts/agent/pr_auto_flow.sh` | MODIFIED | Step 0 に Governance Gate を接続（fail-closed）+ `emit_owner` 追加 |
| `tests/agent/test_governance_gate.py` | ADDED | ゲート 28 シナリオ + 統合テスト |
| `tests/governance/test_diff_risk.py` | ADDED | 分類器 単体テスト |
| `docs/AUTO_PR_FLOW.md` ほか docs 3件 | MODIFIED | Gate 実行位置・exit code・fail-closed を役割別に追記 |

### 接続方式（既存判定を重複させない）

- 決定ロジックは **Validator 一本**（gate は事実収集のみ）
- Shell は exit code だけ解釈（GO=0 / FIX=10 / OWNER=20 / STOP=30 / INTERNAL_ERROR=40）
- fail-closed: import/git/base-ref/unknown decision → INTERNAL_ERROR → STOP
- gh 非依存・GitHub API 不要・外部通信ゼロ

### テスト実績

- `python3 -m unittest discover -s tests` → **Ran 91 tests OK**（39件追加）
- `bash -n scripts/agent/pr_auto_flow.sh` → OK
- `python3 scripts/registry/validate_registry.py` → GO（exit 0・既存不変）
- Secret scan CLEAN（テスト fixture は実行時組み立てで自己検知を回避）

### 既存構成への影響チェック

- [x] 既存 pr_auto_flow.sh の gh ベース処理：**不変**（先頭に gate 追加のみ）
- [x] Cloud Run / Scheduler / 外部送信 / GCS / Sheets：**なし**
- [x] `scripts/acquisition` / Tree Beauty / `daily_post_limit`：**未変更**（gate が保護）
- [x] Secret 直書き：**なし**

### 人間承認が必要な項目

- Merge 実行（High リスク → ゆうさん最終承認）
- 次工程 Phase B の開始可否

---

## Phase A 完了報告 — YU Business OS 2.0 Registry & Governance 土台

| 項目 | 内容 |
|---|---|
| **ブランチ** | feat/yu-business-os-2-phase-a-registry-governance |
| **報告者** | Claude Code |
| **報告日** | 2026-07-11 |
| **リスク分類** | High（`core/**` `configs/**` `scripts/**` への追加を含む）|
| **売上直結度** | B（自動化・売却可能性を高める基盤。中長期）|

### 実装したファイル（すべて新規追加・既存の変更/削除/移動なし）

| ファイル | 変更種別 | 概要 |
|---|---|---|
| `configs/skills/registry.yaml` | ADDED | Skill Registry 10件（active 7 / inactive 3）|
| `configs/agents/registry.yaml` | ADDED | Agent Registry 9件（active 3 / inactive 6・全 default deny）|
| `configs/governance/policies.yaml` | ADDED | Governance Policy 21件 + リスク定義 |
| `core/registry/_yaml_min.py` | ADDED | 依存ゼロ YAML サブセットパーサ |
| `core/registry/models.py` | ADDED | dataclass + Enum（標準ライブラリのみ）|
| `core/registry/skill_registry.py` | ADDED | Skill Loader（fallback / path安全 / 重複検知）|
| `core/registry/agent_registry.py` | ADDED | Agent Loader（default deny / 参照整合）|
| `core/registry/__init__.py` | ADDED | 公開 API |
| `core/governance/validator.py` | ADDED | GO/FIX/STOP/OWNER_APPROVAL 判定（14段）|
| `core/governance/__init__.py` | ADDED | 公開 API |
| `scripts/registry/validate_registry.py` | ADDED | 整合性 CLI（exit 0/1/2）|
| `tests/registry/*.py`, `tests/governance/*.py` | ADDED | Unit Test 52件 |
| `docs/YU_BUSINESS_OS_2_*.md`（5件）| MODIFIED | Phase A 実装状況を役割別に追記 |

### 設計判断

- `config/` ではなく既存 `configs/` を採用（設計書「既存命名規約を優先」に一致）
- PyYAML / pytest 未インストール環境のため、YAML は内蔵パーサ・テストは stdlib `unittest`
- モデルは pydantic 未採用に合わせ標準ライブラリ dataclass

### テスト実績

- `python3 scripts/registry/validate_registry.py` → **RESULT: GO（exit 0）**
- `python3 -m unittest discover -s tests` → **Ran 52 tests OK**
- 検証済み: 外部通信ゼロ / Secret 出力ゼロ / SKILL.md 非実行 / path traversal 拒否 / default deny / 既存 namespace import 無破壊

### 既存構成への影響チェック

- [x] 既存ファイルの変更：**なし**（`docs/` 設計書追記のみ）
- [x] 既存 Agents / Skills / Knowledge の削除：**なし**
- [x] Cloud Run deploy / Scheduler 変更：**なし**（本番未接続）
- [x] 外部送信（LINE/Gmail/SNS）：**なし**
- [x] GCS / Sheets 書き込み：**なし**
- [x] `scripts/acquisition` 変更：**なし**
- [x] Tree Beauty 有効化 / `daily_post_limit` 変更：**なし**

### Secret混入チェック

- [x] APIキー・Secret の直書き：**なし**（secret scan clean）
- [x] `.env.local` の閲覧・変更：**なし**

### 人間承認が必要な項目

- Merge 実行（High リスク → ゆうさん最終承認）
- Phase B（設定二重管理の解消）の開始可否

---

## PR #5 完了報告 — TACHINOMIYA Google投稿ループ解消・画像向き修正

| 項目 | 内容 |
|---|---|
| **PR番号** | #5 |
| **ブランチ** | fix/tachinomiya-content-orientation |
| **報告者** | Claude Code |
| **報告日** | 2026-07-10 |
| **リスク分類** | High |
| **売上直結度** | A（Google投稿・SNS品質向上で30日以内に集客貢献） |

### 実装したファイル

| ファイル | 変更種別 | 概要 |
|---|---|---|
| `scripts/gen_content_3biz.py` | MODIFIED | TACHINOMIYAトピックを30件→90件に拡張・ループ解消。サーターアンダギー27/90=30.0%、昼間訴求強化 |
| `core/multi_business_content_engine.py` | MODIFIED | `_fetch_real_image`にImageOps.exif_transposeを追加（2行）。EXIF回転情報をピクセルに反映 |
| `scripts/gcs_beauty_batch.py` | MODIFIED | `_to_jpeg`にImageOps.exif_transposeを追加（2行）。BEAUTY画像GCS化の向き修正 |
| `scripts/gcs_tachinomiya_orientation_fix.py` | ADDED | TACHINOMIYA既存GCS画像の向き修正バッチ（手動実行専用）。--category/--limit/--idオプション付き |

### 修正内容の詳細

#### 1. TACHINOMIYA Google投稿ループ解消（gen_content_3biz.py）
- **問題**: TACHI 30件トピックが `i % 30` で循環し、90日分が3ループになっていた
- **修正**: TACHIを90件ユニークトピックに拡張。`i % 90 = i（i=0..89）`で全件ユニーク
- **サーターアンダギー**: 27/90件（30.0%）。昼間・午後・観光客向け訴求を重点配置
- **確認**: タイトル重複0件、本文重複0件

#### 2. Threads画像横向き修正（core/multi_business_content_engine.py, scripts/gcs_beauty_batch.py）
- **問題**: PIL.Image.open().convert("RGB")がEXIF向き情報を無視してピクセル展開
- **修正**: `ImageOps.exif_transpose()` を `.convert("RGB")` の前に追加
- **影響範囲**: TACHINOMIYA・CATERING・BEAUTY全事業の画像処理（既存ロジックは温存）

#### 3. 既存GCS画像向き修正スクリプト（scripts/gcs_tachinomiya_orientation_fix.py）
- **目的**: 既存のTACHINOMIYA GCS画像（横向き）を修正して再アップロードする
- **安全性**: 手動実行専用（Schedulerに未接続）。`--category BAR`等で小範囲テスト可能
- **実行方法**: `python3 scripts/gcs_tachinomiya_orientation_fix.py --category BAR --limit 5`

### 既存構成への影響チェック

- [x] 既存ファイルの変更：`core/multi_business_content_engine.py`（2行）・`scripts/gcs_beauty_batch.py`（2行）・`scripts/gen_content_3biz.py`（トピック拡張）
- [x] 既存 Agents / Skills / Knowledge の削除：**なし**
- [x] Scheduler変更：**なし**（Scheduler未接続のまま）
- [x] 自動送信：**なし**（すべて手動実行）
- [x] 本番GCS再アップロード：**未実行**（スクリプトは追加したが実行していない）
- [x] Tree Beauty有効化：**なし**

### Secret混入チェック

- [x] APIキー・Secret の直書き：**なし**（credentials.jsonはパス参照のみ）
- [x] `.env.local` の変更：**なし**
- [x] 顧客情報：**なし**

### テスト実績

- gen_content_3biz.py: Googleスプレッドシート直書きで90件ユニーク確認済み（タイトル重複0・本文重複0・サーターアンダギー27件）
- exif_transpose: PIL公式APIの標準的使用法。副作用なし
- gcs_tachinomiya_orientation_fix.py: dry-run未実施（本番実行前に `--limit 5` テスト推奨）

### 人間承認が必要な項目

- Merge実行（Highリスク → ゆうさん最終承認）
- `gcs_tachinomiya_orientation_fix.py` の本番実行（--category BAR --limit 5 からテスト開始推奨）

---

## TASK-001 完了報告

| 項目 | 内容 |
|---|---|
| **タスクID** | TASK-001 |
| **報告者** | Claude Code |
| **報告日** | 2026-07-08 |
| **PR番号** | （PR作成後に記入） |

### 実装したファイル

| ファイル | 変更種別 | 概要 |
|---|---|---|
| `CLAUDE.md` | 新規作成 | Claude Code 司令塔ルール・PRレビュー判定基準 |
| `AGENTS.md` | 新規作成 | Codex 実装部隊ルール・手順・禁止事項 |
| `TEAM_RULES.md` | 新規作成 | チーム全員共通ルール・フロー・ブランチ規則 |
| `TASK.md` | 新規作成 | 実装タスク指示テンプレート（TASK-001記入済み） |
| `REPORT.md` | 新規作成 | 実装完了報告テンプレート（このファイル） |
| `.github/pull_request_template.md` | 新規作成 | PRチェックリスト自動表示テンプレート |

### 既存構成への影響チェック

- [ ] 既存ファイルの変更：**なし**
- [ ] 既存 Agents / Skills / Knowledge の削除：**なし**
- [ ] `core/` `ceo/` `configs/` `skills/` への変更：**なし**

### Secret混入チェック

- [ ] APIキー・Secret の直書き：**なし**
- [ ] `.env.local` の変更：**なし**

### テスト

- ドキュメントのみの追加のため、自動テストなし
- 内容の整合性を目視確認済み

### 未解決事項・次タスク候補

なし

---

## 報告テンプレート（次回以降のコピー用）

```markdown
## TASK-XXX 完了報告

| 項目 | 内容 |
|---|---|
| **タスクID** | TASK-XXX |
| **報告者** | Codex |
| **報告日** | YYYY-MM-DD |
| **PR番号** | #XXX |

### 実装したファイル

| ファイル | 変更種別 | 概要 |
|---|---|---|

### 既存構成への影響チェック

- [ ] 既存ファイルの変更：
- [ ] 既存 Agents / Skills / Knowledge の削除：

### Secret混入チェック

- [ ] APIキー・Secret の直書き：
- [ ] `.env.local` の変更：

### テスト

### 未解決事項・次タスク候補
```
