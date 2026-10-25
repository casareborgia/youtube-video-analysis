"""P-1 영어 음성 — Andrew 프리셋, 잡 언어, 내 목소리 경로 언어 전달 (작업계획서_ShijiFiles_파일럿3편 4장 P-1)."""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as app_module
import shorts_captions
import shorts_engine
import tts_service
try:   # 문서화된 실행법(-s tests)에서는 tests 폴더가 경로에 있다
    from test_shorts_engine import ShortsS2Base, _fake_merge, _fake_synth
except ImportError:   # python -m unittest tests.test_shorts_english_voice
    from tests.test_shorts_engine import ShortsS2Base, _fake_merge, _fake_synth


class EnglishPresetTests(unittest.TestCase):
    def test_andrew_preset_registered(self):
        by_id = {p["id"]: p for p in tts_service.EDGE_PRESETS}
        andrew = by_id["edge_andrew_en"]
        self.assertEqual(andrew["voice_id"], "en-US-AndrewMultilingualNeural")
        self.assertEqual(andrew["language"], "english")
        self.assertEqual(andrew["default_rate"], "+0%")
        for kid in ("edge_injoon", "edge_sunhi", "edge_hyunsu"):
            self.assertEqual(by_id[kid]["language"], "korean")

    def test_korean_default_stays_first(self):
        # EDGE_PRESETS[0] 은 알 수 없는 edge 코드의 폴백 — 한국어 기본(인준)이 그대로여야 한다
        self.assertEqual(tts_service.EDGE_PRESETS[0]["id"], "edge_injoon")

    def test_voice_language(self):
        self.assertEqual(tts_service.voice_language("edge_andrew_en"), "english")
        self.assertEqual(tts_service.voice_language("edge_injoon"), "korean")
        self.assertEqual(tts_service.voice_language("ko-KR-SunHiNeural"), "korean")
        self.assertIsNone(tts_service.voice_language("my_voice"))
        self.assertIsNone(tts_service.voice_language(""))


class DefaultSynthLanguageTests(unittest.TestCase):
    def setUp(self):
        import tempfile, shutil
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_my_voice_gets_job_language(self):
        calls = {}
        src = os.path.join(self.tmp, "shorts_scene_01.wav")
        with open(src, "wb") as f:
            f.write(b"wav")

        def fake_speech(text, voice_id=None, scene_index=1, topic_slug="scene", language="korean"):
            calls.update(text=text, voice_id=voice_id, language=language)
            return {"status": "success", "filename": "shorts_scene_01.wav", "engine": "qwen-tts"}

        with patch.object(tts_service.TTSService, "synthesize_speech", side_effect=fake_speech), \
             patch.object(tts_service, "AUDIO_DIR", self.tmp):
            res = shorts_engine._default_synth("my_voice", "english")("He wrote the manual.", 1,
                                                                      os.path.join(self.tmp, "narration_01"))
        self.assertEqual(calls["language"], "english")
        self.assertEqual(calls["voice_id"], "my_voice")
        self.assertIsNone(res["captions"])

    def test_language_defaults_to_korean(self):
        calls = {}

        def fake_speech(text, voice_id=None, scene_index=1, topic_slug="scene", language="korean"):
            calls["language"] = language
            return {"status": "error", "message": "x"}

        with patch.object(tts_service.TTSService, "synthesize_speech", side_effect=fake_speech):
            with self.assertRaises(RuntimeError):
                shorts_engine._default_synth("my_voice")("안녕하세요", 1, os.path.join(self.tmp, "n"))
        self.assertEqual(calls["language"], "korean")

    def test_andrew_uses_english_code_and_rate(self):
        seen = {}

        async def fake_edge(text, voice_code=None, rate=None, output_file=None, with_word_boundaries=False):
            seen.update(voice_code=voice_code, rate=rate)
            with open(output_file, "wb") as f:
                f.write(b"mp3")
            return {"captions": [{"text": "A", "startMs": 100, "endMs": 400}]}

        with patch.object(tts_service.TTSService, "synthesize_edge_tts_single", side_effect=fake_edge), \
             patch.object(shorts_engine, "_trim_trailing_silence", return_value=False), \
             patch.object(shorts_engine.producer, "ffmpeg_path", return_value=None):
            res = shorts_engine._default_synth("edge_andrew_en", "english")("A merchant.", 1,
                                                                            os.path.join(self.tmp, "n"))
        self.assertEqual(seen, {"voice_code": "en-US-AndrewMultilingualNeural", "rate": "+0%"})
        self.assertEqual(res["engine"], "edge-tts")


