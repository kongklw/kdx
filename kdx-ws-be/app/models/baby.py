"""baby 模块 SQLAlchemy 模型

映射 kdemo 库中 Django baby 应用已存在的表 (只做映射, 禁止建表/改表)。
表名规则:
- 未显式指定 db_table 的模型 → Django 默认 `{app_label}_{模型名小写}` (如 baby_feedmilk)
- 显式指定 db_table 的模型 → 以 models.py 的 Meta 为准 (如 baby_growing_blog / baby_pants_brand)
注意: app/assistant/db_models.py 已用独立类名映射了部分同一批表 (只读用途),
本文件与其互不冲突, 互不影响。
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    JSON,
    Numeric,
    SmallInteger,
    String,
    Text,
)

from app.core.database import Base


class BabyInfo(Base):
    """宝宝基本信息 → baby_babyinfo"""

    __tablename__ = "baby_babyinfo"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column("user_id", Integer, nullable=True, index=True)
    name = Column(String(100), nullable=False)
    birthday = Column(Date, nullable=False)
    birth_weight = Column(Integer, nullable=False)
    birth_height = Column(Integer, nullable=False)
    gender = Column(String(10), nullable=False, default="F")
    birth_week = Column(Integer, nullable=False, default=40)
    is_sensitive = Column(Boolean, nullable=False, default=False)
    is_only_child = Column(Boolean, nullable=False, default=False)
    image = Column(String(100), nullable=True)
    created_at = Column(Date, nullable=False)
    updated_at = Column(Date, nullable=False)


class GrowingBlogModel(Base):
    """成长时刻博客 → baby_growing_blog (Meta.db_table)"""

    __tablename__ = "baby_growing_blog"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column("user_id", Integer, nullable=False, index=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=True)
    created_time = Column(Date, nullable=False)
    updated_time = Column(Date, nullable=False)
    number_of_comments = Column(Integer, nullable=False, default=0)
    number_of_pingbacks = Column(Integer, nullable=False, default=0)
    rating = Column(Integer, nullable=False, default=5)


class FeedMilk(Base):
    """喂奶记录 → baby_feedmilk"""

    __tablename__ = "baby_feedmilk"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column("user_id", Integer, nullable=False, index=True)
    feed_time = Column(DateTime, nullable=False)
    milk_volume = Column(Integer, nullable=False)
    time_different = Column(DateTime, nullable=True)
    feed_type = Column(String(20), nullable=False, default="bottle")
    duration_total = Column(Integer, nullable=False, default=0)
    left_duration = Column(Integer, nullable=False, default=0)
    right_duration = Column(Integer, nullable=False, default=0)
    note = Column(Text, nullable=True)


class SleepLog(Base):
    """睡眠记录 → baby_sleeplog"""

    __tablename__ = "baby_sleeplog"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column("user_id", Integer, nullable=False, index=True)
    sleep_time = Column(DateTime, nullable=False)
    status = Column(String(100), nullable=False)
    describe = Column(String(600), nullable=True)
    duration = Column(Integer, nullable=True)


class BabyDiapers(Base):
    """尿不湿记录 → baby_babydiapers"""

    __tablename__ = "baby_babydiapers"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column("user_id", Integer, nullable=False, index=True)
    use_date = Column(DateTime, nullable=False)
    brand = Column(String(100), nullable=False)
    tabActiveName = Column(String(100), nullable=False, default="peeing")
    is_leaked = Column(String(10), nullable=False, default="false")
    peeing_color = Column(String(100), nullable=True)
    stool_shape = Column(String(200), nullable=True)
    stool_color = Column(String(100), nullable=True)
    describe = Column(Text, nullable=True)


class Temperature(Base):
    """体温记录 → baby_temperature"""

    __tablename__ = "baby_temperature"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column("user_id", Integer, nullable=False, index=True)
    measure_date = Column(Date, nullable=False, unique=True)
    temperature = Column(String(10), nullable=False)
    status = Column(String(100), nullable=True)


class BabyExpense(Base):
    """花费记录 → baby_babyexpense"""

    __tablename__ = "baby_babyexpense"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column("user_id", Integer, nullable=False, index=True)
    order_time = Column(DateTime, nullable=False)
    name = Column(String(200), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    tag = Column(String(100), nullable=True)
    expense_type = Column(String(10), nullable=False, default="expense")
    image_url = Column(String(500), nullable=True)
    create_time = Column(Date, nullable=False)
    update_time = Column(Date, nullable=False)


class BabyAlbum(Base):
    """宝宝相册 → baby_babyalbum"""

    __tablename__ = "baby_babyalbum"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column("user_id", Integer, nullable=False, index=True)
    content = Column(Text, nullable=True)
    happened_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False)
    visibility = Column(String(20), nullable=False, default="relatives")
    tags = Column(JSON, nullable=True)


class AlbumPhoto(Base):
    """相册照片/视频 → baby_albumphoto"""

    __tablename__ = "baby_albumphoto"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    album_id = Column("album_id", BigInteger, nullable=False, index=True)
    image = Column(String(100), nullable=False)
    poster = Column(String(100), nullable=True)
    is_video = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False)


class GrowthRecord(Base):
    """生长记录 (身高体重头围) → baby_growthrecord"""

    __tablename__ = "baby_growthrecord"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column("user_id", Integer, nullable=False, index=True)
    measure_date = Column(Date, nullable=False)
    height_cm = Column(Numeric(5, 1), nullable=True)
    weight_kg = Column(Numeric(5, 2), nullable=True)
    head_circumference_cm = Column(Numeric(5, 1), nullable=True)
    photo = Column(String(100), nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class VaccineDefinition(Base):
    """疫苗定义 (全局) → baby_vaccinedefinition"""

    __tablename__ = "baby_vaccinedefinition"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    vaccine_key = Column(String(100), nullable=False, unique=True)
    name = Column(String(200), nullable=False)
    dose_index = Column(Integer, nullable=False, default=1)
    dose_total = Column(Integer, nullable=False, default=1)
    fee_type = Column(String(10), nullable=False, default="free")
    description = Column(String(500), nullable=True)
    months_offset = Column(Numeric(4, 1), nullable=False, default=0)
    days_offset = Column(Integer, nullable=False, default=0)
    price_min = Column(Integer, nullable=True)
    price_max = Column(Integer, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class BabyVaccineRecord(Base):
    """用户疫苗接种记录 → baby_babyvaccinerecord"""

    __tablename__ = "baby_babyvaccinerecord"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column("user_id", Integer, nullable=False, index=True)
    vaccine_key = Column(String(100), nullable=False)
    name = Column(String(200), nullable=False)
    dose_index = Column(Integer, nullable=False, default=1)
    dose_total = Column(Integer, nullable=False, default=1)
    fee_type = Column(String(10), nullable=False, default="free")
    description = Column(String(500), nullable=True)
    recommend_date = Column(Date, nullable=False)
    done = Column(Boolean, nullable=False, default=False)
    actual_date = Column(Date, nullable=True)
    price_min = Column(Integer, nullable=True)
    price_max = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class ExpenseTag(Base):
    """花费标签 → baby_expensetag"""

    __tablename__ = "baby_expensetag"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column("user_id", Integer, nullable=False, index=True)
    name = Column(String(50), nullable=False)
    created_at = Column(DateTime, nullable=False)


class UserAppOrder(Base):
    """用户首页应用排序偏好 → baby_userapporder"""

    __tablename__ = "baby_userapporder"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column("user_id", Integer, nullable=False, unique=True)
    order = Column(JSON, nullable=True)
    updated_at = Column(DateTime, nullable=False)


class DailyHabit(Base):
    """每日习惯 → baby_dailyhabit"""

    __tablename__ = "baby_dailyhabit"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column("user_id", Integer, nullable=False, index=True)
    text = Column(String(100), nullable=False)
    icon = Column(String(50), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class TodoList(Base):
    """待办清单 → baby_todolist"""

    __tablename__ = "baby_todolist"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column("user_id", Integer, nullable=False, index=True)
    create_time = Column(Date, nullable=False)
    update_time = Column(Date, nullable=False)
    text = Column(String(100), nullable=False)
    done = Column(Boolean, nullable=False, default=False)
    is_daily = Column(Boolean, nullable=False, default=False)
    icon = Column(String(50), nullable=True)


class MenstrualSetting(Base):
    """经期设置 → baby_menstrualsetting"""

    __tablename__ = "baby_menstrualsetting"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column("user_id", Integer, nullable=False, unique=True)
    cycle_length = Column(Integer, nullable=False, default=28)
    period_length = Column(Integer, nullable=False, default=5)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class MenstrualLog(Base):
    """经期日志 → baby_menstruallog"""

    __tablename__ = "baby_menstruallog"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column("user_id", Integer, nullable=False, index=True)
    date = Column(Date, nullable=False)
    is_period = Column(Boolean, nullable=False, default=False)
    flow_level = Column(Integer, nullable=False, default=0)
    pain_level = Column(Integer, nullable=False, default=0)
    had_sex = Column(Boolean, nullable=False, default=False)
    symptoms = Column(String(500), nullable=True)
    basal_temp = Column(Numeric(4, 2), nullable=True)
    weight_kg = Column(Numeric(5, 2), nullable=True)
    mood = Column(String(20), nullable=True)
    habit_eat_on_time = Column(Boolean, nullable=False, default=False)
    habit_water8 = Column(Boolean, nullable=False, default=False)
    habit_fruits = Column(Boolean, nullable=False, default=False)
    habit_exercise = Column(Boolean, nullable=False, default=False)
    habit_poop = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class BirthdayRecord(Base):
    """生日记录 (公历/农历) → baby_birthdayrecord"""

    __tablename__ = "baby_birthdayrecord"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column("user_id", Integer, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    relation = Column(String(50), nullable=True)
    calendar_type = Column(String(10), nullable=False, default="lunar")
    solar_date = Column(Date, nullable=True)
    lunar_year = Column(Integer, nullable=True)
    lunar_month = Column(Integer, nullable=True)
    lunar_day = Column(Integer, nullable=True)
    lunar_is_leap = Column(Boolean, nullable=False, default=False)
    birth_hour = Column(Integer, nullable=True)
    gender = Column(SmallInteger, nullable=True)
    created_at = Column(Date, nullable=False)
    updated_at = Column(Date, nullable=False)
