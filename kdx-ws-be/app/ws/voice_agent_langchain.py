import json
import logging
import base64
from uuid import uuid4
from typing import Any, Dict, Optional, AsyncIterator
from fastapi import APIRouter, WebSocket
from fastapi.websockets import WebSocketDisconnect
import asyncio
import os
import contextlib
from urllib.parse import quote

from ..core.config import Settings
from ..core.security import extract_token_from_headers, verify_jwt
from ..utils.event import (
    event_to_dict,
    VoiceAgentEvent,
    STTChunkEvent,
    STTOutputEvent,
    AgentChunkEvent,
    ToolCallEvent,
    ToolResultEvent,
    AgentEndEvent,
    TTSChunkEvent,
)
from ..utils.merge_things import merge_async_iters

from langchain_core.runnables import RunnableGenerator

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

try:
    from langgraph.prebuilt import create_react_agent
except Exception:
    create_react_agent = None
try:
    from langchain.agents import create_agent
except Exception:
    create_agent = None

# from dotenv import load_dotenv
# load_dotenv()

logger = logging.getLogger(__name__)


@tool
def add_to_order(item: str, quantity: int) -> str:
    """Add an item to the customer's sandwich order."""
    return f"Added {quantity} x {item} to the order."


@tool
def confirm_order(order_summary: str) -> str:
    """Confirm the final order with the customer."""
    return f"Order confirmed: {order_summary}. Sending to kitchen."


system_prompt = """
You are a helpful sandwich shop assistant. Your goal is to take the user's order.
Be concise and friendly.

Available toppings: lettuce, tomato, onion, pickles, mayo, mustard.
Available meats: turkey, ham, roast beef.
Available cheeses: swiss, cheddar, provolone.
"""

llm_model_name = os.getenv("VOICE_LC_LLM_MODEL") or "qwen3.5-plus"
api_key = os.getenv("DASHSCOPE_API_KEY")
debug_ws = (os.getenv("VOICE_LC_DEBUG_WS") or "").lower() in {"1", "true", "yes"}
llm_model = ChatOpenAI(
    # model="qwen-vl-max-latest",
    model=llm_model_name,
    api_key=api_key,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    temperature=0,
    streaming=True
)


class DashscopeRealtimeASR:
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

        self._ws = await websockets.connect(
            self.url,
            additional_headers={"Authorization": f"Bearer {self.api_key}"},
        )
        await self._ws.send(json.dumps(self._run_task_instruction()))
        self._recv_task = asyncio.create_task(self._recv_loop())
        await self._started.wait()

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
            "header": {"action": "run-task", "task_id": self._task_id, "streaming": "duplex"},
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
            "header": {"action": "finish-task", "task_id": self._task_id, "streaming": "duplex"},
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
                    raise RuntimeError(header.get("error_message") or "dashscope asr task failed")
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
                    if is_final and text != self._last_final:
                        self._last_final = text
                        self._last_partial = ""
                        await self._queue.put(STTOutputEvent.create(text))
                    continue
                if event == "task-finished":
                    self._started.set()
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
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
        await self._ensure_connection()
        ws = self._ws
        if ws is None:
            return
        self._finished = True
        with contextlib.suppress(Exception):
            await ws.send(json.dumps(self._finish_task_instruction()))
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._done.wait(), timeout=2.0)

    async def receive_events(self) -> AsyncIterator[VoiceAgentEvent]:
        while True:
            item = await self._queue.get()
            if item is self._close_sentinel:
                return
            yield item  # type: ignore[misc]

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


class DashscopeQwenTtsRealtime:
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

    async def _synthesize(self, text: str, *, model_override: Optional[str] = None) -> AsyncIterator[bytes]:
        import websockets

        model = model_override or self.model
        url = self.url
        if "?" not in url:
            url = f"{url}?model={quote(model)}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with websockets.connect(url, additional_headers=headers) as websocket:
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
                json.dumps({"type": "response.create", "response": {"modalities": ["audio"]}})
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
                            ((delta.get("audio") or {}).get("data"))
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
            yield item  # type: ignore[misc]

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
        TTSChunkEvent.create(audio[i: i + chunk_size])
        for i in range(0, len(audio), chunk_size)
    ]


agent = None
if create_agent is not None:
    try:
        agent = create_agent(
            model=llm_model,
            tools=[add_to_order, confirm_order],
            system_prompt=system_prompt,
            checkpointer=InMemorySaver(),
        )
    except Exception:
        agent = None

if agent is None and create_react_agent is not None:
    try:
        agent = create_react_agent(
            llm_model,
            tools=[add_to_order, confirm_order],
            checkpointer=InMemorySaver(),
            state_modifier=system_prompt,
        )
    except Exception:
        agent = None


def _as_json(text: str) -> Optional[Dict[str, Any]]:
    try:
        value = json.loads(text)
    except Exception:
        return None
    if isinstance(value, dict):
        return value
    return None


