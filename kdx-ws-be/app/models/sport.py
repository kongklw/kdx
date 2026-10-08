from sqlalchemy import BigInteger, Column, Integer, String

from app.core.database import Base


class Sport(Base):
    """映射 Django sport.SportModels 的真实表 tb_sports

    注意: 表已存在, 仅做 ORM 映射, 禁止建表/改表。
    user_id 为指向 tb_users.id 的外键, 这里映射为普通列以避免跨应用级联配置。
    (user_id, name) 存在唯一约束, 冲突时由服务层捕获 IntegrityError 处理。
    """
    __tablename__ = "tb_sports"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    country = Column(String(100), nullable=False)
    popularity = Column(Integer, nullable=True)
    user_id = Column(BigInteger, nullable=True)
