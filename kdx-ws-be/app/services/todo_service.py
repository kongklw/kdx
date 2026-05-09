from datetime import datetime, timezone
from typing import List
from uuid import uuid4

from ..integrations.todo_repo import TodoRepository
from ..schemas.todo import TodoCreateRequest, TodoItem, TodoUpdateRequest


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TodoService:
    def __init__(self, repo: TodoRepository) -> None:
        self._repo = repo

    def list_items(self, user_id: str) -> List[TodoItem]:
        return self._repo.list_items(user_id)

    def create_item(self, user_id: str, req: TodoCreateRequest) -> TodoItem:
        now = _utcnow()
        item = TodoItem(
            id=str(uuid4()),
            user_id=user_id,
            title=req.title.strip(),
            completed=False,
            created_at=now,
            updated_at=now,
        )
        return self._repo.upsert_item(item)

    def update_item(self, user_id: str, todo_id: str, req: TodoUpdateRequest) -> TodoItem:
        existing = self._repo.get_item(user_id, todo_id)
        if not existing:
            raise KeyError("todo not found")
        updated = existing.model_copy(deep=True)
        if req.title is not None:
            updated.title = req.title.strip()
        if req.completed is not None:
            updated.completed = bool(req.completed)
        updated.updated_at = _utcnow()
        return self._repo.upsert_item(updated)

    def toggle(self, user_id: str, todo_id: str) -> TodoItem:
        existing = self._repo.get_item(user_id, todo_id)
        if not existing:
            raise KeyError("todo not found")
        updated = existing.model_copy(deep=True)
        updated.completed = not bool(updated.completed)
        updated.updated_at = _utcnow()
        return self._repo.upsert_item(updated)

    def delete_item(self, user_id: str, todo_id: str) -> None:
        ok = self._repo.delete_item(user_id, todo_id)
        if not ok:
            raise KeyError("todo not found")

