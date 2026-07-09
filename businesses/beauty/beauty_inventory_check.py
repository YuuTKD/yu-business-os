"""
Tree Beauty 画像在庫 & 投稿候補在庫チェック（API確認用）
実行: cd /Users/tokudayuya/yu-business-os && python3 businesses/beauty/beauty_inventory_check.py

注意: Google認証が必要。認証情報がない環境ではスキップされる。
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

IMAGE_LIBRARY_SS    = "15cfsC2HIzu1FGW602dxqNuv-DJpmLiZhatvB-hDn2XM"
IMAGE_LIBRARY_SHEET = "画像台帳"
THREADS_POST_LOG_SS = "1I6wRRDa-b440DBxZ3TbFbfMxEXZecowzOsxTAYSxyBE"

# beautyのDriveフォルダ名カテゴリ → テーマキー
FOLDER_TO_THEME_CHECK = {
    "脱毛":               "hair_removal",
    "ムダ毛":             "hair_removal",
    "VIO":               "hair_removal",
    "セルフホワイトニング": "whitening",
    "ホワイトニング":       "whitening",
    "よもぎ蒸し":          "yomogi",
    "よもぎ":              "yomogi",
    "カッピング":          "cupping",
    "店舗内観":            "salon_interior",
    "店舗外観":            "salon_interior",
    "内観":               "salon_interior",
    "外観":               "salon_interior",
    "サロン":              "salon_interior",
    "店内":               "salon_interior",
    "スタッフ":            "staff",
    "メニュー":            "menu",
    "料金表":              "menu",
    "キャンペーン":         "campaign",
    "特典":               "campaign",
    "ビフォーアフター":     "general_beauty",
    "お客様の声":          "general_beauty",
    "美容":               "general_beauty",
}

BEAUTY_IMAGE_MIN_STOCK = {
    "salon_interior":  10,
    "hair_removal":    10,
    "whitening":       10,
    "yomogi":          10,
    "cupping":          5,
    "menu":             5,
    "campaign":         5,
    "general_beauty":  10,
    "staff":            5,
}


def check_image_library(creds_path: str) -> dict:
    """IMAGE_LIBRARY の BEAUTY カテゴリ画像数を確認"""
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
        gc = gspread.authorize(creds)
        ws = gc.open_by_key(IMAGE_LIBRARY_SS).worksheet(IMAGE_LIBRARY_SHEET)
        rows = ws.get_all_records()

        # BEAUTYの行だけ抽出
        beauty_rows = [r for r in rows if str(r.get("事業", "")).upper() == "BEAUTY"]
        gcs_rows    = [r for r in beauty_rows if r.get("gcs_public_url", "")]

        # テーマ別カウント
        theme_counts = {}
        for row in beauty_rows:
            cat  = str(row.get("カテゴリ", "")).strip()
            theme = FOLDER_TO_THEME_CHECK.get(cat, "general_beauty")
            img_theme = str(row.get("image_theme", "")).strip()
            use_theme = img_theme if img_theme else theme
            has_gcs = bool(row.get("gcs_public_url", ""))
            if has_gcs:
                theme_counts[use_theme] = theme_counts.get(use_theme, 0) + 1

        return {
            "ok": True,
            "total_beauty": len(beauty_rows),
            "gcs_ready": len(gcs_rows),
            "theme_counts": theme_counts,
        }

    except FileNotFoundError:
        return {"ok": False, "reason": "認証ファイルが見つからない（環境変数GOOGLE_APPLICATION_CREDENTIALS未設定）"}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def check_post_candidates(creds_path: str) -> dict:
    """THREADS_POST_LOG の Threads投稿シートにBeauty候補があるか確認"""
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
        gc = gspread.authorize(creds)

        try:
            ss = gc.open_by_key(THREADS_POST_LOG_SS)
        except Exception as e:
            return {"ok": False, "reason": f"スプレッドシートを開けない: {e}"}

        # シート名一覧を確認
        sheet_names = [ws.title for ws in ss.worksheets()]

        # Beauty向け投稿候補シートを探す
        beauty_sheets = [s for s in sheet_names if "beauty" in s.lower() or "ビューティ" in s]
        stock_sheets  = [s for s in sheet_names if "stock" in s.lower() or "ストック" in s or "投稿" in s]

        results = {}

        # SNS_POST_STOCK シートを確認
        for candidate_sheet in ["SNS_POST_STOCK", "Threads投稿", "投稿ストック", "POST_STOCK"]:
            if candidate_sheet in sheet_names:
                try:
                    ws = ss.worksheet(candidate_sheet)
                    rows = ws.get_all_records()
                    beauty_rows = [r for r in rows
                                   if str(r.get("business", "")).lower() == "beauty"
                                   and str(r.get("status", "")).lower() not in ("投稿済み", "skip", "使用済み")]
                    results[candidate_sheet] = {
                        "total": len(rows),
                        "beauty_available": len(beauty_rows),
                    }
                except Exception as e:
                    results[candidate_sheet] = {"error": str(e)}

        return {
            "ok": True,
            "all_sheets": sheet_names,
            "beauty_sheets": beauty_sheets,
            "stock_sheets": stock_sheets,
            "results": results,
        }

    except FileNotFoundError:
        return {"ok": False, "reason": "認証ファイルが見つからない"}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def run():
    print("=" * 60)
    print("  Tree Beauty 在庫確認チェック")
    print("=" * 60)

    # 認証ファイルを探す
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not creds_path:
        # よくある場所を試す
        for p in [
            "/tmp/gcp-creds.json",
            os.path.expanduser("~/.config/gcloud/application_default_credentials.json"),
        ]:
            if os.path.exists(p):
                creds_path = p
                break

    if not creds_path or not os.path.exists(creds_path):
        print()
        print("  ⚠️  Google認証ファイルが見つかりません")
        print("  GOOGLE_APPLICATION_CREDENTIALS 環境変数を設定するか、")
        print("  Cloud Run環境でこのスクリプトを実行してください。")
        print()
        print("  代替手順:")
        print("  1. yu-holdings-ai の Cloud Run で以下を実行:")
        print(f"     GET /image-library-status?business=beauty")
        print(f"     GET /threads-auto-post-config")
        print()
        print("  IMAGE_LIBRARY ID:", IMAGE_LIBRARY_SS)
        print("  THREADS_POST_LOG ID:", THREADS_POST_LOG_SS)
        return {
            "image_library": {"ok": False, "reason": "認証ファイルなし"},
            "post_candidates": {"ok": False, "reason": "認証ファイルなし"},
        }

    print(f"\n  認証ファイル: {creds_path}")

    print("\n  [1/2] IMAGE_LIBRARY BEAUTY画像在庫確認中...")
    img_result = check_image_library(creds_path)
    if img_result.get("ok"):
        print(f"  BEAUTY総数: {img_result['total_beauty']}件")
        print(f"  GCS化済み: {img_result['gcs_ready']}件")
        print()
        print("  テーマ別GCS画像数:")
        for theme, count in sorted(img_result["theme_counts"].items()):
            min_stock = BEAUTY_IMAGE_MIN_STOCK.get(theme, 5)
            status = "✅" if count >= min_stock else ("⚠️" if count > 0 else "🚨")
            print(f"    {status} {theme:20s}: {count}枚（最低{min_stock}枚必要）")
    else:
        print(f"  ❌ 確認失敗: {img_result['reason']}")

    print("\n  [2/2] Threads投稿候補在庫確認中...")
    post_result = check_post_candidates(creds_path)
    if post_result.get("ok"):
        print(f"  全シート: {', '.join(post_result['all_sheets'])}")
        if post_result["results"]:
            for sheet, data in post_result["results"].items():
                if "error" in data:
                    print(f"  ❌ {sheet}: {data['error']}")
                else:
                    avail = data["beauty_available"]
                    status = "✅" if avail >= 5 else ("⚠️" if avail > 0 else "🚨")
                    print(f"  {status} {sheet}: Beauty候補 {avail}件 / 全{data['total']}件")
        else:
            print("  SNS_POST_STOCK / Threads投稿 シートが見つかりません")
            print("  Beauty投稿候補をスプレッドシートに追加する必要があります")
    else:
        print(f"  ❌ 確認失敗: {post_result['reason']}")

    print()
    print("=" * 60)
    return {"image_library": img_result, "post_candidates": post_result}


if __name__ == "__main__":
    run()
