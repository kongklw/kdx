import base64
import hashlib
import hmac
import json
import secrets
import string
import time
import unicodedata
import uuid
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


# ===================== Django simplejwt 兼容: token 签发 =====================
# 对齐 kdx-be/kdemo/settings.py 的 SIMPLE_JWT 配置:
#   ACCESS_TOKEN_LIFETIME = timedelta(days=1)  -> 86400 秒
#   REFRESH_TOKEN_LIFETIME = timedelta(days=1) -> 86400 秒
#   ALGORITHM = "HS256", SIGNING_KEY = SECRET_KEY (目标项目 .env 已对齐)
ACCESS_TOKEN_LIFETIME_SECONDS = 86400
REFRESH_TOKEN_LIFETIME_SECONDS = 86400


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _create_token(user_id: int, settings: Settings, token_type: str, lifetime_seconds: int) -> str:
    """按 simplejwt 的 payload 结构手写 HS256 族签发 (与 verify_jwt 同风格)

    payload 对齐 rest_framework_simplejwt: {"token_type", "exp", "iat", "jti", "user_id"}
    """
    now = int(time.time())
    payload = {
        "token_type": token_type,
        "exp": now + lifetime_seconds,
        "iat": now,
        "jti": uuid.uuid4().hex,
        "user_id": int(user_id),
    }
    header = {"alg": settings.jwt_algorithm, "typ": "JWT"}
    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode()
    digest = _HS_DIGEST[settings.jwt_algorithm]
    signature = hmac.new(settings.secret_key.encode(), signing_input, digest).digest()
    return f"{header_b64}.{payload_b64}.{_b64url_encode(signature)}"


def create_access_token(user_id: int, settings: Settings, lifetime_seconds: int = ACCESS_TOKEN_LIFETIME_SECONDS) -> str:
    """签发 access token (与 Django simplejwt 签发的 token 互相可验)"""
    return _create_token(user_id, settings, "access", lifetime_seconds)


def create_refresh_token(user_id: int, settings: Settings, lifetime_seconds: int = REFRESH_TOKEN_LIFETIME_SECONDS) -> str:
    """签发 refresh token"""
    return _create_token(user_id, settings, "refresh", lifetime_seconds)


# ===================== Django 密码哈希 (pbkdf2_sha256) 兼容 =====================
# Django 3.2 默认迭代次数 (仅用于新哈希; 校验时以存量哈希中的迭代数为准)
PBKDF2_ITERATIONS = 260000
_SALT_CHARS = string.ascii_letters + string.digits


def make_django_password(password: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    """按 Django pbkdf2_sha256 格式生成密码哈希, 供注册接口写入 tb_users

    格式: pbkdf2_sha256$<iterations>$<salt>$<base64(hash)>
    """
    if not password:
        # Django set_unusable_password 的标记, check_password 恒为 False
        return "!"
    salt = "".join(secrets.choice(_SALT_CHARS) for _ in range(12))
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${base64.b64encode(digest).decode()}"


def verify_django_password(password: str, encoded: str) -> bool:
    """校验 Django 格式密码 (恒定时间比较), 兼容存量任意迭代次数的哈希"""
    try:
        algorithm, iterations, salt, hash_b64 = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
        expected = base64.b64decode(hash_b64)
        return hmac.compare_digest(digest, expected)
    except Exception:
        return False


def normalize_email(email: Optional[str]) -> str:
    """对齐 BaseUserManager.normalize_email: 仅将域名部分小写"""
    if not email or "@" not in email:
        return email or ""
    local, domain = email.rsplit("@", 1)
    return f"{local}@{domain.lower()}"


def normalize_username(username: str) -> str:
    """对齐 AbstractUserManager.normalize_username: NFKC 归一化"""
    return unicodedata.normalize("NFKC", username)
