# 生产级 Agent 系统类型全景与工程目录结构

> 定位：**概念扫盲 + 选型决策 + 落地目录规范**。回答三个问题：
> 1. Agent 系统到底有哪些类型？
> 2. 哪些适合生产？2026 年最流行的是哪一种？
> 3. 选定类型后，代码目录应该怎么组织？
>
> 配套阅读：本项目架构设计 [production-architecture-design.md](./production-architecture-design.md)、RAG 实现 [agent-rag-implementation.md](./agent-rag-implementation.md)。

---

## 0. 一句话结论（TL;DR）

- **2026 年生产环境最流行的 Agent 形态：以"显式状态图（State Graph / 状态机）"为编排内核的单 Agent + 确定性工作流混合架构**，代表框架是 **LangGraph**（Klarna、LinkedIn、Uber、Replit 等在生产使用，1.0 后 API 稳定，被视为生产事实标准）。
- **真正在生产上跑量大头的不是"多 Agent"，而是"工作流 + 工具调用循环"**。Anthropic《Building Effective Agents》的核心建议至今成立：**能用确定性工作流解决的，不要交给自主 Agent；能用单 Agent 的，不要上多 Agent**。
- 需要多 Agent 时，生产上几乎只采用 **Supervisor（主管/层级式）** 拓扑；Agent 之间自由对话的 **Network（网状/Swarm）** 拓扑因不可控、token 成本高、难调试，基本停留在 demo 阶段。
- 框架选型按层区分：**Runtime 层 LangGraph**（可控、可持久化）、**SDK 层 OpenAI Agents SDK**（轻量 handoff）、**角色编排层 CrewAI**（快速原型）、**平台层 Dify/Coze**（低代码）。AutoGen 已进入维护模式，微软统一到 **Microsoft Agent Framework 1.0**（2026-04 发布，原生 MCP/A2A）。

---

## 1. 先厘清概念：Workflow ≠ Agent

很多讨论把两者混为一谈。区分标准是 **"循环与决策权在谁手里"**：

| 维度 | Workflow（工作流） | Agent（智能体） |
|---|---|---|
| 控制流 | 开发者**预先写死**（DAG / 状态机，路径固定） | LLM 在运行时**自主决定**下一步做什么 |
| 循环 | 通常无循环，或固定次数 | 核心就是 `思考 → 行动 → 观察` 循环，直到完成 |
| 可预测性 | 高，每一步可枚举、可测试 | 低，路径由模型动态生成 |
| 成本/延迟 | 低、稳定 | 高，且方差大 |
| 失败模式 | 显式、可复现 | 隐式（死循环、工具误用、跑题） |
| 适用 | 流程稳定、SLA 严格的业务 | 任务开放式、步骤无法预先穷举 |

**工程口诀：Workflow 是"流程图里调 LLM"，Agent 是"LLM 自己画流程图"。**

生产实践中两者不是对立关系，而是**嵌套混合**：外层用确定性工作流把关（鉴权、路由、审批、兜底），在需要开放决策的节点内嵌一个 Agent 循环。本项目 `entry → agent / rag / chitchat` 的意图路由 + LangGraph 工具循环就是这种混合形态。

---

## 2. Agent 系统类型全景

按"编排范式"分三大类，外加两个垂直特化形态：

```
                    Agent 系统类型
                         │
        ┌────────────────┼────────────────────┐
        ▼                ▼                    ▼
  ① 确定性工作流      ② 单 Agent           ③ 多 Agent
  (LLM 是组件)       (一个决策循环)        (多个专业化 Agent)
        │                │                    │
  · Prompt 链       · ReAct/工具调用循环   · Supervisor 层级式 ★生产主流
  · 路由分发         · Plan-and-Execute   · Network 网状/Swarm
  · 并行编排         · Reflection 自省     · 角色协作 Crew
  · Orchestrator-   · 状态机型(FSM图) ★   · 黑板/事件驱动
    Workers ★
  · Evaluator-
    Optimizer
                         │
                         ▼
              ④ 垂直特化形态
              · Agentic RAG（本项目）
              · Deep Agent / 长程任务子 Agent
              · Coding / Computer-Use Agent
```

### 2.1 确定性工作流模式（Workflow Patterns）

源自 Anthropic《Building Effective Agents》，是生产系统中**数量最多**的一类。LLM 在其中只承担单个节点的计算，控制流完全由代码决定。

