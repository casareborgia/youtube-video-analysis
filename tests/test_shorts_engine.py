"""쇼츠 엔진 S-2 단위 테스트 — 잡 생성·60초 컷·edge-tts WordBoundary 파싱(모킹)·비례 분배 폴백·QC·일일 상한·API 라우트.
Node·ffmpeg·네트워크 없이 통과한다 (subprocess·edge_tts·Gemini 는 전부 모킹)."""

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import app as app_module
import concept_packs
import producer
import scene_store
import shorts_engine
import tts_service


def _plan(aspect="9:16", n=5, seconds=8.0, topic="전기차 배터리의 진실", **extra):
    batch = {
        "topic": topic,
        "recommended_title": "아무도 몰랐던 전기차 배터리",
        "aspect_ratio": aspect,
        "concept_key": "shorts_info",
        "seo_description": "배터리 수명의 진실을 1분에 정리합니다.",
        "engagement_question": "여러분은 어느 쪽인가요?",
        "pinned_comment": "📌 끝까지 봐주셔서 감사합니다!",
        "scenes": [
            {"scene_num": i, "seconds": seconds, "narration": f"{i}번째 핵심 내용입니다. 배터리는 생각보다 오래 갑니다.",
             "dramatic_beat": f"비트 {i}", "visual_description_ko": f"비주얼 {i}", "prompt_en": "p"}
            for i in range(1, n + 1)
        ],
    }
    batch.update(extra)
    plan = scene_store.build_plan(batch, scene_seconds=seconds)
    return plan


class ShortsS2Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        dirs = {
            (shorts_engine, "SHORTS_DIR"): os.path.join(self.tmp, "shorts"),
            (shorts_engine, "REMOTION_DIR"): os.path.join(self.tmp, "remotion"),
            (shorts_engine, "SHORTS_USAGE_FILE"): os.path.join(self.tmp, "shorts_usage.json"),
            (scene_store, "SCENES_DIR"): os.path.join(self.tmp, "scene_plans"),
            (producer, "RENDERS_DIR"): os.path.join(self.tmp, "renders"),
        }
        for (mod, name), val in dirs.items():
            if name.endswith("DIR"):
                os.makedirs(val, exist_ok=True)
            p = patch.object(mod, name, val)
            p.start()
            self.addCleanup(p.stop)
        # ffmpeg 없는 환경으로 고정 — 패딩·밝기·loudnorm 은 건너뛰고 테스트가 직접 값을 주입한다
        p = patch.object(producer, "ffmpeg_path", lambda: None)
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(producer, "audio_duration", lambda path: None)
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(shorts_engine, "measure_loudness", lambda path: None)
        p.start()
        self.addCleanup(p.stop)
        # U-3 강조어: 테스트에서는 LLM 을 부르지 않는다(숫자 어절 폴백만)
        p = patch.object(shorts_engine, "_llm_emphasis", lambda narrations: [])
        p.start()
        self.addCleanup(p.stop)

    def save_plan(self, **kw):
        plan = _plan(**kw)
        scene_store.save_plan(plan)
        return plan

    def add_images(self, plan, nums):
        d = producer.render_dir(plan["plan_id"])
        idx = producer.list_media(plan["plan_id"])
        for n in nums:
            fname = f"scene_{n:02d}.png"
            with open(os.path.join(d, fname), "wb") as f:
                f.write(b"png")
            idx[str(n)] = {"file": fname, "type": "image", "source": "gemini"}
        producer._save_index(plan["plan_id"], idx)


# ── 1. 잡 생성 ───────────────────────────────────────────────────────────────

class BuildJobFromPlanTests(ShortsS2Base):
    def test_creates_job_json_with_schema(self):
        plan = self.save_plan(hook_text="이거 모르면 손해", end_tag_text="구독하고 다음 편")
        job = shorts_engine.build_job_from_plan(plan["plan_id"], platforms=["youtube_shorts"])
        self.assertTrue(job["shorts_id"].startswith("shorts_"))
        self.assertEqual(shorts_engine._safe_id(job["shorts_id"]), job["shorts_id"])
        self.assertEqual(job["format"], "scene")
        self.assertEqual(job["status"], "planned")
        self.assertEqual(job["source"]["plan_id"], plan["plan_id"])
        self.assertEqual(job["platforms"], ["youtube_shorts"])
        self.assertEqual(job["voice_id"], "edge_injoon")
        sb = job["storyboard"]
        self.assertEqual(sb["hook_text"], "이거 모르면 손해")
        self.assertEqual(sb["end_tag"]["text"], "구독하고 다음 편")
        self.assertEqual(sb["end_tag"]["seconds"], 2.0)
        self.assertEqual(len(sb["scenes"]), 5)
        self.assertEqual([s["motion"] for s in sb["scenes"]][:4], ["zoom_in", "zoom_out", "pan_left", "pan_right"])
        self.assertIsNone(sb["scenes"][0]["image"])
        self.assertIn("#Shorts", job["metadata"]["youtube"]["title"])
        self.assertEqual(job["metadata"]["youtube"]["pinned_comment"], "📌 끝까지 봐주셔서 감사합니다!")
        self.assertEqual(shorts_engine.total_seconds(job), 42.0)
        # 디스크에 저장됨
        loaded = shorts_engine.load_job(job["shorts_id"])
        self.assertEqual(loaded["storyboard"]["hook_text"], "이거 모르면 손해")
        self.assertEqual([j["shorts_id"] for j in shorts_engine.list_jobs()], [job["shorts_id"]])

    def test_hook_and_end_tag_defaults(self):
        plan = self.save_plan()
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        self.assertEqual(job["storyboard"]["hook_text"], "아무도 몰랐던 전기차 배터리")
        self.assertEqual(job["storyboard"]["end_tag"]["text"], "구독하고 다음 편 보기")

    def test_rejects_16x9_plan(self):
        plan = self.save_plan(aspect="16:9")
        with self.assertRaises(ValueError) as cm:
            shorts_engine.build_job_from_plan(plan["plan_id"])
        self.assertIn("9:16", str(cm.exception))

    def test_missing_plan_raises(self):
        with self.assertRaises(FileNotFoundError):
            shorts_engine.build_job_from_plan("scenes_1_none")

    def test_unknown_platform_rejected(self):
        plan = self.save_plan()
        with self.assertRaises(ValueError):
            shorts_engine.build_job_from_plan(plan["plan_id"], platforms=["tiktok"])

    def test_existing_plan_images_are_linked(self):
        plan = self.save_plan()
        self.add_images(plan, [1, 2])
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        scenes = job["storyboard"]["scenes"]
        self.assertTrue(scenes[0]["image"].endswith("scene_01.png"))
        self.assertTrue(scenes[1]["image"].endswith("scene_02.png"))
        self.assertIsNone(scenes[2]["image"])
        est = shorts_engine.estimate_images(job)
        self.assertEqual((est["needed"], est["reused"], est["scenes"]), (3, 2, [3, 4, 5]))

    def test_scene_cap_six(self):
        plan = self.save_plan(n=8, seconds=5.0)
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        self.assertEqual(len(job["storyboard"]["scenes"]), 6)
        self.assertTrue(any("앞 6개" in w for w in job["warnings"]))


