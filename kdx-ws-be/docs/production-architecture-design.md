# 生产级 Agent / RAG 架构设计草案

> 定位：**目标态（to-be）架构设计**。基于现状文档 [agent-rag-implementation.md](./agent-rag-implementation.md)、深度解析 [agent-rag-deep-dive.md](./agent-rag-deep-dive.md) 与差距分析 [production-optimization-roadmap.md](./production-optimization-roadmap.md) 演进而来。
> 原则：**复用现有资产、渐进式演进、每一步可回滚**——不推倒重来，把现有代码按生产标准重排。

---

## 1. 设计目标与非目标

### 1.1 目标

| # | 目标 | 量化验收 |
|---|---|---|
| G1 | 会话与挂起状态可持久化，多实例水平扩展 | 断线重连记忆不丢；任一实例可接续任一用户会话 |
| G2 | 检索质量可度量、可持续优化 | HitRate@5 ≥ 0.85（CI 门禁），RAGAS faithfulness ≥ 0.85 |
| G3 | 全链路可观测 | 每次请求可回放 trace；token 成本/延迟 P95 有面板 |
| G4 | 事件循环零阻塞 | 压测下长耗时操作（embedding/检索/DB）不阻塞其他连接 |
| G5 | 故障自动隔离与降级 | LLM/向量库任一依赖故障时服务整体可用（降级而非雪崩） |
| G6 | 知识库安全更新 | 增量更新 + 版本回滚；更新期间检索服务不中断 |

### 1.2 非目标（当前明确不做）

- 多模态输入（图片/语音理解进 Agent 主链路）——语音保持独立 demo 通道；
- Multi-Agent 协作——单图 + 意图路由已满足业务复杂度；
- 语义缓存/向量缓存——数据规模（651 chunks）下收益不足，列为远期。

### 1.3 设计原则

1. **检索与生成解耦**：检索器是纯函数式服务，Agent/RAG/未来的 HTTP API 共用同一检索入口；
2. **不信任 LLM**：身份、参数、预算、确认全部在代码层强制，LLM 只负责决策；
3. **一切可评估**：检索、意图、工具选择、端到端答案，每一层都有回归基线；
4. **状态外置**：进程内存只放无状态计算，会话/幂等/索引全部外置到存储层。

---

## 2. 总体架构（目标态）

```
                          ┌─────────────────────────────────────────────────────┐
   前端                    │                  应用层 (FastAPI)                     │
                          │                                                     │
  /ws/baby_assistant ────▶│  WS 网关层：JWT鉴权 · 限流 · 协议适配 · emit注入      │
  /ws/rag_query ─────────▶│                                                     │
                          │        │ ainvoke(config={thread_id, ...})            │
                          │        ▼                                             │
                          │  ┌─────────────────────────────────┐                │
                          │  │   Agent 编排层 (LangGraph)       │                │
                          │  │   全局编译图 + checkpointer      │                │
                          │  │   entry → agent/rag/chitchat    │                │
                          │  │   tools(HITL interrupt)         │                │
                          │  └──────┬──────────────────┬───────┘                │
                          │         │                  │                        │
                          │         ▼                  ▼                        │
                          │  ┌────────────┐      ┌──────────────────┐          │
                          │  │ LLM 网关    │      │ 检索服务 (app/rag)│          │
                          │  │ 多模型路由   │      │ 统一入口 search() │          │
                          │  │ 熔断/降级    │      │ 查询理解→召回→精排│          │
                          │  │ 成本统计    │      └───┬────────┬─────┘          │
                          │  └─────┬──────┘          │        │                │
                          └────────│─────────────────│────────│────────────────┘
                                   │                 │        │
                    ┌──────────────▼───┐   ┌─────────▼──┐  ┌──▼──────────────┐
                    │ DashScope/OpenAI │   │ Embedding   │  │ 向量库 (Qdrant)  │
                    │ (qwen 系,兼容模式)│   │ 服务 (TEI)  │  │ + BM25 索引服务  │
                    └──────────────────┘   └────────────┘  └─────────────────┘
     ┌────────────┐   ┌────────────┐   ┌──────────────┐   ┌──────────────────┐
     │ PostgreSQL  │   │   Redis     │  │ MySQL(业务)   │  │ Langfuse/OTel    │
     │ checkpointer│   │ 幂等/限流/   │  │ 宝宝数据      │  │ trace/指标/日志   │
     │ (会话状态)   │   │ 缓存/pubsub │  └──────────────┘  └──────────────────┘
     └────────────┘   └────────────┘
```

