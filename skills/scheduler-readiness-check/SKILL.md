---
name: scheduler-readiness-check
description: Cloud Schedulerや定期自動実行（自動投稿・自動DM等）をONにしてよいかをREADY/ALMOST_READY/NOT_READYの3段階で判定するSkill。「SchedulerをONにしたい」「自動化を回し始めたい」「無人運用に切り替えたい」「定期実行の準備できてる？」等の相談が来たら、実行前に必ずこのSkillで判定すること。判定なしのScheduler ONは禁止。
---

# scheduler-readiness-check（定期自動実行の開始判定Skill）

## 目的
「Threads実投稿1件成功した→じゃあ全部自動で」の飛躍を止め、
**無人で回して事故らない条件が揃った事業×機能だけ**を、最小範囲でONにする。

## 対象事業（現在のステータス前提）
| 事業 | 自動投稿の現状 | デフォルト扱い |
|---|---|---|
| TACHINOMIYA | Threads実投稿1件成功 | 判定対象 |
| TREE's Catering | Threads実投稿1件成功 | 判定対象 |
| Tree Beauty | 未着手 | **判定対象外（明示指示があるまで含めない）** |
| 琉球火鍋 | 未着手 | **判定対象外（同上）** |

## 使う場面
- Cloud SchedulerのON/頻度変更を検討するとき（実行前必須）
- 新しい定期ジョブ（自動DM・自動レポート等）の稼働開始判定
- 障害・事故後の再開判定（再開もこのSkillを通す）
- 週次での稼働中Schedulerの健全性レビュー

## 入力スキーマ
```yaml
readiness_request:
  business: string            # 1事業のみ。"all"は受け付けない
  job_type: string            # threads_auto_post / ig_auto_post / auto_dm / report 等
  status_data:
    successful_live_posts: int      # 実投稿成功件数
    checks_13_pass: bool            # 13/13チェック通過
    theme_match_pass: bool          # step13通過実績
    usable_images_by_theme: {テーマ: 枚数}
    post_queue_count: int           # 検品済み投稿候補在庫
    avg_quality_score: float        # sns-post-quality-checkの平均
    line_notify_connected: bool
    fail_stop_enabled: bool         # 失敗時自動停止
    off_switch_confirmed: bool      # auto_post_enabledフラグで即OFF可能か
    username_verified: bool         # 投稿先アカウントの確認
    token_expiry_days: int          # トークン残日数
    daily_limit_set: bool
    posting_window_set: bool        # 投稿時間帯制限
    log_updated: bool               # 直近実行ログが記録されているか
    rollback_doc_exists: bool       # 停止・切り戻し手順書の有無
```

## 判定ロジック（3層ゲート）
**第1層：ハード条件（1つでも欠けたら NOT_READY）**
1. off_switch_confirmed = true（即OFFできない自動化は動かさない）
2. fail_stop_enabled = true（連続失敗時の自動停止）
3. username_verified = true（誤アカウント投稿防止）
4. token_expiry_days ≥ 14（期限切れ事故防止）
5. successful_live_posts ≥ 1 かつ checks_13_pass = true

**第2層：運用条件（欠けたら ALMOST_READY止まり）**
6. line_notify_connected = true（無人運用の必須条件。**LINE通知なしで完全無人はいかなる場合も不可**）
7. 投稿予定テーマ全てで usable_images ≥ 5（image-library-manager基準）
8. post_queue_count ≥ 7日分（daily_limit×7以上）
9. avg_quality_score ≥ 8.0
10. daily_limit_set かつ posting_window_set = true
11. rollback_doc_exists = true

**第3層：範囲条件（判定結果に関わらず適用）**
- ONにできるのは **1回の判定につき1事業×1ジョブのみ**（4事業一括ON提案は禁止）
- Beauty・火鍋はゆうさんの明示指示がない限り対象外
- 初回ONは必ず「最小頻度案」（例：1日1投稿×平日のみ×14日間の観察期間）から

**判定マトリクス**
| 判定 | 条件 | 扱い |
|---|---|---|
| READY | 第1層+第2層すべて充足 | 最小頻度案でON可（ゆうさん最終Yes/No必須） |
| ALMOST_READY | 第1層充足・第2層に不足 | 不足条件と充足までの最短手順を提示。ON不可 |
| NOT_READY | 第1層に不足 | ON絶対不可。不足を赤字相当で明示 |

## 実行手順
1. business="all"や複数事業指定を拒否し、1事業に限定させる
2. status_dataの欠損項目を確認 → 欠損は「未確認=不充足」として扱う（楽観判定禁止）
3. 第1層→第2層→第3層の順に判定、各項目のPASS/FAILを表で出力
4. READY時：最小頻度のScheduler案（cron表現＋日本語）、停止条件、観察期間、監視方法を提示
5. ALMOST_READY/NOT_READY時：不足→充足の最短アクション（担当・期限つき）を提示
6. 末尾に必ずゆうさんのYes/No判断項目を出す

