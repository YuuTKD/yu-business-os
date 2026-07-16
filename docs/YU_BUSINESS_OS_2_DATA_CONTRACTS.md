# YU Business OS 2.0 — Data Contracts

作成日: 2026-07-11  
ステータス: 設計書（実装禁止・承認待ち）

**目的**: 全モジュール・API・データストア間のインターフェースを仕様化し、設定の二重管理・命名不統一・DRY_RUN 欠如を解消する設計基盤を提供する。

---

## Contract 1: 事業設定スキーマ（Business Config）

### 1.1 単一設定源（現状）

`configs/business_registry.py` が唯一の正本。

```python
class BusinessConfig(TypedDict):
    name:            str   # 事業正式名 例: "TACHINOMIYA"
    short_name:      str   # Cloud Run サービス名 例: "tachinomiya"
    email:           str   # 事業メール
    location:        str   # 所在地
    booking_url:     str   # 予約 URL
    monthly_target:  int   # 月商目標（円）
    services:        list  # サービスカテゴリ
    menu_map:        dict  # メニュー名 → カテゴリ
    media_channels:  list  # 集客媒体
    content_themes:  list  # コンテンツテーマ
    line_channels:   dict  # LINE チャネル設定（下記参照）
    platforms:       list  # 投稿先プラットフォーム
    csv_sources:     list  # CSV 取込元
    business_type:   str   # restaurant|salon|consulting|bar|retail
    cloud_run_service: str # Cloud Run サービス名
    spreadsheet_id_env: str # スプレッドシート ID の環境変数名
    spreadsheet_id:  str   # スプレッドシート ID（固定値）
    status:          str   # active|inactive
```

### 1.2 LINE チャネル設定スキーマ

```python
# line_channels の構造
{
    "staff": {
        "env_key":       str,   # 環境変数名 例: "LINE_TACHINOMIYASTAFF_TOKEN"
        "broadcast_ok":  bool,  # broadcast API 使用可否
    },
    "customer": {
        "env_key":       str,   # 例: "LINE_TACHINOMIYA_CUSTOMER_TOKEN"
        "broadcast_ok":  bool,  # 顧客への broadcast は原則 False
    },
}
```

### 1.3 現状の設定二重管理（技術的負債）

| 設定源 | 場所 | 事業数 | 問題 |
|---|---|---|---|
| `BUSINESSES` dict | `configs/business_registry.py` | 6 事業 | 正本 |
| `_BUSINESS_CONFIGS` dict | `core/multi_business_content_engine.py` | 4 事業 | 重複・同期漏れリスク |

**2.0 解消 PR（高リスク）の実装仕様**:

```python
# core/multi_business_content_engine.py に追加
from configs.business_registry import BUSINESSES as _REG

_CONTENT_BUSINESS_KEYS = ("beauty", "catering", "tachinomiya", "hinabe")

_SHEET_CONFIGS: dict[str, list] = {
    "beauty":      [...],  # シート名・列定義（現状維持）
    "catering":    [...],
    "tachinomiya": [...],
    "hinabe":      [...],
}

def _build_business_configs() -> dict:
    result = {}
    for key in _CONTENT_BUSINESS_KEYS:
        biz = _REG[key]
        result[key] = {
            "name":           biz["name"],
            "display":        f"{biz['name']}",
            "spreadsheet_id": biz.get("spreadsheet_id", ""),
            "line_token_env": biz["line_channels"]["staff"]["env_key"],
            "gcs_folder":     f"content/{biz['name'].replace(' ', '')}",
            "image_style":    key,
            "sheets":         _SHEET_CONFIGS.get(key, []),
        }
    return result

_BUSINESS_CONFIGS = _build_business_configs()
```

---

## Contract 2: Cloud Run レスポンススキーマ

### 2.1 標準成功レスポンス

```json
{
  "ok": true,
  "business": "TACHINOMIYA",
  "mode": "dry|live|owner_only",
  "timestamp": "2026-07-11T09:00:00+09:00",
  "steps": [
    {"step": 1, "name": "未通知行取得", "count": 3, "status": "ok"},
    {"step": 2, "name": "画像生成", "count": 3, "status": "ok"},
    {"step": 3, "name": "GCS 保存", "count": 3, "status": "ok"},
    {"step": 4, "name": "LINE 通知", "count": 0, "status": "skipped", "reason": "DRY_RUN"}
  ],
  "summary": {
    "processed": 3,
    "succeeded": 3,
    "failed": 0,
    "skipped": 0
  },
  "next_actions": []
}
```

### 2.2 標準エラーレスポンス

```json
{
  "ok": false,
  "business": "TACHINOMIYA",
  "mode": "dry",
  "timestamp": "2026-07-11T09:00:00+09:00",
  "error": {
    "code": "SPREADSHEET_NOT_FOUND",
    "message": "スプレッドシート 1K4KkAh... が見つかりません",
    "step": 1,
    "retryable": false
  },
  "next_actions": ["ゆうさんに TACHINOMIYA_SPREADSHEET_ID を確認してください"]
}
```

