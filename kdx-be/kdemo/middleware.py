import time
from django.utils.deprecation import MiddlewareMixin


class UserAccessLogMiddleware(MiddlewareMixin):
    """记录用户接口访问日志"""
    
    # 排除的路径（如静态文件、健康检查、管理后台等）
    EXCLUDED_PATHS = [
        '/static/',
        '/media/',
        '/admin/jsi18n/',
        '/favicon.ico',
        '/health/',
    ]
    
    def process_request(self, request):
        # 记录请求开始时间
        request._access_start_time = time.time()
    
    def process_response(self, request, response):
        # 跳过未登录用户的请求
        if not hasattr(request, 'user') or not hasattr(request.user, 'is_authenticated'):
            return response
        
        if not request.user.is_authenticated:
            return response
        
        # 跳过排除的路径
        path = request.path
        if any(path.startswith(excluded) for excluded in self.EXCLUDED_PATHS):
            return response
        
        # 记录到数据库
        try:
            from baby.models import UserAccessLog
            
            duration = time.time() - getattr(request, '_access_start_time', time.time())
            
            UserAccessLog.objects.create(
                user=request.user,
                path=path,
                method=request.method,
                ip_address=self._get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                response_status=response.status_code,
                duration=duration
            )
        except Exception:
            # 日志记录失败不影响正常请求
            pass
        
        return response
    
    def _get_client_ip(self, request):
        """获取客户端真实IP"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
