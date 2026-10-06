"""사운드 엔지니어 베가(vega_engine) 단위·통합 테스트.

- 합성 신호(numpy 사인파)만 사용하고 실제 음원 파일과 LLM 호출은 쓰지 않는다.
- pedalboard 등 선택 의존성이 없는 환경에서는 DSP 테스트를 건너뛰고, 비활성 경로만 검증한다.
"""

import os
import json
import shutil
import tempfile
import unittest
import warnings
from unittest import mock

import numpy as np

warnings.filterwarnings("ignore", message=".*Using `httpx` with `starlette.testclient`.*")

import vega_engine

SR = 48000


def _synthetic_stereo(seconds=8.0, level=0.3, sr=SR, seed=0):
    t = np.arange(int(sr * seconds)) / sr
    rng = np.random.default_rng(seed)
    left = level * np.sin(2 * np.pi * 220 * t) + 0.1 * np.sin(2 * np.pi * 3000 * t) + 0.01 * rng.standard_normal(t.size)
    right = level * np.sin(2 * np.pi * 220 * t + 0.3) + 0.1 * np.sin(2 * np.pi * 5000 * t) + 0.01 * rng.standard_normal(t.size)
    return np.stack([left, right]).astype(np.float32)


def _assert_valid_audio(tc, out, inp):
    tc.assertEqual(out.shape, inp.shape)
    tc.assertEqual(out.dtype, np.float32)
    tc.assertTrue(np.all(np.isfinite(out)))
    tc.assertLessEqual(float(np.max(np.abs(out))), 1.0)


class VegaSchemaAndPresetTests(unittest.TestCase):
    def test_every_luna_genre_has_a_valid_preset(self):
        import luna_engine
        for g in luna_engine.GENRE_PRESETS:
            d = vega_engine.preset_for_genre(g["id"])
            self.assertIsInstance(d, vega_engine.MasteringDecisions)
            self.assertLessEqual(d.target_lufs, -8.0)
            self.assertLessEqual(d.limiter.ceiling_dbtp, -0.1)

    def test_unknown_genre_falls_back_to_default(self):
        d = vega_engine.preset_for_genre("no-such-genre")
        self.assertEqual(d.target_lufs, vega_engine.GENRE_MASTER_PRESETS["default"]["target_lufs"])

    def test_sleep_preset_is_quieter_than_beat_genres(self):
        self.assertLess(vega_engine.preset_for_genre("sleep").target_lufs,
                        vega_engine.preset_for_genre("synthwave").target_lufs)

    def test_schema_rejects_out_of_range_values(self):
        raw = json.loads(vega_engine.preset_for_genre("lofi").model_dump_json())
        raw["target_lufs"] = +3.0  # 불가능한 값
        with self.assertRaises(Exception):
            vega_engine.MasteringDecisions.model_validate(raw)
        raw = json.loads(vega_engine.preset_for_genre("lofi").model_dump_json())
        raw["limiter"]["ceiling_dbtp"] = 0.5  # 0 dBTP 초과 금지
        with self.assertRaises(Exception):
            vega_engine.MasteringDecisions.model_validate(raw)

    def test_describe_presets_lists_all(self):
        rows = vega_engine.describe_presets()
        self.assertEqual(len(rows), len(vega_engine.GENRE_MASTER_PRESETS))
        self.assertIn("target_lufs", rows[0])


class VegaDecideTests(unittest.TestCase):
    def test_preset_only_mode_skips_llm(self):
        with mock.patch.object(vega_engine.llm_client, "call_llm_json", side_effect=AssertionError("must not be called")):
            d, src, note = vega_engine.decide({"is_silent": False}, "lofi", use_llm=False)
        self.assertEqual(src, "preset")

    def test_llm_failure_falls_back_to_preset(self):
        with mock.patch.object(vega_engine.llm_client, "call_llm_json", side_effect=RuntimeError("offline")):
            d, src, note = vega_engine.decide({"is_silent": False, "integrated_lufs": -20}, "jazz", use_llm=True)
        self.assertEqual(src, "preset")
        self.assertIn("프리셋", note)
        self.assertEqual(d.target_lufs, vega_engine.preset_for_genre("jazz").target_lufs)

    def test_llm_out_of_range_falls_back_to_preset(self):
        bad = json.loads(vega_engine.preset_for_genre("lofi").model_dump_json())
        bad["compressor"]["ratio"] = 99
        with mock.patch.object(vega_engine.llm_client, "call_llm_json", return_value=(bad, "raw")):
            d, src, note = vega_engine.decide({"is_silent": False}, "lofi", use_llm=True)
        self.assertEqual(src, "preset")
        self.assertIn("허용 범위", note)

    def test_llm_valid_response_is_used(self):
        good = json.loads(vega_engine.preset_for_genre("lofi").model_dump_json())
        good["target_lufs"] = -13.0
        good["reasoning"] = "테스트 사유"
        with mock.patch.object(vega_engine.llm_client, "call_llm_json", return_value=(good, "raw")):
            d, src, note = vega_engine.decide({"is_silent": False}, "lofi", use_llm=True)
        self.assertEqual(src, "llm")
        self.assertEqual(d.target_lufs, -13.0)
        self.assertEqual(d.reasoning, "테스트 사유")

    def test_silent_input_keeps_preset_without_llm(self):
        with mock.patch.object(vega_engine.llm_client, "call_llm_json", side_effect=AssertionError("must not be called")):
            d, src, note = vega_engine.decide({"is_silent": True}, "lofi", use_llm=True)
        self.assertEqual(src, "preset")


