# image-library-manager テストケース（6件）

## TC-01: 事故パターンの再現検知（GCS済み1枚のみ）
- **入力**: mode=shortage_check / planned_themes=["サーターアンダギー"] / 台帳にサーターアンダギー画像2枚（うちGCS済み1枚）、ラフテー画像1枚（GCS済み）
- **期待**: サーターアンダギー=不足判定 / blocked_themesに含める / gcs_pendingの優先度1に未GCS画像 / ラフテーがpostable候補に紛れ込まない
- **NG**: GCS済み1枚を「投稿可」とする（連続使用防止で即破綻するため最低3枚ルール適用）

## TC-02: 使えない理由の明記
- **入力**: mode=audit / http_status=404の画像1枚、caption_keywords空欄の画像1枚、許諾未確認の人物写真1枚を含む台帳
- **期待**: unusable_imagesの3枚すべてに個別の理由1行（"HTTP404" / "caption_keywords未設定" / "人物許諾未確認"）
- **NG**: 「メタデータ不備」等の一括りの理由

## TC-03: 連続使用防止の選定除外
- **入力**: mode=audit / 同一テーマの使える画像4枚、うち1枚が直近3投稿で使用済み
- **期待**: usable_imagesに4枚とも載るが、選定優先順はuse_count最小・last_used最古順で、直近使用画像に「直近3投稿使用・次回選定除外」の注記
- **NG**: 直近使用画像を次回投稿の第一候補にする

## TC-04: 撮影依頼文の生成品質
- **入力**: mode=photo_request / 泡盛テーマ在庫0枚 / business=TACHINOMIYA
- **期待**: photo_request_copyに「テーマ・枚数（5枚）・撮り方3点・提出先フォルダ・期限・担当（ゆうと）」がすべて入り、そのままLINE送信可能な文字数
- **NG**: 「泡盛の写真を撮ってください」だけの抽象依頼

## TC-05: 既存データ保全（禁止事項の遵守）
- **入力**: mode=audit / 台帳に明らかに不要そうな古い画像行（use_count=0・2年前登録）
- **期待**: 削除提案をしない。「アーカイブ候補（人間判断）」としてhuman_checkに回すのみ / 既存列の削除・URL改変の提案ゼロ
- **NG**: 行削除・列削除・URL修正を提案する

## TC-06: 事業横断の在庫マトリクス
- **入力**: mode=audit / business=all / TACHINOMIYA・Catering・Beautyの混在台帳
- **期待**: inventory_matrixが事業×テーマの2軸で出力され、事業ごとにpostable_themes/blocked_themesが分離 / Beautyの人物写真に許諾チェックが適用される
- **NG**: 事業をまたいだ画像流用の提案（Cateringの料理画像をTACHINOMIYA投稿に、等）を無条件に出す

## 合格基準
6件全件で、不足検知の閾値（5枚充足/3-4警告/2以下不足）・理由の個別明記・yes_no_questionの出力が守られること。
