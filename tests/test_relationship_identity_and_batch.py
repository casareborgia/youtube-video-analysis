"""코덱스 지적사항 검증: 식별자 리졸버, 빈 actor 실행 재검증, X 플랫폼 및 영구 제외 회귀 테스트."""

import os
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import app
from services.social_relationship_service import SocialRelationshipService
from social_store import SocialStore


class TestRelationshipIdentityAndBatch(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_social.db")
        self.store = SocialStore(path=self.db_path)
        self.service = SocialRelationshipService(store=self.store)

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("threads_client.load_config")
    def test_resolve_actor_identities_threads(self, mock_load):
        """Threads 플랫폼의 설정으로부터 숫자 ID와 username을 포함한 식별자 풀 도출 검증."""
        mock_load.return_value = {
            "username": "threads_hero",
            "user_id": "998877665544",
        }
        res = self.service.resolve_actor_identities(platform="threads")
        self.assertIn("998877665544", res["actor_identity_pool"])
        self.assertIn("threads_hero", res["actor_identity_pool"])
        self.assertIn("me", res["actor_identity_pool"])
        self.assertEqual(res["primary_actor"], "998877665544")

    @patch("x_client.load_config")
    def test_resolve_actor_identities_x(self, mock_load):
        """X 플랫폼의 설정으로부터 숫자 ID와 username을 포함한 식별자 풀 도출 검증."""
        mock_load.return_value = {
            "username": "x_master",
            "user_id": "1122334455",
        }
        res = self.service.resolve_actor_identities(platform="x")
        self.assertIn("1122334455", res["actor_identity_pool"])
        self.assertIn("x_master", res["actor_identity_pool"])
        self.assertIn("me", res["actor_identity_pool"])
        self.assertEqual(res["primary_actor"], "1122334455")

    @patch("threads_client.load_config")
    def test_batch_register_deduplication_and_permanent_none(self, mock_load):
        """배치 등록 시 중복 제거 및 expires_in_days=None일 때 expires_at=None(영구 제외) 저장 검증."""
        mock_load.return_value = {
            "username": "my_account",
            "user_id": "12345678",
        }
        # 중복 입력 (@ 포함, 대소문자 혼합)
        usernames = ["@Follower1", "follower1", "FOLLOWER1", "@follower2", "  "]
        count = self.service.batch_register_known_followers(
            platform="threads",
            actor_account_id=None,  # 자동 도출
            usernames=usernames,
            expires_in_days=None,
        )
        self.assertEqual(count, 2)  # follower1, follower2 총 2명만 등록

        # DB 레코드 직접 검증
        records = self.store.list_relationships(
            platform="threads",
            actor_account_id="12345678",
        )
        self.assertEqual(len(records), 2)
        for r in records:
            self.assertEqual(r["relationship_type"], "known_follower")
            self.assertEqual(r["source"], "manual_import")
            self.assertIsNone(r["expires_at"], "영구 제외이므로 expires_at은 None이어야 함")

    @patch("threads_client.load_config")
    def test_empty_actor_evaluates_and_excludes_numeric_id_records(self, mock_load):
        """[코덱스 지적 1번 검증] DB에 숫자 ID로 저장된 관계가 actor_account_id=""인 경우에도 자동 제외되는지 검증."""
        mock_load.return_value = {
            "username": "my_account",
            "user_id": "99990000",
        }
        # 1. DB에 숫자 ID(99990000)를 actor로 하여 댓글 작성자 관계 저장
        self.store.upsert_relationship(
            platform="threads",
            actor_account_id="99990000",
            target_account_key="target_friend",
            relationship_type="commented_on_my_content",
            source="post_reply",
        )

        # 2. 클라이언트가 actor_account_id="" (빈 문자열)로 재검증 요청을 보내도 매칭되어야 함
        eval_res = self.service.evaluate_target(
            platform="threads",
            actor_account_id="",  # 빈 문자열!
            target_username="target_friend",
        )
        self.assertTrue(eval_res.excluded, "숫자 ID로 저장된 관계라도 빈 actor 요청 시 자동 리졸브되어 제외되어야 함")
        self.assertEqual(eval_res.reason, "commented_on_my_content")

    @patch("x_client.load_config")
    def test_x_platform_batch_register_and_matching(self, mock_load):
        """[코덱스 지적 2번 검증] X 플랫폼에서 수동 팔로워 등록 후 정상적으로 탐색/실행에서 제외되는지 검증."""
        mock_load.return_value = {
            "username": "x_author",
            "user_id": "55554444",
        }
        # 1. X 플랫폼에 팔로워 일괄 등록 (actor 명시 없이)
        count = self.service.batch_register_known_followers(
            platform="x",
            actor_account_id="",
            usernames=["x_buddy1", "x_buddy2"],
            expires_in_days=None,
        )
        self.assertEqual(count, 2)

        # 2. X 플랫폼에서 빈 actor 또는 사용자명으로 평가 시 정상 제외되는지 확인
        eval_res = self.service.evaluate_target(
            platform="x",
            actor_account_id="",
            target_username="x_buddy1",
        )
        self.assertTrue(eval_res.excluded)
        self.assertEqual(eval_res.reason, "known_follower")

    @patch("threads_client.load_config")
    def test_api_batch_register_endpoint_isolated_from_production_db(self, mock_load):
        """FastAPI 엔드포인트를 통한 팔로워 일괄 등록 검증 (운영 DB 오염 없이 임시 DB에만 기록)."""
        mock_load.return_value = {
            "username": "api_test_user",
            "user_id": "88887777",
        }
        client = TestClient(app)
        # SocialRelationshipService가 self.store(임시 DB)를 사용하도록 완전히 격리
        with patch("services.social_relationship_service.SocialRelationshipService", side_effect=lambda *a, **kw: SocialRelationshipService(store=self.store)):
            res = client.post(
                "/api/engagement/relationships/batch-register",
                json={
                    "platform": "threads",
                    "usernames": ["@api_fan1", "@api_fan2", "api_fan1"],
                    "expires_in_days": None,
                },
            )
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["registered_count"], 2)

        # 1. 임시 DB에는 2개 레코드가 정상 기록되었는지 검증
        temp_records = self.store.list_relationships(platform="threads", actor_account_id="88887777")
        self.assertEqual(len(temp_records), 2)

        # 2. 실제 운영 DB('data/social_engagement.db')에는 단 한 줄도 쓰이지 않았음을 직접 검증
        if os.path.exists("data/social_engagement.db"):
            conn = sqlite3.connect("data/social_engagement.db")
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM social_relationships WHERE actor_account_id = '88887777'")
            prod_count = cur.fetchone()[0]
            conn.close()
            self.assertEqual(prod_count, 0, "실제 운영 DB에는 테스트 데이터가 일절 쓰이지 않아야 함")

    @patch("threads_client.load_config")
    @patch("engagement_automation.get_service")
    def test_api_run_skips_existing_relationship_without_executing_service(self, mock_get_service, mock_load):
        """기존 관계 계정에 대해 /api/engagement/run 요청 시 서비스 execute가 호출되지 않고 안전 스킵되는지 mock 검증."""
        mock_load.return_value = {
            "username": "my_run_user",
            "user_id": "77776666",
        }
        # 1. 임시 DB에 대상 유저를 기존 관계로 등록
        self.store.upsert_relationship(
            platform="threads",
            actor_account_id="77776666",
            target_account_key="already_friend",
            relationship_type="known_follower",
            source="manual_import",
        )

        mock_service_instance = MagicMock()
        mock_get_service.return_value = mock_service_instance

        client = TestClient(app)
        with patch("services.social_relationship_service.SocialRelationshipService", side_effect=lambda *a, **kw: SocialRelationshipService(store=self.store)):
            res = client.post(
                "/api/engagement/run",
                json={
                    "targets": [{
                        "platform": "threads",
                        "account_id": "already_friend",
                        "post_id": "post_1001",
                    }],
                    "actions": ["like"],
                    "dry_run": False,
                    "confirm_live": True,
                    "exclude_existing_relationships": True,
                },
            )
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["skipped"], 1)
            self.assertEqual(data["processed"], 0)
            self.assertEqual(data["summary"]["executed"], 0)

        # 2. 실제 외부 실행 서비스(mock_service_instance.execute)가 전혀 호출되지 않았음을 단언!
        mock_service_instance.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
