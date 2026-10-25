"""U-4 렌더 후 리뷰 — 확인 시트·전환 튐·검은 화면·약속 검사·발행 잠금."""

import os
import shutil
import subprocess
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

import app as app_module
import shorts_engine
import shorts_review

try:   # unittest discover -s tests 로 돌 때는 최상위 이름을 먼저 쓴다
    from test_shorts_engine import ShortsS2Base, _fake_merge, _fake_synth
except ImportError:
    from tests.test_shorts_engine import ShortsS2Base, _fake_merge, _fake_synth

FFMPEG = shutil.which("ffmpeg")


def _job(scene_secs, transitions=None, end_tag=0.0, render=None):
    scenes = [{"scene_num": i + 1, "seconds": s, "kind": "text_card", "title": "제목"} for i, s in enumerate(scene_secs)]
    for i, t in enumerate(transitions or []):
        scenes[i + 1]["transition"] = t
    return {"shorts_id": "rv_test", "format": "scene", "storyboard": {"scenes": scenes, "end_tag": {"text": "끝", "seconds": end_tag}},
            "render": render or {}}


def _make_video(path, filter_complex, seconds):
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=black:s=1080x1920:r=30:d={seconds}",
                    "-filter_complex", filter_complex, "-map", "[v]", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", path],
                   check=True)


class TimelineAndPromiseTests(unittest.TestCase):
    def test_timeline(self):
        tl = shorts_review.review_timeline(_job([4.0, 3.0, 5.0], ["whip", "dip"], end_tag=2.4))
        self.assertEqual(tl["starts"], [0.0, 4.0, 7.0])
        self.assertEqual([(s["t"], s["transition"]) for s in tl["seams"]], [(4.0, "whip"), (7.0, "dip")])
        self.assertEqual(tl["end_tag"], (12.0, 14.4))
        self.assertAlmostEqual(tl["total"], 14.4)

    def test_default_transition_is_fade(self):
        self.assertEqual(shorts_review.review_timeline(_job([3, 3]))["seams"][0]["transition"], "fade")

    def test_promise_downgrade_is_p0(self):
        job = _job([3, 3], render={"renderer_used": "ffmpeg", "fallback_reason": "RuntimeError: Remotion 미설치",
                                    "warnings": ["ffmpeg 폴백: 타이포·데이터 씬(1, 2)은 단색 배경으로 대체됩니다."]})
        res = shorts_review.review_render(job, None, "/nonexistent", "/data/shorts/rv_test")
        p0 = [f for f in res["findings"] if f["level"] == "P0"]
        self.assertEqual([f["code"] for f in p0], ["promise_downgraded"])
        self.assertIn("Remotion 미설치", p0[0]["message"])
        self.assertIn("단색", p0[0]["message"])
        self.assertTrue(res["needs_review"])
        self.assertEqual(res["promise"], "data_explainer")

    def test_remotion_render_has_no_promise_finding(self):
        res = shorts_review.review_render(_job([3, 3], render={"renderer_used": "remotion"}), None, "/x", "/u")
        self.assertFalse(res["needs_review"])
        self.assertEqual([f["code"] for f in res["findings"]], ["review_skipped"])   # ffmpeg 없음 → 시트만 못 만듦


@unittest.skipUnless(FFMPEG, "ffmpeg 필요")
class SheetAndSignalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _review(self, video, job):
        job["render"] = dict(job.get("render") or {}, file=video, renderer_used="remotion")
        return shorts_review.review_render(job, FFMPEG, os.path.join(self.tmp, "out"), "/data/shorts/rv_test")

    def test_three_sheets_and_fast(self):
        video = os.path.join(self.tmp, "v.mp4")
        # 밝기가 서서히 바뀌는 4초 영상(검은 화면 아님)
        _make_video(video, "[0:v]geq=lum='80+40*sin(2*PI*T)':cb=128:cr=128[v]", 4)
        t0 = time.time()
        res = self._review(video, _job([2.0, 2.0], ["fade"], end_tag=0.0))
        self.assertLess(time.time() - t0, 10.0)
        self.assertEqual(sorted(k for k, v in res["sheets"].items() if v), ["phone", "scenes", "seams"])
        for name in ("review_scenes.jpg", "review_seams.jpg", "review_phone.jpg"):
            self.assertTrue(os.path.getsize(os.path.join(self.tmp, "out", name)) > 0)
        self.assertEqual(res["sheets"]["phone"], "/data/shorts/rv_test/review_phone.jpg")
        self.assertEqual(res["counts"], {"P0": 0, "P1": 0, "P2": 0})

    def test_hard_cut_during_fade_is_seam_jump(self):
        video = os.path.join(self.tmp, "cut.mp4")
        # 2초에 검정 → 흰색으로 한 프레임에 바뀜
        _make_video(video, "[0:v]geq=lum='if(lt(T,2),20,235)':cb=128:cr=128[v]", 4)
        res = self._review(video, _job([2.0, 2.0], ["fade"]))
        self.assertIn("seam_jump", [f["code"] for f in res["findings"]])
        res = self._review(video, _job([2.0, 2.0], ["dip"]))            # 원래 컷인 전환은 검사하지 않는다
        self.assertNotIn("seam_jump", [f["code"] for f in res["findings"]])

    def test_gradual_change_is_not_jump(self):
        video = os.path.join(self.tmp, "fade.mp4")
        # 1.8~2.2초에 걸쳐 검정 → 흰색 (변화가 여러 프레임에 퍼짐)
        _make_video(video, "[0:v]geq=lum='20+215*clip((T-1.8)/0.4,0,1)':cb=128:cr=128[v]", 4)
        res = self._review(video, _job([2.0, 2.0], ["fade"]))
        self.assertNotIn("seam_jump", [f["code"] for f in res["findings"]])

    def test_black_frame(self):
        video = os.path.join(self.tmp, "black.mp4")
        _make_video(video, "[0:v]null[v]", 4)
        res = self._review(video, _job([2.0, 2.0], ["fade"]))
        self.assertIn("black_frame", [f["code"] for f in res["findings"]])


