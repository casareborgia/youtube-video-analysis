import unittest
from fastapi.testclient import TestClient
from app import app

class TestSocialUIAPIIntegration(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_social_accounts(self):
        resp = self.client.get("/api/social/accounts")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "success")
        self.assertIn("accounts", data)
        self.assertIsInstance(data["accounts"], list)

    def test_social_scheduler_status(self):
        resp = self.client.get("/api/social/scheduler/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "success")
        self.assertIn("scheduler", data)
        self.assertIn("status", data["scheduler"])

    def test_social_history_endpoint(self):
        resp = self.client.get("/api/social/history?limit=10")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "success")
        self.assertIn("jobs", data)

    def test_social_capabilities(self):
        resp = self.client.get("/api/social/capabilities")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "success")
        self.assertIn("platforms", data)
        self.assertIn("threads", data["platforms"])
        self.assertIn("x", data["platforms"])

    def test_social_drafts_manual(self):
        resp = self.client.post("/api/social/drafts/manual", json={
            "platform": "threads",
            "posts": ["테스트 수동 초안 등록 1번 글"],
            "actor_account_id": "test_actor",
            "dry_run": True
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "success")
        self.assertIn("job_id", data)

    def test_static_index_html_has_social_tab(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("navTabSocial", resp.text)
        self.assertIn("viewSocial", resp.text)
        self.assertIn("socialConfirmModal", resp.text)
        self.assertIn("btnRefreshSocialHistory", resp.text)

if __name__ == "__main__":
    unittest.main()
