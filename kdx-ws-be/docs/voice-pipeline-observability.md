# 语音管线监控与日志埋点设计

> 对应代码: [app/voice/observability.py](../app/voice/observability.py) + [app/ws/ai_entrance.py](../app/ws/ai_entrance.py)
>
> 基础设施复用: [app/core/metrics.py](../app/core/metrics.py) (Prometheus 最小实现 + Langfuse 钩子) + [app/assistant/llm_gateway.py](../app/assistant/llm_gateway.py) (LLM 调用埋点)

---

## 1. 三层可观测性架构

```
┌──────────────────────────────────────────────────────────────────┐
│                     语音管线可观测性                              │
│                                                                  │
│  Layer 1: Prometheus 指标 (GET /metrics)                         │
│  ├─ 请求级: QPS / 延迟 / 成功率 / 错误率                           │
│  ├─ 管线级: ASR 识别延迟 / TTS 合成延迟 / 端到端延迟               │
│  └─ 资源级: 活跃会话数 / 并发处理数                                │
│                                                                  │
│  Layer 2: 结构化日志 (loguru, JSON 格式)                         │
│  ├─ 每阶段记录 request_id / user_id / 耗时 / 结果                  │
│  └─ 错误带完整 traceback                                          │
│                                                                  │
│  Layer 3: Langfuse Trace (env 开关)                              │
│  └─ ASR → Agent → TTS 全链路串联, 按 request_id 查询              │
│                                                                  │
│  传递机制: contextvars (零侵入函数签名)                          │
└──────────────────────────────────────────────────────────────────┘
```

### 设计原则

1. **零侵入**: 所有埋点用 `contextvars` 传递 `request_id` / `user_id` / 阶段时间戳，不侵入业务函数签名
2. **错误降级**: 指标记录失败不影响主流程（`metrics.inc()` 异常被吞掉）
3. **延迟观测**: 用 `observe()` 存 `latest` + `sum`，生产环境换 `prometheus_client.Histogram`
4. **复用现有**: LLM 网关已有埋点（`llm_requests_total` / `llm_latency_ms`），语音层只加管线级指标

---

## 2. contextvars 追踪上下文

[app/voice/observability.py](../app/voice/observability.py) 的 `VoiceTraceContext` 通过 `contextvars` 跨异步调用传递，一个请求一个实例：

```python
@dataclass
class VoiceTraceContext:
    request_id: str          # 唯一标识
    user_id: int             # 用户隔离
    thread_id: str           # LangGraph checkpointer thread
    mode: str                # "text" | "voice"
    t_start: float           # 请求开始时间

    # 管线阶段时间戳
    t_asr_start: float
    t_asr_end: float
    t_agent_start: float
    t_agent_end: float
    t_tts_start: float
    t_tts_end: float

    # 统计
    asr_chunks: int           # 部分识别次数
    asr_final_text: str      # 最终识别文本
    agent_tool_calls: int    # 工具调用次数
    tts_audio_bytes: int     # TTS 音频字节数
    intent: str              # 意图分类
    route: str               # 路由分支
    error: str               # 错误信息
```

**生命周期**:
```python
# 进入请求时创建
ctx = VoiceTraceContext(request_id=..., user_id=..., thread_id=..., mode="voice")
trace_token = set_voice_trace_context(ctx)

# 管线各阶段通过 get_voice_trace() 读上下文
record_asr_start()    # → ctx.t_asr_start = time.time()
record_asr_final(text) # → ctx.t_asr_end = time.time(), ctx.asr_final_text = text
record_agent_end(intent, route, tool_calls) # → ctx.t_agent_end, ctx.intent, ...
record_query_end("ok") # → 计算端到端延迟, 写日志

# 退出时清理
reset_voice_trace_context(trace_token)
```

---

## 3. Prometheus 指标清单

### 3.1 请求级指标

