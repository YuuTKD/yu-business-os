# YU Business OS 2.0 — Master Architecture

作成日: 2026-07-11  
ステータス: 設計書（実装禁止・承認待ち）  
設計者: Claude Code（監査・設計フェーズ）

---

## 設計原則

1. **上位レイヤー追加のみ** — 既存 1.x コードは一切変更しない
2. **Cash-First** — 全レイヤーがキャッシュフローに接続する
3. **OpenAI 禁止** — 新規レイヤーで OpenAI API は使わない（既存 1.x の依存は維持）
4. **オーナーのみ通知** — 全自動通知は `LINE_OWNER_TOKEN` 経由のみ
5. **単一設定源** — `configs/business_registry.py` が唯一の事業設定
6. **止める AI** — 安全ゲートが「しない」を保証する

---

## 1.x 現状資産インベントリ（フルスキャン 2026-07-11）

### 1.1 Cloud Run サービス（7本）

| サービス名 | URL パターン | 重要度 | 状態 |
|---|---|---|---|
| `tree-beauty-ai` | `tree-beauty-ai-*.run.app` | S | 稼働中 |
| `trees-catering-ai` | `trees-catering-ai-*.run.app` | S | 稼働中 |
| `tachinomiya-ai` | `tachinomiya-ai-*.run.app` | S | 稼働中（Scheduler=OFF）|
| `ryukyu-hinabe-ai` | `ryukyu-hinabe-ai-*.run.app` | S | 稼働中 |
| `pasta-pasta-ai` | `pasta-pasta-ai-*.run.app` | A | 稼働中 |
| `z1-ai` | `z1-ai-*.run.app` | A | 稼働中 |
| `yu-holdings-ai` | `yu-holdings-ai-*.run.app` | S | 稼働中（System Health 毎朝8:30）|

全サービスは単一 Dockerfile・単一イメージを共用。`BUSINESS_NAME` 環境変数で事業切り替え。

### 1.2 事業レジストリ（`configs/business_registry.py`）

| key | 事業名 | 業種 | 月商目標 | 状態 |
|---|---|---|---|---|
| `beauty` | Tree Beauty | salon | ¥500K | active |
| `catering` | Trees Catering | catering | ¥800K | active |
| `pasta_pasta` | パスタパスタ | consulting | ¥2M | active |
| `z1` | Z1 | consulting | ¥1.5M | active |
| `tachinomiya` | TACHINOMIYA | restaurant/bar | ¥3.5M | active（Scheduler=OFF）|
| `ryukyu_hinabe` | 琉球火鍋 | restaurant | ¥1.5M | active |

**月商合計目標: ¥9.8M**

### 1.3 コアモジュール（`core/`）

| ファイル | 役割 | 依存 |
|---|---|---|
| `entrypoint.py` | Flask + 15 REST エンドポイント | 全 core モジュール |
| `multi_business_content_engine.py` | 毎朝9:00 コンテンツ自動化 STEP1-7 | OpenAI, GCS, Sheets, LINE |
| `owner_daily.py` | OWNER_ONLY 日次 LINE 配信 | Sheets, LINE_OWNER_TOKEN |
| `system_health.py` | 7 CR + 6 Sheets 死活監視 | GCP Scheduler API, Sheets |
| `executive_team.py` | AI 役員週次ブリーフィング | OpenAI, Sheets |
| `gbp_api.py` | GBP 投稿自動化 | Google Business Profile API |
| `threads_api.py` | Threads OAuth + 投稿 | Threads API |
| `threads_reply_publisher.py` | Threads 返信自動化 | Threads API |
| `sns_pdca.py` | SNS PDCA 追跡 | Sheets |
| `growth_engines.py` | 5 集客エンジン | Sheets, GCS |
| `cash_flow.py` | キャッシュフロー分析 | Sheets |
| `profit_leak.py` | 利益漏れ検知 | Sheets |
| `review_referral.py` | 口コミ・紹介エンジン | Sheets |
| `image_manager.py` | IMAGE_LIBRARY 管理 | GCS, Sheets, Vision |
| `pos_processor.py` | POS データ処理 | Drive, Sheets |
| `credentials_loader.py` | Google 認証 | GCP Secret / B64 env |

### 1.4 エンドポイント一覧（`entrypoint.py`）

```
GET  /health                健康確認
GET  /status                設定確認
POST /google                Google 投稿生成
POST /distribute            5 媒体フル配信
POST /process-csv           CSV 取込 → 週次/月次レポート
POST /generate-weekly-report 週次レポート単独
POST /generate-content      180 日コンテンツ生成
POST /setup-spreadsheet     スプレッドシート初期構築
POST /executive-briefing    AI 役員週次ブリーフィング
POST /process-pos           POS データ取込
GET  /blog-image/<file_id>  Drive 画像プロキシ
POST /daily-line-content    Tree Beauty 日次 LINE
POST /generate-blog-images  HPB ブログ画像生成
POST /image-setup           IMAGE_LIBRARY 初期設定
POST /scan-drive-images     Drive 画像スキャン
POST /content-automation    Multi Business Content Automation
POST /catering-weekly       Catering 週次レポート
POST /catering-monthly      Catering 月次レポート
POST /catering-setup        Catering Sheets 構築
POST /catering-content      Catering 90 日コンテンツ生成
```

### 1.5 エージェント（`agents/`）

| エージェント | 言語 | 状態 |
|---|---|---|
| `product_match_acquisition/` | JavaScript | PAUSED（2026-07-08）|
| `shared/line_notify.js` | JS | 共通ライブラリ |
| `shared/cost_guard.js` | JS | 使用量ガード |
| `shared/dedupe.js` | JS | 重複排除 |
| `shared/human_gate.js` | JS | 人間承認ゲート |
| `shared/secret_guard.js` | JS | Secret 検出 |
| `shared/risk_hint.js` | JS | リスクヒント |

### 1.6 スキル（`skills/`）

| スキル名 | 役割 | 発動条件 |
|---|---|---|
| `debt-collection` | 債権回収テンプレート | 未収金・督促の話題 |
| `image-library-manager` | IMAGE_LIBRARY 管理 | 画像在庫・GCS 化の話題 |
| `pr-review-gate` | PR 自動レビューフロー | PR 受信・レビュー依頼 |
| `pre-deploy-qa` | デプロイ前 QA | デプロイ・本番作業の話題 |
| `scheduler-readiness-check` | Scheduler 準備判定 | Scheduler ON の話題 |
| `sns-post-quality-check` | 投稿品質チェック | 投稿文チェックの話題 |
| `sop-writer` | SOP 生成 | 手順書・マニュアル化の話題 |

### 1.7 データレイヤー

