"""Shiji Files v3 고정 틀 — 6씬 순서·원문 근거 통찰·질문 마무리를 린트와 발행 잠금으로 강제 (2026-10-27 사용자 지시: 이후 시리즈도 변경 금지)."""

import unittest

import concept_packs
import scene_store
import shorts_engine
import shorts_review

try:   # unittest discover -s tests 로 돌 때는 같은 모듈을 다시 import 하지 않도록 최상위 이름을 먼저 쓴다
    from test_shorts_engine import ShortsS2Base
except ImportError:
    from tests.test_shorts_engine import ShortsS2Base


def v3_scenes():
    return [
        {"scene_num": 1, "kind": "image", "seconds": 5, "narration": "He wrote the manual on surviving kings."},
        {"scene_num": 2, "kind": "map", "seconds": 6, "states": ["han", "qin"], "narration": "Han Fei was a prince of tiny Han."},
        {"scene_num": 3, "kind": "image", "seconds": 7, "narration": "His classmate Li Si sent him poison."},
        {"scene_num": 4, "kind": "seal", "seconds": 7, "hanzi": "人主亦有逆鱗", "translation": "Rulers too have reversed scales.",
         "source": "Shiji (c. 94 BC), ch. 63", "narration": "He had warned: rulers too have reversed scales."},
        {"scene_num": 5, "kind": "image", "seconds": 7, "grounding": "說之難在知所說之心", "grounding_source": "Han Feizi, ch. 12",
         "narration": "His lesson: persuasion fails not on facts, but on not knowing the mind of the one you persuade."},
        {"scene_num": 6, "kind": "image", "seconds": 6, "narration": "So whose reversed scale have you touched?"},
    ]


def v3_job(scenes=None):
    return {"shorts_id": "shorts_v3_1", "concept_key": "shorts_shiji", "format_version": 3,
            "storyboard": {"hook_text": "He wrote the manual", "scenes": scenes or v3_scenes(),
                           "end_tag": {"text": "Follow for the next story", "subtext": "", "seconds": 2.4}},
            "captions": []}


def codes(findings, level=None):
    return [f["code"] for f in findings if level is None or f["level"] == level]


class PackTests(unittest.TestCase):
    def test_shiji_pack_is_v3(self):
        spec = concept_packs.shorts_spec("shorts_shiji")
        self.assertEqual(spec["format_version"], 3)
        self.assertEqual((spec["min_scenes"], spec["max_scenes"]), (6, 6))
        self.assertEqual(len(spec["beats"]), 6)
        self.assertIn("seal", spec["beats"][3].lower())
        for f in ("grounding", "grounding_source"):
            self.assertIn(f, spec["scene_kind_fields"])
        # 범용 쇼츠는 그대로
        self.assertNotIn("format_version", concept_packs.shorts_spec("shorts_info"))

    def test_field_lists_stay_in_sync(self):
        self.assertEqual(set(scene_store.SHORTS_KIND_FIELDS), set(shorts_engine.SCENE_KIND_FIELDS))
        self.assertIn("grounding", shorts_engine.SCENE_KIND_FIELDS)


class V3LintTests(unittest.TestCase):
    def test_valid_v3_has_no_v3_findings(self):
        res = shorts_review.lint_storyboard(v3_job())
        self.assertFalse([c for c in codes(res["findings"]) if c.startswith("v3_")], res["findings"])

    def test_scene_count(self):
        res = shorts_review.lint_storyboard(v3_job(v3_scenes()[:5]))
        self.assertIn("v3_scene_count", codes(res["findings"], "P0"))

    def test_seal_must_be_fourth(self):
        sc = v3_scenes()
        sc[2], sc[3] = sc[3], sc[2]
        res = shorts_review.lint_storyboard(v3_job(sc))
        self.assertIn("v3_seal_position", codes(res["findings"], "P0"))

    def test_insight_needs_grounding_and_source(self):
        for drop in ("grounding", "grounding_source"):
            sc = v3_scenes()
            sc[4].pop(drop)
            res = shorts_review.lint_storyboard(v3_job(sc))
            self.assertIn("v3_insight_grounding", codes(res["findings"], "P0"), drop)

    def test_last_scene_must_ask(self):
        sc = v3_scenes()
        sc[5]["narration"] = "That is how power works."
        res = shorts_review.lint_storyboard(v3_job(sc))
        self.assertIn("v3_question", codes(res["findings"], "P0"))
        sc[5]["narration"] = 'Would you have said it? "'   # 닫는 따옴표가 붙어도 물음으로 본다
        res = shorts_review.lint_storyboard(v3_job(sc))
        self.assertNotIn("v3_question", codes(res["findings"]))

    def test_pre_v3_jobs_not_checked(self):
        job = v3_job(v3_scenes()[:4])
        job.pop("format_version")
        res = shorts_review.lint_storyboard(job)
        self.assertFalse([c for c in codes(res["findings"]) if c.startswith("v3_")])

    def test_render_review_locks_publish(self):
        sc = v3_scenes()
        sc[4].pop("grounding")
        job = v3_job(sc)
        review = shorts_review.review_render(job, None, "/nonexistent", "/u")
        self.assertTrue(review["needs_review"])
        job.update(review=review, qc={"passed": True}, status="qc_passed")
        ok, why = shorts_engine.publish_allowed(job)
        self.assertFalse(ok)


class V3PlanToJobTests(ShortsS2Base):
    def test_job_stamped_and_grounding_passes_through(self):
        batch = {"topic": "Han Fei", "recommended_title": "He Wrote the Manual", "aspect_ratio": "9:16", "concept_key": "shorts_shiji",
                 "scenes": [dict(s, prompt_en="p") for s in v3_scenes()]}
        plan = scene_store.build_plan(batch, scene_seconds=7.0)
        scene_store.save_plan(plan)
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        self.assertEqual(job["format_version"], 3)
        s5 = job["storyboard"]["scenes"][4]
        self.assertEqual((s5["grounding"], s5["grounding_source"]), ("說之難在知所說之心", "Han Feizi, ch. 12"))
        self.assertFalse([c for c in codes(job["lint"]["findings"]) if c.startswith("v3_")])

    def test_generic_job_not_stamped(self):
        plan = self.save_plan(n=4)
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        self.assertNotIn("format_version", job)

    def test_storyboard_edit_grounding(self):
        job = v3_job()
        __import__("os").makedirs(shorts_engine.job_dir("shorts_v3_1", create=True), exist_ok=True)
        job = shorts_engine.update_storyboard(job, scenes=[{"scene_num": 5, "grounding": " 說之難 ", "grounding_source": "Han Feizi, ch. 12"}])
        self.assertEqual(job["storyboard"]["scenes"][4]["grounding"], "說之難")


if __name__ == "__main__":
    unittest.main()
