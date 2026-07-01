# IMAGE_LIBRARY 運用 SOP

## 基本ルール

### 画像登録（スキャン）

```bash
# Drive フォルダをスキャンして IMAGE_LIBRARY に登録
POST /scan-drive-images
Body: {"business": "catering", "dry_run": true}
```

### 画像品質基準

| 項目 | 基準 |
|------|------|
| 推奨サイズ | 1MB 以下 |
| 許容上限 | 3MB 未満 |
| 要圧縮 | 3MB 以上 |
| ファイル形式 | JPEG / PNG のみ |
| Threads 推奨解像度 | 1:1（正方形）または 4:5 |

### GCS URL 再利用ルール

- `gcs_public_url` が空でない → そのまま使用（再アップロードしない）
- `gcs_public_url` が空 → GCS アップロード後に IMAGE_LIBRARY に保存
- HTTP ステータスが 200 以外 → 使用不可（`usage_status = ng`）

### 使用禁止条件

- `can_use_for_threads = FALSE`
- `usage_status = ng`
- `http_status ≠ 200`
- `content_type` が image/jpeg・image/png 以外
- `ng_reason` に記入あり

## 圧縮ルール

| サイズ | 対応 |
|--------|------|
| 1MB以下 | そのまま使用 |
| 1-3MB | 使用可能（PIL で JPEG quality=85 で変換） |
| 3MB以上 | `needs_compression = TRUE` → 手動確認後に圧縮 |
| 人物の顔が大きい写真 | 使用前にゆうさん確認 |

## 画像選定優先順位

1. `use_count = 0`（未使用）の画像
2. `last_used_at` が古い画像
3. カテゴリが投稿テーマと一致
4. `quality_score` が高い

## 事業別フォルダ

| 事業 | Drive フォルダID | カテゴリ |
|------|----------------|---------|
| CATERING | 1pXpdO5PiSuIt6NCH1ROPFmRnn4IQItqe | ケータリング/オードブル/会議用弁当/法人利用/イベント |
| TACHINOMIYA | 12lC9_S6Q_hV4tQ9THcy689YjFC-Vn9Us | フード/サーターアンダギー/ドリンク/BAR/店舗 |
| BEAUTY | 1KwoeBNTiN8jnmuBIBvz2D80xFnwxi2gu | 脱毛/ホワイトニング/よもぎ蒸し/店舗内観 |
| HINABE | 1owSjoNNgAS6vPhr9rVHI7tD4hloBLmdL | 火鍋/食材/店舗/コース |
