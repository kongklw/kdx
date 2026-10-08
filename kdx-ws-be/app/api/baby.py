"""baby 模块路由 (工厂模式)

URL 路径与 Django kdx-be/baby/urls.py 完全一致 (前缀 /baby/), 每条 path 的
HTTP 方法集合也与原视图定义一致。响应统一为 {"code", "msg", "data"} JSON 形状。
"""

from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..core.database import get_db
from ..core.security import extract_token_from_headers, verify_jwt
from ..schemas.baby import (
    AlbumCreateBody,
    AiGenBody,
    BabyInfoBody,
    BabyPantsBody,
    BatchDeleteExpenseBody,
    BatchExpenseBody,
    BirthdayBody,
    DailyHabitBody,
    DashboardOrderBody,
    ExpenseBody,
    ExpenseListBody,
    ExpenseTagBody,
    FeedMilkBody,
    GrowingBlogBody,
    GrowthRecordBody,
    PeriodLogBody,
    PeriodSettingsBody,
    SleepBody,
    SleepListBody,
    TemperatureBody,
    TodoCreateBody,
    TodoUpdateBody,
    VaccineAddPaidBody,
    VaccineToggleBody,
)
from ..services import baby_service as svc
from .deps import resolve_user_id


def create_baby_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/baby", tags=["baby"])

    # ── 鉴权辅助 ──────────────────────────────

    def _unauthorized(msg: str) -> JSONResponse:
        """与 DRF 401 行为对齐"""
        return JSONResponse({"code": 401, "msg": msg, "data": None}, status_code=401)

    def get_uid(request: Request, required: bool = True) -> tuple[Optional[str], Optional[JSONResponse]]:
        """解析当前用户 id。

        required=True: 对应原视图 permission_classes=[IsAuthenticated],
        必须携带有效 JWT (payload 含 user_id/sub), 否则 401。
        required=False: 原视图未声明权限类 (DRF 默认 AllowAny),
        按 resolve_user_id 约定 (token 或 query 参数 user_id) 解析, 不加严。
        """
        token = extract_token_from_headers(request.headers.get("authorization"))
        if token:
            try:
                payload = verify_jwt(token, settings)
                uid = payload.get("user_id") or payload.get("sub")
                if uid is not None:
                    return str(uid), None
            except Exception:
                if required:
                    return None, _unauthorized("Authentication credentials were not provided.")
        elif required:
            return None, _unauthorized("Authentication credentials were not provided.")
        return resolve_user_id(request, settings), None

    async def parse_body_and_files(request: Request) -> tuple[dict, list]:
        """兼容 JSON / form / multipart 请求体 (DRF 多解析器行为), 返回 (data, files)"""
        ctype = (request.headers.get("content-type") or "").lower()
        if ctype.startswith("multipart/form-data") or ctype.startswith("application/x-www-form-urlencoded"):
            form = await request.form()
            data: dict = {}
            files: list = []
            for key, value in form.multi_items():
                if hasattr(value, "read"):  # UploadFile
                    content = await value.read()
                    files.append({"filename": value.filename, "content_type": value.content_type,
                                  "content": content})
                else:
                    data[key] = value
            return data, files
        try:
            data = await request.json()
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        return data, []

    def _int_query(request: Request, name: str, default: int, minimum: int | None = None) -> int:
        try:
            value = int(request.query_params.get(name, default))
        except (TypeError, ValueError):
            value = default
        if minimum is not None and value < minimum:
            value = minimum
        return value

    def _base_url(request: Request) -> str:
        return str(request.base_url).rstrip("/")

    # ── 宝宝信息 /baby/info ──────────────────────

    @router.get("/info")
    async def baby_info_get(request: Request, db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        return JSONResponse(svc.get_baby_info(db, svc.uid_int(uid)))

    @router.post("/info")
    async def baby_info_post(request: Request, db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        data, files = await parse_body_and_files(request)
        image_key = None
        for f in files:
            if f.get("filename"):
                image_key = svc.save_upload(f.get("content") or b"", f["filename"], "baby")
                break
        return JSONResponse(svc.save_baby_info(db, user_id, data, image_key))

    # ── dashboard /baby/dashboard ────────────────

    @router.post("/dashboard")
    async def dashboard_post(request: Request, body: DashboardOrderBody,
                             db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.dashboard_save_order(db, user_id, body.app_order))

    @router.get("/dashboard")
    async def dashboard_get(request: Request, db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.dashboard_overview(db, user_id))

    # ── 成长博客 /baby/growing, /baby/ai_gen ─────

    @router.get("/growing")
    async def growing_get(request: Request, db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        return JSONResponse(svc.growing_blog_list(db, svc.uid_int(uid)))

    @router.post("/growing")
    async def growing_post(request: Request, body: GrowingBlogBody,
                           db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        return JSONResponse(svc.growing_blog_create(db, svc.uid_int(uid), body.model_dump(exclude_unset=True)))

    @router.delete("/growing")
    async def growing_delete(request: Request, db: Session = Depends(get_db)):
        get_uid(request, required=False)
        try:
            data = await request.json()
        except Exception:
            data = {}
        return JSONResponse(svc.growing_blog_delete(db, data.get("id")))

    @router.post("/ai_gen")
    async def ai_gen_post(body: AiGenBody):
        return JSONResponse(svc.ai_gen(body.model_dump(exclude_unset=True)))

    # ── 待办 /baby/todo, /baby/todo_table ────────

    @router.get("/todo")
    async def todo_get(request: Request, db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        user_id = svc.uid_int(uid)
        if user_id is None:
            return JSONResponse({"code": 200, "data": [], "msg": "ok"})
        return JSONResponse(svc.todo_list(db, user_id,
                                          request.query_params.get("start_date"),
                                          request.query_params.get("end_date")))

    @router.post("/todo")
    async def todo_post(request: Request, body: TodoCreateBody, db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.todo_create(db, user_id, body.model_dump(exclude_unset=True)))

    @router.put("/todo")
    async def todo_put(request: Request, body: TodoUpdateBody, db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.todo_update(db, user_id, body.model_dump(exclude_unset=True)))

    @router.delete("/todo")
    async def todo_delete(request: Request, body: TodoUpdateBody, db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.todo_delete(db, user_id, body.id))

    @router.get("/todo_table")
    async def todo_table_get(request: Request, db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        user_id = svc.uid_int(uid)
        if user_id is None:
            return JSONResponse({"code": 200, "data": [], "msg": "ok"})
        return JSONResponse(svc.todo_table(db, user_id,
                                           request.query_params.get("start_date"),
                                           request.query_params.get("end_date")))

    # ── 每日习惯 /baby/daily_habit ───────────────

    @router.get("/daily_habit")
    async def habit_get(request: Request, db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        user_id = svc.uid_int(uid)
        if user_id is None:
            return JSONResponse({"code": 200, "data": [], "msg": "ok"})
        return JSONResponse(svc.habit_list(db, user_id))

    @router.post("/daily_habit")
    async def habit_post(request: Request, body: DailyHabitBody, db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.habit_create(db, user_id, body.model_dump(exclude_unset=True)))

    @router.put("/daily_habit")
    async def habit_put(request: Request, body: DailyHabitBody, db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.habit_update(db, user_id, body.model_dump(exclude_unset=True)))

    @router.delete("/daily_habit")
    async def habit_delete(request: Request, body: DailyHabitBody, db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.habit_delete(db, user_id, body.id))

    # ── 喂奶 /baby/feed, /baby/feed_chart ────────

    @router.get("/feed")
    async def feed_get(request: Request, db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.feed_list(db, user_id,
                                          request.query_params.get("start_time"),
                                          request.query_params.get("end_time")))

    @router.post("/feed")
    async def feed_post(request: Request, body: FeedMilkBody, db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.feed_create(db, user_id, body.model_dump(exclude_unset=True)))

    @router.put("/feed")
    async def feed_put(request: Request, body: FeedMilkBody, db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.feed_update(db, user_id, body.model_dump(exclude_unset=True)))

    @router.delete("/feed")
    async def feed_delete(request: Request, body: FeedMilkBody, db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        return JSONResponse(svc.feed_delete(db, body.id))

    @router.get("/feed_chart")
    async def feed_chart_get(request: Request, db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.feed_chart(db, user_id))

    # ── 体温 /baby/temperature ───────────────────

    @router.get("/temperature")
    async def temperature_get(request: Request, db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        user_id = svc.uid_int(uid)
        if user_id is None:
            return JSONResponse({"code": 200, "data": {"results": [], "temperature": "未测"}, "msg": "ok"})
        return JSONResponse(svc.temperature_list(db, user_id,
                                                 request.query_params.get("start_date"),
                                                 request.query_params.get("end_date")))

    @router.post("/temperature")
    async def temperature_post(request: Request, body: TemperatureBody,
                               db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.temperature_create(db, user_id, body.model_dump(exclude_unset=True)))

    @router.delete("/temperature")
    async def temperature_delete(request: Request, body: TemperatureBody,
                                 db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        return JSONResponse(svc.temperature_delete(db, body.id))

    # ── 尿不湿 /baby/pants ───────────────────────

    @router.get("/pants")
    async def pants_get(request: Request, db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        user_id = svc.uid_int(uid)
        if user_id is None:
            return JSONResponse({"code": 200, "data": {"results": [], "count": 0}, "msg": "fetch all success"})
        page_size = min(_int_query(request, "page_size", 20), 100)
        page = _int_query(request, "page", 1, minimum=1)
        return JSONResponse(svc.pants_list(db, user_id, request.query_params.get("use_date"),
                                           page, page_size))

    @router.post("/pants")
    async def pants_post(request: Request, body: BabyPantsBody, db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.pants_create(db, user_id, body.model_dump(exclude_unset=True)))

    @router.delete("/pants")
    async def pants_delete(request: Request, body: BabyPantsBody, db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        return JSONResponse(svc.pants_delete(db, body.id))

    # ── 折线图 /baby/line_chart ──────────────────

    @router.get("/line_chart")
    async def line_chart_get(request: Request, db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.line_chart(db, user_id))

    # ── 花费 /baby/expense* ──────────────────────

    @router.post("/expense_list")
    async def expense_list_post(request: Request, body: ExpenseListBody,
                                db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.expense_list(db, user_id, body.model_dump(exclude_unset=True)))

    @router.get("/expense")
    async def expense_get(request: Request, db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        user_id = svc.uid_int(uid)
        if user_id is None:
            return JSONResponse({"code": 200, "data": [], "msg": "ok"})
        # 原视图 GET 返回当天待办 (保持原行为)
        return JSONResponse(svc.expense_get_today_todos(db, user_id))

    @router.post("/expense")
    async def expense_post(request: Request, body: ExpenseBody, db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.expense_create(db, user_id, body.model_dump(exclude_unset=True)))

    @router.put("/expense")
    async def expense_put(request: Request, body: ExpenseBody, db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.expense_update(db, user_id, body.model_dump(exclude_unset=True)))

    @router.post("/batch_expense")
    async def batch_expense_post(request: Request, body: BatchExpenseBody,
                                 db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.batch_expense(db, user_id, body.model_dump(exclude_unset=True)))

    @router.post("/batch_delete_expense")
    async def batch_delete_expense_post(request: Request, body: BatchDeleteExpenseBody,
                                        db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.batch_delete_expense(db, user_id, body.ids))

    @router.get("/expense_tags")
    async def expense_tags_get(request: Request, db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        user_id = svc.uid_int(uid)
        if user_id is None:
            return JSONResponse({"code": 200, "data": [], "msg": "ok"})
        return JSONResponse(svc.expense_tag_list(db, user_id))

    @router.post("/expense_tags")
    async def expense_tags_post(request: Request, body: ExpenseTagBody,
                                db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.expense_tag_create(db, user_id, body.name))

    # ── 睡眠 /baby/sleep, /baby/sleep_list ───────

    @router.post("/sleep")
    async def sleep_post(request: Request, body: SleepBody, db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.sleep_create(db, user_id, body.model_dump(exclude_unset=True)))

    @router.post("/sleep_list")
    async def sleep_list_post(request: Request, body: SleepListBody,
                              db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        user_id = svc.uid_int(uid)
        if user_id is None:
            return JSONResponse({"code": 200, "data": {"results": [], "count": 0}, "msg": "ok"})
        return JSONResponse(svc.sleep_list(db, user_id, body.model_dump(exclude_unset=True)))

    # ── 相册 /baby/albums* ───────────────────────

    @router.get("/albums/")
    async def albums_get(request: Request, db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        page_size = _int_query(request, "page_size", 20)
        page_num = _int_query(request, "page_num", 1)
        return JSONResponse(svc.album_list(db, user_id, page_num, page_size))

    @router.post("/albums/")
    async def albums_post(request: Request, db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        data, files = await parse_body_and_files(request)
        return JSONResponse(svc.album_create(db, user_id, data, files))

    @router.delete("/albums/{pk}/")
    async def album_delete(request: Request, pk: int, db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.album_delete(db, user_id, pk))

    @router.get("/albums/video/{stream_id}/playback")
    async def album_playback(request: Request, stream_id: str, db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        result = svc.album_video_playback(db, user_id, stream_id, _base_url(request))
        return JSONResponse(result["body"], status_code=result["status_code"])

    @router.get("/albums/video/{stream_id}/hls/{playlist_path:path}")
    async def album_hls(stream_id: str, playlist_path: str):
        # 原视图 authentication_classes=[] → 不鉴权
        result = svc.album_video_hls(stream_id, playlist_path)
        if result["status_code"] == 200:
            return Response(result["text"], media_type=result["content_type"],
                             headers=result.get("headers"))
        if result["status_code"] == 307:
            return RedirectResponse(result["redirect"], status_code=307,
                                    headers=result.get("headers"))
        return JSONResponse(result["body"], status_code=result["status_code"])

    @router.get("/albums/video/{stream_id}/dash/{dash_path:path}")
    async def album_dash(stream_id: str, dash_path: str):
        # 原视图 authentication_classes=[] → 不鉴权
        result = svc.album_video_dash(stream_id, dash_path)
        if result["status_code"] == 200:
            return Response(result["text"], media_type=result["content_type"],
                             headers=result.get("headers"))
        if result["status_code"] == 307:
            return RedirectResponse(result["redirect"], status_code=307,
                                    headers=result.get("headers"))
        return JSONResponse(result["body"], status_code=result["status_code"])

    # ── 生长记录 /baby/growth_records* ───────────

    @router.get("/growth_records/")
    async def growth_records_get(request: Request, db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        page_size = _int_query(request, "page_size", 20)
        page_num = _int_query(request, "page_num", 1)
        return JSONResponse(svc.growth_record_list(db, user_id, page_num, page_size,
                                                   _base_url(request)))

    @router.post("/growth_records/")
    async def growth_records_post(request: Request, db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        data, files = await parse_body_and_files(request)
        photo_file = next((f for f in files if f.get("filename")), None)
        return JSONResponse(svc.growth_record_create(db, user_id, data, photo_file,
                                                     _base_url(request)))

    @router.get("/growth_records/{pk}/")
    async def growth_record_get(request: Request, pk: int, db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.growth_record_detail(db, user_id, pk, _base_url(request)))

    @router.put("/growth_records/{pk}/")
    async def growth_record_put(request: Request, pk: int, db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        data, files = await parse_body_and_files(request)
        photo_file = next((f for f in files if f.get("filename")), None)
        return JSONResponse(svc.growth_record_update(db, user_id, pk, data, photo_file,
                                                     _base_url(request)))

    @router.delete("/growth_records/{pk}/")
    async def growth_record_delete(request: Request, pk: int, db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.growth_record_delete(db, user_id, pk))

    # ── 疫苗 /baby/vaccines* ─────────────────────

    @router.get("/vaccines/schedule/")
    async def vaccine_schedule_get(request: Request, db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.vaccine_schedule(db, user_id))

    @router.post("/vaccines/toggle/")
    async def vaccine_toggle_post(request: Request, body: VaccineToggleBody,
                                  db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.vaccine_toggle(db, user_id, body.model_dump(exclude_unset=True)))

    @router.post("/vaccines/add_paid/")
    async def vaccine_add_paid_post(request: Request, body: VaccineAddPaidBody,
                                    db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.vaccine_add_paid(db, user_id, body.model_dump(exclude_unset=True)))

    # ── 经期 /baby/period* ───────────────────────

    @router.get("/period/overview")
    async def period_overview_get(request: Request, db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.period_overview(db, user_id, request.query_params.get("month")))

    @router.get("/period/log")
    async def period_log_get(request: Request, db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.period_log_get(db, user_id, request.query_params.get("date")))

    @router.post("/period/log")
    async def period_log_post(request: Request, body: PeriodLogBody,
                              db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.period_log_post(db, user_id, body.model_dump(exclude_unset=True)))

    @router.get("/period/settings")
    async def period_settings_get(request: Request, db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.period_settings_get(db, user_id))

    @router.post("/period/settings")
    async def period_settings_post(request: Request, body: PeriodSettingsBody,
                                   db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.period_settings_post(db, user_id, body.model_dump(exclude_unset=True)))

    # ── 生日 /baby/birthday, /baby/birthday_bazi ─

    @router.get("/birthday")
    async def birthday_get(request: Request, db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.birthday_list(db, user_id))

    @router.post("/birthday")
    async def birthday_post(request: Request, body: BirthdayBody,
                            db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.birthday_create(db, user_id, body.model_dump(exclude_unset=True)))

    @router.put("/birthday")
    async def birthday_put(request: Request, body: BirthdayBody,
                           db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.birthday_update(db, user_id, body.model_dump(exclude_unset=True)))

    @router.delete("/birthday")
    async def birthday_delete(request: Request, body: BirthdayBody,
                              db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.birthday_delete(db, user_id, body.model_dump(exclude_unset=True)))

    @router.get("/birthday_bazi")
    async def birthday_bazi_get(request: Request, db: Session = Depends(get_db)):
        uid, err = get_uid(request, required=True)
        if err:
            return err
        user_id = svc.uid_int(uid)
        if user_id is None:
            return _unauthorized("Authentication credentials were not provided.")
        return JSONResponse(svc.birthday_bazi(db, user_id, dict(request.query_params)))

    # ── 访问统计 /baby/access/* ──────────────────

    @router.get("/access/stats")
    async def access_stats_get(request: Request, db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        user_id = svc.uid_int(uid)
        if user_id is None:
            return JSONResponse({"recent_access": [], "hourly_stats": [],
                                 "today_stats": {"total_requests": 0, "avg_duration": 0},
                                 "recent_logs": []})
        return JSONResponse(svc.access_stats(db, user_id))

    @router.get("/access/detail")
    async def access_detail_get(request: Request, db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        user_id = svc.uid_int(uid)
        if user_id is None:
            return JSONResponse({"logs": [], "stats": {"total_count": 0, "avg_duration": 0,
                                                       "max_duration": 0, "min_duration": 0}})
        return JSONResponse(svc.access_detail(db, user_id, request.query_params.get("path")))

    @router.get("/access/detail/{path}")
    async def access_detail_path_get(request: Request, path: str,
                                     db: Session = Depends(get_db)):
        uid, _ = get_uid(request, required=False)
        user_id = svc.uid_int(uid)
        if user_id is None:
            return JSONResponse({"logs": [], "stats": {"total_count": 0, "avg_duration": 0,
                                                       "max_duration": 0, "min_duration": 0}})
        return JSONResponse(svc.access_detail(db, user_id, path))

    return router
