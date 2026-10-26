"""방향 재검토 반영 — 원문 댓글(공개 전환 때 등록)과 이미지 장면 출전 표시줄 (2026-10-27)."""

import os
import re
import unittest
from unittest.mock import MagicMock, patch

import shorts_engine
import shorts_publish
import uploader

try:   # unittest discover -s tests 로 돌 때는 같은 모듈을 다시 import 하지 않도록 최상위 이름을 먼저 쓴다
    from test_shorts_publish import PublishBase, SHIJI
except ImportError:
    from tests.test_shorts_publish import PublishBase, SHIJI

TSX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "remotion", "src", "ShortsScene.tsx")


class CommentTextTests(PublishBase):
    def test_comment_from_seal_scenes(self):
        job = self.make_job(seal_source="Shiji (c. 94 BC), ch. 85")
        text = shorts_publish.original_text_comment(job)
        self.assertIn("Original text, Shiji (c. 94 BC), ch. 85: 此奇貨可居", text)
        self.assertIn('"Rare goods."', text)
        self.assertEqual(text.count("此奇貨可居"), 1)   # 같은 인장은 한 번
        self.assertIn("Kanseki Repository (Kanripo), CC BY-SA 4.0", text)

    def test_plan_comment_wins(self):
        job = self.make_job()
        job["metadata"]["youtube"]["pinned_comment"] = "Custom original text comment."
        self.assertEqual(shorts_publish.original_text_comment(job), "Custom original text comment.")

    def test_generic_job_without_seal_has_no_comment(self):
        job = self.make_job(concept="shorts_info", language="korean")
        for s in job["storyboard"]["scenes"]:
            s["kind"] = "image"
        self.assertEqual(shorts_publish.original_text_comment(job), "")


class CommentFlowTests(PublishBase):
    def test_upload_keeps_comment_pending_not_posted(self):
        up = self.fake_upload()
        job = shorts_publish.publish_youtube(self.make_job(), channel_id=SHIJI)
        self.assertIsNone(up.call_args.kwargs.get("pinned_comment"))   # 비공개 영상에는 댓글을 달 수 없다(403)
        yt = job["publish"]["youtube"]
        self.assertIn("此奇貨可居", yt["comment_pending"])
        self.assertFalse(yt.get("comment_posted"))

    def test_going_public_posts_comment_once(self):
        self.fake_upload()
        job = shorts_publish.publish_youtube(self.make_job(), channel_id=SHIJI)
        with patch.object(uploader, "set_video_privacy", return_value={"privacy": "public"}), \
             patch.object(uploader, "post_comment", return_value={"ok": True}) as pc:
            job = shorts_publish.set_youtube_privacy(job, "public")
            job = shorts_publish.set_youtube_privacy(job, "public")
        pc.assert_called_once()
        self.assertEqual(pc.call_args.args[0], "vid123")
        self.assertIn("此奇貨可居", pc.call_args.args[1])
        self.assertEqual(pc.call_args.kwargs["channel_id"], SHIJI)
        yt = job["publish"]["youtube"]
        self.assertTrue(yt["comment_posted"])
        self.assertIn("studio.youtube.com/video/vid123/comments", yt["studio_comment_url"])

    def test_comment_failure_does_not_undo_public(self):
        self.fake_upload()
        job = shorts_publish.publish_youtube(self.make_job(), channel_id=SHIJI)
        with patch.object(uploader, "set_video_privacy", return_value={"privacy": "public"}), \
             patch.object(uploader, "post_comment", side_effect=RuntimeError("quota")):
            job = shorts_publish.set_youtube_privacy(job, "public")
        yt = job["publish"]["youtube"]
        self.assertEqual(yt["privacy"], "public")
        self.assertFalse(yt["comment_posted"])
        self.assertTrue(any("quota" in w for w in yt["warnings"]))

    def test_unlisted_does_not_post(self):
        self.fake_upload()
        job = shorts_publish.publish_youtube(self.make_job(), channel_id=SHIJI)
        with patch.object(uploader, "set_video_privacy", return_value={"privacy": "unlisted"}), \
             patch.object(uploader, "post_comment") as pc:
            shorts_publish.set_youtube_privacy(job, "unlisted")
        pc.assert_not_called()

    def test_post_original_comment_for_already_public_video(self):
        # 손무 편처럼 이 기능 전에 공개된 영상에 나중에 단다
        self.fake_upload()
        job = shorts_publish.publish_youtube(self.make_job(), channel_id=SHIJI)
        job["publish"]["youtube"]["privacy"] = "public"
        job["publish"]["youtube"].pop("comment_pending", None)
        with patch.object(uploader, "post_comment", return_value={"ok": True}) as pc:
            job = shorts_publish.post_original_comment(job)
        pc.assert_called_once()
        self.assertTrue(job["publish"]["youtube"]["comment_posted"])
        with self.assertRaises(shorts_publish.PublishRefused):
            shorts_publish.post_original_comment(job)   # 두 번 달지 않는다

    def test_post_original_comment_refuses_private(self):
        self.fake_upload()
        job = shorts_publish.publish_youtube(self.make_job(), channel_id=SHIJI)
        with self.assertRaises(shorts_publish.PublishRefused):
            shorts_publish.post_original_comment(job)


class SourceLineTests(PublishBase):
    def props(self, job):
        job["audio"] = {}
        job["captions"] = []
        for s in job["storyboard"]["scenes"]:
            if s["kind"] == "image":
                s["image"] = job["render"]["file"]
        return shorts_engine.build_remotion_props(job)

    def test_shiji_props_get_source_line_from_first_seal(self):
        job = self.make_job(seal_source="Shiji (c. 94 BC), ch. 85")
        with patch.object(shorts_engine, "_ensure_in_job_dir", side_effect=lambda sid, p, prefix: p):
            props = self.props(job)
        self.assertEqual(props["sourceLine"], "From the Shiji (c. 94 BC), ch. 85")

    def test_explicit_source_line_and_generic_none(self):
        job = self.make_job()
        job["source_line"] = "From the Zhanguo ce, §107"
        with patch.object(shorts_engine, "_ensure_in_job_dir", side_effect=lambda sid, p, prefix: p):
            self.assertEqual(self.props(job)["sourceLine"], "From the Zhanguo ce, §107")
            generic = self.make_job(concept="shorts_info")
            for s in generic["storyboard"]["scenes"]:
                s["kind"] = "image"
            self.assertIsNone(self.props(generic)["sourceLine"])

    def test_remotion_accepts_source_line(self):
        src = open(TSX, encoding="utf-8").read()
        self.assertRegex(src, r"sourceLine\?: string \| null")
        self.assertIn("SourceLine", src)


if __name__ == "__main__":
    unittest.main()
