"""채널 개편(루나의 심야 서재) 검증 테스트.

- 구독 링크는 핸들이 아닌 채널 ID URL (핸들 @LunaMidnightRoom 은 존재하지 않아 404 였다)
- 폴백 메타데이터/콘셉트 태그에 'AI음악', '에이전트 루나' 같은 기계적 수식어가 남지 않는다
- 제목 앞 장르 태그 판별 (Lo-Fi 표기 변형 포함)
- 레오 브리프 3 폴백/교정이 개편으로 배제된 장르(synthwave·citypop 등)를 고르지 않는다
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import luna_engine
import trend_scout


class SubscribeUrlTests(unittest.TestCase):
    def test_subscribe_url_uses_channel_id_not_handle(self):
        self.assertIn("/channel/UCowTfbpKpXDBF3Mc50H4iGQ", luna_engine.LUNA_CHANNEL_SUBSCRIBE_URL)
        self.assertNotIn("/@", luna_engine.LUNA_CHANNEL_SUBSCRIBE_URL)

    def test_fallback_description_has_channel_url_and_no_ai_wording(self):
        track = {"title": "Quiet Dust (고요한 먼지)", "genre": "Lo-Fi / Chillhop", "mood": "새벽 감성",
                 "story": "이야기", "has_lyrics": False, "duration": 180}
        with patch.object(luna_engine.llm_client, "call_llm_json", side_effect=RuntimeError("down")):
            meta = luna_engine.build_luna_metadata(track)
        desc = meta["youtube_description"]
        self.assertIn(luna_engine.LUNA_CHANNEL_SUBSCRIBE_URL, desc)
        self.assertNotIn("@LunaMidnightRoom", desc)
        self.assertNotIn("음악에이전트-c3j", desc)
        for banned in ("AI음악", "에이전트 루나", "Agent Luna"):
            self.assertNotIn(banned, meta["youtube_title"])
            self.assertNotIn(banned, desc)
            self.assertNotIn(banned, " ".join(meta["youtube_tags"]))
        self.assertTrue(meta["youtube_title"].startswith("[Lo-Fi]"), meta["youtube_title"])


class GenreTitleTagTests(unittest.TestCase):
    def test_lofi_variants(self):
        for g in ("Lo-Fi / Chillhop", "lofi", "LoFi Beats", "Chillhop"):
            self.assertEqual(luna_engine.genre_title_tag(g), "Lo-Fi", g)

    def test_other_genres(self):
        self.assertEqual(luna_engine.genre_title_tag("Emotional Piano Solo"), "Piano")
        self.assertEqual(luna_engine.genre_title_tag("Deep Sleep / Meditation"), "Sleep")
        self.assertEqual(luna_engine.genre_title_tag("Cinematic Ambient"), "Ambient")
        self.assertEqual(luna_engine.genre_title_tag("Late Night Jazz Cafe"), "Jazz")
        self.assertEqual(luna_engine.genre_title_tag(None), "Lo-Fi")


class ShortsHashtagTests(unittest.TestCase):
    def test_shorts_hashtags_follow_track_genre(self):
        track = {"title": "Felt Keys", "genre": "Emotional Piano Solo"}
        meta = luna_engine.build_luna_shorts_metadata(track, {"youtube_description": "스토리", "youtube_tags": []})
        desc = meta["youtube_description"]
        self.assertIn("#루나의심야서재", desc)
        self.assertIn("#EmotionalPianoSolo", desc)
        self.assertNotIn("#로파이", desc)   # 피아노 숏폼에 로파이 해시태그가 고정으로 붙지 않는다
        self.assertNotIn("#AgentLuna", desc)


class FallbackConceptTagTests(unittest.TestCase):
    def test_fallback_concept_tags_have_no_ai_wording(self):
        with patch.object(luna_engine.llm_client, "call_llm_json", side_effect=RuntimeError("down")):
            c = luna_engine.generate_music_concept(genre="lofi", mood="dawn", vocal_mode="instrumental")
        tags = " ".join(c["tags"])
        self.assertIn("루나의심야서재", tags)
        for banned in ("에이전트루나", "AgentLuna", "AI음악"):
            self.assertNotIn(banned, tags)


class LeoGenrePolicyTests(unittest.TestCase):
    def test_active_genres_exclude_zero_weight(self):
        active = trend_scout.active_luna_genres()
        for g in ("synthwave", "citypop", "rnb-chill", "dark-ambient"):
            self.assertNotIn(g, active)
        self.assertIn("lofi", active)
        self.assertIn("piano", active)

    def test_core_list_matches_weights(self):
        # 3대 코어 잠금: 가중치 > 0 인 장르 집합과 CORE_LUNA_GENRES 가 어긋나면 폴백 경로가 다른 장르를 고르게 된다
        self.assertEqual(set(trend_scout.active_luna_genres()), set(trend_scout.CORE_LUNA_GENRES))
        self.assertEqual(set(trend_scout.CORE_LUNA_GENRES), {"lofi", "piano", "ambient", "sleep"})

    def test_preset_labels_follow_lock(self):
        active = set(trend_scout.active_luna_genres())
        for preset in luna_engine.GENRE_PRESETS:
            if preset["id"] in active:
                self.assertIn("핵심 주력", preset["desc"], preset)
                self.assertNotIn("보관", preset["desc"], preset)
            else:
                self.assertIn("보관", preset["desc"], preset)

    def test_pick_balanced_never_returns_excluded(self):
        for _ in range(50):
            picked = trend_scout.pick_balanced_genres(2, stats={})
            self.assertEqual(len(set(picked)), 2)
            for g in picked:
                self.assertGreater(trend_scout.GENRE_BASE_WEIGHTS.get(g, 0.0), 0.0, picked)

    def test_brief3_correction_replaces_excluded_genre(self):
        # LLM 응답이 배제 장르(synthwave)를 3번 브리프에 넣어도 활성 장르로 교체되는지 확인
        fake = {
            "chart_insights": "x", "top_keywords": ["a"],
            "luna_briefs": [
                {"brief_id": 1, "title_concept": "A", "genre": "lofi", "mood": "dawn", "topic": "t", "angle": "a"},
                {"brief_id": 2, "title_concept": "B", "genre": "piano", "mood": "rainy", "topic": "t", "angle": "a"},
                {"brief_id": 3, "title_concept": "C", "genre": "synthwave", "mood": "calm", "topic": "t", "angle": "a"},
            ],
        }
        self._run_and_assert_active(llm_return=(fake, "{}"))

    def test_brief3_fallback_without_llm_stays_active(self):
        self._run_and_assert_active(llm_side_effect=RuntimeError("down"))

    def _run_and_assert_active(self, llm_return=None, llm_side_effect=None):
        import tempfile
        from pathlib import Path
        fake_trends = {"status": "success", "items": [
            {"rank": i, "title": f"곡 {i}", "channel_title": f"채널 {i}"} for i in range(1, 8)
        ]}
        active = set(trend_scout.active_luna_genres())
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            llm_kwargs = {"side_effect": llm_side_effect} if llm_side_effect else {"return_value": llm_return}
            with patch.object(trend_scout, "TRENDS_DIR", tmp_path), \
                 patch.object(trend_scout, "TOPIC_HISTORY_FILE", tmp_path / "topic_history.json"), \
                 patch.object(trend_scout, "fetch_top20_trends", return_value=fake_trends), \
                 patch.object(trend_scout, "get_production_genre_stats", return_value={}), \
                 patch.object(trend_scout.llm_client, "call_llm_json", **llm_kwargs):
                for _ in range(20):
                    result = trend_scout.analyze_music_trends_for_luna("KR", force_refresh=True)
                    briefs = result["analysis"]["luna_briefs"]
                    self.assertEqual(len(briefs), 3)
                    for b in briefs:
                        self.assertIn(b["genre"], active, b)
                    self.assertEqual(len({b["genre"] for b in briefs}), 3)

if __name__ == "__main__":
    unittest.main()
