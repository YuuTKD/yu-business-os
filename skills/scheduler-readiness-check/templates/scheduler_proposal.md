# Scheduler提案書式（READY判定時のみ作成）

```
【Scheduler ON提案】

■ 対象
- 事業：
- ジョブ：
- 判定：READY（scheduler-readiness-check 実施日：　）

■ 実行設定（初回＝最小頻度）
- 頻度（日本語）：例）平日1日1回 18:00
- cron：例）0 18 * * 1-5（Asia/Tokyo）
- daily_limit：
- posting_window：

■ 観察期間
- 期間：14日間（　月　日〜　月　日）
- 観察中の頻度変更：禁止（引き上げは期間終了後に再判定）

■ 停止条件（1つでも該当したら即OFF）
1. 連続2回の投稿失敗
2. 品質スコア週平均7.0未満
3. LINE通知の未達を検知
4. theme_match FAILの発生
5. ゆうさん・担当者の判断（理由不問で止めてよい）

■ 監視体制
- LINE通知確認：【担当】が【毎朝9時/投稿後】に確認
- 週次レビュー：毎週月曜のKPIレビューで実績報告
- OFF操作の権限者：ゆうさん・【担当】（手順書：　　に格納）

■ 切り戻し手順（要約）
1. auto_post_enabled を false に変更
2. LINEで「停止しました」を関係者に共有
3. 原因記録 → 再開は scheduler-readiness-check の再判定から

■ 承認
この設定でONしてよいですか？ Yes/No（ゆうさん）
```
