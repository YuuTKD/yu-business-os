# 売上成長オペレーションチーム — 使い方

各事業の「利益を伸ばす」運営チーム。運営統括AI(ops)が事業ごとに編成し、新メニュー提案・
リサーチ・分析・集客・価格/粗利改善・リピート施策までを**提案・分析・下書き**で出す。
価格変更/仕入/投稿/送信/公開は人間承認後のみ。

## 起動
```
python3 scripts/team/growth_plan.py --business "TACHINOMIYA"        # 事業の成長プラン案
python3 scripts/team/assemble_team.py --instruction "新メニューとMEO"  # 依頼から編成
```
Claude に「TACHINOMIYAの売上伸ばして」等 → Skill `production-pm`（運営統括）が起動。

## 12役割（SSOT: configs/team/roles.yaml）
①運営統括 ②商品開発 ③市場リサーチ ④データ分析 ⑤集客(⑥MEO ⑦SNS ⑧口コミ・紹介)
⑨収益設計 ⑩顧客成功(⑪失客復活) ⑫営業。

## 事業タイプ別テンプレ
立ち飲み/ケータリング/サロン/火鍋/コンサル/AIネット の「効くレバー」と新メニュー案を内蔵。

## 安全
提案・分析・下書きまで。実行（価格/投稿/送信/仕入）は各承認後。secret/個人情報は出さない。
