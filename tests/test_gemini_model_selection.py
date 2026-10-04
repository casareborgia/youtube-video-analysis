import unittest
from fastapi.testclient import TestClient
import app
import llm_client


class TestGeminiModelSelection(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app.app)

    def test_llm_models_endpoint_surfaces_gemini_first(self):
        res = self.client.get("/api/llm/models")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")

        models = data.get("models", [])
        self.assertTrue(len(models) > 0)

        # Gemini 모델이 목록의 최상단에 위치하는지 검증
        gemini_items = [m for m in models if m["backend"] == "gemini"]
        self.assertTrue(len(gemini_items) >= 3)
        self.assertEqual(gemini_items[0]["backend_label"], "Google Gemini (클라우드)")
        self.assertTrue(gemini_items[0]["online"])

    def test_select_gemini_model_updates_preference_and_status(self):
        target_model = "gemini-3.8-flash"
        res = self.client.post("/api/llm/select-model", json={"model": target_model})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["selected_model"], target_model)
        self.assertEqual(data["active"]["backend_type"], "gemini")
        self.assertEqual(data["active"]["model"], target_model)

        # 상태 엔드포인트에서도 즉시 반영되는지 확인
        status_res = self.client.get("/api/llm/status")
        self.assertEqual(status_res.status_code, 200)
        status_data = status_res.json()
        self.assertEqual(status_data["preference"], "gemini")
        self.assertEqual(status_data["active"]["model"], target_model)


if __name__ == "__main__":
    unittest.main()
