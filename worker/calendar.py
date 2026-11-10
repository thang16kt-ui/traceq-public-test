from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def value(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def next_run_at(schedule, now: datetime) -> datetime:
    """First valid configured wall-clock run strictly after now (Monday=0).

    A nonexistent DST wall time is skipped. On an ambiguous DST wall time,
    the first occurrence is selected once; no duplicate run in the fold.
    """
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    zone = ZoneInfo(value(schedule, "timezone", "Asia/Ho_Chi_Minh"))
    local_time = value(schedule, "local_time", "17:00")
    hour, minute = map(int, local_time.split(":"))
    if not 0 <= hour < 24 or not 0 <= minute < 60:
        raise ValueError("local_time must be HH:MM")
    days = set(value(schedule, "days_of_week", list(range(7))))
    if not days or not days <= set(range(7)):
        raise ValueError("days_of_week must contain Monday=0 through Sunday=6")
    today = now.astimezone(zone).date()
    for delta in range(15):
        day = today + timedelta(days=delta)
        if day.weekday() not in days:
            continue
        wall = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone, fold=0)
        utc = wall.astimezone(timezone.utc)
        if utc.astimezone(zone).replace(tzinfo=None) != wall.replace(tzinfo=None):
            continue
        if utc > now:
            return utc
    raise ValueError("no valid next run in two weeks")


def initial_period_start(schedule, scheduled_at: datetime) -> datetime:
    zone = ZoneInfo(value(schedule, "timezone", "Asia/Ho_Chi_Minh"))
    day = scheduled_at.astimezone(zone).date()
    if value(schedule, "period_rule", "previous_day") == "previous_day":
        day -= timedelta(days=1)
    return datetime(day.year, day.month, day.day, tzinfo=zone).astimezone(timezone.utc)


def period_end(schedule, scheduled_at: datetime) -> datetime:
    if value(schedule, "period_rule", "previous_day") == "day_until_now":
        return scheduled_at
    zone = ZoneInfo(value(schedule, "timezone", "Asia/Ho_Chi_Minh"))
    day = scheduled_at.astimezone(zone).date()
    return datetime(day.year, day.month, day.day, tzinfo=zone).astimezone(timezone.utc)
