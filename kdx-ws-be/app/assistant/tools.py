"""
Assistant 工具集：覆盖首页全部应用的宝宝数据工具

注册清单 (name / 写操作):
- get_baby_info           读  宝宝信息(名字/生日/月龄)
- query_feed_milk         读  查询喂奶记录(今日/区间奶量汇总)
- add_feed_milk           写✓ 记录喂奶
- query_temperature       读  查询体温
- add_temperature         写✓ 记录体温
- query_sleep             读  查询睡眠
- add_sleep               写✓ 记录睡眠
- query_diapers           读  查询尿不湿
- add_diaper              写✓ 记录尿不湿
- query_expense           读  查询花费
- add_expense             写✓ 记录花费
- query_growth            读  查询身高体重
- add_growth              写✓ 记录身高体重
- query_vaccines          读  查询疫苗(待接种/已接种)
- mark_vaccine_done       写✓ 标记疫苗已接种
- query_birthdays         读  查询生日提醒

写操作统一接受 user_id / request_id (幂等键) 参数，由 repository 写库，
graph 层在执行写操作前触发 HITL 确认流程。
"""

from datetime import date, datetime, timedelta

from .repository import BabyDataRepository
from .tool_registry import ToolRegistry

# ──────────────────────────────────────────────
# 日期解析辅助 (LLM 传入的相对日期转绝对日期)
# ──────────────────────────────────────────────

def parse_day(s: str, default: date = None) -> date:
    """'today' / 'yesterday' / '2026-08-26' → date"""
    s = (s or "").strip().lower()
    today = date.today()
    if s in ("", "today", "今天", "今日"):
        return today
    if s in ("yesterday", "昨天", "昨日"):
        return today - timedelta(days=1)
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return default if default else today


def parse_datetime_arg(s: str, default: datetime = None) -> datetime:
    s = (s or "").strip()
    if not s:
        return default if default else datetime.now()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M",
                "%Y-%m-%d", "%Y/%m/%d %H:%M", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt
        except ValueError:
            continue
    return default if default else datetime.now()


def _repo() -> BabyDataRepository:
    from ..core.database import SessionLocal
    return BabyDataRepository(SessionLocal())


def _day_range(day: date):
    start = datetime.combine(day, datetime.min.time())
    end = datetime.combine(day + timedelta(days=1), datetime.min.time()) - timedelta(seconds=1)
    return start, end


# ──────────────────────────────────────────────
# 工具实现 (全部同步函数; user_id 由 Agent 层注入，不暴露给 LLM)
# ──────────────────────────────────────────────