async def _stt_stream(audio_stream: AsyncIterator[bytes]) -> AsyncIterator[VoiceAgentEvent]:
    """
    Transform stream: Audio (Bytes) → Voice Events (VoiceAgentEvent)

    This function takes a stream of audio chunks and sends them to DashScope for STT.

    It uses a producer-consumer pattern where:
    - Producer: A background task reads audio chunks from audio_stream and sends
      them to AssemblyAI via WebSocket. This runs concurrently with the consumer,
      allowing transcription to begin before all audio has arrived.
    - Consumer: The main coroutine receives transcription events from AssemblyAI
      and yields them downstream. Events include both partial results (stt_chunk)
      and final transcripts (stt_output).

    Args:
        audio_stream: Async iterator of PCM audio bytes (16-bit, mono, 16kHz)

    Yields:
        STT events (stt_chunk for partials, stt_output for final transcripts)
    """
    # stt_model_name = os.getenv("VOICE_LC_STT_MODEL") or "paraformer-realtime-v2"
    stt_model_name = os.getenv("VOICE_LC_STT_MODEL") or "paraformer-realtime-v2"
    stt_url = os.getenv("VOICE_LC_STT_URL") or "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
    stt_language = os.getenv("VOICE_LC_STT_LANGUAGE") or "zh"
    stt_sample_rate = int(os.getenv("VOICE_LC_STT_SAMPLE_RATE") or "16000")
    stt_max_sentence_silence_ms = int(os.getenv("VOICE_LC_STT_MAX_SILENCE_MS") or "400")
    stt_semantic_punctuation_enabled = (os.getenv("VOICE_LC_STT_SEMANTIC_PUNC") or "").lower() == "true"
    if "8k" in stt_model_name and stt_sample_rate != 8000:
        logger.warning("VOICE_LC_STT_MODEL=%s requires 8000Hz, overriding sample_rate=%s -> 8000", stt_model_name,
                       stt_sample_rate)
        stt_sample_rate = 8000

    stt = DashscopeRealtimeASR(
        api_key=api_key,
        model=stt_model_name,
        url=stt_url,
        sample_rate=stt_sample_rate,
        language=stt_language,
        max_sentence_silence_ms=stt_max_sentence_silence_ms,
        semantic_punctuation_enabled=stt_semantic_punctuation_enabled,
    )

    async def send_audio():
        try:
            async for audio_chunk in audio_stream:

                logger.info("stt.send_audio bytes=%s", len(audio_chunk))
                await stt.send_audio(audio_chunk)

        finally:
            with contextlib.suppress(Exception):
                await stt.finish()
            with contextlib.suppress(Exception):
                await stt.close()

    send_task = asyncio.create_task(send_audio())

    try:
        async for event in stt.receive_events():

            logger.info("stt.event type=%s", getattr(event, "type", None))
            yield event
    finally:
        with contextlib.suppress(asyncio.CancelledError):
            send_task.cancel()
            await send_task
        with contextlib.suppress(Exception):
            await stt.close()


async def _agent_stream(event_stream: AsyncIterator[VoiceAgentEvent]) -> AsyncIterator[VoiceAgentEvent]:
    """
      Transform stream: Voice Events → Voice Events (with Agent Responses)

      This function takes a stream of upstream voice agent events and processes them.
      When an stt_output event arrives, it passes the transcript to the LangChain agent.
      The agent streams back its response tokens as agent_chunk events.
      Tool calls and results are also emitted as separate events.
      All other upstream events are passed through unchanged.

      The passthrough pattern ensures downstream stages (like TTS) can observe all
      events in the pipeline, not just the ones this stage produces. This enables
      features like displaying partial transcripts while the agent is thinking.

      Args:
          event_stream: An async iterator of upstream voice agent events

      Yields:
          All upstream events plus agent_chunk, tool_call, and tool_result events
      """

    # Generate a unique thread ID for this conversation session
    # This allows the agent to maintain conversation context across multiple turns
    # using the checkpointer (InMemorySaver) configured in the agent
    thread_id = str(uuid4())
    async for event in event_stream:
        yield event
        logger.info(f'agent stream event --> {event}')
        if event.type == 'stt_output':
            if agent is not None and hasattr(agent, "astream"):
                stream = agent.astream(
                    {"messages": [HumanMessage(content=event.transcript)]},
                    {"configurable": {"thread_id": thread_id}},
                    stream_mode="messages"
                )

                async for message, metadata in stream:
                    if isinstance(message, AIMessage):
                        yield AgentChunkEvent.create(message.text)

                        if hasattr(message, 'tool_calls') and message.tool_calls:
                            for tool_call in message.tool_calls:
                                yield ToolCallEvent.create(
                                    id=tool_call.get("id", str(uuid4())),
                                    name=tool_call.get("name", "unknown"),
                                    args=tool_call.get("args", {})
                                )

                    if isinstance(message, ToolMessage):
                        yield ToolResultEvent.create(
                            tool_call_id=getattr(message, "tool_call_id", ""),
                            name=getattr(message, "name", "unknown"),
                            result=str(message.content) if message.content else "",
                        )
            else:
                async for chunk in llm_model.astream(
                        [
                            SystemMessage(content=system_prompt),
                            HumanMessage(content=event.transcript),
                        ]
                ):
                    if getattr(chunk, "content", None):
                        yield AgentChunkEvent.create(str(chunk.content))
            yield AgentEndEvent.create()


