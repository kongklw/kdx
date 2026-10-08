"""聊天历史持久化服务。

Redis list 存储, 降级进程内列表; 复用 resilience.py 的连接模式。
"""
import json
import os
import time
from typing import Any, Dict, List, Optional


class ChatHistoryService:
    """用户聊天历史读写, 按 user_id 隔离, TTL 7 天。"""

    _instance: Optional["ChatHistoryService"] = None

    @classmethod
    def get_instance(cls) -> "ChatHistoryService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._redis_url = os.getenv("REDIS_URL") or os.getenv("RATE_LIMIT_REDIS") or "redis://localhost:6379/0"
        self._redis = None        # aioredis 客户端 (False = 降级)
        self._memory: Dict[str, List[dict]] = {}  # 降级: user_id -> [msg, ...]
        self._TTL = 7 * 24 * 3600
        self._MAX = 500           # 每用户最多保留 500 条

    async def _get_redis(self):
        if self._redis is not None:
            return self._redis if self._redis is not False else None
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
            await self._redis.ping()
        except Exception:
            self._redis = False
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
