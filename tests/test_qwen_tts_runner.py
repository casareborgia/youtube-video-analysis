"""Qwen-TTS 실패를 숨기지 않는다 — 시스템 음성(say)으로 대체하지 않고, 실패 이유를 끝까지 전달한다."""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import qwen_tts_runner
import tts_service


def _run_runner(args):
    """runner 를 프로세스 안에서 돌려 (종료 코드, stdout, stderr) 를 돌려준다."""
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with patch.object(sys, "argv", ["qwen_tts_runner.py"] + args), \
         contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            qwen_tts_runner.main()
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
    return code, out.getvalue(), err.getvalue()


class RunnerFailureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.output = os.path.join(self.tmp, "out.wav")

    def test_model_failure_exits_nonzero_without_system_voice(self):
        # qwen_tts 를 불러올 수 없는 상황(이번 장애처럼 의존성이 깨진 경우)
        with patch.dict(sys.modules, {"qwen_tts": None}), \
             patch("subprocess.run", side_effect=AssertionError("say 로 대체하면 안 된다")) as run:
            code, stdout, stderr = _run_runner(["--mode", "clone", "--text", "안녕하세요", "--output", self.output])
        self.assertEqual(code, 1)
        result = json.loads(stdout.strip().splitlines()[-1])
        self.assertEqual(result["status"], "error")
        self.assertTrue(result["error"])
        self.assertIn("Qwen-TTS", stderr)
        self.assertFalse(os.path.exists(self.output))
        run.assert_not_called()

    def test_stale_output_is_removed_on_failure(self):
        with open(self.output, "wb") as f:
            f.write(b"old")
        with patch.dict(sys.modules, {"qwen_tts": None}):
            code, _, _ = _run_runner(["--mode", "preset", "--text", "안녕하세요", "--output", self.output])
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(self.output))   # 지난번 파일이 성공으로 오인되지 않게


class SynthesizeSpeechQwenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        p = patch.object(tts_service, "AUDIO_DIR", self.tmp)
        p.start()
        self.addCleanup(p.stop)

    def _proc(self, returncode, stdout="", stderr=""):
        r = MagicMock()
        r.returncode, r.stdout, r.stderr = returncode, stdout, stderr
        return r

    def test_runner_error_is_reported_with_reason(self):
        stale = self.tmp / "t_scene_01.wav"
        stale.write_bytes(b"old")
        proc = self._proc(1, stdout=json.dumps({"status": "error", "error": "ImportError: transformers 버전이 맞지 않습니다"}) + "\n")
        with patch.object(tts_service.subprocess, "run", return_value=proc):
            res = tts_service.TTSService.synthesize_speech("테스트 문장입니다", voice_id="my_voice", scene_index=1, topic_slug="t")
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["engine"], "qwen-tts")
        self.assertIn("transformers 버전이 맞지 않습니다", res["message"])
        self.assertFalse(stale.exists())

    def test_runner_error_without_json_uses_stderr(self):
        proc = self._proc(1, stdout="", stderr="Traceback ...\nRuntimeError: MPS out of memory\n")
        with patch.object(tts_service.subprocess, "run", return_value=proc):
            res = tts_service.TTSService.synthesize_speech("테스트 문장입니다", voice_id="docu_male", scene_index=2, topic_slug="t")
        self.assertEqual(res["status"], "error")
        self.assertIn("MPS out of memory", res["message"])

    def test_timeout_is_reported(self):
        with patch.object(tts_service.subprocess, "run", side_effect=tts_service.subprocess.TimeoutExpired(cmd="qwen", timeout=120)):
            res = tts_service.TTSService.synthesize_speech("테스트 문장입니다", voice_id="my_voice", scene_index=3, topic_slug="t")
        self.assertEqual(res["status"], "error")
        self.assertIn("시간", res["message"])

    def test_success_needs_exit_zero_and_file(self):
        def fake_run(cmd, **kw):
            Path(cmd[cmd.index("--output") + 1]).write_bytes(b"wav")
            return self._proc(0, stdout=json.dumps({"status": "success"}))
        with patch.object(tts_service.subprocess, "run", side_effect=fake_run):
            res = tts_service.TTSService.synthesize_speech("테스트 문장입니다", voice_id="my_voice", scene_index=4, topic_slug="t")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["engine"], "qwen-tts")
        self.assertTrue((self.tmp / res["filename"]).exists())


class BatchQwenTests(unittest.TestCase):
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
        self.scenes = [{"scene_num": 1, "narration": "첫 번째 장면입니다"}, {"scene_num": 2, "narration": "두 번째 장면입니다"}]

    def test_failed_scenes_are_marked_and_all_failed_is_error(self):
        fail = {"status": "error", "message": "Qwen-TTS 합성 실패: ImportError"}
        with patch.object(tts_service.TTSService, "synthesize_speech", return_value=fail):
            res = tts_service.TTSService.generate_all_scenes_audio_batch(self.scenes, "주제", voice_id="my_voice")
        self.assertEqual(res["status"], "error")
        self.assertIn("ImportError", res["message"])
        self.assertEqual([e["scene_num"] for e in res["errors"]], [1, 2])
        self.assertTrue(all(s.get("error") for s in res["scenes_audio"]))
        self.assertTrue(all(s.get("audio_url") is None for s in res["scenes_audio"]))

    def test_success_moves_audio_into_topic_folder(self):
        def ok(text, voice_id, scene_index, topic_slug):
            name = f"{topic_slug}_scene_{scene_index:02d}.wav"
            (tts_service.AUDIO_DIR / name).write_bytes(b"wav")
            return {"status": "success", "filename": name, "engine": "qwen-tts"}
        with patch.object(tts_service.TTSService, "synthesize_speech", side_effect=ok):
            res = tts_service.TTSService.generate_all_scenes_audio_batch(self.scenes, "주제", voice_id="my_voice")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["errors"], [])
        for s in res["scenes_audio"]:
            self.assertTrue(os.path.exists(s["audio_file"]), s["audio_file"])


class BatchApiTests(unittest.TestCase):
    def test_all_failed_batch_returns_500_with_reason(self):
        from fastapi.testclient import TestClient
        import app as app_module
        err = {"status": "error", "message": "Qwen-TTS 합성 실패: ImportError", "errors": [{"scene_num": 1, "message": "x"}]}
        with patch.object(tts_service.TTSService, "generate_all_scenes_audio_batch", return_value=err), \
             patch.object(app_module.TTSService, "generate_all_scenes_audio_batch", return_value=err):
            r = TestClient(app_module.app).post("/api/tts/generate-all-scenes",
                                                json={"scenes": [{"scene_num": 1, "narration": "장면"}], "voice_id": "my_voice", "topic": "t"})
        self.assertEqual(r.status_code, 500)
        self.assertIn("ImportError", r.json()["detail"])


if __name__ == "__main__":
    unittest.main()