def make_tools(repo_factory=_repo):

    def get_baby_info(user_id: int, request_id: str = "") -> dict:
        info = repo_factory().get_baby_info(user_id)
        if not info:
            return {"found": False, "message": "尚未添加宝宝信息"}
        birthday = info["birthday"]
        birth = date.fromisoformat(birthday)
        today = date.today()
        months = (today.year - birth.year) * 12 + today.month - birth.month
        if today.day < birth.day:
            months -= 1
        info["age_months"] = max(months, 0)
        info["age_days"] = (today - birth).days
        return {"found": True, "baby": info}

    def query_feed_milk(user_id: int, day: str = "today", request_id: str = "") -> dict:
        d = parse_day(day)
        start, end = _day_range(d)
        return repo_factory().query_feed_milk(user_id, start, end)

    def add_feed_milk(user_id: int, milk_volume: int, feed_time: str = "",
                      feed_type: str = "bottle", note: str = "",
                      request_id: str = "") -> dict:
        dt = parse_datetime_arg(feed_time, datetime.now())
        return repo_factory().add_feed_milk(user_id, dt, int(milk_volume),
                                            feed_type or "bottle", note)

    def query_temperature(user_id: int, day: str = "today", request_id: str = "") -> dict:
        return {"day": str(parse_day(day)),
                "records": repo_factory().query_temperature(user_id, parse_day(day))}

    def add_temperature(user_id: int, temperature: float, day: str = "today",
                        status: str = "", request_id: str = "") -> dict:
        t = float(temperature)
        if t < 30 or t > 45:
            return {"ok": False, "message": "体温数值异常，请确认(单位℃)"}
        return repo_factory().add_temperature(user_id, parse_day(day), t, status)

    def query_sleep(user_id: int, day: str = "today", request_id: str = "") -> dict:
        d = parse_day(day)
        start, end = _day_range(d)
        return repo_factory().query_sleep(user_id, start, end)

    def add_sleep(user_id: int, status: str = "sleep", sleep_time: str = "",
                  duration_minutes: int = 0, describe: str = "",
                  request_id: str = "") -> dict:
        dt = parse_datetime_arg(sleep_time, datetime.now())
        return repo_factory().add_sleep(user_id, dt, status or "sleep",
                                        int(duration_minutes or 0), describe)

    def query_diapers(user_id: int, day: str = "today", request_id: str = "") -> dict:
        d = parse_day(day)
        start, end = _day_range(d)
        return repo_factory().query_diapers(user_id, start, end)

    def add_diaper(user_id: int, diaper_type: str = "peeing", use_date: str = "",
                   brand: str = "", describe: str = "", request_id: str = "") -> dict:
        dt = parse_datetime_arg(use_date, datetime.now())
        return repo_factory().add_diaper(user_id, dt, diaper_type or "peeing", brand, describe)

    def query_expense(user_id: int, start_day: str = "", end_day: str = "",
                      request_id: str = "") -> dict:
        today = date.today()
        sd = parse_day(start_day, today.replace(day=1))
        ed = parse_day(end_day, today)
        start, end = _day_range(sd), _day_range(ed)
        return repo_factory().query_expense(user_id, start[0], end[1])

    def add_expense(user_id: int, name: str, amount: float, tag: str = "",
                    order_time: str = "", request_id: str = "") -> dict:
        dt = parse_datetime_arg(order_time, datetime.now())
        return repo_factory().add_expense(user_id, dt, name, float(amount), tag)

    def query_growth(user_id: int, limit: int = 5, request_id: str = "") -> dict:
        return {"records": repo_factory().query_growth(user_id, int(limit or 5))}

    def add_growth(user_id: int, measure_date: str = "", height_cm: float = None,
                   weight_kg: float = None, head_circumference_cm: float = None,
                   request_id: str = "") -> dict:
        d = parse_day(measure_date, date.today())
        return repo_factory().add_growth(user_id, d, height_cm, weight_kg,
                                         head_circumference_cm)

    def query_vaccines(user_id: int, only_pending: bool = True,
                       request_id: str = "") -> dict:
        records = repo_factory().query_vaccines(user_id, bool(only_pending))
        today = date.today()
        for r in records:
            rd = date.fromisoformat(r["recommend_date"])
            r["overdue"] = rd < today
            r["days_until"] = (rd - today).days
        return {"count": len(records), "records": records}

    def mark_vaccine_done(user_id: int, vaccine_key: str,
                          actual_date: str = "", request_id: str = "") -> dict:
        d = parse_day(actual_date, date.today())
        result = repo_factory().mark_vaccine_done(user_id, vaccine_key, d)
        if not result:
            return {"ok": False, "message": f"未找到待接种记录: {vaccine_key}"}
        return result

    def query_birthdays(user_id: int, days: int = 60, request_id: str = "") -> dict:
        return {"records": repo_factory().query_birthdays(user_id, int(days or 60))}

    # ── 待办 (与 HTTP /todos 共用 TodoService 存储: TODO_REPO=redis 时同一份 Redis 数据) ──

    def _todo_service():
        """进程级缓存 (与 HTTP 路由同构): InMemory 仓库按调用新建会互相看不见"""
        if not hasattr(_todo_service, "_svc"):
            from ..core.config import get_settings
            from ..integrations.todo_repo import create_todo_repository
            from ..services.todo_service import TodoService
            _todo_service._svc = TodoService(create_todo_repository(get_settings()))
        return _todo_service._svc

    def _todo_brief(t) -> dict:
        return {"id": t.id, "title": t.title, "completed": t.completed}

    def query_todos(user_id: int, only_pending: bool = False, request_id: str = "") -> dict:
        items = _todo_service().list_items(str(user_id))
        if only_pending:
            items = [x for x in items if not x.completed]
        return {"total": len(items),
                "todos": [_todo_brief(x) for x in items]}

    def add_todo(user_id: int, title: str, request_id: str = "") -> dict:
        from ..schemas.todo import TodoCreateRequest
        item = _todo_service().create_item(str(user_id), TodoCreateRequest(title=title))
        return {"ok": True, "message": "待办已创建", "todo": _todo_brief(item)}

    def complete_todo(user_id: int, todo_id: str = "", title_match: str = "",
                      completed: bool = True, request_id: str = "") -> dict:
        """按 id 或标题模糊匹配完成待办 (LLM 拿到的常是标题而非 uuid)"""
        from ..schemas.todo import TodoUpdateRequest
        svc = _todo_service()
        uid = str(user_id)
        if not todo_id and title_match:
            matches = [x for x in svc.list_items(uid)
                       if title_match in x.title and x.completed != bool(completed)]
            if not matches:
                return {"ok": False,
                        "message": f"未找到标题含'{title_match}'的待办"}
            todo_id = matches[0].id
        try:
            item = svc.update_item(uid, todo_id,
                                   TodoUpdateRequest(completed=bool(completed)))
        except KeyError:
            return {"ok": False, "message": "待办不存在，可先用 query_todos 查询"}
        return {"ok": True, "todo": _todo_brief(item)}

    return {
        "get_baby_info": get_baby_info,
        "query_feed_milk": query_feed_milk,
        "add_feed_milk": add_feed_milk,
        "query_temperature": query_temperature,
        "add_temperature": add_temperature,
        "query_sleep": query_sleep,
        "add_sleep": add_sleep,
        "query_diapers": query_diapers,
        "add_diaper": add_diaper,
        "query_expense": query_expense,
        "add_expense": add_expense,
        "query_growth": query_growth,
        "add_growth": add_growth,
        "query_vaccines": query_vaccines,
        "mark_vaccine_done": mark_vaccine_done,
        "query_birthdays": query_birthdays,
        "query_todos": query_todos,
        "add_todo": add_todo,
        "complete_todo": complete_todo,
    }