### 2.3 DRY_RUN レスポンス（2.0 追加）

```json
{
  "ok": true,
  "business": "TACHINOMIYA",
  "mode": "dry",
  "dry_run": true,
  "timestamp": "2026-07-11T09:00:00+09:00",
  "preview": {
    "would_post": 3,
    "would_notify": 0,
    "sample_content": "サーターアンダギー専門店TACHINOMIYAへようこそ..."
  }
}
```

---

## Contract 3: EXECUTION_MODE 環境変数スキーマ

### 3.1 現状（不統一）

| モジュール | DRY_RUN 実装 |
|---|---|
| `owner_daily.py` | ✅ あり（`DAILY_ACTION_LINE_MODE` = OFF/OWNER_ONLY/STAFF/DRY_RUN）|
| `multi_business_content_engine.py` | ❌ なし（空 token の安全弁のみ）|
| `entrypoint.py` | ✅ `EXECUTION_MODE=dry` で確認のみ |
| その他 | なし |

### 3.2 2.0 統一仕様

```
環境変数名: EXECUTION_MODE

値:
  dry        → 一切の書き込み・送信なし（デフォルト）
  owner_only → LINE_OWNER_TOKEN のみ通知（スタッフ不可）
  live       → 本番実行（ゆうさんの明示承認後のみ）
```

### 3.3 実装仕様（高リスク PR）

```python
# core/multi_business_content_engine.py に追加

import os

EXEC_MODE = os.getenv("EXECUTION_MODE", "dry")

def _should_send_line(token: str) -> bool:
    """LINE 送信可否を EXECUTION_MODE + トークン長で判定"""
    if EXEC_MODE == "dry":
        return False
    if len(token) < 100:
        return False  # 既存の安全弁
    if EXEC_MODE == "owner_only":
        # オーナートークンのみ許可
        owner_token = os.getenv("LINE_OWNER_TOKEN", "")
        return token == owner_token
    if EXEC_MODE == "live":
        return True
    return False  # フォールバック: 送信しない
```

---

## Contract 4: IMAGE_LIBRARY スキーマ

### 4.1 Google Sheets IMAGE_LIBRARY（Spreadsheet ID: `15cfsC2...`）

| 列名 | 型 | 説明 | 例 |
|---|---|---|---|
| `img_id` | string | 一意 ID | `tachinomiya_001` |
| `business` | string | 事業 key | `tachinomiya` |
| `image_theme` | string | 主テーマ | `サーターアンダギー` |
| `allowed_post_themes` | string (comma) | 使用可能テーマ | `おやつ,商品紹介,観光` |
| `blocked_post_themes` | string (comma) | 使用禁止テーマ | `外観,店内雰囲気` |
| `gcs_public_url` | string | GCS 公開 URL | `https://storage.googleapis.com/...` |
| `drive_file_id` | string | Drive ファイル ID | `1abc...` |
| `orientation_fixed` | bool | EXIF 向き修正済み | `TRUE` |
| `status` | string | active|inactive|pending | `active` |
| `registered_at` | datetime | 登録日時 | `2026-07-11 09:00` |
| `http_checked_at` | datetime | HTTP200 確認日時 | `2026-07-11 09:01` |

### 4.2 TACHINOMIYA 画像在庫（2026-07-11 現在）

| カテゴリ | 現在枚数 | 目標枚数 | 期限 | 状態 |
|---|---|---|---|---|
| 店舗内観 | 1 | 5 | 2026-07-18 | 撮影依頼中 |
| ドリンク | 3 | 8 | 2026-07-25 | 撮影依頼中 |
| 店舗外観 | 4 | 10 | 2026-07-25 | 撮影依頼中 |
| サーターアンダギー | 9 | 15 | 2026-08-31 | 依頼中 |
| BAR 雰囲気 | 6 | 10 | 2026-08-31 | 依頼中 |
| イベント | 3 | 6 | 次回開催時 | 待機 |

---

## Contract 5: LINE 通知スキーマ

### 5.1 通知メッセージフォーマット（TEXT）

```
[{事業名}] {タイトル}

{本文}

📍{ステータス情報}
⏰ {タイムスタンプ} JST
```

### 5.2 通知メッセージフォーマット（IMAGE + TEXT）

```json
{
  "messages": [
    {
      "type": "image",
      "originalContentUrl": "https://storage.googleapis.com/...",
      "previewImageUrl": "https://storage.googleapis.com/..."
    },
    {
      "type": "text",
      "text": "[TACHINOMIYA] 2026-07-11 Google投稿\n\nサーターアンダギー...\n\n✅ 投稿完了"
    }
  ]
}
```

### 5.3 通知チャネル優先順位（2.0 ルール）

```
優先順 1: EXECUTION_MODE=dry    → 送信なし（ログのみ）
優先順 2: EXECUTION_MODE=owner_only → LINE_OWNER_TOKEN のみ
優先順 3: EXECUTION_MODE=live + ゆうさん承認 → 各事業チャネル
```

---

## Contract 6: Scheduler ジョブスキーマ

