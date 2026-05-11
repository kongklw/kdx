import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, WebSocket
from fastapi.websockets import WebSocketDisconnect

from ..core.config import Settings
from ..core.security import extract_token_from_headers, verify_jwt

logger = logging.getLogger(__name__)


def _as_json(text: str) -> Optional[Dict[str, Any]]:
    try:
        value = json.loads(text)
    except Exception:
        return None
    if isinstance(value, dict):
        return value
    return None


async def voice_agent_ws(ws: WebSocket, settings: Settings) -> None:
    user: Optional[Dict[str, Any]] = None
    if not settings.allow_anon_ws:
        token = ws.query_params.get("token") or extract_token_from_headers(
            ws.headers.get("authorization")
        )
        if not token:
            await ws.close(code=4401, reason="missing token")
            return
        try:
            user = verify_jwt(token, settings)
        except Exception as e:
            await ws.close(code=4401, reason=str(e))
            return

    await ws.accept()
    await ws.send_json(
        {
            "type": "connected",
            "user_id": (user or {}).get("user_id"),
            "message": "fastapi voice agent websocket ready",
        }
    )

    audio_bytes = 0
    try:
        while True:
            message = await ws.receive()
            msg_type = message.get("type")
            if msg_type == "websocket.receive":
                text = message.get("text")
                if text is not None:
                    payload = _as_json(text)
                    if payload is None:
                        await ws.send_json({"type": "text", "echo": text})
                        continue
                    t = payload.get("type")
                    if t == "ping":
                        await ws.send_json({"type": "pong"})
                    elif t == "text":
                        await ws.send_json({"type": "text", "echo": payload.get("text")})
                    elif t == "start":
                        audio_bytes = 0
                        await ws.send_json({"type": "started"})
                    elif t == "end":
                        await ws.send_json({"type": "ended", "audio_bytes": audio_bytes})
                    else:
                        await ws.send_json({"type": "ack", "data": payload})
                    continue

                data = message.get("bytes")
                if data is not None:
                    audio_bytes += len(data)
                    await ws.send_json({"type": "audio_ack", "received_bytes": len(data)})
            elif msg_type == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        return
    except Exception:
        logger.exception("voice agent ws unhandled exception")
        try:
            await ws.close(code=1011, reason="internal error")
        except Exception:
            return


def create_voice_agent_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/voice-agent")
    async def ws_voice_agent(ws: WebSocket) -> None:
        await voice_agent_ws(ws, settings)

    return router