class SceneKindTests(ShortsS2Base):
    """작업계획서 7b 씬 종류 — image 외에는 이미지 비용 0."""

    def test_kinds_and_fields_pass_through_and_defaults(self):
        batch_scenes = [
            {"scene_num": 1, "narration": "로봇이 스스로 연습합니다. 정말입니다.", "kind": "text_card", "subtitle": "Argon"},
            {"scene_num": 2, "narration": "ERQA 87퍼센트로 1위입니다.", "kind": "bar_chart", "title": "ERQA", "unit": "%",
             "bars": [{"label": "Argon", "value": 87, "highlight": True}, {"label": "Opus", "value": 82.3}]},
            {"scene_num": 3, "narration": "성공률이 56에서 75로 올랐습니다.", "kind": "compare", "rows": [{"label": "성공률", "from": 56, "to": 75, "unit": "%"}]},
            {"scene_num": 4, "narration": "자유도 18개입니다.", "kind": "stat_card", "value": "18", "unit": "자유도"},
            {"scene_num": 5, "narration": "히어로 장면입니다.", "kind": "image"},
            {"scene_num": 6, "narration": "모르는 종류는 이미지로.", "kind": "hologram"},
        ]
        plan = self.save_plan(n=1)
        plan = scene_store.build_plan({"topic": "t", "aspect_ratio": "9:16", "concept_key": "shorts_info", "scenes": batch_scenes})
        scene_store.save_plan(plan)
        self.assertEqual(plan["structured_scenes"][1]["bars"][0]["highlight"], True)
        self.assertNotIn("kind", scene_store.build_plan({"topic": "t", "scenes": [{"scene_num": 1, "narration": "n"}]})["structured_scenes"][0])
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        sc = job["storyboard"]["scenes"]
        self.assertEqual([x["kind"] for x in sc], ["text_card", "bar_chart", "compare", "stat_card", "image", "image"])
        self.assertEqual(sc[0]["title"], "로봇이 스스로 연습합니다. 정말입니다."[:17] + "…")   # 나레이션에서 제목 채움
        self.assertEqual(sc[0]["subtitle"], "Argon")
        self.assertEqual(sc[1]["bars"][1]["value"], 82.3)
        self.assertEqual(sc[2]["rows"][0]["to"], 75)
        self.assertEqual(sc[3]["value"], 18.0)
        self.assertEqual(sc[3]["label"], "자유도 18개입니다.")
        est = shorts_engine.estimate_images(job)
        self.assertEqual((est["needed"], est["scenes"], est["cost_free"], est["reused"]), (2, [5, 6], 4, 0))
        self.assertEqual(round(est["usd"], 3), round(2 * shorts_engine.IMAGE_USD_PER_IMAGE, 3))

    def test_flyover_kind_defaults(self):
        out = shorts_engine.fill_kind_defaults({"kind": "flyover", "scene_num": 3, "narration": "남강을 따라 진주성으로 날아갑니다."})
        self.assertEqual(out["kind"], "flyover")
        self.assertEqual(out["time_of_day"], "sunset")          # 기본 노을
        self.assertEqual(out["seed"], 3)                         # 씬 번호로 지형이 달라진다
        self.assertNotIn("title", out)                           # 지명 라벨은 선택
        out = shorts_engine.fill_kind_defaults({"kind": "flyover", "scene_num": 1, "narration": "n", "time_of_day": "midnight",
                                                "seed": "x", "title": "경상남도 진주시 남강 촉석루 일대"})
        self.assertEqual(out["time_of_day"], "sunset")          # 모르는 시간대는 기본값
        self.assertEqual(out["seed"], 1)
        self.assertEqual(out["title"], "경상남도 진주시 남강…")   # 12자로 줄임
        out = shorts_engine.fill_kind_defaults({"kind": "flyover", "scene_num": 2, "narration": "n", "time_of_day": "day", "seed": 7})
        self.assertEqual((out["time_of_day"], out["seed"]), ("day", 7))

    def test_flyover_is_cost_free_and_known_to_planner(self):
        spec = concept_packs.shorts_spec("shorts_info")
        self.assertIn("flyover", spec["scene_kinds"])
        self.assertIn("flyover", spec["kind_guide"])
        self.assertIn("time_of_day", spec["scene_kind_fields"])
        self.assertIn("flyover", shorts_engine.SCENE_KINDS)
        plan = scene_store.build_plan({"topic": "진주 여행", "aspect_ratio": "9:16", "concept_key": "shorts_info", "scenes": [
            {"scene_num": 1, "narration": "진주 남강 위를 날아 봅니다.", "kind": "flyover", "time_of_day": "sunrise", "title": "진주 남강"},
            {"scene_num": 2, "narration": "히어로 장면입니다.", "kind": "image"}]})
        scene_store.save_plan(plan)
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        fly = job["storyboard"]["scenes"][0]
        self.assertEqual((fly["kind"], fly["time_of_day"], fly["title"]), ("flyover", "sunrise", "진주 남강"))
        est = shorts_engine.estimate_images(job)
        self.assertEqual((est["needed"], est["cost_free"]), (1, 1))   # flyover 는 이미지 비용 0

    def test_scene3d_kind_is_normalized_and_cost_free(self):
        out = shorts_engine.fill_kind_defaults({"kind": "scene3d", "scene_num": 4, "narration": "n",
                                                "scene3d": {"environment": "space", "objects": [{"type": "globe"}, {"type": "dragon"}]}})
        self.assertEqual(out["kind"], "scene3d")
        self.assertEqual(out["scene3d"]["environment"], "space")
        self.assertEqual([o["type"] for o in out["scene3d"]["objects"]], ["globe"])
        self.assertEqual(out["scene3d"]["seed"], 4)
        out = shorts_engine.fill_kind_defaults({"kind": "scene3d", "scene_num": 1, "narration": "n"})
        self.assertEqual(out["scene3d"]["environment"], "studio")   # 설명이 없어도 그릴 수 있는 기본 장면
        spec = concept_packs.shorts_spec("shorts_info")
        self.assertIn("scene3d", spec["scene_kinds"])
        self.assertIn("scene3d", spec["kind_guide"])
        self.assertIn("scene3d", spec["scene_kind_fields"])
        plan = scene_store.build_plan({"topic": "세계 AI 지도", "aspect_ratio": "9:16", "concept_key": "shorts_info", "scenes": [
            {"scene_num": 1, "narration": "세계 곳곳에서 AI 가 자랍니다.", "kind": "scene3d",
             "scene3d": {"environment": "space", "objects": [{"type": "globe", "pins": [{"lat": 37.5, "lon": 127, "label": "서울"}]}]}}]})
        scene_store.save_plan(plan)
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        sc = job["storyboard"]["scenes"][0]
        self.assertEqual(sc["scene3d"]["objects"][0]["pins"][0]["label"], "서울")
        self.assertEqual(shorts_engine.estimate_images(job)["needed"], 0)

    def test_incomplete_kinds_downgrade_to_text_card(self):
        for scene, expect_note in (
            ({"kind": "stat_card", "narration": "값이 없다"}, "value"),
            ({"kind": "bar_chart", "narration": "막대 하나", "bars": [{"label": "A", "value": 1}]}, "막대"),
            ({"kind": "compare", "narration": "행 없음", "rows": [{"label": "x"}]}, "전→후"),
        ):
            out = shorts_engine.fill_kind_defaults(dict(scene))
            self.assertEqual(out["kind"], "text_card", scene)
            self.assertEqual(out["title"], scene["narration"])
            self.assertIn(expect_note, out["kind_note"])
        self.assertEqual(shorts_engine.fill_kind_defaults({"narration": "x"})["kind"], "image")

    def test_build_skips_image_generation_for_cost_free_scenes(self):
        plan = scene_store.build_plan({"topic": "t", "aspect_ratio": "9:16", "scenes": [
            {"scene_num": 1, "narration": "텍스트 카드 씬", "kind": "text_card", "title": "훅"},
            {"scene_num": 2, "narration": "숫자 카드 씬", "kind": "stat_card", "value": 87, "unit": "%"}]})
        scene_store.save_plan(plan)
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        self.assertEqual(shorts_engine.estimate_images(job)["needed"], 0)
        gen = MagicMock(side_effect=AssertionError("호출되면 안 됨"))
        res = shorts_engine.generate_job_images(job, generator=gen)
        self.assertEqual(res["generated"], [])
        self.assertEqual(shorts_engine.get_today_usage(), 0)

    def test_storyboard_kind_edit(self):
        plan = self.save_plan(n=2)
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        job = shorts_engine.update_storyboard(job, scenes=[{"scene_num": 1, "kind": "text_card", "title": "새 제목", "subtitle": "부제"},
                                                          {"scene_num": 2, "kind": "stat_card"}])
        sc = job["storyboard"]["scenes"]
        self.assertEqual((sc[0]["kind"], sc[0]["title"], sc[0]["subtitle"]), ("text_card", "새 제목", "부제"))
        self.assertEqual(sc[1]["kind"], "text_card")      # value 없는 stat_card 는 text_card 로 내려감
        self.assertIn("value", sc[1]["kind_note"])
        self.assertEqual(shorts_engine.estimate_images(job)["needed"], 0)
        job = shorts_engine.update_storyboard(job, scenes=[{"scene_num": 1, "kind": "image"}])
        self.assertEqual(job["storyboard"]["scenes"][0]["kind"], "image")
        self.assertEqual(shorts_engine.estimate_images(job)["needed"], 1)


