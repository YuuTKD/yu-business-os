# YU Business OS 2.0 — Migration Map

作成日: 2026-07-11  
ステータス: 設計書（実装禁止・承認待ち）

**目的**: 既存 1.x 全資産を 2.0 レイヤーへマッピングし、移行リスクを評価する。  
**原則**: 「触らない」が最優先。移行とは上位レイヤーを追加することであり、既存コードの削除・移動・変更ではない。

---

## 凡例

| マーク | 意味 |
|---|---|
| ✅ KEEP | 現状維持・2.0 でもそのまま使用 |
| ⬆ WRAP | 上位レイヤーで包む（既存は変更しない）|
| 🔧 FIX_NEEDED | 技術的負債あり・将来 PR で対応 |
| 🔴 RISK | リスクあり・要注意 |
| 🗄 ARCHIVE | 休止中・アーカイブ済み |
| 🚫 BLOCKED | 変更禁止・Claude Code が触らない |

---

## セクション 1: インフラ資産

### Cloud Run サービス（7 本）

| サービス | 現状 | 2.0 アクション | リスク |
|---|---|---|---|
| `tree-beauty-ai` | ✅ KEEP | Scheduler 設定変更禁止 | LOW |
| `trees-catering-ai` | ✅ KEEP | Scheduler 設定変更禁止 | LOW |
| `tachinomiya-ai` | 🔧 FIX_NEEDED | Scheduler=OFF 維持、LINE env 変数をゆうさんが空化 | HIGH |
| `ryukyu-hinabe-ai` | ✅ KEEP | 変更禁止 | LOW |
| `pasta-pasta-ai` | ✅ KEEP | 変更禁止 | LOW |
| `z1-ai` | ✅ KEEP | 変更禁止 | LOW |
| `yu-holdings-ai` | ✅ KEEP | System Health 自動実行を維持 | LOW |

### GCS バケット

| バケット / パス | 現状 | 2.0 アクション | リスク |
|---|---|---|---|
| `tree-beauty-blog-images/image-library/tachinomiya/` | ✅ KEEP | 96 枚 _fixed.jpeg 確認済み | LOW |
| `tree-beauty-blog-images/content/` | ✅ KEEP | 変更禁止 | LOW |

---

## セクション 2: コアモジュール（`core/`）

| ファイル | 2.0 区分 | 移行アクション | 優先度 |
|---|---|---|---|
| `entrypoint.py` | ✅ KEEP | 変更なし | — |
| `multi_business_content_engine.py` | 🔧 FIX_NEEDED | DRY_RUN 未実装を将来 PR で追加 | HIGH |
| `owner_daily.py` | ✅ KEEP | DRY_RUN 実装済み・維持 | — |
| `system_health.py` | ✅ KEEP | 変更なし | — |
| `executive_team.py` | ⬆ WRAP | OpenAI 依存は維持（禁止は新規のみ）| MEDIUM |
| `gbp_api.py` | ✅ KEEP | コード準備済み・デプロイ承認待ち | — |
| `threads_api.py` | ✅ KEEP | トークン期限確認をゆうさんタスクに | — |
| `threads_reply_publisher.py` | ✅ KEEP | THREADS_ACCESS_TOKEN 管理維持 | — |
| `sns_pdca.py` | ✅ KEEP | Phase3（Gemini）は API キー取得後 | — |
| `growth_engines.py` | ✅ KEEP | 変更なし | — |
| `cash_flow.py` | ✅ KEEP | 変更なし | — |
| `profit_leak.py` | ✅ KEEP | 変更なし | — |
| `review_referral.py` | ✅ KEEP | 変更なし | — |
| `image_manager.py` | ✅ KEEP | TACHINOMIYA 新規画像追加時に使用 | — |
| `pos_processor.py` | ✅ KEEP | 変更なし | — |
| `credentials_loader.py` | ✅ KEEP | 変更なし | — |
| `knowledge_os.py` | ✅ KEEP | 変更なし | — |
| `mcp_server.py` | ✅ KEEP | Read-Only 8 ツール稼働中 | — |

---

## セクション 3: 設定ファイル（`configs/`）

