import unittest
import asyncio
from unittest.mock import patch
from services.publication_orchestrator import PublicationOrchestrator
from domain.models import StructuredDraft
from domain.enums import StepType, JobStatus
from repositories.routine_repository import RoutineRepository


class TestPublicationOrchestrator(unittest.TestCase):
    def setUp(self):
        self.repo = RoutineRepository()
        self.orchestrator = PublicationOrchestrator(self.repo)

    def test_create_chain_job_and_dry_run_execution(self):
        async def run_test():
            draft = StructuredDraft(
                headline="테스트 헤드라인",
                body="링크 없는 본문 내용입니다. 🔁 🧵",
                first_reply="📌 원문 링크: https://example.com/test",
                topic_key="TEST_TOPIC_1"
            )

            # 1. 작업 등록
            job_id = self.orchestrator.create_chain_job(
                routine_id=1,
                draft=draft,
                platforms=["threads", "x"]
            )
            self.assertIsNotNone(job_id)

            # 등록된 Step 확인 (threads 2개, x 2개 = 총 4개)
            job_data = self.repo.get_outbox_job_by_id(job_id)
            self.assertIsNotNone(job_data)
            self.assertEqual(len(job_data["steps"]), 4)

            # 2. 모의 실행 (dry_run=True)
            res = await self.orchestrator.execute_job(job_id=job_id, dry_run=True)
            self.assertEqual(res.status, JobStatus.SUCCEEDED.value)
            self.assertTrue(res.dry_run)

            # Threads 체인 검증
            threads_res = res.platform_results.get("threads")
            self.assertIsNotNone(threads_res)
            self.assertIn("mock_threads_parent", threads_res["parent_id"])
            self.assertIn("mock_threads_reply", threads_res["reply_id"])

            # X 체인 검증
            x_res = res.platform_results.get("x")
            self.assertIsNotNone(x_res)
            self.assertIn("mock_x_parent", x_res["parent_id"])
            self.assertIn("mock_x_reply", x_res["reply_id"])

        asyncio.run(run_test())

    def test_partial_failure_isolation(self):
        """Threads 성공 + X 실패 시 격리되어 PARTIAL 상태가 되는지 검증"""
        async def run_test():
            draft = StructuredDraft(
                headline="부분 실패 격리 테스트",
                body="본문입니다.",
                first_reply="답글입니다.",
                topic_key="PARTIAL_FAIL_TEST"
            )

            job_id = self.orchestrator.create_chain_job(
                routine_id=1,
                draft=draft,
                platforms=["threads", "x"]
            )

            # Threads는 성공, X는 실패 모의
            async def mock_publish(platform, text, reply_to_id=None):
                if platform == "threads":
                    return "threads_real_id_123"
                else:
                    raise RuntimeError("X API Rate Limit Exceeded (429)")

            with patch.object(self.orchestrator, "_publish_platform_post", side_effect=mock_publish):
                res = await self.orchestrator.execute_job(job_id=job_id, dry_run=False)
                self.assertEqual(res.status, "PARTIAL")
                self.assertEqual(res.platform_results["threads"]["status"], "SUCCEEDED")
                self.assertEqual(res.platform_results["x"]["status"], "FAILED")
                self.assertIn("Rate Limit", res.platform_results["x"]["error"])

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