#### (1) Prompt Chaining（提示链）

把任务拆成固定串行步骤，前一步输出喂给后一步；每步可加代码门禁（gate），不满足就中断。

```
输入 → [LLM 生成提纲] → 门禁检查 → [LLM 写正文] → [LLM 润色] → 输出
```

- **适用**：能清晰拆阶段的任务（营销文案生成、翻译+校对、文档大纲→正文）。
- **生产适配**：★★★★★ 最简单可靠，每步可独立评测、独立缓存、独立换模型。

#### (2) Routing（路由分发）

一个分类节点把输入分流到不同的专用处理链。**专用 Prompt + 专用模型 优于 一个大而全的 Prompt**。

```
                  ┌→ 退款处理链
输入 → [分类 LLM] ├→ 技术支持链
                  └→ 闲聊链
```

- **适用**：客服分流、意图识别（本项目 entry 节点即此模式）、简单问题走小模型/复杂问题走大模型的成本路由。
- **生产适配**：★★★★★ 分类质量可用离线混淆矩阵度量、可回退到默认分支。

#### (3) Parallelization（并行编排）

- **Sectioning（分段）**：一个任务拆成互不依赖的子任务并行跑，最后聚合。如同时查"价格/政策/评价"三类信息。
- **Voting（投票）**：同一任务跑多个实例，多数表决/交叉校验降幻觉。如多个模型各自判断内容是否合规，≥2 票命中才拦截。
- **生产适配**：★★★★☆ 注意并发预算（扇出限流）与聚合幂等；投票模式是低成本提升可靠性的利器。

#### (4) Orchestrator–Workers（主管–工人）★

一个 orchestrator LLM **动态拆解**任务，把子任务分派给并行 worker，再综合结果。与并行分段的区别：**拆几个、拆什么，是运行时动态决定的**。

```
            ┌→ Worker A（代码检索）
[Orchestrator]─→ Worker B（文档检索）  → [Orchestrator 综合]
            └→ Worker C（日志分析）
```

- **适用**：复杂代码变更的影响分析、多源调研报告——子任务数量事前未知。
- **生产适配**：★★★★☆ 这是"多 Agent"与"工作流"的灰色地带：worker 无自主决策权时本质是工作流；给 worker 配工具和自主循环就升级为 Supervisor 多 Agent。**OpenAI Deep Research、多数"深度研究"产品都是此模式**。

#### (5) Evaluator–Optimizer（评估器–优化器）

生成器产出 → 评估器 LLM 按标准打分给修改意见 → 生成器修订，循环直到达标或达迭代上限。

```
[生成] → [评估打分] ─不达标→ [带上意见重新生成]
            │达标
            ▼
          输出
```

- **适用**：翻译润色、代码生成 + review、需要明确评价标准的写作任务。
- **生产适配**：★★★★☆ **必须设最大迭代轮数和退出条件**，否则成本失控；评估标准要结构化（rubric）。

### 2.2 单 Agent 模式（Single Agent）

一个 LLM 在循环中自主使用工具，是"Agent"一词最狭义的所指。

#### (1) ReAct / Tool-Calling Loop（工具调用循环）★基础形态

```
用户消息
   │
   ▼
┌──────────┐  需要信息/操作   ┌──────────┐
│  LLM 思考 │ ──────────────→ │ 调用工具  │
│ (Reason)  │                 │ (Act)    │
└────▲─────┘                 └────┬─────┘
     │                            │
     │  ┌──────────┐              │
     └──│ 观察结果  │◀─────────────┘
        │(Observe) │
        └──────────┘
     循环直到 LLM 给出最终答复（无工具调用）
```

- **核心机制**：现代实现基本不用手写 ReAct 文本格式，而是用模型原生 **Function Calling / Tool Calling**：模型输出结构化工具调用 → 框架执行 → 工具结果回填 → 继续。
- **适用**：工具数量 < ~20、任务步骤有探索性但路径不太深：客服助手、数据分析助理、运维问答。
- **生产适配**：★★★★★ 配好工具白名单、参数校验、循环次数上限、token 预算后，是性价比最高的真 Agent 形态。本项目 `app/agents/` 即此模式。

#### (2) Plan-and-Execute（规划–执行）