# ── 2. 60초 컷 ───────────────────────────────────────────────────────────────

class FitToMaxSecondsTests(ShortsS2Base):
    def test_over_60_cuts_from_last_scene_with_warning(self):
        plan = self.save_plan(n=6, seconds=12.0)          # 72 + 2 = 74초
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        self.assertLessEqual(shorts_engine.total_seconds(job), 60.0)
        secs = [s["seconds"] for s in job["storyboard"]["scenes"]]
        self.assertEqual(secs[:4], [12.0, 12.0, 12.0, 12.0])    # 앞 씬은 손대지 않는다
        self.assertEqual(secs[5], shorts_engine.MIN_SCENE_SECONDS)   # 마지막 씬이 먼저 바닥까지
        self.assertEqual(secs[4], 7.0)
        self.assertTrue(any("상한" in w for w in job["warnings"]))
        self.assertTrue(any("씬 6" in w for w in job["warnings"]))

    def test_drops_scenes_when_min_not_enough(self):
        job = {"shorts_id": "shorts_cut_test", "storyboard": {
            "scenes": [{"scene_num": i, "seconds": 3.0} for i in range(1, 26)], "end_tag": {"seconds": 2.0}}}
        warns = shorts_engine.fit_to_max_seconds(job)
        self.assertLessEqual(shorts_engine.total_seconds(job), 60.0)
        self.assertLess(len(job["storyboard"]["scenes"]), 25)
        self.assertTrue(any("제거" in w for w in warns))

    def test_under_60_untouched(self):
        job = {"shorts_id": "x", "storyboard": {"scenes": [{"scene_num": 1, "seconds": 8.0}], "end_tag": {"seconds": 2.0}}}
        self.assertEqual(shorts_engine.fit_to_max_seconds(job), [])
        self.assertEqual(job["storyboard"]["scenes"][0]["seconds"], 8.0)


# ── 3. edge-tts WordBoundary 파싱 (모킹) ─────────────────────────────────────

class FakeCommunicate:
    """edge_tts.Communicate 대역 — stream() 은 audio + WordBoundary 청크(100ns 틱)를 낸다."""
    instances = []

    def __init__(self, text, voice=None, rate=None, pitch=None, boundary=None, **kw):
        self.text, self.voice, self.rate, self.boundary = text, voice, rate, boundary
        self.saved = None
        FakeCommunicate.instances.append(self)

    async def save(self, path):
        self.saved = path
        with open(path, "wb") as f:
            f.write(b"mp3")

    async def stream(self):
        import re as _re
        words = [_re.sub(r"[^\w가-힣]+", "", w) for w in self.text.split()]   # Azure 처럼 구두점 없이
        yield {"type": "audio", "data": b"ID3"}
        t = 500000  # 50ms
        for w in words:
            dur = 2500000 + 1000000 * len(w)  # 250ms + 100ms/글자
            yield {"type": "WordBoundary", "offset": t, "duration": dur, "text": w}
            yield {"type": "audio", "data": b"\x00" * 10}
            t += dur + 800000
        yield {"type": "audio", "data": b"\xff"}


class EdgeTtsWordBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        FakeCommunicate.instances = []
        p = patch.object(tts_service.edge_tts, "Communicate", FakeCommunicate)
        p.start()
        self.addCleanup(p.stop)

    def test_default_path_unchanged_returns_filename(self):
        out = os.path.join(self.tmp, "a.mp3")
        res = asyncio.run(tts_service.TTSService.synthesize_edge_tts_single("안녕하세요 반갑습니다.", output_file=out))
        self.assertEqual(res, out)
        self.assertEqual(FakeCommunicate.instances[-1].saved, out)
        self.assertIsNone(FakeCommunicate.instances[-1].boundary)   # 기존 호출부: boundary 인자 없음

    def test_word_boundaries_become_caption_tokens(self):
        out = os.path.join(self.tmp, "b.mp3")
        res = asyncio.run(tts_service.TTSService.synthesize_edge_tts_single(
            "이거 모르면 손해입니다. 진짜 그래요", output_file=out, with_word_boundaries=True))
        self.assertEqual(res["file"], out)
        self.assertEqual(FakeCommunicate.instances[-1].boundary, "WordBoundary")
        with open(out, "rb") as f:
            self.assertTrue(f.read().startswith(b"ID3"))     # 오디오 청크가 순서대로 기록됨
        caps = res["captions"]
        self.assertEqual([c["text"] for c in caps], ["이거", " 모르면", " 손해입니다.", " 진짜", " 그래요"])   # 구두점 복원
        self.assertEqual(caps[0]["startMs"], 50)
        self.assertEqual(caps[0]["endMs"], 50 + 250 + 200)
        self.assertTrue(caps[2].get("pageBreakAfter"))        # 문장 끝 마침표
        self.assertFalse(caps[3].get("pageBreakAfter"))
        self.assertTrue(caps[-1].get("pageBreakAfter"))       # 씬 끝은 항상 페이지 끝
        for a, b in zip(caps, caps[1:]):
            self.assertLessEqual(a["endMs"], b["startMs"])
        self.assertEqual(res["word_count"], 5)

    def test_short_text_returns_none(self):
        self.assertIsNone(asyncio.run(tts_service.TTSService.synthesize_edge_tts_single("a", with_word_boundaries=True)))

    def test_converter_merges_punctuation_and_fixes_overlap(self):
        caps = tts_service.word_boundaries_to_captions([
            {"offset": 0, "duration": 3000000, "text": "첫째"},
            {"offset": 2500000, "duration": 2000000, "text": "둘째"},      # 앞 토큰과 겹침
            {"offset": 4500000, "duration": 100000, "text": "?"},           # 구두점만 → 앞에 붙음
        ])
        self.assertEqual([c["text"] for c in caps], ["첫째", " 둘째?"])
        self.assertEqual(caps[0]["endMs"], 250)
        self.assertTrue(caps[-1]["pageBreakAfter"])
        self.assertEqual(tts_service.word_boundaries_to_captions([]), [])

    def test_converter_aligns_with_source_text_for_sentence_breaks(self):
        b = [{"offset": i * 5000000, "duration": 4000000, "text": w} for i, w in enumerate(["이거", "모르면", "손해입니다", "전기차", "갑니다", "정말일까요"])]
        caps = tts_service.word_boundaries_to_captions(b, text="이거 모르면 손해입니다. 전기차 갑니다! 정말일까요?")
        self.assertEqual([c["text"] for c in caps], ["이거", " 모르면", " 손해입니다.", " 전기차", " 갑니다!", " 정말일까요?"])
        self.assertEqual([bool(c.get("pageBreakAfter")) for c in caps], [False, False, True, False, True, True])
        # 원문과 어긋난 어절(인식 불일치)은 그대로 두고 뒤는 계속 맞춘다
        b2 = [dict(x) for x in b]
        b2[1]["text"] = "모르시면"
        caps = tts_service.word_boundaries_to_captions(b2, text="이거 모르면 손해입니다. 전기차 갑니다! 정말일까요?")
        self.assertEqual([c["text"] for c in caps][:3], ["이거", " 모르시면", " 손해입니다."])


# ── 4. 오디오: 단어 타이밍 vs 비례 분배 폴백 ─────────────────────────────────

def _fake_synth(with_captions=True, seconds=6.0):
    def synth(text, scene_num, out_base):
        out = out_base + ".mp3"
        with open(out, "wb") as f:
            f.write(b"mp3")
        caps = None
        if with_captions:
            words = text.split()
            step = int(seconds * 1000 / len(words))
            caps = [{"text": (" " if i else "") + w, "startMs": i * step, "endMs": (i + 1) * step - 50} for i, w in enumerate(words)]
            caps[-1]["pageBreakAfter"] = True
        return {"file": out, "captions": caps, "engine": "edge-tts" if with_captions else "qwen-tts"}
    return synth


def _fake_merge(files, out):
    with open(out, "wb") as f:
        for p in files:
            with open(p, "rb") as g:
                f.write(g.read())
    return True


