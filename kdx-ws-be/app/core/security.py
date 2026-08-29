import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional

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


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


# HMAC-SHA 族: JWT alg → hashlib 摘要算法
_HS_DIGEST = {
    "HS256": hashlib.sha256,
    "HS384": hashlib.sha384,
    "HS512": hashlib.sha512,
}


def verify_jwt(token: str, settings: Settings) -> Dict[str, Any]:
    """校验 JWT (HS256 族, 兼容 Django simplejwt 签发的 token)

    说明: 当前环境安装的是老 jwt==1.4.0 包 (与 PyJWT API 不兼容, 无顶层
    jwt.decode), 因此用标准库手写验签, 避开依赖冲突。
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("invalid token format")

    header_b64, payload_b64, sig_b64 = parts
    header = json.loads(_b64url_decode(header_b64))
    alg = header.get("alg", "")

    digest = _HS_DIGEST.get(alg)
    if not digest:
        raise ValueError(f"unsupported algorithm: {alg or 'missing'}")
    if alg != settings.jwt_algorithm:
        raise ValueError(f"algorithm mismatch: {alg} != {settings.jwt_algorithm}")

    signing_input = f"{header_b64}.{payload_b64}".encode()
    expected = hmac.new(
        settings.secret_key.encode(), signing_input, digest
    ).digest()
    if not hmac.compare_digest(expected, _b64url_decode(sig_b64)):
        raise ValueError("signature verification failed")

    payload = json.loads(_b64url_decode(payload_b64))

    exp = payload.get("exp")
    if exp is not None and time.time() > float(exp):
        raise ValueError("token expired")

    return payload
