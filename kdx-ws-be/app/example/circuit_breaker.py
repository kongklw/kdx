"""
降级与熔断策略 (Degradation & Circuit Breaker)
=================================================

核心概念：
  Agent 系统依赖大量外部服务（LLM API、向量库、第三方接口），任何一个挂掉
  都可能拖垮整个系统。降级与熔断是保障高可用的关键。

  熔断器（Circuit Breaker）三态：
  - Closed（关闭态）：正常调用，统计失败率
  - Open（打开态）：失败率超阈值，直接拒绝请求（快速失败）
  - Half-Open（半开态）：超时后放行少量请求试探，成功则恢复，失败则继续熔断

  降级策略：
  - LLM 不可用 → 降级到规则引擎 / 模板回复
  - 向量库不可用 → 降级到关键词检索
  - 人脸服务不可用 → 降级到密码认证

面试话术：
  "我们的降级熔断基于三态机模型。
   对 LLM API 设置阈值：30秒窗口内失败率 >50% 触发熔断，
   熔断后请求不再打到 LLM，而是走降级策略——用模板回复或规则引擎兜底。
   30秒后进入半开态，放行 10% 流量试探，
   连续 3 次成功则恢复全量，任一失败则继续熔断。
   对 TTS 服务，我做了 fallback_model 切换——
   当 qwen3-tts-vd-2026 不可用时自动切到 qwen3-tts-vd-realtime-2026。"
"""

import asyncio
import time
import random
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Callable, List
from enum import Enum


# ──────────────────────────────────────────────
# 熔断器状态
# ──────────────────────────────────────────────

class CircuitState(Enum):
    CLOSED = "closed"          # 关闭态：正常调用
    OPEN = "open"              # 打开态：熔断中，快速失败
    HALF_OPEN = "half_open"   # 半开态：试探性放行


@dataclass
class CircuitStats:
    """熔断统计"""
    total_calls: int = 0
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float = 0.0
    last_state_change: float = 0.0
    half_open_attempts: int = 0
    half_open_successes: int = 0


# ──────────────────────────────────────────────
# 熔断器
# ──────────────────────────────────────────────

