"""장르별 대표 BGA(시그니처 룸) 자동 매핑 및 렌더러 단위 테스트."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import luna_engine

BASE_DIR = Path(luna_engine.BASE_DIR)
BGA_DIR = BASE_DIR / "data" / "bga_assets"


class SignatureBgaEngineTests(unittest.TestCase):
    @unittest.skipUnless((BGA_DIR / "bga_lofi_study.mp4").exists(),
                         "BGA 루프 mp4 는 gitignore 대상 — scripts/generate_signature_bga_assets.py 로 생성 후 검증")
    def test_all_signature_bga_assets_exist(self):
        """7대 장르별 대표 BGA 비디오 및 썸네일 에셋이 실제 파일시스템에 존재하는지 확인."""
        expected_genres = ["lofi", "piano", "ambient", "sleep", "jazz", "chill", "acoustic"]
        for g in expected_genres:
            sig = luna_engine.resolve_signature_bga(g)
            self.assertIsNotNone(sig["video_path"], f"{g} video_path should exist")
            self.assertIsNotNone(sig["thumbnail_path"], f"{g} thumbnail_path should exist")
            self.assertTrue(os.path.exists(sig["video_path"]), f"{sig['video_path']} file missing")
            self.assertTrue(os.path.exists(sig["thumbnail_path"]), f"{sig['thumbnail_path']} file missing")

    def test_resolve_signature_bga_genre_aliases(self):
        """다양한 장르 별칭 및 복합어가 각각 올바른 대표 BGA 방으로 매핑되는지 검증."""
        test_cases = [
            ("Lo-Fi / Chillhop", "lofi", "책상 서재 (Lo-Fi)"),
            ("Emotional Piano Solo", "piano", "달밤 창가 피아노 (Piano)"),
            ("Cinematic Ambient", "ambient", "자정의 침실 (Ambient)"),
            ("Deep Sleep / Meditation", "sleep", "포근한 수면 안식처 (Sleep)"),
            ("Late Night Jazz Cafe", "jazz", "심야 재즈 카페 (Jazz)"),
            ("Slow R&B Chillout", "chill", "도심 야경 발코니 (Chill)"),
            ("chill", "chill", "도심 야경 발코니 (Chill)"),
            ("Warm Acoustic / Folk", "acoustic", "햇살 다락방 서재 (Acoustic)"),
            ("Dark Atmospheric Ambient", "ambient", "자정의 침실 (Ambient)"),
            ("Synthwave / Cyberpunk", "chill", "도심 야경 발코니 (Chill)"),   # 보관 장르 → 발코니
            ("Nostalgic City Pop", "chill", "도심 야경 발코니 (Chill)"),
            ("Cinematic Felt Piano & Neoclassical", "piano", "달밤 창가 피아노 (Piano)"),
            ("감성 로파이 비트", "lofi", "책상 서재 (Lo-Fi)"),
            ("새벽 감성 피아노 연주곡", "piano", "달밤 창가 피아노 (Piano)"),
            ("깊은 수면과 명상을 위한 델타파", "sleep", "포근한 수면 안식처 (Sleep)"),
            ("심야 재즈 바", "jazz", "심야 재즈 카페 (Jazz)"),
            ("어쿠스틱 통기타", "acoustic", "햇살 다락방 서재 (Acoustic)"),
            ("시티팝 & 드라이브", "chill", "도심 야경 발코니 (Chill)"),
            ("신스웨이브 밤 드라이브", "chill", "도심 야경 발코니 (Chill)"),
            ("앰비언트 사운드스케이프", "ambient", "자정의 침실 (Ambient)"),
            ("햇살 다락방 서재 (Acoustic)", "acoustic", "햇살 다락방 서재 (Acoustic)"),  # 룸 이름의 '서재'가 lofi 로 새지 않음
            ("힐링 재즈 피아노", "piano", "달밤 창가 피아노 (Piano)"),
            ("힐링 재즈", "jazz", "심야 재즈 카페 (Jazz)"),            # '힐링'은 범용어라 수면으로 끌고 가지 않음
            ("기타 장르", "lofi", "책상 서재 (Lo-Fi)"),                # '기타'(etc.)를 어쿠스틱 기타로 오인하지 않음
            ("Electricity Pulse", "lofi", "책상 서재 (Lo-Fi)"),       # 'city' 부분 일치로 발코니가 되지 않음
            ("unknown_custom_genre", "lofi", "책상 서재 (Lo-Fi)"),  # fallback
        ]
        for raw_genre, expected_key, expected_room in test_cases:
            res = luna_engine.resolve_signature_bga(raw_genre)
            self.assertEqual(res["genre_key"], expected_key, f"Failed for {raw_genre}")
            self.assertEqual(res["room_name"], expected_room, f"Failed for {raw_genre}")

    def test_every_preset_genre_resolves_to_existing_map_entry(self):
        """GENRE_PRESETS 의 모든 장르명이 SIGNATURE_BGA_MAP 안의 룸으로 귀결되는지 (새 장르 추가 시 매핑 누락 방지)."""
        for preset in luna_engine.GENRE_PRESETS:
            res = luna_engine.resolve_signature_bga(preset["name"])
            self.assertIn(res["genre_key"], luna_engine.SIGNATURE_BGA_MAP, preset)

    def test_bga_assets_are_repo_local(self):
        """모든 에셋 경로가 저장소 내부(data/bga_assets)에 위치하는지 검증 (세션 캐시 누출 방지)."""
        for k, item in luna_engine.SIGNATURE_BGA_MAP.items():
            v_path = os.path.join(luna_engine.BGA_ASSETS_DIR, item["video"])
            t_path = os.path.join(luna_engine.BGA_ASSETS_DIR, item["thumbnail"])
            self.assertTrue(v_path.startswith(str(BASE_DIR)))
            self.assertTrue(t_path.startswith(str(BASE_DIR)))



def _ffmpeg_ok():
    return shutil.which("ffmpeg") is not None


class SignatureAssetGenerationTests(unittest.TestCase):
    """루프 mp4 자동 생성은 같은 장르 썸네일로만, 그리고 렌더·업로드 경로에서만 일어난다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dp = patch.object(luna_engine, "BGA_ASSETS_DIR", self.tmp)
        self.dp.start()

    def tearDown(self):
        self.dp.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_resolve_does_not_generate_by_default(self):
        with patch.object(luna_engine, "ensure_signature_bga_asset") as ens:
            res = luna_engine.resolve_signature_bga("Emotional Piano Solo")
        ens.assert_not_called()
        self.assertIsNone(res["video_path"])

    def test_missing_thumbnail_never_borrows_another_room(self):
        # lofi 썸네일만 있을 때 piano 루프를 lofi 그림으로 만들면 bga_piano_moonlight.mp4 에 엉뚱한 룸이 영구히 박힌다
        shutil.copy(BGA_DIR / "thumb_lofi_cat.jpg", os.path.join(self.tmp, "thumb_lofi_cat.jpg"))
        with patch.object(luna_engine.subprocess, "run") as run:
            self.assertIsNone(luna_engine.ensure_signature_bga_asset("piano"))
        run.assert_not_called()
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "bga_piano_moonlight.mp4")))

    def test_failed_generation_leaves_no_file(self):
        shutil.copy(BGA_DIR / "thumb_piano_cat.jpg", os.path.join(self.tmp, "thumb_piano_cat.jpg"))
        fail = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")
        with patch.object(luna_engine.subprocess, "run", return_value=fail):
            self.assertIsNone(luna_engine.ensure_signature_bga_asset("piano"))
        self.assertEqual(sorted(os.listdir(self.tmp)), ["thumb_piano_cat.jpg"])


