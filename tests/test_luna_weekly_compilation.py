import importlib.util
import json
import os
import random
import sys
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "scripts"))


def _load(name):
    path = os.path.join(BASE, "scripts", name)
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


weekly = _load("luna_weekly_compilation.py")
build = _load("build_compilation_from_plan.py")
upload = _load("upload_luna_compilation.py")


def candidate(theme, n=3):
    return {"week": 1, "publish_date": "2026-11-07", "theme": theme, "label": theme, "duration_s": 3100, "reused": 1,
            "tracks": [{"start": "00:00", "track_id": f"{theme}_{i}", "title": f"{theme} {i}",
                        "audio_path": f"/x/{theme}_{i}.mp3", "duration_s": 180, "first_release": i == 0}
                       for i in range(n)]}


class FakeBuilder:
    """실제 편성안 읽기·검증은 그대로 쓰고 렌더만 흉내 낸다."""

    def __init__(self, fail=False):
        self.fail, self.calls = fail, []
        self.load_plan, self.select_week, self.validate_week = build.load_plan, build.select_week, build.validate_week

    def build_compilation(self, plan_path, entry, out_dir, render_video_file=True):
        self.calls.append(entry["theme"])
        if self.fail:
            raise RuntimeError("ffmpeg 실패")
        video = Path(out_dir) / "compilation_video.mp4"
        video.write_bytes(b"v")
        meta = {"youtube_title": f"{entry['theme']} 1시간", "youtube_description": "00:00 a", "youtube_tags": ["x"],
                "theme": entry["theme"], "duration_seconds": 3100, "video_file": str(video), "room_name": "r",
                "tracks": [{"start": "00:00", "title": "a", "first_release": True}]}
        (Path(out_dir) / "youtube_metadata.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return {"metadata": meta, "report": {"final_loudness": {"i": -14.0, "tp": -1.5}, "warnings": []}}


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "comps"
        self.root.mkdir()
        self.log = Path(self.tmp.name) / "decisions.jsonl"
        self.cand_calls = 0

    def tearDown(self):
        self.tmp.cleanup()

    def cands(self, themes):
        def fn(publish_date):
            self.cand_calls += 1
            return [candidate(t) for t in themes]
        return fn

    def events(self):
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]



