import json
import logging
import base64
import os, uuid
import time
import asyncio
import calendar
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from custom import MyModelViewSet
from .models import BabyInfo, FeedMilk, SleepLog, BabyDiapers, BabyExpense, Temperature, TodoList, BirthdayRecord
from .serializers import BabyInfoSerializer, FeedMilkSerializer, SleepLogSerializer, BabyDiapersSerializer, \
    BabyExpenseSerializer, TemperatureSerializer, TodoListSerializer, BirthdayRecordSerializer
from utils import convert_seconds, convert_string_datetime, convert_string_date
from datetime import datetime, timedelta, date
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned
from django.db.models import Sum
from zoneinfo import ZoneInfo
from decimal import Decimal, getcontext
from kdemo.settings import MEDIA_ROOT

logger = logging.getLogger(__name__)

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
    if y < 1900 or y > 2100:
        return None
    if m < 1 or m > 12:
        return None
    if d < 1:
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
    if solar < _LUNAR_START:
        return None
    if solar.year < 1900 or solar.year > 2100:
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

    d = offset + 1
    return {'lunar_year': y, 'lunar_month': m, 'lunar_day': int(d), 'lunar_is_leap': bool(is_leap)}


def _pad2(v: int | None) -> str:
    if v is None:
        return ''
    return str(int(v)).zfill(2)


def _format_lunar_iso(y: int | None, m: int | None, d: int | None) -> str | None:
    if not y or not m or not d:
        return None
    return f'{int(y)}-{_pad2(int(m))}-{_pad2(int(d))}'


def _calc_age_ym(birth: date | None, today: date) -> str | None:
    if not birth:
        return None
    if today < birth:
        return None

    years = today.year - birth.year
    months = today.month - birth.month
    if today.day < birth.day:
        months -= 1
    if months < 0:
        years -= 1
        months += 12
    years = max(0, years)
    months = max(0, months)
    if years == 0 and months == 0:
        return '0个月'
    if years == 0:
        return f'{months}个月'
    if months == 0:
        return f'{years}岁'
    return f'{years}岁{months}个月'


def _calc_constellation(birth: date | None) -> str | None:
    if not birth:
        return None
    m = birth.month
    d = birth.day
    ranges = [
        (1, 20, '水瓶座'), (2, 19, '双鱼座'), (3, 21, '白羊座'), (4, 20, '金牛座'),
        (5, 21, '双子座'), (6, 22, '巨蟹座'), (7, 23, '狮子座'), (8, 23, '处女座'),
        (9, 23, '天秤座'), (10, 24, '天蝎座'), (11, 23, '射手座'), (12, 22, '摩羯座'),
    ]
    for month, start_day, name in ranges:
        if (m == month and d >= start_day) or (m == month + 1 and d < start_day):
            return name
    if (m == 12 and d >= 22) or (m == 1 and d < 20):
        return '摩羯座'
    return None


def _ensure_birthday_both_calendars(record: BirthdayRecord) -> None:
    if record.solar_date and not (record.lunar_year and record.lunar_month and record.lunar_day):
        lunar = _solar_to_lunar(record.solar_date)
        if lunar:
            record.lunar_year = lunar['lunar_year']
            record.lunar_month = lunar['lunar_month']
            record.lunar_day = lunar['lunar_day']
            record.lunar_is_leap = lunar['lunar_is_leap']
            record.save(update_fields=['lunar_year', 'lunar_month', 'lunar_day', 'lunar_is_leap', 'updated_at'])
        return

    if record.lunar_year and record.lunar_month and record.lunar_day and not record.solar_date:
        solar = _lunar_to_solar(int(record.lunar_year), int(record.lunar_month), int(record.lunar_day), bool(record.lunar_is_leap))
        if solar:
            record.solar_date = solar
            record.save(update_fields=['solar_date', 'updated_at'])


def _calc_next_birthday_date(record: BirthdayRecord, today: date) -> date | None:
    if record.calendar_type == BirthdayRecord.CalendarType.SOLAR:
        if not record.solar_date:
            return None
        m = record.solar_date.month
        d = record.solar_date.day
        y = today.year
        max_day = calendar.monthrange(y, m)[1]
        d2 = min(d, max_day)
        candidate = date(y, m, d2)
        if candidate < today:
            y += 1
            max_day = calendar.monthrange(y, m)[1]
            d2 = min(d, max_day)
            candidate = date(y, m, d2)
        return candidate

    m = record.lunar_month
    d = record.lunar_day
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


