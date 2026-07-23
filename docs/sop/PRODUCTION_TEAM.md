# 制作・運営チーム（20役割）— 使い方

制作/集客/コンテンツ/商談の依頼を、制作統括AI(pm)が編成して進める仕組み。
すべて**下書き・設計・チェックまで**。送信/投稿/公開/デプロイ/決済は人間承認後のみ。

## 起動
Claude に「LP作って」「集客を強化して」等 → Skill `production-pm` が起動。
または:
```
python3 scripts/team/assemble_team.py --instruction "BeautyのLP作って。SEOとコピーと見積も"
```
→ 編成メンバー・フェーズ計画・遵守事項を出力。

## 構成（SSOT: configs/team/roles.yaml）
①pm ／ ②営業(③見積 ④要件定義) ／ ⑤市場(⑥SEO/MEO ⑦ブランド) ／
⑧UX(⑨導線 ⑩コピー ⑪ビジュアル ⑫画像素材 ⑬モーション) ／
⑭開発(⑮CMS) ／ ⑱公開(⑯技術品質 ⑰法令) ／ ⑲分析(⑳納品後支援)

## 既存ツール連携
見積=catering_quote_draft / コピー=sns-post-quality-check / 画像=image-library-manager /
品質・公開=pre-deploy-qa / 納品後=gbp_review_reply_draft・catering_post_event_followup。

## 安全
指示解析→編成→計画まで自動。実装/投稿/公開/送信は各承認後。secret/個人情報は出力しない。
