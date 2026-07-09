# Tree Beauty Threads自動投稿 — Readiness Report
# 作成：2026-07-06
# 最終更新：2026-07-06（STEP 3〜6実装後）
# 判定者：Claude Code
# 実投稿判断：ゆうさん承認後

---

## 判定：**READY_TO_MANUAL_POST**（条件付き）

| 確認項目 | 状態 | 詳細 |
|---------|------|------|
| `auto_post_enabled` | **False** ✅ | 変更禁止中 |
| `daily_post_limit` | **1** ✅ | 変更なし |
| Threadsアカウント | `tree.beauty_okinawa` ✅ | 変更なし |
| THEME_KEYWORDS["beauty"] | **✅ 追加済み** | 8テーマ・7テスト全PASS |
| SLOT_CONFIG["beauty_morning"] | **✅ 追加済み** | 11:00〜12:00 |
| 美容NG表現チェック組み込み | **✅ 本番フロー組み込み済み** | threads_api.py Step 8.5 |
| DRY_RUN再実行 | **✅ 7/7 PASS** | REVISE:0 / BLOCK:0 |
| Scheduler | **未追加 ✅** | 設計のみ（未デプロイ） |
| TACHINOMIYA/CATERING影響 | **なし ✅** | 変更なし |
| IMAGE_LIBRARY BEAUTY在庫 | **⚠️ 未確認** | Cloud Run環境で確認が必要 |
| SNS_POST_STOCK Beauty候補 | **⚠️ 未確認** | Cloud Run環境で確認が必要 |
| LINE通知先 | LINE_STAFF_TOKEN（暫定） | LINE_BEAUTY_DESTINATION専用変数なし |

---

## 現状確認サマリー（STEP 1）

| 確認項目 | 値 | 状態 |
|---------|-----|------|
| `configs/auto_post_settings.py` beauty設定 | 存在 | ✅ |
| `beauty.auto_post_enabled` | **False** | ✅ 安全（ONにするな） |
| `beauty.daily_post_limit` | **1** | ✅（薬機法リスク考慮） |
| `beauty.posting_window` | **(10:00, 12:00)** | ✅ |
| Threadsアカウント設定 | `EXPECTED_USERNAME["beauty"] = "tree.beauty_okinawa"` | ✅ |
| LINE通知先（beauty専用変数） | **`LINE_BEAUTY_DESTINATION` は未設定** | ⚠️ 要確認 |
| LINE代替通知先 | `LINE_STAFF_TOKEN`（値非表示） | △ 暫定可 |
| Tree Beauty画像在庫（GCS化済み枚数） | **未確認（Cloud Run環境で確認必要）** | ⚠️ |
| `configs/post_theme_rules.py` beauty | `THEME_KEYWORDS["beauty"]` **8テーマ追加済み** | ✅ |
| `configs/auto_post_settings.py` SLOT_CONFIG | **beauty_morning 追加済み** | ✅ |
| 美容NG表現チェック | `check_ng_expression` **本番フロー組み込み済み** | ✅ |
| 既存Scheduler | Tree Beautyの他ジョブはあり。Threads専用ジョブ**なし** | ✅（追加禁止中） |
| TACHINOMIYA/CATERINGへの影響 | **なし**（auto_post_enabled=Falseのまま） | ✅ 安全 |

---

## フォルダ名 → テーマ対応表（STEP 2-3）

| Driveフォルダ名（カテゴリ） | テーマキー | 備考 |
|--------------------------|-----------|------|
| 脱毛 | `hair_removal` | STRONGテーマ |
| セルフホワイトニング / ホワイトニング | `whitening` | STRONGテーマ |
| よもぎ蒸し / よもぎ | `yomogi` | STRONGテーマ |
| カッピング | `cupping` | STRONGテーマ（将来追加） |
| 店舗内観 / 店舗外観 / 内観 / 外観 / 店内 | `salon_interior` | 安全テーマ |
| スタッフ | `staff` | 安全テーマ |
| メニュー / 料金表 / POP | `menu` | 安全テーマ |
| キャンペーン / 特典 | `campaign` | 安全テーマ |
| ビフォーアフター | `general_beauty` | 薬機法注意→general扱い |
| お客様の声 | `general_beauty` | 口コミ内容確認後のみ |