| ファイル | 2.0 区分 | 移行アクション | 優先度 |
|---|---|---|---|
| `business_registry.py` | ⬆ WRAP | **単一設定源として正式化**。`core/multi_business_content_engine.py` の `_BUSINESS_CONFIGS` をこちらから参照するよう高リスク PR で変更 | HIGH |
| `auto_post_settings.py` | ✅ KEEP | 変更なし | — |
| `post_theme_rules.py` | ✅ KEEP | 変更なし | — |
| `env_templates/` | ✅ KEEP | 変更なし | — |

### 設定二重管理 解消ロードマップ

**問題**: 事業設定が 2 か所に存在している

```
configs/business_registry.py    ← 正式・6 事業
core/multi_business_content_engine.py  ← _BUSINESS_CONFIGS（4 事業のみ）
```

**2.0 解消案**（高リスク PR として実装）:

```python
# core/multi_business_content_engine.py の先頭に追加
from configs.business_registry import BUSINESSES as _REG

def _build_business_configs():
    """1.x の _BUSINESS_CONFIGS を business_registry.py から自動生成"""
    result = {}
    for key, biz in _REG.items():
        if key in ("beauty", "catering", "tachinomiya", "hinabe"):
            result[key] = {
                "name":           biz["name"],
                "spreadsheet_id": biz.get("spreadsheet_id", ""),
                "line_token_env": biz["line_channels"]["staff"]["env_key"],
                # ... 以下同様
            }
    return result

_BUSINESS_CONFIGS = _build_business_configs()
```

**前提条件**: ゆうさん承認 + 高リスク PR → 人間マージ

---

## セクション 4: エージェント（`agents/`）

| 資産 | 2.0 区分 | 移行アクション |
|---|---|---|
| `product_match_acquisition/` | 🗄 ARCHIVE | 再開禁止。データは `data/archive/` に保存済み |
| `shared/line_notify.js` | ✅ KEEP | Layer 7 NotificationGateway の参考実装として使用 |
| `shared/cost_guard.js` | ✅ KEEP | Layer 4 Agent Registry のコスト制限に統合 |
| `shared/dedupe.js` | ✅ KEEP | 変更なし |
| `shared/human_gate.js` | ✅ KEEP | Layer 8 Quality Gates の参考実装 |
| `shared/secret_guard.js` | ✅ KEEP | Layer 1 Governance Shell に統合 |
| `shared/risk_hint.js` | ✅ KEEP | Layer 8 Risk Assessment に統合 |

---

## セクション 5: スキル（`skills/`）

全 7 スキルは 2.0 で ACTIVE 維持。変更なし。

| スキル | 1.x 状態 | 2.0 状態 | Layer |
|---|---|---|---|
| `debt-collection` | ACTIVE | ✅ KEEP | Layer 5 |
| `image-library-manager` | ACTIVE | ✅ KEEP | Layer 5 |
| `pr-review-gate` | ACTIVE | ✅ KEEP | Layer 1 + Layer 5 |
| `pre-deploy-qa` | ACTIVE | ✅ KEEP | Layer 8 + Layer 5 |
| `scheduler-readiness-check` | ACTIVE | ✅ KEEP | Layer 11 + Layer 5 |
| `sns-post-quality-check` | ACTIVE | ✅ KEEP | Layer 8 + Layer 5 |
| `sop-writer` | ACTIVE | ✅ KEEP | Layer 5 |

---

## セクション 6: データ資産

### `data/master/`（マスターデータ）

| ファイル | 2.0 区分 | 移行アクション |
|---|---|---|
| `business_profiles.csv` | ✅ KEEP | `configs/business_registry.py` の補完データとして維持 |
| `acquisition_playbooks.csv` | 🗄 ARCHIVE | acquisition PAUSED のため参照のみ |
| `target_profiles.csv` | 🗄 ARCHIVE | 同上 |
| `offer_profiles.csv` | 🗄 ARCHIVE | 同上 |
| `query_templates.csv` | 🗄 ARCHIVE | 同上 |
| `exclusion_rules.csv` | 🗄 ARCHIVE | 同上 |
| `manual_candidates.csv` | 🗄 ARCHIVE | 同上 |

