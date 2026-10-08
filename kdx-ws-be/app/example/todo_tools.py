"""
待办工具 AI 接入 (query_todos / add_todo / complete_todo)
=========================================================

一、核心概念
  待办应用原本只有 REST 接口 (/todos, app/api/todo.py)。本例演示如何把一个
  已有业务"接入" LangGraph Agent 的工具集, 使其可被语音/文字自然语言驱动:

      用户: "帮我记一个待办: 明天带宝宝打疫苗"
        → intent (规则/LLM) → agent_node (Function Calling 决策)
        → confirm_node (HITL 纯函数节点, 写操作 interrupt 暂停)
        → tools 节点执行 add_todo → LLM 总结 → answer_done

  关键设计:
    1. 复用而非重写: AI 工具直接调用 TodoService (与 REST 同一数据源),
       保证 HTTP 客户端和 AI 客户端看到同一份待办数据
    2. 存储后端可切换: create_todo_repository 按 TODO_REPO 环境变量选择
       Redis (RedisTodoRepository) / 进程内存 (InMemoryTodoRepository)
    3. 写操作全部经过 HITL 确认门, 与喂奶/体温等其他写工具一致

二、使用文档
  ─────────────────────────────────────────────
  工具            类型    LLM 参数                          说明
  ─────────────────────────────────────────────
  query_todos     读     only_pending?: bool               列表查询
  add_todo        写     title: str (必填)                 新建, 触发 HITL
  complete_todo   写     todo_id? / title_match?: str      完成/取消完成
                         completed?: bool (默认 true)      二选一, 支持标题模糊匹配
  ─────────────────────────────────────────────
  user_id / request_id 由 Agent 层注入 (contextvar runtime), 不暴露给 LLM。

  自然语言示例 (语音转写或文字均可):
    "帮我记一个待办: 明天带宝宝打疫苗"   → add_todo (确认卡展示 title)
    "我现在有哪些待办?"                  → query_todos
    "我还有什么事没做完?"                → query_todos(only_pending=true)
    "打疫苗这件事办好了"                 → complete_todo(title_match="打疫苗")

  WS 协议交互 (写操作):
    C: {"type":"query","query":"记一个待办:明天打疫苗","request_id":"req-1"}
    S: {"type":"confirmation_request","confirm_id":"CFM-xxx",
        "tools":[{"name":"add_todo","args":{"title":"明天打疫苗"},...}],
        "message":"即将写入宝宝数据，请确认(...):\n· add_todo: title=明天打疫苗"}
    C: {"type":"confirm","confirm_id":"CFM-xxx","action":"approve"}
       (或 reject / approve+modified_args={"add_todo":{"title":"..."}})
    S: {"type":"tool_result",...} → {"type":"answer_done",...} → {"type":"query_done"}

三、生产实践方案
    1. 进程级缓存: TodoService 实例必须缓存 (本例 _todo_service 用函数属性),
       否则 InMemory 仓库按调用新建 → 写入的实例和读取的实例互相看不见
    2. 多实例部署: 设 TODO_REPO=redis, HTTP 与 AI 共享 Redis hash (todo:{user_id},
       TTL 180 天); InMemory 仅适合单实例开发
    3. 幂等: 写工具统一接受 request_id, 由 IdempotencyManager (idem:* 键) 去重,
       客户端重试/断线重发不会重复创建待办
    4. HITL 一致性: 所有写工具 (is_write=True) 自动进 confirm_node 确认门,
       新增写工具时无需改图
    5. title_match 模糊匹配: LLM 通常只拿到标题拿不到 uuid, 服务端做
       contains 匹配兜底; 多条命中取最新一条并可通过 query_todos 先查再改

四、面试话术
  "接入一个已有业务到 Agent, 我的原则是复用 service 层而不是绕过它直连存储。
   待办工具和 REST 接口共用 TodoService, 数据源一致, 权限语义一致 (user_id 由
   runtime 注入, LLM 无法伪造)。写操作沿用统一的 HITL 确认门和幂等管理器,
   新工具只需要注册 schema 和 handler, 图本身零改动——这就是工具注册表 +
   纯函数确认节点架构带来的扩展性。"

五、可运行示例
    cd kdx-ws-be && .venv/bin/python -m app.example.todo_tools
    (默认走 InMemory 仓库, 无外部依赖; TODO_REPO=redis 时写共享 Redis)
"""

import asyncio

from app.assistant.tools import make_tools
from app.assistant.tool_registry import build_default_registry


# ──────────────────────────────────────────────
# 示例 1: 直接调用工具层 (不经 LLM, 验证数据流)
# ──────────────────────────────────────────────

