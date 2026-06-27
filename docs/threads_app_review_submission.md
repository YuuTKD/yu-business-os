# Threads API App Review 申請書（提出用）

> このドキュメントは Meta Developer Console への申請コンテンツを英語・日本語で管理するものです。
> 提出時は英語版をそのまま Management Console の各フィールドに貼り付けてください。

---

## 1. App の基本情報

| 項目 | 内容 |
|------|------|
| App 名 | Trees Hospitality Connect |
| 会社名 | yu holdings（trees-catering / TACHINOMIYA / 琉球火鍋を運営） |
| 担当者メール | yuya_tokuda@trees-catering.com |
| ウェブサイト | （申請前に用意が必要） |
| プライバシーポリシー URL | https://[your-domain]/privacy |
| 利用規約 URL | https://[your-domain]/terms |

---

## 2. App の説明（英語・申請フォーム用）

### App Description（アプリ概要）

```
Trees Hospitality Connect is a customer discovery and response support tool
for two Okinawa-based dining restaurants — TACHINOMIYA (a casual standing bar
on Kokusai Street) and Ryukyu Hinabe (a private-room shabu-shabu / medicinal
hot pot restaurant in Naha).

The app searches for publicly shared Threads posts that express a genuine need
for Okinawa dining recommendations — for example, travelers asking where to eat
near Kokusai Street, or visitors looking for private-room dinner options.

Relevant posts are scored by AI for relevance (0–100). Posts that score 70 or
above are presented to a human staff member via LINE notification, along with
a suggested reply. The staff member then manually visits the original Threads
post, reviews the suggestion, and — only when appropriate — replies by hand.

No automated replies are ever published. No bulk messaging. No unsolicited
outreach. Every reply is a deliberate, human-reviewed action.
```

### 日本語訳（社内確認用）

Trees Hospitality Connect は、沖縄の飲食店2店舗（TACHINOMIYA・琉球火鍋）向けの
来店候補者発見・返信支援ツールです。

沖縄旅行中・旅行予定の Threads ユーザーが投稿した「どこで食べよう」「国際通りのおすすめは？」
といった飲食店相談投稿を公開タイムラインから検索し、AIが関連性スコアを付けます。
スコア70点以上の投稿のみスタッフに LINE 通知し、返信案を提示します。
スタッフが投稿を確認・判断し、適切と判断した場合のみ手動で返信します。
自動返信・一括送信・無差別な勧誘は一切行いません。

---

## 3. threads_keyword_search 申請理由（英語・フォーム用）

```
Use Case:
We operate two dining venues in Naha, Okinawa, Japan:
  - TACHINOMIYA: a casual standing bar / daytime café on Kokusai Street
  - Ryukyu Hinabe: a private-room shabu-shabu and medicinal hot pot restaurant

Travelers and locals frequently post on Threads asking for Okinawa dining
recommendations — "Where should I eat near Kokusai Street tonight?",
"Any good private-room dinner spots in Naha?" — but without tagging any
specific restaurant. Without keyword search, we have no way to discover
these conversations.

How we use threads_keyword_search:
We search for publicly available Threads posts using location + intent keywords
such as "沖縄 おすすめ 教えて" (Okinawa + recommendations + please share) or
"那覇 個室 ディナー" (Naha + private room + dinner). Searches are executed
no more than once every 15 minutes and retrieve only the most recent posts.

Each result is passed through a proprietary relevance scoring algorithm
(0–100 points, 5 criteria):
  1. Okinawa presence / travel intent (25 pts)
  2. Active food search intent (25 pts)
  3. Naha / Kokusai Street area mention (20 pts)
  4. Match with specific venue features (20 pts)
  5. Post specificity — date, group size, occasion (10 pts)

Only posts scoring 70 or above are surfaced to human staff via LINE.
Staff review each post individually and reply manually — never automatically.
Posts below threshold are logged but generate no reply.

Why Standard Access is insufficient:
Standard Access limits searches to the authenticated user's own posts.
Our goal is to discover public posts from travelers who do not know our
venues yet. This requires Advanced Access to threads_keyword_search.

Privacy safeguards:
  - Only publicly visible post content (text, username, URL) is stored.
  - Data is retained for 90 days, then deleted.
  - No data is shared with third parties.
  - Users may request deletion at any time via email.
  - We comply with Meta's Platform Policies and Threads Community Guidelines.
```

---

## 4. データ利用方針（英語・フォーム用）

```
Data collected:
  - Post ID
  - Post text (publicly visible content only)
  - Threads username (public)
  - Post URL (permalink)
  - Post timestamp

Storage:
  - Google Sheets (access restricted to authorized staff only)
  - Retention: 90 days from date of collection
  - No third-party sharing

User actions available:
  - Data deletion request: yuya_tokuda@trees-catering.com
  - Response time: within 72 hours

We do not collect:
  - Private messages
  - Email addresses
  - Phone numbers
  - Location data beyond what is publicly stated in the post
```

