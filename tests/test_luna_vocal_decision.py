"""루나 보컬/연주곡 판정 테스트 (Phase A — fix/luna-vocal-affinity).

LLM 호출은 전부 모킹한다. 검증 범위:
- vocal_affinity(none/high/optional) 기반 auto 판정
- 명시 모드가 LLM 응답에 덮이지 않음
- 주제 키워드가 affinity 보다 우선
- 단어 경계 검사로 "inst" 부분 문자열 오탐 방지
- vocal_decision.reason / vocal_mode 기록
"""

import unittest
from unittest.mock import patch

import luna_engine


def _llm_vocal_response(**overrides):
    """LLM 이 보컬 곡을 반환한 것처럼 꾸민 응답."""
    base = {
        "title": "Test Song (테스트)",
        "story": "테스트 서사",
        "has_lyrics": True,
        "vocal_language": "ko",
        "vocal_style": "soft Korean vocals",
        "lyrics": "[Verse 1]\n테스트 가사",
        "lyria_prompt": "Lo-fi beat, 75 BPM, emotional Korean female vocals, singing in clear Korean lyrics, gentle outro fade-out",
        "visual_prompt": "test cover",
        "tags": ["a", "b"],
    }
    base.update(overrides)
    return base, "raw"


def _llm_inst_response(**overrides):
    base, raw = _llm_vocal_response(
        has_lyrics=False, vocal_language=None, vocal_style=None, lyrics=None,
        lyria_prompt="Felt piano, 70 BPM, No vocals, purely instrumental, gentle outro fade-out",
    )
    base.update(overrides)
    return base, raw


class VocalKeywordDetectorTests(unittest.TestCase):
    def test_inst_keywords_word_boundary(self):
        self.assertEqual(luna_engine._detect_inst_keyword("piano solo at night"), "piano solo")
        self.assertEqual(luna_engine._detect_inst_keyword("chill inst beat"), "inst")
        self.assertEqual(luna_engine._detect_inst_keyword("study bgm"), "bgm")
        # 부분 문자열 오탐 방지
        self.assertIsNone(luna_engine._detect_inst_keyword("install guide music"))
        self.assertIsNone(luna_engine._detect_inst_keyword("instant coffee morning"))

    def test_inst_keywords_korean_longest_first(self):
        self.assertEqual(luna_engine._detect_inst_keyword("비 오는 날 피아노 독주"), "피아노 독주")
        self.assertEqual(luna_engine._detect_inst_keyword("잔잔한 연주곡"), "연주곡")
        self.assertEqual(luna_engine._detect_inst_keyword("노래없이 듣는 밤"), "노래없이")

    def test_vocal_keywords_ignore_negation(self):
        self.assertEqual(luna_engine._detect_vocal_keyword("감성 보컬 발라드"), "보컬")
        self.assertEqual(luna_engine._detect_vocal_keyword("dreamy vocals"), "vocals")
        # "노래없이" 안의 "노래", "no vocals" 안의 "vocals" 는 잡히면 안 된다
        self.assertIsNone(luna_engine._detect_vocal_keyword("노래없이 듣는 밤"))
        self.assertIsNone(luna_engine._detect_vocal_keyword("no vocals please"))

    def test_sanitize_instrumental_prompt(self):
        out = luna_engine._sanitize_instrumental_lyria_prompt(
            "Lo-fi beat, 75 BPM, emotional Korean female vocals, singing in clear Korean lyrics, soulful vocal hooks"
        )
        low = out.lower()
        self.assertNotIn("vocals", low.replace("no vocals", ""))
        self.assertNotIn("singing", low)
        self.assertNotIn("lyrics", low)
        self.assertIn("no vocals", low)
        self.assertIn("instrumental", low)
        self.assertIn("75 bpm", low)


