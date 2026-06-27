"""
YU HOLDINGS Knowledge & Execution OS
--------------------------------------
Phase 1: Google Workspace → Obsidian用Markdown 片方向出力

ストレージ設計:
  ・Markdown ファイルは GCS (google-cloud-storage) で保管
    Bucket: tree-beauty-blog-images / prefix: knowledge-os/
  ・Drive API はフォルダ構造の「表示用ナビ」として維持
    （サービスアカウントはDriveへのファイル書き込みストレージ枠なし）
  ・APIキー/TOKEN/秘密情報はMarkdownに絶対出力しない
  ・既存GCSオブジェクトは削除しない（上書きのみ）
  ・Cloud Run上で動作（gcloud CLI非依存）

Obsidian同期方法（ユーザー操作）:
  gsutil rsync -r gs://tree-beauty-blog-images/knowledge-os/ ~/YU_HOLDINGS_OS/
"""

import os
import io
from datetime import datetime, timezone, timedelta
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from google.cloud import storage as gcs_storage

JST = timezone(timedelta(hours=9))

# ── GCS ──────────────────────────────────────────────────
GCS_BUCKET  = "tree-beauty-blog-images"
GCS_PREFIX  = "knowledge-os"
GCS_PUBLIC_BASE = f"https://storage.googleapis.com/{GCS_BUCKET}/{GCS_PREFIX}"

# ── Google Drive ルートフォルダ名 ─────────────────────────
KNOWLEDGE_ROOT_NAME   = "YU_HOLDINGS_Knowledge_OS"
KNOWLEDGE_ROOT_DESC   = "YU HOLDINGS AI 経営ナレッジ保管庫"

FOLDER_STRUCTURE = {
    "00_Dashboard":          "全事業KPIダッシュボード・システム状況",
    "01_Company_Strategy":   "経営戦略・ビジョン・中長期計画",
    "02_Businesses":         "事業別ナレッジ",
    "03_SOP_Manuals":        "標準作業手順書・スタッフマニュアル",
    "04_Decisions":          "経営判断ログ・承認記録",
    "05_Reports":            "週次・月次レポート",
    "06_Leads_Sales":        "リード・営業情報",
    "07_Marketing":          "コンテンツ・SNS・MEO",
    "08_Automation_System":  "AIシステム・自動化ログ",
    "09_HR_Staff":           "人事・スタッフ情報",
    "10_Finance_Risk":       "財務・リスク管理",
    "99_Archive":            "アーカイブ",
}

BUSINESS_FOLDERS = [
    "Tree_Beauty", "Trees_Catering", "TACHINOMIYA",
    "Ryukyu_Hinabe", "Pasta_Pasta", "Z1", "Consulting", "New_Business",
]
BIZ_INITIAL_FILES = [
    "Overview.md", "KPI.md", "Current_Issues.md", "Growth_Strategy.md",
    "Daily_Actions.md", "SOP.md", "Marketing.md",
    "Sales_Leads.md", "Reports.md", "Decision_Log.md", "Improvement_Log.md",
]

# ── Sheets台帳名・ヘッダー ────────────────────────────────
KNOWLEDGE_SHEETS = {
    "KNOWLEDGE_MASTER": [
        "作成日時", "更新日時", "事業名", "カテゴリ", "タイトル", "要約",
        "本文", "関連URL", "Google Drive File ID", "Obsidian Path",
        "タグ", "重要度", "ステータス", "次アクション", "担当", "同期状態", "エラー内容",
    ],
    "DECISION_LOG": [
        "決定日時", "決定者", "事業名", "テーマ", "決定内容", "理由",
        "期待効果", "金額インパクト", "実行責任者", "期限",
        "関連タスクID", "結果", "Obsidian Path", "ステータス",
    ],
    "SOP_INDEX": [
        "作成日時", "更新日時", "事業名", "業務名", "SOPタイトル", "対象スタッフ",
        "手順概要", "チェック項目", "関連資料URL", "Obsidian Path",
        "Google Docs URL", "最終更新者", "ステータス",
    ],
    "EXECUTION_LOG": [
        "実行日時", "事業名", "実行種別", "タスクID", "内容", "担当者",
        "結果", "売上貢献", "改善点", "次回アクション", "Obsidian Path",
        "関連シート", "メモ",
    ],
    "WEEKLY_REVIEW_LOG": [
        "週", "事業名", "売上", "目標", "達成率", "良かったこと",
        "問題", "原因", "次週アクション", "AI提案",
        "オーナー判断必要", "Obsidian Path", "ステータス",
    ],
}

# ── Markdown フロントマター + テンプレート ─────────────────
MD_TEMPLATE = """\
---
title: {title}
business: {business}
category: {category}
date: {date}
source: {source}
status: {status}
tags: {tags}
---

# {title}

## 要約
{summary}

## 現状
{current}

## 数値
{numbers}

## 問題
{issues}

## 原因
{causes}

## 実行アクション
{actions}

## 次回改善
{next_improvement}

## 関連リンク
{links}
"""


def _now_jst() -> str:
    return datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")


def _date_jst() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d")


def _week_label() -> str:
    today = datetime.now(JST)
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return f"{monday.strftime('%Y/%m/%d')}〜{sunday.strftime('%m/%d')}"


