# データ削除ページ / Data Deletion Page

> **公開用ページ本文**
> このページの内容を `https://[your-domain]/data-deletion` に掲載してください。
> Meta の App Review では「データ削除手順」ページの URL 提出が求められる場合があります。

---

## 日本語版

最終更新日：2026年6月21日

### Threads データ削除依頼

Trees Hospitality Connect（yu holdings 運営）では、Threads の公開投稿から
飲食店探しに関連する投稿を検索・記録しています。

あなたの投稿データが記録されている可能性があり、削除を希望される場合は
以下の手順でご依頼ください。

---

#### 削除依頼の方法

**メールでの依頼（推奨）**

メール送信先：yuya_tokuda@trees-catering.com
件名：Threads データ削除依頼
本文に含める情報：

- Threads ユーザー名（@username の形式）
- 削除をご希望の理由（任意）

---

#### 対応時間・手順

| ステップ | 内容 | 所要時間 |
|----------|------|----------|
| 1. 受付確認 | メール受信後、受付完了の返信を送ります | 24時間以内 |
| 2. データ検索 | ユーザー名でデータベースを検索します | 受付から48時間以内 |
| 3. 削除実行 | 該当するすべての記録を削除します | 受付から72時間以内 |
| 4. 完了通知 | 削除完了をメールでお知らせします | 削除後24時間以内 |

合計対応時間：**ご依頼から72時間以内**

---

#### 削除対象データ

以下のデータが削除されます：

- 投稿本文
- 投稿 URL
- 投稿日時
- Threads ユーザー名

---

#### 削除対象外のデータ

以下は削除できない場合があります：

- 法令に基づく保管義務があるデータ（該当する場合）
- 匿名化処理が完了し、個人を特定できない状態のデータ

---

#### お問い合わせ

ご不明な点は以下までご連絡ください。

メール：yuya_tokuda@trees-catering.com
受付時間：平日 10:00〜18:00（日本時間）

---

## English Version

Last updated: June 21, 2026

### Threads Data Deletion Request

Trees Hospitality Connect (operated by yu holdings) searches and records
publicly visible Threads posts related to Okinawa dining recommendations.

If your post has been recorded and you wish to have it deleted,
please follow the instructions below.

---

#### How to Request Deletion

**Via Email (recommended)**

Email: yuya_tokuda@trees-catering.com
Subject: Threads Data Deletion Request
Include in your message:

- Your Threads username (in @username format)
- Reason for deletion (optional)

---

#### Response Process

| Step | Action | Timeline |
|------|--------|----------|
| 1. Acknowledgment | We confirm receipt of your request | Within 24 hours |
| 2. Search | We locate all records matching your username | Within 48 hours of receipt |
| 3. Deletion | All matching records are permanently deleted | Within 72 hours of receipt |
| 4. Confirmation | We notify you by email that deletion is complete | Within 24 hours of deletion |

Total response time: **within 72 hours of your request**

---

#### What We Delete

The following data will be deleted:

- Post text
- Post URL
- Post timestamp
- Threads username

---

#### What We Cannot Delete

The following may not be deletable:

- Data subject to legal retention obligations (if applicable)
- Data that has been fully anonymized and no longer identifies you

---

#### Contact

For questions or concerns:

Email: yuya_tokuda@trees-catering.com
Business hours: Weekdays 10:00–18:00 JST

---

## Meta コールバック対応（技術情報）

Meta が将来的にデータ削除コールバック（Webhook）を要求する場合に備えて、
以下のエンドポイントを用意する予定です。

```
POST /threads-data-deletion
```

リクエスト：Meta から送信される signed_request を含む JSON
レスポンス：
```json
{
  "url": "https://[your-domain]/data-deletion/confirm?id={confirmation_code}",
  "confirmation_code": "{unique_code}"
}
```

確認ページ（`/data-deletion/confirm?id=xxx`）では削除ステータスを表示します。

*このエンドポイントの実装は App Review 承認後に追加予定です。*
