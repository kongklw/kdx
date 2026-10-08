from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String

from app.core.database import Base


class User(Base):
    """映射 Django users.User (AbstractUser) 的真实表 tb_users

    注意: 表已存在, 仅做 ORM 映射, 禁止建表/改表。
    password 为 Django pbkdf2_sha256 格式, 校验见 core.security.verify_django_password
    """
    __tablename__ = "tb_users"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    password = Column(String(128), nullable=False)
    last_login = Column(DateTime(6), nullable=True)
    is_superuser = Column(Boolean, nullable=False, default=False)
    username = Column(String(150), nullable=False, unique=True)
    first_name = Column(String(150), nullable=False, default="")
    last_name = Column(String(150), nullable=False, default="")
    email = Column(String(254), nullable=False, default="")
    is_staff = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    date_joined = Column(DateTime(6), nullable=False)
    phone = Column(String(11), nullable=True, unique=True)
    introduction = Column(String(100), nullable=True)
    avatar = Column(String(200), nullable=True)
