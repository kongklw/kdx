from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.responses import JSONResponse

from .config import get_settings, load_env
from .voice_ws import voice_agent_ws

load_env(Path(__file__).resolve().parents[2] / "kdemo" / ".env")
settings = get_settings()

app = FastAPI()


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"ok": True})


@app.websocket("/ws/voice-agent")
async def ws_voice_agent(ws: WebSocket) -> None:
    await voice_agent_ws(ws, settings)
