"""WebSocket 实时进度推送
前端通过 WebSocket 连接实时获取任务进度，避免轮询。
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, Set
from uuid import UUID

router = APIRouter()
logger = logging.getLogger(__name__)


class ConnectionManager:
    """WebSocket 连接管理器"""
    def __init__(self):
        # project_id -> set of WebSocket
        self.connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, project_id: str):
        await websocket.accept()
        if project_id not in self.connections:
            self.connections[project_id] = set()
        self.connections[project_id].add(websocket)

    def disconnect(self, websocket: WebSocket, project_id: str):
        if project_id in self.connections:
            self.connections[project_id].discard(websocket)
            if not self.connections[project_id]:
                del self.connections[project_id]

    async def broadcast(self, project_id: str, message: dict):
        if project_id not in self.connections:
            return
        dead = []
        for ws in self.connections[project_id]:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connections[project_id].discard(ws)


manager = ConnectionManager()

# 保存主事件循环引用，供后台线程中的广播使用
_main_loop = None


def set_main_loop(loop):
    """在应用启动时保存主事件循环引用"""
    global _main_loop
    _main_loop = loop


@router.websocket("/ws/tasks/{project_id}")
async def task_progress_ws(websocket: WebSocket, project_id: str):
    """WebSocket 端点 - 实时推送任务进度"""
    await manager.connect(websocket, project_id)
    try:
        while True:
            # 保持连接，接收心跳
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong", "timestamp": str(datetime.now(timezone.utc))})
    except WebSocketDisconnect:
        manager.disconnect(websocket, project_id)


def broadcast_task_update(project_id: str, task_id: str, task_type: str, status: str, progress: int, result: dict = None):
    """同步广播任务更新（从后台任务调用）

    后台任务是同步函数，在线程池中执行，没有自己的事件循环。
    使用 run_coroutine_threadsafe 将广播协程调度到主事件循环执行。
    """
    message = {
        "type": "task_update",
        "task_id": task_id,
        "task_type": task_type,
        "status": status,
        "progress": progress,
        "result": result,
        "timestamp": str(datetime.now(timezone.utc)),
    }
    if _main_loop is None:
        logger.debug(f"WebSocket 广播跳过（主循环未初始化）: task={task_id} status={status}")
        return
    try:
        asyncio.run_coroutine_threadsafe(manager.broadcast(project_id, message), _main_loop)
    except Exception as e:
        logger.warning(f"WebSocket 广播失败: {e}")
