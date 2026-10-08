"""baby 模块业务逻辑

从 Django baby 应用 (kdx-be/baby/*.py views) 逐端点搬迁, 用 SQLAlchemy 重写查询,
响应 JSON 形状/字段名与 DRF 序列化输出保持一致 ({"code", "msg", "data"}), 包括
原有的一些怪异行为也按原样保留 (bug-for-bug 兼容), 并以中文注释标出。

鉴权语义说明 (与 Django 原行为对齐):
- 原 views 中显式 permission_classes=[IsAuthenticated] 的端点 → API 层要求有效
  JWT (user_id/sub), 否则 401
- 未声明权限类的端点 (DRF 默认 AllowAny) → API 层用 resolve_user_id (token 或
  query 参数 user_id), 不加严
"""

import calendar
import json
import logging
import os
import re
import shutil
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models.access_log import UserAccessLog
from ..models.baby import (
    AlbumPhoto,
    BabyAlbum,
    BabyDiapers,
    BabyExpense,
    BabyInfo,
    BabyVaccineRecord,
    BirthdayRecord,
    DailyHabit,
    ExpenseTag,
    FeedMilk,
    GrowingBlogModel,
    GrowthRecord,
    MenstrualLog,
    MenstrualSetting,
    SleepLog,
    Temperature,
    TodoList,
    UserAppOrder,
    VaccineDefinition,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════
# 通用工具
# ══════════════════════════════════════════════

def uid_int(user_id) -> int | None:
    """user_id 字符串 → int; 'anon' 等非法值返回 None (等价于匿名用户)"""
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None


def _parse_date(value):
    """宽松解析日期字符串 → date; 失败返回 None"""
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    s = str(value).strip()
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None


def _parse_dt(value) -> datetime | None:
    """宽松解析日期时间字符串 → 本地朴素 datetime (与 USE_TZ=False 一致)"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    s = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except Exception:
                continue
        else:
            return None
    if dt.tzinfo is not None:
        # 带时区的输入 (如 ...Z) 转为本地 naive 时间
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def _iso(value):
    """datetime/date → ISO 字符串 (DRF 默认 ISO-8601 输出)"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(sep="T", timespec="seconds") if value.microsecond else value.isoformat(sep="T")
    return value.isoformat()


def _dec_str(value):
    """Decimal → 字符串 (DRF DecimalField 输出字符串); None 透传"""
    if value is None:
        return None
    return str(value)


def _dec_float(value):
    """Decimal → float (DRF JSONRenderer 对聚合 Decimal 输出 float); None 透传"""
    if value is None:
        return None
    return float(value)


def _month_to_first_day(s: str) -> str:
    """"2025-02" → "2025-02-01"; 已是完整日期则透传"""
    s = (s or "").strip()
    if not s:
        return "1970-01-01"
    parts = s.split("-")
    if len(parts) >= 3:
        return s[:10]  # 已是 YYYY-MM-DD
    if len(parts) == 2:
        return f"{parts[0]}-{parts[1]}-01"
    return s


def _month_to_last_day(s: str) -> str:
    """"2025-02" → "2025-02-28"; 已是完整日期则透传"""
    s = (s or "").strip()
    if not s:
        return "2099-12-31"
    parts = s.split("-")
    if len(parts) >= 3:
        return s[:10]
    if len(parts) == 2:
        y, m = int(parts[0]), int(parts[1])
        if m == 12:
            ny, nm = y + 1, 1
        else:
            ny, nm = y, m + 1
        from datetime import timedelta
        return (date(ny, nm, 1) - timedelta(days=1)).isoformat()
    return s


def media_root() -> Path:
    """MEDIA_ROOT: 从环境变量取, 默认项目根目录下 media/"""
    return Path(os.getenv("MEDIA_ROOT") or (Path(__file__).resolve().parents[2] / "media"))


def save_upload(content: bytes, filename: str, subdir: str) -> str:
    """上传文件落盘到 MEDIA_ROOT/<subdir>/, 返回相对 key (Django FileField 行为: 重名加随机后缀)"""
    safe_name = Path(filename or "file").name or "file"
    base_dir = media_root() / subdir
    base_dir.mkdir(parents=True, exist_ok=True)
    key = f"{subdir}/{safe_name}"
    if (media_root() / key).exists():
        stem, suffix = Path(safe_name).stem, Path(safe_name).suffix
        key = f"{subdir}/{stem}_{uuid.uuid4().hex[:8]}{suffix}"
    (media_root() / key).write_bytes(content)
    return key


def _read_media_bytes(path: str) -> bytes:
    """读取媒体文件字节 (与 Django expense_views._read_media_bytes 本地分支一致)"""
    norm = (path or "").replace("\\", "/").lstrip("/")
    image_path = media_root() / norm
    if not image_path.exists():
        alt_path = media_root() / "files" / Path(norm).name
        if alt_path.exists():
            image_path = alt_path
    with open(image_path, "rb") as f:
        return f.read()


def convert_seconds(seconds: int) -> str:
    """与 kdx-be utils.convert_seconds 完全一致: '{h}h {m}m'"""
    hours = seconds // 3600
    minute = (seconds % 3600) // 60
    return "{}h {}m".format(hours, minute)


# ══════════════════════════════════════════════
# 宝宝信息 /baby/info
# ══════════════════════════════════════════════

def _babyinfo_dict(obj: BabyInfo) -> dict:
    key = obj.image or ""
    if key:
        image = f"/file/r?key={quote(key)}"
        # 与 Django 一致: image_full 用于 <img src> 直接渲染;
        # 未启用 S3 直链时回退到 /file/r 重定向 (与 image 相同),
        # 而非裸 key (裸 key 会被浏览器当相对路径 → 404)
        image_full = image
        image_thumb = f"/file/r?key={quote(f'baby/thumbs/bi_{obj.id}_w200')}"
    else:
        image = ""
        image_full = ""
        image_thumb = ""
    if obj.birthday:
        status = "育儿中" if obj.birthday <= date.today() else "待产中"
    else:
        status = "备孕中"
    return {
        "id": obj.id,
        "user": obj.user_id,
        "name": obj.name,
        "birthday": _iso(obj.birthday),
        "birth_weight": obj.birth_weight,
        "birth_height": obj.birth_height,
        "gender": obj.gender,
        "image": image,
        "image_full": image_full,
        "image_thumb": image_thumb,
        "status": status,
        "birth_week": obj.birth_week,
        "is_sensitive": obj.is_sensitive,
        "is_only_child": obj.is_only_child,
    }


def get_baby_info(db: Session, user_id: int) -> dict:
    obj = db.query(BabyInfo).filter(BabyInfo.user_id == user_id).first()
    if not obj:
        return {"code": 200, "data": None, "msg": "No baby info found"}
    return {"code": 200, "data": _babyinfo_dict(obj), "msg": "success"}


def save_baby_info(db: Session, user_id: int, data: dict, image_key: str | None) -> dict:
    """创建或更新宝宝信息 (原视图: 有则部分更新, 无则新建)"""
    instance = db.query(BabyInfo).filter(BabyInfo.user_id == user_id).first()
    today = date.today()
    if instance is None:
        instance = BabyInfo(
            user_id=user_id,
            name=str(data.get("name") or ""),
            birthday=_parse_date(data.get("birthday")) or today,
            birth_weight=int(data.get("birth_weight") or 0),
            birth_height=int(data.get("birth_height") or 0),
            gender=str(data.get("gender") or "F"),
            birth_week=int(data.get("birth_week") or 40),
            is_sensitive=bool(data.get("is_sensitive") or False),
            is_only_child=bool(data.get("is_only_child") or False),
            created_at=today,
            updated_at=today,
        )
    else:
        if "name" in data:
            instance.name = str(data.get("name") or "")
        if "birthday" in data and _parse_date(data.get("birthday")):
            instance.birthday = _parse_date(data.get("birthday"))
        if "birth_weight" in data and data.get("birth_weight") is not None:
            instance.birth_weight = int(data.get("birth_weight"))
        if "birth_height" in data and data.get("birth_height") is not None:
            instance.birth_height = int(data.get("birth_height"))
        if "gender" in data and data.get("gender"):
            instance.gender = str(data.get("gender"))
        if "birth_week" in data and data.get("birth_week") is not None:
            instance.birth_week = int(data.get("birth_week"))
        if "is_sensitive" in data:
            instance.is_sensitive = bool(data.get("is_sensitive"))
        if "is_only_child" in data:
            instance.is_only_child = bool(data.get("is_only_child"))
        instance.updated_at = today
    if image_key is not None:
        instance.image = image_key
    db.add(instance)
    db.commit()
    db.refresh(instance)
    return {"code": 200, "msg": "ok", "data": _babyinfo_dict(instance)}


# ══════════════════════════════════════════════
# 喂奶图表 (dashboard 与 /baby/feed_chart 共用, 原 breast_feed_views.process_feed_chart)
# ══════════════════════════════════════════════

def process_feed_chart(db: Session, user_id: int) -> dict:
    chart_data = {
        "current_day": {"xAxisData": [], "lowData": [], "highData": [], "actualData": [], "titleText": "今日奶量",
                        "yMin": 0},
        "latest_week": {"xAxisData": [], "lowData": [], "highData": [], "actualData": [], "titleText": "近15天",
                        "yMin": 600},
        "basic_info": {"milkVolumes": 0, "refermilkVolumes": "800-1000"},
    }
    today = date.today()

    total = db.query(func.coalesce(func.sum(FeedMilk.milk_volume), 0)).filter(
        FeedMilk.user_id == user_id, func.date(FeedMilk.feed_time) == today).scalar()
    chart_data["basic_info"]["milkVolumes"] = int(total or 0)

    current_qs = (db.query(FeedMilk)
                  .filter(FeedMilk.user_id == user_id, func.date(FeedMilk.feed_time) == today)
                  .order_by(FeedMilk.feed_time))
    for obj in current_qs:
        chart_data["current_day"]["lowData"].append(120)
        chart_data["current_day"]["highData"].append(210)
        chart_data["current_day"]["xAxisData"].append(obj.feed_time.strftime("%H:%M"))
        chart_data["current_day"]["actualData"].append(obj.milk_volume)

    start_date = today - timedelta(days=14)
    rows = (db.query(
        func.date(FeedMilk.feed_time).label("day"),
        func.sum(FeedMilk.milk_volume).label("day_volumes"))
        .filter(FeedMilk.user_id == user_id,
                func.date(FeedMilk.feed_time) >= start_date,
                func.date(FeedMilk.feed_time) <= today)
        .group_by(func.date(FeedMilk.feed_time))
        .order_by(func.date(FeedMilk.feed_time)))
    for row in rows:
        d, v = row.day, row.day_volumes
        chart_data["latest_week"]["lowData"].append(800)
        chart_data["latest_week"]["highData"].append(1000)
        chart_data["latest_week"]["xAxisData"].append(d.isoformat() if d else "")
        chart_data["latest_week"]["actualData"].append(int(v) if v is not None else 0)
    return chart_data


# ══════════════════════════════════════════════
# dashboard /baby/dashboard
# ══════════════════════════════════════════════

def dashboard_save_order(db: Session, user_id: int, app_order) -> dict:
    """保存用户首页应用排序偏好"""
    if not app_order or not isinstance(app_order, list):
        return {"code": 400, "msg": "Invalid app_order format", "data": None}
    user_order = db.query(UserAppOrder).filter(UserAppOrder.user_id == user_id).first()
    if user_order is None:
        user_order = UserAppOrder(user_id=user_id, order=app_order, updated_at=datetime.now())
    else:
        user_order.order = app_order
        user_order.updated_at = datetime.now()
    db.add(user_order)
    db.commit()
    return {"code": 200, "msg": "Order saved successfully", "data": None}


def dashboard_overview(db: Session, user_id: int) -> dict:
    """首页看板: 近一周奶量总和 / 总消费 / 今日尿不湿片数 / 今日体温"""
    today = date.today()
    basic_info = {}

    user_order = db.query(UserAppOrder).filter(UserAppOrder.user_id == user_id).first()
    basic_info["app_order"] = user_order.order if user_order else []

    total_milk = db.query(func.coalesce(func.sum(FeedMilk.milk_volume), 0)).filter(
        FeedMilk.user_id == user_id, func.date(FeedMilk.feed_time) == today).scalar()
    basic_info["total_milk_volumes"] = int(total_milk or 0)

    total_amount = db.query(func.sum(BabyExpense.amount)).filter(BabyExpense.user_id == user_id).scalar()
    basic_info["total_amount"] = _dec_float(total_amount) if total_amount is not None else 0

    current_temp = (db.query(Temperature).filter(Temperature.user_id == user_id,
                                                 Temperature.measure_date == today)
                    .order_by(Temperature.id.desc()).first())
    basic_info["current_temperature"] = current_temp.temperature if current_temp else "未测"

    basic_info["babyPantsCount"] = db.query(BabyDiapers).filter(
        BabyDiapers.user_id == user_id, func.date(BabyDiapers.use_date) == today).count()

    chart_data = process_feed_chart(db, user_id)
    return {"code": 200, "data": {"basicInfo": basic_info, "charData": chart_data}, "msg": "ok"}


# ══════════════════════════════════════════════
# 成长博客 /baby/growing, /baby/ai_gen
# ══════════════════════════════════════════════

_RICH_TEXT_FILE_SRC_RE = re.compile(r'(?P<base>(?:https?://[^"\'<>\s]+)?)'
                                    r'(?P<api>/prod-api)?/media/(?P<key>files/[^"\'<>\s]+)')


def _rewrite_rich_text_media(html: str) -> str:
    """富文本里的 /media/files/... 地址改写为 /file/r 代理地址 (与 DRF 序列化器一致)"""
    if not html:
        return html
    if "/file/r" in html:
        return html

    def _sub(m):
        base, api, key = m.group("base") or "", m.group("api") or "", m.group("key") or ""
        return f"{base}{api}/file/r?key={quote(key)}"

    return _RICH_TEXT_FILE_SRC_RE.sub(_sub, html)


def _growing_blog_dict(obj: GrowingBlogModel) -> dict:
    return {
        "id": obj.id,
        "title": obj.title,
        "content": _rewrite_rich_text_media(obj.content or ""),
        "created_time": _iso(obj.created_time),
        "updated_time": _iso(obj.updated_time),
        "number_of_comments": obj.number_of_comments,
        "number_of_pingbacks": obj.number_of_pingbacks,
        "rating": obj.rating,
    }


def growing_blog_list(db: Session, user_id: int) -> dict:
    objs = db.query(GrowingBlogModel).filter(GrowingBlogModel.user_id == user_id).order_by(GrowingBlogModel.id.desc())
    return {"code": 200, "data": [_growing_blog_dict(o) for o in objs], "msg": "fetch all success"}


def growing_blog_create(db: Session, user_id: int, data: dict) -> dict:
    try:
        today = date.today()
        obj = GrowingBlogModel(
            user_id=user_id,
            title=str(data.get("title") or ""),
            content=data.get("content"),
            created_time=today,
            updated_time=today,
        )
        db.add(obj)
        db.commit()
        return {"code": 200, "msg": "ok", "data": None}
    except Exception as exc:
        db.rollback()
        logger.exception("GrowingBlog create error")
        return {"code": 205, "msg": str(exc), "data": None}


def growing_blog_delete(db: Session, blog_id) -> dict:
    obj = db.query(GrowingBlogModel).filter(GrowingBlogModel.id == blog_id).first()
    if not obj:
        return {"code": 404, "data": None, "msg": "not found"}
    db.delete(obj)
    db.commit()
    return {"code": 200, "data": None, "msg": "ok"}


def ai_gen(data: dict) -> dict:
    """AI 生成标题+文章 (原 AIGenView: langchain ChatOpenAI → dashscope, json 模式)"""
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI

        content = data.get("content")
        model = ChatOpenAI(
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model=os.getenv("AI_GEN_MODEL", "qwen3.7-plus"),
        ).bind(response_format={"type": "json_object"})
        prompt = f"""根据下面的内容，写一个带有标题不超过200字的文章。\
                    ```{content}```\
                    结果以json格式返回，key 为 title, content
        """
        output = model.invoke([SystemMessage("You are a helpful assistant. Answer all questions to the best of your ability in chinese"),
                               HumanMessage(prompt)])
        return {"code": 200, "msg": "ok", "data": json.loads(output.content)}
    except Exception as exc:
        return {"code": 205, "msg": str(exc), "data": None}


# ══════════════════════════════════════════════
# 待办 /baby/todo, /baby/todo_table, /baby/daily_habit
# ══════════════════════════════════════════════

def _todo_dict(obj: TodoList) -> dict:
    return {
        "id": obj.id,
        "user": obj.user_id,
        "create_time": _iso(obj.create_time),
        "update_time": _iso(obj.update_time),
        "text": obj.text,
        "done": obj.done,
        "is_daily": obj.is_daily,
        "icon": obj.icon,
    }


def _init_daily_items(db: Session, user_id: int) -> None:
    """原 init_items: 无任何习惯则初始化 8 个默认习惯, 再为当天生成待办"""
    has_habits = db.query(DailyHabit).filter(DailyHabit.user_id == user_id).first() is not None
    now = datetime.now()
    if not has_habits:
        default_habits = [
            {"text": "补充AD", "icon": "medication"},
            {"text": "补充钙/铁", "icon": "cube"},
            {"text": "补充益生菌", "icon": "flower-o"},
            {"text": "观察大便", "icon": "smile-o"},
            {"text": "洗澡抚触", "icon": "hot-o"},
            {"text": "亲子阅读", "icon": "book"},
            {"text": "趴卧练习", "icon": "like-o"},
            {"text": "户外活动", "icon": "location-o"},
        ]
        for h in default_habits:
            db.add(DailyHabit(user_id=user_id, text=h["text"], icon=h["icon"], is_active=True,
                              created_at=now, updated_at=now))
        db.commit()
    for habit in db.query(DailyHabit).filter(DailyHabit.user_id == user_id, DailyHabit.is_active):
        db.add(TodoList(user_id=user_id, create_time=date.today(), update_time=date.today(),
                        text=habit.text, done=False, is_daily=True, icon=habit.icon))
    db.commit()


def todo_list(db: Session, user_id: int, start_date, end_date) -> dict:
    today = date.today().strftime("%Y-%m-%d")
    # Django ORM 对 create_time__gte=None 容忍 (SQL 与 NULL 比较恒空集);
    # SQLAlchemy 会抛 ArgumentError, 故按原语义: 缺参 → 空集
    if start_date is None or end_date is None:
        return {"code": 200, "data": [], "msg": "ok"}
    q = (db.query(TodoList)
         .filter(TodoList.user_id == user_id,
                 TodoList.create_time >= start_date, TodoList.create_time <= end_date))
    # 查当天且为空 → 从习惯初始化 (原行为)
    if str(start_date) == str(end_date) and str(start_date) == today and q.count() == 0:
        _init_daily_items(db, user_id)
        q = (db.query(TodoList)
             .filter(TodoList.user_id == user_id,
                     TodoList.create_time >= start_date, TodoList.create_time <= end_date))
    return {"code": 200, "data": [_todo_dict(o) for o in q], "msg": "ok"}


def todo_create(db: Session, user_id: int, data: dict) -> dict:
    obj = TodoList(
        user_id=user_id,
        create_time=date.today(),
        update_time=date.today(),
        text=data.get("text"),
        done=data.get("done", False) or False,
        is_daily=data.get("is_daily", False) or False,
        icon=data.get("icon", ""),
    )
    db.add(obj)
    db.commit()
    return {"code": 200, "data": None, "msg": "ok"}


def todo_update(db: Session, user_id: int, data: dict) -> dict:
    task_id = data.get("id")
    obj = db.query(TodoList).filter(TodoList.id == task_id, TodoList.user_id == user_id).first()
    if not obj:
        return {"code": 404, "msg": "Todo not found"}
    if "text" in data:
        obj.text = data.get("text")
    if "done" in data:
        obj.done = data.get("done")
    if "is_daily" in data:
        obj.is_daily = data.get("is_daily")
    if "icon" in data:
        obj.icon = data.get("icon")
    obj.update_time = date.today()
    db.commit()
    return {"code": 200, "data": None, "msg": "ok"}


def todo_delete(db: Session, user_id: int, task_id) -> dict:
    obj = db.query(TodoList).filter(TodoList.id == task_id, TodoList.user_id == user_id).first()
    if not obj:
        return {"code": 404, "msg": "Todo not found"}
    db.delete(obj)
    db.commit()
    return {"code": 200, "data": None, "msg": "ok"}


def todo_table(db: Session, user_id: int, start_date, end_date) -> dict:
    """按日期分组的待办表格视图 (缺参 → 空集, 与 Django NULL 比较语义一致)"""
    if start_date is None or end_date is None:
        return {"code": 200, "data": [], "msg": "ok"}
    rows = (db.query(TodoList)
            .filter(TodoList.user_id == user_id,
                    TodoList.create_time >= start_date, TodoList.create_time <= end_date)
            .order_by(TodoList.create_time))
    data = [{"create_time": _iso(o.create_time), "text": o.text, "done": o.done,
             "is_daily": o.is_daily, "icon": o.icon} for o in rows]
    aim_list = []
    seen = {}
    for item in data:
        key = item["create_time"]
        if key not in seen:
            seen[key] = {"date": key, "date_items": []}
            aim_list.append(seen[key])
        seen[key]["date_items"].append(item)
    aim_list.reverse()
    return {"code": 200, "data": aim_list, "msg": "ok"}


def _habit_dict(obj: DailyHabit) -> dict:
    return {
        "id": obj.id,
        "user": obj.user_id,
        "text": obj.text,
        "icon": obj.icon,
        "is_active": obj.is_active,
        "created_at": _iso(obj.created_at),
        "updated_at": _iso(obj.updated_at),
    }


def habit_list(db: Session, user_id: int) -> dict:
    objs = db.query(DailyHabit).filter(DailyHabit.user_id == user_id, DailyHabit.is_active)
    return {"code": 200, "data": [_habit_dict(o) for o in objs], "msg": "ok"}


def habit_create(db: Session, user_id: int, data: dict) -> dict:
    now = datetime.now()
    habit = DailyHabit(user_id=user_id, text=data.get("text"), icon=data.get("icon"),
                       is_active=True, created_at=now, updated_at=now)
    db.add(habit)
    db.commit()
    # 习惯创建后立即生成今天的待办 (原行为)
    db.add(TodoList(user_id=user_id, create_time=date.today(), update_time=date.today(),
                    text=habit.text, done=False, is_daily=True, icon=habit.icon))
    db.commit()
    return {"code": 200, "msg": "Habit added"}


def habit_update(db: Session, user_id: int, data: dict) -> dict:
    habit_id = data.get("id")
    habit = db.query(DailyHabit).filter(DailyHabit.id == habit_id, DailyHabit.user_id == user_id).first()
    if not habit:
        return {"code": 404, "msg": "Habit not found"}
    old_text = habit.text
    if "text" in data:
        habit.text = data.get("text")
    if "icon" in data:
        habit.icon = data.get("icon")
    if "is_active" in data:
        habit.is_active = data.get("is_active")
    habit.updated_at = datetime.now()
    db.commit()

    today = date.today()
    if not habit.is_active:
        # 停用 (软删除) → 删除今天未完成的对应待办
        (db.query(TodoList)
         .filter(TodoList.user_id == user_id, TodoList.text == old_text, TodoList.is_daily,
                 TodoList.create_time == today, TodoList.done.is_(False))
         .delete(synchronize_session=False))
        db.commit()
    else:
        # 文案/图标变化 → 同步今天的待办
        todo_qs = (db.query(TodoList)
                   .filter(TodoList.user_id == user_id, TodoList.text == old_text,
                           TodoList.is_daily, TodoList.create_time == today))
        if todo_qs.first() is not None:
            todo_qs.update({TodoList.text: habit.text, TodoList.icon: habit.icon},
                           synchronize_session=False)
            db.commit()
    return {"code": 200, "msg": "Habit updated"}


def habit_delete(db: Session, user_id: int, habit_id) -> dict:
    habit = db.query(DailyHabit).filter(DailyHabit.id == habit_id, DailyHabit.user_id == user_id).first()
    if not habit:
        return {"code": 404, "msg": "Habit not found"}
    db.delete(habit)
    db.commit()
    return {"code": 200, "msg": "Habit deleted"}


# ══════════════════════════════════════════════
# 喂奶 /baby/feed, /baby/feed_chart
# ══════════════════════════════════════════════

def _feed_dict(obj: FeedMilk) -> dict:
    return {
        "id": obj.id,
        "user": obj.user_id,
        "feed_time": _iso(obj.feed_time),
        "milk_volume": obj.milk_volume,
        "time_different": _iso(obj.time_different),
        "feed_type": obj.feed_type,
        "duration_total": obj.duration_total,
        "left_duration": obj.left_duration,
        "right_duration": obj.right_duration,
        "note": obj.note,
    }


def feed_list(db: Session, user_id: int, start_time, end_time) -> dict:
    """喂奶列表: 相邻记录时间差 + 追加 '还没吃' 伪记录 (原视图逻辑)"""
    try:
        start_dt, end_dt = _parse_dt(start_time), _parse_dt(end_time)
        objs = (db.query(FeedMilk)
                .filter(FeedMilk.user_id == user_id,
                        FeedMilk.feed_time >= start_dt, FeedMilk.feed_time <= end_dt)
                .order_by(FeedMilk.feed_time))
        result_data = [_feed_dict(o) for o in objs]
        if len(result_data) == 0:
            return {"code": 200, "data": [], "msg": "fetch all success"}

        pre_time = None
        for item in result_data:
            if pre_time is None:
                item["time_different"] = "起点顿"
                pre_time = _parse_dt(item.get("feed_time"))
            else:
                this_feed_time = _parse_dt(item.get("feed_time"))
                time_different = this_feed_time - pre_time
                item["time_different"] = convert_seconds(time_different.seconds)
                pre_time = this_feed_time

        now_time = datetime.now()
        time_different = now_time - pre_time
        result_data.append({"feed_time": now_time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "milk_volume": "还没吃",
                            "time_different": convert_seconds(time_different.seconds)})
        result_data.reverse()
        return {"code": 200, "data": result_data, "msg": "fetch all success"}
    except Exception as exc:
        logger.error(str(exc))
        return {"code": 205, "data": None, "msg": str(exc)}


def _feed_fields(data: dict) -> dict:
    """原视图 POST/PUT 共用的字段组装 (int() 容错)"""
    return {
        "feed_time": _parse_dt(data.get("feed_time")),
        "milk_volume": int(data.get("milk_volume") or 0),
        "feed_type": data.get("feed_type", "bottle") or "bottle",
        "duration_total": int(data.get("duration_total") or 0),
        "left_duration": int(data.get("left_duration") or 0),
        "right_duration": int(data.get("right_duration") or 0),
        "note": data.get("note", "") if data.get("note", "") is not None else "",
    }


def feed_create(db: Session, user_id: int, data: dict) -> dict:
    if not _parse_dt(data.get("feed_time")):
        return {"code": 205, "msg": "feed_time 必填", "data": None}
    fields = _feed_fields(data)
    db.add(FeedMilk(user_id=user_id, **fields))
    db.commit()
    return {"code": 200, "msg": "ok", "data": None}


def feed_update(db: Session, user_id: int, data: dict) -> dict:
    feed_obj = db.query(FeedMilk).filter(FeedMilk.id == data.get("id"), FeedMilk.user_id == user_id).first()
    if not feed_obj:
        return {"code": 404, "msg": "Record not found", "data": None}
    for k, v in _feed_fields(data).items():
        setattr(feed_obj, k, v)
    db.commit()
    return {"code": 200, "msg": "ok", "data": None}


def feed_delete(db: Session, feed_id) -> dict:
    obj = db.query(FeedMilk).filter(FeedMilk.id == feed_id).first()
    if not obj:
        return {"code": 404, "data": None, "msg": "not found"}
    db.delete(obj)
    db.commit()
    return {"code": 200, "data": None, "msg": "ok"}


def feed_chart(db: Session, user_id: int) -> dict:
    return {"code": 200, "data": process_feed_chart(db, user_id), "msg": "fetch all success"}


# ══════════════════════════════════════════════
# 体温 /baby/temperature
# ══════════════════════════════════════════════

def _temperature_dict(obj: Temperature) -> dict:
    return {
        "id": obj.id,
        "user": obj.user_id,
        "measure_date": _iso(obj.measure_date),
        "temperature": obj.temperature,
        "status": obj.status,
    }


def temperature_list(db: Session, user_id: int, start_date, end_date) -> dict:
    if not start_date or not end_date:
        today = date.today()
        end_date = today
        start_date = today - timedelta(days=7)
    objs = (db.query(Temperature)
            .filter(Temperature.user_id == user_id,
                    Temperature.measure_date >= _parse_date(start_date),
                    Temperature.measure_date <= _parse_date(end_date))
            .order_by(Temperature.measure_date.desc()))
    current_temp = (db.query(Temperature).filter(Temperature.user_id == user_id,
                                                 Temperature.measure_date == date.today())
                    .order_by(Temperature.id.desc()).first())
    current_temperature = current_temp.temperature if current_temp else "未测"
    return {"code": 200, "data": {"results": [_temperature_dict(o) for o in objs],
                                  "temperature": current_temperature}, "msg": "ok"}


def temperature_create(db: Session, user_id: int, data: dict) -> dict:
    try:
        measure_date = _parse_date(data.get("measure_date"))
        if not measure_date:
            raise ValueError("measure_date 必填")
        try:
            temperature = float(data.get("temperature"))
        except (ValueError, TypeError):
            return {"code": 400, "msg": "Invalid temperature value", "data": None}

        # 状态判定与原视图完全一致
        if temperature <= 36.0:
            status = "低温"
        elif 36.0 < temperature < 37.0:
            status = "正常"
        elif temperature >= 37.0:
            status = "偏高"
        else:
            status = "异常"
        db.add(Temperature(user_id=user_id, measure_date=measure_date,
                           temperature=str(temperature), status=status))
        db.commit()
        return {"code": 200, "msg": "ok", "data": None}
    except Exception as exc:
        db.rollback()
        return {"code": 205, "msg": str(exc), "data": None}


def temperature_delete(db: Session, temp_id) -> dict:
    obj = db.query(Temperature).filter(Temperature.id == temp_id).first()
    if not obj:
        return {"code": 404, "data": None, "msg": "not found"}
    db.delete(obj)
    db.commit()
    return {"code": 200, "data": None, "msg": "ok"}


# ══════════════════════════════════════════════
# 尿不湿 /baby/pants
# ══════════════════════════════════════════════

_STATUS_MAP = {"peeing": "嘘嘘", "stool": "便便", "peeing-stool": "嘘嘘+便便", "dry": "干爽"}


def _diapers_dict(obj: BabyDiapers) -> dict:
    return {
        "id": obj.id,
        "user": obj.user_id,
        "use_date": _iso(obj.use_date),
        "brand": obj.brand,
        "tabActiveName": obj.tabActiveName,
        "is_leaked": obj.is_leaked,
        "peeing_color": obj.peeing_color,
        "stool_shape": obj.stool_shape,
        "stool_color": obj.stool_color,
        "describe": obj.describe,
    }


def pants_list(db: Session, user_id: int, use_date, page: int, page_size: int) -> dict:
    queryset = db.query(BabyDiapers).filter(BabyDiapers.user_id == user_id).order_by(BabyDiapers.use_date.desc())
    if use_date and use_date not in ("null", "undefined"):
        parsed = _parse_date(use_date)
        if parsed:
            queryset = queryset.filter(func.date(BabyDiapers.use_date) == parsed)

    total = queryset.count()
    start = (max(page, 1) - 1) * page_size
    page_objs = queryset[start:start + page_size]

    status_list = []
    for item in page_objs:
        status = item.tabActiveName
        item_dict = {"id": item.id, "status": _STATUS_MAP.get(status), "describe": item.describe,
                     "use_date": _iso(item.use_date)}
        if status == "peeing":
            item_dict["peeing"] = item.peeing_color
        elif status == "stool":
            item_dict["stool"] = str(item.stool_color or "") + str(item.stool_shape or "")
        elif status == "peeing-stool":
            item_dict["peeing"] = item.peeing_color
            item_dict["stool"] = str(item.stool_color or "") + str(item.stool_shape or "")
        status_list.append(item_dict)
    return {"code": 200, "data": {"results": status_list, "count": total}, "msg": "fetch all success"}


def pants_create(db: Session, user_id: int, data: dict) -> dict:
    try:
        use_date = _parse_dt(data.get("use_date"))
        if not use_date:
            raise ValueError("use_date 必填")
        stool_shape_list = data.get("stool_shape_list")
        stool_shape = "#".join(str(x) for x in stool_shape_list) if stool_shape_list else ""
        is_leaked = data.get("is_leaked")
        obj = BabyDiapers(
            user_id=user_id,
            use_date=use_date,
            brand=data.get("brand"),
            tabActiveName=data.get("tabActiveName"),
            peeing_color=str(data.get("peeing_color")) if data.get("peeing_color") is not None else None,
            stool_shape=stool_shape or None,
            stool_color=str(data.get("stool_color")) if data.get("stool_color") is not None else None,
            describe=data.get("describe"),
            is_leaked=str(is_leaked) if is_leaked is not None else "false",
        )
        db.add(obj)
        db.commit()
        return {"code": 200, "msg": "ok", "data": None}
    except Exception as exc:
        db.rollback()
        logger.exception("BabyPants create error")
        return {"code": 205, "msg": str(exc), "data": None}


def pants_delete(db: Session, pants_id) -> dict:
    obj = db.query(BabyDiapers).filter(BabyDiapers.id == pants_id).first()
    if not obj:
        return {"code": 404, "data": None, "msg": "not found"}
    db.delete(obj)
    db.commit()
    return {"code": 200, "data": None, "msg": "ok"}


# ══════════════════════════════════════════════
# 折线图 /baby/line_chart (原 views.LineChartView)
# ══════════════════════════════════════════════

def _process_chart_data(data: list, chart_type: str, need_total: bool = False):
    """原 LineChartView.process_chartData 逐字段复刻"""
    total_count = 0
    x_axis_data = []
    actual_data = []

    if chart_type == "milkVolumes":
        x_axis_name, actual_name, expected_count = "feed_time", "milk_volume", 150
    elif chart_type == "temperature":
        x_axis_name, actual_name, expected_count = "measure_date", "temperature", "36.7"
    elif chart_type == "babyPants":
        x_axis_name, actual_name, expected_count = "use_date", "is_leaked", False
    else:
        x_axis_name, actual_name, expected_count = "order_time", "amount", 3000

    expected_data = [expected_count] * len(data)
    for item in data:
        x_axis_data.append(item[x_axis_name])
        if need_total:
            actual = int(item[actual_name])
            total_count += actual
        else:
            actual = item[actual_name]
        actual_data.append(actual)
    return {"xAxisData": x_axis_data, "expectedData": expected_data, "actualData": actual_data}, total_count


def line_chart(db: Session, user_id: int) -> dict:
    date_time = datetime.now().strftime("%Y-%m-%d 00:00:00")
    today = datetime.now().date()

    total_chart_data = {
        "milkVolumes": {"xAxisData": [], "expectedData": [], "actualData": []},
        "temperature": {"xAxisData": [], "expectedData": [], "actualData": []},
        "babyPants": {"xAxisData": [], "expectedData": [], "actualData": []},
        "purchases": {"xAxisData": [], "expectedData": [], "actualData": []},
    }

    # 奶量 (今日)
    queryset = (db.query(FeedMilk).filter(FeedMilk.user_id == user_id, FeedMilk.feed_time >= date_time)
                .order_by(FeedMilk.feed_time))
    milk_data = [_feed_dict(o) for o in queryset]
    milk_chart, milk_total = _process_chart_data(data=milk_data, chart_type="milkVolumes", need_total=True)
    total_chart_data["milkVolumes"] = milk_chart

    # 体温 (今日 + 一周)
    t = (db.query(Temperature).filter(Temperature.user_id == user_id, Temperature.measure_date == today)
         .order_by(Temperature.id.desc()).first())
    temperature = t.temperature if t else "未测"
    week_start = today - timedelta(days=7)
    week_objs = (db.query(Temperature)
                 .filter(Temperature.user_id == user_id,
                         Temperature.measure_date >= week_start, Temperature.measure_date <= today)
                 .order_by(Temperature.measure_date.desc()))
    temperature_data = [_temperature_dict(o) for o in week_objs]
    temperature_data.reverse()
    temp_chart, _ = _process_chart_data(data=temperature_data, chart_type="temperature", need_total=False)
    total_chart_data["temperature"] = temp_chart

    # 尿不湿 (今日)
    bp_objs = (db.query(BabyDiapers).filter(BabyDiapers.user_id == user_id, BabyDiapers.use_date >= date_time)
               .order_by(BabyDiapers.use_date))
    bp_count = len(bp_objs.all())
    bp_chart, _ = _process_chart_data(data=[_diapers_dict(o) for o in bp_objs], chart_type="babyPants")
    total_chart_data["babyPants"] = bp_chart

    response_data = {
        "basicInfo": {"milkVolumes": milk_total, "temperature": temperature, "babyPants": bp_count},
        "totalLineChartData": total_chart_data,
    }
    return {"code": 200, "msg": "ok", "data": response_data}


# ══════════════════════════════════════════════
# 花费 /baby/expense*, /baby/expense_tags, /baby/batch_expense
# ══════════════════════════════════════════════

def _expense_dict(obj: BabyExpense) -> dict:
    """含 image_url_full 的花费序列化 (本地媒体分支)"""
    raw = str(obj.image_url or "").strip()
    image_url_full = ""
    if raw:
        if raw.startswith("data:image/"):
            image_url_full = raw
        elif raw.startswith("http://") or raw.startswith("https://"):
            if "/media/" not in raw:
                image_url_full = raw
            else:
                raw = raw.split("/media/", 1)[1]
        if not image_url_full:
            key = raw.replace("\\", "/")
            if "/media/" in key:
                key = key.split("/media/", 1)[1]
            key = key.lstrip("/")
            image_url_full = f"/file/r?key={quote(key)}" if key else ""
    return {
        "id": obj.id,
        "user": obj.user_id,
        "order_time": _iso(obj.order_time),
        "name": obj.name,
        "amount": _dec_str(obj.amount),
        "tag": obj.tag,
        "expense_type": obj.expense_type,
        "image_url": obj.image_url,
        "create_time": _iso(obj.create_time),
        "update_time": _iso(obj.update_time),
        "image_url_full": image_url_full,
    }


def expense_list(db: Session, user_id: int, params: dict) -> dict:
    """花费列表 + 区间/累计统计 + 分页 (原 ExpenseListView.post)"""
    page_size = params.get("page_size", 20)
    page_num = params.get("page_num", 1)

    query = db.query(BabyExpense).filter(BabyExpense.user_id == user_id)
    if params.get("name"):
        query = query.filter(BabyExpense.name.contains(params.get("name")))
    if params.get("expense_type") and params.get("expense_type") in ["income", "expense"]:
        query = query.filter(BabyExpense.expense_type == params.get("expense_type"))
    if params.get("monthrange"):
        start_date = params.get("monthrange")[0]
        end_date = params.get("monthrange")[1]
        # 前端 vant MonthPicker 传 "YYYY-MM", MySQL 不接受 "2025-02 00:00:00";
        # 转成完整日期: 起始 = 月初, 结束 = 月末
        start_date = _month_to_first_day(start_date)
        end_date = _month_to_last_day(end_date)
        query = query.filter(BabyExpense.order_time >= f"{start_date} 00:00:00",
                             BabyExpense.order_time <= f"{end_date} 23:59:59")
    # 关键: order_time 相同的行, MySQL 不保证顺序 → LIMIT/OFFSET 分页时同一行
    # 可能出现在不同页 → 前端 append 后 Vue duplicate keys。加 id 做稳定排序。
    query = query.order_by(BabyExpense.order_time.desc(), BabyExpense.id.desc())

    # 区间统计: 用子查询复用过滤条件 (不能直接用 query.whereclause, 版本不兼容)
    filtered_ids = query.with_entities(BabyExpense.id).subquery()
    range_income = db.query(func.coalesce(func.sum(BabyExpense.amount), 0)).filter(
        BabyExpense.id.in_(filtered_ids), BabyExpense.expense_type == "income").scalar()
    range_expense = db.query(func.coalesce(func.sum(BabyExpense.amount), 0)).filter(
        BabyExpense.id.in_(filtered_ids), BabyExpense.expense_type == "expense").scalar()

    all_income = db.query(func.coalesce(func.sum(BabyExpense.amount), 0)).filter(
        BabyExpense.user_id == user_id, BabyExpense.expense_type == "income").scalar()
    all_expense = db.query(func.coalesce(func.sum(BabyExpense.amount), 0)).filter(
        BabyExpense.user_id == user_id, BabyExpense.expense_type == "expense").scalar()

    start = (page_num - 1) * page_size
    total = query.count()
    page_data = query[start:start + page_size]

    return {
        "code": 200,
        "data": {
            "list": [_expense_dict(o) for o in page_data],
            "total": total,
            "all_income": _dec_float(all_income) or 0,
            "all_expense": _dec_float(all_expense) or 0,
            "range_income": _dec_float(range_income) or 0,
            "range_expense": _dec_float(range_expense) or 0,
        },
        "msg": "ok",
    }


def expense_get_today_todos(db: Session, user_id: int) -> dict:
    """原 ExpenseView.get 返回的其实是当天待办 (保持原行为)"""
    create_time = datetime.now().date().strftime("%Y-%m-%d")
    objs = (db.query(TodoList).filter(TodoList.user_id == user_id, TodoList.create_time == create_time))
    return {"code": 200, "data": [_todo_dict(o) for o in objs], "msg": "ok"}


def expense_create(db: Session, user_id: int, data: dict) -> dict:
    order_time = _parse_dt(data.get("order_time"))
    if not order_time:
        return {"code": 205, "msg": "order_time 必填", "data": None}
    amount = data.get("amount")
    db.add(BabyExpense(
        user_id=user_id,
        order_time=order_time,
        name=data.get("name"),
        amount=Decimal(str(amount)) if amount is not None else Decimal("0"),
        tag=data.get("tag"),
        expense_type=data.get("expense_type", "expense") or "expense",
        image_url=data.get("image_url"),
        create_time=date.today(),
        update_time=date.today(),
    ))
    db.commit()
    return {"code": 200, "data": None, "msg": "ok"}


def expense_update(db: Session, user_id: int, data: dict) -> dict:
    pk = data.get("id")
    if not pk:
        return {"code": 400, "msg": "id is required"}
    obj = db.query(BabyExpense).filter(BabyExpense.id == pk, BabyExpense.user_id == user_id).first()
    if not obj:
        return {"code": 404, "msg": "not found"}
    if "order_time" in data:
        parsed = _parse_dt(data.get("order_time"))
        if parsed:
            obj.order_time = parsed
    if "name" in data:
        obj.name = data.get("name", obj.name)
    if "amount" in data and data.get("amount") is not None:
        obj.amount = Decimal(str(data.get("amount")))
    if "tag" in data:
        obj.tag = data.get("tag", obj.tag)
    if "expense_type" in data and data.get("expense_type"):
        obj.expense_type = data.get("expense_type")
    if "image_url" in data:
        obj.image_url = data.get("image_url", obj.image_url)
    obj.update_time = date.today()
    db.commit()
    return {"code": 200, "data": None, "msg": "ok"}


def batch_delete_expense(db: Session, user_id: int, ids) -> dict:
    if isinstance(ids, list) and ids:
        (db.query(BabyExpense).filter(BabyExpense.user_id == user_id, BabyExpense.id.in_(ids))
         .delete(synchronize_session=False))
        db.commit()
    return {"code": 200, "data": None, "msg": "ok"}


def batch_expense(db: Session, user_id: int, data: dict) -> dict:
    """批量识别小票图片 → AI 解析商品/金额 → 建花费记录 (原 BatchExpenseView)"""
    import base64
    import concurrent.futures

    file_list = data.get("fileList") or []

    def process_image_msg(path):
        """单张图片: 读文件 → base64 → LLM 视觉解析 → 入库"""
        from langchain_core.messages import HumanMessage
        from langchain_openai import ChatOpenAI

        thread_id = uuid.uuid1()
        path = (path or "").replace("\\", "/")
        image_type = os.path.splitext(path)[1].lower().lstrip(".") or "jpeg"
        raw = _read_media_bytes(path)
        base64_image = base64.b64encode(raw).decode("utf-8")

        model = ChatOpenAI(
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model=os.getenv("AI_VISION_MODEL", "qwen-vl-max"),
        ).bind(response_format={"type": "json_object"})
        message = [HumanMessage(content=[
            {"type": "text",
             "text": "describe product name if there are multiple merge lines,product category,pay amount ignore money units and pay time"},
            {"type": "image_url", "image_url": {"url": f"data:image/{image_type};base64,{base64_image}"}},
        ])]
        output = model.invoke(message)
        model_content = json.loads(output.content)

        db.add(BabyExpense(
            user_id=user_id,
            order_time=_parse_dt(model_content.get("pay_time")),
            name=str(model_content.get("product_name")),
            amount=Decimal(str(model_content.get("pay_amount"))) if model_content.get("pay_amount") is not None else Decimal("0"),
            tag=str(model_content.get("product_category")) if model_content.get("product_category") is not None else None,
            image_url=path,
            create_time=date.today(),
            update_time=date.today(),
        ))
        db.commit()
        return f"ok {thread_id}"

    # 线程池并发处理, 单张失败仅记日志 (与原行为一致)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(process_image_msg, item.get("name")): item for item in file_list}
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception:
                logger.exception("Expense image task error: %s", futures[future])

    return {"code": 200, "data": "haha success", "msg": "ok"}


def expense_tag_list(db: Session, user_id: int) -> dict:
    tags = db.query(ExpenseTag.name).filter(ExpenseTag.user_id == user_id)
    return {"code": 200, "data": [t.name for t in tags], "msg": "ok"}


def expense_tag_create(db: Session, user_id: int, name) -> dict:
    if not name:
        return {"code": 400, "msg": "name is required"}
    exists = db.query(ExpenseTag).filter(ExpenseTag.user_id == user_id, ExpenseTag.name == name).first()
    if exists:
        return {"code": 400, "msg": "Tag already exists"}
    db.add(ExpenseTag(user_id=user_id, name=name, created_at=datetime.now()))
    db.commit()
    return {"code": 200, "msg": "ok"}


# ══════════════════════════════════════════════
# 睡眠 /baby/sleep, /baby/sleep_list
# ══════════════════════════════════════════════

def _sleep_dict(obj: SleepLog) -> dict:
    return {
        "id": obj.id,
        "user": obj.user_id,
        "sleep_time": _iso(obj.sleep_time),
        "status": obj.status,
        "describe": obj.describe,
        "duration": obj.duration,
    }


def sleep_create(db: Session, user_id: int, data: dict) -> dict:
    sleep_time = _parse_dt(data.get("sleep_time"))
    if not sleep_time:
        return {"code": 205, "msg": "sleep_time 必填", "data": None}
    duration = data.get("duration")
    db.add(SleepLog(
        user_id=user_id,
        sleep_time=sleep_time,
        status=data.get("status"),
        describe=data.get("describe"),
        duration=int(duration) if duration is not None and str(duration) != "" else None,
    ))
    db.commit()
    return {"code": 200, "data": None, "msg": "ok"}


def sleep_list(db: Session, user_id: int, params: dict) -> dict:
    date_value = _parse_date(params.get("date"))
    if not date_value:
        return {"code": 205, "msg": "date 必填", "data": None}
    try:
        page = int(params.get("currentPage", params.get("page_num", 1)))
        page_size = int(params.get("pageSize", params.get("page_size", 10)))
    except (ValueError, TypeError):
        page, page_size = 1, 10

    query = (db.query(SleepLog)
             .filter(SleepLog.user_id == user_id, func.date(SleepLog.sleep_time) == date_value)
             .order_by(SleepLog.sleep_time.desc()))
    count = query.count()
    objs = query[(page - 1) * page_size: page * page_size]
    return {"code": 200, "data": {"results": [_sleep_dict(o) for o in objs], "count": count}, "msg": "ok"}


# ══════════════════════════════════════════════
# 相册 /baby/albums*
# ══════════════════════════════════════════════

def _stream_id_from_key(key: str, fallback: str) -> str:
    """图片 key → 流 ID (文件名安全化, 与 DRF AlbumPhotoSerializer._stream_id 一致)"""
    raw = (key.rsplit("/", 1)[-1].rsplit(".", 1)[0] if key else "").strip()
    if not raw:
        return fallback
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", raw)[:80]
    return safe or fallback


def _photo_dict(obj: AlbumPhoto) -> dict:
    key = obj.image or ""
    sid = _stream_id_from_key(key, str(obj.id))
    base = f"baby_album/thumbs/{sid}_w400"

    image = f"/file/r?key={quote(key)}" if key else ""

    if obj.is_video:
        thumb = ""
    else:
        thumb = f"/file/img?base={quote(base)}" if not key else f"/file/img?base={quote(base)}&src={quote(key)}"

    if obj.is_video:
        hls = (f"/baby/albums/video/{quote(sid)}/hls/master.m3u8" if not key
               else f"/baby/albums/video/{quote(sid)}/hls/master.m3u8?src={quote(key)}")
        dash = (f"/baby/albums/video/{quote(sid)}/dash/manifest.mpd" if not key
                else f"/baby/albums/video/{quote(sid)}/dash/manifest.mpd?src={quote(key)}")
    else:
        hls = ""
        dash = ""

    if not obj.is_video:
        poster = ""
    elif obj.poster:
        poster = f"/file/r?key={quote(obj.poster)}"
    else:
        src = key
        poster = "" if not src else f"/file/r?key={quote(f'baby_album/posters/{sid}.jpg')}&src={quote(src)}"

    return {
        "id": obj.id,
        "image": image,
        "poster": poster,
        "thumb": thumb,
        "hls": hls,
        "dash": dash,
        "is_video": obj.is_video,
        "created_at": _iso(obj.created_at),
    }


def _calc_age_simple(birthday, happened_date) -> str:
    """相册 age_description: 简化年龄计算 (365/30 估算, 与 DRF 序列化器一致)"""
    if not birthday or not happened_date:
        return ""
    if isinstance(happened_date, datetime):
        # datetime 是 date 的子类, 必须先排除再转 date, 否则与 date 比较报错
        happened_date = happened_date.date()
    if happened_date < birthday:
        return "出生前"
    delta_days = (happened_date - birthday).days
    years = delta_days // 365
    remaining_days = delta_days % 365
    months = remaining_days // 30
    days = remaining_days % 30

    parts = []
    if years > 0:
        parts.append(f"{years}岁")
    if months > 0:
        parts.append(f"{months}个月")
    if days > 0:
        parts.append(f"{days}天")
    if not parts:
        return "出生当天"
    return "".join(parts)


def _album_dict(db: Session, obj: BabyAlbum) -> dict:
    baby = db.query(BabyInfo).filter(BabyInfo.user_id == obj.user_id).first()
    age_description = ""
    if baby and baby.birthday and obj.happened_at:
        age_description = _calc_age_simple(baby.birthday, obj.happened_at)
    photos = db.query(AlbumPhoto).filter(AlbumPhoto.album_id == obj.id).order_by(AlbumPhoto.id)
    return {
        "id": obj.id,
        "user": obj.user_id,
        "content": obj.content,
        "happened_at": _iso(obj.happened_at),
        "created_at": _iso(obj.created_at),
        "visibility": obj.visibility,
        "tags": obj.tags if obj.tags is not None else [],
        "photos": [_photo_dict(p) for p in photos],
        "age_description": age_description,
    }


def album_list(db: Session, user_id: int, page_num: int, page_size: int) -> dict:
    query = (db.query(BabyAlbum).filter(BabyAlbum.user_id == user_id)
             .order_by(BabyAlbum.happened_at.desc(), BabyAlbum.created_at.desc()))
    total = query.count()
    start = (max(page_num, 1) - 1) * page_size
    page_data = query[start:start + page_size]
    return {
        "code": 200,
        "msg": "ok",
        "data": {
            "list": [_album_dict(db, o) for o in page_data],
            "total": total,
            "page_num": page_num,
            "page_size": page_size,
        },
    }


def album_create(db: Session, user_id: int, data: dict, files: list) -> dict:
    """创建相册; multipart 上传的图片/视频落盘 MEDIA_ROOT/baby_album/ 并建照片行"""
    try:
        tags = data.get("tags")
        if isinstance(tags, str):
            try:
                tags = json.loads(tags) if tags.startswith("[") else [t.strip() for t in tags.split(",") if t.strip()]
            except Exception:
                tags = []
        happened_at = _parse_dt(data.get("happened_at"))

        album = BabyAlbum(
            user_id=user_id,
            content=data.get("content"),
            happened_at=happened_at,
            created_at=datetime.now(),
            visibility=data.get("visibility") or "relatives",
            tags=tags if isinstance(tags, list) else [],
        )
        db.add(album)
        db.commit()
        db.refresh(album)

        for f in files:
            filename = f.get("filename") or "file"
            content = f.get("content") or b""
            content_type = (f.get("content_type") or "").lower()
            is_video = content_type.startswith("video/") or filename.lower().endswith(
                (".mp4", ".mov", ".avi", ".wmv", ".flv", ".mkv", ".webm"))
            key = save_upload(content, filename, "baby_album")
            db.add(AlbumPhoto(album_id=album.id, image=key, is_video=is_video, created_at=datetime.now()))
        db.commit()
        db.refresh(album)
        return {"code": 200, "msg": "ok", "data": _album_dict(db, album)}
    except Exception as e:
        db.rollback()
        logger.exception("BabyAlbum create error")
        return {"code": 500, "msg": str(e), "data": None}


def album_delete(db: Session, user_id: int, pk: int) -> dict:
    album = db.query(BabyAlbum).filter(BabyAlbum.id == pk, BabyAlbum.user_id == user_id).first()
    if not album:
        return {"code": 404, "msg": "Not found", "data": None}
    # 照片行随外键级联删除 (Django FK on_delete=CASCADE), 这里显式删除保持一致
    db.query(AlbumPhoto).filter(AlbumPhoto.album_id == album.id).delete(synchronize_session=False)
    db.delete(album)
    db.commit()
    return {"code": 200, "msg": "ok", "data": None}


def album_video_playback(db: Session, user_id: int, stream_id: str, base_url: str) -> dict:
    """视频播放信息: 按 stream_id 匹配该用户相册下的视频"""
    photos = db.query(AlbumPhoto).join(BabyAlbum, AlbumPhoto.album_id == BabyAlbum.id).filter(
        BabyAlbum.user_id == user_id, AlbumPhoto.is_video).all()
    photo = None
    for p in photos:
        if _stream_id_from_key(p.image or "", str(p.id)) == stream_id:
            photo = p
            break
    if not photo:
        return {"status_code": 404, "body": {"code": 404, "msg": "Not found", "data": None}}

    key = (photo.image or "").lstrip("/")
    hls_url = f"{base_url}/baby/albums/video/{stream_id}/hls/master.m3u8"
    dash_url = f"{base_url}/baby/albums/video/{stream_id}/dash/manifest.mpd"
    poster_url = f"{base_url}/media/{photo.poster}" if photo.poster else ""
    return {"status_code": 200, "body": {
        "code": 200, "msg": "ok",
        "data": {"mp4": key, "hls": hls_url, "dash": dash_url, "poster": poster_url},
    }}


def _serve_stream_file(stream_id: str, rel: str, kind: str, media_url_prefix: str = "/media"):
    """本地媒体分支: 读取 HLS/DASH 流文件 (m3u8/mpd 文本, 其余 302 到 /media 代理)"""
    if ".." in rel or not rel:
        return {"status_code": 400, "body": {"code": 400, "msg": "invalid path", "data": None}}

    key = f"baby_album/streams/{stream_id}/{kind}/{rel}"
    local_path = (media_root() / key).resolve()
    if not local_path.exists() or local_path.is_dir():
        return {"status_code": 404, "body": {"code": 404, "msg": "Not found", "data": None}}

    lower = rel.lower()
    if lower.endswith(".m3u8") or lower.endswith(".mpd"):
        try:
            text = local_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return {"status_code": 404, "body": {"code": 404, "msg": "Not found", "data": None}}
        out = (text or "")
        if lower.endswith(".m3u8"):
            if out and not out.endswith("\n"):
                out += "\n"
        content_type = "application/vnd.apple.mpegurl" if lower.endswith(".m3u8") else "application/dash+xml"
        return {"status_code": 200, "text": out, "content_type": content_type,
                "headers": {"Cache-Control": "public, max-age=60"}}
    return {"status_code": 307, "redirect": f"{media_url_prefix}/{key}"}


def album_video_hls(stream_id: str, playlist_path: str):
    return _serve_stream_file(stream_id, (playlist_path or "").lstrip("/"), "hls")


def album_video_dash(stream_id: str, dash_path: str):
    return _serve_stream_file(stream_id, (dash_path or "").lstrip("/"), "dash")


# ══════════════════════════════════════════════
# 生长记录 /baby/growth_records*
# ══════════════════════════════════════════════

def _calc_age_str(birthday, target_date) -> str:
    """精确到天的年龄文本 (与 DRF GrowthRecordSerializer._calc_age_str 一致)"""
    if not birthday or not target_date:
        return ""
    if target_date < birthday:
        return "出生前"

    def _days_in_month(y, m):
        if m == 12:
            return (date(y + 1, 1, 1) - date(y, 12, 1)).days
        return (date(y, m + 1, 1) - date(y, m, 1)).days

    years = 0
    while True:
        next_year = birthday.year + years + 1
        next_day = min(birthday.day, _days_in_month(next_year, birthday.month))
        if date(next_year, birthday.month, next_day) > target_date:
            break
        years += 1

    months = 0
    while True:
        total_months = months + 1
        target_year = birthday.year + years
        target_month = birthday.month + total_months
        target_year += (target_month - 1) // 12
        target_month = ((target_month - 1) % 12) + 1
        target_day = min(birthday.day, _days_in_month(target_year, target_month))
        if date(target_year, target_month, target_day) > target_date:
            break
        months += 1

    anchor_year = birthday.year + years
    anchor_month = birthday.month + months
    anchor_year += (anchor_month - 1) // 12
    anchor_month = ((anchor_month - 1) % 12) + 1
    anchor_day = min(birthday.day, _days_in_month(anchor_year, anchor_month))
    days = (target_date - date(anchor_year, anchor_month, anchor_day)).days

    parts = []
    if years > 0:
        parts.append(f"{years}岁")
    if months > 0:
        parts.append(f"{months}个月")
    if days > 0:
        parts.append(f"{days}天")
    if not parts:
        return "出生当天"
    return "".join(parts)


def _growth_dict(db: Session, obj: GrowthRecord, base_url: str | None) -> dict:
    baby = db.query(BabyInfo).filter(BabyInfo.user_id == obj.user_id).first()
    age_description = _calc_age_str(baby.birthday, obj.measure_date) if baby and baby.birthday else ""
    key = obj.photo or ""
    photo = f"/media/{key}" if key else ""
    photo_full = f"/file/r?key={quote(key)}" if key else ""
    if obj.id and key:
        photo_thumb = (f"{base_url}/file/img?base={quote(f'growth/thumbs/gr_{obj.id}_w400')}"
                       if base_url else f"/file/img?base={quote(f'growth/thumbs/gr_{obj.id}_w400')}")
    else:
        photo_thumb = ""
    return {
        "id": obj.id,
        "user": obj.user_id,
        "measure_date": _iso(obj.measure_date),
        "height_cm": _dec_str(obj.height_cm),
        "weight_kg": _dec_str(obj.weight_kg),
        "head_circumference_cm": _dec_str(obj.head_circumference_cm),
        "photo": photo,
        "photo_full": photo_full,
        "photo_thumb": photo_thumb,
        "created_at": _iso(obj.created_at),
        "updated_at": _iso(obj.updated_at),
        "age_description": age_description,
    }


def growth_record_list(db: Session, user_id: int, page_num: int, page_size: int, base_url: str | None) -> dict:
    query = (db.query(GrowthRecord).filter(GrowthRecord.user_id == user_id)
             .order_by(GrowthRecord.measure_date.desc(), GrowthRecord.id.desc()))
    total = query.count()
    start = (max(page_num, 1) - 1) * page_size
    page_data = query[start:start + page_size]
    return {
        "code": 200,
        "msg": "ok",
        "data": {
            "list": [_growth_dict(db, o, base_url) for o in page_data],
            "total": total,
            "page_num": page_num,
            "page_size": page_size,
        },
    }


def growth_record_create(db: Session, user_id: int, data: dict, photo_file: dict | None, base_url: str | None) -> dict:
    measure_date = _parse_date(data.get("measure_date"))
    if not measure_date:
        return {"code": 400, "msg": "measure_date 必填", "data": None}

    def _num(key):
        v = data.get(key)
        if v in (None, ""):
            return None
        try:
            return Decimal(str(v))
        except Exception:
            return None

    height_cm, weight_kg, head_cm = _num("height_cm"), _num("weight_kg"), _num("head_circumference_cm")
    if not (height_cm or weight_kg or head_cm):
        return {"code": 400, "msg": "height_cm/weight_kg/head_circumference_cm 至少填写一项", "data": None}

    now = datetime.now()
    record = GrowthRecord(
        user_id=user_id,
        measure_date=measure_date,
        height_cm=height_cm,
        weight_kg=weight_kg,
        head_circumference_cm=head_cm,
        created_at=now,
        updated_at=now,
    )
    if photo_file:
        record.photo = save_upload(photo_file.get("content") or b"", photo_file.get("filename") or "photo.jpg", "growth")
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"code": 200, "msg": "ok", "data": _growth_dict(db, record, base_url)}


