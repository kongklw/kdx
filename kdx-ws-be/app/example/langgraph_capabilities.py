"""
LangGraph 十大 Capabilities 详解 + Baby Assistant 项目落地对照 (面试版)

官网 Capabilities 列表:
Persistence / Checkpointers / Stores / Fault tolerance / Event streaming /
Streaming / Interrupts / Time travel / Memory / Subgraphs

每个能力按四段讲:
1. 概念本质 (官网定义的人话版)
2. 生产实践方案
3. Baby Assistant 项目现状与升级路径 (graph.py / ws/baby_assistant.py)
4. 面试话术

可运行示例见文件底部 demo(), 覆盖: checkpointer + interrupt + time travel + store + subgraph。
环境: langgraph==1.2.9, langgraph-checkpoint==4.1.1 (requirements.txt)
"""

# ═══════════════════════════════════════════════════════════
# 1. Persistence (持久化)
# ═══════════════════════════════════════════════════════════
# [概念] 图的执行状态(每个 super-step 后的完整 state)能被保存下来,
#        图可以停在任何一步, 之后从断点继续 —— 是其他所有能力的基础设施。
#        按 thread_id 隔离: 同一 thread 的多轮对话共享状态历史。
#
# [生产] - 会话型 Agent 必配: thread_id = 会话ID, 跨请求保持上下文
#        - 后端无状态水平扩容: 状态在 Postgres, 任何实例都能接手任意会话
#        - 多端同步: 手机/网页同一个 thread_id, 上下文一致
#
# [项目现状] graph.py: build_assistant_graph() 编译时【没有】传 checkpointer,
#            多轮记忆靠 ws/baby_assistant.py 连接级 history 列表手工维护。
#            局限: ① WS 断开历史即丢 ② 只能单机单连接 ③ 无法断点恢复。
# [升级]     compile(checkpointer=PostgresSaver(...)), WS 层传 thread_id=str(user_id),
#            删除手工 history —— 3 行代码替换一整套手工状态管理。
#
# [话术] "我的项目当前用连接级 history 管多轮对话, 我清楚它的局限,
#         生产方案是 PostgresSaver checkpointer + thread_id, 状态外置后
#         服务天然无状态, 可以水平扩容。"


# ═══════════════════════════════════════════════════════════
# 2. Checkpointers (检查点)
# ═══════════════════════════════════════════════════════════
# [概念] Persistence 的具体实现组件。图每执行一个 super-step(一个节点跑完),
#        自动把 state 快照存到 checkpointer 存储里, 形成 (thread_id, checkpoint_id) 索引。
#        官方提供 InMemorySaver(测试) / SqliteSaver(单机) / PostgresSaver(生产) / RedisSaver。
#
# [生产] - PostgresSaver: async 版 async_postgres.AsyncPostgresSaver, 配连接池
#        - 注意: state 里存不了的对象(WebSocket 连接/锁)要放到 graph 外,
#          或用 RunnableConfig 注入 —— 这正是我项目把 ws 作为节点工厂参数闭包捕获的原因
#        - checkpoint 表要定期清理或按 TTL 归档, 防止无限膨胀
#
# [项目现状] resilience.py 的 IdempotencyManager 是连接级内存去重; graph 每个节点
#            完成后把中间产物写回 AssistantState —— 相当于"逻辑上的状态机推进",
#            但没有物理快照。
# [话术] "checkpoint 让'图的执行'变成可恢复事务: 任何一步崩溃都能从上一个
#         super-step 重放, 我项目里的熔断+幂等解决的是下游调用的可靠性,
#         checkpointer 解决的是图执行本身的可靠性, 两层互补。"


# ═══════════════════════════════════════════════════════════
# 3. Stores (跨会话存储)
# ═══════════════════════════════════════════════════════════
# [概念] 与 thread 无关的键值/文档存储, 按 (namespace, key) 组织, 跨会话、跨 thread 共享。
#        Checkpointer = "这次对话进行到哪了"; Store = "这个用户是谁、偏好什么"。
#        支持语义检索(向量)的 BaseStore 实现可以做长期记忆召回。
#
# [生产] - 存用户画像: "宝宝对青霉素过敏"、"偏爱母乳喂养" —— 任何新会话都能召回
#        - few-shot 记忆: 把用户纠偏过的回答存起来, 检索后注入 prompt
#        - namespace 设计: ("preferences", user_id) / ("facts", user_id)
#
# [项目现状] graph.py: _load_baby_context() 每轮查 MySQL 拼宝宝上下文注入 system ——
#            这就是"每轮拉取的共享记忆", 但它是结构化数据而非记忆系统。
# [升级]     闲聊/咨询中 LLM 识别到的长期事实(过敏原、习惯)写 Store,
#            entry 节点 search 注入 —— 从"查表"升级为"记忆"。
# [话术] "我项目注入的是结构化的宝宝档案, 遇到'自由文本型长期记忆'
#         (比如用户随口说宝宝对芒果过敏)我会用 LangGraph Store 按用户
#         namespace 存储, entry 节点语义检索召回注入 prompt。"


