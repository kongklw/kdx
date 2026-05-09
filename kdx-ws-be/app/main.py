from pathlib import Path

from fastapi import FastAPI

from .core.config import get_settings, load_env

load_env(Path(__file__).resolve().parents[2] / "kdx-be" / ".env")

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
