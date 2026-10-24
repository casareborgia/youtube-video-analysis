"""예약 업로드 댓글 재등록 검증.

- 공개된 영상에만 댓글을 달고, 아직 비공개(예약)·삭제된 영상은 건너뛴다
- 채널 댓글이 이미 있으면 다시 달지 않는다 (중복 방지)
- 숏폼 댓글은 롱폼 링크 플레이스홀더를 채운 문구로 단다
- max_age_days 보다 오래된 업로드는 보지 않는다
- dry_run 은 등록·기록 변경을 하지 않는다
"""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import luna_engine


def _write(root, track):
    d = os.path.join(root, track["track_id"])
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(track, f, ensure_ascii=False)


class RetryPendingCommentsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        now = time.time()
        _write(self.root, {
            "track_id": "t_public", "uploaded_video_id": "LONG1", "uploaded_at": now - 3600,
            "comment_posted": False, "pinned_comment": "어떤 순간이 남으셨나요?", "playlist_id": "PL1",
            "metadata": {"shorts": {"pinned_comment": f"풀버전 👉 {luna_engine.LONGFORM_URL_PLACEHOLDER} 들어보세요."}},
            "shorts": {"youtube": {"video_id": "SHORT1", "comment_posted": False, "longform_video_id": "LONG1"}},
        })
        _write(self.root, {
            "track_id": "t_scheduled", "uploaded_video_id": "LONG2", "uploaded_at": now - 600,
            "comment_posted": False, "pinned_comment": "예약 영상 댓글입니다.",
        })
        _write(self.root, {
            "track_id": "t_old", "uploaded_video_id": "LONG3", "uploaded_at": now - 30 * 86400,
            "comment_posted": False, "pinned_comment": "오래된 영상 댓글입니다.",
        })
        _write(self.root, {
            "track_id": "t_done", "uploaded_video_id": "LONG4", "uploaded_at": now - 3600,
            "comment_posted": True, "pinned_comment": "이미 달린 댓글입니다.",
        })
        self.statuses = {"LONG1": {"privacy": "public"}, "SHORT1": {"privacy": "public"},
                         "LONG2": {"privacy": "private", "publish_at": "2099-01-01T12:00:00Z"}}
        self.patches = [patch.object(luna_engine, "LUNA_DIR", self.root),
                        patch.object(luna_engine.uploader, "get_video_statuses", side_effect=lambda ids: self.statuses)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def _load(self, tid):
        with open(os.path.join(self.root, tid, "meta.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_posts_only_public_and_marks_flags(self):
        with patch.object(luna_engine.uploader, "channel_has_own_comment", return_value=False), \
             patch.object(luna_engine.uploader, "post_comment", return_value=True) as post:
            res = luna_engine.retry_pending_comments(max_age_days=7)
        posted = {c.args[0]: c.args[1] for c in post.call_args_list}
        self.assertEqual(set(posted), {"LONG1", "SHORT1"})
        self.assertIn("https://youtu.be/LONG1", posted["SHORT1"])
        self.assertNotIn(luna_engine.LONGFORM_URL_PLACEHOLDER, posted["SHORT1"])
        self.assertEqual(res["posted"], 2)
        by_vid = {r["video_id"]: r for r in res["results"]}
        self.assertEqual(by_vid["LONG2"]["status"], "skipped")
        self.assertNotIn("LONG3", by_vid)   # max_age_days 밖
        self.assertNotIn("LONG4", by_vid)   # 이미 등록됨
        t = self._load("t_public")
        self.assertTrue(t["comment_posted"])
        self.assertTrue(t["shorts"]["youtube"]["comment_posted"])
        self.assertFalse(self._load("t_scheduled")["comment_posted"])

    def test_existing_channel_comment_is_not_duplicated(self):
        with patch.object(luna_engine.uploader, "channel_has_own_comment", return_value=True), \
             patch.object(luna_engine.uploader, "post_comment") as post:
            res = luna_engine.retry_pending_comments(max_age_days=7)
        post.assert_not_called()
        self.assertEqual(res["posted"], 0)
        self.assertTrue(self._load("t_public")["comment_posted"])

    def test_dry_run_changes_nothing(self):
        with patch.object(luna_engine.uploader, "channel_has_own_comment", return_value=False), \
             patch.object(luna_engine.uploader, "post_comment") as post:
            res = luna_engine.retry_pending_comments(max_age_days=7, dry_run=True)
        post.assert_not_called()
        self.assertEqual({r["status"] for r in res["results"] if r["video_id"] in ("LONG1", "SHORT1")}, {"would_post"})
        self.assertFalse(self._load("t_public")["comment_posted"])

    def test_deleted_video_is_skipped(self):
        self.statuses.pop("LONG1")
        with patch.object(luna_engine.uploader, "channel_has_own_comment", return_value=False), \
             patch.object(luna_engine.uploader, "post_comment") as post:
            res = luna_engine.retry_pending_comments(max_age_days=7)
        self.assertNotIn("LONG1", [c.args[0] for c in post.call_args_list])
        self.assertEqual({r["video_id"]: r for r in res["results"]}["LONG1"]["reason"], "삭제됨")

    def test_post_error_is_reported_and_flag_stays_false(self):
        with patch.object(luna_engine.uploader, "channel_has_own_comment", return_value=False), \
             patch.object(luna_engine.uploader, "post_comment", side_effect=RuntimeError("403")):
            res = luna_engine.retry_pending_comments(max_age_days=7)
        self.assertEqual({r["video_id"]: r for r in res["results"]}["LONG1"]["status"], "error")
        self.assertFalse(self._load("t_public")["comment_posted"])


if __name__ == "__main__":
    unittest.main()