class SynthesizeJobAudioTests(ShortsS2Base):
    def make_job(self, n=3):
        plan = self.save_plan(n=n)
        return shorts_engine.build_job_from_plan(plan["plan_id"])

    def test_edge_captions_shift_to_absolute_time(self):
        job = self.make_job(3)
        job = shorts_engine.synthesize_job_audio(job, synth=_fake_synth(True, 6.0), merger=_fake_merge, bgm_picker=lambda tid: None)
        self.assertEqual(job["caption_source"], "edge_tts")
        scenes = job["storyboard"]["scenes"]
        # 길이 측정 불가 → 자막 끝 + 0.2초, ffmpeg 없음 → 패드 0
        self.assertAlmostEqual(scenes[0]["seconds"], 6.15, places=2)
        self.assertEqual(scenes[0]["caption_source"], "edge_tts")
        caps = job["captions"]
        n_words = len(scenes[0]["narration"].split())
        self.assertEqual(caps[0]["startMs"], 0)
        self.assertEqual(caps[n_words]["startMs"], int(round(scenes[0]["seconds"] * 1000)))   # 2번 씬 첫 어절
        self.assertTrue(caps[n_words - 1]["pageBreakAfter"])
        self.assertTrue(os.path.exists(job["audio"]["narration"]))
        self.assertIsNone(job["audio"]["bgm"])
        self.assertTrue(any("BGM 없이" in w for w in job["warnings"]))
        self.assertEqual(job["status"], "assets")

    def test_proportional_fallback_when_no_timing(self):
        job = self.make_job(2)
        job = shorts_engine.synthesize_job_audio(job, synth=_fake_synth(False), merger=_fake_merge, bgm_picker=lambda tid: None)
        self.assertEqual(job["caption_source"], "proportional")
        s0 = job["storyboard"]["scenes"][0]
        self.assertAlmostEqual(s0["seconds"], round(len(s0["narration"]) / 5.2, 2), places=1)
        caps = job["captions"]
        self.assertEqual(caps[0]["text"], s0["narration"].split()[0])
        self.assertTrue(caps[len(s0["narration"].split()) - 1]["pageBreakAfter"])
        self.assertEqual(caps[-1]["endMs"], int(round(s0["seconds"] * 1000)) + int(round(job["storyboard"]["scenes"][1]["narration_seconds"] * 1000)))

    def test_mixed_sources_report_proportional(self):
        job = self.make_job(2)
        calls = {"n": 0}
        def synth(text, num, base):
            calls["n"] += 1
            return _fake_synth(calls["n"] == 1)(text, num, base)
        job = shorts_engine.synthesize_job_audio(job, synth=synth, merger=_fake_merge, bgm_picker=lambda tid: None)
        self.assertEqual(job["caption_source"], "proportional")

    def test_bgm_picked_from_instrumental_track(self):
        job = self.make_job(2)
        bgm = os.path.join(self.tmp, "bgm.mp3")
        with open(bgm, "wb") as f:
            f.write(b"mp3")
        job = shorts_engine.synthesize_job_audio(job, synth=_fake_synth(), merger=_fake_merge,
                                                 bgm_picker=lambda tid: {"track_id": "t1", "file": bgm, "title": "Lofi"})
        self.assertEqual(job["audio"]["bgm"], bgm)
        self.assertEqual(job["audio"]["bgm_track_id"], "t1")

    def _bgm_file(self, data=b"luna-mp3"):
        bgm = os.path.join(self.tmp, "luna_audio.mp3")
        with open(bgm, "wb") as f:
            f.write(data)
        return bgm

    def test_bgm_volume_keeps_narration_gap(self):
        job = self.make_job(2)
        bgm = self._bgm_file()
        levels = {"narration.mp3": -19.6, "luna_audio.mp3": -12.4}
        job = shorts_engine.synthesize_job_audio(job, synth=_fake_synth(), merger=_fake_merge,
                                                 bgm_picker=lambda tid: {"track_id": "t1", "file": bgm, "title": "Synth"},
                                                 lufs_probe=lambda path, seconds=None: levels[os.path.basename(path)])
        audio = job["audio"]
        self.assertEqual(audio["bgm_under_lu"], 22.0)
        self.assertEqual(audio["bgm_lufs"], -12.4)
        self.assertEqual(audio["bgm_volume"], round(10 ** ((-19.6 - 22.0 + 12.4) / 20), 4))   # 0.0347
        with open(bgm, "rb") as f:
            self.assertEqual(f.read(), b"luna-mp3")   # 루나 원곡은 읽기만 한다

    def test_bgm_gap_override_and_cap(self):
        job = self.make_job(2)
        job["audio"]["bgm_under_lu"] = 18
        bgm = self._bgm_file()
        levels = {"narration.mp3": -19.6, "luna_audio.mp3": -12.4}
        job = shorts_engine.synthesize_job_audio(job, synth=_fake_synth(), merger=_fake_merge,
                                                 bgm_picker=lambda tid: {"track_id": "t1", "file": bgm, "title": "Synth"},
                                                 lufs_probe=lambda path, seconds=None: levels[os.path.basename(path)])
        self.assertEqual(job["audio"]["bgm_volume"], 0.055)
        # 아주 조용한 곡이어도 기존 배율(0.16)보다 크게 키우지 않는다
        self.assertEqual(shorts_engine.bgm_volume_for(-19.6, -45.0), shorts_engine.DEFAULT_BGM_VOLUME)

    def test_bgm_volume_falls_back_when_unmeasurable(self):
        job = self.make_job(2)
        bgm = self._bgm_file()
        job = shorts_engine.synthesize_job_audio(job, synth=_fake_synth(), merger=_fake_merge,
                                                 bgm_picker=lambda tid: {"track_id": "t1", "file": bgm, "title": "Synth"},
                                                 lufs_probe=lambda path, seconds=None: None)
        self.assertEqual(job["audio"]["bgm_volume"], shorts_engine.BGM_FALLBACK_VOLUME)
        self.assertTrue(any("BGM 음량" in w for w in job["warnings"]))

    def test_pick_bgm_filters_vocal_mode(self):
        fake_luna = MagicMock()
        fake_luna.LUNA_DIR = self.tmp
        os.makedirs(os.path.join(self.tmp, "inst1"))
        with open(os.path.join(self.tmp, "inst1", "audio.mp3"), "wb") as f:
            f.write(b"x")
        fake_luna.list_tracks.return_value = [
            {"track_id": "voc1", "vocal_mode": "lyrics", "title": "Vocal"},
            {"track_id": "inst0", "vocal_mode": "instrumental", "title": "No file"},
            {"track_id": "inst1", "vocal_mode": "instrumental", "title": "Inst"},
        ]
        fake_luna.load_track.return_value = {}
        with patch.dict("sys.modules", {"luna_engine": fake_luna}):
            picked = shorts_engine.pick_bgm()
        self.assertEqual(picked["track_id"], "inst1")
        with patch.dict("sys.modules", {"luna_engine": fake_luna}):
            fake_luna.list_tracks.return_value = [{"track_id": "voc1", "vocal_mode": "lyrics"}]
            self.assertIsNone(shorts_engine.pick_bgm())

    def test_narration_over_60s_fails_clearly(self):
        job = self.make_job(6)
        with self.assertRaises(RuntimeError) as cm:
            shorts_engine.synthesize_job_audio(job, synth=_fake_synth(True, 11.0), merger=_fake_merge, bgm_picker=lambda tid: None)
        self.assertIn("상한", str(cm.exception))
        self.assertEqual(job["storyboard"]["end_tag"]["seconds"], 1.5)   # 엔드 태그를 먼저 줄여 봤다

    def test_empty_narration_rejected(self):
        job = self.make_job(2)
        job["storyboard"]["scenes"][1]["narration"] = ""
        with self.assertRaises(RuntimeError):
            shorts_engine.synthesize_job_audio(job, synth=_fake_synth(), merger=_fake_merge, bgm_picker=lambda tid: None)

# ── 4b. edge-tts 끝 무음 자르기 (InJoon 은 끝에 약 1.2초 무음을 붙인다) ─────────