# ── 認証ユーティリティ ─────────────────────────────────────
def _gc(creds_path: str) -> gspread.Client:
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    return gspread.authorize(creds)


def _drive(creds_path: str):
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _gcs(creds_path: str) -> gcs_storage.Client:
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/devstorage.read_write"],
    )
    return gcs_storage.Client(project=GCS_PROJECT, credentials=creds)


GCS_PROJECT = "tree-beauty-ai-499303"


def _get_or_create_sheet(ss: gspread.Spreadsheet, title: str, header: list) -> gspread.Worksheet:
    try:
        return ss.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=title, rows=2000, cols=len(header))
        ws.update(values=[header], range_name="A1")
        ws.format("A1:Z1", {
            "backgroundColor": {"red": 0.07, "green": 0.15, "blue": 0.25},
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        })
        return ws


# ── GCS Markdown 保存 ─────────────────────────────────────
def _upload_md_gcs(creds_path: str, gcs_path: str, content: str) -> str:
    """
    GCS へ Markdown をアップロードし、公開 URL を返す。
    gcs_path 例: "knowledge-os/05_Reports/weekly_2026-06-24.md"
    """
    client = _gcs(creds_path)
    bucket = client.bucket(GCS_BUCKET)
    blob   = bucket.blob(gcs_path)
    blob.upload_from_string(content.encode("utf-8"), content_type="text/markdown")
    return f"https://storage.googleapis.com/{GCS_BUCKET}/{gcs_path}"


def _gcs_exists(creds_path: str, gcs_path: str) -> bool:
    client = _gcs(creds_path)
    return client.bucket(GCS_BUCKET).blob(gcs_path).exists()


# ── Drive フォルダ操作（ナビ用・ファイル作成はしない） ────
def _find_folder(drv, name: str, parent_id: Optional[str] = None) -> Optional[str]:
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    res = drv.files().list(q=q, fields="files(id,name)").execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


# ── 1. セットアップ ────────────────────────────────────────
def setup(spreadsheet_id: str, creds_path: str) -> dict:
    """
    ① スプレッドシートに5つの台帳シートを追加
    ② GCS に各事業の初期 .md ファイルを生成（既存は上書きしない）
    ③ Drive フォルダ構造は既存のものを読み取るだけ（作成・削除なし）
    """
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)

    result = {
        "ok": True,
        "sheets_created": [],
        "initial_files": [],
        "gcs_bucket": GCS_BUCKET,
        "gcs_prefix": GCS_PREFIX,
        "obsidian_sync_cmd": (
            f"gsutil rsync -r gs://{GCS_BUCKET}/{GCS_PREFIX}/ "
            "~/YU_HOLDINGS_Knowledge_OS/"
        ),
    }

    # ── Sheets 台帳 ──────────────────────────────────────
    for sheet_name, headers in KNOWLEDGE_SHEETS.items():
        _get_or_create_sheet(ss, sheet_name, headers)
        result["sheets_created"].append(sheet_name)

    # ── 各事業の初期 .md を GCS へ ────────────────────────
    for biz in BUSINESS_FOLDERS:
        for fname in BIZ_INITIAL_FILES:
            gcs_path = f"{GCS_PREFIX}/02_Businesses/{biz}/{fname}"
            if not _gcs_exists(creds_path, gcs_path):
                title = fname.replace(".md", "").replace("_", " ")
                md = MD_TEMPLATE.format(
                    title=f"{biz} — {title}",
                    business=biz.replace("_", " "),
                    category=title,
                    date=_date_jst(),
                    source="Knowledge OS Setup",
                    status="draft",
                    tags=f"[{biz}, {title}]",
                    summary="（未記入）",
                    current="（未記入）",
                    numbers="（未記入）",
                    issues="（未記入）",
                    causes="（未記入）",
                    actions="（未記入）",
                    next_improvement="（未記入）",
                    links="（未記入）",
                )
                url = _upload_md_gcs(creds_path, gcs_path, md)
                result["initial_files"].append(f"02_Businesses/{biz}/{fname}")

    # Drive フォルダIDを参照（作成しない）
    try:
        drv = _drive(creds_path)
        folder_ids = _get_folder_ids(drv)
        result["drive_folder_count"] = len(folder_ids)
        result["drive_root_url"] = (
            f"https://drive.google.com/drive/folders/{folder_ids.get('root', '')}"
            if folder_ids.get("root") else ""
        )
    except Exception as e:
        result["drive_note"] = f"Drive参照スキップ: {type(e).__name__}"

    return result


# ── 2. Markdown生成ユーティリティ ────────────────────────
def _render_md(title: str, business: str, category: str, source: str,
               summary: str, current: str = "—", numbers: str = "—",
               issues: str = "—", causes: str = "—", actions: str = "—",
               next_improvement: str = "—", links: str = "—",
               tags: list[str] | None = None, status: str = "auto") -> str:
    return MD_TEMPLATE.format(
        title=title, business=business, category=category,
        date=_date_jst(), source=source, status=status,
        tags=str(tags or [business, category]),
        summary=summary, current=current, numbers=numbers,
        issues=issues, causes=causes, actions=actions,
        next_improvement=next_improvement, links=links,
    )


