import time
import unittest
import asyncio
from unittest.mock import patch
from services.comment_sentinel import CommentSentinel, DetectedComment
from domain.enums import RoutineMode
from repositories.routine_repository import RoutineRepository


class TestCommentSentinel(unittest.TestCase):
    def setUp(self):
        self.repo = RoutineRepository()
        self.sentinel = CommentSentinel(self.repo)

    def test_run_sentinel_cycle_review_mode(self):
        now = int(time.time() * 1000)
        mock_comments = [
            DetectedComment(
                platform="threads",
                comment_id=f"test_th_{now}",
                parent_post_id="post_1",
                author_username="ai_learner",
                content="정리해주신 논문 요약 너무 유익하네요!",
                created_at=int(time.time())
            )
        ]

        async def run_test():
            with patch.object(self.sentinel, "_fetch_recent_comments", return_value=mock_comments):
                # 1. 1회 센티넬 사이클 실행 (REVIEW 모드)
                results = await self.sentinel.run_sentinel_cycle(
                    routine_mode=RoutineMode.REVIEW,
                    dry_run=True
                )
                self.assertEqual(len(results), 1)

                first = results[0]
                self.assertEqual(first.status, "SUGGESTED")
                self.assertIn("@", first.proposed_reply)
                self.assertIsNotNone(first.remote_reply_id)

                # 2. 중복 방지 검증: 바로 다음 사이클 실행 시 이미 처리된 댓글은 스킵되어야 함
                second_results = await self.sentinel.run_sentinel_cycle(
                    routine_mode=RoutineMode.REVIEW,
                    dry_run=True
                )
                self.assertEqual(len(second_results), 0)

        asyncio.run(run_test())

    def test_generate_sympathy_reply_content(self):
        async def run_test():
            burnout_comment = DetectedComment(
                platform="threads",
                comment_id="test_th_burnout",
                parent_post_id="post_1",
                author_username="tired_user",
                content="정말 지치고 번아웃이 심했는데 큰 위로가 되었습니다.",
                created_at=1000
            )
            reply = await self.sentinel._generate_sympathy_reply(burnout_comment)
            self.assertIn("@tired_user", reply)
            self.assertTrue("마음" in reply or "쉼" in reply or "위로" in reply or "감사" in reply)

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
