import unittest
from fastapi.testclient import TestClient
import app
import reply_service


class TestAccountWideReplies(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app.app)
        self.service = reply_service.ReplyService()

    def test_threads_account_replies(self):
        res = self.service.fetch_account_replies(platform="threads")
        self.assertEqual(res.get("status"), "success")
        self.assertEqual(res.get("platform"), "threads")
        self.assertEqual(res.get("scope"), "account_wide")
        self.assertIn("replies", res)
        self.assertIn("comments", res)
        self.assertTrue(len(res["replies"]) > 0)
        first = res["replies"][0]
        self.assertIn("id", first)
        self.assertIn("text", first)
        self.assertIn("username", first)

    def test_x_account_replies(self):
        res = self.service.fetch_account_replies(platform="x")
        self.assertEqual(res.get("status"), "success")
        self.assertEqual(res.get("platform"), "x")
        self.assertEqual(res.get("scope"), "account_wide")
        self.assertIn("replies", res)
        self.assertIn("comments", res)
        self.assertTrue(len(res["replies"]) > 0)
        first = res["replies"][0]
        self.assertIn("id", first)
        self.assertIn("text", first)

    def test_api_endpoint_without_post_id_returns_account_replies(self):
        # Threads
        res_th = self.client.get("/api/social/comments/threads")
        self.assertEqual(res_th.status_code, 200)
        data_th = res_th.json()
        self.assertEqual(data_th.get("status"), "success")
        self.assertEqual(data_th.get("scope"), "account_wide")
        self.assertTrue(len(data_th.get("replies", [])) > 0)

        # X
        res_x = self.client.get("/api/social/comments/x")
        self.assertEqual(res_x.status_code, 200)
        data_x = res_x.json()
        self.assertEqual(data_x.get("status"), "success")
        self.assertEqual(data_x.get("scope"), "account_wide")
        self.assertTrue(len(data_x.get("replies", [])) > 0)

    def test_api_endpoint_with_post_id_falls_back_to_post(self):
        # 특정 게시물 ID 전달 시 해당 게시물 모드로 동작
        res = self.client.get("/api/social/comments/threads/mock_post_123")
        self.assertEqual(res.status_code, 200)

    def test_publish_single_and_enrichment(self):
        import time
        unique_id = f"test_comment_{int(time.time() * 1000)}"
        # 1. 단일 답글 즉시 발행 (dry_run)
        res = self.client.post(
            "/api/social/replies/publish-single",
            json={
                "platform": "threads",
                "target_comment_id": unique_id,
                "reply_text": "답글 확인용 테스트 본문입니다.",
                "dry_run": True,
            },
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "success")
        result = data.get("result", {})
        self.assertEqual(result.get("target_comment_id"), unique_id)
        self.assertTrue(bool(result.get("url")))

        # 2. social_store에서 target 조회 확인
        reply_job = self.service.store.get_reply_for_target("threads", unique_id)
        self.assertIsNotNone(reply_job)
        self.assertEqual(reply_job["status"], "succeeded")
        self.assertEqual(reply_job["reply_content"], "답글 확인용 테스트 본문입니다.")

        # 3. 댓글 enrichment 확인
        enriched = self.service._enrich_comments_with_reply_status(
            "threads",
            [{"id": unique_id, "text": "원문", "username": "someone"}],
        )
        self.assertEqual(len(enriched), 1)
        self.assertTrue(enriched[0]["has_replied"])
        self.assertEqual(enriched[0]["reply_status"], "published")
        self.assertIsNotNone(enriched[0]["my_reply"])
        self.assertEqual(enriched[0]["my_reply"]["text"], "답글 확인용 테스트 본문입니다.")

    def test_direct_batch_publish(self):
        import time
        t = int(time.time() * 1000)
        res = self.client.post(
            "/api/social/replies/batch-publish",
            json={
                "platform": "x",
                "items": [
                    {"comment_id": f"batch_c_1_{t}", "reply_text": "배치 답글 1"},
                    {"comment_id": f"batch_c_2_{t}", "reply_text": "배치 답글 2"},
                ],
                "dry_run": True,
            },
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(len(data.get("results", [])), 2)
        self.assertEqual(data["results"][0]["status"], "success")
        self.assertEqual(data["results"][1]["status"], "success")


if __name__ == "__main__":
    unittest.main()
