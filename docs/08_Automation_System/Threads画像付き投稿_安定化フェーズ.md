# Threads 画像付き投稿 安定化フェーズ（2026/07/01 現在）

## 現在の成功状況

| 事業 | Threads投稿成功数 | 最終投稿日 | 画像付き | 状態 |
|------|-----------------|------------|---------|------|
| Catering | 2件 | 2026/07/01 | ✅ | 安定稼働中 |
| TACHINOMIYA | 2件以上 | 2026/07/01 | ✅ | 安定稼働中 |
| Beauty | 0件 | - | ❌ | 画像不足 |
| 琉球火鍋 | 0件 | - | ❌ | 画像不足 |

## まだ自動ONにしない理由

1. Scheduler ON条件 15項目のうち未達成あり（→ Scheduler_ON条件.md 参照）
2. LINEアラート未実装（投稿失敗を検知できない）
3. 重複投稿防止ロジック未実装
4. IMAGE_LIBRARY に gcs_public_url カラムなし（毎回再アップロード発生）
5. Beauty / 琉球火鍋の IMAGE_LIBRARY 画像が 0 件

## IMAGE_LIBRARY 改善内容（2026/07/01）

### 追加するカラム（22列）

現状 16列 → 改善後 38列

| # | カラム名 | 用途 |
|---|---------|------|
| 17 | gcs_public_url | GCS 公開 URL（再利用で再アップロード不要） |
| 18 | gcs_path | GCS 内パス |
| 19 | business_key | 事業キー（catering/tachinomiya/beauty/ryukyu_hinabe） |
| 20 | image_usage | 用途メモ |
| 21 | content_type | image/jpeg or image/png |
| 22 | file_size_bytes | バイト数 |
| 23 | file_size_mb | MB表示 |
| 24 | width | 横幅px |
| 25 | height | 縦幅px |
| 26 | is_public_url_valid | URLアクセス可否（TRUE/FALSE） |
| 27 | http_status | HTTP応答コード（200/403/404等） |
| 28 | usage_status | active/ng/pending |
| 29 | needs_compression | 3MB超 → TRUE |
| 30 | compression_status | pending/done/skip |
| 31 | can_use_for_threads | Threads 使用可否 |
| 32 | can_use_for_instagram | Instagram 使用可否 |
| 33 | ng_reason | NG理由 |
| 34 | quality_score | 品質スコア 1-5 |
| 35 | brand_fit_score | ブランド適合 1-5 |
| 36 | updated_at | 最終更新日時 |
| 37 | last_post_url | 最終投稿URL |
| 38 | last_post_id | 最終投稿ID |

### GCS URL 再利用設計

```
投稿時フロー（改善後）：
1. select_real_image() → IMAGE_LIBRARY から候補取得
2. selected['gcs_public_url'] が空でない → そのまま使用（GCSアップロードなし）
3. gcs_public_url が空 → Drive DL → GCS アップロード → IMAGE_LIBRARY に保存
```

## 次回実行手順

1. IMAGE_LIBRARY改善コミットの承認（ゆうさんの YES/NO）
2. `/add-image-library-columns` エンドポイントで列追加実行
3. TACHINOMIYA 3件目の投稿（Scheduler ON条件達成）
4. Catering 3件目の投稿（Scheduler ON条件達成）
5. LINE アラート実装
6. Scheduler ON 判断
