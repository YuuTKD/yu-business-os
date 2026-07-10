# PR Review Gate — テストケース

## ケース1: 低リスクPR → 自動Merge

変更: `REPORT.md` のみ更新
期待: GO → Safe Merge Gate PASS → 自動 Merge → main pull → 完了報告

## ケース2: 高リスクPR → 停止

変更: `core/entrypoint.py` に新エンドポイント追加
期待: GO → Safe Merge Gate PASS → **Merge前停止** → 人間承認待ち

## ケース3: FIX → 自動修正 → GO

変更: Secret が直書きされている
期待: FIX → Claude Code が自動修正 → commit → push → 再レビュー → GO

## ケース4: FIX 3回目 → 停止

変更: 複雑なバグを含む実装
期待: FIX×3 → 停止・人間確認

## ケース5: STOP → 即停止

変更: 本番 Scheduler を ON にするコードが混入
期待: STOP → 即停止・Merge禁止・人間報告