---

## allowed / blocked 設計（STEP 4）

| テーマ | allowed | blocked |
|-------|---------|---------|
| `hair_removal` | hair_removal, general_beauty, campaign | whitening, yomogi, cupping, menu |
| `whitening` | whitening, general_beauty, campaign | hair_removal, yomogi, cupping |
| `yomogi` | yomogi, general_beauty, campaign | hair_removal, whitening, cupping |
| `cupping` | cupping, general_beauty, campaign | hair_removal, whitening, yomogi |
| `salon_interior` | salon_interior, general_beauty, staff | hair_removal, whitening, yomogi, cupping |
| `staff` | staff, salon_interior, general_beauty | hair_removal, whitening, yomogi, cupping |
| `menu` | menu, campaign, general_beauty | hair_removal, whitening, yomogi, cupping |
| `campaign` | campaign, menu, general_beauty | （制限なし） |
| `general_beauty` | general_beauty, salon_interior | （制限なし） |

---

## 美容NG表現チェック（STEP 5）

### BLOCKワード（含んだら自動投稿禁止）

```
絶対 / 必ず / 100% / 永久 / 完全に / 確実に
治る・治ります・治った / 改善する・改善します・改善しました
痩せる・痩せます・痩せました / 小顔になる・小顔になります
白くなる（断定） / 効果を保証・効果が保証・保証します
医学的に / 医療効果 / 病気を治 / 症状が改善
Before/After / ビフォーアフター保証 / 個人差なし / 誰でも必ず
不安にさせる / コンプレックスを解消できる（断定）
```

### REVISEワード（修正すれば投稿可）

```
効果あり → 「効果を感じる方も」
かならず → 削除
ぐんぐん・劇的に・みるみる・すごく効く → 削除
完璧な / 理想の体型に（断定） → 「目指したい方へ」
コンプレックスを治す → 「ケアしたい方へ」
```

---

## 文章×画像一致チェック（STEP 6）

threads_api.py Step 13（theme_match）に統合済み。beauty専用 Step 8.5（beauty_ng_check）追加済み。

---

## 残り画像枚数通知設計（STEP 7）

| テーマ | 最低在庫ライン | 通知定義 |
|-------|-------------|---------|
| salon_interior | 10枚 | 0:🚨緊急 / 1〜3:⚠️即補充 / 4〜5:📷今週中 / 6以上:通常 |
| hair_removal | 10枚 | 同上 |
| whitening | 10枚 | 同上 |
| yomogi | 10枚 | 同上 |
| cupping | 5枚 | 同上 |
| menu | 5枚 | 同上 |
| campaign | 5枚 | 同上 |
| general_beauty | 10枚 | 同上 |

---

## LINE通知設計（STEP 8）

- 成功/失敗通知フォーマット: `businesses/beauty/beauty_threads_config.py`
- 通知先: `LINE_STAFF_TOKEN`（`LINE_BEAUTY_DESTINATION` 専用変数は未設定）

---

## Scheduler設計案（STEP 9）

| 項目 | 値 |
|-----|-----|
| job_name | `beauty-threads-morning` |
| cron | `0 11 * * *`（毎朝11:00 JST） |
| status | **NOT_DEPLOYED**（ゆうさん承認後のみ追加） |

`SLOT_CONFIG["beauty_morning"]` に slot設定済み（auto_post_settings.py）。

---

## DRY_RUN再実行結果（STEP 10）

**実行日: 2026-07-06（configs変更後）**