| 指标名 | 类型 | 标签 | 含义 |
|---|---|---|---|
| `voice_queries_total` | counter | `mode` (text/voice) | 请求总数 |
| `voice_query_status_total` | counter | `mode`, `status` (ok/error) | 请求结果统计 |
| `voice_e2e_latency_ms` | histogram | `mode`, `status` | 端到端延迟（query_start → query_done） |
| `voice_active_queries` | gauge | — | 当前并发处理中的请求数 |

### 3.2 管线级指标

| 指标名 | 类型 | 标签 | 含义 |
|---|---|---|---|
| `voice_asr_chunks_total` | counter | — | ASR 部分识别事件总数 |
| `voice_asr_latency_ms` | histogram | — | ASR 识别延迟（asr_start → stt_output） |
| `voice_agent_latency_ms` | histogram | `intent` | Agent 图执行延迟 |
| `voice_tts_chunks_total` | counter | — | TTS 音频帧总数 |
| `voice_tts_latency_ms` | histogram | — | TTS 合成延迟 |

### 3.3 资源级指标

| 指标名 | 类型 | 标签 | 含义 |
|---|---|---|---|
| `voice_connections_total` | counter | `user_id` | 连接建立总数 |
| `voice_active_connections` | gauge | — | 当前活跃 WebSocket 连接数 |
| `voice_disconnects_total` | counter | `reason` (client_disconnect/idle_timeout/internal_error) | 断开原因统计 |

### 3.4 HITL 指标

| 指标名 | 类型 | 标签 | 含义 |
|---|---|---|---|
| `voice_hitl_pending_total` | counter | — | HITL 挂起次数 |
| `voice_hitl_resolved_total` | counter | `action` (approve/reject) | HITL 确认/拒绝统计 |

### 3.5 安全指标

| 指标名 | 类型 | 标签 | 含义 |
|---|---|---|---|
| `voice_rate_limited_total` | counter | `user_id` | 限流触发次数 |
| `voice_idle_timeout_total` | counter | `user_id` | 空闲踢出次数 |
| `voice_errors_total` | counter | `stage`, `error` | 错误按阶段分类 |

### 3.6 已有 LLM 指标（复用）

| 指标名 | 来源 | 含义 |
|---|---|---|
| `llm_requests_total` | `llm_gateway.py` | LLM 调用次数 |
| `llm_requests_failed_total` | `llm_gateway.py` | LLM 调用失败数 |
| `llm_fallback_total` | `llm_gateway.py` | 降级到备用模型次数 |
| `llm_latency_ms` | `llm_gateway.py` | LLM 调用延迟 |
| `llm_breaker_state` | `llm_gateway.py` → `/metrics` | 熔断器状态 |

---

## 4. 结构化日志规范

### 4.1 日志格式

所有语音管线日志统一前缀 `[voice]`，携带 `request_id` + `user_id`：

```
[voice] query_start request_id=abc123 user_id=1 mode=voice
[voice] asr_final request_id=abc123 latency=850ms text_len=12 text=今天喝了多少奶
[voice] agent_done request_id=abc123 latency=1200ms intent=data_query route=agent tool_calls=1
[voice] tts_done request_id=abc123 latency=650ms audio_bytes=38400
[voice] query_done request_id=abc123 user_id=1 mode=voice status=ok latency=2700ms intent=data_query route=agent asr_chunks=3 tool_calls=1 tts_bytes=38400
```

### 4.2 日志级别约定

| 级别 | 场景 |
|---|---|
| `INFO` | 请求开始/完成、ASR 定稿、Agent 完成、TTS 完成、HITL 挂起/确认、连接/断开 |
| `DEBUG` | ASR 开始、TTS 开始、部分识别（高频，生产可关） |
| `WARNING` | 限流、空闲踢出、TTS 失败（可降级） |
| `ERROR` | 管线错误（ASR 失败/Agent 异常/WS 循环异常） |

### 4.3 错误日志带 traceback

```python
# observability.py
def record_error(stage: str, error: str) -> None:
    ctx = get_voice_trace()
    logger.error(
        f"[voice] error request_id={ctx.request_id} "
        f"user_id={ctx.user_id} stage={stage} error={error}"
    )
    # 主流程用 logger.exception() 输出完整 traceback
```

