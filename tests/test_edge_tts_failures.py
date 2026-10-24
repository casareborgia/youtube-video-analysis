"""edge-tts 실패를 숨기지 않는다 — Qwen 기본 화자로 넘어가지 않고 실패 이유를 그대로 알린다."""
import asyncio
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tts_service


class _FakeCommunicate:
    """edge_tts.Communicate 대역. 문장에 '실패' 가 들어 있으면 네트워크 오류를 낸다."""

    def __init__(self, text, voice=None, rate=None, pitch=None, boundary=None):
        self.text = text

    async def save(self, path):
        if "실패" in self.text:
            raise ConnectionError("speech.platform.bing.com 에 연결할 수 없습니다")
        with open(path, "wb") as f:
            f.write(b"mp3")

    async def stream(self):
        yield {"type": "audio", "data": b"partial"}
        raise ConnectionError("스트림이 끊겼습니다")


class SynthesizeSpeechEdgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        p = patch.object(tts_service, "AUDIO_DIR", self.tmp)
        p.start()
        self.addCleanup(p.stop)
        # Qwen 실행으로 넘어가면 안 된다
        p = patch.object(tts_service.subprocess, "run", side_effect=AssertionError("Qwen 으로 넘어가면 안 된다"))
        self.qwen_run = p.start()
        self.addCleanup(p.stop)

    def test_edge_failure_is_reported_not_replaced_by_qwen(self):
        stale = self.tmp / "t_scene_01.mp3"
        stale.write_bytes(b"old")
        with patch.object(tts_service.edge_tts, "Communicate", _FakeCommunicate):
            res = tts_service.TTSService.synthesize_speech("연결 실패 시험 문장", voice_id="edge_injoon", scene_index=1, topic_slug="t")
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["engine"], "edge-tts")
        self.assertIn("ConnectionError", res["message"])
        self.assertFalse(stale.exists())
        self.qwen_run.assert_not_called()

    def test_empty_file_is_not_success(self):
        async def empty(text, voice_code=None, rate=None, output_file=None, **kw):
            open(output_file, "wb").close()
            return output_file
        with patch.object(tts_service.TTSService, "synthesize_edge_tts_single", side_effect=empty):
            res = tts_service.TTSService.synthesize_speech("빈 파일 시험 문장", voice_id="edge_sunhi", scene_index=2, topic_slug="t")
        self.assertEqual(res["status"], "error")
        self.assertFalse((self.tmp / "t_scene_02.mp3").exists())

    def test_unknown_voice_is_rejected(self):
        res = tts_service.TTSService.synthesize_speech("목소리 시험 문장", voice_id="no_such_voice", scene_index=3, topic_slug="t")
        self.assertEqual(res["status"], "error")
        self.assertIn("no_such_voice", res["message"])
        self.qwen_run.assert_not_called()

    def test_edge_success(self):
        with patch.object(tts_service.edge_tts, "Communicate", _FakeCommunicate):
            res = tts_service.TTSService.synthesize_speech("정상 시험 문장", voice_id="edge_injoon", scene_index=4, topic_slug="t")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["engine"], "edge-tts")
        self.assertTrue((self.tmp / res["filename"]).exists())


class EdgeWordBoundaryFailureTests(unittest.TestCase):
    def test_broken_stream_removes_partial_file_and_raises(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        out = os.path.join(d, "n.mp3")
        with patch.object(tts_service.edge_tts, "Communicate", _FakeCommunicate):
            with self.assertRaises(ConnectionError):
                asyncio.run(tts_service.TTSService.synthesize_edge_tts_single(
                    "단어 타이밍 시험 문장", output_file=out, with_word_boundaries=True))
        self.assertFalse(os.path.exists(out))   # 반쯤 쓴 파일이 남지 않는다


class BatchEdgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for name, sub in (("AUDIO_DIR", "audio"), ("ZIP_DIR", "zips")):
            (self.tmp / sub).mkdir()
            p = patch.object(tts_service, name, self.tmp / sub)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(tts_service, "merge_audio_files", lambda files, out: True)
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(tts_service.edge_tts, "Communicate", _FakeCommunicate)
        p.start()
        self.addCleanup(p.stop)

    def test_partial_failure_marks_only_failed_scene(self):
        scenes = [{"scene_num": 1, "narration": "첫 번째 정상 장면"}, {"scene_num": 2, "narration": "두 번째 실패 장면"}]
        res = tts_service.TTSService.generate_all_scenes_audio_batch(scenes, "주제", voice_id="edge_injoon")
        self.assertEqual(res["status"], "success")
        self.assertEqual([e["scene_num"] for e in res["errors"]], [2])
        ok, bad = res["scenes_audio"]
        self.assertTrue(ok["audio_url"])
        self.assertIsNone(bad["audio_url"])
        self.assertIn("ConnectionError", bad["error"])

    def test_all_failed_is_error_and_stale_files_do_not_count(self):
        topic_dir = tts_service.AUDIO_DIR / "주제"
        topic_dir.mkdir()
        (topic_dir / "scene_01.mp3").write_bytes(b"old")   # 지난번 결과
        scenes = [{"scene_num": 1, "narration": "첫 번째 실패 장면"}]
        res = tts_service.TTSService.generate_all_scenes_audio_batch(scenes, "주제", voice_id="edge_injoon")
        self.assertEqual(res["status"], "error")
        self.assertIn("ConnectionError", res["message"])
        self.assertFalse((topic_dir / "scene_01.mp3").exists())


if __name__ == "__main__":
    unittest.main()
