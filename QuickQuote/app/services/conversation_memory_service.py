from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class ConversationMemoryService:
    def __init__(self) -> None:
        self._table_ready = False

    async def ensure_table(self, session: AsyncSession) -> None:
        if self._table_ready:
            return
        ddl = """
        CREATE TABLE IF NOT EXISTS conversation_turns (
            id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            context_id VARCHAR(64) NOT NULL,
            turn_index BIGINT NOT NULL,
            role VARCHAR(16) NOT NULL,
            content TEXT NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            KEY idx_context_id_id (context_id, id)
        )
        """
        await session.execute(text(ddl))
        await session.commit()
        self._table_ready = True

    async def append_turn(
        self,
        session: AsyncSession,
        context_id: str,
        role: str,
        content: str,
    ) -> None:
        await self.ensure_table(session)
        turn_sql = text(
            "SELECT COALESCE(MAX(turn_index), 0) + 1 AS next_turn "
            "FROM conversation_turns WHERE context_id = :context_id"
        )
        result = await session.execute(turn_sql, {"context_id": context_id})
        next_turn = int(result.scalar_one())
        insert_sql = text(
            "INSERT INTO conversation_turns(context_id, turn_index, role, content) "
            "VALUES(:context_id, :turn_index, :role, :content)"
        )
        await session.execute(
            insert_sql,
            {
                "context_id": context_id,
                "turn_index": next_turn,
                "role": role,
                "content": content[:4000],
            },
        )
        await session.commit()

    async def get_recent_turns(
        self, session: AsyncSession, context_id: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        await self.ensure_table(session)
        query_sql = text(
            "SELECT role, content, turn_index, created_at "
            "FROM conversation_turns "
            "WHERE context_id = :context_id "
            "ORDER BY id DESC LIMIT :limit"
        )
        rows = (
            await session.execute(query_sql, {"context_id": context_id, "limit": max(1, min(limit, 50))})
        ).mappings().all()
        history = [dict(row) for row in rows]
        history.reverse()
        return history


conversation_memory_service = ConversationMemoryService()