### 6.1 現状ジョブ定義（推定）

| ジョブ名 | スケジュール | 対象サービス | エンドポイント |
|---|---|---|---|
| beauty-daily-content | 毎朝 09:00 JST | tree-beauty-ai | /content-automation |
| catering-daily-content | 毎朝 09:00 JST | trees-catering-ai | /content-automation |
| tachinomiya-daily-content | OFF | tachinomiya-ai | /content-automation |
| hinabe-daily-content | 未確認 | ryukyu-hinabe-ai | /content-automation |
| system-health | 毎朝 08:30 JST | yu-holdings-ai | /health-check |
| executive-briefing | 毎週月 08:00 JST | yu-holdings-ai | /executive-briefing |
| catering-weekly | 毎週月 08:00 JST | trees-catering-ai | /catering-weekly |
| drive-image-scan | 毎週日 21:00 JST | yu-holdings-ai | /scan-drive-images |
| catering-monthly | 毎月 1 日 | trees-catering-ai | /catering-monthly |

### 6.2 Scheduler 変更禁止条件

Claude Code が変更できる Scheduler 設定は **なし**。  
ゆうさんの明示的な指示 + 高リスク PR + 人間マージ後のみ変更可。

---

## Contract 7: PR フロースキーマ

### 7.1 PR メタデータ

```yaml
PR:
  number: int
  title: string
  branch: "feature/codex-{task_id}-{description}"
  risk_level: "low|high"
  labels:
    - "low-risk" | "high-risk"
    - "human-approval-required"  # high のみ
  review:
    status: "GO|FIX|STOP"
    fix_attempts: 0|1|2|3
    reviewer: "Claude Code"
  revenue_score: "S|A|B|C|D"
  checklist:
    - os_consistency: bool
    - no_existing_destruction: bool
    - cash_first: bool
    - no_secret_injection: bool
    - no_production_impact: bool
    - task_consistency: bool
    - report_updated: bool
    - revenue_score_check: bool
    - risk_classification: bool
    - automation_runaway_check: bool
    - fix_attempt_within_limit: bool
    - prohibition_check: bool
```

### 7.2 FIX_ATTEMPT 制限

```
FIX_ATTEMPT 0 → 初回レビュー
FIX_ATTEMPT 1 → 1 回修正済み
FIX_ATTEMPT 2 → 2 回修正済み（最終自動修正）
FIX_ATTEMPT 3 → 停止・人間確認必須
```

---

## Contract 8: GCS パス規則

### 8.1 現状のパスパターン

```
image-library/{business_lower}/{img_id}_{timestamp}_fixed.jpeg
  例: image-library/tachinomiya/tachinomiya_001_20260711090000_fixed.jpeg

content/{BusinessName}/{date}_{seq}.jpeg
  例: content/TreeBeauty/2026-07-11_001.jpeg
```

### 8.2 2.0 標準化仕様（新規 GCS アップロード時に適用）

```
image-library/{business_key}/{img_id}_{yyyymmddHHMMSS}_fixed.jpeg
```

**ルール**:
- パス区切りは `/` のみ（スペース・日本語禁止）
- business_key は `configs/business_registry.py` の key 値を使用
- `_fixed.jpeg` の接尾辞は EXIF 補正済みを示す

---

## Contract 9: System Health スキーマ

### 9.1 ヘルスチェック結果フォーマット

```json
{
  "checked_at": "2026-07-11T08:30:00+09:00",
  "services": {
    "tree-beauty-ai": {"status": "ok", "http_code": 200},
    "tachinomiya-ai": {"status": "ok", "http_code": 200},
    "...": {}
  },
  "schedulers": {
    "beauty-daily-content": {"state": "ENABLED", "last_run": "2026-07-11T09:00:00+09:00"},
    "tachinomiya-daily-content": {"state": "PAUSED", "reason": "Scheduler OFF（ALMOST_READY）"}
  },
  "spreadsheets": {
    "tree-beauty": {"accessible": true},
    "tachinomiya": {"accessible": true}
  },
  "alerts": []
}
```

### 9.2 アラートレベル

```
CRITICAL → LINE_OWNER_TOKEN に即時通知 + Scheduler 自動停止検討
WARNING  → LINE_OWNER_TOKEN に通知 + ゆうさん確認待ち
INFO     → ログのみ
```

---

## Contract 10: MCP サーバーツールスキーマ

### 10.1 8 ツール一覧（Read-Only、本番稼働中）

| ツール名 | 返却内容 | データソース |
|---|---|---|
| `get_cash_flow_status` | キャッシュフロー状況 | Google Sheets |
| `get_catering_sales_status` | Catering 売上状況 | Google Sheets |
| `get_daily_action_status` | 日次アクション状況 | Google Sheets |
| `get_knowledge_status` | ナレッジ OS 状況 | Google Sheets |
| `get_lead_status` | リード状況 | Google Sheets |
| `get_owner_briefing` | オーナー向けブリーフィング | Google Sheets 複数 |
| `get_profit_leak_status` | 利益漏れ検知状況 | Google Sheets |
| `get_system_health` | システム健全性 | Cloud Run + Sheets |

