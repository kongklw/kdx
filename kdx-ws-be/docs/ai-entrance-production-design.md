# AI 总入口生产级设计（语音 + 文字 → 全页面功能接管）

> 定位：**严格按 2026 生产标准设计的"理想态"方案**。核心目标是"一个统一入口（语音 + 文字）能自动完成应用所有页面的功能交互"。
> 
> 关键前提：**项目已有一套生产级 LangGraph Agent 实现**（[assistant/graph.py](../app/assistant/graph.py)）——两级意图识别 → ReAct 循环 → HITL interrupt → 幂等 → 熔断 → 全局编译图。但它没被语音管线复用、目录挤在一起、缺失 4 个业务域工具。本方案**不重写逻辑，只按生产标准重排目录、补齐能力、统一入口**。

---

## 0. 一句话决策（TL;DR）

- **编排范式**：**FSM/State Graph（LangGraph StateGraph 实现）**——这是 2026 生产级 Agent 的主流工程形态，不是"裸 ReAct"。`agent_node` 内部跑 **ReAct 工具调用循环**（90% 简单 CRUD 一步到位），复杂多域任务（如"生成本月健康报告"）在 `complexity_node` 后加一个可选的 **Planner → 逐步 ReAct 执行 → Aggregator** 分支（Plan-and-Execute 嵌套在同一张状态图内，而非独立架构）。**不搞多 Agent/Supervisor**——25 个数据工具的宝宝管理 App 不需要多 Agent（见 2.1 节和第 7 节完整对比）。
- **传输层**：**WebSocket**（唯一可行选择）。语音需要双向流式传输（客户端发 PCM 帧、服务端回 TTS 音频），SSE 是单向 server→client 必须另开 HTTP 端点处理音频上传和 HITL 确认，协议复杂度翻倍。现有项目已用 WebSocket 跑通鉴权/限流/HITL/会话管理，复用成本最低（见新增 1.4 节传输层决策）。
- **统一入口**：一个 WebSocket 端点 `/ws/ai-entrance`，同时接受文字消息（`query` 类型）和语音音频帧（`audio` 类型）；语音走 DashScope 流式 ASR → 复用同一张 Agent 图 → DashScope TTS 流式输出。
- **现有好资产全复用**：`assistant/graph.py`（图逻辑）、`assistant/runtime.py`（contextvar 注入）、`assistant/llm_gateway.py`（多模型路由）、`assistant/resilience.py`（熔断/幂等/限流）、`assistant/tool_registry.py`（注册中心）、`assistant/repository.py`（数据访问）。
- **补齐 4 个缺失工具域**：待办、相册、经期、健康分析。

---

## 1. 现有系统盘点（看清我们站在哪）

### 1.1 前端页面 → 工具需求映射（必须全覆盖）

| 前端路由 | 页面名 | 对应工具域 | 现有工具覆盖 | 需新增工具 |
|---|---|---|---|---|
| `/mobile/home` + 顶部卡片 | 首页（宝宝档案） | 宝宝信息 | ✅ `get_baby_info` | — |
| `/mobile/functions/breastfeed` | 喂奶 | 喂奶 CRUD | ✅ `query/add_feed_milk` | — |
| `/mobile/functions/temperature` | 体温 | 体温 CRUD | ✅ `query/add_temperature` | — |
| `/mobile/functions/sleep` | 睡眠 | 睡眠 CRUD | ✅ `query/add_sleep` | — |
| `/mobile/functions/babypants` | 尿不湿 | 尿不湿 CRUD | ✅ `query/add_diaper` | — |
| `/mobile/functions/expense` | 花费 | 花费 CRUD | ✅ `query/add_expense` | — |
| `/mobile/functions/bodymetrics` | 身高体重/头围 | 成长 CRUD | ✅ `query/add_growth` | — |
| `/mobile/functions/vaccine` | 疫苗时间表 | 疫苗查询/标记 | ✅ `query_vaccines` `mark_vaccine_done` | — |
| `/mobile/functions/birthday` | 生日提醒 | 生日提醒查询 | ✅ `query_birthdays` | — |
| `/mobile/functions/todo` | **待办** | 待办 CRUD | ❌ **缺失** | 🔴 `list/create/update/toggle/delete_todo` |
| `/mobile/functions/album` | **宝宝相册** | 相册查询/上传/删除 | ❌ **缺失** | 🔴 `query_albums` `add_album_photo` `delete_album_photo` |
| `/mobile/functions/period` | **经期记录** | 经期查询/记录 | ❌ **缺失** | 🔴 `query_period` `add_period_log` |
| `/mobile/functions/analysis` | **健康分析** | 多域数据聚合 + 智能解读 | ❌ **缺失** | 🔴 `query_health_summary` `query_growth_curve` |
| `/mobile/functions/ragchat` | 育儿知识库 | RAG 问答 | ✅ `rag_node`（图内分支） | — |
| `/mobile/functions/langchain` / `/mobile/ai` | AI Park | Agent 对话 | ✅ 统一入口覆盖 | — |
| 底部 Tab：消息/商城 | 外部域 | 暂不 AI 接管（或加只读查询） | — | 可选：`query_messages` |

### 1.2 后端 WebSocket 端点现状

| 端点 | 现状 | 可复用 |
|---|---|---|
| `/ws/baby_assistant` | ✅ **生产级**：鉴权/限流/输入限长/HITL 挂起/幂等/processing 互斥/全局编译图 | ✅ 直接复用图逻辑 |
| `/ws/rag_query` | 独立 RAG 入口 | ✅ 合并到统一入口的 rag 分支 |
| `/ws/voice-agent` | ❌ **空壳**：只做音频字节回显+计数，无 Agent 逻辑 | ❌ 废弃 |
| `/ws/voice_agent_langchain` | ⚠️ **半成品**：DashScope 流式 ASR/TTS 管线完整，但 Agent 是**三明治店 demo**（`_build_tools()` 只返回 `add_to_order` / `confirm_order`），没接宝宝数据工具 | ⚠️ 复用 ASR/TTS 类，**替换 Agent 为 baby_assistant 那张三明治换宝宝助手** |

### 1.3 assistant/ 目录现状（挤在一起的好资产）

```
app/assistant/
├── graph.py          # ✅ 完整生产级 LangGraph 图（两级意图→ReAct→HITL→熔断）
├── runtime.py        # ✅ contextvar 注入运行时上下文（emit/身份/thread_id）
├── llm_gateway.py    # ✅ 多模型路由 + 熔断分桶 + 成本统计 + 降级
├── resilience.py     # ✅ CircuitOpenError / IdempotencyManager / RateLimiter
├── tool_registry.py  # ✅ ToolMeta + ToolRegistry（注册/权限/超时元数据）
├── tools.py          # ✅ 15 个宝宝数据工具（喂奶/体温/睡眠/尿不湿/花费/身高体重/疫苗/生日/宝宝信息）
├── repository.py     # ✅ BabyDataRepository（数据访问）
├── db_models.py      # ✅ SQLAlchemy ORM 模型
└── prompts.py        # 提示词（可能在 graph.py 里内联了）
```

**问题**：编排层（graph）和能力层（tools + repository）没有严格分离，目录扁平，缺失 4 个业务域工具，没有语音管线适配层。

### 1.4 传输层决策：WebSocket vs SSE

> **结论**：**WebSocket 是唯一可行选择**，不存在"SSE 更简单"这种说法——因为语音需求从根上排除了 SSE。

#### 什么场景用 SSE？

SSE（Server-Sent Events）是 HTTP 协议上的单向流式推送，适合：

- 纯文字 Agent 对话（文字进 HTTP POST、文字出 SSE 流）
- 服务器主动推送的通知（新消息到达、长任务进度）
- 前端不支持 WebSocket 的极老环境

本项目**只有 SSE 的优势完全不适用**：没有语音、不需要双向 HITL 确认、不需要持久会话——这些都不是我们的情况。

