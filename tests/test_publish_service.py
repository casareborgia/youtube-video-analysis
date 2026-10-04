"""Unit tests for Phase 4: Threads/X Publishing Orchestrator with Fake Adapters.

Phase 4 완료 조건:
- 가짜 플랫폼 어댑터로 단일·타래·부분 실패·중복 테스트 통과.
- 드라이런, 즉시 실행, 예약 실행 지원.
- 타래 중간 실패 시 성공/실패 항목 기록 및 이전 성공 항목 보존 (처음부터 재발행 방지).
- 동일 승인 요청의 중복 발행 방지 (Idempotency & 상태 펜싱).
"""

from __future__ import annotations

import tempfile
import unittest
import unittest.mock
import warnings
from pathlib import Path

# Suppress StarletteDeprecationWarning for TestClient under -W error
warnings.filterwarnings("ignore", message=".*Using `httpx` with `starlette.testclient`.*")

from fastapi.testclient import TestClient

from app import app
import content_service
import publish_service
import social_store


class FakePlatformAdapter:
    """테스트용 모의 플랫폼 어댑터 (호출 기록 및 실패 주입 지원)"""

    def __init__(self, platform_name: str, fail_on_index: int = -1):
        self.platform_name = platform_name
        self.fail_on_index = fail_on_index
        self.calls = []
        self.call_count = 0

    def publish(self, text: str, reply_to_id: str = None, image_url: str = None, media_ids: list = None):
        current_idx = self.call_count
        self.call_count += 1
        self.calls.append({
            "index": current_idx,
            "text": text,
            "reply_to_id": reply_to_id,
            "image_url": image_url,
            "media_ids": media_ids,
        })

        if current_idx == self.fail_on_index:
            raise RuntimeError(f"Simulated error on item index {current_idx}")

        generated_id = f"{self.platform_name}_post_{current_idx + 1}"
        return {
            "id": generated_id,
            "media_id": generated_id,
            "url": f"https://{self.platform_name}.com/p/{generated_id}",
        }


class PublishServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_publish_social.db"
        self.db_patch = unittest.mock.patch.object(social_store, "DEFAULT_DB_PATH", self.db_path)
        self.db_patch.start()

        self.store = social_store.SocialStore(self.db_path)
        self.client = TestClient(app)

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_single_post_publish_threads_and_x(self):
        """가짜 어댑터로 단일 포스트 발행 검증 (Threads & X)"""
        for platform in ("threads", "x"):
            fake_adapter = FakePlatformAdapter(platform)
            svc = publish_service.PublishService(
                store=self.store,
                threads_adapter=fake_adapter.publish,
                x_adapter=fake_adapter.publish,
            )

            draft = content_service.create_manual_draft(
                platform=platform,
                posts=[f"단일 테스트 포스트 on {platform}"],
                actor_account_id=f"actor_{platform}",
                dry_run=False,
                store=self.store,
            )
            job_id = draft["job"]["job_id"]

            # 1. 승인 전 실행 시도 -> 차단되어야 함
            with self.assertRaises(social_store.InvalidStateTransitionError):
                svc.execute_publish_job(job_id=job_id, worker_id="w1")

            # 2. 승인 후 실행 -> 성공
            self.store.transition_job_status(job_id, "approved")
            res = svc.execute_publish_job(job_id=job_id, worker_id="w1")

            self.assertEqual(res["status"], "succeeded")
            self.assertEqual(res["job"]["status"], "succeeded")
            self.assertEqual(len(fake_adapter.calls), 1)
            self.assertEqual(fake_adapter.calls[0]["reply_to_id"], None)

            # DB 항목 상태 확인
            items = self.store.get_job_items(job_id)
            self.assertEqual(items[0]["status"], "published")
            self.assertEqual(items[0]["platform_post_id"], f"{platform}_post_1")

    def test_thread_sequence_linking(self):
        """가짜 어댑터로 3개 타래 발행 시 reply_to_id가 연쇄 연결되는지 검증"""
        fake_threads = FakePlatformAdapter("threads")
        svc = publish_service.PublishService(
            store=self.store,
            threads_adapter=fake_threads.publish,
        )

        draft = content_service.create_manual_draft(
            platform="threads",
            posts=["1/3 첫 번째 타래", "2/3 두 번째 타래", "3/3 세 번째 타래"],
            actor_account_id="actor_th",
            dry_run=False,
            store=self.store,
        )
        job_id = draft["job"]["job_id"]
        self.store.transition_job_status(job_id, "approved")

        res = svc.execute_publish_job(job_id=job_id, worker_id="w_seq")
        self.assertEqual(res["status"], "succeeded")
        self.assertEqual(len(fake_threads.calls), 3)

        # 1번 포스트: root (reply_to_id None)
        self.assertIsNone(fake_threads.calls[0]["reply_to_id"])
        # 2번 포스트: 1번 포스트 ID를 reply_to_id로 가짐
        self.assertEqual(fake_threads.calls[1]["reply_to_id"], "threads_post_1")
        # 3번 포스트: 2번 포스트 ID를 reply_to_id로 가짐
        self.assertEqual(fake_threads.calls[2]["reply_to_id"], "threads_post_2")

    def test_partial_failure_and_resume_without_republishing(self):
        """
        Phase 4 핵심: 타래 중간 실패(Partial Failure) 처리 및
        재실행 시 처음부터 재발행하지 않고 실패 지점부터 재개(Resume) 검증
        """
        # index 1 (2번째 포스트)에서 실패하도록 설정된 어댑터
        failing_adapter = FakePlatformAdapter("x", fail_on_index=1)
        svc = publish_service.PublishService(
            store=self.store,
            x_adapter=failing_adapter.publish,
        )

        draft = content_service.create_manual_draft(
            platform="x",
            posts=["1/3 트윗 성공 예정", "2/3 트윗 실패 예정", "3/3 트윗 대기"],
            actor_account_id="actor_part",
            dry_run=False,
            store=self.store,
        )
        job_id = draft["job"]["job_id"]
        self.store.transition_job_status(job_id, "approved")

        # 1. 1차 실행: 2번째 포스트에서 실패 -> 작업은 'partial' 상태로 종료
        res1 = svc.execute_publish_job(job_id=job_id, worker_id="w_part_1")
        self.assertEqual(res1["status"], "partial")
        self.assertEqual(res1["job"]["status"], "partial")

        items_after_fail = self.store.get_job_items(job_id)
        self.assertEqual(items_after_fail[0]["status"], "published")
        self.assertEqual(items_after_fail[0]["platform_post_id"], "x_post_1")

        self.assertEqual(items_after_fail[1]["status"], "failed")
        self.assertIn("Simulated error", items_after_fail[1]["error_message"])

        self.assertEqual(items_after_fail[2]["status"], "pending")

        # 2. 문제 해결 후 2차 실행 (어댑터 정상화)
        healthy_adapter = FakePlatformAdapter("x", fail_on_index=-1)
        svc_healthy = publish_service.PublishService(
            store=self.store,
            x_adapter=healthy_adapter.publish,
        )

        res2 = svc_healthy.execute_publish_job(job_id=job_id, worker_id="w_part_2")
        self.assertEqual(res2["status"], "succeeded")
        self.assertEqual(res2["job"]["status"], "succeeded")

        # 중요 검증: 1번 포스트는 healthy_adapter를 호출하지 않고 스킵됨!
        # healthy_adapter는 2번 포스트(index 1)와 3번 포스트(index 2) 총 2회만 호출되어야 함!
        self.assertEqual(len(healthy_adapter.calls), 2)
        # 2번 포스트 발행 시 1번 성공 포스트 ID('x_post_1')를 부모로 이어받음
        self.assertEqual(healthy_adapter.calls[0]["reply_to_id"], "x_post_1")
        self.assertEqual(healthy_adapter.calls[0]["text"], "2/3 트윗 실패 예정")

        # 최종 3개 아이템 모두 published 확인
        final_items = self.store.get_job_items(job_id)
        self.assertTrue(all(it["status"] == "published" for it in final_items))

    def test_duplicate_execution_prevention(self):
        """동일 승인 요청의 중복 발행 방지 검증"""
        adapter = FakePlatformAdapter("threads")
        svc = publish_service.PublishService(
            store=self.store,
            threads_adapter=adapter.publish,
        )

        draft = content_service.create_manual_draft(
            platform="threads",
            posts=["중복 방지 테스트 포스트"],
            actor_account_id="actor_dedup",
            dry_run=False,
            store=self.store,
        )
        job_id = draft["job"]["job_id"]
        self.store.transition_job_status(job_id, "approved")

        # 1차 성공
        res = svc.execute_publish_job(job_id=job_id, worker_id="w_main")
        self.assertEqual(res["status"], "succeeded")
        self.assertEqual(len(adapter.calls), 1)

        # 이미 succeeded인 작업을 다시 실행하려 하면 차단되어야 함
        with self.assertRaises(social_store.InvalidStateTransitionError):
            svc.execute_publish_job(job_id=job_id, worker_id="w_second")

        # 어댑터가 다시 호출되지 않았음을 보증
        self.assertEqual(len(adapter.calls), 1)

    def test_dry_run_execution(self):
        """드라이런 모드에서는 외부 어댑터 호출 없이 가상 ID로 안전 완료"""
        adapter = FakePlatformAdapter("x")
        svc = publish_service.PublishService(
            store=self.store,
            x_adapter=adapter.publish,
        )

        draft = content_service.create_manual_draft(
            platform="x",
            posts=["드라이런 1", "드라이런 2"],
            actor_account_id="actor_dry",
            dry_run=True,
            store=self.store,
        )
        job_id = draft["job"]["job_id"]
        self.store.transition_job_status(job_id, "approved")

        res = svc.execute_publish_job(job_id=job_id, worker_id="w_dry")
        self.assertEqual(res["status"], "succeeded")
        # 어댑터는 0번 호출되어야 함
        self.assertEqual(len(adapter.calls), 0)

        items = self.store.get_job_items(job_id)
        self.assertTrue(items[0]["platform_post_id"].startswith("mock_x_"))
        self.assertTrue(items[1]["platform_post_id"].startswith("mock_x_"))

    def test_api_publish_and_schedule_endpoints(self):
        # 1. 수동 초안 생성 및 승인
        draft = content_service.create_manual_draft(
            platform="threads",
            posts=["API 발행 테스트"],
            actor_account_id="api_actor",
            dry_run=True,
            store=self.store,
        )
        job_id = draft["job"]["job_id"]
        self.store.transition_job_status(job_id, "approved")

        # 2. POST /api/social/publish/{job_id} (드라이런)
        resp_pub = self.client.post(
            f"/api/social/publish/{job_id}",
            json={"dry_run": True, "worker_id": "test_api_worker"},
        )
        self.assertEqual(resp_pub.status_code, 200)
        self.assertEqual(resp_pub.json()["status"], "succeeded")

        # 3. POST /api/social/jobs/{job_id}/schedule
        draft_sched = content_service.create_manual_draft(
            platform="threads",
            posts=["예약 테스트 포스트"],
            actor_account_id="api_actor",
            dry_run=True,
            store=self.store,
        )
        job_id_sched = draft_sched["job"]["job_id"]
        self.store.transition_job_status(job_id_sched, "approved")

        future_ts = 1800000000
        resp_sched = self.client.post(
            f"/api/social/jobs/{job_id_sched}/schedule",
            json={"scheduled_at": future_ts},
        )
        self.assertEqual(resp_sched.status_code, 200)
        self.assertEqual(resp_sched.json()["job"]["status"], "scheduled")
        self.assertEqual(resp_sched.json()["job"]["scheduled_at"], future_ts)


if __name__ == "__main__":
    unittest.main()
