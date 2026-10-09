'''
应用的AI 主入口 (agent + rag + chitchat 全部经此路由)。
实现语音和文字 输入,所有app 实现agent化。

本文件仅负责 WS 接入流程与业务分发; WS 生产级基础设施 (鉴权/连接管理/协议/心跳)
统一复用 app.core.ws, 其他 WS 接口直接复用, 无需重写。
AI 编排 (意图路由 → agent工具调用 / RAG知识问答 / chitchat) 在 service 层
(services/assistant_service.py AssistantSession + assistant/graph.py),
本路由层只做协议分发。RAG 不需要单独接入口: 意图为 knowledge_qa 时图内
自动走 rag_node (retrieve_start/retrieve_done/流式回答), 事件协议同下。

协议 (平铺格式, 与本文件既有事件一致):

Client → Server:
  {"type":"start","codec":...,"sample_rate":...}                        语音会话握手
  二进制 PCM 帧 (16bit/16k/mono)                                        语音流
  {"type":"end","audio_bytes":N}                                        语音结束
  {"type":"query","query":"...","request_id":"..."}                     文字查询
  {"type":"confirm","confirm_id":"CFM-...","action":"approve"|"reject"} 写操作确认 (HITL)
  {"type":"ping"}

Server → Client:
  connected / pong / voice_started / query_received / error
  stt_chunk / stt_output                      (ASR, event_to_dict)
  intent_start / intent_detected              (图: 意图识别)
  retrieve_start / retrieve_done              (图: RAG 检索)
  tool_call / tool_result                     (图: 工具调用)
  confirmation_request {confirm_id,tools,...} (图: HITL 写确认, 等待 confirm)
  generate_chunk / answer_done                (流式回答)
  query_done / query_error                    (单次 query 结束/失败)

注意: 语音会话期间 (processing=True) confirm 会被 busy 拒绝;
pending_confirm 为连接级状态, 断线残留的 interrupt 会在下个连接的新 query 前自动取消;
query/语音会话启动受每用户速率限制 (30/min 滑动窗口, Redis-backed)。
'''
import asyncio
import contextlib
import os
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, WebSocket
from fastapi.websockets import WebSocketDisconnect
from loguru import logger

from ..core.config import Settings
from ..core.ws import (
    CloseCode,
    IdleTimeout,
    MessageTooBig,
    authenticate,
    connection_manager,
    parse_payload,
    receive_message,
    safe_send_json,
)
from ..assistant.resilience import RateLimiter
from ..services.assistant_service import AssistantSession
from ..utils.event import event_to_dict
from ..voice.asr import DashscopeRealtimeASR
from ..services.chat_history_service import ChatHistoryService

RATE_LIMIT_CALLS = 30         # 每用户每分钟 query 上限 (文字按条, 语音按会话)


def create_app_ai_entrance_router(settings: Settings):
    router = APIRouter()
    # 进程级速率限制器: Redis 滑动窗口 (跨连接/跨请求生效);
    # Redis 不可用时自动回退进程内窗口 (单实例仍有效) — 故不能每连接新建
    limiter = RateLimiter(redis_url=settings.redis_url,
                          max_calls=RATE_LIMIT_CALLS, window_seconds=60)

    @router.websocket("/ws/app-ai-entrance")
    async def connect_on(ws: WebSocket):
        await app_ai_entrance_ws(ws, settings, limiter)

    return router