```
data/
  master/         ← 事業プロファイル・取得プレイブック（CSV）
  acquisition/    ← 取得クエリ・ラン記録・重複インデックス（PAUSED）
  archive/        ← 休止システムのスナップショット
  reports/        ← 運用レポート（70+ ファイル、整理要）
```

### 1.8 ガバナンス現状

| ファイル | 役割 | 状態 |
|---|---|---|
| `CLAUDE.md` | Claude Code 司令塔ルール | ✅ 運用中 |
| `AGENTS.md` | Codex 120 点審査ルール | ✅ 運用中（PR #6 で導入）|
| `TEAM_RULES.md` | 全員共通ルール | ✅ 運用中 |
| `TASK.md` | 実装タスク指示書 | ✅ TASK-001 DONE |
| `REPORT.md` | 実装完了報告 | ✅ 運用中 |
| `.github/pull_request_template.md` | PR チェックリスト | ✅ 運用中 |
| `scripts/agent/pr_auto_flow.sh` | PR 自動フロー | ✅ 実装済み |
| `scripts/agent/safe_auto_merge_pr.sh` | 安全 Merge 監査 | ✅ 実装済み |

### 1.9 既知の技術的負債

| 負債 | 場所 | 重大度 | 内容 |
|---|---|---|---|
| 設定二重管理 | `configs/business_registry.py` vs `core/multi_business_content_engine.py` | HIGH | 事業設定が2か所に存在、同期漏れリスク |
| LINE トークン命名不統一 | 全 core/ | HIGH | `LINE_STAFF_TOKEN`, `LINE_TACHINOMIYASTAFF_TOKEN`, `LINE_cateringSTAFF_TOKEN` 等が混在 |
| DRY_RUN 未実装 | `core/multi_business_content_engine.py` | HIGH | `owner_daily.py` には DRY_RUN あり、content engine にはなし |
| OpenAI 依存 | `core/executive_team.py`, `core/multi_business_content_engine.py` | MEDIUM | 記憶の「OpenAI 禁止」ルールと矛盾（既存コードは維持）|
| data/reports/ 過増殖 | `data/reports/` | MEDIUM | 70+ ファイル、同一目的の重複多数 |
| broadcast API リスク | `core/multi_business_content_engine.py:384` | HIGH | TACHINOMIYA が broadcast → スタッフ誤通知リスク |
| TACHINOMIYA LINE 未設定 | Cloud Run 環境変数 | HIGH | `LINE_TACHINOMIYASTAFF_TOKEN` 空化がゆうさんの手動タスク |

---

## 2.0 レイヤー設計

2.0 は既存 1.x を **削除せず**、上位レイヤーとして追加する。

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 13: Archive（休止システム・ロールバック手順）         │
├─────────────────────────────────────────────────────────────┤
│  LAYER 12: Sale Readiness（売却準備・引き渡し文書）         │
├─────────────────────────────────────────────────────────────┤
│  LAYER 11: Automation Control（Scheduler・Circuit Breaker）  │
├─────────────────────────────────────────────────────────────┤
│  LAYER 10: Revenue Engine（集客・売上直結）                  │
├─────────────────────────────────────────────────────────────┤
│  LAYER 9:  Executive Command Center（CEO・MCP・Dashboard）  │
├─────────────────────────────────────────────────────────────┤
│  LAYER 8:  Quality Gates（投稿品質・Scheduler 準備・QA）    │
├─────────────────────────────────────────────────────────────┤
│  LAYER 7:  Notification Gateway（単一通知ルーター）          │
├─────────────────────────────────────────────────────────────┤
│  LAYER 6:  Workflow Engine（PR フロー・コンテンツパイプ）   │
├─────────────────────────────────────────────────────────────┤
│  LAYER 5:  Skill Registry（7 スキル + 活性状態管理）        │
├─────────────────────────────────────────────────────────────┤
│  LAYER 4:  Agent Registry（エージェント台帳・生命周期）     │
├─────────────────────────────────────────────────────────────┤
│  LAYER 3:  Data Contracts（統一スキーマ・単一設定源）        │
├─────────────────────────────────────────────────────────────┤
│  LAYER 2:  Domain Boundaries（5 ドメイン分離）              │
├─────────────────────────────────────────────────────────────┤
│  LAYER 1:  Governance Shell（Claude Code/Codex ルール）     │
├─────────────────────────────────────────────────────────────┤
│  LAYER 0:  1.x Core（既存コード・触らない）                 │
│   core/ agents/ configs/ skills/ scripts/ data/ docs/       │
└─────────────────────────────────────────────────────────────┘
```

---

## Layer 0: 1.x Core（現状維持・変更禁止）

**内容**: 現行 `core/`, `agents/`, `configs/`, `skills/`, `scripts/`, `data/`, `docs/`

**原則**:
- このレイヤーへの直接変更はすべて高リスク PR として人間承認必須
- 2.0 は読み取り・呼び出しのみ行う

---

## Layer 1: Governance Shell

**既存（変更禁止）**:
- `CLAUDE.md` — Claude Code 司令塔ルール
- `AGENTS.md` — Codex 120 点審査
- `TEAM_RULES.md` — 全員共通ルール
- `TASK.md` / `REPORT.md` — タスク・報告書
- `scripts/agent/pr_auto_flow.sh` — PR 自動フロー

**2.0 追加要件（設計のみ）**:
- FIX_ATTEMPT カウンターの永続化（現状は stateless）
- PR ラベル自動付与（`low-risk` / `high-risk` / `human-approval-required`）
- STOP 判定のアラート → `LINE_OWNER_TOKEN` 通知

---

## Layer 2: Domain Boundaries

5 ドメインを正式に分離する。

```
Domain A: CONTENT（コンテンツ生成・配信）
  ├─ Google 投稿生成
  ├─ Threads 投稿・返信
  ├─ Instagram 投稿
  ├─ LINE 配信
  └─ HPB ブログ

Domain B: FINANCE（財務・売上管理）
  ├─ POS データ取込
  ├─ 週次・月次レポート
  ├─ キャッシュフロー
  ├─ 利益漏れ検知
  └─ 口コミ・紹介エンジン

Domain C: ACQUISITION（新規顧客獲得）
  └─ [PAUSED] 商品マッチ先 AI エージェント

Domain D: HEALTH（システム監視）
  ├─ Cloud Run 死活監視
  ├─ Scheduler 状態確認
  ├─ Sheets 接続確認
  └─ 月次売上危険アラート

Domain E: INTELLIGENCE（経営知識・意思決定）
  ├─ AI 役員週次ブリーフィング
  ├─ MCP サーバー（Read-Only 8 ツール）
  ├─ CEO Dashboard
  └─ SNS PDCA 分析
