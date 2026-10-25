"""U-3 자막 그룹핑·강조어·전환 자동 배정."""

import unittest

import shorts_captions as sc
import shorts_engine

try:   # unittest discover -s tests 로 돌 때는 최상위 이름을 먼저 쓴다
    from test_shorts_engine import ShortsS2Base, _fake_merge, _fake_synth
except ImportError:
    from tests.test_shorts_engine import ShortsS2Base, _fake_merge, _fake_synth


def toks(spec, start=0, step=300, gap=12):
    """'가 나 다|라' → 어절 토큰. '|' 는 씬 끝(pageBreakAfter). '/' 는 300ms 쉼."""
    out, t, first = [], start, True
    for word in spec.split():
        pause = word.startswith("/")
        word = word.lstrip("/")
        if pause:
            t += 300
        end_scene = word.endswith("|")
        word = word.rstrip("|")
        out.append({"text": ("" if first else " ") + word, "startMs": t, "endMs": t + step})
        if end_scene:
            out[-1]["pageBreakAfter"] = True
        t += step + gap
        first = end_scene
    return out


def groups_text(captions, energy="normal"):
    line, cur = [], ""
    for c in sc.group_captions(captions, energy):
        cur += c["text"]
        if c.get("pageBreakAfter"):
            line.append(cur.strip())
            cur = ""
    if cur:
        line.append(cur.strip())
    return line


class GroupingTests(unittest.TestCase):
    def test_word_cap_by_energy(self):
        caps = toks("일 이 삼 사 오 육 칠 팔 구|")
        self.assertEqual(groups_text(caps), ["일 이 삼 사", "오 육 칠 팔 구"])        # 4어절, 마지막 외톨이 '구' 는 붙인다
        self.assertEqual(groups_text(caps, "high"), ["일 이 삼", "사 오 육", "칠 팔 구"])
        self.assertEqual(groups_text(caps, "calm"), ["일 이 삼 사 오", "육 칠 팔 구"])

    def test_breaks_on_pause_and_sentence_end(self):
        self.assertEqual(groups_text(toks("가 나 /다 라|")), ["가 나", "다 라"])
        self.assertEqual(groups_text(toks("가 나. 다 라|")), ["가 나.", "다 라"])

    def test_tail_attach_does_not_cross_scene(self):
        # 씬 첫 토큰은 앞 공백이 없다 — 외톨이 판단이 다음 씬으로 넘어가면 안 된다
        caps = toks("가 나 다 라 마|") + toks("바 사|", start=5000)
        self.assertEqual(groups_text(caps), ["가 나 다 라 마", "바 사"])

    def test_original_untouched_and_scene_ends_kept(self):
        caps = toks("가 나|") + toks("다 라|", start=2000)
        out = sc.group_captions(caps)
        self.assertNotIn("pageBreakAfter", caps[0])
        self.assertEqual([bool(c.get("pageBreakAfter")) for c in out], [False, True, False, True])

    def test_caption_groups_timing(self):
        caps = toks("가 나 다 라 /마 바|", start=20)
        g = sc.caption_groups(caps)
        self.assertEqual(g[0]["startMs"], sc.CAPTION_MIN_START_MS)               # 첫 자막은 150ms 뒤
        self.assertEqual(g[0]["hideMs"], min(g[0]["endMs"] + sc.CAPTION_HOLD_MS, g[1]["startMs"]))   # 쉼 뒤면 300ms 에 지움
        tight = sc.caption_groups(toks("일 이 삼 사 오 육 칠|"))
        self.assertEqual(tight[0]["hideMs"], tight[1]["startMs"])               # 바로 이어지면 다음 그룹 시작에 지움
        self.assertEqual(g[1]["hideMs"], g[1]["endMs"] + sc.CAPTION_HOLD_MS)     # 마지막은 300ms 뒤
        self.assertEqual([x["words"] for x in g], [4, 2])

    def test_empty(self):
        self.assertEqual(sc.group_captions([]), [])
        self.assertEqual(sc.caption_groups([]), [])


class EmphasisTests(unittest.TestCase):
    def test_number_emphasis(self):
        self.assertEqual(sc.number_emphasis("공간 추론 시험에서 87퍼센트. 앞섰습니다."), "87퍼센트")
        self.assertEqual(sc.number_emphasis("숫자 없는 문장"), "")

    def test_pick_prefers_valid_llm_then_number_then_none(self):
        scenes = [{"narration": "구글 제미나이 아르곤이 87퍼센트를 기록했습니다."},
                  {"narration": "성공률이 56에서 75로 올랐습니다."},
                  {"narration": "로봇 시대가 왔습니다."},
                  {"narration": "이미 정한 씬", "emphasis": "정한"}]
        sc.pick_emphasis_words(scenes, llm=lambda ns: ["제미나이", "없는단어", ""])
        self.assertEqual((scenes[0]["emphasis"], scenes[0]["emphasis_source"]), ("제미나이", "llm"))
        self.assertEqual((scenes[1]["emphasis"], scenes[1]["emphasis_source"]), ("56에서", "number"))   # 대본에 없는 답은 버림
        self.assertEqual((scenes[2]["emphasis"], scenes[2]["emphasis_source"]), ("", "none"))
        self.assertEqual(scenes[3]["emphasis"], "정한")                                                 # 이미 있는 건 그대로
        self.assertNotIn("emphasis_source", scenes[3])

    def test_llm_failure_falls_back(self):
        def boom(_):
            raise RuntimeError("llm down")
        scenes = [{"narration": "레고는 17초로 줄었습니다."}]
        sc.pick_emphasis_words(scenes, llm=boom)
        self.assertEqual((scenes[0]["emphasis"], scenes[0]["emphasis_source"]), ("17초로", "number"))

    def test_mark_emphasis_within_scene_window(self):
        caps = toks("가 87퍼센트 다|") + toks("87퍼센트 마|", start=3000)
        scenes = [{"seconds": 2.0, "emphasis": "87퍼센트"}, {"seconds": 2.0, "emphasis": ""}]
        out = sc.mark_emphasis(caps, scenes)
        self.assertEqual([bool(c.get("emphasis")) for c in out], [False, True, False, False, False])


