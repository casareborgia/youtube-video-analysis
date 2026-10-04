import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import app
from engagement_automation import (
    EngagementAutomationService,
    EngagementError,
    EngagementPolicy,
    EngagementStore,
    EngagementTarget,
    ThreadsApiEngagementClient,
    UnsupportedAction,
    XApiEngagementClient,
)
import social_store


class EngagementAutomationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "events.db"
        self.store = EngagementStore(self.db_path)
        self.policy = EngagementPolicy(delay_seconds=0)
        self.service = EngagementAutomationService(store=self.store, policy=self.policy)
        self.target = EngagementTarget(
            platform="x",
            post_id="2105629134760370403",
            account_id="1453335049198202883",
            post_url="https://x.com/example/status/2105629134760370403",
            profile_url="https://x.com/example",
        )
        self.threads_target = EngagementTarget(
            platform="threads",
            post_id="post_threads_123",
            account_id="acc_threads_456",
            post_url="https://threads.net/@example/post/post_threads_123",
            profile_url="https://threads.net/@example",
        )

    def tearDown(self):
        self.tmp.cleanup()

    # ==========================================
    # 기본 입력 검증 및 드라이런 검증
    # ==========================================
    def test_dry_run_never_constructs_live_client(self):
        self.service._client = lambda *_: self.fail("live client must not be created")
        result = self.service.execute([self.target], dry_run=True)
        self.assertEqual([r["status"] for r in result["results"]], ["dry_run"] * 3)

    def test_same_target_is_not_processed_twice(self):
        self.service.execute([self.target], actions=["like"], dry_run=True)
        result = self.service.execute([self.target], actions=["like"], dry_run=True)
        self.assertEqual(result["results"][0]["status"], "skipped_duplicate")

    def test_rejects_non_platform_url(self):
        bad = EngagementTarget(
            platform="threads",
            post_id="abc123",
            account_id="example",
            post_url="https://example.com/post/abc123",
        )
        with self.assertRaises(ValueError):
            self.service.execute([bad], dry_run=True)

    def test_rejects_url_for_different_platform(self):
        bad = EngagementTarget(
            platform="x",
            post_id="abc123",
            account_id="example",
            post_url="https://www.threads.com/@example/post/abc123",
        )
        with self.assertRaises(ValueError):
            self.service.execute([bad], dry_run=True)

    def test_request_target_limit(self):
        targets = [
            EngagementTarget("x", str(i), f"account{i}")
            for i in range(self.service.policy.max_targets_per_request + 1)
        ]
        with self.assertRaises(ValueError):
            self.service.execute(targets, dry_run=True)

    def test_rejects_empty_or_duplicate_actions(self):
        with self.assertRaises(ValueError):
            self.service.execute([self.target], actions=[], dry_run=True)
        with self.assertRaises(ValueError):
            self.service.execute([self.target], actions=["like", "like"], dry_run=True)

    # ==========================================
    # Phase 6: Threads 공식 API vs 웹 폴백 구분
    # ==========================================
    def test_threads_api_repost_success(self):
        """Threads 공식 API는 repost 동작만 지원하며, 성공 시 success와 official_api 반환."""
        client = ThreadsApiEngagementClient(token="mock_token")
        with patch("threads_client.repost_post") as mock_repost:
            mock_repost.return_value = {"id": "repost_999"}
            res = client.perform("repost", self.threads_target)
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["via"], "official_api")
            mock_repost.assert_called_once_with(post_id=self.threads_target.post_id, access_token="mock_token")

    def test_threads_api_unsupported_actions_fallback_web_required(self):
        """Threads 공식 API 모드로 follow나 like 요청 시 UnsupportedAction이 발생하고 서비스에서 web_required로 안전 격리."""
        client = ThreadsApiEngagementClient(token="mock_token")
        with self.assertRaises(UnsupportedAction):
            client.perform("like", self.threads_target)
        with self.assertRaises(UnsupportedAction):
            client.perform("follow", self.threads_target)

        # 서비스를 통한 실행 시 web_required로 격리 확인
        self.service._client = lambda platform, fallback: client
        res = self.service.execute([self.threads_target], actions=["like", "follow"], dry_run=False, use_web_fallback=False)
        statuses = [r["status"] for r in res["results"]]
        self.assertEqual(statuses, ["web_required", "web_required"])

    def test_threads_web_fallback_calls_web_client(self):
        """use_web_fallback=True일 경우 WebEngagementClient가 호출되어 웹 방식으로 처리."""
        mock_web = MagicMock()
        mock_web.perform.return_value = {"status": "success", "via": "web"}
        self.service._client = lambda platform, fallback: mock_web if fallback else None

        res = self.service.execute([self.threads_target], actions=["like"], dry_run=False, use_web_fallback=True)
        self.assertEqual(res["results"][0]["status"], "success")
        mock_web.perform.assert_called_once_with("like", self.threads_target)

    # ==========================================
    # Phase 6: X 공식 API 우선 및 이미 완료된 상태(토글 방지)
    # ==========================================
    def test_x_api_actions_success(self):
        """X 공식 API 모드로 follow, like, repost 동작을 각각 올바르게 호출."""
        client = XApiEngagementClient(token="mock_x_token", acting_user_id="act_user_1")
        with patch("x_client.follow_user") as mock_follow, \
             patch("x_client.like_tweet") as mock_like, \
             patch("x_client.retweet") as mock_rt:
            mock_follow.return_value = {"following": True}
            mock_like.return_value = {"liked": True}
            mock_rt.return_value = {"retweeted": True}

            res_follow = client.perform("follow", self.target)
            res_like = client.perform("like", self.target)
            res_rt = client.perform("repost", self.target)

            self.assertEqual(res_follow["status"], "success")
            self.assertEqual(res_like["status"], "success")
            self.assertEqual(res_rt["status"], "success")
            mock_follow.assert_called_once_with(target_user_id=self.target.account_id, acting_user_id="act_user_1", access_token="mock_x_token")
            mock_like.assert_called_once_with(tweet_id=self.target.post_id, acting_user_id="act_user_1", access_token="mock_x_token")
            mock_rt.assert_called_once_with(tweet_id=self.target.post_id, acting_user_id="act_user_1", access_token="mock_x_token")

    def test_x_api_already_done_prevents_toggle(self):
        """X API에서 이미 팔로우/좋아요/리트윗된 상태를 알리는 에러 발생 시 already_done으로 처리하여 토글/취소 방지."""
        import x_client
        client = XApiEngagementClient(token="mock_x_token", acting_user_id="act_user_1")
        with patch("x_client.like_tweet") as mock_like:
            mock_like.side_effect = x_client.XClientError("Already liked this tweet", code="ALREADY_DONE")
            res = client.perform("like", self.target)
            self.assertEqual(res["status"], "already_done")
            self.assertEqual(res["via"], "official_api")

    # ==========================================
    # Phase 6: 공통 작업 모델(social_jobs) 및 상태 머신 연동
    # ==========================================
    def test_common_job_model_lifecycle_succeeded(self):
        """실제 실행 시 social_jobs에 engagement 작업이 등록되고 succeeded 상태로 완료."""
        mock_client = MagicMock()
        mock_client.perform.return_value = {"status": "success", "via": "official_api"}
        self.service._client = lambda platform, fallback: mock_client

        res = self.service.execute([self.target], actions=["like"], dry_run=False)
        self.assertIn("job_id", res)
        job_id = res["job_id"]

        job = self.store.social_store.get_job(job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job["job_type"], "engagement")
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["platform"], "x")

        # job_items 등록 확인
        items = self.store.social_store.list_job_items(job_id)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["status"], "success")

    def test_common_job_model_partial_failure(self):
        """일부 성공, 일부 실패(예: web_required) 시 작업 상태가 partially_failed로 격리."""
        def mock_perform(action, target):
            if action == "like":
                return {"status": "success"}
            raise UnsupportedAction("웹 브라우저가 필요합니다.")

        mock_client = MagicMock()
        mock_client.perform.side_effect = mock_perform
        self.service._client = lambda platform, fallback: mock_client

        res = self.service.execute([self.target], actions=["like", "follow"], dry_run=False)
        job_id = res["job_id"]

        job = self.store.social_store.get_job(job_id)
        self.assertEqual(job["status"], "partially_failed")

        items = self.store.social_store.list_job_items(job_id)
        self.assertEqual(len(items), 2)
        statuses = [it["status"] for it in items]
        self.assertIn("success", statuses)
        self.assertIn("web_required", statuses)

    def test_daily_limits_enforced_in_common_store(self):
        """일일 동작별 한도 및 전체 한도 초과 시 blocked_quota 반환."""
        self.policy.daily_total = 2
        self.policy.daily_like = 1

        mock_client = MagicMock()
        mock_client.perform.return_value = {"status": "success"}
        self.service._client = lambda platform, fallback: mock_client

        t1 = EngagementTarget("x", "post1", "user1")
        t2 = EngagementTarget("x", "post2", "user2")

        # 1번째 like 성공
        res1 = self.service.execute([t1], actions=["like"], dry_run=False)
        self.assertEqual(res1["results"][0]["status"], "success")

        # 2번째 like는 daily_like 한도(1) 초과로 blocked_quota
        res2 = self.service.execute([t2], actions=["like"], dry_run=False)
        self.assertEqual(res2["results"][0]["status"], "blocked_quota")
        self.assertEqual(res2["results"][0]["detail"], "daily_like")

    # ==========================================
    # Phase 6: API 계약 엔드포인트 통합 검증
    # ==========================================
    def test_api_endpoints_contract(self):
        client = TestClient(app)

        # 1. /api/social/capabilities
        resp_cap = client.get("/api/social/capabilities")
        self.assertEqual(resp_cap.status_code, 200)
        cap_data = resp_cap.json()
        self.assertIn("limits", cap_data)
        self.assertEqual(cap_data["limits"]["daily_total"], 30)
        self.assertEqual(cap_data["limits"]["daily_follow"], 10)
        self.assertEqual(cap_data["limits"]["daily_like"], 25)
        self.assertEqual(cap_data["limits"]["daily_repost"], 10)

        # 2. /api/social/history
        resp_hist = client.get("/api/social/history")
        self.assertEqual(resp_hist.status_code, 200)
        self.assertEqual(resp_hist.json()["status"], "success")

        # 3. /api/social/engagement/run (dry_run 검증)
        import uuid
        uid = uuid.uuid4().hex[:8]
        payload = {
            "targets": [
                {
                    "platform": "x",
                    "post_id": f"post_api_{uid}",
                    "account_id": f"acc_api_{uid}",
                }
            ],
            "actions": ["like"],
            "dry_run": True,
        }
        resp_run = client.post("/api/social/engagement/run", json=payload)
        self.assertEqual(resp_run.status_code, 200)
        data = resp_run.json()
        self.assertEqual(data["status"], "success")
        self.assertTrue(data["dry_run"])
        self.assertEqual(data["results"][0]["status"], "dry_run")

        # 4. confirm_live 누락 차단 검증
        payload_live = {
            "targets": [
                {
                    "platform": "x",
                    "post_id": f"post_api_live_{uid}",
                    "account_id": f"acc_api_live_{uid}",
                }
            ],
            "actions": ["like"],
            "dry_run": False,
            "confirm_live": False,
        }
        resp_fail = client.post("/api/social/engagement/run", json=payload_live)
        self.assertEqual(resp_fail.status_code, 400)


if __name__ == "__main__":
    unittest.main()
