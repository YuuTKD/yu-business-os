---
name: pre-deploy-qa
description: Cloud Run / GitHub / Claude Codeでの本番作業（デプロイ・push・設定変更）前の安全確認Skill。GO/STOP/要確認の3段階で判定する。「デプロイしていい？」「pushする前に確認」「Cloud Runに反映」「本番作業」「gcloud run deploy」等の話題が出たら、実行前に必ずこのSkillでチェックすること。判定なしの本番デプロイは禁止。Secret混入・誤プロジェクト・Scheduler誤ON・既存ファイル削除の4大事故を防ぐ。
---

# pre-deploy-qa（本番デプロイ前 安全確認Skill）

## 目的
yu-business-os（Cloud Run / GCS / GitHub / Sheets / Threads API / LINE通知連携）の本番反映前に、
**Secret混入・誤プロジェクト・Scheduler誤ON・既存資産の破壊**を機械的に検出し、GO/STOP/要確認で判定する。

## 対象
- Cloud Runへのデプロイ（gcloud run deploy / CI経由）
- GitHubへのpush・マージ（特にmainブランチ）
- Claude Codeによる自動作業の実行前レビュー
- 環境変数・設定ファイルの変更

## 使う場面
- デプロイコマンド実行の直前（毎回・例外なし）
- Claude Codeに本番系の作業を依頼する前の指示文チェック
- 障害対応中の緊急デプロイ（緊急時こそ省略禁止）
- 外注・スタッフがリポジトリに触る作業の事前レビュー

## 入力スキーマ
```yaml
deploy_check:
  work_summary: string        # 今回の変更内容（1〜3行）
  git_status_output: string   # git status / git diff --stat の出力貼り付け
  changed_files: [string]
  deleted_files: [string]
  target:
    project_id: string        # デプロイ先GCPプロジェクト
    service_name: string
    region: string
    traffic_plan: string      # 例: "100%即時" / "canary 10%"
  includes_scheduler_change: bool
  includes_live_posting: bool   # 本番投稿を伴うか
  rollback_plan: string|null
```

## 判定ロジック（3分類・STOP優先）
**STOP（即中止・1つでも該当したら他の評価は不要）**
| # | 検出条件 |
|---|---|
| S1 | Secret/token/APIキー/パスワードらしき文字列が変更ファイルに含まれる（`api_key=`, `token`, `secret`, `Bearer `, 長いランダム文字列等のパターン） |
| S2 | `.env` / `credentials*.json` / `client_secret*.json` / 秘密鍵ファイルがgit管理に追加されている |
| S3 | `backups/` や dumpファイルのコミット混入 |
| S4 | project_id が本番想定と不一致、または未確認 |
| S5 | 既存ファイルの削除（deleted_files非空）で、削除理由と影響確認が work_summary に無い |
| S6 | includes_scheduler_change=true なのに scheduler-readiness-check の判定結果が添付されていない |
| S7 | includes_live_posting=true なのにゆうさんの事前承認記載が無い |
| S8 | core/ configs/ 配下の変更が「新規追加以外」（既存の編集・削除） |

**要確認（人間の目視確認後にGO可）**
| # | 検出条件 |
|---|---|
| C1 | rollback_plan が空（切り戻し手順なしのデプロイ） |
| C2 | traffic_plan が「100%即時」（canary/段階反映の検討余地） |
| C3 | region / service_name が過去のデプロイ履歴と異なる |
| C4 | 変更ファイル数が10超（レビュー粒度が粗い） |
| C5 | 認証情報のスクリーンショット・ログ貼り付けがwork_summaryや添付に含まれる疑い |

**GO（上記すべて非該当）**
- デプロイ前/後チェックリストを添えてGO判定

## 実行手順
1. git_status_output・changed_filesを走査し、S1〜S3のSecret系パターンを検出（**検出しても内容は出力に転記しない。ファイル名と行番号の指摘のみ**）
2. target情報をS4基準で照合（不明・未記載=STOP）
3. 削除・core/configs変更・Scheduler・本番投稿のS5〜S8を判定
4. STOPなし→C1〜C5の要確認を判定
5. 判定＋修正案＋デプロイ前後チェックリスト＋Claude Codeへ返す確認文を出力

## 出力スキーマ
```yaml
result:
  verdict: GO | STOP | 要確認
  findings: [{id, 深刻度, 場所（ファイル名/行）, 修正案}]  # Secret値そのものは絶対に記載しない
  pre_deploy_checklist: [string]
  post_deploy_checklist: [string]   # 例: revisionの確認 / ヘルスチェック / ログ確認 / 旧revisionへの切り戻しコマンド確認
  claude_code_reply: string         # Claude Codeにそのまま返す確認・修正指示文
  yes_no_question: string           # GO時のみ「この内容でデプロイしますか？ Yes/No」
```

