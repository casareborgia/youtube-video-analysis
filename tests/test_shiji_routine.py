import importlib.util
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

_spec = importlib.util.spec_from_file_location("shiji_routine", os.path.join(BASE, "scripts", "shiji_routine.py"))
routine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(routine)

CH = routine.SHIJI_CHANNEL_ID


def job(sid, video_id=None, channel=CH, posted=False, pending="Original text", render=None, status="draft"):
    yt = {"video_id": video_id, "channel_id": channel, "comment_posted": posted, "comment_pending": pending}
    return {"shorts_id": sid, "concept_key": "shorts_shiji", "status": status,
            "publish": {"youtube": yt}, "render": render or {}}


class PendingCommentTest(unittest.TestCase):
    def test_only_uploaded_shiji_jobs_with_pending_comment(self):
        jobs = [job("a", "v1"), job("b"), job("c", "v3", posted=True), job("d", "v4", channel="UCother"),
                job("e", "v5", pending=None)]
        self.assertEqual([j["shorts_id"] for j in routine.pending_comment_jobs(jobs)], ["a"])


class UnrenderedTest(unittest.TestCase):
    def test_skips_uploaded_rendered_and_building(self):
        jobs = [job("new"), job("up", "v1"), job("done", render={"file": "/x.mp4"}),
                job("busy", status="assets"), job("busy2", status="rendering")]
        self.assertEqual([j["shorts_id"] for j in routine.unrendered_jobs(jobs)], ["new"])


if __name__ == "__main__":
    unittest.main()
