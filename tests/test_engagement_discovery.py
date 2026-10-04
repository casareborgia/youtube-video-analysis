"""EngagementDiscoveryService 및 신규 발굴 필터 API 통합 테스트."""

import time
import unittest
from fastapi.testclient import TestClient

import app
import threads_client
from services.engagement_discovery import EngagementDiscoveryService
from services.social_relationship_service import SocialRelationshipService
from social_store import SocialStore


class TestEngagementDiscovery(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app.app)
        self.service = EngagementDiscoveryService()
        self.store = SocialStore()
        self.rel_service = SocialRelationshipService(store=self.store)

    def test_discover_threads_targets_structure(self):
        """탐색 결과 딕셔너리 구조, 카운트 및 요약 메트릭 검증."""
        res = self.service.discover_targets(platform="threads", topic="스하리", limit=5)
        self.assertIsInstance(res, dict)
        self.assertIn("targets", res)
        self.assertIn("summary", res)
        targets = res["targets"]
        self.assertTrue(len(targets) > 0)
        self.assertLessEqual(len(targets), 5)

        first = targets[0]
        self.assertIn("account_id", first)
        self.assertIn("username", first)
        self.assertIn("post_id", first)
        self.assertIn("post_text", first)
        self.assertIn("is_new_candidate", first)
        self.assertTrue(first["is_new_candidate"])

        # summary 산술 일치 검증: scanned == included + excluded
        summary = res["summary"]
        self.assertEqual(summary["scanned"], summary["included"] + summary["excluded"])

    def test_account_level_exclusion_by_relationship(self):
        """댓글 작성자 등 기존 관계가 형성된 계정은 신규 발굴 탐색 시 자동 제외되어야 함."""
        # 1. 특정 시드 계정(itemcurator_threads)을 댓글 작성자로 관계 캐시에 등록
        target_uname = "itemcurator_threads"
        conf = threads_client.load_config()
        actor = conf.get("username") or "me"
        self.rel_service.record_commenter(
            platform="threads",
            actor_account_id=actor,
            commenter_username=target_uname,
            post_id="post_dummy_123",
        )

        # 2. 신규 발굴 모드(exclude_existing_relationships=True)로 탐색
        res_filtered = self.service.discover_targets(
            platform="threads",
            topic="스하리",
            limit=10,
            exclude_existing_relationships=True,
            actor_account_id=actor,
        )
        filtered_usernames = [t["username"].lower() for t in res_filtered["targets"]]
        self.assertNotIn(target_uname.lower(), filtered_usernames)
        self.assertGreaterEqual(res_filtered["summary"]["excluded_by_reason"].get("commented_on_my_content", 0), 1)

        # 3. 신규 발굴 모드 해제(exclude_existing_relationships=False) 시 다시 후보로 포함될 수 있음
        res_unfiltered = self.service.discover_targets(
            platform="threads",
            topic="스하리",
            limit=10,
            exclude_existing_relationships=False,
            actor_account_id=actor,
        )
        unfiltered_usernames = [t["username"].lower() for t in res_unfiltered["targets"]]
        self.assertIn(target_uname.lower(), unfiltered_usernames)

    def test_api_discover_endpoint_contract(self):
        """GET /api/engagement/discover 엔드포인트 기본값 및 summary 응답 검증."""
        res = self.client.get("/api/engagement/discover?platform=threads&topic=스하리&limit=6&exclude_existing_relationships=true")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("platform"), "threads")
        self.assertEqual(data.get("count"), len(data.get("targets", [])))
        self.assertIn("summary", data)
        self.assertIn("scanned", data["summary"])
        self.assertIn("included", data["summary"])
        self.assertIn("excluded", data["summary"])

    def test_preflight_validation_blocks_existing_relationships_in_auto_run(self):
        """클라이언트가 기존 관계 대상을 직접 auto-run 요청에 주입해도 서버에서 차단되어야 함."""
        blocked_user = "known_friend_999"
        self.rel_service.record_reply_sent(
            platform="threads",
            actor_account_id="me",
            target_username=blocked_user,
            post_id="post_999",
        )

        res = self.client.post(
            "/api/engagement/auto-run",
            json={
                "platform": "threads",
                "targets": [
                    {
                        "account_id": blocked_user,
                        "username": blocked_user,
                        "post_id": "post_fake_888",
                        "post_url": f"https://www.threads.net/@{blocked_user}/post/post_fake_888",
                    }
                ],
                "actions": ["like"],
                "dry_run": True,
                "exclude_existing_relationships": True,
                "actor_account_id": "me",
            },
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "success")
        # 모든 대상이 제외되었으므로 processed=0, skipped=1이어야 함
        self.assertEqual(data.get("processed"), 0)
        self.assertEqual(data.get("skipped"), 1)
        skipped_details = data.get("skipped_details", [])
        self.assertEqual(len(skipped_details), 1)
        self.assertEqual(skipped_details[0]["status"], "skipped_existing_relationship")
        self.assertEqual(skipped_details[0]["reason"], "replied_by_me")

    def test_api_auto_run_dry_run_standard(self):
        """일반 모의 시뮬레이션(Dry Run) 정상 동작 검증."""
        res = self.client.post(
            "/api/engagement/auto-run",
            json={
                "platform": "threads",
                "topic": "스하리",
                "actions": ["like", "repost"],
                "dry_run": True,
                "confirm_live": False,
                "limit": 3,
                "exclude_existing_relationships": True,
            },
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "success")
        result = data.get("result", {})
        if "results" in result:
            for item in result["results"]:
                self.assertIn(item.get("status"), ("dry_run", "skipped_duplicate"))


if __name__ == "__main__":
    unittest.main()
