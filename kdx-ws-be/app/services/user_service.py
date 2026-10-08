import unicodedata
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from ..core.security import (
    make_django_password,
    normalize_email,
    normalize_username,
    verify_django_password,
)
from ..models.user import User


def get_user_by_id(db: Session, user_id) -> Optional[User]:
    try:
        return db.query(User).filter(User.id == int(user_id)).first()
    except (TypeError, ValueError):
        return None


def get_user_by_username(db: Session, username) -> Optional[User]:
    if not username:
        return None
    return db.query(User).filter(User.username == username).first()


def get_user_by_phone(db: Session, phone) -> Optional[User]:
    if not phone:
        return None
    return db.query(User).filter(User.phone == phone).first()


def authenticate_user(db: Session, username, password) -> Optional[User]:
    """对齐 Django LoginView 的认证逻辑:

    1. 先按 username 查并校验密码 (ModelBackend 语义: 校验通过且 is_active 才算登录成功);
    2. 失败则按 phone 查并校验密码 (源代码此分支未检查 is_active, 保持一致)。
    """
    if not password:
        return None
    user = get_user_by_username(db, username)
    if user and user.is_active and verify_django_password(password, user.password):
        return user
    user = get_user_by_phone(db, username)
    if user and verify_django_password(password, user.password):
        return user
    return None


def create_user(db: Session, username=None, password=None, email=None, phone=None) -> User:
    """对齐 Django User.objects.create_user(...) 的字段默认值与归一化逻辑

    username 缺失时抛 ValueError (对应 Django "The given username must be set"),
    由 api 层捕获返回 {"code": 205, ...}。
    """
    if not username:
        raise ValueError("The given username must be set")
    now = datetime.now()  # Django USE_TZ=False, 存 naive 本地时间 (Asia/Shanghai)
    user = User(
        username=normalize_username(str(username)),
        password=make_django_password(password),
        email=normalize_email(email),
        phone=phone,
        is_active=True,
        is_staff=False,
        is_superuser=False,
        first_name="",
        last_name="",
        date_joined=now,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