class AutoModeAffinityTests(unittest.TestCase):
    """auto 모드에서 장르 vocal_affinity 가 판정을 결정하는지 (10개 장르 전수)."""

    def test_affinity_none_forces_instrumental_even_if_llm_sends_lyrics(self):
        for genre, spec in luna_engine.GENRE_SPECS.items():
            if spec["vocal_affinity"] != "none":
                continue
            with self.subTest(genre=genre), patch.object(luna_engine.llm_client, "call_llm_json", return_value=_llm_vocal_response()):
                c = luna_engine.generate_music_concept(genre=genre, mood="dawn", vocal_mode="auto")
            self.assertFalse(c["has_lyrics"])
            self.assertIsNone(c["lyrics"])
            self.assertIsNone(c["vocal_style"])
            self.assertIsNone(c["vocal_language"])
            self.assertEqual(c["vocal_decision"], {"resolved": "instrumental", "reason": "affinity:none"})
            self.assertEqual(c["vocal_mode"], "auto")
            low = c["lyria_prompt"].lower()
            self.assertIn("no vocals", low)
            self.assertNotIn("singing", low)

    def test_affinity_high_forces_lyrics_even_if_llm_sends_instrumental(self):
        for genre, spec in luna_engine.GENRE_SPECS.items():
            if spec["vocal_affinity"] != "high":
                continue
            with self.subTest(genre=genre), patch.object(luna_engine.llm_client, "call_llm_json", return_value=_llm_inst_response()):
                c = luna_engine.generate_music_concept(genre=genre, mood="dawn", vocal_mode="auto")
            self.assertTrue(c["has_lyrics"])
            self.assertEqual(c["vocal_decision"]["reason"], "affinity:high")
            self.assertEqual(c["vocal_language"], "ko")
            self.assertIn("korean", c["lyria_prompt"].lower())

    def test_affinity_optional_trusts_llm(self):
        optional = [g for g, s in luna_engine.GENRE_SPECS.items() if s["vocal_affinity"] == "optional"]
        self.assertTrue(optional)
        for genre in optional:
            with self.subTest(genre=genre, llm="vocal"), patch.object(luna_engine.llm_client, "call_llm_json", return_value=_llm_vocal_response()):
                c = luna_engine.generate_music_concept(genre=genre, mood="dawn", vocal_mode="auto")
            self.assertTrue(c["has_lyrics"])
            self.assertEqual(c["vocal_decision"], {"resolved": "lyrics", "reason": "llm"})

            with self.subTest(genre=genre, llm="inst"), patch.object(luna_engine.llm_client, "call_llm_json", return_value=_llm_inst_response()):
                c = luna_engine.generate_music_concept(genre=genre, mood="dawn", vocal_mode="auto")
            self.assertFalse(c["has_lyrics"])
            self.assertEqual(c["vocal_decision"], {"resolved": "instrumental", "reason": "llm"})

    def test_optional_llm_has_lyrics_string_true_is_accepted(self):
        with patch.object(luna_engine.llm_client, "call_llm_json", return_value=_llm_vocal_response(has_lyrics="true")):
            c = luna_engine.generate_music_concept(genre="lofi", mood="dawn", vocal_mode="auto")
        self.assertTrue(c["has_lyrics"])

    def test_optional_prompt_asks_llm_to_decide(self):
        captured = {}

        def fake_llm(messages, **kw):
            captured["prompt"] = messages[-1]["content"]
            return _llm_inst_response()

        with patch.object(luna_engine.llm_client, "call_llm_json", side_effect=fake_llm):
            luna_engine.generate_music_concept(genre="jazz", mood="dawn", vocal_mode="auto")
        self.assertIn("보컬 유무 자율 결정", captured["prompt"])
        self.assertIn('"has_lyrics"', captured["prompt"])


class ExplicitModeTests(unittest.TestCase):
    def test_instrumental_mode_overrides_llm_lyrics(self):
        with patch.object(luna_engine.llm_client, "call_llm_json", return_value=_llm_vocal_response()):
            c = luna_engine.generate_music_concept(genre="citypop", mood="dawn", vocal_mode="instrumental")
        self.assertFalse(c["has_lyrics"])
        self.assertIsNone(c["lyrics"])
        self.assertEqual(c["vocal_mode"], "instrumental")
        self.assertEqual(c["vocal_decision"], {"resolved": "instrumental", "reason": "explicit_mode"})
        low = c["lyria_prompt"].lower()
        self.assertIn("no vocals", low)
        self.assertNotIn("singing", low)
        self.assertNotIn("female vocals", low)

    def test_lyrics_mode_overrides_affinity_none(self):
        with patch.object(luna_engine.llm_client, "call_llm_json", return_value=_llm_inst_response()):
            c = luna_engine.generate_music_concept(genre="sleep", mood="dawn", vocal_mode="lyrics")
        self.assertTrue(c["has_lyrics"])
        self.assertEqual(c["vocal_mode"], "lyrics")
        self.assertEqual(c["vocal_decision"]["reason"], "explicit_mode")
        self.assertIn("korean", c["lyria_prompt"].lower())

    def test_mode_aliases_normalized(self):
        with patch.object(luna_engine.llm_client, "call_llm_json", return_value=_llm_vocal_response()):
            c = luna_engine.generate_music_concept(genre="lofi", mood="dawn", vocal_mode="INST")
        self.assertEqual(c["vocal_mode"], "instrumental")
        with patch.object(luna_engine.llm_client, "call_llm_json", return_value=_llm_vocal_response()):
            c = luna_engine.generate_music_concept(genre="lofi", mood="dawn", vocal_mode="vocal")
        self.assertEqual(c["vocal_mode"], "lyrics")
        with patch.object(luna_engine.llm_client, "call_llm_json", return_value=_llm_vocal_response()):
            c = luna_engine.generate_music_concept(genre="lofi", mood="dawn", vocal_mode=None)
        self.assertEqual(c["vocal_mode"], "auto")


