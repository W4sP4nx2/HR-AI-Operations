"""WebSocket connection manager for the live case/approval feed."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    """Tracks connected WebSocket clients and broadcasts events to them."""

    def __init__(self) -> None:
        """Initialise an empty connection registry."""
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection.

        Args:
            websocket: The incoming connection.
        """
        await websocket.accept()
        async with self._lock:
            self._connections.append(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a closed/closing connection from the registry.

        Args:
            websocket: The connection to drop.
        """
        async with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)

    async def broadcast(self, event: dict[str, Any]) -> None:
        """Send a JSON event to every connected client.

        Dead connections are pruned automatically.

        Args:
            event: A JSON-serialisable event payload.
        """
        async with self._lock:
            targets = list(self._connections)
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(event)
            except Exception:  # noqa: BLE001 - client likely disconnected
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    if ws in self._connections:
                        self._connections.remove(ws)


manager = ConnectionManager()