async def app_ai_entrance_ws(ws: WebSocket, settings: Settings, limiter: RateLimiter):
    '''
    步骤
    1. jwt 鉴权 (复用 core.ws.authenticate)
    2. 业务层 service (自行实现)
        2.1 service 层去跟 schemas,models等进行交互。当前路由层，只简单调用。
    '''
    ws_config = connection_manager.config

    # ── 1. 准入: Origin + token + JWT (失败已在内部 close) ──────
    user_id = await authenticate(ws, settings, ws_config)
    print(f'user_id-> {user_id}')
    if not user_id:
        return

    # ── 2. 连接数限制 (全局 + 单用户; 超限 close) ───────────────
    if not await connection_manager.acquire(ws, user_id):
        await ws.close(code=CloseCode.POLICY_VIOLATION, reason="too many connections")
        logger.warning(f"[app_ai_entrance] rejected: conn limit reached user={user_id}")
        return

    # thread_id = user-{user_id}: 每用户一个 thread (与 baby_assistant.py 一致),
    # 多轮记忆跨连接保留 (checkpointer 承载)。结论: 同一 thread_id 不会导致
    # 多次 resume / time travel — 每次 ainvoke 只是向该 thread 追加一个新 checkpoint;
    # interrupt 恢复仅发生在显式 Command(resume=...) 时, 由 AssistantSession 的
    # pending_confirm 状态机管理 (见 services/assistant_service.py)。
    thread_id = f"user-{user_id}"

    # ── 3. accept + 进入消息循环 (finally 释放连接计数) ─────────
    await ws.accept()
    await safe_send_json(ws, {
        "type": "connected",
        "user_id": user_id,
        "message": "app ai entrance already",
    })
    logger.info(f"[app_ai_entrance] connected user={user_id}")

    # ── AI 会话 (service 层): 图执行 + HITL 确认, 事件平铺下发 ──
    _chat_history = ChatHistoryService.get_instance()

    async def send_agent_event(event_type: str, data: Dict[str, Any]) -> None:
        await safe_send_json(ws, {"type": event_type, **data})
        # 拦截关键事件 → 持久化 AI 消息到聊天历史
        rid = data.get("request_id", "")
        if event_type == "answer_done":
            await _chat_history.save_message(user_id, {
                "role": "ai",
                "text": data.get("answer", ""),
                "tool_events": data.get("tool_trace", []),
                "request_id": rid,
            })
        elif event_type == "confirmation_request":
            await _chat_history.save_message(user_id, {
                "role": "ai",
                "text": "",
                "confirm": {
                    "confirm_id": data.get("confirm_id"),
                    "tools": data.get("tools", []),
                },
                "request_id": rid,
            })
        elif event_type == "query_error":
            # 查询出错也保存 AI 侧消息, 确保历史中用户消息总有对应回复
            await _chat_history.save_message(user_id, {
                "role": "ai",
                "text": f"⚠️ {data.get('error', '处理失败')}",
                "request_id": rid,
            })

    session = AssistantSession(user_id=user_id, thread_id=thread_id,
                               emit=send_agent_event)

    # ── 业务状态 + 归一化处理 (文字 / 语音 → 统一文本 query) ──────────
    # 设计: 无论语音还是文本输入, 最终都转换成文本 query, 再走同一个 handle。
    # 本步骤只实现 "归一化到 query"; agent 执行 (意图识别 / 工具调用) 见 handle_query。
    processing = False  # 并发互斥: 有 query 在处理时拒绝新 query
    voice_mode = False  # 是否处于语音输入会话
    audio_queue: Optional[asyncio.Queue] = None
    voice_task: Optional[asyncio.Task] = None

    MAX_QUERY_LEN = 500  # 文本 / ASR 转写结果长度上限
    _DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

    async def handle_query(query: str, request_id: str, source: str) -> None:
        """统一文本 query 入口 (文字直出 / 语音 ASR 转写后调用)。

        文字: 直接来自 payload["query"]; 语音: 来自 DashScope ASR 句尾定稿。
        归一化后送 service 层 AssistantSession 执行 agent (意图识别 + 工具调用)。
        """
        print(f'handel query -> {query}, id: {request_id} , source: {source}')
        query = (query or "").strip()
        if not query:
            return
        if len(query) > MAX_QUERY_LEN:
            await safe_send_json(ws, {
                "type": "error",
                "error": f"query too long (max {MAX_QUERY_LEN} chars)",
            })
            return
        logger.info(
            f"[app_ai_entrance] query user={user_id} source={source} "
            f"req={request_id} thread={thread_id} q={query!r}"
        )

        await safe_send_json(ws, {
            "type": "query_received",
            "query": query,
            "request_id": request_id,
            "source": source,  # "text" | "voice"
            "thread_id": thread_id,
        })
        # 持久化用户消息到聊天历史
        await _chat_history.save_message(user_id, {
            "role": "user",
            "text": query,
            "request_id": request_id,
            "source": source,
        })
        # ── agent 执行: 意图识别 + 工具调用 (编排在 service 层 AssistantSession) ──
        if session.pending_confirm:
            await safe_send_json(ws, {
                "type": "error",
                "error": "有待确认的操作未处理，请先确认或取消",
            })
            return
        await session.run_query(query, request_id)




    async def process_voice_query(
            audio_q: asyncio.Queue, request_id: str
    ) -> None:
        """语音管线: PCM 帧 → DashScope 流式 ASR → 句尾定稿 → handle_query。

        与 ai_entrance.py 一致: 边收音边转写, stt_chunk/stt_output 实时下发客户端,
        每个 stt_output (句尾定稿) 作为一条文本 query 送统一 handle。
        """
        stt_model = os.getenv("VOICE_LC_STT_MODEL") or "paraformer-realtime-v2"
        stt_url = os.getenv("VOICE_LC_STT_URL") or "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
        stt_language = os.getenv("VOICE_LC_STT_LANGUAGE") or "zh"
        stt_sample_rate = int(os.getenv("VOICE_LC_STT_SAMPLE_RATE") or "16000")
        stt_max_silence = int(os.getenv("VOICE_LC_STT_MAX_SILENCE_MS") or "400")
        # 语音助手场景推荐 VAD-based 分段 (semantic_punctuation_enabled=false):
        # - true = 语义分段 (需要完整语义句, 短话可能零输出)
        # - false = VAD 静音分段 (按静音阈值切句, 响应更快)
        stt_semantic_punc = (os.getenv("VOICE_LC_STT_SEMANTIC_PUNC") or "false").lower() == "true"
        if "8k" in stt_model and stt_sample_rate != 8000:
            stt_sample_rate = 8000

        print(
            f"[ASR] pipeline start req={request_id} model={stt_model} url={stt_url} "
            f"sample_rate={stt_sample_rate} lang={stt_language} "
            f"silence_ms={stt_max_silence} punc={stt_semantic_punc} "
            f"api_key={'SET' if _DASHSCOPE_API_KEY else '!!! MISSING !!!'}"
        )

        asr = DashscopeRealtimeASR(
            api_key=_DASHSCOPE_API_KEY,
            model=stt_model,
            url=stt_url,
            sample_rate=stt_sample_rate,
            language=stt_language,
            max_sentence_silence_ms=stt_max_silence,
            semantic_punctuation_enabled=stt_semantic_punc,
        )

        fed_chunks = 0
        fed_bytes = 0

        async def feed_audio():
            """从队列取 PCM 帧喂给 ASR; None = 结束信号 (对应 {"type":"end"})。"""
            nonlocal fed_chunks, fed_bytes
            try:
                while True:
                    chunk = await audio_q.get()
                    if chunk is None:
                        print(f"[ASR] feed END sentinel; fed chunks={fed_chunks} bytes={fed_bytes}")
                        break
                    await asr.send_audio(chunk)
                    fed_chunks += 1
                    fed_bytes += len(chunk)
                    if fed_chunks <= 3 or fed_chunks % 20 == 0:
                        print(f"[ASR] feed chunk#{fed_chunks} len={len(chunk)} total_bytes={fed_bytes}")
            except Exception as e:
                # 关键: 之前这里的异常被 finally 的 suppress 吞掉, 现在显式打印并抛出
                print(f"[ASR] feed_audio !!! {type(e).__name__}: {e}")
                logger.exception("[app_ai_entrance] feed_audio failed")
                raise
            finally:
                print("[ASR] → asr.finish()")
                try:
                    await asr.finish()
                    print("[ASR] finish() done")
                except Exception as fe:
                    print(f"[ASR] finish() !!! {type(fe).__name__}: {fe}")

        feed_task = asyncio.create_task(feed_audio())
        total_events = 0
        partial_events = 0
        final_events = 0
        try:
            async for event in asr.receive_events():
                total_events += 1
                print(
                    f"[ASR] ← event#{total_events} type={event.type} "
                    f"transcript={getattr(event, 'transcript', '')!r}"
                )
                # 部分识别 / 句尾定稿 实时下发客户端
                await safe_send_json(ws, event_to_dict(event))
                # 句尾定稿 → 归一化为文本 query, 送统一 handle
                if event.type == "stt_chunk":
                    partial_events += 1
                if event.type == "stt_output":
                    final_events += 1
                    transcript = (event.transcript or "").strip()
                    print(f"[ASR] ★ FINAL transcript = {transcript!r}")
                    if transcript:
                        await handle_query(transcript, request_id, source="voice")
            print(
                f"[ASR] event stream ENDED: total={total_events} "
                f"partials={partial_events} finals={final_events}"
            )
            if total_events == 0:
                print(
                    "[ASR] ⚠️ 没有任何识别事件 — 重点检查: 1) 连接是否建立/卡住 "
                    "2) task-failed(NO_VALID_AUDIO) 3) 音频格式是否为 pcm16 16k mono"
                )
        except Exception as e:
            print(f"[ASR] consumer !!! {type(e).__name__}: {e}")
            logger.exception(f"[app_ai_entrance] voice pipeline failed: {e}")
            await safe_send_json(ws, {"type": "error", "error": f"voice pipeline: {e}"})
        finally:
            feed_task.cancel()
            with contextlib.suppress(BaseException):
                await feed_task
            # 显式暴露 feed 侧异常 (之前 await feed_task 只 suppress CancelledError,
            # 非取消异常被静默)
            if not feed_task.cancelled():
                try:
                    ferr = feed_task.exception()
                except Exception:
                    ferr = None
                if ferr:
                    print(f"[ASR] ⚠️ feed_task ended with {type(ferr).__name__}: {ferr}")
            with contextlib.suppress(Exception):
                await asr.close()
            print(f"[ASR] pipeline done req={request_id}")

    try:
        while True:
            # 空闲踢出: idle_timeout 内无任何消息 (含 ping) 则断开
            try:
                '''
                语音输入:       received msg -> {'type': 'websocket.receive', 'bytes': b'\x02\x00\x80\x00\x08\xfe\x02\x01S\xff'}
                语音输入结束:    received msg -> {'type': 'websocket.receive', 'text': '{"type":"end","audio_bytes":57330}'}
                文字输入:       received msg -> {'type': 'websocket.receive', 'text': '{"type":"query","query":"你好啊","request_id":"req-1789615606828-f4r99t"}'}
                切换tab或刷新：  received msg -> {'type': 'websocket.disconnect', 'code': 1012}
                
                '''
                message = await receive_message(ws, ws_config.idle_timeout)
                print(f'received msg -> {message}')
            except IdleTimeout:
                logger.info(f"[app_ai_entrance] idle timeout user={user_id}")
                await ws.close(code=CloseCode.GOING_AWAY, reason="idle timeout")
                return

            msg_type = message.get("type")
            if msg_type == "websocket.disconnect":
                break
            if msg_type != "websocket.receive":
                continue

            # 协议解析: 文本→JSON; 二进制帧返回 None 交给业务侧
            try:
                # parse_payload 只处理文本输入，如果没有，payload返回的是None
                payload = parse_payload(message, ws_config.max_message_size)
            except MessageTooBig:
                await safe_send_json(ws, {"type": "error",
                                          "error": f"message too large (>{ws_config.max_message_size}B)"})
                await ws.close(code=CloseCode.MESSAGE_TOO_BIG, reason="message too big")
                return
            except ValueError as e:
                await safe_send_json(ws, {"type": "error", "error": str(e)})
                continue

            # 二进制帧 (语音流等): 业务侧按 message["bytes"] 处理
            audio = message.get("bytes") if payload is None else None

            # 心跳: 客户端 ping → 服务端 pong (保活, 配合空闲踢出避免误杀)
            if payload is not None and payload.get("type") == "ping":
                await safe_send_json(ws, {"type": "pong"})
                continue

            # ── 业务消息分发: 文字 / 语音 归一化为文本 query ──────────────

            # 语音会话开始握手: {"type":"start","codec":"pcm_s16le","sample_rate":16000}
            # 前端录音前先发一条 start 声明编码, 后端目前直接忽略, 等音频帧真正到来再开管线
            if payload is not None and payload.get("type") == "start":
                sr = payload.get("sample_rate")
                codec = payload.get("codec")
                print(f"[app_ai_entrance] voice start: codec={codec} sample_rate={sr}")
                await safe_send_json(ws, {"type": "voice_started"})
                continue

            # 文字查询: {"type":"query","query":...,"request_id":...}
            if payload is not None and payload.get("type") == "query":
                # 速率限制 (每用户滑动窗口, 与语音共用配额)
                if not await limiter.allow(f"user:{user_id}"):
                    await safe_send_json(ws, {
                        "type": "error",
                        "error": f"rate limit exceeded ({RATE_LIMIT_CALLS}/min)",
                    })
                    continue
                if processing:
                    await safe_send_json(ws, {
                        "type": "error", "error": "busy: previous query in progress",
                    })
                    continue
                query = (payload.get("query") or "").strip()
                request_id = payload.get("request_id") or str(uuid.uuid4())
                processing = True
                try:
                    await handle_query(query, request_id, source="text")
                finally:
                    processing = False
                continue

            # 写操作确认 (HITL): {"type":"confirm","confirm_id":...,"action":"approve"|"reject"}
            # 从图 interrupt 暂停点恢复; 语音会话期间 processing=True 会被 busy 拒绝
            if payload is not None and payload.get("type") == "confirm":
                if processing:
                    await safe_send_json(ws, {"type": "error", "error": "busy"})
                    continue
                processing = True
                try:
                    await session.resolve_confirm(
                        payload.get("confirm_id") or "",
                        payload.get("action") or "reject",
                    )
                finally:
                    processing = False
                continue

            # 语音帧: 原始 PCM 二进制 → 喂给流式 ASR (首帧开启语音会话)
            if audio is not None:
                if not voice_mode and not processing:
                    # 语音会话启动也消耗限流配额 (整个会话计 1 次, 句尾定稿不再重复计)
                    if not await limiter.allow(f"user:{user_id}"):
                        await safe_send_json(ws, {
                            "type": "error",
                            "error": f"rate limit exceeded ({RATE_LIMIT_CALLS}/min)",
                        })
                        continue
                    voice_mode = True
                    processing = True
                    audio_queue = asyncio.Queue()
                    voice_request_id = str(uuid.uuid4())
                    voice_task = asyncio.create_task(
                        process_voice_query(audio_queue, voice_request_id)
                    )
                if voice_mode and audio_queue is not None:
                    await audio_queue.put(audio)
                continue

            # 语音结束: {"type":"end","audio_bytes":N} → 结束信号, 等待 ASR 定稿
            if payload is not None and payload.get("type") == "end":
                if not voice_mode:
                    continue
                if audio_queue is not None:
                    await audio_queue.put(None)
                if voice_task and not voice_task.done():
                    try:
                        await asyncio.wait_for(voice_task, timeout=30.0)
                        print("[ASR] voice task finished normally")
                    except asyncio.TimeoutError:
                        print("[ASR] ⚠️ voice task 超时 30s 未结束 (连接卡住?), 强制 cancel")
                        voice_task.cancel()
                    except Exception as ve:
                        print(f"[ASR] ⚠️ voice task raised {type(ve).__name__}: {ve}")
                        logger.exception("[app_ai_entrance] voice task error")
                voice_mode = False
                processing = False
                continue

            # 未知文本消息
            if payload is not None:
                await safe_send_json(ws, {
                    "type": "error", "error": f"unknown type: {payload.get('type')}",
                })

    except WebSocketDisconnect:
        logger.info(f"[app_ai_entrance] client disconnected user={user_id}")
        return
    except Exception:
        logger.exception(f"[app_ai_entrance] unhandled exception user={user_id}")
        try:
            await ws.close(code=CloseCode.INTERNAL_ERROR, reason="internal error")
        except Exception:
            pass
        return
    finally:
        # 清理未结束的语音会话 (客户端中途断开时取消 ASR 任务)
        if voice_task is not None and not voice_task.done():
            voice_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await voice_task
        await connection_manager.release(ws, user_id)
        logger.info(f"[app_ai_entrance] connection released user={user_id}")