def growth_record_detail(db: Session, user_id: int, pk: int, base_url: str | None) -> dict:
    record = db.query(GrowthRecord).filter(GrowthRecord.id == pk, GrowthRecord.user_id == user_id).first()
    if not record:
        return {"code": 404, "msg": "Not found", "data": None}
    return {"code": 200, "msg": "ok", "data": _growth_dict(db, record, base_url)}


def growth_record_update(db: Session, user_id: int, pk: int, data: dict,
                         photo_file: dict | None, base_url: str | None) -> dict:
    record = db.query(GrowthRecord).filter(GrowthRecord.id == pk, GrowthRecord.user_id == user_id).first()
    if not record:
        return {"code": 404, "msg": "Not found", "data": None}

    def _num(key):
        if key not in data:
            return (False, None)
        v = data.get(key)
        if v in (None, ""):
            return (True, None)
        try:
            return (True, Decimal(str(v)))
        except Exception:
            return (True, None)

    if "measure_date" in data:
        parsed = _parse_date(data.get("measure_date"))
        if not parsed:
            return {"code": 400, "msg": "measure_date 格式错误", "data": None}
        record.measure_date = parsed
    changed, v = _num("height_cm")
    if changed:
        record.height_cm = v
    changed, v = _num("weight_kg")
    if changed:
        record.weight_kg = v
    changed, v = _num("head_circumference_cm")
    if changed:
        record.head_circumference_cm = v

    if not (record.height_cm or record.weight_kg or record.head_circumference_cm):
        return {"code": 400, "msg": "height_cm/weight_kg/head_circumference_cm 至少填写一项", "data": None}

    record.updated_at = datetime.now()
    if photo_file:
        record.photo = save_upload(photo_file.get("content") or b"", photo_file.get("filename") or "photo.jpg", "growth")
    else:
        remove_photo = str(data.get("remove_photo", "")).lower() in ["1", "true", "yes"]
        if remove_photo:
            record.photo = None
    db.commit()
    db.refresh(record)
    return {"code": 200, "msg": "ok", "data": _growth_dict(db, record, base_url)}


