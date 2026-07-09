# 商品マッチ先AIエージェント 停止記録

停止日: 2026-07-08
停止理由:
  fake/mock候補（fake_serp_realistic_mock）が混入し、
  全10件がスマホ手動確認で NOT_FOUND / MOCK_ONLY となった。
  「ゆうさんの手作業削減・Yes/Noだけで進む」目的に反するため一時停止。

現状:
  ENABLED=false / PAUSED=true / LINE_NOTIFY_ENABLED=false
  REPLY_READY=0件 / 全候補EXCLUDE済み
  Scheduler: OFF（変更なし）

再開条件:
  - SerpAPI / Google CSE 等 live 検索が利用可能になった場合のみ
  - 実在URL確認済み候補が取れる仕組みが整った場合

次に優先する導線:
  インバウンド型（自分の投稿 → 反応者管理 → 返信文生成 → 興味ありだけDM）

禁止継続事項:
  - 自動リプ / 自動DM
  - Scheduler ON
  - mock候補のLINE通知
  - Secret/token表示