---

## 5. 埋点位置一览表

| 管线阶段 | 埋点函数 | 代码位置 | 指标 | 日志 |
|---|---|---|---|---|
| 连接建立 | `record_connection()` | ai_entrance.py: 鉴权后 | `voice_connections_total` + `voice_active_connections++` | INFO |
| 文字请求开始 | `record_query_start("text")` | process_query() | `voice_queries_total{mode=text}` + `voice_active_queries++` | INFO |
| 语音请求开始 | `record_query_start("voice")` | process_voice_query() | `voice_queries_total{mode=voice}` + `voice_active_queries++` | INFO |
| ASR 开始 | `record_asr_start()` | process_voice_query() | — | DEBUG |
| ASR 部分识别 | `record_asr_chunk()` | stt_chunk 事件 | `voice_asr_chunks_total++` | — |
| ASR 定稿 | `record_asr_final(text)` | stt_output 事件 | `voice_asr_latency_ms` observe | INFO |
| Agent 开始 | `record_agent_start()` | run_graph() 前 | — | DEBUG |
| Agent 完成 | `record_agent_end(intent, route, tool_calls)` | run_graph() 后 | `voice_agent_latency_ms{intent}` observe | INFO |
| TTS 开始 | `record_tts_start()` | _stream_tts() | — | DEBUG |
| TTS 音频帧 | `record_tts_chunk(bytes)` | tts receive_events | `voice_tts_chunks_total++` | — |
| TTS 完成 | `record_tts_end()` | _stream_tts() finally | `voice_tts_latency_ms` observe | INFO |
| 请求完成 | `record_query_end(status)` | 各 process 函数 finally | `voice_e2e_latency_ms` observe + `voice_query_status_total` + `voice_active_queries--` | INFO |
| HITL 挂起 | `record_hitl_pending(confirm_id)` | interrupt 检测 | `voice_hitl_pending_total++` | INFO |
| HITL 确认 | `record_hitl_resolved("approve"/"reject")` | process_confirm() | `voice_hitl_resolved_total{action}` | INFO |
| 限流 | `record_rate_limit(user_id)` | limiter.allow() 失败 | `voice_rate_limited_total{user_id}` | WARNING |
| 空闲踢出 | `record_idle_timeout(user_id)` | IDLE_TIMEOUT | `voice_idle_timeout_total{user_id}` | WARNING |
| 管线错误 | `record_error(stage, error)` | 各 catch 块 | `voice_errors_total{stage,error}` | ERROR |
| 连接断开 | `record_disconnect(user_id, reason)` | finally | `voice_active_connections--` + `voice_disconnects_total{reason}` | INFO |

---

## 6. 端到端延迟分解

一次语音请求的完整延迟链：

```
t_start ────────────────────────────────────────────────────── t_query_end
  │                                                            │
  ├── ASR 阶段 ──────────┤                                      │
  │  t_asr_start          t_asr_end                            │
  │  │← asr_latency_ms →│                                      │
  │                       │                                     │
  │                       ├── Agent 阶段 ──────────┤           │
  │                       │  t_agent_start         t_agent_end  │
  │                       │  │← agent_latency_ms →│            │
  │                       │                         │           │
  │                       │                         ├── TTS ───┤│
  │                       │                         │ tts_start││
  │                       │                         │ │← tts_latency_ms →│
  │                       │                         │          tts_end
  │                       │                         │           │
  │←──────────── e2e_latency_ms (t_query_end - t_start) ──────→│
```

**Prometheus 查询示例**:

```promql
# P99 端到端延迟
histogram_quantile(0.99, voice_e2e_latency_ms_sum / voice_e2e_latency_ms_count)

# ASR + Agent + TTS 各阶段延迟占比
voice_asr_latency_ms_latest / voice_e2e_latency_ms_latest
voice_agent_latency_ms_latest / voice_e2e_latency_ms_latest
voice_tts_latency_ms_latest / voice_e2e_latency_ms_latest

# 语音 vs 文字成功率对比
sum(rate(voice_query_status_total{status="ok", mode="voice"}[5m]))
  / sum(rate(voice_queries_total{mode="voice"}[5m]))

# HITL 确认率
sum(rate(voice_hitl_resolved_total{action="approve"}[5m]))
  / sum(rate(voice_hitl_pending_total[5m]))
```