# ──────────────────────────────────────────────
# 注册到 Registry
# ──────────────────────────────────────────────

def register_baby_tools(registry: ToolRegistry) -> None:
    t = make_tools()

    registry.register(ToolMeta_for(
        "get_baby_info", "获取宝宝信息：名字、生日、月龄。回答与宝宝相关的问题前建议先调用。",
        {"type": "object", "properties": {}, "required": []},
        t["get_baby_info"], is_write=False, tags=["baby"],
    ))
    registry.register(ToolMeta_for(
        "query_feed_milk", "查询喂奶记录：某天的喂奶次数与总奶量(ml)。day 可为 today/yesterday/YYYY-MM-DD。",
        {"type": "object", "properties": {"day": {"type": "string", "description": "today/yesterday/YYYY-MM-DD，默认 today"}}, "required": []},
        t["query_feed_milk"], is_write=False, tags=["milk"],
    ))
    registry.register(ToolMeta_for(
        "add_feed_milk", "记录一次喂奶。需要奶量 milk_volume(ml)；feed_time 缺省为现在；feed_type: bottle/breast/formula。",
        {"type": "object",
         "properties": {
             "milk_volume": {"type": "integer", "description": "奶量 ml"},
             "feed_time": {"type": "string", "description": "喂奶时间 YYYY-MM-DD HH:MM，缺省为现在"},
             "feed_type": {"type": "string", "enum": ["bottle", "breast", "formula"]},
             "note": {"type": "string"},
         },
         "required": ["milk_volume"]},
        t["add_feed_milk"], is_write=True, tags=["milk"],
    ))
    registry.register(ToolMeta_for(
        "query_temperature", "查询某天体温记录。",
        {"type": "object", "properties": {"day": {"type": "string"}}, "required": []},
        t["query_temperature"], is_write=False, tags=["temperature"],
    ))
    registry.register(ToolMeta_for(
        "add_temperature", "记录体温(℃)，范围 30~45；同一天重复记录会覆盖。",
        {"type": "object",
         "properties": {
             "temperature": {"type": "number", "description": "体温，如 36.8"},
             "day": {"type": "string", "description": "默认 today"},
             "status": {"type": "string", "description": "状态备注，如 正常/低烧"},
         },
         "required": ["temperature"]},
        t["add_temperature"], is_write=True, tags=["temperature"],
    ))
    registry.register(ToolMeta_for(
        "query_sleep", "查询某天睡眠记录：次数与总时长(分钟)。",
        {"type": "object", "properties": {"day": {"type": "string"}}, "required": []},
        t["query_sleep"], is_write=False, tags=["sleep"],
    ))
    registry.register(ToolMeta_for(
        "add_sleep", "记录一次睡眠。status: sleep(入睡)/wake(醒来)/nap(小睡)。",
        {"type": "object",
         "properties": {
             "status": {"type": "string", "enum": ["sleep", "wake", "nap"]},
             "sleep_time": {"type": "string", "description": "YYYY-MM-DD HH:MM，缺省为现在"},
             "duration_minutes": {"type": "integer"},
             "describe": {"type": "string"},
         },
         "required": []},
        t["add_sleep"], is_write=True, tags=["sleep"],
    ))
    registry.register(ToolMeta_for(
        "query_diapers", "查询某天尿不湿记录：次数与类型分布(peeing/poop)。",
        {"type": "object", "properties": {"day": {"type": "string"}}, "required": []},
        t["query_diapers"], is_write=False, tags=["diaper"],
    ))
    registry.register(ToolMeta_for(
        "add_diaper", "记录一次尿不湿更换。diaper_type: peeing/poop/mixed。",
        {"type": "object",
         "properties": {
             "diaper_type": {"type": "string", "enum": ["peeing", "poop", "mixed"]},
             "use_date": {"type": "string", "description": "YYYY-MM-DD HH:MM，缺省为现在"},
             "brand": {"type": "string"},
             "describe": {"type": "string"},
         },
         "required": []},
        t["add_diaper"], is_write=True, tags=["diaper"],
    ))
    registry.register(ToolMeta_for(
        "query_expense", "查询花费：区间总额、分类汇总。start_day 默认本月1号，end_day 默认今天。",
        {"type": "object",
         "properties": {"start_day": {"type": "string"}, "end_day": {"type": "string"}},
         "required": []},
        t["query_expense"], is_write=False, tags=["expense"],
    ))
    registry.register(ToolMeta_for(
        "add_expense", "记录一笔花费。name 必填；amount 必填(元)。",
        {"type": "object",
         "properties": {
             "name": {"type": "string", "description": "项目名，如 奶粉/疫苗/玩具"},
             "amount": {"type": "number", "description": "金额(元)"},
             "tag": {"type": "string", "description": "分类标签"},
             "order_time": {"type": "string", "description": "YYYY-MM-DD HH:MM，缺省为现在"},
         },
         "required": ["name", "amount"]},
        t["add_expense"], is_write=True, tags=["expense"],
    ))
    registry.register(ToolMeta_for(
        "query_growth", "查询成长记录(身高cm/体重kg/头围cm)，默认最近5条。",
        {"type": "object", "properties": {"limit": {"type": "integer"}}, "required": []},
        t["query_growth"], is_write=False, tags=["growth"],
    ))
    registry.register(ToolMeta_for(
        "add_growth", "记录一次成长测量：身高/体重/头围，至少提供一项。",
        {"type": "object",
         "properties": {
             "measure_date": {"type": "string", "description": "默认 today"},
             "height_cm": {"type": "number"},
             "weight_kg": {"type": "number"},
             "head_circumference_cm": {"type": "number"},
         },
         "required": []},
        t["add_growth"], is_write=True, tags=["growth"],
    ))
    registry.register(ToolMeta_for(
        "query_vaccines", "查询疫苗接种计划。only_pending=true 查待接种(含是否过期/剩余天数)。",
        {"type": "object", "properties": {"only_pending": {"type": "boolean"}}, "required": []},
        t["query_vaccines"], is_write=False, tags=["vaccine"],
    ))
    registry.register(ToolMeta_for(
        "mark_vaccine_done", "标记某支疫苗已完成接种。vaccine_key 必填(可从 query_vaccines 结果获取)。",
        {"type": "object",
         "properties": {
             "vaccine_key": {"type": "string"},
             "actual_date": {"type": "string", "description": "实际接种日期，默认 today"},
         },
         "required": ["vaccine_key"]},
        t["mark_vaccine_done"], is_write=True, tags=["vaccine"],
    ))
    registry.register(ToolMeta_for(
        "query_birthdays", "查询未来N天内(默认60)的家庭生日提醒，含倒计天数。",
        {"type": "object", "properties": {"days": {"type": "integer"}}, "required": []},
        t["query_birthdays"], is_write=False, tags=["birthday"],
    ))
    registry.register(ToolMeta_for(
        "query_todos", "查询待办事项列表。only_pending=true 只看未完成的。",
        {"type": "object", "properties": {"only_pending": {"type": "boolean"}}, "required": []},
        t["query_todos"], is_write=False, tags=["todo"],
    ))
    registry.register(ToolMeta_for(
        "add_todo", "新建一条待办事项。title 必填，如'明天带宝宝打疫苗'。",
        {"type": "object",
         "properties": {"title": {"type": "string", "description": "待办内容"}},
         "required": ["title"]},
        t["add_todo"], is_write=True, tags=["todo"],
    ))
    registry.register(ToolMeta_for(
        "complete_todo", "完成(或取消完成)一条待办。todo_id 与 title_match 二选一，"
                         "title_match 为待办标题中的关键词。",
        {"type": "object",
         "properties": {
             "todo_id": {"type": "string", "description": "待办 id (可从 query_todos 获取)"},
             "title_match": {"type": "string", "description": "标题关键词, 如'打疫苗'"},
             "completed": {"type": "boolean", "description": "true=完成, false=取消完成, 默认 true"},
         },
         "required": []},
        t["complete_todo"], is_write=True, tags=["todo"],
    ))


def ToolMeta_for(name, description, parameters, handler, is_write=False, tags=None):
    from .tool_registry import ToolMeta
    return ToolMeta(name=name, description=description, parameters=parameters,
                    handler=handler, is_write=is_write, tags=tags or [])
