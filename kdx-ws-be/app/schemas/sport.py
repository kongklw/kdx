from typing import Any, Optional

from pydantic import BaseModel


class SportItem(BaseModel):
    """对齐 DRF SportSerializer (fields = "__all__") 的字段结构, 外键以 user 名输出主键"""
    id: int
    user: Optional[int] = None
    name: str
    country: str
    popularity: Optional[int] = None


class SportCreateResponse(BaseModel):
    code: int
    msg: Optional[str] = None
    data: Optional[Any] = None


class SportListResponse(BaseModel):
    code: int
    msg: Optional[str] = None
    data: Optional[list] = None
