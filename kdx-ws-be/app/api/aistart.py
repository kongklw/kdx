"""aistart 应用端点迁移 (Django aistart/urls.py)

URL 与 Django 完全一致:
  POST /ai/ask -> aistart.views.OpenAIView (langgraph 聊天, thread_id 会话记忆)

已与 Django 项目内部模块解耦, 详见 services/aistart_service.py 顶部说明。
"""
import uuid

from fastapi import APIRouter

from ..core.config import Settings
from ..schemas.aistart import AiAskRequest, AiAskResponse
from ..services.aistart_service import AistartChatService


def create_aistart_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/ai", tags=["aistart"])
    service = AistartChatService()

    @router.post("/ask", response_model=AiAskResponse)
    def ask(body: AiAskRequest):
        """对话; 使用同步 def: LLM 调用为长阻塞操作, 交由线程池执行避免卡死事件循环"""
        thread_id = body.thread_id or ""
        if len(thread_id) == 0:
            thread_id = str(uuid.uuid4())
        msg, thread_id = service.ask(body.content, thread_id)
        return {"code": 200, "data": {"msg": msg, "thread_id": thread_id}, "msg": "ok"}

    return router
