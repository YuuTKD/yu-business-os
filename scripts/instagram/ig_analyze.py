#!/usr/bin/env python3
"""Instagram 投稿分析＋プロフィール監査レポート生成（オフライン・ルールベース）。

正規化済みデータ（profile + posts）を受け取り、次の4レポートを **提案ドラフト**として出す:
  1. 投稿分析     … エンゲージメント率・勝ち投稿・時間帯/曜日・ハッシュタグ・メディア種別
  2. プロフィール監査 … bio/リンク/名前検索最適化/投稿頻度/一貫性のチェックリスト＋改善案
  3. 競合比較     … 任意の競合サマリと頻度・エンゲージメントを比較
  4. 改善アクション案  … 分析から次の30日で試す投稿テーマ・頻度・CTA（投稿はしない）

外部送信・自動投稿・API 呼び出しは行わない（ネットワーク非依存の純粋関数群）。
LLM/OpenAI は不使用（ルールベース集計のみ）。

使用例:
  python3 scripts/instagram/ig_analyze.py --input data.json --report all
  python3 scripts/instagram/ig_analyze.py --sample --report audit
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from datetime import datetime

_THIS = os.path.abspath(__file__)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_THIS)))
SAMPLE_PATH = os.path.join(_REPO_ROOT, "tests", "instagram", "fixtures", "sample.json")

_WEEKDAYS_JA = ["月", "火", "水", "木", "金", "土", "日"]
_HASHTAG_RE = re.compile(r"#[^\s#　]+")

# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _num(v, default=0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _parse_ts(ts):
    """ISO8601 文字列を datetime へ。失敗時 None。'+0000' 形式も許容。"""
    if not ts:
        return None
    s = str(ts).strip().replace("Z", "+00:00")
    # '+0000' -> '+00:00'
    m = re.search(r"([+-])(\d{2})(\d{2})$", s)
    if m:
        s = s[: m.start()] + f"{m.group(1)}{m.group(2)}:{m.group(3)}"
    for cand in (s, s.split(".")[0]):
        try:
            return datetime.fromisoformat(cand)
        except ValueError:
            continue
    return None


def extract_hashtags(caption):
    return [h.lower() for h in _HASHTAG_RE.findall(caption or "")]


def post_engagement(post):
    """1投稿の総エンゲージメント（いいね＋コメント＋保存＋シェア）。"""
    return (_num(post.get("likes")) + _num(post.get("comments"))
            + _num(post.get("saves")) + _num(post.get("shares")))


def post_engagement_rate(post, followers):
    """エンゲージメント率。reach があれば reach 基準、無ければフォロワー基準。"""
    base = _num(post.get("reach")) or _num(post.get("impressions")) or _num(followers)
    if base <= 0:
        return 0.0
    return round(post_engagement(post) / base * 100, 2)


# ---------------------------------------------------------------------------
# 1. 投稿分析
# ---------------------------------------------------------------------------


def analyze_posts(data):
    profile = data.get("profile") or {}
    posts = data.get("posts") or []
    followers = _num(profile.get("followers"))

    enriched = []
    for p in posts:
        er = post_engagement_rate(p, followers)
        dt = _parse_ts(p.get("timestamp"))
        enriched.append({
            "id": p.get("id"),
            "caption": (p.get("caption") or "")[:60],
            "media_type": (p.get("media_type") or "UNKNOWN").upper(),
            "engagement": post_engagement(p),
            "engagement_rate": er,
            "hour": dt.hour if dt else None,
            "weekday": dt.weekday() if dt else None,
            "hashtags": extract_hashtags(p.get("caption")),
            "permalink": p.get("permalink"),
        })

    rates = [e["engagement_rate"] for e in enriched] or [0.0]
    avg_er = round(sum(rates) / len(rates), 2)
    top = sorted(enriched, key=lambda e: e["engagement_rate"], reverse=True)[:5]

    # 時間帯・曜日の平均エンゲージメント率
    def _avg_by(key, label_fn):
        buckets = {}
        for e in enriched:
            k = e[key]
            if k is None:
                continue
            buckets.setdefault(k, []).append(e["engagement_rate"])
        rows = [{"key": label_fn(k), "avg_er": round(sum(v) / len(v), 2), "n": len(v)}
                for k, v in buckets.items()]
        return sorted(rows, key=lambda r: r["avg_er"], reverse=True)

    by_hour = _avg_by("hour", lambda h: f"{int(h):02d}時")
    by_weekday = _avg_by("weekday", lambda w: _WEEKDAYS_JA[int(w)])

    # メディア種別
    media = {}
    for e in enriched:
        media.setdefault(e["media_type"], []).append(e["engagement_rate"])
    by_media = sorted(
        [{"key": k, "avg_er": round(sum(v) / len(v), 2), "n": len(v)}
         for k, v in media.items()],
        key=lambda r: r["avg_er"], reverse=True)

    # ハッシュタグ頻度（上位）
    tag_counter = Counter()
    for e in enriched:
        tag_counter.update(set(e["hashtags"]))
    top_tags = [{"tag": t, "count": c} for t, c in tag_counter.most_common(10)]

    return {
        "n_posts": len(posts),
        "avg_engagement_rate": avg_er,
        "top_posts": top,
        "by_hour": by_hour,
        "by_weekday": by_weekday,
        "by_media": by_media,
        "top_hashtags": top_tags,
    }


# ---------------------------------------------------------------------------
# 2. プロフィール監査
# ---------------------------------------------------------------------------


def _posts_per_week(posts):
    ts = sorted(t for t in (_parse_ts(p.get("timestamp")) for p in posts) if t)
    if len(ts) < 2:
        return None
    span_days = max((ts[-1] - ts[0]).days, 1)
    return round(len(ts) / (span_days / 7.0), 1)


def audit_profile(data):
    profile = data.get("profile") or {}
    posts = data.get("posts") or []
    bio = (profile.get("bio") or "").strip()
    name = (profile.get("name") or "").strip()
    website = (profile.get("website") or "").strip()
    ppw = _posts_per_week(posts)

    checks = []

    def add(key, ok, issue, fix):
        checks.append({"key": key, "ok": bool(ok), "issue": issue, "fix": fix})

    add("bio_present", len(bio) >= 20,
        "bio が短い/未設定で価値が伝わらない",
        "誰に・何を・どんな得か を1〜2行で。実店舗なら地域名も入れる")
    has_cta = any(w in bio for w in ("予約", "DM", "ご予約", "お問い合わせ", "↓", "こちら", "LINE"))
    add("bio_cta", has_cta,
        "bio に行動喚起(CTA)が無い",
        "「ご予約はプロフィールのリンクから」等の一言CTAを追加")
    add("link_present", bool(website),
        "プロフィールにリンクが無い",
        "予約/メニュー/GBP へのリンク（または集約リンク）を設定")
    add("name_searchable", any(kw in name for kw in
        ("料理", "居酒屋", "立ち飲み", "ケータリング", "サロン", "脱毛",
         "火鍋", "美容", "バー", "沖縄", "那覇")) or len(name) >= 4,
        "名前欄が検索キーワード最適化されていない",
        "名前欄に『店名｜地域＋業種』を入れて名前検索に強くする")
    add("posting_frequency", (ppw or 0) >= 3,
        f"投稿頻度が低い（週{ppw if ppw is not None else '?'}回）",
        "まず週3〜4回を目安に。勝ち投稿の再利用で頻度を担保")

    score = sum(1 for c in checks if c["ok"])
    return {
        "score": score,
        "max": len(checks),
        "posts_per_week": ppw,
        "checks": checks,
        "profile": {"followers": profile.get("followers"),
                    "username": profile.get("username"),
                    "name": name, "bio_len": len(bio), "website": bool(website)},
    }


# ---------------------------------------------------------------------------
# 3. 競合比較
# ---------------------------------------------------------------------------


def compare_competitors(data):
    profile = data.get("profile") or {}
    comps = data.get("competitors") or []
    me = {
        "username": profile.get("username") or "自社",
        "followers": _num(profile.get("followers")),
        "posts_per_week": _posts_per_week(data.get("posts") or []),
        "avg_engagement_rate": analyze_posts(data)["avg_engagement_rate"],
    }
    rows = [me]
    for c in comps:
        rows.append({
            "username": c.get("username") or "競合",
            "followers": _num(c.get("followers")),
            "posts_per_week": c.get("posts_per_week"),
            "avg_engagement_rate": _num(c.get("avg_engagement_rate")),
        })
    gaps = []
    if comps:
        best_ppw = max((_num(c.get("posts_per_week")) for c in comps), default=0)
        if (me["posts_per_week"] or 0) < best_ppw:
            gaps.append(f"投稿頻度が競合最高値(週{best_ppw:g})を下回る→頻度を上げる")
        best_er = max((_num(c.get("avg_engagement_rate")) for c in comps), default=0)
        if me["avg_engagement_rate"] < best_er:
            gaps.append(f"エンゲージメント率が競合最高値({best_er:g}%)未満→勝ち投稿型を増やす")
    return {"rows": rows, "gaps": gaps, "has_competitors": bool(comps)}


# ---------------------------------------------------------------------------
# 4. 改善アクション案
# ---------------------------------------------------------------------------


def action_plan(data):
    ap = analyze_posts(data)
    au = audit_profile(data)
    actions = []

    # プロフィールの未達項目 → アクション
    for c in au["checks"]:
        if not c["ok"]:
            actions.append(f"プロフィール改善：{c['fix']}")

    # 時間帯/曜日の勝ち筋
    if ap["by_hour"]:
        best_h = ap["by_hour"][0]
        actions.append(f"投稿時間：{best_h['key']}台のエンゲージメントが高い（n={best_h['n']}）→この時間帯を優先")
    if ap["by_weekday"]:
        best_w = ap["by_weekday"][0]
        actions.append(f"曜日：{best_w['key']}曜が好調→重要投稿はこの曜日に")
    if ap["by_media"]:
        best_m = ap["by_media"][0]
        actions.append(f"形式：{best_m['key']} が最も反応が高い→この形式を増やす")
    if ap["top_hashtags"]:
        tags = "・".join(t["tag"] for t in ap["top_hashtags"][:3])
        actions.append(f"ハッシュタグ：よく使う {tags} の効果を検証しつつ地域系タグを追加")

    themes = ["店主/スタッフのこだわり紹介", "人気メニューの調理・こだわり",
              "お客様の声・口コミ紹介（許可取得後）", "限定・季節の告知（予約導線つき）"]
    return {
        "actions": actions,
        "themes_30d": themes,
        "target_frequency": "週3〜4回（うち1回は勝ち投稿の再利用）",
        "cta": "各投稿末に「ご予約/お問い合わせはプロフィールのリンクから」",
    }


# ---------------------------------------------------------------------------
# Markdown 出力
# ---------------------------------------------------------------------------


def _table(headers, rows):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return out


def build_report(data, which="all"):
    profile = data.get("profile") or {}
    uname = profile.get("username") or "アカウント"
    lines = [
        "---", "type: instagram-report-draft", "status: draft",
        f"account: {uname}", "---", "",
        f"# Instagram レポート（案）— {uname}",
        "> これは**分析・提案ドラフト**です。投稿・送信・公開は行いません（承認後に人が実行）。",
        "",
    ]

    if which in ("all", "posts"):
        a = analyze_posts(data)
        lines += ["## 1. 投稿分析",
                  f"- 対象投稿数：{a['n_posts']} / 平均エンゲージメント率：**{a['avg_engagement_rate']}%**", ""]
        if a["top_posts"]:
            lines += ["### 勝ち投稿 TOP5"]
            lines += _table(["ER%", "形式", "キャプション"],
                            [[e["engagement_rate"], e["media_type"], e["caption"]]
                             for e in a["top_posts"]]) + [""]
        if a["by_hour"]:
            lines += ["### 時間帯別 ER（上位）"]
            lines += _table(["時間帯", "平均ER%", "件数"],
                            [[r["key"], r["avg_er"], r["n"]] for r in a["by_hour"][:5]]) + [""]
        if a["by_weekday"]:
            lines += ["### 曜日別 ER"]
            lines += _table(["曜日", "平均ER%", "件数"],
                            [[r["key"], r["avg_er"], r["n"]] for r in a["by_weekday"]]) + [""]
        if a["by_media"]:
            lines += ["### 形式別 ER"]
            lines += _table(["形式", "平均ER%", "件数"],
                            [[r["key"], r["avg_er"], r["n"]] for r in a["by_media"]]) + [""]
        if a["top_hashtags"]:
            lines += ["### よく使うハッシュタグ",
                      "・".join(f"{t['tag']}({t['count']})" for t in a["top_hashtags"]), ""]

    if which in ("all", "audit"):
        au = audit_profile(data)
        lines += ["## 2. プロフィール監査",
                  f"- スコア：**{au['score']}/{au['max']}** / 投稿頻度：週{au['posts_per_week']}回", ""]
        lines += _table(["項目", "判定", "改善案"],
                        [[c["key"], "✅" if c["ok"] else "⚠️",
                          "—" if c["ok"] else c["fix"]] for c in au["checks"]]) + [""]

    if which in ("all", "compare"):
        cm = compare_competitors(data)
        lines += ["## 3. 競合比較"]
        if cm["has_competitors"]:
            lines += _table(["アカウント", "フォロワー", "週間投稿", "平均ER%"],
                            [[r["username"], f"{r['followers']:g}",
                              r["posts_per_week"], r["avg_engagement_rate"]]
                             for r in cm["rows"]])
            lines += [""] + ([f"- ギャップ：{g}" for g in cm["gaps"]] or ["- 目立ったギャップなし"])
        else:
            lines += ["- 競合データ未指定（`competitors` を渡すと比較します）"]
        lines += [""]

    if which in ("all", "actions"):
        pl = action_plan(data)
        lines += ["## 4. 改善アクション案（次の30日）"]
        lines += [f"- {a}" for a in pl["actions"]]
        lines += ["", f"- 推奨頻度：{pl['target_frequency']}",
                  f"- 共通CTA：{pl['cta']}", "", "### 投稿テーマ案"]
        lines += [f"- {t}" for t in pl["themes_30d"]]
        lines += ["", "## 要判断（ゆうさん Yes/No）",
                  "- [ ] Yes / No：このアクション方針で進めてよいか",
                  "- [ ] Yes / No：まず着手するテーマはどれか",
                  "", "（提案です。投稿・送信・公開は承認後に人が実行）"]

    return "\n".join(lines)


def load_input(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Instagram 分析・監査レポート（提案のみ／送信なし）")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", help="正規化済み JSON（profile/posts[/competitors]）")
    src.add_argument("--sample", action="store_true", help="同梱サンプルで実行")
    ap.add_argument("--report", choices=["all", "posts", "audit", "compare", "actions"],
                    default="all")
    ap.add_argument("--json", action="store_true", help="分析結果を JSON で出力")
    ap.add_argument("--output", help="Markdown 保存先")
    args = ap.parse_args(argv)

    data = load_input(SAMPLE_PATH if args.sample else args.input)
    if args.json:
        result = {
            "posts": analyze_posts(data),
            "audit": audit_profile(data),
            "compare": compare_competitors(data),
            "actions": action_plan(data),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    md = build_report(data, args.report)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"レポート案を保存: {args.output}（提案・投稿/送信は承認後）")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
