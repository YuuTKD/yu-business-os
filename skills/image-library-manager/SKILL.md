---
name: image-library-manager
description: IMAGE_LIBRARY（投稿用画像台帳）を完全自動投稿に耐える状態に維持するSkill。画像の分類・GCS化状況・在庫・使用履歴の点検、撮影依頼文の生成に使う。「画像在庫」「IMAGE_LIBRARY」「GCS化」「画像が足りない」「テーマ分類」「撮影依頼」「投稿画像の点検」等の話題が出たら必ずこのSkillを使うこと。自動投稿の画像事故（本文と画像のテーマ不一致）を防ぐ運用の起点となる。
---

# image-library-manager（画像台帳・在庫管理Skill）

## 目的
IMAGE_LIBRARYを「どのテーマの投稿が来ても正しい画像が選ばれる」状態に保つ。
サーターアンダギー本文×ラフテー画像事故（原因：GCS化済み画像1枚のみ＋テーマ一致チェックなし）の再発を、**在庫側から**構造的に防ぐ。step13 theme_matchは投稿時の最終防衛線、本Skillは在庫の予防線という役割分担。

## 対象事業
TACHINOMIYA / TREE's Catering / Tree Beauty / 琉球火鍋（自動投稿対象になった時点で追加）

## 使う場面
- 週次の画像在庫点検（推奨：毎週月曜のKPIレビューと同時）
- 新規画像をIMAGE_LIBRARYに登録するとき（メタデータ付与）
- 自動投稿で「画像が見つからない」「theme_match FAIL」が出た直後
- 撮影依頼をスタッフ・外注に出すとき
- 新テーマの投稿を開始する前の在庫事前確認

## 入力スキーマ
```yaml
request:
  mode: audit | register | shortage_check | photo_request
  business: string | "all"
  image_library_data: string   # IMAGE_LIBRARYシートのエクスポート（CSV/表貼り付け）
  planned_themes: [string]|null  # 今後投稿予定のテーマ（shortage_check用）
  new_image_info: object|null    # register用（ファイル名・被写体・撮影日）
```

## 画像メタデータ標準（registerモードで必ず全項目付与）
| 列 | 必須 | 例 |
|---|---|---|
| category | ◯ | food / drink / interior / event / people / menu |
| image_theme | ◯ | サーターアンダギー / ラフテー / 泡盛 / 店内 / よもぎ蒸し |
| product_name | ◯（商品画像のみ） | 揚げたてサーターアンダギー |
| allowed_post_themes | ◯ | ["サーターアンダギー","スイーツ","揚げたて演出"] |
| blocked_post_themes | ◯ | ["ラフテー","肉料理"]（誤用リスクの高い隣接テーマ） |
| caption_keywords | ◯ | 本文照合用キーワード3〜8個 |
| visual_description | ◯ | 「揚げたてのサーターアンダギー3個、湯気、木皿、カウンター背景」 |
| gcs_public_url | ◯ | （URL。未設定なら空欄のまま=GCS化待ちリスト行き） |
| http_status | 自動 | 200以外は使用不可 |
| use_count / last_used | 自動 | 使用回数・最終使用日 |

## 判定ロジック
**使える画像の定義（AND条件・1つでも欠けたら「使えない画像」）**
1. gcs_public_url が設定済み
2. HTTP 200 が確認済み（点検時にURL疎通を確認）
3. image_theme / allowed_post_themes / caption_keywords がすべて非空
4. 人物写真の場合、掲載許諾フラグ=OK

**在庫充足の基準（テーマ×事業ごと）**
- 完全自動投稿対象テーマ：使える画像 **5枚以上** = 充足 / 3〜4枚 = 警告 / 2枚以下 = **不足（そのテーマの自動投稿は停止推奨）**
- 同一画像の連続使用防止：直近3投稿に使った画像は選定除外。use_count最小・last_used最古を優先

**GCS化の優先順位（撮影・圧縮も同基準）**
1. 投稿予定テーマ（planned_themes）で在庫2枚以下のもの
2. 過去に事故・FAILが出たテーマ
3. 高頻度投稿テーマ（use_count合計が多い順）
4. 圧縮対象：1枚あたり容量が基準超（目安1.5MB超）のもの

## 実行手順
1. image_library_dataを読み込み、標準メタデータ列の欠損を行単位で洗い出す
2. 使える/使えない判定 → 使えない理由を行ごとに1つずつ明記
3. 事業別×テーマ別の在庫マトリクスを作成（充足/警告/不足の3色判定）
4. GCS化待ち・圧縮対象・撮影必要リストを優先順位付きで出力
5. photo_requestモードでは、不足テーマからスタッフ向け撮影依頼文を生成（templates参照）
6. 末尾に「今週の画像アクション」をYes/No 1問で提示