```

**ドメイン間通信ルール**:
- ドメインをまたぐ書き込みは禁止
- ドメインをまたぐ読み取りは `LINE_OWNER_TOKEN` 通知を伴う場合のみ許可
- Domain C（ACQUISITION）は現在 PAUSED = いかなるドメインからも起動禁止

---

## Layer 3: Data Contracts

→ 詳細は `docs/YU_BUSINESS_OS_2_DATA_CONTRACTS.md` を参照

**2.0 で標準化する項目**:

### 3.1 事業設定の単一源化

現状: `configs/business_registry.py`（Python）と `core/multi_business_content_engine.py`（`_BUSINESS_CONFIGS` dict）が別々に存在し同期漏れリスクがある。

2.0 方針: `configs/business_registry.py` を唯一の設定源とし、`_BUSINESS_CONFIGS` は `business_registry.py` から動的に生成する（高リスク PR として実装）。

### 3.2 LINE トークン命名規則

現状（不統一）:
```
LINE_STAFF_TOKEN           # Tree Beauty スタッフ
LINE_TACHINOMIYASTAFF_TOKEN # TACHINOMIYA スタッフ（broadcast リスク）
LINE_cateringSTAFF_TOKEN    # Catering スタッフ
LINE_hinabeSTAFF_TOKEN      # Hinabe スタッフ
LINE_OWNER_TOKEN            # オーナー専用（安全）
```

2.0 命名規則（環境変数リネーム計画、実装は個別高リスク PR）:
```
LINE_{BUSINESS_SHORT_UPPER}_STAFF_TOKEN   # スタッフ（broadcast注意）
LINE_OWNER_TOKEN                          # オーナー専用（現状維持）
LINE_{BUSINESS_SHORT_UPPER}_CUSTOMER_TOKEN # 顧客チャネル（broadcast 要承認）
```

### 3.3 CloudRun レスポンス標準フォーマット

```json
{
  "ok": true/false,
  "business": "string",
  "mode": "dry|live|owner_only|staff",
  "timestamp": "ISO-8601",
  "steps": [...],
  "errors": [...],
  "next_actions": [...]
}
```

### 3.4 DRY_RUN 標準化

2.0 では全 content endpoint に `DRY_RUN` モードを追加する（高リスク PR）:

```
環境変数: EXECUTION_MODE
  dry        → 一切の書き込み・送信をしない（デフォルト）
  owner_only → LINE_OWNER_TOKEN へのみ通知
  live       → 本番（ゆうさんの明示承認後のみ）
```

---

## Layer 4: Agent Registry

**目的**: エージェントのライフサイクルを一元管理する

```yaml
agents:
  product_match_acquisition:
    status: PAUSED
    paused_at: 2026-07-08
    paused_reason: ゆうさん判断（再開禁止）
    resume_requires: ゆうさん明示承認
    data_archive: data/archive/acquisition_paused_20260708/
  
  # 2.0 で追加予定エージェント（現時点では設計のみ）
  content_quality_agent:
    status: NOT_BUILT
    domain: CONTENT
    purpose: 投稿品質の自動スコアリング

  health_alert_agent:
    status: NOT_BUILT
    domain: HEALTH
    purpose: Cloud Run 障害の即時オーナー通知
```

---

## Layer 5: Skill Registry

**全 7 スキルの正式状態**:

| スキル | 状態 | 発動 | 備考 |
|---|---|---|---|
| `debt-collection` | ACTIVE | 手動 | 督促テンプレート |
| `image-library-manager` | ACTIVE | 手動 | TACHINOMIYA 整備で使用中 |
| `pr-review-gate` | ACTIVE | PR 受信時 | 自動フロー統合済み |
| `pre-deploy-qa` | ACTIVE | デプロイ前 | 必須ゲート |
| `scheduler-readiness-check` | ACTIVE | Scheduler ON 前 | TACHINOMIYA ALMOST_READY |
| `sns-post-quality-check` | ACTIVE | 投稿前 | 品質スコア 0-10 |
| `sop-writer` | ACTIVE | SOP 作成時 | スタッフ指示変換 |

---

## Layer 6: Workflow Engine

### 6.1 PR フロー（既存、変更なし）

```
PR 作成 → Claude Code レビュー (GO/FIX/STOP)
  └─ GO → Safe Merge Gate
           ├─ 低リスク → 自動 Merge
           └─ 高リスク → 人間承認待ち
  └─ FIX → 自動修正 × 最大 2 回 → 3 回目で停止
  └─ STOP → 即停止・人間報告
```

### 6.2 コンテンツパイプライン（既存）

```
毎朝 09:00 Cloud Scheduler
  → content-automation endpoint
  → multi_business_content_engine.run()
  STEP1: Sheets から未通知行取得
  STEP2: 画像生成（OpenAI gpt-image-1）
  STEP3: GCS 保存
  STEP4: LINE 通知（各事業トークン）
  STEP5: 通知済みステータス更新
  STEP6: エラー処理（最大 3 回リトライ）
  STEP7: SYSTEM_LOG 記録
```

### 6.3 画像管理パイプライン（既存）

```
毎週日曜 21:00 Cloud Scheduler
  → scan-drive-images endpoint
  → image_manager.scan_drive_images()
  → Drive スキャン → Vision 分析 → IMAGE_LIBRARY 登録
  → GCS 化（_fixed.jpeg）→ HTTP200 確認
```

---

## Layer 7: Notification Gateway

**現状の問題点**:
- 事業ごとに異なる LINE トークンを直接使用
- TACHINOMIYA: `LINE_TACHINOMIYASTAFF_TOKEN` + broadcast API = スタッフ誤通知リスク
- DRY_RUN モードが一部のモジュールにしか存在しない

**2.0 設計（単一ゲートウェイ）**:

```python
class NotificationGateway:
    """
    全通知はこのゲートウェイを経由する。
    LINE_OWNER_TOKEN 以外への通知はゆうさん明示承認が必要。
    """
    
    ROUTES = {
        "owner": "LINE_OWNER_TOKEN",          # 常に安全
        "staff_{biz}": "LINE_{BIZ}_STAFF_TOKEN", # ゆうさん承認必須
        "customer_{biz}": "LINE_{BIZ}_CUSTOMER_TOKEN", # 承認必須
    }
    
    def send(self, channel: str, message: str, mode: str = "dry"):
        if mode == "dry":
            print(f"[DRY_RUN] → {channel}: {message[:50]}")
            return {"ok": True, "dry_run": True}
        if channel != "owner" and not self._human_approved(channel):
            raise PermissionError(f"ゆうさん承認なしに {channel} へは送信できません")
        ...
