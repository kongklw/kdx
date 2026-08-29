"""
宝宝数据访问层 (Repository)

职责：
- 封装 Assistant 全部工具的数据读写，SQLAlchemy 同步会话
- 严格按 user_id 隔离（数据级鉴权，见 example/auth.py 第三层）
- 所有方法为同步实现，调用方 (graph 节点) 用 asyncio.to_thread 包裹避免阻塞事件循环
"""

from datetime import date, datetime, timedelta
from typing import Optional, List, Dict, Any

from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session

from .db_models import (
    BabyInfoRow, FeedMilkRow, SleepLogRow, BabyDiapersRow, TemperatureRow,
    BabyExpenseRow, GrowthRecordRow, BabyVaccineRecordRow, BirthdayRecordRow,
)


def _row_to_dict(row, exclude: tuple = ()) -> Dict[str, Any]:
    out = {}
    for c in row.__table__.columns:
        if c.name in exclude:
            continue
        v = getattr(row, c.name)
        if isinstance(v, (date, datetime)):
            v = v.isoformat()
        elif hasattr(v, "to_eng_string"):  # Decimal
            v = float(v)
        out[c.name] = v
    return out


class BabyDataRepository:
    def __init__(self, session: Session):
        self._s = session

    # ── 宝宝信息 ────────────────────────────────

    def get_baby_info(self, user_id: int) -> Optional[Dict[str, Any]]:
        row = self._s.execute(
            select(BabyInfoRow).where(BabyInfoRow.user_id == user_id)
        ).scalars().first()
        return _row_to_dict(row) if row else None

    # ── 喂奶 ────────────────────────────────────

    def query_feed_milk(self, user_id: int, start: datetime, end: datetime) -> Dict[str, Any]:
        rows = self._s.execute(
            select(FeedMilkRow).where(
                FeedMilkRow.user_id == user_id,
                FeedMilkRow.feed_time >= start,
                FeedMilkRow.feed_time <= end,
            ).order_by(FeedMilkRow.feed_time)
        ).scalars().all()
        records = [_row_to_dict(r) for r in rows]
        return {
            "total_volume_ml": sum(r["milk_volume"] for r in records),
            "count": len(records),
            "records": records,
        }

    def add_feed_milk(self, user_id: int, feed_time: datetime, milk_volume: int,
                      feed_type: str = "bottle", note: str = "") -> Dict[str, Any]:
        row = FeedMilkRow(
            user_id=user_id, feed_time=feed_time, milk_volume=int(milk_volume),
            feed_type=feed_type or "bottle", note=note or None,
        )
        self._s.add(row)
        self._s.commit()
        return _row_to_dict(row)

    # ── 体温 ────────────────────────────────────

    def query_temperature(self, user_id: int, day: date) -> List[Dict[str, Any]]:
        rows = self._s.execute(
            select(TemperatureRow).where(
                TemperatureRow.user_id == user_id,
                TemperatureRow.measure_date == day,
            )
        ).scalars().all()
        return [_row_to_dict(r) for r in rows]

    def add_temperature(self, user_id: int, day: date, temperature: float,
                        status: str = "") -> Dict[str, Any]:
        row = self._s.execute(
            select(TemperatureRow).where(
                TemperatureRow.user_id == user_id,
                TemperatureRow.measure_date == day,
            )
        ).scalars().first()
        if row:  # 当天唯一，更新
            row.temperature = str(temperature)
            row.status = status or None
        else:
            row = TemperatureRow(user_id=user_id, measure_date=day,
                                 temperature=str(temperature), status=status or None)
            self._s.add(row)
        self._s.commit()
        return _row_to_dict(row)

    # ── 睡眠 ────────────────────────────────────

    def query_sleep(self, user_id: int, start: datetime, end: datetime) -> Dict[str, Any]:
        rows = self._s.execute(
            select(SleepLogRow).where(
                SleepLogRow.user_id == user_id,
                SleepLogRow.sleep_time >= start,
                SleepLogRow.sleep_time <= end,
            ).order_by(SleepLogRow.sleep_time)
        ).scalars().all()
        records = [_row_to_dict(r) for r in rows]
        total_minutes = sum((r.get("duration") or 0) for r in records) // 60
        return {"count": len(records), "total_duration_minutes": total_minutes, "records": records}

    def add_sleep(self, user_id: int, sleep_time: datetime, status: str,
                  duration_minutes: int = 0, describe: str = "") -> Dict[str, Any]:
        row = SleepLogRow(
            user_id=user_id, sleep_time=sleep_time, status=status,
            duration=int(duration_minutes) * 60 if duration_minutes else None,
            describe=describe or None,
        )
        self._s.add(row)
        self._s.commit()
        return _row_to_dict(row)

    # ── 尿不湿 ──────────────────────────────────

    def query_diapers(self, user_id: int, start: datetime, end: datetime) -> Dict[str, Any]:
        rows = self._s.execute(
            select(BabyDiapersRow).where(
                BabyDiapersRow.user_id == user_id,
                BabyDiapersRow.use_date >= start,
                BabyDiapersRow.use_date <= end,
            ).order_by(BabyDiapersRow.use_date)
        ).scalars().all()
        records = [_row_to_dict(r) for r in rows]
        by_type: Dict[str, int] = {}
        for r in records:
            t = r.get("tabActiveName") or "unknown"
            by_type[t] = by_type.get(t, 0) + 1
        return {"count": len(records), "by_type": by_type, "records": records}

    def add_diaper(self, user_id: int, use_date: datetime, diaper_type: str = "peeing",
                   brand: str = "", describe: str = "") -> Dict[str, Any]:
        row = BabyDiapersRow(
            user_id=user_id, use_date=use_date, brand=brand or "未记录",
            tabActiveName=diaper_type or "peeing", describe=describe or None,
        )
        self._s.add(row)
        self._s.commit()
        return _row_to_dict(row)

    # ── 花费 ────────────────────────────────────

    def query_expense(self, user_id: int, start: datetime, end: datetime) -> Dict[str, Any]:
        rows = self._s.execute(
            select(BabyExpenseRow).where(
                BabyExpenseRow.user_id == user_id,
                BabyExpenseRow.order_time >= start,
                BabyExpenseRow.order_time <= end,
            ).order_by(desc(BabyExpenseRow.order_time))
        ).scalars().all()
        records = [_row_to_dict(r) for r in rows]
        total = sum(float(r["amount"]) for r in records)
        by_tag: Dict[str, float] = {}
        for r in records:
            t = r.get("tag") or "未分类"
            by_tag[t] = round(by_tag.get(t, 0) + float(r["amount"]), 2)
        return {"total_amount": round(total, 2), "count": len(records),
                "by_tag": by_tag, "records": records[:20]}

    def add_expense(self, user_id: int, order_time: datetime, name: str,
                    amount: float, tag: str = "") -> Dict[str, Any]:
        row = BabyExpenseRow(
            user_id=user_id, order_time=order_time, name=name,
            amount=round(float(amount), 2), tag=tag or None,
        )
        self._s.add(row)
        self._s.commit()
        return _row_to_dict(row)

    # ── 成长(身高体重) ──────────────────────────

    def query_growth(self, user_id: int, limit: int = 5) -> List[Dict[str, Any]]:
        rows = self._s.execute(
            select(GrowthRecordRow).where(GrowthRecordRow.user_id == user_id)
            .order_by(desc(GrowthRecordRow.measure_date)).limit(limit)
        ).scalars().all()
        return [_row_to_dict(r) for r in rows]

    def add_growth(self, user_id: int, measure_date: date, height_cm: float = None,
                   weight_kg: float = None, head_circumference_cm: float = None) -> Dict[str, Any]:
        row = GrowthRecordRow(
            user_id=user_id, measure_date=measure_date,
            height_cm=height_cm, weight_kg=weight_kg,
            head_circumference_cm=head_circumference_cm,
        )
        self._s.add(row)
        self._s.commit()
        return _row_to_dict(row)

    # ── 疫苗 ────────────────────────────────────

    def query_vaccines(self, user_id: int, only_pending: bool = False) -> List[Dict[str, Any]]:
        stmt = select(BabyVaccineRecordRow).where(BabyVaccineRecordRow.user_id == user_id)
        if only_pending:
            stmt = stmt.where(BabyVaccineRecordRow.done == 0)
        stmt = stmt.order_by(BabyVaccineRecordRow.recommend_date)
        rows = self._s.execute(stmt).scalars().all()
        return [_row_to_dict(r) for r in rows]

    def mark_vaccine_done(self, user_id: int, vaccine_key: str,
                          actual_date: date) -> Optional[Dict[str, Any]]:
        row = self._s.execute(
            select(BabyVaccineRecordRow).where(
                BabyVaccineRecordRow.user_id == user_id,
                BabyVaccineRecordRow.vaccine_key == vaccine_key,
                BabyVaccineRecordRow.done == 0,
            ).order_by(BabyVaccineRecordRow.recommend_date)
        ).scalars().first()
        if not row:
            return None
        row.done = 1
        row.actual_date = actual_date
        self._s.commit()
        return _row_to_dict(row)

    # ── 生日 ────────────────────────────────────

    def query_birthdays(self, user_id: int, days: int = 60) -> List[Dict[str, Any]]:
        rows = self._s.execute(
            select(BirthdayRecordRow).where(BirthdayRecordRow.user_id == user_id)
        ).scalars().all()
        today = date.today()
        result = []
        for r in rows:
            if not r.solar_date:
                continue
            next_date = r.solar_date.replace(year=today.year)
            if next_date < today:
                try:
                    next_date = r.solar_date.replace(year=today.year + 1)
                except ValueError:  # 2/29
                    next_date = date(today.year + 1, 3, 1)
            delta = (next_date - today).days
            if delta <= days:
                d = _row_to_dict(r)
                d["days_until"] = delta
                d["next_date"] = next_date.isoformat()
                result.append(d)
        result.sort(key=lambda x: x["days_until"])
        return result