### `data/acquisition/`（取得ログ）

| ファイル | 2.0 区分 | 移行アクション |
|---|---|---|
| `acquisition_*.csv` | 🗄 ARCHIVE | acquisition PAUSED のため読み取り専用 |
| `dedupe_index.csv` | 🗄 ARCHIVE | 同上 |

### `data/reports/`（運用レポート）現状整理

**問題**: 70+ ファイルが混在、同一目的の重複多数

2.0 では下記の統廃合を提案（実装は承認後・高リスク外）:

| カテゴリ | 対象ファイル数 | 統廃合方針 |
|---|---|---|
| TACHINOMIYA 画像関連 | ~8 ファイル | `tachinomiya_image_master.txt` 1 本に集約（提案）|
| TACHINOMIYA LINE 関連 | ~6 ファイル | `tachinomiya_notification_policy.txt` 1 本に（提案）|
| TACHINOMIYA READY 関連 | ~6 ファイル | `tachinomiya_scheduler_readiness_report.txt` が正本 |
| AI net business ログ | ~12 ファイル | `data/archive/acquisition_paused_*/` に移動済み |
| Catering 営業資料 | ~5 ファイル | そのまま維持 |

**注意**: ファイル移動・削除は ゆうさん承認後のみ。提案のみで現時点では変更しない。

---

## セクション 7: ガバナンス資産

| ファイル | 1.x 状態 | 2.0 アクション |
|---|---|---|
| `CLAUDE.md` | ✅ 運用中 | 変更なし |
| `AGENTS.md` | ✅ 運用中（PR #6）| 変更なし |
| `TEAM_RULES.md` | ✅ 運用中 | 変更なし |
| `TASK.md` | TASK-001 DONE | 次タスク記入欄として維持 |
| `REPORT.md` | ✅ 運用中 | 変更なし |
| `.github/pull_request_template.md` | ✅ 運用中 | 変更なし |
| `scripts/agent/pr_auto_flow.sh` | ✅ 運用中 | 変更なし |
| `scripts/agent/safe_auto_merge_pr.sh` | ✅ 運用中 | 変更なし |
| `scripts/review/codex_pr_review.sh` | ✅ 運用中 | 変更なし |

---

## セクション 8: LINE トークン移行マップ

### 現状（問題あり）

```
事業        | 環境変数名                   | 送信先            | リスク
----------- | ---------------------------- | ----------------- | ------
beauty      | LINE_STAFF_TOKEN             | スタッフ broadcast | MEDIUM
catering    | LINE_cateringSTAFF_TOKEN     | スタッフ broadcast | MEDIUM
tachinomiya | LINE_TACHINOMIYASTAFF_TOKEN  | スタッフ broadcast | HIGH (Q1=YES で空化中)
hinabe      | LINE_hinabeSTAFF_TOKEN       | スタッフ broadcast | MEDIUM
全事業共通   | LINE_OWNER_TOKEN             | オーナー専用       | LOW (安全)
```

### 2.0 移行方針（段階的）

```
Phase 0 (今すぐ・ゆうさんが手動実施):
  TACHINOMIYA: LINE_TACHINOMIYASTAFF_TOKEN → Cloud Run で空に設定
  効果: broadcast 送信ゼロ（安全弁作動）

Phase 1 (TACHINOMIYA 画像補充完了後・高リスク PR):
  core/multi_business_content_engine.py の tachinomiya 設定
  Before: "line_token_env": "LINE_TACHINOMIYASTAFF_TOKEN"
  After:  "line_token_env": "LINE_OWNER_TOKEN"

Phase 2 (長期・全事業統一・最終形):
  全事業のコンテンツ完了通知を LINE_OWNER_TOKEN へ統一
  各事業スタッフ通知は DRY_RUN / OWNER_ONLY / STAFF の EXECUTION_MODE で制御
```

---

## セクション 9: Google Sheets 移行マップ