### 10.2 MCP レスポンス標準フォーマット

```json
{
  "tool": "get_cash_flow_status",
  "checked_at": "2026-07-11T09:00:00+09:00",
  "data": { ... },
  "status": "ok|warning|critical",
  "summary": "現在のキャッシュフローは正常範囲内です"
}
```

---

## Contract 11: Registry & Governance（Phase A 実装済み）

Phase A で実装した registry / governance の**確定スキーマ**。実装は
`core/registry/models.py`（dataclass）で表現される。

### 11.1 Skill Registry エントリ（`configs/skills/registry.yaml`）

```yaml
- id: string                 # 一意（重複は FIX）
  name: string
  version: string
  skill_md_path: string      # 実在 SKILL.md の相対パス（未実装なら空文字）
  description: string
  triggers: [string]
  input_schema: {key: type}
  output_schema: {key: type}
  applicable_businesses: [string]   # "all" または business key
  permissions:               # 既定 false（default deny）
    read: bool
    write: bool
    external_send: bool      # skill は常に false
    deploy: bool             # skill は常に false（true は STOP）
    scheduler: bool          # skill は常に false（true は STOP）
    secret_access: bool      # skill は常に false（true は STOP）
  prohibited_actions: [string]
  fallback_behavior: DIRECT_SKILL_MD | LOGIC_DIRECT_APPLY | INACTIVE | STOP
  qa_criteria: [string]
  owner_approval_required: bool
  active: bool
```

**resolve() 返却ステータス**: `AVAILABLE` / `FALLBACK_DIRECT_MD` /
`FALLBACK_LOGIC` / `INACTIVE` / `NOT_FOUND` / `FORBIDDEN` / `INVALID_CONFIG`

### 11.2 Agent Registry エントリ（`configs/agents/registry.yaml`）

```yaml
- id: string
  name: string
  role: string
  description: string
  applicable_businesses: [string]
  read_permissions: [string]     # 最小権限
  write_permissions: [string]    # 既定 空（read-only）
  external_send_permission: bool # 既定 false（true は STOP）
  deploy_permission: bool        # 既定 false（true は STOP）
  scheduler_permission: bool     # 既定 false（true は STOP）
  secret_access: bool            # 既定 false（true は STOP）
  owner_approval_conditions: [string]  # 承認が要る action
  stop_conditions: [string]            # 即 STOP する action
  skills: [string]               # 全て Skill Registry に実在すること
  inputs: [string]
  outputs: [string]
  logs: [string]
  kpis: [string]
  active: bool
```

**resolve() 返却ステータス**: `ALLOWED` / `OWNER_APPROVAL_REQUIRED` /
`FORBIDDEN` / `INACTIVE` / `NOT_FOUND` / `INVALID_CONFIG`

### 11.3 Governance Decision Contract（`core/governance/validator.py`）

```
入力 GovernanceRequest:
  agent_id: string
  action: string
  skill_id: string | null
  target_business: string | null
  file_paths: [string]
  risk_level: LOW | MEDIUM | HIGH | CRITICAL | null
  owner_approved: bool
  branch_name: string | null

出力 GovernanceResult:
  decision: GO | OWNER_APPROVAL_REQUIRED | FIX | STOP
  reasons: [string]
  matched_policies: [string]
  risk_level: LOW | MEDIUM | HIGH | CRITICAL
```

**判定順（要約・default deny）**:
1. config 破損 → STOP
2. 空 action → STOP
3. 未知 Agent → STOP
4. blocked path（`scripts/acquisition/**`）→ STOP
5. hard-stop action（secret/credentials/env/main commit/auto-merge 等）→ STOP
6. main ブランチ書き込み → STOP
7. skill 不正 / skill 禁止 action → STOP
8. agent stop_condition 一致 → STOP
9. CRITICAL risk → STOP
10. 外部送信/deploy/scheduler/本番書込 → 承認なし=`OWNER_APPROVAL_REQUIRED` /
    承認あり+権限あり=`GO` / 承認あり+権限なし=`STOP`
11. safe action（audit_read 等）→ GO
12. agent owner_approval_conditions 一致 → `OWNER_APPROVAL_REQUIRED`
13. 高リスクパスの未分類 write → FIX
14. それ以外の未知 action → STOP（default deny）

### 11.4 CLI 終了コード（`scripts/registry/validate_registry.py`）

```
0 = GO    （issue なし）
1 = FIX   （FIX severity のみ）
2 = STOP  （STOP severity あり、または config ロード失敗）
```

---

## Contract 12: Business Config SSOT（Phase B1 実装済み・Shadow）

`configs/businesses/registry.yaml` の**確定スキーマ**。実装は
`core/business_config/models.py`。

### 12.1 Business エントリ