先由 **Planner** 一次性产出完整任务计划（步骤列表），再由 **Executor** 逐步执行，执行中可带 Replanner 根据观察结果调整计划。

```
[Planner 出计划] → [Executor 逐步执行(可复用 ReAct)] → [Replanner] ─需要调整→ 重规划
                                                          │计划完成
                                                          ▼
                                                       汇总输出
```

- **与 ReAct 的区别**：ReAct 走一步看一步（短视、易偏离）；Plan-Execute 先谋后动（全局更优、少 token 重复推理），代价是灵活性低、规划错误会传导。
- **适用**：多步骤、长周期、步骤可提前枚举的复杂任务；LangGraph 官方教程的 Plan-and-Execute 模板即此模式。2026 年 LangGraph 推出的 **Deep Agents** 把 planning tool + 文件系统记忆 + 上下文隔离子 Agent 做成了开箱原语。
- **生产适配**：★★★★☆ 计划本身要持久化（崩溃可续跑），必须支持中途 replan。

#### (3) Reflection / Self-Critique（自省反思）

Agent 完成动作后先自我批判（"刚才的 SQL 有没有全表扫描？"）再决定是否重做。属于 Evaluator-Optimizer 在 Agent 语境下的形态。

- **生产适配**：★★★☆☆ 单模型自评有"自我宽容"偏差，关键场景应换**不同模型/不同 prompt** 做批评者，或直接上规则校验器。

#### (4) 状态机型 Agent（FSM / State Graph Agent）★ 2026 主流工程形态

严格说这不是与 ReAct 并列的"认知范式"，而是**工程承载范式**：把上述任何模式（路由、ReAct 循环、审批、重试、兜底）显式建模为**有限状态机/有向图**——节点是函数，边是（可条件化的）状态转移，一个强类型 State 对象在图中流动。

```
                 ┌─────────┐
   START ──────▶ │  路由    │
                 └────┬────┘
            ┌─────────┼──────────┐
            ▼         ▼          ▼
       ┌────────┐ ┌───────┐ ┌────────┐
       │ Agent  │ │  RAG  │ │ 闲聊    │
       │工具循环 │ │ 检索   │ │        │
       └───┬────┘ └───┬───┘ └───┬────┘
           │   需审批  │         │
           ▼          ▼         ▼
       ┌──────────────────────────┐
       │  HITL interrupt（等人工） │ ← 状态落 PostgreSQL，进程重启可恢复
       └────────────┬─────────────┘
                    ▼
                 ┌──────┐
                 │ END  │
                 └──────┘
```

- **为什么成为主流**：生产要求的一切——checkpoint 持久化、断点续跑、人审暂停、分支重试、time-travel 回放调试、并发 reducer——在图模型上都是一等公民；在裸 ReAct 循环里则全要手搓。
- **生产适配**：★★★★★ 这就是 LangGraph 的模型，也是本项目的技术路线。

### 2.3 多 Agent 模式（Multi-Agent）

多个各有 prompt/工具/上下文窗口的 Agent 协作。**上多 Agent 的唯一正当理由是"上下文隔离"和"专业化分工"，而不是"看起来更智能"。**

#### (1) Supervisor / Hierarchical（主管–层级式）★ 多 Agent 生产主流

一个 Supervisor Agent（通常是纯路由 LLM 或状态图节点）把子任务派发给专职子 Agent，子 Agent 完成后**把控制权交回** Supervisor。可多层嵌套形成团队层级。

```
                 ┌──────────────┐
                 │  Supervisor   │ （持有全局任务状态、决定派单/汇总）
                 └──┬───┬───┬───┘
            ┌───────┘   │   └────────┐
            ▼           ▼            ▼
      ┌──────────┐ ┌──────────┐ ┌──────────┐
      │Researcher│ │  Coder   │ │ Reviewer │  各自独立上下文/工具集
      │子 Agent  │ │子 Agent   │ │子 Agent  │
      └──────────┘ └──────────┘ └──────────┘
            └───────────┴───────────┘
                        ▼ 控制权始终回到 Supervisor（星型拓扑）
```