def growth_record_delete(db: Session, user_id: int, pk: int) -> dict:
    record = db.query(GrowthRecord).filter(GrowthRecord.id == pk, GrowthRecord.user_id == user_id).first()
    if not record:
        return {"code": 404, "msg": "Not found", "data": None}
    db.delete(record)
    db.commit()
    return {"code": 200, "msg": "ok", "data": None}


# ══════════════════════════════════════════════
# 疫苗 /baby/vaccines*
# ══════════════════════════════════════════════

def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    max_day = calendar.monthrange(y, m)[1]
    if d.day <= max_day:
        return date(y, m, d.day)
    overflow_days = d.day - max_day
    return date(y, m, max_day) + timedelta(days=overflow_days)


def _add_age_offset(birthday: date, months_offset: float = 0.0, days_offset: int = 0) -> date:
    whole = int(months_offset)
    frac = months_offset - whole
    d = _add_months(birthday, whole)
    if abs(frac - 0.5) < 1e-6:
        d = d + timedelta(days=15)
    if days_offset:
        d = d + timedelta(days=days_offset)
    return d


def _age_label(months_offset: float, days_offset: int) -> str:
    if months_offset == 0.0 and days_offset == 0:
        return "出生当天"
    val = months_offset
    if abs(val - int(val)) < 1e-6:
        return f"{int(val)}月龄"
    return f"{val:g}月龄"