---

## 7. Langfuse 全链路 Trace

已有基础设施：[app/core/metrics.py](../app/core/metrics.py) 的 `get_langfuse_handler()` 返回 `CallbackHandler`，按 `user_id` / `request_id` 串联。

**语音管线集成点**:

```python
# ai_entrance.py: run_graph() 内注入 Langfuse callback
from ..core.metrics import get_langfuse_handler

langfuse_handler = get_langfuse_handler()
callbacks = [langfuse_handler] if langfuse_handler else []

result = await graph.ainvoke(
    state,
    {**graph_config(), "callbacks": callbacks}
)
```

Langfuse UI 上按 `request_id` 搜索可看到完整链路：

```
request_id: abc123
├── entry_node (intent: data_query, 80ms)
├── agent_node (LLM call, 1200ms)
│   ├── tool_call: query_feed_milk (340ms)
│   └── tool_call: add_feed_milk (HITL interrupt → resumed, 15s)
├── generate answer (600ms)
└── TTS synthesis (650ms)
```

---

## 8. 生产部署建议

### 8.1 Prometheus 抓取配置

```yaml
scrape_configs:
  - job_name: kdx-voice
    metrics_path: /metrics
    scrape_interval: 15s
    static_configs:
      - targets: ['kdx-ws-be:8000']
```

### 8.2 Grafana Dashboard 面板建议

| 面板 | 指标 | 可视化 |
|---|---|---|
| 请求 QPS | `rate(voice_queries_total[5m])` 按 mode 分 | 时间序列折线 |
| 端到端 P50/P99 延迟 | `histogram_quantile` | 时间序列 |
| 各阶段延迟分解 | asr/agent/tts latency_latest | 堆叠面积图 |
| 成功率 | `ok / total` | 仪表盘 |
| 活跃连接数 | `voice_active_connections` | 数值卡 |
| HITL 确认率 | `approve / pending` | 百分比 |
| 错误率 by stage | `rate(voice_errors_total[5m])` by stage | 条形图 |
| 限流次数 | `rate(voice_rate_limited_total[5m])` | 时间序列 |

### 8.3 告警规则建议

```yaml
groups:
  - name: voice-pipeline
    rules:
      - alert: VoiceErrorRateHigh
        expr: rate(voice_errors_total[5m]) > 0.1
        for: 5m
        annotations:
          summary: "语音管线错误率 > 10%"

      - alert: VoiceP99LatencyHigh
        expr: voice_e2e_latency_ms_latest > 5000
        for: 10m
        annotations:
          summary: "语音 P99 延迟 > 5s"

      - alert: VoiceASRFailure
        expr: rate(voice_errors_total{stage="asr"}[5m]) > 0.05
        for: 5m
        annotations:
          summary: "ASR 错误率 > 5%"

      - alert: VoiceTTSFailure
        expr: rate(voice_errors_total{stage="tts"}[5m]) > 0.05
        for: 5m
        annotations:
          summary: "TTS 错误率 > 5%"
```

---

## 9. 埋点代码文件清单

| 文件 | 职责 |
|---|---|
| [app/voice/observability.py](../app/voice/observability.py) | `VoiceTraceContext` + 全部 `record_*` 函数 |
| [app/ws/ai_entrance.py](../app/ws/ai_entrance.py) | 在管线各阶段调用 `record_*` |
| [app/core/metrics.py](../app/core/metrics.py) | `Metrics` 类 + `get_langfuse_handler()` (已有，复用) |
| [app/api/metrics.py](../app/api/metrics.py) | `GET /metrics` 端点 (已有，自动暴露新增指标) |
| [app/assistant/llm_gateway.py](../app/assistant/llm_gateway.py) | LLM 调用埋点 (已有，复用) |