- **优点**：星型拓扑，对话流可预测、可追踪；子 Agent 上下文隔离，主 Agent 的 token 窗口不被子任务细节污染（Deep Agents 的 subagent 原语解决的就是这个）。
- **适用**：子任务领域差异大、需要不同工具集和 system prompt 的场景（研究/编码/审查分治）。
- **生产适配**：★★★★☆ 需要：结构化的 handoff schema、子 Agent 输出契约、全局状态与局部上下文的边界、每跳的预算控制。
- **框架映射**：LangGraph supervisor 模板 / OpenAI Agents SDK 的 **Handoffs** / Microsoft Agent Framework 的 **handoff 原语** / Claude Agent SDK 的"把子 Agent 当工具调用"。

#### (2) Network / Swarm（网状/群体式）

Agent 之间可自由互相移交、自由对话，没有中心控制者（AutoGen GroupChat、早期 Swarm 的 demo 形态）。

- **生产适配**：★☆☆☆☆ 死循环、互相甩锅、token 指数膨胀、对话不可回放。**生产环境基本不用**，仅用于研究/教学。要收敛必须加规则：最大轮数、强制终止态、中心裁判——加完之后它就退化成了 Supervisor。

#### (3) Role-Based Crew（角色协作式）

用"角色（role）/目标（goal）/任务（task）"声明一个人类团队隐喻：研究员→撰稿人→审核员流水线。**CrewAI** 的招牌抽象；其 **Flows** 又把事件驱动的确定性控制补了回来。

- **生产适配**：★★★☆☆ 原型最快、声明式最省心，但执行细节被框架藏得较深，复杂分支下可控性不如显式图；内容生产、商业自动化类场景落地多。

#### (4) Blackboard / Event-Driven（黑板/事件驱动）

Agent 不直接对话，只读写共享"黑板"（共享状态/事件总线），由事件触发合适的 Agent。适合高扇出、异步、长周期业务流程（保险理赔多部门流转）。

- **生产适配**：★★★☆☆ 架构重，需要消息队列与状态一致性设计；本质是"事件驱动微服务 + LLM 节点"，适合与现有 BPM/工作流引擎融合。

### 2.4 垂直特化形态

| 形态 | 是什么 | 备注 |
|---|---|---|
| **Agentic RAG** | RAG 检索不再是固定一步，而由 Agent 自主决定：是否检索、检索几次、改写 query、调哪种检索源、结果不够要不要再查 | 本项目主线，见 [agent-rag-deep-dive.md](./agent-rag-deep-dive.md)。生产标配：混合检索 + metadata 过滤 + Cross-Encoder 精排 |
| **Deep / Long-horizon Agent** | 面向开放长任务（运行数十分钟～数小时）：内置规划工具、虚拟文件系统做外部记忆、动态 spawn 上下文隔离的子 Agent | 2026 热点，代表：LangGraph Deep Agents、OpenAI Deep Research、Claude 的 research 模式 |
| **Coding / Computer-Use Agent** | 以"写代码/执行 shell/操作浏览器"为行动空间，在沙箱环境中迭代执行 | 代表：Claude Code、Devin、OpenAI Codex。强依赖沙箱隔离、权限确认、diff 级 HITL |
| **Embodied/语音 Agent** | 接入实时语音、传感器，低延迟 turn-taking | 与 Web 后端链路差异大，本项目明确列为非目标 |

---

## 3. 2026 主流框架横评（按"层"选型，不要跨层比较）

"Agent 框架"在 2026 已分化为四层，**越低层越可控越费劲，越高层越省事越黑盒**：

| 层 | 代表 | 一句话定位 | 生产选它的条件 |
|---|---|---|---|
| **Runtime 引擎** | **LangGraph** 1.x（MIT） | 状态图运行时：checkpoint、断点续跑、HITL、time-travel | 默认选择。有状态、长流程、合规审计、复杂分支 |
| **SDK 套件** | **OpenAI Agents SDK** | 四原语：Agent / Tool / Handoff / Guardrail；2026-02 起集成 Temporal 持久化执行 | 全押 OpenAI 生态、要最薄抽象、快速交付 |
| **多 Agent 编排** | **CrewAI** | 角色 + 任务 + Crew，Flows 补事件控制 | 角色分工天然契合的内容/调研流水线，重原型速度 |
| **Agent SDK** | **Claude Agent SDK** | 工具循环优先，子 Agent 即工具，私有化部署友好 | Claude 模型栈、类 Claude Code 的执行体 |
| **统一框架** | **Microsoft Agent Framework 1.0**（AutoGen + Semantic Kernel 继任者，2026-04） | 原生 MCP + A2A，.NET/Python 双栈 | .NET 技术栈、企业 Office/Azure 生态 |
| **轻量代码 Agent** | **Smolagents**（HF） | Code-as-action：让模型直接写 Python 当动作 | 沙箱完备、动作空间是计算而非 API 调用 |
| **低代码平台** | **Dify / Coze** | 可视化编排 + 知识库 + 运营后台 | 团队缺专职 AI 工程师、流程标准化、需业务方自运营 |

