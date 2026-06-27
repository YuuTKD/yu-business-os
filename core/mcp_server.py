"""
YU HOLDINGS AI — Read-Only MCP Server (Phase 1)
------------------------------------------------
Claudeカスタムコネクタ用のリモートMCPサーバー。
Streamable HTTP（JSON-RPC 2.0 over HTTP POST）を Flask にネイティブ実装。

方針:
  ・Phase 1 は READ-ONLY 限定。write系tool・更新・送信は一切作らない。
  ・既存RESTを薄くラップして8 toolsのみ公開。
  ・秘密情報（トークン・APIキー・環境変数の値）は絶対に返さない。
  ・MCPライブラリ非依存（WSGI/Flask互換・攻撃面最小化のため自前実装）。

対応メソッド: initialize / notifications/initialized / ping / tools/list / tools/call
"""

import os
import traceback

PROTOCOL_VERSION_DEFAULT = "2025-06-18"
SERVER_NAME = "YU HOLDINGS AI"
SERVER_VERSION = "1.0.0"

# ── 公開する8 tools（すべて read-only・引数なし） ─────────
_NO_ARGS = {"type": "object", "properties": {}, "additionalProperties": False}

TOOLS = [
    {"name": "get_system_health",
     "description": "System Health Monitorの最新状態（Cloud Run/Scheduler/Sheets接続/直近エラー/危険度/最終チェック日時）を返す。読み取り専用。",
     "inputSchema": _NO_ARGS},
    {"name": "get_cash_flow_status",
     "description": "Cash Flow Survival OSの資金繰り状況（現金残高・7日入金/支払予定・不足見込み・危険度・今日のアクション）を返す。読み取り専用。",
     "inputSchema": _NO_ARGS},
    {"name": "get_profit_leak_status",
     "description": "Profit Leak Detectorの利益漏れ状況（事業別粗利率・危険事業・利益漏れ・改善アクション・危険度）を返す。読み取り専用。",
     "inputSchema": _NO_ARGS},
    {"name": "get_lead_status",
     "description": "Lead Command Centerのリード状況（S/Aリード数・未対応数・推定売上合計・事業別概要）を返す。読み取り専用。",
     "inputSchema": _NO_ARGS},
    {"name": "get_catering_sales_status",
     "description": "Catering B2B Sales Autopilotの営業状況（営業先数・本日DM対象・返信/商談/見積/成約・推定売上・未対応）を返す。読み取り専用。",
     "inputSchema": _NO_ARGS},
    {"name": "get_daily_action_status",
     "description": "Daily Action Commanderの本日タスク状況（事業別タスク数・完了/未完了・完了率・S未完了）を返す。読み取り専用。",
     "inputSchema": _NO_ARGS},
    {"name": "get_knowledge_status",
     "description": "Knowledge OSの同期/Markdown保存状況（GCS保存件数・最新Markdown・同期状況）を返す。読み取り専用。",
     "inputSchema": _NO_ARGS},
    {"name": "get_owner_briefing",
     "description": "上記を統合したオーナー向け5行サマリー（今日一番危険なこと/売上につながること/未対応/資金繰り注意/Yes-No判断）を返す。読み取り専用。",
     "inputSchema": _NO_ARGS},
]

TOOL_NAMES = {t["name"] for t in TOOLS}


# ── 機密マスキング（保険） ────────────────────────────────
def _scrub(text: str) -> str:
    """万一に備え、秘密情報らしき文字列をマスク（read-only出力の最終防衛）"""
    import re
    if not text:
        return text
    # 長いトークン様の文字列をマスク（base64/JWT風 40文字以上）
    text = re.sub(r"[A-Za-z0-9_\-]{40,}\.?[A-Za-z0-9_\-./+=]*", "[REDACTED]", text)
    return text


def _fmt_yen(v) -> str:
    try:
        return f"¥{int(str(v).replace(',', '').replace('¥', '') or 0):,}"
    except (ValueError, TypeError):
        return str(v)


# ── 各ツール実装（read-only） ─────────────────────────────

def _tool_system_health(creds_path, sys_ss):
    """SYSTEM_HEALTH_DASHBOARD の最新行を読むだけ（チェックは実行しない＝書込なし）"""
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    try:
        ws = gc.open_by_key(sys_ss).worksheet("SYSTEM_HEALTH_DASHBOARD")
        recs = ws.get_all_records()
    except Exception:
        return "System Health: ダッシュボード未作成またはデータなし（毎朝8:30に自動更新）"
    if not recs:
        return "System Health: まだ記録がありません"
    last = recs[-1]
    parts = ["【System Health 最新】"]
    for k in ["日付", "チェック日時", "最終チェック", "正常数", "異常数", "危険度",
              "Cloud Run", "Scheduler", "Sheets", "直近エラー", "ステータス"]:
        if k in last and str(last[k]).strip():
            parts.append(f"・{k}: {last[k]}")
    return "\n".join(parts)