class WeeklyCompilationTest(_Base):
    def test_next_publish_date_leaves_two_days(self):
        self.assertEqual(weekly.next_publish_date(date(2026, 11, 5)), date(2026, 11, 7))  # 목 → 토
        self.assertEqual(weekly.next_publish_date(date(2026, 11, 6)), date(2026, 11, 14))  # 금 → 다음 주 토
        self.assertEqual(weekly.next_publish_date(date(2026, 11, 1)), date(2026, 11, 7))

    def test_prepare_draws_once_and_records_probability(self):
        b = FakeBuilder()
        state = weekly.prepare("2026-11-07", root=self.root, rng=random.Random(1),
                               candidates_fn=self.cands(["city_night", "calm_instrumental"]), builder=b,
                               decisions_path=self.log)
        self.assertEqual(state["status"], weekly.STATUS_AWAITING_APPROVAL)
        self.assertEqual(state["publish_at"], "2026-11-07T22:00:00+09:00")
        ev = self.events()
        self.assertEqual(len(ev), 1)
        d = ev[0]
        self.assertEqual(d["event"], "decision")
        self.assertEqual(d["chosen"], {"format": "compilation", "genre": state["theme"], "mood": None, "vocal_mode": None})
        self.assertAlmostEqual(d["action_probability"], 0.5)
        self.assertEqual(d["eligible_actions"]["genre"], ["city_night", "calm_instrumental"])
        self.assertEqual(d["source"], weekly.SOURCE_UNIFORM)
        out = self.root / f"2026-11-07_{state['theme']}"
        self.assertTrue((out / "approval_request.md").exists())
        self.assertIn("--execute", (out / "approval_request.md").read_text(encoding="utf-8"))
        # 다시 실행해도 새로 뽑거나 다시 렌더하지 않는다
        again = weekly.prepare("2026-11-07", root=self.root, candidates_fn=self.cands(["jazz"]), builder=b,
                               decisions_path=self.log)
        self.assertEqual(again["decision_id"], state["decision_id"])
        self.assertEqual(self.cand_calls, 1)
        self.assertEqual(len(b.calls), 1)
        self.assertEqual(len(self.events()), 1)

    def test_build_failure_resumes_with_same_theme(self):
        with self.assertRaises(RuntimeError):
            weekly.prepare("2026-11-07", root=self.root, rng=random.Random(0), candidates_fn=self.cands(["city_night"]),
                           builder=FakeBuilder(fail=True), decisions_path=self.log)
        state = json.loads((self.root / "2026-11-07_city_night" / "decision.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], weekly.STATUS_AWAITING_BUILD)
        b = FakeBuilder()
        done = weekly.prepare("2026-11-07", root=self.root, candidates_fn=self.cands(["calm_instrumental"]), builder=b,
                              decisions_path=self.log)
        self.assertEqual(done["status"], weekly.STATUS_AWAITING_APPROVAL)
        self.assertEqual(b.calls, ["city_night"])
        self.assertEqual(self.cand_calls, 1)
        self.assertEqual(len(self.events()), 1)

    def test_no_candidates_records_nothing(self):
        state = weekly.prepare("2026-11-07", root=self.root, candidates_fn=self.cands([]), builder=FakeBuilder(),
                               decisions_path=self.log)
        self.assertEqual(state["status"], "no_candidates")
        self.assertFalse(self.log.exists())
        self.assertEqual([p for p in self.root.iterdir() if not p.name.startswith(".")], [])

    def test_two_decision_files_for_same_date_is_an_error(self):
        for theme in ("a", "b"):
            (self.root / f"2026-11-07_{theme}").mkdir()
            (self.root / f"2026-11-07_{theme}" / "decision.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            weekly.prepare("2026-11-07", root=self.root, candidates_fn=self.cands(["a"]), builder=FakeBuilder(),
                           decisions_path=self.log)

    def test_record_applied_once(self):
        state = weekly.prepare("2026-11-07", root=self.root, rng=random.Random(0), candidates_fn=self.cands(["city_night"]),
                               builder=FakeBuilder(), decisions_path=self.log)
        out = self.root / "2026-11-07_city_night"
        (out / "upload_result.json").write_text(json.dumps({"video_id": "VID123", "publish_at": state["publish_at"]}),
                                                encoding="utf-8")
        self.assertTrue(weekly.record_applied_for(out, decisions_path=self.log)["recorded"])
        self.assertFalse(weekly.record_applied_for(out, decisions_path=self.log)["recorded"])
        applied = [e for e in self.events() if e["event"] == "applied"]
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0]["content_id"], "VID123")
        self.assertEqual(applied[0]["changed_fields"], [])
        self.assertEqual(applied[0]["decision_id"], state["decision_id"])

    def test_upload_plan_reads_decision_and_blocks_unbuilt(self):
        weekly.prepare("2026-11-07", root=self.root, rng=random.Random(0), candidates_fn=self.cands(["city_night"]),
                       builder=FakeBuilder(), decisions_path=self.log)
        meta = upload.load_plan("2026-11-07_city_night", comp_dir=self.root)
        self.assertEqual(meta["_decision"]["publish_at"], "2026-11-07T22:00:00+09:00")
        self.assertEqual(meta["_decision"]["status"], weekly.STATUS_AWAITING_APPROVAL)
        legacy = self.root / "piano"
        legacy.mkdir()
        video = legacy / "v.mp4"
        video.write_bytes(b"v")
        (legacy / "youtube_metadata.json").write_text(json.dumps(
            {"youtube_title": "t", "youtube_description": "d", "youtube_tags": [], "video_file": str(video)}),
            encoding="utf-8")
        self.assertIsNone(upload.load_plan("piano", comp_dir=self.root)["_decision"])


