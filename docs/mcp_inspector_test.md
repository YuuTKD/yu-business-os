# MCP Inspector テスト手順

公式 MCP Inspector で YU HOLDINGS AI MCPサーバーを検証する手順。

## 起動コマンド
```bash
npx @modelcontextprotocol/inspector
```
ブラウザでInspector UIが開く（通常 http://localhost:6274 ）。

## 接続設定
| 項目 | 値 |
|---|---|
| Transport type | **Streamable HTTP** |
| URL（本番） | `https://yu-holdings-ai-qpiiccdspa-an.a.run.app/mcp` |
| URL（ローカル） | `http://localhost:8088/mcp`（ローカル起動時） |
| 認証 | なし（MCP_ACCESS_TOKEN未設定時）。設定時は Header に `Authorization: Bearer <token>` |

> SSE(Transport=SSE)ではなく **Streamable HTTP** を選ぶこと。

## ローカル起動（任意・ローカルURL検証時）
```bash
cd ~/yu-business-os
export GOOGLE_CREDENTIALS_B64="(Cloud Runと同じ値)"
export GOOGLE_SPREADSHEET_ID="1I6wRRDa-b440DBxZ3TbFbfMxEXZecowzOsxTAYSxyBE"
export BUSINESS_NAME=beauty PORT=8088
python3 -m core.entrypoint
```

## 確認1: 接続 & initialize
- 「Connect」→ 成功すると Server info に `YU HOLDINGS AI / 1.0.0` が表示される。

## 確認2: tools/list
- 「Tools」タブ → **8個** のtoolが表示されること:
  get_system_health / get_cash_flow_status / get_profit_leak_status / get_lead_status /
  get_catering_sales_status / get_daily_action_status / get_knowledge_status / get_owner_briefing
- write系（更新/送信/削除）が **無い** こと。

## 確認3: tools/call
- `get_owner_briefing` を実行（arguments 空）→ 5行サマリーのtextが返る。
- `get_cash_flow_status` を実行 → 危険度・現金残高等が返る。
- `isError: false` であること。

## curl での等価確認（Inspectorなしでも検証可）
```bash
BASE=https://yu-holdings-ai-qpiiccdspa-an.a.run.app

# initialize
curl -s -X POST $BASE/mcp -H "Content-Type: application/json" \
 -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}'

# tools/list
curl -s -X POST $BASE/mcp -H "Content-Type: application/json" \
 -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

# tools/call
curl -s -X POST $BASE/mcp -H "Content-Type: application/json" \
 -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_owner_briefing","arguments":{}}}'
```

## 成功判定
- initialize: `result.serverInfo.name == "YU HOLDINGS AI"`
- tools/list: `result.tools` が **8件**
- tools/call: `result.content[0].text` にデータ、`result.isError == false`
- 既存REST: `GET /health` が `{"status":"ok"}`

## 失敗時の確認項目
| 症状 | 確認 |
|---|---|
| 404 | デプロイ反映確認（最新revision）／URL末尾 `/mcp` |
| 405 | GETで叩いていないか（POSTで送る） |
| 401 | MCP_ACCESS_TOKEN設定時はBearerヘッダ必須 |
| Parse error(-32700) | Content-Type: application/json とJSON妥当性 |
| tools/callでisError:true | Sheetsアクセス/対象シート有無（read-only side）を確認 |
| Claudeコネクタで認証要求 | OAuthメタデータ未提供 → security_policy参照（Phase1.5でOAuth追加） |
