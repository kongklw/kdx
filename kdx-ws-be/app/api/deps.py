from typing import Optional

from fastapi import Request

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