#### 本项目必须双向的三个硬需求

| 需求 | 方向 | SSE 能否满足 | 为什么 |
|---|---|---|---|
| **语音双向流** | 客户端 → 服务端（PCM 音频帧）+ 服务端 → 客户端（TTS 音频帧） | ❌ 完全不行 | SSE 是 server→client 单向流式。客户端发音频帧只能走 HTTP POST（每帧一次请求）或独立 WebSocket——**等于同时维护两套传输层** |
| **HITL 确认** | 服务端下发 `confirmation_request` → 客户端用户 approve/reject → 客户端回传 | ❌ 不优雅 | SSE 推了确认请求后，客户端的 approve/reject 只能走另一条 HTTP 回调端点（`POST /hitl/confirm`），要自己维护 request_id 关联、会话恢复 |
| **持久会话 + 状态同步** | 连接保持期间多次 query 共享同一 session | ❌ 需要大量手工 | SSE 每次 HTTP 请求独立，session 状态要靠 URL query 或 cookie 里的 session_id 手工传递，断线重连时客户端重新拉 SSE 连接但服务端不知道恢复到哪一步 |

#### 详细对比表

| 维度 | WebSocket | SSE + HTTP（混合） | 本项目胜负 |
|---|---|---|---|
| **双向流式** | ✅ 原生 | ❌ 必须 SSE(server→client) + HTTP(client→server) 双端点 | **WebSocket**：语音音频双向流是刚需 |
| **协议开销** | 一次握手，后续帧低开销 | 每次 HTTP POST 都带完整 headers/cookies | **WebSocket**：高频音频帧场景性能翻倍 |
| **HITL 实现** | 图 interrupt → WS 推 confirm_request → 等 WS 回 confirm → Command(resume) 恢复 | SSE 推 confirm → 另开 HTTP POST /hitl/confirm → 后端匹配 request_id → 恢复 | **WebSocket**：SSE 方案要维护额外回调端点 + request_id 关联 |
| **断线重连** | WS 重连 → 用同一个 thread_id 的 checkpointer 恢复图状态 | SSE 重连 → session 状态要手工从 cookie/query 传回来 + 重新初始化图 | **WebSocket**：LangGraph checkpointer 原生配合 |
| **CDN / 反向代理** | 少数企业代理需要 Upgrade 配置 | ✅ 所有 CDN/代理天然支持 | **平**：内部服务无此问题 |
| **调试** | WS Inspector / Chrome DevTools 看帧 | ✅ curl 一条命令搞定 | **平**：开发期方便，生产都是结构化事件日志 |
| **现有代码复用** | ✅ `baby_assistant.py` 鉴权/限流/HITL挂起/processing 互斥/全局编译图已实现 | ❌ 全部重写一遍 HTTP 回调端点 | **WebSocket**：省 500+ 行网关代码 |
| **多协议维护成本** | 一个 WS 端点搞定 | SSE 端点 + HTTP query 端点 + HTTP confirm 端点 + 可能的 HTTP audio 上传端点 | **WebSocket**：单一传输层，单一鉴权/限流逻辑 |

#### 如果强行用 SSE 会怎么样？

为了绕过 SSE 单向限制，你最终会写出这样一套东西：

```
客户端
  │
  ├── HTTP POST /ai/query           ← 文字查询
  ├── HTTP POST /ai/audio_chunk     ← 语音音频帧（每帧一次请求！TLS 握手开销巨大）
  ├── HTTP POST /ai/hitl_confirm    ← HITL 确认
  │
  └── SSE GET /ai/stream?session_id ← 流式文本 + 工具调用 + AI Card + 确认请求 + ...
```

问题：

1. **语音每帧一次 HTTP POST 不现实**：16kHz PCM 每秒 16000 个采样点，通常打包成 40-200ms 一个帧（每秒 5-25 帧）。每帧走一次 HTTP POST（TLS 握手 + headers 解析 + 路由匹配），延迟和 CPU 开销爆炸，ASR 流式实时性彻底丢失
2. **四个端点的鉴权/限流/会话绑定逻辑要写四遍**
3. **所有端点都要维护同一个 session_id → checkpointer 绑定**，SSE 断开重连后还要在 `Last-Event-ID` 里恢复到上次哪条消息

这一套不是"SSE 更简单"，是**SSE 在非双向场景下才更简单，在需要双向流的场景下比 WebSocket 更复杂**。

#### 本项目的决策

沿用现有 WebSocket 网关的设计模式，统一到一个端点 `/ws/ai-entrance`，扩展事件类型支持音频帧和 TTS 输出即可。已验证的基础设施（鉴权/限流/HITL挂起/processing 互斥/全局编译图）100% 复用。

---

## 2. 目标架构

### 2.1 编排范式决策：FSM/State Graph（LangGraph 实现）+ ReAct/Plan-Execute 可选嵌套

> **关键澄清**：当前 2026 主流的"状态机型 Agent"**不是与 ReAct 互斥的替代品**，而是**承载 ReAct/Plan-Execute 等执行范式的工程容器**。这是本方案最容易被误解的点，必须说清楚。

#### 三层结构，各司其职

```
┌─────────────────────────────────────────────────────┐
│  Layer 1: FSM/State Graph（状态图/有限状态机）        │  ← LangGraph StateGraph 实现
│  职责：控制流 + 状态持久化 + 路由决策 + HITL 挂起      │     本方案选的就是这一层
│  形态：entry → conditional_route → agent/rag/... → END
│  State schema：强类型 TypedDict + reducer            │
│  Checkpointer：PostgreSQL（AsyncPostgresSaver）      │
└─────────────────────────────────────────────────────┘
          │ agent_node 内部是什么？
          ▼
┌─────────────────────────────────────────────────────┐
│  Layer 2: ReAct 工具调用循环（90% 场景默认）          │  ← agent_node 内执行循环
│  职责：LLM 思考 → 决定调哪个工具 → 拿到结果 → 总结     │     1 次 LLM call + N 次工具
│  适用：1-3 步就能完成的简单 CRUD 查询/记录              │     (3-5 tools max)
│  例子："今天喝了多少奶？" → query_feed_milk → 回答     │
│        "帮我记 120ml 喂奶" → add_feed_milk → 确认     │
└─────────────────────────────────────────────────────┘
          │ 那 Plan-and-Execute 在哪？
          ▼
┌─────────────────────────────────────────────────────┐
│  Layer 2b: Plan-and-Execute（复杂任务可选）           │  ← 不是独立架构，是 FSM 的一个分支
│  职责：先出完整执行计划 → 逐步执行 → 综合           │     复杂度路由决定是否启用
│  适用：多域/跨工具/8+ 步的开放式任务                    │
│  例子："生成本月健康报告" → 同时查奶量/睡眠/体温/      │
│        疫苗/花费 + 调 RAG 育儿知识库 + 生成 Markdown  │
└─────────────────────────────────────────────────────┘
```

#### 为什么不选"裸 ReAct"或"裸 Plan-Execute"

| 范式 | 优点 | 问题 |
|---|---|---|
| **裸 ReAct**（只有工具调用循环，没有图） | 简单直接，一步到位 | **没有状态持久化**：崩溃后从头来；**没有 HITL**：写操作拦不住；**没有显式路由**：所有任务都丢给同一个 ReAct 循环，LLM 自由选工具但选不对就无限试；**没有预算控制**：token 跑飞了才发现 |
| **裸 Plan-Execute**（先规划后执行，没有图） | 全局最优、少 token 重复推理 | **90% 场景浪费**：用户问"今天奶量"也要先规划"第一步查奶量第二步总结"再执行，多一次 LLM call；**规划成本高**：规划错了全部重排；**灵活性差**：中间观察到意外结果想调整计划要重新跑 Planner |
| **FSM/State Graph + ReAct/Plan-Execute 嵌套**（本方案） | 两种模式的优点都拿到，缺点都屏蔽 | **复杂度**：要理解 StateGraph + conditional_edges + state schema，但这是一次性学习成本，后续加节点/加路由都是图上改几行 |

