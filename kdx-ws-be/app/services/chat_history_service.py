"""聊天历史持久化服务。

Redis list 存储, 降级进程内列表; 复用 resilience.py 的连接模式。
"""
import json
import time
from typing import Any, Dict, List, Optional


class ChatHistoryService:
    """用户聊天历史读写, 按 user_id 隔离, TTL 7 天。

    首次 get_instance(redis_url) 时传入 settings.redis_url;
    后续无参调用返回已缓存的单例。
    """

    _instance: Optional["ChatHistoryService"] = None

    @classmethod
    def get_instance(cls, redis_url: str = None) -> "ChatHistoryService":
        if cls._instance is None:
            cls._instance = cls(redis_url)
        return cls._instance

    def __init__(self, redis_url: str = None):
        # 必须由调用方传入 settings.redis_url; 兜底 localhost 仅用于本地开发
        self._redis_url = redis_url or "redis://localhost:6379/0"
        self._redis = None        # aioredis 客户端 (None=未初始化, False=降级)
        self._memory: Dict[str, List[dict]] = {}  # 降级: user_id -> [msg, ...]
        self._TTL = 7 * 24 * 3600
        self._MAX = 500           # 每用户最多保留 500 条
        self._retry_at = 0.0      # 下次允许重连 Redis 的时间戳 (0=立即可试)

    async def _get_redis(self):
        # 已初始化: 直接返回 (False=降级中)
        if self._redis is not None:
            if self._redis is False:
                # 降级中, 但到重试时间则重新尝试连接
                if time.time() < self._retry_at:
                    return None
                self._redis = None  # 重置, 走下方重连逻辑
            else:
                return self._redis
        # 首次连接或重试
        try:
            import redis.asyncio as aioredis
            client = aioredis.from_url(self._redis_url, decode_responses=True)
            await client.ping()
            self._redis = client
        except Exception:
            self._redis = False
            self._retry_at = time.time() + 30  # 30s 后允许重试
        return self._redis if self._redis is not False else None

    def _key(self, user_id: int) -> str:
        return f"kdx:chat:{user_id}"

    async def save_message(self, user_id: int, msg: Dict[str, Any]) -> None:
        """追加一条消息到用户历史 (RPUSH + TTL 续期 + 截断)"""
        msg.setdefault("created_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
        raw = json.dumps(msg, ensure_ascii=False, default=str)
        r = await self._get_redis()
        if r:
            try:
                pipe = r.pipeline()
                pipe.rpush(self._key(user_id), raw)
                pipe.expire(self._key(user_id), self._TTL)
                pipe.ltrim(self._key(user_id), -self._MAX, -1)
                await pipe.execute()
                return
            except Exception:
                pass
        # 降级: 进程内
        lst = self._memory.setdefault(str(user_id), [])
        lst.append(msg)
        if len(lst) > self._MAX:
            self._memory[str(user_id)] = lst[-self._MAX:]

    async def get_recent(self, user_id: int, limit: int = 50) -> List[dict]:
        """返回最近 limit 条消息 (时间正序, 最旧在前)"""
        r = await self._get_redis()
        if r:
            try:
                raws = await r.lrange(self._key(user_id), -limit, -1)
                return [json.loads(x) for x in raws]
            except Exception:
                pass
        lst = self._memory.get(str(user_id), [])
        return lst[-limit:]
