"""루나 가사·프롬프트 동기화 버그 수정 테스트 (fix/prompt-lyrics-mismatch).

버그 1) 레오 브리프(title_concept/topic/angle/target_audience)가 루나 콘셉트 프롬프트에 빠지거나
       LLM 실패 시 브리프와 무관한 템플릿 곡이 조용히 만들어짐.
버그 2) Lyria 호출에 가사가 전달되지 않아 음원 노랫말과 설명란 가사가 다름.
       + 설명란 가사를 LLM 이 옮겨 쓰면서 요약·변형됨.
       + 백업 신스(보컬 없음) 음원인데 설명란에 가사가 올라감.
LLM·Lyria·ffmpeg 호출은 전부 모킹한다.
"""

import base64
import os
import tempfile
import unittest
from unittest.mock import patch

import luna_engine
import producer

LYRICS_KO = "[Verse 1]\n창틀에 번진 빗물 자국\n푸른 도면 위로 흐르네\n\n[Chorus]\n번져버린 선들을 따라\n지난 계절의 너를 보낸다\n\n[Outro]\n비가 그치면..."

LEO_BRIEF = {
    "brief_id": 1,
    "title_concept": "Waterlogged Blueprint (물기 젖은 청사진)",
    "genre": "piano", "genre_name": "Neoclassical Piano",
    "mood": "rainy", "mood_name": "비 오는 창가 (Rainy Window)",
    "topic": "빗물에 번져버린 미완의 건축 도면을 바라보며 지난 계절의 약속을 떠나보내는 순간",
    "angle": "펠트 피아노 타건음과 빗방울 필드 레코딩으로 시작, 4마디째 첼로 보잉",
    "target_audience": "빗소리를 배경 삼아 감정을 정리하는 리스너",
    "keywords": ["펠트피아노", "빗물자국", "미완의도면"],
}


def _llm_concept(**overrides):
    base = {
        "title": "Bleeding Blueprints (빗물에 번진 청사진)",
        "story": "서사",
        "has_lyrics": True, "vocal_language": "ko", "vocal_style": "soft Korean vocals",
        "lyrics": LYRICS_KO,
        "lyria_prompt": "Felt piano ballad, 62 BPM, emotional Korean female vocals, singing in clear Korean lyrics, gentle outro fade-out",
        "visual_prompt": "cover", "tags": ["a"],
    }
    base.update(overrides)
    return base, "raw"


