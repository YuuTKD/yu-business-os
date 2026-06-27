# Claude カスタムコネクタ 登録手順

## 登録情報

| 項目 | 値 |
|---|---|
| 名前 | YU HOLDINGS AI |
| リモートMCPサーバーURL | `https://yu-holdings-ai-qpiiccdspa-an.a.run.app/mcp` |
| OAuth Client ID | **不要（空欄）** ※まず空欄で試す |
| OAuth Client Secret | **不要（空欄）** ※まず空欄で試す |

## 登録手順（Claude.ai）
1. Claude.ai → 設定（Settings）→ Connectors（コネクタ）
2. 「Add custom connector / カスタムコネクタを追加」
3. **名前**: `YU HOLDINGS AI`
4. **URL**: `https://yu-holdings-ai-qpiiccdspa-an.a.run.app/mcp`
5. 「Advanced settings」内の **OAuth Client ID / Secret は空欄のまま**
6. 「追加 / Connect」

## 接続後にテストする質問
- 今日のYU HOLDINGS全体の状況を教えて
- 資金繰り危険度を教えて
- 今日のSリードを教えて
- TACHINOMIYAの今日のタスク状況を教えて
- オーナーブリーフィングを出して

## うまく接続できない場合
1. **「認証が必要」と出る** → Claudeクライアントが OAuth メタデータを要求している。
   - 対応: Phase 1.5 として `/.well-known/oauth-protected-resource` 等を実装（別途対応）。
2. **接続はできるがツールが見えない** → URL末尾が `/mcp` か、最新revisionか確認。
3. **データが空** → 対象システムにデータ未投入（read-onlyなので閲覧のみ）。

## アクセス制限を有効化したい場合（推奨）
1. `MCP_ACCESS_TOKEN` をCloud Runに設定
2. Claudeコネクタ側でカスタムヘッダ `Authorization: Bearer <token>` を送れる場合のみ有効
   （送れない場合は OAuth 実装が必要）

## 補足
- 本コネクタは **read-only**。Claudeから経営状況の確認・要約はできるが、
  データ更新・送信・投稿は一切できない（安全）。
