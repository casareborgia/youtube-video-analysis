"""한국어 내레이션 Shiji 편 — 자막 트랙 언어, 설명 꼬리, 출전 줄, 원문 댓글이 한국어로 나가는지 (2026-11-28 한국어판 시험)."""

from unittest.mock import patch

import shorts_engine
import shorts_publish
import uploader

try:   # unittest discover -s tests 로 돌 때는 같은 모듈을 다시 import 하지 않도록 최상위 이름을 먼저 쓴다
    from test_shorts_publish import PublishBase, SHIJI
except ImportError:
    from tests.test_shorts_publish import PublishBase, SHIJI

KO_SOURCE = "사기 (기원전 94년경) 권92"


class KoreanNarrationBase(PublishBase):
    def ko_job(self):
        job = self.make_job(seal_source=KO_SOURCE, language="korean")
        job["language"] = "korean"
        job["metadata"]["youtube"].update(title="강을 등지고 진을 친 장군 #Shorts", description="한신은 군사 만 명을 강을 등지고 세웠습니다.")
        for s in job["storyboard"]["scenes"]:
            if s["kind"] == "seal":
                s.update(hanzi="陷之死地而後生", translation="죽을 땅에 빠뜨려야 산다.")
        job["captions"] = [{"text": "한신은", "startMs": 100, "endMs": 500}, {"text": " 웃었다.", "startMs": 500, "endMs": 1100, "pageBreakAfter": True}]
        return job


class KoreanMetadataTests(KoreanNarrationBase):
    def test_description_tail_and_tags_are_korean(self):
        meta = shorts_publish.build_youtube_metadata(self.ko_job())
        desc = meta["description"]
        self.assertTrue(desc.startswith("한신은 군사 만 명을 강을 등지고 세웠습니다."))
        self.assertEqual(desc.count(f"📜 출전: {KO_SOURCE}"), 1)
        self.assertIn("원문: Kanseki Repository (Kanripo), CC BY-SA 4.0", desc)   # 출처 표시(라이선스)는 그대로 남긴다
        self.assertIn("번역: Shiji Files", desc)
        self.assertIn("#고사성어", desc)
        for english in ("Source:", "Original text:", "Translation:", "#ancientchina"):
            self.assertNotIn(english, desc)
        self.assertEqual((meta["default_language"], meta["audio_language"]), ("ko", "ko"))
        self.assertIn("사기", meta["tags"])
        self.assertNotIn("ancient china", meta["tags"])

    def test_english_job_is_unchanged(self):
        meta = shorts_publish.build_youtube_metadata(self.make_job())
        self.assertIn("📜 Source: Shiji, ch. 85", meta["description"])
        self.assertIn("ancient china", meta["tags"])
        self.assertNotIn("출전", meta["description"])


class KoreanCaptionTrackTests(KoreanNarrationBase):
    def test_spoken_captions_go_up_as_korean_only(self):
        self.fake_upload()
        job = self.ko_job()
        job["storyboard"]["scenes"][0]["narration_ko"] = "한신은 웃었다."   # 번역 칸이 남아 있어도 같은 언어를 두 번 올리지 않는다
        with patch.object(uploader, "upload_caption", return_value={"id": "cap"}) as cap, \
             patch.object(uploader, "set_video_localizations", return_value={}) as loc:
            job = shorts_publish.publish_youtube(job, channel_id=SHIJI)
        self.assertEqual([(c.kwargs["language"], c.kwargs["name"]) for c in cap.call_args_list], [("ko", "한국어")])
        self.assertEqual(job["publish"]["youtube"]["captions"], ["ko"])
        loc.assert_not_called()
        with open(cap.call_args.args[1], encoding="utf-8") as f:
            self.assertIn("한신은 웃었다.", f.read())


class KoreanSourceLineTests(KoreanNarrationBase):
    def test_source_line_and_comment_are_korean(self):
        job = self.ko_job()
        self.assertEqual(shorts_engine.source_line(job), f"출전: {KO_SOURCE}")
        text = shorts_publish.original_text_comment(job)
        self.assertIn(f"원문, {KO_SOURCE}: 陷之死地而後生", text)
        self.assertIn('"죽을 땅에 빠뜨려야 산다."', text)
        self.assertIn("Kanseki Repository (Kanripo), CC BY-SA 4.0", text)
        self.assertNotIn("Original text", text)

    def test_english_source_line_is_unchanged(self):
        self.assertEqual(shorts_engine.source_line(self.make_job(seal_source="Shiji (c. 94 BC), ch. 85")), "From the Shiji (c. 94 BC), ch. 85")