class IntegratedLufsTests(unittest.TestCase):
    def test_measures_real_file_and_handles_missing(self):
        ff = producer.ffmpeg_path()
        if not ff:
            self.skipTest("ffmpeg 없음")
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        loud, quiet = os.path.join(d, "loud.mp3"), os.path.join(d, "quiet.mp3")
        for path, vol in ((loud, "0dB"), (quiet, "-12dB")):
            subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                            "-af", f"volume={vol}", "-c:a", "libmp3lame", "-q:a", "2", path], check=True)
        a, b = shorts_engine.integrated_lufs(loud), shorts_engine.integrated_lufs(quiet)
        self.assertIsInstance(a, float)
        self.assertAlmostEqual(a - b, 12.0, delta=0.5)
        self.assertIsNone(shorts_engine.integrated_lufs(os.path.join(d, "none.mp3")))


class TrimTrailingSilenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ff = producer.ffmpeg_path()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_tone_then_silence(self, tone=1.0, silence=1.5):
        out = os.path.join(self.tmp, "n.mp3")
        subprocess.run([self.ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={tone}",
                        "-af", f"apad=pad_dur={silence}", "-c:a", "libmp3lame", "-q:a", "2", out], check=True)
        return out

    def test_trims_trailing_silence_in_place(self):
        if not self.ff:
            self.skipTest("ffmpeg 없음")
        path = self.make_tone_then_silence()
        self.assertGreater(producer.audio_duration(path), 2.3)
        self.assertTrue(shorts_engine._trim_trailing_silence(self.ff, path))
        self.assertLess(producer.audio_duration(path), 1.4)
        self.assertGreater(producer.audio_duration(path), 0.9)
        self.assertFalse(os.path.exists(path + ".trim.mp3"))

    def test_never_cuts_before_last_word_end(self):
        if not self.ff:
            self.skipTest("ffmpeg 없음")
        path = self.make_tone_then_silence()
        # edge-tts 단어 끝 시각은 실제 소리보다 늦다 — 무음 기준 길이(약 1.1초)보다 뒤인 2.0초에서 끝난다고 하면 거기까지는 남긴다
        self.assertTrue(shorts_engine._trim_trailing_silence(self.ff, path, min_seconds=2.0))
        self.assertGreaterEqual(producer.audio_duration(path), 2.0)
        self.assertLess(producer.audio_duration(path), 2.25)

    def test_keeps_original_when_nothing_to_cut(self):
        if not self.ff:
            self.skipTest("ffmpeg 없음")
        path = self.make_tone_then_silence()
        before = producer.audio_duration(path)
        self.assertFalse(shorts_engine._trim_trailing_silence(self.ff, path, min_seconds=before - 0.05))
        self.assertAlmostEqual(producer.audio_duration(path), before, places=2)

    def test_no_ffmpeg_leaves_file(self):
        path = os.path.join(self.tmp, "n.mp3")
        with open(path, "wb") as f:
            f.write(b"mp3")
        self.assertFalse(shorts_engine._trim_trailing_silence(None, path))
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"mp3")

    def test_edge_synth_trims_with_last_word_end(self):
        out_base = os.path.join(self.tmp, "narration_01")
        caps = [{"text": "안녕", "startMs": 350, "endMs": 900}, {"text": " 하세요", "startMs": 900, "endMs": 1800}]

        async def fake_edge(text, voice_code=None, rate=None, output_file=None, with_word_boundaries=False):
            with open(output_file, "wb") as f:
                f.write(b"mp3")
            return {"captions": caps}

        with patch.object(tts_service.TTSService, "synthesize_edge_tts_single", side_effect=fake_edge), \
             patch.object(shorts_engine, "_trim_trailing_silence", return_value=True) as trim, \
             patch.object(producer, "ffmpeg_path", return_value="/usr/bin/ffmpeg"):
            res = shorts_engine._default_synth("edge_injoon")("안녕 하세요", 1, out_base)
        self.assertEqual(res["file"], out_base + ".mp3")
        trim.assert_called_once_with("/usr/bin/ffmpeg", out_base + ".mp3", min_seconds=1.8)


# ── 5. QC ────────────────────────────────────────────────────────────────────

class QcJobTests(ShortsS2Base):
    def make_rendered(self):
        d = os.path.join(self.tmp, "shorts", "shorts_qc_1")
        os.makedirs(d)
        f = os.path.join(d, "final_9x16.mp4")
        with open(f, "wb") as fh:
            fh.write(b"mp4")
        return {"shorts_id": "shorts_qc_1", "status": "rendered", "storyboard": {"scenes": [{"scene_num": 1, "seconds": 5}]},
                "render": {"file": f, "url": "/data/shorts/shorts_qc_1/final_9x16.mp4"}, "audio": {}}

    GOOD = {"width": 1080, "height": 1920, "duration": 42.3, "fps": 30.0, "audio_present": True, "audio_codec": "aac"}

    def test_pass(self):
        job = shorts_engine.qc_job(self.make_rendered(), probe=self.GOOD, brightness=88.0, loudness={"lufs": -18.4, "true_peak": -1.2})
        self.assertTrue(job["qc"]["passed"])
        self.assertEqual(job["status"], "qc_passed")
        self.assertEqual(job["qc"]["failed"], [])
        names = [c["name"] for c in job["qc"]["checks"]]
        for n in ("duration<=60", "1080x1920", "audio_present", "first_frame_not_black", "lufs_within_1db"):
            self.assertIn(n, names)

    def test_fail_collects_items(self):
        bad = dict(self.GOOD, duration=61.0, width=1920, height=1080, audio_present=False)
        job = shorts_engine.qc_job(self.make_rendered(), probe=bad, brightness=3.0, loudness={"lufs": -21.0, "true_peak": -1.0})
        self.assertFalse(job["qc"]["passed"])
        self.assertEqual(job["status"], "failed")
        self.assertEqual(set(job["qc"]["failed"]), {"duration<=60", "1080x1920", "audio_present", "first_frame_not_black", "lufs_within_1db"})
        self.assertIn("QC 실패", job["error"])

    def test_unmeasurable_items_skipped_not_failed(self):
        job = shorts_engine.qc_job(self.make_rendered(), probe=self.GOOD, measure=False)
        self.assertTrue(job["qc"]["passed"])
        skipped = [c["name"] for c in job["qc"]["checks"] if c["skipped"]]
        self.assertEqual(set(skipped), {"first_frame_not_black", "lufs_within_1db"})

    def test_lufs_from_job_audio_is_used(self):
        job = self.make_rendered()
        job["audio"] = {"lufs": -16.5, "true_peak": -1.0}
        job = shorts_engine.qc_job(job, probe=self.GOOD, brightness=50.0)
        self.assertIn("lufs_within_1db", job["qc"]["failed"])

    def test_missing_file_fails(self):
        job = self.make_rendered()
        os.remove(job["render"]["file"])
        job = shorts_engine.qc_job(job, probe=self.GOOD)
        self.assertEqual(job["qc"]["failed"], ["file_exists"])

    def test_first_frame_brightness_parses_rawvideo(self):
        def runner(cmd, capture_output=None, timeout=None):
            res = MagicMock()
            res.returncode, res.stdout = 0, bytes([200, 100, 0, 100])
            return res
        self.assertEqual(shorts_engine.first_frame_brightness(__file__, ff="/fake/ffmpeg", runner=runner), 100.0)
        self.assertIsNone(shorts_engine.first_frame_brightness(__file__, ff=None))

    def test_normalize_loudness_uses_plain_gain_when_peak_allows(self):
        job = self.make_rendered()
        measured = iter([{"lufs": -20.0, "true_peak": -3.0, "silent": False}, {"lufs": -18.1, "true_peak": -1.0, "silent": False}])
        calls = {}
        def runner(cmd, capture_output=None, text=None, timeout=None):
            calls["cmd"] = cmd
            with open(cmd[-1], "wb") as f:
                f.write(b"normalized")
            r = MagicMock(); r.returncode = 0
            return r
        with patch.object(producer, "ffmpeg_path", lambda: "/fake/ffmpeg"):
            job = shorts_engine.normalize_loudness(job, measurer=lambda p: next(measured), runner=runner)
        self.assertTrue(job["audio"]["loudnorm_applied"])
        self.assertEqual(job["audio"]["loudness_method"], "gain")
        self.assertEqual(job["audio"]["lufs_before"], -20.0)
        self.assertEqual(job["audio"]["lufs"], -18.1)
        af = calls["cmd"][calls["cmd"].index("-af") + 1]
        self.assertEqual(af, "volume=2.00dB")   # 대사 강약을 누르지 않고 볼륨만 올린다
        with open(job["render"]["file"], "rb") as f:
            self.assertEqual(f.read(), b"normalized")

    def test_normalize_loudness_falls_back_to_loudnorm_when_peak_would_clip(self):
        job = self.make_rendered()
        measured = iter([{"lufs": -24.0, "true_peak": -2.0, "silent": False}, {"lufs": -18.0, "true_peak": -1.0, "silent": False}])
        calls = {}
        def runner(cmd, capture_output=None, text=None, timeout=None):
            calls["cmd"] = cmd
            with open(cmd[-1], "wb") as f:
                f.write(b"normalized")
            r = MagicMock(); r.returncode = 0
            return r
        with patch.object(producer, "ffmpeg_path", lambda: "/fake/ffmpeg"):
            job = shorts_engine.normalize_loudness(job, measurer=lambda p: next(measured), runner=runner)
        self.assertEqual(job["audio"]["loudness_method"], "loudnorm")
        self.assertIn("loudnorm=I=-18.0:TP=-1.0:LRA=11", " ".join(calls["cmd"]))

    def test_normalize_loudness_skips_when_in_range_or_unmeasurable(self):
        job = self.make_rendered()
        runner = MagicMock()
        job = shorts_engine.normalize_loudness(job, measurer=lambda p: {"lufs": -17.6, "true_peak": -1.0, "silent": False}, runner=runner)
        self.assertFalse(job["audio"]["loudnorm_applied"])
        runner.assert_not_called()
        job = shorts_engine.normalize_loudness(job, measurer=lambda p: None, runner=runner)
        self.assertIsNone(job["audio"]["lufs"])
        runner.assert_not_called()