def _decorate_birthday(record: BirthdayRecord) -> dict:
    _ensure_birthday_both_calendars(record)
    data = BirthdayRecordSerializer(record).data
    today = date.today()
    next_date = _calc_next_birthday_date(record, today)
    data['next_birthday_date'] = next_date.isoformat() if next_date else None
    data['next_birthday_in_days'] = (next_date - today).days if next_date else None
    birth_solar = record.solar_date
    data['age_text'] = _calc_age_ym(birth_solar, today)
    data['constellation'] = _calc_constellation(birth_solar)
    data['lunar_date_iso'] = _format_lunar_iso(record.lunar_year, record.lunar_month, record.lunar_day)
    return data


def get_temperature(user_id, date, mode):
    if mode == 'week':
        start_date = date - timedelta(days=7)
        objs = Temperature.objects.filter(user=user_id, measure_date__gte=start_date, measure_date__lte=date).order_by('-measure_date')
    else:
        objs = Temperature.objects.filter(user=user_id, measure_date=date)
    serializer = TemperatureSerializer(objs, many=True)
    return serializer.data


class LineChartView(APIView):
    permission_classes = [IsAuthenticated]

    def process_chartData(self, data, type, need_total=False):
        total_count = 0
        xAxisData = []
        actualData = []

        if type == 'milkVolumes':

            xAxis_name = 'feed_time'
            actual_name = 'milk_volume'
            expected_count = 150
        elif type == 'temperature':

            xAxis_name = 'measure_date'
            actual_name = 'temperature'
            expected_count = '36.7'

        elif type == 'babyPants':

            xAxis_name = 'use_date'
            actual_name = 'is_leaked'
            expected_count = False
        else:

            xAxis_name = 'order_time'
            actual_name = 'amount'
            expected_count = 3000

        expectedData = [expected_count] * len(data)
        for item in data:
            xAxisData.append(item[xAxis_name])
            if need_total:
                actual = int(item[actual_name])
                total_count += actual
            else:
                actual = item[actual_name]
            actualData.append(actual)

        return {'xAxisData': xAxisData, 'expectedData': expectedData, 'actualData': actualData}, total_count

    def get(self, request, *args, **kwargs):
        user = request.user
        user_id = user.id
        params = request.query_params
        logger.debug("LineChart params: %s", dict(params))
        # date = params.get("date")
        date_time = datetime.now().strftime('%Y-%m-%d 00:00:00')
        date = datetime.now().date()

        '''
        需要完成奶量数据 两天的
        体温数据,一个月的
        尿不湿 两天的
        花费 一个月的
        '''

        '''
        奶量
        '''
        totalLineChartData = {
            'milkVolumes': {'xAxisData': [], 'expectedData': [], 'actualData': []},
            'temperature': {'xAxisData': [], 'expectedData': [], 'actualData': []},
            'babyPants': {'xAxisData': [], 'expectedData': [], 'actualData': []},
            'purchases': {'xAxisData': [], 'expectedData': [], 'actualData': []},
        }
        queryset = FeedMilk.objects.filter(user=user_id, feed_time__gte=date_time).order_by("feed_time")

        sum_milk = queryset.aggregate(Sum('milk_volume'))

        serializer = FeedMilkSerializer(queryset, many=True)
        result_data = serializer.data
        milkVolumes, milk_total_count = self.process_chartData(data=result_data, type='milkVolumes', need_total=True)
        totalLineChartData['milkVolumes'] = milkVolumes

        '''
        temperature
        '''

        try:
            t = Temperature.objects.get(user=user_id, measure_date=date)
            temperature = t.temperature
        except (ObjectDoesNotExist, MultipleObjectsReturned) as exc:
            logger.error(str(exc))
            temperature = '未测'

        temperature_data = get_temperature(user_id, date, 'week')
        temperature_data.reverse()
        chart_temperature, _ = self.process_chartData(data=temperature_data, type='temperature', need_total=False)
        totalLineChartData['temperature'] = chart_temperature

        '''
        babyPants
        '''

        bp_queryset = BabyDiapers.objects.filter(user=user_id, use_date__gte=date_time).order_by("use_date")
        bp_count = bp_queryset.count()
        serializer = BabyDiapersSerializer(bp_queryset, many=True)
        bp_data = serializer.data
        chart_babyPants, babyPants = self.process_chartData(data=bp_data, type='babyPants', need_total=False)
        totalLineChartData['babyPants'] = chart_babyPants

        response_data = {
            'basicInfo': {'milkVolumes': milk_total_count, 'temperature': temperature, 'babyPants': bp_count},
            'totalLineChartData': totalLineChartData}

        return Response({'code': 200, 'msg': 'ok', 'data': response_data})


