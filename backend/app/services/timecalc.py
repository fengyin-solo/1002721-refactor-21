"""时间换算的唯一来源：本地时段解析与查验时长计算都收在这里。

历史上安排查验按本地时段算一次，登记结果、安排复验又各按一套口径（其中一处置换过
UTC、按 UTC 日期做差），查验一旦跨过零点，时长就会平白多出或少掉一天。现在三个环节、
列表/详情/导出以及其他页面都只调用本模块，保证同一票查验在各处读到的时长完全一致。

口径说明：
- 业务时间一律视为「本地时段」（UTC+8）。不带时区的时间字符串直接按本地墙钟解析；
  带时区的先换算到本地，再参与计算，避免不同入口写法不一时跨零点算出差一天。
- 时长由「封箱时间 - 开箱时间」按本地墙钟直接相减得到，单位分钟；不再按日期做差，
  因此 23:50 → 次日 00:10 得到 20 分钟，而不是 1 天。
- 缺开箱或封箱时间、时间无法解析、或封箱早于开箱时，时长无法确定，统一按「待补录」
  处理（时长分钟数取 ``None``），由调用方决定展示文案。
- 本模块只做换算，不改写任何已录入的时间值；换算规则以后再调整，也只需改这一处，
  读取时自然按新规则重算全部历史记录。
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

# 本地时段固定为东八区：时间换算只认这一个基准，不再各处各写一套。
LOCAL_TZ = timezone(timedelta(hours=8))

# 支持的录入格式：日期、本地日期时间，以及带时区偏移的日期时间。
_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d")
_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
)

# 缺时间或无法换算时对外统一的状态文案（对外字段名仍由调用方持有）。
PENDING_DURATION_TEXT = "待补录"


class TimeParseError(ValueError):
    """时间值无法按本地时段口径解析。"""


def parse_local_datetime(value: Any) -> datetime | None:
    """把任意入口录入的时间值解析成本地时段（UTC+8）的「朴素墙钟」。

    返回 naive datetime（已归一到本地墙钟），这样后续相减就是本地时段的直接差值，
    跨零点也不会被时区或 UTC 日期切走一天。``None``/空串返回 ``None``；无法解析时抛
    :class:`TimeParseError`，交由调用方按「待补录」处理。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    else:
        text = str(value).strip()
        if not text:
            return None
        parsed = _parse_text(text)

    if parsed.tzinfo is not None:
        # 带时区的时间先落回本地墙钟，再丢掉 tzinfo，保证后续一律按本地时段相减。
        return parsed.astimezone(LOCAL_TZ).replace(tzinfo=None)
    return parsed


def _parse_text(text: str) -> datetime:
    # 末尾的 Z 表示 UTC：归一成 +00:00 后交给 fromisoformat。
    candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        pass
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise TimeParseError(f"无法按本地时段解析时间值：{text!r}")


def duration_minutes(start_value: Any, end_value: Any) -> int | None:
    """按本地时段口径计算两个时间点之间的时长（分钟，向上取整到整分钟）。

    三个环节共用这一个算法：开箱、登记结果、安排复验给出的时间最终都走到这里。
    任一时间缺失或不可解析、或结束早于开始时返回 ``None``，表示「待补录」。
    """
    start = parse_local_datetime(start_value)
    end = parse_local_datetime(end_value)
    if start is None or end is None:
        return None
    delta_seconds = (end - start).total_seconds()
    if delta_seconds < 0:
        return None
    # 不满一分钟按一分钟计，避免秒级误差在不同入口被四舍五入成不同结果。
    if delta_seconds == 0:
        return 0
    return math.ceil(delta_seconds / 60)


def format_duration(minutes: int | None) -> str:
    """把统一的分钟时长渲染成各处一致的展示文案；``None`` 即「待补录」。"""
    if minutes is None:
        return PENDING_DURATION_TEXT
    hours, remain = divmod(minutes, 60)
    if hours and remain:
        return f"{hours}小时{remain}分钟"
    if hours:
        return f"{hours}小时"
    return f"{remain}分钟"


def inspection_duration(entry: dict[str, Any]) -> int | None:
    """从查验记录上读取开箱/封箱时间并换算时长。

    只依赖最初录入的两个时间值，本身不做任何写操作；换算规则调整后，历史记录在读取
    时即按新规则重算，不需要数据迁移。
    """
    return duration_minutes(entry.get("开箱时间"), entry.get("封箱时间"))
