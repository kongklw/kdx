"""WebSocket 连接管理器: 全局/单用户并发限制 + 定向下发/广播。

单进程实现; 多进程部署需用 Redis (INCR/DECR 计数 + pub/sub 广播) 替换,
接口层调用方式不变 (符合依赖倒置, 实现可平滑替换)。
"""
import asyncio
from typing import Any, Dict, Set

from fastapi import WebSocket
from loguru import logger

from .config import WSConfig, get_ws_config


class ConnectionManager:
    """连接注册表 + 限流 + 推送能力。

    职责:
    - acquire/release: 维护连接集合与计数, 强制全局/单用户并发上限
    - send_to_user:    定向下发到某用户的所有连接 (Agent 事件推送场景)
    - broadcast:       全量广播 (系统通告场景)
    """

    def __init__(self, config: WSConfig) -> None:
        self._config = config
        self._all: Set[WebSocket] = set()
        self._by_user: Dict[int, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()  # 保护 check-then-add 的竞态

    @property
    def config(self) -> WSConfig:
        return self._config

    async def acquire(self, ws: WebSocket, user_id: int) -> bool:
        """尝试注册连接; 超限则踢掉该用户最老的连接, 保证新请求能进。

        设计理由: 前端切 tab / 刷新页面 / 杀进程时, TCP FIN 可能不会立即到达,
        若严格超限即拒绝, 会导致用户被自己的僵尸连接锁死 (rejected: conn limit reached)。
        改为 LRU 淘汰 — 允许用户始终连上, 代价是最老的那个连接被 close。
        """
        async with self._lock:
            if len(self._all) >= self._config.max_connections:
                return False
            bucket = self._by_user.get(user_id)
            if bucket is not None and len(bucket) >= self._config.max_connections_per_user:
                # LRU: 踢掉最早的那个 (WebSocket 对象作为集合元素, 用 id() 排不靠谱,
                # 这里取任意一个即可 — 反正都是僵尸连接)
                oldest = next(iter(bucket))
                bucket.discard(oldest)
                self._all.discard(oldest)
                logger.warning(f"[ConnectionManager] evicted old ws for user={user_id}, id={id(oldest)}")
                try:
                    await oldest.close(code=1001, reason="evicted by new connection")
                except Exception:
                    pass
            self._all.add(ws)
            self._by_user.setdefault(user_id, set()).add(ws)
            return True

    async def release(self, ws: WebSocket, user_id: int) -> None:
        """注销连接 (幂等); finally 中调用, 保证计数不泄漏。"""
        async with self._lock:
            self._all.discard(ws)
            bucket = self._by_user.get(user_id)
            if bucket is not None:
                bucket.discard(ws)
                if not bucket:
                    self._by_user.pop(user_id, None)

    async def send_to_user(self, user_id: int, message: Dict[str, Any]) -> int:
        """定向下发到某用户全部连接; 顺带清理已失效连接, 返回成功数。"""
        bucket = self._by_user.get(user_id)
        if not bucket:
            return 0
        ok = 0
        for ws in list(bucket):
            try:
                await ws.send_json(message)
                ok += 1
            except Exception:
                await self.release(ws, user_id)
        return ok

    async def broadcast(self, message: Dict[str, Any]) -> int:
        """全量广播, 返回成功数 (best-effort, 失败连接忽略, 由各自 release 清理)。"""
        ok = 0
        for ws in list(self._all):
            try:
                await ws.send_json(message)
                ok += 1
            except Exception:
                pass
        return ok

    @property
    def total(self) -> int:
        """当前活跃连接数 (监控/指标用)。"""
        return len(self._all)


# 进程级单例: 各 WS 接口共享同一份连接计数与下发能力
connection_manager = ConnectionManager(get_ws_config())