## 禁止事項
- Secret・token・鍵の**値**を出力に含めること（指摘はファイル名・行番号・種別のみ）
- 危険箇所を残したままGOにすること
- 本番投稿・Scheduler追加を勝手に許可すること（該当時は必ず承認確認）
- project_id不一致・未確認の見逃し
- 既存ファイル削除を「たいした影響はない」と軽視すること
- 緊急を理由としたチェック省略の容認

## 人間確認が必要なポイント
- STOP解除の最終判断（修正後の再チェックはSkill、解除はゆうさん）
- 本番投稿を伴うデプロイの実行承認
- core/ configs/ への新規追加が既存動作に影響しないかのレビュー
- 初めてのregion/サービス名でのデプロイ

## 成功条件
- Secret混入・誤プロジェクトデプロイ・意図しないScheduler ON・既存資産削除の発生ゼロ
- STOP判定→修正→再チェック→GOのループが1日以内に回る
- Claude Codeへの確認文がそのまま貼れて作業が止まらない

## 失敗条件
- findingsに場所（ファイル名）が無い指摘
- STOP該当があるのに要確認/GOに分類
- Secret値が出力に転記されている（このSkill自体の最重大事故）

## 入力例
```yaml
deploy_check:
  work_summary: "Threads投稿のtheme_matchロジック改善。configs/に新規テーマ定義を追加"
  git_status_output: |
    M  services/post_generator.py
    A  configs/themes_tachinomiya.yaml
    A  .env
    D  services/old_matcher.py
  changed_files: ["services/post_generator.py", "configs/themes_tachinomiya.yaml", ".env"]
  deleted_files: ["services/old_matcher.py"]
  target: {project_id: "yu-business-os-prod", service_name: "post-service", region: "asia-northeast1", traffic_plan: "100%即時"}
  includes_scheduler_change: false
  includes_live_posting: false
  rollback_plan: null
```

## 出力例（要点）
```yaml
result:
  verdict: STOP
  findings:
    - {id: S2, 深刻度: 重大, 場所: ".env（git追加）", 修正案: "git rm --cached .env → .gitignoreに追加 → 履歴に載った場合は鍵のローテーション"}
    - {id: S5, 深刻度: 重大, 場所: "services/old_matcher.py（削除）", 修正案: "削除理由・参照元ゼロの確認をwork_summaryに追記。不明なら削除を取り消し、deprecated/へ移動提案（人間承認後）"}
    - {id: C1, 深刻度: 中, 場所: "rollback_plan未記載", 修正案: "直前revision名と切り戻しコマンドを1行で記載"}
    - {id: C2, 深刻度: 低, 場所: "traffic_plan=100%即時", 修正案: "canary運用の要否をゆうさん判断"}
  claude_code_reply: |
    STOPです。以下を修正後、pre-deploy-qaを再実行してください。
    1. .env をgit管理から除外（git rm --cached .env）し .gitignore に追加。コミット履歴に含まれた場合は該当キーをローテーション
    2. services/old_matcher.py の削除を保留。参照ゼロを確認できるまで削除しない
    3. rollback_plan（直前revisionへの切り戻し手順1行）を追記
    修正完了後に再チェックします。デプロイはそれまで実行禁止です。
  yes_no_question: null
```

## テストケース
`tests/test_cases.md` に7ケース。

## テンプレート
- `templates/deploy_checklist.md` — デプロイ前後チェックリスト（毎回コピーして使用）
- `templates/claude_code_gate.md` — Claude Codeへの作業依頼に前置きする安全指示文

## 再利用先
- scheduler-readiness-check（S6で判定結果の添付を要求＝2Skill連携で二重ゲート）
- 外注エンジニア受け入れ時のレビュー標準
- GitHub ActionsのPRテンプレ・CIチェック項目の設計元
- ai-net-business-sns-osリポジトリにも同一基準を適用（横展開）

## 将来の改善余地
- Secret検出パターンのpre-commit hook化（ローカルで先に止める）
- デプロイ履歴台帳（日時・revision・判定結果）の自動記録
- canary運用の標準化（traffic 10%→100%の昇格基準）

## 判断軸への寄与
事故防止（4大事故の機械検出）／売却価値（デプロイ統制・変更管理の証跡＝デューデリ耐性）／外注委任（安全基準込みで作業を渡せる）