# ── 3. System Health → Markdown ──────────────────────────
def export_health_to_md(health_result: dict, creds_path: str) -> tuple[str, str]:
    """System Health Monitor結果をMarkdown化してGCS保存"""
    now   = _date_jst()
    cr    = health_result.get("cloud_run", {})
    sch   = health_result.get("scheduler", {})
    sht   = health_result.get("sheets", {})
    errs  = health_result.get("critical_errors", [])
    beauty = health_result.get("beauty_sales", {})

    numbers = (
        f"- Cloud Run: {cr.get('ok')}/{cr.get('total')} 正常\n"
        f"- Scheduler: {sch.get('ok')}/{sch.get('total')} ENABLED\n"
        f"- Sheets: {sht.get('ok')}/{sht.get('total')} 正常\n"
        f"- 重大エラー: {len(errs)}件"
    )
    if beauty:
        numbers += f"\n- Beauty売上達成率: {beauty.get('rate_pct')}%（{beauty.get('status')}）"

    issues  = "\n".join(f"- {e}" for e in errs) if errs else "なし"
    actions = "- SYSTEM_HEALTH_DASHBOARD を確認\n- 重大エラーは即時対応"

    md = _render_md(
        title=f"System Health Check — {now}",
        business="YU HOLDINGS",
        category="システム監視",
        source="system_health_monitor",
        summary=f"全{cr.get('total',7)}サービス、Scheduler {sch.get('total',31)}本の健全性確認",
        numbers=numbers, issues=issues, actions=actions,
        tags=["system", "health", "monitoring"],
    )
    gcs_path = f"{GCS_PREFIX}/08_Automation_System/health_{now}.md"
    url = _upload_md_gcs(creds_path, gcs_path, md)
    return gcs_path, url


# ── 4. 経営判断 → Markdown ──────────────────────────────
def export_decision_to_md(spreadsheet_id: str, creds_path: str) -> list[dict]:
    """DECISION_LOG の未同期行をMarkdown化してGCS保存"""
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)
    ws = _get_or_create_sheet(ss, "DECISION_LOG", KNOWLEDGE_SHEETS["DECISION_LOG"])

    rows    = ws.get_all_records()
    results = []

    for i, row in enumerate(rows, start=2):
        if row.get("ステータス") in ("同期済", "skip"):
            continue
        if not row.get("決定内容"):
            continue

        title    = row.get("テーマ", "無題の決定")
        biz      = row.get("事業名", "YU HOLDINGS")
        content  = row.get("決定内容", "")
        reason   = row.get("理由", "")
        effect   = row.get("期待効果", "")
        impact   = row.get("金額インパクト", "")
        owner    = row.get("実行責任者", "")
        deadline = row.get("期限", "")

        numbers = f"- 金額インパクト: {impact}\n- 実行責任者: {owner}\n- 期限: {deadline}"
        md = _render_md(
            title=title, business=biz, category="経営判断",
            source="DECISION_LOG",
            summary=content[:200],
            current=f"決定日時: {row.get('決定日時', '')}",
            numbers=numbers, issues=reason,
            actions=f"- {owner} が {deadline} までに実行",
            next_improvement=effect,
        )
        safe_title = "".join(c if c.isalnum() or c in "._- " else "_" for c in title)[:60]
        fname    = f"decision_{_date_jst()}_{safe_title}.md"
        gcs_path = f"{GCS_PREFIX}/04_Decisions/{fname}"
        url      = _upload_md_gcs(creds_path, gcs_path, md)
        obs_path = f"04_Decisions/{fname}"

        ws.update(values=[["同期済"]], range_name=f"N{i}")
        ws.update(values=[[obs_path]], range_name=f"M{i}")
        results.append({"title": title, "gcs_url": url, "path": obs_path})

    return results