#### 复杂度路由：在同一张图里同时支持简单和复杂任务

关键洞察是：**Plan-and-Execute 不是与 FSM 并列的架构，而是 FSM 图里的一个可选分支**。在 `entry_node` 之后加一个复杂度判定节点：

```
START
  │
  ▼
entry_node（三级意图识别 + 宝宝上下文）
  │
  ▼
complexity_node（判定：一句话能说完？跨 3 个以上工具域？含"分析/报告/对比"关键词？）
  │
  ├── 简单任务（CRUD 查询/记录，<3 工具域）
  │     │
  │     ▼
  │   agent_node（直接 ReAct 循环，3-5 步搞定）
  │     │
  │     ▼
  │   总结回答 → END
  │
  └── 复杂任务（多域聚合 / 开放式分析 / 深度查询）
        │
        ▼
      planner_node（LLM 出结构化 step list + 预算）
        │
        ▼
      planner_review_node（可选：规则校验预算/步数/每步工具合理性）
        │
        ▼
      execute_loop_node（循环执行每个 step，每个 step 内部跑 ReAct + tool_exec）
        │  循环直到所有 step 完成 / 预算耗尽 / 达到最大 step 数
        ▼
      aggregator_node（综合所有 step 结果 + RAG 知识 → 最终回答）
        │
        ▼
      END
```

**为什么这样设计**：

1. **90% 简单任务零额外开销**：直接走 ReAct，不经过 planner，和现状一模一样
2. **复杂任务自动升级**："生成本月健康报告" 自动触发 Plan-and-Execute，因为它需要同时查奶量/睡眠/体温/疫苗/花费 + 调 RAG，3+ 工具域
3. **Plan-and-Execute 里每一步的执行还是 ReAct**：planner 输出 step list，每个 step 由一个轻量 ReAct 循环执行（比如第 1 步"查本月奶量" → ReAct 一次 → 工具调用 → 结果），不需要额外架构
4. **所有节点共享同一份 FSM 的状态和 checkpointer**：planner 出的计划、每个 step 的执行结果、最终总结都写进同一张图的 state，断线重连/HITL 暂停/熔断恢复全链路一致

#### 为什么不搞多 Agent/Supervisor？

> 2026 年最容易踩的 Agent 坑就是"为了看起来高级而上多 Agent"。一个宝宝管理 App，工具总数 ~25 个、单次任务深度 3-5 步、任务间几乎没有真正需要"并行协作 + 独立上下文隔离"的场景——用 Supervisor 星型拓扑只会增加 token 成本、延迟和不可观测性。
> 
> **25 个工具、3-5 步任务、单用户单上下文**，用 FSM + ReAct/Plan-Execute 已经覆盖：
> 
> - **ReAct（默认）** 处理 90% 的 CRUD 查询/记录
> - **Plan-and-Execute（复杂度路由）** 处理剩余 10% 的多域聚合任务
> - **多 Agent** 在这个场景下没有真正的技术优势，只有工程复杂度

这正是现有 `assistant/graph.py` 已经写对的架构。本方案只重排目录、补齐工具、统一入口。

### 2.2 总架构图

```
              ┌──────────────────────────────────────────────────────────────┐
              │              统一 AI 入口 WebSocket 网关                       │
              │              /ws/ai-entrance                                  │
              │                                                               │
              │  Client → Server:                                             │
              │   {"type": "query", "query": "今天奶量", "request_id": ".."}   │
              │   {"type": "audio", "audio": "<pcm bytes>"}   (语音帧)          │
              │   {"type": "confirm", "confirm_id": "CFM-..", "action": "..."} │
              │                                                               │
              │  Server → Client:                                             │
              │   {"type": "tool_call", ...}                                  │
              │   {"type": "tool_result", ...}                                │
              │   {"type": "confirmation_request", ...}                       │
              │   {"type": "generate_chunk", ...}     ← 流式文本                 │
              │   {"type": "tts_chunk", "audio": "<base64 pcm>"} ← 语音回复       │
              │   {"type": "card", "card": {...}}      ← AI Card（结构化展示）    │
              │                                                               │
              └──────┬──────────────────────┬─────────────────────────────────┘
                     │ text?                │ audio?
                     ▼                      ▼
              ┌───────────┐          ┌──────────────────────────────────┐
              │  直接进图    │          │  DashScope 流式 ASR               │
              │  (contextvar│          │  paraformer-realtime-v2          │
              │  注入身份)   │          │  → 流式 STTChunk/STTOutput 事件   │
              └─────┬─────┘          └────────────┬─────────────────────┘
                    │                             │ final transcript
                    │                             ▼
                    └──────────────┬──────────────┘
                                   ▼
              ┌───────────────────────────────────────────────────────────────┐
              │           LangGraph 状态图（进程级全局编译一次）                 │
              │                                                               │
              │  START ──▶ entry_node (三级意图识别 + 宝宝上下文加载)               │
              │              │                                                │
              │              ▼                                                │
              │         complexity_node（判定：一句话能说完？跨3+工具域？        │
              │              │              含"分析/报告/对比"关键词？）          │
              │              │                                                │
              │     ┌────────┼──────────────────────────────────┐            │
              │     │        │                                  │            │
              │     ▼        ▼                                  ▼            │
              │  简单任务    rag_node                         复杂多域任务      │
              │  (CRUD查询/   (RAG 育儿知识库)                   │            │
              │   记录)                                             │            │
              │     │        │                                  │            │
              │     ▼        │                                  ▼            │
              │  agent_node  │                           planner_node          │
              │  (直接ReAct,  │                           (LLM出结构化steplist)  │
              │   3-5步搞定)  │                                  │            │
              │     │        │                                  ▼            │
              │     ▼        │                         planner_review_node     │
              │  tool_exec   │                         (规则校验预算/步数)       │
              │  (幂等+熔断+  │                                  │            │
              │   HITL)       │                                  ▼            │
              │     │        │                        execute_loop_node       │
              │     │        │                        (循环执行每个step,        │
              │     │        │                         每步内部跑ReAct+tool)    │
              │     │        │                                  │            │
              │     │        │                                  ▼            │
              │     └── agent ◀─┘                         aggregator_node      │
              │           (ReAct回流:工具结果再推理)         (综合所有step+RAG)  │
              │                    │                                  │      │
              │                    ▼                                  └───┐  │
              │              chitchat_node                              END │
              │              (闲聊/兜底/导航建议)                              │
              │                                                                   │
              │  ────────────────────────────────────────────────────────          │
              │  State schema: AssistantState（强类型 TypedDict + reducer）          │
              │  Checkpointer: PostgreSQL（AsyncPostgresSaver，跨实例持久化）         │
              └──────────────────┬──────────────────────────────────────────────┘
                                 │
                        answer + tool_trace
                                 │
                    ┌────────────┴──────────────┐
                    │                           │
                    ▼                           ▼
            ┌─────────────┐             ┌─────────────────────┐
            │ 流式文本输出   │             │ DashScope TTS (可选)   │
            │ generate_chunk│             │ qwen3-tts-vd           │
            │ + AI Card     │             │ 流式 tts_chunk 音频帧  │
            └─────────────┘             └─────────────────────┘
```

### 2.3 语音→Agent→TTS 管线（复用 voice_agent_langchain.py 的 ASR/TTS 类）

```
音频帧 (16kHz PCM)
    │
    ▼
DashscopeRealtimeASR (paraformer-realtime-v2)
    │  ├─ STTChunkEvent   ← 流式部分识别（前端做打字指示器/状态反馈）
    │  └─ STTOutputEvent  ← 最终识别文本（sentence_end=true）
    │
    ▼
Agent 图入口 (entry_node → route_after_intent → agent_node/rag_node/...)
    │  emit("tool_call") / emit("tool_result") / emit("generate_chunk")
    │
    ▼
AI Agent 最终完整回答文本
    │
    ▼
DashscopeQwenTtsRealtime (qwen3-tts-vd)
    │  TTSChunkEvent → base64 PCM 音频帧
    │
    ▼
客户端播放 + 打字指示器 + AI Card 展示
```

