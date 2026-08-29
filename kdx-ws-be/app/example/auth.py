"""
鉴权 (Authentication & Authorization)
=======================================

核心概念：
  Agent 系统的鉴权分两层：
  1. Authentication（认证）：你是谁？—— JWT Token 校验用户身份
  2. Authorization（授权）：你能做什么？—— RBAC 角色权限控制工具访问

  在 Agent 系统中的特殊性：
  - WebSocket 连接需要鉴权（不能像 HTTP 那样每次带 header）
  - 工具调用需要鉴权（不同角色可调用不同工具）
  - Agent 之间通信需要鉴权（防止 Agent 越权调用）

面试话术：
  "我们的鉴权分三层：
   第一层是连接级鉴权——WebSocket 握手时校验 JWT Token，
   支持 query/header/cookie 三种传参方式，不通过直接 close(4401)。
   第二层是工具级鉴权——Agent 调用工具时检查用户角色是否有权限，
   比如 prescribe_medication 工具只有 doctor 角色能调用。
   第三层是数据级鉴权——查询结果按 user_id 过滤，确保用户只能看到自己的数据。"
"""

import base64
import hmac
import hashlib
import json
import time
import asyncio
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Set
from enum import Enum


# ──────────────────────────────────────────────
# 轻量 JWT 实现（不依赖外部库，面试 demo 用）
# ──────────────────────────────────────────────

class SimpleJWT:
    """轻量 JWT：Header.Payload.Signature，使用 HMAC-SHA256"""

    @staticmethod
    def encode(payload: Dict, secret: str) -> str:
        header = {"alg": "HS256", "typ": "JWT"}
        header_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=").decode()
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        signing_input = f"{header_b64}.{payload_b64}"
        signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
        sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
        return f"{signing_input}.{sig_b64}"

    @staticmethod
    def decode(token: str, secret: str) -> Dict:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Invalid token format")
        header_b64, payload_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}"
        expected_sig = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
        expected_sig_b64 = base64.urlsafe_b64encode(expected_sig).rstrip(b"=").decode()
        if not hmac.compare_digest(sig_b64, expected_sig_b64):
            raise ValueError("Invalid signature")
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
        if "exp" in payload and payload["exp"] < time.time():
            raise ValueError("Token expired")
        return payload


# ──────────────────────────────────────────────
# 角色定义
# ──────────────────────────────────────────────

class Role(Enum):
    USER = "user"          # 普通用户
    DOCTOR = "doctor"      # 医生
    ADMIN = "admin"        # 管理员


# 角色层级（高角色继承低角色的权限）
ROLE_HIERARCHY: Dict[Role, int] = {
    Role.USER: 0,
    Role.DOCTOR: 1,
    Role.ADMIN: 2,
}


# ──────────────────────────────────────────────
# JWT 认证
# ──────────────────────────────────────────────

class JWTAuth:
    """
    JWT 认证器

    职责：
    1. 签发 Token（登录时）
    2. 验证 Token（每次请求）
    3. 提取用户信息（user_id, role）
    """

    def __init__(self, secret_key: str, algorithm: str = "HS256"):
        self._secret = secret_key

    def create_token(
        self,
        user_id: str,
        role: Role,
        expires_in: int = 3600,
    ) -> str:
        """签发 JWT Token"""
        payload = {
            "user_id": user_id,
            "role": role.value,
            "iat": int(time.time()),
            "exp": int(time.time()) + expires_in,
        }
        return SimpleJWT.encode(payload, self._secret)

    def verify_token(self, token: str) -> Dict[str, Any]:
        """
        验证 Token

        返回 payload（含 user_id, role）
        验证失败抛异常（签名无效 / 过期）
        """
        return SimpleJWT.decode(token, self._secret)

    @staticmethod
    def extract_token_from_query(query_params: Dict) -> Optional[str]:
        """从 query 参数提取 token"""
        return query_params.get("token")

    @staticmethod
    def extract_token_from_header(authorization: Optional[str]) -> Optional[str]:
        """从 Authorization header 提取 token"""
        if not authorization:
            return None
        if authorization.startswith("Bearer "):
            return authorization[7:]
        return authorization

    @staticmethod
    def extract_token_from_cookie(cookie_header: Optional[str]) -> Optional[str]:
        """从 Cookie 提取 token"""
        if not cookie_header:
            return None
        for item in cookie_header.split(";"):
            item = item.strip()
            if item.startswith("token="):
                return item[6:]
        return None