| スプレッドシート | 事業 | 現状 | 2.0 アクション |
|---|---|---|---|
| `1I6wRRD...` | Tree Beauty | ✅ KEEP | 変更なし |
| `1tNE35i...` | Catering | ✅ KEEP | 変更なし |
| `1K4KkAh...` | TACHINOMIYA | ✅ KEEP | 変更なし（Scheduler OFF 維持）|
| `1jwFmQt...` | 琉球火鍋 | ✅ KEEP | 変更なし |
| `1MVz203...` | パスタパスタ | ✅ KEEP | 変更なし |
| `10YHdIx...` | Z1 | ✅ KEEP | 変更なし |
| `15cfsC2...` | IMAGE_LIBRARY | ✅ KEEP | TACHINOMIYA 新規画像追加時に更新 |

---

## セクション 10: 移行リスクマトリクス

### 高リスク（要人間承認）

| 変更内容 | リスク理由 | 承認条件 |
|---|---|---|
| `_BUSINESS_CONFIGS` → `business_registry.py` 統合 | core/ 変更・Cloud Run 再デプロイ | ゆうさん判断 |
| TACHINOMIYA `line_token_env` 切り替え | LINE 通知先変更・本番影響 | 画像補充完了後・ゆうさん判断 |
| DRY_RUN モード追加 | core/ 変更 | ゆうさん判断 |
| Notification Gateway 実装 | 新モジュール + core/ 変更 | 設計レビュー後・ゆうさん判断 |
| `data/reports/` 整理・移動 | 既存ファイル削除リスク | ゆうさん明示承認 |

### 低リスク（Claude Code が実施可能）

| 変更内容 | 理由 |
|---|---|
| `docs/` 以下に設計書を追加 | ドキュメントのみ |
| `TASK.md` にタスクを追記 | ドキュメントのみ |
| `REPORT.md` を更新 | ドキュメントのみ |
| `data/reports/` 内の既存ファイルを更新（追記） | 既存ファイルの更新 |

### 絶対禁止（何があっても実施しない）

| 禁止事項 |
|---|
| 既存 Cloud Run サービスの削除・新規デプロイ |
| 既存 Scheduler の ON/OFF 変更 |
| `data/reports/` ファイルの削除・移動（ゆうさん承認なし）|
| LINE/SNS/Gmail への本番送信 |
| `Tree Beauty` の商品マッチ対象化 |
| `acquisition` エージェントの再開 |
| `daily_post_limit` / `posting_window` の変更 |

---

## Phase A 移行結果（2026-07-11）— 追加のみ・既存無変更

Phase A は Registry / Governance レイヤーを**新規追加**した。1.x の資産に対する
KEEP/WRAP/ARCHIVE 区分は**すべて維持**され、既存ファイルの変更・削除・移動は
ゼロである。

### 移行アクションの実績

| 資産 | 計画区分 | Phase A での実績 |
|---|---|---|
| 既存 `core/**` | ✅ KEEP | 無変更（新規サブパッケージ `core/registry`, `core/governance` を**追加**）|
| 既存 `configs/**` | ⬆ WRAP | 無変更（`configs/skills`, `configs/agents`, `configs/governance` を**追加**）|
| 既存 `skills/**` | ✅ KEEP | 無変更（Skill Registry から**参照のみ**・SKILL.md は実行しない）|
| 既存 `scripts/**` | ✅ KEEP | 無変更（`scripts/registry/` を**追加**）|
| `scripts/acquisition/**` | 🗄 ARCHIVE | 無変更・Governance が触れると STOP |
| `agents/product_match_acquisition` | 🗄 ARCHIVE | 無変更・Agent Registry には登録しない |

### rollback 特性

Phase A は**追加差分のみ**のため、rollback は「PR を Merge しない / ブランチ破棄」
で完結する。既存本番へ未接続なので本番影響はゼロ。既存ファイルの削除・移動が
ないため復元操作は不要。

### 命名の移行判断

設計書のツリーは `config/` を示していたが、既存 `configs/` を採用した
（本書セクション 3 の「既存命名規約を優先」原則に一致）。`config/` と `configs/`
の二重ディレクトリという footgun を回避するための意図的な判断。

---

## Phase B1 移行結果（2026-07-11）— Legacy → Shadow Registry 対応表

事業設定の SSOT を **shadow mode** で追加。既存の Legacy 設定は**すべて維持**
（削除・上書き・本番読込先切替なし）。