**设计要点**：
- **ASR/TTS 类直接复用** `voice_agent_langchain.py` 里的 `DashscopeRealtimeASR` 和 `DashscopeQwenTtsRealtime`（已成熟，带 fallback 模型）
- **Agent 替换为 baby_assistant 图**：删掉三明治 demo 的 `_build_tools()` 和 `_build_agent()`，改用 `get_compiled_graph()`（进程级共享编译图）
- **事件流合并**：Agent 图通过 contextvar 注入 emit 回调，与 ASR/TTS 的事件队列通过 `merge_async_iters` 合并，统一推送到客户端
- **语音/文字同一图实例**：两者唯一区别是入口（文字直接进图、语音先过 ASR），后续图执行完全相同——意味着用户可以语音问、文字追问、断线重连、HITL 确认，全链路一致

---

## 3. 工具清单（25 个，全覆盖）

### 3.1 现有 15 个（直接保留，无需改动）

| Tool | 域 | 读/写 |
|---|---|---|
| get_baby_info | 宝宝档案 | 读 |
| query_feed_milk / add_feed_milk | 喂奶 | 读/写 ✓ |
| query_temperature / add_temperature | 体温 | 读/写 ✓ |
| query_sleep / add_sleep | 睡眠 | 读/写 ✓ |
| query_diapers / add_diaper | 尿不湿 | 读/写 ✓ |
| query_expense / add_expense | 花费 | 读/写 ✓ |
| query_growth / add_growth | 身高体重/头围 | 读/写 ✓ |
| query_vaccines / mark_vaccine_done | 疫苗 | 读/写 ✓ |
| query_birthdays | 生日提醒 | 读 |

### 3.2 新增 10 个（4 个业务域）

#### 待办域（复用 `/todo` HTTP router 的 TodoService）

| Tool | 描述 | 参数 | 读/写 |
|---|---|---|---|
| list_todos | 查询待办事项列表 | `status: pending\|done\|all, include_daily: bool` | 读 |
| create_todo | 创建新待办 | `content: str, remind_at: datetime, is_daily: bool, tag: str` | 写 ✓ |
| update_todo | 更新待办（内容/时间/标签） | `todo_id: str, content: str, remind_at: datetime` | 写 ✓ |
| toggle_todo | 切换待办完成状态 | `todo_id: str` | 写 ✓ |
| delete_todo | 删除待办 | `todo_id: str` | 写 ✓ |

#### 相册域（复用 Django BabyAlbum / AlbumPhoto 模型 + MinIO 文件存储）

| Tool | 描述 | 参数 | 读/写 |
|---|---|---|---|
| query_albums | 查询相册列表及封面 | `limit: int` | 读 |
| add_album_photo | 新增相册照片（需要先由前端完成文件上传，tool 接收已上传 file_key） | `album_id: int, file_key: str, caption: str, shot_date: date` | 写 ✓ |
| delete_album_photo | 删除相册照片 | `photo_id: int` | 写 ✓ |

#### 经期域（复用 Django MenstrualSetting / MenstrualLog 模型）

| Tool | 描述 | 参数 | 读/写 |
|---|---|---|---|
| query_period | 查询经期记录（最近 N 条 + 周期预测） | `days: int` | 读 |
| add_period_log | 记录经期日志 | `log_date: date, flow_level: light\|normal\|heavy, symptom: str, note: str` | 写 ✓ |

#### 健康分析域（聚合多域数据，新增 AnalysisService）

| Tool | 描述 | 参数 | 读/写 |
|---|---|---|---|
| query_health_summary | 聚合多域数据生成健康总览 | `range_days: int` | 读 |
| query_growth_curve | 查询身高体重历史曲线 + 百分位对比 | `metric: height_cm\|weight_kg\|head_circumference_cm, limit: int` | 读 |

### 3.3 新写操作 HITL 标记

所有新增写操作（待办 create/update/toggle/delete、相册 add/delete、经期 add_period_log）在注册到 ToolRegistry 时**必须**设 `is_write=True`——这会触发 `agent_node` 里的 HITL interrupt 暂停流程：

```
用户: "帮我删掉所有过期的待办"
Agent: 选择了 delete_todo(6条)
  → agent_node 检测到 is_write=True
  → interrupt({confirm_id, tools, "即将删除6条待办"})
  → WS 下发 confirmation_request
  → 用户 approve/reject
  → Command(resume=...) 恢复执行
```

---

## 4. 严格生产级目录结构

### 4.1 目标目录（与现有 asset 的迁移映射）

