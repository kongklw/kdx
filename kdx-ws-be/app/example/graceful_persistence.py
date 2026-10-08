"""
优雅持久化降级 (delivered-then-persist-failed)
===============================================

一、核心概念
  一次 query 的生命周期里, 故障发生在不同时刻, 客户端应该得到完全不同的响应:

    ┌─────────────────────────────┬───────────────────────────┐
    │ 故障时机                     │ 正确的客户端响应            │
    ├─────────────────────────────┼───────────────────────────┤
    │ 内容送达前 (意图/LLM/检索失败) │ query_error (真失败)       │
    │ 内容送达后 (收尾持久化失败)    │ query_done(degraded=true) │
    └─────────────────────────────┴───────────────────────────┘

  "内容送达后持久化失败"的典型场景: 图执行完成、answer 已流式下发, 但
  langgraph checkpointer 收尾写 Redis (保存最终 checkpoint / 多轮记忆) 超时。
  此时 ainvoke 抛异常, 但用户其实已经看到了完整回答——再发 query_error 会造成
  UX 矛盾 (界面上答案显示正常, 却弹出错误)。

  解法 (services/assistant_service.py AssistantSession._tracked_emit):
    1. 用 shim 包装 emit, 记录已下发的事件类型 (seen 集合)
    2. 异常处理时检查 seen: 出现过 answer_done / confirmation_request
       → 内容已送达, 降级为 query_done(route="degraded", degraded=True)
    3. 否则 → 维持 query_error

二、生产实践方案
    1. 根因治理优先于容错: 本例的超时根因是应用与 Redis 跨公网 (WAN RTT 抖动),
       生产部署 Redis 必须与应用同 VPC; 容错分支只是兜底不是解药
    2. 客户端契约: 收到 degraded=true 的 query_done 视为成功 (答案已渲染),
       可选展示轻提示 "回答已完成, 本次记录可能未同步"; 绝不能当错误弹窗
    3. 代价要知情: 降级意味着该轮对话的最终状态没进 checkpointer, 下一轮
       多轮记忆可能"少记一嘴"——对闲聊/RAG 无感, 对 agent 可接受
    4. 可观测性: degraded 事件应打点告警, 持续出现 = Redis 健康度恶化信号
       (llm_gateway 的计量日志同理); 静默吞掉会把慢性故障拖成事故
    5. 双路径覆盖: run_query 和 _resume (HITL 恢复) 都要做同样的分支,
       只修一条路径等于留了一半的洞

三、面试话术
  "AI 应用的异常处理不能按'成功/失败'二分, 要按'用户价值是否已交付'划分。
   我们的生产事故里, RAG 回答都流式显示完了, checkpointer 收尾写 Redis 超时
   导致 ainvoke 抛异常, 服务端又补发一条 query_error——客户端刚渲染完答案就
   弹错误。修复方式是给 emit 加一层 tracking shim, 异常时根据'已送达事件'
   分流: 送达过的降级成带 degraded 标记的 query_done, 没送达的才是真 error。
   同时打点 degraded 速率作为 Redis 健康度信号。这是把分布式系统里
   'at-least-once 交付后的确认失败'思想搬到了流式 AI 会话上。"

四、可运行示例
    cd kdx-ws-be && .venv/bin/python -m app.example.graceful_persistence
    (纯内存模拟, 无需 LLM / Redis / 网络; 三个场景全部带断言)

五、LangGraph 伪代码 (故障点与防护位置示意)
    result = await graph.ainvoke(state, config)   # ← 内部时序:
    #   entry → intent → rag/agent → 流式 emit(answer_done)   ← 用户已看到答案
    #   → checkpointer.aput(final state)                      ← 这里超时抛异常
    # 防护: emit 经 _tracked_emit shim 进入 runtime contextvar,
    #       ainvoke 抛异常后 run_query 检查 seen 再决定 query_done(degraded)
    #       还是 query_error
"""

import asyncio
import json
from typing import Any, Dict, List

from app.services.assistant_service import AssistantSession


# ──────────────────────────────────────────────
# 测试基建: 最小 AssistantSession + 可编程 FakeGraph
# ──────────────────────────────────────────────

def make_session(events: List[Dict[str, Any]]) -> AssistantSession:
    """绕过 __init__ 构造最小可跑 run_query 的会话 (不碰 Redis/LLM)"""
    sess = object.__new__(AssistantSession)
    sess.user_id = 99002
    sess.thread_id = "demo-graceful"
    sess.pending_confirm = None
    sess._graph = None  # 由各场景注入

    async def capture_emit(event_type: str, data: Dict[str, Any]) -> None:
        events.append({"type": event_type, **data})

    sess._emit = capture_emit

    async def no_pending() -> bool:  # 隔离 stale-interrupt 防御 (真实实现查 Redis)
        return False

    async def no_interrupt(result: Any, request_id: str) -> bool:
        return False

    sess._has_pending_interrupt = no_pending
    sess._handle_interrupt = no_interrupt
    return sess


