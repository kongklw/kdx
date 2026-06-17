from typing import Any, Dict, Optional
import jwt
from .config import Settings


def extract_token_from_headers(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


def extract_token_from_cookie(cookie: Optional[str]) -> Optional[str]:
    """从 Cookie 中提取 token"""
    if not cookie:
        return None
    token_key = "Admin-Token"
    cookies = cookie.split(";")
    for c in cookies:
        parts = c.strip().split("=")
        if len(parts) == 2 and parts[0] == token_key:
            return parts[1]
    return None


def verify_jwt(token: str, settings: Settings) -> Dict[str, Any]:
    return jwt.decode(
        token,
        settings.secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"verify_aud": False},
    )
