# SNS投稿PDCAシステム グレードアップ 設計書（実装前・提案）

最終目的: **バズではなく、予約・来店・問い合わせ・売上の最大化**。
対象事業: Tree Beauty / Trees Catering / TACHINOMIYA / 琉球火鍋 / パスタパスタ / Z1
対象媒体: Google投稿 / Threads投稿 / LINE公式

---

## 0. 重要前提（再確認）
- **画像生成は対象外（Phase全体でテキストのみ）**。本システムは投稿文の管理・分析・リライトに専念。
  画像は既存の仕組みに任せ、本PDCAでは扱わない。
- Google投稿・Threads投稿は **API投稿不可 → 人間が手動投稿**（本システムは「ストック管理＋結果記録＋改善」に専念）
- LINE公式の反応は **スクショ → AIで読取 → シート記録**（OCRは Google Cloud Vision・無料枠／OpenAI不使用）
- 元投稿は **絶対に上書きしない**。改善版は別シート（SNS_REWRITE_STOCK）へ
- 既存コード・既存シートを壊さない。**新規シート追加＋バックアップ優先**

---

## 1. 全体設計図

```
[人間] ─ Google/Threads/LINEに手動投稿
   │
   ├─ 投稿実績(数値)を手入力 or スクショ ──┐
   │                                      │
[LINE公式の反応スクショ] ─ オーナー/スタッフがLINE送信 │
   │                                      ▼
   ▼                          ┌─────────────────────────┐
LINE Webhook(ハブ: tachinomiya-ai)        │  Google Cloud Vision OCR │ (無料・既存流用)
   │  画像種別を判定                        └─────────────────────────┘
   │  「LINE反応スクショ」→ SNS処理へ                     │ 抽出: 友だち追加/メッセージ/予約/問い合わせ/クーポン
   ▼                                                     ▼
┌──────────────────────────────────────────────────────────────┐
│  SNS PDCA Core (新規 core/sns_pdca.py)                          │
│  ① 取込: LINE_SCREENSHOT_LOG へ記録（信頼度低→要確認）            │
│  ② 紐付: スクショ反応 ↔ SNS_RESULT ↔ SNS_POST_STOCK             │
│  ③ 分析: SNS_AI_ANALYSIS（勝ちフック/悩み/CTA・TYPE別TOP10・導線）│
│  ④ 改善: 未投稿ストックを勝ちパターンへリライト → SNS_REWRITE_STOCK │
│  ⑤ 戦略: 次30日投稿戦略を提案                                    │
└──────────────────────────────────────────────────────────────┘
   │                         │                          │
   ▼                         ▼                          ▼
SNS_DASHBOARD          Daily Action連携           Knowledge OS / MCP(read-only)
(経営者確認)          (未投稿/要承認タスク)        (Markdown保存・Claude確認)
```

---

## 2. 既存スプレッドシートとの連携方法

| 既存資産 | 連携内容 |
|---|---|
| 各事業の投稿ストック（既存 Content Engine が生成した投稿群） | SNS_POST_STOCK へ **読み込み取込**（コピー）。既存シートは読むだけ・変更しない |
| Daily Sales Screenshot OS（既存・Vision OCR・LINE webhookハブ） | **OCR基盤とWebhookハブを流用**。画像種別に「LINE反応」を追加して振り分け |
| 各事業スプレッドシート（TACHINOMIYA 1K4KkAh 等）| business_name で紐付け。実績の一部（予約/売上）は既存POS/売上データと突合可能 |
| YU CEO Dashboard（統合 1I6wRRDa）| **新規SNS_*シートはここに集約**（一元管理＝目的に合致）。business_name列で6事業を区別 |
| Daily Action Commander | 「未投稿◯件」「改善版◯件が承認待ち」をタスク自動注入（read→タスク化） |
| MCP Server | Phase2で read-only tool `get_sns_status` を追加（Claudeから確認） |