```yaml
- id: string                 # 一意（重複は STOP）
  slug: string               # 一意（重複は STOP）
  display_name: string
  brand_name: string
  business_type: string
  status: ACTIVE | INACTIVE | PLANNED | EXCLUDED | ARCHIVED
  active: bool
  timezone: string
  currency: string
  owner: string
  monthly_target: int
  services:                  # cloud_run_service / scheduler_jobs / line / threads / pos ...
  notification_policy:       # mode / owner_channel_env / staff_channel_env（env 名のみ）
  automation_policy:         # scheduler_status / dry_run_default（本番状態は UNKNOWN 既定）
  posting_policy:            # platforms / daily_post_limit=UNKNOWN / posting_window=UNKNOWN
  approval_policy:           # high_risk_requires_owner
  protected_fields: [string] # daily_post_limit / posting_window / scheduler_status
  environment_variable_names: [NAME]   # 変数名のみ（値は禁止）
  legacy_sources: [path::VAR]          # リポジトリ内パスのみ（traversal は STOP）
  migration_status: LEGACY_ONLY | SHADOW_DEFINED | VERIFIED
  metadata: {}
```

### 12.2 禁止フィールド / 禁止値（loader が STOP）

- フィールド名: `token` `api_key` `secret` `password` `private_key`
  `client_secret` `credentials` `access_token` `refresh_token` `bearer`
- 値: secret-like（`sk-…` `ghp_…` `AIza…` `xox…` `-----BEGIN`）
- `environment_variable_names`: 値ではなく **NAME** のみ（`[A-Z][A-Z0-9_]*`）
- `migration_status`: `PRODUCTION_CONNECTED` / `PARTIALLY_CONNECTED` /
  `READY_FOR_ADAPTER` は shadow mode で **禁止**（STOP）
- `legacy_sources`: リポジトリ外パス・`../` traversal は **STOP**

### 12.3 Loader / Comparator の戻り値

```
LoaderStatus : AVAILABLE | INACTIVE | NOT_FOUND | INVALID_CONFIG |
               LEGACY_ONLY | SHADOW_DEFINED | VERIFIED
Comparator   : GO  完全一致
               FIX 非危険な乖離（値/型/subset/missing）— 自動上書きしない
               STOP secret / cross-business 混入 / dup id・slug / production 誤表示
CLI exit     : 0=GO / 1=FIX / 2=STOP / 3=INTERNAL_ERROR（fail-closed）
```

### 12.4 Phase B1.1 追加スキーマ（canonical / alias / 昼夜内訳）

```yaml
  monthly_target: int             # 合計（= day + night のとき一致必須、不一致は FIX）
  monthly_target_day: int         # 昼の内訳（任意）
  monthly_target_night: int       # 夜の内訳（任意）
  slug_aliases: [string]          # legacy キー（例 hinabe → canonical ryukyu_hinabe）
  environment_variable_aliases:   # legacy env 名 → canonical env 名（NAME のみ）
    LEGACY_NAME: CANONICAL_NAME
```

**確定 canonical 値（2026-07-11 ゆうさん確定）**
- TACHINOMIYA 月商: **5,500,000**（昼 2,500,000 + 夜 3,000,000）
- 火鍋 canonical id: `ryukyu_hinabe` / legacy alias: `hinabe`
- TACHINOMIYA staff LINE canonical: `LINE_TACHINOMIYA_STAFF_TOKEN` /
  legacy alias: `LINE_TACHINOMIYASTAFF_TOKEN`（`TACHINOMIYA_LINE_STAFF_TOKEN` も alias）

**alias 方針**: canonical 優先・legacy は互換読込のみ・即削除しない。
`resolve_staff_env(biz, available_names)` は canonical→legacy の順で解決し、
どちらも無ければ `None`（安全停止）。**token 値は読まず・出さず**、返すのは NAME のみ。
staff 通知は常に owner approval 必須（`staff_send_requires_owner_approval` = True）。

**検証（loader/comparator）**: 昼夜合計不一致→FIX / alias 循環→STOP /
unknown alias target→FIX / slug alias が実 id/slug と衝突→STOP。

### 12.5 Config Builder / Supply 契約（Phase B2-4 Batch 1）

**BuildResult**（`core/business_config/config_builder.py`）
```
business_id: string
decision:    GO | FIX | STOP
source:      SSOT | FALLBACK_LEGACY
config:      dict | null   # legacy 互換 shape（GO 時）
issues:      [string]
reason:      string | null
```

**SSOT が overlay するキー（他は legacy 通し）**
```
monthly_target  business_type  status(ACTIVE→"active")  cloud_run_service
```
**overlay しないもの**: LINE env 名（実 env を壊さない）/ spreadsheet_id 値 /
menu_map / content_themes / line_channels 構造 / email / pos folder …

**Supply 結果**（`config_supply.py`）
```
runtime_source: LEGACY | SSOT | FALLBACK_LEGACY
decision:       GO | FIX | STOP | INTERNAL_ERROR
used_fallback / fallback_reason / config_shape_valid / comparison_decision / warnings
```

**CLI exit**（`check_ssot_config_supply.py`）: 0=GO / 1=FIX / 2=STOP / 3=INTERNAL_ERROR

**禁止**: Secret 値取得・env 値供給・入力 mutation・不明値の推測・silent fallback・
`SSOT_ONLY`・対象外事業への SSOT 供給。