# ── 5. 日次エクスポート ────────────────────────────────────
def export_daily(spreadsheet_id: str, creds_path: str) -> dict:
    """
    当日の重要ログ・タスク結果・売上アラート・決定事項を
    Markdown化してDrive保存 + KNOWLEDGE_MASTER + EXECUTION_LOGに記録
    """
    gc    = _gc(creds_path)
    ss    = gc.open_by_key(spreadsheet_id)
    now   = _now_jst()
    date  = _date_jst()
    km_ws = _get_or_create_sheet(ss, "KNOWLEDGE_MASTER", KNOWLEDGE_SHEETS["KNOWLEDGE_MASTER"])
    el_ws = _get_or_create_sheet(ss, "EXECUTION_LOG",    KNOWLEDGE_SHEETS["EXECUTION_LOG"])
    exported = []

    # ── (a) SYSTEM_HEALTH_DASHBOARD 当日分 ──────────────
    try:
        dash_ws    = ss.worksheet("SYSTEM_HEALTH_DASHBOARD")
        today_rows = [r for r in dash_ws.get_all_values()[1:]
                      if r and r[0].startswith(date[:10])]
        if today_rows:
            errors       = [r for r in today_rows if r[3] not in ("正常",)]
            summary      = f"Cloud Run・Scheduler・Sheets全チェック完了 / 異常{len(errors)}件"
            numbers_text = f"- チェック件数: {len(today_rows)}\n- 異常件数: {len(errors)}"
            issues_text  = "\n".join(f"- {r[1]}: {r[7]}" for r in errors) or "なし"
            md = _render_md(
                title=f"Daily Health Report — {date}",
                business="YU HOLDINGS", category="システム監視",
                source="SYSTEM_HEALTH_DASHBOARD",
                summary=summary, numbers=numbers_text, issues=issues_text,
                actions="- 次の問題は翌日チェックで継続監視",
                tags=["health", "daily", "system"],
            )
            gcs_path = f"{GCS_PREFIX}/08_Automation_System/daily_health_{date}.md"
            url      = _upload_md_gcs(creds_path, gcs_path, md)
            obs_path = f"08_Automation_System/daily_health_{date}.md"
            km_ws.append_row([
                now, now, "YU HOLDINGS", "システム監視",
                f"Daily Health Report — {date}", summary,
                "", url, "", obs_path, "health,daily", "A",
                "完了", "", "AI", "同期済", "",
            ])
            exported.append({"type": "health", "gcs_path": gcs_path, "url": url})
    except Exception as e:
        exported.append({"type": "health", "error": str(e)[:80]})

    # ── (b) Beauty 売上危険アラート ──────────────────────
    try:
        beauty_ss_id = os.getenv("GOOGLE_SPREADSHEET_ID", spreadsheet_id)
        bss    = gc.open_by_key(beauty_ss_id)
        kpi_ws = bss.worksheet("POS_KPI")
        ym     = datetime.now(JST).strftime("%Y/%m")
        for row in kpi_ws.get_all_values()[1:]:
            if row and row[0] == ym:
                sales  = int(row[1]) if row[1] and row[1].replace(",","").isdigit() else 0
                target = int(row[4]) if len(row)>4 and row[4] and row[4].replace(",","").isdigit() else 0
                rate   = sales / target if target else 0
                if rate < 0.60:
                    shortage   = max(0, target - sales)
                    importance = "S" if rate < 0.30 else "A"
                    md = _render_md(
                        title=f"Beauty 売上アラート — {ym}",
                        business="Tree Beauty", category="売上アラート",
                        source="POS_KPI",
                        summary=f"売上 ¥{sales:,} / 目標 ¥{target:,} / 達成率{rate*100:.1f}%",
                        numbers=(
                            f"- 売上: ¥{sales:,}\n- 目標: ¥{target:,}\n"
                            f"- 達成率: {rate*100:.1f}%\n- 不足額: ¥{shortage:,}"
                        ),
                        issues=f"達成率{rate*100:.1f}% — 目標の60%未満（重要度{importance}）",
                        actions=(
                            "- 予約空き状況を即日投稿\n- 口コミ依頼1件実施\n"
                            "- HPBブログ更新\n- Google投稿実施\n- 再来店LINE送信候補確認"
                        ),
                        tags=["beauty", "sales_alert", importance.lower()],
                        status=f"要対応(重要度{importance})",
                    )
                    gcs_path = f"{GCS_PREFIX}/02_Businesses/Tree_Beauty/beauty_sales_alert_{ym.replace('/','-')}.md"
                    url      = _upload_md_gcs(creds_path, gcs_path, md)
                    obs_path = f"02_Businesses/Tree_Beauty/beauty_sales_alert_{ym.replace('/','-')}.md"
                    km_ws.append_row([
                        now, now, "Tree Beauty", "売上アラート",
                        f"Beauty売上アラート {ym}", f"達成率{rate*100:.1f}%",
                        "", url, "", obs_path, f"beauty,sales_alert,{importance.lower()}",
                        importance, "要対応", "予約空き・口コミ・HPB・Google投稿", "AI", "同期済", "",
                    ])
                    exported.append({"type": "beauty_alert", "gcs_path": gcs_path, "url": url})
                break
    except Exception as e:
        exported.append({"type": "beauty_alert", "error": str(e)[:80]})

    # ── (c) EXECUTION_LOG 記録 ────────────────────────────
    el_ws.append_row([
        now, "YU HOLDINGS", "日次ナレッジエクスポート", "",
        f"Daily Knowledge Export — {date}", "AI",
        "完了", "", "", "",
        f"{GCS_PREFIX}/00_Dashboard/daily_{date}.md", "KNOWLEDGE_MASTER", "",
    ])

    return {"ok": True, "date": date, "exported": exported}


# ── 6. 週次エクスポート ────────────────────────────────────
# 各事業の設定: (env_key, monthly_target, fallback_sheets)
_BIZ_CONFIG = {
    "Tree Beauty": {
        "env":    "GOOGLE_SPREADSHEET_ID",
        "target": 500_000,
        "sheets": ["POS_KPI", "POS_日次売上"],
        "folder": "Tree_Beauty",
    },
    "TACHINOMIYA": {
        "env":    "TACHINOMIYA_SPREADSHEET_ID",
        "target": 3_500_000,
        "sheets": ["POS_KPI", "POS_日次売上", "02_日次売上"],
        "folder": "TACHINOMIYA",
    },
    "Trees Catering": {
        "env":    "CATERING_SPREADSHEET_ID",
        "target": 800_000,
        "sheets": ["POS_KPI", "06_売上管理"],
        "folder": "Trees_Catering",
    },
    "琉球火鍋": {
        "env":    "HINABE_SPREADSHEET_ID",
        "target": 1_500_000,
        "sheets": ["POS_KPI", "01_KPI", "02_日次売上"],
        "folder": "Ryukyu_Hinabe",
    },
    "パスタパスタ": {
        "env":    "PASTA_SPREADSHEET_ID",
        "target": 2_000_000,
        "sheets": ["POS_KPI", "05_売上管理"],
        "folder": "Pasta_Pasta",
    },
    "Z1": {
        "env":    "Z1_SPREADSHEET_ID",
        "target": 1_500_000,
        "sheets": ["POS_KPI", "05_売上管理"],
        "folder": "Z1",
    },
}


