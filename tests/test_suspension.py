import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import DomainError, RadioDB


class EmergencySuspensionTest(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.db = RadioDB(self.path)
        self.p1 = self.db.add_program("早间新闻", "talk", 30, "2026-01-01", "2026-12-31", None, 0, ["华东"])
        self.p2 = self.db.add_program("午后音乐", "music", 30, "2026-01-01", "2026-12-31", None, 0, ["华东"])

    def tearDown(self):
        self.db.close()
        os.unlink(self.path)

    def test_suspension_cancels_unaired_slots_and_lists_originals(self):
        s1 = self.db.schedule_slot("2026-09-28", "09:00", self.p1, "华东")
        s2 = self.db.schedule_slot("2026-09-28", "10:00", self.p2, "华东")
        s3 = self.db.schedule_slot("2026-09-28", "12:00", self.p1, "华东")
        result = self.db.register_suspension("华东", "2026-09-28", "08:30", "10:30", "发射塔故障")
        self.assertFalse(result["reused"])
        self.assertEqual("active", result["status"])
        self.assertEqual("cancelled", self.db.get_slot(s1)["status"])
        self.assertEqual("cancelled", self.db.get_slot(s2)["status"])
        self.assertEqual("planned", self.db.get_slot(s3)["status"])
        impacts = {i["slot_id"]: i for i in result["impacts"]}
        self.assertEqual({s1, s2}, set(impacts))
        self.assertEqual(self.p1, impacts[s1]["original_program_id"])
        self.assertEqual("早间新闻", impacts[s1]["original_title"])
        self.assertEqual("09:00", impacts[s1]["original_start_time"])
        self.assertEqual(30, impacts[s1]["original_duration_minutes"])

    def test_playout_overlap_rejects_entire_suspension(self):
        s1 = self.db.schedule_slot("2026-09-28", "09:00", self.p1, "华东")
        s2 = self.db.schedule_slot("2026-09-28", "10:00", self.p2, "华东")
        self.db.record_playout(s1, "09:00", 30, self.p1)
        with self.assertRaisesRegex(DomainError, f"排期#{s1}"):
            self.db.register_suspension("华东", "2026-09-28", "09:15", "10:30")
        # 整笔拒绝：排期不变、不产生停播记录
        self.assertEqual("planned", self.db.get_slot(s1)["status"])
        self.assertEqual("planned", self.db.get_slot(s2)["status"])
        self.assertEqual([], self.db.list_suspensions())

    def test_aired_slots_stay_untouched_when_window_misses_playout(self):
        s1 = self.db.schedule_slot("2026-09-28", "09:00", self.p1, "华东")
        s2 = self.db.schedule_slot("2026-09-28", "10:00", self.p2, "华东")
        self.db.record_playout(s1, "09:00", 30, self.p1)
        self.db.register_suspension("华东", "2026-09-28", "10:00", "11:00")
        self.assertEqual("planned", self.db.get_slot(s1)["status"])
        self.assertEqual("cancelled", self.db.get_slot(s2)["status"])

    def test_duplicate_window_reuses_original_result(self):
        self.db.schedule_slot("2026-09-28", "09:00", self.p1, "华东")
        first = self.db.register_suspension("华东", "2026-09-28", "08:00", "10:00")
        second = self.db.register_suspension("华东", "2026-09-28", "08:00", "10:00")
        self.assertTrue(second["reused"])
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(first["impacts"]), len(second["impacts"]))
        self.assertEqual(1, len(self.db.list_suspensions()))

    def test_restore_returns_slots_to_original_program_and_time(self):
        s1 = self.db.schedule_slot("2026-09-28", "09:00", self.p1, "华东")
        result = self.db.register_suspension("华东", "2026-09-28", "08:00", "10:00")
        self.assertEqual("cancelled", self.db.get_slot(s1)["status"])
        restored = self.db.restore_suspension(result["id"])
        slot = self.db.get_slot(s1)
        self.assertEqual("planned", slot["status"])
        self.assertEqual(self.p1, slot["program_id"])
        self.assertEqual("09:00", slot["start_time"])
        self.assertEqual("restored", restored["status"])
        self.assertTrue(all(i["restored"] for i in restored["impacts"]))
        with self.assertRaisesRegex(DomainError, "已恢复"):
            self.db.restore_suspension(result["id"])

    def test_restore_rejected_when_original_time_taken(self):
        s1 = self.db.schedule_slot("2026-09-28", "09:00", self.p1, "华东")
        result = self.db.register_suspension("华东", "2026-09-28", "08:00", "10:00")
        self.db.schedule_slot("2026-09-28", "09:10", self.p2, "华东")
        with self.assertRaisesRegex(DomainError, "恢复失败"):
            self.db.restore_suspension(result["id"])
        self.assertEqual("cancelled", self.db.get_slot(s1)["status"])

    def test_invalid_window_rejected(self):
        with self.assertRaisesRegex(DomainError, "早于结束时间"):
            self.db.register_suspension("华东", "2026-09-28", "10:00", "09:00")
        with self.assertRaisesRegex(DomainError, "YYYY-MM-DD"):
            self.db.register_suspension("华东", "28/09/2026", "09:00", "10:00")
        with self.assertRaisesRegex(DomainError, "地区不能为空"):
            self.db.register_suspension(" ", "2026-09-28", "09:00", "10:00")


if __name__ == "__main__":
    unittest.main()
