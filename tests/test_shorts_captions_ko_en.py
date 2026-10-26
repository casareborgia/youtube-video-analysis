"""영어·한국어 자막 트랙과 한국어 제목·설명 (2026-10-27 사용자 결정: 한국어 음성판은 보류, 자막·다국어 제목부터)."""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import concept_packs
import scene_store
import shorts_engine
import shorts_publish
import uploader

try:   # unittest discover -s tests 로 돌 때는 같은 모듈을 다시 import 하지 않도록 최상위 이름을 먼저 쓴다
    from test_shorts_publish import PublishBase, SHIJI
    from test_shorts_engine import ShortsS2Base
except ImportError:
    from tests.test_shorts_publish import PublishBase, SHIJI
    from tests.test_shorts_engine import ShortsS2Base


def with_timing(job):
    """실제 빌드 뒤처럼 씬 길이와 어절 자막 토큰을 채운다."""
    secs = [5.0, 6.0, 7.0]
    for s, sec, ko in zip(job["storyboard"]["scenes"], secs, ["상인이 왕자를 보았다.", "이것은 사 둘 만한 진귀한 물건이다.", "같은 말."]):
        s["seconds"] = sec
        s["narration_ko"] = ko
    job["captions"] = [
        {"text": "A", "startMs": 100, "endMs": 300}, {"text": " merchant.", "startMs": 300, "endMs": 900, "pageBreakAfter": True},
        {"text": "Rare", "startMs": 5200, "endMs": 5600}, {"text": " goods.", "startMs": 5600, "endMs": 6100, "pageBreakAfter": True},
    ]
    job["metadata"]["youtube"].update(title_ko="제국을 산 상인", description_ko="볼모 왕자에게 전 재산을 건 상인 이야기.")
    return job


class SrtTests(PublishBase):
    def test_english_srt_from_word_captions(self):
        job = with_timing(self.make_job())
        path = os.path.join(self.tmp, "en.srt")
        shorts_publish.build_srt_en(job, path)
        text = open(path, encoding="utf-8").read()
        self.assertIn("00:00:00,100 --> 00:00:00,900\nA merchant.", text)
        self.assertIn("00:00:05,200 --> 00:00:06,100\nRare goods.", text)

    def test_korean_srt_follows_scene_windows(self):
        job = with_timing(self.make_job())
        path = os.path.join(self.tmp, "ko.srt")
        n = shorts_publish.build_srt_ko(job, path)
        text = open(path, encoding="utf-8").read()
        self.assertEqual(n, 3)
        self.assertIn("00:00:00,000 --> 00:00:05,000\n상인이 왕자를 보았다.", text)
        self.assertIn("00:00:05,000 --> 00:00:11,000\n이것은 사 둘 만한 진귀한 물건이다.", text)
        self.assertIn("00:00:11,000 --> 00:00:18,000\n같은 말.", text)

    def test_no_korean_text_no_track(self):
        job = self.make_job()
        self.assertEqual(shorts_publish.build_srt_ko(job, os.path.join(self.tmp, "ko.srt")), 0)

    def test_korean_localization(self):
        loc = shorts_publish.korean_localization(with_timing(self.make_job()))
        self.assertEqual(loc["title"], "제국을 산 상인 #Shorts")
        self.assertTrue(loc["description"].startswith("볼모 왕자에게 전 재산을 건 상인 이야기."))
        self.assertIn("📜 Source: Shiji, ch. 85", loc["description"])
        self.assertIn("Kanripo", loc["description"])
        self.assertIsNone(shorts_publish.korean_localization(self.make_job()))   # 한국어 제목이 없으면 없음