def _parse_int(val: str) -> int:
    if not val:
        return 0
    cleaned = str(val).replace(",", "").replace("¥", "").replace(" ", "").strip()
    try:
        return int(float(cleaned))
    except (ValueError, TypeError):
        return 0


def _fetch_biz_kpi(gc, biz_name: str, cfg: dict, ym: str) -> dict:
    """
    事業スプレッドシートから月次売上を取得。
    POS_KPI → 代替シートの順でフォールバック。
    """
    ss_id = os.getenv(cfg["env"], "")
    if not ss_id:
        return {"sales": 0, "target": cfg["target"], "source": "データなし（SS_ID未設定）", "ok": False}

    try:
        bss    = gc.open_by_key(ss_id)
        sheets = [ws.title for ws in bss.worksheets()]
    except Exception as e:
        return {"sales": 0, "target": cfg["target"], "source": f"スプレッドシートアクセス失敗", "ok": False}

    for sheet_name in cfg["sheets"]:
        if sheet_name not in sheets:
            continue
        try:
            ws   = bss.worksheet(sheet_name)
            rows = ws.get_all_values()
            for row in rows:
                if not row or not row[0]:
                    continue
                cell = str(row[0]).strip()
                if cell == ym or cell.startswith(ym[:7]):
                    # POS_KPI: r[1]=売上, r[4]=目標
                    if sheet_name == "POS_KPI":
                        sales  = _parse_int(row[1]) if len(row) > 1 else 0
                        target = _parse_int(row[4]) if len(row) > 4 else cfg["target"]
                        if target == 0:
                            target = cfg["target"]
                        return {"sales": sales, "target": target,
                                "source": "POS_KPI", "ok": True}
                    # POS_日次売上 / 02_日次売上: r[2]=売上が多い構造
                    if sheet_name in ("POS_日次売上", "02_日次売上"):
                        # 年月が一致する行を合計（日次データのため）
                        month_rows = [r for r in rows if r and str(r[0]).startswith(ym)]
                        total = sum(_parse_int(r[2]) for r in month_rows if len(r) > 2)
                        if total > 0:
                            return {"sales": total, "target": cfg["target"],
                                    "source": f"{sheet_name}（日次合計、暫定）", "ok": True}
                    # 06_売上管理: r[0]=年月, r[3]=売上
                    if sheet_name == "06_売上管理":
                        month_rows = [r for r in rows if r and str(r[0]) == ym]
                        total = sum(_parse_int(r[3]) for r in month_rows if len(r) > 3)
                        if total > 0:
                            return {"sales": total, "target": cfg["target"],
                                    "source": "06_売上管理（受注ベース）", "ok": True}
                    # 05_売上管理 (コンサル): r[0]=年月, r[2]か r[3]=売上
                    if sheet_name == "05_売上管理":
                        month_rows = [r for r in rows if r and str(r[0]).startswith(ym[:4])]
                        total = sum(_parse_int(r[2]) for r in month_rows if len(r) > 2)
                        if total > 0:
                            return {"sales": total, "target": cfg["target"],
                                    "source": "05_売上管理（暫定）", "ok": True}
                    # 01_KPI (琉球火鍋など): r[0]=年月, r[1]=売上, r[4]=目標
                    if sheet_name == "01_KPI":
                        sales  = _parse_int(row[1]) if len(row) > 1 else 0
                        target = _parse_int(row[4]) if len(row) > 4 else cfg["target"]
                        if target == 0:
                            target = cfg["target"]
                        if sales > 0:
                            return {"sales": sales, "target": target,
                                    "source": "01_KPI", "ok": True}
        except Exception:
            continue

    return {"sales": 0, "target": cfg["target"],
            "source": "POS_KPI未整備 — CSVアップロード確認が必要", "ok": False}


def _danger_level(rate: float) -> str:
    if rate >= 0.90:  return "🟢 良好"
    if rate >= 0.70:  return "🟡 注意"
    if rate >= 0.50:  return "🟠 危険"
    return "🔴 重大危機"


