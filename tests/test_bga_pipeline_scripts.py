"""시그니처 BGA 파이프라인 스크립트 정책 테스트.

scripts/ 아래 유튜브 업로드 스크립트들의 공개 메타데이터 템플릿(설명·태그)에
채널 정책상 금지된 기계적 수식어('Agent Luna', 'AgentLuna', 'AI음악')가 다시 들어가지 않는지,
썸네일·소스 이미지가 저장소 밖(Antigravity brain 캐시)을 가리키지 않는지 확인한다.
"""
import importlib.util
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

BANNED = ("Agent Luna", "에이전트 루나", "AgentLuna", "AI음악")


def _load(name):
    path = os.path.join(BASE, "scripts", name)
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class UploadScriptPolicyTests(unittest.TestCase):
    def test_compilation_metadata_has_no_ai_wording_or_persona_credit(self):
        m = _load("create_luna_compilation.py")
        for genre in m.GENRE_CHOICES:
            playlist = [{"title": "A (가)", "duration": 180.0, "released": True},
                        {"title": "B (나)", "duration": 200.0, "released": False}]
            meta = m.build_youtube_metadata(genre, playlist, 380.0)
            text = " ".join([meta["youtube_title"], meta["youtube_description"], *meta["youtube_tags"]])
            for w in BANNED + ("에이전트 레오", "Agent Leo"):
                self.assertNotIn(w, text, (genre, w))
            self.assertLessEqual(len(meta["youtube_title"]), 100, meta["youtube_title"])
            self.assertLessEqual(len(meta["youtube_tags"]), 15)

    def test_replace_script_metadata_has_no_ai_wording(self):
        m = _load("replace_scheduled_videos_with_bga.py")
        desc = m.build_description("t", "story", "Lo-Fi")
        for w in BANNED:
            self.assertNotIn(w, desc, w)
            self.assertFalse(any(w in t for t in m.CLEAN_TAGS), w)
        for p in m.THUMB_FILES.values():
            self.assertTrue(str(p).startswith(BASE), p)

    def test_generator_sources_are_repo_local(self):
        m = _load("generate_signature_bga_assets.py")
        for p in m.SOURCE_IMAGES.values():
            self.assertTrue(str(p).startswith(BASE), p)
        self.assertEqual(set(m.SOURCE_IMAGES), set(m.TARGET_FILES))

    def test_live_fix_script_cleans_known_patterns(self):
        m = _load("fix_live_metadata_ai_trace.py")
        desc = "x\n음악: 에이전트 루나 (Agent Luna) - 루나의 심야 서재\n#로파이 #AgentLuna"
        out = m.clean_description(desc)
        for w in BANNED:
            self.assertNotIn(w, out)
        self.assertEqual(m.clean_tags(["로파이", "AgentLuna", "SleepBGM"]), ["로파이", "SleepBGM"])

    def test_adjustment_script_skips_replaced_ids(self):
        m = _load("apply_scheduled_video_adjustments.py")
        for old in m.REPLACED_BY_BGA:
            self.assertIn(old, m.ADJUSTMENTS)


if __name__ == "__main__":
    unittest.main()
