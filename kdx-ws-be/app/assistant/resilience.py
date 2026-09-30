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
    幂等管理器 (落地 example/idempotent.py)

    生产版: 优先 Redis SETNX + TTL (跨进程生效); Redis 不可用时回退内存。
    覆盖场景: 前端重试/用户双击导致的同一 request_id 重复提交。
    """

    def __init__(self, ttl_seconds: int = 1800, max_entries: int = 256,
                 redis_url: Optional[str] = None):
        self._ttl = ttl_seconds
        self._max = max_entries
        self._results: Dict[str, Dict[str, Any]] = {}  # 内存回退
        self._redis = None
        self._redis_url = redis_url

    async def _get_redis(self):
        """懒初始化 Redis 连接 (失败则永久回退内存)"""
        if self._redis is not None:
            return self._redis if self._redis is not False else None
        if not self._redis_url:
            self._redis = False
            return None
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
            await self._redis.ping()
        except Exception:
            self._redis = False
        return self._redis if self._redis is not False else None

    @staticmethod
    def tool_key(request_id: str, tool_name: str, args: Dict[str, Any]) -> str:
        raw = json.dumps({"rid": request_id, "tool": tool_name, "args": args},
                         sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    async def get_cached(self, key: str) -> Optional[Dict[str, Any]]:
        """查缓存: 优先 Redis, 回退内存"""
        # Redis 路径
        r = await self._get_redis()
        if r:
            try:
                cached = await r.get(f"idem:{key}")
                if cached:
                    return json.loads(cached)
            except Exception:
                pass
        # 内存回退
        item = self._results.get(key)
        if not item:
            return None
        if time.time() - item["ts"] > self._ttl:
            del self._results[key]
            return None
        return item["result"]

    async def save(self, key: str, result: Dict[str, Any]):
        """存缓存: 优先 Redis SETNX, 回退内存"""
        payload = json.dumps(result, ensure_ascii=False, default=str)
        # Redis 路径
        r = await self._get_redis()
        if r:
            try:
                await r.set(f"idem:{key}", payload, nx=True, ex=self._ttl)
                return
            except Exception:
                pass
        # 内存回退
        if len(self._results) >= self._max:
            keys = sorted(self._results.keys(), key=lambda k: self._results[k]["ts"])
            for k in keys[: self._max // 2]:
                del self._results[k]
        self._results[key] = {"ts": time.time(), "result": result}


class RateLimiter:
    """
    速率限制器 (滑动窗口, Redis-backed)

    生产版: Redis ZSET 滑动窗口 (跨进程生效, 精确到秒)
    降级:   Redis 不可用时回退进程内滑动窗口 (单实例仍有效)
    """

    def __init__(self, redis_url: Optional[str] = None,
                 max_calls: int = 30, window_seconds: int = 60):
        self._redis_url = redis_url
        self._max_calls = max_calls
        self._window = window_seconds
        self._redis = None
        self._memory: Dict[str, list] = {}   # key -> [timestamps]

    async def _get_redis(self):
        if self._redis is not None:
            return self._redis if self._redis is not False else None
        if not self._redis_url:
            self._redis = False
            return None
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
            await self._redis.ping()
        except Exception:
            self._redis = False
        return self._redis if self._redis is not False else None

    async def allow(self, key: str) -> bool:
        """判断 key (如 user:{id}) 是否允许通过限流"""
        now = time.time()
        r = await self._get_redis()
        if r:
            try:
                import uuid
                zkey = f"rl:{key}"
                member = str(uuid.uuid4())
                pipe = r.pipeline()
                pipe.zremrangebyscore(zkey, 0, now - self._window)
                pipe.zadd(zkey, {member: now})
                pipe.zcard(zkey)
                pipe.expire(zkey, self._window)
                await pipe.execute()
                count = await r.zcard(zkey)
                return count <= self._max_calls
            except Exception:
                pass
        # 内存回退 (滑动窗口)
        ts_list = self._memory.setdefault(key, [])
        ts_list[:] = [t for t in ts_list if t > now - self._window]
        if len(ts_list) >= self._max_calls:
            return False
        ts_list.append(now)
        return True