```
kdx-ws-be/app/
├── main.py                          # 应用入口：加载配置 → 启动钩子 → 注册 router
│                                    #  （保持不变，新增 include ai_entrance_router）
│
├── core/                            # 横切基础设施（保持不变）
│   ├── config.py                    # pydantic-settings
│   ├── database.py                  # SQLAlchemy SessionLocal + AsyncPostgres checkpointer
│   ├── security.py                  # JWT 验签 / token 提取
│   ├── logging.py                   # loguru 配置
│   ├── metrics.py                   # Prometheus 指标
│   └── observability.py             # 【新增】OpenTelemetry + Langfuse 集成入口
│
├── api/                             # HTTP 路由层（保持不变）
│   ├── health.py
│   ├── metrics.py
│   ├── todo.py                      # ✅ 保持独立（FastAPI 原生 HTTP）
│   ├── face.py
│   ├── access_stats.py
│   └── deps.py
│
├── ws/                              # WebSocket 网关层（统一收口到 ai_entrance）
│   ├── ai_entrance.py               # 【新增/替代】统一文字+语音入口
│   │                                #   · 从 voice_agent_langchain.py 搬 ASR/TTS 类
│   │                                #   · 复用 baby_assistant.py 的鉴权/限流/HITL挂起/事件协议
│   │                                #   · 替换 agent 为 agents/graph.get_compiled_graph()
│   ├── baby_assistant.py            # 【废弃】功能合并到 ai_entrance
│   ├── voice_agent.py               # 【废弃】空壳
│   ├── voice_agent_langchain.py     # 【废弃】功能合并到 ai_entrance
│   └── rag_query.py                 # 【可选废弃】rag 合并到统一入口的 intent 分支
│
├── agents/                          # ★ 编排层（纯决策与流程，不放业务细节）
│   │                                #   ← 从 assistant/ 重排而来
│   │
│   ├── state.py                     # 【迁移自 assistant/graph.py 里的 AssistantState】
│   │                                #   · 强类型 TypedDict + reducer（并发更新规则）
│   │                                #   · 所有 graph 节点通过 state 传递数据，不闭包捕获外部
│   │
│   ├── graph.py                     # 【迁移自 assistant/graph.py 的构图逻辑】
│   │                                #   · build_agent_graph(checkpointer) → 编译 StateGraph
│   │                                #   · get_compiled_graph() → 进程级单例
│   │                                #   · 保持全局编译一次、checkpointer 持久化
│   │
│   ├── nodes/                       # 【从 assistant/graph.py 拆出节点函数到包结构】
│   │   ├── __init__.py
│   │   ├── entry.py                 # entry_node: 三级意图识别 + 宝宝上下文加载
│   │   ├── agent.py                 # agent_node: LLM 决策（工具绑定 + HITL interrupt）
│   │   ├── rag.py                   # rag_node: 统一检索服务
│   │   ├── chitchat.py              # chitchat_node
│   │   ├── navigate.py              # 【新增】navigate_node: 页面导航建议（"打开体温页"）
│   │   ├── fallback.py              # fallback_node: 低置信度引导
│   │   ├── give_up.py               # give_up_node: ReAct 超限兜底
│   │   └── tools.py                 # tool_exec_node: 工具执行 + 幂等 + 熔断
│   │
│   ├── edges.py                     # 【从 assistant/graph.py 拆出条件路由判定】
│   │   ├── route_after_intent()     #   intent → agent/rag/chitchat/navigate/fallback
│   │   └── route_after_agent()      #   tool_calls → tools / give_up / end
│   │
│   ├── intents.py                   # 【从 assistant/graph.py 拆出意图识别逻辑】
│   │   ├── rule_intent()            #   规则优先（零延迟零成本）
│   │   ├── llm_intent()             #   LLM few-shot 兜底（廉价小模型）
│   │   └── INTENT_PATTERNS          #   意图关键词表
│   │
│   ├── middleware/                  # 【新增】图级中间件（每次节点执行前后触发）
│   │   ├── budget.py                #   token/成本预算检查 + 超限终止
│   │   ├── guardrails.py            #   输入/输出护栏（注入检测 + 敏感词过滤）
│   │   └── trace.py                  #   OpenTelemetry span 注入
│   │
│   └── prompts/                     # 【拆出系统提示词到独立文件，版本化】
│       ├── agent.py                 # agent_node 的 system prompt（工具调用规则）
│       ├── rag.py                   # rag_node 的 system prompt
│       ├── chitchat.py              # chitchat_node 的 system prompt
│       ├── navigate.py              # navigate_node 的 system prompt
│       └── intent_classifier.py     # llm_intent 的 few-shot prompt
│
├── tools/                           # ★ 能力层（Agent 与业务之间的唯一边界）
│   │                                #   ← 从 assistant/ 重排 + 新增
│   │
│   ├── registry.py                  # 【迁移自 assistant/tool_registry.py】
│   │                                #   ToolMeta + ToolRegistry：注册/权限/超时元数据
│   │                                #   register() / get_schemas_for_llm() / is_write_tool()
│   │
│   ├── baby/                        # 宝宝数据域（现有 15 个，保持不变）
│   │   ├── __init__.py              # register_baby_tools(registry)
│   │   ├── info.py                  # get_baby_info
│   │   ├── feed.py                  # query/add_feed_milk
│   │   ├── temperature.py            # query/add_temperature
│   │   ├── sleep.py                 # query/add_sleep
│   │   ├── diaper.py                # query/add_diaper
│   │   ├── expense.py               # query/add_expense
│   │   ├── growth.py                # query/add_growth
│   │   ├── vaccine.py               # query_vaccines / mark_vaccine_done
│   │   └── birthday.py              # query_birthdays
│   │
│   ├── todo/                        # 【新增】待办域
│   │   ├── __init__.py              # register_todo_tools(registry)
│   │   ├── list.py                  # list_todos
│   │   ├── crud.py                  # create / update / toggle / delete_todo
│   │   └── _service.py              # 内部：包装 services/todo_service.py（复用现有）
│   │
│   ├── album/                       # 【新增】相册域
│   │   ├── __init__.py              # register_album_tools(registry)
│   │   ├── query.py                 # query_albums
│   │   ├── photo.py                 # add_album_photo / delete_album_photo
│   │   └── _service.py              # 内部：包装 Django BabyAlbum/AlbumPhoto + MinIO
│   │
│   ├── period/                      # 【新增】经期域
│   │   ├── __init__.py              # register_period_tools(registry)
│   │   ├── query.py                 # query_period
│   │   ├── log.py                   # add_period_log
│   │   └── _service.py              # 内部：包装 Django MenstrualLog
│   │
│   ├── analysis/                    # 【新增】健康分析域
│   │   ├── __init__.py              # register_analysis_tools(registry)
│   │   ├── summary.py               # query_health_summary（多域聚合）
│   │   ├── growth_curve.py          # query_growth_curve（历史趋势 + 百分位）
│   │   └── _service.py              # 内部：新增 AnalysisService（多域数据聚合）
│   │
│   ├── navigation.py                # 【新增】页面导航建议工具
│   │                                #   suggest_page(target): 建议用户去哪个页面查看
│   │                                #   （"建议打开首页查看宝宝档案" / "点击待办查看待处理事项"）
│   │                                #   返回结构化 page_key + 建议文案，前端可渲染跳转按钮
│   │
│   ├── schemas.py                   # 【新增】所有工具入参/出参的 Pydantic 模型
│   │                                #   ToolCallArgs / ToolResult / HITLConfirmRequest
│   │
│   └── mcp/                         # 【预留】外部 MCP server 工具适配
│
├── services/                        # 业务领域服务（可被非 Agent 复用）
│   ├── todo_service.py              # ✅ 已有，被 tools/todo/_service.py 包装
│   ├── analysis_service.py          # 【新增】多域数据聚合
│   ├── baby_data_repository.py      # 【迁移自 assistant/repository.py，改名明确】
│   ├── period_repository.py         # 【新增】经期数据访问
│   ├── album_repository.py          # 【新增】相册 + MinIO 数据访问
│   └── memory.py                    # ✅ 已有
│
├── rag/                             # 统一检索服务（保持不变）
│   ├── service.py                   # RetrievalService（混合检索 + 精排）
│   ├── retriever.py
│   ├── embeddings.py
│   └── indexer/
│
├── assistant/                       # ★ 【保留但瘦身，只留运行时基础设施】
│                                    #   编排层和能力层已搬到 agents/ 和 tools/
│                                    #   这里只放运行时必需的底座
│   ├── runtime.py                   # ✅ 【保留】contextvar 注入 + emit（图执行必需）
│   ├── llm_gateway.py               # ✅ 【保留】多模型路由 + 熔断 + 成本（图执行必需）
│   ├── resilience.py                # ✅ 【保留】CircuitOpenError / IdempotencyManager / RateLimiter
│   └── __init__.py
│                                    # 【删除或迁移】
│                                    #   graph.py → agents/graph.py
│                                    #   nodes.py / state.py → agents/
│                                    #   tools.py → tools/baby/ + tools/todo/ + ...
│                                    #   tool_registry.py → tools/registry.py
│                                    #   repository.py → services/baby_data_repository.py
│                                    #   db_models.py → models/
│
├── models/                          # ORM 模型（保持不变，db_models.py 合并进来）
├── schemas/                         # API DTO（保持不变）
├── integrations/                    # 第三方客户端（保持不变：MinIO / Redis）
├── evals/                           # 【新增】离线评测
│   ├── datasets/
│   └── run_eval.py
└── utils/                           # 工具模块（保持不变，merge_things/event 等留此处）
```

### 4.2 关键迁移映射表

| 现有位置 | 新位置 | 操作 |
|---|---|---|
| `assistant/graph.py` 里的 `AssistantState` | `agents/state.py` | 拆出 |
| `assistant/graph.py` 里的 `build_assistant_graph` | `agents/graph.py` | 改名为 `build_agent_graph`，拆节点到 `agents/nodes/` |
| `assistant/graph.py` 里的意图识别逻辑 | `agents/intents.py` | 拆出 |
| `assistant/graph.py` 里的条件路由 | `agents/edges.py` | 拆出 |
| `assistant/tools.py`（15 个工具） | `tools/baby/` + `tools/todo/` + `tools/album/` + `tools/period/` + `tools/analysis/` | 按域拆分文件 |
| `assistant/tool_registry.py` | `tools/registry.py` | 改名明确 |
| `assistant/repository.py` | `services/baby_data_repository.py` | 改名 + 与 Django 数据模型对齐 |
| `assistant/db_models.py` | `models/` | 合并到统一 ORM 目录 |
| `assistant/runtime.py` | `assistant/runtime.py` | ✅ 保留（图执行必需） |
| `assistant/llm_gateway.py` | `assistant/llm_gateway.py` | ✅ 保留 |
| `assistant/resilience.py` | `assistant/resilience.py` | ✅ 保留 |
| `ws/baby_assistant.py` | `ws/ai_entrance.py` | ⚠️ 合并（复制鉴权/限流/HITL挂起逻辑，替换入口） |
| `ws/voice_agent_langchain.py` | `ws/ai_entrance.py` | ⚠️ 合并（搬 ASR/TTS 类，替换 Agent 为 baby_assistant 图） |
| `ws/voice_agent.py` | 删除 | ❌ 空壳，废弃 |
| `api/ai_entrance.py` | 被 `ws/ai_entrance.py` 替代 | ⚠️ HTTP 入口没必要，全部走 WS |

