"""海关查验业务规则：状态流转、字段校验与筛选口径都收在这里。

时间换算不在这里各写一套：安排查验、登记结果、安排复验以及任何页面读到的查验时长，
全部取自 :mod:`app.services.timecalc`，保证同一票查验跨零点时各处算出的时长一致。
"""
from __future__ import annotations

from typing import Any

from app.services import timecalc
from app.services.timecalc import PENDING_DURATION_TEXT
from app.store import store

MODULE = "customs"
REQUIRED_FIELDS = ["查验编号", "箱号", "查验类型"]
STATUS_ORDER = ["待查验", "查验中", "已放行", "待复验"]
ACTION_RULES = {"安排查验": "查验中", "登记结果": "已放行", "安排复验": "待复验"}
NEGATIVE_ACTIONS = []

# 每个环节登记的时间字段：三个动作共用 timecalc 里同一套换算口径。
ACTION_TIME_FIELD = {
    "安排查验": "开箱时间",
    "登记结果": "封箱时间",
    "安排复验": "复验时间",
}

# 对外只读字段：列表、详情、导出、其他页面都带这一份时长，值由开箱/封箱时间现算，
# 不入库、不缓存，所以换算规则调整后历史记录自动按新口径重算。
DURATION_FIELD = "查验时长"


def _read_action_time(action: str, values: dict[str, Any]) -> Any:
    """从动作入参里取出本环节登记的时间；允许专用字段，也允许统一的「时间」。"""
    field = ACTION_TIME_FIELD[action]
    if values.get(field) not in (None, ""):
        return values.get(field)
    return values.get("时间")


class CustomsService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("查验编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        items = [self._with_duration(row) for row in rows[start:start + size]]
        return items, total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._with_duration(entry) if entry is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        # 创建时允许一并带上级别、结果等展示字段，但时间只在三个环节里登记。
        for field in ("查验级别", "查验结果", "开箱时间", "封箱时间", "复验时间"):
            if values.get(field) not in (None, ""):
                entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return self._with_duration(entry), []

    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"查验记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于海关查验可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"

        values = values or {}
        time_field = ACTION_TIME_FIELD[action]
        raw_time = _read_action_time(action, values)

        # 同一票查验同一环节重复登记只认第一回：时间沿用最初录入的值，不覆盖、不重算。
        if entry.get(time_field) not in (None, ""):
            return self._with_duration(entry), (
                f"{action}的时间已登记（{entry.get(time_field)}），重复登记只认第一回，沿用首次录入"
            )

        if raw_time in (None, ""):
            # 缺时间不拦流程：先流转，时长按待补录处理，等补录后再换算。
            entry["status"] = target
            entry["pending"] = target != STATUS_ORDER[-1]
            return self._with_duration(entry), f"查验记录已{action}，未登记{time_field}，时长按待补录处理"

        try:
            parsed = timecalc.parse_local_datetime(raw_time)
        except timecalc.TimeParseError:
            return None, f"{time_field}「{raw_time}」无法识别，请按 2026-09-01 23:50 这样的本地时间填写"
        # 入库的仍是当初录入的原始值（这里归一为解析出的本地墙钟文本），换算只在读取时做。
        entry[time_field] = parsed.strftime("%Y-%m-%d %H:%M:%S")
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return self._with_duration(entry), f"查验记录已{action}"

    # -- 时长读取：所有出口共用这一份 -------------------------------------

    @staticmethod
    def _with_duration(entry: dict[str, Any]) -> dict[str, Any]:
        """给记录补上对外只读的「查验时长」，值永远来自 timecalc 的同一套算法。"""
        minutes = timecalc.inspection_duration(entry)
        # 拷贝一层，避免把派生字段写回仓库；原始记录里只保留最初录入的时间。
        view = dict(entry)
        view["查验时长分钟"] = minutes
        view[DURATION_FIELD] = timecalc.format_duration(minutes)
        return view

    def duration_for_container(self, container_no: Any) -> str:
        """供其他页面按箱号取查验时长：取到的就是查验页同一份，绝不在本地另算。"""
        text = str(container_no or "").strip()
        if not text:
            return PENDING_DURATION_TEXT
        for row in store.rows(MODULE):
            if str(row.get("箱号") or "").strip() == text:
                return timecalc.format_duration(timecalc.inspection_duration(row))
        return PENDING_DURATION_TEXT
