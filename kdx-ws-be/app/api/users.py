"""users 应用端点迁移 (Django kdemo/urls.py 顶层 token 视图 + users/urls.py)

URL 与 Django 完全一致:
  POST /token/          -> simplejwt TokenObtainPairView (username+password -> access/refresh)
  POST /token/refresh/  -> simplejwt TokenRefreshView (refresh -> access)
  POST /user/signin     -> users.views.UserView (注册)
  POST /user/login      -> users.views.LoginView (登录, 返回 access)
  GET  /user/info       -> users.views.UserInfo (token 从 query 参数读取)
  POST /user/logout     -> users.views.Logout
"""
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..core.database import get_db
from ..core.security import (
    create_access_token,
    create_refresh_token,
    extract_token_from_headers,
    verify_jwt,
)
from ..schemas.user import (
    ApiResponse,
    TokenObtainRequest,
    TokenObtainResponse,
    TokenRefreshRequest,
    TokenRefreshResponse,
    UserLoginRequest,
)
from ..services.user_service import authenticate_user, create_user, get_user_by_id


def create_users_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["users"])

    def _user_id_from_bearer(request: Request) -> Optional[int]:
        """从 Authorization: Bearer 解析并校验 access token, 返回 user_id 或 None"""
        token = extract_token_from_headers(request.headers.get("authorization"))
        if not token:
            return None
        try:
            payload = verify_jwt(token, settings)
        except Exception:
            return None
        # Django AUTH_TOKEN_CLASSES 仅 AccessToken, refresh token 不当作 access 使用
        if payload.get("token_type") != "access":
            return None
        uid = payload.get("user_id")
        try:
            return int(uid)
        except (TypeError, ValueError):
            return None

    @router.post("/token/", response_model=TokenObtainResponse)
    async def obtain_token(body: TokenObtainRequest, db: Session = Depends(get_db)):
        """对齐 simplejwt TokenObtainPairView: 成功返回 {access, refresh}, 失败 401"""
        user = authenticate_user(db, body.username, body.password)
        if user is None:
            raise HTTPException(
                status_code=401,
                detail="No active account found with the given credentials",
            )
        return TokenObtainResponse(
            access=create_access_token(user.id, settings),
            refresh=create_refresh_token(user.id, settings),
        )

    @router.post("/token/refresh/", response_model=TokenRefreshResponse)
    async def refresh_token(body: TokenRefreshRequest):
        """对齐 simplejwt TokenRefreshView: 用 refresh 换新 access, 无效 401"""
        try:
            payload = verify_jwt(body.refresh, settings)
        except Exception:
            raise HTTPException(
                status_code=401,
                detail={"detail": "Token is invalid or expired", "code": "token_not_valid"},
            )
        if payload.get("token_type") != "refresh":
            raise HTTPException(
                status_code=401,
                detail={"detail": "Token has wrong type", "code": "token_not_valid"},
            )
        return TokenRefreshResponse(access=create_access_token(int(payload["user_id"]), settings))

    @router.post("/user/signin", response_model=ApiResponse)
    async def signin(request: Request, body: dict = Body(...), db: Session = Depends(get_db)):
        """注册 (对齐 users.views.UserView.post): 成功 code=200, 任何异常 code=205"""
        try:
            create_user(
                db,
                username=body.get("username"),
                password=body.get("password"),
                email=body.get("email"),
                phone=body.get("phone"),
            )
            return {"code": 200, "msg": "ok", "data": None}
        except Exception as exc:
            return {"code": 205, "msg": str(exc), "data": None}

    @router.post("/user/login", response_model=ApiResponse)
    async def login(body: UserLoginRequest, db: Session = Depends(get_db)):
        """登录 (对齐 users.views.LoginView): username 兼容手机号, 成功返回 access token"""
        try:
            user = authenticate_user(db, body.username, body.password)
            if user is not None:
                token = create_access_token(user.id, settings)
                return {"code": 200, "data": {"token": token}, "msg": "success"}
            return {"code": 205, "data": None, "msg": "账号或密码错误"}
        except Exception as exc:
            return {"code": 205, "data": None, "msg": str(exc)}

    @router.get("/user/info", response_model=ApiResponse)
    async def user_info(request: Request, token: Optional[str] = None, db: Session = Depends(get_db)):
        """当前用户信息 (对齐 users.views.UserInfo): token 从 query 参数读取"""
        try:
            if not token:
                raise ValueError("token 参数缺失")
            payload = verify_jwt(token, settings)
            if payload.get("token_type") != "access":
                raise ValueError("Token has wrong type")
            user = get_user_by_id(db, payload.get("user_id"))
            if user is None:
                raise ValueError("User not found")
            user_info = {
                "id": user.id,
                "roles": ["admin"],
                "introduction": "I am a super administrator",
                "avatar": "https://wpimg.wallstcn.com/f778738c-e4f8-4870-b634-56703b4acafe.gif",
                "name": user.username,
            }
            return {"code": 200, "data": user_info, "msg": "ok"}
        except Exception as exc:
            return {"code": 205, "data": None, "msg": str(exc)}

    @router.post("/user/logout", response_model=ApiResponse)
    async def logout(request: Request):
        """登出 (对齐 users.views.Logout): Django 仅清理 session, JWT 无状态, 直接成功"""
        return {"code": 200, "data": "ok", "msg": "ok"}

    return router
