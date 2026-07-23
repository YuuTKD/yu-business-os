#!/usr/bin/env python3
"""Trees Catering — イベント後フォロー文の下書き生成（送信はしない）。

実施したイベント情報から、翌日送る「お礼＋クチコミ依頼＋次回提案」の**下書き**
（Markdown）を生成する。メール・LINE・DM 送信、GBP 投稿、外部通信は一切しない。
生成文を人間が確認して送る（誤送信ゼロ設計）。個人情報は本文に転記しない。

使用例:
  python3 scripts/business_tools/catering_post_event_followup.py \
    --event "会社懇親会" --date 2026-08-10 --guests 25 --contact-name 田中
"""

from __future__ import annotations

import argparse
import datetime
import json
import re

_PII = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
                  r"|(?<!\d)0\d{1,4}-?\d{1,4}-?\d{3,4}(?!\d)")

# 次回提案の定番（イベント種別に応じた案・確定ではない）
NEXT_BY_EVENT = {
    "懇親会": "四半期ごとの定例懇親プラン（幹事の手間を減らす一括手配）",
    "会社懇親会": "四半期ごとの定例懇親プラン（幹事の手間を減らす一括手配）",
    "パーティー": "季節メニューを変えた次回パーティープラン",
    "結婚式二次会": "記念日・周年イベント向けのアニバーサリープラン",
    "法人イベント": "社内イベント年間パッケージ（複数回割）",
    "記念日": "次の記念日・お祝い向けの特別プラン",
    "オフィス": "定期デリバリー（週次・月次のオフィスケータリング）",
}
DEFAULT_NEXT = "ご要望に合わせた次回オリジナルプラン"


def _honor(name):
    n = (name or "").strip()
    n = _PII.sub("", n)             # 念のため PII を除去
    return f"{n}様" if n else "ご担当者様"


def build_followup(event, date=None, guests=None, contact_name="",
                   business="Trees Catering", review_url_placeholder="[GoogleクチコミURL]",
                   next_suggestion=None):
    ev = (event or "イベント").strip() or "イベント"
    honor = _honor(contact_name)
    nxt = next_suggestion or NEXT_BY_EVENT.get(ev, DEFAULT_NEXT)
    g = f"{int(guests)}名" if guests else "多数"
    send_on = None
    if date:
        try:
            d = datetime.date.fromisoformat(date)
            send_on = (d + datetime.timedelta(days=1)).isoformat()
        except ValueError:
            send_on = None

    thanks = (f"{honor}\n\nこの度は{ev}（{g}）に{business}をご利用いただき、"
              "誠にありがとうございました。皆さまに楽しくお過ごしいただけていましたら幸いです。")
    review = ("もし当日の料理やサービスにご満足いただけましたら、"
              f"よろしければGoogleでのご感想をお寄せいただけますと励みになります。\n{review_url_placeholder}")
    proposal = (f"次回は「{nxt}」もご用意できます。ご予定が決まりましたら、"
                "人数・ご予算に合わせてお見積りをお出しします。お気軽にご連絡ください。")

    return {
        "business": business, "event": ev, "guests": g, "date": date or "未記録",
        "send_on": send_on or "実施翌日", "next_suggestion": nxt,
        "thanks": thanks, "review": review, "proposal": proposal,
    }


def to_markdown(f):
    gen = datetime.datetime.now().astimezone().isoformat(timespec="minutes")
    return "\n".join([
        "---", "type: catering-post-event-followup", "status: draft",
        f"generated_at: {gen}", "---", "",
        f"# イベント後フォロー下書き（{f['business']}）",
        f"- 対象イベント：{f['event']}（{f['guests']}）／実施日 {f['date']}",
        f"- 推奨送信日：**{f['send_on']}**（実施翌日）", "",
        "## ① お礼メッセージ（案）", "", f["thanks"], "",
        "## ② クチコミ依頼（案・任意）", "", f["review"], "",
        "## ③ 次回提案（案）", "", f["proposal"], "",
        "## 送信前チェック（人間が確認）",
        "- [ ] 宛名・敬称が正しい / 個人情報の誤りがない",
        "- [ ] クチコミURLを実際のものに差し替えた",
        "- [ ] 送信手段（メール/LINE等）と文面を確認した",
        "- [ ] この内容で送付してよい",
        "",
        "（↑ 下書きです。自動送信・自動投稿はしません）",
    ])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Catering イベント後フォロー下書き（送信しない）")
    ap.add_argument("--event", required=True)
    ap.add_argument("--date", default=None)
    ap.add_argument("--guests", type=int, default=None)
    ap.add_argument("--contact-name", default="")
    ap.add_argument("--business", default="Trees Catering")
    ap.add_argument("--next", dest="next_suggestion", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--output", default=None)
    args = ap.parse_args(argv)
    f = build_followup(args.event, args.date, args.guests, args.contact_name,
                       args.business, next_suggestion=args.next_suggestion)
    if args.json:
        print(json.dumps(f, ensure_ascii=False, indent=2))
        return 0
    md = to_markdown(f)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"フォロー下書きを保存: {args.output}（推奨送信日 {f['send_on']}・送信は手動）")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
