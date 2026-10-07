"""tests/test_vega_feedback.py - 베가 피드백 로깅 및 프리셋 보정 제안 단위 테스트"""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import vega_feedback
import luna_engine
from app import app


class VegaFeedbackUnitTests(unittest.TestCase):
    """vega_feedback 모듈 함수 레벨 단위 테스트"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name) / "vega_feedback.jsonl"
        self.patcher = patch.object(vega_feedback, "FEEDBACK_PATH", self.temp_path)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.temp_dir.cleanup()

    def test_record_and_load_feedback(self):
        """이벤트 기록 및 로드, 필터링 검증"""
        # 1. remaster 이벤트 기록
        ev1 = {
            "event": "remaster",
            "track_id": "track_1",
            "genre": "lofi",
            "mood": "dawn",
            "prompt": "저음 보강",
            "use_llm": True,
            "decision_source": "llm",
            "decision_model": "gemini-3.8-flash",
            "decisions": {
                "target_lufs": -13.5,
                "compressor": {"threshold_db": -17.0, "ratio": 2.2},
                "saturator": {"drive_db": 3.2, "mix": 0.35},
                "stereo_image": {"width": 1.1},
            },
            "before": {"integrated_lufs": -16.0, "true_peak_dbtp": -2.0},
            "after": {"integrated_lufs": -14.0, "true_peak_dbtp": -1.0},
        }
        res1 = vega_feedback.record_feedback(ev1)
        self.assertEqual(res1["status"], "ok")

        # 2. render 이벤트 기록
        ev2 = {
            "event": "render",
            "track_id": "track_1",
            "genre": "lofi",
            "mood": "dawn",
            "decisions": {"target_lufs": -14.0},
        }
        res2 = vega_feedback.record_feedback(ev2)
        self.assertEqual(res2["status"], "ok")

        # 3. preference 이벤트 기록
        ev3 = {
            "event": "preference",
            "track_id": "track_2",
            "genre": "ambient",
            "choice": "master",
        }
        res3 = vega_feedback.record_feedback(ev3)
        self.assertEqual(res3["status"], "ok")

        # 로드 검증
        all_records = vega_feedback.load_feedback()
        self.assertEqual(len(all_records), 3)
        # 최근순 정렬 확인 (마지막에 쓴 ev3 가 맨 앞)
        self.assertEqual(all_records[0]["event"], "preference")
        self.assertEqual(all_records[0]["track_id"], "track_2")

        # 장르 필터
        lofi_records = vega_feedback.load_feedback(genre="lofi")
        self.assertEqual(len(lofi_records), 2)

        # 이벤트 필터
        pref_records = vega_feedback.load_feedback(event="preference")
        self.assertEqual(len(pref_records), 1)
        self.assertEqual(pref_records[0]["choice"], "master")

    def test_record_write_failure_returns_skipped(self):
        """파일 쓰기 오류 시 예외 없이 skipped 반환 (open 자체를 실패시켜 권한·OS 와 무관하게 검증)"""
        with patch("vega_feedback.open", side_effect=OSError("disk full"), create=True):
            res = vega_feedback.record_feedback({"event": "remaster", "genre": "lofi"})
        self.assertEqual(res["status"], "skipped")
        self.assertIn("disk full", res["reason"])
        self.assertFalse(self.temp_path.exists())

    def test_display_name_genre_is_resolved_to_preset_key(self):
        """트랙 genre 가 표시명("Lo-Fi / Chillhop")이어도 기록엔 genre_key 가 남고, 표시명·키 어느 쪽으로 조회해도 같은 결과"""
        for _ in range(3):
            vega_feedback.record_feedback({
                "event": "render", "genre": "Lo-Fi / Chillhop",
                "decisions": {"target_lufs": -13.0},
            })
        recs = vega_feedback.load_feedback(genre="lofi")
        self.assertEqual(len(recs), 3)
        self.assertEqual(recs[0]["genre_key"], "lofi")
        self.assertEqual(recs[0]["genre"], "Lo-Fi / Chillhop")
        by_name = vega_feedback.suggest_preset_adjustment("Lo-Fi / Chillhop")
        by_key = vega_feedback.suggest_preset_adjustment("lofi")
        self.assertEqual(by_name["status"], "ok")
        self.assertEqual(by_name["samples"], 3)
        self.assertEqual(by_name["suggestions"], by_key["suggestions"])
        lufs = {s["param"]: s for s in by_name["suggestions"]}["target_lufs"]
        self.assertEqual(lufs["preset"], -14.0)   # lofi 프리셋 (default 가 아님)
        self.assertEqual(lufs["delta"], 1.0)

    def test_samples_without_decisions_are_not_counted(self):
        """마스터링 없이 렌더된 기록(decisions 없음)은 표본 수에 포함되지 않는다"""
        for _ in range(3):
            vega_feedback.record_feedback({"event": "render", "genre": "lofi"})
        res = vega_feedback.suggest_preset_adjustment("lofi")
        self.assertEqual(res["status"], "insufficient")
        self.assertEqual(res["samples"], 0)

    def test_build_event_from_track_uses_mastering_genre_key(self):
        track = {
            "track_id": "t1", "genre": "Emotional Piano Solo", "mood": "calm",
            "mastering": {"status": "done", "genre_key": "piano", "decision_source": "llm",
                          "decision_model": "gemini-3.8-flash", "target_lufs": -16.0, "ceiling_dbtp": -1.0,
                          "decisions": {"target_lufs": -16.0, "compressor": {"threshold_db": -20, "ratio": 1.6},
                                        "saturator": {"drive_db": 1.0, "mix": 0.1}, "stereo_image": {"width": 1.1},
                                        "tonal_eq": {"bands": [{"frequency": 8000, "gain_db": 1.0, "q": 0.7, "filter_type": "high_shelf"}]}},
                          "before": {"integrated_lufs": -11.0, "true_peak_dbtp": 0.3},
                          "after": {"integrated_lufs": -16.0, "true_peak_dbtp": -1.1}},
            "audio_file": "/should/not/be/recorded.wav",
        }
        ev = vega_feedback.build_feedback_event("preference", track, choice="raw")
        self.assertEqual(ev["genre_key"], "piano")
        self.assertEqual(ev["choice"], "raw")
        self.assertEqual(ev["decisions"]["tonal_eq.high_shelf_gain_db"], 1.0)
        self.assertEqual(ev["decisions"]["compressor.ratio"], 1.6)
        rec = vega_feedback.record_feedback(ev)["event"]
        self.assertNotIn("audio_file", rec)
        self.assertNotIn("audio_url", json.dumps(rec))

    def test_suggest_insufficient_samples(self):
        """표본 수가 min_samples(3) 미만일 때 insufficient 반환"""
        # 0건
        res0 = vega_feedback.suggest_preset_adjustment("lofi", min_samples=3)
        self.assertEqual(res0["status"], "insufficient")
        self.assertEqual(res0["samples"], 0)

        # 2건만 기록 (1건은 preset 모드라 카운트 제외, 1건만 llm)
        ev_llm = {
            "event": "remaster",
            "genre": "lofi",
            "decision_source": "llm",
            "decisions": {"target_lufs": -13.0},
        }
        ev_preset = {
            "event": "remaster",
            "genre": "lofi",
            "decision_source": "preset",  # 제외 대상
            "decisions": {"target_lufs": -14.0},
        }
        vega_feedback.record_feedback(ev_llm)
        vega_feedback.record_feedback(ev_preset)

        res2 = vega_feedback.suggest_preset_adjustment("lofi", min_samples=3)
        self.assertEqual(res2["status"], "insufficient")
        self.assertEqual(res2["samples"], 1)

    def test_suggest_median_and_clamping(self):
        """중앙값 계산 및 delta 클램프 동작 검증"""
        # lofi 기본 프리셋 target_lufs 는 -14.0
        # 표본 3건의 target_lufs 가 -12.0 일 때: median = -12.0, raw_delta = +2.0
        # target_lufs 의 max_delta 는 1.0 이므로, delta 는 +1.0 으로 클램프되어야 함 -> suggested = -13.0
        for _ in range(3):
            vega_feedback.record_feedback({
                "event": "remaster",
                "genre": "lofi",
                "decision_source": "llm",
                "decisions": {
                    "target_lufs": -12.0,
                    "compressor.threshold_db": -16.0,  # 프리셋 -18.0 대비 +2.0 -> 클램프 +1.0 -> -17.0
                    "compressor.ratio": 3.0,            # 프리셋 2.0 대비 +1.0 -> 클램프 +0.3 -> 2.3
                    "saturator.drive_db": 5.0,          # 프리셋 3.0 대비 +2.0 -> 클램프 +1.0 -> 4.0
                    "stereo_image.width": 1.3,          # 프리셋 1.05 대비 +0.25 -> 클램프 +0.1 -> 1.15
                    "tonal_eq.low_shelf_gain_db": 3.5,  # 프리셋 1.5 대비 +2.0 -> 클램프 +1.0 -> 2.5
                }
            })

        res = vega_feedback.suggest_preset_adjustment("lofi", min_samples=3)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["samples"], 3)
        suggestions = {s["param"]: s for s in res["suggestions"]}

        # 1. target_lufs 클램프 (+1.0)
        self.assertIn("target_lufs", suggestions)
        self.assertEqual(suggestions["target_lufs"]["preset"], -14.0)
        self.assertEqual(suggestions["target_lufs"]["median"], -12.0)
        self.assertEqual(suggestions["target_lufs"]["delta"], 1.0)
        self.assertEqual(suggestions["target_lufs"]["suggested"], -13.0)

        # 2. compressor.ratio 클램프 (+0.3)
        self.assertIn("compressor.ratio", suggestions)
        self.assertEqual(suggestions["compressor.ratio"]["delta"], 0.3)
        self.assertEqual(suggestions["compressor.ratio"]["suggested"], 2.3)

        # 3. stereo_image.width 클램프 (+0.1)
        self.assertIn("stereo_image.width", suggestions)
        self.assertEqual(suggestions["stereo_image.width"]["delta"], 0.1)
        self.assertEqual(suggestions["stereo_image.width"]["suggested"], 1.15)

    def test_suggest_excludes_small_delta(self):
        """|delta| < 0.05 인 항목은 제안에서 제외됨을 검증"""
        # lofi 기본 프리셋 target_lufs = -14.0
        # 표본 target_lufs 가 -14.02 일 때: delta = -0.02 (< 0.05) -> 제외
        for _ in range(3):
            vega_feedback.record_feedback({
                "event": "render",
                "genre": "lofi",
                "decisions": {
                    "target_lufs": -14.02,
                    "compressor.threshold_db": -17.0,  # delta = +1.0 (포함)
                }
            })

        res = vega_feedback.suggest_preset_adjustment("lofi", min_samples=3)
        self.assertEqual(res["status"], "ok")
        params = [s["param"] for s in res["suggestions"]]
        self.assertNotIn("target_lufs", params)
        self.assertIn("compressor.threshold_db", params)


class VegaFeedbackApiTests(unittest.TestCase):
    """FastAPI 엔드포인트 연동 테스트"""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name) / "vega_feedback.jsonl"
        self.patcher = patch.object(vega_feedback, "FEEDBACK_PATH", self.temp_path)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.temp_dir.cleanup()

    def test_post_feedback_success_and_invalid_choice(self):
        # 모의 트랙 생성
        mock_track = {
            "track_id": "test_track_1",
            "title": "Feedback Test Track",
            "genre": "lofi",
            "mastering": {"status": "done", "target_lufs": -14.0}
        }
        with patch("luna_engine.load_track", return_value=mock_track):
            # 정상 요청 ("master")
            resp = self.client.post("/api/vega/feedback", json={
                "track_id": "test_track_1",
                "choice": "master"
            })
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["event"]["choice"], "master")

            # 잘못된 choice ("invalid") -> 400
            resp_bad = self.client.post("/api/vega/feedback", json={
                "track_id": "test_track_1",
                "choice": "unknown_mode"
            })
            self.assertEqual(resp_bad.status_code, 400)

    def test_get_feedback_and_suggest_endpoints(self):
        # 1. feedback 조회
        resp_list = self.client.get("/api/vega/feedback")
        self.assertEqual(resp_list.status_code, 200)
        self.assertEqual(resp_list.json(), [])

        # 2. suggest 조회 (데이터 없음 -> insufficient)
        resp_sug = self.client.get("/api/vega/feedback/suggest?genre=lofi")
        self.assertEqual(resp_sug.status_code, 200)
        self.assertEqual(resp_sug.json()["status"], "insufficient")


if __name__ == "__main__":
    unittest.main()
