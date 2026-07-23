#!/usr/bin/env python3
"""運営統括AI — 各事業の「利益を伸ばす」成長プラン案を生成する（実行はしない）。

事業名を渡すと、事業タイプに応じた 新メニュー案・リサーチ観点・分析KPI・集客施策・
価格/粗利改善・リピート/失客復活・30日アクション を **提案ドラフト**として出す。
価格変更/仕入変更/投稿/送信/公開は行わない（人間が承認して実行）。

使用例:
  python3 scripts/team/growth_plan.py --business TACHINOMIYA
  python3 scripts/team/growth_plan.py --business "Tree Beauty" --focus 集客
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

_THIS = os.path.abspath(__file__)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_THIS)))
ROLES_PATH = os.path.join(_REPO_ROOT, "configs", "team", "roles.yaml")

if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from scripts.team.assemble_team import load_roles, assemble  # noqa: E402


def detect_type(business, data):
    # 部分一致（substring）で判定。正規表現は使わない（入力起因のエラーを避ける）。
    text = (business or "").lower()
    for tid, spec in (data.get("business_types") or {}).items():
        for m in (spec.get("match") or []):
            if m.lower() in text:
                return tid, spec
    return "unknown", {"label": "未分類", "menu_ideas": [], "levers": []}


# 事業横断で共通の分析KPI・集客・リピートの雛形
COMMON_KPIS = ["客単価", "客数/来店数", "原価率・粗利率", "曜日・時間帯別売上",
               "リピート率", "新規/既存の比率"]
COMMON_MARKETING = ["GBP(Googleマップ)の情報最適化＋口コミ獲得（MEO）",
                    "勝ち投稿の再利用でSNS頻度を担保（承認して投稿）",
                    "既存客への一言告知（LINE等・下書きを承認して送信）"]
COMMON_RETENTION = ["初回→2回目の再来導線（次回特典・予約）",
                    "休眠客への復活オファー下書き（承認して送信）",
                    "満足客に口コミ・紹介を依頼"]


def build_growth_plan(business, data, focus=None):
    if not business or not business.strip():
        raise SystemExit("STOP: --business を指定してください。")
    tid, spec = detect_type(business, data)
    team = assemble(f"{business} の売上・利益を伸ばす {focus or ''}".strip(), path=ROLES_PATH)
    plan = {
        "business": business.strip(), "type": tid, "type_label": spec["label"],
        "levers": spec.get("levers", []),
        "menu_ideas": spec.get("menu_ideas", []),
        "research_points": ["近隣・同業の価格帯と人気メニュー", "客層と来店動機",
                            "満たせていないニーズ（口コミ/要望から）"],
        "kpis": COMMON_KPIS,
        "marketing": COMMON_MARKETING,
        "pricing": ["原価率の高い商品の見直し／セット化で粗利改善",
                    "高粗利商品の訴求強化・アップセル導線"],
        "retention": COMMON_RETENTION,
        "team": [m["name"] for m in team["engaged"]],
        "focus": focus,
    }
    return plan


def to_markdown(p):
    lines = [
        "---", "type: growth-plan-draft", "status: draft",
        f"business: {p['business']}", "---", "",
        f"# {p['business']} 利益成長プラン（案）",
        f"- 事業タイプ：{p['type_label']}",
        f"- 効くレバー：{('・'.join(p['levers']) or '未確認')}",
        f"- 編成：{'／'.join(p['team'])}",
    ]
    if p["focus"]:
        lines.append(f"- 重点：{p['focus']}")
    lines += [
        "", "> これは**提案ドラフト**です。価格変更・仕入・投稿・送信・公開は承認後に実行してください。", "",
        "## 1. 新メニュー・商品の案",
    ]
    lines += ([f"- {m}" for m in p["menu_ideas"]] or ["- 未確認（事業タイプ要確認）"])
    lines += ["", "## 2. リサーチ観点（何を調べるか）"] + [f"- {r}" for r in p["research_points"]]
    lines += ["", "## 3. 見るべきKPI（分析）"] + [f"- {k}" for k in p["kpis"]]
    lines += ["", "## 4. 集客施策"] + [f"- {m}" for m in p["marketing"]]
    lines += ["", "## 5. 価格・粗利改善"] + [f"- {x}" for x in p["pricing"]]
    lines += ["", "## 6. リピート・失客復活"] + [f"- {r}" for r in p["retention"]]
    lines += [
        "", "## 7. まず30日でやること（案）",
        "1. KPIの現状値を1回集計（客単価・原価率・リピート率）",
        "2. 新メニュー案から1つ試作→反応を見る",
        "3. MEO最適化＋口コミ依頼を開始（投稿は承認）",
        "",
        "## 要判断（ゆうさん Yes/No）",
        "- [ ] Yes / No：この方向で進めてよいか",
        "- [ ] Yes / No：まず着手する打ち手はどれか（番号）",
        "",
        "（提案です。実行=価格変更/投稿/送信/仕入は承認後）",
    ]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="各事業の利益成長プラン案（実行しない）")
    ap.add_argument("--business", required=True)
    ap.add_argument("--focus", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--output", default=None)
    args = ap.parse_args(argv)
    data, _roles = load_roles(ROLES_PATH)
    p = build_growth_plan(args.business, data, args.focus)
    if args.json:
        print(json.dumps(p, ensure_ascii=False, indent=2))
        return 0
    md = to_markdown(p)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"成長プラン案を保存: {args.output}（提案・実行は承認後）")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