### Legacy → Shadow 対応表

| Legacy ソース | 記号 | Shadow Registry での扱い |
|---|---|---|
| `configs/business_registry.py :: BUSINESSES`（6事業）| ✅ KEEP | 権威 Legacy。Comparator の基準 |
| `core/multi_business_content_engine.py :: _BUSINESS_CONFIGS`（5キー）| ✅ KEEP | subset 比較。`hinabe` 別名重複を検出 |
| `core/system_health.py :: MONTHLY_TARGETS`（6）| ✅ KEEP | 参照のみ（本 PR では未接続）|
| `ceo/executive_team.py :: BUSINESS_TARGETS`（6）| ✅ KEEP | target 比較 → TACHINOMIYA 乖離を検出 |
| `core/entrypoint.py :: _CONTENT_LINE_TOKEN_MAP` | ✅ KEEP | env 名のみ・未接続 |

### 検出された乖離（自動上書きせず FIX として報告）

| 事業 | フィールド | 乖離内容 |
|---|---|---|
| tachinomiya | monthly_target | `executive_team` 1,200,000 ≠ 正本 3,500,000 |
| catering / tachinomiya / ryukyu_hinabe | line token 名 | `_BUSINESS_CONFIGS` の env 名が `business_registry.py` と不一致 |
| hinabe | key | `_BUSINESS_CONFIGS` に `ryukyu_hinabe` と重複する別名 `hinabe` |

### 本番未接続の保証

- Shadow Registry は**本番読込元ではない**（既存コードは従来どおり）
- 値の自動同期・自動上書きなし
- rollback は追加差分の revert のみで完結（既存ファイル無変更）

---

## Phase B1.1 移行結果（2026-07-11）— 乖離解消・互換期間

B1 で検出した5件を確定値で解消。CLI は **GO（mismatch 0）** に。

### 解消内容と互換方針

| 乖離 | 解消 | 互換期間の扱い |
|---|---|---|
| TACHINOMIYA target 1.2M/3.5M | legacy を **5.5M** に統一（`business_registry.py` / `system_health.py` / `executive_team.py`）+ SSOT に昼2.5M/夜3.0M内訳 | 値は即統一（内訳は SSOT が保持）|
| 火鍋 `hinabe` 重複キー | SSOT `ryukyu_hinabe` に `slug_aliases: [hinabe]` | `hinabe` は alias として受理・**削除しない** |
| LINE 名不一致（tachinomiya/catering/hinabe）| SSOT に `environment_variable_aliases`（legacy→canonical）| legacy 名は互換読込のみ・**削除しない** |

### 互換期間（Phase B2 まで）

- legacy alias は削除せず**併存**。canonical 優先で解決し、legacy は fallback。
- 本番 env 変数名は**変更しない**（Cloud Run 側の実 env を壊さない）。名称統一の
  実切替は Phase B2 で 1 事業ずつ・owner 承認・人間 Merge。

---

## Phase B2-1 移行結果（2026-07-11）— TACHINOMIYA Shadow 接続

TACHINOMIYA を対象に、Legacy と SSOT を**実行時比較**する Shadow Adapter を追加。
本番の設定読込先は**切替えない**（`runtime_source` は常に `LEGACY`）。

| 項目 | 内容 |
|---|---|
| Adapter | `core/business_config/shadow_adapter.py`（TACHINOMIYA 限定）|
| Legacy 読取 | `configs/business_registry.py::BUSINESSES`（AST 静的・import なし）|
| SSOT 読取 | `configs/businesses/registry.yaml` |
| **runtime_source** | **常に LEGACY**（SSOT 値は本番へ渡さない・渡せば STOP）|
| モード | OFF / SHADOW_ONLY(既定) / ENFORCE_COMPARE（引数・CLI・テスト限定）|
| 本番接続 | **なし**（production main path 未変更・default OFF の hook のみ）|

比較対象は env 変数**名**のみ（token 値は読まない）。mismatch は fail-closed
（危険=STOP / 非危険=SHADOW は FIX・ENFORCE は STOP）。実切替は Phase B2-2。

---

## Phase B2-2 移行結果（2026-07-11）— TACHINOMIYA SSOT primary + Legacy fallback

