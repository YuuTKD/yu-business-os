"""
YU BUSINESS OS - Google認証ローダー

Cloud Run環境では GOOGLE_CREDENTIALS_B64 から認証情報を展開する。
ローカル開発では credentials.json を直接使用する。
"""

import os, base64, json, tempfile

_cached_path: str | None = None


def load_google_credentials() -> str | None:
    global _cached_path
    if _cached_path and os.path.exists(_cached_path):
        return _cached_path

    # Cloud Run: B64エンコードされた認証情報を展開
    b64 = os.getenv("GOOGLE_CREDENTIALS_B64", "")
    if b64:
        try:
            decoded = base64.b64decode(b64)
            tmp = tempfile.NamedTemporaryFile(
                suffix="_google_creds.json", delete=False, mode="wb"
            )
            tmp.write(decoded)
            tmp.flush()
            _cached_path = tmp.name
            return _cached_path
        except Exception as e:
            print(f"[credentials_loader] B64デコード失敗: {e}")

    # ローカル: credentials.json を探す
    candidates = [
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "credentials.json"),
        os.path.join(os.path.dirname(__file__), "..", "credentials.json"),
        os.path.join(os.path.expanduser("~"), "credentials.json"),
    ]
    for path in candidates:
        if os.path.exists(path):
            _cached_path = os.path.abspath(path)
            return _cached_path

    print("[credentials_loader] Google認証情報が見つかりません")
    return None