class BirthdayView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        qs = BirthdayRecord.objects.filter(user=request.user).order_by('-updated_at', '-id')
        items = [_decorate_birthday(x) for x in qs]
        return Response({'code': 200, 'msg': 'ok', 'data': items})

    def post(self, request, *args, **kwargs):
        payload = request.data or {}
        name = (payload.get('name') or '').strip()
        if not name:
            return Response({'code': 400, 'msg': 'name 必填', 'data': None})

        calendar_type = payload.get('calendar_type') or BirthdayRecord.CalendarType.LUNAR
        if calendar_type not in [BirthdayRecord.CalendarType.LUNAR, BirthdayRecord.CalendarType.SOLAR]:
            return Response({'code': 400, 'msg': 'calendar_type 参数错误', 'data': None})

        relation = payload.get('relation')
        data = {
            'user': request.user,
            'name': name,
            'relation': relation,
            'calendar_type': calendar_type
        }

        if calendar_type == BirthdayRecord.CalendarType.SOLAR:
            solar_date = payload.get('solar_date')
            if not solar_date:
                return Response({'code': 400, 'msg': 'solar_date 必填', 'data': None})
            try:
                solar = date.fromisoformat(solar_date)
                data['solar_date'] = solar
            except Exception:
                return Response({'code': 400, 'msg': 'solar_date 格式错误', 'data': None})
            lunar = _solar_to_lunar(solar)
            if lunar:
                data.update(lunar)
        else:
            try:
                data['lunar_year'] = int(payload.get('lunar_year'))
            except Exception:
                return Response({'code': 400, 'msg': 'lunar_year 必填', 'data': None})
            try:
                data['lunar_month'] = int(payload.get('lunar_month'))
                data['lunar_day'] = int(payload.get('lunar_day'))
            except Exception:
                return Response({'code': 400, 'msg': 'lunar_month/lunar_day 必填', 'data': None})
            data['lunar_is_leap'] = bool(payload.get('lunar_is_leap'))
            solar = _lunar_to_solar(int(data['lunar_year']), int(data['lunar_month']), int(data['lunar_day']), bool(data['lunar_is_leap']))
            if solar:
                data['solar_date'] = solar

        ok, birth_hour = _parse_birth_hour(payload.get('birth_hour'))
        if not ok:
            return Response({'code': 400, 'msg': 'birth_hour 参数错误', 'data': None})
        data['birth_hour'] = birth_hour

        ok, gender = _parse_gender(payload.get('gender'))
        if not ok:
            return Response({'code': 400, 'msg': 'gender 参数错误', 'data': None})
        data['gender'] = gender

        record = BirthdayRecord.objects.create(**data)
        return Response({'code': 200, 'msg': 'ok', 'data': _decorate_birthday(record)})

    def put(self, request, *args, **kwargs):
        payload = request.data or {}
        rid = payload.get('id')
        if not rid:
            return Response({'code': 400, 'msg': 'id 必填', 'data': None})
        record = BirthdayRecord.objects.filter(user=request.user, id=rid).first()
        if not record:
            return Response({'code': 404, 'msg': '记录不存在', 'data': None})

        if 'name' in payload:
            record.name = (payload.get('name') or '').strip()
        if 'relation' in payload:
            record.relation = payload.get('relation')
        if 'calendar_type' in payload:
            ct = payload.get('calendar_type')
            if ct not in [BirthdayRecord.CalendarType.LUNAR, BirthdayRecord.CalendarType.SOLAR]:
                return Response({'code': 400, 'msg': 'calendar_type 参数错误', 'data': None})
            record.calendar_type = ct

        if record.calendar_type == BirthdayRecord.CalendarType.SOLAR:
            if 'solar_date' in payload:
                solar_date = payload.get('solar_date')
                if not solar_date:
                    record.solar_date = None
                else:
                    try:
                        record.solar_date = date.fromisoformat(solar_date)
                    except Exception:
                        return Response({'code': 400, 'msg': 'solar_date 格式错误', 'data': None})
            if record.solar_date:
                lunar = _solar_to_lunar(record.solar_date)
                if lunar:
                    record.lunar_year = lunar['lunar_year']
                    record.lunar_month = lunar['lunar_month']
                    record.lunar_day = lunar['lunar_day']
                    record.lunar_is_leap = lunar['lunar_is_leap']
        else:
            if 'lunar_year' in payload:
                try:
                    record.lunar_year = int(payload.get('lunar_year'))
                except Exception:
                    return Response({'code': 400, 'msg': 'lunar_year 参数错误', 'data': None})
            if 'lunar_month' in payload:
                record.lunar_month = int(payload.get('lunar_month'))
            if 'lunar_day' in payload:
                record.lunar_day = int(payload.get('lunar_day'))
            if 'lunar_is_leap' in payload:
                record.lunar_is_leap = bool(payload.get('lunar_is_leap'))
            if record.lunar_year and record.lunar_month and record.lunar_day:
                solar = _lunar_to_solar(int(record.lunar_year), int(record.lunar_month), int(record.lunar_day), bool(record.lunar_is_leap))
                if solar:
                    record.solar_date = solar

        if 'birth_hour' in payload:
            ok, birth_hour = _parse_birth_hour(payload.get('birth_hour'))
            if not ok:
                return Response({'code': 400, 'msg': 'birth_hour 参数错误', 'data': None})
            record.birth_hour = birth_hour

        if 'gender' in payload:
            ok, gender = _parse_gender(payload.get('gender'))
            if not ok:
                return Response({'code': 400, 'msg': 'gender 参数错误', 'data': None})
            record.gender = gender

        record.save()
        return Response({'code': 200, 'msg': 'ok', 'data': _decorate_birthday(record)})

    def delete(self, request, *args, **kwargs):
        payload = request.data or {}
        rid = payload.get('id')
        if not rid:
            return Response({'code': 400, 'msg': 'id 必填', 'data': None})
        record = BirthdayRecord.objects.filter(user=request.user, id=rid).first()
        if not record:
            return Response({'code': 404, 'msg': '记录不存在', 'data': None})
        record.delete()
        return Response({'code': 200, 'msg': 'ok', 'data': None})