# ──────────────────────────────────────────────
# 工具级鉴权
# ──────────────────────────────────────────────

@dataclass
class ToolPermission:
    """工具权限定义"""
    tool_name: str
    required_role: Role       # 调用此工具所需最低角色
    description: str = ""


class AuthorizationManager:
    """
    授权管理器

    基于 RBAC（Role-Based Access Control）做工具级权限控制
    """

    def __init__(self):
        self._permissions: Dict[str, ToolPermission] = {}

    def register_permission(self, perm: ToolPermission):
        """注册工具权限"""
        self._permissions[perm.tool_name] = perm

    def check_permission(self, role: Role, tool_name: str) -> bool:
        """检查角色是否有权限调用工具"""
        perm = self._permissions.get(tool_name)
        if perm is None:
            # 未注册权限的工具默认允许所有角色调用
            return True
        user_level = ROLE_HIERARCHY.get(role, 0)
        required_level = ROLE_HIERARCHY.get(perm.required_role, 0)
        return user_level >= required_level

    def get_allowed_tools(self, role: Role) -> List[str]:
        """获取该角色可调用的所有工具"""
        return [
            name for name, perm in self._permissions.items()
            if self.check_permission(role, name)
        ]


# ──────────────────────────────────────────────
# Agent 鉴权中间件
# ──────────────────────────────────────────────

class AuthMiddleware:
    """
    Agent 鉴权中间件

    在 Agent 执行前拦截，做三层校验：
    1. 连接级：JWT Token 是否有效
    2. 工具级：用户角色是否能调用该工具
    3. 数据级：用户只能操作自己的数据
    """

    def __init__(self, jwt_auth: JWTAuth, auth_manager: AuthorizationManager):
        self._jwt = jwt_auth
        self._auth_manager = auth_manager
        self._auth_log: List[Dict] = []

    def authenticate(self, token: str) -> Dict[str, Any]:
        """认证：验证 Token，返回用户信息"""
        try:
            payload = self._jwt.verify_token(token)
            self._auth_log.append({
                "user_id": payload.get("user_id"),
                "action": "authenticate",
                "success": True,
            })
            return payload
        except Exception as e:
            self._auth_log.append({
                "action": "authenticate",
                "success": False,
                "error": str(e),
            })
            raise PermissionError(f"Token 验证失败: {e}")

    def authorize_tool_call(
        self,
        role: Role,
        tool_name: str,
    ) -> bool:
        """授权：检查角色是否有权限调用工具"""
        allowed = self._auth_manager.check_permission(role, tool_name)
        self._auth_log.append({
            "tool": tool_name,
            "role": role.value,
            "action": "authorize_tool",
            "success": allowed,
        })
        if not allowed:
            raise PermissionError(
                f"权限不足: 角色 '{role.value}' 无法调用工具 '{tool_name}'"
            )
        return True

    def authorize_data_access(
        self,
        user_id: str,
        target_user_id: str,
    ) -> bool:
        """数据级鉴权：确保用户只能访问自己的数据"""
        allowed = (user_id == target_user_id)
        if not allowed:
            raise PermissionError(
                f"数据访问被拒绝: 用户 '{user_id}' 试图访问用户 '{target_user_id}' 的数据"
            )
        return True


# ──────────────────────────────────────────────
# WebSocket 鉴权流程（模拟）
# ──────────────────────────────────────────────