# ── 버그 1: 레오 브리프 반영 ──────────────────────────────────────────────
class LeoBriefIntoConceptTests(unittest.TestCase):
    def test_normalize_maps_music_brief_fields(self):
        b = luna_engine.normalize_leo_brief(LEO_BRIEF)
        self.assertEqual(b["title_concept"], LEO_BRIEF["title_concept"])
        self.assertEqual(b["audience"], LEO_BRIEF["target_audience"])
        self.assertEqual(b["keywords"], LEO_BRIEF["keywords"])
        # 일반 트렌드 리포트형(audience_triggers) 도 받는다
        self.assertEqual(luna_engine.normalize_leo_brief({"audience_triggers": "x"})["audience"], "x")
        self.assertIsNone(luna_engine.normalize_leo_brief("not a dict"))

    def test_prompt_contains_title_concept_angle_audience(self):
        captured = {}

        def fake_llm(messages, **kw):
            captured["prompt"] = messages[-1]["content"]
            captured["max_tokens"] = kw.get("max_tokens")
            return _llm_concept()

        with patch.object(luna_engine.llm_client, "call_llm_json", side_effect=fake_llm):
            c = luna_engine.generate_music_concept(genre="piano", mood="rainy", leo_brief=LEO_BRIEF, vocal_mode="lyrics")
        p = captured["prompt"]
        for needle in (LEO_BRIEF["title_concept"], LEO_BRIEF["topic"], LEO_BRIEF["angle"], LEO_BRIEF["target_audience"], "펠트피아노"):
            self.assertIn(needle, p)
        self.assertIn("기획서", p)                       # 브리프를 '영감'이 아닌 기획서로 지시
        self.assertGreaterEqual(captured["max_tokens"], 8192)  # 응답 잘림 → 폴백 사고 방지
        self.assertEqual(c["concept_source"], "llm")
        self.assertEqual(c["trend_brief"]["title_concept"], LEO_BRIEF["title_concept"])
        self.assertEqual(c["trend_brief"]["audience_triggers"], LEO_BRIEF["target_audience"])

    def test_llm_failure_keeps_brief_title_and_topic_and_flags_fallback(self):
        with patch.object(luna_engine.llm_client, "call_llm_json", side_effect=RuntimeError("down")):
            c = luna_engine.generate_music_concept(genre="piano", mood="rainy", leo_brief=LEO_BRIEF, vocal_mode="auto")
        self.assertEqual(c["title"], LEO_BRIEF["title_concept"])
        self.assertEqual(c["story"], LEO_BRIEF["topic"])
        self.assertEqual(c["concept_source"], "fallback")
        self.assertIn("템플릿", c["concept_warning"])
        self.assertIn("펠트피아노", c["tags"])
        self.assertIn("Theme:", c["lyria_prompt"])

    def test_llm_failure_without_brief_uses_genre_template_including_dark_ambient(self):
        with patch.object(luna_engine.llm_client, "call_llm_json", side_effect=RuntimeError("down")):
            c = luna_engine.generate_music_concept(genre="dark-ambient", mood="focus", vocal_mode="auto")
        self.assertEqual(c["concept_source"], "fallback")
        self.assertNotIn("Velvet Afterglow", c["title"])   # 예전엔 lofi 템플릿으로 떨어졌다
        self.assertIn("Abyssal", c["title"])


