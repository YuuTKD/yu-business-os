"""
GBP アカウント・Location ID 取得スクリプト（新旧API両対応）
"""
import json, ssl, urllib.request, urllib.parse, time

TOKENS_PATH = "/Users/tokudayuya/yu-business-os/backups/gbp_oauth_tokens.json"
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

def get_access_token(tokens: dict) -> str:
    data = urllib.parse.urlencode({
        "client_id":     tokens["client_id"],
        "client_secret": tokens["client_secret"],
        "refresh_token": tokens["refresh_token"],
        "grant_type":    "refresh_token",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, context=ssl_ctx) as resp:
        return json.loads(resp.read())["access_token"]

def api_get(url: str, access_token: str):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    try:
        with urllib.request.urlopen(req, context=ssl_ctx) as resp:
            return json.loads(resp.read()), None
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return None, f"HTTP {e.code}: {body[:300]}"
    except Exception as e:
        return None, str(e)

if __name__ == "__main__":
    with open(TOKENS_PATH) as f:
        tokens = json.load(f)

    print("Access Token取得中...")
    access_token = get_access_token(tokens)
    print("✅ Access Token取得成功\n")

    # --- 新API ---
    print("=== 新API: mybusinessaccountmanagement ===")
    data, err = api_get(
        "https://mybusinessaccountmanagement.googleapis.com/v1/accounts",
        access_token,
    )
    if data:
        accounts_new = data.get("accounts", [])
        print(f"✅ アカウント数: {len(accounts_new)}")
        for acc in accounts_new:
            print(f"  {acc.get('name')} | {acc.get('accountName')}")
    else:
        print(f"❌ {err}")
        accounts_new = []

    time.sleep(2)

    # --- 旧API v4 ---
    print("\n=== 旧API v4: mybusiness ===")
    data_v4, err_v4 = api_get(
        "https://mybusiness.googleapis.com/v4/accounts",
        access_token,
    )
    if data_v4:
        accounts_v4 = data_v4.get("accounts", [])
        print(f"✅ アカウント数: {len(accounts_v4)}")
        for acc in accounts_v4:
            print(f"  name: {acc.get('name')}")
            print(f"  accountName: {acc.get('accountName')}")
            acc_name = acc.get("name")
            time.sleep(1)
            loc_data, loc_err = api_get(
                f"https://mybusiness.googleapis.com/v4/{acc_name}/locations",
                access_token,
            )
            if loc_data:
                locs = loc_data.get("locations", [])
                print(f"  ロケーション数: {len(locs)}")
                for loc in locs:
                    print(f"    name:      {loc.get('name')}")
                    print(f"    locationName: {loc.get('locationName')}")
                    print(f"    storeCode: {loc.get('storeCode')}")
            else:
                print(f"  ロケーション取得失敗: {loc_err}")
    else:
        print(f"❌ {err_v4}")
        accounts_v4 = []

    # --- accountManagement accounts → businessInformation locations ---
    if accounts_new:
        print("\n=== 新API: businessInformation locations ===")
        for acc in accounts_new:
            acc_name = acc.get("name")
            time.sleep(2)
            loc_data, loc_err = api_get(
                f"https://mybusinessbusinessinformation.googleapis.com/v1/{acc_name}/locations?readMask=name,title,storeCode",
                access_token,
            )
            if loc_data:
                locs = loc_data.get("locations", [])
                print(f"✅ {acc.get('accountName')} ロケーション数: {len(locs)}")
                for loc in locs:
                    print(f"  name:  {loc.get('name')}")
                    print(f"  title: {loc.get('title')}")
            else:
                print(f"❌ {acc.get('accountName')}: {loc_err}")
