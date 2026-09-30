# Agent / RAG 深度解析（专题补充）

> 本文是两份主文档的**深度补充**，收录三轮专题解析：
> - **Part A**：RAG 核心流程深度解析（结构感知切分 / 混合检索 / 流式生成）
> - **Part B**：Agent 框架选型、实现逻辑及与 RAG 的交互流程
>
> 配套阅读：[agent-rag-implementation.md](./agent-rag-implementation.md)（全链路说明）、[production-optimization-roadmap.md](./production-optimization-roadmap.md)（生产级差距）。
> 所有结论对应真实代码，附文件与行号引用。

---

# Part A：RAG 核心流程深度解析

这三块正好构成 RAG 的"**离线入库 → 在线检索 → 生成输出**"三段链路。

```
【离线】源文档(.md) → 结构感知切分 → text2vec 向量化 → ChromaDB (651 chunks)
【在线】query → 混合检索(向量+BM25) → 精排 → 父章节扩展 → 流式生成
```

## A1. 结构感知切分（离线入库）

位置：[load_rag_knowledge.py](../scripts/load_rag_knowledge.py) 的 `split_document_by_section()`。

核心思想：**不是按固定字数盲切，而是先解析 markdown 结构，再按"原子单元"打包**。三个不变量：表格永不跨块、句子永不被切断、不跨标题语义边界。

### 阶段 1：解析原子单元（`_parse_units`，L95-140）

逐行扫描 markdown，产出三类原子单元 `(标题路径, 类型, 文本)`：

```
# 疫苗接种指南            ← 标题入"标题栈"
## 流感疫苗              ← 栈变成 [疫苗接种指南, 流感疫苗]
    段落文字...           → ("疫苗接种指南 > 流感疫苗", "para", ...)
    | 疫苗 | 剂次 |       ← 连续 | 行聚合成一个表格原子块
    | 脊灰 | 4 |          → (同上路径, "table", 整张表)
```

关键机制是**标题栈**：遇到 `#` 标题就把栈弹到同级再压栈，因此每个块携带完整多级路径（如 `疫苗接种 > 流感疫苗 > 注意事项`）。这条路径最后写进元数据 `section`，其父路径写进 `parent_section`——这是后面"父章节扩展"能回溯邻居块的前提。

### 阶段 2：短节合并（L211-222）

标题开启新章节组，估算组内 token，小于 `MIN_CHUNK_TOKENS = 80` 的碎节**向前并入上一组**。目的：防止"3 个字的补充说明"被切成碎块、然后又被质量过滤（`min_length=100` 字符）丢掉，导致该段知识彻底检索不到。

### 阶段 3：组内打包 + overlap 回取（L224-244）

```
超长封口流程:
  buf 累计原子单元, blen 累计 token
  ├── 新单元放得下（blen+tl ≤ 500）→ 直接放入
  ├── 放不下 → 封口: 当前 buf 成块
  │            然后 _tail_overlap() 从块【尾部】回取完整原子单元
  │            作为下一块的开头（overlap 预算 ≤50 token 且 ≤半块）
  └── 单个单元自己就 >500 → _hard_split() 句子级硬切兜底（按。！？断句，同样带 overlap）
```

`_tail_overlap` 的讲究在于回取的是**完整单元**而不是字符串切片——不会出现"半句话"或"半张表"作为下一块开头；且遇到 heading 立即停止回取，保证不把上一节的标题混进下一节。

### 支撑细节

- **token 估算**（`_est_tokens`，L81-92）：CJK 字符 1 字 ≈ 1 token，其他 4 字符 ≈ 1 token。不用 tiktoken 是因为要联网下词表，且对中文 embedding 场景这个近似误差 <15% 已够用。
- **参数**：`chunk_size=500`（近似 token）/ `chunk_overlap=50`，全局统一（优化文档里提到这是可调优项）。
- **质量过滤与去重**：`len(content) >= 100` 字符 + 内容 hash 去重。
- 最终每块落库的 id 是 `{filename}_{chunk_index}`，`chunk_index` 让检索层能找到"物理相邻块"。

