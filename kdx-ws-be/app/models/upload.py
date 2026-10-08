from sqlalchemy import BigInteger, Boolean, Column, DateTime, String
from app.core.database import Base


class FileRecord(Base):
    """文件上传记录 - 映射 Django fileUpload_file 表 (表已存在, 仅映射, 禁止建表/改表)"""
    __tablename__ = 'fileUpload_file'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    # 逻辑外键 -> tb_users.id (约束在库端, 这里只做映射)
    user_id = Column(BigInteger, nullable=True)
    # Django FileField: 相对 MEDIA_ROOT 的存储路径, 如 "files/xxxxxxxxxx.jpg"
    file = Column(String(100), nullable=True)
    upload_method = Column(String(20), nullable=False)
    created_at = Column(DateTime, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'file': self.file,
            'upload_method': self.upload_method,
            'created_at': str(self.created_at),
        }


class MediaAsset(Base):
    """媒体资源 (MinIO/S3 直传) - 映射 Django fileUpload_mediaasset 表 (仅映射)"""
    __tablename__ = 'fileUpload_mediaasset'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    bucket = Column(String(128), nullable=False)
    object_key = Column(String(1024), nullable=False)
    original_name = Column(String(255), nullable=True)
    content_type = Column(String(255), nullable=True)
    size_bytes = Column(BigInteger, nullable=True)
    etag = Column(String(255), nullable=True)
    is_video = Column(Boolean, nullable=False, default=False)
    purpose = Column(String(64), nullable=False)
    ref_type = Column(String(64), nullable=True)
    ref_id = Column(BigInteger, nullable=True)
    status = Column(String(16), nullable=False, default='init')
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