# ──────────────────────────────────────────────
# 八字 / 五行
# ──────────────────────────────────────────────

_GAN_WUXING = {
    '甲': '木', '乙': '木', '丙': '火', '丁': '火', '戊': '土',
    '己': '土', '庚': '金', '辛': '金', '壬': '水', '癸': '水'
}
_ZHI_WUXING = {
    '子': '水', '丑': '土', '寅': '木', '卯': '木', '辰': '土', '巳': '火',
    '午': '火', '未': '土', '申': '金', '酉': '金', '戌': '土', '亥': '水'
}
_WUXING_ORDER = ['金', '木', '水', '火', '土']

_GAN_YINYANG = {
    '甲': '阳', '乙': '阴', '丙': '阳', '丁': '阴', '戊': '阳',
    '己': '阴', '庚': '阳', '辛': '阴', '壬': '阳', '癸': '阴'
}
_ZHI_YINYANG = {
    '子': '阳', '丑': '阴', '寅': '阳', '卯': '阴', '辰': '阳', '巳': '阴',
    '午': '阳', '未': '阴', '申': '阳', '酉': '阴', '戌': '阳', '亥': '阴'
}
# 月支藏干本气十神 → 格局名（比肩/劫财为特殊格局：建禄/月刃）
_SHISHEN_GEJU = {
    '比肩': '建禄格', '劫财': '月刃格',
    '食神': '食神格', '伤官': '伤官格',
    '偏财': '偏财格', '正财': '正财格',
    '七杀': '七杀格', '正官': '正官格',
    '偏印': '偏印格', '正印': '正印格'
}