补充事实：

- **协议层**：**MCP**（Model Context Protocol，接工具/数据源）与 **A2A**（Agent-to-Agent，跨进程 Agent 互调）在 2026 已成互通标配，新系统的工具接入层建议预留 MCP client 位。
- **可观测性**：LangSmith（LangGraph 原生）、Langfuse（开源、可私有化，本项目选型）均走 OpenTelemetry 语义。
- **选型反模式**：为"怕被框架绑定"而自研编排循环——状态持久化、重试、中断恢复、并发 reducer 四个坑踩完，得到一个残缺版 LangGraph。

---

## 4. 生产级 Agent 的必备能力清单（选型验收表）

无论哪种类型/框架，上生产前逐条对照：

| # | 能力 | 说明 | 本项目对应 |
|---|---|---|---|
| 1 | **状态外置与持久化** | 会话/图状态进 PostgreSQL/Redis，进程无状态、可水平扩、崩溃续跑 | checkpointer 设计 |
| 2 | **Durable Execution** | 每个节点执行可重试、幂等；失败从上个 checkpoint 恢复而非重头再来 | `example/idempotent.py` |
| 3 | **Human-in-the-loop** | 写操作/危险动作可 interrupt 暂停，等人工审批后恢复 | `example/hitl.py` |
| 4 | **工具治理** | 注册中心、参数 schema 校验、权限分级、超时、熔断、审计日志 | `assistant/tool_registry.py`、`example/circuit_breaker.py` |
| 5 | **Guardrails（护栏）** | 输入侧：注入/越权/PII；输出侧：敏感信息/格式；强制在代码层而非靠 prompt | `core/security.py` |
| 6 | **预算与循环控制** | 最大迭代轮数、token/成本预算、单工具调用上限，超限走兜底 | — |
| 7 | **全链路可观测** | trace（每次工具调用的入参/出参/耗时/token）、指标面板、日志关联 | `core/metrics.py` + Langfuse |
| 8 | **离线评测集 + CI 门禁** | 意图分类、工具选择、检索命中、答案忠实度分层评测，防止改 prompt 引入回归 | docs 中 G2 验收 |
| 9 | **模型网关** | 多供应商、按任务路由模型、降级 fallback、统一计费 | `assistant/llm_gateway.py` |
| 10 | **降级兜底** | LLM/向量库故障时系统整体可用（缓存答案/转人工/只读模式） | `assistant/resilience.py` |
| 11 | **多租户与数据隔离** | 检索 metadata 过滤强制租户边界，工具调用二次鉴权 | — |
| 12 | **版本化与灰度** | prompt/图定义版本化，可按租户灰度、可回滚 | — |

---

## 5. 工程目录结构规范

原则：**编排层（决定"做什么"）与能力层（决定"怎么做"）严格分离**；Agent 节点只做决策与编排，不直接写 SQL/HTTP；所有外部世界访问收敛到 tools/services。

### 5.1 单 Agent 生产结构（推荐基线，与本项目现状对齐）

本项目已有的 `app/agents/`（state/nodes/graph/tools/prompts 五件套）就是最小正确结构，生产完整版建议如下：

