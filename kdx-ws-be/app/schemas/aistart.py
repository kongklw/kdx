from typing import Optional

from pydantic import BaseModel


class AiAskRequest(BaseModel):
    """POST /ai/ask 请求体 (对齐 aistart.views.OpenAIView)"""
    content: Optional[str] = None
    thread_id: Optional[str] = None


class AiAskData(BaseModel):
    msg: str
    thread_id: str


class AiAskResponse(BaseModel):
    code: int
    data: Optional[AiAskData] = None
    msg: str
