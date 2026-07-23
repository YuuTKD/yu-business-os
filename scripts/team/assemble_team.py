#!/usr/bin/env python3
"""運営統括AI(ops) — 依頼を解析して運営チームを編成し、進行計画を出す。

依頼テキストからキーワードで必要な役割（商品開発/リサーチ/分析/集客/収益設計/顧客成功/営業）
を選び、標準フェーズ順に並べた編成表と進行計画を返す。価格変更・投稿・公開・送信は行わない
（提案・分析・下書きと役割割当まで）。

使用例:
  python3 scripts/team/assemble_team.py --instruction "TACHINOMIYAの新メニューとMEO"
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

try:
    import yaml as _yaml

    def _load_yaml(t):
        return _yaml.safe_load(t)
except Exception:  # pragma: no cover
    if _REPO_ROOT not in sys.path:
        sys.path.insert(0, _REPO_ROOT)
    from core.registry._yaml_min import safe_load as _load_yaml


def load_roles(path=ROLES_PATH):
    with open(path, encoding="utf-8") as fh:
        data = _load_yaml(fh.read())
    roles = {r["id"]: r for r in (data or {}).get("roles", [])}
    return data, roles


def lead_id(roles):
    """The root role (parent が空) をリードとする。"""
    for rid, r in roles.items():
        if not r.get("parent"):
            return rid
    return next(iter(roles))


def select_roles(instruction, roles, explicit=None):
    """Return the set of engaged role ids. リード（統括）は常に含む。

    explicit: 明示指定された role id のリスト（キーワードより優先）。
    キーワード該当なし → リード + research/analytics（まず調査・分析から）。
    """
    text = (instruction or "").lower()
    lead = lead_id(roles)
    engaged = {lead}
    if explicit:
        for e in explicit:
            if e in roles:
                engaged.add(e)
                p = roles[e].get("parent")
                if p:
                    engaged.add(p)
    for rid, r in roles.items():
        for kw in (r.get("keywords") or []):
            if kw.lower() in text:
                engaged.add(rid)
                p = r.get("parent")
                if p:
                    engaged.add(p)   # 子が動くなら統括も編成
                break
    if engaged == {lead}:
        engaged.update({rid for rid in ("research", "analytics") if rid in roles})
        return engaged, True
    return engaged, False


def build_plan(engaged, data, roles):
    order = (data or {}).get("phase_order", [])
    phases = []
    for rid in order:
        if rid in engaged and rid in roles:
            r = roles[rid]
            phases.append({"num": r["num"], "id": rid, "name": r["name_ja"],
                           "mission": r["mission"], "outputs": r.get("outputs", [])})
    return phases


def assemble(instruction, explicit=None, path=ROLES_PATH):
    data, roles = load_roles(path)
    lead = lead_id(roles)
    engaged, needs_hearing = select_roles(instruction, roles, explicit)
    phases = build_plan(engaged, data, roles)
    engaged_detail = sorted(
        ({"num": roles[i]["num"], "id": i, "name": roles[i]["name_ja"],
          "division": roles[i].get("division")} for i in engaged if i in roles),
        key=lambda x: x["num"])
    return {
        "lead": {"num": roles[lead]["num"], "id": lead, "name": roles[lead]["name_ja"]},
        "instruction": instruction,
        "engaged": engaged_detail,
        "phases": phases,
        "needs_hearing": needs_hearing,
        "guardrails": (data or {}).get("common_guardrails", []),
    }


def to_text(a):
    lines = [f"【運営統括AI 編成】依頼: {a['instruction']}",
             f"リード: ①{a['lead']['name']}", ""]
    lines.append("── 編成メンバー ──")
    for m in a["engaged"]:
        div = f"（{m['division']}）" if m.get("division") else "（統括）"
        lines.append(f"  {m['num']:>2} {m['name']}{div}")
    lines += ["", "── 進行計画（フェーズ順）──"]
    for i, p in enumerate(a["phases"], 1):
        lines.append(f"  {i}. {p['name']}：{p['mission']} → {'/'.join(p['outputs'])}")
    if a["needs_hearing"]:
        lines += ["", "※ 指示が抽象的なため、まず要件ヒアリングから開始します。"]
    lines += ["", "── 遵守事項 ──"] + [f"  - {g}" for g in a["guardrails"]]
    lines.append("")
    lines.append("（編成と計画です。実装・投稿・公開・送信は各承認後に行います）")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="運営統括AI チーム編成（提案・計画のみ）")
    ap.add_argument("--instruction", required=True)
    ap.add_argument("--role", action="append", default=[],
                    help="明示指定する role/division id（複数可）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    a = assemble(args.instruction, args.role)
    print(json.dumps(a, ensure_ascii=False, indent=2) if args.json else to_text(a))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
