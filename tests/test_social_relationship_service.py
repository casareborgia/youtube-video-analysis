"""SocialRelationshipService 및 관계 캐시 단위 테스트."""

import os
import tempfile
import time
import unittest

from services.social_relationship_service import SocialRelationshipService
from social_store import SocialStore


class TestSocialRelationshipService(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_social.db")
        self.store = SocialStore(path=self.db_path)
        self.service = SocialRelationshipService(store=self.store)
        self.actor_id = "test_user_me"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_self_account_exclusion(self):
        """본인 계정은 항상 self_account로 배제되어야 함."""
        res1 = self.service.evaluate_target(
            platform="threads",
            actor_account_id=self.actor_id,
            target_username="test_user_me",
        )
        self.assertTrue(res1.excluded)
        self.assertEqual(res1.reason, "self_account")

        # @ 기호 및 대소문자 포함 본인
        res2 = self.service.evaluate_target(
            platform="threads",
            actor_account_id=self.actor_id,
            target_username=" @TEST_USER_ME ",
        )
        self.assertTrue(res2.excluded)
        self.assertEqual(res2.reason, "self_account")

    def test_normalization_prevents_bypass(self):
        """@ 기호, 공백, 대소문자 차이로 필터를 우회할 수 없어야 함."""
        # 1. 댓글 작성자 등록
        self.service.record_commenter(
            platform="threads",
            actor_account_id=self.actor_id,
            commenter_username="@Commenter_User",
        )

        # 2. 다른 형식으로 조회해도 배제되어야 함
        res = self.service.evaluate_target(
            platform="threads",
            actor_account_id=self.actor_id,
            target_username="commenter_user",
        )
        self.assertTrue(res.excluded)
        self.assertEqual(res.reason, "commented_on_my_content")

    def test_platform_isolation(self):
        """Threads와 X의 동일한 사용자명은 상호 격리되어야 함."""
        self.service.record_commenter(
            platform="threads",
            actor_account_id=self.actor_id,
            commenter_username="common_user",
        )

        # Threads에서는 제외
        res_threads = self.service.evaluate_target(
            platform="threads",
            actor_account_id=self.actor_id,
            target_username="common_user",
        )
        self.assertTrue(res_threads.excluded)

        # X에서는 신규 후보여야 함 (제외되지 않음)
        res_x = self.service.evaluate_target(
            platform="x",
            actor_account_id=self.actor_id,
            target_username="common_user",
        )
        self.assertFalse(res_x.excluded)

    def test_engagement_success_records_and_excludes(self):
        """스하리 성공(좋아요, 팔로우 등) 이력이 있으면 배제되어야 함."""
        self.service.record_engagement_success(
            platform="threads",
            actor_account_id=self.actor_id,
            action="like",
            target_username="liked_user",
            target_post_id="post_999",
        )

        res = self.service.evaluate_target(
            platform="threads",
            actor_account_id=self.actor_id,
            target_username="liked_user",
        )
        self.assertTrue(res.excluded)
        self.assertEqual(res.reason, "engaged_before")

    def test_replied_by_me_excludes(self):
        """내가 답글을 보낸 이력이 있으면 배제되어야 함."""
        self.service.record_reply_sent(
            platform="threads",
            actor_account_id=self.actor_id,
            target_username="replied_person",
        )

        res = self.service.evaluate_target(
            platform="threads",
            actor_account_id=self.actor_id,
            target_username="replied_person",
        )
        self.assertTrue(res.excluded)
        self.assertEqual(res.reason, "replied_by_me")

    def test_expiration_policy(self):
        """만료 기간이 지난 관찰 관계 신호는 정리 후 신규 후보로 복귀해야 함."""
        now = int(time.time())
        # 과거 200일 전에 기록된 댓글 (180일 만료)
        self.service.record_commenter(
            platform="threads",
            actor_account_id=self.actor_id,
            commenter_username="old_commenter",
            expires_in_days=180,
            now_ts=now - (200 * 86400),
        )

        # 현재 시점 조회 시 만료되어 제외되지 않아야 함
        res = self.service.evaluate_target(
            platform="threads",
            actor_account_id=self.actor_id,
            target_username="old_commenter",
            now_ts=now,
        )
        self.assertFalse(res.excluded)

        # 만료 레코드 정리 함수 동작 검증
        deleted_count = self.service.expire_old_relationships(now_ts=now)
        self.assertGreaterEqual(deleted_count, 1)

    def test_suppress_and_unsuppress(self):
        """수동 제외 및 해제 검증."""
        self.service.suppress_account(
            platform="threads",
            actor_account_id=self.actor_id,
            target_account_key="blocked_user",
            reason="광고 계정",
        )

        res1 = self.service.evaluate_target(
            platform="threads",
            actor_account_id=self.actor_id,
            target_username="blocked_user",
        )
        self.assertTrue(res1.excluded)
        self.assertEqual(res1.reason, "suppressed")

        # 해제
        unsuppressed = self.service.unsuppress_account(
            platform="threads",
            actor_account_id=self.actor_id,
            target_account_key="blocked_user",
        )
        self.assertTrue(unsuppressed)

        res2 = self.service.evaluate_target(
            platform="threads",
            actor_account_id=self.actor_id,
            target_username="blocked_user",
        )
        self.assertFalse(res2.excluded)


if __name__ == "__main__":
    unittest.main()
