"""춘식 BGA (Veo 3.1) 파이프라인 단위 테스트 (Phase C-1a)."""

import os
import json
import time
import shutil
import tempfile
import unittest
import subprocess
from unittest.mock import patch

from fastapi.testclient import TestClient

import luna_engine
import choonsik_bga
import app


class FakeOperation:
    def __init__(self, name, video_bytes=b"fake_video_mp4_bytes", fail_rai=False, always_pending=False):
        self.name = name
        self.done = False
        self.error = None
        self.poll_count = 0
        self.video_bytes = video_bytes
        self.fail_rai = fail_rai
        self.always_pending = always_pending
        self.response = None


class FakeClient:
    def __init__(self, fail_shot_index=-1, always_pending=False):
        self.fail_shot_index = fail_shot_index
        self.always_pending = always_pending
        self.call_count = 0
        self.models = self
        self.operations = self

    def generate_videos(self, model, prompt, image, config):
        self.call_count += 1
        idx = self.call_count - 1
        fail_rai = (idx == self.fail_shot_index)
        return FakeOperation(
            name=f"projects/p/operations/op_{idx}",
            fail_rai=fail_rai,
            always_pending=self.always_pending
        )

    def get(self, op):
        op.poll_count += 1
        if not op.always_pending and op.poll_count >= 2:
            op.done = True
            if op.fail_rai:
                class R:
                    generated_videos = []
                    rai_media_filtered_reasons = ["sensitive content detected"]
                op.response = R()
            else:
                class Vid:
                    def __init__(self, b):
                        self.video_bytes = b
                class R:
                    def __init__(self, b):
                        self.generated_videos = [Vid(b)]
                op.response = R(op.video_bytes)
        return op


class BgaPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.lp = patch.object(luna_engine, "LUNA_DIR", self.tmp)
        self.lp.start()
        self.addCleanup(self.lp.stop)

    def test_plan_fallback_on_llm_exception(self):
        track = {
            "track_id": "test_track",
            "visual_prompt": "A tranquil starry lake",
            "genre": "ambient",
        }
        with patch.object(choonsik_bga.llm_client, "call_llm_json", side_effect=RuntimeError("LLM down")):
            shots = choonsik_bga.plan_bga_shots(track, n_shots=3)

        self.assertEqual(len(shots), 3)
        self.assertTrue(all(s["source"] == "template" for s in shots))
        # 3종 카메라 서로 다름
        cameras = [s["camera"] for s in shots]
        self.assertEqual(len(set(cameras)), 3)
        # 접미사 포함 및 ambient 색감
        for s in shots:
            self.assertIn(choonsik_bga.BGA_PROMPT_SUFFIX, s["prompt"])
            self.assertIn("cool desaturated deep blue", s["prompt"])

    def test_plan_genre_grading_citypop(self):
        track = {
            "track_id": "test_citypop",
            "visual_prompt": "Neon city drive",
            "genre": "citypop",
        }
        with patch.object(choonsik_bga.llm_client, "call_llm_json", side_effect=RuntimeError("LLM down")):
            shots = choonsik_bga.plan_bga_shots(track, n_shots=3)
        for s in shots:
            self.assertIn("teal and magenta neon", s["prompt"])

    def test_plan_fallback_when_llm_returns_insufficient_shots(self):
        track = {
            "track_id": "test_track",
            "visual_prompt": "Space nebula",
            "genre": "ambient",
        }
        # LLM이 샷 2개만 반환하는 경우
        fake_resp = {"shots": [{"camera": "c1", "prompt": "p1"}, {"camera": "c2", "prompt": "p2"}]}
        with patch.object(choonsik_bga.llm_client, "call_llm_json", return_value=(fake_resp, "")):
            shots = choonsik_bga.plan_bga_shots(track, n_shots=3)
        self.assertEqual(len(shots), 3)
        self.assertTrue(all(s["source"] == "template" for s in shots))

    def test_plan_llm_success_with_suffix_and_camera_reinforced(self):
        track = {
            "track_id": "test_track",
            "visual_prompt": "Space nebula",
            "genre": "ambient",
        }
        fake_resp = {
            "shots": [
                {"camera": "custom 1", "prompt": "Nebula drifting"},
                {"camera": "custom 2", "prompt": "Stars glowing"},
                {"camera": "custom 3", "prompt": "Comet passing"},
            ]
        }
        with patch.object(choonsik_bga.llm_client, "call_llm_json", return_value=(fake_resp, "")):
            shots = choonsik_bga.plan_bga_shots(track, n_shots=3)
        self.assertEqual(len(shots), 3)
        self.assertTrue(all(s["source"] == "llm" for s in shots))
        for i, s in enumerate(shots):
            self.assertIn(choonsik_bga.BGA_PROMPT_SUFFIX, s["prompt"])
            self.assertEqual(s["camera"], choonsik_bga.BGA_CAMERA_MOVES[i])


class BgaCostAndUsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.usage_file = os.path.join(self.tmp, "bga_usage.json")
        self.up = patch.object(choonsik_bga, "BGA_USAGE_FILE", self.usage_file)
        self.up.start()
        self.addCleanup(self.up.stop)

    def test_estimate_bga_cost_default_and_1080p(self):
        c720 = choonsik_bga.estimate_bga_cost(3, resolution="720p")
        self.assertEqual(c720["usd"], 1.92)
        self.assertEqual(c720["rate_source"], "secondary")

        with patch.dict(os.environ, {"BGA_RESOLUTION": "1080p"}):
            c1080 = choonsik_bga.estimate_bga_cost(3)
            self.assertEqual(c1080["usd"], 2.4)

    def test_usage_counter_lifecycle(self):
        # 파일 없음 -> 0
        self.assertEqual(choonsik_bga.get_today_usage(), 0)
        # 증가
        choonsik_bga._increment_usage(2)
        self.assertEqual(choonsik_bga.get_today_usage(), 2)
        choonsik_bga._increment_usage(3)
        self.assertEqual(choonsik_bga.get_today_usage(), 5)

        # 다른 날짜 키와 분리
        data = json.load(open(self.usage_file, encoding="utf-8"))
        data["2025-01-01"] = 10
        with open(self.usage_file, "w", encoding="utf-8") as f:
            json.dump(data, f)
        self.assertEqual(choonsik_bga.get_today_usage(), 5)


class BgaGenerateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.lp = patch.object(luna_engine, "LUNA_DIR", self.tmp)
        self.lp.start()
        self.addCleanup(self.lp.stop)

        self.usage_file = os.path.join(self.tmp, "bga_usage.json")
        self.up = patch.object(choonsik_bga, "BGA_USAGE_FILE", self.usage_file)
        self.up.start()
        self.addCleanup(self.up.stop)

        self.t_dir = os.path.join(self.tmp, "luna_gen")
        os.makedirs(self.t_dir)
        self.cover = os.path.join(self.t_dir, "cover.jpg")
        with open(self.cover, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 20)
        self.track = {
            "track_id": "luna_gen",
            "title": "BGA Gen Track",
            "cover_file": self.cover,
            "bga": {
                "shots": [
                    {"index": 0, "prompt": "Shot 0", "camera": "cam0"},
                    {"index": 1, "prompt": "Shot 1", "camera": "cam1"},
                    {"index": 2, "prompt": "Shot 2", "camera": "cam2"},
                ]
            }
        }

    def test_dry_run_no_client_call(self):
        fake = FakeClient()
        res = choonsik_bga.generate_bga_clips(self.track, dry_run=True, client=fake)
        self.assertEqual(fake.call_count, 0)
        self.assertTrue(res["bga"]["dry_run"])
        self.assertIn("estimate", res["bga"])

    def test_generate_clips_success_lifecycle(self):
        fake = FakeClient()
        sleep_calls = []
        res = choonsik_bga.generate_bga_clips(
            self.track,
            client=fake,
            sleep_fn=lambda s: sleep_calls.append(s)
        )
        self.assertEqual(fake.call_count, 3)
        self.assertEqual(choonsik_bga.get_today_usage(), 3)
        clips = res["bga"]["clips"]
        self.assertEqual(len(clips), 3)
        for i in range(3):
            c = clips[str(i)]
            self.assertEqual(c["status"], "done")
            self.assertTrue(os.path.exists(c["file"]))
            self.assertIsNotNone(c["operation_name"])
        # 폴링 확인
        self.assertGreater(len(sleep_calls), 0)

    def test_second_shot_rai_filtered(self):
        fake = FakeClient(fail_shot_index=1)
        res = choonsik_bga.generate_bga_clips(self.track, client=fake, sleep_fn=lambda s: None)
        clips = res["bga"]["clips"]
        self.assertEqual(clips["0"]["status"], "done")
        self.assertEqual(clips["1"]["status"], "failed")
        self.assertIn("필터됨", clips["1"]["error"])
        self.assertEqual(clips["2"]["status"], "done")
        self.assertEqual(res["bga"]["done_count"], 2)

    def test_daily_cap_exceeded_before_calling(self):
        choonsik_bga._increment_usage(11)
        fake = FakeClient()
        with patch.dict(os.environ, {"BGA_MAX_CLIPS_PER_DAY": "12"}):
            with self.assertRaises(RuntimeError) as cm:
                choonsik_bga.generate_bga_clips(self.track, client=fake)
            self.assertIn("상한", str(cm.exception))
        self.assertEqual(fake.call_count, 0)

    def test_too_many_shots_raises_value_error(self):
        fake = FakeClient()
        shots4 = [{"index": i, "prompt": f"p{i}"} for i in range(4)]
        with self.assertRaises(ValueError):
            choonsik_bga.generate_bga_clips(self.track, shots=shots4, client=fake)
        self.assertEqual(fake.call_count, 0)

    def test_missing_gcp_project_raises_runtime_error(self):
        with patch.dict(os.environ, {}, clear=True):
            if "GCP_PROJECT" in os.environ:
                del os.environ["GCP_PROJECT"]
            with self.assertRaises(RuntimeError) as cm:
                choonsik_bga.generate_bga_clips(self.track, client=None)
            self.assertIn("GCP_PROJECT", str(cm.exception))

    def test_timeout_marks_shot_failed(self):
        fake = FakeClient(always_pending=True)
        # BGA_POLL_TIMEOUT = 0 으로 주어 즉시 타임아웃
        with patch.object(choonsik_bga, "BGA_POLL_TIMEOUT", 0):
            with self.assertRaises(RuntimeError):  # 모든 샷 실패로 최종 RuntimeError
                choonsik_bga.generate_bga_clips(self.track, client=fake, sleep_fn=lambda s: None)
        clips = self.track["bga"]["clips"]
        for i in range(3):
            self.assertEqual(clips[str(i)]["status"], "failed")


class BgaApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.lp = patch.object(luna_engine, "LUNA_DIR", self.tmp)
        self.lp.start()
        self.addCleanup(self.lp.stop)

        self.usage_file = os.path.join(self.tmp, "bga_usage.json")
        self.up = patch.object(choonsik_bga, "BGA_USAGE_FILE", self.usage_file)
        self.up.start()
        self.addCleanup(self.up.stop)

        self.t_dir = os.path.join(self.tmp, "api_track")
        os.makedirs(self.t_dir)
        self.cover = os.path.join(self.t_dir, "cover.jpg")
        with open(self.cover, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 20)
        self.track = {
            "track_id": "api_track",
            "title": "API Track",
            "cover_file": self.cover,
            "bga": {"shots": [{"index": 0, "prompt": "P0"}]}
        }
        luna_engine.save_track(self.track)
        self.client = TestClient(app.app)

    def test_api_generate_requires_confirm(self):
        with patch.object(choonsik_bga, "_make_vertex_client") as mk:
            resp = self.client.post("/api/luna/bga/generate", json={"track_id": "api_track"})
            self.assertEqual(resp.status_code, 400)
            self.assertIn("confirm=true", resp.text)
            mk.assert_not_called()

    def test_api_generate_confirm_and_dry_run_success(self):
        resp = self.client.post(
            "/api/luna/bga/generate",
            json={"track_id": "api_track", "confirm": True, "dry_run": True}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["bga"]["dry_run"])

    def test_api_generate_daily_cap_exceeded_returns_429(self):
        choonsik_bga._increment_usage(12)
        with patch.dict(os.environ, {"BGA_MAX_CLIPS_PER_DAY": "12"}):
            resp = self.client.post(
                "/api/luna/bga/generate",
                json={"track_id": "api_track", "confirm": True}
            )
            self.assertEqual(resp.status_code, 429)

    def test_api_get_usage_returns_200(self):
        resp = self.client.get("/api/luna/bga/usage")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("today", data)
        self.assertIn("cap", data)
        self.assertEqual(data["rate_source"], "secondary")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe 필요")
class BgaRealFfmpegRenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.lp = patch.object(luna_engine, "LUNA_DIR", self.tmp)
        self.lp.start()
        self.addCleanup(self.lp.stop)

        self.t_dir = os.path.join(self.tmp, "real_render")
        os.makedirs(os.path.join(self.t_dir, "bga"))

        # 오디오 10초 생성
        self.audio = os.path.join(self.t_dir, "audio.mp3")
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=10",
            "-c:a", "libmp3lame", "-b:a", "96k", self.audio
        ], check=True, capture_output=True)

        # 합성 클립 3개 (각 3초, 색 다름, 320x180)
        colors = ["0x334455", "0x553344", "0x445533"]
        self.clip_files = []
        for i, col in enumerate(colors):
            cf = os.path.join(self.t_dir, "bga", f"clip_{i}.mp4")
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={col}:s=320x180:d=3",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", cf
            ], check=True, capture_output=True)
            self.clip_files.append(cf)

        # 기존 video.mp4 (백업 검증용)
        self.existing_video = os.path.join(self.t_dir, "video.mp4")
        with open(self.existing_video, "wb") as f:
            f.write(b"existing_cover_video_content")

        self.track = {
            "track_id": "real_render",
            "title": "Real Render Track",
            "audio_file": self.audio,
            "duration_seconds": 10,
            "video_source": "cover",
            "bga": {
                "clips": {
                    "0": {"status": "done", "file": self.clip_files[0]},
                    "1": {"status": "done", "file": self.clip_files[1]},
                    "2": {"status": "done", "file": self.clip_files[2]},
                }
            }
        }
        luna_engine.save_track(self.track)

    def test_render_bga_loop_lifecycle_and_backup(self):
        res = choonsik_bga.render_bga_loop(self.track, with_waveform=False, upscale=False)
        out_v = res["video_file"]
        self.assertTrue(os.path.exists(out_v))
        self.assertEqual(res["video_source"], "bga")

        # 켄번즈 백업 생성 확인
        backup = os.path.join(self.t_dir, "video_cover_backup.mp4")
        self.assertTrue(os.path.exists(backup))

        # ffprobe 검증
        probe = subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height:format=duration",
            "-of", "json", out_v
        ], capture_output=True, text=True, check=True)
        info = json.loads(probe.stdout)
        dur = float(info["format"]["duration"])
        self.assertAlmostEqual(dur, 10.0, delta=0.8)
        self.assertEqual(info["streams"][0]["width"], 320)
        self.assertEqual(info["streams"][0]["height"], 180)

        # loop_unit 길이 검증: 3 + 3 + 3 - 2 = 7초 (오차 0.5초 이내)
        loop_unit = res["bga"]["loop_unit_file"]
        self.assertTrue(os.path.exists(loop_unit))
        probe_unit = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "json", loop_unit
        ], capture_output=True, text=True, check=True)
        unit_dur = float(json.loads(probe_unit.stdout)["format"]["duration"])
        self.assertAlmostEqual(unit_dur, 7.0, delta=0.5)

    def test_render_bga_loop_upscale_and_waveform(self):
        res = choonsik_bga.render_bga_loop(self.track, with_waveform=True, upscale=True)
        out_v = res["video_file"]
        probe = subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "json", out_v
        ], capture_output=True, text=True, check=True)
        info = json.loads(probe.stdout)
        self.assertEqual(info["streams"][0]["width"], 1920)
        self.assertEqual(info["streams"][0]["height"], 1080)

    def test_render_bga_loop_insufficient_clips_raises_error(self):
        # 클립 1개만 남김
        self.track["bga"]["clips"] = {
            "0": {"status": "done", "file": self.clip_files[0]},
            "1": {"status": "failed", "file": None},
            "2": {"status": "failed", "file": None},
        }
        with self.assertRaises(RuntimeError) as cm:
            choonsik_bga.render_bga_loop(self.track)
        self.assertIn("2개 미만", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