### 12.6 Readiness Gate 契約（Phase B2-5）

**ReadinessResult**（`core/business_config/readiness.py`）
```
business_id / ssot_status / runtime_source / config_supply / legacy_fallback /
rollback_ready / owner_approval / missing_requirements / warnings / blockers /
readiness_decision / next_action
```
**readiness_decision**
```
READY                   技術条件 + owner 承認 + 運用確認が揃う（deploy は別承認）
ALMOST_READY            非危険な運用不足（画像不足 / token 未確認 / GBP 認証未確認 等）
OWNER_APPROVAL_REQUIRED 技術的に準備完了・owner 承認待ち
NOT_READY               SSOT供給不可 / 必須欠損 / 対象外事業
STOP                    Secret / cross-business 混入 / 危険な有効化 / production write
```
**運用確認項目**（code では検証不能・owner 確認まで ALMOST_READY）
```
tachinomiya: image_stock_sufficient / threads_token_verified / gbp_auth_verified
catering / beauty / ryukyu_hinabe: なし
```
**CLI exit**（`check_ssot_readiness.py`）: 0=READY/OWNER_APPROVAL のみ / 1=ALMOST_READY・NOT_READY 含む / 2=STOP 含む / 3=INTERNAL_ERROR

**この Gate は監査のみ**: deploy / Scheduler / Cloud Run / 投稿 / 送信 / 書込は一切しない。

### 12.7 Approval Ledger / Activation 契約（Phase B2-6）

**Approval Ledger**（`configs/governance/readiness_approvals.yaml`）
```yaml
- business_id / approval_type: READINESS / approved: bool /
  approved_by: OWNER / approval_scope: SSOT_PRODUCTION_READINESS /
  deploy_approval: false / scheduler_approval: false / external_send_approval: false /
  approved_at / source / expires_at / prohibited_actions[] / notes
```
※ Secret/token/個人情報なし。scheduler/external-send 承認は false 強制（loader が検査）。
`deploy_approval: true` は**スコープ必須**（`deploy_scope` ブロックが無ければ loader が issue）:
```yaml
deploy_scope: { service, env_var_name, from_mode, to_mode, smoke_test, rollback_mode }
```
記録は承認の監査証跡であり **deploy 実行ではない**（実 deploy は人間が gcloud で行う）。
現状 deploy 承認済み: `catering`（trees-catering-ai の runtime mode env のみ）。

**Readiness 追加判定**: `PHOTO_PENDING_READY`（token+GBP 確認済み・写真のみ残り）

**TACHINOMIYA 監査**（`tachinomiya_audit.py`・read-only・値は読まない）
```
threads_token: env NAME 宣言確認 → 期限/有効性は MANUAL_CHECK_REQUIRED
gbp:           auth ファイル存在確認 → 有効性は MANUAL_CHECK_REQUIRED
image:         PHOTO_PENDING（interior 1→5 / drink 3→8 / exterior 4→10）
```

**Activation Dry Run**（`activation.py`）
```
decision: DRY_RUN_GO | READINESS_BLOCKED | OWNER_APPROVAL_REQUIRED |
          DEPLOY_APPROVAL_REQUIRED | STOP | INTERNAL_ERROR
plan:     current/desired state・env NAME 変更・cloud_run_service・
          deploy/rollback command 候補（**実行しない**）・smoke_test・stop_conditions
```
**CLI exit**（`dry_run_ssot_activation.py`）: 0=DRY_RUN_GO / 1=READINESS_BLOCKED /
2=OWNER_APPROVAL_REQUIRED / 3=DEPLOY_APPROVAL_REQUIRED / 4=STOP / 5=INTERNAL_ERROR

### 12.8 Production Plan 契約（Phase B2-7）

**Production Plan**（`core/business_config/production_plan.py`・READY 3事業）
```
business_id / readiness / current_runtime_mode / proposed_runtime_mode /
cloud_run_service / project_id / region / env_var_names[] /
deploy_required / deploy_approved(false) / scheduler_required / scheduler_approved(false) /
external_send_required / external_send_approved(false) / smoke_tests[] / health_check /
rollback_steps[] / command_candidates{execute:false, deploy/env_update/smoke/rollback} /
blockers[] / warnings[] / decision / next_action
```
**decision**: PREPARED | DEPLOY_APPROVAL_REQUIRED | MANUAL_CHECK_REQUIRED | NOT_READY | STOP
（deploy_approved は本 phase で常に false。command は候補文字列・**実行フラグ常に false**・不明値は `UNKNOWN`）

**TACHINOMIYA Technical Readiness**（`tachinomiya_technical_readiness`）
```
threads_token / gbp / image / scheduler_expected(OFF) / posting_executed(false) /
line_sent(false) / manual_checks[] / decision / next_action
```
decision: PHOTO_PENDING_READY（token+GBP 確認済・写真のみ）| MANUAL_CHECK_REQUIRED（token/GBP 手動確認要）| READY