def _now() -> datetime:
    return datetime.now()


def vaccine_schedule(db: Session, user_id: int) -> dict:
    baby = db.query(BabyInfo).filter(BabyInfo.user_id == user_id).first()
    if not baby or not baby.birthday:
        return {"code": 400, "msg": "请先完善宝宝信息", "data": None}

    birthday = baby.birthday
    defs = (db.query(VaccineDefinition).filter(VaccineDefinition.is_active)
            .order_by(VaccineDefinition.months_offset, VaccineDefinition.days_offset, VaccineDefinition.id))
    defs = list(defs)
    image_url = f"/media/{baby.image}" if baby.image else ""
    if not defs:
        return {"code": 200, "msg": "ok", "data": {
            "baby": {"name": baby.name, "birthday": baby.birthday.isoformat(), "image": image_url},
            "groups": [], "paid_candidates": []}}

    vaccine_keys = [d.vaccine_key for d in defs]
    existing = (db.query(BabyVaccineRecord)
                .filter(BabyVaccineRecord.user_id == user_id, BabyVaccineRecord.vaccine_key.in_(vaccine_keys))
                .order_by(BabyVaccineRecord.updated_at.desc(), BabyVaccineRecord.id.desc()))
    record_map = {}
    keep_ids = set()
    for r in existing:
        if r.vaccine_key not in record_map:
            record_map[r.vaccine_key] = r
            keep_ids.add(r.id)
    # 同一疫苗多条记录时去重 (原行为)
    if keep_ids:
        (db.query(BabyVaccineRecord)
         .filter(BabyVaccineRecord.user_id == user_id, BabyVaccineRecord.vaccine_key.in_(vaccine_keys),
                 ~BabyVaccineRecord.id.in_(keep_ids))
         .delete(synchronize_session=False))
        db.commit()

    groups = {}
    for d in defs:
        months_offset = float(d.months_offset)
        label = _age_label(months_offset, d.days_offset)
        r = record_map.get(d.vaccine_key)
        is_paid = d.fee_type == "paid"
        status = "pending"
        if not r and not is_paid:
            # 免费疫苗缺记录 → 自动按月龄生成
            r = BabyVaccineRecord(
                user_id=user_id, vaccine_key=d.vaccine_key, name=d.name,
                dose_index=d.dose_index, dose_total=d.dose_total, fee_type=d.fee_type,
                description=d.description, recommend_date=_add_age_offset(birthday, months_offset, d.days_offset),
                done=False, actual_date=None, price_min=d.price_min, price_max=d.price_max,
                created_at=_now(), updated_at=_now())
            db.add(r)
            db.commit()
            db.refresh(r)
            record_map[d.vaccine_key] = r
        if is_paid and not r:
            status = "not_added"
        if r and r.done:
            status = "done"

        recommend_date_str = (r.recommend_date.isoformat() if r
                              else _add_age_offset(birthday, months_offset, d.days_offset).isoformat())
        groups.setdefault(label, []).append({
            "record_id": r.id if r else None,
            "vaccine_key": d.vaccine_key,
            "name": d.name,
            "dose_index": d.dose_index,
            "dose_total": d.dose_total,
            "fee_type": d.fee_type,
            "description": d.description or "",
            "recommend_date": recommend_date_str,
            "actual_date": r.actual_date.isoformat() if (r and r.actual_date) else None,
            "status": status,
            "price_min": d.price_min,
            "price_max": d.price_max,
        })

    group_list = [{"label": label, "items": items} for label, items in groups.items()]

    def _group_sort_key(x):
        if x["label"] == "出生当天":
            return -1
        num = x["label"].replace("月龄", "")
        try:
            return float(num)
        except Exception:
            return 999

    group_list.sort(key=_group_sort_key)

    paid_candidates = []
    for d in defs:
        if d.fee_type != "paid":
            continue
        if record_map.get(d.vaccine_key):
            continue
        paid_candidates.append({
            "vaccine_key": d.vaccine_key,
            "name": d.name,
            "dose_index": d.dose_index,
            "dose_total": d.dose_total,
            "recommend_date": _add_age_offset(birthday, float(d.months_offset), d.days_offset).isoformat(),
            "price_min": d.price_min,
            "price_max": d.price_max,
        })

    return {"code": 200, "msg": "ok", "data": {
        "baby": {"name": baby.name, "birthday": baby.birthday.isoformat(), "image": image_url},
        "groups": group_list, "paid_candidates": paid_candidates}}


