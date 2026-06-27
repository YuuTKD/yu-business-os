"""
YU HOLDINGS AI Company Simulator - FastAPI Server
"""

import asyncio
import json
import random
import time
from datetime import datetime
from typing import Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from agents import AGENTS

app = FastAPI(title="YU HOLDINGS AI Company")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ─── WebSocket 接続管理 ───
connected_clients: Set[WebSocket] = set()

# ─── エージェント状態管理 ───
agent_states: dict = {}
agent_logs: dict = {}

def init_states():
    for ag in AGENTS:
        agent_states[ag["id"]] = {
            "status": "idle",  # idle | thinking | outputting
            "current_task": "",
            "task_count": 0,
            "last_active": datetime.now().strftime("%H:%M:%S"),
        }
        agent_logs[ag["id"]] = []

init_states()

# ─── ブロードキャスト ───
async def broadcast(data: dict):
    global connected_clients
    payload = json.dumps(data, ensure_ascii=False)
    dead: Set[WebSocket] = set()
    for ws in list(connected_clients):
        try:
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    connected_clients -= dead

# ─── シミュレーションループ（エージェントごと） ───
async def agent_loop(ag: dict):
    agent_id = ag["id"]
    tasks = ag["tasks"]
    lo, hi = ag["interval_range"]

    # 各エージェントの初期待機をランダムにずらす
    await asyncio.sleep(random.uniform(0.5, 5.0))

    while True:
        # ─ idle: 待機 ─
        idle_secs = random.uniform(lo, hi)
        agent_states[agent_id]["status"] = "idle"
        agent_states[agent_id]["current_task"] = ""
        await broadcast({
            "type": "status",
            "agent_id": agent_id,
            "status": "idle",
            "current_task": "",
        })
        await asyncio.sleep(idle_secs)

        # ─ thinking: 思考 ─
        task = random.choice(tasks)
        agent_states[agent_id]["status"] = "thinking"
        agent_states[agent_id]["current_task"] = task
        agent_states[agent_id]["last_active"] = datetime.now().strftime("%H:%M:%S")
        await broadcast({
            "type": "status",
            "agent_id": agent_id,
            "status": "thinking",
            "current_task": task,
        })
        await asyncio.sleep(random.uniform(2.0, 5.0))

        # ─ outputting: 出力 ─
        agent_states[agent_id]["status"] = "outputting"
        await broadcast({
            "type": "status",
            "agent_id": agent_id,
            "status": "outputting",
            "current_task": task,
        })
        await asyncio.sleep(random.uniform(1.5, 4.0))

        # ─ ログ追記 ─
        agent_states[agent_id]["task_count"] += 1
        count = agent_states[agent_id]["task_count"]
        ts = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{ts}] ✅ {task.replace('中...', '完了').replace('生成中', '生成完了').replace('送信中', '送信完了').replace('確認中', '確認完了').replace('分析中', '分析完了').replace('実行中', '実行完了').replace('選定中', '選定完了').replace('処理中', '処理完了').replace('集計中', '集計完了').replace('アップロード中', 'アップロード完了').replace('算出中', '算出完了').replace('計測中', '計測完了').replace('策定中', '策定完了').replace('更新中', '更新完了').replace('収集中', '収集完了').replace('モニタリング中', 'モニタリング完了')} (#{count})"
        agent_logs[agent_id].append(log_entry)
        if len(agent_logs[agent_id]) > 20:
            agent_logs[agent_id] = agent_logs[agent_id][-20:]

        await broadcast({
            "type": "log",
            "agent_id": agent_id,
            "log": log_entry,
            "task_count": count,
        })

# ─── サーバー起動時にシミュレーション開始 ───
@app.on_event("startup")
async def start_simulation():
    for ag in AGENTS:
        asyncio.create_task(agent_loop(ag))

# ─── WebSocket エンドポイント ───
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_clients.add(ws)

    # 接続時に現在の全状態を送信
    initial = {
        "type": "init",
        "agents": AGENTS,
        "states": agent_states,
        "logs": agent_logs,
    }
    await ws.send_text(json.dumps(initial, ensure_ascii=False))

    try:
        while True:
            await ws.receive_text()  # ping 受信待機
    except WebSocketDisconnect:
        connected_clients.discard(ws)

# ─── トップページ ───
@app.get("/", response_class=HTMLResponse)
async def index():
    with open("static/index.html", encoding="utf-8") as f:
        return f.read()
