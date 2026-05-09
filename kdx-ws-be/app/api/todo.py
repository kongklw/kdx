from typing import List

from fastapi import APIRouter, HTTPException, Request

from ..core.config import Settings
from ..integrations.todo_repo import create_todo_repository
from ..schemas.todo import TodoCreateRequest, TodoDeleteResponse, TodoItem, TodoUpdateRequest
from ..services.todo_service import TodoService
from .deps import resolve_user_id


def create_todo_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/todo", tags=["todo"])
    repo = create_todo_repository(settings)
    service = TodoService(repo)

    @router.get("", response_model=List[TodoItem])
    async def list_todos(request: Request) -> List[TodoItem]:
        user_id = resolve_user_id(request, settings)
        return service.list_items(user_id)

    @router.post("", response_model=TodoItem)
    async def create_todo(request: Request, body: TodoCreateRequest) -> TodoItem:
        user_id = resolve_user_id(request, settings)
        return service.create_item(user_id, body)

    @router.patch("/{todo_id}", response_model=TodoItem)
    async def update_todo(todo_id: str, request: Request, body: TodoUpdateRequest) -> TodoItem:
        user_id = resolve_user_id(request, settings)
        try:
            return service.update_item(user_id, todo_id, body)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @router.patch("/{todo_id}/toggle", response_model=TodoItem)
    async def toggle_todo(todo_id: str, request: Request) -> TodoItem:
        user_id = resolve_user_id(request, settings)
        try:
            return service.toggle(user_id, todo_id)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @router.delete("/{todo_id}", response_model=TodoDeleteResponse)
    async def delete_todo(todo_id: str, request: Request) -> TodoDeleteResponse:
        user_id = resolve_user_id(request, settings)
        try:
            service.delete_item(user_id, todo_id)
            return TodoDeleteResponse(deleted=True)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))

    return router