def _tool_cash_flow(creds_path, cf_ss):
    from core.cash_flow import get_status
    d = get_status(cf_ss, creds_path)
    if not d.get("ok"):
        return "資金繰り: データなし（CASH_FLOW_MASTERに入力が必要）"
    emoji = {"S": "🔴", "A": "🟠", "B": "🟡", "C": "🟢"}.get(d.get("危険度"), "")
    lines = [
        "【資金繰り状況】",
        f"{emoji} 危険度: {d.get('危険度')}",
        f"・現金残高: {_fmt_yen(d.get('現金残高'))}",
        f"・7日以内入金予定: {_fmt_yen(d.get('7日入金'))}",
        f"・7日以内支払い予定: {_fmt_yen(d.get('7日支払い'))}",
        f"・不足見込み: {_fmt_yen(d.get('不足見込み'))}",
        f"・今日必要な売上: {_fmt_yen(d.get('今日必要な売上'))}",
        f"・危険日: {d.get('危険日') or 'なし'}",
    ]
    acts = d.get("actions", [])
    if acts:
        lines.append("・今日のアクション: " + " / ".join(acts[:3]))
    return "\n".join(lines)


def _tool_profit_leak(creds_path, cf_ss):
    from core.profit_leak import get_status
    d = get_status(cf_ss, creds_path)
    if not d.get("ok"):
        return "利益漏れ: データなし（PROFIT_LEAK_MASTERに入力が必要）"
    lines = [f"【利益漏れ状況】 漏れ合計: {_fmt_yen(d.get('total_leak'))}"]
    for biz, b in d.get("by_business", {}).items():
        emoji = {"S": "🔴", "A": "🟠", "B": "🟡", "C": "🟢"}.get(b.get("危険度"), "")
        line = f"{emoji} {biz}: 粗利率{b.get('粗利率')} 危険度{b.get('危険度')} 漏れ{_fmt_yen(b.get('利益漏れ'))}"
        if b.get("危険度") in ("S", "A") and b.get("改善"):
            line += f" → {b.get('改善')}"
        lines.append(line)
    if len(lines) == 1:
        lines.append("（データなし）")
    return "\n".join(lines)


def _tool_lead(creds_path, cf_ss):
    from core.lead_command import get_status
    d = get_status(cf_ss, creds_path)
    if not d.get("ok"):
        return "リード: データなし"
    p = d.get("priority", {})
    return "\n".join([
        "【リード状況】",
        f"・合計: {d.get('total', 0)}件",
        f"・Sリード: {p.get('S', 0)}件 / Aリード: {p.get('A', 0)}件",
        f"・未対応: {d.get('unhandled', 0)}件",
        f"・推定売上合計: {_fmt_yen(d.get('estimated_sales_total'))}",
    ])


def _tool_catering_sales(creds_path, cf_ss):
    from core.catering_sales import get_status
    d = get_status(cf_ss, creds_path)
    if not d.get("ok"):
        return "ケータリング営業: データなし"
    st = d.get("status", {})
    pr = d.get("priority", {})
    return "\n".join([
        "【ケータリング営業状況】",
        f"・営業先数: {d.get('total', 0)}件",
        f"・優先度: S{pr.get('S', 0)} / A{pr.get('A', 0)} / B{pr.get('B', 0)} / C{pr.get('C', 0)}",
        f"・状況内訳: " + " / ".join(f"{k}:{v}" for k, v in st.items()),
    ])


def _tool_daily_action(creds_path):
    from core.daily_action_commander import get_status
    d = get_status(creds_path=creds_path)
    if not d.get("ok"):
        return "Daily Action: データなし"
    lines = ["【本日のタスク状況】"]
    biz_stats = d.get("businesses") or d.get("by_business") or d.get("stats") or {}
    if isinstance(biz_stats, dict) and biz_stats:
        for biz, b in biz_stats.items():
            if isinstance(b, dict):
                lines.append(f"・{biz}: 完了{b.get('完了数', b.get('done', '?'))}/{b.get('全タスク数', b.get('total', '?'))}")
    else:
        # 汎用: そのまま主要キーを表示
        for k in ["date", "日付", "total", "completed", "completion_rate", "完了率"]:
            if k in d:
                lines.append(f"・{k}: {d[k]}")
    if len(lines) == 1:
        lines.append("（本日のタスク未生成、または毎朝9:00に生成）")
    return "\n".join(lines)


def _tool_knowledge(creds_path, sys_ss):
    from core.knowledge_os import get_status
    d = get_status(sys_ss, creds_path)
    lines = ["【Knowledge OS 状況】"]
    for k, v in d.items():
        if k in ("ok",) or "token" in k.lower() or "secret" in k.lower():
            continue
        lines.append(f"・{k}: {v}")
    return "\n".join(lines) if len(lines) > 1 else "Knowledge OS: 状況取得"