# ── 6. 이미지 상한·사용량·과금 가드 ──────────────────────────────────────────

class ImageCapTests(ShortsS2Base):
    def test_usage_counter_lifecycle(self):
        self.assertEqual(shorts_engine.get_today_usage(), 0)
        shorts_engine._increment_usage(3)
        shorts_engine._increment_usage(2)
        self.assertEqual(shorts_engine.get_today_usage(), 5)
        u = shorts_engine.usage_summary()
        self.assertEqual((u["today"], u["cap"], u["remaining"], u["per_job_cap"]), (5, 40, 35, 7))
        with patch.dict(os.environ, {"SHORTS_MAX_IMAGES_PER_DAY": "10", "SHORTS_MAX_IMAGES_PER_JOB": "3"}):
            self.assertEqual((shorts_engine.daily_cap(), shorts_engine.per_job_cap()), (10, 3))

    def test_estimate_blocks_daily_cap(self):
        plan = self.save_plan(n=5)
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        with patch.object(producer, "gemini_key", lambda: "k"):
            est = shorts_engine.estimate_images(job)
            self.assertEqual((est["needed"], est["usd"], est["allowed"]), (5, round(5 * shorts_engine.IMAGE_USD_PER_IMAGE, 3), True))
            shorts_engine._increment_usage(37)
            est = shorts_engine.estimate_images(job)
            self.assertFalse(est["allowed"])
            self.assertIn("일일", est["reason"])
            with self.assertRaises(RuntimeError):
                shorts_engine.generate_job_images(job, generator=MagicMock())

    def test_estimate_blocks_per_job_cap_and_missing_key(self):
        plan = self.save_plan(n=5)
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        with patch.dict(os.environ, {"SHORTS_MAX_IMAGES_PER_JOB": "4"}), patch.object(producer, "gemini_key", lambda: "k"):
            est = shorts_engine.estimate_images(job)
            self.assertFalse(est["allowed"])
            self.assertIn("편당", est["reason"])
        with patch.object(producer, "gemini_key", lambda: ""):
            est = shorts_engine.estimate_images(job)
            self.assertFalse(est["allowed"])
            self.assertIn("Gemini", est["reason"])

    def test_generate_uses_producer_slots_and_counts_usage(self):
        plan = self.save_plan(n=3)
        self.add_images(plan, [1])
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        rec = {}
        def gen(p, slots=None, progress=None):
            rec["slots"] = slots
            self.assertEqual(p["aspect_ratio"], "9:16")
            progress("images", "x", 50)
            self.add_images(p, [int(s) for s in slots])
            return {"generated": list(slots), "errors": []}
        prog = []
        with patch.object(producer, "gemini_key", lambda: "k"):
            res = shorts_engine.generate_job_images(job, progress_cb=lambda s, m, p: prog.append((s, p)), generator=gen)
        self.assertEqual(rec["slots"], ["2", "3"])
        self.assertEqual(res["generated"], ["2", "3"])
        self.assertEqual(shorts_engine.get_today_usage(), 2)
        self.assertTrue(all(s["image"] for s in job["storyboard"]["scenes"]))
        self.assertEqual(prog, [("images", 50)])
        # 다시 부르면 생성 없음
        self.assertEqual(shorts_engine.generate_job_images(job, generator=MagicMock(side_effect=AssertionError))["generated"], [])

    def test_partial_failure_raises_but_counts_generated(self):
        plan = self.save_plan(n=3)
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        def gen(p, slots=None, progress=None):
            self.add_images(p, [1])
            return {"generated": ["1"], "errors": [{"slot": "2", "error": "안전 필터"}, {"slot": "3", "error": "한도"}]}
        with patch.object(producer, "gemini_key", lambda: "k"):
            with self.assertRaises(RuntimeError) as cm:
                shorts_engine.generate_job_images(job, generator=gen)
        self.assertIn("2, 3", str(cm.exception))
        self.assertEqual(shorts_engine.get_today_usage(), 1)
        self.assertTrue(any("안전 필터" in w for w in job["warnings"]))


# ── 7. 빌드 오케스트레이션 ───────────────────────────────────────────────────

class BuildJobTests(ShortsS2Base):
    def fake_renderer(self, job, renderer=None, progress_cb=None):
        d = shorts_engine.job_dir(job["shorts_id"], create=True)
        f = os.path.join(d, shorts_engine.FINAL_NAME)
        with open(f, "wb") as fh:
            fh.write(b"mp4")
        job["render"] = {"renderer_used": "remotion", "file": f, "url": f"/data/shorts/{job['shorts_id']}/final_9x16.mp4",
                         "probe": QcJobTests.GOOD}
        job["status"] = "rendered"
        if progress_cb:
            progress_cb("shorts_render", "렌더", 100)
        return job

    def hooks(self, **over):
        h = {"synth": _fake_synth(), "merger": _fake_merge, "bgm_picker": lambda tid: None, "renderer_fn": self.fake_renderer,
             "measurer": lambda p: {"lufs": -18.2, "true_peak": -1.1, "silent": False},
             "qc_kwargs": {"brightness": 90.0}}
        h.update(over)
        return h

    def test_full_pipeline_reaches_qc_passed(self):
        plan = self.save_plan(n=4)
        self.add_images(plan, [1, 2, 3, 4])
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        prog = []
        job = shorts_engine.build_job(job, options={"confirm": False}, progress_cb=lambda s, m, p: prog.append((s, p)), **self.hooks())
        self.assertEqual(job["status"], "qc_passed", job.get("error"))
        self.assertEqual(job["caption_source"], "edge_tts")
        self.assertEqual(job["audio"]["lufs"], -18.2)
        self.assertTrue(job["qc"]["passed"])
        pcts = [p for _, p in prog]
        self.assertEqual(pcts, sorted(pcts))
        self.assertEqual(prog[-1], ("qc", 100))
        stages = [s for s, _ in prog]
        self.assertEqual(stages[0], "images")
        self.assertTrue(40 <= [p for s, p in prog if s == "audio"][0] <= 60)
        self.assertTrue(all(60 <= p <= 97 for s, p in prog if s == "render"))
        self.assertEqual(shorts_engine.load_job(job["shorts_id"])["status"], "qc_passed")

    def test_confirm_guard_blocks_image_generation(self):
        plan = self.save_plan(n=3)
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        gen = MagicMock()
        with patch.object(producer, "gemini_key", lambda: "k"):
            job = shorts_engine.build_job(job, options={"confirm": False}, **self.hooks(generator=gen))
        self.assertEqual(job["status"], "failed")
        self.assertIn("confirm=true", job["error"])
        gen.assert_not_called()

    def test_confirmed_build_generates_images_then_passes(self):
        plan = self.save_plan(n=3)
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        def gen(p, slots=None, progress=None):
            self.add_images(p, [int(s) for s in slots])
            return {"generated": list(slots), "errors": []}
        with patch.object(producer, "gemini_key", lambda: "k"):
            job = shorts_engine.build_job(job, options={"confirm": True}, **self.hooks(generator=gen))
        self.assertEqual(job["status"], "qc_passed", job.get("error"))
        self.assertEqual(shorts_engine.get_today_usage(), 3)

    def test_render_failure_marks_failed(self):
        plan = self.save_plan(n=2)
        self.add_images(plan, [1, 2])
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        def boom(job, renderer=None, progress_cb=None):
            raise RuntimeError("Remotion 렌더 실패: boom")
        job = shorts_engine.build_job(job, **self.hooks(renderer_fn=boom))
        self.assertEqual(job["status"], "failed")
        self.assertIn("boom", job["error"])

    def test_qc_failure_sets_failed_with_checks(self):
        plan = self.save_plan(n=2)
        self.add_images(plan, [1, 2])
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        job = shorts_engine.build_job(job, **self.hooks(qc_kwargs={"brightness": 2.0}))
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["qc"]["failed"], ["first_frame_not_black"])


