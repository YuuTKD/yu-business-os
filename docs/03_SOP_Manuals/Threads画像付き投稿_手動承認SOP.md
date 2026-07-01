# Threads 画像付き投稿 手動承認 SOP

## 目的

Scheduler 自動化の前段階として、手動で投稿候補を確認・承認して投稿する。

## 実行手順

### Step 1: 投稿候補確認（dry_run）

```bash
curl -X POST https://yu-holdings-ai-qpiiccdspa-an.a.run.app/threads-auto-post \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true}'
```

確認ポイント:
- `pending_count` が 1 以上
- `has_image: true` であること
- `business` が catering または tachinomiya であること

### Step 2: 候補の内容確認

- 本文が 60 文字以上か
- NGワード含まないか（求人/採用/スタッフ募集/テスト/仮/ダミー）
- 前回投稿と内容が重複していないか
- 画像 URL が GCS または HTTPS であること

### Step 3: 承認投稿

```bash
curl -X POST https://yu-holdings-ai-qpiiccdspa-an.a.run.app/threads-auto-post \
  -H "Content-Type: application/json" \
  -d '{"dry_run": false, "max_per_biz": 1}'
```

### Step 4: 投稿確認

- レスポンスの `ok: true` を確認
- `permalink` を Threads アプリで確認
- SNS_POST_STOCK の status が「投稿済み」に更新されているか確認

### Step 5: 翌日インサイト確認

```bash
curl https://yu-holdings-ai-qpiiccdspa-an.a.run.app/threads-auto-post-status
```

## NGチェックリスト

投稿前に以下を確認:

- [ ] 本文が 60 文字以上
- [ ] image_url が HTTPS で始まる
- [ ] business が ALLOWED_BIZ に含まれる
- [ ] 直近 3 投稿と本文が重複しない
- [ ] NGワードなし
- [ ] username が EXPECTED_USERNAME と一致（システムが自動確認）

## エラー時の対応

| エラー | 対応 |
|--------|------|
| username mismatch | 即座に停止。Threads OAuth 再確認 |
| image_url not HTTPS | image_url を修正してから再実行 |
| token expired | THREADS_ACCOUNT_CONFIG のトークン更新 |
| GCS upload failed | Drive 画像を確認。別画像を指定 |
