"""海关查验时间换算：开箱到封箱（含复验）时长只认这一份算法。

安排查验、登记结果、安排复验三个环节，以及查验列表、查验详情、
集装箱页面等所有读取入口，都通过本模块换算时长，避免各处各算一套
导致跨零点的查验时长差出一天。

口径：
- 录入时间按原样保留（字符串存储，不就地改写）；
- 跨零点（封箱时间的时钟时刻早于开箱时间、且仍在同一自然日）按次日处理；
- 开/封箱时间缺一项，或结束时间早于开始时间，统一视为「待补录」。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from app.store import store

MODULE = "customs"

OPEN_FIELD = "开箱时间"
CLOSE_FIELD = "封箱时间"
REINSPECT_FIELD = "复验时间"

# 三个环节提交时间时允许写入的字段：对外字段名保持原样。
ACTION_TIME_FIELDS = {
    "安排查验": (OPEN_FIELD,),
    "登记结果": (CLOSE_FIELD,),
    "安排复验": (REINSPECT_FIELD, CLOSE_FIELD),
}

# 迁移与动作回算时落库的内部字段；对外输出时会剥掉下划线前缀。
MINUTES_KEY = "_查验时长分钟"
MISSING_KEY = "_时间待补录"
PENDING_DURATION_TEXT = "待补录"

_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M")


def parse_time(raw: Any) -> datetime | None:
    """把录入的时间字符串解析成时间点；空值或无法识别的格式返回 None。

    只有日期（如 2026-09-01）时按当天 00:00 处理，与原录入展示保持一致。
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.combine(date.fromisoformat(text), datetime.min.time())
    except ValueError:
        return None


def duration_minutes(open_raw: Any, close_raw: Any) -> int | None:
    """开箱到封箱的时长（分钟）；缺时间或先后倒置时返回 None（待补录）。

    跨零点处理：封箱的时钟时刻早于开箱、且两个录入仍落在同一自然日时，
    说明查验跨过了零点，把封箱时间顺延一天，避免直接相减得到负值、
    也避免各入口各用一套日期差口径算出相差一天。
    """
    opened = parse_time(open_raw)
    closed = parse_time(close_raw)
    if opened is None or closed is None:
        return None
    if closed.date() == opened.date() and closed.time() < opened.time():
        closed += timedelta(days=1)
    delta = closed - opened
    if delta < timedelta(0):
        return None
    return int(delta.total_seconds() // 60)


def format_duration(minutes: int | None) -> str:
    """把分钟数格式化成对业务可读的时长文案；None 即「待补录」。"""
    if minutes is None:
        return PENDING_DURATION_TEXT
    days, rem = divmod(minutes, 24 * 60)
    hours, mins = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}天")
    if hours:
        parts.append(f"{hours}小时")
    if mins or not parts:
        parts.append(f"{mins}分钟")
    return "".join(parts)


def _entry_duration_minutes(entry: dict[str, Any]) -> int | None:
    """按当前录入时间重算一票查验的时长，不依赖任何已缓存的值。"""
    return duration_minutes(entry.get(OPEN_FIELD), entry.get(CLOSE_FIELD))


def describe_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """统一的对外投影：剥掉内部字段，并给出各处一致的「查验时长」。

    列表、详情、导出以及其它页面读取同一票查验时都走这里，
    保证同一个入口和详情里读到的时长是同一个数。
    """
    projected = {
        key: value for key, value in entry.items() if not key.startswith("_")
    }
    minutes = _entry_duration_minutes(entry)
    projected["查验时长"] = format_duration(minutes)
    return projected


def describe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [describe_entry(row) for row in rows]


def duration_by_container() -> dict[str, str]:
    """按箱号给出查验时长文案，供集装箱等其它页面取同一份结果。"""
    result: dict[str, str] = {}
    for row in store.rows(MODULE):
        container_no = str(row.get("箱号") or "").strip()
        if container_no:
            result[container_no] = describe_entry(row)["查验时长"]
    return result


def recalculate_entry(entry: dict[str, Any]) -> None:
    """用统一算法回算单票查验，并同步维护内部缓存与待补录标记。

    动作执行和历史数据迁移都调它；录入时间沿用当初的值，不做改写。
    """
    minutes = _entry_duration_minutes(entry)
    entry[MINUTES_KEY] = minutes
    entry[MISSING_KEY] = minutes is None


def backfill_existing() -> int:
    """换算规矩换过之后重算已有查验记录；返回重算条数。

    录入时间沿用当初的值；缺时间或时间倒置的记录按待补录处理。
    """
    count = 0
    for row in store.rows(MODULE):
        recalculate_entry(row)
        count += 1
    return count
