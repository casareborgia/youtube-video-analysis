import unittest
from fastapi.testclient import TestClient
from app import app


class TestAutonomousRoutes(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_list_routines(self):
        response = self.client.get("/api/routines")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 4)
        codes = [r["code"] for r in data]
        self.assertIn("AI_TREND", codes)
        self.assertIn("MAUM_PROMO", codes)
        self.assertIn("RESEARCH", codes)
        self.assertIn("COMMENT_REPLY", codes)

    def test_get_routine_by_code(self):
        response = self.client.get("/api/routines/AI_TREND")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], "AI_TREND")
        self.assertIn("sources", data)
        self.assertGreaterEqual(len(data["schedules"]), 1)

    def test_update_routine(self):
        payload = {
            "mode": "AUTO",
            "schedules": [
                {"local_time": "12:00", "days_of_week": ["MON", "WED"], "enabled": True}
            ],
            "max_posts_per_day": 4
        }
        response = self.client.put("/api/routines/AI_TREND", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["mode"], "AUTO")
        self.assertEqual(data["max_posts_per_day"], 4)
        self.assertEqual(data["schedules"][0]["local_time"], "12:00")

    def test_list_sources(self):
        response = self.client.get("/api/sources")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreaterEqual(len(data), 3)

    def test_test_source_ssrf_blocked(self):
        payload = {
            "url": "http://127.0.0.1:8765/api/routines",
            "kind": "JSON_API"
        }
        response = self.client.post("/api/sources/test", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertTrue("SSRF" in (data["error"] or "") or "차단" in (data["error"] or ""))

    def test_maum_angles_api(self):
        response = self.client.get("/api/routines/MAUM_PROMO/angles")
        self.assertEqual(response.status_code, 200)
        angles = response.json()
        self.assertEqual(len(angles), 8)

        next_res = self.client.get("/api/routines/MAUM_PROMO/next-angle")
        self.assertEqual(next_res.status_code, 200)
        next_angle = next_res.json()
        self.assertIsNotNone(next_angle)
        self.assertIn("title", next_angle)

    def test_pilot_status(self):
        response = self.client.get("/api/pilot/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "OPERATIONAL")
        self.assertEqual(data["total_routines"], 4)
        self.assertGreaterEqual(data["total_sources"], 3)

    def test_run_routine_now(self):
        # 마음지기 루틴 즉시 1회 실행
        response = self.client.post("/api/routines/MAUM_PROMO/run?limit=1")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["routine_code"], "MAUM_PROMO")
        self.assertEqual(data["executed_items_count"], 1)

        result_item = data["results"][0]
        draft = result_item["draft"]
        self.assertIn("body", draft)
        self.assertIn("first_reply", draft)

        # 본문 링크 0개 검증
        import re
        self.assertEqual(len(re.findall(r"https?://", draft["body"])), 0)
        # 첫 답글 원문/서비스 링크 포함 검증
        self.assertIn("https://maumjigi.com", draft["first_reply"])

    def test_outbox_jobs_api_and_approval(self):
        # 1. 아웃박스 목록 조회
        list_res = self.client.get("/api/outbox/jobs")
        self.assertEqual(list_res.status_code, 200)
        jobs = list_res.json()
        self.assertGreaterEqual(len(jobs), 1)

        job_id = jobs[0]["id"]
        # 2. 특정 작업 상세 조회
        detail_res = self.client.get(f"/api/outbox/jobs/{job_id}")
        self.assertEqual(detail_res.status_code, 200)
        job_detail = detail_res.json()
        self.assertEqual(job_detail["id"], job_id)
        self.assertGreaterEqual(len(job_detail["steps"]), 2)

        # 3. 작업 모의 승인 및 발행
        approve_res = self.client.post(f"/api/outbox/jobs/{job_id}/approve?dry_run=true")
        self.assertEqual(approve_res.status_code, 200)
        approve_data = approve_res.json()
        self.assertIn("result", approve_data)
        self.assertEqual(approve_data["result"]["status"], "SUCCEEDED")

    def test_scheduler_endpoints(self):
        # 스케줄러 잡 조회
        resp = self.client.get("/api/scheduler/jobs")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("jobs", data)

        # 스케줄러 리로드
        reload_res = self.client.post("/api/scheduler/reload")
        self.assertEqual(reload_res.status_code, 200)
        r_data = reload_res.json()
        self.assertTrue(r_data["success"])
        self.assertGreaterEqual(r_data["jobs_count"], 4)


if __name__ == "__main__":
    unittest.main()