---

## 5. 安全制御の説明（審査員が懸念するポイントへの回答）

| 懸念 | 当システムの対策 |
|------|-----------------|
| 自動スパム返信 | DRY_RUN=true を本番環境でも維持。自動返信コードは存在しない |
| 大量送信 | 同一投稿への返信は1回のみ。同一ユーザーへは7日以内の通知制限あり |
| 無差別勧誘 | 関連性スコア70点未満の投稿は通知しない（約40〜60%が対象外） |
| 個人情報収集 | 公開投稿のテキスト・ユーザー名・URLのみ。非公開情報は一切取得しない |
| 継続的な監視 | 15分ごとの定期実行。スタッフ1名が手動で全返信を確認・承認 |

---

## 6. 申請フォーム記入マッピング

| フォーム項目 | 使用する内容 |
|------------|-------------|
| Describe your use case | セクション2 英語版を貼付 |
| Why do you need this permission? | セクション3 全文を貼付 |
| How will you use the data? | セクション4 全文を貼付 |
| Screencast / demo video | `threads_review_video_script.md` の手順で録画 |
| Privacy policy URL | https://[your-domain]/privacy |
| Terms of service URL | https://[your-domain]/terms |

---

## 7. 事前確認事項

申請前に以下を必ず再確認してください。

- [ ] Meta Developer Console で `threads_keyword_search` 権限の正式名称が変更されていないか
- [ ] `threads_manage_replies` が返信に必要か、それとも `threads_manage_mentions` か
- [ ] Business Verification（法人確認）が完了しているか
- [ ] プライバシーポリシーページが HTTPS で公開されているか
- [ ] 利用規約ページが HTTPS で公開されているか
- [ ] テスター用アカウントが Meta Developer Console に登録されているか
- [ ] テスト用投稿（英語・日本語）が準備されているか

---

*このドキュメントは `docs/threads_app_review.md` の内容を統合・拡張したものです。*
*更新日: 2026-06-21*

---

## 8. 申請用 HP ページ構成

App Review には公開済みの Web ページが必要です。以下の構成を推奨します。

```
[your-domain]
├── /                     トップページ（事業紹介）
├── /privacy              プライバシーポリシー（必須）
├── /terms                利用規約（推奨）
├── /data-deletion        データ削除ページ（推奨）
└── /about                会社概要（任意）
```

### 最低限必要なページ内容

| ページ | 必須 | 参照ドキュメント |
|--------|------|-----------------|
| `/privacy` | ◎ 必須 | `docs/threads_privacy_policy.md` |
| `/terms` | ○ 推奨 | `docs/threads_terms.md` |
| `/data-deletion` | ○ 推奨 | `docs/threads_data_deletion.md` |

### 推奨ドメイン候補

- `tachinomiya-naha.com`
- `trees-catering.com`（既存ドメインがある場合はそちらを優先）
- `yu-holdings.jp`

### HP に記載すべき内容

トップページに以下を含めることを推奨します：

1. 事業者名（yu holdings）
2. 運営店舗名（TACHINOMIYA・琉球火鍋）
3. 所在地（沖縄県那覇市）
4. 連絡先メールアドレス
5. Trees Hospitality Connect の簡単な説明

---

## 9. Business Verification 必要項目

| 項目 | 内容 | 備考 |
|------|------|------|
| 法人種別 | 株式会社 / 合同会社 等 | 登記書類で確認 |
| 法人名（日本語） | yu holdings または登記上の名称 | |
| 法人名（英語） | Yu Holdings Co., Ltd. 等 | 登記書類の英語表記に合わせる |
| 本社住所 | 沖縄県那覇市〇〇 | 登記上の住所 |
| 代表者名 | 徳田 悠哉 | パスポート等と一致させる |
| 事業内容 | 飲食店経営 / 飲食業 | |
| ウェブサイト | https://[your-domain] | HTTPS 必須 |
| Meta Business Manager | 作成・ログイン済みであること | |
| 確認書類 | 登記簿謄本（発行3ヶ月以内推奨） | PDF または画像 |

Business Verification は通常 **2〜5 営業日** かかります。
App Review の申請前に完了させることを強く推奨します。

---

## 既存ドキュメントとの関係

| ドキュメント | 役割 |
|-------------|------|
| `docs/threads_app_review.md` | 技術仕様・権限説明・テスト手順（既存・参照用） |
| `docs/threads_app_review_submission.md`（本書） | 申請フォームに貼り付ける文章・提出用資料集 |
| `docs/threads_privacy_policy.md` | 公開 Web ページ用プライバシーポリシー本文 |
| `docs/threads_data_deletion.md` | 公開 Web ページ用データ削除ページ本文 |
| `docs/threads_terms.md` | 公開 Web ページ用利用規約本文 |
| `docs/threads_review_video_script.md` | 画面録画の撮影シナリオ |
| `docs/threads_review_checklist.md` | 申請前チェックリスト |