```
app/
├── main.py                     # 应用入口：装配 FastAPI / 路由 / 生命周期
├── config.py                   # 环境配置（pydantic-settings）
│
├── api/                        # HTTP 路由层（薄：参数校验 → 调 service）
│   └── v1/
├── ws/                         # WebSocket 网关层：鉴权/限流/协议适配/事件注入
│
├── agents/                     # ★ Agent 编排层（只放"决策与流程"，不放业务细节）
│   ├── state.py                #   强类型 State schema + reducer（并发更新规则）
│   ├── graph.py                #   构图：add_node/add_edge/条件路由 + compile(checkpointer)
│   ├── nodes.py                #   节点函数（单文件可控时）；膨胀后拆 nodes/ 包：
│   │                           #     nodes/router.py 意图路由
│   │                           #     nodes/agent.py    工具调用循环
│   │                           #     nodes/rag.py
│   │                           #     nodes/chitchat.py
│   │                           #     nodes/summarizer.py
│   ├── edges.py                #   条件边/路由判定（从 nodes 拆出，便于单测）
│   ├── prompts/                #   提示词模板，按节点一文件，带版本号
│   │   ├── router.py
│   │   └── system.py
│   ├── middleware/             #   图级中间件：token 计费、审计、trace 注入、护栏
│   └── interrupts.py           #   HITL interrupt 定义与恢复 schema
│
├── tools/                      # ★ 工具层：Agent 与世界之间的唯一边界
│   ├── registry.py             #   工具注册中心（@tool 统一登记、权限/超时元数据）
│   ├── schemas.py              #   工具入参/出参 Pydantic 模型（即 function schema）
│   ├── baby.py                 #   按领域组织的工具集（查奶量/记录睡眠...）
│   ├── search.py
│   └── mcp/                    #   MCP client：外部 MCP server 工具适配
│
├── rag/                        # 检索能力（纯函数式服务，Agent/HTTP 共用）
│   ├── retriever.py            #   统一入口 search()：query 改写 → 混合召回 → 精排
│   ├── chunking.py
│   ├── embeddings.py
│   └── indexer/                #   增量索引、版本管理
│
├── services/                   # 业务领域服务（工具的实际实现调这里，可被非 Agent 复用）
│   ├── todo_service.py
│   └── memory.py
│
├── assistant/                  # Agent 运行时基础设施（本项目已有的生产化沉淀）
│   ├── llm_gateway.py          #   多模型路由 / 降级 / 成本统计
│   ├── resilience.py           #   熔断 / 重试 / 限流 / 兜底
│   ├── runtime.py              #   图实例装配与调用封装（ainvoke/astream）
│   ├── repository.py           #   会话/检查点仓储
│   └── db_models.py
│
├── repositories/               # 数据访问层（MySQL/Redis/向量库）
├── models/                     # ORM 模型
├── schemas/                    # API DTO
├── core/                       # 横切：logging / metrics / security / database
├── integrations/               # 第三方系统客户端
├── evals/                      # ★ 离线评测：数据集 + 分层指标 + CI 脚本
│   ├── datasets/
│   └── run_eval.py
└── utils/
```

**依赖方向（只允许向内依赖）**：

```
api/ws  →  agents(编排)  →  tools  →  services  →  repositories
              │                              │
              └──────────────→ rag ───────────┘
       （任何层都可横切使用 core/config、assistant 运行时）
```

禁反例：❌ 在 node 里直接 `requests.post`；❌ 在 tool 里拼图路由；❌ prompt 里硬编码业务 SQL。

### 5.2 多 Agent（Supervisor）结构的增量扩展

单 Agent 结构验证跑通后，**只增量增加 `subagents/`，其余不动**：

```
app/agents/
├── state.py                    # 全局状态：任务清单、各子 Agent 结果摘要、预算
├── graph.py                    # supervisor 图：supervisor 节点 + 子 agent 节点 + 汇总
├── nodes/
│   ├── supervisor.py           #   派单/收单决策（输出结构化 handoff 指令）
│   └── aggregator.py           #   子结果综合
├── subagents/                  # ★ 每个子 Agent 自带五件套，互相独立
│   ├── researcher/
│   │   ├── state.py            #   局部状态（与全局 state 显式映射，不共享隐式上下文）
│   │   ├── graph.py
│   │   ├── nodes.py
│   │   ├── prompts.py
│   │   └── tools.py            #   只暴露该领域工具，做权限最小化
│   ├── coder/
│   └── reviewer/
└── contracts/                  # ★ handoff 输入/输出契约（Pydantic）
    └── handoff.py              #   TaskEnvelope{task_id, assignee, payload, deadline}
```

多 Agent 目录设计的三条铁律：

1. **契约先行**：supervisor 与 subagent 之间只传结构化 `TaskEnvelope`，不传自由文本聊天记录；
2. **上下文隔离**：子 Agent 看不到全局历史，只收到任务包；结果只回摘要/产物引用（大产物落文件系统或对象存储）；
3. **预算穿透**：每跳携带剩余预算字段，supervisor 可随时熔断整个任务。

