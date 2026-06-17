from typing import List, Optional
from datetime import datetime, timedelta
from sqlalchemy import func, desc
from sqlalchemy.orm import Session
from app.models.access_log import UserAccessLog


class AccessLogRepository:
    """用户访问日志仓储 - 与 Django 项目共享表"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create_log(
        self,
        user_id: int,
        path: str,
        method: str,
        ip_address: Optional[str],
        user_agent: Optional[str],
        response_status: int,
        duration: float
    ) -> UserAccessLog:
        """创建访问日志"""
        log = UserAccessLog(
            user_id=user_id,
            path=path,
            method=method,
            ip_address=ip_address,
            user_agent=user_agent,
            response_status=response_status,
            duration=duration
        )
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log
    
    def get_recent_access(self, user_id: int, limit: int = 20) -> List[dict]:
        """获取最近访问的接口列表"""
        results = self.db.query(
            UserAccessLog.path,
            UserAccessLog.method,
            func.count(UserAccessLog.id).label('count')
        ).filter(
            UserAccessLog.user_id == user_id
        ).group_by(
            UserAccessLog.path,
            UserAccessLog.method
        ).order_by(
            desc('count')
        ).limit(limit).all()
        
        return [{'path': r.path, 'method': r.method, 'count': r.count} for r in results]
    
    def get_hourly_stats(self, user_id: int, hours: int = 24) -> List[dict]:
        """获取每小时的访问量"""
        since = datetime.utcnow() - timedelta(hours=hours)
        
        results = self.db.query(
            func.date_trunc('hour', UserAccessLog.created_at).label('hour'),
            func.count(UserAccessLog.id).label('count')
        ).filter(
            UserAccessLog.user_id == user_id,
            UserAccessLog.created_at >= since
        ).group_by(
            'hour'
        ).order_by('hour').all()
        
        return [{'hour': str(r.hour), 'count': r.count} for r in results]
    
    def get_today_stats(self, user_id: int) -> dict:
        """获取今日访问统计"""
        today = datetime.utcnow().date()
        today_start = datetime.combine(today, datetime.min.time())
        
        result = self.db.query(
            func.count(UserAccessLog.id).label('total_requests'),
            func.avg(UserAccessLog.duration).label('avg_duration')
        ).filter(
            UserAccessLog.user_id == user_id,
            UserAccessLog.created_at >= today_start
        ).first()
        
        return {
            'total_requests': result.total_requests or 0,
            'avg_duration': round(result.avg_duration or 0, 3)
        }
    
    def get_recent_logs(self, user_id: int, limit: int = 10) -> List[dict]:
        """获取最近的访问记录"""
        logs = self.db.query(UserAccessLog).filter(
            UserAccessLog.user_id == user_id
        ).order_by(
            desc(UserAccessLog.created_at)
        ).limit(limit).all()
        
        return [log.to_dict() for log in logs]
    
    def get_path_stats(self, user_id: int, path_keyword: Optional[str] = None) -> dict:
        """获取特定路径的访问统计"""
        query = self.db.query(
            func.count(UserAccessLog.id).label('total_count'),
            func.avg(UserAccessLog.duration).label('avg_duration'),
            func.max(UserAccessLog.duration).label('max_duration'),
            func.min(UserAccessLog.duration).label('min_duration')
        ).filter(
            UserAccessLog.user_id == user_id
        )
        
        if path_keyword:
            query = query.filter(UserAccessLog.path.contains(path_keyword))
        
        result = query.first()
        
        return {
            'total_count': result.total_count or 0,
            'avg_duration': round(result.avg_duration or 0, 3),
            'max_duration': round(result.max_duration or 0, 3),
            'min_duration': round(result.min_duration or 0, 3),
        }
    
    def get_path_logs(self, user_id: int, path_keyword: Optional[str] = None, limit: int = 100) -> List[dict]:
        """获取特定路径的访问记录"""
        query = self.db.query(UserAccessLog).filter(
            UserAccessLog.user_id == user_id
        )
        
        if path_keyword:
            query = query.filter(UserAccessLog.path.contains(path_keyword))
        
        logs = query.order_by(
            desc(UserAccessLog.created_at)
        ).limit(limit).all()
        
        return [log.to_dict() for log in logs]