def _get_latest_vaccine_record(db: Session, user_id: int, vaccine_key: str):
    """取最新一条记录并删除重复旧记录 (原 _get_latest_record)"""
    record = (db.query(BabyVaccineRecord).filter(BabyVaccineRecord.user_id == user_id,
                                                 BabyVaccineRecord.vaccine_key == vaccine_key)
              .order_by(BabyVaccineRecord.updated_at.desc(), BabyVaccineRecord.id.desc())
              .first())
    if record:
        # 去重删除需重新构造 Query (带 order_by 的 Query 不能直接 delete)
        (db.query(BabyVaccineRecord)
         .filter(BabyVaccineRecord.user_id == user_id, BabyVaccineRecord.vaccine_key == vaccine_key,
                 BabyVaccineRecord.id != record.id)
         .delete(synchronize_session=False))
        db.commit()
    return record


def vaccine_toggle(db: Session, user_id: int, data: dict) -> dict:
    vaccine_key = data.get("vaccine_key")
    date_type = data.get("date_type")
    date_str = data.get("date")
    recommend_date_str = data.get("recommend_date")
    actual_date_str = data.get("actual_date")
    raw_done = data.get("done")

    if vaccine_key is None:
        return {"code": 400, "msg": "vaccine_key 必填", "data": None}

    d = db.query(VaccineDefinition).filter(VaccineDefinition.vaccine_key == vaccine_key,
                                           VaccineDefinition.is_active).first()
    if not d:
        return {"code": 400, "msg": "未知疫苗", "data": None}

    if date_type:
        if date_type not in ["recommend", "actual"]:
            return {"code": 400, "msg": "date_type 参数错误", "data": None}
        if date_str is None:
            date_str = recommend_date_str if date_type == "recommend" else actual_date_str
        if not date_str:
            return {"code": 400, "msg": "date 必填", "data": None}
        try:
            new_date = date.fromisoformat(str(date_str))
        except Exception:
            return {"code": 400, "msg": "date 格式错误", "data": None}

        record = _get_latest_vaccine_record(db, user_id, vaccine_key)
        if not record and d.fee_type == "paid":
            return {"code": 400, "msg": "请先添加自费疫苗", "data": None}

        if date_type == "recommend":
            if not record:
                record = BabyVaccineRecord(
                    user_id=user_id, vaccine_key=vaccine_key, name=d.name,
                    dose_index=d.dose_index, dose_total=d.dose_total, fee_type=d.fee_type,
                    description=d.description, recommend_date=new_date, done=False, actual_date=None,
                    price_min=d.price_min, price_max=d.price_max, created_at=_now(), updated_at=_now())
                db.add(record)
            else:
                record.recommend_date = new_date
            record.updated_at = _now()
            db.commit()
            db.refresh(record)
        else:
            if not record:
                return {"code": 400, "msg": "记录不存在", "data": None}
            record.actual_date = new_date
            if not record.done:
                record.done = True
            record.updated_at = _now()
            db.commit()
            db.refresh(record)

        return {"code": 200, "msg": "ok", "data": {
            "record_id": record.id, "done": record.done,
            "recommend_date": record.recommend_date.isoformat(),
            "actual_date": record.actual_date.isoformat() if record.actual_date else None}}

    if raw_done is None:
        return {"code": 400, "msg": "done 必填", "data": None}

    done = raw_done if isinstance(raw_done, bool) else str(raw_done).lower() in ["1", "true", "yes"]
    record = _get_latest_vaccine_record(db, user_id, vaccine_key)
    if not record and d.fee_type == "paid":
        return {"code": 400, "msg": "请先添加自费疫苗", "data": None}

    if not record:
        baby = db.query(BabyInfo).filter(BabyInfo.user_id == user_id).first()
        if not baby or not baby.birthday:
            return {"code": 400, "msg": "请先完善宝宝信息", "data": None}
        if recommend_date_str:
            try:
                recommend_date = date.fromisoformat(str(recommend_date_str))
            except Exception:
                return {"code": 400, "msg": "recommend_date 格式错误", "data": None}
        else:
            recommend_date = _add_age_offset(baby.birthday, float(d.months_offset), d.days_offset)
        record = BabyVaccineRecord(
            user_id=user_id, vaccine_key=vaccine_key, name=d.name,
            dose_index=d.dose_index, dose_total=d.dose_total, fee_type=d.fee_type,
            description=d.description, recommend_date=recommend_date, done=False, actual_date=None,
            price_min=d.price_min, price_max=d.price_max, created_at=_now(), updated_at=_now())
        db.add(record)

    if done:
        if actual_date_str:
            try:
                actual_date = date.fromisoformat(str(actual_date_str))
            except Exception:
                return {"code": 400, "msg": "actual_date 格式错误", "data": None}
        else:
            actual_date = record.actual_date or record.recommend_date
        record.done = True
        record.actual_date = actual_date
    else:
        record.done = False
        record.actual_date = None
    record.updated_at = _now()
    db.commit()
    db.refresh(record)

    return {"code": 200, "msg": "ok", "data": {
        "record_id": record.id, "done": record.done,
        "recommend_date": record.recommend_date.isoformat(),
        "actual_date": record.actual_date.isoformat() if record.actual_date else None}}


