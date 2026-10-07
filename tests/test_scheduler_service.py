"""Phase 7: 로컬 예약 실행기 및 재시도 엔진 단위/통합 테스트.

작업지시서 Phase 7 완료 조건:
- 가상 시계(Virtual Time / Time Provider) 주입을 통한 예약 및 지수 백오프 검증
- 원자적 리스 점유를 통한 중복 실행 방지 검증
- 일시적 오류 vs 영구적 오류 분류 및 지수 백오프 검증
- 최대 재시도 초과 시 failed 종결 검증
- 앱 재시작 시 유예 기간 내 즉시 복구 및 초과 시 needs_approval 격리 검증
- 작업 취소 및 수동 재시도 API 계약 검증
"""

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import app
import scheduler_service
from scheduler_service import (
    LocalJobScheduler,
    MissedSchedulePolicy,
    RetryPolicy,
)
import social_store
from social_store import SocialStore


class SchedulerServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test_social.db"
        self.patch_db = patch("social_store.DEFAULT_DB_PATH", self.db_path)
        self.patch_db.start()
        self.store = SocialStore(path=self.db_path)

        # 가상 시계 초기화 (기본 1,000,000초부터 시작)
        self.current_time = 1_000_000.0

        def virtual_time():
            return self.current_time

        self.time_provider = virtual_time

        self.retry_policy = RetryPolicy(
            max_retries=3,
            base_delay_seconds=10,
            max_delay_seconds=300,
        )
        self.missed_policy = MissedSchedulePolicy(grace_period_seconds=3600)

        self.mock_pub = MagicMock()
        self.mock_rep = MagicMock()
        self.mock_eng = MagicMock()

        self.scheduler = LocalJobScheduler(
            store=self.store,
            pub_service=self.mock_pub,
            rep_service=self.mock_rep,
            eng_service=self.mock_eng,
            retry_policy=self.retry_policy,
            missed_policy=self.missed_policy,
            time_provider=self.time_provider,
            worker_id="test_worker_1",
        )

    def tearDown(self):
        self.scheduler.stop()
        self.patch_db.stop()
        self.tmp.cleanup()

    # ==========================================
    # 1. 재시도 정책 및 지수 백오프 계산 검증
    # ==========================================
    def test_retry_policy_classification(self):
        """일시적 오류와 영구적 오류가 올바르게 분류되는지 검증."""
        # 재시도 가능: 타임아웃, 네트워크 오류, 5xx, 429
        self.assertTrue(self.retry_policy.is_retryable("TIMEOUT", "Connection timed out"))
        self.assertTrue(self.retry_policy.is_retryable("HTTP_503", "Service Unavailable"))
        self.assertTrue(self.retry_policy.is_retryable("RATE_LIMIT", "Too many requests 429"))
        self.assertTrue(self.retry_policy.is_retryable("", "Server Error 500 Internal"))

        # 재시도 불가: 인증 오류, 401, 403, 400, 권한 부족
        self.assertFalse(self.retry_policy.is_retryable("UNAUTHORIZED", "Invalid Bearer Token"))
        self.assertFalse(self.retry_policy.is_retryable("FORBIDDEN", "Missing required scope"))
        self.assertFalse(self.retry_policy.is_retryable("HTTP_400", "Bad Request invalid parameter"))
        self.assertFalse(self.retry_policy.is_retryable("TOKEN_EXPIRED", "Token expired"))
        self.assertFalse(self.retry_policy.is_retryable("", "Client error: unapproved job"))

    def test_exponential_backoff_calculation(self):
        """지수 백오프 지연 시간 계산 검증 (10 * 2^retry_count, max 300)."""
        # base=10: 10 * 2^0 = 10
        self.assertEqual(self.retry_policy.compute_backoff(0), 10)
        # 10 * 2^1 = 20
        self.assertEqual(self.retry_policy.compute_backoff(1), 20)
        # 10 * 2^2 = 40
        self.assertEqual(self.retry_policy.compute_backoff(2), 40)
        # 10 * 2^3 = 80
        self.assertEqual(self.retry_policy.compute_backoff(3), 80)
        # 상한선(300) 제한 확인
        self.assertEqual(self.retry_policy.compute_backoff(10), 300)

    # ==========================================
    # 2. 가상 시계를 이용한 미래 예약 실행 검증
    # ==========================================
    def test_scheduled_job_lease_and_execution_with_virtual_time(self):
        """미래 시각으로 예약된 작업이 시각 도래 전에는 실행되지 않고, 시각 도래 후 정확히 1회 실행."""
        job = self.store.create_job(
            platform="threads",
            job_type="publish",
            actor_account_id="act_user_1",
            dry_run=True,
        )
        job_id = job["job_id"]
        # 60초 뒤로 예약 (approved_at도 설정)
        future_time = int(self.current_time + 60)
        self.scheduler.schedule_job(job_id, scheduled_at=future_time, require_approval=False)

        # 1. 현재 시각(t = 1,000,000)에는 아직 시각이 도래하지 않아 점유되지 않음
        result_before = self.scheduler.run_once()
        self.assertIsNone(result_before)
        self.mock_pub.execute_publish_job.assert_not_called()

        # 2. 가상 시계를 61초 후로 진행 (t = 1,000,061)
        self.current_time += 61.0

        self.mock_pub.execute_publish_job.return_value = {"status": "succeeded", "post_id": "p_123"}
        result_after = self.scheduler.run_once()

        self.assertIsNotNone(result_after)
        self.assertEqual(result_after["job_id"], job_id)
        self.assertEqual(result_after["status"], "succeeded")
        self.mock_pub.execute_publish_job.assert_called_once_with(
            job_id=job_id, worker_id="test_worker_1", dry_run=True
        )

    # ==========================================
    # 3. 원자적 동시성 점유 (중복 실행 방지)
    # ==========================================
    def test_atomic_lease_concurrency_no_double_execution(self):
        """2개 워커가 동시에 도래한 작업을 점유하려 할 때 1개 워커만 획득 성공."""
        job = self.store.create_job(
            platform="x",
            job_type="publish",
            actor_account_id="act_user_x",
            dry_run=True,
        )
        job_id = job["job_id"]
        # 승인 및 현재 시각 실행 상태로 전이
        self.store.transition_job_status(job_id, "approved")
        self.store.transition_job_status(job_id, "scheduled", scheduled_at=int(self.current_time))

        scheduler_worker_2 = LocalJobScheduler(
            store=self.store,
            time_provider=self.time_provider,
            worker_id="test_worker_2",
        )

        # 워커 1이 점유 시도 -> 성공
        res1 = self.scheduler.run_once()
        self.assertIsNotNone(res1)
        self.assertEqual(res1["job_id"], job_id)

        # 동일 시점에 워커 2가 점유 시도 -> 이미 점유되어 실행 중이므로 None 반환
        res2 = scheduler_worker_2.run_once()
        self.assertIsNone(res2)

    # ==========================================
    # 4. 일시적 오류 시 지수 백오프 및 재시도 검증
    # ==========================================
    def test_transient_failure_exponential_backoff_and_reschedule(self):
        """일시적 오류 발생 시 지수 백오프가 적용되어 scheduled로 복귀하고 시각이 연기됨."""
        job = self.store.create_job(
            platform="x",
            job_type="publish",
            actor_account_id="act_user_x",
            dry_run=False,
        )
        job_id = job["job_id"]
        self.store.transition_job_status(job_id, "approved")
        self.store.transition_job_status(job_id, "scheduled", scheduled_at=int(self.current_time))

        # 일시적 타임아웃 오류 발생 모킹
        class TransientError(Exception):
            code = "TIMEOUT"

        self.mock_pub.execute_publish_job.side_effect = TransientError("Read timeout to api.x.com")

        # 1회차 실행 시도 -> 실패 후 백오프 예약
        res = self.scheduler.run_once()
        self.assertIsNotNone(res)
        self.assertEqual(res["status"], "scheduled")
        self.assertEqual(res["action"], "retry_scheduled")
        # 1회차 백오프: 10초 뒤 (1,000,000 + 10 = 1,000,010)
        self.assertEqual(res["next_schedule"], 1_000_010)

        # DB 상태 검증
        updated_job = self.store.get_job(job_id)
        self.assertEqual(updated_job["status"], "scheduled")
        self.assertEqual(updated_job["scheduled_at"], 1_000_010)
        self.assertEqual(updated_job["retry_count"], 1)
        self.assertEqual(updated_job["last_error_code"], "TIMEOUT")

    # ==========================================
    # 5. 영구적 오류 시 즉시 failed 종결 검증
    # ==========================================
    def test_permanent_failure_immediate_failed_status(self):
        """인증 실패(UNAUTHORIZED) 등 영구적 오류는 재시도 없이 즉시 failed 상태로 종료."""
        job = self.store.create_job(
            platform="x",
            job_type="publish",
            actor_account_id="act_user_x",
            dry_run=False,
        )
        job_id = job["job_id"]
        self.store.transition_job_status(job_id, "approved")
        self.store.transition_job_status(job_id, "scheduled", scheduled_at=int(self.current_time))

        class PermanentError(Exception):
            code = "UNAUTHORIZED"

        self.mock_pub.execute_publish_job.side_effect = PermanentError("Invalid access token or expired")

        res = self.scheduler.run_once()
        self.assertIsNotNone(res)
        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["error_code"], "UNAUTHORIZED")

        # DB 상태 검증: 재시도 카운트 없이 failed로 확정
        updated_job = self.store.get_job(job_id)
        self.assertEqual(updated_job["status"], "failed")
        self.assertEqual(updated_job["last_error_code"], "UNAUTHORIZED")

    # ==========================================
    # 6. 최대 재시도 초과 시 failed 확정
    # ==========================================
    def test_max_retries_exhaustion(self):
        """일시적 오류라도 max_retries(3회)에 도달하면 최종 failed로 확정."""
        job = self.store.create_job(
            platform="threads",
            job_type="publish",
            actor_account_id="act_threads",
            max_retries=2,
            dry_run=False,
        )
        job_id = job["job_id"]
        self.store.transition_job_status(job_id, "approved")
        self.store.transition_job_status(job_id, "scheduled", scheduled_at=int(self.current_time))

        class TransientError(Exception):
            code = "HTTP_503"

        self.mock_pub.execute_publish_job.side_effect = TransientError("Service unavailable")

        # 시도 1
        res1 = self.scheduler.run_once()
        self.assertEqual(res1["status"], "scheduled")
        self.current_time = res1["next_schedule"]

        # 시도 2
        res2 = self.scheduler.run_once()
        self.assertEqual(res2["status"], "scheduled")
        self.current_time = res2["next_schedule"]

        # 시도 3: max_retries(2회) 초과 -> failed
        res3 = self.scheduler.run_once()
        self.assertEqual(res3["status"], "failed")
        self.assertTrue(res3["retries_exhausted"])

        final_job = self.store.get_job(job_id)
        self.assertEqual(final_job["status"], "failed")

    # ==========================================
    # 7. 기한 지난 예약 작업 복구 및 격리
    # ==========================================
    def test_missed_schedule_recovery_within_grace_period(self):
        """유예 시간(3600초) 이내의 지난 예약은 즉시 정상 실행."""
        job = self.store.create_job(
            platform="threads",
            job_type="publish",
            actor_account_id="act_threads",
            dry_run=True,
        )
        job_id = job["job_id"]
        # 10분 전(600초 전)에 예약되었던 작업
        self.store.transition_job_status(job_id, "approved")
        self.store.transition_job_status(job_id, "scheduled", scheduled_at=int(self.current_time - 600))

        self.mock_pub.execute_publish_job.return_value = {"status": "succeeded"}
        res = self.scheduler.run_once()
        self.assertIsNotNone(res)
        self.assertEqual(res["job_id"], job_id)
        self.assertEqual(res["status"], "succeeded")

    def test_missed_schedule_marked_needs_approval_if_exceeding_grace_period(self):
        """유예 시간(3600초)을 초과하여 심각하게 지난 예약은 임의 실행되지 않고 needs_approval 로 전환."""
        job = self.store.create_job(
            platform="threads",
            job_type="publish",
            actor_account_id="act_threads",
            dry_run=True,
        )
        job_id = job["job_id"]
        # 2시간 전(7200초 전)에 예약되었던 작업
        self.store.transition_job_status(job_id, "approved")
        self.store.transition_job_status(job_id, "scheduled", scheduled_at=int(self.current_time - 7200))

        # 틱 실행
        res = self.scheduler.run_once()
        # 점유되어 실행되지 않음
        self.assertIsNone(res)
        self.mock_pub.execute_publish_job.assert_not_called()

        # DB 확인: needs_approval 로 안전 전환됨
        updated_job = self.store.get_job(job_id)
        self.assertEqual(updated_job["status"], "needs_approval")
        self.assertEqual(updated_job["last_error_code"], "MISSED_SCHEDULE")

    # ==========================================
    # 8. 작업 취소 및 수동 재실행
    # ==========================================
    def test_cancel_and_manual_retry_job(self):
        """작업 취소(cancelled) 및 수동 재실행(retry) 제어 검증."""
        job = self.store.create_job(
            platform="x",
            job_type="publish",
            actor_account_id="act_user_x",
            dry_run=True,
        )
        job_id = job["job_id"]
        self.store.transition_job_status(job_id, "approved")
        self.store.transition_job_status(job_id, "scheduled", scheduled_at=int(self.current_time + 300))

        # 취소
        cancelled = self.scheduler.cancel_job(job_id)
        self.assertEqual(cancelled["status"], "cancelled")

        # 수동 재실행 (run_immediately=False -> scheduled 등록)
        retried = self.scheduler.retry_job_manually(job_id, run_immediately=False)
        self.assertEqual(retried["status"], "scheduled")

    # ==========================================
    # 9. API 엔드포인트 계약 테스트
    # ==========================================
    def test_api_scheduler_endpoints(self):
        client = TestClient(app)

        # 1. GET /api/social/scheduler/status
        resp_status = client.get("/api/social/scheduler/status")
        self.assertEqual(resp_status.status_code, 200)
        status_data = resp_status.json()
        self.assertEqual(status_data["status"], "success")
        self.assertIn("scheduler", status_data)

        # 2. POST /api/social/scheduler/tick
        resp_tick = client.post("/api/social/scheduler/tick")
        self.assertEqual(resp_tick.status_code, 200)
        self.assertEqual(resp_tick.json()["status"], "success")

        # 3. 작업 생성 후 취소 API (/api/social/jobs/{job_id}/cancel)
        global_store = SocialStore()
        test_job = global_store.create_job(
            platform="x",
            job_type="publish",
            actor_account_id="api_test_actor",
            dry_run=True,
        )
        test_jid = test_job["job_id"]
        global_store.transition_job_status(test_jid, "approved")
        global_store.transition_job_status(test_jid, "scheduled", scheduled_at=int(time.time() + 600))

        resp_cancel = client.post(f"/api/social/jobs/{test_jid}/cancel")
        self.assertEqual(resp_cancel.status_code, 200)
        self.assertEqual(resp_cancel.json()["job"]["status"], "cancelled")

        # 4. 작업 수동 재시도 API (/api/social/jobs/{job_id}/retry)
        resp_retry = client.post(f"/api/social/jobs/{test_jid}/retry?run_immediately=false")
        self.assertEqual(resp_retry.status_code, 200)
        self.assertEqual(resp_retry.json()["job"]["status"], "scheduled")


if __name__ == "__main__":
    unittest.main()
