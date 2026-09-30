"""WebSocket 准入控制: Origin 校验 + token 提取 + JWT 验签。

所有 WS 接口复用; 在 accept 之前完成, 失败即 close, 不占连接资源。
"""
from typing import Optional

from fastapi import WebSocket
from loguru import logger

from ..config import Settings
from ..security import (
    extract_token_from_cookie,
    extract_token_from_headers,
    verify_jwt,
)
from .config import WSConfig
from .protocol import CloseCode


def extract_token(ws: WebSocket) -> Optional[str]:
    """三种提取方式 (优先级): query.token → Authorization: Bearer → Cookie。"""
    token = ws.query_params.get("token")
    if not token:
        token = extract_token_from_headers(ws.headers.get("authorization"))
    if not token:
        token = extract_token_from_cookie(ws.headers.get("cookie"))
    return token


def check_origin(ws: WebSocket, config: WSConfig) -> bool:
    """CSWSH (跨站 WebSocket 劫持) 防护: Origin 须在白名单内。

    - 未配置白名单 → 不校验 (开发环境 / 内网)
    - 客户端无 Origin 头 → 放行 (App/小程序等非浏览器客户端, 不受 CSWSH 约束)
    """
    if not config.allowed_origins:
        return True
    origin = ws.headers.get("origin")
    if not origin:
        return True
    return origin in config.allowed_origins


async def authenticate(ws: WebSocket, settings: Settings, config: WSConfig) -> Optional[int]:
    """准入: Origin → token → JWT。成功返回 user_id; 失败已 close 并返回 None。

    统一在此处完成所有 accept 前的拒绝逻辑, 接口层只需判断返回值。
    """
    if not check_origin(ws, config):
        await ws.close(code=CloseCode.POLICY_VIOLATION, reason="origin not allowed")
        logger.warning(f"[ws] rejected: bad origin={ws.headers.get('origin')}")
        return None

    token = extract_token(ws)
    if not token:
        await ws.close(code=CloseCode.AUTH_FAILED, reason="missing token")
        logger.warning("[ws] rejected: no token")
        return None

    try:
        user = verify_jwt(token, settings)
    except Exception as e:
        await ws.close(code=CloseCode.AUTH_FAILED, reason=f"invalid token: {e}")
        logger.warning(f"[ws] rejected: invalid token - {e}")
        return None

    user_id = user.get("user_id")
    if user_id is None:
        await ws.close(code=CloseCode.AUTH_FAILED, reason="token without user_id")
        return None
    return int(user_id)
