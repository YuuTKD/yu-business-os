#!/usr/bin/env python3
"""制作統括AI(pm) — 指示を解析してチームを編成し、進行計画を出す。

指示テキストからキーワードで必要な役割を選び、標準フェーズ順に並べた編成表と
進行計画を返す。実装・投稿・公開・送信は行わない（計画と役割割当まで）。

使用例:
  python3 scripts/team/assemble_team.py --instruction "BeautyのLP作って。SEOと見積も"
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


def select_roles(instruction, roles, explicit=None):
    """Return the set of engaged role ids. PM(①) is always the lead.

    explicit: 明示指定された division/role id のリスト（キーワードより優先）。
    キーワード該当なし → PM + requirements のみ（要ヒアリング）。
    """
    text = (instruction or "").lower()
    engaged = {"pm"}
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
    # 何も当たらなければ最小編成（PM + 要件定義）で必ずヒアリングから
    if engaged == {"pm"}:
        engaged.update({"sales", "requirements"})
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
    engaged, needs_hearing = select_roles(instruction, roles, explicit)
    phases = build_plan(engaged, data, roles)
    engaged_detail = sorted(
        ({"num": roles[i]["num"], "id": i, "name": roles[i]["name_ja"],
          "division": roles[i].get("division")} for i in engaged if i in roles),
        key=lambda x: x["num"])
    return {
        "lead": {"num": 1, "id": "pm", "name": roles["pm"]["name_ja"]},
        "instruction": instruction,
        "engaged": engaged_detail,
        "phases": phases,
        "needs_hearing": needs_hearing,
        "guardrails": (data or {}).get("common_guardrails", []),
    }


def to_text(a):
    lines = [f"【制作統括AI 編成】指示: {a['instruction']}",
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
    ap = argparse.ArgumentParser(description="制作統括AI チーム編成（計画のみ）")
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
