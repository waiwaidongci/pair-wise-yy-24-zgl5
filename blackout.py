"""Emergency blackout rules (pure domain layer).

This module only decides what a blackout window does: which unaired slots
must be cancelled and which playout records conflict with the window. It
never touches the database. Persistence lives in ``database.py`` and the
page/API operations live in ``app.py``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# Slots in these statuses are still plans waiting to air, so a blackout
# window covering them turns them into cancellations.
CANCELLABLE_STATUSES = ("planned", "replaced")


class BlackoutError(ValueError):
    """The blackout window itself is invalid."""


class BlackoutConflictError(BlackoutError):
    """The window overlaps real playout records; the whole entry is refused."""

    def __init__(self, message: str, conflicts: list[dict]) -> None:
        super().__init__(message)
        self.conflicts = conflicts


@dataclass
class BlackoutPlan:
    affected: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)


def minutes(value: str) -> int:
    try:
        parsed = datetime.strptime(value, "%H:%M")
    except (TypeError, ValueError) as exc:
        raise BlackoutError("时间必须使用 HH:MM") from exc
    return parsed.hour * 60 + parsed.minute


def shift_time(value: str, delta_minutes: int) -> str:
    total = minutes(value) + int(delta_minutes)
    return f"{total // 60:02d}:{total % 60:02d}"


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    # Half-open intervals: touching boundaries do not overlap.
    return a_start < b_end and b_start < a_end


def parse_window(region: str, air_date: str, start_time: str, end_time: str) -> tuple[str, str, str, str]:
    region = (region or "").strip()
    if not region:
        raise BlackoutError("地区不能为空")
    try:
        datetime.strptime(air_date, "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise BlackoutError("日期必须使用 YYYY-MM-DD") from exc
    start, end = minutes(start_time), minutes(end_time)
    if start >= end:
        raise BlackoutError("停播结束时间必须晚于开始时间")
    return region, air_date, start_time, end_time


def plan_blackout(region: str, air_date: str, start_time: str, end_time: str,
                  slots: list[dict], playouts: list[dict]) -> BlackoutPlan:
    """Compute cancellations and conflicts for one blackout window.

    ``slots`` rows need: id, region, air_date, start_time, duration_minutes,
    status. ``playouts`` rows need: playout_id, slot_id, region, air_date,
    actual_start, actual_duration_minutes (and optional title).
    """
    window_start, window_end = minutes(start_time), minutes(end_time)
    logged_slot_ids = {
        log["slot_id"] for log in playouts
        if log.get("region") == region and log.get("air_date") == air_date
    }
    plan = BlackoutPlan()
    for slot in slots:
        if slot.get("region") != region or slot.get("air_date") != air_date:
            continue
        if slot.get("status") not in CANCELLABLE_STATUSES:
            continue
        # A slot that already has a playout record stays exactly as it is.
        if slot["id"] in logged_slot_ids:
            continue
        slot_start = minutes(slot["start_time"])
        slot_end = slot_start + int(slot["duration_minutes"])
        if _overlaps(window_start, window_end, slot_start, slot_end):
            plan.affected.append(slot)
    for log in playouts:
        if log.get("region") != region or log.get("air_date") != air_date:
            continue
        actual_start = minutes(log["actual_start"])
        actual_end = actual_start + int(log["actual_duration_minutes"])
        if _overlaps(window_start, window_end, actual_start, actual_end):
            plan.conflicts.append({
                "playout_id": log["playout_id"],
                "slot_id": log["slot_id"],
                "title": log.get("title"),
                "actual_start": log["actual_start"],
                "actual_end": shift_time(log["actual_start"], log["actual_duration_minutes"]),
            })
    return plan


def reject_if_conflicted(plan: BlackoutPlan) -> None:
    """Refuse the whole entry when any real playout overlaps the window."""
    if plan.conflicts:
        raise BlackoutConflictError("停播窗口与实播记录重叠，已整笔拒绝", plan.conflicts)
