"""편성안 JSON → 주간 컴필레이션 스크립트(build_compilation_from_plan.py) 테스트. 업로드는 하지 않는다."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def _load(name):
    path = os.path.join(BASE, "scripts", name)
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


build = _load("build_compilation_from_plan.py")
upload = _load("upload_luna_compilation.py")


def week_entry(tracks=None, theme="city_night"):
    return {
        "week": 1, "publish_date": "2026-10-31", "theme": theme, "label": "도시의 밤 시티팝·신스웨이브·R&B",
        "duration_s": 3651,
        "tracks": tracks or [
            {"start": "00:00", "track_id": "luna_1", "title": "Backspace Echoes (지워진 기록)",
             "audio_path": "/x/luna_1/audio.mp3", "duration_s": 181, "first_release": False},
            {"start": "03:01", "track_id": "luna_2", "title": "Glasshouse Canopy (빌딩 숲 너머의 온실)",
             "audio_path": "/x/luna_2/audio.mp3", "duration_s": 147, "first_release": True},
        ],
    }


class PlanSelectionTests(unittest.TestCase):
    def test_select_week_by_number_or_date(self):
        plan = [dict(week_entry(), week=1), dict(week_entry(), week=2, publish_date="2026-11-07")]
        self.assertEqual(build.select_week(plan, week=2)["publish_date"], "2026-11-07")
        self.assertEqual(build.select_week(plan, publish_date="2026-10-31")["week"], 1)
        with self.assertRaises(ValueError):
            build.select_week(plan)  # 두 개가 걸림
        with self.assertRaises(ValueError):
            build.select_week(plan, week=9)

    def test_duplicate_track_rejected(self):
        e = week_entry()
        e["tracks"][1]["track_id"] = "luna_1"
        with self.assertRaisesRegex(ValueError, "두 번"):
            build.validate_week(e)

    def test_output_dir_name(self):
        self.assertEqual(build.output_dir_for(week_entry(), Path("/r")), Path("/r/2026-10-31_city_night"))


class TimelineAndMetadataTests(unittest.TestCase):
    def test_timeline_accounts_for_crossfade(self):
        starts = build.compute_timeline([180.0, 150.0, 200.0], 2.0)
        self.assertEqual(starts, [0.0, 178.0, 326.0])
        self.assertEqual(build.total_duration([180.0, 150.0, 200.0], 2.0), 526.0)

    def test_metadata_has_actual_duration_star_and_ai_disclosure(self):
        items = [{"title": "A (가)", "start": 0.0, "first_release": False},
                 {"title": "B (나)", "start": 3601.0, "first_release": True}]
        meta = build.build_youtube_metadata(week_entry(), items, 3611.4)
        self.assertTrue(meta["youtube_title"].startswith("[1 Hour Playlist]"))
        self.assertIn("(미발표곡 포함)", meta["youtube_title"])
        self.assertLessEqual(len(meta["youtube_title"]), 100)
        desc = meta["youtube_description"]
        self.assertIn("00:00 A (가)\n", desc)
        self.assertIn("01:00:01 B (나) ★", desc)
        self.assertIn("★ 표시는", desc)
        self.assertIn(build.AI_DISCLOSURE, desc)
        self.assertTrue(meta["contains_synthetic_media"])
        self.assertLessEqual(len(meta["youtube_tags"]), 15)

    def test_short_compilation_title_uses_minutes(self):
        items = [{"title": "A", "start": 0.0, "first_release": False}]
        meta = build.build_youtube_metadata(week_entry(), items, 52 * 60 + 56)
        self.assertTrue(meta["youtube_title"].startswith("[52 Min Playlist]"))
        self.assertNotIn("★", meta["youtube_description"])

    def test_metadata_passes_upload_banned_word_check(self):
        for theme in list(build.THEME_COPY) + ["unknown_theme"]:
            items = [{"title": "A", "start": 0.0, "first_release": True}]
            meta = build.build_youtube_metadata(week_entry(theme=theme), items, 3600)
            text = " ".join([meta["youtube_title"], meta["youtube_description"], *meta["youtube_tags"]]).lower()
            self.assertFalse([w for w in upload.BANNED_WORDS if w.lower() in text], theme)

    def test_visual_genre_majority(self):
        self.assertEqual(build.pick_visual_genre(["Slow R&B Chillout", "Nostalgic City Pop", "Lo-Fi / Chillhop"]), "chill")
        self.assertEqual(build.pick_visual_genre([]), "lofi")


class AudioFilterTests(unittest.TestCase):
    def test_filter_chain(self):
        f = build.build_audio_filter([1.5, -2.0, 0.0], 2.0)
        self.assertEqual(f.count("acrossfade=d=2.0"), 2)
        self.assertIn("volume=1.50dB", f)
        self.assertIn("volume=-2.00dB", f)
        self.assertIn("alimiter=limit=0.7943", f)
        self.assertTrue(f.endswith("[out]"))

    def test_gain_is_clamped(self):
        self.assertEqual(build.track_gain_db(-40.0), build.MAX_TRACK_GAIN_DB)
        self.assertAlmostEqual(build.track_gain_db(-12.68), -1.32)

    def test_parse_loudnorm_json(self):
        stderr = 'noise\n[Parsed_loudnorm_0 @ 0x1]\n{\n "input_i" : "-12.68",\n "input_tp" : "0.27",\n "input_lra" : "8.10"\n}\n'
        self.assertEqual(build.parse_loudnorm_json(stderr), {"i": -12.68, "tp": 0.27, "lra": 8.1})
        with self.assertRaises(ValueError):
            build.parse_loudnorm_json("no json")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg 필요")
class BuildIntegrationTests(unittest.TestCase):
    """사인파 3곡(음량 제각각)을 실제로 합성해 길이·음량·산출물을 확인한다."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        tracks = []
        for i, (freq, vol) in enumerate([(220, 1.6), (330, 5.0), (440, 2.8)]):
            d = self.tmp / f"luna_{i}"
            d.mkdir()
            audio = d / "audio.mp3"
            subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                            "-i", f"sine=frequency={freq}:duration=6", "-af", f"volume={vol}",
                            "-c:a", "libmp3lame", "-b:a", "192k", str(audio)], check=True)
            (d / "meta.json").write_text(json.dumps({"genre": "Slow R&B Chillout"}), encoding="utf-8")
            tracks.append({"start": "", "track_id": f"luna_{i}", "title": f"Song {i}", "audio_path": str(audio),
                           "duration_s": 6, "first_release": i == 1})
        self.entry = week_entry(tracks)
        self.plan = self.tmp / "plan.json"
        self.plan.write_text(json.dumps([self.entry]), encoding="utf-8")

    def test_build_audio_only(self):
        out = self.tmp / "out"
        with patch.object(build.luna_engine, "BGA_ASSETS_DIR", str(self.tmp / "no_bga")):
            res = build.build_compilation(self.plan, self.entry, out, crossfade=1.0, render_video_file=False)
        report, meta = res["report"], res["metadata"]
        self.assertAlmostEqual(report["actual_duration_s"], 16.0, delta=0.3)  # 6*3 - 1*2
        self.assertLessEqual(abs(report["final_loudness"]["i"] - build.TARGET_LUFS), 1.0)
        self.assertLessEqual(report["final_loudness"]["tp"], build.TARGET_TP_DBTP)
        self.assertEqual([t["actual_start"] for t in report["tracks"]], ["00:00", "00:05", "00:10"])
        self.assertFalse(report["uploaded"])
        self.assertEqual(meta["upload_status"], "not_uploaded")
        self.assertIn("00:05 Song 1 ★", meta["youtube_description"])
        self.assertEqual(sorted(p.name for p in out.iterdir()),
                         ["build_report.json", "compilation_audio.mp3", "youtube_metadata.json", "youtube_metadata.txt"])

    def test_missing_audio_rejected(self):
        self.entry["tracks"][0]["audio_path"] = str(self.tmp / "nope.mp3")
        with self.assertRaises(FileNotFoundError):
            build.build_compilation(self.plan, self.entry, self.tmp / "out", render_video_file=False)


if __name__ == "__main__":
    unittest.main()