## A2. 混合检索（在线查询）

位置：[retriever.py](../app/rag/retriever.py) 的 `HybridRetriever.search()`，五步流水线。

```
query ──┬─▶ 向量路: embed_query → Chroma cosine top-20 ─┐
        └─▶ 关键词路: jieba分词 → BM25 top-20 ──────────┤
                                                        ▼ RRF 融合
                                              月龄软过滤 + 权威度加权
                                                        ▼
                                              文档级多样性 top-3
                                                        ▼
                                              父章节扩展 → 上下文
```

### 为什么两路混合

单路各有盲区：
- **向量**（语义）：搜"小儿麻痹预防"能召回讲"脊灰疫苗"的内容（同义改写强），但搜疫苗**专有名**"脊灰"反而可能漏——短专名在语义空间里区分度不高；
- **BM25**（字面）：精确命中"脊灰"这类硬关键词，但用户换个说法就失效。

### BM25 路的实现（[bm25.py](../app/rag/bm25.py)）

手写 BM25Okapi（零新依赖）：`k1=1.5` 控制词频饱和（一个词出现 3 次和 30 次差距不大）、`b=0.75` 控制长文档惩罚。分词用 `jieba.cut_for_search`（搜索引擎模式，粒度更细）。索引**懒构建**：进程首次查询时把 Chroma 全库拉到内存分词建倒排（651 chunks 秒级），之后常驻。

### RRF 融合（L145-157）——设计上最聪明的一步

```python
d['rrf'] += 1.0 / (self.rrf_k + rank + 1)   # rrf_k=60，对每一路的排名求和
```

融合的是**排名**而不是分数。这一步很关键：向量 cosine 分数（0~1 量级）和 BM25 分数（可以到几十）量纲完全不同，直接加权需要先做归一化且很敏感。RRF 只看"你在这路排第几名"：排名越靠前贡献越大，`k=60` 压平了头部差距避免单路霸榜。**双路都命中的文档自然分数最高**——这是免调参、稳健的业界标准做法。

### 月龄软过滤 + 权威度加权（L159-173）

```python
final_score = rrf归一化 + age_boost项 + 0.1 × (authority/5 - 0.5)
```

- **月龄**：正则从 query 抽月龄（`6个月`→6.0、`1岁`→12.0），与块元数据 `age_ranges` 比对（±3 个月容差）。命中 `+0.15`，明确不匹配 `-0.075`，**元数据缺失或 query 无月龄 → 0（不加分不降权）**——是"软过滤"，宁可排序打折也不丢结果，这是容错设计。
- **权威度**：入库时按来源目录打的静态分（WHO/CDC/卫健委=5，综合知识=3），让"6个月能不能吃蜂蜜"这类有分歧的问题优先返回权威机构的说法。

### 文档级多样性（L177-188）

top-3 名额里，**同一篇文档只允许占一个名额**（按 id 前缀 `filename_` 判定）。否则一篇长文档的 chunk_3/chunk_5/chunk_7 会挤占全部名额，其他文档的观点完全进不了上下文。被挤掉的同文档邻居块，下一步会以"补充"身份回来。

### 父章节扩展 small-to-big（L200-230）

解决"检索粒度 vs 上下文完整性"的矛盾：
- **检索用小块**（500 token）：块越聚焦，embedding 越精准；
- **返回用大块**：命中块沿 `chunk_index ± 1` 找**同 `parent_section`** 的相邻块，标注 `rel='parent'`（"补充"），预算 `max_expand_tokens=600`。

即：最终给 LLM 的上下文 = 3 个精准命中块 + 若干同章节补充块，前提必须同父章节（防止拼来不相关段落）。

## A3. 流式生成流程（生成输出）

位置：[rag_query.py](../app/ws/rag_query.py) 的 `generate_node`（RAG 图第三节点），以及 Agent 图内的 `rag_node`/`chitchat_node`（模式相同）。

### 机制

检索完成后上下文已定，`generate_node`（L186-229）构造 LLM 时开启流式：