# ── 버그 2: Lyria 입력에 가사 포함 ───────────────────────────────────────
class LyriaInputTests(unittest.TestCase):
    def test_vocal_track_input_has_direction_then_exact_lyrics(self):
        track = {"lyria_prompt": "Felt piano ballad, 62 BPM, Korean female vocals", "has_lyrics": True,
                 "lyrics": LYRICS_KO, "vocal_language": "ko"}
        inp = luna_engine.build_lyria_input(track)
        self.assertTrue(inp.startswith("Felt piano ballad"))
        self.assertIn("Sing exactly the following lyrics in Korean", inp)
        self.assertIn(LYRICS_KO, inp)                     # 가사 원문이 한 글자도 바뀌지 않고 들어간다
        self.assertLess(inp.index("62 BPM"), inp.index("[Verse 1]"))

    def test_instrumental_track_input_has_no_lyrics(self):
        track = {"lyria_prompt": "Felt piano, no vocals", "has_lyrics": False, "lyrics": LYRICS_KO}
        inp = luna_engine.build_lyria_input(track)
        self.assertNotIn("[Verse", inp)
        self.assertNotIn("Sing exactly", inp)

    def test_sanitizer_touches_direction_but_not_lyrics(self):
        track = {"lyria_prompt": "dark drone pad", "has_lyrics": True, "vocal_language": "en",
                 "lyrics": "[Verse 1]\nIn the dark I hear the drone of the city"}
        inp = luna_engine.build_lyria_input(track)
        self.assertTrue(inp.startswith("deep night deep bass tone pad"))      # 지시문은 순화
        self.assertIn("In the dark I hear the drone of the city", inp)         # 가사는 원문 유지

    def test_lyria_generate_sends_lyrics_in_input_and_returns_output_text(self):
        sent = {}

        def fake_create(client, api_key, payload):
            sent["payload"] = payload
            return {"id": "it1", "status": "completed",
                    "outputs": [{"type": "text", "text": "[Verse 1]\n창틀에 번진 빗물 자국"},
                                {"type": "audio", "data": base64.b64encode(b"\x00" * 4000).decode()}]}

        track = {"lyria_prompt": "Felt piano ballad, 62 BPM", "has_lyrics": True, "lyrics": LYRICS_KO, "vocal_language": "ko"}
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(producer, "get_genai_client", return_value=None), \
             patch.object(producer, "_create_interaction", side_effect=fake_create), \
             patch.object(producer, "_wait_interaction", side_effect=lambda c, k, r, **kw: r):
            out = os.path.join(tmp, "a.mp3")
            text = luna_engine._lyria_generate("key", "lyria-3.5", luna_engine.build_lyria_input(track), 180, out)
            self.assertTrue(os.path.getsize(out) >= 4000)
        self.assertEqual(sent["payload"]["model"], "lyria-3.5")
        self.assertIn(LYRICS_KO, sent["payload"]["input"][0]["text"])
        self.assertIn("창틀에 번진", text)

    def test_generate_luna_audio_records_lyria_input_and_vocal_flags(self):
        track = {"track_id": "luna_test_sync", "lyria_prompt": "Felt piano ballad, 62 BPM", "has_lyrics": True,
                 "lyrics": LYRICS_KO, "vocal_language": "ko"}

        def fake_gen(key, model, prompt, dur, out_path):
            with open(out_path, "wb") as f:
                f.write(b"\x00" * 5000)
            return "[Verse 1] 창틀에 번진 빗물 자국"

        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(luna_engine, "LUNA_DIR", tmp), \
             patch.object(producer, "gemini_key", return_value="k"), \
             patch.object(luna_engine, "_lyria_generate", side_effect=fake_gen), \
             patch.object(luna_engine, "_ensure_audio_duration", return_value=180.0), \
             patch.object(luna_engine.vega_engine, "master_track", return_value=None):
            t = luna_engine.generate_luna_audio(track, duration_seconds=180, master_audio=False)
        self.assertIn(LYRICS_KO, t["lyria_input"])
        self.assertTrue(t["audio_has_vocals"])
        self.assertTrue(t["lyrics_in_audio"])
        self.assertIn("창틀에 번진", t["lyria_output_text"])

    def test_synth_fallback_marks_audio_without_vocals(self):
        track = {"track_id": "luna_test_fb", "lyria_prompt": "x", "has_lyrics": True, "lyrics": LYRICS_KO, "vocal_language": "ko"}

        def fake_synth(path, duration=180):
            with open(path, "wb") as f:
                f.write(b"\x00" * 5000)

        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(luna_engine, "LUNA_DIR", tmp), \
             patch.object(producer, "gemini_key", return_value=None), \
             patch.object(luna_engine, "_generate_fallback_ambient_mp3", side_effect=fake_synth), \
             patch.object(luna_engine, "_ensure_audio_duration", return_value=180.0):
            t = luna_engine.generate_luna_audio(track, duration_seconds=180, master_audio=False)
        self.assertFalse(t["is_ai_generated"])
        self.assertFalse(t["audio_has_vocals"])
        self.assertTrue(t["has_lyrics"])   # 가사 텍스트 자체는 남겨 UI 에서 볼 수 있다


