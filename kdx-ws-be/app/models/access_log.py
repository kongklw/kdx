from sqlalchemy import Column, Integer, String, Float, DateTime, Index, BigInteger
from sqlalchemy.sql import func
from app.core.database import Base


class UserAccessLog(Base):
    """用户访问日志 - 与 Django 项目共享表"""
    __tablename__ = "baby_useraccesslog"  # Django 默认表名格式: appname_modelname
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    path = Column(String(500), nullable=False)
    method = Column(String(10), nullable=False)
    ip_address = Column(String(45), nullable=True)  # Django GenericIPAddressField
    user_agent = Column(String(500), nullable=True)
    response_status = Column(Integer, nullable=False)
    duration = Column(Float, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    
    __table_args__ = (
        Index('baby_useraccesslog_user_id_created_at_758e30_idx', 'user_id', 'created_at'),
        Index('baby_useraccesslog_path_created_at_bde4f3_idx', 'path', 'created_at'),
    )
    
    def __repr__(self):
        return f"<UserAccessLog(user_id={self.user_id}, path={self.path}, created_at={self.created_at})>"
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'path': self.path,
            'method': self.method,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'response_status': self.response_status,
            'duration': round(self.duration, 3),
            'created_at': str(self.created_at)
        }