## 出力スキーマ
```yaml
result:
  verdict: READY | ALMOST_READY | NOT_READY
  gate_results: {項目: PASS/FAIL（理由）}   # 全項目
  missing_conditions: [{項目, 充足への最短手順, 担当, 期限目安}]
  minimum_scope: string        # ONにしてよい最小対象（事業×ジョブ×頻度）
  block_reasons: [string]|null
  scheduler_proposal:          # READY時のみ
    frequency: string          # 例: 平日1日1回 18:00
    cron: string
    observation_period: string # 例: 14日間
    stop_conditions: [string]  # 例: 連続2回失敗 / quality_score平均7未満 / LINE通知未達
    monitoring: string         # 誰が何をいつ見るか
  yes_no_items: [string]       # ゆうさんのYes/No判断項目
```

## 禁止事項
- 条件未達でREADYにすること（「ほぼ揃っているから」は不可）
- LINE通知未接続で完全無人運用をOKにすること
- 画像在庫不足（テーマ別5枚未満）でのON許可
- Beauty・火鍋を勝手に判定対象・ON対象にすること
- 4事業一括ON・複数ジョブ同時ONの推奨
- 欠損データの楽観補完（不明=不充足が原則）

## 人間確認が必要なポイント
- READY判定後の最終ON実行（ゆうさんのYes必須。Skillは判定までで実行しない）
- 観察期間終了後の頻度引き上げ判断
- 事故後の再開判定（原因対策の完了確認）
- 新事業（Beauty/火鍋）の判定対象追加

## 成功条件
- Scheduler起因の投稿事故ゼロを維持
- ON後14日間の観察期間で停止条件に一度も抵触しない
- ALMOST_READYの不足条件が「担当・期限つきタスク」としてそのまま実行に移せる

## 失敗条件
- 判定表に理由のないPASS/FAILがある
- READYなのにscheduler_proposal（頻度・停止条件・監視）が欠けている
- 不足条件が「準備を整えましょう」等の抽象論

## 入力例
```yaml
readiness_request:
  business: TACHINOMIYA
  job_type: threads_auto_post
  status_data:
    successful_live_posts: 1
    checks_13_pass: true
    theme_match_pass: true
    usable_images_by_theme: {サーターアンダギー: 3, 泡盛: 0}
    post_queue_count: 4
    avg_quality_score: 8.2
    line_notify_connected: false
    fail_stop_enabled: true
    off_switch_confirmed: true
    username_verified: true
    token_expiry_days: 32
    daily_limit_set: true
    posting_window_set: true
    log_updated: true
    rollback_doc_exists: true
```

## 出力例（要点）
```yaml
result:
  verdict: ALMOST_READY
  gate_results:
    第1層: 全5項目PASS
    LINE通知: "FAIL（未接続。無人運用の必須条件）"
    画像在庫: "FAIL（サーターアンダギー3枚<5、泡盛0枚）"
    投稿候補在庫: "FAIL（4件<7日分）"
    品質スコア: "PASS（8.2）"
  missing_conditions:
    - {項目: LINE通知接続, 充足への最短手順: "失敗/成功の通知をLINE公式に接続しテスト送信1件", 担当: ゆうさん（実装承認）, 期限目安: 7/8}
    - {項目: 画像在庫, 充足への最短手順: "撮影依頼（image-library-managerのphoto_request実行済み文面を使用）", 担当: ゆうと, 期限目安: 7/11}
    - {項目: 投稿候補在庫, 充足への最短手順: "検品済み投稿を+3件ストック", 担当: スタッフ+quality-check, 期限目安: 7/10}
  minimum_scope: "TACHINOMIYA × threads_auto_post のみ（Catering は別判定）"
  yes_no_items:
    - "LINE通知の接続作業を今週の最優先にしますか？ Yes/No"
    - "充足後の初回ONは『平日1日1回18:00×14日観察』案で進めますか？ Yes/No"
```

## テストケース
`tests/test_cases.md` に6ケース。

## テンプレート
- `templates/readiness_checklist.md` — ON前チェックリスト（印刷・チャット貼付用）
- `templates/scheduler_proposal.md` — Scheduler提案書式（停止条件・監視込み）

## 再利用先
- pre-deploy-qa（Scheduler追加を伴うデプロイの事前判定として連携）
- image-library-manager / sns-post-quality-check（在庫・品質データの供給元）
- Beauty・火鍋の自動化開始時にそのまま同一基準を適用（横展開）
- 自動DM・自動レポート等、投稿以外の定期ジョブにも同じ3層ゲートを転用

## 将来の改善余地
- status_dataの自動収集（ログ・シートからの読み取り専用集計）
- 観察期間中のKPI自動レポート（停止条件への接近を事前警告）
- 頻度引き上げの段階基準（14日無事故→2投稿/日、等）の定式化

## 判断軸への寄与
事故防止（無人運用の3層ゲート）／完全自動運用（安全にONへ進む唯一の関門）／稼働ゼロ（ゆうさんの判断をYes/No 2問に圧縮）
