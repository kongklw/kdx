"""
AI 统一入口 WebSocket 路由 (生产版)

一个端点同时接受文字和语音, 背后复用同一张 LangGraph 状态图 (baby_assistant)。
替代旧的 voice_agent_langchain.py (三明治 demo) 和 baby_assistant.py (纯文字)。

协议 (统一 v3, 兼容文字+语音):

Client → Server:
  {"type": "query", "query": "...", "request_id": "uuid"}         ← 文字
  {"type": "audio", "audio": "<base64 pcm 16kHz>"}                 ← 语音帧
  {"type": "audio_start"}                                           ← 开始语音输入
  {"type": "audio_end"}                                             ← 结束语音输入
  {"type": "confirm", "confirm_id": "CFM-..", "action": "approve|reject"}
  {"type": "ping"}

Server → Client:
  {"type": "connected", ...}
  {"type": "pong"}
  {"type": "stt_chunk", "transcript": "..."}                       ← 部分识别
  {"type": "stt_output", "transcript": "..."}                      ← 句尾定稿
  {"type": "query_start", ...}
  {"type": "intent_detected", ...}
  {"type": "tool_call", ...}
  {"type": "tool_result", ...}
  {"type": "confirmation_request", ...}
  {"type": "generate_chunk", "chunk": "..."}                       ← 流式文本
  {"type": "answer_done", "answer": "...", ...}
  {"type": "tts_chunk", "audio": "<base64 pcm 24kHz>"}             ← 语音回复
  {"type": "query_done", ...}
  {"type": "query_error", "error": "..."}

生产化要点 (合并 baby_assistant + voice_agent_langchain 的精华):
- 全局共享图: get_compiled_graph() 进程级编译一次
- 会话持久化: thread_id = user-{user_id}, checkpointer 承载多轮记忆
- contextvar: set_runtime_context 注入 emit/身份
- 原生 HITL: interrupt() → Command(resume=...) 恢复
- 限流: Redis 滑动窗口 30 次/分钟/用户
- 输入限长: query ≤ 500 字符
- 空闲踢出: 10 分钟无消息自动断开
- 语音打断: 用户开始说话时取消正在进行的 TTS
- ASR/TTS 复用: DashScope paraformer-realtime-v2 + qwen3-tts-vd
"""

import asyncio
import base64
import contextlib
import json
import os
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, WebSocket
from fastapi.websockets import WebSocketDisconnect
from loguru import logger

from ..core.config import Settings
from ..core.security import (
    extract_token_from_cookie,
    extract_token_from_headers,
    verify_jwt,
)
from ..voice.asr import DashscopeRealtimeASR
from ..voice.tts import DashscopeQwenTtsRealtime
from ..voice.observability import (
    VoiceTraceContext,
    set_voice_trace_context,
    reset_voice_trace_context,
    record_connection,
    record_disconnect,
    record_query_start,
    record_query_end,
    record_asr_start,
    record_asr_chunk,
    record_asr_final,
    record_agent_start,
    record_agent_end,
    record_tts_start,
    record_tts_chunk,
    record_tts_end,
    record_hitl_pending,
    record_hitl_resolved,
    record_error,
    record_rate_limit,
    record_idle_timeout,
)
from ..utils.event import event_to_dict

MAX_QUERY_LEN = 500
RATE_LIMIT_CALLS = 30
CONFIRM_TTL = 300
IDLE_TIMEOUT = 600
_TTS_CHUNK_SIZE = 16_384


def create_ai_entrance_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/ai-entrance")
    async def on_connect(ws: WebSocket) -> None:
        await ai_entrance_websocket(ws, settings)

    return router


