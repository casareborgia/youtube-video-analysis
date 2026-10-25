"""U-2 오디오 2.0 — BGM 진입점·BGM 준비(말소리 대역 비우기)·나레이션 EQ·덕킹 배율 전달."""

import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import producer
import shorts_engine

try:   # unittest discover -s tests 로 돌 때는 최상위 이름을 먼저 쓴다
    from test_shorts_engine import ShortsS2Base, _fake_merge, _fake_synth
except ImportError:
    from tests.test_shorts_engine import ShortsS2Base, _fake_merge, _fake_synth

FFMPEG = shutil.which("ffmpeg")


def _ramp(quiet_until, length, quiet=-40.0, loud=-14.0, step=0.1):
    """조용한 인트로 뒤 큰 소리가 이어지는 단기 음량 표본."""
    n = int(length / step)
    return [(round(i * step, 2), quiet if i * step < quiet_until else loud) for i in range(1, n + 1)]


class EntryOffsetTests(unittest.TestCase):
    def test_skips_quiet_intro(self):
        # S(3초 창)는 11초에 처음 큰 값 → 1.5초 당겨 9.5초부터
        self.assertEqual(shorts_engine.bgm_entry_offset("x", 30.0, samples=_ramp(11.0, 180.0)), 9.5)

    def test_loud_from_start_is_zero(self):
        self.assertEqual(shorts_engine.bgm_entry_offset("x", 30.0, samples=_ramp(0.0, 180.0)), 0.0)

    def test_intro_under_min_is_zero(self):
        self.assertEqual(shorts_engine.bgm_entry_offset("x", 30.0, samples=_ramp(2.0, 180.0)), 0.0)   # 0.5초 < 1초

    def test_never_runs_past_track_end(self):
        # 큰 소리가 늦게(150초) 나와도 영상 50초가 끝까지 들어가도록 길이-50-0.5 에서 멈춘다
        self.assertEqual(shorts_engine.bgm_entry_offset("x", 50.0, samples=_ramp(150.0, 180.0)), 129.5)

    def test_track_shorter_than_video_is_zero(self):
        self.assertEqual(shorts_engine.bgm_entry_offset("x", 50.0, samples=_ramp(10.0, 40.0)), 0.0)

    def test_no_samples_is_zero(self):
        self.assertEqual(shorts_engine.bgm_entry_offset("x", 30.0, samples=[]), 0.0)
        self.assertEqual(shorts_engine.bgm_entry_offset("x", 30.0, samples=[(0.1, -120.7)] * 50), 0.0)

    def test_parses_ebur128_log(self):
        log = ("[Parsed_ebur128_0 @ 0x1] t: 0.0999773  TARGET:-23 LUFS    M:-120.7 S:-120.7     I: -70.0 LUFS       LRA:   0.0 LU\n"
               "[Parsed_ebur128_0 @ 0x1] t: 3.1        TARGET:-23 LUFS    M: -18.2 S: -19.5     I: -19.0 LUFS       LRA:   1.0 LU\n")
        runner = MagicMock(return_value=subprocess.CompletedProcess([], 0, "", log))
        with tempfile.NamedTemporaryFile(suffix=".mp3") as f, patch.object(producer, "ffmpeg_path", lambda: "ffmpeg"):
            self.assertEqual(shorts_engine.short_term_loudness(f.name, runner=runner), [(0.0999773, -120.7), (3.1, -19.5)])


class FilterAndPrepareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.src = os.path.join(self.tmp, "song.mp3")
        with open(self.src, "wb") as f:
            f.write(b"mp3")

    def test_prepare_bgm_command(self):
        def runner(cmd, **kw):
            with open(cmd[-1], "wb") as f:
                f.write(b"out")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        runner = MagicMock(side_effect=runner)
        dst = os.path.join(self.tmp, "bgm_prepared.mp3")
        self.assertEqual(shorts_engine.prepare_bgm("ffmpeg", self.src, dst, 9.5, 40.0, runner=runner), dst)
        cmd = runner.call_args[0][0]
        self.assertEqual(cmd[cmd.index("-ss") + 1], "9.50")
        self.assertEqual(cmd[cmd.index("-t") + 1], "41.00")                 # 영상 길이 + 1초
        self.assertEqual(cmd[cmd.index("-af") + 1], shorts_engine.BGM_CARVE_FILTER)

    def test_prepare_bgm_without_carve_and_failures(self):
        runner = MagicMock(return_value=subprocess.CompletedProcess([], 1, "", "err"))
        dst = os.path.join(self.tmp, "b.mp3")
        self.assertIsNone(shorts_engine.prepare_bgm("ffmpeg", self.src, dst, 0, 30, carve=False, runner=runner))
        self.assertNotIn("-af", runner.call_args[0][0])
        self.assertIsNone(shorts_engine.prepare_bgm(None, self.src, dst, 0, 30))
        self.assertIsNone(shorts_engine.prepare_bgm("ffmpeg", os.path.join(self.tmp, "none.mp3"), dst, 0, 30))

    def test_filter_inplace_keeps_original_on_failure(self):
        runner = MagicMock(return_value=subprocess.CompletedProcess([], 1, "", "boom"))
        self.assertFalse(shorts_engine._filter_inplace("ffmpeg", self.src, "anull", runner=runner))
        with open(self.src, "rb") as f:
            self.assertEqual(f.read(), b"mp3")

    def test_voice_eq_env_switch(self):
        with patch.dict(os.environ, {"SHORTS_VOICE_EQ": "0"}):
            self.assertFalse(shorts_engine.voice_eq_enabled())
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SHORTS_VOICE_EQ", None)
            self.assertTrue(shorts_engine.voice_eq_enabled())

    @unittest.skipUnless(FFMPEG, "ffmpeg 필요")
    def test_real_ffmpeg_eq_keeps_duration_and_entry_found(self):
        tone = os.path.join(self.tmp, "tone.mp3")
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:d=3", "-c:a", "libmp3lame", tone], check=True)
        before = producer.audio_duration(tone)
        self.assertTrue(shorts_engine._filter_inplace(FFMPEG, tone, shorts_engine.VOICE_EQ_FILTER))
        self.assertAlmostEqual(producer.audio_duration(tone), before, delta=0.06)   # 자막 타이밍이 밀리지 않는다
        # 조용한 12초 + 큰 50초 → 진입점은 12초 근처
        song = os.path.join(self.tmp, "song_real.mp3")
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=220:d=12", "-f", "lavfi", "-i", "sine=f=330:d=50",
                        "-filter_complex", "[0:a]volume=0.01[a];[1:a]volume=0.8[b];[a][b]concat=n=2:v=0:a=1", "-c:a", "libmp3lame", song], check=True)
        with patch.object(producer, "ffmpeg_path", lambda: FFMPEG):
            off = shorts_engine.bgm_entry_offset(song, 30.0)
        self.assertGreater(off, 9.0)
        self.assertLess(off, 13.0)