def _parse_birth_hour(value):
    """解析出生时辰(0-23整点)，允许 None/空 表示未填。返回 (ok, hour|None)。"""
    if value in [None, '']:
        return True, None
    try:
        h = int(value)
    except Exception:
        return False, None
    if h < 0 or h > 23:
        return False, None
    return True, h


def _parse_gender(value):
    """解析性别(1=男 0=女)，允许 None/空 表示未填。返回 (ok, gender|None)。"""
    if value in [None, '']:
        return True, None
    try:
        g = int(value)
    except Exception:
        return False, None
    if g not in (0, 1):
        return False, None
    return True, g


def _build_bazi_payload(record: BirthdayRecord, hour=None, sect=2) -> dict:
    from lunar_python import Solar

    solar_dt = record.solar_date
    h = int(hour) if hour is not None else None
    if h is not None and (h < 0 or h > 23):
        h = None
    solar = Solar.fromYmdHms(solar_dt.year, solar_dt.month, solar_dt.day, h if h is not None else 0, 0, 0)
    lunar = solar.getLunar()
    ec = lunar.getEightChar()
    # 子时换日流派: 1=晚子时(23:00起)日柱算明天 2=晚子时日柱算当天(默认)
    ec.setSect(sect)

    def _pillar(label, key, gan, zhi, nayin, shishen_gan, hide_gan, shishen_zhi, dishi):
        return {
            'key': key,
            'label': label,
            'ganzhi': f'{gan}{zhi}',
            'gan': gan,
            'zhi': zhi,
            'gan_wuxing': _GAN_WUXING.get(gan, ''),
            'zhi_wuxing': _ZHI_WUXING.get(zhi, ''),
            'gan_yinyang': _GAN_YINYANG.get(gan, ''),
            'zhi_yinyang': _ZHI_YINYANG.get(zhi, ''),
            'gan_shishen': shishen_gan,
            'zhi_hide_gan': hide_gan,
            'zhi_shishen_benqi': shishen_zhi,
            'dishi': dishi,
            'nayin': nayin
        }

    pillars = [
        _pillar('年柱', 'year', ec.getYearGan(), ec.getYearZhi(), ec.getYearNaYin(),
                ec.getYearShiShenGan(), ''.join(ec.getYearHideGan()), (ec.getYearShiShenZhi() or [''])[0], ec.getYearDiShi()),
        _pillar('月柱', 'month', ec.getMonthGan(), ec.getMonthZhi(), ec.getMonthNaYin(),
                ec.getMonthShiShenGan(), ''.join(ec.getMonthHideGan()), (ec.getMonthShiShenZhi() or [''])[0], ec.getMonthDiShi()),
        _pillar('日柱', 'day', ec.getDayGan(), ec.getDayZhi(), ec.getDayNaYin(),
                ec.getDayShiShenGan(), ''.join(ec.getDayHideGan()), (ec.getDayShiShenZhi() or [''])[0], ec.getDayDiShi())
    ]
    if h is not None:
        pillars.append(_pillar('时柱', 'time', ec.getTimeGan(), ec.getTimeZhi(), ec.getTimeNaYin(),
                               ec.getTimeShiShenGan(), ''.join(ec.getTimeHideGan()), (ec.getTimeShiShenZhi() or [''])[0], ec.getTimeDiShi()))
    else:
        pillars.append({'key': 'time', 'label': '时柱', 'ganzhi': None, 'gan': None, 'zhi': None,
                        'gan_wuxing': None, 'zhi_wuxing': None, 'gan_yinyang': None, 'zhi_yinyang': None,
                        'gan_shishen': None, 'zhi_hide_gan': None, 'zhi_shishen_benqi': None,
                        'dishi': None, 'nayin': None})

    count = {k: 0 for k in _WUXING_ORDER}
    for p in pillars:
        for wx in (p.get('gan_wuxing'), p.get('zhi_wuxing')):
            if wx in count:
                count[wx] += 1

    missing = [k for k in _WUXING_ORDER if count[k] == 0]
    strongest = max(_WUXING_ORDER, key=lambda k: count[k]) if any(count.values()) else None

    leap_txt = '闰' if record.lunar_is_leap else ''
    lunar_text = f"{lunar.getYearInChinese()}年{leap_txt}{lunar.getMonthInChinese()}月{lunar.getDayInChinese()}"

    year_nayin = ec.getYearNaYin()
    day_gan = ec.getDayGan()
    # 格局：以月支藏干本气十神定格
    month_benqi_shishen = (ec.getMonthShiShenZhi() or [''])[0]

    # 大运流年：需要性别(阳男阴女顺排、阴男阳女逆排)
    yun_info = None
    if record.gender in (0, 1):
        yun = ec.getYun(1 if record.gender == 1 else 0)
        dayuns = []
        for dy in yun.getDaYun():
            liunian = [
                {'year': x.getYear(), 'age': x.getAge(), 'ganzhi': x.getGanZhi()}
                for x in (dy.getLiuNian() or [])
            ]
            dayuns.append({
                'ganzhi': dy.getGanZhi() or None,  # 第一步为起运前，无干支
                'start_year': dy.getStartYear(),
                'end_year': dy.getEndYear(),
                'start_age': dy.getStartAge(),
                'end_age': dy.getEndAge(),
                'liunian': liunian
            })
        start_solar = yun.getStartSolar()
        yun_info = {
            'gender': record.gender,
            'start_text': f"{yun.getStartYear()}年{yun.getStartMonth()}个月{yun.getStartDay()}天",
            'start_solar': start_solar.toYmd() if start_solar else None,
            'dayuns': dayuns
        }

    return {
        'name': record.name,
        'solar_date': solar_dt.isoformat(),
        'lunar_text': lunar_text,
        'lunar_is_leap': bool(record.lunar_is_leap),
        'year_ganzhi': ec.getYearGan() + ec.getYearZhi(),
        'zodiac': lunar.getYearShengXiao(),
        'year_nayin': year_nayin,
        'life_element': year_nayin[-1] if year_nayin else None,
        'hour': h,
        'pillars': pillars,
        'wuxing_count': count,
        'missing_wuxing': missing,
        'strongest_wuxing': strongest,
        'count_basis': 8 if h is not None else 6,
        'geju': _SHISHEN_GEJU.get(month_benqi_shishen),
        'geju_shishen': month_benqi_shishen,
        'taiyuan': ec.getTaiYuan(),
        'minggong': ec.getMingGong(),
        'shengong': ec.getShenGong(),
        'xunkong': ''.join(ec.getDayXunKong()),
        'rizhu': {
            'gan': day_gan,
            'yinyang': _GAN_YINYANG.get(day_gan, ''),
            'wuxing': _GAN_WUXING.get(day_gan, ''),
            'nayin': ec.getDayNaYin()
        },
        'sect': sect,
        'yun': yun_info
    }


