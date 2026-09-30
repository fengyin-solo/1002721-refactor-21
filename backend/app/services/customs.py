"""海关查验业务规则：状态流转、字段校验与筛选口径都收在这里。

查验时长的换算统一收在 ``inspection_time``，本服务只负责状态流转与
时间录入；列表、详情、导出读到的时长都由同一份算法给出。
"""
from __future__ import annotations

from typing import Any

from app.services import inspection_time as clock
from app.store import store

MODULE = "customs"
REQUIRED_FIELDS = ["查验编号", "箱号", "查验类型"]
STATUS_ORDER = ["待查验", "查验中", "已放行", "待复验"]
ACTION_RULES = {"安排查验": "查验中", "登记结果": "已放行", "安排复验": "待复验"}
NEGATIVE_ACTIONS = []

# 登记结果只认第一回：已经有封箱时间或查验结果的，不再接受重复登记。
RESULT_FIELDS = (clock.CLOSE_FIELD, "查验结果")


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
        page_rows = rows[start:start + size]
        return clock.describe_rows(page_rows), total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return clock.describe_entry(entry) if entry is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        # 选填的展示字段也原样收下，避免登记入口丢弃已录入的信息。
        for field in ("查验级别", clock.OPEN_FIELD, "查验结果", clock.CLOSE_FIELD, "查验状态"):
            if values.get(field) is not None:
                entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        clock.recalculate_entry(entry)
        return clock.describe_entry(entry), []

    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"查验记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于海关查验可执行范围"

        payload = values or {}
        if action == "登记结果" and self._has_result(entry):
            # 同一票查验重复登记只认第一回：保留首录的时间与结果。
            return None, "该票查验已登记过结果，只认第一回登记，不能重复登记"

        # 三个环节提交的时间都按原样留存，转换只发生在读取时的统一算法里。
        for field in clock.ACTION_TIME_FIELDS.get(action, ()):
            value = payload.get(field)
            if value is not None and str(value).strip():
                entry[field] = str(value).strip()
        if action == "登记结果":
            result = payload.get("查验结果")
            if result is not None and str(result).strip():
                entry["查验结果"] = str(result).strip()

        target = ACTION_RULES[action]
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        if target in STATUS_ORDER:
            entry["查验状态"] = target

        clock.recalculate_entry(entry)
        return clock.describe_entry(entry), f"查验记录已{action}"

    @staticmethod
    def _has_result(entry: dict[str, Any]) -> bool:
        return any(str(entry.get(field) or "").strip() for field in RESULT_FIELDS)
