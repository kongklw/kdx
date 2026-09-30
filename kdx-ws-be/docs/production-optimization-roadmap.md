# 生产级 Agent / RAG 优化路线图

> 目标：对照生产级别标准，逐项列出当前实现（见 [agent-rag-implementation.md](./agent-rag-implementation.md)）的差距、风险与改进方案。本文的落地后的目标态整体设计见 [production-architecture-design.md](./production-architecture-design.md)（架构设计草案）。
> 优先级定义：**P0** = 上生产前必须解决（正确性/数据安全）；**P1** = 稳定运行必需（可靠性/可扩展）；**P2** = 体验与长期演进（质量/效率）。

---

## 0. 差距总览

| 维度 | 当前状态 | 生产级要求 | 优先级 |
|---|---|---|---|
| 会话持久化 | 无 checkpointer，记忆存 WS 连接内存 | LangGraph Checkpointer（Postgres/Redis），断线可恢复 | **P0** |
| 幂等 | 单连接内存 Dict | Redis SETNX + TTL，跨进程生效 | **P0** |
| ReAct 循环上限 | `MAX_TOOL_ROUNDS=5` 已定义但**未生效** | 状态机硬上限 + 超限降级 | **P0** |
| HITL 挂起状态 | WS 进程内存变量 | checkpointer/interrupt 持久化，重启不丢 | **P1** |
| 事件循环阻塞 | `rag_query` 检索/推理同步阻塞 | 全链路 `to_thread`/线程池隔离 | **P0** |
| 多实例扩展 | 每连接编译图、BM25 索引进程内 | 全局共享编译图 + 独立检索服务 | P1 |
| LLM 可观测 | loguru 日志 | Langfuse/LangSmith 全链路 trace + 成本统计 | P1 |
| Agent 评估 | 无 | 工具调用准确率/意图分类评估集 + 回归 | P1 |
| Rerank | 无 Cross-Encoder（仅注释提及） | bge-reranker 精排 | P1 |
| 查询改写 | 无（多轮指代无法处理） | query condense / HyDE | P1 |
| RAG 端到端评估 | 仅 12 条检索评估，无答案质量评估 | RAGAS（faithfulness/answer relevance）+ 更大标注集 | P1 |
| 知识库更新 | 全量删库重建，无版本化 | 增量 upsert + 版本管理 + 回滚 | P1 |
| 向量库 | 单机 SQLite Chroma | Milvus/Qdrant/云服务 + 备份 | P2 |
| Embedding | CPU 进程内 text2vec 小模型 | bge-m3 / API 化独立服务 + GPU | P1 |
| 安全加固 | 基本齐备（JWT/身份注入/写确认） | confirm TTL、输入限长、速率限制、密钥管理 | P1 |

---

## 1. Agent 优化项

### 1.1 【P0】接入 LangGraph Checkpointer，实现真正的会话持久化

