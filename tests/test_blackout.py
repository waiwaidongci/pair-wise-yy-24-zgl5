import os
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blackout import BlackoutConflictError, BlackoutError
from database import DomainError, RadioDB


class EmergencyBlackoutTest(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.db = RadioDB(self.path)
        self.p1 = self.db.add_program("早间新闻", "talk", 30, "2026-01-01", "2026-12-31", None, 0, ["华东"])
        self.p2 = self.db.add_program("午间音乐", "music", 60, "2026-01-01", "2026-12-31", None, 0, ["华东"])
        # 华东 2026-09-28: 09:00 news(30) 10:00 music(60) 12:00 news(30)
        self.s1 = self.db.schedule_slot("2026-09-28", "09:00", self.p1, "华东")
        self.s2 = self.db.schedule_slot("2026-09-28", "10:00", self.p2, "华东")
        self.s3 = self.db.schedule_slot("2026-09-28", "12:00", self.p1, "华东")

    def tearDown(self):
        self.db.close()
        os.unlink(self.path)

    def test_cancels_unaired_overlapping_slots_and_keeps_snapshot(self):
        result = self.db.register_blackout("华东", "2026-09-28", "09:30", "11:00", "设备故障")
        self.assertEqual("active", result["status"])
        self.assertEqual([self.s2], [c["slot_id"] for c in result["cancellations"]])
        self.assertEqual("cancelled", self.db.get_slot(self.s2)["status"])
        # slots outside the window keep playing as planned
        self.assertEqual("planned", self.db.get_slot(self.s1)["status"])
        self.assertEqual("planned", self.db.get_slot(self.s3)["status"])
        snapshot = result["cancellations"][0]
        self.assertEqual(self.p2, snapshot["program_id"])
        self.assertEqual("10:00", snapshot["start_time"])
        self.assertEqual(60, snapshot["duration_minutes"])

    def test_window_overlapping_playout_is_entirely_rejected_with_conflicts(self):
        # 09:00 news actually aired 09:00-09:30
        self.db.record_playout(self.s1, "09:00", 30, self.p1)
        with self.assertRaises(BlackoutConflictError) as ctx:
            self.db.register_blackout("华东", "2026-09-28", "08:00", "09:15", "突发停播")
        conflicts = ctx.exception.conflicts
        self.assertEqual([self.s1], [c["slot_id"] for c in conflicts])
        self.assertEqual("09:30", conflicts[0]["actual_end"])
        # whole entry refused: no blackout row, nothing cancelled, aired slot untouched
        self.assertEqual([], self.db.list_blackouts())
        self.assertEqual("planned", self.db.get_slot(self.s1)["status"])
        self.assertEqual("planned", self.db.get_slot(self.s2)["status"])

    def test_aired_slot_not_cancelled_and_adjacent_window_is_accepted(self):
        # playout sits just before the window: touching boundary must not conflict
        self.db.record_playout(self.s1, "09:00", 30, self.p1)
        result = self.db.register_blackout("华东", "2026-09-28", "09:30", "10:00", "")
        self.assertEqual([], result["cancellations"])
        self.assertEqual("planned", self.db.get_slot(self.s1)["status"])

    def test_duplicate_window_reuses_original_result(self):
        first = self.db.register_blackout("华东", "2026-09-28", "09:30", "11:00", "原因甲")
        again = self.db.register_blackout("华东", "2026-09-28", "09:30", "11:00", "另一个原因")
        self.assertFalse(first["reused"])
        self.assertTrue(again["reused"])
        self.assertEqual(first["id"], again["id"])
        self.assertEqual("原因甲", again["reason"])
        self.assertEqual(1, len(self.db.list_blackouts()))

    def test_other_regions_and_dates_are_unaffected(self):
        north = self.db.add_program("华北新闻", "talk", 30, "2026-01-01", "2026-12-31", None, 0, ["华北"])
        other_day = self.db.schedule_slot("2026-09-29", "10:00", self.p2, "华东")
        other_region = self.db.schedule_slot("2026-09-28", "10:00", north, "华北")
        self.db.register_blackout("华东", "2026-09-28", "09:30", "11:00", "")
        self.assertEqual("planned", self.db.get_slot(other_day)["status"])
        self.assertEqual("planned", self.db.get_slot(other_region)["status"])

    def test_restore_returns_slot_to_original_snapshot(self):
        # replace s1 first so its pre-blackout status is 'replaced'
        self.db.replace_slot(self.s1, self.p2)
        result = self.db.register_blackout("华东", "2026-09-28", "08:00", "13:00", "")
        self.assertEqual(3, len(result["cancellations"]))
        for slot_id in (self.s1, self.s2, self.s3):
            self.assertEqual("cancelled", self.db.get_slot(slot_id)["status"])
        restored = self.db.restore_blackout(result["id"])
        self.assertEqual([self.s1, self.s2, self.s3], restored["restored_slots"])
        self.assertEqual([], restored["skipped_slots"])
        s1 = self.db.get_slot(self.s1)
        self.assertEqual("replaced", s1["status"])
        self.assertEqual(self.p2, s1["program_id"])
        self.assertEqual(60, s1["duration_minutes"])
        self.assertEqual(self.p1, s1["replaced_from"])
        self.assertEqual("planned", self.db.get_slot(self.s3)["status"])
        self.assertEqual("restored", self.db.get_blackout(result["id"])["status"])
        # after restoring, the same window may be registered again
        fresh = self.db.register_blackout("华东", "2026-09-28", "08:00", "13:00", "")
        self.assertFalse(fresh["reused"])

    def test_cancelled_slot_frees_window_for_new_schedule(self):
        self.db.register_blackout("华东", "2026-09-28", "09:30", "11:00", "")
        # new plan overlapping the cancelled 10:00 slot must be accepted
        new_slot = self.db.schedule_slot("2026-09-28", "10:00", self.p1, "华东")
        self.assertTrue(new_slot)

    def test_invalid_window(self):
        with self.assertRaises(BlackoutError):
            self.db.register_blackout("华东", "2026-09-28", "11:00", "10:00", "")
        with self.assertRaises(BlackoutError):
            self.db.register_blackout("", "2026-09-28", "09:00", "10:00", "")
        with self.assertRaises(BlackoutError):
            self.db.register_blackout("华东", "2026/09/28", "09:00", "10:00", "")

    def test_restore_unknown_or_already_restored_fails(self):
        with self.assertRaises(DomainError):
            self.db.restore_blackout(9999)
        result = self.db.register_blackout("华东", "2026-09-28", "09:30", "11:00", "")
        self.db.restore_blackout(result["id"])
        with self.assertRaises(DomainError):
            self.db.restore_blackout(result["id"])


if __name__ == "__main__":
    unittest.main()
