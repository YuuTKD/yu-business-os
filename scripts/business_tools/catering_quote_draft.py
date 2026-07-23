#!/usr/bin/env python3
"""Trees Catering — 見積ドラフト生成ツール（送信はしない）。

問い合わせ内容（人数・予算・日程・イベント種別・スタイル）から、単価・小計・
オプション・合計と献立案を含む **見積ドラフト（Markdown）** を生成する。
外部送信・メール・LINE・投稿は一切行わない（人間が確認して送る）。

使用例:
  python3 scripts/business_tools/catering_quote_draft.py \
    --guests 20 --event パーティー --date 2026-08-10 --budget 40000

数値は概算ドラフト。最終価格・在庫・可否は人間が確認して確定する。
"""

from __future__ import annotations

import argparse
import datetime
import json

BASE_PER_PERSON = 1500          # 1人あたり基準（円・税別）
MIN_GUESTS = 10
TAX_RATE = 0.10

# 人数ボリューム割（多いほど単価を下げられる想定・ドラフト）
def per_person_price(guests: int, base: int = BASE_PER_PERSON) -> int:
    if guests >= 50:
        return base - 200
    if guests >= 30:
        return base - 100
    return base

# イベント種別ごとの献立案（案・確定ではない）
MENU_BY_EVENT = {
    "パーティー": ["フィンガーフード盛合せ", "ローストビーフ", "彩りサラダ",
                  "スイーツ4種", "ソフトドリンク"],
    "懇親会": ["オードブル盛合せ", "から揚げ", "生ハムとチーズ", "おにぎり/軽食"],
    "結婚式二次会": ["前菜ブッフェ", "メインの肉料理", "デザートビュッフェ",
                    "乾杯用スパークリング(手配可)"],
    "法人イベント": ["個包装フィンガーフード", "サンドイッチ", "サラダ", "ドリンク"],
    "記念日": ["特製オードブル", "メイン料理", "ホールケーキ(要相談)"],
    "オフィス": ["個包装デリ", "サラダボウル", "ドリンク"],
}
DEFAULT_MENU = ["フィンガーフード盛合せ", "サラダ", "スイーツ", "ドリンク"]

# 追加オプション（フラット・ドラフト）
OPTIONS = {
    "装飾": 8000,
    "運営スタッフ": 15000,
    "配送設営": 5000,
    "食器レンタル": 3000,
}


def build_quote(guests, event="パーティー", date=None, budget=None,
                per_person=None, options=None, style="フィンガーフード"):
    if guests is None or int(guests) < MIN_GUESTS:
        raise SystemExit(f"STOP: 人数は{MIN_GUESTS}名以上を想定（入力: {guests}）。")
    guests = int(guests)
    unit = int(per_person) if per_person else per_person_price(guests)
    subtotal = unit * guests
    options = options or []
    opt_lines, opt_total = [], 0
    for o in options:
        amt = OPTIONS.get(o)
        if amt is None:
            raise SystemExit(f"STOP: 未知のオプション '{o}'（{list(OPTIONS)}）。")
        opt_lines.append((o, amt))
        opt_total += amt
    net = subtotal + opt_total
    tax = round(net * TAX_RATE)
    total = net + tax
    within = None
    if budget:
        within = int(budget) >= total
    menu = MENU_BY_EVENT.get(event, DEFAULT_MENU)
    return {
        "guests": guests, "event": event, "date": date or "未定",
        "unit": unit, "subtotal": subtotal, "options": opt_lines,
        "option_total": opt_total, "net": net, "tax": tax, "total": total,
        "budget": int(budget) if budget else None, "within_budget": within,
        "menu": menu, "style": style,
    }


def to_markdown(q: dict) -> str:
    gen = datetime.datetime.now().astimezone().isoformat(timespec="minutes")
    lines = [
        "---", "type: catering-quote-draft", "status: draft",
        f"generated_at: {gen}", "---", "",
        "# 見積ドラフト（Trees Catering）",
        "> これは**ドラフト**です。価格・在庫・可否を確認のうえ、送信前に確定してください。", "",
        "## ご依頼概要",
        f"- 日程：{q['date']}", f"- イベント：{q['event']}",
        f"- 人数：{q['guests']}名", f"- スタイル：{q['style']}", "",
        "## お見積り（税別→税込）",
        f"- 単価：¥{q['unit']:,} × {q['guests']}名 = ¥{q['subtotal']:,}",
    ]
    if q["options"]:
        lines.append("- オプション：")
        for o, amt in q["options"]:
            lines.append(f"  - {o}：¥{amt:,}")
        lines.append(f"  - 小計：¥{q['option_total']:,}")
    lines += [
        f"- 小計（税別）：¥{q['net']:,}",
        f"- 消費税(10%)：¥{q['tax']:,}",
        f"- **合計（税込）：¥{q['total']:,}**",
    ]
    if q["budget"] is not None:
        judge = "予算内 ✅" if q["within_budget"] else "予算超過 ⚠️（内容調整をご提案）"
        lines.append(f"- ご予算：¥{q['budget']:,} → {judge}")
    lines += ["", "## 献立案（一例・ご要望で調整可）"]
    lines += [f"- {m}" for m in q["menu"]]
    lines += [
        "", "## 備考",
        "- 内容・人数・アレルギー対応はオリジナルで調整可能です。",
        "- 確定後、当日の設営・運営もご相談ください。", "",
        "## 送信前チェック（人間が確認）",
        "- [ ] 価格・オプションを確定した", "- [ ] 在庫・スタッフ手配を確認した",
        "- [ ] 日程・搬入時間を確認した", "- [ ] この内容で送付してよい",
        "",
    ]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Trees Catering 見積ドラフト生成（送信しない）")
    ap.add_argument("--guests", type=int, required=True)
    ap.add_argument("--event", default="パーティー")
    ap.add_argument("--date", default=None)
    ap.add_argument("--budget", type=int, default=None)
    ap.add_argument("--per-person", type=int, default=None)
    ap.add_argument("--style", default="フィンガーフード")
    ap.add_argument("--option", action="append", default=[],
                    help=f"追加オプション（{list(OPTIONS)}）・複数可")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--output", default=None, help="Markdown 保存先（省略時は標準出力）")
    args = ap.parse_args(argv)
    q = build_quote(args.guests, args.event, args.date, args.budget,
                    args.per_person, args.option, args.style)
    if args.json:
        print(json.dumps(q, ensure_ascii=False, indent=2))
        return 0
    md = to_markdown(q)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"見積ドラフトを保存: {args.output}（合計 ¥{q['total']:,}・送信は手動）")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
