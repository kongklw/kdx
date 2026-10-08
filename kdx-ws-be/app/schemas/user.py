from typing import Any, Optional

from pydantic import BaseModel


class ApiResponse(BaseModel):
    """对齐 DRF 视图的通用响应结构: {"code", "data", "msg"}"""
    code: int
    msg: Optional[str] = None
    data: Optional[Any] = None


class TokenObtainRequest(BaseModel):
    """POST /token/ 请求体 (对齐 simplejwt TokenObtainPairView)"""
    username: str
    password: str


class TokenObtainResponse(BaseModel):
    access: str
    refresh: str


class TokenRefreshRequest(BaseModel):
    """POST /token/refresh/ 请求体"""
    refresh: str


class TokenRefreshResponse(BaseModel):
    access: str


class UserLoginRequest(BaseModel):
    """POST /user/login 请求体 (username 字段兼容手机号登录)"""
    username: Optional[str] = None
    password: Optional[str] = None


class UserInfoData(BaseModel):
    """GET /user/info 返回的 data (与 Django UserInfo 视图字段一致)"""
    id: int
    roles: list
    introduction: str
    avatar: str
    name: str