def vaccine_add_paid(db: Session, user_id: int, data: dict) -> dict:
    vaccine_key = data.get("vaccine_key")
    recommend_date_str = data.get("recommend_date")
    if vaccine_key is None or recommend_date_str is None:
        return {"code": 400, "msg": "vaccine_key/recommend_date 必填", "data": None}
    try:
        recommend_date = date.fromisoformat(str(recommend_date_str))
    except Exception:
        return {"code": 400, "msg": "recommend_date 格式错误", "data": None}

    d = db.query(VaccineDefinition).filter(VaccineDefinition.vaccine_key == vaccine_key,
                                           VaccineDefinition.is_active).first()
    if not d:
        return {"code": 400, "msg": "未知疫苗", "data": None}
    if d.fee_type != "paid":
        return {"code": 400, "msg": "该疫苗不是自费疫苗", "data": None}

    record = (db.query(BabyVaccineRecord)
              .filter(BabyVaccineRecord.user_id == user_id, BabyVaccineRecord.vaccine_key == vaccine_key,
                      BabyVaccineRecord.recommend_date == recommend_date).first())
    if record:
        return {"code": 200, "msg": "ok", "data": {"record_id": record.id}}

    record = BabyVaccineRecord(
        user_id=user_id, vaccine_key=vaccine_key, name=d.name,
        dose_index=d.dose_index, dose_total=d.dose_total, fee_type=d.fee_type,
        description=d.description, recommend_date=recommend_date, done=False, actual_date=None,
        price_min=d.price_min, price_max=d.price_max, created_at=_now(), updated_at=_now())
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"code": 200, "msg": "ok", "data": {"record_id": record.id}}


# ══════════════════════════════════════════════
# 经期 /baby/period*
# ══════════════════════════════════════════════

def _period_log_dict(log: MenstrualLog | None) -> dict | None:
    if log is None:
        return None
    return {
        "id": log.id,
        "user": log.user_id,
        "date": _iso(log.date),
        "is_period": log.is_period,
        "flow_level": log.flow_level,
        "pain_level": log.pain_level,
        "had_sex": log.had_sex,
        "symptoms": log.symptoms,
        "basal_temp": _dec_str(log.basal_temp),
        "weight_kg": _dec_str(log.weight_kg),
        "mood": log.mood,
        "habit_eat_on_time": log.habit_eat_on_time,
        "habit_water8": log.habit_water8,
        "habit_fruits": log.habit_fruits,
        "habit_exercise": log.habit_exercise,
        "habit_poop": log.habit_poop,
        "created_at": _iso(log.created_at),
        "updated_at": _iso(log.updated_at),
    }


def _period_setting_dict(s: MenstrualSetting) -> dict:
    return {
        "id": s.id,
        "user": s.user_id,
        "cycle_length": s.cycle_length,
        "period_length": s.period_length,
        "created_at": _iso(s.created_at),
        "updated_at": _iso(s.updated_at),
    }


def _get_or_create_setting(db: Session, user_id: int) -> MenstrualSetting:
    s = db.query(MenstrualSetting).filter(MenstrualSetting.user_id == user_id).first()
    if not s:
        s = MenstrualSetting(user_id=user_id, cycle_length=28, period_length=5,
                             created_at=_now(), updated_at=_now())
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def period_overview(db: Session, user_id: int, month_str) -> dict:
    today = date.today()
    if month_str:
        try:
            year, mon = [int(x) for x in str(month_str).split("-")]
            first_day = date(year, mon, 1)
        except Exception:
            return {"code": 400, "msg": "month 格式错误", "data": None}
    else:
        first_day = date(today.year, today.month, 1)
    if first_day.month == 12:
        next_month_first = date(first_day.year + 1, 1, 1)
    else:
        next_month_first = date(first_day.year, first_day.month + 1, 1)
    last_day = next_month_first - timedelta(days=1)

    setting = _get_or_create_setting(db, user_id)

    logs = (db.query(MenstrualLog).filter(MenstrualLog.user_id == user_id,
                                          MenstrualLog.date >= first_day, MenstrualLog.date <= last_day))
    day_map = {l.date.isoformat(): l for l in logs}

    latest_period = (db.query(MenstrualLog).filter(MenstrualLog.user_id == user_id, MenstrualLog.is_period)
                     .order_by(MenstrualLog.date.desc()).first())
    cycle_len = setting.cycle_length or 28
    period_len = setting.period_length or 5
    predict_ovulation = predict_period_start = fertile_start = fertile_end = None
    if latest_period:
        predict_period_start = latest_period.date + timedelta(days=cycle_len)
        predict_ovulation = latest_period.date + timedelta(days=cycle_len - 14)
        fertile_start = predict_ovulation - timedelta(days=5)
        fertile_end = predict_ovulation + timedelta(days=1)

    days = []
    cur = first_day
    while cur <= last_day:
        key = cur.isoformat()
        status = []
        log = day_map.get(key)
        if log and log.is_period:
            status.append("period")
        if predict_period_start and predict_period_start <= cur < predict_period_start + timedelta(days=period_len):
            status.append("predicted_period")
        if fertile_start and fertile_start <= cur <= fertile_end:
            status.append("fertile")
            if predict_ovulation:
                if cur == predict_ovulation:
                    status.append("ovulation")
                elif predict_ovulation - timedelta(days=2) <= cur <= predict_ovulation - timedelta(days=1):
                    status.append("fertile_very_high")
                elif (predict_ovulation - timedelta(days=4) <= cur <= predict_ovulation - timedelta(days=3)
                      or predict_ovulation + timedelta(days=1) <= cur <= predict_ovulation + timedelta(days=2)):
                    status.append("fertile_high")
        days.append({"date": key, "status": status, "log": _period_log_dict(log)})
        cur += timedelta(days=1)

    return {"code": 200, "msg": "ok", "data": {
        "month": first_day.strftime("%Y-%m"),
        "days": days,
        "predict_next_ovulation": predict_ovulation.isoformat() if predict_ovulation else None,
        "predict_next_period_start": predict_period_start.isoformat() if predict_period_start else None,
        "cycle_length": cycle_len,
        "period_length": period_len,
    }}


def period_log_get(db: Session, user_id: int, date_str) -> dict:
    if not date_str:
        return {"code": 400, "msg": "date 必填", "data": None}
    d = _parse_date(date_str)
    if not d:
        return {"code": 400, "msg": "date 格式错误", "data": None}
    record = db.query(MenstrualLog).filter(MenstrualLog.user_id == user_id, MenstrualLog.date == d).first()
    return {"code": 200, "msg": "ok", "data": _period_log_dict(record)}


def period_log_post(db: Session, user_id: int, data: dict) -> dict:
    date_str = data.get("date")
    if not date_str:
        return {"code": 400, "msg": "date 必填", "data": None}
    d = _parse_date(date_str)
    if not d:
        return {"code": 400, "msg": "date 格式错误", "data": None}

    def normalize_empty(v):
        return None if v == "" else v

    def parse_int(v):
        v = normalize_empty(v)
        if v is None:
            return None
        return int(v)

    def parse_bool(v):
        if v is None:
            return None
        return v if isinstance(v, bool) else str(v).lower() in ["1", "true", "yes"]

    record = db.query(MenstrualLog).filter(MenstrualLog.user_id == user_id, MenstrualLog.date == d).first()
    payload = {}
    # 仅更新提交了的字段; 空字符串归一为 None (与原视图一致)
    if data.get("is_period") is not None:
        payload["is_period"] = parse_bool(data.get("is_period"))
    if data.get("flow_level") is not None:
        parsed = parse_int(data.get("flow_level"))
        if parsed is not None:
            payload["flow_level"] = parsed
    if data.get("pain_level") is not None:
        parsed = parse_int(data.get("pain_level"))
        if parsed is not None:
            payload["pain_level"] = parsed
    if data.get("had_sex") is not None:
        payload["had_sex"] = parse_bool(data.get("had_sex"))
    if data.get("symptoms") is not None:
        payload["symptoms"] = normalize_empty(data.get("symptoms"))
    if data.get("basal_temp") is not None:
        v = normalize_empty(data.get("basal_temp"))
        if v is not None:
            payload["basal_temp"] = Decimal(str(v))
    if data.get("weight_kg") is not None:
        v = normalize_empty(data.get("weight_kg"))
        if v is not None:
            payload["weight_kg"] = Decimal(str(v))
    if data.get("mood") is not None:
        payload["mood"] = normalize_empty(data.get("mood"))
    for habit_key in ("habit_eat_on_time", "habit_water8", "habit_fruits", "habit_exercise", "habit_poop"):
        if data.get(habit_key) is not None:
            payload[habit_key] = parse_bool(data.get(habit_key))

    if record:
        for k, v in payload.items():
            setattr(record, k, v)
        record.updated_at = _now()
    else:
        record = MenstrualLog(user_id=user_id, date=d, created_at=_now(), updated_at=_now(), **payload)
        db.add(record)
    db.commit()
    db.refresh(record)
    return {"code": 200, "msg": "ok", "data": _period_log_dict(record)}


def period_settings_get(db: Session, user_id: int) -> dict:
    s = _get_or_create_setting(db, user_id)
    return {"code": 200, "msg": "ok", "data": _period_setting_dict(s)}


def period_settings_post(db: Session, user_id: int, data: dict) -> dict:
    s = _get_or_create_setting(db, user_id)
    cycle_length = data.get("cycle_length")
    period_length = data.get("period_length")
    if cycle_length is not None:
        try:
            s.cycle_length = int(cycle_length)
        except Exception:
            return {"code": 400, "msg": "cycle_length 格式错误", "data": None}
    if period_length is not None:
        try:
            s.period_length = int(period_length)
        except Exception:
            return {"code": 400, "msg": "period_length 格式错误", "data": None}
    s.updated_at = _now()
    db.commit()
    db.refresh(s)
    return {"code": 200, "msg": "ok", "data": _period_setting_dict(s)}


# ══════════════════════════════════════════════
# 生日 /baby/birthday, /baby/birthday_bazi (农历换算纯 Python 移植)
# ══════════════════════════════════════════════