# ═══════════════════════════════════════════════════════════
# 4. Fault tolerance (容错)
# ═══════════════════════════════════════════════════════════
# [概念] 有了 checkpointer, 图执行的容错=从最近 checkpoint 重放:
#        节点执行 → 存快照 → 崩溃 → 重启 → 从快照后继续, 已成功的节点不重复执行。
#        要求节点操作幂等(重放语义), LangGraph 官方建议把"有副作用的写"设计为可重试。
#
# [生产] - LLM 调用: 配 tenacity 指数退避重试(我项目 requirements 里有 tenacity)
#        - 图级: 崩溃恢复靠 checkpoint 重放
#        - 下游服务: 熔断器防止雪崩
#        - 三层各管一段: 重试管瞬时错误, 熔断管持续故障, checkpoint 管进程崩溃
#
# [项目现状] resilience.py: LLMCircuitBreaker(三态机 Closed→Open→Half-Open) + 幂等管理器;
#            graph.py: agent 节点 except CircuitOpenError 时降级为模板回答。
#            容错是"应用层手工实现"的, 没有图级 checkpoint 重放。
# [话术] "我按层做了容错: 工具调用有熔断+幂等, LLM 失败降级模板回答;
#         生产再加 checkpointer, 进程重启后从最近快照重放, 三层防线。"


# ═══════════════════════════════════════════════════════════
# 5. Event streaming (事件流) 与 6. Streaming (流式)
# ═══════════════════════════════════════════════════════════
# [概念]
#   Event streaming: 用 astream_events / astream(stream_mode=...) 拿到图执行过程的
#       结构化事件流 —— 哪个节点开始/结束、LLM token、自定义事件, 前端可渲染执行轨迹。
#   Streaming: 狭义指 LLM token 级流式输出(stream_mode="messages")。
#   stream_mode 可多选: ["updates", "messages", "custom", "debug", "values"]
#       updates=每个节点的 state 增量 / messages=LLM token / custom=节点内自定义
#
# [生产] - token 流给前端打字机效果; updates 流渲染"正在查询数据..."步骤条;
#          custom 事件透传工具调用进度
#        - WebSocket 场景: 把 astream 事件映射为 JSON 事件帧 (type/payload)
#
# [项目现状] graph.py: emit() 函数在节点内部手动推送业务事件
#            (intent_detected / tool_start / tool_result / generate_chunk / answer_done),
#            LLM token 用 llm.astream + breaker.call_stream 手工循环 —— 等价于
#            stream_mode="messages"+"custom" 的手工版, 前端 AssistantChat.vue 按事件类型渲染。
# [升级]     改为 astream_events 统一消费, 节点内只 yield 自定义事件;
#            好处是事件协议标准化、不依赖每个节点自觉调用 emit。
# [话术] "我选了 WebSocket + 自定义事件协议而不是 SSE, 因为 HITL 确认
#         需要双向通道; token 流用 call_stream 包装熔断器实现流式。
#         官方的 astream_events 是它的标准化替代, 我知道如何迁移。"


