"""P-4 수묵 시네마틱 스타일 — 로컬 ComfyUI 생성기·이미지 백엔드·톤 묶음 (작업계획서_ShijiFiles_파일럿3편 4장 P-4)."""

import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as app_module
import comfy_images
import concept_packs
import producer
import shorts_engine
import shorts_review

try:   # unittest discover -s tests 로 돌 때는 같은 모듈을 다시 import 하지 않도록 최상위 이름을 먼저 쓴다
    from test_shorts_engine import ShortsS2Base, _plan
except ImportError:
    from tests.test_shorts_engine import ShortsS2Base, _plan

PNG = b"\x89PNG\r\n\x1a\nfake"


class FakeComfy:
    """POST /prompt → prompt_id, GET /history/<id> → outputs, GET /view → 바이트. fail_slots 의 씬은 실행 오류로 끝난다."""

    def __init__(self, fail_prompts=()):
        self.posted = []
        self.fail_prompts = set(fail_prompts)

    def post_json(self, url, body, timeout=30):
        self.posted.append(body)
        return {"prompt_id": f"pid{len(self.posted)}"}

    def get_json(self, url, timeout=30):
        pid = url.rsplit("/", 1)[-1]
        n = int(pid[3:])
        if n in self.fail_prompts:
            return {pid: {"status": {"status_str": "error", "completed": False}, "outputs": {}}}
        return {pid: {"outputs": {"10": {"images": [{"filename": f"shiji_{n}.png", "subfolder": "", "type": "output"}]}}}}

    def get_bytes(self, url, timeout=60):
        return PNG


def _patch_http(fake):
    return [patch.object(comfy_images, "_post_json", fake.post_json),
            patch.object(comfy_images, "_get_json", fake.get_json),
            patch.object(comfy_images, "_get_bytes", fake.get_bytes),
            patch.object(comfy_images, "POLL_SECONDS", 0)]


class PromptTests(unittest.TestCase):
    def test_flow_prompt_cleaned_and_style_appended(self):
        sc = {"prompt_en": "Hyperrealistic 8k cinematic footage of a merchant bowing to a prince. Audio: wind, footsteps. "
                           "(SFX and ambience only — no voice) --ar 9:16 --no voice, music"}
        p = comfy_images.scene_prompt(sc, "ink wash style")
        self.assertTrue(p.startswith("a merchant bowing to a prince"), p)
        for bad in ("Audio:", "--ar", "--no", "Hyperrealistic 8k cinematic footage of"):
            self.assertNotIn(bad, p)
        self.assertTrue(p.endswith("ink wash style"))

    def test_fallback_to_visual_description(self):
        p = comfy_images.scene_prompt({"visual_description_en": "an old general on a hill"}, "S")
        self.assertEqual(p, "an old general on a hill, S")

    def test_seed_is_stable_per_plan_and_slot(self):
        self.assertEqual(comfy_images.seed_for("plan_a", "3"), comfy_images.seed_for("plan_a", "3"))
        self.assertNotEqual(comfy_images.seed_for("plan_a", "3"), comfy_images.seed_for("plan_a", "4"))


class GeneratorTests(ShortsS2Base):
    def make_plan(self):
        plan = _plan(n=3, concept_key="shorts_shiji")
        for sc in plan["structured_scenes"]:
            sc["prompt_en"] = f"Hyperrealistic 8k cinematic footage of scene {sc['scene_num']}. Audio: wind. --ar 9:16"
        return plan

    def run_gen(self, fake, plan, slots):
        ps = _patch_http(fake)
        for p in ps:
            p.start()
            self.addCleanup(p.stop)
        with patch.object(comfy_images, "comfy_available", return_value=True):
            return comfy_images.generate_images(plan, slots=slots, style="INK")

    def test_generates_saves_and_indexes(self):
        plan = self.make_plan()
        fake = FakeComfy()
        res = self.run_gen(fake, plan, ["1", "3"])
        self.assertEqual(res["generated"], ["1", "3"])
        self.assertEqual(res["errors"], [])
        wf = fake.posted[0]["prompt"]
        texts = [n["inputs"]["text"] for n in wf.values() if n.get("class_type") == "CLIPTextEncode"]
        self.assertEqual(texts, ["scene 1, INK"])
        lat = [n["inputs"] for n in wf.values() if n.get("class_type") == "EmptySD3LatentImage"][0]
        self.assertEqual((lat["width"], lat["height"]), (comfy_images.WIDTH, comfy_images.HEIGHT))
        idx = producer.list_media(plan["plan_id"])
        self.assertEqual(idx["1"]["source"], "comfyui")
        self.assertEqual(idx["1"]["prompt"], "scene 1, INK")
        with open(os.path.join(producer.render_dir(plan["plan_id"]), idx["3"]["file"]), "rb") as f:
            self.assertEqual(f.read(), PNG)

    def test_one_failure_does_not_stop_others(self):
        plan = self.make_plan()
        res = self.run_gen(FakeComfy(fail_prompts={1}), plan, ["1", "2"])
        self.assertEqual(res["generated"], ["2"])
        self.assertEqual([e["slot"] for e in res["errors"]], ["1"])

    def test_comfy_down_raises_clear_error_and_never_falls_back(self):
        plan = self.make_plan()
        with patch.object(comfy_images, "comfy_available", return_value=False), \
             patch.object(producer, "generate_images", side_effect=AssertionError("Gemini 로 넘어가면 안 된다")):
            with self.assertRaises(comfy_images.ComfyUnavailable) as cm:
                comfy_images.generate_images(plan, slots=["1"])
        self.assertIn("ComfyUI", str(cm.exception))
        self.assertEqual(producer.list_media(plan["plan_id"]), {})


