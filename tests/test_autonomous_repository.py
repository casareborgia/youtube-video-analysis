import os
import unittest
from repositories.routine_repository import RoutineRepository
from domain.models import RoutineUpdate, SourceCreate, SourceUpdate, ScheduleItem
from domain.enums import RoutineMode, SourceType

TEST_DB_PATH = "data/test_autonomous_operator.db"


class TestRoutineRepository(unittest.TestCase):
    def setUp(self):
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
        self.repo = RoutineRepository(db_path=TEST_DB_PATH)

    def tearDown(self):
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)

    def test_default_routines_seeded(self):
        routines = self.repo.get_routines()
        self.assertEqual(len(routines), 4)

        keys = [r.key for r in routines]
        self.assertIn("AI_TREND", keys)
        self.assertIn("MAUM_PROMO", keys)
        self.assertIn("RESEARCH", keys)
        self.assertIn("COMMENT_REPLY", keys)

        # AI_TREND 스케줄 3회 확인
        ai_routine = self.repo.get_routine_by_key("AI_TREND")
        self.assertIsNotNone(ai_routine)
        self.assertEqual(len(ai_routine.schedules), 3)
        self.assertEqual(len(ai_routine.sources), 2)

    def test_maum_angles_seeded_and_cycled(self):
        maum = self.repo.get_routine_by_key("MAUM_PROMO")
        self.assertIsNotNone(maum)

        angles = self.repo.get_angles(maum.id)
        self.assertEqual(len(angles), 8)

        # 첫 번째 순환 선택
        first = self.repo.get_next_angle(maum.id)
        self.assertIsNotNone(first)
        self.assertEqual(first.angle_index, 1)

        # 두 번째 순환 선택은 다른 앵글이어야 함
        second = self.repo.get_next_angle(maum.id)
        self.assertIsNotNone(second)
        self.assertNotEqual(first.id, second.id)

    def test_update_routine(self):
        ai_routine = self.repo.get_routine_by_key("AI_TREND")
        self.assertIsNotNone(ai_routine)

        updated = self.repo.update_routine(
            ai_routine.id,
            RoutineUpdate(
                mode=RoutineMode.AUTO,
                schedules=[ScheduleItem(local_time="10:30", days_of_week=["MON", "WED", "FRI"])],
                max_posts_per_day=5
            )
        )
        self.assertEqual(updated.mode, RoutineMode.AUTO)
        self.assertEqual(len(updated.schedules), 1)
        self.assertEqual(updated.schedules[0].local_time, "10:30")
        self.assertEqual(updated.max_posts_per_day, 5)

    def test_source_crud(self):
        ai_routine = self.repo.get_routine_by_key("AI_TREND")
        new_source = self.repo.add_source(
            SourceCreate(
                routine_id=ai_routine.id,
                name="Custom Tech Blog",
                kind=SourceType.RSS_ATOM,
                url="https://example.com/rss.xml",
                enabled=True
            )
        )
        self.assertIsNotNone(new_source.id)
        self.assertEqual(new_source.name, "Custom Tech Blog")

        # 수정
        updated_source = self.repo.update_source(
            new_source.id,
            SourceUpdate(name="Updated Blog", enabled=False)
        )
        self.assertEqual(updated_source.name, "Updated Blog")
        self.assertFalse(updated_source.enabled)

        # 삭제
        deleted = self.repo.delete_source(new_source.id)
        self.assertTrue(deleted)
        self.assertIsNone(self.repo.get_source_by_id(new_source.id))

    def test_dedup_collection(self):
        ai_routine = self.repo.get_routine_by_key("AI_TREND")
        url_hash = "abc123hash"
        self.assertFalse(self.repo.is_item_collected(url_hash))

        self.repo.record_collected_item(
            url_hash=url_hash,
            url="https://example.com/news/1",
            title="Sample News",
            summary="Summary text",
            source_id=1,
            routine_id=ai_routine.id
        )
        self.assertTrue(self.repo.is_item_collected(url_hash))


if __name__ == "__main__":
    unittest.main()
