import logging
import json
from typing import Dict, Set, Optional
from datetime import datetime
from collections import defaultdict

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class WebSocketManager:
    def __init__(self):
        self._connections: Dict[str, Set[WebSocket]] = defaultdict(set)
        self._client_info: Dict[WebSocket, Dict] = {}

    async def connect(self, websocket: WebSocket, session_id: str, client_info: Dict = None):
        await websocket.accept()
        self._connections[session_id].add(websocket)
        self._client_info[websocket] = {
            "session_id": session_id,
            "connected_at": datetime.utcnow().isoformat(),
            "client_info": client_info or {}
        }
        logger.info(f"WebSocket connected: session_id={session_id}, total={len(self._connections[session_id])}")

    def disconnect(self, websocket: WebSocket, session_id: str):
        self._connections[session_id].discard(websocket)
        self._client_info.pop(websocket, None)
        logger.info(f"WebSocket disconnected: session_id={session_id}, remaining={len(self._connections[session_id])}")

    async def send_to_session(self, session_id: str, message: Dict):
        if session_id in self._connections:
            dead_connections = set()
            for connection in self._connections[session_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"Error sending to websocket: {str(e)}")
                    dead_connections.add(connection)
            for dead in dead_connections:
                self.disconnect(dead, session_id)

    async def send_to_client(self, websocket: WebSocket, message: Dict):
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Error sending to specific client: {str(e)}")

    async def broadcast(self, message: Dict):
        for session_id in self._connections:
            await self.send_to_session(session_id, message)

    def get_session_clients(self, session_id: str) -> int:
        return len(self._connections.get(session_id, set()))

    def get_all_sessions(self) -> list:
        return list(self._connections.keys())

    async def handle_ping(self, websocket: WebSocket):
        await websocket.send_json({
            "type": "pong",
            "timestamp": datetime.utcnow().isoformat()
        })


ws_manager = WebSocketManager()
