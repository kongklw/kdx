"""AI 聊天历史 HTTP API。

GET /api/v1/ai/chat-history?limit=50 — 返回当前用户最近 N 条聊天记录
"""
from fastapi import APIRouter, Query, Request

from ..core.config import Settings
from ..api.deps import require_user_id
from ..services.chat_history_service import ChatHistoryService


def create_ai_chat_router(settings: Settings):
    router = APIRouter(prefix="/api/v1/ai", tags=["ai-chat"])
    svc = ChatHistoryService.get_instance(settings.redis_url)

    @router.get("/chat-history")
    async def get_chat_history(request: Request, limit: int = Query(50, ge=1, le=500)):
        uid = require_user_id(request, settings)
        messages = await svc.get_recent(uid, limit)
        return {"code": 200, "data": {"messages": messages}, "msg": "ok"}

    return router
