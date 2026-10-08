from typing import Optional

from fastapi import HTTPException, Request

from ..core.config import Settings
from ..core.security import extract_token_from_headers, verify_jwt


def resolve_user_id(request: Request, settings: Settings) -> str:
    token = extract_token_from_headers(request.headers.get("authorization"))
    if token:
        try:
            payload = verify_jwt(token, settings)
            uid = payload.get("user_id") or payload.get("sub")
            if uid is not None:
                return str(uid)
        except Exception:
            pass

    uid_qs: Optional[str] = request.query_params.get("user_id")
    if uid_qs:
        return uid_qs
    uid_header = request.headers.get("x-user-id")
    if uid_header:
        return uid_header
    return "anon"


def require_user_id(request: Request, settings: Settings) -> int:
    """强鉴权: 仅接受有效 Bearer JWT (语义等同 Django DRF IsAuthenticated)

    兼容 Django simplejwt 签发的 token (user_id claim); 校验失败返回 401,
    响应体形状与 DRF 一致: {"detail": "..."}
    """
    token = extract_token_from_headers(request.headers.get("authorization"))
    if not token:
        raise HTTPException(status_code=401, detail="Authentication credentials were not provided.")
    try:
        payload = verify_jwt(token, settings)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    uid = payload.get("user_id") or payload.get("sub")
    if uid is None:
        raise HTTPException(status_code=401, detail="Token missing user_id claim.")
    try:
        return int(uid)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid user_id claim.")

