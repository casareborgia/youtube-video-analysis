"""Unit tests for Phase 5: Comment/Reply Automation.

Phase 5 완료 조건:
- 승인 누락 차단 (Unapproved execution strictly blocked)
- 중복 방지 (Duplicate reply prevention on same target comment)
- 부분 실패 (Partial failure isolation without crashing batch)
- 권한 오류 (Permission required / Unsupported reporting without unauthorized fallback)
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
import reply_service
import social_store


class FakeReplyAdapter:
    """테스트용 모의 답글 발행 어댑터"""

    def __init__(self, platform_name: str, fail_on_comment_ids: set = None):
        self.platform_name = platform_name
        self.fail_on_comment_ids = fail_on_comment_ids or set()
        self.calls = []

    def publish(self, text: str, reply_to_id: str = None, **kwargs):
        self.calls.append({"text": text, "reply_to_id": reply_to_id})
        if reply_to_id in self.fail_on_comment_ids:
            raise RuntimeError(f"Simulated reply failure on {reply_to_id}")

        gen_id = f"reply_{self.platform_name}_{len(self.calls)}"
        return {"id": gen_id, "media_id": gen_id, "url": f"https://{self.platform_name}.com/r/{gen_id}"}


class ReplyServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_reply_social.db"
        self.db_patch = unittest.mock.patch.object(social_store, "DEFAULT_DB_PATH", self.db_path)
        self.db_patch.start()

        self.store = social_store.SocialStore(self.db_path)
        self.client = TestClient(app)

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_unapproved_reply_execution_blocked(self):
        """Phase 5 완료조건 1: 승인되지 않은 답글 작업 실행 엄격 차단 검증"""
        adapter = FakeReplyAdapter("threads")
        svc = reply_service.ReplyService(store=self.store, threads_adapter=adapter.publish)

        # 1. Draft 상태 답글 생성 (approved_at = 0)
        comments = [{"id": "comm_unapp_1", "text": "좋은 글이네요!"}]
        drafts = svc.create_reply_drafts_from_comments(
            platform="threads",
            comments=comments,
            actor_account_id="actor_rep_1",
            dry_run=False,
        )
        job_id = drafts[0]["job_id"]

        # 2. 미승인 상태에서 배치 실행 시도
        res = svc.execute_batch_replies(job_ids=[job_id], worker_id="w_rep")

        self.assertEqual(res["total_processed"], 1)
        self.assertEqual(res["success_count"], 0)
        self.assertEqual(res["blocked_count"], 1)
        self.assertEqual(res["results"][0]["status"], "unapproved_blocked")

        # 어댑터가 전혀 호출되지 않았음을 보증
        self.assertEqual(len(adapter.calls), 0)

        # 3. 승인 후 실행 -> 성공
        self.store.transition_job_status(job_id, "approved")
        res_approved = svc.execute_batch_replies(job_ids=[job_id], worker_id="w_rep")
        self.assertEqual(res_approved["success_count"], 1)
        self.assertEqual(len(adapter.calls), 1)

    def test_duplicate_reply_prevention(self):
        """Phase 5 완료조건 2: 동일 원댓글 대상 중복 답글 방지 검증"""
        adapter = FakeReplyAdapter("x")
        svc = reply_service.ReplyService(store=self.store, x_adapter=adapter.publish)

        # 댓글 1개에 대해 2개의 초안 등록 시도
        comments = [{"id": "comm_dup_999", "text": "핵심 팁 감사해요!"}]
        drafts = svc.create_reply_drafts_from_comments(
            platform="x",
            comments=comments,
            actor_account_id="actor_rep_2",
            dry_run=False,
        )
        job_id = drafts[0]["job_id"]
        self.store.transition_job_status(job_id, "approved")

        # 1차 실행 성공
        res1 = svc.execute_batch_replies(job_ids=[job_id], worker_id="w_rep")
        self.assertEqual(res1["success_count"], 1)
        self.assertEqual(len(adapter.calls), 1)

        # 동일 원댓글에 대해 또 다른 작업을 만들어 승인 후 실행 시도
        job2 = self.store.create_job(
            platform="x",
            job_type="reply",
            actor_account_id="actor_rep_2",
            target_id="comm_dup_999",
            dry_run=False,
        )
        self.store.add_job_items(job2["job_id"], [{"item_index": 0, "content": "중복 답글 시도"}])
        self.store.transition_job_status(job2["job_id"], "approved")

        res2 = svc.execute_batch_replies(job_ids=[job2["job_id"]], worker_id="w_rep")
        self.assertEqual(res2["success_count"], 0)
        self.assertEqual(res2["blocked_count"], 1)
        self.assertEqual(res2["results"][0]["status"], "skipped_duplicate")

        # 어댑터가 추가 호출되지 않았음을 보증
        self.assertEqual(len(adapter.calls), 1)

    def test_partial_failure_isolation_in_batch(self):
        """Phase 5 완료조건 3: 배치 답글 중 특정 댓글 실패 시 부분 실패 격리 검증"""
        # comm_fail_2 에서만 에러가 발생하도록 설정
        failing_adapter = FakeReplyAdapter("threads", fail_on_comment_ids={"comm_fail_2"})
        svc = reply_service.ReplyService(store=self.store, threads_adapter=failing_adapter.publish)

        comments = [
            {"id": "comm_ok_1", "text": "댓글 1"},
            {"id": "comm_fail_2", "text": "댓글 2 (실패 대상)"},
            {"id": "comm_ok_3", "text": "댓글 3"},
        ]
        drafts = svc.create_reply_drafts_from_comments(
            platform="threads",
            comments=comments,
            actor_account_id="actor_rep_3",
            dry_run=False,
        )
        job_ids = [d["job_id"] for d in drafts]
        for jid in job_ids:
            self.store.transition_job_status(jid, "approved")

        # 배치 실행
        res = svc.execute_batch_replies(job_ids=job_ids, worker_id="w_rep")

        self.assertEqual(res["total_processed"], 3)
        self.assertEqual(res["success_count"], 2)  # 1번, 3번 성공
        self.assertEqual(res["failure_count"], 1)  # 2번 실패

        statuses = [r["status"] for r in res["results"]]
        self.assertEqual(statuses, ["success", "failed", "success"])

        # 2번 실패가 3번 성공을 방해하지 않았음을 검증
        self.assertEqual(len(failing_adapter.calls), 3)

    def test_permission_error_and_unsupported_reporting(self):
        """Phase 5 완료조건 4: 권한 부족 및 미지원 시 안전한 에러 보고 검증"""
        # 1. Threads 권한 오류 모의
        def mock_threads_perm_error(post_id):
            return {
                "platform": "threads",
                "status": "permission_required",
                "code": "PERMISSION_REQUIRED",
                "message": "threads_read_replies scope required",
                "replies": [],
            }

        svc = reply_service.ReplyService(store=self.store, threads_fetcher=mock_threads_perm_error)
        res_th = svc.fetch_post_replies("threads", "post_123")
        self.assertEqual(res_th["status"], "permission_required")
        self.assertEqual(res_th["code"], "PERMISSION_REQUIRED")

        # 2. X 미지원 보고 모의
        def mock_x_unsupported(post_id):
            return {
                "platform": "x",
                "status": "unsupported",
                "code": "UNSUPPORTED",
                "message": "X API Free tier does not support reply search",
                "replies": [],
            }

        svc_x = reply_service.ReplyService(store=self.store, x_fetcher=mock_x_unsupported)
        res_x = svc_x.fetch_post_replies("x", "post_456")
        self.assertEqual(res_x["status"], "unsupported")
        self.assertEqual(res_x["code"], "UNSUPPORTED")

    def test_batch_preview_functionality(self):
        """배치 실행 전 미리보기(승인 여부 집계) 검증"""
        svc = reply_service.ReplyService(store=self.store)
        comments = [
            {"id": "comm_prev_1", "text": "댓글 1"},
            {"id": "comm_prev_2", "text": "댓글 2"},
        ]
        drafts = svc.create_reply_drafts_from_comments(
            platform="threads",
            comments=comments,
            actor_account_id="actor_prev",
        )
        # 1번만 승인
        self.store.transition_job_status(drafts[0]["job_id"], "approved")

        preview = svc.preview_batch_replies([drafts[0]["job_id"], drafts[1]["job_id"]])
        self.assertEqual(preview["total_requested"], 2)
        self.assertEqual(preview["approved_count"], 1)
        self.assertEqual(preview["unapproved_count"], 1)
        self.assertTrue(preview["can_execute"])

    def test_api_reply_endpoints(self):
        # 1. POST /api/social/replies/drafts-from-comments
        resp_draft = self.client.post(
            "/api/social/replies/drafts-from-comments",
            json={
                "platform": "threads",
                "comments": [{"id": "api_comm_1", "text": "유익한 영상이네요!"}],
                "actor_account_id": "api_user",
                "tone": "friendly",
                "dry_run": True,
            },
        )
        self.assertEqual(resp_draft.status_code, 200)
        drafts = resp_draft.json()["drafts"]
        job_id = drafts[0]["job_id"]

        # 2. POST /api/social/replies/batch-preview
        resp_prev = self.client.post(
            "/api/social/replies/batch-preview",
            json={"job_ids": [job_id]},
        )
        self.assertEqual(resp_prev.status_code, 200)
        self.assertEqual(resp_prev.json()["preview"]["unapproved_count"], 1)

        # 3. 승인 후 POST /api/social/replies/batch-execute (드라이런)
        self.store.transition_job_status(job_id, "approved")
        resp_exec = self.client.post(
            "/api/social/replies/batch-execute",
            json={"job_ids": [job_id], "dry_run": True},
        )
        self.assertEqual(resp_exec.status_code, 200)
        self.assertEqual(resp_exec.json()["result"]["success_count"], 1)


if __name__ == "__main__":
    unittest.main()