def _weekly_md(week: str, now: str, biz_data: list[dict]) -> str:
    """週次レビューMarkdownを生成"""
    today    = datetime.now(JST)
    days_left = (today.replace(day=1, month=today.month % 12 + 1 if today.month < 12 else 1,
                               year=today.year + (1 if today.month == 12 else 0)) -
                 timedelta(days=1)).day - today.day + 1

    # 全社サマリー計算
    total_sales  = sum(b["sales"] for b in biz_data if b.get("ok"))
    total_target = sum(b["target"] for b in biz_data if b.get("ok"))
    total_rate   = total_sales / total_target if total_target else 0
    danger_biz   = [b["name"] for b in biz_data if b.get("ok") and b["sales"]/b["target"] < 0.60]
    good_biz     = [b["name"] for b in biz_data if b.get("ok") and b["sales"]/b["target"] >= 0.90]

    # 最重要アクション（最も危険な事業）
    worst = min((b for b in biz_data if b.get("ok")), key=lambda b: b["sales"]/b["target"], default=None)
    top_action = f"{worst['name']} 達成率{worst['sales']/worst['target']*100:.1f}% — 即時強化対応" if worst else "なし"

    lines = [
        f"---",
        f"title: YU HOLDINGS 週次レビュー {week}",
        f"business: YU HOLDINGS",
        f"category: 週次レポート",
        f"date: {_date_jst()}",
        f"source: knowledge_os_weekly",
        f"status: auto",
        f"tags: [weekly, kpi, all_business]",
        f"---",
        f"",
        f"# YU HOLDINGS 週次レビュー",
        f"**対象週**: {week}　**生成**: {now}",
        f"",
        f"---",
        f"",
        f"## 全社サマリー",
        f"",
        f"| 項目 | 値 |",
        f"|---|---|",
        f"| 総売上（月間累計） | ¥{total_sales:,} |",
        f"| 目標合計 | ¥{total_target:,} |",
        f"| 全社達成率 | {total_rate*100:.1f}% |",
        f"| 残日数 | {days_left}日 |",
        f"| 危険事業（60%未満） | {', '.join(danger_biz) if danger_biz else 'なし'} |",
        f"| 好調事業（90%以上） | {', '.join(good_biz) if good_biz else 'なし'} |",
        f"| **今週の最重要アクション** | {top_action} |",
        f"",
        f"---",
        f"",
        f"## 事業別レビュー",
        f"",
    ]

    for b in biz_data:
        sales  = b["sales"]
        target = b["target"]
        rate   = sales / target if target else 0
        short  = max(0, target - sales)
        daily_need = round(short / days_left) if days_left > 0 else 0
        danger = _danger_level(rate)

        if b.get("ok"):
            analysis = (
                f"達成率{rate*100:.1f}%。"
                + (f"残{days_left}日で¥{short:,}の挽回が必要（日販¥{daily_need:,}）。" if short > 0 else "目標達成ペース。")
            )
            s_task = (
                f"売上強化SNS投稿・口コミ依頼・予約促進を最優先"
                if rate < 0.50
                else f"現状維持＋集客施策継続" if rate < 0.90
                else "ペース維持・スタッフ評価実施"
            )
            owner_note = (
                f"⚠️ 目標達成に向け追加施策の判断が必要（不足額¥{short:,}）" if rate < 0.60
                else "現状継続で問題なし"
            )
        else:
            analysis   = f"⚠️ {b['source']}"
            s_task     = "CSVアップロード or 売上入力を確認"
            owner_note = "データ入力確認が必要"

        lines += [
            f"### {b['name']}",
            f"",
            f"| 指標 | 値 |",
            f"|---|---|",
            f"| 月間累計売上 | ¥{sales:,} |",
            f"| 月次目標 | ¥{target:,} |",
            f"| 達成率 | {rate*100:.1f}% |",
            f"| 不足額 | ¥{short:,} |",
            f"| 必要日販（残{days_left}日） | ¥{daily_need:,} |",
            f"| 危険度 | {danger} |",
            f"| データソース | {b['source']} |",
            f"",
            f"**AI分析**: {analysis}",
            f"",
            f"**来週のSタスク**: {s_task}",
            f"",
            f"**オーナー判断事項**: {owner_note}",
            f"",
        ]

    # 重点改善
    lines += [
        f"---",
        f"",
        f"## 重点改善",
        f"",
    ]
    sorted_biz = sorted((b for b in biz_data if b.get("ok")),
                        key=lambda b: b["sales"]/b["target"])
    for b in sorted_biz[:3]:
        rate  = b["sales"] / b["target"]
        short = max(0, b["target"] - b["sales"])
        lines.append(f"### {b['name']} — 達成率{rate*100:.1f}%（不足額¥{short:,}）")
        lines.append(f"- 残{days_left}日で必要日販: ¥{round(short/days_left):,}" if days_left else "")
        lines.append(f"- 即時アクション: SNS投稿・口コミ依頼・予約促進・HPB更新")
        lines.append(f"")

    # 来週の実行指示
    lines += [
        f"---",
        f"",
        f"## 来週の実行指示（Daily Action Commander 反映案）",
        f"",
    ]
    for b in sorted_biz:
        rate  = b["sales"] / b["target"]
        if rate < 0.60:
            lines.append(f"- 【{b['name']}・S】予約/空き枠SNS告知を毎日実施")
            lines.append(f"- 【{b['name']}・S】口コミ依頼を週3件以上")
        elif rate < 0.90:
            lines.append(f"- 【{b['name']}・A】集客コンテンツを週2件投稿")
    lines.append(f"")

    return "\n".join(lines)


