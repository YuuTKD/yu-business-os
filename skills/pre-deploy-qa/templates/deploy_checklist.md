# デプロイ前後チェックリスト（毎回コピーして使用）

## デプロイ前（全項目☑してから実行）
- [ ] git status を確認し、意図しないファイルが含まれていない
- [ ] .env / credentials / client_secret / 秘密鍵 / backups が含まれていない
- [ ] 変更ファイルにSecret・token・APIキーの直書きがない（grep確認）
- [ ] deleted_files がある場合、削除理由と参照ゼロ確認を記録した
- [ ] core/ configs/ の変更は「新規追加のみ」である
- [ ] project_id：【　　　】← 本番と目視一致を確認した
- [ ] service_name / region：【　　　/　　　】← 過去デプロイと一致
- [ ] traffic：【100% / canary　%】← 100%即時の場合は理由を記載
- [ ] Scheduler変更を含む → scheduler-readiness-checkの判定結果を添付した
- [ ] 本番投稿を含む → ゆうさんの承認を得た（日時：　）
- [ ] rollback：直前revision【　　　】/ 切り戻しコマンドを控えた

## デプロイ後（15分以内に実施）
- [ ] 新revisionが想定どおり作成された（revision名：　）
- [ ] traffic配分が計画どおり
- [ ] ヘルスチェック / 主要エンドポイントの応答確認
- [ ] Cloud Runログにエラーが出ていない（最初の10分）
- [ ] 連携先（Sheets / GCS / LINE通知）の疎通1件確認
- [ ] 異常時：控えたコマンドで旧revisionへ切り戻し → LINEで共有

## 記録（デプロイ台帳へ1行追記）
日時 / 作業者 / 変更概要 / revision / 判定（GO） / 特記
