from django.db.models import Count
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from baby.models import UserAccessLog


class UserAccessStatsView(APIView):
    """用户访问统计"""
    
    def get(self, request):
        user = request.user
        today = timezone.now().date()
        
        # 1. 最近访问的接口列表
        recent_access = UserAccessLog.objects.filter(user=user).values(
            'path', 'method'
        ).annotate(
            count=Count('id')
        ).order_by('-count')[:20]
        
        # 2. 每小时的访问量（最近24小时）
        from django.db.models.functions import TruncHour
        hourly_stats = UserAccessLog.objects.filter(
            user=user, 
            created_at__gte=timezone.now() - timezone.timedelta(hours=24)
        ).annotate(
            hour=TruncHour('created_at')
        ).values('hour').annotate(
            count=Count('id')
        ).order_by('hour')
        
        # 3. 今日访问统计
        today_stats = UserAccessLog.objects.filter(
            user=user, 
            created_at__date=today
        ).aggregate(
            total_requests=Count('id'),
            avg_duration=Count('duration')
        )
        
        # 4. 响应时间统计
        duration_stats = UserAccessLog.objects.filter(
            user=user,
            created_at__date=today
        ).aggregate(
            avg_duration=Count('duration'),
            max_duration=Count('duration'),
            min_duration=Count('duration')
        )
        
        # 5. 最近10条访问记录
        recent_logs = UserAccessLog.objects.filter(user=user)[:10].values(
            'path', 'method', 'response_status', 'duration', 'created_at', 'ip_address'
        )
        
        return Response({
            'recent_access': list(recent_access),
            'hourly_stats': list(hourly_stats),
            'today_stats': {
                'total_requests': today_stats['total_requests'] or 0,
                'avg_duration': round(today_stats['avg_duration'] or 0, 3),
            },
            'recent_logs': list(recent_logs),
        })


class UserAccessDetailView(APIView):
    """用户访问详情"""
    
    def get(self, request, path=None):
        user = request.user
        
        # 查询特定路径的访问记录
        if path:
            logs = UserAccessLog.objects.filter(
                user=user,
                path__icontains=path
            ).order_by('-created_at')[:100]
        else:
            logs = UserAccessLog.objects.filter(user=user).order_by('-created_at')[:100]
        
        # 统计该路径的访问信息
        from django.db.models import Avg, Max, Min
        stats = UserAccessLog.objects.filter(
            user=user,
            path__icontains=path
        ).aggregate(
            total_count=Count('id'),
            avg_duration=Avg('duration'),
            max_duration=Max('duration'),
            min_duration=Min('duration'),
        )
        
        return Response({
            'logs': list(logs.values(
                'path', 'method', 'response_status', 'duration', 
                'created_at', 'ip_address', 'user_agent'
            )),
            'stats': {
                'total_count': stats['total_count'] or 0,
                'avg_duration': round(stats['avg_duration'] or 0, 3),
                'max_duration': round(stats['max_duration'] or 0, 3),
                'min_duration': round(stats['min_duration'] or 0, 3),
            }
        })