TACHINOMIYA のみ、設定読込の第一候補を **SSOT** に切替可能にした（Legacy fallback 付き）。
Cloud Run deploy・Scheduler 変更・外部送信は**なし**。

| 項目 | 内容 |
|---|---|
| Resolver | `core/business_config/runtime_resolver.py`（TACHINOMIYA 限定）|
| CLI | `scripts/business_config/check_tachinomiya_runtime.py`（exit 0/10/20/30/40/50）|
| runtime mode | LEGACY_ONLY / SHADOW_ONLY / **SSOT_PRIMARY_WITH_LEGACY_FALLBACK** / SSOT_ONLY(禁止=STOP)|
| SSOT 使用条件 | 承認済み + mismatch 0 + SSOT 有効 + migration ∈ {SHADOW_DEFINED, VERIFIED} |
| fallback 条件 | SSOT 読込失敗 / schema 不完全（**mismatch は fallback しない → FIX/STOP**）|
| 他事業 | 常に LEGACY（SSOT primary 要求は STOP）|
| 本番 main path | **未変更**（default OFF hook のみ・強制接続なし）|

### rollback switch

`--mode LEGACY_ONLY`（引数1つ）で即 Legacy に戻る。Cloud Run 未設定のため
コード/引数レベルの切替のみ・外部通信不要・Legacy/alias は削除しない。

---

## Phase B2-3 移行結果（2026-07-11）— 本番 main path へ Resolver を安全接続

`core/entrypoint.py` の設定読込直後に、SSOT Runtime Resolver を **feature flag
（既定 LEGACY_ONLY）越しに接続**した。既定では従来と完全に同一挙動。

| 項目 | 内容 |
|---|---|
| Runtime Loader | `core/business_config/runtime_loader.py`（flag 判定・fail-closed）|
| Business Loader | `core/business_config/business_loader.py`（legacy 取得＋接続）|
| Entrypoint | `apply_runtime_config` を追加呼出（既存 CONFIG は**そのまま返す**）|
| CLI | `scripts/business_config/check_runtime_main_path.py`（exit 0/10/20/30/40/50）|
| Feature flag | `YU_CONFIG_RUNTIME_MODE`: **LEGACY_ONLY(既定)** / AUTO / OWNER_APPROVED |
| SSOT 使用 | owner 承認時のみ（AUTO+`YU_OWNER_APPROVED=true` または OWNER_APPROVED）|
| 対象 | TACHINOMIYA のみ・他事業は常に LEGACY |

**重要**: `apply_runtime_config` は CONFIG オブジェクトを**変更せず同一物を返す**
（source を判定・記録するのみ）。既定 LEGACY_ONLY では Resolver を呼ばない。
deploy / Cloud Run env / Scheduler / 投稿 / LINE いずれも**なし**。

### rollback

`YU_CONFIG_RUNTIME_MODE=LEGACY_ONLY`（既定）へ戻すだけ。1 設定・code revert 不要・
外部通信不要・Legacy/alias 削除なし。

---

## Phase B2-4 Batch 1 移行結果（2026-07-11）— SSOT 由来 config 供給（3事業）

Batch 1 = **TACHINOMIYA / TREE'S CATERING / TREE BEAUTY**。owner 承認時のみ、
SSOT 由来の Legacy 互換 config を Runtime へ供給。既定は LEGACY_ONLY（供給なし）。

### runtime_source と挙動

| flag / 状況 | runtime_source | 挙動 |
|---|---|---|
| LEGACY_ONLY（既定）| LEGACY | legacy をそのまま（Builder 不呼出）|
| AUTO 承認なし | LEGACY | owner 承認待ち |
| AUTO+承認 / OWNER_APPROVED（mismatch 0）| **SSOT** | Builder が Legacy 互換 config を供給 |
| SSOT 読込失敗 / shape 不正 | FALLBACK_LEGACY | Legacy へ fallback（理由付き）|
| 非危険な mismatch | FALLBACK_LEGACY（decision FIX）| **隠さず FIX 報告**・legacy 供給 |
| 事業ID混入 / 危険 mismatch | — | STOP |
| 対象外3事業 | LEGACY | 挙動不変 |