class PublishLanguagesTests(PublishBase):
    def test_publish_uploads_both_tracks_and_korean_title(self):
        self.fake_upload()
        with patch.object(uploader, "upload_caption", return_value={"id": "cap"}) as cap, \
             patch.object(uploader, "set_video_localizations", return_value={"ko": {}}) as loc:
            job = shorts_publish.publish_youtube(with_timing(self.make_job()), channel_id=SHIJI)
        langs = sorted(c.kwargs["language"] for c in cap.call_args_list)
        self.assertEqual(langs, ["en", "ko"])
        for c in cap.call_args_list:
            self.assertEqual((c.args[0], c.kwargs["channel_id"]), ("vid123", SHIJI))
            self.assertTrue(os.path.exists(c.args[1]))
        self.assertEqual(loc.call_args.args[1]["ko"]["title"], "제국을 산 상인 #Shorts")
        yt = job["publish"]["youtube"]
        self.assertEqual(sorted(yt["captions"]), ["en", "ko"])
        self.assertTrue(yt["localizations"]["ko"])

    def test_caption_failure_keeps_upload(self):
        self.fake_upload()
        with patch.object(uploader, "upload_caption", side_effect=RuntimeError("quota")), \
             patch.object(uploader, "set_video_localizations", return_value={}):
            job = shorts_publish.publish_youtube(with_timing(self.make_job()), channel_id=SHIJI)
        yt = job["publish"]["youtube"]
        self.assertEqual(yt["video_id"], "vid123")
        self.assertTrue(any("quota" in w for w in yt["warnings"]))

    def test_add_languages_later_and_only_missing(self):
        self.fake_upload()
        job = with_timing(self.make_job())
        saved = [s.pop("narration_ko") for s in job["storyboard"]["scenes"]]   # 한국어 번역 없이 올림 → 영어만
        title_ko = job["metadata"]["youtube"].pop("title_ko")
        with patch.object(uploader, "upload_caption", return_value={"id": "c"}), \
             patch.object(uploader, "set_video_localizations", return_value={}):
            job = shorts_publish.publish_youtube(job, channel_id=SHIJI)
        self.assertEqual(sorted(job["publish"]["youtube"]["captions"]), ["en"])
        for s, ko in zip(job["storyboard"]["scenes"], saved):
            s["narration_ko"] = ko
        job["metadata"]["youtube"]["title_ko"] = title_ko
        with patch.object(uploader, "upload_caption", return_value={"id": "c"}) as cap, \
             patch.object(uploader, "set_video_localizations", return_value={}) as loc:
            job = shorts_publish.add_languages(job)
        self.assertEqual([c.kwargs["language"] for c in cap.call_args_list], ["ko"])   # 이미 있는 영어는 다시 올리지 않는다
        loc.assert_called_once()
        self.assertEqual(sorted(job["publish"]["youtube"]["captions"]), ["en", "ko"])

    def test_add_languages_needs_upload(self):
        with self.assertRaises(shorts_publish.PublishRefused):
            shorts_publish.add_languages(self.make_job())


class UploaderLanguageTests(unittest.TestCase):
    def test_upload_caption_body(self):
        yt = MagicMock()
        yt.captions.return_value.insert.return_value.execute.return_value = {"id": "cap1"}
        tmp = tempfile.NamedTemporaryFile(suffix=".srt", delete=False)
        tmp.write(b"1\n00:00:00,000 --> 00:00:01,000\nhi\n")
        tmp.close()
        self.addCleanup(os.remove, tmp.name)
        with patch.object(uploader, "_creds", return_value=object()), patch.object(uploader, "_service", return_value=yt), \
             patch("googleapiclient.http.MediaFileUpload", MagicMock()):
            res = uploader.upload_caption("v1", tmp.name, language="ko", name="한국어", channel_id=SHIJI)
        body = yt.captions.return_value.insert.call_args.kwargs["body"]
        self.assertEqual(body["snippet"], {"videoId": "v1", "language": "ko", "name": "한국어", "isDraft": False})
        self.assertEqual(res["id"], "cap1")

    def test_localizations_keep_snippet(self):
        yt = MagicMock()
        yt.videos.return_value.list.return_value.execute.return_value = {"items": [{
            "snippet": {"title": "T", "description": "D", "tags": ["a"], "categoryId": "27", "defaultLanguage": "en",
                        "defaultAudioLanguage": "en", "channelId": "x", "thumbnails": {}},
            "localizations": {"ja": {"title": "J", "description": "JD"}}}]}
        yt.videos.return_value.update.return_value.execute.return_value = {"localizations": {"ko": {}, "ja": {}}}
        with patch.object(uploader, "_creds", return_value=object()), patch.object(uploader, "_service", return_value=yt):
            uploader.set_video_localizations("v1", {"ko": {"title": "제목", "description": "설명"}}, channel_id=SHIJI)
        kw = yt.videos.return_value.update.call_args.kwargs
        self.assertEqual(kw["part"], "snippet,localizations")
        snip = kw["body"]["snippet"]
        self.assertEqual((snip["title"], snip["categoryId"], snip["tags"], snip["defaultLanguage"]), ("T", "27", ["a"], "en"))
        self.assertNotIn("channelId", snip)   # 읽기 전용 값은 보내지 않는다
        self.assertEqual(set(kw["body"]["localizations"]), {"ko", "ja"})   # 기존 언어는 유지


class PlanFieldTests(ShortsS2Base):
    def test_korean_fields_flow_from_plan_to_job(self):
        self.assertIn("narration_ko", concept_packs.shorts_spec("shorts_shiji")["scene_kind_fields"])
        self.assertEqual(set(scene_store.SHORTS_KIND_FIELDS), set(shorts_engine.SCENE_KIND_FIELDS))
        batch = {"topic": "X", "recommended_title": "X", "aspect_ratio": "9:16", "concept_key": "shorts_shiji",
                 "title_ko": "엑스", "description_ko": "설명",
                 "scenes": [{"scene_num": 1, "kind": "image", "narration": "A.", "narration_ko": "가.", "prompt_en": "p"}]}
        plan = scene_store.build_plan(batch, scene_seconds=5.0)
        scene_store.save_plan(plan)
        job = shorts_engine.build_job_from_plan(plan["plan_id"])
        self.assertEqual(job["storyboard"]["scenes"][0]["narration_ko"], "가.")
        self.assertEqual((job["metadata"]["youtube"]["title_ko"], job["metadata"]["youtube"]["description_ko"]), ("엑스", "설명"))


if __name__ == "__main__":
    unittest.main()
