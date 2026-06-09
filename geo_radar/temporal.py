"""时间归一化与生效状态判断（§6.7）。含周期性（季节性）公告。时区按 Asia/Shanghai 处理。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

NOT_STARTED = "NOT_STARTED"
ACTIVE = "ACTIVE"
EXPIRED = "EXPIRED"
LONG_TERM = "LONG_TERM"
INACTIVE = "INACTIVE"   # 周期性公告，当前不在生效窗口
UNKNOWN = "UNKNOWN"


@dataclass
class Validity:
    status: str
    basis: str
    active: bool  # 当前时刻是否生效


from datetime import timezone, timedelta
CST = timezone(timedelta(hours=8))

def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CST)
    return dt


def _in_md_window(now: datetime, start_md: str, end_md: str) -> bool:
    """now 的 (月,日) 是否落在 [start_md, end_md]，支持跨年窗口（如 11-15~02-15）。"""
    sm, sd = (int(x) for x in start_md.split("-"))
    em, ed = (int(x) for x in end_md.split("-"))
    cur, start, end = (now.month, now.day), (sm, sd), (em, ed)
    if start <= end:
        return start <= cur <= end
    return cur >= start or cur <= end


def evaluate(announcement: dict, now: datetime) -> Validity:
    time = announcement.get("time") or {}
    mode = time.get("mode")

    if mode == "recurring_seasonal":
        for w in time.get("windows", []):
            if _in_md_window(now, w["start"], w["end"]):
                return Validity(ACTIVE, f"周期性公告，当前在窗口 {w['start']}~{w['end']} 内", True)
        return Validity(INACTIVE, "周期性公告，当前不在任何生效窗口内", False)

    if mode == "long_term":
        return Validity(LONG_TERM, "长期管制，无明确结束时间", True)

    if mode == "single":
        start, end = _parse(time.get("start")), _parse(time.get("end"))
        if start is None and end is None:
            return Validity(UNKNOWN, "缺少起止时间", False)
        if start and now < start:
            return Validity(NOT_STARTED, f"早于开始时间 {start.isoformat()}", False)
        if end and now > end:
            return Validity(EXPIRED, f"晚于结束时间 {end.isoformat()}", False)
        return Validity(ACTIVE, "当前处于管控时段内", True)

    return Validity(UNKNOWN, "时间表达缺失或无法解析", False)


def hits_time(announcement: dict, when: datetime) -> bool:
    """查询时间是否命中该公告的生效窗口。"""
    return evaluate(announcement, when).active
