"""baby 模块 pydantic 请求模型

说明:
- Django/DRF 原接口请求体非常宽松 (缺字段/多字段均容忍), 因此所有字段均为
  Optional 且 extra="allow", 由 service 层按原 views.py 语义取值
- 响应保持与 Django 一致的 {"code", "msg", "data"} 形状, 由 service 层直接
  构造 dict (字段名/类型逐字段对齐 DRF 序列化输出), 不再用响应模型强约束
"""

from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict


class _FlexibleModel(BaseModel):
    """宽松基类: 允许多余字段, 与 DRF 对 QueryDict/JSON 的容忍行为一致"""

    model_config = ConfigDict(extra="allow")


# ── 宝宝信息 ──
class BabyInfoBody(_FlexibleModel):
    name: Optional[str] = None
    birthday: Optional[str] = None
    birth_weight: Optional[int] = None
    birth_height: Optional[int] = None
    gender: Optional[str] = None
    birth_week: Optional[int] = None
    is_sensitive: Optional[bool] = None
    is_only_child: Optional[bool] = None


# ── dashboard ──
class DashboardOrderBody(_FlexibleModel):
    app_order: Optional[List[Any]] = None


# ── 成长博客 ──
class GrowingBlogBody(_FlexibleModel):
    title: Optional[str] = None
    content: Optional[str] = None


class AiGenBody(_FlexibleModel):
    content: Optional[str] = None


# ── 待办 ──
class TodoCreateBody(_FlexibleModel):
    text: Optional[str] = None
    done: Optional[bool] = False
    is_daily: Optional[bool] = False
    icon: Optional[str] = ""


class TodoUpdateBody(_FlexibleModel):
    id: Optional[int] = None
    text: Optional[str] = None
    done: Optional[bool] = None
    is_daily: Optional[bool] = None
    icon: Optional[str] = None


class DailyHabitBody(_FlexibleModel):
    id: Optional[int] = None
    text: Optional[str] = None
    icon: Optional[str] = None
    is_active: Optional[bool] = None


# ── 喂奶 ──
class FeedMilkBody(_FlexibleModel):
    id: Optional[int] = None
    feed_time: Optional[str] = None
    milk_volume: Optional[Any] = None
    feed_type: Optional[str] = "bottle"
    duration_total: Optional[Any] = 0
    left_duration: Optional[Any] = 0
    right_duration: Optional[Any] = 0
    note: Optional[str] = ""


# ── 体温 ──
class TemperatureBody(_FlexibleModel):
    id: Optional[int] = None
    measure_date: Optional[str] = None
    temperature: Optional[Any] = None


# ── 尿不湿 ──
class BabyPantsBody(_FlexibleModel):
    id: Optional[int] = None
    use_date: Optional[str] = None
    tabActiveName: Optional[str] = None
    peeing_color: Optional[Any] = None
    stool_color: Optional[Any] = None
    stool_shape_list: Optional[List[Any]] = None
    brand: Optional[str] = None
    is_leaked: Optional[Any] = None
    describe: Optional[str] = None


# ── 花费 ──
class ExpenseBody(_FlexibleModel):
    id: Optional[int] = None
    order_time: Optional[str] = None
    name: Optional[str] = None
    amount: Optional[Any] = None
    tag: Optional[str] = None
    expense_type: Optional[str] = "expense"
    image_url: Optional[str] = None


class ExpenseListBody(_FlexibleModel):
    page_size: Optional[int] = 20
    page_num: Optional[int] = 1
    name: Optional[str] = None
    expense_type: Optional[str] = None
    monthrange: Optional[List[str]] = None


class BatchDeleteExpenseBody(_FlexibleModel):
    ids: Optional[List[int]] = None


class BatchExpenseBody(_FlexibleModel):
    fileList: Optional[List[Any]] = None


class ExpenseTagBody(_FlexibleModel):
    name: Optional[str] = None


# ── 睡眠 ──
class SleepBody(_FlexibleModel):
    sleep_time: Optional[str] = None
    status: Optional[str] = None
    describe: Optional[str] = None
    duration: Optional[Any] = None


class SleepListBody(_FlexibleModel):
    date: Optional[str] = None
    currentPage: Optional[Any] = None
    page_num: Optional[Any] = None
    pageSize: Optional[Any] = None
    page_size: Optional[Any] = None


# ── 相册 ──
class AlbumCreateBody(_FlexibleModel):
    content: Optional[str] = None
    happened_at: Optional[str] = None
    visibility: Optional[str] = "relatives"
    tags: Optional[Any] = None
    media_asset_ids: Optional[List[Any]] = None


# ── 生长记录 ──
class GrowthRecordBody(_FlexibleModel):
    measure_date: Optional[str] = None
    height_cm: Optional[Any] = None
    weight_kg: Optional[Any] = None
    head_circumference_cm: Optional[Any] = None
    remove_photo: Optional[Any] = None


# ── 疫苗 ──
class VaccineToggleBody(_FlexibleModel):
    vaccine_key: Optional[str] = None
    date_type: Optional[str] = None
    date: Optional[str] = None
    recommend_date: Optional[str] = None
    actual_date: Optional[str] = None
    done: Optional[Any] = None


class VaccineAddPaidBody(_FlexibleModel):
    vaccine_key: Optional[str] = None
    recommend_date: Optional[str] = None


# ── 经期 ──
class PeriodLogBody(_FlexibleModel):
    date: Optional[str] = None
    is_period: Optional[Any] = None
    flow_level: Optional[Any] = None
    pain_level: Optional[Any] = None
    had_sex: Optional[Any] = None
    symptoms: Optional[Any] = None
    basal_temp: Optional[Any] = None
    weight_kg: Optional[Any] = None
    mood: Optional[Any] = None
    habit_eat_on_time: Optional[Any] = None
    habit_water8: Optional[Any] = None
    habit_fruits: Optional[Any] = None
    habit_exercise: Optional[Any] = None
    habit_poop: Optional[Any] = None


class PeriodSettingsBody(_FlexibleModel):
    cycle_length: Optional[Any] = None
    period_length: Optional[Any] = None


# ── 生日 ──
class BirthdayBody(_FlexibleModel):
    id: Optional[int] = None
    name: Optional[str] = None
    relation: Optional[str] = None
    calendar_type: Optional[str] = None
    solar_date: Optional[str] = None
    lunar_year: Optional[Any] = None
    lunar_month: Optional[Any] = None
    lunar_day: Optional[Any] = None
    lunar_is_leap: Optional[Any] = None
    birth_hour: Optional[Any] = None
    gender: Optional[Any] = None
