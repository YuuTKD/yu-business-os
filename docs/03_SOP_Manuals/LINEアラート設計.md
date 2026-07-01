# Threads 投稿 LINE アラート設計

作成日: 2026/07/01  
ステータス: 設計完了・実装待ち

## 通知が必要なケース（12種）

| # | アラートタイプ | severity | 送信タイミング |
|---|-------------|---------|--------------|
| 1 | Threads投稿成功 | INFO | 投稿後即時 |
| 2 | Threads投稿失敗 | ERROR | 失敗時即時 |
| 3 | 画像URLエラー | WARNING | 投稿試行時 |
| 4 | username不一致 | CRITICAL | 検知即時 |
| 5 | token期限切れ/認証エラー | ERROR | 認証失敗時 |
| 6 | 投稿候補なし | WARNING | Scheduler実行時 |
| 7 | 画像候補なし | WARNING | 画像選定時 |
| 8 | 低品質候補のみ | WARNING | 候補評価時 |
| 9 | 重複投稿検出 | WARNING | 重複チェック時 |
| 10 | Cloud Runエラー | CRITICAL | 例外発生時 |
| 11 | Scheduler実行失敗 | ERROR | Scheduler起動時 |
| 12 | シート更新失敗 | ERROR | 書き戻し失敗時 |

## LINE 通知メッセージ案

### 1. 投稿成功
```
【✅ Threads投稿成功】
事業：{business_name}
投稿URL：{permalink}
画像：{image_filename}（{category}）
文字数：{text_length}字
次回インサイト取得：翌日以降
```

### 2. 投稿失敗
```
【❌ Threads投稿失敗】
事業：{business_name}
原因：{error_message}
投稿候補ID：{post_candidate_id}
対応：SNS_POST_STOCKの当該行を確認してください
再実行可否：手動で dry_run=false を再実行
```

### 3. 画像URLエラー
```
【⚠️ 画像URLエラー】
事業：{business_name}
画像ID：{image_id}
URL：{image_url}
HTTP状態：{http_status}
対応：IMAGE_LIBRARYの当該行を確認してください
```

### 4. username不一致（最重要）
```
【🚨 username不一致 - 即確認】
事業：{business_name}
期待username：{expected}
実際のusername：{actual}
対応：投稿を中止しました。Threads OAuth を再確認してください。
```

### 5. token期限切れ
```
【🔑 Threads token期限切れ】
事業：{business_name}
有効期限：{expires_at}
対応：/threads-oauth/{biz_key} でトークン更新してください
```

### 6. 投稿候補なし
```
【📭 投稿候補なし】
事業：{business_name}
SNS_POST_STOCKに「未投稿」の Threads 行がありません。
対応：新しい投稿候補をSNS_POST_STOCKに追加してください。
```

### 7. 画像候補なし
```
【🖼️ 画像候補なし - テキスト投稿に移行しません】
事業：{business_name}
IMAGE_LIBRARYに使用可能な画像がありません。
対応：Drive フォルダに写真を追加して /scan-drive-images を実行
```

## 必要なログ項目（THREADS_ALERT_LOG シート）

| カラム | 説明 |
|-------|------|
| alert_type | success/image_error/username_mismatch/token_expired等 |
| business_key | catering/tachinomiya/beauty/ryukyu_hinabe |
| severity | INFO/WARNING/ERROR/CRITICAL |
| message | 通知メッセージ本文 |
| error_detail | スタックトレースまたは詳細エラー |
| post_candidate_id | 投稿候補の行番号またはpost_no |
| image_id | IMAGE_LIBRARY の画像ID |
| post_url | 投稿後の permalink |
| sent_at | 通知送信日時 |
| status | sent/failed |
| resolved_at | 解決日時（手動入力） |

## 実装方針

### 送信先
- LINE STAFF チャンネル（OWNER_ONLY ルーム）
- severity=CRITICAL は即時送信
- severity=INFO は日次サマリーで可

### 実装場所
- `core/threads_auto_post.py` → `run()` 内で投稿後/失敗後に呼ぶ
- `core/line_alert.py` (新規作成) → `send_threads_alert(alert_type, biz_key, **kwargs)`

### 実装時の注意
- LINE token は環境変数から取得（ソースに書かない）
- 通知失敗でも投稿フローは継続（アラート失敗が投稿を止めない）
- THREADS_ALERT_LOG への記録は通知送信の前後どちらでも可
