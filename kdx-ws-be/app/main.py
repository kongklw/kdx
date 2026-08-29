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
from .api.todo import create_todo_router
from .api.face import create_face_router
from .api.access_stats import create_access_stats_router
from .ws.voice_agent import create_voice_agent_router
from .ws.voice_agent_langchain import create_voice_agent_langchain_router
from .ws.rag_query import create_rag_query_router
from .ws.baby_assistant import create_baby_assistant_router

settings = get_settings()

app = FastAPI()

# Add middleware
app.add_middleware(UserAccessLogMiddleware)

app.include_router(health_router)
app.include_router(create_todo_router(settings))
app.include_router(create_face_router(settings))
app.include_router(create_access_stats_router(settings))
app.include_router(create_voice_agent_router(settings))
app.include_router(create_voice_agent_langchain_router(settings))
app.include_router(create_rag_query_router(settings))
app.include_router(create_baby_assistant_router(settings))
