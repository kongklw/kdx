from pathlib import Path
import os
from fastapi import FastAPI

from .core.config import get_settings, load_env


BASE_DIR = Path(__file__).resolve().parent.parent
env_path =os.path.join(BASE_DIR, '.env')
load_env(env_path)

from .api.health import router as health_router
from .api.todo import create_todo_router
from .ws.voice_agent import create_voice_agent_router
from .ws.voice_agent_langchain import create_voice_agent_langchain_router

settings = get_settings()

app = FastAPI()
app.include_router(health_router)
app.include_router(create_todo_router(settings))
app.include_router(create_voice_agent_router(settings))
app.include_router(create_voice_agent_langchain_router(settings))