class AssignTransitionsTests(ShortsS2Base):
    def make_job(self, kinds):
        plan = self.save_plan(n=len(kinds))
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        for s, k in zip(job["storyboard"]["scenes"], kinds):
            s["kind"] = k
            s.pop("transition", None)
            s.pop("transition_auto", None)
        return job

    def test_rules(self):
        job = self.make_job(["text_card", "text_card", "image", "bar_chart", "compare", "compare"])
        seams = shorts_engine.assign_transitions(job)
        self.assertEqual(len(seams), 5)
        self.assertIn(seams[0], ("color_flood", "dip"))           # 같은 종류가 이어짐
        self.assertEqual(seams[1], "zoom_through")                # 이미지로 들어감
        self.assertIn(seams[4], ("color_flood", "dip"))
        self.assertTrue(all(a != b for a, b in zip(seams, seams[1:])))   # 연속 같은 전환 없음
        self.assertGreaterEqual(len(set(seams)), 3)
        self.assertNotIn("none", seams)                           # 자동 배정은 하드컷을 쓰지 않는다
        self.assertTrue(all(s["transition_auto"] for s in job["storyboard"]["scenes"][1:]))

    def test_user_choice_respected_and_auto_reassigned(self):
        job = self.make_job(["text_card", "stat_card", "compare"])
        job["storyboard"]["scenes"][1]["transition"] = "wipe"     # 사용자가 고름
        seams = shorts_engine.assign_transitions(job)
        self.assertEqual(seams[0], "wipe")
        self.assertNotEqual(seams[1], "wipe")
        job["storyboard"]["scenes"][2]["kind"] = "image"          # 씬 종류가 바뀌면 자동 배정만 다시
        self.assertEqual(shorts_engine.assign_transitions(job), ["wipe", "zoom_through"])

    def test_job_lint_has_no_repetition_after_assign(self):
        job = self.make_job(["image"] * 5)
        shorts_engine.assign_transitions(job)
        lint = shorts_engine.refresh_lint(job)
        self.assertFalse([f for f in lint["findings"] if f["code"] == "repetition" and "전환" in f["message"]])

    def test_props_group_captions_and_emphasis(self):
        plan = self.save_plan(n=2)
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        job["storyboard"]["scenes"][0]["narration"] = "배터리 수명은 15년 입니다 정말 오래 갑니다"
        job = shorts_engine.synthesize_job_audio(job, synth=_fake_synth(True, 6.0), merger=_fake_merge, bgm_picker=lambda tid: None)
        shorts_engine.ensure_emphasis(job, llm=lambda ns: [])
        for s in job["storyboard"]["scenes"]:
            s["kind"], s["title"] = "text_card", "제목"
        props = shorts_engine.build_remotion_props(job)
        self.assertEqual(props["captionPageMs"], sc.GROUPED_PAGE_MS)
        self.assertEqual(props["captionHoldMs"], sc.CAPTION_HOLD_MS)
        self.assertEqual(props["captionMinStartMs"], sc.CAPTION_MIN_START_MS)
        self.assertEqual([c["text"].strip() for c in props["captions"] if c.get("emphasis")][:1], ["15년"])
        self.assertTrue(any(c.get("pageBreakAfter") for c in props["captions"]))
        self.assertEqual(len(job["captions"]), len(props["captions"]))        # 저장된 자막은 그대로, props 만 그룹핑

    def test_build_job_fills_emphasis_with_hook(self):
        plan = self.save_plan(n=2)
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        for s in job["storyboard"]["scenes"]:
            s["kind"], s["title"] = "text_card", "제목"
        shorts_engine.build_job(job, options={}, synth=_fake_synth(True, 5.0), merger=_fake_merge, bgm_picker=lambda tid: None,
                                renderer_fn=lambda job, renderer=None, progress_cb=None: None, measurer=lambda p: None,
                                qc_kwargs={"probe": {}, "brightness": 50}, emphasis_llm=lambda ns: ["핵심", "내용입니다"])
        sources = [s.get("emphasis_source") for s in job["storyboard"]["scenes"]]
        self.assertEqual(sources, ["llm", "llm"])


if __name__ == "__main__":
    unittest.main()
