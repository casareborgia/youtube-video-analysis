import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest
from fastapi.testclient import TestClient
import app
import reply_service
import social_store
import threads_client
import x_client


# ---- 외부 자격증명(.env) 없이도 동작하도록 Threads / X 클라이언트를 격리하는 가짜 응답 ----
FAKE_THREADS_CONF = {
    "access_token": "test-threads-token",
    "user_id": "th_user_1",
    "username": "test_threads_user",
    "app_id": "",
    "app_secret": "",
    "redirect_uri": "http://127.0.0.1:8765/api/threads/auth/callback",
    "profile_pic": "",
    "token_expires_at": 0,
}

FAKE_X_STATUS = {
    "platform": "x",
    "connected": True,
    "status": "connected",
    # reply_service 는 'test_mock_uid' 일 때 실제 X API(mentions) 호출을 건너뛴다.
    "account_id": "test_mock_uid",
    "username": "test_x_user",
    "display_name": "Test X",
    "scopes": ["tweet.read", "tweet.write", "users.read"],
    "expires_at": 0,
    "expires_in_seconds": 0,
    "error_code": None,
    "message": "mock connected",
}

FAKE_X_CONF = {"access_token": "test-x-token", "user_id": "test_mock_uid", "username": "test_x_user"}


def _fake_threads_http(url: str, method: str = "GET", params=None, data=None, headers=None) -> dict:
    """Threads Graph API 를 흉내 낸다: 내 게시물 목록 → 각 게시물의 답글 목록"""
    if url.endswith("/threads"):
        return {"data": [{"id": "th_p_1", "text": "테스트 게시물 본문", "timestamp": "2026-10-01T00:00:00+0000"}]}
    if url.endswith("/replies"):
        return {
            "data": [
                {"id": "th_c_1", "text": "타인이 남긴 댓글", "username": "someone_else", "timestamp": "2026-10-01T01:00:00+0000"},
                {"id": "th_c_2", "text": "내가 남긴 답글", "username": "test_threads_user", "timestamp": "2026-10-01T02:00:00+0000"},
            ]
        }
    return {"data": []}


class TestAccountWideReplies(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test_replies.db"
        self.patches = [
            patch("social_store.DEFAULT_DB_PATH", self.db_path),
            # Threads: 토큰 로드 및 Graph API 호출 격리
            patch.object(threads_client, "load_config", return_value=dict(FAKE_THREADS_CONF)),
            patch.object(threads_client, "_http_request", side_effect=_fake_threads_http),
            # X: 연결 상태 및 토큰 로드 격리
            patch.object(x_client, "get_status", return_value=dict(FAKE_X_STATUS)),
            patch.object(x_client, "load_config", return_value=dict(FAKE_X_CONF)),
        ]
        for p in self.patches:
            p.start()
        self.client = TestClient(app.app)
        self.service = reply_service.ReplyService(store=social_store.SocialStore(self.db_path))

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

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
        # 타인 댓글이 본인 답글보다 먼저 와야 한다
        self.assertEqual(first["id"], "th_c_1")
        self.assertEqual(first["username"], "someone_else")
        self.assertEqual(res.get("account_username"), "test_threads_user")

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
