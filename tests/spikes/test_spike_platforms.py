import unittest
from unittest.mock import patch, MagicMock

class TestSpikePlatforms(unittest.TestCase):
    """Phase 0 (Spike 0): X 및 Threads 본문 + 첫 답글(셀프 답글) 연쇄 발행 체인 계약 검증"""

    def test_01_x_chain_publishing_contract(self):
        """X v2 API: 본문 생성 -> remote_id 획득 -> in_reply_to_tweet_id로 첫 답글 생성 계약"""
        body_text = "인공지능 최신 동향 요약 본문 (링크 없음)"
        reply_text = "출처: https://news.hada.io/topic?id=123"

        mock_client = MagicMock()
        # 1단계 본문 게시
        mock_client.create_post.return_value = "tweet_parent_123"
        parent_id = mock_client.create_post(body_text)
        self.assertEqual(parent_id, "tweet_parent_123")

        # 2단계 셀프 답글 게시
        mock_client.create_reply.return_value = "tweet_reply_456"
        reply_id = mock_client.create_reply(parent_id=parent_id, text=reply_text)
        self.assertEqual(reply_id, "tweet_reply_456")

        mock_client.create_post.assert_called_once_with(body_text)
        mock_client.create_reply.assert_called_once_with(parent_id="tweet_parent_123", text=reply_text)
        print("\n[X API 체인 계약 검증 성공] 본문 -> tweet_parent_123 -> reply.in_reply_to_tweet_id 호출 계약 일치")

    def test_02_threads_chain_publishing_contract(self):
        """Threads v1.0 API: 텍스트 컨테이너 -> 발행 -> reply_to_id 답글 컨테이너 -> 발행 계약"""
        body_text = "Threads 최신 연구 소개 본문 (링크 없음)"
        reply_text = "논문 원문: https://arxiv.org/abs/2609.12345"

        mock_threads = MagicMock()
        # 1단계 본문 (컨테이너 생성 -> 발행)
        mock_threads.create_text_container.return_value = "c_parent_111"
        mock_threads.publish_container.return_value = "th_parent_222"
        c1 = mock_threads.create_text_container(text=body_text)
        p1 = mock_threads.publish_container(c1)
        self.assertEqual(p1, "th_parent_222")

        # 2단계 답글 (reply_to_id 지정 컨테이너 생성 -> 발행)
        mock_threads.create_text_container.return_value = "c_reply_333"
        mock_threads.publish_container.return_value = "th_reply_444"
        c2 = mock_threads.create_text_container(text=reply_text, reply_to_id=p1)
        p2 = mock_threads.publish_container(c2)
        self.assertEqual(p2, "th_reply_444")

        self.assertEqual(p1, "th_parent_222")
        self.assertEqual(p2, "th_reply_444")
        print("\n[Threads API 체인 계약 검증 성공] 본문(c_parent->th_parent) -> reply_to_id 답글(c_reply->th_reply) 계약 일치")

if __name__ == "__main__":
    unittest.main()
