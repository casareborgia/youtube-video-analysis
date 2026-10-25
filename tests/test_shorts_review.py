"""U-1 렌더 전 스토리보드 린트 (shorts_review) — 규칙 경계값·위험 점수·엔진/API 연결."""

import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import app as app_module
import shorts_engine
import shorts_review
try:   # unittest discover -s tests 로 돌 때는 같은 모듈을 다시 import 하지 않도록 최상위 이름을 먼저 쓴다
    from test_shorts_engine import ShortsS2Base
except ImportError:
    from tests.test_shorts_engine import ShortsS2Base


def _job(scenes, hook="로봇이 스스로 연습한다?", hook_seconds=3.0, end_tag=None, captions=None):
    return {
        "storyboard": {
            "hook_text": hook,
            "hook_seconds": hook_seconds,
            "scenes": [dict({"scene_num": i + 1}, **s) for i, s in enumerate(scenes)],
            "end_tag": end_tag if end_tag is not None else {"text": "구독하고 다음 편 보기", "subtext": "출처 · 채널", "seconds": 2.5},
        },
        "captions": captions or [],
        "caption_page_ms": 1200,
    }


def _codes(res, level=None):
    return [f["code"] for f in res["findings"] if level is None or f["level"] == level]


# 「Gemini 4 Argon」 잡(v3)과 같은 구성: 텍스트 2 · 막대 1 · 이미지 1 · 비교 2, 전환 지정 없음
ARGON_SCENES = [
    {"kind": "text_card", "seconds": 9.4, "title": "로봇이 스스로 연습한다", "subtitle": "Google · Gemini 4 Argon", "palette": 0,
     "narration": "로봇이 시뮬레이션에서 스스로 연습하고 실제로 움직입니다. 구글 제미나이 4 아르곤 이야기입니다."},
    {"kind": "bar_chart", "seconds": 8.6, "title": "ERQA 공간 추론 벤치마크", "palette": 1,
     "bars": [{"label": "Gemini 4 Argon", "value": 87}, {"label": "Claude Opus", "value": 80}, {"label": "GPT-6", "value": 78}],
     "narration": "공간 추론 시험 ERQA에서 87퍼센트. 클로드 오퍼스와 GPT-6보다 앞섰습니다."},
    {"kind": "image", "seconds": 7.0, "image": "x.png", "palette": 2, "narration": "보스턴다이내믹스 스팟은 세 다리로 균형을 잡았습니다."},
    {"kind": "text_card", "seconds": 6.9, "title": "영상 1편 · 손그림 1장 → 물리 시뮬레이션", "subtitle": "Real2Sim 디지털 트윈", "palette": 3,
     "narration": "영상 한 편, 손그림 한 장이면 물리 시뮬레이션 쌍둥이를 만들어 냅니다."},
    {"kind": "compare", "seconds": 9.9, "title": "시뮬레이션 데이터로 학습한 결과", "palette": 4,
     "rows": [{"label": "성공률", "from": 56, "to": 75}, {"label": "작업 시간", "from": 35, "to": 24}],
     "narration": "성공률이 56에서 75퍼센트로, 작업 시간은 35초에서 24초로 줄었습니다."},
    {"kind": "compare", "seconds": 9.1, "title": "LEGO 옮기기 · 세 번의 자기 개선", "palette": 5,
     "rows": [{"label": "소요 시간", "from": 59, "to": 17}],
     "narration": "레고 옮기기는 세 번 만에 59초에서 17초로. 로봇 시대, 어디까지 왔을까요?"},
]


