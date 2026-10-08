"""k8s 应用端点迁移 (Django k8s/urls.py)

URL 与 Django 完全一致:
  GET /k8s/pods -> k8s.views.Pos.get (列出所有命名空间 pod)

源视图因 self.v1 未初始化实际恒返回 205; 此处为可用实现, 集群不可用时
降级为同样的 {"code": 205, "data": None, "msg": ...} 响应结构。
"""
from fastapi import APIRouter

from ..core.config import Settings
from ..schemas.user import ApiResponse
from ..services import k8s_service


def create_k8s_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/k8s", tags=["k8s"])

    @router.get("/pods", response_model=ApiResponse)
    def list_pods():
        """列出 pod; 使用同步 def: kubernetes 客户端为阻塞调用, 交由线程池执行"""
        try:
            k8s_service.list_all_pods()
            return {"code": 200, "data": "ok", "msg": "success"}
        except Exception as exc:
            return {"code": 205, "data": None, "msg": str(exc)}

    return router
