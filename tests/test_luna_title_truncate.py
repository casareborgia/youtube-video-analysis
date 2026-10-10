"""유튜브 제목 100자 단어 경계 컷 테스트."""

import unittest
from unittest.mock import patch

import luna_engine
from luna_engine import truncate_title


class TruncateTitleTests(unittest.TestCase):
    def test_short_title_unchanged(self):
        self.assertEqual(truncate_title("Short Title"), "Short Title")

    def test_cuts_at_word_boundary_not_mid_word(self):
        # 실제 사례: 100자 경계가 "Emotional Pi|ano Solo" 중간에 걸림
        t = "에이전트 루나 (Agent Luna) - Petrichor on Worn Felt (빗물 머금은 펠트 건반) | 비 내리는 새벽 창가, 엉킨 마음을 씻어내는 Emotional Piano Solo"
        out = truncate_title(t)
        self.assertLessEqual(len(out), 100)
        self.assertFalse(out.endswith("Pi"))
        self.assertTrue(out.endswith("씻어내는") or out.endswith("Emotional"), out)
        self.assertFalse(out.endswith((" ", "|", "-", ",", "(")))

    def test_suffix_always_preserved(self):
        out = truncate_title("A" * 120, suffix=" (Highlight) #Shorts")
        self.assertLessEqual(len(out), 100)
        self.assertTrue(out.endswith(" (Highlight) #Shorts"))

    def test_suffix_with_word_boundary(self):
        words = " ".join(["word"] * 40)  # 199자
        out = truncate_title(words, suffix=" #Shorts")
        self.assertLessEqual(len(out), 100)
        self.assertTrue(out.endswith("word #Shorts"))

    def test_falls_back_to_hard_cut_when_no_boundary(self):
        out = truncate_title("가" * 150)
        self.assertEqual(len(out), 100)

    def test_trailing_separator_removed(self):
        t = "제목 " + "x" * 90 + " | 뒤에 오는 긴 장르 이름"
        out = truncate_title(t)
        self.assertLessEqual(len(out), 100)
        self.assertFalse(out.endswith("|"))


class BuildMetadataTitleTests(unittest.TestCase):
    def test_llm_title_is_word_boundary_truncated(self):
        long_title = "에이전트 루나 (Agent Luna) - " + "아주 긴 제목 " * 12 + "Emotional Piano Solo"
        with patch.object(luna_engine.llm_client, "call_llm_json", return_value=({
            "youtube_title": long_title, "youtube_description": "d", "pinned_comment": "p"
        }, "raw")):
            meta = luna_engine.build_luna_metadata({"title": "X", "genre": "Emotional Piano Solo", "mood": "rainy"})
        self.assertLessEqual(len(meta["youtube_title"]), 100)
        self.assertFalse(meta["youtube_title"].endswith("Pi"))
        self.assertTrue(meta["shorts"]["youtube_title"].endswith("#Shorts"))

    def test_fallback_title_is_word_boundary_truncated(self):
        with patch.object(luna_engine.llm_client, "call_llm_json", side_effect=RuntimeError("down")):
            meta = luna_engine.build_luna_metadata({"title": "T" * 80, "genre": "Emotional Piano Solo", "mood": "비 오는 창가 (Rainy Window)"})
        self.assertLessEqual(len(meta["youtube_title"]), 100)


if __name__ == "__main__":
    unittest.main()