class ArgonCaseTests(unittest.TestCase):
    def test_argon_lint_and_risk(self):
        # 실제 잡처럼 발화 내내 어절 자막이 깔린다(첫 토큰 98ms — 실제 Argon 잡 값)
        total_ms = int(sum(s["seconds"] for s in ARGON_SCENES) * 1000)
        caps = [{"text": "어절", "startMs": ms, "endMs": ms + 600} for ms in range(98, total_ms - 600, 700)]
        argon_tag = {"text": "구독하고 다음 AI 동향 보기", "subtext": "어사이드 AI 브리핑 · 출처 GeekNews", "seconds": 2.0}
        res = shorts_review.lint_storyboard(_job(ARGON_SCENES, captions=caps, end_tag=argon_tag))
        self.assertEqual(sorted(_codes(res)), ["caption_at_zero", "line_unread", "repetition", "typography_overreliance"])
        self.assertEqual(_codes(res, "P0"), ["line_unread"])               # 엔드 태그 2.0초 - 페이드인 0.33초 < 2초
        self.assertEqual(_codes(res, "P1"), ["typography_overreliance", "repetition"])
        self.assertEqual(res["counts"], {"P0": 1, "P1": 2, "P2": 1})
        risk = res["risk"]
        self.assertEqual(risk["axes"]["typography"]["score"], 4.0)      # 5/6 = 83% > 60%
        self.assertEqual(risk["axes"]["repetition"]["score"], 1.5)      # 전환 전부 fade
        self.assertEqual(risk["axes"]["motion"]["score"], 3.3)          # 움직이는 씬 1/6
        self.assertEqual(risk["axes"]["hook"]["score"], 0.0)            # 질문 훅
        self.assertEqual(risk["score"], 2.2)
        self.assertEqual(risk["verdict"], "acceptable")
        self.assertFalse(res["needs_confirm"])

    def test_findings_sorted_p0_first(self):
        scenes = [dict(s) for s in ARGON_SCENES]
        res = shorts_review.lint_storyboard(_job(scenes, end_tag={"text": "구독", "subtext": "", "seconds": 1.0}))
        self.assertEqual(res["findings"][0]["level"], "P0")
        levels = [f["level"] for f in res["findings"]]
        self.assertEqual(levels, sorted(levels))


