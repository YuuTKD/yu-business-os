# YU HOLDINGS AI — Read-Only MCP Server 実装メモ

## 概要
既存 Flask製 REST API（yu-holdings-ai / Cloud Run）に、Claudeカスタムコネクタ用の
リモートMCPサーバー（Streamable HTTP / JSON-RPC 2.0）を `/mcp` として追加。

- **Phase 1 = READ-ONLY 限定**。write系tool・更新・送信は一切なし。
- 8 toolsのみ公開（確認・取得・要約）。
- 既存RESTを薄くラップ。既存エンドポイントは無影響。
- OpenAI不使用。

## 実装方式
- **MCPライブラリ非依存（自前実装）**。
  - 理由: 公式 `mcp` Python SDK は ASGI/async前提で、現行の Flask(WSGI)+gunicorn 構成に
    そのまま載せられない。JSON-RPC 2.0 を直接実装する方が依存・攻撃面・障害点が少なく安全。
  - そのため requirements.txt への追加は不要（新規依存ゼロでデプロイ）。
- トランスポート: **Streamable HTTP**。`POST /mcp` に JSON-RPC を受け、`application/json` で応答。
  - `GET /mcp` → 405（サーバー起点SSEは未使用）
  - `DELETE /mcp` → 204（ステートレス）
  - 応答に `Mcp-Session-Id` ヘッダ付与（互換性向上・ステートレス）

## ファイル
- `core/mcp_server.py` — TOOLS定義・JSON-RPCハンドラ・各tool（read-only）
- `core/entrypoint.py` — `/mcp` ルート追加（POST/GET/DELETE）

## 対応メソッド
| method | 動作 |
|---|---|
| initialize | protocolVersion / capabilities / serverInfo を返す |
| notifications/initialized | 本文なし(202) |
| ping | 空result |
| tools/list | 8 tools を返す |
| tools/call | read-only tool実行、text contentを返す |
| 未対応 | -32601 Method not found |

## tool → 既存機能マッピング（すべて read-only）
| tool | 呼び出し（write=Falseのみ） |
|---|---|
| get_system_health | SYSTEM_HEALTH_DASHBOARD 最新行を読むだけ（チェック実行=書込はしない） |
| get_cash_flow_status | cash_flow.get_status |
| get_profit_leak_status | profit_leak.get_status |
| get_lead_status | lead_command.get_status |
| get_catering_sales_status | catering_sales.get_status |
| get_daily_action_status | daily_action_commander.get_status |
| get_knowledge_status | knowledge_os.get_status |
| get_owner_briefing | 上記の統合（read-only） |

## 安全設計
- write系tool/メソッドは存在しない（tools/listに出ない＝呼べない）。
- 返却テキストは `_scrub()` で40文字以上のトークン様文字列をマスク（最終防衛）。
- 環境変数の値・チャンネルシークレット・APIキーは返さない。
- 任意のアクセス制限: 環境変数 `MCP_ACCESS_TOKEN` を設定すると
  `Authorization: Bearer <token>` 必須になる（未設定なら無認証＝現状）。

## 本番URL
```
https://yu-holdings-ai-qpiiccdspa-an.a.run.app/mcp
```

## デプロイ
通常の `gcloud run deploy yu-holdings-ai --source .`。新規依存なし。
revision 00022-qnw で本番反映済み。