```

**実装方針**: 新規高リスク PR として実装（既存コードは変更しない）

---

## Layer 8: Quality Gates

### Gate 1: SNS Post Quality（`skills/sns-post-quality-check`）
- 投稿文を 0-10 点でスコア
- PASS(8+) / REVISE(5-7) / BLOCK(0-4) で判定
- 完全自動投稿前の必須ゲート

### Gate 2: Scheduler Readiness（`skills/scheduler-readiness-check`）
- READY / ALMOST_READY / NOT_READY の 3 段階
- TACHINOMIYA: 現在 ALMOST_READY（画像不足が未解消）

### Gate 3: Pre-Deploy QA（`skills/pre-deploy-qa`）
- デプロイ前の GO/STOP 判定
- Secret 混入・誤プロジェクト・Scheduler 誤 ON の 4 大事故防止

### Gate 4: PR Review（`skills/pr-review-gate` + `AGENTS.md`）
- 12 観点レビュー（Codex 120 点）
- GO/FIX/STOP 判定・FIX_ATTEMPT 最大 3 回

---

## Layer 9: Executive Command Center

### 9.1 CEO Dashboard（`apps_script/ceo_dashboard_v2.js`）
- YU HOLDINGS 全体売上ダッシュボード
- Google Sheets ベース

### 9.2 AI 役員週次ブリーフィング（`ceo/executive_team.py`）
- AI COO / CFO / CMO / CTO の役割分担
- 毎週月曜 8:00 自動実行
- 結果は CEO Dashboard + LINE に送信

### 9.3 MCP サーバー（`core/mcp_server.py`）
- Read-Only 8 ツール本番稼働
- OAuthなしで登録（現状維持）
- ツール一覧: `get_cash_flow_status`, `get_catering_sales_status`, `get_daily_action_status`, `get_knowledge_status`, `get_lead_status`, `get_owner_briefing`, `get_profit_leak_status`, `get_system_health`

---

## Layer 10: Revenue Engine

### 10.1 集客直結 5 エンジン（`core/growth_engines.py`）
- SNS スクショ OCR
- 勝ち投稿再利用
- MEO（GBP）
- 失客復活
- 高粗利訴求

### 10.2 ケータリング営業システム（`core/catering_sales.py`, `core/catering_report.py`）
- 週次・月次レポート自動生成
- 見込み客管理

### 10.3 SNS PDCA（`core/sns_pdca.py`）
- Google/Threads/LINE 投稿記録・分析・改善
- Phase1-2 本番稼働・900 件取込済
- Phase3（Gemini リライト）API キー待ち

### 10.4 GBP 自動投稿（`core/gbp_api.py`）
- 3 事業 Google 投稿自動化
- キュー 267 件・DRY_RUN 済
- コード準備完了・未デプロイ（API 承認待ち）

---

## Layer 11: Automation Control

### 11.1 Scheduler 管理方針

| 事業 | 状態 | 変更条件 |
|---|---|---|
| Tree Beauty | ON（推定） | 変更禁止 |
| Catering | ON（推定） | 変更禁止 |
| TACHINOMIYA | OFF | READY 判定後ゆうさん承認必須 |
| 琉球火鍋 | 確認要 | 変更禁止 |
| パスタパスタ | 確認要 | 変更禁止 |
| Z1 | 確認要 | 変更禁止 |

**変更禁止ルール**: Claude Code は `daily_post_limit`, `posting_window`, Scheduler ON/OFF のいかなる変更も行わない。

### 11.2 Circuit Breaker（2.0 設計）

```python
class AutomationCircuitBreaker:
    """
    自動化が暴走した場合の緊急停止。
    全 Scheduler を一括停止する。
    実行は ゆうさんの明示承認後のみ。
    """
    def emergency_stop(self, reason: str):
        # Cloud Scheduler Admin API で全ジョブを PAUSED に
        # LINE_OWNER_TOKEN に緊急通知
        # data/reports/ に incident log 記録
        pass
```

---

## Layer 12: Sale Readiness

**TACHINOMIYA 自動化 READY 条件**（現状 ALMOST_READY）:

| 条件 | 現状 | 期限 |
|---|---|---|
| 店舗内観 5 枚以上 | 1 枚 | 2026-07-18 |
| ドリンク 8 枚以上 | 3 枚 | 2026-07-25 |
| 店舗外観 10 枚以上 | 4 枚 | 2026-07-25 |
| Threads トークン期限確認 | 未確認 | Scheduler ON 前 |
| Google 認証有効性確認 | 未確認 | Scheduler ON 前 |
| LINE 通知先確認（Q1=YES 対応中）| 対応中 | ゆうさん手動 |
| Google 投稿 90 件テーマ一致 | FIX | 画像補充後 |

---

## Layer 13: Archive

**休止システム一覧**:

| システム | 休止日 | 保存場所 | 再開条件 |
|---|---|---|---|
| 商品マッチ先 AI エージェント | 2026-07-08 | `data/archive/acquisition_paused_20260708/` | ゆうさん明示承認のみ |
| Tree Beauty 商品マッチ | 2026-07-08 | 同上 | INACTIVE 維持 |

**ロールバック手順**: `data/reports/tachinomiya_rollback_procedure.txt` 参照

---

## 依存関係マップ

```
GCP Project: tree-beauty-ai-499303 (asia-northeast1)
│
├── Cloud Run (7 サービス)
│   └── 共通: Dockerfile + gunicorn + Flask
│
├── Cloud Scheduler (各事業 + 全体監視)
│   └── HTTP POST → Cloud Run エンドポイント
│
├── Google Cloud Storage
│   └── バケット: tree-beauty-blog-images
│       ├── image-library/tachinomiya/ (96 枚 _fixed.jpeg)
│       ├── content/TreeBeauty/
│       ├── content/Catering/
│       └── content/Tachinomiya/
│
├── Google Sheets (事業別スプレッドシート × 6)
│   ├── Tree Beauty SS: 1I6wRRD...
│   ├── Catering SS: 1tNE35i...
│   ├── TACHINOMIYA SS: 1K4KkAh...
│   ├── 琉球火鍋 SS: 1jwFmQt...
│   ├── パスタパスタ SS: 1MVz203...
│   └── Z1 SS: 10YHdIx...
│
├── Google Drive (POS データフォルダ × 3 事業)
│
├── LINE Messaging API
│   ├── LINE_OWNER_TOKEN (安全)
│   ├── LINE_STAFF_TOKEN (beauty スタッフ)
│   ├── LINE_TACHINOMIYASTAFF_TOKEN (broadcast リスク、Q1=YES で空化中)
│   ├── LINE_cateringSTAFF_TOKEN
│   └── LINE_hinabeSTAFF_TOKEN
│
├── Threads API
│   └── THREADS_ACCESS_TOKEN (60 日有効、期限確認要)
│
└── OpenAI API (既存 1.x のみ使用、新規追加禁止)
    ├── gpt-image-1 (コンテンツ画像生成)
    └── executive_team.py (役員ブリーフィング)