# ── 버그 2: 설명란 가사는 원문 그대로 ────────────────────────────────────
class DescriptionLyricsTests(unittest.TestCase):
    def _track(self, **kw):
        t = {"title": "Bleeding Blueprints", "genre": "Emotional Piano Solo", "mood": "비 오는 창가", "story": "서사",
             "has_lyrics": True, "lyrics": LYRICS_KO, "vocal_style": "soft", "duration_seconds": 170}
        t.update(kw)
        return t

    def test_llm_placeholder_is_replaced_with_exact_lyrics(self):
        llm = ({"youtube_title": "T", "pinned_comment": "질문입니다.",
                "youtube_description": f"스토리\n\n작곡: 루나\n\n{luna_engine.LYRICS_PLACEHOLDER}\n\n[Timeline]\n0:00 X\n\n#a #b"}, "raw")
        with patch.object(luna_engine.llm_client, "call_llm_json", return_value=llm):
            meta = luna_engine.build_luna_metadata(self._track())
        d = meta["youtube_description"]
        self.assertNotIn(luna_engine.LYRICS_PLACEHOLDER, d)
        self.assertIn(f"[Lyrics / 가사]\n{LYRICS_KO}", d)
        self.assertEqual(d.count("[Lyrics / 가사]"), 1)
        self.assertLess(d.index("[Lyrics / 가사]"), d.index("[Timeline]"))

    def test_llm_paraphrased_lyrics_are_replaced_by_original(self):
        paraphrased = "[Lyrics / 가사]\n[Verse 1]\n창가에 번진 빗물 흔적\n파란 도면 위로 흐른다\n\n[Chorus]\n흐려진 선을 따라 널 보낸다"
        llm = ({"youtube_title": "T", "pinned_comment": "질문입니다.",
                "youtube_description": f"스토리\n\n{paraphrased}\n\n[Timeline]\n0:00 X\n\n#a"}, "raw")
        with patch.object(luna_engine.llm_client, "call_llm_json", return_value=llm):
            meta = luna_engine.build_luna_metadata(self._track())
        d = meta["youtube_description"]
        self.assertNotIn("창가에 번진 빗물 흔적", d)        # LLM 변형 가사 제거
        self.assertIn("창틀에 번진 빗물 자국", d)            # 원문 가사 삽입
        self.assertEqual(d.count("[Lyrics / 가사]"), 1)
        self.assertIn("[Timeline]", d)
        self.assertIn("#a", d)

    def test_llm_omitted_lyrics_are_inserted_before_timeline(self):
        llm = ({"youtube_title": "T", "pinned_comment": "질문입니다.",
                "youtube_description": "스토리\n\n[Timeline]\n0:00 X"}, "raw")
        with patch.object(luna_engine.llm_client, "call_llm_json", return_value=llm):
            meta = luna_engine.build_luna_metadata(self._track())
        d = meta["youtube_description"]
        self.assertIn(LYRICS_KO, d)
        self.assertLess(d.index("[Lyrics"), d.index("[Timeline]"))

    def test_prompt_does_not_ask_llm_to_copy_full_lyrics(self):
        captured = {}

        def fake(messages, **kw):
            captured["p"] = messages[-1]["content"]
            raise RuntimeError("down")

        long_lyrics = "\n".join(f"[Verse {i}]\n가사 줄 {i}" for i in range(1, 15)) + "\n\n[Outro]\n마지막 여운"
        with patch.object(luna_engine.llm_client, "call_llm_json", side_effect=fake):
            luna_engine.build_luna_metadata(self._track(lyrics=long_lyrics))
        self.assertIn(luna_engine.LYRICS_PLACEHOLDER, captured["p"])
        self.assertIn("가사 줄 1", captured["p"])
        self.assertNotIn("마지막 여운", captured["p"])   # 전문이 아닌 발췌(앞 10줄)만 제공
        self.assertIn("직접 옮겨 쓰지 말 것", captured["p"])

    def test_fallback_description_has_exact_lyrics(self):
        with patch.object(luna_engine.llm_client, "call_llm_json", side_effect=RuntimeError("down")):
            meta = luna_engine.build_luna_metadata(self._track())
        self.assertIn(f"[Lyrics / 가사]\n{LYRICS_KO}", meta["youtube_description"])
        self.assertIn("보컬: 에이전트 루나", meta["youtube_description"])

    def test_vocal_less_audio_drops_lyrics_and_vocal_credit(self):
        with patch.object(luna_engine.llm_client, "call_llm_json", side_effect=RuntimeError("down")):
            meta = luna_engine.build_luna_metadata(self._track(audio_has_vocals=False))
        d = meta["youtube_description"]
        self.assertNotIn("[Lyrics", d)
        self.assertNotIn("보컬:", d)
        self.assertNotIn("가사", meta["youtube_tags"])
        self.assertIn("순수연주곡", meta["youtube_tags"])

    def test_legacy_track_without_flag_still_includes_lyrics(self):
        with patch.object(luna_engine.llm_client, "call_llm_json", side_effect=RuntimeError("down")):
            meta = luna_engine.build_luna_metadata(self._track())   # audio_has_vocals 키 없음 (구 트랙)
        self.assertIn("[Lyrics / 가사]", meta["youtube_description"])

    def test_description_capped_to_youtube_limit(self):
        long_lyrics = "\n".join(f"[Verse {i}]\n" + "가" * 200 for i in range(40))
        with patch.object(luna_engine.llm_client, "call_llm_json", side_effect=RuntimeError("down")):
            meta = luna_engine.build_luna_metadata(self._track(lyrics=long_lyrics))
        self.assertLessEqual(len(meta["youtube_description"]), luna_engine.YOUTUBE_DESCRIPTION_MAX)

    def test_shorts_description_excludes_lyric_body_paragraphs(self):
        base = {"youtube_description": f"스토리\n\n[Lyrics / 가사]\n[Verse 1]\n가사1\n\n[Chorus]\n가사2\n\n[Timeline]\n0:00", "youtube_tags": []}
        m = luna_engine.build_luna_shorts_metadata({"title": "X", "genre": "Lo-Fi / Chillhop"}, base)
        self.assertNotIn("가사2", m["youtube_description"])
        self.assertNotIn("[Chorus]", m["youtube_description"])
        self.assertIn("스토리", m["youtube_description"])