class BirthdayBaziView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        payload = request.query_params
        rid = payload.get('id')
        if not rid:
            return Response({'code': 400, 'msg': 'id 必填', 'data': None})
        record = BirthdayRecord.objects.filter(user=request.user, id=rid).first()
        if not record:
            return Response({'code': 404, 'msg': '记录不存在', 'data': None})

        _ensure_birthday_both_calendars(record)
        if not record.solar_date:
            return Response({'code': 400, 'msg': '生日日期缺失，无法测算八字', 'data': None})

        hour = record.birth_hour
        if payload.get('hour') not in [None, '']:
            try:
                hour = int(payload.get('hour'))
            except Exception:
                return Response({'code': 400, 'msg': 'hour 参数错误', 'data': None})

        # 子时换日流派: 1=晚子时(23:00起)算明天 2=晚子时算当天(默认)
        sect = 2
        if payload.get('sect') not in [None, '']:
            try:
                sect = int(payload.get('sect'))
            except Exception:
                return Response({'code': 400, 'msg': 'sect 参数错误', 'data': None})
            if sect not in (1, 2):
                return Response({'code': 400, 'msg': 'sect 参数错误', 'data': None})

        try:
            data = _build_bazi_payload(record, hour=hour, sect=sect)
        except Exception as e:
            logger.exception('bazi calc failed: %s', e)
            return Response({'code': 500, 'msg': '八字测算失败，请稍后重试', 'data': None})
        return Response({'code': 200, 'msg': 'ok', 'data': data})
