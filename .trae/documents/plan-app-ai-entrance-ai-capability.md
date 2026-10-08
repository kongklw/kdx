# app_ai_entrance.py 接入 AI 能力（agent 执行）实现方案

## Context

`app/ws/app_ai_entrance.py` 是应用 AI 主入口（文字 + 语音统一归一化为文本 query），`handle_query()` 中的 TODO（L119）待实现 agent 执行。经探索，AI 能力主体**已经存在**，无需重写：

- `app/assistant/graph.py`：完整 LangGraph 图（两级意图识别 → agent(ReAct 工具调用) / rag / chitchat / fallback 路由，写操作 `interrupt()` 做 HITL 确认），`get_compiled_graph()` 进程级单例
- `app/assistant/runtime.py`：contextvar 注入 emit 回调 / 用户身份（`set_runtime_context`）
- `app/ws/baby_assistant.py`：已有一套完整接入参考（confirm 恢复协议）

本任务 = 新增 service 层封装 + 在 WS 层接线（用户已确认三个决策）：
1. **代码组织**：封装到 service 层（符合文件头"当前路由层，只简单调用"的约定）
2. **事件格式**：平铺格式 `{"type": "generate_chunk", "chunk": "..."}`（与本文件现有事件一致）
3. **thread_id**：每用户一个 `user-{user_id}`（与 baby_assistant.py 一致）

## 变更 1：新建 `app/services/assistant_service.py`

`AssistantSession` 类，封装图执行细节，emit 回调由 WS 层注入（WS 无关，可复用/可测试）：

```python
class AssistantSession:
    def __init__(self, user_id: int, thread_id: str,
                 emit: Callable[[str, dict], Awaitable[None]]):
        # emit: async (event_type, data) -> None，WS 层用 safe_send_json 平铺下发
        self._graph = get_compiled_graph()   # app/assistant/graph.py L709 进程级单例
        self.pending_confirm: Optional[dict] = None  # {"confirm_id", "request_id", "ts"}

    async def run_query(self, query: str, request_id: str) -> None:
        # 1) 防御：graph.get_state(config) 发现遗留 pending interrupt（如断线残留）且本地无挂起
        #    → 先 Command(resume={"action": "reject"}) 干净取消，再跑新 query
        # 2) set_runtime_context(user_id, request_id, emit, thread_id) → try/finally reset
        # 3) graph.ainvoke(initial_state, {"configurable": {"thread_id": ...}})
        #    initial_state 不含 messages（由 checkpointer 恢复多轮历史），
        #    仅 user_id/query/request_id/tool_trace=[]/tool_rounds=0
        # 4) 结果含 "__interrupt__" → 提取载荷存 pending_confirm，
        #    emit("confirmation_request", {request_id, confirm_id, tools, message})
        # 5) 正常结束 → emit("query_done", {request_id, intent, route, tool_trace, sources})
        #    异常 → emit("query_error", {request_id, error})

    async def resolve_confirm(self, confirm_id: str, action: str) -> None:
        # 无 pending / confirm_id 不匹配 → query_error
        # reject → Command(resume={"action": "reject"}) 走图内取消分支（线程干净收尾，
        #          图返回后补发 generate_chunk/answer_done/query_done，取消文案"好的，已取消本次操作。"）
        # approve → Command(resume={"action": "approve"}) 恢复执行（图内自动完成工具执行+总结）
        #           图若再次 interrupt（多轮写确认）→ 重新下发 confirmation_request
        # 全程同样注入 runtime context，finally 清 pending_confirm
```

复用的现有实现（不重复造）：
- `app/assistant/graph.py`：`get_compiled_graph`、`AssistantState`
- `app/assistant/runtime.py`：`set_runtime_context` / `reset_runtime_context`
- `langgraph.types.Command`（baby_assistant.py L248-249 同款用法）

## 变更 2：修改 `app/ws/app_ai_entrance.py`

1. **L64-68 疑问注释改写为结论注释**：`thread_id = user-{user_id}` 每用户一个 thread；每次 `ainvoke` 只是追加新 checkpoint，**不会**自动 resume/time travel；interrupt 恢复仅发生在显式 `Command(resume=...)` 时，由 service 层的 pending_confirm 状态机管理
2. 连接建立后（accept 之后）创建 `AssistantSession`，emit 闭包用 `safe_send_json` 平铺下发：`{"type": event_type, **data}`
3. `handle_query()` TODO 处替换为：
   ```python
   if session.pending_confirm:
       await safe_send_json(ws, {"type": "error",
           "error": "pending write confirmation, please approve/reject first"})
       return
   await session.run_query(query, request_id)
   ```
4. **新增 `confirm` 消息分支**（与 query 同受 `processing` 互斥）：`{"type":"confirm","confirm_id":"CFM-...","action":"approve"|"reject"}` → `session.resolve_confirm(...)`；processing 中回 busy error
5. 模块 docstring 补充协议文档（上行 confirm；下行事件清单见下）

不改动：鉴权 / 连接管理 / 心跳 / 语音 ASR 管线 / core.ws。

## 事件协议（平铺格式，均含 `request_id`，与本文件 `query_received`/`stt_chunk` 风格一致）

```
Client → Server (新增):
  {"type": "confirm", "confirm_id": "CFM-...", "action": "approve" | "reject"}

Server → Client (新增，来自图内 emit 平铺转发):
  intent_start / intent_detected / retrieve_start / retrieve_done
  tool_call {id, name, args} / tool_result {id, name, result, ok}
  confirmation_request {confirm_id, tools, message}   ← HITL 写确认
  generate_chunk {chunk} / answer_done {answer, sources?, tool_trace?}
  query_done {request_id, intent, route, tool_trace, sources}
  query_error {request_id, error}
```

注意：语音会话期间 `processing=True` 且 `handle_query` 在 `process_voice_query` 内被 await，confirm 消息此时会被 busy 拒绝（与 baby_assistant.py 行为一致），docstring 注明。

## Verification

1. **导入检查**：`cd /home/konglingwen/myspace/kdx/kdx-ws-be && python -c "from app.main import app"`
2. **端到端 WS 测试**（临时脚本放 /tmp，用 `app/core/security` 签发 JWT）连 `/ws/app-ai-entrance?token=...`：
   - `{"type":"query","query":"你好"}` → 期望 intent_detected(chitchat) + generate_chunk 流 + answer_done + query_done
   - `{"type":"query","query":"记录喂奶80毫升"}` → 期望 intent_detected(data_query) + tool_call + confirmation_request
   - `{"type":"confirm","action":"reject"}` → 取消文案 + query_done；再测 approve → tool_result + query_done
   - 验证多轮记忆：连续两条相关 query，第二次能引用上文
3. **依赖**：DASHSCOPE_API_KEY（.env）；MySQL/Redis 走 docker compose（Redis 不可用时幂等自动回退内存，已确认 `resilience.py` L147 容错）