```

---

## Phase A 実装記録（2026-07-11）— Layer 1 / 4 / 5 の土台

Layer 1（Governance）・Layer 4（Agent Registry）・Layer 5（Skill Registry）の
**最小安全実装**を追加した。既存 Layer 0（1.x Core）には一切接続していない
（import 可能・検索 API・検証 CLI・Unit Test まで。本番配線は次 Phase）。

### 追加ファイル（新規のみ・既存の削除/移動なし）

```
configs/skills/registry.yaml         Skill Registry（10件: active 7 / inactive 3）
configs/agents/registry.yaml         Agent Registry（9件: active 3 / inactive 6）
configs/governance/policies.yaml     Governance Policy（21ポリシー + リスク定義）

core/registry/__init__.py            公開 API
core/registry/_yaml_min.py           依存ゼロの YAML サブセットパーサ（PyYAMLがあれば優先）
core/registry/models.py              dataclass + Enum（標準ライブラリのみ）
core/registry/skill_registry.py      Skill Loader（fallback / path安全 / 重複検知）
core/registry/agent_registry.py      Agent Loader（default deny / 参照整合）
core/governance/__init__.py          公開 API
core/governance/validator.py         GO/FIX/STOP/OWNER_APPROVAL_REQUIRED 判定

scripts/registry/validate_registry.py  整合性 CLI（exit 0=GO / 1=FIX / 2=STOP）
tests/registry/*, tests/governance/*   Unit Test 52件（stdlib unittest）
```

### なぜ依存ゼロか

`no_external_send` / 外部通信ゼロ方針と「新規ライブラリ最小限」を満たすため、
YAML は内蔵パーサ、モデルは dataclass、テストは stdlib `unittest` で実装した
（PyYAML 未インストール・pytest 未インストール環境でも動作する）。
`config/` ではなく既存の `configs/` を採用（設計書の「既存命名規約を優先」に従う）。

### Layer 別の実装状況

| Layer | 実装状況 |
|---|---|
| Layer 1 Governance | Validator + Policy を実装。PR フロー本体（既存）は不変 |
| Layer 4 Agent Registry | 台帳 + Loader 実装。全 Agent default deny |
| Layer 5 Skill Registry | 台帳 + Loader + fallback 実装。実在 SKILL.md のみ正パス |
| Layer 0 / 2 / 3 / 6-13 | 未接続（設計のまま）|

---

## Phase B1 実装記録（2026-07-11）— Layer 3 Business Config SSOT（Shadow）

Layer 3（Data Contracts）の中核として、事業設定の **Single Source of Truth**
を shadow mode で追加した。本番読込元は既存のまま（未接続）。

### 配置と責務

```
configs/businesses/registry.yaml       SSOT データ（6事業・secret-free）
core/business_config/
  models.py          スキーマ（dataclass + enum）
  loader.py          読込・検証・クエリ（fail-closed）
  legacy_adapter.py  既存設定を AST 静的読取（import/exec なし）
  comparator.py      SSOT ↔ Legacy 差分 → GO/FIX/STOP
scripts/business_config/validate_business_configs.py   検証 CLI（exit 0/1/2/3）
```

### 責務境界（二重管理の解消方針）

| 層 | 責務 |
|---|---|
| `configs/businesses/registry.yaml` | 事業設定の正本（shadow・env 名のみ・値なし）|
| `configs/business_registry.py`（既存）| 本番の実読込元（**変更しない**）|
| `_BUSINESS_CONFIGS`（既存）| content engine の実読込元（**変更しない**）|
| Comparator | 正本と Legacy の乖離を検出（自動上書きしない）|

現状は 5 箇所（`business_registry.py` / `_BUSINESS_CONFIGS` /
`system_health.py` / `executive_team.py` / `entrypoint.py`）に事業設定が分散。
SSOT はこれらを統合する上位正本だが、Phase B1 では **読取・比較のみ**。

---

## Phase B2-4 Batch 1 実装記録（2026-07-11）— SSOT 値の供給（3事業）

SSOT を「判定に使うだけ」から、**SSOT の値を Legacy 互換 config に変換して Runtime
へ供給できる状態**へ進めた。対象は **TACHINOMIYA / TREE'S CATERING / TREE BEAUTY**。

### Config Builder の責務と配置

```
core/business_config/config_builder.py   SSOT → Legacy 互換 dict へ変換 + shape 検証
core/business_config/config_supply.py     3事業の供給判定（comparator + builder）
core/business_config/runtime_loader.py    apply_runtime_config を supply へ拡張
scripts/business_config/check_ssot_config_supply.py  供給検証 CLI
```

### Builder の設計（安全な部分供給）

- SSOT が所有するスカラー（`monthly_target` / `business_type` / `status` /
  `cloud_run_service`）のみを legacy dict の**ディープコピー**へ overlay
- それ以外（menu_map / content_themes / line_channels / email / pos folder …）は
  legacy から**そのまま通す**
- **LINE の env 名は overlay しない**（実 Cloud Run env は legacy 名で設定されており、
  名前変更は本番切替＝禁止）
- 入力 legacy は**変更せず**新規 dict を返す。Secret 値は読まない（env 名のみ）
- SSOT フィールド欠損/型不一致 → FIX（Legacy fallback）/ 事業ID不一致 → STOP

対象外3事業（`ryukyu_hinabe` / `pasta_pasta` / `z1`）の Runtime 挙動は不変。

---

## Phase B2-6 実装記録（2026-07-12）— Readiness 承認 + Activation Dry Run

owner の readiness 承認を監査可能に記録し、4事業の本番接続を **Dry Run** で判定
（実 deploy はしない）。

### 追加コンポーネント

```
configs/governance/readiness_approvals.yaml   Owner 承認台帳（READINESS scope のみ）
core/business_config/approvals.py             台帳ローダ（deploy/scheduler/send は false 強制）
core/business_config/tachinomiya_audit.py     token/GBP/画像の read-only 監査（値は読まない）
core/business_config/readiness.py             台帳連携 + PHOTO_PENDING_READY 追加
core/business_config/activation.py            本番接続 Dry Run + Plan + Rollback 検証
scripts/business_config/dry_run_ssot_activation.py  Dry Run CLI（exit 0-5）
```

### 承認スコープの分離（越権防止）

readiness 承認は **deploy / Scheduler / external-send 承認とは別物**。台帳は
各承認を独立フラグで持ち、B2-6 では deploy/scheduler/send は全て false。
readiness 承認を deploy 承認へ拡大解釈しない。

### Activation は Dry Run のみ

deploy コマンドは**候補文字列として生成**するだけで**実行しない**。deploy 承認が
無いため、READY 事業でも `DEPLOY_APPROVAL_REQUIRED` で停止。本番操作ゼロ。

---

# Release & Operations OS（Phase R 設計 2026-07-15）

**目的**: PR Merge 後、ゆうさんの YES 1回で テスト → Staging → 本番反映 → 監視 →
異常時 Rollback → 記録・報告まで自動完了させる。PR #20（画像生成停止）で1日を要した
手作業（ローカル環境差・重複テスト・貼り付け・認証待ち・手動 Revision 確認）をゼロ化する。

## R.0 全体フロー（正）

```
PR Merge (main)
  └─ release.yml 起動（GitHub Actions / 固定CI環境）
      ├─ [1] Change Classification（diff_risk.py 拡張・正本1つ）
      ├─ [2] Test Selection → 実行（同一SHAでPASS済みならskip）
      ├─ [3] Build 1回（Cloud Build → Artifact Registry, image=SHA）
      ├─ [4] Staging = 本番サービスへ --no-traffic --tag candidate revision
      ├─ [5] Smoke Test（tag URL / read-only / endpoint registry 準拠）
      ├─ [6] LINE 通知「本番反映承認」+ 承認リンク
      ├─ [7] Owner YES（GitHub Environment 承認 = 正本・1タップ・1回）
      ├─ [8] Progressive Deploy: catering → tachinomiya → beauty（1サービスずつ traffic昇格）
      │       各サービス: snapshot → promote → smoke → log check → GO/ROLLBACK
      ├─ [9] 異常時: 旧Revision traffic100% 自動Rollback → 後続停止 → LINE即通知
      ├─ [10] Deployment Ledger 記録（GCS・正本1つ）
      └─ [11] LINE 完了報告
```

ゆうさんの操作 = **[7] の YES/NO 1回のみ**。貼り付け・ターミナル・Revision確認ゼロ。

## R.1 Component 責任分界

| 主体 | 責任 | してはならないこと |
|---|---|---|
| Fable 5 | Architecture / 移行 / リスク設計 | 実装・deploy |
| Claude Code (Opus) | コード・テスト・Workflow 実装、PR 作成 | 本番 deploy（CLAUDE.md 禁止を維持） |
| Codex | 独立レビュー（security/governance/rollback/workflow） | 実装・deploy |
| GitHub Actions | test / build / staging / **production deploy** / smoke / rollback / ledger / 通知 | Scheduler 変更・Secret 直書き・対象外事業 deploy |
| Cloud Build | コンテナ build（SHA タグ・1回） | deploy 判断 |
| ゆうさん | YES / NO、CRITICAL時のみ手動 | （通常運用で手作業なし） |

**Claude Code 禁止と実行設計の矛盾解消**: 本番反映の実行主体を GitHub Actions
（Workload Identity Federation で認証された machine identity）に移す。Claude Code は
Workflow *コード* を PR で書くだけ。CLAUDE.md の禁止は今後も有効。

## R.2 12機能の設計

### (1) Change Classification Engine — 正本は `core/governance/diff_risk.py`

既存 `classify_paths()`（CRITICAL/HIGH/MEDIUM/LOW・blocked prefix・secret/runaway scan）を
**唯一の分類正本**として拡張する。新規分類器は作らない。

追加する関数（同ファイル内）:
- `classify_change(paths) -> ChangeReport`: 既存 risk 判定 + カテゴリ判定
  （docs_only / content_policy / sns_post / image_policy / business_config / ssot /
  core_runtime / cloud_run_service / scheduler / secret_reference / external_send /
  acquisition / tree_beauty / financial / deployment_workflow）
- 対象事業・対象サービスは `configs/businesses/registry.yaml`（既存 SSOT）の
  `cloud_run_service` から**導出**する。手動の対応表は持たない。

出力（JSON, Data Contracts 参照）: risk_level / categories / businesses / services /
required_tests / deploy_required / approval_required / auto_rollback / prohibited。
CLI: `scripts/release/classify_change.py`（薄いラッパのみ。判定ロジックは diff_risk.py）。

### (2) Test Selection Engine

`tests/` は既にドメイン分割済み（agent / business_config / content / governance / registry）。
カテゴリ→テストセットの対応は classification 出力に含め、Actions の job summary に記録
（監査可能）。

| カテゴリ | テストセット |
|---|---|
| docs_only | なし（lint のみ） |
| content_policy / image_policy | tests/content + tests/governance |
| business_config / ssot | tests/business_config + tests/registry |
| sns_post | tests/content + 該当 smoke |
| deployment_workflow | workflow 構文 + dry-run + tests/governance |
| **core_runtime / governance / secret_reference / external_send / cross-business / production routing** | **Full suite（強制・選択不可）** |

**重複実行防止**: `PASS 記録 = commit SHA + testset hash` を GitHub Actions cache/check-run に
保存。同一 SHA・同一セットが PASS 済みなら skip（ログに SKIPPED_ALREADY_PASSED を明記）。
現在 Full suite は約5秒（388件）なので、MVP では「Full suite を SHA ごとに1回だけ」で
15分 KPI を満たす。選択エンジンはテスト増加に備えた将来レバー。

### (3) Fixed CI Environment — 採用: GitHub Actions + requirements.lock

| 案 | 安全 | 実装コスト | 再現性 | 採点 |
|---|---|---|---|---|
| **A. ubuntu-24.04 pin + setup-python 3.11 pin + requirements.lock（pip-compile）** | 高 | 最小 | 高 | **88 — 採用** |
| B. 全ジョブ Docker（python:3.11-slim） | 高 | 中 | 最高 | 80（起動遅・保守増） |
| C. uv + uv.lock | 高 | 中 | 高 | 78（新ツール導入は今不要） |
| D. ローカル Mac 継続 | 低 | 0 | 最低 | 15（不採用・今回の事故原因） |

固定対象: runner `ubuntu-24.04`（bash 5 標準 → declare -A 事故根絶）、Python `3.11.x`
（Dockerfile と一致）、`requirements.lock`（requirements.txt から pip-compile 生成、正本は
requirements.txt）、gcloud は `google-github-actions/setup-gcloud@vX` を version pin、
timeout は全 job に `timeout-minutes` 必須。**ローカル Mac は開発専用**とし、release 経路
から完全排除。

### (4) Staging — 採用: 案B（本番サービスへ traffic 0% revision）

| 案 | 安全 | 月額 | 忠実度 | 採点 |
|---|---|---|---|---|
| A. 専用 Staging service ×3 | 高 | +数百円〜 + env二重管理 | 中（env drift） | 70 |
| **B. `--no-traffic --tag candidate` revision** | 高 | **0円** | **最高（本番env そのもの）** | **90 — 採用** |
| C. Preview service | 中 | 低 | 中 | 65 |
| D. Dry Run のみ | 中 | 0 | 低（実行経路未検証） | 55 |

`gcloud run deploy --image <SHA> --no-traffic --tag candidate` → tag URL
（`https://candidate---<service>.a.run.app`）に対して read-only smoke。承認後
`update-traffic --to-latest`。**Staging 段階での LINE 送信・投稿・GCS/Sheets 書込みは
禁止**（smoke は GET の /health /status のみ。POST endpoint は叩かない。Scheduler は
tag URL を知らないため誤発火しない）。

### (5) Smoke Test Engine

**endpoint registry を正本管理**: `configs/businesses/registry.yaml` の各事業に
`endpoints: {health: /health, status: /status}` を追記（推測禁止の根拠データ）。
検証項目: revision READY / health=200 / status=200 / business identity 一致 /
config source / image_generation=false / line_text=true / line_image=false /
startup・import・config load error なし / 5xx なし / Secret 露出なし。

**PR #20 の教訓**: 現在の `/status` は content policy フラグを返さない。Phase R3 で
`/status` に read-only 追加フィールド（`release: {commit, image_generation,
delivery_mode, config_source}`）を実装し、smoke がコード保証ではなく**実測**で確認
できるようにする。ログ検査は `gcloud run services logs read`（Actions の viewer SA）。

### (6) Owner Approval Gateway — 正本: GitHub Environment `production`

| 案 | 安全 | 実装コスト | YES体験 | 採点 |
|---|---|---|---|---|
| **A. GitHub Environment required reviewer（LINE は通知+リンク搬送）** | 最高（native 監査・PR/SHA紐付け・再利用不可） | 最小 | LINE内リンク1タップ→Approve | **92 — 採用** |
| B. LINE 返信 YES → webhook → GitHub API | 中（署名検証・nonce・token 管理を自作） | 高 | LINE 完結 | 70（R8 でオプション追加可） |
| C. 両方必須（二重承認） | 高 | 高 | 2回操作 | 40（YES 1回原則に反する・不採用） |

**二重化しない。GitHub Environment 承認が唯一の deploy 承認**。要件充足:
YES 1回限り＝1 deployment に1 approve / 有効期限＝Actions job timeout（30分）で失効 /
PR・サービス・Revision 紐付け＝deployment payload / 別 PR 流用不可＝run 単位 /
readiness・deploy・scheduler・external send の承認分離＝既存
`readiness_approvals.yaml` の分離原則を継承（Environment は deploy approval のみを表す）/
監査証跡＝GitHub native + Ledger 転記 / LINE 障害時＝GitHub UI/mobile から直接 Approve /
二重実行防止＝concurrency group + deployment lock（後述）。
B 案（LINE 返信 YES ブリッジ）は R8 のオプション: 既存 `line-task-webhook` で LINE 署名
検証 → pending approval の one-time nonce 照合 → Secret Manager 上の GitHub App token で
REST approve。MVP には含めない。

### (7) Progressive Production Deployment

順序（固定・registry から生成）: **catering → tachinomiya → beauty**（PR #20 実績と同順。
低リスク→高リスク、Beauty は GBP 依存が大きいため最後）。琉球火鍋は明示承認がある
release のみ末尾に追加。pasta_pasta / z1 / yu-holdings-ai は対象外リスト（deploy job が
サービス名を検証し、リスト外は即 STOP）。
build は SHA image を1回だけ作り、3サービスへ同一 image を `--image` で配布
（`--source` ×3 の重複 build を排除 → 時間短縮 + バイナリ一致保証）。
各サービス: snapshot（旧 revision 記録）→ promote → readiness → smoke → log check →
GO なら次へ。**1件失敗で後続停止**（`needs:` chain + fail-fast）。

### (8) Automatic Rollback

トリガ: revision READY 失敗 / health≠200 / status 異常 / business identity 不一致 /
config source 異常 / 5xx 増加 / startup・import・config error / Secret 露出疑い /
image_generation 誤有効化 / LINE 文章経路停止 / LINE 画像経路誤有効化 /
cross-business impact / timeout / unknown state（**不明は全て Rollback 側に倒す**）。
動作: `update-traffic --to-revisions <旧>=100` → 必要なら
`YU_CONFIG_RUNTIME_MODE=LEGACY_ONLY` へ戻す → health/status 再確認 → Ledger 記録 →
LINE 即通知 → 後続 deploy 停止。
**Rollback 失敗 = CRITICAL**: production lock を設置（deploy workflow 起動拒否）→
LINE + GitHub Issue の二重通知 → 人間 runbook（rollback.yml の workflow_dispatch で
service/revision を指定し再試行）。成功扱いにしない。

### (9) Deployment Ledger — 正本: GCS

| 保存先 | 改ざん耐性 | 検索性 | コスト | 運用負荷 | 採点 |
|---|---|---|---|---|---|
| GitHub Artifact | 低（90日で消える） | 低 | 0 | 低 | 40 |
| **GCS（versioning + retention lock）** | **高** | 中（BQ external table で拡張可） | ~¥10/月 | 低 | **90 — 採用** |
| Firestore | 中 | 高 | 低 | 中 | 72 |
| BigQuery | 中 | 最高 | 低 | 中 | 70（今は過剰） |
| Google Sheets | 低（可変・quota） | 中 | 0 | 中 | 45 |
| Repo JSON | 中 | 高 | 0 | 高（main push 禁止と衝突） | 50 |

`gs://yu-release-ledger/<deployment_id>.json`（object per deployment、bucket versioning +
retention policy で追記のみ）。書込みは専用 SA（objectCreator のみ）。GitHub Deployments
API の記録は副次証跡として自動併存。スキーマは Data Contracts 参照。

### (10) Timeout / Resume / Idempotency

- job 別 `timeout-minutes`: test 10 / build 15 / service deploy 10 / smoke 5 / 全体 45
- `concurrency: group: production-release`（同時実行キュー化・旧 run の二重起動防止）
- **deployment lock**: GCS `locks/production.lock` を `ifGenerationMatch=0` で作成
  （取得失敗＝他 deploy 進行中 → 待機 or 中止）。終了時削除、stuck は TTL で強制解放
- **resume**: Ledger の deployment_id + service 状態を見て、ACTIVATED 済みサービスを
  skip して途中再開（同一 deployment_id の再実行は冪等）
- heartbeat: 各 step の開始/終了を Ledger に逐次記録 → stuck 検知（1日ハングの根絶）
- retry 上限: deploy 1回・smoke 2回。超過は Rollback へ

### (11) Notification System

既存 OWNER_ONLY LINE 基盤を再利用。種別: approval required / started / service
activated / rollback executed / failed / timeout / credentials expired / manual
intervention required / final summary。**Secret・token・URL パラメータの個人情報は
載せない**。通知 step は `if: always()` + `continue-on-error: true` — 通知失敗が
deploy 本体を殺さない。通知不達時は GitHub Issue へフォールバック。

### (12) Human Override / Emergency Mode

- `rollback.yml`（workflow_dispatch）: service + 対象 revision を入力し即 rollback
- production lock: repo variable `PRODUCTION_FROZEN=true` + GCS lock → release.yml が
  起動時に検査し停止（deploy 停止 / traffic 固定 / service freeze を兼ねる）
- workflow cancel: GitHub UI 標準
- **emergency bypass**: 別 Environment `production-emergency`（reviewer 必須・理由入力
  必須・Ledger に bypass 記録・期限は当該 run 限り＝自動失効）。通常経路の Gate を
  恒久的に無効化する手段は設けない

## R.3 GitHub Actions 構成（最小3 Workflow + 1 composite）

8本に分けず、保守性優先で集約する:

| Workflow | trigger | 内容 |
|---|---|---|
| `pr-validation.yml` | pull_request | classification → selected tests → governance gate（既存 governance_gate.py 呼出し） |
| `release.yml` | push: main | classify → test(skip済み判定) → build 1回 → staging(no-traffic) → smoke → **environment: production 承認** → progressive deploy（composite 再利用×3） → ledger → notify。rollback ロジック内蔵 |
| `rollback.yml` | workflow_dispatch | 緊急手動 rollback（service / revision 指定） |
| composite: `deploy-service` | — | snapshot → promote → smoke → log check → rollback-on-fail（3サービスで再利用） |

## R.4 Secret / 権限設計

- **Workload Identity Federation 採用**（長期 SA key 全面禁止）。GitHub OIDC →
  該当 repo + environment 限定で impersonation
- SA 分離: `release-deployer`（run.developer + cloudbuild.builds.editor + AR writer）/
  `release-verifier`（run.viewer + logging.viewer）/ `release-ledger`
  （対象 bucket の objectCreator のみ）/ approval listener は R8 まで不要
- LINE token は Google Secret Manager 参照（Actions は accessor 権限、値は Workflow ログ
  へ出さない = `add-mask`）
- GitHub Environments: `production`（required reviewer=ゆうさん / branch=main 限定 /
  environment secrets）。wait timer は使わない（15分 KPI と矛盾）

## R.5 事業保護（deploy 経路への埋め込み）

- 対象サービス allowlist は registry から生成: catering / tachinomiya / beauty（＋明示
  承認時のみ ryukyu_hinabe）。**allowlist 外へは deploy job 自体が拒否**
- TACHINOMIYA: 写真在庫不足を READY 扱いしない（既存 readiness gate をそのまま利用）/
  Scheduler 無断 ON 禁止（release.yml は Scheduler API を一切呼ばない）
- Beauty: Tree Beauty 再有効化・Scheduler・投稿の同時変更禁止（classification が
  tree_beauty カテゴリを検知したら approval_required + CRITICAL 昇格）
- 琉球火鍋: 別オーナー。GBP 自動化対象外。明示承認なしに対象へ入れない
- pasta_pasta / z1: Release OS 対象外・Legacy 維持・自動 deploy 禁止（allowlist 外）

## R.6 Phase R1 実装結果（2026-07-15・本番非接触）

固定 CI + PR Validation を実装。監査で判明した事実に基づく実採用:

- **Runner**: `ubuntu-24.04`（bash 5 標準 → declare -A 事故根絶）
- **Python**: `3.11`（本番 `Dockerfile: python:3.11-slim` と一致）
- **依存固定**: `requirements.lock`（正本 `requirements.txt` を py3.11 クリーン環境で解決した
  完全 freeze・71パッケージ）。CI は `pip install --no-deps -r requirements.lock` で lock を
  唯一の真実として install。**CI 内 lock 生成はしない**。hash 固定は pip-tools/uv 導入が
  必要なため R1 では見送り（`==` 固定で再現性確保）
- **テスト**: `python -m unittest discover -s tests -p "test_*.py"`（stdlib unittest・388件）。
  成否は **exit code のみ**で判定（件数の文字列パースはしない＝失敗#9 の再発防止）。
  監査により、テストは `gspread`/`requests` を top-level import する core モジュール経由で
  第三者依存を必要とすることが判明 → CI での依存 install は必須
- **Governance Gate**: `scripts/agent/governance_gate.py --base origin/<base> --head HEAD`。
  exit を GO=0 / FIX=10 / OWNER_APPROVAL_REQUIRED=20 / STOP=30 / INTERNAL_ERROR=40 で判定。
  **20 は HIGH PR の正常状態（人間承認は merge 時）＝CI check は通す**が summary に明記。
  10/30/40 のみ check を落とす
- **Workflow**: `.github/workflows/pr-validation.yml` 1本のみ（既存 workflow はゼロ＝重複なし・
  Required Check 互換問題なし）。trigger= `pull_request(main)` + `workflow_dispatch`。
  `pull_request_target` は不使用（fork PR に Secret を渡さない）
- **権限**: `contents: read` + `pull-requests: read` のみ。`id-token` / `deployments` 無し
- **Timeout/Concurrency**: job `timeout-minutes: 20`、PR 単位 concurrency + cancel-in-progress
  （1日ハングと二重起動の構造的禁止）
- **本番非接触**: gcloud / deploy / Scheduler / Secret / GCS / LINE を一切呼ばない

## R.7 Phase R2 実装結果（2026-07-15・本番非接触）

Change Classification + Test Selection を実装。分類正本は `core/governance/diff_risk.py` の
**追加関数 `classify_change()`** 1つ（新規分類器を増やさず既存 helper を再利用・
`validator.py` の決定経路は無変更）。CLI `scripts/release/classify_change.py` が git diff から
分類 JSON を出力し、`pr-validation.yml` が `run_scope`（FULL / NONE / GROUPS・fail-closed）で
テストを選択実行。docs-only はテスト0、部分変更は該当グループのみ、危険/unknown/空 diff は
全実行。合計 413 テスト PASS。本番非接触。

## R.8 Phase R2.5 実装結果（2026-07-16・本番非接触）

Release Infrastructure Bootstrap を実装（`scripts/release/bootstrap_release_infra.sh`）。
`--plan`(既定・無変更) / `--verify`(read-only) / `--rollback-plan` / `--apply`(CONFIRM=yes +
gcloud + project 一致で人間実行) の4モード。構築対象＝WIF pool + OIDC provider(repo 限定) +
SA 3種(least privilege・長期key無し) + Artifact Registry + append-only GCS Ledger bucket +
repo variables。GitHub Environment は MANUAL_STEP_REQUIRED。実 gcloud で plan(変更0)/verify
(全 MISSING)/apply ガード(CONFIRM無で STOP)を検証。11テスト + FULL = 424 PASS。`--apply` は
オーナー実行（Claude Code は実行しない）。
