"""Gemini 텍스트 호출 요청 타임아웃 테스트 (fix/gemini-text-call-timeout).

call_gemini 이 매 요청에 http_options.timeout(ms) 을 넣는지, 환경변수로 조절되는지,
json_mode 재시도 경로에서도 유지되는지, 타임아웃 예외가 call_llm 의 로컬 폴백으로 이어지는지 검증한다.
"""

import unittest
from unittest.mock import patch

import llm_client
import producer


class _FakeModels:
    def __init__(self, fail_first=False, raise_always=None):
        self.calls = []
        self.fail_first = fail_first
        self.raise_always = raise_always

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "config": dict(config)})
        if self.raise_always:
            raise self.raise_always
        if self.fail_first and len(self.calls) == 1:
            raise RuntimeError("json mime not supported")

        class R:
            text = '{"ok": true}'
        return R()


class _FakeClient:
    def __init__(self, models):
        self.models = models


class GeminiTimeoutTests(unittest.TestCase):
    def test_default_timeout_is_sent_in_ms(self):
        fm = _FakeModels()
        with patch.object(producer, "get_genai_client", return_value=_FakeClient(fm)), \
             patch.object(llm_client, "GEMINI_TEXT_TIMEOUT_SECONDS", 180.0):
            out = llm_client.call_gemini([{"role": "user", "content": "hi"}], json_mode=True)
        self.assertEqual(out, '{"ok": true}')
        cfg = fm.calls[0]["config"]
        self.assertEqual(cfg["http_options"], {"timeout": 180000})
        self.assertEqual(cfg["response_mime_type"], "application/json")

    def test_timeout_env_override(self):
        fm = _FakeModels()
        with patch.object(producer, "get_genai_client", return_value=_FakeClient(fm)), \
             patch.object(llm_client, "GEMINI_TEXT_TIMEOUT_SECONDS", 45.0):
            llm_client.call_gemini([{"role": "user", "content": "hi"}])
        self.assertEqual(fm.calls[0]["config"]["http_options"]["timeout"], 45000)

    def test_zero_disables_timeout(self):
        fm = _FakeModels()
        with patch.object(producer, "get_genai_client", return_value=_FakeClient(fm)), \
             patch.object(llm_client, "GEMINI_TEXT_TIMEOUT_SECONDS", 0.0):
            llm_client.call_gemini([{"role": "user", "content": "hi"}])
        self.assertNotIn("http_options", fm.calls[0]["config"])

    def test_json_mode_retry_keeps_timeout(self):
        fm = _FakeModels(fail_first=True)
        with patch.object(producer, "get_genai_client", return_value=_FakeClient(fm)), \
             patch.object(llm_client, "GEMINI_TEXT_TIMEOUT_SECONDS", 180.0):
            llm_client.call_gemini([{"role": "user", "content": "hi"}], json_mode=True)
        self.assertEqual(len(fm.calls), 2)
        self.assertNotIn("response_mime_type", fm.calls[1]["config"])
        self.assertEqual(fm.calls[1]["config"]["http_options"]["timeout"], 180000)

    def test_timeout_error_falls_back_to_local_llm(self):
        fm = _FakeModels(raise_always=TimeoutError("timed out"))
        gemini_be = {"backend_type": "gemini", "model": "gemini-3.8-flash", "name": "Gemini", "base": ""}
        local_be = {"backend_type": "ollama", "model": "gemma4:latest", "name": "Ollama", "base": "http://127.0.0.1:11434"}

        def fake_detect(force=None):
            return local_be if force in ("lmstudio", "ollama") else gemini_be

        def fake_post_factory():
            class Resp:
                def __init__(self):
                    self.body = b'{"choices":[{"message":{"content":"local ok"},"finish_reason":"stop"}]}'
                def read(self): return self.body
                def __enter__(self): return self
                def __exit__(self, *a): return False
            return lambda req, timeout=None: Resp()

        with patch.object(producer, "get_genai_client", return_value=_FakeClient(fm)), \
             patch.object(llm_client, "detect_backend", side_effect=fake_detect), \
             patch.object(llm_client, "_selected_model", None), \
             patch.object(llm_client.urllib.request, "urlopen", fake_post_factory()):
            out = llm_client.call_llm([{"role": "user", "content": "hi"}])
        self.assertEqual(out, "local ok")
        self.assertEqual(len(fm.calls), 1)   # Gemini 는 한 번 시도 후 로컬로 넘어간다


if __name__ == "__main__":
    unittest.main()
