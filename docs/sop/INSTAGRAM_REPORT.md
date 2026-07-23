# Instagram 分析・監査レポート — 使い方

Windsor AI 等から取得した Instagram データで、投稿分析・プロフィール監査・競合比較・
改善アクション案を **提案ドラフト**として出す。投稿/送信/公開はしない（承認後に人が実行）。

## 手順
1. データ取得（Windsor AI）— 鍵は環境変数のみ、既定はオフライン:
   `python3 scripts/instagram/windsor_source.py --raw raw.json --out normalized.json`
   ライブ取得は owner が鍵を設定して: `WINDSOR_API_KEY=*** ... --live`
2. レポート生成:
   `python3 scripts/instagram/ig_analyze.py --input normalized.json --report all`
   まず試す: `python3 scripts/instagram/ig_analyze.py --sample`

## 出力レポート
1. 投稿分析: 平均ER・勝ち投稿TOP5・時間帯/曜日/形式別ER・ハッシュタグ
2. プロフィール監査: bio/CTA/リンク/名前検索最適化/投稿頻度の5点チェック＋改善案
3. 競合比較: フォロワー・週間投稿・平均ER の比較とギャップ
4. 改善アクション案: 次の30日のテーマ・頻度・CTA（投稿はしない）

## 安全
ルールベース集計（OpenAI不使用）。APIキーは環境変数のみでコードに書かない。
自動投稿/DM/送信/公開なし。数値の捏造なし（データ無しは出さない）。