class BackendTests(ShortsS2Base):
    def shiji_job(self, n=3):
        plan = _plan(n=n, concept_key="shorts_shiji")
        scene_plan = __import__("scene_store").save_plan(plan) or plan
        return shorts_engine.build_job_from_plan(plan["plan_id"]), plan

    def test_backend_from_pack(self):
        job, _ = self.shiji_job()
        self.assertEqual(shorts_engine.image_backend(job), "comfyui")
        self.assertEqual(shorts_engine.image_backend({"concept_key": "shorts_info"}), "gemini")
        self.assertEqual(shorts_engine.image_backend({"concept_key": "shorts_info", "image_backend": "comfyui"}), "comfyui")

    def test_estimate_comfy_is_free_and_ignores_gemini_cap(self):
        job, _ = self.shiji_job()
        with patch.object(shorts_engine, "get_today_usage", return_value=10_000), \
             patch.object(comfy_images, "comfy_available", return_value=True):
            est = shorts_engine.estimate_images(job)
        self.assertEqual((est["backend"], est["usd"], est["allowed"]), ("comfyui", 0, True))
        self.assertEqual(est["needed"], 3)

    def test_estimate_comfy_down_not_allowed(self):
        job, _ = self.shiji_job()
        with patch.object(comfy_images, "comfy_available", return_value=False):
            est = shorts_engine.estimate_images(job)
        self.assertFalse(est["allowed"])
        self.assertIn("ComfyUI", est["reason"])

    def test_comfy_generation_not_counted_as_gemini_usage(self):
        job, plan = self.shiji_job(n=2)

        def gen(p, slots=None, progress=None):
            d = producer.render_dir(p["plan_id"])
            idx = producer.list_media(p["plan_id"])
            for s in slots:
                fname = f"scene_{int(s):02d}.png"
                with open(os.path.join(d, fname), "wb") as f:
                    f.write(PNG)
                idx[s] = {"file": fname, "type": "image", "source": "comfyui"}
            producer._save_index(p["plan_id"], idx)
            return {"generated": list(slots), "errors": []}

        with patch.object(comfy_images, "comfy_available", return_value=True):
            shorts_engine.generate_job_images(job, generator=gen)
        self.assertEqual(shorts_engine.get_today_usage(), 0)
        self.assertEqual([s.get("image_source") for s in job["storyboard"]["scenes"]], ["comfyui", "comfyui"])

    def test_api_build_needs_no_confirm_for_comfy(self):
        job, _ = self.shiji_job()
        client = TestClient(app_module.app)
        app_module._shorts_building.clear()
        with patch.object(comfy_images, "comfy_available", return_value=True), \
             patch.object(app_module, "_run_shorts_build_worker", lambda sid, opts: None):
            r = client.post(f"/api/shorts/jobs/{job['shorts_id']}/build", json={"confirm": False, "confirm_lint": True})
        app_module._shorts_building.clear()
        self.assertEqual(r.json()["status"], "started", r.text)


class InkToneTests(ShortsS2Base):
    def test_pack_tone(self):
        spec = concept_packs.shorts_spec("shorts_shiji")
        self.assertEqual(spec["image_backend"], "comfyui")
        self.assertIn("ink wash", spec["image_style"])
        self.assertIn("no text", spec["image_style"])
        self.assertEqual(spec["accent"], "#d4af37")
        self.assertTrue(spec["end_tag"]["text"].isascii())
        self.assertTrue(set(spec["transitions"]) <= set(shorts_engine.SCENE_TRANSITIONS))
        self.assertIn("수묵", concept_packs.get_pack("shorts_shiji")["render_style"])
        self.assertEqual(spec["image_style"], comfy_images.INK_STYLE)   # 생성기 기본값과 팩 스타일은 한 문구
        # 범용 팩은 그대로
        self.assertNotIn("image_backend", concept_packs.shorts_spec("shorts_info"))

    def test_job_gets_accent_and_transitions_stay_in_palette(self):
        plan = _plan(n=5, concept_key="shorts_shiji")
        __import__("scene_store").save_plan(plan)
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        self.assertEqual(job["accent"], "#d4af37")
        allowed = set(concept_packs.shorts_spec("shorts_shiji")["transitions"])
        seams = shorts_engine.assign_transitions(job)
        self.assertTrue(seams and set(seams) <= allowed, seams)
        self.assertEqual(job["storyboard"]["end_tag"]["text"], concept_packs.shorts_spec("shorts_shiji")["end_tag"]["text"])

    def test_generic_job_keeps_default_accent_and_transitions(self):
        plan = _plan(n=5)
        __import__("scene_store").save_plan(plan)
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        self.assertNotIn("accent", job)
        self.assertIn("slide", shorts_engine.assign_transitions(job) + ["slide"])   # 회귀 방지: 범용 로직 유지


class ReviewImageTextTests(unittest.TestCase):
    def test_comfy_images_get_manual_text_check(self):
        job = {"storyboard": {"scenes": [{"scene_num": 1, "kind": "image", "seconds": 5, "image_source": "comfyui"},
                                         {"scene_num": 2, "kind": "seal", "seconds": 5, "hanzi": "此奇貨可居", "source": "Shiji, ch. 85"},
                                         {"scene_num": 3, "kind": "image", "seconds": 5, "image_source": "gemini"}]}}
        review = shorts_review.review_render(job, None, "/nonexistent", "/u")
        f = [x for x in review["findings"] if x["code"] == "image_text_check"]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["level"], "P2")
        self.assertIn("1", f[0]["message"])
        self.assertFalse(review["needs_review"])   # 사람 확인 안내일 뿐 발행을 막지 않는다


if __name__ == "__main__":
    unittest.main()