## 出力スキーマ
```yaml
result:
  usable_images: [{id, image_theme, use_count, last_used}]
  unusable_images: [{id, 理由}]        # 理由は必ず1行で具体的に
  gcs_pending: [{id, 優先度, 理由}]
  compress_targets: [id]
  shoot_needed: [{theme, business, 必要枚数, 期限目安}]
  inventory_matrix: {事業: {テーマ: {枚数, 判定}}}
  postable_themes: [string]           # 今すぐ自動投稿してよいテーマ
  blocked_themes: [{theme, 理由}]      # 在庫不足で投稿停止すべきテーマ
  photo_request_copy: string|null     # スタッフ向け撮影依頼文
  yes_no_question: string
```

## 禁止事項
- 既存画像データ・既存列の削除（点検は読み取り+追記提案のみ）
- 画像URLの改変（gcs_public_urlは登録時の値をそのまま扱う）
- 人物写真の許諾未確認での使用可判定
- 未分類画像（メタデータ欠損）を商品名入り投稿の候補にすること
- 本文テーマと画像テーマがズレる可能性のあるマッチング（allowed_post_themes外は常に不可）
- 在庫不足テーマを「たぶん大丈夫」で投稿可にすること

## 人間確認が必要なポイント
- 人物写真の掲載許諾（スタッフ・お客様）
- blocked_post_themesの初期設定（隣接テーマの誤用リスク判断）
- 撮影依頼の期限と担当割り（ゆうと/美優/外注）
- 在庫不足テーマの投稿停止判断（売上導線に関わる場合）

## 成功条件
- theme_match FAILの発生がゼロで維持される（在庫側で先回りできている）
- 自動投稿対象テーマすべてが「使える画像5枚以上」を維持
- 撮影依頼→登録→GCS化がスタッフだけで回る

## 失敗条件
- 「画像を増やしましょう」等の抽象出力（枚数・テーマ・期限・担当が無い）
- 使えない理由が書かれていない画像リスト
- 在庫不足を検知しながらpostable_themesに含めてしまう

## 入力例
```yaml
request:
  mode: shortage_check
  business: TACHINOMIYA
  planned_themes: ["サーターアンダギー", "泡盛", "せんべろセット"]
  image_library_data: |
    id, image_theme, gcs_public_url, http_status, use_count, last_used
    001, ラフテー, https://storage.googleapis.com/.../rafute.jpg, 200, 12, 2026-07-01
    002, サーターアンダギー, (空欄), -, 0, -
    003, サーターアンダギー, https://storage.googleapis.com/.../sata1.jpg, 200, 3, 2026-06-28
```

## 出力例（要点）
```yaml
result:
  inventory_matrix:
    TACHINOMIYA:
      サーターアンダギー: {枚数: 1, 判定: 不足}   # 002はGCS未化のため除外
      泡盛: {枚数: 0, 判定: 不足}
      せんべろセット: {枚数: 0, 判定: 不足}
  gcs_pending:
    - {id: "002", 優先度: 1, 理由: "投稿予定テーマかつ在庫1枚。GCS化で即2枚に"}
  shoot_needed:
    - {theme: 泡盛, business: TACHINOMIYA, 必要枚数: 5, 期限目安: "7/11(土)まで"}
    - {theme: せんべろセット, business: TACHINOMIYA, 必要枚数: 5, 期限目安: "7/11(土)まで"}
  postable_themes: []
  blocked_themes:
    - {theme: サーターアンダギー, 理由: "使える画像1枚。連続使用防止ルールにより自動投稿不可（最低3枚必要）"}
  yes_no_question: "泡盛・せんべろの撮影依頼をゆうとに今日出しますか？ Yes/No"
```

## テストケース
`tests/test_cases.md` に6ケース。

## テンプレート
- `templates/photo_request.md` — スタッフ向け撮影依頼文（被写体・構図・枚数指定）
- `templates/register_checklist.md` — 新規画像登録チェックリスト

## 再利用先
- sns-post-quality-check（おすすめ画像カテゴリの在庫裏付け）
- scheduler-readiness-check（判定項目「画像在庫」のデータ供給元）
- sop-writer（撮影依頼SOPへの変換）
- Beauty・火鍋の自動投稿開始時の在庫立ち上げ手順として横展開

## 将来の改善余地
- GCS疎通チェック（HTTP200確認）の定期スクリプト化（Cloud Run外・読み取り専用で）
- 画像→visual_description の自動生成（Vision API）
- 投稿実績×画像別エンゲージメントの突合で「勝ち画像」を優先配信

## 判断軸への寄与
稼働ゼロ（撮影依頼の自動生成）／事故防止（テーマ不一致の予防線）／売却価値（画像資産の台帳整備＝引き継ぎ可能な運用資産）