# ── 8. 스토리보드 편집 ───────────────────────────────────────────────────────

class UpdateStoryboardTests(ShortsS2Base):
    def test_edit_fields_and_refit(self):
        plan = self.save_plan(n=3)
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        job = shorts_engine.update_storyboard(job, hook_text="  새 훅  ", scenes=[
            {"scene_num": 2, "narration": "바뀐 대본", "seconds": 15, "motion": "pan_right"},
            {"scene_num": 9, "narration": "없는 씬"}, {"scene_num": 3, "motion": "spin"}], end_tag={"text": "끝", "seconds": 9})
        sb = job["storyboard"]
        self.assertEqual(sb["hook_text"], "새 훅")
        self.assertEqual(sb["scenes"][1]["narration"], "바뀐 대본")
        self.assertEqual(sb["scenes"][1]["seconds"], 15.0)
        self.assertEqual(sb["scenes"][1]["motion"], "pan_right")
        self.assertEqual(sb["scenes"][2]["motion"], "pan_left")   # 잘못된 모션은 무시
        self.assertEqual(sb["end_tag"]["text"], "끝")
        self.assertEqual(sb["end_tag"]["seconds"], 4.0)            # 상한 4초
        self.assertEqual(shorts_engine.load_job(job["shorts_id"])["storyboard"]["hook_text"], "새 훅")

    def test_edit_transition(self):
        plan = self.save_plan(n=3)
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        job = shorts_engine.update_storyboard(job, scenes=[{"scene_num": 2, "transition": "wipe"}, {"scene_num": 3, "transition": "spin"}])
        sb = job["storyboard"]
        self.assertEqual(sb["scenes"][1]["transition"], "wipe")
        self.assertNotIn("transition_auto", sb["scenes"][1])     # 사용자가 고른 전환
        self.assertNotEqual(sb["scenes"][2]["transition"], "spin")  # 잘못된 전환은 무시되고
        self.assertTrue(sb["scenes"][2]["transition_auto"])      # U-3 자동 배정이 채운다


# ── 9. API 라우트 (TestClient) ───────────────────────────────────────────────