class EngineReviewTests(ShortsS2Base):
    def make_rendered_job(self, renderer_used="remotion"):
        plan = self.save_plan(n=2)
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        f = os.path.join(shorts_engine.job_dir(job["shorts_id"], create=True), shorts_engine.FINAL_NAME)
        with open(f, "wb") as fh:
            fh.write(b"mp4")
        job["render"] = {"file": f, "renderer_used": renderer_used}
        job["qc"] = {"passed": True, "checks": []}
        job["status"] = "qc_passed"
        if renderer_used == "ffmpeg":
            job["render"]["fallback_reason"] = "RuntimeError: Remotion 미설치"
        return job

    def test_run_review_locks_and_override_unlocks(self):
        job = shorts_engine.run_review(self.make_rendered_job("ffmpeg"))
        self.assertEqual(job["status"], "needs_review")
        ok, why = shorts_engine.publish_allowed(job)
        self.assertFalse(ok)
        self.assertIn("P0", why)
        with self.assertRaises(ValueError):
            shorts_engine.override_review(job, "짧음")
        job = shorts_engine.override_review(job, "폰트 서버 점검 중이라 이번만 진행")
        self.assertEqual(job["status"], "qc_passed")
        self.assertEqual(shorts_engine.publish_allowed(job), (True, ""))
        job = shorts_engine.run_review(job)                    # 다시 돌리면 진행 기록은 지운다
        self.assertEqual(job["status"], "needs_review")
        self.assertIsNone(job["review"]["override"])

    def test_publish_allowed_matrix(self):
        job = self.make_rendered_job()
        self.assertEqual(shorts_engine.publish_allowed(job), (False, "렌더 후 리뷰가 없습니다 — 리뷰를 먼저 돌리세요."))
        job = shorts_engine.run_review(job)
        self.assertEqual(job["status"], "qc_passed")
        self.assertEqual(shorts_engine.publish_allowed(job), (True, ""))
        job["qc"]["passed"] = False
        self.assertFalse(shorts_engine.publish_allowed(job)[0])
        with self.assertRaises(ValueError):
            shorts_engine.override_review(job, "검토 필요 상태가 아님")

    def test_build_job_runs_review_and_ffmpeg_fallback_needs_review(self):
        plan = self.save_plan(n=2)
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        for s in job["storyboard"]["scenes"]:
            s["kind"], s["title"] = "text_card", "제목"

        def fake_render(job, renderer=None, progress_cb=None):
            f = os.path.join(shorts_engine.job_dir(job["shorts_id"], create=True), shorts_engine.FINAL_NAME)
            with open(f, "wb") as fh:
                fh.write(b"mp4")
            job["render"] = {"file": f, "renderer_used": "ffmpeg", "fallback_reason": "RuntimeError: Failed to fetch",
                             "warnings": ["ffmpeg 폴백: 타이포·데이터 씬(1, 2)은 단색 배경으로 대체됩니다."]}
            return job

        probe = {"width": 1080, "height": 1920, "duration": 20.0, "audio_present": True, "audio_codec": "aac"}
        job = shorts_engine.build_job(job, options={}, synth=_fake_synth(True, 5.0), merger=_fake_merge, bgm_picker=lambda tid: None,
                                      renderer_fn=fake_render, measurer=lambda p: None, emphasis_llm=lambda ns: [],
                                      qc_kwargs={"probe": probe, "brightness": 50, "loudness": {"lufs": -18.0, "true_peak": -2.0}})
        self.assertTrue(job["qc"]["passed"])
        self.assertEqual(job["status"], "needs_review")
        self.assertEqual([f["code"] for f in job["review"]["findings"] if f["level"] == "P0"], ["promise_downgraded"])
        self.assertIn("검토 필요", job["progress"]["message"])

    def test_api_review_and_override(self):
        client = TestClient(app_module.app)
        app_module._shorts_building.clear()
        job = self.make_rendered_job("ffmpeg")
        shorts_engine.save_job(job)
        sid = job["shorts_id"]
        r = client.post(f"/api/shorts/jobs/{sid}/review")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["data"]["status"], "needs_review")
        self.assertEqual(client.post(f"/api/shorts/jobs/{sid}/review/override", json={"reason": "짧"}).status_code, 400)
        r = client.post(f"/api/shorts/jobs/{sid}/review/override", json={"reason": "확인했고 이번만 진행합니다"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["data"]["status"], "qc_passed")
        plan = self.save_plan(n=2, topic="렌더 없음")
        bare = shorts_engine.build_job_from_plan(plan["plan_id"])
        self.assertEqual(client.post(f"/api/shorts/jobs/{bare['shorts_id']}/review").status_code, 400)
        self.assertEqual(client.post("/api/shorts/jobs/bad!id/review").status_code, 400)


if __name__ == "__main__":
    unittest.main()