async def websocket_auth_flow(
    token: str,
    auth_middleware: AuthMiddleware,
) -> Dict[str, Any]:
    """
    WebSocket 连接鉴权流程

    对应项目中的 voice_agent_langchain.py:
      token = ws.query_params.get("token")
      ...
      user = verify_jwt(token, settings)
    """
    # Step 1: 认证（验证 Token）
    try:
        user = auth_middleware.authenticate(token)
        print(f"  [Auth] 认证成功: user_id={user['user_id']}, role={user['role']}")
        return user
    except PermissionError as e:
        print(f"  [Auth] 认证失败: {e}")
        # ws.close(code=4401, reason="invalid token")
        raise


async def tool_call_auth_flow(
    user: Dict[str, Any],
    tool_name: str,
    auth_middleware: AuthMiddleware,
):
    """工具调用鉴权流程"""
    role = Role(user.get("role", "user"))
    try:
        auth_middleware.authorize_tool_call(role, tool_name)
        print(f"  [Auth] 工具授权通过: {tool_name} (role={role.value})")
    except PermissionError as e:
        print(f"  [Auth] 工具授权拒绝: {e}")
        raise


# ──────────────────────────────────────────────
# 运行示例
# ──────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("鉴权 Demo（认证 + 授权）")
    print("=" * 60)

    # 初始化
    jwt_auth = JWTAuth(secret_key="my-secret-key")
    auth_manager = AuthorizationManager()
    auth_manager.register_permission(ToolPermission("query_vaccine", Role.USER, "查询疫苗"))
    auth_manager.register_permission(ToolPermission("book_appointment", Role.USER, "预约挂号"))
    auth_manager.register_permission(ToolPermission("prescribe_medication", Role.DOCTOR, "开处方"))
    auth_manager.register_permission(ToolPermission("manage_system", Role.ADMIN, "系统管理"))
    middleware = AuthMiddleware(jwt_auth, auth_manager)

    # 签发不同角色的 Token
    user_token = jwt_auth.create_token("user_001", Role.USER)
    doctor_token = jwt_auth.create_token("doctor_001", Role.DOCTOR)
    admin_token = jwt_auth.create_token("admin_001", Role.ADMIN)

    # 1. 普通 Token 提取
    print("\n1. Token 提取方式:")
    print(f"  从 query: token={JWTAuth.extract_token_from_query({'token': user_token})[:20]}...")
    print(f"  从 header: token={JWTAuth.extract_token_from_header(f'Bearer {user_token}')[:20]}...")
    print(f"  从 cookie: token={JWTAuth.extract_token_from_cookie(f'token={user_token}')[:20]}...")

    # 2. WebSocket 鉴权
    print("\n2. WebSocket 连接鉴权:")
    user = await websocket_auth_flow(user_token, middleware)
    doctor = await websocket_auth_flow(doctor_token, middleware)

    # 3. 工具级鉴权
    print("\n3. 工具调用鉴权:")
    # user 调用 query_vaccine → 通过
    await tool_call_auth_flow(user, "query_vaccine", middleware)
    # user 调用 prescribe_medication → 拒绝
    try:
        await tool_call_auth_flow(user, "prescribe_medication", middleware)
    except PermissionError:
        pass
    # doctor 调用 prescribe_medication → 通过
    await tool_call_auth_flow(doctor, "prescribe_medication", middleware)

    # 4. 数据级鉴权
    print("\n4. 数据级鉴权:")
    middleware.authorize_data_access("user_001", "user_001")  # 自己访问自己
    print("  user_001 访问 user_001 数据 → 通过")
    try:
        middleware.authorize_data_access("user_001", "user_002")  # 访问别人
    except PermissionError:
        print("  user_001 访问 user_002 数据 → 拒绝")

    # 5. 各角色可见工具
    print("\n5. 各角色可用工具:")
    for role in [Role.USER, Role.DOCTOR, Role.ADMIN]:
        tools = auth_manager.get_allowed_tools(role)
        print(f"  {role.value}: {tools}")

    # 6. Token 过期
    print("\n6. Token 过期:")
    expired_token = jwt_auth.create_token("user_001", Role.USER, expires_in=-1)
    try:
        await websocket_auth_flow(expired_token, middleware)
    except PermissionError:
        print("  过期 Token 被正确拒绝")


if __name__ == "__main__":
    asyncio.run(main())