**配置方針**: 新規6シートは統合SS（YU CEO Dashboard）に作成し、business_name列で全事業を一元管理。
既存の各事業投稿ストックからは「取込（読み取りコピー）」のみ行い、既存シートには一切書き込まない。

---

## 3. 追加するシート構成（6シート＋投稿3分類）

### 投稿3分類（TYPE）— 全投稿に付与
| TYPE | 名称 | 目的(KPI) |
|---|---|---|
| TYPE-A | 認知投稿 | インプレッション・シェア・保存・フォロワー増 |
| TYPE-B | 興味投稿 | プロフィールアクセス・LINE追加・DM |
| TYPE-C | 集客投稿 | 予約・問い合わせ・来店・売上 |

→ SNS_POST_STOCK.post_type に A/B/C を格納。分析・戦略はTYPE別に最適化。

### シート一覧（すべて統合SSに新規作成・既存に影響なし）
1. **LINE_SCREENSHOT_LOG**（15列）: screenshot_id / business_name / upload_date / period_start / period_end / screenshot_file_url / extracted_text / line_friend_add_count / line_message_count / reservation_count / inquiry_count / coupon_click_count / ai_confidence_score / human_check_status / memo
2. **SNS_POST_STOCK**（16列）: post_id / business_name / platform / post_no / original_text / current_text / post_type(A/B/C) / target_stage / customer_pain / hook_text / cta / status / scheduled_date / posted_date / posted_url / rewrite_version / memo
3. **SNS_RESULT**（18列）: post_id / business_name / platform / posted_date / impressions / likes / comments / shares / saves / profile_access / line_add / dm_count / reservation_count / inquiry_count / visit_count / sales_amount / related_screenshot_id / manual_note
4. **SNS_AI_ANALYSIS**（14列）: analysis_id / analysis_date / business_name / platform / period_start / period_end / top_post_ids / weak_post_ids / winning_hooks / winning_customer_pains / winning_cta / line_reaction_summary / bad_patterns / next_improvement_policy / ai_summary
5. **SNS_REWRITE_STOCK**（11列）: rewrite_id / original_post_id / business_name / platform / old_text / rewritten_text / rewrite_reason / improvement_point / expected_effect / status / created_at
6. **SNS_DASHBOARD**（経営者確認用）: 事業別投稿数 / 媒体別投稿数 / 投稿済み数 / 未投稿数 / LINE追加数 / 問い合わせ数 / 予約数 / 反応上位投稿 / 売上につながった投稿 / 改善された投稿数 / 次に増やすテーマ / 次に減らすテーマ / 今週の最重要アクション

**バックアップ方針**: 各シート作成前に、既存投稿ストックを読み取った時点のスナップショットを
`SNS_POST_STOCK_BACKUP_YYYYMMDD` としてGCS(Knowledge OS)へMarkdown/CSV保存。元データは不変。

---

## 4. スクショ読み取りフロー

```
スタッフ/オーナー → LINE公式に「LINE反応スクショ」を送信
   ↓
LINE Webhook(ハブ tachinomiya-ai/line-task-webhook)
   ↓ 画像メッセージを判定
   ├─ 売上スクショ → 既存 Daily Sales Screenshot OS（変更なし）
   └─ LINE反応スクショ → 新SNS取込へ ※判別方法は下記
   ↓
Google Cloud Vision で OCR（無料枠・既存 analyze_image を流用）
   ↓ ルールベース抽出
   ・友だち追加数 / メッセージ数 / 予約数 / 問い合わせ数 / クーポンクリック数
   ・対象期間(period_start〜end)
   ↓
LINE_SCREENSHOT_LOG へ記録
   ・ai_confidence_score を算出
   ・低信頼度 → human_check_status = 「要確認」＋スタッフへ確認文（DRY_RUN）
   ↓
紐付け: 期間×事業 で SNS_RESULT の該当投稿群へ反応を配分/集計
   （related_screenshot_id で双方向リンク）
```