class FakeGraph:
    """模拟真实图: emit_after_delivery=True 时先像 rag_node 一样经 runtime
    context 送出回答, 再在 checkpointer 收尾阶段抛 Redis 超时"""

    def __init__(self, emit_after_delivery: bool):
        self.emit_after_delivery = emit_after_delivery

    async def ainvoke(self, state, config):
        from app.assistant.runtime import get_runtime_context
        ctx = get_runtime_context()
        if self.emit_after_delivery:
            # 模拟 rag_node: 流式回答已完整送达客户端
            await ctx.emit("generate_chunk", {"chunk": "保持皮肤湿润..."})
            await ctx.emit("answer_done", {"answer": "保持皮肤湿润，避免刺激..."})
        raise TimeoutError(
            "Timeout reading from 47.95.15.228:6379")  # checkpointer.aput 超时


async def run(sess: AssistantSession, rid: str) -> None:
    await sess.run_query("宝宝湿疹怎么办", rid)


# ──────────────────────────────────────────────
# 示例 1: 内容送达后持久化失败 → 降级 query_done(degraded)
# ──────────────────────────────────────────────

async def demo_degraded_after_delivery() -> None:
    print("── 1. answer 已送达, checkpointer 写 Redis 超时 ──")
    events: List[Dict[str, Any]] = []
    sess = make_session(events)
    sess._graph = FakeGraph(emit_after_delivery=True)
    await run(sess, "req-1")

    tail = events[-1]
    print("  事件序列:", [e["type"] for e in events])
    print("  收尾事件:", json.dumps(tail, ensure_ascii=False)[:150])
    assert tail["type"] == "query_done", "必须是 query_done 而非 query_error"
    assert tail["degraded"] is True and tail["route"] == "degraded"
    assert "answer_done" in [e["type"] for e in events]
    print("  [PASS] 客户端正常收尾 (degraded=true), 不再出现矛盾报错\n")


# ──────────────────────────────────────────────
# 示例 2: 内容送达前就失败 → 维持 query_error (真失败)
# ──────────────────────────────────────────────

async def demo_error_before_delivery() -> None:
    print("── 2. 意图/LLM 阶段就挂了, 用户什么都没收到 ──")
    events: List[Dict[str, Any]] = []
    sess = make_session(events)
    sess._graph = FakeGraph(emit_after_delivery=False)
    await run(sess, "req-2")

    tail = events[-1]
    print("  事件序列:", [e["type"] for e in events])
    print("  收尾事件:", json.dumps(tail, ensure_ascii=False)[:150])
    assert tail["type"] == "query_error", "未送达内容必须报 query_error"
    assert "Timeout" in tail["error"]
    print("  [PASS] 真失败仍走 query_error, 客户端可重试\n")


# ──────────────────────────────────────────────
# 示例 3: HITL 确认卡已送达后持久化失败 → 同样降级
# ──────────────────────────────────────────────

async def demo_degraded_after_confirm_card() -> None:
    print("── 3. confirmation_request 已送达, 收尾持久化失败 ──")
    events: List[Dict[str, Any]] = []
    sess = make_session(events)
    sess._graph = None

    class ConfirmGraph(FakeGraph):
        async def ainvoke(self, state, config):
            from app.assistant.runtime import get_runtime_context
            await get_runtime_context().emit("confirmation_request", {
                "request_id": "req-3", "confirm_id": "CFM-x",
                "tools": [{"name": "add_todo", "args": {"title": "明天打疫苗"}}],
                "message": "即将写入宝宝数据，请确认",
            })
            raise TimeoutError("Timeout reading from 47.95.15.228:6379")

    sess._graph = ConfirmGraph(False)
    await run(sess, "req-3")

    tail = events[-1]
    print("  事件序列:", [e["type"] for e in events])
    assert tail["type"] == "query_done" and tail["degraded"] is True
    print("  [PASS] 确认卡已送达 → 降级收尾, 用户仍可继续 confirm\n")


async def main() -> None:
    await demo_degraded_after_delivery()
    await demo_error_before_delivery()
    await demo_degraded_after_confirm_card()
    print("全部场景通过。真实链路: 修复已在线上验证 — "
          "RAG answer_done 后 Redis 超时, 客户端收到 query_done(degraded=true)。")


if __name__ == "__main__":
    asyncio.run(main())
