"""fileUpload 迁移相关 schema (请求体模型; 响应沿用 DRF 风格 {code, msg, data})"""
from typing import Optional

from pydantic import BaseModel


class PresignInitRequest(BaseModel):
    """MinIO/S3 直传初始化请求"""
    purpose: str = ""
    filename: str = ""
    content_type: str = ""
    size: Optional[int] = None
    is_video: bool = False
    expires_in: int = 600


class PresignCompleteRequest(BaseModel):
    """MinIO/S3 直传完成确认请求"""
    asset_id: Optional[int] = None


class ApiResponse(BaseModel):
    """与 Django DRF views 保持一致的统一响应形状"""
    code: int
    msg: str
    data: object = None
