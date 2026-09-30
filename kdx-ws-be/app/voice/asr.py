"""
DashScope 流式 ASR (语音识别)

基于 paraformer-realtime-v2 模型, 通过 WebSocket 双工协议:
- 客户端发送 PCM 音频帧 (16kHz mono 16bit)
- 服务端返回 STTChunkEvent (部分识别) / STTOutputEvent (句尾定稿)

用法:
    asr = DashscopeRealtimeASR(api_key=..., model=..., url=..., ...)
    async for audio_chunk in audio_stream:
        await asr.send_audio(audio_chunk)
    await asr.finish()
    async for event in asr.receive_events():
        # event.type == "stt_chunk" | "stt_output"
        ...
"""

import asyncio
import contextlib
import json
from typing import Any, AsyncIterator, Dict, Optional
from uuid import uuid4

from loguru import logger

from ..utils.event import VoiceAgentEvent, STTChunkEvent, STTOutputEvent


class DashscopeRealtimeASR:
    """DashScope 实时流式语音识别客户端"""

    def __init__(
        self,
        *,
        api_key: Optional[str],
        model: str,
        url: str,
        sample_rate: int,
        language: Optional[str],
        max_sentence_silence_ms: int,
        semantic_punctuation_enabled: bool,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.url = url
        self.sample_rate = sample_rate
        self.language = language
        self.max_sentence_silence_ms = max_sentence_silence_ms
        self.semantic_punctuation_enabled = semantic_punctuation_enabled

        self._ws = None
        self._task_id = uuid4().hex
        self._started = asyncio.Event()
        self._done = asyncio.Event()
        self._queue: asyncio.Queue[object] = asyncio.Queue()
        self._close_sentinel = object()
        self._recv_task: Optional[asyncio.Task[None]] = None
        self._closed = False
        self._finished = False

        self._last_partial: str = ""
        self._last_final: str = ""

    async def _ensure_connection(self) -> None:
        if self._closed:
            raise RuntimeError("DashscopeRealtimeASR: Connection closed")
        if self._ws is not None:
            return
        if not self.api_key:
            raise RuntimeError("missing DASHSCOPE_API_KEY")

        import websockets
        import time as _time

        print(f"[ASR.net] connecting → {self.url} model={self.model}")
        _t0 = _time.monotonic()
        self._ws = await websockets.connect(
            self.url,
            additional_headers={"Authorization": f"Bearer {self.api_key}"},
        )
        print(f"[ASR.net] TCP/WS connected in {(_time.monotonic()-_t0)*1000:.0f}ms, sending run-task")
        await self._ws.send(json.dumps(self._run_task_instruction()))
        self._recv_task = asyncio.create_task(self._recv_loop())
        # 关键: 若服务端不回 task-started, 这里会永久卡住 — 加超时保护 + 日志
        try:
            await asyncio.wait_for(self._started.wait(), timeout=10.0)
            print(f"[ASR.net] ★ task-started, pipeline ready (setup {(_time.monotonic()-_t0)*1000:.0f}ms)")
        except asyncio.TimeoutError:
            print("[ASR.net] !!! never received task-started within 10s (检查 url/鉴权/run-task 参数)")
            raise RuntimeError("dashscope asr task-started timeout")

    def _run_task_instruction(self) -> Dict[str, Any]:
        parameters: Dict[str, Any] = {
            "format": "pcm",
            "sample_rate": self.sample_rate,
            "disfluency_removal_enabled": False,
            "max_sentence_silence": int(self.max_sentence_silence_ms),
            "semantic_punctuation_enabled": bool(self.semantic_punctuation_enabled),
            "punctuation_prediction_enabled": True,
            "inverse_text_normalization_enabled": True,
        }
        if self.language and self.model.startswith("paraformer-realtime-v2"):
            parameters["language_hints"] = [self.language]

        return {
            "header": {
                "action": "run-task",
                "task_id": self._task_id,
                "streaming": "duplex",
            },
            "payload": {
                "task_group": "audio",
                "task": "asr",
                "function": "recognition",
                "model": self.model,
                "parameters": parameters,
                "input": {},
            },
        }

    def _finish_task_instruction(self) -> Dict[str, Any]:
        return {
            "header": {
                "action": "finish-task",
                "task_id": self._task_id,
                "streaming": "duplex",
            },
            "payload": {"input": {}},
        }

    async def _recv_loop(self) -> None:
        ws = self._ws
        if ws is None:
            return

        try:
            while True:
                raw = await ws.recv()
                if not isinstance(raw, str):
                    continue
                msg = _as_json(raw) or {}
                header = msg.get("header") or {}
                event = header.get("event")
                if event == "task-started":
                    self._started.set()
                    continue
                if event == "task-failed":
                    self._started.set()
                    error_code = header.get("error_code")
                    error_message = (
                        header.get("error_message") or "dashscope asr task failed"
                    )
                    print(f"[ASR.net] !!! task-failed code={error_code} msg={error_message}")
                    if error_code == "NO_VALID_AUDIO_ERROR":
                        logger.info(
                            f"DashScope ASR task failed due to no audio: {error_message}"
                        )
                        self._finished = True
                        return
                    raise RuntimeError(error_message)
                if event == "result-generated":
                    payload = msg.get("payload") or {}
                    output = payload.get("output") or {}
                    sentence = output.get("sentence") or {}
                    heartbeat = sentence.get("heartbeat")
                    if heartbeat:
                        continue
                    text = sentence.get("text") or ""
                    if not isinstance(text, str) or not text.strip():
                        continue

                    if text != self._last_partial:
                        self._last_partial = text
                        await self._queue.put(STTChunkEvent.create(text))

                    sentence_end = bool(sentence.get("sentence_end"))
                    end_time = sentence.get("end_time")
                    is_final = sentence_end or end_time is not None
                    print(
                        f"[ASR.net] result-generated text={text!r} "
                        f"sentence_end={sentence_end} end_time={end_time} final={is_final}"
                    )
                    if is_final and text != self._last_final:
                        self._last_final = text
                        self._last_partial = ""
                        await self._queue.put(STTOutputEvent.create(text))
                    continue
                if event == "task-finished":
                    print("[ASR.net] task-finished")
                    self._started.set()
                    break
                # 其他未识别事件, 打印便于排查
                print(f"[ASR.net] unhandled event={event} header={header}")
        except asyncio.CancelledError:
            raise
        except Exception:
            print("[ASR.net] recv loop exception:")
            logger.exception("dashscope asr recv loop failed")
        finally:
            self._done.set()
            await self._queue.put(self._close_sentinel)
            with contextlib.suppress(Exception):
                await ws.close()

    async def send_audio(self, audio: bytes) -> None:
        if self._closed or self._finished:
            return
        await self._ensure_connection()
        ws = self._ws
        if ws is None:
            return
        await ws.send(audio)

    async def finish(self) -> None:
        if self._closed or self._finished:
            return
        self._finished = True
        ws = self._ws
        if ws is None:
            await self._queue.put(self._close_sentinel)
            return
        with contextlib.suppress(Exception):
            await ws.send(json.dumps(self._finish_task_instruction()))
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._done.wait(), timeout=2.0)

    async def receive_events(self) -> AsyncIterator[VoiceAgentEvent]:
        while True:
            item = await self._queue.get()
            if item is self._close_sentinel:
                return
            yield item

    async def close(self) -> None:
        self._closed = True
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(self._recv_task, timeout=2.0)
        ws = self._ws
        if ws is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(ws.close(), timeout=2.0)
        await self._queue.put(self._close_sentinel)


def _as_json(text: str) -> Optional[Dict[str, Any]]:
    try:
        value = json.loads(text)
    except Exception:
        return None
    return value if isinstance(value, dict) else None