def demo_tool_calls() -> None:
    print("── 1. 工具层直调 (user_id 注入, 无 LLM) ──")
    t = make_tools()
    uid = 99001  # 演示专用 user

    created = t["add_todo"](uid, "明天带宝宝打疫苗", request_id="demo-add-1")
    print("add_todo        →", created)
    assert created["ok"]

    listed = t["query_todos"](uid)
    print("query_todos     →", {"total": listed["total"],
                                "titles": [x["title"] for x in listed["todos"]]})

    done = t["complete_todo"](uid, title_match="打疫苗", request_id="demo-done-1")
    print("complete_todo   →", done)
    assert done["ok"] and done["todo"]["completed"]

    pending = t["query_todos"](uid, only_pending=True)
    print("only_pending    →", {"total": pending["total"]})
    assert pending["total"] == 0

    miss = t["complete_todo"](uid, title_match="不存在的", request_id="demo-miss-1")
    print("未命中          →", miss)
    assert not miss["ok"]

    _cleanup(uid)
    print("   [PASS] 增 → 查 → 标题匹配完成 → 未完成清零 → 未命中优雅报错\n")


def _cleanup(user_id: int) -> None:
    """清理演示数据 (InMemory 随进程消亡; TODO_REPO=redis 时显式删除)"""
    from app.core.config import get_settings
    from app.integrations.todo_repo import create_todo_repository
    from app.services.todo_service import TodoService
    svc = TodoService(create_todo_repository(get_settings()))
    for item in svc.list_items(str(user_id)):
        svc.delete_item(str(user_id), item.id)


# ──────────────────────────────────────────────
# 示例 2: 注册表视角 (HITL 门自动生效)
# ──────────────────────────────────────────────

def demo_registry() -> None:
    print("── 2. 工具注册表: 写操作自动进 HITL 确认门 ──")
    reg = build_default_registry()
    for name in ("query_todos", "add_todo", "complete_todo"):
        meta = reg.get(name)
        print(f"{name:14s} is_write={reg.is_write_tool(name)}  params={list(meta.parameters.get('properties', {}))}")
    total = len(reg._tools) if hasattr(reg, "_tools") else "?"
    print(f"注册表工具总数: {total} (新增待办 3 个, 图零改动)\n")


# ──────────────────────────────────────────────
# 示例 3: WS 全链路 (需本地起服务; 默认跳过)
# ──────────────────────────────────────────────

async def demo_ws_flow(port: int = 8765) -> None:
    """端到端: 自然语言 → confirmation_request → approve → answer_done。

    先起服务: cd kdx-ws-be && .venv/bin/python -m uvicorn app.main:app --port 8765
    再运行:   .venv/bin/python -m app.example.todo_tools ws
    """
    import hashlib
    import hmac
    import base64
    import json
    import time as _time

    import websockets

    from app.core.config import get_settings

    s = get_settings()
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    h = b64(json.dumps({"alg": s.jwt_algorithm, "typ": "jwt"}).encode())
    p = b64(json.dumps({"user_id": 1, "exp": _time.time() + 7200}).encode())
    d = {"HS256": hashlib.sha256, "HS384": hashlib.sha384,
         "HS512": hashlib.sha512}[s.jwt_algorithm]
    sig = b64(hmac.new(s.secret_key.encode(), f"{h}.{p}".encode(), d).digest())

    async with websockets.connect(
            f"ws://127.0.0.1:{port}/ws/app-ai-entrance?token={h}.{p}.{sig}",
            max_size=1 << 22) as ws:
        print(await ws.recv())  # connected
        await ws.send(json.dumps({"type": "query",
                                  "query": "帮我记一个待办: 明天带宝宝打疫苗",
                                  "request_id": f"demo-ws-{_time.time()}"}))
        while True:
            ev = json.loads(await ws.recv())
            if ev["type"] == "confirmation_request":
                print("confirmation_request:", ev["message"])
                await ws.send(json.dumps({"type": "confirm",
                                          "confirm_id": ev["confirm_id"],
                                          "action": "approve"}))
            elif ev["type"] in ("answer_done", "query_done"):
                print(f"{ev['type']}:", ev)
                if ev["type"] == "query_done":
                    break


# ──────────────────────────────────────────────
# LangGraph 伪代码 (接入位置示意)
# ──────────────────────────────────────────────
#
#   graph: entry → agent → confirm → (tools | give_up | end) → ...
#
#   def agent_node(state):            # LLM 决策, 不执行
#       resp = llm.bind_tools(registry.schemas).invoke(msgs)
#       return {"tool_calls": resp.tool_calls}
#
#   def confirm_node(state):          # 纯函数节点, 写操作 interrupt
#       writes = [c for c in state.tool_calls if registry.is_write_tool(c.name)]
#       if writes:
#           decision = interrupt({"tools": writes, "message": _confirm_summary(writes)})
#           if decision.action == "reject":
#               return {"answer": "已取消", "tool_calls": None}
#       return {"tool_calls": state.tool_calls}
#
#   def tools_node(state):            # 实际执行 (add_todo 在此运行)
#       for c in state.tool_calls:
#           result = registry.get(c.name).handler(user_id=runtime.user_id,
#                                                 request_id=runtime.request_id,
#                                                 **c.args)   # ← TodoService.create_item


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "ws":
        asyncio.run(demo_ws_flow())
    else:
        demo_tool_calls()
        demo_registry()
        print("全部示例通过。运行 'python -m app.example.todo_tools ws' 可看 WS 全链路。")
