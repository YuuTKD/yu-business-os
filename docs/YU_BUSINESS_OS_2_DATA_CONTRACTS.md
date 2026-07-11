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
