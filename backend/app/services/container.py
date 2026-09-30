"""集装箱信息业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.services.customs import CustomsService
from app.store import store

MODULE = "container"
REQUIRED_FIELDS = ["箱号", "箱型尺寸", "箱主代码"]
STATUS_ORDER = ["在场", "已装船", "已提箱", "待查验"]
ACTION_RULES = {"装船出场": "已装船", "办理提箱": "已提箱", "安排查验": "待查验"}
NEGATIVE_ACTIONS = []

# 查验时长不在本模块另算：直接复用海关查验的同一份换算结果。
_customs_service = CustomsService()


class ContainerService:
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
            rows = [row for row in rows if keyword in str(row.get("箱号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        items = [self._with_customs_duration(row) for row in rows[start:start + size]]
        return items, total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._with_customs_duration(entry) if entry is not None else None

    @staticmethod
    def _with_customs_duration(entry: dict[str, Any]) -> dict[str, Any]:
        """本页展示的查验时长直接取海关查验那份，绝不在集装箱模块另写一套换算。"""
        view = dict(entry)
        view["查验时长"] = _customs_service.duration_for_container(entry.get("箱号"))
        return view

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"集装箱 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于集装箱信息可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"集装箱已{action}"
