---
name: instagram-report
description: Instagramの投稿分析・プロフィール監査・競合比較・改善アクション案のレポートを作りたいときに起動する。Windsor AI等から取得したデータ（正規化JSON）を渡すと、送信・投稿はせずMarkdownの提案ドラフトを出す。ルールベース集計でOpenAI不使用。投稿/送信/公開は人間承認後のみ。
---

# instagram-report（Instagram 分析・監査レポート）

## 役割
Instagram の投稿データとプロフィールから、①投稿分析 ②プロフィール監査 ③競合比較
④改善アクション案 を **Markdownの提案ドラフト**として出す。投稿・送信・公開はしない。

## データ取得（Windsor AI）
Windsor AI から取得した生JSONを正規化する。**鍵は環境変数 WINDSOR_API_KEY のみ**（コードに書かない）。
- オフライン: `python3 scripts/instagram/windsor_source.py --raw raw.json --out normalized.json`
- ライブ取得(鍵と承認が要る/owner実行): `WINDSOR_API_KEY=*** python3 scripts/instagram/windsor_source.py --live --out normalized.json`

## レポート生成
```
python3 scripts/instagram/ig_analyze.py --input normalized.json --report all
python3 scripts/instagram/ig_analyze.py --sample --report audit   # 同梱サンプルで試す
```
`--report` は all / posts / audit / compare / actions。`--output` で保存、`--json` で生データ。

## 正規化データ形式
```
{ "profile": {username,name,bio,followers,website,...},
  "posts": [ {id,timestamp,media_type,caption,likes,comments,saves,shares,reach,...} ],
  "competitors": [ {username,followers,posts_per_week,avg_engagement_rate} ] }
```

## 禁止
自動投稿・DM・送信・公開（**人間承認後のみ**）。APIキーの直書き・出力。OpenAI等の有料LLM利用。
数値の捏造（データが無い項目は出さない/「未確認」）。