### 4.3 依赖方向（只允许向内依赖）

```
ws/ai_entrance (网关)
  │
  ├── agents/ (编排)
  │   ├── tools/registry.get_schemas_for_llm()
  │   └── assistant/runtime.set_runtime_context()
  │
  ├── voice/ (语音管线，从 voice_agent_langchain.py 搬来的 ASR/TTS 类)
  │   └── assistant/llm_gateway (TTS 模型可能复用)
  │
  ▼
agents/ (编排层) ──┬──→ tools/ (能力层) ──→ services/ (领域服务) ──→ models/ + integrations/
                   └──→ assistant/llm_gateway (LLM 调用)
                   └──→ rag/service (RAG 分支)
                   └──→ assistant/resilience (熔断/幂等)

任何层都可以横切使用: core/config.py, core/security.py, core/observability.py, utils/

❌ 禁止反例：
- node 里直接 requests.post 而不调 tool
- tool 里拼图路由 / 改 graph
- prompt 里硬编码业务 SQL / 业务字段
- agent 闭包捕获外部 WS 连接（必须通过 contextvar 拿 emit）
```

---

## 5. 统一入口协议设计

### 5.1 客户端 → 服务器

```jsonc
// 文字查询
{ "type": "query", "query": "今天喝了多少奶？", "request_id": "uuid-xxx" }

// 语音帧（16kHz PCM 16bit mono，base64 或原始二进制）
{ "type": "audio", "audio": "<base64>" }

// 语音会话控制（可选：start/end 用于 VAD 或 ASR session 控制）
{ "type": "audio_start" }
{ "type": "audio_end" }

// HITL 确认
{ "type": "confirm", "confirm_id": "CFM-xxx", "action": "approve" | "reject" }

// 健康检查
{ "type": "ping" }
```

### 5.2 服务器 → 客户端

```jsonc
// 连接成功
{ "type": "connected", "user_id": 123, "message": "ai entrance ready (protocol v3)" }

// 请求开始
{ "type": "query_start", "query": "...", "request_id": "..." }

// 意图识别结果
{ "type": "intent_detected", "intent": "data_query", "confidence": 0.92, "source": "rule" }

// 工具调用/结果（ReAct 循环过程）
{ "type": "tool_call", "id": "c0", "name": "query_feed_milk", "args": { "day": "today" } }
{ "type": "tool_result", "id": "c0", "name": "query_feed_milk", "ok": true,
  "result": "{\"count\":8,\"total_ml\":1280}" }

// 写操作 HITL 确认请求
{ "type": "confirmation_request",
  "confirm_id": "CFM-abc", "expires_in": 300,
  "tools": [{ "name": "add_feed_milk", "args": {"milk_volume": 120},
              "description": "记录一次喂奶 120ml" }],
  "message": "即将写入宝宝数据，请确认" }

// 流式文本输出（逐 token）
{ "type": "generate_chunk", "chunk": "宝宝今天一共喝了" }
{ "type": "generate_chunk", "chunk": "1280 毫升奶，分 8 次喂养。" }

// 语音输出（可选，Base64 PCM 24kHz mono 16bit）
{ "type": "tts_chunk", "audio": "<base64>" }

// ★ AI Card（结构化展示，用户要求的"时间/问题/工具/结果/tokens"）
{ "type": "card",
  "card": {
    "request_id": "uuid-xxx",
    "timestamp": "2026-09-14T15:30:00+08:00",
    "query": "今天喝了多少奶？",
    "intent": "data_query",
    "route": "agent",
    "tool_trace": [
      { "name": "query_feed_milk", "args": {"day": "today"},
        "ok": true, "result_summary": "8次/1280ml", "cached": false }
    ],
    "sources": [],           // RAG 时填
    "answer": "宝宝今天一共喝了1280毫升奶，分8次喂养。",
    "model": "qwen3.5-plus",
    "tokens": { "input": 1234, "output": 456, "total": 1690 },
    "latency_ms": 1823
  }
}

// 请求完成（无 interrupt 时）
{ "type": "query_done", "request_id": "uuid-xxx" }

// 错误
{ "type": "query_error", "error": "rate limit exceeded (30/min)" }
```

### 5.3 AI Card 前端渲染（用户明确要求）

前端收到 `card` 事件后，渲染一张卡片，包含：
- **头部**：时间戳 + 模型 + 耗时 + token 用量（右上角一排小徽章）
- **用户问题**：原始 query（左侧气泡）
- **Agent 回复**：answer 文本（右侧气泡 + Markdown 渲染）
- **工具调用链**：折叠列表，每步显示工具名 + 参数 + 结果摘要 + 成功/失败图标
- **来源引用**（RAG 时）：可点击跳转文档
- **反馈按钮**：👍👎 + 自由文本备注（收集 bad case 进评测集）

---

## 6. 迁移计划（分三阶段，每阶段可回滚）

### 阶段一：补齐工具 + 重排目录（不动语音管线）

1. 新增 `services/todo_service.py`（从 `api/todo.py` 提取）、`services/analysis_service.py`
2. 新增 `tools/todo/`、`tools/album/`、`tools/period/`、`tools/analysis/` 四个域包
3. 重排 `assistant/` → `agents/` + `tools/` + `assistant/`（保留 runtime/llm_gateway/resilience）
4. 把现有 15 个宝宝工具按域拆分到 `tools/baby/`
5. `graph.py` 拆成 `agents/state.py` + `agents/graph.py` + `agents/nodes/` + `agents/edges.py` + `agents/intents.py` + `agents/prompts/`
6. 单元测试全通过（mock LLM + SQLAlchemy）
7. **不影响** baby_assistant WS 端点（保持兼容）

**回滚**：目录重排是纯重构，如果出问题可以把 import 路径改回去

### 阶段二：统一入口（语音 + 文字合并）

1. 新建 `ws/ai_entrance.py`
   - 从 `voice_agent_langchain.py` 搬 `DashscopeRealtimeASR` 和 `DashscopeQwenTtsRealtime` 两个类（它们已经成熟）
   - 复制 `baby_assistant.py` 的鉴权/限流/HITL 挂起/事件协议/processing 互斥逻辑
   - 替换 Agent 入口为 `agents/graph.get_compiled_graph()`（复用 baby_assistant 图）
   - 合并 ASR → Agent → TTS 三段流式管线（用 `merge_async_iters`）
2. main.py 注册新路由，保持 baby_assistant 和 voice_agent_langchain 共存
3. 端到端测试（文字查询 + 语音查询 + 写操作 HITL + 断线重连）
4. AI Card 前端渲染实现

**回滚**：main.py comment out 新路由即可

### 阶段三：废弃旧端点 + 持久化存储替换

1. 把 checkpointer 从 MemorySaver 换成 **PostgreSQL AsyncPostgresSaver**（LangGraph 官方支持）
2. 废弃 `/ws/baby_assistant`、`/ws/voice-agent`、`/ws/voice_agent_langchain`、`/ws/rag_query`（前端路由全部切到 `/ws/ai-entrance`）
3. 把写操作的 HITL pending 状态存储从 Redis 换成 PostgreSQL（与 checkpointer 统一）
4. 部署 Redis 仅作为限流 + 幂等缓存（TTL 30 分钟内）
5. 压测 + 水平扩多实例验证（实例 A 发起 HITL → 实例 B 收到 confirm → 实例 A 已下线也能恢复，因为 checkpointer 在 PG）