# ═══════════════════════════════════════════════════════════
# 7. Interrupts (中断 / HITL)
# ═══════════════════════════════════════════════════════════
# [概念] 官方的人工介入原语: 节点内调用 interrupt(payload) → 图暂停, state 已被
#        checkpointer 持久化; 人工决策后用 Command(resume=决策值) 从【同一行代码】恢复执行,
#        interrupt() 的返回值就是用户的决策。暂停点 = 事务挂起点。
#
# [生产] - 高危写操作前置确认(删除/支付/医嘱类)
#        - 信息不足时向用户反问(slot filling)
#        - 审批流: resume 值携带 approve/reject/edit + 修改后的参数
#
# [项目现状] graph.py: route_after_agent 把 pending_write 路由到 wait_confirm(=END),
#            WS 层 pending 变量保存挂起上下文, 用户点确认后 resume=True 直通 tools ——
#            这是 interrupt 的手工等价实现! 区别:
#              手工版: 挂起状态在 WS 连接内存, 断线即丢
#              官方版: 挂起状态在 checkpointer, 断线重连/换设备都能恢复确认
# [升级]     tool_exec 节点开头: decision = interrupt({"tool":..., "args":...}),
#            决策后 resume → 删掉 WS 层 pending/resume 逻辑。
# [话术] "我在项目里手工实现了 HITL: 条件边路由到 wait_confirm 出口,
#         WS 层挂起等确认。我理解官方 interrupt 的本质是一样的 ——
#         都是把图的执行切成'确认前/确认后'两个事务, 官方版多了
#         checkpointer 持久化, 所以能跨连接恢复, 这是我的升级方向。"


# ═══════════════════════════════════════════════════════════
# 8. Time travel (时间旅行)
# ═══════════════════════════════════════════════════════════
# [概念] checkpointer 保留了 state 历史 → 可以: get_state_history() 回看任意时刻的
#        完整状态; update_state() 修改历史某一步的 state; 从历史 checkpoint 重新
#        invoke(None, config) 分叉重放(分支执行)。
#
# [生产] - 调试: "为什么回答错误?" → 回放当时的完整 state 定位是路由错还是工具错
#        - 审计合规: 医疗/金融场景, 每一步决策可回溯
#        - 用户"撤回上一条" → 从上一个 checkpoint 重跑
#        - bad case 沉淀: 把出错时刻的 state 存成回归测试集
#
# [项目现状] 无。日志里有 tool_trace 但不是可回放的状态快照。
# [话术] "time travel 依赖 checkpoint 历史, 我项目要支持'撤回重问'
#         的话, 开 PostgresSaver 后 get_state_history + 从指定 checkpoint
#         重放即可, 本质是把图的执行当成可版本化的数据。"


# ═══════════════════════════════════════════════════════════
# 9. Memory (记忆)
# ═══════════════════════════════════════════════════════════
# [概念] 短期记忆 = thread 内的 messages 历史(checkpointer 承载);
#        长期记忆 = Store 承载的跨 thread 知识。
#        常见模式: 滑动窗口截断 / 摘要压缩(summary node) / 实体记忆 / 语义检索召回。
#
# [生产] - 滑动窗口 + token 预算: 保留 system + 最近 N 轮
#        - 长会话: 超过阈值触发摘要压缩节点, 旧对话压缩成 summary 放回 state
#        - 长期: 对话中提取事实 → Store, 每轮检索 top-k 注入
#
# [项目现状] ws/baby_assistant.py: history 保留最近 MAX_HISTORY_MESSAGES 条 —— 滑动窗口;
#            graph.py: agent 节点 msgs = [system] + messages + [HumanMessage(query)]。
#            已具备短期记忆, 缺摘要压缩和长期记忆。
# [升级]     历史超 20 条触发 summarize 节点; 长期记忆用 Store(见第 3 节)。
# [话术] "我的短期记忆是滑动窗口, 我知道下一级优化是摘要压缩, 以及
#         用 Store 做跨会话长期记忆 —— 短期靠 checkpoint, 长期靠 store,
#         这句话是 LangGraph 记忆体系的口诀。"


# ═══════════════════════════════════════════════════════════
# 10. Subgraphs (子图)
# ═══════════════════════════════════════════════════════════
# [概念] 图可以嵌套: 一个 compiled graph 直接作为父图的节点。子图有自己的
#        state/节点/边/checkpointer。共享 state 时直接复用 schema; 不同 schema 时
#        用转换节点做字段映射。父图把控制权整体交给子图, 子图跑完返回。
#
# [生产] - 多 Agent 编排的标准载体: 每个 Agent = 一个子图(内含自己的 ReAct 循环),
#          Supervisor 父图负责路由 —— 团队可并行开发, 子图独立测试
#        - 复杂节点内部流程私有化: 数据查询子图(解析时间范围→多工具并行→合并)
#        - 子图独立配 checkpointer, 实现分级持久化
#
# [项目现状] graph.py: 单图承载全部逻辑(entry/agent/tools/rag/chitchat)。
#            意图路由到不同节点 = "逻辑上的分工", 但都在一张图里。
# [升级]     拆: data_agent 子图(ReAct 循环整体) / rag_agent 子图 / chat 子图,
#            父图只做 intent → route。单图→子图拆分是 Agent 系统从 MVP 到
#            团队协作的标志性演进。
# [话术] "我项目是单图 MVP, 我清楚演进路径: 把 ReAct 循环抽成 data_agent
#         子图, 父图只做意图路由 —— 子图独立开发/测试/部署, 这也是
#         supervisor 多 agent 模式的工程载体。"