class RuleBoundaryTests(unittest.TestCase):
    def _img(self, n, seconds=6.0):
        return [{"kind": "image", "seconds": seconds, "image": "a.png", "motion": "zoom_in", "narration": "가나다라마바사 아자차카."} for _ in range(n)]

    def test_hook_read_time_boundary(self):
        # 4어절: 0.5 + 0.3*4 = 1.7초
        ok = shorts_review.lint_storyboard(_job(self._img(3), hook="이거 모르면 정말 손해", hook_seconds=1.7))
        self.assertNotIn("line_unread", _codes(ok))
        bad = shorts_review.lint_storyboard(_job(self._img(3), hook="이거 모르면 정말 손해", hook_seconds=1.6))
        self.assertIn("line_unread", _codes(bad, "P0"))

    def test_symbol_tokens_not_counted(self):
        self.assertEqual(shorts_review._words("영상 1편 · 손그림 1장 → 물리"), 5)

    def test_card_read_time(self):
        # text_card 등장 0.87초 + 6어절 → 0.5+1.8 = 2.3초 필요 → 씬 3.0초면 가시 2.13초 < 2.3
        card = {"kind": "text_card", "seconds": 3.0, "title": "하나 둘 셋 넷", "subtitle": "다섯 여섯", "palette": 1, "narration": "짧다."}
        res = shorts_review.lint_storyboard(_job([card] + self._img(2)))
        self.assertIn("line_unread", _codes(res, "P0"))
        card["seconds"] = 3.3
        self.assertNotIn("line_unread", _codes(shorts_review.lint_storyboard(_job([card] + self._img(2)))))

    def test_end_tag_last_line_two_seconds(self):
        # 마지막 줄은 페이드인(10프레임)을 뺀 뒤 2초 이상 보여야 한다
        res = shorts_review.lint_storyboard(_job(self._img(3), end_tag={"text": "구독", "subtext": "아주 긴 출처 줄 하나 둘 셋 넷 다섯", "seconds": 2.3}))
        self.assertIn("line_unread", _codes(res, "P0"))
        res = shorts_review.lint_storyboard(_job(self._img(3), end_tag={"text": "구독", "subtext": "아주 긴 출처 줄 하나 둘 셋 넷 다섯", "seconds": 2.34}))
        self.assertNotIn("line_unread", _codes(res))   # 부제는 읽기 시간에 넣지 않는다

    def test_first_frame_empty(self):
        cards = [{"kind": "text_card", "seconds": 6, "title": "제목", "palette": i, "narration": "나레이션."} for i in range(3)]
        self.assertIn("first_frame_empty", _codes(shorts_review.lint_storyboard(_job(cards, hook="")), "P0"))
        self.assertNotIn("first_frame_empty", _codes(shorts_review.lint_storyboard(_job(self._img(3), hook=""))))
        self.assertNotIn("first_frame_empty", _codes(shorts_review.lint_storyboard(_job(cards))))

    def test_text_overflow(self):
        res = shorts_review.lint_storyboard(_job(self._img(3), hook="가" * 31))
        self.assertIn("text_overflow", _codes(res, "P1"))
        card = {"kind": "text_card", "seconds": 15, "title": "가" * 43, "palette": 1, "narration": "나레이션."}
        self.assertIn("text_overflow", _codes(shorts_review.lint_storyboard(_job([card] + self._img(2)))))

    def test_typography_thresholds(self):
        def cards(n_text, n_img):
            out = [{"kind": "stat_card", "seconds": 6, "value": i, "palette": i, "transition": ("slide" if i % 2 else "wipe"), "narration": "숫자."} for i in range(n_text)]
            return out + self._img(n_img)
        r60 = shorts_review.lint_storyboard(_job(cards(3, 2)))         # 60% → 지적 없음
        self.assertNotIn("typography_overreliance", _codes(r60))
        r67 = shorts_review.lint_storyboard(_job(cards(2, 1)))         # 67% → P1
        self.assertIn("typography_overreliance", _codes(r67, "P1"))
        r100 = shorts_review.lint_storyboard(_job(cards(3, 0)))        # 100% → P0
        self.assertIn("typography_overreliance", _codes(r100, "P0"))

    def test_dead_stretch_without_narration(self):
        card = {"kind": "text_card", "seconds": 6.0, "title": "제목", "palette": 1, "narration": ""}
        res = shorts_review.lint_storyboard(_job([card] + self._img(2)))
        self.assertIn("dead_stretch", _codes(res, "P1"))

    def test_dead_stretch_cleared_by_caption_pages(self):
        card = {"kind": "text_card", "seconds": 6.0, "title": "제목", "palette": 1, "narration": "말"}
        caps = [{"text": "말", "startMs": s, "endMs": s + 1000} for s in (300, 1600, 2900, 4200)]
        res = shorts_review.lint_storyboard(_job([card] + self._img(2), captions=caps))
        self.assertNotIn("dead_stretch", _codes(res))

    def test_moving_scenes_never_dead(self):
        res = shorts_review.lint_storyboard(_job(self._img(3, seconds=12.0)))
        self.assertNotIn("dead_stretch", _codes(res))

    def test_repetition_kind_run_and_transitions(self):
        scenes = [{"kind": "text_card", "seconds": 6, "title": "제목", "palette": i, "transition": t, "narration": "나레이션."}
                  for i, t in enumerate(["fade", "slide", "wipe"])] + self._img(1)
        res = shorts_review.lint_storyboard(_job(scenes))
        msgs = [f["message"] for f in res["findings"] if f["code"] == "repetition"]
        self.assertTrue(any("연속 3번 text_card" in m for m in msgs), msgs)
        scenes = self._img(4)
        for s, t in zip(scenes, ["fade", "slide", "slide", "wipe"]):
            s["transition"] = t
        res = shorts_review.lint_storyboard(_job(scenes))
        self.assertTrue(any("바로 앞과 같습니다" in f["message"] for f in res["findings"]))
        res = shorts_review.lint_storyboard(_job(self._img(4)))
        self.assertTrue(any("모두 같은 전환(fade)" in f["message"] for f in res["findings"]))

    def test_same_palette_all_cards(self):
        cards = [{"kind": k, "seconds": 6, "title": "제목", "palette": 2, "narration": "나레이션."} for k in ("text_card", "stat_card", "compare")]
        res = shorts_review.lint_storyboard(_job(cards))
        self.assertTrue(any("같은 팔레트" in f["message"] for f in res["findings"]))

    def test_screen_repeats_voice(self):
        card = {"kind": "text_card", "seconds": 8, "title": "배터리는 생각보다 오래 갑니다", "palette": 1,
                "narration": "놀랍게도 배터리는 생각보다 오래 갑니다. 십 년도 거뜬합니다."}
        res = shorts_review.lint_storyboard(_job([card] + self._img(2)))
        self.assertIn("screen_repeats_voice", _codes(res, "P1"))
        card["title"] = "수명 10년"
        self.assertNotIn("screen_repeats_voice", _codes(shorts_review.lint_storyboard(_job([card] + self._img(2)))))

    def test_generic_phrase(self):
        res = shorts_review.lint_storyboard(_job(self._img(2), hook="혁신적인 배터리의 비밀"))
        f = [x for x in res["findings"] if x["code"] == "generic_phrase"]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["level"], "P2")
        self.assertIn("혁신적", f[0]["message"])

    def test_caption_at_zero_boundary(self):
        caps = lambda ms: [{"text": "가", "startMs": ms, "endMs": ms + 400}]
        self.assertIn("caption_at_zero", _codes(shorts_review.lint_storyboard(_job(self._img(2), captions=caps(99)))))
        self.assertNotIn("caption_at_zero", _codes(shorts_review.lint_storyboard(_job(self._img(2), captions=caps(100)))))

    def test_risk_fail_needs_confirm(self):
        cards = [{"kind": "text_card", "seconds": 6, "title": "제목", "palette": i, "narration": "나레이션."} for i in range(4)]
        res = shorts_review.lint_storyboard(_job(cards, hook=""))
        self.assertEqual(res["risk"]["verdict"], "fail")
        self.assertGreaterEqual(res["risk"]["score"], 4.0)
        self.assertTrue(res["needs_confirm"])

    def test_empty_storyboard_does_not_crash(self):
        res = shorts_review.lint_storyboard({"storyboard": {"scenes": []}})
        self.assertIn("risk", res)