**回滚**：main.py re-enable 旧路由

---

## 7. 为什么不是裸 ReAct / 裸 Plan-Execute / 多 Agent——三种候选范式的对比决策

这是本方案最核心的决策问题。2026 年有三种主流单 Agent 执行范式（ReAct、Plan-and-Execute、FSM/State Graph）和两种多 Agent 拓扑（Supervisor、Swarm）。本方案的最终选择是：**FSM/State Graph（LangGraph）作为承载容器，ReAct 为默认执行循环，Plan-and-Execute 作为复杂度路由后的可选嵌套分支**。

以下是每种候选被排除或被选中的具体理由：

### 7.1 裸 ReAct 循环——为什么不选它作为顶层架构？

**裸 ReAct 的形态**：一个 LLM + 一张工具表 + 一个 while 循环（LLM 决策 → 工具调用 → 观察 → 再决策，直到 LLM 说"我直接回答"）。没有状态图，没有显式路由，没有 checkpoint。

**为什么 90% 项目最后都放弃它**：

| 维度 | 裸 ReAct | FSM/State Graph + ReAct（本方案） |
|---|---|---|
| **持久化** | 崩溃后从头来（没有 checkpoint） | LangGraph checkpointer 持久化 state，崩溃/重启/实例切换都能续跑 |
| **HITL** | 要自己实现"检测到写操作就 break 循环 + 保存状态 + 等用户 + 从断点恢复" | 原生 `interrupt()` 暂停图，checkpointer 存状态，前端 approve 后 `Command(resume)` 恢复 |
| **路由** | 所有任务丢给同一个 LLM 自由选工具——"查今天奶量"和"生成本月健康报告"走同一条路径，LLM 会把简单问题复杂化 | 三级意图识别 + 复杂度路由：简单 CRUD → 直接 ReAct（省 planner token），复杂任务 → Planner 分支 |
| **预算/循环控制** | 要自己数 tool_calls 次数 + 超上限就 break 循环 + 兜底一条 "我不行了" | 图上加一条 `route_after_agent` 条件边 + `MAX_TOOL_ROUNDS=5`，超限自动走 `give_up_node` |
| **护栏/熔断** | 每个工具调用前要自己加 try-except + 重试逻辑 | 图级中间件统一处理；工具执行节点有 `resilience.IdempotencyManager` + `CircuitOpenError` |
| **调试** | 一条 trace，但执行路径全由 LLM 动态决定，bug 难复现（"为什么它那天选了工具 A 而不是 B？"） | 图上的每个节点都是确定性函数，可以 step-through 任意节点；条件路由是代码写死的，LLM 不能跳过 |
| **并发安全** | 多用户/多轮对话的 while 循环共享上下文容易串状态 | 每个 thread_id 独立 state，reducer 规则明确定义并发更新怎么 merge |

> 裸 ReAct 适合**演示/PoC**（50 行代码跑通一个"帮我查奶量"的 demo），**不适合生产**。本项目的 `assistant/graph.py` 已经写清楚了：ReAct 循环是 **agent_node 内部的执行方式**，不是顶层架构。

### 7.2 裸 Plan-and-Execute——为什么不全量用它？

**裸 Plan-and-Execute 的形态**：一个 Planner LLM 先出完整 step list（结构化的、固定数量的步骤），然后一个 Executor 逐步执行，每个 step 内部可以是工具调用。没有状态图承载，Planner 输出一次性决定所有后续。

**为什么在本项目里"全量用 Plan-and-Execute"是反模式**：

| 维度 | 裸 Plan-and-Execute | FSM + ReAct 默认、Plan-Execute 可选（本方案） |
|---|---|---|
| **Token 开销（90% 简单场景）** | "今天喝了多少奶？"也要先 Planner 出计划 → 多一次 LLM call（~500 token） | 直接 ReAct → 一次 LLM call + 工具调用 |
| **延迟（90% 简单场景）** | Planner + Executor 至少两次 LLM round trip | 一次 LLM round trip + 工具执行 |
| **规划成本** | Planner 可能规划错（比如把"查本月奶量"拆成"先查奶量再查睡眠再查疫苗"——后两个跟奶量无关），执行到一半发现不对 → 全部重新规划 | ReAct 让 LLM 边做边观察，发现不对可以调整下一个工具选择；复杂度路由只在确实需要时才启 Planner |
| **规划灵活性** | Planner 出的 step list 是"一次定终身"——中间观察到奶量数据异常（8000ml/天）想追加"查体温"验证？不行，step list 没这一步 | ReAct 循环的灵活性 + 复杂度路由的分层设计：简单任务不用规划（ReAct），复杂任务先规划（Planner）但每步内部仍可灵活调整 |
| **适用场景** | 开放式、步骤多但流程可枚举的任务（Deep Research、代码重构、文档生成） | 绝大多数 CRUD 查询/记录 + 少量复杂聚合（复杂度路由自动分流） |

> 关键洞察：**Plan-and-Execute 不是 FSM 的替代品，而是 FSM 图里的一个可选分支**。把 Planner 作为 `entry_node` 之后的一个条件路由分支（复杂度判定 → 复杂任务才进 Planner），就能同时拿到两种范式的好处。本方案的复杂度路由设计就是这个思路。

### 7.3 多 Agent/Supervisor——为什么不搞？

多 Agent 在本项目里**没有真正的技术优势**，只有工程复杂度。以下是具体理由：

| 维度 | FSM + ReAct/Plan-Execute（本方案） | Supervisor 多 Agent |
|---|---|---|
| **Token 成本** | 1 次入口 + N 次工具调用（N ≤ 3） | Supervisor 先拆任务 + 至少 1 次子 Agent 调用 + 汇总 → token 翻倍 |
| **延迟** | 稳定（单次 ReAct ~1-2s/步） | 每增加一层 Supervisor 就多一次 LLM round trip |
| **可观测性** | 一条 trace 贯穿全程 | Supervisor 和各子 Agent 各有自己的 trace，关联靠 thread_id 拼接 |
| **工具选择** | 一张 ToolRegistry（25 工具） | Supervisor 先"选子 Agent"，子 Agent 再"选工具"——两层选择都可能错 |
| **上下文隔离** | 不需要：user_id 已做数据隔离 | 需要但为此付出的成本 > 收益 |
| **工程复杂度** | 写 1 张图 + 补工具 | 写 N 张图 + Supervisor 路由 + handoff 契约 + 跨图状态调试 |
| **适用场景** | 25 工具、3-5 步任务、单用户单上下文 | 需要真并行（研究/编码/审查同时跑）、工具域差异巨大、独立沙箱 |

**正确判断标准**：

- "帮我写个待办" → **不需要多 Agent**。单 Agent 一个 ReAct 循环搞定
- "生成本月健康报告"（查奶量/睡眠/体温/疫苗/花费 + 调 RAG + 生成 Markdown） → **不需要多 Agent**。单 Agent 拿全量工具 + Plan-and-Execute 分支搞定
- "同时做三件事：写代码 + 跑测试 + 生成 PR 文案 + 自动 review" → **这才需要多 Agent**（真并行 + 独立沙箱 + 独立上下文）

本项目里没有第三种场景。

> 口诀：**能用确定性工作流解决的不要交给自主 Agent；能用单 Agent 搞定的不要上多 Agent**。2026 年多 Agent 真正的价值场景是 Open-ended 的长程任务（Deep Research/Code Agent/Autonomous Data Analysis），不是 CRUD 类业务。

### 7.4 最终决策矩阵

