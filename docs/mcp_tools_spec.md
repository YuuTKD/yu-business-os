# MCP Tools 仕様（Phase 1 / Read-Only / 8 tools）

すべて **引数なし・読み取り専用**。`tools/call` の `arguments` は空オブジェクトでよい。

| # | tool名 | 返す内容 | データ元 |
|---|---|---|---|
| 1 | get_system_health | Cloud Run/Scheduler/Sheets接続・直近エラー・危険度・最終チェック日時 | SYSTEM_HEALTH_DASHBOARD（最新行・読むだけ） |
| 2 | get_cash_flow_status | 現金残高・7日入金/支払予定・不足見込み・危険度・今日のアクション | Cash Flow Survival OS |
| 3 | get_profit_leak_status | 事業別粗利率・危険事業・利益漏れ・改善アクション・危険度 | Profit Leak Detector |
| 4 | get_lead_status | S/Aリード数・未対応数・推定売上合計 | Lead Command Center |
| 5 | get_catering_sales_status | 営業先数・優先度内訳・状況内訳 | Catering B2B Sales Autopilot |
| 6 | get_daily_action_status | 事業別タスク数・完了/未完了・完了率 | Daily Action Commander |
| 7 | get_knowledge_status | GCS保存件数・同期状況など | Knowledge OS |
| 8 | get_owner_briefing | 5行サマリー（危険/売上/未対応/資金繰り/Yes-No判断） | 1〜6の統合 |

## tools/call リクエスト例
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": { "name": "get_owner_briefing", "arguments": {} }
}
```

## tools/call レスポンス例
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [{ "type": "text", "text": "【オーナーブリーフィング（5行）】..." }],
    "isError": false
  }
}
```

## 出力サンプル（get_owner_briefing）
```
【オーナーブリーフィング（5行）】
1. 今日一番危険: 🔴 資金繰り危険度S・不足¥2,397,751・今日必要な売上¥2,397,751
2. 今日一番売上に: Sリード9件・推定売上¥1,471,000
3. 確認すべき未対応: 未対応リード13件
4. 資金繰り注意: 危険日接近・要回収
5. Yes/No判断: 支払い分割/回収前倒しを今日やるか？
```

## 制約
- write系tool（更新/送信/投稿/削除）は **存在しない**。
- 引数で対象期間・事業を指定する機能は Phase 1 では未提供（全社の最新状態を返す）。
- Phase 2 で必要に応じ「事業指定」「期間指定」のread-only引数を追加可能。