_LUNAR_INFO = [
    0x04bd8, 0x04ae0, 0x0a570, 0x054d5, 0x0d260, 0x0d950, 0x16554, 0x056a0, 0x09ad0, 0x055d2,
    0x04ae0, 0x0a5b6, 0x0a4d0, 0x0d250, 0x1d255, 0x0b540, 0x0d6a0, 0x0ada2, 0x095b0, 0x14977,
    0x04970, 0x0a4b0, 0x0b4b5, 0x06a50, 0x06d40, 0x1ab54, 0x02b60, 0x09570, 0x052f2, 0x04970,
    0x06566, 0x0d4a0, 0x0ea50, 0x06e95, 0x05ad0, 0x02b60, 0x186e3, 0x092e0, 0x1c8d7, 0x0c950,
    0x0d4a0, 0x1d8a6, 0x0b550, 0x056a0, 0x1a5b4, 0x025d0, 0x092d0, 0x0d2b2, 0x0a950, 0x0b557,
    0x06ca0, 0x0b550, 0x15355, 0x04da0, 0x0a5b0, 0x14573, 0x052b0, 0x0a9a8, 0x0e950, 0x06aa0,
    0x0aea6, 0x0ab50, 0x04b60, 0x0aae4, 0x0a570, 0x05260, 0x0f263, 0x0d950, 0x05b57, 0x056a0,
    0x096d0, 0x04dd5, 0x04ad0, 0x0a4d0, 0x0d4d4, 0x0d250, 0x0d558, 0x0b540, 0x0b6a0, 0x195a6,
    0x095b0, 0x049b0, 0x0a974, 0x0a4b0, 0x0b27a, 0x06a50, 0x06d40, 0x0af46, 0x0ab60, 0x09570,
    0x04af5, 0x04970, 0x064b0, 0x074a3, 0x0ea50, 0x06b58, 0x05ac0, 0x0ab60, 0x096d5, 0x092e0,
    0x0c960, 0x0d954, 0x0d4a0, 0x0da50, 0x07552, 0x056a0, 0x0abb7, 0x025d0, 0x092d0, 0x0cab5,
    0x0a950, 0x0b4a0, 0x0baa4, 0x0ad50, 0x055d9, 0x04ba0, 0x0a5b0, 0x15176, 0x052b0, 0x0a930,
    0x07954, 0x06aa0, 0x0ad50, 0x05b52, 0x04b60, 0x0a6e6, 0x0a4e0, 0x0d260, 0x0ea65, 0x0d530,
    0x05aa0, 0x076a3, 0x096d0, 0x04afb, 0x04ad0, 0x0a4d0, 0x1d0b6, 0x0d250, 0x0d520, 0x0dd45,
    0x0b5a0, 0x056d0, 0x055b2, 0x049b0, 0x0a577, 0x0a4b0, 0x0aa50, 0x1b255, 0x06d20, 0x0ada0,
    0x14b63, 0x09370, 0x049f8, 0x04970, 0x064b0, 0x168a6, 0x0ea50, 0x06b20, 0x1a6c4, 0x0aae0,
    0x0a2e0, 0x0d2e3, 0x0c960, 0x0d557, 0x0d4a0, 0x0da50, 0x05d55, 0x056a0, 0x0a6d0, 0x055d4,
    0x052d0, 0x0a9b8, 0x0a950, 0x0b4a0, 0x0b6a6, 0x0ad50, 0x055a0, 0x0aba4, 0x0a5b0, 0x052b0,
    0x0b273, 0x06930, 0x07337, 0x06aa0, 0x0ad50, 0x14b55, 0x04b60, 0x0a570, 0x054e4, 0x0d160,
    0x0e968, 0x0d520, 0x0daa0, 0x16aa6, 0x056d0, 0x04ae0, 0x0a9d4, 0x0a2d0, 0x0d150, 0x0f252,
    0x0d520
]

_LUNAR_START = date(1900, 1, 31)


def _lunar_leap_month(y: int) -> int:
    return _LUNAR_INFO[y - 1900] & 0xF


def _lunar_leap_days(y: int) -> int:
    if _lunar_leap_month(y):
        return 30 if (_LUNAR_INFO[y - 1900] & 0x10000) else 29
    return 0


def _lunar_month_days(y: int, m: int) -> int:
    if m < 1 or m > 12:
        return 0
    return 30 if (_LUNAR_INFO[y - 1900] & (0x10000 >> m)) else 29


def _lunar_year_days(y: int) -> int:
    total = 348
    info = _LUNAR_INFO[y - 1900]
    bit = 0x8000
    while bit > 0x8:
        total += 1 if (info & bit) else 0
        bit >>= 1
    return total + _lunar_leap_days(y)


def _lunar_to_solar(y: int, m: int, d: int, is_leap: bool) -> date | None:
    """农历 → 公历"""
    if y < 1900 or y > 2100 or m < 1 or m > 12 or d < 1:
        return None

    offset = 0
    for yr in range(1900, y):
        offset += _lunar_year_days(yr)

    leap = _lunar_leap_month(y)
    for mo in range(1, m):
        offset += _lunar_month_days(y, mo)
        if leap and mo == leap:
            offset += _lunar_leap_days(y)

    if is_leap:
        if not leap or leap != m:
            is_leap = False
        else:
            offset += _lunar_month_days(y, m)

    mdays = _lunar_leap_days(y) if (is_leap and leap == m) else _lunar_month_days(y, m)
    if d > mdays:
        d = mdays

    offset += d - 1
    return _LUNAR_START + timedelta(days=offset)


def _solar_to_lunar(solar: date) -> dict | None:
    """公历 → 农历"""
    if solar < _LUNAR_START or solar.year < 1900 or solar.year > 2100:
        return None

    offset = (solar - _LUNAR_START).days
    y = 1900
    while y <= 2100:
        y_days = _lunar_year_days(y)
        if offset < y_days:
            break
        offset -= y_days
        y += 1
    if y > 2100:
        return None

    leap_month = _lunar_leap_month(y)
    is_leap = False
    m = 1
    while m <= 12:
        if leap_month and m == leap_month + 1 and not is_leap:
            is_leap = True
            mdays = _lunar_leap_days(y)
            m -= 1
        else:
            mdays = _lunar_month_days(y, m)
        if offset < mdays:
            break
        offset -= mdays
        if is_leap and m == leap_month:
            is_leap = False
        m += 1

    return {"lunar_year": y, "lunar_month": m, "lunar_day": int(offset + 1), "lunar_is_leap": bool(is_leap)}


def _pad2(v):
    if v is None:
        return ""
    return str(int(v)).zfill(2)


def _format_lunar_iso(y, m, d) -> str | None:
    if not y or not m or not d:
        return None
    return f"{int(y)}-{_pad2(int(m))}-{_pad2(int(d))}"


def _calc_age_ym(birth: date | None, today: date) -> str | None:
    if not birth or today < birth:
        return None
    years = today.year - birth.year
    months = today.month - birth.month
    if today.day < birth.day:
        months -= 1
    if months < 0:
        years -= 1
        months += 12
    years, months = max(0, years), max(0, months)
    if years == 0 and months == 0:
        return "0个月"
    if years == 0:
        return f"{months}个月"
    if months == 0:
        return f"{years}岁"
    return f"{years}岁{months}个月"


def _calc_constellation(birth: date | None) -> str | None:
    if not birth:
        return None
    m, d = birth.month, birth.day
    ranges = [
        (1, 20, "水瓶座"), (2, 19, "双鱼座"), (3, 21, "白羊座"), (4, 20, "金牛座"),
        (5, 21, "双子座"), (6, 22, "巨蟹座"), (7, 23, "狮子座"), (8, 23, "处女座"),
        (9, 23, "天秤座"), (10, 24, "天蝎座"), (11, 23, "射手座"), (12, 22, "摩羯座"),
    ]
    for month, start_day, name in ranges:
        if (m == month and d >= start_day) or (m == month + 1 and d < start_day):
            return name
    if (m == 12 and d >= 22) or (m == 1 and d < 20):
        return "摩羯座"
    return None


def _ensure_birthday_both_calendars(db: Session, record: BirthdayRecord) -> None:
    """公历/农历互补 (原 _ensure_birthday_both_calendars)"""
    if record.solar_date and not (record.lunar_year and record.lunar_month and record.lunar_day):
        lunar = _solar_to_lunar(record.solar_date)
        if lunar:
            record.lunar_year = lunar["lunar_year"]
            record.lunar_month = lunar["lunar_month"]
            record.lunar_day = lunar["lunar_day"]
            record.lunar_is_leap = lunar["lunar_is_leap"]
            record.updated_at = date.today()
            db.commit()
        return
    if record.lunar_year and record.lunar_month and record.lunar_day and not record.solar_date:
        solar = _lunar_to_solar(int(record.lunar_year), int(record.lunar_month),
                                int(record.lunar_day), bool(record.lunar_is_leap))
        if solar:
            record.solar_date = solar
            record.updated_at = date.today()
            db.commit()


def _calc_next_birthday_date(record: BirthdayRecord, today: date) -> date | None:
    if record.calendar_type == "solar":
        if not record.solar_date:
            return None
        m, d = record.solar_date.month, record.solar_date.day
        y = today.year
        max_day = calendar.monthrange(y, m)[1]
        candidate = date(y, m, min(d, max_day))
        if candidate < today:
            y += 1
            max_day = calendar.monthrange(y, m)[1]
            candidate = date(y, m, min(d, max_day))
        return candidate

    m, d = record.lunar_month, record.lunar_day
    if not m or not d:
        return None
    y = today.year
    is_leap = bool(record.lunar_is_leap)
    candidate = _lunar_to_solar(y, int(m), int(d), is_leap)
    if candidate is None:
        return None
    if candidate < today:
        candidate = _lunar_to_solar(y + 1, int(m), int(d), is_leap)
    return candidate


def _birthday_dict(db: Session, record: BirthdayRecord) -> dict:
    """生日序列化 + 装饰字段 (原 _decorate_birthday)"""
    _ensure_birthday_both_calendars(db, record)
    today = date.today()
    next_date = _calc_next_birthday_date(record, today)
    return {
        "id": record.id,
        "user": record.user_id,
        "name": record.name,
        "relation": record.relation,
        "calendar_type": record.calendar_type,
        "solar_date": _iso(record.solar_date),
        "lunar_year": record.lunar_year,
        "lunar_month": record.lunar_month,
        "lunar_day": record.lunar_day,
        "lunar_is_leap": record.lunar_is_leap,
        "birth_hour": record.birth_hour,
        "gender": record.gender,
        "created_at": _iso(record.created_at),
        "updated_at": _iso(record.updated_at),
        "next_birthday_date": next_date.isoformat() if next_date else None,
        "next_birthday_in_days": (next_date - today).days if next_date else None,
        "age_text": _calc_age_ym(record.solar_date, today),
        "constellation": _calc_constellation(record.solar_date),
        "lunar_date_iso": _format_lunar_iso(record.lunar_year, record.lunar_month, record.lunar_day),
    }


def _parse_birth_hour(value):
    """出生时辰 (0-23), 允许空 → (ok, hour|None)"""
    if value in [None, ""]:
        return True, None
    try:
        h = int(value)
    except Exception:
        return False, None
    if h < 0 or h > 23:
        return False, None
    return True, h


def _parse_gender(value):
    """性别 (1=男 0=女), 允许空 → (ok, gender|None)"""
    if value in [None, ""]:
        return True, None
    try:
        g = int(value)
    except Exception:
        return False, None
    if g not in (0, 1):
        return False, None
    return True, g


def birthday_list(db: Session, user_id: int) -> dict:
    qs = (db.query(BirthdayRecord).filter(BirthdayRecord.user_id == user_id)
          .order_by(BirthdayRecord.updated_at.desc(), BirthdayRecord.id.desc()))
    return {"code": 200, "msg": "ok", "data": [_birthday_dict(db, x) for x in qs]}


def birthday_create(db: Session, user_id: int, payload: dict) -> dict:
    name = (payload.get("name") or "").strip()
    if not name:
        return {"code": 400, "msg": "name 必填", "data": None}

    calendar_type = payload.get("calendar_type") or "lunar"
    if calendar_type not in ["lunar", "solar"]:
        return {"code": 400, "msg": "calendar_type 参数错误", "data": None}

    data = {"user_id": user_id, "name": name, "relation": payload.get("relation"),
            "calendar_type": calendar_type, "created_at": date.today(), "updated_at": date.today()}

    if calendar_type == "solar":
        solar_date = payload.get("solar_date")
        if not solar_date:
            return {"code": 400, "msg": "solar_date 必填", "data": None}
        solar = _parse_date(solar_date)
        if not solar:
            return {"code": 400, "msg": "solar_date 格式错误", "data": None}
        data["solar_date"] = solar
        lunar = _solar_to_lunar(solar)
        if lunar:
            data.update(lunar)
    else:
        try:
            data["lunar_year"] = int(payload.get("lunar_year"))
        except Exception:
            return {"code": 400, "msg": "lunar_year 必填", "data": None}
        try:
            data["lunar_month"] = int(payload.get("lunar_month"))
            data["lunar_day"] = int(payload.get("lunar_day"))
        except Exception:
            return {"code": 400, "msg": "lunar_month/lunar_day 必填", "data": None}
        data["lunar_is_leap"] = bool(payload.get("lunar_is_leap"))
        solar = _lunar_to_solar(int(data["lunar_year"]), int(data["lunar_month"]),
                                int(data["lunar_day"]), bool(data["lunar_is_leap"]))
        if solar:
            data["solar_date"] = solar

    ok, birth_hour = _parse_birth_hour(payload.get("birth_hour"))
    if not ok:
        return {"code": 400, "msg": "birth_hour 参数错误", "data": None}
    data["birth_hour"] = birth_hour

    ok, gender = _parse_gender(payload.get("gender"))
    if not ok:
        return {"code": 400, "msg": "gender 参数错误", "data": None}
    data["gender"] = gender

    record = BirthdayRecord(**data)
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"code": 200, "msg": "ok", "data": _birthday_dict(db, record)}