| 候选范式 | 决策 | 理由 |
|---|---|---|
| 裸 ReAct 循环 | ❌ 排除 | 没有状态持久化、没有 HITL、没有显式路由、没有护栏、调试困难。适合 PoC，不适合生产 |
| 裸 Plan-and-Execute | ❌ 不全量用 | 90% 简单场景有额外 token/延迟开销；规划是"一次定终身"，不够灵活 |
| **FSM/State Graph + ReAct 默认 + Plan-Execute 可选** | ✅ **选中** | 三层结构各司其职：FSM 承载工程约束（持久化/HITL/路由/护栏），ReAct 处理 90% 简单任务，Plan-Execute 处理剩余 10% 复杂任务；三种模式共享同一张图的 state 和 checkpointer |
| Supervisor 多 Agent | ❌ 排除 | 本项目场景没有真正的技术优势，token 成本翻倍、延迟增加、可观测性变差 |
| Swarm/网状拓扑 | ❌ 排除 | 生产环境不用，死循环、互相甩锅、token 指数膨胀 |

---

## 8. 生产级能力验收清单

按本方案落地后，逐条对照 [agent-system-types-and-structure.md](./agent-system-types-and-structure.md) 的 12 项生产级能力：

| # | 能力 | 本方案实现点 |
|---|---|---|
| 1 | 状态外置持久化 | Checkpointer: PostgreSQL AsyncPostgresSaver（阶段三落地） |
| 2 | Durable Execution | 每个节点可重试；中断从 checkpoint 恢复而非重头再来 |
| 3 | Human-in-the-loop | 所有写操作工具带 `is_write=True` → `agent_node` 里 `interrupt()` 暂停 |
| 4 | 工具治理 | `tools/registry.py`：注册/权限/超时/幂等元数据；参数 schema 校验 |
| 5 | Guardrails | `agents/middleware/guardrails.py` 输入注入检测 + 输出敏感词 |
| 6 | 预算与循环控制 | `MAX_TOOL_ROUNDS=5` + `agents/middleware/budget.py` token 预算检查 |
| 7 | 全链路可观测 | `agents/middleware/trace.py` + Langfuse/OTel 集成（复用 assistant/llm_gateway 埋点） |
| 8 | 离线评测集 + CI 门禁 | `evals/` 目录：意图分类、工具选择、端到端答案分层评测 |
| 9 | 模型网关 | `assistant/llm_gateway.py`：多供应商 + 任务路由 + 熔断 + 降级 + 成本统计 |
| 10 | 降级兜底 | CircuitOpenError → 系统降级提示；RAG 检索失败 → 明确说明无知识库内容 |
| 11 | 多租户数据隔离 | 所有工具强制注入 `user_id`（由 WS 鉴权层提取，不信任 LLM） |
| 12 | 版本化与灰度 | agents/prompts/ 按节点版本化；Graph 定义版本号；可按租户灰度切换 |

---

## 9. 面试谈点（Talking Points）

1. **"为什么选 FSM/State Graph 而不是裸 ReAct？"** ——两者不是替代关系：**FSM 是工程承载容器，ReAct 是 agent node 里的执行循环**。裸 ReAct 没有状态持久化（崩溃重跑）、没有 HITL（写操作拦不住）、没有显式路由（所有任务丢给 LLM 自由选）、调试难复现；FSM 把这些都做成图的一等公民：checkpointer 持久化、原生 `interrupt()`、条件路由是代码写死的、每个节点是确定性函数可 step-through。口诀：裸 ReAct 适合 PoC，FSM+ReAct 才是生产。
2. **"为什么不全量用 Plan-and-Execute？"** ——90% 的 CRUD 查询/记录场景（"今天奶量"、"记 120ml 喂奶"）加 Planner 是浪费：多一次 LLM call、延迟翻倍、规划是"一次定终身"不够灵活。Plan-and-Execute 应该是**复杂度路由后的可选分支**：简单任务直接走 ReAct（零额外开销），复杂多域任务（"生成本月健康报告"同时查奶量+睡眠+体温+疫苗+花费+RAG）才启 Planner，Planner 输出 step list 后每个 step 内部还是跑 ReAct。三种模式共享同一张 FSM 的 state 和 checkpointer。
3. **"WebSocket vs SSE 哪个好？"** ——本项目**只能选 WebSocket**。原因是语音需要双向流（客户端发 PCM 帧、服务端回 TTS 音频帧），SSE 是单向 server→client，要支持双向就得 SSE + HTTP 回调端点 + HTTP 音频上传端点，维护三套协议/鉴权/限流逻辑，而且语音帧每帧走一次 HTTP POST 延迟爆炸。WebSocket 一个端点搞定所有：文字 query、语音帧、HITL confirm、流式文本/音频输出，复用现有鉴权/限流/会话基础设施。
4. **"为什么不是多 Agent/Supervisor？"** ——25 个数据工具、3-5 步任务、单用户单上下文，没有真正需要多 Agent 的场景。FSM + ReAct（默认）+ Plan-and-Execute（复杂任务）已经覆盖。多 Agent 会让 token 成本翻倍、延迟增加、可观测性变差（多 trace 要拼接）、工程复杂度爆炸。正确判断："帮我写个待办"不需要多 Agent，"同时写代码+跑测试+生成 PR 文案+自动 review"才需要。
5. **"语音+文字统一入口怎么设计？"** ——一个 WS 端点，文字 query 直接进图，语音帧先过 DashScope 流式 ASR（paraformer-realtime-v2）拿最终 transcript 再进同一张 Agent 图；ASR/TTS 事件和 Agent emit 事件用 `merge_async_iters` 合并，统一推客户端；DashScope TTS 流式输出音频帧。文字/语音/断线重连/HITL 全链路一致。
6. **"LLM 随机游走怎么防？"** ——FSM 图先路由再执行：三级意图识别+复杂度路由把简单/复杂/闲聊分到不同专职节点；工具总数 25 按域分区注册+tags 过滤；`MAX_TOOL_ROUNDS=5` 超限走 give_up；写操作强制 HITL interrupt；熔断/幂等/护栏三重防护。ReAct 循环在 agent node 里跑但走图的条件路由和预算控制。
7. **"写操作为什么要 HITL？"** ——不信任 LLM 原则：LLM 可能"好心办坏事"（误删待办/错记奶量）。所有 `is_write=True` 工具触发 LangGraph 原生 `interrupt()`，checkpointer 持久化暂停状态，前端收到 `confirmation_request` 后等用户 approve/reject，通过 `Command(resume)` 恢复执行。
8. **"checkpointer 用什么？"** ——MemorySaver 只在本地 demo 用；生产必须 PostgreSQL AsyncPostgresSaver（LangGraph 官方），保证多实例水平扩时实例 A 发起 HITL 暂停、实例 B 收到 confirm 也能正确恢复。
9. **"现有代码怎么处理？"** ——assistant/ 里的好资产全保留重排目录：runtime（contextvar）、llm_gateway、resilience、graph 的图逻辑、15 个宝宝工具。语音管线复用 voice_agent_langchain.py 的 DashScope ASR/TTS 类，但删掉三明治 demo 的 Agent 换成 baby_assistant 图。目录重排是纯重构，import 路径改回去就能回滚。

---

## 参考来源

- [agent-system-types-and-structure.md](./agent-system-types-and-structure.md)（本项目 Agent 类型全景）
- [production-architecture-design.md](./production-architecture-design.md)（架构设计草案，G1-G6 验收）
- [assistant/graph.py](../app/assistant/graph.py)（现有生产级 LangGraph 图实现）
- [ws/baby_assistant.py](../app/ws/baby_assistant.py)（现有生产级 WS 网关）
- [ws/voice_agent_langchain.py](../app/ws/voice_agent_langchain.py)（现有 DashScope 流式 ASR/TTS 管线）
- LangGraph 官方文档：StateGraph / Checkpointer / interrupt() / Command(resume) / AsyncPostgresSaver
- Anthropic, *Building Effective Agents*（workflow 五模式，"能 deterministic 就不要自主"原则）
- 本项目 `api/todo.py`、Django baby 模块（待办/相册/经期模型来源）
