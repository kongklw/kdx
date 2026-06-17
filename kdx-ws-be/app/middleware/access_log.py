import time
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.database import SessionLocal
from app.repositories.access_log_repo import AccessLogRepository
from app.api.deps import resolve_user_id
from app.core.config import get_settings


class UserAccessLogMiddleware(BaseHTTPMiddleware):
    """记录用户接口访问日志"""
    
    # 排除的路径
    EXCLUDED_PATHS = [
        '/health',
        '/docs',
        '/openapi.json',
        '/redoc',
        '/favicon.ico',
    ]
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 记录开始时间
        start_time = time.time()
        
        # 处理请求
        response = await call_next(request)
        
        # 跳过排除的路径
        path = request.url.path
        if any(path.startswith(excluded) for excluded in self.EXCLUDED_PATHS):
            return response
        
        # 获取用户ID
        try:
            settings = get_settings()
            user_id_str = resolve_user_id(request, settings)
            
            # 只记录有效用户（非匿名用户）
            if user_id_str and user_id_str != "anon":
                try:
                    user_id = int(user_id_str)
                    duration = time.time() - start_time
                    
                    # 获取客户端IP
                    ip_address = self._get_client_ip(request)
                    
                    # 获取User Agent
                    user_agent = request.headers.get('user-agent', '')[:500]
                    
                    # 异步记录到数据库
                    self._log_access(
                        user_id=user_id,
                        path=path,
                        method=request.method,
                        ip_address=ip_address,
                        user_agent=user_agent,
                        response_status=response.status_code,
                        duration=duration
                    )
                except (ValueError, Exception):
                    # 用户ID无效或其他错误，跳过记录
                    pass
        except Exception:
            # 中间件错误不影响正常请求
            pass
        
        return response
    
    def _get_client_ip(self, request: Request) -> str:
        """获取客户端真实IP"""
        x_forwarded_for = request.headers.get('x-forwarded-for')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            x_real_ip = request.headers.get('x-real-ip')
            if x_real_ip:
                ip = x_real_ip
            else:
                ip = request.client.host if request.client else 'unknown'
        return ip
    
    def _log_access(
        self,
        user_id: int,
        path: str,
        method: str,
        ip_address: str,
        user_agent: str,
        response_status: int,
        duration: float
    ):
        """记录访问日志到数据库"""
        try:
            db = SessionLocal()
            try:
                repo = AccessLogRepository(db)
                repo.create_log(
                    user_id=user_id,
                    path=path,
                    method=method,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    response_status=response_status,
                    duration=duration
                )
            finally:
                db.close()
        except Exception:
            # 日志记录失败不影响请求
            pass