**画像種別の判別方法（売上スクショ vs LINE反応スクショ）**:
- 案1: 送信時にキャプション/キーワードを付ける（「反応」「インサイト」等）→ それで振り分け（最も確実）
- 案2: OCRテキストに「友だち追加」「メッセージ」「インサイト」等があればLINE反応と判定
- 案3: 専用の受付（例: メッセージ冒頭に `SNS:` を付ける）
→ 設計では **案1+案2併用** を推奨（誤判別時は要確認へ）

---

## 5. 投稿改善リライトの流れ

```
SNS_RESULT + LINE_SCREENSHOT_LOG（反応データ）
   ↓ ① 評価指標を「売上貢献度」で再重み付け
      重み: 売上>予約>問い合わせ>LINE追加>プロフィールアクセス >> いいね/保存
   ↓ ② TYPE別に勝ち/負けを判定
      勝ち投稿: winning_hooks / winning_customer_pains / winning_cta を抽出（頻度×コンバージョン相関）
      負け投稿: bad_patterns を抽出（共通点）
   ↓ ③ 未投稿ストック(status=未投稿)を対象に、勝ちパターンへリライト
      ・元投稿は SNS_POST_STOCK に温存（上書き禁止）
      ・改善版を SNS_REWRITE_STOCK に保存（old_text/rewritten_text/理由/期待効果）
      ・rewrite_version をインクリメント管理
   ↓ ④ 人間が承認 → 承認版を手動投稿 → 結果をまた記録（PDCAループ）
```

### ★重要な技術論点: リライト/分析の「生成」をどう行うか（OpenAI禁止）
分析の **抽出・スコアリング・TOP10・導線分析** は完全ルールベースで実装可能（LLM不要）。
ただし **投稿文の自動リライト（生成）** はLLMが要る領域。OpenAI禁止のため選択肢:

| 案 | 方式 | コスト | 品質 | 備考 |
|---|---|---|---|---|
| **A（推奨）** | Google Gemini API 無料枠 | 無料 | 高 | GCPネイティブ・自然な生成。無料枠内運用 |
| B | テンプレート再構成（勝ちフック+悩み+CTAを差し込み） | 完全無料 | 中 | LLMなし・決定論的・創造性は限定 |
| C | Claude(本MCP)経由で人間がリライト依頼 | 無料 | 高 | 自動ではない・人間が都度Claudeに依頼 |
| D | ハイブリッド: 分析=ルールベース＋生成=Gemini | 無料 | 高 | Aの実務版 |

→ **どれを採用するかで実装が変わる**ため、最後に確認します。

---

## 6. 既存コードへの影響範囲

| 対象 | 影響 | 対応 |
|---|---|---|
| 既存REST/エンドポイント | なし（新規 `/sns-*` を追加するのみ） | 追加方式 |
| 既存シート | 読むだけ・書き込まない | バックアップ後に参照 |
| Daily Sales Screenshot OS | Webhookに画像種別分岐を1段追加 | 既存売上フローは不変 |
| LINE Webhook ハブ(tachinomiya-ai) | image→種別判定の分岐追加 | 後方互換（判別不能は従来=売上扱いにせず要確認へ） |
| MCP Server | Phase2で read-only tool追加 | 既存8toolsは不変 |
| Content Engine | 読み取り取込のみ | 生成側は不変 |
| 新規ファイル | `core/sns_pdca.py`（新規） | 単一モジュールに集約 |

**破壊リスク最小化**: 既存webhookの画像分岐は「LINE反応と確証が取れた時のみSNS処理」。
判別不能は従来動作を維持＋要確認ログ。

---

## 7. 最小実装プラン（フェーズ分け）