class EngineAndApiTests(ShortsS2Base):
    def test_job_carries_lint_and_refreshes_on_edit(self):
        plan = self.save_plan(n=3)
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        self.assertIn("lint", job)
        self.assertEqual(shorts_engine.load_job(job["shorts_id"])["lint"]["risk"]["axes"]["typography"]["score"], 0.0)
        job = shorts_engine.update_storyboard(job, scenes=[{"scene_num": n, "kind": "text_card", "title": f"제목 {n}"} for n in (1, 2, 3)])
        self.assertIn("typography_overreliance", _codes(job["lint"], "P0"))

    def test_lint_route_and_build_gate(self):
        client = TestClient(app_module.app)
        app_module._shorts_building.clear()
        plan = self.save_plan(n=4)
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        job = shorts_engine.update_storyboard(job, hook_text="", scenes=[{"scene_num": n, "kind": "text_card", "title": f"제목 {n}"} for n in (1, 2, 3, 4)])
        sid = job["shorts_id"]
        r = client.get(f"/api/shorts/jobs/{sid}/lint")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["lint"]["risk"]["verdict"], "fail")
        self.assertEqual(client.get("/api/shorts/jobs/bad!id/lint").status_code, 400)
        worker = MagicMock()
        with patch.object(app_module, "_run_shorts_build_worker", worker):
            r = client.post(f"/api/shorts/jobs/{sid}/build", json={})
            self.assertEqual(r.json()["status"], "lint_confirm_required")
            worker.assert_not_called()
            r = client.post(f"/api/shorts/jobs/{sid}/build", json={"confirm_lint": True})
            self.assertEqual(r.json()["status"], "started", r.text)
        worker.assert_called_once()
        app_module._shorts_building.clear()


if __name__ == "__main__":
    unittest.main()