### 2.1 服务拆分决策

| 组件 | 形态 | 理由 |
|---|---|---|
| 应用层（WS/编排/工具） | 单一 FastAPI 服务，uvicorn 多 worker | 业务量级下不必微服务化；无状态化后可水平扩 |
| Embedding | **独立容器**（TEI / 自建 FastAPI+GPU 可选） | 把 torch 从 Web 进程剥离（现状痛点）；可独立扩缩与缓存 |
| 向量库 | Chroma → **Qdrant**（容器部署） | 需要增量 upsert、metadata 过滤、副本；Chroma 单机 SQLite 到顶 |
| Checkpointer 存储 | PostgreSQL | LangGraph 官方 AsyncPostgresSaver，事务性与 interrupt 恢复可靠 |
| Redis | 已有，扩容用途 | 幂等 SETNX、限流、BM25 失效广播（pub/sub）、热点缓存 |
| 离线管道 | 独立脚本/定时任务（不进 Web 进程） | 摄入、打标、评估、重建索引均为批处理 |

---

## 3. Agent 子系统设计

### 3.1 全局编译图 + 运行时上下文注入（替代 per-connection 编图）

**现状问题**：每次 WS 连接 `build_assistant_graph(ws=ws)`，节点闭包捕获连接对象，图无法共享，checkpointer 无法引入（[graph.py L605-660](../app/assistant/graph.py#L605-L660)）。

**目标设计**：图在进程启动时编译一次；连接相关的 `emit` 回调通过 LangGraph `config` 注入，节点内用 helper 取用：

```python
# app/assistant/runtime.py（新增）
from contextvars import ContextVar
_emit_var: ContextVar = ContextVar("emit", default=None)

def get_emit():
    return _emit_var.get() or _noop_emit

# 节点内（替代闭包捕获 ws）：
async def agent_node(state):
    emit = get_emit()
    await emit("tool_call", {...})

# WS 层进入时：
token = _emit_var.set(make_emit(ws))
try:
    result = await graph.ainvoke(state, config)   # 全局共享的 graph
finally:
    _emit_var.reset(token)
```

- `build_assistant_graph()` 改为无参、进程级调用一次（`app/main.py` 启动时）；
- `make_resume_state` 等闭包产物随之退役；
- 收益：编译一次（内存↓）、LLM 实例复用、checkpointer 可用、单测直接调节点。

### 3.2 会话持久化：Checkpointer + 原生 interrupt

**目标设计**（替换 WS 层手工 `history/pending`，[baby_assistant.py L79-170](../app/ws/baby_assistant.py#L79-L170)）：

```python
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import interrupt, Command

checkpointer = AsyncPostgresSaver.from_conn_string(PG_DSN)   # 启动时建一次

graph = workflow.compile(checkpointer=checkpointer)

# agent 节点内 —— 写操作改为原生 interrupt（替代 pending_write + 图 END）:
if write_calls and not state.get("confirmed"):
    decision = interrupt({                       # 图在此暂停，状态落库
        "type": "confirmation",
        "tools": [{...} for c in write_calls],
    })
    if decision["action"] == "reject":
        return {"answer": "好的，已取消本次操作。", "tool_calls": None}
    # approve → 继续（可带用户修改后的参数）

# WS 层 —— 三个入口统一为一种模式:
config = {"configurable": {
    "thread_id": f"baby-{user_id}",              # 跨连接延续记忆
    "emit": ...,
}}
result = await graph.ainvoke(inputs, config)     # 新消息 / Command(resume=...) 同一入口
```

要点：
- `thread_id = baby-{user_id}`：多轮记忆与 HITL 挂起全部由 checkpointer 托管，前端断线重连后 `confirm` 依然有效（进程重启也一样）；
- `confirm_id` 由 interrupt payload 携带，恢复时用 `Command(resume=Decision)`；
- 删除项：WS 层 `history` 列表、`pending` 字典、`make_resume_state()`、`wait_confirm` 出口、`processing` 改为基于 Redis 的 per-thread 锁（多实例下仍需防并发写同一 thread）。

### 3.3 意图路由层：可评估、可配置

**保留两级策略**（规则快路径已被证明有效），但做三项加固：

1. **规则表配置化**：`DATA_QUERY_PATTERNS` 等三张表（[graph.py L164-183](../app/assistant/graph.py#L164-L183)）移到 YAML，启动加载 + Redis pub/sub 热更新；
2. **LLM 分类结构化输出**：`json.loads` 裸解析（[L231](../app/assistant/graph.py#L231)）→ `llm.with_structured_output(IntentResult)`（Pydantic 模型，字段含 intent/confidence/reason）；
3. **意图评估集进 CI**：50+ 条标注 query，意图准确率 < 阈值则发布门禁失败（与 RAG 门禁同一套机制）。

同时引入**路由影子评估**：生产流量下并行记录"规则结果 vs LLM 结果 vs 实际最优分支"（用回答后用户行为近似），为将来削减 LLM 分层调用提供数据。

### 3.4 工具执行层：三层防线

**现状**：`ToolRegistry.execute()` 只做异常包装；参数校验依赖个别工具自觉（仅 add_temperature 有范围检查）。

**目标设计**（[tool_registry.py](../app/assistant/tool_registry.py) 扩展）：

```python
class ToolRegistry:
    def execute(self, name, args, ctx: ToolContext) -> ToolResult:
        meta = self._tools.get(name)
        if meta is None or not meta.enabled:
            return ToolResult.err("tool not found/disabled")
        # 防线1: 执行侧按 JSON Schema 校验（不信任 LLM 传参）
        errs = jsonschema.validate_args(args, meta.parameters)
        if errs:
            return ToolResult.err(f"invalid args: {errs}")   # 错误回灌 LLM 让其自纠
        # 防线2: 身份与租户强制（保留现有设计）
        args["user_id"] = ctx.user_id
        args["request_id"] = ctx.request_id
        # 防线3: 幂等（移除——写操作幂等上移到 Redis 层，见 3.6）
        result = await asyncio.to_thread(meta.handler, **args)
        return ToolResult.from(result)                        # 统一 ok/data/error + 耗时
```

配套改进：
- 工具 handler 返回统一 `ToolResult`（携带 `latency_ms`），喂给 trace 与指标；
- 超时控制：每个工具声明 `timeout_s`（默认 5s），`asyncio.wait_for` 包裹，防单个慢 SQL 卡住 ReAct 轮次；
- 工具执行错误**结构化回灌** LLM（"参数 day 格式错误，应为 YYYY-MM-DD"），让模型自纠重试而非直接失败——这是 ReAct 系统的成熟实践。

### 3.5 ReAct 循环硬约束

```python
def route_after_agent(state) -> Literal["tools", "end", "give_up"]:
    if state.get("tool_calls"):
        if (state.get("tool_rounds") or 0) >= settings.max_tool_rounds:   # 5
            return "give_up"
        return "tools"
    return "end"
```

新增 `give_up` 节点：汇总 `tool_trace` 中已成功的操作告知用户，明确说明未完成部分。同时把"轮数上限"、"单轮 token 预算"纳入 Settings。

### 3.6 LLM 网关（新增模块 `app/assistant/llm_gateway.py`）

把分散三处的 `ChatOpenAI(...)` 硬编码（[graph.py L108](../app/assistant/graph.py#L108)、[rag_query.py L203](../app/ws/rag_query.py#L203)、[voice_agent_langchain.py L104](../app/ws/voice_agent_langchain.py#L104)）收敛为一个网关：

```python
class LLMGateway:
    """所有 LLM 调用的唯一出口: 构造/路由/熔断/降级/计量"""

    def get(self, profile: str) -> BaseChatModel:
        # profile: "agent"(0.3,bind_tools) / "rag"(0) / "intent"(低价快速模型) / "condense"
        # 多模型路由: 主 qwen3.7-plus, 备 qwen-turbo(降级), 意图/改写用小模型省成本

    async def ainvoke(self, profile, msgs, **kw): ...    # 熔断 + 重试(幂等类) + 计量
    def astream(self, profile, msgs, **kw): ...          # call_stream 语义保留
```

- **重试策略**：连接类错误（超时/429）自动重试 1 次（指数退避）；内容类错误不重试直接上报；
- **降级链**：`qwen3.7-plus 失败 → qwen-turbo → 固定文案`（当前只有固定文案一级）；
- **计量**：每次调用记录 `profile/model/prompt_tokens/completion_tokens/latency`，双写 Langfuse 与 Prometheus；
- 熔断器保留现有实现，但改为**按 profile 分桶**（意图小模型挂了不应熔断主对话模型）。

### 3.7 WS 网关层加固

在 [baby_assistant.py](../app/ws/baby_assistant.py) 基础上补齐：

| 项 | 设计 |
|---|---|
| 限流 | Redis 滑动窗口：每 user_id 20 次/分钟、每次 query ≤ 500 字符 |
| 连接治理 | 单用户连接数 ≤ 3；服务端 30s 无任何消息主动断开（当前只被动等断） |
| 心跳 | 保留 ping/pong；pong 缺失 2 次即断开回收资源 |
| 背压 | 事件推送失败计数，连续失败主动断开（防慢消费者堆积内存） |

---

## 4. RAG 子系统设计

### 4.1 统一检索服务（消灭双链路）

**现状**：Agent 图内纯向量（[graph.py L516-520](../app/assistant/graph.py#L516-L520)）与独立端点混合检索并存。

**目标**：`app/rag/` 包成为**唯一检索入口**，对外只暴露一个 API：

```python
# app/rag/service.py（新增，检索服务门面）
class RetrievalService:
    async def search(self, req: RetrievalRequest) -> RetrievalResult: ...
        # 唯一入口; Agent 图内节点、/ws/rag_query、未来 HTTP API 全部走这里

@dataclass
class RetrievalRequest:
    query: str
    top_k: int = 3
    fetch: int = 20
    age_months: float | None = None     # Agent 侧可显式传入（来自 baby_context），
                                        # 未传则走 query 正则抽取（现状逻辑保留）
    history: list[str] | None = None    # 多轮改写用（见 4.4）
    enable_rerank: bool = True

@dataclass
class RetrievalResult:
    hits: list[Hit]          # 命中块（含 score/来源/调试字段）
    expanded: list[Hit]      # 父章节扩展块
    context: str             # 组装好的上下文（预算裁剪后）
    sources: list[Source]    # 引用元数据
    debug: dict              # 各阶段耗时/召回数（进 trace）
```

同时把 `get_chroma_collection()/get_embedding_function()/get_retriever()` 从 [ws/rag_query.py](../app/ws/rag_query.py) **下沉到 `app/rag/`**，消除 `assistant → ws` 的分层倒挂。

### 4.2 Embedding 服务化

**现状**：`text2vec-base-chinese` 在 Web 进程内 CPU 推理（[text2vec_embedding_text2vec.py](../app/scripts/text2vec_embedding_text2vec.py)），拖累事件循环且模型能力到顶。

**目标**：

```
┌─────────────┐  HTTP/gRPC   ┌──────────────────────────────┐
│  应用层      │────────────▶│  Embedding 服务 (TEI 容器)     │
│ rag/agent   │  /embed      │  模型: BAAI/bge-m3            │
└─────────────┘  /embed_all   │  GPU 可选; 内置 LRU 结果缓存   │
                              └──────────────────────────────┘
```

- 模型升级 **bge-m3**（稠密+稀疏一体，长文本，多语）或保守选 `bge-large-zh-v1.5`；query 侧加 bge 指令前缀；
- **EmbeddingFunction 适配器保留接口**（`embed_documents/embed_query`），实现改为 HTTP 客户端 + 本地 LRU 缓存（`hash(text) → vector`），离线摄入与在线检索共用；
- 服务不可用时降级：直接走 BM25 纯关键词检索（可用性优先），并打告警指标；
- **换模型 = 全量重建**：通过 4.5 的版本机制执行，不在线热换。

### 4.3 检索管道 v2

在现有五步流水线（[retriever.py](../app/rag/retriever.py)）基础上插入两级能力：

```
查询理解            召回                    粗排                    精排            组装
┌────────────┐  ┌───────────────────┐  ┌──────────────────┐  ┌──────────────┐  ┌──────────────┐
│ 指代消解/改写│→│ 向量 top-20        │→│ RRF 融合          │→│ bge-reranker │→│ 预算裁剪       │
│ (多轮 condense)│ │ + BM25 top-20    │  │ + 月龄软过滤       │  │ (Cross-     │  │ + 父章节扩展   │
│             │  │ (bge-m3 稠密+稀疏) │  │ + 权威度加权       │  │  Encoder)   │  │ + 去重        │
└────────────┘  └───────────────────┘  │ + 文档多样性       │  └──────────────┘  └──────────────┘
                                        └──────────────────┘
```

- **粗排保留现有 RRF+软过滤实现**（已验证有效），新增第 4.5 步：`bge-reranker-base`（CPU 单条 ~50ms，top-10 精排）；`enable_rerank=False` 或 reranker 超时（200ms 门限）时跳过——精排是**可降级增强**，不是必经路径；
- **预算裁剪**（新增，替代现状无上限拼接）：`system + context + query ≤ 模型窗口 60%`，超限按精排分数从低到高丢块；`expanded` 组装优先级低于 `hits`；
- 所有阶段耗时打点进 `debug`，Langfuse 面板可视化每段延迟。

### 4.4 查询理解（多轮改写）

新增 `app/rag/query_rewriter.py`：

```python
async def condense(history: list[str], query: str) -> str:
    """最近2~3轮 + 当前问题 → 独立完整的检索 query（一次低价 LLM 调用）"""
    # 规则短路: query 无代词/省略特征（那/它/呢/还要/然后呢）→ 原样返回, 零成本
    # LLM: 用网关 "condense" profile（qwen-turbo, temperature=0）
```

接入点：`RetrievalRequest.history` 由 WS 层从 checkpointer 取最近对话传入；Agent 图内 RAG 节点天然有 `state["messages"]`。

### 4.5 知识库生命周期管理（离线管道重构）

**现状**：全量 `shutil.rmtree` 重建，BM25 失效无联动（[load_rag_knowledge.py L340-342](../scripts/load_rag_knowledge.py#L340-L342)）。

**目标设计**：

```
manifest.json（版本台账）                离线管道（定时/手动触发）
┌──────────────────────┐      ┌────────────────────────────────────────┐
│ version: v20260901    │      │ 1. 扫描 data/rag/**/*.md               │
│ embedding: bge-m3     │◀─────│ 2. hash(filepath+content) 对比 manifest │
│ docs: 202             │      │    → 新增/变更/删除 三类清单             │
│ chunks: 651           │      │ 3. 变更文档: LLM 批量打标(topics/ages)  │
│ doc_fingerprints:     │      │ 4. 切分(复用现有结构感知切分, 不动)        │
│   "Weaning.md": a3f.. │      │ 5. Qdrant upsert/delete (按 chunk id)   │
└──────────────────────┘      │ 6. 刷新 BM25 → Redis publish "index_vN" │
                              │ 7. eval_rag 回归 → 达标则发布 manifest   │
                              └────────────────────────────────────────┘
```

- **增量**：指纹对比，只处理变更文档，Qdrant `upsert`/`delete`；
- **版本**：collection 按版本命名（`baby_feeding_vN`），新版本回归通过后原子切换别名，旧版本保留一个周期可回滚；
- **失效联动**：各应用实例订阅 Redis 频道，收到消息后 `retriever.invalidate_index()` 重建 BM25——修复现状"重建后 BM25 与向量库不一致"的隐患；
- **元数据打标升级**：关键词规则（[L17-70](../scripts/load_rag_knowledge.py#L17-L70)）→ LLM 离线批量打标（成本低、离线可重跑），规则结果保留为 fallback。

### 4.6 存储演进

| 存储 | 现状 | 目标 | 迁移要点 |
|---|---|---|---|
| 向量库 | Chroma 单机 SQLite | Qdrant（Docker） | 全量重灌脚本（摄入管道复用）；Qdrant filter 支持 `age_ranges/topics` 硬过滤（现状软过滤可升级为"硬过滤+软加权"混合策略，评估后定） |
| 会话状态 | WS 进程内存 | PostgreSQL (checkpointer) | 现状无需迁移（本来就没存住）；上线即新数据 |
| 幂等 | 连接内存 Dict | Redis `SETNX+EX` | 键公式保留 `sha256(request_id+tool+args)` |
| BM25 索引 | 每进程懒构建 | 保留进程内 + Redis pub/sub 失效联动 | 不引入独立搜索服务（651 chunks 无必要；文档量 >5 万再评估） |

---

## 5. 平台支撑层

### 5.1 可观测性（三支柱）

```
Traces   → Langfuse（自托管）: 每次 ainvoke 一个 trace
             span 树: intent → retrieve → rerank → generate / tool_call 链
             记录: prompt/completion/模型/latency/tokens/成本
Metrics  → Prometheus + Grafana:
             QPS、意图分布、工具成功率、幂等命中率、熔断状态(现有 snapshot())
             TTFT(首字延迟)、检索分段耗时、RAG 零召回率告警
Logs     → loguru（保留）+ request_id 透传，与 trace_id 关联
```

接入方式：Langfuse 的 LangChain callback handler 挂在 `LLMGateway` 与全局图编译参数上，**业务代码零侵入**。

### 5.2 评估与 CI 门禁

| 评估对象 | 工具 | 门禁 |
|---|---|---|
| 检索质量 | eval_rag.py（现有，标注集 12→100+） | HitRate@5 ≥ 0.85，MRR 不回退 |
| 端到端答案 | RAGAS（faithfulness / answer_relevancy） | 抽样 50 条/晚，低于阈值告警 |
| 意图分类 | 标注集（50+ 条） | 准确率 ≥ 0.9 |
| 工具选择 | Agent 回归集：query → 期望工具序列/参数 | 全对才算过 |
| 线上回流 | 用户点踩 → badcase 池 → 人工标注 → 进评估集 | 每周清理 |

落点：`scripts/` 下统一 `make eval` 入口；CI 在向量库版本发布、prompt 变更、模型变更三类事件时强制执行。

### 5.3 安全清单（在优化文档 §1.9 基础上收口为实施项）

1. `confirm_id` 改 uuid4 + 5 分钟 TTL（interrupt 天然支持超时恢复策略）；
2. 输入限长 + 每用户限流（见 3.7）；
3. 工具参数执行侧校验（见 3.4）；
4. 密钥：`.env` 仅开发用，生产走环境注入/密钥管理；删除 [config.py L51](../app/core/config.py#L51) 的 DSN print；
5. SQL 注入面：保留 SQLAlchemy 参数化（现状已安全），禁止拼接；
6. 审计：写操作（add_* 工具）落审计表（user_id/tool/args_hash/confirm 者与时间）。

### 5.4 成本治理

- 意图/改写用 `qwen-turbo` 级小模型（成本 ~1/10）；
- 检索上下文预算裁剪（直接降低 prompt token）；
- Langfuse 成本面板按 `user_id/意图/模型` 维度聚合，异常用户/异常分支告警。

---

## 6. 部署拓扑

```
                    ┌────────────┐
     用户 ────────▶ │  Nginx/网关  │  (TLS, WS 代理)
                    └─────┬──────┘
                          │
              ┌───────────┴───────────┐
              │  kdx-ws-be × 2        │  ← 无状态, 水平扩展
              │  (uvicorn 2 workers)  │
              └───┬─────┬─────┬───────┘
                  │     │     │
     ┌────────────▼─┐ ┌─▼───────▼────────┐ ┌─────────────┐
     │ PostgreSQL    │ │ Redis            │ │ Qdrant      │
     │ (checkpointer)│ │ (幂等/限流/pubsub)│ │ (向量, 副本1)│
     └───────────────┘ └──────────────────┘ └─────────────┘
     ┌───────────────┐ ┌──────────────────┐ ┌──────────────────┐
     │ MySQL(已有)    │ │ TEI embedding    │ │ Langfuse/Prom    │
     └───────────────┘ └──────────────────┘ └──────────────────┘
     离线管道: kdx-ingest (Cron/K8s Job) — 摄入/打标/评估/发布
```

- 应用服务无状态化是扩容前提（§3.1/3.2 完成后才成立）；
- 资源画像：应用 1C2G（不再背 torch）、TEI 可选 GPU；
- 现有 docker-compose（[docker-compose.yml](../docker-compose.yml)）扩展为全组件编排，新增 pg/tei/qdrant/langfuse 服务。

---

## 7. WS 协议 v2（向后兼容）

保留现有事件格式 `{type, data}`（前端已依赖），只增不改：

| 变更 | 内容 |
|---|---|
| 新增 `rate_limited` | `{retry_after}`——替代裸 query_error |
| 新增 `interrupted` | interrupt 触发时推送（兼容现有 `confirmation_request` 字段，前端无感） |
| `wait_confirm` 保留 | 语义不变，但由 interrupt 驱动 |
| `query_done` 增强 | 增加 `usage: {prompt_tokens, completion_tokens}` 与 `latency_ms` |
| 版本协商 | 连接首包 `connected` 携带 `protocol: 2`，旧前端按 v1 处理（新增字段忽略即可） |

---

## 8. 迁移路线（现状 → 目标映射）

| # | 现状组件 | 目标组件 | 迁移方式 | 依赖 |
|---|---|---|---|---|
| M1 | 检索同步阻塞 | 全链路 to_thread | 数行改动 | 无 |
| M2 | ReAct 无上限 | `give_up` 分支 | 数行改动 | 无 |
| M3 | 双 RAG 链路 | RetrievalService 统一 | 中等重构（retriever 下沉 app/rag） | M1 |
| M4 | per-connection 编图 | 全局编译图 + contextvar emit | 中等重构（节点签名改造） | 无 |
| M5 | WS 层记忆/HITL | Checkpointer + interrupt | 较大重构（删 WS 层状态代码） | M4, PostgreSQL |
| M6 | 内存幂等 | Redis SETNX | 小改 | Redis（已有） |
| M7 | 硬编码 LLM | LLMGateway | 小-中改 | 无 |
| M8 | Chroma 单机 | Qdrant + 增量管道 + manifest | 较大（离线管道重写） | TEI(换模型) |
| M9 | 进程内 embedding | TEI 服务 + 缓存适配器 | 中改 | 容器化 |
| M10 | 无精排 | bge-reranker 插槽 | 小改（search() 加一步） | M8 |
| M11 | 无观测 | Langfuse + Prometheus | 小改（callback 接入） | 容器化 |
| M12 | 评估只有检索 | 全层评估 + CI 门禁 | 持续建设 | M3 |

**节奏**：M1/M2/M6/M7（约 1-2 天量级）→ M4/M11 → M3/M5 → M9/M8/M10/M12。每步独立可发布、可回滚（发布开关：RetrievalService 内部保留新旧路径切换参数一周，对比指标后删旧）。

---

## 9. 风险与开放问题

| 风险 | 影响 | 缓解 |
|---|---|---|
| PostgreSQL 成为新单点 | 会话不可用 | 常规主备即可（会话丢失可接受，重建成本低） |
| bge-m3 换模型后检索指标不升反降 | 检索质量 | 版本机制双跑对比，eval 达标才切流 |
| interrupt 与现有前端 confirm 协议偏差 | 前端改造量 | 协议 v2 兼容层：服务端把 interrupt 事件映射为现有 `confirmation_request` 格式 |
| Qdrant 运维成本（自建） | 运维负担 | 先单节点副本1起步；量级证明需要时再上集群 |
| 多轮 condense 引入额外延迟 | 首字延迟 +200-500ms | 规则短路覆盖大多数 query；仅改写 query 走小模型 |

**开放问题（需业务决策）**：
1. 复合请求（"查奶量 + 问喂养建议"）是否需要支持？需要则引入"检索即工具"模式与现有路由并存；
2. 知识库多租户/个性化过滤（按用户可见范围）是否在路线内？影响 Qdrant payload 设计；
3. 写操作确认是否需要"修改参数后确认"（当前 approve/reject 二值）？interrupt 设计已预留 decision payload 扩展位。

---

## 附：目标态目录结构增量

```
app/
├── assistant/
│   ├── runtime.py           # [新] contextvar emit / ToolContext
│   ├── llm_gateway.py       # [新] LLM 网关
│   ├── graph.py             # [改] 无参编译 + interrupt + give_up
│   └── ...（registry/tools/repository 保留增强）
├── rag/
│   ├── service.py           # [新] RetrievalService 门面
│   ├── query_rewriter.py    # [新] 多轮改写
│   ├── embed_client.py      # [新] TEI HTTP 客户端 + LRU 缓存
│   ├── reranker.py          # [新] bge-reranker 封装（可降级）
│   ├── retriever.py         # [保留] 粗排逻辑（RRF/软过滤/多样性/扩展）
│   └── bm25.py              # [保留]
├── obs/
│   ├── tracing.py           # [新] Langfuse/OTel 接入
│   └── metrics.py           # [新] Prometheus 指标
scripts/
├── load_rag_knowledge.py    # [改] 增量化 + manifest + Qdrant
└── eval_rag.py              # [保留] + eval_agent.py [新]
```
