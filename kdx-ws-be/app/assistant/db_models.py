"""
SQLAlchemy 模型：映射 kdx-be (Django) 同库中的宝宝数据表

说明：
- kdx-ws-be 与 kdx-be (Django) 共用同一个 MySQL (kdemo 库)
- Django 表名约定: {app_label}_{model_name小写} → baby_feedmilk / baby_temperature ...
- 这里只映射 Assistant 工具需要的列，未列出的列不受影响
- user 外键仅存 int id (users_user.id)，不映射 User 表
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Numeric, String, Text, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class DjangoBase(DeclarativeBase):
    pass


class BabyInfoRow(DjangoBase):
    __tablename__ = "baby_babyinfo"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column("user_id", Integer)
    name: Mapped[str] = mapped_column(String(100))
    birthday: Mapped[date] = mapped_column(Date)
    gender: Mapped[str] = mapped_column(String(10), default="F")


class FeedMilkRow(DjangoBase):
    __tablename__ = "baby_feedmilk"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column("user_id", Integer)
    feed_time: Mapped[datetime] = mapped_column(DateTime)
    milk_volume: Mapped[int] = mapped_column(Integer)
    feed_type: Mapped[str] = mapped_column(String(20), default="bottle")
    duration_total: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(Text, nullable=True)


class SleepLogRow(DjangoBase):
    __tablename__ = "baby_sleeplog"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column("user_id", Integer)
    sleep_time: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(100))
    describe: Mapped[str] = mapped_column(String(600), nullable=True)
    duration: Mapped[int] = mapped_column(Integer, nullable=True)


class BabyDiapersRow(DjangoBase):
    __tablename__ = "baby_babydiapers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column("user_id", Integer)
    use_date: Mapped[datetime] = mapped_column(DateTime)
    brand: Mapped[str] = mapped_column(String(100))
    tabActiveName: Mapped[str] = mapped_column(String(100), default="peeing")
    is_leaked: Mapped[str] = mapped_column(String(10), default="false")
    describe: Mapped[str] = mapped_column(Text, nullable=True)


class TemperatureRow(DjangoBase):
    __tablename__ = "baby_temperature"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column("user_id", Integer)
    measure_date: Mapped[date] = mapped_column(Date)
    temperature: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(100), nullable=True)


class BabyExpenseRow(DjangoBase):
    __tablename__ = "baby_babyexpense"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column("user_id", Integer)
    order_time: Mapped[datetime] = mapped_column(DateTime)
    name: Mapped[str] = mapped_column(String(200))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    tag: Mapped[str] = mapped_column(String(100), nullable=True)
    expense_type: Mapped[str] = mapped_column(String(10), default="expense")


class GrowthRecordRow(DjangoBase):
    __tablename__ = "baby_growthrecord"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column("user_id", Integer)
    measure_date: Mapped[date] = mapped_column(Date)
    height_cm: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=True)
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=True)
    head_circumference_cm: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=True)


class BabyVaccineRecordRow(DjangoBase):
    __tablename__ = "baby_babyvaccinerecord"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column("user_id", Integer)
    vaccine_key: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    dose_index: Mapped[int] = mapped_column(Integer, default=1)
    dose_total: Mapped[int] = mapped_column(Integer, default=1)
    fee_type: Mapped[str] = mapped_column(String(10), default="free")
    recommend_date: Mapped[date] = mapped_column(Date)
    done: Mapped[bool] = mapped_column(Integer, default=0)  # Django Boolean → tinyint
    actual_date: Mapped[date] = mapped_column(Date, nullable=True)


class BirthdayRecordRow(DjangoBase):
    __tablename__ = "baby_birthdayrecord"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column("user_id", Integer)
    name: Mapped[str] = mapped_column(String(100))
    relation: Mapped[str] = mapped_column(String(50), nullable=True)
    calendar_type: Mapped[str] = mapped_column(String(10), default="lunar")
    solar_date: Mapped[date] = mapped_column(Date, nullable=True)
