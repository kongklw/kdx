# Agent 工程化示例集

本目录包含 Agent 开发中 **10 个核心概念** 的完整可运行 demo，每个文件包含：
- 概念解释
- 生产实践方案
- LangGraph/LangChain 对应实现（伪代码或真实代码）
- 面试话术
- 可运行示例

## 文件一览

| 文件 | 概念 | 面试关键词 |
|------|------|-----------|
| `intent_recognition.py` | 意图识别 | 两级策略(规则+LLM)、槽位抽取、置信度兜底 |
| `dynamic_routing.py` | 动态路由 | 声明式路由表、conditional_edges、热更新 |
| `multi_agent.py` | 多 Agent 协同 | Supervisor 模式、串行流水线、并行扇出 |
| `state_machine.py` | 状态机管理 | 状态转换图、before/after hook、非法转换拦截 |
| `hitl.py` | 人工介入 HITL | interrupt/checkpoint、approve/reject/edit、超时告警 |
| `function_calling.py` | Tool/Function Calling | @tool 装饰器、ReAct 循环、ToolMessage 反馈 |
| `tool_registry.py` | 工具注册中心 | 动态注册、RBAC 权限、热上下线、标签筛选 |
| `auth.py` | 鉴权 | JWT 三种传参、RBAC 角色层级、工具级+数据级授权 |
| `idempotent.py` | 幂等 | request_id 去重、状态前置检查、Redis SETNX |
| `circuit_breaker.py` | 降级与熔断 | 三态机(Closed/Open/Half-Open)、降级策略、fallback |

## 运行方式

```bash
cd /home/konglingwen/myspace/kdx/kdx-ws-be

# 安装依赖
pip install -e .

# 运行单个 demo（以意图识别为例）
python -m app.example.intent_recognition

# 运行动态路由 demo
python -m app.example.dynamic_routing

# 运行多 Agent 协同 demo
python -m app.example.multi_agent

# 运行状态机 demo
python -m app.example.state_machine

# 运行 HITL demo
python -m app.example.hitl

# 运行 Function Calling demo
python -m app.example.function_calling

# 运行工具注册中心 demo
python -m app.example.tool_registry

# 运行鉴权 demo（需要 PyJWT）
python -m app.example.auth

# 运行幂等 demo
python -m app.example.idempotent

# 运行熔断器 demo
python -m app.example.circuit_breaker
```

## 概念关联图

```
用户请求
    │
    ▼
┌──────────────┐     ┌─────────────────┐     ┌───────────────┐
│  鉴权(JWT)    │────▶│  意图识别        │────▶│  动态路由      │
│  auth.py     │     │  intent_recog.. │     │  routing.py  │
└──────────────┘     └─────────────────┘     └───────┬───────┘
                                                     │
                    ┌────────────────────────────────┘
                    ▼
             ┌──────────────┐
             │ 多 Agent 协同  │──▶ ┌──────────────┐  ┌──────────────┐
             │ multi_agent  │    │ 工具注册中心   │  │ Function     │
             └──────┬───────┘    │ tool_registry │──│ Calling      │
                    │            └──────────────┘  └──────────────┘
                    ▼
             ┌──────────────┐
             │  状态机管理   │────▶ ┌──────────────┐
             │ state_machine│      │  HITL 人工介入│
             └──────┬───────┘      │  hitl.py    │
                    │              └──────────────┘
                    ▼
             ┌──────────────┐     ┌──────────────┐
             │  幂等检查     │────▶│ 熔断 + 降级   │
             │ idempotent   │     │ circuit_br.. │
             └──────────────┘     └──────────────┘
```

## 面试速记卡

| 面试官问 | 你答什么 |
|---------|---------|
| "怎么做意图识别？" | "两级策略：规则正则覆盖80%高频场景，未命中走LLM few-shot分类，输出intent+confidence+slots JSON，低置信度走兜底" |
| "怎么做动态路由？" | "声明式路由表，intent→handler映射可热更新。LangGraph用conditional_edges实现" |
| "多Agent怎么协同？" | "Supervisor模式：Supervisor负责任务分解和分发，专职Agent各司其职，通过SharedState传递中间结果" |
| "状态怎么管理？" | "StateGraph本质是状态机，节点=状态，边=转换，conditional_edges=条件分支，checkpoint支持持久化" |
| "HITL怎么做？" | "LangGraph interrupt()暂停+checkpoint持久化，人工通过Command(resume=...)恢复，支持approve/reject/edit" |
| "Function Calling流程？" | "LLM收到工具schema→输出tool_calls→Agent执行→ToolMessage反馈→LLM继续推理" |
| "工具怎么管理？" | "工具注册中心动态注册/发现，按RBAC权限过滤，支持热上下线和标签筛选" |
| "鉴权怎么设计？" | "三层：连接级JWT校验、工具级RBAC授权、数据级user_id隔离" |
| "如何保证幂等？" | "request_id+Redis SETNX去重，叠加状态前置检查双重保证" |
| "服务挂了怎么办？" | "三态熔断器：Closed→Open→Half-Open，降级策略：LLM→模板、向量库→关键词、TTS→文本" |
