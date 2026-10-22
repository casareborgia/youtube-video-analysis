"""장르별 롱폼 컴필레이션 생성·업로드 스크립트 테스트."""
import importlib.util
import json
import os
import shutil
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


create = _load("create_luna_compilation.py")
upload = _load("upload_luna_compilation.py")


class ScanAndPlaylistTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        tracks = [
            ("luna_1", "Emotional Piano Solo", "Felt (펠트)", "VID1"),
            ("luna_2", "Cinematic Felt Piano & Neoclassical", "Moon (달)", None),
            ("luna_3", "Cinematic Ambient", "Drift (표류)", None),
            ("luna_4", "Late Night Jazz Cafe", "Bar (바)", None),
            ("luna_5", "Emotional Piano Solo", "NoAudio", None),
        ]
        for tid, genre, title, vid in tracks:
            d = self.tmp / tid
            d.mkdir()
            meta = {"track_id": tid, "genre": genre, "title": title}
            if vid:
                meta["uploaded_video_id"] = vid
            (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
            if title != "NoAudio":
                (d / "audio.mp3").write_bytes(tid.encode() * 4000)

    def scan(self, genre):
        with patch.object(create, "get_audio_duration", return_value=180.0):
            return create.scan_available_tracks(genre, luna_dir=self.tmp)

    def test_scan_uses_engine_room_mapping(self):
        self.assertEqual([t["track_id"] for t in self.scan("piano")], ["luna_1", "luna_2"])  # 음원 없는 곡 제외
        self.assertEqual([t["track_id"] for t in self.scan("ambient")], ["luna_3"])
        self.assertEqual([t["track_id"] for t in self.scan("all_sleep")], ["luna_1", "luna_2", "luna_3"])
        self.assertEqual([t["released"] for t in self.scan("piano")], [True, False])

    def test_identical_audio_in_two_folders_is_listed_once(self):
        d = self.tmp / "luna_6"
        d.mkdir()
        (d / "meta.json").write_text(json.dumps({"track_id": "luna_6", "genre": "Cinematic Ambient", "title": "Drift (표류)"}), encoding="utf-8")
        shutil.copy(self.tmp / "luna_3" / "audio.mp3", d / "audio.mp3")
        self.assertEqual([t["track_id"] for t in self.scan("ambient")], ["luna_3"])

    def test_unmeasurable_audio_is_skipped(self):
        with patch.object(create, "get_audio_duration", return_value=0.0):
            self.assertEqual(create.scan_available_tracks("piano", luna_dir=self.tmp), [])

    def test_default_playlist_plays_each_track_once(self):
        tracks = self.scan("piano")
        self.assertEqual(create.build_playlist(tracks), tracks)
        self.assertEqual(len(create.build_playlist(tracks, 1000)), 6)  # --minutes 지정 시에만 순환 반복

    def test_unknown_genre_rejected(self):
        with self.assertRaises(ValueError):
            create.room_keys_for("kpop")


class MetadataTests(unittest.TestCase):
    def test_title_timeline_and_new_track_marks(self):
        playlist = [{"title": "Felt (펠트)", "duration": 185.0, "released": True},
                    {"title": "Moon (달)", "duration": 200.0, "released": False}]
        meta = create.build_youtube_metadata("piano", playlist, 2400.0)
        self.assertTrue(meta["youtube_title"].startswith("[40 Min Playlist]"), meta["youtube_title"])
        self.assertIn("(미발표곡 포함)", meta["youtube_title"])
        self.assertIn("00:00 Felt (펠트)\n03:05 Moon (달) ★", meta["youtube_description"])
        self.assertNotIn("레오", meta["youtube_description"])
        self.assertIn("#새벽피아노", meta["youtube_description"])

    def test_no_new_mark_when_all_released(self):
        meta = create.build_youtube_metadata("ambient", [{"title": "A", "duration": 3700.0, "released": True}], 3700.0)
        self.assertTrue(meta["youtube_title"].startswith("[1 Hour Playlist]"))
        self.assertNotIn("미발표", meta["youtube_title"])
        self.assertNotIn("★", meta["youtube_description"])


class UploadPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "piano").mkdir()
        self.video = self.tmp / "piano" / "compilation_video.mp4"
        self.video.write_bytes(b"\0")
        self.meta = {"youtube_title": "[40 Min Playlist] 피아노 | 루나의 심야 서재", "youtube_description": "desc",
                     "youtube_tags": ["피아노"], "video_file": str(self.video), "room_name": "달밤 창가 피아노 (Piano)",
                     "duration_seconds": 2400}

    def write(self, **kw):
        (self.tmp / "piano" / "youtube_metadata.json").write_text(json.dumps(dict(self.meta, **kw)), encoding="utf-8")

    def test_valid_plan_points_marker_into_genre_dir(self):
        self.write()
        plan = upload.load_plan("piano", comp_dir=self.tmp)
        self.assertEqual(plan["_result_file"], str(self.tmp / "piano" / "upload_result.json"))

    def test_rejects_persona_credit_and_missing_video(self):
        self.write(youtube_description="기획 & 큐레이션: 에이전트 레오 (Agent Leo)")
        with self.assertRaises(ValueError):
            upload.load_plan("piano", comp_dir=self.tmp)
        self.write(video_file=str(self.tmp / "nope.mp4"))
        with self.assertRaises(ValueError):
            upload.load_plan("piano", comp_dir=self.tmp)
        with self.assertRaises(ValueError):
            upload.load_plan("ambient", comp_dir=self.tmp)


if __name__ == "__main__":
    unittest.main()
