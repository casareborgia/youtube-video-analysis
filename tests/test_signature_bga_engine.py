"""장르별 대표 BGA(시그니처 룸) 자동 매핑 및 렌더러 단위 테스트."""
import os
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