@unittest.skipUnless(vega_engine.is_available(), "pedalboard/pyloudnorm/soundfile/scipy 미설치")
class VegaDspTests(unittest.TestCase):
    def test_analyze_returns_finite_metrics(self):
        a = _synthetic_stereo()
        m = vega_engine.analyze(a, SR)
        for k in ("integrated_lufs", "true_peak_dbtp", "crest_factor_db", "dynamic_range_db",
                  "rms_sub_db", "rms_low_db", "rms_mid_db", "rms_high_db",
                  "spectral_centroid_hz", "spectral_flatness", "stereo_width", "low_end_correlation"):
            self.assertIn(k, m)
            self.assertTrue(np.isfinite(m[k]), k)
        self.assertFalse(m["is_silent"])
        self.assertGreater(m["low_end_correlation"], 0.8)  # 거의 동위상 저음

    def test_analyze_silence(self):
        m = vega_engine.analyze(np.zeros((2, SR), dtype=np.float32), SR)
        self.assertTrue(m["is_silent"])

    def test_true_peak_is_measured_per_channel(self):
        # 한쪽 채널만 큰 신호: 채널을 합쳐 재면 -6dB 낮게 나온다. 채널별 측정이면 0dB 근처.
        n = SR
        hot = np.zeros((2, n), dtype=np.float32)
        hot[0] = 0.99 * np.sin(2 * np.pi * 1000 * np.arange(n) / SR)
        self.assertGreater(vega_engine._true_peak_dbtp(hot), -1.0)

    def test_process_hits_target_loudness_and_ceiling(self):
        a = _synthetic_stereo(seconds=12.0)
        for genre in ("lofi", "sleep", "synthwave", "citypop"):
            d = vega_engine.preset_for_genre(genre)
            out, log = vega_engine.process(a, SR, d)
            _assert_valid_audio(self, out, a)
            after = vega_engine.analyze(out, SR)
            self.assertLessEqual(after["true_peak_dbtp"], d.limiter.ceiling_dbtp + 0.1, genre)
            # 목표 음량에서 ±1 LU 안 (리미터가 많이 물면 아래로 벗어날 수 있으나 위로는 안 된다)
            self.assertLessEqual(after["integrated_lufs"], d.target_lufs + 0.5, genre)
            self.assertGreaterEqual(after["integrated_lufs"], d.target_lufs - 1.5, genre)

    def test_process_raises_quiet_input(self):
        a = (_synthetic_stereo() * 0.05).astype(np.float32)  # 전체를 -26 dB 낮춘 조용한 입력
        before = vega_engine.analyze(a, SR)["integrated_lufs"]
        out, _ = vega_engine.process(a, SR, vega_engine.preset_for_genre("lofi"))
        after = vega_engine.analyze(out, SR)["integrated_lufs"]
        self.assertGreater(after, before + 6.0)

    def test_process_edge_cases(self):
        d = vega_engine.preset_for_genre("default")
        # 무음
        z = np.zeros((2, SR), dtype=np.float32)
        out, log = vega_engine.process(z, SR, d)
        _assert_valid_audio(self, out, z)
        self.assertEqual(log.get("skipped"), "silent")
        # 아주 짧은 입력 (0.1초)
        short = _synthetic_stereo(seconds=0.1)
        out, _ = vega_engine.process(short, SR, d)
        _assert_valid_audio(self, out, short)
        # 풀스케일 입력
        hot = np.clip(_synthetic_stereo(level=0.99), -0.99, 0.99).astype(np.float32)
        out, _ = vega_engine.process(hot, SR, d)
        _assert_valid_audio(self, out, hot)
        self.assertLessEqual(vega_engine.analyze(out, SR)["true_peak_dbtp"], d.limiter.ceiling_dbtp + 0.1)

    def test_saturator_mix_zero_is_identity(self):
        a = _synthetic_stereo().astype(np.float64)
        out = vega_engine._apply_saturator(a, vega_engine.SaturatorSettings(drive_db=6, mix=0.0))
        np.testing.assert_array_equal(out, a)