class SanitizerMusicTermTests(unittest.TestCase):
    def test_music_terms_survive_safety_sanitizer(self):
        out = luna_engine._sanitize_lyria_prompt("Dark Atmospheric Ambient, dark ambient drone, zero percussive attack, soft attack pads, a dark alley attack")
        self.assertIn("Dark Atmospheric Ambient", out)
        self.assertIn("dark ambient", out)
        self.assertIn("percussive attack", out)
        self.assertIn("soft attack", out)
        self.assertIn("deep night alley crescendo", out)   # 장르·음악 용어가 아닌 곳만 순화
        self.assertNotIn("drone", out)


class StripHelperTests(unittest.TestCase):
    def test_strip_keeps_non_lyric_sections(self):
        desc = "소개\n\n[Lyrics / 가사]\n[Verse 1]\n라라\n\n[Chorus]\n룰루\n\n✨ 구독해주세요\n\n[Timeline]\n0:00 A\n\n#tag"
        out = luna_engine._strip_llm_lyrics_section(desc)
        self.assertNotIn("라라", out)
        self.assertIn(luna_engine.LYRICS_PLACEHOLDER, out)
        self.assertIn("✨ 구독해주세요", out)
        self.assertIn("[Timeline]", out)
        self.assertIn("#tag", out)

    def test_strip_ignores_story_sentence_starting_with_gasa(self):
        desc = "가사 한 줄 한 줄이 빗물처럼 스며드는 곡입니다.\n\n[Timeline]\n0:00 A"
        self.assertEqual(luna_engine._strip_llm_lyrics_section(desc), desc)

    def test_strip_handles_colon_header(self):
        desc = "소개\n\nLyrics:\n[Verse 1]\n라라\n\n#tag"
        out = luna_engine._strip_llm_lyrics_section(desc)
        self.assertNotIn("라라", out)
        self.assertIn("#tag", out)

    def test_strip_without_lyrics_is_noop(self):
        desc = "소개\n\n[Timeline]\n0:00 A"
        self.assertEqual(luna_engine._strip_llm_lyrics_section(desc), desc)


if __name__ == "__main__":
    unittest.main()