- **Phase 0（準備）**: 既存投稿ストックの場所・形式を棚卸し → バックアップ → シート設計確定
- **Phase 1（記録基盤・read重視）**:
  - 6シート作成（統合SS）／既存ストックを SNS_POST_STOCK へ取込
  - LINE反応スクショ取込（Vision OCR）→ LINE_SCREENSHOT_LOG
  - 手動/スクショで SNS_RESULT 記録
  - SNS_DASHBOARD（集計・閲覧）
  - エンドポイント: `/sns-setup` `/sns-import-stock` `/sns-screenshot-webhook(分岐)` `/sns-result-record` `/sns-status`
- **Phase 2（分析）**: SNS_AI_ANALYSIS（ルールベースでTOP10・勝ちパターン・導線・bad patterns）
  - `/sns-analyze` `/sns-dashboard-refresh`／MCP read-only tool `get_sns_status`
- **Phase 3（改善生成）**: SNS_REWRITE_STOCK（採用方式A/B/C/Dに従う）／次30日戦略提案
  - `/sns-rewrite`（未投稿→改善版・元は不変）／`/sns-strategy-30days`
- **Phase 4（運用）**: Daily Action連携（未投稿・要承認・要確認をタスク化）／週次レポート

各Phaseは独立リリース可。Phase1（記録）だけでも価値が出る。

---

## 8. AI分析で実施する項目（ルールベース中心）

- 認知投稿(TYPE-A) TOP10 / 興味投稿(TYPE-B) TOP10 / 集客投稿(TYPE-C) TOP10
- **バズったが売上につながらない投稿**分析（高impression × 低予約/売上）
- **売上につながったが伸びなかった投稿**分析（高予約/売上 × 低impression）
- 認知→興味→集客の **導線分析**（TYPE別のLINE追加・予約への寄与）
- 各事業ごとの **勝ちパターン抽出**（hook/customer_pain/cta）
- 未投稿ストックの **自動改善**（勝ちパターンへ寄せる）
- 改善版投稿の **自動生成**（採用方式に依存）
- **次回30日分の投稿戦略提案**（TYPE構成比・テーマ・媒体配分・本数）

評価の重み付け（最重要方針）:
`売上 > 来店 > 予約 > 問い合わせ > LINE追加 > プロフィールアクセス >>> いいね/保存/シェア`

---

## 9. リスクと対策

| リスク | 対策 |
|---|---|
| 既存シート破壊 | 読み取り専用＋事前バックアップ（GCS）。書込は新規シートのみ |
| スクショ誤読 | Vision信頼度スコア→低ければ human_check_status=要確認。人間最終確認 |
| 売上スクショとLINE反応スクショの誤判別 | キャプション＋OCRキーワード併用。不明は要確認（自動処理しない） |
| 元投稿の喪失 | 上書き禁止。改善版は別シート。rewrite_versionで履歴 |
| リライト品質（OpenAI禁止） | 方式A/B/C/Dから選択。Bなら完全無料・決定論的 |
| 反応と投稿の紐付けズレ | 期間×事業で配分＋related_screenshot_idで追跡。手動補正欄(manual_note) |
| 媒体APIなし（手動投稿） | 本システムは「投稿支援」に徹し、投稿実行は人間。posted_url手入力で実績化 |
| 機密/個人情報 | LINE反応スクショに顧客個人情報が写る場合あり→集計値のみ記録、原画はGCS限定・URL非公開 |

---

## 10. 最初に決めてほしいこと（実装着手の前提）
1. **リライト/生成エンジン**: A(Gemini無料) / B(テンプレ・完全無料) / C(Claude経由) / D(ハイブリッド)
2. **既存投稿ストックの所在**: Content Engineの出力シート名・スプレッドシートを教えてほしい（取込元）
3. **シート配置**: 統合SS一元管理でよいか（推奨）／各事業SSに分散したいか
4. **スクショ種別判別**: キャプション方式でよいか（「反応」等の語を付けて送る）

これらが決まり次第、Phase 1から実装に着手します（承認後）。
