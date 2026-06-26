import asyncio
from typing import Any


class ContextStore:
    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def set(self, context_id: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            self._store[context_id] = payload

    async def get(self, context_id: str) -> dict[str, Any] | None:
        async with self._lock:
            return self._store.get(context_id)


context_store = ContextStore()