class SynthesizeIntegrationTests(ShortsS2Base):
    def make_job(self, n=3):
        plan = self.save_plan(n=n)
        return shorts_engine.build_job_from_plan(plan["plan_id"])

    def test_prepared_bgm_and_offset_recorded(self):
        job = self.make_job(3)
        bgm = os.path.join(self.tmp, "song.mp3")
        with open(bgm, "wb") as f:
            f.write(b"mp3")
        prepared = {}

        def fake_prepare(ff, src, dst, offset, duration, carve=True, runner=None):
            prepared.update(src=src, offset=offset, duration=duration)
            with open(dst, "wb") as f:
                f.write(b"cut")
            return dst

        levels = {"narration.mp3": -20.0, "bgm_prepared.mp3": -12.0}
        with patch.object(shorts_engine, "bgm_entry_offset", lambda path, duration: 9.5), \
             patch.object(shorts_engine, "prepare_bgm", fake_prepare):
            job = shorts_engine.synthesize_job_audio(job, synth=_fake_synth(True, 6.0), merger=_fake_merge,
                                                     bgm_picker=lambda tid: {"track_id": "t1", "file": bgm, "title": "Lofi"},
                                                     lufs_probe=lambda path, seconds=None: levels[os.path.basename(path)])
        audio = job["audio"]
        self.assertEqual(prepared["src"], bgm)                                # 원곡은 읽기만
        self.assertEqual(prepared["offset"], 9.5)
        self.assertTrue(audio["bgm"].endswith("bgm_prepared.mp3"))
        self.assertEqual(audio["bgm_source"], bgm)
        self.assertEqual(audio["bgm_offset"], 9.5)
        self.assertEqual(audio["bgm_volume"], shorts_engine.bgm_volume_for(-20.0, -12.0))   # 준비된 구간으로 잰다
        self.assertEqual(audio["bgm_duck_boost"], shorts_engine.BGM_DUCK_BOOST)
        self.assertFalse(audio["voice_eq"])                                   # 테스트 환경은 ffmpeg 없음

    def test_falls_back_to_original_when_prepare_fails(self):
        job = self.make_job(3)
        bgm = os.path.join(self.tmp, "song.mp3")
        with open(bgm, "wb") as f:
            f.write(b"mp3")
        with patch.object(shorts_engine, "bgm_entry_offset", lambda path, duration: 9.5):
            job = shorts_engine.synthesize_job_audio(job, synth=_fake_synth(True, 6.0), merger=_fake_merge,
                                                     bgm_picker=lambda tid: {"track_id": "t1", "file": bgm, "title": "Lofi"},
                                                     lufs_probe=lambda path, seconds=None: -15.0)
        self.assertEqual(job["audio"]["bgm"], bgm)
        self.assertEqual(job["audio"]["bgm_offset"], 0.0)

    def test_voice_eq_applied_to_merged_narration(self):
        job = self.make_job(2)
        calls = []
        with patch.object(producer, "ffmpeg_path", lambda: "ffmpeg"), \
             patch.object(shorts_engine, "_pad_audio", lambda ff, src, dst, pad: src), \
             patch.object(shorts_engine, "_filter_inplace", lambda ff, path, af: calls.append((os.path.basename(path), af)) or True):
            job = shorts_engine.synthesize_job_audio(job, synth=_fake_synth(True, 5.0), merger=_fake_merge, bgm_picker=lambda tid: None)
        self.assertEqual(calls, [("narration.mp3", shorts_engine.VOICE_EQ_FILTER)])
        self.assertTrue(job["audio"]["voice_eq"])

    def test_props_carry_duck_boost(self):
        job = self.make_job(2)
        job = shorts_engine.synthesize_job_audio(job, synth=_fake_synth(True, 5.0), merger=_fake_merge, bgm_picker=lambda tid: None)
        for s in job["storyboard"]["scenes"]:
            s["kind"] = "text_card"
            s["title"] = "제목"
        self.assertEqual(shorts_engine.build_remotion_props(job)["bgmBoost"], shorts_engine.BGM_DUCK_BOOST)
        job["audio"]["bgm_duck_boost"] = 3.0
        self.assertEqual(shorts_engine.build_remotion_props(job)["bgmBoost"], 3.0)


if __name__ == "__main__":
    unittest.main()
