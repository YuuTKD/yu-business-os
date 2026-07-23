#!/usr/bin/env python3
"""Google Business Profile 口コミ返信ドラフト生成（投稿はしない・全事業共通）。

★評価と本文から、評価に応じた**返信文の下書き**を生成する。GBP API 投稿・外部
送信は一切しない（人間が確認して GBP 管理画面から投稿する）。口コミ本文の個人情報
は返信文へ転記しない（一般的な文面＋改善姿勢）。低評価は謝意・真摯・オフライン誘導。

使用例:
  python3 scripts/business_tools/gbp_review_reply_draft.py \
    --business "Tree Beauty" --rating 2 --text "予約時間に案内されず待たされた"
"""

from __future__ import annotations

import argparse
import json
import re

# 本文キーワード → 触れる話題（本文に該当があるときだけ言及・捏造しない）
_TOPIC = {
    "接客・スタッフ": r"接客|スタッフ|店員|対応|丁寧|愛想",
    "料理・味": r"美味し|おいし|料理|味|メニュー|ドリンク",
    "雰囲気・空間": r"雰囲気|居心地|清潔|きれい|綺麗|内装|空間",
    "価格": r"価格|値段|コスパ|高い|安い",
    "待ち時間・予約": r"待|予約|時間|案内",
}
# 個人情報は返信に出さない（マスク検出用）
_PII = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
                  r"|(?<!\d)0\d{1,4}-?\d{1,4}-?\d{3,4}(?!\d)")


def _topics(text):
    return [name for name, pat in _TOPIC.items() if re.search(pat, text or "")]


def build_reply(business, rating, text="", contact_hint="店舗までお電話"):
    if rating is None or not (1 <= int(rating) <= 5):
        raise SystemExit("STOP: 評価は 1〜5 で指定してください。")
    rating = int(rating)
    topics = _topics(text)
    biz = (business or "当店").strip() or "当店"

    if rating >= 4:
        body = (f"この度は{biz}をご利用いただき、また嬉しいお言葉を賜り"
                "誠にありがとうございます。")
        if topics:
            body += f"「{topics[0]}」についてお褒めいただき大変励みになります。"
        body += "これからも皆さまにご満足いただけるよう努めてまいります。またのご来店を心よりお待ちしております。"
    elif rating == 3:
        body = (f"この度は{biz}へご来店・ご評価いただきありがとうございます。"
                "いただいたご意見は真摯に受け止め、より良いサービスへ改善してまいります。")
        if topics:
            body += f"特に「{topics[0]}」の点、今後の参考にさせていただきます。"
        body += "またお越しいただけますと幸いです。"
    else:  # 1-2★
        body = (f"この度は{biz}にてご期待に沿えず、誠に申し訳ございませんでした。"
                "貴重なご意見として重く受け止めております。")
        if topics:
            body += f"「{topics[0]}」につきまして、早急に社内で確認し改善に努めます。"
        body += (f"差し支えなければ{contact_hint}にてご連絡いただけますと、"
                 "直接お詫びとお話を伺い、改善につなげたく存じます。")

    # 返信本文に個人情報が混入しないことを保証（テンプレなので通常混入しないが二重防御）
    body = _PII.sub("", body)
    return {"business": biz, "rating": rating, "topics": topics, "reply": body}


def to_output(r):
    star = "★" * r["rating"] + "☆" * (5 - r["rating"])
    return "\n".join([
        f"【GBP返信ドラフト】{r['business']}  評価 {star}（{r['rating']}）",
        f"検出トピック: {', '.join(r['topics']) or 'なし（一般文面）'}",
        "",
        "── 返信文（案）──",
        r["reply"],
        "",
        "投稿前チェック（人間が確認）",
        "- [ ] 事実誤認がない / 個人情報を含まない",
        "- [ ] 店舗トーンに合っている",
        "- [ ] この内容で GBP から投稿してよい",
        "",
        "（↑ ドラフトです。自動投稿はしません。GBP 管理画面から手動で投稿してください）",
    ])


def main(argv=None):
    ap = argparse.ArgumentParser(description="GBP 口コミ返信ドラフト（投稿しない）")
    ap.add_argument("--business", required=True)
    ap.add_argument("--rating", type=int, required=True)
    ap.add_argument("--text", default="")
    ap.add_argument("--contact-hint", default="店舗までお電話")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    r = build_reply(args.business, args.rating, args.text, args.contact_hint)
    print(json.dumps(r, ensure_ascii=False, indent=2) if args.json else to_output(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
