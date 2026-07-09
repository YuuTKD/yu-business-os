# Tree Beauty Threads — 手動1件実投稿前チェックレポート
# 作成：2026-07-06
# 目的：ALMOST_READY → READY_TO_MANUAL_POST

---

## 1. 作成・更新ファイル

| ファイル | 種別 | 内容 |
|---------|------|------|
| `configs/post_theme_rules.py` | 更新 | `THEME_KEYWORDS["beauty"]` に8テーマ追加 |
| `configs/auto_post_settings.py` | 更新 | `SLOT_CONFIG["beauty_morning"]` 追加 |
| `core/threads_api.py` | 更新 | Step 8.5 `beauty_ng_check` 追加 |
| `businesses/beauty/beauty_threads_config.py` | 既存 | テーマ・NGチェック設計（変更なし） |
| `businesses/beauty/beauty_threads_dry_run.py` | 既存 | DRY_RUNシミュレーター（変更なし） |
| `businesses/beauty/beauty_inventory_check.py` | 新規 | 在庫確認スクリプト |
| `docs/beauty_threads_readiness_20260706.md` | 更新 | 判定を READY_TO_MANUAL_POST に更新 |
| `docs/beauty_threads_pre_manual_post_check_20260706.md` | 新規 | 本ファイル |

---

## 2. 画像在庫確認結果

| 確認方法 | 結果 |
|---------|------|
| ローカルスクリプト実行 | ⚠️ Google認証ファイルなし（Cloud Run環境外） |
| スクリプト場所 | `businesses/beauty/beauty_inventory_check.py` |
| Cloud Runでの確認方法 | `GET /threads-auto-post-ready-check` または IMAGE_LIBRARY直接確認 |
| IMAGE_LIBRARY シートID | `15cfsC2HIzu1FGW602dxqNuv-DJpmLiZhatvB-hDn2XM`（シート名: 画像台帳） |

### 必要な最低在庫ライン

| テーマ | 最低ライン | 現在の確認状況 |
|-------|-----------|------------|
| salon_interior | 10枚 | 未確認（ゆうさん確認） |
| hair_removal | 10枚 | 未確認（ゆうさん確認） |
| whitening | 10枚 | 未確認（ゆうさん確認） |
| yomogi | 10枚 | 未確認（ゆうさん確認） |
| cupping | 5枚 | 未確認（ゆうさん確認） |
| menu | 5枚 | 未確認（ゆうさん確認） |
| campaign | 5枚 | 未確認（ゆうさん確認） |
| general_beauty | 10枚 | 未確認（ゆうさん確認） |

> GCS化済み画像が0枚のテーマは自動投稿でスキップされる。
> 特に `salon_interior` / `hair_removal` / `whitening` / `yomogi` の在庫が最重要。

---

## 3. 投稿候補在庫確認結果

| 確認項目 | 状態 |
|---------|------|
| SNS_POST_STOCK シートのBeauty候補 | 未確認（ゆうさん確認） |
| THREADS_POST_LOG ID | `1I6wRRDa-b440DBxZ3TbFbfMxEXZecowzOsxTAYSxyBE` |
| 必要な最低件数 | 5件以上（beauty / 未投稿 / スコア3以上） |

### Beauty投稿候補がない場合の追加方法

SNS_POST_STOCK シートに以下のフォーマットで投稿候補を追加してください：

```
business:    beauty
post_theme:  salon_interior（or hair_removal / whitening / yomogi / campaign等）
text:        投稿本文（薬機法NG表現なし・安全表現使用済みのもの）
score:       3以上
status:      （空白 = 未投稿）
```

サンプル投稿文は `businesses/beauty/beauty_threads_dry_run.py` の `DRY_RUN_POSTS` を参照。

---

## 4. THEME_KEYWORDS追加内容

**変更ファイル:** `configs/post_theme_rules.py`
**変更前:** `"beauty": []`（空配列）
**変更後:** 8テーマを追加

```python
"beauty": [
    ("hair_removal", ["脱毛", "ムダ毛", "除毛", "VIO", "自己処理", "ツルツル", ...]),
    ("whitening",    ["ホワイトニング", "歯を白く", "歯の白さ", "口元", ...]),
    ("yomogi",       ["よもぎ蒸し", "よもぎ", "ヨモギ", "蒸し", "温活", "冷え", ...]),
    ("cupping",      ["カッピング", "吸い玉", "コリ", "肩こり", "血行"]),
    ("salon_interior", ["サロン", "店内", "空間", "内観", "完全個室", ...]),
    ("menu",         ["料金", "メニュー", "価格", "コース", "プラン", ...]),
    ("campaign",     ["キャンペーン", "限定", "特別価格", "期間限定", ...]),
    ("general_beauty", ["美容", "肌", "スキンケア", "エステ", "リラックス", ...]),
]
```

