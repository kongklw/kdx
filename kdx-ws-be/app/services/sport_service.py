from typing import List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models.sport import Sport


def create_sport(db: Session, user_id: int, name: str, country: str, popularity: Optional[int]) -> Optional[Sport]:
    """创建运动记录并关联当前用户

    返回 None 表示违反 (user_id, name) 唯一约束, 对齐 DRF unique_together 校验失败。
    """
    sport = Sport(user_id=user_id, name=name, country=country, popularity=popularity)
    db.add(sport)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    db.refresh(sport)
    return sport


def list_sports_by_user(db: Session, user_id: int) -> List[Sport]:
    """过滤当前用户的运动记录 (对齐 SportList 视图)"""
    return db.query(Sport).filter(Sport.user_id == user_id).all()