async def ai_entrance_websocket(ws: WebSocket, settings: Settings) -> None:
    # ── 鉴权 (JWT, 三种 token 提取方式) ──────────────────
    token: Optional[str] = ws.query_params.get("token")
    if not token:
        token = extract_token_from_headers(ws.headers.get("authorization"))
    if not token:
        token = extract_token_from_cookie(ws.headers.get("cookie"))

    if not token:
        await ws.close(code=4401, reason="missing token")
        logger.warning("[ai_entrance] rejected: no token")
        return

    try:
        user = verify_jwt(token, settings)
    except Exception as e:
        await ws.close(code=4401, reason=f"invalid token: {e}")
        logger.warning(f"[ai_entrance] rejected: invalid token - {e}")
        return

    user_id = int(user.get("user_id"))
    thread_id = f"user-{user_id}"
    await ws.accept()
    await ws.send_json(
        {
            "type": "connected",
            "user_id": user_id,
            "message": "ai entrance ready (protocol v3, voice+text)",
        }
    )
    record_connection(user_id)

    # ── 全局共享图 + 运行时 ──────────────────────────────
    from ..assistant.graph import get_compiled_graph, AssistantState
    from ..assistant.runtime import set_runtime_context, reset_runtime_context
    from ..assistant.resilience import RateLimiter
    from langgraph.types import Command

    graph = get_compiled_graph()
    limiter = RateLimiter(
        redis_url=settings.redis_url,
        max_calls=RATE_LIMIT_CALLS,
        window_seconds=60,
    )

    api_key = os.getenv("DASHSCOPE_API_KEY")
    pending_redis = None
    processing = False  # 防止并发 query 打乱状态机
    voice_mode = False  # 当前是否在语音输入模式
    audio_frame_queue: Optional[asyncio.Queue] = None
    voice_task: Optional[asyncio.Task] = None

    # TTS 实例 (懒加载, 跨 query 复用)
    _tts: Optional[DashscopeQwenTtsRealtime] = None

    async def get_tts() -> DashscopeQwenTtsRealtime:
        nonlocal _tts
        if _tts is None or _tts._closed:
            tts_model = os.getenv("VOICE_LC_TTS_MODEL") or "qwen3-tts-vd-2026-01-26"
            tts_voice = os.getenv("VOICE_LC_TTS_VOICE") or "Cherry"
            tts_url = os.getenv("VOICE_LC_TTS_URL") or "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
            _tts = DashscopeQwenTtsRealtime(
                api_key=api_key,
                model=tts_model,
                voice=tts_voice,
                url=tts_url,
                response_format="pcm_24000hz_mono_16bit",
            )
        return _tts

    async def send_event(event_type: str, data: Dict[str, Any]):
        try:
            await ws.send_json({"type": event_type, "data": data})
        except Exception:
            pass

    async def get_redis():
        nonlocal pending_redis
        if pending_redis is not None:
            return pending_redis if pending_redis is not False else None
        try:
            import redis.asyncio as aioredis
            pending_redis = aioredis.from_url(settings.redis_url, decode_responses=True)
            await pending_redis.ping()
        except Exception:
            pending_redis = False
        return pending_redis if pending_redis is not False else None

    def build_initial_state(query: str, request_id: str) -> AssistantState:
        return {
            "user_id": user_id,
            "query": query,
            "request_id": request_id,
            "tool_trace": [],
            "tool_rounds": 0,
        }

    def graph_config() -> Dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}}

    # ── HITL 挂起状态管理 (Redis) ────────────────────────
    async def store_pending(confirm_id: str, request_id: str, is_voice: bool) -> None:
        payload = json.dumps(
            {
                "confirm_id": confirm_id,
                "request_id": request_id,
                "ts": time.time(),
                "voice": is_voice,
            },
            ensure_ascii=False,
        )
        r = await get_redis()
        if r:
            try:
                await r.set(f"agent:pending:{thread_id}", payload, ex=CONFIRM_TTL)
                return
            except Exception:
                pass

    async def load_pending() -> Optional[Dict[str, Any]]:
        r = await get_redis()
        if r:
            try:
                raw = await r.get(f"agent:pending:{thread_id}")
                if raw:
                    return json.loads(raw)
            except Exception:
                pass
        return None

    async def clear_pending() -> None:
        r = await get_redis()
        if r:
            try:
                await r.delete(f"agent:pending:{thread_id}")
            except Exception:
                pass

    # ── HITL interrupt 处理 ──────────────────────────────
    async def handle_interrupt(result: Dict[str, Any], request_id: str, is_voice: bool) -> None:
        interrupts = result.get("__interrupt__")
        if not interrupts:
            return
        first = interrupts[0]
        payload = getattr(first, "value", first) if not isinstance(first, dict) else first
        confirm_id = payload.get("confirm_id") or f"CFM-{uuid.uuid4().hex}"
        await store_pending(confirm_id, request_id, is_voice)
        await send_event("confirmation_request", {
            "request_id": request_id,
            "confirm_id": confirm_id,
            "tools": payload.get("tools", []),
            "message": payload.get("message", "即将写入宝宝数据，请确认"),
            "expires_in": CONFIRM_TTL,
        })

    # ── 图执行 + 事件流式推送 ────────────────────────────
    async def run_graph(
        state: AssistantState, request_id: str, is_voice: bool
    ) -> Dict[str, Any]:
        """统一执行入口: 注入运行时上下文 → 图执行 → 处理 HITL 挂起"""
        # 语音模式: emit 回调同时收集 generate_chunk 文本用于 TTS
        collected_text: list[str] = []

        async def emit_with_collect(event_type: str, data: Dict[str, Any]):
            await send_event(event_type, data)
            if event_type == "generate_chunk":
                collected_text.append(data.get("chunk", ""))

        token = set_runtime_context(
            user_id=user_id,
            request_id=request_id,
            emit=emit_with_collect if is_voice else send_event,
            thread_id=thread_id,
        )
        try:
            result = await graph.ainvoke(state, graph_config())
            await handle_interrupt(result, request_id, is_voice)

            # 语音模式: 无 interrupt → 收集的文本送 TTS
            if is_voice and not result.get("__interrupt__"):
                full_text = "".join(collected_text).strip()
                if full_text:
                    await _stream_tts(full_text)

            return result
        finally:
            reset_runtime_context(token)

    async def _stream_tts(text: str) -> None:
        """将文本送 TTS 合成, 流式推送音频帧"""
        record_tts_start()
        try:
            tts = await get_tts()
            await tts.send_text(text)
            async for event in tts.receive_events():
                # 统计 TTS 音频字节数
                if hasattr(event, "audio") and event.audio:
                    record_tts_chunk(len(event.audio))
                await ws.send_json(event_to_dict(event))
        except Exception as e:
            record_error("tts", str(e))
            logger.warning(f"[ai_entrance] TTS failed: {e}")
        finally:
            record_tts_end()

    # ── 文字 query 处理 (与 baby_assistant 一致) ─────────
    async def process_query(query: str, request_id: str) -> None:
        ctx = VoiceTraceContext(request_id=request_id, user_id=user_id, thread_id=thread_id, mode="text")
        trace_token = set_voice_trace_context(ctx)
        record_query_start("text")
        await send_event("query_start", {"query": query, "request_id": request_id})
        try:
            record_agent_start()
            result = await run_graph(
                build_initial_state(query, request_id), request_id, is_voice=False
            )
            record_agent_end(
                intent=result.get("intent", ""),
                route=result.get("route") or result.get("intent") or "",
                tool_calls=len(result.get("tool_trace") or []),
            )
            if result.get("__interrupt__"):
                confirm_id = ""
                interrupts = result.get("__interrupt__")
                if interrupts:
                    payload = getattr(interrupts[0], "value", interrupts[0]) if not isinstance(interrupts[0], dict) else interrupts[0]
                    confirm_id = payload.get("confirm_id", "")
                record_hitl_pending(confirm_id)
                return
            await send_event("query_done", {
                "request_id": request_id,
                "intent": result.get("intent"),
                "route": result.get("route") or result.get("intent"),
                "tool_trace": result.get("tool_trace") or [],
                "sources": result.get("sources") or [],
            })
            record_query_end(status="ok")
        except Exception as e:
            record_error("agent", str(e))
            logger.exception(f"[ai_entrance] query failed: {e}")
            await send_event("query_error", {"error": str(e)})
            record_query_end(status="error")
        finally:
            reset_voice_trace_context(trace_token)

    # ── 语音 query 处理: ASR → 图 → TTS ─────────────────
    async def process_voice_query(
        audio_queue: asyncio.Queue, request_id: str
    ) -> None:
        """语音管线: 音频帧 → ASR → 最终 transcript → 图 → TTS"""
        ctx = VoiceTraceContext(request_id=request_id, user_id=user_id, thread_id=thread_id, mode="voice")
        trace_token = set_voice_trace_context(ctx)
        record_query_start("voice")

        stt_model = os.getenv("VOICE_LC_STT_MODEL") or "paraformer-realtime-v2"
        stt_url = os.getenv("VOICE_LC_STT_URL") or "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
        stt_language = os.getenv("VOICE_LC_STT_LANGUAGE") or "zh"
        stt_sample_rate = int(os.getenv("VOICE_LC_STT_SAMPLE_RATE") or "16000")
        stt_max_silence = int(os.getenv("VOICE_LC_STT_MAX_SILENCE_MS") or "400")
        stt_semantic_punc = (os.getenv("VOICE_LC_STT_SEMANTIC_PUNC") or "").lower() == "true"
        if "8k" in stt_model and stt_sample_rate != 8000:
            stt_sample_rate = 8000

        asr = DashscopeRealtimeASR(
            api_key=api_key,
            model=stt_model,
            url=stt_url,
            sample_rate=stt_sample_rate,
            language=stt_language,
            max_sentence_silence_ms=stt_max_silence,
            semantic_punctuation_enabled=stt_semantic_punc,
        )

        final_transcript = ""

        async def feed_audio():
            """从队列取音频帧喂给 ASR"""
            try:
                while True:
                    chunk = await audio_queue.get()
                    if chunk is None:  # 结束信号
                        break
                    await asr.send_audio(chunk)
            finally:
                with contextlib.suppress(Exception):
                    await asr.finish()
                with contextlib.suppress(Exception):
                    await asr.close()

        feed_task = asyncio.create_task(feed_audio())

        try:
            record_asr_start()
            async for event in asr.receive_events():
                await ws.send_json(event_to_dict(event))

                # 部分识别
                if event.type == "stt_chunk":
                    record_asr_chunk()

                # 句尾定稿 → 作为 query 送入图
                if event.type == "stt_output":
                    final_transcript = event.transcript
                    record_asr_final(final_transcript)

                    if not final_transcript.strip():
                        continue
                    if len(final_transcript) > MAX_QUERY_LEN:
                        record_error("asr", f"transcript too long ({len(final_transcript)} chars)")
                        await send_event("query_error", {
                            "error": f"voice transcript too long (max {MAX_QUERY_LEN} chars)"
                        })
                        continue

                    await send_event("query_start", {
                        "query": final_transcript,
                        "request_id": request_id,
                        "source": "voice",
                    })

                    record_agent_start()
                    result = await run_graph(
                        build_initial_state(final_transcript, request_id),
                        request_id,
                        is_voice=True,
                    )
                    record_agent_end(
                        intent=result.get("intent", ""),
                        route=result.get("route") or result.get("intent") or "",
                        tool_calls=len(result.get("tool_trace") or []),
                    )

                    if result.get("__interrupt__"):
                        confirm_id = ""
                        interrupts = result.get("__interrupt__")
                        if interrupts:
                            payload = getattr(interrupts[0], "value", interrupts[0]) if not isinstance(interrupts[0], dict) else interrupts[0]
                            confirm_id = payload.get("confirm_id", "")
                        record_hitl_pending(confirm_id)
                        return  # 等待用户 confirm

                    await send_event("query_done", {
                        "request_id": request_id,
                        "intent": result.get("intent"),
                        "route": result.get("route") or result.get("intent"),
                        "tool_trace": result.get("tool_trace") or [],
                        "sources": result.get("sources") or [],
                    })
                    record_query_end(status="ok")
        except Exception as e:
            record_error("voice_pipeline", str(e))
            logger.exception(f"[ai_entrance] voice query failed: {e}")
            await send_event("query_error", {"error": str(e)})
            record_query_end(status="error")
        finally:
            with contextlib.suppress(asyncio.CancelledError):
                feed_task.cancel()
                await feed_task
            with contextlib.suppress(Exception):
                await asr.close()
            reset_voice_trace_context(trace_token)

    # ── HITL confirm 处理 (文字/语音通用) ───────────────
    async def process_confirm(confirm_id: str, action: str) -> None:
        pending = await load_pending()
        if not pending:
            await send_event("query_error", {"error": "no pending confirmation or expired"})
            return
        if pending.get("confirm_id") and confirm_id and confirm_id != pending["confirm_id"]:
            await send_event("query_error", {"error": "confirm_id mismatch"})
            return
        if time.time() - pending.get("ts", time.time()) > CONFIRM_TTL:
            await clear_pending()
            await send_event("query_error", {"error": "confirmation expired, please retry"})
            return

        is_voice = pending.get("voice", False)

        if action == "reject":
            await clear_pending()
            record_hitl_resolved("reject")
            answer = "好的，已取消本次操作。"
            await send_event("generate_chunk", {"chunk": answer})
            await send_event("answer_done", {"answer": answer})
            if is_voice:
                await _stream_tts(answer)
            await send_event("query_done", {
                "request_id": pending.get("request_id", ""),
                "route": "data_query(rejected)",
                "tool_trace": [],
            })
            return

        # approve: 从 interrupt 暂停点恢复
        record_hitl_resolved("approve")
        request_id = pending.get("request_id") or str(uuid.uuid4())
        collected_text: list[str] = []

        async def emit_with_collect(event_type: str, data: Dict[str, Any]):
            await send_event(event_type, data)
            if is_voice and event_type == "generate_chunk":
                collected_text.append(data.get("chunk", ""))

        token = set_runtime_context(
            user_id=user_id,
            request_id=request_id,
            emit=emit_with_collect if is_voice else send_event,
            thread_id=thread_id,
        )
        try:
            result = await graph.ainvoke(
                Command(resume={"action": "approve"}), graph_config()
            )
            await handle_interrupt(result, request_id, is_voice)
            if result.get("__interrupt__"):
                return

            # 语音模式: 恢复后的回答送 TTS
            if is_voice:
                full_text = "".join(collected_text).strip()
                if not full_text:
                    full_text = result.get("answer", "").strip()
                if full_text:
                    await _stream_tts(full_text)

            await send_event("query_done", {
                "request_id": request_id,
                "intent": result.get("intent") or "data_query",
                "route": "data_query(resumed)",
                "tool_trace": result.get("tool_trace") or [],
                "sources": result.get("sources") or [],
            })
        except Exception as e:
            logger.exception(f"[ai_entrance] resume failed: {e}")
            await send_event("query_error", {"error": str(e)})
        finally:
            await clear_pending()
            reset_runtime_context(token)

    # ── 消息循环 (文字 + 语音 + HITL 统一处理) ──────────
    try:
        while True:
            try:
                message = await asyncio.wait_for(ws.receive(), timeout=IDLE_TIMEOUT)
            except asyncio.TimeoutError:
                record_idle_timeout(user_id)
                await ws.close(code=1001, reason="idle timeout")
                return

            msg_type = message.get("type")
            if msg_type == "websocket.disconnect":
                break
            if msg_type != "websocket.receive":
                continue

            # 二进制消息 = 原始 PCM 音频帧
            raw_bytes = message.get("bytes")
            if raw_bytes is not None:
                if voice_mode and not processing and audio_frame_queue is not None:
                    await audio_frame_queue.put(raw_bytes)
                continue

            text = message.get("text")
            if not text:
                continue

            try:
                payload = json.loads(text)
            except Exception as e:
                await send_event("query_error", {"error": f"invalid json: {e}"})
                continue

            p_type = payload.get("type")

            if p_type == "ping":
                await send_event("pong", {})
                continue

            # ── 文字查询 ────────────────────────────────
            if p_type == "query":
                query = (payload.get("query") or "").strip()
                if not query:
                    continue
                if len(query) > MAX_QUERY_LEN:
                    await send_event("query_error", {
                        "error": f"query too long (max {MAX_QUERY_LEN} chars)"
                    })
                    continue
                if not await limiter.allow(f"user:{user_id}"):
                    record_rate_limit(user_id)
                    await send_event("query_error", {
                        "error": f"rate limit exceeded ({RATE_LIMIT_CALLS}/min)"
                    })
                    continue
                if await load_pending():
                    await send_event("query_error", {
                        "error": "pending write confirmation, please approve/reject first"
                    })
                    continue
                if processing:
                    await send_event("query_error", {"error": "busy: previous query in progress"})
                    continue

                # 用户发文字时, 取消正在进行的 TTS (打断)
                if _tts and _tts._task and not _tts._task.done():
                    _tts._task.cancel()

                processing = True
                try:
                    request_id = payload.get("request_id") or str(uuid.uuid4())
                    await process_query(query, request_id)
                finally:
                    processing = False
                continue

            # ── 语音帧 (base64 编码的 JSON 消息) ─────────
            if p_type == "audio":
                if processing:
                    # 用户说话时打断正在进行的 TTS
                    if _tts and _tts._task and not _tts._task.done():
                        _tts._task.cancel()
                    continue
                audio_b64 = payload.get("audio")
                if not audio_b64:
                    continue
                try:
                    pcm = base64.b64decode(audio_b64)
                except Exception:
                    continue
                if voice_mode and audio_frame_queue is not None:
                    await audio_frame_queue.put(pcm)
                continue

            # ── 语音会话控制 ────────────────────────────
            if p_type == "audio_start":
                if processing:
                    continue
                if await load_pending():
                    await send_event("query_error", {
                        "error": "pending confirmation, please approve/reject first"
                    })
                    continue
                if not await limiter.allow(f"user:{user_id}"):
                    record_rate_limit(user_id)
                    await send_event("query_error", {
                        "error": f"rate limit exceeded ({RATE_LIMIT_CALLS}/min)"
                    })
                    continue

                # 取消正在进行的 TTS (语音打断)
                if _tts and _tts._task and not _tts._task.done():
                    _tts._task.cancel()

                voice_mode = True
                processing = True
                audio_frame_queue = asyncio.Queue()
                voice_request_id = str(uuid.uuid4())

                # 启动语音处理协程
                voice_task = asyncio.create_task(
                    process_voice_query(audio_frame_queue, voice_request_id)
                )
                continue

            if p_type == "audio_end":
                if not voice_mode:
                    continue
                # 发送结束信号给音频队列
                if audio_frame_queue is not None:
                    await audio_frame_queue.put(None)
                # 等待语音处理完成
                if voice_task and not voice_task.done():
                    try:
                        await asyncio.wait_for(voice_task, timeout=30.0)
                    except asyncio.TimeoutError:
                        voice_task.cancel()
                voice_mode = False
                processing = False
                continue

            # ── HITL 确认 ───────────────────────────────
            if p_type == "confirm":
                if processing and not voice_mode:
                    await send_event("query_error", {"error": "busy"})
                    continue
                processing = True
                try:
                    await process_confirm(
                        payload.get("confirm_id") or "",
                        payload.get("action") or "reject",
                    )
                finally:
                    processing = False
                continue

            await send_event("query_error", {"error": f"unknown type: {p_type}"})

    except WebSocketDisconnect:
        record_disconnect(user_id, "client_disconnect")
        return
    except Exception as e:
        record_error("ws_loop", str(e))
        logger.exception("[ai_entrance] unhandled exception")
        try:
            await ws.close(code=1011, reason="internal error")
        except Exception:
            record_disconnect(user_id, "internal_error")
            return
        record_disconnect(user_id, "internal_error")
        return
    finally:
        # 清理 TTS
        if _tts is not None:
            with contextlib.suppress(Exception):
                await _tts.close()