async def _tts_stream(
        event_stream: AsyncIterator[VoiceAgentEvent],
) -> AsyncIterator[VoiceAgentEvent]:
    """
    Transform stream: Voice Events → Voice Events (with Audio)

    This function takes a stream of upstream voice agent events and processes them.
    When agent_chunk events arrive, it sends the text to Cartesia for TTS synthesis.
    Audio is streamed back as tts_chunk events as it's generated.
    All upstream events are passed through unchanged.

    It uses merge_async_iters to combine two concurrent streams:
    - process_upstream(): Iterates through incoming events, yields them for
      passthrough, and sends agent text chunks to Cartesia for synthesis.
    - tts.receive_events(): Yields audio chunks from Cartesia as they are
      synthesized.

    The merge utility runs both iterators concurrently, yielding items from
    either stream as they become available. This allows audio generation to
    begin before the agent has finished generating all text, minimizing latency.

    Args:
        event_stream: An async iterator of upstream voice agent events

    Yields:
        All upstream events plus tts_chunk events for synthesized audio
    """
    tts_model_name = os.getenv("VOICE_LC_TTS_MODEL") or "qwen3-tts-vd-2026-01-26"
    tts_voice = os.getenv("VOICE_LC_TTS_VOICE") or "Cherry"
    tts_url = os.getenv("VOICE_LC_TTS_URL") or "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
    tts = DashscopeQwenTtsRealtime(
        api_key=api_key,
        model=tts_model_name,
        voice=tts_voice,
        url=tts_url,
        response_format="pcm_24000hz_mono_16bit",
    )

    async def process_upstream() -> AsyncIterator[VoiceAgentEvent]:
        """
        Process upstream events, yielding them while sending text to Cartesia.

        This async generator serves two purposes:
        1. Pass through all upstream events (stt_chunk, stt_output, agent_chunk)
           so downstream consumers can observe the full event stream.
        2. Buffer agent_chunk text and send to Cartesia when agent_end arrives.
           This ensures the full response is sent at once for better TTS quality.
        """
        buffer: list[str] = []
        async for event in event_stream:
            # Pass through all events to downstream consumers
            yield event
            # Buffer agent text chunks
            if event.type == "agent_chunk":
                buffer.append(event.text)
            # Send all buffered text to Cartesia when agent finishes
            if event.type == "agent_end":
                await tts.send_text("".join(buffer))
                buffer = []

    try:
        # Merge the processed upstream events with TTS audio events
        # Both streams run concurrently, yielding events as they arrive
        async for event in merge_async_iters(process_upstream(), tts.receive_events()):
            yield event
    finally:
        # Cleanup: close the WebSocket connection to Cartesia
        await tts.close()


pipeline = (
        RunnableGenerator(_stt_stream)  # Audio -> STT events
        | RunnableGenerator(_agent_stream)  # STT events -> STT + Agent events
        | RunnableGenerator(_tts_stream)  # STT + Agent events -> All events
)


async def voice_agent_langchain(
        ws: WebSocket,
        settings: Settings,
) -> None:
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
            "message": "fastapi voice agent (langchain) websocket ready",
        }
    )

    async def websocket_audio_stream() -> AsyncIterator[bytes]:
        while True:
            message = await ws.receive()

            msg_type = message.get("type")
            has_bytes = message.get("bytes") is not None
            text = message.get("text")
            logger.info("ws.receive type=%s bytes=%s text=%s", msg_type, has_bytes,
                        (text[:120] if isinstance(text, str) else None))
            msg_type = message.get("type")
            if msg_type == "websocket.disconnect":
                break
            if msg_type != "websocket.receive":
                continue
            data = message.get("bytes")
            if data is not None:
                yield data
                continue
            text = message.get("text")
            if text is None:
                continue
            payload = _as_json(text)
            if payload and payload.get("type") == "ping":
                try:
                    await ws.send_json({"type": "pong"})
                except Exception:
                    return

    try:
        output_stream = pipeline.atransform(websocket_audio_stream())

        # Process all events from the pipeline, sending events back to the client
        async for event in output_stream:
            await ws.send_json(event_to_dict(event))
    except WebSocketDisconnect:
        return
    except Exception:
        logger.exception("voice_agent_langchain ws unhandled exception")
        try:
            await ws.close(code=1011, reason="internal error")
        except Exception:
            return


def create_voice_agent_langchain_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/voice_agent_langchain")
    async def on_connect(ws: WebSocket) -> None:
        await voice_agent_langchain(ws, settings)

    return router