@unittest.skipUnless(_ffmpeg_ok(), "ffmpeg 필요")
class RenderFallbackSourceTests(unittest.TestCase):
    """루프 합성이 안 될 때의 폴백 영상은 signature_bga 로 위장하지 않는다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.assets = os.path.join(self.tmp, "assets")
        os.makedirs(self.assets)
        self.lp = patch.object(luna_engine, "LUNA_DIR", self.tmp)
        self.dp = patch.object(luna_engine, "BGA_ASSETS_DIR", self.assets)
        self.ep = patch.object(luna_engine, "ensure_signature_bga_asset", return_value=None)
        for p in (self.lp, self.dp, self.ep):
            p.start()
        t_dir = os.path.join(self.tmp, "t1")
        os.makedirs(t_dir)
        self.audio = os.path.join(t_dir, "audio.mp3")
        self.cover = os.path.join(t_dir, "cover.jpg")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:d=2", self.audio], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:s=320x180",
                        "-frames:v", "1", self.cover], check=True)
        self.track = {"track_id": "t1", "genre": "Emotional Piano Solo", "title": "T",
                      "audio_file": self.audio, "cover_file": self.cover, "duration_seconds": 2}

    def tearDown(self):
        for p in (self.lp, self.dp, self.ep):
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_signature_thumbnail_fallback_is_labelled(self):
        shutil.copy(self.cover, os.path.join(self.assets, "thumb_piano_cat.jpg"))
        res = luna_engine.render_luna_video(dict(self.track), quality="360p")
        self.assertEqual(res["video_source"], "signature_thumbnail")
        self.assertEqual(res["signature_bga_room"], "달밤 창가 피아노 (Piano)")
        self.assertIn(res["video_source"], luna_engine.SIGNATURE_VIDEO_SOURCES)

    def test_cover_fallback_does_not_claim_a_room(self):
        t = dict(self.track, video_source="signature_bga", signature_bga_room="달밤 창가 피아노 (Piano)")
        res = luna_engine.render_luna_video(t, quality="360p")
        self.assertEqual(res["video_source"], "cover")
        self.assertNotIn("signature_bga_room", res)
        self.assertNotIn(res["video_source"], luna_engine.SIGNATURE_VIDEO_SOURCES)


class UploadSignatureRerenderTests(unittest.TestCase):
    """업로드 전: 장르 대표 룸이 아닌 롱폼·숏폼 영상은 백업 후 대표 BGA 로 다시 렌더하고, 실패하면 올리지 않는다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for p in (patch.object(luna_engine, "LUNA_DIR", self.tmp),
                  patch.object(luna_engine, "ensure_signature_bga_asset", return_value=None)):
            p.start(); self.addCleanup(p.stop)
        self.d = os.path.join(self.tmp, "luna_v"); os.makedirs(self.d)
        for name, body in (("audio.mp3", b"a"), ("audio_shorts.mp3", b"a"), ("video.mp4", b"veo"), ("video_shorts.mp4", b"cover")):
            open(os.path.join(self.d, name), "wb").write(body)
        self.track = {
            "track_id": "luna_v", "title": "Song", "genre": "Emotional Piano Solo", "video_source": "bga-remotion",
            "metadata": {"youtube_title": "[Piano] Song", "youtube_description": "desc", "youtube_tags": ["t"], "pinned_comment": "pin"},
            "shorts": {"video_file": os.path.join(self.d, "video_shorts.mp4"), "audio_file": os.path.join(self.d, "audio_shorts.mp3"),
                       "video_source": "cover"},
        }
        luna_engine.save_track(self.track)
        self.room = "달밤 창가 피아노 (Piano)"

    def _fake_render(self, key):
        def render(track, *a, **kw):
            info = track if key is None else track.setdefault(key, {})
            info.update(video_source="signature_bga", signature_bga_room=self.room)
            return track
        return render

    def _fake_upload(self, **kw):
        return {"video_id": "VID", "url": "https://youtu.be/VID", "comment_posted": True, "warnings": []}

    def test_longform_and_shorts_are_rerendered_with_backup(self):
        with patch.object(luna_engine, "render_luna_video", side_effect=self._fake_render(None)) as rl, \
                patch.object(luna_engine, "render_luna_shorts_video", side_effect=self._fake_render("shorts")) as rs, \
                patch.object(luna_engine.uploader, "upload_video", side_effect=self._fake_upload):
            res = luna_engine.upload_luna_to_youtube("luna_v", with_shorts=True)
        rl.assert_called_once()
        rs.assert_called_once()
        self.assertEqual(res["status"], "success")
        self.assertEqual(open(os.path.join(self.d, "video_bga-remotion_backup.mp4"), "rb").read(), b"veo")
        self.assertEqual(open(os.path.join(self.d, "video_shorts_cover_backup.mp4"), "rb").read(), b"cover")

    def test_already_signature_videos_are_not_rerendered(self):
        self.track.update(video_source="signature_bga", signature_bga_room=self.room)
        self.track["shorts"].update(video_source="signature_thumbnail", signature_bga_room=self.room)
        luna_engine.save_track(self.track)
        with patch.object(luna_engine, "render_luna_video") as rl, \
                patch.object(luna_engine, "render_luna_shorts_video") as rs, \
                patch.object(luna_engine.uploader, "upload_video", side_effect=self._fake_upload):
            luna_engine.upload_luna_to_youtube("luna_v", with_shorts=True)
        rl.assert_not_called()
        rs.assert_not_called()

    def test_failed_rerender_restores_video_and_aborts_upload(self):
        def broken(track, *a, **kw):
            open(os.path.join(self.d, "video.mp4"), "wb").write(b"half")
            raise RuntimeError("ffmpeg died")
        with patch.object(luna_engine, "render_luna_video", side_effect=broken), \
                patch.object(luna_engine.uploader, "upload_video") as up:
            with self.assertRaises(RuntimeError):
                luna_engine.upload_luna_to_youtube("luna_v")
        up.assert_not_called()
        self.assertEqual(open(os.path.join(self.d, "video.mp4"), "rb").read(), b"veo")