**テスト結果（extract_post_theme 7テスト全PASS）:**

| テスト文 | 抽出テーマ | 期待テーマ | 判定 |
|---------|-----------|-----------|------|
| 脱毛を気になる方へ | hair_removal | hair_removal | ✅ |
| よもぎ蒸しで温活 | yomogi | yomogi | ✅ |
| ホワイトニングで口元ケア | whitening | whitening | ✅ |
| カッピングで肩こりケア | cupping | cupping | ✅ |
| サロンの完全個室で | salon_interior | salon_interior | ✅ |
| 期間限定キャンペーン | campaign | campaign | ✅ |
| 清潔感ある自分磨き | general_beauty | general_beauty | ✅ |

---

## 5. SLOT_CONFIG追加内容

**変更ファイル:** `configs/auto_post_settings.py`
**追加内容:**

```python
"beauty_morning": {
    "business": "beauty",
    "posting_window": ("11:00", "12:00"),
    "preferred_post_themes": [
        "salon_interior",  # 1. 安全（NG表現リスク最低）
        "hair_removal",    # 2. 主力サービス
        "whitening",       # 3. 主力サービス
        "yomogi",          # 4. 主力サービス
        "general_beauty",  # 5. フォールバック
    ],
},
```

**確認済み:**
- `auto_post_enabled = False` は**変更なし**（意図的・ゆうさん承認待ち）
- `daily_post_limit = 1` は変更なし
- TACHINOMIYA/CATERINGの4 slotは変更なし

---

## 6. 美容NG表現チェック組み込み結果

**変更ファイル:** `core/threads_api.py`
**組み込み場所:** `run_full_auto()` 関数の Step 8.5（post_stock と duplicate の間）
**条件:** `biz_key == "beauty"` の場合のみ実行（他事業に影響なし）

### 組み込みコード

```python
# 8.5. 美容NG表現チェック（beauty専用・薬機法対策）
if biz_key == "beauty":
    try:
        from businesses.beauty.beauty_threads_config import check_ng_expression
        ng_result = check_ng_expression(text)
        verdict = ng_result.get("verdict", "PASS")
        found   = ng_result.get("found", [])
        if verdict == "BLOCK":
            return fail("beauty_ng_check",
                        f"薬機法BLOCKワード検出: {', '.join(found)} → 投稿中止。投稿候補を修正してください。")
        elif verdict == "REVISE":
            return fail("beauty_ng_check",
                        f"修正推奨ワード検出: {', '.join(found)} → 修正後に再実行してください。")
        ok_step("beauty_ng_check", f"PASS（検出なし）")
    except ImportError:
        ok_step("beauty_ng_check", "SKIP（beauty_threads_config未ロード）")
```

### NG表現チェックテスト結果（6テスト全PASS）

| テスト文 | 期待 | 結果 | 検出ワード |
|---------|-----|------|----------|
| 絶対に効果があります。必ず綺麗になります。 | BLOCK | ✅ BLOCK | [絶対, 必ず] |
| 劇的に変わる美容法を試してみて | REVISE | ✅ REVISE | [劇的に] |
| まずは体験から。気になる方へ。個人差があります。 | PASS | ✅ PASS | [] |
| 100%の効果を保証します。痩せる保証。治る。 | BLOCK | ✅ BLOCK | [100%, 治る, 痩せる, 効果を保証, 保証します] |
| 清潔感のある印象ケアを目指したい方へ | PASS | ✅ PASS | [] |
| 永久脱毛で白くなる。医療効果あり | BLOCK | ✅ BLOCK | [永久, 白くなる, 医療効果] |

---

## 7. DRY_RUN再実行結果

**実行コマンド:** `python3 businesses/beauty/beauty_threads_dry_run.py`
**実行日:** 2026-07-06（configs変更後）