```python
model = ChatOpenAI(model='qwen3.7-plus', temperature=0, streaming=True)

full_answer = ""
async for chunk in model.astream([HumanMessage(content=prompt)]):
    if chunk.content:                       # AIMessageChunk，逐 token 到达
        full_answer += chunk.content
        await send_ws_event(ws, "generate_chunk", {
            "chunk": chunk.content,          # 增量片段
            "total_length": len(full_answer) # 已累计长度（前端可做进度）
        })

await send_ws_event(ws, "generate_done", {"answer": full_answer, "sources": state["sources"]})
```

要点：
1. **`astream` 是异步生成器**：OpenAI 兼容接口的 SSE 流被 langchain 包装成逐个 `AIMessageChunk`，每到一个 token 就 `await` 推一次 WS 事件——**用户在首 token 到达时就开始看到文字**，不用等完整回答。
2. **服务端同时拼完整答案**：`full_answer` 在循环里累计，结束时随 `generate_done` 一次性下发，前端用它做最终渲染/落库，chunk 只用于过程展示。
3. **引用来源与正文分离**：`sources`（title/filename/category）在检索节点就产出，随 `generate_done` 一起返回；prompt 里要求模型标注 `[文档1]`，前端据此把引用角标和来源卡片关联。（"模型标注是否真实对应"没有校验，这是优化文档里的 P1 监控项。）

### 熔断器包裹流式调用（Agent 侧）