### 5.3 最小验证结构（demo / POC 阶段）

不允许一上来就建全套。POC 阶段 5 个文件足够（即本项目 `app/agents/` 现状）：

```
agents/
├── state.py     # 状态定义
├── nodes.py     # 全部节点
├── graph.py     # 构图编译
├── tools.py     # 工具集
└── prompts.py   # 提示词
```

**从 5.3 演进到 5.1 的触发信号**：nodes.py 超 400 行 / 工具超过 8 个 / 出现第二个调用方（HTTP 与 WS 共用）/ 需要接第二家模型。

---

## 6. 选型决策树

```
你的任务流程步骤能提前穷举吗？
├─ 能 → 用确定性 Workflow
│       ├─ 单一固定流水线 ……………… Prompt Chaining
│       ├─ 输入分几类、处理不同 ……… Routing
│       ├─ 可并行/要表决 ……………… Parallelization
│       ├─ 子任务数量运行时才知道 … Orchestrator-Workers
│       └─ 有明确质量标准可迭代 …… Evaluator-Optimizer
│
└─ 不能，需要模型临场探索
    └─ 一个 Agent + 工具够吗？
        ├─ 够（<20 工具、深度 <8 步）…… ReAct/Tool-Calling 循环，用 LangGraph 状态图承载 ★
        └─ 不够
            ├─ 主要是"先规划再执行" …… Plan-and-Execute / Deep Agent
            └─ 子任务领域差异大、需不同工具集与上下文
                └─ 用 Supervisor 多 Agent（子 Agent 即专职工具）★
                    （不要用自由对话的网状拓扑）
```

框架一句话决策：

- **要上生产、有专职工程师 → LangGraph**（本项目路线，2026 最主流）
- 只在 OpenAI 上快跑 → OpenAI Agents SDK
- 一周内要给老板演示多角色协作 → CrewAI
- 没有工程师、业务自己配 → Dify/Coze
- .NET 栈/微软生态 → Microsoft Agent Framework

---

## 7. 面试谈点（Talking Points）

1. **"Workflow 和 Agent 的区别？"** ——控制流在代码还是在 LLM 手里；生产默认从 workflow 起步，在需要开放决策的节点内嵌 agent 循环，而不是一上来全自主。
2. **"多 Agent 是不是更好？"** ——生产上 90% 的多 Agent 需求用单 Agent + 丰富工具就能解决；多 Agent 的真实价值是**上下文隔离与专业化**，且拓扑只选 supervisor 星型，网状拓扑不可运维。
3. **"为什么选 LangGraph？"** ——它把 Agent 建模为显式状态图：checkpoint 持久化、断点续跑、HITL、time-travel 调试、并发 reducer 都是一等公民；这些在裸 ReAct 循环里全要手搓。代价是学习曲线，用 5 件套小结构起步可规避过度工程。
4. **"Agent 怎么保证生产可靠？"** ——不信任 LLM 原则：鉴权、参数校验、预算、审批在代码层强制；状态外置、工具幂等、全链路 trace、分层评测 CI、模型网关降级。
5. **"Agentic RAG 和传统 RAG？"** ——检索从固定一步变成 Agent 可自主编排的动作：是否查、查几次、query 改写、多源选择；质量靠混合检索 + metadata 过滤 + Cross-Encoder 精排 + 忠实度评测。
6. **"MCP / A2A 了解吗？"** ——MCP 解决 Agent 接工具/数据源的标准插头问题；A2A 解决跨进程 Agent 互调；2026 框架普遍原生支持，设计工具层时应预留。

---

## 参考来源

- Anthropic, *Building Effective Agents*（workflow 五模式的原始定义）
- LangGraph 官方文档：Multi-agent Supervisors、Plan-and-Execute、Deep Agents、Persistence/HITL
- OpenAI Agents SDK 文档（Agents/Tools/Handoffs/Guardrails；Temporal durable execution，2026）
- Microsoft Agent Framework 1.0 发布说明（AutoGen/Semantic Kernel 继任，MCP + A2A，2026-04）
- 2026 年框架横评资料（LangGraph / CrewAI / OpenAI Agents SDK / Claude Agent SDK / Smolagents 生产适配对比）