class WeeklyCompilationRobustnessTest(_Base):
    def test_crash_while_logging_does_not_redraw(self):
        real = weekly.luna_decisions.record_decision
        with patch.object(weekly.luna_decisions, "record_decision", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                weekly.prepare("2026-11-07", root=self.root, rng=random.Random(0),
                               candidates_fn=self.cands(["city_night", "calm_instrumental"]), builder=FakeBuilder(),
                               decisions_path=self.log)
        self.assertIs(weekly.luna_decisions.record_decision, real)
        [folder] = [p for p in self.root.iterdir() if p.is_dir()]
        drawn = json.loads((folder / "decision.json").read_text(encoding="utf-8"))
        self.assertEqual(drawn["status"], weekly.STATUS_DRAWING)
        state = weekly.prepare("2026-11-07", root=self.root, candidates_fn=self.cands(["jazz"]), builder=FakeBuilder(),
                               decisions_path=self.log)
        self.assertEqual(self.cand_calls, 1)  # 다시 뽑지 않음
        self.assertEqual(state["decision_id"], drawn["decision_id"])
        self.assertEqual(state["theme"], drawn["theme"])
        ev = self.events()
        self.assertEqual([e["decision_id"] for e in ev], [drawn["decision_id"]])
        self.assertEqual(ev[0]["context"]["candidates"][0]["theme"], "city_night")

    def test_folder_without_decision_file_is_an_error(self):
        (self.root / "2026-11-07_city_night").mkdir()
        with self.assertRaises(RuntimeError):
            weekly.prepare("2026-11-07", root=self.root, candidates_fn=self.cands(["city_night"]), builder=FakeBuilder(),
                           decisions_path=self.log)
        self.assertEqual(self.cand_calls, 0)

    def test_logged_decision_without_folder_is_not_redrawn(self):
        weekly.prepare("2026-11-07", root=self.root, rng=random.Random(0), candidates_fn=self.cands(["city_night"]),
                       builder=FakeBuilder(), decisions_path=self.log)
        other = Path(self.tmp.name) / "other_root"
        with self.assertRaises(RuntimeError):
            weekly.prepare("2026-11-07", root=other, candidates_fn=self.cands(["city_night"]), builder=FakeBuilder(),
                           decisions_path=self.log)
        self.assertEqual(self.cand_calls, 1)

    def test_concurrent_prepare_is_refused(self):
        with weekly.date_lock(self.root, "2026-11-07"):
            with self.assertRaises(RuntimeError):
                weekly.prepare("2026-11-07", root=self.root, candidates_fn=self.cands(["city_night"]),
                               builder=FakeBuilder(), decisions_path=self.log)
        self.assertEqual(self.cand_calls, 0)

    def test_skipped_saturday_is_reported(self):
        self.assertEqual(weekly.skipped_publish_date(date(2026, 11, 6), self.root), date(2026, 11, 7))  # 금요일 실행
        self.assertIsNone(weekly.skipped_publish_date(date(2026, 11, 5), self.root))  # 목요일 정상
        (self.root / "2026-11-07_x").mkdir()
        (self.root / "2026-11-07_x" / "decision.json").write_text("{}", encoding="utf-8")
        self.assertIsNone(weekly.skipped_publish_date(date(2026, 11, 6), self.root))  # 이미 준비됨


class UploadIntegrationTest(_Base):
    def run_upload(self, folder, uploader_result, extra=()):
        fake = types.ModuleType("uploader")
        fake.upload_video = lambda progress=None, **kw: dict(uploader_result, _kw=kw)
        argv = ["upload_luna_compilation.py", "--genre", folder, "--execute", *extra]
        with patch.object(upload, "COMPILATIONS_DIR", self.root), patch.object(sys, "argv", argv), \
                patch.dict(sys.modules, {"uploader": fake}), \
                patch.object(weekly.luna_decisions, "DECISIONS_PATH", self.log):
            try:
                upload.main()
                return 0
            except SystemExit as e:
                return e.code or 0

    def test_main_uploads_with_decision_time_and_records_applied(self):
        state = weekly.prepare("2099-01-03", root=self.root, rng=random.Random(0), candidates_fn=self.cands(["city_night"]),
                               builder=FakeBuilder(), decisions_path=self.log)
        rc = self.run_upload("2099-01-03_city_night", {"video_id": "VIDX", "url": "https://youtu.be/VIDX"})
        self.assertEqual(rc, 0)
        result = json.loads((self.root / "2099-01-03_city_night" / "upload_result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["publish_at"], "2099-01-03T22:00:00+09:00")
        self.assertTrue(result["contains_synthetic_media"])
        applied = [e for e in self.events() if e["event"] == "applied"]
        self.assertEqual([(a["decision_id"], a["content_id"]) for a in applied], [(state["decision_id"], "VIDX")])

    def test_main_exits_2_when_recording_fails(self):
        weekly.prepare("2099-01-03", root=self.root, rng=random.Random(0), candidates_fn=self.cands(["city_night"]),
                       builder=FakeBuilder(), decisions_path=self.log)
        rc = self.run_upload("2099-01-03_city_night", {"video_id": None, "url": None})
        self.assertEqual(rc, 2)

    def test_main_refuses_past_publish_time(self):
        weekly.prepare("2026-01-03", root=self.root, rng=random.Random(0), candidates_fn=self.cands(["city_night"]),
                       builder=FakeBuilder(), decisions_path=self.log)
        rc = self.run_upload("2026-01-03_city_night", {"video_id": "V", "url": "u"})
        self.assertEqual(rc, 1)
        self.assertFalse((self.root / "2026-01-03_city_night" / "upload_result.json").exists())
        with self.assertRaises(ValueError):
            upload.check_publish_at("2026-11-01T22:00:00", now=None)  # 시간대 없음


if __name__ == "__main__":
    unittest.main()