### fallback は「隠さない」

- mismatch は fallback で握りつぶさず **FIX として報告**（silent fallback なし）
- fallback には必ず `fallback_reason` を付す
- Legacy/alias は削除しない・env の実体名は変更しない

### rollback

`YU_CONFIG_RUNTIME_MODE=LEGACY_ONLY`（既定）に戻すだけ。SSOT→LEGACY を即切替。
code revert 不要・env 削除でも Legacy 復帰。

### Batch 2 候補

`ryukyu_hinabe`（火鍋）→ その後 `pasta_pasta` / `z1`（別 PR・別承認）。

---

## Phase B2-4 Batch 2 移行結果（2026-07-12）— 火鍋のみ SSOT 供給

Batch 2 = **`ryukyu_hinabe`（琉球火鍋）のみ**。`pasta_pasta` / `z1` は**対象外・不変**。

| 項目 | 内容 |
|---|---|
| 追加供給対象 | `ryukyu_hinabe`（canonical id）|
| legacy alias | `hinabe`（alias としてのみ維持・削除しない）|
| alias 解決 | `supply('hinabe')` は canonical `ryukyu_hinabe` に解決され同一 config |
| 供給挙動 | 既定 LEGACY_ONLY / owner 承認時のみ SSOT / 失敗時 Legacy fallback（理由付き）|
| 保持 | POS(usen・tabelog)・売上連携・別オーナー email・approval policy は legacy 通し |
| 有効化しない | GBP 自動化 / 投稿 / LINE / Gmail / Scheduler / Cloud Run |
| 対象外 | `pasta_pasta` / `z1` は常に LEGACY（コード・設定・テスト・docs 変更なし）|

rollback: `YU_CONFIG_RUNTIME_MODE=LEGACY_ONLY`（既定）に戻すだけ。次候補: `pasta_pasta` / `z1`。

---

## Phase R: Release & Operations OS 移行マップ（設計 2026-07-15）

### 再利用する既存資産（変更せず接続）

| 既存資産 | Release OS での役割 |
|---|---|
| `core/governance/diff_risk.py` | Change Classification の**唯一の正本**（関数追加のみ） |
| `scripts/agent/governance_gate.py` | pr-validation.yml が呼ぶ PR ゲート（そのまま） |
| `scripts/agent/pr_auto_flow.sh` / `safe_auto_merge_pr.sh` | PR レビュー経路（そのまま。release 経路とは分離） |
| `configs/businesses/registry.yaml` | business / service / endpoint / deploy_order の SSOT（release ブロック追記） |
| `configs/governance/policies.yaml` | deployment policy の正本（release ポリシー追記） |
| `configs/governance/readiness_approvals.yaml` | readiness 承認の正本（deploy 承認とは分離のまま） |
| `configs/content_policy.yaml` + `core/content_policy.py` | smoke の image/LINE フラグ検証対象 |
| `Dockerfile`（python:3.11-slim） | CI Python バージョンの基準・Cloud Build のビルド定義 |
| `requirements.txt` | 依存の正本（lock を**生成**する。手書き二重管理しない） |
| `tests/`（agent/business_config/content/governance/registry） | Test Selection の単位 |
| `core/entrypoint.py` の `/health` `/status` | smoke endpoint（R3 で status に release 情報を追加） |
| OWNER_ONLY LINE 基盤 | 承認通知・完了報告チャネル |
| TACHINOMIYA readiness gate / activation dry run | deploy 前 readiness 判定にそのまま接続 |

### 新規追加（追加のみ・既存無変更）

| 追加物 | 内容 |
|---|---|
| `.github/workflows/pr-validation.yml` | PR: classification + selected tests + governance gate |
| `.github/workflows/release.yml` | main push: test→build→staging→承認→progressive deploy→ledger→通知 |
| `.github/workflows/rollback.yml` | 緊急手動 rollback（workflow_dispatch） |
| `.github/actions/deploy-service/`（composite） | snapshot→promote→smoke→rollback-on-fail |
| `scripts/release/classify_change.py` | diff_risk.py の薄い CLI ラッパ |
| `scripts/release/smoke_test.py` | endpoint registry 準拠の read-only smoke |
| `requirements.lock` | pip-compile 生成物 |
| GCP: WIF pool/provider・SA 3種・`gs://yu-release-ledger` | 人間が1回だけ setup（runbook 提供） |
| GitHub: Environment `production`（reviewer=ゆうさん） | 人間が1回だけ setup |