# ═══════════════════════════════════════════════════════════
# 可运行示例: checkpointer + interrupt + time travel + store + subgraph 一图打尽
# 运行: cd kdx-ws-be && uv run python -m app.example.langgraph_capabilities
# ═══════════════════════════════════════════════════════════

def demo():
    from typing import TypedDict, Literal, Annotated
    import operator
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore
    from langgraph.types import interrupt, Command

    # ── 1. State ────────────────────────────────
    class State(TypedDict):
        query: str
        amount: float               # 待确认的写操作金额
        decision: str               # HITL 决策
        trace: Annotated[list, operator.add]   # subgraph 结果合并用

    # ── 2. 子图: 独立的数据处理单元 (Capabilities #10) ──
    def build_child_graph():
        def work(state: State):
            return {"trace": [f"child processed: {state['query']}"]}

        g = StateGraph(State)
        g.add_node("work", work)
        g.add_edge(START, "work")
        g.add_edge("work", END)
        return g.compile()

    child = build_child_graph()

    # ── 3. 父图节点 ──────────────────────────────
    def entry(state: State):
        # Store: 跨会话记忆写入 (Capabilities #3/#9)
        store.put(("profile", "u3"), "pref", {"like": "简短回答"})
        return {"trace": ["entry"]}

    def confirm(state: State):
        # interrupt: 图在此暂停, state 已被 checkpointer 持久化 (Capabilities #7)
        decision = interrupt({
            "type": "hitl_confirm",
            "tool": "add_feed_milk",
            "args": {"amount": state["amount"]},
        })
        return {"decision": str(decision), "trace": [f"confirmed={decision}"]}

    def finish(state: State):
        return {"trace": [f"finish, decision={state['decision']}"]}

    g = StateGraph(State)
    g.add_node("entry", entry)
    g.add_node("child", child)          # 子图直接作为节点
    g.add_node("confirm", confirm)
    g.add_node("finish", finish)
    g.add_edge(START, "entry")
    g.add_edge("entry", "child")
    g.add_edge("child", "confirm")

    def route(state: State) -> Literal["finish", "__end__"]:
        return "finish" if "approve" in state["decision"] else END

    g.add_conditional_edges("confirm", route)
    g.add_edge("finish", END)

    # ── 4. 编译: checkpointer(Persistence #1/#2) + store ──
    checkpointer = InMemorySaver()      # 生产换 PostgresSaver
    store = InMemoryStore()             # 生产换 PostgresStore
    app = g.compile(checkpointer=checkpointer, store=store)

    cfg = {"configurable": {"thread_id": "user-3-thread-1"}}

    # ── 5. Event streaming (Capabilities #5/#6): stream_mode="updates" ──
    print("── 第一次 invoke: 会在 confirm 节点 interrupt ──")
    for ev in app.stream(
            {"query": "记录喂奶", "amount": 90.0, "trace": []},
            cfg, stream_mode="updates"):
        print("  update:", ev)

    snap = app.get_state(cfg)
    print("  interrupted at:", snap.next, "| pending task:", snap.tasks[0].interrupts[0].value)

    # ── 6. Store 读取: 跨 thread 记忆 (Capabilities #3) ──
    print("  store recall:", store.get(("profile", "u3"), "pref").value)

    # ── 7. Time travel (Capabilities #8): 回看 state 历史 ──
    print("── state history ──")
    for h in app.get_state_history(cfg):
        print("  checkpoint:", h.config["configurable"]["checkpoint_id"][:8],
              "| next:", h.next, "| trace:", h.values.get("trace"))

    # ── 8. resume: 从 interrupt 同一行代码恢复 (Capabilities #7) ──
    print("── resume with approve ──")
    for ev in app.stream(Command(resume="approve"), cfg, stream_mode="updates"):
        print("  update:", ev)

    # ── 9. Fault tolerance (Capabilities #4): 从最后 checkpoint 重放 ──
    last = app.get_state(cfg)
    print("── replay from last checkpoint ──")
    print("  state:", last.values["trace"])
    print("\nALL_CAPABILITIES_DEMO_OK")


if __name__ == "__main__":
    demo()
