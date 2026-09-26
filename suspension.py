"""应急停播规则。

纯业务逻辑，不持有数据库连接：校验停播窗口、计算受影响排期与实播冲突、
检查恢复时的时段冲突。数据由调用方传入，便于独立测试。
"""
from __future__ import annotations

from datetime import datetime

from database import DomainError


def _minutes(value: str) -> int:
    parsed = datetime.strptime(value, "%H:%M")
    return parsed.hour * 60 + parsed.minute


def _intervals_overlap(a_start: str, a_duration: int, b_start: str, b_duration: int) -> bool:
    start_a, start_b = _minutes(a_start), _minutes(b_start)
    return start_a < start_b + b_duration and start_b < start_a + a_duration


def _in_window(start_time: str, duration_minutes: int, window: dict) -> bool:
    return _intervals_overlap(start_time, duration_minutes, window["start_time"],
                              _minutes(window["end_time"]) - _minutes(window["start_time"]))


def validate_window(region: str, air_date: str, start_time: str, end_time: str) -> dict:
    """校验并标准化停播窗口参数。"""
    region = str(region).strip()
    if not region:
        raise DomainError("地区不能为空")
    try:
        datetime.strptime(air_date, "%Y-%m-%d")
    except ValueError as exc:
        raise DomainError("停播日期必须使用 YYYY-MM-DD") from exc
    try:
        start, end = _minutes(start_time), _minutes(end_time)
    except ValueError as exc:
        raise DomainError("起止时间必须使用 HH:MM") from exc
    if start >= end:
        raise DomainError("停播开始时间必须早于结束时间")
    return {"region": region, "air_date": air_date, "start_time": start_time, "end_time": end_time}


def plan_suspension(window: dict, slots: list[dict], logs: list[dict]) -> tuple[list[dict], list[dict]]:
    """计算停播窗口的实播冲突与受影响排期。

    slots 为同地区同日期且未取消的排期，logs 为这些排期的实播记录。
    返回 (conflicts, affected)：
    - conflicts：与窗口重叠的实播记录，非空时调用方应整笔拒绝；
    - affected：尚未实播且计划时间与窗口重叠、应转为取消的排期。
    已登记实播的排期保持原样，既不取消也不被重复计入。
    """
    logged = {log["slot_id"] for log in logs}
    conflicts = [log for log in logs if _in_window(log["actual_start"], log["actual_duration_minutes"], window)]
    affected = [
        slot for slot in slots
        if slot["id"] not in logged and _in_window(slot["start_time"], slot["duration_minutes"], window)
    ]
    return conflicts, affected


def find_restore_conflicts(impacts: list[dict], current_slots: list[dict]) -> list[dict]:
    """检查恢复停播时，各受影响排期的原时段是否已被现有未取消排期占用。"""
    conflicts = []
    for impact in impacts:
        for slot in current_slots:
            if slot["id"] == impact["slot_id"]:
                continue
            if _intervals_overlap(impact["original_start_time"], impact["original_duration_minutes"],
                                  slot["start_time"], slot["duration_minutes"]):
                conflicts.append({"impact": impact, "slot": slot})
    return conflicts
