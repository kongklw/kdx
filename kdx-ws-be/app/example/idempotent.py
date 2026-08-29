"""
幂等 (Idempotency)
=====================

核心概念：
  幂等 = 同一操作执行多次，结果与执行一次相同。
  在 Agent 系统中，网络重试、用户重复点击、消息重复投递都会导致重复请求。
  幂等保证这些重复不会造成副作用（如重复扣款、重复预约）。

实现方式：
  1. 请求 ID + 去重表：每个请求带唯一 request_id，处理前查表是否已处理
  2. 状态前置检查：操作前检查业务状态，只有合法状态才执行
  3. 结果缓存：相同 request_id 直接返回缓存结果

面试话术：
  "我们的幂等设计采用 request_id + Redis 去重表。
   客户端每次请求携带 UUID 作为 request_id，服务端处理前用 SETNX 写入 Redis，
   如果已存在说明是重复请求，直接返回之前的结果。
   同时结合状态前置检查——比如预约前先检查是否已预约，
   双重保证不会产生重复数据。TTL 设置为 30 分钟，自动清理过期记录。"
"""

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Callable, List


# ──────────────────────────────────────────────
# 幂等管理器
# ──────────────────────────────────────────────

@dataclass
class CachedResult:
    """缓存的处理结果"""
    request_id: str
    result: Any
    status: str               # success / error
    created_at: float


class IdempotencyManager:
    """
    幂等管理器

    核心机制：
    1. 客户端携带唯一 request_id
    2. 处理前检查 request_id 是否已处理过
    3. 已处理 → 返回缓存结果
    4. 未处理 → 执行，缓存结果，设置 TTL

    对应 Redis 实现：
      SETNX key value EX ttl   → 如果 key 不存在则设置，TTL 过期自动清理
    """

    def __init__(self, ttl_seconds: int = 1800):
        self._cache: Dict[str, CachedResult] = {}  # 实际用 Redis
        self._processing: Set[str] = set()         # 正在处理中的请求
        self._ttl = ttl_seconds
        self._lock = asyncio.Lock()

    async def execute_idempotent(
        self,
        request_id: str,
        handler: Callable,
        *args,
        **kwargs,
    ) -> Any:
        """
        幂等执行

        1. 检查是否已缓存（命中 → 直接返回）
        2. 检查是否正在处理中（命中 → 等待结果）
        3. 执行 handler，缓存结果
        """
        async with self._lock:
            # 清理过期缓存
            self._cleanup_expired()

            # 命中缓存
            if request_id in self._cache:
                cached = self._cache[request_id]
                print(f"  [Idempotent] 命中缓存: {request_id} → {cached.result}")
                return cached.result

            # 正在处理中
            if request_id in self._processing:
                print(f"  [Idempotent] 重复请求(处理中): {request_id}")
                return {"error": "duplicate_request", "message": "请求正在处理中"}

            # 标记为处理中
            self._processing.add(request_id)

        # 执行 handler（不加锁，避免阻塞其他请求）
        try:
            result = await handler(*args, **kwargs)
            status = "success"
        except Exception as e:
            result = {"error": str(e)}
            status = "error"

        async with self._lock:
            self._processing.discard(request_id)
            # 缓存结果
            self._cache[request_id] = CachedResult(
                request_id=request_id,
                result=result,
                status=status,
                created_at=time.time(),
            )

        return result

    def _cleanup_expired(self):
        """清理过期缓存"""
        now = time.time()
        expired = [
            rid for rid, cached in self._cache.items()
            if now - cached.created_at > self._ttl
        ]
        for rid in expired:
            del self._cache[rid]

    def get_cache_info(self) -> Dict:
        """获取缓存统计"""
        return {
            "cached_count": len(self._cache),
            "processing_count": len(self._processing),
            "ttl_seconds": self._ttl,
        }


# ──────────────────────────────────────────────
# 状态前置检查（第二种幂等策略）
# ──────────────────────────────────────────────

class AppointmentService:
    """
    预约服务（状态前置检查幂等）

    即使没有 request_id，通过业务状态也能防止重复：
    - 已预约的不能重复预约
    - 已取消的可以重新预约
    """

    def __init__(self):
        self._appointments: Dict[str, Dict] = {}

    async def book_appointment(
        self,
        user_id: str,
        hospital: str,
        date: str,
    ) -> Dict:
        """预约挂号（状态前置检查）"""
        key = f"{user_id}_{hospital}_{date}"

        # 状态前置检查
        existing = self._appointments.get(key)
        if existing and existing["status"] == "booked":
            print(f"  [StateCheck] 重复预约被拦截: {key}")
            return existing  # 返回已存在的预约

        # 执行预约
        appointment = {
            "appointment_id": f"APT-{hash(key) % 100000}",
            "user_id": user_id,
            "hospital": hospital,
            "date": date,
            "status": "booked",
            "created_at": time.time(),
        }
        self._appointments[key] = appointment
        print(f"  [StateCheck] 预约成功: {key}")
        return appointment


# ──────────────────────────────────────────────
# 工具调用幂等
# ──────────────────────────────────────────────

async def mock_tool_call(tool_name: str, args: Dict) -> Dict:
    """模拟工具调用（带副作用）"""
    print(f"  [Tool] 执行 {tool_name}({args})")
    await asyncio.sleep(0.01)
    return {"success": True, "tool": tool_name, "result": "done"}


# ──────────────────────────────────────────────
# 运行示例
# ──────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("幂等 Demo（request_id 去重 + 状态前置检查）")
    print("=" * 60)

    # ── 方式一：request_id 去重 ──
    print("\n1. request_id 去重:")
    idem = IdempotencyManager(ttl_seconds=60)

    request_id = "REQ-001"
    # 第一次调用 → 正常执行
    print("\n  第一次调用:")
    result1 = await idem.execute_idempotent(
        request_id,
        mock_tool_call,
        "query_vaccine",
        {"vaccine_name": "乙肝"},
    )
    print(f"  结果: {result1}")

    # 第二次相同 request_id → 命中缓存
    print("\n  第二次调用（相同 request_id）:")
    result2 = await idem.execute_idempotent(
        request_id,
        mock_tool_call,
        "query_vaccine",
        {"vaccine_name": "乙肝"},
    )
    print(f"  结果: {result2}")

    # 第三次不同 request_id → 正常执行
    print("\n  第三次调用（不同 request_id）:")
    result3 = await idem.execute_idempotent(
        "REQ-002",
        mock_tool_call,
        "query_vaccine",
        {"vaccine_name": "乙肝"},
    )
    print(f"  结果: {result3}")

    # ── 方式二：状态前置检查 ──
    print(f"\n{'─' * 40}")
    print("2. 状态前置检查:")
    appt_service = AppointmentService()

    # 第一次预约 → 成功
    print("\n  第一次预约:")
    r1 = await appt_service.book_appointment("user_001", "北京儿童医院", "2026-09-01")
    print(f"  结果: {r1}")

    # 第二次预约（相同参数） → 被拦截
    print("\n  第二次预约（重复）:")
    r2 = await appt_service.book_appointment("user_001", "北京儿童医院", "2026-09-01")
    print(f"  结果: {r2}")

    # ── 缓存统计 ──
    print(f"\n{'─' * 40}")
    print("3. 缓存统计:")
    print(f"  {idem.get_cache_info()}")


if __name__ == "__main__":
    asyncio.run(main())
