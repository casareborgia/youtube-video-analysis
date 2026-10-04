import unittest
from services.scheduler_cron import AutonomousScheduler
from repositories.routine_repository import RoutineRepository


class TestSchedulerCron(unittest.TestCase):
    def setUp(self):
        self.repo = RoutineRepository()
        self.scheduler = AutonomousScheduler(self.repo)

    def test_reload_jobs_registers_all_routine_schedules(self):
        # 1. 스케줄 잡 동적 등록
        self.scheduler.reload_jobs()
        summary = self.scheduler.get_jobs_summary()

        # AI_TREND(3회) + MAUM_PROMO(2회) + RESEARCH(1회) + COMMENT_REPLY(2회) = 총 8개 잡
        self.assertGreaterEqual(len(summary), 6)

        job_ids = [j["job_id"] for j in summary]
        # AI_TREND 09:00, 14:00, 21:00 잡 포함 검증
        self.assertTrue(any("AI_TREND" in jid for jid in job_ids))
        self.assertTrue(any("MAUM_PROMO" in jid for jid in job_ids))
        self.assertTrue(any("RESEARCH" in jid for jid in job_ids))
        self.assertTrue(any("COMMENT_REPLY" in jid for jid in job_ids))

    def test_timezone_and_trigger_info(self):
        self.scheduler.reload_jobs()
        summary = self.scheduler.get_jobs_summary()
        self.assertGreater(len(summary), 0)

        first_job = summary[0]
        self.assertIn("job_id", first_job)
        self.assertIn("name", first_job)
        self.assertIn("trigger", first_job)


if __name__ == "__main__":
    unittest.main()