class JobLanguageTests(ShortsS2Base):
    def test_job_language_rules(self):
        self.assertEqual(shorts_engine.job_language({}, "edge_andrew_en"), "english")
        self.assertEqual(shorts_engine.job_language({"language": "english"}, "my_voice"), "english")
        self.assertEqual(shorts_engine.job_language({}, "my_voice"), "korean")
        self.assertEqual(shorts_engine.job_language({}, None), "korean")

    def test_build_job_from_plan_language(self):
        plan = self.save_plan(n=3)
        job = shorts_engine.build_job_from_plan(plan["plan_id"], voice_id="my_voice", language="english")
        self.assertEqual(job["language"], "english")
        job2 = shorts_engine.build_job_from_plan(plan["plan_id"])
        self.assertNotIn("language", job2)
        with self.assertRaises(ValueError):
            shorts_engine.build_job_from_plan(plan["plan_id"], language="klingon")

    def test_synthesize_records_language_and_passes_it(self):
        plan = self.save_plan(n=2)
        job = shorts_engine.build_job_from_plan(plan["plan_id"], voice_id="my_voice", language="english")
        seen = {}
        real = _fake_synth(False)

        def fake_factory(voice_id, language="korean"):
            seen.update(voice_id=voice_id, language=language)
            return real

        with patch.object(shorts_engine, "_default_synth", side_effect=fake_factory):
            job = shorts_engine.synthesize_job_audio(job, merger=_fake_merge, bgm_picker=lambda tid: None)
        self.assertEqual(seen, {"voice_id": "my_voice", "language": "english"})
        self.assertEqual(job["language"], "english")
        self.assertEqual(job["narration_language"], "english")

    def test_language_from_voice_when_job_has_none(self):
        plan = self.save_plan(n=2)
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        job = shorts_engine.synthesize_job_audio(job, voice_id="edge_andrew_en", synth=_fake_synth(True, 4.0),
                                                 merger=_fake_merge, bgm_picker=lambda tid: None)
        self.assertEqual(job["narration_language"], "english")
        self.assertNotIn("language", job)   # 추정값은 굳히지 않는다

    def test_voice_switch_does_not_keep_old_guess(self):
        plan = self.save_plan(n=2)
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        job = shorts_engine.synthesize_job_audio(job, voice_id="edge_andrew_en", synth=_fake_synth(True, 4.0),
                                                 merger=_fake_merge, bgm_picker=lambda tid: None)
        job = shorts_engine.synthesize_job_audio(job, voice_id="edge_injoon", synth=_fake_synth(True, 4.0),
                                                 merger=_fake_merge, bgm_picker=lambda tid: None)
        self.assertEqual(job["narration_language"], "korean")
        self.assertFalse(any("다릅니다" in w for w in job.get("warnings") or []))

    def test_mismatch_warns(self):
        plan = self.save_plan(n=2)
        job = shorts_engine.build_job_from_plan(plan["plan_id"], language="korean")
        job = shorts_engine.synthesize_job_audio(job, voice_id="edge_andrew_en", synth=_fake_synth(True, 4.0),
                                                 merger=_fake_merge, bgm_picker=lambda tid: None)
        self.assertEqual(job["narration_language"], "korean")
        self.assertTrue(any("english" in w and "korean" in w for w in job.get("warnings") or []))


class EnglishApiTests(ShortsS2Base):
    def setUp(self):
        super().setUp()
        self.client = TestClient(app_module.app)
        app_module._shorts_building.clear()

    def test_create_job_with_language(self):
        plan = self.save_plan(n=3)
        r = self.client.post("/api/shorts/jobs", json={"plan_id": plan["plan_id"], "voice_id": "edge_andrew_en",
                                                       "language": "english"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["data"]["language"], "english")

    def test_create_job_rejects_unknown_language(self):
        plan = self.save_plan(n=3)
        r = self.client.post("/api/shorts/jobs", json={"plan_id": plan["plan_id"], "language": "klingon"})
        self.assertEqual(r.status_code, 400)


class EnglishCaptionGroupingTests(unittest.TestCase):
    def test_four_words_per_group_and_sentence_end(self):
        words = ["A", "merchant", "looked", "at", "a", "hostage", "prince.", "He", "smiled."]
        caps = [{"text": (" " if i else "") + w, "startMs": i * 300, "endMs": i * 300 + 250} for i, w in enumerate(words)]
        caps[-1]["pageBreakAfter"] = True
        groups = shorts_captions.caption_groups(caps)
        self.assertTrue(all(g["words"] <= 5 for g in groups), groups)
        # "prince." 에서 문장이 끝나므로 그 단어 끝(6번째 토큰: 6*300+250)에서 그룹이 끊긴다
        self.assertIn(2050, [g["endMs"] for g in groups])


if __name__ == "__main__":
    unittest.main()
