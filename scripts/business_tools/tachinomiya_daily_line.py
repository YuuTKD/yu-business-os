#!/usr/bin/env python3
"""TACHINOMIYA — 日次売上「一言LINE」通知文の生成（送信はしない）。

その日の昼/夜売上を入れると、日次目標比・合計・前年比を1通のLINEメッセージ文
（テキスト）にして出力する。**LINE API 送信・投稿・外部通信は一切しない**。
生成したテキストを人間が確認して LINE へ貼る（誤送信ゼロ設計）。

月次目標（既定）: 昼 250万 / 夜 300万（合計 550万）。日次目標は月次÷営業日数。

使用例:
  python3 scripts/business_tools/tachinomiya_daily_line.py \
    --lunch 98000 --dinner 88000 --date 2026-07-23 --last-year 177000
"""

from __future__ import annotations

import argparse
import datetime
import json

MONTHLY_LUNCH = 2_500_000
MONTHLY_DINNER = 3_000_000
OPERATING_DAYS = 26   # 月あたり営業日（既定）


def _pct(actual, target):
    return round(actual / target * 100) if target else 0


def build_report(lunch, dinner, date=None,
                 monthly_lunch=MONTHLY_LUNCH, monthly_dinner=MONTHLY_DINNER,
                 operating_days=OPERATING_DAYS, last_year=None):
    if lunch is None or dinner is None or int(lunch) < 0 or int(dinner) < 0:
        raise SystemExit("STOP: 昼・夜の売上（0以上）を入力してください。")
    lunch, dinner = int(lunch), int(dinner)
    if operating_days <= 0:
        raise SystemExit("STOP: 営業日数は1以上。")
    dt_lunch = round(monthly_lunch / operating_days)
    dt_dinner = round(monthly_dinner / operating_days)
    total = lunch + dinner
    dt_total = dt_lunch + dt_dinner
    yoy = None
    if last_year:
        ly = int(last_year)
        yoy = {"amount": ly, "pct": _pct(total, ly) if ly else 0,
               "diff": total - ly}
    return {
        "date": date or datetime.date.today().strftime("%Y-%m-%d"),
        "lunch": lunch, "dinner": dinner, "total": total,
        "dt_lunch": dt_lunch, "dt_dinner": dt_dinner, "dt_total": dt_total,
        "pct_lunch": _pct(lunch, dt_lunch), "pct_dinner": _pct(dinner, dt_dinner),
        "pct_total": _pct(total, dt_total), "yoy": yoy,
    }


def _mark(pct):
    return "✅" if pct >= 100 else ("➖" if pct >= 90 else "⚠️")


def _one_liner(r):
    # データから機械的に導く（原因は推測しない）
    if r["pct_total"] >= 100:
        return "目標達成。良い流れ、継続を。"
    lags = []
    if r["pct_lunch"] < 100:
        lags.append("昼")
    if r["pct_dinner"] < 100:
        lags.append("夜")
    who = "・".join(lags) if lags else "全体"
    return f"{who}が目標未達。明日の集客施策を検討。"


def to_line_text(r):
    md = f"{int(r['date'][5:7])}/{int(r['date'][8:10])}"  # 07-23 → 7/23
    lines = [
        f"【立ち飲み {md} 売上】",
        f"昼 ¥{r['lunch']:,} / 目標 ¥{r['dt_lunch']:,}（{r['pct_lunch']}%）{_mark(r['pct_lunch'])}",
        f"夜 ¥{r['dinner']:,} / 目標 ¥{r['dt_dinner']:,}（{r['pct_dinner']}%）{_mark(r['pct_dinner'])}",
        f"合計 ¥{r['total']:,}（対目標 {r['pct_total']}%）{_mark(r['pct_total'])}",
    ]
    if r["yoy"]:
        sign = "+" if r["yoy"]["diff"] >= 0 else ""
        lines.append(f"前年比 {r['yoy']['pct']}%（{sign}¥{r['yoy']['diff']:,}）")
    lines.append(f"一言: {_one_liner(r)}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="TACHINOMIYA 日次売上→一言LINE文（送信しない）")
    ap.add_argument("--lunch", type=int, required=True)
    ap.add_argument("--dinner", type=int, required=True)
    ap.add_argument("--date", default=None)
    ap.add_argument("--last-year", type=int, default=None)
    ap.add_argument("--operating-days", type=int, default=OPERATING_DAYS)
    ap.add_argument("--monthly-lunch", type=int, default=MONTHLY_LUNCH)
    ap.add_argument("--monthly-dinner", type=int, default=MONTHLY_DINNER)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    r = build_report(args.lunch, args.dinner, args.date, args.monthly_lunch,
                     args.monthly_dinner, args.operating_days, args.last_year)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0
    print(to_line_text(r))
    print("\n（↑ このテキストを確認して LINE へ貼り付け。自動送信はしません）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