class BannedBrandMetadataTests(unittest.TestCase):
    def test_detects_old_brand_in_description_and_tags_not_only_title(self):
        clean = {"youtube_title": "[Piano] Felt", "youtube_description": "음악: 루나의 심야 서재", "youtube_tags": ["수면음악"]}
        self.assertFalse(luna_engine.metadata_has_banned_brand(clean))
        self.assertTrue(luna_engine.metadata_has_banned_brand(dict(clean, youtube_description="- 작곡: 에이전트 루나 (Agent Luna)")))
        self.assertTrue(luna_engine.metadata_has_banned_brand(dict(clean, youtube_tags=["에이전트루나"])))
        self.assertTrue(luna_engine.metadata_has_banned_brand(dict(clean, shorts={"youtube_description": "#Shorts #AgentLuna"})))

    def test_concept_tags_with_old_brand_are_dropped(self):
        track = {"title": "Felt (펠트)", "genre": "Emotional Piano Solo", "mood": "새벽", "story": "이야기",
                 "has_lyrics": False, "duration": 180, "tags": ["에이전트루나", "AgentLuna", "피아노"]}
        with patch.object(luna_engine.llm_client, "call_llm_json", side_effect=RuntimeError("down")):
            meta = luna_engine.build_luna_metadata(track)
        self.assertFalse(luna_engine.metadata_has_banned_brand(meta), meta["youtube_tags"])
        self.assertIn("피아노", meta["youtube_tags"])


if __name__ == "__main__":
    unittest.main()
