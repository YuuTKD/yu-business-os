# App Review 申請前チェックリスト

> このチェックリストをすべてチェックしてから申請してください。
> 更新日: 2026-06-21

---

## フェーズ1：Meta Developer アカウント準備

- [ ] **Meta アカウント作成済み**
  - Meta for Developers (developers.facebook.com) にログインできる状態か

- [ ] **Business Manager アカウント作成済み**
  - business.facebook.com にアクセスして確認

- [ ] **Business Verification（法人確認）完了**
  - 必要書類: 登記簿謄本または法人確認書類
  - 所要時間: 通常 2〜5 営業日
  - ※ Advanced Access 申請には Business Verification が前提条件

- [ ] **Threads アプリが Developer Console に登録済み**
  - App 名: Trees Hospitality Connect（または任意の名称）
  - App タイプ: Business
  - Threads ユースケース（Use Case）が有効になっている

- [ ] **テスターアカウントを最低1名追加済み**
  - Developer Console → Roles → Testers
  - テスターの Threads アカウントが有効である

---

## フェーズ2：技術要件

- [ ] **`threads_basic` 権限が付与済み**（テスト環境で動作確認済み）

- [ ] **アクセストークンの取得・動作確認済み**
  - Graph API Explorer または OAuth フローでトークン取得
  - `GET /me?fields=id,name` が成功すること

- [ ] **keyword_search エンドポイントの動作確認**（テスト環境）
  ```
  GET https://graph.threads.net/v1.0/keyword_search
    ?q=沖縄+おすすめ
    &search_type=RECENT
    &access_token={token}
  ```

- [ ] **テスト用投稿を2件以上作成済み**
  - テスターアカウントで投稿（公開設定）
  - 投稿内容は審査シナリオに沿ったもの

- [ ] **Cloud Run の全エンドポイントが稼働中**
  - `/threads-manual-setup` ✓
  - `/threads-manual-process` ✓
  - `/threads-manual-test` ✓
  - `/threads-manual-status` ✓
  - `/threads-dry-run-status` ✓

- [ ] **DRY_RUN=true のままであること**
  - `curl .../threads-dry-run-status` で確認

- [ ] **LINE 通知が届くことを確認済み**
  - TACHINOMIYA スタッフ LINE ✓
  - 琉球火鍋スタッフ LINE ✓

---

## フェーズ3：法的ページの公開

- [ ] **プライバシーポリシーページが HTTPS で公開済み**
  - URL: `https://[your-domain]/privacy`
  - 参照: `docs/threads_privacy_policy.md`
  - 日本語版・英語版の両方を掲載

- [ ] **利用規約ページが HTTPS で公開済み**
  - URL: `https://[your-domain]/terms`
  - 参照: `docs/threads_terms.md`

- [ ] **データ削除ページが HTTPS で公開済み**
  - URL: `https://[your-domain]/data-deletion`
  - 参照: `docs/threads_data_deletion.md`

- [ ] **ウェブサイトドメインが Meta Console に登録済み**
  - Business Settings → Brand Safety → Domains

---

## フェーズ4：申請コンテンツの準備

- [ ] **申請文（英語）の準備完了**
  - 参照: `docs/threads_app_review_submission.md` セクション2・3・4
  - 文字数: 各フィールド 300〜1,000 文字程度

- [ ] **テスト手順（英語）の準備完了**
  - 参照: `docs/threads_review_video_script.md`

- [ ] **画面録画の完成**
  - 参照: `docs/threads_review_video_script.md`
  - 長さ: 5〜8分
  - 形式: MP4、1080p 以上
  - 内容確認:
    - [ ] keyword_search の実行
    - [ ] スコアリングの表示
    - [ ] シートへの記録
    - [ ] LINE 通知の受信
    - [ ] 手動返信の実施
    - [ ] 重複防止の動作
    - [ ] DRY_RUN モードの確認

---

## フェーズ5：申請直前の最終確認

- [ ] **権限名の最終確認**
  - Developer Console で `threads_keyword_search` の正式名称が変更されていないか
  - `threads_manage_replies` または `threads_manage_mentions` の要否を再確認

- [ ] **プライバシーポリシー URL が Developer Console に登録済み**

- [ ] **利用規約 URL が Developer Console に登録済み**

- [ ] **申請フォームの全フィールドに英語で記入済み**
  - App の説明（App Description）
  - `threads_keyword_search` の利用理由
  - データの利用方針
  - テスト手順

- [ ] **画面録画のアップロード完了**

- [ ] **Business Verification 完了済みであることを確認**

---

## 申請後の対応

- [ ] **審査状況のメール通知を確認**（Developer Console に登録したメール）
- [ ] **追加情報リクエストへの対応体制を確保**（審査期間: 通常 2〜4 週間）
- [ ] **審査通過後に DRY_RUN=false へ変更する手順を確認済み**

---

## Business Verification 必要書類一覧

以下を事前に準備してください。

| 書類 | 備考 |
|------|------|
| 法人登記簿謄本 | 発行から3ヶ月以内のものが望ましい |
| 事業者名（英語表記） | yu holdings（または登記上の名称） |
| 事業所住所 | 沖縄県那覇市の住所（英語表記も用意） |
| 事業者ウェブサイト URL | HTTPS 必須 |
| 代表者名 | パスポートまたは身分証明書と一致する氏名 |
| Meta Business Manager アカウント | 作成済みであること |

---

## よくある却下理由と対策

| 却下理由 | 対策 |
|----------|------|
| プライバシーポリシーが未公開 | HTTPS で公開し URL を登録 |
| ユースケースの説明が不明瞭 | セクション3の申請文を詳しく記入 |
| 自動スパムの懸念 | 人間承認・DRY_RUN・重複防止を強調 |
| Business Verification 未完了 | 先に BV を完了させてから申請 |
| 動画が権限の利用を示していない | シナリオ シーン2（keyword_search 実行）を必ず含める |
| テスター未登録 | Developer Console でテスターを追加 |
