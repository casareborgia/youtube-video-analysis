"""P-3 원문 인장(seal)·전국시대 지도(map) 씬 (작업계획서_ShijiFiles_파일럿3편 4장 P-3)."""

import os
import re
import unittest

import concept_packs
import shorts_engine
import shorts_review

try:   # unittest discover -s tests 로 돌 때는 같은 모듈을 다시 import 하지 않도록 최상위 이름을 먼저 쓴다
    from test_shorts_engine import ShortsS2Base
except ImportError:
    from tests.test_shorts_engine import ShortsS2Base

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TSX = os.path.join(BASE, "remotion", "src", "ShortsScene.tsx")
MAP_TS = os.path.join(BASE, "remotion", "src", "warringStatesMap.ts")

SEAL = {"kind": "seal", "seconds": 6.0, "hanzi": "此奇貨可居", "translation": "This is rare goods, worth hoarding.",
        "source": "Shiji, ch. 85", "narration": "He looked at the prince and said: this is rare goods, worth hoarding."}
MAP = {"kind": "map", "seconds": 5.0, "states": ["qin", "zhao"], "arrows": [{"from": "qin", "to": "zhao"}],
       "narration": "Qin marched east toward Zhao."}


def _job(scenes):
    return {"storyboard": {"hook_text": "A merchant bought an empire", "hook_seconds": 3.0,
                           "scenes": [dict({"scene_num": i + 1}, **s) for i, s in enumerate(scenes)],
                           "end_tag": {"text": "Follow for part 2", "subtext": "", "seconds": 2.5}},
            "captions": []}


def _codes(findings, level=None):
    return [f["code"] for f in findings if level is None or f["level"] == level]


class KindRegistryTests(unittest.TestCase):
    def test_engine_and_shiji_pack_list_new_kinds(self):
        for k in ("seal", "map"):
            self.assertIn(k, shorts_engine.SCENE_KINDS)
        spec = concept_packs.shorts_spec("shorts_shiji")
        self.assertEqual(tuple(spec["scene_kinds"]), shorts_engine.SCENE_KINDS)
        for f in ("hanzi", "translation", "source", "states", "arrows", "year"):
            self.assertIn(f, spec["scene_kind_fields"])
        self.assertIn("seal", spec["kind_guide"])

    def test_generic_shorts_pack_unchanged(self):
        # 범용 쇼츠 기획(AI 트렌드 등)에는 고전 원문·지도 선택지를 내보내지 않는다
        spec = concept_packs.shorts_spec("shorts_info")
        self.assertNotIn("seal", spec["scene_kinds"])
        self.assertNotIn("map", spec["kind_guide"])
        self.assertTrue(set(spec["scene_kinds"]) <= set(shorts_engine.SCENE_KINDS))
        self.assertTrue(concept_packs.is_shorts_pack("shorts_shiji"))

    def test_remotion_kind_union_matches_engine(self):
        src = open(TSX, encoding="utf-8").read()
        m = re.search(r"export type ShortsSceneKind = ([^;]+);", src)
        self.assertEqual(set(re.findall(r'"(\w+)"', m.group(1))), set(shorts_engine.SCENE_KINDS))

    def test_map_state_ids_match_remotion_map(self):
        ids = re.findall(r'id: "(\w+)"', open(MAP_TS, encoding="utf-8").read())
        self.assertEqual(sorted(ids), sorted(shorts_engine.MAP_STATES))
        self.assertEqual(len(shorts_engine.MAP_STATES), 7)


SHIJI_SPEC = concept_packs.shorts_spec("shorts_shiji")


class PlanStoreTests(ShortsS2Base):
    def test_plan_keeps_seal_and_map_fields_and_job_gets_them(self):
        import scene_store
        self.assertEqual(set(scene_store.SHORTS_KIND_FIELDS), set(shorts_engine.SCENE_KIND_FIELDS))
        batch = {"topic": "Sun Tzu", "recommended_title": "Sun Tzu's Job Interview", "aspect_ratio": "9:16",
                 "concept_key": "shorts_shiji",
                 "scenes": [dict(MAP, scene_num=1, prompt_en="p", year="c. 260 BC"),
                            dict(SEAL, scene_num=2, prompt_en="p")]}
        plan = scene_store.build_plan(batch, scene_seconds=5.0)
        scene_store.save_plan(plan)
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        mp, seal = job["storyboard"]["scenes"]
        self.assertEqual((seal["kind"], seal["hanzi"], seal["source"]), ("seal", "此奇貨可居", "Shiji, ch. 85"))
        self.assertEqual((mp["kind"], mp["states"], mp["arrows"]), ("map", ["qin", "zhao"], [{"from": "qin", "to": "zhao"}]))


