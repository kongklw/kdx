"""sport 应用端点迁移 (Django sport/urls.py)

URL 与 Django 完全一致:
  GET  /sport/add   -> sport.views.SportView.get (返回空响应)
  POST /sport/add   -> sport.views.SportView.post (创建, 关联当前用户)
  GET  /sport/list  -> sport.views.SportList (过滤当前用户的记录)

行为差异说明: 源视图未配置 permission, 无 token 时 request.user 为 AnonymousUser
会直接 500; 此处要求有效 Bearer access token (401), 语义更明确。
"""
from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..core.database import get_db
from ..core.security import extract_token_from_headers, verify_jwt
from ..schemas.sport import SportCreateResponse, SportItem, SportListResponse
from ..services.sport_service import create_sport, list_sports_by_user


def create_sport_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/sport", tags=["sport"])

    def _require_user_id(request: Request) -> int:
        token = extract_token_from_headers(request.headers.get("authorization"))
        if not token:
            raise HTTPException(status_code=401, detail="未认证: 缺少 Bearer token")
        try:
            payload = verify_jwt(token, settings)
        except Exception:
            raise HTTPException(status_code=401, detail="未认证: token 无效或已过期")
        if payload.get("token_type") != "access":
            raise HTTPException(status_code=401, detail="未认证: 需要 access token")
        uid = payload.get("user_id")
        try:
            return int(uid)
        except (TypeError, ValueError):
            raise HTTPException(status_code=401, detail="未认证: token 中缺少 user_id")

    @router.get("/add")
    async def sport_add_get():
        """对齐源 SportView.get: 返回空响应"""
        return Response(status_code=200)

    @router.post("/add", response_model=SportCreateResponse)
    async def sport_add(request: Request, body: dict = Body(...), db: Session = Depends(get_db)):
        """创建运动记录 (对齐 SportSerializer: name/country 必填, user 只读注入)"""
        user_id = _require_user_id(request)
        missing = {f: ["This field is required."] for f in ("name", "country") if not body.get(f)}
        if missing:
            return {"code": 400, "data": None, "msg": str(missing)}
        popularity = body.get("popularity")
        try:
            popularity = int(popularity) if popularity is not None else None
        except (TypeError, ValueError):
            return {"code": 400, "data": None, "msg": "{'popularity': ['A valid integer is required.']}"}
        sport = create_sport(db, user_id, str(body["name"]), str(body["country"]), popularity)
        if sport is None:
            return {"code": 400, "data": None, "msg": "{'non_field_errors': ['该用户下已存在同名运动 (user, name 唯一)']}"}
        return {"code": 200, "data": None, "msg": "create successful"}

    @router.get("/list", response_model=SportListResponse)
    async def sport_list(request: Request, db: Session = Depends(get_db)):
        """列出当前用户的运动记录 (对齐 SportSerializer 输出: 外键名为 user)"""
        user_id = _require_user_id(request)
        items = list_sports_by_user(db, user_id)
        data = [
            SportItem(id=s.id, user=s.user_id, name=s.name, country=s.country, popularity=s.popularity).model_dump()
            for s in items
        ]
        return {"code": 200, "data": data, "msg": "fetch all success"}

    return router