class ShortsApiTests(ShortsS2Base):
    def setUp(self):
        super().setUp()
        self.client = TestClient(app_module.app)
        app_module._shorts_building.clear()

    def test_create_list_get_delete(self):
        plan = self.save_plan(n=3)
        r = self.client.post("/api/shorts/jobs", json={"plan_id": plan["plan_id"], "platforms": ["youtube_shorts"]})
        self.assertEqual(r.status_code, 200, r.text)
        sid = r.json()["shorts_id"]
        self.assertEqual(r.json()["estimate"]["needed"], 3)
        self.assertEqual(r.json()["data"]["storyboard"]["hook_text"], "아무도 몰랐던 전기차 배터리")
        r = self.client.get("/api/shorts/jobs")
        self.assertEqual([j["shorts_id"] for j in r.json()["data"]], [sid])
        self.assertFalse(r.json()["data"][0]["building"])
        r = self.client.get(f"/api/shorts/jobs/{sid}")
        self.assertEqual(r.json()["data"]["status"], "planned")
        r = self.client.get("/api/shorts/plans")
        self.assertEqual([p["id"] for p in r.json()["data"]], [plan["plan_id"]])
        r = self.client.delete(f"/api/shorts/jobs/{sid}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get(f"/api/shorts/jobs/{sid}").status_code, 404)

    def test_plans_endpoint_hides_16x9(self):
        self.save_plan(aspect="16:9", topic="가로")
        v = self.save_plan(aspect="9:16", topic="세로")
        r = self.client.get("/api/shorts/plans")
        self.assertEqual([p["id"] for p in r.json()["data"]], [v["plan_id"]])

    def test_create_errors(self):
        self.assertEqual(self.client.post("/api/shorts/jobs", json={"plan_id": "scenes_1_x"}).status_code, 404)
        plan = self.save_plan(aspect="16:9")
        r = self.client.post("/api/shorts/jobs", json={"plan_id": plan["plan_id"]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("9:16", r.json()["detail"])

    def test_invalid_id_rejected_everywhere(self):
        for method, path in (("get", "/api/shorts/jobs/..%2Fetc"), ("get", "/api/shorts/jobs/a b"), ("delete", "/api/shorts/jobs/x"),
                             ("post", "/api/shorts/jobs/bad!id/build"), ("get", "/api/shorts/jobs/bad!id/estimate")):
            r = getattr(self.client, method)(path, **({"json": {}} if method == "post" else {}))
            self.assertIn(r.status_code, (400, 404), f"{method} {path} -> {r.status_code}")
        self.assertEqual(self.client.get("/api/shorts/jobs/shorts_missing_1").status_code, 404)

    def test_storyboard_put(self):
        plan = self.save_plan(n=2)
        sid = self.client.post("/api/shorts/jobs", json={"plan_id": plan["plan_id"]}).json()["shorts_id"]
        r = self.client.put(f"/api/shorts/jobs/{sid}/storyboard", json={"hook_text": "훅!", "scenes": [{"scene_num": 1, "seconds": 6}],
                                                                       "end_tag": {"text": "구독"}})
        self.assertEqual(r.status_code, 200, r.text)
        sb = r.json()["data"]["storyboard"]
        self.assertEqual((sb["hook_text"], sb["scenes"][0]["seconds"], sb["end_tag"]["text"]), ("훅!", 6.0, "구독"))

    def test_build_requires_confirm_and_returns_estimate(self):
        plan = self.save_plan(n=3)
        sid = self.client.post("/api/shorts/jobs", json={"plan_id": plan["plan_id"]}).json()["shorts_id"]
        with patch.object(producer, "gemini_key", lambda: "k"), patch.object(shorts_engine, "build_job") as bj:
            r = self.client.post(f"/api/shorts/jobs/{sid}/build", json={"confirm": False})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["status"], "confirm_required")
            self.assertEqual(r.json()["estimate"]["needed"], 3)
            bj.assert_not_called()
            r = self.client.get(f"/api/shorts/jobs/{sid}/estimate")
            self.assertEqual(r.json()["estimate"]["usd"], round(3 * shorts_engine.IMAGE_USD_PER_IMAGE, 3))

    def test_build_daily_cap_returns_429(self):
        plan = self.save_plan(n=3)
        sid = self.client.post("/api/shorts/jobs", json={"plan_id": plan["plan_id"]}).json()["shorts_id"]
        shorts_engine._increment_usage(39)
        with patch.object(producer, "gemini_key", lambda: "k"), patch.object(shorts_engine, "build_job") as bj:
            r = self.client.post(f"/api/shorts/jobs/{sid}/build", json={"confirm": True})
            self.assertEqual(r.status_code, 429)
            bj.assert_not_called()

    def test_build_without_key_returns_400(self):
        plan = self.save_plan(n=2)
        sid = self.client.post("/api/shorts/jobs", json={"plan_id": plan["plan_id"]}).json()["shorts_id"]
        with patch.object(producer, "gemini_key", lambda: ""), patch.object(shorts_engine, "build_job") as bj:
            r = self.client.post(f"/api/shorts/jobs/{sid}/build", json={"confirm": True})
            self.assertEqual(r.status_code, 400)
            bj.assert_not_called()

    def test_build_starts_background_worker_with_options(self):
        plan = self.save_plan(n=2)
        self.add_images(plan, [1, 2])
        sid = self.client.post("/api/shorts/jobs", json={"plan_id": plan["plan_id"]}).json()["shorts_id"]
        rec = {}
        def fake_build(job, options=None, progress_cb=None, **kw):
            rec["sid"], rec["options"] = job["shorts_id"], options
            job["status"] = "qc_passed"
            shorts_engine.save_job(job)
            return job
        with patch.object(shorts_engine, "build_job", fake_build):
            r = self.client.post(f"/api/shorts/jobs/{sid}/build", json={"confirm": False, "renderer": "ffmpeg", "voice_id": "edge_sunhi"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "started")
        self.assertEqual(r.json()["estimate"]["needed"], 0)
        self.assertEqual(rec["sid"], sid)
        self.assertEqual(rec["options"], {"confirm": False, "renderer": "ffmpeg", "voice_id": "edge_sunhi"})
        self.assertEqual(self.client.get(f"/api/shorts/jobs/{sid}").json()["data"]["status"], "qc_passed")
        self.assertNotIn(sid, app_module._shorts_building)

    def test_build_conflict_while_building(self):
        plan = self.save_plan(n=2)
        sid = self.client.post("/api/shorts/jobs", json={"plan_id": plan["plan_id"]}).json()["shorts_id"]
        app_module._shorts_building.add(sid)
        try:
            self.assertEqual(self.client.post(f"/api/shorts/jobs/{sid}/build", json={"confirm": True}).status_code, 409)
            self.assertEqual(self.client.put(f"/api/shorts/jobs/{sid}/storyboard", json={"hook_text": "x"}).status_code, 409)
            self.assertEqual(self.client.delete(f"/api/shorts/jobs/{sid}").status_code, 409)
            self.assertTrue(self.client.get(f"/api/shorts/jobs/{sid}").json()["building"])
        finally:
            app_module._shorts_building.discard(sid)

    def test_usage_endpoint(self):
        r = self.client.get("/api/shorts/usage")
        self.assertEqual(r.status_code, 200)
        for k in ("today", "cap", "per_job_cap", "remotion_available", "default_renderer", "gemini_key_set"):
            self.assertIn(k, r.json())


# ── 10. 컨셉 팩 · 프롬프트 생성기 9:16 분기 ─────────────────────────────────

class ConceptAndPromptTests(unittest.TestCase):
    def test_shorts_pack_and_spec(self):
        import concept_packs
        self.assertIn("shorts_info", [p["key"] for p in concept_packs.list_packs()])
        spec = concept_packs.shorts_spec("shorts_info")
        self.assertEqual(spec["max_scenes"], 6)
        self.assertEqual((spec["scene_seconds"]["min"], spec["scene_seconds"]["max"]), (5.0, 8.0))
        self.assertEqual((spec["total_seconds"]["min"], spec["total_seconds"]["max"]), (30.0, 58.0))
        self.assertEqual((spec["hook_words"]["min"], spec["hook_words"]["max"]), (3, 5))
        self.assertTrue(concept_packs.is_shorts_pack("shorts_info"))
        self.assertFalse(concept_packs.is_shorts_pack("redline_engineering"))
        self.assertEqual(concept_packs.shorts_spec("redline_engineering")["max_scenes"], 6)   # 기본 규격 폴백
        self.assertFalse(concept_packs.allows_text("shorts_info", "scene"))
        self.assertIn("훅", concept_packs.get_pack("shorts_info")["plot"])

    def test_vertical_scene_count_capped_and_hook_fields(self):
        from prompt_generator import PromptGenerator
        sent = {}
        def fake_llm(messages, max_tokens=None, temperature=None):
            sent["prompt"] = messages[1]["content"]
            scenes = [{"scene_num": i, "narration": "나레이션 " * 5, "prompt_en": "x", "visual_description_ko": "v", "sfx": "s"} for i in range(1, 7)]
            return json.dumps({"recommended_title": "제목", "hook_text": "이거 모르면 손해", "end_tag_text": "구독!", "scenes": scenes}, ensure_ascii=False)
        with patch("prompt_generator.llm_client.call_llm", fake_llm), \
             patch.object(PromptGenerator, "generate_redline_image_prompts", staticmethod(lambda **kw: {"thumbnail_redline": {}, "scene_first_frames": []})), \
             patch.object(PromptGenerator, "save_output_document", staticmethod(lambda d: "")):
            res = PromptGenerator.generate_prompts_from_custom_topic("주제", scene_count=10, aspect_ratio="9:16", concept_key="shorts_info")
            self.assertIn("총 씬 개수: 정확히 6개", sent["prompt"])
            self.assertIn("쇼츠(9:16) 전용 규칙", sent["prompt"])
            self.assertIn('"hook_text"', sent["prompt"])
            self.assertIn('"kind": "image|text_card|stat_card|bar_chart|compare|flyover|scene3d"', sent["prompt"])
            self.assertIn("image 는 편당 최대 2씬", sent["prompt"])
            self.assertEqual([sc["kind"] for sc in res["scenes"]], ["image"] * 6)   # kind 없으면 image
            self.assertEqual(res["hook_text"], "이거 모르면 손해")
            self.assertEqual(res["end_tag_text"], "구독!")
            self.assertEqual(res["shorts_spec"]["max_scenes"], 6)
            # 16:9 롱폼은 그대로: 씬 10개, 쇼츠 규칙 없음, 훅 필드 없음
            res = PromptGenerator.generate_prompts_from_custom_topic("주제", scene_count=10, aspect_ratio="16:9")
            self.assertIn("총 씬 개수: 정확히 10개", sent["prompt"])
            self.assertNotIn("쇼츠(9:16) 전용 규칙", sent["prompt"])
            self.assertNotIn('"kind"', sent["prompt"])
            self.assertNotIn("hook_text", res)
            self.assertNotIn("kind", res["scenes"][0])

    def test_vertical_llm_kinds_validated(self):
        from prompt_generator import PromptGenerator
        def fake_llm(messages, max_tokens=None, temperature=None):
            scenes = [{"scene_num": 1, "narration": "n" * 40, "kind": "text_card", "title": "훅"},
                      {"scene_num": 2, "narration": "n" * 40, "kind": "STAT_CARD", "value": 3},
                      {"scene_num": 3, "narration": "n" * 40, "kind": "hologram"}]
            return json.dumps({"recommended_title": "제목", "scenes": scenes}, ensure_ascii=False)
        with patch("prompt_generator.llm_client.call_llm", fake_llm), \
             patch.object(PromptGenerator, "generate_redline_image_prompts", staticmethod(lambda **kw: {"thumbnail_redline": {}, "scene_first_frames": []})), \
             patch.object(PromptGenerator, "save_output_document", staticmethod(lambda d: "")):
            res = PromptGenerator.generate_prompts_from_custom_topic("주제", scene_count=3, aspect_ratio="9:16", concept_key="shorts_info")
        self.assertEqual([sc["kind"] for sc in res["scenes"]], ["text_card", "stat_card", "image"])

    def test_scene_store_keeps_hook_fields(self):
        plan = scene_store.build_plan({"topic": "t", "aspect_ratio": "9:16", "hook_text": "훅", "end_tag_text": "끝",
                                       "scenes": [{"scene_num": 1, "narration": "n"}]})
        self.assertEqual((plan["hook_text"], plan["end_tag_text"], plan["end_tag_subtext"]), ("훅", "끝", ""))


if __name__ == "__main__":
    unittest.main()