**CLI exit**（`check_activation_plan.py` / `check_tachinomiya_technical_readiness.py`）:
0=PREPARED/PHOTO_PENDING_READY / 1=MANUAL_CHECK_REQUIRED / 2=NOT_READY / 3=STOP / 4=INTERNAL_ERROR

**この phase は準備・技術確認のみ**: deploy / env 変更 / Scheduler / 投稿 / 送信は一切実行しない。

---

## Contract 12: Release & Operations OS（Phase R 設計 2026-07-15）

### 12.1 Change Classification schema（正本: `core/governance/diff_risk.py` 出力）

```json
{
  "commit_sha": "ca2c730...",
  "pr_number": 20,
  "risk_level": "LOW|MEDIUM|HIGH|CRITICAL",
  "categories": ["content_policy", "image_policy"],
  "businesses": ["catering", "tachinomiya", "beauty"],
  "services": ["trees-catering-ai", "tachinomiya-ai", "tree-beauty-ai"],
  "required_tests": ["tests/content", "tests/governance"],
  "full_suite_forced": false,
  "deploy_required": true,
  "approval_required": true,
  "auto_rollback": true,
  "prohibited": ["scheduler_change", "external_send"],
  "blocked_files": [],
  "secret_suspect": false
}
```
- categories 全集合: docs_only / content_policy / sns_post / image_policy /
  business_config / ssot / core_runtime / cloud_run_service / scheduler /
  secret_reference / external_send / acquisition / tree_beauty / financial /
  deployment_workflow
- `full_suite_forced=true` 条件: core_runtime / governance / secret_reference /
  external_send / cross-business / production routing / deployment_workflow
- businesses→services は `configs/businesses/registry.yaml` から導出（手動表なし）

### 12.2 Test Selection result schema（Actions job summary へ記録・監査用）

```json
{
  "commit_sha": "...", "testset_hash": "sha256(...)",
  "selected": ["tests/content", "tests/governance"],
  "reason": "categories=[content_policy]",
  "skipped_already_passed": false,
  "result": "PASS|FAIL", "ran": 388, "duration_sec": 5
}
```
skip 判定キー = `commit_sha + testset_hash`。PASS 記録なしなら必ず実行。

### 12.3 Approval schema（正本: GitHub Environment `production` / Ledger へ転記）

```json
{
  "approval_id": "gha-run-<run_id>-attempt-<n>",
  "approval_type": "DEPLOY",
  "pr_number": 20, "commit_sha": "...",
  "services": ["trees-catering-ai", "tachinomiya-ai", "tree-beauty-ai"],
  "approved_by": "OWNER", "approved_at": "ISO8601",
  "expires": "run timeout (30min) で自動失効",
  "scope_note": "この run のこの SHA 限り。Scheduler / external send / readiness は別承認"
}
```
- readiness 承認は従来どおり `configs/governance/readiness_approvals.yaml`（別正本・混同禁止）
- YES の再利用・別 PR 流用は構造上不可（run 単位で消費）

### 12.4 Deployment Ledger schema（正本: `gs://yu-release-ledger/<deployment_id>.json`）

```json
{
  "deployment_id": "rel-20260715-<run_id>",
  "pr_number": 20, "commit_sha": "...",
  "risk_level": "HIGH", "selected_tests": [...], "test_result": "PASS",
  "approval": { "...": "12.3 を埋め込み" },
  "services": [
    {
      "business": "catering", "service": "trees-catering-ai",
      "project": "tree-beauty-ai-499303", "region": "asia-northeast1",
      "staging_revision": "trees-catering-ai-00061-xxx",
      "old_revision": "trees-catering-ai-00060-yyy",
      "new_revision": "trees-catering-ai-00061-xxx",
      "traffic": "100%", "health": 200, "status": 200,
      "result": "ACTIVATED|ROLLED_BACK|FAILED|SKIPPED_ALREADY_ACTIVE|NOT_STARTED",
      "rollback": { "executed": false, "target": null, "verified": null },
      "duration_sec": 95, "error_reason": null
    }
  ],
  "final_verdict": "ACTIVATED_ALL_TARGETS|PARTIALLY_ACTIVATED|ROLLED_BACK|FAILED|STOPPED",
  "heartbeat": [{"step": "smoke:catering", "at": "ISO8601"}],
  "audit_timestamp": "ISO8601"
}
```
書込みは追記のみ（bucket versioning + retention）。resume 時は同 deployment_id を読み、
`result=ACTIVATED` のサービスを skip。

### 12.5 Service / Endpoint registry schema（正本: `configs/businesses/registry.yaml` に追記）

```yaml
# 各 business 配下に追加（例）
services:
  cloud_run_service: trees-catering-ai
  release:
    deploy_target: true          # allowlist（false/欠落 = deploy 禁止）
    deploy_order: 1              # catering=1, tachinomiya=2, beauty=3
    endpoints:                   # smoke が使う実在 endpoint（推測禁止の根拠）
      health: /health
      status: /status
```
pasta_pasta / z1 / ryukyu_hinabe は `deploy_target: false`（琉球火鍋は明示承認 release のみ
一時的に true にする PR を別途出す）。

