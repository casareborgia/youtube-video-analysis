"""Remotion 컴포지터 스파이크 단위 테스트 (Phase C-1b-2). Node 없이 독립 통과 가능."""

import os
import json
import shutil
import tempfile
import unittest
import subprocess
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

import luna_engine
import choonsik_bga
import app


class RemotionPythonWrapperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        self.lp = patch.object(luna_engine, "LUNA_DIR", self.tmp)
        self.lp.start()
        self.addCleanup(self.lp.stop)

        self.fake_remotion = os.path.join(self.tmp, "fake_remotion")
        os.makedirs(self.fake_remotion)
        self.rp = patch.object(choonsik_bga, "REMOTION_DIR", self.fake_remotion)
        self.rp.start()
        self.addCleanup(self.rp.stop)

        self.t_dir = os.path.join(self.tmp, "track_rem")
        os.makedirs(os.path.join(self.t_dir, "bga"))

        # 마스터링 전 원본(audio.mp3)과 베가 마스터본(audio_mastered.wav)을 둘 다 두고,
        # track["audio_file"] 이 가리키는 마스터본이 쓰이는지 검증한다.
        with open(os.path.join(self.t_dir, "audio.mp3"), "wb") as f:
            f.write(b"fake_raw_audio")
        self.audio = os.path.join(self.t_dir, "audio_mastered.wav")
        with open(self.audio, "wb") as f:
            f.write(b"fake_mastered_audio")

        self.loop_unit = os.path.join(self.t_dir, "bga", "loop_unit.mp4")
        with open(self.loop_unit, "wb") as f:
            f.write(b"fake_loop_unit")

        self.track = {
            "track_id": "track_rem",
            "title": "Bleeding Blueprints (빗물에 번진 청사진)",
            "genre": "Emotional Piano Solo",
            "audio_file": self.audio,
            "duration_seconds": 120.0,
            "bga": {
                "loop_unit_file": self.loop_unit
            }
        }
        luna_engine.save_track(self.track)

    def test_missing_node_modules_raises_runtime_error(self):
        fake_runner = MagicMock()
        with self.assertRaises(RuntimeError) as cm:
            choonsik_bga.render_bga_remotion(self.track, runner=fake_runner)
        self.assertIn("미설치", str(cm.exception))
        fake_runner.assert_not_called()

    def test_missing_loop_unit_raises_runtime_error(self):
        # node_modules 디렉터리 생성
        os.makedirs(os.path.join(self.fake_remotion, "node_modules"))
        os.remove(self.loop_unit)
        self.track["bga"]["loop_unit_file"] = ""

        fake_runner = MagicMock()
        with self.assertRaises(RuntimeError) as cm:
            choonsik_bga.render_bga_remotion(self.track, runner=fake_runner)
        self.assertIn("loop_unit", str(cm.exception))
        fake_runner.assert_not_called()

    def test_missing_audio_file_raises_file_not_found(self):
        os.makedirs(os.path.join(self.fake_remotion, "node_modules"))
        os.remove(self.audio)
        fake_runner = MagicMock()
        with self.assertRaises(FileNotFoundError):
            choonsik_bga.render_bga_remotion(self.track, runner=fake_runner)
        fake_runner.assert_not_called()

    def test_successful_render_invocation_and_metadata_save(self):
        os.makedirs(os.path.join(self.fake_remotion, "node_modules"))

        captured = {}

        def fake_runner(cmd, cwd, timeout, capture_output, text):
            # cmd[5] 가 출력 파일 경로 (out_file)
            out_file = cmd[5]
            captured["cmd"] = cmd
            captured["cwd"] = cwd
            captured["props"] = json.loads(cmd[cmd.index("--props") + 1])
            with open(out_file, "wb") as f:
                f.write(b"rendered_mp4_bytes")
            res = MagicMock()
            res.returncode = 0
            res.stdout = "Rendered frames successfully"
            res.stderr = ""
            return res

        res = choonsik_bga.render_bga_remotion(self.track, runner=fake_runner)
        rem_meta = res.get("bga", {}).get("remotion", {})
        # 호출 계약: remotion/ 에서 실행, LunaBga 컴포지션, props 에 트랙·길이 정보
        self.assertEqual(captured["cwd"], self.fake_remotion)
        self.assertEqual(captured["cmd"][:5], ["npx", "remotion", "render", "src/index.ts", "LunaBga"])
        props = captured["props"]
        self.assertEqual(props["trackId"], "track_rem")
        self.assertIn("durationSeconds", props)
        self.assertIn("loopUnitSeconds", props)
        self.assertEqual(props["title"], "Bleeding Blueprints")
        self.assertIn("빗물에 번진 청사진", props["subtitle"])
        # 베가 마스터본(audio_mastered.wav)을 써야 하고, 원본 audio.mp3 를 쓰면 안 된다
        self.assertEqual(props["audio"], "luna/track_rem/audio_mastered.wav")
        self.assertTrue(os.path.exists(rem_meta["file"]))
        self.assertTrue(rem_meta["file"].endswith("video_remotion.mp4"))
        self.assertEqual(rem_meta["url"], "/data/luna_music/track_rem/video_remotion.mp4")
        self.assertGreater(rem_meta["rendered_at"], 0)

        # 저장된 track 확인
        saved = luna_engine.load_track("track_rem")
        self.assertEqual(saved["bga"]["remotion"]["file"], rem_meta["file"])

    def test_render_failure_raises_runtime_error_with_stderr(self):
        os.makedirs(os.path.join(self.fake_remotion, "node_modules"))

        def fake_runner(cmd, cwd, timeout, capture_output, text):
            res = MagicMock()
            res.returncode = 1
            res.stdout = ""
            res.stderr = "Error: Out of memory or browser crashed"
            return res

        with self.assertRaises(RuntimeError) as cm:
            choonsik_bga.render_bga_remotion(self.track, runner=fake_runner)
        self.assertIn("browser crashed", str(cm.exception))


class RemotionApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        self.lp = patch.object(luna_engine, "LUNA_DIR", self.tmp)
        self.lp.start()
        self.addCleanup(self.lp.stop)

        self.fake_remotion = os.path.join(self.tmp, "fake_remotion")
        os.makedirs(self.fake_remotion)
        self.rp = patch.object(choonsik_bga, "REMOTION_DIR", self.fake_remotion)
        self.rp.start()
        self.addCleanup(self.rp.stop)

        self.client = TestClient(app.app)

        self.t_dir = os.path.join(self.tmp, "track_api")
        os.makedirs(os.path.join(self.t_dir, "bga"))
        self.audio = os.path.join(self.t_dir, "audio.mp3")
        with open(self.audio, "wb") as f:
            f.write(b"audio")
        self.loop_unit = os.path.join(self.t_dir, "bga", "loop_unit.mp4")
        with open(self.loop_unit, "wb") as f:
            f.write(b"loop")

        self.track = {
            "track_id": "track_api",
            "title": "API Track",
            "audio_file": self.audio,
            "bga": {"loop_unit_file": self.loop_unit}
        }
        luna_engine.save_track(self.track)

    def test_api_render_remotion_track_not_found_returns_404(self):
        resp = self.client.post("/api/luna/bga/render-remotion", json={"track_id": "nonexistent"})
        self.assertEqual(resp.status_code, 404)

    def test_api_render_remotion_missing_node_modules_returns_503(self):
        # node_modules 디렉터리 없음 -> 503
        resp = self.client.post("/api/luna/bga/render-remotion", json={"track_id": "track_api"})
        self.assertEqual(resp.status_code, 503)
        self.assertIn("미설치", resp.text)

    def test_api_render_remotion_missing_loop_unit_returns_400(self):
        os.makedirs(os.path.join(self.fake_remotion, "node_modules"))
        os.remove(self.loop_unit)
        self.track["bga"]["loop_unit_file"] = ""
        luna_engine.save_track(self.track)

        resp = self.client.post("/api/luna/bga/render-remotion", json={"track_id": "track_api"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("loop_unit", resp.text)

    def test_api_render_remotion_success_returns_200(self):
        os.makedirs(os.path.join(self.fake_remotion, "node_modules"))

        def fake_render(track_data, **kwargs):
            track_data.setdefault("bga", {})["remotion"] = {
                "file": "/dummy/video_remotion.mp4",
                "url": "/data/luna_music/track_api/video_remotion.mp4"
            }
            return track_data

        with patch.object(choonsik_bga, "render_bga_remotion", side_effect=fake_render):
            resp = self.client.post("/api/luna/bga/render-remotion", json={"track_id": "track_api"})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("remotion", data.get("bga", {}))


class RemotionNodeSmokeTests(unittest.TestCase):
    @unittest.skipUnless(
        os.path.exists(os.path.join(luna_engine.BASE_DIR, "remotion", "node_modules")),
        "실제 remotion/node_modules 가 있을 때만 실행"
    )
    def test_real_remotion_compositions_contains_lunabga(self):
        remotion_dir = os.path.join(luna_engine.BASE_DIR, "remotion")
        res = subprocess.run(
            ["npx", "remotion", "compositions", "src/index.ts"],
            cwd=remotion_dir,
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("LunaBga", res.stdout)


if __name__ == "__main__":
    unittest.main()