### 変更禁止対象（Release OS が触れないもの）

- 既存 Core / Agents / Skills / Knowledge / QA（削除・移動なし）
- Cloud Scheduler（作成・変更・ON/OFF 一切なし。release.yml は Scheduler API を呼ばない）
- Secret / token / credentials（コード・Workflow への直書き禁止。SM/WIF のみ）
- `scripts/acquisition/**`（frozen のまま）
- pasta_pasta / z1 / yu-holdings-ai（deploy allowlist 外）
- 既存 PR フロー（pr_auto_flow.sh）— Release OS は Merge **後**を担当し役割が重ならない

### 段階移行と rollback map

| 段階 | 導入物 | 戻し方 |
|---|---|---|
| R1 | CI + pr-validation.yml | workflow ファイル削除（本番影響ゼロ） |
| R2 | classification + test selection | 同上（PR ゲートは governance_gate 継続） |
| R3 | release.yml（deploy は dry-run モード） | `RELEASE_MODE=dry_run` へ戻す（repo variable） |
| R4 | Ledger | 書込み停止のみ（読み手なし） |
| R5 | Environment 承認 + LINE 通知 | Environment の reviewer 解除で従来手動へ |
| R6-7 | 実 deploy（canary→3事業） | rollback.yml + 従来の手動 gcloud 手順（runbook 維持） |
| R8 | resume/lock/emergency | 個別 feature flag で無効化 |

**移行中の並行運用**: R6 で catering canary が安定するまで、従来の手動 deploy 手順
（`docs/pr20_production_rollout_runbook.md` 相当）を廃止しない。Release OS が2回連続で
無事故 deploy したら手動手順を「緊急時のみ」に降格。

### Phase R1 実装結果（2026-07-15）

| 追加物 | 状態 |
|---|---|
| `.github/workflows/pr-validation.yml` | 新規作成（既存 workflow 0本＝重複・Required Check 衝突なし） |
| `requirements.lock` | 新規作成（`requirements.txt` を正本に py3.11 で freeze・71 pkg・== 固定） |

**既存資産の無変更を確認**: Core / Agents / Skills / Knowledge / Governance / Registry /
`governance_gate.py` / `pr_auto_flow.sh` / `safe_auto_merge_pr.sh` / 既存テスト / CLAUDE.md /
Cloud Run いずれも変更・削除・移動なし。`requirements.txt` も無変更（lock は追加のみ）。
**rollback**: PR を merge しない / branch 削除 / workflow revert で完結（本番非接触のため
Cloud Run rollback 不要）。R2 以降は未着手。

## Phase R2 実装結果（2026-07-15）

追加のみ: `core/governance/diff_risk.py` に `classify_change` 追加（既存 `classify_paths` /
secret / runaway helper は無変更）・`scripts/release/classify_change.py`（新規）・
`tests/governance/test_change_classification.py`（新規25件）・`pr-validation.yml` 更新。
既存 Core/Agents/Skills/Governance の決定経路（`validator.py`）は無変更。rollback は
revert / branch 削除で完結（本番非接触）。分類の正本は diff_risk.py 単一（複数ファイル管理なし）。

## Phase R2.5 実装結果（2026-07-16）

追加のみ: `scripts/release/bootstrap_release_infra.sh`（新規）+ `tests/release/test_bootstrap_plan.py`
（新規11件）+ docs。既存 Core/Agents/Skills/Governance/Registry 無変更。infra 作成は
`--apply`（人間・CONFIRM=yes）で行い、Claude Code は plan/verify(read-only) のみ実行。rollback は
revert / branch 削除、infra は `--rollback-plan` の逆順（人間）。SSOT: 事業/サービス/リージョンは
`configs/businesses/registry.yaml`、infra 名は bootstrap スクリプトが正本。