### 12.6 Smoke result schema

```json
{
  "service": "trees-catering-ai", "phase": "staging|production",
  "revision": "...", "ready": true,
  "health_code": 200, "status_code": 200,
  "business_identity": "TREE'S CATERING", "identity_match": true,
  "release_info": { "commit": "...", "image_generation": false,
                    "delivery_mode": "TEXT_ONLY", "config_source": "LEGACY|SSOT" },
  "log_findings": [], "secret_exposure": false,
  "verdict": "GO|ROLLBACK"
}
```
`release_info` は Phase R3 で `/status` に追加する read-only フィールドから取得。
unknown / 取得不能は **verdict=ROLLBACK**（fail-closed）。

### 12.7 Rollback schema

```json
{
  "service": "...", "trigger": "health_not_200|status_abnormal|identity_mismatch|...",
  "from_revision": "...", "to_revision": "...",
  "traffic_restored": true, "post_health": 200, "post_status": 200,
  "env_mode_restored": null,
  "result": "ROLLED_BACK|ROLLBACK_FAILED_CRITICAL",
  "followup": "後続 deploy 停止 / CRITICAL 時 production lock + LINE + GitHub Issue"
}
```

### 12.8 Notification routing（正本: release.yml 内の1テーブル）

approval_required / started / activated / rollback / failed / timeout /
credentials_expired / manual_required / final_summary → OWNER_ONLY LINE。
Secret・token・env 値は載せない。通知失敗は deploy を失敗させない
（`if: always()` + `continue-on-error`）。不達時 GitHub Issue へフォールバック。

### 12.9 PR Validation contract（Phase R1 実装済み・2026-07-15）

`.github/workflows/pr-validation.yml` の入出力契約:

```
trigger      : pull_request(base=main) | workflow_dispatch
runner       : ubuntu-24.04
python       : 3.11 (production Dockerfile 準拠)
install      : pip install --no-deps -r requirements.lock   # committed lock のみ
judge        : exit code のみ（テスト件数の文字列パースは禁止）
gate_exit    : GO=0 | FIX=10 | OWNER_APPROVAL_REQUIRED=20 | STOP=30 | INTERNAL_ERROR=40
check_result : pass = {0, 20} / fail = {10, 30, 40, その他}
               ※ 20 は HIGH PR の正常状態（人間承認は merge 時・コード欠陥ではない）
permissions  : contents:read + pull-requests:read（id-token/deployments なし）
production   : gcloud/deploy/Scheduler/Secret/GCS/LINE 不使用
```

`requirements.lock` schema: `pip freeze --exclude-editable | sort` の完全固定（`名前==版`）。
正本は `requirements.txt`。更新は別 PR で lock を再生成（CI 内自動生成は禁止）。

## Contract 13: Change Classification（Phase R2 実装済み・2026-07-15）

`diff_risk.classify_change(paths, added_text="", registry=None) -> dict`。出力キー:
`risk_level / categories / affected_businesses / affected_services / selected_test_groups /
full_test_required / staging_required / production_approval_required / rollback_required /
blocked / reasons`。`selected_test_groups` は実在 dir（agent/business_config/content/
governance/registry）または sentinel `FULL` のみ。CLI は加えて `run_scope`(FULL|NONE|GROUPS)
を GITHUB_OUTPUT へ emit（fail-closed: unknown/blocked/空 diff → FULL）。Secret 値は出さない
（scan は boolean のみ）。

## Contract 14: Release Infra Bootstrap（Phase R2.5 実装済み・2026-07-16）

`scripts/release/bootstrap_release_infra.sh <mode>`。mode ∈ {--plan(既定・無変更),
--verify(read-only), --rollback-plan(表示のみ), --apply(CONFIRM=yes 必須・人間)}。SSOT 値:
project=tree-beauty-ai-499303 / region=asia-northeast1 / pool=github-release-pool /
provider=github-oidc(condition `assertion.repository=='YuuTKD/yu-business-os'`) /
SA={release-deployer, release-verifier, release-ledger}@project /
AR=yu-release(docker) / bucket=gs://yu-release-ledger(UBLA+PAP+versioning+retention,
ledger SA=objectCreator のみ=append-only)。長期 SA key・roles/owner・editor・admin を作らない
（fail-closed テストで保証）。Secret 値は出力しない。

## Phase R3 実装結果 + R2.5 Retention 例外（2026-07-16）

R2.5 retention は OWNER_ACCEPTED_EXCEPTION（34495200s≈399d18h・2026-07-16 承認・policy 変更なし・verify=READY_WITH_EXCEPTION）。
R3: `release.yml`(workflow_dispatch のみ・WIF・SHA build→AR→`--no-traffic --tag candidate`→read-only smoke・**update-traffic なし**) + `smoke_test.py` + `configs/release/services.yaml`(endpoint SSOT) + `/status` read-only 拡張。対象=trees-catering-ai のみ(allowlist)。457 tests PASS。candidate deploy は未実行(次の owner YES)。本番 traffic/Scheduler/Secret 不変。
