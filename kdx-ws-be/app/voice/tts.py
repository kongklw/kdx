"""
DashScope 流式 TTS (语音合成)

基于 qwen3-tts-vd 模型, 通过 WebSocket 双工协议:
- 客户端发送文本 (send_text)
- 服务端返回 PCM 音频流 (24kHz mono 16bit, base64 编码)

支持 fallback 模型: 主模型失败时自动降级到备用模型。
输出通过 TTSChunkEvent 事件流式推送, 每个 chunk ≤ 16KB。
"""

import asyncio
import base64
import contextlib
import json
from typing import AsyncIterator, Optional
from urllib.parse import quote

from loguru import logger

from ..utils.event import VoiceAgentEvent, TTSChunkEvent


class DashscopeQwenTtsRealtime:
    """DashScope 实时流式语音合成客户端"""

    def __init__(
        self,
        *,
        api_key: Optional[str],
        model: str,
        voice: str,
        url: str,
        response_format: str,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.url = url
        self.response_format = response_format
        self._queue: asyncio.Queue[object] = asyncio.Queue()
        self._task: Optional[asyncio.Task[None]] = None
        self._closed = False
        self._close_sentinel = object()

    async def send_text(self, text: str) -> None:
        if self._closed:
            return
        if not self.api_key:
            raise RuntimeError("missing DASHSCOPE_API_KEY")

        # 取消上一个合成任务 (支持打断: 用户说话时停止 TTS)
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        while not self._queue.empty():
            with contextlib.suppress(Exception):
                self._queue.get_nowait()

        self._task = asyncio.create_task(self._run(text))

    async def _run(self, text: str) -> None:
        try:
            async for audio in self._synthesize(text):
                for event in _split_tts_chunk_events(audio):
                    await self._queue.put(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            fallback_model = _fallback_tts_model(self.model)
            if fallback_model and fallback_model != self.model:
                try:
                    async for audio in self._synthesize(text, model_override=fallback_model):
                        for event in _split_tts_chunk_events(audio):
                            await self._queue.put(event)
                    return
                except Exception:
                    logger.exception("dashscope qwen tts synthesis failed (fallback model)")
                    return
            logger.exception("dashscope qwen tts synthesis failed")

    async def _synthesize(
        self, text: str, *, model_override: Optional[str] = None
    ) -> AsyncIterator[bytes]:
        import websockets

        model = model_override or self.model
        url = self.url
        if "?" not in url:
            url = f"{url}?model={quote(model)}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with websockets.connect(url, extra_headers=headers) as websocket:
            while True:
                raw = await websocket.recv()
                event = json.loads(raw)
                if event.get("type") == "session.created":
                    break
                if event.get("type") == "error":
                    raise RuntimeError(str(event))

            await websocket.send(
                json.dumps(
                    {
                        "type": "session.update",
                        "session": {
                            "voice": self.voice,
                            "response_format": self.response_format,
                        },
                    }
                )
            )
            await websocket.send(
                json.dumps(
                    {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": text}],
                        },
                    }
                )
            )
            await websocket.send(
                json.dumps(
                    {"type": "response.create", "response": {"modalities": ["audio"]}}
                )
            )

            while True:
                raw = await websocket.recv()
                event = json.loads(raw)
                event_type = event.get("type")
                if event_type == "response.audio.delta":
                    delta = event.get("delta")
                    if isinstance(delta, str) and delta:
                        yield base64.b64decode(delta)
                        continue
                    if isinstance(delta, dict):
                        audio_data = (
                            (delta.get("audio") or {}).get("data")
                            if isinstance(delta.get("audio"), dict)
                            else None
                        )
                        if isinstance(audio_data, str) and audio_data:
                            yield base64.b64decode(audio_data)
                            continue
                if event_type == "response.done":
                    break
                if event_type == "error":
                    raise RuntimeError(str(event))

    async def receive_events(self) -> AsyncIterator[VoiceAgentEvent]:
        while True:
            item = await self._queue.get()
            if item is self._close_sentinel:
                return
            yield item

    async def close(self) -> None:
        self._closed = True
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        await self._queue.put(self._close_sentinel)


def _fallback_tts_model(model: str) -> Optional[str]:
    if not model:
        return None
    if model == "qwen3-tts-vd-2026-01-26":
        return "qwen3-tts-vd-realtime-2026-01-15"
    return None


def _split_tts_chunk_events(audio: bytes) -> list[TTSChunkEvent]:
    chunk_size = 16_384
    if not audio:
        return []
    if len(audio) <= chunk_size:
        return [TTSChunkEvent.create(audio)]
    return [
        TTSChunkEvent.create(audio[i : i + chunk_size])
        for i in range(0, len(audio), chunk_size)
    ]
