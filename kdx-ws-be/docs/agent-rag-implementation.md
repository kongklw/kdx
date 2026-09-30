# Agent 与 RAG 实现说明文档

> 项目：kdx-ws-be（Baby Assistant 后端）
> 本文档面向"想彻底搞懂这套系统怎么跑起来"的读者，从框架选型、图结构、工具调用，到 RAG 从数据源到最终回答的完整链路，逐层拆解。所有结论均对应真实代码，附文件与行号引用。

---

## 1. 总览

### 1.1 技术栈

| 组件 | 选型 | 版本 | 说明 |
|---|---|---|---|
| Web 框架 | FastAPI + WebSocket | 0.139.0 | 所有 AI 能力通过 WS 端点暴露 |
| Agent 框架 | **LangGraph** | 1.2.9 | 状态图驱动的 Agent 编排 |
| LLM 接入 | langchain-openai (`ChatOpenAI`) | 1.3.5 | OpenAI 兼容协议接阿里 DashScope |
| LLM 模型 | 通义千问 `qwen3.7-plus`（默认） | - | `ASSISTANT_MODEL` 环境变量可覆盖 |
| 向量数据库 | ChromaDB（PersistentClient 单机版） | 1.5.9 | SQLite 持久化，`data/chroma_db` |
| Embedding | `shibing624/text2vec-base-chinese` | text2vec 1.3.8 | 本地 CPU 推理，中文语义向量 |
| 关键词检索 | 手写 BM25Okapi + jieba | 0.42.1 | 零额外依赖 |
| 业务数据库 | MySQL + SQLAlchemy 2.0（同步） | 2.0.51 | 宝宝数据读写 |
| 鉴权 | JWT（PyJWT） | - | WS 连接级校验 |

依赖清单见 [requirements.txt](../requirements.txt)。

### 1.2 模块地图

```
app/
├── main.py                      # FastAPI 入口，注册 4 个 WS 路由
├── assistant/                   # ★ Agent 核心（LangGraph）
│   ├── graph.py                 #   状态图：意图识别→路由→ReAct/HITL/RAG/闲聊
│   ├── tool_registry.py         #   工具注册中心（schema 生成 + 安全执行）
│   ├── tools.py                 #   16 个宝宝数据工具（8 读 8 写）
│   ├── repository.py            #   SQLAlchemy 数据访问层
│   ├── db_models.py             #   宝宝数据表模型
│   └── resilience.py            #   熔断器 + 幂等管理器
├── rag/                         # ★ RAG 检索核心
│   ├── retriever.py             #   HybridRetriever：混合召回→融合→精排→父章节扩展
│   └── bm25.py                  #   手写 BM25Okapi
├── ws/                          # ★ WebSocket 接入层
│   ├── baby_assistant.py        #   /ws/baby_assistant  Agent 主入口
│   ├── rag_query.py             #   /ws/rag_query       RAG 独立查询入口（RAG 图）
│   ├── voice_agent_langchain.py #   /ws/voice_agent_langchain 语音 Agent demo
│   └── voice_agent.py           #   /ws/voice-agent     纯 echo 占位
├── scripts/
│   └── text2vec_embedding_text2vec.py  # EmbeddingFunction 适配器
└── core/                        # 配置 / JWT 安全 / 日志 / DB

scripts/
├── load_rag_knowledge.py        # ★ 离线摄入：切分 + 元数据 + 入库 Chroma
├── eval_rag.py                  # ★ 检索评估（HitRate/MRR，A/B 对比，CI 门禁）
└── load_rag_knowledge_simple.py # 简化版摄入（旧）
data/
├── rag/baby_feeding/            # 知识库源文档（9 个权威机构目录的 .md）
└── chroma_db/                   # Chroma 持久化 + db_summary.json
```

### 1.3 整体架构

```
                         ┌──────────────────────────────────────────────┐
  前端 (WebSocket)        │                FastAPI 后端                   │
                         │                                              │
  /ws/baby_assistant ───▶│ baby_assistant.py                            │
  /ws/rag_query ────────▶│ rag_query.py          ┌────────────────┐    │
                         │        │              │  MySQL(业务数据) │    │
  /ws/voice_agent_       │        ▼              └────────────────┘    │
    langchain ──────────▶│  ┌──────────────────────────────┐            │
                         │  │  LangGraph 状态图             │            │
                         │  │  Assistant: entry→agent/rag/  │──tools──▶ │ (SQLAlchemy)
                         │  │             chitchat/fallback │           │
                         │  │  RAG: retrieve→rerank→generate│           │
                         │  └──────────────────────────────┘            │
                         │        │                │                    │
                         │        ▼                ▼                    │
                         │  ChatOpenAI(qwen)    HybridRetriever         │
                         │  (DashScope 兼容)     ├─ ChromaDB(向量)       │
                         │                       └─ BM25+jieba(关键词)  │
                         └──────────────────────────────────────────────┘
```

