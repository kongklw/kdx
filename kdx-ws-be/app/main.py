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
from .ws.voice_agent import create_voice_agent_router
from .ws.voice_agent_langchain import create_voice_agent_langchain_router
from .ws.rag_query import create_rag_query_router
from .ws.baby_assistant import create_baby_assistant_router
from .ws.ai_entrance import create_ai_entrance_router
from .ws.app_ai_entrance import create_app_ai_entrance_router

settings = get_settings()

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