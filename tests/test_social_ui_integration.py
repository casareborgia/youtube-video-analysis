import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest
from fastapi.testclient import TestClient
from app import app
import social_store

class TestSocialUIAPIIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test_ui_social.db"
        self.patch_db = patch("social_store.DEFAULT_DB_PATH", self.db_path)
        self.patch_db.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.patch_db.stop()
        self.tmp.cleanup()

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
        # 환경설정 모달 내 X 연동 요소 검증
        self.assertIn("envXBadge", resp.text)
        self.assertIn("btnConnectX", resp.text)
        self.assertIn("envXTokenInput", resp.text)

        # 🤖 Phase 4 자율 오퍼레이터 대시보드 UI 요소 검증
        self.assertIn("socialTabAutonomous", resp.text)
        self.assertIn("autonomousRoutinesContainer", resp.text)
        self.assertIn("sourcesListContainer", resp.text)
        self.assertIn("outboxJobsContainer", resp.text)
        self.assertIn("modalScheduleEdit", resp.text)
        self.assertIn("modalAddSource", resp.text)
        self.assertIn("btnRefreshAutonomous", resp.text)

    def test_x_settings_and_status(self):
        # 1. status 조회
        resp = self.client.get("/api/x/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("platform", data)
        self.assertEqual(data["platform"], "x")

        # 2. settings 저장
        resp2 = self.client.post("/api/x/settings", json={
            "access_token": "test_mock_token",
            "user_id": "test_mock_uid"
        })
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()
        self.assertEqual(data2.get("platform"), "x")

if __name__ == "__main__":
    unittest.main()