def birthday_update(db: Session, user_id: int, payload: dict) -> dict:
    rid = payload.get("id")
    if not rid:
        return {"code": 400, "msg": "id 必填", "data": None}
    record = db.query(BirthdayRecord).filter(BirthdayRecord.user_id == user_id,
                                             BirthdayRecord.id == rid).first()
    if not record:
        return {"code": 404, "msg": "记录不存在", "data": None}

    if "name" in payload:
        record.name = (payload.get("name") or "").strip()
    if "relation" in payload:
        record.relation = payload.get("relation")
    if "calendar_type" in payload:
        ct = payload.get("calendar_type")
        if ct not in ["lunar", "solar"]:
            return {"code": 400, "msg": "calendar_type 参数错误", "data": None}
        record.calendar_type = ct

    if record.calendar_type == "solar":
        if "solar_date" in payload:
            solar_date = payload.get("solar_date")
            if not solar_date:
                record.solar_date = None
            else:
                solar = _parse_date(solar_date)
                if not solar:
                    return {"code": 400, "msg": "solar_date 格式错误", "data": None}
                record.solar_date = solar
        if record.solar_date:
            lunar = _solar_to_lunar(record.solar_date)
            if lunar:
                record.lunar_year = lunar["lunar_year"]
                record.lunar_month = lunar["lunar_month"]
                record.lunar_day = lunar["lunar_day"]
                record.lunar_is_leap = lunar["lunar_is_leap"]
    else:
        if "lunar_year" in payload:
            try:
                record.lunar_year = int(payload.get("lunar_year"))
            except Exception:
                return {"code": 400, "msg": "lunar_year 参数错误", "data": None}
        if "lunar_month" in payload:
            record.lunar_month = int(payload.get("lunar_month"))
        if "lunar_day" in payload:
            record.lunar_day = int(payload.get("lunar_day"))
        if "lunar_is_leap" in payload:
            record.lunar_is_leap = bool(payload.get("lunar_is_leap"))
        if record.lunar_year and record.lunar_month and record.lunar_day:
            solar = _lunar_to_solar(int(record.lunar_year), int(record.lunar_month),
                                    int(record.lunar_day), bool(record.lunar_is_leap))
            if solar:
                record.solar_date = solar

    if "birth_hour" in payload:
        ok, birth_hour = _parse_birth_hour(payload.get("birth_hour"))
        if not ok:
            return {"code": 400, "msg": "birth_hour 参数错误", "data": None}
        record.birth_hour = birth_hour

    if "gender" in payload:
        ok, gender = _parse_gender(payload.get("gender"))
        if not ok:
            return {"code": 400, "msg": "gender 参数错误", "data": None}
        record.gender = gender

    record.updated_at = date.today()
    db.commit()
    db.refresh(record)
    return {"code": 200, "msg": "ok", "data": _birthday_dict(db, record)}


def birthday_delete(db: Session, user_id: int, payload: dict) -> dict:
    rid = payload.get("id")
    if not rid:
        return {"code": 400, "msg": "id 必填", "data": None}
    record = db.query(BirthdayRecord).filter(BirthdayRecord.user_id == user_id,
                                             BirthdayRecord.id == rid).first()
    if not record:
        return {"code": 404, "msg": "记录不存在", "data": None}
    db.delete(record)
    db.commit()
    return {"code": 200, "msg": "ok", "data": None}


def birthday_bazi(db: Session, user_id: int, query_params: dict) -> dict:
    """八字测算 (依赖 lunar_python; 未安装时按原错误路径返回 code 500)"""
    rid = query_params.get("id")
    if not rid:
        return {"code": 400, "msg": "id 必填", "data": None}
    record = db.query(BirthdayRecord).filter(BirthdayRecord.user_id == user_id,
                                             BirthdayRecord.id == rid).first()
    if not record:
        return {"code": 404, "msg": "记录不存在", "data": None}

    _ensure_birthday_both_calendars(db, record)
    if not record.solar_date:
        return {"code": 400, "msg": "生日日期缺失，无法测算八字", "data": None}

    hour = record.birth_hour
    if query_params.get("hour") not in [None, ""]:
        try:
            hour = int(query_params.get("hour"))
        except Exception:
            return {"code": 400, "msg": "hour 参数错误", "data": None}

    sect = 2
    if query_params.get("sect") not in [None, ""]:
        try:
            sect = int(query_params.get("sect"))
        except Exception:
            return {"code": 400, "msg": "sect 参数错误", "data": None}
        if sect not in (1, 2):
            return {"code": 400, "msg": "sect 参数错误", "data": None}

    try:
        data = _build_bazi_payload(record, hour=hour, sect=sect)
    except Exception as e:
        logger.exception("bazi calc failed: %s", e)
        return {"code": 500, "msg": "八字测算失败，请稍后重试", "data": None}
    return {"code": 200, "msg": "ok", "data": data}


# ── 八字 / 五行 (原 views.py 移植) ──

_GAN_WUXING = {"甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土",
               "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水"}
_ZHI_WUXING = {"子": "水", "丑": "土", "寅": "木", "卯": "木", "辰": "土", "巳": "火",
               "午": "火", "未": "土", "申": "金", "酉": "金", "戌": "土", "亥": "水"}
_WUXING_ORDER = ["金", "木", "水", "火", "土"]
_GAN_YINYANG = {"甲": "阳", "乙": "阴", "丙": "阳", "丁": "阴", "戊": "阳",
                "己": "阴", "庚": "阳", "辛": "阴", "壬": "阳", "癸": "阴"}
_ZHI_YINYANG = {"子": "阳", "丑": "阴", "寅": "阳", "卯": "阴", "辰": "阳", "巳": "阴",
                "午": "阳", "未": "阴", "申": "阳", "酉": "阴", "戌": "阳", "亥": "阴"}
_SHISHEN_GEJU = {"比肩": "建禄格", "劫财": "月刃格", "食神": "食神格", "伤官": "伤官格",
                 "偏财": "偏财格", "正财": "正财格", "七杀": "七杀格", "正官": "正官格",
                 "偏印": "偏印格", "正印": "正印格"}


def _build_bazi_payload(record: BirthdayRecord, hour=None, sect=2) -> dict:
    from lunar_python import Solar

    solar_dt = record.solar_date
    h = int(hour) if hour is not None else None
    if h is not None and (h < 0 or h > 23):
        h = None
    solar = Solar.fromYmdHms(solar_dt.year, solar_dt.month, solar_dt.day, h if h is not None else 0, 0, 0)
    lunar = solar.getLunar()
    ec = lunar.getEightChar()
    ec.setSect(sect)  # 子时换日流派: 1=晚子时算明天 2=晚子时算当天(默认)

    def _pillar(label, key, gan, zhi, nayin, shishen_gan, hide_gan, shishen_zhi, dishi):
        return {
            "key": key, "label": label, "ganzhi": f"{gan}{zhi}", "gan": gan, "zhi": zhi,
            "gan_wuxing": _GAN_WUXING.get(gan, ""), "zhi_wuxing": _ZHI_WUXING.get(zhi, ""),
            "gan_yinyang": _GAN_YINYANG.get(gan, ""), "zhi_yinyang": _ZHI_YINYANG.get(zhi, ""),
            "gan_shishen": shishen_gan, "zhi_hide_gan": hide_gan,
            "zhi_shishen_benqi": shishen_zhi, "dishi": dishi, "nayin": nayin,
        }

    pillars = [
        _pillar("年柱", "year", ec.getYearGan(), ec.getYearZhi(), ec.getYearNaYin(),
                ec.getYearShiShenGan(), "".join(ec.getYearHideGan()), (ec.getYearShiShenZhi() or [""])[0], ec.getYearDiShi()),
        _pillar("月柱", "month", ec.getMonthGan(), ec.getMonthZhi(), ec.getMonthNaYin(),
                ec.getMonthShiShenGan(), "".join(ec.getMonthHideGan()), (ec.getMonthShiShenZhi() or [""])[0], ec.getMonthDiShi()),
        _pillar("日柱", "day", ec.getDayGan(), ec.getDayZhi(), ec.getDayNaYin(),
                ec.getDayShiShenGan(), "".join(ec.getDayHideGan()), (ec.getDayShiShenZhi() or [""])[0], ec.getDayDiShi()),
    ]
    if h is not None:
        pillars.append(_pillar("时柱", "time", ec.getTimeGan(), ec.getTimeZhi(), ec.getTimeNaYin(),
                               ec.getTimeShiShenGan(), "".join(ec.getTimeHideGan()),
                               (ec.getTimeShiShenZhi() or [""])[0], ec.getTimeDiShi()))
    else:
        pillars.append({"key": "time", "label": "时柱", "ganzhi": None, "gan": None, "zhi": None,
                        "gan_wuxing": None, "zhi_wuxing": None, "gan_yinyang": None, "zhi_yinyang": None,
                        "gan_shishen": None, "zhi_hide_gan": None, "zhi_shishen_benqi": None,
                        "dishi": None, "nayin": None})

    count = {k: 0 for k in _WUXING_ORDER}
    for p in pillars:
        for wx in (p.get("gan_wuxing"), p.get("zhi_wuxing")):
            if wx in count:
                count[wx] += 1

    missing = [k for k in _WUXING_ORDER if count[k] == 0]
    strongest = max(_WUXING_ORDER, key=lambda k: count[k]) if any(count.values()) else None

    leap_txt = "闰" if record.lunar_is_leap else ""
    lunar_text = f"{lunar.getYearInChinese()}年{leap_txt}{lunar.getMonthInChinese()}月{lunar.getDayInChinese()}"

    year_nayin = ec.getYearNaYin()
    day_gan = ec.getDayGan()
    month_benqi_shishen = (ec.getMonthShiShenZhi() or [""])[0]

    # 大运流年: 需要性别 (阳男阴女顺排、阴男阳女逆排)
    yun_info = None
    if record.gender in (0, 1):
        yun = ec.getYun(1 if record.gender == 1 else 0)
        dayuns = []
        for dy in yun.getDaYun():
            liunian = [{"year": x.getYear(), "age": x.getAge(), "ganzhi": x.getGanZhi()}
                       for x in (dy.getLiuNian() or [])]
            dayuns.append({
                "ganzhi": dy.getGanZhi() or None,
                "start_year": dy.getStartYear(), "end_year": dy.getEndYear(),
                "start_age": dy.getStartAge(), "end_age": dy.getEndAge(),
                "liunian": liunian,
            })
        start_solar = yun.getStartSolar()
        yun_info = {
            "gender": record.gender,
            "start_text": f"{yun.getStartYear()}年{yun.getStartMonth()}个月{yun.getStartDay()}天",
            "start_solar": start_solar.toYmd() if start_solar else None,
            "dayuns": dayuns,
        }

    return {
        "name": record.name,
        "solar_date": solar_dt.isoformat(),
        "lunar_text": lunar_text,
        "lunar_is_leap": bool(record.lunar_is_leap),
        "year_ganzhi": ec.getYearGan() + ec.getYearZhi(),
        "zodiac": lunar.getYearShengXiao(),
        "year_nayin": year_nayin,
        "life_element": year_nayin[-1] if year_nayin else None,
        "hour": h,
        "pillars": pillars,
        "wuxing_count": count,
        "missing_wuxing": missing,
        "strongest_wuxing": strongest,
        "count_basis": 8 if h is not None else 6,
        "geju": _SHISHEN_GEJU.get(month_benqi_shishen),
        "geju_shishen": month_benqi_shishen,
        "taiyuan": ec.getTaiYuan(),
        "minggong": ec.getMingGong(),
        "shengong": ec.getShenGong(),
        "xunkong": "".join(ec.getDayXunKong()),
        "rizhu": {
            "gan": day_gan, "yinyang": _GAN_YINYANG.get(day_gan, ""),
            "wuxing": _GAN_WUXING.get(day_gan, ""), "nayin": ec.getDayNaYin(),
        },
        "sect": sect,
        "yun": yun_info,
    }


# ══════════════════════════════════════════════
# 访问统计 /baby/access/* (原 access_views, bug-for-bug 兼容)
# ══════════════════════════════════════════════

def access_stats(db: Session, user_id: int) -> dict:
    """访问统计: today_stats.avg_duration 在原版里实为 count('duration') — 保持一致"""
    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())

    recent_access = (db.query(UserAccessLog.path, UserAccessLog.method,
                              func.count(UserAccessLog.id).label("count"))
                     .filter(UserAccessLog.user_id == user_id)
                     .group_by(UserAccessLog.path, UserAccessLog.method)
                     .order_by(func.count(UserAccessLog.id).desc())
                     .limit(20))
    recent_access = [{"path": r.path, "method": r.method, "count": r.count} for r in recent_access]

    since = datetime.now() - timedelta(hours=24)
    hourly_rows = (db.query(
        func.date_format(UserAccessLog.created_at, "%Y-%m-%d %H:00:00").label("hour"),
        func.count(UserAccessLog.id).label("count"))
        .filter(UserAccessLog.user_id == user_id, UserAccessLog.created_at >= since)
        .group_by(func.date_format(UserAccessLog.created_at, "%Y-%m-%d %H:00:00"))
        .order_by(func.date_format(UserAccessLog.created_at, "%Y-%m-%d %H:00:00")))
    hourly_stats = [{"hour": r.hour.replace(" ", "T"), "count": r.count} for r in hourly_rows]

    today_row = (db.query(func.count(UserAccessLog.id).label("total_requests"),
                          func.count(UserAccessLog.duration).label("avg_duration"))
                 .filter(UserAccessLog.user_id == user_id, UserAccessLog.created_at >= today_start).first())

    recent_logs = (db.query(UserAccessLog).filter(UserAccessLog.user_id == user_id)
                   .order_by(UserAccessLog.created_at.desc()).limit(10))
    recent_logs = [{"path": l.path, "method": l.method, "response_status": l.response_status,
                    "duration": l.duration, "created_at": _iso(l.created_at), "ip_address": l.ip_address}
                   for l in recent_logs]

    return {
        "recent_access": recent_access,
        "hourly_stats": hourly_stats,
        "today_stats": {
            "total_requests": today_row.total_requests or 0,
            "avg_duration": round(today_row.avg_duration or 0, 3),
        },
        "recent_logs": recent_logs,
    }


def access_detail(db: Session, user_id: int, path: str | None) -> dict:
    """访问详情: 最近 100 条 + 该路径统计"""
    query = db.query(UserAccessLog).filter(UserAccessLog.user_id == user_id)
    stats_query = db.query(
        func.count(UserAccessLog.id).label("total_count"),
        func.avg(UserAccessLog.duration).label("avg_duration"),
        func.max(UserAccessLog.duration).label("max_duration"),
        func.min(UserAccessLog.duration).label("min_duration"),
    ).filter(UserAccessLog.user_id == user_id)
    if path:
        query = query.filter(UserAccessLog.path.contains(path))
        stats_query = stats_query.filter(UserAccessLog.path.contains(path))

    logs = query.order_by(UserAccessLog.created_at.desc()).limit(100)
    stats = stats_query.first()

    return {
        "logs": [{"path": l.path, "method": l.method, "response_status": l.response_status,
                  "duration": l.duration, "created_at": _iso(l.created_at),
                  "ip_address": l.ip_address, "user_agent": l.user_agent} for l in logs],
        "stats": {
            "total_count": stats.total_count or 0,
            "avg_duration": round(stats.avg_duration or 0, 3),
            "max_duration": round(stats.max_duration or 0, 3),
            "min_duration": round(stats.min_duration or 0, 3),
        },
    }
