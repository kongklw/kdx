"""
弹性层：熔断器 + 幂等管理器 (落地 example/circuit_breaker.py 与 example/idempotent.py)

- CircuitBreaker: 三态机 Closed → Open → Half-Open，保护 LLM 调用
- IdempotencyManager: request_id 去重，防止重复写入工具造成重复数据
"""

import asyncio
import time
import hashlib
import json
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Optional


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    pass


class CircuitBreaker:
    """
    三态熔断器

    - failure_threshold: 失败率阈值，超过则熔断
    - min_calls: 最小样本数
    - recovery_timeout: Open 持续多久进入 Half-Open
    - half_open_successes: 半开态连续成功 N 次后恢复 Closed
    """

    def __init__(
        self,
        name: str,
        failure_threshold: float = 0.5,
        min_calls: int = 4,
        recovery_timeout: float = 30.0,
        half_open_successes: int = 2,
    ):
        self.name = name
        self._failure_threshold = failure_threshold
        self._min_calls = min_calls
        self._recovery_timeout = recovery_timeout
        self._half_open_successes_needed = half_open_successes

        self._state = CircuitState.CLOSED
        self._total = 0
        self._failures = 0
        self._half_open_successes = 0
        self._last_state_change = time.time()
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_state_change > self._recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_successes = 0
                self._last_state_change = time.time()
        return self._state

    @property
    def is_open(self) -> bool:
        return self.state == CircuitState.OPEN

    async def record_success(self):
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_successes += 1
                if self._half_open_successes >= self._half_open_successes_needed:
                    self._state = CircuitState.CLOSED
                    self._total = 0
                    self._failures = 0
                    self._last_state_change = time.time()
            else:
                self._total += 1

    async def record_failure(self):
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                # 半开态试探失败 → 重新熔断
                self._state = CircuitState.OPEN
                self._last_state_change = time.time()
                return
            self._total += 1
            self._failures += 1
            if self._total >= self._min_calls:
                rate = self._failures / self._total
                if rate >= self._failure_threshold:
                    self._state = CircuitState.OPEN
                    self._last_state_change = time.time()

    def snapshot(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state.value,
            "total": self._total,
            "failures": self._failures,
        }


class LLMCircuitBreaker(CircuitBreaker):
    """包住 LLM 调用的熔断器：连续失败率超阈值后直接短路走降级"""

    async def call(self, func: Callable[..., Awaitable[Any]], *args, **kwargs) -> Any:
        if self.is_open:
            raise CircuitOpenError(f"circuit [{self.name}] is OPEN, call rejected")
        try:
            result = await func(*args, **kwargs)
            await self.record_success()
            return result
        except CircuitOpenError:
            raise
        except Exception:
            await self.record_failure()
            raise

    async def call_stream(self, func: Callable[..., Any], *args, **kwargs):
        """包装返回 async generator 的调用 (如 llm.astream 流式输出)

        完整迭代成功 → 记成功; 迭代中抛异常 → 记失败。
        调用方需用 `async for chunk in breaker.call_stream(llm.astream, msgs)` 消费。
        """
        if self.is_open:
            raise CircuitOpenError(f"circuit [{self.name}] is OPEN, call rejected")
        agen = func(*args, **kwargs)
        try:
            async for item in agen:
                yield item
        except CircuitOpenError:
            raise
        except Exception:
            await self.record_failure()
            raise
        else:
            await self.record_success()


class IdempotencyManager:
    """
    连接级幂等管理器 (落地 example/idempotent.py)

    生产环境应替换为 Redis SETNX + TTL；此处为单连接内存实现，
    覆盖场景：前端重试/用户双击导致的同一 request_id 重复提交。
    """

    def __init__(self, ttl_seconds: int = 1800, max_entries: int = 256):
        self._ttl = ttl_seconds
        self._max = max_entries
        self._results: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def tool_key(request_id: str, tool_name: str, args: Dict[str, Any]) -> str:
        raw = json.dumps({"rid": request_id, "tool": tool_name, "args": args},
                         sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get_cached(self, key: str) -> Optional[Dict[str, Any]]:
        item = self._results.get(key)
        if not item:
            return None
        if time.time() - item["ts"] > self._ttl:
            del self._results[key]
            return None
        return item["result"]

    def save(self, key: str, result: Dict[str, Any]):
        if len(self._results) >= self._max:  # 简单淘汰：清最旧一半
            keys = sorted(self._results.keys(), key=lambda k: self._results[k]["ts"])
            for k in keys[: self._max // 2]:
                del self._results[k]
        self._results[key] = {"ts": time.time(), "result": result}
