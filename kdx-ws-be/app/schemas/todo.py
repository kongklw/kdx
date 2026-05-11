from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class TodoCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class TodoUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    completed: Optional[bool] = None


class TodoItem(BaseModel):
    id: str
    user_id: str
    title: str
    completed: bool
    created_at: datetime
    updated_at: datetime


class TodoDeleteResponse(BaseModel):
    deleted: Literal[True]

