# MCP セキュリティポリシー（Phase 1）

## 基本方針
Phase 1 MCPサーバーは **READ-ONLY 限定**。Claude（または接続元）から
データの確認・取得・要約のみ可能で、状態を変える操作は一切できない。

## 実装済みの保証
- ✅ MCP tools は **8つのみ**（tools/list で固定返却）
- ✅ 全tool が read-only（Sheets更新・LINE送信・投稿・削除・デプロイ・Scheduler変更なし）
- ✅ write系メソッド/tool は **未実装**（呼ぶ手段が存在しない）
- ✅ 返却から秘密情報を除外（`_scrub()` で長尺トークンをマスク）
- ✅ 環境変数の値・Channel secret・APIキーは返さない
- ✅ 既存REST APIに影響なし（/health 等は従来どおり）

## 認証の現状と確認結果

### Claudeカスタムコネクタの認証要件（確認事項への回答）
1. **OAuthなしで追加可能か**: MCPサーバー自体は無認証で稼働可能（MCP Inspector / curl で接続可）。
   Claude.ai のカスタムコネクタは、リモートMCP URL登録時に **OAuth Client ID / Secret 欄は任意（空欄可）**。
   空欄で登録を試せる。
2. **OAuth Client ID/Secret 空欄でも接続できるか**: 多くの場合、接続時に Claude 側が
   OAuth メタデータ（`/.well-known/oauth-protected-resource` 等）を探索する。
   見つからない場合、クライアントのバージョンにより「無認証で接続」または「認証が必要」と表示され得る。
   → **まず空欄で登録を試し、弾かれたら OAuth メタデータ追加（Phase 1.5）が必要**。
3. **接続不可時に必要な認証方式**: OAuth 2.0（Authorization Code + PKCE）+
   `/.well-known/oauth-authorization-server` / `/.well-known/oauth-protected-resource` の提供。
4. **allUsers公開でread-only MCPを出すリスク**:
   - URLを知る第三者が経営KPI（売上・資金繰り危険度・リード・利益）を取得し得る = **情報漏えいリスク（中〜高）**。
   - write不可なのでデータ改ざん・送信被害はないが、機密性の観点で要対策。
5. **最低限追加すべきアクセス制限（推奨）**:
   - **`MCP_ACCESS_TOKEN` を設定**（実装済み）。設定すると `Authorization: Bearer <token>` 必須。
     Claudeコネクタ側で同ヘッダを送れる場合はこれで簡易保護可能。
   - 将来的に OAuth 2.0 を実装し正式保護。
   - またはCloud Run の Ingress/IAM制限（ただしClaudeからの到達性とトレードオフ）。

## 推奨運用（Phase 1）
- テスト/個人利用の間は無認証でも可（read-only・データ閲覧のみ）。
- 本格運用前に **`MCP_ACCESS_TOKEN` 設定** または **OAuth実装** を行う。
- 機密度が高い場合は、公開前に必ずアクセス制限を有効化する。

## 禁止事項（Phase 1で実装しないもの）
Sheets更新 / LINE送信 / Cloud Runデプロイ操作 / Cloud Scheduler変更 / IAM変更 /
ファイル削除 / 投稿 / 外部顧客送信 / スタッフ本番通知 / 秘密情報表示 / 環境変数値表示。