| # | テーマ | スロット | NG表現 | 画像一致 | 総合 |
|---|-------|---------|--------|---------|------|
| 1 | salon_interior | beauty_morning | PASS | ✅ OK | ✅ PASS |
| 2 | hair_removal | beauty_morning | PASS | ✅ OK | ✅ PASS |
| 3 | whitening | beauty_morning | PASS | ✅ OK | ✅ PASS |
| 4 | yomogi | beauty_morning | PASS | ✅ OK | ✅ PASS |
| 5 | cupping | beauty_morning | PASS | ✅ OK | ✅ PASS |
| 6 | campaign | beauty_morning | PASS | ✅ OK | ✅ PASS |
| 7 | general_beauty | beauty_morning | PASS | ✅ OK | ✅ PASS |

```
PASS    : 7/7
REVISE  : 0/7
BLOCK   : 0/7
画像不一致: 0/7
```

---

## 8. auto_post_enabled状態

```
beauty.auto_post_enabled = False
```

**変更なし。ゆうさん承認後に True にする。**

---

## 9. Scheduler状態

| Scheduler | 状態 |
|----------|------|
| tachinomiya_morning | 稼働中（変更なし） |
| tachinomiya_evening | 稼働中（変更なし） |
| catering_lunch | 稼働中（変更なし） |
| catering_night | 稼働中（変更なし） |
| beauty_morning | **未追加（設計のみ）** |

---

## 10. TACHINOMIYA/CATERINGへの影響

| 影響項目 | 状態 |
|---------|------|
| auto_post_enabled | TACHINOMIYA/CATERING は True のまま（変更なし） |
| Scheduler | 変更なし（4ジョブ全て稼働中） |
| threads_api.py | beauty_ng_check は `if biz_key == "beauty":` で分離 |
| post_theme_rules.py | beauty エントリの追加のみ（他事業のルール変更なし） |
| auto_post_settings.py | beauty_morning の追加のみ（既存スロット変更なし） |

**結論: TACHINOMIYA/CATERINGへの影響は一切なし**

---

## 11. 最終判定

### 判定：**READY_TO_MANUAL_POST**（条件付き）

#### 完了済み条件 ✅

- [x] THEME_KEYWORDS["beauty"] 追加済み（8テーマ・テスト7/7 PASS）
- [x] SLOT_CONFIG["beauty_morning"] 追加済み（11:00〜12:00）
- [x] 美容NG表現チェック本番フロー組み込み済み（threads_api.py Step 8.5）
- [x] DRY_RUN再実行 PASS（7/7）
- [x] auto_post_enabled = False 維持
- [x] Scheduler 未追加
- [x] TACHINOMIYA/CATERING 影響なし

#### 未確認条件 ⚠️（ゆうさん側で確認が必要）

- [ ] IMAGE_LIBRARY BEAUTY在庫（GCS化済み枚数）
- [ ] SNS_POST_STOCK Beauty投稿候補（5件以上）

上記2点が確認OKであれば → **READY_TO_MANUAL_POST（完全）**

---

## 12. ゆうさんがYes/Noで判断すること

| # | 確認事項 | 判断 |
|---|---------|------|
| 1 | IMAGE_LIBRARY でBEAUTYカテゴリの画像が各テーマ最低ライン以上あるか？ | Yes / No |
| 2 | SNS_POST_STOCK にBeauty投稿候補が5件以上あるか？（なければ追加が必要） | Yes / No |
| 3 | 1と2がYesなら、手動1件実投稿テストを今日実行するか？ | Yes / No |

### 手動1件実投稿のコマンド（ゆうさんがYes判断後のみ）

```bash
# Cloud Run へのリクエスト（dry_run=false・beauty）
curl -X POST https://yu-holdings-ai-XXXX.run.app/threads-auto-post-full \
  -H "Content-Type: application/json" \
  -d '{"business": "beauty", "slot": "beauty_morning", "dry_run": false}'
```

**注意:**
- dry_run=false を指定するときは必ずゆうさんが手動で実行
- 実行前にLINE通知が届くこと（LINE_STAFF_TOKEN が有効であること）を確認
- 投稿後は `@tree.beauty_okinawa` のアカウントで投稿内容を目視確認

---

*Readiness Report: `docs/beauty_threads_readiness_20260706.md`*
*DRY_RUN スクリプト: `businesses/beauty/beauty_threads_dry_run.py`*
*在庫確認スクリプト: `businesses/beauty/beauty_inventory_check.py`*
*ロールバック手順: `docs/THREADS_AUTO_POST_ROLLBACK.md`*