class CircuitBreaker:
    """
    熔断器

    参数：
    - failure_threshold: 失败率阈值（0~1），超过则熔断
    - min_calls: 最少调用次数（样本太小不做判断）
    - recovery_timeout: 熔断后多久进入半开态（秒）
    - half_open_max_attempts: 半开态最大试探次数
    - half_open_success_threshold: 半开态连续成功多少次才恢复
    """

    def __init__(
        self,
        name: str,
        failure_threshold: float = 0.5,
        min_calls: int = 10,
        recovery_timeout: float = 30.0,
        half_open_max_attempts: int = 3,
        half_open_success_threshold: int = 2,
    ):
        self.name = name
        self._state = CircuitState.CLOSED
        self._stats = CircuitStats()
        self._failure_threshold = failure_threshold
        self._min_calls = min_calls
        self._recovery_timeout = recovery_timeout
        self._half_open_max = half_open_max_attempts
        self._half_open_success = half_open_success_threshold
        self._lock = asyncio.Lock()
        self._state_log: List[Dict] = []

    @property
    def state(self) -> CircuitState:
        # 检查是否该从 OPEN → HALF_OPEN
        if self._state == CircuitState.OPEN:
            if time.time() - self._stats.last_state_change > self._recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._stats.half_open_attempts = 0
                self._stats.half_open_successes = 0
                self._stats.last_state_change = time.time()
                self._log("OPEN → HALF_OPEN")
        return self._state

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        通过熔断器调用函数

        1. CLOSED → 正常调用，统计成功率
        2. OPEN → 直接抛异常（快速失败）
        3. HALF_OPEN → 放行少量请求试探
        """
        current_state = self.state

        if current_state == CircuitState.OPEN:
            raise CircuitOpenError(
                f"熔断器 [{self.name}] 处于 OPEN 状态，请求被拒绝"
            )

        if current_state == CircuitState.HALF_OPEN:
            if self._stats.half_open_attempts >= self._half_open_max:
                raise CircuitOpenError(
                    f"熔断器 [{self.name}] 半开态试探次数已达上限"
                )
            self._stats.half_open_attempts += 1

        # 执行调用
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as e:
            await self._on_failure()
            raise

    async def _on_success(self):
        """调用成功"""
        async with self._lock:
            self._stats.success_count += 1
            self._stats.total_calls += 1

            if self._state == CircuitState.HALF_OPEN:
                self._stats.half_open_successes += 1
                if self._stats.half_open_successes >= self._half_open_success:
                    # 恢复
                    self._state = CircuitState.CLOSED
                    self._stats = CircuitStats()
                    self._stats.last_state_change = time.time()
                    self._log("HALF_OPEN → CLOSED (恢复)")

    async def _on_failure(self):
        """调用失败"""
        async with self._lock:
            self._stats.failure_count += 1
            self._stats.total_calls += 1
            self._stats.last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                # 半开态失败 → 重新熔断
                self._state = CircuitState.OPEN
                self._stats.last_state_change = time.time()
                self._log("HALF_OPEN → OPEN (试探失败)")

            elif self._state == CircuitState.CLOSED:
                # 关闭态：检查是否该熔断
                if self._stats.total_calls >= self._min_calls:
                    failure_rate = self._stats.failure_count / self._stats.total_calls
                    if failure_rate >= self._failure_threshold:
                        self._state = CircuitState.OPEN
                        self._stats.last_state_change = time.time()
                        self._log(
                            f"CLOSED → OPEN (失败率={failure_rate:.0%})"
                        )

    def _log(self, msg: str):
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "breaker": self.name,
            "event": msg,
        }
        self._state_log.append(entry)
        print(f"  [Breaker] {self.name}: {msg}")

    def get_state(self) -> Dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "total_calls": self._stats.total_calls,
            "failure_count": self._stats.failure_count,
            "success_count": self._stats.success_count,
        }


class CircuitOpenError(Exception):
    """熔断器打开异常"""
    pass


# ──────────────────────────────────────────────
# 降级策略
# ──────────────────────────────────────────────

class DegradationHandler:
    """
    降级处理器

    当主服务不可用时，按降级策略兜底：
    - LLM → 模板回复
    - 向量检索 → 关键词检索
    - TTS → 文本输出
    """

    @staticmethod
    async def llm_degradation(query: str) -> str:
        """LLM 降级：返回模板回复"""
        return f"【系统降级提示】AI 服务暂时不可用，请稍后重试。您的请求已记录：{query[:50]}"

    @staticmethod
    async def vector_search_degradation(query: str) -> List[Dict]:
        """向量检索降级：关键词匹配"""
        print("  [Degrade] 向量检索降级到关键词匹配")
        return [
            {"title": "婴幼儿疫苗接种指南", "source": "缓存", "content": "乙肝疫苗..."},
            {"title": "辅食添加建议", "source": "缓存", "content": "6月龄开始..."},
        ]

    @staticmethod
    async def tts_degradation(text: str) -> bytes:
        """TTS 降级：返回空音频"""
        print(f"  [Degrade] TTS 降级，仅返回文本: {text[:30]}...")
        return b""


# ──────────────────────────────────────────────
# 服务调用封装（熔断 + 降级）
# ──────────────────────────────────────────────

class ResilientCaller:
    """
    弹性调用器：熔断 + 降级 + 重试

    调用链：
    1. 熔断器检查 → OPEN 直接降级
    2. 调用服务 → 成功返回
    3. 调用失败 → 记录到熔断器 → 返回降级结果
    """

    def __init__(self):
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._degradation: Dict[str, Callable] = {}

    def register(
        self,
        service_name: str,
        breaker: CircuitBreaker,
        degradation: Optional[Callable] = None,
    ):
        self._breakers[service_name] = breaker
        if degradation:
            self._degradation[service_name] = degradation

    async def call(
        self,
        service_name: str,
        func: Callable,
        *args,
        **kwargs,
    ) -> Any:
        """弹性调用"""
        breaker = self._breakers.get(service_name)
        degrade = self._degradation.get(service_name)

        if breaker is None:
            return await func(*args, **kwargs)

        try:
            return await breaker.call(func, *args, **kwargs)
        except CircuitOpenError:
            # 熔断打开 → 降级
            print(f"  [Resilient] {service_name} 熔断中，执行降级")
            if degrade:
                return await degrade(*args, **kwargs)
            raise
        except Exception as e:
            # 调用失败 → 降级
            print(f"  [Resilient] {service_name} 调用失败({e})，执行降级")
            if degrade:
                return await degrade(*args, **kwargs)
            raise


# ──────────────────────────────────────────────
# 模拟服务
# ──────────────────────────────────────────────

call_count = 0

async def mock_llm_service(query: str) -> str:
    """模拟 LLM 服务（有概率失败）"""
    global call_count
    call_count += 1
    if call_count <= 5:
        # 前5次调用都失败
        raise ConnectionError("LLM API 不可用")
    return f"LLM 回复: {query}"


# ──────────────────────────────────────────────
# 运行示例
# ──────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("降级与熔断 Demo")
    print("=" * 60)

    # 初始化
    llm_breaker = CircuitBreaker(
        name="LLM-API",
        failure_threshold=0.5,
        min_calls=4,          # demo 用小值
        recovery_timeout=2.0, # 2秒后进入半开态
        half_open_max_attempts=3,
        half_open_success_threshold=2,
    )

    caller = ResilientCaller()
    caller.register(
        "LLM-API",
        llm_breaker,
        degradation=DegradationHandler.llm_degradation,
    )

    # 模拟连续调用
    print("\n1. 连续调用 LLM（前5次失败，触发熔断）:")
    for i in range(8):
        print(f"\n  第 {i+1} 次调用:")
        result = await caller.call("LLM-API", mock_llm_service, "乙肝疫苗怎么打？")
        print(f"  结果: {result}")
        state = llm_breaker.get_state()
        print(f"  熔断器状态: {state['state']} (total={state['total_calls']}, fail={state['failure_count']})")

        await asyncio.sleep(0.3)

    # 等待恢复超时后进入半开态
    print(f"\n2. 等待 {llm_breaker._recovery_timeout}秒后，熔断器自动进入半开态...")
    await asyncio.sleep(2.5)

    print("\n3. 半开态试探调用:")
    # 此时 call_count > 5，mock_llm_service 会成功
    for i in range(3):
        print(f"\n  试探第 {i+1} 次:")
        result = await caller.call("LLM-API", mock_llm_service, "疫苗查询")
        print(f"  结果: {result}")
        state = llm_breaker.get_state()
        print(f"  熔断器状态: {state['state']}")

    # 打印状态变更日志
    print(f"\n{'─' * 40}")
    print("熔断器状态变更日志:")
    for entry in llm_breaker._state_log:
        print(f"  {entry['time']} [{entry['breaker']}] {entry['event']}")


if __name__ == "__main__":
    asyncio.run(main())
