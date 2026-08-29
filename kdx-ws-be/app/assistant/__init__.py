"""Baby Assistant 应用包

将 app/example 中的生产实践方案落地为真实的 AI Park Assistant：
- 意图识别 (intent_recognition)    → graph.py intent_node
- 动态路由 (dynamic_routing)       → graph.py conditional_edges
- 多Agent协同 (multi_agent)        → graph.py 数据Agent/RAG Agent/闲聊Agent + ReAct循环
- 状态机管理 (state_machine)       → StateGraph 状态流转 + WS层会话状态机
- 人工介入 HITL (hitl)             → 写入类工具确认暂停/恢复
- Function Calling (function_calling) → tools.py + graph.py ReAct 循环
- 工具注册中心 (tool_registry)     → tool_registry.py
- 鉴权 (auth)                      → ws/baby_assistant.py JWT 三种提取方式
- 幂等 (idempotent)                → resilience.py IdempotencyManager
- 降级与熔断 (circuit_breaker)     → resilience.py CircuitBreaker
"""
