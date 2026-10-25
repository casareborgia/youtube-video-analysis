"""쇼츠 엔진 S-1 단위 테스트 — Remotion 래퍼·ffmpeg 폴백·디스패처·자막 유틸. Node 없이 독립 통과."""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import shorts_engine


def _ok_runner(record):
    def runner(cmd, cwd=None, timeout=None, capture_output=None, text=None):
        record["cmd"] = cmd
        record["cwd"] = cwd
        out_file = cmd[cmd.index("render") + 3]
        with open(out_file, "wb") as f:
            f.write(b"rendered")
        res = MagicMock()
        res.returncode, res.stdout, res.stderr = 0, "ok", ""
        return res
    return runner


class ShortsEngineBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.shorts_dir = os.path.join(self.tmp, "shorts")
        self.remotion = os.path.join(self.tmp, "remotion")
        os.makedirs(self.shorts_dir)
        os.makedirs(self.remotion)
        for name, val in (("SHORTS_DIR", self.shorts_dir), ("REMOTION_DIR", self.remotion)):
            p = patch.object(shorts_engine, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.sid = "shorts_test_01"
        self.jd = os.path.join(self.shorts_dir, self.sid)
        os.makedirs(self.jd)
        self.imgs = []
        for i in (1, 2, 3):
            p = os.path.join(self.jd, f"scene_{i:02d}.png")
            with open(p, "wb") as f:
                f.write(b"png")
            self.imgs.append(p)
        # 잡 폴더 밖의 나레이션 → 복사돼 들어와야 한다
        self.outside_dir = os.path.join(self.tmp, "outside")
        os.makedirs(self.outside_dir)
        self.narr = os.path.join(self.outside_dir, "narration.mp3")
        with open(self.narr, "wb") as f:
            f.write(b"mp3")
        self.job = {
            "shorts_id": self.sid,
            "storyboard": {
                "hook_text": "이거 모르면 손해",
                "hook_seconds": 3,
                "scenes": [
                    {"scene_num": 1, "seconds": 6, "image": self.imgs[0], "motion": "zoom_in"},
                    {"scene_num": 2, "seconds": 6, "image": self.imgs[1]},
                    {"scene_num": 3, "seconds": 6, "image": self.imgs[2], "motion": "pan_left"},
                ],
                "end_tag": {"text": "구독", "subtext": "다음 편", "seconds": 2},
            },
            "captions": shorts_engine.proportional_captions("첫 번째 문장입니다", 0, 2000)
            + shorts_engine.proportional_captions("두 번째 문장", 2200, 4000),
            "audio": {"narration": self.narr, "bgm": None, "bgm_volume": 0.2},
            "brand": "SHORTS LAB",
            "accent": "#ff0000",
        }

    def enable_node(self):
        os.makedirs(os.path.join(self.remotion, "node_modules"), exist_ok=True)


class RemotionWrapperTests(ShortsEngineBase):
    def test_missing_node_modules_raises(self):
        runner = MagicMock()
        with self.assertRaises(RuntimeError) as cm:
            shorts_engine.render_shorts_remotion(self.job, runner=runner)
        self.assertIn("미설치", str(cm.exception))
        runner.assert_not_called()

    def test_invalid_job_id_rejected(self):
        self.enable_node()
        self.job["shorts_id"] = "../etc"
        with self.assertRaises(ValueError):
            shorts_engine.render_shorts_remotion(self.job, runner=MagicMock())

    def test_over_60s_rejected_before_render(self):
        self.enable_node()
        self.job["storyboard"]["scenes"][0]["seconds"] = 50
        runner = MagicMock()
        with self.assertRaises(RuntimeError) as cm:
            shorts_engine.render_shorts_remotion(self.job, runner=runner)
        self.assertIn("상한", str(cm.exception))
        runner.assert_not_called()

    def test_props_mapping_and_asset_import(self):
        self.enable_node()
        rec = {}
        job = shorts_engine.render_shorts_remotion(self.job, runner=_ok_runner(rec))
        self.assertEqual(rec["cwd"], self.remotion)
        self.assertEqual(rec["cmd"][:5], ["npx", "remotion", "render", "src/index.ts", "ShortsScene"])
        with open(rec["cmd"][rec["cmd"].index("--props") + 1], encoding="utf-8") as f:
            props = json.load(f)
        self.assertEqual(props["jobId"], self.sid)
        self.assertEqual([s["image"] for s in props["scenes"]],
                         [f"shorts/{self.sid}/scene_01.png", f"shorts/{self.sid}/scene_02.png", f"shorts/{self.sid}/scene_03.png"])
        self.assertEqual([s["motion"] for s in props["scenes"]], ["zoom_in", "zoom_out", "pan_left"])
        self.assertEqual(props["hookText"], "이거 모르면 손해")
        self.assertEqual(props["endTag"]["seconds"], 2.0)
        self.assertEqual(props["accent"], "#ff0000")
        self.assertEqual(props["bgmVolume"], 0.2)
        self.assertIsNone(props["bgmAudio"])
        # 잡 폴더 밖 나레이션은 복사돼 public 상대 경로로 들어온다
        self.assertEqual(props["narrationAudio"], f"shorts/{self.sid}/narration_narration.mp3")
        self.assertTrue(os.path.exists(os.path.join(self.jd, "narration_narration.mp3")))
        # 자막 토큰은 text/startMs/endMs/pageBreakAfter 만 전달
        self.assertEqual(set(props["captions"][0].keys()), {"text", "startMs", "endMs"})
        self.assertTrue(props["captions"][2].get("pageBreakAfter"))
        # 결과 기록
        self.assertEqual(job["render"]["renderer_used"], "remotion")
        self.assertTrue(job["render"]["file"].endswith("final_9x16.mp4"))
        self.assertEqual(job["status"], "rendered")
        saved = shorts_engine.load_job(self.sid)
        self.assertEqual(saved["render"]["url"], f"/data/shorts/{self.sid}/final_9x16.mp4")

    def test_transition_and_sfx_props(self):
        self.enable_node()
        scenes = self.job["storyboard"]["scenes"]
        scenes[1]["transition"] = "slide"
        scenes[2]["transition"] = "spin"   # 모르는 전환은 빼고 보낸다(Remotion 기본 fade)
        self.job["sfx"] = True
        rec = {}
        shorts_engine.render_shorts_remotion(self.job, runner=_ok_runner(rec))
        with open(rec["cmd"][rec["cmd"].index("--props") + 1], encoding="utf-8") as f:
            props = json.load(f)
        self.assertNotIn("transition", props["scenes"][0])
        self.assertEqual(props["scenes"][1]["transition"], "slide")
        self.assertNotIn("transition", props["scenes"][2])
        self.assertTrue(props["sfx"])

    def test_sfx_off_by_default(self):
        self.enable_node()
        rec = {}
        shorts_engine.render_shorts_remotion(self.job, runner=_ok_runner(rec))
        with open(rec["cmd"][rec["cmd"].index("--props") + 1], encoding="utf-8") as f:
            self.assertFalse(json.load(f)["sfx"])

    def test_render_failure_surfaces_stderr(self):
        self.enable_node()

        def bad(cmd, cwd=None, timeout=None, capture_output=None, text=None):
            res = MagicMock()
            res.returncode, res.stdout, res.stderr = 1, "", "Error: browser crashed"
            return res

        with self.assertRaises(RuntimeError) as cm:
            shorts_engine.render_shorts_remotion(self.job, runner=bad)
        self.assertIn("browser crashed", str(cm.exception))


class SceneKindTests(ShortsEngineBase):
    def test_non_image_kinds_need_no_image_and_pass_fields(self):
        self.enable_node()
        self.job["storyboard"]["scenes"] = [
            {"scene_num": 1, "seconds": 6, "kind": "text_card", "title": "로봇이 스스로 연습한다", "subtitle": "Gemini 4 Argon"},
            {"scene_num": 2, "seconds": 6, "kind": "bar_chart", "title": "ERQA", "unit": "%", "decimals": 1,
             "bars": [{"label": "Argon", "value": 87, "highlight": True}, {"label": "Opus", "value": 82.3}]},
            {"scene_num": 3, "seconds": 6, "kind": "compare", "rows": [{"label": "성공률", "from": 56, "to": 75, "unit": "%"}]},
            {"scene_num": 4, "seconds": 6, "kind": "stat_card", "value": 18, "unit": "자유도", "label": "Spot"},
            {"scene_num": 5, "seconds": 6, "image": self.imgs[0]},
        ]
        self.job["storyboard"]["end_tag"] = None
        rec = {}
        shorts_engine.render_shorts_remotion(self.job, runner=_ok_runner(rec))
        with open(rec["cmd"][rec["cmd"].index("--props") + 1], encoding="utf-8") as f:
            props = json.load(f)
        kinds = [s["kind"] for s in props["scenes"]]
        self.assertEqual(kinds, ["text_card", "bar_chart", "compare", "stat_card", "image"])
        self.assertNotIn("image", props["scenes"][0])
        self.assertEqual(props["scenes"][1]["bars"][0]["highlight"], True)
        self.assertEqual(props["scenes"][2]["rows"][0]["to"], 75)
        self.assertEqual(props["scenes"][3]["unit"], "자유도")
        self.assertTrue(props["scenes"][4]["image"].endswith("scene_01.png"))

    def test_flyover_props(self):
        self.enable_node()
        self.job["storyboard"]["scenes"] = [
            {"scene_num": 1, "seconds": 6, "kind": "flyover", "time_of_day": "sunrise", "seed": 4, "title": "진주 남강"},
            {"scene_num": 2, "seconds": 6, "image": self.imgs[0]},
        ]
        self.job["storyboard"]["end_tag"] = None
        rec = {}
        shorts_engine.render_shorts_remotion(self.job, runner=_ok_runner(rec))
        with open(rec["cmd"][rec["cmd"].index("--props") + 1], encoding="utf-8") as f:
            props = json.load(f)
        fly = props["scenes"][0]
        self.assertEqual((fly["kind"], fly["time_of_day"], fly["seed"], fly["title"]), ("flyover", "sunrise", 4, "진주 남강"))
        self.assertNotIn("image", fly)

    def test_scene3d_props_copy_model_and_drop_missing(self):
        self.enable_node()
        model = os.path.join(self.tmp, "robot.glb")
        with open(model, "wb") as f:
            f.write(b"glTF")
        self.job["storyboard"]["scenes"] = [
            {"scene_num": 1, "seconds": 6, "kind": "scene3d", "scene3d": shorts_engine.scene3d_spec.normalize_scene3d({
                "environment": "studio", "objects": [{"type": "model", "src": model, "scale": 2},
                                                     {"type": "model", "src": os.path.join(self.tmp, "none.glb")},
                                                     {"type": "text", "text": "신제품"}]}, 1)},
            {"scene_num": 2, "seconds": 6, "image": self.imgs[0]},
        ]
        self.job["storyboard"]["end_tag"] = None
        rec = {}
        job = shorts_engine.render_shorts_remotion(self.job, runner=_ok_runner(rec))
        with open(rec["cmd"][rec["cmd"].index("--props") + 1], encoding="utf-8") as f:
            props = json.load(f)
        objs = props["scenes"][0]["scene3d"]["objects"]
        self.assertEqual([o["type"] for o in objs], ["model", "text"])          # 없는 모델 파일은 빠진다
        self.assertEqual(objs[0]["src"], f"shorts/{self.sid}/scene_01_model_robot.glb")
        self.assertTrue(os.path.exists(os.path.join(self.jd, "scene_01_model_robot.glb")))
        self.assertTrue(any("none.glb" in w for w in job.get("warnings", [])))
        self.assertNotIn("image", props["scenes"][0])

    def test_unknown_kind_rejected(self):
        self.enable_node()
        self.job["storyboard"]["scenes"][0]["kind"] = "hologram"
        with self.assertRaises(RuntimeError) as cm:
            shorts_engine.render_shorts_remotion(self.job, runner=MagicMock())
        self.assertIn("kind", str(cm.exception))

    def test_ffmpeg_fallback_uses_color_for_kind_scenes(self):
        calls = []

        def runner(cmd, capture_output=None, text=None, timeout=None):
            calls.append(cmd)
            res = MagicMock()
            res.returncode, res.stdout, res.stderr = 0, "", ""
            # 단색 배경 png 를 실제로 만들지 않으므로 존재 검사를 위해 빈 파일 생성
            if "-frames:v" in cmd and cmd[-1].endswith(".png"):
                open(cmd[-1], "wb").close()
            return res

        self.job["storyboard"]["scenes"][1] = {"scene_num": 2, "seconds": 6, "kind": "stat_card", "value": 87, "unit": "%"}
        with patch.object(shorts_engine.producer, "ffmpeg_path", return_value="/fake/ffmpeg"), \
             patch.object(shorts_engine, "_ffmpeg_has_filter", return_value=False):
            job = shorts_engine.render_shorts_ffmpeg(self.job, runner=runner)
        color_cmds = [c for c in calls if "-f" in c and "lavfi" in c and any("color=c=" in x for x in c)]
        self.assertEqual(len(color_cmds), 1)
        self.assertTrue(any("타이포" in w for w in job["render"]["warnings"]))


class DispatcherTests(ShortsEngineBase):
    def test_remotion_failure_falls_back_to_ffmpeg(self):
        self.enable_node()
        with patch.object(shorts_engine, "render_shorts_remotion", side_effect=RuntimeError("browser crashed")), \
             patch.object(shorts_engine, "render_shorts_ffmpeg") as ffm, \
             patch.object(shorts_engine, "probe_video", return_value={"width": 1080}):
            def fake_ffmpeg(job, progress_cb=None, runner=None):
                job["render"] = {"renderer_used": "ffmpeg", "file": os.path.join(self.jd, "final_9x16.mp4"), "warnings": []}
                return job
            ffm.side_effect = fake_ffmpeg
            job = shorts_engine.render_shorts(self.job, renderer="remotion")
        self.assertEqual(job["render"]["renderer_used"], "ffmpeg")
        self.assertIn("browser crashed", job["render"]["fallback_reason"])
        self.assertEqual(job["render"]["probe"]["width"], 1080)

    def test_missing_node_falls_back(self):
        with patch.object(shorts_engine, "render_shorts_ffmpeg") as ffm, \
             patch.object(shorts_engine, "probe_video", return_value={}):
            ffm.side_effect = lambda job, progress_cb=None, runner=None: {**job, "render": {"renderer_used": "ffmpeg", "file": "x"}}
            job = shorts_engine.render_shorts(self.job)
        self.assertEqual(job["render"]["renderer_used"], "ffmpeg")
        self.assertIn("미설치", job["render"]["fallback_reason"])

    def test_input_errors_do_not_fall_back(self):
        self.enable_node()
        self.job["storyboard"]["scenes"][0]["seconds"] = 59
        with patch.object(shorts_engine, "render_shorts_ffmpeg") as ffm:
            with self.assertRaises(RuntimeError):
                shorts_engine.render_shorts(self.job, renderer="remotion")
            ffm.assert_not_called()

    def test_env_ffmpeg_skips_remotion(self):
        self.enable_node()
        with patch.dict(os.environ, {"SHORTS_RENDERER": "ffmpeg"}), \
             patch.object(shorts_engine, "render_shorts_remotion") as rem, \
             patch.object(shorts_engine, "render_shorts_ffmpeg") as ffm, \
             patch.object(shorts_engine, "probe_video", return_value={}):
            ffm.side_effect = lambda job, progress_cb=None, runner=None: {**job, "render": {"renderer_used": "ffmpeg", "file": "x"}}
            job = shorts_engine.render_shorts(self.job)
        rem.assert_not_called()
        self.assertEqual(job["renderer_requested"], "ffmpeg")
        self.assertNotIn("fallback_reason", job["render"])


class FfmpegFallbackCommandTests(ShortsEngineBase):
    def test_ffmpeg_fallback_command_shape(self):
        calls = []

        def runner(cmd, capture_output=None, text=None, timeout=None):
            calls.append(cmd)
            res = MagicMock()
            res.returncode, res.stdout, res.stderr = 0, "", ""
            return res

        with patch.object(shorts_engine.producer, "ffmpeg_path", return_value="/fake/ffmpeg"), \
             patch.object(shorts_engine, "_ffmpeg_has_filter", return_value=True), \
             patch.object(shorts_engine.producer, "find_font", return_value="/System/Library/Fonts/AppleSDGothicNeo.ttc"):
            job = shorts_engine.render_shorts_ffmpeg(self.job, runner=runner)
        # 씬 3개 + 최종 1개
        self.assertEqual(len(calls), 4)
        final = calls[-1]
        fc = final[final.index("-filter_complex") + 1]
        self.assertIn("xfade=transition=fade", fc)
        self.assertIn("subtitles=", fc)
        self.assertIn("FontName=Apple SD Gothic Neo", fc)
        self.assertIn("apad", fc)  # 나레이션 경로
        self.assertNotIn("sidechaincompress", fc)  # bgm 없음
        self.assertEqual(final[final.index("-t") + 1], "20.000")  # Σseconds + 엔드 태그 (xfade 로 짧아지지 않음)
        self.assertIn("offset=6.000", fc)
        self.assertIn("offset=12.000", fc)
        # 마지막이 아닌 씬은 다음 씬 페이드(0.4초)만큼 길게 만든다
        first_scene = calls[0]
        self.assertEqual(first_scene[first_scene.index("-t") + 1], "6.400")
        self.assertTrue(os.path.exists(os.path.join(self.jd, "captions.srt")))
        self.assertEqual(job["render"]["renderer_used"], "ffmpeg")
        self.assertTrue(any("폴백" in w for w in job["render"]["warnings"]))
        # 마지막 씬은 엔드 태그 길이만큼 길어진다
        last_scene = calls[2]
        self.assertEqual(last_scene[last_scene.index("-t") + 1], "8.000")


class CaptionUtilTests(unittest.TestCase):
    def test_proportional_captions_cover_span_in_order(self):
        caps = shorts_engine.proportional_captions("가나다 라 마바사아", 1000, 4000)
        self.assertEqual([c["text"] for c in caps], ["가나다", " 라", " 마바사아"])
        self.assertEqual(caps[0]["startMs"], 1000)
        self.assertEqual(caps[-1]["endMs"], 4000)
        self.assertTrue(caps[-1]["pageBreakAfter"])
        for a, b in zip(caps, caps[1:]):
            self.assertLessEqual(a["endMs"], b["startMs"] + 1)
        # 긴 어절이 더 긴 구간을 받는다
        self.assertGreater(caps[2]["endMs"] - caps[2]["startMs"], caps[1]["endMs"] - caps[1]["startMs"])

    def test_proportional_captions_empty(self):
        self.assertEqual(shorts_engine.proportional_captions("", 0, 1000), [])
        self.assertEqual(shorts_engine.proportional_captions("가", 1000, 1000), [])

    def test_srt_pages(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        caps = shorts_engine.proportional_captions("첫 문장", 0, 1000) + shorts_engine.proportional_captions("둘째 문장 입니다", 1100, 4000)
        p = shorts_engine.captions_to_srt(caps, os.path.join(tmp, "c.srt"), page_ms=1200)
        body = open(p, encoding="utf-8").read()
        self.assertIn("1\n00:00:00,000 --> 00:00:01,000\n첫 문장", body)
        # 둘째 문장은 1.2초를 넘기므로 Remotion 의 틱톡식 규칙과 같이 두 페이지로 나뉜다
        self.assertIn("둘째 문장\n", body)
        self.assertIn("입니다\n", body)
        self.assertEqual(body.count("-->"), 3)
        # 페이지를 넉넉히 주면 한 큐로 합쳐진다
        p2 = shorts_engine.captions_to_srt(caps, os.path.join(tmp, "c2.srt"), page_ms=5000)
        self.assertIn("둘째 문장 입니다", open(p2, encoding="utf-8").read())

    def test_total_seconds(self):
        job = {"storyboard": {"scenes": [{"seconds": 5}, {"seconds": 7.5}], "end_tag": {"seconds": 2}}}
        self.assertEqual(shorts_engine.total_seconds(job), 14.5)


if __name__ == "__main__":
    unittest.main()
