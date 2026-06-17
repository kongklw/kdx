from typing import Optional, List
from fastapi import APIRouter, Request, Depends, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.core.config import Settings
from app.core.database import get_db
from app.repositories.access_log_repo import AccessLogRepository
from app.api.deps import resolve_user_id


# Pydantic Models
class TodayStats(BaseModel):
    total_requests: int
    avg_duration: float


class HourlyStats(BaseModel):
    hour: str
    count: int


class RecentAccess(BaseModel):
    path: str
    method: str
    count: int


class RecentLog(BaseModel):
    id: int
    path: str
    method: str
    response_status: int
    duration: float
    created_at: str
    ip_address: Optional[str]


class PathStats(BaseModel):
    total_count: int
    avg_duration: float
    max_duration: float
    min_duration: float


class LogEntry(BaseModel):
    id: int
    path: str
    method: str
    response_status: int
    duration: float
    created_at: str
    ip_address: Optional[str]
    user_agent: Optional[str]


class AccessStatsResponse(BaseModel):
    recent_access: List[RecentAccess]
    hourly_stats: List[HourlyStats]
    today_stats: TodayStats
    recent_logs: List[RecentLog]


class PathLogsResponse(BaseModel):
    logs: List[LogEntry]
    stats: PathStats


def create_access_stats_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/access", tags=["access-stats"])
    
    @router.get("/stats", response_model=AccessStatsResponse)
    async def get_access_stats(
        request: Request,
        db: Session = Depends(get_db)
    ) -> AccessStatsResponse:
        """获取用户访问统计"""
        user_id_str = resolve_user_id(request, settings)
        
        if not user_id_str or user_id_str == "anon":
            return AccessStatsResponse(
                recent_access=[],
                hourly_stats=[],
                today_stats=TodayStats(total_requests=0, avg_duration=0),
                recent_logs=[]
            )
        
        try:
            user_id = int(user_id_str)
        except ValueError:
            return AccessStatsResponse(
                recent_access=[],
                hourly_stats=[],
                today_stats=TodayStats(total_requests=0, avg_duration=0),
                recent_logs=[]
            )
        
        repo = AccessLogRepository(db)
        
        # 获取最近访问的接口
        recent_access = repo.get_recent_access(user_id)
        
        # 获取每小时统计
        hourly_stats = repo.get_hourly_stats(user_id)
        
        # 获取今日统计
        today_stats = repo.get_today_stats(user_id)
        
        # 获取最近的访问记录
        recent_logs = repo.get_recent_logs(user_id)
        
        return AccessStatsResponse(
            recent_access=[
                RecentAccess(**item) for item in recent_access
            ],
            hourly_stats=[
                HourlyStats(**item) for item in hourly_stats
            ],
            today_stats=TodayStats(**today_stats),
            recent_logs=[
                RecentLog(**item) for item in recent_logs
            ]
        )
    
    @router.get("/detail", response_model=PathLogsResponse)
    async def get_access_detail(
        request: Request,
        path: Optional[str] = Query(None, description="路径关键词"),
        limit: int = Query(100, ge=1, le=1000),
        db: Session = Depends(get_db)
    ) -> PathLogsResponse:
        """获取特定路径的访问详情"""
        user_id_str = resolve_user_id(request, settings)
        
        if not user_id_str or user_id_str == "anon":
            return PathLogsResponse(
                logs=[],
                stats=PathStats(total_count=0, avg_duration=0, max_duration=0, min_duration=0)
            )
        
        try:
            user_id = int(user_id_str)
        except ValueError:
            return PathLogsResponse(
                logs=[],
                stats=PathStats(total_count=0, avg_duration=0, max_duration=0, min_duration=0)
            )
        
        repo = AccessLogRepository(db)
        
        # 获取路径统计
        stats = repo.get_path_stats(user_id, path)
        
        # 获取日志列表
        logs = repo.get_path_logs(user_id, path, limit)
        
        return PathLogsResponse(
            stats=PathStats(**stats),
            logs=[
                LogEntry(**item) for item in logs
            ]
        )
    
    return router
