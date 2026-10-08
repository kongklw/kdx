from pathlib import Path
import os
from fastapi import FastAPI

from .core.config import get_settings, load_env
from .core.logging import setup_logging
from .middleware.access_log import UserAccessLogMiddleware


BASE_DIR = Path(__file__).resolve().parent.parent
env_path = os.path.join(BASE_DIR, '.env')
load_env(env_path)

# Initialize logging configuration
log_level = os.getenv("LOG_LEVEL", "INFO")
setup_logging(log_level=log_level, log_dir=os.path.join(BASE_DIR, "logs"))

from .api.health import router as health_router
from .api.metrics import router as metrics_router
from .api.todo import create_todo_router
from .api.face import create_face_router
from .api.access_stats import create_access_stats_router
from .api.users import create_users_router
from .api.sport import create_sport_router
from .api.k8s import create_k8s_router
from .api.aistart import create_aistart_router
from .api.baby import create_baby_router
from .api.file_upload import create_file_upload_router
from .api.rag_http import create_rag_http_router
from .api.ai_chat import create_ai_chat_router
from .ws.voice_agent import create_voice_agent_router
from .ws.voice_agent_langchain import create_voice_agent_langchain_router
from .ws.rag_query import create_rag_query_router
from .ws.baby_assistant import create_baby_assistant_router
from .ws.ai_entrance import create_ai_entrance_router
from .ws.app_ai_entrance import create_app_ai_entrance_router

settings = get_settings()

# checkpointer 初始化 (必须在 include_router 之前: 路由工厂 import 期编图)
from .assistant.graph import init_graph_checkpointer
_checkpointer_kind = init_graph_checkpointer()

app = FastAPI()

# Add middleware
app.add_middleware(UserAccessLogMiddleware)


@app.on_event("startup")
async def on_startup() -> None:
    """启动钩子: 后台监听知识库变更广播, 联动刷新 BM25 索引"""
    from .rag.service import start_invalidate_listener
    start_invalidate_listener()


app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(create_todo_router(settings))
app.include_router(create_face_router(settings))
app.include_router(create_access_stats_router(settings))
app.include_router(create_voice_agent_router(settings))
app.include_router(create_voice_agent_langchain_router(settings))
app.include_router(create_rag_query_router(settings))
app.include_router(create_baby_assistant_router(settings))
app.include_router(create_ai_entrance_router(settings))
app.include_router(create_app_ai_entrance_router(settings))
# ── kdx-be (Django) 功能迁移: URL 路径与原项目保持一致 ──
app.include_router(create_users_router(settings))    # /token/, /user/*
app.include_router(create_sport_router(settings))    # /sport/*
app.include_router(create_k8s_router(settings))      # /k8s/*
app.include_router(create_aistart_router(settings))  # /ai/*
app.include_router(create_baby_router(settings))     # /baby/*
app.include_router(create_file_upload_router(settings))  # /file/*, /media/*
app.include_router(create_rag_http_router(settings))     # /rag/*
app.include_router(create_ai_chat_router(settings))      # /api/v1/ai/chat-history