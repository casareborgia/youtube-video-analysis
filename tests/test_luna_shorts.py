"""루나 하이라이트 숏폼 파이프라인 테스트 (Phase B — feat/luna-shorts-highlight).

- pick_highlight_window: 합성 음량 곡선에서 최대 에너지 구간 선택, 페이드 제외, 짧은 곡 처리
- extract_audio_highlight: 측정 실패 폴백(45s), 수동 시작, ffmpeg 인자, track_data.shorts 기록
- build_luna_shorts_metadata / 플레이스홀더 치환
- upload_luna_to_youtube(with_shorts=True): 롱폼→숏폼 순서, 링크 삽입, 공개 시각 지연, 부분 실패 처리
- (ffmpeg 있을 때만) 실제 9:16 렌더 → 1080x1920, 60초 미만
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import luna_engine
import uploader


def _levels(total=180, loud_from=50, loud_to=95):
    """앞뒤는 조용(-40 LUFS), [loud_from, loud_to) 는 큼(-10 LUFS)."""
    return [(-10.0 if loud_from <= s < loud_to else -40.0) for s in range(total)]


class PickHighlightWindowTests(unittest.TestCase):
    def test_picks_loudest_window(self):
        start = luna_engine.pick_highlight_window(_levels(), 45, 180)
        self.assertIsNotNone(start)
        # 45초 창이 큰 구간(50~95) 안에 완전히 들어가야 한다
        self.assertEqual(start, 50)

    def test_respects_head_and_tail_skip(self):
        # 0~44 초가 가장 큰 경우에도 head_skip(10) 전에는 시작하지 않는다
        lv = _levels(180, 0, 45)
        self.assertGreaterEqual(luna_engine.pick_highlight_window(lv, 45, 180), 10)
        # 마지막 45초가 가장 큰 경우 tail_skip(15) 를 침범하지 않는다
        lv = _levels(180, 135, 180)
        start = luna_engine.pick_highlight_window(lv, 45, 180)
        self.assertLessEqual(start + 45, 180 - 15)

    def test_too_short_returns_none(self):
        self.assertIsNone(luna_engine.pick_highlight_window(_levels(60, 10, 30), 45, 60))


class ExtractHighlightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.lp = patch.object(luna_engine, "LUNA_DIR", self.tmp); self.lp.start(); self.addCleanup(self.lp.stop)
        os.makedirs(os.path.join(self.tmp, "luna_t"))
        self.audio = os.path.join(self.tmp, "luna_t", "audio.mp3")
        open(self.audio, "wb").write(b"\x00" * 10)
        self.track = {"track_id": "luna_t", "title": "T", "audio_file": self.audio, "duration_seconds": 180}
        self.calls = []

        def fake_run(cmd, **kw):
            self.calls.append(cmd)
            class R: returncode = 0; stderr = ""
            return R()
        self.rp = patch.object(luna_engine.subprocess, "run", side_effect=fake_run); self.rp.start(); self.addCleanup(self.rp.stop)
        self.dp = patch.object(luna_engine.producer, "audio_duration", return_value=180.0); self.dp.start(); self.addCleanup(self.dp.stop)

    def test_fallback_when_measurement_fails(self):
        with patch.object(luna_engine, "_measure_loudness_timeline", side_effect=RuntimeError("no ffmpeg")):
            out = luna_engine.extract_audio_highlight(self.track, duration=45)
        sh = out["shorts"]
        self.assertEqual((sh["start"], sh["end"], sh["method"]), (45.0, 90.0, "fallback"))
        cmd = self.calls[-1]
        self.assertIn("-ss", cmd); self.assertEqual(cmd[cmd.index("-ss") + 1], "45.000")
        self.assertEqual(cmd[cmd.index("-t") + 1], "45.000")
        self.assertTrue(cmd[-1].endswith("audio_shorts.mp3"))
        self.assertIn("afade=t=in", cmd[cmd.index("-af") + 1])
        # 입력은 마스터본(audio.mp3) — audio_raw 가 아니다
        self.assertEqual(cmd[cmd.index("-i") + 1], self.audio)
        # meta.json 에 저장됐는지
        saved = json.load(open(os.path.join(self.tmp, "luna_t", "meta.json"), encoding="utf-8"))
        self.assertEqual(saved["shorts"]["method"], "fallback")

    def test_energy_method_uses_loudest_window(self):
        with patch.object(luna_engine, "_measure_loudness_timeline", return_value=_levels()):
            out = luna_engine.extract_audio_highlight(self.track, duration=45)
        self.assertEqual(out["shorts"]["method"], "energy")
        self.assertEqual(out["shorts"]["start"], 50.0)

    def test_manual_start_override_and_clamp(self):
        out = luna_engine.extract_audio_highlight(self.track, duration=45, start_override=170)
        sh = out["shorts"]
        self.assertEqual(sh["method"], "manual")
        self.assertEqual(sh["start"], 135.0)  # 180-45 로 클램프
        self.assertLessEqual(sh["end"], 180.0)

    def test_duration_clamped_below_60(self):
        out = luna_engine.extract_audio_highlight(self.track, duration=90, start_override=0)
        self.assertLessEqual(out["shorts"]["duration"], 59)

    def test_reextract_marks_existing_video_stale(self):
        self.track["shorts"] = {"video_file": "x.mp4", "video_url": "/x.mp4"}
        out = luna_engine.extract_audio_highlight(self.track, duration=45, start_override=10)
        self.assertTrue(out["shorts"]["video_stale"])


class ShortsMetadataTests(unittest.TestCase):
    def test_title_has_shorts_tag_and_fits_100(self):
        track = {"title": "A" * 120, "genre": "Lo-Fi / Chillhop", "story": "s"}
        base = {"youtube_description": "p1\n\np2\n\np3\n\n[Lyrics / 가사]\nla", "youtube_tags": ["a"]}
        m = luna_engine.build_luna_shorts_metadata(track, base)
        self.assertLessEqual(len(m["youtube_title"]), 100)
        self.assertTrue(m["youtube_title"].endswith("#Shorts"))
        self.assertIn(luna_engine.LONGFORM_URL_PLACEHOLDER, m["youtube_description"])
        self.assertIn("#Shorts", m["youtube_description"])
        self.assertIn("#LoFi", m["youtube_description"])
        self.assertNotIn("[Lyrics", m["youtube_description"])
        self.assertIn("Shorts", m["youtube_tags"]); self.assertIn("YouTubeShorts", m["youtube_tags"])
        self.assertIn(luna_engine.LONGFORM_URL_PLACEHOLDER, m["pinned_comment"])

    def test_build_luna_metadata_includes_shorts_block(self):
        with patch.object(luna_engine.llm_client, "call_llm_json", side_effect=RuntimeError("down")):
            meta = luna_engine.build_luna_metadata({"title": "X", "genre": "Lo-Fi / Chillhop"})
        self.assertIn("shorts", meta)
        self.assertTrue(meta["shorts"]["youtube_title"].endswith("#Shorts"))

    def test_placeholder_fill(self):
        s = f"풀버전 {luna_engine.LONGFORM_URL_PLACEHOLDER} {luna_engine.PLAYLIST_URL_PLACEHOLDER}"
        self.assertEqual(luna_engine._fill_shorts_placeholders(s, "VID1"), "풀버전 https://youtu.be/VID1")
        self.assertIn("playlist?list=PL9", luna_engine._fill_shorts_placeholders(s, "VID1", "PL9"))

    def test_shift_publish_at(self):
        self.assertIsNone(luna_engine._shift_publish_at(None))
        self.assertEqual(luna_engine._shift_publish_at("2026-10-10T09:00:00+09:00"), "2026-10-10T09:10:00+09:00")


class UploadWithShortsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.lp = patch.object(luna_engine, "LUNA_DIR", self.tmp); self.lp.start(); self.addCleanup(self.lp.stop)
        d = os.path.join(self.tmp, "luna_u"); os.makedirs(d)
        for name in ("video.mp4", "video_shorts.mp4", "cover.jpg"):
            open(os.path.join(d, name), "wb").write(b"\x00")
        self.track = {
            "track_id": "luna_u", "title": "Song", "genre": "Lo-Fi / Chillhop",
            "video_file": os.path.join(d, "video.mp4"), "cover_file": os.path.join(d, "cover.jpg"),
            "metadata": {"youtube_title": "Long", "youtube_description": "desc", "youtube_tags": ["t"], "pinned_comment": "pin"},
            "shorts": {"video_file": os.path.join(d, "video_shorts.mp4"), "start": 45, "end": 90},
        }
        luna_engine.save_track(self.track)
        self.calls = []

    def _fake_upload(self, fail_on_call=None):
        def f(**kw):
            self.calls.append(kw)
            n = len(self.calls)
            if fail_on_call == n:
                raise RuntimeError("quota")
            return {"video_id": f"VID{n}", "url": f"https://youtu.be/VID{n}", "publish_at": kw.get("publish_at"), "comment_posted": True, "warnings": []}
        return f

    def test_longform_then_shorts_with_link_and_delay(self):
        with patch.object(uploader, "upload_video", side_effect=self._fake_upload()):
            res = luna_engine.upload_luna_to_youtube("luna_u", privacy_status="private", publish_at="2026-10-10T09:00:00+09:00", playlist_id="PL1", with_shorts=True)
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(self.calls[0]["video_path"].endswith("video.mp4"))
        second = self.calls[1]
        self.assertTrue(second["video_path"].endswith("video_shorts.mp4"))
        self.assertIn("https://youtu.be/VID1", second["description"])
        self.assertIn("https://youtu.be/VID1", second["pinned_comment"])
        self.assertIn("playlist?list=PL1", second["pinned_comment"])
        self.assertTrue(second["title"].endswith("#Shorts"))
        self.assertEqual(second["publish_at"], "2026-10-10T09:10:00+09:00")  # 롱폼보다 뒤
        self.assertEqual(second["privacy"], "private")
        self.assertIsNone(second["thumbnail_path"])
        self.assertEqual(res["video_id"], "VID1")
        self.assertEqual(res["shorts"]["video_id"], "VID2")
        saved = luna_engine.load_track("luna_u")
        self.assertEqual(saved["shorts"]["youtube"]["longform_video_id"], "VID1")

    def test_default_without_shorts_is_single_upload(self):
        with patch.object(uploader, "upload_video", side_effect=self._fake_upload()):
            res = luna_engine.upload_luna_to_youtube("luna_u")
        self.assertEqual(len(self.calls), 1)
        self.assertIsNone(res["shorts"])

    def test_shorts_failure_keeps_longform_result(self):
        with patch.object(uploader, "upload_video", side_effect=self._fake_upload(fail_on_call=2)):
            res = luna_engine.upload_luna_to_youtube("luna_u", with_shorts=True)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["video_id"], "VID1")
        self.assertIsNone(res["shorts"])
        self.assertTrue(any("숏폼" in w for w in res["warnings"]))
        saved = luna_engine.load_track("luna_u")
        self.assertEqual(saved["uploaded_video_id"], "VID1")
        self.assertIn("quota", saved["shorts"]["upload_error"])

    def test_longform_failure_skips_shorts(self):
        with patch.object(uploader, "upload_video", side_effect=self._fake_upload(fail_on_call=1)):
            with self.assertRaises(RuntimeError):
                luna_engine.upload_luna_to_youtube("luna_u", with_shorts=True)
        self.assertEqual(len(self.calls), 1)

    def test_missing_shorts_video_is_reported_not_fatal(self):
        os.remove(os.path.join(self.tmp, "luna_u", "video_shorts.mp4"))
        with patch.object(uploader, "upload_video", side_effect=self._fake_upload()):
            res = luna_engine.upload_luna_to_youtube("luna_u", with_shorts=True)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(res["video_id"], "VID1")
        self.assertIsNone(res["shorts"])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg 필요")
class RealFfmpegRenderTests(unittest.TestCase):
    def test_render_produces_vertical_short_video(self):
        tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        d = os.path.join(tmp, "luna_r"); os.makedirs(d)
        audio = os.path.join(d, "audio.mp3"); cover = os.path.join(d, "cover.jpg")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-c:a", "libmp3lame", "-b:a", "96k", audio], check=True, capture_output=True)
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=0x334455:s=640x360:d=1", "-frames:v", "1", cover], check=True, capture_output=True)
        track = {"track_id": "luna_r", "title": "Render Test", "audio_file": audio, "cover_file": cover, "duration_seconds": 6}
        with patch.object(luna_engine, "LUNA_DIR", tmp):
            track = luna_engine.extract_audio_highlight(track, duration=15, start_override=1)
            track = luna_engine.render_luna_shorts_video(track)
        out = track["shorts"]["video_file"]
        self.assertTrue(os.path.exists(out))
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration", "-of", "json", out], capture_output=True, text=True, check=True)
        info = json.loads(probe.stdout)
        self.assertEqual((info["streams"][0]["width"], info["streams"][0]["height"]), (1080, 1920))
        self.assertLess(float(info["format"]["duration"]), 60)
        # 실제 ebur128 측정 경로도 한 번 태운다
        with patch.object(luna_engine, "LUNA_DIR", tmp):
            levels = luna_engine._measure_loudness_timeline(audio)
        self.assertGreaterEqual(len(levels), 5)


if __name__ == "__main__":
    unittest.main()