def _tool_owner_briefing(creds_path, cf_ss):
    """5行のオーナー向けサマリー（read-only統合）"""
    danger_line = "資金繰り: 取得不可"
    needed = 0
    cf_danger = "C"
    try:
        from core.cash_flow import get_status as cf_get
        cf = cf_get(cf_ss, creds_path)
        if cf.get("ok"):
            cf_danger = cf.get("危険度", "C")
            needed = cf.get("不足見込み", 0)
            danger_line = f"資金繰り危険度{cf_danger}・不足{_fmt_yen(needed)}・今日必要な売上{_fmt_yen(cf.get('今日必要な売上'))}"
    except Exception:
        pass

    profit_line = ""
    try:
        from core.profit_leak import get_status as pl_get
        pl = pl_get(cf_ss, creds_path)
        worst = [(biz, b) for biz, b in pl.get("by_business", {}).items() if b.get("危険度") in ("S", "A")]
        if worst:
            biz, b = worst[0]
            profit_line = f"{biz}の利益漏れ{_fmt_yen(b.get('利益漏れ'))}（{b.get('改善', '')}）"
    except Exception:
        pass

    lead_line = ""
    try:
        from core.lead_command import get_status as ld_get
        ld = ld_get(cf_ss, creds_path)
        s_cnt = ld.get("priority", {}).get("S", 0)
        lead_line = f"Sリード{s_cnt}件・推定売上{_fmt_yen(ld.get('estimated_sales_total'))}"
    except Exception:
        pass

    unhandled = ""
    try:
        from core.lead_command import get_status as ld_get2
        ld2 = ld_get2(cf_ss, creds_path)
        unhandled = f"未対応リード{ld2.get('unhandled', 0)}件"
    except Exception:
        pass

    danger_emoji = {"S": "🔴", "A": "🟠", "B": "🟡", "C": "🟢"}.get(cf_danger, "")
    yesno = "支払い分割/回収前倒しを今日やるか？" if cf_danger in ("S", "A") else "特になし（通常営業でOK）"

    return "\n".join([
        "【オーナーブリーフィング（5行）】",
        f"1. 今日一番危険: {danger_emoji} {danger_line}",
        f"2. 今日一番売上に: {lead_line or profit_line or '大きな案件なし'}",
        f"3. 確認すべき未対応: {unhandled or 'なし'}",
        f"4. 資金繰り注意: {('危険日接近・要回収' if cf_danger in ('S','A') else '問題なし')}",
        f"5. Yes/No判断: {yesno}",
    ])


def _dispatch_tool(name, creds_path, cf_ss, sys_ss):
    if name == "get_system_health":      return _tool_system_health(creds_path, sys_ss)
    if name == "get_cash_flow_status":   return _tool_cash_flow(creds_path, cf_ss)
    if name == "get_profit_leak_status": return _tool_profit_leak(creds_path, cf_ss)
    if name == "get_lead_status":        return _tool_lead(creds_path, cf_ss)
    if name == "get_catering_sales_status": return _tool_catering_sales(creds_path, cf_ss)
    if name == "get_daily_action_status": return _tool_daily_action(creds_path)
    if name == "get_knowledge_status":   return _tool_knowledge(creds_path, sys_ss)
    if name == "get_owner_briefing":     return _tool_owner_briefing(creds_path, cf_ss)
    raise ValueError(f"unknown tool: {name}")


# ── JSON-RPC ハンドラ（Streamable HTTP） ──────────────────

def _result(rid, result):
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def _handle_one(msg, creds_path, cf_ss, sys_ss):
    """1件のJSON-RPCメッセージを処理。(response_or_None, http_status)"""
    method = msg.get("method")
    rid = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        proto = params.get("protocolVersion", PROTOCOL_VERSION_DEFAULT)
        return _result(rid, {
            "protocolVersion": proto,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": "YU HOLDINGS の経営状況を確認するread-onlyツール群です。",
        }), 200

    if method in ("notifications/initialized", "initialized", "notifications/cancelled"):
        return None, 202  # 通知 → 本文なし

    if method == "ping":
        return _result(rid, {}), 200

    if method == "tools/list":
        return _result(rid, {"tools": TOOLS}), 200

    if method == "tools/call":
        name = params.get("name", "")
        if name not in TOOL_NAMES:
            return _result(rid, {
                "content": [{"type": "text", "text": f"不明なツール: {name}"}],
                "isError": True,
            }), 200
        try:
            text = _dispatch_tool(name, creds_path, cf_ss, sys_ss)
            text = _scrub(text)
            return _result(rid, {
                "content": [{"type": "text", "text": text}],
                "isError": False,
            }), 200
        except Exception as e:
            traceback.print_exc()
            return _result(rid, {
                "content": [{"type": "text", "text": f"取得エラー: {str(e)[:200]}"}],
                "isError": True,
            }), 200

    # 未対応メソッド
    if rid is None:
        return None, 202
    return _error(rid, -32601, f"Method not found: {method}"), 200


def handle_mcp(body, creds_path, cf_ss, sys_ss):
    """
    MCP リクエスト本体を処理。
    body は単一dict or バッチ(list)。
    返り値: (json_serializable_or_None, http_status)
    """
    if isinstance(body, list):
        responses = []
        for m in body:
            resp, _ = _handle_one(m, creds_path, cf_ss, sys_ss)
            if resp is not None:
                responses.append(resp)
        return (responses or None), 200
    if isinstance(body, dict):
        return _handle_one(body, creds_path, cf_ss, sys_ss)
    return _error(None, -32700, "Parse error"), 400
