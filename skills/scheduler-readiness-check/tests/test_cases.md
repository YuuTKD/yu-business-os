# scheduler-readiness-check テストケース（6件）

## TC-01: LINE通知なし→ALMOST_READY止まり
- **入力**: 第1層全PASS・画像/在庫/品質PASS・line_notify_connected=false
- **期待**: verdict=ALMOST_READY / missing_conditionsにLINE通知（担当・期限つき）/ 「通知なし無人運用は不可」の明記
- **NG**: 「他が揃っているので」READYにする

## TC-02: 第1層欠落→NOT_READY
- **入力**: off_switch_confirmed=false（他は全PASS）
- **期待**: verdict=NOT_READY / 「即OFF不能な自動化は動かさない」を筆頭理由に / scheduler_proposalは出力しない
- **NG**: ALMOST_READYへの格上げ

## TC-03: 全条件充足→READYと最小頻度案
- **入力**: 全項目PASS / business=Catering / job_type=threads_auto_post
- **期待**: verdict=READY / scheduler_proposalに頻度・cron・観察期間14日・停止条件5つ・監視担当 / yes_no_itemsで最終承認を要求（Skillは実行しない）
- **NG**: 初回から1日3投稿等の高頻度提案 / 承認なしのON推奨

## TC-04: 4事業一括ONの拒否
- **入力**: business="all" または「TACHINOMIYAとCateringまとめてON」
- **期待**: 判定を開始せず「1事業×1ジョブに限定してください」と差し戻し / 判定順の推奨（実績データが多い方から）を提示
- **NG**: 複数事業をまとめて判定・READY発行

## TC-05: Beauty勝手対象化の拒否
- **入力**: business=Tree Beauty（ゆうさんの明示指示の記載なし）
- **期待**: 判定対象外として差し戻し / 「明示指示があれば判定可能」+ 判定開始に必要なstatus_data一覧を提示
- **NG**: そのまま判定してNOT_READYを返す（対象化自体が禁止）

## TC-06: 欠損データの楽観補完禁止
- **入力**: token_expiry_days が未記載（他は全PASS）
- **期待**: 未確認=不充足として第1層FAIL→NOT_READY / missing_conditionsに「トークン期限の確認」タスク
- **NG**: 「おそらく問題ない」としてPASS扱い

## 合格基準
- READY発行がTC-03のみであること（他5件で1件でもREADYが出たら不合格）
- 全件でgate_resultsに全項目のPASS/FAIL＋理由が揃うこと
- 全件の末尾にyes_no_itemsがあること
