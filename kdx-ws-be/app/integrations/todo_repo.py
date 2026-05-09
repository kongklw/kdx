import json
import os
from typing import Dict, List, Optional, Protocol
from datetime import datetime, timezone

import redis

from ..core.config import Settings
from ..schemas.todo import TodoItem


class TodoRepository(Protocol):
    def list_items(self, user_id: str) -> List[TodoItem]:
        ...

    def get_item(self, user_id: str, todo_id: str) -> Optional[TodoItem]:
        ...

    def upsert_item(self, item: TodoItem) -> TodoItem:
        ...

    def delete_item(self, user_id: str, todo_id: str) -> bool:
        ...


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_item(data: Dict) -> TodoItem:
    return TodoItem.model_validate(data)


class InMemoryTodoRepository:
    def __init__(self) -> None:
        self._data: Dict[str, Dict[str, Dict]] = {}

    def list_items(self, user_id: str) -> List[TodoItem]:
        raw = list(self._data.get(user_id, {}).values())
        items = [_to_item(x) for x in raw]
        items.sort(key=lambda x: x.created_at, reverse=True)
        return items

    def get_item(self, user_id: str, todo_id: str) -> Optional[TodoItem]:
        raw = (self._data.get(user_id, {}) or {}).get(todo_id)
        return _to_item(raw) if raw else None

    def upsert_item(self, item: TodoItem) -> TodoItem:
        self._data.setdefault(item.user_id, {})[item.id] = item.model_dump(mode="json")
        return item

    def delete_item(self, user_id: str, todo_id: str) -> bool:
        bucket = self._data.get(user_id, {})
        if todo_id in bucket:
            del bucket[todo_id]
            return True
        return False


class RedisTodoRepository:
    def __init__(self, r: redis.Redis) -> None:
        self._r = r

    def _key(self, user_id: str) -> str:
        return f"todo:{user_id}"

    def list_items(self, user_id: str) -> List[TodoItem]:
        key = self._key(user_id)
        values = self._r.hvals(key)
        items: List[TodoItem] = []
        for v in values:
            try:
                items.append(_to_item(json.loads(v)))
            except Exception:
                continue
        items.sort(key=lambda x: x.created_at, reverse=True)
        return items

    def get_item(self, user_id: str, todo_id: str) -> Optional[TodoItem]:
        key = self._key(user_id)
        v = self._r.hget(key, todo_id)
        if not v:
            return None
        try:
            return _to_item(json.loads(v))
        except Exception:
            return None

    def upsert_item(self, item: TodoItem) -> TodoItem:
        key = self._key(item.user_id)
        self._r.hset(key, item.id, json.dumps(item.model_dump(mode="json"), ensure_ascii=False))
        self._r.expire(key, 60 * 60 * 24 * 180)
        return item

    def delete_item(self, user_id: str, todo_id: str) -> bool:
        key = self._key(user_id)
        removed = self._r.hdel(key, todo_id)
        return bool(removed)


def create_todo_repository(settings: Settings) -> TodoRepository:
    backend = (os.getenv("TODO_REPO") or "").lower().strip()
    if backend in {"redis", "cache"}:
        r = redis.Redis.from_url(settings.redis_url)
        try:
            r.ping()
            return RedisTodoRepository(r)
        except Exception:
            return InMemoryTodoRepository()
    return InMemoryTodoRepository()
