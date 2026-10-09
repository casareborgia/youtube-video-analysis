import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app
import llm_client
import producer


def _offline_probe(url: str, timeout: float = 1.5):
    """LM Studio / Ollama 로컬 포트 프로브를 네트워크 없이 '꺼짐'으로 처리"""
    raise urllib.error.URLError("offline in tests")


class TestGeminiModelSelection(unittest.TestCase):
    """
    외부 자격증명(.env 의 GEMINI_API_KEY)이나 로컬 LLM 서버 없이도 통과하도록
    환경 의존 지점을 모두 mock 으로 격리한다.
    - producer.gemini_key: 가짜 키 반환 → Gemini 백엔드 online 으로 감지
    - llm_client.SETTINGS_FILE: 임시 경로 → data/settings.json 오염 방지
    - llm_client._get_json: 로컬 포트 프로브 차단
    - TUBEINSIGHT_LLM_BACKEND: 환경변수 강제 백엔드 제거
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        settings_path = Path(self.tmp.name) / "settings.json"

        self.patches = [
            patch.object(producer, "gemini_key", return_value="test-gemini-key"),
            patch.object(llm_client, "SETTINGS_FILE", settings_path),
            patch.object(llm_client, "_get_json", side_effect=_offline_probe),
            patch.object(llm_client, "_preference", "gemini"),
            patch.object(llm_client, "_selected_model", None),
            patch.dict(llm_client._cache, {"ts": 0.0, "backend": None}),
            patch.dict("os.environ", {}, clear=False),
        ]
        for p in self.patches:
            p.start()
        import os
        os.environ.pop("TUBEINSIGHT_LLM_BACKEND", None)

        self.client = TestClient(app.app)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_llm_models_endpoint_surfaces_gemini_first(self):
        res = self.client.get("/api/llm/models")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")

        models = data.get("models", [])
        self.assertTrue(len(models) > 0)

        # Gemini 모델이 목록의 최상단에 위치하는지 검증
        self.assertEqual(models[0]["backend"], "gemini")
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
