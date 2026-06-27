#!/bin/bash
cd "$(dirname "$0")"

# 依存チェック
python3 -c "import fastapi, uvicorn" 2>/dev/null || pip3 install fastapi uvicorn websockets -q

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║        YU HOLDINGS AI Company Simulator              ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "  ブラウザで確認: http://localhost:8765"
echo "  終了: Ctrl+C"
echo ""

# ブラウザを1秒後に開く
(sleep 1.5 && open http://localhost:8765) &

# サーバー起動
python3 -m uvicorn server:app --host 0.0.0.0 --port 8765 --reload