def export_weekly(spreadsheet_id: str, creds_path: str) -> dict:
    """全事業週次KPIを集計し、リッチなMarkdownとして GCS 保存"""
    gc    = _gc(creds_path)
    ss    = gc.open_by_key(spreadsheet_id)
    week  = _week_label()
    now   = _now_jst()
    ym    = datetime.now(JST).strftime("%Y/%m")
    km_ws = _get_or_create_sheet(ss, "KNOWLEDGE_MASTER",  KNOWLEDGE_SHEETS["KNOWLEDGE_MASTER"])
    wr_ws = _get_or_create_sheet(ss, "WEEKLY_REVIEW_LOG", KNOWLEDGE_SHEETS["WEEKLY_REVIEW_LOG"])

    biz_data = []
    for biz_name, cfg in _BIZ_CONFIG.items():
        kpi = _fetch_biz_kpi(gc, biz_name, cfg, ym)
        kpi["name"] = biz_name
        biz_data.append(kpi)
        rate = kpi["sales"] / kpi["target"] if kpi["target"] else 0
        wr_ws.append_row([
            week, biz_name, kpi["sales"], kpi["target"], f"{rate*100:.1f}%",
            "", "", kpi["source"], "", "", "", "", "未記入",
        ])

    md       = _weekly_md(week, now, biz_data)
    fname    = f"weekly_review_{_date_jst()}.md"
    gcs_path = f"{GCS_PREFIX}/05_Reports/{fname}"
    url      = _upload_md_gcs(creds_path, gcs_path, md)
    obs_path = f"05_Reports/{fname}"

    ok_count = sum(1 for b in biz_data if b.get("ok"))
    km_ws.append_row([
        now, now, "YU HOLDINGS", "週次レポート",
        f"Weekly Review — {week}", f"{ok_count}/{len(biz_data)}事業データあり",
        "", url, "", obs_path, "weekly,kpi", "A",
        "完了", "", "AI", "同期済", "",
    ])

    return {
        "ok":       True,
        "week":     week,
        "biz_count": len(biz_data),
        "ok_count":  ok_count,
        "exported": [{"gcs_path": gcs_path, "url": url}],
    }


# ── 7. SOP エクスポート ────────────────────────────────────
_INITIAL_SOPS = [
    {
        "business": "YU HOLDINGS", "task": "System Health Monitor確認手順",
        "title":    "System Health Monitor 日次確認SOP",
        "staff":    "オーナー・AI管理者",
        "steps":    (
            "1. 毎朝8:30にLINE通知を確認\n"
            "2. 異常があれば SYSTEM_HEALTH_DASHBOARD を開く\n"
            "3. 重要度S/Aのエラーは当日中に対応\n"
            "4. Cloud Runサービスダウンは Cloud Run コンソールで再デプロイ\n"
            "5. Schedulerジョブ無効は Cloud Scheduler で ENABLE"
        ),
        "checks": "□ LINE通知受信 □ ダッシュボード確認 □ エラー対応完了",
    },
    {
        "business": "TACHINOMIYA", "task": "口コミ依頼ルール",
        "title":    "TACHINOMIYA 口コミ依頼SOP",
        "staff":    "スタッフ全員",
        "steps":    (
            "1. 来店客が食事を楽しんでいるタイミングで声かけ\n"
            "2. 「Googleマップの口コミを書いていただけますか？」\n"
            "3. QRコードを提示（Googleマップのリンク）\n"
            "4. 書いてもらえたら「ありがとうございます」と伝える\n"
            "5. 完了をDAC（LINE）で「完了」と返信"
        ),
        "checks": "□ 声かけ実施 □ QR提示 □ LINE完了報告",
    },
    {
        "business": "Tree Beauty", "task": "POS CSVアップロード手順",
        "title":    "Airegi POS CSV アップロードSOP",
        "staff":    "オーナー",
        "steps":    (
            "1. Airegi管理画面から「売上集計CSV」と「会計明細CSV」をダウンロード\n"
            "2. /Users/tokudayuya/Downloads/ に保存\n"
            "3. Claude Codeに「スプレッドシートを更新して」と依頼\n"
            "4. POS_日次売上・②売上入力・POS_KPI の更新を確認\n"
            "5. 月次目標との達成率を確認"
        ),
        "checks": "□ CSV保存 □ スプレッドシート更新 □ KPI確認",
    },
]


def export_sop(spreadsheet_id: str, creds_path: str) -> dict:
    """SOP_INDEXの未同期行 + 初期SOPをMarkdown化してGCS保存"""
    gc     = _gc(creds_path)
    ss     = gc.open_by_key(spreadsheet_id)
    sop_ws = _get_or_create_sheet(ss, "SOP_INDEX",       KNOWLEDGE_SHEETS["SOP_INDEX"])
    km_ws  = _get_or_create_sheet(ss, "KNOWLEDGE_MASTER", KNOWLEDGE_SHEETS["KNOWLEDGE_MASTER"])
    now      = _now_jst()
    exported = []

    for sop in _INITIAL_SOPS:
        title = sop["title"]
        safe  = "".join(c if c.isalnum() or c in "._- " else "_" for c in title)[:60]
        fname = f"sop_{safe}.md"

        existing = [r for r in sop_ws.get_all_records() if r.get("SOPタイトル") == title]
        if existing:
            continue

        md = _render_md(
            title=title, business=sop["business"],
            category="SOP", source="SOP_INDEX",
            summary=sop["steps"].split("\n")[0],
            current=f"対象スタッフ: {sop['staff']}",
            actions=sop["steps"],
            next_improvement=sop.get("checks", ""),
            tags=["sop", sop["business"].lower().replace(" ","_")],
        )
        gcs_path = f"{GCS_PREFIX}/03_SOP_Manuals/{fname}"
        url      = _upload_md_gcs(creds_path, gcs_path, md)
        obs_path = f"03_SOP_Manuals/{fname}"

        sop_ws.append_row([
            now, now, sop["business"], sop["task"], title, sop["staff"],
            sop["steps"][:100], sop.get("checks",""), url, obs_path, "", "AI", "有効",
        ])
        km_ws.append_row([
            now, now, sop["business"], "SOP", title, sop["steps"][:100],
            "", url, "", obs_path, f"sop,{sop['business'].lower()}", "B",
            "完了", "", "AI", "同期済", "",
        ])
        exported.append({"title": title, "gcs_path": gcs_path, "url": url})

    return {"ok": True, "exported": exported}