| # | テーマ | NG表現 | 画像一致 | 総合 |
|---|-------|--------|---------|------|
| 1 | salon_interior | PASS | ✅ OK | ✅ PASS |
| 2 | hair_removal | PASS | ✅ OK | ✅ PASS |
| 3 | whitening | PASS | ✅ OK | ✅ PASS |
| 4 | yomogi | PASS | ✅ OK | ✅ PASS |
| 5 | cupping | PASS | ✅ OK | ✅ PASS |
| 6 | campaign | PASS | ✅ OK | ✅ PASS |
| 7 | general_beauty | PASS | ✅ OK | ✅ PASS |

**結果：7/7 PASS / REVISE: 0 / BLOCK: 0 / 画像不一致: 0**

---

## Readiness判定（STEP 11）

### 判定：**READY_TO_MANUAL_POST**（条件付き）

残る確認事項（ゆうさん側で確認が必要）:
1. IMAGE_LIBRARY のBEAUTY在庫（GCS化済み枚数確認）
2. SNS_POST_STOCK のBeauty投稿候補5件以上確認

上記2点が確認OKならば → 手動1件実投稿テスト可

---

## pre-deploy-qa（STEP 12）

### 実装済みの変更

| ファイル | 変更内容 | 状態 |
|---------|---------|------|
| `configs/post_theme_rules.py` | `THEME_KEYWORDS["beauty"]` に8テーマ追加 | ✅ 実装済み |
| `configs/auto_post_settings.py` | `SLOT_CONFIG["beauty_morning"]` 追加 | ✅ 実装済み |
| `core/threads_api.py` | Step 8.5 beauty_ng_check 追加（beauty専用） | ✅ 実装済み |
| `businesses/beauty/beauty_threads_config.py` | 全テーマ・NG表現チェック設計 | ✅ 既存 |
| `businesses/beauty/beauty_threads_dry_run.py` | DRY_RUNシミュレーター | ✅ 既存 |
| `businesses/beauty/beauty_inventory_check.py` | 在庫確認スクリプト | ✅ 追加済み |

### 禁止事項チェック

| 禁止事項 | 状態 |
|---------|------|
| Scheduler追加 | ✅ 禁止（設計のみ） |
| beauty auto_post_enabled=True | ✅ 禁止（Falseのまま） |
| 実投稿 | ✅ 禁止（DRY_RUNのみ） |
| TACHINOMIYA/CATERING変更 | ✅ 触れていない |
| Secret/Token表示 | ✅ 表示なし |
| 既存画像/ログ/列削除 | ✅ 削除なし |

---

## TACHINOMIYA/CATERINGへの影響

**影響：なし**

- beauty.auto_post_enabled = False のまま
- TACHINOMIYA/CATERINGのScheduler（4本）は変更なし
- threads_api.py の beauty_ng_check は `if biz_key == "beauty":` で完全分離

---

## ゆうさんがYes/Noで判断すること

| # | 確認事項 | 推奨 | 状態 |
|---|---------|------|------|
| 1 | IMAGE_LIBRARY BEAUTYカテゴリのGCS化済み画像数を確認（脱毛/ホワイト/よもぎ各10枚以上か） | **確認推奨** | ⚠️ 要確認 |
| 2 | SNS_POST_STOCK にBeauty投稿候補が5件以上あるか確認 | **確認推奨** | ⚠️ 要確認 |
| 3 | 上記1・2がOKなら手動1件実投稿テストを実行するか（dry_run=False・slot=beauty_morning） | **ゆうさん判断** | 未着手 |
| 4 | 実投稿1件正常完了後、Scheduler追加するか | **ゆうさん承認後のみ** | 未着手 |
| 5 | `LINE_BEAUTY_DESTINATION` 専用変数を設定するか（なければ `LINE_STAFF_TOKEN` で代替可） | 要確認 | ⚠️ |

---

*設計ファイル: `businesses/beauty/beauty_threads_config.py`*
*DRY_RUN: `businesses/beauty/beauty_threads_dry_run.py`*
*在庫確認: `businesses/beauty/beauty_inventory_check.py`*
*ロールバック: `docs/THREADS_AUTO_POST_ROLLBACK.md`*