有 **两条独立的 AI 链路**：
1. **Agent 链路**（`/ws/baby_assistant`）：意图识别 → 数据查询/记录（Function Calling + HITL）/ 知识问答（RAG）/ 闲聊。
2. **纯 RAG 链路**（`/ws/rag_query`）：独立的三节点 RAG 图（retrieve → rerank → generate）。

---

## 2. Agent 实现详解

### 2.1 框架与核心文件

Agent 基于 **LangGraph 的 `StateGraph`** 手工编排（不是 `create_react_agent` 预置模板），核心在 [graph.py](../app/assistant/graph.py)。

LangChain/LangGraph 采用**懒加载**模式（[graph.py L54-76](../app/assistant/graph.py#L54-L76)）：首次调用 `_init_lc()` 才 import，避免模块导入期就拉起 torch 等重依赖。

LLM 构造（[graph.py L108-119](../app/assistant/graph.py#L108-L119)）：

```python
llm = ChatOpenAI(
    model=MODEL_NAME,                    # 默认 qwen3.7-plus，env ASSISTANT_MODEL 可覆盖
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",  # OpenAI 兼容模式
    temperature=0.3,
    streaming=streaming,                 # 数据 Agent 非流式，RAG/闲聊流式
)
```

关键常量（[graph.py L79-82](../app/assistant/graph.py#L79-L82)）：

```python
MODEL_NAME = os.getenv("ASSISTANT_MODEL", "qwen3.7-plus")
MAX_TOOL_ROUNDS = 5          # ReAct 最大循环轮数（防失控）
CONFIDENCE_THRESHOLD = 0.6   # 意图置信度阈值，低于走 fallback
```

### 2.2 State 定义

`AssistantState`（[graph.py L126-157](../app/assistant/graph.py#L126-L157)）是一个 `TypedDict(total=False)`，字段分五组：

| 分组 | 字段 | 作用 |
|---|---|---|
| 基础 | `user_id / query / request_id` | 由 WS 层注入，**不信任 LLM** |
| HITL | `resume / confirmed / pending_write / confirmed_call` | 人工确认的暂停/恢复 |
| 会话 | `messages` | langchain 消息列表（多轮历史） |
| 意图 | `intent / confidence / slots / route` | 规则+LLM 两级识别结果 |
| 上下文 | `baby_context` | 宝宝名字/生日/月龄 + 今日日期，注入 system prompt |
| 工具链路 | `tool_rounds / tool_calls / tool_trace` | ReAct 循环计数与轨迹 |
| 输出 | `answer / sources / error` | 最终回答、引用来源 |

### 2.3 图结构：节点、边与路由

图构建在 `build_assistant_graph()`（[graph.py L605-660](../app/assistant/graph.py#L605-L660)），结构如下：

```
                 ┌─────────────┐
    START ──────▶ │ entry       │ 加载宝宝上下文 + 两级意图识别
                 └──────┬──────┘
          route_entry（条件边；HITL resume 时直通 tools）
     ┌───────────────┼──────────────────┐
     ▼               ▼                  ▼
 ┌───────┐    ┌─────────┐        ┌──────────┐
 │ agent │    │   rag   │        │ chitchat │────▶ END
 │(ReAct)│    │(知识问答)│        │ fallback │────▶ END
 └───┬───┘    └────┬────┘        └──────────┘
     │ route_after_agent
     ├─ pending_write → wait_confirm ──▶ END（HITL 暂停，WS 层等确认）
     ├─ tool_calls   → tools ──────────▶ agent（ReAct 循环回边）
     └─ 都没有        → END（agent 已直接回答）
```

几个要点：

1. **每次 WS 连接都重新编译一张图**（[baby_assistant.py L77](../app/ws/baby_assistant.py#L77) `graph = build_assistant_graph(ws=ws)`）。因为节点用**同步工厂函数 + 闭包**捕获该连接的 `ws`（事件推送）与 `idem`（幂等管理器）——这是项目遵循的"同步工厂、异步闭包"模式。
2. **编译时未传 checkpointer**（[graph.py L660](../app/assistant/graph.py#L660) `return workflow.compile()`），图本身无跨轮持久化。
3. `wait_confirm` 直接连 `END`：HITL 不是 LangGraph 原生 `interrupt()`，而是"图正常结束 + WS 层保存挂起状态 + 用户确认后用 `make_resume_state()` 重新 `ainvoke`"（[graph.py L663-672](../app/assistant/graph.py#L663-L672)）。

### 2.4 两级意图识别（规则优先 → LLM 兜底）

在 `entry` 节点（[graph.py L261-299](../app/assistant/graph.py#L261-L299)）执行：

1. **第一级：规则匹配**（`_rule_intent`，[graph.py L186-210](../app/assistant/graph.py#L186-L210)）——零延迟零成本。三张关键词表：
   - `DATA_QUERY_PATTERNS`：奶量/体温/睡眠/尿不湿/花费/成长/疫苗/生日 → `data_query`（置信度 0.9）
   - `KNOWLEDGE_PATTERNS`：怎么/为什么/能不能/辅食/黄疸… → `knowledge_qa`（0.85）
   - `CHITCHAT_PATTERNS`：你好/你是谁 → `chitchat`（0.8）
   - 另有正则兜底：`记录|记一下` 或 `数字+单位`（如 "80ml"）→ `data_query`
2. **第二级：LLM few-shot 分类**（`_llm_intent`，[graph.py L213-241](../app/assistant/graph.py#L213-L241)）——规则未命中时，让 LLM 输出 `{"intent":..., "confidence":...}` JSON，`json.loads` 提取花括号内解析。
3. **置信度兜底**：低于 `0.6` 一律按 `chitchat` 处理（[graph.py L284-285](../app/assistant/graph.py#L284-L285)）。
4. LLM 意图调用被熔断器包住（`_safe_llm_intent`），熔断打开时降级为 `knowledge_qa(0.55)`。

路由是**声明式映射**（`route_after_intent`，[graph.py L333-340](../app/assistant/graph.py#L333-L340)）：`data_query→agent`、`knowledge_qa→rag`、`chitchat→chitchat`、未知→`fallback`。

同时 `entry` 会调 `_load_baby_context()`（[graph.py L302-322](../app/assistant/graph.py#L302-L322)）从 MySQL 查宝宝信息，生成"今天是 X。宝宝信息: 名字=…, 月龄=…个月。"注入后续所有 system prompt。

### 2.5 Function Calling：工具注册中心 + ReAct 循环

#### 工具注册中心（[tool_registry.py](../app/assistant/tool_registry.py)）

```python
@dataclass
class ToolMeta:
    name: str
    description: str
    parameters: Dict[str, Any]              # JSON Schema
    handler: Callable[..., Dict[str, Any]]  # 同步函数
    is_write: bool = False                  # 写操作 → 触发 HITL
    tags: List[str] = ...
```

- `get_schemas_for_llm()`：把工具转成 OpenAI function calling 格式 `[{type:"function", function:{name,description,parameters}}]`，交给 `llm.bind_tools()`。
- `execute()`：统一异常包装为 `{"ok": False, "error": ...}`，工具内抛异常不会炸图。
- `is_write_tool()`：Agent 层据此决定是否触发人工确认。

#### 工具集（[tools.py](../app/assistant/tools.py)）

16 个工具覆盖宝宝数据全部场景（8 读 8 写）：

| 读（无需确认） | 写（需要 HITL 确认） |
|---|---|
| `get_baby_info` | `add_feed_milk`（记录喂奶） |
| `query_feed_milk` | `add_temperature`（记录体温，30~45℃ 校验） |
| `query_temperature` | `add_sleep`（记录睡眠） |
| `query_sleep` | `add_diaper`（记录尿不湿） |
| `query_diapers` | `add_expense`（记录花费） |
| `query_expense` | `add_growth`（记录身高体重头围） |
| `query_growth` | `mark_vaccine_done`（标记疫苗已接种） |
| `query_vaccines` / `query_birthdays` | — |

工具全是**同步函数**（SQLAlchemy 同步访问），内部做参数归一化：`parse_day()` 把 `today/yesterday/2026-08-26` 统一成 `date`。**关键安全设计：所有工具签名都含 `user_id`，但该参数不出现在传给 LLM 的 schema 里**，执行前由 `tool_exec_node` 强制注入真实身份——LLM 无法伪造他人身份。

#### ReAct 循环（[graph.py L345-508](../app/assistant/graph.py#L345-L508)）

**`agent` 节点**（LLM 决策）：

```python
msgs = [SystemMessage(content=system)] + messages + [HumanMessage(content=query)]
llm = _make_llm(streaming=False, bind_tools_schemas=schemas)
resp = await get_llm_breaker().call(llm.ainvoke, msgs)      # 熔断保护
tool_calls = list(getattr(resp, "tool_calls", None) or [])
```

三种出口：
- 无 tool_calls → 直接把 `resp.content` 作为回答（推 `generate_chunk` + `answer_done`）。
- 有写操作且未确认 → 构造 `pending_write`（含 `confirm_id=CFM-{毫秒时间戳}`），推 `confirmation_request` 事件，返回后条件边把它送进 `wait_confirm → END` 暂停。
- 有读操作（或已确认）→ 返回 `tool_calls`，条件边送进 `tools`。

**`tools` 节点**（工具执行，[graph.py L434-506](../app/assistant/graph.py#L434-L506)）逐个执行：

1. 把 `AIMessage(tool_calls=...)` 追加进 messages（保证 ToolMessage 配对合法）。
2. **注入身份与幂等键**：`args["user_id"] = user_id; args.setdefault("request_id", request_id)`。
3. **幂等检查**（仅写操作）：`idem.tool_key(request_id, name, args)` 生成 SHA256 键，命中缓存则直接返回"该记录已存在，未重复写入"。
4. **执行**：`await asyncio.to_thread(registry.execute, name, args)`——同步 SQLAlchemy 不阻塞事件循环。
5. 结果包成 `ToolMessage` 追加回 messages，推 `tool_result` 事件，记录 `tool_trace`。
6. 返回 `tool_rounds + 1`，条件边 `tools → agent` 回到 LLM 总结——**这就是 ReAct 循环**：思考 → 调工具 → 观察 → 再思考，直到 LLM 不再调工具、输出最终中文总结。

### 2.6 HITL（Human-in-the-Loop）人工确认

写操作（记录奶量/体温等）必须经用户确认才落库，流程横跨图与 WS 层：

```
agent 决策出写操作
   │ 推 confirmation_request {confirm_id, tools:[{name,args,description}]}
   ▼
wait_confirm → 图 END（状态冻结在 WS 层的 pending 变量）
   │
用户发送 {"type":"confirm","confirm_id":"CFM-...","action":"approve"/"reject"}
   │
   ├─ reject → 直接回复"已取消"，不重新进图（[baby_assistant.py L145-150]）
   └─ approve → make_resume_state(pending, confirmed=True)
                构造 {resume:true, confirmed:true, confirmed_call: pending.tool_calls}
                重新 graph.ainvoke(resume_state)
                entry 节点检测到 resume 直通 → route_entry 返回 "tools"
                tools 节点从 confirmed_call 取出工具执行 → 回 agent 总结
```

代码位置：[graph.py L388-404](../app/assistant/graph.py#L388-L404)（发起确认）、[graph.py L663-672](../app/assistant/graph.py#L663-L672)（恢复状态）、[baby_assistant.py L134-170](../app/ws/baby_assistant.py#L134-L170)（WS 层确认处理）。恢复时有 `confirm_id` 校验防串号。

### 2.7 容错层：熔断 + 幂等（[resilience.py](../app/assistant/resilience.py)）

**熔断器**（三态机 Closed → Open → Half-Open）：

```python
LLMCircuitBreaker(
    name="assistant-llm",
    failure_threshold=0.6,   # 失败率 ≥60% 熔断
    min_calls=4,             # 至少 4 个样本才统计
    recovery_timeout=30.0,   # Open 30 秒后进 Half-Open 试探
)
```

- `call()`：包同步式 await 调用；`call_stream()`：包 `llm.astream` 异步生成器，迭代中途异常也算失败。
- 熔断打开时抛 `CircuitOpenError`，各节点捕获后输出固定降级文案"【系统降级】AI 服务暂时不可用，请稍后重试"（如 [graph.py L376](../app/assistant/graph.py#L376)、[L558-560](../app/assistant/graph.py#L558-L560)）。

**幂等管理器** `IdempotencyManager`：

- 键 = `sha256(request_id + tool_name + args JSON)`（[resilience.py L157-160](../app/assistant/resilience.py#L157-L160)）。
- 内存实现（TTL 30 分钟，上限 256 条），覆盖"前端重试/用户双击导致同一 request_id 重复提交"。
- 代码注释明确说明：生产应替换为 Redis SETNX + TTL。

### 2.8 WebSocket 接入层与事件协议（[baby_assistant.py](../app/ws/baby_assistant.py)）

**鉴权**：三种 token 提取方式——query 参数 `?token=`、`Authorization: Bearer` 头、Cookie（[baby_assistant.py L49-53](../app/ws/baby_assistant.py#L49-L53)），失败以 4401 关闭连接。

**客户端 → 服务端**：

```json
{"type": "ping"}
{"type": "query", "query": "今天喝了多少奶", "request_id": "uuid"}
{"type": "confirm", "confirm_id": "CFM-...", "action": "approve" | "reject"}
```

**服务端 → 客户端**（全链路事件，前端据此渲染过程动画）：

| 事件 | 时机 |
|---|---|
| `connected` | 连接建立 |
| `intent_start` / `intent_detected` | 意图识别开始/结果（含置信度与来源 rule/llm） |
| `retrieve_start` / `retrieve_done` | RAG 检索开始/结果（含来源列表） |
| `tool_call` / `tool_result` | 每个工具调用/返回 |
| `confirmation_request` / `wait_confirm` | HITL 发起/挂起 |
| `generate_chunk` | LLM 流式文本块 |
| `answer_done` | 最终答案（含 sources / tool_trace） |
| `query_done` / `query_error` | 请求结束/出错 |

**并发控制**：连接级 `processing` 布尔锁，处理中再收到 query 直接回 `busy` 错误（[baby_assistant.py L200-209](../app/ws/baby_assistant.py#L200-L209)）。

**多轮记忆**：WS 层手工维护 `history`（langchain messages），每轮追加 `HumanMessage(query)` + `AIMessage(answer)`，上限 `MAX_HISTORY_MESSAGES = 20` 条，构造初始 state 时传入 `messages` 字段（[baby_assistant.py L79-112](../app/ws/baby_assistant.py#L79-L112)）。

### 2.9 一次 Agent 请求的完整生命周期

以用户发送 **"记录喂奶 80ml"** 为例：

```
1. WS 收到 query（request_id=uuid）→ 推 query_start
2. graph.ainvoke(initial_state)
3. entry 节点：
   - 查 MySQL 得宝宝上下文（"月龄=8个月"）
   - 规则意图：命中"记录"正则 → data_query(0.85)，零 LLM 调用
   - 推 intent_detected
4. route_after_intent → agent
5. agent 节点：system(角色+宝宝上下文) + history + 用户消息 → bind_tools 的 qwen
   → 返回 tool_calls=[{name:"add_feed_milk", args:{milk_volume:80}}]
   → add_feed_milk 是写操作且未 confirmed
   → 推 confirmation_request，state 置 pending_write
6. route_after_agent → wait_confirm → 图 END
7. WS 层保存 pending，推 wait_confirm 事件
   ……（用户在前端点"确认"）
8. 收到 {"type":"confirm","action":"approve"}
   → make_resume_state() → 重新 ainvoke
   → entry 检测 resume 直通 tools
9. tools 节点：
   - 注入 user_id/request_id
   - 幂等键查缓存（未命中）
   - to_thread 执行 SQLAlchemy insert
   - 成功 → 存幂等结果；推 tool_call / tool_result
   - 返回后回 agent
10. agent 节点：带着 ToolMessage 再调 LLM → 无 tool_calls
    → 流式输出"好的，已记录 80ml 奶量…" → answer_done
11. WS 层把本轮 Human/AI 消息追加进 history（≤20 条），推 query_done
```

### 2.10 语音 Agent（[voice_agent_langchain.py](../app/ws/voice_agent_langchain.py)）

一个端到端**语音实时对话 demo**（三明治店点餐场景），展示与主 Agent 不同的另一种 LangGraph 用法：

- **语音管线**：DashScope 实时 ASR（`DashscopeRealtimeASR`）→ 文本进 Agent → DashScope 实时 TTS（`DashscopeQwenTtsRealtime`，模型 `qwen3-tts-vd-2026-01-26`，音色 Cherry）→ 音频二进制块回推。
- **Agent 构建**（[L115-143](../app/ws/voice_agent_langchain.py#L115-L143)）：优先 `langchain.agents.create_agent`，失败则回退 `langgraph.prebuilt.create_react_agent`——即 **LangGraph 预置 ReAct 模板**（与主 Agent 的手工 StateGraph 形成对照），工具用 `@tool` 装饰器定义。
- **记忆**：传入 `checkpointer=InMemorySaver()`，每会话生成 `thread_id`，通过 `config={"configurable":{"thread_id":...}}` 实现多轮。
- **流式**：`agent.astream(..., stream_mode="messages")` 把 `AIMessageChunk/ToolMessage` 转成 `AgentChunkEvent/ToolCallEvent/ToolResultEvent`，与 TTS 音频流经 `merge_async_iters` 合并推送。
- 定位是**演示/学习代码**，未接入业务数据工具。

另外 `/ws/voice-agent`（[voice_agent.py](../app/ws/voice_agent.py)）是纯 echo 占位端点，仅用于音频通道联调。

---

## 3. RAG 实现详解

### 3.1 总体架构与数据流

```
【离线】 源文档(.md) → 加载/去重 → 元数据提取 → 结构感知切分 → 质量过滤
         → text2vec 向量化 → ChromaDB 持久化 (data/chroma_db, 651 chunks)
                    scripts/load_rag_knowledge.py

【在线】 用户 query ─┬─▶ 向量检索 (Chroma, top-20) ─┐
                     └─▶ BM25+jieba (top-20) ──────┤ RRF 融合
                                                   ▼
                                     月龄软过滤 + 权威度加权 + 文档级多样性
                                                   ▼ top-3
                                     父章节扩展(small-to-big) → 拼 prompt
                                                   ▼
                                     qwen 流式生成 + 引用来源 → WebSocket
                              app/rag/retriever.py + app/ws/rag_query.py
```

### 3.2 知识库数据源与元数据设计

源文档在 `data/rag/baby_feeding/`，按**权威机构**分 9 个目录：WHO、美国CDC、美国儿科学会、英国NHS、中国疾控中心、国家卫生健康委、中国营养学会、健康中国、综合知识。当前规模（`data/chroma_db/db_summary.json`）：**202 篇文档 → 651 个 chunk**，覆盖 13 个主题（喂养营养/生长发育/疫苗接种/睡眠作息/常见疾病等）。

每个 chunk 携带丰富元数据（[load_rag_knowledge.py L370-382](../scripts/load_rag_knowledge.py#L370-L382)）：

| 元数据 | 来源 | 用途 |
|---|---|---|
| `category`（机构） | 目录名 | 检索层加权 |
| `authority`（权威度 2~5） | `SOURCE_AUTHORITY` 静态表：卫健委/WHO/CDC=5，营养学会=4，综合=3 | 精排加权 |
| `topics`（13 主题） | `TOPIC_KEYWORDS` 关键词规则检测 | 过滤/展示 |
| `age_ranges`（月龄段） | `AGE_RANGE_KEYWORDS` 规则检测：0-6个月/6-12个月/1-3岁/3-6岁 | 月龄软过滤 |
| `title` / `section` / `parent_section` | 文档一级标题 / 多级标题路径 | 引用展示 / 父章节扩展 |
| `chunk_index` / `total_chunks` | 切分序号 | 相邻块回溯 |

### 3.3 离线摄入：加载 → 切分 → 入库（[scripts/load_rag_knowledge.py](../scripts/load_rag_knowledge.py)）

**① 加载与去重**（`load_markdown_files`，L278-316）：遍历目录读 `.md`，按文档一级标题去重；同时从 `**来源**: [xx](url)` 行提取来源。

**② 结构感知切分**（`split_document_by_section`，L189-244）——这是切分的核心，三阶段流水线：

- **阶段 1 解析原子单元**（`_parse_units`，L95-140）：逐行解析 markdown，用**标题栈**维护 `#`~`######` 层级，每个块携带完整标题路径（如 `疫苗接种 > 流感疫苗 > 注意事项`）；连续 `|` 行聚合为**表格原子块**（表格永不跨块拆散），段落是原子单元（句子永不被切断）。
- **阶段 2 短节合并**：标题开启新章节组，估算组内 token，少于 `MIN_CHUNK_TOKENS = 80` 的碎节向前并入，避免碎块被质量过滤丢弃。
- **阶段 3 线性打包**：按 `chunk_size=500`（近似 token）装填，超限封口；封口时 `_tail_overlap()`（L176-186）从尾部回取**完整原子单元**（不取半句、不跨 heading、总量 ≤ overlap=50 且 ≤ 半块）作为下一块开头。单个段落超长时走 `_hard_split()` 句子级硬切兜底（同样带 overlap）。

**token 估算**（`_est_tokens`，L81-92）：不依赖 tiktoken 联网下载词表——CJK 字符 1 字 ≈ 1 token，其他 4 字符 ≈ 1 token，误差 <15%。

**③ 质量过滤与去重**（L247-259）：`len(content) >= 100` 字符；内容 hash 去重。

**④ 入库**（`init_chroma_db`，L326-426）：

```python
client = PersistentClient(path='data/chroma_db')
collection = client.get_or_create_collection(
    name="baby_feeding",
    embedding_function=Text2VecEmbeddingFunction(),
    metadata={"hnsw:space": "cosine"},     # 余弦相似度
)
collection.add(documents, metadatas, ids)   # batch=100; id = f"{filename}_{chunk_index}"
```

重建策略是**全量重建**（先 `shutil.rmtree` 删旧库），并在 `db_summary.json` 落一份统计摘要。

### 3.4 Embedding（[app/scripts/text2vec_embedding_text2vec.py](../app/scripts/text2vec_embedding_text2vec.py)）

```python
class Text2VecEmbeddingFunction(EmbeddingFunction):
    def __init__(self, model_name='shibing624/text2vec-base-chinese'):
        self.model = SentenceModel(model_name)   # text2vec, 本地 CPU torch 推理

    def embed_documents(self, texts):   # 批量：入库用
        return self.model.encode(texts, normalize_embeddings=True).tolist()

    def embed_query(self, input):       # 单条：查询用
        return self.model.encode([input], normalize_embeddings=True).tolist()
```

- 模型：`text2vec-base-chinese`（CoSENT 训练的中文句向量模型），输出**归一化**向量，配 Chroma 的 cosine 空间。
- 运行位置：**Web 进程内 CPU 推理**（无独立 embedding 服务），首次调用懒加载模型。

### 3.5 在线检索：HybridRetriever（[app/rag/retriever.py](../app/rag/retriever.py)）

`search(query, k=3, fetch=20)` 五步流水线：

**① 双路召回**（L137-142）：

```python
q_emb = self.embed_fn.embed_query(query)
vec = self.collection.query(query_embeddings=q_emb, n_results=fetch)   # 向量路
bm_pairs = idx['bm25'].top_n(list(jieba.cut_for_search(query)), fetch)  # 关键词路
```

设计动机：向量漏**关键词硬匹配**（如疫苗名"脊灰"），BM25 漏同义改写，互补。

**BM25 实现**（[bm25.py](../app/rag/bm25.py)）——手写 BM25Okapi（零新依赖，40 行核心算法）：`k1=1.5`（词频饱和）、`b=0.75`（长度归一化），IDF 用 `ln((N-df+0.5)/(df+0.5)+1)`，分词用 `jieba.cut_for_search`。索引**懒构建**：首次查询把 Chroma 全库 `collection.get()` 拉到内存分词建索引（L104-116）；`invalidate_index()` 供知识库重建后强制失效。

**② RRF（Reciprocal Rank Fusion）融合**（L145-157）：

```python
d['rrf'] += 1.0 / (self.rrf_k + rank + 1)     # rrf_k=60，对每路排名求和
```

按排名（而非分数）融合——双路都命中的文档自然得分高，无需调两路分数量纲。

**③ 月龄软过滤 + 权威度加权**（L159-173）：

```python
final = rrf_norm + age_boost项 + w_authority·(authority/5 - 0.5)
# age_boost=0.15：query 抽出月龄（正则 '6个月'/'1岁'）与 meta.age_ranges 匹配
#   （±3 个月容差）→ +0.15；明确不匹配 → -0.075；元数据缺失 → 0（优雅降级）
# w_authority=0.1：WHO/CDC(5分) 比 综合知识(3分) 排名更靠前
```

**④ 文档级多样性 top-k**（L177-188）：同一文档（按 `id` 前缀 `filename_` 判定）只取最高分块进 top-k=3，避免一篇文档的多个 chunk 挤占名额——被挤掉的邻居块由下一步补回。

**⑤ 父章节扩展（small-to-big）**（`expand_parents`，L200-230）：对每个命中块，按 `chunk_index ± 1` 找**同 parent_section** 的相邻块拼进上下文（`rel='parent'` 标注"补充"），预算 `max_expand_tokens=600`。检索用小块保证精准，返回用父章节保证完整。

### 3.6 生成与引用（[rag_query.py](../app/ws/rag_query.py)）

三节点 RAG 图（`create_rag_graph`，L232-256）：`retrieve → rerank → generate`。

- `retrieve_node`（L131-166）：调 `HybridRetriever.search(k=3, fetch=20)`，把命中列表（含 `vec_rank/bm25_rank/score/age_match` 调试信息）推给前端。
- `rerank_node`（L169-183）：`expand_parents` + `build_context`——最终上下文里命中块标注"【文档N·命中】"，扩展块标注"【文档N·补充】"。
- `generate_node`（L186-229）：拼 prompt（规则明确要求"优先使用知识库；没有则明确说明；标注引用来源如 [文档1]"），`ChatOpenAI(model='qwen3.7-plus', temperature=0, streaming=True)` 流式生成，每个 chunk 推 `generate_chunk` 事件，最终 `generate_done` 携带完整 answer + sources（title/filename/category）。

### 3.7 RAG WebSocket 查询链路（`/ws/rag_query`）

```
client: {"type":"query","query":"6个月能吃鸡蛋吗"}
server: query_start
      → retrieve_start → retrieve_done {documents:[{title,section,score,vec_rank,bm25_rank,age_match}]}
      → rerank_done    {hit_count, expanded_count, context_chars}
      → generate_start → generate_chunk × N（流式文本）→ generate_done {answer, sources}
      → query_done
```

连接同样走 JWT 三方式鉴权（query/Bearer/Cookie），支持 ping/pong 心跳。

### 3.8 评估体系（[scripts/eval_rag.py](../scripts/eval_rag.py)）

项目带了一个**检索回归评估**脚本，理念是"检索策略切换、参数调优不能凭感觉，必须在固定标注集上量化"：

- **标注集**：内置 12 条 seed 用例（中文口语 query → 相关文档名，命中任一 chunk 即算），支持 `--cases` 外部扩充。
- **指标**：`HitRate@k`（k=1,3,5,10，核心召回指标）、`MRR`（第一条相关文档排名倒数均值）、`AvgRank`、`AvgLatencyMs`。
- **A/B 对比**：同一标注集分别跑"纯向量（旧实现）"与"混合检索（新实现）"，输出差值表。
- **CI 门禁**：`--min-hitrate 0.6` 低于阈值退出码 1，可接入 CI。

### 3.9 一次 RAG 查询的完整生命周期

```
1. 用户在知识问答页输入 "宝宝辅食什么时候开始添加" → WS query
2. query_start
3. retrieve 节点：
   - embed_query("宝宝辅食什么时候开始添加") → 768 维向量（首次调用会加载模型）
   - Chroma 向量召回 top-20；BM25（首次查询懒建全库索引）召回 top-20
   - RRF 融合 → 月龄软过滤（query 无月龄则跳过）→ 权威度加权 → 文档去重 top-3
4. rerank 节点：top-3 各回溯 1 个同父章节相邻块（600 token 预算）
   → build_context 生成带【命中/补充】标注的上下文
5. generate 节点：system 规则 + 知识库内容 + 用户问题 → qwen 流式生成
   → generate_chunk 逐块推送 → 前端同时渲染来源卡片
6. query_done {answer, sources:[{title, filename, category}]}
```

### 3.10 Agent 与 RAG 的结合点

`/ws/baby_assistant` 图内有一个 `rag` 节点（`make_rag_node`，[graph.py L513-565](../app/assistant/graph.py#L513-L565)）：意图识别为 `knowledge_qa` 时走这里。它复用了 `rag_query.py` 的 Chroma collection 与 embedding 函数，但**实现是简化版**：直接 `collection.query(n_results=3)` 纯向量检索（未走 HybridRetriever 混合检索），拼上下文后流式生成。也就是说，独立 RAG 端点用的是完整混合检索，Agent 内嵌 RAG 用的是纯向量检索——两者的统一是当前待优化点之一（见优化文档 §3.1）。

---

## 4. 快速上手索引

| 想了解 | 看哪里 |
|---|---|
| Agent 图怎么编 | [app/assistant/graph.py](../app/assistant/graph.py) `build_assistant_graph()` |
| 有哪些工具、schema 长啥样 | [app/assistant/tools.py](../app/assistant/tools.py) `register_baby_tools()` |
| 熔断/幂等怎么实现 | [app/assistant/resilience.py](../app/assistant/resilience.py) |
| 切分策略细节 | [scripts/load_rag_knowledge.py](../scripts/load_rag_knowledge.py) `split_document_by_section()` |
| 混合检索/RRF/父章节扩展 | [app/rag/retriever.py](../app/rag/retriever.py) `HybridRetriever.search()` |
| RAG 端到端事件协议 | [app/ws/rag_query.py](../app/ws/rag_query.py) |
| Agent WS 协议与 HITL | [app/ws/baby_assistant.py](../app/ws/baby_assistant.py) |
| 检索效果评估 | [scripts/eval_rag.py](../scripts/eval_rag.py) |

深度专题解析（切分/混合检索/流式生成的逐行拆解，Agent 框架选型与 RAG 交互的决策分析）见姊妹文档：[agent-rag-deep-dive.md](./agent-rag-deep-dive.md)。

生产级差距与优化路线见姊妹文档：[production-optimization-roadmap.md](./production-optimization-roadmap.md)。
