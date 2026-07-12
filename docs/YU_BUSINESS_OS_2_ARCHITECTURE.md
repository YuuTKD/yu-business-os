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