**现状**：[graph.py L660](../app/assistant/graph.py#L660) `workflow.compile()` 未传 checkpointer；多轮记忆靠 [baby_assistant.py L79-112](../app/ws/baby_assistant.py#L79-L112) 的连接级 `history` 列表手工维护。

**差距与风险**：
- 连接断开 = 记忆清零；多进程/多实例部署时同一用户连到不同 worker 互相看不见历史。
- HITL 的 `pending`（挂起的写操作）也是内存变量，进程重启后用户确认无处恢复。
- 无法使用 LangGraph 原生 `interrupt()` / time-travel（回放、审计某一步的 state）。

**方案**：
```python
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver   # 或 RedisSaver

checkpointer = AsyncPostgresSaver.from_conn_string(PG_DSN)
graph = workflow.compile(checkpointer=checkpointer)

# WS 层不再手工维护 history，改用 thread_id：
config = {"configurable": {"thread_id": f"user-{user_id}"}}
result = await graph.ainvoke(initial_state, config)
# HITL 用原生模式：图内 interrupt() 暂停，恢复用 Command(resume=...)
```
- `thread_id` 用 `user_id`（跨连接延续记忆）或 `user_id + session_id`（按会话隔离）。
- 切换后可删掉 WS 层的 `history/pending` 手工管理逻辑，`make_resume_state()` 一并退役。
- 依赖已有：`langgraph-checkpoint==4.1.1` 已在 requirements 中，只差接入。

### 1.2 【P0】让 ReAct 循环上限真正生效

**现状**：`MAX_TOOL_ROUNDS = 5` 在 [graph.py L81](../app/assistant/graph.py#L81) 定义，`tool_rounds` 也在 [L505](../app/assistant/graph.py#L505) 递增，但 **`route_after_agent`（L409-420）从未检查 `tool_rounds`**。

**风险**：模型异常时（如反复输出无效 tool_calls）理论上是无限循环，烧 token 且用户挂死。

**方案**：
```python
def route_after_agent(state) -> Literal["tools", "wait_confirm", "end", "give_up"]:
    if state.get("pending_write"):
        return "wait_confirm"
    if state.get("tool_calls"):
        if (state.get("tool_rounds") or 0) >= MAX_TOOL_ROUNDS:
            return "give_up"          # 新增兜底节点：告知用户并给出已执行的操作摘要
        return "tools"
    return "end"
```
`give_up` 节点：输出"本轮操作较复杂，已执行 X，请换个说法或稍后再试"，避免用户看到静默失败。

### 1.3 【P0】消除事件循环阻塞

**现状**：[rag_query.py L137](../app/ws/rag_query.py#L137) `retriever.search(query, k=3, fetch=20)` 在 async 节点里**同步调用**——首次查询会触发：全库拉取 + jieba 分词建索引（秒级）+ text2vec CPU 推理，全程阻塞 uvicorn 事件循环，期间**所有连接的所有请求都被卡住**。`generate_node` 的 embedding 也是同步调用。（Agent 图内的 `make_rag_node` 反而用了 `asyncio.to_thread`，是正确示范。）

**方案**：
```python
result = await asyncio.to_thread(retriever.search, query, k=3, fetch=20)
```
- 系统性排查：凡是 CPU/同步 IO（embedding、BM25、SQLAlchemy、模型加载）一律 `to_thread` 或 `run_in_executor`，并考虑用专用线程池限制并发（`loop.run_in_executor(pool, ...)`）防止线程爆炸。

### 1.4 【P0】幂等管理器升级为 Redis

**现状**：[resilience.py L143-176](../app/assistant/resilience.py#L143-L176) `IdempotencyManager` 是单连接内存实现（代码注释自己也写明"生产环境应替换为 Redis SETNX + TTL"）。

**差距**：多 worker / 多实例下完全失效——同一 request_id 打到两个实例会**重复写入**宝宝数据；连接断开重连后幂等缓存也丢失。

**方案**：
```python
# Redis SETNX + TTL 语义
ok = await redis.set(key, result_json, nx=True, ex=1800)
if not ok:
    return await redis.get(key)   # 幂等命中
```
- 项目已配置 Redis（[config.py](../app/core/config.py) 有 redis_url），只差实现。
- 熔断器同理：进程内单例在多实例下各自为政，可后续用 Redis 共享计数（P2，非必需）。

### 1.5 【P1】意图识别强化

**现状**（[graph.py L164-241](../app/assistant/graph.py#L164-L241)）：
- 规则关键词表硬编码，无维护工具；
- LLM 意图 JSON 裸解析（`json.loads`），失败静默降级为 knowledge_qa；
- `confidence` 是 LLM 自报的，不可校准；低置信度直接按 chitchat 兜底，错误路由无感知。

**方案**：
1. LLM 意图输出改用结构化输出（`llm.with_structured_output(Pydantic模型)`），替代字符串截取解析。
2. 建意图分类评估集（几十条真实 query + 标签），把意图准确率纳入回归。
3. 中期：把 `data_query` 类意图直接交给 Agent 自主判断（LLM 看到工具列表自然会选），意图路由只区分"知识问答 vs 其他"，减少路由错误面；或引入小模型（qwen-turbo）做低成本分类。
4. 规则表配置化（YAML/DB），支持热更新，不需要改代码发版。

### 1.6 【P1】可观测性：trace、指标、成本

**现状**：仅 loguru 文本日志（logs/ 目录）+ WS 事件流。requirements 里装了 `opentelemetry-*`、`langsmith` 但**完全未接入**。无 token 用量统计、无每次请求成本、无 P95 延迟、无 LLM 错误率面板。

**方案**：
1. **Langfuse（开源自托管）或 LangSmith** 接入 LangGraph：`ChatOpenAI` 挂 callback handler，自动记录每次 LLM 调用的 prompt/completion/token/延迟/工具轨迹，按 `session_id=user_id`、`trace_id=request_id` 串联。
2. 指标暴露 Prometheus：查询 QPS、意图分布、工具调用成功率、熔断状态（`LLMCircuitBreaker.snapshot()` 已有现成数据）、流式首字延迟（TTFT）。
3. 关键业务埋点：记录每次写操作确认率（approve/reject 比）、幂等命中率。

### 1.7 【P1】Agent 评估体系（当前为 0）

**现状**：RAG 有 [eval_rag.py](../scripts/eval_rag.py)，Agent 链路没有任何评估——意图路由对不对、工具选得对不对、参数抽得对不对，全凭感觉。

**方案**（参考 RAG 评估的模式，建立 Agent 回归集）：
| 评估层 | 方法 | 示例用例 |
|---|---|---|
| 意图分类 | 标注集准确率 | "喝奶了吗"→data_query |
| 工具选择 | 跑图后断言 `tool_trace` 的工具序列 | "记录体温37.5" → [add_temperature] |
| 参数抽取 | 断言工具入参 | milk_volume=80、day=today |
| 端到端 | LLM-as-judge 给回答打分 | 完整 query → answer 质量评分 |
| 幂等/HITL | 集成测试：重复 request_id、reject 流程 | 现有 `app/test/` 扩充 |

### 1.8 【P1】架构性重构：全局共享编译图

**现状**：每次 WS 连接 `build_assistant_graph(ws=ws)` 新建一张图——节点闭包捕获连接对象导致图无法进程级共享，也让 checkpointer 难以引入。

**方案**：节点不再闭包捕获 `ws`，改为通过 **LangGraph 自定义 `config["configurable"]`** 或 contextvar 在运行时传递 emit 回调：
```python
# 节点内: emit = get_current_emit()  (contextvar, WS 层进入时 set)
graph = build_assistant_graph()      # 进程启动时编译一次（带 checkpointer）
# 每次请求: await graph.ainvoke(state, config={thread_id, emit via configurable})
```
收益：编译一次、模型实例复用（`_make_llm` 目前也是每次调用新建）、内存与延迟双降。

### 1.9 【P1】安全加固清单

| 项 | 现状 | 建议 |
|---|---|---|
| confirm 过期 | `confirm_id` 无 TTL，挂起可无限期恢复 | pending 写操作 5 分钟过期；`confirm_id` 改用 uuid4（当前 `CFM-{毫秒}` 可预测，[graph.py L390](../app/assistant/graph.py#L390)） |
| 输入限长 | query 无长度限制 | query ≤ 500 字符，超长拒绝（防 prompt 费用攻击） |
| 速率限制 | 无 | Redis 滑动窗口：每用户 N 次/分钟 |
| 工具参数校验 | 仅 add_temperature 有范围检查 | 执行侧按 JSON Schema 统一校验（pydantic/jsonschema），不只依赖 LLM 自觉 |
| LLM 注入防御 | system prompt 直接拼接宝宝信息 | 对用户输入做基本清洗；工具结果包 ToolMessage（已做，保持） |
| 密钥管理 | `.env` 明文 DASHSCOPE_API_KEY 且 [config.py L51](../app/core/config.py#L51) 把 MySQL DSN 打到 stdout | 生产用密钥管理服务/环境注入；删除 print |
| WS 资源 | 无连接数/单用户连接数限制 | 上限 + 心跳超时踢出（当前只回 pong 不检测死链） |

### 1.10 【P2】体验与其他

- **Agent 节点流式化**：`agent_node` 用 `streaming=False`（[graph.py L373](../app/assistant/graph.py#L373)），带工具的复杂请求用户要干等；可用 `astream_events` 在 tool-call 决策阶段就推送"正在查询…"中间态。
- **voice_agent_langchain.py 定位**：三明治店 demo 混在生产代码库且注册进 main.py，建议移到 `app/example/` 或独立服务，避免维护噪音。
- **模型配置集中化**：`qwen3.7-plus`、base_url、temperature 分散硬编码在 [graph.py](../app/assistant/graph.py)、[rag_query.py L204](../app/ws/rag_query.py#L204)、[voice_agent_langchain.py](../app/ws/voice_agent_langchain.py) 三处，收敛到 Settings 统一管理。
- **降级策略分级**：熔断后目前只有固定文案；可分级——LLM 意图失败→纯规则路由；RAG 生成失败→直接返回 sources 摘要。

---

## 2. RAG 优化项

### 2.1 【P0】统一两条 RAG 路径

**现状**：Agent 图内 `make_rag_node`（[graph.py L516-520](../app/assistant/graph.py#L516-L520)）是**纯向量** `collection.query(n_results=3)`；而独立端点 `/ws/rag_query` 用完整 `HybridRetriever`（混合召回+RRF+月龄过滤+父章节扩展）。同一个"6个月能吃鸡蛋吗"在两个入口得到不同质量的检索。

**方案**：`make_rag_node` 改调 `get_retriever().search()`，删除内联的简化检索；并把 retriever/embedding 的单例获取逻辑从 `ws/rag_query.py` 下沉到 `app/rag/` 包内（当前检索核心模块反向依赖 WS 层，[graph.py L517](../app/assistant/graph.py#L517) `from ..ws.rag_query import ...` 属于分层倒挂）。

### 2.2 【P1】接入 Cross-Encoder 重排

**现状**：精排只有启发式加权（RRF + age_boost + authority），代码注释（[retriever.py L12](../app/rag/retriever.py#L12)）已预留"生产可替换 Cross-Encoder（bge-reranker）"，[scripts/reranker.py](../scripts/reranker.py) 只有 851 字节的雏形。

**方案**：
```
双路召回 top-20 → RRF+过滤（粗排 top-10）→ bge-reranker-base 精排 → top-3
```
- 用 `sentence_transformers.CrossEncoder` 加载 `BAAI/bge-reranker-base`（CPU 可跑，单条 ~50ms，10 条 500ms；有 GPU 换 base/large）。
- 接口保持 `search()` 不变，rerank 作为第 4.5 步插入；用 [eval_rag.py](../scripts/eval_rag.py) A/B 验证 MRR 提升。

### 2.3 【P1】查询改写与多轮上下文

**现状**：每次 query 独立检索，无改写。RAG 端点无会话概念；Agent 端点虽有 history 但 RAG 节点只拿原始 query。用户问"那辅食呢？"（指代前文）会检索出无关结果。

**方案**（按成本递增选一）：
1. **多轮 query condense**：把最近 2~3 轮对话 + 当前问题交给 LLM 改写成独立完整的检索 query（一次廉价 LLM 调用，效果最好）。
2. 规则版：代词/省略检测（"那/它/呢/还要"）触发 condense，其余直通。
3. 进阶：HyDE（假设性回答检索）或 multi-query 扩展，对召回率敏感的场景再做。

### 2.4 【P1】Embedding 升级与服务化

**现状**：`text2vec-base-chinese`（CoSENT，2014 年代风格的平均池化模型）在 **Web 进程内 CPU 推理**。它是当前检索质量的天花板——语义表达能力明显弱于新一代模型；且模型进程内加载，内存 (~400MB) 与推理延迟随并发不可控。

**方案**：
1. 模型升级：`BAAI/bge-large-zh-v1.5` 或 `bge-m3`（多语/长文本/稠密+稀疏一体），配合 bge 模型的 query 指令前缀。**注意：换 embedding 模型必须全量重建向量库，且 embedding 函数名/维度要与 collection 绑定校验**。
2. 服务化：embedding 独立为 FastAPI 微服务（或 TEI - text-embeddings-inference 容器），主服务 HTTP/gRPC 调用，GPU 可选。收益：Web 进程不再背 torch，滚动发布不受模型加载影响，embedding 可缓存复用。

### 2.5 【P1】知识库增量更新与版本管理

**现状**：重建 = `shutil.rmtree` 删库全量重灌（[load_rag_knowledge.py L340-342](../scripts/load_rag_knowledge.py#L340-L342)）；BM25 索引的 `invalidate_index()` 存在但**无人调用**——重建后存量进程的 BM25 索引与新向量库不一致（文档已删但 BM25 还能召回）。

**方案**：
1. 增量：以 `filepath + mtime/hash` 为指纹，新增/变更文档 `upsert`、消失文档 `delete(where={"filepath": ...})`。
2. 版本：collection 按版本命名（`baby_feeding_v20260830`），双写+切流+回滚；或至少保留 `db_summary.json` 之外的 manifest（文档清单+hash）。
3. 失效联动：重建/增量完成后向各进程广播 invalidate（Redis pub/sub），BM25 索引同步刷新。
4. 元数据抽取升级：topics/age_ranges 目前靠关键词规则（[load_rag_knowledge.py L17-70](../scripts/load_rag_knowledge.py#L17-L70)），可用 LLM 离线批量打标提升准确率（离线任务，成本可忽略）。

### 2.6 【P1】RAG 端到端评估与监控

**现状**：[eval_rag.py](../scripts/eval_rag.py) 只评**检索**（HitRate/MRR），且标注集仅 12 条；答案质量（忠实性、相关性、引用正确性）无评估。线上无检索质量监控。

**方案**：
1. 标注集扩到 100+ 条（按 13 主题 × 4 月龄段覆盖），建立 badcase 回流机制（用户点踩 → 入标注池）。
2. 端到端评估引入 **RAGAS**：`faithfulness`（答案是否忠于检索内容）、`answer_relevancy`、`context_precision/recall`，用 LLM-as-judge 定期跑。
3. 引用校验：模型输出的 `[文档N]` 标注与实际 sources 比对，引用错乱率作为监控指标。
4. 线上指标：检索耗时分布、平均 score、零召回率（`fused_n=0`）告警——零召回往往意味着索引挂了。

### 2.7 【P2】向量库与基础设施演进

- **Chroma 单机 → 独立部署**：SQLite 存储无并发写保护、无高可用。中期迁 Qdrant/Milvus（支持 metadata where 过滤、增量 upsert、副本），或 Chroma Server 模式（HTTP，仍是单机但至少解耦存储）。
- **prompt 长度预算**：上下文拼装无总 token 上限（父章节扩展有 600 token，但 3 个命中块本身无上限）。加预算控制器：system + context + query ≤ 模型窗口的 60%，超限按 score 截断低分块。
- **缓存层**：高频育儿问题（"辅食什么时候加"）——query embedding 结果 + 检索结果缓存（Redis，TTL 1h，语义缓存可后期）。
- **切分参数自适应**：500/50 全局统一；可用评估集对 chunk_size 网格搜索（300/500/800 × overlap 0/50/100），不同文档类型（指南类 vs 百科类）可不同参数。

---

## 3. 建议落地顺序（四阶段）

```
阶段一（正确性止血，改动小收益大）
  ├─ 1.2 ReAct 循环上限生效          —— 几行代码
  ├─ 1.3 事件循环阻塞消除(to_thread)  —— 几行代码
  └─ 2.1 统一两条 RAG 路径           —— 小重构

阶段二（生产化底座）
  ├─ 1.1 Checkpointer + 原生 interrupt（连带重构 1.8 共享图）
  ├─ 1.4 Redis 幂等
  ├─ 1.6 Langfuse/Prometheus 可观测
  └─ 1.9 安全加固清单

阶段三（检索质量）
  ├─ 2.2 bge-reranker 精排
  ├─ 2.3 查询改写
  ├─ 2.5 增量更新 + invalidate 联动
  └─ 2.6 RAGAS 端到端评估 + 标注集扩充

阶段四（规模化）
  ├─ 2.4 Embedding 升级 bge-m3 + 服务化
  ├─ 2.7 向量库独立部署
  └─ 1.7 Agent 评估体系完善 + CI 门禁
```

**验收标准建议**：每个阶段用现有 [eval_rag.py](../scripts/eval_rag.py)（检索）+ 阶段三建立的 Agent 回归集 + Langfuse 面板（延迟/错误率/成本）做前后对照，指标不回退才算完成。

---

## 4. 明确可以保留不动的部分

当前实现里这些设计已达生产水准，重构时**不要推翻**：

1. **工具层身份注入**（user_id 强制覆盖，不信任 LLM 传参，[graph.py L455-457](../app/assistant/graph.py#L455-L457)）——正确的安全模型。
2. **写操作 HITL 确认**的产品逻辑（含 reject 不重进图、confirm_id 校验）——换 checkpointer 实现时保留交互协议。
3. **RRF 排名融合**（而非分数融合）——免调参、稳健，业界标准做法。
4. **结构感知切分**（表格不拆、句子不断、父章节路径）——超出多数 demo 水准，评估验证后再调参。
5. **月龄软过滤而非硬过滤**（元数据缺失优雅降级）——正确的容错姿势。
6. **检索评估先行**（eval_rag 的 CI 门禁思路）——所有优化都应在这个框架下验证。
