"""
可观测性: 指标注册表 + Langfuse 钩子
====================================

Prometheus 文本暴露格式的最小实现 (无外部依赖):
    metrics.inc("agent_queries_total", labels={"intent": "data_query"})
    metrics.set("llm_breaker_state", 1, labels={"profile": "agent"})

接入点:
- LLM 网关: 每次调用记录 usage (latency/token/成功/降级)
- 熔断器: snapshot() 定时刷 gauge
- WS 层: 查询 QPS / 写操作确认率 / 幂等命中率
- /metrics 端点暴露文本格式供 Prometheus 抓取
"""

import threading
import time
from typing import Any, Dict, List, Optional


class Metrics:
    def __init__(self):
        self._lock = threading.Lock()
        self._counters: Dict[str, float] = {}
        self._gauges: Dict[str, float] = {}
        self._labels: Dict[str, Dict[str, str]] = {}

    def _key(self, name: str, labels: Optional[Dict[str, str]]) -> str:
        if not labels:
            return name
        parts = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{parts}}}"

    def inc(self, name: str, labels: Optional[Dict[str, str]] = None, value: float = 1) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + value
            self._labels[key] = labels or {}

    def set(self, name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._gauges[key] = value
            self._labels[key] = labels or {}

    def observe(self, name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """直方图近似: 用 gauge 存最近值 + counter 累计 (生产换 prometheus_client.Histogram)"""
        key = self._key(name + "_sum", labels)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + value
        self.set(name + "_latest", value, labels)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
            }

    def render_prometheus(self) -> str:
        """输出 Prometheus 文本格式 (counter 以 _total 后缀约定由采集方处理)"""
        lines = []
        with self._lock:
            for key, val in sorted(self._counters.items()):
                lines.append(f"# TYPE {key.split('{')[0]} counter")
                lines.append(f"{key} {val}")
            for key, val in sorted(self._gauges.items()):
                lines.append(f"# TYPE {key.split('{')[0]} gauge")
                lines.append(f"{key} {val}")
        return "\n".join(lines) + "\n"


_metrics = Metrics()


def get_metrics() -> Metrics:
    return _metrics


# ──────────────────────────────────────────────
# Langfuse 回调钩子 (env 开关, 未配置时零开销 no-op)
# ──────────────────────────────────────────────

_langfuse_handler = None
_langfuse_checked = False


def get_langfuse_handler():
    """
    返回 Langfuse callback handler (若配置了 LANGFUSE_PUBLIC_KEY / LANGFUSE_HOST)。
    用于 ChatOpenAI(callbacks=[...]) 全链路 trace, 按 user_id/request_id 串联。
    """
    global _langfuse_handler, _langfuse_checked
    if _langfuse_checked:
        return _langfuse_handler
    _langfuse_checked = True
    try:
        import os
        if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
            return None
        from langfuse import Langfuse
        langfuse = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=os.getenv("LANGFUSE_HOST", "http://localhost:3000"),
        )
        from langfuse.callback import CallbackHandler
        _langfuse_handler = CallbackHandler(langfuse=langfuse)
    except Exception:
        _langfuse_handler = None
    return _langfuse_handler