Agent 图内的 RAG/闲聊节点多了一层保护（[graph.py L553-557](../app/assistant/graph.py#L553-L557)）：

```python
async for chunk in get_llm_breaker().call_stream(llm.astream, msgs):
    ...
```

`call_stream`（[resilience.py L122-140](../app/assistant/resilience.py#L122-L140)）特殊之处：流式调用"成功"要等**完整迭代走完**才算——中途断流也算失败并计入熔断器；熔断打开时直接抛 `CircuitOpenError`，节点捕获后输出降级文案"【系统降级】AI 服务暂时不可用"。而独立 RAG 端点的 `generate_node` 没包熔断，LLM 挂了直接走 `query_error`，这是两条路径的又一个差异点。

### 完整事件时间线

```
query_start
→ retrieve_start → retrieve_done   (混合检索，块级耗时)
→ rerank_done                      (父章节扩展，上下文字符数)
→ generate_start
→ generate_chunk × N               (逐 token，首字延迟 ≈ 检索耗时 + LLM TTFT)
→ generate_done {answer, sources}  (完整答案 + 引用)
→ query_done
```

一个值得注意的对比：**数据 Agent 的 `agent_node` 是 `streaming=False`**（[graph.py L373](../app/assistant/graph.py#L373)）——因为带工具调用的请求需要拿到完整的 `tool_calls` 结构才能继续执行，只有"最终总结/闲聊/RAG"这些纯文本输出才走流式。

---

# Part B：Agent 框架选型、实现逻辑及与 RAG 的交互流程

## B1. 框架选型：为什么是 LangGraph

### 1.1 选型结果

| 层 | 选型 | 版本 |
|---|---|---|
| Agent 编排 | **LangGraph `StateGraph`（手工建模）** | 1.2.9 |
| 消息/工具抽象 | langchain-core（`AIMessage/ToolMessage` 等） | 1.4.9 |
| LLM 接入 | langchain-openai 的 `ChatOpenAI` | 1.3.5 |
| 模型 | 通义千问 `qwen3.7-plus`，DashScope OpenAI 兼容模式 | - |

### 1.2 为什么不选其他方案

- **裸 OpenAI SDK + 手写 while 循环**：Function Calling 循环、状态管理、分支路由全要自己维护，逻辑散落在代码里；LangGraph 把这些变成**显式的状态图**——节点、边、条件路由都是声明式的，图的形状一眼可读（[graph.py 顶部 L6-25 的 ASCII 图](../app/assistant/graph.py#L6-L25)）。
- **LangChain `AgentExecutor` / 预置 `create_react_agent`**：黑盒程度高，无法插入"写操作先人工确认再执行"这类自定义控制流。本项目的核心需求恰恰是 **HITL（写操作暂停等确认）**，必须自己控制状态机的每一条边。
- **选 LangGraph 的直接收益**：条件边（`add_conditional_edges`）天然支持意图路由；`TypedDict` 状态在节点间自动合并，工具轨迹、挂起状态都有明确落点；将来接 `checkpointer`/`interrupt` 只需改编译参数，图结构不动。

项目里其实**两种风格都有**：主 Agent（`/ws/baby_assistant`）是手工 `StateGraph`（生产链路），而语音 demo（[voice_agent_langchain.py L115-143](../app/ws/voice_agent_langchain.py#L115-L143)）用预置 `create_react_agent` + `InMemorySaver`——它没有自定义控制流需求，预置模板就够了。这个对比本身说明了选型逻辑：**需要自定义控制流选手工建模，纯 ReAct 循环用预置件**。

### 1.3 两个工程决策

1. **LLM 走 OpenAI 兼容协议**：`ChatOpenAI(base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")`（[graph.py L108-119](../app/assistant/graph.py#L108-L119)）。好处是厂商无关——换 DeepSeek/GPT 只改环境变量，`bind_tools`、流式等能力全部沿用。
2. **懒加载**：`_init_lc()` 首次调用才 import LangChain（[graph.py L54-76](../app/assistant/graph.py#L54-L76)）。因为 langchain 生态会连带拉起 torch 等重依赖，懒加载保证非 AI 路由（如 `/health`）的导入期不被拖慢。

## B2. 实现逻辑：状态机怎么跑

### 2.1 全景图

```
START → entry ──┬─ route_entry(条件边)
                ├── "agent"      数据查询/记录（ReAct + 工具 + HITL）
                ├── "rag"        知识问答（检索+生成）
                ├── "chitchat"   闲聊
                └── "fallback"   兜底
agent → route_after_agent(条件边)
                ├── "tools"        有工具要执行 → 回 agent（ReAct 循环）
                ├── "wait_confirm" 有写操作待确认 → END 暂停
                └── "end"          agent 已直接回答 → END
```

每次 WS 连接编译一张图（[baby_assistant.py L77](../app/ws/baby_assistant.py#L77)），节点用**同步工厂函数 + async 闭包**实现——工厂捕获该连接的 `ws`（事件推送）和 `idem`（幂等器），闭包内才是 async 节点逻辑。这是项目的基础模式：`make_entry_node`/`make_agent_node`/`make_tool_exec_node` 全部如此。

### 2.2 entry 节点：两级意图识别（L261-299）

1. **第一级规则**（`_rule_intent`）：三张关键词表 + 两条正则，零延迟零成本覆盖高频意图——命中"奶量/体温/睡眠…"→ `data_query(0.9)`；"怎么/为什么/能不能…"→ `knowledge_qa(0.85)`；`记录|记一下` 或 `数字+单位` → `data_query`。
2. **第二级 LLM 兜底**（`_llm_intent`）：规则未命中才调 LLM 做 few-shot 分类，要求输出 `{"intent":..., "confidence":...}` JSON。
3. **置信度闸门**：confidence < 0.6 一律按 `chitchat` 兜底；LLM 意图调用被熔断器包住，熔断时降级为 `knowledge_qa`。

同时加载 `baby_context`（查 MySQL 拼出"今天是 X，宝宝月龄 N 个月"）——这是所有后续 prompt 的公共上下文。

**设计逻辑**：大多数育儿数据请求是"记录喂奶 80ml"这类高频模式，规则层就消化掉了，不花 LLM 调用；只有长尾表达才进 LLM 分层，成本和延迟同时可控。

### 2.3 agent 节点：Function Calling 决策（L345-406）

```python
msgs = [SystemMessage(system)] + messages + [HumanMessage(query)]
llm  = _make_llm(bind_tools_schemas=registry.get_schemas_for_llm())
resp = await get_llm_breaker().call(llm.ainvoke, msgs)
```

三个出口：
- **无 tool_calls** → 直接回答（内容推 `generate_chunk` 流给前端）；
- **含写操作且未确认** → 构造 `pending_write`，推 `confirmation_request`，条件边送 `wait_confirm → END` 暂停；
- **读操作** → 返回 `tool_calls`，送 `tools` 节点执行。

### 2.4 工具系统：注册中心模式（对比 @tool 装饰器）

主 Agent **不用** `@tool` 装饰器，而是自建 [ToolRegistry](../app/assistant/tool_registry.py)：

```python
@dataclass
class ToolMeta:
    name: str; description: str
    parameters: Dict[str, Any]              # 手写 JSON Schema
    handler: Callable                       # 同步函数
    is_write: bool = False                  # ← 关键：写标记驱动 HITL
```

理由：框架需要按 `is_write` **区分读写操作**来触发人工确认，这是 `@tool` 的纯描述式注册给不了的元数据维度。16 个工具（8 读 8 写）在 [tools.py](../app/assistant/tools.py) 注册，schema 手写便于精确控制参数描述。

`tool_exec_node`（L434-506）的执行逻辑体现三个安全设计：

```python
args["user_id"] = user_id                    # ① 身份强制注入，不信任 LLM 传参
idem_key = idem.tool_key(request_id, name, args)  # ② 写操作幂等（SHA256 键）
result = await asyncio.to_thread(registry.execute, name, args)  # ③ 同步DB放线程池
```

执行完把结果包成 `ToolMessage` 追加回 messages、`tool_rounds+1`，条件边 `tools → agent` 回到 LLM 总结——**这就是 ReAct 循环**：推理 → 调工具 → 观察 → 再推理，直到 LLM 不再要工具、输出最终中文回答。

### 2.5 HITL：跨图与 WS 层的状态接力

LangGraph 的 `wait_confirm` 出口连 `END`——写操作确认是"图结束 + WS 层保存挂起状态"实现的（[baby_assistant.py L134-170](../app/ws/baby_assistant.py#L134-L170)）：

```
agent 决策写操作 → 推 confirmation_request → 图 END（pending 存在 WS 层）
用户 approve → make_resume_state() 构造 {resume:true, confirmed_call:待执行工具}
            → 重新 graph.ainvoke() → entry 检测 resume 直通 tools → 执行 → agent 总结
用户 reject → 不重进图，直接回复"已取消"（防 Agent 再次发起写循环）
```

### 2.6 容错层

- **熔断器**（[resilience.py](../app/assistant/resilience.py)）：三态机包住所有 LLM 调用（失败率 ≥60% 且样本 ≥4 → Open 30 秒 → Half-Open 试探），熔断期间各节点输出固定降级文案，**LLM 故障不会拖垮整个服务**。
- **幂等器**：`request_id + tool + args` 做键，前端重试/双击不会重复写库。
- **连接级并发锁**：`processing` 布尔量，处理中新请求直接回 `busy`。

### 2.7 多轮记忆

无 checkpointer，WS 层手工维护：每轮结束追加 `HumanMessage(query) + AIMessage(answer)`，截断到 20 条，下一轮通过 `state["messages"]` 进图。跨轮记忆只保留"问-答"对（工具调用中间过程不保留）。

## B3. 与 RAG 的交互流程

### 3.1 交互方式：不是工具调用，是专职节点

关键设计决策：**RAG 不是 Agent 的一个 tool**，而是一条**独立路由分支**。意图识别为 `knowledge_qa` 时，`route_after_intent` 直接把请求送进图内的 `rag` 节点（[make_rag_node，L513-565](../app/assistant/graph.py#L513-L565)）。

对比另一种常见设计（把 `knowledge_base_search` 注册成一个 tool，让 LLM 自己决定何时检索）：本项目选择显式路由，好处是**确定性强**——知识问答 100% 走 RAG 流程、事件协议固定（`retrieve_start/done` 前端能渲染检索过程），不依赖 LLM 的调用决策；代价是路由错了就全错（意图识别准确率成为上限），且 RAG 与工具链无法在单轮内组合（比如"查一下宝宝今天奶量，再告诉我该喂多少"这种复合请求会被拆到 data_query 分支）。

### 3.2 图内 rag 节点的执行流程

```python
# ① 复用 RAG 端点的基础设施（Chroma collection + embedding 单例）
from ..ws.rag_query import get_chroma_collection, get_embedding_function

# ② 纯向量检索（注意：简化版，没走 HybridRetriever）
results = await asyncio.to_thread(_retrieve, query)   # collection.query(n_results=3)

# ③ 拼上下文 + 注入宝宝上下文
system = SystemMessage(
    "你是专业的育儿知识助手。根据知识库内容回答问题。\n"
    "1. 优先使用知识库信息; 没有则明确说明\n..."
    f"{state.get('baby_context', '')}\n"          # ← Agent 侧独有：月龄上下文
    f"知识库内容:\n{context}"
)

# ④ 流式生成（带熔断保护）
async for chunk in get_llm_breaker().call_stream(llm.astream, [system, human]):
    await emit("generate_chunk", {"chunk": chunk.content})

await emit("answer_done", {"answer": full, "sources": sources})
```

交互发生在这几个接触点：
1. **基础设施复用**：直接 import `ws/rag_query.py` 的 `get_chroma_collection()` / `get_embedding_function()`（进程级单例）；
2. **上下文融合**：RAG prompt 里注入了 Agent 图 entry 节点查出的 `baby_context`（宝宝月龄），所以回答能带上"你家宝宝 8 个月，可以…"这种个性化表述——这是独立 RAG 端点做不到的；
3. **事件协议统一**：`retrieve_start/done → generate_chunk → answer_done` 与 Agent 其他分支共用同一套 WS 事件格式。

### 3.3 与独立 RAG 端点的关系（重要差异）

系统里实际存在**两条 RAG 链路**：

| | Agent 图内 `rag` 节点 | 独立端点 `/ws/rag_query` |
|---|---|---|
| 检索 | **纯向量** top-3 | **混合检索**（向量+BM25 RRF+月龄过滤+父章节扩展） |
| 熔断 | 有（`call_stream` 包裹） | 无 |
| 个性化 | 注入宝宝月龄上下文 | 无会话/上下文 |
| 定位 | 对话入口的知识问答 | 专用知识库查询页 |

两者共享同一个 Chroma collection（`baby_feeding`）和 embedding 函数，但检索质量不对等——Agent 入口用的是简化版检索。这是优化文档 §2.1 列的 P0 项：让 `make_rag_node` 改调 `get_retriever().search()` 统一到混合检索，同时把 retriever 单例从 `ws/` 层下沉到 `app/rag/` 包（消除目前 `assistant` 反向依赖 `ws` 的分层倒挂）。

### 3.4 端到端时序（Agent 内的 RAG 请求）

```
用户: "6个月能吃鸡蛋吗"
① WS query → query_start
② entry: 查宝宝上下文（月龄6个月）→ 规则命中"能不能吃" → knowledge_qa(0.85)
③ route_after_intent → rag 节点
④ 纯向量检索 Chroma top-3（to_thread）→ 推 retrieve_done {sources}
⑤ 拼prompt（育儿助手角色 + 月龄上下文 + 知识库内容）
⑥ qwen 流式生成 → generate_chunk × N（前端逐字渲染）
⑦ answer_done {answer, sources} → 图 END → WS 层记入 history → query_done
```

### 3.5 一句话总结

**框架选型**上用 LangGraph 手工建模换取对控制流的完全掌控（HITL 是硬需求）；**实现逻辑**上是"意图分层消解成本 + ReAct 循环执行工具 + 状态机管理暂停恢复"三件事；**与 RAG 的交互**上选择了"意图路由到专职节点"而非"检索即工具"，用确定性换取灵活性，代价是双链路不一致——这也是当前最值得先修的一处（见优化文档 §2.1）。