# ── 8. ステータス確認 ─────────────────────────────────────
def get_status(spreadsheet_id: str, creds_path: str) -> dict:
    gc = _gc(creds_path)
    ss = gc.open_by_key(spreadsheet_id)

    stats = {}
    for sheet_name in KNOWLEDGE_SHEETS:
        try:
            ws    = ss.worksheet(sheet_name)
            rows  = ws.get_all_values()
            total = max(0, len(rows) - 1)
            synced = sum(1 for r in rows[1:] if len(r) > 15 and r[15] == "同期済")
            errors = sum(1 for r in rows[1:] if len(r) > 16 and r[16])
            stats[sheet_name] = {"total": total, "synced": synced, "errors": errors}
        except Exception:
            stats[sheet_name] = {"total": 0, "synced": 0, "errors": 0}

    return {
        "ok": True,
        "checked_at": _now_jst(),
        "sheets": stats,
        "total_records":  sum(v["total"]  for v in stats.values()),
        "total_synced":   sum(v["synced"] for v in stats.values()),
        "total_errors":   sum(v["errors"] for v in stats.values()),
    }


# ── 9. フォルダIDキャッシュ取得 ───────────────────────────
def _get_folder_ids(drv) -> dict:
    """Drive上のKnowledge OSフォルダIDを全取得"""
    root_id = _find_folder(drv, KNOWLEDGE_ROOT_NAME)
    if not root_id:
        return {}
    ids = {"root": root_id}
    for folder in FOLDER_STRUCTURE:
        fid = _find_folder(drv, folder, parent_id=root_id)
        if fid:
            ids[folder] = fid
    return ids


# ── 10. 決定事項を自動保存 ───────────────────────────────
def save_decision(
    spreadsheet_id: str, creds_path: str,
    theme: str, business: str, content: str,
    reason: str, effect: str, impact: str = "",
    owner: str = "AI", deadline: str = "",
    auto_export_md: bool = True,
) -> dict:
    gc    = _gc(creds_path)
    ss    = gc.open_by_key(spreadsheet_id)
    ws    = _get_or_create_sheet(ss, "DECISION_LOG", KNOWLEDGE_SHEETS["DECISION_LOG"])
    now   = _now_jst()

    row = [
        now, "AI/オーナー", business, theme, content, reason,
        effect, impact, owner, deadline,
        "", "", "", "未同期",
    ]
    ws.append_row(row)

    if auto_export_md:
        try:
            export_decision_to_md(spreadsheet_id, creds_path)
        except Exception as e:
            return {"ok": True, "warning": str(e)[:80]}

    return {"ok": True, "theme": theme, "logged": True}


# ── 11. テスト ─────────────────────────────────────────────
def run_test(spreadsheet_id: str, creds_path: str) -> dict:
    """テスト用Markdown生成 → GCS保存 → Sheets記録"""
    gc    = _gc(creds_path)
    ss    = gc.open_by_key(spreadsheet_id)
    km_ws = _get_or_create_sheet(ss, "KNOWLEDGE_MASTER", KNOWLEDGE_SHEETS["KNOWLEDGE_MASTER"])
    now   = _now_jst()
    date  = _date_jst()

    test_md = _render_md(
        title=f"[TEST] Knowledge OS テスト — {date}",
        business="YU HOLDINGS",
        category="システムテスト",
        source="knowledge_test",
        summary="Knowledge OS 動作確認テスト。GCS保存・Sheets記録が正常に動作しているか確認。",
        numbers=f"- ストレージ: GCS ({GCS_BUCKET})\n- テスト日時: {now}",
        issues="なし（テスト実行）",
        actions="- GCS保存確認\n- Sheets記録確認\n- Markdown形式確認",
        tags=["test", "knowledge_os"],
        status="test",
    )
    gcs_path = f"{GCS_PREFIX}/00_Dashboard/test_{date}.md"
    url      = _upload_md_gcs(creds_path, gcs_path, test_md)
    obs_path = f"00_Dashboard/test_{date}.md"

    km_ws.append_row([
        now, now, "YU HOLDINGS", "テスト", "[TEST] Knowledge OS テスト",
        "動作確認テスト", "", url, "", obs_path,
        "test", "C", "完了", "", "AI", "同期済", "",
    ])

    return {
        "ok":       True,
        "gcs_path": gcs_path,
        "gcs_url":  url,
        "obs_path": obs_path,
        "obsidian_sync_cmd": (
            f"gsutil rsync -r gs://{GCS_BUCKET}/{GCS_PREFIX}/ ~/YU_HOLDINGS_Knowledge_OS/"
        ),
    }