class KeywordPriorityTests(unittest.TestCase):
    def test_inst_keyword_beats_affinity_high(self):
        with patch.object(luna_engine.llm_client, "call_llm_json", return_value=_llm_vocal_response()):
            c = luna_engine.generate_music_concept(genre="citypop", mood="dawn", custom_topic="피아노 독주", vocal_mode="auto")
        self.assertFalse(c["has_lyrics"])
        self.assertEqual(c["vocal_decision"]["reason"], "keyword:피아노 독주")

    def test_vocal_keyword_beats_affinity_none(self):
        with patch.object(luna_engine.llm_client, "call_llm_json", return_value=_llm_inst_response()):
            c = luna_engine.generate_music_concept(genre="piano", mood="dawn", custom_topic="감성 보컬 발라드", vocal_mode="auto")
        self.assertTrue(c["has_lyrics"])
        self.assertEqual(c["vocal_decision"]["reason"], "keyword:보컬")

    def test_install_does_not_trigger_inst(self):
        with patch.object(luna_engine.llm_client, "call_llm_json", return_value=_llm_vocal_response()):
            c = luna_engine.generate_music_concept(genre="citypop", mood="dawn", custom_topic="install guide", vocal_mode="auto")
        self.assertTrue(c["has_lyrics"])
        self.assertEqual(c["vocal_decision"]["reason"], "affinity:high")

    def test_leo_brief_topic_is_considered(self):
        brief = {"topic": "순수 연주곡 집중 BGM", "angle": "", "audience_triggers": "", "keywords": []}
        with patch.object(luna_engine.llm_client, "call_llm_json", return_value=_llm_vocal_response()):
            c = luna_engine.generate_music_concept(genre="lofi", mood="dawn", leo_brief=brief, vocal_mode="auto")
        self.assertFalse(c["has_lyrics"])
        self.assertTrue(c["vocal_decision"]["reason"].startswith("keyword:"))


class FallbackTests(unittest.TestCase):
    def test_llm_failure_optional_genre_falls_back_to_instrumental(self):
        with patch.object(luna_engine.llm_client, "call_llm_json", side_effect=RuntimeError("down")):
            c = luna_engine.generate_music_concept(genre="lofi", mood="dawn", vocal_mode="auto")
        self.assertFalse(c["has_lyrics"])
        self.assertEqual(c["vocal_decision"], {"resolved": "instrumental", "reason": "fallback:instrumental"})
        self.assertIn("no vocals", c["lyria_prompt"].lower())

    def test_llm_failure_keeps_explicit_lyrics(self):
        with patch.object(luna_engine.llm_client, "call_llm_json", side_effect=RuntimeError("down")):
            c = luna_engine.generate_music_concept(genre="citypop", mood="dawn", vocal_mode="lyrics")
        self.assertTrue(c["has_lyrics"])
        self.assertTrue(c["lyrics"])
        self.assertEqual(c["vocal_decision"]["reason"], "explicit_mode")


class ListTracksExposureTests(unittest.TestCase):
    def test_list_tracks_includes_vocal_fields_with_none_for_legacy(self):
        import json, os, tempfile
        with tempfile.TemporaryDirectory() as tmp, patch.object(luna_engine, "LUNA_DIR", tmp):
            os.makedirs(os.path.join(tmp, "luna_legacy"))
            with open(os.path.join(tmp, "luna_legacy", "meta.json"), "w", encoding="utf-8") as f:
                json.dump({"track_id": "luna_legacy", "title": "old", "has_lyrics": True}, f)
            os.makedirs(os.path.join(tmp, "luna_new"))
            with open(os.path.join(tmp, "luna_new", "meta.json"), "w", encoding="utf-8") as f:
                json.dump({"track_id": "luna_new", "title": "new", "has_lyrics": False,
                           "vocal_mode": "auto", "vocal_decision": {"resolved": "instrumental", "reason": "affinity:none"}}, f)
            rows = {t["track_id"]: t for t in luna_engine.list_tracks()}
        self.assertIsNone(rows["luna_legacy"]["vocal_mode"])
        self.assertIsNone(rows["luna_legacy"]["vocal_decision"])
        self.assertEqual(rows["luna_new"]["vocal_mode"], "auto")
        self.assertEqual(rows["luna_new"]["vocal_decision"]["reason"], "affinity:none")


if __name__ == "__main__":
    unittest.main()