@unittest.skipUnless(vega_engine.is_available(), "pedalboard/pyloudnorm/soundfile/scipy 미설치")
class VegaMasterTrackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="vega_test_")
        self.track_id = "luna_test_0001"
        tdir = os.path.join(self.tmp, self.track_id)
        os.makedirs(tdir)
        self.raw_path = os.path.join(tdir, "audio.wav")
        vega_engine.write_audio(_synthetic_stereo(seconds=6.0), SR, self.raw_path, 16)
        self.track = {"track_id": self.track_id, "genre": "lofi", "mood": "dawn",
                      "audio_file": self.raw_path, "audio_url": f"/data/luna_music/{self.track_id}/audio.wav"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_master_track_preserves_raw_and_switches_audio_file(self):
        out = vega_engine.master_track(dict(self.track), use_llm=False, luna_dir=self.tmp)
        m = out["mastering"]
        self.assertEqual(m["status"], "done", m)
        self.assertEqual(m["decision_source"], "preset")
        self.assertTrue(out["audio_file"].endswith(vega_engine.MASTERED_FILENAME))
        self.assertTrue(os.path.exists(out["audio_file"]))
        self.assertTrue(os.path.exists(out["audio_raw_file"]))
        self.assertTrue(out["audio_raw_url"].endswith("audio_raw.wav"))
        self.assertEqual(out["audio_url"], f"/data/luna_music/{self.track_id}/{vega_engine.MASTERED_FILENAME}")
        self.assertIn("before", m)
        self.assertIn("after", m)
        self.assertLessEqual(m["after"]["true_peak_dbtp"], m["ceiling_dbtp"] + 0.1)

    def test_remaster_starts_from_raw_not_from_previous_master(self):
        first = vega_engine.master_track(dict(self.track), use_llm=False, luna_dir=self.tmp)
        second = vega_engine.master_track(dict(first), use_llm=False, luna_dir=self.tmp)
        # 두 번째도 같은 원본에서 시작했으므로 before 측정값이 동일해야 한다 (열화 누적 없음)
        self.assertEqual(first["mastering"]["before"]["integrated_lufs"], second["mastering"]["before"]["integrated_lufs"])
        self.assertEqual(first["audio_raw_file"], second["audio_raw_file"])

    def test_missing_audio_reports_failed_and_keeps_track_usable(self):
        bad = {"track_id": "luna_missing", "genre": "lofi", "audio_file": os.path.join(self.tmp, "nope.mp3")}
        out = vega_engine.master_track(bad, use_llm=False, luna_dir=self.tmp)
        self.assertEqual(out["mastering"]["status"], "failed")
        self.assertEqual(out["audio_file"], bad["audio_file"])

    def test_llm_failure_during_master_still_succeeds_with_preset(self):
        with mock.patch.object(vega_engine.llm_client, "call_llm_json", side_effect=RuntimeError("offline")):
            out = vega_engine.master_track(dict(self.track), use_llm=True, luna_dir=self.tmp)
        self.assertEqual(out["mastering"]["status"], "done")
        self.assertEqual(out["mastering"]["decision_source"], "preset")


class VegaUnavailablePathTests(unittest.TestCase):
    def test_master_track_skips_cleanly_when_dependencies_missing(self):
        with mock.patch.object(vega_engine, "VEGA_AVAILABLE", False), \
             mock.patch.object(vega_engine, "_IMPORT_ERROR", "No module named 'pedalboard'"):
            track = {"track_id": "x", "genre": "lofi", "audio_file": "/nonexistent/audio.mp3"}
            out = vega_engine.master_track(dict(track), use_llm=False, luna_dir="/tmp")
        self.assertEqual(out["mastering"]["status"], "skipped")
        self.assertEqual(out["audio_file"], track["audio_file"])
        self.assertIn("pip install", out["mastering"]["install_hint"])


class VegaApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from app import app
        self.client = TestClient(app)

    def test_vega_status_endpoint(self):
        res = self.client.get("/api/vega/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("available", data)
        self.assertIn("presets", data)
        self.assertIn("auto_master_enabled", data)
        self.assertGreaterEqual(len(data["presets"]), 10)

    def test_master_unknown_track_returns_404(self):
        res = self.client.post("/api/luna/master", json={"track_id": "luna_does_not_exist_000", "prompt": ""})
        self.assertEqual(res.status_code, 404)

    def test_generate_request_accepts_mastering_fields(self):
        from app import LunaTrackGenerateRequest
        req = LunaTrackGenerateRequest(genre="lofi", mood="dawn", master_audio=False, mastering_prompt="따뜻하게")
        self.assertFalse(req.master_audio)
        self.assertEqual(req.mastering_prompt, "따뜻하게")


if __name__ == "__main__":
    unittest.main()
