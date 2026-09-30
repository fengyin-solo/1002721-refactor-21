"""集装箱信息业务规则：状态流转、字段校验与筛选口径都收在这里。

本页面展示的「查验时长」不在本模块另算一套，而是按箱号取海关查验那边
``inspection_time`` 给出的同一份结果，保证同一票查验在两处读到的数字一致。
"""
from __future__ import annotations

from typing import Any

from app.services import inspection_time as clock
from app.store import store

MODULE = "container"
REQUIRED_FIELDS = ["箱号", "箱型尺寸", "箱主代码"]
STATUS_ORDER = ["在场", "已装船", "已提箱", "待查验"]
ACTION_RULES = {"装船出场": "已装船", "办理提箱": "已提箱", "安排查验": "待查验"}
NEGATIVE_ACTIONS = []


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
        durations = clock.duration_by_container()
        return [
            self._with_inspection_duration(row, durations)
            for row in rows[start:start + size]
        ], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return self._with_inspection_duration(entry, clock.duration_by_container())

    @staticmethod
    def _with_inspection_duration(
        entry: dict[str, Any], durations: dict[str, str]
    ) -> dict[str, Any]:
        # 复制后再挂查验时长，避免把跨模块字段写回集装箱原始记录。
        projected = dict(entry)
        duration = durations.get(str(entry.get("箱号") or "").strip())
        projected["查验时长"] = duration if duration is not None else "—"
        return projected

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