class FillDefaultsTests(unittest.TestCase):
    def test_generic_pack_turns_seal_into_image(self):
        self.assertEqual(shorts_engine.fill_kind_defaults(dict(SEAL))["kind"], "image")

    def test_seal_kept_and_trimmed(self):
        s = shorts_engine.fill_kind_defaults(dict(SEAL, hanzi="  此奇貨可居 ", translation="x" * 300, source=" Shiji, ch. 85 "), SHIJI_SPEC)
        self.assertEqual(s["kind"], "seal")
        self.assertEqual(s["hanzi"], "此奇貨可居")
        self.assertEqual(s["source"], "Shiji, ch. 85")
        self.assertLessEqual(len(s["translation"]), shorts_engine.SEAL_TRANSLATION_MAX)

    def test_seal_without_hanzi_falls_back_to_text_card(self):
        s = shorts_engine.fill_kind_defaults({"kind": "seal", "narration": "No quote here at all", "scene_num": 2}, SHIJI_SPEC)
        self.assertEqual(s["kind"], "text_card")
        self.assertIn("seal", s["kind_note"])

    def test_seal_without_source_stays_seal(self):
        # 출전이 없어도 조용히 바꾸지 않는다 — 린트가 P0 로 막는다
        s = shorts_engine.fill_kind_defaults(dict(SEAL, source=""), SHIJI_SPEC)
        self.assertEqual(s["kind"], "seal")

    def test_map_filters_unknown_states_and_arrows(self):
        s = shorts_engine.fill_kind_defaults({"kind": "map", "states": ["qin", "rome", "QI"],
                                              "arrows": [{"from": "qin", "to": "qi"}, {"from": "qin", "to": "qin"},
                                                         {"from": "x", "to": "chu"}, "bad"]}, SHIJI_SPEC)
        self.assertEqual(s["kind"], "map")
        self.assertEqual(s["states"], ["qin", "qi"])
        self.assertEqual(s["arrows"], [{"from": "qin", "to": "qi"}])
        self.assertEqual(s["year"], "c. 260 BC")

    def test_map_keeps_given_year(self):
        s = shorts_engine.fill_kind_defaults(dict(MAP, year="221 BC"), SHIJI_SPEC)
        self.assertEqual(s["year"], "221 BC")


class PropsTests(ShortsS2Base):
    def test_props_pass_seal_and_map_fields(self):
        job = {"shorts_id": "shorts_seal_1", "storyboard": {"scenes": [dict(SEAL, scene_num=1), dict(MAP, scene_num=2, year="c. 260 BC")]},
               "captions": [], "audio": {}}
        props = shorts_engine.build_remotion_props(job)
        seal, mp = props["scenes"]
        self.assertEqual((seal["kind"], seal["hanzi"], seal["source"]), ("seal", "此奇貨可居", "Shiji, ch. 85"))
        self.assertEqual(seal["translation"], SEAL["translation"])
        self.assertEqual((mp["kind"], mp["states"], mp["arrows"], mp["year"]),
                         ("map", ["qin", "zhao"], [{"from": "qin", "to": "zhao"}], "c. 260 BC"))
        self.assertNotIn("image", seal)


class SealLintTests(unittest.TestCase):
    def test_valid_seal_has_no_seal_findings(self):
        res = shorts_review.lint_storyboard(_job([SEAL]))
        self.assertFalse([c for c in _codes(res["findings"]) if c.startswith("seal_")])

    def test_missing_source_is_p0(self):
        res = shorts_review.lint_storyboard(_job([dict(SEAL, source="")]))
        self.assertIn("seal_no_source", _codes(res["findings"], "P0"))

    def test_glyph_missing_from_font_is_p0(self):
        res = shorts_review.lint_storyboard(_job([dict(SEAL, hanzi="逺方之人")]))   # 逺 은 인장 글꼴에 없다
        p0 = [f for f in res["findings"] if f["code"] == "seal_missing_glyph"]
        self.assertEqual(len(p0), 1)
        self.assertEqual(p0[0]["level"], "P0")
        self.assertIn("逺", p0[0]["message"])

    def test_long_quote_is_p1(self):
        res = shorts_review.lint_storyboard(_job([dict(SEAL, hanzi="臣既已受命為將將在軍君命有所不受")]))
        self.assertIn("seal_too_long", _codes(res["findings"], "P1"))

    def test_punctuation_not_counted_or_glyph_checked(self):
        res = shorts_review.lint_storyboard(_job([dict(SEAL, hanzi="將在軍，君命有所不受。")]))
        self.assertFalse([c for c in _codes(res["findings"]) if c.startswith("seal_")])

    def test_render_review_blocks_publish_on_seal_p0(self):
        job = _job([dict(SEAL, source="")])
        review = shorts_review.review_render(job, None, "/nonexistent", "/u")
        self.assertTrue(review["needs_review"])
        self.assertIn("seal_no_source", _codes(review["findings"], "P0"))
        job.update(review=review, qc={"passed": True}, status="qc_passed")
        ok, why = shorts_engine.publish_allowed(job)
        self.assertFalse(ok)
        self.assertIn("P0", why)

    def test_seal_and_map_count_as_text_kinds_and_animate(self):
        self.assertIn("seal", shorts_review.TEXT_KINDS)
        self.assertIn("map", shorts_review.TEXT_KINDS)
        self.assertGreater(shorts_review._anim_end_seconds(SEAL), 0.5)
        self.assertGreater(shorts_review._anim_end_seconds(MAP), 0.5)

    def test_screen_texts(self):
        self.assertEqual(shorts_review._screen_texts(SEAL), [SEAL["translation"], "Shiji, ch. 85"])
        self.assertEqual(shorts_review._screen_texts(dict(MAP, year="c. 260 BC")), ["c. 260 BC"])


class StoryboardEditTests(ShortsS2Base):
    def test_ui_edits_seal_fields(self):
        job = {"shorts_id": "shorts_seal_2", "storyboard": {"scenes": [dict(SEAL, scene_num=1)]}, "captions": []}
        os.makedirs(shorts_engine.job_dir("shorts_seal_2", create=True), exist_ok=True)
        job = shorts_engine.update_storyboard(job, scenes=[{"scene_num": 1, "hanzi": " 遂斬隊長二人以徇 ",
                                                            "translation": "He beheaded the two captains.", "source": "Shiji, ch. 65"}])
        s = job["storyboard"]["scenes"][0]
        self.assertEqual((s["hanzi"], s["translation"], s["source"]), ("遂斬隊長二人以徇", "He beheaded the two captains.", "Shiji, ch. 65"))


if __name__ == "__main__":
    unittest.main()
